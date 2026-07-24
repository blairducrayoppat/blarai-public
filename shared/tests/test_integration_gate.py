"""M2 W4 (#740) — integration-verification tests: the per-wave gate on the integrated
main, the JOB-level spec-blind oracle (python + node), evidence-gated statuses, the
verdict computation, and the scorecard emission.

Every external effect rides the injected SwapOps seams, so the whole wave loop runs
model-free and GPU-free here (the plan §4.3 seam requirement is exactly what makes
these tests possible — and any effect that bypassed the seam would be untestable and
rejected)."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from shared.fleet import plan_graph as pg
from shared.fleet import swap_driver as sd
from shared.fleet import swap_ops as so
from shared.fleet.acceptance import (
    JOB_ORACLE_CODE_KEY,
    JOB_ORACLE_PATH_KEY,
    JOB_ORACLE_PATH_NODE,
    JOB_ORACLE_PATH_PYTHON,
    AcceptanceCriterion,
    AcceptanceSpec,
    extract_job_oracle,
    generate_job_acceptance_oracle,
    generate_plan,
)
from shared.fleet.context_pack import PACK_INSTRUCTION
from shared.fleet.dispatch import FleetDispatchConfig, TaskOutcome

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


def _mk_repo(tmp_path: Path, name: str = "proj") -> Path:
    repo = tmp_path / name
    (repo / ".git").mkdir(parents=True, exist_ok=True)
    return repo


def _plan_tasks(repo: Path) -> list[dict]:
    """A 3-node chain + one independent root: storage <- report; util independent."""
    return [
        {"repo": str(repo), "task": "storage", "prompt": "build storage",
         "depends_on": [],
         "contract": {"creates": ["src/storage.py"], "exports": ["save(x)"],
                      "notes": "rows are dicts"}},
        {"repo": str(repo), "task": "report", "prompt": "build report",
         "depends_on": ["storage"]},
        {"repo": str(repo), "task": "util", "prompt": "build util", "depends_on": []},
    ]


def _build_plan(tmp_path: Path, tasks: list[dict], *, run_id: str = "R1") -> pg.JobPlan:
    raw = pg.build_plan_raw(
        plan_id=run_id, goal="a budget tracker", repo=str(tasks[0]["repo"]), tasks=tasks,
        criteria=["adds expenses", "lists by month"],
    )
    result = pg.validate_plan(raw, projects_dir=tmp_path)
    assert result.ok and result.plan is not None
    return result.plan


def _merged(task):
    return TaskOutcome(task=task["task"], outcome="processed", result="MERGED",
                       detail="RESULT: MERGED to main")


def _ops(calls, **overrides):
    base = dict(
        available_gb=lambda: 26.0,
        backend_alive=lambda: False,
        load_30b=lambda: (calls.append("load"), True)[1],
        wait_ready=lambda: True,
        run_task=lambda t: (calls.append(("task", t["task"], t["prompt"])), _merged(t))[1],
        cancel_requested=lambda: False,
        disarm_watchdog=lambda: calls.append("disarm"),
        stop_ovms=lambda: calls.append("stop"),
        write_report=lambda rid, outs: calls.append(("report", rid, len(outs))),
        restart_launcher=lambda: calls.append("restart"),
        backend_ready=lambda: True,
        signal_failure=lambda msg: calls.append(("signal", msg)),
        run_wave_gate=lambda repo: (calls.append(("wave_gate", repo)),
                                    {"ok": True, "evidence": "verify=pass; tests=pass"})[1],
        run_job_oracle=lambda repo, rel: (calls.append(("job_oracle", repo, rel)),
                                          {"status": "passed", "evidence": "exit 0"})[1],
        write_scorecard=lambda sc: calls.append(("scorecard", sc)),
        write_job_summary=lambda text: calls.append(("job_summary", text)),
        log_pack=lambda tid, pack: calls.append(("pack", tid, pack)),
    )
    base.update(overrides)
    return sd.SwapOps(**base)


def _driver(tmp_path, ops, tasks, plan, **kw):
    store = pg.PlanStore(tmp_path / "plan.json", projects_dir=tmp_path)
    return sd.SwapDriver(
        run_id="R1", session_id="s1", tasks=tasks,
        swap_state_path=tmp_path / "swap.json", ops=ops,
        gate_gb=21.0, sleep=lambda _s: None,
        plan=store.write(plan), plan_store=store, **kw,
    )


def _scorecard(calls) -> dict:
    for c in calls:
        if isinstance(c, tuple) and c[0] == "scorecard":
            return c[1]
    raise AssertionError("no scorecard emitted")


# ---------------------------------------------------------------------------
# Wave scheduling + evidence-gated statuses
# ---------------------------------------------------------------------------


def test_waves_run_in_dependency_order_and_all_merge(tmp_path):
    repo = _mk_repo(tmp_path)
    tasks = _plan_tasks(repo)
    plan = _build_plan(tmp_path, tasks)
    calls = []
    result = _driver(tmp_path, _ops(calls), tasks, plan).run()
    ran = [c[1] for c in calls if isinstance(c, tuple) and c[0] == "task"]
    # wave 1: storage + util (roots, original order); wave 2: report.
    assert ran == ["storage", "util", "report"]
    assert result.outcome == "complete"
    sc = _scorecard(calls)
    assert {t["id"]: t["status"] for t in sc["tasks"]} == {
        "storage": "merged", "util": "merged", "report": "merged"}


def test_wave_gate_runs_after_each_merging_wave(tmp_path):
    repo = _mk_repo(tmp_path)
    tasks = _plan_tasks(repo)
    plan = _build_plan(tmp_path, tasks)
    calls = []
    _driver(tmp_path, _ops(calls), tasks, plan).run()
    gates = [c for c in calls if isinstance(c, tuple) and c[0] == "wave_gate"]
    assert len(gates) == 2  # two waves, both merged something
    sc = _scorecard(calls)
    assert [w["status"] for w in sc["waves"]] == ["passed", "passed"]


def test_diamond_plan_wave_grouping(tmp_path):
    repo = _mk_repo(tmp_path)
    tasks = [
        {"repo": str(repo), "task": "a", "prompt": "pa", "depends_on": []},
        {"repo": str(repo), "task": "b", "prompt": "pb", "depends_on": ["a"]},
        {"repo": str(repo), "task": "c", "prompt": "pc", "depends_on": ["a"]},
        {"repo": str(repo), "task": "d", "prompt": "pd", "depends_on": ["b", "c"]},
    ]
    plan = _build_plan(tmp_path, tasks)
    calls = []
    _driver(tmp_path, _ops(calls), tasks, plan).run()
    ran = [c[1] for c in calls if isinstance(c, tuple) and c[0] == "task"]
    assert ran == ["a", "b", "c", "d"]
    gates = [c for c in calls if isinstance(c, tuple) and c[0] == "wave_gate"]
    assert len(gates) == 3


def test_statuses_persisted_and_hash_repinned(tmp_path):
    repo = _mk_repo(tmp_path)
    tasks = _plan_tasks(repo)
    plan = _build_plan(tmp_path, tasks)
    calls = []
    _driver(tmp_path, _ops(calls), tasks, plan).run()
    persisted = json.loads((tmp_path / "plan.json").read_text(encoding="utf-8"))
    assert all(t["status"] == "merged" for t in persisted["tasks"])
    assert persisted["job_acceptance"]["status"] == "passed"
    # Seam note (b): the swap-state pin follows the LAST persist's hash.
    swap = json.loads((tmp_path / "swap.json").read_text(encoding="utf-8"))
    assert swap["plan_hash"] == persisted["plan_hash"]
    # And the persisted artifact re-loads clean through the hash-verifying store.
    loaded = pg.PlanStore(tmp_path / "plan.json", projects_dir=tmp_path).load()
    assert loaded.ok


# ---------------------------------------------------------------------------
# W3 wiring: context packs at enqueue
# ---------------------------------------------------------------------------


def test_dependent_task_prompt_carries_context_pack(tmp_path):
    repo = _mk_repo(tmp_path)
    tasks = _plan_tasks(repo)
    plan = _build_plan(tmp_path, tasks)
    calls = []
    heads = iter([f"{i:040x}" for i in range(1, 10)])
    ops = _ops(
        calls,
        repo_head=lambda _r: next(heads, ""),
        dep_delta=lambda _r, _b, _m: {"files": ["src/storage.py"],
                                      "signatures": ["def save(x)"]},
    )
    _driver(tmp_path, ops, tasks, plan).run()
    prompts = {c[1]: c[2] for c in calls if isinstance(c, tuple) and c[0] == "task"}
    # Roots get NO pack — no header, no instruction line. (They DO get the #989
    # scope ceiling, which is contract-derived, not dependency-derived.)
    assert prompts["storage"].startswith("build storage")
    assert prompts["util"].startswith("build util")
    assert PACK_INSTRUCTION not in prompts["storage"]
    assert PACK_INSTRUCTION not in prompts["util"]
    # The dependent gets contract + as-built + the instruction, appended.
    assert prompts["report"].startswith("build report\n\n")
    assert "creates src/storage.py" in prompts["report"]
    assert PACK_INSTRUCTION in prompts["report"]
    # The pack is logged VERBATIM.
    packs = [c for c in calls if isinstance(c, tuple) and c[0] == "pack"]
    assert len(packs) == 1 and packs[0][1] == "report"
    assert packs[0][2] in prompts["report"]
    sc = _scorecard(calls)
    assert sc["packs_consumed"] == 1


def test_pack_uses_recorded_merge_refs_for_dep_delta(tmp_path):
    repo = _mk_repo(tmp_path)
    tasks = _plan_tasks(repo)
    plan = _build_plan(tmp_path, tasks)
    calls = []
    heads = iter(["base1", "merge1", "base2", "merge2", "base3", "merge3"])
    deltas = []

    def dep_delta(r, base, merge):
        deltas.append((base, merge))
        return {"files": [], "signatures": []}

    ops = _ops(calls, repo_head=lambda _r: next(heads, ""), dep_delta=dep_delta)
    _driver(tmp_path, ops, tasks, plan).run()
    # The EXACT deterministic read sequence (single-threaded wave loop, stable
    # order): the #989 sprawl recorder reads each merged task's OWN refs right
    # after its merge (storage, then util), the PACK for report reads its
    # DEPENDENCY storage's recorded refs — (base1, merge1) AGAIN, the load-bearing
    # pin: a wrong-task lookup in _build_pack would surface here as a different
    # pair (a membership/subset form provably could not catch that — review of
    # e56138a0, F1) — and the sprawl recorder then reads report's own refs.
    assert deltas == [
        ("base1", "merge1"),   # sprawl read: storage's own merge
        ("base2", "merge2"),   # sprawl read: util's own merge
        ("base1", "merge1"),   # PACK for report: bracketed by DEP storage's refs
        ("base3", "merge3"),   # sprawl read: report's own merge
    ]


def test_pack_degrades_to_contract_only_without_repo_head(tmp_path):
    repo = _mk_repo(tmp_path)
    tasks = _plan_tasks(repo)
    plan = _build_plan(tmp_path, tasks)
    calls = []
    _driver(tmp_path, _ops(calls), tasks, plan).run()  # default repo_head='' / delta={}
    prompts = {c[1]: c[2] for c in calls if isinstance(c, tuple) and c[0] == "task"}
    assert "creates src/storage.py" in prompts["report"]
    assert "as-built" not in prompts["report"]


# ---------------------------------------------------------------------------
# W4: the wave gate short-circuit + honesty
# ---------------------------------------------------------------------------


def test_wave_gate_failure_short_circuits_and_skips_pending(tmp_path):
    repo = _mk_repo(tmp_path)
    tasks = _plan_tasks(repo)
    plan = _build_plan(tmp_path, tasks)
    calls = []
    ops = _ops(calls, run_wave_gate=lambda repo: {"ok": False, "evidence": "tests=fail"})
    _driver(tmp_path, ops, tasks, plan).run()
    ran = [c[1] for c in calls if isinstance(c, tuple) and c[0] == "task"]
    assert ran == ["storage", "util"]           # wave 2 never ran
    sc = _scorecard(calls)
    statuses = {t["id"]: t["status"] for t in sc["tasks"]}
    assert statuses["report"] == "skipped"      # N1: the dependent subtree skipped
    assert sc["waves"][0]["status"] == "failed"
    assert sc["job_acceptance"]["status"] == "not-run"   # never graded on a broken base
    assert sc["verdict"] == "PARKED-HONEST"
    assert sc["attribution"] == "BUILD"
    oracle_calls = [c for c in calls if isinstance(c, tuple) and c[0] == "job_oracle"]
    assert oracle_calls == []


def test_wave_gate_unavailable_is_recorded_not_run_and_never_blocks(tmp_path):
    repo = _mk_repo(tmp_path)
    tasks = _plan_tasks(repo)
    plan = _build_plan(tmp_path, tasks)
    calls = []
    ops = _ops(calls, run_wave_gate=sd._noop_wave_gate)
    _driver(tmp_path, ops, tasks, plan).run()
    ran = [c[1] for c in calls if isinstance(c, tuple) and c[0] == "task"]
    assert ran == ["storage", "util", "report"]  # never blocked
    sc = _scorecard(calls)
    assert all(w["status"] == "not-run" for w in sc["waves"])  # honest, not passed
    assert sc["job_acceptance"]["status"] == "passed"


def test_wave_gate_exception_is_could_not_run(tmp_path):
    repo = _mk_repo(tmp_path)
    tasks = _plan_tasks(repo)
    plan = _build_plan(tmp_path, tasks)
    calls = []

    def boom(_repo):
        raise OSError("gate machinery down")

    ops = _ops(calls, run_wave_gate=boom)
    result = _driver(tmp_path, ops, tasks, plan).run()
    assert result.outcome == "complete"
    sc = _scorecard(calls)
    assert all(w["status"] == "not-run" for w in sc["waves"])


# ---------------------------------------------------------------------------
# W4: the job oracle is the finish line
# ---------------------------------------------------------------------------


def test_job_oracle_failure_means_job_not_done(tmp_path):
    repo = _mk_repo(tmp_path)
    tasks = _plan_tasks(repo)
    plan = _build_plan(tmp_path, tasks)
    calls = []
    ops = _ops(calls, run_job_oracle=lambda r, p: {"status": "failed",
                                                   "evidence": "2 failed"})
    _driver(tmp_path, ops, tasks, plan).run()
    sc = _scorecard(calls)
    assert sc["job_acceptance"]["status"] == "failed"
    assert sc["verdict"] == "PARKED-HONEST" and sc["attribution"] == "BUILD"


def test_job_oracle_unavailable_is_not_run_never_green(tmp_path):
    """Merged-but-unverifiable is exactly the FALSE-DONE class — the honest verdict
    is STALLED (could not be scored), attributed VERIFY (the oracle was missing,
    not the build). Lane V's scenario 'job-oracle-unrun-is-not-green' pins this."""
    repo = _mk_repo(tmp_path)
    tasks = _plan_tasks(repo)
    plan = _build_plan(tmp_path, tasks)
    calls = []
    ops = _ops(calls, run_job_oracle=sd._noop_job_oracle)
    _driver(tmp_path, ops, tasks, plan).run()
    sc = _scorecard(calls)
    assert sc["job_acceptance"]["status"] == "not-run"
    assert sc["evidence"]["oracle_status"] == "not-run"
    assert sc["verdict"] == "STALLED" and sc["attribution"] == "VERIFY"


