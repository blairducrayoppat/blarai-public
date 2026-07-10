"""Tests for swap_driver — the increment-2 swap state machine.

All side-effects are injected (SwapOps), so the sequencing + every decision point
(gate, cancel, bounded retry, NEVER-ZERO teardown) is exercised without a real swap.
"""

from __future__ import annotations

import json

import pytest

from shared.fleet import swap_driver as sd
from shared.fleet import swap_state as ss
from shared.fleet.acceptance import ACCEPTANCE_TASK_SLUG
from shared.fleet.dispatch import TaskOutcome

_TASKS = [{"repo": "X", "task": "a", "prompt": "pa"},
          {"repo": "X", "task": "b", "prompt": "pb"}]

#: A single VISUAL task (web surface + real visual criteria) — the shape that makes the #688
#: Phase 3 design loop eligible. The default _ops run_task returns MERGED, so a built app exists.
_WEB_TASK = {
    "repo": "C:/proj/landing", "task": "build-landing", "prompt": "build the landing page",
    "surface": "web", "goal": "a landing page for a bakery",
    "visual_criteria_json": json.dumps(["A hero image is visible", "The menu is legible"]),
}


def _outcome(task):
    return TaskOutcome(task=task["task"], outcome="processed", result="MERGED", detail="ok")


def _ops(calls, **overrides):
    base = dict(
        available_gb=lambda: 26.0,
        backend_alive=lambda: False,
        load_30b=lambda: (calls.append("load"), True)[1],
        wait_ready=lambda: True,
        run_task=lambda t: (calls.append(("task", t["task"])), _outcome(t))[1],
        cancel_requested=lambda: False,
        disarm_watchdog=lambda: calls.append("disarm"),
        stop_ovms=lambda: calls.append("stop"),
        write_report=lambda rid, outs: calls.append(("report", rid, len(outs))),
        restart_launcher=lambda: calls.append("restart"),
        backend_ready=lambda: True,
        signal_failure=lambda msg: calls.append(("signal", msg)),
    )
    base.update(overrides)
    return sd.SwapOps(**base)


def _driver(tmp_path, ops, tasks=None, **kw):
    return sd.SwapDriver(
        run_id="R1", session_id="s1",
        tasks=_TASKS if tasks is None else tasks,
        swap_state_path=tmp_path / "swap.json", ops=ops,
        gate_gb=21.0, sleep=lambda _s: None, **kw,
    )


def _final_phase(tmp_path):
    st = ss.read_swap_state(tmp_path / "swap.json")
    return st.phase if st else None


def _has(calls, tag):
    return any(isinstance(c, tuple) and c[0] == tag for c in calls)


# ---- happy path -----------------------------------------------------------


def test_happy_path_full_sequence(tmp_path):
    calls = []
    res = _driver(tmp_path, _ops(calls)).run()
    assert res.outcome == "complete" and res.loaded_30b and res.restart_ok
    assert len(res.outcomes) == 2
    assert calls == ["load", ("task", "a"), ("task", "b"), ("report", "R1", 2),
                     "disarm", "stop", "restart"]
    assert _final_phase(tmp_path) == ss.PHASE_RECOVERED  # healthy runs now END terminal (f13742f: the driver stamps its own last act)


# ---- #670 FIX (b): acceptance-task gating on parked features --------------


def _gated_tasks():
    # [feature, feature, acceptance-tests] — the exact compiled shape for a >=2-feature goal.
    return [{"repo": "X", "task": "feature-a", "prompt": "pa"},
            {"repo": "X", "task": "feature-b", "prompt": "pb"},
            {"repo": "X", "task": ACCEPTANCE_TASK_SLUG, "prompt": "tests"}]


def test_acceptance_skipped_when_feature_parked(tmp_path):
    # The live #670 failure: features PARKED, so the appended acceptance-tests task ran in a
    # worktree branched from a feature-less main and ground the resident 30B ~24 min. The
    # driver must SKIP the acceptance task when any preceding feature did not merge.
    calls = []
    results = {"feature-a": "MERGED", "feature-b": "PARKED"}

    def run_task(t):
        calls.append(("task", t["task"]))
        return TaskOutcome(task=t["task"], outcome="processed",
                           result=results[t["task"]], detail="ok")

    res = _driver(tmp_path, _ops(calls, run_task=run_task), tasks=_gated_tasks()).run()

    # run_task was NEVER invoked for the acceptance slug — the empty-workspace grind cannot recur.
    assert ("task", ACCEPTANCE_TASK_SLUG) not in calls
    # Exact call-list: only the two features run; the report still carries all 3 outcomes
    # (2 real + 1 synthetic SKIPPED). Mutation-resistant: reverting the guard fires run_task on
    # the acceptance task and BOTH this and the membership assertion above fail.
    assert calls == ["load", ("task", "feature-a"), ("task", "feature-b"),
                     ("report", "R1", 3), "disarm", "stop", "restart"]
    # Exactly one synthetic SKIPPED outcome for the acceptance task, naming only the parked feature.
    skipped = [o for o in res.outcomes if o.result == "SKIPPED"]
    assert len(skipped) == 1
    assert skipped[0].task == ACCEPTANCE_TASK_SLUG
    assert "feature-b" in skipped[0].detail
    assert "feature-a" not in skipped[0].detail        # merged features are NOT named
    # Teardown still converges normally (the guard is a CODE-loop continue, not an early return).
    assert res.outcome == "complete" and res.restart_ok
    assert _final_phase(tmp_path) == ss.PHASE_RECOVERED  # healthy runs now END terminal (f13742f: the driver stamps its own last act)


def test_acceptance_runs_when_all_features_merged(tmp_path):
    # No-op proof: when every preceding feature MERGED, the acceptance task RUNS exactly as
    # before — the guard must not fire on the healthy path.
    calls = []
    res = _driver(tmp_path, _ops(calls), tasks=_gated_tasks()).run()  # default run_task -> all MERGED
    assert ("task", ACCEPTANCE_TASK_SLUG) in calls
    assert calls == ["load", ("task", "feature-a"), ("task", "feature-b"),
                     ("task", ACCEPTANCE_TASK_SLUG), ("report", "R1", 3),
                     "disarm", "stop", "restart"]
    assert len(res.outcomes) == 3 and all(o.result == "MERGED" for o in res.outcomes)


