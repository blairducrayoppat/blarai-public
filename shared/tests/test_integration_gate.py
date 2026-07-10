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
    # Roots get NO pack (byte-identical prompts).
    assert prompts["storage"] == "build storage"
    assert prompts["util"] == "build util"
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
    # report depends on storage: delta must be bracketed by storage's (base, merge).
    assert deltas == [("base1", "merge1")]


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
    _driver(tmp_path, _ops(calls), tasks, plan).run()
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
    assert sc["samples_consumed"] == -1
    assert "samples_consumed" in sc["not_measured"]
    assert sc["interventions"] == 0
    assert sc["evidence"]["oracle_status"] == "passed"


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

    def fake_run(cmd, timeout_s, cwd=None):
        graded["cmd"] = cmd
        graded["cwd"] = cwd
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
                                 _PY_ORACLE, run=lambda c, t, cwd=None: (False, "", "1 failed"))
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

    def fake_run(cmd, timeout_s, cwd=None):
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
