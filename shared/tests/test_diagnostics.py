"""Tests for the lightweight memory diagnostics (#561).

Verify the snapshot shape, that logging never raises, and the psutil-absent
fail-soft path — without depending on any particular memory level.
"""

from __future__ import annotations

import logging

import pytest

from shared import diagnostics


def test_memory_snapshot_has_expected_keys() -> None:
    snap = diagnostics.memory_snapshot()
    if snap:  # psutil present (it is in this env); fail-soft returns {} if absent
        assert set(snap) == {
            "sys_total_mb",
            "sys_available_mb",
            "sys_used_pct",
            "proc_rss_mb",
        }
        assert snap["sys_total_mb"] > 0
        assert 0.0 <= snap["sys_used_pct"] <= 100.0


def test_log_memory_logs_and_returns_snapshot(caplog: pytest.LogCaptureFixture) -> None:
    log = logging.getLogger("test.diag")
    with caplog.at_level(logging.INFO, logger="test.diag"):
        snap = diagnostics.log_memory(log, "unit.test", img="100x100")
    assert isinstance(snap, dict)
    assert "MEM[unit.test]" in caplog.text
    assert "img=100x100" in caplog.text  # extra kwargs are appended verbatim


def test_log_memory_fail_soft_when_psutil_absent(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr(diagnostics, "_PSUTIL_AVAILABLE", False)
    log = logging.getLogger("test.diag2")
    with caplog.at_level(logging.INFO, logger="test.diag2"):
        snap = diagnostics.log_memory(log, "noinfo")  # must not raise
    assert snap == {}
    assert "psutil unavailable" in caplog.text
