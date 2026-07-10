"""#752 F1/F2 — card-driven diamond decomposition + the B2 job-level acceptance oracle.

The M2 battery's B2 card declares a 4-unit ``diamond`` (tokenize -> {word-freq, n-grams} ->
report), but the 14B right-sizing ruler collapses the natural-language goal to ONE task and
``build_job_plan`` degrades to the flat queue (``test_build_job_plan_single_task_degrades_to_
flat_queue`` in test_integration_gate is that exact failure). These tests prove the INVERSE for
a carded diamond: :mod:`shared.fleet.battery_plans` authorises the 4-arm graph + a job oracle,
``generate_plan`` uses it via the generic ``decomposition_override`` seam, and ``build_job_plan``
builds the graph (>=4 edges, >=3 waves) instead of degrading.

The whole seam runs model-free and GPU-free (the ``generate_fn`` is injected); the one
subprocess test grades the REAL shipped oracle against a reference ``app`` package to prove F2
has teeth and that ``from app.tokenize import ...`` resolves under the driver's grade mechanism.
"""

from __future__ import annotations

import ast
import json
import subprocess
import sys
from pathlib import Path

import pytest

from shared.fleet import battery_plans
from shared.fleet import swap_ops as so
from shared.fleet import acceptance as acc
from shared.fleet.acceptance import (
    JOB_ORACLE_CODE_KEY,
    JOB_ORACLE_PATH_KEY,
    JOB_ORACLE_PATH_PYTHON,
    DecompositionOverride,
    generate_plan,
)
from shared.fleet.dispatch import FleetDispatchConfig
from tools.dispatch_harness.battery import compute_waves

# The four `app`-package arm module names — the reconciliation point with the sibling F3 fix
# (per-task oracles pinned to `app`). Asserted here so a drift is caught at merge.
_APP_MODULES = ("tokenize", "word_frequencies", "neighbor_pairs", "report")


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


def _mk_repo(tmp_path: Path, name: str) -> Path:
    """A repo that passes ``validate_repo`` containment (a ``.git`` dir under projects_dir)."""
    repo = tmp_path / name
    (repo / ".git").mkdir(parents=True, exist_ok=True)
    return repo


def _swap_config(tmp_path: Path) -> FleetDispatchConfig:
    setup = tmp_path / "agentic"
    (setup / "scripts").mkdir(parents=True, exist_ok=True)
    return FleetDispatchConfig(
        scripts_dir=setup / "scripts",
        queue_path=setup / "state" / "fleet-queue.json",
        runs_dir=setup / "state" / "fleet-runs",
        projects_dir=tmp_path,
        plan_graph=True,
    )


def _fake_gen(prompt: str) -> str:
    """A fake 14B for the override path: it is called for criteria / build-signal / assumptions /
    assets ONLY (decompose + job-oracle are supplied by the override). Returns a behavior
    criterion + a python build signal so the realistic 5-task shape (4 arms + acceptance-tests)
    is exercised. It must NEVER be asked to decompose — an override bypasses that."""
    assert "decomposing a software change request" not in prompt, (
        "the override path must not call the 14B decomposer"
    )
    if "ACCEPTANCE CRITERIA" in prompt:
        return json.dumps([{"text": "each word is counted", "tier": "behavior",
                            "check": "count the words"}])
    if "Classify what KIND of software" in prompt:
        return json.dumps({"surface": "command-line", "candidates": [],
                           "language_hint": "python", "complexity": "moderate", "components": []})
    return "[]"


def _diamond_override(repo: Path) -> DecompositionOverride:
    return DecompositionOverride(
        tasks=battery_plans.build_text_stats_diamond(str(repo)),
        job_oracle_code=battery_plans._TEXT_STATS_JOB_ORACLE_PY,
        job_oracle_path=JOB_ORACLE_PATH_PYTHON,
    )


def _edges(tasks) -> int:
    """Total dependency edges over a list of PlanTask objects (or arm dicts)."""
    total = 0
    for t in tasks:
        deps = t.depends_on if hasattr(t, "depends_on") else t["depends_on"]
        total += len(deps)
    return total


