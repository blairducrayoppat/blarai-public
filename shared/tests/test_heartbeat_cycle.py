"""Locks for the C3 heartbeat wake cycle (#845 limb 3, design §2/§5/§8).

The acceptance-shape locks this limb owns, per the LA-approved design §11 row 3:
forced-crash convergence, tripwire suppression + UNREACHABLE locks, the dedup lock
(same condition, 3 simulated cycles → 1 proposal), the TTL-expiry lock, and the
operator-absence locks (sweep pause + sanctioned ``extend_ttl`` on exit + Expedite
filtering) — plus the design-§5 trusted-repo_id sourcing locks (structured record
only, never run text) and the mid-swap-zero-model-calls lock.

Everything drives the REAL engine over injected fixture substrate (real proposal
store, real seen-set/board-history files on tmp paths, recording sinks) — the
mocks-lie lesson: the store, the diff code, and the set algebra are the genuine
articles; only the I/O boundaries (Vikunja, the model, the clock) are injected.
"""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping

import pytest

from shared.coordinator import cadence
from shared.coordinator import heartbeat_cycle as hc
from shared.coordinator.config import CoordinatorConfig, GovernedCoreRoots
from shared.coordinator.proposal_store import (
    ProposalLane,
    ProposalStatus,
    build_proposal_store,
)
from shared.fleet import coord_board_history as bh
from shared.fleet import coord_lifecycle as cl
from shared.fleet import swap_state as ss
from shared.fleet import vikunja_bridge as vb
from shared.fleet import work_state as ws
from shared.fleet.dispatch import FleetDispatchConfig, TaskOutcome

NOW = datetime(2026, 7, 14, 18, 0, 0, tzinfo=timezone.utc)
LOCAL_DAY = datetime(2026, 7, 14, 13, 0, 0)  # naive local, outside 23:00-09:00
LOCAL_NIGHT = datetime(2026, 7, 14, 23, 30, 0)  # naive local, inside the window

AC = cadence.PowerProbe(cadence.PowerState.AC)


# ---------------------------------------------------------------------------
# Fixture builders
# ---------------------------------------------------------------------------


def _fleet_config(tmp_path: Path) -> FleetDispatchConfig:
    projects = tmp_path / "projects"
    (projects / "widget").mkdir(parents=True, exist_ok=True)
    runs = tmp_path / "runs"
    runs.mkdir(exist_ok=True)
    return FleetDispatchConfig(
        scripts_dir=tmp_path / "scripts",
        queue_path=tmp_path / "state" / "fleet-queue.json",
        runs_dir=runs,
        projects_dir=projects,
    )


def _flow(open_count: int) -> Any:
    from shared.fleet import flow_metrics as fm

    return fm.FlowMetrics(
        computed_at=NOW.isoformat(),
        age_basis_field=fm.DEFAULT_AGE_BASIS_FIELD,
        open_count=open_count,
    )


def _project(
    name: str = "alpha",
    project_id: int = 3,
    *,
    board_status: vb.ReadStatus = vb.ReadStatus.OK,
    ready_tasks: "tuple[Mapping[str, Any], ...]" = (),
    buckets: "tuple[Mapping[str, Any], ...] | None" = None,
    stalls: "tuple[cl.StallSignal, ...]" = (),
    open_count: int = 0,
) -> ws.ProjectWorkState:
    if buckets is None:
        buckets = (
            {"title": cl.BUCKET_READY, "tasks": [dict(t) for t in ready_tasks]},
            {"title": cl.BUCKET_IN_PROGRESS, "tasks": []},
        )
    if board_status is vb.ReadStatus.UNREACHABLE:
        board = vb.ReadResult(status=board_status, items=(), error="down")
    else:
        board = vb.ReadResult(status=board_status, items=tuple(dict(b) for b in buckets))
    return ws.ProjectWorkState(
        name=name,
        project_id=project_id,
        board=board,
        summary=vb.ReadResult(status=vb.ReadStatus.EMPTY),
        flow=_flow(open_count) if board_status is not vb.ReadStatus.UNREACHABLE else None,
        stalls=stalls,
    )


def _tri(status: vb.ReadStatus, value: Any = None, error: str = "") -> ws.TriStateRead:
    return ws.TriStateRead(status=status, value=value, error=error)


def _snapshot(
    *,
    projects: "tuple[ws.ProjectWorkState, ...]" = (),
    latest_run: "ws.TriStateRead | None" = None,
    swap_in_flight: bool = False,
    substrate_unreachable: "tuple[str, ...]" = (),
    extra_substrate: "tuple[ws.SubstrateLiveness, ...]" = (),
) -> ws.WorkStateSnapshot:
    substrate = tuple(
        ws.SubstrateLiveness(
            name=name,
            status=(
                vb.ReadStatus.UNREACHABLE
                if name in substrate_unreachable
                else vb.ReadStatus.OK
            ),
            error="down" if name in substrate_unreachable else "",
        )
        for name in ("vikunja", "fleet_swap_state", "fleet_queue")
    ) + extra_substrate
    return ws.WorkStateSnapshot(
        computed_at=NOW.isoformat(),
        swap=_tri(vb.ReadStatus.EMPTY),
        swap_in_flight=swap_in_flight,
        queue=_tri(vb.ReadStatus.EMPTY),
        latest_run=latest_run if latest_run is not None else _tri(vb.ReadStatus.EMPTY),
        campaign=_tri(vb.ReadStatus.EMPTY),
        projects=projects,
        substrate=substrate,
    )


class _MoveSink:
    """Recording move sink — succeeds for one project id, fail-softs elsewhere."""

    def __init__(self, accept_project: int | None = 3) -> None:
        self.calls: list[tuple[int, str, str]] = []
        self.accept_project = accept_project

    def __call__(self, project_id: int, run_id: str, bucket: str) -> vb.BoardMoveResult:
        self.calls.append((project_id, run_id, bucket))
        if self.accept_project is not None and project_id == self.accept_project:
            return vb.BoardMoveResult(True, f"moved to {bucket!r}", bucket_id=1)
        return vb.BoardMoveResult(False, "no job ticket")


