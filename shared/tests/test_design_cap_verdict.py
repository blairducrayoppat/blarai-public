"""#740 c.1710 + c.1717 (LA decisions 2026-07-11) — design-review verdict re-class.

c.1710: a design-review-ITERATION-CAP ending on an otherwise-VALID run — the coder
built, the design reviewer reviewed, fix iterations ran, the cap was reached —
classifies **PARKED-HONEST [VERIFY]** (an honest, MEASURED capability failure).
c.1717 extends the ruling symmetrically: a CLEAN design-review ending (a REAL
critique ran and the reviewer was satisfied) on an all-merged run reclasses
PARKED-HONEST [VERIFY] the same way, in BOTH merged-but-unverifiable terminals.
**STALLED stays reserved for harness/run-invalid classes** (crashes, budget
tree-kills, wedges — runs whose measurements can't be trusted): the campaign's
zero-STALLED banking rule exists to keep harness malfunctions out of reliability
data, and on night-20260711 it blocked a pass over B5's VALID measured outcome
(run 20260711-034818-bd logged "Design-review iteration cap reached -- the
operator judges the final look." then "JOB verdict: STALLED (attribution:
VERIFY) (flat-queue mode)").

Locks:
  * the exact B5 shape end-to-end (flat queue, all merged, design cap reached)
    => a PARKED-HONEST [VERIFY] scorecard with the machine-auditable cap trail;
  * the c.1717 clean twin end-to-end (real satisfied review, ``ok=True``) =>
    PARKED-HONEST [VERIFY] with ``evidence.design_review = "clean"``;
  * an UNAVAILABLE critique (the noop/fallback ``ok=False``) is NOT a measured
    ending — the all-merged terminals stay STALLED [VERIFY] (dormant-safety);
    a reviewer-NOT-satisfied non-iterate ending and a mid-loop reload failure
    reclass nothing either;
  * genuine harness-stall shapes STAY STALLED (budget stop dominates; nothing-ran
    stays STALLED [HARNESS]; a crashed no-scorecard job synthesizes
    STALLED [HARNESS]);
  * the never-GREEN locks hold through the re-class (flat can't GREEN; a design
    ending can neither mint nor demote a plan-mode GREEN);
  * the battery banking rule: a pass whose PARKED-HONEST came from a design
    ending BANKS (summary exit 0 — run-battery-night.ps1 banks on
    runnerExit -eq 0), one containing a true STALLED does not (exit 1).

Every external effect rides the injected ``SwapOps`` seams — model-free, GPU-free.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from shared.fleet import plan_graph as pg
from shared.fleet import swap_driver as sd
from shared.fleet.dispatch import TaskOutcome

# ---------------------------------------------------------------------------
# Helpers (self-contained, mirroring test_flat_scorecard / test_failure_policy)
# ---------------------------------------------------------------------------


def _outcome(task: str, result: str) -> TaskOutcome:
    return TaskOutcome(task=task, outcome="processed", result=result,
                       detail=f"RESULT: {result}")


def _min_ops(calls: list, **overrides) -> sd.SwapOps:
    """A recording ``SwapOps`` with every required seam wired to a no-op/success so a
    flat ``SwapDriver`` can ``run()`` end to end model-free. ``write_progress`` records
    the operator trail (the exact B5 log-shape assertions read it)."""
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
        write_progress=lambda msg: calls.append(("progress", msg)),
    )
    base.update(overrides)
    return sd.SwapOps(**base)


#: A B5-like flat task: a VISUAL surface with real visual criteria, so the driver's
#: ``_design_target`` selects it and the end-of-run VLM design loop actually runs.
_B5_TASK = {
    "repo": "battery-b5-habit-web", "task": "habit-tracker", "prompt": "build it",
    "surface": "web", "visual_criteria_json": '["chart renders", "tick-list visible"]',
    "goal": "habit tracker with chart",
}


def _iterating_design_loop(_app_dir: str, _goal: str, _vcj: str) -> dict:
    """A design reviewer that ALWAYS requests another lap — with the default cap of 2
    this is exactly B5's night-20260711 ending: critique -> fix -> re-critique -> CAP."""
    return {"should_iterate": True, "needs_work": True,
            "feedback": "the chart overlaps the tick-list", "layout_hard": False,
            "capture_tier": "web-headless", "ok": True}


