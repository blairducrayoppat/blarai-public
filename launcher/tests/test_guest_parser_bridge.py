"""
Tests for the AF_HYPERV version bridge (#655 Option A)
======================================================
The runtime venv is Python 3.11 (no ``socket.AF_HYPERV`` until 3.12), so the
launcher reaches the guest parser through a 3.14 subprocess helper.  These tests
cover the THREE moving parts WITHOUT touching a real VM / real Hyper-V / a real
AF_HYPERV socket — everything is mocked, a fake bridge executable, or loopback:

  * version-routing: 3.11 (no AF_HYPERV) → bridge path; simulated 3.12 (attr
    present) → in-process; no-bridge-found → GP_BRIDGE_UNAVAILABLE fail-closed.
  * the invoker's subprocess protocol — driven against a FAKE bridge executable
    (a tiny real Python script that returns canned status + frames over the
    documented stdin/stdout contract), and against a monkeypatched subprocess.
  * the seam-bound health probe: True on a good canned response, False (never
    raising) on garbled / timeout / unbound-bridge.
  * the seam binding registers + fails closed when unbound.

Mock surface: ``subprocess`` (fake bridge / canned), ``socket.AF_HYPERV``
presence (monkeypatched), and the parked bridge holder.  No VM, no real socket.
"""

from __future__ import annotations

import json
import socket
import struct
import sys
import textwrap
from pathlib import Path

import pytest

from launcher.guest_parser import (
    _default_transport_reachable,
    get_guest_parser_bridge,
    set_guest_parser_bridge,
)
from launcher.guest_parser_bridge import (
    BRIDGE_BAD_JOB,
    BRIDGE_NO_AF_HYPERV,
    BRIDGE_OK,
)
from launcher.guest_parser_health import (
    HEALTH_HTML,
    build_health_request_frames,
    make_health_probe,
)
from launcher.guest_parser_invoker import (
    BridgeUnavailableError,
    GuestParserBridge,
    bridge_required,
    discover_bridge_command,
)
from launcher.parser_channel_seam import (
    ParserEndpoint,
    clear_parser_channel_bindings,
    get_parser_health_probe,
    register_parser_health_probe,
)
from shared.ipc.parse_channel import (
    ChunkAssembler,
    decode_parse_request,
    encode_parse_response,
)
from shared.ipc.protocol import MessageType

_LEN = struct.Struct("!I")


@pytest.fixture(autouse=True)
def _clean_bridge_and_seam():
    """Start every test from the fail-closed default (nothing bound/parked)."""
    set_guest_parser_bridge(None)
    clear_parser_channel_bindings()
    yield
    set_guest_parser_bridge(None)
    clear_parser_channel_bindings()


def _endpoint(timeout_s: float = 1.0) -> ParserEndpoint:
    return ParserEndpoint(
        vm_id="9c7f986f-7afd-48b0-af5b-2c330df6b38f",
        service_guid="0000c351-facb-11e6-bd58-64006a7986d3",
        vsock_port=50001,
        timeout_s=timeout_s,
    )


def _frame_list_bytes(frames: list[bytes]) -> bytes:
    parts = [b"".join((_LEN.pack(len(f)), f)) for f in frames]
    parts.append(_LEN.pack(0))
    return b"".join(parts)


def _canned_health_response_frames(request_id: str) -> list[bytes]:
    """A well-formed INGEST_PARSE_RESPONSE the guest would send for the probe."""
    return encode_parse_response(
        request_id=request_id,
        status="clean",
        text="BlarAI guest parser health document.",
        title="BlarAI guest parser health",
        word_count=6,
        confidence=0.9,
        reasons=(),
    )


# ---------------------------------------------------------------------------
# Version routing
# ---------------------------------------------------------------------------