class _PostSink:
    def __init__(self, ok: bool = True) -> None:
        self.calls: list[tuple[int, str]] = []
        self.ok = ok

    def __call__(self, task_id: int, text: str) -> bool:
        self.calls.append((task_id, text))
        return self.ok


class _DraftSpy:
    def __init__(self, outcome: "hc.DraftOutcome | None" = None) -> None:
        self.prompts: list[str] = []
        self.outcome = outcome or hc.DraftOutcome(status="drafted", text="prose")

    def __call__(self, prompt: str) -> hc.DraftOutcome:
        self.prompts.append(prompt)
        return self.outcome


@pytest.fixture()
def store():
    s = build_proposal_store(":memory:")
    try:
        yield s
    finally:
        s.close()


def _env(
    tmp_path: Path,
    store,
    snapshot: ws.WorkStateSnapshot,
    *,
    config: CoordinatorConfig | None = None,
    move: "_MoveSink | None" = None,
    post: "_PostSink | None" = None,
    draft: "_DraftSpy | None" = None,
    shadow_mode: bool = True,
    read_acceptance=None,
    read_scorecard=None,
    eligible_ready=None,
) -> hc.CycleEnv:
    fc = _fleet_config(tmp_path)
    return hc.CycleEnv(
        fleet_config=fc,
        coordinator_config=config or CoordinatorConfig(heartbeat_enabled=True),
        coordinator_projects={"alpha": 3},
        roots=GovernedCoreRoots(repo_root=tmp_path / "blarai-repo"),
        board_history_path=tmp_path / "coord" / "board_history.json",
        stall_seen_path=tmp_path / "coord" / "stall_seen.json",
        absence_stamp_path=tmp_path / "coord" / "absence_start.json",
        store=store,
        shadow_mode=shadow_mode,
        move_card=move or _MoveSink(),
        post_stall_comment=post or _PostSink(),
        draft=draft,
        power_probe=lambda: AC,
        read_swap=lambda: _tri(vb.ReadStatus.EMPTY),
        compose_snapshot=lambda now: snapshot,
        read_acceptance=read_acceptance or (lambda rid: None),
        read_scorecard=read_scorecard or (lambda rid: None),
        eligible_ready=eligible_ready,
    )


def _run(env: hc.CycleEnv, **kw) -> hc.CycleResult:
    kw.setdefault("now", NOW)
    kw.setdefault("local_now", LOCAL_DAY)
    return hc.run_wake_cycle(env, **kw)


def _parked_run(run_id: str = "r-1") -> ws.TriStateRead:
    return _tri(
        vb.ReadStatus.OK,
        (run_id, (TaskOutcome("build the widget", "processed", "PARKED", "RESULT: PARKED"),)),
    )


def _acceptance(repo: Any):
    return lambda rid: {"spec": {}, "repo": repo}


# ---------------------------------------------------------------------------
# Entry contract + SKIP
# ---------------------------------------------------------------------------


def test_naive_now_raises(tmp_path, store) -> None:
    env = _env(tmp_path, store, _snapshot())
    with pytest.raises(ValueError, match="timezone-aware"):
        hc.run_wake_cycle(env, now=NOW.replace(tzinfo=None), local_now=LOCAL_DAY)


def test_aware_local_now_raises(tmp_path, store) -> None:
    env = _env(tmp_path, store, _snapshot())
    with pytest.raises(ValueError, match="NAIVE local"):
        hc.run_wake_cycle(env, now=NOW, local_now=NOW)


def test_teardown_skips_everything(tmp_path, store) -> None:
    composed: list[datetime] = []
    env = replace(
        _env(tmp_path, store, _snapshot()),
        compose_snapshot=lambda now: composed.append(now) or _snapshot(),
    )
    result = _run(env, teardown_started=True)
    assert result.decision.mode is cadence.CycleMode.SKIP
    assert result.snapshot is None
    assert result.digest is None
    assert composed == []  # nothing but the mode step ran


def test_previous_cycle_running_skips(tmp_path, store) -> None:
    result = _run(_env(tmp_path, store, _snapshot()), previous_cycle_running=True)
    assert result.decision.mode is cadence.CycleMode.SKIP


# ---------------------------------------------------------------------------
# TTL sweep + the TTL-expiry lock
# ---------------------------------------------------------------------------


def _staged_proposal(store, *, staged_at: datetime, fingerprint: str = "fp-ttl") -> str:
    p = store.add_draft(
        lane=ProposalLane.WORKSPACE,
        proposal_class="redispatch",
        fingerprint=fingerprint,
        payload={"goal": "g"},
        now=staged_at,
    )
    store.mark_staged(p.id, now=staged_at)
    return p.id


def test_ttl_expiry_lock(tmp_path, store) -> None:
    """A STAGED proposal past its TTL is demoted to DRAFT with a note by step 2."""
    pid = _staged_proposal(store, staged_at=NOW - timedelta(days=8))
    result = _run(_env(tmp_path, store, _snapshot()))
    assert result.ttl_expired == 1
    demoted = store.get(pid)
    assert demoted is not None and demoted.status is ProposalStatus.DRAFT
    assert "TTL-expired" in demoted.system_note


def test_no_store_surfaces_condition_and_proceeds(tmp_path, store) -> None:
    env = replace(_env(tmp_path, store, _snapshot()), store=None)
    result = _run(env)
    kinds = [c.kind for c in result.conditions]
    assert "store-unavailable" in kinds
    assert result.digest is not None  # the cycle still completed


# ---------------------------------------------------------------------------
# Operator-absence locks (design §8.2)
# ---------------------------------------------------------------------------


def _absent_config() -> CoordinatorConfig:
    return CoordinatorConfig(heartbeat_enabled=True, operator_absent=True)


def test_absence_start_stamps_and_pauses_sweep(tmp_path, store) -> None:
    pid = _staged_proposal(store, staged_at=NOW - timedelta(days=8))
    env = _env(tmp_path, store, _snapshot(), config=_absent_config())
    result = _run(env)
    # Sweep paused: the stale STAGED proposal was NOT demoted.
    assert store.get(pid).status is ProposalStatus.STAGED
    assert result.ttl_expired == 0
    assert result.absence is not None and result.absence.started_this_cycle
    stamp = json.loads(env.absence_stamp_path.read_text(encoding="utf-8"))
    assert stamp["absent_since"] == NOW.isoformat()


