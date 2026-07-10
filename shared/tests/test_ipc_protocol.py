"""
Tests — IPC Message Protocol (P1.6)
======================================
shared/ipc/protocol.py

Groups:
  A. TestMessageType — enum values, membership.
  B. TestAdjudicationRequest — construction, serialization, frozen.
  C. TestAdjudicationResponse — construction, serialization, frozen.
  D. TestMessageFramerEncode — encoding, size enforcement, types.
  E. TestMessageFramerDecode — decoding, error cases, type routing.
  F. TestMessageFramerTyped — encode_request, decode_request,
     encode_response, decode_response, encode_error, encode_heartbeat.
"""

from __future__ import annotations

import json
import pytest

from shared.ipc.protocol import (
    DEFAULT_MAX_MESSAGE_BYTES,
    AdjudicationRequest,
    AdjudicationResponse,
    MessageFramer,
    MessageType,
)


# =====================================================================
# Group A: MessageType
# =====================================================================


class TestMessageType:
    """Enum correctness."""

    def test_all_types_are_strings(self) -> None:
        for mt in MessageType:
            assert isinstance(mt.value, str)

    def test_expected_types_exist(self) -> None:
        names = {mt.name for mt in MessageType}
        assert names == {
            "ADJUDICATION_REQUEST",
            "ADJUDICATION_RESPONSE",
            "ERROR",
            "HEARTBEAT",
            "HANDSHAKE_REQUEST",
            "HANDSHAKE_RESPONSE",
            "PROMPT_REQUEST",
            "STREAM_TOKEN",
            "PGOV_RESULT",
            "GENERATION_COMPLETE",
            # Knowledge-bank ingest (UC-002/UC-003, #655):
            "INGEST_SUBMIT",
            "INGEST_DECISION",
            "INGEST_RESULT",
            # Guest parse channel (UC-003 Stage C, #655) — chunked framing
            # contract in shared/ipc/parse_channel.py:
            "INGEST_PARSE_REQUEST",
            "INGEST_PARSE_RESPONSE",
            # Local generative imaging (UC-010, ADR-033 — DORMANT):
            "IMAGE_GEN_REQUEST",
            "IMAGE_GEN_RESULT",
            # Image display-resolve channel (UC-010/UC-003 WS3, ADR-033 §D) —
            # chunked framing contract in shared/ipc/resolve_channel.py:
            "IMAGE_RESOLVE_REQUEST",
            "IMAGE_RESOLVE_RESPONSE",
            # Generated-image management (UC-010 Phase 1, #667) — metadata-only
            # list / delete / mark-saved over the gateway→AO leg:
            "IMAGE_LIST_REQUEST",
            "IMAGE_LIST_RESPONSE",
            "IMAGE_MANAGE_REQUEST",
            "IMAGE_MANAGE_RESULT",
            # Headless-coding dispatch — the Acceptance-Layer PLAN + EXECUTE steps (#670):
            "PLAN_REQUEST",
            "PLAN_RESULT",
            "EXECUTE_REQUEST",
            "EXECUTE_RESULT",
            # Guest-certified oracle channel (#744, DORMANT) — chunked framing
            # contract in shared/ipc/oracle_channel.py:
            "ORACLE_EXEC_REQUEST",
            "ORACLE_EXEC_RESPONSE",
        }

    def test_value_round_trip(self) -> None:
        for mt in MessageType:
            assert MessageType(mt.value) is mt


# =====================================================================
# Group B: AdjudicationRequest
# =====================================================================


