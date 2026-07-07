"""Unit + dry-run tests for the autonomous-dispatch harness (tools/dispatch_harness).

No model, no live AO, no GPU. Covers the harness's PURE pieces — job-config parsing, the
clarifying-answer mapping, the doom-detection predicate (hand-built mtimes/CPU/log-state), the
report assembly, and the outcome classifier — plus a DRY-RUN of the FULL flow against a fake
in-process AO (a real DispatchCoordinator wired to injected plan/execute fns + a fake fleet-run
dir). The coordinator-flow fakes mirror tests/integration/test_dispatch_coordinator.py.

These run in the standing gate (tests/integration is in scope). asyncio_mode=auto, so async test
functions need no decorator.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from shared.fleet import dispatch as fleet
from shared.fleet.acceptance import AcceptanceCriterion, AcceptanceSpec, PlanResult

from tools.dispatch_harness.clarify import parse_question_options, pick_clarify_answer
from tools.dispatch_harness.config import load_harness_config
from tools.dispatch_harness.harness import (
    DispatchHarness,
    _approve_succeeded,
    _is_clarifying_question,
    _plan_failure_summary,
)
from tools.dispatch_harness.jobs import JobSpec, load_jobs, parse_jobs
from tools.dispatch_harness.monitor import (
    DoomVerdict,
    RunMonitor,
    RunSignals,
    classify_outcome,
    classify_run_health,
)
from tools.dispatch_harness.report import JobReport, SweepReport


# ===========================================================================
# job-config parsing
# ===========================================================================


def test_parse_jobs_object_form_with_default_clarify():
    data = {
        "default_clarify_answer": "2",
        "jobs": [
            {"repo": "calc", "goal": "a calculator", "expected": "merged"},
            {"repo": "web", "goal": "a web app", "clarify_answer": "web"},
        ],
    }
    jobs = parse_jobs(data)
    assert [j.repo for j in jobs] == ["calc", "web"]
    assert jobs[0].clarify_answer == "2"          # fell back to the config default
    assert jobs[0].expected == "MERGED"           # upper-cased
    assert jobs[1].clarify_answer == "web"        # explicit wins
    assert jobs[0].command == "/dispatch calc | a calculator"


def test_parse_jobs_bare_list_form_uses_arg_default():
    jobs = parse_jobs(
        [{"repo": "r", "goal": "g"}], default_clarify_answer="1"
    )
    assert jobs[0].clarify_answer == "1"


def test_parse_jobs_rejects_non_object_job():
    with pytest.raises(ValueError, match="must be an object"):
        parse_jobs({"jobs": ["not-a-dict"]})


def test_parse_jobs_requires_repo_and_goal():
    with pytest.raises(ValueError, match="needs both 'repo' and 'goal'"):
        parse_jobs({"jobs": [{"repo": "r"}]})


def test_parse_jobs_rejects_scalar_config():
    with pytest.raises(ValueError, match="must be a list of jobs or an object"):
        parse_jobs(42)


def test_load_jobs_reads_json_file(tmp_path):
    p = tmp_path / "sweep.json"
    p.write_text(json.dumps({"jobs": [{"repo": "r", "goal": "g"}]}), encoding="utf-8")
    jobs = load_jobs(p, default_clarify_answer="3")
    assert jobs[0].repo == "r" and jobs[0].clarify_answer == "3"


def test_load_jobs_bad_json_raises_valueerror(tmp_path):
    p = tmp_path / "bad.json"
    p.write_text("{not json", encoding="utf-8")
    with pytest.raises(ValueError, match="not valid JSON"):
        load_jobs(p)


def test_example_sweep_file_parses():
    # The shipped example must always parse (it is the LA's starting point).
    example = (
        Path(__file__).resolve().parents[2]
        / "tools" / "dispatch_harness" / "examples" / "sweep.json"
    )
    jobs = load_jobs(example)
    assert len(jobs) == 3 and jobs[0].repo == "rocket-calc"


# ===========================================================================
# clarifying-answer mapping (Inc-4)
# ===========================================================================

# The coordinator's rendered question (verbatim shape from _render_clarifying_question).
_QUESTION = (
    "Before I plan “an app with buttons”, one quick question:\n"
    "\n"
    "Where will you mainly use this?\n"
    "  1. On this computer\n"
    "  2. In a web browser\n"
    "  3. On a phone\n"
    "\n"
    "Reply with the number (e.g. `2`), or `/dispatch reject` to cancel."
)


def test_parse_question_options_recovers_numbered_options():
    opts = parse_question_options(_QUESTION)
    assert [o.number for o in opts] == ["1", "2", "3"]
    assert opts[1].label == "In a web browser"


def test_pick_clarify_answer_passes_through_valid_number():
    assert pick_clarify_answer(_QUESTION, "2", default="1") == "2"


def test_pick_clarify_answer_maps_label_substring():
    # "web" is contained in "In a web browser" -> option 2.
    assert pick_clarify_answer(_QUESTION, "web", default="1") == "2"
    # "this computer" matches option 1.
    assert pick_clarify_answer(_QUESTION, "on this computer", default="3") == "1"
    # "phone" matches option 3.
    assert pick_clarify_answer(_QUESTION, "phone", default="1") == "3"


def test_pick_clarify_answer_falls_back_to_default_when_unmatched():
    # An answer that matches nothing falls back to the default, resolved against the options.
    assert pick_clarify_answer(_QUESTION, "spaceship", default="2") == "2"
    assert pick_clarify_answer(_QUESTION, "spaceship", default="web") == "2"


def test_pick_clarify_answer_out_of_range_number_is_not_invented():
    # An out-of-range number does not resolve; with an unresolvable default it is handed back raw
    # (the coordinator's own out-of-range fallback then proceeds with the un-refined plan).
    assert pick_clarify_answer(_QUESTION, "9", default="nonsense") == "9"


def test_pick_clarify_answer_no_options_returns_raw():
    assert pick_clarify_answer("not a question", "1", default="2") == "1"


# ===========================================================================
# doom-detection predicate (pure — hand-built RunSignals)
# ===========================================================================


def _sig(
    *,
    wall_now=1000.0,
    summary=False,
    summary_text="",
    swap_failed=False,
    journal=None,
    fleet_log=None,
    ovms=None,
    review_log=None,
    design_log=None,
    swap_progress=None,
    cpu=False,
    phase="CODE",
):
    return RunSignals(
        now=wall_now,
        wall_now=wall_now,
        summary_exists=summary,
        summary_text=summary_text,
        swap_failed_exists=swap_failed,
        journal_mtime=journal,
        fleet_log_mtime=fleet_log,
        ovms_log_mtime=ovms,
        review_log_mtime=review_log,
        design_log_mtime=design_log,
        swap_progress_mtime=swap_progress,
        coder_cpu_active=cpu,
        phase=phase,
    )


def test_doom_complete_when_summary_present():
    # COMPLETE requires BOTH a SUMMARY and a TERMINAL swap phase (the 14B swap-back done) — #686.
    cur = _sig(summary=True, summary_text="x", phase="RECOVERED")
    assert classify_run_health(None, cur, stall_grace_s=90) is DoomVerdict.COMPLETE


def test_doom_summary_mid_coding_is_not_complete():
    # The #686 bug: a per-task SUMMARY appears while the swap is still CODE (more tasks / the 14B
    # not yet restored) -> NOT complete; the harness must keep monitoring until the swap-back.
    cur = _sig(summary=True, summary_text="x", phase="CODE")
    assert classify_run_health(None, cur, stall_grace_s=90) is not DoomVerdict.COMPLETE


def test_doom_complete_dry_run_no_swap_phase():
    # A dry-run / fake AO has NO swap pipeline (phase="") -> SUMMARY alone is authoritative.
    cur = _sig(summary=True, summary_text="x", phase="")
    assert classify_run_health(None, cur, stall_grace_s=90) is DoomVerdict.COMPLETE


def test_doom_complete_terminal_phase_without_summary():
    # A crashed run can reach a terminal swap phase (RECOVERED) having written NO SUMMARY -> still
    # COMPLETE (the dispatch is over) so the harness concludes instead of hanging forever.
    cur = _sig(summary=False, phase="RECOVERED")
    assert classify_run_health(None, cur, stall_grace_s=90) is DoomVerdict.COMPLETE


def test_doom_dry_run_no_summary_is_not_complete():
    # Conversely, NO swap pipeline (phase="") AND no SUMMARY -> not complete (the dry-run hasn't
    # produced its authoritative signal yet).
    cur = _sig(summary=False, phase="", journal=None, fleet_log=None)
    assert classify_run_health(None, cur, stall_grace_s=90) is not DoomVerdict.COMPLETE


def test_doom_not_doomed_during_swap_teardown():
    # A stalled-looking state (old log, no CPU) but the swap is in a TEARDOWN phase (no coder) ->
    # WAITING, not DOOMED: a quiet swap-back is the driver winding down, not a doomed coder.
    prev = _sig(wall_now=1000.0, journal=850.0, fleet_log=850.0, cpu=False, phase="UNLOAD-30B")
    cur = _sig(wall_now=1100.0, journal=850.0, fleet_log=850.0, cpu=False, phase="UNLOAD-30B")
    assert classify_run_health(prev, cur, stall_grace_s=90) is DoomVerdict.WAITING


def test_doom_failed_signal_when_swap_failed_file():
    cur = _sig(swap_failed=True, journal=900.0)
    assert classify_run_health(None, cur, stall_grace_s=90) is DoomVerdict.FAILED_SIGNAL


def test_doom_waiting_before_any_progress_artifact():
    # No logs, no summary yet -> the run simply hasn't started; never DOOMED.
    cur = _sig(journal=None, fleet_log=None, ovms=None)
    assert classify_run_health(None, cur, stall_grace_s=90) is DoomVerdict.WAITING


def test_doom_running_when_cpu_active_even_if_logs_quiet():
    # Logs old, but a coder process is burning CPU -> RUNNING (the false-stall guard).
    prev = _sig(wall_now=1000.0, journal=800.0, cpu=False)
    cur = _sig(wall_now=1100.0, journal=800.0, cpu=True)
    assert classify_run_health(prev, cur, stall_grace_s=90) is DoomVerdict.RUNNING


def test_doom_running_when_mtime_advances():
    prev = _sig(wall_now=1000.0, fleet_log=995.0, cpu=False)
    cur = _sig(wall_now=1100.0, fleet_log=1050.0, cpu=False)  # log advanced
    assert classify_run_health(prev, cur, stall_grace_s=90) is DoomVerdict.RUNNING


def test_doom_running_when_review_log_advances():
    # #687 false-doom: a long [4/5] 30B review is GPU-bound (cpu idle) and writes ONLY to
    # *.review.log -- journal/run-fleet/ovms stay quiet. The review log advancing must read as
    # RUNNING, not a stall, or a healthy review gets killed AND its cancel-on-doom skips the design
    # phase. Here only review_log advances; everything else is stale + no CPU.
    prev = _sig(wall_now=1000.0, journal=850.0, fleet_log=850.0, review_log=995.0, cpu=False)
    cur = _sig(wall_now=1100.0, journal=850.0, fleet_log=850.0, review_log=1050.0, cpu=False)
    assert classify_run_health(prev, cur, stall_grace_s=90) is DoomVerdict.RUNNING


def test_doom_running_when_design_log_advances():
    # The end-of-run design phase: the 30B is unloaded (cpu idle); the VLM writes design-critique.log
    # while the fleet logs are quiet. design_log advancing -> RUNNING.
    prev = _sig(wall_now=1000.0, journal=850.0, fleet_log=850.0, design_log=995.0, cpu=False, phase="DESIGN")
    cur = _sig(wall_now=1100.0, journal=850.0, fleet_log=850.0, design_log=1050.0, cpu=False, phase="DESIGN")
    assert classify_run_health(prev, cur, stall_grace_s=90) is DoomVerdict.RUNNING


def test_doom_running_when_swap_progress_advances():
    # The swap trail (phase transitions / design notes) advancing is also progress.
    prev = _sig(wall_now=1000.0, journal=850.0, fleet_log=850.0, swap_progress=995.0, cpu=False)
    cur = _sig(wall_now=1100.0, journal=850.0, fleet_log=850.0, swap_progress=1050.0, cpu=False)
    assert classify_run_health(prev, cur, stall_grace_s=90) is DoomVerdict.RUNNING


def test_doom_still_detected_when_all_logs_including_new_ones_stale():
    # The new signals must NOT weaken doom detection: when review/design/swap logs are ALSO stale (a
    # genuinely hung coder), the run is still DOOMED. (Mutation guard: a new signal that always
    # reported fresh would mask every stall and this would flip to not-DOOMED.)
    prev = _sig(wall_now=1000.0, journal=850.0, fleet_log=850.0, review_log=850.0,
                design_log=850.0, swap_progress=850.0, cpu=False)
    cur = _sig(wall_now=1100.0, journal=850.0, fleet_log=850.0, review_log=850.0,
               design_log=850.0, swap_progress=850.0, cpu=False)
    assert classify_run_health(prev, cur, stall_grace_s=90) is DoomVerdict.DOOMED


def test_doom_detected_when_stalled_and_idle():
    # The real 14:23 rocket-calc stall: a fleet log exists but is old, no CPU, no summary,
    # and a prior snapshot confirms the stall persisted -> DOOMED (stop fast).
    prev = _sig(wall_now=1000.0, journal=850.0, fleet_log=850.0, cpu=False)
    cur = _sig(wall_now=1100.0, journal=850.0, fleet_log=850.0, cpu=False)  # 250s old, no advance
    assert classify_run_health(prev, cur, stall_grace_s=90) is DoomVerdict.DOOMED


def test_doom_not_declared_within_grace():
    # Stalled but the freshest progress is younger than the grace window -> WAITING, not DOOMED.
    prev = _sig(wall_now=1000.0, journal=970.0, cpu=False)
    cur = _sig(wall_now=1030.0, journal=970.0, cpu=False)  # only 60s old, grace=90
    assert classify_run_health(prev, cur, stall_grace_s=90) is DoomVerdict.WAITING


def test_doom_not_declared_without_prior_snapshot():
    # Even an old artifact needs a SECOND confirming snapshot before we call it doomed (avoid a
    # first-poll false positive right after a slow startup).
    cur = _sig(wall_now=1100.0, journal=850.0, cpu=False)
    assert classify_run_health(None, cur, stall_grace_s=90) is DoomVerdict.WAITING


# ===========================================================================
# outcome classification (off the real fleet parser)
# ===========================================================================

_SUMMARY_MERGED = (
    "Fleet run RID — 1 task(s):\n"
    "- build-it: processed\n"
    "    RESULT: MERGED into your project - just open the app and try it.\n"
)
_SUMMARY_PARKED = (
    "Fleet run RID — 1 task(s):\n"
    "- build-it: processed\n"
    "    RESULT: NOT merged. The work is parked safely on branch 'agent/build-it'.\n"
)
_SUMMARY_MIXED = _SUMMARY_MERGED + (
    "- add-tests: processed\n"
    "    RESULT: BLOCKED: a potential secret was detected.\n"
)


def test_classify_outcome_merged():
    assert classify_outcome(_SUMMARY_MERGED) == "MERGED"


def test_classify_outcome_parked():
    assert classify_outcome(_SUMMARY_PARKED) == "PARKED"


def test_classify_outcome_worst_of_mixed_is_blocked():
    # A sweep headline flags the worst task: merged + blocked -> BLOCKED.
    assert classify_outcome(_SUMMARY_MIXED) == "BLOCKED"


def test_classify_outcome_empty_is_none():
    assert classify_outcome("nothing parseable here") == "NONE"


# ===========================================================================
# report assembly
# ===========================================================================


def test_job_report_expectation_met_flags():
    j = JobReport(repo="r", goal="g", outcome="MERGED", expected="MERGED", verdict="COMPLETE")
    assert j.expectation_met == "met" and j.ok is True
    j2 = JobReport(repo="r", goal="g", outcome="PARKED", expected="MERGED", verdict="COMPLETE")
    assert j2.expectation_met == "UNMET"
    j3 = JobReport(repo="r", goal="g", outcome="MERGED", verdict="COMPLETE")
    assert j3.expectation_met == "n/a"


def test_job_report_ok_requires_complete_and_no_error():
    assert JobReport(repo="r", goal="g", verdict="DOOMED").ok is False
    assert JobReport(repo="r", goal="g", verdict="COMPLETE", error="boom").ok is False


def test_sweep_report_render_and_dict():
    sweep = SweepReport(dry_run=True)
    sweep.add(JobReport(repo="calc", goal="a calc", plan_ok=True, approved=True,
                        run_id="RID1", outcome="MERGED", verdict="COMPLETE",
                        expected="MERGED", wall_clock_s=12.0))
    sweep.add(JobReport(repo="hang", goal="a hang", plan_ok=True, approved=True,
                        run_id="RID2", verdict="DOOMED", wall_clock_s=95.0,
                        stop_reason="determined-doomed: no fleet progress"))
    text = sweep.render()
    assert "DRY-RUN" in text
    assert "calc | a calc" in text and "MERGED" in text
    assert "stopped: determined-doomed" in text
    d = sweep.to_dict()
    assert d["total"] == 2 and d["complete"] == 1 and d["doomed"] == 1
    assert d["jobs"][0]["expectation_met"] == "met"


def test_sweep_report_empty_render():
    assert "no jobs ran" in SweepReport().render()


# ===========================================================================
# harness reply helpers (pure)
# ===========================================================================


def test_is_clarifying_question_detects_question_not_preview():
    assert _is_clarifying_question(_QUESTION) is True
    # A normal preview offers approve -> NOT a clarifying question.
    assert _is_clarifying_question("Automatic checks…\n/dispatch approve or /dispatch reject") is False


def test_approve_succeeded_marker():
    assert _approve_succeeded("Dispatching RID-DET — 1 task(s) to the coder fleet.") is True
    assert _approve_succeeded("Nothing to approve — start one with /dispatch …") is False


def test_plan_failure_summary_classifies_known_shells():
    assert "disabled" in _plan_failure_summary(
        "Coding dispatch is off. It's dormant by default — enable it with …"
    )
    assert "go-live" in _plan_failure_summary(
        "Coding dispatch is enabled, but the plan/execute wiring … isn't connected yet — "
        "that's the on-hardware go-live step."
    )
    assert "could not connect" in _plan_failure_summary(
        "Could not connect to the Assistant Orchestrator (Fail-Closed)."
    )


# ===========================================================================
# config resolution
# ===========================================================================


def test_load_harness_config_reads_committed_default_toml():
    # The real AO default.toml resolves to port 5001 and the configured roots.
    cfg = load_harness_config()
    assert cfg.port == 5001
    assert cfg.config_path.name == "default.toml"


def test_load_harness_config_missing_file_falls_back(tmp_path):
    cfg = load_harness_config(tmp_path / "nope.toml")
    assert cfg.port == 5001 and cfg.fleet_dispatch_enabled is False


def test_load_harness_config_parses_overrides(tmp_path):
    p = tmp_path / "c.toml"
    p.write_text(
        "[ipc]\nvsock_port = 5009\n"
        "[fleet_dispatch]\nenabled = true\n"
        "agentic_setup_dir = \"D:/fleet\"\nprojects_dir = \"D:/proj\"\n"
        "swap_run_budget_s = 1200.0\n",
        encoding="utf-8",
    )
    cfg = load_harness_config(p)
    assert cfg.port == 5009 and cfg.fleet_dispatch_enabled is True
    assert cfg.agentic_setup_dir == "D:/fleet" and cfg.swap_run_budget_s == 1200.0


def test_load_harness_config_bad_toml_raises(tmp_path):
    p = tmp_path / "bad.toml"
    p.write_text("this is = = not toml", encoding="utf-8")
    with pytest.raises(ValueError, match="not valid TOML"):
        load_harness_config(p)


# ===========================================================================
# DRY-RUN of the FULL flow against a fake in-process AO
# ===========================================================================
#
# A real DispatchCoordinator wired to injected plan/execute fns + a fake fleet-run dir; the
# execute fn writes a SUMMARY so the monitor returns COMPLETE. Mirrors the coordinator-test fakes.


def _fake_config(tmp_path: Path) -> fleet.FleetDispatchConfig:
    return fleet.FleetDispatchConfig(
        scripts_dir=tmp_path / "scripts",
        queue_path=tmp_path / "state" / "fleet-queue.json",
        runs_dir=tmp_path / "state" / "fleet-runs",
        projects_dir=tmp_path / "projects",
    )


def _clear_spec(goal="a calc"):
    return AcceptanceSpec(
        goal,
        (
            AcceptanceCriterion("c1", "the project builds", "build", ""),
            AcceptanceCriterion("c2", "2 + 3 shows 5", "behavior", ""),
        ),
        build_plan={"surface": "desktop-gui", "language_hint": None,
                    "complexity": "moderate", "components": []},
    )


def _ambiguous_spec(goal="an app"):
    return AcceptanceSpec(
        goal,
        (AcceptanceCriterion("c1", "the project builds", "build", ""),),
        build_plan={"surface": "ambiguous", "language_hint": None, "complexity": "moderate",
                    "components": [], "candidates": ["desktop-gui", "web", "mobile"]},
    )


def _plan_fn(spec_factory):
    async def plan_fn(repo, goal):
        spec = spec_factory(goal)
        return PlanResult(
            ok=True,
            tasks=[{"repo": repo, "task": "build-it", "prompt": "build it",
                    "surface": spec.build_plan.get("surface", "unknown")}],
            spec=spec,
            message="planned",
        )

    return plan_fn


def _execute_fn(config, *, calls, outcome_line="    RESULT: MERGED into your project.\n"):
    async def execute_fn(session_id, run_id, repo, tasks, spec):
        calls.append({"run_id": run_id, "tasks": tasks, "surface": tasks[0].get("surface")})
        run_dir = config.runs_dir / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "SUMMARY.txt").write_text(
            f"Fleet run {run_id} — 1 task(s):\n- build-it: processed\n{outcome_line}",
            encoding="utf-8",
        )
        return fleet.DispatchResult(
            ok=True, run_id=run_id,
            message=f"Dispatching {run_id} — 1 task(s) to the coder fleet.",
        )

    return execute_fn


def _harness(config, plan_fn, execute_fn, **kw):
    return DispatchHarness.for_dry_run(
        config=config, plan_fn=plan_fn, execute_fn=execute_fn,
        mint_run_id=lambda: "RID-DRY", **kw,
    )


async def test_dry_run_clear_surface_full_flow_merged(tmp_path):
    cfg = _fake_config(tmp_path)
    calls: list = []
    h = _harness(cfg, _plan_fn(_clear_spec), _execute_fn(cfg, calls=calls))
    report = await h.run_job(JobSpec(repo="calc", goal="a calc", expected="MERGED"))
    assert report.plan_ok is True
    assert report.asked_clarifying is False     # clear surface asks nothing
    assert report.approved is True
    assert report.run_id == "RID-DRY"
    assert report.verdict == "COMPLETE"
    assert report.outcome == "MERGED"
    assert report.expectation_met == "met"
    assert len(calls) == 1                       # execute fired exactly once


async def test_dry_run_clarifying_question_answered_then_executes(tmp_path):
    cfg = _fake_config(tmp_path)
    calls: list = []
    h = _harness(cfg, _plan_fn(_ambiguous_spec), _execute_fn(cfg, calls=calls),
                 default_clarify_answer="1")
    # Answer "web" -> option 2 -> the resolved surface threads into the executed task.
    report = await h.run_job(JobSpec(repo="app", goal="an app", clarify_answer="web"))
    assert report.asked_clarifying is True
    assert report.answered == "2"                # "web" mapped to option 2
    assert report.approved is True
    assert report.verdict == "COMPLETE"
    assert calls[0]["surface"] == "web"          # the chosen surface reached EXECUTE


async def test_dry_run_default_clarify_answer_used_when_job_omits(tmp_path):
    cfg = _fake_config(tmp_path)
    calls: list = []
    h = _harness(cfg, _plan_fn(_ambiguous_spec), _execute_fn(cfg, calls=calls),
                 default_clarify_answer="3")
    report = await h.run_job(JobSpec(repo="app", goal="an app"))  # no clarify_answer
    assert report.asked_clarifying is True and report.answered == "3"
    assert calls[0]["surface"] == "mobile"       # option 3 == mobile


async def test_dry_run_parked_outcome_is_complete_not_doomed(tmp_path):
    # A PARKED run is a real COMPLETE result (the pipeline ran), not a doom.
    cfg = _fake_config(tmp_path)
    calls: list = []
    h = _harness(
        cfg, _plan_fn(_clear_spec),
        _execute_fn(cfg, calls=calls,
                    outcome_line="    RESULT: NOT merged. parked on branch 'agent/build-it'.\n"),
    )
    report = await h.run_job(JobSpec(repo="calc", goal="a calc", expected="MERGED"))
    assert report.verdict == "COMPLETE" and report.outcome == "PARKED"
    assert report.expectation_met == "UNMET"     # expected MERGED, got PARKED


async def test_dry_run_disabled_coordinator_reports_error_no_execute(tmp_path):
    # If the coordinator is disabled, PLAN returns the disabled notice -> no approvable preview.
    cfg = _fake_config(tmp_path)
    from services.ui_gateway.src.dispatch_coordinator import DispatchCoordinator

    coord = DispatchCoordinator(config=cfg, enabled=False)

    async def _send(session, text):
        from services.ui_gateway.src.dispatch_coordinator import parse_dispatch_command
        cmd = parse_dispatch_command(text)
        return await coord.handle_command(session, cmd) if cmd else ""

    h = DispatchHarness(send_fn=_send, config=cfg, coordinator=coord, dry_run=True)
    report = await h.run_job(JobSpec(repo="calc", goal="a calc"))
    assert report.plan_ok is False and report.approved is False
    assert "disabled" in report.error


async def test_dry_run_sweep_accumulates_each_job(tmp_path):
    cfg = _fake_config(tmp_path)
    calls: list = []
    h = _harness(cfg, _plan_fn(_clear_spec), _execute_fn(cfg, calls=calls))
    sweep = await h.run_sweep([
        JobSpec(repo="a", goal="first calc"),
        JobSpec(repo="b", goal="second calc"),
    ])
    assert len(sweep.jobs) == 2
    assert all(j.verdict == "COMPLETE" for j in sweep.jobs)
    assert sweep.to_dict()["complete"] == 2


async def test_dry_run_no_path_fires_execute_without_approve(tmp_path):
    # The mandatory-confirm guarantee survives the harness: only the approve step fires execute.
    # We assert by counting execute calls after a job that we abort by rejecting via a custom
    # send wrapper would be complex; instead verify the coordinator-level guarantee holds by
    # checking the harness issues exactly one execute per completed job (above) and that a
    # plan-only interaction fires none.
    cfg = _fake_config(tmp_path)
    calls: list = []
    from services.ui_gateway.src.dispatch_coordinator import (
        DispatchCommand,
        DispatchCoordinator,
    )

    coord = DispatchCoordinator(
        config=cfg, enabled=True, plan_fn=_plan_fn(_clear_spec),
        execute_fn=_execute_fn(cfg, calls=calls), mint_run_id=lambda: "RID-X",
    )
    # PLAN then REJECT — no execute.
    await coord.handle_command("s", DispatchCommand(kind="run", repo="calc", goal="g"))
    await coord.handle_command("s", DispatchCommand(kind="reject"))
    assert calls == []


# ===========================================================================
# RunMonitor live loop (the I/O shell over the pure predicate) — stop-doomed-fast
# ===========================================================================


def _runs_config(tmp_path: Path) -> fleet.FleetDispatchConfig:
    """A config whose runs_dir + state/logs exist, for the monitor's real disk reads."""
    state = tmp_path / "state"
    (state / "fleet-runs").mkdir(parents=True)
    (state / "logs").mkdir(parents=True)
    return fleet.FleetDispatchConfig(
        scripts_dir=tmp_path / "scripts",
        queue_path=state / "fleet-queue.json",
        runs_dir=state / "fleet-runs",
        projects_dir=tmp_path / "projects",
    )