def test_absence_continue_keeps_original_stamp(tmp_path, store) -> None:
    env = _env(tmp_path, store, _snapshot(), config=_absent_config())
    _run(env)
    later = NOW + timedelta(hours=3)
    result = hc.run_wake_cycle(env, now=later, local_now=LOCAL_DAY)
    assert result.absence is not None and not result.absence.started_this_cycle
    stamp = json.loads(env.absence_stamp_path.read_text(encoding="utf-8"))
    assert stamp["absent_since"] == NOW.isoformat()  # not re-stamped


def test_absence_exit_extends_ttl_before_sweep(tmp_path, store) -> None:
    """The load-bearing order: on exit, extend_ttl lands BEFORE the sweep, so a
    proposal whose deadline passed DURING the absence survives (no demote-at-once)."""
    # Staged 6 days ago → expires in 1 day. Absence spans 3 days → without the
    # pause, the sweep at exit would demote it.
    pid = _staged_proposal(store, staged_at=NOW - timedelta(days=6))
    absent_env = _env(tmp_path, store, _snapshot(), config=_absent_config())
    _run(absent_env)  # stamps absence at NOW

    exit_now = NOW + timedelta(days=3)
    present_env = _env(tmp_path, store, _snapshot())
    result = hc.run_wake_cycle(present_env, now=exit_now, local_now=LOCAL_DAY)

    assert result.absence is not None and result.absence.ended_this_cycle
    assert result.absence.extended_count == 1
    assert result.absence.paused_duration_s == pytest.approx(3 * 86400)
    assert store.get(pid).status is ProposalStatus.STAGED  # survived the exit sweep
    assert not present_env.absence_stamp_path.exists()  # stamp cleared
    # And the pause is finite: past the EXTENDED deadline it still expires.
    assert store.expire_stale(now=exit_now + timedelta(days=2)) == 1


def test_absence_exit_store_fault_keeps_stamp_and_skips_sweep(tmp_path, store) -> None:
    pid = _staged_proposal(store, staged_at=NOW - timedelta(days=8))
    absent_env = _env(tmp_path, store, _snapshot(), config=_absent_config())
    _run(absent_env)

    class _Boom:
        def extend_ttl(self, **kw):
            raise RuntimeError("keystore offline")

        def expire_stale(self, **kw):
            raise AssertionError("sweep must not run when the pause failed")

        def list_active(self):
            return []

    broken_env = replace(_env(tmp_path, store, _snapshot()), store=_Boom())
    result = hc.run_wake_cycle(
        broken_env, now=NOW + timedelta(days=1), local_now=LOCAL_DAY
    )
    assert broken_env.absence_stamp_path.exists()  # retried next cycle
    kinds = [c.kind for c in result.conditions]
    assert "absence-reconcile-failed" in kinds
    assert any(c.machinery_health for c in result.conditions)
    # The real store was untouched: proposal still STAGED, retry converges later.
    assert store.get(pid).status is ProposalStatus.STAGED


def test_absence_suppresses_non_expedite_stall_comments(tmp_path, store) -> None:
    standard = cl.StallSignal(
        task_id=11, title="t", service_class=cl.ServiceClass.STANDARD,
        age_seconds=1e6, fingerprint="Standard:11",
    )
    expedite = cl.StallSignal(
        task_id=12, title="u", service_class=cl.ServiceClass.EXPEDITE,
        age_seconds=1e6, fingerprint="Expedite:12",
    )
    snap = _snapshot(projects=(_project(stalls=(standard, expedite)),))
    post = _PostSink()
    env = _env(tmp_path, store, snap, config=_absent_config(), post=post)
    result = _run(env)
    assert [c[0] for c in post.calls] == [12]  # only the Expedite stall posted
    assert any(c.kind == "stall-comments-suppressed" for c in result.conditions)

    # On the present cycle the suppressed stall retries and posts exactly once.
    present = _env(tmp_path, store, snap, post=post)
    hc.run_wake_cycle(present, now=NOW + timedelta(hours=1), local_now=LOCAL_DAY)
    assert sorted(c[0] for c in post.calls) == [11, 12]


# ---------------------------------------------------------------------------
# Board-history observe (step 4)
# ---------------------------------------------------------------------------


def test_observe_writes_ok_boards_only(tmp_path, store) -> None:
    ok_project = _project(
        name="alpha", project_id=3,
        ready_tasks=({"id": 101, "title": "a"},),
    )
    snap = _snapshot(projects=(ok_project,))
    env = _env(tmp_path, store, snap)
    _run(env)
    state = bh.read_board_history(env.board_history_path).state
    assert state.entries["3:101"].bucket == cl.BUCKET_READY

    # Next cycle the SAME project reads UNREACHABLE: history carried forward, not pruned.
    down = _snapshot(projects=(_project(board_status=vb.ReadStatus.UNREACHABLE),))
    env_down = _env(tmp_path, store, down)
    hc.run_wake_cycle(env_down, now=NOW + timedelta(minutes=15), local_now=LOCAL_DAY)
    state2 = bh.read_board_history(env_down.board_history_path).state
    assert state2.entries["3:101"].first_seen == state.entries["3:101"].first_seen


def test_corrupt_record_rebuilt_and_surfaced(tmp_path, store) -> None:
    env = _env(tmp_path, store, _snapshot(projects=(_project(ready_tasks=({"id": 7},)),)))
    env.board_history_path.parent.mkdir(parents=True, exist_ok=True)
    env.board_history_path.write_text("{not json", encoding="utf-8")
    result = _run(env)
    assert any(
        c.kind == "board-history-corrupt" and c.machinery_health
        for c in result.conditions
    )
    rebuilt = bh.read_board_history(env.board_history_path)
    assert not rebuilt.corrupt and "3:7" in rebuilt.state.entries


