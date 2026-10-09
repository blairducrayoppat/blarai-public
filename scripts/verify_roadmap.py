"""
BlarAI roadmap verifier — is the order still TRUE?
==================================================
The half of #1411 the offline gate cannot do.

`tests/security/test_roadmap_is_not_stale.py` checks the FORM of `docs/ROADMAP.md`: that the
block parses, that ranks are contiguous, that the vocabularies hold, that the refresh date
does not trail `main`. All of that can be true of a roadmap whose every entry points at work
that is already finished.

That is not hypothetical. On 2026-08-15 the operator was handed #1390 as a decision he needed
to make, and half of it had already been fixed and merged at 00:35 that same morning
(`5b86dda7`). The ticket was open, so the board said "open"; nobody had closed it. He was
being asked to decide something already partly built, and the reason the roadmap could say so
with a straight face is that nothing compared it against the board.

WHAT THIS CHECKS, against the LIVE Vikunja board:

  * every ticket cited in the roadmap still EXISTS;
  * every ticket cited is still OPEN — a closed one is the #1390 case and is reported as
    STALE, loudly, because it is the shape that wastes the operator's attention;
  * every row marked `needs-operator: yes` names a ticket (work only he can move, with no
    durable home, cannot reach him);
  * rows citing `-` are reported as UNTICKETED — not a failure, but named every run, because
    work with no ticket does not survive the session that thought of it.

WHY IT IS A SCRIPT AND NOT A GATE TEST. It needs the Vikunja server. The standing gate is
offline and deterministic by design, and giving it a service dependency would mean a gate that
fails when a local server is down — an alarm about nothing, which is how real alarms come to be
ignored (lesson 351). So this is run by a session, or by a scheduled job, and its output is
read by a person.

HONEST LIMIT, stated here rather than discovered later. This proves the roadmap does not point
at DEAD work. It cannot prove the order is RIGHT — that is a judgement about what matters and
it belongs to the operator. And it cannot see work that was never written down at all: a
roadmap is only as complete as the board behind it, the same limit `verify_disposition.py`
states about findings nobody recorded.

USAGE

    .venv/Scripts/python.exe scripts/verify_roadmap.py            # check the live board
    .venv/Scripts/python.exe scripts/verify_roadmap.py --offline  # form only, no server

Exit 0 = every cited ticket exists and is open. Exit 1 = at least one is stale or missing.
Exit 2 = the board could not be reached, which is reported as a failure to VERIFY rather than
as a pass — an unreachable board must never read as a clean bill of health.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
ROADMAP = _REPO / "docs" / "ROADMAP.md"

# Runnable as a bare script from anywhere, not only as `python -m`. Without this the
# credential-resolving import below fails with ModuleNotFoundError and the run reports
# "could not authenticate" — a true statement about the wrong cause, which is its own
# small dishonesty.
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

_BLOCK_RE = re.compile(r"```roadmap\n(.*?)```", re.DOTALL)
_VIKUNJA = "http://localhost:3456/api/v1"


def parse_rows(text: str) -> "list[dict]":
    """Every row of the machine-checkable block. Shared shape with the gate test; kept here
    rather than imported so this script runs standalone in a bare checkout."""
    m = _BLOCK_RE.search(text)
    if not m:
        return []
    out: list[dict] = []
    for line in m.group(1).splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = [p.strip() for p in line.split("|")]
        if len(parts) != 5:
            continue
        out.append({
            "rank": parts[0], "ticket": parts[1], "when": parts[2],
            "needs_operator": parts[3], "text": parts[4],
        })
    return out


def _client():
    """An authenticated client, built from the SAME credential source the MCP server and the
    fleet bridge already read (`VIKUNJA_URL` / `VIKUNJA_USER` / `VIKUNJA_PASS`, env then
    `.env`). Reused rather than reimplemented: a second auth path would be a second thing to
    keep in step, and this one already enforces the loopback-only rule."""
    from shared.fleet.vikunja_bridge import (  # noqa: PLC0415 — dev-tier import by design
        _VikunjaClient, _default_transport, _resolve_credentials, assert_loopback,
    )

    url, user, password = _resolve_credentials()
    assert_loopback(url)
    client = _VikunjaClient(url, user, password, transport=_default_transport())
    client.login()
    return client


def _fetch_task(client, task_id: int) -> "dict | None":
    """The task, `{"__missing__": True}` if the board says it does not exist, or a raise for
    anything else — the caller must be able to tell "closed" from "could not ask"."""
    try:
        return client._call("GET", f"/tasks/{task_id}")
    except RuntimeError as exc:
        if "404" in str(exc):
            return {"__missing__": True}
        raise


def main(argv: "list[str] | None" = None) -> int:
    ap = argparse.ArgumentParser(prog="verify_roadmap.py")
    ap.add_argument("--offline", action="store_true",
                    help="check the form only; do not contact the board")
    args = ap.parse_args(argv)

    if not ROADMAP.is_file():
        print(f"FAIL: {ROADMAP} does not exist — #1411 part (a) is missing")
        return 1

    rows = parse_rows(ROADMAP.read_text(encoding="utf-8", errors="replace"))
    if not rows:
        print("FAIL: no ```roadmap block found — there is nothing to verify")
        return 1

    print(f"roadmap rows: {len(rows)}")

    unticketed = [r for r in rows if r["ticket"] == "-"]
    for r in unticketed:
        print(f"  [UNTICKETED] rank {r['rank']}: {r['text'][:80]}")
    operator_rows = [r for r in rows if r["needs_operator"] == "yes"]
    print(f"  needs the operator: {len(operator_rows)} of {len(rows)}")

    bad_operator = [r for r in operator_rows if r["ticket"] == "-"]
    if bad_operator:
        for r in bad_operator:
            print(f"  [FAIL] rank {r['rank']} needs the operator but names no ticket — "
                  f"it cannot reach him")

    if args.offline:
        print("\n--offline: the board was NOT consulted, so nothing here says a cited "
              "ticket is still open.")
        return 1 if bad_operator else 0

    try:
        client = _client()
    except Exception as exc:  # noqa: BLE001
        print(f"\nFAIL: could not authenticate to the board ({type(exc).__name__}: {exc}).")
        print("Reported as a failure to VERIFY, not as a pass. Credentials come from "
              "VIKUNJA_URL / VIKUNJA_USER / VIKUNJA_PASS (env, then .env) — the same source "
              "the MCP server reads.")
        return 2

    stale: list[str] = []
    missing: list[str] = []
    checked = 0
    for r in rows:
        if r["ticket"] == "-":
            continue
        tid = int(r["ticket"].lstrip("#"))
        try:
            task = _fetch_task(client, tid)
        except Exception as exc:  # noqa: BLE001
            print(f"\nFAIL: could not reach the board ({type(exc).__name__}: {exc}).")
            print("Reported as a failure to VERIFY, not as a pass — an unreachable board is "
                  "not a clean bill of health. Start the server "
                  "(devplatform/tools/vikunja/...) and re-run.")
            return 2
        checked += 1
        if task is None or task.get("__missing__"):
            missing.append(f"rank {r['rank']}: {r['ticket']} does not exist")
        elif task.get("done"):
            stale.append(
                f"rank {r['rank']}: {r['ticket']} is CLOSED — {str(task.get('title',''))[:70]}"
            )

    print(f"\nchecked against the live board: {checked}")
    for s in stale:
        print(f"  [STALE] {s}")
    for m in missing:
        print(f"  [MISSING] {m}")

    if stale or missing or bad_operator:
        print(
            f"\nRESULT: FAIL — {len(stale)} stale / {len(missing)} missing / "
            f"{len(bad_operator)} unreachable-operator of {len(rows)} rows."
        )
        print("A roadmap pointing at finished work is the #1390 case: the operator is asked "
              "to decide something already built. Re-measure the order; do not just delete "
              "the row.")
        return 1

    print(f"\nRESULT: PASS — {checked} cited tickets all exist and are open; "
          f"{len(unticketed)} row(s) deliberately unticketed.")
    print("NOTE: this says the roadmap does not point at DEAD work. It does not say the "
          "ORDER is right — that judgement is the operator's.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
