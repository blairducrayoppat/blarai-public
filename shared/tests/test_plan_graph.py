"""Tests for plan_graph — the JobPlan v1 ruler, wave compiler, evidence-gated status
machine, and PlanStore (M2 W1, #740).

Pure/deterministic throughout (no model, no GPU). The N7 security fixtures (plan §10.2)
live here too: path-traversal repo target, shell-metacharacter slugs, oversized plans,
and on-disk tamper of the persisted artifact.
"""

from __future__ import annotations

import json

import pytest

from shared.fleet import plan_graph as pg
from shared.fleet.dispatch import FleetDispatchConfig, build_default_config


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _projects(tmp_path):
    proj = tmp_path / "projects"
    (proj / "myapp" / ".git").mkdir(parents=True, exist_ok=True)  # idempotent per test
    return proj


def _repo(tmp_path) -> str:
    return str(_projects(tmp_path) / "myapp")


def _raw_plan(repo: str, tasks: list[dict], **overrides) -> dict:
    raw = {
        "schema": "jobplan/v1",
        "plan_id": "20260705-test",
        "goal": "a budget tracker",
        "repo": repo,
        "tasks": tasks,
        "integration_nodes": [],
        "job_acceptance": {"criteria": [], "oracle_path": "tests/test_job_acceptance.py",
                           "status": "pending"},
        "redecompose_budget": {"per_task": 1, "per_job": 2, "spent": 0},
        "plan_hash": "",
    }
    raw.update(overrides)
    return raw


def _task(tid: str, deps: list[str] | None = None, **extra) -> dict:
    t = {"id": tid, "prompt": f"build {tid}", "depends_on": deps or []}
    t.update(extra)
    return t


def _diamond(repo: str) -> dict:
    """storage -> {add, list} -> report."""
    return _raw_plan(repo, [
        _task("storage"),
        _task("add-cmd", ["storage"]),
        _task("list-cmd", ["storage"]),
        _task("report", ["add-cmd", "list-cmd"]),
    ])


# ---------------------------------------------------------------------------
# validate_plan — schema shapes and refusals
# ---------------------------------------------------------------------------


def test_valid_diamond_plan_validates(tmp_path):
    proj = _projects(tmp_path)
    res = pg.validate_plan(_diamond(str(proj / "myapp")), projects_dir=proj)
    assert res.ok and not res.degraded and res.plan is not None
    assert [t.id for t in res.plan.tasks] == ["storage", "add-cmd", "list-cmd", "report"]
    assert res.plan.tasks[3].depends_on == ["add-cmd", "list-cmd"]
    assert all(t.status == "pending" for t in res.plan.tasks)


def test_non_dict_plan_refused(tmp_path):
    res = pg.validate_plan(["not", "a", "plan"], projects_dir=_projects(tmp_path))
    assert not res.ok and res.plan is None and "not a JSON object" in res.reason


def test_unknown_schema_refused(tmp_path):
    proj = _projects(tmp_path)
    raw = _diamond(str(proj / "myapp"))
    raw["schema"] = "jobplan/v99"
    res = pg.validate_plan(raw, projects_dir=proj)
    assert not res.ok and "schema" in res.reason


def test_missing_repo_refused(tmp_path):
    proj = _projects(tmp_path)
    res = pg.validate_plan(_raw_plan("", [_task("a")]), projects_dir=proj)
    assert not res.ok and "repo" in res.reason


def test_zero_tasks_refused(tmp_path):
    proj = _projects(tmp_path)
    res = pg.validate_plan(_raw_plan(str(proj / "myapp"), []), projects_dir=proj)
    assert not res.ok and "no tasks" in res.reason


def test_all_tasks_unusable_refused(tmp_path):
    proj = _projects(tmp_path)
    raw = _raw_plan(str(proj / "myapp"), [{"id": "", "prompt": ""}, "not a dict", {"id": "x"}])
    res = pg.validate_plan(raw, projects_dir=proj)
    assert not res.ok and "no usable tasks" in res.reason


# ---------------------------------------------------------------------------
# N7 — repo containment (path traversal / forbidden roots / non-git)
# ---------------------------------------------------------------------------


def test_n7_path_traversal_repo_refused(tmp_path):
    # A repo path that resolves OUTSIDE the projects dir must refuse — nothing
    # executes outside projects_dir (plan §10 S1).
    proj = _projects(tmp_path)
    outside = tmp_path / "evil"
    (outside / ".git").mkdir(parents=True)
    traversal = str(proj / "myapp" / ".." / ".." / "evil")
    res = pg.validate_plan(_raw_plan(traversal, [_task("a")]), projects_dir=proj)
    assert not res.ok and "refused" in res.reason


def test_n7_forbidden_root_refused(tmp_path):
    # A plan targeting a BlarAI tree refuses even if someone nests it under projects.
    proj = _projects(tmp_path)
    blar = proj / "BlarAI" / "sub"
    (blar / ".git").mkdir(parents=True)
    res = pg.validate_plan(_raw_plan(str(blar), [_task("a")]), projects_dir=proj)
    assert not res.ok and "refused" in res.reason


def test_non_git_repo_refused(tmp_path):
    proj = _projects(tmp_path)
    (proj / "plaindir").mkdir()
    res = pg.validate_plan(_raw_plan(str(proj / "plaindir"), [_task("a")]), projects_dir=proj)
    assert not res.ok