def test_unchanged_membership_does_not_rewrite(tmp_path, store) -> None:
    snap = _snapshot(projects=(_project(ready_tasks=({"id": 5},)),))
    env = _env(tmp_path, store, snap)
    _run(env)
    first = env.board_history_path.read_text(encoding="utf-8")
    hc.run_wake_cycle(env, now=NOW + timedelta(minutes=15), local_now=LOCAL_DAY)
    assert env.board_history_path.read_text(encoding="utf-8") == first


# ---------------------------------------------------------------------------
# Harvest → board movement (step 5) + the oracle fact
# ---------------------------------------------------------------------------


def _merged_run(run_id: str = "r-9") -> ws.TriStateRead:
    return _tri(
        vb.ReadStatus.OK,
        (run_id, (TaskOutcome("ship it", "processed", "MERGED", "RESULT: MERGED"),)),
    )


def test_merged_with_oracle_moves_to_done(tmp_path, store) -> None:
    move = _MoveSink(accept_project=3)
    env = _env(
        tmp_path, store, _snapshot(latest_run=_merged_run()), move=move,
        read_scorecard=lambda rid: {"evidence": {"oracle_status": "passed"}},
    )
    result = _run(env)
    assert move.calls == [(3, "r-9", cl.BUCKET_DONE)]
    assert result.board_moves[0].moved


def test_merged_without_oracle_never_moves_to_done(tmp_path, store) -> None:
    """The forged-Done lock's runtime feed: absent/failed scorecard ⇒ not Done."""
    move = _MoveSink(accept_project=3)
    env = _env(
        tmp_path, store, _snapshot(latest_run=_merged_run()), move=move,
        read_scorecard=lambda rid: {"evidence": {"oracle_status": "failed"}},
    )
    _run(env)
    assert move.calls and move.calls[0][2] != cl.BUCKET_DONE


def test_parked_moves_to_ready(tmp_path, store) -> None:
    move = _MoveSink(accept_project=3)
    env = _env(tmp_path, store, _snapshot(latest_run=_parked_run()), move=move)
    _run(env)
    assert move.calls[0][2] == cl.BUCKET_READY


def test_no_card_anywhere_is_surfaced_not_fatal(tmp_path, store) -> None:
    move = _MoveSink(accept_project=None)
    env = _env(tmp_path, store, _snapshot(latest_run=_parked_run()), move=move)
    result = _run(env)
    assert any(c.kind == "board-move-not-applied" for c in result.conditions)
    assert result.digest is not None


def test_move_sink_raising_is_fail_soft(tmp_path, store) -> None:
    def boom(project_id: int, run_id: str, bucket: str) -> vb.BoardMoveResult:
        raise RuntimeError("bridge down")

    env = _env(tmp_path, store, _snapshot(latest_run=_parked_run()), move=boom)
    result = _run(env)
    failed = [s for s in result.steps if s.name == "harvest-board-move"]
    assert failed and not failed[0].ok
    assert result.digest is not None


def test_oracle_fact_is_scorecard_only() -> None:
    assert hc.oracle_passed_from_scorecard({"evidence": {"oracle_status": "passed"}})
    assert not hc.oracle_passed_from_scorecard({"evidence": {"oracle_status": "skipped"}})
    assert not hc.oracle_passed_from_scorecard({"evidence": {}})
    assert not hc.oracle_passed_from_scorecard({})
    assert not hc.oracle_passed_from_scorecard(None)
    assert not hc.oracle_passed_from_scorecard("passed")


# ---------------------------------------------------------------------------
# Stall pass (step 6): episode dedup + failed-post retry
# ---------------------------------------------------------------------------


def _stalled_snapshot() -> ws.WorkStateSnapshot:
    signal = cl.StallSignal(
        task_id=42, title="stuck", service_class=cl.ServiceClass.STANDARD,
        age_seconds=1e6, fingerprint="Standard:42",
    )
    return _snapshot(projects=(_project(stalls=(signal,)),))


def test_stall_commented_once_per_episode(tmp_path, store) -> None:
    post = _PostSink()
    env = _env(tmp_path, store, _stalled_snapshot(), post=post)
    _run(env)
    hc.run_wake_cycle(env, now=NOW + timedelta(minutes=15), local_now=LOCAL_DAY)
    assert len(post.calls) == 1  # second cycle: ongoing, silent


def test_failed_post_retries_next_cycle(tmp_path, store) -> None:
    failing = _PostSink(ok=False)
    env = _env(tmp_path, store, _stalled_snapshot(), post=failing)
    result = _run(env)
    assert result.stall_result is not None and result.stall_result.post_failures

    working = _PostSink()
    env2 = _env(tmp_path, store, _stalled_snapshot(), post=working)
    hc.run_wake_cycle(env2, now=NOW + timedelta(minutes=15), local_now=LOCAL_DAY)
    assert len(working.calls) == 1  # retried exactly once, then persisted


# ---------------------------------------------------------------------------
# Redispatch staging (step 7): trusted repo_id (§5) + wrap + dedup + promotion
# ---------------------------------------------------------------------------


def test_dedup_lock_three_cycles_one_proposal(tmp_path, store) -> None:
    """The keyed acceptance lock: the same parked evidence, three simulated
    cycles → exactly ONE active proposal in the store."""
    snap = _snapshot(latest_run=_parked_run())
    env = _env(tmp_path, store, snap, read_acceptance=_acceptance("widget"))
    for i in range(3):
        hc.run_wake_cycle(
            env, now=NOW + timedelta(minutes=15 * i), local_now=LOCAL_DAY
        )
    assert len(store.list_active()) == 1


def test_shadow_keeps_drafts_live_promotes(tmp_path, store) -> None:
    snap = _snapshot(latest_run=_parked_run())
    env = _env(tmp_path, store, snap, read_acceptance=_acceptance("widget"))
    result = _run(env)
    assert result.redispatch is not None and len(result.redispatch.staged) == 1
    assert result.promoted_proposal_ids == ()
    assert store.list_active()[0].status is ProposalStatus.DRAFT  # shadow: DRAFT stays

    live_env = _env(
        tmp_path, store, _snapshot(latest_run=_parked_run("r-2")),
        shadow_mode=False, read_acceptance=_acceptance("widget"),
    )
    live_result = hc.run_wake_cycle(
        live_env, now=NOW + timedelta(minutes=15), local_now=LOCAL_DAY
    )
    assert len(live_result.promoted_proposal_ids) == 1
    promoted = live_env.store.get(live_result.promoted_proposal_ids[0])
    assert promoted.status is ProposalStatus.STAGED


