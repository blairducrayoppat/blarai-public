"""Tests for the named-pipe wire protocol (length-prefixed JSON)."""

from __future__ import annotations

import json
import struct

import pytest

from services.ui_backend.src.protocol import (
    MAX_FRAME_BYTES,
    ProtocolError,
    encode_frame,
    error_response,
    ok_response,
    read_frame,
    stream_frame,
)


class _ByteFeeder:
    """recv_exact source backed by a fixed byte buffer (returns b'' at EOF)."""

    def __init__(self, data: bytes) -> None:
        self._data = data
        self._pos = 0

    def __call__(self, n: int) -> bytes:
        chunk = self._data[self._pos : self._pos + n]
        self._pos += len(chunk)
        return chunk


def test_encode_read_roundtrip() -> None:
    frame = {"id": 1, "method": "ping", "params": {"x": [1, 2, 3]}}
    feeder = _ByteFeeder(encode_frame(frame))
    assert read_frame(feeder) == frame


def test_multiple_frames_in_sequence() -> None:
    a = {"id": 1, "method": "a", "params": {}}
    b = {"id": 2, "method": "b", "params": {"k": "v"}}
    feeder = _ByteFeeder(encode_frame(a) + encode_frame(b))
    assert read_frame(feeder) == a
    assert read_frame(feeder) == b
    assert read_frame(feeder) is None  # clean EOF


def test_clean_eof_returns_none() -> None:
    assert read_frame(_ByteFeeder(b"")) is None


def test_truncated_header_raises() -> None:
    with pytest.raises(ProtocolError, match="Truncated frame header"):
        read_frame(_ByteFeeder(b"\x00\x01"))  # only 2 of 4 header bytes


def test_truncated_body_raises() -> None:
    # Header claims 100 bytes; supply 5.
    data = struct.pack("!I", 100) + b"short"
    with pytest.raises(ProtocolError, match="Truncated frame body"):
        read_frame(_ByteFeeder(data))


def test_zero_length_frame_raises() -> None:
    with pytest.raises(ProtocolError, match="Zero-length"):
        read_frame(_ByteFeeder(struct.pack("!I", 0)))


def test_oversize_length_raises() -> None:
    data = struct.pack("!I", MAX_FRAME_BYTES + 1)
    with pytest.raises(ProtocolError, match="exceeds limit"):
        read_frame(_ByteFeeder(data))


def test_malformed_json_raises() -> None:
    body = b"{not json"
    data = struct.pack("!I", len(body)) + body
    with pytest.raises(ProtocolError, match="Malformed frame JSON"):
        read_frame(_ByteFeeder(data))


def test_non_object_frame_raises() -> None:
    body = json.dumps([1, 2, 3]).encode("utf-8")
    data = struct.pack("!I", len(body)) + body
    with pytest.raises(ProtocolError, match="must be a JSON object"):
        read_frame(_ByteFeeder(data))


def test_encode_oversize_raises() -> None:
    huge = {"id": 1, "blob": "x" * (MAX_FRAME_BYTES + 10)}
    with pytest.raises(ProtocolError, match="exceeds limit"):
        encode_frame(huge)


def test_response_builders() -> None:
    assert ok_response(7, {"a": 1}) == {"id": 7, "ok": True, "result": {"a": 1}}
    assert error_response(7, "boom", "bad") == {
        "id": 7,
        "ok": False,
        "error": {"code": "boom", "message": "bad"},
    }
    assert stream_frame(7, "token", {"t": "hi"}) == {
        "id": 7,
        "stream": "token",
        "value": {"t": "hi"},
    }


def test_unicode_roundtrip() -> None:
    frame = {"id": 1, "text": "café — naïve — 日本語 — 🎉"}
    feeder = _ByteFeeder(encode_frame(frame))
    assert read_frame(feeder) == frame
