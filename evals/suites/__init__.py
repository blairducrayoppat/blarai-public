"""
Eval Harness — Suite Registry
==============================
Each suite module exposes:

    run_suite(golden_path: Path | None = None,
              *, include_hardware: bool = False,
              model_target: ModelTarget | None = None) -> SuiteReport

Suites are registered here by name; ``evals.run`` resolves them lazily so
that importing one suite's (potentially heavy) dependencies is never paid
for a run of a different suite.

``model_target`` (#931) is the OPT-IN hardware model-target override — passed
uniformly to every runner exactly like ``include_hardware``. Model-in-the-loop
suites consume it to select the pipeline class / model directory; the fully
deterministic suites (governance, tool_calling, coordinator) accept and ignore
it, since they load no model. ``None`` (the default) keeps every suite's
byte-identical default 14B path.
"""

from __future__ import annotations

import importlib
from pathlib import Path
from typing import Callable, Protocol

from evals.model_target import ModelTarget
from evals.types import SuiteReport


class SuiteRunner(Protocol):
    def __call__(
        self,
        golden_path: Path | None = None,
        *,
        include_hardware: bool = False,
        model_target: ModelTarget | None = None,
    ) -> SuiteReport: ...


SUITE_NAMES: tuple[str, ...] = (
    "pa_classification",
    "tool_calling",
    "governance",
    "answer_quality",
    "oracle_quality",
    "preference_memory",
    "coordinator",
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
