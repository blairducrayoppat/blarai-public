"""
Tests for the guest parse channel (UC-003 Stage C, #655) — the chunked
framing above the 64 KB vsock frame cap.

The load-bearing properties: a body up to the 262,144-byte hard cap crosses
intact in deterministically-framed chunks, every emitted frame individually
fits the 64 KB envelope, and EVERY contract violation (oversize, truncation,
reorder, duplication, header mutation, bad base64, wrong chunk size) fails
closed with nothing silently coerced.
"""

from __future__ import annotations

import base64
import json

import pytest

from shared.ipc.parse_channel import (
    PARSE_BODY_MAX_BYTES,
    PARSE_CHUNK_DATA_BYTES,
    PARSE_MAX_CHUNKS,
    PARSE_REQUEST_ID_MAX_CHARS,
    PARSE_SOURCE_URL_MAX_CHARS,
    ChunkAssembler,
    ParseChannelError,
    decode_parse_request,
    decode_parse_response,
    encode_parse_request,
    encode_parse_response,
)
from shared.ipc.protocol import (
    DEFAULT_MAX_MESSAGE_BYTES,
    MessageFramer,
    MessageType,
)

_FRAMER = MessageFramer()


def _assemble_request(frames: list[bytes]) -> ChunkAssembler:
    assembler = ChunkAssembler(MessageType.INGEST_PARSE_REQUEST)
    for frame in frames:
        assembler.feed(frame)
    return assembler


def _round_trip_request(body: bytes, **kwargs: str) -> tuple[list[bytes], ChunkAssembler]:
    frames = encode_parse_request(request_id="rt-1", html=body, **kwargs)
    return frames, _assemble_request(frames)


def _request_chunk_payload(frame: bytes) -> dict:
    """Decode a frame's chunk payload for surgical mutation tests."""
    msg_type, request_id, payload = _FRAMER.decode(frame)
    assert msg_type is MessageType.INGEST_PARSE_REQUEST
    payload["_request_id"] = request_id
    return payload


def _reframe(payload: dict) -> bytes:
    request_id = payload.pop("_request_id")
    return _FRAMER.encode(MessageType.INGEST_PARSE_REQUEST, payload, request_id)


class TestMessageTypes:
    def test_parse_types_exist(self) -> None:
        assert MessageType.INGEST_PARSE_REQUEST.value == "INGEST_PARSE_REQUEST"
        assert MessageType.INGEST_PARSE_RESPONSE.value == "INGEST_PARSE_RESPONSE"

    def test_parse_types_decode_round_trip(self) -> None:
        raw = _FRAMER.encode(MessageType.INGEST_PARSE_REQUEST, {"seq": 0}, "r1")
        msg_type, request_id, payload = _FRAMER.decode(raw)
        assert msg_type is MessageType.INGEST_PARSE_REQUEST
        assert request_id == "r1"
        assert payload == {"seq": 0}


