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
# #1195 item 3 — attribution: WHICH symbol, killed by WHICH test
# ---------------------------------------------------------------------------


def test_every_site_names_its_enclosing_top_level_symbol():
    """Without this the score is whole-file and no criterion can ever claim a kill."""
    attributed = om.mutation_sites_attributed(_CALC)
    assert attributed, "the fixture must produce sites"
    assert {sym for _op, _line, sym in attributed} == {"add", "is_pos"}
    # The two-tuple contract other callers rely on is unchanged by the third element.
    assert om.mutation_sites(_CALC) == [(op, line) for op, line, _ in attributed]


def test_nested_and_method_sites_attribute_to_the_EXPORTED_name():
    """A criterion's subject can only ever be a name the oracle imported, so a site inside a
    nested helper or a method must attribute to the top-level name that contains it."""
    src = (
        "def outer(n):\n"
        "    def inner(x):\n"
        "        return x + 1\n"
        "    return inner(n)\n"
        "\n"
        "class Deck:\n"
        "    def add(self, n):\n"
        "        return n + 2\n"
    )
    assert {sym for _op, _line, sym in om.mutation_sites_attributed(src)} == {"outer", "Deck"}


def test_module_level_site_names_no_symbol():
    """Module scope is a real answer, not a missing one: it supports no rung, and must not be
    silently folded into whichever function happens to be nearby."""
    src = "LIMIT = 10\n\ndef f(n):\n    return n + 1\n"
    by_symbol = {sym for _op, _line, sym in om.mutation_sites_attributed(src)}
    assert "" in by_symbol, "a module-level constant must attribute to no symbol"
    assert "f" in by_symbol


@pytest.mark.parametrize("blob,expect", [
    # The REAL pinned runner's shapes, captured from `uv run ... python -m pytest -q`.
    ("=========================== short test summary info ====================\n"
     "FAILED tests/t.py::test_alpha - assert (1 + 1) == 3\n"
     "ERROR tests/t.py::test_setup_fails - RuntimeError: boom\n"
     "1 failed, 1 error in 0.5s", ("test_alpha", "test_setup_fails")),
    # Parametrisation is stripped: the exam's AST reader sees one `def`, not one per param.
    ("FAILED tests/t.py::test_param[2] - assert 2 == 1\n"
     "FAILED tests/t.py::test_param[3] - assert 3 == 1", ("test_param",)),
    # A class-based test reports as Class::method; the method name is the grain.
    ("FAILED tests/t.py::TestDeck::test_add - AssertionError", ("test_add",)),
    # Fallback: the FAILURES banner, when a repo config suppresses the short summary.
    ("=========== FAILURES ===========\n_________ test_beta _________\n", ("test_beta",)),
    # A collection error names no test function; it must yield nothing rather than a path.
    ("ERROR tests/t.py\n1 error in 0.1s", ()),
])
def test_failing_tests_parses_the_measured_runner_shapes(blob, expect):
    assert om.failing_tests(blob) == expect


def test_a_blind_run_names_nobody_rather_than_guessing():
    """`addopts = -rN --tb=no` suppresses BOTH the summary and the traceback — measured on the
    pinned runner. The RED/GREEN answer survives (it is the exit code); the attribution does
    not, and an empty answer must mean "cannot attribute", never "nothing failed"."""
    assert om.failing_tests("E.F   [100%]\n1 failed, 1 passed, 1 error in 0.01s") == ()
    assert om.failing_tests("") == ()


def test_killed_mutants_record_who_killed_them(tmp_path):
    """The row that makes L4 possible: outcome + symbol + the failing test names."""
    repo = _repo(tmp_path)
    blob = "FAILED tests/t.py::test_pos - assert False\n1 failed in 0.1s"
    ev = om.run_oracle_mutation_audit(
        None, "R", str(repo), JOB_ORACLE_PATH_PYTHON, _SHARP_ORACLE,
        run=_FakeRunner(mutant=(False, blob, "")), pytest_cmd=_fake_cmd, persist=False)
    rows = ev[om.EV_MUTANTS]
    assert len(rows) == ev["ran"] == 8
    assert all(r["outcome"] == "killed" for r in rows)
    assert all(r["killed_by"] == ["test_pos"] for r in rows)
    assert {r["symbol"] for r in rows} == {"add", "is_pos"}
    assert ev[om.EV_ORACLE_SHA] == om.oracle_digest(_SHARP_ORACLE)


