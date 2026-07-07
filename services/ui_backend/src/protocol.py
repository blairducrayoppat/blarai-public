"""
UI Backend Wire Protocol — length-prefixed JSON over a named pipe (ADR-014)
===========================================================================
The WinUI 3 front end and this Python backend exchange JSON frames over a
Windows named pipe. Each frame is a 4-byte big-endian unsigned length prefix
followed by that many bytes of UTF-8 JSON — the same framing discipline the
vsock transport uses (`shared/ipc/vsock.py` `!I` / 4-byte header), chosen for
consistency so a developer who knows one knows the other.

Request frame (front end -> backend):
    {"id": <int>, "method": <str>, "params": {<...>}}

Response frame(s) (backend -> front end). Non-streaming methods send exactly
one of:
    {"id": <int>, "ok": true,  "result": <any>}
    {"id": <int>, "ok": false, "error": {"code": <str>, "message": <str>}}

Streaming methods (currently only ``prompt``) send a sequence of:
    {"id": <int>, "stream": "token", "value": {<StreamToken dict>}}
    {"id": <int>, "stream": "pgov",  "value": {<GatewayPGOVResult dict>}}
    {"id": <int>, "stream": "end",   "value": {"request_id": <str>}}
and may send a terminal error frame instead of "end" on failure.

Security:
  - Frame size is hard-capped (MAX_FRAME_BYTES) on both encode and decode to
    prevent an unbounded-read against a hostile or corrupt peer.
  - Malformed JSON / oversize frames raise ProtocolError; the caller maps that
    to a Fail-Closed error response or a closed connection.
  - No external network: a named pipe is a kernel object, not a socket.
"""

from __future__ import annotations

import json
import struct
from typing import Any, Callable

# 4-byte big-endian unsigned length prefix (mirrors shared/ipc/vsock.py).
_HEADER_FORMAT: str = "!I"
_HEADER_SIZE: int = 4

# Generous bound: text documents cap at 16 KB and media is store-only
# (placeholder text), so real frames are small. 4 MB leaves ample headroom
# for long history payloads while still refusing pathological inputs.
MAX_FRAME_BYTES: int = 4 * 1024 * 1024


class ProtocolError(Exception):
    """Raised on a malformed, oversize, or truncated frame."""


def encode_frame(obj: dict[str, Any]) -> bytes:
    """Serialize *obj* to a length-prefixed JSON frame.

    Raises:
        ProtocolError: If the encoded body exceeds ``MAX_FRAME_BYTES``.
    """
    body = json.dumps(obj, separators=(",", ":")).encode("utf-8")
    if len(body) > MAX_FRAME_BYTES:
        raise ProtocolError(
            f"Frame body {len(body)} exceeds limit {MAX_FRAME_BYTES}"
        )
    return struct.pack(_HEADER_FORMAT, len(body)) + body


def read_frame(recv_exact: Callable[[int], bytes]) -> dict[str, Any] | None:
    """Read one frame using *recv_exact*, a callable returning exactly N bytes.

    ``recv_exact(n)`` MUST return exactly ``n`` bytes, or ``b""`` (empty) at
    end-of-stream. (The named-pipe server provides a helper that loops
    ``ReadFile`` until ``n`` bytes are accumulated.)

    Returns:
        The decoded frame dict, or ``None`` if the stream is cleanly closed
        before any header byte arrives.

    Raises:
        ProtocolError: On a truncated header/body, an oversize length, or
            malformed JSON.
    """
    header = recv_exact(_HEADER_SIZE)
    if header == b"":
        return None  # clean EOF at a frame boundary
    if len(header) != _HEADER_SIZE:
        raise ProtocolError("Truncated frame header")

    (length,) = struct.unpack(_HEADER_FORMAT, header)
    if length > MAX_FRAME_BYTES:
        raise ProtocolError(f"Frame length {length} exceeds limit {MAX_FRAME_BYTES}")
    if length == 0:
        raise ProtocolError("Zero-length frame")

    body = recv_exact(length)
    if len(body) != length:
        raise ProtocolError("Truncated frame body")

    try:
        decoded = json.loads(body.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ProtocolError(f"Malformed frame JSON: {exc}") from exc

    if not isinstance(decoded, dict):
        raise ProtocolError("Frame must be a JSON object")
    return decoded


def ok_response(request_id: Any, result: Any) -> dict[str, Any]:
    """Build a success response frame."""
    return {"id": request_id, "ok": True, "result": result}


def error_response(request_id: Any, code: str, message: str) -> dict[str, Any]:
    """Build an error response frame (Fail-Closed shape)."""
    return {"id": request_id, "ok": False, "error": {"code": code, "message": message}}


def stream_frame(request_id: Any, kind: str, value: Any) -> dict[str, Any]:
    """Build a streaming frame (``kind`` is ``"token"``/``"pgov"``/``"end"``)."""
    return {"id": request_id, "stream": kind, "value": value}