class TestAdjudicationRequest:
    """Request dataclass behaviour."""

    def test_construction(self) -> None:
        req = AdjudicationRequest(car_json='{"a":1}', request_id="r1")
        assert req.car_json == '{"a":1}'
        assert req.request_id == "r1"

    def test_to_dict(self) -> None:
        req = AdjudicationRequest(car_json='{"b":2}', request_id="r2")
        d = req.to_dict()
        assert d == {"car_json": '{"b":2}', "request_id": "r2"}

    def test_from_dict(self) -> None:
        d = {"car_json": '{"c":3}', "request_id": "r3"}
        req = AdjudicationRequest.from_dict(d)
        assert req.car_json == '{"c":3}'
        assert req.request_id == "r3"

    def test_from_dict_missing_keys_defaults_to_empty(self) -> None:
        req = AdjudicationRequest.from_dict({})
        assert req.car_json == ""
        assert req.request_id == ""

    def test_frozen_immutable(self) -> None:
        req = AdjudicationRequest(car_json='{"d":4}', request_id="r4")
        with pytest.raises(AttributeError):
            req.car_json = "changed"  # type: ignore[misc]


# =====================================================================
# Group C: AdjudicationResponse
# =====================================================================


class TestAdjudicationResponse:
    """Response dataclass behaviour."""

    def test_construction_defaults(self) -> None:
        resp = AdjudicationResponse(decision="DENY")
        assert resp.decision == "DENY"
        assert resp.jwt_token == ""
        assert resp.car_hash == ""
        assert resp.request_id == ""
        assert resp.error == ""

    def test_construction_full(self) -> None:
        resp = AdjudicationResponse(
            decision="ALLOW",
            jwt_token="tok123",
            car_hash="abc",
            request_id="r5",
            error="",
        )
        assert resp.decision == "ALLOW"
        assert resp.jwt_token == "tok123"

    def test_to_dict_and_back(self) -> None:
        resp = AdjudicationResponse(
            decision="ESCALATE",
            jwt_token="",
            car_hash="hash",
            request_id="r6",
            error="low confidence",
        )
        d = resp.to_dict()
        rebuilt = AdjudicationResponse.from_dict(d)
        assert rebuilt == resp

    def test_from_dict_missing_keys(self) -> None:
        resp = AdjudicationResponse.from_dict({})
        assert resp.decision == "DENY"  # default fallback

    def test_frozen_immutable(self) -> None:
        resp = AdjudicationResponse(decision="ALLOW")
        with pytest.raises(AttributeError):
            resp.decision = "DENY"  # type: ignore[misc]


# =====================================================================
# Group D: MessageFramer — encoding
# =====================================================================


class TestMessageFramerEncode:
    """Encoding to JSON bytes."""

    def test_encode_produces_bytes(self) -> None:
        framer = MessageFramer()
        data = framer.encode(MessageType.HEARTBEAT, {"status": "alive"}, "hb1")
        assert isinstance(data, bytes)

    def test_encode_json_structure(self) -> None:
        framer = MessageFramer()
        data = framer.encode(
            MessageType.ADJUDICATION_REQUEST,
            {"car_json": "{}", "request_id": "r1"},
            "r1",
        )
        obj = json.loads(data.decode("utf-8"))
        assert obj["type"] == "ADJUDICATION_REQUEST"
        assert obj["request_id"] == "r1"
        assert obj["payload"]["car_json"] == "{}"

    def test_encode_size_limit_exceeded_raises(self) -> None:
        framer = MessageFramer(max_message_bytes=50)
        with pytest.raises(ValueError, match="exceeds limit"):
            framer.encode(
                MessageType.ADJUDICATION_REQUEST,
                {"car_json": "x" * 100},
                "r1",
            )

    def test_encode_size_limit_not_exceeded(self) -> None:
        framer = MessageFramer(max_message_bytes=65_536)
        data = framer.encode(MessageType.HEARTBEAT, {}, "hb")
        assert len(data) < 65_536

    def test_default_max_bytes(self) -> None:
        framer = MessageFramer()
        assert framer.max_message_bytes == DEFAULT_MAX_MESSAGE_BYTES

    def test_custom_max_bytes(self) -> None:
        framer = MessageFramer(max_message_bytes=1024)
        assert framer.max_message_bytes == 1024


