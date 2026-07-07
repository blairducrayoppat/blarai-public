"""Frame-contract regression locks for ``_m_resolve_image`` (ADR-033 §D).

The named-pipe ``resolve_image`` leg is the ONLY safety net for the field names
the C# ``BackendClient.ResolveImageAsync`` reassembler depends on
(``data_b64`` / ``mime`` / ``found``).  These tests drive ``_m_resolve_image``
with a FAKE gateway (no real store, no decrypt, no bytes to disk) and PIN the
exact emitted frame shape, so a future rename breaks the gate here rather than
silently on the on-hardware go-live ceremony.

Frame shape (``protocol.stream_frame``): ``{"id": rid, "stream": kind, "value": v}``.
"""

from __future__ import annotations

import asyncio
from typing import Any

from services.ui_backend.src.dispatcher import RpcDispatcher


class _FakeGateway:
    """Minimal gateway exposing only the resolve reader the dispatcher calls.

    ``_resolve_generated_image(image_id)`` returns whatever ``result`` is set to
    (a ``(mime, bytes)`` pair or ``None``).  ``calls`` records every id it was
    asked to resolve so a test can assert a malformed id NEVER reaches it.
    """

    def __init__(self, result: tuple[str, bytes] | None) -> None:
        self._result = result
        self.calls: list[str] = []

    def _resolve_generated_image(self, image_id: str) -> tuple[str, bytes] | None:
        self.calls.append(image_id)
        return self._result


def _run(dispatcher: RpcDispatcher, request: dict[str, Any]) -> list[dict[str, Any]]:
    frames: list[dict[str, Any]] = []

    async def send(frame: dict[str, Any]) -> None:
        frames.append(frame)

    asyncio.run(dispatcher.handle(request, send))
    return frames


# A valid uuid4().hex-shaped id (32 lowercase hex) the id gate accepts.
_VALID_ID = "0123456789abcdef0123456789abcdef"
_PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"fake-decrypted-pixels"


# ── happy path: chunk(s) with data_b64 + mime, then end{found:true} ────────


def test_resolve_image_emits_chunk_then_end_found_true() -> None:
    import base64

    gateway = _FakeGateway(("image/png", _PNG_BYTES))
    d = RpcDispatcher(gateway, None)
    frames = _run(
        d, {"id": 9, "method": "resolve_image", "params": {"image_id": _VALID_ID}}
    )

    kinds = [f.get("stream") for f in frames]
    # One-or-more chunk(s) then exactly one terminal end.
    assert kinds[-1] == "end"
    chunk_frames = [f for f in frames if f.get("stream") == "chunk"]
    assert len(chunk_frames) >= 1

    # The C# reassembler depends on these EXACT field names.
    first = chunk_frames[0]
    assert set(first["value"]) == {"data_b64", "mime"}  # mime rides the FIRST chunk
    assert first["value"]["mime"] == "image/png"
    # data_b64 is base64 of the (decrypted) bytes — reassembling decodes to them.
    reassembled = b"".join(
        base64.b64decode(f["value"]["data_b64"]) for f in chunk_frames
    )
    assert reassembled == _PNG_BYTES

    # Only the FIRST chunk carries mime; later chunks (if any) carry data only.
    for f in chunk_frames[1:]:
        assert set(f["value"]) == {"data_b64"}

    # Terminal frame: exactly {"found": True}.
    assert frames[-1]["value"] == {"found": True}
    # rid is preserved on every frame.
    assert all(f["id"] == 9 for f in frames)
    assert gateway.calls == [_VALID_ID]


def test_resolve_image_chunks_large_image_mime_on_first_only() -> None:
    """A >chunk-size image splits across multiple chunk frames; mime rides only
    the first.  PINS the per-chunk field contract under real chunking."""
    import base64

    big = b"\x89PNG\r\n\x1a\n" + b"Q" * (RpcDispatcher._RESOLVE_PIPE_CHUNK_BYTES + 1024)
    gateway = _FakeGateway(("image/png", big))
    d = RpcDispatcher(gateway, None)
    frames = _run(
        d, {"id": 3, "method": "resolve_image", "params": {"image_id": _VALID_ID}}
    )

    chunk_frames = [f for f in frames if f.get("stream") == "chunk"]
    assert len(chunk_frames) >= 2  # actually chunked
    assert "mime" in chunk_frames[0]["value"]
    assert all("mime" not in f["value"] for f in chunk_frames[1:])
    reassembled = b"".join(
        base64.b64decode(f["value"]["data_b64"]) for f in chunk_frames
    )
    assert reassembled == big
    assert frames[-1]["value"] == {"found": True}


# ── none result: a single end{found:false}, no chunk ───────────────────────


def test_resolve_image_none_result_emits_only_end_found_false() -> None:
    gateway = _FakeGateway(None)  # unknown id / decrypt-quarantine / dormant
    d = RpcDispatcher(gateway, None)
    frames = _run(
        d, {"id": 1, "method": "resolve_image", "params": {"image_id": _VALID_ID}}
    )

    assert len(frames) == 1
    assert frames[0]["stream"] == "end"
    assert frames[0]["value"] == {"found": False}
    # The gateway WAS consulted (the id is well-formed) but returned None.
    assert gateway.calls == [_VALID_ID]


def test_resolve_image_empty_bytes_treated_as_not_found() -> None:
    """A found row with empty bytes ⇒ end{found:false}, no chunk (display-absent)."""
    gateway = _FakeGateway(("image/png", b""))
    d = RpcDispatcher(gateway, None)
    frames = _run(
        d, {"id": 2, "method": "resolve_image", "params": {"image_id": _VALID_ID}}
    )
    assert len(frames) == 1
    assert frames[0]["value"] == {"found": False}


# ── malformed / forged id: end{found:false}, NO resolve attempt ────────────


def test_resolve_image_malformed_id_never_reaches_gateway() -> None:
    gateway = _FakeGateway(("image/png", _PNG_BYTES))
    d = RpcDispatcher(gateway, None)
    frames = _run(
        d,
        {"id": 5, "method": "resolve_image", "params": {"image_id": "not-a-valid-id"}},
    )

    assert len(frames) == 1
    assert frames[0]["stream"] == "end"
    assert frames[0]["value"] == {"found": False}
    # Fail-closed: a forged/malformed id is refused BEFORE the resolve leg.
    assert gateway.calls == []


def test_resolve_image_forged_id_with_non_hex_tail_refused() -> None:
    """A 32-hex id with extra non-hex characters fails the anchored \\A…\\Z gate
    ⇒ end{found:false}, NO resolve attempt (the ADR-032 Am.1 anchoring lesson)."""
    gateway = _FakeGateway(("image/png", _PNG_BYTES))
    d = RpcDispatcher(gateway, None)
    frames = _run(
        d,
        {"id": 6, "method": "resolve_image", "params": {"image_id": _VALID_ID + "zz"}},
    )
    assert len(frames) == 1
    assert frames[0]["stream"] == "end"
    assert frames[0]["value"] == {"found": False}
    assert gateway.calls == []
