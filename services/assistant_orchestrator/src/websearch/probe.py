"""Kagi ``web_search`` live-contract probe (Vikunja #739 — the L188 control).

A cheap, standalone rehearsal of the ONE risky moment in the web_search go-live
ceremony (``docs/runbooks/web_search_go_live.md`` Step 6): the first live GET to
Kagi. It exercises the REAL external contract's three axes against the real
endpoint with the real credential, so a contract drift like the #724 v0->v1
**HTTP 401** is caught by an operator running one command BEFORE the ceremony,
not by the ceremony's first outbound fetch:

  * **auth axis** — does ``Authorization: Bearer <key>`` against
    ``POST /api/v1/search`` return HTTP 200 (not 401/403)?
  * **transport axis** — does the fetch reach the endpoint through the ONE
    sanctioned egress door at all (SSRF guard + PA adjudication + widen/revoke)?
  * **schema axis** — does the response carry ``data.search`` as a list of
    result objects, and does the ADAPTER's own SSOT parser
    (:func:`live_adapter._parse_v1_search`) map at least one result from it?

WHY IT ROUTES THROUGH THE DOOR (not a private httpx client). BlarAI's runtime
may import a network client in exactly one module — the egress door
(``shared/security/guarded_fetch.py``; ``tests/security/test_no_external_egress``
enforces this). So the probe fetches through :func:`guarded_fetch.fetch_external`,
exactly as the adapter does, and — because the door is deny-by-default (no
adjudicator + empty allowlist) — it TEMPORARILY registers a tightly-scoped
adjudicator that ALLOWs only this one endpoint+purpose for the single probe
fetch, then restores the prior door posture in a ``finally``. This is the manual
go-live rehearsal action; the probe is never invoked by any test, and it changes
no config, no allowlist, and no shipped default.

REFUSE, NEVER FAKE. With no Kagi credential provisioned the probe exits **2**
with a clear message (it does not silently "pass"). It hits the network ONLY
when invoked with the explicit ``--probe`` flag; a bare
``python -m services.assistant_orchestrator.src.websearch.probe`` performs no
I/O and prints usage. Importing this module performs no network I/O of any kind
(all door/adapter imports are lazy, inside :func:`main`).

Exit codes:

  * ``0`` — CONTRACT VERIFIED (auth accepted + schema present + parser maps ≥1).
  * ``1`` — CONTRACT DRIFT (reachable but auth rejected, or the response schema
    diverged from the adapter's assumption).
  * ``2`` — REFUSED: no usable Kagi API key is provisioned (never a fake pass).
  * ``3`` — INCONCLUSIVE: the endpoint could not be exercised (egress door
    denied the fetch, network/transport error, or a non-JSON body) — not a
    verified pass and not proof of drift; see the printed reason.

Usage::

    python -m services.assistant_orchestrator.src.websearch.probe --probe
    python -m services.assistant_orchestrator.src.websearch.probe --probe --query "openvino latest release"
"""

from __future__ import annotations

import argparse
import sys
from typing import TYPE_CHECKING, Callable, Optional, Sequence

if TYPE_CHECKING:  # import-time-free type hints only (no runtime network import)
    from shared.security.guarded_fetch import Verdict

#: The door's per-URL adjudicator shape: ``(url, purpose) -> Verdict``.
UrlAdjudicator = Callable[[str, str], "Verdict"]

# Exit codes (see module docstring).
EXIT_VERIFIED: int = 0
EXIT_DRIFT: int = 1
EXIT_NO_CREDENTIAL: int = 2
EXIT_INCONCLUSIVE: int = 3

#: The default benign probe query — a term that reliably returns web results so
#: the schema axis has entries to inspect. Overridable with ``--query``.
_DEFAULT_QUERY: str = "openvino latest release"


