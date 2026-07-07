"""Tests for the PLAN_REQUEST / PLAN_RESULT framer round-trip (#670).

The headless-coding-dispatch PLAN step crosses the gateway↔AO vsock leg: the gateway
sends a goal + repo, the AO returns the decomposed tasks + the validated AcceptanceSpec
(metadata only — no model weights, no conversation).
"""

from __future__ import annotations

import pytest

from shared.ipc.protocol import MessageFramer, MessageType


def test_plan_request_roundtrip():
    f = MessageFramer()
    frame = f.encode_plan_request(repo="myapp", goal="a calculator", request_id="r1")
    msg_type, rid, _payload = f.decode(frame)
    assert msg_type == MessageType.PLAN_REQUEST and rid == "r1"
    assert f.decode_plan_request(frame) == {"repo": "myapp", "goal": "a calculator"}


def test_plan_result_roundtrip():
    f = MessageFramer()
    tasks = [
        {"repo": "R", "task": "add-calc", "prompt": "build a calc"},
        {"repo": "R", "task": "acceptance-tests", "prompt": "test it"},
    ]
    criteria = {
        "goal": "a calc",
        "criteria": [{"id": "c1", "text": "it builds", "tier": "build", "check": ""}],
    }
    frame = f.encode_plan_result(
        ok=True, message="planned", fell_back=False,
        tasks=tasks, criteria=criteria, request_id="r2",
    )
    got = f.decode_plan_result(frame)
    assert got["ok"] is True and got["message"] == "planned" and got["fell_back"] is False
    assert got["tasks"] == tasks and got["criteria"] == criteria


def test_plan_result_failure_shape():
    f = MessageFramer()
    got = f.decode_plan_result(f.encode_plan_result(ok=False, message="Planning failed"))
    assert got["ok"] is False and got["message"] == "Planning failed"
    assert got["tasks"] == [] and got["criteria"] == {}  # empty defaults on failure


def test_decode_plan_result_rejects_wrong_type():
    f = MessageFramer()
    with pytest.raises(ValueError):
        f.decode_plan_result(f.encode_plan_request(repo="r", goal="g"))


def test_decode_plan_request_rejects_wrong_type():
    f = MessageFramer()
    with pytest.raises(ValueError):
        f.decode_plan_request(f.encode_plan_result(ok=True))


# ---- EXECUTE (the operator-approved dispatch fires the swap) ---------------


def test_execute_request_roundtrip():
    f = MessageFramer()
    tasks = [{"repo": "R", "task": "t", "prompt": "p"}]
    frame = f.encode_execute_request(session_id="s1", run_id="RID1", tasks=tasks, request_id="r1")
    msg_type, rid, _payload = f.decode(frame)
    assert msg_type == MessageType.EXECUTE_REQUEST and rid == "r1"
    assert f.decode_execute_request(frame) == {
        "session_id": "s1", "run_id": "RID1", "tasks": tasks,
    }


def test_execute_result_roundtrip():
    f = MessageFramer()
    got = f.decode_execute_result(
        f.encode_execute_result(ok=True, run_id="RID1", message="dispatching")
    )
    assert got == {"ok": True, "run_id": "RID1", "message": "dispatching"}


def test_execute_result_failure_shape():
    f = MessageFramer()
    got = f.decode_execute_result(f.encode_execute_result(ok=False, message="enqueue refused"))
    assert got["ok"] is False and got["message"] == "enqueue refused" and got["run_id"] == ""


def test_decode_execute_result_rejects_wrong_type():
    f = MessageFramer()
    with pytest.raises(ValueError):
        f.decode_execute_result(f.encode_execute_request(session_id="s", run_id="r"))
