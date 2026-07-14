"""
Typed-guard locks for the IPC decode trust boundary (#803).

Every MessageFramer payload decoder documents ``Raises: ValueError`` — but
the historical bare ``int()``/``str()``/``bool()`` coercions raised
``TypeError`` on containers (a contract lie any ``except ValueError``-only
caller would crash on) or, worse, swallowed them (``str(["x"])`` →
``"['x']"`` flowing on as "valid").  These locks pin the #803 contract for
every guarded site, in both directions:

  - MALFORMED: a present-but-mistyped field fails the decode with the
    documented ``ValueError`` and the deterministic content-free fingerprint
    (field name + expected/received TYPE names — never the value, which may
    carry operator content).
  - WELL-FORMED: a well-formed frame decodes to the exact same view as
    before the guards (full dict equality), and ABSENT fields keep their
    documented defaults — missing-key tolerance is a locked contract.
"""

from __future__ import annotations

from typing import Any

import pytest

from shared.ipc.protocol import (
    MessageFramer,
    MessageType,
    ensure_int,
    require_bool,
    require_dict,
    require_int,
    require_list,
    require_str,
    require_str_list,
)


@pytest.fixture()
def framer() -> MessageFramer:
    return MessageFramer()


def _frame(
    framer: MessageFramer, msg_type: MessageType, payload: dict[str, Any]
) -> bytes:
    """Craft an arbitrary (possibly malformed) payload frame via generic encode."""
    return framer.encode(msg_type, payload, "r-guard")


# ─────────────────────────────────────────────────────────────────
# Guard primitives
# ─────────────────────────────────────────────────────────────────


