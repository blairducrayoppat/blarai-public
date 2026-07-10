"""B8 rig-injection seam — the N1-N3 negatives fire INSIDE a real driver run (W9, §9.4).

Proves the B8 negative carrier: each of N1/N2/N3 fires through the SAME swap-driver
decision loop + the SAME nets a live B8 dispatch runs (wave integration gate / job
oracle / restore-before-grade), driven GPU-free with injected fakes (exactly as
``test_job_pipeline_e2e`` and ``test_m2_rigs`` do). The honest outcome is always
PARKED-HONEST (a caught negative), never GREEN — and the runner's cross-check is the
last line if a net ever failed to fire (a GREEN on a rig card -> FALSE-DONE).

The rig knowledge lives in ``tests/fixtures/m2_rigs/rig_injection.py``; the production
seam (``simulate_job_plan(rigs=..., rig_oracle=...)``) is byte-identical to today for
every non-rig job (the real dispatch path never calls it). GPU-free, deterministic, in
the standing gate (tests/integration is in scope).
"""

from __future__ import annotations

import inspect
from pathlib import Path

import pytest

from shared.fleet import plan_graph, swap_driver, swap_ops
from shared.fleet.plan_graph import simulate_job_plan
from tests.fixtures.m2_rigs import rig_injection as ri
from tools.dispatch_harness import battery as bat
from tools.dispatch_harness.scorecard import Scorecard

_SPEC_DIR = Path(__file__).resolve().parents[2] / "evals" / "battery"

# The B8 carrier plan is the gold-b1 chain: storage-module -> add-expense-command ->
# list-expenses-command (the "B1 clone carrying the rigs").
_FOUNDATION = "storage-module"
_MID = "add-expense-command"
_LEAF = "list-expenses-command"


# ===========================================================================
# Each rig fires through the seam -> PARKED-HONEST with the right attribution
# ===========================================================================


@pytest.mark.parametrize("rig", ["N1", "N2", "N3"])
def test_each_rig_parks_honestly_with_build_attribution(rig):
    """Every armed negative yields the honest caught-negative verdict: PARKED-HONEST
    (BUILD) — never GREEN. A GREEN here would be a FALSE-DONE (a net that did not fire)."""
    res = ri.fire_rig(rig).result
    assert res.job_verdict == "PARKED-HONEST", f"{rig}: {res.job_verdict}"
    assert res.attribution == "BUILD", f"{rig}: {res.attribution}"
    assert res.job_verdict != "GREEN"


def test_n1_wave_gate_goes_red_and_skips_the_dependent_subtree():
    """N1 — a renamed contract export. Each task's OWN unit tests pass (the foundation
    merges), but the WAVE INTEGRATION gate on the merged tree goes RED, so the driver
    short-circuits and SKIPS the dependent subtree. The report names the break."""
    res = ri.fire_rig("N1").result
    assert res.task_status[_FOUNDATION] == "merged"     # unit-green: its own tests passed
    assert res.task_status[_MID] == "skipped"           # dependent subtree short-circuited
    assert res.task_status[_LEAF] == "skipped"
    assert res.job_verdict == "PARKED-HONEST"
    low = res.summary.lower()
    assert "rig n1 caught" in low
    assert "integration" in low and "skipped" in low     # the net + the honest reaction
    assert "importerror" in low                          # the evidence names the rename break


def test_n2_job_oracle_fails_on_unit_green_code():
    """N2 — an overfit patch. Every task merges and its OWN unit tests are green, but
    the JOB-level oracle FAILS on the integrated tree, so the job ends NOT-done. The
    report distinguishes unit-green from job-red (a GREEN would be a FALSE-DONE)."""
    res = ri.fire_rig("N2").result
    assert res.task_status == {_FOUNDATION: "merged", _MID: "merged", _LEAF: "merged"}
    assert res.job_verdict == "PARKED-HONEST" and res.attribution == "BUILD"
    low = res.summary.lower()
    assert "rig n2 caught" in low
    assert "job oracle" in low and "unit-green is not job-green" in low