class _FakeClock:
    """A monotonic+wall clock that advances by a fixed step on each read pair, so the loop's
    elapsed/age math is deterministic. ``read`` returns the current value; ``tick`` advances it."""

    def __init__(self, start: float = 1000.0, step: float = 30.0):
        self.t = start
        self.step = step

    def monotonic(self) -> float:
        return self.t

    def tick(self, _seconds: float = 0.0) -> None:
        self.t += self.step


def test_run_monitor_completes_when_summary_appears(tmp_path):
    cfg = _runs_config(tmp_path)
    run_dir = cfg.runs_dir / "RID"
    run_dir.mkdir()
    (run_dir / "SUMMARY.txt").write_text(
        "Fleet run RID — 1 task(s):\n- build-it: processed\n    RESULT: MERGED.\n",
        encoding="utf-8",
    )
    stopped = {"n": 0}
    mon = RunMonitor(
        config=cfg, run_id="RID", poll_interval_s=0.0, stall_grace_s=10.0,
        overall_timeout_s=1000.0, stop_fn=lambda: stopped.__setitem__("n", stopped["n"] + 1),
        sleep=lambda _s: None, proc_cpu_probe=lambda: False,
    )
    result = mon.run()
    assert result.verdict is DoomVerdict.COMPLETE
    assert result.outcome == "MERGED"
    assert stopped["n"] == 0  # a clean completion never calls stop


