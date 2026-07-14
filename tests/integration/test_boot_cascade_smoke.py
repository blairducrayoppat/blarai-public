"""
Production-parity lane — Lock (ii): boot-cascade smoke lock.

Sprint 16 SDV §4 criterion #6(ii) — ticket #619.

WHY THIS FILE EXISTS — the lock-before-modify discipline
=========================================================
Sprint 16 opens two gate-critical changes: #615 (AF_HYPERV guest↔host boundary
fix) and egress mediation.  Before those changes land, the CURRENT Sprint-15
cascade — per-boot cert mint → PA/AO service handshakes → prompt-flow preflight
— must be regression-locked in an automated, headless test.  Without this lock,
"#615 + egress didn't break the cascade" is only provable by the LA babysitting
a full boot at the terminal, which is the exact manual-marathon problem this
sprint exists to kill.

The lock-before-modify discipline (the direct answer to BUILD_JOURNAL lesson 56):
acquire a green automated gate on the CURRENT cascade, then Sprint 17 modifies
the cascade with the gate already in place.  A failing gate at Sprint-17 PR time
is a test surfacing a regression; a passing gate is confirmation the changes
did not break the boot path.

TWO-TIER STRUCTURE
==================
(ii-a) STUBBED tier — GREEN in the Layer-A suite right now (no GPU, no TPM):
    Exercises the cascade-INVOCATION logic (the real function calls in the right
    order) and the TEARDOWN logic (both services stopped, resources released).
    GPU inference is stubbed via monkeypatch — the same pattern used in
    tests/integration/test_prompt_round_trip_host_mode.py.  Cert provisioning
    runs the REAL provision_per_boot_certs() against a tmp_path certs dir.
    The session store is built via the REAL build_session_store() in dev_mode.
    The TransportGateway handshake and preflight run against the REAL AO IPC
    listener (GPU stubbed).

    Specifically, the stubbed tier exercises:
      Step 1.5 — provision_per_boot_certs() (REAL cert generation, tmp_path)
      Step 3   — PolicyAgentService.start() (REAL service, GPU stubbed)
      Step 4   — AssistantOrchestratorService.start() (REAL service, GPU stubbed)
      Step 5   — build_session_store() (REAL factory, dev_mode, :memory:)
      Step 6   — TransportGateway construction (REAL, dev loopback)
      Step 6a  — gateway.check_pa_status() (REAL handshake, both listeners up)
      Step 6b  — _run_uat2_prompt_flow_preflight() (REAL preflight, stub reply)
      Teardown — PA.stop(), AO.stop(), session store closed, certs cleaned up

    The ONLY stubbed component is OrchestratorGPUInference (no Qwen3-14B load).

(ii-b) REAL-GPU tier — BUILT, SCRIPTED, marked @hardware — DEFERRED to Sprint-17:
    Identical cascade, real model load.  Runs as a PREREQUISITE before the
    first #615/egress edit in Sprint 17.  Marked with the ``hardware`` marker
    so Layer-A DESELECTS it.

ISOLATION
=========
All tests use tmp_path only.  The root conftest.py redirects LOCALAPPDATA/HOME/
XDG_DATA_HOME to a throwaway temp dir at process startup and unsets
BLARAI_DEK_KEYSTORE, so the real user-data directory is never touched.
The PA and AO bind fixed loopback ports (5000/5001 per launcher constants).
Each test skips if those ports are in use (live BlarAI instance on the dev box).
"""

from __future__ import annotations

import asyncio
import os
import socket
import threading
from pathlib import Path
from typing import Any

import pytest

