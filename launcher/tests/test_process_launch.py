"""Tests for de-elevated WinUI launch (ADR-019).

The Medium-integrity launch primitive itself is a Windows token operation that
needs an elevated launcher to exercise meaningfully (verified live on the Arc
140V host, 2026-06-03). These tests cover the orchestration and the pure
helpers that do not require elevation, mocking the privilege boundary so they
run anywhere.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from launcher import process_launch
from launcher.process_launch import (
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
