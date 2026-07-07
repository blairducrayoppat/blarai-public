"""Tests for the UI backend RPC dispatcher (routing + streaming + persistence)."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from services.ui_backend.src._stub import StubGateway
from services.ui_backend.src.dispatcher import RpcDispatcher
from services.ui_gateway.src.session_store import SessionStore


def _run(dispatcher: RpcDispatcher, request: dict[str, Any]) -> list[dict[str, Any]]:
    """Drive one request and return the frames the dispatcher emitted."""
    frames: list[dict[str, Any]] = []

    async def send(frame: dict[str, Any]) -> None:
        frames.append(frame)

    asyncio.run(dispatcher.handle(request, send))
    return frames


@pytest.fixture()
def store() -> SessionStore:
    return SessionStore(db_path=":memory:")


@pytest.fixture()
def dispatcher(store: SessionStore) -> RpcDispatcher:
    return RpcDispatcher(StubGateway(), store)


# ── Routing / errors ──────────────────────────────────────────────────


def test_unknown_method_errors(dispatcher: RpcDispatcher) -> None:
    frames = _run(dispatcher, {"id": 1, "method": "nope", "params": {}})
    assert frames == [
        {"id": 1, "ok": False, "error": {"code": "unknown_method", "message": "Unknown method: 'nope'"}}
    ]


def test_bad_params_errors(dispatcher: RpcDispatcher) -> None:
    frames = _run(dispatcher, {"id": 1, "method": "list_sessions", "params": []})
    assert frames[0]["ok"] is False
    assert frames[0]["error"]["code"] == "bad_params"


def test_missing_param_errors(dispatcher: RpcDispatcher) -> None:
    frames = _run(dispatcher, {"id": 1, "method": "get_turns", "params": {}})
    assert frames[0]["ok"] is False
    assert frames[0]["error"]["code"] == "missing_param"


# ── Session methods ────────────────────────────────────────────────────


def test_create_then_list_sessions(dispatcher: RpcDispatcher) -> None:
    created = _run(dispatcher, {"id": 1, "method": "create_session", "params": {"title": "Hi"}})
    assert created[0]["ok"] is True
    sid = created[0]["result"]["session_id"]

    listed = _run(dispatcher, {"id": 2, "method": "list_sessions", "params": {}})
    assert listed[0]["ok"] is True
    rows = listed[0]["result"]
    assert any(r["id"] == sid and r["title"] == "Hi" and r["is_active"] for r in rows)


def test_rename_session(dispatcher: RpcDispatcher, store: SessionStore) -> None:
    sid = store.create_session(title="old")
    frames = _run(
        dispatcher,
        {"id": 1, "method": "rename_session", "params": {"session_id": sid, "title": "new"}},
    )
    assert frames[0]["result"]["updated"] is True
    assert store.list_sessions()[0].title == "new"


def test_delete_session(dispatcher: RpcDispatcher, store: SessionStore) -> None:
    sid = store.create_session()
    frames = _run(
        dispatcher, {"id": 1, "method": "delete_session", "params": {"session_id": sid}}
    )
    assert frames[0]["result"]["deleted"] is True
    assert store.list_sessions() == []


def test_get_turns_after_prompt(dispatcher: RpcDispatcher, store: SessionStore) -> None:
    sid = store.create_session()
    _run(dispatcher, {"id": 1, "method": "prompt", "params": {"session_id": sid, "prompt": "hello"}})
    frames = _run(dispatcher, {"id": 2, "method": "get_turns", "params": {"session_id": sid}})
    roles = [t["role"] for t in frames[0]["result"]]
    assert "assistant" in roles  # assistant turn persisted by the dispatcher


# ── Document methods ───────────────────────────────────────────────────


def test_load_document_routes(dispatcher: RpcDispatcher) -> None:
    frames = _run(
        dispatcher,
        {"id": 1, "method": "load_document", "params": {"session_id": "s", "filename": "n.txt"}},
    )
    assert frames[0]["ok"] is True
    assert frames[0]["result"]["filename"] == "n.txt"
    assert frames[0]["result"]["media_type"] == "text"


def test_unload_and_trust_route(dispatcher: RpcDispatcher) -> None:
    u = _run(dispatcher, {"id": 1, "method": "unload_documents", "params": {"session_id": "s"}})
    assert u[0]["result"]["unloaded"] is True
    t = _run(dispatcher, {"id": 2, "method": "trust_documents_for_tools", "params": {"session_id": "s"}})
    assert t[0]["result"]["trusted"] is True


def test_list_userdata_files_routes(dispatcher: RpcDispatcher) -> None:
    frames = _run(dispatcher, {"id": 1, "method": "list_userdata_files", "params": {}})
    assert frames[0] == {"id": 1, "ok": True, "result": []}


# ── Off-the-event-loop (freeze fix, #561) ──────────────────────────────
#
# server.py runs one run_until_complete loop per connection, so a blocking
# document load on the loop thread freezes voice + chat behind it (the
# observed ~5-min queue). These tests assert the blocking work runs on a
# worker thread, never the loop thread.


def test_load_document_runs_off_event_loop() -> None:
    import threading

    idents: dict[str, int] = {}

    class _ThreadSpyGateway(StubGateway):
        def load_document(self, session_id: str, filename: str) -> dict[str, object]:
            idents["worker"] = threading.get_ident()
            return super().load_document(session_id, filename)

    d = RpcDispatcher(_ThreadSpyGateway(), None)
    frames: list[dict[str, Any]] = []

    async def drive() -> None:
        idents["loop"] = threading.get_ident()

        async def send(frame: dict[str, Any]) -> None:
            frames.append(frame)

        await d.handle(
            {"id": 1, "method": "load_document",
             "params": {"session_id": "s", "filename": "n.txt"}},
            send,
        )

    asyncio.run(drive())
    assert frames[0]["ok"] is True
    assert idents["worker"] != idents["loop"]  # ran off the loop thread


def test_store_attachment_runs_off_event_loop(monkeypatch: pytest.MonkeyPatch) -> None:
    import threading

    from services.ui_gateway.src import document_loader

    idents: dict[str, int] = {}

    def _spy_store_attachment(src_path: str) -> dict[str, object]:
        idents["copy_worker"] = threading.get_ident()
        return {"filename": "pic.png", "content": "", "media_type": "image", "message": ""}

    monkeypatch.setattr(document_loader, "store_attachment", _spy_store_attachment)

    class _ThreadSpyGateway(StubGateway):
        def load_document(self, session_id: str, filename: str) -> dict[str, object]:
            idents["reload_worker"] = threading.get_ident()
            return super().load_document(session_id, filename)

    d = RpcDispatcher(_ThreadSpyGateway(), None)
    frames: list[dict[str, Any]] = []

    async def drive() -> None:
        idents["loop"] = threading.get_ident()

        async def send(frame: dict[str, Any]) -> None:
            frames.append(frame)

        await d.handle(
            {"id": 1, "method": "store_attachment",
             "params": {"session_id": "s", "src_path": "C:/somewhere/pic.png"}},
            send,
        )

    asyncio.run(drive())
    assert frames[0]["ok"] is True
    # Both the copy and the staged re-load ran off the loop thread.
    assert idents["copy_worker"] != idents["loop"]
    assert idents["reload_worker"] != idents["loop"]


# ── Streaming prompt ───────────────────────────────────────────────────


def test_prompt_streams_token_pgov_end(dispatcher: RpcDispatcher, store: SessionStore) -> None:
    sid = store.create_session()
    frames = _run(
        dispatcher,
        {"id": 9, "method": "prompt", "params": {"session_id": sid, "prompt": "two words"}},
    )
    kinds = [f.get("stream") for f in frames]
    assert "token" in kinds
    # exactly one pgov then end, in that order, as the last two frames
    assert kinds[-2:] == ["pgov", "end"]
    assert all(f["id"] == 9 for f in frames)
    # the reconstructed reply echoes the prompt (stub behavior)
    text = "".join(f["value"]["token"] for f in frames if f.get("stream") == "token")
    assert "two words" in text


def test_prompt_persists_approved_assistant_turn(
    dispatcher: RpcDispatcher, store: SessionStore
) -> None:
    sid = store.create_session()
    _run(dispatcher, {"id": 1, "method": "prompt", "params": {"session_id": sid, "prompt": "hi"}})
    turns = store.get_session_turns(sid)
    assistant = [t for t in turns if t.role == "assistant"]
    assert len(assistant) == 1
    assert assistant[0].pgov_status == "approved"


def test_no_store_dispatcher_tolerates_session_calls() -> None:
    d = RpcDispatcher(StubGateway(), None)
    frames = _run(d, {"id": 1, "method": "list_sessions", "params": {}})
    assert frames[0] == {"id": 1, "ok": True, "result": []}
    frames = _run(d, {"id": 2, "method": "create_session", "params": {}})
    assert frames[0]["ok"] is False
    assert frames[0]["error"]["code"] == "no_store"
