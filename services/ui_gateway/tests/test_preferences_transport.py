"""
Tests — TransportGateway operator-preference legs (#770 M1).
=============================================================
``_preference_write_call`` drives PREFERENCE_WRITE_REQUEST →
PREFERENCE_WRITE_RESULT and ``_preference_list_call`` drives
PREFERENCE_LIST_REQUEST → PREFERENCE_LIST_RESPONSE, each over a fresh AO
connection.  Both are Fail-Closed (an error-shaped dict on any failure,
never raises).

Also asserts the END-TO-END gateway wiring: a ``/remember`` / ``/preferences``
message routed through ``handle_preferences_command`` reaches the coordinator,
whose injected write/list calls are the gateway's REAL transport legs (a
scripted AO drives the full chain) — and that a non-command message returns
``None`` (the normal prompt flow proceeds untouched).

A fake transport replays scripted frames; the real AO is never started.
Model-free; no real %LOCALAPPDATA% (root conftest redirects it).
"""

from __future__ import annotations

import asyncio
from typing import Any

from services.ui_gateway.src.transport import StartupState, TransportGateway
from shared.ipc.protocol import MessageFramer, MessageType

_framer = MessageFramer()

_ID_A = "a" * 32


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


def _write_result(*, status: str, pref_id: str = _ID_A) -> bytes:
    return _framer.encode_preference_write_result(
        ok=status in ("stored", "updated", "deleted"),
        op="remember", status=status, pref_id=pref_id, request_id="x",
    )


def _list_response(records: list[dict[str, Any]]) -> bytes:
    return _framer.encode_preference_list_response(
        preferences=records, request_id="x",
    )


def _rec(pref_id: str, body: str) -> dict[str, Any]:
    return {
        "pref_id": pref_id, "type_tag": "standing-rule", "subject": "",
        "body": body, "created": "2026-07-09T00:00:00+00:00",
        "updated": "2026-07-09T00:00:00+00:00",
    }


class TestWriteLeg:
    def test_write_round_trip_and_close(self) -> None:
        scripted = _ScriptedTransport([_write_result(status="stored")])
        gw = _gateway(scripted)
        result = asyncio.run(
            gw._preference_write_call("remember", "call me Blair", "")
        )
        assert result["status"] == "stored"
        assert scripted.closed
        msg_type, _rid, payload = _framer.decode(scripted.sent[0])
        assert msg_type is MessageType.PREFERENCE_WRITE_REQUEST
        assert payload["body"] == "call me Blair"  # verbatim on the wire

    def test_no_connection_is_fail_closed_shape(self) -> None:
        gw = _gateway(None)

        async def _open():
            return None

        gw._open_prompt_transport = _open  # type: ignore[method-assign]
        result = asyncio.run(gw._preference_write_call("remember", "x", ""))
        assert result["status"] == "refused"
        assert result["error_code"] == "TRANSPORT_ERROR"

    def test_invalid_op_never_crosses_ipc(self) -> None:
        scripted = _ScriptedTransport([])
        gw = _gateway(scripted)
        result = asyncio.run(gw._preference_write_call("obliterate", "x", ""))
        assert result["error_code"] == "TRANSPORT_ERROR"
        assert scripted.sent == []  # fail-closed at encode; nothing sent

    def test_no_response_is_fail_closed(self) -> None:
        scripted = _ScriptedTransport(None)
        gw = _gateway(scripted)
        result = asyncio.run(gw._preference_write_call("delete", "", _ID_A))
        assert result["status"] == "refused"
        assert scripted.closed


class TestListLeg:
    def test_list_round_trip(self) -> None:
        scripted = _ScriptedTransport(
            [_list_response([_rec(_ID_A, "call me Blair")])]
        )
        gw = _gateway(scripted)
        result = asyncio.run(gw._preference_list_call())
        assert result["total"] == 1
        assert result["preferences"][0]["body"] == "call me Blair"
        msg_type, _rid, _payload = _framer.decode(scripted.sent[0])
        assert msg_type is MessageType.PREFERENCE_LIST_REQUEST

    def test_list_failure_is_error_shaped(self) -> None:
        scripted = _ScriptedTransport(None)
        gw = _gateway(scripted)
        result = asyncio.run(gw._preference_list_call())
        assert result["preferences"] == [] and result["error"]


class TestEndToEndIntercept:
    def test_remember_reaches_the_ao_through_the_real_legs(self) -> None:
        scripted = _ScriptedTransport([_write_result(status="stored")])
        gw = _gateway(scripted)
        reply = asyncio.run(
            gw.handle_preferences_command("s-1", "/remember call me Blair")
        )
        assert reply is not None and "Saved" in reply
        msg_type, _rid, payload = _framer.decode(scripted.sent[0])
        assert msg_type is MessageType.PREFERENCE_WRITE_REQUEST
        assert payload == {
            "op": "remember", "body": "call me Blair", "pref_id": "", "token": "",
            "expires": "",
        }

    def test_confirm_reaches_the_ao_with_only_the_token(self) -> None:
        # #770 M2 W1 — /remember-confirm <token> rides the SAME PREFERENCE_WRITE
        # leg, carrying only the token (no body — confirm-hop integrity).
        tok = "0123456789abcdef"
        scripted = _ScriptedTransport([_write_result(status="stored")])
        gw = _gateway(scripted)
        reply = asyncio.run(
            gw.handle_preferences_command("s-1", f"/remember-confirm {tok}")
        )
        assert reply is not None and "Saved" in reply
        msg_type, _rid, payload = _framer.decode(scripted.sent[0])
        assert msg_type is MessageType.PREFERENCE_WRITE_REQUEST
        assert payload == {
            "op": "confirm", "body": "", "pref_id": "", "token": tok,
            "expires": "",
        }

    def test_preferences_list_reaches_the_ao(self) -> None:
        scripted = _ScriptedTransport(
            [_list_response([_rec(_ID_A, "call me Blair")])]
        )
        gw = _gateway(scripted)
        reply = asyncio.run(gw.handle_preferences_command("s-1", "/preferences"))
        assert reply is not None and "1. (standing-rule) call me Blair" in reply

    def test_non_command_returns_none_for_normal_prompt_flow(self) -> None:
        gw = _gateway(_ScriptedTransport([]))
        for text in ("hello there", "", "  ", "/load notes.txt"):
            assert asyncio.run(gw.handle_preferences_command("s-1", text)) is None

    def test_usage_reply_never_touches_the_transport(self) -> None:
        scripted = _ScriptedTransport([])
        gw = _gateway(scripted)
        reply = asyncio.run(gw.handle_preferences_command("s-1", "/remember"))
        assert reply is not None and "Usage" in reply
        assert scripted.sent == []  # deterministic help; no AO round-trip
