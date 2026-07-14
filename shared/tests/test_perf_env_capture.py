"""Tests for the perf-harness box-state capture (#816 Part 2).

Every probe is exercised through its injected seam — no real Hyper-V, no real
sockets, no real process table (the ps_runner / connector / process_names /
mem_prober parameters exist exactly so these tests never touch the box).  The
load-bearing contracts under test:

* FAIL-SOFT: no probe failure — error exit, raised exception, absent psutil —
  may ever escape :func:`capture_box_state` (a capture failure must NEVER
  break a bench run).
* HONEST UNKNOWN: a probe that cannot answer stamps the string ``"unknown"``,
  never ``False``/``[]``/an absent key — "cannot check" must not read as
  "the box was clean" (the 2026-07-10 unnoticed-VM incident class).
* SHAPE STABILITY: the capture dict carries exactly ``BOX_STATE_KEYS``, every
  key always present — downstream evidence scrapers key on it.
"""

from __future__ import annotations

import re
from typing import Any

import pytest

from shared import perf_env_capture
from shared.perf_env_capture import (
    BOX_STATE_KEYS,
    UNKNOWN,
    capture_box_state,
    capture_vm_states,
    probe_ovms_process,
    probe_port_listening,
    probe_ram_available_gib,
)

# ---------------------------------------------------------------------------
# Seam fakes
# ---------------------------------------------------------------------------


def _ps_ok(stdout: str) -> Any:
    """A PsRunner that succeeds with the given stdout."""

    def runner(command: str) -> tuple[int, str, str]:
        assert "Get-VM" in command  # the seam receives the real enumeration command
        return 0, stdout, ""

    return runner


def _ps_fail(code: int = 1, stderr: str = "access denied") -> Any:
    def runner(command: str) -> tuple[int, str, str]:
        return code, "", stderr

    return runner


def _ps_raises(command: str) -> tuple[int, str, str]:
    raise RuntimeError("runner exploded")


class _FakeSocket:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


def _connector_listening(address: tuple[str, int], timeout: float) -> _FakeSocket:
    return _FakeSocket()


def _connector_refused(address: tuple[str, int], timeout: float) -> _FakeSocket:
    raise ConnectionRefusedError("nothing listening")


def _connector_timeout(address: tuple[str, int], timeout: float) -> _FakeSocket:
    raise TimeoutError("no answer")


def _connector_broken(address: tuple[str, int], timeout: float) -> _FakeSocket:
    raise ValueError("probe machinery broke")  # non-OSError — not a port answer


# ---------------------------------------------------------------------------
# vm_states
# ---------------------------------------------------------------------------


def test_vm_states_parses_all_vms_with_states() -> None:
    out = capture_vm_states(_ps_ok("BlarAI-Orchestrator\tOff\nSomeOtherVM\tRunning"))
    assert out == [
        {"name": "BlarAI-Orchestrator", "state": "Off"},
        {"name": "SomeOtherVM", "state": "Running"},
    ]


def test_vm_states_zero_vms_is_an_honest_empty_list_not_unknown() -> None:
    # Get-VM succeeded and enumerated nothing: that IS the answer.
    assert capture_vm_states(_ps_ok("")) == []


def test_vm_states_nonzero_exit_is_unknown() -> None:
    # Non-elevated shell / Hyper-V module absent → the enumeration FAILED;
    # stamping [] here would fake a clean box (the incident class).
    assert capture_vm_states(_ps_fail()) == UNKNOWN


def test_vm_states_runner_exception_is_unknown_never_raises() -> None:
    assert capture_vm_states(_ps_raises) == UNKNOWN


def test_vm_states_malformed_line_degrades_per_line() -> None:
    out = capture_vm_states(_ps_ok("GoodVM\tRunning\nNoTabInThisLine"))
    assert out == [
        {"name": "GoodVM", "state": "Running"},
        {"name": "NoTabInThisLine", "state": UNKNOWN},
    ]


def test_vm_states_blank_lines_and_padding_are_tolerated() -> None:
    out = capture_vm_states(_ps_ok("\n  Spaced VM Name \tOff  \n\n"))
    assert out == [{"name": "Spaced VM Name", "state": "Off"}]


# ---------------------------------------------------------------------------
# port probes
# ---------------------------------------------------------------------------


def test_port_listening_true_and_socket_closed() -> None:
    seen: list[_FakeSocket] = []

    def connector(address: tuple[str, int], timeout: float) -> _FakeSocket:
        assert address == ("127.0.0.1", 5001)
        sock = _FakeSocket()
        seen.append(sock)
        return sock

    assert probe_port_listening(5001, connector=connector) is True
    assert seen and seen[0].closed  # the probe never leaks its connection


def test_port_listening_refused_is_false() -> None:
    assert probe_port_listening(5001, connector=_connector_refused) is False


def test_port_listening_timeout_is_false() -> None:
    # TimeoutError is an OSError in 3.10+: nothing answered → not listening.
    assert probe_port_listening(8000, connector=_connector_timeout) is False


