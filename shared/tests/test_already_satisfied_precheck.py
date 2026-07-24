"""#1049 — the already-satisfied pre-check (dispatch-quality-ledger tuning candidate a).

Drives the REAL ``SwapDriver`` through injected ``SwapOps`` fakes (the house pattern —
``tests/integration/test_guest_oracle_driver.py``), locking:

  * OFF (the fail-closed default) ⇒ BYTE-IDENTICAL legacy dispatch: the pre-check seam
    is NEVER consulted and every wave dispatches — the toggle-off proof;
  * ON + oracle PASSES on the current tree ⇒ every still-pending task is recorded as
    an HONEST SKIP (reason + evidence on the outcome row, ``evidence.already_satisfied``
    on the scorecard, task status ``skipped`` — never a pass) and NO coder candidate is
    spent; the finish-line oracle still grades the tree independently and only its own
    pass mints GREEN;
  * FAIL-CLOSED: an oracle FAIL / not-run / raise / malformed result, a tree with no
    merge yet, or a failed wave gate each dispatch the wave exactly as before — a skip
    can never ride an undetermined condition;
  * verdict semantics: satisfied skips (and ONLY driver-recorded satisfied skips) count
    as delivered in ``compute_job_verdict``; a park-propagated skip still falls through
    to the legacy branches.
"""

from __future__ import annotations

import json
from dataclasses import replace as dc_replace

import pytest

from shared.fleet import plan_graph as pg
from shared.fleet import swap_driver as sd
from shared.fleet.dispatch import FleetDispatchConfig, TaskOutcome


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
        run_job_oracle=lambda r, rel: (calls.append(("job_oracle", r, rel)),
                                       {"status": "passed", "evidence": "exit 0"})[1],
        write_scorecard=lambda sc: calls.append(("scorecard", sc)),
    )
    base.update(overrides)
    return sd.SwapOps(**base)


def _recording_precheck(calls, result):
    def precheck(repo, rel):
        calls.append(("precheck", repo, rel))
        if isinstance(result, Exception):
            raise result
        return result

    return precheck


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
    return store.write(result.plan), store, tasks


def _plan_driver(tmp_path, calls, *, precheck_result=None, ops_overrides=None, **kw):
    plan, store, tasks = _plan_fixture(tmp_path)
    overrides = dict(ops_overrides or {})
    if precheck_result is not None:
        overrides["precheck_job_oracle"] = _recording_precheck(calls, precheck_result)
    ops = _ops(calls, **overrides)
    return sd.SwapDriver(
        run_id="R1", session_id="s1", tasks=tasks,
        swap_state_path=tmp_path / "swap.json", ops=ops,
        gate_gb=21.0, sleep=lambda _s: None,
        plan=plan, plan_store=store, **kw,
    )


def _scorecard(calls):
    for c in calls:
        if isinstance(c, tuple) and c[0] == "scorecard":
            return c[1]
    return None


def _task_calls(calls):
    return [c for c in calls if isinstance(c, tuple) and c[0] == "task"]


def _precheck_calls(calls):
    return [c for c in calls if isinstance(c, tuple) and c[0] == "precheck"]


# ---- OFF: byte-identical legacy dispatch (the toggle-off proof) -----------------


def test_off_default_never_consults_precheck_and_dispatches_every_wave(tmp_path):
    calls = []
    res = _plan_driver(
        tmp_path, calls,
        precheck_result={"status": "passed", "evidence": "exit 0"},
    ).run()   # already_satisfied_precheck NOT passed -> default False
    assert res.outcome == "complete"
    assert _precheck_calls(calls) == []                 # seam untouched — dormancy proof
    assert [c[1] for c in _task_calls(calls)] == ["storage", "report"]
    sc = _scorecard(calls)
    assert sc is not None and sc["verdict"] == "GREEN"
    assert "already_satisfied" not in sc["evidence"]


def test_off_explicit_false_never_consults_precheck(tmp_path):
    calls = []
    _plan_driver(
        tmp_path, calls,
        precheck_result={"status": "passed", "evidence": "exit 0"},
        already_satisfied_precheck=False,
    ).run()
    assert _precheck_calls(calls) == []
    assert [c[1] for c in _task_calls(calls)] == ["storage", "report"]


# ---- ON + PASS: the honest skip, no candidate spent ------------------------------


