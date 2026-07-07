"""Tests — the gateway DispatchCoordinator PLAN seam (``_dispatch_plan_fn``, #670).

``_dispatch_plan_fn`` encodes a PLAN_REQUEST, sends it to the AO, and reconstructs a
``PlanResult`` from the PLAN_RESULT (or a Fail-Closed transport error). The transport call
is overridden so no AO / live IPC is needed — the AO handler is tested separately.
"""

from __future__ import annotations

from typing import Any

import pytest

from services.ui_gateway.src.transport import TransportGateway
from shared.ipc.protocol import MessageFramer


class _PlanGwHarness:
    """Minimal stand-in: _framer + an overridden _plan_transport_call returning a canned dict."""

    def __init__(self, transport_result: dict[str, Any]) -> None:
        self._framer = MessageFramer()
        self._result = transport_result
        self.sent_message: bytes | None = None

    async def _plan_transport_call(self, message: bytes) -> dict[str, Any]:
        self.sent_message = message
        return self._result

    _dispatch_plan_fn = TransportGateway._dispatch_plan_fn


@pytest.mark.asyncio
async def test_dispatch_plan_fn_reconstructs_plan_result():
    h = _PlanGwHarness({
        "ok": True, "message": "planned", "fell_back": False,
        "tasks": [{"repo": "r", "task": "t", "prompt": "p"}],
        "criteria": {
            "goal": "g",
            "criteria": [{"id": "c1", "text": "it builds", "tier": "build", "check": ""}],
        },
    })
    res = await h._dispatch_plan_fn("r", "a goal")
    assert res.ok and len(res.tasks) == 1 and res.fell_back is False
    assert res.spec.goal == "g" and res.spec.criteria[0].tier == "build"
    # the request frame carried the repo + goal
    assert h._framer.decode_plan_request(h.sent_message) == {"repo": "r", "goal": "a goal"}


@pytest.mark.asyncio
async def test_dispatch_plan_fn_fell_back_flag_passes_through():
    h = _PlanGwHarness({
        "ok": True, "message": "fell back", "fell_back": True,
        "tasks": [{"repo": "r", "task": "t", "prompt": "p"}],
        "criteria": {"goal": "g", "criteria": [{"id": "c1", "text": "it builds", "tier": "build", "check": ""}]},
    })
    res = await h._dispatch_plan_fn("r", "g")
    assert res.ok and res.fell_back is True


@pytest.mark.asyncio
async def test_dispatch_plan_fn_transport_error_fails_closed():
    h = _PlanGwHarness({
        "ok": False, "message": "Could not connect to the Assistant Orchestrator (Fail-Closed).",
        "fell_back": False, "tasks": [], "criteria": {},
    })
    res = await h._dispatch_plan_fn("r", "g")
    assert not res.ok and "Could not connect" in res.message and res.tasks == []


@pytest.mark.asyncio
async def test_dispatch_plan_fn_carries_ambiguous_build_plan_for_the_question():
    # Increment 4 IPC-transparency lock: the ambiguity signal (surface=ambiguous + candidates)
    # rides INSIDE the spec dict over the EXISTING PLAN_RESULT channel — no new IPC verb. The
    # AO sends criteria=spec.to_dict(); the gateway reconstructs via AcceptanceSpec.from_dict,
    # so build_plan (incl. candidates) survives and resolve_clarifying_question can fire on it.
    from shared.fleet import acceptance as acc
    h = _PlanGwHarness({
        "ok": True, "message": "planned", "fell_back": False,
        "tasks": [{"repo": "r", "task": "t", "prompt": "p"}],
        "criteria": {
            "goal": "an app with buttons",
            "criteria": [{"id": "c1", "text": "it builds", "tier": "build", "check": ""}],
            "build_plan": {
                "surface": "ambiguous", "language_hint": None, "complexity": "moderate",
                "components": [], "candidates": ["desktop-gui", "web", "mobile"],
            },
        },
    })
    res = await h._dispatch_plan_fn("r", "an app with buttons")
    assert res.spec.build_plan["surface"] == "ambiguous"
    assert res.spec.build_plan["candidates"] == ["desktop-gui", "web", "mobile"]
    # the coordinator's gate hook would fire the curated question on exactly this plan
    q = acc.resolve_clarifying_question(res.spec.build_plan)
    assert q is not None and q["question"] == "Where will you mainly use this?"


# ---- the EXECUTE seam (sub-part 3b) ----------------------------------------


class _ExecGwHarness:
    """Minimal stand-in: _framer + an overridden _execute_transport_call returning a dict."""

    def __init__(self, transport_result: dict[str, Any]) -> None:
        self._framer = MessageFramer()
        self._result = transport_result
        self.sent_message: bytes | None = None

    async def _execute_transport_call(self, message: bytes) -> dict[str, Any]:
        self.sent_message = message
        return self._result

    _dispatch_execute_fn = TransportGateway._dispatch_execute_fn


@pytest.mark.asyncio
async def test_dispatch_execute_fn_reconstructs_dispatch_result():
    h = _ExecGwHarness({"ok": True, "run_id": "RID1", "message": "dispatching RID1…"})
    res = await h._dispatch_execute_fn(
        "s1", "RID1", "repo", [{"repo": "r", "task": "t", "prompt": "p"}], None
    )
    assert res.ok and res.run_id == "RID1" and "dispatching" in res.message
    # the request frame carried session_id + run_id + the APPROVED tasks
    assert h._framer.decode_execute_request(h.sent_message) == {
        "session_id": "s1", "run_id": "RID1", "tasks": [{"repo": "r", "task": "t", "prompt": "p"}],
    }


@pytest.mark.asyncio
async def test_dispatch_execute_fn_transport_error_fails_closed():
    h = _ExecGwHarness({"ok": False, "run_id": "", "message": "Could not connect (Fail-Closed)."})
    res = await h._dispatch_execute_fn("s", "RID1", "repo", [], None)
    assert not res.ok and "Could not connect" in res.message
    assert res.run_id == "RID1"  # falls back to the passed run_id when the AO didn't echo one


# ---- built-but-wired dormancy guard (the full surface) --------------------


def test_gateway_wires_both_seams_and_ships_dormant():
    # The real gateway constructs its DispatchCoordinator with BOTH plan_fn AND execute_fn
    # wired (the full surface is built), AND ships dormant (enabled=false) — dormancy is the
    # flag alone, not a missing seam.
    gw = TransportGateway()  # fleet_dispatch_enabled defaults False
    coord = gw._dispatch_coordinator
    assert coord._plan_fn is not None       # PLAN seam wired
    assert coord._execute_fn is not None    # EXECUTE seam wired
    assert coord._enabled is False          # dormant by default


@pytest.mark.asyncio
async def test_gateway_dormant_fires_nothing_even_with_seams_wired():
    from services.ui_gateway.src.dispatch_coordinator import DispatchCommand

    gw = TransportGateway()
    reply = await gw._dispatch_coordinator.handle_command(
        "s", DispatchCommand(kind="run", repo="r", goal="g")
    )
    assert "off" in reply.lower() or "dormant" in reply.lower()  # disabled BEFORE either seam