def test_run_monitor_waits_for_swapback_not_first_summary(tmp_path):
    """#686: a per-task SUMMARY appears while the swap is still CODE -> the monitor must NOT
    complete; only when the swap reaches RECOVERED (the 14B back) does it return COMPLETE with the
    CUMULATIVE outcome (proving it did not conclude after task 1)."""
    from shared.fleet import swap_state as ss
    from shared.fleet.swap_ops import swap_state_path

    cfg = _runs_config(tmp_path)
    run_dir = cfg.runs_dir / "RID"
    run_dir.mkdir()
    # Task 1 parked: a SUMMARY exists but the swap is still CODE (task 2 / swap-back pending).
    (run_dir / "SUMMARY.txt").write_text(
        "Fleet run RID — 1 task(s):\n- t1: processed\n"
        "    RESULT: NOT merged. The work is parked safely on branch 'agent/t1'.\n",
        encoding="utf-8",
    )
    sp = swap_state_path(cfg)
    ss.write_swap_state(ss.SwapState(run_id="RID", session_id="s", phase=ss.PHASE_CODE), path=sp)

    mon = RunMonitor(
        config=cfg, run_id="RID", poll_interval_s=0.0, stall_grace_s=10.0,
        overall_timeout_s=1000.0, sleep=lambda _s: None, proc_cpu_probe=lambda: True,
    )
    orig = mon.snapshot
    polls = {"n": 0}

    def flipping():
        polls["n"] += 1
        if polls["n"] == 3:
            # all tasks done + the 14B restored: cumulative SUMMARY + the terminal RECOVERED phase.
            (run_dir / "SUMMARY.txt").write_text(
                "Fleet run RID — 2 task(s):\n"
                "- t1: processed\n    RESULT: NOT merged. The work is parked safely on branch 'agent/t1'.\n"
                "- t2: processed\n    RESULT: MERGED into your project.\n",
                encoding="utf-8",
            )
            ss.write_swap_state(
                ss.SwapState(run_id="RID", session_id="s", phase=ss.PHASE_RECOVERED), path=sp
            )
        return orig()

    mon.snapshot = flipping  # type: ignore[method-assign]
    result = mon.run()
    assert result.verdict is DoomVerdict.COMPLETE
    assert result.outcome == "PARKED"          # the CUMULATIVE worst, not task 1 alone
    assert result.last_phase == ss.PHASE_RECOVERED
    assert polls["n"] >= 3                       # did NOT complete on the first (CODE-phase) poll


