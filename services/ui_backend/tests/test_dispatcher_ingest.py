"""Dispatcher tests for the ingest/informational interception (#655 Stage B).

Locks the frame contract: an intercepted turn emits exactly ONE token frame
(the full informational text — no per-token streaming) plus the terminal
``end`` frame; NO pgov frame (the text was never PGOV-validated) and NO
audio/TTS frames regardless of the user's speak preference.  A gateway
without the ingest surface (stubs/fakes) keeps the unchanged prompt arc.
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


class IngestAwareGateway(StubGateway):
    """StubGateway + the #655 ingest surface, returning a scripted reply."""

    def __init__(self, info_text: str | None) -> None:
        super().__init__()
        self._info_text = info_text
        self.ingest_calls: list[tuple[str, str]] = []

    async def handle_ingest_command(self, session_id: str, text: str) -> str | None:
        self.ingest_calls.append((session_id, text))
        return self._info_text


INFO_TEXT = "**Ingest preview** — cleaned article body here.\n\nReply /approve or /reject."


class TestInformationalFrameEmission:
    def test_single_token_frame_plus_end(self) -> None:
        gateway = IngestAwareGateway(INFO_TEXT)
        dispatcher = RpcDispatcher(gateway, SessionStore(db_path=":memory:"))
        frames = _run(dispatcher, {
            "id": 7, "method": "prompt",
            "params": {"session_id": "s1", "prompt": "/ingest pasted text"},
        })

        kinds = [f.get("stream") for f in frames]
        assert kinds == ["token", "end"]  # ONE token frame, then end — no pgov

        token = frames[0]["value"]
        assert token["token"] == INFO_TEXT  # the whole text in one frame
        assert token["token_index"] == 0
        assert token["is_final"] is True
        assert token["is_tool_call"] is False
        assert token["is_thinking"] is False
        assert frames[1]["value"]["informational"] is True
        assert gateway.ingest_calls == [("s1", "/ingest pasted text")]

    def test_no_pgov_frame_for_informational_turn(self) -> None:
        gateway = IngestAwareGateway(INFO_TEXT)
        dispatcher = RpcDispatcher(gateway, SessionStore(db_path=":memory:"))
        frames = _run(dispatcher, {
            "id": 1, "method": "prompt",
            "params": {"session_id": "s1", "prompt": "/approve"},
        })
        assert all(f.get("stream") != "pgov" for f in frames)

    def test_no_audio_frames_even_with_speak_true(self) -> None:
        """Informational turns are never spoken — speak=True is ignored."""
        gateway = IngestAwareGateway(INFO_TEXT)
        dispatcher = RpcDispatcher(
            gateway, SessionStore(db_path=":memory:"), voice=StubVoiceEngine()
        )
        frames = _run(dispatcher, {
            "id": 2, "method": "prompt",
            "params": {
                "session_id": "s1",
                "prompt": "/ingest pasted text",
                "speak": True,
            },
        })
        kinds = [f.get("stream") for f in frames]
        assert kinds == ["token", "end"]
        assert all(f.get("stream") not in ("audio", "audio_cancel") for f in frames)

    def test_dispatcher_does_not_persist_for_informational_turn(self) -> None:
        """Persistence is the GATEWAY's job for intercepted turns — the
        dispatcher must not add a duplicate assistant row."""
        store = SessionStore(db_path=":memory:")
        sid = store.create_session("t")
        gateway = IngestAwareGateway(INFO_TEXT)
        dispatcher = RpcDispatcher(gateway, store)
        _run(dispatcher, {
            "id": 3, "method": "prompt",
            "params": {"session_id": sid, "prompt": "/ingest pasted"},
        })
        # The fake gateway does not persist; the dispatcher must not either.
        assert store.get_session_turns(sid) == []


class TestIngestFailsafe:
    def test_stalled_ingest_handler_hits_failsafe(self) -> None:
        """A stalled ingest IPC call is bounded by the prompt failsafe — the
        front end still gets a terminal end frame within the deadline."""

        class StalledGateway(StubGateway):
            async def handle_ingest_command(
                self, session_id: str, text: str
            ) -> str | None:
                await asyncio.sleep(30)  # never finishes within the bound
                return "unreachable"

        dispatcher = RpcDispatcher(
            StalledGateway(),
            SessionStore(db_path=":memory:"),
            prompt_stream_failsafe_s=0.05,
        )
        frames = _run(dispatcher, {
            "id": 6, "method": "prompt",
            "params": {"session_id": "s1", "prompt": "/approve"},
        })
        kinds = [f.get("stream") for f in frames]
        assert kinds == ["token", "end"]
        assert "timed out" in frames[0]["value"]["token"]
        assert frames[1]["value"]["failsafe"] is True


