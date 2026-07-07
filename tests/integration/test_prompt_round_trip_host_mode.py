"""End-to-end gateway<->Orchestrator PROMPT_REQUEST round-trip (host-mode wiring).

WHY THIS FILE EXISTS — the gap that let the bug through
======================================================
Production host-mode boot rejected every user prompt::

    stream_tokens: error from Orchestrator: {'error': 'Unsupported message type: PROMPT_REQUEST'}

Root cause: ``launcher/__main__.py`` pointed the gateway's transport port at the
Policy Agent (PA, 5000) instead of the Assistant Orchestrator (AO, 5001) in
production host-mode.  The gateway uses ONE port for both its PA-liveness
handshake and its prompt connection
(``services/ui_gateway/src/transport.py`` ``self._port``).  Since S15-EA-4f the
PA answers ``HANDSHAKE_REQUEST`` (so Boot-Phase-3 looked healthy), but the PA
rejects ``PROMPT_REQUEST`` — so the misroute stayed invisible until a real
prompt arrived.  Dev-mode worked because it always targeted the AO.

No existing test exercised the REAL gateway<->AO prompt round-trip: the AO
entrypoint tests MOCK ``VsockListener`` entirely, and the ui_gateway IPC tests
drive the gateway against a hand-rolled mock TCP server, never the real AO
listener at the launcher-resolved port.  This file closes that gap:

  * ``test_prompt_reaches_ao_via_resolved_port`` — stands up the REAL AO IPC
    listener (GPU stubbed) at ``ORCHESTRATOR_HOST_LOOPBACK_PORT`` and a real
    ``TransportGateway`` pointed at ``resolve_gateway_port(host_mode=True)``,
    sends a real ``PROMPT_REQUEST`` and asserts a ``STREAM_TOKEN`` comes back
    with NO "Unsupported message type" error.  This FAILS on the pre-fix
    wiring (``resolve_gateway_port`` returning the PA port) and PASSES after.

  * ``test_prompt_to_pa_port_is_rejected`` — characterizes the bug directly:
    points the gateway at the PA's real listener and asserts the exact
    ``Unsupported message type: PROMPT_REQUEST`` symptom.  This documents WHY
    the misroute was fatal and is green before and after the fix.

ISOLATION
=========
Loopback + tmp paths only.  The rootdir ``conftest.py`` already redirects
``%LOCALAPPDATA%``/``HOME``/``XDG_DATA_HOME`` to a throwaway temp dir at pytest
process startup and unsets ``BLARAI_DEK_KEYSTORE``, so the real user-data
directory is never touched.  The AO/PA run in dev_mode (no mTLS, no TPM, no real
certs); GPU generation is stubbed so Qwen3-14B never loads.

The AO and PA bind the FIXED production ports (5001 / 5000) because the bug is a
fixed-port misroute and the gateway connects to whatever
``resolve_gateway_port`` returns — a fixed constant, not an ephemeral port.  If
a live BlarAI instance already holds those ports (e.g. the app is running on the
dev box), the affected test skips cleanly rather than fighting for the port; CI
runs with the ports free and gets the real assertion.
"""

from __future__ import annotations

import asyncio
import socket
import threading
import time
from pathlib import Path
from typing import Any, Iterator

import pytest

from launcher.__main__ import (
    ORCHESTRATOR_HOST_LOOPBACK_PORT,
    PA_HOST_PRODUCTION_PORT,
    resolve_gateway_port,
)
from services.assistant_orchestrator.src.entrypoint import (
    AssistantOrchestratorService,
)
from services.assistant_orchestrator.src.gpu_inference import GenerationResult
from services.policy_agent.src.ipc import PolicyAgentListener
from services.ui_gateway.src.transport import StartupState, TransportGateway
from shared.ipc.vsock import VsockAddress, VsockConfig

pytestmark = pytest.mark.slow


# Canned assistant reply the stubbed AO generator streams back.  Kept benign so
# the real PGOV output validator approves it (no untrusted content is present,
# so the leakage detector never engages).
_STUB_REPLY = "Hello from the orchestrator."