def test_run_monitor_doom_then_waits_for_swapback(tmp_path):
    """After a DOOMED stop the monitor keeps polling for the swap to wind down to RECOVERED before
    returning (the harness never reports 'done' mid-swap-back, #686). The returned verdict is the
    DOOMED stop verdict, but only once the 14B is back."""
    import os

    from shared.fleet import swap_state as ss
    from shared.fleet.swap_ops import swap_state_path

    cfg = _runs_config(tmp_path)
    run_dir = cfg.runs_dir / "RID"
    run_dir.mkdir()
    journal = run_dir / "journal.log"
    journal.write_text("2026-01-01 | TASK-START | t\n", encoding="utf-8")
    old = 500.0
    os.utime(journal, (old, old))
    sp = swap_state_path(cfg)
    ss.write_swap_state(ss.SwapState(run_id="RID", session_id="s", phase=ss.PHASE_CODE), path=sp)

    clock = _FakeClock(start=10_000.0, step=30.0)
    stopped = {"n": 0}
    mon = RunMonitor(
        config=cfg, run_id="RID", poll_interval_s=0.0, stall_grace_s=60.0,
        overall_timeout_s=10_000.0, swapback_grace_s=10_000.0,  # large -> only RECOVERED ends it
        stop_fn=lambda: stopped.__setitem__("n", stopped["n"] + 1),
        sleep=lambda _s: None, clock=clock.monotonic, wall_clock=lambda: 100_000.0,
        proc_cpu_probe=lambda: False,
    )
    orig = mon.snapshot
    polls = {"n": 0}

    def ticking():
        clock.tick()
        polls["n"] += 1
        if polls["n"] == 4:  # the driver wound the swap-back down to RECOVERED + a cumulative SUMMARY
            (run_dir / "SUMMARY.txt").write_text(
                "Fleet run RID — 1 task(s):\n- t: processed\n    RESULT: parked.\n",
                encoding="utf-8",
            )
            ss.write_swap_state(
                ss.SwapState(run_id="RID", session_id="s", phase=ss.PHASE_RECOVERED), path=sp
            )
        return orig()

    mon.snapshot = ticking  # type: ignore[method-assign]
    result = mon.run()
    assert result.verdict is DoomVerdict.DOOMED       # the stop verdict is preserved
    assert stopped["n"] == 1                           # stopped exactly once, at the doom
    assert result.last_phase == ss.PHASE_RECOVERED     # it WAITED for the swap-back to finish


