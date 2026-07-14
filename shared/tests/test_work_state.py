"""Locks for the work-state snapshot composer (#843, ADR-039 §2.10 / §2.14.5).

Every substrate read is exercised through its OWN tri-state outcomes
(OK/EMPTY/UNREACHABLE) using tmp_path fixtures (files) and the same
FakeVikunja fake transport ``test_vikunja_bridge.py`` uses (no live Vikunja,
no live fleet state — fully offline).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from shared.fleet import acp_progress as ap
from shared.fleet import coord_lifecycle as cl
from shared.fleet import coord_stall_state as css
from shared.fleet import swap_state as ss
from shared.fleet import vikunja_bridge as vb
from shared.fleet import work_state as ws
from shared.fleet.dispatch import FleetDispatchConfig
from shared.tests.test_vikunja_bridge import FakeVikunja

_NOW = datetime(2026, 7, 12, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _loopback_env(monkeypatch):
    """Mirror test_vikunja_bridge.py's hermetic loopback env — work_state
    calls into vikunja_bridge, which resolves credentials from these vars."""
    monkeypatch.setenv("VIKUNJA_URL", "http://localhost:3456")
    monkeypatch.setenv("VIKUNJA_USER", "blarai")
    monkeypatch.setenv("VIKUNJA_PASS", "test-pass")


def _config(tmp_path: Path) -> FleetDispatchConfig:
    return FleetDispatchConfig(
        scripts_dir=tmp_path / "scripts",
        queue_path=tmp_path / "state" / "fleet-queue.json",
        runs_dir=tmp_path / "state" / "fleet-runs",
        projects_dir=tmp_path / "projects",
    )


# ---------------------------------------------------------------------------
# read_swap_snapshot
# ---------------------------------------------------------------------------


def test_swap_snapshot_empty_when_file_absent(tmp_path):
    cfg = _config(tmp_path)
    result = ws.read_swap_snapshot(cfg)
    assert result.status == vb.ReadStatus.EMPTY
    assert result.value is None
    assert result.ok is True  # EMPTY is still a successful read


def test_swap_snapshot_ok_when_valid(tmp_path):
    from shared.fleet.swap_ops import swap_state_path

    cfg = _config(tmp_path)
    path = swap_state_path(cfg)
    state = ss.SwapState(run_id="R1", session_id="S1", phase=ss.PHASE_CODE)
    ss.write_swap_state(state, path=path)

    result = ws.read_swap_snapshot(cfg)
    assert result.status == vb.ReadStatus.OK
    assert result.value.run_id == "R1"
    assert result.value.phase == ss.PHASE_CODE


def test_swap_snapshot_unreachable_when_file_corrupt(tmp_path):
    from shared.fleet.swap_ops import swap_state_path

    cfg = _config(tmp_path)
    path = swap_state_path(cfg)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{not valid json", encoding="utf-8")

    result = ws.read_swap_snapshot(cfg)
    assert result.status == vb.ReadStatus.UNREACHABLE
    assert result.ok is False
    assert result.error


def test_swap_snapshot_unreachable_never_equals_empty_status(tmp_path):
    """THE lock: a corrupt file (UNREACHABLE) must never present the same
    status as a genuinely-absent one (EMPTY) — a caller branching on
    ``result.status`` alone must be able to tell a real problem from a
    quiet boot."""
    from shared.fleet.swap_ops import swap_state_path

    absent = ws.read_swap_snapshot(_config(tmp_path))

    corrupt_cfg = _config(tmp_path / "corrupt")
    path = swap_state_path(corrupt_cfg)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{garbage", encoding="utf-8")
    corrupt = ws.read_swap_snapshot(corrupt_cfg)

    assert absent.status == vb.ReadStatus.EMPTY
    assert corrupt.status == vb.ReadStatus.UNREACHABLE
    assert absent.status != corrupt.status


def test_swap_in_flight_computed_from_non_terminal_phase(tmp_path):
    from shared.fleet.swap_ops import swap_state_path

    cfg = _config(tmp_path)
    path = swap_state_path(cfg)
    ss.write_swap_state(
        ss.SwapState(run_id="R1", session_id="S1", phase=ss.PHASE_CODE), path=path
    )
    snap = ws.compose_work_state(
        fleet_config=cfg, coordinator_projects={}, now=_NOW, vikunja_transport=FakeVikunja()
    )
    assert snap.swap_in_flight is True


def test_swap_not_in_flight_when_idle(tmp_path):
    from shared.fleet.swap_ops import swap_state_path

    cfg = _config(tmp_path)
    path = swap_state_path(cfg)
    ss.write_swap_state(
        ss.SwapState(run_id="R1", session_id="S1", phase=ss.PHASE_IDLE), path=path
    )
    snap = ws.compose_work_state(
        fleet_config=cfg, coordinator_projects={}, now=_NOW, vikunja_transport=FakeVikunja()
    )
    assert snap.swap_in_flight is False


def test_swap_not_in_flight_when_absent(tmp_path):
    cfg = _config(tmp_path)
    snap = ws.compose_work_state(
        fleet_config=cfg, coordinator_projects={}, now=_NOW, vikunja_transport=FakeVikunja()
    )
    assert snap.swap_in_flight is False  # EMPTY (no file) must not read as "in flight"


# ---------------------------------------------------------------------------
# read_fleet_queue
# ---------------------------------------------------------------------------


def test_fleet_queue_empty_when_absent(tmp_path):
    cfg = _config(tmp_path)
    result = ws.read_fleet_queue(cfg)
    assert result.status == vb.ReadStatus.EMPTY


def test_fleet_queue_ok_when_valid_json(tmp_path):
    cfg = _config(tmp_path)
    cfg.queue_path.parent.mkdir(parents=True, exist_ok=True)
    cfg.queue_path.write_text('{"tasks": [1, 2, 3]}', encoding="utf-8")
    result = ws.read_fleet_queue(cfg)
    assert result.status == vb.ReadStatus.OK
    assert result.value == {"tasks": [1, 2, 3]}


def test_fleet_queue_unreachable_when_malformed(tmp_path):
    cfg = _config(tmp_path)
    cfg.queue_path.parent.mkdir(parents=True, exist_ok=True)
    cfg.queue_path.write_text("{not json", encoding="utf-8")
    result = ws.read_fleet_queue(cfg)
    assert result.status == vb.ReadStatus.UNREACHABLE
    assert result.error


def test_fleet_queue_empty_when_blank_file(tmp_path):
    cfg = _config(tmp_path)
    cfg.queue_path.parent.mkdir(parents=True, exist_ok=True)
    cfg.queue_path.write_text("   \n", encoding="utf-8")
    result = ws.read_fleet_queue(cfg)
    assert result.status == vb.ReadStatus.EMPTY


# ---------------------------------------------------------------------------
# read_campaign_state
# ---------------------------------------------------------------------------


def test_campaign_state_empty_when_path_unconfigured():
    result = ws.read_campaign_state(None)
    assert result.status == vb.ReadStatus.EMPTY
    assert result.ok is True


def test_campaign_state_ok_when_valid(tmp_path):
    p = tmp_path / "campaign.json"
    p.write_text('{"completed_passes": 3}', encoding="utf-8")
    result = ws.read_campaign_state(p)
    assert result.status == vb.ReadStatus.OK
    assert result.value == {"completed_passes": 3}


def test_campaign_state_unreachable_when_configured_but_unreadable(tmp_path):
    p = tmp_path / "campaign.json"
    p.write_text("{broken", encoding="utf-8")
    result = ws.read_campaign_state(p)
    assert result.status == vb.ReadStatus.UNREACHABLE


# ---------------------------------------------------------------------------
# read_latest_run_summary
# ---------------------------------------------------------------------------


def test_run_summary_empty_when_no_runs(tmp_path):
    cfg = _config(tmp_path)
    result = ws.read_latest_run_summary(cfg)
    assert result.status == vb.ReadStatus.EMPTY


def test_run_summary_empty_when_run_dir_exists_but_no_summary_yet(tmp_path):
    cfg = _config(tmp_path)
    (cfg.runs_dir / "20260712-120000-bd").mkdir(parents=True)
    result = ws.read_latest_run_summary(cfg)
    assert result.status == vb.ReadStatus.EMPTY
    assert result.value == ("20260712-120000-bd", ())


def test_run_summary_ok_when_outcomes_parse(tmp_path):
    cfg = _config(tmp_path)
    run_dir = cfg.runs_dir / "20260712-120000-bd"
    run_dir.mkdir(parents=True)
    summary_text = (
        "- calc: built\n"
        "  RESULT: merged cleanly\n"
        "  full report: some/path.txt\n"
    )
    (run_dir / "SUMMARY.txt").write_text(summary_text, encoding="utf-8")
    result = ws.read_latest_run_summary(cfg)
    assert result.status == vb.ReadStatus.OK
    run_id, outcomes = result.value
    assert run_id == "20260712-120000-bd"
    assert len(outcomes) == 1
    assert outcomes[0].result == "MERGED"


# ---------------------------------------------------------------------------
# read_project_work_state — board + summary + flow, UNREACHABLE propagation
# ---------------------------------------------------------------------------


def test_project_work_state_composes_board_summary_flow():
    fake = FakeVikunja()
    fake.seed_view(7, 2, title="Board", kind="kanban")
    fake.seed_bucket(7, 2, 10, title="Ready")
    fake.seed_task(7, title="t1", done=False, bucket_id=10, created="2026-07-10T12:00:00Z")
    fake.seed_task(7, title="t2-done", done=True, created="2026-07-01T00:00:00Z", done_at="2026-07-05T00:00:00Z")

    pw = ws.read_project_work_state("Coder Jobs", 7, now=_NOW, transport=fake)
    assert pw.name == "Coder Jobs"
    assert pw.project_id == 7
    assert pw.board.status == vb.ReadStatus.OK
    assert pw.summary.status == vb.ReadStatus.OK
    assert pw.flow is not None
    assert pw.flow.open_count == 1
    assert len(pw.flow.cycle_times_seconds) == 1  # the done task contributes a cycle time


def test_project_work_state_flow_none_when_unreachable():
    fake = FakeVikunja(fail=True)
    pw = ws.read_project_work_state("Coder Jobs", 7, now=_NOW, transport=fake)
    assert pw.flow is None
    assert pw.board.status == vb.ReadStatus.UNREACHABLE
    assert pw.summary.status == vb.ReadStatus.UNREACHABLE


def test_project_work_state_unbucketed_task_not_lost_from_flow():
    """The bug this module's design note calls out: a task with NO
    bucket_id must still count toward flow metrics (age/aging-WIP), even
    though board_state's per-bucket grouping would never attribute it to
    any bucket."""
    fake = FakeVikunja()
    fake.seed_view(7, 2, title="Board", kind="kanban")
    fake.seed_bucket(7, 2, 10, title="Ready")
    # No bucket_id at all -> board_state's buckets would show ZERO tasks,
    # but flow metrics must still see this task.
    fake.seed_task(7, title="unbucketed", done=False, created="2026-07-10T12:00:00Z")

    pw = ws.read_project_work_state("Coder Jobs", 7, now=_NOW, transport=fake)
    assert pw.board.items[0]["tasks"] == []  # confirms the bucket really is empty
    assert pw.flow is not None
    assert pw.flow.open_count == 1  # but the task is NOT lost from flow metrics
    assert pw.flow.ages[0].title == "unbucketed"


# ---------------------------------------------------------------------------
# compose_work_state — the full snapshot
# ---------------------------------------------------------------------------


def test_compose_work_state_empty_projects_mapping(tmp_path):
    cfg = _config(tmp_path)
    snap = ws.compose_work_state(
        fleet_config=cfg, coordinator_projects={}, now=_NOW, vikunja_transport=FakeVikunja()
    )
    assert snap.projects == ()
    assert snap.computed_at == _NOW.isoformat()


def test_compose_work_state_full_composition(tmp_path):
    cfg = _config(tmp_path)
    fake = FakeVikunja()
    fake.seed_task(7, title="t1", done=False, created="2026-07-10T12:00:00Z")

    snap = ws.compose_work_state(
        fleet_config=cfg,
        coordinator_projects={"Coder Jobs": 7},
        now=_NOW,
        vikunja_transport=fake,
    )
    assert len(snap.projects) == 1
    assert snap.projects[0].name == "Coder Jobs"
    assert snap.projects[0].flow.open_count == 1
    # substrate liveness is populated for every consulted substrate
    names = {s.name for s in snap.substrate}
    assert names == {"vikunja", "fleet_swap_state", "fleet_queue"}
    vikunja_status = next(s for s in snap.substrate if s.name == "vikunja")
    assert vikunja_status.status == vb.ReadStatus.OK


def test_compose_work_state_vikunja_down_surfaces_on_substrate_not_silently(tmp_path):
    """A dead Vikunja must be a SURFACED substrate condition — never look
    like zero configured projects or a quiet board (ADR-039 §2.12.6)."""
    cfg_tmp = _config(tmp_path)  # no fleet-state files written -> absent-EMPTY, unrelated to the Vikunja probe
    fake = FakeVikunja(fail=True)
    snap = ws.compose_work_state(
        fleet_config=cfg_tmp,
        coordinator_projects={"Coder Jobs": 7},
        now=_NOW,
        vikunja_transport=fake,
    )
    vikunja_status = next(s for s in snap.substrate if s.name == "vikunja")
    assert vikunja_status.status == vb.ReadStatus.UNREACHABLE
    assert vikunja_status.error
    assert snap.projects[0].flow is None  # not silently zero/empty
    assert snap.projects[0].board.status == vb.ReadStatus.UNREACHABLE


def test_compose_work_state_defaults_now_to_real_clock(tmp_path):
    """now= is optional — the composer must still work end-to-end without
    a caller-injected clock (production path). vikunja_transport is still a
    fake (offline-only tests, per the C1 build brief) — this test's OWN
    concern is the clock default, not live Vikunja reachability."""
    cfg = _config(tmp_path)
    snap = ws.compose_work_state(
        fleet_config=cfg, coordinator_projects={}, vikunja_transport=FakeVikunja()
    )
    assert snap.computed_at  # some ISO timestamp was recorded
    parsed = datetime.fromisoformat(snap.computed_at)
    assert parsed.tzinfo is not None


# ---------------------------------------------------------------------------
# Stall detection on the snapshot (#844 C2) + the ONE seen-set read
# ---------------------------------------------------------------------------


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


def test_project_stalls_detected_from_open_tasks(tmp_path):
    """read_project_work_state runs per-class detect_stalls over the SAME open
    tasks it already fetched — three ~1h items + one 100h item -> one outlier."""
    fake = FakeVikunja()
    for _ in range(3):
        fake.seed_task(
            7, title="recent", done=False, created=_iso(_NOW - timedelta(hours=1))
        )
    stuck = fake.seed_task(
        7, title="stuck", done=False, created=_iso(_NOW - timedelta(hours=100))
    )
    pw = ws.read_project_work_state("Coder Jobs", 7, now=_NOW, transport=fake)
    assert [s.task_id for s in pw.stalls] == [stuck]
    assert pw.stalls[0].service_class is cl.ServiceClass.STANDARD


def test_project_stalls_empty_when_board_unreachable(tmp_path):
    """No stalls over an UNKNOWN board (the same honesty as ``flow=None``)."""
    fake = FakeVikunja(fail=True)
    pw = ws.read_project_work_state("Coder Jobs", 7, now=_NOW, transport=fake)
    assert pw.stalls == ()
    assert pw.flow is None


def test_compose_reads_stall_seen_fingerprints(tmp_path):
    seen = tmp_path / "coord" / "stall_seen.json"
    css.write_seen_state(
        css.StallSeenState(frozenset({"Standard:4"}), _NOW.isoformat()), path=seen
    )
    snap = ws.compose_work_state(
        fleet_config=_config(tmp_path),
        coordinator_projects={},
        now=_NOW,
        stall_seen_path=seen,
        vikunja_transport=FakeVikunja(),
    )
    assert snap.stall_seen_fingerprints == frozenset({"Standard:4"})


def test_compose_without_seen_path_is_empty_fingerprints(tmp_path):
    """No seen path -> everything reads as NEW, never falsely 'flagged'."""
    snap = ws.compose_work_state(
        fleet_config=_config(tmp_path),
        coordinator_projects={},
        now=_NOW,
        vikunja_transport=FakeVikunja(),
    )
    assert snap.stall_seen_fingerprints == frozenset()


def test_compose_with_unreadable_seen_path_fail_soft_empty(tmp_path):
    """A corrupt seen-set must not crash the read surface — it degrades to empty
    (ADR-039 §2.12.6 applied to the seen-set read)."""
    seen = tmp_path / "stall_seen.json"
    seen.write_text("{garbage", encoding="utf-8")
    snap = ws.compose_work_state(
        fleet_config=_config(tmp_path),
        coordinator_projects={},
        now=_NOW,
        stall_seen_path=seen,
        vikunja_transport=FakeVikunja(),
    )
    assert snap.stall_seen_fingerprints == frozenset()


# ---------------------------------------------------------------------------
# read_acp_run_progress (#844 C2) — the latest coder run's durable ACP progress
# ---------------------------------------------------------------------------


def _seed_acp_progress(cfg, run_id, *, age_s, summary_done=False):
    run_dir = cfg.runs_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    if summary_done:
        (run_dir / "SUMMARY.txt").write_text("done", encoding="utf-8")
    ap.write_acp_progress(
        ap.AcpProgressSnapshot(
            run_id=run_id,
            last_event_at=(_NOW - timedelta(seconds=age_s)).isoformat(),
            steps=2, edits=1, event_count=3,
        ),
        path=run_dir / ap.ACP_PROGRESS_FILENAME,
    )


def test_acp_progress_ok_active_run_recent(tmp_path, monkeypatch):
    cfg = _config(tmp_path)
    _seed_acp_progress(cfg, "R9", age_s=30)
    monkeypatch.setattr(ws.fleet, "latest_run_id", lambda *, config: "R9")
    res = ws.read_acp_run_progress(cfg, now=_NOW)
    assert res.status == vb.ReadStatus.OK
    assert res.value.run_id == "R9"
    assert res.value.run_active is True
    assert res.value.quiet is False  # 30 s < 300 s default


def test_acp_progress_active_stale_is_quiet(tmp_path, monkeypatch):
    cfg = _config(tmp_path)
    _seed_acp_progress(cfg, "R9", age_s=400)
    monkeypatch.setattr(ws.fleet, "latest_run_id", lambda *, config: "R9")
    res = ws.read_acp_run_progress(cfg, now=_NOW)
    assert res.status == vb.ReadStatus.OK
    assert res.value.quiet is True


def test_acp_progress_finished_run_never_quiet(tmp_path, monkeypatch):
    cfg = _config(tmp_path)
    _seed_acp_progress(cfg, "R9", age_s=9999, summary_done=True)  # SUMMARY -> finished
    monkeypatch.setattr(ws.fleet, "latest_run_id", lambda *, config: "R9")
    res = ws.read_acp_run_progress(cfg, now=_NOW)
    assert res.status == vb.ReadStatus.OK
    assert res.value.run_active is False
    assert res.value.quiet is False  # a finished run is never 'quiet'


def test_acp_progress_empty_when_no_run(tmp_path, monkeypatch):
    cfg = _config(tmp_path)
    monkeypatch.setattr(ws.fleet, "latest_run_id", lambda *, config: "")
    res = ws.read_acp_run_progress(cfg, now=_NOW)
    assert res.status == vb.ReadStatus.EMPTY


def test_acp_progress_empty_when_run_has_no_artifact(tmp_path, monkeypatch):
    cfg = _config(tmp_path)
    (cfg.runs_dir / "R9").mkdir(parents=True)  # a run dir but no acp-progress.json
    monkeypatch.setattr(ws.fleet, "latest_run_id", lambda *, config: "R9")
    res = ws.read_acp_run_progress(cfg, now=_NOW)
    assert res.status == vb.ReadStatus.EMPTY


def test_acp_progress_unreachable_when_corrupt(tmp_path, monkeypatch):
    cfg = _config(tmp_path)
    run_dir = cfg.runs_dir / "R9"
    run_dir.mkdir(parents=True)
    (run_dir / ap.ACP_PROGRESS_FILENAME).write_text("{garbage", encoding="utf-8")
    monkeypatch.setattr(ws.fleet, "latest_run_id", lambda *, config: "R9")
    res = ws.read_acp_run_progress(cfg, now=_NOW)
    assert res.status == vb.ReadStatus.UNREACHABLE
    assert res.value is None
    assert res.error


def test_compose_includes_acp_progress_empty_by_default(tmp_path):
    snap = ws.compose_work_state(
        fleet_config=_config(tmp_path), coordinator_projects={}, now=_NOW,
        vikunja_transport=FakeVikunja(),
    )
    assert snap.acp_progress.status == vb.ReadStatus.EMPTY