# =====================================================================
# Group E: MessageFramer — decoding
# =====================================================================


class TestMessageFramerDecode:
    """Decoding from JSON bytes."""

    def test_decode_valid_envelope(self) -> None:
        framer = MessageFramer()
        raw = json.dumps(
            {
                "type": "HEARTBEAT",
                "request_id": "hb1",
                "payload": {"status": "alive"},
            }
        ).encode("utf-8")
        msg_type, rid, payload = framer.decode(raw)
        assert msg_type == MessageType.HEARTBEAT
        assert rid == "hb1"
        assert payload["status"] == "alive"

    def test_decode_malformed_json_raises(self) -> None:
        framer = MessageFramer()
        with pytest.raises(ValueError, match="Malformed JSON"):
            framer.decode(b"not json at all")

    def test_decode_unknown_type_raises(self) -> None:
        framer = MessageFramer()
        raw = json.dumps({"type": "UNKNOWN_TYPE", "payload": {}}).encode()
        with pytest.raises(ValueError, match="Unknown message type"):
            framer.decode(raw)

    def test_decode_non_dict_envelope_raises(self) -> None:
        framer = MessageFramer()
        with pytest.raises(ValueError, match="must be a JSON object"):
            framer.decode(b'"just a string"')

    def test_decode_non_dict_payload_raises(self) -> None:
        framer = MessageFramer()
        raw = json.dumps(
            {"type": "HEARTBEAT", "payload": "not_a_dict"}
        ).encode()
        with pytest.raises(ValueError, match="Payload must be a dict"):
            framer.decode(raw)

    def test_round_trip_encode_decode(self) -> None:
        framer = MessageFramer()
        original_payload = {"car_json": '{"v":"READ"}', "request_id": "r7"}
        encoded = framer.encode(
            MessageType.ADJUDICATION_REQUEST, original_payload, "r7"
        )
        msg_type, rid, payload = framer.decode(encoded)
        assert msg_type == MessageType.ADJUDICATION_REQUEST
        assert rid == "r7"
        assert payload == original_payload


# =====================================================================
# Group F: MessageFramer — typed convenience methods
# =====================================================================


class TestMessageFramerTyped:
    """Typed encode/decode convenience methods."""

    def test_encode_request(self) -> None:
        framer = MessageFramer()
        req = AdjudicationRequest(car_json='{"v":"READ"}', request_id="r8")
        data = framer.encode_request(req)
        msg_type, rid, payload = framer.decode(data)
        assert msg_type == MessageType.ADJUDICATION_REQUEST
        assert rid == "r8"
        assert payload["car_json"] == '{"v":"READ"}'

    def test_decode_request(self) -> None:
        framer = MessageFramer()
        req = AdjudicationRequest(car_json='{"v":"WRITE"}', request_id="r9")
        data = framer.encode_request(req)
        decoded = framer.decode_request(data)
        assert decoded.car_json == '{"v":"WRITE"}'
        assert decoded.request_id == "r9"

    def test_decode_request_wrong_type_raises(self) -> None:
        framer = MessageFramer()
        data = framer.encode(MessageType.HEARTBEAT, {}, "hb")
        with pytest.raises(ValueError, match="Expected ADJUDICATION_REQUEST"):
            framer.decode_request(data)

    def test_encode_response(self) -> None:
        framer = MessageFramer()
        resp = AdjudicationResponse(
            decision="ALLOW", jwt_token="jwt123", request_id="r10"
        )
        data = framer.encode_response(resp)
        msg_type, rid, payload = framer.decode(data)
        assert msg_type == MessageType.ADJUDICATION_RESPONSE
        assert payload["jwt_token"] == "jwt123"

    def test_decode_response(self) -> None:
        framer = MessageFramer()
        resp = AdjudicationResponse(
            decision="DENY", car_hash="h1", request_id="r11", error="blocked"
        )
        data = framer.encode_response(resp)
        decoded = framer.decode_response(data)
        assert decoded.decision == "DENY"
        assert decoded.car_hash == "h1"
        assert decoded.error == "blocked"

    def test_decode_response_wrong_type_raises(self) -> None:
        framer = MessageFramer()
        data = framer.encode(MessageType.ERROR, {"error": "bad"}, "e1")
        with pytest.raises(ValueError, match="Expected ADJUDICATION_RESPONSE"):
            framer.decode_response(data)

    def test_encode_error(self) -> None:
        framer = MessageFramer()
        data = framer.encode_error("something broke", "e2")
        msg_type, rid, payload = framer.decode(data)
        assert msg_type == MessageType.ERROR
        assert rid == "e2"
        assert payload["error"] == "something broke"

    def test_encode_heartbeat(self) -> None:
        framer = MessageFramer()
        data = framer.encode_heartbeat("hb2")
        msg_type, rid, payload = framer.decode(data)
        assert msg_type == MessageType.HEARTBEAT
        assert rid == "hb2"
        assert payload["status"] == "alive"