# ---------------------------------------------------------------------------
# N7 — slug neutralization + oversized-plan cap
# ---------------------------------------------------------------------------


def test_n7_shell_metacharacter_task_id_neutralized(tmp_path):
    # No plan field ever reaches a shell un-slugified (review criterion): ids are
    # slugified, so metacharacters cannot survive into branch/worktree/process args.
    proj = _projects(tmp_path)
    hostile = 'rm -rf ~; $(curl evil) && `reboot` | "quoted"'
    raw = _raw_plan(str(proj / "myapp"), [{"id": hostile, "prompt": "p"}])
    res = pg.validate_plan(raw, projects_dir=proj)
    assert res.ok
    slug = res.plan.tasks[0].id
    assert not set(slug) & set(' ;$()&`|"~\\'), slug
    assert slug == "rm-rf-curl-evil-reboot-quoted"


def test_n7_oversized_plan_capped(tmp_path):
    proj = _projects(tmp_path)
    tasks = [_task(f"t{i}") for i in range(20)]
    res = pg.validate_plan(_raw_plan(str(proj / "myapp"), tasks), projects_dir=proj,
                           max_tasks=8)
    assert res.ok and len(res.plan.tasks) == 8
    assert any("capped" in w for w in res.warnings)


def test_refs_to_capped_away_tasks_dropped(tmp_path):
    proj = _projects(tmp_path)
    tasks = [_task("a"), _task("b", ["a", "c"]), _task("c")]
    res = pg.validate_plan(_raw_plan(str(proj / "myapp"), tasks), projects_dir=proj,
                           max_tasks=2)
    assert res.ok and [t.id for t in res.plan.tasks] == ["a", "b"]
    assert res.plan.tasks[1].depends_on == ["a"]  # the "c" ref died with the cap
    assert any("unknown depends_on" in w for w in res.warnings)


# ---------------------------------------------------------------------------
# Edge cleaning: unknown refs, self refs, malformed depends_on
# ---------------------------------------------------------------------------


def test_unknown_ref_dropped_with_warning(tmp_path):
    proj = _projects(tmp_path)
    raw = _raw_plan(str(proj / "myapp"), [_task("a"), _task("b", ["a", "ghost"])])
    res = pg.validate_plan(raw, projects_dir=proj)
    assert res.ok and res.plan.tasks[1].depends_on == ["a"]
    assert any("ghost" in w for w in res.warnings)


def test_self_ref_dropped(tmp_path):
    proj = _projects(tmp_path)
    raw = _raw_plan(str(proj / "myapp"), [_task("a", ["a"])])
    res = pg.validate_plan(raw, projects_dir=proj)
    assert res.ok and res.plan.tasks[0].depends_on == []
    assert any("self" in w for w in res.warnings)


def test_malformed_depends_on_ignored(tmp_path):
    proj = _projects(tmp_path)
    raw = _raw_plan(str(proj / "myapp"),
                    [_task("a"), {"id": "b", "prompt": "p", "depends_on": "a"}])
    res = pg.validate_plan(raw, projects_dir=proj)
    assert res.ok and res.plan.tasks[1].depends_on == []
    assert any("malformed depends_on" in w for w in res.warnings)


def test_ref_slugified_to_match_task_slug(tmp_path):
    # Refs are slugified the same way ids are, so "Storage Module" resolves to the
    # sibling that slugged to "storage-module".
    proj = _projects(tmp_path)
    raw = _raw_plan(str(proj / "myapp"), [
        {"id": "Storage Module", "prompt": "p"},
        {"id": "add", "prompt": "p", "depends_on": ["Storage Module"]},
    ])
    res = pg.validate_plan(raw, projects_dir=proj)
    assert res.ok and res.plan.tasks[0].id == "storage-module"
    assert res.plan.tasks[1].depends_on == ["storage-module"]


def test_duplicate_ids_deduped_first_kept(tmp_path):
    proj = _projects(tmp_path)
    raw = _raw_plan(str(proj / "myapp"), [
        {"id": "Add Health", "prompt": "first"},
        {"id": "add  health", "prompt": "second"},
    ])
    res = pg.validate_plan(raw, projects_dir=proj)
    assert res.ok and len(res.plan.tasks) == 1
    assert res.plan.tasks[0].prompt == "first"
    assert any("duplicate" in w for w in res.warnings)


# ---------------------------------------------------------------------------
# Cycle degeneracy ⇒ original-order linear chain (today's serial semantics)
# ---------------------------------------------------------------------------


def test_cycle_degrades_to_linear_chain(tmp_path):
    proj = _projects(tmp_path)
    raw = _raw_plan(str(proj / "myapp"), [
        _task("a", ["c"]), _task("b", ["a"]), _task("c", ["b"]),
    ])
    res = pg.validate_plan(raw, projects_dir=proj)
    assert res.ok and res.degraded
    assert [t.depends_on for t in res.plan.tasks] == [[], ["a"], ["b"]]
    assert any("cycle" in w for w in res.warnings)


def test_two_node_cycle_degrades(tmp_path):
    proj = _projects(tmp_path)
    raw = _raw_plan(str(proj / "myapp"), [_task("a", ["b"]), _task("b", ["a"]), _task("c")])
    res = pg.validate_plan(raw, projects_dir=proj)
    assert res.ok and res.degraded
    assert [t.depends_on for t in res.plan.tasks] == [[], ["a"], ["b"]]


