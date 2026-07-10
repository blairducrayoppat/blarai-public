"""Offline locks for the guest-oracle AF_HYPERV transport (#744, slice 2).

Locks, in order of importance:

  1. **STRUCTURAL DORMANCY** — the transport factory ships BUILT-NOT-REGISTERED
     (the #655 url_adjudicator precedent): the production call site
     (``swap_ops.real_run_guest_oracle``) still passes ``transport=None``, the
     pipeline's ``transport`` parameter still DEFAULTS to ``None``, and NO
     production module imports the factory or the bridge.  These are the tests
     the go-live ceremony will consciously amend.
  2. The factory's wiring-time validation (loud raises) and the returned
     callable's never-raise fail-closed contract (every failure → an honest
     ``not-run`` with a stable machine reason).
  3. The full encode → wire → guest → decode chain against a FAKE socket
     (no VM, no live AF_HYPERV — the live in-guest proof is the LA's
     supervised ceremony), including ONE end-to-end run through the real
     ``run_guest_oracle`` pipeline with the guest half executing real pytest.
  4. The 3.14 bridge helper (``shared.fleet.guest_oracle_bridge``) and the
     3.11 invoker (``GuestOracleBridge``) — both halves of the version bridge,
     proven to speak the same pipe framing offline.
"""

from __future__ import annotations

import inspect
import io
import json
import socket
import struct
import subprocess
import sys
import types
from pathlib import Path

import pytest

from shared.constants import ORCHESTRATOR_VM_ID
from shared.fleet import guest_oracle as go
from shared.fleet import guest_oracle_bridge as gob
from shared.fleet import guest_oracle_transport as got
from shared.ipc.oracle_channel import (
    ORACLE_BODY_MAX_BYTES,
    OracleChunkAssembler,
    OracleExecResponse,
    decode_oracle_request,
    encode_oracle_request,
    encode_oracle_response,
)
from shared.ipc.protocol import MessageFramer, MessageType

REPO_ROOT = Path(__file__).resolve().parents[2]

ORACLE_PATH = "tests/test_job_acceptance.py"

_ENDPOINT = got.OracleEndpoint(
    vm_id=ORCHESTRATOR_VM_ID,
    service_guid=got.hv_service_guid_for_port(50001),
    vsock_port=50001,
    timeout_s=5.0,
)


# =============================================================================
# 1. STRUCTURAL DORMANCY (the locks the go-live ceremony consciously amends)
# =============================================================================


def test_pipeline_transport_parameter_still_defaults_to_none():
    # THE dormancy contract at the pipeline layer: run_guest_oracle's transport
    # defaults to None, so an unwired call is an honest not-run.
    sig = inspect.signature(go.run_guest_oracle)
    assert sig.parameters["transport"].default is None


def test_production_call_site_registers_the_transport():
    # CONSCIOUSLY AMENDED at the 2026-07-08 go-live ceremony (#744): the
    # registration this lock used to forbid is now the thing it PINS.  The
    # call site must build the factory (port 50002, the guest service's), and
    # must keep the fail-soft degrade: a factory failure becomes
    # transport=None (honest not-run), never a raise into the swap teardown.
    import shared.fleet.swap_ops as swap_ops

    src = inspect.getsource(swap_ops.real_run_guest_oracle)
    assert "make_guest_oracle_transport" in src
    assert "GUEST_ORACLE_VSOCK_PORT" in src
    assert "transport = None" in src  # the fail-soft degrade branch
    assert swap_ops.GUEST_ORACLE_VSOCK_PORT == 50002


def test_call_site_port_matches_the_guest_service():
    # The two sides of the corridor can never silently diverge: the port the
    # host registers == the port the guest service binds.
    import shared.fleet.swap_ops as swap_ops
    from shared.fleet.guest_oracle_service import DEFAULT_ORACLE_PORT

    assert swap_ops.GUEST_ORACLE_VSOCK_PORT == DEFAULT_ORACLE_PORT


def _production_py_files():
    for top in ("shared", "services", "launcher"):
        base = REPO_ROOT / top
        if not base.is_dir():  # pragma: no cover - repo-shape guard
            continue
        for path in sorted(base.rglob("*.py")):
            rel = path.relative_to(REPO_ROOT).as_posix()
            if "tests" in path.relative_to(REPO_ROOT).parts:
                continue
            if rel in (
                "shared/fleet/guest_oracle_transport.py",
                "shared/fleet/guest_oracle_bridge.py",
            ):
                continue
            yield path, rel


