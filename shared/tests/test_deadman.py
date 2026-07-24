"""Locks for the C3 dead-man watchdog + boot reconcile (#845 limb 7, design §6).

The keyed acceptance shapes: a heartbeat that stops stamping trips the watchdog
surface; ``thread_dead=true`` trips immediately; the watchdog is ABSENT when the
heartbeat is disabled (the same factory gate). Plus the §6.2 anti-false-alarm
properties: the stamp's own deadline rules (no fixed K×interval), one alert per
stale episode with re-arm on a fresh stamp, a clean stop reads as quiet, and the
§6.3 boot reconcile's three-way split.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

from shared.coordinator import deadman as dm
from shared.coordinator import heartbeat as hb

NOW = datetime(2026, 7, 14, 21, 0, 0, tzinfo=timezone.utc)

#: This boot's stamp identity in these fixtures (review 06a5b435 MAJOR 1).
SESSION = "s-current"


def _write_stamp(path: Path, **overrides) -> None:
    payload = {
        "started_at": NOW.isoformat(),
        "completed_at": NOW.isoformat(),
        "mode": "FULL",
        "next_interval_s": 900.0,
        "next_expected_by": (NOW + timedelta(seconds=900)).isoformat(),
        "shadow_mode": True,
        "thread_dead": False,
        "stopped_cleanly": False,
        "session_id": SESSION,
        "steps": [],
        "note": "",
    }
    payload.update(overrides)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _watchdog(tmp_path: Path, **kw) -> "tuple[dm.DeadManWatchdog, list[str]]":
    alerts: list[str] = []
    stamp = tmp_path / "coord" / "heartbeat-liveness.json"
    kw.setdefault("stamp_path", stamp)
    kw.setdefault("session_id", SESSION)
    kw.setdefault("alert", alerts.append)
    return dm.DeadManWatchdog(**kw), alerts


# ---------------------------------------------------------------------------
# The one comparison (§6.2) — driven through check_once with injected clocks
# ---------------------------------------------------------------------------


def test_fresh_stamp_is_quiet(tmp_path: Path) -> None:
    wd, alerts = _watchdog(tmp_path)
    _write_stamp(wd._stamp_path)  # noqa: SLF001
    assert wd.check_once(NOW + timedelta(seconds=100)) is None
    assert alerts == []


def test_stale_stamp_trips_the_surface(tmp_path: Path) -> None:
    """The keyed lock: a heartbeat that stops stamping is DETECTED — the
    stamp's own deadline plus the registered slack, nothing else."""
    wd, alerts = _watchdog(tmp_path)
    _write_stamp(wd._stamp_path)  # noqa: SLF001 — deadline NOW+900
    late = NOW + timedelta(seconds=900 + dm.DEADMAN_SLACK_S + 1)
    message = wd.check_once(late)
    assert message is not None and "LATE" in message
    assert len(alerts) == 1


def test_stretched_deadline_never_false_alarms(tmp_path: Path) -> None:
    """A battery-stretched cycle declares its longer deadline itself — the
    watchdog honors it (the design-review MAJOR that killed K×interval)."""
    wd, alerts = _watchdog(tmp_path)
    _write_stamp(
        wd._stamp_path,  # noqa: SLF001
        next_interval_s=3600.0,
        next_expected_by=(NOW + timedelta(seconds=3600)).isoformat(),
    )
    # Late by AC standards (900s), comfortably inside the declared 3600s.
    assert wd.check_once(NOW + timedelta(seconds=1500)) is None
    assert alerts == []


def test_thread_dead_trips_immediately(tmp_path: Path) -> None:
    wd, alerts = _watchdog(tmp_path)
    _write_stamp(wd._stamp_path, thread_dead=True, note="RuntimeError: boom")  # noqa: SLF001
    message = wd.check_once(NOW)  # no deadline math — immediate
    assert message is not None and "DIED" in message and "boom" in message
    assert len(alerts) == 1


