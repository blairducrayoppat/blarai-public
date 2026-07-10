"""Locks for the guest oracle service (#744 go-live ceremony, 2026-07-08).

The guest-resident listener that runs ``execute_snapshot`` behind the oracle
channel.  Everything here runs OFFLINE on the host: the connection loop is
driven through a fake transport (the ``VsockTransport`` receive/send shape),
with the REAL channel encode/decode and — in the money test — the REAL
``execute_snapshot`` running actual ``python -m pytest``.
"""

from __future__ import annotations

import io
import zipfile

import pytest

from shared.fleet import guest_oracle as go
from shared.fleet.guest_oracle_service import (
    DEFAULT_ORACLE_PORT,
    REASON_CHANNEL_VIOLATION,
    REASON_SERVICE_INTERNAL,
    GuestOracleService,
    main,
)
from shared.ipc.oracle_channel import (
    OracleChunkAssembler,
    decode_oracle_response,
    encode_oracle_request,
)
from shared.ipc.protocol import MessageType


class FakeTransport:
    """Scripted receive queue + send recorder (the fail-closed wire shape)."""

    def __init__(self, frames: list[bytes]) -> None:
        self._rx = list(frames)
        self.sent: list[bytes] = []
        self.send_ok = True

    def receive(self) -> bytes | None:
        return self._rx.pop(0) if self._rx else None

    def send(self, data: bytes) -> bool:
        if not self.send_ok:
            return False
        self.sent.append(data)
        return True


