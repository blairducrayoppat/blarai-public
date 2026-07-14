"""
BlarAI Launcher — Main Entry Point
====================================
Orchestrates the complete startup sequence:

  1. Check/request Administrator privileges (Hyper-V requires elevation)
  2. Start BlarAI-Orchestrator Hyper-V VM
  3. Execute Policy Agent measured-boot gate (GPU)
  4. Start Assistant Orchestrator service (NPU)
  5. Initialize SessionStore
  6. Initialize TransportGateway + handshake/prompt-flow preflight
  7. Launch BlarAIApp (Textual TUI)
  8. On exit: stop services, stop VM, clean up

Execute with:
    python -m launcher

Security:
  - No external network calls — code-enforced at process entry by the egress
    kill-switch (ADR-020): loopback + Hyper-V vsock only; all other outbound
    sockets refused fail-closed. (No longer merely environmental.)
  - Fail-Closed: startup failures → graceful exit with log message
  - Admin elevation via standard Windows UAC prompt
"""

from __future__ import annotations

import asyncio
import atexit
import json
import logging
import os
import subprocess
import sys
import threading
import time
import tomllib
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Logging — configure before any imports that use logger
# ---------------------------------------------------------------------------

_LOCALAPPDATA = os.environ.get("LOCALAPPDATA", "")
_LOG_DIR = os.path.join(_LOCALAPPDATA, "BlarAI") if _LOCALAPPDATA else ""

if _LOG_DIR:
    os.makedirs(_LOG_DIR, exist_ok=True)
    _LOG_PATH = os.path.join(_LOG_DIR, "launcher.log")
else:
    _LOG_PATH = "launcher.log"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    handlers=[
        logging.FileHandler(_LOG_PATH, encoding="utf-8"),
        logging.StreamHandler(sys.stderr),
    ],
)

logger = logging.getLogger("blarai.launcher")


EVIDENCE_PATH_ENV: str = "BLARAI_ACTIVATION_EVIDENCE_PATH"
DEFAULT_EVIDENCE_PATH: str = "phase2_gates/evidence/uat2_real_runtime_activation.json"
PROMPT_FLOW_EVIDENCE_PATH_ENV: str = "BLARAI_PROMPT_FLOW_EVIDENCE_PATH"
DEFAULT_PROMPT_FLOW_EVIDENCE_PATH: str = "phase2_gates/evidence/uat2_milestone2_prompt_flow.json"
# Assistant Orchestrator (AO) loopback listener port.  This is the SINGLE
# SOURCE OF TRUTH for where the gateway sends a PROMPT_REQUEST: it MUST equal
# the AO's own listener port, which the AO derives from its config
# [ipc].vsock_port (services/assistant_orchestrator/config/default.toml = 5001
# and guest_runtime.toml = 5001).  The invariant `gateway prompt port == AO
# listener port` is regression-locked by
# launcher/tests/test_resolve_gateway_port.py, which asserts this constant
# equals the AO production-config vsock_port so the two can never silently
# diverge again.  The gateway uses ONE port for BOTH its PA-liveness handshake
# and its prompt connection (services/ui_gateway/src/transport.py self._port),
# and the AO answers HANDSHAKE_REQUEST as well as PROMPT_REQUEST — so targeting
# the AO satisfies both, exactly as the dev path has always done.
ORCHESTRATOR_HOST_LOOPBACK_PORT: int = 5001
# PA listener port (matches the PA's [ipc].vsock_port in default.toml).  The
# gateway does NOT send the user's prompt here: the Policy Agent handles
# ADJUDICATION_REQUEST (and, since S15-EA-4f, HANDSHAKE_REQUEST) but rejects
# PROMPT_REQUEST with "Unsupported message type" — see
# services/policy_agent/src/ipc.py.  Retained for documentation / future
# PA-specific addressing; it is intentionally NOT the gateway prompt port.
PA_HOST_PRODUCTION_PORT: int = 5000


def resolve_gateway_port(*, dev_mode: bool, host_mode: bool) -> int:
    """Resolve the TCP/vsock port the TransportGateway connects to.

    The gateway uses a SINGLE port for both its PA-liveness handshake and the
    prompt connection (``services/ui_gateway/src/transport.py`` ``self._port``).
    That single port MUST be the Assistant Orchestrator's listener port, because
    the AO is the service that handles ``PROMPT_REQUEST``.  The Policy Agent
    listens on a different port and rejects ``PROMPT_REQUEST`` with
    "Unsupported message type" — pointing the gateway there is the production
    host-mode bug this function exists to prevent (the dev path always targeted
    the AO, which is why prompts worked in dev but failed in production).

    mTLS is the ONLY prod/dev difference on this path — NOT the port.  Both
    dev-mode and production host-mode therefore resolve to the same AO loopback
    port; guest-mode (AF_HYPERV) does not use a TCP port and returns 0.

    Args:
        dev_mode: True for the dev loopback path (no mTLS).
        host_mode: True for HOST deployment topology (loopback + mTLS in prod).
                   Ignored when ``dev_mode`` is True (dev is always loopback).

    Returns:
        ``ORCHESTRATOR_HOST_LOOPBACK_PORT`` for dev-mode and production
        host-mode; ``0`` for production guest-mode (AF_HYPERV, port unused).
    """
    if dev_mode:
        # Dev path: loopback to the AO, no mTLS.
        return ORCHESTRATOR_HOST_LOOPBACK_PORT
    if host_mode:
        # Production host-mode: loopback + mTLS to the AO (fidelity-2 / SDV §4).
        # Same port as dev — only the mTLS layer differs.
        return ORCHESTRATOR_HOST_LOOPBACK_PORT
    # Production guest-mode: AF_HYPERV — port not used for TCP.
    return 0


def _hyperv_transport_available() -> bool:
    """Probe whether this host can create a Windows AF_HYPERV socket.

    The guest boundary (#615) is a Windows-Hyper-V-only transport.  This is a
    cheap capability probe — it creates and immediately closes an AF_HYPERV
    socket without connecting — used by ``resolve_gateway_topology`` to decide
    whether a requested GUEST topology can actually be served, or whether the
    launcher must fall back to host-mode.

    Returns:
        True if an AF_HYPERV ``SOCK_STREAM`` socket can be created (Windows
        with Hyper-V socket support); False on any platform/OS error.
    """
    if sys.platform != "win32":
        return False
    import socket as _socket

    # Fail LOUD — never silently claim the guest path.  socket.AF_HYPERV is
    # absent on Python < 3.12 (BlarAI's venv is 3.11.x); creating a socket with
    # the fallback family int *succeeds* but cannot connect ("bad family"), which
    # is exactly why this creation-only probe used to falsely report the guest
    # path as available.  Real support requires the attribute, not a successful
    # socket() call.  The host-side AF_HYPERV component must run on Python >= 3.12.
    if not hasattr(_socket, "AF_HYPERV"):
        logger.error(
            "GUEST topology needs AF_HYPERV, but this Python lacks "
            "socket.AF_HYPERV (requires >= 3.12; running %s) — refusing to claim "
            "guest-mode, falling back to host-mode.",
            sys.version.split()[0],
        )
        return False

    from shared.ipc.vsock import AF_HYPERV, HV_PROTOCOL_RAW

    probe: _socket.socket | None = None
    try:
        probe = _socket.socket(AF_HYPERV, _socket.SOCK_STREAM, HV_PROTOCOL_RAW)
        return True
    except OSError as exc:
        logger.warning("AF_HYPERV socket probe failed: %s", exc)
        return False
    finally:
        if probe is not None:
            try:
                probe.close()
            except OSError:
                pass


def resolve_gateway_topology(
    runtime_mode: DeploymentMode,
    *,
    dev_mode: bool,
) -> bool:
    """Resolve the gateway's effective ``host_mode`` with a clean fallback.

    The gateway transport topology (#615):

      - ``DeploymentMode.HOST`` → ``host_mode=True`` — loopback + mTLS
        (fidelity-2).  This is BlarAI's DEFAULT topology and is returned
        unconditionally for HOST mode; the guest path never overrides it.
      - ``DeploymentMode.GUEST`` → ``host_mode=False`` — AF_HYPERV + mTLS
        across the VM boundary, *but only if* this host can actually create
        an AF_HYPERV socket (``_hyperv_transport_available``).  If GUEST is
        requested on a host without Hyper-V socket support, the launcher logs
        the downgrade and FALLS BACK to host-mode rather than failing the
        boot — host-mode is the safe, always-available default.

    dev_mode is accepted for symmetry with ``resolve_gateway_port`` and to
    short-circuit the AF_HYPERV probe (dev is always loopback); it does not
    change the returned ``host_mode`` value (dev_mode is layered separately).

    Args:
        runtime_mode: The resolved deployment mode (HOST or GUEST).
        dev_mode: True for the dev loopback path (skips the AF_HYPERV probe).

    Returns:
        ``True`` for host-mode (loopback) topology, ``False`` for the guest
        (AF_HYPERV) boundary.  GUEST downgrades to ``True`` when AF_HYPERV is
        unavailable.
    """
    if runtime_mode == DeploymentMode.HOST:
        return True
    # GUEST requested.  In dev_mode the transport is loopback regardless, so
    # report host-mode (the AF_HYPERV probe is irrelevant to a dev launch).
    if dev_mode:
        return True
    if _hyperv_transport_available():
        # Guest boundary is serviceable — use the AF_HYPERV topology.
        return False
    logger.warning(
        "GUEST topology requested but AF_HYPERV transport is unavailable on "
        "this host — falling back to host-mode (loopback + mTLS). The guest "
        "boundary requires Windows with Hyper-V socket support (#615)."
    )
    return True


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def _record_activation_evidence(payload: dict[str, object]) -> None:
    evidence_raw = os.environ.get(EVIDENCE_PATH_ENV, DEFAULT_EVIDENCE_PATH).strip()
    if not evidence_raw:
        evidence_raw = DEFAULT_EVIDENCE_PATH

    evidence_path = Path(evidence_raw)
    if not evidence_path.is_absolute():
        evidence_path = (Path.cwd() / evidence_path).resolve()

    evidence_path.parent.mkdir(parents=True, exist_ok=True)
    with open(evidence_path, "w", encoding="utf-8") as file_obj:
        json.dump(payload, file_obj, indent=2, sort_keys=True)


def _record_prompt_flow_evidence(payload: dict[str, object]) -> None:
    evidence_raw = os.environ.get(
        PROMPT_FLOW_EVIDENCE_PATH_ENV,
        DEFAULT_PROMPT_FLOW_EVIDENCE_PATH,
    ).strip()
    if not evidence_raw:
        evidence_raw = DEFAULT_PROMPT_FLOW_EVIDENCE_PATH

    evidence_path = Path(evidence_raw)
    if not evidence_path.is_absolute():
        evidence_path = (Path.cwd() / evidence_path).resolve()

    evidence_path.parent.mkdir(parents=True, exist_ok=True)
    with open(evidence_path, "w", encoding="utf-8") as file_obj:
        json.dump(payload, file_obj, indent=2, sort_keys=True)


def _run_uat2_prompt_flow_preflight(
    *,
    gateway: TransportGateway,
    session_store: EncryptedSessionStore,
    runtime_mode: DeploymentMode,
) -> bool:
    payload: dict[str, object] = {
        "timestamp": _timestamp(),
        "milestone": "Operational Exit Milestone 2",
        "gate": "UAT2_MINIMAL_PROMPT_FLOW",
        "startup_profile": "production",
        "runtime_mode": runtime_mode.value,
        "disposition": "FAIL",
        "fail_closed": "true",
        "session_id": "",
        "request_id": "",
        "prompt": "UAT2_M2_HEALTHCHECK",
        "token_count": 0,
        "response_excerpt": "",
        "pgov": {
            "approved": False,
            "reason_codes": [],
        },
        "failure": None,
    }

    async def _execute() -> dict[str, object]:
        session_id = session_store.create_session(title="UAT2_M2_PROMPT_FLOW")
        request_id = await gateway.send_prompt(session_id, "UAT2_M2_HEALTHCHECK")

        tokens: list[str] = []
        async for stream_token in gateway.stream_tokens(session_id):
            tokens.append(stream_token.token)

        pgov_result = gateway.get_pgov_result(request_id)
        response_text = "".join(tokens).strip()
        if not response_text:
            response_text = pgov_result.sanitized_text

        if response_text:
            session_store.add_turn(
                session_id=session_id,
                role="assistant",
                content=response_text,
                pgov_status=("approved" if pgov_result.approved else "denied"),
                pgov_reasons=list(pgov_result.reason_codes),
            )

        return {
            "session_id": session_id,
            "request_id": request_id,
            "token_count": len(tokens),
            "response_excerpt": response_text[:512],
            "pgov": {
                "approved": pgov_result.approved,
                "reason_codes": list(pgov_result.reason_codes),
            },
        }

    try:
        result = asyncio.run(_execute())
        payload["session_id"] = result["session_id"]
        payload["request_id"] = result["request_id"]
        payload["token_count"] = result["token_count"]
        payload["response_excerpt"] = result["response_excerpt"]
        payload["pgov"] = result["pgov"]
        payload["disposition"] = "PASS"
        _record_prompt_flow_evidence(payload)
        # Clean up the ephemeral health-check session so it does not
        # pollute the user-visible session list on every launch.
        _preflight_sid = str(result["session_id"])
        if _preflight_sid:
            try:
                session_store.delete_session(_preflight_sid)
            except Exception:  # noqa: BLE001
                pass  # best-effort cleanup; preflight already passed
        return True
    except Exception as exc:  # noqa: BLE001
        payload["failure"] = {
            "timestamp": _timestamp(),
            "stage": "prompt_flow",
            "code": "UAT2_PROMPT_FLOW_FAILED",
            "message": str(exc),
            "disposition": "FAIL",
            "fail_closed": "true",
        }
        _record_prompt_flow_evidence(payload)
        return False


