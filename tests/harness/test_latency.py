"""Layer A unit tests for the latency utilities + community-grade perf recorder.

NO models. Covers the recorder path (``write_perf_record`` / ``build_environment``)
that the hardware CLI exercises but the default suite would otherwise never touch
— so a bug in environment capture or filename sanitisation cannot ship silently
(the CLAUDE.md testing-data mandate runs through this code).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.harness import latency


def test_percentile_edges_and_interpolation() -> None:
    assert latency.percentile([], 50) == 0.0
    assert latency.percentile([5.0], 95) == 5.0
    # p50 of 1..4 (0-indexed interpolation at k=1.5) = 2.5
    assert latency.percentile([1.0, 2.0, 3.0, 4.0], 50) == 2.5


def test_summarize_shape() -> None:
    assert latency.summarize([])["count"] == 0
    s = latency.summarize([1.0, 2.0, 3.0, 4.0])
    assert s["count"] == 4
    assert s["min_ms"] == 1.0
    assert s["max_ms"] == 4.0
    assert s["mean_ms"] == 2.5


def test_stopwatch_measures_nonnegative() -> None:
    with latency.Stopwatch() as sw:
        sum(range(10_000))
    assert sw.ms >= 0.0


def test_build_environment_names_what_it_cannot_measure() -> None:
    env = latency.build_environment({"extra_key": "v"})
    assert env["cpu"].startswith("Intel")
    assert env["extra_key"] == "v"
    assert env["not_measured"], "must enumerate uncovered dimensions, not imply full coverage"


def test_write_perf_record_writes_sanitised_json(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(latency, "PERF_DIR", tmp_path)
    path = latency.write_perf_record(
        "unit",
        {"x": 1, "nested": {"y": 2}},
        when_iso="2026-06-04T00:00:00.123+00:00",
        model="M-test",
        precision="INT4",
        methodology="unit test",
        notes="a note",
    )
    assert path.parent == tmp_path
    # Colons / plus / dot from the ISO timestamp must be filename-safe.
    assert ":" not in path.name and "+" not in path.name

    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["name"] == "unit"
    assert data["model"] == "M-test"
    assert data["precision"] == "INT4"
    assert data["measurements"] == {"x": 1, "nested": {"y": 2}}
    assert data["notes"] == "a note"
    assert "not_measured" in data["environment"]
    assert data["source"].startswith("tests/harness")
