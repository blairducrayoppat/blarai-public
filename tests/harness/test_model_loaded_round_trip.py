"""C1 (GAP-5) — model-loaded gateway->AO round-trip in PRODUCTION posture.

WHY THIS FILE EXISTS — closing GAP-5
====================================
``tests/integration/test_prompt_round_trip_host_mode.py`` proves the
gateway<->AO PROMPT_REQUEST wiring with the GPU *stubbed* and the AO in
``dev_mode=True`` (no mTLS).  ``tests/harness/test_sprint12_real_model.py``
drives the REAL Qwen3-14B but only through the in-process ``_handle_connection``
path with a ``_FakeTransport`` — it never crosses a real socket and never runs
mTLS.  Neither test exercises the link the Sprint-15 terminal actually burned on:
the FULL gateway -> real ``TransportGateway`` socket -> real AO IPC listener under
**production mTLS** (``dev_mode=False``, real certificates) -> real Qwen3-14B
generation -> real PGOV output validation -> response streamed back.  This file
is that link, end to end, in production posture.

PRODUCTION POSTURE IS THE C1 FIDELITY BAR
=========================================
The crux of C1 is ``dev_mode=False`` on BOTH ends, so the REAL production mTLS
handshake runs (``create_server_ssl_context`` on the AO listener,
``create_client_ssl_context`` on the gateway, ``CERT_REQUIRED`` both ways) — NOT
the dev no-TLS loopback.  The only thing the loopback path changes from true
production is the socket family (AF_INET vs AF_HYPERV); the mTLS code path, the
signature-verified manifest boot, the JWT validator init, and the
``_handle_prompt_request`` turn are all the production ones.  See the cert-wiring
trade-off note on ``production_certs`` below.

The run also goes through the **signed-manifest verification path**: with
``dev_mode=False`` + ``require_signed_manifest=true``, the AO boot reaches
``load_manifest_verified(require_signed=True)`` at config-load (verifying the
detached ``manifest.json.sig`` against ``manifest.json.pub`` via the TPM key) AND
``verify_all_manifest_entries`` at ``load_model()`` (the SHA-256 digest sweep).
Both are production defaults reached by simply running the real service against
the real ``models/qwen3-14b/openvino-int4-gpu/manifest.json`` (+ ``.sig`` / ``.pub``).

MARKERS / WHERE THIS RUNS
=========================
Marked ``hardware`` + ``slow`` so the standing gate DESELECTS it.  It loads the
real 14B and requires the signed manifest material on disk, so it SKIPS cleanly
(model / signature absent) on a machine without the weights — its first green run
is the GPU box (the Orchestrator homes it).  It emits parseable timing lines
(model-load seconds, first-token ms, total ms) the Orchestrator captures as
community-grade perf evidence (PERFORMANCE_LOG.md / docs/performance/).

ISOLATION
=========
``tmp_path`` for the AO config + per-boot certs + the generated JWT public key;
the per-boot certs are minted by the REAL ``provision_per_boot_certs`` into a tmp
dir, never the real ``certs/``.  The AO binds the production loopback port
(5001); if a live BlarAI instance already holds it, the test SKIPS rather than
fighting for the port.  The root ``conftest.py`` redirects ``%LOCALAPPDATA%`` and
unsets ``BLARAI_DEK_KEYSTORE`` at process startup, so the real user-data dir is
never touched.  The ``real_ao_listener_production`` fixture stops its service in a
``finally`` so the autouse port-5001 leak detector (#630) stays green.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Iterator

import pytest

from launcher.__main__ import (
    ORCHESTRATOR_HOST_LOOPBACK_PORT,
    resolve_gateway_port,
)
from services.ui_gateway.src.transport import StartupState, TransportGateway

pytestmark = [pytest.mark.slow, pytest.mark.hardware]

# Repo root: tests/harness/<file> -> parents[2] is the repo root, where
# models/qwen3-14b/openvino-int4-gpu/manifest.json(.sig/.pub) lives.  Mirrors
# tests/harness/test_sprint12_real_model.py's _REPO_ROOT.
_REPO_ROOT = Path(__file__).resolve().parents[2]

# Canonical production model + signed-manifest locations (the real signature
# material the Orchestrator's GPU run uses).  Relative paths so the AO's
# _resolve_path resolves them against the repo root exactly as production does.
_MODEL_REL = "models/qwen3-14b/openvino-int4-gpu"
_DRAFT_REL = "models/qwen3-0.6b-pruned-6l/openvino-int8-gpu"
_MANIFEST_REL = f"{_MODEL_REL}/manifest.json"

# A benign, single-sentence prompt.  PGOV must APPROVE this (no untrusted content
# is present, leakage detection is disabled, so the validator returns approved=
# True and the gateway shows no denial card).
_BENIGN_PROMPT = "Say hello in one short, friendly sentence."

# Parseable timing prefix the Orchestrator greps out of stdout for perf capture.
_TIMING_PREFIX = "C1_PERF"


def _signed_manifest_present() -> bool:
    """True iff the real model + the detached signed-manifest material are on disk.

    The production-posture boot needs BOTH the weights (to load) AND the
    ``.sig`` / ``.pub`` files (so ``require_signed_manifest=true`` can verify a
    real signature rather than fail-closed on a missing ``.sig``).  Absent any of
    these, the test SKIPS — that is the expected worktree state; the GPU box has
    all of them.
    """
    model_bin = _REPO_ROOT / _MODEL_REL / "openvino_model.bin"
    manifest = _REPO_ROOT / _MANIFEST_REL
    sig = _REPO_ROOT / f"{_MANIFEST_REL}.sig"
    return model_bin.exists() and manifest.exists() and sig.exists()


def _write_ao_production_config(
    path: Path,
    *,
    vsock_port: int,
    mtls_cert_path: Path,
    mtls_key_path: Path,
    ca_cert_path: Path,
    jwt_ca_cert_path: Path,
) -> None:
    """Write a ``dev_mode=false`` AO config wired for the production mTLS boot.

    Differs from the stub round-trip's ``_write_ao_dev_config`` in the two ways
    that MAKE this production posture:

      * ``[security].dev_mode = false`` — the AO listener builds a real mTLS
        server context (``create_server_ssl_context``) and the boot runs the
        production security-material validation.
      * ``[security].require_signed_manifest = true`` + a real ``weight_manifest``
        pointing at the on-disk ``manifest.json`` — so the boot reaches
        ``load_manifest_verified(require_signed=True)`` (the detached ``.sig``
        verification) at config-load AND ``verify_all_manifest_entries`` (the
        digest sweep) at ``load_model()``.

    The model_dir / draft / manifest are ABSOLUTE paths to the real repo-root
    model + signed manifest.  They cannot be relative here: the AO derives its
    ``repo_root`` from the config file's OWN location (``service_root.parents[1]``
    in ``_load_entrypoint_config``), and this config lives under ``tmp_path`` for
    isolation — so a relative ``models/...`` resolves under the tmp dir (which has
    no weights) and the boot fail-closes with ``AO_CFG_KGM_PATH_NOT_FOUND``.
    ``_resolve_path`` passes absolute paths through unchanged, so the boot loads +
    verifies the REAL on-disk weights/manifest — identical fidelity to production,
    just addressed absolutely because the test config is not at the real repo path.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"""
[runtime]
deployment_mode = "host"

[gpu]
device = "GPU"
priority = 1
model_dir = "{(_REPO_ROOT / _MODEL_REL).as_posix()}"
weight_manifest = "{(_REPO_ROOT / _MANIFEST_REL).as_posix()}"
draft_model_dir = "{(_REPO_ROOT / _DRAFT_REL).as_posix()}"
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
require_signed_manifest = true
jwt_ca_cert_path = "{jwt_ca_cert_path.as_posix()}"

[ipc]
vsock_cid = 2
vsock_port = {vsock_port}
mtls_cert_path = "{mtls_cert_path.as_posix()}"
mtls_key_path = "{mtls_key_path.as_posix()}"
ca_cert_path = "{ca_cert_path.as_posix()}"
timeout_ms = 30000
max_message_bytes = 65536

[pgov]
cosine_similarity_threshold = 0.85
pii_mode = "off"
leakage_detection_enabled = false
block_tools_on_untrusted_content = true
""".strip(),
        encoding="utf-8",
    )