def test_acyclic_forward_ref_is_not_degraded(tmp_path):
    # A dep on a LATER task in the array is legal (order comes from the wave
    # compiler, not array position) — must NOT be treated as degeneracy.
    proj = _projects(tmp_path)
    raw = _raw_plan(str(proj / "myapp"), [_task("a", ["b"]), _task("b")])
    res = pg.validate_plan(raw, projects_dir=proj)
    assert res.ok and not res.degraded
    assert res.plan.tasks[0].depends_on == ["b"]


# ---------------------------------------------------------------------------
# Contract degradation (missing/malformed ⇒ empty, never blocks)
# ---------------------------------------------------------------------------


def test_missing_contract_becomes_empty(tmp_path):
    proj = _projects(tmp_path)
    res = pg.validate_plan(_raw_plan(str(proj / "myapp"), [_task("a")]), projects_dir=proj)
    assert res.ok
    assert res.plan.tasks[0].contract == pg.TaskContract()


def test_malformed_contract_becomes_empty_task_still_runs(tmp_path):
    proj = _projects(tmp_path)
    raw = _raw_plan(str(proj / "myapp"),
                    [_task("a", contract="not a dict"), _task("b", contract=[1, 2])])
    res = pg.validate_plan(raw, projects_dir=proj)
    assert res.ok and len(res.plan.tasks) == 2
    assert res.plan.tasks[0].contract == pg.TaskContract()
    assert res.plan.tasks[1].contract == pg.TaskContract()


def test_contract_notes_capped_and_control_chars_stripped(tmp_path):
    proj = _projects(tmp_path)
    contract = {"creates": ["src/a.py"], "exports": ["f(x)"],
                "notes": "line1\nline2\x00" + "x" * 500}
    raw = _raw_plan(str(proj / "myapp"), [_task("a", contract=contract)])
    res = pg.validate_plan(raw, projects_dir=proj)
    got = res.plan.tasks[0].contract
    assert got.creates == ["src/a.py"] and got.exports == ["f(x)"]
    assert len(got.notes) <= 280 and "\n" not in got.notes and "\x00" not in got.notes


def test_contract_lists_cleaned_and_capped(tmp_path):
    proj = _projects(tmp_path)
    contract = {"creates": [f"f{i}.py" for i in range(100)] + [42, ""],
                "exports": "not a list", "notes": 42}
    raw = _raw_plan(str(proj / "myapp"), [_task("a", contract=contract)])
    res = pg.validate_plan(raw, projects_dir=proj)
    got = res.plan.tasks[0].contract
    assert len(got.creates) == 32 and got.exports == [] and got.notes == ""


# ---------------------------------------------------------------------------
# Status / integration / acceptance / budget normalization
# ---------------------------------------------------------------------------


def test_unknown_task_status_reset_to_pending(tmp_path):
    proj = _projects(tmp_path)
    raw = _raw_plan(str(proj / "myapp"), [_task("a", status="exploded")])
    res = pg.validate_plan(raw, projects_dir=proj)
    assert res.ok and res.plan.tasks[0].status == "pending"
    assert any("unknown status" in w for w in res.warnings)


def test_integration_nodes_normalized(tmp_path):
    proj = _projects(tmp_path)
    raw = _raw_plan(str(proj / "myapp"), [_task("a")], integration_nodes=[
        {"after_wave": 1, "status": "passed"},
        {"after_wave": 0, "status": "pending"},      # invalid wave -> dropped
        {"after_wave": 2, "status": "sideways"},     # unknown status -> pending
        "junk",
    ])
    res = pg.validate_plan(raw, projects_dir=proj)
    assert res.ok
    assert [(n.after_wave, n.status) for n in res.plan.integration_nodes] == [
        (1, "passed"), (2, "pending")]


def test_job_acceptance_defaults_and_normalization(tmp_path):
    proj = _projects(tmp_path)
    raw = _raw_plan(str(proj / "myapp"), [_task("a")])
    del raw["job_acceptance"]
    res = pg.validate_plan(raw, projects_dir=proj)
    assert res.ok
    assert res.plan.job_acceptance.oracle_path == "tests/test_job_acceptance.py"
    assert res.plan.job_acceptance.status == "pending"

    raw2 = _raw_plan(str(proj / "myapp"), [_task("a")],
                     job_acceptance={"criteria": ["adds work", 42], "oracle_path": "",
                                     "status": "sideways"})
    res2 = pg.validate_plan(raw2, projects_dir=proj)
    assert res2.plan.job_acceptance.criteria == ["adds work"]
    assert res2.plan.job_acceptance.oracle_path == "tests/test_job_acceptance.py"
    assert res2.plan.job_acceptance.status == "pending"


def test_redecompose_budget_defaults_on_malformed(tmp_path):
    proj = _projects(tmp_path)
    raw = _raw_plan(str(proj / "myapp"), [_task("a")],
                    redecompose_budget={"per_task": -3, "per_job": "two", "spent": True})
    res = pg.validate_plan(raw, projects_dir=proj)
    assert res.ok
    assert res.plan.redecompose_budget == pg.RedecomposeBudget(per_task=1, per_job=2, spent=0)


