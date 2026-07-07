"""
Guest Parser Service — VM-homed HTML extraction (UC-003 Stage C, ADR-030 §3)
============================================================================
The long-running guest-resident listener that closes the §4 lxml interim:
hostile fetched web bytes are parsed INSIDE the Hyper-V guest, never in a
host process holding the unsealed DEK and the GPU pipeline (roadmap §6
Decision 3, HYBRID topology).

Flow per request (the ``shared/ipc/parse_channel.py`` wire contract):

  host glue (later task) ──INGEST_PARSE_REQUEST chunks──▶ this service
      raw HTML bytes + source-url metadata
  this service: UTF-8 decode → trafilatura extraction (the canonical knobs,
      ``services/cleaner/src/extraction.extract_document`` — EXTRACTION
      ONLY, never trafilatura's fetch machinery; ADR-030 §4) → pure-Python
      normalization (``normalize_text``) → extraction-quality verdict
      (``judge_extraction``, injection axis = 0)
  this service ──INGEST_PARSE_RESPONSE chunks──▶ host glue
      cleaned text + title/byline/date/word_count/confidence/status/reasons

DIVISION OF LABOR (binding): the guest verdict covers EXTRACTION-QUALITY
axes only.  Injection sanitization (the ADR-013 scan + delimiter strip)
runs HOST-side on the returned text — those primitives live in host service
packages the Alpine guest does not carry, and the host pipeline composes
the final verdict.  ``INJECTION_PATTERN_DETECTED`` therefore never appears
in a guest response; a forged delimiter in the page SURVIVES into the
response text by design and is stripped host-side.

CHARSET: the channel carries bytes; charset negotiation belongs to the host
fetch layer (``guarded_fetch``).  The parser decodes UTF-8 strict first and
falls back to ``errors="replace"`` — a wrongly-declared page yields mojibake
that the conservative quarantine floors catch, instead of a hard failure
the operator cannot review.

FAIL-CLOSED rules:
  * Channel violation (oversize declaration, bad sequence, malformed frame):
    one error response IF a request_id is already known, then the connection
    is DROPPED — no resync on a corrupted stream.
  * Truncation (transport closes mid-message): connection dropped, no
    response (there is no one to answer).
  * Extraction failure on hostile bytes: a quarantined EXTRACTION_FAILED
    response (empty text, confidence 0.0) — a verdict, not a fault.
  * Internal error: an ``error`` response carrying the exception CLASS name
    only (labels, never content), then the next request is served.
  * Oversize response body: a small RESPONSE_TOO_LARGE error response.
  * Listener invariant: an unexpected per-connection failure is logged
    (exception class name only — never content) and costs that connection
    ONLY; the accept loop continues to the next connection.

PORTABILITY (Alpine 3.21 / Python 3.12 / lxml 5.3.0): stdlib +
trafilatura/lxml only (via ``extraction.py``); POSIX-clean (no winreg, no
path assumptions — config via argv/env); the ``__main__`` binds a Linux
``AF_VSOCK`` listener (``socket.AF_VSOCK`` / ``VMADDR_CID_ANY``) — the
Windows host side addresses it as hv_sock service GUID
``GUEST_PARSER_SERVICE_GUID`` (port 50001).  mTLS is fail-closed at startup:
without cert paths the service refuses to start unless ``--allow-plaintext``
is explicitly passed (the #615 echo precedent for transport bring-up).
"""

from __future__ import annotations

import argparse
import logging
import os
import socket
import ssl
import sys
from typing import Protocol

from services.cleaner.src.extraction import (
    REASON_EXTRACTION_FAILED,
    clean_metadata_field,
    extract_document,
    judge_extraction,
)
from services.cleaner.src.normalize import normalize_text
from shared.ipc.parse_channel import (
    ChunkAssembler,
    ParseChannelError,
    ParseRequest,
    ParseResponse,
    decode_parse_request,
    encode_parse_response,
)
from shared.ipc.protocol import MessageFramer, MessageType
from shared.ipc.vsock import VsockAddress, VsockConfig, VsockTransport

logger = logging.getLogger(__name__)

#: Error codes on guest error responses (labels only — the cross-session
#: contract; never rename without a contract bump).
ERROR_CHANNEL_VIOLATION: str = "PARSE_CHANNEL_VIOLATION"
ERROR_RESPONSE_TOO_LARGE: str = "RESPONSE_TOO_LARGE"
ERROR_PARSER_INTERNAL: str = "PARSER_INTERNAL_ERROR"

#: Default accept/read timeout for the guest listener (seconds).
DEFAULT_TIMEOUT_S: float = 30.0

#: Fallback default port — kept equal to shared.constants.GUEST_PARSER_VSOCK_PORT
#: (50001 == 0xC351 → hv_sock GUID 0000c351-facb-11e6-bd58-64006a7986d3).
#: Redeclared here so the guest deployment does not need shared/constants.py;
#: a host-side test locks the two values together.
DEFAULT_PARSER_PORT: int = 50001


