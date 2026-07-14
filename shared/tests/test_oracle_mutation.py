"""#828 (QUALITY-10) — bounded offline oracle-mutation-audit locks.

The mechanism is proven two ways:

  * OFFLINE, subprocess-free (the standing-gate locks): the deterministic operator
    table + selection are pure AST, and the score/verdict logic is driven by a FAKE
    oracle runner (a vacuous oracle passes every mutant → 0/n weak; a sharp oracle
    fails every mutant → n/n strong; the advisory invariant; budget; restore).
  * REAL, hermetic (``@pytest.mark.slow``, deselected from the standing gate): a
    genuine ``python -m pytest`` run over real mutants of a real feature file —
    the true semantic proof that a vacuous oracle scores 0 and a sharp one kills.

Everything advisory-only: the audit returns an evidence dict with NO verdict field,
and a low score changes nothing (ADR-037 §Decision-1 invariant 5).
"""

from __future__ import annotations

import json
import subprocess
import sys
from types import SimpleNamespace

import pytest

from shared.fleet import oracle_mutation as om
from shared.fleet import oracle_qa
from shared.fleet.acceptance import JOB_ORACLE_PATH_NODE, JOB_ORACLE_PATH_PYTHON

# ---------------------------------------------------------------------------
# Fixtures — a small feature file with every operator's site, and its oracles
# ---------------------------------------------------------------------------

#: Feature code with a site for EVERY operator: arithmetic (a+b), a boundary
#: compare (n>0), numeric + bool constants (0/True/False), two mutable functions
#: (early-return), and an ``if`` (conditional negation). 8 mutation sites total.
_CALC = (
    "def add(a, b):\n"
    "    return a + b\n"
    "\n"
    "def is_pos(n):\n"
    "    if n > 0:\n"
    "        return True\n"
    "    return False\n"
)

#: A SHARP oracle: pins the return values AND the boundary (the n==0 case).
_SHARP_ORACLE = (
    "from calc import is_pos, add\n\n"
    "def test_pos():\n"
    "    assert is_pos(5) is True\n"
    "    assert is_pos(-3) is False\n"
    "    assert is_pos(0) is False\n\n"
    "def test_add():\n"
    "    assert add(2, 3) == 5\n"
    "    assert add(0, 0) == 0\n"
)

#: A VACUOUS oracle: a no-raise smoke that asserts nothing about the code's OUTPUT
#: (it passes #821's adequacy floor via the no-raise calls, yet catches no mutant).
_VACUOUS_ORACLE = (
    "from calc import is_pos, add\n\n"
    "def test_smoke():\n"
    "    is_pos(5)\n"
    "    add(2, 3)\n"
    "    assert 2 + 2 == 4\n"
)


def _repo(tmp_path, feature: str = _CALC):
    repo = tmp_path / "proj"
    repo.mkdir(parents=True, exist_ok=True)
    (repo / "calc.py").write_text(feature, encoding="utf-8")
    return repo


class _FakeRunner:
    """A fake oracle subprocess: call 1 is the baseline, the rest are mutants.
    Returns ``(ok, out, err)`` shaped like a pytest summary so ``_passed_count`` /
    ``_run_completed`` interpret it exactly as the real runner's output."""

    def __init__(self, baseline=(True, "1 passed in 0.01s", ""),
                 mutant=(True, "1 passed in 0.01s", "")):
        self.calls: list = []
        self.baseline = baseline
        self.mutant = mutant

    def __call__(self, cmd, cwd, timeout_s, env):
        self.calls.append((tuple(cmd), cwd, timeout_s))
        return self.baseline if len(self.calls) == 1 else self.mutant


def _fake_cmd(rel: str) -> list[str]:
    return ["FAKE-RUNNER", rel]


class _SeqClock:
    """A deterministic clock returning a fixed sequence, clamped to the last value
    (so a trailing large value keeps a budget deadline tripped)."""

    def __init__(self, seq):
        self.seq = list(seq)
        self.i = 0

    def __call__(self) -> float:
        v = self.seq[min(self.i, len(self.seq) - 1)]
        self.i += 1
        return float(v)


# ---------------------------------------------------------------------------
# The operator table — pure, deterministic, offline
# ---------------------------------------------------------------------------


def test_operator_table_covers_all_five_classes():
    ops = {op for op, _ in om.mutation_sites(_CALC)}
    assert ops == set(om.OPERATORS)  # every operator has a site on the fixture


def test_mutation_sites_deterministic():
    assert om.mutation_sites(_CALC) == om.mutation_sites(_CALC)
    assert om.mutation_sites("not python (:") == []  # unparseable → []


