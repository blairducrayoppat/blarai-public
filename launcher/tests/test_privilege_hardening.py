"""Tests for launcher token privilege-stripping (#652 D-a).

The real strip is a Windows token operation that, on an elevated launcher,
permanently removes privileges from the *current* process for its lifetime —
which a test must never do to itself (it would alter the pytest process and
every subsequent test). So these tests mock the token enumeration + the
per-privilege removal and assert the pure keep/remove DECISION logic and the
fail-safe contract. They are headless and run anywhere.

What is covered:
  * the keep-allowlist is honoured (SeChangeNotify + SeImpersonate always kept;
    the two #637 owner/DACL privileges kept);
  * classic escalation privileges (SeDebug, SeLoadDriver, SeTcb, …) are marked
    for removal;
  * the report shape (removed / kept / errors), sorted;
  * fail-safe: a simulated API failure at every stage returns a report and never
    raises, and a privilege the API declines to remove lands in ``errors`` (not
    silently dropped from the accounting).
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from launcher import privilege_hardening
from launcher.privilege_hardening import (
    KEEP_PRIVILEGES,
    strip_unused_privileges,
)


# A representative elevated-launcher privilege set: the two hard-required keeps,
# the two conservative #637 keeps, and a spread of classic escalation privileges
# that MUST be removed. Names are the canonical Se* identifiers.
_KEPT_NAMES = [
    "SeChangeNotifyPrivilege",
    "SeImpersonatePrivilege",
    "SeRestorePrivilege",
    "SeTakeOwnershipPrivilege",
]
_REMOVE_NAMES = [
    "SeDebugPrivilege",
    "SeLoadDriverPrivilege",
    "SeTcbPrivilege",
    "SeBackupPrivilege",
    "SeCreateTokenPrivilege",
    "SeAssignPrimaryTokenPrivilege",
    "SeSecurityPrivilege",
    "SeShutdownPrivilege",
    "SeSystemEnvironmentPrivilege",
    "SeManageVolumePrivilege",
]


def _fake_enumeration(names: list[str]) -> list[tuple[object, str, bool]]:
    """Build a fake ``_enumerate_privileges`` return: (luid, name, enabled) triples.

    The LUID is a throwaway sentinel — the decision logic keys on the NAME only,
    and ``_remove_privilege`` is mocked, so the LUID is never dereferenced.
    """
    return [(object(), name, True) for name in names]


def _patched_strip(
    names: list[str],
    *,
    remove_returns: bool = True,
):
    """Run ``strip_unused_privileges`` with the token layer fully mocked.

    Patches the platform/elevation/handle plumbing so no real token is touched,
    feeds *names* as the enumerated privileges, and makes every removal report
    *remove_returns*. Returns the report dict.
    """
    with patch.object(privilege_hardening.sys, "platform", "win32"), patch.object(
        privilege_hardening,
        "_api",
        return_value=(_FakeAdvapi32WithOpen(open_succeeds=True), _FakeKernel32()),
    ), patch.object(
        privilege_hardening, "_enumerate_privileges", return_value=_fake_enumeration(names)
    ), patch.object(
        privilege_hardening, "_remove_privilege", return_value=remove_returns
    ), patch.object(
        privilege_hardening, "_is_elevated", return_value=True
    ), patch.object(
        privilege_hardening.ctypes, "get_last_error", return_value=0
    ):
        # token = wintypes.HANDLE() stays a REAL (empty) ctypes handle so
        # ctypes.byref(token) works; the OpenProcessToken stub ignores it.
        return strip_unused_privileges()


class _FakeKernel32:
    """Minimal kernel32 stub: a truthy current-process handle + a no-op close."""

    def GetCurrentProcess(self) -> int:  # noqa: N802 - mirrors Win32 name
        return -1  # pseudo-handle, truthy

    def CloseHandle(self, handle: object) -> bool:  # noqa: N802
        return True


class _FakeAdvapi32WithOpen:
    """advapi32 stub whose ``OpenProcessToken`` outcome is configurable."""

    def __init__(self, *, open_succeeds: bool) -> None:
        self._open_succeeds = open_succeeds

    def OpenProcessToken(self, proc, access, out_handle) -> int:  # noqa: N802
        return 1 if self._open_succeeds else 0


class TestKeepRemoveDecision:
    """The allowlist decision: keep the allowlisted, remove everything else."""

    def test_keeps_change_notify_and_impersonate_always(self) -> None:
        report = _patched_strip(_KEPT_NAMES + _REMOVE_NAMES)
        assert "SeChangeNotifyPrivilege" in report["kept"]
        assert "SeImpersonatePrivilege" in report["kept"]

    def test_keeps_637_owner_dacl_privileges(self) -> None:
        report = _patched_strip(_KEPT_NAMES + _REMOVE_NAMES)
        # Conservative-keep-on-doubt for the #637 owner/DACL path.
        assert "SeRestorePrivilege" in report["kept"]
        assert "SeTakeOwnershipPrivilege" in report["kept"]

    def test_removes_classic_escalation_privileges(self) -> None:
        report = _patched_strip(_KEPT_NAMES + _REMOVE_NAMES)
        for name in _REMOVE_NAMES:
            assert name in report["removed"], f"{name} should be removed"

    def test_no_overlap_between_kept_and_removed(self) -> None:
        report = _patched_strip(_KEPT_NAMES + _REMOVE_NAMES)
        assert set(report["kept"]).isdisjoint(report["removed"])

    def test_every_kept_name_is_in_the_allowlist(self) -> None:
        report = _patched_strip(_KEPT_NAMES + _REMOVE_NAMES)
        for name in report["kept"]:
            assert name in KEEP_PRIVILEGES

    def test_report_lists_are_sorted(self) -> None:
        # Feed in a deliberately unsorted order.
        report = _patched_strip(list(reversed(_REMOVE_NAMES)) + _KEPT_NAMES)
        assert report["removed"] == sorted(report["removed"])
        assert report["kept"] == sorted(report["kept"])

    def test_allowlist_is_exactly_the_four_documented_privileges(self) -> None:
        # Lock the keep-set so adding/removing one is a conscious, reviewed change.
        assert KEEP_PRIVILEGES == frozenset(
            {
                "SeChangeNotifyPrivilege",
                "SeImpersonatePrivilege",
                "SeRestorePrivilege",
                "SeTakeOwnershipPrivilege",
            }
        )

    def test_only_allowlisted_present_means_nothing_removed(self) -> None:
        report = _patched_strip(list(_KEPT_NAMES))
        assert report["removed"] == []
        assert sorted(report["kept"]) == sorted(_KEPT_NAMES)


class TestReportShape:
    """The report contract every caller relies on."""

    def test_report_has_three_list_keys(self) -> None:
        report = _patched_strip(_KEPT_NAMES + _REMOVE_NAMES)
        assert set(report.keys()) == {"removed", "kept", "errors"}
        assert all(isinstance(report[k], list) for k in report)

    def test_declined_removal_lands_in_errors_not_removed(self) -> None:
        # The API reports it could not remove the privilege (held-but-not-removed).
        report = _patched_strip(_REMOVE_NAMES, remove_returns=False)
        assert report["removed"] == []
        for name in _REMOVE_NAMES:
            assert name in report["errors"]


class TestFailSafe:
    """Fail-safe, never fail-boot: every failure path returns a report, no raise."""

    def test_non_windows_is_noop_report(self) -> None:
        with patch.object(privilege_hardening.sys, "platform", "linux"):
            report = strip_unused_privileges()
        assert report == {"removed": [], "kept": [], "errors": []}

    def test_api_load_failure_returns_empty_report(self) -> None:
        with patch.object(privilege_hardening.sys, "platform", "win32"), patch.object(
            privilege_hardening, "_api", return_value=None
        ):
            report = strip_unused_privileges()
        assert report == {"removed": [], "kept": [], "errors": []}

    def test_open_process_token_failure_is_recorded_not_raised(self) -> None:
        with patch.object(privilege_hardening.sys, "platform", "win32"), patch.object(
            privilege_hardening,
            "_api",
            return_value=(_FakeAdvapi32WithOpen(open_succeeds=False), _FakeKernel32()),
        ), patch.object(
            privilege_hardening.ctypes, "get_last_error", return_value=5
        ):
            report = strip_unused_privileges()
        # Did not raise; recorded the failure; removed/kept stay empty.
        assert report["removed"] == []
        assert report["kept"] == []
        assert any("OpenProcessToken" in e for e in report["errors"])

    def test_enumeration_raising_does_not_propagate(self) -> None:
        with patch.object(privilege_hardening.sys, "platform", "win32"), patch.object(
            privilege_hardening,
            "_api",
            return_value=(_FakeAdvapi32WithOpen(open_succeeds=True), _FakeKernel32()),
        ), patch.object(
            privilege_hardening,
            "_enumerate_privileges",
            side_effect=RuntimeError("simulated CNG/advapi32 explosion"),
        ), patch.object(
            privilege_hardening.ctypes, "get_last_error", return_value=0
        ):
            # Must NOT raise — the outer guard catches it.
            report = strip_unused_privileges()
        assert report["removed"] == []
        assert any("exception" in e for e in report["errors"])

    def test_empty_enumeration_returns_empty_report(self) -> None:
        report = _patched_strip([])
        assert report == {"removed": [], "kept": [], "errors": []}

    def test_strip_never_raises_under_any_patched_failure(self) -> None:
        # Belt-and-suspenders: the public entry point is total — it returns a
        # dict in every branch exercised above.
        try:
            _patched_strip(_KEPT_NAMES + _REMOVE_NAMES)
            _patched_strip([], remove_returns=False)
        except Exception as exc:  # noqa: BLE001
            pytest.fail(f"strip_unused_privileges raised: {exc!r}")