class TestGuardPrimitives:
    """Direct unit locks on the require_*/ensure_int helpers."""

    # require_int -----------------------------------------------------
    def test_require_int_missing_returns_default(self) -> None:
        assert require_int({}, "n", 7) == 7

    def test_require_int_valid(self) -> None:
        assert require_int({"n": 0}, "n", 7) == 0

    @pytest.mark.parametrize("bad", [["x"], {"a": 1}, "5", 5.0, None, True])
    def test_require_int_mistyped_raises(self, bad: Any) -> None:
        with pytest.raises(ValueError, match="'n' must be int"):
            require_int({"n": bad}, "n")

    # require_str -----------------------------------------------------
    def test_require_str_missing_returns_default(self) -> None:
        assert require_str({}, "s", "d") == "d"

    def test_require_str_valid(self) -> None:
        assert require_str({"s": ""}, "s", "d") == ""

    @pytest.mark.parametrize("bad", [["x"], {"a": 1}, 5, 5.0, None, True])
    def test_require_str_mistyped_raises(self, bad: Any) -> None:
        with pytest.raises(ValueError, match="'s' must be str"):
            require_str({"s": bad}, "s")

    # require_bool ----------------------------------------------------
    def test_require_bool_missing_returns_default(self) -> None:
        assert require_bool({}, "b") is False
        assert require_bool({}, "b", True) is True

    def test_require_bool_valid(self) -> None:
        assert require_bool({"b": True}, "b") is True
        assert require_bool({"b": False}, "b", True) is False

    @pytest.mark.parametrize("bad", [[1], {"a": 1}, "true", 1, 0, None])
    def test_require_bool_mistyped_raises(self, bad: Any) -> None:
        """A truthy container must FAIL, never flow on as True."""
        with pytest.raises(ValueError, match="'b' must be bool"):
            require_bool({"b": bad}, "b")

    # require_list ----------------------------------------------------
    def test_require_list_missing_returns_fresh_empty(self) -> None:
        first = require_list({}, "l")
        first.append("polluted")
        assert require_list({}, "l") == []

    def test_require_list_valid(self) -> None:
        assert require_list({"l": [1, "a"]}, "l") == [1, "a"]

    @pytest.mark.parametrize("bad", ["abc", {"a": 1}, 5, None, True])
    def test_require_list_mistyped_raises(self, bad: Any) -> None:
        """A str must not ``list()``-explode into characters."""
        with pytest.raises(ValueError, match="'l' must be list"):
            require_list({"l": bad}, "l")

    # require_dict ----------------------------------------------------
    def test_require_dict_missing_returns_fresh_empty(self) -> None:
        first = require_dict({}, "d")
        first["polluted"] = 1
        assert require_dict({}, "d") == {}

    def test_require_dict_valid(self) -> None:
        assert require_dict({"d": {"k": 1}}, "d") == {"k": 1}

    @pytest.mark.parametrize("bad", [["ab", "cd"], "x", 5, None, True])
    def test_require_dict_mistyped_raises(self, bad: Any) -> None:
        with pytest.raises(ValueError, match="'d' must be dict"):
            require_dict({"d": bad}, "d")

    # require_str_list ------------------------------------------------
    def test_require_str_list_valid_and_missing(self) -> None:
        assert require_str_list({"r": ["a", "b"]}, "r") == ["a", "b"]
        assert require_str_list({}, "r") == []

    def test_require_str_list_non_list_raises(self) -> None:
        with pytest.raises(ValueError, match="'r' must be list"):
            require_str_list({"r": "ABC"}, "r")

    def test_require_str_list_mistyped_element_raises_with_index(self) -> None:
        with pytest.raises(ValueError, match=r"'r\[1\]' must be str"):
            require_str_list({"r": ["a", 5]}, "r")

    # ensure_int ------------------------------------------------------
    def test_ensure_int_valid(self) -> None:
        assert ensure_int(5, "total") == 5

    @pytest.mark.parametrize("bad", [True, "5", [5], None])
    def test_ensure_int_mistyped_raises(self, bad: Any) -> None:
        with pytest.raises(ValueError, match="'total' must be int"):
            ensure_int(bad, "total")

    # Fingerprint discipline ------------------------------------------
    def test_error_is_content_free(self) -> None:
        """The fingerprint carries field + TYPE names, NEVER the value —
        a malformed field may carry operator content and the message flows
        into logs/error labels (privacy mandate)."""
        with pytest.raises(ValueError) as excinfo:
            require_str({"message": ["OPERATOR-SECRET"]}, "message")
        text = str(excinfo.value)
        assert "'message'" in text
        assert "str" in text and "list" in text
        assert "OPERATOR-SECRET" not in text


# ─────────────────────────────────────────────────────────────────
# INGEST_RESULT (the ticket's primary anchor)
# ─────────────────────────────────────────────────────────────────


class TestIngestResultGuards:
    def test_container_chunk_count_raises_valueerror(
        self, framer: MessageFramer
    ) -> None:
        """The anchored defect: bare ``int()`` raised TypeError on a container,
        breaking the documented ``Raises: ValueError`` contract."""
        raw = _frame(framer, MessageType.INGEST_RESULT, {"chunk_count": ["x"]})
        with pytest.raises(ValueError, match="'chunk_count' must be int"):
            framer.decode_ingest_result(raw)

    def test_numeric_string_chunk_count_raises(self, framer: MessageFramer) -> None:
        raw = _frame(framer, MessageType.INGEST_RESULT, {"chunk_count": "7"})
        with pytest.raises(ValueError, match="'chunk_count' must be int"):
            framer.decode_ingest_result(raw)

    def test_container_message_raises_not_swallowed(
        self, framer: MessageFramer
    ) -> None:
        """The ticket's swallow example: ``str(["x"])`` used to flow on as "['x']"."""
        raw = _frame(framer, MessageType.INGEST_RESULT, {"message": ["x"]})
        with pytest.raises(ValueError, match="'message' must be str"):
            framer.decode_ingest_result(raw)

    def test_container_ok_raises_not_truthy(self, framer: MessageFramer) -> None:
        raw = _frame(framer, MessageType.INGEST_RESULT, {"ok": [1]})
        with pytest.raises(ValueError, match="'ok' must be bool"):
            framer.decode_ingest_result(raw)

    def test_well_formed_decodes_identically(self, framer: MessageFramer) -> None:
        raw = framer.encode_ingest_result(
            ok=True, doc_uuid="d-1", state="approved", chunk_count=3,
            error_code="", message="", request_id="r",
        )
        assert framer.decode_ingest_result(raw) == {
            "ok": True, "doc_uuid": "d-1", "state": "approved",
            "chunk_count": 3, "error_code": "", "message": "",
        }

    def test_missing_fields_keep_documented_defaults(
        self, framer: MessageFramer
    ) -> None:
        raw = _frame(framer, MessageType.INGEST_RESULT, {})
        assert framer.decode_ingest_result(raw) == {
            "ok": False, "doc_uuid": "", "state": "error",
            "chunk_count": 0, "error_code": "", "message": "",
        }


