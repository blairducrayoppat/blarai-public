"""F4 (#752) — the flat-queue REPORT-phase seam (the "W6 REPORT-phase seam").

When a dispatch job degrades to the legacy flat task queue (``SwapDriver`` built with
``plan=None`` — e.g. B2, whose diamond collapsed to one task), the driver's REPORT phase
must STILL emit a ``state/fleet-runs/<RunId>/scorecard.json`` so the battery adopts a real
job verdict instead of synthesizing ``STALLED [HARNESS]`` ("no driver scorecard … W6
REPORT-phase seam pending").

These tests lock the two new pure functions (``compute_flat_verdict`` /
``build_flat_scorecard``) and the ``_emit_plan_artifacts`` flat branch, including the
load-bearing anti-FALSE-DONE property: **flat mode can never return GREEN** (a flat run
has no job oracle to prove the integrated whole). Every external effect rides the injected
``SwapOps`` seams, so this runs model-free and GPU-free.
"""

from __future__ import annotations

import pytest

from shared.fleet import swap_driver as sd
from shared.fleet.dispatch import TaskOutcome

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


def _outcome(task: str, result: str) -> TaskOutcome:
    return TaskOutcome(task=task, outcome="processed", result=result,
                       detail=f"RESULT: {result}")


def _min_ops(calls: list, **overrides) -> sd.SwapOps:
    """A recording ``SwapOps`` with every required seam wired to a no-op/success, so a
    flat ``SwapDriver`` can ``run()`` end to end model-free. ``write_scorecard`` /
    ``write_job_summary`` record into ``calls`` so the emitted artifacts can be inspected."""
    base = dict(
        available_gb=lambda: 26.0,
        backend_alive=lambda: False,
        load_30b=lambda: True,
        wait_ready=lambda: True,
        run_task=lambda t: (calls.append(("task", t["task"])), _outcome(t["task"], "MERGED"))[1],
        cancel_requested=lambda: False,
        disarm_watchdog=lambda: None,
        stop_ovms=lambda: None,
        write_report=lambda rid, outs: calls.append(("report", rid, len(outs))),
        restart_launcher=lambda: calls.append("restart"),
        backend_ready=lambda: True,
        signal_failure=lambda msg: calls.append(("signal", msg)),
        write_scorecard=lambda sc: calls.append(("scorecard", sc)),
        write_job_summary=lambda text: calls.append(("job_summary", text)),
    )
    base.update(overrides)
    return sd.SwapOps(**base)


def _flat_driver(tmp_path, ops, tasks, **kw) -> sd.SwapDriver:
    """A FLAT-mode driver (``plan=None`` — the legacy queue)."""
    return sd.SwapDriver(
        run_id="R-FLAT", session_id="s1", tasks=tasks,
        swap_state_path=tmp_path / "swap.json", ops=ops,
        gate_gb=20.0, sleep=lambda _s: None, **kw,
    )


def _scorecard(calls: list) -> dict:
    for c in calls:
        if isinstance(c, tuple) and c[0] == "scorecard":
            return c[1]
    raise AssertionError("no scorecard emitted")


def _job_summary(calls: list) -> str:
    for c in calls:
        if isinstance(c, tuple) and c[0] == "job_summary":
            return c[1]
    raise AssertionError("no job summary emitted")


# ---------------------------------------------------------------------------
# compute_flat_verdict (pure) — every branch, ESPECIALLY the anti-false-done lock
# ---------------------------------------------------------------------------


def test_flat_verdict_all_merged_is_stalled_verify_never_green():
    """THE anti-FALSE-DONE lock: an all-merged flat run has NO job oracle to prove the
    integrated whole, so it must be STALLED (VERIFY) — NEVER GREEN. Merged-but-
    unverifiable is exactly the FALSE-DONE class; flat mode cannot emit GREEN."""
    outcomes = [_outcome("a", "MERGED"), _outcome("b", "MERGED")]
    verdict, attribution = sd.compute_flat_verdict(outcomes, cancelled=False, stopped=False)
    assert verdict == sd.VERDICT_STALLED
    assert attribution == sd.ATTRIBUTION_VERIFY
    assert verdict != sd.VERDICT_GREEN


