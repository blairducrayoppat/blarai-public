"""Locks for the #749 driver-side REPORT ticket leg (wired 2026-07-14 at the
LA-present supervised proof — the seam's named unblock condition).

The contract the original TODO pinned: the post happens AFTER the guarded
scorecard/summary writes, OUTSIDE the guarded sequence, wholly fail-soft (a
Vikunja stall can cost only the one bounded call, never the teardown), and the
default is a byte-stable no-op so every pre-#749 spec and legacy test resolves
fail-closed. Plus the spec round-trip: the AO-resolved knobs ride the spec to
the detached driver exactly like plan_graph/guest_oracle_enabled.
"""

from __future__ import annotations

import json
from pathlib import Path

from shared.fleet import swap_driver as sd
from shared.fleet import swap_ops as so
from shared.fleet import swap_state as ss
from shared.fleet.dispatch import FleetDispatchConfig, TaskOutcome


def _config(tmp_path: Path, **kw) -> FleetDispatchConfig:
    return FleetDispatchConfig(
        scripts_dir=tmp_path / "scripts",
        queue_path=tmp_path / "state" / "fleet-queue.json",
        runs_dir=tmp_path / "state" / "fleet-runs",
        projects_dir=tmp_path / "projects",
        **kw,
    )


_TASKS = [{"task": "a", "repo": "r"}, {"task": "b", "repo": "r"}]


def _merged(t: dict) -> TaskOutcome:
    return TaskOutcome(task=t["task"], outcome="processed", result="MERGED",
                       detail="merged")


def _ops(calls, **overrides) -> sd.SwapOps:
    base = dict(
        available_gb=lambda: 26.0,
        backend_alive=lambda: False,
        load_30b=lambda: (calls.append("load"), True)[1],
        wait_ready=lambda: True,
        run_task=lambda t: (calls.append(("task", t["task"])), _merged(t))[1],
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


def _driver(tmp_path, ops) -> sd.SwapDriver:
    return sd.SwapDriver(
        run_id="R1", session_id="s1", tasks=_TASKS,
        swap_state_path=tmp_path / "swap.json", ops=ops,
        gate_gb=21.0, sleep=lambda _s: None,
    )


# ---------------------------------------------------------------------------
# The driver leg
# ---------------------------------------------------------------------------


def test_post_runs_after_report_with_the_scorecard(tmp_path: Path) -> None:
    calls: list = []
    posted: list[dict] = []
    ops = _ops(calls, post_job_ticket=posted.append)
    res = _driver(tmp_path, ops).run()
    assert res.outcome == "complete"
    assert len(posted) == 1 and "verdict" in posted[0]
    # AFTER the artifact writes: the report call precedes the post.
    assert ("report", "R1", 2) in calls


def test_raising_post_never_touches_the_teardown(tmp_path: Path) -> None:
    """The TODO's own constraint, locked: a Vikunja stall costs ONLY the one
    call — disarm/stop/restart all still run and the run completes."""
    calls: list = []

    def boom(scorecard: dict) -> None:
        raise RuntimeError("vikunja hung")

    res = _driver(tmp_path, _ops(calls, post_job_ticket=boom)).run()
    assert res.outcome == "complete"
    assert "disarm" in calls and "stop" in calls and "restart" in calls


def test_default_is_a_noop_and_byte_stable(tmp_path: Path) -> None:
    """Pre-#749 posture: no override ⇒ the exact legacy call list (the same
    assertion shape test_doom_check pins) — nothing new observable."""
    calls: list = []
    res = _driver(tmp_path, _ops(calls)).run()
    assert res.outcome == "complete"
    assert calls == ["load", ("task", "a"), ("task", "b"), ("report", "R1", 2),
                     "disarm", "stop", "restart"]


# ---------------------------------------------------------------------------
# The spec round-trip (AO knobs -> spec -> detached driver config)
# ---------------------------------------------------------------------------


def _launch_spec(tmp_path: Path, config: FleetDispatchConfig) -> dict:
    captured: list[Path] = []
    so.prepare_and_launch_swap(
        config, run_id="R9", session_id="s", tasks=_TASKS, old_pid=1234,
        relaunch_argv=["x"], relaunch_cwd=str(tmp_path), gate_gb=21.0,
        spawn=captured.append,
    )
    return json.loads(captured[0].read_text(encoding="utf-8"))


def test_spec_carries_the_bridge_knobs(tmp_path: Path) -> None:
    config = _config(tmp_path, vikunja_bridge=True, vikunja_bridge_project_id=12)
    spec = _launch_spec(tmp_path, config)
    assert spec["vikunja_bridge"] is True
    assert spec["vikunja_bridge_project_id"] == 12


def test_absent_spec_keys_resolve_off(tmp_path: Path) -> None:
    """A pre-#749 spec re-read after a crash recovery posts nothing."""
    spec = _launch_spec(tmp_path, _config(tmp_path))
    assert spec["vikunja_bridge"] is False
    assert spec["vikunja_bridge_project_id"] == 0


# ---------------------------------------------------------------------------
# The poster (goal/repo from the dispatch-written swap state; bridge-gated)
# ---------------------------------------------------------------------------


def test_poster_reads_goal_repo_from_swap_state(tmp_path: Path, monkeypatch) -> None:
    config = _config(tmp_path, vikunja_bridge=True, vikunja_bridge_project_id=12)
    ss.write_swap_state(
        ss.SwapState(run_id="R7", session_id="s", phase="RUNNING", tasks=_TASKS),
        path=so.swap_state_path(config),
    )
    ensured: list[tuple] = []
    outcomes: list[tuple] = []

    from shared.fleet import vikunja_bridge as vb

    monkeypatch.setattr(
        vb, "ensure_job_ticket",
        lambda cfg, rid, goal, repo, **kw: (ensured.append((rid, goal, repo)), 77)[1],
    )
    monkeypatch.setattr(
        vb, "post_outcome",
        lambda cfg, tid, sc, **kw: (outcomes.append((tid, sc.get("verdict"))), True)[1],
    )
    poster = so.build_job_ticket_poster(config, "R7")
    poster({"verdict": "GREEN", "evidence": {"oracle_status": "passed"}})
    assert ensured == [("R7", "a", "r")]  # the dispatch-written structured record
    assert outcomes == [(77, "GREEN")]


def test_poster_skips_outcome_when_no_ticket(tmp_path: Path, monkeypatch) -> None:
    """ensure_job_ticket None (bridge off / project unset / outage) ⇒ no
    post_outcome call — the double gate the bridge owns stays authoritative."""
    config = _config(tmp_path)  # bridge off
    from shared.fleet import vikunja_bridge as vb

    called: list = []
    monkeypatch.setattr(vb, "ensure_job_ticket", lambda *a, **kw: None)
    monkeypatch.setattr(
        vb, "post_outcome", lambda *a, **kw: called.append(a) or True
    )
    so.build_job_ticket_poster(config, "R7")({"verdict": "GREEN"})
    assert called == []