class TestVersionRouting:
    def test_bridge_required_tracks_af_hyperv_attr(self, monkeypatch) -> None:
        # Simulate a 3.11 runtime (no AF_HYPERV) → bridge required.
        monkeypatch.delattr(socket, "AF_HYPERV", raising=False)
        assert bridge_required() is True
        # Simulate a 3.12+ runtime (attr present) → bridge NOT required.
        monkeypatch.setattr(socket, "AF_HYPERV", 34, raising=False)
        assert bridge_required() is False

    def test_sub_312_routes_through_bridge(self, monkeypatch) -> None:
        """No AF_HYPERV + a parked bridge → reachability goes through the bridge."""
        monkeypatch.setattr(sys, "platform", "win32")
        monkeypatch.delattr(socket, "AF_HYPERV", raising=False)
        calls: list[ParserEndpoint] = []

        class _FakeBridge:
            def reachable(self, endpoint):
                calls.append(endpoint)
                return True

        set_guest_parser_bridge(_FakeBridge())  # type: ignore[arg-type]
        assert _default_transport_reachable(_endpoint()) is True
        assert len(calls) == 1

    def test_sub_312_no_bridge_fails_closed(self, monkeypatch) -> None:
        """No AF_HYPERV + NO bridge parked → refuse (fail-closed), never raise."""
        monkeypatch.setattr(sys, "platform", "win32")
        monkeypatch.delattr(socket, "AF_HYPERV", raising=False)
        set_guest_parser_bridge(None)
        assert _default_transport_reachable(_endpoint()) is False

    def test_312_uses_in_process_not_bridge(self, monkeypatch) -> None:
        """AF_HYPERV present → in-process path; a parked bridge is NOT consulted."""
        monkeypatch.setattr(sys, "platform", "win32")
        monkeypatch.setattr(socket, "AF_HYPERV", 34, raising=False)

        class _ExplodingBridge:
            def reachable(self, endpoint):  # pragma: no cover - must not be called
                raise AssertionError("bridge consulted on a 3.12+ interpreter")

        set_guest_parser_bridge(_ExplodingBridge())  # type: ignore[arg-type]

        # The in-process path will try to open a real AF_HYPERV socket and fail
        # (no VM) — returning False without raising and without the bridge.
        fake_sock_calls: list[tuple] = []

        def _fake_socket(*args, **kwargs):
            fake_sock_calls.append(args)
            raise OSError("no VM in test")

        monkeypatch.setattr(socket, "socket", _fake_socket)
        assert _default_transport_reachable(_endpoint()) is False
        assert fake_sock_calls, "in-process path should have attempted a socket"

    def test_bridge_reachable_exception_is_fail_closed(self, monkeypatch) -> None:
        monkeypatch.setattr(sys, "platform", "win32")
        monkeypatch.delattr(socket, "AF_HYPERV", raising=False)

        class _RaisingBridge:
            def reachable(self, endpoint):
                raise RuntimeError("boom")

        set_guest_parser_bridge(_RaisingBridge())  # type: ignore[arg-type]
        assert _default_transport_reachable(_endpoint()) is False


# ---------------------------------------------------------------------------
# Interpreter discovery
# ---------------------------------------------------------------------------


class TestDiscovery:
    def test_no_candidate_qualifies_raises(self, monkeypatch) -> None:
        # Every candidate fails the AF_HYPERV probe → GP_BRIDGE_UNAVAILABLE.
        monkeypatch.setattr(
            "launcher.guest_parser_invoker._interp_has_af_hyperv",
            lambda command: False,
        )
        with pytest.raises(BridgeUnavailableError) as exc_info:
            discover_bridge_command()
        assert exc_info.value.code == "GP_BRIDGE_UNAVAILABLE"

    def test_explicit_bridge_python_is_first_candidate(self, monkeypatch) -> None:
        seen: list[list[str]] = []

        def _probe(command):
            seen.append(command)
            return command == ["C:/py314/python.exe"]

        monkeypatch.setattr(
            "launcher.guest_parser_invoker._interp_has_af_hyperv", _probe
        )
        cmd = discover_bridge_command(bridge_python="C:/py314/python.exe")
        assert cmd == ["C:/py314/python.exe"]
        assert seen[0] == ["C:/py314/python.exe"]  # tried FIRST

    def test_discovery_never_uses_311_runtime(self, monkeypatch) -> None:
        """The running interpreter is never a discovery candidate."""
        captured: list[list[str]] = []

        def _probe(command):
            captured.append(command)
            return False

        monkeypatch.setattr(
            "launcher.guest_parser_invoker._interp_has_af_hyperv", _probe
        )
        with pytest.raises(BridgeUnavailableError):
            discover_bridge_command()
        for command in captured:
            assert sys.executable not in command, (
                "the 3.11 runtime sys.executable must never be a bridge candidate"
            )


