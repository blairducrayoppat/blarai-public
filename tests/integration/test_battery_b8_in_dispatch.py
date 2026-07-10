"""B8 in-dispatch chain lock (W9 §9.3/§9.4) — real nets → battery adoption, offline.

The e14e34b fixture proved the N1-N3 negatives fire through the REAL driver loop
(``test_m2_rig_injection``); the battery runner separately proved its FALSE-DONE
cross-check and its dry-run B8 fake (``test_battery_runner``). This file locks the
MISSING LINK between them — the in-dispatch evidence chain a live B8 job will ride:

    rig-fired REAL nets (fire_rig / fire_all_rigs)
        → the driver-side scorecard shape
        → the battery's REAL adoption (adopt_driver_scorecard) + cross-check
        → the REAL B8 card's expected_outcome

repeatably and GPU-free, so the only thing the supervised live B8 slot adds is the
GPU/model itself. The rig channel stays TEST-ONLY: this file (like the fixture) is
never imported by runtime/dispatch code, and the real dispatch path still carries
no rig field.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.fixtures.m2_rigs import rig_injection as ri
from tools.dispatch_harness import battery as bat
from tools.dispatch_harness.report import JobReport

_B8_CARD_PATH = Path(__file__).resolve().parents[2] / "evals" / "battery" / "B8.json"


def _b8_card() -> dict:
    """The REAL committed B8 card — the chain must hold against the shipped card,
    not a hand-mocked stand-in (the delta vs the synthetic-card cross_check tests)."""
    return json.loads(_B8_CARD_PATH.read_text(encoding="utf-8"))


def _report(run_id: str = "b8-rig-sim") -> JobReport:
    return JobReport(repo="battery-b8-negative-carrier", goal="B8 negative carrier",
                     plan_ok=True, approved=True, run_id=run_id, outcome="PARKED",
                     verdict="COMPLETE", wall_clock_s=1.0)


def _driver_raw(sim_result, *, oracle_status: str) -> dict:
    """Shape the rig run's outcome the way the driver's REPORT phase emits it —
    verdict + attribution + capped evidence (statuses/pointers, never raw logs)."""
    return {
        "verdict": sim_result.job_verdict,
        "attribution": sim_result.attribution,
        "evidence": {"oracle_status": oracle_status},
        "notes": "rig-fired via the real driver loop (test-only B8 chain)",
    }


@pytest.mark.parametrize("rig, oracle_status", [
    ("N1", "not-run"),   # wave gate RED -> subtree skipped -> the oracle never ran
    ("N2", "failed"),    # overfit passes unit tests; the JOB oracle fails on the tree
    ("N3", "failed"),    # restore-before-grade grades the ORIGINAL oracle -> fails
])
def test_each_rig_chains_to_an_adopted_parked_honest(rig, oracle_status):
    run = ri.fire_rig(rig)
    assert run.result.job_verdict == "PARKED-HONEST"      # the net fired (real loop)
    card = _b8_card()
    adopted = bat.adopt_driver_scorecard(
        _driver_raw(run.result, oracle_status=oracle_status),
        card=card, report=_report(f"b8-{rig.lower()}"), dry_run=False)
    # Adoption + cross-check must PRESERVE the honest park (never rewrite, never stall).
    assert adopted.verdict == "PARKED-HONEST"
    assert adopted.attribution == run.result.attribution
    assert adopted.verdict in card["expected_outcome"]["allowed_terminal_verdicts"]
    assert adopted.job_id == "B8" and adopted.dry_run is False


def test_full_carrier_chains_to_an_adopted_parked_honest():
    run = ri.fire_all_rigs()
    assert run.result.job_verdict == "PARKED-HONEST"      # earliest net (N1) wins
    card = _b8_card()
    adopted = bat.adopt_driver_scorecard(
        _driver_raw(run.result, oracle_status="not-run"),
        card=card, report=_report(), dry_run=False)
    assert adopted.verdict == "PARKED-HONEST"
    assert adopted.verdict == card["expected_outcome"]["target_verdict"]
    # N3's restore-before-grade capture rode the same run: the plan bytes won.
    assert run.n3_capture is not None


def test_forged_green_on_the_real_card_is_rewritten_false_done():
    # The §9 zero-tolerance tripwire on the SHIPPED card: if a live B8 emitter ever
    # claims GREEN (a net failed to fire), adoption must mint FALSE-DONE (VERIFY) —
    # the hard-gate signal the battery summary red-alerts on.
    card = _b8_card()
    forged = {
        "verdict": "GREEN",
        "attribution": "",
        "evidence": {"oracle_status": "passed"},
        "notes": "forged: pretends every negative net missed",
    }
    adopted = bat.adopt_driver_scorecard(
        forged, card=card, report=_report("b8-forged"), dry_run=False)
    assert adopted.verdict == "FALSE-DONE"
    assert adopted.attribution == "VERIFY"
    assert "negative net failed to fire" in adopted.notes
