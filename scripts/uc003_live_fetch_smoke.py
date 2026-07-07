"""
UC-003 Live-Fetch Smoke — the first sanctioned external egress (#655 going-live).
================================================================================
THE air-gap-removal proof: one operator-directed `/ingest <url>` fetched through
the single Policy-Agent-gated door (`shared.security.guarded_fetch`), parsed
INSIDE the NIC-less guest over AF_HYPERV vsock, and composed host-side — proving
fetch → guest-parse → preview end to end against a real internet article.

RUN UNDER THE 3.11 RUNTIME VENV (it owns httpx + trafilatura). The guest parse
hop runs through the production version bridge (a py-3.14 subprocess, since 3.11
lacks `socket.AF_HYPERV`). This mirrors the production architecture exactly.

SELF-REWELDING (fail-closed): the PA adjudicator is registered with EXACTLY the
operator's host allowlisted for this one fetch, and is CLEARED in a `finally` (and
again on process exit), so the egress door returns to deny-by-default no matter
how this exits. The egress allowlist is the operator's single host — the
per-action carve-out of ADR-027 Amendment 1 ("the paste is the consent for that
ONE URL"). GET-only is enforced by the door.

This harness deliberately does NOT globally arm `shared.security.egress_guard`
(the rule-3 kill-switch layer): the door's pre-fetch SSRF resolution would trip an
armed guard before the per-fetch widen (documented in guarded_fetch). The armed
posture is covered by tests/security and is a clean follow-up; this smoke proves
the per-action door + the guest parse corridor.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# The LA-chosen first-fetch article (#655 c.1055) and its single host.
URL = (
    "https://www.bleepingcomputer.com/news/security/"
    "github-announces-npm-security-changes-to-tackle-supply-chain-attacks/"
)
HOST_ALLOWLIST = frozenset({"www.bleepingcomputer.com"})
VM_ID = "9c7f986f-7afd-48b0-af5b-2c330df6b38f"
VSOCK_PORT = 50001


def _bring_up_parser():
    """Bring the resident guest parser to READY via the version bridge (no deploy)."""
    from launcher.guest_parser import (
        GuestParserConfig,
        GuestParserManager,
        hv_service_guid_for_port,
        set_guest_parser_bridge,
    )
    from launcher.guest_parser_health import make_health_probe
    from launcher.guest_parser_invoker import GuestParserBridge, bridge_required
    from launcher.parser_channel_seam import register_parser_health_probe

    config = GuestParserConfig(
        enabled=True,
        vm_name="BlarAI-Orchestrator",
        guest_root="/opt/blarai/parser",
        vsock_port=VSOCK_PORT,
        service_guid=hv_service_guid_for_port(VSOCK_PORT),
        service_source_dir="services/cleaner/guest",
        entry_module="blarai_guest_parser",
        deploy_timeout_s=120.0,
        health_timeout_s=30.0,
        health_poll_interval_s=1.0,
        bridge_python="",
    )
    if bridge_required():
        set_guest_parser_bridge(GuestParserBridge(bridge_python=""))
    register_parser_health_probe(make_health_probe())
    manager = GuestParserManager(config, vm_id=VM_ID)
    # Resident-parser model: the parser auto-starts on guest boot, so we skip
    # deploy() (Copy-VMFile is dead on this kernel) and go straight to start(),
    # which is the health check (transport reachable + frame-level probe).
    if not manager.start():
        raise RuntimeError(f"guest parser not READY: {manager.failure}")
    return manager


def main() -> int:
    from services.cleaner.src.pipeline import clean_from_guest_parse
    from services.ui_gateway.src.url_adjudicator import (
        make_deterministic_url_adjudicate,
        register_url_ingest_adjudicator,
    )
    from shared.security import guarded_fetch

    print("[1] bringing up the resident guest parser (via the 3.14 bridge)…")
    manager = _bring_up_parser()
    print(f"    guest parser READY (state={manager.state.value})")

    print("[2] registering the PA adjudicator — bleepingcomputer host allowlisted "
          "for ONE fetch (ADR-027 Am.1 per-action carve-out)…")
    register_url_ingest_adjudicator(make_deterministic_url_adjudicate(HOST_ALLOWLIST))
    try:
        print(f"[3] >>> FIRST SANCTIONED EGRESS — GET {URL}")
        result = guarded_fetch.fetch_external(URL, purpose="uc003-url-ingest", timeout_s=30.0)
        if not result.ok:
            print(f"    FETCH DENIED (door fail-closed): {result.denied_reason}")
            return 4
        print(f"    FETCHED ok: http={result.status}, content_type={result.content_type!r}, "
              f"bytes={len(result.content_text)}, injection_flags={list(result.injection_flags)}")

        print("[4] parsing the hostile HTML INSIDE the NIC-less guest…")
        parsed = manager.parse_html(result.content_text, URL)
        if parsed is None:
            print("    FAIL: guest parse returned None (unreachable / channel rejected)")
            return 5
        if parsed.status == "error":
            print(f"    FAIL: guest parser error: {parsed.error_code}")
            return 6
        print(f"    guest parse ok: status={parsed.status}, word_count={parsed.word_count}")

        print("[5] composing the host-side verdict (ADR-030 §5 injection axis)…")
        clean = clean_from_guest_parse(
            parsed,
            raw_len=len(result.content_text),
            extra_injection_findings=len(result.injection_flags),
        )
        print("")
        print("================= GREEN SIGNAL — UC-003 live fetch =================")
        print(f"  title       : {clean.title!r}")
        print(f"  byline      : {clean.byline!r}")
        print(f"  published   : {clean.published_date!r}")
        print(f"  word_count  : {clean.word_count}")
        print(f"  status      : {clean.status}")
        print(f"  confidence  : {clean.confidence:.3f}")
        print(f"  reasons     : {list(clean.reasons)}")
        print(f"  cleaner_ver : {clean.cleaner_version}")
        print(f"  source_fmt  : {clean.source_format}")
        print("  --- cleaned text preview (first 600 chars) ---")
        print(f"  {clean.text[:600]!r}")
        print("===================================================================")
        return 0
    finally:
        from shared.security.guarded_fetch import clear_url_adjudicator

        clear_url_adjudicator()
        manager.stop()
        print("[re-weld] PA adjudicator CLEARED + parser stopped — "
              "egress door back to deny-by-default.")


if __name__ == "__main__":
    sys.exit(main())
