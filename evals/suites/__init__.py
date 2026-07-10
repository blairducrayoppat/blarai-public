"""
Eval Harness — Suite Registry
==============================
Each suite module exposes:

    run_suite(golden_path: Path | None = None,
              *, include_hardware: bool = False) -> SuiteReport

Suites are registered here by name; ``evals.run`` resolves them lazily so
that importing one suite's (potentially heavy) dependencies is never paid
for a run of a different suite.
"""

from __future__ import annotations

import importlib
from pathlib import Path
from typing import Callable, Protocol

from evals.types import SuiteReport


class SuiteRunner(Protocol):
    def __call__(
        self,
        golden_path: Path | None = None,
        *,
        include_hardware: bool = False,
    ) -> SuiteReport: ...


SUITE_NAMES: tuple[str, ...] = (
    "pa_classification",
    "tool_calling",
    "governance",
    "answer_quality",
    "oracle_quality",
)


def get_runner(suite: str) -> SuiteRunner:
    """Resolve a suite runner by name (lazy import).

    Raises:
        KeyError: If the suite name is unknown.
    """
    if suite not in SUITE_NAMES:
        raise KeyError(
            f"Unknown suite '{suite}'. Available: {', '.join(SUITE_NAMES)}"
        )
    module = importlib.import_module(f"evals.suites.{suite}")
    runner: Callable[..., SuiteReport] = getattr(module, "run_suite")
    return runner