def test_build_mutant_each_operator_changes_source():
    # Enumerate real mutants and assert the classic textual signatures appear.
    variants = []
    for i in range(len(om.mutation_sites(_CALC))):
        m = om.build_mutant(_CALC, i)
        assert m is not None
        assert m != _CALC  # every mutant differs from the original
        variants.append(m)
    joined = "\n===\n".join(variants)
    assert "a - b" in joined          # arithmetic +→-
    assert "n >= 0" in joined         # boundary >→>=
    assert "return None" in joined    # early-return injection
    assert "not n > 0" in joined or "not (n > 0)" in joined  # conditional negation
    assert "return n + 2" not in joined  # sanity: add has names, not a constant here
    # A constant perturbation is present (0→1 in the compare, or a bool flip).
    assert ("n > 1" in joined) or ("return True" in joined and "return False" in joined)


def test_build_mutant_out_of_range_is_none():
    assert om.build_mutant(_CALC, 999) is None
    assert om.build_mutant(_CALC, -1) is None


def test_trivial_functions_get_no_early_return_site():
    trivial = "def a():\n    pass\ndef b():\n    ...\ndef c():\n    return\ndef d():\n    return None\n"
    assert not any(op == om.OP_EARLY_RETURN for op, _ in om.mutation_sites(trivial))


# ---------------------------------------------------------------------------
# Deterministic, operator-diverse, bounded selection
# ---------------------------------------------------------------------------


def test_select_is_operator_diverse_and_capped():
    pool = (
        [{"operator": om.OP_BOUNDARY, "k": i} for i in range(5)]
        + [{"operator": om.OP_ARITHMETIC, "k": i} for i in range(5)]
        + [{"operator": om.OP_CONSTANT, "k": i} for i in range(5)]
    )
    picked = om._select(pool, 3)
    assert len(picked) == 3
    # Round-robin → the first three span three distinct operators (max diversity).
    assert len({p["operator"] for p in picked}) == 3


def test_select_deterministic():
    pool = [{"operator": op, "k": i} for i in range(4) for op in om.OPERATORS]
    assert om._select(pool, 7) == om._select(pool, 7)


# ---------------------------------------------------------------------------
# THE CORE LOCKS — vacuous scores 0/n, sharp kills n/n (offline, fake runner)
# ---------------------------------------------------------------------------


def test_vacuous_oracle_scores_zero(tmp_path):
    repo = _repo(tmp_path)
    runner = _FakeRunner(mutant=(True, "1 passed", ""))  # every mutant survives
    ev = om.run_oracle_mutation_audit(
        None, "R", str(repo), JOB_ORACLE_PATH_PYTHON, _VACUOUS_ORACLE,
        run=runner, pytest_cmd=_fake_cmd, persist=False)
    assert ev["mutation_audit"] == "run"
    assert ev["ran"] == 8 and ev["killed"] == 0
    assert ev["oracle_mutation_score"] == "0/8"
    assert ev["oracle_mutation_coverage"] == "weak"  # the #828 low-score → weak stamp
    assert len(ev["survivors"]) >= 1  # survivors name WHERE the oracle is blind


def test_sharp_oracle_kills_mutants(tmp_path):
    repo = _repo(tmp_path)
    runner = _FakeRunner(mutant=(False, "1 failed", ""))  # every mutant killed
    ev = om.run_oracle_mutation_audit(
        None, "R", str(repo), JOB_ORACLE_PATH_PYTHON, _SHARP_ORACLE,
        run=runner, pytest_cmd=_fake_cmd, persist=False)
    assert ev["mutation_audit"] == "run"
    assert ev["ran"] == 8 and ev["killed"] == 8
    assert ev["oracle_mutation_score"] == "8/8"
    assert ev["oracle_mutation_coverage"] == "strong"
    assert ev["survivors"] == []


# ---------------------------------------------------------------------------
# THE ADVISORY INVARIANT — the verdict is byte-unchanged regardless of score
# ---------------------------------------------------------------------------

_FORBIDDEN_VERDICT_KEYS = {
    "verdict", "green", "banked", "status", "gate", "passed", "done", "attribution",
    "oracle_status",
}
_ADVISORY_KEYS = {
    "oracle_mutation_score", "oracle_mutation_coverage", "killed", "survived",
    "ran", "by_operator", "survivors", "mutation_audit",
}


