"""Sprint 8 EA-4 WI-11: tests for shared.ipc.protocol UI Gateway convenience encoders.

Covers the 6 untested encode_* methods for UI-Gateway message types:
HANDSHAKE_REQUEST, HANDSHAKE_RESPONSE, PROMPT_REQUEST, STREAM_TOKEN,
PGOV_RESULT, GENERATION_COMPLETE.
"""
from __future__ import annotations

import json

import pytest

from shared.ipc.protocol import MessageFramer, MessageType


@pytest.fixture
def framer() -> MessageFramer:
    return MessageFramer()


def _decode_envelope(framer: MessageFramer, raw: bytes) -> tuple[MessageType, str, dict]:
    return framer.decode(raw)


class TestHandshakeRequestEncoder:
    def test_encode_roundtrip(self, framer: MessageFramer) -> None:
        raw = framer.encode_handshake_request(request_id="h-1")
        msg_type, rid, payload = _decode_envelope(framer, raw)
        assert msg_type == MessageType.HANDSHAKE_REQUEST
        assert rid == "h-1"
        assert payload == {"type": "pa_status_check"}


class TestHandshakeResponseEncoder:
    def test_encode_roundtrip(self, framer: MessageFramer) -> None:
        raw = framer.encode_handshake_response(status="operational", request_id="h-2")
        msg_type, rid, payload = _decode_envelope(framer, raw)
        assert msg_type == MessageType.HANDSHAKE_RESPONSE
        assert rid == "h-2"
        assert payload == {"status": "operational"}


class TestPromptRequestEncoder:
    def test_encode_roundtrip(self, framer: MessageFramer) -> None:
        raw = framer.encode_prompt_request(
            session_id="sess-7",
            prompt="hello",
            request_id="p-1",
        )
        msg_type, rid, payload = _decode_envelope(framer, raw)
        assert msg_type == MessageType.PROMPT_REQUEST
        assert rid == "p-1"
        assert payload == {
            "session_id": "sess-7",
            "prompt": "hello",
            "history": [],
            "documents": [],
            "clear_documents": False,
            "documents_trusted_for_tools": False,
            "external_documents": [],
        }


class TestStreamTokenEncoder:
    def test_encode_roundtrip(self, framer: MessageFramer) -> None:
        raw = framer.encode_stream_token(
            token="hi",
            token_index=3,
            is_final=False,
            is_tool_call=False,
            session_id="sess-7",
            request_id="t-1",
            is_thinking=True,
        )
        msg_type, rid, payload = _decode_envelope(framer, raw)
        assert msg_type == MessageType.STREAM_TOKEN
        assert rid == "t-1"
        assert payload == {
            "token": "hi",
            "token_index": 3,
            "is_final": False,
            "is_tool_call": False,
            "session_id": "sess-7",
            "is_thinking": True,
        }


class TestPgovResultEncoder:
    def test_encode_roundtrip(self, framer: MessageFramer) -> None:
        raw = framer.encode_pgov_result(
            approved=True,
            sanitized_text="ok",
            reason_codes=["R1", "R2"],
            request_id="g-1",
        )
        msg_type, rid, payload = _decode_envelope(framer, raw)
        assert msg_type == MessageType.PGOV_RESULT
        assert rid == "g-1"
        assert payload == {
            "approved": True,
            "sanitized_text": "ok",
            "reason_codes": ["R1", "R2"],
        }
        # JSON-round-trippable
        assert json.loads(raw.decode("utf-8"))["payload"]["approved"] is True


class TestGenerationCompleteEncoder:
    def test_encode_roundtrip(self, framer: MessageFramer) -> None:
        raw = framer.encode_generation_complete(request_id="c-1")
        msg_type, rid, payload = _decode_envelope(framer, raw)
        assert msg_type == MessageType.GENERATION_COMPLETE
        assert rid == "c-1"
        assert payload == {"status": "complete"}
