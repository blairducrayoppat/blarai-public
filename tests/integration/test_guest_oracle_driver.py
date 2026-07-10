"""Driver-level locks for the #744 guest-certified oracle seam (DORMANT).

Drives the REAL ``SwapDriver`` through injected ``SwapOps`` fakes (the house
pattern — ``tests/integration/test_swap_driver.py`` ``_ops()``), locking:

  * OFF (the shipped default) ⇒ BYTE-IDENTICAL today-behavior: the exact
    legacy call list, ZERO touches of either guest seam, no evidence write,
    no signal — the dormancy proof;
  * ON ⇒ EXACTLY ONE guest run per JOB, positioned in the RAM-free window
    (after stop-OVMS/UNLOAD-30B, before RESTART-AO), advisory-only;
  * fail-soft: a raising executor / evidence writer NEVER blocks the 14B
    restore; every degraded path is an honest ``not-run``;
  * divergence (host-pass/guest-fail) flagged in the certificate block;
  * verdict/attribution semantics untouched — the scorecard is identical
    with the knob on and off.
"""

from __future__ import annotations

import pytest

from shared.fleet import plan_graph as pg
from shared.fleet import swap_driver as sd
from shared.fleet.dispatch import TaskOutcome

_TASKS = [{"repo": "X", "task": "a", "prompt": "pa"},
          {"repo": "X", "task": "b", "prompt": "pb"}]

ORACLE_PATH = pg.DEFAULT_ORACLE_PATH


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


def _recording_guest(calls, result=None):
    def run_guest_oracle(repo, rel):
        calls.append(("guest_oracle", repo, rel))
        return result or {"status": "passed", "reason": "", "evidence": "exit 0"}

    return run_guest_oracle


def _record_block(calls):
    return lambda block: calls.append(("guest_block", block))


def _driver(tmp_path, ops, tasks=None, **kw):
    return sd.SwapDriver(
        run_id="R1", session_id="s1",
        tasks=_TASKS if tasks is None else tasks,
        swap_state_path=tmp_path / "swap.json", ops=ops,
        gate_gb=21.0, sleep=lambda _s: None, **kw,
    )


def _plan_fixture(tmp_path):
    repo = tmp_path / "proj"
    (repo / ".git").mkdir(parents=True, exist_ok=True)
    tasks = [
        {"repo": str(repo), "task": "storage", "prompt": "ps", "depends_on": []},
        {"repo": str(repo), "task": "report", "prompt": "pr", "depends_on": ["storage"]},
    ]
    raw = pg.build_plan_raw(plan_id="R1", goal="g", repo=str(repo), tasks=tasks,
                            criteria=["works"])
    result = pg.validate_plan(raw, projects_dir=tmp_path)
    assert result.ok and result.plan is not None
    store = pg.PlanStore(tmp_path / "plan.json", projects_dir=tmp_path)
    return store.write(result.plan), store, tasks, str(repo)


def _plan_driver(tmp_path, calls, *, host_status="passed", guest=None, **kw):
    plan, store, tasks, repo = _plan_fixture(tmp_path)
    overrides = dict(
        run_wave_gate=lambda r: {"ok": True, "evidence": "pass"},
        run_job_oracle=lambda r, rel: (calls.append(("job_oracle", r, rel)),
                                       {"status": host_status, "evidence": "host run"})[1],
        run_guest_oracle=_recording_guest(calls, guest),
        write_guest_oracle=_record_block(calls),
        write_scorecard=lambda sc: calls.append(("scorecard", sc)),
    )
    overrides.update(kw.pop("ops_overrides", {}))   # a test's override wins
    ops = _ops(calls, **overrides)
    return _driver(tmp_path, ops, tasks=tasks, plan=plan, plan_store=store, **kw), repo


def _guest_calls(calls):
    return [c for c in calls if isinstance(c, tuple) and c[0] == "guest_oracle"]


def _block(calls):
    for c in calls:
        if isinstance(c, tuple) and c[0] == "guest_block":
            return c[1]
    return None


# ---- OFF: byte-identical dormancy (the regression lock the design demands) ----


