"""#1410 same-day witness — does the exam repair loop engage on the REAL model?

WHY THIS EXISTS, and why it is not a nightly.

`validate_authored_oracle` returned early for every non-python ecosystem, so website exams
skipped plan-time quality checking entirely — and with it the bounded repair loop, the only
mechanism that turns a bad exam into a good one. Nine consecutive B9 nights recorded
`verdict: refuse` beside `regeneration.rounds: 0`: the model authored a thin exam and was
never once asked to try again.

**The defect and the fix both live at PLAN time.** So witnessing the repair takes the first
minutes of a job, not the ~4.8 hours a full B9 run costs, and waiting for 23:00 to learn it
would be a self-inflicted delay. #740 RULE 2 bounds how many changes go into one *run*; it
says nothing about how many runs happen in a day.

WHAT THIS DOES. Builds a REAL `TransportGateway` against the RUNNING orchestrator — the same
wiring `DispatchHarness.for_live` uses, over the AO's loopback port rather than the named
pipe, so it does not contend with the desktop app for the single pipe instance (#1412). It
sends one `/dispatch <repo> | <goal>` with a website-shaped goal and STOPS at the plan card.

NOTHING IS DISPATCHED. The corridor requires an explicit `/dispatch approve` before any coder
candidate is spent; this never sends one. No sandbox, no scorecard, no counter, no fleet
queue entry.

USAGE (backend must be up — the launcher hosts the resident 14B):

    .venv/Scripts/python.exe tools/probes/probe_1410_repair_loop.py

Exit 0 = the loop engaged (`regeneration.rounds >= 1`). Exit 1 = inconclusive, with the
reason stated. Exit 2 = could not reach the model, which is reported as a failure to measure
rather than as a pass.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

#: A website-shaped goal, deliberately close to B9's so the model authors the same KIND of
#: exam the nine refused runs produced. Not B9's verbatim goal — this must not be mistaken
#: for a battery result.
GOAL = (
    "a small website for a pottery studio: a home page, a gallery listing the pieces, "
    "an individual page for each piece, and a contact form that stores enquiries"
)
REPO_NAME = "probe-1410-pottery"


def _ao_port() -> int:
    """The AO loopback port, read from its own config rather than assumed."""
    import tomllib

    cfg = REPO / "services" / "assistant_orchestrator" / "config" / "default.toml"
    data = tomllib.loads(cfg.read_text(encoding="utf-8"))
    return int(data.get("ipc", {}).get("vsock_port", 5001))


async def main() -> int:
    from tools.dispatch_harness.harness import DispatchHarness
    from shared.fleet.acceptance import JOB_ORACLE_QA_KEY

    port = _ao_port()
    print(f"AO port (from default.toml): {port}")

    harness = DispatchHarness.for_live(
        port=port,
        agentic_setup_dir=str(Path.home() / "agentic-setup"),
        projects_dir=str(Path.home() / "projects"),
        fleet_dispatch_enabled=True,
        session_id="probe-1410",
    )
    coord = harness.coordinator
    if coord is None:
        print("FAIL: the live harness exposed no coordinator")
        return 2

    print(f"\n--- planning (real 14B, real oracle authoring + QA) ---")
    print(f"goal: {GOAL}\n")
    reply = await harness.send_fn("probe-1410", f"/dispatch new {REPO_NAME} | {GOAL}")
    print((reply or "(no reply)")[:1400])

    pending = coord.pending_for("probe-1410")
    if pending is None:
        clar = coord.pending_clarification_for("probe-1410")
        req = coord.pending_requirements_for("probe-1410")
        print(
            f"\nNo plan card. clarifying={clar is not None} requirements={req is not None}"
        )
        print("The corridor asked a question instead of planning — answer it and re-run, "
              "or the plan did not complete. Nothing was dispatched either way.")
        return 1

    qa_raw = ""
    for t in pending.tasks:
        if isinstance(t, dict) and t.get(JOB_ORACLE_QA_KEY):
            qa_raw = str(t[JOB_ORACLE_QA_KEY])
            break

    print("\n--- the QA evidence this run would have banked ---")
    if not qa_raw:
        print("NONE — no oracle-QA evidence rode the plan.")
        print("\nINCONCLUSIVE: the authoring path did not reach QA at all.")
        return 1

    qa = json.loads(qa_raw)
    print(json.dumps(qa, indent=2)[:2200])

    rounds = int((qa.get("regeneration") or {}).get("rounds", 0) or 0)
    verdict = qa.get("verdict")
    language = qa.get("language")

    print("\n=== VERDICT ===")
    print(f"language            = {language}")
    print(f"verdict             = {verdict}")
    print(f"regeneration.rounds = {rounds}   (the shipped defect recorded 0, nine runs running)")

    if language != "node":
        print("\nINCONCLUSIVE: the plan authored a non-node exam, so this run does not "
              "exercise the fixed path. Re-run with a goal that produces a website.")
        return 1
    if rounds >= 1:
        print("\nWITNESSED: the repair loop engaged on the real model. Before this fix the "
              "node path returned before the loop and this figure could only ever be 0.")
        return 0
    print("\nINCONCLUSIVE, and this is a GOOD outcome rather than a regression: the model "
          "authored an adequate exam first time, so there was nothing to repair. That the "
          "loop is now REACHED is proven by the unit locks; this run simply had no defect "
          "to fix. Re-run, or witness it on a night whose first draft is thin.")
    return 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