# ─────────────────────────────────────────────────────────────────
# PLAN_REQUEST / PLAN_RESULT (twins)
# ─────────────────────────────────────────────────────────────────


class TestPlanRequestGuards:
    def test_container_repo_raises(self, framer: MessageFramer) -> None:
        raw = _frame(framer, MessageType.PLAN_REQUEST, {"repo": ["r"], "goal": "g"})
        with pytest.raises(ValueError, match="'repo' must be str"):
            framer.decode_plan_request(raw)

    def test_well_formed_and_defaults(self, framer: MessageFramer) -> None:
        raw = framer.encode_plan_request(repo="blarai", goal="fix", request_id="r")
        assert framer.decode_plan_request(raw) == {"repo": "blarai", "goal": "fix"}
        empty = _frame(framer, MessageType.PLAN_REQUEST, {})
        assert framer.decode_plan_request(empty) == {"repo": "", "goal": ""}


class TestPlanResultGuards:
    def test_str_tasks_raises_not_char_exploded(self, framer: MessageFramer) -> None:
        """``list("abc")`` used to silently become ``['a', 'b', 'c']``."""
        raw = _frame(framer, MessageType.PLAN_RESULT, {"tasks": "abc"})
        with pytest.raises(ValueError, match="'tasks' must be list"):
            framer.decode_plan_result(raw)

    def test_list_criteria_raises(self, framer: MessageFramer) -> None:
        raw = _frame(framer, MessageType.PLAN_RESULT, {"criteria": ["a", "b"]})
        with pytest.raises(ValueError, match="'criteria' must be dict"):
            framer.decode_plan_result(raw)

    def test_container_fell_back_raises(self, framer: MessageFramer) -> None:
        raw = _frame(framer, MessageType.PLAN_RESULT, {"fell_back": ["y"]})
        with pytest.raises(ValueError, match="'fell_back' must be bool"):
            framer.decode_plan_result(raw)

    def test_well_formed_and_defaults(self, framer: MessageFramer) -> None:
        tasks = [{"repo": "blarai", "task": "t", "prompt": "p"}]
        criteria = {"goal": "g", "criteria": ["c1"]}
        raw = framer.encode_plan_result(
            ok=True, message="m", fell_back=False, tasks=tasks,
            criteria=criteria, request_id="r",
        )
        assert framer.decode_plan_result(raw) == {
            "ok": True, "message": "m", "fell_back": False,
            "tasks": tasks, "criteria": criteria,
            "questions": [],  # #819 additive
            "revision": [],  # #820 additive
        }
        empty = _frame(framer, MessageType.PLAN_RESULT, {})
        assert framer.decode_plan_result(empty) == {
            "ok": False, "message": "", "fell_back": False,
            "tasks": [], "criteria": {}, "questions": [], "revision": [],
        }


# ─────────────────────────────────────────────────────────────────
# EXECUTE_REQUEST / EXECUTE_RESULT (twins)
# ─────────────────────────────────────────────────────────────────