def test_one_alert_per_episode_and_rearm(tmp_path: Path) -> None:
    wd, alerts = _watchdog(tmp_path)
    _write_stamp(wd._stamp_path)  # noqa: SLF001
    late = NOW + timedelta(seconds=900 + dm.DEADMAN_SLACK_S + 1)
    assert wd.check_once(late) is not None
    assert wd.check_once(late + timedelta(seconds=60)) is None  # same episode
    assert len(alerts) == 1
    # A fresh stamp re-arms; a NEW staleness is a NEW episode.
    fresh_deadline = late + timedelta(seconds=900)
    _write_stamp(
        wd._stamp_path,  # noqa: SLF001
        next_expected_by=fresh_deadline.isoformat(),
    )
    assert wd.check_once(late + timedelta(seconds=120)) is None  # healthy again
    assert (
        wd.check_once(fresh_deadline + timedelta(seconds=dm.DEADMAN_SLACK_S + 1))
        is not None
    )
    assert len(alerts) == 2


def test_no_stamp_past_boot_expectation_trips(tmp_path: Path) -> None:
    """The grace anchors at the FIRST check (review 06a5b435 NIT 9), then a
    persistent silence past it trips once."""
    wd, alerts = _watchdog(tmp_path, initial_grace_s=1200.0)
    assert wd.check_once(NOW) is None  # anchors NOW+1200
    assert wd.check_once(NOW + timedelta(seconds=600)) is None  # still expected
    message = wd.check_once(NOW + timedelta(seconds=1201))
    assert message is not None and "NO current-session liveness stamp" in message
    assert len(alerts) == 1


def test_foreign_stamps_route_to_grace_uniformly(tmp_path: Path) -> None:
    """Review 06a5b435 MAJOR 1: a leftover PRIOR-session stamp — stale, dead,
    malformed, or missing its id entirely — reads as no-current-stamp. Inside
    the boot grace it is QUIET (the boot reconcile owns the past tense); past
    the grace it trips as no-first-beat, never as a present-tense wedge."""
    foreign_shapes = (
        # A crash leftover: long-stale deadline.
        {"session_id": "s-previous",
         "next_expected_by": (NOW - timedelta(days=1)).isoformat()},
        # A prior session's died thread.
        {"session_id": "s-previous", "thread_dead": True, "note": "old boom"},
        # A prior session's malformed deadline.
        {"session_id": "s-previous", "next_expected_by": "garbage"},
        # A pre-session-id stamp (no id at all) — reads as NOT MINE.
        {"session_id": None},
    )
    for overrides in foreign_shapes:
        wd, alerts = _watchdog(tmp_path, initial_grace_s=1200.0)
        _write_stamp(wd._stamp_path, **overrides)  # noqa: SLF001
        assert wd.check_once(NOW) is None, overrides  # anchors + quiet in grace
        assert alerts == [], overrides
        late = wd.check_once(NOW + timedelta(seconds=1201))
        assert late is not None and "NO current-session" in late, overrides
        assert "DIED" not in late and "LATE" not in late, overrides


def test_current_session_beat_after_foreign_stamp_rearms_normal_rules(
    tmp_path: Path,
) -> None:
    """Once THIS session beats, the normal stamp rules govern again."""
    wd, alerts = _watchdog(tmp_path, initial_grace_s=1200.0)
    _write_stamp(
        wd._stamp_path,  # noqa: SLF001
        session_id="s-previous",
        next_expected_by=(NOW - timedelta(days=1)).isoformat(),
    )
    assert wd.check_once(NOW) is None  # foreign: quiet
    _write_stamp(wd._stamp_path)  # the current session's first beat  # noqa: SLF001
    assert wd.check_once(NOW + timedelta(seconds=100)) is None  # healthy
    late = wd.check_once(NOW + timedelta(seconds=900 + dm.DEADMAN_SLACK_S + 1))
    assert late is not None and "LATE" in late  # present-tense rules apply
    assert len(alerts) == 1