def _waves(plan_tasks) -> list[list[str]]:
    return compute_waves([{"id": t.id, "depends_on": t.depends_on} for t in plan_tasks])


# ---------------------------------------------------------------------------
# F1 — the diamond decomposition shape (4 arms, 4 edges, 3 waves)
# ---------------------------------------------------------------------------


def test_diamond_decomposition_is_a_4_arm_3_wave_graph():
    arms = battery_plans.build_text_stats_diamond("C:/x/battery-b2-text-stats")
    assert [t["task"] for t in arms] == ["tokenize", "word-frequencies", "neighbor-pairs", "report"]
    # tokenize -> {word-freq, n-grams} -> report : exactly 4 edges, exactly 3 waves.
    assert _edges(arms) == 4
    waves = compute_waves([{"id": t["task"], "depends_on": t["depends_on"]} for t in arms])
    assert waves == [["tokenize"], ["neighbor-pairs", "word-frequencies"], ["report"]]
    assert len(waves) == 3
    # The fan-in join depends on BOTH count arms; the count arms both depend on tokenize.
    by_id = {t["task"]: t for t in arms}
    assert by_id["tokenize"]["depends_on"] == []
    assert by_id["word-frequencies"]["depends_on"] == ["tokenize"]
    assert by_id["neighbor-pairs"]["depends_on"] == ["tokenize"]
    assert set(by_id["report"]["depends_on"]) == {"word-frequencies", "neighbor-pairs"}


def test_diamond_arms_use_the_app_package_convention():
    arms = battery_plans.build_text_stats_diamond("/repo")
    all_creates = [c for t in arms for c in t["contract"]["creates"]]
    # Every created module lives under the `app` package (the F3 reconciliation point).
    assert all(c.startswith("app/") for c in all_creates)
    assert "app/__init__.py" in all_creates
    for mod in _APP_MODULES:
        assert f"app/{mod}.py" in all_creates, f"missing app/{mod}.py in arm contracts"
    # Each arm declares a contract with exports (build_plan_raw / the job oracle read these).
    for t in arms:
        assert t["contract"]["creates"] and t["contract"]["exports"]
        assert isinstance(t["contract"]["notes"], str)
    # Arms carry the absolute repo (mirrors decompose_request; passes validate_repo downstream).
    assert all(t["repo"] == "/repo" for t in arms)


# ---------------------------------------------------------------------------
# F2 — the job-level acceptance oracle (valid, app-pinned, grades the join)
# ---------------------------------------------------------------------------


def test_job_oracle_is_valid_python_and_imports_arms_from_app():
    code = battery_plans._TEXT_STATS_JOB_ORACLE_PY
    tree = ast.parse(code)  # fail-closed contract: a malformed oracle would be dropped
    for mod in _APP_MODULES:
        fn = "combined_report" if mod == "report" else mod
        assert f"from app.{mod} import {fn}" in code, f"oracle must import app.{mod}"
    tests = [n for n in ast.walk(tree)
             if isinstance(n, ast.FunctionDef) and n.name.startswith("test_")]
    # One test per arm behaviour + the join.
    assert len(tests) >= 4


def _write_reference_app(repo: Path, *, report_body: str, freq_body: str) -> None:
    """A CORRECT reference implementation of the four arms (parametrised so a test can inject a
    BROKEN report/frequency arm to prove the oracle has teeth)."""
    app = repo / "app"
    app.mkdir(parents=True, exist_ok=True)
    (app / "__init__.py").write_text("", encoding="utf-8")
    (app / "tokenize.py").write_text(
        "def tokenize(text):\n"
        "    words = []\n"
        "    for raw in text.split():\n"
        "        w = raw.strip(\".,!?;:'\\\"()[]{}\").lower()\n"
        "        if w:\n"
        "            words.append(w)\n"
        "    return words\n",
        encoding="utf-8",
    )
    (app / "word_frequencies.py").write_text(freq_body, encoding="utf-8")
    (app / "neighbor_pairs.py").write_text(
        "def neighbor_pairs(tokens):\n"
        "    pairs = {}\n"
        "    for a, b in zip(tokens, tokens[1:]):\n"
        "        pairs[(a, b)] = pairs.get((a, b), 0) + 1\n"
        "    return pairs\n",
        encoding="utf-8",
    )
    (app / "report.py").write_text(report_body, encoding="utf-8")
    tests_dir = repo / "tests"
    tests_dir.mkdir(parents=True, exist_ok=True)
    (tests_dir / "test_job_acceptance.py").write_text(
        battery_plans._TEXT_STATS_JOB_ORACLE_PY, encoding="utf-8"
    )


