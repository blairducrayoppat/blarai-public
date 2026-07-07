"""
Guest-Parser Frame-Level Health Probe (#655 Stage C — the seam binding)
=======================================================================
:mod:`launcher.parser_channel_seam` defines an ABSTRACT ``HealthProbe`` —
``Callable[[ParserEndpoint], bool]`` — that the guest-parser manager consults to
decide READY, and FAILS CLOSED (``GP_CHANNEL_UNBOUND``) while none is bound.  This
module builds the REAL probe and the round-trip it performs:

  * The probe sends a minimal ``INGEST_PARSE_REQUEST`` (trivial fixed HTML) and
    requires a well-formed ``INGEST_PARSE_RESPONSE`` back.  There is no separate
    PING frame in the parse channel — a tiny parse IS the natural frame-level
    health check (``services/cleaner/guest/parser_service.py`` answers it).
  * Transport routing matches the rest of #655: on a 3.12+ interpreter the probe
    talks AF_HYPERV in-process; on the 3.11 runtime it routes through the parked
    :class:`launcher.guest_parser_invoker.GuestParserBridge` (the 3.14
    subprocess).  The launcher binds ONE probe that does the right thing for the
    running interpreter.

The probe NEVER raises for an expected failure (returns False) — the manager
treats an escaped exception as a failed probe anyway, but a clean False keeps the
log quiet on ordinary unreachability.  Fail-closed: a garbled / timed-out / wrong
response → False, never a fabricated True.

Security: no external network calls (AF_HYPERV vsock / the bridge subprocess
only); no page content in logs (the health HTML is a fixed constant).
"""

from __future__ import annotations

import logging
import socket
import uuid

from launcher.parser_channel_seam import HealthProbe, ParserEndpoint
from shared.ipc.parse_channel import (
    ChunkAssembler,
    ParseChannelError,
    ParseResponse,
    decode_parse_response,
    encode_parse_request,
)
from shared.ipc.protocol import MessageType

logger = logging.getLogger(__name__)

# The fixed, trivial HTML the health probe parses.  Small, self-contained, and
# extraction-friendly: a title + a paragraph the guest's trafilatura extractor
# returns cleanly.  A constant — never page content, so it is safe to log.
HEALTH_HTML: bytes = (
    b"<html><head><title>BlarAI guest parser health</title></head>"
    b"<body><article><h1>BlarAI guest parser health</h1>"
    b"<p>This fixed document is the frame-level health check for the "
    b"UC-003 guest-homed parser. It contains enough prose for the "
    b"extractor to return a clean, well-formed parse response so the "
    b"launcher can confirm the parse channel end to end.</p>"
    b"</article></body></html>"
)

#: The source_url metadata on the health request — a sentinel, not a real URL
#: (the guest never fetches; ADR-030 §4).  Printable ASCII per the channel rule.
HEALTH_SOURCE_URL: str = "blarai://guest-parser-health-check"


def build_health_request_frames(request_id: str | None = None) -> list[bytes]:
    """Encode the minimal health ``INGEST_PARSE_REQUEST`` into chunked frames.

    Args:
        request_id: correlation id (a fresh UUID when None).
    """
    rid = request_id or uuid.uuid4().hex
    return encode_parse_request(
        request_id=rid,
        html=HEALTH_HTML,
        source_url=HEALTH_SOURCE_URL,
    )


def _in_process_round_trip(
    endpoint: ParserEndpoint,
    request_frames: list[bytes],
    *,
    mtls_cert: str = "",
    mtls_key: str = "",
    mtls_ca: str = "",
) -> ParseResponse | None:
    """Do the parse round-trip in-process over AF_HYPERV (3.12+ interpreter).

    Returns the decoded response, or None on any failure (fail-closed).
    """
    if not hasattr(socket, "AF_HYPERV"):  # pragma: no cover - guarded by caller
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
        # No mTLS material → explicit plaintext-AF_HYPERV bring-up (#655).  The
        # OLD `dev_mode=not has_mtls` sent the no-cert probe to AF_INET 127.0.0.1
        # instead of crossing the VM boundary — the same conflation the #655 host
        # transport fix removes.  dev_mode=False + host_mode=False keeps the probe
        # on the AF_HYPERV guest boundary; mTLS is honored when certs are given.
        allow_plaintext_hyperv=not has_mtls,
    )
    transport = VsockTransport(
        config,
        dev_mode=False,
        host_mode=False,
    )
    if not transport.connect():
        return None
    try:
        for frame in request_frames:
            if not transport.send(frame):
                return None
        assembler = ChunkAssembler(MessageType.INGEST_PARSE_RESPONSE)
        while True:
            frame = transport.receive()
            if frame is None:
                return None
            try:
                complete = assembler.feed(frame)
            except (ParseChannelError, ValueError):
                return None
            if complete:
                break
        try:
            return decode_parse_response(assembler)
        except (ParseChannelError, ValueError):
            return None
    finally:
        transport.close()