def test_advisory_invariant_score_moves_no_verdict(tmp_path):
    repo = _repo(tmp_path)
    weak = om.run_oracle_mutation_audit(
        None, "R", str(repo), JOB_ORACLE_PATH_PYTHON, _VACUOUS_ORACLE,
        run=_FakeRunner(mutant=(True, "1 passed", "")), pytest_cmd=_fake_cmd, persist=False)
    strong = om.run_oracle_mutation_audit(
        None, "R", str(repo), JOB_ORACLE_PATH_PYTHON, _SHARP_ORACLE,
        run=_FakeRunner(mutant=(False, "1 failed", "")), pytest_cmd=_fake_cmd, persist=False)
    # 1) The audit exposes no verdict field, at ANY score.
    for ev in (weak, strong):
        assert not (set(ev) & _FORBIDDEN_VERDICT_KEYS)
    # 2) The two evidence dicts differ ONLY in advisory tally/score/band fields —
    #    everything structural (targets, planned, seed, language, budget) is byte-equal.
    differing = {k for k in set(weak) | set(strong) if weak.get(k) != strong.get(k)}
    assert differing <= _ADVISORY_KEYS, f"non-advisory field moved with the score: {differing}"


def test_module_exposes_no_verdict_authority():
    # No public symbol can move a verdict — the only entry point returns evidence.
    assert not any(
        n for n in dir(om)
        if n.startswith(("compute_", "verdict", "rewrite_", "downgrade_", "bank_"))
    )


# ---------------------------------------------------------------------------
# Budget — honest partial / skipped stamps, never a faked full score
# ---------------------------------------------------------------------------


def test_budget_expiry_before_any_mutant_is_skipped_budget(tmp_path):
    repo = _repo(tmp_path)
    # deadline base=0 (+budget 5 → 5); baseline remaining ok; first loop-check = 10 ≥ 5.
    clock = _SeqClock([0, 0] + [10] * 50)
    ev = om.run_oracle_mutation_audit(
        None, "R", str(repo), JOB_ORACLE_PATH_PYTHON, _SHARP_ORACLE,
        run=_FakeRunner(mutant=(False, "1 failed", "")), pytest_cmd=_fake_cmd,
        persist=False, budget_s=5, clock=clock)
    assert ev["mutation_audit"] == "skipped-budget"
    assert ev["ran"] == 0


def test_budget_expiry_mid_run_is_partial_budget(tmp_path):
    repo = _repo(tmp_path)
    # baseline ok; iter1 runs one mutant; iter2 loop-check trips.
    clock = _SeqClock([0, 0, 0, 0] + [10] * 50)
    ev = om.run_oracle_mutation_audit(
        None, "R", str(repo), JOB_ORACLE_PATH_PYTHON, _SHARP_ORACLE,
        run=_FakeRunner(mutant=(False, "1 failed", "")), pytest_cmd=_fake_cmd,
        persist=False, budget_s=5, clock=clock)
    assert ev["mutation_audit"] == "partial-budget"
    assert ev["ran"] == 1 and ev["killed"] == 1


# ---------------------------------------------------------------------------
# Honest fail-soft skips (baseline / machinery / language / disabled / targets)
# ---------------------------------------------------------------------------


def test_baseline_not_green_declines(tmp_path):
    repo = _repo(tmp_path)
    # exit 0 but zero passed (all-skipped seed guard / collected-0) → not a green baseline.
    runner = _FakeRunner(baseline=(True, "no tests ran in 0.01s", ""))
    ev = om.run_oracle_mutation_audit(
        None, "R", str(repo), JOB_ORACLE_PATH_PYTHON, _SHARP_ORACLE,
        run=runner, pytest_cmd=_fake_cmd, persist=False)
    assert ev["mutation_audit"] == "skipped-baseline-not-green"
    assert ev["ran"] == 0 and len(runner.calls) == 1  # never ran a mutant


def test_baseline_not_run_declines(tmp_path):
    repo = _repo(tmp_path)
    runner = _FakeRunner(baseline=(False, "", ""))  # machinery miss on the baseline
    ev = om.run_oracle_mutation_audit(
        None, "R", str(repo), JOB_ORACLE_PATH_PYTHON, _SHARP_ORACLE,
        run=runner, pytest_cmd=_fake_cmd, persist=False)
    assert ev["mutation_audit"] == "skipped-baseline-not-run"


def test_machinery_miss_mutants_not_counted(tmp_path):
    repo = _repo(tmp_path)
    # Baseline green, but every mutant run is a machinery miss (no summary) → not counted.
    runner = _FakeRunner(mutant=(False, "", ""))
    ev = om.run_oracle_mutation_audit(
        None, "R", str(repo), JOB_ORACLE_PATH_PYTHON, _SHARP_ORACLE,
        run=runner, pytest_cmd=_fake_cmd, persist=False)
    assert ev["mutation_audit"] == "run"
    assert ev["ran"] == 0 and ev["killed"] == 0
    assert ev["oracle_mutation_coverage"] == "unknown"  # nothing counted → honest unknown