def test_flat_verdict_one_not_merged_is_parked_honest_build():
    """B2's case: a task parked / failed its gate / was skipped-because-unmerged is an
    honest RED — PARKED-HONEST (BUILD)."""
    for red in ("PARKED", "BLOCKED", "NOTHING", "UNKNOWN", "SKIPPED"):
        outcomes = [_outcome("a", "MERGED"), _outcome("b", red)]
        verdict, attribution = sd.compute_flat_verdict(outcomes, cancelled=False, stopped=False)
        assert verdict == sd.VERDICT_PARKED_HONEST, red
        assert attribution == sd.ATTRIBUTION_BUILD, red


def test_flat_verdict_empty_is_stalled_harness():
    """Nothing ran (a settle/gate/load abort before the first task): STALLED (HARNESS)."""
    verdict, attribution = sd.compute_flat_verdict([], cancelled=False, stopped=False)
    assert verdict == sd.VERDICT_STALLED
    assert attribution == sd.ATTRIBUTION_HARNESS


def test_flat_verdict_cancelled_is_parked_honest_harness():
    """Operator cancel with work done: PARKED-HONEST (HARNESS) — a refusal with
    evidence, externally stopped (the interventions counter carries the operator signal)."""
    outcomes = [_outcome("a", "MERGED")]
    verdict, attribution = sd.compute_flat_verdict(outcomes, cancelled=True, stopped=False)
    assert verdict == sd.VERDICT_PARKED_HONEST
    assert attribution == sd.ATTRIBUTION_HARNESS


def test_flat_verdict_stopped_is_stalled_harness():
    """The out-of-band budget watchdog fired: STALLED (HARNESS) — could-not-finish. Stop
    dominates even an all-merged outcome set (the run was externally killed)."""
    outcomes = [_outcome("a", "MERGED")]
    verdict, attribution = sd.compute_flat_verdict(outcomes, cancelled=False, stopped=True)
    assert verdict == sd.VERDICT_STALLED
    assert attribution == sd.ATTRIBUTION_HARNESS


def test_flat_verdict_stopped_dominates_cancelled():
    """Precedence: stopped is checked before cancelled (mirrors compute_job_verdict)."""
    outcomes = [_outcome("a", "MERGED")]
    assert sd.compute_flat_verdict(outcomes, cancelled=True, stopped=True) == (
        sd.VERDICT_STALLED, sd.ATTRIBUTION_HARNESS)


# ---------------------------------------------------------------------------
# build_flat_scorecard — shape parity with build_scorecard + adoption vocab
# ---------------------------------------------------------------------------


def test_flat_scorecard_has_same_keys_as_plan_scorecard(tmp_path):
    """The flat card is the plan card's structural twin: same m2-scorecard/v1 keys, so
    the battery's adopt_driver_scorecard reads it identically."""
    # #790: a representative per-task best-of-N log (new-agent-task.ps1's exact line
    # shape) so samples_consumed recovers a REAL value via run_dir instead of the -1
    # default — see test_flat_scorecard_samples_consumed_fallback_when_no_run_dir
    # below for the absent-signal honesty contract, and test_integration_gate.py's
    # test_samples_consumed_from_run_dir_* for the focused parser/summing locks.
    (tmp_path / "run-fleet-a.log").write_text(
        "  Best-of-N: 2 candidate(s) -> no candidate passed; kept the best of 2 by gate rank.\n"
        "RESULT: MERGED to main\n",
        encoding="utf-8",
    )
    sc = sd.build_flat_scorecard(
        [_outcome("a", "MERGED")], run_id="R-FLAT", repo="battery-x", goal="g",
        wall_clock_s=1.5, cancelled=False, stopped=False, degraded=False,
        run_dir=tmp_path,
    )
    assert sc["schema"] == sd.SCORECARD_SCHEMA
    for key in ("run_id", "plan_id", "goal", "repo", "verdict", "attribution",
                "cancelled", "degraded", "wall_clock_s", "tasks", "waves",
                "job_acceptance", "packs_consumed", "samples_consumed",
                "interventions", "redecompose_spent", "not_measured", "notes",
                "evidence"):
        assert key in sc, f"flat scorecard missing {key}"
    # Adoption conventions: oracle_status is not-run (no oracle); waves empty;
    # job_acceptance not-run (flat mode grades no integrated whole).
    # #790: samples_consumed is RECOVERED (run_dir was supplied above) — measured
    # this time, so it drops out of not_measured too.
    assert sc["samples_consumed"] == 2
    assert "samples_consumed" not in sc["not_measured"]
    assert sc["waves"] == []
    assert sc["job_acceptance"] == {"status": "not-run", "oracle_path": "", "evidence": ""}
    assert sc["evidence"]["oracle_status"] == "not-run"
    # #789: a flat run is marked mode "flat" so the battery segments it OUT of the
    # plan-graph GREEN-rate denominator (structurally non-GREEN; measurement fairness).
    assert sc["evidence"]["mode"] == "flat"
    assert sc["tasks"] == [{"id": "a", "status": "", "result": "MERGED",
                            "detail": "RESULT: MERGED"}]