def test_off_default_flat_run_never_touches_guest_seams_exact_call_list(tmp_path):
    calls = []
    ops = _ops(calls,
               run_guest_oracle=_recording_guest(calls),
               write_guest_oracle=_record_block(calls))
    res = _driver(tmp_path, ops).run()   # guest_oracle_enabled NOT passed -> default False
    # EXACT legacy call list — the same sequence test_happy_path_full_sequence pins;
    # neither guest seam fired, no evidence write, no signal. Mutation-resistant:
    # calling the seam even once (e.g. dropping the enabled gate) breaks equality.
    assert calls == ["load", ("task", "a"), ("task", "b"), ("report", "R1", 2),
                     "disarm", "stop", "restart"]
    assert res.guest_oracle_signal is None


def test_off_explicit_false_plan_run_never_touches_guest_seams(tmp_path):
    calls = []
    driver, _repo = _plan_driver(tmp_path, calls, guest_oracle_enabled=False)
    res = driver.run()
    assert _guest_calls(calls) == [] and _block(calls) is None
    assert res.guest_oracle_signal is None


def test_off_scorecard_identical_to_on(tmp_path):
    # Verdict/attribution semantics are UNTOUCHED: the scorecard emitted with the
    # knob on equals the knob-off scorecard on every field except wall-clock.
    def scorecard(enabled):
        calls = []
        driver, _repo = _plan_driver(tmp_path, calls, guest_oracle_enabled=enabled)
        driver.run()
        sc = next(c[1] for c in calls if isinstance(c, tuple) and c[0] == "scorecard")
        sc.pop("wall_clock_s", None)
        ev = sc.get("evidence")
        if isinstance(ev, dict):
            ev.pop("plan", None)
        return sc

    off, on = scorecard(False), scorecard(True)
    assert on == off
    assert "guest_oracle" not in on      # the certificate lives BESIDE the scorecard


# ---- ON: one run per job, in the RAM-free window ------------------------------


def test_on_runs_once_per_job_in_the_ram_free_window(tmp_path):
    calls = []
    driver, repo = _plan_driver(tmp_path, calls, guest_oracle_enabled=True)
    res = driver.run()
    guests = _guest_calls(calls)
    assert guests == [("guest_oracle", repo, ORACLE_PATH)]      # EXACTLY once, per JOB
    # Window lock: after stop-OVMS (UNLOAD-30B), before RESTART-AO.
    i_stop, i_guest = calls.index("stop"), calls.index(guests[0])
    i_restart = calls.index("restart")
    assert i_stop < i_guest < i_restart
    # The advisory block was persisted and surfaced, host status recorded.
    block = _block(calls)
    assert block is not None and block["advisory"] is True
    assert block["status"] == "passed" and block["host_status"] == "passed"
    assert block["divergence"] is False
    assert res.guest_oracle_signal == block


def test_on_divergence_host_pass_guest_fail_is_flagged(tmp_path):
    calls = []
    driver, _repo = _plan_driver(
        tmp_path, calls, guest_oracle_enabled=True,
        guest={"status": "failed", "reason": "", "evidence": "1 failed in guest"})
    res = driver.run()
    block = _block(calls)
    assert block["divergence"] is True
    assert "DIVERGENCE" in block["evidence"]
    # Advisory only: the driver outcome is still complete; nothing verdict-shaped moved.
    assert res.outcome == "complete"


def test_on_guest_executor_raise_is_not_run_and_restore_proceeds(tmp_path):
    calls = []

    def exploding(repo, rel):
        calls.append(("guest_oracle", repo, rel))
        raise RuntimeError("vsock died")

    driver, _repo = _plan_driver(tmp_path, calls, guest_oracle_enabled=True,
                                 ops_overrides={"run_guest_oracle": exploding})
    res = driver.run()
    assert "restart" in calls                       # the 14B restore was never blocked
    assert res.restart_ok
    assert res.guest_oracle_signal["status"] == "not-run"
    assert res.guest_oracle_signal["reason"] == "guest-oracle-raised"


def test_on_evidence_writer_raise_is_fail_soft(tmp_path):
    calls = []

    def exploding_write(_block):
        raise OSError("disk full")

    driver, _repo = _plan_driver(tmp_path, calls, guest_oracle_enabled=True,
                                 ops_overrides={"write_guest_oracle": exploding_write})
    res = driver.run()
    assert "restart" in calls and res.restart_ok
    assert res.guest_oracle_signal is not None      # the signal still surfaced in-process