def test_node_oracle_is_skipped_no_python_runner(tmp_path):
    repo = _repo(tmp_path)
    ev = om.run_oracle_mutation_audit(
        None, "R", str(repo), JOB_ORACLE_PATH_NODE, "test('x', () => {});",
        run=_FakeRunner(), pytest_cmd=_fake_cmd, persist=False)
    assert ev["mutation_audit"] == "skipped-no-python-runner"
    assert ev["language"] == "node"


def test_disabled_kill_switch_is_no_op(tmp_path, monkeypatch):
    monkeypatch.setenv("BLARAI_ORACLE_MUTATION", "0")
    assert om.oracle_mutation_enabled() is False
    runner = _FakeRunner()
    ev = om.run_oracle_mutation_audit(
        None, "R", str(_repo(tmp_path)), JOB_ORACLE_PATH_PYTHON, _SHARP_ORACLE,
        run=runner, pytest_cmd=_fake_cmd, persist=False)
    assert ev["mutation_audit"] == "skipped-disabled"
    assert runner.calls == []  # never spawned anything


def test_no_targets_declines(tmp_path):
    repo = _repo(tmp_path)
    oracle = "from totally_unbuilt import gadget\n\ndef test_g():\n    assert gadget() == 1\n"
    ev = om.run_oracle_mutation_audit(
        None, "R", str(repo), JOB_ORACLE_PATH_PYTHON, oracle,
        run=_FakeRunner(), pytest_cmd=_fake_cmd, persist=False)
    assert ev["mutation_audit"] == "skipped-no-targets"


def test_no_runner_declines(tmp_path):
    repo = _repo(tmp_path)
    ev = om.run_oracle_mutation_audit(
        None, "R", str(repo), JOB_ORACLE_PATH_PYTHON, _SHARP_ORACLE,
        run=_FakeRunner(), pytest_cmd=lambda rel: None, persist=False)
    assert ev["mutation_audit"] == "skipped-no-runner"


# ---------------------------------------------------------------------------
# The tree is left EXACTLY as found (feature + oracle restored)
# ---------------------------------------------------------------------------


def test_tree_is_restored_after_audit(tmp_path):
    repo = _repo(tmp_path)
    calc_before = (repo / "calc.py").read_bytes()
    # Pre-existing oracle content must be restored byte-for-byte.
    (repo / "tests").mkdir()
    sentinel = "# operator's pre-existing oracle bytes\n"
    (repo / JOB_ORACLE_PATH_PYTHON).write_text(sentinel, encoding="utf-8")
    om.run_oracle_mutation_audit(
        None, "R", str(repo), JOB_ORACLE_PATH_PYTHON, _SHARP_ORACLE,
        run=_FakeRunner(mutant=(False, "1 failed", "")), pytest_cmd=_fake_cmd, persist=False)
    assert (repo / "calc.py").read_bytes() == calc_before  # feature untouched
    assert (repo / JOB_ORACLE_PATH_PYTHON).read_text(encoding="utf-8") == sentinel


def test_absent_oracle_file_removed_after_audit(tmp_path):
    repo = _repo(tmp_path)
    om.run_oracle_mutation_audit(
        None, "R", str(repo), JOB_ORACLE_PATH_PYTHON, _SHARP_ORACLE,
        run=_FakeRunner(mutant=(False, "1 failed", "")), pytest_cmd=_fake_cmd, persist=False)
    # The oracle did not exist before → it is removed again (restore-to-absent).
    assert not (repo / JOB_ORACLE_PATH_PYTHON).exists()


# ---------------------------------------------------------------------------
# Evidence shape + persistence
# ---------------------------------------------------------------------------


def test_evidence_shape_and_persist(tmp_path):
    repo = _repo(tmp_path)
    config = SimpleNamespace(runs_dir=tmp_path / "runs")
    ev = om.run_oracle_mutation_audit(
        config, "RUN1", str(repo), JOB_ORACLE_PATH_PYTHON, _SHARP_ORACLE,
        run=_FakeRunner(mutant=(False, "1 failed", "")), pytest_cmd=_fake_cmd)
    assert ev["audit"] == "oracle_mutation" and ev["language"] == "python"
    assert ev["targets"] == ["calc.py"] and ev["total_sites"] == 8
    assert ev["planned"] == 8 and ev["seed"]  # a reproducibility fingerprint is stamped
    assert set(ev["by_operator"]) == set(om.OPERATORS)  # every operator was exercised
    # Persisted to <run>/oracle-mutation.json (mirrors #821's oracle-qa.json).
    written = json.loads(
        (config.runs_dir / "RUN1" / "oracle-mutation.json").read_text(encoding="utf-8"))
    assert written == ev


