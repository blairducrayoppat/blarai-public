"""
Tests — TransportGateway._resolve_generated_image (UC-010/UC-003 WS3)
====================================================================
The SYNC half of the display corridor: drives IMAGE_RESOLVE_REQUEST → chunked
IMAGE_RESOLVE_RESPONSE over a fresh AO connection into a capped
:class:`ResolveAssembler` and returns ``(mime, bytes) | None`` — Fail-Closed
(None on placeholder / cap / truncation / any error).

A fake transport replays scripted resolve-channel frames; the real AO is never
started.  Model-free; no real %LOCALAPPDATA% (root conftest redirects it).
"""

from __future__ import annotations

from typing import Any

from services.ui_gateway.src.transport import StartupState, TransportGateway
from shared.ipc.protocol import MessageFramer, MessageType
from shared.ipc.resolve_channel import (
    RESOLVE_CHUNK_DATA_BYTES,
    encode_resolve_placeholder,
    encode_resolve_response,
)

_framer = MessageFramer()
_PNG = b"\x89PNG\r\n\x1a\n" + b"\x00\x01\x02\x03" * 64


class _ScriptedTransport:
    """Replays a fixed list of response frames; records the request + close."""

    def __init__(self, frames: list[bytes] | None) -> None:
        self._frames = list(frames or [])
        self.sent: list[bytes] = []
        self.closed = False
        self._truncate = frames is None  # None list = immediate truncation

    def send(self, data: bytes) -> bool:
        self.sent.append(data)
        return True

    def receive(self) -> bytes | None:
        if self._truncate or not self._frames:
            return None  # truncation / end-of-stream
        return self._frames.pop(0)

    def close(self) -> None:
        self.closed = True


def _gateway(transport: _ScriptedTransport | None) -> TransportGateway:
    gw = TransportGateway(dev_mode=True, port=0)
    gw._state = StartupState.OPERATIONAL
    gw._open_prompt_transport_sync = lambda: transport  # type: ignore[method-assign]
    return gw


# ---------------------------------------------------------------------------
# Found
# ---------------------------------------------------------------------------


def test_found_single_chunk_returns_bytes() -> None:
    frames = encode_resolve_response(request_id="r1", mime="image/png", data=_PNG)
    t = _ScriptedTransport(frames)
    gw = _gateway(t)
    got = gw._resolve_generated_image("a" * 32)
    assert got == ("image/png", _PNG)
    assert t.closed is True  # connection-per-message hygiene
    # The request frame the gateway sent is a well-formed IMAGE_RESOLVE_REQUEST.
    mt, _rid, payload = _framer.decode(t.sent[0])
    assert mt == MessageType.IMAGE_RESOLVE_REQUEST
    assert payload["image_id"] == "a" * 32


def test_found_multichunk_reassembles() -> None:
    big = b"\x89PNG\r\n\x1a\n" + bytes(range(256)) * ((RESOLVE_CHUNK_DATA_BYTES * 2) // 256 + 1)
    frames = encode_resolve_response(request_id="r2", mime="image/webp", data=big)
    assert len(frames) >= 2
    gw = _gateway(_ScriptedTransport(frames))
    got = gw._resolve_generated_image("b" * 32)
    assert got is not None
    assert got[0] == "image/webp"
    assert got[1] == big


# ---------------------------------------------------------------------------
# Placeholder / None paths
# ---------------------------------------------------------------------------


def test_placeholder_returns_none() -> None:
    frames = encode_resolve_placeholder(request_id="r3")
    gw = _gateway(_ScriptedTransport(frames))
    assert gw._resolve_generated_image("c" * 32) is None


def test_empty_id_returns_none_without_connecting() -> None:
    t = _ScriptedTransport([])
    gw = _gateway(t)
    assert gw._resolve_generated_image("") is None
    assert t.sent == []  # never connected / sent


def test_connect_failure_returns_none() -> None:
    gw = _gateway(None)
    assert gw._resolve_generated_image("d" * 32) is None


def test_truncated_stream_returns_none() -> None:
    """receive() returns None mid-stream → incomplete assembler → None."""
    big = b"X" * (RESOLVE_CHUNK_DATA_BYTES * 2)
    frames = encode_resolve_response(request_id="r4", mime="image/png", data=big)
    # Deliver only the FIRST chunk, then truncate.
    t = _ScriptedTransport([frames[0]])
    gw = _gateway(t)
    assert gw._resolve_generated_image("e" * 32) is None
    assert t.closed is True


def test_oversize_declaration_returns_none_no_unbounded_reassembly() -> None:
    """A first frame declaring an over-cap total is rejected by the assembler
    (before buffering) → None.  No unbounded reassembly."""
    import base64
    from shared.ipc.resolve_channel import RESOLVE_BODY_MAX_BYTES

    bad = _framer.encode(
        MessageType.IMAGE_RESOLVE_RESPONSE,
        {
            "found": True,
            "seq": 0,
            "chunk_count": 99,
            "total_bytes": RESOLVE_BODY_MAX_BYTES + 1,
            "mime": "image/png",
            "data": base64.b64encode(b"x" * 10).decode("ascii"),
        },
        "r5",
    )
    t = _ScriptedTransport([bad])
    gw = _gateway(t)
    assert gw._resolve_generated_image("f" * 32) is None


def test_malformed_frame_returns_none() -> None:
    bad = _framer.encode(MessageType.HEARTBEAT, {}, "r6")  # wrong type
    gw = _gateway(_ScriptedTransport([bad]))
    assert gw._resolve_generated_image("0" * 32) is None


def test_send_failure_returns_none() -> None:
    class _SendFail(_ScriptedTransport):
        def send(self, data: bytes) -> bool:
            return False

    t = _SendFail([])
    gw = _gateway(t)
    assert gw._resolve_generated_image("a" * 32) is None
    assert t.closed is True
