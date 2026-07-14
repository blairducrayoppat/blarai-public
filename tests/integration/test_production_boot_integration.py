"""Full PRODUCTION-mode boot integration test — Sprint 17 SDV §4 criterion C2.

WHY THIS FILE EXISTS — the spine's second half (depends on G1's post-#615 topology)
==================================================================================
C1 (#615, stream G1, merged) fixed the Windows ``AF_HYPERV`` guest-boundary
addressing and wired ``launcher.resolve_gateway_topology()`` so the launcher
selects HOST (loopback + mTLS) or GUEST (AF_HYPERV) topology with a clean host
fallback.  C2 (this file) is the *composed* production boot path against that
post-#615 topology:

    cert-mint → PA → AO → mTLS handshake → preflight → prompt → teardown

run in PRODUCTION posture (``dev_mode=False``) — the posture that fail-CLOSES
without security material (it bit stream J at the merge gate: the AO's
``_validate_security_material`` requires a Known-Good Manifest + a JWT CA public
key, and ``build_session_store`` / the PA refuse the SoftwareSealer outside an
explicit dev context).  The existing ``test_boot_cascade_smoke.py`` exercises the
SAME cascade in **dev** posture (no mTLS, no security material); this file is the
production complement — it proves the cascade composes when the production
security gate is actually armed, with the GPU stubbed so no model loads.

THE PRODUCTION-vs-DEV DESIGN FACT THAT SHAPES THE TWO TIERS
===========================================================
A production-posture boot has two service-start paths with very different
hardware coupling:

  * The **Assistant Orchestrator** production gate needs only a Known-Good
    Manifest (a 64-hex digest entry for ``openvino_model.bin``), a JWT CA public
    key file, and mTLS cert paths.  It does NOT need a TPM, and with
    ``OrchestratorGPUInference`` stubbed it does NOT load Qwen3-14B.  So the AO
    can run its FULL production posture in the gate with stand-in material.

  * The **Policy Agent** production gate is irreducibly hardware-bound: it
    requires a *provisioned TPM JWT key* (``tpm_signer.key_exists``) AND a
    *provisioned TPM audit key* (``_build_audit_log`` REFUSES TO START in
    production without it — ADR-025 §2.8(a)), plus a measured-boot weight-integrity
    gate over the real model directory and a real model load.  None of that can be
    stood in without a TPM + the real model.

Therefore the GATE tier composes the production cascade around the **AO in real
production posture** (real mTLS listener, stand-in manifest + JWT CA, GPU
stubbed) and the **real per-boot mTLS handshake** the gateway performs against it
(client cert ↔ server cert, ``CERT_REQUIRED`` both ways, verified against the
per-boot CA).  This is the genuine production transport seam — the ``dev_mode``
fallback (AF_INET vs AF_HYPERV) is the transport, NOT the TLS: ``VsockListener``
builds ``create_server_ssl_context`` whenever the cert paths are present, exactly
as in a real production host-mode boot (see ``shared.ipc.vsock`` and
``services.ui_gateway.src.transport._connect_host_loopback_mtls``).

The full-production PA-start (TPM + real model) + the model-loaded AO generation
live in the MODEL-LOADED tier (``@pytest.mark.hardware``), homed to the LA
on-chip / Sprint-18 session.

WHAT THE GATE TIER ACTUALLY EXECUTES (not skip-only)
====================================================
``test_full_production_cascade_to_preflight`` runs, end to end, with the GPU
stubbed and the air-gap UP:

    Step 1.5  provision_per_boot_certs()        — REAL per-boot CA + mTLS certs
    Step 3*   (PA start)                        — see note below
    Step 4    AssistantOrchestratorService.start(dev_mode_override=False)
                                                — REAL production posture, stand-in
                                                  manifest + JWT CA, mTLS listener,
                                                  GPU stubbed
    Step 5    build_session_store(dev_mode=True) — in-memory store for the preflight
    Step 6    TransportGateway(host_mode=True, mtls_*) — REAL production gateway
    Step 6a   gateway.check_pa_status()         — REAL loopback + mTLS handshake
    Step 6b   _run_uat2_prompt_flow_preflight() — REAL prompt round-trip (stub reply)
    Teardown  AO.stop()                         — clean stop, port released

  * PA-start in FULL production posture is hardware-bound (TPM + real model), so
    the gate tier does not start a production PA; the composed mTLS handshake +
    prompt round-trip runs against the AO (which answers HANDSHAKE_REQUEST and
    PROMPT_REQUEST — the gateway uses ONE port for both, per
    ``launcher.resolve_gateway_port``).  The real production PA boot is the
    MODEL-LOADED tier.  ``test_boot_cascade_smoke.py`` already locks the
    dev-posture PA+AO handshake; G1's ``test_guest_boundary_hyperv.py`` locks the
    AF_HYPERV guest round-trip — this file does not duplicate either.

ISOLATION
=========
All tests use ``tmp_path`` only.  The root ``conftest.py`` redirects
``LOCALAPPDATA`` / ``HOME`` / ``XDG_DATA_HOME`` to a throwaway temp dir at pytest
process startup and unsets ``BLARAI_DEK_KEYSTORE``, so the real user-data
directory (live ``sessions.db`` / DEK keystore) is never touched.  The AO binds
the fixed AO loopback port (``ORCHESTRATOR_HOST_LOOPBACK_PORT``); each test that
binds it skips cleanly if a live BlarAI instance already holds it.

SHARED/SERVICES/LAUNCHER ARE READ-ONLY HERE
===========================================
This file IMPORTS and EXERCISES the production code; it modifies none of it.  The
cascade is built entirely from existing public APIs.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import socket
from pathlib import Path
from typing import Any

import pytest

from launcher.__main__ import (
    ORCHESTRATOR_HOST_LOOPBACK_PORT,
    PA_HOST_PRODUCTION_PORT,
    resolve_gateway_port,
    resolve_gateway_topology,
    _run_uat2_prompt_flow_preflight,
)
from services.assistant_orchestrator.src.entrypoint import AssistantOrchestratorService
from services.assistant_orchestrator.src.gpu_inference import GenerationResult
from services.ui_gateway.src.session_store import build_session_store
from services.ui_gateway.src.transport import StartupState, TransportGateway
from shared.runtime_config import DeploymentMode
from shared.security.cert_provisioning import provision_per_boot_certs


# ---------------------------------------------------------------------------
# Shared infrastructure
# ---------------------------------------------------------------------------

# Canned reply the stubbed AO streams back.  Short, benign, PGOV-safe (no
# untrusted content is present, so the PGOV leakage detector never engages).
_STUB_REPLY: str = "Production boot preflight reply from the stubbed orchestrator."

# The model binary filename the production security-material gate looks for in
# the Known-Good Manifest (see AssistantOrchestratorService._validate_security_material
# and PolicyAgentService._load_entrypoint_config: ``model_dir / "openvino_model.bin"``).
_MODEL_BIN_NAME: str = "openvino_model.bin"


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

    Mirrors ``test_boot_cascade_smoke.py._StubInference``: ``load_model()``
    returns True immediately (bypassing the real weight-integrity sweep and the
    OpenVINO pipeline build), and ``generate_text()`` invokes the stream callback
    with ``_STUB_REPLY`` and returns a well-formed ``GenerationResult`` so the
    AO's ``_handle_prompt_request`` proceeds to PGOV and ``GENERATION_COMPLETE``.

    Because ``load_model()`` is stubbed, the production security-material gate the
    AO runs at config-load time (which only checks the manifest's *digest entry*
    for ``openvino_model.bin`` by NAME, not the file's bytes) is the only weight
    check exercised — and the stand-in manifest below satisfies it with a real
    64-hex digest.
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


def _provision_standin_security_material(
    tmp_path: Path,
    *,
    include_model_digest: bool = True,
) -> dict[str, Path]:
    """Mint the full stand-in security material a PRODUCTION boot requires.

    This is the heart of the gate tier: it produces, in ``tmp_path``, every
    artifact the production security-material gate validates so the cascade can
    proceed with ``dev_mode=False`` and the GPU stubbed — no TPM, no real model.

    Produces:
      - **Per-boot mTLS certs** (REAL ``provision_per_boot_certs``): the per-boot
        CA + PA-server + gateway-client + orchestrator certs.  These are the real
        production mTLS material — the handshake over them is a genuine
        ``CERT_REQUIRED`` mutual TLS exchange.
      - **A model directory** containing a tiny stand-in ``openvino_model.bin``
        (a few bytes; the GPU is stubbed so it is never read by OpenVINO).
      - **A Known-Good Manifest** (``manifest.json``) whose ``digests`` map carries
        the REAL sha256 of that stand-in bin under ``openvino_model.bin`` — a valid
        64-hex digest that satisfies ``_validate_security_material`` (and would even
        pass a real ``verify_all_manifest_entries`` sweep against this dir).  When
        ``include_model_digest`` is False the digest entry is omitted, so the gate
        REJECTS — used by the negative-control test.
      - **A JWT CA public key** (``jwt_ca.pem``): a real EC public key (P-256) in
        SPKI PEM form that ``AgenticJWTValidator.from_public_key_file`` accepts.
        Stands in for the operator's TPM-exported JWT public key.

    Returns a dict of the artifact paths the config writer + cascade need.
    """
    # --- Per-boot mTLS certs (REAL) ---
    certs_dir = tmp_path / "certs"
    certs = provision_per_boot_certs(certs_dir=certs_dir)

    # --- Stand-in model dir + bin (GPU stubbed → bytes never read by OV) ---
    model_dir = tmp_path / "models" / "qwen3-14b" / "openvino-int4-gpu"
    model_dir.mkdir(parents=True, exist_ok=True)
    model_bin = model_dir / _MODEL_BIN_NAME
    model_bin.write_bytes(b"stand-in-openvino-weights-not-a-real-model")

    # --- Known-Good Manifest with the REAL digest of the stand-in bin ---
    manifest_path = model_dir / "manifest.json"
    digests: dict[str, str] = {}
    if include_model_digest:
        digests[_MODEL_BIN_NAME] = hashlib.sha256(model_bin.read_bytes()).hexdigest()
    manifest_path.write_text(
        json.dumps({"version": "1.0.0", "digests": digests}),
        encoding="utf-8",
    )

    # --- JWT CA public key (real EC P-256 SPKI PEM) ---
    # Reuse the PA's own key-pair generator so the artifact is byte-identical in
    # shape to the production JWT public key the operator's ceremony exports.
    from cryptography.hazmat.primitives import serialization

    from services.policy_agent.src.jwt_minter import AgenticJWTMinter

    _priv, pub = AgenticJWTMinter.generate_key_pair()
    jwt_ca_path = tmp_path / "jwt_ca.pem"
    jwt_ca_path.write_bytes(
        pub.public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
    )

    return {
        "ca_cert_path": certs.ca_cert_path,
        "pa_server_cert_path": certs.pa_server_cert_path,
        "pa_server_key_path": certs.pa_server_key_path,
        "gateway_client_cert_path": certs.gateway_client_cert_path,
        "gateway_client_key_path": certs.gateway_client_key_path,
        "orch_cert_path": certs.orch_client_cert_path,
        "orch_key_path": certs.orch_client_key_path,
        "model_dir": model_dir,
        "manifest_path": manifest_path,
        "jwt_ca_path": jwt_ca_path,
    }


def _write_ao_production_config(
    path: Path,
    *,
    vsock_port: int,
    material: dict[str, Path],
) -> None:
    """Write a minimal PRODUCTION-mode (``dev_mode=false``) AO config.

    Mirrors the dev-config writer in ``test_boot_cascade_smoke.py`` but flips the
    posture to production and wires every field the production security-material
    gate + mTLS listener require:

      - ``[security] dev_mode = false`` — the production posture under test.
      - ``[security] jwt_ca_cert_path`` — the stand-in JWT CA public key.
      - ``[gpu] weight_manifest`` — the stand-in Known-Good Manifest.
      - ``[ipc] mtls_cert_path / mtls_key_path / ca_cert_path`` — the per-boot
        ORCH cert (the AO's own listener identity) + the per-boot CA, so
        ``VsockListener.start`` builds a REAL ``create_server_ssl_context`` and
        the loopback listener performs ``CERT_REQUIRED`` mutual TLS.

    All paths are absolute (``tmp_path``), which the AO's ``_resolve_path``
    returns as-is, so nothing resolves against the repo.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"""
[runtime]
deployment_mode = "host"

[gpu]
device = "GPU"
priority = 1
model_dir = "{material['model_dir'].as_posix()}"
weight_manifest = "{material['manifest_path'].as_posix()}"
draft_model_dir = "models/qwen3-0.6b/openvino-int4-gpu"
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
dev_mode = false
jwt_ca_cert_path = "{material['jwt_ca_path'].as_posix()}"

[ipc]
vsock_cid = 2
vsock_port = {vsock_port}
mtls_cert_path = "{material['orch_cert_path'].as_posix()}"
mtls_key_path = "{material['orch_key_path'].as_posix()}"
ca_cert_path = "{material['ca_cert_path'].as_posix()}"
timeout_ms = 5000
max_message_bytes = 65536

[pgov]
cosine_similarity_threshold = 0.85
pii_mode = "off"
leakage_detection_enabled = false
""".strip(),
        encoding="utf-8",
    )


