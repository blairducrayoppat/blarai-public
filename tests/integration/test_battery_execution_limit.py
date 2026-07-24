"""#833 — the battery ExecutionTimeLimit derivation is the OWNED (window, budget)
pair for the un-importable Task-Scheduler ceiling (the PT10H incident's durable
control). These locks freeze the arithmetic so the derived floor can never drift
from the runner's constants the way the hand-typed PT16H did.
"""

from __future__ import annotations

import json

import pytest

from shared.fleet.swap_ops import CARD_RUN_BUDGET_MAX_S
from tools.dispatch_harness import battery_execution_limit as bel
from tools.dispatch_harness.battery import load_cards

# ---------------------------------------------------------------------------
# #927 coherence constants (LA-approved 2026-07-17 c.2156). The coherence lock
# agentic-setup/scripts/verify-battery-budget-coherence.ps1 is the LIVE teeth;
# these BlarAI-side locks freeze the half it reads (the card budgets + the
# derivation) so the (window, budget) pair can never silently drift.
# ---------------------------------------------------------------------------

# C2 floor: a 2-wave, best-of-2 job needs 2 x 2 x 3600 s = 14400 s of per-job
# budget; the 10800 s swap_run_budget_s default is the PROVEN C2 FAIL
# (10800 < 14400). Every multi-wave card must clear this minimum.
_C2_MIN_PER_JOB_BUDGET_S = 14400.0

# C3 ceiling: the live Task-Scheduler ExecutionTimeLimit (PT16H). Un-importable
# (it lives in Windows Task Scheduler — the EXTERNAL row in the timeout-registry
# BACKLOG), mirrored here as the ceiling the derived floor must stay under.
# verify-battery-task-settings.ps1 is the live out-of-band check (T4).
_PT16H_CEILING_S = 57600.0

# The active lean campaign (agentic-setup/state/battery-campaign.json jobs=[B2,B4],
# the #904 trim) — the multi-wave cards #927 provisions per-card budgets on.
_ACTIVE_MULTIWAVE_CARDS = ("B2", "B4")


# ---------------------------------------------------------------------------
# The pure arithmetic core — the real regression lock (no files, deterministic).
# ---------------------------------------------------------------------------


def test_compose_sums_each_budget_plus_per_job_and_fixed_overhead():
    # 6 default jobs (the 2026-07-15 campaign): 6 x (10800 + 300) + 1800 = 68400 s
    # = 19.0 h — the number the verify script asserts the live task dominates.
    assert bel.compose_required_s([10800.0] * 6) == 6 * (10800.0 + 300.0) + 1800.0
    assert bel.compose_required_s([10800.0] * 6) == 68400.0


def test_compose_empty_job_set_is_fixed_overhead_only():
    assert bel.compose_required_s([]) == bel._FIXED_OVERHEAD_S


def test_overhead_constants_are_pinned():
    # Pin each constant directly so a compensating dual change (raise one, lower the
    # other) cannot slip through the aggregate assertion above.
    assert bel._PER_JOB_OVERHEAD_S == 300.0
    assert bel._FIXED_OVERHEAD_S == 1800.0


def test_compose_dominates_the_raw_inner_budget_sum():
    # The invariant #833 enforces: the outer window always EXCEEDS the sum of the
    # inner per-job budgets (overhead is strictly positive), so the task ceiling
    # can never preempt the runner's own completion/abort logic.
    budgets = [10800.0, 10800.0, 21600.0]
    assert bel.compose_required_s(budgets) > sum(budgets)


def test_effective_budget_defaults_when_override_absent_or_zero():
    assert bel.effective_job_budget_s({}, 10800.0) == 10800.0
    assert bel.effective_job_budget_s({"run_budget_s": 0}, 10800.0) == 10800.0
    assert bel.effective_job_budget_s({"run_budget_s": None}, 10800.0) == 10800.0


def test_effective_budget_honors_a_positive_override():
    assert bel.effective_job_budget_s({"run_budget_s": 21600}, 10800.0) == 21600.0


def test_effective_budget_clamps_to_the_per_card_ceiling():
    over = CARD_RUN_BUDGET_MAX_S + 100000
    assert bel.effective_job_budget_s({"run_budget_s": over}, 10800.0) == CARD_RUN_BUDGET_MAX_S


# ---------------------------------------------------------------------------
# Campaign job-set loading (tmp fixtures — deterministic, no live config).
# ---------------------------------------------------------------------------