# ---- (2b) GPU wait-verify gate (#670 run-2) -------------------------------


def test_gpu_gate_aborts_when_gpu_still_busy(tmp_path):
    # Probe says the GPU hasn't released (the 14B context didn't clear) -> abort-to-safe;
    # the 30B is NEVER loaded onto a busy GPU, and the NEVER-ZERO teardown restores the 14B.
    calls = []
    ops = _ops(calls, gpu_free_gb=lambda: 5.0)  # < the 15 GiB 30B need
    res = _driver(tmp_path, ops, gpu_gate_gb=15.0, gpu_settle_timeout_s=0.0).run()
    assert res.outcome == "gpu-gate-abort"
    assert "load" not in calls
    assert "disarm" in calls and "stop" in calls and "restart" in calls


def test_gpu_gate_proceeds_when_gpu_clear(tmp_path):
    calls = []
    ops = _ops(calls, gpu_free_gb=lambda: 20.0)  # >= need -> load proceeds
    res = _driver(tmp_path, ops, gpu_gate_gb=15.0).run()
    assert res.outcome == "complete" and "load" in calls


def test_gpu_gate_proceeds_when_probe_unavailable(tmp_path):
    # None (unreadable iGPU probe) -> proceed on the graceful 14B unload; never block the swap.
    calls = []
    ops = _ops(calls, gpu_free_gb=lambda: None)
    res = _driver(tmp_path, ops, gpu_gate_gb=15.0).run()
    assert res.outcome == "complete" and "load" in calls


def test_gpu_gate_waits_for_release_then_proceeds(tmp_path):
    # Wait-verify: busy on the first polls, clear on the next -> it WAITS then loads, rather
    # than aborting prematurely while the 14B is mid-release.
    calls = []
    seq = iter([8.0, 8.0, 18.0])  # busy, busy, then clear
    ops = _ops(calls, gpu_free_gb=lambda: next(seq))
    res = _driver(tmp_path, ops, gpu_gate_gb=15.0,
                  gpu_settle_timeout_s=30.0, gpu_settle_poll_s=1.0).run()
    assert res.outcome == "complete" and "load" in calls


# ---- progress trail (restart-surviving, #670) -----------------------------


def test_progress_trail_happy_path(tmp_path):
    progress: list = []
    _driver(tmp_path, _ops([], write_progress=lambda m: progress.append(m))).run()
    joined = " | ".join(progress).lower()
    assert "loading the 30b" in joined          # gate passed -> loading
    assert "coder fleet is running" in joined   # 30B up -> fleet runs the tasks
    assert "swapping the 14b back" in joined     # teardown
    assert "14b is back" in joined               # 14B restored


def test_progress_trail_gate_abort(tmp_path):
    progress: list = []
    # available below the gate -> abort-to-safe; never loads the 30B, still restores the 14B.
    _driver(tmp_path, _ops([], available_gb=lambda: 5.0,
                           write_progress=lambda m: progress.append(m))).run()
    joined = " | ".join(progress).lower()
    assert "aborted safely" in joined and "restoring the 14b" in joined
    assert "loading the 30b" not in joined       # the 30B was never loaded
    assert "14b is back" in joined               # never-zero: the 14B is restored


def test_progress_trail_restart_failure(tmp_path):
    progress: list = []
    _driver(tmp_path, _ops([], backend_ready=lambda: False,   # never comes back up
                           write_progress=lambda m: progress.append(m)),
            restart_retries=1).run()
    joined = " | ".join(progress).lower()
    assert "did not restart" in joined and "restart blarai to recover" in joined


# ---- never-zero on every fail-path ----------------------------------------


def test_gate_abort_does_not_load_but_restores(tmp_path):
    calls = []
    res = _driver(tmp_path, _ops(calls, available_gb=lambda: 20.0)).run()
    assert res.outcome == "gate-abort" and not res.loaded_30b
    assert "20.0" in res.message and "free something or retry" in res.message
    assert "load" not in calls                                # never loaded the 30B
    assert calls == ["disarm", "stop", "restart"]             # never-zero restore


def test_settle_timeout_restores(tmp_path):
    calls = []
    res = _driver(tmp_path, _ops(calls, backend_alive=lambda: True),
                  settle_timeout_s=0.05, settle_poll_s=0.01).run()
    assert res.outcome == "settle-timeout"
    assert "load" not in calls
    assert "disarm" in calls and "stop" in calls and "restart" in calls


def test_load_fail_restores(tmp_path):
    calls = []
    res = _driver(tmp_path, _ops(calls, wait_ready=lambda: False)).run()
    assert res.outcome == "load-fail"
    assert ("task", "a") not in calls                         # no tasks ran
    assert "disarm" in calls and "stop" in calls and "restart" in calls


def test_never_zero_on_run_task_exception(tmp_path):
    calls = []

    def boom(_t):
        raise RuntimeError("fleet exploded")

    with pytest.raises(RuntimeError):
        _driver(tmp_path, _ops(calls, run_task=boom)).run()
    # the teardown STILL restored the assistant before re-raising
    assert "disarm" in calls and "stop" in calls and "restart" in calls
    assert _final_phase(tmp_path) == ss.PHASE_RECOVERED  # healthy runs now END terminal (f13742f: the driver stamps its own last act)


# ---- per-task cancel ------------------------------------------------------


def test_cancel_is_per_task(tmp_path):
    calls = []
    state = {"n": 0}

    def cancel():
        state["n"] += 1
        return state["n"] > 1          # not cancelled before task a; cancelled before b

    res = _driver(tmp_path, _ops(calls, cancel_requested=cancel)).run()
    assert res.outcome == "cancelled" and res.cancelled
    assert len(res.outcomes) == 1                              # only task a ran
    assert ("task", "a") in calls and ("task", "b") not in calls
    assert "disarm" in calls and "stop" in calls and "restart" in calls


# ---- disarm-before-stop ---------------------------------------------------


