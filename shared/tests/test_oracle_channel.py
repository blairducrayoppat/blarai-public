"""Tests for the guest-oracle channel (shared/ipc/oracle_channel.py, #744).

The chunked framing contract mirrored from the proven UC-003 parse channel:
deterministic framing, hard caps both directions validated BEFORE buffering,
truncation/reorder/cross-talk/tamper all fail-closed. The corridor is DORMANT
(no production transport sends these frames); these locks pin the wire
contract so the supervised go-live ceremony only wires sockets, never
renegotiates framing.
"""

from __future__ import annotations

import base64
import json

import pytest

from shared.ipc import oracle_channel as oc
from shared.ipc.protocol import MessageFramer, MessageType


def _assemble(frames, expected_type):
    asm = oc.OracleChunkAssembler(expected_type)
    done = False
    for frame in frames:
        done = asm.feed(frame)
    assert done and asm.complete
    return asm


def _payload(frame):
    _t, _rid, payload = MessageFramer().decode(frame)
    return payload


# ---- request round trip -----------------------------------------------------


def test_request_round_trip_single_chunk():
    frames = oc.encode_oracle_request(
        request_id="R1", snapshot_zip=b"PK-zip-bytes", oracle_path="tests/test_job_acceptance.py")
    assert len(frames) == 1
    req = oc.decode_oracle_request(_assemble(frames, MessageType.ORACLE_EXEC_REQUEST))
    assert req.request_id == "R1"
    assert req.oracle_path == "tests/test_job_acceptance.py"
    assert req.snapshot_zip == b"PK-zip-bytes"