def test_run_monitor_ignores_stale_other_run_phase(tmp_path):
    """A leftover RECOVERED from a PRIOR run (a different run_id in the per-box swap-state file)
    must NOT complete THIS run — the monitor only trusts a phase whose run_id matches."""
    from shared.fleet import swap_state as ss
    from shared.fleet.swap_ops import swap_state_path

    cfg = _runs_config(tmp_path)
    run_dir = cfg.runs_dir / "RID"
    run_dir.mkdir()
    (run_dir / "journal.log").write_text("2026-01-01 | TASK-START | t\n", encoding="utf-8")
    sp = swap_state_path(cfg)
    # A STALE terminal state belonging to a DIFFERENT dispatch.
    ss.write_swap_state(
        ss.SwapState(run_id="OTHER-OLD", session_id="s", phase=ss.PHASE_RECOVERED), path=sp
    )
    polls = {"n": 0}
    mon = RunMonitor(
        config=cfg, run_id="RID", poll_interval_s=0.0, stall_grace_s=10.0,
        overall_timeout_s=1000.0, sleep=lambda _s: None, proc_cpu_probe=lambda: True,
    )
    orig = mon.snapshot

    def flip():
        polls["n"] += 1
        if polls["n"] == 2:
            # NOW our OWN run reaches its terminal phase + writes its SUMMARY.
            (run_dir / "SUMMARY.txt").write_text(
                "Fleet run RID — 1 task(s):\n- t: processed\n    RESULT: MERGED into your project.\n",
                encoding="utf-8",
            )
            ss.write_swap_state(
                ss.SwapState(run_id="RID", session_id="s", phase=ss.PHASE_RECOVERED), path=sp
            )
        return orig()

    mon.snapshot = flip  # type: ignore[method-assign]
    result = mon.run()
    assert result.verdict is DoomVerdict.COMPLETE
    assert result.outcome == "MERGED"
    assert polls["n"] >= 2  # did NOT complete on poll 1 from the stale OTHER-run RECOVERED


