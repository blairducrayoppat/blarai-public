"""
Guest-Oracle AF_HYPERV Version Bridge — the 3.14 subprocess helper (#744)
=========================================================================
The BlarAI runtime venv is pinned to Python **3.11.9** (OpenVINO GenAI + the
14B weights are validated against it).  ``socket.AF_HYPERV`` — the address
family the Windows host needs to open an hv_sock to the NIC-less Hyper-V guest
— first appeared in CPython **3.12**.  So the 3.11 swap driver cannot, in its
own interpreter, reach the guest oracle service at all.

This module is the guest-oracle mirror of the PROVEN #655 parser bridge
(:mod:`launcher.guest_parser_bridge` — same contract, same framing, same
fail-closed posture) speaking the ORACLE_EXEC corridor instead of the parse
channel.  It RUNS UNDER PYTHON 3.14 as a short-lived subprocess: the 3.11
invoker (:mod:`shared.fleet.guest_oracle_transport`) spawns it per operation
(ONE guest-oracle run per dispatched JOB — the lowest-frequency corridor in
the system; a daemon would be over-engineering), hands it a job on stdin, and
reads the result on stdout.  The version jump is isolated to one
out-of-process hop; the runtime venv is never touched.

It lives in ``shared/fleet/`` (not ``launcher/``) because the swap driver is
the caller and ``shared`` must not import ``launcher`` (layering); the code
MIRRORS the launcher bridge rather than importing it.

STRUCTURAL DORMANCY (#744): NOTHING in production spawns this helper — the
only caller is the built-not-registered transport factory in
:mod:`shared.fleet.guest_oracle_transport`, which no production code path
constructs.  Wiring it live is the LA's supervised go-live ceremony.

RUNS UNDER 3.14 — IMPORT DISCIPLINE (load-bearing)
==================================================
Because this file executes under a *different* interpreter than the swap
driver, it imports ONLY:
  * the standard library (``argparse``/``json``/``socket``/``struct``/``sys``
    — all present + identical-enough across 3.11→3.14), and
  * the PURE-PYTHON, 3.14-safe shared IPC modules it needs to do the real
    I/O: :mod:`shared.ipc.vsock` (the AF_HYPERV transport) and
    :mod:`shared.ipc.oracle_channel` (the chunked ORACLE_EXEC framing) —
    which in turn pull only :mod:`shared.ipc.protocol` (stdlib-only).

It MUST NOT import anything from ``launcher`` or the heavy fleet modules and
MUST NOT import any network client (``httpx``/``requests``/``urllib.request``/
``http.client``) — the air-gap egress import-scan covers ``shared/``, and the
only socket this helper ever opens is the AF_HYPERV vsock to the guest (a
LOCAL VM boundary, not external network).

THE BRIDGE CONTRACT (cross-interpreter — the 3.11 invoker speaks the other side)
================================================================================
Invocation::

    <py3.14> -m shared.fleet.guest_oracle_bridge

stdin (ONE line of UTF-8 JSON, then raw bytes for the oracle op):

    {"op": "reachable"|"oracle",
     "vm_id": <guid str>, "service_guid": <guid str>,
     "vsock_port": <int>, "timeout_s": <float>,
     "mtls_cert": <str>, "mtls_key": <str>, "mtls_ca": <str>}

  * ``op = "reachable"``: open the AF_HYPERV socket, prove the guest listener
    accepts, close.  No request frames consumed.  (Transport-level only.)
  * ``op = "oracle"``: after the JSON line, stdin carries the
    ORACLE_EXEC_REQUEST as length-prefixed frames (4-byte big-endian length +
    frame bytes, repeated; a 4-byte length of 0 terminates the list).  The
    helper sends each frame over the transport, then reads the chunked
    ORACLE_EXEC_RESPONSE back and validates it decodes before shipping it.

stdout:

  * Line 1: ONE line of UTF-8 JSON status::

        {"ok": <bool>, "code": <str>, "op": <str>,
         "frames": <int>,          # response frames that follow (oracle only)
         "message": <str>}         # structural label only, never snapshot bytes

  * For ``op = "oracle"`` with ``ok = true``: after the status line, the
    response frames as length-prefixed bytes (same 4-byte-length framing),
    terminated by a 4-byte 0 length.

Exit code: 0 on ``ok = true``, non-zero on any failure.  A crashed / garbled /
timed-out bridge is mapped by the 3.11 invoker to a fail-closed None — the
pipeline then reports an honest ``not-run``, NEVER an implied pass.

mTLS posture (mirror of the #655 precedent): plaintext-AF_HYPERV bring-up by
default (``allow_plaintext_hyperv`` iff no cert material — a LOCAL VM
boundary), dormant mTLS plumbing threaded through — populating the cert paths
in the job activates mTLS with no code change; partial material is rejected by
the transport's own validation, never silently downgraded.

Security:
  - No external network calls.  The only socket opened is AF_HYPERV to the guest.
  - Fail-closed: every error path → ``ok = false`` + non-zero exit; nothing is
    coerced into a plausible-looking success.
  - Logs (stderr) carry structural labels only — never snapshot source bytes.
"""