def test_disarm_strictly_before_stop(tmp_path):
    calls = []
    _driver(tmp_path, _ops(calls)).run()
    assert calls.index("disarm") < calls.index("stop")


# ---- RESTART-AO bounded retry + out-of-band signal ------------------------


def test_restart_retries_then_signals_failure(tmp_path):
    calls = []
    res = _driver(tmp_path, _ops(calls, backend_ready=lambda: False),
                  restart_retries=3).run()
    assert res.outcome == "complete"           # the run itself finished
    assert res.restart_ok is False
    assert calls.count("restart") == 3
    assert _has(calls, "signal")               # loud out-of-band failure
    assert _final_phase(tmp_path) == ss.PHASE_FAILED


def test_restart_succeeds_second_try_no_signal(tmp_path):
    calls = []
    ready = {"n": 0}

    def backend_ready():
        ready["n"] += 1
        return ready["n"] >= 2                  # fails once, then comes up

    res = _driver(tmp_path, _ops(calls, backend_ready=backend_ready),
                  restart_retries=3).run()
    assert res.restart_ok is True
    assert calls.count("restart") == 2
    assert not _has(calls, "signal")


# ---- report is the cumulative across the per-task loop ---------------------


def test_report_written_once_with_all_outcomes(tmp_path):
    calls = []
    three = [{"repo": "X", "task": t, "prompt": "p"} for t in ("a", "b", "c")]
    _driver(tmp_path, _ops(calls), tasks=three).run()
    reports = [c for c in calls if isinstance(c, tuple) and c[0] == "report"]
    assert reports == [("report", "R1", 3)]    # one cumulative write, all 3 tasks


# ==========================================================================
# #670 Problem 2 — out-of-band budget watchdog + never-zero teardown hardening
# ==========================================================================


# ---- the pure deadline predicate ------------------------------------------


def test_should_abort_run_pure():
    assert sd.should_abort_run(elapsed_s=10.0, budget_s=5.0) is True
    assert sd.should_abort_run(elapsed_s=3.0, budget_s=5.0) is False
    assert sd.should_abort_run(elapsed_s=10.0, budget_s=0.0) is False    # 0 disables
    assert sd.should_abort_run(elapsed_s=10.0, budget_s=-1.0) is False   # negative disables


# ---- the watchdog loop: request_stop THEN abort, in order, once ------------


def test_run_budget_watchdog_fires_stop_then_abort_at_deadline():
    events = []
    clock = iter([0.0, 0.5, 1.0, 1.5])
    sd.run_budget_watchdog(
        budget_s=1.0, finished=lambda: False,
        abort=lambda: events.append("abort"),
        request_stop=lambda: events.append("stop"),
        poll_s=0.0, sleep=lambda _s: None, monotonic=lambda: next(clock),
    )
    assert events == ["stop", "abort"]   # stop strictly before abort, then returns


def test_run_budget_watchdog_noop_when_finished_early():
    events = []
    sd.run_budget_watchdog(
        budget_s=1.0, finished=lambda: True,       # already finished -> never aborts
        abort=lambda: events.append("abort"),
        request_stop=lambda: events.append("stop"),
        poll_s=0.0, sleep=lambda _s: None, monotonic=lambda: 999.0,
    )
    assert events == []                            # clean run -> no stop, no abort


def test_run_budget_watchdog_finished_during_sleep_no_abort():
    # Obligation A (structural): if `finished` becomes True during the sleep, the FIRST thing the
    # next iteration checks is `finished` -> it returns WITHOUT aborting, even though the deadline
    # is now past. (A loop that checked the deadline first would fire abort here.)
    events = []
    state = {"finished": False}
    reads = iter([0.0, 0.5])                       # start, then iter-1 elapsed (< budget)
    sd.run_budget_watchdog(
        budget_s=1.0, finished=lambda: state["finished"],
        abort=lambda: events.append("abort"),
        request_stop=lambda: events.append("stop"),
        poll_s=0.0, sleep=lambda _s: state.__setitem__("finished", True),
        monotonic=lambda: next(reads, 99.0),
    )
    assert events == []


# ---- BudgetWatchdog lifecycle ---------------------------------------------


def test_budget_watchdog_disabled_spawns_no_thread():
    wd = sd.BudgetWatchdog(budget_s=0.0, abort=lambda: None, request_stop=lambda: None)
    wd.start()
    assert wd._thread is None     # the disable path spawns no daemon
    wd.stop()                     # idempotent + exception-proof — no AttributeError


def test_budget_watchdog_real_thread_stop_joins_clean():
    aborts = []
    wd = sd.BudgetWatchdog(
        budget_s=1000.0,          # deadline never reached during the test
        abort=lambda: aborts.append("abort"), request_stop=lambda: None, poll_s=0.001,
    )
    wd.start()
    assert wd._thread is not None
    wd.stop()                     # set finished + UNBOUNDED join (not join(timeout))
    assert wd._thread is None     # joined + cleared
    assert aborts == []           # never aborted (deadline never hit; stop joined cleanly)


# ---- never-zero on a BaseException (obligation: teardown still restores) ---


def test_never_zero_on_base_exception(tmp_path):
    calls = []

    def boom(_t):
        raise KeyboardInterrupt()          # BaseException, NOT Exception

    with pytest.raises(KeyboardInterrupt):
        _driver(tmp_path, _ops(calls, run_task=boom)).run()
    assert "disarm" in calls and "stop" in calls and "restart" in calls
    assert _final_phase(tmp_path) == ss.PHASE_RECOVERED  # healthy runs now END terminal (f13742f: the driver stamps its own last act)


def test_teardown_step_raise_still_restarts(tmp_path):
    # A teardown STEP that raises must NOT mask the run nor skip the 14B restore (_guard catches).
    calls = []

    def boom_disarm():
        calls.append("disarm")
        raise RuntimeError("disarm exploded")

    res = _driver(tmp_path, _ops(calls, disarm_watchdog=boom_disarm)).run()
    assert res.outcome == "complete"
    assert "restart" in calls               # the restore STILL ran past the failed step