def test_request_round_trip_multi_chunk_exact_reassembly():
    body = bytes(range(256)) * 700          # 179,200 bytes -> 4 chunks
    frames = oc.encode_oracle_request(
        request_id="R2", snapshot_zip=body, oracle_path="tests/test_job_acceptance.py")
    assert len(frames) == -(-len(body) // oc.ORACLE_CHUNK_DATA_BYTES)
    req = oc.decode_oracle_request(_assemble(frames, MessageType.ORACLE_EXEC_REQUEST))
    assert req.snapshot_zip == body


def test_request_meta_rides_chunk_zero_only():
    body = b"x" * (oc.ORACLE_CHUNK_DATA_BYTES + 1)
    frames = oc.encode_oracle_request(
        request_id="R3", snapshot_zip=body, oracle_path="tests/test_job_acceptance.py")
    assert "meta" in _payload(frames[0])
    assert "meta" not in _payload(frames[1])


# ---- request encode-side fail-closed ----------------------------------------


@pytest.mark.parametrize("bad", [b"", b"x" * (oc.ORACLE_BODY_MAX_BYTES + 1)],
                         ids=["empty", "oversize"])
def test_request_body_caps_unsendable(bad):
    with pytest.raises(oc.OracleChannelError):
        oc.encode_oracle_request(request_id="R", snapshot_zip=bad,
                                 oracle_path="tests/test_job_acceptance.py")


@pytest.mark.parametrize("bad_path", [
    "", "   ",
    "a" * (oc.ORACLE_PATH_MAX_CHARS + 1),
    "tests/éval.py",                    # non-ASCII
    "tests\\test_job_acceptance.py",         # backslash
    "/etc/passwd",                           # absolute
    "C:/x/y.py",                             # drive
    "tests/../secrets.py",                   # traversal
    "tests//x.py",                           # empty segment
])
def test_request_hostile_oracle_path_unsendable(bad_path):
    with pytest.raises(oc.OracleChannelError):
        oc.encode_oracle_request(request_id="R", snapshot_zip=b"z", oracle_path=bad_path)


def test_request_id_required_and_capped():
    with pytest.raises(oc.OracleChannelError):
        oc.encode_oracle_request(request_id="", snapshot_zip=b"z",
                                 oracle_path="tests/test_job_acceptance.py")
    with pytest.raises(oc.OracleChannelError):
        oc.encode_oracle_request(request_id="i" * (oc.ORACLE_REQUEST_ID_MAX_CHARS + 1),
                                 snapshot_zip=b"z",
                                 oracle_path="tests/test_job_acceptance.py")


# ---- response round trip + closed vocabulary ---------------------------------


@pytest.mark.parametrize("status,reason", [
    ("passed", ""), ("failed", ""), ("not-run", "deps-unavailable"),
])
def test_response_round_trip(status, reason):
    frames = oc.encode_oracle_response(
        request_id="R9", status=status, reason=reason, evidence="exit 0; 3 passed")
    resp = oc.decode_oracle_response(_assemble(frames, MessageType.ORACLE_EXEC_RESPONSE))
    assert resp.request_id == "R9"
    assert resp.status == status and resp.reason == reason
    assert resp.evidence == "exit 0; 3 passed"


def test_response_unknown_status_unsendable():
    with pytest.raises(oc.OracleChannelError):
        oc.encode_oracle_response(request_id="R", status="maybe")


def test_response_not_run_requires_reason_and_run_refuses_reason():
    with pytest.raises(oc.OracleChannelError):
        oc.encode_oracle_response(request_id="R", status="not-run", reason="  ")
    with pytest.raises(oc.OracleChannelError):
        oc.encode_oracle_response(request_id="R", status="passed", reason="why")


def test_response_decode_rejects_forged_status():
    # A forged body carrying an out-of-vocabulary status must be REJECTED, never
    # coerced into a plausible-looking verdict (fail-closed on the receive side).
    body = json.dumps({"status": "certified", "reason": "", "evidence": ""}).encode()
    frames = oc._encode_chunked(  # bypass encode validation to forge the wire
        MessageType.ORACLE_EXEC_RESPONSE, "R", body, {}, MessageFramer())
    asm = _assemble(frames, MessageType.ORACLE_EXEC_RESPONSE)
    with pytest.raises(oc.OracleChannelError):
        oc.decode_oracle_response(asm)


def test_response_decode_rejects_non_json_body():
    frames = oc._encode_chunked(
        MessageType.ORACLE_EXEC_RESPONSE, "R", b"\xff\xfenot json", {}, MessageFramer())
    asm = _assemble(frames, MessageType.ORACLE_EXEC_RESPONSE)
    with pytest.raises(oc.OracleChannelError):
        oc.decode_oracle_response(asm)


# ---- assembler fail-closed rules ---------------------------------------------


def _two_chunk_frames():
    body = b"y" * (oc.ORACLE_CHUNK_DATA_BYTES + 10)
    return oc.encode_oracle_request(
        request_id="RA", snapshot_zip=body, oracle_path="tests/test_job_acceptance.py")


def test_truncated_stream_is_a_hard_failure():
    frames = _two_chunk_frames()
    asm = oc.OracleChunkAssembler(MessageType.ORACLE_EXEC_REQUEST)
    assert asm.feed(frames[0]) is False
    with pytest.raises(oc.OracleChannelError, match="incomplete"):
        asm.body()


def test_out_of_order_chunk_rejected():
    frames = _two_chunk_frames()
    asm = oc.OracleChunkAssembler(MessageType.ORACLE_EXEC_REQUEST)
    with pytest.raises(oc.OracleChannelError, match="out of order"):
        asm.feed(frames[1])


def test_duplicate_chunk_rejected():
    frames = _two_chunk_frames()
    asm = oc.OracleChunkAssembler(MessageType.ORACLE_EXEC_REQUEST)
    asm.feed(frames[0])
    with pytest.raises(oc.OracleChannelError, match="out of order"):
        asm.feed(frames[0])


def test_cross_talk_request_id_change_rejected():
    frames_a = _two_chunk_frames()
    body = b"y" * (oc.ORACLE_CHUNK_DATA_BYTES + 10)
    frames_b = oc.encode_oracle_request(
        request_id="RB", snapshot_zip=body, oracle_path="tests/test_job_acceptance.py")
    asm = oc.OracleChunkAssembler(MessageType.ORACLE_EXEC_REQUEST)
    asm.feed(frames_a[0])
    with pytest.raises(oc.OracleChannelError, match="cross-talk"):
        asm.feed(frames_b[1])


def test_oversize_declaration_rejected_before_buffering():
    framer = MessageFramer()
    payload = {"seq": 0, "chunk_count": 1,
               "total_bytes": oc.ORACLE_BODY_MAX_BYTES + 1,
               "data": base64.b64encode(b"x").decode("ascii"), "meta": {}}
    frame = framer.encode(MessageType.ORACLE_EXEC_REQUEST, payload, "R")
    asm = oc.OracleChunkAssembler(MessageType.ORACLE_EXEC_REQUEST)
    with pytest.raises(oc.OracleChannelError, match="rejected before buffering"):
        asm.feed(frame)


def test_wrong_chunk_size_rejected():
    framer = MessageFramer()
    payload = {"seq": 0, "chunk_count": 1, "total_bytes": 10,
               "data": base64.b64encode(b"short").decode("ascii"), "meta": {}}
    frame = framer.encode(MessageType.ORACLE_EXEC_REQUEST, payload, "R")
    asm = oc.OracleChunkAssembler(MessageType.ORACLE_EXEC_REQUEST)
    with pytest.raises(oc.OracleChannelError, match="deterministic"):
        asm.feed(frame)


def test_invalid_base64_rejected():
    framer = MessageFramer()
    payload = {"seq": 0, "chunk_count": 1, "total_bytes": 4,
               "data": "@@not-base64@@", "meta": {}}
    frame = framer.encode(MessageType.ORACLE_EXEC_REQUEST, payload, "R")
    asm = oc.OracleChunkAssembler(MessageType.ORACLE_EXEC_REQUEST)
    with pytest.raises(oc.OracleChannelError, match="base64"):
        asm.feed(frame)


def test_wrong_message_type_rejected():
    frames = _two_chunk_frames()
    asm = oc.OracleChunkAssembler(MessageType.ORACLE_EXEC_RESPONSE)
    with pytest.raises(oc.OracleChannelError, match="expected"):
        asm.feed(frames[0])


def test_non_channel_type_refused_at_construction():
    with pytest.raises(oc.OracleChannelError):
        oc.OracleChunkAssembler(MessageType.HEARTBEAT)


def test_frame_after_completion_rejected():
    frames = oc.encode_oracle_request(
        request_id="R1", snapshot_zip=b"z", oracle_path="tests/test_job_acceptance.py")
    asm = _assemble(frames, MessageType.ORACLE_EXEC_REQUEST)
    with pytest.raises(oc.OracleChannelError, match="after message completion"):
        asm.feed(frames[0])


def test_header_mutation_mid_message_rejected():
    frames = _two_chunk_frames()
    framer = MessageFramer()
    _t, rid, payload = framer.decode(frames[1])
    payload["total_bytes"] = payload["total_bytes"] + 1
    forged = framer.encode(MessageType.ORACLE_EXEC_REQUEST, payload, rid)
    asm = oc.OracleChunkAssembler(MessageType.ORACLE_EXEC_REQUEST)
    asm.feed(frames[0])
    with pytest.raises(oc.OracleChannelError, match="mutated"):
        asm.feed(forged)


def test_decode_request_requires_oracle_path_meta():
    frames = oc._encode_chunked(
        MessageType.ORACLE_EXEC_REQUEST, "R", b"zip", {}, MessageFramer())
    asm = _assemble(frames, MessageType.ORACLE_EXEC_REQUEST)
    with pytest.raises(oc.OracleChannelError, match="oracle_path"):
        oc.decode_oracle_request(asm)
