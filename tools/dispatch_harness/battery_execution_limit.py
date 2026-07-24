"""Derive the REQUIRED minimum Task-Scheduler ExecutionTimeLimit for the nightly
M2 battery from the runner's OWN budgets (#833).

Why this exists — the PT10H incident (2026-07-11)
--------------------------------------------------
The nightly battery is launched by a Windows scheduled task
(``\\BlarAI\\BlarAI-M2-Battery-Nightly``) whose ``ExecutionTimeLimit`` is an
OUTER wall-clock ceiling. On 2026-07-11 that ceiling (then PT10H) tree-killed the
runner at 10:00:00 — three minutes before the final job's driver finished — and
the night had to be reconstructed post-hoc (#740 c.1734). The ceiling was an
INVISIBLE-TAXONOMY member (lesson 217 class): it lives in Task Scheduler, outside
``shared/timeout_registry.py``'s sight, and silently overruled every registered
INNER budget — a textbook lesson-221 (window, budget) pair violation where nobody
owned the pair. The immediate fix raised PT10H -> PT16H, but that number was
hand-sized (57600 s == 5 x 10800 + 3600, i.e. 5 jobs) and never recorded anywhere.

The invariant this module owns
------------------------------
The OUTER window (the scheduled task's ExecutionTimeLimit) must DOMINATE the sum
of the runner's INNER per-job budgets, so the task ceiling can never preempt the
runner's own completion/abort logic. This module computes that required minimum
from the SAME constants the runner uses — ``HarnessConfig.swap_run_budget_s`` (the
per-job monitor abort budget), each active card's optional ``run_budget_s``
override (clamped to ``CARD_RUN_BUDGET_MAX_S``), the active campaign job set, and a
per-job re-ensure + fixed campaign overhead — so it can NEVER silently drift from
the runner the way a hand-typed PT16H did.

The ExecutionTimeLimit itself is un-importable (it lives in Task Scheduler), so it
can never be a registered ``TimeoutEntry``; the registry's BACKLOG names the pair
and points HERE for the derivation. ``verify-battery-task-settings.ps1`` (#833)
reads this number and fails loud when the live task's ExecutionTimeLimit is below
it.

Scope note — the pre-run admission wait is deliberately EXCLUDED. The launcher's
23:00->04:00 dispatch/lean admission loop can add up to ~5 h before a run starts,
but it is INDEPENDENTLY bounded by its own 04:00 self-exit cutoff and does not
extend a started run's execution phase; this bound covers the RUN phase the ticket
names ("N jobs x per-job ceiling + swap overhead"). A conforming ExecutionTimeLimit
is therefore NECESSARY-not-sufficient: it covers a full run once one STARTS, but a
night that admits very late could still be preempted even at the floor. That the run
phase alone can approach 19 h already sits close to the 24 h daily cadence — the real
lever for late-start nights is job count / card grain (not a larger ceiling), an
operator (Lead-Architect) reliability call.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Iterable
from pathlib import Path

from shared.fleet.swap_ops import CARD_RUN_BUDGET_MAX_S

from .battery import load_cards
from .config import load_harness_config

# Per-job overhead OUTSIDE the monitored per-job budget: the swap-back (30B -> 14B)
# plus the AoReensurer re-ensure before the next job (``boot_wait_s`` = 180 s in
# tools/dispatch_harness/battery.py, a cold 14B load can exceed 2 min) plus margin.
# Conservative — over-counting overhead only widens the required ceiling, which is
# the safe direction for an anti-preemption bound.
_PER_JOB_OVERHEAD_S: float = 300.0

# Fixed per-night overhead: the preflight (lean/probe/AO detached boot, <= 240 s),
# fresh-sandbox archive+init for each job, and the morning-report write, plus
# margin. Does NOT include the 23:00->04:00 admission wait (self-bounded; see the
# module docstring).
_FIXED_OVERHEAD_S: float = 1800.0

_DEFAULT_AGENTIC_ROOT = Path("C:/Users/mrbla/agentic-setup")
_CAMPAIGN_REL = ("state", "battery-campaign.json")


def default_campaign_path(cfg=None) -> Path:
    """Locate ``state/battery-campaign.json`` under the resolved agentic-setup root.

    Mirrors run-battery-night.ps1, which reads the campaign from the agentic-setup
    checkout the harness config points at (falling back to the documented path for
    this box when the config names no root).
    """
    if cfg is None:
        cfg = load_harness_config()
    root = Path(cfg.agentic_setup_dir) if cfg.agentic_setup_dir else _DEFAULT_AGENTIC_ROOT
    return root.joinpath(*_CAMPAIGN_REL)


def load_campaign_jobs(campaign_path: str | Path | None = None) -> list[str]:
    """The active job ids for a night (``jobs`` in the campaign config).

    ``jobs`` already excludes the ``excluded`` set; this is the MAX job set a night
    can run (the launcher's late-start B6 trim only ever SHRINKS it, so ``jobs`` is
    the worst case for the ceiling). A missing/malformed config raises loudly — a
    ceiling derived from a guessed job set would be exactly the fiction #833 exists
    to prevent.
    """
    path = Path(campaign_path) if campaign_path else default_campaign_path()
    if not path.is_file():
        raise FileNotFoundError(f"battery campaign config not found: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    jobs = data.get("jobs")
    if not isinstance(jobs, list) or not all(isinstance(j, str) for j in jobs):
        raise ValueError(f"{path}: 'jobs' must be a list of job-id strings")
    return list(jobs)


def effective_job_budget_s(card: dict, default_budget_s: float) -> float:
    """One job's monitor abort budget: its ``run_budget_s`` override (clamped to
    ``CARD_RUN_BUDGET_MAX_S``) if set, else the campaign default ``swap_run_budget_s``.

    Mirrors the runner: ``run_budget_s`` absent/0 means "campaign default"; a set
    value is clamped at honor-time by ``swap_ops`` so a card can never bleed past
    the per-card ceiling.
    """
    rb = card.get("run_budget_s") or 0.0
    if isinstance(rb, (int, float)) and rb > 0:
        return min(float(rb), CARD_RUN_BUDGET_MAX_S)
    return default_budget_s


def compose_required_s(job_budgets: Iterable[float]) -> float:
    """The required ExecutionTimeLimit floor: each job's budget + its per-job
    overhead, plus the fixed per-night overhead. Pure arithmetic (the unit-tested
    core), independent of any file or live config.
    """
    return sum(float(b) + _PER_JOB_OVERHEAD_S for b in job_budgets) + _FIXED_OVERHEAD_S


def breakdown(
    *,
    campaign_path: str | Path | None = None,
    config_path: str | Path | None = None,
    spec_dir: str | Path | None = None,
) -> dict:
    """Full derivation with its inputs exposed — the diagnostic surface the verify
    script prints and the finding cites."""
    cfg = load_harness_config(config_path)
    default_budget = float(cfg.swap_run_budget_s)
    jobs = load_campaign_jobs(campaign_path or default_campaign_path(cfg))
    cards = load_cards(Path(spec_dir) if spec_dir else None)
    per_job = [
        {
            "id": jid,
            "budget_s": effective_job_budget_s(cards.get(jid) or {}, default_budget),
            "has_card": jid in cards,
        }
        for jid in jobs
    ]
    required = compose_required_s(row["budget_s"] for row in per_job)
    return {
        "required_s": required,
        "n_jobs": len(jobs),
        "jobs": jobs,
        "default_budget_s": default_budget,
        "per_job_overhead_s": _PER_JOB_OVERHEAD_S,
        "fixed_overhead_s": _FIXED_OVERHEAD_S,
        "per_job": per_job,
    }


def required_execution_limit_s(
    *,
    campaign_path: str | Path | None = None,
    config_path: str | Path | None = None,
    spec_dir: str | Path | None = None,
) -> float:
    """The single number ``verify-battery-task-settings.ps1`` compares the live
    task's ExecutionTimeLimit against."""
    return breakdown(
        campaign_path=campaign_path, config_path=config_path, spec_dir=spec_dir
    )["required_s"]


def _main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        description="Derive the required minimum battery ExecutionTimeLimit (seconds)."
    )
    parser.add_argument("--campaign", default=None, help="battery-campaign.json path")
    parser.add_argument("--config", default=None, help="AO default.toml path")
    parser.add_argument("--spec-dir", default=None, help="battery card spec dir")
    parser.add_argument(
        "--seconds-only",
        action="store_true",
        help="print only the required seconds (integer) — the machine-readable field",
    )
    args = parser.parse_args(argv)
    bd = breakdown(
        campaign_path=args.campaign, config_path=args.config, spec_dir=args.spec_dir
    )
    if args.seconds_only:
        print(int(round(bd["required_s"])))
    else:
        print(json.dumps(bd, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
