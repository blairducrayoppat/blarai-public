"""Production-posture RUNTIME guard (GAP-12 / #600) — Sprint 17 SDV C5.

WHY THIS FILE EXISTS — the dynamic complement to the static locks
=================================================================
``test_secure_defaults.py`` reads the shipped TOML and asserts the *file* still
declares ``dev_mode = false``.  That is a STATIC lock: it proves the config on
disk is secure, but it cannot prove that a boot in production posture actually
*resolves* ``dev_mode`` to ``False`` at runtime, nor that the production-only
fail-closed behaviours engage.  A regression that left the file correct but
short-circuited the resolution (an inverted override default, a stray
``BLARAI_DEV_MODE`` leak, a service ignoring ``dev_mode_override``) would sail
past the static lock and only surface at the LA's terminal.

This file is the DYNAMIC/runtime complement (GAP-12 in the Sprint-16 coverage
audit; ticket #600; SECURITY_ROADMAP §5.11).  It boots the system in PRODUCTION
posture through the REAL resolution chain the launcher uses and asserts:

  1. The launcher's own resolution chain
     (``resolve_dev_mode(HOST, dev_mode_override=resolve_dev_override())``)
     resolves ``False`` with no dev opt-in in the environment — this is the
     EXACT call at ``launcher/__main__.py`` ~:547.
  2. A Policy Agent constructed in production posture resolves a runtime
     entrypoint config with ``dev_mode is False`` (real shipped ``default.toml``,
     real ``_load_entrypoint_config`` — no TPM / model / cert files required,
     because the PA defers ``_validate_security_material`` to ``start()``).
  3. Production-only RUNTIME behaviours actually engage (the dynamic part the
     static lock cannot show):
       - the prompt-flow preflight is ON in production
         (``_prompt_flow_preflight_enabled(dev_mode=False) is True``);
       - the dev_mode/network_facing interlock admits the production combo;
       - the encrypted session store REFUSES TO START in production with no
         DEK keystore (``StoreProvisioningError``) — whereas dev mode succeeds
         with a SoftwareSealer.  This is a true runtime behavioural divergence
         between dev and production, not a config read.
       - the Assistant Orchestrator's production security-material gate fires
         (its ``_load_entrypoint_config`` runs ``_validate_security_material``
         in production and fail-closes when the Known-Good Manifest is absent),
         while the same construction in dev mode skips the gate and resolves
         ``dev_mode is False`` is *not* asserted there — dev resolves True.

TIERING (SDV §4 C5 / §8 gate-honesty)
=====================================
* ``TestProductionPostureRuntimeGuard`` — the GATE tier.  GREEN in the standing
  gate (no GPU, no TPM, no model files).  Every test EXECUTES its
  ``dev_mode is False`` / production-behaviour assertion; none is a skip-only
  shell.  These use the real shipped configs and the real resolution APIs with
  SoftwareSealer/stand-in material where security material is needed.
* ``TestProductionPostureFullBoot`` — the SLOW tier (``@pytest.mark.slow``,
  deselected by the gate's ``addopts``).  A REAL full production
  ``PolicyAgentService(...).start()`` that needs a provisioned TPM (JWT signing
  key + audit key) + a Known-Good Manifest.  Its first green run is the LA
  on-chip session (see "HOW TO RUN" on the class).  It must NOT be the only
  place the ``dev_mode=False`` assertion lives — the gate tier above carries the
  load-bearing runtime assertion.

ISOLATION
=========
The root ``conftest.py`` redirects ``LOCALAPPDATA`` / ``HOME`` / ``XDG_DATA_HOME``
to a throwaway temp dir at process startup and unsets ``BLARAI_DEK_KEYSTORE``.
Every test here additionally uses ``tmp_path`` only and scrubs the three
posture env vars (``BLARAI_DEV_MODE`` / ``BLARAI_NETWORK_FACING`` /
``BLARAI_DEK_KEYSTORE``) via monkeypatch so the assertions are deterministic
regardless of the launching shell.  No real user data is ever written.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

from launcher.__main__ import _prompt_flow_preflight_enabled
from services.assistant_orchestrator.src.entrypoint import AssistantOrchestratorService
from services.policy_agent.src.entrypoint import PolicyAgentService
from services.ui_gateway.src.session_store import StoreProvisioningError, build_session_store
from shared.runtime_config import (
    ConfigResolutionError,
    DeploymentMode,
    resolve_dev_override,
    resolve_network_facing,
)
from shared.security.dev_mode_guard import (
    DevModeNetworkFacingError,
    assert_dev_mode_network_facing_safe,
    resolve_dev_mode,
)

_REPO = Path(__file__).resolve().parents[2]
_AO_CONFIG = _REPO / "services/assistant_orchestrator/config/default.toml"
_PA_CONFIG = _REPO / "services/policy_agent/config/default.toml"

# The three environment knobs that can perturb the resolved posture.  Every test
# scrubs these so production is resolved from the mode default, not a leaked
# shell opt-in.
_POSTURE_ENV_VARS = (
    "BLARAI_DEV_MODE",        # dev opt-in (truthy → dev mode)
    "BLARAI_NETWORK_FACING",  # network-facing opt-in
    "BLARAI_DEK_KEYSTORE",    # production DEK keystore path
)


@pytest.fixture
def _clean_posture_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Remove the posture env vars so production is resolved from the default.

    The root conftest already unsets ``BLARAI_DEK_KEYSTORE``; this fixture makes
    all three explicit and local so a test is deterministic no matter what the
    launching shell exported.
    """
    for var in _POSTURE_ENV_VARS:
        monkeypatch.delenv(var, raising=False)


