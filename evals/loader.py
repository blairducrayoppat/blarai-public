"""
Eval Harness — Golden-Set Loader
=================================
JSONL loader shared by all suites (one JSON object per line, blank lines
ignored — the same convention as tests/pa_quality_benchmark/corpus.jsonl).

Every golden case carries at minimum:
  id           — unique within the suite (stable across runs; baselines key on it).
  description  — human-readable intent of the case.

Suite-specific fields are validated by each suite runner.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

GOLDEN_DIR: Path = Path(__file__).parent / "golden"


class GoldenDataError(Exception):
    """A golden file is missing or malformed (harness error, exit 2)."""


def golden_path(suite: str, golden_dir: Path = GOLDEN_DIR) -> Path:
    return golden_dir / f"{suite}.jsonl"


def load_golden(path: Path) -> list[dict[str, Any]]:
    """Load a golden JSONL file.

    Args:
        path: Path to the .jsonl golden file.

    Returns:
        List of case dicts in file order.

    Raises:
        GoldenDataError: If the file is missing, a line is malformed, a
            required field is absent, or two cases share an id.
    """
    if not path.exists():
        raise GoldenDataError(f"Golden file not found: {path}")

    cases: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    with open(path, encoding="utf-8") as fh:
        for lineno, line in enumerate(fh, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                case = json.loads(line)
            except json.JSONDecodeError as exc:
                raise GoldenDataError(
                    f"{path.name} line {lineno}: invalid JSON — {exc}"
                ) from exc
            if not isinstance(case, dict):
                raise GoldenDataError(
                    f"{path.name} line {lineno}: case must be a JSON object"
                )
            for required in ("id", "description"):
                if required not in case:
                    raise GoldenDataError(
                        f"{path.name} line {lineno}: missing required "
                        f"field '{required}'"
                    )
            case_id = str(case["id"])
            if case_id in seen_ids:
                raise GoldenDataError(
                    f"{path.name} line {lineno}: duplicate case id "
                    f"'{case_id}'"
                )
            seen_ids.add(case_id)
            cases.append(case)

    if not cases:
        raise GoldenDataError(f"{path.name}: golden file is empty")
    return cases
