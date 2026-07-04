"""
Guest Parser Lifecycle Manager — UC-003 Stage C (#655, ADR-030 §3)
===================================================================
Deploys, starts, health-checks, and stops the guest-homed HTML parser as part
of the BlarAI launcher lifecycle.  The parser itself (service code + the
parse-channel message types) is built on a parallel branch; this module owns
ONLY the host-side lifecycle and references the health frame abstractly
through :mod:`launcher.parser_channel_seam`.

Topology (ADR-030 §3, LA-ratified 2026-06-10): hostile web bytes fetched by
the single host-side ``guarded_fetch`` door are PARSED ONLY inside the
NIC-less Hyper-V guest; cleaned text returns over AF_HYPERV vsock.  This
manager is how the guest side of that composition comes up and is proven
healthy before the capability is ever reported available.

Access mechanism (designed; controlled-session-proven steps are named in
``docs/security/guest_parser_provisioning_record.md``):

  * FILE TRANSFER — ``Copy-VMFile`` via the Hyper-V Guest Service Interface
    (``launcher.vm_manager.copy_file_to_vm``).  Requires ``hv_fcopy_daemon``
    running in the Alpine guest; the one recorded live attempt (2026-02-25,
    ``P5_GUEST_CHANNEL_NOT_READY``) failed because the daemon was not enabled
    — the provisioning script enables it persistently.
  * COMMAND EXECUTION — none exists host→guest for a Linux guest (PowerShell
    Direct is Windows-guest-only; the guest is NIC-less by posture).  Instead,
    a one-time-provisioned OpenRC supervisor inside the guest
    (``scripts/guest/parser_supervisor.sh``) watches ``incoming/`` and applies
    host-shipped bundles automatically: verify sha256 → atomic release swap →
    (re)start the parser child.  After provisioning, deploy/start/health/stop
    are fully host-automatable with NO guest console step.

Deploy protocol (host side, this module): ship ``bundle.zip`` then
``bundle.sha256`` then ``deploy.trigger`` — the trigger is copied LAST so the
guest supervisor never applies a partial deploy (it acts only on a present
trigger whose bundle hash verifies).

FAIL-CLOSED contract (ADR-030 §3 — the named anti-pattern is silent host-side
parsing): every failure path lands in :attr:`GuestParserState.FAILED` with a
deterministic failure fingerprint, ``is_available()`` is True ONLY in READY,
and there is NO fallback of any kind in this module.  The ingest URL mode
must consult availability and refuse when it is False; this module guarantees
the truth signal, the cleaner owns the refusal UX.

Security:
  - No external network calls (PowerShell subprocess + AF_HYPERV vsock only).
  - Fail-Closed everywhere; unbound parse-channel probe ⇒ never READY.
  - The launcher's zero-NIC assertion (verify_vm_zero_nic, at VM start)
    is a precondition this manager inherits, not re-implements.
"""

from __future__ import annotations

import hashlib
import json
import logging
import socket
import sys
import tempfile
import threading
import time
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Callable, Optional

from launcher.parser_channel_seam import (
    ParserEndpoint,
    get_parser_health_probe,
    get_parser_stop_signal,
)

if TYPE_CHECKING:
    from launcher.guest_parser_invoker import GuestParserBridge
    from shared.ipc.parse_channel import ParseResponse
from launcher.vm_manager import (
    VMState,
    copy_file_to_vm,
    get_vm_state,
    is_guest_service_interface_enabled,
)

logger = logging.getLogger(__name__)


# hv_sock service-GUID template suffix (Windows registers vsock ports as
# <port_hex>-facb-11e6-bd58-64006a7986d3 — see shared/constants.py).
_HV_SOCK_GUID_SUFFIX: str = "-facb-11e6-bd58-64006a7986d3"

# Guest-side filenames of the deploy protocol (must match
# scripts/guest/parser_supervisor.sh).
_BUNDLE_NAME: str = "bundle.zip"
_BUNDLE_HASH_NAME: str = "bundle.sha256"
_TRIGGER_NAME: str = "deploy.trigger"
_SERVICE_CONF_NAME: str = "service.conf"