# ---------------------------------------------------------------------------
# compile_waves — chain / diamond / independent, stable order, fail-loud
# ---------------------------------------------------------------------------


def _validated(tmp_path, tasks):
    proj = _projects(tmp_path)
    res = pg.validate_plan(_raw_plan(str(proj / "myapp"), tasks), projects_dir=proj)
    assert res.ok
    return res.plan


def test_waves_chain(tmp_path):
    plan = _validated(tmp_path, [_task("a"), _task("b", ["a"]), _task("c", ["b"])])
    waves = pg.compile_waves(plan)
    assert [[t.id for t in w] for w in waves] == [["a"], ["b"], ["c"]]


def test_waves_diamond_stable_original_order(tmp_path):
    proj = _projects(tmp_path)
    res = pg.validate_plan(_diamond(str(proj / "myapp")), projects_dir=proj)
    waves = pg.compile_waves(res.plan)
    assert [[t.id for t in w] for w in waves] == [["storage"], ["add-cmd", "list-cmd"], ["report"]]


def test_waves_independent_single_wave(tmp_path):
    plan = _validated(tmp_path, [_task("x"), _task("y"), _task("z")])
    waves = pg.compile_waves(plan)
    assert [[t.id for t in w] for w in waves] == [["x", "y", "z"]]


def test_waves_fail_loud_on_unvalidated_cycle(tmp_path):
    # compile_waves only accepts ruler-validated plans; a smuggled cycle raises.
    plan = pg.JobPlan(plan_id="p", goal="g", repo="r", tasks=[
        pg.PlanTask(id="a", prompt="p", depends_on=["b"]),
        pg.PlanTask(id="b", prompt="p", depends_on=["a"]),
    ])
    with pytest.raises(ValueError, match="validate_plan"):
        pg.compile_waves(plan)


# ---------------------------------------------------------------------------
# Evidence-gated status machine + skip propagation
# ---------------------------------------------------------------------------


def test_merged_requires_evidence(tmp_path):
    plan = _validated(tmp_path, [_task("a")])
    plan = pg.mark_building(pg.mark_ready(plan, "a"), "a")
    with pytest.raises(ValueError, match="evidence"):
        pg.mark_merged(plan, "a", "")
    with pytest.raises(ValueError, match="evidence"):
        pg.mark_merged(plan, "a", "   ")
    done = pg.mark_merged(plan, "a", "RESULT: merged to main (run 123)")
    assert done.task("a").status == "merged"


def test_ready_requires_deps_merged(tmp_path):
    plan = _validated(tmp_path, [_task("a"), _task("b", ["a"])])
    with pytest.raises(ValueError, match="not merged"):
        pg.mark_ready(plan, "b")
    plan = pg.mark_merged(pg.mark_building(pg.mark_ready(plan, "a"), "a"), "a", "RESULT: merged")
    assert pg.mark_ready(plan, "b").task("b").status == "ready"


def test_building_requires_ready(tmp_path):
    plan = _validated(tmp_path, [_task("a")])
    with pytest.raises(ValueError, match="requires ready"):
        pg.mark_building(plan, "a")


def test_parked_skips_dependents_transitively(tmp_path):
    plan = _validated(tmp_path, [_task("a"), _task("b", ["a"]), _task("c", ["b"])])
    parked = pg.mark_parked(plan, "a", "gate red x3 — oracle failures attached")
    assert parked.task("a").status == "parked"
    assert parked.task("b").status == "skipped"
    assert parked.task("c").status == "skipped"


def test_skip_propagation_across_diamond_join_spares_independent_branch(tmp_path):
    proj = _projects(tmp_path)
    res = pg.validate_plan(_diamond(str(proj / "myapp")), projects_dir=proj)
    plan = res.plan
    plan = pg.mark_merged(pg.mark_building(pg.mark_ready(plan, "storage"), "storage"),
                          "storage", "RESULT: merged")
    parked = pg.mark_parked(plan, "add-cmd", "park evidence")
    assert parked.task("add-cmd").status == "parked"
    assert parked.task("report").status == "skipped"   # join child dies
    assert parked.task("list-cmd").status == "pending"  # independent branch survives
    assert parked.task("storage").status == "merged"    # terminal history untouched


def test_blocked_requires_evidence_and_propagates(tmp_path):
    plan = _validated(tmp_path, [_task("a"), _task("b", ["a"])])
    with pytest.raises(ValueError, match="evidence"):
        pg.mark_blocked(plan, "a", "")
    blocked = pg.mark_blocked(plan, "a", "gitleaks: planted credential at src/x.py:3")
    assert blocked.task("a").status == "blocked"
    assert blocked.task("b").status == "skipped"


def test_terminal_states_refuse_further_transitions(tmp_path):
    plan = _validated(tmp_path, [_task("a")])
    parked = pg.mark_parked(plan, "a", "evidence")
    with pytest.raises(ValueError, match="terminal"):
        pg.mark_merged(parked, "a", "evidence")
    with pytest.raises(ValueError, match="terminal"):
        pg.mark_ready(parked, "a")


def test_unknown_task_id_fails_loud(tmp_path):
    plan = _validated(tmp_path, [_task("a")])
    with pytest.raises(ValueError, match="unknown task"):
        pg.mark_merged(plan, "ghost", "evidence")