def test_surviving_mutants_record_the_symbol_they_slipped_past(tmp_path):
    repo = _repo(tmp_path)
    ev = om.run_oracle_mutation_audit(
        None, "R", str(repo), JOB_ORACLE_PATH_PYTHON, _VACUOUS_ORACLE,
        run=_FakeRunner(mutant=(True, "1 passed", "")), pytest_cmd=_fake_cmd, persist=False)
    rows = ev[om.EV_MUTANTS]
    assert rows and all(r["outcome"] == "survived" for r in rows)
    assert all(r["killed_by"] == [] for r in rows)
    assert all(r["symbol"] in {"add", "is_pos"} for r in rows)
    # The survivors list gains the symbol too, so the whole-file summary can name it.
    assert all("symbol" in s for s in ev["survivors"])


def test_a_kill_nobody_claims_is_recorded_as_unclaimed(tmp_path):
    """A RED run whose failing tests could not be parsed still COUNTS as a kill (the exit code
    is unambiguous) but names nobody. Reading that as evidence for a criterion would be the
    fail-open this whole rung exists to refuse."""
    repo = _repo(tmp_path)
    ev = om.run_oracle_mutation_audit(
        None, "R", str(repo), JOB_ORACLE_PATH_PYTHON, _SHARP_ORACLE,
        run=_FakeRunner(mutant=(False, "1 failed in 0.01s", "")), pytest_cmd=_fake_cmd,
        persist=False)
    assert ev["killed"] == 8, "the kill still counts toward the whole-file score"
    assert all(r["killed_by"] == [] for r in ev[om.EV_MUTANTS])


def test_a_skipped_audit_banks_the_attribution_shape_empty(tmp_path):
    """Key ABSENCE must never be how a consumer learns attribution is missing — an audit that
    predates the feature and one that ran and attributed nothing would look alike."""
    ev = om.not_measured_evidence(JOB_ORACLE_PATH_PYTHON, "skipped-no-delivered-tree")
    assert ev[om.EV_MUTANTS] == [] and ev[om.EV_ORACLE_SHA] == ""
    assert ev[om.EV_ORACLE_PATH] == JOB_ORACLE_PATH_PYTHON


def test_oracle_digest_distinguishes_two_exams():
    assert om.oracle_digest(_SHARP_ORACLE) != om.oracle_digest(_VACUOUS_ORACLE)
    assert om.oracle_digest(_SHARP_ORACLE) == om.oracle_digest(_SHARP_ORACLE)


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
    # #1195 item 3: the per-mutant attribution rows and the digest of the exam they came
    # from. Both move with the score by construction (a different exam kills differently) and
    # neither is a verdict — the traceability ladder GRADES from them; it is not told a result.
    om.EV_MUTANTS, om.EV_ORACLE_SHA,
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
# #1231 — a tighter budget must never make the audit look BETTER
# ---------------------------------------------------------------------------


class _MixedRunner:
    """Baseline passes; then mutants alternate KILLED / SURVIVED.

    The pre-existing budget locks use a sharp runner that kills every mutant, which
    pins the score at a 100% ceiling — a ceiling cannot detect inflation, so those
    tests passed happily while the band rose as the budget fell. A mixed verdict is
    what makes the defect observable at all."""

    def __init__(self) -> None:
        self.calls: list = []

    def __call__(self, cmd, cwd, timeout_s, env):
        self.calls.append((tuple(cmd), cwd, timeout_s))
        if len(self.calls) == 1:
            return (True, "1 passed in 0.01s", "")
        # even-numbered mutant calls fail (oracle RED -> killed), odd ones pass (survived)
        return ((False, "1 failed in 0.01s", "") if len(self.calls) % 2 == 0
                else (True, "1 passed in 0.01s", ""))