def test_job_oracle_not_graded_when_nothing_merged(tmp_path):
    repo = _mk_repo(tmp_path)
    tasks = _plan_tasks(repo)
    plan = _build_plan(tmp_path, tasks)
    calls = []
    parked = lambda t: TaskOutcome(task=t["task"], outcome="errored", result="PARKED",
                                   detail="RESULT: NOT merged")
    ops = _ops(calls, run_task=lambda t: (calls.append(("task", t["task"], t["prompt"])),
                                          parked(t))[1])
    _driver(tmp_path, ops, tasks, plan).run()
    sc = _scorecard(calls)
    assert sc["job_acceptance"]["status"] == "not-run"
    assert "nothing merged" in sc["job_acceptance"]["evidence"]


def test_oracle_path_comes_from_plan(tmp_path):
    repo = _mk_repo(tmp_path)
    tasks = _plan_tasks(repo)
    raw = pg.build_plan_raw(plan_id="R1", goal="g", repo=str(repo), tasks=tasks,
                            oracle_path=JOB_ORACLE_PATH_NODE)
    plan = pg.validate_plan(raw, projects_dir=tmp_path).plan
    calls = []
    _driver(tmp_path, _ops(calls), tasks, plan).run()
    oracle_calls = [c for c in calls if isinstance(c, tuple) and c[0] == "job_oracle"]
    assert oracle_calls and oracle_calls[0][2] == JOB_ORACLE_PATH_NODE


# ---------------------------------------------------------------------------
# #822 layout gate: import-contract enforcement on the final integrated tree
# ---------------------------------------------------------------------------


def _layout_tasks(repo: Path) -> list[dict]:
    """2-task chain: core (wave 1) then cli (wave 2) — the cli task's contract CREATES
    cli_interface, so an unresolved `cli_interface` import maps to it (the fix target)."""
    return [
        {"repo": str(repo), "task": "core", "prompt": "build core", "depends_on": [],
         "contract": {"creates": ["core.py"], "exports": ["helper()"]}},
        {"repo": str(repo), "task": "cli", "prompt": "build cli", "depends_on": ["core"],
         "contract": {"creates": ["cli_interface.py"], "exports": ["run_cli()"]}},
    ]


_LAYOUT_CONTRACT = ["from cli_interface import run_cli"]
_UNRESOLVED = [{"raw": "from cli_interface import run_cli", "module": "cli_interface",
                "reason": "module 'cli_interface' does not resolve from the repo root"}]


def test_layout_gate_noop_seam_is_byte_identical(tmp_path):
    """The default (noop) probe seam returns ok=None → inert: the job grades + completes
    exactly as before the feature, even with a contract present (byte-identical)."""
    repo = _mk_repo(tmp_path)
    tasks = _layout_tasks(repo)
    plan = _build_plan(tmp_path, tasks)
    calls = []
    ops = _ops(calls, job_oracle_contract=lambda: _LAYOUT_CONTRACT)  # noop probe default
    result = _driver(tmp_path, ops, tasks, plan).run()
    sc = _scorecard(calls)
    assert sc["job_acceptance"]["status"] == "passed"
    assert result.outcome == "complete"
    assert not any(w["status"] == "failed" for w in sc["waves"])


def test_layout_gate_pass_lets_job_grade(tmp_path):
    repo = _mk_repo(tmp_path)
    tasks = _layout_tasks(repo)
    plan = _build_plan(tmp_path, tasks)
    calls = []
    ops = _ops(calls, job_oracle_contract=lambda: _LAYOUT_CONTRACT,
               run_import_probe=lambda r, p: {"ok": True, "unresolved": [],
                                              "evidence": "all resolved"})
    _driver(tmp_path, ops, tasks, plan).run()
    sc = _scorecard(calls)
    assert sc["job_acceptance"]["status"] == "passed"
    assert [c for c in calls if isinstance(c, tuple) and c[0] == "job_oracle"]  # graded


def test_layout_gate_unresolved_after_fix_cycle_parks_honest(tmp_path):
    """Probe fails, the fix cycle re-runs the offending task but it STILL fails → a
    FAILED integration gate → PARKED-HONEST [BUILD]; the oracle never grades and the
    exact unresolved entry is NAMED (the B6n2 shape, pre-empted before the oracle)."""
    repo = _mk_repo(tmp_path)
    tasks = _layout_tasks(repo)
    plan = _build_plan(tmp_path, tasks)
    calls = []
    ops = _ops(calls, job_oracle_contract=lambda: _LAYOUT_CONTRACT,
               run_import_probe=lambda r, p: {"ok": False, "unresolved": _UNRESOLVED,
                                              "evidence": "unresolved"})
    _driver(tmp_path, ops, tasks, plan).run()
    sc = _scorecard(calls)
    assert sc["verdict"] == "PARKED-HONEST" and sc["attribution"] == "BUILD"
    assert sc["job_acceptance"]["status"] == "not-run"  # never graded on an unmet contract
    assert [c for c in calls if isinstance(c, tuple) and c[0] == "job_oracle"] == []
    assert any(w["status"] == "failed" for w in sc["waves"])
    # the ONE fix cycle re-ran the OFFENDING task (cli — its contract creates cli_interface)
    fix_prompts = [c[2] for c in calls
                   if isinstance(c, tuple) and c[0] == "task" and c[1] == "cli"
                   and "LAYOUT FIX" in c[2]]
    assert fix_prompts and "cli_interface" in fix_prompts[0]


def test_layout_gate_fix_cycle_resolves_then_grades(tmp_path):
    """Probe fails once; the fix cycle re-runs the offending task (MERGED); the re-probe
    RESOLVES → the job grades normally, no failed gate."""
    repo = _mk_repo(tmp_path)
    tasks = _layout_tasks(repo)
    plan = _build_plan(tmp_path, tasks)
    calls = []
    seq = iter([{"ok": False, "unresolved": _UNRESOLVED, "evidence": "x"},
                {"ok": True, "unresolved": [], "evidence": "resolved"}])
    ops = _ops(calls, job_oracle_contract=lambda: _LAYOUT_CONTRACT,
               run_import_probe=lambda r, p: next(seq))
    _driver(tmp_path, ops, tasks, plan).run()
    sc = _scorecard(calls)
    assert sc["job_acceptance"]["status"] == "passed"
    assert not any(w["status"] == "failed" for w in sc["waves"])
    fix_runs = [c for c in calls if isinstance(c, tuple) and c[0] == "task"
                and c[1] == "cli" and "LAYOUT FIX" in c[2]]
    assert len(fix_runs) == 1


def test_layout_gate_fix_budget_is_one(tmp_path):
    """The fix cycle runs at most ONCE per job even if the probe keeps failing (initial
    probe + exactly one re-probe after the single fix cycle)."""
    repo = _mk_repo(tmp_path)
    tasks = _layout_tasks(repo)
    plan = _build_plan(tmp_path, tasks)
    calls = []
    probes: list[int] = []

    def probe(_r, _p):
        probes.append(1)
        return {"ok": False, "unresolved": _UNRESOLVED, "evidence": "x"}

    ops = _ops(calls, job_oracle_contract=lambda: _LAYOUT_CONTRACT, run_import_probe=probe)
    _driver(tmp_path, ops, tasks, plan).run()
    assert len(probes) == 2  # initial + one re-probe; the fix budget caps at 1
    fix_runs = [c for c in calls if isinstance(c, tuple) and c[0] == "task"
                and c[1] == "cli" and "LAYOUT FIX" in c[2]]
    assert len(fix_runs) == 1


def test_layout_gate_could_not_run_is_non_blocking(tmp_path):
    """A probe that could not run (ok=None) is honest + non-blocking — the job grades."""
    repo = _mk_repo(tmp_path)
    tasks = _layout_tasks(repo)
    plan = _build_plan(tmp_path, tasks)
    calls = []
    ops = _ops(calls, job_oracle_contract=lambda: _LAYOUT_CONTRACT,
               run_import_probe=lambda r, p: {"ok": None, "unresolved": [],
                                              "evidence": "uv unavailable"})
    _driver(tmp_path, ops, tasks, plan).run()
    sc = _scorecard(calls)
    assert sc["job_acceptance"]["status"] == "passed"


# ---------------------------------------------------------------------------
# #830 G6 executability floor (driver wiring — sibling of the layout gate)
# ---------------------------------------------------------------------------

#: A node boot failure whose unresolved module (cli_interface) maps to the `cli` task in
#: _layout_tasks (its contract creates cli_interface) — the fix target.
_EXEC_BOOT_FAIL = {
    "ok": False, "language": "node",
    "evidence": "booting node main.js failed: ERR_MODULE_NOT_FOUND cli_interface",
    "fingerprint": "ERR_MODULE_NOT_FOUND:cli_interface",
    "unresolved": [{"module": "cli_interface", "raw": "node main.js --help",
                    "reason": "Cannot find module cli_interface"}],
}


def test_exec_smoke_noop_seam_is_byte_identical(tmp_path):
    """The default (noop) smoke seam returns ok=None → inert: the job grades + completes
    exactly as before the feature (byte-identical)."""
    repo = _mk_repo(tmp_path)
    tasks = _layout_tasks(repo)
    plan = _build_plan(tmp_path, tasks)
    calls = []
    result = _driver(tmp_path, _ops(calls), tasks, plan).run()
    sc = _scorecard(calls)
    assert sc["job_acceptance"]["status"] == "passed"
    assert result.outcome == "complete"


def test_exec_smoke_pass_lets_job_grade(tmp_path):
    repo = _mk_repo(tmp_path)
    tasks = _layout_tasks(repo)
    plan = _build_plan(tmp_path, tasks)
    calls = []
    ops = _ops(calls, run_exec_smoke=lambda r, p: (
        calls.append(("exec_smoke", r, p)),
        {"ok": True, "language": "python", "evidence": "main.py imports and starts",
         "fingerprint": "", "unresolved": []})[1])
    _driver(tmp_path, ops, tasks, plan).run()
    sc = _scorecard(calls)
    assert sc["job_acceptance"]["status"] == "passed"
    assert [c for c in calls if isinstance(c, tuple) and c[0] == "exec_smoke"]  # ran
    assert [c for c in calls if isinstance(c, tuple) and c[0] == "job_oracle"]  # graded


def test_exec_smoke_boot_fail_after_fix_cycle_parks_honest(tmp_path):
    """Boot fails, the fix cycle re-runs the boot-error-owning task but it STILL fails to
    boot → a FAILED integration gate → PARKED-HONEST [BUILD]; the oracle never grades and
    the boot error is NAMED verbatim in the fix prompt (the B7 shape pre-empted before the
    oracle)."""
    repo = _mk_repo(tmp_path)
    tasks = _layout_tasks(repo)
    plan = _build_plan(tmp_path, tasks)
    calls = []
    ops = _ops(calls, run_exec_smoke=lambda r, p: dict(_EXEC_BOOT_FAIL))
    _driver(tmp_path, ops, tasks, plan).run()
    sc = _scorecard(calls)
    assert sc["verdict"] == "PARKED-HONEST" and sc["attribution"] == "BUILD"
    assert sc["job_acceptance"]["status"] == "not-run"  # never graded on a non-booting app
    assert [c for c in calls if isinstance(c, tuple) and c[0] == "job_oracle"] == []
    assert any(w["status"] == "failed" for w in sc["waves"])
    fix_prompts = [c[2] for c in calls
                   if isinstance(c, tuple) and c[0] == "task" and c[1] == "cli"
                   and "EXECUTABILITY FIX" in c[2]]
    assert fix_prompts and "ERR_MODULE_NOT_FOUND" in fix_prompts[0]


def test_exec_smoke_fix_cycle_resolves_then_grades(tmp_path):
    """Boot fails once; the fix cycle re-runs the owning task (MERGED); the re-smoke BOOTS
    → the job grades normally, no failed gate."""
    repo = _mk_repo(tmp_path)
    tasks = _layout_tasks(repo)
    plan = _build_plan(tmp_path, tasks)
    calls = []
    seq = iter([dict(_EXEC_BOOT_FAIL),
                {"ok": True, "language": "node", "evidence": "boots", "fingerprint": "",
                 "unresolved": []}])
    ops = _ops(calls, run_exec_smoke=lambda r, p: next(seq))
    _driver(tmp_path, ops, tasks, plan).run()
    sc = _scorecard(calls)
    assert sc["job_acceptance"]["status"] == "passed"
    assert not any(w["status"] == "failed" for w in sc["waves"])
    fix_runs = [c for c in calls if isinstance(c, tuple) and c[0] == "task"
                and c[1] == "cli" and "EXECUTABILITY FIX" in c[2]]
    assert len(fix_runs) == 1


def test_exec_smoke_fix_budget_is_one(tmp_path):
    """The boot fix cycle runs at most ONCE per job even if the smoke keeps failing (initial
    smoke + exactly one re-smoke after the single fix cycle)."""
    repo = _mk_repo(tmp_path)
    tasks = _layout_tasks(repo)
    plan = _build_plan(tmp_path, tasks)
    calls = []
    smokes: list[int] = []

    def smoke(_r, _p):
        smokes.append(1)
        return dict(_EXEC_BOOT_FAIL)

    ops = _ops(calls, run_exec_smoke=smoke)
    _driver(tmp_path, ops, tasks, plan).run()
    assert len(smokes) == 2  # initial + one re-smoke; the fix budget caps at 1
    fix_runs = [c for c in calls if isinstance(c, tuple) and c[0] == "task"
                and c[1] == "cli" and "EXECUTABILITY FIX" in c[2]]
    assert len(fix_runs) == 1


def test_exec_smoke_could_not_run_is_non_blocking(tmp_path):
    """A smoke that could not run (ok=None) is honest + non-blocking — the job grades (the
    python/green path is unchanged when no floor applies)."""
    repo = _mk_repo(tmp_path)
    tasks = _layout_tasks(repo)
    plan = _build_plan(tmp_path, tasks)
    calls = []
    ops = _ops(calls, run_exec_smoke=lambda r, p: {
        "ok": None, "language": "python", "evidence": "uv unavailable",
        "fingerprint": "", "unresolved": []})
    _driver(tmp_path, ops, tasks, plan).run()
    sc = _scorecard(calls)
    assert sc["job_acceptance"]["status"] == "passed"


def test_exec_smoke_skipped_when_layout_gate_already_failed(tmp_path):
    """Ordering lock: the exec floor runs AFTER the layout gate — when the layout gate has
    already failed the wave, the exec smoke seam is never even consulted (and the oracle
    stays not-run). Runs BEFORE the oracle: the two tests above prove the oracle skips on a
    boot fail."""
    repo = _mk_repo(tmp_path)
    tasks = _layout_tasks(repo)
    plan = _build_plan(tmp_path, tasks)
    calls = []
    ops = _ops(
        calls,
        job_oracle_contract=lambda: _LAYOUT_CONTRACT,
        run_import_probe=lambda r, p: {"ok": False, "unresolved": _UNRESOLVED,
                                       "evidence": "unresolved"},
        run_exec_smoke=lambda r, p: (calls.append(("exec_smoke", r, p)), {"ok": True})[1])
    _driver(tmp_path, ops, tasks, plan).run()
    sc = _scorecard(calls)
    assert any(w["status"] == "failed" for w in sc["waves"])  # layout failed the wave
    assert [c for c in calls if isinstance(c, tuple) and c[0] == "exec_smoke"] == []
    assert sc["job_acceptance"]["status"] == "not-run"


