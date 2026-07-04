"""Tests for tools.perf_contrib.cli — deterministic, no I/O outside tmp_path.

All tests drive the ``main()`` function directly (no subprocess) so there is
no coverage gap between the test and the real code path.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from tools.perf_contrib.cli import main
from tools.perf_contrib.tests.fixtures import minimal_valid, invalid_missing_not_measured


def _write_harness(directory: Path, name: str, record: dict[str, Any]) -> Path:
    path = directory / f"harness_{name}.json"
    path.write_text(json.dumps(record, indent=2), encoding="utf-8")
    return path


class TestValidateCli:
    def test_validate_single_valid_file_exits_0(self, tmp_path: Path) -> None:
        path = _write_harness(tmp_path, "chat", minimal_valid())
        rc = main(["validate", str(path)])
        assert rc == 0

    def test_validate_single_invalid_file_exits_1(self, tmp_path: Path) -> None:
        path = _write_harness(tmp_path, "bad", invalid_missing_not_measured())
        rc = main(["validate", str(path)])
        assert rc == 1

    def test_validate_mix_exits_1(self, tmp_path: Path) -> None:
        valid_path = _write_harness(tmp_path, "good", minimal_valid())
        bad_path = _write_harness(tmp_path, "bad", invalid_missing_not_measured())
        rc = main(["validate", str(valid_path), str(bad_path)])
        assert rc == 1

    def test_validate_all_valid_exits_0(self, tmp_path: Path) -> None:
        for i in range(3):
            rec = minimal_valid()
            rec["name"] = f"scenario_{i}"
            rec["timestamp"] = f"2026-06-0{i + 1}T12:00:00Z"
            _write_harness(tmp_path, f"s{i}", rec)
        paths = [str(p) for p in sorted(tmp_path.glob("harness_*.json"))]
        rc = main(["validate"] + paths)
        assert rc == 0

    def test_validate_nonexistent_file_exits_1(self, tmp_path: Path) -> None:
        rc = main(["validate", str(tmp_path / "does_not_exist.json")])
        assert rc == 1

    def test_validate_malformed_json_exits_1(self, tmp_path: Path) -> None:
        bad = tmp_path / "harness_corrupt.json"
        bad.write_text("{ not json", encoding="utf-8")
        rc = main(["validate", str(bad)])
        assert rc == 1


class TestAggregateCli:
    def test_aggregate_exits_0_with_valid_records(self, tmp_path: Path) -> None:
        _write_harness(tmp_path, "chat", minimal_valid())
        rc = main(["aggregate", "--perf-dir", str(tmp_path), "--out-dir", str(tmp_path)])
        assert rc == 0

    def test_aggregate_exits_1_with_no_valid_records(self, tmp_path: Path) -> None:
        _write_harness(tmp_path, "bad", invalid_missing_not_measured())
        rc = main(["aggregate", "--perf-dir", str(tmp_path), "--out-dir", str(tmp_path)])
        assert rc == 1

    def test_aggregate_produces_jsonl(self, tmp_path: Path) -> None:
        _write_harness(tmp_path, "chat", minimal_valid())
        main(["aggregate", "--perf-dir", str(tmp_path), "--out-dir", str(tmp_path)])
        assert (tmp_path / "blarai_perf_dataset.jsonl").exists()

    def test_aggregate_produces_csv(self, tmp_path: Path) -> None:
        _write_harness(tmp_path, "chat", minimal_valid())
        main(["aggregate", "--perf-dir", str(tmp_path), "--out-dir", str(tmp_path)])
        assert (tmp_path / "blarai_perf_dataset.csv").exists()

    def test_aggregate_empty_dir_exits_1(self, tmp_path: Path) -> None:
        rc = main(["aggregate", "--perf-dir", str(tmp_path), "--out-dir", str(tmp_path)])
        assert rc == 1