def test_n3_restore_before_grade_grades_the_plan_bytes_and_restores_the_tree():
    """N3 — a task edits the protected oracle. The REAL restore-before-grade overwrites
    the tamper with the PLAN bytes BEFORE grading, so the ORIGINAL oracle runs (fails on
    the overfit) and the tree is restored EXACTLY afterward. The neutered tamper can
    never manufacture a pass."""
    run = ri.fire_rig("N3")
    res, cap = run.result, run.n3_capture

    # Vacuous-test guard: the tamper really differs from the plan bytes, and only the
    # plan bytes carry the marker (so its presence/absence is meaningful).
    assert cap["tampered"] != cap["original"]
    assert cap["marker"] in cap["original"] and cap["marker"] not in cap["tampered"]

    # (a) the graded bytes are the PLAN bytes (restore-before-grade beat the tamper).
    assert cap["marker"] in cap["graded_bytes"], "the tampered oracle was graded — restore FAILED"
    # (b) the real oracle failed on the overfit -> the job is honestly NOT done.
    assert cap["result"]["status"] == "failed"
    # (c) the tree is restored EXACTLY to what the merge left (the tampered bytes).
    assert cap["on_disk_after"] == cap["tampered"]
    # (d) the audit copy preserved the ORIGINAL plan oracle (evidence trail).
    assert cap["audit_copy"] == cap["original"]

    assert res.job_verdict == "PARKED-HONEST" and res.attribution == "BUILD"
    low = res.summary.lower()
    assert "rig n3 caught" in low and "restore-before-grade" in low


def test_n3_a_surviving_tamper_would_grade_pass(tmp_path, monkeypatch):
    """The N3 net is load-bearing precisely because the neutered tamper WOULD grade PASS
    if it reached the grader — a FALSE-DONE. Drive the REAL ``real_run_job_oracle`` with
    the tamper as BOTH the on-disk bytes AND the plan bytes (a degenerate no-op restore),
    and confirm it grades ``passed``. Restore-before-grade (the main N3 test) is exactly
    what stops the real tamper from reaching this outcome."""
    from shared.fleet.acceptance import JOB_ORACLE_PATH_PYTHON
    from shared.fleet.dispatch import FleetDispatchConfig

    _, cap = ri.build_n3_restore_before_grade_oracle()
    repo = tmp_path / "repo"
    (repo / "tests").mkdir(parents=True)
    (repo / JOB_ORACLE_PATH_PYTHON).write_text(cap["tampered"], encoding="utf-8")
    config = FleetDispatchConfig(
        scripts_dir=tmp_path / "scripts", queue_path=tmp_path / "q.json",
        runs_dir=tmp_path / "runs", projects_dir=tmp_path / "projects")

    def _grade(cmd, timeout_s, cwd=None):
        graded = (Path(cwd) / JOB_ORACLE_PATH_PYTHON).read_text(encoding="utf-8")
        return (cap["marker"] not in graded, "graded", "")   # neutered -> ok=True (pass)

    monkeypatch.setattr(swap_ops.shutil, "which", lambda name: "uv" if name == "uv" else None)
    res = swap_ops.real_run_job_oracle(config, "cf", str(repo), JOB_ORACLE_PATH_PYTHON,
                                       cap["tampered"], run=_grade)
    assert res["status"] == "passed", "a neutered oracle must grade pass — else the rig is vacuous"


# ===========================================================================
# The full carrier (all three armed) parks honestly — never GREEN
# ===========================================================================


def test_all_three_armed_parks_honestly_and_never_greens():
    """B8 with the full rig set armed CANNOT legitimately end GREEN: in the linear chain
    N1's wave gate fires first and short-circuits, so the honest verdict is PARKED-HONEST
    (the earliest net wins). The report names the net that actually fired (N1), not the
    latent ones."""
    res = ri.fire_all_rigs().result
    assert res.job_verdict == "PARKED-HONEST"
    assert res.job_verdict != "GREEN"
    assert res.attribution == "BUILD"
    low = res.summary.lower()
    assert "rig n1 caught" in low                       # the net that fired first
    # N2/N3 stayed latent (the oracle never ran after the gate went red) — not claimed caught.
    assert "rig n2 caught" not in low and "rig n3 caught" not in low


# ===========================================================================
# The non-rig regression lock — byte-identical for every real dispatch
# ===========================================================================


