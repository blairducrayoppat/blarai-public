"""
Tests — Image-Resolve Channel (UC-010/UC-003 WS3, ADR-033 §D)
=============================================================
shared/ipc/resolve_channel.py

The chunked, capped, fail-closed framing for the display-resolve corridor
(IMAGE_RESOLVE_REQUEST → chunked IMAGE_RESOLVE_RESPONSE). Modelled on the proven
parse channel; these locks mirror test_parse_channel's discipline:

  * round-trip (small single-chunk + multi-chunk byte-identical reassembly)
  * the placeholder (found=false) single small frame — no data
  * oversize rejected BEFORE buffering (encode raises; assembler rejects an
    oversize declared total on the FIRST frame)
  * truncation / reorder / cross-talk / bad-base64 all fail closed (raise)
  * the cap is sized for generated images (decoupled from + larger than image_staging.MAX_IMAGE_BYTES)

Model-free; no AO, no network.
"""

from __future__ import annotations

import base64
import json

import pytest

from shared.ipc.protocol import MessageFramer, MessageType
from shared.ipc.resolve_channel import (
    RESOLVE_BODY_MAX_BYTES,
    RESOLVE_CHUNK_DATA_BYTES,
    ResolveAssembler,
    ResolveChannelError,
    decode_resolve_request,
    encode_resolve_placeholder,
    encode_resolve_request,
    encode_resolve_response,
)
from shared.security.image_staging import MAX_IMAGE_BYTES

_PNG = b"\x89PNG\r\n\x1a\n"


def _assemble(frames: list[bytes]) -> ResolveAssembler:
    asm = ResolveAssembler()
    for f in frames:
        asm.feed(f)
    return asm


# ---------------------------------------------------------------------------
# Cap lock — the resolve cap is sized for generated images (NOT the fetch cap)
# ---------------------------------------------------------------------------


def test_resolve_cap_sized_for_generated_images() -> None:
    # The resolve corridor delivers generated images, which have NO 2 MiB fetch
    # cap (a 1024² SDXL PNG routinely exceeds it), so the resolve cap is
    # DELIBERATELY decoupled from + larger than image_staging.MAX_IMAGE_BYTES.
    # (The prior coupling silently refused generated images — #666 go-live.)
    assert RESOLVE_BODY_MAX_BYTES == 16 * 1024 * 1024
    assert RESOLVE_BODY_MAX_BYTES > MAX_IMAGE_BYTES


# ---------------------------------------------------------------------------
# Request encode / decode
# ---------------------------------------------------------------------------


def test_request_round_trip() -> None:
    iid = "a" * 32
    frame = encode_resolve_request(request_id="r1", image_id=iid)
    req = decode_resolve_request(frame)
    assert req.request_id == "r1"
    assert req.image_id == iid


def test_request_missing_id_raises() -> None:
    with pytest.raises(ResolveChannelError):
        encode_resolve_request(request_id="r1", image_id="")
    with pytest.raises(ResolveChannelError):
        encode_resolve_request(request_id="", image_id="a" * 32)


def test_decode_request_wrong_type_raises() -> None:
    framer = MessageFramer()
    bad = framer.encode(MessageType.HEARTBEAT, {}, "r1")
    with pytest.raises(ResolveChannelError):
        decode_resolve_request(bad)


# ---------------------------------------------------------------------------
# Response round-trip — small (single chunk) and multi-chunk
# ---------------------------------------------------------------------------


def test_response_small_round_trip() -> None:
    body = _PNG + b"\x01\x02\x03" * 50
    frames = encode_resolve_response(request_id="r2", mime="image/png", data=body)
    assert len(frames) == 1
    asm = _assemble(frames)
    assert asm.complete
    assert asm.found is True
    assert asm.mime == "image/png"
    assert asm.body() == body
    resp = asm.response()
    assert resp.data == body and resp.mime == "image/png" and resp.found