# ---------------------------------------------------------------------------
# Invoker subprocess protocol — against a FAKE BRIDGE EXECUTABLE
# ---------------------------------------------------------------------------


# A tiny real Python script standing in for launcher.guest_parser_bridge.  It
# speaks the documented stdin/stdout contract: read the job line, (for
# health/parse) read the length-prefixed request frames, emit a JSON status
# line, then (for parse) the canned response frames.  Driven as a REAL
# subprocess so the invoker's process/pipe protocol is exercised for real.
_FAKE_BRIDGE_SRC = textwrap.dedent(
    """
    import json, struct, sys
    LEN = struct.Struct("!I")
    def read_exact(n):
        buf = b""
        while len(buf) < n:
            c = sys.stdin.buffer.read(n - len(buf))
            if not c:
                return None
            buf += c
        return buf
    def read_frames():
        frames = []
        while True:
            h = read_exact(4)
            (length,) = LEN.unpack(h)
            if length == 0:
                return frames
            frames.append(read_exact(length))
    job = json.loads(sys.stdin.buffer.readline().decode("utf-8"))
    op = job["op"]
    mode = "{mode}"
    if op in ("health", "parse"):
        req = read_frames()
    if mode == "ok":
        if op == "reachable":
            print(json.dumps({{"ok": True, "code": "OK", "op": op, "frames": 0, "message": ""}}))
        elif op == "health":
            print(json.dumps({{"ok": True, "code": "OK", "op": op, "frames": 0, "message": ""}}))
        else:  # parse — echo canned frames
            resp = {resp_frames!r}
            print(json.dumps({{"ok": True, "code": "OK", "op": op, "frames": len(resp), "message": ""}}))
            sys.stdout.flush()
            for f in resp:
                sys.stdout.buffer.write(LEN.pack(len(f)))
                sys.stdout.buffer.write(f)
            sys.stdout.buffer.write(LEN.pack(0))
            sys.stdout.buffer.flush()
            sys.exit(0)
        sys.exit(0)
    elif mode == "fail":
        print(json.dumps({{"ok": False, "code": "BRIDGE_CONNECT_FAILED", "op": op, "frames": 0, "message": "x"}}))
        sys.exit(1)
    elif mode == "garbled":
        sys.stdout.write("this is not json\\n")
        sys.exit(1)
    """
)


def _write_fake_bridge(
    tmp_path: Path, *, mode: str, resp_frames: list[bytes] | None = None
) -> Path:
    src = _FAKE_BRIDGE_SRC.format(mode=mode, resp_frames=resp_frames or [])
    path = tmp_path / "fake_bridge.py"
    path.write_text(src, encoding="utf-8")
    return path


def _bridge_with_fake(
    tmp_path: Path, *, mode: str, resp_frames: list[bytes] | None = None
) -> GuestParserBridge:
    """A GuestParserBridge whose 'module' is the fake bridge script (run by path).

    ``_command`` bypasses discovery; the invoker runs ``<python> -m <module>``
    so we point the module at the fake script's import name on a PYTHONPATH that
    includes tmp_path.
    """
    fake = _write_fake_bridge(tmp_path, mode=mode, resp_frames=resp_frames)
    # Run the fake as a plain script path: command = [python], module = the
    # script path used with -m won't work (it's not a package), so instead we
    # set _command to [python, str(fake_path)] and bridge_module to a no-op by
    # pointing the invoker at running the file directly.  The invoker always
    # appends ["-m", module]; to run a file we wrap: command runs the file and
    # ignores the trailing "-m module" by making module a harmless flag-less
    # arg is not possible — so we use a sitecustomize-free approach: put the
    # fake on sys.path and import it as a module.
    repo_root = tmp_path
    return GuestParserBridge(
        _command=[sys.executable],
        bridge_module="fake_bridge",
        repo_root=repo_root,
        mtls_cert="",
        mtls_key="",
        mtls_ca="",
    )