def test_no_acceptance_record_skips_staging_surfaced(tmp_path, store) -> None:
    env = _env(tmp_path, store, _snapshot(latest_run=_parked_run()))  # record → None
    result = _run(env)
    assert result.redispatch is None
    assert any(c.kind == "redispatch-target-unresolved" for c in result.conditions)
    assert store.list_active() == []


def test_repo_path_inside_projects_dir_normalizes(tmp_path, store) -> None:
    fc_projects = tmp_path / "projects"
    env = _env(
        tmp_path, store, _snapshot(latest_run=_parked_run()),
        read_acceptance=_acceptance(str(fc_projects / "widget")),
    )
    result = _run(env)
    assert result.redispatch is not None and len(result.redispatch.staged) == 1


def test_repo_path_outside_projects_dir_skips(tmp_path, store) -> None:
    env = _env(
        tmp_path, store, _snapshot(latest_run=_parked_run()),
        read_acceptance=_acceptance(str(tmp_path / "elsewhere" / "widget")),
    )
    result = _run(env)
    assert result.redispatch is None
    assert any(c.kind == "redispatch-target-unresolved" for c in result.conditions)
    assert store.list_active() == []


def test_stage_raise_is_wrapped_and_retries(tmp_path, store, monkeypatch) -> None:
    """The #844 c.1876 whole-invocation wrap: a raise is recorded, nothing is
    written, and the SAME evidence stages cleanly next cycle."""

    def boom(*a, **kw):
        raise RuntimeError("store schema surprise")

    monkeypatch.setattr(hc.cr, "stage_redispatch_proposals", boom)
    snap = _snapshot(latest_run=_parked_run())
    env = _env(tmp_path, store, snap, read_acceptance=_acceptance("widget"))
    result = _run(env)
    assert any(c.kind == "redispatch-staging-failed" for c in result.conditions)
    assert store.list_active() == []

    monkeypatch.undo()
    result2 = hc.run_wake_cycle(
        env, now=NOW + timedelta(minutes=15), local_now=LOCAL_DAY
    )
    assert result2.redispatch is not None and len(result2.redispatch.staged) == 1


def test_normalize_trusted_repo_id_rules(tmp_path) -> None:
    pd = tmp_path / "projects"
    (pd / "widget").mkdir(parents=True)
    ok, _ = hc.normalize_trusted_repo_id("widget", projects_dir=pd)
    assert ok == "widget"
    ok, _ = hc.normalize_trusted_repo_id(str(pd / "widget"), projects_dir=pd)
    assert ok == "widget"
    for bad in (
        None, "", "  ", "..", "../evil", "a/b", str(tmp_path / "other" / "x"),
        str(pd / "widget" / "nested"), 42,
    ):
        refused, reason = hc.normalize_trusted_repo_id(bad, projects_dir=pd)
        assert refused is None and reason


def test_result_literals_match_fleet_vocabulary() -> None:
    """Drift lock: this module's RESULT literals stay inside the fleet's own
    classified vocabulary (the same source coord_redispatch's lock parses)."""
    import inspect

    from shared.fleet import dispatch

    source = inspect.getsource(dispatch._classify_result)
    assert f'"{hc.RESULT_MERGED}"' in source
    assert f'"{hc.RESULT_PARKED}"' in source
    from shared.fleet.coord_redispatch import REDISPATCH_ELIGIBLE_RESULTS

    assert hc.RESULT_PARKED in REDISPATCH_ELIGIBLE_RESULTS


# ---------------------------------------------------------------------------
# Quiet-queue tripwire (step 8, design §8.1)
# ---------------------------------------------------------------------------


def _ready_snapshot(**kw) -> ws.WorkStateSnapshot:
    return _snapshot(
        projects=(_project(ready_tasks=({"id": 1, "title": "go"},)),), **kw
    )


def test_tripwire_fires_on_ready_and_idle(tmp_path, store) -> None:
    result = _run(_env(tmp_path, store, _ready_snapshot()))
    assert result.tripwire is not None and result.tripwire.fired
    assert any(c.kind == "quiet-queue-tripwire" for c in result.conditions)


def test_tripwire_ignores_test_class_ready_tasks(tmp_path, store) -> None:
    """#887: a SYNTHETIC battery/test ticket sitting in Ready is not real work
    waiting to be pulled — it must NOT fire the quiet-queue alarm, and (unlike a
    resource-gated card) it is not counted as gated inventory either."""
    battery = {"id": 9, "title": "battery-park", "labels": [{"title": cl.TEST_CLASS_LABEL}]}
    snap = _snapshot(projects=(_project(ready_tasks=(battery,)),))
    result = hc.evaluate_quiet_queue_tripwire(
        snap, in_overnight_window=False, in_boot_grace=False, absence_active=False
    )
    assert not result.fired
    assert result.ready_eligible_total == 0
    assert result.gated_inventory == 0  # excluded outright, not gated


def test_tripwire_counts_only_real_ready_work_in_a_mixed_column(tmp_path, store) -> None:
    battery = {"id": 9, "title": "battery-park", "labels": [{"title": cl.TEST_CLASS_LABEL}]}
    real = {"id": 1, "title": "go"}
    snap = _snapshot(projects=(_project(ready_tasks=(battery, real)),))
    result = hc.evaluate_quiet_queue_tripwire(
        snap, in_overnight_window=False, in_boot_grace=False, absence_active=False
    )
    assert result.fired  # one REAL Ready item, nothing pulling
    assert result.ready_eligible_total == 1


def test_tripwire_suppressed_on_unreachable_substrate(tmp_path, store) -> None:
    """Unknown ≠ quiet: a dead substrate suppresses + surfaces, never alarms."""
    snap = _ready_snapshot(substrate_unreachable=("vikunja",))
    result = _run(_env(tmp_path, store, snap))
    assert result.tripwire is not None and not result.tripwire.fired
    assert any("PM substrate unreachable" in r for r in result.tripwire.suppressed_reasons)
    assert any(
        c.kind == "tripwire-suppressed" and c.machinery_health
        for c in result.conditions
    )