def test_on_pass_skips_remaining_wave_and_spends_no_candidate(tmp_path):
    calls = []
    res = _plan_driver(
        tmp_path, calls,
        precheck_result={"status": "passed", "evidence": "exit 0; 2 passed"},
        already_satisfied_precheck=True,
    ).run()
    assert res.outcome == "complete"
    # Wave 1 (storage) dispatched; wave 2 (report) skipped — ONE coder spend only.
    assert [c[1] for c in _task_calls(calls)] == ["storage"]
    assert len(_precheck_calls(calls)) == 1
    # The skip is LOUD: an explicit SKIPPED outcome row carrying reason + evidence.
    skip = [o for o in res.outcomes if getattr(o, "result", "") == "SKIPPED"]
    assert len(skip) == 1 and skip[0].task == "report"
    assert "already satisfied" in skip[0].detail
    assert "no coder candidate spent" in skip[0].detail
    assert "exit 0; 2 passed" in skip[0].detail
    # Scorecard: GREEN rides the FINISH-LINE oracle (which still ran), the task row
    # stays status=skipped (a skip is never relabeled a pass), and the audit trail
    # names the satisfied task.
    sc = _scorecard(calls)
    assert sc is not None and sc["verdict"] == "GREEN"
    rows = {t["id"]: t for t in sc["tasks"]}
    assert rows["storage"]["status"] == pg.STATUS_MERGED
    assert rows["report"]["status"] == pg.STATUS_SKIPPED
    assert sc["evidence"]["already_satisfied"] == "report"
    assert "\n" not in sc["evidence"]["already_satisfied"]
    assert "already-satisfied skip" in sc["notes"]
    assert any(c[0] == "job_oracle" for c in calls if isinstance(c, tuple))


def test_on_precheck_not_consulted_before_first_merge(tmp_path):
    calls = []
    _plan_driver(
        tmp_path, calls,
        precheck_result={"status": "passed", "evidence": "exit 0"},
        already_satisfied_precheck=True,
    ).run()
    # The one pre-check call happens strictly AFTER the first coder dispatch —
    # wave 1 on an untouched tree never pays an oracle run.
    pre = _precheck_calls(calls)
    assert len(pre) == 1
    assert calls.index(pre[0]) > calls.index(("task", "storage"))


# ---- FAIL-CLOSED: anything but an explicit pass dispatches normally --------------


@pytest.mark.parametrize("result", [
    {"status": "failed", "evidence": "1 failed"},
    {"status": "not-run", "evidence": "node unavailable"},
    {"status": "bogus", "evidence": "unknown vocab"},
    "not-a-dict",
    RuntimeError("precheck machinery exploded"),
])
def test_fail_closed_non_pass_dispatches_the_wave(tmp_path, result):
    calls = []
    res = _plan_driver(
        tmp_path, calls,
        precheck_result=result,
        already_satisfied_precheck=True,
    ).run()
    assert res.outcome == "complete"
    # The wave dispatched exactly as before — no skip on an undetermined condition.
    assert [c[1] for c in _task_calls(calls)] == ["storage", "report"]
    assert not any(getattr(o, "result", "") == "SKIPPED" for o in res.outcomes)
    sc = _scorecard(calls)
    assert sc is not None and sc["verdict"] == "GREEN"     # normal all-merged path
    assert "already_satisfied" not in sc["evidence"]


def test_fail_closed_noop_seam_default_dispatches_the_wave(tmp_path):
    # Knob ON but the seam left at its _noop default (not-run) — a construction that
    # never wired the live oracle can never skip.
    calls = []
    res = _plan_driver(tmp_path, calls, already_satisfied_precheck=True).run()
    assert [c[1] for c in _task_calls(calls)] == ["storage", "report"]
    assert not any(getattr(o, "result", "") == "SKIPPED" for o in res.outcomes)


# ---- verdict semantics (pure) ----------------------------------------------------


def _plan_with_statuses(tmp_path, storage_status, report_status):
    plan, _store, _tasks = _plan_fixture(tmp_path)
    new_tasks = []
    for t in plan.tasks:
        status = storage_status if t.id == "storage" else report_status
        new_tasks.append(dc_replace(t, status=status))
    return dc_replace(plan, tasks=new_tasks)


def _acc(plan, status):
    return dc_replace(plan, job_acceptance=dc_replace(plan.job_acceptance, status=status))


def test_verdict_green_with_satisfied_skip_and_passing_oracle(tmp_path):
    plan = _acc(_plan_with_statuses(tmp_path, pg.STATUS_MERGED, pg.STATUS_SKIPPED),
                "passed")
    verdict, attribution = sd.compute_job_verdict(
        plan, cancelled=False, stopped=False, wave_gates=[],
        satisfied_skips=frozenset({"report"}))
    assert (verdict, attribution) == (sd.VERDICT_GREEN, "")