# ---------------------------------------------------------------------------
# #790 defect #2: the layout / exec-smoke fix cycle must re-run the OWNER of the
# unresolved module (parked or merged), NEVER a merged SIBLING. The pre-#790
# _owning_task scanned ONLY merged tasks and matched by a coarse `app`-substring, so
# it re-ran a sibling right past the parked owner — resolving 0/3 on the 2026-07-12
# battery (B2 re-ran `tokenize`; B7 `password-generator-helper`; B4 `implement-data-
# storage`). These lock the precise owner selection at the pure-helper, white-box
# (_owning_task), and end-to-end (fix-cycle) levels.
# ---------------------------------------------------------------------------


def _b7_tasks(repo: Path) -> list[dict]:
    """The B7 live shape: three INDEPENDENT node helpers (zero dependency edges). The job
    oracle imports convertUnit from ../src/unit-converter-helper.js — owned solely by
    unit-converter-helper."""
    return [
        {"repo": str(repo), "task": "slugify-phrase-helper", "prompt": "build slugify",
         "depends_on": [], "contract": {"creates": ["src/slugify-phrase-helper.js"],
                                        "exports": ["slugify(phrase)"]}},
        {"repo": str(repo), "task": "unit-converter-helper", "prompt": "build converter",
         "depends_on": [], "contract": {"creates": ["src/unit-converter-helper.js"],
                                        "exports": ["convertUnit(value, from, to)"]}},
        {"repo": str(repo), "task": "password-generator-helper", "prompt": "build password",
         "depends_on": [], "contract": {"creates": ["src/password-generator-helper.js"],
                                        "exports": ["generatePassword(length)"]}},
    ]


_B7_CONTRACT = ["import { convertUnit } from '../src/unit-converter-helper.js'"]
_B7_UNRESOLVED = [{
    "raw": "import { convertUnit } from '../src/unit-converter-helper.js'",
    "spec": "../src/unit-converter-helper.js",
    "reason": "specifier '../src/unit-converter-helper.js' does not resolve (ERR_MODULE_NOT_FOUND)",
}]


def _park_owner_merge_siblings(plan, *, owner: str, siblings: list[str], evidence="RESULT: Nothing to merge"):
    """Independent tasks: merge every *sibling*, park the *owner* — the B7/B2 live shape."""
    for tid in siblings:
        plan = pg.mark_ready(plan, tid)
        plan = pg.mark_building(plan, tid)
        plan = pg.mark_merged(plan, tid, "ev")
    return pg.mark_parked(plan, owner, evidence)


# ---- pure helpers: PRECISE module -> owner keys (never the `app`-substring) ----------


def test_module_forms_python_dotted_module_never_bare_package():
    forms = sd._module_forms("app.word_frequencies")
    assert "app/word_frequencies" in forms and "word_frequencies" in forms
    assert "app" not in forms  # the bare token that substring-matched every app/ sibling


def test_module_forms_node_spec_strips_relative_prefix_and_ext():
    assert sd._module_forms("../src/unit-converter-helper.js") == {
        "src/unit-converter-helper", "unit-converter-helper"}


def test_create_forms_owner_matches_but_sibling_does_not():
    keys = sd._module_forms("../src/unit-converter-helper.js")
    assert sd._create_forms("src/unit-converter-helper.js") & keys          # owner
    assert not (sd._create_forms("src/password-generator-helper.js") & keys)  # sibling (old sink[-1])


def test_create_forms_app_package_no_substring_false_match():
    keys = sd._module_forms("app.word_frequencies")
    tok = sd._create_forms("app/tokenize.py") | sd._create_forms("app/__init__.py")
    assert not (tok & keys)                                   # the `app`-substring match is gone
    assert sd._create_forms("app/word_frequencies.py") & keys  # the real owner still matches


def test_create_forms_package_prefix_maps_bare_package_import():
    # B4: `import flashcard_app` (bare package) maps to the task creating a submodule.
    keys = sd._module_forms("flashcard_app")
    assert sd._create_forms("flashcard_app/card_manager.py") & keys


def test_owner_match_keys_carries_named_export_symbol():
    pk, sk = sd._owner_match_keys([{"spec": "../src/x.js", "name": "convertUnit"}])
    assert "convertunit" in sk


# ---- white-box _owning_task: the parked owner beats the merged sibling ----------------


def test_owning_task_selects_parked_owner_over_merged_sibling_b7(tmp_path):
    repo = _mk_repo(tmp_path)
    tasks = _b7_tasks(repo)
    plan = _park_owner_merge_siblings(
        _build_plan(tmp_path, tasks), owner="unit-converter-helper",
        siblings=["slugify-phrase-helper", "password-generator-helper"])
    driver = _driver(tmp_path, _ops([]), tasks, plan)
    target = driver._owning_task(_B7_UNRESOLVED)
    assert target is not None and target.id == "unit-converter-helper"  # NOT password-generator-helper


def test_owning_task_b2_app_module_selects_parked_owner_not_tokenize(tmp_path):
    """B2 live shape: `app.word_frequencies` unresolved. Pre-#790 reduced it to `app`,
    which substring-matched tokenize's `app/tokenize.py` -> re-ran tokenize. Now it maps
    to word-frequencies (creates app/word_frequencies.py), which parked."""
    repo = _mk_repo(tmp_path)
    tasks = [
        {"repo": str(repo), "task": "tokenize", "prompt": "p", "depends_on": [],
         "contract": {"creates": ["app/__init__.py", "app/tokenize.py"],
                      "exports": ["tokenize(text)"]}},
        {"repo": str(repo), "task": "word-frequencies", "prompt": "p",
         "depends_on": ["tokenize"],
         "contract": {"creates": ["app/word_frequencies.py"],
                      "exports": ["word_frequencies(tokens)"]}},
    ]
    plan = _build_plan(tmp_path, tasks)
    plan = pg.mark_ready(plan, "tokenize")
    plan = pg.mark_building(plan, "tokenize")
    plan = pg.mark_merged(plan, "tokenize", "ev")
    plan = pg.mark_parked(plan, "word-frequencies", "RESULT: Nothing to merge")
    driver = _driver(tmp_path, _ops([]), tasks, plan)
    unresolved = [{"raw": "from app.word_frequencies import word_frequencies",
                   "module": "app.word_frequencies",
                   "reason": "module 'app.word_frequencies' does not resolve"}]
    target = driver._owning_task(unresolved)
    assert target is not None and target.id == "word-frequencies"  # NOT tokenize


def test_owning_task_prefers_parked_owner_when_two_owners_match(tmp_path):
    """B2 with two owners in scope: `app.word_frequencies` (owner parked) AND `app.report`
    (owner skipped after the park). The parked/failed owner is re-run first (rank), never
    the skipped one whose own dependency is still missing."""
    repo = _mk_repo(tmp_path)
    tasks = [
        {"repo": str(repo), "task": "tokenize", "prompt": "p", "depends_on": [],
         "contract": {"creates": ["app/__init__.py", "app/tokenize.py"], "exports": ["tokenize(text)"]}},
        {"repo": str(repo), "task": "word-frequencies", "prompt": "p", "depends_on": ["tokenize"],
         "contract": {"creates": ["app/word_frequencies.py"], "exports": ["word_frequencies(tokens)"]}},
        {"repo": str(repo), "task": "report", "prompt": "p", "depends_on": ["word-frequencies"],
         "contract": {"creates": ["app/report.py"], "exports": ["combined_report(text)"]}},
    ]
    plan = _build_plan(tmp_path, tasks)
    plan = pg.mark_ready(plan, "tokenize")
    plan = pg.mark_building(plan, "tokenize")
    plan = pg.mark_merged(plan, "tokenize", "ev")
    plan = pg.mark_parked(plan, "word-frequencies", "ev")  # parks -> report SKIPPED transitively
    assert plan.task("report").status == pg.STATUS_SKIPPED
    driver = _driver(tmp_path, _ops([]), tasks, plan)
    unresolved = [
        {"module": "app.word_frequencies", "raw": "x", "reason": "y"},
        {"module": "app.report", "raw": "x", "reason": "y"},
    ]
    assert driver._owning_task(unresolved).id == "word-frequencies"  # parked beats skipped


def test_owning_task_still_selects_merged_owner_b6n2(tmp_path):
    """No parked owner: the MERGED owner that misplaced its module is still the target
    (the B6n2 case this gate was first built for — preserved)."""
    repo = _mk_repo(tmp_path)
    tasks = _layout_tasks(repo)  # core + cli; cli creates cli_interface
    plan = _build_plan(tmp_path, tasks)
    for tid in ("core", "cli"):
        plan = pg.mark_ready(plan, tid)
        plan = pg.mark_building(plan, tid)
        plan = pg.mark_merged(plan, tid, "ev")
    driver = _driver(tmp_path, _ops([]), tasks, plan)
    assert driver._owning_task(_UNRESOLVED).id == "cli"


def test_owning_task_falls_back_to_sink_when_no_contract_owns(tmp_path):
    """Fail-soft: when NO contract precisely owns the module, the pre-existing heuristic
    (merged sink / last merged) is byte-identical — no regression."""
    repo = _mk_repo(tmp_path)
    tasks = _b7_tasks(repo)
    plan = _build_plan(tmp_path, tasks)
    for tid in ("slugify-phrase-helper", "unit-converter-helper", "password-generator-helper"):
        plan = pg.mark_ready(plan, tid)
        plan = pg.mark_building(plan, tid)
        plan = pg.mark_merged(plan, tid, "ev")
    driver = _driver(tmp_path, _ops([]), tasks, plan)
    unresolved = [{"module": "totally-unrelated-thing", "raw": "x", "reason": "y"}]
    assert driver._owning_task(unresolved).id == "password-generator-helper"  # sinks[-1], unchanged


# ---- end-to-end: the fix cycle re-runs the owner (the regression lock) ----------------


def _b7_parking_run_task(calls, *, fix_marker: str):
    """A run_task that PARKS unit-converter-helper on its FIRST (wave) run and merges every
    other run — including the fix-cycle re-run (identified by *fix_marker* in the prompt)."""
    def run_task(t):
        calls.append(("task", t["task"], t["prompt"]))
        if t["task"] == "unit-converter-helper" and fix_marker not in t["prompt"]:
            return TaskOutcome(task=t["task"], outcome="errored", result="PARKED",
                               detail="RESULT: Nothing to merge")
        return _merged(t)
    return run_task


def test_layout_fix_cycle_reruns_parked_owner_not_sibling_b7(tmp_path):
    """THE #790 regression lock (B7): unit-converter-helper PARKS while its two independent
    siblings merge; the oracle imports convertUnit from the missing module. The ONE layout
    fix cycle must re-run the PARKED OWNER, never the last merged sibling (password-
    generator-helper — exactly what sinks[-1] re-ran before the fix, 0/3 on 2026-07-12)."""
    repo = _mk_repo(tmp_path)
    tasks = _b7_tasks(repo)
    plan = _build_plan(tmp_path, tasks)
    calls = []
    ops = _ops(calls, run_task=_b7_parking_run_task(calls, fix_marker="LAYOUT FIX"),
               job_oracle_contract=lambda: _B7_CONTRACT,
               run_import_probe=lambda r, p: {"ok": False, "unresolved": _B7_UNRESOLVED,
                                              "evidence": "unresolved"})
    _driver(tmp_path, ops, tasks, plan).run()
    fixed = [c[1] for c in calls if isinstance(c, tuple) and c[0] == "task"
             and "LAYOUT FIX" in c[2]]
    assert fixed == ["unit-converter-helper"]              # the owner, exactly once
    assert "password-generator-helper" not in fixed         # never the sibling
    # the fix prompt names the exact missing module (the coder's actionable signal)
    fix_prompt = next(c[2] for c in calls if isinstance(c, tuple) and c[0] == "task"
                      and c[1] == "unit-converter-helper" and "LAYOUT FIX" in c[2])
    assert "unit-converter-helper.js" in fix_prompt


def test_layout_fix_cycle_owner_rerun_resolves_import_b7(tmp_path):
    """The payoff: with the OWNER re-run (not a sibling), the re-probe RESOLVES and the
    layout gate does NOT fail the wave — the layout-fix-cycle now RESOLVES the import
    (0/3 -> resolved), where re-running a sibling structurally never could."""
    repo = _mk_repo(tmp_path)
    tasks = _b7_tasks(repo)
    plan = _build_plan(tmp_path, tasks)
    calls = []
    seq = iter([{"ok": False, "unresolved": _B7_UNRESOLVED, "evidence": "x"},
                {"ok": True, "unresolved": [], "evidence": "resolved"}])
    ops = _ops(calls, run_task=_b7_parking_run_task(calls, fix_marker="LAYOUT FIX"),
               job_oracle_contract=lambda: _B7_CONTRACT,
               run_import_probe=lambda r, p: next(seq))
    _driver(tmp_path, ops, tasks, plan).run()
    fixed = [c[1] for c in calls if isinstance(c, tuple) and c[0] == "task"
             and "LAYOUT FIX" in c[2]]
    assert fixed == ["unit-converter-helper"]
    sc = _scorecard(calls)
    assert not any(w["status"] == "failed" for w in sc["waves"])  # layout gate passed post-fix
    assert [c for c in calls if isinstance(c, tuple) and c[0] == "job_oracle"]  # oracle graded
    # N1 lock (#790 review): the owner-selection fix ships WITHOUT any verdict-
    # semantics change — the parked owner whose fix-cycle re-run MERGED stays
    # PARKED in the persisted plan (promoting a recovered owner to merged/GREEN
    # is an explicitly LA-held decision, deliberately not folded in here).
    persisted = pg.PlanStore(tmp_path / "plan.json", projects_dir=tmp_path).load()
    assert persisted.plan is not None
    assert persisted.plan.task("unit-converter-helper").status == pg.STATUS_PARKED


def test_exec_smoke_fix_cycle_reruns_parked_owner_not_sibling_b7(tmp_path):
    """The exec-smoke boot-fix cycle shares _owning_task, so it inherits the fix: a boot
    error naming the missing module re-runs the PARKED OWNER, not a merged sibling."""
    repo = _mk_repo(tmp_path)
    tasks = _b7_tasks(repo)
    plan = _build_plan(tmp_path, tasks)
    calls = []
    boot_fail = {
        "ok": False, "language": "node",
        "evidence": "booting node main.js failed: ERR_MODULE_NOT_FOUND ../src/unit-converter-helper.js",
        "fingerprint": "ERR_MODULE_NOT_FOUND",
        "unresolved": [{"spec": "../src/unit-converter-helper.js", "raw": "node main.js --help",
                        "reason": "Cannot find module ../src/unit-converter-helper.js"}],
    }
    ops = _ops(calls, run_task=_b7_parking_run_task(calls, fix_marker="EXECUTABILITY FIX"),
               run_exec_smoke=lambda r, p: dict(boot_fail))
    _driver(tmp_path, ops, tasks, plan).run()
    fixed = [c[1] for c in calls if isinstance(c, tuple) and c[0] == "task"
             and "EXECUTABILITY FIX" in c[2]]
    assert fixed == ["unit-converter-helper"]              # the owner, not password-generator-helper


# ---------------------------------------------------------------------------
# #831 per-task ERROR-level static pre-gate (the cheapest gate, FIRST)
# ---------------------------------------------------------------------------

_F821_ERR = {"summary": "storage.py:2 F821: Undefined name `convertUnits`",
             "code": "F821", "line": 2, "path": "storage.py", "lang": "python"}
_F821_FIX = ("STATIC PRE-GATE FIX (single focus — fix ONLY these exact error-level "
             "defects): storage.py:2 F821: Undefined name `convertUnits`")