def test_tripwire_suppressed_on_unreachable_board(tmp_path, store) -> None:
    snap = _snapshot(
        projects=(
            _project(ready_tasks=({"id": 1},)),
            _project(name="beta", project_id=4, board_status=vb.ReadStatus.UNREACHABLE),
        )
    )
    result = _run(_env(tmp_path, store, snap))
    assert not result.tripwire.fired
    assert any("board:beta" in r for r in result.tripwire.suppressed_reasons)


def test_tripwire_suppressed_mid_swap(tmp_path, store) -> None:
    result = _run(_env(tmp_path, store, _ready_snapshot(swap_in_flight=True)))
    assert not result.tripwire.fired


def test_tripwire_suppressed_overnight(tmp_path, store) -> None:
    result = hc.run_wake_cycle(
        _env(tmp_path, store, _ready_snapshot()), now=NOW, local_now=LOCAL_NIGHT
    )
    assert not result.tripwire.fired
    assert any("overnight" in r for r in result.tripwire.suppressed_reasons)


def test_tripwire_suppressed_in_boot_grace(tmp_path, store) -> None:
    result = _run(_env(tmp_path, store, _ready_snapshot()), in_boot_grace=True)
    assert not result.tripwire.fired


def test_tripwire_suppressed_during_absence(tmp_path, store) -> None:
    result = _run(_env(tmp_path, store, _ready_snapshot(), config=_absent_config()))
    assert not result.tripwire.fired
    assert any("operator absent" in r for r in result.tripwire.suppressed_reasons)


def test_tripwire_suppressed_while_run_active(tmp_path, store) -> None:
    active = _tri(vb.ReadStatus.EMPTY, ("r-live", ()))
    result = _run(_env(tmp_path, store, _ready_snapshot(latest_run=active)))
    assert not result.tripwire.fired
    assert any("dispatch run is active" in r for r in result.tripwire.suppressed_reasons)


def test_all_gated_reports_inventory_never_alarms(tmp_path, store) -> None:
    """#845 c.1839 V4: all-gated Ready + idle fleet → NO tripwire; gated inventory."""
    result = _run(
        _env(tmp_path, store, _ready_snapshot(), eligible_ready=lambda t: False)
    )
    assert not result.tripwire.fired
    assert result.tripwire.gated_inventory == 1
    assert any(c.kind == "gated-inventory" for c in result.conditions)


def test_raising_evaluator_keeps_card_gated(tmp_path, store) -> None:
    """#845 c.1839 V3: an evaluator that raises returns UNKNOWN — gated-and-visible,
    never released."""

    def boom(task: Mapping[str, Any]) -> bool:
        raise RuntimeError("registry offline")

    result = _run(_env(tmp_path, store, _ready_snapshot(), eligible_ready=boom))
    assert not result.tripwire.fired
    assert result.tripwire.gated_inventory == 1


# ---------------------------------------------------------------------------
# Drafting (step 9): mode gating + deferral semantics
# ---------------------------------------------------------------------------


def test_mid_swap_cycle_makes_zero_model_calls(tmp_path, store) -> None:
    """The acceptance lock: a mid-swap cycle provably never touches the model."""
    in_flight_state = ss.SwapState(run_id="r-live", session_id="s", phase="RUNNING")
    assert ss.is_in_flight(in_flight_state)  # self-checking fixture
    spy = _DraftSpy()
    env = replace(
        _env(
            tmp_path, store,
            _snapshot(latest_run=_merged_run(), swap_in_flight=True),
            draft=spy,
        ),
        read_swap=lambda: _tri(vb.ReadStatus.OK, in_flight_state),
    )
    result = _run(env)
    assert result.decision.mode is cadence.CycleMode.DETERMINISTIC_ONLY
    assert spy.prompts == []


def test_unreachable_swap_read_defers_drafting(tmp_path, store) -> None:
    """Unknown ≠ idle (design-review F1): an unreadable swap state is never
    clearance to draft."""
    spy = _DraftSpy()
    env = replace(
        _env(tmp_path, store, _snapshot(latest_run=_merged_run()), draft=spy),
        read_swap=lambda: _tri(vb.ReadStatus.UNREACHABLE, error="torn"),
    )
    result = _run(env)
    assert result.decision.mode is cadence.CycleMode.DETERMINISTIC_ONLY
    assert spy.prompts == []


def test_full_mode_drafts_and_digest_carries_prose(tmp_path, store) -> None:
    """A guard-compliant draft (verdict echo, no contradicting claim) still
    flows into the digest — #946 gates, it does not silence."""
    text = "INCOMPLETE: The task merged; the acceptance grade did not run."
    spy = _DraftSpy(hc.DraftOutcome(status="drafted", text=text))
    env = _env(tmp_path, store, _snapshot(latest_run=_merged_run()), draft=spy)
    result = _run(env)
    assert result.decision.mode is cadence.CycleMode.FULL
    assert spy.prompts  # called
    # #946 drafting contract: the prompt carries the verdict + echo requirement.
    assert "recorded verdict is INCOMPLETE" in spy.prompts[0]
    assert result.digest is not None and result.digest.model_drafted
    assert result.digest.model_prose == text
    assert result.digest.prose_guard_action == "accepted"
    assert result.digest.run_headline.startswith("Run r-9: INCOMPLETE")


def test_prose_guard_rejects_false_success_prose_end_to_end(tmp_path, store) -> None:
    """#946 wire lock — the #855-measured failure verbatim: success prose about
    a non-success run is refused at the REAL run_cycle seam. The digest keeps
    the deterministic headline, drops the prose, and journals the audit trail
    (raw rejected text + action) for the false-refusal measurement."""
    text = (
        "The run passed all acceptance tests, confirming that the system is "
        "fully functional and ready for use."
    )
    spy = _DraftSpy(hc.DraftOutcome(status="drafted", text=text))
    env = _env(tmp_path, store, _snapshot(latest_run=_merged_run()), draft=spy)
    result = _run(env)
    d = result.digest
    assert d is not None
    assert d.model_prose == "" and not d.model_drafted
    assert d.prose_guard_action == "rejected:echo-missing"
    assert d.model_prose_rejected == text
    assert d.run_headline.startswith("Run r-9: INCOMPLETE")
    assert any(
        s.name == "prose-guard" and "rejected" in s.detail for s in result.steps
    )