def _prompt_flow_preflight_enabled(*, dev_mode: bool) -> bool:
    """Whether the real model-loaded prompt-flow preflight runs at boot.

    The prompt-flow preflight (Step 6b) sends a real ``UAT2_M2_HEALTHCHECK``
    prompt through ``gateway.send_prompt`` → streams REAL tokens from the
    already-loaded model → checks PGOV, fail-closed. It is the ONLY boot gate
    that exercises the *full* prompt path end to end. The cheap handshake
    preflight (Step 6a) only confirms the Policy Agent answers a
    ``HANDSHAKE_REQUEST`` — which is exactly what masked the production
    host-mode routing bug where the gateway sent ``PROMPT_REQUEST`` to the PA
    (rejected: "Unsupported message type") instead of the Assistant
    Orchestrator. A handshake-only gate cannot catch a misroute on the prompt
    path; this gate can.

    Default posture (S15 host-mode-routing fix):
      * Production (``dev_mode=False``): **ON by default**. The model is
        already loaded at this point in boot, so the marginal cost is a single
        short generation (~8s), not a model load — cheap insurance that the
        whole prompt path works before the UI appears. This turns "broken
        prompt path discovered by the user on their first message" into "boot
        fails closed, with the model loaded, before the UI opens." Reversible:
        set ``BLARAI_PROMPTFLOW_PREFLIGHT=0`` (or ``false``/``no``/``off``) to
        skip it explicitly.
      * Dev (``dev_mode=True``): **OFF by default** so iterative dev launches
        stay fast; dev already targets the AO correctly and a dev operator
        sees a broken prompt immediately. Set ``BLARAI_PROMPTFLOW_PREFLIGHT=1``
        to opt in (e.g. milestone / acceptance verification runs).

    The env var is an explicit override in BOTH directions and always wins over
    the mode default.
    """
    override = os.environ.get("BLARAI_PROMPTFLOW_PREFLIGHT", "").strip().lower()
    if override in ("1", "true", "yes", "on"):
        return True
    if override in ("0", "false", "no", "off"):
        return False
    # No explicit override → mode default: ON in production, OFF in dev.
    return not dev_mode


# ---------------------------------------------------------------------------
# VM stop-on-exit policy
# ---------------------------------------------------------------------------

# The three legal values of the stop-on-exit policy.  Anything else (typo,
# empty, unset) falls through to the DEFAULT below — deny-by-stale-resource:
# the on-demand assistant's VM is *released* by default, never left leaking.
VM_STOP_POLICY_ALWAYS: str = "always"
VM_STOP_POLICY_IF_STARTED: str = "if_started"
VM_STOP_POLICY_NEVER: str = "never"

# NEW DEFAULT (2026-06-10 vm-stop-ratchet fix): always stop the VM the launcher
# leaves behind.  This single-user box runs the BlarAI-Orchestrator VM ONLY for
# BlarAI; an on-demand assistant must release its 2 GiB when closed.  The legacy
# "if_started" behaviour ratcheted ownership — the launcher only ever stopped a
# VM it personally started, so any VM left Running across a boot (a crash, a hard
# console close that killed the process mid-``Stop-VM``, a host reboot that
# resurrected it, or another tool starting it) was then skipped by EVERY
# subsequent clean exit, and the leak self-perpetuated forever.
VM_STOP_POLICY_DEFAULT: str = VM_STOP_POLICY_ALWAYS

# Override env var (launcher-posture knob — same env-var idiom as dev_mode /
# network_facing / promptflow_preflight; the launcher reads no TOML for its own
# posture).  Config-surface key name: ``vm_stop_on_exit``.
VM_STOP_ON_EXIT_ENV: str = "BLARAI_VM_STOP_ON_EXIT"


def _resolve_vm_stop_policy() -> str:
    """Resolve the VM stop-on-exit policy for this launcher process.

    Returns one of ``"always"`` | ``"if_started"`` | ``"never"``:

      * ``"always"``  (NEW DEFAULT) — stop the BlarAI-Orchestrator VM in
        :func:`_cleanup` whenever it is currently Running, *regardless* of
        whether this launcher started it.  Fixes the ownership ratchet so an
        on-demand assistant releases its 2 GiB on every clean close.
      * ``"if_started"`` — legacy behaviour: stop the VM only if this launcher
        started it this boot (``_vm_was_started``).  Preserved for the
        parallel-dev scenario where another session owns the VM and this
        launcher must not yank it out from under that session.
      * ``"never"`` — never stop the VM (leave it Running on exit).

    Resolution: the ``BLARAI_VM_STOP_ON_EXIT`` env var (case-insensitive),
    falling back to :data:`VM_STOP_POLICY_DEFAULT` (``"always"``).  An
    unrecognised, empty, or unset value resolves to the default — the safe
    posture is to release the VM, so a typo never silently re-arms the leak.
    """
    raw = os.environ.get(VM_STOP_ON_EXIT_ENV, "").strip().lower()
    if raw in (
        VM_STOP_POLICY_ALWAYS,
        VM_STOP_POLICY_IF_STARTED,
        VM_STOP_POLICY_NEVER,
    ):
        return raw
    if raw:
        logger.warning(
            "Unrecognised %s=%r — falling back to default policy %r",
            VM_STOP_ON_EXIT_ENV,
            raw,
            VM_STOP_POLICY_DEFAULT,
        )
    return VM_STOP_POLICY_DEFAULT


# ---------------------------------------------------------------------------
# Imports (after logging setup)
# ---------------------------------------------------------------------------

from launcher.vm_manager import (
    VMState,
    ensure_vm_running,
    get_vm_state,
    is_admin,
    request_elevation,
    stop_vm,
)
from launcher.process_launch import launch_winui
from launcher.privilege_hardening import strip_unused_privileges
from launcher.orphan_guard import assign_process_to_job, create_kill_on_close_job
from launcher.instance_lock import (
    acquire_instance_lock,
    lock_path_for_repo,
    refuse_message,
    release_instance_lock,
)
from launcher.step_aside import start_force_exit_watchdog
from shared.runtime_config import (
    ConfigResolutionError,
    DeploymentMode,
    resolve_deployment_mode,
    resolve_dev_override,
    resolve_network_facing,
    resolve_service_config_path,
    resolve_service_root,
)
from shared.security.dev_mode_guard import (
    DevModeNetworkFacingError,
    assert_dev_mode_network_facing_safe,
    resolve_dev_mode,
)
from shared.security.cert_provisioning import (
    CertProvisioningError,
    PerBootCerts,
    provision_per_boot_certs,
)
from shared.constants import (
    DRAFT_MODEL_OV_PATH,
    ORCHESTRATOR_VM_NAME,
    TARGET_MODEL_OV_PATH,
    VOICE_ENABLED,
)
from shared.inference.shared_pipeline import (
    SharedInferencePipeline,
    build_shared_pipeline,
)
from services.assistant_orchestrator.src import entrypoint as _ao_entrypoint
from services.assistant_orchestrator.src.entrypoint import (
    AssistantOrchestratorService,
)
from services.policy_agent.src.entrypoint import PolicyAgentService
from services.ui_gateway.src.constants import SESSION_DB_PATH
from services.ui_gateway.src.session_store import (
    EncryptedSessionStore,
    build_session_store,
)
from services.ui_gateway.src.transport import TransportGateway
from services.ui_shell.src.app import BlarAIApp
from services.ui_backend.src.server import NamedPipeServer
from services.voice.src.engine import VoiceEngine


# UI surface selection (ADR-014). Default is the Textual TUI (unchanged).
# Set BLARAI_UI=winui to host the WinUI 3 app over the named-pipe backend
# instead — the launcher serves the (already-built) gateway behind the pipe
# and launches the WinUI executable, then tears down when its window closes.
WINUI_EXE_REL: str = (
    "services/ui_winui/bin/x64/Debug/"
    "net8.0-windows10.0.19041.0/BlarAI.Desktop.exe"
)

# #649 / ADR-024 §2.5 — repo-root-relative path to the built Windows-Hello approval
# helper (the Release build of tools/hello_verify). Mirrors WINUI_EXE_REL's shape.
# The launcher resolves this against the repo root and hands the BiometricApproval-
# Verifier the absolute path, so the verifier never depends on the process CWD. The
# canonical default also lives in shared.security.hello_verifier.HELLO_EXE_REL; both
# point at the same Release output of the #649 helper csproj.
HELLO_EXE_REL: str = (
    "tools/hello_verify/bin/x64/Release/"
    "net8.0-windows10.0.19041.0/BlarAI.HelloVerify.exe"
)


def _select_biometric_verifier(repo_root: Path):
    """Return a ready ``BiometricApprovalVerifier`` iff Windows Hello is available.

    The startup verifier-selection helper shared by BOTH UI surfaces (#649). It
    resolves the Hello helper exe under ``repo_root``, constructs the verifier, and
    runs its non-interactive ``--check`` probe (``is_available()``). Returns the
    verifier when Hello reports *Available* on this box, or ``None`` otherwise (helper
    not built, no enrolled biometric/PIN, probe error/timeout — all fail-closed to
    ``None`` inside ``is_available``). The caller decides the per-surface fallback:

      * TUI surface  → on ``None``, fall back to the in-process ``TUIApprovalVerifier``
        modal (today's behaviour).
      * WinUI surface → on ``None``, register NOTHING (ESCALATE stays the dormant
        silent-DENY — there is no in-process Textual app to host a modal on the WinUI
        surface; the WinUI-native prompt is a deferred follow-on, moot on a Hello-
        capable box).

    Because the Hello prompt is a SYSTEM dialog (not a window any surface owns), the
    SAME verifier works for both surfaces — the AO runs in this launcher process for
    both, so the verifier spawns the helper from here regardless of which surface is
    in front. Any failure here is swallowed by the caller's existing fail-safe
    try/except; this helper itself only ever returns a verifier or ``None``.
    """
    from shared.security.hello_verifier import BiometricApprovalVerifier

    verifier = BiometricApprovalVerifier(exe_path=repo_root / HELLO_EXE_REL)
    if verifier.is_available():
        return verifier
    return None


def _ui_mode() -> str:
    """Return the selected UI surface: ``"winui"`` or ``"tui"`` (default).

    Selected by the ``--winui`` CLI flag OR ``BLARAI_UI=winui``. The CLI flag
    is the reliable signal across UAC elevation: ``request_elevation`` forwards
    ``sys.argv`` to the elevated relaunch but NOT the parent's environment
    block, so an env var set before elevation would be lost — the flag is not.
    """
    if "--winui" in sys.argv:
        return "winui"
    return "winui" if os.environ.get("BLARAI_UI", "").strip().lower() == "winui" else "tui"


def _go_live_requested() -> bool:
    """True iff the operator requested URL-ingest go-live for THIS session.

    Selected by the ``--go-live`` CLI flag — the reliable signal across UAC
    elevation (see :func:`_ui_mode`): ``request_elevation`` forwards ``sys.argv``
    to the elevated relaunch but NOT the parent's environment block, so an env var
    set in a non-elevated shell (or a desktop ``.bat`` that self-elevates) is lost
    on the elevation hop, while a CLI flag survives. When present the launcher
    enables the guest parser for this boot by setting
    ``BLARAI_GUEST_PARSER_ENABLED`` in-process (so ``load_guest_parser_config``
    enables it); the committed default stays disabled (welded at rest), and the
    next boot WITHOUT ``--go-live`` is welded again. This is the per-session,
    reversible operator door-opener (ADR-027 Amendment 1)."""
    return "--go-live" in sys.argv