def test_transport_references_stay_at_the_sanctioned_sites():
    # CONSCIOUSLY AMENDED at the 2026-07-08 go-live ceremony (#744): the
    # former structural-absence lock becomes a REGISTRATION-CONTAINMENT lock.
    # Exactly THREE production files may reference the transport family:
    #   * shared/fleet/swap_ops.py         — THE registration site (the
    #     ceremony's one-line wiring; factory + port constant)
    #   * shared/timeout_registry.py       — governance metadata (module name
    #     + timeout constant only; never the factory/bridge — the #767
    #     exemption, unchanged)
    #   * shared/fleet/guest_oracle_service.py — the GUEST-side service
    #     bundle source (no factory/bridge references; it is the far END of
    #     the corridor, not a caller)
    # Anything else referencing the factory or bridge is scope creep on a
    # security corridor and fails here.
    offenders: list[str] = []
    needles = (
        "guest_oracle_transport",
        "guest_oracle_bridge",
        "make_guest_oracle_transport",
    )
    registration_rel = "shared/fleet/swap_ops.py"
    registry_rel = "shared/timeout_registry.py"
    service_rel = "shared/fleet/guest_oracle_service.py"
    for path, rel in _production_py_files():
        text = path.read_text(encoding="utf-8", errors="replace")
        if rel == registration_rel:
            assert "make_guest_oracle_transport" in text  # the wiring lives here
            continue
        if rel == registry_rel:
            assert "make_guest_oracle_transport" not in text, (
                "the timeout registry may reference the transport MODULE (its "
                "timeout row) but must never reference the FACTORY."
            )
            assert "guest_oracle_bridge" not in text
            continue
        if rel == service_rel:
            assert "make_guest_oracle_transport" not in text, (
                "the guest service is the far end of the corridor — it must "
                "never construct the host-side factory."
            )
            assert "guest_oracle_bridge" not in text
            continue
        if any(needle in text for needle in needles):
            offenders.append(rel)
    assert offenders == [], (
        "an UNSANCTIONED production module references the guest-oracle "
        f"transport family — registration is contained to swap_ops by "
        f"ceremony decision (#744, 2026-07-08): {offenders}"
    )


def test_off_behavior_unchanged_pipeline_reports_transport_unregistered(tmp_path):
    # Byte-identical OFF behavior: with no transport registered the pipeline
    # still reports the honest not-run this build has always reported.
    (tmp_path / "calc.py").write_text(
        "def add(a, b):\n    return a + b\n", encoding="utf-8"
    )
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_job_acceptance.py").write_text(
        "def test_p():\n    pass\n", encoding="utf-8"
    )
    res = go.run_guest_oracle(
        str(tmp_path),
        ORACLE_PATH,
        "from calc import add\n\ndef test_a():\n    assert add(1, 1) == 2\n",
    )
    assert res["status"] == "not-run"
    assert res["reason"] == go.REASON_TRANSPORT_UNREGISTERED


# =============================================================================
# 2. Factory wiring-time validation (loud) + callable contract (never raises)
# =============================================================================


def test_factory_derives_the_hv_sock_template_guid():
    assert got.hv_service_guid_for_port(50001) == (
        "0000c351-facb-11e6-bd58-64006a7986d3"
    )


def test_factory_rejects_out_of_range_port():
    with pytest.raises(got.GuestOracleTransportError) as exc_info:
        got.make_guest_oracle_transport(vsock_port=0, _round_trip=lambda e, f: None)
    assert exc_info.value.code == "GO_CONFIG_PORT_INVALID"


def test_factory_rejects_mismatched_explicit_guid():
    # The #615 silent-divergence class: an explicit GUID that does not match
    # the hv_sock template for the port refuses at wiring time.
    with pytest.raises(got.GuestOracleTransportError) as exc_info:
        got.make_guest_oracle_transport(
            service_guid="0000c350-facb-11e6-bd58-64006a7986d3",  # port 50000's
            vsock_port=50001,
            _round_trip=lambda e, f: None,
        )
    assert exc_info.value.code == "GO_CONFIG_GUID_MISMATCH"


def test_factory_accepts_matching_explicit_guid_case_insensitively():
    transport = got.make_guest_oracle_transport(
        service_guid="0000C351-FACB-11E6-BD58-64006A7986D3",
        vsock_port=50001,
        _round_trip=lambda e, f: None,
    )
    assert callable(transport)


def test_factory_rejects_non_positive_timeout():
    with pytest.raises(got.GuestOracleTransportError) as exc_info:
        got.make_guest_oracle_transport(timeout_s=0, _round_trip=lambda e, f: None)
    assert exc_info.value.code == "GO_CONFIG_TIMEOUT_INVALID"


def test_factory_raises_loud_at_wiring_time_when_no_bridge_interpreter(monkeypatch):
    # The invoker precedent: a missing 3.12+ interpreter is caught at FACTORY
    # time (the wiring ceremony), never as a surprise inside the swap teardown.
    monkeypatch.setattr(got, "bridge_required", lambda: True)

    def _no_bridge(bridge_python=""):
        raise got.BridgeUnavailableError("none found")

    monkeypatch.setattr(got, "discover_bridge_command", _no_bridge)
    with pytest.raises(got.BridgeUnavailableError):
        got.make_guest_oracle_transport()