def _load_toml(path: Path) -> dict:
    with path.open("rb") as handle:
        return tomllib.load(handle)


# ---------------------------------------------------------------------------
# GATE tier — GREEN in the standing gate (no GPU / TPM / model files).
# Every test EXECUTES a runtime dev_mode=False / production-behaviour assertion.
# ---------------------------------------------------------------------------


class TestProductionPostureRuntimeGuard:
    """Runtime production-posture guard — the dynamic complement to the static
    secure-defaults locks.

    These tests assert the *resolved* posture and production-only *behaviours*,
    not the on-disk config (that is ``test_secure_defaults.py``'s job).  All run
    without hardware: the heaviest dependency is a SoftwareSealer-backed
    in-memory session store.
    """

    def test_launcher_resolution_chain_resolves_production(
        self, _clean_posture_env: None
    ) -> None:
        """The launcher's OWN resolution chain resolves dev_mode=False.

        This reproduces ``launcher/__main__.py`` ~:547 exactly:
        ``resolve_dev_mode(runtime_mode, dev_mode_override=resolve_dev_override())``
        with ``runtime_mode = HOST`` and no ``BLARAI_DEV_MODE`` in the env.  If a
        regression inverted the HOST default or made ``resolve_dev_override``
        return True spuriously, this fails — the dynamic catch the static config
        lock cannot provide.
        """
        # No dev opt-in in the environment → no override.
        assert resolve_dev_override() is None, (
            "resolve_dev_override() must return None when BLARAI_DEV_MODE is unset"
        )

        resolved = resolve_dev_mode(
            DeploymentMode.HOST,
            dev_mode_override=resolve_dev_override(),
        )
        assert resolved is False, (
            "Production HOST boot must resolve dev_mode=False at runtime "
            f"(launcher resolution chain); got {resolved!r}"
        )

        # GUEST also resolves production.
        assert (
            resolve_dev_mode(
                DeploymentMode.GUEST,
                dev_mode_override=resolve_dev_override(),
            )
            is False
        ), "Production GUEST boot must resolve dev_mode=False at runtime"

    def test_dev_opt_in_env_is_loud_and_explicit(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The ONLY way to leave production is the explicit BLARAI_DEV_MODE opt-in.

        Locks the escape-hatch contract: with the env var set truthy the chain
        resolves True (so the loud INSECURE banner fires); production is never
        reachable-to-dev silently.  This guards the negative space around the
        production default — proving False is the default *because* the opt-in is
        required, not by accident.
        """
        for var in _POSTURE_ENV_VARS:
            monkeypatch.delenv(var, raising=False)

        monkeypatch.setenv("BLARAI_DEV_MODE", "1")
        assert resolve_dev_override() is True
        assert (
            resolve_dev_mode(
                DeploymentMode.HOST,
                dev_mode_override=resolve_dev_override(),
            )
            is True
        ), "BLARAI_DEV_MODE=1 must resolve dev_mode=True (explicit, loud opt-in)"

        # A non-truthy value is NOT an opt-in — production stays the default.
        monkeypatch.setenv("BLARAI_DEV_MODE", "0")
        assert resolve_dev_override() is None
        assert (
            resolve_dev_mode(
                DeploymentMode.HOST,
                dev_mode_override=resolve_dev_override(),
            )
            is False
        ), "BLARAI_DEV_MODE=0 is not an opt-in; production (False) must stand"

    def test_policy_agent_resolves_dev_mode_false_at_runtime(
        self, _clean_posture_env: None
    ) -> None:
        """A PA constructed in production posture resolves dev_mode=False.

        Exercises the REAL ``from_runtime_mode`` + ``_load_entrypoint_config``
        path against the REAL shipped ``default.toml``.  The PA defers
        ``_validate_security_material`` to ``start()``, so config resolution
        succeeds without TPM/model files — letting us assert the *resolved*
        runtime ``dev_mode`` directly.  This is the heart of GAP-12 for the PA:
        not "the file says false" but "the running service resolved false".
        """
        service = PolicyAgentService.from_runtime_mode(
            "host",
            dev_mode_override=False,
        )
        resolved = service._load_entrypoint_config()
        assert resolved.dev_mode is False, (
            "PA production posture must resolve dev_mode=False at runtime; "
            f"got {resolved.dev_mode!r}"
        )
        assert resolved.deployment_mode == DeploymentMode.HOST

        # With NO override, the shipped config's own [security].dev_mode (false)
        # must carry through — i.e. production is the resolved default, not only
        # reachable via an explicit override=False.
        service_default = PolicyAgentService.from_runtime_mode("host")
        assert service_default._load_entrypoint_config().dev_mode is False, (
            "PA must resolve dev_mode=False from the shipped config with no override"
        )

    def test_policy_agent_dev_override_flips_runtime_resolution(
        self, _clean_posture_env: None
    ) -> None:
        """Control check: dev_mode_override=True flips the SAME runtime path to True.

        Proves the production assertion above is load-bearing — the resolution
        actually reads the override rather than always returning False (a bug
        that would make the production assertion pass vacuously).
        """
        service = PolicyAgentService.from_runtime_mode(
            "host",
            dev_mode_override=True,
        )
        assert service._load_entrypoint_config().dev_mode is True, (
            "dev_mode_override=True must resolve dev_mode=True — confirms the "
            "production-posture path is genuinely override-sensitive"
        )

    def test_prompt_flow_preflight_is_on_in_production(self) -> None:
        """A production-only RUNTIME behaviour engages: the prompt-flow preflight.

        ``_prompt_flow_preflight_enabled(dev_mode=False)`` is the launcher's
        Step-6b gate.  In production it is ON; in dev it is OFF.  This is the
        behavioural counterpart to the posture flag — production does not merely
        *say* it is production, it *runs* the production preflight.
        """
        assert _prompt_flow_preflight_enabled(dev_mode=False) is True, (
            "Prompt-flow preflight must be ON at runtime in production posture"
        )
        assert _prompt_flow_preflight_enabled(dev_mode=True) is False, (
            "Prompt-flow preflight must be OFF in dev posture (control check)"
        )

    def test_interlock_admits_production_combo(
        self, _clean_posture_env: None
    ) -> None:
        """The dev_mode/network_facing interlock admits the resolved production combo.

        With ``dev_mode=False`` and the air-gapped ``network_facing=False`` (the
        resolved default), the fail-closed interlock must NOT raise — a normal
        production boot proceeds.  This asserts the guard the launcher runs at
        ~:554 does not spuriously refuse production.
        """
        resolved_dev = resolve_dev_mode(
            DeploymentMode.HOST,
            dev_mode_override=resolve_dev_override(),
        )
        resolved_net = resolve_network_facing()
        assert resolved_dev is False
        assert resolved_net is False, (
            "Air-gapped production must resolve network_facing=False"
        )

        # Must not raise — the production combo is admitted.
        assert_dev_mode_network_facing_safe(
            dev_mode=resolved_dev,
            network_facing=resolved_net,
        )

        # And production + a (future) network-facing posture is the SAFE combo
        # the interlock exists to permit — dev_mode=False never trips it.
        assert_dev_mode_network_facing_safe(dev_mode=False, network_facing=True)

    def test_interlock_refuses_dev_plus_network_facing(self) -> None:
        """Control check: the interlock still refuses the insecure combo.

        Proves the interlock is a real fail-closed control (not a no-op that
        would make the production-admit assertion above meaningless): dev_mode +
        network_facing together MUST raise.
        """
        with pytest.raises(DevModeNetworkFacingError):
            assert_dev_mode_network_facing_safe(dev_mode=True, network_facing=True)

    def test_session_store_refuses_to_start_in_production_without_keystore(
        self, tmp_path: Path, _clean_posture_env: None
    ) -> None:
        """Production RUNTIME behaviour: the encrypted store refuses the dev fallback.

        This is the sharpest dynamic assertion in the file — a true *behavioural*
        divergence between dev and production that no static config read can show.
        In production posture (``dev_mode=False``) with no ``BLARAI_DEK_KEYSTORE``,
        ``build_session_store`` REFUSES TO START (``StoreProvisioningError``)
        rather than silently encrypting under the public SoftwareSealer key
        (ADR-025 §2.8(a)).  The conftest already unsets the keystore var; the
        fixture re-scrubs it for determinism.
        """
        db_path = str(tmp_path / "prod_posture_sessions.db")

        with pytest.raises(StoreProvisioningError):
            build_session_store(db_path, dev_mode=False)

        # The DB file must NOT have been created — refuse-to-start means no store.
        assert not Path(db_path).exists(), (
            "Production refuse-to-start must not create the session DB"
        )

    def test_session_store_dev_mode_succeeds_proving_divergence(
        self, tmp_path: Path, _clean_posture_env: None
    ) -> None:
        """Control check: the SAME call in dev posture succeeds (SoftwareSealer).

        Pairs with the refuse-to-start test to prove the divergence is driven by
        the runtime ``dev_mode`` flag, not by an unrelated failure.  Dev mode
        builds a usable SoftwareSealer-backed store; production refuses it.
        """
        db_path = str(tmp_path / "dev_posture_sessions.db")
        store = build_session_store(db_path, dev_mode=True)
        try:
            assert store is not None
            # has_encryption is the production-wiring invariant — even the dev
            # SoftwareSealer path is encrypted at rest.
            assert store.has_encryption is True
        finally:
            store.close()

    def test_assistant_orchestrator_production_security_gate_fires(
        self, tmp_path: Path, _clean_posture_env: None
    ) -> None:
        """Production RUNTIME behaviour: the AO security-material gate fail-closes.

        Unlike the PA, the AO's ``_load_entrypoint_config`` runs
        ``_validate_security_material`` inline.  In production posture
        (``dev_mode=False``) the gate requires the Known-Good Manifest to EXIST at
        the configured ``weight_manifest`` path; when it is absent the gate
        fail-closes with a ``ConfigResolutionError`` carrying an ``AO_CFG_KGM``
        code (``AO_CFG_KGM_PATH_NOT_FOUND``).  This proves the production security
        gate is genuinely engaged at runtime (a dev-mode construction skips it).

        Determinism note — the seam this guards.  The test config provides NO JWT
        CA public key (and no ``weight_manifest``), so ``_validate_security_material``
        always trips in production REGARDLESS of host — but the EXACT code is host-
        dependent, which is the whole lesson: on a provisioned dev machine the real
        manifest resolves present (the gate correctly accepts it under the staged-OFF
        ``require_signed_manifest=false``) so the gate trips on the absent JWT CA
        (``AO_CFG_JWT_CA_PATH_MISSING``); on a bare git worktree (no ``models/`` —
        weights aren't in git) it trips at the manifest (``AO_CFG_KGM_*``).  An
        earlier cut pinned the assertion to ``AO_CFG_KGM`` and built against the
        shipped ``default.toml`` via ``from_runtime_mode``; that passed in a worktree
        but FAILED on the dev machine.  Both codes are reachable ONLY past the
        ``dev_mode`` early-return, so EITHER proves the same GAP-12 invariant — the
        production security-material gate is engaged at runtime — and the test
        accepts either rather than the host-decided one.  A posture test must own
        the outcome it asserts, never the host's provisioning state.

        The fail-closed raise IS the production behaviour under test; it is the
        same control that refuses absent/unconfigured trust material in a real boot.
        """
        config_path = (
            tmp_path / "services" / "assistant_orchestrator" / "config" / "default.toml"
        )
        config_path.parent.mkdir(parents=True, exist_ok=True)
        # Identical to the dev-mode control config below EXCEPT dev_mode=false and
        # constructed with dev_mode_override=False — so the ONLY difference that can
        # explain a divergent outcome is the production posture itself.  The config
        # provides no JWT CA (and no manifest), so the production security-material
        # gate fail-closes on every host; dev mode skips the gate and resolves.
        config_path.write_text(
            """
[runtime]
deployment_mode = "host"

[gpu]
device = "GPU"
model_dir = "models/qwen3-14b/openvino-int4-gpu"
priority = 1

[generation]
max_new_tokens = 64
temperature = 0.0
top_k = 50
top_p = 0.9
repetition_penalty = 1.1
do_sample = false
response_depth_mode = "standard"

[security]
dev_mode = false

[ipc]
vsock_cid = 2
vsock_port = 5001
timeout_ms = 250
max_message_bytes = 65536

[pgov]
cosine_similarity_threshold = 0.85
pii_mode = "off"
leakage_detection_enabled = false
""".strip(),
            encoding="utf-8",
        )

        service = AssistantOrchestratorService(
            config_path,
            dev_mode_override=False,
            deployment_mode="host",
        )
        with pytest.raises(ConfigResolutionError) as exc_info:
            service._load_entrypoint_config()

        # The fail-closed code must be a PRODUCTION security-material gate code — a
        # Known-Good Manifest (AO_CFG_KGM_*) or JWT CA (AO_CFG_JWT_CA_*) check, both
        # reachable ONLY past the dev_mode early-return in _validate_security_material.
        # Either proves the production gate fired (not an unrelated config error);
        # dev mode skips the whole method (the control test below).
        code = exc_info.value.code
        assert code.startswith("AO_CFG_KGM") or code.startswith("AO_CFG_JWT_CA"), (
            "AO production posture must fail-closed at a security-material gate "
            f"(Known-Good Manifest or JWT CA public key); got code={code!r}"
        )

    def test_assistant_orchestrator_dev_mode_resolves_and_skips_gate(
        self, tmp_path: Path, _clean_posture_env: None
    ) -> None:
        """Control check: dev posture resolves dev_mode=True and SKIPS the gate.

        Confirms the AO gate above is production-specific: the same construction
        in dev mode resolves a config with ``dev_mode is True`` and does NOT
        fail-close on the absent manifest (the security-material gate is skipped
        in dev).  Written against a tmp dev config so it depends on no shipped
        production material.
        """
        config_path = tmp_path / "services" / "assistant_orchestrator" / "config" / "default.toml"
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(
            """
[runtime]
deployment_mode = "host"

[gpu]
device = "GPU"
model_dir = "models/qwen3-14b/openvino-int4-gpu"
priority = 1

[generation]
max_new_tokens = 64
temperature = 0.0
top_k = 50
top_p = 0.9
repetition_penalty = 1.1
do_sample = false
response_depth_mode = "standard"

[security]
dev_mode = true

[ipc]
vsock_cid = 2
vsock_port = 5001
timeout_ms = 250
max_message_bytes = 65536

[pgov]
cosine_similarity_threshold = 0.85
pii_mode = "off"
leakage_detection_enabled = false
""".strip(),
            encoding="utf-8",
        )

        service = AssistantOrchestratorService(
            config_path,
            dev_mode_override=True,
            deployment_mode="host",
        )
        resolved = service._load_entrypoint_config()
        assert resolved.dev_mode is True, (
            "Dev posture must resolve dev_mode=True (control for the production gate)"
        )

    def test_shipped_configs_declare_production_for_runtime_resolution(self) -> None:
        """Cross-check the shipped configs the runtime path reads.

        Lighter than the runtime assertions above and intentionally overlapping
        with ``test_secure_defaults.py`` ONLY on the dev_mode flag — here the
        purpose is to confirm the *inputs* to the runtime resolution path are
        production, so a green runtime assertion above cannot be explained away
        by a dev config that happened to be loaded.  If this and the runtime
        tests ever disagree, the resolution path has a bug.
        """
        for label, path in (("AO", _AO_CONFIG), ("PA", _PA_CONFIG)):
            assert path.exists(), f"shipped {label} config missing: {path}"
            security = _load_toml(path).get("security", {})
            assert security.get("dev_mode") is False, (
                f"{label} shipped config must declare [security].dev_mode=false "
                f"(runtime-resolution input); got {security.get('dev_mode')!r}"
            )
            assert security.get("fail_closed") is True, (
                f"{label} shipped config must declare [security].fail_closed=true"
            )


# ---------------------------------------------------------------------------
# SLOW tier — real full production boot (needs TPM + Known-Good Manifest).
# Deselected by the gate's addopts (-m 'not slow ...').  First green run is the
# LA on-chip session.  NOT the only home of the dev_mode=False assertion — the
# gate tier above carries the load-bearing runtime assertion.
# ---------------------------------------------------------------------------


class TestProductionPostureFullBoot:
    """Real full production boot asserting dev_mode=False on the LIVE service.

    THIS TIER IS BUILT BUT NOT VERIFIED IN THE GATE.  It is ``@pytest.mark.slow``
    so the standing gate deselects it.  It needs a fully provisioned chip:
      - the PA JWT TPM signing key (``BlarAI-PA-JWT-Signing``),
      - the audit TPM signing key (``BlarAI-Audit-Signing-Key-v1``),
      - a Known-Good Manifest present at the configured model dir,
      - the OpenVINO model weights at ``models/qwen3-14b/openvino-int4-gpu/``.

    HOW TO RUN (on-chip / dev machine, after the provisioning ceremonies):
        C:/Users/mrbla/BlarAI/.venv/Scripts/python.exe -m pytest \\
            tests/security/test_production_posture.py::TestProductionPostureFullBoot \\
            -m slow -v

    Expected result: the PA starts in production posture and the LIVE service's
    resolved entrypoint config reports ``dev_mode is False``.  A failure here is
    a production-boot regression.

    HOME: this tier's first green run belongs to the LA on-chip session (Sprint
    17 §7) or, if not executed there, carries forward to the Sprint-18 pre-gate
    sweep.  See the Sprint-17 SCR.
    """

    @pytest.mark.slow
    def test_real_production_boot_resolves_dev_mode_false(self) -> None:
        """Full production PA boot — assert the LIVE service resolved dev_mode=False.

        Constructs the PA in production posture (NO ``dev_mode_override`` — the
        shipped config's ``dev_mode=false`` and the HOST default must carry it),
        starts it for real (TPM + manifest required), and asserts the resolved
        runtime config on the live service is production.  Bricks (does not skip)
        if the chip is not provisioned — by design, this is the real-boot gate.
        """
        service = PolicyAgentService.from_runtime_mode("host")

        # The resolved config must already report production BEFORE start — this
        # is the runtime resolution, asserted on the real service object.
        resolved = service._load_entrypoint_config()
        assert resolved.dev_mode is False, (
            "Live production PA must resolve dev_mode=False at runtime"
        )

        started = service.start()
        try:
            assert started is True, (
                "Production PA must start with provisioned TPM + Known-Good "
                f"Manifest; last_failure={service.last_failure}"
            )
            assert service.running is True
            # Re-assert on the running service: production posture held through
            # the full measured-boot sequence.
            assert service._load_entrypoint_config().dev_mode is False
        finally:
            service.stop()
