"""Tests for the orphan-guard Job Object helpers (#652 deliverable B).

The kill-on-close behaviour itself is a kernel effect that only manifests when
the launcher process actually dies, so it is verified live, not here. These
tests cover the fail-safe contract of the two public helpers — they must return
cleanly (None / False) on every failure path and never raise into the boot/launch
path — with the Win32 layer mocked so they run headless anywhere.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from launcher import orphan_guard
from launcher.orphan_guard import assign_process_to_job, create_kill_on_close_job


class TestCreateKillOnCloseJob:
    def test_non_windows_returns_none(self) -> None:
        with patch.object(orphan_guard, "_k32", return_value=None):
            assert create_kill_on_close_job() is None

    def test_create_failure_returns_none(self) -> None:
        fake = MagicMock()
        fake.CreateJobObjectW.return_value = 0  # NULL handle == failure
        with patch.object(orphan_guard, "_k32", return_value=fake), patch.object(
            orphan_guard.ctypes, "get_last_error", return_value=5
        ):
            assert create_kill_on_close_job() is None

    def test_setinformation_failure_closes_job_and_returns_none(self) -> None:
        fake = MagicMock()
        fake.CreateJobObjectW.return_value = 999
        fake.SetInformationJobObject.return_value = 0  # failure
        with patch.object(orphan_guard, "_k32", return_value=fake), patch.object(
            orphan_guard.ctypes, "get_last_error", return_value=5
        ):
            assert create_kill_on_close_job() is None
        # The orphaned job handle must be closed on the failure path.
        fake.CloseHandle.assert_called_once()

    def test_success_returns_int_handle_and_sets_kill_flag(self) -> None:
        fake = MagicMock()
        fake.CreateJobObjectW.return_value = 777
        fake.SetInformationJobObject.return_value = 1
        with patch.object(orphan_guard, "_k32", return_value=fake):
            result = create_kill_on_close_job()
        assert result == 777
        # The flag passed must include KILL_ON_JOB_CLOSE.
        args = fake.SetInformationJobObject.call_args
        info_struct = args.args[2]._obj  # ctypes.byref(...) -> ._obj
        flags = info_struct.BasicLimitInformation.LimitFlags
        assert flags & orphan_guard._JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE

    def test_exception_is_swallowed_returns_none(self) -> None:
        fake = MagicMock()
        fake.CreateJobObjectW.side_effect = OSError("boom")
        with patch.object(orphan_guard, "_k32", return_value=fake):
            assert create_kill_on_close_job() is None


class TestAssignProcessToJob:
    def test_none_job_returns_false(self) -> None:
        assert assign_process_to_job(None, 1234) is False

    def test_falsy_process_handle_returns_false(self) -> None:
        assert assign_process_to_job(555, 0) is False

    def test_assign_success_returns_true(self) -> None:
        fake = MagicMock()
        fake.AssignProcessToJobObject.return_value = 1
        with patch.object(orphan_guard, "_k32", return_value=fake):
            assert assign_process_to_job(555, 1234) is True

    def test_assign_failure_returns_false_does_not_raise(self) -> None:
        fake = MagicMock()
        fake.AssignProcessToJobObject.return_value = 0  # the CreateProcessWithTokenW conflict case
        with patch.object(orphan_guard, "_k32", return_value=fake), patch.object(
            orphan_guard.ctypes, "get_last_error", return_value=5
        ):
            assert assign_process_to_job(555, 1234) is False

    def test_exception_is_swallowed_returns_false(self) -> None:
        fake = MagicMock()
        fake.AssignProcessToJobObject.side_effect = OSError("boom")
        with patch.object(orphan_guard, "_k32", return_value=fake):
            assert assign_process_to_job(555, 1234) is False
