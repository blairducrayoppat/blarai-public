"""
Tests for VM Lifecycle Manager
================================
Tests are structured to work WITHOUT Hyper-V (mocked PowerShell calls).
The real VM operations are tested only in integration environments.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from launcher.vm_manager import (
    VMState,
    copy_file_to_vm,
    get_vm_state,
    is_guest_service_interface_enabled,
    is_admin,
    start_vm,
    stop_vm,
    verify_vm_zero_nic,
)


# ---------------------------------------------------------------------------
# VMState Tests
# ---------------------------------------------------------------------------


class TestVMState:
    """Tests for VMState enum."""

    def test_running_value(self) -> None:
        assert VMState.RUNNING.value == "Running"

    def test_off_value(self) -> None:
        assert VMState.OFF.value == "Off"

    def test_unknown_value(self) -> None:
        assert VMState.UNKNOWN.value == "Unknown"

    def test_from_string(self) -> None:
        assert VMState("Running") == VMState.RUNNING
        assert VMState("Off") == VMState.OFF

    def test_invalid_string_raises(self) -> None:
        with pytest.raises(ValueError):
            VMState("InvalidState")


# ---------------------------------------------------------------------------
# Mocked PowerShell Tests
# ---------------------------------------------------------------------------


class TestGetVMState:
    """Tests for get_vm_state with mocked PowerShell."""

    @patch("launcher.vm_manager._run_ps")
    def test_returns_running(self, mock_ps) -> None:
        mock_ps.return_value = (0, "Running", "")
        assert get_vm_state("TestVM") == VMState.RUNNING

    @patch("launcher.vm_manager._run_ps")
    def test_returns_off(self, mock_ps) -> None:
        mock_ps.return_value = (0, "Off", "")
        assert get_vm_state("TestVM") == VMState.OFF

    @patch("launcher.vm_manager._run_ps")
    def test_returns_unknown_on_error(self, mock_ps) -> None:
        mock_ps.return_value = (1, "", "VM not found")
        assert get_vm_state("TestVM") == VMState.UNKNOWN

    @patch("launcher.vm_manager._run_ps")
    def test_returns_unknown_on_empty(self, mock_ps) -> None:
        mock_ps.return_value = (0, "", "")
        assert get_vm_state("TestVM") == VMState.UNKNOWN

    @patch("launcher.vm_manager._run_ps")
    def test_returns_unknown_on_unrecognized(self, mock_ps) -> None:
        mock_ps.return_value = (0, "Suspended", "")
        assert get_vm_state("TestVM") == VMState.UNKNOWN


class TestStartVM:
    """Tests for start_vm with mocked PowerShell.

    The zero-NIC posture gate (#655) is mocked GREEN here so these cases
    keep testing the start/state mechanics in isolation; the gate's own
    behaviour is covered by TestZeroNicAssertion below.
    """

    @patch("launcher.vm_manager.verify_vm_zero_nic", return_value=True)
    @patch("launcher.vm_manager.get_vm_state")
    def test_already_running_returns_true(self, mock_state, _mock_nic) -> None:
        mock_state.return_value = VMState.RUNNING
        assert start_vm("TestVM") is True

    @patch("launcher.vm_manager.get_vm_state")
    def test_unknown_returns_false(self, mock_state) -> None:
        mock_state.return_value = VMState.UNKNOWN
        assert start_vm("TestVM") is False

    @patch("launcher.vm_manager.time")
    @patch("launcher.vm_manager._run_ps")
    @patch("launcher.vm_manager.get_vm_state")
    @patch("launcher.vm_manager.verify_vm_zero_nic", return_value=True)
    def test_start_from_off_success(
        self, _mock_nic, mock_state, mock_ps, mock_time
    ) -> None:
        # First call: OFF (triggers start), second call: RUNNING (confirms)
        mock_state.side_effect = [VMState.OFF, VMState.RUNNING]
        mock_ps.return_value = (0, "", "")
        mock_time.monotonic.side_effect = [0.0, 1.0]
        mock_time.sleep = lambda _: None
        assert start_vm("TestVM") is True

    @patch("launcher.vm_manager._run_ps")
    @patch("launcher.vm_manager.get_vm_state")
    @patch("launcher.vm_manager.verify_vm_zero_nic", return_value=True)
    def test_start_ps_failure(self, _mock_nic, mock_state, mock_ps) -> None:
        mock_state.return_value = VMState.OFF
        mock_ps.return_value = (1, "", "Access denied")
        assert start_vm("TestVM") is False


class TestZeroNicAssertion:
    """#655 LA verdict 2026-06-10: the guest VM must remain NIC-less under
    the one-door host-side-fetch composition — start_vm refuses fail-closed
    unless the adapter enumeration verifiably reports zero."""

    # — verify_vm_zero_nic unit behaviour (mocked enumeration) —

    @patch("launcher.vm_manager._run_ps")
    def test_zero_adapters_verifies(self, mock_ps) -> None:
        mock_ps.return_value = (0, "0", "")
        assert verify_vm_zero_nic("TestVM") is True
        command = mock_ps.call_args[0][0]
        assert 'Get-VMNetworkAdapter -VMName "TestVM"' in command

    @patch("launcher.vm_manager._run_ps")
    def test_one_adapter_refuses(self, mock_ps) -> None:
        mock_ps.return_value = (0, "1", "")
        assert verify_vm_zero_nic("TestVM") is False

    @patch("launcher.vm_manager._run_ps")
    def test_many_adapters_refuse(self, mock_ps) -> None:
        mock_ps.return_value = (0, "3", "")
        assert verify_vm_zero_nic("TestVM") is False

    @patch("launcher.vm_manager._run_ps")
    def test_enumeration_failure_refuses_fail_closed(self, mock_ps) -> None:
        mock_ps.return_value = (1, "", "Hyper-V module not loaded")
        assert verify_vm_zero_nic("TestVM") is False

    @patch("launcher.vm_manager._run_ps")
    def test_unparseable_count_refuses_fail_closed(self, mock_ps) -> None:
        mock_ps.return_value = (0, "garbage", "")
        assert verify_vm_zero_nic("TestVM") is False

    # — start_vm integration: the gate actually guards the start path —

    @patch("launcher.vm_manager.time")
    @patch("launcher.vm_manager._run_ps")
    @patch("launcher.vm_manager.get_vm_state")
    def test_start_proceeds_with_zero_nics(
        self, mock_state, mock_ps, mock_time
    ) -> None:
        mock_state.side_effect = [VMState.OFF, VMState.RUNNING]
        # First _run_ps call: NIC enumeration ("0"); second: Start-VM.
        mock_ps.side_effect = [(0, "0", ""), (0, "", "")]
        mock_time.monotonic.side_effect = [0.0, 1.0]
        mock_time.sleep = lambda _: None
        assert start_vm("TestVM") is True
        assert "Start-VM" in mock_ps.call_args_list[1][0][0]

    @patch("launcher.vm_manager._run_ps")
    @patch("launcher.vm_manager.get_vm_state")
    def test_start_refused_with_one_nic_and_never_starts(
        self, mock_state, mock_ps
    ) -> None:
        mock_state.return_value = VMState.OFF
        mock_ps.return_value = (0, "1", "")
        assert start_vm("TestVM") is False
        # Start-VM must never have been issued — the refusal precedes it.
        for call in mock_ps.call_args_list:
            assert "Start-VM" not in call[0][0]

    @patch("launcher.vm_manager._run_ps")
    @patch("launcher.vm_manager.get_vm_state")
    def test_start_refused_on_enumeration_failure(
        self, mock_state, mock_ps
    ) -> None:
        mock_state.return_value = VMState.OFF
        mock_ps.return_value = (1, "", "boom")
        assert start_vm("TestVM") is False
        for call in mock_ps.call_args_list:
            assert "Start-VM" not in call[0][0]

    @patch("launcher.vm_manager._run_ps")
    @patch("launcher.vm_manager.get_vm_state")
    def test_already_running_with_nic_refused(self, mock_state, mock_ps) -> None:
        """A RUNNING guest with an attached adapter is the posture violation
        itself — accepting it because 'it was already on' would launder the
        breach.  Refused fail-closed."""
        mock_state.return_value = VMState.RUNNING
        mock_ps.return_value = (0, "1", "")
        assert start_vm("TestVM") is False


class TestStopVM:
    """Tests for stop_vm with mocked PowerShell."""

    @patch("launcher.vm_manager.get_vm_state")
    def test_already_off_returns_true(self, mock_state) -> None:
        mock_state.return_value = VMState.OFF
        assert stop_vm("TestVM") is True

    @patch("launcher.vm_manager.get_vm_state")
    def test_unknown_returns_true(self, mock_state) -> None:
        """Unknown VM treated as stopped (non-fatal)."""
        mock_state.return_value = VMState.UNKNOWN
        assert stop_vm("TestVM") is True

    @patch("launcher.vm_manager.time")
    @patch("launcher.vm_manager._run_ps")
    @patch("launcher.vm_manager.get_vm_state")
    def test_stop_running_success(self, mock_state, mock_ps, mock_time) -> None:
        mock_state.side_effect = [VMState.RUNNING, VMState.OFF]
        mock_ps.return_value = (0, "", "")
        mock_time.monotonic.side_effect = [0.0, 1.0]
        mock_time.sleep = lambda _: None
        assert stop_vm("TestVM") is True


# ---------------------------------------------------------------------------
# Admin Check Tests
# ---------------------------------------------------------------------------


class TestIsAdmin:
    """Tests for is_admin()."""

    @patch("launcher.vm_manager.ctypes")
    def test_admin_true(self, mock_ctypes) -> None:
        mock_ctypes.windll.shell32.IsUserAnAdmin.return_value = 1
        assert is_admin() is True

    @patch("launcher.vm_manager.ctypes")
    def test_admin_false(self, mock_ctypes) -> None:
        mock_ctypes.windll.shell32.IsUserAnAdmin.return_value = 0
        assert is_admin() is False

    @patch("launcher.vm_manager.ctypes")
    def test_admin_error(self, mock_ctypes) -> None:
        mock_ctypes.windll.shell32.IsUserAnAdmin.side_effect = AttributeError
        assert is_admin() is False


class TestGuestIntegrationHelpers:
    """Tests for guest deployment helper methods."""

    @patch("launcher.vm_manager._run_ps")
    def test_guest_service_interface_enabled_true(self, mock_ps) -> None:
        mock_ps.return_value = (0, "True", "")
        assert is_guest_service_interface_enabled("TestVM") is True

    @patch("launcher.vm_manager._run_ps")
    def test_guest_service_interface_enabled_false(self, mock_ps) -> None:
        mock_ps.return_value = (0, "False", "")
        assert is_guest_service_interface_enabled("TestVM") is False

    def test_copy_file_to_vm_missing_source(self, tmp_path: Path) -> None:
        missing = tmp_path / "does-not-exist.txt"
        assert copy_file_to_vm(missing, "/tmp/a.txt", vm_name="TestVM") is False

    @patch("launcher.vm_manager._run_ps")
    def test_copy_file_to_vm_success(self, mock_ps, tmp_path: Path) -> None:
        source = tmp_path / "payload.txt"
        source.write_text("ok", encoding="utf-8")
        mock_ps.return_value = (0, "", "")

        ok = copy_file_to_vm(
            source,
            "/tmp/payload.txt",
            vm_name="TestVM",
        )
        assert ok is True

    @patch("launcher.vm_manager._run_ps")
    def test_copy_file_to_vm_failure(self, mock_ps, tmp_path: Path) -> None:
        source = tmp_path / "payload.txt"
        source.write_text("ok", encoding="utf-8")
        mock_ps.return_value = (1, "", "copy failed")

        ok = copy_file_to_vm(
            source,
            "/tmp/payload.txt",
            vm_name="TestVM",
        )
        assert ok is False


# ---------------------------------------------------------------------------
# EA-4 WI-9: TestRequestElevation
# ---------------------------------------------------------------------------


from launcher.vm_manager import request_elevation


class TestRequestElevation:
    """Sprint 8 EA-4 WI-9: request_elevation success + failure branches."""

    @patch("launcher.vm_manager.ctypes")
    def test_success_returns_true(self, mock_ctypes) -> None:
        """ShellExecuteW return > 32 → True."""
        mock_ctypes.windll.shell32.ShellExecuteW.return_value = 42
        assert request_elevation() is True
        mock_ctypes.windll.shell32.ShellExecuteW.assert_called_once()

    @patch("launcher.vm_manager.ctypes")
    def test_shellexecute_low_return_is_failure(self, mock_ctypes) -> None:
        """ShellExecuteW return <= 32 (e.g., user declined UAC) → False."""
        mock_ctypes.windll.shell32.ShellExecuteW.return_value = 5
        assert request_elevation() is False

    @patch("launcher.vm_manager.ctypes")
    def test_os_error_returns_false(self, mock_ctypes) -> None:
        """Raised OSError from ctypes call → False (Fail-Closed)."""
        mock_ctypes.windll.shell32.ShellExecuteW.side_effect = OSError("no windll")
        assert request_elevation() is False