def _build_voice_engine(repo_root: Path) -> VoiceEngine:
    """Construct the STT/TTS engine fail-soft from on-disk model assets (ADR-017).

    Either or both models may be absent (weights live under the gitignored
    ``models/`` and are not committed); a missing or unloadable model simply
    disables that half — voice never blocks the surface from coming up.

    Always-off-at-boot (#660, decision #3): NO model is loaded at launch
    regardless of ``VOICE_ENABLED``.  The engine is built with
    :meth:`VoiceEngine.with_paths` so it *remembers* where to load from, and the
    WinUI voice toggles load each half on demand in-session (``voice_set_stt`` /
    ``voice_set_tts``) and unload it to reclaim RAM on toggle-off.  This keeps the
    RAM-safe posture on every launch (the 100%-RAM-freeze history is why) while
    making voice reachable without a reboot.  ``VOICE_ENABLED=True`` (the legacy
    #561 preload path) still pre-warms both halves at boot for anyone who wants
    voice resident from launch.
    """
    whisper_dir = repo_root / "models" / "whisper-small" / "openvino"
    kokoro_model = repo_root / "models" / "kokoro" / "kokoro-v1.0.onnx"
    kokoro_voices = repo_root / "models" / "kokoro" / "voices-v1.0.bin"
    whisper_arg = str(whisper_dir) if whisper_dir.is_dir() else None
    kokoro_model_arg = str(kokoro_model) if kokoro_model.is_file() else None
    kokoro_voices_arg = str(kokoro_voices) if kokoro_voices.is_file() else None

    if not VOICE_ENABLED:
        # Build an EMPTY engine that remembers the paths so the toggles can load
        # on demand. No Whisper + no 54-voice Kokoro bank occupy RAM at boot.
        engine = VoiceEngine.with_paths(
            whisper_dir=whisper_arg,
            kokoro_model=kokoro_model_arg,
            kokoro_voices=kokoro_voices_arg,
            device="GPU",
        )
        _step("Voice: OFF AT BOOT (RAM-safe) — models load on demand from the "
              "WinUI voice toggles and unload to reclaim RAM (#660). "
              "Set VOICE_ENABLED=True (shared/constants.py) to pre-warm at boot.")
        return engine
    engine = VoiceEngine.load(
        whisper_dir=whisper_arg,
        kokoro_model=kokoro_model_arg,
        kokoro_voices=kokoro_voices_arg,
        device="GPU",
    )
    msg = (
        f"Voice: STT {'ready' if engine.stt_available else 'off'}, "
        f"TTS {'ready' if engine.tts_available else 'off'} "
        f"({len(engine.available_voices())} voices)"
    )
    _step(msg)
    # Also record to the voice diagnostics log so model-load state is visible
    # even when the launcher console is not (ADR-017 bring-up).
    try:
        import time as _t
        log_path = repo_root / "userdata" / "_voice_backend.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a", encoding="utf-8") as fh:
            fh.write(f"{_t.strftime('%H:%M:%S')} LAUNCHER real VoiceEngine — {msg}\n")
    except Exception:  # noqa: BLE001 — diagnostics only
        pass
    return engine


# #652 deliverable B — the kill-on-close Job Object the WinUI child is assigned
# to. Held at module scope for the launcher's whole lifetime: the job terminates
# its members when its LAST handle closes, so this handle must stay open until
# the launcher exits (which is the event we WANT to trigger the kill). Created
# lazily on first child spawn; None until then / when the guard is unavailable.
_orphan_guard_job: int | None = None


def _winui_child_handle(proc: object) -> int | None:
    """Extract the raw OS process handle from whatever ``launch_winui`` returned.

    ``launch_winui`` returns either a ``process_launch._HandleProc`` (the
    de-elevated path — raw handle in ``_h``) or a ``subprocess.Popen`` (the
    ordinary fallback — Windows handle in ``_handle``). Returns the handle as an
    ``int``, or ``None`` if neither attribute is present (then orphan-guarding is
    skipped — fail-safe). Pure attribute read; never raises.
    """
    handle = getattr(proc, "_h", None)
    if handle is None:
        handle = getattr(proc, "_handle", None)
    try:
        return int(handle) if handle else None
    except (TypeError, ValueError):
        return None


def _guard_winui_child(proc: object) -> None:
    """Best-effort: assign the spawned WinUI child to a kill-on-close Job Object.

    Creates the job once (parked in ``_orphan_guard_job``) and assigns *proc* to
    it so the child cannot outlive the launcher (#652 deliverable B). Entirely
    best-effort and fail-safe: if the job can't be created or the child can't be
    assigned (e.g. the ``CreateProcessWithTokenW`` child already sits in a
    secondary-logon job that forbids nesting), it logs and returns — the child
    runs unguarded and the surface is never risked.
    """
    global _orphan_guard_job
    try:
        if _orphan_guard_job is None:
            _orphan_guard_job = create_kill_on_close_job()
        handle = _winui_child_handle(proc)
        if handle is None:
            logger.info(
                "orphan-guard: could not read the WinUI child handle; child runs "
                "unguarded (fail-safe)."
            )
            return
        assigned = assign_process_to_job(_orphan_guard_job, handle)
        if assigned:
            _step("WinUI child orphan-guarded (kill-on-close Job Object) ✓")
        else:
            _step(
                "WinUI child running unguarded (orphan-guard unavailable / "
                "declined — surface unaffected)."
            )
    except Exception as exc:  # noqa: BLE001 — orphan-guard must never break launch
        logger.warning(
            "orphan-guard: unexpected error guarding the WinUI child (%r) — child "
            "runs unguarded (fail-safe).",
            exc,
        )


def _run_winui_surface(
    *,
    gateway: TransportGateway,
    session_store: EncryptedSessionStore,
    repo_root: Path,
) -> int:
    """Serve the gateway over the named pipe and run the WinUI app to exit.

    Reuses the identical startup the TUI path uses (shared pipeline, PA, AO,
    gateway, handshake all already done by main()); only the final surface
    differs. The pipe server runs on a daemon thread; the WinUI executable is
    launched as a subprocess and waited on. When its window closes, the server
    is stopped and control returns for normal cleanup.
    """
    exe = repo_root / WINUI_EXE_REL
    if not exe.is_file():
        logger.error("WinUI executable not found at %s — build it first.", exe)
        _step(f"ERROR: WinUI app not built ({exe}). Run dotnet build.")
        return 1

    # #649 / ADR-024 §2.5 — ACTIVATE the ESCALATE human-review consumer on the
    # WinUI (primary) surface via Windows Hello. The Hello prompt is a SYSTEM dialog
    # raised by a subprocess from THIS launcher process — where the AO tool loop runs
    # for the WinUI surface too — so it reaches the operator without any cross-process
    # delivery to the separate WinUI executable. If Hello is available, register the
    # BiometricApprovalVerifier so a PA ESCALATE pauses the turn and prompts for a
    # fingerprint/PIN/face. If it is NOT available, register NOTHING: there is no
    # in-process Textual app on the WinUI surface to host the modal fallback, so
    # ESCALATE stays the dormant silent-DENY (== today's behaviour) — the WinUI-native
    # prompt is the deferred follow-on (moot on a Hello-capable box). FAIL-SAFE: any
    # wiring error is swallowed here and leaves ESCALATE silent-DENY; it can never
    # block the WinUI surface from launching.
    try:
        from shared.security.escalation_consent import register_verifier

        hello_verifier = _select_biometric_verifier(repo_root)
        if hello_verifier is not None:
            register_verifier(hello_verifier)
            _step("ESCALATE consumer ACTIVE on WinUI surface via Windows Hello ✓")
            logger.info(
                "ESCALATE human-review consumer ACTIVE on WinUI surface (#649) — "
                "PA ESCALATE verdicts now prompt for Windows Hello approval."
            )
        else:
            logger.info(
                "Windows Hello unavailable — ESCALATE stays silent-DENY on the "
                "WinUI surface (#649; no in-process modal fallback on WinUI)."
            )
    except Exception as exc:  # noqa: BLE001 — never block WinUI launch on this
        logger.warning(
            "Could not wire the ESCALATE Hello verifier on WinUI (#649): %s — "
            "ESCALATE stays silent-DENY (fail-safe).",
            exc,
        )

    voice = _build_voice_engine(repo_root)
    server = NamedPipeServer(gateway, session_store, voice=voice)
    server_thread = threading.Thread(
        target=server.serve_forever, name="winui-pipe-server", daemon=True
    )
    server_thread.start()
    _step("UI backend serving on named pipe — launching WinUI app…")
    logger.info("WinUI surface: pipe server up, launching %s", exe)

    try:
        # Spawn the UI de-elevated (Medium integrity) when the launcher is
        # elevated, so file attach — OneDrive cloud-only files and drag-drop —
        # works against a same-integrity Explorer (ADR-019). Falls back to an
        # ordinary launch if the de-elevation primitive is unavailable.
        proc = launch_winui(str(exe))
    except OSError as exc:
        logger.error("Failed to launch WinUI app: %s", exc)
        server.stop()
        return 1

    # #652 deliverable B (safe half): orphan-guard the WinUI child via a
    # kill-on-close Job Object so it can never outlive the launcher (a windowed
    # UI with no backend). BEST-EFFORT + degrades gracefully — the WinUI child is
    # launched via CreateProcessWithTokenW (ADR-019), and assigning such a child
    # to a job can conflict with the secondary-logon service's own job/nesting
    # limits. If the assignment fails, the child simply runs unguarded; the
    # surface is NEVER risked for the orphan-guard. The job handle is parked in a
    # module global so it stays open for the launcher's lifetime (closing it is
    # exactly the event that triggers the kill — so it must outlive the child).
    _guard_winui_child(proc)

    proc.wait()  # block until the user closes the window
    logger.info("WinUI app exited (code %s) — stopping pipe server", proc.returncode)
    server.stop()
    return 0


# ---------------------------------------------------------------------------
# Point-of-use sealed-VM ensure (#788 — lazy VM start)
# ---------------------------------------------------------------------------


def _ensure_vm_for_feature(feature: str) -> bool:
    """Lazily ensure the sealed Hyper-V VM is Running for a point-of-use consumer.

    Since #788 the launcher no longer starts the sealed VM unconditionally at
    boot — a plain chat launch never needs it (see :func:`main` Step 2). A
    feature that DOES need the sealed guest — URL-ingest guest parsing here, or
    dispatch guest-oracle execution in the fleet-runner process (#744, its own
    guard) — calls this at its point of use to start + verify the VM, FAILING
    CLOSED on failure so no containment is lost; the start is only deferred to
    the moment the sealed VM is actually exercised.

    Fast path: returns ``True`` immediately when the VM is already Running (an
    eager ``--go-live`` boot pays nothing here). Otherwise it starts the VM via
    :func:`ensure_vm_running` (idempotent, waits for Running) and records
    ``_vm_was_started`` so the ``if_started`` stop-on-exit policy still stops a
    VM this process brought up.

    Args:
        feature: human-readable name of the consumer, for the step log.

    Returns:
        ``True`` iff the VM is Running; ``False`` (fail-closed) otherwise — the
        caller MUST refuse the feature on ``False``.
    """
    global _vm_was_started
    if get_vm_state() == VMState.RUNNING:
        return True
    _step(f"Sealed VM not running — starting it now for {feature} (lazy, #788)…")
    if ensure_vm_running():
        _vm_was_started = True
        _step("VM running ✓")
        return True
    logger.error("Point-of-use sealed-VM start FAILED for %s (fail-closed)", feature)
    _step(
        f"Sealed VM start FAILED for {feature} — capability UNAVAILABLE "
        "(fail-closed)."
    )
    return False


# ---------------------------------------------------------------------------
# Guest parser bring-up (#655 Stage C — ADR-030 §3 guest-homed parsing)
# ---------------------------------------------------------------------------