def _pregate(ok, *, errors=None, fix_prompt=""):
    return {"ok": ok, "errors": errors or [], "checked": 1, "skipped": [],
            "stamp": ("clean" if ok else "fail" if ok is False else "skipped"),
            "evidence": "e", "fix_prompt": fix_prompt}


def test_static_pregate_noop_seam_is_byte_identical(tmp_path):
    """The default (noop) static-pregate seam returns ok=None → inert: the job grades +
    completes exactly as before the feature (byte-identical, no fix re-runs)."""
    repo = _mk_repo(tmp_path)
    tasks = _plan_tasks(repo)
    plan = _build_plan(tmp_path, tasks)
    calls = []
    result = _driver(tmp_path, _ops(calls), tasks, plan).run()  # noop default
    sc = _scorecard(calls)
    assert sc["job_acceptance"]["status"] == "passed" and result.outcome == "complete"
    assert not any(isinstance(c, tuple) and c[0] == "task" and "STATIC PRE-GATE FIX" in c[2]
                   for c in calls)


def test_static_pregate_clean_no_fix_cycle(tmp_path):
    repo = _mk_repo(tmp_path)
    tasks = _plan_tasks(repo)
    plan = _build_plan(tmp_path, tasks)
    calls = []
    ops = _ops(calls, run_static_pregate=lambda r, b, m: _pregate(True))
    _driver(tmp_path, ops, tasks, plan).run()
    assert not any(isinstance(c, tuple) and c[0] == "task" and "STATIC PRE-GATE FIX" in c[2]
                   for c in calls)
    assert _scorecard(calls)["job_acceptance"]["status"] == "passed"


def test_static_pregate_fail_feeds_fix_cycle_with_exact_error(tmp_path):
    """THE lock: an F821 defect is caught pre-suite and the fix cycle re-runs the
    offending task with the EXACT error named (file:line, single-focus)."""
    repo = _mk_repo(tmp_path)
    tasks = _plan_tasks(repo)
    plan = _build_plan(tmp_path, tasks)
    calls = []
    seq = iter([_pregate(False, errors=[_F821_ERR], fix_prompt=_F821_FIX)])
    ops = _ops(calls, run_static_pregate=lambda r, b, m: next(seq, _pregate(True)))
    _driver(tmp_path, ops, tasks, plan).run()
    fix_runs = [c for c in calls if isinstance(c, tuple) and c[0] == "task"
                and "STATIC PRE-GATE FIX" in c[2]]
    assert fix_runs, "the fix cycle must re-run the offending task"
    assert "F821" in fix_runs[0][2] and "convertUnits" in fix_runs[0][2]
    # the job still grades (the static pre-gate never blocks)
    assert _scorecard(calls)["job_acceptance"]["status"] == "passed"


def test_static_pregate_fix_resolves_then_job_grades(tmp_path):
    """Fail once → fix cycle → re-probe clean → the job grades; NO wave gate is failed by
    the static pre-gate (it is a fix-feed net, not an enforcer)."""
    repo = _mk_repo(tmp_path)
    tasks = _plan_tasks(repo)
    plan = _build_plan(tmp_path, tasks)
    calls = []
    seq = iter([_pregate(False, errors=[_F821_ERR], fix_prompt=_F821_FIX), _pregate(True)])
    ops = _ops(calls, repo_head=lambda r: "deadbeef12",  # non-empty → the re-probe fires
               run_static_pregate=lambda r, b, m: next(seq, _pregate(True)))
    _driver(tmp_path, ops, tasks, plan).run()
    sc = _scorecard(calls)
    assert sc["job_acceptance"]["status"] == "passed"
    assert not any(w["status"] == "failed" for w in sc["waves"])


def test_static_pregate_persistent_fail_is_non_blocking(tmp_path):
    """Even if the static pre-gate NEVER resolves, it never blocks: the wave gate + the
    finish-line oracle remain the enforcers, so an all-merged, wave-green, oracle-pass
    run stays GREEN (the static pre-gate is a fix-feed net, never a new blocker — the
    non-blocking design lock)."""
    repo = _mk_repo(tmp_path)
    tasks = _plan_tasks(repo)
    plan = _build_plan(tmp_path, tasks)
    calls = []
    ops = _ops(calls, repo_head=lambda r: "deadbeef12",
               run_static_pregate=lambda r, b, m: _pregate(
                   False, errors=[_F821_ERR], fix_prompt=_F821_FIX))
    _driver(tmp_path, ops, tasks, plan).run()
    sc = _scorecard(calls)
    assert sc["verdict"] == "GREEN"                        # never blocked
    assert not any(w["status"] == "failed" for w in sc["waves"])
    assert sc["job_acceptance"]["status"] == "passed"


def test_static_pregate_runs_before_the_wave_gate(tmp_path):
    """Composition: the per-task static pre-gate (cheapest) runs BEFORE the wave gate
    (the suite) for that wave — the cheapest-first ordering the ticket requires."""
    repo = _mk_repo(tmp_path)
    tasks = _plan_tasks(repo)
    plan = _build_plan(tmp_path, tasks)
    calls = []
    ops = _ops(
        calls,
        run_static_pregate=lambda r, b, m: (calls.append(("pregate", m)), _pregate(True))[1],
        run_wave_gate=lambda r: (calls.append(("wave_gate", r)),
                                 {"ok": True, "evidence": ""})[1],
    )
    _driver(tmp_path, ops, tasks, plan).run()
    kinds = [c[0] for c in calls
             if isinstance(c, tuple) and c[0] in ("pregate", "wave_gate")]
    assert kinds[0] == "pregate"                            # a task pre-gate comes first
    assert kinds.index("pregate") < kinds.index("wave_gate")  # before the wave suite


# ---------------------------------------------------------------------------
# Legacy byte-stability + cancel/stop verdicts
# ---------------------------------------------------------------------------


def test_legacy_mode_plan_none_emits_report_scorecard_not_wave_seams(tmp_path):
    calls = []
    seam_hits = []
    ops = _ops(
        calls,
        run_wave_gate=lambda r: (seam_hits.append("gate"), {"ok": True, "evidence": ""})[1],
        run_job_oracle=lambda r, p: (seam_hits.append("oracle"),
                                     {"status": "passed", "evidence": ""})[1],
        write_scorecard=lambda sc: seam_hits.append("scorecard"),
        write_job_summary=lambda t: seam_hits.append("summary"),
        log_pack=lambda tid, pack: seam_hits.append("pack"),
    )
    driver = sd.SwapDriver(
        run_id="R1", session_id="s1",
        tasks=[{"repo": "X", "task": "a", "prompt": "pa"}],
        swap_state_path=tmp_path / "swap.json", ops=ops,
        gate_gb=21.0, sleep=lambda _s: None,
    )
    result = driver.run()
    assert result.outcome == "complete"
    # F4 (#752): flat mode now emits the REPORT-phase scorecard + JOB_SUMMARY so the
    # battery adopts a real verdict instead of synthesizing STALLED [HARNESS]; the WAVE
    # seams (gate/oracle/pack) still never fire without a JobPlan.
    assert seam_hits == ["scorecard", "summary"]
    assert not ({"gate", "oracle", "pack"} & set(seam_hits))


def test_cancel_mid_plan_is_parked_honest_with_intervention(tmp_path):
    """Operator cancel: PARKED-HONEST (a refusal with evidence), attributed HARNESS
    (the adoption validator requires a valid attribution on every non-GREEN), with
    the operator signal carried by the ``interventions`` counter (§9.4 hard gate)."""
    repo = _mk_repo(tmp_path)
    tasks = _plan_tasks(repo)
    plan = _build_plan(tmp_path, tasks)
    calls = []
    cancels = iter([False, False, True])  # cancel before the second wave
    ops = _ops(calls, cancel_requested=lambda: next(cancels, True))
    result = _driver(tmp_path, ops, tasks, plan).run()
    assert result.cancelled
    sc = _scorecard(calls)
    assert sc["cancelled"] is True
    assert sc["interventions"] == 1
    assert sc["verdict"] == "PARKED-HONEST" and sc["attribution"] == "HARNESS"
    assert "cancelled by the operator" in sc["notes"]


def test_budget_stop_mid_plan_is_stalled_harness(tmp_path):
    repo = _mk_repo(tmp_path)
    tasks = _plan_tasks(repo)
    plan = _build_plan(tmp_path, tasks)
    calls = []
    stops = iter([False, False, False, True])
    ops = _ops(calls, stop_requested=lambda: next(stops, True))
    result = _driver(tmp_path, ops, tasks, plan).run()
    assert result.outcome == "budget-timeout"
    sc = _scorecard(calls)
    assert sc["verdict"] == "STALLED" and sc["attribution"] == "HARNESS"


def test_job_summary_written_with_evidence_pointers(tmp_path):
    repo = _mk_repo(tmp_path)
    tasks = _plan_tasks(repo)
    plan = _build_plan(tmp_path, tasks)
    calls = []
    _driver(tmp_path, _ops(calls), tasks, plan).run()
    summaries = [c[1] for c in calls if isinstance(c, tuple) and c[0] == "job_summary"]
    assert len(summaries) == 1
    text = summaries[0]
    assert "verdict: GREEN" in text
    assert "[merged] storage" in text
    assert "wave 1: passed" in text
    assert "Job acceptance" in text
    # The JOB_SUMMARY must never collide with dispatch.parse_summary's task-line shape.
    from shared.fleet.dispatch import parse_summary

    assert parse_summary(text) == []


def test_scorecard_schema_shape(tmp_path):
    repo = _mk_repo(tmp_path)
    tasks = _plan_tasks(repo)
    plan = _build_plan(tmp_path, tasks)
    calls = []
    # #790: a representative per-task best-of-N log (new-agent-task.ps1's exact line
    # shape) so samples_consumed recovers a REAL value via run_dir instead of the -1
    # default — see the fallback/sum/parser-focused tests below for the rest of the
    # honesty contract (absent signal, multi-task summing, the bare parse).
    (tmp_path / "run-fleet-storage.log").write_text(
        "  Best-of-N: 2 candidate(s) -> no candidate passed; kept the best of 2 by gate rank.\n"
        "RESULT: MERGED to main\n",
        encoding="utf-8",
    )
    _driver(tmp_path, _ops(calls), tasks, plan, run_dir=tmp_path).run()
    sc = _scorecard(calls)
    assert sc["schema"] == sd.SCORECARD_SCHEMA
    for key in ("run_id", "plan_id", "goal", "repo", "verdict", "attribution",
                "cancelled", "degraded", "wall_clock_s", "tasks", "waves",
                "job_acceptance", "packs_consumed", "samples_consumed",
                "interventions", "redecompose_spent", "not_measured", "notes",
                "evidence"):
        assert key in sc, f"scorecard missing {key}"
    assert sc["verdict"] == "GREEN" and sc["attribution"] == ""
    # The battery adoption conventions (tools/dispatch_harness/scorecard.py):
    # -1 == not instrumented; oracle_status is the FALSE-DONE cross-check hook.
    # #790: samples_consumed is now RECOVERED (run_dir was supplied above) — it is
    # measured this time, so it drops out of not_measured too.
    assert sc["samples_consumed"] == 2
    assert "samples_consumed" not in sc["not_measured"]
    assert sc["interventions"] == 0
    assert sc["evidence"]["oracle_status"] == "passed"


def test_scorecard_samples_consumed_fallback_when_run_dir_absent(tmp_path):
    """#790 honesty contract: no run_dir supplied (the byte-identical default for
    every caller that predates this feature, e.g. the plan_graph.py simulation
    harness) -> samples_consumed stays -1 ("not instrumented") and is named in
    not_measured. This is the exact assertion test_scorecard_schema_shape carried
    before run_dir existed, now isolated under its own name."""
    repo = _mk_repo(tmp_path)
    tasks = _plan_tasks(repo)
    plan = _build_plan(tmp_path, tasks)
    calls = []
    _driver(tmp_path, _ops(calls), tasks, plan).run()  # no run_dir kwarg
    sc = _scorecard(calls)
    assert sc["samples_consumed"] == -1
    assert "samples_consumed" in sc["not_measured"]


def test_scorecard_samples_consumed_fallback_when_no_best_of_n_line(tmp_path):
    """run_dir IS supplied but its log carries no Best-of-N line (every task resolved
    on its first candidate, the common case — new-agent-task.ps1 only prints the line
    when ``$bon.Count -gt 1``) -> still -1, NEVER a false '0 consumed' claim (0
    candidates consumed is never literally true; -1 means honestly unknown)."""
    repo = _mk_repo(tmp_path)
    tasks = _plan_tasks(repo)
    plan = _build_plan(tmp_path, tasks)
    calls = []
    (tmp_path / "run-fleet-storage.log").write_text("RESULT: MERGED to main\n", encoding="utf-8")
    _driver(tmp_path, _ops(calls), tasks, plan, run_dir=tmp_path).run()
    sc = _scorecard(calls)
    assert sc["samples_consumed"] == -1
    assert "samples_consumed" in sc["not_measured"]


def test_samples_consumed_from_run_dir_parses_best_of_n_line(tmp_path):
    """#790 focused parser lock: a representative 'Best-of-N: N candidate(s) -> ...'
    line — the exact shape new-agent-task.ps1 writes (#689) — is recovered."""
    (tmp_path / "run-fleet-storage.log").write_text(
        "[1/5] Building candidate 1 of 2 in isolated workspace (Model, max 30 min)...\n"
        "  Candidate 1 did not pass the gate; trying a FRESH independent candidate (2/2)...\n"
        "  Best-of-N: 2 candidate(s) -> no candidate passed; kept the best of 2 by gate rank.\n"
        "RESULT: MERGED to main\n",
        encoding="utf-8",
    )
    assert sd._samples_consumed_from_run_dir(tmp_path) == 2


def test_samples_consumed_from_run_dir_sums_across_task_logs(tmp_path):
    """Each task gets its own run-fleet-<slug>.log (#689/#695 concurrent candidates);
    the job-level samples_consumed SUMS every task's recovered count. A task that
    never sampled beyond its first candidate (util here) contributes nothing — the
    documented lower-bound honesty, not a missing-file error."""
    (tmp_path / "run-fleet-storage.log").write_text(
        "  Best-of-N: 2 candidate(s) -> no candidate passed; kept the best of 2 by gate rank.\n",
        encoding="utf-8",
    )
    (tmp_path / "run-fleet-util.log").write_text("RESULT: MERGED to main\n", encoding="utf-8")
    (tmp_path / "run-fleet-report.log").write_text(
        "  Best-of-N: 3 candidate(s) -> candidate 2 passed the gate.\n",
        encoding="utf-8",
    )
    assert sd._samples_consumed_from_run_dir(tmp_path) == 5


def test_samples_consumed_from_run_dir_none_or_missing_is_sentinel(tmp_path):
    """None / '' / a directory that doesn't exist are all the same honest -1 —
    never raises, never guesses 0."""
    assert sd._samples_consumed_from_run_dir(None) == -1
    assert sd._samples_consumed_from_run_dir("") == -1
    assert sd._samples_consumed_from_run_dir(tmp_path / "does-not-exist") == -1


