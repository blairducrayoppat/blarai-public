"""
Eval Harness — Baseline Storage and Regression Comparison
==========================================================
A baseline is a committed JSON snapshot of per-case statuses for one suite.
Comparison semantics (fail-closed):

  REGRESSION (exit nonzero):
    * a case that PASSED in the baseline now fails or errors;
    * a case failing/erroring now that is ABSENT from the baseline (a new
      case must either pass or be consciously baselined as a known-fail);
    * a case present in the baseline that is missing from the run (a golden
      case was removed without refreshing the baseline).

  NOT a regression:
    * a case that failed in the baseline and still fails (a *known* model
      deficiency being tracked — e.g. ISS-3 classification misses);
    * a case that failed in the baseline and now passes (an IMPROVEMENT —
      reported so the operator can refresh the baseline);
    * hardware-skipped cases (never scored, never compared).
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from evals.types import CaseStatus, SuiteReport

BASELINE_DIR: Path = Path(__file__).parent / "baselines"

_FAILING = {CaseStatus.FAIL, CaseStatus.ERROR}


class BaselineError(Exception):
    """A baseline file is missing or malformed (harness error, exit 2)."""


@dataclass
class Comparison:
    """Result of comparing a suite run against its committed baseline."""

    suite: str
    regressions: list[str] = field(default_factory=list)
    improvements: list[str] = field(default_factory=list)
    known_failures: list[str] = field(default_factory=list)

    @property
    def has_regressions(self) -> bool:
        return bool(self.regressions)

    def to_dict(self) -> dict[str, Any]:
        return {
            "suite": self.suite,
            "has_regressions": self.has_regressions,
            "regressions": list(self.regressions),
            "improvements": list(self.improvements),
            "known_failures": list(self.known_failures),
        }


def _resolve_git_sha() -> str:
    """Best-effort short git SHA for baseline provenance."""
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            stderr=subprocess.DEVNULL,
            text=True,
            cwd=Path(__file__).parent,
        ).strip()
    except Exception:  # noqa: BLE001 — provenance only, never load-bearing
        return "unknown"


def baseline_path(suite: str, baseline_dir: Path = BASELINE_DIR) -> Path:
    return baseline_dir / f"{suite}.json"


def write_baseline(
    report: SuiteReport, baseline_dir: Path = BASELINE_DIR
) -> Path:
    """Write (or refresh) the committed baseline for a suite.

    Hardware-skipped cases are stored with their skipped status so the
    baseline documents which cases are model-in-the-loop, but they are
    never compared.

    Returns:
        Path to the written baseline file.
    """
    baseline_dir.mkdir(parents=True, exist_ok=True)
    path = baseline_path(report.suite, baseline_dir)
    payload: dict[str, Any] = {
        "suite": report.suite,
        "git_sha": _resolve_git_sha(),
        "generated_at": datetime.now(tz=timezone.utc).isoformat(),
        "aggregates": report.aggregates(),
        "cases": report.case_statuses(),
    }
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return path


def load_baseline(
    suite: str, baseline_dir: Path = BASELINE_DIR
) -> dict[str, Any]:
    """Load and validate the committed baseline for a suite.

    Raises:
        BaselineError: If the baseline file is missing or malformed.
    """
    path = baseline_path(suite, baseline_dir)
    if not path.exists():
        raise BaselineError(
            f"No committed baseline for suite '{suite}' at {path}. "
            f"Generate one with: python -m evals.run --suite {suite} "
            f"--write-baseline"
        )
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise BaselineError(f"Baseline {path} is not valid JSON: {exc}") from exc
    if not isinstance(payload, dict) or "cases" not in payload:
        raise BaselineError(f"Baseline {path} is missing the 'cases' block")
    cases = payload["cases"]
    if not isinstance(cases, dict):
        raise BaselineError(f"Baseline {path} 'cases' must be an object")
    return payload


def compare(
    report: SuiteReport, baseline: dict[str, Any]
) -> Comparison:
    """Compare a suite run against its baseline (see module docstring)."""
    baseline_cases: dict[str, str] = dict(baseline.get("cases", {}))
    comparison = Comparison(suite=report.suite)

    run_ids: set[str] = set()
    for result in report.results:
        run_ids.add(result.case_id)
        if result.status is CaseStatus.SKIPPED_HARDWARE:
            continue
        base_status = baseline_cases.get(result.case_id)
        if result.status in _FAILING:
            if base_status is None:
                comparison.regressions.append(
                    f"new failing case not in baseline: {result.case_id} "
                    f"({result.status.value}: {result.detail or 'mismatch'})"
                )
            elif base_status == CaseStatus.PASS.value:
                comparison.regressions.append(
                    f"regressed vs baseline: {result.case_id} "
                    f"(baseline pass -> {result.status.value}: "
                    f"{result.detail or 'mismatch'})"
                )
            else:
                comparison.known_failures.append(result.case_id)
        elif result.status is CaseStatus.PASS and base_status in (
            CaseStatus.FAIL.value,
            CaseStatus.ERROR.value,
        ):
            comparison.improvements.append(result.case_id)

    # A baselined case that vanished from the run — the golden set shrank
    # (or an id was renamed) without a conscious baseline refresh.
    for case_id, base_status in baseline_cases.items():
        if case_id not in run_ids and base_status != (
            CaseStatus.SKIPPED_HARDWARE.value
        ):
            comparison.regressions.append(
                f"baselined case missing from run: {case_id}"
            )

    return comparison