def test_restart_baseexception_retries_and_preserves_original(tmp_path):
    # MERGE-GATE catch (#670 P2): a BaseException from restart_launcher/backend_ready (reachable —
    # the driver is spawned CREATE_NEW_PROCESS_GROUP) must NOT escape _restart_with_retry, abandon
    # the loop after one unverified attempt, skip backend_ready, or mask the ORIGINAL exception.
    calls = []
    attempts = {"n": 0}

    def flaky_restart():
        attempts["n"] += 1
        calls.append(("restart", attempts["n"]))
        if attempts["n"] == 1:
            raise KeyboardInterrupt("ctrl-break during the relaunch")   # BaseException mid-restore

    ready = {"n": 0}

    def backend_ready():
        ready["n"] += 1
        calls.append(("ready", ready["n"]))
        return ready["n"] >= 2                                          # down after #1, up after #2

    def boom_task(_t):
        raise RuntimeError("the ORIGINAL task failure")                 # the run's own exception

    with pytest.raises(RuntimeError, match="the ORIGINAL task failure"):
        _driver(tmp_path, _ops(calls, run_task=boom_task,
                               restart_launcher=flaky_restart, backend_ready=backend_ready),
                restart_retries=3).run()
    assert ("restart", 2) in calls          # (a) attempt 2 ran despite the BaseException on #1
    assert ("ready", 1) in calls and ("ready", 2) in calls   # (b) backend_ready consulted each time
    # (c) the 14B restore was reached (it came up on attempt 2); (d) the ORIGINAL RuntimeError
    #     propagated — NOT the injected KeyboardInterrupt (pytest.raises match asserts it).


# ---- fail-loud verify-the-stop --------------------------------------------


def test_verify_ovms_still_resident_signals(tmp_path):
    # OVMS never unloads -> after the FULL poll window AND a forced retry (+ post-retry poll),
    # signal_failure fires (genuine, not premature). The 14B restore STILL runs (#670 B2).
    calls = []
    _driver(tmp_path, _ops(calls, ovms_alive=lambda: True),      # never stops
            ovms_stop_timeout_s=5.0, ovms_stop_poll_s=1.0,
            ovms_stop_retry_timeout_s=5.0).run()
    assert calls.count("stop") == 2         # initial stop + the forced retry
    assert _has(calls, "signal")            # LOUD: signal_failure fired AFTER the window
    assert "restart" in calls               # 14B restore STILL ran (fail-soft)


def test_verify_ovms_clears_during_poll_no_signal(tmp_path):
    # The #670 B2 fix: a slow ~15 GB unload that finishes a couple polls later is NOT a
    # failure. The POLL catches it within the window -> NO forced retry, NO false alarm
    # (the old check-then-one-retry fired before the big-model unload completed).
    calls = []
    seq = iter([True, True, False])         # resident for two polls, then gone
    _driver(tmp_path, _ops(calls, ovms_alive=lambda: next(seq)),
            ovms_stop_timeout_s=10.0, ovms_stop_poll_s=1.0).run()
    assert calls.count("stop") == 1         # ONLY the initial stop — no forced retry needed
    assert not _has(calls, "signal")        # cleared within the window -> no false alarm
    assert "restart" in calls               # 14B restore still ran


def test_verify_ovms_clears_after_forced_retry_no_signal(tmp_path):
    # OVMS rides out the whole poll window, but the FORCED Stop-Process takes -> no signal.
    calls = []
    alive = {"v": True}

    def stop():
        calls.append("stop")
        if calls.count("stop") >= 2:        # the forced retry actually stops it
            alive["v"] = False

    _driver(tmp_path, _ops(calls, ovms_alive=lambda: alive["v"], stop_ovms=stop),
            ovms_stop_timeout_s=3.0, ovms_stop_poll_s=1.0,
            ovms_stop_retry_timeout_s=3.0).run()
    assert calls.count("stop") == 2         # initial stop + forced retry (which worked)
    assert not _has(calls, "signal")        # forced retry cleared it -> no false alarm
    assert "restart" in calls


def test_verify_ovms_default_false_keeps_single_stop(tmp_path):
    # The default ovms_alive (False) -> the poll reports gone immediately -> the legacy
    # single-stop sequence, no forced retry, no signal.
    calls = []
    _driver(tmp_path, _ops(calls)).run()
    assert calls.count("stop") == 1 and not _has(calls, "signal")


# ---- worktree sweep: every exit path, AFTER the restore, off the default ---


def test_worktree_sweep_runs_after_restore(tmp_path):
    calls = []
    _driver(tmp_path, _ops(calls, sweep_worktrees=lambda: calls.append("sweep"))).run()
    assert "sweep" in calls
    assert calls.index("restart") < calls.index("sweep")   # AFTER the 14B restore (LA refinement)


def test_worktree_sweep_runs_on_gate_abort(tmp_path):
    calls = []
    _driver(tmp_path, _ops(calls, available_gb=lambda: 5.0,
                           sweep_worktrees=lambda: calls.append("sweep"))).run()
    assert "sweep" in calls and "load" not in calls        # swept even though the 30B never loaded


def test_worktree_sweep_runs_on_exception_path(tmp_path):
    calls = []

    def boom(_t):
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError):
        _driver(tmp_path, _ops(calls, run_task=boom,
                               sweep_worktrees=lambda: calls.append("sweep"))).run()
    assert "sweep" in calls               # teardown swept before the re-raise


def test_begin_teardown_called_at_entry(tmp_path):
    # Teardown ENTRY inert-ifies the abort (begin_teardown) BEFORE any stop step (obligation A).
    calls = []
    _driver(tmp_path, _ops(calls, begin_teardown=lambda: calls.append("begin"))).run()
    assert calls.index("begin") < calls.index("disarm")


# ---- budget-timeout: stop_requested breaks the loop / pre-empts the load ---


def test_budget_stop_breaks_loop_and_restores(tmp_path):
    calls = []
    pre = iter([False, False, False])     # settle, gate, gpu-clear pass; then the loop sees True
    _ops_kw = _ops(calls, stop_requested=lambda: next(pre, True))
    res = _driver(tmp_path, _ops_kw).run()
    assert res.outcome == "budget-timeout"
    assert "load" in calls                                  # tasks reached -> the 30B loaded
    assert "disarm" in calls and "stop" in calls and "restart" in calls   # never-zero restore