def test_load_campaign_jobs_reads_the_jobs_list(tmp_path):
    p = tmp_path / "battery-campaign.json"
    p.write_text(json.dumps({"jobs": ["B1", "B2", "B4"]}), encoding="utf-8")
    assert bel.load_campaign_jobs(p) == ["B1", "B2", "B4"]


def test_load_campaign_jobs_missing_file_fails_loud(tmp_path):
    with pytest.raises(FileNotFoundError):
        bel.load_campaign_jobs(tmp_path / "nope.json")


def test_load_campaign_jobs_malformed_jobs_fails_loud(tmp_path):
    p = tmp_path / "battery-campaign.json"
    p.write_text(json.dumps({"jobs": "B1"}), encoding="utf-8")
    with pytest.raises(ValueError):
        bel.load_campaign_jobs(p)


# ---------------------------------------------------------------------------
# Live smoke test — the real derivation must be sane (skips if the campaign
# config is absent, e.g. an isolated worktree without the agentic-setup box).
# ---------------------------------------------------------------------------


def test_live_derivation_is_sane_and_includes_overhead():
    if not bel.default_campaign_path().is_file():
        pytest.skip("battery-campaign.json not present on this checkout")
    bd = bel.breakdown()
    assert bd["required_s"] > 0
    # Overhead is always included, so the floor strictly exceeds the raw sum of
    # the per-job budgets — never merely equals it.
    raw = sum(row["budget_s"] for row in bd["per_job"])
    assert bd["required_s"] > raw
    assert bd["n_jobs"] == len(bd["jobs"])


# ---------------------------------------------------------------------------
# #927 — the per-card (window, budget) coherence lock (LA-approved 2026-07-17).
# The multi-wave active-campaign cards carry a per-card run_budget_s that clears
# the coherence lock's C2 floor WITHOUT a global swap_run_budget_s bump, so the
# derived RUN-phase floor stays under the un-importable PT16H Task-Scheduler
# ceiling (C3 / #833 T4). These read the REAL in-repo cards (evals/battery), so
# they lock the BlarAI-side half the ps1 coherence verifier reads.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("card_id", _ACTIVE_MULTIWAVE_CARDS)
def test_927_multiwave_card_clears_c2_floor_and_rides_below_the_clamp(card_id):
    card = load_cards()[card_id]
    rb = card.get("run_budget_s")
    assert isinstance(rb, (int, float)) and rb > 0, (
        f"{card_id}: #927 requires an explicit per-card run_budget_s on the "
        f"multi-wave cards — absent/0 falls back to the 10800 s C2-FAIL default"
    )
    assert rb >= _C2_MIN_PER_JOB_BUDGET_S, (
        f"{card_id}: run_budget_s {rb} < the {_C2_MIN_PER_JOB_BUDGET_S} s C2 "
        f"floor — a multi-wave job below the 2-wave/best-of-2 minimum re-opens "
        f"the overall-run-budget starvation #927 closed"
    )
    assert rb <= CARD_RUN_BUDGET_MAX_S, (
        f"{card_id}: run_budget_s {rb} exceeds the {CARD_RUN_BUDGET_MAX_S} s "
        f"per-card clamp (CARD_RUN_BUDGET_MAX_S)"
    )


def test_927_lean_campaign_floor_stays_under_pt16h_ceiling():
    # C3: with the #927 per-card budgets the LEAN campaign's derived RUN-phase
    # floor must stay UNDER the PT16H ceiling — the guard that the per-card (not
    # global) lever cannot re-cross the ceiling a blanket 14400 bump would have
    # (the ~25 h/6-job floor the #927 finding rejected).
    cards = load_cards()
    budgets = [
        bel.effective_job_budget_s(cards[cid], bel.load_harness_config().swap_run_budget_s)
        for cid in _ACTIVE_MULTIWAVE_CARDS
    ]
    floor = bel.compose_required_s(budgets)
    assert floor <= _PT16H_CEILING_S, (
        f"lean-campaign derived floor {floor} s exceeds the PT16H ceiling "
        f"{_PT16H_CEILING_S} s — the #927 per-card budgets no longer fit under "
        f"the Task-Scheduler ExecutionTimeLimit (verify-battery-task-settings.ps1 T4)"
    )
    # Overhead is always included: the floor strictly exceeds the raw budget sum.
    assert floor > sum(budgets)