class TestExecuteRequestGuards:
    def test_int_session_id_raises(self, framer: MessageFramer) -> None:
        raw = _frame(framer, MessageType.EXECUTE_REQUEST, {"session_id": 5})
        with pytest.raises(ValueError, match="'session_id' must be str"):
            framer.decode_execute_request(raw)

    def test_dict_tasks_raises(self, framer: MessageFramer) -> None:
        raw = _frame(framer, MessageType.EXECUTE_REQUEST, {"tasks": {"a": 1}})
        with pytest.raises(ValueError, match="'tasks' must be list"):
            framer.decode_execute_request(raw)

    def test_well_formed_and_defaults(self, framer: MessageFramer) -> None:
        raw = framer.encode_execute_request(
            session_id="s", run_id="run-1", tasks=[{"t": 1}], request_id="r",
        )
        assert framer.decode_execute_request(raw) == {
            "session_id": "s", "run_id": "run-1", "tasks": [{"t": 1}],
        }
        empty = _frame(framer, MessageType.EXECUTE_REQUEST, {})
        assert framer.decode_execute_request(empty) == {
            "session_id": "", "run_id": "", "tasks": [],
        }


class TestExecuteResultGuards:
    def test_str_ok_raises(self, framer: MessageFramer) -> None:
        raw = _frame(framer, MessageType.EXECUTE_RESULT, {"ok": "true"})
        with pytest.raises(ValueError, match="'ok' must be bool"):
            framer.decode_execute_result(raw)

    def test_container_run_id_raises(self, framer: MessageFramer) -> None:
        raw = _frame(framer, MessageType.EXECUTE_RESULT, {"run_id": ["r"]})
        with pytest.raises(ValueError, match="'run_id' must be str"):
            framer.decode_execute_result(raw)

    def test_well_formed_and_defaults(self, framer: MessageFramer) -> None:
        raw = framer.encode_execute_result(
            ok=True, run_id="run-9", message="queued", request_id="r",
        )
        assert framer.decode_execute_result(raw) == {
            "ok": True, "run_id": "run-9", "message": "queued",
        }
        empty = _frame(framer, MessageType.EXECUTE_RESULT, {})
        assert framer.decode_execute_result(empty) == {
            "ok": False, "run_id": "", "message": "",
        }


# ─────────────────────────────────────────────────────────────────
# IMAGE_GEN_RESULT (twin)
# ─────────────────────────────────────────────────────────────────


class TestImageGenResultGuards:
    def test_container_image_ref_raises(self, framer: MessageFramer) -> None:
        raw = _frame(
            framer, MessageType.IMAGE_GEN_RESULT, {"image_ref": ["blarai-img://x"]}
        )
        with pytest.raises(ValueError, match="'image_ref' must be str"):
            framer.decode_image_gen_result(raw)

    def test_container_ok_raises(self, framer: MessageFramer) -> None:
        raw = _frame(framer, MessageType.IMAGE_GEN_RESULT, {"ok": [1]})
        with pytest.raises(ValueError, match="'ok' must be bool"):
            framer.decode_image_gen_result(raw)

    def test_well_formed_and_defaults(self, framer: MessageFramer) -> None:
        raw = framer.encode_image_gen_result(
            ok=True, image_ref="blarai-img://" + "a" * 32, mime="image/png",
            request_id="r",
        )
        assert framer.decode_image_gen_result(raw) == {
            "ok": True, "image_ref": "blarai-img://" + "a" * 32,
            "mime": "image/png", "error_code": "", "message": "",
        }
        empty = _frame(framer, MessageType.IMAGE_GEN_RESULT, {})
        assert framer.decode_image_gen_result(empty) == {
            "ok": False, "image_ref": "", "mime": "", "error_code": "",
            "message": "",
        }


# ─────────────────────────────────────────────────────────────────
# IMAGE_LIST encode + decode (the :1135/:1142/:1171/:1178 anchors)
# ─────────────────────────────────────────────────────────────────