def test_budget_stop_before_load_skips_30b(tmp_path):
    calls = []
    res = _driver(tmp_path, _ops(calls, stop_requested=lambda: True)).run()  # fires immediately
    assert res.outcome == "budget-timeout"
    assert "load" not in calls            # the expensive 30B load was never paid
    assert "disarm" in calls and "stop" in calls and "restart" in calls


def test_budget_watchdog_started_inside_run_and_stopped(tmp_path):
    # An injected watchdog is started (run entry) + stopped (teardown entry) on the happy path.
    events = []

    class _FakeWatchdog:
        def start(self):
            events.append("start")

        def stop(self):
            events.append("stop-wd")

    _driver(tmp_path, _ops([]), budget_watchdog=_FakeWatchdog()).run()
    assert events == ["start", "stop-wd"]   # started once, stopped once


def test_budget_watchdog_stopped_even_on_exception(tmp_path):
    events = []

    class _FakeWatchdog:
        def start(self):
            events.append("start")

        def stop(self):
            events.append("stop-wd")

    def boom(_t):
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError):
        _driver(tmp_path, _ops([], run_task=boom), budget_watchdog=_FakeWatchdog()).run()
    assert events == ["start", "stop-wd"]   # stopped at teardown entry despite the exception


# ==========================================================================
# #688 Phase 3 — end-of-run VLM design loop (critique -> feed back -> fix -> re-critique)
# ==========================================================================


def _design_fixes(calls):
    """The design-fix task slugs that actually ran (run_task) during a recorded run."""
    return [c[1] for c in calls
            if isinstance(c, tuple) and c[0] == "task" and str(c[1]).startswith("design-fix")]


def test_design_phase_iterates_and_feeds_feedback_back(tmp_path):
    # The CLOSED LOOP: critique says iterate -> the 30B is reloaded -> a fix task whose prompt
    # CARRIES the reviewer feedback runs -> a second critique. Two laps; the second clears it.
    calls = []
    captured = {"design": [], "fix_prompts": []}
    seq = iter([
        {"should_iterate": True, "needs_work": True, "feedback": "FIX-THE-HERO-SPACING",
         "layout_hard": True, "capture_tier": "web"},
        {"should_iterate": False, "needs_work": False, "feedback": "looks intentional now",
         "layout_hard": False, "capture_tier": "web"},
    ])

    def design(app_dir, goal, vcj):
        captured["design"].append((app_dir, goal, vcj))
        calls.append("critique")
        return next(seq)

    def run_task(t):
        calls.append(("task", t["task"]))
        if str(t["task"]).startswith("design-fix"):
            captured["fix_prompts"].append(t["prompt"])
        return _outcome(t)

    res = _driver(tmp_path, _ops(calls, run_design_loop=design, run_task=run_task),
                  tasks=[_WEB_TASK]).run()

    assert res.outcome == "complete" and res.restart_ok
    assert calls.count("critique") == 2                       # critique -> fix -> re-critique
    assert _design_fixes(calls) == ["design-fix-1"]           # exactly one fix lap
    # the closed-loop FEEDBACK step: the fix prompt embeds the reviewer's critique verbatim.
    assert len(captured["fix_prompts"]) == 1
    assert "FIX-THE-HERO-SPACING" in captured["fix_prompts"][0]
    assert calls.count("load") == 2                           # initial CODE load + the fix reload
    # the critique always sees the design target's app_dir / goal / criteria.
    assert captured["design"] == [
        (_WEB_TASK["repo"], _WEB_TASK["goal"], _WEB_TASK["visual_criteria_json"])
    ] * 2
    # the LAST critique result is carried on the driver result (a loop signal, not a verdict).
    assert res.design_signal is not None and res.design_signal["should_iterate"] is False
    # never-zero restore still reached after the design loop.
    assert "disarm" in calls and "restart" in calls
    assert _final_phase(tmp_path) == ss.PHASE_RECOVERED  # healthy runs now END terminal (f13742f: the driver stamps its own last act)


def test_design_phase_stops_when_no_iterate(tmp_path):
    # First critique says it's fine -> NO fix lap, NO reload; one pass only.
    calls = []

    def design(app_dir, goal, vcj):
        calls.append("critique")
        return {"should_iterate": False, "needs_work": False, "feedback": "ok",
                "layout_hard": False, "capture_tier": "web"}

    res = _driver(tmp_path, _ops(calls, run_design_loop=design), tasks=[_WEB_TASK]).run()
    assert calls.count("critique") == 1
    assert _design_fixes(calls) == []          # no fix task ran
    assert calls.count("load") == 1            # the 30B was never reloaded
    assert "restart" in calls                  # teardown reached


def test_design_phase_stops_at_iteration_cap(tmp_path):
    # A never-satisfied critic: should_iterate stays True -> bounded by max_design_iterations.
    calls = []

    def design(app_dir, goal, vcj):
        calls.append("critique")
        return {"should_iterate": True, "needs_work": True, "feedback": "still off",
                "layout_hard": False, "capture_tier": "web"}

    res = _driver(tmp_path, _ops(calls, run_design_loop=design), tasks=[_WEB_TASK],
                  max_design_iterations=2).run()
    assert calls.count("critique") == 2                  # exactly the cap
    assert _design_fixes(calls) == ["design-fix-1"]      # cap - 1 fix laps
    assert res.outcome == "complete" and "restart" in calls


def test_design_phase_fail_soft_on_fix_run_task_raise(tmp_path):
    # A fix-task run_task that RAISES is swallowed (design is best-effort) -> the run still
    # completes and the 14B is restored (NEVER-ZERO). The exception does NOT propagate.
    calls = []

    def design(app_dir, goal, vcj):
        calls.append("critique")
        return {"should_iterate": True, "needs_work": True, "feedback": "fix it",
                "layout_hard": False, "capture_tier": "web"}

    def run_task(t):
        if str(t["task"]).startswith("design-fix"):
            raise RuntimeError("fleet exploded on the design fix")
        calls.append(("task", t["task"]))
        return _outcome(t)

    res = _driver(tmp_path, _ops(calls, run_design_loop=design, run_task=run_task),
                  tasks=[_WEB_TASK]).run()
    assert res.outcome == "complete"                 # design raise swallowed; run not crashed
    assert calls.count("critique") == 1              # raised on the first fix, before re-critique
    assert "disarm" in calls and "restart" in calls  # never-zero restore still ran