def test_scorecard_is_adoptable_by_the_battery_runner(tmp_path):
    """The cross-lane lock: the driver's emitted scorecard must survive Lane V's
    REAL adopt_driver_scorecard (overlay + validate + FALSE-DONE cross-check)
    without degrading — an unadoptable card is scored STALLED+HARNESS by design,
    which would silently discard every real verdict this driver computes."""
    battery = pytest.importorskip("tools.dispatch_harness.battery")
    from tools.dispatch_harness.report import JobReport

    repo = _mk_repo(tmp_path)
    tasks = _plan_tasks(repo)
    plan = _build_plan(tmp_path, tasks)
    calls = []
    _driver(tmp_path, _ops(calls), tasks, plan).run()
    raw = _scorecard(calls)
    card = {"id": "B1", "repo": "battery-b1",
            "expected_outcome": {"oracle": {"expected": True}}, "rigs": []}
    report = JobReport(repo="battery-b1", goal="g", run_id="R1", wall_clock_s=1.0)
    adopted = battery.adopt_driver_scorecard(raw, card=card, report=report, dry_run=False)
    assert adopted.verdict == "GREEN", f"adoption degraded the card: {adopted.notes}"
    assert adopted.attribution == ""
    assert adopted.packs_consumed == raw["packs_consumed"]
    # And a non-GREEN card adopts with its attribution intact (validator-clean).
    calls2 = []
    ops2 = _ops(calls2, run_job_oracle=sd._noop_job_oracle)
    _driver(tmp_path / "x2", ops2, tasks, _build_plan(tmp_path, tasks)).run()
    raw2 = _scorecard(calls2)
    adopted2 = battery.adopt_driver_scorecard(raw2, card=card, report=report, dry_run=False)
    assert adopted2.verdict == "STALLED" and adopted2.attribution == "VERIFY"
    assert "invalid" not in adopted2.notes


# ---------------------------------------------------------------------------
# compute_job_verdict (pure)
# ---------------------------------------------------------------------------


def _verdict_plan(tmp_path, *, statuses: dict, acc_status: str = "pending") -> pg.JobPlan:
    repo = _mk_repo(tmp_path, "vp")
    tasks = [{"repo": str(repo), "task": tid, "prompt": "p", "depends_on": []}
             for tid in statuses]
    plan = _build_plan(tmp_path, tasks, run_id="V1")
    for tid, status in statuses.items():
        if status == "merged":
            plan = pg.mark_ready(plan, tid)
            plan = pg.mark_building(plan, tid)
            plan = pg.mark_merged(plan, tid, "ev")
        elif status == "parked":
            plan = pg.mark_parked(plan, tid, "ev")
        elif status == "blocked":
            plan = pg.mark_blocked(plan, tid, "ev")
    if acc_status != "pending":
        plan = pg.mark_job_acceptance(plan, acc_status, "ev")
    return plan


def test_verdict_green_requires_oracle_pass(tmp_path):
    plan = _verdict_plan(tmp_path, statuses={"a": "merged"}, acc_status="passed")
    assert sd.compute_job_verdict(plan, cancelled=False, stopped=False,
                                  wave_gates=[]) == ("GREEN", "")
    plan2 = _verdict_plan(tmp_path, statuses={"a": "merged"}, acc_status="not-run")
    verdict, attribution = sd.compute_job_verdict(
        plan2, cancelled=False, stopped=False, wave_gates=[])
    assert verdict == "STALLED" and attribution == "VERIFY"


def test_verdict_never_green_with_failed_gate(tmp_path):
    plan = _verdict_plan(tmp_path, statuses={"a": "merged"}, acc_status="passed")
    verdict, attribution = sd.compute_job_verdict(
        plan, cancelled=False, stopped=False,
        wave_gates=[{"wave": 1, "status": "failed", "evidence": "x"}])
    assert verdict == "PARKED-HONEST" and attribution == "BUILD"


def test_verdict_parked_and_blocked_attribute_build(tmp_path):
    for bad in ("parked", "blocked"):
        plan = _verdict_plan(tmp_path, statuses={"a": "merged", "b": bad})
        verdict, attribution = sd.compute_job_verdict(
            plan, cancelled=False, stopped=False, wave_gates=[])
        assert verdict == "PARKED-HONEST" and attribution == "BUILD"


def test_verdict_stopped_is_stalled_harness(tmp_path):
    plan = _verdict_plan(tmp_path, statuses={"a": "merged"}, acc_status="passed")
    assert sd.compute_job_verdict(plan, cancelled=False, stopped=True,
                                  wave_gates=[]) == ("STALLED", "HARNESS")


def test_verdict_flaky_oracle_reroutes_build_to_verify(tmp_path):
    """#829: an all-merged tree whose JOB ORACLE failed then PASSED on a fresh hermetic
    re-run is a nondeterministic GRADER, not a wrong coder — the park attribution moves
    BUILD -> VERIFY. Without the flag the SAME failure stays BUILD (byte-stable)."""
    plan = _verdict_plan(tmp_path, statuses={"a": "merged"}, acc_status="failed")
    assert sd.compute_job_verdict(
        plan, cancelled=False, stopped=False, wave_gates=[], oracle_flaky=True) == (
            "PARKED-HONEST", "VERIFY")
    # The flag is opt-in: default False is byte-identical to before #829.
    assert sd.compute_job_verdict(
        plan, cancelled=False, stopped=False, wave_gates=[]) == ("PARKED-HONEST", "BUILD")
    assert sd.compute_job_verdict(
        plan, cancelled=False, stopped=False, wave_gates=[], oracle_flaky=False) == (
            "PARKED-HONEST", "BUILD")


def test_verdict_flaky_flag_never_reroutes_a_gate_failure(tmp_path):
    """The reroute is narrow: a FAILED WAVE GATE is a build-integration instrument the
    flake differential never re-ran, so it stays BUILD even if oracle_flaky is set (the
    flag can only relabel a JOB-ORACLE park, never launder a gate failure)."""
    plan = _verdict_plan(tmp_path, statuses={"a": "merged"}, acc_status="passed")
    verdict, attribution = sd.compute_job_verdict(
        plan, cancelled=False, stopped=False,
        wave_gates=[{"wave": 1, "status": "failed", "evidence": "x"}], oracle_flaky=True)
    assert verdict == "PARKED-HONEST" and attribution == "BUILD"


def test_verdict_flaky_flag_never_mints_green_or_reroutes_a_real_park(tmp_path):
    """oracle_flaky can never UPGRADE a verdict: a genuinely parked/blocked task stays a
    BUILD park (a real build failure), and the flag never produces GREEN."""
    plan = _verdict_plan(tmp_path, statuses={"a": "merged", "b": "parked"})
    verdict, attribution = sd.compute_job_verdict(
        plan, cancelled=False, stopped=False, wave_gates=[], oracle_flaky=True)
    assert verdict == "PARKED-HONEST" and attribution == "BUILD"


def test_flaky_oracle_scorecard_and_driver_attribute_verify(tmp_path):
    """End-to-end through the driver seams: a job oracle that reports failed +
    ``oracle_flaky`` (the wrapper's flip stamp) drives the scorecard to PARKED-HONEST
    (VERIFY) with an ``oracle_flaky: true`` evidence stamp — the coder stops eating the
    grader's flakiness. The default (no flag) attributes the same failure BUILD."""
    repo = _mk_repo(tmp_path)
    tasks = _plan_tasks(repo)

    def _run(flaky: bool) -> dict:
        plan = _build_plan(tmp_path, tasks)
        calls = []
        oracle = {"status": "failed", "evidence": "nonzero exit; assert 689 == 1"}
        if flaky:
            oracle["oracle_flaky"] = True
        ops = _ops(calls, run_job_oracle=lambda r, rel: (
            calls.append(("job_oracle", r, rel)), dict(oracle))[1])
        _driver(tmp_path, ops, tasks, plan).run()
        return _scorecard(calls)

    flaky_sc = _run(True)
    assert flaky_sc["verdict"] == "PARKED-HONEST" and flaky_sc["attribution"] == "VERIFY"
    assert flaky_sc["evidence"]["oracle_flaky"] == "true"
    assert flaky_sc["evidence"]["oracle_status"] == "failed"  # never mints a pass

    plain_sc = _run(False)
    assert plain_sc["verdict"] == "PARKED-HONEST" and plain_sc["attribution"] == "BUILD"
    assert "oracle_flaky" not in plain_sc["evidence"]


# ---------------------------------------------------------------------------
# Oracle FITNESS (oracle_unfit) — a grader that covered ZERO criteria graded
# nothing, so its failures are evidence about ITSELF, not about the build.
#
# Founding evidence (both PARKED-HONEST [BUILD] with failure_class ORACLE-DEFECT
# — the coder convicted of the grader's bug, twice):
#   * run 20260719-002208-bd (card B4) — 6/6 build waves passed, import probe and
#     layout gate clean, job oracle failed 4-of-6 (three NameErrors on a module the
#     oracle never imports + an unwrapped SystemExit: 0), oracle-qa oracle_coverage
#     "0/6", covered [].
#   * 2026-07-16, same B4 card — docs/quality/dispatch-quality-ledger.md.
# ---------------------------------------------------------------------------

#: The measured B4 oracle-qa.json (run 20260719-002208-bd) — a blind grader that
#: nevertheless issued a verdict. Kept verbatim as the positive control: the
#: fitness predicate must call THIS unfit, or the class is not actually caught.
_B4_UNFIT_ORACLE_QA = {
    "validated": True,
    "language": "python",
    "verdict": "seed-partial",
    "findings": {"invented_contract": 9, "traceability_gap": 12, "collectability": 0},
    "findings_total": 21,
    "regeneration": {"rounds": 2, "exhausted": False},
    "oracle_coverage": "0/6",
    "covered": [],
    "uncovered": ["c2", "c3", "c4", "c5", "c7", "c8"],
    "f2p_baseline": "not-run",
    "collectability": "unconfirmed",
}


def _write_oracle_qa(run_dir: Path, payload) -> Path:
    """Seed a run directory with an ``oracle-qa.json`` sidecar (raw text when
    *payload* is a str, so malformed-JSON cases are expressible)."""
    run_dir.mkdir(parents=True, exist_ok=True)
    path = run_dir / "oracle-qa.json"
    path.write_text(payload if isinstance(payload, str) else json.dumps(payload),
                    encoding="utf-8")
    return path


def test_coverage_zero_predicate_parses_only_a_real_zero_numerator():
    """The fitness parse, exhaustively. UNFIT is exactly ``"0/n"`` with n > 0;
    every ambiguous or malformed input is NOT unfit, so a missing/garbled signal
    can never silently re-tag a park (fail toward current behaviour)."""
    assert sd._coverage_is_zero("0/6") is True
    assert sd._coverage_is_zero("0/1") is True
    assert sd._coverage_is_zero(" 0 / 6 ") is True  # tolerant of whitespace

    # Fit graders — any covered criterion at all.
    for fit in ("1/6", "3/6", "6/6", "1/1"):
        assert sd._coverage_is_zero(fit) is False, fit

    # Degenerate / unknown / malformed — never unfit.
    for unknown in ("0/0", "unknown", "", "partial", "full", "0", "/6", "0/",
                    "0/6/7", "-0/6", "0.0/6", "zero/six", "0/six", "n/a"):
        assert sd._coverage_is_zero(unknown) is False, unknown

    # Absent or wrong-typed — never unfit, never raises.
    for absent in (None, 0, 0.0, [], {}, True, ["0/6"]):
        assert sd._coverage_is_zero(absent) is False, absent

    # Bounded: an absurdly long token is refused rather than parsed.
    assert sd._coverage_is_zero("0/" + "9" * 200) is False


def test_oracle_unfit_reads_the_runs_own_oracle_qa_sidecar(tmp_path):
    """The run-dir read: the measured B4 sidecar is UNFIT; a covering grader is FIT;
    and every absent/unreadable shape is FIT (never re-tag on missing data)."""
    unfit_dir = tmp_path / "unfit"
    _write_oracle_qa(unfit_dir, _B4_UNFIT_ORACLE_QA)
    assert sd._oracle_unfit_from_run_dir(unfit_dir) is True
    assert sd._oracle_unfit_from_run_dir(str(unfit_dir)) is True  # str path too

    fit_dir = tmp_path / "fit"
    _write_oracle_qa(fit_dir, {**_B4_UNFIT_ORACLE_QA,
                               "oracle_coverage": "3/6", "covered": ["c2", "c3", "c4"]})
    assert sd._oracle_unfit_from_run_dir(fit_dir) is False

    # No run_dir at all / a directory with no sidecar / a sidecar with no stamp.
    assert sd._oracle_unfit_from_run_dir(None) is False
    assert sd._oracle_unfit_from_run_dir("") is False
    empty = tmp_path / "empty"
    empty.mkdir()
    assert sd._oracle_unfit_from_run_dir(empty) is False
    assert sd._oracle_unfit_from_run_dir(tmp_path / "does-not-exist") is False
    no_stamp = tmp_path / "nostamp"
    _write_oracle_qa(no_stamp, {"validated": True, "language": "python"})
    assert sd._oracle_unfit_from_run_dir(no_stamp) is False

    # Unreadable / wrong-shaped payloads — fail-soft to FIT, never raise.
    for name, payload in (("malformed", "{not json at all"),
                          ("truncated", '{"oracle_coverage": "0/6"'),
                          ("list", "[1, 2, 3]"),
                          ("scalar", '"0/6"'),
                          ("empty-file", ""),
                          ("null-cov", '{"oracle_coverage": null}')):
        bad = tmp_path / name
        _write_oracle_qa(bad, payload)
        assert sd._oracle_unfit_from_run_dir(bad) is False, name


def test_verdict_unfit_oracle_reroutes_build_to_verify(tmp_path):
    """The defect this closes: an all-merged tree whose JOB ORACLE covered ZERO
    criteria is a grader that graded nothing — the park attribution moves BUILD ->
    VERIFY. The verdict itself is unchanged: PARKED-HONEST in, PARKED-HONEST out."""
    plan = _verdict_plan(tmp_path, statuses={"a": "merged"}, acc_status="failed")
    assert sd.compute_job_verdict(
        plan, cancelled=False, stopped=False, wave_gates=[], oracle_unfit=True) == (
            "PARKED-HONEST", "VERIFY")


def test_verdict_fit_oracle_on_a_failed_job_still_attributes_build(tmp_path):
    """TOGGLE-OFF (the probe must be able to FAIL): with the lock disengaged — a FIT
    grader, or no fitness finding at all — the very same failed job stays BUILD. Without
    this the VERIFY assertion above proves only that the test can't reach the branch."""
    plan = _verdict_plan(tmp_path, statuses={"a": "merged"}, acc_status="failed")
    # Explicitly fit.
    assert sd.compute_job_verdict(
        plan, cancelled=False, stopped=False, wave_gates=[], oracle_unfit=False) == (
            "PARKED-HONEST", "BUILD")
    # Opt-in: the default is byte-identical to the pre-fix behaviour.
    assert sd.compute_job_verdict(
        plan, cancelled=False, stopped=False, wave_gates=[]) == ("PARKED-HONEST", "BUILD")


def test_verdict_unknown_coverage_never_silently_retags(tmp_path):
    """Unknown/absent coverage is NOT a fitness finding: the predicate returns False and
    the park stays BUILD. Re-tagging on missing data would launder real build failures
    into grader faults — the fix must fail toward the pre-existing attribution."""
    plan = _verdict_plan(tmp_path, statuses={"a": "merged"}, acc_status="failed")
    for coverage in ("unknown", "0/0", "", "garbage"):
        run_dir = tmp_path / f"cov-{coverage or 'blank'}".replace("/", "-")
        _write_oracle_qa(run_dir, {**_B4_UNFIT_ORACLE_QA, "oracle_coverage": coverage})
        unfit = sd._oracle_unfit_from_run_dir(run_dir)
        assert unfit is False, coverage
        assert sd.compute_job_verdict(
            plan, cancelled=False, stopped=False, wave_gates=[], oracle_unfit=unfit) == (
                "PARKED-HONEST", "BUILD"), coverage