def _maybe_start_guest_parser() -> "GuestParserManager | None":  # noqa: F821
    """Deploy + start the guest-homed parser when ``[guest_parser]`` enables it.

    Returns the :class:`launcher.guest_parser.GuestParserManager` (parked in
    the module accessor for the in-process ingest path), or ``None`` when the
    feature is disabled or its config cannot be loaded.

    FAIL-CLOSED FOR THE CAPABILITY, FAIL-SOFT FOR THE BOOT: a guest parser
    that cannot come up makes URL-mode ingest REFUSE (ADR-030 §3 — silent
    host-side parsing is the named anti-pattern, so there is no fallback),
    but it never blocks the assistant from booting — paste/local-file ingest
    and ordinary chat do not depend on it.  Every failure is loud here and
    deterministic in the manager's failure fingerprint.
    """
    from launcher.guest_parser import (
        GuestParserConfigError,
        GuestParserManager,
        load_guest_parser_config,
        set_guest_parser_bridge,
        set_guest_parser_manager,
    )
    from launcher.guest_parser_health import make_health_probe
    from launcher.guest_parser_invoker import (
        BridgeUnavailableError,
        GuestParserBridge,
        bridge_required,
    )
    from launcher.parser_channel_seam import register_parser_health_probe

    try:
        gp_config = load_guest_parser_config()
    except GuestParserConfigError as exc:
        logger.error("Guest parser config invalid (fail-closed): %s", exc)
        _step(
            f"Guest parser: config invalid ({exc.code}) — URL-ingest parse "
            "capability UNAVAILABLE (fail-closed)."
        )
        set_guest_parser_manager(None)
        return None

    if not gp_config.enabled:
        logger.info(
            "Guest parser disabled (guest_parser.enabled=false) — URL-ingest "
            "parse capability unavailable; ingest URL mode refuses (ADR-030)."
        )
        set_guest_parser_manager(None)
        return None

    # #788 point-of-use fail-closed: the guest parser EXERCISES the sealed VM
    # (the AF_HYPERV bridge handshake, Copy-VMFile deploy, and vsock health all
    # require the Alpine guest up). Since #788 the VM is no longer guaranteed
    # Running at boot in the normal path — only --go-live boots it eagerly — so
    # ensure it HERE, at the guest parser's point of use, before anything that
    # needs it. Fail-closed: if the sealed VM cannot be brought up, park NO
    # manager (guest_parser_available() → False → URL ingest refuses, ADR-030
    # §3) and return. (Guard ADDED by #788; the pre-existing ingest-side
    # refuse-when-unavailable check remains the outer lock. In --go-live mode
    # boot already started the VM eagerly, so this returns True instantly.)
    if not _ensure_vm_for_feature("guest parser (URL ingest)"):
        _step(
            "Guest parser: sealed VM unavailable — URL-ingest parse capability "
            "UNAVAILABLE (fail-closed); boot continues."
        )
        set_guest_parser_manager(None)
        return None

    manager = GuestParserManager(gp_config)
    set_guest_parser_manager(manager)

    # #655 Option A — the AF_HYPERV version bridge.  The runtime venv is Python
    # 3.11 (no socket.AF_HYPERV until 3.12); reach the guest through the 3.14
    # subprocess helper.  Build it BEFORE deploy/start so a missing bridge fails
    # closed LOUD here (never a pretended capability).  A future 3.12+ runtime
    # makes the bridge unnecessary (bridge_required() is False) — the in-process
    # AF_HYPERV path is used and no subprocess is spawned.
    if bridge_required():
        try:
            bridge = GuestParserBridge(
                bridge_python=gp_config.bridge_python,
                mtls_cert=gp_config.mtls_cert,
                mtls_key=gp_config.mtls_key,
                mtls_ca=gp_config.mtls_ca,
            )
        except BridgeUnavailableError as exc:
            logger.error("Guest parser bridge unavailable (fail-closed): %s", exc)
            _step(
                f"Guest parser: AF_HYPERV bridge unavailable ({exc.code}) — the "
                "3.11 runtime cannot reach the guest and no 3.14 helper was "
                "found; URL-ingest parse capability UNAVAILABLE (fail-closed). "
                "Set [guest_parser].bridge_python or install py -3.14."
            )
            set_guest_parser_bridge(None)
            return manager
        set_guest_parser_bridge(bridge)
        _step(
            "Guest parser: AF_HYPERV version bridge resolved "
            f"({' '.join(bridge.command)}) — 3.11→3.14 subprocess hop."
        )
    else:
        set_guest_parser_bridge(None)
        logger.info(
            "Guest parser: running interpreter has socket.AF_HYPERV — using the "
            "in-process transport (no version bridge needed)."
        )

    # Bind the REAL frame-level health probe to the parser-channel seam BEFORE
    # start() consults it — resolves GP_CHANNEL_UNBOUND now that the parse
    # channel is integrated.  The probe sends a minimal parse request and
    # requires a well-formed response (routes via the bridge on 3.11, in-process
    # on 3.12+).
    register_parser_health_probe(
        make_health_probe(
            mtls_cert=gp_config.mtls_cert,
            mtls_key=gp_config.mtls_key,
            mtls_ca=gp_config.mtls_ca,
        )
    )

    if gp_config.resident:
        # Resident model (#655 go-live): the parser is baked into the guest image
        # and auto-starts on boot via OpenRC, so Copy-VMFile deploy is dead on the
        # guest kernel.  Skip deploy() entirely and go straight to start() (legal
        # from IDLE) — host-side "start" only awaits the guest's own health.
        _step(
            "Guest parser: resident model — skipping host deploy (parser baked "
            "into the guest image, Copy-VMFile retired); awaiting guest health…"
        )
    else:
        _step("Deploying guest parser (UC-003 Stage C, ADR-030 guest-homed)…")
        if not manager.deploy():
            failure = manager.failure or {}
            _step(
                "Guest parser deploy FAILED "
                f"[{failure.get('code', 'UNKNOWN')}] — URL-ingest parse "
                "capability UNAVAILABLE (fail-closed); boot continues."
            )
            return manager
        _step("Guest parser bundle shipped ✓ — awaiting guest health…")
    if not manager.start():
        failure = manager.failure or {}
        _step(
            "Guest parser start FAILED "
            f"[{failure.get('code', 'UNKNOWN')}] — URL-ingest parse "
            "capability UNAVAILABLE (fail-closed); boot continues."
        )
        return manager
    _step("Guest parser READY ✓ (vsock health verified)")

    # The door-opening act — reached ONLY when the operator deliberately enabled the
    # guest parser this session (enabled=false at rest; the env override or a manual
    # config edit is what got us here).  Register the operator "URL = authorization"
    # adjudicator on the one egress door so the Policy Agent adjudicates each
    # /ingest <url> and the operator's paste authorizes that ONE host (ADR-027
    # Amendment 1).  Fail-closed: if registration raises, guarded_fetch has NO
    # adjudicator and denies EVERY fetch — URL ingest is simply unavailable.
    try:
        from services.ui_gateway.src.url_adjudicator import (
            make_operator_url_adjudicate,
            register_url_ingest_adjudicator,
        )

        register_url_ingest_adjudicator(make_operator_url_adjudicate())
        _step(
            "Egress door OPEN for operator URL ingest — the Policy Agent now "
            "adjudicates each /ingest <url>; the operator's paste authorizes that one "
            "host (ADR-027 Am.1). SSRF/GET-only/injection guards remain; nothing is "
            "stored without /approve.")
    except Exception as exc:
        logger.error("URL-ingest adjudicator registration FAILED: %s", exc)
        _step(
            f"Guest parser READY but adjudicator registration FAILED "
            f"({type(exc).__name__}) — URL fetches DENY (fail-closed); URL ingest "
            "unavailable this session.")
    return manager


# ---------------------------------------------------------------------------
# Cleanup Registry
# ---------------------------------------------------------------------------

_session_store: EncryptedSessionStore | None = None
_policy_agent_service: PolicyAgentService | None = None
_orchestrator_service: AssistantOrchestratorService | None = None
_vm_was_started: bool = False
# #655 Stage C — the guest-homed parser lifecycle manager (None when the
# feature is disabled / failed to come up; the ingest URL path consults
# launcher.guest_parser.guest_parser_available() and REFUSES on False).
_guest_parser_manager = None  # type: ignore[var-annotated]
# Single-instance lock path, set ONLY after a successful acquire so _cleanup releases
# exactly what we own (#670 run-1 fix A). None when dev-mode or unacquired.
_instance_lock_path: "Path | None" = None
# Set True at the top of _cleanup — the step-aside watchdog's "interrupt delivered"
# signal so it can tell a wedged main thread from a slow-but-running teardown (#670 fix C).
_cleanup_started: bool = False
# The shared 14B pipeline (PA+AO), set in main(). The step-aside watchdog releases its
# GPU/Level-Zero context before the force-exit so the incoming 30B loads onto a clean GPU
# (#670 run-2 fix 2a): os._exit skips the OpenVINO destructors, so the release is explicit.
_shared_pipeline: "SharedInferencePipeline | None" = None


def _release_14b_gpu() -> None:
    """Graceful 14B GPU-context release for the model-swap step-aside (#670 run-2 fix 2a).

    Run (bounded) by the force-exit watchdog before os._exit. A no-op when the pipeline
    isn't built. The actual GPU-context teardown is live-validated on the box."""
    pipe = _shared_pipeline
    if pipe is not None:
        pipe.release_gpu_for_exit()


def _do_stop_vm() -> None:
    """Stop the VM, logging a WARNING (never raising) if the stop did not confirm.

    ``stop_vm`` is graceful with a ~30s timeout and returns ``False`` if the VM
    did not reach Off in time (or ``Stop-VM`` itself failed).  ``_cleanup`` runs
    on the ``atexit`` exit path, so it must NEVER raise — a slow or failed stop
    is surfaced as a WARNING in ``launcher.log`` and the exit completes.
    """
    if not stop_vm():
        logger.warning(
            "Cleanup: stop_vm() did not confirm the VM reached Off "
            "(timeout or Stop-VM failure) — the VM may still be Running; "
            "stop it manually with: Stop-VM -Name \"%s\"",
            ORCHESTRATOR_VM_NAME,
        )


def _cleanup_vm() -> None:
    """Apply the ``vm_stop_on_exit`` policy to the Hyper-V VM at exit.

    Three policies (see :func:`_resolve_vm_stop_policy`):

      * ``"always"`` (default) — stop the VM whenever it is currently Running,
        regardless of ``_vm_was_started``.  This is the ratchet fix: a VM left
        Running across a prior boot is no longer skipped forever.  When the VM
        is already Off/Saved/absent we do NOT issue a spurious ``Stop-VM``.
      * ``"if_started"`` — legacy: stop only if this launcher started the VM
        this boot.  Preserves the parallel-dev case where another session owns
        the VM.
      * ``"never"`` — leave the VM Running.

    The log line always states the policy and the reason a stop is / is not
    happening, so ``launcher.log`` shows WHY (the missing "stopping Hyper-V VM"
    line was exactly the signature of the original leak).
    """
    policy = _resolve_vm_stop_policy()

    if policy == VM_STOP_POLICY_NEVER:
        logger.info("Cleanup: leaving VM running (policy=never)")
        return

    if policy == VM_STOP_POLICY_IF_STARTED:
        if _vm_was_started:
            logger.info(
                "Cleanup: stopping Hyper-V VM (policy=if_started, "
                "this launcher started it this boot)"
            )
            _do_stop_vm()
        else:
            logger.info(
                "Cleanup: leaving VM running "
                "(policy=if_started, VM was already running at boot)"
            )
        return

    # policy == "always" (default): stop whenever the VM is currently Running.
    # Check live state first so we never issue a spurious Stop-VM against a VM
    # that is already Off/Saved/absent.
    current_state = get_vm_state()
    if current_state == VMState.RUNNING:
        logger.info(
            "Cleanup: stopping Hyper-V VM (policy=always, VM is Running, "
            "was_started=%s)",
            _vm_was_started,
        )
        _do_stop_vm()
    else:
        logger.info(
            "Cleanup: leaving VM as-is (policy=always, VM not Running: state=%s)",
            current_state.value,
        )


def _cleanup() -> None:
    """Graceful shutdown: stop services, VM, session store."""
    global _cleanup_started
    # Signal the step-aside watchdog that the graceful path is unwinding (so it waits
    # out a slow teardown rather than force-killing a teardown that IS progressing).
    _cleanup_started = True
    logger.info("Cleanup: shutting down components")

    # #655 Stage C: stop the guest parser BEFORE the VM stop-on-exit policy
    # runs (#657) — a best-effort graceful signal when the parse channel has
    # bound one; the VM stop below remains the authoritative teardown.
    if _guest_parser_manager is not None:
        logger.info("Cleanup: stopping guest parser")
        _guest_parser_manager.stop()

    if _policy_agent_service is not None and _policy_agent_service.running:
        logger.info("Cleanup: stopping Policy Agent service")
        _policy_agent_service.stop()

    if _orchestrator_service is not None and _orchestrator_service.running:
        logger.info("Cleanup: stopping Assistant Orchestrator service")
        _orchestrator_service.stop()

    if _session_store is not None:
        logger.info("Cleanup: closing session store")
        _session_store.close()

    _cleanup_vm()

    # Release the single-instance lock LAST (after services + VM are down) so the swap
    # relaunch can acquire it. A forceful os._exit skips this -> the lock is left stale
    # for the relaunch to reclaim (#670 run-1 fix A).
    if _instance_lock_path is not None:
        try:
            if release_instance_lock(_instance_lock_path):
                logger.info("Cleanup: released single-instance lock")
        except Exception:  # noqa: BLE001 — lock release must never block teardown
            pass

    logger.info("Cleanup: complete")


# NOTE (#783): _cleanup is registered with atexit inside main(), NOT here at
# module scope.  Module-scope registration armed the FULL production teardown
# (including the policy=always real Stop-VM against BlarAI-Orchestrator) in
# EVERY process that merely imports this module — which is every standing-gate
# pytest run.  Three gate runs on 2026-07-09 each force-stopped the live guest
# VM at interpreter exit (LOCALAPPDATA redirection scopes data, not the
# hypervisor).  Importing must be side-effect-free; only an actual launcher
# boot owns the teardown.


