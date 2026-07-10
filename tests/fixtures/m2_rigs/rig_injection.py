"""B8 negative-carrier rig injection (W9, plan §9.3/§9.4) — TEST-ONLY.

Fires the N1-N3 negative controls INSIDE a real swap-driver run via the
``shared.fleet.plan_graph.simulate_job_plan`` seam (GPU-free, model-free,
milliseconds), so B8 — "a B1 clone carrying the N1-N3 rigs" — becomes a
rig-carrying battery job whose REAL gates catch the sabotage and the honest
outcome is PARKED-HONEST (a real caught negative), never GREEN.

The standalone live proof
(``phase2_gates/evidence/m2_live_negatives_n1n2n3_2026-07-06.json``) proved each
rig against real sandbox repos STANDALONE. This fixture makes the same three
negatives fire through the SAME driver decision loop + the SAME nets a real B8
dispatch runs — but with the fleet/gates/oracle injected as fakes (no GPU, no
model, no OVMS):

  * **N1** — a renamed contract export → the WAVE INTEGRATION gate on the merged
    tree goes RED → the dependent subtree is ``skipped`` → PARKED-HONEST (BUILD).
  * **N2** — an overfit patch that passes its OWN unit tests but violates a
    JOB-oracle criterion → the job oracle FAILS on the integrated tree →
    PARKED-HONEST (BUILD); unit-green distinguished from job-red.
  * **N3** — a task edits the protected oracle file → the REAL restore-before-grade
    (``swap_ops.real_run_job_oracle``) overwrites the tamper with the PLAN bytes
    BEFORE grading, so the ORIGINAL oracle runs and the tree is restored exactly
    → the tamper can never manufacture a pass → PARKED-HONEST (BUILD).

This is a TEST FIXTURE: it is never imported by runtime/dispatch code, and the
``simulate_job_plan`` seam it drives is byte-identical to today for any non-rig
job (``rigs`` / ``rig_oracle`` default to None).
"""

from __future__ import annotations

import json
import tempfile
from dataclasses import dataclass
from pathlib import Path
from unittest import mock

# The gold-b1 plan is the "B1 clone" B8 carries (evals/battery/gold/gold-b1.json).
_GOLD_B1 = Path(__file__).resolve().parents[3] / "evals" / "battery" / "gold" / "gold-b1.json"

#: The distinctive marker only the ORIGINAL (plan-carried) N3 oracle carries — its
#: presence in the graded bytes proves the plan bytes won the restore-before-grade.
_N3_REAL_MARKER = "N3_REAL_ORACLE_CRITERION"


def load_b8_carrier_plan() -> dict:
    """B8's carrier plan: the gold-b1 three-task chain (storage -> add -> list) with a
    B8 plan id. ``simulate_job_plan`` rewrites the repo to its sandbox and re-validates
    (no hash check), so the clone drives the real wave loop without a separate gold-b8
    artifact — exactly the card's "a B1 clone carrying the N1-N3 rigs"."""
    plan = json.loads(_GOLD_B1.read_text(encoding="utf-8"))
    plan["plan_id"] = "gold-b8-negative-carrier"
    return plan


def _all_merged_run_task():
    """A scripted fleet fake where EVERY task returns MERGED — unit-green: each part
    passes its OWN per-task gate (the sabotage only shows at the wave/job level)."""
    from shared.fleet.dispatch import TaskOutcome

    def run_task(task: dict) -> TaskOutcome:
        tid = str(task.get("task") or task.get("id") or "")
        return TaskOutcome(task=tid, outcome="processed", result="MERGED",
                           detail=f"RESULT: MERGED (rig unit-green; {tid})")

    return run_task


def _no_split_generate_fn():
    """A scripted 14B that never proposes a re-decompose (the rigs do not exercise W5)."""

    def generate_fn(_prompt: str) -> str:
        return ""

    return generate_fn


