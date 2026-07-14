"""Tests for de-elevated WinUI launch (ADR-019).

The Medium-integrity launch primitive itself is a Windows token operation that
needs an elevated launcher to exercise meaningfully (verified live on the Arc
140V host, 2026-06-03). These tests cover the orchestration and the pure
helpers that do not require elevation, mocking the privilege boundary so they
run anywhere.
"""

from __future__ import annotations

import subprocess
from unittest.mock import MagicMock, patch

import pytest

from launcher import process_launch
from launcher.process_launch import (
    _WAIT_FAILED,
    _WAIT_OBJECT_0,
    _WAIT_SUPERVISORY_INTERVAL_S,
    _WAIT_TIMEOUT,
    _HandleProc,
    _integrity_rid_name,
    launch_winui,
)

_EXE = r"C:\app\BlarAI.Desktop.exe"


class TestIntegrityRidName:
    """The integrity-level RID → human name mapping used in launch logs."""

    def test_known_levels(self) -> None:
        assert _integrity_rid_name(0x1000) == "Low"
        assert _integrity_rid_name(0x2000) == "Medium"
        assert _integrity_rid_name(0x3000) == "High"
        assert _integrity_rid_name(0x4000) == "System"

    def test_none_is_unknown(self) -> None:
        assert _integrity_rid_name(None) == "unknown"

    def test_unrecognised_rid_renders_hex(self) -> None:
        assert _integrity_rid_name(0x9999) == "0x9999"


class TestLaunchWinui:
    """The fail-safe orchestration: medium when elevated, else plain launch."""

    def test_not_elevated_uses_plain_popen(self) -> None:
        sentinel = MagicMock()
        with patch.object(process_launch, "_is_elevated", return_value=False), patch.object(
            process_launch.subprocess, "Popen", return_value=sentinel
        ) as popen, patch.object(process_launch, "launch_medium_integrity") as medium:
            result = launch_winui(_EXE)
        assert result is sentinel
        popen.assert_called_once_with([_EXE])
        medium.assert_not_called()

    def test_elevated_uses_medium_integrity(self) -> None:
        sentinel = MagicMock()
        with patch.object(process_launch, "_is_elevated", return_value=True), patch.object(
            process_launch, "launch_medium_integrity", return_value=sentinel
        ) as medium, patch.object(process_launch.subprocess, "Popen") as popen:
            result = launch_winui(_EXE)
        assert result is sentinel
        medium.assert_called_once()
        popen.assert_not_called()

    def test_elevated_falls_back_to_popen_when_medium_unavailable(self) -> None:
        sentinel = MagicMock()
        with patch.object(process_launch, "_is_elevated", return_value=True), patch.object(
            process_launch, "launch_medium_integrity", return_value=None
        ), patch.object(
            process_launch.subprocess, "Popen", return_value=sentinel
        ) as popen:
            result = launch_winui(_EXE)
        assert result is sentinel
        popen.assert_called_once_with([_EXE])


class TestHandleProc:
    """The Popen-shaped wrapper's contract used by ``_run_winui_surface``."""

    def test_initial_state(self) -> None:
        proc = _HandleProc(h_process=0, pid=4321)
        assert proc.pid == 4321
        assert proc.returncode is None
        # The surface relies on these attributes existing (drop-in for Popen).
        assert hasattr(proc, "wait")


class TestHandleProcWait:
    """The bounded-chunk child-wait (#812 / AUDIT-13): no unconditional INFINITE."""

    @staticmethod
    def _mock_k32(wait_results):
        """A kernel32 stand-in whose WaitForSingleObject yields *wait_results*."""
        k32 = MagicMock()
        k32.WaitForSingleObject.side_effect = list(wait_results)
        # GetExitCodeProcess is a no-op mock, so the real DWORD out-param stays
        # at its zero default → returncode 0 (deterministic).
        k32.GetExitCodeProcess.return_value = 1
        k32.CloseHandle.return_value = 1
        return k32

    def test_polls_in_bounded_chunks_until_exit(self) -> None:
        # TIMEOUT twice (child still up) then OBJECT_0 (it exited): the loop must
        # wake each chunk rather than block once on _INFINITE.
        k32 = self._mock_k32([_WAIT_TIMEOUT, _WAIT_TIMEOUT, _WAIT_OBJECT_0])
        proc = _HandleProc(h_process=1234, pid=4321)
        with patch.object(process_launch.ctypes, "WinDLL", return_value=k32):
            rc = proc.wait()
        assert rc == 0
        assert proc.returncode == 0
        assert k32.WaitForSingleObject.call_count == 3
        # every wait used the bounded supervisory chunk, never _INFINITE.
        expected_ms = int(_WAIT_SUPERVISORY_INTERVAL_S * 1000)
        waited_ms = [c.args[1] for c in k32.WaitForSingleObject.call_args_list]
        assert waited_ms == [expected_ms, expected_ms, expected_ms]
        assert process_launch._INFINITE not in waited_ms
        k32.CloseHandle.assert_called_once()

    def test_immediate_exit_closes_handle_once(self) -> None:
        k32 = self._mock_k32([_WAIT_OBJECT_0])
        proc = _HandleProc(h_process=99, pid=7)
        with patch.object(process_launch.ctypes, "WinDLL", return_value=k32):
            rc = proc.wait()
        assert rc == 0
        assert k32.WaitForSingleObject.call_count == 1
        k32.CloseHandle.assert_called_once()

    def test_wait_failed_breaks_gracefully(self) -> None:
        # A failed wait must not spin forever: break, read the code, close.
        k32 = self._mock_k32([_WAIT_FAILED])
        proc = _HandleProc(h_process=5, pid=8)
        with patch.object(process_launch.ctypes, "WinDLL", return_value=k32):
            rc = proc.wait()
        assert isinstance(rc, int)
        assert k32.WaitForSingleObject.call_count == 1
        k32.CloseHandle.assert_called_once()

    def test_timeout_raises_and_preserves_handle(self) -> None:
        # WaitForSingleObject never signals; a bounded timeout must raise
        # TimeoutExpired (Popen parity) and NOT close the still-open handle.
        k32 = self._mock_k32([_WAIT_TIMEOUT, _WAIT_TIMEOUT, _WAIT_TIMEOUT])
        proc = _HandleProc(h_process=3, pid=11)
        # deadline=1001.0; iter1 remaining 0.5 (>0 → one wait); iter2 remaining
        # -1.0 (≤0 → raise). Exactly one WaitForSingleObject, three monotonics.
        monotonic = MagicMock(side_effect=[1000.0, 1000.5, 1002.0])
        with patch.object(
            process_launch.ctypes, "WinDLL", return_value=k32
        ), patch.object(process_launch.time, "monotonic", monotonic):
            with pytest.raises(subprocess.TimeoutExpired):
                proc.wait(timeout=1.0)
        assert proc.returncode is None  # never completed
        assert k32.WaitForSingleObject.call_count == 1
        k32.CloseHandle.assert_not_called()  # handle preserved for a retry

    def test_cached_returncode_short_circuits(self) -> None:
        proc = _HandleProc(h_process=1, pid=2)
        proc.returncode = 3
        # A known result must not touch kernel32 at all (no double CloseHandle).
        with patch.object(
            process_launch.ctypes, "WinDLL", side_effect=AssertionError("touched")
        ):
            assert proc.wait() == 3