def _decode_request_frames(frames: list[bytes]):
    asm = OracleChunkAssembler(MessageType.ORACLE_EXEC_REQUEST)
    for frame in frames:
        asm.feed(frame)
    return decode_oracle_request(asm)


def _echo_round_trip(status: str = "passed", reason: str = "", evidence: str = "ok"):
    """A fake round-trip that echoes the request's correlation id."""

    def round_trip(endpoint, frames):
        req = _decode_request_frames(frames)
        return OracleExecResponse(
            request_id=req.request_id,
            status=status,
            reason=reason,
            evidence=evidence,
        )

    return round_trip


def test_transport_maps_passed_response_to_result_dict():
    transport = got.make_guest_oracle_transport(
        _round_trip=_echo_round_trip("passed", "", "exit 0; 3 passed")
    )
    result = transport(b"PK-fake-zip", ORACLE_PATH)
    assert result == {"status": "passed", "reason": "", "evidence": "exit 0; 3 passed"}


def test_transport_maps_failed_and_not_run_responses():
    failed = got.make_guest_oracle_transport(
        _round_trip=_echo_round_trip("failed", "", "nonzero exit")
    )(b"zipbytes", ORACLE_PATH)
    assert failed["status"] == "failed"
    not_run = got.make_guest_oracle_transport(
        _round_trip=_echo_round_trip("not-run", "deps-unavailable", "no numpy")
    )(b"zipbytes", ORACLE_PATH)
    assert not_run == {
        "status": "not-run",
        "reason": "deps-unavailable",
        "evidence": "no numpy",
    }


def test_transport_round_trip_failure_is_honest_not_run_guest_unreachable():
    transport = got.make_guest_oracle_transport(_round_trip=lambda e, f: None)
    result = transport(b"zipbytes", ORACLE_PATH)
    assert result["status"] == "not-run"
    assert result["reason"] == got.REASON_GUEST_UNREACHABLE


def test_transport_never_raises_a_round_trip_exception():
    def exploding(endpoint, frames):
        raise RuntimeError("boom")

    transport = got.make_guest_oracle_transport(_round_trip=exploding)
    result = transport(b"zipbytes", ORACLE_PATH)
    assert result["status"] == "not-run"
    assert result["reason"] == go.REASON_GUEST_ERROR


def test_transport_refuses_correlation_mismatch_fail_closed():
    # A stale / cross-talk answer must never be attributed to THIS request.
    def stale(endpoint, frames):
        return OracleExecResponse(
            request_id="f" * 32, status="passed", reason="", evidence="stale"
        )

    transport = got.make_guest_oracle_transport(_round_trip=stale)
    result = transport(b"zipbytes", ORACLE_PATH)
    assert result["status"] == "not-run"
    assert result["reason"] == go.REASON_GUEST_ERROR
    assert "correlation" in result["evidence"]


def test_transport_hostile_oracle_path_is_unsendable_before_any_io():
    calls: list[object] = []

    def recording(endpoint, frames):  # pragma: no cover - must NOT run
        calls.append(frames)
        return None

    transport = got.make_guest_oracle_transport(_round_trip=recording)
    result = transport(b"zipbytes", "../escape/oracle.py")
    assert result["status"] == "not-run"
    assert result["reason"] == got.REASON_REQUEST_UNSENDABLE
    assert calls == []  # refused at encode — no I/O ever happened


def test_transport_empty_and_oversize_snapshots_are_unsendable():
    transport = got.make_guest_oracle_transport(_round_trip=lambda e, f: None)
    assert transport(b"", ORACLE_PATH)["reason"] == got.REASON_REQUEST_UNSENDABLE
    oversize = b"x" * (ORACLE_BODY_MAX_BYTES + 1)
    assert transport(oversize, ORACLE_PATH)["reason"] == got.REASON_REQUEST_UNSENDABLE


def test_transport_endpoint_carries_the_factory_addressing():
    seen: dict[str, object] = {}

    def recording(endpoint, frames):
        seen["endpoint"] = endpoint
        return None

    transport = got.make_guest_oracle_transport(
        vm_id="11111111-2222-3333-4444-555555555555",
        vsock_port=50002,
        timeout_s=42.0,
        _round_trip=recording,
    )
    transport(b"zipbytes", ORACLE_PATH)
    endpoint = seen["endpoint"]
    assert endpoint.vm_id == "11111111-2222-3333-4444-555555555555"
    assert endpoint.vsock_port == 50002
    assert endpoint.service_guid == got.hv_service_guid_for_port(50002)
    assert endpoint.timeout_s == 42.0


