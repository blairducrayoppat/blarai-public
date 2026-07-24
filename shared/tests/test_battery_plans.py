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

The B4 section (#1008) locks the flashcards MIXED card the same way — plus the defect class
that forced it: the 14B-generated job oracle called ``data_storage.load_cards()`` without ever
importing ``data_storage`` (NameError at grade time, seven consecutive nights, the grader's own
crash charged to the coder). Every REGISTERED card oracle is AST-checked for unresolved names,
and B4's authored contract is asserted 1:1 with the oracle's imports (#989 c.2299).
"""

from __future__ import annotations

import ast
import builtins
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


def test_resolve_override_fires_for_the_real_b1_card(tmp_path):
    # B1 is a chain shape — the override must fire and supply the 3-arm plan + oracle.
    # This regression lock prevents B1 from STALLING again due to oracle-not-generated.
    ov = battery_plans.resolve_plan_override("battery-b1-expense-cli", projects_dir=tmp_path)
    assert ov is not None, (
        "B1 chain card must get an override — without it the plan has no contracts, "
        "no oracle is generated, and all-tasks-merged produces STALLED [VERIFY]"
    )
    assert len(ov.tasks) == 3, f"B1 chain must have exactly 3 arms, got {len(ov.tasks)}"
    assert ov.job_oracle_path == JOB_ORACLE_PATH_PYTHON
    assert "from app.storage import save_expense, load_expenses" in ov.job_oracle_code
    # All arms must carry the absolute repo path.
    assert all(t["repo"] == str(tmp_path / "battery-b1-expense-cli") for t in ov.tasks)
    # The first arm must declare creates/exports so generate_job_acceptance_oracle would
    # have generated an oracle from the declared contracts (structural invariant).
    store_task = ov.tasks[0]
    assert store_task["task"] == "store-expenses"
    assert store_task["contract"]["creates"], "store-expenses must declare file creates"
    assert store_task["contract"]["exports"], "store-expenses must declare function exports"


def test_resolve_override_none_for_non_battery_repo(tmp_path):
    # Fast path: a production/operator repo never reads a card.
    assert battery_plans.resolve_plan_override("rocket-calc", projects_dir=tmp_path) is None
    assert battery_plans.resolve_plan_override(
        "C:/Users/x/projects/myapp", projects_dir=tmp_path
    ) is None


def test_resolve_override_none_for_unhandled_shape_battery_card(tmp_path):
    spec = tmp_path / "spec"
    spec.mkdir()
    (spec / "B0.json").write_text(json.dumps({
        "schema": "battery-card/v1", "id": "B0", "repo": "battery-b0-linear",
        "shape": "linear", "units": 3, "goal": "a plain linear job"}), encoding="utf-8")
    assert battery_plans.resolve_plan_override(
        "battery-b0-linear", projects_dir=tmp_path, spec_dir=spec
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


# ---------------------------------------------------------------------------
# B4 (#1008) — the flashcards MIXED plan + oracle, and the unresolved-name lock
# ---------------------------------------------------------------------------

# The five `app`-package B4 module names — the 1:1 import-contract surface: each build arm
# creates exactly one of these, and the job oracle imports exactly these five.
_B4_APP_MODULES = ("data_storage", "deck_import", "card_entry", "quiz_engine", "score_tracker")


def _flashcards_override(repo: Path) -> DecompositionOverride:
    return DecompositionOverride(
        tasks=battery_plans.build_flashcards_mixed(str(repo)),
        job_oracle_code=battery_plans._FLASHCARDS_JOB_ORACLE_PY,
        job_oracle_path=JOB_ORACLE_PATH_PYTHON,
    )


def test_flashcards_decomposition_is_a_5_arm_4_wave_mixed_graph():
    arms = battery_plans.build_flashcards_mixed("C:/x/battery-b4-flashcards-cli")
    assert [t["task"] for t in arms] == [
        "store-cards", "import-deck", "add-card", "quiz", "track-scores"]
    # store -> {import, add} -> quiz -> track : exactly 5 edges, exactly 4 waves — the
    # card's min_dependency_edges:4 / expects_waves_gte:3, both cleared with margin.
    assert _edges(arms) == 5
    waves = compute_waves([{"id": t["task"], "depends_on": t["depends_on"]} for t in arms])
    assert waves == [["store-cards"], ["add-card", "import-deck"], ["quiz"], ["track-scores"]]
    by_id = {t["task"]: t for t in arms}
    assert by_id["store-cards"]["depends_on"] == []
    assert by_id["import-deck"]["depends_on"] == ["store-cards"]
    assert by_id["add-card"]["depends_on"] == ["store-cards"]
    assert set(by_id["quiz"]["depends_on"]) == {"import-deck", "add-card"}
    assert by_id["track-scores"]["depends_on"] == ["quiz"]


def test_flashcards_arms_use_the_app_package_convention():
    arms = battery_plans.build_flashcards_mixed("/repo")
    all_creates = [c for t in arms for c in t["contract"]["creates"]]
    # Every created module lives under `app` except the CLI face, which only the LAST arm
    # creates (once every module it wires exists — the parallel wave-2 siblings must never
    # share a file, or their worktree merges collide).
    assert "app/__init__.py" in all_creates
    assert "cli.py" in all_creates
    for mod in _B4_APP_MODULES:
        assert f"app/{mod}.py" in all_creates, f"missing app/{mod}.py in arm contracts"
    assert all(c.startswith("app/") or c == "cli.py" for c in all_creates)
    for t in arms:
        assert t["contract"]["creates"] and t["contract"]["exports"]
        assert isinstance(t["contract"]["notes"], str)
    assert all(t["repo"] == "/repo" for t in arms)
    assert "cli.py" in arms[-1]["contract"]["creates"]
    assert all("cli.py" not in t["contract"]["creates"] for t in arms[:-1])


def _unresolved_names(code: str) -> set[str]:
    """Names LOADED somewhere in *code* but bound nowhere in it — any import, def, parameter,
    assignment, exception name, or comprehension target counts as a binding, scope-blind.
    Deliberately an over-approximation of binding (a name bound in one function counts for
    all), so it can miss a cross-scope bug — but it exactly catches the #1008 class: a module
    referenced at a call site (``data_storage.load_cards()``) that no statement ever binds."""
    tree = ast.parse(code)
    bound: set[str] = set(dir(builtins))
    loaded: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            bound.update((a.asname or a.name).split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            bound.update(a.asname or a.name for a in node.names)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            bound.add(node.name)
        elif isinstance(node, ast.arg):
            bound.add(node.arg)
        elif isinstance(node, ast.ExceptHandler) and node.name:
            bound.add(node.name)
        elif isinstance(node, ast.Name):
            if isinstance(node.ctx, ast.Load):
                loaded.add(node.id)
            else:  # Store/Del — assignments, for/with targets, comprehension targets
                bound.add(node.id)
    return loaded - bound


@pytest.mark.parametrize("card_id", sorted(battery_plans._PLAN_BUILDERS))
def test_registered_job_oracles_import_every_name_they_reference(card_id):
    """THE #1008 regression lock: B4's model-generated oracle called
    ``data_storage.load_cards()`` without importing ``data_storage`` — NameError at grade
    time, "3 failed, 3 passed", seven consecutive nights, the grader's own crash charged to
    the coder. No REGISTERED card oracle may load a name it never binds, so the bare-
    NameError class cannot reseed through this registry."""
    _builder, oracle_code = battery_plans._PLAN_BUILDERS[card_id]
    missing = _unresolved_names(oracle_code)
    assert not missing, (
        f"{card_id} job oracle references name(s) it never imports/binds: {sorted(missing)}"
    )


def test_flashcards_contract_is_1_to_1_with_the_oracle_imports():
    """#989 c.2299: oracle import-contract coverage (modules ÷ build tasks) predicts clean
    wave distribution — and B4's model-generated contract omitted wave 1's own module. The
    authored plan must be a bijection: the oracle imports exactly the app modules the arms
    create, and each arm creates exactly ONE oracle-imported module."""
    arms = battery_plans.build_flashcards_mixed("/repo")
    tree = ast.parse(battery_plans._FLASHCARDS_JOB_ORACLE_PY)
    oracle_modules = {
        node.module.split(".", 1)[1]
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        and node.module and node.module.startswith("app.")
    }
    assert oracle_modules == set(_B4_APP_MODULES)
    owners: dict[str, str] = {}
    for t in arms:
        owned = [
            c[len("app/"):-len(".py")]
            for c in t["contract"]["creates"]
            if c.startswith("app/") and c.endswith(".py") and c != "app/__init__.py"
        ]
        assert len(owned) == 1, f"arm {t['task']!r} must own exactly one app module: {owned}"
        assert owned[0] not in owners, f"module {owned[0]!r} owned by two arms"
        owners[owned[0]] = t["task"]
    assert set(owners) == oracle_modules


def test_resolve_override_fires_for_the_real_b4_card(tmp_path):
    # Uses the committed evals/battery/B4.json (default spec dir) — the mixed shape must
    # resolve, or B4 keeps regenerating the broken model-written oracle #1008 replaced.
    ov = battery_plans.resolve_plan_override(
        "battery-b4-flashcards-cli", projects_dir=tmp_path
    )
    assert ov is not None, (
        "B4 mixed card must get an override — without it plan generation regenerates the "
        "broken model-written oracle (#1008: NameError on the unimported data_storage)"
    )
    assert len(ov.tasks) == 5, f"B4 mixed must have exactly 5 arms, got {len(ov.tasks)}"
    assert ov.job_oracle_path == JOB_ORACLE_PATH_PYTHON
    assert "from app.data_storage import save_cards, load_cards" in ov.job_oracle_code
    assert all(
        t["repo"] == str(tmp_path / "battery-b4-flashcards-cli") for t in ov.tasks
    )


def _write_reference_flashcards(repo: Path, *, storage_body: str, quiz_body: str) -> None:
    """A CORRECT reference implementation of the five arms (parametrised so a test can inject
    a BROKEN storage/quiz arm to prove the oracle has teeth)."""
    app = repo / "app"
    app.mkdir(parents=True, exist_ok=True)
    (app / "__init__.py").write_text("", encoding="utf-8")
    (app / "data_storage.py").write_text(storage_body, encoding="utf-8")
    (app / "deck_import.py").write_text(
        "from app.data_storage import load_cards, save_cards\n\n\n"
        "def import_deck(file_path, data_path=None):\n"
        "    cards = load_cards(path=data_path)\n"
        "    count = 0\n"
        "    with open(file_path, 'r', encoding='utf-8') as f:\n"
        "        for line in f:\n"
        "            line = line.strip()\n"
        "            if not line or '|' not in line:\n"
        "                continue\n"
        "            question, answer = line.split('|', 1)\n"
        "            cards.append({'question': question.strip(), 'answer': answer.strip()})\n"
        "            count += 1\n"
        "    save_cards(cards, path=data_path)\n"
        "    return count\n",
        encoding="utf-8",
    )
    (app / "card_entry.py").write_text(
        "from app.data_storage import load_cards, save_cards\n\n\n"
        "def add_card(question, answer, data_path=None):\n"
        "    if not isinstance(question, str) or not question.strip():\n"
        "        raise ValueError('question must be a non-empty string')\n"
        "    if not isinstance(answer, str) or not answer.strip():\n"
        "        raise ValueError('answer must be a non-empty string')\n"
        "    cards = load_cards(path=data_path)\n"
        "    cards.append({'question': question, 'answer': answer})\n"
        "    save_cards(cards, path=data_path)\n",
        encoding="utf-8",
    )
    (app / "quiz_engine.py").write_text(quiz_body, encoding="utf-8")
    (app / "score_tracker.py").write_text(
        "import json\n"
        "import os\n\n\n"
        "def load_scores(scores_path=None):\n"
        "    target = scores_path or 'scores.json'\n"
        "    if not os.path.exists(target):\n"
        "        return []\n"
        "    with open(target, 'r', encoding='utf-8') as f:\n"
        "        content = f.read().strip()\n"
        "    return json.loads(content) if content else []\n\n\n"
        "def record_score(correct, asked, scores_path=None):\n"
        "    target = scores_path or 'scores.json'\n"
        "    scores = load_scores(scores_path=target)\n"
        "    scores.append({'correct': correct, 'asked': asked})\n"
        "    with open(target, 'w', encoding='utf-8') as f:\n"
        "        json.dump(scores, f)\n",
        encoding="utf-8",
    )
    tests_dir = repo / "tests"
    tests_dir.mkdir(parents=True, exist_ok=True)
    (tests_dir / "test_job_acceptance.py").write_text(
        battery_plans._FLASHCARDS_JOB_ORACLE_PY, encoding="utf-8"
    )


_B4_GOOD_STORAGE = (
    "import json\n"
    "import os\n\n\n"
    "def save_cards(cards, path=None):\n"
    "    target = path or 'cards.json'\n"
    "    with open(target, 'w', encoding='utf-8') as f:\n"
    "        json.dump(cards, f)\n\n\n"
    "def load_cards(path=None):\n"
    "    target = path or 'cards.json'\n"
    "    if not os.path.exists(target):\n"
    "        return []\n"
    "    with open(target, 'r', encoding='utf-8') as f:\n"
    "        content = f.read().strip()\n"
    "    return json.loads(content) if content else []\n"
)
# A storage arm that never persists — the between-sessions promise is broken.
_B4_BROKEN_STORAGE = (
    "def save_cards(cards, path=None):\n"
    "    pass\n\n\n"
    "def load_cards(path=None):\n"
    "    return []\n"
)
_B4_GOOD_QUIZ = (
    "from app.data_storage import load_cards\n\n\n"
    "def run_quiz(answer_fn, data_path=None):\n"
    "    cards = load_cards(path=data_path)\n"
    "    correct = 0\n"
    "    for card in cards:\n"
    "        given = str(answer_fn(card['question']))\n"
    "        if given.strip().lower() == str(card['answer']).strip().lower():\n"
    "            correct += 1\n"
    "    return {'asked': len(cards), 'correct': correct}\n"
)
# A quiz arm that never checks the answer — every quiz scores zero.
_B4_BROKEN_QUIZ = (
    "from app.data_storage import load_cards\n\n\n"
    "def run_quiz(answer_fn, data_path=None):\n"
    "    cards = load_cards(path=data_path)\n"
    "    for card in cards:\n"
    "        answer_fn(card['question'])\n"
    "    return {'asked': len(cards), 'correct': 0}\n"
)


def test_flashcards_job_oracle_grades_the_integrated_flow(tmp_path):
    # (1) A CORRECT integrated tree passes — the app-package imports resolve (data_storage
    #     INCLUDED, the #1008 defect) and persist/import/add/quiz/score all hold.
    good = _mk_repo(tmp_path, "good")
    _write_reference_flashcards(good, storage_body=_B4_GOOD_STORAGE, quiz_body=_B4_GOOD_QUIZ)
    res_ok = _run_oracle(good)
    assert res_ok.returncode == 0, f"correct impl should pass:\n{res_ok.stdout}\n{res_ok.stderr}"

    # (2) A quiz that never checks answers fails — the quiz behaviour is graded, not smoke.
    quiz_broken = _mk_repo(tmp_path, "quiz_broken")
    _write_reference_flashcards(
        quiz_broken, storage_body=_B4_GOOD_STORAGE, quiz_body=_B4_BROKEN_QUIZ
    )
    res_quiz = _run_oracle(quiz_broken)
    assert res_quiz.returncode != 0, f"a non-checking quiz must fail:\n{res_quiz.stdout}"

    # (3) A storage arm that never persists fails — the between-sessions promise is graded.
    storage_broken = _mk_repo(tmp_path, "storage_broken")
    _write_reference_flashcards(
        storage_broken, storage_body=_B4_BROKEN_STORAGE, quiz_body=_B4_GOOD_QUIZ
    )
    res_store = _run_oracle(storage_broken)
    assert res_store.returncode != 0, f"a non-persisting store must fail:\n{res_store.stdout}"


def test_build_job_plan_builds_the_mixed_graph_for_b4(tmp_path):
    """The B4 analogue of the diamond graph test: the authored mixed plan flows through
    generate_plan + build_job_plan un-degraded, meeting the card's expected_outcome floor
    (min_dependency_edges:4, expects_waves_gte:3) with the job oracle pinned."""
    repo = _mk_repo(tmp_path, "battery-b4-flashcards-cli")
    plan_result = generate_plan(
        "a flashcard study program", "battery-b4-flashcards-cli",
        generate_fn=_fake_gen, projects_dir=tmp_path,
        decomposition_override=_flashcards_override(repo),
    )
    assert plan_result.ok and len(plan_result.tasks) >= 2 and not plan_result.fell_back
    assert plan_result.tasks[-1].get(JOB_ORACLE_PATH_KEY) == JOB_ORACLE_PATH_PYTHON

    config = _swap_config(tmp_path)
    plan, store, degraded, cleaned = so.build_job_plan(config, "RB4", plan_result.tasks)

    assert plan is not None and store is not None
    assert degraded is False
    assert _edges(plan.tasks) >= 4
    assert len(_waves(plan.tasks)) >= 3
    assert plan.job_acceptance.oracle_path == JOB_ORACLE_PATH_PYTHON
    assert all(JOB_ORACLE_CODE_KEY not in t for t in cleaned)