def _satisfied_design_loop(_app_dir: str, _goal: str, _vcj: str) -> dict:
    """The c.1717 clean ending: a REAL critique ran (``ok=True`` — the flag every
    unavailable/fail-soft producer reports False) and the reviewer was satisfied."""
    return {"should_iterate": False, "needs_work": False,
            "feedback": "matches the visual criteria", "layout_hard": False,
            "capture_tier": "web-headless", "ok": True}


def _flat_driver(tmp_path: Path, ops: sd.SwapOps, tasks: list[dict], **kw) -> sd.SwapDriver:
    return sd.SwapDriver(
        run_id="R-B5", session_id="s1", tasks=tasks,
        swap_state_path=tmp_path / "swap.json", ops=ops,
        gate_gb=20.0, sleep=lambda _s: None, **kw,
    )


def _scorecard(calls: list) -> dict:
    for c in calls:
        if isinstance(c, tuple) and c[0] == "scorecard":
            return c[1]
    raise AssertionError("no scorecard emitted")


def _trail(calls: list) -> list[str]:
    return [c[1] for c in calls if isinstance(c, tuple) and c[0] == "progress"]


def _mk_repo(tmp_path: Path, name: str = "proj") -> Path:
    repo = tmp_path / name
    (repo / ".git").mkdir(parents=True, exist_ok=True)
    return repo


def _one_task_plan(tmp_path: Path) -> pg.JobPlan:
    repo = _mk_repo(tmp_path)
    raw = pg.build_plan_raw(plan_id="R1", goal="g", repo=str(repo),
                            tasks=[{"repo": str(repo), "task": "a", "prompt": "p",
                                    "depends_on": []}])
    result = pg.validate_plan(raw, projects_dir=tmp_path)
    assert result.ok and result.plan is not None
    return result.plan


def _all_merged(plan: pg.JobPlan) -> pg.JobPlan:
    for t in plan.tasks:
        plan = pg.mark_merged(pg.mark_building(pg.mark_ready(plan, t.id), t.id),
                              t.id, "RESULT: MERGED to main")
    return plan


def _merged_not_run_plan(tmp_path: Path) -> pg.JobPlan:
    """All merged + the oracle honestly stamped ``not-run`` (the live
    ``_run_job_acceptance`` always stamps before the design phase can run)."""
    return pg.mark_job_acceptance(_all_merged(_one_task_plan(tmp_path)),
                                  "not-run", "job oracle raised: missing")


# ---------------------------------------------------------------------------
# compute_flat_verdict — the exact classification site that graded B5 (pure)
# ---------------------------------------------------------------------------


def test_flat_all_merged_with_design_cap_is_parked_honest_verify():
    """THE c.1710 rule: an all-merged flat run whose design review ended ON its
    iteration cap is a VALID run with a MEASURED capability shortfall —
    PARKED-HONEST (VERIFY), no longer STALLED."""
    outcomes = [_outcome("a", "MERGED"), _outcome("design-fix-1", "MERGED")]
    verdict, attribution = sd.compute_flat_verdict(
        outcomes, cancelled=False, stopped=False,
        design_review_ending=sd.DESIGN_REVIEW_CAP)
    assert verdict == sd.VERDICT_PARKED_HONEST
    assert attribution == sd.ATTRIBUTION_VERIFY


def test_flat_all_merged_with_clean_ending_is_parked_honest_verify():
    """THE c.1717 extension: a CLEAN ending (real critique, reviewer satisfied) on an
    all-merged flat run reclasses PARKED-HONEST (VERIFY) exactly like the cap."""
    outcomes = [_outcome("a", "MERGED")]
    verdict, attribution = sd.compute_flat_verdict(
        outcomes, cancelled=False, stopped=False,
        design_review_ending=sd.DESIGN_REVIEW_CLEAN)
    assert verdict == sd.VERDICT_PARKED_HONEST
    assert attribution == sd.ATTRIBUTION_VERIFY