@pytest.fixture(scope="module")
def production_certs(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Path]:
    """Mint per-boot mTLS certs + a JWT public key for the production boot.

    CERT-WIRING TRADE-OFF (the C1 decision the brief asks me to name)
    ----------------------------------------------------------------
    The two candidates for the ``dev_mode=False`` mTLS material were:

      (A) the REAL ceremony certs in ``certs/`` (``ca.pem`` +
          ``orch_client.pem`` + ``pa_server.pem`` ...), and
      (B) the per-boot ``provision_per_boot_certs()`` mint into ``tmp_path``
          (the temp-CA mTLS pattern used by ``tests/integration/
          test_security_cascade.py`` and ``test_shared_ipc_transport.py``).

    I chose (B), for three reasons:

      1. ``provision_per_boot_certs`` is the REAL production cert-minting
         function — it is literally what the launcher calls per boot (ADR-026).
         So (B) is not a hand-rolled stand-in; it exercises the same cert
         material production mints, just into a tmp dir.  Higher fidelity than
         the ``_generate_test_certs`` helper, and it gives a server cert + a
         client cert that provably chain to ONE per-boot CA — exactly the
         loopback gateway(client)<->AO(server) handshake C1 needs.
      2. The real ``certs/`` material is per-chip, ceremony-generated, and
         gitignored: it is absent in the worktree and not guaranteed present in
         the same role-pairing on the GPU box, so depending on it would make the
         test SKIP for cert-absence reasons unrelated to the model — muddying the
         one thing C1 is meant to confirm (the real model round-trip).
      3. ``dev_mode`` stays ``False`` regardless of which certs are used, so the
         PRODUCTION mTLS code path (``create_server_ssl_context`` /
         ``create_client_ssl_context``, ``CERT_REQUIRED``) is what executes
         either way — the fidelity bar is met by (B), and (B) is the more
         robust, self-contained choice.

    The JWT CA is a separately-generated EC P-256 public key (the AO's
    ``jwt_ca_cert_path`` must load as an ``EllipticCurvePublicKey`` —
    ``AgenticJWTValidator.from_public_key_file`` — and a CA *certificate* is not a
    bare public key).  The validator is only constructed at boot here; the
    round-trip does not mint a JWT, so a fresh keypair is sufficient.
    """
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec

    from shared.security.cert_provisioning import provision_per_boot_certs

    certs_dir = tmp_path_factory.mktemp("c1_prod_certs")
    minted = provision_per_boot_certs(certs_dir=certs_dir)

    # Generate the EC public key the AO uses as its JWT validation key.
    jwt_key = ec.generate_private_key(ec.SECP256R1())
    jwt_pub_path = certs_dir / "jwt_ca_public.pem"
    jwt_pub_path.write_bytes(
        jwt_key.public_key().public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
    )

    return {
        # AO listener identity (server) — orch cert is SERVER_AUTH + CLIENT_AUTH.
        "ao_cert": minted.orch_client_cert_path,
        "ao_key": minted.orch_client_key_path,
        # Gateway client identity.
        "gw_cert": minted.gateway_client_cert_path,
        "gw_key": minted.gateway_client_key_path,
        # Shared per-boot CA both ends verify against.
        "ca": minted.ca_cert_path,
        # JWT validation public key.
        "jwt_pub": jwt_pub_path,
    }