def test_transport_default_endpoint_is_the_744_design():
    seen: dict[str, object] = {}

    def recording(endpoint, frames):
        seen["endpoint"] = endpoint
        return None

    got.make_guest_oracle_transport(_round_trip=recording)(b"z", ORACLE_PATH)
    endpoint = seen["endpoint"]
    assert endpoint.vm_id == ORCHESTRATOR_VM_ID
    assert endpoint.vsock_port == got.ORACLE_VSOCK_PORT_DEFAULT == 50001
    assert endpoint.timeout_s == got.ORACLE_TRANSPORT_TIMEOUT_S_DEFAULT


# =============================================================================
# 3. The wire chain against a FAKE socket (no VM, no live AF_HYPERV)
# =============================================================================


class FakeGuestVsock:
    """A connect/send/receive/close double simulating the guest service.

    On the first ``receive`` it assembles the sent ORACLE_EXEC_REQUEST frames,
    hands the decoded request to *responder*, and streams back the frames the
    responder returns (then None, simulating close).
    """

    def __init__(self, responder, *, accept: bool = True, truncate_after: int = -1):
        self._responder = responder
        self._accept = accept
        self._truncate_after = truncate_after
        self._sent: list[bytes] = []
        self._out: list[bytes] | None = None
        self._served = 0
        self.closed = False

    def connect(self) -> bool:
        return self._accept

    def send(self, frame: bytes) -> bool:
        self._sent.append(frame)
        return True

    def receive(self) -> bytes | None:
        if self._out is None:
            req = _decode_request_frames(self._sent)
            self._out = list(self._responder(req))
        if self._truncate_after >= 0 and self._served >= self._truncate_after:
            return None
        if self._served >= len(self._out):
            return None
        frame = self._out[self._served]
        self._served += 1
        return frame

    def close(self) -> None:
        self.closed = True


def _canned_responder(status: str = "passed", reason: str = "", evidence: str = "exit 0"):
    def responder(req):
        return encode_oracle_response(
            request_id=req.request_id,
            status=status,
            reason=reason,
            evidence=evidence,
        )

    return responder


def test_in_process_round_trip_full_chain_over_fake_socket():
    fake = FakeGuestVsock(_canned_responder("passed", "", "exit 0; 3 passed"))
    frames = encode_oracle_request(
        request_id="a" * 32, snapshot_zip=b"PK-zip", oracle_path=ORACLE_PATH
    )
    response = got.oracle_round_trip(
        _ENDPOINT, frames, _transport_factory=lambda: fake
    )
    assert response is not None
    assert response.status == "passed"
    assert response.request_id == "a" * 32
    assert fake.closed  # the socket is always closed, success or not


def test_in_process_round_trip_connect_refused_is_none():
    fake = FakeGuestVsock(_canned_responder(), accept=False)
    frames = encode_oracle_request(
        request_id="a" * 32, snapshot_zip=b"PK-zip", oracle_path=ORACLE_PATH
    )
    assert got.oracle_round_trip(_ENDPOINT, frames, _transport_factory=lambda: fake) is None


def test_in_process_round_trip_truncated_response_is_none():
    # Multi-chunk response cut off mid-stream: the assembler never completes,
    # receive() returns None → fail-closed None, never a partial verdict.
    big_evidence = "e" * 100_000  # forces > 1 response chunk
    fake = FakeGuestVsock(
        _canned_responder("failed", "", big_evidence), truncate_after=1
    )
    frames = encode_oracle_request(
        request_id="a" * 32, snapshot_zip=b"PK-zip", oracle_path=ORACLE_PATH
    )
    assert got.oracle_round_trip(_ENDPOINT, frames, _transport_factory=lambda: fake) is None
    assert fake.closed


def test_in_process_round_trip_wrong_frame_type_is_none():
    # A guest answering with a NON-oracle frame is a channel violation → None.
    def wrong_type(req):
        return [
            MessageFramer().encode(
                MessageType.ORACLE_EXEC_REQUEST,
                {"seq": 0, "chunk_count": 1, "total_bytes": 1, "data": "eA=="},
                req.request_id,
            )
        ]

    fake = FakeGuestVsock(wrong_type)
    frames = encode_oracle_request(
        request_id="a" * 32, snapshot_zip=b"PK-zip", oracle_path=ORACLE_PATH
    )
    assert got.oracle_round_trip(_ENDPOINT, frames, _transport_factory=lambda: fake) is None