class ParseTransport(Protocol):
    """The transport surface this service consumes (``VsockTransport`` or a
    test double): length-framed, fail-closed receive/send."""

    def receive(self) -> bytes | None:  # pragma: no cover - protocol stub
        ...

    def send(self, data: bytes) -> bool:  # pragma: no cover - protocol stub
        ...


class GuestParserService:
    """Stateless request handler + connection loop for the parse channel."""

    def __init__(self, *, framer: MessageFramer | None = None) -> None:
        self._framer = framer or MessageFramer()

    # ------------------------------------------------------------------
    # Pure parsing logic (transport-free; unit-testable directly)
    # ------------------------------------------------------------------

    def parse(self, request: ParseRequest) -> ParseResponse:
        """Extract + normalize + judge one request.  Total: never raises on
        any input bytes — hostile-input failures are quarantine verdicts."""
        try:
            html = request.html.decode("utf-8")
        except UnicodeDecodeError:
            # Charset is the host fetch layer's job (module docstring);
            # replacement-decode and let the quality floors judge the result.
            html = request.html.decode("utf-8", errors="replace")

        raw_len = len(html)
        extracted = extract_document(html, source_url=request.source_url or None)
        if extracted is None or raw_len == 0:
            return ParseResponse(
                request_id=request.request_id,
                status="quarantined",
                text="",
                title=None,
                byline=None,
                published_date=None,
                word_count=0,
                confidence=0.0,
                reasons=(REASON_EXTRACTION_FAILED,),
            )

        # Pure-Python normalization is the guest's cleaning share; the
        # sanitization stage is composed host-side (module docstring).
        text = normalize_text(extracted.text)
        verdict = judge_extraction(text, raw_len, injection_finding_count=0)

        return ParseResponse(
            request_id=request.request_id,
            status="quarantined" if verdict.reasons else "clean",
            text=text,
            title=clean_metadata_field(extracted.title),
            byline=clean_metadata_field(extracted.byline),
            published_date=clean_metadata_field(extracted.published_date),
            word_count=verdict.word_count,
            confidence=verdict.confidence,
            reasons=verdict.reasons,
        )

    # ------------------------------------------------------------------
    # Connection loop
    # ------------------------------------------------------------------

    def serve_connection(self, transport: ParseTransport) -> int:
        """Serve parse requests on one connection until it closes.

        Returns the number of requests fully served (response sent).
        Fail-closed: any channel violation or truncation drops the
        connection (see module docstring).
        """
        served = 0
        while True:
            assembler = ChunkAssembler(
                MessageType.INGEST_PARSE_REQUEST, framer=self._framer
            )
            frame = transport.receive()
            if frame is None:
                return served  # clean close between messages
            while True:
                try:
                    complete = assembler.feed(frame)
                except ValueError as exc:
                    # ParseChannelError or a malformed envelope: answer if
                    # addressable, then drop the connection (no resync).
                    logger.error("parse-channel violation: %s", exc)
                    self._send_error(
                        transport,
                        assembler.request_id,
                        ERROR_CHANNEL_VIOLATION,
                        str(exc),
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
        self, transport: ParseTransport, assembler: ChunkAssembler
    ) -> bool:
        """Parse one assembled request and send the response.

        Returns False when the connection must be dropped (send failure).
        """
        request_id = assembler.request_id
        try:
            try:
                request = decode_parse_request(assembler)
            except ParseChannelError as exc:
                # Decode-side REQUEST violation (the chunks assembled but the
                # request schema is malformed, e.g. a non-string source_url
                # meta): a request-side channel violation — reported with the
                # violation code, never the response-size code.
                logger.error("request decode failed for %s: %s", request_id, exc)
                return self._send_error(
                    transport, request_id, ERROR_CHANNEL_VIOLATION, str(exc)
                )
            response = self.parse(request)
            frames = encode_parse_response(
                request_id=response.request_id,
                status=response.status,
                text=response.text,
                title=response.title,
                byline=response.byline,
                published_date=response.published_date,
                word_count=response.word_count,
                confidence=response.confidence,
                reasons=response.reasons,
                framer=self._framer,
            )
        except ParseChannelError as exc:
            # Encode-side cap: the serialized response outgrew the hard cap.
            logger.error("response encoding failed for %s: %s", request_id, exc)
            return self._send_error(
                transport, request_id, ERROR_RESPONSE_TOO_LARGE, str(exc)
            )
        except Exception as exc:  # noqa: BLE001 — fail-closed: label-only error reply
            # Exception CLASS name only — never content (module docstring).
            logger.exception("internal parser error for %s", request_id)
            return self._send_error(
                transport, request_id, ERROR_PARSER_INTERNAL, type(exc).__name__
            )

        for frame in frames:
            if not transport.send(frame):
                logger.error("send failed mid-response (request_id=%s)", request_id)
                return False
        return True

    def _send_error(
        self,
        transport: ParseTransport,
        request_id: str,
        error_code: str,
        message: str,
    ) -> bool:
        """Send a small error response if *request_id* is addressable."""
        if not request_id:
            return False  # first frame never yielded a correlation id
        try:
            frames = encode_parse_response(
                request_id=request_id,
                status="error",
                text="",
                error_code=error_code,
                message=message[:200],
                framer=self._framer,
            )
        except ValueError:
            # The error response itself failed to encode — fail closed: no
            # response, the caller drops the connection.  Catch ValueError,
            # not just ParseChannelError: ParseChannelError SUBCLASSES
            # ValueError, and MessageFramer.encode raises the PLAIN base
            # class when the envelope (which echoes the peer-supplied
            # request_id) exceeds the 64 KB frame cap.  Catching only the
            # subclass here once let that plain ValueError escape through
            # serve_connection and kill the listener (#655 adversarial
            # review; the channel-side request_id cap now also rejects the
            # trigger on the first frame — this is the defense in depth).
            return False
        for frame in frames:
            if not transport.send(frame):
                return False
        return True