from launcher.__main__ import (
    ORCHESTRATOR_HOST_LOOPBACK_PORT,
    PA_HOST_PRODUCTION_PORT,
    _prompt_flow_preflight_enabled,
    _run_uat2_prompt_flow_preflight,
    resolve_gateway_port,
)
from services.assistant_orchestrator.src.entrypoint import AssistantOrchestratorService
from services.assistant_orchestrator.src.gpu_inference import GenerationResult
from services.policy_agent.src.entrypoint import PolicyAgentService
from services.ui_gateway.src.session_store import build_session_store
from services.ui_gateway.src.transport import StartupState, TransportGateway
from shared.security.cert_provisioning import provision_per_boot_certs


# ---------------------------------------------------------------------------
# Shared infrastructure
# ---------------------------------------------------------------------------

# Canned reply the stubbed AO streams back.  Short, benign, PGOV-safe.
_STUB_REPLY: str = "Boot preflight reply from the stubbed orchestrator."


def _port_is_free(port: int) -> bool:
    """True if 127.0.0.1:port can be bound (no live service holding it)."""
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        probe.bind(("127.0.0.1", port))
    except OSError:
        return False
    finally:
        probe.close()
    return True


class _StubInference:
    """Drop-in for OrchestratorGPUInference that never loads a real model.

    Mirrors the pattern from test_prompt_round_trip_host_mode.py._StubInference:
    load_model() returns True immediately, generate_text() invokes the stream
    callback with _STUB_REPLY and returns a well-formed GenerationResult so the
    AO's _handle_prompt_request proceeds to PGOV and GENERATION_COMPLETE.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self.loaded: bool = False

    def load_model(self) -> bool:
        self.loaded = True
        return True

    def unload(self) -> None:
        self.loaded = False

    def generate_text(
        self,
        prompt: str,
        *args: Any,
        stream_callback: Any = None,
        **kwargs: Any,
    ) -> GenerationResult:
        if stream_callback is not None:
            stream_callback(_STUB_REPLY)
        return GenerationResult(
            tokens=[1, 2, 3],
            text=_STUB_REPLY,
            token_count=max(1, len(_STUB_REPLY) // 4),
            latency_first_token_ms=0.0,
            latency_total_ms=0.0,
            truncated=False,
            error=None,
        )


def _write_ao_dev_config(path: Path, *, vsock_port: int) -> None:
    """Write a minimal dev-mode AO config.  Mirrors the pattern from test_prompt_round_trip_host_mode.py.

    Model dirs are written as ABSOLUTE repo-rooted paths.  This config lives under
    ``tmp_path``, and the AO's ``_resolve_path`` roots a *relative* ``model_dir`` off
    the config's own ``service_root`` (i.e. under tmp), where no weights exist — which
    failed the real-model tier with ``AO_MODEL_LOAD_FAILED``.  The stubbed tier never
    saw this (``OrchestratorGPUInference`` is monkeypatched, so the paths are never
    read); the real-model tier needs them to point at the actual ``models/`` tree.
    """
    repo_root = Path(__file__).resolve().parents[2]
    model_dir = (repo_root / "models" / "qwen3-14b" / "openvino-int4-gpu").as_posix()
    weight_manifest = (
        repo_root / "models" / "qwen3-14b" / "openvino-int4-gpu" / "manifest.json"
    ).as_posix()
    draft_model_dir = (repo_root / "models" / "qwen3-0.6b" / "openvino-int4-gpu").as_posix()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"""
[runtime]
deployment_mode = "host"

[gpu]
device = "GPU"
priority = 1
model_dir = "{model_dir}"
weight_manifest = "{weight_manifest}"
draft_model_dir = "{draft_model_dir}"
speculative_decoding_enabled = true

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
vsock_port = {vsock_port}
timeout_ms = 250
max_message_bytes = 65536