def test_in_process_round_trip_without_af_hyperv_or_seam_is_none(monkeypatch):
    # On the 3.11 runtime with no bridge and no seam there is NO path to the
    # guest at all — fail-closed None (never a fabricated verdict).
    monkeypatch.delattr(socket, "AF_HYPERV", raising=False)
    frames = encode_oracle_request(
        request_id="a" * 32, snapshot_zip=b"PK-zip", oracle_path=ORACLE_PATH
    )
    assert got.oracle_round_trip(_ENDPOINT, frames) is None


def test_round_trip_prefers_the_bridge_when_given():
    class FakeBridge:
        def __init__(self, frames_out):
            self.calls: list[tuple[object, list[bytes]]] = []
            self._frames_out = frames_out

        def oracle(self, endpoint, request_frames):
            self.calls.append((endpoint, request_frames))
            return self._frames_out

    request_frames = encode_oracle_request(
        request_id="b" * 32, snapshot_zip=b"PK-zip", oracle_path=ORACLE_PATH
    )
    response_frames = encode_oracle_response(
        request_id="b" * 32, status="failed", evidence="nonzero exit"
    )
    bridge = FakeBridge(response_frames)
    response = got.oracle_round_trip(_ENDPOINT, request_frames, bridge=bridge)
    assert response is not None and response.status == "failed"
    assert bridge.calls and bridge.calls[0][0] is _ENDPOINT


def test_round_trip_bridge_failure_and_crash_are_none():
    class NoneBridge:
        def oracle(self, endpoint, request_frames):
            return None

    class CrashBridge:
        def oracle(self, endpoint, request_frames):
            raise OSError("pipe burst")

    frames = encode_oracle_request(
        request_id="b" * 32, snapshot_zip=b"PK-zip", oracle_path=ORACLE_PATH
    )
    assert got.oracle_round_trip(_ENDPOINT, frames, bridge=NoneBridge()) is None
    assert got.oracle_round_trip(_ENDPOINT, frames, bridge=CrashBridge()) is None


def test_round_trip_bridge_garbled_frames_are_none():
    class GarbledBridge:
        def oracle(self, endpoint, request_frames):
            return [b"not-a-frame"]

    frames = encode_oracle_request(
        request_id="b" * 32, snapshot_zip=b"PK-zip", oracle_path=ORACLE_PATH
    )
    assert got.oracle_round_trip(_ENDPOINT, frames, bridge=GarbledBridge()) is None


def test_end_to_end_pipeline_over_fake_socket_with_real_guest_pytest(tmp_path):
    # THE money lock: the REAL host pipeline (snapshot → overlay → dep scan →
    # zip → encode) through a fake socket to the REAL guest half
    # (safe-extract → actual `python -m pytest`) and back through the channel
    # decode into the pipeline's closed result shape.  Only the AF_HYPERV
    # socket is faked — the live in-guest run is the LA's supervised ceremony.
    (tmp_path / "calc.py").write_text(
        "def add(a, b):\n    return a + b\n", encoding="utf-8"
    )
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_job_acceptance.py").write_text(
        "def test_p():\n    pass\n", encoding="utf-8"
    )

    def guest_responder(req):
        result = go.execute_snapshot(req.snapshot_zip, req.oracle_path)
        return encode_oracle_response(
            request_id=req.request_id,
            status=result["status"],
            reason=result["reason"],
            evidence=result["evidence"],
        )

    transport = got.make_guest_oracle_transport(
        _round_trip=lambda endpoint, frames: got.oracle_round_trip(
            endpoint,
            frames,
            _transport_factory=lambda: FakeGuestVsock(guest_responder),
        )
    )
    result = go.run_guest_oracle(
        str(tmp_path),
        ORACLE_PATH,
        "from calc import add\n\n\ndef test_add():\n    assert add(2, 3) == 5\n",
        transport=transport,
    )
    assert result["status"] == "passed"
    assert result["reason"] == ""
    assert "exit 0" in result["evidence"]


# =============================================================================
# 4a. The 3.11-side invoker (GuestOracleBridge) — subprocess seam faked
# =============================================================================


def _bridge_stdout(status: dict, frames: list[bytes] | None = None) -> bytes:
    out = (json.dumps(status) + "\n").encode("utf-8")
    if frames is not None:
        out += got._frame_list_bytes(frames)
    return out


def _fake_subprocess_run(stdout: bytes, returncode: int = 0, capture: dict | None = None):
    def fake_run(argv, **kwargs):
        if capture is not None:
            capture["argv"] = argv
            capture["kwargs"] = kwargs
        return types.SimpleNamespace(stdout=stdout, stderr=b"", returncode=returncode)

    return fake_run