def test_transitions_return_new_plans_original_unchanged(tmp_path):
    plan = _validated(tmp_path, [_task("a")])
    ready = pg.mark_ready(plan, "a")
    assert plan.task("a").status == "pending" and ready.task("a").status == "ready"


def test_integration_and_job_acceptance_evidence_gated(tmp_path):
    plan = _validated(tmp_path, [_task("a")])
    with pytest.raises(ValueError, match="evidence"):
        pg.mark_integration(plan, 1, passed=True, evidence="")
    gated = pg.mark_integration(plan, 1, passed=False, evidence="pytest exit 1 on main")
    assert gated.integration_nodes[0].status == "failed"
    with pytest.raises(ValueError, match="evidence"):
        pg.mark_job_acceptance(plan, "passed", "")
    with pytest.raises(ValueError, match="invalid outcome"):
        pg.mark_job_acceptance(plan, "pending", "evidence")
    # H2 FALSE-DONE guard: a job may NOT be marked 'passed' while any task is non-terminal
    # (pending/ready/building) — a done job cannot have an unfinished task. 'failed'/'not-run'
    # stay unrestricted (a job legitimately fails or is not run mid-flight).
    with pytest.raises(ValueError, match="FALSE-DONE|non-terminal"):
        pg.mark_job_acceptance(plan, "passed", "job oracle green: 12 passed")  # 'a' is pending
    assert pg.mark_job_acceptance(plan, "failed", "oracle red").job_acceptance.status == "failed"
    assert pg.mark_job_acceptance(plan, "not-run", "not executed").job_acceptance.status == "not-run"
    # Once the only task is terminal (merged), 'passed' is allowed.
    done_plan = pg.mark_merged(pg.mark_building(pg.mark_ready(plan, "a"), "a"), "a", "RESULT: merged")
    assert pg.mark_job_acceptance(done_plan, "passed", "job oracle green: 12 passed").job_acceptance.status == "passed"


def test_redecompose_budget_spend_and_exhaust(tmp_path):
    plan = _validated(tmp_path, [_task("a")])
    plan = pg.spend_redecompose(pg.spend_redecompose(plan))
    assert plan.redecompose_budget.spent == 2
    with pytest.raises(ValueError, match="exhausted"):
        pg.spend_redecompose(plan)


# ---------------------------------------------------------------------------
# PlanStore — hash, tamper refusal, load-time re-validation (§10 S1)
# ---------------------------------------------------------------------------


def _store(tmp_path) -> pg.PlanStore:
    return pg.PlanStore(tmp_path / "state" / "job-plan.json",
                        projects_dir=_projects(tmp_path))


def test_store_write_load_round_trip(tmp_path):
    store = _store(tmp_path)
    plan = _validated(tmp_path, [_task("a"), _task("b", ["a"])])
    written = store.write(plan)
    assert written.plan_hash and len(written.plan_hash) == 64
    loaded = store.load()
    assert loaded.ok and loaded.plan is not None
    assert loaded.plan.plan_hash == written.plan_hash
    assert [t.to_raw() for t in loaded.plan.tasks] == [t.to_raw() for t in written.tasks]


def test_store_hash_deterministic(tmp_path):
    store = _store(tmp_path)
    plan = _validated(tmp_path, [_task("a")])
    assert store.write(plan).plan_hash == store.write(plan).plan_hash


def _identity_plan() -> dict:
    """A full jobplan/v1 dict exercising every hashed identity field + every excluded
    mutable-status field (repo is a bare string — compute_plan_hash hashes it, never
    resolves it)."""
    return _raw_plan("C:/proj/app", [
        {"id": "a", "prompt": "build a", "depends_on": [], "status": "pending",
         "contract": {"creates": ["a.py"], "exports": ["a()"], "notes": "n"}},
        {"id": "b", "prompt": "build b", "depends_on": ["a"], "status": "pending",
         "contract": {"creates": ["b.py"], "exports": [], "notes": ""}},
    ], integration_nodes=[{"after_wave": 1, "status": "pending"}],
       job_acceptance={"criteria": ["c1"], "oracle_path": "tests/x.py", "status": "pending"})


def test_plan_hash_is_stable_across_status_but_not_content():
    # #740 H3: the plan_hash seals the IMMUTABLE IDENTITY of the FULL plan. A change to a
    # MUTABLE runtime-status field must NOT change it (else the swap-state pin self-
    # invalidates and the S1 tamper check false-fires on the system's own writes); a change
    # to ANY hashed identity field (goal/repo/prompt/deps/contract/oracle_path/criteria/
    # budget-limit/wave-index) MUST change it (tamper is caught).
    import copy
    plan = _identity_plan()
    base = pg.compute_plan_hash(plan)

    # Mutable runtime state (advisory, EXCLUDED from the seal) -> SAME hash.
    for mut in (
        lambda p: p["tasks"][0].__setitem__("status", "merged"),
        lambda p: p["redecompose_budget"].__setitem__("spent", 2),
        lambda p: p["job_acceptance"].__setitem__("status", "passed"),
        lambda p: p["integration_nodes"][0].__setitem__("status", "passed"),
    ):
        p = copy.deepcopy(plan)
        mut(p)
        assert pg.compute_plan_hash(p) == base

    # Immutable identity (INCLUDED in the seal) -> DIFFERENT hash.
    for label, mut in (
        ("goal", lambda p: p.__setitem__("goal", "a different goal")),
        ("repo", lambda p: p.__setitem__("repo", "C:/proj/other")),
        ("prompt", lambda p: p["tasks"][0].__setitem__("prompt", "build a differently")),
        ("depends_on", lambda p: p["tasks"][1].__setitem__("depends_on", [])),
        ("contract", lambda p: p["tasks"][0]["contract"].__setitem__("creates", ["evil.py"])),
        ("oracle_path", lambda p: p["job_acceptance"].__setitem__("oracle_path", "../../evil.py")),
        ("criteria", lambda p: p["job_acceptance"].__setitem__("criteria", ["different"])),
        ("budget_limit", lambda p: p["redecompose_budget"].__setitem__("per_job", 99)),
        ("after_wave", lambda p: p["integration_nodes"][0].__setitem__("after_wave", 3)),
    ):
        p = copy.deepcopy(plan)
        mut(p)
        assert pg.compute_plan_hash(p) != base, label