def _request_step_aside() -> None:
    """Daemon→main step-aside for a model swap (#670). The AO runs on a daemon thread and
    CANNOT ``sys.exit`` the process (and calling ``_cleanup`` from it would self-join the AO
    loop), so it interrupts the launcher's MAIN thread (which runs the app) — raising
    ``KeyboardInterrupt`` there. The main unwinds to ``atexit``→``_cleanup`` (stop services,
    UNLOAD the 14B, free the GPU/VM) and exits, freeing the box for the detached swap driver
    to load the 30B; the driver relaunches the launcher afterwards (never-zero). Cross-platform
    via ``_thread.interrupt_main`` (works on Windows + POSIX, from any thread).

    LIVE-TUNED (Phase B): the exact interrupt → clean-exit → WinUI-close/reopen is validated at
    the on-hardware shakedown; this is the wired mechanism, not a proven-clean exit."""
    import _thread

    # Instrument GPU-free (system RAM = the iGPU's GPU-memory pool) at the START of the
    # step-aside, 14B still loaded (#670 run-2). Pairs with the driver's GPU-clear log at
    # 30B-load time for a measured before/after handoff. Best-effort; never blocks.
    try:
        from shared.fleet.swap_ops import real_gpu_free_gb

        _gpu_before = real_gpu_free_gb()
        logger.critical(
            "Step-aside — GPU-free (system RAM) before the 14B unload: %s GiB (#670 run-2).",
            f"{_gpu_before:.1f}" if _gpu_before is not None else "n/a",
        )
    except Exception:  # noqa: BLE001 — instrumentation must never block the step-aside
        pass

    logger.info("Step-aside requested — interrupting the main thread for a graceful exit.")
    _thread.interrupt_main()
    # GUARANTEED TERMINATION (#670 run-1 fix C): interrupt_main() may never be delivered
    # if WinUI's native event loop is parked (the run-1 wedge), which deadlocks the swap
    # driver's settle (it waits on old_pid death). A daemon watchdog forces the process
    # down if the graceful interrupt+teardown does not complete — graceful first, forceful
    # backstop. _cleanup sets _cleanup_started (the watchdog's "interrupt delivered" signal).
    start_force_exit_watchdog(lambda: _cleanup_started, unload_gpu=_release_14b_gpu)


# ---------------------------------------------------------------------------
# Startup Sequence
# ---------------------------------------------------------------------------


def _banner() -> None:
    """Print startup banner to stderr (visible in console mode)."""
    print(
        "\n"
        "  ╔══════════════════════════════════════╗\n"
        "  ║         BlarAI Assistant              ║\n"
        "  ║  Production Runtime                    ║\n"
        "  ╚══════════════════════════════════════╝\n",
        file=sys.stderr,
    )


def _step(msg: str) -> None:
    """Print a startup step to stderr."""
    print(f"  → {msg}", file=sys.stderr)
    logger.info("Startup: %s", msg)


def _resolve_kv_cache_precision(runtime_mode: DeploymentMode) -> str | None:
    """Read the optional ``[gpu].kv_cache_precision`` knob from the AO config TOML.

    OpenVINO 2026.2 GPU KV-cache quantization hint (e.g. ``'u8'``/``'u4'``/``'i4'``),
    threaded into the shared LLMPipeline build (A3). Empty/unset → ``None`` = the
    runtime default (FP16), byte-identical to the pre-2026.2 behaviour. This is a
    Session-2 memory/quality A/B knob, so it MUST NOT break boot: any error reading
    it fails soft to ``None`` (unset). If the AO config itself is genuinely broken,
    the AO construction later in this same boot fails closed with the proper error —
    this read does not introduce a new failure path. The same ``runtime_mode`` is
    used here as for ``from_runtime_mode`` below, so it reads exactly the config the
    AO will load (``default.toml`` for HOST, ``guest_runtime.toml`` for GUEST)."""
    try:
        service_root = resolve_service_root(
            _ao_entrypoint.__file__, "services.assistant_orchestrator"
        )
        config_path = resolve_service_config_path(
            service_root, deployment_mode=runtime_mode
        )
        with open(config_path, "rb") as config_file:
            config_data = tomllib.load(config_file)
        gpu_section = config_data.get("gpu", {})
        value = str(gpu_section.get("kv_cache_precision", "")).strip()
        return value or None
    except Exception as exc:  # noqa: BLE001 — optional perf knob, fail soft to unset
        logger.warning(
            "Could not read [gpu].kv_cache_precision (optional perf knob); leaving "
            "it unset (FP16 default). Reason: %s",
            exc,
        )
        return None