def test_invoker_oracle_op_returns_response_frames(monkeypatch):
    response_frames = encode_oracle_response(
        request_id="c" * 32, status="passed", evidence="exit 0"
    )
    capture: dict = {}
    monkeypatch.setattr(
        got.subprocess,
        "run",
        _fake_subprocess_run(
            _bridge_stdout(
                {"ok": True, "code": "OK", "op": "oracle", "frames": len(response_frames)},
                response_frames,
            ),
            capture=capture,
        ),
    )
    bridge = got.GuestOracleBridge(_command=["fake-python"])
    request_frames = encode_oracle_request(
        request_id="c" * 32, snapshot_zip=b"PK-zip", oracle_path=ORACLE_PATH
    )
    frames = bridge.oracle(_ENDPOINT, request_frames)
    assert frames == response_frames
    # And the decoded view round-trips through the shared assembler.
    response = got._assemble_response(frames)
    assert response is not None and response.status == "passed"
    # The spawned command targets the ORACLE bridge module under the resolved
    # interpreter, with the repo root on PYTHONPATH.
    assert capture["argv"][:1] == ["fake-python"]
    assert capture["argv"][-2:] == ["-m", "shared.fleet.guest_oracle_bridge"]
    assert str(REPO_ROOT) in capture["kwargs"]["env"]["PYTHONPATH"]


def test_invoker_stdin_carries_the_job_line_then_length_prefixed_frames(monkeypatch):
    capture: dict = {}
    monkeypatch.setattr(
        got.subprocess,
        "run",
        _fake_subprocess_run(
            _bridge_stdout({"ok": False, "code": "BRIDGE_CONNECT_FAILED", "op": "oracle"}),
            returncode=1,
            capture=capture,
        ),
    )
    bridge = got.GuestOracleBridge(
        _command=["fake-python"], mtls_cert="c.pem", mtls_key="k.pem", mtls_ca="ca.pem"
    )
    request_frames = encode_oracle_request(
        request_id="c" * 32, snapshot_zip=b"PK-zip", oracle_path=ORACLE_PATH
    )
    bridge.oracle(_ENDPOINT, request_frames)
    payload: bytes = capture["kwargs"]["input"]
    newline = payload.find(b"\n")
    job = json.loads(payload[:newline].decode("utf-8"))
    assert job["op"] == "oracle"
    assert job["vm_id"] == _ENDPOINT.vm_id
    assert job["service_guid"] == _ENDPOINT.service_guid
    assert job["vsock_port"] == 50001
    assert job["mtls_cert"] == "c.pem" and job["mtls_ca"] == "ca.pem"
    assert got._decode_frame_list(payload[newline + 1 :]) == request_frames


def test_invoker_failure_modes_map_to_none(monkeypatch):
    bridge = got.GuestOracleBridge(_command=["fake-python"])
    request_frames = encode_oracle_request(
        request_id="c" * 32, snapshot_zip=b"PK-zip", oracle_path=ORACLE_PATH
    )
    # ok=false status → None.
    monkeypatch.setattr(
        got.subprocess,
        "run",
        _fake_subprocess_run(
            _bridge_stdout({"ok": False, "code": "BRIDGE_RECV_FAILED", "op": "oracle"}),
            returncode=1,
        ),
    )
    assert bridge.oracle(_ENDPOINT, request_frames) is None
    # Garbled stdout (no status line) → None.
    monkeypatch.setattr(
        got.subprocess, "run", _fake_subprocess_run(b"\x00\x01garbage-no-newline")
    )
    assert bridge.oracle(_ENDPOINT, request_frames) is None
    # Timeout → None.

    def timeout_run(argv, **kwargs):
        raise subprocess.TimeoutExpired(cmd=argv, timeout=1.0)

    monkeypatch.setattr(got.subprocess, "run", timeout_run)
    assert bridge.oracle(_ENDPOINT, request_frames) is None
    # Spawn failure → None.

    def oserror_run(argv, **kwargs):
        raise OSError("no such interpreter")

    monkeypatch.setattr(got.subprocess, "run", oserror_run)
    assert bridge.oracle(_ENDPOINT, request_frames) is None


def test_invoker_reachable_maps_status_ok(monkeypatch):
    bridge = got.GuestOracleBridge(_command=["fake-python"])
    monkeypatch.setattr(
        got.subprocess,
        "run",
        _fake_subprocess_run(_bridge_stdout({"ok": True, "code": "OK", "op": "reachable"})),
    )
    assert bridge.reachable(_ENDPOINT) is True
    monkeypatch.setattr(
        got.subprocess,
        "run",
        _fake_subprocess_run(
            _bridge_stdout({"ok": False, "code": "BRIDGE_CONNECT_FAILED", "op": "reachable"}),
            returncode=1,
        ),
    )
    assert bridge.reachable(_ENDPOINT) is False


def test_discovery_returns_first_qualifying_candidate(monkeypatch):
    monkeypatch.setattr(
        got, "_interp_has_af_hyperv", lambda command: command == ["C:/py314/python.exe"]
    )
    command = got.discover_bridge_command("C:/py314/python.exe")
    assert command == ["C:/py314/python.exe"]


