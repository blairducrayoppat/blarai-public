"""Dispatcher tests for the #712 UI follow-up action attachment.

Locks the frame contract: a SUCCESSFUL image reply carries
``ui_actions="image"`` + the image id (so the WinUI shows Edit/Save buttons),
and a dispatch PLAN-preview reply carries ``ui_actions="dispatch_plan"`` (so it
shows Approve/Reject). getattr-guarded + pop-on-read: a refusal / status / a
gateway without the signal surface emits a plain frame with no actions. Mirrors
the ingest editable-preview attachment contract (test_dispatcher_ingest.py).
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


# A well-formed 32-hex generated-image id.
_IMG_ID = "0123456789abcdef0123456789abcdef"


class ImagineGateway(StubGateway):
    """StubGateway + the imagine surface + the one-shot image-action signal."""

    def __init__(self, reply: str, meta: dict[str, str] | None) -> None:
        super().__init__()
        self._reply = reply
        self._meta = meta
        self.meta_calls: list[str] = []

    async def handle_imagine_command(self, session_id: str, text: str) -> str | None:
        return self._reply

    def image_action_meta(self, session_id: str) -> dict[str, str] | None:
        self.meta_calls.append(session_id)
        return self._meta


class DispatchGateway(StubGateway):
    """StubGateway + the dispatch surface + the one-shot plan-action signal."""

    def __init__(self, reply: str, kind: str) -> None:
        super().__init__()
        self._reply = reply
        self._kind = kind
        self.kind_calls: list[str] = []

    async def handle_dispatch_command(self, session_id: str, text: str) -> str | None:
        return self._reply

    def dispatch_action_kind(self, session_id: str) -> str:
        self.kind_calls.append(session_id)
        return self._kind


def test_image_reply_carries_edit_save_actions() -> None:
    gw = ImagineGateway(
        f"![generated image](blarai-img://{_IMG_ID})\n\ndone", {"image_id": _IMG_ID}
    )
    d = RpcDispatcher(gw, SessionStore(db_path=":memory:"))
    frames = _run(d, {"id": 1, "method": "prompt",
                      "params": {"session_id": "s1", "prompt": "/imagine a cat"}})
    kinds = [f.get("stream") for f in frames]
    assert kinds == ["token", "end"]
    token = frames[0]["value"]
    assert token["ui_actions"] == "image"
    assert token["ui_action_id"] == _IMG_ID
    assert gw.meta_calls == ["s1"]


def test_image_reply_without_meta_has_no_actions() -> None:
    gw = ImagineGateway("Image generation is unavailable.", None)  # a refusal
    d = RpcDispatcher(gw, SessionStore(db_path=":memory:"))
    frames = _run(d, {"id": 1, "method": "prompt",
                      "params": {"session_id": "s1", "prompt": "/imagine a cat"}})
    token = frames[0]["value"]
    assert "ui_actions" not in token
    assert "ui_action_id" not in token


def test_dispatch_plan_reply_carries_approve_reject_actions() -> None:
    gw = DispatchGateway("Here are the criteria...", "dispatch_plan")
    d = RpcDispatcher(gw, SessionStore(db_path=":memory:"))
    frames = _run(d, {"id": 1, "method": "prompt",
                      "params": {"session_id": "s1", "prompt": "/dispatch calc | a calc"}})
    kinds = [f.get("stream") for f in frames]
    assert kinds == ["token", "end"]
    token = frames[0]["value"]
    assert token["ui_actions"] == "dispatch_plan"
    assert gw.kind_calls == ["s1"]


def test_dispatch_non_plan_reply_has_no_actions() -> None:
    gw = DispatchGateway("Nothing to approve.", "")  # e.g. a status / reject reply
    d = RpcDispatcher(gw, SessionStore(db_path=":memory:"))
    frames = _run(d, {"id": 1, "method": "prompt",
                      "params": {"session_id": "s1", "prompt": "/dispatch status"}})
    token = frames[0]["value"]
    assert "ui_actions" not in token


def test_gateway_without_action_surface_is_unaffected() -> None:
    """A gateway with handle_imagine_command but NO image_action_meta — the
    getattr guard holds, the frame carries no actions."""

    class Bare(StubGateway):
        async def handle_imagine_command(self, session_id: str, text: str) -> str | None:
            return "done"

    d = RpcDispatcher(Bare(), SessionStore(db_path=":memory:"))
    frames = _run(d, {"id": 1, "method": "prompt",
                      "params": {"session_id": "s1", "prompt": "/imagine a cat"}})
    token = frames[0]["value"]
    assert token["token"] == "done"
    assert "ui_actions" not in token