# =====================================================================
# Group G: encode_prompt_request — history parameter (FUT-07)
# =====================================================================


class TestEncodePromptRequestHistory:
    """FUT-07 — encode_prompt_request with/without history parameter."""

    def test_no_history_defaults_to_empty_list(self) -> None:
        """Omitting history produces an empty list in the payload."""
        framer = MessageFramer()
        data = framer.encode_prompt_request("sess-1", "Hello")
        _, _, payload = framer.decode(data)
        assert payload["history"] == []

    def test_history_none_defaults_to_empty_list(self) -> None:
        """Explicitly passing history=None produces an empty list."""
        framer = MessageFramer()
        data = framer.encode_prompt_request("sess-1", "Hello", history=None)
        _, _, payload = framer.decode(data)
        assert payload["history"] == []

    def test_history_preserved_in_payload(self) -> None:
        """Supplied history entries survive encode → decode round-trip."""
        framer = MessageFramer()
        history = [
            {"role": "user", "content": "My name is Alice"},
            {"role": "assistant", "content": "Nice to meet you, Alice!"},
        ]
        data = framer.encode_prompt_request("sess-2", "What is my name?", history=history)
        _, _, payload = framer.decode(data)
        assert payload["history"] == history

    def test_decode_round_trip_preserves_all_fields(self) -> None:
        """Full round-trip: session_id, prompt, and history all preserved."""
        framer = MessageFramer()
        history = [{"role": "user", "content": "Hi"}, {"role": "assistant", "content": "Hello"}]
        data = framer.encode_prompt_request(
            "sess-rt", "follow-up", request_id="req-rt", history=history
        )
        msg_type, rid, payload = framer.decode(data)
        assert msg_type == MessageType.PROMPT_REQUEST
        assert rid == "req-rt"
        assert payload["session_id"] == "sess-rt"
        assert payload["prompt"] == "follow-up"
        assert payload["history"] == history

    def test_existing_callers_unaffected_backward_compat(self) -> None:
        """Calls without history parameter still produce valid PROMPT_REQUEST."""
        framer = MessageFramer()
        data = framer.encode_prompt_request("sess-bc", "backward compat prompt", "req-bc")
        msg_type, rid, payload = framer.decode(data)
        assert msg_type == MessageType.PROMPT_REQUEST
        assert rid == "req-bc"
        assert payload["prompt"] == "backward compat prompt"
        assert payload["history"] == []

    def test_large_history_within_64kb_limit(self) -> None:
        """A moderately large history stays within the 64 KB envelope limit."""
        framer = MessageFramer()
        history = [
            {"role": "user" if i % 2 == 0 else "assistant", "content": f"message {i}"}
            for i in range(50)
        ]
        # Must not raise (within 64 KB limit)
        data = framer.encode_prompt_request("sess-large", "summary please", history=history)
        assert len(data) <= 65_536