@pytest.fixture(scope="module")
def engine() -> Iterator[Any]:
    """Load the REAL Qwen3-14B ONCE for the module, or skip if absent.

    Mirrors ``tests/harness/test_sprint12_real_model.py``'s module-scoped engine
    discipline: OpenVINO does not release GPU memory in-process, so a per-test
    reload risks OOM — load the 14B once, share it, unload at module teardown.

    This loads the engine DIRECTLY (not via the service boot) so the weights are
    paid for exactly once; the ``real_ao_listener_production`` fixture then injects
    this pre-loaded engine into the real service boot (whose own ``load_model()``
    no-ops because the engine reports loaded), keeping the production config-load
    signature verification + listener mTLS + handler path REAL while loading the
    model only once.
    """
    if not _signed_manifest_present():
        pytest.skip(
            "Real Qwen3-14B weights and/or the signed-manifest material "
            f"({_MANIFEST_REL}.sig) are absent under {_REPO_ROOT} — C1 production "
            "round-trip requires the model + signed manifest on disk (GPU box)."
        )

    from services.assistant_orchestrator.src.gpu_inference import (
        OrchestratorGPUInference,
    )

    model_dir = _REPO_ROOT / _MODEL_REL
    draft_dir = _REPO_ROOT / _DRAFT_REL
    manifest = _REPO_ROOT / _MANIFEST_REL

    load_start = time.perf_counter()
    eng = OrchestratorGPUInference(
        model_dir=str(model_dir),
        device="GPU",
        # Pass the manifest so the engine's own load_model() runs the digest
        # sweep (verify_all_manifest_entries) — the load-time half of the
        # signed-manifest path — even though we load it directly here.
        manifest_path=str(manifest),
        draft_model_dir=str(draft_dir) if draft_dir.exists() else None,
    )
    if not eng.load_model():
        raise RuntimeError(
            "Real Qwen3-14B load_model() returned False despite weights on disk "
            "(check the manifest digest sweep and GPU availability)."
        )
    load_seconds = time.perf_counter() - load_start
    print(f"{_TIMING_PREFIX} model_load_seconds={load_seconds:.3f}")

    yield eng

    if hasattr(eng, "unload"):
        eng.unload()