def test_clean_stop_reads_as_quiet(tmp_path: Path) -> None:
    wd, alerts = _watchdog(tmp_path)
    _write_stamp(
        wd._stamp_path,  # noqa: SLF001
        stopped_cleanly=True,
        next_expected_by="",
        mode="STOPPED",
    )
    assert wd.check_once(NOW + timedelta(days=1)) is None  # nothing is due
    assert alerts == []


def test_malformed_deadline_reads_as_wedged(tmp_path: Path) -> None:
    """Unknown ≠ healthy: an unparseable deadline is itself the alarm."""
    wd, alerts = _watchdog(tmp_path)
    _write_stamp(wd._stamp_path, next_expected_by="not-a-time")  # noqa: SLF001
    assert wd.check_once(NOW) is not None
    assert len(alerts) == 1


def test_raising_alert_sink_retries_instead_of_consuming_the_episode(
    tmp_path: Path,
) -> None:
    """Review 06a5b435 MINOR 3: a raising sink is logged and NOT latched — the
    episode retries next poll and lands the moment the sink recovers."""
    sink_box: dict = {"raise": True, "delivered": []}

    def flaky(message: str) -> None:
        if sink_box["raise"]:
            raise RuntimeError("surface down")
        sink_box["delivered"].append(message)

    wd, _ = _watchdog(tmp_path, alert=flaky)
    _write_stamp(wd._stamp_path, thread_dead=True)  # noqa: SLF001
    assert wd.check_once(NOW) is not None  # returned, logged, no raise
    assert wd.check_once(NOW + timedelta(seconds=30)) is not None  # retried
    sink_box["raise"] = False
    assert wd.check_once(NOW + timedelta(seconds=60)) is not None  # delivered
    assert len(sink_box["delivered"]) == 1
    assert wd.check_once(NOW + timedelta(seconds=90)) is None  # NOW latched


def test_real_thread_wedge_trips_within_poll_budget(tmp_path: Path) -> None:
    """The wedge-trips-surface lock on the REAL thread: fast poll, tiny slack,
    a stamp that never refreshes — the alert lands within the poll budget.
    Deadline relative to the REAL clock the thread uses (review NIT 8)."""
    alerts: list[str] = []
    stamp = tmp_path / "coord" / "heartbeat-liveness.json"
    real_now = datetime.now(timezone.utc)
    _write_stamp(
        stamp, next_expected_by=(real_now - timedelta(seconds=10)).isoformat()
    )
    wd = dm.DeadManWatchdog(
        stamp_path=stamp,
        session_id=SESSION,
        alert=alerts.append,
        slack_s=0.01,
        poll_s=0.01,
    )
    wd.start()
    deadline = time.monotonic() + 5.0
    while not alerts and time.monotonic() < deadline:
        time.sleep(0.01)
    wd.stop()
    assert alerts, "the wedged stamp never tripped the surface"


def test_trip_reaches_operator_surface_through_the_real_router(tmp_path: Path) -> None:
    """Review 06a5b435 MINOR 6 — the built-but-wired-into-nothing seam, driven
    end to end: a trip through the SAME route_health adapter shape the factory
    wires, over a REAL router and REAL born-encrypted journal — the operator
    surface hears it, the journal records NOTHING (health is unjournalable)."""
    from shared.coordinator.heartbeat_cycle import SurfacedCondition
    from shared.coordinator.output_router import build_output_router
    from shared.coordinator.shadow_journal import build_shadow_journal

    journal = build_shadow_journal(":memory:")
    try:
        surfaced: list[str] = []
        router = build_output_router(
            shadow_mode=True, journal=journal, operator_surface=surfaced.append
        )

        def health_alert(message: str) -> None:
            router.route_health(
                SurfacedCondition("dead-man", message, machinery_health=True)
            )

        wd, _ = _watchdog(tmp_path, alert=health_alert)
        _write_stamp(wd._stamp_path, thread_dead=True, note="boom")  # noqa: SLF001
        assert wd.check_once(NOW) is not None
        assert surfaced and "DIED" in surfaced[0]
        assert journal.count() == 0  # never shadow-gated, never journaled
    finally:
        journal.close()