def test_response_multi_chunk_byte_identical() -> None:
    # Force >1 chunk: 2.5 * chunk size.
    body = bytes(range(256)) * ((RESOLVE_CHUNK_DATA_BYTES * 5 // 2) // 256 + 1)
    body = body[: RESOLVE_CHUNK_DATA_BYTES * 5 // 2]
    frames = encode_resolve_response(request_id="r3", mime="image/webp", data=body)
    assert len(frames) >= 3
    asm = _assemble(frames)
    assert asm.complete and asm.found
    assert asm.body() == body
    assert asm.mime == "image/webp"


def test_response_exact_chunk_boundary() -> None:
    body = b"Z" * (RESOLVE_CHUNK_DATA_BYTES * 2)
    frames = encode_resolve_response(request_id="r4", mime="image/png", data=body)
    assert len(frames) == 2
    assert _assemble(frames).body() == body


# ---------------------------------------------------------------------------
# Placeholder (None result)
# ---------------------------------------------------------------------------


def test_placeholder_single_frame_no_data() -> None:
    frames = encode_resolve_placeholder(request_id="r5")
    assert len(frames) == 1
    payload = json.loads(frames[0].decode("utf-8"))["payload"]
    assert payload == {"found": False}  # no data, no mime
    asm = _assemble(frames)
    assert asm.complete
    assert asm.found is False
    assert asm.body() == b""
    assert asm.response().found is False


def test_placeholder_requires_request_id() -> None:
    with pytest.raises(ResolveChannelError):
        encode_resolve_placeholder(request_id="")


# ---------------------------------------------------------------------------
# Encode-side fail-closed
# ---------------------------------------------------------------------------


def test_encode_oversize_body_raises_before_send() -> None:
    too_big = b"\x00" * (RESOLVE_BODY_MAX_BYTES + 1)
    with pytest.raises(ResolveChannelError):
        encode_resolve_response(request_id="r6", mime="image/png", data=too_big)


def test_encode_empty_body_raises() -> None:
    with pytest.raises(ResolveChannelError):
        encode_resolve_response(request_id="r6", mime="image/png", data=b"")


def test_encode_empty_mime_raises() -> None:
    with pytest.raises(ResolveChannelError):
        encode_resolve_response(request_id="r6", mime="", data=_PNG)


# ---------------------------------------------------------------------------
# Receive-side fail-closed: oversize-before-buffering, truncation, reorder,
# cross-talk, bad base64
# ---------------------------------------------------------------------------


def _found_frame(
    *,
    request_id: str = "r",
    seq: int = 0,
    chunk_count: int = 1,
    total_bytes: int,
    raw: bytes,
    mime: str | None = "image/png",
) -> bytes:
    payload: dict = {
        "found": True,
        "seq": seq,
        "chunk_count": chunk_count,
        "total_bytes": total_bytes,
        "data": base64.b64encode(raw).decode("ascii"),
    }
    if mime is not None:
        payload["mime"] = mime
    return MessageFramer().encode(
        MessageType.IMAGE_RESOLVE_RESPONSE, payload, request_id
    )


def test_oversize_declaration_rejected_on_first_frame_before_buffering() -> None:
    # A hand-rolled first frame declaring an over-cap total is rejected at feed
    # time before any (further) buffering — no unbounded reassembly.
    asm = ResolveAssembler()
    bad = _found_frame(
        total_bytes=RESOLVE_BODY_MAX_BYTES + 1,
        chunk_count=99,
        raw=b"x" * 10,
    )
    with pytest.raises(ResolveChannelError):
        asm.feed(bad)


def test_truncation_incomplete_body_raises() -> None:
    body = b"Q" * (RESOLVE_CHUNK_DATA_BYTES * 2)
    frames = encode_resolve_response(request_id="r7", mime="image/png", data=body)
    asm = ResolveAssembler()
    asm.feed(frames[0])  # only the first of two chunks
    assert not asm.complete
    with pytest.raises(ResolveChannelError):
        asm.body()


def test_reorder_raises() -> None:
    body = b"R" * (RESOLVE_CHUNK_DATA_BYTES * 2)
    frames = encode_resolve_response(request_id="r8", mime="image/png", data=body)
    asm = ResolveAssembler()
    with pytest.raises(ResolveChannelError):
        asm.feed(frames[1])  # seq 1 before seq 0


def test_cross_talk_request_id_change_raises() -> None:
    body = b"C" * (RESOLVE_CHUNK_DATA_BYTES * 2)
    a = encode_resolve_response(request_id="rA", mime="image/png", data=body)
    b = encode_resolve_response(request_id="rB", mime="image/png", data=body)
    asm = ResolveAssembler()
    asm.feed(a[0])
    with pytest.raises(ResolveChannelError):
        asm.feed(b[1])  # different request_id mid-message


def test_header_mutation_mid_message_raises() -> None:
    body = b"H" * (RESOLVE_CHUNK_DATA_BYTES * 2)
    frames = encode_resolve_response(request_id="r9", mime="image/png", data=body)
    asm = ResolveAssembler()
    asm.feed(frames[0])
    # Forge a second frame with a different total_bytes.
    forged = _found_frame(
        request_id="r9",
        seq=1,
        chunk_count=2,
        total_bytes=999,
        raw=b"x" * (RESOLVE_CHUNK_DATA_BYTES - (RESOLVE_CHUNK_DATA_BYTES * 2 - 999)),
        mime=None,
    )
    with pytest.raises(ResolveChannelError):
        asm.feed(forged)


def test_bad_base64_raises() -> None:
    payload = {
        "found": True,
        "seq": 0,
        "chunk_count": 1,
        "total_bytes": 4,
        "mime": "image/png",
        "data": "!!!not base64!!!",
    }
    frame = MessageFramer().encode(MessageType.IMAGE_RESOLVE_RESPONSE, payload, "rX")
    asm = ResolveAssembler()
    with pytest.raises(ResolveChannelError):
        asm.feed(frame)


def test_wrong_chunk_size_raises() -> None:
    # Declare 2 chunks of a 2*chunk body but send a too-short first chunk.
    asm = ResolveAssembler()
    bad = _found_frame(
        total_bytes=RESOLVE_CHUNK_DATA_BYTES * 2,
        chunk_count=2,
        raw=b"x" * 10,  # not RESOLVE_CHUNK_DATA_BYTES
    )
    with pytest.raises(ResolveChannelError):
        asm.feed(bad)


def test_placeholder_after_found_chunk_raises() -> None:
    body = b"M" * (RESOLVE_CHUNK_DATA_BYTES * 2)
    frames = encode_resolve_response(request_id="rP", mime="image/png", data=body)
    asm = ResolveAssembler()
    asm.feed(frames[0])
    placeholder = encode_resolve_placeholder(request_id="rP")[0]
    with pytest.raises(ResolveChannelError):
        asm.feed(placeholder)


def test_found_chunk_after_placeholder_raises() -> None:
    asm = ResolveAssembler()
    asm.feed(encode_resolve_placeholder(request_id="rD")[0])
    # placeholder completes the assembler; any further frame raises.
    with pytest.raises(ResolveChannelError):
        asm.feed(_found_frame(request_id="rD", total_bytes=4, raw=b"abcd"))


def test_wrong_type_frame_raises() -> None:
    bad = MessageFramer().encode(MessageType.HEARTBEAT, {}, "rE")
    asm = ResolveAssembler()
    with pytest.raises(ResolveChannelError):
        asm.feed(bad)


def test_found_flag_must_be_bool() -> None:
    payload = {"found": "yes"}
    frame = MessageFramer().encode(MessageType.IMAGE_RESOLVE_RESPONSE, payload, "rF")
    asm = ResolveAssembler()
    with pytest.raises(ResolveChannelError):
        asm.feed(frame)
