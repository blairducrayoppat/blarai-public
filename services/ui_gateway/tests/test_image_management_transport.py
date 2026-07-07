"""
Tests — TransportGateway generated-image management legs (UC-010 Phase 1, #667)
===============================================================================
``_list_generated_images`` drives IMAGE_LIST_REQUEST → IMAGE_LIST_RESPONSE and
``_manage_generated_image`` drives IMAGE_MANAGE_REQUEST → IMAGE_MANAGE_RESULT,
each over a fresh AO connection.  Both are Fail-Closed (an error-shaped dict on
any failure, never raises).

Also asserts the END-TO-END gateway wiring with NO dispatcher change: a
``/images`` message routed through ``handle_imagine_command`` reaches the
coordinator's ``/images`` surface, and the coordinator's injected lister/manager
are the gateway's real transport legs (so a scripted AO drives the full chain).

A fake transport replays scripted frames; the real AO is never started.
Model-free; no real %LOCALAPPDATA% (root conftest redirects it).
"""

from __future__ import annotations

import asyncio
from typing import Any

from services.ui_gateway.src.transport import StartupState, TransportGateway
from shared.ipc.protocol import MessageFramer, MessageType

_framer = MessageFramer()


class _ScriptedTransport:
    """Replays a fixed list of response frames; records the request + close."""

    def __init__(self, frames: list[bytes] | None) -> None:
        self._frames = list(frames or [])
        self.sent: list[bytes] = []
        self.closed = False
        self._truncate = frames is None

    def send(self, data: bytes) -> bool:
        self.sent.append(data)
        return True

    def receive(self) -> bytes | None:
        if self._truncate or not self._frames:
            return None
        return self._frames.pop(0)

    def close(self) -> None:
        self.closed = True


def _gateway(transport: _ScriptedTransport | None) -> TransportGateway:
    gw = TransportGateway(dev_mode=True, port=0)
    gw._state = StartupState.OPERATIONAL

    async def _open():
        return transport

    gw._open_prompt_transport = _open  # type: ignore[method-assign]
    return gw


def _list_response(records: list[dict[str, Any]], total: int, truncated: bool = False) -> bytes:
    return _framer.encode_image_list_response(
        images=records, total=total, truncated=truncated, request_id="x",
    )


def _manage_result(*, ok: bool, action: str, image_id: str, found: bool) -> bytes:
    return _framer.encode_image_manage_result(
        ok=ok, action=action, image_id=image_id, found=found, request_id="x",
    )


def _rec(image_id: str, *, saved: bool = False) -> dict[str, Any]:
    return {
        "image_id": image_id, "session_id": "s1", "mime": "image/png",
        "byte_size": 2048, "saved": saved, "created_at": "2026-06-17T00:00:00+00:00",
    }


# ---------------------------------------------------------------------------
# _list_generated_images
# ---------------------------------------------------------------------------


def test_list_leg_decodes_response() -> None:
    async def run():
        t = _ScriptedTransport([_list_response([_rec("a" * 32, saved=True)], total=1)])
        gw = _gateway(t)
        d = await gw._list_generated_images(None)
        assert d["total"] == 1
        assert d["images"][0]["image_id"] == "a" * 32
        assert d["images"][0]["saved"] is True
        assert t.closed is True
        # The sent frame is a well-formed IMAGE_LIST_REQUEST.
        mt, _rid, payload = _framer.decode(t.sent[0])
        assert mt == MessageType.IMAGE_LIST_REQUEST
    asyncio.run(run())


def test_list_leg_session_filter_in_request() -> None:
    async def run():
        t = _ScriptedTransport([_list_response([], total=0)])
        gw = _gateway(t)
        await gw._list_generated_images("sess-42")
        _mt, _rid, payload = _framer.decode(t.sent[0])
        assert payload["session_id"] == "sess-42"
    asyncio.run(run())


def test_list_leg_connect_failure_is_error_dict() -> None:
    async def run():
        gw = _gateway(None)
        d = await gw._list_generated_images(None)
        assert d["images"] == [] and d["total"] == 0
        assert d.get("error")  # non-empty error text (Fail-Closed shape)
    asyncio.run(run())