class TestInvokerSubprocessProtocol:
    def test_reachable_ok(self, tmp_path) -> None:
        bridge = _bridge_with_fake(tmp_path, mode="ok")
        assert bridge.reachable(_endpoint()) is True

    def test_reachable_fail(self, tmp_path) -> None:
        bridge = _bridge_with_fake(tmp_path, mode="fail")
        assert bridge.reachable(_endpoint()) is False

    def test_health_ok(self, tmp_path) -> None:
        bridge = _bridge_with_fake(tmp_path, mode="ok")
        frames = build_health_request_frames("rid-health")
        assert bridge.health(_endpoint(), frames) is True

    def test_parse_returns_canned_frames(self, tmp_path) -> None:
        canned = _canned_health_response_frames("rid-parse")
        bridge = _bridge_with_fake(tmp_path, mode="ok", resp_frames=canned)
        frames = build_health_request_frames("rid-parse")
        out = bridge.parse(_endpoint(), frames)
        assert out is not None
        # The returned frames re-assemble into a decodable response.
        assembler = ChunkAssembler(MessageType.INGEST_PARSE_RESPONSE)
        for f in out:
            done = assembler.feed(f)
        assert done is True

    def test_parse_failure_returns_none(self, tmp_path) -> None:
        bridge = _bridge_with_fake(tmp_path, mode="fail")
        frames = build_health_request_frames("rid")
        assert bridge.parse(_endpoint(), frames) is None

    def test_garbled_output_is_fail_closed(self, tmp_path) -> None:
        bridge = _bridge_with_fake(tmp_path, mode="garbled")
        assert bridge.reachable(_endpoint()) is False
        frames = build_health_request_frames("rid")
        assert bridge.health(_endpoint(), frames) is False

    def test_missing_bridge_executable_is_fail_closed(self, tmp_path) -> None:
        bridge = GuestParserBridge(
            _command=[str(tmp_path / "does_not_exist.exe")],
            bridge_module="fake_bridge",
            repo_root=tmp_path,
        )
        assert bridge.reachable(_endpoint()) is False

    def test_request_frames_reach_the_bridge(self, tmp_path) -> None:
        """The bridge receives the exact request frames the invoker sent."""
        # A fake that re-emits the REQUEST it received as the parse response
        # frames so we can assert the invoker shipped them intact.
        src = textwrap.dedent(
            """
            import json, struct, sys
            LEN = struct.Struct("!I")
            def read_exact(n):
                buf = b""
                while len(buf) < n:
                    c = sys.stdin.buffer.read(n - len(buf))
                    if not c:
                        return None
                    buf += c
                return buf
            def read_frames():
                frames = []
                while True:
                    (length,) = LEN.unpack(read_exact(4))
                    if length == 0:
                        return frames
                    frames.append(read_exact(length))
            job = json.loads(sys.stdin.buffer.readline().decode("utf-8"))
            req = read_frames()
            print(json.dumps({"ok": True, "code": "OK", "op": "parse",
                              "frames": len(req), "message": ""}))
            sys.stdout.flush()
            for f in req:
                sys.stdout.buffer.write(LEN.pack(len(f)))
                sys.stdout.buffer.write(f)
            sys.stdout.buffer.write(LEN.pack(0))
            sys.stdout.buffer.flush()
            """
        )
        (tmp_path / "fake_bridge.py").write_text(src, encoding="utf-8")
        bridge = GuestParserBridge(
            _command=[sys.executable],
            bridge_module="fake_bridge",
            repo_root=tmp_path,
        )
        sent = build_health_request_frames("rid-echo")
        echoed = bridge.parse(_endpoint(), sent)
        assert echoed == sent

        # And the echoed request decodes to the health HTML — full fidelity.
        assembler = ChunkAssembler(MessageType.INGEST_PARSE_REQUEST)
        for f in echoed:
            assembler.feed(f)
        request = decode_parse_request(assembler)
        assert request.html == HEALTH_HTML


# ---------------------------------------------------------------------------
# The real bridge helper's job/protocol handling (transport injected)
# ---------------------------------------------------------------------------