def test_prose_guard_rejects_lying_echo_end_to_end(tmp_path, store) -> None:
    """#946 wire lock: an echo that CLAIMS a better verdict than the harvest
    truth is a mismatch, not a pass — the echo is validated against truth,
    never trusted as self-report."""
    spy = _DraftSpy(
        hc.DraftOutcome(status="drafted", text="SUCCEEDED: everything is great.")
    )
    env = _env(tmp_path, store, _snapshot(latest_run=_merged_run()), draft=spy)
    result = _run(env)
    d = result.digest
    assert d is not None
    assert d.model_prose == ""
    assert d.prose_guard_action == "rejected:echo-mismatch:SUCCEEDED"


def test_busy_draft_is_deferral_not_error(tmp_path, store) -> None:
    spy = _DraftSpy(hc.DraftOutcome(status="busy", reason="chat holds the lock"))
    env = _env(tmp_path, store, _snapshot(latest_run=_merged_run()), draft=spy)
    result = _run(env)
    assert len(spy.prompts) == 1  # a deferral stops further calls this cycle
    assert any(c.kind == "drafting-deferred" for c in result.conditions)
    assert result.digest is not None and not result.digest.model_drafted


def test_draft_raise_is_fail_soft(tmp_path, store) -> None:
    def boom(prompt: str) -> hc.DraftOutcome:
        raise RuntimeError("adapter exploded")

    env = _env(tmp_path, store, _snapshot(latest_run=_merged_run()), draft=boom)
    result = _run(env)
    assert result.drafts and result.drafts[0].status == "failed"
    assert result.digest is not None  # skeleton stands in


def test_no_seam_records_dormant(tmp_path, store) -> None:
    result = _run(_env(tmp_path, store, _snapshot(latest_run=_merged_run())))
    assert result.drafts == ()


# ---------------------------------------------------------------------------
# Digest (step 10): exactly one, deterministic skeleton, absence accumulation
# ---------------------------------------------------------------------------


def test_one_digest_with_skeleton_facts(tmp_path, store) -> None:
    snap = _snapshot(
        latest_run=_parked_run(),
        projects=(_project(ready_tasks=({"id": 1},), open_count=4),),
    )
    env = _env(tmp_path, store, snap, read_acceptance=_acceptance("widget"))
    result = _run(env)
    digest = result.digest
    assert digest is not None
    assert digest.queue_depth == {"alpha": 1}
    assert digest.open_by_project == {"alpha": 4}
    assert digest.runs_harvested == ("r-1",)
    assert digest.proposals_pending == 1
    assert not digest.absence_accumulated


def test_digest_open_delta_vs_prior(tmp_path, store) -> None:
    snap = _snapshot(projects=(_project(open_count=4),))
    env = _env(tmp_path, store, snap)
    first = _run(env)
    snap2 = _snapshot(projects=(_project(open_count=6),))
    env2 = _env(tmp_path, store, snap2)
    second = hc.run_wake_cycle(
        env2, now=NOW + timedelta(minutes=15), local_now=LOCAL_DAY,
        prior_digest=first.digest,
    )
    assert second.digest.open_delta_by_project == {"alpha": 2}


def test_absence_digest_accumulates(tmp_path, store) -> None:
    result = _run(_env(tmp_path, store, _snapshot(), config=_absent_config()))
    assert result.digest is not None and result.digest.absence_accumulated


# ---------------------------------------------------------------------------
# Forced-crash convergence (design §2): a cycle interrupted mid-way leaves no
# duplicate side effects on the next full cycle.
# ---------------------------------------------------------------------------


def test_crash_mid_cycle_converges_clean(tmp_path, store) -> None:
    """Cycle 1 'crashes' at its sinks (post + move both blow up) AFTER the
    board-history write and the store staging; cycle 2 runs healthy. Convergence:
    exactly one stall comment, exactly one proposal, the move retried — no dupes."""
    signal = cl.StallSignal(
        task_id=42, title="stuck", service_class=cl.ServiceClass.STANDARD,
        age_seconds=1e6, fingerprint="Standard:42",
    )
    snap = _snapshot(
        latest_run=_parked_run(),
        projects=(_project(ready_tasks=({"id": 1},), stalls=(signal,)),),
    )

    def raising_move(p: int, r: str, b: str) -> vb.BoardMoveResult:
        raise RuntimeError("crash before the board saw it")

    crash_env = _env(
        tmp_path, store, snap,
        move=raising_move, post=_PostSink(ok=False),
        read_acceptance=_acceptance("widget"),
    )
    crashed = _run(crash_env)
    assert any(not s.ok for s in crashed.steps)  # the crash was recorded, not raised
    assert len(store.list_active()) == 1  # staged before the 'crash'

    move = _MoveSink(accept_project=3)
    post = _PostSink()
    healthy_env = _env(
        tmp_path, store, snap, move=move, post=post,
        read_acceptance=_acceptance("widget"),
    )
    healthy = hc.run_wake_cycle(
        healthy_env, now=NOW + timedelta(minutes=15), local_now=LOCAL_DAY
    )
    assert len(store.list_active()) == 1  # fingerprint dedup: still ONE proposal
    assert len(post.calls) == 1  # the failed comment retried exactly once
    assert move.calls and move.calls[0][2] == cl.BUCKET_READY  # move retried
    # And a third cycle is fully silent on the sinks (episode + dedup algebra).
    third_post = _PostSink()
    third_env = _env(
        tmp_path, store, snap, move=_MoveSink(), post=third_post,
        read_acceptance=_acceptance("widget"),
    )
    hc.run_wake_cycle(third_env, now=NOW + timedelta(minutes=30), local_now=LOCAL_DAY)
    assert third_post.calls == []
    assert len(store.list_active()) == 1