class TestNormalPromptPassthrough:
    def test_none_reply_runs_the_unchanged_prompt_arc(self) -> None:
        gateway = IngestAwareGateway(None)  # handler present, declines
        store = SessionStore(db_path=":memory:")
        sid = store.create_session("t")
        dispatcher = RpcDispatcher(gateway, store)
        frames = _run(dispatcher, {
            "id": 4, "method": "prompt",
            "params": {"session_id": sid, "prompt": "hello there"},
        })
        kinds = [f.get("stream") for f in frames]
        assert "pgov" in kinds  # the full model arc ran
        assert kinds[-1] == "end"
        assert kinds.count("token") > 1  # streamed token-by-token
        assert gateway.ingest_calls == [(sid, "hello there")]

    def test_gateway_without_ingest_surface_is_unaffected(self) -> None:
        """StubGateway has no handle_ingest_command — getattr guard holds."""
        store = SessionStore(db_path=":memory:")
        sid = store.create_session("t")
        dispatcher = RpcDispatcher(StubGateway(), store)
        frames = _run(dispatcher, {
            "id": 5, "method": "prompt",
            "params": {"session_id": sid, "prompt": "/ingest pasted text"},
        })
        kinds = [f.get("stream") for f in frames]
        assert "pgov" in kinds  # treated as a normal prompt
        assert kinds[-1] == "end"


# ---------------------------------------------------------------------------
# Editable-preview attachment + the ingest_decide RPC (#663 Workstream A)
# ---------------------------------------------------------------------------


class PreviewAwareGateway(IngestAwareGateway):
    """Ingest gateway that also exposes the one-shot editable-preview signal."""

    def __init__(self, info_text: str | None, meta: dict[str, str] | None) -> None:
        super().__init__(info_text)
        self._meta = meta
        self.preview_meta_calls: list[str] = []

    def ingest_preview_meta(self, session_id: str) -> dict[str, str] | None:
        self.preview_meta_calls.append(session_id)
        return self._meta


class DecideAwareGateway(StubGateway):
    """StubGateway + the #663 structured approve|reject decision channel."""

    def __init__(self, reply: str, decided: bool = True) -> None:
        super().__init__()
        self._reply = reply
        self._decided = decided
        self.decide_calls: list[tuple[str, str, str]] = []

    async def handle_ingest_decision(
        self, session_id: str, decision: str, edited_body: str = ""
    ) -> tuple[str, bool]:
        self.decide_calls.append((session_id, decision, edited_body))
        return self._reply, self._decided


class TestEditablePreviewAttachment:
    def test_preview_frame_carries_editable_body(self) -> None:
        meta = {
            "doc_uuid": "d-77", "source_type": "paste",
            "editable_body": "the cleaned body to edit",
        }
        gateway = PreviewAwareGateway(INFO_TEXT, meta)
        dispatcher = RpcDispatcher(gateway, SessionStore(db_path=":memory:"))
        frames = _run(dispatcher, {
            "id": 8, "method": "prompt",
            "params": {"session_id": "s1", "prompt": "/ingest pasted text"},
        })
        token = frames[0]["value"]
        assert token["token"] == INFO_TEXT  # the rendered preview is unchanged
        assert token["ingest_preview"] is True
        assert token["ingest_doc_uuid"] == "d-77"
        assert token["ingest_source_type"] == "paste"
        assert token["ingest_editable_body"] == "the cleaned body to edit"
        assert gateway.preview_meta_calls == ["s1"]

    def test_no_meta_means_no_attachment(self) -> None:
        gateway = PreviewAwareGateway(INFO_TEXT, None)  # not a new preview turn
        dispatcher = RpcDispatcher(gateway, SessionStore(db_path=":memory:"))
        frames = _run(dispatcher, {
            "id": 8, "method": "prompt",
            "params": {"session_id": "s1", "prompt": "/approve"},
        })
        token = frames[0]["value"]
        assert "ingest_preview" not in token
        assert "ingest_editable_body" not in token

    def test_gateway_without_preview_surface_is_unaffected(self) -> None:
        """IngestAwareGateway has handle_ingest_command but NO
        ingest_preview_meta — the getattr guard holds, no attachment."""
        gateway = IngestAwareGateway(INFO_TEXT)
        dispatcher = RpcDispatcher(gateway, SessionStore(db_path=":memory:"))
        frames = _run(dispatcher, {
            "id": 8, "method": "prompt",
            "params": {"session_id": "s1", "prompt": "/ingest pasted text"},
        })
        token = frames[0]["value"]
        assert token["token"] == INFO_TEXT
        assert "ingest_preview" not in token


