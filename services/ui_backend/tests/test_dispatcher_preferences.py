"""Dispatcher tests for the preference-memory interception (#770 M1, Loop 1).

Locks the dispatcher wiring for /remember + /preferences (the N1 integration step
of the M1 merge motion): a gateway that exposes ``handle_preferences_command`` has
its reply emitted as exactly ONE informational token frame + the terminal ``end``
frame — NO pgov frame (the text was never PGOV-validated) and NO audio/TTS frames
regardless of the speak preference (P8: no model call, no spoken output on the
write seam).  A ``None`` reply (not a preference command) keeps the unchanged
prompt arc; a gateway WITHOUT the surface (StubGateway) is unaffected by the
getattr guard.
"""

from __future__ import annotations

import asyncio
from typing import Any

from services.ui_backend.src._stub import StubGateway, StubVoiceEngine
from services.ui_backend.src.dispatcher import RpcDispatcher
from services.ui_gateway.src.session_store import SessionStore


def _run(dispatcher: RpcDispatcher, request: dict[str, Any]) -> list[dict[str, Any]]:
    frames: list[dict[str, Any]] = []

    async def send(frame: dict[str, Any]) -> None:
        frames.append(frame)

    asyncio.run(dispatcher.handle(request, send))
    return frames


class PreferenceAwareGateway(StubGateway):
    """StubGateway + the #770 preference surface, returning a scripted reply."""

    def __init__(self, info_text: str | None) -> None:
        super().__init__()
        self._info_text = info_text
        self.preference_calls: list[tuple[str, str]] = []

    async def handle_preferences_command(
        self, session_id: str, text: str
    ) -> str | None:
        self.preference_calls.append((session_id, text))
        return self._info_text


REMEMBER_REPLY = "Saved: “Always use metric units.” (say /preferences to review)."
LIST_REPLY = "Your saved preferences:\n1. Always use metric units."


class TestInformationalFrameEmission:
    def test_remember_single_token_frame_plus_end(self) -> None:
        gateway = PreferenceAwareGateway(REMEMBER_REPLY)
        dispatcher = RpcDispatcher(gateway, SessionStore(db_path=":memory:"))
        frames = _run(dispatcher, {
            "id": 7, "method": "prompt",
            "params": {"session_id": "s1", "prompt": "/remember Always use metric units"},
        })

        kinds = [f.get("stream") for f in frames]
        assert kinds == ["token", "end"]  # ONE token frame, then end — no pgov

        token = frames[0]["value"]
        assert token["token"] == REMEMBER_REPLY  # the whole reply in one frame
        assert token["token_index"] == 0
        assert token["is_final"] is True
        assert token["is_tool_call"] is False
        assert token["is_thinking"] is False
        assert frames[1]["value"]["informational"] is True
        assert gateway.preference_calls == [
            ("s1", "/remember Always use metric units")
        ]

    def test_preferences_list_routed_to_handler(self) -> None:
        gateway = PreferenceAwareGateway(LIST_REPLY)
        dispatcher = RpcDispatcher(gateway, SessionStore(db_path=":memory:"))
        frames = _run(dispatcher, {
            "id": 1, "method": "prompt",
            "params": {"session_id": "s1", "prompt": "/preferences"},
        })
        assert [f.get("stream") for f in frames] == ["token", "end"]
        assert frames[0]["value"]["token"] == LIST_REPLY
        assert gateway.preference_calls == [("s1", "/preferences")]

    def test_no_pgov_frame_for_preference_turn(self) -> None:
        gateway = PreferenceAwareGateway(REMEMBER_REPLY)
        dispatcher = RpcDispatcher(gateway, SessionStore(db_path=":memory:"))
        frames = _run(dispatcher, {
            "id": 2, "method": "prompt",
            "params": {"session_id": "s1", "prompt": "/remember call me Blair"},
        })
        assert all(f.get("stream") != "pgov" for f in frames)

    def test_no_audio_frames_even_with_speak_true(self) -> None:
        """Preference turns are never spoken — speak=True is ignored (P8: no model call)."""
        gateway = PreferenceAwareGateway(REMEMBER_REPLY)
        dispatcher = RpcDispatcher(
            gateway, SessionStore(db_path=":memory:"), voice=StubVoiceEngine()
        )
        frames = _run(dispatcher, {
            "id": 3, "method": "prompt",
            "params": {
                "session_id": "s1",
                "prompt": "/remember Always use metric units",
                "speak": True,
            },
        })
        kinds = [f.get("stream") for f in frames]
        assert "audio" not in kinds
        assert kinds == ["token", "end"]


class TestPassthroughWhenNotAPreferenceCommand:
    def test_none_reply_keeps_normal_prompt_arc(self) -> None:
        """A non-preference prompt (handler returns None) proceeds to the normal arc."""
        gateway = PreferenceAwareGateway(None)  # handler returns None → not intercepted
        store = SessionStore(db_path=":memory:")
        sid = store.create_session()
        dispatcher = RpcDispatcher(gateway, store)
        frames = _run(dispatcher, {
            "id": 4, "method": "prompt",
            "params": {"session_id": sid, "prompt": "what is the capital of France?"},
        })
        # The stub's normal prompt arc ends ["pgov", "end"] — the interception did
        # NOT swallow the turn (informational turns end ["token", "end"], no pgov).
        kinds = [f.get("stream") for f in frames]
        assert kinds[-2:] == ["pgov", "end"]
        # The handler was still consulted (getattr present), then declined.
        assert gateway.preference_calls == [
            (sid, "what is the capital of France?")
        ]

    def test_stub_gateway_without_surface_is_unaffected(self) -> None:
        """A gateway lacking handle_preferences_command keeps the unchanged arc."""
        gateway = StubGateway()  # no preference handler at all
        store = SessionStore(db_path=":memory:")
        sid = store.create_session()
        dispatcher = RpcDispatcher(gateway, store)
        frames = _run(dispatcher, {
            "id": 5, "method": "prompt",
            "params": {"session_id": sid, "prompt": "/remember something"},
        })
        # getattr guard → interception skipped → normal prompt arc ends ["pgov", "end"].
        assert [f.get("stream") for f in frames][-2:] == ["pgov", "end"]