class TestRequestRoundTrip:
    @pytest.mark.parametrize(
        ("size", "expected_chunks"),
        [
            (1, 1),  # minimum body
            (PARSE_CHUNK_DATA_BYTES, 1),  # exactly one full chunk
            (PARSE_CHUNK_DATA_BYTES + 1, 2),  # first split point
            (65_536, 2),  # the 64 KB frame-cap boundary
            (94_208, 3),  # 92 KB — realistic article page
            (PARSE_BODY_MAX_BYTES, 6),  # the 262,144 hard cap (4+ frames)
        ],
        ids=["1B", "one-chunk", "split-point", "64KB", "92KB", "cap-262144"],
    )
    def test_body_crosses_intact(self, size: int, expected_chunks: int) -> None:
        body = bytes(i % 251 for i in range(size))  # non-trivial, non-repeating
        frames, assembler = _round_trip_request(body, source_url="https://example.org/a")
        assert len(frames) == expected_chunks
        assert assembler.complete is True
        request = decode_parse_request(assembler)
        assert request.html == body  # byte-identical across the channel
        assert request.source_url == "https://example.org/a"
        assert request.request_id == "rt-1"

    def test_max_chunks_constant_matches_cap(self) -> None:
        assert PARSE_MAX_CHUNKS == -(-PARSE_BODY_MAX_BYTES // PARSE_CHUNK_DATA_BYTES)
        assert PARSE_MAX_CHUNKS >= 4  # the cap genuinely needs 4+ frames

    def test_every_frame_fits_the_64kb_envelope(self) -> None:
        """The whole point of the layer: at the body cap WITH a maximal
        source_url, every individual frame still fits the transport cap."""
        frames = encode_parse_request(
            request_id="rt-cap",
            html=b"x" * PARSE_BODY_MAX_BYTES,
            source_url="https://example.org/" + "p" * (PARSE_SOURCE_URL_MAX_CHARS - 20),
        )
        for frame in frames:
            assert len(frame) <= DEFAULT_MAX_MESSAGE_BYTES

    def test_deterministic_framing(self) -> None:
        body = b"deterministic" * 9000  # ~117 KB, 3 chunks
        first = encode_parse_request(request_id="d-1", html=body)
        second = encode_parse_request(request_id="d-1", html=body)
        assert first == second

    def test_request_id_at_cap_accepted(self) -> None:
        """Exactly PARSE_REQUEST_ID_MAX_CHARS is valid — the cap is an
        inclusive bound, not an off-by-one."""
        rid = "r" * PARSE_REQUEST_ID_MAX_CHARS
        frames = encode_parse_request(request_id=rid, html=b"x")
        assembler = _assemble_request(frames)
        assert decode_parse_request(assembler).request_id == rid


class TestEncodeFailClosed:
    def test_cap_plus_one_rejected_at_encode(self) -> None:
        with pytest.raises(ParseChannelError, match="exceeds the hard cap"):
            encode_parse_request(
                request_id="r", html=b"x" * (PARSE_BODY_MAX_BYTES + 1)
            )

    def test_empty_body_rejected(self) -> None:
        with pytest.raises(ParseChannelError, match="empty"):
            encode_parse_request(request_id="r", html=b"")

    @pytest.mark.parametrize("bad_rid", ["", "   "])
    def test_missing_request_id_rejected(self, bad_rid: str) -> None:
        with pytest.raises(ParseChannelError, match="request_id"):
            encode_parse_request(request_id=bad_rid, html=b"x")

    def test_oversize_source_url_rejected(self) -> None:
        with pytest.raises(ParseChannelError, match="source_url"):
            encode_parse_request(
                request_id="r",
                html=b"x",
                source_url="u" * (PARSE_SOURCE_URL_MAX_CHARS + 1),
            )

    @pytest.mark.parametrize("bad_url", ["https://exämple.org/", "https://e.org/\n"])
    def test_non_printable_ascii_source_url_rejected(self, bad_url: str) -> None:
        with pytest.raises(ParseChannelError, match="printable ASCII"):
            encode_parse_request(request_id="r", html=b"x", source_url=bad_url)

    def test_over_cap_request_id_rejected_at_encode(self) -> None:
        with pytest.raises(ParseChannelError, match="request_id of .* exceeds"):
            encode_parse_request(
                request_id="r" * (PARSE_REQUEST_ID_MAX_CHARS + 1), html=b"x"
            )


class TestAssemblerFailClosed:
    """Truncation / reorder / oversize / mutation — every path rejects."""

    def _frames(self, size: int = PARSE_CHUNK_DATA_BYTES * 2 + 10) -> list[bytes]:
        return encode_parse_request(
            request_id="fc-1", html=bytes(i % 256 for i in range(size))
        )

    def test_truncation_detectable_and_body_raises(self) -> None:
        frames = self._frames()
        assembler = ChunkAssembler(MessageType.INGEST_PARSE_REQUEST)
        for frame in frames[:-1]:  # final chunk never arrives
            assert assembler.feed(frame) is False
        assert assembler.complete is False
        with pytest.raises(ParseChannelError, match="incomplete"):
            assembler.body()

    def test_missing_chunk_rejected(self) -> None:
        frames = self._frames()
        assembler = ChunkAssembler(MessageType.INGEST_PARSE_REQUEST)
        assembler.feed(frames[0])
        with pytest.raises(ParseChannelError, match="out of order"):
            assembler.feed(frames[2])  # chunk 1 skipped

    def test_out_of_order_first_chunk_rejected(self) -> None:
        frames = self._frames()
        assembler = ChunkAssembler(MessageType.INGEST_PARSE_REQUEST)
        with pytest.raises(ParseChannelError, match="out of order"):
            assembler.feed(frames[1])  # arrives before chunk 0

    def test_duplicate_chunk_rejected(self) -> None:
        frames = self._frames()
        assembler = ChunkAssembler(MessageType.INGEST_PARSE_REQUEST)
        assembler.feed(frames[0])
        with pytest.raises(ParseChannelError, match="out of order"):
            assembler.feed(frames[0])

    def test_frame_after_completion_rejected(self) -> None:
        frames = encode_parse_request(request_id="r", html=b"tiny")
        assembler = _assemble_request(frames)
        assert assembler.complete is True
        with pytest.raises(ParseChannelError, match="after message completion"):
            assembler.feed(frames[0])

    def test_oversize_declaration_rejected_before_buffering(self) -> None:
        payload = {
            "seq": 0,
            "chunk_count": 7,
            "total_bytes": PARSE_BODY_MAX_BYTES + 1,
            "data": base64.b64encode(b"x").decode("ascii"),
            "meta": {},
        }
        frame = _FRAMER.encode(MessageType.INGEST_PARSE_REQUEST, payload, "big-1")
        assembler = ChunkAssembler(MessageType.INGEST_PARSE_REQUEST)
        with pytest.raises(ParseChannelError, match="rejected before buffering"):
            assembler.feed(frame)
        # request_id was recorded BEFORE rejection — the service can still
        # address an error response at the violator.
        assert assembler.request_id == "big-1"

    def test_wrong_chunk_count_rejected(self) -> None:
        frames = self._frames()
        payload = _request_chunk_payload(frames[0])
        payload["chunk_count"] = payload["chunk_count"] + 1
        assembler = ChunkAssembler(MessageType.INGEST_PARSE_REQUEST)
        with pytest.raises(ParseChannelError, match="one valid framing"):
            assembler.feed(_reframe(payload))

    def test_header_mutation_mid_message_rejected(self) -> None:
        frames = self._frames()
        assembler = ChunkAssembler(MessageType.INGEST_PARSE_REQUEST)
        assembler.feed(frames[0])
        payload = _request_chunk_payload(frames[1])
        payload["total_bytes"] = payload["total_bytes"] - 1
        with pytest.raises(ParseChannelError, match="mutated mid-message"):
            assembler.feed(_reframe(payload))

    def test_request_id_change_mid_message_rejected(self) -> None:
        frames = self._frames()
        assembler = ChunkAssembler(MessageType.INGEST_PARSE_REQUEST)
        assembler.feed(frames[0])
        payload = _request_chunk_payload(frames[1])
        payload["_request_id"] = "someone-else"
        with pytest.raises(ParseChannelError, match="cross-talk"):
            assembler.feed(_reframe(payload))

    def test_invalid_base64_rejected(self) -> None:
        frames = self._frames()
        payload = _request_chunk_payload(frames[0])
        payload["data"] = "not!!valid@@base64"
        assembler = ChunkAssembler(MessageType.INGEST_PARSE_REQUEST)
        with pytest.raises(ParseChannelError, match="invalid base64"):
            assembler.feed(_reframe(payload))

    def test_wrong_chunk_size_rejected(self) -> None:
        payload = {
            "seq": 0,
            "chunk_count": 1,
            "total_bytes": 2,
            "data": base64.b64encode(b"x").decode("ascii"),  # 1 byte, claims 2
            "meta": {},
        }
        frame = _FRAMER.encode(MessageType.INGEST_PARSE_REQUEST, payload, "ws-1")
        assembler = ChunkAssembler(MessageType.INGEST_PARSE_REQUEST)
        with pytest.raises(ParseChannelError, match="exactly"):
            assembler.feed(frame)

    def test_meta_on_later_chunk_rejected(self) -> None:
        frames = self._frames()
        assembler = ChunkAssembler(MessageType.INGEST_PARSE_REQUEST)
        assembler.feed(frames[0])
        payload = _request_chunk_payload(frames[1])
        payload["meta"] = {"sneak": True}
        with pytest.raises(ParseChannelError, match="only valid on chunk 0"):
            assembler.feed(_reframe(payload))

    def test_wrong_message_type_rejected(self) -> None:
        frames = self._frames()
        assembler = ChunkAssembler(MessageType.INGEST_PARSE_RESPONSE)
        with pytest.raises(ParseChannelError, match="expected INGEST_PARSE_RESPONSE"):
            assembler.feed(frames[0])

    def test_missing_request_id_rejected(self) -> None:
        payload = {
            "seq": 0,
            "chunk_count": 1,
            "total_bytes": 1,
            "data": base64.b64encode(b"x").decode("ascii"),
            "meta": {},
        }
        frame = _FRAMER.encode(MessageType.INGEST_PARSE_REQUEST, payload, "")
        assembler = ChunkAssembler(MessageType.INGEST_PARSE_REQUEST)
        with pytest.raises(ParseChannelError, match="request_id"):
            assembler.feed(frame)

    def test_over_cap_request_id_rejected_on_first_frame(self) -> None:
        """An over-long correlation id dies at assembly time on the FIRST
        frame — and is NEVER recorded, so a service has nothing to echo.
        (The pre-cap failure mode: a ~65,200-char id fit the incoming 64 KB
        frame but made the ECHOED error-response envelope unencodable —
        #655 adversarial review.)"""
        payload = {
            "seq": 0,
            "chunk_count": 1,
            "total_bytes": 1,
            "data": base64.b64encode(b"x").decode("ascii"),
            "meta": {},
        }
        frame = _FRAMER.encode(
            MessageType.INGEST_PARSE_REQUEST,
            payload,
            "r" * (PARSE_REQUEST_ID_MAX_CHARS + 1),
        )
        assembler = ChunkAssembler(MessageType.INGEST_PARSE_REQUEST)
        with pytest.raises(ParseChannelError, match="request_id of .* exceeds"):
            assembler.feed(frame)
        assert assembler.request_id == ""  # nothing recorded, nothing to echo

    def test_non_parse_type_assembler_rejected(self) -> None:
        with pytest.raises(ParseChannelError, match="not a parse-channel"):
            ChunkAssembler(MessageType.HEARTBEAT)


class TestResponseRoundTrip:
    _FIELDS = dict(
        status="quarantined",
        text="Cleaned article text — café, 東京, and a code block.\n\nSecond para.",
        title="A Title",
        byline="A. Writer",
        published_date="2026-06-11",
        word_count=12,
        confidence=0.375,
        reasons=("LOW_TEXT_LENGTH",),
    )

    def _round_trip(self, **overrides: object) -> object:
        fields = {**self._FIELDS, **overrides}
        frames = encode_parse_response(request_id="resp-1", **fields)  # type: ignore[arg-type]
        assembler = ChunkAssembler(MessageType.INGEST_PARSE_RESPONSE)
        for frame in frames:
            assembler.feed(frame)
        return decode_parse_response(assembler)

    def test_all_fields_round_trip(self) -> None:
        response = self._round_trip()
        assert response.request_id == "resp-1"
        assert response.status == "quarantined"
        assert response.text == self._FIELDS["text"]  # unicode survives intact
        assert response.title == "A Title"
        assert response.byline == "A. Writer"
        assert response.published_date == "2026-06-11"
        assert response.word_count == 12
        assert response.confidence == pytest.approx(0.375)
        assert response.reasons == ("LOW_TEXT_LENGTH",)
        assert response.error_code == ""

    def test_none_metadata_round_trips_as_none(self) -> None:
        response = self._round_trip(title=None, byline=None, published_date=None)
        assert response.title is None
        assert response.byline is None
        assert response.published_date is None

    def test_large_text_spans_multiple_frames(self) -> None:
        text = ("A long paragraph of cleaned text. " * 4000).strip()  # ~136 KB
        frames = encode_parse_response(
            request_id="resp-big",
            status="clean",
            text=text,
            word_count=len(text.split()),
            confidence=1.0,
        )
        assert len(frames) >= 3
        assembler = ChunkAssembler(MessageType.INGEST_PARSE_RESPONSE)
        for frame in frames:
            assembler.feed(frame)
        response = decode_parse_response(assembler)
        assert response.text == text

    def test_error_response_round_trip(self) -> None:
        response = self._round_trip(
            status="error",
            text="",
            title=None,
            byline=None,
            published_date=None,
            word_count=0,
            confidence=0.0,
            reasons=(),
            error_code="PARSE_CHANNEL_VIOLATION",
            message="declared total_bytes 999999 outside bounds",
        )
        assert response.status == "error"
        assert response.error_code == "PARSE_CHANNEL_VIOLATION"
        assert response.text == ""

    def test_unknown_status_rejected_at_encode(self) -> None:
        with pytest.raises(ParseChannelError, match="closed vocabulary"):
            self._round_trip(status="maybe")

    def test_error_status_requires_error_code(self) -> None:
        with pytest.raises(ParseChannelError, match="error_code"):
            self._round_trip(status="error", reasons=())

    def test_error_code_forbidden_on_non_error(self) -> None:
        with pytest.raises(ParseChannelError, match="only valid with status"):
            self._round_trip(error_code="SOMETHING")

    @pytest.mark.parametrize("bad", [-0.1, 1.1])
    def test_confidence_bounds_enforced_at_encode(self, bad: float) -> None:
        with pytest.raises(ParseChannelError, match="confidence"):
            self._round_trip(confidence=bad)

    def test_negative_word_count_rejected_at_encode(self) -> None:
        with pytest.raises(ParseChannelError, match="word_count"):
            self._round_trip(word_count=-1)

    def test_oversize_response_body_rejected_at_encode(self) -> None:
        with pytest.raises(ParseChannelError, match="exceeds the hard cap"):
            encode_parse_response(
                request_id="r",
                status="clean",
                text="x" * (PARSE_BODY_MAX_BYTES + 1),
                confidence=1.0,
            )


class TestDecodeFailClosed:
    def _response_assembler_with_body(self, doc: object) -> ChunkAssembler:
        body = json.dumps(doc, separators=(",", ":")).encode("utf-8")
        payload = {
            "seq": 0,
            "chunk_count": 1,
            "total_bytes": len(body),
            "data": base64.b64encode(body).decode("ascii"),
            "meta": {},
        }
        frame = _FRAMER.encode(MessageType.INGEST_PARSE_RESPONSE, payload, "d-1")
        assembler = ChunkAssembler(MessageType.INGEST_PARSE_RESPONSE)
        assembler.feed(frame)
        return assembler

    def test_decode_request_rejects_response_assembler(self) -> None:
        assembler = ChunkAssembler(MessageType.INGEST_PARSE_RESPONSE)
        with pytest.raises(ParseChannelError, match="INGEST_PARSE_REQUEST"):
            decode_parse_request(assembler)

    def test_decode_response_rejects_request_assembler(self) -> None:
        assembler = ChunkAssembler(MessageType.INGEST_PARSE_REQUEST)
        with pytest.raises(ParseChannelError, match="INGEST_PARSE_RESPONSE"):
            decode_parse_response(assembler)

    def test_decode_incomplete_request_raises(self) -> None:
        frames = encode_parse_request(
            request_id="r", html=b"z" * (PARSE_CHUNK_DATA_BYTES + 1)
        )
        assembler = ChunkAssembler(MessageType.INGEST_PARSE_REQUEST)
        assembler.feed(frames[0])
        with pytest.raises(ParseChannelError, match="incomplete"):
            decode_parse_request(assembler)

    def test_non_json_response_body_rejected(self) -> None:
        body = b"\xff\xfenot json"
        payload = {
            "seq": 0,
            "chunk_count": 1,
            "total_bytes": len(body),
            "data": base64.b64encode(body).decode("ascii"),
            "meta": {},
        }
        frame = _FRAMER.encode(MessageType.INGEST_PARSE_RESPONSE, payload, "d-2")
        assembler = ChunkAssembler(MessageType.INGEST_PARSE_RESPONSE)
        assembler.feed(frame)
        with pytest.raises(ParseChannelError, match="UTF-8 JSON"):
            decode_parse_response(assembler)

    def test_unknown_status_rejected_at_decode(self) -> None:
        assembler = self._response_assembler_with_body(
            {"status": "trusted", "text": "", "word_count": 0,
             "confidence": 0.0, "reasons": []}
        )
        with pytest.raises(ParseChannelError, match="status"):
            decode_parse_response(assembler)

    def test_malformed_fields_rejected_at_decode(self) -> None:
        assembler = self._response_assembler_with_body(
            {"status": "clean", "text": "ok", "word_count": True,
             "confidence": 0.5, "reasons": []}
        )
        with pytest.raises(ParseChannelError, match="word_count"):
            decode_parse_response(assembler)

    def test_error_status_without_code_rejected_at_decode(self) -> None:
        assembler = self._response_assembler_with_body(
            {"status": "error", "text": "", "word_count": 0,
             "confidence": 0.0, "reasons": [], "error_code": ""}
        )
        with pytest.raises(ParseChannelError, match="error_code"):
            decode_parse_response(assembler)