def test_watchdog_absent_when_heartbeat_disabled() -> None:
    """The §6/§11 acceptance shape, asserted directly (review 06a5b435 MINOR
    5): no heartbeat, no watchdog — the same factory gate builds both."""
    disabled = SimpleNamespace(coordinator_heartbeat_enabled=False)
    assert hb.build_heartbeat(disabled, cleanup_started=lambda: False) is None


# ---------------------------------------------------------------------------
# Boot reconcile (§6.3)
# ---------------------------------------------------------------------------


def test_reconcile_thread_dead_notices(tmp_path: Path) -> None:
    notice = dm.reconcile_boot_stamp(
        {"thread_dead": True, "note": "boom", "completed_at": "T"}
    )
    assert notice is not None and "DIED" in notice and "boom" in notice


def test_reconcile_unclean_end_notices(tmp_path: Path) -> None:
    notice = dm.reconcile_boot_stamp(
        {"thread_dead": False, "stopped_cleanly": False, "completed_at": "T",
         "next_expected_by": "D"}
    )
    assert notice is not None and "WITHOUT a clean" in notice


def test_reconcile_clean_stop_and_missing_are_silent() -> None:
    assert dm.reconcile_boot_stamp({"stopped_cleanly": True}) is None
    assert dm.reconcile_boot_stamp(None) is None


# ---------------------------------------------------------------------------
# The heartbeat pairing (§6.2 "no heartbeat, no watchdog") + the clean stop
# ---------------------------------------------------------------------------


class _WatchdogRecorder:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def start(self) -> None:
        self.calls.append("start")

    def stop(self) -> None:
        self.calls.append("stop")


def _paired_heartbeat(
    tmp_path: Path,
    recorder: _WatchdogRecorder,
    clock: "object | None" = None,
) -> hb.Heartbeat:
    from shared.coordinator import cadence
    from shared.coordinator import heartbeat_cycle as hc

    def cycle_fn(env, **kw):
        return hc.CycleResult(
            started_at=NOW.isoformat(),
            decision=cadence.CycleDecision(
                mode=cadence.CycleMode.FULL, next_interval_s=900.0
            ),
        )

    class _NullRouter:
        def route_tripwire(self, c):
            pass

        def record_proposal_copy(self, p):
            pass

        def route_digest(self, d):
            pass

    return hb.Heartbeat(
        env=SimpleNamespace(),
        router=_NullRouter(),
        interval_s=900.0,
        boot_grace_s=0.0,
        shadow_mode=True,
        stamp_path=tmp_path / "coord" / "heartbeat-liveness.json",
        seen_path=tmp_path / "coord" / "stall_seen.json",
        cleanup_started=lambda: False,
        clock=clock or (lambda: NOW),
        local_clock=lambda: datetime(2026, 7, 14, 16, 0, 0),
        cycle_fn=cycle_fn,
        max_cycles=1,
        watchdog=recorder,
        session_id=SESSION,
    )


def test_start_and_stop_drive_the_watchdog(tmp_path: Path) -> None:
    recorder = _WatchdogRecorder()
    beat = _paired_heartbeat(tmp_path, recorder)
    beat.start()
    beat._thread.join(timeout=10.0)  # noqa: SLF001
    beat.stop()
    assert recorder.calls == ["start", "stop"]


def test_stop_writes_the_clean_stop_marker(tmp_path: Path) -> None:
    recorder = _WatchdogRecorder()
    beat = _paired_heartbeat(tmp_path, recorder)
    beat.start()
    beat._thread.join(timeout=10.0)  # noqa: SLF001
    beat.stop()
    stamp = json.loads(
        (tmp_path / "coord" / "heartbeat-liveness.json").read_text(encoding="utf-8")
    )
    assert stamp["stopped_cleanly"] is True
    assert stamp["mode"] == "STOPPED"
    assert stamp["next_expected_by"] == ""  # nothing is due — the §6.3 marker
    # And the next boot's reconcile reads it as silence.
    assert dm.reconcile_boot_stamp(stamp) is None


