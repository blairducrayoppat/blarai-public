"""Tests for tools.perf_contrib.aggregator — deterministic, no GPU, no network.

Uses ``tmp_path`` (pytest built-in) as a scratch directory; does not touch
``docs/performance/`` at all during test runs.
"""
from __future__ import annotations

import csv
import json
import re
from pathlib import Path
from typing import Any

import pytest

from tools.perf_contrib.aggregator import (
    aggregate,
    discover_records,
    _scrub_record,
    _flatten_for_csv,
)
from tools.perf_contrib.tests.fixtures import (
    minimal_valid,
    harness_chat_record,
    invalid_missing_not_measured,
    invalid_missing_measurements,
    invalid_methodology_too_short,
)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _write_harness(directory: Path, name: str, record: dict[str, Any]) -> Path:
    """Write a harness_*.json file to *directory* and return the path."""
    path = directory / f"harness_{name}.json"
    path.write_text(json.dumps(record, indent=2), encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# discover_records
# ---------------------------------------------------------------------------

class TestDiscoverRecords:
    def test_finds_harness_files(self, tmp_path: Path) -> None:
        _write_harness(tmp_path, "chat_2026-06-01", minimal_valid())
        _write_harness(tmp_path, "router_2026-06-01", minimal_valid())
        found = discover_records(tmp_path)
        assert len(found) == 2

    def test_ignores_non_harness_files(self, tmp_path: Path) -> None:
        _write_harness(tmp_path, "chat", minimal_valid())
        # These must NOT be discovered.
        (tmp_path / "benchmark_2026.json").write_text("{}", encoding="utf-8")
        (tmp_path / "perf_history.jsonl").write_text("", encoding="utf-8")
        found = discover_records(tmp_path)
        assert len(found) == 1

    def test_returns_sorted_by_name(self, tmp_path: Path) -> None:
        _write_harness(tmp_path, "z_last", minimal_valid())
        _write_harness(tmp_path, "a_first", minimal_valid())
        found = discover_records(tmp_path)
        assert found[0].name < found[1].name

    def test_empty_directory_returns_empty_list(self, tmp_path: Path) -> None:
        assert discover_records(tmp_path) == []


# ---------------------------------------------------------------------------
# privacy scrubber
# ---------------------------------------------------------------------------

class TestScrubRecord:
    def test_strips_reply_preview(self) -> None:
        rec = harness_chat_record()
        scrubbed = _scrub_record(rec)
        assert "reply_preview" not in scrubbed
        assert "reply_preview" not in scrubbed.get("measurements", {})

    def test_replaces_windows_absolute_path(self) -> None:
        rec = minimal_valid()
        rec["measurements"]["model_dir"] = r"C:\Users\mrbla\BlarAI\models\qwen3-14b"
        scrubbed = _scrub_record(rec)
        assert r"C:\Users" not in json.dumps(scrubbed)
        assert "<local-path>" in json.dumps(scrubbed)

    def test_replaces_path_in_nested_environment(self) -> None:
        rec = minimal_valid()
        rec["environment"]["model_dir"] = "C:/Users/mrbla/BlarAI/models"
        scrubbed = _scrub_record(rec)
        env_str = json.dumps(scrubbed["environment"])
        assert "C:/Users" not in env_str
        assert "<local-path>" in env_str

    def test_replaces_path_in_measurements(self) -> None:
        rec = minimal_valid()
        rec["measurements"]["draft_model_dir"] = r"C:\Users\mrbla\BlarAI\models\qwen3-0.6b"
        scrubbed = _scrub_record(rec)
        meas_str = json.dumps(scrubbed["measurements"])
        assert r"C:\Users" not in meas_str
        assert "<local-path>" in meas_str

    def test_non_path_strings_unaffected(self) -> None:
        rec = minimal_valid()
        scrubbed = _scrub_record(rec)
        assert scrubbed["name"] == rec["name"]
        assert scrubbed["model"] == rec["model"]

    def test_does_not_mutate_original(self) -> None:
        rec = harness_chat_record()
        original_has_preview = "reply_preview" in rec["measurements"]
        _scrub_record(rec)
        assert ("reply_preview" in rec["measurements"]) == original_has_preview


# ---------------------------------------------------------------------------
# CSV flattening
# ---------------------------------------------------------------------------

class TestFlattenForCsv:
    def test_env_keys_prefixed(self) -> None:
        rec = minimal_valid()
        flat = _flatten_for_csv(rec)
        assert "env_cpu" in flat
        assert "environment" not in flat

    def test_measurements_keys_prefixed(self) -> None:
        rec = minimal_valid()
        flat = _flatten_for_csv(rec)
        assert "meas_load_ms" in flat
        assert "measurements" not in flat

    def test_nested_dict_json_serialised(self) -> None:
        rec = minimal_valid()
        flat = _flatten_for_csv(rec)
        # env_not_measured is a list — should be JSON string in CSV
        val = flat.get("env_not_measured", "")
        assert isinstance(val, str)
        # Must be valid JSON
        parsed = json.loads(val)
        assert isinstance(parsed, list)

    def test_scalar_values_preserved(self) -> None:
        rec = minimal_valid()
        flat = _flatten_for_csv(rec)
        assert flat["name"] == rec["name"]
        assert flat["model"] == rec["model"]
        assert flat["precision"] == rec["precision"]


# ---------------------------------------------------------------------------
# aggregate()
# ---------------------------------------------------------------------------

class TestAggregate:
    def test_single_valid_record_included(self, tmp_path: Path) -> None:
        _write_harness(tmp_path, "chat", minimal_valid())
        report = aggregate(perf_dir=tmp_path, out_dir=tmp_path)
        assert report.total_found == 1
        assert report.valid_count == 1
        assert report.invalid_count == 0

    def test_invalid_record_skipped(self, tmp_path: Path) -> None:
        _write_harness(tmp_path, "valid", minimal_valid())
        _write_harness(tmp_path, "bad_no_measured", invalid_missing_not_measured())
        report = aggregate(perf_dir=tmp_path, out_dir=tmp_path)
        assert report.valid_count == 1
        assert report.invalid_count == 1
        assert len(report.skipped_paths) == 1

    def test_all_invalid_skipped(self, tmp_path: Path) -> None:
        _write_harness(tmp_path, "bad1", invalid_missing_not_measured())
        _write_harness(tmp_path, "bad2", invalid_missing_measurements())
        report = aggregate(perf_dir=tmp_path, out_dir=tmp_path)
        assert report.valid_count == 0
        assert report.invalid_count == 2

    def test_empty_directory(self, tmp_path: Path) -> None:
        report = aggregate(perf_dir=tmp_path, out_dir=tmp_path)
        assert report.total_found == 0
        assert report.valid_count == 0

    def test_jsonl_written(self, tmp_path: Path) -> None:
        _write_harness(tmp_path, "chat", minimal_valid())
        report = aggregate(perf_dir=tmp_path, out_dir=tmp_path)
        assert report.output_jsonl is not None
        assert report.output_jsonl.exists()

    def test_csv_written(self, tmp_path: Path) -> None:
        _write_harness(tmp_path, "chat", minimal_valid())
        report = aggregate(perf_dir=tmp_path, out_dir=tmp_path)
        assert report.output_csv is not None
        assert report.output_csv.exists()

    def test_jsonl_is_valid_ndjson(self, tmp_path: Path) -> None:
        _write_harness(tmp_path, "chat", minimal_valid())
        _write_harness(tmp_path, "router", harness_chat_record())
        report = aggregate(perf_dir=tmp_path, out_dir=tmp_path)
        lines = report.output_jsonl.read_text(encoding="utf-8").splitlines()
        assert len(lines) == 2
        for line in lines:
            obj = json.loads(line)
            assert isinstance(obj, dict)

    def test_csv_has_header_and_rows(self, tmp_path: Path) -> None:
        _write_harness(tmp_path, "chat", minimal_valid())
        _write_harness(tmp_path, "router", harness_chat_record())
        report = aggregate(perf_dir=tmp_path, out_dir=tmp_path)
        with report.output_csv.open(encoding="utf-8") as fh:
            reader = list(csv.DictReader(fh))
        assert len(reader) == 2
        assert "name" in reader[0]

    def test_source_file_stamped_in_jsonl(self, tmp_path: Path) -> None:
        _write_harness(tmp_path, "chat_2026", minimal_valid())
        report = aggregate(perf_dir=tmp_path, out_dir=tmp_path)
        line = report.output_jsonl.read_text(encoding="utf-8").strip()
        obj = json.loads(line)
        assert obj.get("_source_file") == "harness_chat_2026.json"

    def test_reply_preview_scrubbed_from_jsonl(self, tmp_path: Path) -> None:
        """reply_preview must not appear in the published dataset."""
        _write_harness(tmp_path, "chat", harness_chat_record())
        report = aggregate(perf_dir=tmp_path, out_dir=tmp_path)
        content = report.output_jsonl.read_text(encoding="utf-8")
        assert "reply_preview" not in content

    def test_windows_paths_scrubbed_from_jsonl(self, tmp_path: Path) -> None:
        rec = minimal_valid()
        rec["measurements"]["draft_dir"] = r"C:\Users\mrbla\BlarAI\models"
        _write_harness(tmp_path, "chat", rec)
        report = aggregate(perf_dir=tmp_path, out_dir=tmp_path)
        content = report.output_jsonl.read_text(encoding="utf-8")
        assert r"C:\Users" not in content
        assert "<local-path>" in content

    def test_non_harness_json_ignored(self, tmp_path: Path) -> None:
        """benchmark_*.json and other non-harness files must NOT be aggregated."""
        _write_harness(tmp_path, "chat", minimal_valid())
        (tmp_path / "benchmark_2026-05-21.json").write_text(
            json.dumps({"benchmark": "something"}), encoding="utf-8"
        )
        report = aggregate(perf_dir=tmp_path, out_dir=tmp_path)
        assert report.total_found == 1  # only the harness_chat file

    def test_malformed_json_skipped_with_report(self, tmp_path: Path) -> None:
        bad_path = tmp_path / "harness_corrupt.json"
        bad_path.write_text("{ this is not json", encoding="utf-8")
        report = aggregate(perf_dir=tmp_path, out_dir=tmp_path)
        assert report.invalid_count == 1
        assert len(report.skipped_paths) == 1
        skipped_file, errs = report.skipped_paths[0]
        assert "parse" in errs[0].lower() or "json" in errs[0].lower()

    def test_output_to_separate_out_dir(self, tmp_path: Path) -> None:
        perf_dir = tmp_path / "perf"
        out_dir = tmp_path / "output"
        perf_dir.mkdir()
        _write_harness(perf_dir, "chat", minimal_valid())
        report = aggregate(perf_dir=perf_dir, out_dir=out_dir)
        assert report.output_jsonl.parent == out_dir
        assert report.output_csv.parent == out_dir

    def test_multiple_valid_records_all_included(self, tmp_path: Path) -> None:
        for i in range(5):
            rec = minimal_valid()
            rec["name"] = f"scenario_{i}"
            rec["timestamp"] = f"2026-06-0{i + 1}T12:00:00Z"
            _write_harness(tmp_path, f"scenario_{i}", rec)
        report = aggregate(perf_dir=tmp_path, out_dir=tmp_path)
        assert report.valid_count == 5
        assert report.total_found == 5

    def test_skipped_paths_names_invalid_files(self, tmp_path: Path) -> None:
        _write_harness(tmp_path, "bad", invalid_methodology_too_short())
        report = aggregate(perf_dir=tmp_path, out_dir=tmp_path)
        assert report.skipped_paths[0][0].name == "harness_bad.json"

    def test_empty_jsonl_when_no_valid_records(self, tmp_path: Path) -> None:
        _write_harness(tmp_path, "bad", invalid_missing_not_measured())
        report = aggregate(perf_dir=tmp_path, out_dir=tmp_path)
        lines = [
            l for l in report.output_jsonl.read_text(encoding="utf-8").splitlines()
            if l.strip()
        ]
        assert lines == []