def test_list_leg_truncation_returns_none_is_error() -> None:
    async def run():
        t = _ScriptedTransport(None)  # immediate truncation
        gw = _gateway(t)
        d = await gw._list_generated_images(None)
        assert d.get("error")
    asyncio.run(run())


# ---------------------------------------------------------------------------
# _manage_generated_image
# ---------------------------------------------------------------------------


def test_manage_leg_delete_round_trip() -> None:
    async def run():
        iid = "b" * 32
        t = _ScriptedTransport([_manage_result(ok=True, action="delete", image_id=iid, found=True)])
        gw = _gateway(t)
        d = await gw._manage_generated_image("delete", iid)
        assert d["ok"] is True and d["found"] is True
        mt, _rid, payload = _framer.decode(t.sent[0])
        assert mt == MessageType.IMAGE_MANAGE_REQUEST
        assert payload == {"action": "delete", "image_id": iid}
        assert t.closed is True
    asyncio.run(run())


def test_manage_leg_mark_saved_round_trip() -> None:
    async def run():
        iid = "c" * 32
        t = _ScriptedTransport([_manage_result(ok=True, action="mark_saved", image_id=iid, found=True)])
        gw = _gateway(t)
        d = await gw._manage_generated_image("mark_saved", iid)
        assert d["ok"] is True
        _mt, _rid, payload = _framer.decode(t.sent[0])
        assert payload["action"] == "mark_saved"
    asyncio.run(run())


def test_manage_leg_connect_failure_is_error() -> None:
    async def run():
        gw = _gateway(None)
        d = await gw._manage_generated_image("delete", "d" * 32)
        assert d["ok"] is False
        assert d["error_code"] == "TRANSPORT_ERROR"
    asyncio.run(run())


# ---------------------------------------------------------------------------
# End-to-end gateway wiring: /images through handle_imagine_command (no dispatcher)
# ---------------------------------------------------------------------------


def test_handle_imagine_command_routes_images_list() -> None:
    """A /images message routed through the gateway's handle_imagine_command
    reaches the coordinator + the gateway-wired lister leg (a scripted AO drives
    the full chain), proving NO dispatcher change is needed for /images."""
    async def run():
        t = _ScriptedTransport([_list_response([_rec("a" * 32, saved=True)], total=1)])
        gw = _gateway(t)
        reply = await gw.handle_imagine_command("s1", "/images")
        assert reply is not None
        assert "aaaaaaaa" in reply  # short id rendered
        assert "SAVED" in reply
        # The frame the gateway actually sent was an IMAGE_LIST_REQUEST.
        mt, _rid, _p = _framer.decode(t.sent[0])
        assert mt == MessageType.IMAGE_LIST_REQUEST
    asyncio.run(run())


def test_handle_imagine_command_routes_images_delete() -> None:
    async def run():
        iid = "a" * 32
        t = _ScriptedTransport([_manage_result(ok=True, action="delete", image_id=iid, found=True)])
        gw = _gateway(t)
        reply = await gw.handle_imagine_command("s1", f"/images delete {iid}")
        assert reply is not None
        assert "deleted" in reply.lower()
        mt, _rid, payload = _framer.decode(t.sent[0])
        assert mt == MessageType.IMAGE_MANAGE_REQUEST
        assert payload["action"] == "delete"
    asyncio.run(run())


def test_handle_imagine_command_images_delete_partial_id_no_ipc() -> None:
    """A partial id is refused in the coordinator BEFORE any IPC — the gateway
    never connects to the AO for a forged delete."""
    async def run():
        t = _ScriptedTransport([])  # nothing should be sent
        gw = _gateway(t)
        reply = await gw.handle_imagine_command("s1", "/images delete abc")
        assert reply is not None
        assert "32-character" in reply
        assert t.sent == []  # no IPC issued
    asyncio.run(run())


def test_handle_imagine_command_non_image_returns_none() -> None:
    """A normal prompt is NOT an image command — handle_imagine_command returns
    None so the caller proceeds with the unchanged send_prompt flow."""
    async def run():
        gw = _gateway(_ScriptedTransport([]))
        assert await gw.handle_imagine_command("s1", "just chatting") is None
    asyncio.run(run())