def test_flat_scorecard_samples_consumed_fallback_when_no_run_dir():
    """#790 honesty contract: no run_dir supplied (the byte-identical default for
    every caller that predates this feature) -> samples_consumed stays -1 ("not
    instrumented") and is named in not_measured. This is the exact assertion
    test_flat_scorecard_has_same_keys_as_plan_scorecard carried before run_dir
    existed, now isolated under its own name."""
    sc = sd.build_flat_scorecard(
        [_outcome("a", "MERGED")], run_id="R-FLAT", repo="battery-x", goal="g",
        wall_clock_s=1.5, cancelled=False, stopped=False, degraded=False,
    )
    assert sc["samples_consumed"] == -1
    assert "samples_consumed" in sc["not_measured"]


def test_flat_scorecard_interventions_and_cancelled_flags():
    sc = sd.build_flat_scorecard(
        [_outcome("a", "MERGED")], run_id="R", repo="battery-x", goal="g",
        wall_clock_s=0.0, cancelled=True, stopped=False, degraded=True,
    )
    assert sc["cancelled"] is True
    assert sc["degraded"] is True
    assert sc["interventions"] == 1
    assert sc["verdict"] == sd.VERDICT_PARKED_HONEST and sc["attribution"] == sd.ATTRIBUTION_HARNESS


def test_flat_scorecard_all_string_values_single_line():
    """S6: every string value must be single-line (the adopter's validate rejects \\r/\\n)."""
    sc = sd.build_flat_scorecard(
        [_outcome("a", "PARKED")], run_id="R", repo="battery-x", goal="g",
        wall_clock_s=1.0, cancelled=False, stopped=False, degraded=False,
    )

    def _check(v):
        if isinstance(v, str):
            assert "\n" not in v and "\r" not in v, repr(v)
        elif isinstance(v, dict):
            for x in v.values():
                _check(x)
        elif isinstance(v, list):
            for x in v:
                _check(x)

    _check(sc)


def test_flat_scorecard_never_green_all_merged():
    """The build path enforces the same lock as the verdict fn: all-merged ⇒ STALLED/VERIFY."""
    sc = sd.build_flat_scorecard(
        [_outcome("a", "MERGED"), _outcome("b", "MERGED")], run_id="R", repo="battery-x",
        goal="g", wall_clock_s=1.0, cancelled=False, stopped=False, degraded=False,
    )
    assert sc["verdict"] == sd.VERDICT_STALLED and sc["attribution"] == sd.ATTRIBUTION_VERIFY
    assert sc["verdict"] != sd.VERDICT_GREEN


def test_flat_scorecard_renders_a_job_summary():
    """render_job_summary must work on the flat scorecard shape (no plan-only key deref)."""
    sc = sd.build_flat_scorecard(
        [_outcome("a", "PARKED")], run_id="R-FLAT", repo="battery-x", goal="ship it",
        wall_clock_s=1.0, cancelled=False, stopped=False, degraded=False,
    )
    text = sd.render_job_summary(sc)
    assert "verdict: PARKED-HONEST (attribution: BUILD)" in text
    assert "JOB R-FLAT — ship it" in text
    # Must never collide with dispatch.parse_summary's task-line shape.
    from shared.fleet.dispatch import parse_summary

    assert parse_summary(text) == []


# ---------------------------------------------------------------------------
# Adoption cross-lane lock — the flat card survives the REAL battery adopter
# ---------------------------------------------------------------------------