def _build_parser() -> argparse.ArgumentParser:
    """Build the argparse parser (import-safe; constructs no network state)."""
    parser = argparse.ArgumentParser(
        prog="python -m services.assistant_orchestrator.src.websearch.probe",
        description=(
            "Kagi web_search live-contract probe (Vikunja #739 / L188). "
            "Exercises the real Kagi Search API contract with the provisioned "
            "credential. Requires --probe to touch the network; refuses (exit 2) "
            "if no key is provisioned."
        ),
    )
    parser.add_argument(
        "--probe",
        action="store_true",
        help=(
            "Actually run the live probe (fires ONE real fetch to kagi.com "
            "through the egress door). Without this flag nothing is fetched."
        ),
    )
    parser.add_argument(
        "--query",
        default=_DEFAULT_QUERY,
        help=(
            "The benign search query to send (default: %(default)r). Only the "
            "response SHAPE is inspected; result content is never trusted."
        ),
    )
    return parser


def _scoped_probe_adjudicator(endpoint: str, purpose: str) -> UrlAdjudicator:
    """Build a one-endpoint ALLOW adjudicator bound to this probe's single fetch.

    Returns an adjudicator that ALLOWs only the exact ``(endpoint, purpose)``
    this probe is about to fetch and DENIes anything else — the door still runs
    its full SSRF guard, resolution recheck, and widen/revoke around the call.
    """
    from shared.security.guarded_fetch import Verdict

    def _adjudicate(url: str, fetch_purpose: str) -> "Verdict":
        if url == endpoint and fetch_purpose == purpose:
            return Verdict.ALLOW
        return Verdict.DENY

    return _adjudicate