def test_run_monitor_stops_doomed_run_fast(tmp_path):
    # A stalled run: an OLD journal log, no SUMMARY, no coder CPU. The loop must reach DOOMED on
    # the second poll (a prior snapshot confirms the stall) and call stop_fn exactly once.
    import os

    cfg = _runs_config(tmp_path)
    run_dir = cfg.runs_dir / "RID"
    run_dir.mkdir()
    journal = run_dir / "journal.log"
    journal.write_text("2026-01-01 | TASK-START | build-it\n", encoding="utf-8")
    # Backdate the journal far beyond the stall grace.
    old = 500.0
    os.utime(journal, (old, old))

    clock = _FakeClock(start=10_000.0, step=30.0)
    stopped = {"n": 0}
    mon = RunMonitor(
        config=cfg, run_id="RID", poll_interval_s=0.0, stall_grace_s=60.0,
        overall_timeout_s=10_000.0,
        stop_fn=lambda: stopped.__setitem__("n", stopped["n"] + 1),
        sleep=lambda _s: None, clock=clock.monotonic,
        # wall_clock returns "now" well past the journal's mtime so wall_age >> grace.
        wall_clock=lambda: 100_000.0,
        proc_cpu_probe=lambda: False,
    )
    # Advance the monotonic clock between polls so elapsed grows (but stays under the timeout).
    orig_snapshot = mon.snapshot

    def ticking_snapshot():
        clock.tick()
        return orig_snapshot()

    mon.snapshot = ticking_snapshot  # type: ignore[method-assign]
    result = mon.run()
    assert result.verdict is DoomVerdict.DOOMED
    assert stopped["n"] == 1  # stopped fast, exactly once
    assert "determined-doomed" in result.stop_reason