def hv_service_guid_for_port(port: int) -> str:
    """Return the hv_sock template service GUID for an AF_VSOCK port."""
    return f"{port:08x}{_HV_SOCK_GUID_SUFFIX}"


class GuestParserConfigError(ValueError):
    """Deterministic guest-parser config failure (fail-closed)."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


@dataclass(frozen=True)
class GuestParserConfig:
    """Resolved ``[guest_parser]`` configuration (launcher/config/default.toml)."""

    enabled: bool
    vm_name: str
    guest_root: str
    vsock_port: int
    service_guid: str
    service_source_dir: str
    entry_module: str
    deploy_timeout_s: float
    health_timeout_s: float
    health_poll_interval_s: float
    bridge_python: str
    """AF_HYPERV version-bridge interpreter (#655).  Empty ⇒ auto-discover the
    3.14 helper interpreter; never the 3.11 runtime ``sys.executable``."""

    resident: bool = False
    """Resident model (#655 go-live).  The parser is baked into the guest image
    and auto-starts on boot via OpenRC, so the host-side ``Copy-VMFile`` deploy
    is dead on the guest kernel (it was never the live channel — the guest
    supervisor watches ``incoming/``; a resident image needs no shipment).  When
    True the launcher SKIPS ``deploy()`` entirely and goes straight to
    ``start()`` (legal from IDLE), awaiting the guest's own health.  When False
    the legacy deploy()→start() path runs unchanged."""

    mtls_cert: str = ""
    mtls_key: str = ""
    mtls_ca: str = ""
    """Host↔guest parse-channel mTLS material (#655 go-live prep — dormant).
    All three empty ⇒ plaintext-AF_HYPERV bring-up (the current default; the
    parse channel is on-box host↔guest vsock, never a network path, so the
    plaintext exposure is local-only).  When the guest is re-provisioned with
    certs, populating these activates mTLS on the health probe AND the content
    parse round-trip with NO code change — the plumbing is threaded through but
    inert until certs are present (fail-closed: partial material is rejected by
    the transport's own mTLS validation, never silently downgraded)."""


def default_config_path() -> Path:
    """The shipped launcher config file."""
    return Path(__file__).resolve().parent / "config" / "default.toml"


def load_guest_parser_config(
    config_path: str | Path | None = None,
) -> GuestParserConfig:
    """Load + validate the ``[guest_parser]`` section.  Fail-closed.

    Raises:
        GuestParserConfigError: missing file, unparseable TOML, type errors,
            port out of range, or a service GUID that does not match the
            hv_sock template for the configured port (the silent-divergence
            class the #615 work taught us to lock).
    """
    import tomllib

    path = Path(config_path) if config_path is not None else default_config_path()
    if not path.is_file():
        raise GuestParserConfigError(
            "GP_CONFIG_MISSING", f"launcher config not found: {path}"
        )
    try:
        with open(path, "rb") as file_obj:
            data = tomllib.load(file_obj)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise GuestParserConfigError(
            "GP_CONFIG_UNPARSEABLE", f"cannot parse {path}: {exc}"
        ) from exc

    section = data.get("guest_parser", {})
    if not isinstance(section, dict):
        raise GuestParserConfigError(
            "GP_CONFIG_SECTION_INVALID", "[guest_parser] is not a table"
        )

    def _get(key: str, default: object, kind: type) -> object:
        value = section.get(key, default)
        # bool is an int subclass — reject bools where numbers are expected
        # and non-bools where a bool is expected.
        if kind is float and isinstance(value, int) and not isinstance(value, bool):
            value = float(value)
        if not isinstance(value, kind) or (
            kind is int and isinstance(value, bool)
        ):
            raise GuestParserConfigError(
                "GP_CONFIG_TYPE_INVALID",
                f"guest_parser.{key} must be {kind.__name__}, got {value!r}",
            )
        return value

    enabled = _get("enabled", False, bool)
    # Reversible, ON-ONLY env override (#655 go-live).  A per-session operator
    # go-live can enable the guest parser via the env var WITHOUT editing the
    # committed default (which stays enabled=false — the welded-at-rest posture).
    # It only ever turns the feature ON; it never forces it off, and the next boot
    # WITHOUT the var is welded again.  This is the deliberate, reversible knob the
    # operator flips for the first live INGEST_FETCH ceremony.
    import os

    _env = os.environ.get("BLARAI_GUEST_PARSER_ENABLED")
    if _env is not None and _env.strip().lower() in ("1", "true", "yes", "on"):
        enabled = True
        logger.warning(
            "guest_parser: ENABLED via BLARAI_GUEST_PARSER_ENABLED env override "
            "(per-session operator go-live; the committed default stays disabled — "
            "the next boot WITHOUT this var is welded again).")
    vm_name = _get("vm_name", "BlarAI-Orchestrator", str)
    guest_root = _get("guest_root", "/opt/blarai/parser", str)
    vsock_port = _get("vsock_port", 50001, int)
    service_guid = str(_get("service_guid", hv_service_guid_for_port(50001), str))
    service_source_dir = _get("service_source_dir", "services/cleaner/guest", str)
    entry_module = _get("entry_module", "blarai_guest_parser", str)
    deploy_timeout_s = _get("deploy_timeout_s", 120.0, float)
    health_timeout_s = _get("health_timeout_s", 30.0, float)
    health_poll_interval_s = _get("health_poll_interval_s", 1.0, float)
    bridge_python = _get("bridge_python", "", str)
    resident = _get("resident", False, bool)
    mtls_cert = _get("mtls_cert", "", str)
    mtls_key = _get("mtls_key", "", str)
    mtls_ca = _get("mtls_ca", "", str)

    if not (0 < int(vsock_port) <= 0xFFFFFFFF):
        raise GuestParserConfigError(
            "GP_CONFIG_PORT_INVALID",
            f"guest_parser.vsock_port out of range: {vsock_port}",
        )
    expected_guid = hv_service_guid_for_port(int(vsock_port))
    if service_guid.strip().lower() != expected_guid:
        raise GuestParserConfigError(
            "GP_CONFIG_GUID_MISMATCH",
            f"guest_parser.service_guid {service_guid!r} does not match the "
            f"hv_sock template for port {vsock_port} ({expected_guid!r}); "
            "refusing fail-closed so addressing can never silently diverge.",
        )
    if float(health_timeout_s) <= 0 or float(health_poll_interval_s) <= 0:
        raise GuestParserConfigError(
            "GP_CONFIG_TIMEOUT_INVALID",
            "guest_parser health timeouts must be positive",
        )

    return GuestParserConfig(
        enabled=bool(enabled),
        vm_name=str(vm_name),
        guest_root=str(guest_root).rstrip("/"),
        vsock_port=int(vsock_port),
        service_guid=service_guid.strip().lower(),
        service_source_dir=str(service_source_dir),
        entry_module=str(entry_module),
        deploy_timeout_s=float(deploy_timeout_s),
        health_timeout_s=float(health_timeout_s),
        health_poll_interval_s=float(health_poll_interval_s),
        bridge_python=str(bridge_python),
        resident=bool(resident),
        mtls_cert=str(mtls_cert),
        mtls_key=str(mtls_key),
        mtls_ca=str(mtls_ca),
    )


class GuestParserState(str, Enum):
    """Guest parser lifecycle states (host-side view)."""

    IDLE = "idle"
    DEPLOYING = "deploying"
    DEPLOYED = "deployed"
    STARTING = "starting"
    READY = "ready"
    STOPPED = "stopped"
    FAILED = "failed"


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def _fingerprint(stage: str, code: str, message: str) -> dict[str, str]:
    return {
        "timestamp": _timestamp(),
        "stage": stage,
        "code": code,
        "message": message,
        "disposition": "FAIL",
        "fail_closed": "true",
    }


# ---------------------------------------------------------------------------
# AF_HYPERV version bridge (#655 Option A) — process-wide holder.
# The runtime venv is Python 3.11 (no socket.AF_HYPERV until 3.12).  When the
# launcher wiring detects that, it builds a GuestParserBridge (the 3.14
# subprocess invoker) and parks it here so the default reachability check + the
# seam-bound health probe route through it.  A future 3.12+ runtime makes the
# bridge unnecessary: the holder stays None and the in-process AF_HYPERV path
# below is used directly.
# ---------------------------------------------------------------------------

_bridge_lock = threading.Lock()
_bridge: "GuestParserBridge | None" = None  # noqa: F821


def set_guest_parser_bridge(bridge: "GuestParserBridge | None") -> None:  # noqa: F821
    """Park (or clear) the process-wide AF_HYPERV version bridge."""
    global _bridge
    with _bridge_lock:
        _bridge = bridge


def get_guest_parser_bridge() -> "GuestParserBridge | None":  # noqa: F821
    """The parked version bridge, or None (in-process AF_HYPERV / unbridged)."""
    with _bridge_lock:
        return _bridge


def _default_transport_reachable(endpoint: ParserEndpoint) -> bool:
    """TRANSPORT-level reachability: can the host open the AF_HYPERV socket?

    This is deliberately NOT a health check — it only proves the guest-side
    listener accepts.  The frame-level verdict belongs to the seam-bound probe.

    Routing (the #655 version-bridge):
      * The running interpreter HAS ``socket.AF_HYPERV`` (3.12+): open the
        socket in-process — the original #615 fast path, no subprocess.
      * The running interpreter LACKS it (the 3.11 runtime): route through the
        parked :class:`launcher.guest_parser_invoker.GuestParserBridge` (a 3.14
        subprocess).  No bridge parked ⇒ refuse fail-closed (the launcher binds
        it at startup when the feature is enabled; an unbound bridge on a 3.11
        interpreter means the capability cannot be claimed).
    """
    if sys.platform != "win32":
        return False

    if not hasattr(socket, "AF_HYPERV"):
        bridge = get_guest_parser_bridge()
        if bridge is None:
            logger.error(
                "guest-parser: this Python (%s) lacks socket.AF_HYPERV (needs "
                ">= 3.12) and no version bridge is bound — cannot reach the "
                "guest parser; refusing fail-closed (#655: the 3.14 subprocess "
                "bridge isolates the version jump without migrating the 3.11 "
                "runtime).",
                sys.version.split()[0],
            )
            return False
        try:
            return bool(bridge.reachable(endpoint))
        except Exception as exc:  # noqa: BLE001 — fail-closed, never raise
            logger.error(
                "guest-parser bridge reachability raised (%s) — fail-closed",
                type(exc).__name__,
            )
            return False

    # In-process AF_HYPERV (3.12+ runtime) — the #615 fast path.
    from shared.ipc.vsock import AF_HYPERV, HV_PROTOCOL_RAW

    probe: socket.socket | None = None
    try:
        probe = socket.socket(AF_HYPERV, socket.SOCK_STREAM, HV_PROTOCOL_RAW)
        probe.settimeout(min(endpoint.timeout_s, 5.0))
        probe.connect((endpoint.vm_id, endpoint.service_guid))
        return True
    except OSError as exc:
        logger.debug("guest-parser transport probe: %s", exc)
        return False
    finally:
        if probe is not None:
            try:
                probe.close()
            except OSError:
                pass


class GuestParserManager:
    """Deploy / start / health-check / stop state machine for the guest parser.

    All Hyper-V interaction goes through :mod:`launcher.vm_manager` (mocked in
    unit tests); the frame-level health check goes through the parser-channel
    seam (bound at integration time; UNBOUND ⇒ fail closed).
    """

    def __init__(
        self,
        config: GuestParserConfig,
        *,
        repo_root: Path | None = None,
        vm_id: str | None = None,
        transport_check: Callable[[ParserEndpoint], bool] | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        from shared.constants import ORCHESTRATOR_VM_ID

        self._config = config
        self._repo_root = (
            repo_root
            if repo_root is not None
            else Path(__file__).resolve().parents[1]
        )
        self._vm_id = vm_id if vm_id is not None else ORCHESTRATOR_VM_ID
        self._transport_check = (
            transport_check
            if transport_check is not None
            else _default_transport_reachable
        )
        self._clock = clock
        self._sleep = sleep
        self._lock = threading.Lock()
        self._state: GuestParserState = GuestParserState.IDLE
        self._failure: dict[str, str] | None = None

    # ── introspection ────────────────────────────────────────────────────

    @property
    def state(self) -> GuestParserState:
        with self._lock:
            return self._state

    @property
    def failure(self) -> dict[str, str] | None:
        """The deterministic fingerprint of the last failure, if any."""
        with self._lock:
            return dict(self._failure) if self._failure is not None else None

    @property
    def config(self) -> GuestParserConfig:
        return self._config

    def is_available(self) -> bool:
        """True ONLY when the guest parser is proven READY.

        This is the truth signal the ingest URL mode consults: False means
        the cleaner MUST refuse URL ingest (ADR-030 §3) — never fall back to
        host parsing.
        """
        return self.state == GuestParserState.READY

    def _endpoint(self) -> ParserEndpoint:
        return ParserEndpoint(
            vm_id=self._vm_id,
            service_guid=self._config.service_guid,
            vsock_port=self._config.vsock_port,
            timeout_s=self._config.health_timeout_s,
        )

    def _fail(self, stage: str, code: str, message: str) -> bool:
        fp = _fingerprint(stage, code, message)
        with self._lock:
            self._state = GuestParserState.FAILED
            self._failure = fp
        logger.error("guest-parser %s FAILED [%s]: %s", stage, code, message)
        return False

    def _set_state(self, state: GuestParserState) -> None:
        with self._lock:
            self._state = state

    # ── deploy ───────────────────────────────────────────────────────────

    def deploy(self) -> bool:
        """Ship the parser service bundle into the guest's ``incoming/``.

        Protocol: bundle.zip → bundle.sha256 → deploy.trigger (trigger LAST —
        the guest supervisor's commit point, so a partial copy is never
        applied).  Returns True on success (state → DEPLOYED).  Fail-closed:
        any precondition or copy failure → state FAILED + fingerprint.
        """
        if not self._config.enabled:
            return self._fail(
                "deploy",
                "GP_DISABLED",
                "guest_parser.enabled is false — deploy refused",
            )
        if self.state not in (GuestParserState.IDLE, GuestParserState.STOPPED):
            return self._fail(
                "deploy",
                "GP_STATE_INVALID",
                f"deploy not legal from state {self.state.value!r}",
            )
        self._set_state(GuestParserState.DEPLOYING)

        if get_vm_state(self._config.vm_name) != VMState.RUNNING:
            return self._fail(
                "deploy",
                "GP_VM_NOT_RUNNING",
                f"VM '{self._config.vm_name}' is not Running — the launcher "
                "starts the VM before the parser deploy; refusing.",
            )
        if not is_guest_service_interface_enabled(self._config.vm_name):
            return self._fail(
                "deploy",
                "GP_GSI_DISABLED",
                "Hyper-V Guest Service Interface is not enabled — Copy-VMFile "
                "deploy channel unavailable.",
            )

        source_dir = self._repo_root / self._config.service_source_dir
        if not source_dir.is_dir():
            return self._fail(
                "deploy",
                "GP_SOURCE_MISSING",
                f"parser service source dir missing: {source_dir} (the guest "
                "parser service is built on the parallel #655 branch; deploy "
                "binds at integration).",
            )

        incoming = f"{self._config.guest_root}/incoming"
        with tempfile.TemporaryDirectory(prefix="blarai-gp-deploy-") as tmp:
            tmp_path = Path(tmp)
            bundle_path = tmp_path / _BUNDLE_NAME
            try:
                bundle_sha256 = self._build_bundle(source_dir, bundle_path)
            except OSError as exc:
                return self._fail(
                    "deploy", "GP_BUNDLE_BUILD_FAILED", f"bundle build: {exc}"
                )

            hash_path = tmp_path / _BUNDLE_HASH_NAME
            # sha256sum -c format: "<hash>  <filename>" (two spaces).  LF
            # endings are LOAD-BEARING: busybox sha256sum -c in the Alpine
            # guest treats a CRLF line as filename "bundle.zip\r" and fails —
            # never let Windows text-mode translation in here.
            hash_path.write_text(
                f"{bundle_sha256}  {_BUNDLE_NAME}\n",
                encoding="utf-8",
                newline="\n",
            )
            trigger_path = tmp_path / _TRIGGER_NAME
            trigger_path.write_text(
                json.dumps(
                    {
                        "staged_utc": _timestamp(),
                        "bundle_sha256": bundle_sha256,
                        "entry_module": self._config.entry_module,
                    },
                    indent=2,
                ),
                encoding="utf-8",
                newline="\n",
            )

            # Ship in commit-last order.
            for local, name in (
                (bundle_path, _BUNDLE_NAME),
                (hash_path, _BUNDLE_HASH_NAME),
                (trigger_path, _TRIGGER_NAME),
            ):
                ok = copy_file_to_vm(
                    source_path=local,
                    destination_path=f"{incoming}/{name}",
                    vm_name=self._config.vm_name,
                    timeout=self._config.deploy_timeout_s,
                )
                if not ok:
                    return self._fail(
                        "deploy",
                        "GP_COPY_FAILED",
                        f"Copy-VMFile failed for {incoming}/{name} — deploy "
                        "channel not ready (is hv_fcopy_daemon running in the "
                        "guest? see the provisioning record).",
                    )

        self._set_state(GuestParserState.DEPLOYED)
        logger.info(
            "guest-parser deploy shipped (bundle sha256 %s… → %s)",
            bundle_sha256[:12],
            incoming,
        )
        return True

    def _build_bundle(self, source_dir: Path, bundle_path: Path) -> str:
        """Zip the service files + a generated service.conf; return sha256."""
        with zipfile.ZipFile(
            bundle_path, "w", compression=zipfile.ZIP_DEFLATED
        ) as zip_obj:
            for child in sorted(source_dir.rglob("*")):
                if child.is_dir() or "__pycache__" in child.parts:
                    continue
                zip_obj.write(child, child.relative_to(source_dir).as_posix())
            zip_obj.writestr(
                _SERVICE_CONF_NAME,
                (
                    "# generated by launcher.guest_parser — sourced by the\n"
                    "# guest supervisor (scripts/guest/parser_supervisor.sh)\n"
                    f"ENTRY_MODULE={self._config.entry_module}\n"
                    f"VSOCK_PORT={self._config.vsock_port}\n"
                ),
            )
        digest = hashlib.sha256()
        with open(bundle_path, "rb") as file_obj:
            for chunk in iter(lambda: file_obj.read(1 << 20), b""):
                digest.update(chunk)
        return digest.hexdigest()

    # ── start / health ───────────────────────────────────────────────────

    def start(self) -> bool:
        """Await guest-parser readiness: transport reachable + health frame OK.

        The guest supervisor auto-(re)starts the parser when the VM boots and
        when a deploy lands — there is no host→guest exec step.  "Start" on
        the host side therefore means: wait (bounded) for the vsock listener,
        then require the seam-bound frame-level health probe to pass.
        UNBOUND probe ⇒ FAILED (the parse channel is built on the parallel
        branch; until the integration binds it, the parser can never be
        reported READY — fail-closed by construction).
        """
        if not self._config.enabled:
            return self._fail(
                "start", "GP_DISABLED", "guest_parser.enabled is false"
            )
        if self.state not in (
            GuestParserState.IDLE,
            GuestParserState.DEPLOYED,
        ):
            return self._fail(
                "start",
                "GP_STATE_INVALID",
                f"start not legal from state {self.state.value!r}",
            )
        self._set_state(GuestParserState.STARTING)
        endpoint = self._endpoint()

        deadline = self._clock() + self._config.health_timeout_s
        reachable = False
        while True:
            try:
                reachable = bool(self._transport_check(endpoint))
            except Exception as exc:  # noqa: BLE001 — fail-closed, never raise
                logger.error("guest-parser transport check error: %s", exc)
                reachable = False
            if reachable or self._clock() >= deadline:
                break
            self._sleep(self._config.health_poll_interval_s)

        if not reachable:
            return self._fail(
                "start",
                "GP_HEALTH_TIMEOUT",
                f"guest parser vsock listener not reachable within "
                f"{self._config.health_timeout_s:.0f}s "
                f"(vm_id={endpoint.vm_id}, service_guid={endpoint.service_guid}).",
            )

        probe = get_parser_health_probe()
        if probe is None:
            return self._fail(
                "start",
                "GP_CHANNEL_UNBOUND",
                "no parse-channel health probe is bound "
                "(launcher.parser_channel_seam) — the parse-channel message "
                "types are built on the parallel #655 branch; the guest "
                "parser stays unavailable until the integration binds the "
                "probe (fail-closed).",
            )
        try:
            healthy = bool(probe(endpoint))
        except Exception as exc:  # noqa: BLE001 — fail-closed
            return self._fail(
                "start", "GP_HEALTH_PROBE_ERROR", f"health probe raised: {exc}"
            )
        if not healthy:
            return self._fail(
                "start",
                "GP_HEALTH_FAILED",
                "guest parser reachable but the health frame check failed.",
            )

        self._set_state(GuestParserState.READY)
        with self._lock:
            self._failure = None
        logger.info(
            "guest-parser READY (port %d, guid %s)",
            self._config.vsock_port,
            self._config.service_guid,
        )
        return True

    def check_health(self) -> bool:
        """Re-probe a READY parser; a failed re-probe degrades READY → FAILED.

        This is the service-crash detector: the guest supervisor gives up
        after bounded restarts (its listener disappears), the next health
        check here fails, availability flips False, and URL-mode ingest
        refuses from that moment on.
        """
        if self.state != GuestParserState.READY:
            return False
        probe = get_parser_health_probe()
        if probe is None:
            return not self._fail(
                "health",
                "GP_CHANNEL_UNBOUND",
                "health probe unbound during steady-state check",
            )
        try:
            healthy = bool(probe(self._endpoint()))
        except Exception as exc:  # noqa: BLE001 — fail-closed
            healthy = False
            logger.error("guest-parser steady-state probe raised: %s", exc)
        if not healthy:
            self._fail(
                "health",
                "GP_HEALTH_LOST",
                "guest parser stopped answering health checks (service "
                "crash / guest restart) — capability withdrawn fail-closed.",
            )
            return False
        return True

    # ── parse (URL-ingest content path) ──────────────────────────────────

    def parse_html(
        self, html: str, source_url: str = ""
    ) -> "ParseResponse | None":
        """Parse fetched HTML inside the guest; return the decoded response.

        The host-side entry point the URL-ingest path calls AFTER the single
        ``guarded_fetch`` door returns a body: the hostile HTML crosses to the
        NIC-less guest over the parse channel and only the cleaned text +
        extraction verdict comes back (ADR-030 §3).  Routes through the parked
        version bridge on the 3.11 runtime, in-process AF_HYPERV on 3.12+.

        Refuses (returns ``None``) unless the parser is proven READY — URL
        ingest NEVER falls back to host-side parsing.  Never raises: an
        over-cap body, a channel violation, an unreachable guest, or a bridge
        crash all map to ``None`` and the caller renders a loud refusal.

        Args:
            html: the fetched page text (``guarded_fetch`` already decoded it
                by the page's declared charset); re-encoded UTF-8 for the
                channel (the guest re-decodes UTF-8 — charset is the host
                fetch layer's job, parser_service docstring).
            source_url: extractor-heuristic metadata ONLY (nothing in the guest
                fetches).  A value that violates the channel's printable-ASCII /
                length rule is dropped to ``""`` so a legitimate fetch is never
                refused over metadata.
        """
        if not self.is_available():
            return None

        # Lazy imports keep this module's import light and acyclic (the manager
        # references the parse channel abstractly via the seam elsewhere; the
        # round-trip client is launcher-wiring-level).
        import uuid as _uuid

        from launcher.guest_parser_health import parse_round_trip
        from shared.ipc.parse_channel import (
            PARSE_SOURCE_URL_MAX_CHARS,
            ParseChannelError,
            encode_parse_request,
        )

        safe_source_url = (
            source_url
            if (
                len(source_url) <= PARSE_SOURCE_URL_MAX_CHARS
                and all(0x20 <= ord(ch) < 0x7F for ch in source_url)
            )
            else ""
        )
        try:
            request_frames = encode_parse_request(
                request_id=_uuid.uuid4().hex,
                html=html.encode("utf-8"),
                source_url=safe_source_url,
            )
        except (ParseChannelError, ValueError) as exc:
            logger.warning(
                "guest-parser parse_html: request refused at encode (%s) — "
                "fail-closed (oversize body for the %d-byte parse channel).",
                type(exc).__name__,
                # PARSE_BODY_MAX_BYTES is the relevant bound; label only.
                262_144,
            )
            return None

        try:
            return parse_round_trip(
                self._endpoint(),
                request_frames,
                mtls_cert=self._config.mtls_cert,
                mtls_key=self._config.mtls_key,
                mtls_ca=self._config.mtls_ca,
            )
        except Exception as exc:  # noqa: BLE001 — fail-closed, never raise
            logger.error(
                "guest-parser parse_html round-trip raised (%s) — fail-closed",
                type(exc).__name__,
            )
            return None

    # ── stop ─────────────────────────────────────────────────────────────

    def stop(self) -> None:
        """Stop integration with the #657 stop-on-exit policy.  Never raises.

        Sends the seam-bound graceful-stop signal when one is registered
        (best-effort); the AUTHORITATIVE stop is the launcher's existing VM
        stop-on-exit (#657 ``vm_stop_on_exit`` policy) — the parser dies with
        the VM.  Called from the launcher's ``_cleanup`` BEFORE ``_cleanup_vm``.
        """
        try:
            if self.state == GuestParserState.READY:
                signal = get_parser_stop_signal()
                if signal is not None:
                    try:
                        signal(self._endpoint())
                    except Exception as exc:  # noqa: BLE001 — best-effort only
                        logger.warning(
                            "guest-parser graceful stop signal failed "
                            "(VM stop-on-exit remains authoritative): %s",
                            exc,
                        )
        finally:
            self._set_state(GuestParserState.STOPPED)
            logger.info(
                "guest-parser stopped (authoritative teardown: #657 VM "
                "stop-on-exit policy)"
            )


# ---------------------------------------------------------------------------
# Process-wide accessor (in-process integration point, mirrors the
# escalation_consent register/get idiom).  The launcher parks the manager it
# built here so the ingest path (same process: the AO tool loop runs in the
# launcher) can consult is_available().
# ---------------------------------------------------------------------------

_manager_lock = threading.Lock()
_manager: Optional[GuestParserManager] = None


def set_guest_parser_manager(manager: Optional[GuestParserManager]) -> None:
    """Park (or clear) the process-wide guest parser manager."""
    global _manager
    with _manager_lock:
        _manager = manager


def get_guest_parser_manager() -> Optional[GuestParserManager]:
    """The launcher-built manager, or None (⇒ capability unavailable)."""
    with _manager_lock:
        return _manager


def guest_parser_available() -> bool:
    """Convenience truth signal for the ingest URL path.

    False when no manager exists, the feature is disabled, or the parser is
    not proven READY — in every one of those cases URL-mode ingest must
    refuse (ADR-030 §3).
    """
    manager = get_guest_parser_manager()
    return manager is not None and manager.is_available()