def test_seed_is_stable_across_runs(tmp_path):
    repo = _repo(tmp_path)
    kw = dict(run=_FakeRunner(mutant=(False, "1 failed", "")),
              pytest_cmd=_fake_cmd, persist=False)
    a = om.run_oracle_mutation_audit(None, "R", str(repo), JOB_ORACLE_PATH_PYTHON, _SHARP_ORACLE, **kw)
    b = om.run_oracle_mutation_audit(None, "R", str(repo), JOB_ORACLE_PATH_PYTHON, _SHARP_ORACLE, **kw)
    assert a["seed"] == b["seed"] and a["planned"] == b["planned"]


# ---------------------------------------------------------------------------
# Grade-parity runner + budget registration (drift locks)
# ---------------------------------------------------------------------------


def test_grade_cmd_pins_match_the_grade_path(monkeypatch):
    from pathlib import Path

    monkeypatch.setattr(om.shutil, "which", lambda n: "uv" if n == "uv" else None)
    cmd = om._grade_cmd(JOB_ORACLE_PATH_PYTHON)
    assert cmd[:3] == ["uv", "run", "--no-project"]
    assert cmd[-5:] == ["python", "-m", "pytest", "-q", JOB_ORACLE_PATH_PYTHON]
    # The pins are #821's, which its own lock ties to swap_ops' grade invocation.
    assert oracle_qa._QA_PYTEST_PIN in cmd and oracle_qa._QA_HYPOTHESIS_PIN in cmd
    grade_src = (Path(om.__file__).resolve().parents[1] / "fleet" / "swap_ops.py").read_text(
        encoding="utf-8")
    assert oracle_qa._QA_PYTEST_PIN in grade_src and oracle_qa._QA_HYPOTHESIS_PIN in grade_src


def test_grade_cmd_none_without_uv(monkeypatch):
    monkeypatch.setattr(om.shutil, "which", lambda n: None)
    assert om._grade_cmd(JOB_ORACLE_PATH_PYTHON) is None


def test_budget_constant_is_registered():
    from shared.timeout_registry import registry_names

    assert "shared.fleet.oracle_mutation:ORACLE_MUTATION_BUDGET_S" in registry_names()


# ---------------------------------------------------------------------------
# REAL, hermetic end-to-end proof (slow — deselected from the standing gate)
# ---------------------------------------------------------------------------


def _real_pytest_cmd(rel: str) -> list[str]:
    return [sys.executable, "-m", "pytest", "-q", rel, "-p", "no:cacheprovider"]


def _subprocess_pytest_available() -> bool:
    try:
        cp = subprocess.run(
            [sys.executable, "-m", "pytest", "--version"],
            capture_output=True, timeout=60)
        return cp.returncode == 0
    except Exception:  # noqa: BLE001
        return False


@pytest.mark.slow
@pytest.mark.skipif(not _subprocess_pytest_available(), reason="no subprocess pytest runner")
def test_real_end_to_end_vacuous_zero_and_sharp_kills(tmp_path):
    """The genuine semantic lock on REAL pytest + REAL mutants: a vacuous oracle
    scores 0/n (weak); a sharp oracle kills the classic mutants (strong/adequate)."""
    repo = _repo(tmp_path)
    config = SimpleNamespace(runs_dir=tmp_path / "runs")

    sharp = om.run_oracle_mutation_audit(
        config, "SHARP", str(repo), JOB_ORACLE_PATH_PYTHON, _SHARP_ORACLE,
        run=oracle_qa._default_run, pytest_cmd=_real_pytest_cmd, max_mutants=8)
    assert sharp["mutation_audit"] == "run"
    assert sharp["ran"] >= 6 and sharp["killed"] >= 1
    assert sharp["oracle_mutation_coverage"] in ("strong", "adequate")

    vacuous = om.run_oracle_mutation_audit(
        config, "VAC", str(repo), JOB_ORACLE_PATH_PYTHON, _VACUOUS_ORACLE,
        run=oracle_qa._default_run, pytest_cmd=_real_pytest_cmd, max_mutants=8)
    assert vacuous["mutation_audit"] == "run"
    assert vacuous["ran"] >= 6 and vacuous["killed"] == 0
    assert vacuous["oracle_mutation_coverage"] == "weak"

    # The real tree is left exactly as found.
    assert (repo / "calc.py").read_text(encoding="utf-8") == _CALC
    assert not (repo / JOB_ORACLE_PATH_PYTHON).exists()