def test_discovery_never_uses_the_running_interpreter_and_fails_loud(monkeypatch):
    probed: list[list[str]] = []

    def record(command):
        probed.append(command)
        return False

    monkeypatch.setattr(got, "_interp_has_af_hyperv", record)
    with pytest.raises(got.BridgeUnavailableError):
        got.discover_bridge_command()
    assert [sys.executable] not in probed  # NEVER the 3.11 runtime


# =============================================================================
# 4b. The 3.14 bridge helper module (run under fakes — no subprocess, no VM)
# =============================================================================


class _FakeStdout:
    def __init__(self):
        self.buffer = io.BytesIO()
        self.text = io.StringIO()

    def write(self, s: str) -> int:
        return self.text.write(s)

    def flush(self) -> None:
        pass


def _run_bridge(monkeypatch, stdin_payload: bytes, transport=None, *, af_hyperv=True):
    """Drive gob.run() with faked stdio (+ optionally a faked transport)."""
    if af_hyperv:
        monkeypatch.setattr(gob.socket, "AF_HYPERV", 34, raising=False)
    else:
        monkeypatch.delattr(gob.socket, "AF_HYPERV", raising=False)
    if transport is not None:
        monkeypatch.setattr(gob, "_build_transport", lambda job: transport)
    fake_stdout = _FakeStdout()
    monkeypatch.setattr(
        gob.sys, "stdin", types.SimpleNamespace(buffer=io.BytesIO(stdin_payload))
    )
    monkeypatch.setattr(gob.sys, "stdout", fake_stdout)
    exit_code = gob.run([])
    status_line = fake_stdout.text.getvalue()
    status = json.loads(status_line) if status_line.strip() else {}
    return exit_code, status, fake_stdout.buffer.getvalue()


def _job_bytes(op: str = "oracle", **overrides) -> bytes:
    job = {
        "op": op,
        "vm_id": _ENDPOINT.vm_id,
        "service_guid": _ENDPOINT.service_guid,
        "vsock_port": _ENDPOINT.vsock_port,
        "timeout_s": _ENDPOINT.timeout_s,
        "mtls_cert": "",
        "mtls_key": "",
        "mtls_ca": "",
    }
    job.update(overrides)
    return (json.dumps(job) + "\n").encode("utf-8")


def test_bridge_oracle_op_round_trips_and_ships_response_frames(monkeypatch):
    fake = FakeGuestVsock(_canned_responder("passed", "", "exit 0"))
    request_frames = encode_oracle_request(
        request_id="d" * 32, snapshot_zip=b"PK-zip", oracle_path=ORACLE_PATH
    )
    stdin_payload = _job_bytes("oracle") + got._frame_list_bytes(request_frames)
    exit_code, status, frames_blob = _run_bridge(monkeypatch, stdin_payload, fake)
    assert exit_code == 0
    assert status["ok"] is True and status["code"] == gob.BRIDGE_OK
    # The two halves speak ONE pipe framing: the invoker's decoder reads the
    # bridge's frame blob, and the shared assembler decodes the response.
    frames = got._decode_frame_list(frames_blob)
    assert status["frames"] == len(frames) > 0
    response = got._assemble_response(frames)
    assert response is not None
    assert response.status == "passed" and response.request_id == "d" * 32
    assert fake.closed


def test_bridge_reachable_op(monkeypatch):
    ok_fake = FakeGuestVsock(_canned_responder())
    exit_code, status, _blob = _run_bridge(monkeypatch, _job_bytes("reachable"), ok_fake)
    assert exit_code == 0 and status["ok"] is True
    refused = FakeGuestVsock(_canned_responder(), accept=False)
    exit_code, status, _blob = _run_bridge(monkeypatch, _job_bytes("reachable"), refused)
    assert exit_code == 1
    assert status["ok"] is False and status["code"] == gob.BRIDGE_CONNECT_FAILED


def test_bridge_refuses_without_af_hyperv(monkeypatch):
    # A mis-discovered interpreter must still fail closed inside the helper.
    exit_code, status, _blob = _run_bridge(
        monkeypatch, _job_bytes("oracle"), af_hyperv=False
    )
    assert exit_code == 3
    assert status["ok"] is False and status["code"] == gob.BRIDGE_NO_AF_HYPERV