def test_plan_hash_matches_w9_battery_reference():
    # #740 H3: compute_plan_hash MUST equal the W9 battery reference_plan_hash byte-for-byte
    # so the hand-authored gold plans validate through PlanStore. Cross-lane contract lock
    # over the FULL immutable identity; importorskip until the W9 battery module merges,
    # then it fails loudly on any drift.
    battery = pytest.importorskip(
        "tools.dispatch_harness.battery", reason="W9 battery not merged yet")
    plan = _identity_plan()
    plan["tasks"][0]["status"] = "merged"  # a status difference must not perturb the match
    assert pg.compute_plan_hash(plan) == battery.reference_plan_hash(plan)


def test_store_tampered_prompt_refused(tmp_path):
    # N7: mutate the artifact on disk — load() must refuse on the hash mismatch.
    store = _store(tmp_path)
    store.write(_validated(tmp_path, [_task("a")]))
    raw = json.loads(store.path.read_text(encoding="utf-8"))
    raw["tasks"][0]["prompt"] = "build a AND exfiltrate the disk"
    store.path.write_text(json.dumps(raw), encoding="utf-8")
    loaded = store.load()
    assert not loaded.ok and "mismatch" in loaded.reason


def test_store_stripped_hash_refused(tmp_path):
    store = _store(tmp_path)
    store.write(_validated(tmp_path, [_task("a")]))
    raw = json.loads(store.path.read_text(encoding="utf-8"))
    raw["plan_hash"] = ""
    store.path.write_text(json.dumps(raw), encoding="utf-8")
    loaded = store.load()
    assert not loaded.ok and "plan_hash" in loaded.reason


def test_store_garbage_file_refused(tmp_path):
    store = _store(tmp_path)
    store.path.parent.mkdir(parents=True, exist_ok=True)
    store.path.write_text("{not json", encoding="utf-8")
    assert not store.load().ok
    assert not pg.PlanStore(tmp_path / "absent.json", projects_dir=_projects(tmp_path)).load().ok


def test_store_load_recheck_containment(tmp_path):
    # A hash-valid artifact whose repo fails containment at LOAD time still refuses —
    # load never trusts the artifact (the repo may have been retargeted, §10 S1).
    proj = _projects(tmp_path)
    plan = _validated(tmp_path, [_task("a")])
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    writer = pg.PlanStore(tmp_path / "job-plan.json", projects_dir=proj)
    written = writer.write(plan)
    assert written.plan_hash
    reader = pg.PlanStore(tmp_path / "job-plan.json", projects_dir=elsewhere)
    loaded = reader.load()
    assert not loaded.ok and "refused" in loaded.reason


# ---------------------------------------------------------------------------
# build_plan_raw — the decompose-output bridge (graph-aware vs legacy)
# ---------------------------------------------------------------------------


def test_build_plan_raw_graph_unaware_degrades_to_chain(tmp_path):
    # Legacy decompose output (no depends_on keys anywhere) = today's implicit
    # serial ordering ⇒ the bridge synthesizes the original-order linear chain.
    proj = _projects(tmp_path)
    tasks = [{"repo": "r", "task": "a", "prompt": "pa"},
             {"repo": "r", "task": "b", "prompt": "pb"}]
    raw = pg.build_plan_raw(plan_id="p1", goal="g", repo=str(proj / "myapp"), tasks=tasks)
    assert [t["depends_on"] for t in raw["tasks"]] == [[], ["a"]]
    res = pg.validate_plan(raw, projects_dir=proj)
    assert res.ok and not res.degraded


def test_build_plan_raw_graph_aware_respects_empty_deps(tmp_path):
    # A graph-aware emission (>=1 task carries the key) keeps explicit [] roots
    # independent — B7's parallel-branch shape stays expressible.
    proj = _projects(tmp_path)
    tasks = [{"repo": "r", "task": "a", "prompt": "pa", "depends_on": []},
             {"repo": "r", "task": "b", "prompt": "pb", "depends_on": ["a"]},
             {"repo": "r", "task": "c", "prompt": "pc"}]
    raw = pg.build_plan_raw(plan_id="p1", goal="g", repo=str(proj / "myapp"), tasks=tasks)
    assert [t["depends_on"] for t in raw["tasks"]] == [[], ["a"], []]
    res = pg.validate_plan(raw, projects_dir=proj)
    waves = pg.compile_waves(res.plan)
    assert [[t.id for t in w] for w in waves] == [["a", "c"], ["b"]]