def _image_record(**overrides: Any) -> dict[str, Any]:
    record: dict[str, Any] = {
        "image_id": "a" * 32, "session_id": "s1", "mime": "image/png",
        "byte_size": 2048, "saved": False,
        "created_at": "2026-07-11T00:00:00+00:00",
    }
    record.update(overrides)
    return record


class TestImageListEncodeGuards:
    """Encode-side anchors: a malformed record fails the encode with the
    deterministic ValueError — never a raw TypeError, never a silently
    minted number (the store already types byte_size int, None→0)."""

    @pytest.mark.parametrize("bad", [[1], {"n": 1}, "123", None, True])
    def test_mistyped_byte_size_raises(
        self, framer: MessageFramer, bad: Any
    ) -> None:
        with pytest.raises(ValueError, match="'byte_size' must be int"):
            framer.encode_image_list_response(
                images=[_image_record(byte_size=bad)], total=1, request_id="r",
            )

    @pytest.mark.parametrize("bad", [[5], "5", True])
    def test_mistyped_total_raises(self, framer: MessageFramer, bad: Any) -> None:
        with pytest.raises(ValueError, match="'total' must be int"):
            framer.encode_image_list_response(images=[], total=bad, request_id="r")

    def test_well_formed_encode_byte_identical(self, framer: MessageFramer) -> None:
        """A well-formed listing encodes to exactly the pre-guard envelope."""
        record = _image_record()
        raw = framer.encode_image_list_response(
            images=[record], total=1, truncated=False, request_id="r",
        )
        expected = framer.encode(
            MessageType.IMAGE_LIST_RESPONSE,
            {"images": [record], "total": 1, "truncated": False},
            "r",
        )
        assert raw == expected

    def test_missing_byte_size_still_defaults_to_zero(
        self, framer: MessageFramer
    ) -> None:
        record = _image_record()
        del record["byte_size"]
        raw = framer.encode_image_list_response(
            images=[record], total=1, request_id="r",
        )
        decoded = framer.decode_image_list_response(raw)
        assert decoded["images"][0]["byte_size"] == 0


class TestImageListDecodeGuards:
    def test_str_images_field_raises_not_emptied(self, framer: MessageFramer) -> None:
        """A malformed ``images`` field used to silently decode as ``[]``."""
        raw = _frame(framer, MessageType.IMAGE_LIST_RESPONSE, {"images": "hello"})
        with pytest.raises(ValueError, match="'images' must be list"):
            framer.decode_image_list_response(raw)

    def test_non_dict_record_raises_not_dropped(self, framer: MessageFramer) -> None:
        """A non-dict record used to be silently DROPPED — a partial listing
        presented as complete.  It now fails the decode (Fail-Closed)."""
        raw = _frame(
            framer, MessageType.IMAGE_LIST_RESPONSE, {"images": [["x"]]}
        )
        with pytest.raises(ValueError, match=r"'images\[0\]' must be dict"):
            framer.decode_image_list_response(raw)

    def test_container_byte_size_raises(self, framer: MessageFramer) -> None:
        raw = _frame(
            framer,
            MessageType.IMAGE_LIST_RESPONSE,
            {"images": [_image_record(byte_size={"n": 1})]},
        )
        with pytest.raises(ValueError, match="'byte_size' must be int"):
            framer.decode_image_list_response(raw)

    def test_container_saved_raises(self, framer: MessageFramer) -> None:
        raw = _frame(
            framer,
            MessageType.IMAGE_LIST_RESPONSE,
            {"images": [_image_record(saved=[1])]},
        )
        with pytest.raises(ValueError, match="'saved' must be bool"):
            framer.decode_image_list_response(raw)

    def test_numeric_string_total_raises(self, framer: MessageFramer) -> None:
        raw = _frame(
            framer, MessageType.IMAGE_LIST_RESPONSE, {"images": [], "total": "5"}
        )
        with pytest.raises(ValueError, match="'total' must be int"):
            framer.decode_image_list_response(raw)

    def test_container_truncated_raises(self, framer: MessageFramer) -> None:
        raw = _frame(
            framer,
            MessageType.IMAGE_LIST_RESPONSE,
            {"images": [], "truncated": [True]},
        )
        with pytest.raises(ValueError, match="'truncated' must be bool"):
            framer.decode_image_list_response(raw)

    def test_well_formed_and_defaults(self, framer: MessageFramer) -> None:
        record = _image_record(saved=True)
        raw = framer.encode_image_list_response(
            images=[record], total=5, truncated=True, request_id="r",
        )
        assert framer.decode_image_list_response(raw) == {
            "images": [record], "total": 5, "truncated": True,
        }
        empty = _frame(framer, MessageType.IMAGE_LIST_RESPONSE, {})
        assert framer.decode_image_list_response(empty) == {
            "images": [], "total": 0, "truncated": False,
        }

    def test_absent_total_defaults_to_record_count(
        self, framer: MessageFramer
    ) -> None:
        raw = _frame(
            framer,
            MessageType.IMAGE_LIST_RESPONSE,
            {"images": [_image_record(), _image_record(image_id="b" * 32)]},
        )
        assert framer.decode_image_list_response(raw)["total"] == 2


