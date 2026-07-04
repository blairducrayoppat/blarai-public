"""
UC-003 Markdown-Structure Verification — guest parse, NO egress (#662, #655).
=============================================================================
Confirms that ``include_formatting=True`` (services/cleaner/src/extraction.py)
is LIVE inside the re-provisioned guest parser: a heading/list/bold-bearing HTML
fixture is sent over the AF_HYPERV vsock parse channel and the returned cleaned
text is checked for the formatting markers the OLD (flag-off) code stripped.

THIS IS DELIBERATELY OFF THE EGRESS PATH (the other agent's point, and correct):
there is NO ``guarded_fetch``, NO URL adjudicator, NO ``egress_guard`` — only a
host→guest parse of bytes this process already holds. The welded egress door and
the #659 locks are untouched. The fetch limb stays dormant by structural absence.

RUN UNDER THE 3.11 RUNTIME VENV (``.venv``). 3.11 lacks ``socket.AF_HYPERV``, so
the parse hop routes through the production version bridge (a py-3.14 subprocess),
mirroring production exactly — the same path the 2026-06-12 live-fetch proof used.

Exit 0 = markers confirmed live; non-zero = a specific failure stage.
"""

from __future__ import annotations

import json
import os
import sys
import uuid
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# The Windows console codec is cp1252; the status arrows and the guest's returned
# text both carry non-cp1252 unicode. Force UTF-8 so the run never dies on a glyph.
try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except Exception:  # noqa: BLE001 — best-effort; fall back to default stream
    pass

VM_ID = "9c7f986f-7afd-48b0-af5b-2c330df6b38f"
VSOCK_PORT = 50001
EVIDENCE_JSON = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "docs", "security", "uc003_markdown_verify_2026-06-13.json",
)

# An article-shaped fixture with a heading, a sub-heading, an unordered list, and
# an inline-bold phrase. Well over the 80-word HTML extraction floor so the verdict
# comes back "clean". The list items carry distinctive phrases so the dash markers
# are unambiguous to grep.
FIXTURE_HTML: bytes = (
    b"<html><head><title>Markdown Structure Verification</title></head>"
    b"<body><article>"
    b"<h1>Markdown Structure Verification</h1>"
    b"<p>This document exists to confirm that the BlarAI guest-homed parser "
    b"preserves document structure when it extracts an article. The extraction "
    b"stage now passes the include_formatting flag to trafilatura, which means "
    b"headings, unordered lists, and inline emphasis all survive the trip from "
    b"raw HTML into the cleaned article text that the assistant renders.</p>"
    b"<h2>Why structure matters</h2>"
    b"<p>A knowledge bank that flattens every heading into indistinguishable "
    b"prose loses the shape of the source. Section boundaries, enumerated steps, "
    b"and the emphasis an author placed on a <strong>critical warning</strong> "
    b"are part of the meaning, not decoration. Preserving them keeps the stored "
    b"article faithful to what was published.</p>"
    b"<h2>What this fixture checks</h2>"
    b"<p>The list below should return with leading dash markers, the headings "
    b"above should remain distinct lines, and the bold phrase should be wrapped "
    b"in emphasis markers when the parser returns its cleaned text.</p>"
    b"<ul>"
    b"<li>First, that unordered list items keep their dash markers intact.</li>"
    b"<li>Second, that multiple list entries each stay on their own line.</li>"
    b"<li>Third, that the list is not collapsed into one flat paragraph.</li>"
    b"</ul>"
    b"<p>If the cleaned text contains the dash-prefixed list items and the "
    b"emphasis markers, the include_formatting flag is confirmed live inside the "
    b"NIC-less guest, end to end over the vsock parse channel.</p>"
    b"</article></body></html>"
)
SOURCE_URL = "blarai://uc003-markdown-verify"