def main() -> int:
    """Main launcher entry point.

    Returns:
        Exit code (0 = success, 1 = failure).
    """
    global _session_store, _policy_agent_service
    global _orchestrator_service, _vm_was_started, _guest_parser_manager
    global _instance_lock_path, _shared_pipeline

    # #783: arm the production teardown ONLY when actually booting the launcher.
    # A bare import (pytest collection, tooling) must never register a handler
    # that can stop the real Hyper-V VM at interpreter exit.
    atexit.register(_cleanup)

    try:
        runtime_mode = resolve_deployment_mode()
    except ConfigResolutionError as exc:
        logger.error("Launcher runtime mode resolution failed: %s", exc)
        _step(f"ERROR: launcher mode invalid ({exc.code}).")
        input("\n  Press Enter to exit…")
        return 1

    # ── Security posture resolution (before any service construction) ─────────
    # ACTIVATION COMPLETE (Sprint 15 EA-4b): production is now the HOST default.
    #
    # resolve_dev_mode is the centralised, logged replacement for the previous
    # three silent inline ternaries ``(True if runtime_mode == HOST else None)``.
    # HOST resolves production (dev_mode=False) by default — the Known-Good
    # Manifest is staged (EA-3) and the JWT TPM key provisioned (EA-4 ceremony).
    #
    # Dev mode is now an explicit, LOUD opt-in: set BLARAI_DEV_MODE=1 in the
    # process environment before launch.  resolve_dev_override() reads that env
    # var and returns True (opt-in) or None (no override → production default).
    # The loud INSECURE banner fires on every dev-mode boot — it is never silent.
    # The interlock still refuses dev_mode=True + network_facing=True.
    _dev_mode: bool = resolve_dev_mode(runtime_mode, dev_mode_override=resolve_dev_override())
    _network_facing: bool = resolve_network_facing()

    # Interlock: refuse (dev_mode=True AND network_facing=True) before touching
    # any service.  Today _network_facing is always False so the interlock never
    # trips — but it is the load-bearing control the moment egress lands.
    try:
        assert_dev_mode_network_facing_safe(
            dev_mode=_dev_mode,
            network_facing=_network_facing,
        )
    except DevModeNetworkFacingError as exc:
        logger.critical("SECURITY INTERLOCK: %s", exc)
        _step(
            "FATAL: Security interlock refused launch — dev_mode + network_facing "
            "cannot both be active.  See launcher.log for details."
        )
        input("\n  Press Enter to exit…")
        return 1

    activation_evidence: dict[str, object] = {
        "timestamp": _timestamp(),
        "milestone": "Production Runtime Activation",
        "gate": "REAL_RUNTIME_ACTIVATION",
        "startup_profile": "production",
        "runtime_mode": runtime_mode.value,
        "vm_required": True,
        "steps": {
            "admin_ok": False,
            "certs_provisioned": False,
            "vm_running": False,
            "policy_agent_started": False,
            "assistant_orchestrator_started": False,
            "gateway_initialized": False,
            "gateway_handshake_ok": False,
            "prompt_flow_ok": False,
        },
        "disposition": "FAIL",
        "fail_closed": "true",
        "failure": None,
    }

    _banner()

    # ── Step 1: Check Admin privileges ────────────────────────────
    _step("Checking Administrator privileges…")

    if not is_admin():
        logger.info("Not running as admin — requesting elevation")
        _step("Requesting Administrator access (UAC prompt)…")
        elevated = request_elevation()
        if elevated:
            activation_evidence["disposition"] = "ELEVATION_HANDOFF"
            activation_evidence["failure"] = {
                "timestamp": _timestamp(),
                "stage": "admin_check",
                "code": "UAC_PROMPT_TRIGGERED",
                "message": "Elevation prompt launched; current process exiting for handoff.",
                "disposition": "FAIL",
                "fail_closed": "true",
            }
            _record_activation_evidence(activation_evidence)
            # The elevated process was launched; this one should exit.
            logger.info("Elevation requested — current process exiting")
            return 0
        else:
            logger.error("Elevation denied or failed")
            activation_evidence["failure"] = {
                "timestamp": _timestamp(),
                "stage": "admin_check",
                "code": "UAC_ELEVATION_DENIED",
                "message": "Administrator access required for launcher startup.",
                "disposition": "FAIL",
                "fail_closed": "true",
            }
            _record_activation_evidence(activation_evidence)
            _step("ERROR: Administrator access required for Hyper-V VM management.")
            _step("Please right-click the application and select 'Run as administrator'.")
            input("\n  Press Enter to exit…")
            return 1

    logger.info("Running with Administrator privileges")
    _step("Administrator privileges confirmed ✓")
    activation_evidence["steps"]["admin_ok"] = True

    # ── Step 1.4: Strip unused token privileges (#652 D-a) ────────────────
    # The launcher is now confirmed elevated, so its primary token carries the
    # full elevated privilege set (SeDebug, SeLoadDriver, SeTcb, SeTakeOwnership,
    # …) — most of which BlarAI never uses. Remove everything not on the tight
    # keep-allowlist (SeChangeNotify + SeImpersonate + the two #637 owner/DACL
    # privileges) PERMANENTLY for this process (SE_PRIVILEGE_REMOVED), here —
    # BEFORE the in-process Policy Agent / Assistant Orchestrator threads start
    # (Steps 3/4) and BEFORE any child is spawned (WinUI, Hello helper,
    # powershell.exe) — so the removed privileges are absent from every
    # in-process component (including the LLM tool loop) and are not inherited
    # by children. SeImpersonate is KEPT precisely so the ADR-019 WinUI
    # de-elevation (CreateProcessWithTokenW) still works. FAIL-SAFE: this never
    # raises and never blocks boot; on any error it logs and continues, and on a
    # non-elevated dev run it simply strips the few non-allowlisted privileges in
    # the standard token. See launcher/privilege_hardening.py.
    _step("Hardening launcher token (stripping unused privileges, #652)…")
    try:
        _priv_report = strip_unused_privileges()
        _step(
            "Token hardened: removed "
            f"{len(_priv_report['removed'])} privilege(s) "
            f"({', '.join(_priv_report['removed']) or 'none'}), kept "
            f"{len(_priv_report['kept'])} "
            f"({', '.join(_priv_report['kept']) or 'none'}) ✓"
        )
        activation_evidence["steps"]["privileges_stripped"] = {
            "removed": _priv_report["removed"],
            "kept": _priv_report["kept"],
            "errors": _priv_report["errors"],
        }
    except Exception as _priv_exc:  # noqa: BLE001 — hardening must never block boot
        # strip_unused_privileges is already fail-safe and should not raise, but
        # this outer guard makes the never-fail-boot contract belt-and-suspenders.
        logger.warning(
            "privilege-hardening: unexpected error at call site (%r); continuing "
            "boot without it (fail-safe).",
            _priv_exc,
        )
        activation_evidence["steps"]["privileges_stripped"] = {
            "removed": [],
            "kept": [],
            "errors": [f"call-site exception: {type(_priv_exc).__name__}"],
        }

    # ── Step 1.4: Single-instance guard (#670 Phase-B run-1 fix A) ────────
    # Acquire a per-checkout lock BEFORE cert provisioning so a SECOND launcher refuses
    # cleanly WITHOUT ever stomping the shared certs/ dir. Run-1 had four launchers; each
    # re-minted a fresh per-boot CA into certs/, so the gateway<->PA mTLS presented a leaf
    # signed by one boot's CA to a peer trusting another's -> CERTIFICATE_VERIFY_FAILED ->
    # Fail-Closed. Production-scoped (matches cert provisioning; dev/harness launches are
    # unaffected). The swap relaunch acquires only AFTER the old instance is gone — graceful
    # release in _cleanup, or the step-aside watchdog force-kills a wedged old -> stale lock
    # -> reclaim.
    if not _dev_mode:
        _lock_path = lock_path_for_repo(Path(__file__).resolve().parent.parent)
        _lock = acquire_instance_lock(_lock_path)
        if not _lock.acquired:
            _refuse = refuse_message(_lock.holder_pid)
            print(f"\n{_refuse}\n", file=sys.stderr)
            logger.critical("Single-instance guard refused boot (#670): %s", _refuse)
            # Hard-exit WITHOUT atexit/_cleanup: a refused instance acquired nothing and
            # started nothing, and running _cleanup_vm here (policy=always) would STOP the
            # LIVE instance's VM. Flush logs, then terminate.
            logging.shutdown()
            os._exit(1)
        _instance_lock_path = _lock_path  # we own it now -> _cleanup releases it
        _step(
            "Single-instance lock acquired ✓"
            + (" (reclaimed a stale lock)" if _lock.reclaimed_stale else "")
        )
        activation_evidence["steps"]["single_instance"] = {
            "acquired": True,
            "reclaimed_stale": _lock.reclaimed_stale,
        }

    # ── Step 1.5: Per-boot mTLS cert provisioning (ADR-026) ───────────────
    # Placed AFTER admin is confirmed (the is_admin/request_elevation/return-0
    # block above) so it fires EXACTLY ONCE, in the elevated process.  A
    # non-admin launch elevates and returns 0 before reaching here, so the
    # short-lived non-elevated process never mints (avoids the double-mint
    # where the non-elevated process would otherwise write certs first).
    #
    # Fires only in production (dev_mode=False).  Generates a fresh ephemeral
    # CA + PA-server cert + gateway-client cert and writes them to certs/ so
    # PolicyAgentService (Step 3) + TransportGateway (Step 6) pick them up at
    # the [ipc] paths without any manual step.  In dev_mode the cert paths
    # remain unset and the dev-mode TCP-loopback path skips mTLS per existing
    # design.  Still precedes all service construction.
    #
    # Fail-Closed: a CertProvisioningError aborts startup — we never start
    # services with absent or stale certs in production.
    _per_boot_certs: PerBootCerts | None = None
    if not _dev_mode:
        _step("Provisioning per-boot mTLS certificates (ADR-026)…")
        try:
            _repo_root_for_certs = Path(__file__).resolve().parent.parent
            # #863: the battery's per-job AO reboots (boot_launcher_detached sets
            # BLARAI_REUSE_CERTS=1) reuse an existing consistent per-boot cert set
            # rather than re-mint a fresh CA under the still-running/leaked prior AO
            # (which rotates the CA out from under its leaf -> handshake fails, the
            # deterministic per-job STALL night-20260711). Production / interactive
            # boots leave the env var unset -> per-boot minting (ADR-026) unchanged.
            _reuse_certs = os.environ.get("BLARAI_REUSE_CERTS", "") == "1"
            _per_boot_certs = provision_per_boot_certs(
                repo_root=_repo_root_for_certs,
                reuse_if_consistent=_reuse_certs,
            )
            _step(
                f"Per-boot mTLS certs provisioned ✓  "
                f"(CA: {_per_boot_certs.ca_cert_path.name}, "
                f"PA-server: {_per_boot_certs.pa_server_cert_path.name}, "
                f"GW-client: {_per_boot_certs.gateway_client_cert_path.name})"
            )
            logger.info(
                "Per-boot mTLS certs written: CA=%s PA-server=%s GW-client=%s",
                _per_boot_certs.ca_cert_path,
                _per_boot_certs.pa_server_cert_path,
                _per_boot_certs.gateway_client_cert_path,
            )
            activation_evidence["steps"]["certs_provisioned"] = True
        except CertProvisioningError as exc:
            logger.critical("Per-boot cert provisioning failed (fail-closed): %s", exc)
            activation_evidence["failure"] = {
                "timestamp": _timestamp(),
                "stage": "cert_provisioning",
                "code": "CERT_PROVISIONING_FAILED",
                "message": str(exc),
                "disposition": "FAIL",
                "fail_closed": "true",
            }
            _record_activation_evidence(activation_evidence)
            _step("FATAL: Per-boot mTLS cert provisioning failed (Fail-Closed).")
            _step("Check %s for details." % _LOG_PATH)
            input("\n  Press Enter to exit…")
            return 1

    # ── Step 2: Sealed Hyper-V VM — LAZY unless --go-live (#788) ──────────
    # The sealed guest VM's ONLY consumers are the URL-ingest guest parser
    # (dormant; brought up at boot only under --go-live) and the dispatch
    # guest oracle (dispatch-only, run in a separate fleet-runner process —
    # #744, its own ensure-start). Plain chat never exercises the VM, so a
    # normal launch no longer pays the ~10-15s Alpine cold-boot nor holds the
    # ~1-2 GB it would never touch.
    #
    # FAIL-CLOSED CONTAINMENT IS NOT REMOVED — IT IS DEFERRED TO POINT-OF-USE.
    # A feature that needs the sealed guest starts + verifies it and fails
    # closed THERE (see `_ensure_vm_for_feature` and its call inside
    # `_maybe_start_guest_parser`; the dispatch-oracle guard is #744's, in the
    # fleet runner). No protection is lost — only the start is deferred to the
    # moment the sealed VM is actually used.
    #
    # SECURITY POSTURE NOTE (#788 → #787 Phase-2 coverage matrix): this turns
    # the always-present sealed VM (an unconditional containment component) into
    # a present-on-demand one. Surfaced deliberately for the coverage matrix —
    # no containment is weakened, only the start is deferred.
    if _go_live_requested():
        # --go-live → EAGER (behaviour unchanged): the guest parser is deployed
        # at boot, so the sealed VM MUST be up now. Fail-closed abort on a
        # VM-start failure (the guest parser is the point of use, and it is a
        # boot-time consumer in this mode).
        _step("Starting BlarAI-Orchestrator VM (--go-live: eager for URL ingest)…")

        vm_initial_state = get_vm_state()
        _vm_was_started = vm_initial_state != VMState.RUNNING

        if ensure_vm_running():
            _step("VM running ✓")
            activation_evidence["steps"]["vm_running"] = True

            # ── Step 2.4: Guest parser bring-up (#655 Stage C) ─────────
            # Deploy + start the guest-homed parser (ADR-030 §3 guest-homed
            # parsing). Capability-fail-closed, boot-fail-soft: a parser that
            # cannot come up leaves URL-mode ingest refusing but never blocks
            # the boot.
            #
            # --go-live translates the elevation-surviving CLI flag into the
            # in-process enable BEFORE the config is read, so the operator can
            # open URL ingest for THIS session from a desktop .bat without a
            # terminal. The committed default stays enabled=false (welded at
            # rest); the next boot without --go-live is welded again.
            os.environ["BLARAI_GUEST_PARSER_ENABLED"] = "true"
            _step(
                "--go-live: operator URL-ingest ENABLED for this session "
                "(per-session; committed default stays welded — next boot "
                "without --go-live is deny-by-default again)."
            )
            _guest_parser_manager = _maybe_start_guest_parser()
            activation_evidence["steps"]["guest_parser"] = (
                _guest_parser_manager.state.value
                if _guest_parser_manager is not None
                else "disabled"
            )
        else:
            _vm_was_started = False
            logger.error("VM start failed — aborting (Fail-Closed)")
            activation_evidence["failure"] = {
                "timestamp": _timestamp(),
                "stage": "vm_start",
                "code": "VM_START_FAILED",
                "message": "Hyper-V VM failed to start.",
                "disposition": "FAIL",
                "fail_closed": "true",
            }
            _record_activation_evidence(activation_evidence)
            _step("ERROR: VM start failed (Fail-Closed).")
            _step("Check %s for details." % _LOG_PATH)
            input("\n  Press Enter to exit…")
            return 1
    else:
        # Normal (lazy) mode: defer the sealed VM to point-of-use. Plain chat
        # needs no guest VM; the guest parser stays welded (enabled=false → URL
        # ingest refuses) and no oracle dispatch is in flight at boot. If a
        # VM-needing feature fires this session it starts + verifies the VM and
        # fails closed AT THAT POINT (`_ensure_vm_for_feature`), so containment
        # is preserved — only the start is deferred.
        _vm_was_started = False
        _step(
            "Sealed VM start DEFERRED (lazy, #788) — plain chat needs no guest "
            "VM; a feature that needs it (URL ingest / dispatch oracle) starts + "
            "verifies it at point-of-use and fails closed there. Relaunch with "
            "--go-live for eager URL-ingest bring-up."
        )
        activation_evidence["steps"]["vm_running"] = "deferred"
        activation_evidence["steps"]["guest_parser"] = "disabled"

    # ── Step 2.5: Build shared LLMPipeline ────────────────────────
    # ADR-012 §2.1 / §3.1: "single compilation, shared weights" across PA + AO.
    # One ov_genai.LLMPipeline compiled here and threaded into both services;
    # threading.Lock inside the wrapper serialises .generate() between callers.
    # Frees ~8 GB of GPU memory and one ~15-18s compile from every boot.
    _step("Building shared LLMPipeline (one compile, used by PA + AO)…")
    _repo_root = Path(__file__).resolve().parent.parent
    # Optional OpenVINO 2026.2 GPU KV-cache precision hint (A3) — read fail-soft
    # from the AO [gpu] config; None (the shipped default) leaves the build
    # byte-identical to the pre-2026.2 FP16 behaviour.
    _kv_cache_precision = _resolve_kv_cache_precision(runtime_mode)
    _shared_build = build_shared_pipeline(
        model_dir=_repo_root / TARGET_MODEL_OV_PATH,
        draft_model_dir=_repo_root / DRAFT_MODEL_OV_PATH,
        # ADR-012 Amendment 3 (Phase 0, OV GenAI 2026.1): re-checked DEC-06
        # empirically — prefix caching ON yields ~23% higher TPS and halves
        # TTFT with no spec-decode acceptance-rate collapse signature.
        enable_prefix_caching=True,
        device="GPU",
        target_manifest_path=_repo_root / TARGET_MODEL_OV_PATH / "manifest.json",
        draft_manifest_path=_repo_root / DRAFT_MODEL_OV_PATH / "manifest.json",
        # PA security-gate posture inherited (was PA=HIGH/AO=MEDIUM pre-unification;
        # under a single shared pipeline the priority is moot for scheduling but
        # documents the security frame). ADR-012 Amendment 3.
        model_priority="HIGH",
        kv_cache_precision=_kv_cache_precision,
    )
    if not _shared_build.ok:
        logger.error("Shared LLMPipeline build failed: %s", _shared_build.error)
        activation_evidence["failure"] = {
            "timestamp": _timestamp(),
            "stage": "shared_pipeline_build",
            "code": "SHARED_PIPELINE_BUILD_FAILED",
            "message": str(_shared_build.error),
            "disposition": "FAIL",
            "fail_closed": "true",
        }
        _record_activation_evidence(activation_evidence)
        _step("ERROR: Shared LLMPipeline build failed (Fail-Closed).")
        _step("Check %s for details." % _LOG_PATH)
        input("\n  Press Enter to exit…")
        return 1
    _shared_pipeline = _shared_build.pipeline
    _step("Shared LLMPipeline ready ✓")
    activation_evidence["steps"]["shared_pipeline_built"] = True

    # ── Step 3: Execute Policy Agent measured boot ────────────────
    _step(
        "Executing Policy Agent measured-boot gate "
        f"({runtime_mode.value} mode)…"
    )
    try:
        _policy_agent_service = PolicyAgentService.from_runtime_mode(
            runtime_mode,
            dev_mode_override=_dev_mode,  # centralised via resolve_dev_mode()
            shared_pipeline=_shared_pipeline,
        )
    except ConfigResolutionError as exc:
        logger.error("Policy Agent config resolution failed: %s", exc)
        activation_evidence["failure"] = {
            "timestamp": _timestamp(),
            "stage": "policy_agent_config",
            "code": exc.code,
            "message": str(exc),
            "disposition": "FAIL",
            "fail_closed": "true",
        }
        _record_activation_evidence(activation_evidence)
        _step(
            "ERROR: Policy Agent config resolution failed "
            f"({exc.code}) (Fail-Closed)."
        )
        _step("Check %s for details." % _LOG_PATH)
        input("\n  Press Enter to exit…")
        return 1
    if not _policy_agent_service.start():
        logger.error("Policy Agent entrypoint failed to initialize")
        if _policy_agent_service.last_failure is not None:
            logger.error(
                "Policy Agent startup fingerprint: %s",
                _policy_agent_service.last_failure,
            )
            activation_evidence["failure"] = dict(_policy_agent_service.last_failure)
            _step(
                "ERROR: Policy Agent startup failed "
                f"[{_policy_agent_service.last_failure.get('code', 'UNKNOWN')}] "
                "(Fail-Closed)."
            )
            boot_state = _policy_agent_service.measured_boot_state
            if boot_state is not None:
                _step(
                    "Measured-boot result: "
                    f"attempt={boot_state.attempt_count}, "
                    f"hard_lock={str(boot_state.hard_locked).lower()}"
                )
        else:
            activation_evidence["failure"] = {
                "timestamp": _timestamp(),
                "stage": "policy_agent_start",
                "code": "PA_START_FAILED",
                "message": "Policy Agent startup failed with no fingerprint.",
                "disposition": "FAIL",
                "fail_closed": "true",
            }
            _step("ERROR: Policy Agent startup failed (Fail-Closed).")
        _record_activation_evidence(activation_evidence)
        _step("Check %s for details." % _LOG_PATH)
        input("\n  Press Enter to exit…")
        return 1
    _step("Policy Agent measured-boot gate passed ✓")
    activation_evidence["steps"]["policy_agent_started"] = True

    # ── Step 4: Start Assistant Orchestrator entrypoint ───────────
    _step(
        "Starting Assistant Orchestrator service entrypoint "
        f"({runtime_mode.value} mode)…"
    )
    try:
        _orchestrator_service = AssistantOrchestratorService.from_runtime_mode(
            runtime_mode,
            dev_mode_override=_dev_mode,  # centralised via resolve_dev_mode()
            shared_pipeline=_shared_pipeline,
        )
    except ConfigResolutionError as exc:
        logger.error("Assistant Orchestrator config resolution failed: %s", exc)
        activation_evidence["failure"] = {
            "timestamp": _timestamp(),
            "stage": "assistant_orchestrator_config",
            "code": exc.code,
            "message": str(exc),
            "disposition": "FAIL",
            "fail_closed": "true",
        }
        _record_activation_evidence(activation_evidence)
        _step(
            "ERROR: Assistant Orchestrator config resolution failed "
            f"({exc.code}) (Fail-Closed)."
        )
        _step("Check %s for details." % _LOG_PATH)
        input("\n  Press Enter to exit…")
        return 1
    if not _orchestrator_service.start():
        logger.error("Assistant Orchestrator entrypoint failed to initialize")
        if _orchestrator_service.last_failure is not None:
            logger.error(
                "Assistant Orchestrator startup fingerprint: %s",
                _orchestrator_service.last_failure,
            )
            activation_evidence["failure"] = dict(_orchestrator_service.last_failure)
            _step(
                "ERROR: Assistant Orchestrator startup failed "
                f"[{_orchestrator_service.last_failure.get('code', 'UNKNOWN')}] "
                "(Fail-Closed)."
            )
        else:
            activation_evidence["failure"] = {
                "timestamp": _timestamp(),
                "stage": "assistant_orchestrator_start",
                "code": "AO_START_FAILED",
                "message": "Assistant Orchestrator startup failed with no fingerprint.",
                "disposition": "FAIL",
                "fail_closed": "true",
            }
            _step("ERROR: Assistant Orchestrator startup failed (Fail-Closed).")
        _record_activation_evidence(activation_evidence)
        _step("Check %s for details." % _LOG_PATH)
        input("\n  Press Enter to exit…")
        return 1
    _step("Assistant Orchestrator entrypoint ready ✓")
    activation_evidence["steps"]["assistant_orchestrator_started"] = True

    # ── Step 5: Initialize Session Store (encrypted at rest) ──────
    # Sprint 14 EA-4 (ADR-025): the production session store is the AES-256-GCM
    # EncryptedSessionStore.  build_session_store() requires an explicit dev_mode
    # argument (EA-7 MINOR-3 fix): in production (dev_mode=False) a missing
    # BLARAI_DEK_KEYSTORE raises StoreProvisioningError rather than silently
    # falling back to the SoftwareSealer (ADR-025 §2.8(a) — symmetric with the
    # audit refuse-to-start).  The already-resolved _dev_mode is passed through.
    #
    # Fail-closed: unlike the substrate store (memory is non-load-bearing and
    # degrades to None on DEK failure), sessions.db holds the user's actual
    # conversation history.  If the DEK cannot be unsealed, build_session_store
    # raises DekEnvelopeError, which propagates into the handler below — we
    # REFUSE to start rather than fall back to a plaintext store.  There is no
    # plaintext session-store path in production.
    _step("Initializing session database (encrypted at rest)…")

    db_path = SESSION_DB_PATH if SESSION_DB_PATH else ":memory:"
    if db_path == ":memory:":
        logger.warning(
            "%%LOCALAPPDATA%% not set — using in-memory session database"
        )

    try:
        _session_store = build_session_store(db_path, dev_mode=_dev_mode)
        _step("Session database ready (encrypted) ✓")
    except Exception as exc:
        # Fail-closed: DEK unseal failure or any other construction error
        # refuses startup — NO plaintext fallback (ADR-025).
        logger.error("EncryptedSessionStore init failed (fail-closed): %s", exc)
        activation_evidence["failure"] = {
            "timestamp": _timestamp(),
            "stage": "session_store_init",
            "code": "SESSION_STORE_INIT_FAILED",
            "message": str(exc),
            "disposition": "FAIL",
            "fail_closed": "true",
        }
        _record_activation_evidence(activation_evidence)
        _step("ERROR: Encrypted session database initialization failed (fail-closed).")
        input("\n  Press Enter to exit…")
        return 1

    # ── Step 6: Initialize Transport Gateway ──────────────────────
    # Use the already-resolved _dev_mode rather than re-deriving it from
    # runtime_mode — keeps the three call sites consistent (resolve once, use
    # everywhere) and ensures the interlock above covers the gateway as well.
    gateway_dev_mode = _dev_mode
    # host_mode reflects the deployment topology: HOST (default) → loopback
    # + mTLS; GUEST → AF_HYPERV + mTLS across the VM boundary (#615).
    # resolve_gateway_topology flips to the guest boundary ONLY when GUEST is
    # selected AND this host can serve AF_HYPERV; otherwise it falls back to
    # host-mode cleanly (host-mode is BlarAI's always-available default — the
    # guest path is an added capability, never a replacement that can wedge
    # the default boot).
    gateway_host_mode = resolve_gateway_topology(
        runtime_mode, dev_mode=gateway_dev_mode
    )
    # Surface a clear downgrade signal when GUEST was requested but we resolved
    # to host-mode (AF_HYPERV unavailable) — committed-but-fell-back honesty.
    guest_topology_downgraded = (
        runtime_mode == DeploymentMode.GUEST
        and not gateway_dev_mode
        and gateway_host_mode
    )

    if gateway_dev_mode:
        _step("Initializing transport gateway (dev loopback mode)…")
    elif guest_topology_downgraded:
        _step(
            "Initializing transport gateway (GUEST requested but AF_HYPERV "
            "unavailable — falling back to production host-mode: loopback + "
            "mTLS)…"
        )
    elif gateway_host_mode:
        _step(
            "Initializing transport gateway (production host-mode: "
            "loopback + mTLS, fidelity-2)…"
        )
    else:
        _step(
            "Initializing transport gateway (production guest-mode: "
            "AF_HYPERV boundary, #615)…"
        )

    # Single source of truth for the gateway's transport port (the prompt
    # path).  resolve_gateway_port returns the Assistant Orchestrator's
    # loopback listener port for BOTH dev and production host-mode — the AO is
    # the service that handles PROMPT_REQUEST.  The previous code pointed
    # production host-mode at the PA's port (5000), so the gateway handshook
    # the PA (which answers) but sent the prompt to the PA too — the PA
    # rejected PROMPT_REQUEST with "Unsupported message type", which surfaced as
    # "stream_tokens: error from Orchestrator". mTLS is the only prod/dev
    # difference on this path, not the port. See resolve_gateway_port.
    gateway_port = resolve_gateway_port(
        dev_mode=gateway_dev_mode,
        host_mode=gateway_host_mode,
    )

    # In production (dev_mode=False), supply the per-boot client cert paths
    # minted above so the gateway's fidelity-2 connect path constructs the
    # mTLS VsockConfig correctly (ADR-026 / S15-EA-4d).  In dev_mode
    # _per_boot_certs is None and the loopback path skips mTLS per existing
    # design.
    gateway = TransportGateway(
        session_store=_session_store,
        dev_mode=gateway_dev_mode,
        host_mode=gateway_host_mode,
        host="127.0.0.1",
        port=gateway_port,
        mtls_cert_path=(
            str(_per_boot_certs.gateway_client_cert_path)
            if _per_boot_certs is not None
            else ""
        ),
        mtls_key_path=(
            str(_per_boot_certs.gateway_client_key_path)
            if _per_boot_certs is not None
            else ""
        ),
        ca_cert_path=(
            str(_per_boot_certs.ca_cert_path)
            if _per_boot_certs is not None
            else ""
        ),
        # UC-003 Workstream B #1: thread the AO-resolved [knowledge].images_enabled
        # weld-lock into the gateway so the gateway-side image FETCH gate honors
        # the same flag the AO storage gate reads (single source of truth — read
        # off the already-started orchestrator service, never a second TOML parse).
        # Default-dormant: false until the LA go-live ceremony flips the config.
        images_enabled=_orchestrator_service.knowledge_images_enabled,
        # Headless-coding dispatch (agentic-setup brief §9): thread the AO-resolved
        # [fleet_dispatch].enabled into the gateway's DispatchCoordinator (single
        # source of truth, read off the started orchestrator service — never a
        # second TOML parse). Default-dormant: false until the operator flips it.
        fleet_dispatch_enabled=_orchestrator_service.fleet_dispatch_enabled,
        # #670: the dispatch target is config-driven (not compiled in) — thread the
        # AO-resolved roots into the gateway's fleet config (empty -> compiled-in fallback).
        fleet_dispatch_agentic_setup_dir=_orchestrator_service.fleet_dispatch_agentic_setup_dir,
        fleet_dispatch_projects_dir=_orchestrator_service.fleet_dispatch_projects_dir,
        # Coordinator program C1 read surface (#843, ADR-039): thread the
        # AO-resolved [coordinator] settings into the gateway's
        # CoordCoordinator (single source of truth, read off the started
        # orchestrator service — never a second TOML parse). Default-dormant:
        # false until the operator flips [coordinator].enabled.
        coordinator_enabled=_orchestrator_service.coordinator_enabled,
        coordinator_projects=_orchestrator_service.coordinator_projects,
        coordinator_campaign_state_path=(
            _orchestrator_service.coordinator_battery_campaign_state_path
        ),
        # #801: thread the AO-resolved [context].session_idle_ttl_s into the
        # gateway's session-state reaper (single source of truth, read off the
        # started orchestrator service — never a second TOML parse), so ONE
        # operator-visible knob bounds session-keyed state in both processes.
        session_state_ttl_s=_orchestrator_service.session_idle_ttl_s,
    )
    _step("Transport gateway ready ✓")
    activation_evidence["steps"]["gateway_initialized"] = True

    # Headless-coding dispatch EXECUTE (#670): give the AO its swap context — how to relaunch
    # THIS launcher after a model swap (its REAL startup mode, captured from its own argv, not
    # a guess) + the daemon→main step-aside signal. The AO daemon thread cannot sys.exit the
    # process, so EXECUTE asks the launcher main thread (running the app) to step aside via
    # _request_step_aside. Always set (harmless while dormant — EXECUTE never fires unless the
    # operator both enables [fleet_dispatch] AND approves a dispatch).
    try:
        from shared.fleet.swap_ops import compute_relaunch_argv as _compute_relaunch

        _relaunch_argv, _relaunch_cwd = _compute_relaunch(
            winui=(_ui_mode() == "winui"),
            go_live=("--go-live" in sys.argv),
            repo_root=str(Path(__file__).resolve().parent.parent),
        )
        _orchestrator_service.set_swap_context(
            relaunch_argv=_relaunch_argv,
            relaunch_cwd=_relaunch_cwd,
            step_aside=_request_step_aside,
        )
    except Exception as _exc:  # noqa: BLE001 — never block boot on dispatch wiring
        logger.error("Dispatch swap-context wiring failed (continuing boot): %s", _exc)
    # Record the resolved transport topology (auditable boot evidence) — and
    # flag any GUEST→host-mode downgrade so a fell-back boot is never silently
    # indistinguishable from a true host-mode boot.
    activation_evidence["steps"]["gateway_topology"] = (
        "dev_loopback"
        if gateway_dev_mode
        else ("host_mode" if gateway_host_mode else "guest_af_hyperv")
    )
    if guest_topology_downgraded:
        activation_evidence["steps"]["gateway_topology_downgraded"] = True

    # ── Step 6a: Handshake preflight ──────────────────────────────
    _step("Executing real-runtime handshake preflight…")
    handshake_ok = asyncio.run(gateway.check_pa_status())
    if not handshake_ok:
        logger.error("Handshake preflight failed")
        activation_evidence["failure"] = {
            "timestamp": _timestamp(),
            "stage": "gateway_handshake",
            "code": "GATEWAY_HANDSHAKE_FAILED",
            "message": "Real-runtime handshake failed before UI launch.",
            "disposition": "FAIL",
            "fail_closed": "true",
        }
        _record_activation_evidence(activation_evidence)
        _step("ERROR: Real-runtime handshake failed (Fail-Closed).")
        _step("Check %s for details." % _LOG_PATH)
        input("\n  Press Enter to exit…")
        return 1
    _step("Real-runtime handshake passed ✓")
    activation_evidence["steps"]["gateway_handshake_ok"] = True

    # ── Step 6b: Prompt-flow preflight (production default-ON) ─────
    # The real model-loaded prompt-flow preflight runs a complete generation
    # (~8s) through the SAME send_prompt→AO path the user's prompts take. In
    # production it runs BY DEFAULT (the model is already loaded, so the cost
    # is one short generation, not a model load) — it is the gate that would
    # have caught the host-mode PROMPT_REQUEST misroute at boot instead of at
    # the user's first prompt. Reversible via BLARAI_PROMPTFLOW_PREFLIGHT=0.
    # Dev defaults OFF to keep iterative launches fast (opt in with =1).
    if not _prompt_flow_preflight_enabled(dev_mode=_dev_mode):
        _step(
            "Prompt-flow preflight skipped "
            "(set BLARAI_PROMPTFLOW_PREFLIGHT=1 to run it)."
        )
        activation_evidence["steps"]["prompt_flow_preflight"] = "skipped"
    elif _session_store is None:
        logger.error("Session store unavailable for prompt-flow preflight")
        activation_evidence["failure"] = {
            "timestamp": _timestamp(),
            "stage": "prompt_flow",
            "code": "PROMPT_FLOW_STORE_UNAVAILABLE",
            "message": "Session store unavailable before prompt-flow preflight.",
            "disposition": "FAIL",
            "fail_closed": "true",
        }
        _record_activation_evidence(activation_evidence)
        _step("ERROR: Prompt-flow preflight store unavailable (Fail-Closed).")
        _step("Check %s for details." % _LOG_PATH)
        input("\n  Press Enter to exit…")
        return 1
    else:
        _step("Executing minimal prompt-flow preflight…")
        prompt_flow_ok = _run_uat2_prompt_flow_preflight(
            gateway=gateway,
            session_store=_session_store,
            runtime_mode=runtime_mode,
        )
        if not prompt_flow_ok:
            logger.error("Minimal prompt-flow preflight failed")
            activation_evidence["failure"] = {
                "timestamp": _timestamp(),
                "stage": "prompt_flow",
                "code": "PROMPT_FLOW_FAILED",
                "message": "Minimal prompt-flow preflight failed before UI launch.",
                "disposition": "FAIL",
                "fail_closed": "true",
            }
            _record_activation_evidence(activation_evidence)
            _step("ERROR: Minimal prompt-flow preflight failed (Fail-Closed).")
            _step("Check %s for details." % _LOG_PATH)
            input("\n  Press Enter to exit…")
            return 1
        _step("Minimal prompt-flow preflight passed ✓")
        activation_evidence["steps"]["prompt_flow_ok"] = True

    # ── Step 7: Launch UI surface ─────────────────────────────────
    # Default is the Textual TUI (unchanged). BLARAI_UI=winui serves the
    # already-built gateway over the named pipe and runs the WinUI app
    # instead — same startup, different surface (ADR-014).
    if _ui_mode() == "winui":
        _step("Launching BlarAI WinUI surface…")
        logger.info("All components initialized — launching WinUI over named pipe")
        activation_evidence["disposition"] = "PASS"
        _record_activation_evidence(activation_evidence)
        repo_root = Path(__file__).resolve().parent.parent
        winui_rc = _run_winui_surface(
            gateway=gateway,
            session_store=_session_store,
            repo_root=repo_root,
        )
        logger.info("WinUI surface exited (rc=%s)", winui_rc)
        return winui_rc

    _step("Launching BlarAI Assistant TUI…")
    logger.info("All components initialized — launching Textual app")

    try:
        app = BlarAIApp(
            gateway=gateway,
            session_store=_session_store,
        )
        # #639 + #649 / ADR-024 §2.5 — ACTIVATE the ESCALATE human-review consumer on
        # the TUI surface. Register an operator-approval verifier so a PA ESCALATE
        # verdict PAUSES the turn and surfaces an inline approve/deny prompt instead
        # of the dormant silent-DENY. Verifier selection (#649): if Windows Hello is
        # available on this box, register the BiometricApprovalVerifier (a SYSTEM
        # fingerprint/PIN/face prompt — the LA's stated goal); otherwise fall back to
        # the in-process TUIApprovalVerifier modal (the #639 behaviour). Both run in
        # THIS launcher process, where the AO tool loop also runs (the AO is started
        # via _orchestrator_service.start() above; the gateway<->AO loopback-5001 hop
        # is in-process), so the verifier reaches the operator either way — the Hello
        # helper as a subprocess raising a system dialog, the TUI verifier via
        # App.call_from_thread. FAIL-SAFE: if the Hello prompt or the modal cannot
        # surface, the core request_escalation_consent times out to DENY (== today's
        # behaviour), so this can never reduce safety; and if registration here fails
        # entirely, the TUI still launches and ESCALATE stays silent-DENY. (The WinUI
        # primary surface registers the SAME Hello verifier in _run_winui_surface.)
        try:
            from shared.security.escalation_consent import register_verifier
            from services.ui_shell.src.escalation_prompt import TUIApprovalVerifier

            _repo_root_for_hello = Path(__file__).resolve().parent.parent
            _hello_verifier = _select_biometric_verifier(_repo_root_for_hello)
            if _hello_verifier is not None:
                register_verifier(_hello_verifier)
                logger.info(
                    "ESCALATE human-review consumer ACTIVE on TUI surface via Windows "
                    "Hello (#649) — PA ESCALATE verdicts now prompt for a fingerprint/"
                    "PIN/face approval."
                )
            else:
                register_verifier(TUIApprovalVerifier(app))
                logger.info(
                    "ESCALATE human-review consumer ACTIVE on TUI surface via the "
                    "Textual modal (#639; Windows Hello unavailable) — PA ESCALATE "
                    "verdicts now prompt the operator for approval."
                )
        except Exception as exc:  # noqa: BLE001 — never block TUI launch on this
            logger.warning(
                "Could not wire the ESCALATE TUI verifier (#639/#649): %s — ESCALATE "
                "stays silent-DENY (fail-safe).",
                exc,
            )
        activation_evidence["disposition"] = "PASS"
        _record_activation_evidence(activation_evidence)

        # Suppress stderr log output before TUI launch — raw log lines
        # bleed through Textual's screen as visible artifacts.
        # Raise level to CRITICAL+1 (effectively silent) rather than
        # removing the handler, which can interfere with Textual's
        # terminal initialisation.  Disk logging via FileHandler is
        # unaffected.
        root_logger = logging.getLogger()
        for handler in root_logger.handlers:
            if isinstance(handler, logging.StreamHandler) and not isinstance(
                handler, logging.FileHandler
            ):
                handler.setLevel(logging.CRITICAL + 1)

        app.run()
    except Exception as exc:
        logger.error("TUI crashed: %s", exc, exc_info=True)
        activation_evidence["failure"] = {
            "timestamp": _timestamp(),
            "stage": "tui_run",
            "code": "LAUNCHER_TUI_RUNTIME_ERROR",
            "message": str(exc),
            "disposition": "FAIL",
            "fail_closed": "true",
        }
        _record_activation_evidence(activation_evidence)
        _step("ERROR: Application crashed. Check %s" % _LOG_PATH)
        input("\n  Press Enter to exit…")
        return 1

    logger.info("TUI exited normally")
    return 0


