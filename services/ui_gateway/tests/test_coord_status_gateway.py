"""Gateway-level wiring locks for /coord status (#843).

Mirrors test_dispatch_plan.py's "built-but-wired dormancy guard" shape:
proves the REAL TransportGateway constructs its CoordCoordinator wired to
real collaborators AND ships dormant (enabled=false) — dormancy is the flag
alone, never a missing seam.
"""

from __future__ import annotations

import pytest

from services.ui_gateway.src.coord_coordinator import CoordCommand
from services.ui_gateway.src.transport import TransportGateway


def test_gateway_constructs_coord_coordinator_dormant_by_default():
    gw = TransportGateway()  # coordinator_enabled defaults False
    coord = gw._coord_coordinator
    assert coord._enabled is False
    assert coord._fleet_config is not None  # the fleet config seam IS wired


@pytest.mark.asyncio
async def test_gateway_dormant_coord_fires_nothing():
    gw = TransportGateway()
    reply = await gw._coord_coordinator.handle_command("s", CoordCommand(kind="status"))
    assert "off" in reply.lower() or "dormant" in reply.lower()


@pytest.mark.asyncio
async def test_handle_coord_command_returns_none_for_non_coord_text():
    gw = TransportGateway()
    assert await gw.handle_coord_command("s1", "hello there") is None
    assert await gw.handle_coord_command("s1", "/dispatch status") is None


@pytest.mark.asyncio
async def test_handle_coord_command_intercepts_and_persists_informational_turn():
    gw = TransportGateway()  # dormant -> a clear notice, but STILL intercepted (not None)
    reply = await gw.handle_coord_command("s1", "/coord status")
    assert reply is not None
    assert "off" in reply.lower() or "dormant" in reply.lower()


def test_gateway_threads_coordinator_projects_and_campaign_path(tmp_path):
    campaign = tmp_path / "campaign.json"
    gw = TransportGateway(
        coordinator_enabled=True,
        coordinator_projects={"Coder Jobs": 7},
        coordinator_campaign_state_path=str(campaign),
    )
    coord = gw._coord_coordinator
    assert coord._enabled is True
    assert coord._coordinator_projects == {"Coder Jobs": 7}
    assert coord._campaign_state_path == campaign