# ---------------------------------------------------------------------------
# Config knob — [fleet_dispatch].plan_graph plumbing (OFF default)
# ---------------------------------------------------------------------------


def test_plan_graph_knob_default_off():
    cfg = build_default_config()
    assert cfg.plan_graph is False
    # Positional back-compat: existing constructions carry the False default too.
    bare = FleetDispatchConfig(
        scripts_dir=cfg.scripts_dir, queue_path=cfg.queue_path,
        runs_dir=cfg.runs_dir, projects_dir=cfg.projects_dir,
    )
    assert bare.plan_graph is False


def test_plan_graph_knob_threads_through():
    assert build_default_config(plan_graph=True).plan_graph is True
    assert build_default_config("C:/x", "C:/y", plan_graph=True).plan_graph is True


def test_default_toml_ships_plan_graph_on():
    # The shipped default.toml carries the knob ON since the W8 live proof
    # (2026-07-05 run `20260705-214803-bd`: a real 6-task dependency graph executed
    # in waves on the Arc 140V — #740/#748; the LA's proven-features-default-LIVE
    # rule). The OFF path stays available and regression-locked (plan_graph=false
    # reproduces the flat queue byte-identically — the degradation suite above).
    from pathlib import Path
    toml_path = (Path(__file__).resolve().parents[2] /
                 "services" / "assistant_orchestrator" / "config" / "default.toml")
    text = toml_path.read_text(encoding="utf-8")
    assert "plan_graph = true" in text


# ===========================================================================
# #740 M2 W1 hardening — reproduce-then-close (Vikunja #740; adversarial defect set)
# ===========================================================================


# ---- H1: mark_merged must not bypass the deps-merged gate --------------------


def test_h1_mark_merged_requires_ready_or_building(tmp_path):
    # H1: a raw pending -> merged skips the deps-merged invariant in mark_ready (a
    # FALSE-DONE surface). merged now requires source status in {ready, building}.
    plan = _validated(tmp_path, [_task("a")])
    assert plan.task("a").status == "pending"
    with pytest.raises(ValueError, match="merged requires ready or building"):
        pg.mark_merged(plan, "a", "RESULT: merged")  # was allowed pre-fix
    ready = pg.mark_ready(plan, "a")
    assert pg.mark_merged(ready, "a", "ev").task("a").status == "merged"        # ready -> ok
    building = pg.mark_building(ready, "a")
    assert pg.mark_merged(building, "a", "ev").task("a").status == "merged"     # building -> ok


def test_h1_merged_from_pending_cannot_skip_unmerged_dependency(tmp_path):
    # The concrete FALSE-DONE the gate closes: b depends on an unmerged a — b must not
    # be markable merged directly from pending (which would bypass mark_ready's check).
    plan = _validated(tmp_path, [_task("a"), _task("b", ["a"])])
    with pytest.raises(ValueError, match="merged requires ready or building"):
        pg.mark_merged(plan, "b", "RESULT: merged")


# ---- H3: the hash covers the full immutable identity (tamper now refused) ----


def _tamper_load(tmp_path, mutate):
    """Write a valid plan, apply *mutate* to the on-disk raw dict (retaining the written
    hash), then load(). Returns the PlanValidation."""
    store = _store(tmp_path)
    store.write(_validated(tmp_path, [_task("a"), _task("b", ["a"])]))
    raw = json.loads(store.path.read_text(encoding="utf-8"))
    mutate(raw)
    store.path.write_text(json.dumps(raw), encoding="utf-8")
    return store.load()


def test_h3_oracle_path_tamper_refused(tmp_path):
    # oracle_path is now hashed — an oracle redirect (a FALSE-DONE surface) is caught.
    def redirect(raw):
        raw["job_acceptance"]["oracle_path"] = "../../evil.py"
    loaded = _tamper_load(tmp_path, redirect)
    assert not loaded.ok and "mismatch" in loaded.reason  # pre-fix: loaded.ok was True


def test_h3_repo_retarget_tamper_refused(tmp_path):
    # repo is now hashed — a retarget to ANOTHER valid repo can no longer ride silently.
    proj = _projects(tmp_path)
    (proj / "other" / ".git").mkdir(parents=True, exist_ok=True)
    def retarget(raw):
        raw["repo"] = str(proj / "other")
    loaded = _tamper_load(tmp_path, retarget)
    assert not loaded.ok and "mismatch" in loaded.reason


def test_h3_budget_limit_tamper_refused(tmp_path):
    # The re-decompose budget CEILINGS are hashed (spent is not) — a ceiling bump is caught.
    def bump(raw):
        raw["redecompose_budget"]["per_job"] = 999
    loaded = _tamper_load(tmp_path, bump)
    assert not loaded.ok and "mismatch" in loaded.reason


def test_h3_integration_wave_tamper_refused(tmp_path):
    # An integration node's after_wave index is hashed (its status is not).
    def add_wave(raw):
        raw["integration_nodes"] = [{"after_wave": 5, "status": "pending"}]
    loaded = _tamper_load(tmp_path, add_wave)
    assert not loaded.ok and "mismatch" in loaded.reason