def test_verdict_unfit_is_anchored_on_coverage_not_finding_counts(tmp_path):
    """The rejected anchor, locked: ``invented_contract`` / ``traceability_gap`` are
    CUMULATIVE across regeneration rounds and carry a known false-positive, so they must
    NEVER drive attribution. A grader with the B4 finding counts but real coverage (3/6)
    is FIT, and its failed job stays BUILD."""
    noisy_but_covering = {**_B4_UNFIT_ORACLE_QA,
                          "oracle_coverage": "3/6",
                          "covered": ["c2", "c3", "c4"],
                          "findings": {"invented_contract": 99, "traceability_gap": 99},
                          "findings_total": 198}
    run_dir = tmp_path / "noisy"
    _write_oracle_qa(run_dir, noisy_but_covering)
    assert sd._oracle_unfit_from_run_dir(run_dir) is False
    plan = _verdict_plan(tmp_path, statuses={"a": "merged"}, acc_status="failed")
    assert sd.compute_job_verdict(
        plan, cancelled=False, stopped=False, wave_gates=[], oracle_unfit=False) == (
            "PARKED-HONEST", "BUILD")


def test_verdict_unfit_flag_never_reroutes_a_gate_failure(tmp_path):
    """PRECEDENCE lock: a FAILED WAVE GATE is a build-integration instrument that oracle
    coverage says nothing about, so it stays BUILD even when the oracle is also unfit —
    the flag can only relabel a JOB-ORACLE park, never launder a gate failure."""
    plan = _verdict_plan(tmp_path, statuses={"a": "merged"}, acc_status="passed")
    verdict, attribution = sd.compute_job_verdict(
        plan, cancelled=False, stopped=False,
        wave_gates=[{"wave": 1, "status": "failed", "evidence": "x"}], oracle_unfit=True)
    assert verdict == "PARKED-HONEST" and attribution == "BUILD"
    # And with BOTH grader-fault flags set it is still the gate that decides.
    assert sd.compute_job_verdict(
        plan, cancelled=False, stopped=False,
        wave_gates=[{"wave": 1, "status": "failed", "evidence": "x"}],
        oracle_flaky=True, oracle_unfit=True) == ("PARKED-HONEST", "BUILD")


def test_verdict_unfit_flag_never_upgrades_a_verdict(tmp_path):
    """The load-bearing safety property: ``oracle_unfit`` only ever RE-TAGS a park.

    It can never mint GREEN out of a non-GREEN, never rescues a genuinely parked or
    blocked task, never touches the stopped/cancelled/stalled classes — and it never
    demotes a real pass either, so pass BANKING is unaffected (a GREEN's coverage
    disclosure is the separate #832 green-audit authority, not this one)."""
    plan = _verdict_plan(tmp_path, statuses={"a": "merged"}, acc_status="failed")
    for gates in ([], [{"wave": 1, "status": "passed", "evidence": "x"}]):
        verdict, _ = sd.compute_job_verdict(
            plan, cancelled=False, stopped=False, wave_gates=gates, oracle_unfit=True)
        assert verdict != "GREEN"

    # A real build park stays a BUILD park.
    parked = _verdict_plan(tmp_path, statuses={"a": "merged", "b": "parked"})
    assert sd.compute_job_verdict(
        parked, cancelled=False, stopped=False, wave_gates=[], oracle_unfit=True) == (
            "PARKED-HONEST", "BUILD")
    blocked = _verdict_plan(tmp_path, statuses={"a": "merged", "b": "blocked"})
    assert sd.compute_job_verdict(
        blocked, cancelled=False, stopped=False, wave_gates=[], oracle_unfit=True) == (
            "PARKED-HONEST", "BUILD")

    # Harness classes are untouched.
    assert sd.compute_job_verdict(
        plan, cancelled=False, stopped=True, wave_gates=[], oracle_unfit=True) == (
            "STALLED", "HARNESS")
    assert sd.compute_job_verdict(
        plan, cancelled=True, stopped=False, wave_gates=[], oracle_unfit=True) == (
            "PARKED-HONEST", "HARNESS")

    # A PASSING oracle still banks GREEN — pass banking is unaffected.
    passed = _verdict_plan(tmp_path, statuses={"a": "merged"}, acc_status="passed")
    assert sd.compute_job_verdict(
        passed, cancelled=False, stopped=False, wave_gates=[], oracle_unfit=True) == (
            "GREEN", "")

    # An unrun oracle stays the merged-but-unverifiable STALLED class.
    unrun = _verdict_plan(tmp_path, statuses={"a": "merged"}, acc_status="not-run")
    assert sd.compute_job_verdict(
        unrun, cancelled=False, stopped=False, wave_gates=[], oracle_unfit=True) == (
            "STALLED", "VERIFY")


def test_unfit_oracle_scorecard_and_driver_attribute_verify(tmp_path):
    """REACHABILITY through the real driver seams — the lock that proves the predicate is
    WIRED, not merely written (a pure function nothing calls is the built-into-nothing
    shape). The driver reads the run's OWN oracle-qa.json off disk: the measured B4
    sidecar drives PARKED-HONEST (VERIFY) with an ``oracle_unfit: true`` stamp, while the
    identical run whose grader covered 3/6 still attributes BUILD."""
    repo = _mk_repo(tmp_path)
    tasks = _plan_tasks(repo)

    def _run(name: str, oracle_qa) -> dict:
        run_dir = tmp_path / name
        if oracle_qa is not None:
            _write_oracle_qa(run_dir, oracle_qa)
        plan = _build_plan(tmp_path, tasks)
        calls = []
        oracle = {"status": "failed",
                  "evidence": "nonzero exit; NameError: name 'data_storage' is not defined"}
        ops = _ops(calls, run_job_oracle=lambda r, rel: (
            calls.append(("job_oracle", r, rel)), dict(oracle))[1])
        _driver(tmp_path, ops, tasks, plan, run_dir=run_dir).run()
        return _scorecard(calls)

    unfit_sc = _run("unfit-run", _B4_UNFIT_ORACLE_QA)
    assert unfit_sc["verdict"] == "PARKED-HONEST" and unfit_sc["attribution"] == "VERIFY"
    assert unfit_sc["evidence"]["oracle_unfit"] == "true"
    assert unfit_sc["evidence"]["oracle_status"] == "failed"  # never mints a pass
    assert "graded ZERO" in unfit_sc["notes"]

    fit_sc = _run("fit-run", {**_B4_UNFIT_ORACLE_QA,
                              "oracle_coverage": "4/6", "covered": ["c2", "c3", "c4", "c5"]})
    assert fit_sc["verdict"] == "PARKED-HONEST" and fit_sc["attribution"] == "BUILD"
    assert "oracle_unfit" not in fit_sc["evidence"]

    # No sidecar at all (the pre-#821 shape): unchanged, still BUILD.
    bare_sc = _run("bare-run", None)
    assert bare_sc["verdict"] == "PARKED-HONEST" and bare_sc["attribution"] == "BUILD"
    assert "oracle_unfit" not in bare_sc["evidence"]

    # CROSS-LANE lock: the new evidence key must survive Lane V's REAL adopter. A
    # scorecard the adopter refuses degrades to STALLED+HARNESS and takes the whole
    # night's verdict with it — the exact d0294595 shape, where a newly-folded
    # evidence value was rejected by the fail-closed writer on its first live run.
    battery = pytest.importorskip("tools.dispatch_harness.battery")
    from tools.dispatch_harness.report import JobReport

    card = {"id": "B4", "repo": "battery-b4",
            "expected_outcome": {"oracle": {"expected": True}}, "rigs": []}
    report = JobReport(repo="battery-b4", goal="g", run_id="R1", wall_clock_s=1.0)
    adopted = battery.adopt_driver_scorecard(
        unfit_sc, card=card, report=report, dry_run=False)
    assert adopted.verdict == "PARKED-HONEST", f"adoption degraded the card: {adopted.notes}"
    assert adopted.attribution == "VERIFY"
    assert adopted.evidence.get("oracle_unfit") == "true"


# ---------------------------------------------------------------------------
# Job-oracle generation (acceptance.py) — python + node, fail-closed
# ---------------------------------------------------------------------------

_PY_ORACLE = (
    "from storage import save\n\n"
    "def test_save_roundtrip():\n"
    "    assert save(1) is not None\n"
)
_NODE_ORACLE = (
    "import test from 'node:test';\n"
    "import assert from 'node:assert';\n"
    "import { addExpense } from '../src/storage.mjs';\n"
    "test('adds', () => { assert.ok(addExpense({amount: 1})); });\n"
)


def _spec(*, language_hint=None, surface=None, with_criteria=True) -> AcceptanceSpec:
    build_plan = None
    if language_hint is not None or surface is not None:
        build_plan = {"surface": surface or "unknown", "language_hint": language_hint,
                      "complexity": "moderate", "components": []}
    criteria = ()
    if with_criteria:
        criteria = (
            AcceptanceCriterion(id="c1", text="It adds expenses correctly",
                                tier="behavior", check="add then list"),
        )
    return AcceptanceSpec(goal="a budget tracker", criteria=criteria,
                          build_plan=build_plan)


def _contract_tasks(n: int = 2) -> list[dict]:
    return [
        {"repo": "X", "task": f"t{i}", "prompt": f"p{i}",
         "contract": {"creates": [f"src/m{i}.py"], "exports": [f"f{i}(x)"], "notes": ""}}
        for i in range(n)
    ]


def test_job_oracle_python_multi_task():
    code, path = generate_job_acceptance_oracle(
        "a budget tracker", _spec(language_hint="python"), _contract_tasks(),
        generate_fn=lambda p: _PY_ORACLE,
    )
    assert path == JOB_ORACLE_PATH_PYTHON
    assert "def test_save_roundtrip" in code


def test_job_oracle_node_via_hint_and_via_web_surface():
    for spec in (_spec(language_hint="node"), _spec(surface="web")):
        code, path = generate_job_acceptance_oracle(
            "g", spec, _contract_tasks(), generate_fn=lambda p: _NODE_ORACLE)
        assert path == JOB_ORACLE_PATH_NODE
        assert "node:test" in code


def test_job_oracle_prompt_carries_contracts_and_criteria():
    seen = {}

    def gen(prompt):
        seen["prompt"] = prompt
        return _PY_ORACLE

    generate_job_acceptance_oracle(
        "a budget tracker", _spec(language_hint="python"), _contract_tasks(),
        generate_fn=gen)
    assert "creates src/m0.py" in seen["prompt"]
    assert "exports f0(x)" in seen["prompt"]
    assert "It adds expenses correctly" in seen["prompt"]


#: A BROKEN hypothesis JOB oracle: `st.text(min_length=1)` raises TypeError at collection.
_BROKEN_HYP_JOB_ORACLE = (
    "from hypothesis import given\n"
    "from hypothesis import strategies as st\n"
    "from src.m0 import f0\n"
    "\n\n"
    "@given(st.text(min_length=1))\n"
    "def test_f0(s):\n"
    "    assert f0(s) is not None\n"
)


def test_job_oracle_repairs_hypothesis_kwargs():
    # The job-level generator also repairs the known-invalid Hypothesis size kwargs before its
    # structural validation, so a mis-emitted property test seeds collectable (battery job B1).
    code, path = generate_job_acceptance_oracle(
        "a budget tracker", _spec(language_hint="python"), _contract_tasks(),
        generate_fn=lambda p: _BROKEN_HYP_JOB_ORACLE)
    assert path == JOB_ORACLE_PATH_PYTHON
    assert "min_length" not in code
    assert "st.text(min_size=1)" in code


@pytest.mark.parametrize("case", ["single", "no_target", "no_criteria", "no_contracts",
                                  "junk_py", "junk_node", "raises"])
def test_job_oracle_fail_closed(case):
    spec = _spec(language_hint="python")
    tasks = _contract_tasks()
    gen = lambda p: _PY_ORACLE
    if case == "single":
        tasks = _contract_tasks(1)
    elif case == "no_target":
        spec = _spec(language_hint="dotnet")
    elif case == "no_criteria":
        spec = _spec(language_hint="python", with_criteria=False)
    elif case == "no_contracts":
        tasks = [{"repo": "X", "task": "t", "prompt": "p"},
                 {"repo": "X", "task": "u", "prompt": "q"}]
    elif case == "junk_py":
        gen = lambda p: "def broken(:\n"
    elif case == "junk_node":
        spec = _spec(language_hint="node")
        gen = lambda p: "console.log('no tests here')"
    elif case == "raises":
        def gen(_p):
            raise RuntimeError("model down")
    assert generate_job_acceptance_oracle("g", spec, tasks, generate_fn=gen) == ("", "")


def test_generate_plan_stamps_job_oracle_on_last_task(tmp_path):
    repo = _mk_repo(tmp_path, "budget")

    def gen(prompt):
        if "decomposing a software change request" in prompt:
            return json.dumps([
                {"task": "storage", "prompt": "build storage", "depends_on": [],
                 "contract": {"creates": ["src/storage.py"], "exports": ["save(x)"],
                              "notes": ""}},
                {"task": "report", "prompt": "build report", "depends_on": ["storage"]},
            ])
        if "ACCEPTANCE CRITERIA" in prompt:
            return json.dumps([{"text": "It adds expenses correctly",
                                "tier": "behavior", "check": "add then list"}])
        if "Classify what KIND of software" in prompt:
            return json.dumps({"surface": "command-line", "candidates": [],
                               "language_hint": "python", "complexity": "simple",
                               "components": []})
        if "JOB-LEVEL ACCEPTANCE" in prompt:
            return _PY_ORACLE
        return "[]"

    plan = generate_plan("a budget tracker", "budget", generate_fn=gen,
                         projects_dir=tmp_path)
    assert plan.ok and len(plan.tasks) >= 2
    last = plan.tasks[-1]
    assert last.get(JOB_ORACLE_PATH_KEY) == JOB_ORACLE_PATH_PYTHON
    assert "def test_save_roundtrip" in last.get(JOB_ORACLE_CODE_KEY, "")
    # No other task carries the blob.
    assert all(JOB_ORACLE_CODE_KEY not in t for t in plan.tasks[:-1])


def test_extract_job_oracle_pops_keys_and_refuses_unpinned_path():
    tasks = [
        {"repo": "X", "task": "a", "prompt": "p"},
        {"repo": "X", "task": "b", "prompt": "q",
         JOB_ORACLE_CODE_KEY: "code", JOB_ORACLE_PATH_KEY: JOB_ORACLE_PATH_PYTHON},
    ]
    cleaned, code, path = extract_job_oracle(tasks)
    assert code == "code" and path == JOB_ORACLE_PATH_PYTHON
    assert all(JOB_ORACLE_CODE_KEY not in t and JOB_ORACLE_PATH_KEY not in t
               for t in cleaned)
    # S1 containment: a traversal path is refused outright.
    evil = [{"repo": "X", "task": "a", "prompt": "p",
             JOB_ORACLE_CODE_KEY: "code", JOB_ORACLE_PATH_KEY: "../../evil.py"}]
    _cleaned, code2, path2 = extract_job_oracle(evil)
    assert (code2, path2) == ("", "")


# ---------------------------------------------------------------------------
# Live seams with injected runners (no real subprocess)
# ---------------------------------------------------------------------------


