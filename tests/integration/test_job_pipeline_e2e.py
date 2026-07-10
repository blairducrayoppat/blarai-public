"""L1 full-pipeline orchestration simulator — scaffold + scenario table (W9).

Plan §9.2: a cross-workstream harness that drives the REAL plan-graph driver loop
end-to-end with an injected scripted 14B (``generate_fn``) and a scripted fleet
(canned ``RESULT:`` lines / ``TaskOutcome``s) — no GPU, milliseconds per scenario
— so the combinatorics get exhausted HERE as a state-machine property,
independent of any model: park-in-wave-1 vs wave-N, dependent-skip across diamond
joins, cycle -> linear-chain fallback, junk-plan -> degraded single-task path,
re-decompose fires once then budget-exhausts, integration-node red -> short
circuit, and every terminal state rendered honestly. This is where "nothing is
marked done without its verification pass" is proven.

TEST-FIRST posture (W9 builds this before/alongside W1-W5). Two halves:

* **The scenario table (`SCENARIOS`) + meta-tests — RUN TODAY.** ~30 scenario
  SPECS authored as data (name, plan-input, scripted fleet results, expected
  terminal statuses/waves/report facts, expected job verdict). The meta-tests
  keep the table SELF-CONSISTENT now (valid statuses, wave order matches the
  reference wave compiler, skip-propagation expectations match graph
  reachability, no scenario ever EXPECTS a FALSE-DONE) — so the day the driver
  lands, the expectations it is checked against are already proven sound. A few
  scenarios that only need the existing decompose/acceptance fakes run their
  mechanism live today.

* **The driver harness — green-by-SKIP today, LIVE when W1 lands.** Each
  full-pipeline test guards on ``pytest.importorskip("shared.fleet.plan_graph",
  …)`` (function-level, so the meta-tests above still run) and drives the real
  loop through the ``SwapOps`` seam. The assumed entry seam is documented at
  :func:`_resolve_pipeline_runner`; it is resolved defensively so a partial W1
  stays green-by-skip until the full seam exists, then goes live.

GPU-free, deterministic, in the standing gate (tests/integration is in scope).
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from shared.fleet.dispatch import TaskOutcome
from tools.dispatch_harness.battery import (
    TASK_STATUSES,
    compute_waves,
    validate_jobplan,
)
from tools.dispatch_harness.scorecard import VERDICT_FALSE_DONE, VERDICTS

# Terminal per-task statuses a scenario may EXPECT (the pinned JobPlan v1 set).
_TERMINAL_TASK_STATUSES = {"merged", "parked", "blocked", "skipped"}
# Categories whose plan is DELIBERATELY invalid (the ruler must reject/degrade).
_JUNK_CATEGORIES = {"cycle-fallback", "junk-plan"}
# Categories where the simple park->skip propagation rule holds (plan §4.6): a task
# is skipped iff a (transitive) dependency parked/blocked. (integration-red uses a
# different short-circuit rule and is excluded from that specific consistency check.)
_SIMPLE_PROPAGATION_CATEGORIES = {
    "park-wave-1", "park-wave-n", "diamond-skip", "independent-skip", "blocked",
}


# ---------------------------------------------------------------------------
# Scenario spec + small plan builders (keep the 30-row table readable)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ScenarioSpec:
    """One simulator scenario, authored as data (plan §9.2)."""

    name: str
    category: str
    plan: object                       # a JobPlan v1 dict, or junk (str / wrong-shape) for degrade tests
    fleet_results: dict                # task-id -> classified fleet result (MERGED/PARKED/BLOCKED/NOTHING)
    expected_task_status: dict         # task-id -> terminal JobPlan status
    expected_job_verdict: str          # GREEN | PARKED-HONEST | STALLED | RECOVERED (NEVER FALSE-DONE)
    expected_waves: list = field(default_factory=list)   # topo waves (ids), [] for junk/cyclic
    oracle_status: str = "passed"      # the job oracle result the scripted verifier returns
    expected_report_facts: tuple = ()  # substrings the JOB_SUMMARY must contain
    scripted_splits: dict = field(default_factory=dict)  # task-id -> [child (id,deps)] for re-decompose
    runnable_now: bool = False
    notes: str = ""


def _task(tid: str, deps: list[str]) -> dict:
    return {
        "id": tid,
        "prompt": f"build {tid} (self-contained instruction for the coder)",
        "depends_on": list(deps),
        "contract": {
            "creates": [f"src/{tid.replace('-', '_')}.py"],
            "exports": [f"{tid.replace('-', '_')}_entry()"],
            "notes": f"the {tid} unit",
        },
        "status": "pending",
    }


def _plan(tasks_spec: list[tuple[str, list[str]]], *, plan_id: str,
          oracle: str = "tests/test_job_acceptance.py",
          nodes: int | None = None) -> dict:
    """A minimal valid JobPlan v1 from ``[(id, [deps]), …]`` (hash NOT stamped —
    the table validates with ``check_hash=False``; these are synthetic)."""
    tasks = [_task(tid, deps) for tid, deps in tasks_spec]
    try:
        wave_count = len(compute_waves(tasks))
    except ValueError:
        wave_count = 1
    n = nodes if nodes is not None else wave_count
    return {
        "schema": "jobplan/v1",
        "plan_id": plan_id,
        "goal": f"a synthetic {plan_id} job for the L1 simulator",
        "repo": f"C:/Users/mrbla/projects/battery-{plan_id}",
        "tasks": tasks,
        "integration_nodes": [{"after_wave": i + 1, "status": "pending"} for i in range(n)],
        "job_acceptance": {"criteria": [], "oracle_path": oracle, "status": "pending"},
        "redecompose_budget": {"per_task": 1, "per_job": 2, "spent": 0},
        "plan_hash": "synthetic-unstamped",
    }


# Common chains reused across scenarios.
def _chain3(pid: str) -> dict:
    return _plan([("storage", []), ("add", ["storage"]), ("list", ["add"])], plan_id=pid)


def _diamond(pid: str) -> dict:
    return _plan([("root", []), ("left", ["root"]), ("right", ["root"]),
                 ("join", ["left", "right"])], plan_id=pid)


def _independent3(pid: str) -> dict:
    return _plan([("slugify", []), ("convert", []), ("password", [])], plan_id=pid)


_ALL_MERGED_CHAIN = {"storage": "MERGED", "add": "MERGED", "list": "MERGED"}


# ---------------------------------------------------------------------------
# The scenario table (~30) — plan §9.2's exhausted combinatorics
# ---------------------------------------------------------------------------

SCENARIOS: list[ScenarioSpec] = [
    # ---- happy paths / honest terminal rendering ----
    ScenarioSpec(
        "happy-chain-3-all-merged", "happy", _chain3("happy-chain"),
        _ALL_MERGED_CHAIN,
        {"storage": "merged", "add": "merged", "list": "merged"},
        "GREEN", expected_waves=[["storage"], ["add"], ["list"]],
        oracle_status="passed",
        expected_report_facts=("merged", "job acceptance"),
        notes="B1 shape: chain, all merged, oracle green -> GREEN.",
    ),
    ScenarioSpec(
        "happy-single-task", "single-task",
        _plan([("build-it", [])], plan_id="happy-single"),
        {"build-it": "MERGED"},
        {"build-it": "merged"},
        "GREEN", expected_waves=[["build-it"]],
        expected_report_facts=("merged",),
        notes="Degenerate graph == one task == today's serial behavior; still oracle-gated.",
    ),
    ScenarioSpec(
        "happy-independent-3-all-merged", "happy", _independent3("happy-indep"),
        {"slugify": "MERGED", "convert": "MERGED", "password": "MERGED"},
        {"slugify": "merged", "convert": "merged", "password": "merged"},
        "GREEN", expected_waves=[["convert", "password", "slugify"]],
        expected_report_facts=("merged",),
        notes="B7 shape: 3 independent units, one wave, all merged.",
    ),
    ScenarioSpec(
        "happy-diamond-all-merged", "happy", _diamond("happy-diamond"),
        {"root": "MERGED", "left": "MERGED", "right": "MERGED", "join": "MERGED"},
        {"root": "merged", "left": "merged", "right": "merged", "join": "merged"},
        "GREEN", expected_waves=[["root"], ["left", "right"], ["join"]],
        expected_report_facts=("merged",),
        notes="Diamond fan-in, all merged -> GREEN.",
    ),

    # ---- park in wave 1 (foundation dies -> everything downstream skips) ----
    ScenarioSpec(
        "park-wave1-foundation", "park-wave-1", _chain3("park-w1"),
        {"storage": "PARKED"},
        {"storage": "parked", "add": "skipped", "list": "skipped"},
        "PARKED-HONEST", expected_waves=[["storage"], ["add"], ["list"]],
        oracle_status="not-run",
        expected_report_facts=("storage", "parked", "skipped"),
        notes="Foundational task parks in wave 1 -> both dependents skip; job NOT done.",
    ),
    ScenarioSpec(
        "park-wave1-diamond-root", "diamond-skip", _diamond("park-w1-diamond"),
        {"root": "PARKED"},
        {"root": "parked", "left": "skipped", "right": "skipped", "join": "skipped"},
        "PARKED-HONEST", expected_waves=[["root"], ["left", "right"], ["join"]],
        oracle_status="not-run",
        expected_report_facts=("root", "parked", "skipped"),
        notes="Diamond root parks -> the whole diamond skips.",
    ),

    # ---- park in wave N ----
    ScenarioSpec(
        "park-waveN-leaf", "park-wave-n", _chain3("park-wn-leaf"),
        {"storage": "MERGED", "add": "MERGED", "list": "PARKED"},
        {"storage": "merged", "add": "merged", "list": "parked"},
        "PARKED-HONEST", expected_waves=[["storage"], ["add"], ["list"]],
        oracle_status="not-run",
        expected_report_facts=("list", "parked"),
        notes="Last task parks -> earlier merges kept, job NOT done (honest).",
    ),
    ScenarioSpec(
        "park-waveN-mid", "park-wave-n", _chain3("park-wn-mid"),
        {"storage": "MERGED", "add": "PARKED"},
        {"storage": "merged", "add": "parked", "list": "skipped"},
        "PARKED-HONEST", expected_waves=[["storage"], ["add"], ["list"]],
        oracle_status="not-run",
        expected_report_facts=("add", "parked", "list", "skipped"),
        notes="Mid-chain park -> only the downstream leaf skips.",
    ),

    # ---- diamond skip propagation ----
    ScenarioSpec(
        "diamond-one-arm-parks", "diamond-skip", _diamond("diamond-1arm"),
        {"root": "MERGED", "left": "PARKED", "right": "MERGED"},
        {"root": "merged", "left": "parked", "right": "merged", "join": "skipped"},
        "PARKED-HONEST", expected_waves=[["root"], ["left", "right"], ["join"]],
        oracle_status="not-run",
        expected_report_facts=("left", "parked", "join", "skipped"),
        notes="One diamond arm parks -> the join (needs both) skips; the other arm still merges.",
    ),
    ScenarioSpec(
        "diamond-join-parks", "diamond-skip", _diamond("diamond-join"),
        {"root": "MERGED", "left": "MERGED", "right": "MERGED", "join": "PARKED"},
        {"root": "merged", "left": "merged", "right": "merged", "join": "parked"},
        "PARKED-HONEST", expected_waves=[["root"], ["left", "right"], ["join"]],
        oracle_status="not-run",
        expected_report_facts=("join", "parked"),
        notes="All arms merge but the join parks -> job NOT done, nothing to skip.",
    ),

    # ---- independent branch skip isolation ----
    ScenarioSpec(
        "independent-one-parks", "independent-skip", _independent3("indep-1parks"),
        {"slugify": "MERGED", "convert": "PARKED", "password": "MERGED"},
        {"slugify": "merged", "convert": "parked", "password": "merged"},
        "PARKED-HONEST", expected_waves=[["convert", "password", "slugify"]],
        oracle_status="not-run",
        expected_report_facts=("convert", "parked"),
        notes="One independent branch parks -> the other two are unaffected (skip isolation).",
    ),

    # ---- cycle -> linear-chain fallback (today's semantics) ----
    ScenarioSpec(
        "cycle-two-node-fallback", "cycle-fallback",
        _plan([("a", ["b"]), ("b", ["a"])], plan_id="cycle-2", nodes=1),
        {"a": "MERGED", "b": "MERGED"},
        {"a": "merged", "b": "merged"},
        "GREEN", expected_waves=[],
        oracle_status="passed",
        expected_report_facts=("linear", "fallback"),
        notes="A<->B cycle -> ruler breaks edges to a linear chain (today's exact behavior); "
              "degradation is LOGGED, not hidden. Fleet merges both -> GREEN on the chain.",
    ),
    ScenarioSpec(
        "cycle-self-loop-fallback", "cycle-fallback",
        _plan([("solo", ["solo"])], plan_id="cycle-self", nodes=1),
        {"solo": "MERGED"},
        {"solo": "merged"},
        "GREEN", expected_waves=[],
        oracle_status="passed",
        expected_report_facts=("linear", "fallback"),
        notes="Self-dependency -> edge dropped -> single task; degradation logged.",
    ),

    # ---- junk plan -> degraded single-task path ----
    ScenarioSpec(
        "junk-malformed-not-a-dict", "junk-plan",
        "this is not a plan at all — the 14B truncated mid-stream",
        {"build-it": "MERGED"},
        {"build-it": "merged"},
        "GREEN", expected_waves=[],
        oracle_status="passed",
        expected_report_facts=("fallback", "single"),
        notes="Unparseable/non-object plan -> deterministic fallback to ONE validated task "
              "(the goal as the prompt); never zero work, never a crash.",
    ),
    ScenarioSpec(
        "junk-wrong-shape-tasks", "junk-plan",
        {"schema": "jobplan/v1", "plan_id": "junk-shape", "goal": "g",
         "repo": "C:/Users/mrbla/projects/battery-junk", "tasks": {"not": "a list"},
         "integration_nodes": [], "job_acceptance": {"criteria": [], "oracle_path": "x", "status": "pending"},
         "redecompose_budget": {"per_task": 1, "per_job": 2, "spent": 0}, "plan_hash": "x"},
        {"build-it": "MERGED"},
        {"build-it": "merged"},
        "GREEN", expected_waves=[],
        oracle_status="passed",
        expected_report_facts=("fallback",),
        notes="Schema-valid JSON, wrong shape (tasks not a list) -> ruler rejects -> single-task degrade.",
    ),
    ScenarioSpec(
        "junk-model-prose-no-array", "junk-plan",
        "Sure! Here's how I'd approach it: first the storage, then the commands. "
        "Let me know if you'd like me to elaborate!",
        {"build-it": "MERGED"},
        {"build-it": "merged"},
        "GREEN", expected_waves=[],
        oracle_status="passed",
        expected_report_facts=("fallback",),
        runnable_now=True,
        notes="Model prose with no JSON array -> zero candidates -> single-task fallback. "
              "runnable_now: the mechanism is exercised against the REAL decompose parser today.",
    ),

    # ---- re-decomposition (bounded) ----
    ScenarioSpec(
        "redecompose-once-then-park", "redecompose", _chain3("redecomp-park"),
        {"storage": "MERGED", "add": "PARKED", "list": "skip"},
        {"storage": "merged", "add": "parked", "list": "skipped"},
        "PARKED-HONEST", expected_waves=[["storage"], ["add"], ["list"]],
        oracle_status="not-run",
        scripted_splits={"add": [("add-core", ["storage"]), ("add-validate", ["add-core"])]},
        expected_report_facts=("re-decompose", "budget", "parked"),
        notes="N4: 'add' fails identically; per_task budget=1 -> ONE evidence-fed re-decompose "
              "into 2 children that ALSO fail -> budget exhausts -> subtree parks. Exactly one split.",
    ),
    ScenarioSpec(
        "redecompose-once-then-succeed", "redecompose", _chain3("redecomp-win"),
        {"storage": "MERGED", "add": "PARKED-THEN-CHILDREN-MERGE", "list": "MERGED"},
        {"storage": "merged", "add": "merged", "list": "merged"},
        "GREEN", expected_waves=[["storage"], ["add"], ["list"]],
        oracle_status="passed",
        scripted_splits={"add": [("add-core", ["storage"]), ("add-validate", ["add-core"])]},
        expected_report_facts=("re-decompose",),
        notes="Re-decompose RECOVERS: 'add' fails once, its 2 children both merge -> subtree completes "
              "-> job GREEN. Proves the bound helps, not just parks.",
    ),
    ScenarioSpec(
        "redecompose-per-job-budget-exhausts", "redecompose",
        _plan([("a", []), ("b", []), ("c", [])], plan_id="redecomp-jobbudget", nodes=1),
        {"a": "PARKED", "b": "PARKED", "c": "PARKED"},
        {"a": "parked", "b": "parked", "c": "parked"},
        "PARKED-HONEST", expected_waves=[["a", "b", "c"]],
        oracle_status="not-run",
        scripted_splits={"a": [("a1", [])], "b": [("b1", [])], "c": [("c1", [])]},
        expected_report_facts=("budget", "per_job"),
        notes="Three tasks fail; per_job budget=2 allows TWO re-decomposes; the third gets none "
              "and parks directly. The job-level budget is the hard stop.",
    ),

    # ---- integration node red -> short-circuit ----
    ScenarioSpec(
        "integration-red-wave1-shortcircuit", "integration-red", _chain3("intred-w1"),
        {"storage": "MERGED"},
        {"storage": "merged", "add": "skipped", "list": "skipped"},
        "PARKED-HONEST", expected_waves=[["storage"], ["add"], ["list"]],
        oracle_status="not-run",
        expected_report_facts=("integration", "wave 1", "skipped"),
        notes="N1: wave-1 integration gate on the merged tree goes RED (a contract break) -> later "
              "waves NEVER run; downstream skipped; the report names the break. Catch-at-the-join.",
    ),
    ScenarioSpec(
        "integration-red-waveN", "integration-red", _chain3("intred-wn"),
        {"storage": "MERGED", "add": "MERGED"},
        {"storage": "merged", "add": "merged", "list": "skipped"},
        "PARKED-HONEST", expected_waves=[["storage"], ["add"], ["list"]],
        oracle_status="not-run",
        expected_report_facts=("integration", "skipped"),
        notes="Wave-2 gate red after wave-1 merged -> wave-3 short-circuited.",
    ),

    # ---- job-level oracle (the finish line) ----
    ScenarioSpec(
        "job-oracle-red-despite-all-merged", "job-oracle", _chain3("joboracle-red"),
        _ALL_MERGED_CHAIN,
        {"storage": "merged", "add": "merged", "list": "merged"},
        "PARKED-HONEST", expected_waves=[["storage"], ["add"], ["list"]],
        oracle_status="failed",
        expected_report_facts=("job", "oracle", "not"),
        notes="N2: every task merged + its OWN unit tests green, but the job-level spec-blind oracle "
              "FAILS on the integrated tree -> job ends NOT-done. A GREEN here would be a FALSE-DONE. "
              "unit-green is distinguished from job-red in the report.",
    ),
    ScenarioSpec(
        "job-oracle-green-is-the-gate", "job-oracle", _chain3("joboracle-green"),
        _ALL_MERGED_CHAIN,
        {"storage": "merged", "add": "merged", "list": "merged"},
        "GREEN", expected_waves=[["storage"], ["add"], ["list"]],
        oracle_status="passed",
        expected_report_facts=("job", "oracle", "pass"),
        notes="The finish line: all merged AND the job oracle passes on the integrated tree -> GREEN.",
    ),
    ScenarioSpec(
        "job-oracle-unrun-is-not-green", "job-oracle", _chain3("joboracle-unrun"),
        _ALL_MERGED_CHAIN,
        {"storage": "merged", "add": "merged", "list": "merged"},
        "STALLED", expected_waves=[["storage"], ["add"], ["list"]],
        oracle_status="not-run",
        expected_report_facts=("oracle", "not", "run"),
        notes="All merged but the job oracle never RAN -> must NOT report GREEN. 'merged but "
              "unverifiable' is exactly the FALSE-DONE class; honest verdict is STALLED/not-done.",
    ),

    # ---- protected-oracle tamper (restore-before-grading) ----
    ScenarioSpec(
        "oracle-tamper-restore-then-grade", "oracle-tamper", _chain3("oracle-tamper"),
        _ALL_MERGED_CHAIN,
        {"storage": "merged", "add": "merged", "list": "merged"},
        "GREEN", expected_waves=[["storage"], ["add"], ["list"]],
        oracle_status="passed",
        expected_report_facts=("oracle", "restore"),
        notes="N3: a task edits the protected oracle file -> restore-before-grading -> grading runs "
              "against the ORIGINAL. Here the code genuinely passes the original -> GREEN, tamper noted.",
    ),

    # ---- secret-scan blocked (N8) ----
    ScenarioSpec(
        "blocked-secret-scan", "blocked", _chain3("blocked-secret"),
        {"storage": "MERGED", "add": "BLOCKED"},
        {"storage": "merged", "add": "blocked", "list": "skipped"},
        "PARKED-HONEST", expected_waves=[["storage"], ["add"], ["list"]],
        oracle_status="not-run",
        expected_report_facts=("add", "blocked", "list", "skipped"),
        notes="N8: a planted credential trips gitleaks fail-closed -> 'add' parks BLOCKED, its "
              "dependent skips, the report says BLOCKED honestly. Inherited control, job-level lock.",
    ),

    # ---- recovered (crash path worked) ----
    ScenarioSpec(
        "recovered-swap-failed-then-restored", "recovered", _chain3("recovered"),
        _ALL_MERGED_CHAIN,
        {"storage": "merged", "add": "merged", "list": "merged"},
        "RECOVERED", expected_waves=[["storage"], ["add"], ["list"]],
        oracle_status="passed",
        expected_report_facts=("recovered",),
        notes="Tasks merge but the 14B swap-back initially fails then recovers (RECOVERED phase). "
              "The crash path is a first-class verdict; the work is not lost.",
    ),

    # ---- stalled (watchdog had to kill -> harness fault, not capability) ----
    ScenarioSpec(
        "stalled-watchdog-kill", "stalled", _chain3("stalled"),
        {"storage": "MERGED", "add": "HANG"},
        {"storage": "merged", "add": "building", "list": "pending"},
        "STALLED", expected_waves=[["storage"], ["add"], ["list"]],
        oracle_status="not-run",
        expected_report_facts=("stalled", "watchdog"),
        notes="'add' hangs -> the budget watchdog tree-kills the run -> STALLED (a HARNESS fault, "
              "never scored as a capability datum). Resumable by design.",
    ),

    # ---- context pack consumed (S2 property in-pipeline) ----
    ScenarioSpec(
        "context-pack-consumed-by-dependent", "context-pack",
        _plan([("storage", []), ("add", ["storage"])], plan_id="ctxpack"),
        {"storage": "MERGED", "add": "MERGED"},
        {"storage": "merged", "add": "merged"},
        "GREEN", expected_waves=[["storage"], ["add"]],
        oracle_status="passed",
        expected_report_facts=("context pack", "storage"),
        notes="'add' depends on 'storage' -> at enqueue time a context pack is assembled from "
              "storage's contract (paths + export signatures ONLY, no free text) and appended to "
              "add's prompt, and logged. Proves the pack is CONSUMED (plan §3.2 DoD) + the S2 "
              "structural-only property inside the live pipeline.",
    ),

    # ---- additive-knob invariant: plan_graph OFF == today's flat queue ----
    ScenarioSpec(
        "plan-graph-off-byte-identical", "degrade-off", _chain3("knob-off"),
        _ALL_MERGED_CHAIN,
        {"storage": "merged", "add": "merged", "list": "merged"},
        "GREEN", expected_waves=[["storage"], ["add"], ["list"]],
        oracle_status="passed",
        expected_report_facts=("merged",),
        notes="With [fleet_dispatch].plan_graph OFF the driver reproduces today's flat serial queue "
              "byte-identically (no waves, no packs, no job oracle) — the §4.1.5 additive-knob "
              "invariant. The scheduler path is exercised only when the knob is ON.",
    ),
]


# ---------------------------------------------------------------------------
# Scripted fakes — the SwapOps steering wheel (built against the REAL seams)
# ---------------------------------------------------------------------------


def _scripted_run_task(fleet_results: dict):
    """A ``run_task(task)->TaskOutcome`` fake keyed by task id (the real ``SwapOps.run_task``
    shape). Unmapped tasks default to MERGED so a scenario only scripts the interesting ones.

    Rig-grammar convention (§9.2 — the steering channel the base signature cannot carry):
    the ``result`` field stays the standard classification the driver branches on
    (MERGED/PARKED/BLOCKED/NOTHING), while the RAW scripted code rides VERBATIM in the
    outcome ``detail`` (``code=<code>``). That lets the simulator act on the codes the
    author encoded but the standard classification collapses — ``HANG`` (a wedged task
    the budget watchdog must tree-kill) and ``PARKED-THEN-CHILDREN-MERGE`` (a task that
    parks once then its evidence-fed re-decomposition succeeds). The code rides the fleet
    RESULT line, which is exactly the failing-evidence surface the real re-decompose reads."""

    def run_task(task: dict) -> TaskOutcome:
        tid = str(task.get("task") or task.get("id") or "")
        code = fleet_results.get(tid, "MERGED")
        result = code if code in {"MERGED", "PARKED", "BLOCKED", "NOTHING"} else "PARKED"
        return TaskOutcome(task=tid, outcome="processed", result=result,
                           detail=f"RESULT: {result} (scripted; code={code})")

    return run_task


def _scripted_generate_fn(scripted_splits: dict):
    """A ``generate_fn(prompt)->str`` fake: returns a scripted JSON split when the
    re-decompose ('go finer') template is seen, else empty (no proposal).

    Fires on EITHER a prompt that already names a scripted child id (the direct
    ``dc.split_failed_task`` shape the meta-test uses) OR the simulator's re-decompose
    marker ``[[redecompose:<parent-id>]]`` (§9.2 rig grammar — the real
    ``_SPLIT_TEMPLATE`` prompt is built from the FAILED task's text, which cannot name
    children the model has not proposed yet, so the simulator injects the marker keyed on
    the parent id to trigger the scripted split)."""
    import json as _json

    def generate_fn(prompt: str) -> str:
        for tid, children in scripted_splits.items():
            if children and (f"[[redecompose:{tid}]]" in prompt
                             or any(cid in prompt for cid, _ in children)):
                return _json.dumps([{"task": cid, "prompt": f"build {cid}"} for cid, _ in children])
        return ""

    return generate_fn


# ---------------------------------------------------------------------------
# Meta-tests over the scenario TABLE — RUN TODAY (keep it self-consistent)
# ---------------------------------------------------------------------------


def test_scenario_table_has_roughly_thirty_scenarios():
    assert len(SCENARIOS) >= 28, f"expected ~30 scenarios, have {len(SCENARIOS)}"


def test_scenario_names_are_unique():
    names = [s.name for s in SCENARIOS]
    assert len(names) == len(set(names))


def test_scenario_table_covers_every_required_category():
    required = {
        "happy", "single-task", "park-wave-1", "park-wave-n", "diamond-skip",
        "independent-skip", "cycle-fallback", "junk-plan", "redecompose",
        "integration-red", "job-oracle", "oracle-tamper", "blocked", "recovered",
        "stalled", "context-pack", "degrade-off",
    }
    present = {s.category for s in SCENARIOS}
    assert required <= present, f"missing categories: {sorted(required - present)}"


def test_no_scenario_ever_expects_a_false_done():
    """The zero-tolerance invariant at the spec level: FALSE-DONE is only ever a
    DETECTED failure, never an EXPECTED outcome. A scenario that expected one would
    be encoding the unforgivable result as normal."""
    for s in SCENARIOS:
        assert s.expected_job_verdict != VERDICT_FALSE_DONE, s.name
        assert s.expected_job_verdict in VERDICTS, f"{s.name}: {s.expected_job_verdict}"


def test_expected_task_statuses_are_valid_vocabulary():
    for s in SCENARIOS:
        for tid, status in s.expected_task_status.items():
            assert status in TASK_STATUSES, f"{s.name}: {tid} -> {status}"


def test_non_junk_plans_are_wellformed_and_junk_plans_are_rejected():
    for s in SCENARIOS:
        if s.category in _JUNK_CATEGORIES:
            errors = validate_jobplan(s.plan, check_hash=False) if isinstance(s.plan, dict) \
                else ["not a dict"]
            assert errors, f"{s.name} is tagged junk/cyclic but validates clean"
        else:
            assert isinstance(s.plan, dict), s.name
            errors = validate_jobplan(s.plan, check_hash=False)
            assert not errors, f"{s.name} should be well-formed but: {errors}"


def test_expected_waves_match_the_reference_wave_compiler():
    """For every acyclic non-junk plan, the declared expected_waves must equal what
    the reference wave compiler produces — so the table's wave expectations are
    provably correct BEFORE the driver is checked against them."""
    for s in SCENARIOS:
        if s.category in _JUNK_CATEGORIES or not s.expected_waves:
            continue
        got = compute_waves(s.plan["tasks"])
        assert got == s.expected_waves, f"{s.name}: waves {got} != declared {s.expected_waves}"


def test_fleet_results_reference_real_tasks_for_graph_plans():
    for s in SCENARIOS:
        if not isinstance(s.plan, dict) or not isinstance(s.plan.get("tasks"), list):
            continue
        ids = {t["id"] for t in s.plan["tasks"]}
        # scripted splits may introduce child ids; the base result keys must be real
        # task ids OR child ids from a scripted split (re-decompose replacement).
        child_ids = {cid for children in s.scripted_splits.values() for cid, _ in children}
        for tid in s.fleet_results:
            assert tid in ids or tid in child_ids, f"{s.name}: fleet result for unknown '{tid}'"


def test_skip_propagation_expectations_match_graph_reachability():
    """The table's SKIP expectations must equal graph reachability from the failed
    tasks (plan §4.6: a task skips iff a transitive dependency parked/blocked). This
    is the mutation-resistant core: if someone later mis-edits an expected status,
    this fails — the scenarios cannot silently drift from the propagation rule they
    are supposed to prove."""
    for s in SCENARIOS:
        if s.category not in _SIMPLE_PROPAGATION_CATEGORIES:
            continue
        tasks = s.plan["tasks"]
        deps = {t["id"]: set(t["depends_on"]) for t in tasks}
        failed = {tid for tid, st in s.expected_task_status.items()
                  if st in {"parked", "blocked"}}
        # Transitive dependents of any failed task must be exactly the 'skipped' set.
        expected_skipped = set()
        changed = True
        dead = set(failed)
        while changed:
            changed = False
            for tid, d in deps.items():
                if tid not in dead and (d & dead):
                    dead.add(tid)
                    expected_skipped.add(tid)
                    changed = True
        declared_skipped = {tid for tid, st in s.expected_task_status.items()
                            if st == "skipped"}
        assert declared_skipped == expected_skipped, (
            f"{s.name}: declared skipped {declared_skipped} != reachable-from-failed "
            f"{expected_skipped}"
        )


def test_report_facts_present_for_non_happy_scenarios():
    """Every scenario that isn't a plain happy/merge path must declare at least one
    JOB_SUMMARY fact to assert — a terminal state we never check the RENDER of is
    exactly the theater plan §9 forbids."""
    for s in SCENARIOS:
        if s.category in {"happy", "single-task", "degrade-off"}:
            continue
        assert s.expected_report_facts, f"{s.name} declares no report facts to verify"


# ---------------------------------------------------------------------------
# Runnable-NOW mechanism proofs (no plan_graph) — the scripted fakes are sound
# ---------------------------------------------------------------------------


def test_now_scripted_fleet_fake_returns_taskoutcomes():
    run_task = _scripted_run_task({"storage": "PARKED", "add": "BLOCKED"})
    assert run_task({"task": "storage"}).result == "PARKED"
    assert run_task({"task": "add"}).result == "BLOCKED"
    assert run_task({"task": "list"}).result == "MERGED"  # default


def test_now_scripted_generate_fn_returns_split_json_on_go_finer():
    import json as _json

    gen = _scripted_generate_fn({"add": [("add-core", []), ("add-validate", [])]})
    out = gen("please split add-core into steps")
    assert _json.loads(out)[0]["task"] == "add-core"
    assert gen("unrelated prompt") == ""


def test_now_junk_prose_degrades_through_the_real_decompose_parser(tmp_path):
    """The 'junk-model-prose-no-array' scenario's mechanism, exercised against the
    REAL decompose_request today: prose in -> single-task fallback out, never a
    crash, never zero work. When W1 lands this same scenario runs through the full
    pipeline; today it proves the degrade path it depends on already holds."""
    from shared.fleet.decompose import decompose_request

    repo = tmp_path / "battery-junk"
    repo.mkdir()
    (repo / ".git").mkdir()
    # The scenario's plan-input IS model prose (no JSON array); feed it as the fake
    # 14B's output and confirm the real ruler degrades to a single validated task.
    scenario = next(s for s in SCENARIOS if s.name == "junk-model-prose-no-array")
    prose = scenario.plan
    assert isinstance(prose, str)
    result = decompose_request(
        "a small budgeting tool",
        "battery-junk",
        generate_fn=lambda _prompt: prose,
        projects_dir=tmp_path,
    )
    assert result.ok and result.fell_back and len(result.tasks) == 1


# ---------------------------------------------------------------------------
# The full-pipeline driver harness — green-by-SKIP today, LIVE when W1 lands
# ---------------------------------------------------------------------------


def _resolve_pipeline_runner(plan_graph):
    """Resolve the ASSUMED W1 simulator seam, or skip with a clear reason.

    The assumed entry point (documented here so Lane A/W1 can match or supersede
    it): a callable that drives one JobPlan through the real wave scheduler with
    injected fakes and returns a result object exposing ``task_status`` (dict),
    ``waves`` (list[list[str]]), ``job_verdict`` (str), and ``summary`` (str)::

        run_job_plan(plan: dict, *, run_task, generate_fn,
                     oracle_status="passed", plan_graph_enabled=True) -> Result

    Resolved defensively: if plan_graph is present but this seam is not wired yet
    (a partial W1), we SKIP rather than fail — the suite stays green-by-skip until
    the full seam exists, then goes live. Names tried, in order:
    ``simulate_job_plan``, ``run_job_plan``, ``JobPlanSimulator`` (``.run``)."""
    for attr in ("simulate_job_plan", "run_job_plan"):
        fn = getattr(plan_graph, attr, None)
        if callable(fn):
            return fn
    sim = getattr(plan_graph, "JobPlanSimulator", None)
    if sim is not None and hasattr(sim, "run"):
        return lambda plan, **kw: sim(**kw).run(plan)
    pytest.skip(
        "shared.fleet.plan_graph is importable but the L1 simulator seam "
        "(simulate_job_plan / run_job_plan / JobPlanSimulator.run) is not wired yet — "
        "W1/W3/W4/W5 pending; this scenario goes live when the seam lands."
    )


@pytest.mark.parametrize("scenario", SCENARIOS, ids=[s.name for s in SCENARIOS])
def test_pipeline_scenario(scenario: ScenarioSpec):
    """Drive one scenario through the REAL plan-graph driver loop with scripted
    fakes and assert the terminal statuses, waves, job verdict, and honest report
    render. Green-by-SKIP until W1's ``shared.fleet.plan_graph`` lands."""
    plan_graph = pytest.importorskip(
        "shared.fleet.plan_graph",
        reason="W1 pending — the plan-graph driver does not exist yet; flip live when Lane A merges.",
    )
    run = _resolve_pipeline_runner(plan_graph)

    result = run(
        scenario.plan,
        run_task=_scripted_run_task(scenario.fleet_results),
        generate_fn=_scripted_generate_fn(scenario.scripted_splits),
        oracle_status=scenario.oracle_status,
        plan_graph_enabled=(scenario.category != "degrade-off"),
    )

    # Terminal per-task statuses (evidence-gated transitions, plan §4.3).
    task_status = dict(getattr(result, "task_status", {}) or {})
    for tid, expected in scenario.expected_task_status.items():
        assert task_status.get(tid) == expected, (
            f"{scenario.name}: task '{tid}' -> {task_status.get(tid)}, expected {expected}"
        )

    # Wave order (topological), when the scenario declares it.
    if scenario.expected_waves:
        assert list(getattr(result, "waves", [])) == scenario.expected_waves, scenario.name

    # The job verdict — and the FALSE-DONE tripwire: a scenario that expects a
    # non-GREEN must NEVER come back GREEN (that would be the unforgivable outcome).
    verdict = getattr(result, "job_verdict", "")
    assert verdict == scenario.expected_job_verdict, (
        f"{scenario.name}: verdict {verdict}, expected {scenario.expected_job_verdict}"
    )
    if scenario.expected_job_verdict != "GREEN":
        assert verdict != "GREEN", f"{scenario.name}: FALSE-DONE — reported GREEN when not done"

    # Honest report rendering — every declared terminal fact must appear.
    summary = (getattr(result, "summary", "") or "").lower()
    for fact in scenario.expected_report_facts:
        assert fact.lower() in summary, f"{scenario.name}: report missing '{fact}'"