class TestBridgeHelperJobParsing:
    def _run_bridge(self, stdin_bytes: bytes, monkeypatch) -> tuple[int, dict]:
        """Run launcher.guest_parser_bridge.run() in-process with patched stdin
        capture of stdout — exercises the real job/frame/status code paths.

        AF_HYPERV is forced present so the helper does not early-exit; the
        transport is replaced so no real socket is opened.
        """
        import io

        from launcher import guest_parser_bridge as gpb

        monkeypatch.setattr(socket, "AF_HYPERV", 34, raising=False)

        out_buf = io.BytesIO()

        class _Stdout:
            buffer = out_buf

            def __init__(self):
                self._text = io.StringIO()

            def write(self, s):
                self._text.write(s)

            def flush(self):
                pass

            def getvalue(self):
                return self._text.getvalue()

        class _Stdin:
            buffer = io.BytesIO(stdin_bytes)

        fake_out = _Stdout()
        monkeypatch.setattr(gpb.sys, "stdout", fake_out)
        monkeypatch.setattr(gpb.sys, "stdin", _Stdin())
        code = gpb.run([])
        status_line = fake_out.getvalue().splitlines()[0]
        return code, json.loads(status_line)

    def test_empty_stdin_is_bad_job(self, monkeypatch) -> None:
        code, status = self._run_bridge(b"", monkeypatch)
        assert status["ok"] is False
        assert status["code"] == BRIDGE_BAD_JOB
        assert code == 2

    def test_unknown_op_is_bad_job(self, monkeypatch) -> None:
        job = json.dumps(
            {
                "op": "frobnicate",
                "vm_id": "a",
                "service_guid": "b",
                "vsock_port": 50001,
                "timeout_s": 1.0,
            }
        ).encode("utf-8")
        code, status = self._run_bridge(job + b"\n", monkeypatch)
        assert status["ok"] is False
        assert status["code"] == BRIDGE_BAD_JOB

    def test_missing_af_hyperv_is_loud(self, monkeypatch) -> None:
        import io

        from launcher import guest_parser_bridge as gpb

        monkeypatch.delattr(socket, "AF_HYPERV", raising=False)

        class _Stdout:
            buffer = io.BytesIO()

            def __init__(self):
                self._text = io.StringIO()

            def write(self, s):
                self._text.write(s)

            def flush(self):
                pass

            def getvalue(self):
                return self._text.getvalue()

        class _Stdin:
            buffer = io.BytesIO(b"")

        fake_out = _Stdout()
        monkeypatch.setattr(gpb.sys, "stdout", fake_out)
        monkeypatch.setattr(gpb.sys, "stdin", _Stdin())
        code = gpb.run([])
        status = json.loads(fake_out.getvalue().splitlines()[0])
        assert status["code"] == BRIDGE_NO_AF_HYPERV
        assert code == 3

    def test_reachable_op_round_trip(self, monkeypatch) -> None:
        """A 'reachable' job with a fake transport that connects → ok=True."""
        from launcher import guest_parser_bridge as gpb

        class _FakeTransport:
            def connect(self):
                return True

            def close(self):
                pass

        monkeypatch.setattr(gpb, "_build_transport", lambda job: _FakeTransport())
        job = json.dumps(
            {
                "op": "reachable",
                "vm_id": "a",
                "service_guid": "b",
                "vsock_port": 50001,
                "timeout_s": 1.0,
            }
        ).encode("utf-8")
        code, status = self._run_bridge(job + b"\n", monkeypatch)
        assert status["ok"] is True
        assert status["code"] == BRIDGE_OK
        assert code == 0


# ---------------------------------------------------------------------------
# Seam-bound health probe
# ---------------------------------------------------------------------------


class TestHealthProbe:
    def test_probe_true_on_good_bridge_response(self) -> None:
        request_seen: list[list[bytes]] = []

        class _GoodBridge:
            def health(self, endpoint, request_frames):
                request_seen.append(request_frames)
                return True

        set_guest_parser_bridge(_GoodBridge())  # type: ignore[arg-type]
        probe = make_health_probe()
        assert probe(_endpoint()) is True
        # The probe sent a real health request (the fixed HTML).
        assert request_seen and len(request_seen[0]) >= 1

    def test_probe_false_on_bridge_false(self) -> None:
        class _BadBridge:
            def health(self, endpoint, request_frames):
                return False

        set_guest_parser_bridge(_BadBridge())  # type: ignore[arg-type]
        probe = make_health_probe()
        assert probe(_endpoint()) is False

    def test_probe_never_raises_on_bridge_exception(self) -> None:
        class _RaisingBridge:
            def health(self, endpoint, request_frames):
                raise RuntimeError("garbled")

        set_guest_parser_bridge(_RaisingBridge())  # type: ignore[arg-type]
        probe = make_health_probe()
        # Must return False, never propagate.
        assert probe(_endpoint()) is False

    def test_probe_false_when_no_bridge_and_no_af_hyperv(self, monkeypatch) -> None:
        """3.11 + no bridge → no path to the guest → False (fail-closed)."""
        monkeypatch.delattr(socket, "AF_HYPERV", raising=False)
        set_guest_parser_bridge(None)
        probe = make_health_probe()
        assert probe(_endpoint()) is False