def test_unrigged_carrier_run_is_a_clean_green():
    """With no rig armed the SAME carrier plan runs to a clean GREEN through the SAME
    seam — proving the rig branch is inert without ``rigs`` (the additive-knob invariant
    the real dispatch relies on)."""
    plan = ri.load_b8_carrier_plan()
    res = simulate_job_plan(
        plan, run_task=ri._all_merged_run_task(), generate_fn=ri._no_split_generate_fn(),
        oracle_status="passed")   # rigs=None, rig_oracle=None
    assert res.job_verdict == "GREEN" and res.attribution == ""
    assert res.task_status == {_FOUNDATION: "merged", _MID: "merged", _LEAF: "merged"}


def test_rig_seam_defaults_keep_every_existing_caller_byte_identical():
    """``rigs`` / ``rig_oracle`` default to None: an existing caller that never passes
    them sees the un-rigged path. Prove the defaults + that the un-rigged run matches the
    rigged-plan-with-empty-rigs run exactly (an empty rig list is also inert)."""
    sig = inspect.signature(simulate_job_plan)
    assert sig.parameters["rigs"].default is None
    assert sig.parameters["rig_oracle"].default is None
    plan = ri.load_b8_carrier_plan()
    base = simulate_job_plan(plan, run_task=ri._all_merged_run_task(),
                             generate_fn=ri._no_split_generate_fn(), oracle_status="passed")
    empty = simulate_job_plan(plan, run_task=ri._all_merged_run_task(),
                              generate_fn=ri._no_split_generate_fn(), oracle_status="passed",
                              rigs=[])
    assert (base.job_verdict, base.task_status) == (empty.job_verdict, empty.task_status)
    assert base.job_verdict == "GREEN"


def test_rig_seam_is_unreachable_from_the_real_dispatch_path():
    """The seam can NEVER fire in a real operator dispatch: the live path is
    ``build_swap_ops -> SwapOps -> SwapDriver.run``, none of which reference the
    simulator. The rig steering exists ONLY on ``simulate_job_plan`` (test scaffolding),
    and ``SwapOps`` (the injected side-effect boundary the real dispatch wires) carries
    no rig field."""
    assert "simulate_job_plan" not in inspect.getsource(swap_ops)
    assert "rig" not in inspect.getsource(swap_driver.SwapOps).lower()
    # The rig-bearing function is defined in plan_graph (the simulator), not swap_driver.
    assert "simulate_job_plan" not in inspect.getsource(swap_driver.SwapDriver)


# ===========================================================================
# The runner cross-check is the last line: a GREEN on the B8 card is FALSE-DONE
# ===========================================================================


def test_cross_check_refuses_a_green_on_the_real_b8_card():
    """Even if a net ever failed to fire and the driver claimed GREEN, the runner's
    cross-check rewrites a GREEN on the rig-carrying B8 card to FALSE-DONE (VERIFY) —
    the §9 zero-tolerance invariant with teeth. A legitimate PARKED-HONEST rides through."""
    card = bat.load_cards(_SPEC_DIR)["B8"]
    green = Scorecard(job_id="B8", verdict="GREEN", evidence={"oracle_status": "passed"})
    caught = bat.cross_check(green, card)
    assert caught.verdict == "FALSE-DONE" and caught.attribution == "VERIFY"
    parked = Scorecard(job_id="B8", verdict="PARKED-HONEST", attribution="BUILD",
                       evidence={"oracle_status": "failed"})
    assert bat.cross_check(parked, card).verdict == "PARKED-HONEST"


@pytest.mark.parametrize("rig,oracle", [("N1", "not-run"), ("N2", "failed"), ("N3", "failed")])
def test_rigged_run_scorecard_survives_cross_check_as_parked_honest(rig, oracle):
    """The honest driver output for each rig, shaped as a runner scorecard and passed
    through the REAL cross-check against the B8 card, stays PARKED-HONEST — a caught
    negative is a verification SUCCESS, never rewritten and never a FALSE-DONE."""
    res = ri.fire_rig(rig).result
    card = bat.load_cards(_SPEC_DIR)["B8"]
    sc = Scorecard(job_id="B8", verdict=res.job_verdict, attribution=res.attribution,
                   evidence={"oracle_status": oracle})
    checked = bat.cross_check(sc, card)
    assert checked.verdict == "PARKED-HONEST" and checked.attribution == "BUILD"