def test_flat_all_merged_without_ending_stays_stalled_verify():
    """The unchanged twin: no measured design ending => the merged-but-unverifiable
    anti-FALSE-DONE terminal stays STALLED (VERIFY)."""
    outcomes = [_outcome("a", "MERGED")]
    assert sd.compute_flat_verdict(outcomes, cancelled=False, stopped=False) == (
        sd.VERDICT_STALLED, sd.ATTRIBUTION_VERIFY)
    assert sd.compute_flat_verdict(
        outcomes, cancelled=False, stopped=False, design_review_ending="") == (
        sd.VERDICT_STALLED, sd.ATTRIBUTION_VERIFY)


def test_flat_unknown_ending_token_is_ignored():
    """Fail-conservative: only the two known ending tokens reclass — an unknown
    token behaves like no ending (STALLED [VERIFY]), never like a measurement."""
    outcomes = [_outcome("a", "MERGED")]
    assert sd.compute_flat_verdict(
        outcomes, cancelled=False, stopped=False,
        design_review_ending="weird-token") == (
        sd.VERDICT_STALLED, sd.ATTRIBUTION_VERIFY)


def test_flat_design_endings_never_green():
    """The flat never-GREEN lock survives the re-class: both ending signals only
    move the verdict WITHIN non-GREEN."""
    outcomes = [_outcome("a", "MERGED"), _outcome("b", "MERGED")]
    for ending in (sd.DESIGN_REVIEW_CAP, sd.DESIGN_REVIEW_CLEAN):
        verdict, _ = sd.compute_flat_verdict(
            outcomes, cancelled=False, stopped=False, design_review_ending=ending)
        assert verdict != sd.VERDICT_GREEN, ending


def test_flat_budget_stop_dominates_design_endings():
    """A genuine harness-stall class: the budget watchdog killed the run. STALLED
    (HARNESS) even if an ending signal were somehow set — run-invalid dominates."""
    outcomes = [_outcome("a", "MERGED")]
    for ending in (sd.DESIGN_REVIEW_CAP, sd.DESIGN_REVIEW_CLEAN):
        assert sd.compute_flat_verdict(
            outcomes, cancelled=False, stopped=True, design_review_ending=ending) == (
            sd.VERDICT_STALLED, sd.ATTRIBUTION_HARNESS), ending


def test_flat_nothing_ran_dominates_design_endings():
    """Nothing ran (settle/gate/load abort): STALLED (HARNESS) — an ending signal
    cannot resurrect a run that never produced outcomes (defensive; structurally the
    design loop cannot even run without a merged outcome)."""
    for ending in (sd.DESIGN_REVIEW_CAP, sd.DESIGN_REVIEW_CLEAN):
        assert sd.compute_flat_verdict(
            [], cancelled=False, stopped=False, design_review_ending=ending) == (
            sd.VERDICT_STALLED, sd.ATTRIBUTION_HARNESS), ending


def test_flat_cancel_precedence_unchanged_by_design_endings():
    """An operator cancel keeps its own class (PARKED-HONEST / HARNESS — the
    interventions counter carries the operator signal), not VERIFY."""
    outcomes = [_outcome("a", "MERGED")]
    for ending in (sd.DESIGN_REVIEW_CAP, sd.DESIGN_REVIEW_CLEAN):
        assert sd.compute_flat_verdict(
            outcomes, cancelled=True, stopped=False, design_review_ending=ending) == (
            sd.VERDICT_PARKED_HONEST, sd.ATTRIBUTION_HARNESS), ending


def test_flat_unmerged_with_endings_keeps_build_attribution():
    """A parked/unmerged task is the more specific failure signal: PARKED-HONEST
    (BUILD) — already an honest, bankable RED; a design ending does not
    re-attribute it."""
    outcomes = [_outcome("a", "MERGED"), _outcome("design-fix-1", "PARKED")]
    for ending in (sd.DESIGN_REVIEW_CAP, sd.DESIGN_REVIEW_CLEAN):
        assert sd.compute_flat_verdict(
            outcomes, cancelled=False, stopped=False, design_review_ending=ending) == (
            sd.VERDICT_PARKED_HONEST, sd.ATTRIBUTION_BUILD), ending


