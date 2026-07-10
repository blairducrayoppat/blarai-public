"""
Guest Oracle Service — VM-homed job-oracle execution (#744, the go-live ceremony)
=================================================================================
The long-running guest-resident listener that completes the guest-certified
oracle corridor: a fleet job's SNAPSHOT (deterministic zip of the coder-built
tree + the spec-blind job oracle) is re-run with ``python -m pytest`` INSIDE
the NIC-less Hyper-V guest — an isolation certificate the host result cannot
forge — and the closed ``{status, reason, evidence}`` verdict rides back over
AF_HYPERV vsock.  Mirrors the PROVEN UC-003 guest parser service
(``services/cleaner/guest/parser_service.py``) structurally: same fail-closed
connection rules, same mTLS-or-explicit-plaintext startup gate, same
sequential single-connection listener.

Flow per request (the ``shared/ipc/oracle_channel.py`` wire contract):

  host transport (the #744 host-side factory, via the 3.14 bridge)
      ──ORACLE_EXEC_REQUEST chunks──▶ this service
      snapshot zip bytes + oracle_rel_path
  this service: ``guest_oracle.execute_snapshot`` — pinned-path check,
      zip-slip/bomb-guarded extract into a temp dir, ``python -m pytest``
      with a hard timeout, honest ``not-run`` on every machinery failure
  this service ──ORACLE_EXEC_RESPONSE chunks──▶ host transport
      status ∈ {passed, failed, not-run} + reason + evidence

FAIL-CLOSED rules (the parser service's, inherited verbatim):
  * Channel violation: one addressable ``not-run`` response if a request_id
    is already known, then the connection is DROPPED (no resync).
  * Truncation: connection dropped, no response.
  * Oracle machinery failure: an honest ``not-run`` WITH its reason — never
    a fabricated verdict (``execute_snapshot`` already guarantees this).
  * Internal error: a ``not-run`` carrying the exception CLASS name only
    (labels, never snapshot content), then the next request is served.
  * Listener invariant: an unexpected per-connection failure costs that
    connection ONLY; the accept loop continues.

PORT: **50002** — the guest PARSER owns 50001; the two services are separate
OpenRC units with separate listeners (coupling their go-live ceremonies was
rejected at the transport build, #744 c.1445).  The host-side factory takes
the port as a parameter (``vsock_port=50002`` at the registration site),
exactly the no-code-change re-point the ceremony was designed for.

PORTABILITY (Alpine 3.21 / Python 3.12): stdlib only at module level plus
``shared.ipc`` (oracle_channel → protocol, both stdlib-pure) and
``shared.fleet.guest_oracle`` (stdlib + shared.ipc; #744 guest-portability
note there).  POSIX-clean; the ``__main__`` binds a Linux ``AF_VSOCK``
listener — the Windows host addresses it as hv_sock service GUID
``0000c352-facb-11e6-bd58-64006a7986d3`` (port 50002 = 0xC352).
"""

from __future__ import annotations

import argparse
import logging
import os
import socket
import ssl
import sys
from typing import Protocol

from shared.fleet.guest_oracle import execute_snapshot
from shared.ipc.oracle_channel import (
    OracleChannelError,
    OracleChunkAssembler,
    decode_oracle_request,
    encode_oracle_response,
)
from shared.ipc.protocol import MessageFramer, MessageType

logger = logging.getLogger(__name__)

#: Machine reasons this service adds on transport-layer failures (labels only;
#: they ride the closed ``not-run`` status, which REQUIRES a reason).
REASON_CHANNEL_VIOLATION: str = "oracle-channel-violation"
REASON_SERVICE_INTERNAL: str = "oracle-service-internal-error"
REASON_RESPONSE_TOO_LARGE: str = "oracle-response-too-large"

#: Default accept/read timeout for the guest listener (seconds).
DEFAULT_TIMEOUT_S: float = 30.0

#: The oracle service port — 50002 (0xC352).  The parser owns 50001; a
#: host-side lock pins the two apart AND pins this value equal to what the
#: go-live registration passes to the host-side factory.
DEFAULT_ORACLE_PORT: int = 50002