# ---------------------------------------------------------------------------
# Seam binding + fail-closed-when-unbound (the GP_CHANNEL_UNBOUND resolution)
# ---------------------------------------------------------------------------


class TestSeamBinding:
    def test_unbound_seam_fails_closed(self) -> None:
        clear_parser_channel_bindings()
        assert get_parser_health_probe() is None

    def test_register_real_probe_binds_it(self) -> None:
        probe = make_health_probe()
        register_parser_health_probe(probe)
        assert get_parser_health_probe() is probe

    def test_bound_probe_is_callable_and_fail_closed(self, monkeypatch) -> None:
        """The bound probe returns a bool (never raises) even with no transport."""
        monkeypatch.delattr(socket, "AF_HYPERV", raising=False)
        set_guest_parser_bridge(None)
        register_parser_health_probe(make_health_probe())
        bound = get_parser_health_probe()
        assert bound is not None
        result = bound(_endpoint())
        assert result is False  # no path → fail-closed, no exception


# ---------------------------------------------------------------------------
# Launcher orchestration: _maybe_start_guest_parser builds the bridge + binds
# the probe BEFORE start(), and fails closed (manager FAILED, boot alive) when
# the bridge cannot be resolved.
# ---------------------------------------------------------------------------


def _enabled_config():
    from launcher.guest_parser import GuestParserConfig, hv_service_guid_for_port

    return GuestParserConfig(
        enabled=True,
        vm_name="TestVM",
        guest_root="/opt/blarai/parser",
        vsock_port=50001,
        service_guid=hv_service_guid_for_port(50001),
        service_source_dir="services/cleaner/guest",
        entry_module="blarai_guest_parser",
        deploy_timeout_s=30.0,
        health_timeout_s=5.0,
        health_poll_interval_s=0.01,
        bridge_python="",
    )


class TestLauncherBridgeWiring:
    def test_bridge_unavailable_fails_closed_boot_alive(self, monkeypatch) -> None:
        """No 3.14 interpreter → GP_BRIDGE_UNAVAILABLE, manager returned (boot
        continues), capability unavailable — NEVER a pretended READY."""
        from unittest.mock import patch

        from launcher.__main__ import _maybe_start_guest_parser
        from launcher.guest_parser import (
            GuestParserState,
            guest_parser_available,
            set_guest_parser_manager,
        )

        set_guest_parser_manager(None)
        with patch(
            "launcher.guest_parser.load_guest_parser_config",
            return_value=_enabled_config(),
        ), patch(
            "launcher.guest_parser_invoker.bridge_required", return_value=True
        ), patch(
            "launcher.guest_parser_invoker.discover_bridge_command",
            side_effect=BridgeUnavailableError("no 3.14 found"),
        ):
            result = _maybe_start_guest_parser()

        assert result is not None  # manager returned (boot not aborted)
        assert result.state != GuestParserState.READY
        assert guest_parser_available() is False
        # No probe should have been bound (we never reached the bind step).
        assert get_guest_parser_bridge() is None

    def test_bridge_resolved_binds_probe_and_reaches_ready(
        self, monkeypatch, tmp_path
    ) -> None:
        """Bridge resolved + probe green + transport reachable → READY, and the
        seam probe is bound by the launcher (not pre-bound by the test)."""
        from unittest.mock import patch

        from launcher.__main__ import _maybe_start_guest_parser
        from launcher.guest_parser import (
            GuestParserManager,
            GuestParserState,
            guest_parser_available,
            set_guest_parser_manager,
        )
        from launcher.vm_manager import VMState

        (tmp_path / "services" / "cleaner" / "guest").mkdir(parents=True)
        (tmp_path / "services" / "cleaner" / "guest" / "x.py").write_text(
            "# placeholder\n", encoding="utf-8"
        )
        set_guest_parser_manager(None)

        real_init = GuestParserManager.__init__

        def init_with_seams(self, cfg, **kwargs):
            kwargs.setdefault("repo_root", tmp_path)
            kwargs.setdefault("transport_check", lambda endpoint: True)
            real_init(self, cfg, **kwargs)

        fake_bridge = object()
        with patch(
            "launcher.guest_parser.load_guest_parser_config",
            return_value=_enabled_config(),
        ), patch.object(
            GuestParserManager, "__init__", init_with_seams
        ), patch(
            "launcher.guest_parser_invoker.bridge_required", return_value=True
        ), patch(
            "launcher.guest_parser_invoker.GuestParserBridge",
            return_value=_StubBridge(),
        ), patch(
            "launcher.guest_parser.get_vm_state", return_value=VMState.RUNNING
        ), patch(
            "launcher.guest_parser.is_guest_service_interface_enabled",
            return_value=True,
        ), patch(
            "launcher.guest_parser.copy_file_to_vm", return_value=True
        ):
            result = _maybe_start_guest_parser()

        assert result is not None
        assert result.state == GuestParserState.READY
        assert guest_parser_available() is True
        # The launcher bound a real probe to the seam.
        assert get_parser_health_probe() is not None