def test_live_promotion_fault_repromotes_next_cycle(tmp_path, store, monkeypatch) -> None:
    """Review 66789b24 finding 1: a fault between add_draft and mark_staged leaves
    a never-surfaced DRAFT (staged_at == ''); the next live cycle re-promotes it
    via the dedup path instead of stranding it forever."""
    snap = _snapshot(latest_run=_parked_run())

    def boom(proposal_id, *, now=None):
        raise RuntimeError("transient store fault at promotion")

    monkeypatch.setattr(store, "mark_staged", boom)
    env = _env(
        tmp_path, store, snap, shadow_mode=False, read_acceptance=_acceptance("widget")
    )
    first = _run(env)
    assert first.promoted_proposal_ids == ()
    stranded = store.list_active()
    assert len(stranded) == 1
    assert stranded[0].status is ProposalStatus.DRAFT and not stranded[0].staged_at

    monkeypatch.undo()
    second = hc.run_wake_cycle(
        env, now=NOW + timedelta(minutes=15), local_now=LOCAL_DAY
    )
    assert len(second.promoted_proposal_ids) == 1
    assert store.get(second.promoted_proposal_ids[0]).status is ProposalStatus.STAGED


def test_ttl_demoted_draft_is_not_repromoted(tmp_path, store) -> None:
    """The finding-1 guard's other half: a TTL-demoted DRAFT (staged_at set) is
    never re-surfaced by the dedup path — that would rebuild the wall of stale
    asks §2.12.5 forbids."""
    snap = _snapshot(latest_run=_parked_run())
    env = _env(
        tmp_path, store, snap, shadow_mode=False, read_acceptance=_acceptance("widget")
    )
    first = _run(env)
    assert len(first.promoted_proposal_ids) == 1  # staged + promoted

    later = NOW + timedelta(days=8)  # past the 7-day TTL
    second = hc.run_wake_cycle(env, now=later, local_now=LOCAL_DAY)
    assert second.ttl_expired == 1  # the sweep demoted it
    assert second.promoted_proposal_ids == ()  # and it stays a quiet DRAFT
    assert store.list_active()[0].status is ProposalStatus.DRAFT


def test_board_history_corrupt_does_not_suppress_tripwire(tmp_path, store) -> None:
    """Review 66789b24 finding 2: the age record is not consulted by the tripwire
    predicate — its corruption must not mask a genuine quiet-queue alarm."""
    snap = _ready_snapshot(
        extra_substrate=(
            ws.SubstrateLiveness(
                name="board_history",
                status=vb.ReadStatus.UNREACHABLE,
                error="corrupt",
            ),
        )
    )
    result = _run(_env(tmp_path, store, snap))
    assert result.tripwire is not None and result.tripwire.fired


def test_latest_run_unreachable_suppresses_tripwire(tmp_path, store) -> None:
    """WIP unknown ≠ idle: an unreadable latest-run state suppresses the alarm."""
    snap = _ready_snapshot(latest_run=_tri(vb.ReadStatus.UNREACHABLE, error="torn"))
    result = _run(_env(tmp_path, store, snap))
    assert not result.tripwire.fired
    assert any("latest run state unreachable" in r for r in result.tripwire.suppressed_reasons)


def test_lingering_applied_stamp_never_reextends(tmp_path, store) -> None:
    """Review 66789b24 finding 3: once the exit extension has landed (applied_at
    set), a stamp whose clear failed only retries the clear — it never compounds
    the extension."""
    staged = _staged_proposal(store, staged_at=NOW)
    before = store.get(staged).expires_at
    env = _env(tmp_path, store, _snapshot())
    env.absence_stamp_path.parent.mkdir(parents=True, exist_ok=True)
    env.absence_stamp_path.write_text(
        json.dumps(
            {
                "absent_since": (NOW - timedelta(days=1)).isoformat(),
                "applied_at": NOW.isoformat(),
            }
        ),
        encoding="utf-8",
    )
    result = hc.run_wake_cycle(
        env, now=NOW + timedelta(hours=1), local_now=LOCAL_DAY
    )
    assert store.get(staged).expires_at == before  # NOT extended again
    assert not env.absence_stamp_path.exists()  # the clear was retried and landed
    assert result.absence is not None and not result.absence.ended_this_cycle
    assert not any(c.kind == "operator-absence-ended" for c in result.conditions)


def test_fresh_absence_supersedes_lingering_applied_stamp(tmp_path, store) -> None:
    """A NEW absence episode beginning while the previous episode's applied stamp
    lingers re-stamps fresh — the old episode's marker never leaks into the new
    episode's duration."""
    env = _env(tmp_path, store, _snapshot(), config=_absent_config())
    env.absence_stamp_path.parent.mkdir(parents=True, exist_ok=True)
    env.absence_stamp_path.write_text(
        json.dumps(
            {
                "absent_since": (NOW - timedelta(days=2)).isoformat(),
                "applied_at": (NOW - timedelta(days=1)).isoformat(),
            }
        ),
        encoding="utf-8",
    )
    result = _run(env)
    assert result.absence is not None and result.absence.started_this_cycle
    stamp = json.loads(env.absence_stamp_path.read_text(encoding="utf-8"))
    assert stamp["absent_since"] == NOW.isoformat()
    assert "applied_at" not in stamp


def test_digest_compose_failure_recorded_not_raised(tmp_path, store, monkeypatch) -> None:
    """Review 66789b24 finding 4: the digest step is wrapped like every other."""

    def boom(*a, **kw):
        raise RuntimeError("digest exploded")

    monkeypatch.setattr(hc, "_compose_digest", boom)
    result = _run(_env(tmp_path, store, _snapshot()))  # must not raise
    digest_steps = [s for s in result.steps if s.name == "digest"]
    assert digest_steps and not digest_steps[0].ok
    assert result.digest is None


def test_compose_failure_fails_cycle_softly(tmp_path, store) -> None:
    def boom(now: datetime) -> ws.WorkStateSnapshot:
        raise RuntimeError("vikunja timeout mid-compose")

    env = replace(_env(tmp_path, store, _snapshot()), compose_snapshot=boom)
    result = _run(env)  # must NOT raise
    assert any(c.kind == "compose-failed" and c.machinery_health for c in result.conditions)
    assert result.snapshot is None and result.digest is None