#: Guest-side pytest bound, threaded to ``execute_snapshot`` (which defaults
#: to the same value — redeclared for the argparse surface; the registry row
#: 'Guest oracle pytest run' governs the number).
DEFAULT_EXEC_TIMEOUT_S: float = 600.0


class OracleTransport(Protocol):
    """The transport surface this service consumes (``VsockTransport`` shape
    or a test double): length-framed, fail-closed receive/send."""

    def receive(self) -> bytes | None:  # pragma: no cover - protocol stub
        ...

    def send(self, data: bytes) -> bool:  # pragma: no cover - protocol stub
        ...


class GuestOracleService:
    """Stateless request handler + connection loop for the oracle channel."""

    def __init__(
        self,
        *,
        framer: MessageFramer | None = None,
        exec_timeout_s: float = DEFAULT_EXEC_TIMEOUT_S,
        _execute=None,
    ) -> None:
        self._framer = framer or MessageFramer()
        self._exec_timeout_s = float(exec_timeout_s)
        # Test seam: replaces execute_snapshot so connection-loop locks run
        # without a real pytest subprocess.  Production leaves it None.
        self._execute = _execute

    # ------------------------------------------------------------------
    # Pure execution logic (transport-free; unit-testable directly)
    # ------------------------------------------------------------------

    def run_oracle(self, snapshot_zip: bytes, oracle_rel_path: str) -> dict:
        """Execute one snapshot.  Total: never raises — ``execute_snapshot``
        maps every machinery failure to an honest ``not-run``."""
        executor = self._execute or execute_snapshot
        try:
            return executor(
                snapshot_zip, oracle_rel_path, timeout_s=self._exec_timeout_s
            )
        except Exception as exc:  # noqa: BLE001 — belt: label-only, never raise
            logger.exception("execute_snapshot raised (should be total)")
            return {
                "status": "not-run",
                "reason": REASON_SERVICE_INTERNAL,
                "evidence": f"executor raised: {type(exc).__name__}",
            }

    # ------------------------------------------------------------------
    # Connection loop (the parser service's, on the oracle channel)
    # ------------------------------------------------------------------

    def serve_connection(self, transport: OracleTransport) -> int:
        """Serve oracle requests on one connection until it closes.

        Returns the number of requests fully served (response sent).
        Fail-closed: any channel violation or truncation drops the
        connection (module docstring).
        """
        served = 0
        while True:
            assembler = OracleChunkAssembler(
                MessageType.ORACLE_EXEC_REQUEST, framer=self._framer
            )
            frame = transport.receive()
            if frame is None:
                return served  # clean close between messages
            while True:
                try:
                    complete = assembler.feed(frame)
                except ValueError as exc:
                    # OracleChannelError subclasses ValueError; the framer's
                    # plain ValueError on a hostile envelope is caught too
                    # (the #655 adversarial-review class, inherited).
                    logger.error("oracle-channel violation: %s", exc)
                    self._send_not_run(
                        transport,
                        assembler.request_id,
                        REASON_CHANNEL_VIOLATION,
                        type(exc).__name__,
                    )
                    return served
                if complete:
                    break
                frame = transport.receive()
                if frame is None:
                    logger.error(
                        "connection closed mid-message (truncated request, "
                        "request_id=%s) — dropping connection",
                        assembler.request_id or "<unknown>",
                    )
                    return served

            if not self._handle_request(transport, assembler):
                return served
            served += 1

    def _handle_request(
        self, transport: OracleTransport, assembler: OracleChunkAssembler
    ) -> bool:
        """Execute one assembled request and send the response.

        Returns False when the connection must be dropped (send failure).
        """
        request_id = assembler.request_id
        try:
            try:
                request = decode_oracle_request(assembler)
            except OracleChannelError as exc:
                logger.error("request decode failed for %s: %s", request_id, exc)
                return self._send_not_run(
                    transport, request_id, REASON_CHANNEL_VIOLATION,
                    type(exc).__name__,
                )
            result = self.run_oracle(request.snapshot_zip, request.oracle_path)
            frames = encode_oracle_response(
                request_id=request.request_id,
                status=str(result.get("status", "not-run")),
                reason=str(result.get("reason", "")),
                evidence=str(result.get("evidence", "")),
                framer=self._framer,
            )
        except OracleChannelError as exc:
            # Encode-side cap (an evidence blob outgrew the response cap):
            # retry with the evidence dropped — the VERDICT must still land.
            logger.error("response encoding failed for %s: %s", request_id, exc)
            try:
                frames = encode_oracle_response(
                    request_id=request_id,
                    status="not-run",
                    reason=REASON_RESPONSE_TOO_LARGE,
                    evidence="",
                    framer=self._framer,
                )
            except ValueError:
                return False
        except Exception as exc:  # noqa: BLE001 — label-only error reply
            logger.exception("internal oracle-service error for %s", request_id)
            return self._send_not_run(
                transport, request_id, REASON_SERVICE_INTERNAL, type(exc).__name__
            )

        for frame in frames:
            if not transport.send(frame):
                logger.error("send failed mid-response (request_id=%s)", request_id)
                return False
        return True

    def _send_not_run(
        self,
        transport: OracleTransport,
        request_id: str,
        reason: str,
        detail: str,
    ) -> bool:
        """Send an honest ``not-run`` if *request_id* is addressable."""
        if not request_id:
            return False  # first frame never yielded a correlation id
        try:
            frames = encode_oracle_response(
                request_id=request_id,
                status="not-run",
                reason=reason,
                evidence=detail[:200],
                framer=self._framer,
            )
        except ValueError:
            # The error response itself failed to encode — fail closed
            # (catch ValueError, not just OracleChannelError: the framer
            # raises the plain base class on a hostile echoed request_id —
            # the #655 adversarial-review defense, inherited).
            return False
        for frame in frames:
            if not transport.send(frame):
                return False
        return True