def _validate_as_battery(raw: dict, job_id: str = "B-flat") -> list[str]:
    """The flat DRIVER card carries the driver schema (``m2-scorecard/v1``) and no
    ``job_id`` by design — the battery stamps its own (``battery-scorecard/v1`` + job_id)
    during adoption (``_base_fields``). Mirror that single overlay so
    ``scorecard.validate`` exercises every OTHER structural rule on the flat card
    (attribution-required-on-non-GREEN, oracle_status vocab, single-line notes, the
    -1 conventions…)."""
    from tools.dispatch_harness import scorecard as bscorecard

    merged = {**raw, "schema": bscorecard.SCORECARD_SCHEMA, "job_id": job_id}
    return bscorecard.validate(merged)


def test_flat_scorecard_validates_against_battery_scorecard_validate():
    for outcomes in ([_outcome("a", "MERGED")], [_outcome("a", "PARKED")], []):
        sc = sd.build_flat_scorecard(
            outcomes, run_id="R", repo="battery-x", goal="g",
            wall_clock_s=1.0, cancelled=False, stopped=False, degraded=False,
        )
        assert _validate_as_battery(sc) == [], sc


def test_flat_all_merged_adopts_as_stalled_verify():
    """all-merged flat card ⇒ the battery adopts STALLED/VERIFY (NOT synthesized, NOT
    degraded to 'invalid'). This is the seam F4 closes: a real verdict, not STALLED[HARNESS]
    from synthesize_scorecard."""
    battery = pytest.importorskip("tools.dispatch_harness.battery")
    from tools.dispatch_harness.report import JobReport

    raw = sd.build_flat_scorecard(
        [_outcome("a", "MERGED")], run_id="R-FLAT", repo="battery-b2", goal="g",
        wall_clock_s=1.0, cancelled=False, stopped=False, degraded=False,
    )
    card = {"id": "B2", "repo": "battery-b2",
            "expected_outcome": {"oracle": {"expected": True}}, "rigs": []}
    report = JobReport(repo="battery-b2", goal="g", run_id="R-FLAT", wall_clock_s=1.0)
    adopted = battery.adopt_driver_scorecard(raw, card=card, report=report, dry_run=False)
    assert adopted.verdict == "STALLED" and adopted.attribution == "VERIFY", adopted.notes
    assert "invalid" not in adopted.notes
    assert adopted.schema == "battery-scorecard/v1"


def test_flat_parked_adopts_as_parked_honest_build():
    """B2's degraded-diamond RED: one task didn't merge ⇒ the battery adopts
    PARKED-HONEST/BUILD (an honest verification success, attribution intact)."""
    battery = pytest.importorskip("tools.dispatch_harness.battery")
    from tools.dispatch_harness.report import JobReport

    raw = sd.build_flat_scorecard(
        [_outcome("a", "MERGED"), _outcome("b", "PARKED")], run_id="R-FLAT",
        repo="battery-b2", goal="g", wall_clock_s=1.0, cancelled=False, stopped=False,
        degraded=True,
    )
    card = {"id": "B2", "repo": "battery-b2",
            "expected_outcome": {"oracle": {"expected": True}}, "rigs": []}
    report = JobReport(repo="battery-b2", goal="g", run_id="R-FLAT", wall_clock_s=1.0)
    adopted = battery.adopt_driver_scorecard(raw, card=card, report=report, dry_run=False)
    assert adopted.verdict == "PARKED-HONEST" and adopted.attribution == "BUILD", adopted.notes
    assert "invalid" not in adopted.notes
    # The adopted battery card is itself structurally valid (the real published artifact).
    from tools.dispatch_harness import scorecard as bscorecard

    assert bscorecard.validate(adopted.to_dict()) == []


# ---------------------------------------------------------------------------
# _emit_plan_artifacts (flat branch) — the smallest driver seam
# ---------------------------------------------------------------------------