def test_design_phase_breaks_when_reload_fails(tmp_path):
    # The fix needs the coder back; if load_30b can't reload it, the loop stops cleanly.
    calls = []
    loads = {"n": 0}

    def load():
        loads["n"] += 1
        calls.append("load")
        return loads["n"] == 1          # the CODE-loop load succeeds; the fix reload fails

    def design(app_dir, goal, vcj):
        calls.append("critique")
        return {"should_iterate": True, "needs_work": True, "feedback": "fix it",
                "layout_hard": False, "capture_tier": "web"}

    res = _driver(tmp_path, _ops(calls, run_design_loop=design, load_30b=load),
                  tasks=[_WEB_TASK]).run()
    assert calls.count("critique") == 1     # critiqued once; reload failed -> no second critique
    assert _design_fixes(calls) == []       # no fix task ran (reload failed first)
    assert "restart" in calls               # teardown reached


def test_design_phase_skipped_for_command_line(tmp_path):
    calls = []
    design_calls = []
    cli_task = {**_WEB_TASK, "surface": "command-line"}
    res = _driver(tmp_path, _ops(calls, run_design_loop=lambda a, g, v: design_calls.append(1)),
                  tasks=[cli_task]).run()
    assert design_calls == []                # non-visual surface -> never critiqued
    assert res.design_signal is None
    assert calls.count("stop") == 1          # only the teardown stop; no design model churn


def test_design_phase_skipped_for_empty_visual_criteria(tmp_path):
    calls = []
    design_calls = []
    no_criteria = {**_WEB_TASK, "visual_criteria_json": "[]"}
    res = _driver(tmp_path, _ops(calls, run_design_loop=lambda a, g, v: design_calls.append(1)),
                  tasks=[no_criteria]).run()
    assert design_calls == []                # "[]" -> nothing to judge -> skipped
    assert res.design_signal is None


def test_design_phase_skipped_when_nothing_merged(tmp_path):
    calls = []
    design_calls = []

    def parked(t):
        calls.append(("task", t["task"]))
        return TaskOutcome(task=t["task"], outcome="processed", result="PARKED",
                           detail="not merged")

    res = _driver(tmp_path, _ops(calls, run_task=parked,
                                 run_design_loop=lambda a, g, v: design_calls.append(1)),
                  tasks=[_WEB_TASK]).run()
    assert design_calls == []                # no MERGED code -> nothing built to review
    assert res.design_signal is None


def test_design_phase_skipped_when_cancel_requested(tmp_path):
    # cancel is False during the (single) per-task check, True at the design-phase check, so the
    # run completes but the design loop is skipped — isolating the cancel guard from the loop.
    calls = []
    design_calls = []
    state = {"n": 0}

    def cancel():
        state["n"] += 1
        return state["n"] > 1            # False for the per-task check; True at the design check

    res = _driver(tmp_path, _ops(calls, cancel_requested=cancel,
                                 run_design_loop=lambda a, g, v: design_calls.append(1)),
                  tasks=[_WEB_TASK]).run()
    assert res.outcome == "complete"         # the CODE loop did not cancel
    assert design_calls == []                # the design phase was skipped by the cancel guard
    assert res.design_signal is None


def test_design_progress_is_suggestion_not_verdict(tmp_path):
    # The progress note is the reviewer's SUGGESTION (loop signal), never a "verified/passed/done"
    # verdict — the operator's eyeball decides. It leads with the hard layout finding.
    progress = []

    def design(app_dir, goal, vcj):
        return {"should_iterate": False, "needs_work": True, "feedback": "tighten the spacing",
                "layout_hard": True, "capture_tier": "web"}

    _driver(tmp_path, _ops([], run_design_loop=design,
                           write_progress=lambda m: progress.append(m)),
            tasks=[_WEB_TASK]).run()
    note = next(m for m in progress if "design reviewer" in m.lower())
    low = note.lower()
    assert "judge for yourself" in low
    assert "layout" in low                   # led with the deterministic layout finding
    assert "tighten the spacing" in low      # then the VLM feedback
    for banned in ("verified", "passed", "done"):
        assert banned not in low


# ==========================================================================
# #687 task 2 — cross-model 14B code critic (post-merge; BEFORE the design loop)
# ==========================================================================

#: A simple merged task with a repo but NO visual surface — isolates the critic phase from
#: the design phase (``_design_target`` returns None, so no ``stop_ovms`` from design churn).
_MERGED_TASK = {"repo": "C:/proj/app", "task": "add-feature", "prompt": "build it"}


def _critic_fixes(calls):
    """The critic-fix task slugs that actually ran (run_task) during a recorded run."""
    return [c[1] for c in calls
            if isinstance(c, tuple) and c[0] == "task" and str(c[1]).startswith("critic-fix")]


def test_critic_phase_dormant_with_noop_is_call_list_identical(tmp_path):
    # DORMANT-safe regression lock: with _noop_critic wired (the default) the call list is
    # byte-identical to a pre-critic run.  No extra stop/load/any call appears.
    calls = []
    res = _driver(tmp_path, _ops(calls), tasks=[_MERGED_TASK]).run()
    assert res.outcome == "complete" and res.restart_ok
    assert calls == ["load", ("task", "add-feature"), ("report", "R1", 1),
                     "disarm", "stop", "restart"]
    # critic_signal is set even by the noop (one pass -> UNCLEAR / no iterate).
    assert res.critic_signal is not None
    assert res.critic_signal["should_iterate"] is False


def test_critic_phase_logs_active_when_enabled(tmp_path):
    # False-dormant-trap fix: the phase announces ACTIVE/DORMANT so a misrouted
    # BLARAI_ENABLE_CRITIC (exported on the wrong process) is observable in the trail.
    progress: list = []
    _driver(tmp_path, _ops([], critic_enabled=True,
                           write_progress=lambda m: progress.append(m)),
            tasks=[_MERGED_TASK]).run()
    joined = " | ".join(progress).lower()
    assert "code critic is active" in joined
    assert "dormant" not in joined