# ---------------------------------------------------------------------------
# Guest entry point (runs inside the Alpine VM) — the parser service's shape
# ---------------------------------------------------------------------------


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m shared.fleet.guest_oracle_service",
        description=(
            "BlarAI guest oracle service (#744) — AF_VSOCK listener inside "
            "the Alpine guest; re-runs a fleet job's oracle in isolation so "
            "the host verdict gains a guest certificate."
        ),
    )
    parser.add_argument(
        "--transport",
        choices=("vsock", "tcp"),
        default=os.environ.get("BLARAI_ORACLE_TRANSPORT", "vsock"),
        help="vsock = Linux AF_VSOCK guest listener (default); "
        "tcp = 127.0.0.1 loopback for in-guest/dev testing only.",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get("BLARAI_ORACLE_PORT", str(DEFAULT_ORACLE_PORT))),
        help=f"Listener port (default {DEFAULT_ORACLE_PORT} = hv_sock 0xC352; "
        "the parser owns 50001).",
    )
    parser.add_argument(
        "--timeout-s",
        type=float,
        default=float(os.environ.get("BLARAI_ORACLE_TIMEOUT_S", str(DEFAULT_TIMEOUT_S))),
        help="Accept/read timeout in seconds.",
    )
    parser.add_argument(
        "--exec-timeout-s",
        type=float,
        default=float(
            os.environ.get("BLARAI_ORACLE_EXEC_TIMEOUT_S", str(DEFAULT_EXEC_TIMEOUT_S))
        ),
        help="Hard bound on one in-guest pytest run (seconds).",
    )
    parser.add_argument(
        "--cert", default=os.environ.get("BLARAI_ORACLE_CERT", ""),
        help="mTLS server certificate (PEM).",
    )
    parser.add_argument(
        "--key", default=os.environ.get("BLARAI_ORACLE_KEY", ""),
        help="mTLS private key (PEM).",
    )
    parser.add_argument(
        "--ca", default=os.environ.get("BLARAI_ORACLE_CA", ""),
        help="CA certificate for client verification (PEM).",
    )
    parser.add_argument(
        "--allow-plaintext",
        action="store_true",
        help="Explicitly run WITHOUT mTLS (fail-closed default refuses; "
        "plaintext-AF_HYPERV bring-up only, per the #615/#655 precedent).",
    )
    return parser