class TestIngestDecideMethod:
    def test_approve_routes_and_reports_decided(self) -> None:
        gateway = DecideAwareGateway(
            "Approved — stored. (Your curated edit was stored — not the cleaner's "
            "original.)", decided=True,
        )
        dispatcher = RpcDispatcher(gateway, SessionStore(db_path=":memory:"))
        frames = _run(dispatcher, {
            "id": 9, "method": "ingest_decide",
            "params": {"session_id": "s1", "decision": "approve",
                       "edited_body": "trimmed curated body"},
        })
        kinds = [f.get("stream") for f in frames]
        assert kinds == ["token", "end"]  # one token + terminal end, no pgov
        assert frames[0]["value"]["token"].startswith("Approved")
        assert frames[0]["value"]["is_final"] is True
        assert frames[1]["value"]["informational"] is True
        assert frames[1]["value"]["ingest_decided"] is True
        assert gateway.decide_calls == [("s1", "approve", "trimmed curated body")]

    def test_reject_routes(self) -> None:
        gateway = DecideAwareGateway("Rejected — discarded.", decided=True)
        dispatcher = RpcDispatcher(gateway, SessionStore(db_path=":memory:"))
        frames = _run(dispatcher, {
            "id": 9, "method": "ingest_decide",
            "params": {"session_id": "s1", "decision": "reject"},
        })
        assert frames[0]["value"]["token"].startswith("Rejected")
        assert frames[1]["value"]["ingest_decided"] is True
        assert gateway.decide_calls == [("s1", "reject", "")]

    def test_still_pending_reports_decided_false(self) -> None:
        """A transient failure → decided=False so the WinUI keeps the buttons."""
        gateway = DecideAwareGateway(
            "Ingest approve failed (the document is still pending)", decided=False,
        )
        dispatcher = RpcDispatcher(gateway, SessionStore(db_path=":memory:"))
        frames = _run(dispatcher, {
            "id": 9, "method": "ingest_decide",
            "params": {"session_id": "s1", "decision": "approve", "edited_body": "x"},
        })
        assert frames[1]["value"]["ingest_decided"] is False

    def test_missing_edited_body_defaults_empty(self) -> None:
        gateway = DecideAwareGateway("Approved")
        dispatcher = RpcDispatcher(gateway, SessionStore(db_path=":memory:"))
        _run(dispatcher, {
            "id": 10, "method": "ingest_decide",
            "params": {"session_id": "s1", "decision": "approve"},
        })
        assert gateway.decide_calls == [("s1", "approve", "")]

    def test_stub_gateway_returns_error_frame(self) -> None:
        """StubGateway has no handle_ingest_decision — clean unsupported error."""
        dispatcher = RpcDispatcher(StubGateway(), SessionStore(db_path=":memory:"))
        frames = _run(dispatcher, {
            "id": 11, "method": "ingest_decide",
            "params": {"session_id": "s1", "decision": "approve", "edited_body": "x"},
        })
        assert len(frames) == 1
        assert frames[0]["ok"] is False
        assert frames[0]["error"]["code"] == "unsupported"
        assert frames[0].get("stream") is None

    def test_stalled_decide_hits_failsafe(self) -> None:
        class StalledDecide(StubGateway):
            async def handle_ingest_decision(
                self, session_id: str, decision: str, edited_body: str = ""
            ) -> tuple[str, bool]:
                await asyncio.sleep(30)
                return "unreachable", True

        dispatcher = RpcDispatcher(
            StalledDecide(),
            SessionStore(db_path=":memory:"),
            prompt_stream_failsafe_s=0.05,
        )
        frames = _run(dispatcher, {
            "id": 12, "method": "ingest_decide",
            "params": {"session_id": "s1", "decision": "approve", "edited_body": "x"},
        })
        kinds = [f.get("stream") for f in frames]
        assert kinds == ["token", "end"]
        assert "timed out" in frames[0]["value"]["token"]
        assert frames[1]["value"]["failsafe"] is True
        assert frames[1]["value"]["ingest_decided"] is False