# ---------------------------------------------------------------------------
# Module entry point
# ---------------------------------------------------------------------------

def _arm_egress_guard() -> None:
    """Wire + arm the code-enforced egress kill-switch (ADR-020 + ADR-027).

    Run at the REAL process entry, before any runtime network activity. Two steps,
    in order:

      1. Import the ADR-027 exfil-screen module (``shared.security.exfil_screen``)
         and call ``wire_into_egress_guard()`` so it registers its outbound-payload
         screener via the egress_guard arm-hook seam (no circular import — the
         screen module imports egress_guard, never the reverse; #634). Importing
         the module alone has no side effect by design, so the explicit wiring call
         is what arms the screener at ``arm()`` time. The module is imported
         defensively: it is a separate Sprint-17 stream (H-b) and may not be present
         in every checkout; its absence must not block the air-gapped baseline
         guard, which is the load-bearing control.
      2. ``egress_guard.arm()`` installs the process-wide guard and runs every
         registered arm-hook — so screener-registration + the anomaly auto-trip
         wiring (ADR-027 §3 / rule 4) are live from the first armed socket onward.

    STAGED/DORMANT (Sprint 17 + #634): the active allowlist stays loopback +
    AF_HYPERV; no external endpoint is widened in; the screener fires ONLY for
    sockets connected to a vetted external-allowlisted endpoint, so with the
    allowlist empty it never runs — screening enforces external-egress rules only
    once a web feature ships post-#556 and widens the allowlist. The
    arm/registration wiring, however, runs on EVERY production boot — so it is
    exercised and must be correct.
    """
    from shared.security import egress_guard

    try:
        # Importing the module has no side effect by design; wire_into_egress_guard
        # registers the screener via the arm-hook seam (#634). If H-b's module is
        # not on this checkout, the baseline guard still arms below — fail toward
        # the *more* restrictive posture.
        from shared.security import exfil_screen  # type: ignore[import-not-found]

        exfil_screen.wire_into_egress_guard()
    except ImportError:
        logger.info(
            "Egress: exfil-screen module not present; arming baseline guard "
            "(loopback + AF_HYPERV only). Outbound screening inactive until the "
            "module ships (ADR-027 rule 4)."
        )

    egress_guard.arm()