def _port_is_free(port: int) -> bool:
    """True if 127.0.0.1:port can be bound (no live service is holding it)."""
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

    ``generate_text`` invokes the streaming callback with the canned reply (so a
    real ``STREAM_TOKEN`` is emitted by the AO's ``_handle_prompt_request``) and
    returns a successful, tool-call-free ``GenerationResult`` so the handler
    proceeds to PGOV and ``GENERATION_COMPLETE``.
    """

    def __init__(self, *args, **kwargs) -> None:  # noqa: D401, ANN002, ANN003
        self.loaded = False

    def load_model(self) -> bool:
        self.loaded = True
        return True

    def unload(self) -> None:
        self.loaded = False

    def generate_text(self, prompt, *args, stream_callback=None, **kwargs):  # noqa: ANN001, ANN002, ANN003
        if stream_callback is not None:
            stream_callback(_STUB_REPLY)
        return GenerationResult(
            tokens=[1, 2, 3],
            text=_STUB_REPLY,
            token_count=max(1, len(_STUB_REPLY) // 4),
            latency_first_token_ms=0.0,
            latency_total_ms=0.0,
            was_preempted=False,
            resume_latency_ms=0.0,
            truncated=False,
            error=None,
        )


def _write_ao_dev_config(path: Path, *, vsock_port: int) -> None:
    """Write a minimal dev-mode AO config bound to ``vsock_port``.

    Mirrors ``services/assistant_orchestrator/tests/test_entrypoint.py``'s
    ``_write_minimal_config`` (the established AO-construction pattern), with the
    listener port parameterised.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"""
[runtime]
deployment_mode = "host"

[gpu]
device = "GPU"
priority = 1
model_dir = "models/qwen3-14b/openvino-int4-gpu"
weight_manifest = "models/qwen3-14b/openvino-int4-gpu/manifest.json"
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


@pytest.fixture()
def real_ao_listener(tmp_path, monkeypatch):
    """Start the REAL Assistant Orchestrator IPC listener (GPU stubbed).

    Binds the AO's production loopback port (``ORCHESTRATOR_HOST_LOOPBACK_PORT``)
    in dev_mode so no certs are needed.  Yields the bound port.  Skips if a live
    instance already holds the port.
    """
    if not _port_is_free(ORCHESTRATOR_HOST_LOOPBACK_PORT):
        pytest.skip(
            f"AO loopback port {ORCHESTRATOR_HOST_LOOPBACK_PORT} is in use "
            "(a live BlarAI instance?) — skipping real-listener round-trip."
        )

    # Patch the GPU inference class the entrypoint instantiates so start()
    # never loads Qwen3-14B; the real VsockListener / serve loop / handler run.
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
        f"AO service failed to start: {service.last_failure}"
    )
    try:
        yield ORCHESTRATOR_HOST_LOOPBACK_PORT
    finally:
        service.stop()


@pytest.fixture()
def real_pa_listener():
    """Start the REAL Policy Agent IPC listener on its production loopback port.

    Dev_mode (no mTLS).  The PA answers HANDSHAKE_REQUEST but rejects
    PROMPT_REQUEST — exactly the surface the misroute hit.  Yields the bound
    port.  Skips if a live instance already holds the port.
    """
    if not _port_is_free(PA_HOST_PRODUCTION_PORT):
        pytest.skip(
            f"PA loopback port {PA_HOST_PRODUCTION_PORT} is in use "
            "(a live BlarAI instance?) — skipping PA-rejector test."
        )

    config = VsockConfig(
        address=VsockAddress(cid=2, port=PA_HOST_PRODUCTION_PORT),
        timeout_ms=250,
        max_message_bytes=65536,
    )
    listener = PolicyAgentListener(config, dev_mode=True)
    assert listener.start() is True, "PA listener failed to start"

    stop_event = threading.Event()
    thread = threading.Thread(
        target=listener.serve_forever,
        args=(stop_event,),
        kwargs={"idle_sleep_s": 0.01},
        name="pa-listener-test-loop",
        daemon=True,
    )
    thread.start()
    try:
        yield PA_HOST_PRODUCTION_PORT
    finally:
        stop_event.set()
        listener.stop()
        thread.join(timeout=2.0)


async def _run_round_trip(port: int) -> list:
    """Drive handshake -> send_prompt -> stream_tokens against ``port``.

    Returns the list of yielded StreamTokens (empty on the misroute symptom).
    """
    gateway = TransportGateway(dev_mode=True, host="127.0.0.1", port=port)
    handshake_ok = await gateway.check_pa_status()
    assert handshake_ok is True
    assert gateway.state == StartupState.OPERATIONAL

    await gateway.send_prompt("sess-round-trip", "Say hello")
    return [tok async for tok in gateway.stream_tokens("sess-round-trip")]


class TestPromptRoundTripReachesOrchestrator:
    """The fix, end to end: PROMPT_REQUEST must reach the AO and stream back."""

    @pytest.mark.asyncio
    async def test_prompt_reaches_ao_via_resolved_port(
        self, real_ao_listener, caplog
    ) -> None:
        """Gateway -> resolve_gateway_port(host_mode) -> REAL AO -> STREAM_TOKEN.

        RED on pre-fix wiring: ``resolve_gateway_port(dev_mode=False,
        host_mode=True)`` returned the PA port (5000), so the gateway would
        connect to a port the AO is not listening on (or to the PA) and the
        prompt would be rejected / dropped — zero tokens, an error logged.
        GREEN after the fix: the resolved port is the AO's (5001), the real
        ``_handle_prompt_request`` runs, and the stubbed reply streams back.
        """
        resolved_port = resolve_gateway_port(dev_mode=False, host_mode=True)
        # Guard the invariant under test: the production-host-mode port the
        # launcher would hand the gateway must be the AO listener port.
        assert resolved_port == real_ao_listener

        with caplog.at_level("ERROR"):
            tokens = await _run_round_trip(resolved_port)

        # (a) No "Unsupported message type" error surfaced anywhere.
        joined_logs = " ".join(rec.getMessage() for rec in caplog.records)
        assert "Unsupported message type" not in joined_logs, joined_logs
        assert "error from Orchestrator" not in joined_logs, joined_logs

        # (c) A STREAM_TOKEN carrying the stubbed reply came back — proving the
        # AO's _handle_prompt_request (b) was reached and answered.
        assert tokens, "expected at least one STREAM_TOKEN from the AO"
        streamed = "".join(tok.token for tok in tokens)
        assert _STUB_REPLY in streamed, streamed


class TestPromptToPolicyAgentPortIsRejected:
    """Characterize the bug: the PA rejects PROMPT_REQUEST (the misroute)."""

    @pytest.mark.asyncio
    async def test_prompt_to_pa_port_is_rejected(
        self, real_pa_listener, caplog
    ) -> None:
        """Pointing the gateway at the PA port reproduces the exact symptom.

        This is what the buggy launcher did: it sent PROMPT_REQUEST to the PA's
        port.  The PA handshakes fine (Boot-Phase-3 looks healthy) but rejects
        the prompt with "Unsupported message type: PROMPT_REQUEST", which the
        gateway logs as "stream_tokens: error from Orchestrator" and yields no
        tokens.
        """
        with caplog.at_level("ERROR"):
            tokens = await _run_round_trip(real_pa_listener)

        # The misroute yields zero tokens...
        assert tokens == []
        # ...and surfaces the precise production symptom in the gateway log.
        joined_logs = " ".join(rec.getMessage() for rec in caplog.records)
        assert "error from Orchestrator" in joined_logs, joined_logs
        assert "Unsupported message type: PROMPT_REQUEST" in joined_logs, joined_logs

    def test_resolve_gateway_port_does_not_target_pa(self) -> None:
        """Belt-and-suspenders: the fix never routes prompts to the PA port."""
        assert (
            resolve_gateway_port(dev_mode=False, host_mode=True)
            != PA_HOST_PRODUCTION_PORT
        )


# ===========================================================================
# C2 (GAP-6) — model-loaded tier of the IPC-routing regression lock
# ===========================================================================
# The stub scenario above (test_prompt_reaches_ao_via_resolved_port) proves the
# gateway -> resolve_gateway_port(host_mode) -> AO -> STREAM_TOKEN wiring with the
# GPU stubbed.  GAP-6 (the Sprint-16 coverage audit) asked for the SAME lock
# driven by the REAL Qwen3-14B: that the ISS-10 misroute class ("Unsupported
# message type: PROMPT_REQUEST" / "error from Orchestrator") does not reappear
# under REAL load, not only with a canned stub reply.
#
# This tier mirrors the stub scenario but lets the REAL OrchestratorGPUInference
# load instead of monkeypatching _StubInference.  It is marked ``hardware`` (on
# top of the module's ``slow``), so the standing gate DESELECTS it; its first
# green run is the GPU box (the Orchestrator homes it).  It SKIPS cleanly when
# the weights are absent (the worktree / any non-GPU machine).
#
# Posture note: this tier stays in ``dev_mode=True`` to mirror the existing stub
# scenario's contract exactly — the variable under test here is REAL-MODEL vs
# stub, holding the rest of the wiring constant.  The production-mTLS posture
# (dev_mode=False, real certs) is C1's bar and lives in
# tests/harness/test_model_loaded_round_trip.py.

# Repo root: tests/integration/<file> -> parents[2] is the repo root, where the
# real model weights live.  Mirrors tests/harness/test_sprint12_real_model.py.
_REPO_ROOT = Path(__file__).resolve().parents[2]
_MODEL_LOADED_REL = "models/qwen3-14b/openvino-int4-gpu"
_DRAFT_LOADED_REL = "models/qwen3-0.6b-pruned-6l/openvino-int8-gpu"
_MODEL_LOADED_PROMPT = "Say hello in one short, friendly sentence."


def _write_ao_dev_config_model_loaded(path: Path, *, vsock_port: int) -> None:
    """Write a dev-mode AO config pointed at the REAL model dir + manifest.

    Same shape as ``_write_ao_dev_config`` (the stub helper) but with the real
    ``model_dir`` / ``draft_model_dir`` / ``weight_manifest`` paths (relative, so
    the AO's ``_resolve_path`` resolves them against the repo root) so the real
    14B loads.  ``dev_mode=true`` (no mTLS) to mirror the stub scenario's
    contract — the variable under test is real-model-vs-stub, not the transport
    security layer (that is C1).  ``require_signed_manifest`` is left at its
    config default (unset -> False here) because dev_mode short-circuits the
    signature-material validation; the digest sweep in ``load_model()`` still runs
    against the real manifest.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"""
[runtime]
deployment_mode = "host"

[gpu]
device = "GPU"
priority = 1
model_dir = "{_MODEL_LOADED_REL}"
weight_manifest = "{_MODEL_LOADED_REL}/manifest.json"
draft_model_dir = "{_DRAFT_LOADED_REL}"
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
timeout_ms = 30000
max_message_bytes = 65536

[pgov]
cosine_similarity_threshold = 0.85
pii_mode = "off"
leakage_detection_enabled = false
""".strip(),
        encoding="utf-8",
    )


@pytest.fixture(scope="module")
def model_loaded_engine() -> Iterator[Any]:
    """Load the REAL Qwen3-14B ONCE for the module, or skip if absent.

    Mirrors ``tests/harness/test_sprint12_real_model.py``'s engine discipline:
    OpenVINO does not release GPU memory in-process, so a per-test reload risks
    OOM — load once, share, unload at module teardown.  Loaded directly so the
    weights are paid for once; the listener fixture injects this engine into the
    real service boot.
    """
    model_dir = _REPO_ROOT / _MODEL_LOADED_REL
    if not (model_dir / "openvino_model.bin").exists():
        pytest.skip(
            f"Real Qwen3-14B weights absent: {model_dir} — C2 model-loaded "
            "IPC-routing lock requires the model on disk (GPU box)."
        )

    from services.assistant_orchestrator.src.gpu_inference import (
        OrchestratorGPUInference,
    )

    draft_dir = _REPO_ROOT / _DRAFT_LOADED_REL
    eng = OrchestratorGPUInference(
        model_dir=str(model_dir),
        device="GPU",
        manifest_path=str(model_dir / "manifest.json"),
        draft_model_dir=str(draft_dir) if draft_dir.exists() else None,
    )
    if not eng.load_model():
        raise RuntimeError(
            "Real Qwen3-14B load_model() returned False despite weights on disk."
        )
    yield eng
    if hasattr(eng, "unload"):
        eng.unload()


@pytest.fixture()
def real_ao_listener_model_loaded(
    model_loaded_engine: Any, tmp_path, monkeypatch
) -> Iterator[int]:
    """Start the REAL AO IPC listener driving the REAL model (GPU NOT stubbed).

    The model-loaded twin of ``real_ao_listener``: identical wiring (dev_mode,
    production loopback port, real VsockListener / serve loop / handler) EXCEPT
    the GPU inference class is patched to return the pre-loaded module engine
    instead of ``_StubInference`` — so the real ``_handle_prompt_request`` drives
    real Qwen3-14B generation.  Skips if a live instance holds the port; stops
    the service in ``finally`` (port-5001 leak detector #630 stays green).
    """
    if not _port_is_free(ORCHESTRATOR_HOST_LOOPBACK_PORT):
        pytest.skip(
            f"AO loopback port {ORCHESTRATOR_HOST_LOOPBACK_PORT} is in use "
            "(a live BlarAI instance?) — skipping model-loaded round-trip."
        )

    class _PreloadedInference:
        """Returns the pre-loaded module engine; load_model() does not recompile."""

        def __init__(self, *args: Any, **kwargs: Any) -> None:
            self._engine = model_loaded_engine

        def __getattr__(self, name: str) -> Any:
            return getattr(self._engine, name)

        def load_model(self) -> bool:
            return bool(getattr(self._engine, "loaded", True))

        def unload(self) -> None:
            return None  # module-scoped engine fixture owns unload

    monkeypatch.setattr(
        "services.assistant_orchestrator.src.entrypoint.OrchestratorGPUInference",
        _PreloadedInference,
    )

    config_path = (
        tmp_path
        / "services"
        / "assistant_orchestrator"
        / "config"
        / "default.toml"
    )
    _write_ao_dev_config_model_loaded(
        config_path, vsock_port=ORCHESTRATOR_HOST_LOOPBACK_PORT
    )

    service = AssistantOrchestratorService(
        config_path,
        dev_mode_override=True,
        deployment_mode="host",
    )
    assert service.start() is True, (
        f"model-loaded AO service failed to start: {service.last_failure}"
    )
    try:
        yield ORCHESTRATOR_HOST_LOOPBACK_PORT
    finally:
        service.stop()


class TestPromptRoundTripModelLoaded:
    """C2: the ISS-10 IPC-routing lock, driven by the REAL model under load."""

    @pytest.mark.hardware
    @pytest.mark.asyncio
    async def test_prompt_reaches_ao_via_resolved_port_model_loaded(
        self, real_ao_listener_model_loaded, caplog
    ) -> None:
        """Gateway -> resolve_gateway_port(host_mode) -> REAL AO -> STREAM_TOKEN.

        The model-loaded tier of ``test_prompt_reaches_ao_via_resolved_port``:
        the REAL Qwen3-14B generates the reply instead of ``_StubInference``.
        Asserts:
          * ``resolve_gateway_port(dev_mode=False, host_mode=True)`` resolves to
            the AO loopback port (the launcher invariant, under real load);
          * a real ``PROMPT_REQUEST`` reaches the real AO and a ``STREAM_TOKEN``
            comes back carrying real model output;
          * NO "Unsupported message type: PROMPT_REQUEST" / "error from
            Orchestrator" misroute appears under real load (the ISS-10 class).
        """
        resolved_port = resolve_gateway_port(dev_mode=False, host_mode=True)
        assert resolved_port == real_ao_listener_model_loaded

        start = time.perf_counter()
        with caplog.at_level("ERROR"):
            tokens = await _run_round_trip(resolved_port)
        total_ms = (time.perf_counter() - start) * 1000.0

        # No misroute symptom anywhere (the ISS-10 regression class).
        joined_logs = " ".join(rec.getMessage() for rec in caplog.records)
        assert "Unsupported message type: PROMPT_REQUEST" not in joined_logs, joined_logs
        assert "error from Orchestrator" not in joined_logs, joined_logs

        # A STREAM_TOKEN carrying REAL model output came back — proving the real
        # _handle_prompt_request was reached and answered under real generation.
        assert tokens, "expected at least one STREAM_TOKEN from the real AO"
        streamed = "".join(tok.token for tok in tokens)
        assert streamed.strip(), f"real-model stream was empty: {streamed!r}"

        # Parseable perf line for the Orchestrator's GPU-box capture.
        print(f"C2_PERF total_ms={total_ms:.1f} response_chars={len(streamed)}")