def test_critic_phase_logs_dormant_when_disabled(tmp_path):
    # critic_enabled defaults False (the shipped default) -> the trail says DORMANT and names the var.
    progress: list = []
    _driver(tmp_path, _ops([], write_progress=lambda m: progress.append(m)),
            tasks=[_MERGED_TASK]).run()
    joined = " | ".join(progress).lower()
    assert "code critic is dormant" in joined
    assert "not seen by swap_driver" in joined


def test_critic_phase_fires_and_sets_signal(tmp_path):
    # A MERGE verdict: one pass, no fix lap, critic_signal populated.
    calls = []
    captured: list = []

    def critic(app_dir, base_branch, base_sha=""):
        captured.append((app_dir, base_branch))
        calls.append("critic")
        return {"should_iterate": False, "verdict": "MERGE", "findings": ""}

    res = _driver(tmp_path, _ops(calls, run_critic=critic), tasks=[_MERGED_TASK]).run()
    assert res.outcome == "complete"
    assert calls.count("critic") == 1
    assert _critic_fixes(calls) == []          # no fix lap
    assert calls.count("load") == 1            # only the CODE-loop load
    assert captured == [("C:/proj/app", "main")]
    assert res.critic_signal is not None
    assert res.critic_signal["verdict"] == "MERGE"
    assert res.critic_signal["should_iterate"] is False
    assert "disarm" in calls and "restart" in calls


def test_critic_phase_iterates_and_feeds_findings_back(tmp_path):
    # CLOSED LOOP: FIX FIRST -> reload 30B -> fix task (prompt carries findings) -> re-critique.
    calls = []
    captured_prompts: list = []
    seq = iter([
        {"should_iterate": True, "verdict": "FIX FIRST",
         "findings": "1. app/main.py:42 - empty input - raises KeyError"},
        {"should_iterate": False, "verdict": "MERGE", "findings": ""},
    ])

    def critic(app_dir, base_branch, base_sha=""):
        calls.append("critic")
        return next(seq)

    def run_task(t):
        calls.append(("task", t["task"]))
        if str(t["task"]).startswith("critic-fix"):
            captured_prompts.append(t["prompt"])
        return _outcome(t)

    res = _driver(tmp_path, _ops(calls, run_critic=critic, run_task=run_task),
                  tasks=[_MERGED_TASK]).run()

    assert res.outcome == "complete" and res.restart_ok
    assert calls.count("critic") == 2                         # critique -> fix -> re-critique
    assert _critic_fixes(calls) == ["critic-fix-1"]           # exactly one fix lap
    # the closed-loop FINDINGS step: the fix prompt embeds the critic's findings verbatim.
    assert len(captured_prompts) == 1
    assert "app/main.py:42" in captured_prompts[0]
    assert "KeyError" in captured_prompts[0]
    assert calls.count("load") == 2                           # CODE load + the fix reload
    # critic does NOT call stop_ovms — only teardown does.
    assert calls.count("stop") == 1
    # the LAST critic result is carried on the driver result (a loop signal, not a verdict).
    assert res.critic_signal is not None and res.critic_signal["verdict"] == "MERGE"
    assert _final_phase(tmp_path) == ss.PHASE_RECOVERED  # healthy runs now END terminal (f13742f: the driver stamps its own last act)


def test_critic_phase_stops_at_iteration_cap(tmp_path):
    # A never-satisfied critic: should_iterate stays True -> bounded by max_critic_iterations.
    calls = []

    def critic(app_dir, base_branch, base_sha=""):
        calls.append("critic")
        return {"should_iterate": True, "verdict": "FIX FIRST",
                "findings": "1. x.py:1 - x - wrong"}

    res = _driver(tmp_path, _ops(calls, run_critic=critic), tasks=[_MERGED_TASK],
                  max_critic_iterations=2).run()
    assert calls.count("critic") == 2                  # exactly the cap
    assert _critic_fixes(calls) == ["critic-fix-1"]    # cap - 1 fix laps
    assert res.outcome == "complete" and "restart" in calls


def test_critic_phase_fail_soft_on_fix_run_task_raise(tmp_path):
    # A fix-task run_task that RAISES is swallowed (critic is best-effort) -> run still completes
    # and the 14B is restored (NEVER-ZERO).
    calls = []

    def critic(app_dir, base_branch, base_sha=""):
        calls.append("critic")
        return {"should_iterate": True, "verdict": "FIX FIRST",
                "findings": "1. x.py:1 - x - wrong"}

    def run_task(t):
        if str(t["task"]).startswith("critic-fix"):
            raise RuntimeError("fleet exploded on the critic fix")
        calls.append(("task", t["task"]))
        return _outcome(t)

    res = _driver(tmp_path, _ops(calls, run_critic=critic, run_task=run_task),
                  tasks=[_MERGED_TASK]).run()
    assert res.outcome == "complete"              # critic raise swallowed; run not crashed
    assert calls.count("critic") == 1             # raised on the first fix, before re-critique
    assert "disarm" in calls and "restart" in calls


def test_critic_phase_breaks_when_reload_fails(tmp_path):
    # The fix needs the coder back; if load_30b fails, the loop stops cleanly.
    calls = []
    loads = {"n": 0}

    def load():
        loads["n"] += 1
        calls.append("load")
        return loads["n"] == 1      # the CODE-loop load succeeds; the fix reload fails

    def critic(app_dir, base_branch, base_sha=""):
        calls.append("critic")
        return {"should_iterate": True, "verdict": "FIX FIRST",
                "findings": "1. x.py:1 - x - wrong"}

    res = _driver(tmp_path, _ops(calls, run_critic=critic, load_30b=load),
                  tasks=[_MERGED_TASK]).run()
    assert calls.count("critic") == 1      # critiqued once; reload failed -> no second pass
    assert _critic_fixes(calls) == []      # no fix task ran (reload failed first)
    assert "restart" in calls              # teardown reached