def test_verdict_skip_without_satisfied_record_is_not_green(tmp_path):
    # The SAME statuses without the driver's satisfied record (e.g. a park-propagated
    # skip) keep the legacy fallthrough — an unexplained skip can never mint GREEN.
    plan = _acc(_plan_with_statuses(tmp_path, pg.STATUS_MERGED, pg.STATUS_SKIPPED),
                "passed")
    for sat in (None, frozenset(), frozenset({"someone-else"})):
        verdict, _attr = sd.compute_job_verdict(
            plan, cancelled=False, stopped=False, wave_gates=[], satisfied_skips=sat)
        assert verdict != sd.VERDICT_GREEN


def test_verdict_satisfied_skip_with_failed_oracle_parks_honest(tmp_path):
    plan = _acc(_plan_with_statuses(tmp_path, pg.STATUS_MERGED, pg.STATUS_SKIPPED),
                "failed")
    verdict, attribution = sd.compute_job_verdict(
        plan, cancelled=False, stopped=False, wave_gates=[],
        satisfied_skips=frozenset({"report"}))
    assert (verdict, attribution) == (sd.VERDICT_PARKED_HONEST, sd.ATTRIBUTION_BUILD)


def test_verdict_satisfied_skip_with_unrun_oracle_is_stalled_false_done(tmp_path):
    # Delivered-but-unverified stays the FALSE-DONE class: a pre-check pass is not a
    # finish-line grade, so a run whose real oracle never ran cannot be GREEN.
    plan = _acc(_plan_with_statuses(tmp_path, pg.STATUS_MERGED, pg.STATUS_SKIPPED),
                "not-run")
    verdict, attribution = sd.compute_job_verdict(
        plan, cancelled=False, stopped=False, wave_gates=[],
        satisfied_skips=frozenset({"report"}))
    assert (verdict, attribution) == (sd.VERDICT_STALLED, sd.ATTRIBUTION_VERIFY)


def test_verdict_legacy_none_default_byte_identical(tmp_path):
    # No satisfied_skips argument at all — every branch reads exactly as before.
    plan = _acc(_plan_with_statuses(tmp_path, pg.STATUS_MERGED, pg.STATUS_MERGED),
                "passed")
    assert sd.compute_job_verdict(
        plan, cancelled=False, stopped=False, wave_gates=[]) == (sd.VERDICT_GREEN, "")


# ---- scorecard stamping (pure) ---------------------------------------------------


def test_scorecard_stamps_already_satisfied_evidence_and_note(tmp_path):
    plan = _acc(_plan_with_statuses(tmp_path, pg.STATUS_MERGED, pg.STATUS_SKIPPED),
                "passed")
    sc = sd.build_scorecard(
        plan, run_id="R1", outcomes=[], wave_gates=[], job_evidence="exit 0",
        cancelled=False, stopped=False, degraded=False, packs_consumed=0,
        wall_clock_s=1.0, satisfied_skips=frozenset({"report"}))
    assert sc["verdict"] == sd.VERDICT_GREEN
    assert sc["evidence"]["already_satisfied"] == "report"
    assert "already-satisfied skip" in sc["notes"]
    assert {t["id"]: t["status"] for t in sc["tasks"]}["report"] == pg.STATUS_SKIPPED


def test_scorecard_without_satisfied_skips_stamps_nothing(tmp_path):
    plan = _acc(_plan_with_statuses(tmp_path, pg.STATUS_MERGED, pg.STATUS_MERGED),
                "passed")
    sc = sd.build_scorecard(
        plan, run_id="R1", outcomes=[], wave_gates=[], job_evidence="exit 0",
        cancelled=False, stopped=False, degraded=False, packs_consumed=0,
        wall_clock_s=1.0)
    assert "already_satisfied" not in sc["evidence"]
    assert "already-satisfied" not in sc["notes"]


# ---- knob plumbing: config -> spec -> driver, and the live seam wiring -----------


def _cfg(tmp_path, **kw):
    state = tmp_path / "state"
    return FleetDispatchConfig(
        scripts_dir=tmp_path / "scripts", queue_path=state / "fleet-queue.json",
        runs_dir=state / "fleet-runs", projects_dir=tmp_path / "projects", **kw)


