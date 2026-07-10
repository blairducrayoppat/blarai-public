"""
Guest-Oracle AF_HYPERV Transport — the 3.11-side invoker + factory (#744)
=========================================================================
The missing limb of the guest-certified oracle corridor: something that ships
``(snapshot_zip, oracle_rel_path)`` to the NIC-less Alpine guest
(``BlarAI-Orchestrator``) over AF_HYPERV vsock as an ORACLE_EXEC_REQUEST and
returns the guest's advisory ``{"status", "reason", "evidence"}`` verdict from
the ORACLE_EXEC_RESPONSE.  :func:`make_guest_oracle_transport` produces exactly
the ``Callable[[bytes, str], dict]`` that
:func:`shared.fleet.guest_oracle.run_guest_oracle` accepts as ``transport``.

STRUCTURAL DORMANCY (#744 — non-negotiable)
===========================================
NO production code path constructs or registers this transport.  The factory
exists BUILT-NOT-REGISTERED (the #655 ``url_adjudicator`` precedent):
``SwapOps.run_guest_oracle`` / ``swap_ops.real_run_guest_oracle`` keep
``transport=None``, so even with the ``[fleet_dispatch].guest_oracle_enabled``
knob ON the pipeline reports an honest ``not-run``
(``guest-transport-unregistered``).  Regression locks in
``shared/tests/test_guest_oracle_transport.py`` pin BOTH facts: the production
call site still passes ``transport=None``, and no production module imports
this factory.  Registering it — one line at the ``real_run_guest_oracle`` call
site — is the LA's supervised go-live ceremony, together with guest pytest
provisioning and the knob flip.

TRANSPORT ROUTING (the proven #655 pattern, mirrored exactly)
=============================================================
  * The running interpreter HAS ``socket.AF_HYPERV`` (3.12+): the round-trip
    opens the hv_sock in-process (:mod:`shared.ipc.vsock`) — no subprocess.
  * The running interpreter LACKS it (the 3.11 runtime): the round-trip goes
    through :class:`GuestOracleBridge` — a short-lived Python 3.14 subprocess
    running :mod:`shared.fleet.guest_oracle_bridge` (one process per op; ONE
    guest run per JOB is the lowest-frequency corridor in the system).
    Interpreter discovery order mirrors the launcher invoker: an explicit
    ``bridge_python``, then ``py -3.14``, then the known dev-box path — a
    candidate qualifies ONLY if it reports ``socket.AF_HYPERV``; the 3.11
    ``sys.executable`` is NEVER silently used.  No candidate ⇒
    :class:`BridgeUnavailableError` AT FACTORY TIME (loud at the wiring
    ceremony, never a surprise in the swap teardown).

This module lives in ``shared/fleet/`` (not ``launcher/``) because the swap
driver is the caller and ``shared`` must not import ``launcher`` (layering);
it MIRRORS :mod:`launcher.guest_parser_invoker` / the
``launcher.guest_parser_health`` round-trip rather than importing them.

FAIL-CLOSED CONTRACT
====================
The factory may raise (wiring-time validation: bad port/GUID, no bridge
interpreter).  The RETURNED callable never raises: an unsendable request, an
unreachable guest, a garbled/truncated response, a correlation mismatch, or a
bridge crash all map to an honest ``{"status": "not-run", ...}`` with a stable
machine reason — the pipeline's contract (never an implied pass, never a raise
into the swap teardown, which guards it again regardless).

mTLS posture (mirror of what the #655 guest_parser bridge ships today):
plaintext-AF_HYPERV bring-up by default (the corridor is on-box host↔guest
vsock, never a network path), dormant mTLS plumbing threaded through — passing
``mtls_cert``/``mtls_key``/``mtls_ca`` activates mTLS on the round-trip with
no code change; partial material is rejected by the transport's own
validation, never silently downgraded.

Security: no external network calls (AF_HYPERV vsock / the bridge subprocess
only — the air-gap import scan covers ``shared/``); logs carry structural
labels only, never snapshot source bytes.
"""

from __future__ import annotations