# ─────────────────────────────────────────────────────────────────
# IMAGE_MANAGE_RESULT (the ticket's "manage" anchor)
# ─────────────────────────────────────────────────────────────────


class TestImageManageResultGuards:
    def test_container_found_raises(self, framer: MessageFramer) -> None:
        raw = _frame(framer, MessageType.IMAGE_MANAGE_RESULT, {"found": ["y"]})
        with pytest.raises(ValueError, match="'found' must be bool"):
            framer.decode_image_manage_result(raw)

    def test_int_action_raises(self, framer: MessageFramer) -> None:
        raw = _frame(framer, MessageType.IMAGE_MANAGE_RESULT, {"action": 5})
        with pytest.raises(ValueError, match="'action' must be str"):
            framer.decode_image_manage_result(raw)

    def test_well_formed_and_defaults(self, framer: MessageFramer) -> None:
        raw = framer.encode_image_manage_result(
            ok=True, action="delete", image_id="a" * 32, found=True,
            request_id="r",
        )
        assert framer.decode_image_manage_result(raw) == {
            "ok": True, "action": "delete", "image_id": "a" * 32,
            "found": True, "error_code": "", "message": "",
        }
        empty = _frame(framer, MessageType.IMAGE_MANAGE_RESULT, {})
        assert framer.decode_image_manage_result(empty) == {
            "ok": False, "action": "", "image_id": "", "found": False,
            "error_code": "", "message": "",
        }


# ─────────────────────────────────────────────────────────────────
# PREFERENCE_WRITE_RESULT / PREFERENCE_LIST_RESPONSE (twins)
# ─────────────────────────────────────────────────────────────────