from __future__ import annotations

import argparse
import json
import socket
import struct
import sys
from typing import Any

from shared.ipc.oracle_channel import (
    OracleChannelError,
    OracleChunkAssembler,
    decode_oracle_response,
)
from shared.ipc.protocol import MessageType
from shared.ipc.vsock import VsockAddress, VsockConfig, VsockTransport

# Structural status codes the bridge emits (labels only — the 3.11 invoker maps
# them; never rename without updating shared.fleet.guest_oracle_transport).
BRIDGE_OK: str = "OK"
BRIDGE_BAD_JOB: str = "BRIDGE_BAD_JOB"
BRIDGE_NO_AF_HYPERV: str = "BRIDGE_NO_AF_HYPERV"
BRIDGE_CONNECT_FAILED: str = "BRIDGE_CONNECT_FAILED"
BRIDGE_SEND_FAILED: str = "BRIDGE_SEND_FAILED"
BRIDGE_RECV_FAILED: str = "BRIDGE_RECV_FAILED"
BRIDGE_BAD_RESPONSE: str = "BRIDGE_BAD_RESPONSE"
BRIDGE_INTERNAL: str = "BRIDGE_INTERNAL"

_VALID_OPS: frozenset[str] = frozenset({"reachable", "oracle"})

# Frame length-prefix header (matches the launcher bridge — 4-byte big-endian;
# a 0 length ends the list).  This is the STDIN/STDOUT pipe framing only —
# distinct from, but shaped like, the on-socket vsock framing.
_LEN_FORMAT = "!I"
_LEN_SIZE = struct.calcsize(_LEN_FORMAT)

# Defensive bound on a single pipe frame (an over-cap frame would be unsendable
# over the 64 KB transport anyway; this stops a garbled length from forcing a
# huge read on the bridge's own stdin).  Generous headroom over the 64 KB cap.
_MAX_PIPE_FRAME_BYTES: int = 1 << 20


def _read_exact(stream: Any, num_bytes: int) -> bytes | None:
    """Read exactly *num_bytes* from a binary stream, or None at clean EOF."""
    buf = bytearray()
    while len(buf) < num_bytes:
        chunk = stream.read(num_bytes - len(buf))
        if not chunk:
            return None
        buf.extend(chunk)
    return bytes(buf)


def _read_frames(stream: Any) -> list[bytes]:
    """Read length-prefixed frames until a 0-length terminator.

    Raises:
        ValueError: truncated stream, or a declared frame length over the cap.
    """
    frames: list[bytes] = []
    while True:
        header = _read_exact(stream, _LEN_SIZE)
        if header is None:
            raise ValueError("truncated frame list on stdin (no terminator)")
        (length,) = struct.unpack(_LEN_FORMAT, header)
        if length == 0:
            return frames
        if length > _MAX_PIPE_FRAME_BYTES:
            raise ValueError(f"pipe frame length {length} over cap")
        frame = _read_exact(stream, length)
        if frame is None:
            raise ValueError("truncated frame body on stdin")
        frames.append(frame)