_BAND_RANK = {"unknown": -1, "weak": 0, "adequate": 1, "strong": 2}


def _run_with_clock(repo, clock):
    return om.run_oracle_mutation_audit(
        None, "R", str(repo), JOB_ORACLE_PATH_PYTHON, _SHARP_ORACLE,
        run=_MixedRunner(), pytest_cmd=_fake_cmd,
        persist=False, budget_s=5, clock=clock)


def test_tightening_the_budget_cannot_raise_the_coverage_band(tmp_path):
    """The defect, stated as an invariant: doing LESS work must not report BETTER
    coverage. Before #1231 the band was killed/ran, so dropping every mutant the
    oracle would have survived left a 1/1 'strong' behind."""
    full = _run_with_clock(_repo(tmp_path), _SeqClock([0] * 400))
    # base + baseline-remaining + (loop-check, remaining) per mutant, then the check
    # that trips: one mutant runs, the rest are dropped.
    tight = _run_with_clock(_repo(tmp_path), _SeqClock([0, 0, 0, 0] + [10] * 400))

    assert full["mutation_audit"] == "run"
    assert tight["mutation_audit"] == "partial-budget"
    assert tight["ran"] < full["ran"], "the tight run must actually have dropped mutants"
    assert tight["not_run"] > 0

    assert _BAND_RANK[tight["oracle_mutation_coverage"]] <= _BAND_RANK[full["oracle_mutation_coverage"]], (
        f"a tighter budget reported a BETTER band: {tight['oracle_mutation_coverage']} "
        f"(ran {tight['ran']}, dropped {tight['not_run']}) vs "
        f"{full['oracle_mutation_coverage']} (ran {full['ran']})"
    )


def test_dropped_mutants_are_counted_not_forgotten(tmp_path):
    """A reader must be able to see how much of the audit actually happened rather than
    inferring completeness from a bare score.

    ``planned`` is the authority on the selection size -- an earlier draft of this fix
    added a second ``selected`` key derived as ran+not_run, which reported 0 for a run
    that planned 8 mutants and lost all 8 to machinery misses. Two keys for one fact
    disagree the moment anything takes a third path."""
    tight = _run_with_clock(_repo(tmp_path), _SeqClock([0, 0, 0, 0] + [10] * 400))

    assert tight["not_run"] > 0
    assert tight["planned"] == tight["ran"] + tight["not_run"] + tight["unreachable"], (
        "every selected mutant must land in exactly one bucket"
    )
    # The score still describes what RAN -- it is not retconned into a completeness claim.
    assert tight["oracle_mutation_score"] == f"{tight['killed']}/{tight['ran']}"


class _NoVerdictAfterN:
    """Baseline passes, the first ``n_ok`` mutants are KILLED, the rest return a blob the
    verdict parser cannot read — the shape a per-mutant timeout produces in production."""

    def __init__(self, n_ok: int = 0) -> None:
        self.calls = 0
        self.n_ok = n_ok

    def __call__(self, cmd, cwd, timeout_s, env):
        self.calls += 1
        if self.calls == 1:
            return (True, "1 passed in 0.01s", "")
        if self.calls - 1 <= self.n_ok:
            return (False, "1 failed in 0.01s", "")  # oracle RED -> killed
        return (False, "ERROR: could not start interpreter", "")  # no readable verdict