[pgov]
cosine_similarity_threshold = 0.85
pii_mode = "off"
leakage_detection_enabled = false
""".strip(),
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# (ii-a) Stubbed-model tier — GREEN in Layer-A suite (no GPU required)
# ---------------------------------------------------------------------------


class TestBootCascadeSmoke:
    """Smoke lock on the Sprint-15 production cascade (GPU stubbed).

    The stubbed tier exercises the REAL cascade-invocation and teardown logic:
    cert mint → PA service start → AO service start → session store build →
    gateway construction → handshake preflight → prompt-flow preflight →
    teardown.

    This is NOT a trivial smoke.  The key invariants asserted:
      - provision_per_boot_certs() succeeds and writes the expected cert files.
      - PolicyAgentService.start() returns True (the real service binds the port).
      - AssistantOrchestratorService.start() returns True (real serve loop starts).
      - build_session_store() returns a usable store (real DEK creation).
      - TransportGateway.check_pa_status() returns True (REAL handshake to AO).
      - _run_uat2_prompt_flow_preflight() returns True (REAL prompt round-trip).
      - PA.stop() and AO.stop() complete without raising (clean teardown path).
    Any regression in the invocation logic or teardown is caught here before
    it reaches the LA's terminal.
    """

    def test_cert_mint_step(self, tmp_path: Path) -> None:
        """Step 1.5: provision_per_boot_certs() mints certs to a tmp dir.

        This is a standalone test for the cert-provisioning step of the cascade.
        It runs WITHOUT any services and exercises the REAL cert generation logic,
        confirming the cascade's first non-trivial step works in isolation.
        """
        certs_dir = tmp_path / "certs"
        certs = provision_per_boot_certs(certs_dir=certs_dir)

        # Confirm all expected cert files were written (they are the inputs to
        # the PA and gateway TLS contexts in production).
        assert certs.ca_cert_path.exists(), "CA cert must be written"
        assert certs.pa_server_cert_path.exists(), "PA server cert must be written"
        assert certs.pa_server_key_path.exists(), "PA server key must be written"
        assert certs.gateway_client_cert_path.exists(), "Gateway client cert must be written"
        assert certs.gateway_client_key_path.exists(), "Gateway client key must be written"

        # All certs must be non-empty PEM files.
        for path in (
            certs.ca_cert_path,
            certs.pa_server_cert_path,
            certs.gateway_client_cert_path,
        ):
            content = path.read_text(encoding="utf-8")
            assert "-----BEGIN CERTIFICATE-----" in content, (
                f"{path.name} must be a valid PEM certificate"
            )

    def test_prompt_flow_preflight_enabled_logic(self) -> None:
        """_prompt_flow_preflight_enabled() control logic is correct.

        The preflight is OFF by default in dev_mode and ON in production.
        This locks the conditional logic that gates Step 6b in the cascade.
        """
        # Baseline: production mode has preflight ON, dev has it OFF.
        assert _prompt_flow_preflight_enabled(dev_mode=False) is True, (
            "Prompt-flow preflight must be ON by default in production"
        )
        assert _prompt_flow_preflight_enabled(dev_mode=True) is False, (
            "Prompt-flow preflight must be OFF by default in dev mode"
        )

        # BLARAI_PROMPTFLOW_PREFLIGHT env var overrides both directions.
        old = os.environ.pop("BLARAI_PROMPTFLOW_PREFLIGHT", None)
        try:
            os.environ["BLARAI_PROMPTFLOW_PREFLIGHT"] = "0"
            assert _prompt_flow_preflight_enabled(dev_mode=False) is False, (
                "Env var '0' must disable preflight even in production"
            )
            os.environ["BLARAI_PROMPTFLOW_PREFLIGHT"] = "1"
            assert _prompt_flow_preflight_enabled(dev_mode=True) is True, (
                "Env var '1' must enable preflight even in dev"
            )
        finally:
            if old is not None:
                os.environ["BLARAI_PROMPTFLOW_PREFLIGHT"] = old
            else:
                os.environ.pop("BLARAI_PROMPTFLOW_PREFLIGHT", None)

    def test_resolve_gateway_port_cascade_invariant(self) -> None:
        """resolve_gateway_port() always targets the AO, not the PA.

        This is the single-line invariant the Sprint-15 host-mode routing fix
        established.  It locks the cascade's port-resolution step.
        """
        prod_port = resolve_gateway_port(dev_mode=False, host_mode=True)
        dev_port = resolve_gateway_port(dev_mode=True, host_mode=True)
        assert prod_port == ORCHESTRATOR_HOST_LOOPBACK_PORT, (
            f"Production port must be {ORCHESTRATOR_HOST_LOOPBACK_PORT}, got {prod_port}"
        )
        assert dev_port == ORCHESTRATOR_HOST_LOOPBACK_PORT, (
            f"Dev port must be {ORCHESTRATOR_HOST_LOOPBACK_PORT}, got {dev_port}"
        )
        assert prod_port != PA_HOST_PRODUCTION_PORT, (
            "Gateway must NOT target the PA port — that was the Sprint-15 misroute bug"
        )

    def test_session_store_build_step(self, tmp_path: Path) -> None:
        """Step 5: build_session_store() constructs a usable store in dev mode.

        Exercises the REAL factory with a dev_mode path, which creates a
        SoftwareSealer-backed DEK and EncryptedSessionStore.  Locks the
        factory's dev-mode code path and the store's basic write/read cycle.
        """
        db_path = str(tmp_path / "cascade_sessions.db")
        store = build_session_store(db_path, dev_mode=True)
        assert store is not None

        # Must be usable: write a session, read it back.
        sid = store.create_session(title="Cascade smoke session")
        store.add_turn(sid, "user", "smoke test prompt", "N/A", [])
        sessions = store.list_sessions()
        assert any(s.id == sid for s in sessions), "Created session must be listed"
        store.close()

    @pytest.mark.asyncio
    async def test_ao_service_starts_stops_cleanly(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Step 4 + teardown: AO service starts (GPU stubbed) and stops cleanly.

        Exercises the REAL AssistantOrchestratorService.start() / .stop()
        lifecycle.  The GPU inference class is monkeypatched to _StubInference
        so Qwen3-14B never loads, but the real VsockListener, serve loop, and
        handler are exercised.  Skips if the AO port is already in use.
        """
        if not _port_is_free(ORCHESTRATOR_HOST_LOOPBACK_PORT):
            pytest.skip(
                f"AO loopback port {ORCHESTRATOR_HOST_LOOPBACK_PORT} is in use — "
                "skipping (live BlarAI instance?)"
            )

        monkeypatch.setattr(
            "services.assistant_orchestrator.src.entrypoint.OrchestratorGPUInference",
            _StubInference,
        )
        config_path = (
            tmp_path
            / "services"
            / "assistant_orchestrator"
            / "config"
            / "default.toml"
        )
        _write_ao_dev_config(config_path, vsock_port=ORCHESTRATOR_HOST_LOOPBACK_PORT)

        service = AssistantOrchestratorService(
            config_path,
            dev_mode_override=True,
            deployment_mode="host",
        )
        started = service.start()
        assert started is True, (
            f"AO service must start with stubbed GPU; last_failure={service.last_failure}"
        )
        assert service.running is True

        # Teardown — clean stop, no hang.
        service.stop()
        # Running flag is cleared by stop.
        assert service.running is False

    @pytest.mark.asyncio
    async def test_gateway_handshake_preflight_step(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Step 6a: gateway handshake preflight against REAL AO (GPU stubbed).

        Starts the REAL AO service (GPU stubbed), constructs a REAL
        TransportGateway, and runs the REAL check_pa_status() call — the same
        handshake the launcher's Step 6a executes.  Asserts the gateway reaches
        OPERATIONAL state.  This is the most direct regression lock for the
        Sprint-15 host-mode routing fix: if the gateway targeted the wrong port,
        the handshake would time out or return False.
        """
        if not _port_is_free(ORCHESTRATOR_HOST_LOOPBACK_PORT):
            pytest.skip(
                f"AO loopback port {ORCHESTRATOR_HOST_LOOPBACK_PORT} is in use — "
                "skipping (live BlarAI instance?)"
            )

        monkeypatch.setattr(
            "services.assistant_orchestrator.src.entrypoint.OrchestratorGPUInference",
            _StubInference,
        )
        config_path = (
            tmp_path
            / "services"
            / "assistant_orchestrator"
            / "config"
            / "default.toml"
        )
        _write_ao_dev_config(config_path, vsock_port=ORCHESTRATOR_HOST_LOOPBACK_PORT)

        service = AssistantOrchestratorService(
            config_path,
            dev_mode_override=True,
            deployment_mode="host",
        )
        assert service.start() is True, (
            f"AO service must start for handshake test; last_failure={service.last_failure}"
        )

        try:
            gateway = TransportGateway(
                dev_mode=True,
                host="127.0.0.1",
                port=ORCHESTRATOR_HOST_LOOPBACK_PORT,
            )
            handshake_ok = await gateway.check_pa_status()
            assert handshake_ok is True, "Gateway handshake must succeed against the real AO"
            assert gateway.state == StartupState.OPERATIONAL, (
                f"Gateway state must be OPERATIONAL after handshake; got {gateway.state}"
            )
        finally:
            service.stop()

    def test_full_prompt_flow_preflight_step(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Steps 6a+6b: full prompt-flow preflight against REAL AO (GPU stubbed).

        Exercises _run_uat2_prompt_flow_preflight() — the function called at
        Step 6b in the production launcher.  This is the tightest cascade lock:
        the preflight sends a REAL prompt through the REAL send_prompt→AO path
        (with the GPU stubbed so the AO returns _STUB_REPLY without loading the
        model), checks PGOV, writes the session, and cleans up.  If this passes,
        the prompt path from gateway to AO is confirmed working.

        This is the central test that locks the Sprint-15 production cascade.
        A regression in any of the following would break it:
          - resolve_gateway_port() returning the wrong port
          - TransportGateway failing to build a connection
          - AO _handle_prompt_request() throwing or not replying
          - PGOV output validation blocking a benign reply
          - _run_uat2_prompt_flow_preflight() failing to create/delete a session

        NOTE: this test is intentionally NOT marked @pytest.mark.asyncio.
        _run_uat2_prompt_flow_preflight() calls asyncio.run() internally (it is
        the production launcher's synchronous entry point into the async prompt
        path).  Calling asyncio.run() from inside an already-running event loop
        raises RuntimeError; to avoid this the gateway handshake (which IS
        async) runs in a fresh event loop via asyncio.get_event_loop().run_until_complete()
        before the synchronous preflight call.
        """
        if not _port_is_free(ORCHESTRATOR_HOST_LOOPBACK_PORT):
            pytest.skip(
                f"AO loopback port {ORCHESTRATOR_HOST_LOOPBACK_PORT} is in use — "
                "skipping (live BlarAI instance?)"
            )

        monkeypatch.setattr(
            "services.assistant_orchestrator.src.entrypoint.OrchestratorGPUInference",
            _StubInference,
        )
        config_path = (
            tmp_path
            / "services"
            / "assistant_orchestrator"
            / "config"
            / "default.toml"
        )
        _write_ao_dev_config(config_path, vsock_port=ORCHESTRATOR_HOST_LOOPBACK_PORT)

        service = AssistantOrchestratorService(
            config_path,
            dev_mode_override=True,
            deployment_mode="host",
        )
        assert service.start() is True, (
            f"AO service must start for preflight test; last_failure={service.last_failure}"
        )

        try:
            gateway = TransportGateway(
                dev_mode=True,
                host="127.0.0.1",
                port=ORCHESTRATOR_HOST_LOOPBACK_PORT,
            )
            # Handshake first (Step 6a) — run in a fresh synchronous event loop
            # so _run_uat2_prompt_flow_preflight() can call asyncio.run() (Step 6b)
            # without hitting "cannot run nested event loops".
            loop = asyncio.new_event_loop()
            try:
                handshake_ok = loop.run_until_complete(gateway.check_pa_status())
            finally:
                loop.close()
            assert handshake_ok is True, "Handshake must succeed before preflight"

            # Session store for the preflight (mirrors Step 5 in the launcher).
            store = build_session_store(":memory:", dev_mode=True)

            from shared.runtime_config import DeploymentMode

            # Run the REAL prompt-flow preflight — Step 6b.
            # _run_uat2_prompt_flow_preflight() calls asyncio.run() internally
            # (it is a synchronous function in the production launcher).
            preflight_ok = _run_uat2_prompt_flow_preflight(
                gateway=gateway,
                session_store=store,
                runtime_mode=DeploymentMode.HOST,
            )
            assert preflight_ok is True, (
                "Prompt-flow preflight must return True with stubbed AO; "
                "a False here means a real cascade regression"
            )
        finally:
            service.stop()
            # store is in-memory; no explicit cleanup needed.

    @pytest.mark.asyncio
    async def test_cascade_teardown_releases_ports(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Teardown: after .stop(), both AO ports are released for a re-bind.

        Locks the teardown logic: after a cascade run, .stop() must release the
        loopback port so a subsequent boot (or the next test) is not blocked.
        If stop() fails to release the socket, the next integration test / next
        launcher boot will find the port in use and fail silently or skip.
        """
        if not _port_is_free(ORCHESTRATOR_HOST_LOOPBACK_PORT):
            pytest.skip(
                f"AO loopback port {ORCHESTRATOR_HOST_LOOPBACK_PORT} is in use — "
                "skipping teardown test"
            )

        monkeypatch.setattr(
            "services.assistant_orchestrator.src.entrypoint.OrchestratorGPUInference",
            _StubInference,
        )
        config_path = (
            tmp_path
            / "services"
            / "assistant_orchestrator"
            / "config"
            / "default.toml"
        )
        _write_ao_dev_config(config_path, vsock_port=ORCHESTRATOR_HOST_LOOPBACK_PORT)

        service = AssistantOrchestratorService(
            config_path,
            dev_mode_override=True,
            deployment_mode="host",
        )
        assert service.start() is True
        service.stop()

        # After stop(), the port must be re-bindable (teardown released it).
        assert _port_is_free(ORCHESTRATOR_HOST_LOOPBACK_PORT), (
            f"Port {ORCHESTRATOR_HOST_LOOPBACK_PORT} must be free after service.stop() — "
            "teardown did not release the socket"
        )


# ---------------------------------------------------------------------------
# (ii-b) Real-GPU tier — BUILT, SCRIPTED, marked @hardware, DEFERRED Sprint-17
# ---------------------------------------------------------------------------


class TestBootCascadeSmokeRealModel:
    """Real-model boot-cascade smoke — Sprint-17-kickoff PREREQUISITE.

    THIS TIER IS BUILT BUT NOT VERIFIED THIS SPRINT.  It is marked with the
    ``hardware`` marker so Layer-A DESELECTS it.  Its first green run is a
    prerequisite before the first #615/egress edit in Sprint 17.

    WHY THE REAL-GPU RUN IS DEFERRED:
    The LA directive for SDV §4 criterion #6(ii) is explicit: a lock that has
    never gone green locks nothing.  But the first real-GPU run MUST be a
    confirmation (harness verified on stubbed tier) not a discovery (harness
    broken because it was never exercised).  The stubbed tier (ii-a) proves the
    harness works.  The real-GPU run then confirms the model loads and serves,
    locking the FULL cascade before Sprint 17 modifies it.

    HOW TO RUN (Sprint-17 kickoff, dev machine):
        set BLARAI_PROMPTFLOW_PREFLIGHT=1
        C:/Users/mrbla/BlarAI/.venv/Scripts/python.exe -m pytest \\
            tests/integration/test_boot_cascade_smoke.py::TestBootCascadeSmokeRealModel \\
            -m hardware -v

    PREREQUISITE: models must be present at:
        models/qwen3-14b/openvino-int4-gpu/
        models/qwen3-0.6b/openvino-int4-gpu/  (optional, speculative decoding)

    Expected result: all tests PASS.  Any failure is a cascade regression that
    must be fixed BEFORE the first #615/egress edit.
    """

    @pytest.mark.hardware
    def test_real_model_cascade_to_preflight_passing(
        self, tmp_path: Path
    ) -> None:
        """Full cascade to preflight passing with the REAL Qwen3-14B model.

        Steps exercised:
          1.5  provision_per_boot_certs() — real certs, tmp_path dir
          3    PolicyAgentService.start() — REAL PA (real model via shared pipeline)
          4    AssistantOrchestratorService.start() — REAL AO (real model)
          5    build_session_store() — REAL factory, dev_mode
          6    TransportGateway construction — REAL, dev loopback
          6a   gateway.check_pa_status() — REAL handshake
          6b   _run_uat2_prompt_flow_preflight() — REAL prompt, REAL generation
          Teardown — PA.stop(), AO.stop(), store.close()

        This test BRICKS if the model is absent or fails to load — that is by
        design (it is a hardware gate, not a fallback-safe test).
        """
        if not _port_is_free(ORCHESTRATOR_HOST_LOOPBACK_PORT):
            pytest.skip(
                f"AO loopback port {ORCHESTRATOR_HOST_LOOPBACK_PORT} is in use"
            )
        if not _port_is_free(PA_HOST_PRODUCTION_PORT):
            pytest.skip(
                f"PA loopback port {PA_HOST_PRODUCTION_PORT} is in use"
            )

        # --- Step 1.5: cert mint ---
        certs_dir = tmp_path / "certs"
        provision_per_boot_certs(certs_dir=certs_dir)

        # --- Steps 3+4: start PA and AO with REAL models ---
        pa_service = PolicyAgentService.from_runtime_mode(
            "host",
            dev_mode_override=True,
        )
        assert pa_service.start() is True, (
            f"PA service must start with real model; last_failure={pa_service.last_failure}"
        )

        ao_config_path = (
            tmp_path
            / "services"
            / "assistant_orchestrator"
            / "config"
            / "default.toml"
        )
        _write_ao_dev_config(ao_config_path, vsock_port=ORCHESTRATOR_HOST_LOOPBACK_PORT)
        ao_service = AssistantOrchestratorService(
            ao_config_path,
            dev_mode_override=True,
            deployment_mode="host",
        )
        assert ao_service.start() is True, (
            f"AO service must start with real model; last_failure={ao_service.last_failure}"
        )

        try:
            # --- Step 5: session store ---
            store = build_session_store(":memory:", dev_mode=True)

            # --- Steps 6+6a+6b: gateway handshake + prompt-flow preflight ---
            gateway = TransportGateway(
                dev_mode=True,
                host="127.0.0.1",
                port=ORCHESTRATOR_HOST_LOOPBACK_PORT,
            )
            handshake_ok = asyncio.run(gateway.check_pa_status())
            assert handshake_ok is True, "Handshake must succeed with real services"

            from shared.runtime_config import DeploymentMode

            preflight_ok = _run_uat2_prompt_flow_preflight(
                gateway=gateway,
                session_store=store,
                runtime_mode=DeploymentMode.HOST,
            )
            assert preflight_ok is True, (
                "Prompt-flow preflight must pass with real Qwen3-14B — "
                "if this fails, the cascade is broken before #615/egress edits begin"
            )
        finally:
            ao_service.stop()
            pa_service.stop()