def request_egress_rearm_on_surface() -> bool:
    """Launcher-side seam to clear a tripped egress kill-switch via Windows Hello (#653).

    THE SINGLE FUNCTION the operator surface calls to drive an egress re-arm. It
    wraps the surface-independent core
    (:func:`shared.security.egress_rearm.request_egress_rearm`) with launcher
    logging, and returns a simple ``bool`` so a surface-side command handler does
    not need to know the :class:`ApprovalResult` shape.

    Why a launcher-side seam (and not a backend RPC the WinUI calls directly):
    the WinUI↔backend named pipe (``services/ui_backend``) is strictly
    request/response — the C# ``PipeClient`` writes one request and reads exactly
    one reply under a 1-permit gate, with NO background reader — so the backend
    cannot *push* an "Egress LOCKED" banner to the WinUI, and there is no existing
    channel to extend for a server-initiated notification. Re-arm therefore needs
    net-new cross-process notification plumbing (see the #653 report / the deferred
    WinUI-native ESCALATE prompt, which needs the SAME plumbing — build it once,
    reusable). Until that lands, this seam is the integration point: the AO tool
    loop and the Hello verifier both run in THIS launcher process, and the Hello
    prompt is a SYSTEM dialog, so calling this from here raises the prompt for the
    operator regardless of which surface (TUI/WinUI) is in front — exactly like the
    #649 ESCALATE verifier wiring in ``_run_winui_surface``.

    Fail-closed: returns True ONLY if the latch is now clear — either it was not
    tripped (no-op) or the operator approved via Hello in time. Every other path
    (no verifier wired, deny/cancel, timeout, verifier error) returns False and the
    kill-switch stays LOCKED. Never raises: any unexpected error is logged and
    treated as "stayed locked" (fail-closed).

    Returns:
        ``True`` iff egress is no longer tripped after the call; ``False`` if it
        remains LOCKED.
    """
    from shared.security import egress_guard
    from shared.security.egress_rearm import request_egress_rearm

    if not egress_guard.is_tripped():
        return True  # nothing to clear — no prompt raised
    _step("Egress kill-switch is LOCKED — requesting Windows Hello re-arm…")
    logger.warning(
        "Egress re-arm requested on surface (#653) — trip reason: %r",
        egress_guard.trip_reason(),
    )
    try:
        result = request_egress_rearm()
    except Exception as exc:  # noqa: BLE001 — fail-closed: never let re-arm crash the surface
        logger.error(
            "Egress re-arm seam: unexpected error (%r) — kill-switch stays LOCKED "
            "(fail-closed).",
            exc,
        )
        return False
    if result.approved and not egress_guard.is_tripped():
        _step("Egress kill-switch CLEARED via Windows Hello ✓")
        return True
    _step("Egress re-arm DENIED/cancelled — kill-switch stays LOCKED.")
    return False


if __name__ == "__main__":
    try:
        # Tier-0 security (ADR-020 + ADR-027): arm the code-enforced egress
        # kill-switch before any runtime network activity. Installed here at the
        # real process entry — not at module top-level, nor inside main() —
        # because the test suite imports this module and calls main() directly
        # with mocked dependencies, and must never inherit the process-wide
        # socket patch.
        _arm_egress_guard()

        sys.exit(main())
    except Exception as _fatal:
        # Catch import errors or any fatal crash before logging is set up
        import traceback
        _crash_log = os.path.join(
            os.environ.get("LOCALAPPDATA", ""), "BlarAI", "crash.log"
        )
        os.makedirs(os.path.dirname(_crash_log), exist_ok=True)
        with open(_crash_log, "a", encoding="utf-8") as _f:
            _f.write(f"\n--- CRASH {time.strftime('%Y-%m-%d %H:%M:%S')} ---\n")
            traceback.print_exc(file=_f)
        print(f"\nFATAL ERROR — see {_crash_log}")
        print(traceback.format_exc())
        input("\n  Press Enter to exit…")
        sys.exit(1)
