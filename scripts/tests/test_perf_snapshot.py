"""
Tests for scripts/perf_snapshot.py — the BlarAI performance-tracking tool.

Covers the pure, deterministic helpers:
  - parse_latest_boot: boot duration from launcher.log text
  - extract_benchmark_metrics: TTFT / throughput from a benchmark payload
  - find_latest_benchmark: newest benchmark_*.json by mtime
  - build_record / append_jsonl: dataset record assembly + JSONL append

The live measurement (measure_memory, git_sha) is not unit-tested — it
depends on the running system.
"""

from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path

import pytest

# Import the script directly by file path (scripts/ is not a package).
_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "perf_snapshot.py"
_spec = importlib.util.spec_from_file_location("perf_snapshot", _SCRIPT)
assert _spec and _spec.loader
perf_snapshot = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(perf_snapshot)


# ---------------------------------------------------------------------------
# parse_latest_boot
# ---------------------------------------------------------------------------

_ONE_BOOT = """\
2026-05-22 14:18:47,605 [blarai.launcher] INFO: Startup: Checking Administrator privileges
2026-05-22 14:18:49,340 [blarai.launcher] INFO: Startup: VM running
2026-05-22 14:19:35,987 [services.ui_shell.src.app] INFO: Boot-Phase-3: OPERATIONAL — input enabled
"""

_TWO_BOOTS = """\
2026-05-22 14:13:33,055 [blarai.launcher] INFO: Startup: Checking Administrator privileges
2026-05-22 14:15:57,558 [services.ui_shell.src.app] INFO: Boot-Phase-3: OPERATIONAL — input enabled
2026-05-22 14:18:47,605 [blarai.launcher] INFO: Startup: Checking Administrator privileges
2026-05-22 14:19:35,987 [services.ui_shell.src.app] INFO: Boot-Phase-3: OPERATIONAL — input enabled
"""


class TestParseLatestBoot:
    def test_single_boot_duration(self) -> None:
        boot = perf_snapshot.parse_latest_boot(_ONE_BOOT)
        assert boot is not None
        assert boot["seconds"] == 48.4  # 14:19:35.987 - 14:18:47.605
        assert boot["started"] == "2026-05-22 14:18:47.605000"

    def test_returns_the_most_recent_boot(self) -> None:
        boot = perf_snapshot.parse_latest_boot(_TWO_BOOTS)
        assert boot is not None
        assert boot["seconds"] == 48.4  # the 2nd boot, not the 144.5s first

    def test_incomplete_boot_returns_none(self) -> None:
        """A boot that started but never reached OPERATIONAL -> None."""
        text = "2026-05-22 14:18:47,605 [blarai.launcher] INFO: Startup: Checking Administrator privileges\n"
        assert perf_snapshot.parse_latest_boot(text) is None

    def test_skips_in_progress_last_boot(self) -> None:
        """If the most recent boot is still in progress (no OPERATIONAL
        line yet), fall back to the previous complete boot rather than
        reporting nothing. This was a real bug found running the tool."""
        text = _TWO_BOOTS + (
            "2026-05-22 14:42:51,483 [blarai.launcher] INFO: "
            "Startup: Checking Administrator privileges\n"
        )
        boot = perf_snapshot.parse_latest_boot(text)
        assert boot is not None
        assert boot["seconds"] == 48.4  # the last *complete* boot

    def test_empty_log_returns_none(self) -> None:
        assert perf_snapshot.parse_latest_boot("") is None


# ---------------------------------------------------------------------------
# extract_benchmark_metrics
# ---------------------------------------------------------------------------