def test_the_three_buckets_reconcile_against_planned(tmp_path):
    """``planned`` is the authority on the selection size; every mutant lands in exactly
    one of ran / not_run / unreachable. An earlier cut of this fix added a ``selected`` key
    derived as ran+not_run, which reported 0 for a run that planned 8 and lost all 8 to
    machinery misses -- two keys for one fact disagree as soon as a third path exists."""
    ev = om.run_oracle_mutation_audit(
        None, "R", str(_repo(tmp_path)), JOB_ORACLE_PATH_PYTHON, _SHARP_ORACLE,
        run=_NoVerdictAfterN(0), pytest_cmd=_fake_cmd, persist=False, budget_s=999)

    assert ev["planned"] > 0
    assert ev["ran"] == 0 and ev["not_run"] == 0
    assert ev["unreachable"] == ev["planned"], "every mutant was unreachable here"
    assert ev["planned"] == ev["ran"] + ev["not_run"] + ev["unreachable"]


def test_unreadable_verdicts_cannot_report_a_complete_strong_audit(tmp_path):
    """The sibling of the budget defect, and a WORSE claim: with no budget pressure the
    stamp said ``run`` -- asserting completeness outright -- while 7 of 8 mutants had
    timed out and the band read ``strong`` off a 1/1 score."""
    ev = om.run_oracle_mutation_audit(
        None, "R", str(_repo(tmp_path)), JOB_ORACLE_PATH_PYTHON, _SHARP_ORACLE,
        run=_NoVerdictAfterN(1), pytest_cmd=_fake_cmd, persist=False, budget_s=10 ** 9)

    assert ev["ran"] == 1 and ev["killed"] == 1  # everything that got a verdict was killed
    assert ev["unreachable"] > 0
    assert ev["mutation_audit"] != "run", (
        "'run' asserts the audit completed; mutants the machinery never reached mean it did not"
    )
    assert ev["mutation_audit"] == "partial-machinery"
    assert ev["oracle_mutation_coverage"] != "strong", (
        "a 1/1 score over 8 selected mutants reported 'strong' with no partial stamp at all"
    )


def test_unreachable_mutants_get_no_verdict_rows(tmp_path):
    """They must be visible downstream, and must never look like a subject that was tested."""
    ev = om.run_oracle_mutation_audit(
        None, "R", str(_repo(tmp_path)), JOB_ORACLE_PATH_PYTHON, _SHARP_ORACLE,
        run=_NoVerdictAfterN(1), pytest_cmd=_fake_cmd, persist=False, budget_s=10 ** 9)

    rows = ev[om.EV_MUTANTS]
    assert [r["outcome"] for r in rows].count("no-verdict") == ev["unreachable"]
    assert len(rows) == ev["planned"], "every selected mutant needs a row"
    for row in rows:
        if row["outcome"] == "no-verdict":
            assert row["killed_by"] == []


def test_the_second_break_site_also_records_its_dropped_mutants(tmp_path):
    """There are TWO budget exits. The loop-head check and the post-write ``remaining``
    check. An independent review found only the first was reached by any test: deleting the
    second site's bookkeeping left the whole suite green, so the fixed defect could have
    been reintroduced there silently."""
    # call 4 is the `remaining` read -- 10 >= deadline 5 trips the SECOND site, at idx 0.
    ev = _run_with_clock(_repo(tmp_path), _SeqClock([0, 0, 0, 10] + [10] * 400))

    assert ev["ran"] == 0
    assert ev["not_run"] == ev["planned"], (
        "the mutant in flight when the second budget check tripped must be recorded too"
    )
    assert ev["mutation_audit"] == "skipped-budget"


def test_the_second_break_site_mid_run_keeps_the_counts_disjoint(tmp_path):
    """The in-flight item breaks BEFORE ``ran += 1``, so it belongs to not_run and must not
    also be counted as run -- the double-count this slicing could easily have introduced."""
    ev = _run_with_clock(_repo(tmp_path), _SeqClock([0, 0, 0, 0, 0, 10] + [10] * 400))

    assert ev["ran"] >= 1 and ev["not_run"] >= 1
    assert ev["planned"] == ev["ran"] + ev["not_run"] + ev["unreachable"]
    sites = [(r["file"], r["line"], r["operator"]) for r in ev[om.EV_MUTANTS]]
    assert len(sites) == len(set(sites)), "a mutant was recorded twice"