def _write_frames(stream: Any, frames: list[bytes]) -> None:
    """Write length-prefixed frames + a 0-length terminator."""
    for frame in frames:
        stream.write(struct.pack(_LEN_FORMAT, len(frame)))
        stream.write(frame)
    stream.write(struct.pack(_LEN_FORMAT, 0))


def _emit_status(
    *, ok: bool, code: str, op: str, frames: int = 0, message: str = ""
) -> None:
    """Write the single JSON status line to stdout (text), then flush."""
    line = json.dumps(
        {"ok": ok, "code": code, "op": op, "frames": frames, "message": message},
        separators=(",", ":"),
    )
    sys.stdout.write(line + "\n")
    sys.stdout.flush()


def _build_transport(job: dict[str, Any]) -> VsockTransport:
    """Construct the AF_HYPERV transport for *job* (mTLS when material given).

    dev_mode is False (this is a real guest boundary); host_mode is False so the
    transport takes the AF_HYPERV path.  mTLS is enabled iff cert+ca are present;
    otherwise the EXPLICIT ``allow_plaintext_hyperv`` opt-in (#655) selects the
    plaintext-AF_HYPERV bring-up path.  The bridge mirrors the invoker's posture
    — it does not decide it: the factory chooses whether to pass certs.
    """
    has_mtls = bool(job.get("mtls_cert") and job.get("mtls_ca"))
    address = VsockAddress(
        cid=0,
        port=int(job["vsock_port"]),
        vm_id=str(job["vm_id"]),
        service_guid=str(job["service_guid"]),
    )
    config = VsockConfig(
        address=address,
        mtls_cert_path=str(job.get("mtls_cert", "")),
        mtls_key_path=str(job.get("mtls_key", "")),
        ca_cert_path=str(job.get("mtls_ca", "")),
        timeout_ms=max(1, int(float(job["timeout_s"]) * 1000)),
        # No mTLS material → the explicit plaintext-AF_HYPERV bring-up path
        # (#655) so the base VsockTransport does not refuse the bare connection.
        allow_plaintext_hyperv=not has_mtls,
    )
    return VsockTransport(config, dev_mode=False, host_mode=False)


def _op_reachable(transport: VsockTransport) -> tuple[bool, str, str]:
    """Open + immediately close the AF_HYPERV socket — transport reachability."""
    if not transport.connect():
        return False, BRIDGE_CONNECT_FAILED, "guest listener did not accept"
    transport.close()
    return True, BRIDGE_OK, ""


def _round_trip(
    transport: VsockTransport, request_frames: list[bytes]
) -> tuple[bool, str, str, list[bytes]]:
    """Send the oracle request frames; read the chunked response.  Fail-closed."""
    if not transport.connect():
        return False, BRIDGE_CONNECT_FAILED, "guest listener did not accept", []
    try:
        for frame in request_frames:
            if not transport.send(frame):
                return False, BRIDGE_SEND_FAILED, "send failed mid-request", []
        assembler = OracleChunkAssembler(MessageType.ORACLE_EXEC_RESPONSE)
        response_frames: list[bytes] = []
        while True:
            frame = transport.receive()
            if frame is None:
                return (
                    False,
                    BRIDGE_RECV_FAILED,
                    "connection closed mid-response",
                    [],
                )
            response_frames.append(frame)
            try:
                complete = assembler.feed(frame)
            except (OracleChannelError, ValueError) as exc:
                return (
                    False,
                    BRIDGE_BAD_RESPONSE,
                    f"response framing rejected: {type(exc).__name__}",
                    [],
                )
            if complete:
                break
        # Validate the assembled response decodes (closed status vocabulary,
        # not-run-requires-reason) BEFORE shipping frames back — a garbled
        # guest answer dies here, never coerced into a plausible verdict.
        try:
            decode_oracle_response(assembler)
        except (OracleChannelError, ValueError) as exc:
            return (
                False,
                BRIDGE_BAD_RESPONSE,
                f"response did not decode: {type(exc).__name__}",
                [],
            )
        return True, BRIDGE_OK, "", response_frames
    finally:
        transport.close()


