"""Aggregate and curate valid perf records into a publishable dataset.

Reads all ``harness_*.json`` files from ``docs/performance/`` (the community-grade
records written by ``tests/harness/latency.py:write_perf_record``), validates each
one, and emits two outputs:

1. ``<out_dir>/blarai_perf_dataset.jsonl``  — newline-delimited JSON, one record per
   line, scrubbed of local paths that would leak machine layout.
2. ``<out_dir>/blarai_perf_dataset.csv``    — flat CSV for easy spreadsheet/pandas
   consumption, one row per record (nested dicts are flattened one level).

Both outputs carry ONLY records that pass schema validation. Invalid records are
reported to stderr and skipped — never silently dropped, never silently included.

Privacy scrub
-------------
The records written by the harness can contain ``model_dir`` or ``reply_preview``
fields that may include local path segments (``C:\\Users\\mrbla\\...``) or
free-text user input. The scrubber replaces Windows absolute paths with ``<local-path>``
and strips the ``reply_preview`` key entirely (content is not our data to publish).

No network calls are made. The caller submits the output manually.
"""

from __future__ import annotations

import csv
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from tools.perf_contrib.schema import validate

_REPO_ROOT = Path(__file__).resolve().parents[2]
PERF_DIR = _REPO_ROOT / "docs" / "performance"

# Regex that catches Windows absolute paths: e.g. C:\Users\foo\... or C:/Users/foo/...
_WIN_PATH_RE = re.compile(r"[A-Za-z]:[/\\][^\s\"',;>]+")

# Keys whose values may contain free-text user content — strip before publishing.
_STRIP_KEYS = frozenset({"reply_preview", "reply_text", "user_content"})


@dataclass
class AggregationReport:
    """Summary of one aggregation run."""

    total_found: int = 0
    valid_count: int = 0
    invalid_count: int = 0
    skipped_paths: list[tuple[Path, list[str]]] = field(default_factory=list)
    output_jsonl: Path | None = None
    output_csv: Path | None = None

    def print_summary(self, *, file: Any = None) -> None:
        out = file or sys.stdout
        print(f"Records found  : {self.total_found}", file=out)
        print(f"Valid / included: {self.valid_count}", file=out)
        print(f"Invalid / skipped: {self.invalid_count}", file=out)
        if self.skipped_paths:
            print("Skipped records:", file=out)
            for path, errs in self.skipped_paths:
                print(f"  {path.name}", file=out)
                for e in errs:
                    print(f"    - {e}", file=out)
        if self.output_jsonl:
            print(f"JSONL output   : {self.output_jsonl}", file=out)
        if self.output_csv:
            print(f"CSV output     : {self.output_csv}", file=out)


def _scrub_value(value: Any) -> Any:
    """Recursively scrub local paths from a value."""
    if isinstance(value, str):
        return _WIN_PATH_RE.sub("<local-path>", value)
    if isinstance(value, dict):
        return {k: _scrub_value(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_scrub_value(item) for item in value]
    return value


def _scrub_record(record: dict[str, Any]) -> dict[str, Any]:
    """Return a privacy-scrubbed copy of *record*.

    - Replaces Windows absolute paths in all string values.
    - Removes keys listed in ``_STRIP_KEYS`` from the top-level and from
      ``measurements`` (where ``reply_preview`` typically lives).
    """
    scrubbed: dict[str, Any] = {}
    for key, value in record.items():
        if key in _STRIP_KEYS:
            continue
        scrubbed[key] = _scrub_value(value)

    # Also strip from nested measurements dict.
    if isinstance(scrubbed.get("measurements"), dict):
        scrubbed["measurements"] = {
            k: v
            for k, v in scrubbed["measurements"].items()
            if k not in _STRIP_KEYS
        }

    return scrubbed


def _flatten_for_csv(record: dict[str, Any]) -> dict[str, Any]:
    """Flatten one level of nesting for CSV output.

    ``environment`` and ``measurements`` sub-dicts are expanded with
    ``env_*`` and ``meas_*`` prefixes.  Nested lists are JSON-serialised.
    """
    flat: dict[str, Any] = {}
    for key, value in record.items():
        if key == "environment" and isinstance(value, dict):
            for sub_key, sub_val in value.items():
                csv_val = json.dumps(sub_val) if isinstance(sub_val, (dict, list)) else sub_val
                flat[f"env_{sub_key}"] = csv_val
        elif key == "measurements" and isinstance(value, dict):
            for sub_key, sub_val in value.items():
                csv_val = json.dumps(sub_val) if isinstance(sub_val, (dict, list)) else sub_val
                flat[f"meas_{sub_key}"] = csv_val
        else:
            flat[key] = json.dumps(value) if isinstance(value, (dict, list)) else value
    return flat


def discover_records(perf_dir: Path | None = None) -> list[Path]:
    """Return all ``harness_*.json`` files in the perf directory, sorted by name."""
    directory = perf_dir or PERF_DIR
    return sorted(directory.glob("harness_*.json"))


def aggregate(
    perf_dir: Path | None = None,
    out_dir: Path | None = None,
) -> AggregationReport:
    """Aggregate valid harness records into publishable CSV + JSONL.

    Args:
        perf_dir: Override for ``docs/performance/``.  Uses the canonical path
            when ``None``.
        out_dir: Directory to write outputs.  Defaults to ``perf_dir``.

    Returns:
        An :class:`AggregationReport` describing what was found and produced.
    """
    directory = perf_dir or PERF_DIR
    output_directory = out_dir or directory
    output_directory.mkdir(parents=True, exist_ok=True)

    paths = discover_records(directory)
    report = AggregationReport(total_found=len(paths))

    valid_records: list[dict[str, Any]] = []

    for path in paths:
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            report.invalid_count += 1
            report.skipped_paths.append((path, [f"Could not parse JSON: {exc}"]))
            print(f"SKIP (parse error): {path.name}: {exc}", file=sys.stderr)
            continue

        result = validate(raw)
        if not result.valid:
            report.invalid_count += 1
            report.skipped_paths.append((path, list(result.errors)))
            print(f"SKIP (invalid): {path.name}", file=sys.stderr)
            for err in result.errors:
                print(f"  - {err}", file=sys.stderr)
            continue

        if result.warnings:
            print(f"WARN: {path.name}", file=sys.stderr)
            for warn in result.warnings:
                print(f"  ~ {warn}", file=sys.stderr)

        scrubbed = _scrub_record(raw)
        # Stamp which source file this came from so the dataset is traceable.
        scrubbed["_source_file"] = path.name
        valid_records.append(scrubbed)
        report.valid_count += 1

    # --- write JSONL ---
    jsonl_path = output_directory / "blarai_perf_dataset.jsonl"
    with jsonl_path.open("w", encoding="utf-8", newline="\n") as fh:
        for rec in valid_records:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    report.output_jsonl = jsonl_path

    # --- write CSV ---
    csv_path = output_directory / "blarai_perf_dataset.csv"
    flat_records = [_flatten_for_csv(r) for r in valid_records]
    # Stable column order: gather all keys seen, with a preferred prefix ordering.
    all_keys: list[str] = []
    seen: set[str] = set()
    preferred_first = ["_source_file", "name", "timestamp", "model", "precision", "methodology"]
    for key in preferred_first:
        if any(key in fr for fr in flat_records):
            all_keys.append(key)
            seen.add(key)
    for fr in flat_records:
        for key in fr:
            if key not in seen:
                all_keys.append(key)
                seen.add(key)

    with csv_path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=all_keys, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(flat_records)
    report.output_csv = csv_path

    return report