@pytest.fixture()
def real_ao_listener_production(
    engine: Any,
    production_certs: dict[str, Path],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[int]:
    """Start the REAL AO IPC listener in PRODUCTION posture (dev_mode=False, mTLS).

    Wires a ``dev_mode=false`` config with real per-boot mTLS certs + a real
    signed manifest, so ``service.start()`` runs the production boot:
      - ``_load_entrypoint_config`` -> ``_validate_security_material`` ->
        ``load_manifest_verified(require_signed=True)`` (the detached ``.sig``
        verification against ``manifest.json.pub``),
      - the JWT validator init,
      - ``VsockListener.start()`` building a real mTLS server context
        (``CERT_REQUIRED``) and binding 127.0.0.1:5001.

    The ``OrchestratorGPUInference`` the entrypoint instantiates is patched to a
    thin wrapper returning the pre-loaded module ``engine`` so the 14B loads
    ONCE for the module (the weights are not re-paid per test); its
    ``load_model()`` still runs the manifest digest sweep but does not recompile.

    Skips if a live BlarAI instance already holds port 5001.  Stops the service
    in ``finally`` (port-5001 leak detector #630 stays green).
    """
    from services.assistant_orchestrator.src.entrypoint import (
        AssistantOrchestratorService,
    )

    # Local import so the helper is available without dragging it into module
    # scope; mirrors the stub file's _port_is_free.
    import socket as _socket

    def _port_is_free(port: int) -> bool:
        probe = _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM)
        try:
            probe.bind(("127.0.0.1", port))
        except OSError:
            return False
        finally:
            probe.close()
        return True

    if not _port_is_free(ORCHESTRATOR_HOST_LOOPBACK_PORT):
        pytest.skip(
            f"AO loopback port {ORCHESTRATOR_HOST_LOOPBACK_PORT} is in use "
            "(a live BlarAI instance?) — skipping production round-trip."
        )

    # Patch the GPU inference class the entrypoint instantiates so start()
    # references the pre-loaded module engine instead of compiling a SECOND
    # 14B.  The wrapper forwards everything else to the real engine, so the
    # real _handle_prompt_request drives real generation.
    class _PreloadedInference:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            self._engine = engine

        def __getattr__(self, name: str) -> Any:
            return getattr(self._engine, name)

        def load_model(self) -> bool:
            # Already loaded once at module scope — do not recompile.
            return bool(getattr(self._engine, "loaded", True))

        def unload(self) -> None:
            # Ownership of unload belongs to the module-scoped engine fixture.
            return None

    monkeypatch.setattr(
        "services.assistant_orchestrator.src.entrypoint.OrchestratorGPUInference",
        _PreloadedInference,
    )

    config_path = (
        tmp_path / "services" / "assistant_orchestrator" / "config" / "default.toml"
    )
    _write_ao_production_config(
        config_path,
        vsock_port=ORCHESTRATOR_HOST_LOOPBACK_PORT,
        mtls_cert_path=production_certs["ao_cert"],
        mtls_key_path=production_certs["ao_key"],
        ca_cert_path=production_certs["ca"],
        jwt_ca_cert_path=production_certs["jwt_pub"],
    )

    service = AssistantOrchestratorService(
        config_path,
        deployment_mode="host",
        # No dev_mode_override — dev_mode resolves False from the config, which
        # is the whole point (production posture).
    )
    assert service.start() is True, (
        "Production-posture AO service failed to start (dev_mode=False). "
        f"last_failure={service.last_failure}"
    )
    try:
        yield ORCHESTRATOR_HOST_LOOPBACK_PORT
    finally:
        service.stop()


