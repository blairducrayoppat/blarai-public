"""
IPC framing — PREFERENCE_* verbs (#770 M1).
============================================
Round-trips, fail-closed encode gates, and the pinned-key projection
(defence in depth on BOTH encode and decode — the IMAGE_LIST pattern).
"""

from __future__ import annotations

import pytest

from shared.ipc.protocol import MessageFramer, MessageType

framer = MessageFramer()


class TestWriteRequest:
    def test_round_trip(self) -> None:
        frame = framer.encode_preference_write_request(
            op="remember", body="call me Blair", request_id="r-1"
        )
        msg_type, request_id, payload = framer.decode(frame)
        assert msg_type is MessageType.PREFERENCE_WRITE_REQUEST
        assert request_id == "r-1"
        assert payload == {
            "op": "remember", "body": "call me Blair", "pref_id": "", "token": "",
            "expires": "",
        }

    def test_confirm_carries_token_and_no_body(self) -> None:
        # #770 M2 W1 — the confirm frame carries ONLY the staged-proposal token;
        # the AO commits the staged bytes, so no body crosses (confirm-hop
        # integrity).
        frame = framer.encode_preference_write_request(
            op="confirm", token="0123456789abcdef", request_id="r-c"
        )
        _mt, _rid, payload = framer.decode(frame)
        assert payload == {
            "op": "confirm", "body": "", "pref_id": "", "token": "0123456789abcdef",
            "expires": "",
        }

    def test_remember_carries_expires(self) -> None:
        frame = framer.encode_preference_write_request(
            op="remember", body="answer in French", expires="2026-07-15",
        )
        _mt, _rid, payload = framer.decode(frame)
        assert payload["expires"] == "2026-07-15"

    def test_invalid_op_fail_closed_at_encode(self) -> None:
        with pytest.raises(ValueError, match="Invalid preference-write op"):
            framer.encode_preference_write_request(op="obliterate")

    @pytest.mark.parametrize("op", ["remember", "edit", "delete", "confirm", "dismiss"])
    def test_all_ops_encode(self, op: str) -> None:
        framer.encode_preference_write_request(op=op, body="b", pref_id="a" * 32)


class TestWriteResult:
    def test_round_trip_with_conflict(self) -> None:
        frame = framer.encode_preference_write_result(
            ok=True,
            op="remember",
            status="requires_confirmation",
            pref_id="a" * 32,
            conflict={"pref_id": "a" * 32, "body": "always use metric units",
                      "smuggled": "x"},
            message="confirm needed",
            request_id="r-2",
        )
        decoded = framer.decode_preference_write_result(frame)
        assert decoded["status"] == "requires_confirmation"
        assert decoded["conflict"] == {
            "pref_id": "a" * 32, "body": "always use metric units",
        }  # extra keys projected away at encode

    def test_round_trip_without_conflict(self) -> None:
        frame = framer.encode_preference_write_result(
            ok=True, op="delete", status="deleted", pref_id="b" * 32,
        )
        decoded = framer.decode_preference_write_result(frame)
        assert decoded["ok"] is True
        assert decoded["conflict"] is None

    def test_invalid_status_fail_closed_at_encode(self) -> None:
        with pytest.raises(ValueError, match="Invalid preference-write status"):
            framer.encode_preference_write_result(
                ok=True, op="remember", status="banana"
            )

    def test_decode_rejects_wrong_type(self) -> None:
        frame = framer.encode_preference_list_request(request_id="r-3")
        with pytest.raises(ValueError, match="Expected PREFERENCE_WRITE_RESULT"):
            framer.decode_preference_write_result(frame)


class TestListing:
    def test_round_trip_projects_pinned_keys(self) -> None:
        frame = framer.encode_preference_list_response(
            preferences=[
                {
                    "pref_id": "a" * 32,
                    "type_tag": "address-form",
                    "subject": "",
                    "body": "call me Blair",
                    "created": "2026-07-09T00:00:00+00:00",
                    "updated": "2026-07-09T00:00:00+00:00",
                    "smuggled_field": "nope",
                }
            ],
            request_id="r-4",
        )
        decoded = framer.decode_preference_list_response(frame)
        assert decoded["total"] == 1
        (record,) = decoded["preferences"]
        assert set(record) == set(framer.PREFERENCE_LIST_KEYS)
        assert record["body"] == "call me Blair"

    def test_decode_re_normalises_hostile_records(self) -> None:
        # A hostile AO reply with junk records must decode to the pinned shape.
        raw = framer.encode(
            MessageType.PREFERENCE_LIST_RESPONSE,
            {"preferences": [{"evil": 1}, "not-a-dict", {"body": "x"}],
             "total": 99},
            "r-5",
        )
        decoded = framer.decode_preference_list_response(raw)
        assert all(set(r) == set(framer.PREFERENCE_LIST_KEYS)
                   for r in decoded["preferences"])
        assert len(decoded["preferences"]) == 2  # the non-dict dropped

    def test_empty_listing(self) -> None:
        frame = framer.encode_preference_list_response(preferences=[])
        decoded = framer.decode_preference_list_response(frame)
        assert decoded == {"preferences": [], "total": 0}

    def test_decode_rejects_wrong_type(self) -> None:
        frame = framer.encode_preference_write_result(
            ok=True, op="remember", status="stored"
        )
        with pytest.raises(ValueError, match="Expected PREFERENCE_LIST_RESPONSE"):
            framer.decode_preference_list_response(frame)
