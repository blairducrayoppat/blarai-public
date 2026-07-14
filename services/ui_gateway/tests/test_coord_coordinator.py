"""Locks for the gateway-side /coord status coordinator (#843).

Dormancy-first (mirrors test_dispatch_plan.py's shape), command parsing,
and the fail-closed exception path. No live Vikunja: FakeVikunja (borrowed
from shared/tests/test_vikunja_bridge.py) stands in for the transport.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest

from services.ui_gateway.src.coord_coordinator import (
    CoordCoordinator,
    parse_coord_command,
)
from shared.fleet.dispatch import FleetDispatchConfig
from shared.tests.test_vikunja_bridge import FakeVikunja

_NOW = datetime(2026, 7, 12, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _loopback_env(monkeypatch):
    monkeypatch.setenv("VIKUNJA_URL", "http://localhost:3456")
    monkeypatch.setenv("VIKUNJA_USER", "blarai")
    monkeypatch.setenv("VIKUNJA_PASS", "test-pass")


def _config(tmp_path) -> FleetDispatchConfig:
    return FleetDispatchConfig(
        scripts_dir=tmp_path / "scripts",
        queue_path=tmp_path / "state" / "fleet-queue.json",
        runs_dir=tmp_path / "state" / "fleet-runs",
        projects_dir=tmp_path / "projects",
    )


# ---------------------------------------------------------------------------
# parse_coord_command
# ---------------------------------------------------------------------------


def test_parse_ignores_non_coord_text():
    assert parse_coord_command("hello there") is None
    assert parse_coord_command("/dispatch status") is None


def test_parse_bare_coord_defaults_to_status():
    assert parse_coord_command("/coord").kind == "status"
    assert parse_coord_command("/coord ").kind == "status"


def test_parse_status_case_insensitive():
    assert parse_coord_command("/coord status").kind == "status"
    assert parse_coord_command("/COORD STATUS").kind == "status"
    assert parse_coord_command("/Coord Status").kind == "status"


def test_parse_unknown_subcommand():
    cmd = parse_coord_command("/coord approve 42")
    assert cmd.kind == "unknown"
    assert cmd.raw == "approve 42"


# ---------------------------------------------------------------------------
# Dormancy — enabled=False must touch NOTHING
# ---------------------------------------------------------------------------


def test_dormant_by_default_makes_zero_vikunja_calls(tmp_path):
    fake = FakeVikunja()
    coord = CoordCoordinator(
        enabled=False,
        fleet_config=_config(tmp_path),
        coordinator_projects={"Coder Jobs": 7},
        vikunja_transport=fake,
        clock=lambda: _NOW,
    )
    reply = asyncio.run(coord.handle_command("s1", parse_coord_command("/coord status")))
    assert "off" in reply.lower()
    assert fake.calls == []  # the gate fires BEFORE any collaborator is touched


def test_dormant_reply_names_the_config_flag(tmp_path):
    coord = CoordCoordinator(enabled=False, fleet_config=_config(tmp_path))
    reply = asyncio.run(coord.handle_command("s1", parse_coord_command("/coord")))
    assert "[coordinator].enabled" in reply


# ---------------------------------------------------------------------------
# Enabled — a real (fixture) status report comes back
# ---------------------------------------------------------------------------


def test_enabled_status_returns_a_report(tmp_path):
    fake = FakeVikunja()
    fake.seed_task(7, title="a task", done=False, created="2026-07-10T12:00:00Z")
    coord = CoordCoordinator(
        enabled=True,
        fleet_config=_config(tmp_path),
        coordinator_projects={"Coder Jobs": 7},
        vikunja_transport=fake,
        clock=lambda: _NOW,
    )
    reply = asyncio.run(coord.handle_command("s1", parse_coord_command("/coord status")))
    assert "Coordinator status as of" in reply
    assert "Coder Jobs" in reply
    assert "Fleet swap: idle" in reply


def test_enabled_empty_projects_still_returns_cleanly(tmp_path):
    # vikunja_transport is still a FakeVikunja (offline-only tests, per the C1
    # build brief) even though this test has zero configured projects —
    # compose_work_state still probes Vikunja's own liveness unconditionally
    # (the substrate-liveness leg), so a real transport would otherwise reach
    # out to whatever is actually on :3456.
    coord = CoordCoordinator(
        enabled=True, fleet_config=_config(tmp_path), clock=lambda: _NOW,
        vikunja_transport=FakeVikunja(),
    )
    reply = asyncio.run(coord.handle_command("s1", parse_coord_command("/coord status")))
    assert "No coordinator projects configured" in reply


def test_enabled_vikunja_down_surfaces_unreachable(tmp_path):
    fake = FakeVikunja(fail=True)
    coord = CoordCoordinator(
        enabled=True,
        fleet_config=_config(tmp_path),
        coordinator_projects={"Coder Jobs": 7},
        vikunja_transport=fake,
        clock=lambda: _NOW,
    )
    reply = asyncio.run(coord.handle_command("s1", parse_coord_command("/coord status")))
    assert "UNREACHABLE" in reply


def test_unknown_subcommand_when_enabled_returns_honest_notice(tmp_path):
    coord = CoordCoordinator(enabled=True, fleet_config=_config(tmp_path), clock=lambda: _NOW)
    reply = asyncio.run(coord.handle_command("s1", parse_coord_command("/coord approve 1")))
    assert "isn't available yet" in reply
    assert "approve 1" in reply


# ---------------------------------------------------------------------------
# Fail-closed on an internal exception — never raises out of handle_command
# ---------------------------------------------------------------------------


def test_internal_exception_is_fail_closed_never_raised(tmp_path, monkeypatch):
    coord = CoordCoordinator(enabled=True, fleet_config=_config(tmp_path), clock=lambda: _NOW)

    def _boom(*_a, **_kw):
        raise RuntimeError("simulated internal failure")

    monkeypatch.setattr(
        "services.ui_gateway.src.coord_coordinator.ws.compose_work_state", _boom
    )
    reply = asyncio.run(coord.handle_command("s1", parse_coord_command("/coord status")))
    assert "Fail-Closed" in reply
    assert "simulated internal failure" in reply