def _run_probe(query: str) -> int:
    """Execute the live contract probe. Returns one of the module's exit codes.

    Lazy-imports the door + adapter so importing this module stays network-free.
    """
    # Lazy imports (keep module import side-effect-free and network-client-free).
    from shared.secrets.kagi_key_loader import load_wrapped_kagi_key
    from shared.security import guarded_fetch
    from shared.security.guarded_fetch import fetch_external
    from services.assistant_orchestrator.src.websearch.live_adapter import (
        DEFAULT_SEARCH_TIMEOUT_S,
        KAGI_SEARCH_ENDPOINT,
        WEB_SEARCH_FETCH_PURPOSE,
        _parse_v1_search,
    )

    print("Kagi web_search live-contract probe (Vikunja #739 / L188)")
    print(f"  endpoint : POST {KAGI_SEARCH_ENDPOINT}")
    print("  auth     : Authorization: Bearer <redacted>")
    print(f"  query    : {query!r}")
    print("")

    # --- REFUSE (never fake) when no credential is provisioned. ---
    key = load_wrapped_kagi_key()
    if key is None:
        print(
            "REFUSED: no usable Kagi API key is provisioned "
            "(%LOCALAPPDATA%\\BlarAI\\secrets\\kagi_api_key.dpapi absent or "
            "malformed)."
        )
        print(
            "Provision it via:  python -m shared.secrets.provision_kagi_key  "
            "then re-run. This probe never fakes a pass."
        )
        return EXIT_NO_CREDENTIAL

    # --- Arm the door for exactly this one fetch, restoring posture after. ---
    previous = guarded_fetch.active_url_adjudicator()
    guarded_fetch.register_url_adjudicator(
        _scoped_probe_adjudicator(KAGI_SEARCH_ENDPOINT, WEB_SEARCH_FETCH_PURPOSE)
    )
    try:
        result = fetch_external(
            KAGI_SEARCH_ENDPOINT,
            purpose=WEB_SEARCH_FETCH_PURPOSE,
            timeout_s=DEFAULT_SEARCH_TIMEOUT_S,
            authorization=key.authorization_header_value(),
            method="POST",
            json_body={"query": query.strip() or _DEFAULT_QUERY},
        )
    finally:
        # Restore the exact prior door posture (usually: no adjudicator = dormant).
        if previous is not None:
            guarded_fetch.register_url_adjudicator(previous)
        else:
            guarded_fetch.clear_url_adjudicator()

    # --- Transport axis: did the fetch reach the endpoint through the door? ---
    if not result.ok:
        print(
            f"  [axis] transport (egress door) : FAIL "
            f"({result.denied_reason})"
        )
        print(
            "VERDICT: INCONCLUSIVE — the egress door did not permit/complete the "
            "fetch, so the live contract was not exercised. This is a probe-"
            "harness/transport condition, NOT proof the contract is intact."
        )
        return EXIT_INCONCLUSIVE
    print("  [axis] transport (egress door) : PASS (fetch completed)")

    # --- Auth axis: 200 vs 401/403. The #724 drift signature is a 401 here. ---
    if result.status != 200:
        drift = result.status in (401, 403)
        print(
            f"  [axis] auth accepted           : FAIL (HTTP {result.status})"
        )
        if drift:
            print(
                "VERDICT: CONTRACT DRIFT — the endpoint rejected the auth/request "
                "shape (this is exactly the #724 v0->v1 401 signature: verify the "
                "endpoint path, method, and Authorization scheme against the "
                "CURRENT Kagi API docs before go-live)."
            )
            return EXIT_DRIFT
        print(
            "VERDICT: INCONCLUSIVE — a non-200, non-auth HTTP status; the contract "
            "was not confirmed. See the status above."
        )
        return EXIT_INCONCLUSIVE
    print("  [axis] auth accepted           : PASS (HTTP 200)")

    # --- Schema axis: JSON dict -> data.search list -> adapter parser maps it. ---
    import json

    try:
        raw = json.loads(result.content_text)
    except (json.JSONDecodeError, ValueError):
        print("  [axis] response is JSON        : FAIL (body is not valid JSON)")
        print(
            "VERDICT: INCONCLUSIVE — HTTP 200 but the body did not parse as JSON; "
            "the response contract could not be checked."
        )
        return EXIT_INCONCLUSIVE
    if not isinstance(raw, dict):
        print("  [axis] response is JSON dict   : FAIL (top-level is not an object)")
        print("VERDICT: CONTRACT DRIFT — the v1 response is expected to be a JSON object.")
        return EXIT_DRIFT
    print("  [axis] response is JSON dict   : PASS")

    data = raw.get("data")
    search = data.get("search") if isinstance(data, dict) else None
    if not isinstance(search, list):
        print("  [axis] data.search is a list   : FAIL (missing or not a list)")
        print(
            "VERDICT: CONTRACT DRIFT — genuine results are expected under "
            "data.search (a list). The response schema diverged from the "
            "adapter's assumption."
        )
        return EXIT_DRIFT
    print(f"  [axis] data.search is a list   : PASS ({len(search)} entries)")

    # Run the response through the adapter's OWN SSOT parser (never a fork) to
    # prove the end-to-end mapping contract, not just the raw shape.
    parsed = _parse_v1_search(raw)
    if not parsed:
        print("  [axis] parser maps results     : FAIL (0 SearchResult produced)")
        print(
            "VERDICT: CONTRACT DRIFT — data.search entries did not yield any "
            "parseable result (each result object is expected to carry a usable "
            "'url'). The per-entry field contract diverged."
        )
        return EXIT_DRIFT
    print(f"  [axis] parser maps results     : PASS ({len(parsed)} SearchResult)")

    print("")
    print("VERDICT: CONTRACT VERIFIED — Kagi v1 auth + response schema match the "
          "adapter's live-contract assumptions.")
    return EXIT_VERIFIED


def main(argv: Optional[Sequence[str]] = None) -> int:
    """CLI entrypoint. Returns a process exit code (see module docstring).

    Importing this module and referencing ``main`` performs no network I/O; the
    network is touched only when ``main`` is invoked with ``--probe``.
    """
    parser = _build_parser()
    args = parser.parse_args(argv)
    if not args.probe:
        parser.print_help()
        print("")
        print(
            "Nothing fetched: pass --probe to run the live contract check "
            "(requires a provisioned Kagi API key)."
        )
        return EXIT_NO_CREDENTIAL
    return _run_probe(args.query)


if __name__ == "__main__":  # pragma: no cover - manual operator entrypoint
    sys.exit(main())