# ---------------------------------------------------------------------------
# compute_job_verdict — the plan-graph twin (pure)
# ---------------------------------------------------------------------------


def test_plan_all_merged_oracle_not_run_with_cap_is_parked_honest_verify(tmp_path):
    """The plan-mode twin of the B5 terminal: everything merged, gates clean, the job
    oracle honestly stamped ``not-run`` — WITH the design cap the run carries a
    measured verify outcome, so it is PARKED-HONEST (VERIFY), not STALLED."""
    verdict, attribution = sd.compute_job_verdict(
        _merged_not_run_plan(tmp_path), cancelled=False, stopped=False,
        wave_gates=[], design_review_ending=sd.DESIGN_REVIEW_CAP)
    assert (verdict, attribution) == (sd.VERDICT_PARKED_HONEST, sd.ATTRIBUTION_VERIFY)


def test_plan_all_merged_oracle_not_run_with_clean_is_parked_honest_verify(tmp_path):
    """c.1717 symmetric across BOTH terminals: the clean ending reclasses the
    plan-mode merged-but-unverifiable terminal too."""
    verdict, attribution = sd.compute_job_verdict(
        _merged_not_run_plan(tmp_path), cancelled=False, stopped=False,
        wave_gates=[], design_review_ending=sd.DESIGN_REVIEW_CLEAN)
    assert (verdict, attribution) == (sd.VERDICT_PARKED_HONEST, sd.ATTRIBUTION_VERIFY)


def test_plan_all_merged_oracle_not_run_without_ending_stays_stalled_verify(tmp_path):
    """The unchanged twin: merged-but-unverifiable without a measured design ending
    stays STALLED (VERIFY: the oracle was missing, not the build)."""
    assert sd.compute_job_verdict(
        _merged_not_run_plan(tmp_path), cancelled=False, stopped=False,
        wave_gates=[]) == (sd.VERDICT_STALLED, sd.ATTRIBUTION_VERIFY)


def test_plan_acceptance_never_stamped_fallback_untouched_by_endings(tmp_path):
    """The defensive fallback (acc still 'pending' — the run died before the
    acceptance phase stamped, an un-classifiable shape unreachable on the live path
    once the design loop has run) stays STALLED (VERIFY) even with an ending signal:
    'do NOT touch any other STALLED source'."""
    plan = _all_merged(_one_task_plan(tmp_path))   # job_acceptance stays "pending"
    for ending in (sd.DESIGN_REVIEW_CAP, sd.DESIGN_REVIEW_CLEAN):
        assert sd.compute_job_verdict(
            plan, cancelled=False, stopped=False, wave_gates=[],
            design_review_ending=ending) == (
            sd.VERDICT_STALLED, sd.ATTRIBUTION_VERIFY), ending


def test_plan_endings_never_mint_and_never_demote_green(tmp_path):
    """The endings are banking-validity signals only. They can NEVER mint GREEN
    (oracle not-run + ending => PARKED-HONEST, proven above) and NEVER demote one:
    an oracle-passed run stays GREEN whatever the design review said — the
    operator's eyeball, not the VLM, judges the look."""
    plan = pg.mark_job_acceptance(_all_merged(_one_task_plan(tmp_path)),
                                  "passed", "exit 0")
    for ending in (sd.DESIGN_REVIEW_CAP, sd.DESIGN_REVIEW_CLEAN):
        assert sd.compute_job_verdict(
            plan, cancelled=False, stopped=False, wave_gates=[],
            design_review_ending=ending) == (sd.VERDICT_GREEN, ""), ending


def test_plan_budget_stop_dominates_design_endings(tmp_path):
    plan = _merged_not_run_plan(tmp_path)
    for ending in (sd.DESIGN_REVIEW_CAP, sd.DESIGN_REVIEW_CLEAN):
        assert sd.compute_job_verdict(
            plan, cancelled=False, stopped=True, wave_gates=[],
            design_review_ending=ending) == (
            sd.VERDICT_STALLED, sd.ATTRIBUTION_HARNESS), ending


