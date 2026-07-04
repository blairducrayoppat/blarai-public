"""
Tests for the step-0 VHDX backup script's refusal predicate (#655 Stage C)
===========================================================================
``scripts/backup_orchestrator_vhdx.ps1`` refuses to run unless the VM is
verifiably Off.  These tests exercise the REAL shipped predicate
(``Get-BackupRefusalReason``) by dot-sourcing the script in ``-AsLibrary``
mode inside one throwaway PowerShell process — so the unit under test is the
exact code the controlled session will run, with zero Python-side mirror to
drift.  No Hyper-V cmdlet executes: -AsLibrary returns before the main body,
and the predicate itself is a pure function.
"""

from __future__ import annotations

import json
import subprocess
import sys
from functools import lru_cache
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(
    sys.platform != "win32",
    reason="PowerShell predicate test (Windows host only)",
)

_SCRIPT = (
    Path(__file__).resolve().parents[2] / "scripts" / "backup_orchestrator_vhdx.ps1"
)


@lru_cache(maxsize=1)
def _predicate_results() -> dict[str, str]:
    """Dot-source the script as a library and evaluate every case in ONE
    PowerShell spawn (kept fast for the standing gate)."""
    command = (
        f". '{_SCRIPT}' -AsLibrary; "
        "$r = [ordered]@{}; "
        "$r['off'] = Get-BackupRefusalReason -VmState 'Off'; "
        "$r['off_padded'] = Get-BackupRefusalReason -VmState ' Off '; "
        "$r['running'] = Get-BackupRefusalReason -VmState 'Running'; "
        "$r['saved'] = Get-BackupRefusalReason -VmState 'Saved'; "
        "$r['paused'] = Get-BackupRefusalReason -VmState 'Paused'; "
        "$r['starting'] = Get-BackupRefusalReason -VmState 'Starting'; "
        "$r['empty'] = Get-BackupRefusalReason -VmState ''; "
        "$r['whitespace'] = Get-BackupRefusalReason -VmState '   '; "
        "$r['queryfail'] = "
        "Get-BackupRefusalReason -VmState 'Off' -StateQueryFailed $true; "
        "$r | ConvertTo-Json -Compress"
    )
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, (
        f"predicate harness failed: stdout={result.stdout!r} "
        f"stderr={result.stderr!r}"
    )
    parsed = json.loads(result.stdout)
    # ConvertTo-Json renders empty strings as "" and keeps key order.
    return {key: ("" if value is None else str(value)) for key, value in parsed.items()}


class TestBackupRefusalPredicate:
    def test_script_exists(self) -> None:
        assert _SCRIPT.is_file()

    def test_off_is_permitted(self) -> None:
        assert _predicate_results()["off"] == ""

    def test_off_with_padding_is_permitted(self) -> None:
        """State string trimming: ' Off ' is the same verifiable Off."""
        assert _predicate_results()["off_padded"] == ""

    def test_running_refuses(self) -> None:
        reason = _predicate_results()["running"]
        assert reason != ""
        assert "Running" in reason

    def test_saved_refuses(self) -> None:
        """Saved is NOT a safe copy point (dirty memory state references the
        disk) — only exactly Off permits the backup."""
        assert _predicate_results()["saved"] != ""

    def test_paused_refuses(self) -> None:
        assert _predicate_results()["paused"] != ""

    def test_starting_refuses(self) -> None:
        assert _predicate_results()["starting"] != ""

    def test_empty_state_refuses_fail_closed(self) -> None:
        assert _predicate_results()["empty"] != ""

    def test_whitespace_state_refuses_fail_closed(self) -> None:
        assert _predicate_results()["whitespace"] != ""

    def test_failed_state_query_refuses_fail_closed(self) -> None:
        """Even an 'Off' reading is refused when the query itself failed —
        never copy on uncertainty."""
        reason = _predicate_results()["queryfail"]
        assert reason != ""
        assert "fail-closed" in reason