def run(argv: list[str] | None = None) -> int:
    """Entry point: read the job, do the op, emit status (+ frames).  Fail-closed."""
    parser = argparse.ArgumentParser(
        prog="python -m shared.fleet.guest_oracle_bridge",
        description=(
            "AF_HYPERV version bridge for the #744 guest-oracle corridor — "
            "runs under Python 3.14 so the 3.11 swap driver can reach the "
            "guest oracle service; reads a job on stdin, opens the guest "
            "vsock, writes the result to stdout."
        ),
    )
    parser.parse_args(argv)

    if not hasattr(socket, "AF_HYPERV"):
        # This helper is supposed to run under a 3.12+ interpreter; if it does
        # not, say so loudly rather than pretend (the invoker pre-checks, but a
        # mis-discovered interpreter must still fail closed here).
        _emit_status(
            ok=False,
            code=BRIDGE_NO_AF_HYPERV,
            op="?",
            message=f"interpreter {sys.version.split()[0]} lacks socket.AF_HYPERV",
        )
        return 3

    try:
        raw_job = sys.stdin.buffer.readline()
        if not raw_job:
            _emit_status(ok=False, code=BRIDGE_BAD_JOB, op="?", message="empty stdin")
            return 2
        job = json.loads(raw_job.decode("utf-8"))
        if not isinstance(job, dict):
            raise ValueError("job is not a JSON object")
        op = job.get("op")
        if op not in _VALID_OPS:
            raise ValueError(f"unknown op {op!r}")
        for key in ("vm_id", "service_guid", "vsock_port", "timeout_s"):
            if key not in job:
                raise ValueError(f"job missing required key {key!r}")
    except (ValueError, UnicodeDecodeError) as exc:
        _emit_status(
            ok=False,
            code=BRIDGE_BAD_JOB,
            op="?",
            message=f"bad job: {type(exc).__name__}",
        )
        return 2

    try:
        transport = _build_transport(job)
    except (KeyError, ValueError, TypeError) as exc:
        _emit_status(
            ok=False,
            code=BRIDGE_BAD_JOB,
            op=str(op),
            message=f"bad endpoint: {type(exc).__name__}",
        )
        return 2

    try:
        if op == "reachable":
            ok, code, message = _op_reachable(transport)
            _emit_status(ok=ok, code=code, op=op, message=message)
            return 0 if ok else 1

        # op == "oracle" — read the request frames that follow the job line.
        try:
            request_frames = _read_frames(sys.stdin.buffer)
        except ValueError as exc:
            _emit_status(
                ok=False,
                code=BRIDGE_BAD_JOB,
                op=op,
                message=f"bad request frames: {type(exc).__name__}",
            )
            return 2
        if not request_frames:
            _emit_status(
                ok=False, code=BRIDGE_BAD_JOB, op=op, message="no request frames"
            )
            return 2

        ok, code, message, response_frames = _round_trip(transport, request_frames)
        _emit_status(
            ok=ok, code=code, op=op, frames=len(response_frames), message=message
        )
        if ok:
            _write_frames(sys.stdout.buffer, response_frames)
            sys.stdout.buffer.flush()
        return 0 if ok else 1
    except Exception as exc:  # noqa: BLE001 — fail-closed: never crash silently
        print(f"bridge internal error: {type(exc).__name__}", file=sys.stderr)
        _emit_status(
            ok=False, code=BRIDGE_INTERNAL, op=str(op), message=type(exc).__name__
        )
        return 4


if __name__ == "__main__":
    sys.exit(run())