def _config(tmp_path: Path) -> FleetDispatchConfig:
    setup = tmp_path / "setup"
    (setup / "scripts").mkdir(parents=True)
    return FleetDispatchConfig(
        scripts_dir=setup / "scripts",
        queue_path=setup / "state" / "fleet-queue.json",
        runs_dir=setup / "state" / "fleet-runs",
        projects_dir=tmp_path,
    )


def test_real_run_job_oracle_restore_before_grade(tmp_path, monkeypatch):
    config = _config(tmp_path)
    repo = _mk_repo(tmp_path, "target")
    target = repo / JOB_ORACLE_PATH_PYTHON
    target.parent.mkdir(parents=True)
    target.write_text("TAMPERED BY A MERGED TASK", encoding="utf-8")
    monkeypatch.setattr(so.shutil, "which", lambda name: f"C:/fake/{name}.exe")
    graded = {}

    def fake_run(cmd, timeout_s, cwd=None, env=None):
        graded["cmd"] = cmd
        graded["cwd"] = cwd
        graded["env"] = env
        graded["content_at_grade"] = target.read_text(encoding="utf-8")
        return (True, "1 passed", "")

    res = so.real_run_job_oracle(config, "R1", str(repo), JOB_ORACLE_PATH_PYTHON,
                                 _PY_ORACLE, run=fake_run)
    assert res["status"] == "passed"
    # Restore-before-grade: the PLAN bytes were graded, never the tampered file...
    assert graded["content_at_grade"] == _PY_ORACLE
    assert graded["cwd"] == str(repo)
    # ...and the tree is left exactly as the merges made it.
    assert target.read_text(encoding="utf-8") == "TAMPERED BY A MERGED TASK"
    # The audit copy survives in the run dir.
    audit = config.runs_dir / "R1" / "job-oracle-test_job_acceptance.py"
    assert audit.read_text(encoding="utf-8") == _PY_ORACLE


def test_real_run_job_oracle_removes_file_when_absent_before(tmp_path, monkeypatch):
    config = _config(tmp_path)
    repo = _mk_repo(tmp_path, "target2")
    monkeypatch.setattr(so.shutil, "which", lambda name: f"C:/fake/{name}.exe")
    res = so.real_run_job_oracle(config, "R1", str(repo), JOB_ORACLE_PATH_PYTHON,
                                 _PY_ORACLE, run=lambda c, t, cwd=None, env=None: (False, "", "1 failed"))
    assert res["status"] == "failed"
    assert not (repo / JOB_ORACLE_PATH_PYTHON).exists()


def test_real_run_job_oracle_refuses_unpinned_path_and_missing_code(tmp_path):
    config = _config(tmp_path)
    repo = _mk_repo(tmp_path, "target3")
    res = so.real_run_job_oracle(config, "R1", str(repo), "../../evil.py", "code",
                                 run=lambda c, t, cwd=None: (True, "", ""))
    assert res["status"] == "not-run" and "refused" in res["evidence"]
    assert not (tmp_path / "evil.py").exists()
    res2 = so.real_run_job_oracle(config, "R1", str(repo), JOB_ORACLE_PATH_PYTHON, "",
                                  run=lambda c, t, cwd=None: (True, "", ""))
    assert res2["status"] == "not-run"


def test_real_run_job_oracle_node_uses_node_test_runner(tmp_path, monkeypatch):
    config = _config(tmp_path)
    repo = _mk_repo(tmp_path, "web")
    monkeypatch.setattr(so.shutil, "which", lambda name: f"C:/fake/{name}.exe")
    seen = {}

    def fake_run(cmd, timeout_s, cwd=None):
        seen["cmd"] = cmd
        return (True, "pass 1", "")

    res = so.real_run_job_oracle(config, "R1", str(repo), JOB_ORACLE_PATH_NODE,
                                 _NODE_ORACLE, run=fake_run)
    assert res["status"] == "passed"
    assert seen["cmd"][0].endswith("node.exe") and seen["cmd"][1] == "--test"
    assert seen["cmd"][2] == JOB_ORACLE_PATH_NODE


def test_real_run_wave_gate_honesty_matrix(tmp_path, monkeypatch):
    config = _config(tmp_path)
    (config.scripts_dir / "verify-project.ps1").write_text("# stub", encoding="utf-8")
    repo = _mk_repo(tmp_path, "pyproj")
    (repo / "main.py").write_text("print('hi')\n", encoding="utf-8")
    monkeypatch.setattr(so.shutil, "which", lambda name: f"C:/fake/{name}.exe")

    def run_pass(cmd, timeout_s, cwd=None):
        if "verify-project.ps1" in str(cmd):
            return (True, '{"overall": "pass"}', "")
        return (True, "ok", "")

    res = so.real_run_wave_gate(config, "R1", str(repo), run=run_pass)
    assert res["ok"] is True and "verify=pass" in res["evidence"]

    def run_fail(cmd, timeout_s, cwd=None):
        if "verify-project.ps1" in str(cmd):
            return (True, '{"overall": "pass"}', "")
        return (False, "FAILED test_x", "")

    res2 = so.real_run_wave_gate(config, "R1", str(repo), run=run_fail)
    assert res2["ok"] is False and "tests=fail" in res2["evidence"]

    # Neither signal could run -> honest None (could-not-run), never pass or fail.
    config_no_script = _config(tmp_path / "other")
    empty_repo = _mk_repo(tmp_path, "emptyproj")
    res3 = so.real_run_wave_gate(config_no_script, "R1", str(empty_repo),
                                 run=lambda c, t, cwd=None: (True, "", ""))
    assert res3["ok"] is None


# ---------------------------------------------------------------------------
# build_job_plan (swap_ops) — the run_swap-side plan construction + degrade rule
# ---------------------------------------------------------------------------


def _swap_config(tmp_path: Path) -> FleetDispatchConfig:
    setup = tmp_path / "agentic"
    (setup / "scripts").mkdir(parents=True)
    return FleetDispatchConfig(
        scripts_dir=setup / "scripts",
        queue_path=setup / "state" / "fleet-queue.json",
        runs_dir=setup / "state" / "fleet-runs",
        projects_dir=tmp_path,
        plan_graph=True,
    )


def test_build_job_plan_builds_validates_and_persists(tmp_path):
    config = _swap_config(tmp_path)
    repo = _mk_repo(tmp_path, "budget")
    tasks = _plan_tasks(repo)
    plan, store, degraded, cleaned = so.build_job_plan(config, "R9", tasks)
    assert plan is not None and store is not None and degraded is False
    assert len(cleaned) == 3
    assert (so.plan_path(config)).is_file()
    # The persisted artifact re-loads clean through the hash-verifying store.
    assert pg.PlanStore(so.plan_path(config), projects_dir=tmp_path).load().ok


def test_build_job_plan_forged_statuses_cannot_seed_completion(tmp_path):
    """W1-hardening reconciliation: persisted/forged statuses are ADVISORY, never
    authority. A swap-state task claiming status=merged (tamper or stale resume data)
    must land in the fresh plan as PENDING — done-ness is re-derived ONLY from this
    run's fleet RESULT lines + a fresh oracle run (§9 zero-FALSE-DONE)."""
    config = _swap_config(tmp_path)
    repo = _mk_repo(tmp_path, "budget2")
    tasks = _plan_tasks(repo)
    for t in tasks:
        t["status"] = "merged"          # the forgery
    plan, _store, _deg, _cleaned = so.build_job_plan(config, "R9", tasks)
    assert plan is not None
    assert all(t.status == pg.STATUS_PENDING for t in plan.tasks)


def test_build_job_plan_stamps_acceptance_deps_and_pops_oracle(tmp_path):
    config = _swap_config(tmp_path)
    repo = _mk_repo(tmp_path, "budget3")
    tasks = _plan_tasks(repo) + [{
        "repo": str(repo), "task": "acceptance-tests", "prompt": "write the tests",
        JOB_ORACLE_CODE_KEY: _PY_ORACLE, JOB_ORACLE_PATH_KEY: JOB_ORACLE_PATH_PYTHON,
    }]
    plan, _store, _deg, cleaned = so.build_job_plan(config, "R9", tasks)
    assert plan is not None
    # Seam note (a): the appended acceptance task depends on ALL feature tasks.
    acc = plan.task("acceptance-tests")
    assert set(acc.depends_on) == {"storage", "report", "util"}
    # The oracle blob is POPPED from the driver-facing dicts; its path pins the plan.
    assert all(JOB_ORACLE_CODE_KEY not in t for t in cleaned)
    assert plan.job_acceptance.oracle_path == JOB_ORACLE_PATH_PYTHON


def test_build_job_plan_reads_criteria_from_acceptance_record(tmp_path):
    config = _swap_config(tmp_path)
    repo = _mk_repo(tmp_path, "budget4")
    from shared.fleet.dispatch import write_acceptance_record

    write_acceptance_record(
        config, "R9",
        spec_dict={"goal": "the recorded goal",
                   "criteria": [{"id": "c1", "text": "It adds", "tier": "behavior",
                                 "check": ""}]},
        repo=str(repo),
    )
    plan, _store, _deg, _cleaned = so.build_job_plan(config, "R9", _plan_tasks(repo))
    assert plan is not None
    assert plan.goal == "the recorded goal"
    assert plan.job_acceptance.criteria == ["It adds"]


def test_build_job_plan_refusal_degrades_to_flat_queue(tmp_path):
    # A repo-CONTAINMENT refusal (the plan ruler rejects a repo outside projects_dir) degrades
    # to the flat queue. TWO tasks so the refusal is driven by validate_plan, not the separate
    # <2-task degrade rule below (which would otherwise short-circuit a 1-task list first).
    config = _swap_config(tmp_path)
    outside = tmp_path.parent / "outside-repo"
    (outside / ".git").mkdir(parents=True, exist_ok=True)
    tasks = [{"repo": str(outside), "task": "a", "prompt": "pa", "depends_on": []},
             {"repo": str(outside), "task": "b", "prompt": "pb", "depends_on": []}]
    plan, store, degraded, cleaned = so.build_job_plan(config, "R9", tasks)
    assert plan is None and store is None and degraded is False
    assert cleaned                      # the flat queue still runs these
    # The degradation is LOGGED, never hidden.
    trail = so.read_swap_progress(config, "R9")
    assert "degrading to the flat task queue" in trail


def test_build_job_plan_single_task_degrades_to_flat_queue(tmp_path):
    """A <2-task plan has no job-level oracle and no graph to schedule; running it as a 1-task
    plan-graph job records job acceptance not-run and STALLS at [VERIFY] even when the lone
    task merged clean (the 2026-07-06 B2 under-decomposition failure). build_job_plan must
    DEGRADE it to the flat queue (plan=None) so the per-task path — build/test/verify + the
    #690 per-task oracle the task still carries — grades the single task -> GREEN-able."""
    config = _swap_config(tmp_path)
    repo = _mk_repo(tmp_path, "solo")
    # One IN-BOUNDS, otherwise-valid task (it would PASS repo containment) — proving the degrade
    # is driven ONLY by the <2 count, never a validation refusal. It carries a per-task oracle
    # field (the #690 shared scorecard), which must survive extract_job_oracle to the flat queue.
    tasks = [{"repo": str(repo), "task": "solo", "prompt": "build the whole toolkit",
              "depends_on": [], "acceptance_test_code": "def test_x():\n    assert True\n"}]
    plan, store, degraded, cleaned = so.build_job_plan(config, "R9", tasks)
    assert plan is None and store is None and degraded is False
    assert len(cleaned) == 1 and cleaned[0]["task"] == "solo"   # flat queue runs the lone task
    assert cleaned[0].get("acceptance_test_code")               # per-task oracle preserved
    assert not so.plan_path(config).is_file()                  # no plan-graph artifact persisted
    trail = so.read_swap_progress(config, "R9")
    assert "degrading to the flat task queue" in trail and "<2-task plan" in trail


# ---------------------------------------------------------------------------
# #824 — always-on per-run decompose-downgrade evidence (decompose-diagnostics.json)
# ---------------------------------------------------------------------------


def _read_decompose_decision(config, run_id) -> dict:
    return json.loads(so.decompose_diagnostics_path(config, run_id).read_text(encoding="utf-8"))


def test_build_job_plan_writes_plan_graph_decision_evidence(tmp_path):
    """A plan-graph dispatch records mode=plan-graph + the task slugs — the #827 classifier
    reads this per-run instead of inferring the mode from a prose swap-progress line."""
    config = _swap_config(tmp_path)
    repo = _mk_repo(tmp_path, "budget5")
    plan, _store, _deg, _cleaned = so.build_job_plan(config, "R9", _plan_tasks(repo))
    assert plan is not None
    decision = _read_decompose_decision(config, "R9")
    assert decision["schema"] == "decompose-decision/v1"
    assert decision["mode"] == "plan-graph"
    assert decision["flat_reason"] == "" and decision["degraded"] is False
    assert decision["cleaned_task_count"] == 3
    assert set(decision["task_slugs"]) == {"storage", "report", "util"}


def test_build_job_plan_single_task_writes_flat_decision_evidence(tmp_path):
    """The B5/habit downgrade class: a <2-task plan records mode=flat + flat_reason=under-2-tasks
    so the next battery night MEASURES the downgrade (with the surviving slug) not infers it."""
    config = _swap_config(tmp_path)
    repo = _mk_repo(tmp_path, "solo2")
    tasks = [{"repo": str(repo), "task": "solo", "prompt": "build the whole toolkit",
              "depends_on": []}]
    plan, _store, _deg, _cleaned = so.build_job_plan(config, "R9", tasks)
    assert plan is None
    decision = _read_decompose_decision(config, "R9")
    assert decision["mode"] == "flat" and decision["flat_reason"] == "under-2-tasks"
    assert decision["cleaned_task_count"] == 1 and decision["task_slugs"] == ["solo"]


def test_build_job_plan_refusal_writes_flat_decision_evidence(tmp_path):
    """A validation refusal records mode=flat + flat_reason=validation-refused:<reason> so the
    WHY is captured per-run (not just that it degraded)."""
    config = _swap_config(tmp_path)
    outside = tmp_path.parent / "outside-repo-824"
    (outside / ".git").mkdir(parents=True, exist_ok=True)
    tasks = [{"repo": str(outside), "task": "a", "prompt": "pa", "depends_on": []},
             {"repo": str(outside), "task": "b", "prompt": "pb", "depends_on": []}]
    plan, _store, _deg, _cleaned = so.build_job_plan(config, "R9", tasks)
    assert plan is None
    decision = _read_decompose_decision(config, "R9")
    assert decision["mode"] == "flat"
    assert decision["flat_reason"].startswith("validation-refused:")


# ---------------------------------------------------------------------------
# #748 — job-oracle SEEDING (the coder codes toward the job spec, plan §4.5)
# ---------------------------------------------------------------------------


def test_oracle_seeded_before_wave_one_and_prompts_carry_the_spec(tmp_path):
    # Run 20260705-214803-bd failure class: the oracle graded a module layout the
    # coder was never shown. Seeding must happen BEFORE the first task runs and
    # every task prompt must carry the job-spec sentence.
    repo = _mk_repo(tmp_path)
    tasks = _plan_tasks(repo)
    plan = _build_plan(tmp_path, tasks)
    calls = []
    ops = _ops(calls, seed_job_oracle=lambda repo_, rel: (
        calls.append(("seed", repo_, rel)), {"ok": True, "evidence": "seeded"})[1])
    _driver(tmp_path, ops, tasks, plan).run()
    seed_idx = next(i for i, c in enumerate(calls)
                    if isinstance(c, tuple) and c[0] == "seed")
    first_task_idx = next(i for i, c in enumerate(calls)
                          if isinstance(c, tuple) and c[0] == "task")
    assert seed_idx < first_task_idx
    assert calls[seed_idx][2] == plan.job_acceptance.oracle_path
    prompts = [c[2] for c in calls if isinstance(c, tuple) and c[0] == "task"]
    assert prompts
    assert all("job-level acceptance file" in p for p in prompts)
    assert all(plan.job_acceptance.oracle_path in p for p in prompts)