def test_bridge_bad_jobs_fail_closed(monkeypatch):
    # Empty stdin.
    exit_code, status, _b = _run_bridge(monkeypatch, b"")
    assert exit_code == 2 and status["code"] == gob.BRIDGE_BAD_JOB
    # Non-JSON job line.
    exit_code, status, _b = _run_bridge(monkeypatch, b"not-json\n")
    assert exit_code == 2 and status["code"] == gob.BRIDGE_BAD_JOB
    # Unknown op (the parser bridge's ops are NOT valid here — one corridor,
    # one vocabulary).
    exit_code, status, _b = _run_bridge(monkeypatch, _job_bytes("parse"))
    assert exit_code == 2 and status["code"] == gob.BRIDGE_BAD_JOB
    # Missing required endpoint key.
    job = json.loads(_job_bytes("oracle").decode("utf-8"))
    del job["vm_id"]
    exit_code, status, _b = _run_bridge(
        monkeypatch, (json.dumps(job) + "\n").encode("utf-8")
    )
    assert exit_code == 2 and status["code"] == gob.BRIDGE_BAD_JOB


def test_bridge_oracle_requires_request_frames(monkeypatch):
    fake = FakeGuestVsock(_canned_responder())
    # A frame list with only the 0-length terminator = no frames.
    stdin_payload = _job_bytes("oracle") + struct.pack("!I", 0)
    exit_code, status, _b = _run_bridge(monkeypatch, stdin_payload, fake)
    assert exit_code == 2 and status["code"] == gob.BRIDGE_BAD_JOB
    # A truncated frame list (no terminator) is also a bad job.
    stdin_payload = _job_bytes("oracle") + struct.pack("!I", 10) + b"short"
    exit_code, status, _b = _run_bridge(monkeypatch, stdin_payload, fake)
    assert exit_code == 2 and status["code"] == gob.BRIDGE_BAD_JOB


def test_bridge_garbled_guest_response_fails_closed(monkeypatch):
    def wrong_type(req):
        return [
            MessageFramer().encode(
                MessageType.ORACLE_EXEC_REQUEST,
                {"seq": 0, "chunk_count": 1, "total_bytes": 1, "data": "eA=="},
                req.request_id,
            )
        ]

    fake = FakeGuestVsock(wrong_type)
    request_frames = encode_oracle_request(
        request_id="d" * 32, snapshot_zip=b"PK-zip", oracle_path=ORACLE_PATH
    )
    stdin_payload = _job_bytes("oracle") + got._frame_list_bytes(request_frames)
    exit_code, status, frames_blob = _run_bridge(monkeypatch, stdin_payload, fake)
    assert exit_code == 1
    assert status["ok"] is False and status["code"] == gob.BRIDGE_BAD_RESPONSE
    assert frames_blob == b""  # nothing shipped on failure


def test_bridge_truncated_guest_response_fails_closed(monkeypatch):
    fake = FakeGuestVsock(_canned_responder("failed", "", "e" * 100_000), truncate_after=1)
    request_frames = encode_oracle_request(
        request_id="d" * 32, snapshot_zip=b"PK-zip", oracle_path=ORACLE_PATH
    )
    stdin_payload = _job_bytes("oracle") + got._frame_list_bytes(request_frames)
    exit_code, status, _blob = _run_bridge(monkeypatch, stdin_payload, fake)
    assert exit_code == 1
    assert status["ok"] is False and status["code"] == gob.BRIDGE_RECV_FAILED


def test_bridge_connect_refused_on_oracle_op(monkeypatch):
    fake = FakeGuestVsock(_canned_responder(), accept=False)
    request_frames = encode_oracle_request(
        request_id="d" * 32, snapshot_zip=b"PK-zip", oracle_path=ORACLE_PATH
    )
    stdin_payload = _job_bytes("oracle") + got._frame_list_bytes(request_frames)
    exit_code, status, _blob = _run_bridge(monkeypatch, stdin_payload, fake)
    assert exit_code == 1
    assert status["code"] == gob.BRIDGE_CONNECT_FAILED


def test_bridge_import_discipline_no_launcher_no_network_clients():
    # The helper runs under a DIFFERENT interpreter (3.14): it may import only
    # stdlib + the pure-Python shared.ipc modules.  No launcher, no heavy
    # fleet modules, no network clients (the air-gap posture).
    text = (REPO_ROOT / "shared" / "fleet" / "guest_oracle_bridge.py").read_text(
        encoding="utf-8"
    )
    import_lines = [
        line.strip()
        for line in text.splitlines()
        if line.startswith(("import ", "from "))
    ]
    for line in import_lines:
        assert not line.startswith(("from launcher", "import launcher")), line
        assert "httpx" not in line and "requests" not in line, line
        assert "urllib" not in line and "http.client" not in line, line
    # Only the three sanctioned shared.ipc imports.
    shared_imports = [line for line in import_lines if "shared." in line]
    assert all(
        line.startswith(
            ("from shared.ipc.oracle_channel", "from shared.ipc.protocol",
             "from shared.ipc.vsock")
        )
        for line in shared_imports
    ), shared_imports