def test_critic_phase_skipped_when_nothing_merged(tmp_path):
    calls = []
    critic_calls: list = []

    def parked(t):
        calls.append(("task", t["task"]))
        return TaskOutcome(task=t["task"], outcome="processed", result="PARKED",
                           detail="not merged")

    res = _driver(tmp_path, _ops(calls, run_task=parked,
                                 run_critic=lambda a, b, s="": critic_calls.append(1)),
                  tasks=[_MERGED_TASK]).run()
    assert critic_calls == []           # nothing merged -> _critic_target is None -> skipped
    assert res.critic_signal is None    # never set


def test_critic_phase_skipped_when_cancel_requested(tmp_path):
    # cancel is False during the per-task check; True at the critic-phase entry guard.
    calls = []
    critic_calls: list = []
    state = {"n": 0}

    def cancel():
        state["n"] += 1
        return state["n"] > 1      # False for the task; True at the critic phase check

    res = _driver(tmp_path, _ops(calls, cancel_requested=cancel,
                                 run_critic=lambda a, b, s="": critic_calls.append(1)),
                  tasks=[_MERGED_TASK]).run()
    assert res.outcome == "complete"    # the CODE loop did not cancel
    assert critic_calls == []           # the critic was skipped by the cancel guard
    assert res.critic_signal is None    # never set


def test_critic_phase_does_not_call_stop_ovms(tmp_path):
    # The critic does NOT call stop_ovms (unlike the design phase): the live impl uses
    # start-llm -Force internally to swap models. Only the teardown stop should appear.
    calls = []

    def critic(app_dir, base_branch, base_sha=""):
        calls.append("critic")
        return {"should_iterate": False, "verdict": "MERGE", "findings": ""}

    _driver(tmp_path, _ops(calls, run_critic=critic), tasks=[_MERGED_TASK]).run()
    assert calls.count("stop") == 1     # teardown only; the critic added no stop
    assert calls.count("critic") == 1   # the critic DID run


# ---- #693: the critic diffs from main's PRE-dispatch HEAD --------------------


def test_critic_receives_pre_dispatch_base_sha(tmp_path):
    # #693: a multi-commit agent branch fast-forwarded onto an unchanged main collapses to
    # linear history, so the script-side HEAD~1..HEAD fallback sees only the LAST commit.
    # The driver must record the repo's HEAD BEFORE its first task runs and hand the critic
    # that FIRST reading — never a post-merge head.
    calls = []
    heads = iter(["sha-pre-dispatch", "sha-after-task"])
    captured: list = []

    def critic(app_dir, base_branch, base_sha=""):
        captured.append((app_dir, base_sha))
        return {"should_iterate": False, "verdict": "MERGE", "findings": ""}

    _driver(tmp_path, _ops(calls, run_critic=critic,
                           repo_head=lambda repo: next(heads, "sha-late")),
            tasks=[_MERGED_TASK]).run()
    assert captured == [("C:/proj/app", "sha-pre-dispatch")]


def test_critic_base_sha_pinned_to_first_task_of_repo(tmp_path):
    # Two tasks in one repo: the base recorded before task 1 must survive task 2's
    # pre-task read (setdefault semantics) — the critic reviews ALL the merged work.
    calls = []
    heads = iter(["sha-0", "sha-1", "sha-2"])
    captured: list = []

    def critic(app_dir, base_branch, base_sha=""):
        captured.append(base_sha)
        return {"should_iterate": False, "verdict": "MERGE", "findings": ""}

    _driver(tmp_path, _ops(calls, run_critic=critic,
                           repo_head=lambda repo: next(heads, "sha-late")),
            tasks=_TASKS).run()
    assert captured == ["sha-0"]


def test_critic_base_sha_empty_when_head_unreadable(tmp_path):
    # repo_head raising must degrade to "" (the script-side Resolve-CriticRange fallback),
    # never crash the loop or invent a base.
    calls = []
    captured: list = []

    def critic(app_dir, base_branch, base_sha=""):
        captured.append(base_sha)
        return {"should_iterate": False, "verdict": "MERGE", "findings": ""}

    def boom(_repo):
        raise RuntimeError("git unavailable")

    res = _driver(tmp_path, _ops(calls, run_critic=critic, repo_head=boom),
                  tasks=[_MERGED_TASK]).run()
    assert res.outcome == "complete"
    assert captured == [""]


def test_critic_phase_fires_before_design_phase(tmp_path):
    # Ordering guarantee: the critic fires in the call list BEFORE the first design stop.
    # Use _WEB_TASK so BOTH phases are eligible (visual + merged).
    calls = []

    def critic(app_dir, base_branch, base_sha=""):
        calls.append("critic")
        return {"should_iterate": False, "verdict": "MERGE", "findings": ""}

    def design(app_dir, goal, vcj):
        calls.append("design")
        return {"should_iterate": False, "needs_work": False,
                "feedback": "", "layout_hard": False, "capture_tier": ""}

    _driver(tmp_path, _ops(calls, run_critic=critic, run_design_loop=design),
            tasks=[_WEB_TASK]).run()
    assert "critic" in calls and "design" in calls
    assert calls.index("critic") < calls.index("design")


def test_critic_target_finds_first_merged_with_repo(tmp_path):
    # _critic_target returns the task dict for the FIRST MERGED outcome that has a repo;
    # it skips PARKED outcomes even when they have a repo.
    calls = []
    seen_app_dirs: list = []
    tasks = [
        {"repo": "C:/repo-a", "task": "feat-a", "prompt": "pa"},
        {"repo": "C:/repo-b", "task": "feat-b", "prompt": "pb"},
    ]
    results = {"feat-a": "PARKED", "feat-b": "MERGED"}

    def run_task(t):
        calls.append(("task", t["task"]))
        return TaskOutcome(task=t["task"], outcome="processed",
                           result=results[t["task"]], detail="ok")

    def critic(app_dir, base_branch, base_sha=""):
        seen_app_dirs.append(app_dir)
        calls.append("critic")
        return {"should_iterate": False, "verdict": "MERGE", "findings": ""}

    _driver(tmp_path, _ops(calls, run_task=run_task, run_critic=critic),
            tasks=tasks).run()
    assert seen_app_dirs == ["C:/repo-b"]   # feat-a parked; feat-b is the first MERGED