class _StubBridge:
    """A bridge that always answers reachable/health True (no subprocess)."""

    command = ["py", "-3.14"]

    def reachable(self, endpoint):
        return True

    def health(self, endpoint, request_frames):
        return True

    def parse(self, endpoint, request_frames):
        return request_frames


# ---------------------------------------------------------------------------
# Bridge transport selection — plaintext-AF_HYPERV vs mTLS (#655)
# ---------------------------------------------------------------------------


class TestBridgeTransportSelection:
    """``_build_transport`` selects the plaintext-AF_HYPERV bring-up path when the
    job carries no mTLS material, and the AF_HYPERV+mTLS path when it does.

    Locks the #655 decoupling at the bridge seam: the bridge no longer carries a
    bespoke transport subclass — it constructs a stock ``VsockTransport`` with the
    explicit ``allow_plaintext_hyperv`` opt-in.  No real socket is opened.
    """

    @staticmethod
    def _job(*, mtls: bool) -> dict:
        job = {
            "op": "parse",
            "vm_id": "9c7f986f-7afd-48b0-af5b-2c330df6b38f",
            "service_guid": "0000c351-facb-11e6-bd58-64006a7986d3",
            "vsock_port": 50001,
            "timeout_s": 1.0,
            "mtls_cert": "",
            "mtls_key": "",
            "mtls_ca": "",
        }
        if mtls:
            job["mtls_cert"] = "host.pem"
            job["mtls_key"] = "host.key"
            job["mtls_ca"] = "ca.pem"
        return job

    def test_no_mtls_job_selects_plaintext_hyperv(self) -> None:
        """A job with empty mTLS material → allow_plaintext_hyperv=True transport."""
        from launcher.guest_parser_bridge import _build_transport

        transport = _build_transport(self._job(mtls=False))
        # Stock VsockTransport, guest-mode, plaintext bring-up opt-in set.
        assert transport.dev_mode is False
        assert transport.host_mode is False
        assert transport.config.allow_plaintext_hyperv is True
        assert transport._is_plaintext_hyperv() is True

    def test_mtls_job_does_not_select_plaintext(self) -> None:
        """A job WITH mTLS material → mTLS path (plaintext opt-in inert/off)."""
        from launcher.guest_parser_bridge import _build_transport

        transport = _build_transport(self._job(mtls=True))
        assert transport.dev_mode is False
        assert transport.host_mode is False
        # mTLS material present → not the plaintext path (mTLS wins).
        assert transport._is_plaintext_hyperv() is False
        assert transport.config.mtls_cert_path == "host.pem"

    def test_built_transport_is_stock_vsock_transport(self) -> None:
        """The bridge builds a plain VsockTransport (no bespoke subclass, #655)."""
        from shared.ipc.vsock import VsockTransport

        from launcher.guest_parser_bridge import _build_transport

        transport = _build_transport(self._job(mtls=False))
        assert type(transport) is VsockTransport