def build_n3_restore_before_grade_oracle():
    """Build the N3 job-oracle seam that fires through the REAL restore-before-grade
    (``swap_ops.real_run_job_oracle``), plus a ``capture`` dict the caller asserts on.

    The closure, per call: plants a TAMPERED (neutered-to-pass) oracle on disk at the
    pinned oracle path, hands ``real_run_job_oracle`` the ORIGINAL plan bytes, and
    grades via an injected runner that reads the file AT GRADE TIME — so the graded
    bytes prove which oracle actually ran. ``real_run_job_oracle`` writes the plan
    bytes over the tamper BEFORE grading and restores the prior (tampered) bytes after,
    so ``capture`` records: ``graded_bytes`` (must carry the real marker — the plan
    bytes won), ``on_disk_after`` (must equal the tamper — the tree was restored), the
    audit copy, and the graded status (``failed`` — the real criterion the overfit
    violates). ``shutil.which`` is patched so the ``.py`` grader path is taken with no
    ``uv`` installed — the injected runner replaces the subprocess, so nothing runs."""
    from shared.fleet import swap_ops
    from shared.fleet.acceptance import JOB_ORACLE_PATH_PYTHON
    from shared.fleet.dispatch import FleetDispatchConfig

    original = (
        "# original job oracle: asserts the REAL criterion the overfit patch violates\n"
        f"def test_job_criterion():  # {_N3_REAL_MARKER}\n"
        "    raise AssertionError('the overfit implementation fails the real criterion')\n"
    )
    tampered = (
        "# TAMPERED by a merged task: neutered to pass trivially (a FALSE-DONE attempt)\n"
        "def test_job_criterion():\n"
        "    assert True  # tamper: always green\n"
    )
    capture: dict = {"marker": _N3_REAL_MARKER, "original": original, "tampered": tampered}

    def _grade_by_on_disk_content(cmd, timeout_s, cwd=None):
        # Stands in for `uv run pytest <oracle>`; reads the oracle file AT GRADE TIME.
        graded = (Path(cwd) / JOB_ORACLE_PATH_PYTHON).read_text(encoding="utf-8")
        capture["graded_bytes"] = graded
        # The ORIGINAL oracle asserts the criterion the overfit violates -> nonzero exit
        # (ok=False). A surviving tamper (neutered file, no marker) would PASS (ok=True) —
        # exactly the FALSE-DONE that restore-before-grade prevents.
        ok = _N3_REAL_MARKER not in graded
        return (ok, "pytest graded the on-disk oracle", "")

    def oracle_fn(_repo: str, rel_path: str) -> dict:
        rel = rel_path if rel_path == JOB_ORACLE_PATH_PYTHON else JOB_ORACLE_PATH_PYTHON
        repo_root = Path(tempfile.mkdtemp(prefix="n3-rig-repo-"))
        (repo_root / ".git").mkdir(parents=True, exist_ok=True)
        target = repo_root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(tampered, encoding="utf-8")   # a merged task tampered the oracle
        cfg_root = Path(tempfile.mkdtemp(prefix="n3-rig-cfg-"))
        config = FleetDispatchConfig(
            scripts_dir=cfg_root / "scripts",
            queue_path=cfg_root / "state" / "q.json",
            runs_dir=cfg_root / "state" / "runs",
            projects_dir=cfg_root / "projects",
        )
        with mock.patch.object(swap_ops.shutil, "which",
                               side_effect=lambda name: "uv" if name == "uv" else None):
            res = swap_ops.real_run_job_oracle(
                config, "n3", str(repo_root), rel, original,
                run=_grade_by_on_disk_content)
        capture["repo"] = str(repo_root)
        capture["rel"] = rel
        capture["on_disk_after"] = target.read_text(encoding="utf-8")
        audit = config.runs_dir / "n3" / f"job-oracle-{Path(rel).name}"
        capture["audit_copy"] = audit.read_text(encoding="utf-8") if audit.is_file() else ""
        capture["result"] = dict(res)
        return res

    return oracle_fn, capture


@dataclass
class RigRun:
    """One rig-injected simulator run: the driver result + (for N3) the restore capture."""

    result: object                    # shared.fleet.plan_graph.JobPlanSimResult
    n3_capture: "dict | None" = None


def fire_rig(rig: str, *, plan: "dict | None" = None) -> RigRun:
    """Fire ONE armed rig (``"N1"`` / ``"N2"`` / ``"N3"``) through the real driver via
    ``simulate_job_plan``, returning the honest result (PARKED-HONEST) + capture."""
    from shared.fleet.plan_graph import simulate_job_plan

    rig = str(rig).strip().upper()
    plan = plan if plan is not None else load_b8_carrier_plan()
    kwargs = dict(run_task=_all_merged_run_task(), generate_fn=_no_split_generate_fn(),
                  rigs=[rig])
    n3_capture = None
    if rig == "N3":
        oracle_fn, n3_capture = build_n3_restore_before_grade_oracle()
        kwargs["rig_oracle"] = oracle_fn
    return RigRun(result=simulate_job_plan(plan, **kwargs), n3_capture=n3_capture)


def fire_all_rigs(*, plan: "dict | None" = None) -> RigRun:
    """Fire the full B8 carrier (all three negatives armed at once) through the real
    driver. In the linear B1 chain N1's wave gate fires first and short-circuits, so
    the honest verdict is PARKED-HONEST (the earliest net wins) — never GREEN."""
    from shared.fleet.plan_graph import simulate_job_plan

    plan = plan if plan is not None else load_b8_carrier_plan()
    oracle_fn, n3_capture = build_n3_restore_before_grade_oracle()
    result = simulate_job_plan(
        plan, run_task=_all_merged_run_task(), generate_fn=_no_split_generate_fn(),
        rigs=["N1", "N2", "N3"], rig_oracle=oracle_fn)
    return RigRun(result=result, n3_capture=n3_capture)