_GOOD_FREQ = (
    "def word_frequencies(tokens):\n"
    "    freqs = {}\n"
    "    for t in tokens:\n"
    "        freqs[t] = freqs.get(t, 0) + 1\n"
    "    return freqs\n"
)
_GOOD_REPORT = (
    "from app.tokenize import tokenize\n"
    "from app.word_frequencies import word_frequencies\n"
    "from app.neighbor_pairs import neighbor_pairs\n\n"
    "def combined_report(text):\n"
    "    tokens = tokenize(text)\n"
    "    freqs = word_frequencies(tokens)\n"
    "    pairs = neighbor_pairs(tokens)\n"
    "    lines = ['Word frequencies:']\n"
    "    for word, count in sorted(freqs.items(), key=lambda kv: (-kv[1], kv[0])):\n"
    "        lines.append(f'  {word}: {count}')\n"
    "    lines.append('Neighbouring pairs:')\n"
    "    for (a, b), count in sorted(pairs.items(), key=lambda kv: (-kv[1], kv[0])):\n"
    "        lines.append(f'  {a} {b}: {count}')\n"
    "    return '\\n'.join(lines)\n"
)
# A report that shows ONLY frequencies — the neighbouring-pair findings are absent.
_FREQ_ONLY_REPORT = (
    "from app.tokenize import tokenize\n"
    "from app.word_frequencies import word_frequencies\n\n"
    "def combined_report(text):\n"
    "    freqs = word_frequencies(tokenize(text))\n"
    "    lines = ['Word frequencies:']\n"
    "    for word, count in sorted(freqs.items()):\n"
    "        lines.append(f'  {word}: {count}')\n"
    "    return '\\n'.join(lines)\n"
)
# A frequency arm that is off by one — the counts are wrong.
_BROKEN_FREQ = (
    "def word_frequencies(tokens):\n"
    "    freqs = {}\n"
    "    for t in tokens:\n"
    "        freqs[t] = freqs.get(t, 0) + 2\n"   # wrong: double counts
    "    return freqs\n"
)


def _run_oracle(repo: Path) -> subprocess.CompletedProcess:
    """Grade the seeded oracle exactly as ``real_run_job_oracle`` does — ``python -m pytest``
    from the repo root (which puts the repo root on sys.path so ``from app.tokenize`` resolves)."""
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "tests/test_job_acceptance.py"],
        cwd=str(repo), capture_output=True, text=True, timeout=180,
    )


def test_job_oracle_grades_the_joined_diamond(tmp_path):
    # (1) A CORRECT integrated tree passes — proving the app-package imports resolve and the
    #     four assertions (tokenize / word-freq / pairs / the joined report) all hold.
    good = _mk_repo(tmp_path, "good")
    _write_reference_app(good, report_body=_GOOD_REPORT, freq_body=_GOOD_FREQ)
    res_ok = _run_oracle(good)
    assert res_ok.returncode == 0, f"correct impl should pass:\n{res_ok.stdout}\n{res_ok.stderr}"

    # (2) A report that DROPS the neighbouring-pair findings fails — the JOIN has teeth.
    join_broken = _mk_repo(tmp_path, "join_broken")
    _write_reference_app(join_broken, report_body=_FREQ_ONLY_REPORT, freq_body=_GOOD_FREQ)
    res_join = _run_oracle(join_broken)
    assert res_join.returncode != 0, f"a freq-only report must fail the join:\n{res_join.stdout}"

    # (3) A wrong word-frequency arm fails — each ARM is graded, not just the join.
    arm_broken = _mk_repo(tmp_path, "arm_broken")
    _write_reference_app(arm_broken, report_body=_GOOD_REPORT, freq_body=_BROKEN_FREQ)
    res_arm = _run_oracle(arm_broken)
    assert res_arm.returncode != 0, f"a wrong frequency arm must fail:\n{res_arm.stdout}"