def _assemble_bridge_response(frames: list[bytes]) -> ParseResponse | None:
    """Assemble bridge-returned ``INGEST_PARSE_RESPONSE`` frames into a typed view.

    The version bridge (the 3.11 runtime path) returns the raw response frames;
    assemble + decode them here.  Any channel/framing violation, truncation, or
    malformed body → None (fail-closed), never a fabricated verdict.
    """
    assembler = ChunkAssembler(MessageType.INGEST_PARSE_RESPONSE)
    try:
        for frame in frames:
            assembler.feed(frame)
        if not assembler.complete:
            return None
        return decode_parse_response(assembler)
    except (ParseChannelError, ValueError):
        return None


def parse_round_trip(
    endpoint: ParserEndpoint,
    request_frames: list[bytes],
    *,
    mtls_cert: str = "",
    mtls_key: str = "",
    mtls_ca: str = "",
) -> ParseResponse | None:
    """Run a prepared parse request through the guest and decode the response.

    The content-parse sibling of :func:`make_health_probe`: identical transport
    routing — the parked :class:`launcher.guest_parser_invoker.GuestParserBridge`
    on the 3.11 runtime, in-process AF_HYPERV on 3.12+ — but it returns the
    DECODED :class:`ParseResponse` (the health probe only needs a bool).  Never
    raises; any failure (unreachable, garbled, channel violation, bridge crash)
    → None (fail-closed: URL ingest refuses, NEVER a host-side parse fallback —
    ADR-030 §3).
    """
    # Import here to avoid a launcher import cycle (guest_parser imports the
    # seam; this module is imported BY the launcher wiring), mirroring the
    # health probe's lazy bridge lookup.
    from launcher.guest_parser import get_guest_parser_bridge

    bridge = get_guest_parser_bridge()
    if bridge is not None:
        try:
            frames = bridge.parse(endpoint, request_frames)
        except Exception as exc:  # noqa: BLE001 — fail-closed, never raise
            logger.error(
                "guest-parser parse bridge raised (%s) — fail-closed",
                type(exc).__name__,
            )
            return None
        if frames is None:
            return None
        return _assemble_bridge_response(frames)

    # No bridge → in-process AF_HYPERV (3.12+).  On a 3.11 interpreter with no
    # bridge bound there is no path to the guest at all → None.
    return _in_process_round_trip(
        endpoint,
        request_frames,
        mtls_cert=mtls_cert,
        mtls_key=mtls_key,
        mtls_ca=mtls_ca,
    )


def make_health_probe(
    *,
    mtls_cert: str = "",
    mtls_key: str = "",
    mtls_ca: str = "",
) -> HealthProbe:
    """Build the seam ``HealthProbe`` for the running interpreter.

    The returned callable sends the minimal health parse request and returns
    True iff a well-formed response comes back.  It routes through the parked
    version bridge on the 3.11 runtime and in-process on 3.12+.  It never raises.
    """

    def _probe(endpoint: ParserEndpoint) -> bool:
        try:
            request_frames = build_health_request_frames()
        except (ParseChannelError, ValueError) as exc:  # pragma: no cover
            logger.error(
                "guest-parser health: could not encode request (%s)",
                type(exc).__name__,
            )
            return False

        # Import here to avoid a launcher import cycle (guest_parser imports the
        # seam; this module is imported BY the launcher wiring).
        from launcher.guest_parser import get_guest_parser_bridge

        bridge = get_guest_parser_bridge()
        if bridge is not None:
            try:
                return bool(bridge.health(endpoint, request_frames))
            except Exception as exc:  # noqa: BLE001 — fail-closed
                logger.error(
                    "guest-parser health bridge raised (%s) — fail-closed",
                    type(exc).__name__,
                )
                return False

        # No bridge → in-process AF_HYPERV (3.12+).  On a 3.11 interpreter with
        # no bridge bound there is no path to the guest at all → False.
        response = _in_process_round_trip(
            endpoint,
            request_frames,
            mtls_cert=mtls_cert,
            mtls_key=mtls_key,
            mtls_ca=mtls_ca,
        )
        if response is None:
            return False
        # A well-formed response of ANY status (clean/quarantined/error) proves
        # the channel works end to end.  The health check verifies the CHANNEL,
        # not the extraction verdict of one fixed document.
        return True

    return _probe