def test_port_listening_non_socket_failure_is_unknown() -> None:
    assert probe_port_listening(8000, connector=_connector_broken) == UNKNOWN


# ---------------------------------------------------------------------------
# ovms process
# ---------------------------------------------------------------------------


def test_ovms_process_true_case_insensitive() -> None:
    assert probe_ovms_process(["python.exe", "OVMS.exe"]) is True
    assert probe_ovms_process(["ovms"]) is True


def test_ovms_process_false_when_absent() -> None:
    assert probe_ovms_process(["python.exe", "node.exe", ""]) is False


def test_ovms_process_unknown_when_psutil_absent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # "Cannot check" must never stamp as "no model server".
    monkeypatch.setattr(perf_env_capture, "psutil", None)
    assert probe_ovms_process(None) == UNKNOWN


def test_ovms_process_broken_iterable_is_unknown() -> None:
    def bad() -> Any:
        yield "python.exe"
        raise RuntimeError("process table vanished")

    assert probe_ovms_process(bad()) == UNKNOWN


# ---------------------------------------------------------------------------
# ram
# ---------------------------------------------------------------------------


def test_ram_available_gib_from_prober() -> None:
    assert probe_ram_available_gib(lambda: 21.5 * (1024.0**3)) == 21.5


def test_ram_available_gib_prober_failure_is_unknown() -> None:
    def boom() -> float:
        raise RuntimeError("no memory API")

    assert probe_ram_available_gib(boom) == UNKNOWN


def test_ram_available_gib_unknown_when_psutil_absent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(perf_env_capture, "psutil", None)
    assert probe_ram_available_gib(None) == UNKNOWN


# ---------------------------------------------------------------------------
# capture_box_state — assembly
# ---------------------------------------------------------------------------

_ISO_Z = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


def test_capture_box_state_full_shape_with_all_seams() -> None:
    box = capture_box_state(
        ps_runner=_ps_ok("BlarAI-Orchestrator\tRunning"),
        connector=_connector_listening,
        process_names=["ovms.exe"],
        mem_prober=lambda: 10.0 * (1024.0**3),
    )
    assert set(box) == set(BOX_STATE_KEYS)
    assert box["vm_states"] == [{"name": "BlarAI-Orchestrator", "state": "Running"}]
    assert box["ao_listening"] is True
    assert box["ovms_listening"] is True
    assert box["ovms_process"] is True
    assert box["ram_available_gib"] == 10.0
    assert _ISO_Z.match(box["captured_utc"])


def test_capture_box_state_lean_box_reads_clean() -> None:
    box = capture_box_state(
        ps_runner=_ps_ok("BlarAI-Orchestrator\tOff"),
        connector=_connector_refused,
        process_names=["python.exe"],
        mem_prober=lambda: 22.0 * (1024.0**3),
    )
    assert box["vm_states"] == [{"name": "BlarAI-Orchestrator", "state": "Off"}]
    assert box["ao_listening"] is False
    assert box["ovms_listening"] is False
    assert box["ovms_process"] is False


def test_capture_box_state_every_probe_failing_never_raises() -> None:
    # The never-break-a-bench-run contract: total probe wipeout → a complete
    # dict of honest "unknown"s, not an exception and not missing keys.
    def bad_names() -> Any:
        raise RuntimeError("boom")
        yield  # pragma: no cover — makes this a generator function

    box = capture_box_state(
        ps_runner=_ps_raises,
        connector=_connector_broken,
        process_names=bad_names(),
        mem_prober=lambda: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    assert set(box) == set(BOX_STATE_KEYS)
    assert box["vm_states"] == UNKNOWN
    assert box["ao_listening"] == UNKNOWN
    assert box["ovms_listening"] == UNKNOWN
    assert box["ovms_process"] == UNKNOWN
    assert box["ram_available_gib"] == UNKNOWN
    assert _ISO_Z.match(box["captured_utc"])  # the clock still stamps


def test_capture_box_state_ports_are_configurable() -> None:
    probed: list[tuple[str, int]] = []

    def connector(address: tuple[str, int], timeout: float) -> _FakeSocket:
        probed.append(address)
        return _FakeSocket()

    capture_box_state(
        ao_port=15001,
        ovms_port=18000,
        ps_runner=_ps_ok(""),
        connector=connector,
        process_names=[],
        mem_prober=lambda: 0.0,
    )
    assert ("127.0.0.1", 15001) in probed
    assert ("127.0.0.1", 18000) in probed


def test_box_state_keys_is_the_locked_six_key_contract() -> None:
    # The canonical shape downstream scrapers key on; changing it is a
    # deliberate schema decision, not a drive-by.
    assert BOX_STATE_KEYS == frozenset(
        {
            "vm_states",
            "ao_listening",
            "ovms_listening",
            "ovms_process",
            "ram_available_gib",
            "captured_utc",
        }
    )