import json
import logging
import os
import socket
import struct
import subprocess
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from shared.constants import ORCHESTRATOR_VM_ID
from shared.fleet.guest_oracle import REASON_GUEST_ERROR
from shared.ipc.oracle_channel import (
    OracleChannelError,
    OracleChunkAssembler,
    OracleExecResponse,
    decode_oracle_response,
    encode_oracle_request,
)
from shared.ipc.protocol import MessageType

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Corridor defaults (the #744 design pins the BlarAI-Orchestrator guest at
# vsock 50001 — the same service port the ticket names; the factory keeps it a
# parameter so the go-live ceremony can re-point without a code change).
# ---------------------------------------------------------------------------

#: hv_sock service-GUID template suffix (Windows registers vsock ports as
#: <port_hex>-facb-11e6-bd58-64006a7986d3 — see shared/constants.py).
_HV_SOCK_GUID_SUFFIX: str = "-facb-11e6-bd58-64006a7986d3"

#: The #744-designed guest service port (ticket: "NIC-less Alpine, vsock 50001").
ORACLE_VSOCK_PORT_DEFAULT: int = 50001

#: Round-trip budget.  The guest-side pytest run is bounded at 600 s
#: (``guest_oracle.execute_snapshot``); 630 s covers it plus extract/transfer
#: slack.  The bridge subprocess adds its own spawn margin on top.
ORACLE_TRANSPORT_TIMEOUT_S_DEFAULT: float = 630.0

#: Stable machine reasons this transport adds to the closed not-run vocabulary
#: (the pipeline passes any not-run reason through to the evidence block).
REASON_GUEST_UNREACHABLE: str = "guest-unreachable"
REASON_REQUEST_UNSENDABLE: str = "oracle-request-unsendable"

# The known absolute path the dev box ships Python 3.14 at (discovery step 3;
# mirrors launcher.guest_parser_invoker._KNOWN_BRIDGE_PATHS).
_KNOWN_BRIDGE_PATHS: tuple[str, ...] = (
    r"C:\Users\mrbla\AppData\Local\Python\pythoncore-3.14-64\python.exe",
)

# The `py -3.14` launcher form (discovery step 2) — Windows only.
_PY_LAUNCHER_ARGS: tuple[str, ...] = ("py", "-3.14")

# Frame length-prefix (matches shared.fleet.guest_oracle_bridge — 4-byte
# big-endian, 0 length terminates the list).
_LEN_FORMAT = "!I"
_LEN_SIZE = struct.calcsize(_LEN_FORMAT)

# A tiny probe program: exit 0 iff this interpreter has socket.AF_HYPERV.
_AF_HYPERV_PROBE = "import socket,sys;sys.exit(0 if hasattr(socket,'AF_HYPERV') else 7)"

# Bounded wait for the interpreter-capability probe (fast, local).
_PROBE_TIMEOUT_S: float = 10.0


def hv_service_guid_for_port(port: int) -> str:
    """Return the hv_sock template service GUID for an AF_VSOCK port."""
    return f"{port:08x}{_HV_SOCK_GUID_SUFFIX}"


class GuestOracleTransportError(ValueError):
    """Deterministic wiring-time transport-config failure (fail-closed, loud)."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


class BridgeUnavailableError(RuntimeError):
    """No 3.12+ interpreter with ``socket.AF_HYPERV`` could be discovered.

    Carries the structural code ``GO_BRIDGE_UNAVAILABLE`` — raised at FACTORY
    time so a missing bridge is caught at the wiring ceremony, never inside
    the swap teardown (which only ever sees the never-raising callable).
    """

    code: str = "GO_BRIDGE_UNAVAILABLE"

    def __init__(self, message: str) -> None:
        super().__init__(f"{self.code}: {message}")
        self.message = message


@dataclass(frozen=True)
class OracleEndpoint:
    """The guest oracle service's AF_HYPERV address (mirror of ParserEndpoint)."""

    vm_id: str
    service_guid: str
    vsock_port: int
    timeout_s: float


def bridge_required() -> bool:
    """True when the running interpreter lacks ``socket.AF_HYPERV`` (needs the
    subprocess bridge); False when it can open AF_HYPERV in-process (3.12+)."""
    return not hasattr(socket, "AF_HYPERV")


# ---------------------------------------------------------------------------
# Bridge interpreter discovery (mirrors launcher.guest_parser_invoker)
# ---------------------------------------------------------------------------


def _candidate_commands(bridge_python: str = "") -> list[list[str]]:
    """The interpreter-command candidates, in discovery order."""
    candidates: list[list[str]] = []
    if bridge_python.strip():
        candidates.append([bridge_python.strip()])
    if sys.platform == "win32":
        candidates.append(list(_PY_LAUNCHER_ARGS))
    for path in _KNOWN_BRIDGE_PATHS:
        if Path(path).is_file():
            candidates.append([path])
    return candidates


def _interp_has_af_hyperv(command: list[str]) -> bool:
    """True iff *command* launches an interpreter reporting ``socket.AF_HYPERV``."""
    try:
        result = subprocess.run(
            [*command, "-c", _AF_HYPERV_PROBE],
            capture_output=True,
            timeout=_PROBE_TIMEOUT_S,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        logger.debug("oracle bridge interpreter probe failed for %r: %s", command, exc)
        return False
    return result.returncode == 0


def discover_bridge_command(bridge_python: str = "") -> list[str]:
    """Return the bridge interpreter command, or raise BridgeUnavailableError.

    Tries each candidate in discovery order and returns the FIRST that reports
    ``socket.AF_HYPERV``.  The running 3.11 ``sys.executable`` is never a
    candidate — it cannot address AF_HYPERV, which is the whole bug the bridge
    routes around (#655 lesson, inherited).

    Raises:
        BridgeUnavailableError: no candidate qualifies (fail-closed, loud).
    """
    tried: list[str] = []
    for command in _candidate_commands(bridge_python):
        tried.append(" ".join(command))
        if _interp_has_af_hyperv(command):
            logger.info(
                "guest-oracle bridge interpreter resolved: %s", " ".join(command)
            )
            return command
    raise BridgeUnavailableError(
        "no Python 3.12+ interpreter with socket.AF_HYPERV found (tried: "
        f"{tried or ['<none>']}); pass bridge_python or install py -3.14 — "
        "refusing fail-closed (NEVER the 3.11 runtime, which cannot address "
        "AF_HYPERV)."
    )


# ---------------------------------------------------------------------------
# Pipe framing helpers (the invoker side of the bridge contract)
# ---------------------------------------------------------------------------


def _frame_list_bytes(frames: list[bytes]) -> bytes:
    """Encode frames as length-prefixed bytes + a 0-length terminator."""
    parts: list[bytes] = []
    for frame in frames:
        parts.append(struct.pack(_LEN_FORMAT, len(frame)))
        parts.append(frame)
    parts.append(struct.pack(_LEN_FORMAT, 0))
    return b"".join(parts)


def _decode_frame_list(blob: bytes) -> list[bytes]:
    """Decode length-prefixed frames (terminated by a 0 length) from *blob*."""
    frames: list[bytes] = []
    offset = 0
    while offset + _LEN_SIZE <= len(blob):
        (length,) = struct.unpack_from(_LEN_FORMAT, blob, offset)
        offset += _LEN_SIZE
        if length == 0:
            break
        if offset + length > len(blob):
            raise ValueError("truncated response frame from bridge")
        frames.append(blob[offset : offset + length])
        offset += length
    return frames


def _split_status_and_frames(stdout: bytes) -> tuple[dict, list[bytes]]:
    """Split the bridge's stdout into the JSON status line + trailing frames."""
    newline = stdout.find(b"\n")
    if newline < 0:
        raise ValueError("bridge stdout has no status line")
    status = json.loads(stdout[:newline].decode("utf-8"))
    if not isinstance(status, dict):
        raise ValueError("bridge status is not a JSON object")
    remainder = stdout[newline + 1 :]
    frames = _decode_frame_list(remainder)
    return status, frames


# ---------------------------------------------------------------------------
# The 3.11-side bridge invoker (mirror of launcher.guest_parser_invoker)
# ---------------------------------------------------------------------------


class GuestOracleBridge:
    """Spawns the 3.14 helper per op; maps results to the transport's needs.

    One instance is built by :func:`make_guest_oracle_transport` when the
    running interpreter needs the bridge.  Each call spawns a fresh subprocess
    (one guest run per JOB — no daemon).  Construction resolves the
    interpreter ONCE (fail-closed if none qualifies) so a missing bridge is
    caught at wiring time, not at first use.
    """

    def __init__(
        self,
        *,
        bridge_python: str = "",
        mtls_cert: str = "",
        mtls_key: str = "",
        mtls_ca: str = "",
        bridge_module: str = "shared.fleet.guest_oracle_bridge",
        repo_root: Path | None = None,
        _command: list[str] | None = None,
    ) -> None:
        # ``_command`` is a test seam (a fake bridge executable); production
        # resolves via discovery.
        self._command = (
            list(_command)
            if _command is not None
            else discover_bridge_command(bridge_python)
        )
        self._bridge_module = bridge_module
        self._mtls_cert = mtls_cert
        self._mtls_key = mtls_key
        self._mtls_ca = mtls_ca
        self._repo_root = (
            repo_root if repo_root is not None else Path(__file__).resolve().parents[2]
        )

    @property
    def command(self) -> list[str]:
        """The resolved bridge interpreter command (read-only)."""
        return list(self._command)

    def _job(self, op: str, endpoint: OracleEndpoint) -> dict:
        return {
            "op": op,
            "vm_id": endpoint.vm_id,
            "service_guid": endpoint.service_guid,
            "vsock_port": endpoint.vsock_port,
            "timeout_s": endpoint.timeout_s,
            "mtls_cert": self._mtls_cert,
            "mtls_key": self._mtls_key,
            "mtls_ca": self._mtls_ca,
        }

    def _run(
        self, op: str, endpoint: OracleEndpoint, request_frames: list[bytes]
    ) -> tuple[dict, list[bytes]] | None:
        """Spawn the bridge for one op; return (status, frames) or None on failure.

        Timeout-bounded by ``endpoint.timeout_s`` plus a small spawn margin.  A
        crash, timeout, non-JSON status, or non-zero exit with no parseable
        status all map to None (fail-closed at the call site).
        """
        job_line = (json.dumps(self._job(op, endpoint)) + "\n").encode("utf-8")
        stdin_payload = job_line
        if op == "oracle":
            stdin_payload += _frame_list_bytes(request_frames)

        # The bridge runs as `-m shared.fleet.guest_oracle_bridge`, so it needs
        # the repo root on its import path (PYTHONPATH) — it imports shared.ipc.*.
        env = dict(os.environ)
        existing = env.get("PYTHONPATH", "")
        repo = str(self._repo_root)
        env["PYTHONPATH"] = repo + (os.pathsep + existing if existing else "")

        # Spawn margin over the op's own budget: connect + interpreter start.
        timeout_s = float(endpoint.timeout_s) + 15.0
        try:
            proc = subprocess.run(  # noqa: S603 — vector argv, no shell
                [*self._command, "-m", self._bridge_module],
                input=stdin_payload,
                capture_output=True,
                timeout=timeout_s,
                check=False,
                env=env,
                cwd=repo,
            )
        except subprocess.TimeoutExpired:
            logger.error("guest-oracle bridge timed out (op=%s) — fail-closed", op)
            return None
        except (OSError, subprocess.SubprocessError) as exc:
            logger.error(
                "guest-oracle bridge spawn failed (op=%s): %s — fail-closed",
                op,
                type(exc).__name__,
            )
            return None

        if proc.stderr:
            # Structural labels only (the bridge never logs snapshot bytes);
            # surface at debug so a failing bridge is diagnosable without leaking.
            logger.debug(
                "guest-oracle bridge stderr (op=%s): %s",
                op,
                proc.stderr.decode("utf-8", errors="replace").strip()[:500],
            )
        try:
            status, frames = _split_status_and_frames(proc.stdout)
        except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            logger.error(
                "guest-oracle bridge produced unparseable output (op=%s): %s "
                "(exit=%s) — fail-closed",
                op,
                type(exc).__name__,
                proc.returncode,
            )
            return None
        return status, frames

    # ── ops ───────────────────────────────────────────────────────────────

    def reachable(self, endpoint: OracleEndpoint) -> bool:
        """Transport reachability via the bridge (open + close AF_HYPERV)."""
        result = self._run("reachable", endpoint, [])
        if result is None:
            return False
        status, _frames = result
        return bool(status.get("ok"))

    def oracle(
        self, endpoint: OracleEndpoint, request_frames: list[bytes]
    ) -> list[bytes] | None:
        """Full oracle round-trip: returns the response frames, or None on failure."""
        result = self._run("oracle", endpoint, request_frames)
        if result is None:
            return None
        status, frames = result
        if not status.get("ok"):
            return None
        return frames


# ---------------------------------------------------------------------------
# Round-trip (routing mirror of launcher.guest_parser_health.parse_round_trip)
# ---------------------------------------------------------------------------


def _assemble_response(frames: list[bytes]) -> OracleExecResponse | None:
    """Assemble ORACLE_EXEC_RESPONSE frames into a typed view (fail-closed).

    Any channel/framing violation, truncation, or malformed body → None —
    never a fabricated verdict.
    """
    assembler = OracleChunkAssembler(MessageType.ORACLE_EXEC_RESPONSE)
    try:
        for frame in frames:
            assembler.feed(frame)
        if not assembler.complete:
            return None
        return decode_oracle_response(assembler)
    except (OracleChannelError, ValueError):
        return None


def _in_process_round_trip(
    endpoint: OracleEndpoint,
    request_frames: list[bytes],
    *,
    mtls_cert: str = "",
    mtls_key: str = "",
    mtls_ca: str = "",
    _transport_factory: "Callable[[], object] | None" = None,
) -> OracleExecResponse | None:
    """Do the oracle round-trip in-process over AF_HYPERV (3.12+ interpreter).

    Returns the decoded response, or None on any failure (fail-closed).
    ``_transport_factory`` is a TEST SEAM: a zero-arg callable returning a
    connect/send/receive/close transport double, so the full encode→wire→decode
    chain is lockable offline without AF_HYPERV (no VM, no live connection).
    """
    if _transport_factory is not None:
        transport = _transport_factory()
    else:
        if not hasattr(socket, "AF_HYPERV"):
            return None
        from shared.ipc.vsock import VsockAddress, VsockConfig, VsockTransport

        address = VsockAddress(
            cid=0,
            port=endpoint.vsock_port,
            vm_id=endpoint.vm_id,
            service_guid=endpoint.service_guid,
        )
        has_mtls = bool(mtls_cert and mtls_ca)
        config = VsockConfig(
            address=address,
            mtls_cert_path=mtls_cert,
            mtls_key_path=mtls_key,
            ca_cert_path=mtls_ca,
            timeout_ms=max(1, int(endpoint.timeout_s * 1000)),
            # No mTLS material → explicit plaintext-AF_HYPERV bring-up (#655
            # posture, mirrored): dev_mode=False + host_mode=False keeps the
            # round-trip on the AF_HYPERV guest boundary; mTLS is honored when
            # certs are given.
            allow_plaintext_hyperv=not has_mtls,
        )
        transport = VsockTransport(config, dev_mode=False, host_mode=False)
    if not transport.connect():
        return None
    try:
        for frame in request_frames:
            if not transport.send(frame):
                return None
        assembler = OracleChunkAssembler(MessageType.ORACLE_EXEC_RESPONSE)
        while True:
            frame = transport.receive()
            if frame is None:
                return None
            try:
                complete = assembler.feed(frame)
            except (OracleChannelError, ValueError):
                return None
            if complete:
                break
        try:
            return decode_oracle_response(assembler)
        except (OracleChannelError, ValueError):
            return None
    finally:
        transport.close()


def oracle_round_trip(
    endpoint: OracleEndpoint,
    request_frames: list[bytes],
    *,
    bridge: GuestOracleBridge | None = None,
    mtls_cert: str = "",
    mtls_key: str = "",
    mtls_ca: str = "",
    _transport_factory: "Callable[[], object] | None" = None,
) -> OracleExecResponse | None:
    """Run a prepared oracle request through the guest; decode the response.

    Identical transport routing to the #655 ``parse_round_trip``: through the
    given :class:`GuestOracleBridge` on the 3.11 runtime, in-process AF_HYPERV
    on 3.12+ (or the ``_transport_factory`` test seam).  Never raises; any
    failure (unreachable, garbled, channel violation, bridge crash) → None
    (fail-closed — the caller maps it to an honest ``not-run``).
    """
    if bridge is not None:
        try:
            frames = bridge.oracle(endpoint, request_frames)
        except Exception as exc:  # noqa: BLE001 — fail-closed, never raise
            logger.error(
                "guest-oracle bridge raised (%s) — fail-closed",
                type(exc).__name__,
            )
            return None
        if frames is None:
            return None
        return _assemble_response(frames)

    # No bridge → in-process AF_HYPERV (3.12+) or the test seam.  On a 3.11
    # interpreter with no bridge there is no path to the guest at all → None.
    try:
        return _in_process_round_trip(
            endpoint,
            request_frames,
            mtls_cert=mtls_cert,
            mtls_key=mtls_key,
            mtls_ca=mtls_ca,
            _transport_factory=_transport_factory,
        )
    except Exception as exc:  # noqa: BLE001 — fail-closed, never raise
        logger.error(
            "guest-oracle in-process round-trip raised (%s) — fail-closed",
            type(exc).__name__,
        )
        return None


# ---------------------------------------------------------------------------
# The factory — BUILT-NOT-REGISTERED (the structural dormancy contract)
# ---------------------------------------------------------------------------


def _not_run(reason: str, evidence: str) -> dict:
    return {"status": "not-run", "reason": reason, "evidence": evidence[:2000]}


def make_guest_oracle_transport(
    *,
    vm_id: str = "",
    vsock_port: int = ORACLE_VSOCK_PORT_DEFAULT,
    service_guid: str = "",
    timeout_s: float = ORACLE_TRANSPORT_TIMEOUT_S_DEFAULT,
    bridge_python: str = "",
    mtls_cert: str = "",
    mtls_key: str = "",
    mtls_ca: str = "",
    _round_trip: "Callable[[OracleEndpoint, list[bytes]], OracleExecResponse | None] | None" = None,
) -> Callable[[bytes, str], dict]:
    """Build the guest-oracle ``transport`` callable for ``run_guest_oracle``.

    NO production code calls this — the factory ships built-not-registered
    (#744 structural dormancy; the #655 url_adjudicator precedent).  Wiring it
    into ``real_run_guest_oracle`` is the LA's supervised go-live ceremony.

    Wiring-time validation is LOUD (raises); the returned callable NEVER
    raises — every failure is an honest ``{"status": "not-run", ...}``.

    Args:
        vm_id: the Hyper-V VM id ('' ⇒ ``ORCHESTRATOR_VM_ID``).
        vsock_port: the guest oracle service's AF_VSOCK port (#744: 50001).
        service_guid: explicit hv_sock service GUID ('' ⇒ derived from the
            port via the hv_sock template).
        timeout_s: round-trip budget (covers the guest's bounded pytest run).
        bridge_python: explicit 3.12+ interpreter for the version bridge
            ('' ⇒ auto-discover; never the 3.11 runtime).
        mtls_cert / mtls_key / mtls_ca: dormant mTLS plumbing — all empty ⇒
            plaintext-AF_HYPERV bring-up (the #655 posture); populated ⇒ mTLS
            with no code change.
        _round_trip: TEST SEAM — replaces the whole wire round-trip.

    Raises:
        GuestOracleTransportError: bad port, or an explicit *service_guid*
            that does not match the hv_sock template for *vsock_port* (the
            silent-divergence class the #615 work taught us to lock).
        BridgeUnavailableError: the runtime needs the version bridge and no
            qualifying 3.12+ interpreter exists (caught at wiring time).
    """
    if not (0 < int(vsock_port) <= 0xFFFFFFFF):
        raise GuestOracleTransportError(
            "GO_CONFIG_PORT_INVALID", f"vsock_port out of range: {vsock_port}"
        )
    expected_guid = hv_service_guid_for_port(int(vsock_port))
    resolved_guid = (service_guid or expected_guid).strip().lower()
    if resolved_guid != expected_guid:
        raise GuestOracleTransportError(
            "GO_CONFIG_GUID_MISMATCH",
            f"service_guid {service_guid!r} does not match the hv_sock "
            f"template for port {vsock_port} ({expected_guid!r}); refusing "
            "fail-closed so addressing can never silently diverge.",
        )
    if float(timeout_s) <= 0:
        raise GuestOracleTransportError(
            "GO_CONFIG_TIMEOUT_INVALID", "timeout_s must be positive"
        )

    endpoint = OracleEndpoint(
        vm_id=(vm_id or ORCHESTRATOR_VM_ID),
        service_guid=resolved_guid,
        vsock_port=int(vsock_port),
        timeout_s=float(timeout_s),
    )

    if _round_trip is not None:
        round_trip = _round_trip
    else:
        # Resolve the version bridge NOW (fail-closed at wiring time, the
        # invoker-precedent posture) when the runtime cannot open AF_HYPERV
        # itself; a 3.12+ runtime goes in-process with no subprocess at all.
        bridge = (
            GuestOracleBridge(
                bridge_python=bridge_python,
                mtls_cert=mtls_cert,
                mtls_key=mtls_key,
                mtls_ca=mtls_ca,
            )
            if bridge_required()
            else None
        )

        def round_trip(
            ep: OracleEndpoint, frames: list[bytes]
        ) -> OracleExecResponse | None:
            return oracle_round_trip(
                ep,
                frames,
                bridge=bridge,
                mtls_cert=mtls_cert,
                mtls_key=mtls_key,
                mtls_ca=mtls_ca,
            )

    def transport(snapshot_zip: bytes, oracle_rel_path: str) -> dict:
        """Ship the snapshot to the guest; return the closed result shape.

        The exact ``transport`` signature ``run_guest_oracle`` accepts.
        NEVER raises (the pipeline guards again regardless — belt and braces).
        """
        try:
            request_id = uuid.uuid4().hex
            try:
                request_frames = encode_oracle_request(
                    request_id=request_id,
                    snapshot_zip=snapshot_zip,
                    oracle_path=oracle_rel_path,
                )
            except (OracleChannelError, ValueError) as exc:
                # A hostile/oversize/malformed request is UNSENDABLE — refused
                # at encode, before any I/O (the corridor's own contract).
                return _not_run(
                    REASON_REQUEST_UNSENDABLE,
                    f"request refused at encode: {type(exc).__name__}",
                )
            response = round_trip(endpoint, request_frames)
            if response is None:
                return _not_run(
                    REASON_GUEST_UNREACHABLE,
                    "guest oracle round-trip failed (unreachable guest, "
                    "garbled response, or bridge failure) — isolation "
                    "certificate withheld, fail-closed",
                )
            if response.request_id != request_id:
                # Cross-talk / stale answer: never attribute a verdict that
                # does not correlate to THIS request.
                return _not_run(
                    REASON_GUEST_ERROR,
                    "response correlation mismatch (request_id echo differs)",
                )
            return {
                "status": response.status,
                "reason": response.reason,
                "evidence": response.evidence,
            }
        except BaseException as exc:  # noqa: BLE001 — never raise into the pipeline
            return _not_run(
                REASON_GUEST_ERROR,
                f"guest oracle transport error: {type(exc).__name__}",
            )

    return transport