# ---------------------------------------------------------------------------
# Guest entry point (runs inside the Alpine VM)
# ---------------------------------------------------------------------------


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m services.cleaner.guest.parser_service",
        description=(
            "BlarAI guest parser service (UC-003 Stage C) — AF_VSOCK listener "
            "inside the Alpine guest; parses hostile HTML so the host never "
            "does (ADR-030 §3)."
        ),
    )
    parser.add_argument(
        "--transport",
        choices=("vsock", "tcp"),
        default=os.environ.get("BLARAI_PARSER_TRANSPORT", "vsock"),
        help="vsock = Linux AF_VSOCK guest listener (default); "
        "tcp = 127.0.0.1 loopback for in-guest/dev testing only.",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get("BLARAI_PARSER_PORT", str(DEFAULT_PARSER_PORT))),
        help=f"Listener port (default {DEFAULT_PARSER_PORT} = hv_sock 0xC351).",
    )
    parser.add_argument(
        "--timeout-s",
        type=float,
        default=float(os.environ.get("BLARAI_PARSER_TIMEOUT_S", str(DEFAULT_TIMEOUT_S))),
        help="Accept/read timeout in seconds.",
    )
    parser.add_argument(
        "--cert",
        default=os.environ.get("BLARAI_PARSER_CERT", ""),
        help="mTLS server certificate (PEM).",
    )
    parser.add_argument(
        "--key",
        default=os.environ.get("BLARAI_PARSER_KEY", ""),
        help="mTLS private key (PEM).",
    )
    parser.add_argument(
        "--ca",
        default=os.environ.get("BLARAI_PARSER_CA", ""),
        help="CA certificate for client verification (PEM).",
    )
    parser.add_argument(
        "--allow-plaintext",
        action="store_true",
        help="Explicitly run WITHOUT mTLS (fail-closed default refuses; "
        "transport bring-up only, per the #615 echo precedent).",
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
    """mTLS server context — mirrors shared.ipc.vsock.create_server_ssl_context
    but RAISES on failure (refuse-to-start beats a silent plaintext fallback)."""
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.verify_mode = ssl.CERT_REQUIRED
    ctx.load_cert_chain(certfile=cert, keyfile=key)
    ctx.load_verify_locations(cafile=ca)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    return ctx


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
    listener.settimeout(args.timeout_s)
    logger.info(
        "guest parser listening (%s port %d, mTLS=%s)",
        args.transport,
        args.port,
        "on" if ssl_ctx is not None else "OFF (explicit --allow-plaintext)",
    )

    service = GuestParserService()
    config = VsockConfig(
        address=VsockAddress(cid=0, port=args.port),
        timeout_ms=int(args.timeout_s * 1000),
    )
    try:
        while True:
            try:
                client, _addr = listener.accept()
            except socket.timeout:
                continue
            except OSError as exc:
                logger.error("accept failed: %s", exc)
                continue
            client.settimeout(args.timeout_s)
            if ssl_ctx is not None:
                try:
                    client = ssl_ctx.wrap_socket(client, server_side=True)
                except (ssl.SSLError, OSError) as exc:
                    logger.error("mTLS handshake failed (connection dropped): %s", exc)
                    try:
                        client.close()
                    except OSError:
                        pass
                    continue
            transport = VsockTransport(
                config,
                dev_mode=ssl_ctx is None,
                host_mode=False,
                _socket=client,
            )
            try:
                served = service.serve_connection(transport)
                logger.info("connection closed after %d request(s)", served)
            except Exception as exc:  # noqa: BLE001 — one connection must never cost the listener
                # Structural label ONLY (exception class name) — never page
                # content or paths in a guest log line.  A malformed or
                # hostile connection costs at most that connection; the
                # accept loop continues (#655 adversarial review).
                logger.error(
                    "unexpected error serving connection (%s) — connection "
                    "dropped, listener continues",
                    type(exc).__name__,
                )
            finally:
                transport.close()
    except KeyboardInterrupt:
        logger.info("shutdown requested")
        return 0
    finally:
        try:
            listener.close()
        except OSError:
            pass


if __name__ == "__main__":
    sys.exit(main())
