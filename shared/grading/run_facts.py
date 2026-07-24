"""A run's deterministic facts, re-derived from its ``scorecard.json`` (#1079).

The grading tool's ground truth. Every fact here comes from the run's scorecard
through the SAME production derivations the live harvest uses —
:func:`shared.coordinator.heartbeat_cycle.oracle_passed_from_scorecard` for the
oracle status and :func:`shared.fleet.work_state.outcomes_from_scorecard` for the
per-task results — never from a re-implementation. That reuse is the point: a
grader that re-derived outcomes by reading each task's ``result`` field alone
would mis-read a plan-graph task whose ``status`` is ``parked`` while its cause
token is ``NOTHING`` (live instance: run 20260719-233631-bd), and would then grade
the ruler against a truth the ruler never saw.

Pure apart from the injected reader: ``read_scorecard`` supplies the parsed
document, so fixtures and the live tree drive identical code.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Final

from shared.coordinator.heartbeat_cycle import oracle_passed_from_scorecard
from shared.coordinator.prose_guard import RunTruth
from shared.fleet.work_state import outcomes_from_scorecard

#: The per-task ``result`` token meaning the task's branch reached the project.
RESULT_MERGED: Final[str] = "MERGED"

#: The per-task ``result`` token meaning the task parked (honestly or otherwise).
RESULT_PARKED: Final[str] = "PARKED"

#: ``run_id →`` parsed ``scorecard.json``, or ``None`` when unavailable.
ScorecardReader = Callable[[str], Any]


@dataclass(frozen=True)
class RunFacts:
    """One run's scorecard-derived facts — the grader's ground truth.

    :attr:`any_merged` and :attr:`any_parked` are the two flags the board-move
    ruler consumes (``merged`` / ``parked`` in
    :func:`shared.fleet.coord_lifecycle.resolve_board_transition`).
    :attr:`all_merged` is NOT a ruler input; it exists because drafted prose makes
    universally-quantified merge claims ("all features were merged") that ``any``
    cannot adjudicate."""

    run_id: str
    oracle_passed: bool
    any_merged: bool
    all_merged: bool
    any_parked: bool
    task_count: int
    merged_count: int
    scorecard_verdict: str
    """The scorecard's own ``verdict`` string (GREEN / PARKED-HONEST / …), carried
    for the report's legibility. NOT used in any grading decision — the ruler and
    the guard both derive from the structured flags above, so grading against the
    verdict string would grade a different thing than production reads."""

    task_results: tuple[tuple[str, str], ...] = ()
    """This run's ``(task, result)`` pairs — the ONLY vocabulary #1067's guard
    accepts in the variable positions of its negated-failure carve-out.

    They were read in :func:`read_run_facts` and discarded one line later, and
    the consequence was that this grader called the guard with NO vocabulary. It
    scored the live false-suppression statement as still suppressed — reporting
    the PRE-#1067 rate — while screening the adversarial corpus with a guard
    STRICTER than production, overstating the catch rate. Both numbers described
    a configuration that does not ship, and both feed #1068's pre-specified bar.
    Defaulted, so a caller that omits them degrades to the fail-closed empty
    vocabulary rather than to a wrong one."""

    def run_truth(self) -> RunTruth:
        """The production :class:`~shared.coordinator.prose_guard.RunTruth` these
        facts support.

        This is NOT the whole of what the live cycle passes to the guard, and an
        earlier version of this docstring claimed it was: since #1067 the cycle
        also passes ``task_results``. Callers re-running the guard must forward
        :attr:`task_results` alongside this value, or they are measuring a guard
        that does not ship."""
        return RunTruth(
            run_id=self.run_id,
            oracle_passed=self.oracle_passed,
            merged=self.any_merged,
            parked=self.any_parked,
        )


def read_run_facts(run_id: str, *, read_scorecard: ScorecardReader) -> RunFacts | None:
    """Derive *run_id*'s :class:`RunFacts`, or ``None`` when its scorecard yields
    no usable outcomes.

    ``None`` is a REPORTED state, never a silent zero: a run whose scorecard is
    absent, unreadable, or malformed cannot be graded, and the caller records it
    as ungradable coverage rather than scoring the decision correct by default."""
    scorecard = read_scorecard(run_id)
    outcomes = outcomes_from_scorecard(scorecard)
    if outcomes is None:
        return None
    results = [o.result for o in outcomes]
    merged_count = results.count(RESULT_MERGED)
    verdict = ""
    if isinstance(scorecard, dict):
        raw_verdict = scorecard.get("verdict")
        if isinstance(raw_verdict, str):
            verdict = raw_verdict
    return RunFacts(
        run_id=run_id,
        oracle_passed=oracle_passed_from_scorecard(scorecard),
        any_merged=merged_count > 0,
        all_merged=bool(results) and merged_count == len(results),
        any_parked=RESULT_PARKED in results,
        task_count=len(results),
        merged_count=merged_count,
        task_results=tuple((o.task, o.result) for o in outcomes),
        scorecard_verdict=verdict,
    )


def file_scorecard_reader(runs_dir: Path) -> ScorecardReader:
    """A :data:`ScorecardReader` over ``runs_dir/<run_id>/scorecard.json``.

    Fail-soft on the read exactly as the live cycle's default reader is
    (:func:`shared.coordinator.heartbeat_cycle._default_read_scorecard`): an
    absent or unparseable file yields ``None``, which
    :func:`read_run_facts` turns into a reported ungradable run."""

    def _read(run_id: str) -> Any:
        try:
            return json.loads(
                (runs_dir / run_id / "scorecard.json").read_text(encoding="utf-8")
            )
        except (OSError, ValueError, TypeError):
            return None

    return _read