def test_spec_carries_already_satisfied_precheck_knob(tmp_path):
    import shared.fleet.swap_ops as so

    so.prepare_and_launch_swap(
        _cfg(tmp_path), run_id="R1", session_id="s1",
        tasks=[{"repo": "X", "task": "a", "prompt": "p"}],
        old_pid=1, relaunch_argv=["py"], relaunch_cwd="C:/x",
        gate_gb=21.0, spawn=lambda p: None,
    )
    spec = json.loads((so.swap_dir(_cfg(tmp_path)) / "spec.json").read_text(encoding="utf-8"))
    assert spec["already_satisfied_precheck"] is False     # dataclass default

    cfg_on = _cfg(tmp_path, already_satisfied_precheck=True)
    so.prepare_and_launch_swap(
        cfg_on, run_id="R2", session_id="s1",
        tasks=[{"repo": "X", "task": "a", "prompt": "p"}],
        old_pid=1, relaunch_argv=["py"], relaunch_cwd="C:/x",
        gate_gb=21.0, spawn=lambda p: None,
    )
    spec = json.loads((so.swap_dir(cfg_on) / "spec.json").read_text(encoding="utf-8"))
    assert spec["already_satisfied_precheck"] is True


def test_run_swap_threads_precheck_knob_to_driver(tmp_path, monkeypatch):
    # spec -> SwapDriver(already_satisfied_precheck=...) — and a PRE-#1049 spec (no
    # key) resolves False, so crash-recovery re-reads of old specs stay legacy.
    import shared.fleet.swap_driver as sd_mod
    import shared.fleet.swap_ops as so
    import shared.fleet.swap_state as ss

    seen = {}
    real_init = sd_mod.SwapDriver.__init__

    def spy_init(self, *a, already_satisfied_precheck=False, **k):
        seen.setdefault("values", []).append(already_satisfied_precheck)
        real_init(self, *a, already_satisfied_precheck=already_satisfied_precheck, **k)

    monkeypatch.setattr(sd_mod.SwapDriver, "__init__", spy_init)
    monkeypatch.setattr(sd_mod.SwapDriver, "run", lambda self: None)
    cfg = _cfg(tmp_path)
    ss.write_swap_state(
        ss.SwapState(run_id="R1", session_id="s", phase=ss.PHASE_HANDOFF, tasks=[]),
        path=so.swap_state_path(cfg),
    )
    base = {"run_id": "R1", "session_id": "s", "old_pid": 1, "relaunch_argv": ["py"],
            "relaunch_cwd": "C:/x", "gate_gb": 21.0, "run_budget_s": 0.0,
            "scripts_dir": str(cfg.scripts_dir), "queue_path": str(cfg.queue_path),
            "runs_dir": str(cfg.runs_dir), "projects_dir": str(cfg.projects_dir)}
    spec_path = so.swap_dir(cfg) / "spec.json"
    spec_path.parent.mkdir(parents=True, exist_ok=True)

    spec_path.write_text(json.dumps(base), encoding="utf-8")          # pre-#1049 spec
    so.run_swap(spec_path)
    spec_path.write_text(json.dumps({**base, "already_satisfied_precheck": True}),
                         encoding="utf-8")
    so.run_swap(spec_path)
    assert seen["values"] == [False, True]


def test_live_wiring_precheck_is_single_run_never_flake_checked(tmp_path, monkeypatch):
    # build_swap_ops wires precheck_job_oracle to the SINGLE-run oracle grade —
    # deliberately NOT the #829 flake-checked wrapper (the differential protects
    # convictions; a non-passing pre-check convicts nobody).
    import shared.fleet.swap_ops as so
    from shared.fleet.acceptance import (
        JOB_ORACLE_CODE_KEY, JOB_ORACLE_PATH_KEY, JOB_ORACLE_PATH_PYTHON)

    code = "def test_x():\n    assert True\n"
    hits = []
    monkeypatch.setattr(so, "real_run_job_oracle",
                        lambda cfg, rid, repo, rel, oc, **kw:
                        (hits.append(("single", repo, rel, oc)),
                         {"status": "passed", "evidence": "exit 0"})[1])
    monkeypatch.setattr(so, "real_run_job_oracle_flake_checked",
                        lambda cfg, rid, repo, rel, oc, **kw:
                        (hits.append(("flake", repo, rel)),
                         {"status": "passed", "evidence": "exit 0"})[1])
    ops = so.build_swap_ops(
        _cfg(tmp_path), run_id="R", old_pid=1,
        relaunch_argv=["py"], relaunch_cwd="C:/x",
        tasks=[{"repo": "X", "task": "a", "prompt": "p",
                JOB_ORACLE_CODE_KEY: code,
                JOB_ORACLE_PATH_KEY: JOB_ORACLE_PATH_PYTHON}])
    res = ops.precheck_job_oracle("C:/r", JOB_ORACLE_PATH_PYTHON)
    assert res["status"] == "passed"
    assert [h[0] for h in hits] == ["single"]
    assert hits[0][3] == code
