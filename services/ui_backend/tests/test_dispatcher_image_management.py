"""Frame-contract regression locks for the gallery management RPCs (UC-010 #668).

The WinUI gallery pane (UC-010 Phase 2) reaches the born-encrypted generated
images through two NON-STREAMING dispatcher RPCs:

* ``list_generated_images`` → ``_m_list_generated_images`` — METADATA-ONLY list.
* ``manage_generated_image`` → ``_m_manage_generated_image`` — delete / mark_saved
  by a ``uuid4().hex`` id.

These tests drive both through ``RpcDispatcher.handle`` with a FAKE gateway (no
real store, no decrypt, no bytes anywhere) and PIN: the ``ok_response`` shape the
C# ``BackendClient`` parses, the metadata-only contract, the up-front id/action
gate (a forged id or unknown action NEVER reaches the gateway), and the
fail-closed degradation (a stub gateway / any exception → a clean empty/ok=False
result, never an error frame, never a raise).

Mirrors ``test_dispatcher_resolve_image.py`` (same fake-gateway + ``_run`` shape).
The wire field names asserted here (``image_id``/``session_id``/``mime``/
``byte_size``/``saved``/``created_at`` for the list; ``ok``/``action``/
``image_id``/``found`` for manage) are the Phase-1 IMAGE_LIST/IMAGE_MANAGE
contract (services/ui_gateway/src/transport.py).
"""

from __future__ import annotations

import asyncio
from typing import Any

from services.ui_backend.src.dispatcher import RpcDispatcher


class _FakeGateway:
    """Minimal gateway exposing only the two management legs the dispatcher calls.

    ``_list_generated_images(session_id)`` and ``_manage_generated_image(action,
    image_id)`` each return whatever canned dict the test set, and RECORD every
    call so a test can assert a forged id / bad action NEVER reaches them.

    Both are ``async def`` — MATCHING the real ``TransportGateway`` legs (also
    ``async def``).  This shape parity is load-bearing: an earlier sync-``def`` fake
    let the dispatcher's wrong ``asyncio.to_thread(async_leg)`` PASS these tests
    while failing in production ("coroutine is not JSON serializable", #668).  Keep
    them async so the dispatcher must ``await`` them directly, as the real legs do.
    """

    def __init__(
        self,
        list_result: dict[str, Any] | None = None,
        manage_result: dict[str, Any] | None = None,
    ) -> None:
        self._list_result = list_result
        self._manage_result = manage_result
        self.list_calls: list[str | None] = []
        self.manage_calls: list[tuple[str, str]] = []

    async def _list_generated_images(self, session_id: str | None) -> dict[str, Any]:
        self.list_calls.append(session_id)
        return self._list_result or {"images": [], "total": 0, "truncated": False}

    async def _manage_generated_image(self, action: str, image_id: str) -> dict[str, Any]:
        self.manage_calls.append((action, image_id))
        return self._manage_result or {
            "ok": True, "action": action, "image_id": image_id, "found": True,
        }


class _StubGateway:
    """A gateway WITHOUT the management legs (an older backend) — getattr → None."""


def _run(dispatcher: RpcDispatcher, request: dict[str, Any]) -> list[dict[str, Any]]:
    frames: list[dict[str, Any]] = []

    async def send(frame: dict[str, Any]) -> None:
        frames.append(frame)

    asyncio.run(dispatcher.handle(request, send))
    return frames


# A valid uuid4().hex-shaped id (32 lowercase hex) the id gate accepts.
_VALID_ID = "0123456789abcdef0123456789abcdef"

# One canned metadata record in the Phase-1 IMAGE_LIST shape (no bytes).
_REC = {
    "image_id": _VALID_ID, "session_id": "s1", "mime": "image/png",
    "byte_size": 2048, "saved": False, "created_at": "2026-06-17T00:00:00+00:00",
}


# ── list: single ok_response carrying metadata ────────────────────────────


def test_list_emits_single_ok_response_with_metadata() -> None:
    gateway = _FakeGateway(list_result={"images": [_REC], "total": 1, "truncated": False})
    d = RpcDispatcher(gateway, None)
    frames = _run(
        d, {"id": 7, "method": "list_generated_images", "params": {}}
    )

    # Exactly one non-streaming ok_response frame.
    assert len(frames) == 1
    frame = frames[0]
    assert frame["id"] == 7
    assert frame["ok"] is True
    result = frame["result"]
    assert result["total"] == 1
    assert result["truncated"] is False
    # The record carries METADATA ONLY — the C# GeneratedImageMeta field names.
    img = result["images"][0]
    assert set(img) >= {"image_id", "session_id", "mime", "byte_size", "saved", "created_at"}
    # No byte-bearing field crossed the wire (metadata-only contract).
    assert "data" not in img and "data_b64" not in img and "bytes" not in img
    # Missing session_id → None filter (all images).
    assert gateway.list_calls == [None]


def test_list_passes_session_filter() -> None:
    gateway = _FakeGateway(list_result={"images": [], "total": 0, "truncated": False})
    d = RpcDispatcher(gateway, None)
    _run(
        d,
        {"id": 8, "method": "list_generated_images", "params": {"session_id": "sess-42"}},
    )
    assert gateway.list_calls == ["sess-42"]


def test_list_empty_session_string_is_none_filter() -> None:
    """An empty-string session_id is normalized to None (all images), not "" ."""
    gateway = _FakeGateway()
    d = RpcDispatcher(gateway, None)
    _run(
        d, {"id": 9, "method": "list_generated_images", "params": {"session_id": ""}}
    )
    assert gateway.list_calls == [None]


