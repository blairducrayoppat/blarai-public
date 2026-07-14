"""Dispatcher-level interception lock for /coord status (#843).

Mirrors test_dispatcher_ui_actions.py's DispatchGateway pattern: proves
_m_prompt reaches handle_coord_command via the getattr guard, emits ONE
informational token + terminal end frame, and — the regression lock for a
gateway that does NOT carry the coordinator surface (a StubGateway, or any
older/other gateway shape) — falls straight through untouched (no
AttributeError, no behavior change) exactly like every other pre-existing
interceptor.
"""

from __future__ import annotations

import asyncio
from typing import Any

from services.ui_backend.src._stub import StubGateway
from services.ui_backend.src.dispatcher import RpcDispatcher
from services.ui_gateway.src.session_store import SessionStore


def _run(dispatcher: RpcDispatcher, request: dict[str, Any]) -> list[dict[str, Any]]:
    frames: list[dict[str, Any]] = []

    async def send(frame: dict[str, Any]) -> None:
        frames.append(frame)

    asyncio.run(dispatcher.handle(request, send))
    return frames


class CoordGateway(StubGateway):
    """StubGateway + the coordinator status surface."""

    def __init__(self, reply: "str | None") -> None:
        super().__init__()
        self._reply = reply
        self.calls: list[tuple[str, str]] = []

    async def handle_coord_command(self, session_id: str, text: str) -> "str | None":
        self.calls.append((session_id, text))
        return self._reply


def test_coord_status_reply_emits_one_informational_frame_pair():
    gw = CoordGateway("Coordinator status as of ...\n\nFleet swap: idle (14B resident)\n")
    d = RpcDispatcher(gw, SessionStore(db_path=":memory:"))
    frames = _run(d, {"id": 1, "method": "prompt",
                      "params": {"session_id": "s1", "prompt": "/coord status"}})
    kinds = [f.get("stream") for f in frames]
    assert kinds == ["token", "end"]
    token = frames[0]["value"]
    assert "Fleet swap: idle" in token["token"]
    assert token["is_final"] is True
    assert frames[1]["value"]["informational"] is True
    assert gw.calls == [("s1", "/coord status")]


def test_coord_none_reply_falls_through_to_normal_prompt_path():
    """handle_coord_command returning None (not a /coord command) must NOT
    short-circuit — the normal send_prompt path proceeds untouched, exactly
    like every other interceptor's None-return contract."""
    gw = CoordGateway(None)
    d = RpcDispatcher(gw, SessionStore(db_path=":memory:"))
    frames = _run(d, {"id": 1, "method": "prompt",
                      "params": {"session_id": "s1", "prompt": "hello there"}})
    # StubGateway's normal send_prompt/stream_tokens path still ran (no crash,
    # no informational short-circuit stealing the turn).
    assert gw.calls == [("s1", "hello there")]
    assert frames  # the stub's own stream still produced frames normally


def test_stub_gateway_without_coord_surface_is_untouched():
    """A gateway WITHOUT handle_coord_command (e.g. a stub, or a future
    alternate gateway shape) must behave exactly as before this change —
    the getattr guard skips coordinator interception silently, no
    AttributeError."""
    gw = StubGateway()
    d = RpcDispatcher(gw, SessionStore(db_path=":memory:"))
    frames = _run(d, {"id": 1, "method": "prompt",
                      "params": {"session_id": "s1", "prompt": "/coord status"}})
    assert frames  # ran to completion via the normal path, no crash