class TestExtractBenchmarkMetrics:
    def test_prefers_spec_on(self) -> None:
        data = {
            "results": {
                "spec_off": {"aggregate": {"median_ttft_ms": 999.0, "median_tps": 5.0}},
                "spec_on": {
                    "load_ms": 12235.2,
                    "aggregate": {"median_ttft_ms": 817.8, "median_tps": 12.24},
                },
            }
        }
        m = perf_snapshot.extract_benchmark_metrics(data)
        assert m["config"] == "spec_on"
        assert m["median_ttft_ms"] == 817.8
        assert m["median_tps"] == 12.24
        assert m["load_ms"] == 12235.2

    def test_falls_back_to_only_config(self) -> None:
        data = {"results": {"spec_off": {"aggregate": {"median_ttft_ms": 900.0, "median_tps": 6.0}}}}
        m = perf_snapshot.extract_benchmark_metrics(data)
        assert m["config"] == "spec_off"
        assert m["median_ttft_ms"] == 900.0

    def test_empty_results_returns_empty(self) -> None:
        assert perf_snapshot.extract_benchmark_metrics({"results": {}}) == {}
        assert perf_snapshot.extract_benchmark_metrics({}) == {}


# ---------------------------------------------------------------------------
# find_latest_benchmark
# ---------------------------------------------------------------------------


class TestFindLatestBenchmark:
    def test_returns_newest_by_filename_not_mtime(self, tmp_path: Path) -> None:
        """Sorts by the filename timestamp, not mtime — mtime is unreliable
        (a file copy / git checkout can give an old run the newest mtime)."""
        old = tmp_path / "benchmark_2026-05-21_00-00-00.json"
        new = tmp_path / "benchmark_2026-05-22_06-53-50.json"
        old.write_text("{}", encoding="utf-8")
        new.write_text("{}", encoding="utf-8")
        # Give the OLD run the NEWER mtime — name-sort must still win.
        os.utime(old, (9_000_000, 9_000_000))
        os.utime(new, (1_000_000, 1_000_000))
        assert perf_snapshot.find_latest_benchmark(tmp_path) == new

    def test_none_when_no_benchmarks(self, tmp_path: Path) -> None:
        assert perf_snapshot.find_latest_benchmark(tmp_path) is None


# ---------------------------------------------------------------------------
# build_record / append_jsonl
# ---------------------------------------------------------------------------


class TestBuildRecord:
    def test_record_has_all_sections(self) -> None:
        rec = perf_snapshot.build_record(
            git_sha="abc1234",
            openvino_version="2026.1.0",
            memory={"system_used_gb": 27.7, "blarai_running": True},
            power={"line_status": "Online", "battery_percent": 95},
            boot={"seconds": 48.4, "started": "2026-05-22 14:18:47.605000"},
            inference={"median_ttft_ms": 817.8},
            note="after driver update",
        )
        assert rec["git_sha"] == "abc1234"
        assert rec["openvino_version"] == "2026.1.0"
        assert rec["boot"]["seconds"] == 48.4
        assert rec["memory"]["system_used_gb"] == 27.7
        assert rec["power"]["line_status"] == "Online"
        assert rec["inference"]["median_ttft_ms"] == 817.8
        assert rec["note"] == "after driver update"
        assert "ts" in rec

    def test_empty_sections_become_none(self) -> None:
        rec = perf_snapshot.build_record(
            git_sha="x", openvino_version="x", memory={}, power={}, boot=None,
            inference={}, note="",
        )
        assert rec["inference"] is None
        assert rec["power"] is None


class TestAppendJsonl:
    def test_appends_one_line_per_record(self, tmp_path: Path) -> None:
        path = tmp_path / "sub" / "perf_history.jsonl"
        perf_snapshot.append_jsonl({"a": 1}, path)
        perf_snapshot.append_jsonl({"a": 2}, path)
        lines = path.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 2
        assert json.loads(lines[0]) == {"a": 1}
        assert json.loads(lines[1]) == {"a": 2}

    def test_creates_parent_directory(self, tmp_path: Path) -> None:
        path = tmp_path / "deep" / "nested" / "perf_history.jsonl"
        perf_snapshot.append_jsonl({"ok": True}, path)
        assert path.is_file()
