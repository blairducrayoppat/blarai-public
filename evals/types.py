"""
Eval Harness — Result Types
============================
Shared result dataclasses for all eval suites.

Statuses:
  pass              — actual behaviour matched the golden expectation.
  fail              — actual behaviour diverged from the golden expectation.
  error             — the harness could not evaluate the case (malformed
                      golden data, unexpected exception in the harness
                      itself). Errors are scored as failures for baseline
                      comparison (fail-closed).
  skipped_hardware  — the case is model-in-the-loop (requires the Arc 140V)
                      and hardware execution was not requested. Skipped
                      cases never count toward pass-rate and never trigger
                      or mask a regression.
  tool_call         — the model answered with a native tool-call block and
                      nothing else. Production would execute the tool loop
                      and show the user its final answer; the single-shot
                      harness cannot (#1023), so the case was REACHED but is
                      UNSCORABLE one-shot. Distinct from an all-<think>
                      empty answer, which production would also display as
                      empty and which therefore stays a scoreable fail.
                      Excluded from pass-rate; every baseline transition
                      involving it is loud (see evals/baseline.py).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class CaseStatus(str, Enum):
    """Outcome of a single golden case."""

    PASS = "pass"
    FAIL = "fail"
    ERROR = "error"
    SKIPPED_HARDWARE = "skipped_hardware"
    TOOL_CALL = "tool_call"


@dataclass(frozen=True)
class CaseResult:
    """Outcome for a single golden case.

    Attributes:
        case_id: Unique golden-case id (e.g. ``pa-det-001``).
        status: The evaluated CaseStatus.
        description: Human-readable case description from the golden file.
        expected: Serializable representation of the expected outcome.
        actual: Serializable representation of the observed outcome.
        detail: Optional harness note (error text, mismatch explanation).
    """

    case_id: str
    status: CaseStatus
    description: str = ""
    expected: Any = None
    actual: Any = None
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable dict for the report."""
        return {
            "id": self.case_id,
            "status": self.status.value,
            "description": self.description,
            "expected": self.expected,
            "actual": self.actual,
            "detail": self.detail,
        }


@dataclass
class SuiteReport:
    """Aggregated result of one eval suite run."""

    suite: str
    results: list[CaseResult] = field(default_factory=list)

    # ------------------------------------------------------------------
    # Aggregates
    # ------------------------------------------------------------------

    @property
    def total(self) -> int:
        return len(self.results)

    @property
    def passed(self) -> int:
        return sum(1 for r in self.results if r.status is CaseStatus.PASS)

    @property
    def failed(self) -> int:
        return sum(1 for r in self.results if r.status is CaseStatus.FAIL)

    @property
    def errors(self) -> int:
        return sum(1 for r in self.results if r.status is CaseStatus.ERROR)

    @property
    def skipped_hardware(self) -> int:
        return sum(
            1 for r in self.results if r.status is CaseStatus.SKIPPED_HARDWARE
        )

    @property
    def tool_calls(self) -> int:
        return sum(1 for r in self.results if r.status is CaseStatus.TOOL_CALL)

    @property
    def evaluated(self) -> int:
        """Cases actually scored (total minus hardware-skipped and
        tool-call cases — reached but unscorable one-shot)."""
        return self.total - self.skipped_hardware - self.tool_calls

    @property
    def pass_rate(self) -> float:
        """passed / evaluated. 0.0 when nothing was evaluated."""
        if self.evaluated == 0:
            return 0.0
        return self.passed / self.evaluated

    def aggregates(self) -> dict[str, Any]:
        """Return the aggregate block for reports and baselines."""
        return {
            "total": self.total,
            "evaluated": self.evaluated,
            "passed": self.passed,
            "failed": self.failed,
            "errors": self.errors,
            "skipped_hardware": self.skipped_hardware,
            "tool_calls": self.tool_calls,
            "pass_rate": round(self.pass_rate, 6),
        }

    def case_statuses(self) -> dict[str, str]:
        """Return {case_id: status} for baseline storage (sorted by id)."""
        return {
            r.case_id: r.status.value
            for r in sorted(self.results, key=lambda r: r.case_id)
        }

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable dict for the report."""
        return {
            "suite": self.suite,
            "aggregates": self.aggregates(),
            "cases": [r.to_dict() for r in self.results],
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, sort_keys=True)
