"""
Guest-Parser Provisioning Round-Trip Smoke (#655 Stage C — acceptance proof)
============================================================================
The standalone harness the controlled provisioning session runs as the
guest-parser ACCEPTANCE proof.  It connects to a LIVE guest parser over the
Windows AF_HYPERV vsock, sends a small fixed HTML page, and prints the returned
status + title + word_count + the first ~200 chars of cleaned text.

RUN IT UNDER PYTHON 3.14 (the interpreter that HAS ``socket.AF_HYPERV`` — the
3.11 runtime cannot address AF_HYPERV, which is the whole reason the version
bridge exists).  From the repo root::

    py -3.14 scripts/guest_parser_smoke.py \
        --vm-id <VmId-guid> \
        --service-guid <hv_sock-service-guid> \
        --port 50001

Optional mTLS (matches the guest service's posture; omit for a plaintext
bring-up against a guest started with ``--allow-plaintext``)::

        --cert host.pem --key host.key --ca ca.pem

Fail-loud, exit non-zero on ANY error (unreachable guest, malformed response,
missing AF_HYPERV).  A clean run prints a PASS line and exits 0 — that line is
the provisioning-acceptance evidence.

Security: no external network calls — the only socket opened is AF_HYPERV to the
guest VM.  The HTML is a fixed in-script constant (never fetched).
"""

from __future__ import annotations

import argparse
import os
import socket
import sys
import uuid

# Make the repo root importable when run as a plain script under 3.14.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shared.ipc.parse_channel import (  # noqa: E402
    ChunkAssembler,
    ParseChannelError,
    ParseResponse,
    decode_parse_response,
    encode_parse_request,
)
from shared.ipc.protocol import MessageType  # noqa: E402
from shared.ipc.vsock import (  # noqa: E402
    VsockAddress,
    VsockConfig,
    VsockTransport,
)

# A small, self-contained, extraction-friendly page (title + prose).
_SMOKE_HTML: bytes = (
    b"<html><head><title>BlarAI Guest Parser Smoke</title></head>"
    b"<body><article><h1>BlarAI Guest Parser Smoke</h1>"
    b"<p>This fixed document exercises the UC-003 guest-homed parser end to "
    b"end over the AF_HYPERV vsock boundary. The guest extracts the article "
    b"text, normalizes it, and returns a clean parse response. If you can read "
    b"this sentence in the cleaned output, the provisioning round-trip works "
    b"and the parse channel is healthy on this machine.</p>"
    b"</article></body></html>"
)
_SMOKE_SOURCE_URL: str = "blarai://guest-parser-smoke"


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="py -3.14 scripts/guest_parser_smoke.py",
        description=(
            "Guest-parser AF_HYPERV provisioning round-trip smoke (#655 Stage C)."
        ),
    )
    parser.add_argument("--vm-id", required=True, help="Hyper-V VmId GUID.")
    parser.add_argument(
        "--service-guid",
        required=True,
        help="hv_sock service GUID (<port_hex>-facb-11e6-bd58-64006a7986d3).",
    )
    parser.add_argument(
        "--port", type=int, default=50001, help="AF_VSOCK port (default 50001)."
    )
    parser.add_argument(
        "--timeout-s", type=float, default=30.0, help="Connect/read timeout."
    )
    parser.add_argument("--cert", default="", help="mTLS client cert (PEM).")
    parser.add_argument("--key", default="", help="mTLS private key (PEM).")
    parser.add_argument("--ca", default="", help="mTLS CA cert (PEM).")
    return parser


def _round_trip(args: argparse.Namespace) -> ParseResponse:
    """Connect, send the fixed HTML, decode the response.  Raises on any error."""
    if not hasattr(socket, "AF_HYPERV"):
        raise RuntimeError(
            f"this interpreter ({sys.version.split()[0]}) lacks socket.AF_HYPERV "
            "— run the smoke harness under Python 3.14 (py -3.14)."
        )

    address = VsockAddress(
        cid=0,
        port=args.port,
        vm_id=args.vm_id,
        service_guid=args.service_guid,
    )
    has_mtls = bool(args.cert and args.ca)
    # #655: when no mTLS material is supplied, reach the guest over PLAINTEXT
    # AF_HYPERV — the host-side parallel to the guest's --allow-plaintext flag.
    # The OLD code set dev_mode=not has_mtls, which sent the host to AF_INET
    # 127.0.0.1:port (connection-refused) instead of crossing the VM boundary.
    # With mTLS args, the cert material drives the AF_HYPERV+mTLS path (the
    # plaintext opt-in is inert when certs are present — mTLS wins).
    config = VsockConfig(
        address=address,
        mtls_cert_path=args.cert,
        mtls_key_path=args.key,
        ca_cert_path=args.ca,
        timeout_ms=max(1, int(args.timeout_s * 1000)),
        allow_plaintext_hyperv=not has_mtls,
    )
    # dev_mode=False + host_mode=False → AF_HYPERV guest boundary.  mTLS when
    # certs are given; plaintext bring-up (no SSL) when allow_plaintext_hyperv.
    transport = VsockTransport(config, dev_mode=False, host_mode=False)

    if not transport.connect():
        raise RuntimeError(
            "could not open the AF_HYPERV vsock to the guest parser "
            f"(vm_id={args.vm_id}, service_guid={args.service_guid}, "
            f"port={args.port}) — is the guest listener up and the service GUID "
            "registered on the host?"
        )
    try:
        request_id = uuid.uuid4().hex
        frames = encode_parse_request(
            request_id=request_id,
            html=_SMOKE_HTML,
            source_url=_SMOKE_SOURCE_URL,
        )
        for frame in frames:
            if not transport.send(frame):
                raise RuntimeError("send failed mid-request")

        assembler = ChunkAssembler(MessageType.INGEST_PARSE_RESPONSE)
        while True:
            frame = transport.receive()
            if frame is None:
                raise RuntimeError("connection closed mid-response (truncated)")
            if assembler.feed(frame):
                break
        return decode_parse_response(assembler)
    finally:
        transport.close()


def main(argv: list[str] | None = None) -> int:
    args = _build_arg_parser().parse_args(argv)
    try:
        response = _round_trip(args)
    except (RuntimeError, ParseChannelError, ValueError) as exc:
        print(f"FAIL: guest parser round-trip failed: {exc}", file=sys.stderr)
        return 1

    snippet = response.text[:200].replace("\n", " ")
    print("PASS: guest parser round-trip OK")
    print(f"  status      : {response.status}")
    print(f"  title       : {response.title!r}")
    print(f"  word_count  : {response.word_count}")
    print(f"  confidence  : {response.confidence:.3f}")
    print(f"  reasons     : {list(response.reasons)}")
    print(f"  text[:200]  : {snippet!r}")
    # A non-error response with text is the acceptance signal; an 'error' status
    # is a fail-loud (the channel worked but the guest reported a fault).
    if response.status == "error":
        print(
            f"FAIL: guest returned status=error (code={response.error_code})",
            file=sys.stderr,
        )
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