def test_list_stub_gateway_fails_closed_to_empty() -> None:
    """A gateway without the leg degrades to an empty gallery, not an error frame."""
    d = RpcDispatcher(_StubGateway(), None)
    frames = _run(d, {"id": 1, "method": "list_generated_images", "params": {}})
    assert len(frames) == 1
    assert frames[0]["ok"] is True
    assert frames[0]["result"] == {"images": [], "total": 0, "truncated": False}


def test_list_gateway_exception_fails_closed_to_empty() -> None:
    """ANY exception in the gateway leg → a clean empty result, never a raise."""
    class _BoomGateway:
        async def _list_generated_images(self, session_id: str | None) -> dict[str, Any]:
            raise RuntimeError("vsock blew up")

    d = RpcDispatcher(_BoomGateway(), None)
    frames = _run(d, {"id": 2, "method": "list_generated_images", "params": {}})
    assert len(frames) == 1
    assert frames[0]["ok"] is True  # ok_response, NOT an error frame
    assert frames[0]["result"] == {"images": [], "total": 0, "truncated": False}


# ── manage: delete / mark_saved delegate with the right action ─────────────


def test_manage_delete_delegates_with_action() -> None:
    gateway = _FakeGateway(manage_result={
        "ok": True, "action": "delete", "image_id": _VALID_ID, "found": True,
    })
    d = RpcDispatcher(gateway, None)
    frames = _run(d, {
        "id": 3, "method": "manage_generated_image",
        "params": {"action": "delete", "image_id": _VALID_ID},
    })
    assert len(frames) == 1
    assert frames[0]["ok"] is True
    assert frames[0]["result"]["ok"] is True
    assert frames[0]["result"]["found"] is True
    assert gateway.manage_calls == [("delete", _VALID_ID)]


def test_manage_mark_saved_delegates_with_action() -> None:
    gateway = _FakeGateway(manage_result={
        "ok": True, "action": "mark_saved", "image_id": _VALID_ID, "found": True,
    })
    d = RpcDispatcher(gateway, None)
    frames = _run(d, {
        "id": 4, "method": "manage_generated_image",
        "params": {"action": "mark_saved", "image_id": _VALID_ID},
    })
    assert frames[0]["result"]["action"] == "mark_saved"
    assert gateway.manage_calls == [("mark_saved", _VALID_ID)]


# ── manage: forged id / bad action refused BEFORE the gateway ──────────────


def test_manage_malformed_id_never_reaches_gateway() -> None:
    gateway = _FakeGateway()
    d = RpcDispatcher(gateway, None)
    frames = _run(d, {
        "id": 5, "method": "manage_generated_image",
        "params": {"action": "delete", "image_id": "not-a-valid-id"},
    })
    assert len(frames) == 1
    result = frames[0]["result"]
    assert result["ok"] is False
    assert result["error_code"] == "BAD_REQUEST"
    assert result["found"] is False
    # Fail-closed: a forged id is refused BEFORE the store is touched.
    assert gateway.manage_calls == []


def test_manage_id_with_non_hex_tail_refused() -> None:
    """A 32-hex id with extra characters fails the anchored \\A…\\Z gate (no IPC)."""
    gateway = _FakeGateway()
    d = RpcDispatcher(gateway, None)
    frames = _run(d, {
        "id": 6, "method": "manage_generated_image",
        "params": {"action": "delete", "image_id": _VALID_ID + "zz"},
    })
    assert frames[0]["result"]["error_code"] == "BAD_REQUEST"
    assert gateway.manage_calls == []


def test_manage_unknown_action_never_reaches_gateway() -> None:
    gateway = _FakeGateway()
    d = RpcDispatcher(gateway, None)
    frames = _run(d, {
        "id": 7, "method": "manage_generated_image",
        "params": {"action": "wipe_everything", "image_id": _VALID_ID},
    })
    result = frames[0]["result"]
    assert result["ok"] is False
    assert result["error_code"] == "BAD_REQUEST"
    # A bad action is refused BEFORE the store is touched (even with a valid id).
    assert gateway.manage_calls == []


def test_manage_empty_action_refused() -> None:
    gateway = _FakeGateway()
    d = RpcDispatcher(gateway, None)
    frames = _run(d, {
        "id": 8, "method": "manage_generated_image",
        "params": {"image_id": _VALID_ID},  # action missing entirely
    })
    assert frames[0]["result"]["error_code"] == "BAD_REQUEST"
    assert gateway.manage_calls == []


# ── manage: stub gateway / exception fail closed ───────────────────────────


def test_manage_stub_gateway_fails_closed() -> None:
    d = RpcDispatcher(_StubGateway(), None)
    frames = _run(d, {
        "id": 9, "method": "manage_generated_image",
        "params": {"action": "delete", "image_id": _VALID_ID},
    })
    result = frames[0]["result"]
    assert result["ok"] is False
    assert result["error_code"] == "UNSUPPORTED"


def test_manage_gateway_exception_fails_closed() -> None:
    class _BoomGateway:
        async def _manage_generated_image(self, action: str, image_id: str) -> dict[str, Any]:
            raise RuntimeError("store locked")

    d = RpcDispatcher(_BoomGateway(), None)
    frames = _run(d, {
        "id": 10, "method": "manage_generated_image",
        "params": {"action": "delete", "image_id": _VALID_ID},
    })
    result = frames[0]["result"]
    assert result["ok"] is False  # ok_response wrapper True, inner ok False
    assert frames[0]["ok"] is True  # never an error frame
    assert result["error_code"] == "INTERNAL_ERROR"
