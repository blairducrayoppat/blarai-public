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
from collections.abc import Callable
from pathlib import Path
from typing import Protocol

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
    "conversation",
    "agentic",
)


#: Suites that evaluate NOTHING in a default (no-hardware) run, declared.
#:
#: A suite whose cases are all model-in-the-loop reports ``0/0 passed`` and
#: exits green — it is not protecting anything in CI, and nothing about the
#: output says so. Both new suites were born that way on 2026-09-22 and it took
#: reading the runner's own output to notice (#1624).
#:
#: Membership here is a DECLARATION, not an excuse: the runner prints NO SIGNAL
#: for these, an undeclared inert suite is a harness error, and a gate test
#: asserts this set is exactly the set that evaluates zero cases — so declaring
#: a suite that does have a deterministic floor fails just as loudly. Adding a
#: model-only suite therefore has to be a deliberate, reviewable act.
#:
#: ``conversation`` is here because its subject IS the model's multi-turn
#: judgement; the composition path underneath it is locked separately by
#: tests/integration/test_multiturn_prompt_assembly.py. ``agentic`` is NOT
#: here: its loop mechanics run deterministically from scripted model outputs.
HARDWARE_TIER_SUITES: frozenset[str] = frozenset({"conversation"})


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
    runner: Callable[..., SuiteReport] = module.run_suite
    return runner