class TestPreferenceWriteResultGuards:
    def test_str_conflict_raises_not_none(self, framer: MessageFramer) -> None:
        """A malformed ``conflict`` used to silently read as "no conflict"."""
        raw = _frame(
            framer, MessageType.PREFERENCE_WRITE_RESULT, {"conflict": "not-a-dict"}
        )
        with pytest.raises(ValueError, match="'conflict' must be dict or null"):
            framer.decode_preference_write_result(raw)

    def test_container_conflict_field_raises(self, framer: MessageFramer) -> None:
        raw = _frame(
            framer,
            MessageType.PREFERENCE_WRITE_RESULT,
            {"conflict": {"pref_id": ["p"], "body": "b"}},
        )
        with pytest.raises(ValueError, match="'pref_id' must be str"):
            framer.decode_preference_write_result(raw)

    def test_container_token_raises(self, framer: MessageFramer) -> None:
        raw = _frame(framer, MessageType.PREFERENCE_WRITE_RESULT, {"token": ["t"]})
        with pytest.raises(ValueError, match="'token' must be str"):
            framer.decode_preference_write_result(raw)

    def test_well_formed_with_conflict(self, framer: MessageFramer) -> None:
        raw = framer.encode_preference_write_result(
            ok=False, op="remember", status="requires_confirmation",
            conflict={"pref_id": "p-1", "body": "the old preference"},
            token="tok-1", request_id="r",
        )
        assert framer.decode_preference_write_result(raw) == {
            "ok": False, "op": "remember", "status": "requires_confirmation",
            "pref_id": "",
            "conflict": {"pref_id": "p-1", "body": "the old preference"},
            "token": "tok-1", "error_code": "", "message": "",
        }

    def test_null_and_absent_conflict_decode_to_none(
        self, framer: MessageFramer
    ) -> None:
        # encode sends an explicit JSON null when conflict is None
        raw = framer.encode_preference_write_result(
            ok=True, op="remember", status="stored", request_id="r",
        )
        assert framer.decode_preference_write_result(raw)["conflict"] is None
        absent = _frame(framer, MessageType.PREFERENCE_WRITE_RESULT, {})
        decoded = framer.decode_preference_write_result(absent)
        assert decoded["conflict"] is None
        assert decoded["ok"] is False


class TestPreferenceListResponseGuards:
    def test_str_preferences_field_raises_not_emptied(
        self, framer: MessageFramer
    ) -> None:
        raw = _frame(
            framer, MessageType.PREFERENCE_LIST_RESPONSE, {"preferences": "abc"}
        )
        with pytest.raises(ValueError, match="'preferences' must be list"):
            framer.decode_preference_list_response(raw)

    def test_non_dict_record_raises_not_dropped(self, framer: MessageFramer) -> None:
        raw = _frame(
            framer, MessageType.PREFERENCE_LIST_RESPONSE, {"preferences": [["x"]]}
        )
        with pytest.raises(ValueError, match=r"'preferences\[0\]' must be dict"):
            framer.decode_preference_list_response(raw)

    def test_container_body_raises_not_swallowed(self, framer: MessageFramer) -> None:
        """A container ``body`` used to str-coerce to "['b']" and flow on."""
        raw = _frame(
            framer,
            MessageType.PREFERENCE_LIST_RESPONSE,
            {"preferences": [{"pref_id": "p", "body": ["b"]}]},
        )
        with pytest.raises(ValueError, match="'body' must be str"):
            framer.decode_preference_list_response(raw)

    def test_container_total_raises(self, framer: MessageFramer) -> None:
        raw = _frame(
            framer,
            MessageType.PREFERENCE_LIST_RESPONSE,
            {"preferences": [], "total": [2]},
        )
        with pytest.raises(ValueError, match="'total' must be int"):
            framer.decode_preference_list_response(raw)

    def test_well_formed_and_record_defaults(self, framer: MessageFramer) -> None:
        pref = {
            "pref_id": "p-1", "type_tag": "style", "subject": "code",
            "body": "prefer tabs", "created": "2026-07-11", "updated": "",
            "expires": "",
        }
        raw = framer.encode_preference_list_response(
            preferences=[pref], request_id="r",
        )
        assert framer.decode_preference_list_response(raw) == {
            "preferences": [pref], "total": 1,
        }
        # A record with missing keys keeps the "" defaults (pinned projection).
        sparse = _frame(
            framer,
            MessageType.PREFERENCE_LIST_RESPONSE,
            {"preferences": [{"pref_id": "p-2"}]},
        )
        decoded = framer.decode_preference_list_response(sparse)
        assert decoded["preferences"][0]["pref_id"] == "p-2"
        assert decoded["preferences"][0]["body"] == ""
        assert decoded["total"] == 1