def test_dropped_mutants_appear_as_not_run_rows(tmp_path):
    """A partial audit must not LOOK complete to a downstream reader of EV_MUTANTS."""
    tight = _run_with_clock(_repo(tmp_path), _SeqClock([0, 0, 0, 0] + [10] * 400))

    rows = tight[om.EV_MUTANTS]
    outcomes = [r["outcome"] for r in rows]
    assert outcomes.count("not-run") == tight["not_run"]
    assert len(rows) == tight["ran"] + tight["not_run"], "every accounted mutant needs a row"
    for row in rows:
        if row["outcome"] == "not-run":
            assert row["killed_by"] == [], "a mutant that never ran cannot name a killer"


def test_a_band_of_strong_requires_every_selected_mutant_to_have_run(tmp_path):
    """The sharp-oracle case: 100% of what ran was killed, but not everything ran.
    'strong' would be a claim about mutants nobody tried."""
    repo = _repo(tmp_path)
    ev = om.run_oracle_mutation_audit(
        None, "R", str(repo), JOB_ORACLE_PATH_PYTHON, _SHARP_ORACLE,
        run=_FakeRunner(mutant=(False, "1 failed", "")), pytest_cmd=_fake_cmd,
        persist=False, budget_s=5, clock=_SeqClock([0, 0, 0, 0] + [10] * 400))

    assert ev["killed"] == ev["ran"] == 1  # everything that ran was killed
    assert ev["not_run"] > 0
    assert ev["oracle_mutation_coverage"] != "strong", (
        "a 1/1 score with dropped mutants reported 'strong' -- the exact inflation #1231 fixes"
    )


def test_nothing_ran_stays_unknown_rather_than_weak(tmp_path):
    """Fail-closed must not overshoot into asserting a finding. With zero attempts the
    audit has no opinion; reporting 'weak' would convict an oracle nobody examined."""
    ev = om.run_oracle_mutation_audit(
        None, "R", str(_repo(tmp_path)), JOB_ORACLE_PATH_PYTHON, _SHARP_ORACLE,
        run=_FakeRunner(mutant=(False, "1 failed", "")), pytest_cmd=_fake_cmd,
        persist=False, budget_s=5, clock=_SeqClock([0, 0] + [10] * 400))

    assert ev["ran"] == 0
    assert ev["mutation_audit"] == "skipped-budget"
    assert ev["oracle_mutation_coverage"] == "unknown"


def test_band_counts_unrun_mutants_against_the_score():
    """The unit-level statement of the rule, independent of the audit's plumbing."""
    assert om._band(4, 4, 0) == "strong"
    assert om._band(4, 4, 16) == "weak", "16 unattempted mutants must not read as strong"
    assert om._band(9, 10, 0) == "adequate"
    assert om._band(9, 10, 40) == "weak"
    assert om._band(0, 0, 20) == "unknown", "no attempts means no opinion, not a bad one"


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
    """Baseline green, every mutant run a machinery miss (no summary) → not counted.

    This test asserted ``mutation_audit == "run"`` until #1231. That was the defect
    written down as expected behaviour: ``run`` asserts the audit COMPLETED, and here it
    reached none of its mutants. The stamp is now ``skipped-machinery`` (``ran == 0``),
    or ``partial-machinery`` when some mutants did get a verdict. A baseline that encodes
    the bug is the one place a green suite actively defends it.
    """
    repo = _repo(tmp_path)
    runner = _FakeRunner(mutant=(False, "", ""))
    ev = om.run_oracle_mutation_audit(
        None, "R", str(repo), JOB_ORACLE_PATH_PYTHON, _SHARP_ORACLE,
        run=runner, pytest_cmd=_fake_cmd, persist=False)
    assert ev["mutation_audit"] == "skipped-machinery"
    assert ev["ran"] == 0 and ev["killed"] == 0
    assert ev["unreachable"] == ev["planned"]
    assert ev["oracle_mutation_coverage"] == "unknown"  # nothing counted → honest unknown
    assert not om.is_measured(ev), "an audit that reached no mutant is not a measurement"


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