def test_emit_plan_artifacts_flat_writes_scorecard_and_summary(tmp_path):
    """Drive the REAL SwapDriver._emit_plan_artifacts in FLAT mode (plan=None) with a
    recording fake: a scorecard IS written (was NOT before F4), through the same injected
    seams, and it adopts cleanly."""
    battery = pytest.importorskip("tools.dispatch_harness.battery")
    from tools.dispatch_harness.report import JobReport

    calls: list = []
    ops = _min_ops(calls)
    driver = _flat_driver(tmp_path, ops, [{"repo": "battery-b2", "task": "a", "prompt": "pa"}])
    assert driver._plan is None  # FLAT mode
    outcomes = [_outcome("a", "MERGED")]
    driver._emit_plan_artifacts(outcomes)

    sc = _scorecard(calls)                       # a scorecard WAS written
    assert sc["schema"] == sd.SCORECARD_SCHEMA
    assert sc["run_id"] == "R-FLAT"
    assert sc["repo"] == "battery-b2"
    assert sc["verdict"] == "STALLED" and sc["attribution"] == "VERIFY"
    assert _validate_as_battery(sc) == []
    assert "verdict: STALLED" in _job_summary(calls)

    card = {"id": "B2", "repo": "battery-b2",
            "expected_outcome": {"oracle": {"expected": True}}, "rigs": []}
    report = JobReport(repo="battery-b2", goal="g", run_id="R-FLAT", wall_clock_s=1.0)
    adopted = battery.adopt_driver_scorecard(sc, card=card, report=report, dry_run=False)
    assert adopted.verdict == "STALLED" and adopted.attribution == "VERIFY"
    assert "invalid" not in adopted.notes


def test_flat_run_end_to_end_emits_parked_honest_on_unmerged(tmp_path):
    """Full flat .run(): a task that doesn't merge yields a REPORT-phase PARKED-HONEST/
    BUILD scorecard — the B2 case. Proves the flat CODE loop records state + the teardown
    REPORT phase fires."""
    calls: list = []
    ops = _min_ops(calls, run_task=lambda t: _outcome(t["task"], "PARKED"))
    result = _flat_driver(tmp_path, ops, [{"repo": "battery-b2", "task": "a", "prompt": "pa"}]).run()
    assert result.outcome == "complete"
    sc = _scorecard(calls)
    assert sc["verdict"] == "PARKED-HONEST" and sc["attribution"] == "BUILD"
    assert sc["cancelled"] is False
    assert _validate_as_battery(sc) == []


def test_flat_run_end_to_end_cancel_after_a_task_is_parked_honest_harness(tmp_path):
    """Full flat .run() with an operator cancel AFTER the first task merged: the flat loop
    records cancelled onto self, and the REPORT phase emits PARKED-HONEST/HARNESS with
    interventions=1 (the operator signal). Two tasks so a MERGE lands before the cancel —
    a cancel BEFORE any task runs is honestly STALLED/HARNESS (nothing built), covered by
    test_flat_verdict_empty_is_stalled_harness."""
    calls: list = []
    cancels = iter([False, True])  # run task a, then cancel at the second boundary
    ops = _min_ops(calls, cancel_requested=lambda: next(cancels, True))
    tasks = [{"repo": "battery-b2", "task": "a", "prompt": "pa"},
             {"repo": "battery-b2", "task": "b", "prompt": "pb"}]
    result = _flat_driver(tmp_path, ops, tasks).run()
    assert result.cancelled is True
    sc = _scorecard(calls)
    assert sc["verdict"] == "PARKED-HONEST" and sc["attribution"] == "HARNESS"
    assert sc["cancelled"] is True and sc["interventions"] == 1


def test_flat_run_end_to_end_cancel_before_any_task_is_stalled_harness(tmp_path):
    """A cancel at the FIRST boundary (nothing ran) is honestly STALLED/HARNESS — the
    empty-outcomes check dominates cancelled (nothing was built to park)."""
    calls: list = []
    ops = _min_ops(calls, cancel_requested=lambda: True)
    result = _flat_driver(tmp_path, ops, [{"repo": "battery-b2", "task": "a", "prompt": "pa"}]).run()
    assert result.cancelled is True
    sc = _scorecard(calls)
    assert sc["verdict"] == "STALLED" and sc["attribution"] == "HARNESS"
    assert sc["cancelled"] is True and sc["interventions"] == 1


def test_flat_run_end_to_end_all_merged_is_stalled_verify_not_green(tmp_path):
    """The end-to-end anti-FALSE-DONE lock: a flat run where everything merges is STALLED/
    VERIFY (no job oracle to prove the whole), NEVER GREEN."""
    calls: list = []
    ops = _min_ops(calls)  # default run_task returns MERGED
    result = _flat_driver(tmp_path, ops, [{"repo": "battery-b2", "task": "a", "prompt": "pa"}]).run()
    assert result.outcome == "complete"
    sc = _scorecard(calls)
    assert sc["verdict"] == "STALLED" and sc["attribution"] == "VERIFY"
    assert sc["verdict"] != "GREEN"