def test_plan_crashed_mid_build_stays_stalled_harness_with_endings(tmp_path):
    """A task frozen mid-build (the run died around it) is run-invalid: STALLED
    (HARNESS) regardless of any ending signal — 'do NOT touch any other STALLED
    source'."""
    plan = _one_task_plan(tmp_path)
    plan = pg.mark_building(pg.mark_ready(plan, plan.tasks[0].id), plan.tasks[0].id)
    for ending in (sd.DESIGN_REVIEW_CAP, sd.DESIGN_REVIEW_CLEAN):
        assert sd.compute_job_verdict(
            plan, cancelled=False, stopped=False, wave_gates=[],
            design_review_ending=ending) == (
            sd.VERDICT_STALLED, sd.ATTRIBUTION_HARNESS), ending


# ---------------------------------------------------------------------------
# The scorecard builders — verdict + the machine-auditable design-review trail
# ---------------------------------------------------------------------------


def test_flat_scorecard_design_cap_stamps_verdict_and_audit_trail():
    sc = sd.build_flat_scorecard(
        [_outcome("a", "MERGED"), _outcome("design-fix-1", "MERGED")],
        run_id="R-B5", repo="battery-b5-habit-web", goal="habit tracker",
        wall_clock_s=100.0, cancelled=False, stopped=False, degraded=False,
        design_review_ending=sd.DESIGN_REVIEW_CAP,
    )
    assert sc["verdict"] == sd.VERDICT_PARKED_HONEST
    assert sc["attribution"] == sd.ATTRIBUTION_VERIFY
    assert sc["evidence"]["design_review"] == "cap-reached"
    assert sc["evidence"]["mode"] == "flat"                # #789 segmentation intact
    assert "design-review iteration cap reached" in sc["notes"]
    assert "operator judges the final look" in sc["notes"]
    # S6: still single-line everywhere (the adopter's validate rejects \r/\n).
    assert "\n" not in sc["notes"] and "\r" not in sc["notes"]


def test_flat_scorecard_clean_ending_stamps_verdict_and_audit_trail():
    sc = sd.build_flat_scorecard(
        [_outcome("a", "MERGED")],
        run_id="R-B5", repo="battery-b5-habit-web", goal="habit tracker",
        wall_clock_s=90.0, cancelled=False, stopped=False, degraded=False,
        design_review_ending=sd.DESIGN_REVIEW_CLEAN,
    )
    assert sc["verdict"] == sd.VERDICT_PARKED_HONEST
    assert sc["attribution"] == sd.ATTRIBUTION_VERIFY
    assert sc["evidence"]["design_review"] == "clean"
    assert "design review completed clean" in sc["notes"]
    assert "reviewer satisfied" in sc["notes"]
    assert "\n" not in sc["notes"] and "\r" not in sc["notes"]


def test_flat_scorecard_without_ending_is_byte_stable():
    """No ending => the pre-decision card, byte-identical: same STALLED/VERIFY
    verdict, same notes, and NO design_review evidence key (the audit stamp only
    rides a real measured ending)."""
    sc = sd.build_flat_scorecard(
        [_outcome("a", "MERGED")], run_id="R", repo="battery-x", goal="g",
        wall_clock_s=1.0, cancelled=False, stopped=False, degraded=False,
    )
    assert sc["verdict"] == sd.VERDICT_STALLED and sc["attribution"] == sd.ATTRIBUTION_VERIFY
    assert sc["evidence"] == {"oracle_status": "not-run", "mode": "flat"}
    assert "design-review" not in sc["notes"] and "design review" not in sc["notes"]