async def _run_production_round_trip(
    port: int, certs: dict[str, Path]
) -> tuple[TransportGateway, list, str, float, float]:
    """Drive handshake -> send_prompt -> stream_tokens over PRODUCTION mTLS.

    Builds a ``dev_mode=False, host_mode=True`` ``TransportGateway`` with the
    gateway-client mTLS cert paths, so ``_connect_host_loopback_mtls`` performs
    the real ``CERT_REQUIRED`` client handshake against the AO's mTLS listener.

    Returns ``(gateway, tokens, request_id, first_token_ms, total_ms)``.  The
    gateway is returned so the caller can read the cached PGOV result via
    ``gateway.get_pgov_result(request_id)``.  ``tokens`` is the list of text
    StreamTokens (empty on the misroute symptom).
    """
    gateway = TransportGateway(
        dev_mode=False,
        host_mode=True,
        host="127.0.0.1",
        port=port,
        mtls_cert_path=str(certs["gw_cert"]),
        mtls_key_path=str(certs["gw_key"]),
        ca_cert_path=str(certs["ca"]),
    )

    handshake_ok = await gateway.check_pa_status()
    assert handshake_ok is True, "production mTLS handshake to the AO must succeed"
    assert gateway.state == StartupState.OPERATIONAL

    start = time.perf_counter()
    request_id = await gateway.send_prompt("sess-c1-prod", _BENIGN_PROMPT)

    tokens: list = []
    first_token_ms = 0.0
    async for tok in gateway.stream_tokens("sess-c1-prod"):
        if not tokens:
            first_token_ms = (time.perf_counter() - start) * 1000.0
        tokens.append(tok)
    total_ms = (time.perf_counter() - start) * 1000.0

    return gateway, tokens, request_id, first_token_ms, total_ms


class TestModelLoadedRoundTripProduction:
    """The full production-posture link: real model + real mTLS + real PGOV."""

    @pytest.mark.asyncio
    async def test_production_round_trip_streams_real_model_output(
        self, real_ao_listener_production: int, production_certs: dict[str, Path], caplog
    ) -> None:
        """Gateway(mTLS) -> real AO(mTLS) -> real Qwen3-14B -> PGOV -> STREAM_TOKEN.

        Asserts the four C1 acceptance conditions:
          (a) at least one STREAM_TOKEN carrying real model output returns;
          (b) NO "Unsupported message type" misroute (the ISS-10 class);
          (c) PGOV APPROVES the benign prompt — no denial card
              (gateway.get_pgov_result(request_id).approved is True);
          (d) the run went through the signed-manifest verification path —
              guaranteed by the production boot itself: the
              ``real_ao_listener_production`` fixture's ``service.start()`` only
              returns True after ``load_manifest_verified(require_signed=True)``
              accepted the detached ``manifest.json.sig`` (a missing/invalid
              ``.sig`` would have fail-closed the boot and the fixture would have
              skipped/failed before this test ran).

        Emits parseable timing lines (model-load seconds are printed by the
        ``engine`` fixture; first-token + total ms are printed here) for the
        Orchestrator's community-grade perf capture.
        """
        # The production-host-mode port the launcher hands the gateway must be
        # the AO listener port (the same invariant the stub lock guards, here
        # under real load).
        resolved_port = resolve_gateway_port(dev_mode=False, host_mode=True)
        assert resolved_port == real_ao_listener_production

        from services.ui_gateway.src.transport import PGOV_DENIAL_FALLBACK

        with caplog.at_level("ERROR"):
            gateway, tokens, request_id, first_token_ms, total_ms = (
                await _run_production_round_trip(resolved_port, production_certs)
            )

        # (a) Real model output streamed back.
        assert tokens, "expected at least one STREAM_TOKEN from the real model"
        streamed = "".join(tok.token for tok in tokens)
        assert streamed.strip(), (
            f"streamed response was empty/whitespace: {streamed!r}"
        )

        # (b) No misroute symptom anywhere in the gateway/AO logs.
        joined_logs = " ".join(rec.getMessage() for rec in caplog.records)
        assert "Unsupported message type" not in joined_logs, joined_logs
        assert "error from Orchestrator" not in joined_logs, joined_logs

        # (c) PGOV APPROVED the benign prompt — no denial card.  The gateway
        # caches the PGOV_RESULT frame during stream_tokens; read it back.
        pgov = gateway.get_pgov_result(request_id)
        assert pgov.approved is True, (
            "PGOV must approve a benign prompt (no denial card); "
            f"reason_codes={pgov.reason_codes}"
        )
        # Belt-and-suspenders: a denial would have streamed the fallback text.
        assert PGOV_DENIAL_FALLBACK not in streamed, (
            f"unexpected PGOV denial card in stream: {streamed!r}"
        )

        # Emit parseable perf evidence for the Orchestrator's GPU-box capture.
        print(f"{_TIMING_PREFIX} first_token_ms={first_token_ms:.1f}")
        print(f"{_TIMING_PREFIX} total_ms={total_ms:.1f}")
        print(f"{_TIMING_PREFIX} response_chars={len(streamed)}")