def _run_scenario(run, scenario: ScenarioSpec):
    return run(
        scenario.plan,
        run_task=_scripted_run_task(scenario.fleet_results),
        generate_fn=_scripted_generate_fn(scenario.scripted_splits),
        oracle_status=scenario.oracle_status,
        plan_graph_enabled=(scenario.category != "degrade-off"),
    )


def test_simulator_rides_the_real_orchestration_primitives(monkeypatch):
    """Anti-parallel-impl proof: the simulator drives the REAL plan-graph orchestration,
    not a private reimplementation. Break a real primitive and a scenario's outcome MUST
    change — a harness that keeps passing when the real logic is broken is theater
    (plan §9 R3: 'a bug in the harness itself gives false confidence').

    We break two load-bearing primitives:

    * ``plan_graph.mark_merged`` — the evidence-gated done transition the driver calls
      as ``pg.mark_merged``. No-op it and an all-merged happy chain can no longer report
      ``merged``/GREEN (it goes STALLED — a task frozen mid-build).
    * ``swap_driver.compute_job_verdict`` — the §9.4 verdict function. Force it GREEN and
      a PARKED-HONEST scenario would (wrongly) report GREEN, proving ``result.job_verdict``
      comes from the real verdict logic (the FALSE-DONE tripwire's actual teeth)."""
    plan_graph = pytest.importorskip("shared.fleet.plan_graph")
    run = _resolve_pipeline_runner(plan_graph)

    happy = next(s for s in SCENARIOS if s.name == "happy-chain-3-all-merged")
    base = _run_scenario(run, happy)
    assert base.job_verdict == "GREEN"
    assert base.task_status.get("storage") == "merged"

    # Break the REAL evidence-gated merge transition -> the happy chain cannot be GREEN.
    monkeypatch.setattr(plan_graph, "mark_merged", lambda plan, task_id, evidence: plan)
    broken = _run_scenario(run, happy)
    assert broken.job_verdict != "GREEN", "simulator ignored the real mark_merged (parallel impl?)"
    assert broken.task_status.get("storage") != "merged"

    # Force the REAL verdict function GREEN -> a refusal scenario wrongly reports GREEN,
    # proving result.job_verdict is the real compute_job_verdict, not a local recomputation.
    park = next(s for s in SCENARIOS if s.name == "park-wave1-foundation")
    monkeypatch.setattr("shared.fleet.swap_driver.compute_job_verdict",
                        lambda *a, **k: ("GREEN", ""))
    forced = _run_scenario(run, park)
    assert forced.job_verdict == "GREEN", "simulator did not ride the real compute_job_verdict"