# ---------------------------------------------------------------------------
# resolve_plan_override — fires ONLY for a carded diamond battery repo
# ---------------------------------------------------------------------------


def test_resolve_override_fires_for_the_real_b2_card(tmp_path):
    # Uses the committed evals/battery/B2.json (default spec dir).
    ov = battery_plans.resolve_plan_override("battery-b2-text-stats", projects_dir=tmp_path)
    assert ov is not None
    assert len(ov.tasks) == 4
    assert ov.job_oracle_path == JOB_ORACLE_PATH_PYTHON
    assert "from app.tokenize import tokenize" in ov.job_oracle_code
    # Arms carry the absolute repo under projects_dir (mirrors decompose_request).
    assert all(t["repo"] == str(tmp_path / "battery-b2-text-stats") for t in ov.tasks)


def test_resolve_override_none_for_non_battery_repo(tmp_path):
    # Fast path: a production/operator repo never reads a card.
    assert battery_plans.resolve_plan_override("rocket-calc", projects_dir=tmp_path) is None
    assert battery_plans.resolve_plan_override(
        "C:/Users/x/projects/myapp", projects_dir=tmp_path
    ) is None


def test_resolve_override_none_for_non_diamond_battery_card(tmp_path):
    spec = tmp_path / "spec"
    spec.mkdir()
    (spec / "B4.json").write_text(json.dumps({
        "schema": "battery-card/v1", "id": "B4", "repo": "battery-b4-linear",
        "shape": "linear", "units": 3, "goal": "a plain linear job"}), encoding="utf-8")
    assert battery_plans.resolve_plan_override(
        "battery-b4-linear", projects_dir=tmp_path, spec_dir=spec
    ) is None


def test_resolve_override_none_for_diamond_without_registered_builder(tmp_path):
    # A diamond card the module has no arm builder for must FAIL CLOSED (never inject a shape
    # we cannot author), not silently reuse the text-stats arms.
    spec = tmp_path / "spec"
    spec.mkdir()
    (spec / "B9.json").write_text(json.dumps({
        "schema": "battery-card/v1", "id": "B9", "repo": "battery-b9-unknown",
        "shape": "diamond", "units": 4, "goal": "some other diamond"}), encoding="utf-8")
    assert battery_plans.resolve_plan_override(
        "battery-b9-unknown", projects_dir=tmp_path, spec_dir=spec
    ) is None


# ---------------------------------------------------------------------------
# generate_plan — the override drives the plan; None is byte-identical
# ---------------------------------------------------------------------------


def test_generate_plan_with_override_yields_multi_task_plan_with_job_oracle(tmp_path):
    repo = _mk_repo(tmp_path, "battery-b2-text-stats")
    plan = generate_plan(
        "a little text-statistics toolkit", "battery-b2-text-stats",
        generate_fn=_fake_gen, projects_dir=tmp_path,
        decomposition_override=_diamond_override(repo),
    )
    assert plan.ok and len(plan.tasks) >= 2 and not plan.fell_back
    # The job oracle rides the FINAL compiled task, and only it.
    last = plan.tasks[-1]
    assert last.get(JOB_ORACLE_PATH_KEY) == JOB_ORACLE_PATH_PYTHON
    assert "from app.tokenize import tokenize" in last.get(JOB_ORACLE_CODE_KEY, "")
    assert all(JOB_ORACLE_CODE_KEY not in t for t in plan.tasks[:-1])
    # The four arm slugs survive compilation (build fields threaded, graph keys intact).
    arm_slugs = {t.get("task") for t in plan.tasks}
    assert {"tokenize", "word-frequencies", "neighbor-pairs", "report"} <= arm_slugs