def test_plan_scorecard_ending_fact_recorded_even_when_verdict_green(tmp_path):
    """The audit-trail separation: the FACT (how the design loop ended) is stamped
    on the plan card even when the verdict branch didn't consume it (GREEN — the
    oracle passed). The re-grade trail never depends on the verdict."""
    plan = pg.mark_job_acceptance(_all_merged(_one_task_plan(tmp_path)),
                                  "passed", "exit 0")
    sc = sd.build_scorecard(
        plan, run_id="R1", outcomes=[_outcome("a", "MERGED")], wave_gates=[],
        job_evidence="exit 0", cancelled=False, stopped=False, degraded=False,
        packs_consumed=0, wall_clock_s=10.0,
        design_review_ending=sd.DESIGN_REVIEW_CLEAN,
    )
    assert sc["verdict"] == sd.VERDICT_GREEN and sc["attribution"] == ""
    assert sc["evidence"]["design_review"] == "clean"
    assert "design review completed clean" in sc["notes"]


def test_plan_scorecard_endings_on_unverified_tree_are_parked_honest_verify(tmp_path):
    for ending in (sd.DESIGN_REVIEW_CAP, sd.DESIGN_REVIEW_CLEAN):
        sc = sd.build_scorecard(
            _merged_not_run_plan(tmp_path), run_id="R1",
            outcomes=[_outcome("a", "MERGED")], wave_gates=[], job_evidence="",
            cancelled=False, stopped=False, degraded=False, packs_consumed=0,
            wall_clock_s=10.0, design_review_ending=ending,
        )
        assert sc["verdict"] == sd.VERDICT_PARKED_HONEST, ending
        assert sc["attribution"] == sd.ATTRIBUTION_VERIFY, ending
        assert sc["evidence"]["design_review"] == ending


# ---------------------------------------------------------------------------
# The exact B5 shape + the c.1717 clean twin, end to end — the REAL SwapDriver
# through the REAL design loop
# ---------------------------------------------------------------------------


def test_b5_shape_flat_design_cap_run_emits_parked_honest_verify(tmp_path):
    """Night-20260711 B5, re-run under the corrected rule: a flat visual job builds
    and MERGES, the design reviewer requests changes, ONE fix lap runs (and merges),
    the re-critique still requests changes, the iteration cap (default 2) ends the
    loop — and the REPORT phase now scores PARKED-HONEST [VERIFY] with the cap audit
    trail, where the old code logged 'JOB verdict: STALLED (attribution: VERIFY)
    (flat-queue mode).' and burned the pass."""
    calls: list = []
    ops = _min_ops(calls, run_design_loop=_iterating_design_loop)
    result = _flat_driver(tmp_path, ops, [dict(_B5_TASK)]).run()

    assert result.outcome == "complete"
    # The iterations actually ran: the coder's fix lap was dispatched and merged.
    assert ("task", "design-fix-1") in calls
    # The loop ended ON the cap (the reviewer still requesting changes).
    trail = _trail(calls)
    assert any("Design-review iteration cap reached" in ln for ln in trail)

    sc = _scorecard(calls)
    assert sc["verdict"] == sd.VERDICT_PARKED_HONEST
    assert sc["attribution"] == sd.ATTRIBUTION_VERIFY
    assert sc["evidence"] == {"oracle_status": "not-run", "mode": "flat",
                              "design_review": "cap-reached"}
    assert all(t["result"] == "MERGED" for t in sc["tasks"])
    # The corrected operator-facing log line (the B5 trail shape, re-classed).
    assert any(
        "JOB verdict: PARKED-HONEST (attribution: VERIFY) (flat-queue mode)." in ln
        for ln in trail)
    assert not any("JOB verdict: STALLED" in ln for ln in trail)


def test_clean_ending_flat_run_emits_parked_honest_verify(tmp_path):
    """The c.1717 clean twin end-to-end: a REAL critique runs on the first lap
    (``ok=True``), the reviewer is satisfied, the loop ends clean — the REPORT
    phase scores PARKED-HONEST [VERIFY] with the clean audit stamp (this exact
    shape scored STALLED [VERIFY] and blocked banking before c.1717)."""
    calls: list = []
    ops = _min_ops(calls, run_design_loop=_satisfied_design_loop)
    result = _flat_driver(tmp_path, ops, [dict(_B5_TASK)]).run()

    assert result.outcome == "complete"
    assert ("task", "design-fix-1") not in calls          # no fix lap needed
    sc = _scorecard(calls)
    assert sc["verdict"] == sd.VERDICT_PARKED_HONEST
    assert sc["attribution"] == sd.ATTRIBUTION_VERIFY
    assert sc["evidence"] == {"oracle_status": "not-run", "mode": "flat",
                              "design_review": "clean"}
    trail = _trail(calls)
    assert any(
        "JOB verdict: PARKED-HONEST (attribution: VERIFY) (flat-queue mode)." in ln
        for ln in trail)