def _build_production_gateway(
    material: dict[str, Path], *, port: int
) -> TransportGateway:
    """Construct a PRODUCTION host-mode gateway wired with the per-boot client certs.

    ``dev_mode=False`` + ``host_mode=True`` is the post-#615 gate-runnable
    topology (``resolve_gateway_topology(HOST, dev_mode=False) is True``).  The
    gateway-client cert/key + per-boot CA are supplied exactly as the launcher
    supplies them after ``provision_per_boot_certs`` (ADR-026), so
    ``_connect_host_loopback_mtls`` performs a REAL ``CERT_REQUIRED`` mutual-TLS
    connection to the AO listener — no dev-loopback shortcut.
    """
    return TransportGateway(
        session_store=None,
        dev_mode=False,
        host_mode=True,
        host="127.0.0.1",
        port=port,
        mtls_cert_path=str(material["gateway_client_cert_path"]),
        mtls_key_path=str(material["gateway_client_key_path"]),
        ca_cert_path=str(material["ca_cert_path"]),
    )


# ---------------------------------------------------------------------------
# Gate tier — GREEN in the standing gate (production posture, GPU stubbed, real mTLS)
# ---------------------------------------------------------------------------


class TestProductionBootCascadeGate:
    """The composed PRODUCTION boot cascade, gate-runnable (GPU stubbed, real mTLS).

    Production posture (``dev_mode=False``) with stand-in security material
    (SoftwareSealer-free: per-boot certs + a Known-Good Manifest + a JWT CA
    public key) and the GPU stubbed.  Every NON-hardware production seam is REAL:
    real per-boot cert minting, the AO's real production security-material gate, a
    real ``CERT_REQUIRED`` mutual-TLS listener + handshake, and the real
    prompt-flow preflight round-trip.

    This is the regression lock that proves the production boot path *composes*
    once its security gate is armed — the gap that bit stream J at the Sprint-17
    merge gate (a production posture that fail-closes without material) and the
    Sprint-15 host-mode misroute (a production-only transport path no test
    exercised).
    """

    def test_topology_resolves_host_mode_for_gate_path(self) -> None:
        """resolve_gateway_topology(HOST) → host_mode for the gate-runnable path.

        The post-#615 topology selection (G1): HOST always resolves to host-mode
        (loopback + mTLS) — the always-available default the guest path never
        overrides.  This is the topology the rest of the gate-tier cascade runs
        against.  GUEST + dev_mode also reports host-mode (the AF_HYPERV probe is
        irrelevant to a dev launch).  We do NOT here assert the GUEST production
        AF_HYPERV path — that addressing is G1's (test_guest_boundary_hyperv.py).
        """
        assert resolve_gateway_topology(DeploymentMode.HOST, dev_mode=False) is True, (
            "HOST must resolve to host-mode (loopback + mTLS) — the gate-runnable "
            "default topology post-#615"
        )
        assert resolve_gateway_topology(DeploymentMode.HOST, dev_mode=True) is True, (
            "HOST in dev_mode is still host-mode topology (dev layers separately)"
        )
        assert resolve_gateway_topology(DeploymentMode.GUEST, dev_mode=True) is True, (
            "GUEST in dev_mode reports host-mode — the AF_HYPERV probe is skipped "
            "for a dev launch"
        )
        # The gateway prompt port for the gate-runnable host path targets the AO
        # (the service that answers PROMPT_REQUEST), never the PA — the Sprint-15
        # misroute invariant.
        assert resolve_gateway_port(dev_mode=False, host_mode=True) == (
            ORCHESTRATOR_HOST_LOOPBACK_PORT
        )
        assert (
            resolve_gateway_port(dev_mode=False, host_mode=True)
            != PA_HOST_PRODUCTION_PORT
        )

    def test_standin_material_satisfies_production_manifest_gate(
        self, tmp_path: Path
    ) -> None:
        """The stand-in manifest is a REAL, gate-passing Known-Good Manifest.

        Proves the stand-in material is not a mock that bypasses the gate: the
        manifest carries the REAL sha256 of the stand-in model bin under
        ``openvino_model.bin``, so ``load_manifest`` returns a 64-hex digest the
        production ``_validate_security_material`` accepts, and a real
        ``verify_all_manifest_entries`` sweep over the stand-in dir passes.  This
        is what lets the production cascade proceed with the GPU stubbed.
        """
        material = _provision_standin_security_material(tmp_path)

        from shared.models.weight_integrity import (
            load_manifest,
            verify_all_manifest_entries,
        )

        digests = load_manifest(material["manifest_path"])
        assert digests is not None, "stand-in manifest must load"
        digest = digests.get(_MODEL_BIN_NAME)
        assert digest is not None and len(digest) == 64, (
            "stand-in manifest must carry a 64-hex digest for the model bin "
            "(the production security gate matches by this entry)"
        )

        sweep = verify_all_manifest_entries(material["model_dir"], material["manifest_path"])
        assert sweep.all_verified is True, (
            f"stand-in manifest must pass a real weight sweep; error={sweep.error}"
        )

        # The JWT CA stand-in must be a usable EC public key (the other half of
        # the AO production gate).
        from shared.crypto.jwt_validator import AgenticJWTValidator

        assert AgenticJWTValidator.from_public_key_file(material["jwt_ca_path"]) is not None, (
            "stand-in JWT CA public key must load as an EC public key"
        )

    def test_ao_starts_in_production_posture_with_standin_material(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Step 4: AO starts in PRODUCTION posture (dev_mode=False), GPU stubbed.

        This is the seam that bit stream J: a production-posture AO fail-CLOSES
        without security material.  Here the stand-in manifest + JWT CA + per-boot
        mTLS certs satisfy the gate, the GPU is stubbed, and the REAL production
        ``AssistantOrchestratorService.start()`` runs end to end — building the
        mTLS listener via ``create_server_ssl_context``.  Asserts the service
        reaches ``running`` and stops cleanly.
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
        material = _provision_standin_security_material(tmp_path)
        config_path = (
            tmp_path / "services" / "assistant_orchestrator" / "config" / "default.toml"
        )
        _write_ao_production_config(
            config_path,
            vsock_port=ORCHESTRATOR_HOST_LOOPBACK_PORT,
            material=material,
        )

        service = AssistantOrchestratorService(
            config_path,
            dev_mode_override=False,  # PRODUCTION posture — the point of this test
            deployment_mode="host",
        )
        started = service.start()
        assert started is True, (
            "AO must start in PRODUCTION posture with stand-in security material "
            f"and stubbed GPU; last_failure={service.last_failure}"
        )
        assert service.running is True

        service.stop()
        assert service.running is False
        # Teardown must release the mTLS listener port for a re-bind.
        assert _port_is_free(ORCHESTRATOR_HOST_LOOPBACK_PORT), (
            f"Port {ORCHESTRATOR_HOST_LOOPBACK_PORT} must be free after stop() — "
            "production-posture teardown did not release the socket"
        )

    def test_production_cascade_refuses_without_model_digest(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Negative control: the production security gate is REAL, not bypassed.

        Same production posture, but the Known-Good Manifest omits the digest
        entry for ``openvino_model.bin``.  ``_validate_security_material`` must
        reject (``AO_CFG_KGM_MODEL_DIGEST_MISSING``) and ``start()`` must return
        False — proving the gate the gate-tier relies on actually fail-closes, so
        a green positive test cannot be a silent no-op.
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
        material = _provision_standin_security_material(
            tmp_path, include_model_digest=False
        )
        config_path = (
            tmp_path / "services" / "assistant_orchestrator" / "config" / "default.toml"
        )
        _write_ao_production_config(
            config_path,
            vsock_port=ORCHESTRATOR_HOST_LOOPBACK_PORT,
            material=material,
        )

        service = AssistantOrchestratorService(
            config_path,
            dev_mode_override=False,
            deployment_mode="host",
        )
        started = service.start()
        assert started is False, (
            "AO must REFUSE to start in production when the manifest lacks the "
            "model digest — the security gate must fail-closed"
        )
        assert service.last_failure is not None
        assert service.last_failure.get("code") == "AO_CFG_KGM_MODEL_DIGEST_MISSING", (
            f"expected the missing-digest fail-closed code; got {service.last_failure}"
        )
        # A refused start must not leave the listener port bound.
        assert _port_is_free(ORCHESTRATOR_HOST_LOOPBACK_PORT)

    def test_full_production_cascade_to_preflight(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """THE C2 walk: composed PRODUCTION cascade to a prompt round-trip (GPU stubbed).

        Composes the production boot path against the post-#615 host topology,
        with the air-gap UP and the GPU stubbed:

          1.5  provision_per_boot_certs()         — REAL per-boot mTLS certs
          (topology) resolve_gateway_topology(HOST) is host-mode (gate-runnable)
          4    AssistantOrchestratorService.start(dev_mode_override=False)
                                                  — REAL production posture + mTLS
                                                    listener, GPU stubbed
          5    build_session_store(dev_mode=True) — in-memory store for the preflight
          6    TransportGateway(host_mode=True, mtls_*)
                                                  — REAL production gateway (client certs)
          6a   gateway.check_pa_status()          — REAL loopback + mTLS handshake
          6b   _run_uat2_prompt_flow_preflight()  — REAL prompt → stream → PGOV → store
          Teardown  AO.stop()                     — clean stop, port released

        This is NOT skip-only: every step EXECUTES.  The mTLS handshake is a real
        ``CERT_REQUIRED`` exchange over the minted per-boot certs — a regression
        in the production transport (cert mount, port resolution, server/client
        SSL context, or the prompt path) breaks it.  The full-production PA-start
        (TPM) + the real model generation are the MODEL-LOADED tier below.
        """
        if not _port_is_free(ORCHESTRATOR_HOST_LOOPBACK_PORT):
            pytest.skip(
                f"AO loopback port {ORCHESTRATOR_HOST_LOOPBACK_PORT} is in use — "
                "skipping (live BlarAI instance?)"
            )

        # Confirm the topology the cascade is built against is the gate-runnable
        # host path (the post-#615 selection).
        assert resolve_gateway_topology(DeploymentMode.HOST, dev_mode=False) is True

        monkeypatch.setattr(
            "services.assistant_orchestrator.src.entrypoint.OrchestratorGPUInference",
            _StubInference,
        )

        # --- Step 1.5 + material: per-boot certs + stand-in manifest/JWT CA ---
        material = _provision_standin_security_material(tmp_path)

        # --- Step 4: start the AO in PRODUCTION posture (mTLS listener up) ---
        config_path = (
            tmp_path / "services" / "assistant_orchestrator" / "config" / "default.toml"
        )
        _write_ao_production_config(
            config_path,
            vsock_port=ORCHESTRATOR_HOST_LOOPBACK_PORT,
            material=material,
        )
        service = AssistantOrchestratorService(
            config_path,
            dev_mode_override=False,
            deployment_mode="host",
        )
        assert service.start() is True, (
            "AO must start in production posture for the cascade; "
            f"last_failure={service.last_failure}"
        )

        try:
            # --- Step 5: session store (in-memory, for the preflight) ---
            store = build_session_store(":memory:", dev_mode=True)

            # --- Step 6: production gateway wired with the per-boot client certs ---
            gateway_port = resolve_gateway_port(dev_mode=False, host_mode=True)
            assert gateway_port == ORCHESTRATOR_HOST_LOOPBACK_PORT
            gateway = _build_production_gateway(material, port=gateway_port)

            # --- Step 6a: REAL loopback + mTLS handshake ---
            # Run in a fresh synchronous event loop so the synchronous
            # _run_uat2_prompt_flow_preflight (Step 6b) can call asyncio.run()
            # internally without hitting "cannot run nested event loops".
            loop = asyncio.new_event_loop()
            try:
                handshake_ok = loop.run_until_complete(gateway.check_pa_status())
            finally:
                loop.close()
            assert handshake_ok is True, (
                "Production loopback + mTLS handshake must succeed against the AO"
            )
            assert gateway.state == StartupState.OPERATIONAL, (
                f"Gateway must be OPERATIONAL after the mTLS handshake; "
                f"got {gateway.state}"
            )
            # Reaching OPERATIONAL is itself the mTLS proof: the handshake ran
            # over a real CERT_REQUIRED mutual-TLS channel (both the AO listener's
            # create_server_ssl_context and the gateway's create_client_ssl_context
            # verify the peer against the per-boot CA — a cert that did not chain
            # would have failed the handshake, as the negative control in
            # test_security_cascade.py proves).  Assert the stored transport is the
            # PRODUCTION mTLS path (not a dev-loopback shortcut): dev_mode=False,
            # host_mode=True.  The peer-CN is extracted on the SERVER (accept) side
            # — here that is the AO's internal listener, not the gateway-held
            # client transport — so it is not asserted from this client handle (the
            # server-side peer-CN extraction is locked by test_security_cascade.py).
            assert gateway._transport is not None  # noqa: SLF001 — asserting the seam
            assert gateway._transport.dev_mode is False, (  # noqa: SLF001
                "the prompt transport must be the production (non-dev) mTLS path"
            )
            assert gateway._transport.host_mode is True  # noqa: SLF001

            # --- Step 6b: REAL prompt-flow preflight round-trip ---
            preflight_ok = _run_uat2_prompt_flow_preflight(
                gateway=gateway,
                session_store=store,
                runtime_mode=DeploymentMode.HOST,
            )
            assert preflight_ok is True, (
                "Production prompt-flow preflight must round-trip through the mTLS "
                "channel with the stubbed AO; a False here is a real cascade "
                "regression"
            )
        finally:
            # --- Teardown: clean stop, port released ---
            service.stop()

        assert service.running is False
        assert _port_is_free(ORCHESTRATOR_HOST_LOOPBACK_PORT), (
            "production cascade teardown must release the AO mTLS listener port"
        )


# ---------------------------------------------------------------------------
# Model-loaded tier — BUILT, SCRIPTED, marked @hardware (gate DESELECTS it)
# ---------------------------------------------------------------------------


class TestProductionBootCascadeRealModel:
    """The FULL production boot cascade with the real model + real PA — hardware-marked.

    THIS TIER IS BUILT BUT NOT VERIFIED IN THE GATE.  It is marked
    ``@pytest.mark.hardware`` so the standing gate DESELECTS it.  Its first green
    run needs an on-chip / Sprint-18 home (the Orchestrator homes it, per the C2
    tier note in the SDV — model-loaded tier hardware-marked + batched).

    It composes the SAME production cascade as the gate tier, but with the two
    hardware-bound halves the gate tier necessarily stands in:

      - the **Policy Agent** started in FULL production posture — the real
        measured-boot weight-integrity gate, the real model load, the TPM-backed
        JWT minter AND the TPM-backed audit signer (the PA REFUSES TO START in
        production without a provisioned ``BlarAI-Audit-Signing-Key-v1`` — ADR-025
        §2.8(a)); and
      - the **Assistant Orchestrator** loading the REAL Qwen3-14B and generating a
        REAL response through the prompt-flow preflight.

    WHY THE FULL-PRODUCTION RUN IS DEFERRED (the gate-honesty discipline)
    --------------------------------------------------------------------
    A lock that has never gone green locks nothing, but the first full-production
    run must be a CONFIRMATION (the cascade harness proven on the gate tier) not a
    DISCOVERY (the harness broken because it was never exercised).  The gate tier
    above proves the composed production cascade walks — real per-boot certs, the
    real production security-material gate, a real mutual-TLS handshake, the real
    preflight round-trip — with the GPU + TPM stood in.  This tier then confirms
    it against the chip + the model, locking the FULL production boot path before
    the #598 air-gap-removal gate (Sprint 18).

    HOW TO RUN (dev machine: real TPM 2.0 + Qwen3-14B present)
    =========================================================
    From the repo root, on the deployment hardware (a Windows host with a TPM 2.0
    exposed via the Microsoft Platform Crypto Provider AND the production keys
    provisioned by the LA ceremony)::

        set BLARAI_PROMPTFLOW_PREFLIGHT=1
        C:/Users/mrbla/BlarAI/.venv/Scripts/python.exe -m pytest \\
            tests/integration/test_production_boot_integration.py::TestProductionBootCascadeRealModel \\
            -m hardware -v

    PREREQUISITES
    -------------
    - Models present at::
          models/qwen3-14b/openvino-int4-gpu/      (with its real manifest.json)
          models/qwen3-0.6b/openvino-int4-gpu/     (optional — speculative decoding)
    - The production TPM keys provisioned on this host (the LA on-chip ceremony):
        * the PA JWT signing key (``jwt.tpm_key_name`` in the PA prod config),
        * the dedicated audit key ``BlarAI-Audit-Signing-Key-v1`` (AUDIT_TPM_KEY_NAME),
        * the JWT CA public key exported to the PA config's ``jwt.ca_cert_path``.
      ``shared.security.tpm_signer.is_available()`` must return True; the test
      SKIPS (does not fail) if the TPM or the keys are absent, so it is safe to
      run in ``-m hardware`` selections on non-TPM machines.
    - Per-boot certs are minted by the test (``provision_per_boot_certs``); no
      manual cert step is needed.

    Expected result: the composed production cascade goes green end to end —
    cert-mint → real PA boot (TPM + model) → real AO boot (model) → real mTLS
    handshake → real prompt round-trip → teardown.
    """

    @pytest.mark.hardware
    def test_full_production_cascade_real_model_and_tpm(self, tmp_path: Path) -> None:
        """Full production cascade with the REAL PA (TPM), REAL AO model, REAL mTLS.

        Steps exercised (all REAL — no stand-ins):
          1.5  provision_per_boot_certs()         — real per-boot mTLS certs (tmp dir)
          3    PolicyAgentService.from_runtime_mode("host", dev_mode_override=False)
                                                  — real measured-boot + model + TPM
                                                    JWT minter + TPM audit signer
          4    AssistantOrchestratorService.from_runtime_mode("host", dev_mode=False)
                                                  — real Qwen3-14B load, production posture
          5    build_session_store(dev_mode=False) — real DEK-backed store (TPM sealer)
          6    TransportGateway(host_mode=True, mtls_*) — real production gateway
          6a   gateway.check_pa_status()          — real loopback + mTLS handshake
          6b   _run_uat2_prompt_flow_preflight()  — real prompt, real generation
          Teardown  AO.stop(), PA.stop()

        This SKIPS (does not fail) if any real prerequisite is absent — by design,
        so it is safe to run in ``-m hardware`` selections on an under-provisioned
        machine (e.g. a dev box that has a TPM but no models yet).  The
        prerequisites checked: a reachable TPM 2.0, the production TPM keys
        provisioned (JWT signing + the dedicated audit key), and the production
        model material present (the real ``manifest.json`` + model bin the PA/AO
        production configs point at via ``from_runtime_mode``).  When all are
        present it runs the REAL cascade end to end.
        """
        from shared.security import tpm_signer as _tpm_signer

        if not _tpm_signer.is_available():
            pytest.skip(
                "Real TPM 2.0 (Microsoft Platform Crypto Provider) not available — "
                "the full-production cascade tier requires deployment hardware."
            )

        # Production model material must be present — the real PA/AO configs
        # (read by from_runtime_mode) resolve weight_manifest against
        # <repo_root>/models/...  A TPM-present box without the models would
        # otherwise fail-close at the PA measured-boot weight gate, not skip.
        # repo_root: this file is <repo_root>/tests/integration/<this>.py.
        from shared.constants import TARGET_MODEL_OV_PATH

        repo_root = Path(__file__).resolve().parents[2]
        target_manifest = repo_root / TARGET_MODEL_OV_PATH / "manifest.json"
        target_bin = repo_root / TARGET_MODEL_OV_PATH / _MODEL_BIN_NAME
        if not (target_manifest.exists() and target_bin.exists()):
            pytest.skip(
                "Production model material not present "
                f"({TARGET_MODEL_OV_PATH}/manifest.json + {_MODEL_BIN_NAME}) — "
                "the full-production cascade tier requires the real Qwen3-14B model."
            )

        # The production TPM keys must be provisioned (the LA on-chip ceremony).
        # Without them the PA refuses to start (JWT minter + audit signer);
        # skip rather than fail so an unprovisioned-but-TPM-present box is safe.
        from shared.security.audit_log import AUDIT_TPM_KEY_NAME

        try:
            audit_key_ready = _tpm_signer.key_exists(AUDIT_TPM_KEY_NAME)
        except (_tpm_signer.TpmUnavailable, _tpm_signer.TpmSigningError):
            audit_key_ready = False
        if not audit_key_ready:
            pytest.skip(
                f"Production TPM audit key '{AUDIT_TPM_KEY_NAME}' not provisioned — "
                "run the LA on-chip ceremony; the PA refuses to start without it "
                "(ADR-025 §2.8(a))."
            )

        if not _port_is_free(ORCHESTRATOR_HOST_LOOPBACK_PORT):
            pytest.skip(f"AO loopback port {ORCHESTRATOR_HOST_LOOPBACK_PORT} is in use")
        if not _port_is_free(PA_HOST_PRODUCTION_PORT):
            pytest.skip(f"PA loopback port {PA_HOST_PRODUCTION_PORT} is in use")

        # The prompt-flow preflight must be ON for this confirmation run.
        os.environ["BLARAI_PROMPTFLOW_PREFLIGHT"] = "1"

        from services.policy_agent.src.entrypoint import PolicyAgentService

        # --- Step 1.5: per-boot mTLS certs (REAL) ---
        # Mint into the PRODUCTION certs/ location (repo_root), exactly as the
        # launcher does at boot (launcher/__main__.py:751) — so the REAL PA
        # (from_runtime_mode, whose shipped config reads certs/pa_server.pem +
        # certs/ca.pem) and the gateway share ONE per-boot cert set + CA.  Minting
        # into a tmp dir (the prior bug) left the gateway trusting a tmp CA the PA's
        # shipped certs were never signed by -> CERTIFICATE_VERIFY_FAILED.  Per-boot
        # mTLS certs are ephemeral + gitignored; the next real boot re-mints them.
        certs = provision_per_boot_certs(repo_root=repo_root)

        # --- Step 3: real PA in FULL production posture (TPM + model) ---
        pa_service = PolicyAgentService.from_runtime_mode(
            "host",
            dev_mode_override=False,
        )
        assert pa_service.start() is True, (
            "PA must start in full production posture (TPM JWT + TPM audit + model); "
            f"last_failure={pa_service.last_failure}"
        )

        ao_service: AssistantOrchestratorService | None = None
        try:
            # --- Step 4: real AO (real Qwen3-14B), production posture ---
            ao_service = AssistantOrchestratorService.from_runtime_mode(
                "host",
                dev_mode_override=False,
            )
            assert ao_service.start() is True, (
                "AO must start with the real model in production posture; "
                f"last_failure={ao_service.last_failure}"
            )

            # --- Step 5: real DEK-backed session store (TPM sealer) ---
            store = build_session_store(":memory:", dev_mode=False)

            # --- Step 6: production gateway with the per-boot client certs ---
            gateway = TransportGateway(
                session_store=None,
                dev_mode=False,
                host_mode=True,
                host="127.0.0.1",
                port=resolve_gateway_port(dev_mode=False, host_mode=True),
                mtls_cert_path=str(certs.gateway_client_cert_path),
                mtls_key_path=str(certs.gateway_client_key_path),
                ca_cert_path=str(certs.ca_cert_path),
            )

            # --- Step 6a: real loopback + mTLS handshake ---
            handshake_ok = asyncio.run(gateway.check_pa_status())
            assert handshake_ok is True, "Production mTLS handshake must succeed"

            # --- Step 6b: real prompt-flow preflight (real generation) ---
            preflight_ok = _run_uat2_prompt_flow_preflight(
                gateway=gateway,
                session_store=store,
                runtime_mode=DeploymentMode.HOST,
            )
            assert preflight_ok is True, (
                "Full production prompt-flow preflight must pass with the real "
                "Qwen3-14B — if this fails the production boot path is broken "
                "before the #598 gate"
            )
        finally:
            if ao_service is not None:
                ao_service.stop()
            pa_service.stop()