def _snapshot(test_body: str) -> bytes:
    """A minimal valid snapshot: one module + the pinned python oracle path."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("calc.py", "def add(a, b):\n    return a + b\n")
        zf.writestr("tests/test_job_acceptance.py", test_body)
    return buf.getvalue()


def _request_frames(snapshot: bytes, oracle_path: str = "tests/test_job_acceptance.py",
                    request_id: str = "req-1") -> list[bytes]:
    return encode_oracle_request(
        request_id=request_id, snapshot_zip=snapshot, oracle_path=oracle_path
    )


def _decode_reply(sent: list[bytes]):
    assembler = OracleChunkAssembler(MessageType.ORACLE_EXEC_RESPONSE)
    for frame in sent:
        assembler.feed(frame)
    return decode_oracle_response(assembler)


# ---------------------------------------------------------------------------
# Cross-module pins (the parser-service redeclaration precedent)
# ---------------------------------------------------------------------------


def test_guest_allowed_paths_pin_matches_acceptance():
    """guest_oracle redeclares the pinned oracle paths so the guest payload
    never drags the decompose machinery; this lock keeps the copies equal."""
    from shared.fleet.acceptance import JOB_ORACLE_ALLOWED_PATHS as canonical

    assert go.JOB_ORACLE_ALLOWED_PATHS == canonical


def test_oracle_port_is_50002_and_distinct_from_the_parser():
    from services.cleaner.guest.parser_service import DEFAULT_PARSER_PORT

    assert DEFAULT_ORACLE_PORT == 50002
    assert DEFAULT_ORACLE_PORT != DEFAULT_PARSER_PORT


# ---------------------------------------------------------------------------
# The money test — real channel, real executor, real pytest
# ---------------------------------------------------------------------------


def test_full_round_trip_real_pytest_passes():
    svc = GuestOracleService()
    t = FakeTransport(_request_frames(_snapshot(
        "from calc import add\n\ndef test_add():\n    assert add(2, 3) == 5\n")))
    served = svc.serve_connection(t)
    assert served == 1
    reply = _decode_reply(t.sent)
    assert reply.request_id == "req-1"
    assert reply.status == "passed"


def test_full_round_trip_real_pytest_fails_honestly():
    svc = GuestOracleService()
    t = FakeTransport(_request_frames(_snapshot(
        "from calc import add\n\ndef test_add():\n    assert add(2, 3) == 6\n")))
    assert svc.serve_connection(t) == 1
    reply = _decode_reply(t.sent)
    assert reply.status == "failed"


def test_refused_path_is_honest_not_run():
    svc = GuestOracleService()
    t = FakeTransport(_request_frames(_snapshot("x = 1\n"), oracle_path="tests/evil.py"))
    assert svc.serve_connection(t) == 1
    reply = _decode_reply(t.sent)
    assert reply.status == "not-run"
    assert "refused" in reply.reason or reply.reason


# ---------------------------------------------------------------------------
# Fail-closed connection rules
# ---------------------------------------------------------------------------


def test_channel_violation_answers_then_drops():
    svc = GuestOracleService(_execute=lambda *a, **k: {"status": "passed", "reason": "", "evidence": ""})
    # A snapshot big enough to chunk across multiple frames, then feed a
    # MID-MESSAGE chunk first: a sequence violation whose envelope still
    # carries the request_id, so the error is addressable.  The padding must
    # be INCOMPRESSIBLE (a deterministic hash chain) — DEFLATE flattens
    # repeated text back under one frame.
    import hashlib

    pad = bytearray()
    seed = b"blarai-761"
    while len(pad) < 120_000:
        seed = hashlib.sha256(seed).digest()
        pad.extend(seed)
    big_buf = io.BytesIO()
    with zipfile.ZipFile(big_buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("calc.py", "x = 1\n")
        zf.writestr("data.bin", bytes(pad))
        zf.writestr("tests/test_job_acceptance.py", "def test_p():\n    pass\n")
    frames = _request_frames(big_buf.getvalue())
    assert len(frames) >= 2, "need a multi-frame request for this lock"
    t = FakeTransport([frames[1]])
    assert svc.serve_connection(t) == 0
    reply = _decode_reply(t.sent)
    assert reply.status == "not-run"
    assert reply.reason == REASON_CHANNEL_VIOLATION


def test_truncated_request_drops_without_response():
    svc = GuestOracleService(_execute=lambda *a, **k: {"status": "passed", "reason": "", "evidence": ""})
    frames = _request_frames(_snapshot("x = 1\n"))
    t = FakeTransport(frames[:-1])  # connection closes mid-message
    assert svc.serve_connection(t) == 0
    assert t.sent == []


def test_internal_error_is_label_only_not_run():
    def boom(*a, **k):
        raise RuntimeError("secret snapshot content must never ride an error")

    svc = GuestOracleService(_execute=boom)
    t = FakeTransport(_request_frames(_snapshot("x = 1\n")))
    assert svc.serve_connection(t) == 1
    reply = _decode_reply(t.sent)
    assert reply.status == "not-run"
    assert reply.reason == REASON_SERVICE_INTERNAL
    assert "secret" not in reply.evidence  # class name only


def test_send_failure_drops_connection():
    svc = GuestOracleService(_execute=lambda *a, **k: {"status": "passed", "reason": "", "evidence": ""})
    t = FakeTransport(_request_frames(_snapshot("x = 1\n")))
    t.send_ok = False
    assert svc.serve_connection(t) == 0


def test_two_requests_one_connection():
    svc = GuestOracleService(_execute=lambda *a, **k: {"status": "passed", "reason": "", "evidence": ""})
    frames = _request_frames(_snapshot("x = 1\n"), request_id="req-1")
    frames += _request_frames(_snapshot("x = 1\n"), request_id="req-2")
    t = FakeTransport(frames)
    assert svc.serve_connection(t) == 2


def test_exec_timeout_threads_to_the_executor():
    seen = {}

    def probe(snapshot, path, *, timeout_s):
        seen["timeout_s"] = timeout_s
        return {"status": "not-run", "reason": "probe", "evidence": ""}

    svc = GuestOracleService(exec_timeout_s=123.0, _execute=probe)
    t = FakeTransport(_request_frames(_snapshot("x = 1\n")))
    svc.serve_connection(t)
    assert seen["timeout_s"] == 123.0


# ---------------------------------------------------------------------------
# Startup gate (mTLS-or-explicit-plaintext, the #615/#655 precedent)
# ---------------------------------------------------------------------------


def test_main_refuses_without_plaintext_optin():
    assert main(["--transport", "tcp", "--port", "0"]) == 2


def test_main_refuses_partial_mtls_material(tmp_path):
    cert = tmp_path / "c.pem"
    cert.write_text("not a cert", encoding="utf-8")
    assert main(["--transport", "tcp", "--port", "0", "--cert", str(cert)]) == 2


def test_main_refuses_unloadable_mtls_material(tmp_path):
    for name in ("c.pem", "k.pem", "ca.pem"):
        (tmp_path / name).write_text("garbage", encoding="utf-8")
    rc = main([
        "--transport", "tcp", "--port", "0",
        "--cert", str(tmp_path / "c.pem"),
        "--key", str(tmp_path / "k.pem"),
        "--ca", str(tmp_path / "ca.pem"),
    ])
    assert rc == 2