def test_unavailable_critique_ending_is_not_a_measured_ending(tmp_path):
    """DORMANT-safety (the c.1717 boundary): the DEFAULT noop design loop reports
    'design critique unavailable' with ``ok=False`` — no reviewer ever looked, so
    the all-merged flat run keeps the unchanged merged-but-unverifiable STALLED
    [VERIFY] and carries NO design_review stamp. An unavailable critique must
    never wear the satisfied reviewer's clothes."""
    calls: list = []
    ops = _min_ops(calls)   # default design loop: ok=False, "critique unavailable"
    result = _flat_driver(tmp_path, ops, [dict(_B5_TASK)]).run()
    assert result.outcome == "complete"
    sc = _scorecard(calls)
    assert sc["verdict"] == sd.VERDICT_STALLED and sc["attribution"] == sd.ATTRIBUTION_VERIFY
    assert "design_review" not in sc["evidence"]


def test_not_satisfied_non_iterate_ending_reclasses_nothing(tmp_path):
    """A review that ends without iterating but NOT satisfied (``ok=True`` yet
    ``needs_work=True`` — e.g. the ps-side loop declined another lap) is neither
    clean nor cap: out of the decided scope, so the terminal stays STALLED
    [VERIFY] and no stamp rides."""
    def declined(_a: str, _g: str, _v: str) -> dict:
        return {"should_iterate": False, "needs_work": True,
                "feedback": "spacing still off", "layout_hard": False,
                "capture_tier": "web-headless", "ok": True}

    calls: list = []
    ops = _min_ops(calls, run_design_loop=declined)
    result = _flat_driver(tmp_path, ops, [dict(_B5_TASK)]).run()
    assert result.outcome == "complete"
    sc = _scorecard(calls)
    assert sc["verdict"] == sd.VERDICT_STALLED and sc["attribution"] == sd.ATTRIBUTION_VERIFY
    assert "design_review" not in sc["evidence"]


def test_b5_shape_reload_failure_mid_design_is_not_a_measured_ending(tmp_path):
    """A design loop aborted by a coder-reload FAILURE (a harness-ish mid-loop
    break, NOT a measured ending) must not claim the re-class: the run stays on
    the unchanged STALLED [VERIFY] terminal."""
    calls: list = []
    loads = iter([True])    # the initial 30B load succeeds; the design-fix reload fails
    ops = _min_ops(calls,
                   run_design_loop=_iterating_design_loop,
                   load_30b=lambda: next(loads, False))
    result = _flat_driver(tmp_path, ops, [dict(_B5_TASK)]).run()
    assert result.outcome == "complete"
    trail = _trail(calls)
    assert any("Could not reload the coder for the design fix" in ln for ln in trail)
    assert not any("Design-review iteration cap reached" in ln for ln in trail)
    sc = _scorecard(calls)
    assert sc["verdict"] == sd.VERDICT_STALLED and sc["attribution"] == sd.ATTRIBUTION_VERIFY
    assert "design_review" not in sc["evidence"]


def test_genuine_budget_stall_still_emits_stalled_harness(tmp_path):
    """The genuine harness-stall shape at the driver level: the out-of-band budget
    stop fires at the first task boundary — the run never completes, the design loop
    never runs, and the scorecard stays STALLED [HARNESS] (untouched by this change)."""
    calls: list = []
    ops = _min_ops(calls, stop_requested=lambda: True)
    result = _flat_driver(tmp_path, ops, [dict(_B5_TASK)]).run()
    assert result.outcome == "budget-timeout"
    sc = _scorecard(calls)
    assert sc["verdict"] == sd.VERDICT_STALLED and sc["attribution"] == sd.ATTRIBUTION_HARNESS
    assert "design_review" not in sc["evidence"]