def test_unseeded_oracle_leaves_prompts_unchanged(tmp_path):
    # The noop default (ok=False) reproduces pre-seeding behavior exactly: no spec
    # sentence in any prompt, the run proceeds, the oracle still grades at the end.
    repo = _mk_repo(tmp_path)
    tasks = _plan_tasks(repo)
    plan = _build_plan(tmp_path, tasks)
    calls = []
    _driver(tmp_path, _ops(calls), tasks, plan).run()
    prompts = [c[2] for c in calls if isinstance(c, tuple) and c[0] == "task"]
    assert prompts
    assert all("job-level acceptance file" not in p for p in prompts)
    assert any(isinstance(c, tuple) and c[0] == "job_oracle" for c in calls)


def test_seed_op_raising_never_blocks_the_run(tmp_path):
    repo = _mk_repo(tmp_path)
    tasks = _plan_tasks(repo)
    plan = _build_plan(tmp_path, tasks)
    calls = []

    def _boom(_r, _p):
        raise RuntimeError("seed exploded")

    _driver(tmp_path, _ops(calls, seed_job_oracle=_boom), tasks, plan).run()
    assert any(isinstance(c, tuple) and c[0] == "task" for c in calls)
    assert any(isinstance(c, tuple) and c[0] == "job_oracle" for c in calls)


def test_real_seed_job_oracle_writes_guarded_file_and_commits(tmp_path, monkeypatch):
    config = _config(tmp_path)
    repo = _mk_repo(tmp_path, "seedme")
    monkeypatch.setattr(so.shutil, "which", lambda name: f"C:/fake/{name}.exe")
    ran = []

    def fake_run(cmd, timeout_s, cwd=None):
        ran.append((tuple(cmd), cwd))
        return (True, "", "")

    res = so.real_seed_job_oracle(config, "R1", str(repo), JOB_ORACLE_PATH_PYTHON,
                                  _PY_ORACLE, run=fake_run)
    assert res["ok"] is True
    seeded = (repo / JOB_ORACLE_PATH_PYTHON).read_text(encoding="utf-8")
    # Guard-wrapped: module-level skip FIRST, then the oracle verbatim.
    assert "allow_module_level=True" in seeded.split(_PY_ORACLE)[0]
    assert seeded.endswith(_PY_ORACLE)
    # git add + git commit, argv-only, cwd=repo.
    assert [c[0][1] for c in ran] == ["add", "commit"]
    assert all(c[1] == str(repo) for c in ran)
    # Idempotent: identical re-seed is ok WITHOUT touching git again.
    ran.clear()
    res2 = so.real_seed_job_oracle(config, "R1", str(repo), JOB_ORACLE_PATH_PYTHON,
                                   _PY_ORACLE, run=fake_run)
    assert res2["ok"] is True and "already" in res2["evidence"]
    assert ran == []


def test_real_seed_job_oracle_containment_refusals(tmp_path, monkeypatch):
    config = _config(tmp_path)
    repo = _mk_repo(tmp_path, "seedno")
    # Unpinned path refused — nothing written.
    res = so.real_seed_job_oracle(config, "R1", str(repo), "../../evil.py", "code",
                                  run=lambda c, t, cwd=None: (True, "", ""))
    assert res["ok"] is False and "refused" in res["evidence"]
    assert not (tmp_path / "evil.py").exists()
    # Empty oracle code refused.
    res2 = so.real_seed_job_oracle(config, "R1", str(repo), JOB_ORACLE_PATH_PYTHON, "",
                                   run=lambda c, t, cwd=None: (True, "", ""))
    assert res2["ok"] is False
    # Defense-in-depth: a PINNED path whose extension has no designed guard is
    # refused, never seeded unguarded (an unguarded seed would fail every gate).
    import shared.fleet.acceptance as acceptance

    monkeypatch.setattr(acceptance, "JOB_ORACLE_ALLOWED_PATHS",
                        frozenset({"tests/oracle.spec.ts"}))
    res3 = so.real_seed_job_oracle(config, "R1", str(repo), "tests/oracle.spec.ts",
                                   "it('x', () => {});",
                                   run=lambda c, t, cwd=None: (True, "", ""))
    assert res3["ok"] is False and "no seed guard" in res3["evidence"]
    assert not (repo / "tests" / "oracle.spec.ts").exists()


def test_real_seed_job_oracle_commit_failure_is_honest(tmp_path, monkeypatch):
    # An uncommitted seed never reaches task worktrees (they branch from main), so a
    # failed commit must report ok=False — the driver then says "NOT seeded" honestly.
    config = _config(tmp_path)
    repo = _mk_repo(tmp_path, "seedfail")
    monkeypatch.setattr(so.shutil, "which", lambda name: f"C:/fake/{name}.exe")

    def fake_run(cmd, timeout_s, cwd=None):
        if cmd[1] == "commit":
            return (False, "", "hook rejected")
        return (True, "", "")

    res = so.real_seed_job_oracle(config, "R1", str(repo), JOB_ORACLE_PATH_PYTHON,
                                  _PY_ORACLE, run=fake_run)
    assert res["ok"] is False and "commit failed" in res["evidence"]


def test_grade_overwrites_seeded_guard_and_restores_it(tmp_path, monkeypatch):
    # The seeded (guarded) copy is `prior` at grade time: plan bytes are graded,
    # the guarded copy is restored — the guard never needs a gate exclusion.
    config = _config(tmp_path)
    repo = _mk_repo(tmp_path, "seedgrade")
    monkeypatch.setattr(so.shutil, "which", lambda name: f"C:/fake/{name}.exe")
    so.real_seed_job_oracle(config, "R1", str(repo), JOB_ORACLE_PATH_PYTHON,
                            _PY_ORACLE, run=lambda c, t, cwd=None: (True, "", ""))
    seeded = (repo / JOB_ORACLE_PATH_PYTHON).read_text(encoding="utf-8")
    graded = {}

    def fake_run(cmd, timeout_s, cwd=None, env=None):
        graded["content"] = (repo / JOB_ORACLE_PATH_PYTHON).read_text(encoding="utf-8")
        return (True, "1 passed", "")

    res = so.real_run_job_oracle(config, "R1", str(repo), JOB_ORACLE_PATH_PYTHON,
                                 _PY_ORACLE, run=fake_run)
    assert res["status"] == "passed"
    assert graded["content"] == _PY_ORACLE          # UNguarded plan bytes graded
    assert (repo / JOB_ORACLE_PATH_PYTHON).read_text(encoding="utf-8") == seeded


# ---------------------------------------------------------------------------
# #740 — NODE job-oracle seeding (the .mjs guard: hoisting-proof skip wrapper)
# ---------------------------------------------------------------------------

_SKIP_NO_NODE = pytest.mark.skipif(
    shutil.which("node") is None, reason="node not on PATH"
)

#: A plan-shaped node oracle whose imports point at NOT-YET-BUILT modules and whose
#: body carries ``*/``-bearing content (a star regex + a glob string) — the exact
#: classes that break a block-comment wrap and defeat a top-of-file exit guard.
_NODE_SEED_ORACLE = (
    "import test from 'node:test';\n"
    "import assert from 'node:assert';\n"
    "import { addExpense } from '../src/storage.mjs';\n"
    "import { listByMonth } from '../src/report.mjs';\n"
    "test('adds', () => { assert.ok(addExpense({amount: 1})); });\n"
    "test('star regex + glob survive commenting', () => {\n"
    "  assert.match('aa', /a*/);\n"
    "  assert.ok('src/**/*.mjs'.length > 0);\n"
    "});\n"
)


def test_real_seed_job_oracle_node_writes_guarded_file_and_commits(
    tmp_path, monkeypatch
):
    config = _config(tmp_path)
    repo = _mk_repo(tmp_path, "seednode")
    monkeypatch.setattr(so.shutil, "which", lambda name: f"C:/fake/{name}.exe")
    ran = []

    def fake_run(cmd, timeout_s, cwd=None):
        ran.append((tuple(cmd), cwd))
        return (True, "", "")

    res = so.real_seed_job_oracle(config, "R1", str(repo), JOB_ORACLE_PATH_NODE,
                                  _NODE_SEED_ORACLE, run=fake_run)
    assert res["ok"] is True
    seeded = (repo / JOB_ORACLE_PATH_NODE).read_text(encoding="utf-8")
    # Guard first: the skip-registering node:test wrapper precedes the spec body.
    guard = seeded.split("// ---- seeded oracle spec below")[0]
    assert "node:test" in guard and "{ skip:" in guard
    # HOISTING-PROOF BY CONSTRUCTION: the only uncommented import in the whole
    # seeded file is the node:test builtin — no executable line can reference a
    # not-yet-built module (static ESM imports link before any body statement).
    executable = [ln for ln in seeded.splitlines() if not ln.lstrip().startswith("//")]
    imports = [ln for ln in executable if "import" in ln]
    assert imports and all("node:test" in ln for ln in imports)
    assert all("../src/" not in ln for ln in executable)
    # The oracle body rides along line-commented VERBATIM (the coder's readable spec).
    for line in _NODE_SEED_ORACLE.splitlines():
        assert f"// {line}" in seeded
    # git add + git commit, argv-only, cwd=repo (same corridor as the python seed).
    assert [c[0][1] for c in ran] == ["add", "commit"]
    assert all(c[1] == str(repo) for c in ran)
    # Idempotent: identical re-seed is ok WITHOUT touching git again.
    ran.clear()
    res2 = so.real_seed_job_oracle(config, "R1", str(repo), JOB_ORACLE_PATH_NODE,
                                   _NODE_SEED_ORACLE, run=fake_run)
    assert res2["ok"] is True and "already" in res2["evidence"]
    assert ran == []


def test_real_seed_job_oracle_node_commit_failure_is_honest(tmp_path, monkeypatch):
    # Same honesty contract as the python seed: an uncommitted .mjs seed never
    # reaches task worktrees, so a failed commit must report ok=False.
    config = _config(tmp_path)
    repo = _mk_repo(tmp_path, "seednodefail")
    monkeypatch.setattr(so.shutil, "which", lambda name: f"C:/fake/{name}.exe")

    def fake_run(cmd, timeout_s, cwd=None):
        if cmd[1] == "commit":
            return (False, "", "hook rejected")
        return (True, "", "")

    res = so.real_seed_job_oracle(config, "R1", str(repo), JOB_ORACLE_PATH_NODE,
                                  _NODE_SEED_ORACLE, run=fake_run)
    assert res["ok"] is False and "commit failed" in res["evidence"]


def test_grade_overwrites_seeded_node_guard_and_restores_it(tmp_path, monkeypatch):
    # Plan bytes ALWAYS win for .mjs too: the seeded (guarded) copy is `prior` at
    # grade time — node --test grades the UNWRAPPED plan-carried oracle, then the
    # guarded copy is restored, so the guard needs no env var at grade time.
    config = _config(tmp_path)
    repo = _mk_repo(tmp_path, "seednodegrade")
    monkeypatch.setattr(so.shutil, "which", lambda name: f"C:/fake/{name}.exe")
    so.real_seed_job_oracle(config, "R1", str(repo), JOB_ORACLE_PATH_NODE,
                            _NODE_SEED_ORACLE,
                            run=lambda c, t, cwd=None: (True, "", ""))
    seeded = (repo / JOB_ORACLE_PATH_NODE).read_text(encoding="utf-8")
    assert seeded != _NODE_SEED_ORACLE
    graded = {}

    def fake_run(cmd, timeout_s, cwd=None):
        graded["cmd"] = cmd
        graded["content"] = (repo / JOB_ORACLE_PATH_NODE).read_text(encoding="utf-8")
        return (True, "pass 2", "")

    res = so.real_run_job_oracle(config, "R1", str(repo), JOB_ORACLE_PATH_NODE,
                                 _NODE_SEED_ORACLE, run=fake_run)
    assert res["status"] == "passed"
    assert graded["content"] == _NODE_SEED_ORACLE   # UNguarded plan bytes graded
    assert graded["cmd"][1] == "--test"             # via the node:test runner
    assert (repo / JOB_ORACLE_PATH_NODE).read_text(encoding="utf-8") == seeded


@_SKIP_NO_NODE
def test_seeded_node_oracle_is_inert_under_real_node_test(tmp_path):
    # The load-bearing proof of the .mjs guard design (#740): static ESM imports
    # are HOISTED — module linking resolves them before ANY body statement, so a
    # top-of-file exit can never beat an import of a not-yet-built module; only a
    # seed whose body cannot LINK (line-commented) is safe under `npm test` /
    # `node --test` wave gates. Seed a guarded oracle whose imports point at
    # modules that DO NOT EXIST, then drive the REAL node:
    #   1. file-arg + discovery runs of the SEEDED copy pass clean (skipped 1);
    #   2. the UNWRAPPED plan bytes (exactly what grading writes) FAIL — proving
    #      node really collects this path and the guard is load-bearing.
    config = _config(tmp_path)
    repo = _mk_repo(tmp_path, "webproj")
    so.real_seed_job_oracle(config, "R1", str(repo), JOB_ORACLE_PATH_NODE,
                            _NODE_SEED_ORACLE,
                            run=lambda c, t, cwd=None: (True, "", ""))
    node = shutil.which("node")
    assert node is not None

    def run_node(*args: str) -> tuple[int, str]:
        cp = subprocess.run(  # noqa: S603 — pinned binary, constant argv, tmp cwd
            [node, "--test", *args], cwd=str(repo), capture_output=True,
            encoding="utf-8", errors="replace", timeout=120,
        )
        return cp.returncode, (cp.stdout or "") + (cp.stderr or "")

    rc, out = run_node(JOB_ORACLE_PATH_NODE)      # per-file (the grader's shape)
    assert rc == 0, out
    assert "skipped 1" in out and "fail 0" in out
    rc2, out2 = run_node()                        # discovery (the npm-test shape)
    assert rc2 == 0, out2
    assert "skipped 1" in out2
    # Control: the raw plan bytes at the same path MUST fail (missing modules) —
    # the same write grading performs; a guard "passing" here would be theater.
    (repo / JOB_ORACLE_PATH_NODE).write_text(_NODE_SEED_ORACLE, encoding="utf-8")
    rc3, out3 = run_node(JOB_ORACLE_PATH_NODE)
    assert rc3 != 0, out3


def test_job_oracle_template_demands_argv_hygiene():
    # Run 20260705-224742-bd: the oracle's launch test called main() in-process and
    # pytest's own argv leaked into the app — a structurally unfair red for every
    # argv-reading CLI (6/7 oracle tests green, the launch smoke red on pytest's
    # flags). The python template must instruct sys.argv isolation for in-process
    # CLI entry-point calls.
    from shared.fleet.acceptance import _JOB_ORACLE_TEMPLATE_PY

    assert "sys.argv" in _JOB_ORACLE_TEMPLATE_PY
    assert "never leak" in _JOB_ORACLE_TEMPLATE_PY