def _create_listener_socket(transport: str, port: int) -> socket.socket:
    """Bind the guest listener.  AF_VSOCK is Linux-only by design."""
    if transport == "vsock":
        if not hasattr(socket, "AF_VSOCK"):
            raise RuntimeError(
                "socket.AF_VSOCK is unavailable — this entry point runs "
                "inside the Linux guest (Alpine), not on the Windows host."
            )
        sock = socket.socket(socket.AF_VSOCK, socket.SOCK_STREAM)  # type: ignore[attr-defined]
        sock.bind((socket.VMADDR_CID_ANY, port))  # type: ignore[attr-defined]
    else:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("127.0.0.1", port))
    sock.listen(1)  # sequential, one connection at a time (repo IPC design)
    return sock


def _build_ssl_context(cert: str, key: str, ca: str) -> ssl.SSLContext:
    """mTLS server context — refuse-to-start beats a silent plaintext fallback."""
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.verify_mode = ssl.CERT_REQUIRED
    ctx.load_cert_chain(certfile=cert, keyfile=key)
    ctx.load_verify_locations(cafile=ca)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    return ctx


class _SocketTransport:
    """Minimal length-framed transport over an accepted socket — the
    ``VsockTransport`` receive/send contract without its Windows-side config
    machinery (the guest needs exactly this and nothing more)."""

    _LEN_BYTES = 4
    _MAX_FRAME = 65536

    def __init__(self, conn: socket.socket) -> None:
        self._conn = conn

    def _read_exact(self, n: int) -> bytes | None:
        buf = bytearray()
        while len(buf) < n:
            chunk = self._conn.recv(n - len(buf))
            if not chunk:
                return None
            buf.extend(chunk)
        return bytes(buf)

    def receive(self) -> bytes | None:
        header = self._read_exact(self._LEN_BYTES)
        if header is None:
            return None
        length = int.from_bytes(header, "big")
        if not (0 < length <= self._MAX_FRAME):
            return None  # hostile length: drop the connection
        return self._read_exact(length)

    def send(self, data: bytes) -> bool:
        try:
            self._conn.sendall(len(data).to_bytes(self._LEN_BYTES, "big") + data)
            return True
        except OSError:
            return False


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )
    args = _build_arg_parser().parse_args(argv)

    ssl_ctx: ssl.SSLContext | None = None
    if args.cert or args.key or args.ca:
        if not (args.cert and args.key and args.ca):
            logger.error("mTLS requires --cert, --key AND --ca (fail-closed)")
            return 2
        try:
            ssl_ctx = _build_ssl_context(args.cert, args.key, args.ca)
        except (ssl.SSLError, OSError, ValueError) as exc:
            logger.error("mTLS context creation failed (refusing to start): %s", exc)
            return 2
    elif not args.allow_plaintext:
        logger.error(
            "no mTLS material configured and --allow-plaintext not given — "
            "refusing to start (fail-closed default)"
        )
        return 2

    try:
        listener = _create_listener_socket(args.transport, args.port)
    except (OSError, RuntimeError) as exc:
        logger.error("listener bind failed: %s", exc)
        return 1

    service = GuestOracleService(exec_timeout_s=args.exec_timeout_s)
    logger.info(
        "guest oracle service listening (%s port %d, mTLS=%s, exec bound %.0fs)",
        args.transport, args.port, "on" if ssl_ctx else "OFF (explicit plaintext)",
        args.exec_timeout_s,
    )
    while True:
        try:
            conn, _peer = listener.accept()
        except OSError as exc:
            logger.error("accept failed: %s — listener exiting", exc)
            return 1
        try:
            if ssl_ctx is not None:
                conn = ssl_ctx.wrap_socket(conn, server_side=True)
            conn.settimeout(args.timeout_s)
            served = service.serve_connection(_SocketTransport(conn))
            logger.info("connection closed after %d request(s)", served)
        except Exception as exc:  # noqa: BLE001 — one connection only
            logger.error("connection failed: %s (%s)", type(exc).__name__, exc)
        finally:
            try:
                conn.close()
            except OSError:
                pass


if __name__ == "__main__":
    sys.exit(main())