def test_stop_skips_the_marker_when_the_heartbeat_was_overdue(tmp_path: Path) -> None:
    """Review 06a5b435 MAJOR 2: a wedge that rides into a clean shutdown is NOT
    buried — the clean-stop marker is skipped when this session's stamp was
    already past its own deadline + slack at teardown, so the boot reconcile
    still voices it next session."""
    clock_box = {"now": NOW}
    recorder = _WatchdogRecorder()
    beat = _paired_heartbeat(tmp_path, recorder, clock=lambda: clock_box["now"])
    beat.start()
    beat._thread.join(timeout=10.0)  # noqa: SLF001 — one cycle stamped (deadline NOW+900)
    # Teardown arrives long past the declared deadline + slack: the wedge case.
    clock_box["now"] = NOW + timedelta(seconds=900 + dm.DEADMAN_SLACK_S + 60)
    beat.stop()
    stamp = json.loads(
        (tmp_path / "coord" / "heartbeat-liveness.json").read_text(encoding="utf-8")
    )
    assert stamp["stopped_cleanly"] is False  # the marker was withheld
    notice = dm.reconcile_boot_stamp(stamp)
    assert notice is not None and "WITHOUT a clean" in notice


def test_stop_never_overwrites_a_thread_dead_stamp(tmp_path: Path) -> None:
    """The wall-3 record outranks teardown bookkeeping: a died-thread stamp
    survives stop() so the next boot's reconcile still sees the wedge."""

    def exploding(env, **kw):
        raise RuntimeError("wall-2 breach")

    recorder = _WatchdogRecorder()
    beat = _paired_heartbeat(tmp_path, recorder)
    beat._cycle_fn = exploding  # noqa: SLF001
    beat.start()
    beat._thread.join(timeout=10.0)  # noqa: SLF001
    beat.stop()
    stamp = json.loads(
        (tmp_path / "coord" / "heartbeat-liveness.json").read_text(encoding="utf-8")
    )
    assert stamp["thread_dead"] is True  # NOT clobbered by the clean-stop marker
    assert dm.reconcile_boot_stamp(stamp) is not None


def test_factory_pairs_watchdog_with_heartbeat(tmp_path: Path) -> None:
    """No heartbeat, no watchdog — and WITH a heartbeat, the watchdog exists,
    reads the same stamp path, and alerts through the router's health surface."""
    service = SimpleNamespace(
        coordinator_heartbeat_enabled=True,
        coordinator_enabled=False,
        coordinator_projects={},
        coordinator_battery_campaign_state_path="",
        coordinator_heartbeat_interval_s=900.0,
        coordinator_heartbeat_battery_multiplier=4.0,
        coordinator_heartbeat_boot_grace_s=300.0,
        coordinator_overnight_window="23:00-09:00",
        coordinator_operator_absent=False,
        coordinator_shadow_mode=True,
        fleet_dispatch_agentic_setup_dir=str(tmp_path / "agentic"),
        fleet_dispatch_projects_dir=str(tmp_path / "projects"),
    )
    beat = hb.build_heartbeat(
        service,
        cleanup_started=lambda: False,
        data_dir=tmp_path / "data",
        dev_mode=True,
    )
    assert beat is not None
    watchdog = beat._watchdog  # noqa: SLF001
    assert isinstance(watchdog, dm.DeadManWatchdog)
    assert watchdog._stamp_path == beat._stamp_path  # noqa: SLF001 — one stamp
    assert watchdog._slack_s == dm.DEADMAN_SLACK_S  # noqa: SLF001 — registered
    # One session identity, minted per build, shared by both (MAJOR-1 fix).
    assert watchdog._session_id == beat._session_id != ""  # noqa: SLF001
    assert not watchdog.running  # built, not started — start() is the pairing