def test_generate_plan_none_override_is_byte_identical(tmp_path):
    """Passing ``decomposition_override=None`` (every production request) is identical to not
    passing it — the added param never perturbs the model path."""
    _mk_repo(tmp_path, "normalapp")

    def decomp_gen(prompt: str) -> str:
        if "decomposing a software change request" in prompt:
            return json.dumps([{"task": "core", "prompt": "build the thing"}])
        if "ACCEPTANCE CRITERIA" in prompt:
            return json.dumps([{"text": "it works", "tier": "behavior", "check": "run it"}])
        if "Classify what KIND of software" in prompt:
            return json.dumps({"surface": "command-line", "candidates": [],
                               "language_hint": "python", "complexity": "simple", "components": []})
        return "[]"

    r_default = generate_plan("a thing", "normalapp", generate_fn=decomp_gen, projects_dir=tmp_path)
    r_none = generate_plan("a thing", "normalapp", generate_fn=decomp_gen, projects_dir=tmp_path,
                           decomposition_override=None)
    assert r_default == r_none  # frozen dataclass value-equality


def test_override_bypasses_decompose_request_but_none_still_calls_it(tmp_path, monkeypatch):
    repo = _mk_repo(tmp_path, "battery-b2-text-stats")
    _mk_repo(tmp_path, "normalapp")
    calls = {"n": 0}
    real = acc.decompose_request

    def spy(*a, **k):
        calls["n"] += 1
        return real(*a, **k)

    monkeypatch.setattr(acc, "decompose_request", spy)

    # With an override → the 14B decomposer is NOT called.
    generate_plan("g", "battery-b2-text-stats", generate_fn=_fake_gen, projects_dir=tmp_path,
                  decomposition_override=_diamond_override(repo))
    assert calls["n"] == 0

    # Without an override → the model path calls it exactly once (unchanged behavior).
    def decomp_gen(prompt: str) -> str:
        if "decomposing a software change request" in prompt:
            return json.dumps([{"task": "core", "prompt": "build"}])
        return "[]"

    generate_plan("g", "normalapp", generate_fn=decomp_gen, projects_dir=tmp_path)
    assert calls["n"] == 1


# ---------------------------------------------------------------------------
# build_job_plan — the diamond BUILDS the graph (NOT the flat degrade)
# ---------------------------------------------------------------------------


def test_build_job_plan_builds_the_diamond_graph_not_the_flat_degrade(tmp_path):
    """The inverse of test_build_job_plan_single_task_degrades_to_flat_queue: a carded diamond
    (>=2 tasks, a real dependency graph, a job oracle) must BUILD the plan graph — plan != None,
    not degraded, >=4 edges and >=3 waves (the card's min_dependency_edges:4 / expects_waves_gte:3
    end to end)."""
    repo = _mk_repo(tmp_path, "battery-b2-text-stats")
    plan_result = generate_plan(
        "a little text-statistics toolkit", "battery-b2-text-stats",
        generate_fn=_fake_gen, projects_dir=tmp_path,
        decomposition_override=_diamond_override(repo),
    )
    assert plan_result.ok and len(plan_result.tasks) >= 2

    config = _swap_config(tmp_path)
    plan, store, degraded, cleaned = so.build_job_plan(config, "RB2", plan_result.tasks)

    assert plan is not None and store is not None
    assert degraded is False                       # NOT the flat degrade / not a cycle chain
    assert len(plan.tasks) >= 2
    assert _edges(plan.tasks) >= 4
    assert len(_waves(plan.tasks)) >= 3
    # The job oracle path pins the plan (popped from the driver-facing task dicts).
    assert plan.job_acceptance.oracle_path == JOB_ORACLE_PATH_PYTHON
    assert all(JOB_ORACLE_CODE_KEY not in t for t in cleaned)
    # The persisted artifact re-loads clean through the hash-verifying store.
    assert so.plan_path(config).is_file()