def main() -> int:
    from launcher.guest_parser import (
        hv_service_guid_for_port,
        set_guest_parser_bridge,
    )
    from launcher.guest_parser_health import parse_round_trip
    from launcher.guest_parser_invoker import GuestParserBridge, bridge_required
    from launcher.parser_channel_seam import ParserEndpoint
    from shared.ipc.parse_channel import encode_parse_request

    print("[1] arming the AF_HYPERV version bridge (py-3.14 subprocess; 3.11 "
          "runtime lacks socket.AF_HYPERV)…")
    if bridge_required():
        set_guest_parser_bridge(GuestParserBridge(bridge_python=""))
        print("    bridge parked (production-faithful path)")
    else:
        print("    interpreter has AF_HYPERV in-process — no bridge needed")

    endpoint = ParserEndpoint(
        vm_id=VM_ID,
        service_guid=hv_service_guid_for_port(VSOCK_PORT),
        vsock_port=VSOCK_PORT,
        timeout_s=30.0,
    )
    print(f"[2] encoding parse request (fixture {len(FIXTURE_HTML)} bytes) → "
          f"guest {endpoint.service_guid} port {VSOCK_PORT}")
    frames = encode_parse_request(
        request_id=uuid.uuid4().hex, html=FIXTURE_HTML, source_url=SOURCE_URL
    )

    print("[3] >>> host→guest PARSE round-trip (NO fetch, NO egress)…")
    resp = parse_round_trip(endpoint, frames)
    if resp is None:
        print("    FAIL: parse_round_trip returned None (guest unreachable / "
              "channel rejected / bridge crash) — is blarai-parser running?")
        return 5
    if resp.status == "error":
        print(f"    FAIL: guest parser error response: {resp.error_code} "
              f"({resp.message})")
        return 6
    print(f"    guest parse ok: status={resp.status}, word_count={resp.word_count}, "
          f"confidence={resp.confidence:.3f}")

    text = resp.text
    # Marker detection. The OLD (flag-off) code stripped ALL of these — any one
    # present proves include_formatting=True reached the guest. The dash list
    # marker is the corpus-confirmed format for trafilatura 2.1.0 + the flag.
    has_list = "\n- " in text or text.startswith("- ")
    has_bold = "**" in text
    has_heading_hash = any(
        line.lstrip().startswith("#") for line in text.splitlines()
    )

    print("[4] formatting-marker scan of returned cleaned text:")
    print(f"    list dash marker (- ) : {has_list}")
    print(f"    inline bold (**)      : {has_bold}")
    print(f"    heading hash (#)      : {has_heading_hash}")
    print("    --- full returned text ---")
    for line in text.splitlines():
        print(f"    | {line}")
    print("    --- end returned text ---")

    # Decisive pass: the dash list marker (the corpus-confirmed, OLD-code-stripped
    # signal). Bold/heading are reported as corroborating evidence.
    passed = has_list

    evidence = {
        "verified_utc": datetime.now(timezone.utc).isoformat(),
        "purpose": "UC-003 markdown structure (include_formatting=True) live in guest",
        "egress": "NONE — host->guest parse only; guarded_fetch/adjudicator/egress_guard untouched",
        "transport": "AF_HYPERV vsock via py-3.14 version bridge (3.11 runtime)",
        "endpoint": {
            "vm_id": VM_ID,
            "service_guid": endpoint.service_guid,
            "vsock_port": VSOCK_PORT,
        },
        "response": {
            "status": resp.status,
            "word_count": resp.word_count,
            "confidence": resp.confidence,
            "reasons": list(resp.reasons),
            "title": resp.title,
        },
        "markers": {
            "list_dash": has_list,
            "inline_bold": has_bold,
            "heading_hash": has_heading_hash,
        },
        "returned_text": text,
        "result": "PASS" if passed else "FAIL",
    }
    with open(EVIDENCE_JSON, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(evidence, fh, indent=2, ensure_ascii=False)
    print(f"[5] evidence written → {EVIDENCE_JSON}")

    print("")
    if passed:
        print("================= GREEN — markdown structure LIVE in guest ===========")
        print("  include_formatting=True confirmed end-to-end over the parse channel.")
        print("======================================================================")
        return 0
    print("================= RED — formatting markers ABSENT ====================")
    print("  The guest returned cleaned text WITHOUT the dash list marker — the")
    print("  flag did not reach the guest (re-check provision.sh ran the new ISO).")
    print("======================================================================")
    return 7


if __name__ == "__main__":
    sys.exit(main())