def test_run_monitor_failed_signal_does_not_stop(tmp_path):
    # The SWAP_FAILED out-of-band file -> FAILED_SIGNAL; the run already ended, so no stop call.
    from shared.fleet.swap_ops import status_path, swap_dir

    cfg = _runs_config(tmp_path)
    (cfg.runs_dir / "RID").mkdir()
    swap_dir(cfg).mkdir(parents=True, exist_ok=True)
    status_path(cfg, "RID").write_text("the swap failed\n", encoding="utf-8")
    stopped = {"n": 0}
    mon = RunMonitor(
        config=cfg, run_id="RID", poll_interval_s=0.0, stall_grace_s=10.0,
        stop_fn=lambda: stopped.__setitem__("n", stopped["n"] + 1),
        sleep=lambda _s: None, proc_cpu_probe=lambda: False,
    )
    result = mon.run()
    assert result.verdict is DoomVerdict.FAILED_SIGNAL
    assert stopped["n"] == 0


def test_run_monitor_overall_timeout_stops(tmp_path):
    # No artifacts ever appear (WAITING forever) but the overall timeout fires and stops.
    cfg = _runs_config(tmp_path)
    (cfg.runs_dir / "RID").mkdir()
    clock = _FakeClock(start=0.0, step=50.0)
    stopped = {"n": 0}
    mon = RunMonitor(
        config=cfg, run_id="RID", poll_interval_s=0.0, stall_grace_s=10.0,
        overall_timeout_s=100.0,
        stop_fn=lambda: stopped.__setitem__("n", stopped["n"] + 1),
        sleep=lambda _s: None, clock=clock.monotonic, wall_clock=lambda: 0.0,
        proc_cpu_probe=lambda: False,
    )
    orig = mon.snapshot
    mon.snapshot = lambda: (clock.tick(), orig())[1]  # type: ignore[method-assign]
    result = mon.run()
    assert result.verdict is DoomVerdict.DOOMED   # timeout is reported as a doom-class stop
    assert "overall timeout" in result.stop_reason
    assert stopped["n"] == 1


def test_run_monitor_reads_swap_progress_tail(tmp_path):
    from shared.fleet.swap_ops import write_swap_progress

    cfg = _runs_config(tmp_path)
    run_dir = cfg.runs_dir / "RID"
    run_dir.mkdir()
    write_swap_progress(cfg, "RID", "stepping aside for the 30B")
    (run_dir / "SUMMARY.txt").write_text(
        "Fleet run RID — 1 task(s):\n- t: processed\n    RESULT: MERGED.\n", encoding="utf-8"
    )
    mon = RunMonitor(
        config=cfg, run_id="RID", poll_interval_s=0.0, sleep=lambda _s: None,
        proc_cpu_probe=lambda: False,
    )
    result = mon.run()
    assert "stepping aside for the 30B" in result.progress_tail
