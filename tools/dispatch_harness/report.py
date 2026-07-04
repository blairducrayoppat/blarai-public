"""Structured per-job + sweep report assembly.

Each dispatched job accumulates a :class:`JobReport` (plan ok?, asked a clarifying question?,
what it answered, the run id, the classified outcome, wall-clock, and a stop reason if the
monitor stopped it). The sweep collects them into a :class:`SweepReport` that renders a compact
human table plus a machine-readable dict (so the LA can eyeball it or save it).

Pure data + rendering — no I/O, no model, no live AO. Assembled by the harness; unit-tested
directly with hand-built reports.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field


@dataclass
class JobReport:
    """The outcome record for one dispatched job."""

    repo: str
    goal: str
    plan_ok: bool = False           # PLAN returned criteria (vs a refusal / wiring notice)
    asked_clarifying: bool = False  # the coordinator asked an Inc-4 question
    answered: str = ""              # the option number/text the harness replied with
    approved: bool = False          # /dispatch approve fired EXECUTE successfully
    run_id: str = ""
    outcome: str = ""               # MERGED | PARKED | BLOCKED | NOTHING | UNKNOWN | NONE | ""
    verdict: str = ""               # the monitor's DoomVerdict (COMPLETE/DOOMED/FAILED/…)
    expected: str = ""              # the job's expected outcome (annotation only)
    wall_clock_s: float = 0.0
    stop_reason: str = ""           # why the monitor stopped (doom/timeout/failure), if any
    error: str = ""                 # a hard error that aborted the job before/at dispatch
    plan_preview: str = ""          # the first lines of the PLAN preview (for the log)
    progress_tail: str = ""         # the swap-progress trail (what happened during the swap)

    @property
    def expectation_met(self) -> str:
        """``"n/a"`` when no expectation was set, else ``"met"`` / ``"UNMET"``."""
        if not self.expected:
            return "n/a"
        return "met" if self.outcome == self.expected else "UNMET"

    @property
    def ok(self) -> bool:
        """A job is 'ok' if it reached a clean COMPLETE with no hard error. (PARKED/BLOCKED are
        still COMPLETE runs — a real fleet result the operator reviews — so 'ok' here means 'the
        pipeline ran end to end', not 'the code merged'.)"""
        return not self.error and self.verdict == "COMPLETE"

    def to_dict(self) -> dict:
        d = asdict(self)
        d["expectation_met"] = self.expectation_met
        d["ok"] = self.ok
        return d


@dataclass
class SweepReport:
    """The accumulated report for a whole sweep (one or many jobs)."""

    jobs: list[JobReport] = field(default_factory=list)
    dry_run: bool = False

    def add(self, job: JobReport) -> None:
        self.jobs.append(job)

    def to_dict(self) -> dict:
        return {
            "dry_run": self.dry_run,
            "total": len(self.jobs),
            "complete": sum(1 for j in self.jobs if j.verdict == "COMPLETE"),
            "doomed": sum(1 for j in self.jobs if j.verdict in ("DOOMED", "FAILED")),
            "errored": sum(1 for j in self.jobs if j.error),
            "jobs": [j.to_dict() for j in self.jobs],
        }

    def to_json(self, *, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent)

    def render(self) -> str:
        """A compact human-readable summary table + per-job detail."""
        if not self.jobs:
            return "Dispatch sweep: no jobs ran."
        lines: list[str] = []
        head = "Dispatch sweep" + (" (DRY-RUN — fake in-process AO)" if self.dry_run else "")
        lines.append(head)
        lines.append("=" * len(head))
        for i, j in enumerate(self.jobs, start=1):
            status = j.error or j.verdict or "?"
            outcome = j.outcome or "—"
            exp = "" if j.expectation_met == "n/a" else f"  [expected {j.expected}: {j.expectation_met}]"
            lines.append(
                f"{i}. {j.repo} | {j.goal}"
            )
            lines.append(
                f"     plan_ok={j.plan_ok}  asked={j.asked_clarifying}"
                + (f' answered="{j.answered}"' if j.asked_clarifying else "")
                + f"  approved={j.approved}"
            )
            lines.append(
                f"     run_id={j.run_id or '—'}  status={status}  outcome={outcome}"
                f"  ({j.wall_clock_s:.0f}s){exp}"
            )
            if j.stop_reason:
                lines.append(f"     stopped: {j.stop_reason}")
            if j.error:
                lines.append(f"     ERROR: {j.error}")
        ok_n = sum(1 for j in self.jobs if j.verdict == "COMPLETE")
        lines.append("")
        lines.append(
            f"Completed {ok_n}/{len(self.jobs)} run(s) end-to-end; "
            f"{sum(1 for j in self.jobs if j.verdict in ('DOOMED', 'FAILED'))} stopped, "
            f"{sum(1 for j in self.jobs if j.error)} errored before dispatch."
        )
        return "\n".join(lines)