# ---------------------------------------------------------------------------
# Battery adoption + the banking rule — the verdict must flow through unmangled
# ---------------------------------------------------------------------------


def _emitted_card(tmp_path, design_loop) -> dict:
    calls: list = []
    ops = _min_ops(calls, run_design_loop=design_loop)
    _flat_driver(tmp_path, ops, [dict(_B5_TASK)]).run()
    return _scorecard(calls)


_B5_CARD = {"id": "B5", "repo": "battery-b5-habit-web",
            "expected_outcome": {"oracle": {"expected": True}}, "rigs": []}


def test_design_ending_cards_adopt_unmangled_through_real_battery_adopter(tmp_path):
    """The battery seam: driver-emitted PARKED-HONEST [VERIFY] cards from BOTH
    endings survive the REAL adopt_driver_scorecard — validation, context overlay,
    AND the FALSE-DONE cross-check (which only rewrites GREEN) — with verdict,
    attribution, and the design_review audit stamp intact; the adopted artifact
    itself validates."""
    battery = pytest.importorskip("tools.dispatch_harness.battery")
    from tools.dispatch_harness import scorecard as bscorecard
    from tools.dispatch_harness.report import JobReport

    report = JobReport(repo="battery-b5-habit-web", goal="habit tracker",
                       run_id="R-B5", wall_clock_s=100.0)
    for loop, stamp in ((_iterating_design_loop, "cap-reached"),
                        (_satisfied_design_loop, "clean")):
        raw = _emitted_card(tmp_path / stamp, loop)
        adopted = battery.adopt_driver_scorecard(
            raw, card=_B5_CARD, report=report, dry_run=False)
        assert adopted.verdict == "PARKED-HONEST", (stamp, adopted.notes)
        assert adopted.attribution == "VERIFY", stamp
        assert adopted.evidence.get("design_review") == stamp
        assert "invalid" not in adopted.notes
        assert bscorecard.validate(adopted.to_dict()) == [], stamp


def test_banking_rule_design_ending_passes_bank_true_stalled_does_not(tmp_path):
    """The REAL banking predicate: run-battery-night.ps1 banks a pass on
    ``$fullPass -and $runnerExit -eq 0`` where the runner exit is
    ``BatterySummary.exit_code()``. A pass whose non-GREENs are the design-ending
    PARKED-HONEST cards (cap AND clean) exits 0 (BANKS); add a true harness stall
    (the runner's own synthesized crash card) and it exits 1 (does NOT bank)."""
    battery = pytest.importorskip("tools.dispatch_harness.battery")
    from tools.dispatch_harness.report import JobReport

    report = JobReport(repo="battery-b5-habit-web", goal="habit tracker",
                       run_id="R-B5", wall_clock_s=100.0)
    capped = battery.adopt_driver_scorecard(
        _emitted_card(tmp_path / "cap", _iterating_design_loop),
        card=_B5_CARD, report=report, dry_run=False)
    clean = battery.adopt_driver_scorecard(
        _emitted_card(tmp_path / "clean", _satisfied_design_loop),
        card=_B5_CARD, report=report, dry_run=False)
    assert capped.verdict == "PARKED-HONEST" and clean.verdict == "PARKED-HONEST"

    banked = battery.BatterySummary(scorecards=[capped, clean])
    assert banked.stalled == 0
    assert banked.exit_code() == 0      # the pass BANKS

    crashed = battery.synthesize_scorecard(
        JobReport(repo="battery-b6", goal="g", error="dispatch crashed"),
        {"id": "B6", "repo": "battery-b6", "expected_outcome": {}},
        runs_dir=None, dry_run=False)
    assert crashed.verdict == "STALLED" and crashed.attribution == "HARNESS"

    blocked = battery.BatterySummary(scorecards=[capped, clean, crashed])
    assert blocked.stalled == 1
    assert blocked.exit_code() == 1     # a true STALLED still blocks the bank