def test_h3_status_change_on_disk_is_advisory_and_still_loads(tmp_path):
    # The INTEGRITY CONTRACT: status is NOT integrity-covered — a status flip on disk keeps
    # the identity hash valid, so load() SUCCEEDS and the loaded status rides from disk as
    # ADVISORY (a driver must re-derive done-ness from a fresh oracle run, never trust this).
    store = _store(tmp_path)
    store.write(_validated(tmp_path, [_task("a"), _task("b", ["a"])]))
    raw = json.loads(store.path.read_text(encoding="utf-8"))
    raw["tasks"][0]["status"] = "merged"          # advisory flip
    raw["job_acceptance"]["status"] = "passed"    # advisory flip
    raw["redecompose_budget"]["spent"] = 1        # advisory (not a ceiling)
    store.path.write_text(json.dumps(raw), encoding="utf-8")
    loaded = store.load()
    assert loaded.ok and loaded.plan is not None
    assert loaded.plan.task("a").status == "merged"           # advisory value rides through
    assert loaded.plan.job_acceptance.status == "passed"
    assert loaded.plan.redecompose_budget.spent == 1


# ---- H4: load() degrades on unreadable/pathological input, never crashes -----


def test_h4_invalid_utf8_refused_not_crash(tmp_path):
    store = _store(tmp_path)
    store.path.parent.mkdir(parents=True, exist_ok=True)
    store.path.write_bytes(b"\xff\xfe not utf-8 \xc3\x28")
    loaded = store.load()  # pre-fix: raised UnicodeDecodeError
    assert not loaded.ok and "unreadable" in loaded.reason


def test_h4_deeply_nested_json_refused_not_crash(tmp_path):
    store = _store(tmp_path)
    store.path.parent.mkdir(parents=True, exist_ok=True)
    depth = 200_000
    store.path.write_text("[" * depth + "]" * depth, encoding="utf-8")
    loaded = store.load()  # pre-fix: raised RecursionError
    assert not loaded.ok


# ---- H5: bool after_wave + goal/prompt/oracle_path cap + control-strip -------


def test_h5_integration_node_bool_after_wave_dropped(tmp_path):
    # isinstance(True, int) is True — a JSON `true` must NOT pass as after_wave==1.
    proj = _projects(tmp_path)
    raw = _raw_plan(str(proj / "myapp"), [_task("a")],
                    integration_nodes=[{"after_wave": True, "status": "pending"}])
    res = pg.validate_plan(raw, projects_dir=proj)
    assert res.ok and res.plan.integration_nodes == []            # pre-fix: kept as True
    assert any("malformed integration node" in w for w in res.warnings)


def test_h5_goal_prompt_oracle_path_control_stripped_and_capped(tmp_path):
    proj = _projects(tmp_path)
    raw = _raw_plan(str(proj / "myapp"),
                    [_task("a", prompt="do\x00 the\x1bthing" + "y" * 20000)],
                    goal="a\x00goal\x1b" + "x" * 10000,
                    job_acceptance={"criteria": [], "oracle_path": "tests/\x00\x1bt.py",
                                    "status": "pending"})
    res = pg.validate_plan(raw, projects_dir=proj)
    assert res.ok
    assert "\x00" not in res.plan.goal and "\x1b" not in res.plan.goal
    assert len(res.plan.goal) <= pg.GOAL_MAX
    p = res.plan.tasks[0].prompt
    assert "\x00" not in p and "\x1b" not in p and len(p) <= pg.PROMPT_MAX
    op = res.plan.job_acceptance.oracle_path
    assert "\x00" not in op and "\x1b" not in op


def test_h5_valid_goal_prompt_unchanged(tmp_path):
    # Behavior-preserving: a normal (short, control-char-free) goal/prompt is byte-identical.
    proj = _projects(tmp_path)
    raw = _raw_plan(str(proj / "myapp"), [_task("a")], goal="a budget tracker")
    res = pg.validate_plan(raw, projects_dir=proj)
    assert res.plan.goal == "a budget tracker"
    assert res.plan.tasks[0].prompt == "build a"


# ---- H6: slug-collision edge must not retarget to the survivor ---------------


def test_h6_slug_collision_dependent_not_retargeted_to_survivor(tmp_path):
    # Two ids whose slugs collide (identical first-48 chars): only the first survives dedup.
    # A dependent that referenced the DROPPED dup must have its ref DROPPED, never silently
    # retargeted onto the surviving task (which is a DIFFERENT unit of work).
    proj = _projects(tmp_path)
    collided = "a" * 48
    long_a, long_b = collided + "-branch-one", collided + "-branch-two"
    assert pg.slugify_task(long_a) == pg.slugify_task(long_b) == collided  # precondition
    raw = _raw_plan(str(proj / "myapp"), [
        {"id": long_a, "prompt": "survivor"},
        {"id": long_b, "prompt": "dropped duplicate"},
        _task("zed", [long_b]),   # meant the DROPPED dup
    ])
    res = pg.validate_plan(raw, projects_dir=proj)
    assert res.ok
    zed = res.plan.task("zed")
    assert collided not in zed.depends_on    # pre-fix: zed.depends_on == [collided]
    assert zed.depends_on == []
    assert any("ambiguous" in w for w in res.warnings)