def test_on_flat_mode_records_honest_not_run_without_calling_executor(tmp_path):
    # Flat queue (no JobPlan) has no job-level oracle to certify — the block says so
    # and the executor is NEVER invoked (nothing would be shippable).
    calls = []
    ops = _ops(calls,
               run_guest_oracle=_recording_guest(calls),
               write_guest_oracle=_record_block(calls))
    res = _driver(tmp_path, ops, guest_oracle_enabled=True).run()
    assert _guest_calls(calls) == []
    block = _block(calls)
    assert (block["status"], block["reason"]) == ("not-run", "flat-queue-mode")
    assert res.guest_oracle_signal == block


def test_on_cancelled_run_records_not_run_without_calling_executor(tmp_path):
    calls = []
    cancelled = {"flag": False}

    def run_task(t):
        calls.append(("task", t["task"]))
        cancelled["flag"] = True                    # cancel lands after the first task
        return _outcome(t)

    driver, _repo = _plan_driver(
        tmp_path, calls, guest_oracle_enabled=True,
        ops_overrides={"run_task": run_task,
                       "cancel_requested": lambda: cancelled["flag"]})
    driver.run()
    assert _guest_calls(calls) == []
    block = _block(calls)
    assert (block["status"], block["reason"]) == ("not-run", "run-cancelled-or-stopped")


def test_on_host_oracle_not_run_records_not_run_without_calling_executor(tmp_path):
    calls = []
    driver, _repo = _plan_driver(tmp_path, calls, guest_oracle_enabled=True,
                                 host_status="not-run")
    driver.run()
    assert _guest_calls(calls) == []
    block = _block(calls)
    assert (block["status"], block["reason"]) == ("not-run", "host-oracle-not-run")


def test_on_nothing_merged_records_not_run_without_calling_executor(tmp_path):
    calls = []

    def parked(t):
        calls.append(("task", t["task"]))
        return TaskOutcome(task=t["task"], outcome="processed", result="PARKED", detail="p")

    driver, _repo = _plan_driver(tmp_path, calls, guest_oracle_enabled=True,
                                 ops_overrides={"run_task": parked})
    driver.run()
    assert _guest_calls(calls) == []
    block = _block(calls)
    assert (block["status"], block["reason"]) == ("not-run", "nothing-merged")


def test_on_guest_runs_even_when_host_failed_no_divergence(tmp_path):
    # A host-fail is still certified (the guest confirming the failure is evidence);
    # divergence flags ONLY the host-pass/guest-fail shape.
    calls = []
    driver, repo = _plan_driver(
        tmp_path, calls, guest_oracle_enabled=True, host_status="failed",
        guest={"status": "failed", "reason": "", "evidence": "1 failed"})
    driver.run()
    assert _guest_calls(calls) == [("guest_oracle", repo, ORACLE_PATH)]
    block = _block(calls)
    assert block["divergence"] is False and block["host_status"] == "failed"


def test_on_malformed_executor_result_is_fail_closed(tmp_path):
    calls = []

    def non_dict(repo, rel):
        calls.append(("guest_oracle", repo, rel))
        return "passed"                             # a string is NOT a result

    driver, _repo = _plan_driver(tmp_path, calls, guest_oracle_enabled=True,
                                 ops_overrides={"run_guest_oracle": non_dict})
    res = driver.run()
    assert res.guest_oracle_signal["status"] == "not-run"
    assert res.guest_oracle_signal["reason"] == "guest-oracle-non-dict"


# ---- default seam values (SwapOps constructed bare) ---------------------------


def test_swap_ops_defaults_are_dormant_not_run():
    ops = sd.SwapOps(
        available_gb=lambda: 0.0, backend_alive=lambda: False,
        load_30b=lambda: True, wait_ready=lambda: True,
        run_task=lambda t: None, cancel_requested=lambda: False,
        disarm_watchdog=lambda: None, stop_ovms=lambda: None,
        write_report=lambda r, o: None, restart_launcher=lambda: None,
        backend_ready=lambda: True, signal_failure=lambda m: None,
    )
    res = ops.run_guest_oracle("X", ORACLE_PATH)
    assert res["status"] == "not-run"               # never a silent pass
    assert ops.write_guest_oracle({"any": "block"}) is None
