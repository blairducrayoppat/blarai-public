"""Requirement → oracle-assertion traceability (the coverage a GREEN actually PROVED).

Design SSOT: ``docs/design/oracle_coverage_traceability_DESIGN.md``.

The suites here lock the four things that make this instrument trustworthy rather than
merely present:

* **The ladder discriminates** — each level fires on evidence that justifies it, and the
  TOGGLE half (security principle 12) proves each probe FAILS to fire once that evidence is
  removed. Without the toggle, "covered" cannot be distinguished from "the check could not
  reach the code".
* **Not-knowing never reads as passing** — an undecidable criterion blocks ``GREEN-VERIFIED``
  through the REAL ``classify_green`` entry point, not a helper.
* **Anti-tuning** — the covered set may not grow to include the mapper's say-so (L1), and a
  saturating declaration must not reach ``GREEN-VERIFIED`` on the real B2 oracle shape. These
  fail loudly if a future session widens the predicate to make the class easier to earn.
* **Coverage is never minted** — the two ways a lenient predicate hands out L3 for nothing
  (an assertion that bears on no subject, and a symbol the deliverable never wrote) each get
  their own suite below, with the toggle half proving the honest shape still scores.
* **Fail-soft** — every unusable input yields ``available=False`` with a reason, never a
  number that could be mistaken for a score.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import pytest

from tools.dispatch_harness import failure_taxonomy as ftax
from tools.dispatch_harness import scorecard as scorecard_mod
from tools.dispatch_harness.green_quality import traceability as tr
from tools.dispatch_harness.scorecard import Scorecard

# ---------------------------------------------------------------------------
# Fixtures — the real 2026-07-29 B2 shape, reduced to what the instrument reads
# ---------------------------------------------------------------------------

#: The B2 text-stats oracle shape: a criterion whose wording names its symbol (c3), one that
#: names a symbol never exercised (c4 -> a real GAP), and one whose wording names nothing (c5).
B2_ORACLE = '''
from stats.tokenize import tokenize
from stats.frequency import word_frequencies
from stats.pairs import neighbor_pairs

def test_word_frequencies_counts_each_word():
    assert word_frequencies(["a", "a", "b"]) == {"a": 2, "b": 1}

def test_tokenize_runs():
    tokenize("hello world")
'''

B2_CRITERIA = [
    {"id": "c1", "text": "The code should compile and install.", "tier": "build", "check": ""},
    {"id": "c3", "text": "The word frequency count should be accurate.",
     "tier": "behavior", "check": "Compare the frequency output with known results."},
    {"id": "c4", "text": "The neighbor pairs count should identify frequent pairs.",
     "tier": "behavior", "check": ""},
    {"id": "c5", "text": "It should not crash on empty or invalid data.",
     "tier": "smoke", "check": ""},
    {"id": "c8", "text": "The report should look tidy.", "tier": "visual", "check": ""},
]


def _index(*roots: str) -> tr.FirstPartyIndex:
    """A resolved first-party surface, standing in for what a delivered tree provides."""
    return tr.FirstPartyIndex.from_roots(set(roots), source="test fixture")


#: The B2 deliverable ships one package, ``stats``; the smaller fixtures below ship ``app``.
#: Every ``assess`` call names its index explicitly — there is no ambient default, because the
#: absence of one is the point: nothing is the deliverable's until a tree says so.
B2_INDEX = _index("stats")
APP_INDEX = _index("app")


def _levels(result: tr.TraceabilityResult) -> dict:
    return {c.criterion_id: c.level for c in result.criteria}


def _seed_run(d: Path, *, oracle: str = B2_ORACLE, criteria: "list[dict] | None" = None,
              probe_modules: "tuple[str, ...]" = ("stats.frequency",),
              unresolved: "list[dict] | None" = None) -> Path:
    """A run directory in the shape a dispatch actually banks: the spec, the seeded oracle,
    and the #822 resolve-probe pair that establishes which modules the delivered tree
    provided. Written rather than mocked so ``resolve_first_party`` is driven for real."""
    d.mkdir(parents=True, exist_ok=True)
    (d / "acceptance.json").write_text(
        json.dumps({"spec": {"goal": "g", "criteria": criteria if criteria is not None
                             else B2_CRITERIA}}), encoding="utf-8")
    (d / "job-oracle-test_job_acceptance.py").write_text(oracle, encoding="utf-8")
    (d / "import-probe-targets.json").write_text(
        json.dumps([{"kind": "py", "module": m, "spec": "", "level": 0, "names": [],
                     "raw": f"import {m}"} for m in probe_modules]), encoding="utf-8")
    (d / "import-probe-verdict.json").write_text(
        json.dumps({"ok": not unresolved, "unresolved": unresolved or [],
                    "probed": len(probe_modules), "skipped": 0}), encoding="utf-8")
    return d


# ---------------------------------------------------------------------------
# The denominator
# ---------------------------------------------------------------------------


def test_denominator_is_test_tier_only_and_says_so():
    """build/visual/human criteria are excluded by construction — and the exclusion rides on
    the block, so the figure cannot be quoted as "all the criteria"."""
    result = tr.assess(B2_ORACLE, B2_CRITERIA, first_party=B2_INDEX)
    assert result.available
    assert result.denominator == 3                      # c3, c4, c5 — not c1/c8
    assert set(_levels(result)) == {"c3", "c4", "c5"}
    assert set(result.to_block()["denominator_excludes"]) == {"build", "visual", "human"}


def test_no_test_tier_criteria_is_unavailable_never_a_score():
    """A spec with nothing a pytest oracle can verify has no coverage — it must not read as
    0/0 or as a pass."""
    result = tr.assess(B2_ORACLE, [c for c in B2_CRITERIA if c["tier"] == "visual"],
                       first_party=B2_INDEX)
    assert not result.available
    assert "no test-tier" in result.reason
    assert "unavailable" in result.fingerprint()


# ---------------------------------------------------------------------------
# The ladder — each level fires on its own evidence
# ---------------------------------------------------------------------------


def test_l3_asserted_when_the_subject_is_exercised_and_something_is_asserted():
    result = tr.assess(B2_ORACLE, B2_CRITERIA, first_party=B2_INDEX)
    assert _levels(result)["c3"] == tr.LEVEL_ASSERTED
    assert result.verified == 1


def test_l0_gap_when_the_subject_binds_but_no_test_touches_it():
    """c4's subject `neighbor_pairs` is imported and named by the criterion, yet no test
    exercises it. That is a real, nameable hole — not an undecidable."""
    result = tr.assess(B2_ORACLE, B2_CRITERIA, first_party=B2_INDEX)
    assert _levels(result)["c4"] == tr.LEVEL_GAP
    assert result.gap == 1


def test_l2_bound_when_the_subject_is_called_but_nothing_is_asserted():
    """`tokenize` is exercised by a test that asserts nothing — bound, not verified."""
    criteria = [{"id": "cX", "text": "The tokenize step should split text.",
                 "tier": "behavior", "check": ""}]
    result = tr.assess(B2_ORACLE, criteria, first_party=B2_INDEX)
    assert _levels(result)["cX"] == tr.LEVEL_BOUND
    assert result.verified == 0 and result.weak == 1


def test_undecidable_when_the_criterion_names_no_symbol():
    """c5 ("should not crash on empty or invalid data") names nothing in the oracle's
    vocabulary. Neither covered nor a gap."""
    result = tr.assess(B2_ORACLE, B2_CRITERIA, first_party=B2_INDEX)
    assert _levels(result)["c5"] == tr.LEVEL_UNDECIDABLE
    assert result.undecidable == 1


def test_pytest_raises_counts_as_an_assertion():
    """`with pytest.raises(...)` carries no `assert` keyword and is still an assertion —
    reading such a test as assertion-free would demote genuine verification to L2."""
    code = (
        "import pytest\n"
        "from app.card_entry import add_card\n"
        "def test_add_card_rejects_empty_input():\n"
        "    with pytest.raises(ValueError):\n"
        "        add_card('', 'x')\n"
    )
    criteria = [{"id": "c1", "text": "add card must reject empty entries.",
                 "tier": "behavior", "check": ""}]
    assert _levels(tr.assess(code, criteria, first_party=APP_INDEX))["c1"] == tr.LEVEL_ASSERTED


#: The commonest sound shape: the subject is called for its EFFECT, and the assertion runs
#: over a value read back afterwards. Neither assert names ``add_card``, yet ``add_card`` is
#: exactly what the test verifies — the chain ``path -> loaded`` is what carries the evidence.
INDIRECT_ORACLE = (
    "from app.card_entry import add_card\n"
    "from app.data_storage import load_cards\n"
    "def test_add_card_appends(tmp_path):\n"
    "    path = tmp_path / 'cards.json'\n"
    "    add_card(path, 'q', 'a')\n"
    "    loaded = load_cards(path)\n"
    "    assert len(loaded) == 1\n"
)

INDIRECT_CRITERIA = [{"id": "c1", "text": "add card must append to the stored cards.",
                      "tier": "behavior", "check": ""}]


def test_assertion_through_a_local_still_counts():
    """Requiring the subject's NAME inside the assert expression would score real
    verification as L2, so the trace follows the dataflow: ``path`` is handed to the subject,
    ``loaded`` is derived from ``path``, and the assertion over ``loaded`` therefore bears on
    ``add_card``."""
    assert _levels(tr.assess(INDIRECT_ORACLE, INDIRECT_CRITERIA,
                             first_party=APP_INDEX))["c1"] == tr.LEVEL_ASSERTED


def test_transitive_indirection_survives_several_hops():
    """The chain is followed as far as it goes, not one link: taint accumulates through each
    binding, so a subject three assignments upstream of the assertion still counts."""
    code = (
        "from app.report import build_report\n"
        "def test_report():\n"
        "    raw = build_report(['a'])\n"
        "    lines = raw.splitlines()\n"
        "    first = lines[0]\n"
        "    assert 'a' in first\n"
    )
    criteria = [{"id": "c1", "text": "The build report step must list each entry.",
                 "tier": "behavior", "check": ""}]
    assert _levels(tr.assess(code, criteria, first_party=APP_INDEX))["c1"] == tr.LEVEL_ASSERTED


def test_multi_subject_criterion_needs_every_subject_exercised():
    """A criterion naming several symbols must not bank on whichever one happened to bind
    while the symbol it is centrally about goes untested."""
    code = (
        "from app.a import word_frequencies\n"
        "from app.b import combined_report\n"
        "def test_freq():\n"
        "    assert word_frequencies(['a']) == {'a': 1}\n"
    )
    criteria = [{"id": "c1",
                 "text": "The combined report should present the word frequencies.",
                 "tier": "behavior", "check": ""}]
    row = tr.assess(code, criteria, first_party=APP_INDEX).criteria[0]
    assert row.level == tr.LEVEL_BOUND
    assert "combined_report" in row.reason


# ---------------------------------------------------------------------------
# TOGGLE — every probe must FAIL to fire once its evidence is removed (principle 12)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "mutation,expect",
    [
        # Remove the assertion -> L3 must fall to L2 (the probe cannot still claim verified).
        (lambda s: s.replace(
            'assert word_frequencies(["a", "a", "b"]) == {"a": 2, "b": 1}',
            'word_frequencies(["a", "a", "b"])'), tr.LEVEL_BOUND),
        # Remove the test entirely -> L3 must fall to L0-GAP.
        (lambda s: s.replace(
            'def test_word_frequencies_counts_each_word():\n'
            '    assert word_frequencies(["a", "a", "b"]) == {"a": 2, "b": 1}\n', ""),
         tr.LEVEL_GAP),
        # Remove the import -> the symbol is no longer first-party, nothing binds -> UNDECIDABLE.
        (lambda s: s.replace("from stats.frequency import word_frequencies\n", ""),
         tr.LEVEL_UNDECIDABLE),
    ],
)
def test_toggle_each_level_stops_firing_without_its_evidence(mutation, expect):
    """The lock-off half: with the evidence removed the probe must report a WEAKER level.
    A probe that keeps reporting L3 here is not measuring — it is asserting."""
    baseline = tr.assess(B2_ORACLE, B2_CRITERIA, first_party=B2_INDEX)
    assert _levels(baseline)["c3"] == tr.LEVEL_ASSERTED, "baseline must start verified"
    weakened = tr.assess(mutation(B2_ORACLE), B2_CRITERIA, first_party=B2_INDEX)
    assert _levels(weakened)["c3"] == expect
    assert weakened.verified < baseline.verified


# ---------------------------------------------------------------------------
# NEVER MINT (1) — the assertion must BEAR ON the subject, not merely co-exist with it
# ---------------------------------------------------------------------------

#: A test that touches the subject and asserts — about nothing. Under the predicate this
#: replaced ("the test asserts SOMETHING") it scored `1/1 L3+` and `verified_class: True`.
TOUCH_ONLY_ORACLE = (
    "from stats.frequency import word_frequencies\n"
    "def test_touches_it():\n"
    "    result = word_frequencies(['a', 'b'])\n"
    "    assert True\n"
)

FREQ_CRITERIA = [{"id": "c1", "text": "The word frequency count should be accurate.",
                  "tier": "behavior", "check": ""}]


def test_assert_true_never_reaches_l3():
    """`assert True` is an assertion about nothing. Counting it is not a precision loss, it
    is coverage minted from a keyword — the one thing this module's invariant forbids."""
    result = tr.assess(TOUCH_ONLY_ORACLE, FREQ_CRITERIA, first_party=B2_INDEX)
    row = result.criteria[0]
    assert row.level == tr.LEVEL_BOUND
    assert result.verified == 0 and not result.verified_class
    assert "no assertion bears on the subject" in row.reason


def test_an_assertion_about_a_different_symbol_never_reaches_l3():
    """A test may assert loudly and correctly about `tokenize` while calling
    `word_frequencies` for its side effects. That is evidence about `tokenize`, and crediting
    the criterion about frequencies with it is a borrowed proof."""
    code = (
        "from stats.frequency import word_frequencies\n"
        "from stats.tokenize import tokenize\n"
        "def test_tokenize_only():\n"
        "    word_frequencies(['a'])\n"
        "    assert tokenize('a b') == ['a', 'b']\n"
    )
    row = tr.assess(code, FREQ_CRITERIA, first_party=B2_INDEX).criteria[0]
    assert row.level == tr.LEVEL_BOUND
    assert row.subjects == ("word_frequencies",)


def test_the_bound_reason_names_which_kind_of_weakness_it_found():
    """L2 has two distinct causes and a reader must be able to tell them apart: a test that
    asserts nothing at all, and a test that asserts about something else. Collapsing them is
    how the weaker case hid."""
    silent = tr.assess(
        "from stats.frequency import word_frequencies\n"
        "def test_runs():\n"
        "    word_frequencies(['a'])\n", FREQ_CRITERIA, first_party=B2_INDEX).criteria[0]
    noisy = tr.assess(TOUCH_ONLY_ORACLE, FREQ_CRITERIA, first_party=B2_INDEX).criteria[0]
    assert silent.level == noisy.level == tr.LEVEL_BOUND
    assert "asserts nothing" in silent.reason
    assert "does assert" in noisy.reason


def test_toggle_cutting_the_dataflow_chain_drops_the_indirect_case_to_l2():
    """The lock-off half for the dataflow trace. With the shared handle removed the two calls
    no longer have anything to do with each other, and the honest answer is L2 — so the L3 in
    :func:`test_assertion_through_a_local_still_counts` is measured, not assumed."""
    cut = INDIRECT_ORACLE.replace("add_card(path, 'q', 'a')", "add_card('q', 'a')")
    assert _levels(tr.assess(INDIRECT_ORACLE, INDIRECT_CRITERIA,
                             first_party=APP_INDEX))["c1"] == tr.LEVEL_ASSERTED
    assert _levels(tr.assess(cut, INDIRECT_CRITERIA,
                             first_party=APP_INDEX))["c1"] == tr.LEVEL_BOUND


# ---------------------------------------------------------------------------
# NAMED CREDIT PATHS — known over-credits, retained on purpose, pinned so they cannot drift
# ---------------------------------------------------------------------------
#
# These tests assert what the instrument DOES, not what it should ideally do. They exist
# because an undocumented credit path is how the predicate this module replaced went wrong: a
# limit written only in a docstring can quietly stop being true, where a limit with a test
# fails the moment someone changes it and forces the change to be deliberate. If a future
# session tightens either rule, these SHOULD fail — update them, do not delete them.


def test_named_credit_path_an_input_only_assertion_reaches_l3():
    """The argument-taint rule cannot tell an assertion about what the subject PRODUCED from
    one about what it was GIVEN, so asserting the input is unchanged credits the subject.

    The second half is why the rule stays: it is the same mechanism that carries the genuine
    `export_to_spreadsheet(inv, file_path); assert file_path.exists()` shape, which is real in
    the banked corpus. Removing the disjunct closes the first case and reopens the second, so
    both are asserted together — a future session weighing the trade sees both halves fail."""
    over_credited = (
        "from stats.frequency import word_frequencies\n"
        "def test_x():\n"
        "    data = ['a', 'b']\n"
        "    word_frequencies(data)\n"
        "    assert data == ['a', 'b']\n"        # nothing about the frequency count
    )
    assert _levels(tr.assess(over_credited, FREQ_CRITERIA,
                             first_party=B2_INDEX))["c1"] == tr.LEVEL_ASSERTED

    genuine = (
        "from stats.report import export_to_spreadsheet\n"
        "def test_export(tmp_path):\n"
        "    file_path = tmp_path / 'out.csv'\n"
        "    export_to_spreadsheet({'a': 1}, file_path)\n"
        "    assert file_path.exists()\n"
    )
    criteria = [{"id": "c1", "text": "The program must export to a spreadsheet file.",
                 "tier": "behavior", "check": ""}]
    assert _levels(tr.assess(genuine, criteria,
                             first_party=B2_INDEX))["c1"] == tr.LEVEL_ASSERTED


def test_named_credit_path_taint_from_an_untaken_branch_reaches_l3():
    """Taint is never retracted, so the subject is credited from the arm that did not run.
    Path-sensitivity is the fix and is not implemented; this pins the cost of not having it."""
    code = (
        "from stats.frequency import word_frequencies\n"
        "def test_y(flag):\n"
        "    if flag:\n"
        "        out = word_frequencies(['a'])\n"
        "    else:\n"
        "        out = None\n"
        "    assert out is None\n"
    )
    assert _levels(tr.assess(code, FREQ_CRITERIA,
                             first_party=B2_INDEX))["c1"] == tr.LEVEL_ASSERTED


def test_named_credit_path_filesystem_dataflow_is_under_counted_not_credited():
    """The corresponding blind spot in the SAFE direction, pinned for the same reason. The
    real B1 shape verifies persistence through the filesystem, with no variable linking the
    write to the read-back, and lands at L2. It is the costliest thing this analysis misses,
    and it is measured here rather than only described."""
    code = (
        "from stats.storage import save_expense, load_expenses\n"
        "def test_expense_persists_after_save():\n"
        "    save_expense(12.50, 'groceries', '2024-01-15')\n"
        "    loaded = load_expenses()\n"
        "    assert any(abs(e - 12.50) < 0.01 for e in loaded)\n"
    )
    criteria = [{"id": "c1", "text": "The program must save expenses so they persist.",
                 "tier": "behavior", "check": ""}]
    row = tr.assess(code, criteria, first_party=B2_INDEX).criteria[0]
    assert row.level == tr.LEVEL_BOUND
    assert row.subjects == ("save_expense",)


# ---------------------------------------------------------------------------
# NEVER MINT (2) — a subject must be a symbol the DELIVERABLE provides
# ---------------------------------------------------------------------------

#: An oracle that proves something true about the standard library. Under the denylist this
#: replaced, `statistics` was simply a module nobody had listed, so `mean` became the
#: criterion's own subject and earned it L3 the deliverable never proved.
STDLIB_ORACLE = (
    "from statistics import mean\n"
    "def test_mean():\n"
    "    assert mean([1, 2]) == 1.5\n"
)

MEAN_CRITERIA = [{"id": "c1", "text": "The report should show the mean value.",
                  "tier": "behavior", "check": ""}]


@pytest.mark.parametrize("code,root", [
    (STDLIB_ORACLE, "statistics"),
    ("from numpy import mean\n"
     "def test_mean():\n"
     "    assert mean([1, 2]) == 1.5\n", "numpy"),
])
def test_a_symbol_the_deliverable_never_wrote_is_not_a_subject(code, root):
    """Stdlib and third-party alike: the deliverable ships `app`, so nothing imported from
    anywhere else can be what a criterion is about. UNDECIDABLE, never covered."""
    result = tr.assess(code, MEAN_CRITERIA, first_party=APP_INDEX)
    assert _levels(result)["c1"] == tr.LEVEL_UNDECIDABLE
    assert result.verified == 0 and not result.verified_class
    assert root not in APP_INDEX


def test_toggle_the_same_symbol_scores_once_the_tree_actually_provides_it():
    """The lock-off half: `mean` is refused because `statistics` is not the deliverable's, NOT
    because the probe cannot reach the code. A deliverable that really does ship a `statistics`
    package would bind — which is why the refusal above is a measurement."""
    delivered = tr.assess(
        "from stats.summary import mean\n"
        "def test_mean():\n"
        "    assert mean([1, 2]) == 1.5\n", MEAN_CRITERIA, first_party=B2_INDEX)
    assert _levels(delivered)["c1"] == tr.LEVEL_ASSERTED


def test_a_tree_shadowing_a_stdlib_name_loses_the_subject_rather_than_winning_it():
    """A deliverable shipping its own `json.py` makes the root contested. The index drops it:
    an ambiguous subject is not evidence, and under-counting is the required direction."""
    shadow = tr.FirstPartyIndex.from_roots({"json", "app"}, source="test fixture")
    assert "app" in shadow and "json" not in shadow


def test_an_unresolved_first_party_surface_denies_a_number(tmp_path):
    """The fail-closed half of resolution. An instrument that cannot tell the deliverable from
    the world has not measured leniently — it has not measured, and must say so."""
    for result in (tr.assess(STDLIB_ORACLE, MEAN_CRITERIA),
                   tr.assess(STDLIB_ORACLE, MEAN_CRITERIA,
                             first_party=tr.FirstPartyIndex.unresolved("no tree"))):
        assert not result.available
        assert "first-party module surface not resolved" in result.reason
        assert not result.verified_class
        assert "unavailable" in result.fingerprint()


def test_resolve_first_party_prefers_the_runs_own_banked_probe(tmp_path):
    """The probe pair was written AT RUN TIME against the tree as delivered, so it outranks a
    sandbox directory that has been rebuilt several batteries since."""
    d = _seed_run(tmp_path / "run-p", probe_modules=("stats.frequency", "stats.pairs"))
    index = tr.resolve_first_party(d)
    assert index.resolved and index.roots == frozenset({"stats"})
    assert "import-probe-targets.json" in index.source


def test_a_module_the_probe_could_not_import_is_not_first_party(tmp_path):
    """`unresolved` means the delivered tree did not provide the module. Counting it anyway
    would attribute to the deliverable a surface the run itself recorded as absent."""
    d = _seed_run(
        tmp_path / "run-q", probe_modules=("stats.frequency",),
        unresolved=[{"raw": "from stats.frequency import word_frequencies",
                     "module": "stats.frequency", "reason": "does not resolve"}])
    assert not tr.resolve_first_party(d).resolved
    assert not tr.assess_run(d).available


def test_resolve_first_party_falls_back_to_the_delivered_tree_then_gives_up(tmp_path):
    """No probe: read the tree the scorecard names. No tree either: unresolved — never an
    empty index passed off as "the deliverable provides nothing"."""
    repo = tmp_path / "sandbox"
    (repo / "stats").mkdir(parents=True)
    (repo / "stats" / "frequency.py").write_text("", encoding="utf-8")
    (repo / "notes.txt").write_text("", encoding="utf-8")

    d = tmp_path / "run-t"
    d.mkdir()
    (d / "scorecard.json").write_text(json.dumps({"repo": str(repo)}), encoding="utf-8")
    index = tr.resolve_first_party(d)
    assert index.resolved and index.roots == frozenset({"stats"})
    assert "delivered tree" in index.source

    gone = tmp_path / "run-u"
    gone.mkdir()
    (gone / "scorecard.json").write_text(
        json.dumps({"repo": str(tmp_path / "vanished")}), encoding="utf-8")
    assert not tr.resolve_first_party(gone).resolved
    assert not tr.resolve_first_party(tmp_path / "run-v").resolved


# ---------------------------------------------------------------------------
# ANTI-TUNING — the bar may not be lowered to make GREEN-VERIFIED reachable
# ---------------------------------------------------------------------------


def test_declared_only_is_never_counted_as_covered():
    """A mapper's say-so (L1) is an assertion, not evidence. This is the exact predicate the
    incumbent #821 rule used, and widening COVERED_LEVELS to include it would restore it."""
    assert tr.LEVEL_DECLARED not in tr.COVERED_LEVELS
    assert tr.COVERED_LEVELS == frozenset({tr.LEVEL_ASSERTED, tr.LEVEL_KILLS})


def test_a_saturating_declaration_cannot_manufacture_coverage():
    """Mapping EVERY criterion to EVERY test — the declaration that scores 6/6 under the
    incumbent rule — must not lift a single criterion into the covered set."""
    every_test = ["test_word_frequencies_counts_each_word", "test_tokenize_runs"]
    saturated = tr.assess(
        B2_ORACLE, B2_CRITERIA, first_party=B2_INDEX,
        declared_map={c["id"]: list(every_test) for c in B2_CRITERIA},
    )
    honest = tr.assess(B2_ORACLE, B2_CRITERIA, first_party=B2_INDEX)
    assert saturated.verified == honest.verified
    assert not saturated.verified_class
    # The declaration may only lift UNDECIDABLE -> L1, and L1 is not covered.
    assert _levels(saturated)["c5"] == tr.LEVEL_DECLARED
    assert saturated.verified == 1


# ---------------------------------------------------------------------------
# L4-KILLS (#1195 item 3) — the rung, and the toggle that must take it away
#
# Every mutation sidecar below is produced by the REAL
# ``shared.fleet.oracle_mutation.run_oracle_mutation_audit`` over a REAL repo, then written
# to disk and read back through the REAL ``assess_run``. A hand-built dict would be a fixture
# production cannot produce, and a rung graded from one would be a rung for a different
# program: the edge-case shapes below are all DERIVED from a genuine emission.
# ---------------------------------------------------------------------------

#: The B2 fixture's three feature modules, each with a mutable site inside a named function.
_B2_FEATURE_FILES = {
    "stats/tokenize.py": "def tokenize(text):\n    return text.split(' ')\n",
    "stats/frequency.py": (
        "def word_frequencies(tokens):\n"
        "    out = {}\n"
        "    for t in tokens:\n"
        "        out[t] = out.get(t, 0) + 1\n"
        "    return out\n"
    ),
    "stats/pairs.py": "def neighbor_pairs(tokens):\n    return len(tokens) - 1\n",
}

def _red(*tests: str) -> str:
    """A RED pytest tail in the shape the pinned runner actually prints — measured from
    ``uv run --no-project --with pytest==9.1.1 python -m pytest -q``, not invented.

    The trailing count line is load-bearing and was learned the hard way while writing these
    tests: without it the audit's own completion detector reads the run as a CRASH rather
    than a failure, counts no mutant, and the assertions below pass or fail for a reason that
    has nothing to do with the rung. A blob production cannot produce tests a different
    program."""
    return "\n".join(
        ["=========== short test summary info ==========="]
        + [f"FAILED tests/test_job_acceptance.py::{t} - assert False" for t in tests]
        + [f"{len(tests)} failed, 1 passed in 0.4s"])


#: The pinned runner's output when the B2 exam's frequency test goes RED.
_RED_FREQUENCY = _red("test_word_frequencies_counts_each_word")


class _StubRunner:
    """The oracle subprocess, stubbed at the SUBPROCESS boundary only: call 1 is the green
    baseline, every later call is a mutant returning *mutant_blob*. Everything above this
    line — site enumeration, symbol attribution, killer parsing, evidence assembly — is the
    real audit doing its real work."""

    def __init__(self, mutant_blob: str, ok: bool = False) -> None:
        self.calls = 0
        self.mutant = (ok, mutant_blob, "")

    def __call__(self, cmd, cwd, timeout_s, env):
        self.calls += 1
        return (True, "3 passed in 0.4s", "") if self.calls == 1 else self.mutant


def _real_mutation_evidence(tmp_path: Path, *, oracle: str = B2_ORACLE,
                            mutant_blob: str = _RED_FREQUENCY, survived: bool = False,
                            files: "dict[str, str] | None" = None) -> dict:
    """A genuine ``oracle-mutation.json`` payload from the real audit over a real tree."""
    from shared.fleet.acceptance import JOB_ORACLE_PATH_PYTHON
    from shared.fleet.oracle_mutation import run_oracle_mutation_audit

    repo = tmp_path / f"repo-{len(list(tmp_path.iterdir()))}"
    for rel, src in (files if files is not None else _B2_FEATURE_FILES).items():
        target = repo / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(src, encoding="utf-8")
    return run_oracle_mutation_audit(
        None, "R", str(repo), JOB_ORACLE_PATH_PYTHON, oracle,
        run=_StubRunner(mutant_blob, ok=survived), pytest_cmd=lambda rel: ["FAKE", rel],
        persist=False)


def _bank_mutation(run_dir: Path, evidence: dict) -> None:
    (run_dir / "oracle-mutation.json").write_text(
        json.dumps(evidence, indent=2), encoding="utf-8")


def test_l4_is_awarded_when_the_criterion_s_own_test_kills_its_own_subject(tmp_path):
    """The rung, end to end: real audit -> banked sidecar -> real assess_run.

    c3's subject is ``word_frequencies`` and its asserting test is
    ``test_word_frequencies_counts_each_word``; the audit records that same test failing on a
    mutant inside that same symbol. That, and only that, is L4."""
    run = _seed_run(tmp_path / "run")
    _bank_mutation(run, _real_mutation_evidence(tmp_path))

    result = tr.assess_run(run)

    assert _levels(result)["c3"] == tr.LEVEL_KILLS
    c3 = next(c for c in result.criteria if c.criterion_id == "c3")
    assert c3.l4 == tr.L4_KILLED
    assert c3.l4_evidence == ("test_word_frequencies_counts_each_word",)
    assert "L4 killed:1" in result.fingerprint()
    assert result.to_block()["l4"]["killed"] == 1


def test_removing_the_attribution_drops_the_grade_and_says_so(tmp_path):
    """The toggle half (principle 12). The SAME oracle and the SAME criteria, with the
    sidecar withheld, must fall back to L3 and disclose that L4 was not measured AT ALL —
    an instrument that goes blind produces a worse stamp, never a clean one."""
    with_attr = _seed_run(tmp_path / "on")
    _bank_mutation(with_attr, _real_mutation_evidence(tmp_path))
    without = _seed_run(tmp_path / "off")  # identical, minus the sidecar

    on, off = tr.assess_run(with_attr), tr.assess_run(without)

    assert _levels(on)["c3"] == tr.LEVEL_KILLS
    assert _levels(off)["c3"] == tr.LEVEL_ASSERTED, "the rung must not survive its evidence"
    assert off.l4_measured == 0 and not off.attribution.available
    assert "L4 not measured" in off.fingerprint()
    assert any("not measured at all for this run" in n for n in off.not_measured())
    # And the thing that must NOT change: L3 and L4 are both covered, so withdrawing the
    # evidence moves the rung without moving the headline.
    assert on.verified == off.verified


def test_a_kill_by_someone_else_s_test_is_not_this_criterion_s_evidence(tmp_path):
    """The mutant died, but not at this criterion's hands. Crediting the criterion would make
    L4 mean "the exam has some teeth somewhere", which is the whole-file figure it replaced."""
    run = _seed_run(tmp_path / "run")
    _bank_mutation(run, _real_mutation_evidence(
        tmp_path, mutant_blob=_red("test_tokenize_runs")))

    c3 = next(c for c in tr.assess_run(run).criteria if c.criterion_id == "c3")

    assert c3.level == tr.LEVEL_ASSERTED
    assert c3.l4 == tr.L4_NOT_ATTRIBUTED
    assert "only by other tests" in c3.reason


def test_a_kill_nobody_claimed_is_not_a_rung(tmp_path):
    """A repo whose pytest config suppresses the failure summary yields RED runs that name
    nobody. "Something failed" is not "this criterion's test failed"."""
    run = _seed_run(tmp_path / "run")
    evidence = _real_mutation_evidence(tmp_path, mutant_blob="1 failed, 2 passed in 0.4s")
    _bank_mutation(run, evidence)

    result = tr.assess_run(run)

    assert evidence["killed"] > 0, "the mutants still died; only the attribution is missing"
    assert _levels(result)["c3"] == tr.LEVEL_ASSERTED
    assert result.attribution.unattributed_kills == evidence["killed"]
    assert result.to_block()["l4"]["killed"] == 0


@pytest.mark.parametrize("row, label", [
    ({"symbol": "word_frequencies", "outcome": "not-run"}, "not-run"),
    ({"symbol": "word_frequencies"}, "outcome key absent"),
    ({"symbol": "word_frequencies", "outcome": "wat"}, "unrecognised outcome"),
])
def test_a_mutant_that_never_RAN_was_not_put_to_the_question(row, label):
    """[kill] ``mutated`` means the subject was PUT TO THE QUESTION. A mutant that never
    executed was not, and admitting it is the #1223 invariant inverted.

    Membership in ``mutated`` with no entry in the outcome-strict ``killed_by``/``survived``
    renders as L4_NOT_ATTRIBUTED — *"the subject WAS mutated and every mutant was caught, but
    only by other tests"*. For a row that never ran, that sentence asserts a cause the
    evidence does not contain: nothing was caught, because nothing ran.

    This is latent today and becomes systematic the moment #1231 emits a third outcome for
    budget-truncated mutants — an interaction neither branch introduces alone, which is why
    the guard lands here rather than there. Found by independent review, 2026-08-07.

    Toggle: delete the ``outcome not in (L4_KILLED, L4_SURVIVED)`` guard in
    ``fold_mutation_attribution`` and all three of these go red.
    """
    code = "def f(): pass"
    digest = hashlib.sha256(code.encode("utf-8", "replace")).hexdigest()
    evidence = {"mutation_audit": "run", "ran": 1, "oracle_sha256": digest, "mutants": [row]}

    attribution = tr.fold_mutation_attribution(evidence, code)

    assert attribution.available is True, "the sidecar itself is readable; only the row is unusable"
    assert attribution.mutated == set(), (
        f"a {label} mutant entered `mutated`, so its criterion will be told every mutant was "
        "caught by other tests — when nothing ran at all")


def test_a_kill_the_run_could_not_attribute_IS_still_a_real_mutation(tmp_path):
    """CONTROL for the lock above — it must not reject everything with an odd outcome.

    A row that says ``killed`` with no named killer DID run and WAS caught; only the credit is
    missing. That is a genuine not-attributed case and must stay in ``mutated``, or the guard
    would suppress the very blindness ``unattributed_kills`` exists to make visible."""
    code = "def f(): pass"
    digest = hashlib.sha256(code.encode("utf-8", "replace")).hexdigest()
    evidence = {"mutation_audit": "run", "ran": 1, "oracle_sha256": digest,
                "mutants": [{"symbol": "word_frequencies", "outcome": "killed", "killed_by": []}]}

    attribution = tr.fold_mutation_attribution(evidence, code)

    assert attribution.mutated == {"word_frequencies"}
    assert attribution.unattributed_kills == 1


def test_a_surviving_mutant_is_reported_and_never_promoted(tmp_path):
    """The exam passed wrong code. That is the opposite of the rung, and it must show up as
    a named locus rather than as silence."""
    run = _seed_run(tmp_path / "run")
    _bank_mutation(run, _real_mutation_evidence(
        tmp_path, mutant_blob="3 passed in 0.4s", survived=True))

    c3 = next(c for c in tr.assess_run(run).criteria if c.criterion_id == "c3")

    assert c3.level == tr.LEVEL_ASSERTED and c3.l4 == tr.L4_SURVIVED
    assert c3.l4_survivors and all("stats/frequency.py" in s for s in c3.l4_survivors)
    assert "SURVIVED the whole exam" in c3.reason


def test_a_blind_spot_survives_the_rung_being_earned(tmp_path):
    """Earning L4 and having a hole are not exclusive. Measured on the operator's real B2 run:
    ``neighbor_pairs`` killed four mutants via its own test and let two boundary/constant
    mutants through. Reporting only the rung would erase the half a reader needs."""
    run = _seed_run(tmp_path / "run")
    evidence = _real_mutation_evidence(tmp_path)
    # One mutant of the criterion's own subject slipped through; the rest still died to it.
    survivor = next(m for m in evidence["mutants"] if m["symbol"] == "word_frequencies")
    survivor.update(outcome="survived", killed_by=[])
    _bank_mutation(run, evidence)

    result = tr.assess_run(run)
    c3 = next(c for c in result.criteria if c.criterion_id == "c3")

    assert c3.level == tr.LEVEL_KILLS, "the surviving sibling does not un-earn the rung"
    assert c3.l4_survivors, "nor does the rung hide the hole"
    assert "still partly unguarded" in c3.reason
    assert result.to_block()["l4"]["blind_spots"] == 1


def test_an_ambiguous_symbol_name_earns_nothing(tmp_path):
    """``helper`` in two mutated files cannot be traced to a criterion whose ``helper`` came
    from one of them, and the banked evidence does not say which. Errors flow toward "can't
    tell" — the module's standing bias, inherited here."""
    run = _seed_run(tmp_path / "run")
    evidence = _real_mutation_evidence(tmp_path)
    for m in evidence["mutants"]:  # the same name now appears in a second mutated file
        m["symbol"] = "word_frequencies"
    evidence["mutants"][0]["file"] = "stats/other.py"
    _bank_mutation(run, evidence)

    result = tr.assess_run(run)

    assert "word_frequencies" in result.attribution.ambiguous
    assert _levels(result)["c3"] == tr.LEVEL_ASSERTED
    assert result.to_block()["l4"]["killed"] == 0


def test_attribution_from_a_different_exam_is_refused(tmp_path):
    """The two stages find their oracle independently. Crediting one exam's kills to another
    exam's tests would look exactly like evidence, so the digest is checked rather than
    trusted."""
    run = _seed_run(tmp_path / "run")
    _bank_mutation(run, _real_mutation_evidence(
        tmp_path, oracle=B2_ORACLE + "\ndef test_extra():\n    assert True\n"))

    result = tr.assess_run(run)

    assert not result.attribution.available
    assert "digest mismatch" in result.attribution.reason
    assert _levels(result)["c3"] == tr.LEVEL_ASSERTED


@pytest.mark.parametrize("mangle,expect", [
    (lambda ev: ev.update(mutation_audit="skipped-no-targets", ran=0), "did not discriminate"),
    (lambda ev: ev.update(oracle_sha256=""), "carries no oracle digest"),
    (lambda ev: ev.update(mutants=[]), "banked no per-mutant attribution"),
])
def test_each_unusable_sidecar_names_its_own_defect(tmp_path, mangle, expect):
    """Four ways attribution can be missing, four distinct reasons. Collapsing them into one
    silence is how a reader stops being able to tell "nobody looked" from "nothing was found"
    — including the case of an audit banked before attribution existed (no digest), which is
    every sidecar on this machine older than #1195."""
    run = _seed_run(tmp_path / "run")
    evidence = _real_mutation_evidence(tmp_path)
    mangle(evidence)
    _bank_mutation(run, evidence)

    result = tr.assess_run(run)

    assert not result.attribution.available
    assert expect in result.attribution.reason
    assert _levels(result)["c3"] == tr.LEVEL_ASSERTED
    assert any(expect in n for n in result.not_measured())


def test_the_not_measured_disclosure_states_the_condition_rather_than_vanishing(tmp_path):
    """L4 became reachable, not universal. The standing entry must keep saying under WHAT
    condition the rung is awarded, on runs that earned it as much as on runs that did not."""
    run = _seed_run(tmp_path / "run")
    _bank_mutation(run, _real_mutation_evidence(tmp_path))

    earned = tr.assess_run(run)

    assert earned.to_block()["l4"]["killed"] == 1
    condition = [n for n in earned.not_measured() if n.startswith("L4-KILLS")]
    assert len(condition) == 1 and "CONDITIONAL" in condition[0]
    # ... and the unmeasured remainder is still counted, on the very run that earned a rung.
    assert earned.l4_unmeasured == earned.denominator - earned.l4_measured > 0


def test_attribution_can_never_manufacture_a_level_below_l3(tmp_path):
    """Mutation answers "does this assertion discriminate", which presupposes an assertion.
    A GAP or an UNDECIDABLE criterion must be untouched by any amount of mutation evidence."""
    run = _seed_run(tmp_path / "run")
    evidence = _real_mutation_evidence(tmp_path)
    # Claim a kill on every symbol, by every test in the exam — the most generous possible
    # attribution. c4 (GAP) and c5 (UNDECIDABLE) must not move.
    for m in evidence["mutants"]:
        m["killed_by"] = ["test_word_frequencies_counts_each_word", "test_tokenize_runs"]
    _bank_mutation(run, evidence)

    levels = _levels(tr.assess_run(run))

    assert levels["c4"] == tr.LEVEL_GAP
    assert levels["c5"] == tr.LEVEL_UNDECIDABLE


# ---------------------------------------------------------------------------
# The honest output when coverage cannot be determined
# ---------------------------------------------------------------------------


def test_undecidable_blocks_verified_even_with_everything_else_perfect():
    """The load-bearing rule: one criterion we cannot judge is enough to deny the clean
    class. An instrument that goes blind must produce a WORSE class, never a clean one."""
    code = (
        "from app.a import word_frequencies\n"
        "def test_freq():\n"
        "    assert word_frequencies(['a']) == {'a': 1}\n"
    )
    ok = tr.assess(code, [{"id": "c1", "text": "The word frequencies must be right.",
                           "tier": "behavior", "check": ""}], first_party=APP_INDEX)
    assert ok.verified_class, "a fully-verified spec must be able to reach the clean class"

    plus_blind = tr.assess(code, [
        {"id": "c1", "text": "The word frequencies must be right.",
         "tier": "behavior", "check": ""},
        {"id": "c2", "text": "It should feel responsive.", "tier": "behavior", "check": ""},
    ], first_party=APP_INDEX)
    assert plus_blind.undecidable == 1
    assert not plus_blind.verified_class


def test_fingerprint_never_emits_a_bare_ratio():
    result = tr.assess(B2_ORACLE, B2_CRITERIA, first_party=B2_INDEX)
    fp = result.fingerprint()
    for token in ("weak:", "gap:", "undecidable:", "L3+"):
        assert token in fp, f"{token!r} missing from {fp!r}"


@pytest.mark.parametrize("code,criteria,expect", [
    ("", B2_CRITERIA, "no oracle code"),
    ("def broken(:\n", B2_CRITERIA, "does not parse"),
])
def test_unusable_input_is_unavailable_never_a_number(code, criteria, expect):
    result = tr.assess(code, criteria, first_party=B2_INDEX)
    assert not result.available and expect in result.reason
    assert not result.verified_class
    assert "unavailable" in result.fingerprint()


# ---------------------------------------------------------------------------
# Reachability — the real classify_green entry point, not a helper
# ---------------------------------------------------------------------------


def _run_dir(tmp_path: Path, run_id: str, block: dict) -> Path:
    d = tmp_path / run_id
    d.mkdir(parents=True, exist_ok=True)
    (d / tr.TRACEABILITY_SIDECAR_NAME).write_text(json.dumps(block), encoding="utf-8")
    return tmp_path


@pytest.mark.parametrize("source,expect_class", [
    # fully verified -> the clean class is genuinely reachable
    (lambda: tr.assess("from app.a import word_frequencies\n"
                       "def test_f():\n"
                       "    assert word_frequencies(['a']) == {'a': 1}\n",
                       [{"id": "c1", "text": "The word frequencies must be right.",
                         "tier": "behavior", "check": ""}], first_party=APP_INDEX),
     ftax.CLASS_GREEN_VERIFIED),
    # one blind criterion -> PARTIAL, never VERIFIED
    (lambda: tr.assess(B2_ORACLE, B2_CRITERIA, first_party=B2_INDEX), ftax.CLASS_GREEN_PARTIAL),
])
def test_classify_green_consumes_the_traceability_sidecar(tmp_path, source, expect_class):
    """Driven through the REAL classifier over a REAL sidecar on disk — the built-but-wired-
    into-nothing check. A module nothing calls is not a control."""
    result = source()
    runs_dir = _run_dir(tmp_path, "run-1", result.to_block())
    sc = Scorecard(job_id="B2", verdict="GREEN", evidence={"oracle_status": "passed"},
                   run_id="run-1", repo="sandbox/b2")
    klass, fingerprint = ftax.classify_scorecard(sc, runs_dir=runs_dir)
    assert klass == expect_class
    assert fingerprint == result.fingerprint()


def test_classify_green_reports_unverified_when_nothing_could_be_verified(tmp_path):
    """Verified NOTHING is UNVERIFIED, not PARTIAL — "partial" claims some of it was proven."""
    blind = tr.assess(B2_ORACLE, [{"id": "c9", "text": "It should feel nice.",
                                   "tier": "behavior", "check": ""}],
                      first_party=B2_INDEX)
    runs_dir = _run_dir(tmp_path, "run-2", blind.to_block())
    sc = Scorecard(job_id="B2", verdict="GREEN", evidence={}, run_id="run-2",
                   repo="sandbox/b2")
    klass, _ = ftax.classify_scorecard(sc, runs_dir=runs_dir)
    assert klass == ftax.CLASS_GREEN_UNVERIFIED


def test_the_deterministic_block_outranks_the_model_declaration(tmp_path):
    """When both sidecars exist the AST evidence wins over the 14B's k/n assertion — the
    declaration is what proved saturable."""
    result = tr.assess(B2_ORACLE, B2_CRITERIA, first_party=B2_INDEX)
    runs_dir = _run_dir(tmp_path, "run-3", result.to_block())
    (runs_dir / "run-3" / "oracle-qa.json").write_text(
        json.dumps({"oracle_coverage": "6/6", "covered": ["c1"], "uncovered": []}),
        encoding="utf-8")
    sc = Scorecard(job_id="B2", verdict="GREEN", evidence={}, run_id="run-3",
                   repo="sandbox/b2")
    klass, fingerprint = ftax.classify_scorecard(sc, runs_dir=runs_dir)
    assert klass == ftax.CLASS_GREEN_PARTIAL
    assert "6/6" not in fingerprint


def test_absent_sidecar_leaves_the_incumbent_path_byte_identical(tmp_path):
    """The wiring is additive: with no traceability block the classifier behaves exactly as
    it did before this module existed."""
    d = tmp_path / "run-4"
    d.mkdir(parents=True)
    (d / "oracle-qa.json").write_text(
        json.dumps({"oracle_coverage": "unknown", "covered": [], "uncovered": []}),
        encoding="utf-8")
    sc = Scorecard(job_id="B2", verdict="GREEN", evidence={}, run_id="run-4",
                   repo="sandbox/b2")
    klass, fingerprint = ftax.classify_scorecard(sc, runs_dir=tmp_path)
    assert klass == ftax.CLASS_GREEN_UNVERIFIED
    assert fingerprint == "oracle_coverage=unknown (no traceability map)"


def test_assess_run_reads_a_real_run_directory_shape(tmp_path):
    """The run-dir entry point reads what a dispatch actually banks: acceptance.json, a
    job-oracle-*.py, and the resolve-probe pair, and writes its sidecar beside them."""
    d = _seed_run(tmp_path / "20260729-230125-bd")

    result = tr.assess_and_persist(d)
    assert result.available and result.denominator == 3
    banked = json.loads((d / tr.TRACEABILITY_SIDECAR_NAME).read_text(encoding="utf-8"))
    assert banked["schema"] == tr.TRACEABILITY_SCHEMA
    assert banked["advisory"] is True
    assert "verdict" not in banked, "an advisory instrument must expose no verdict field"
    # The provenance of first-party status rides along: a reader can see WHAT decided that
    # `stats` belonged to the deliverable rather than to the world.
    assert "import-probe-targets.json" in banked["first_party_source"]


@pytest.mark.parametrize("missing", ["acceptance.json", "job-oracle-test_job_acceptance.py"])
def test_assess_run_is_fail_soft_on_a_missing_input(tmp_path, missing):
    d = _seed_run(tmp_path / "run-5")
    (d / missing).unlink()
    result = tr.assess_run(d)
    assert not result.available and result.reason
    assert not result.verified_class


def test_battery_close_produces_the_sidecar_and_classifies_from_it(tmp_path):
    """The production seam: ``BatterySummary.classify`` must COMPUTE the traceability block
    for each run, bank it, and classify from it. Without this the module would be reachable
    only from the CLI and no night would ever produce one — built and wired into nothing."""
    from tools.dispatch_harness import battery as bat

    runs_dir = tmp_path / "runs"
    run = _seed_run(runs_dir / "20260729-230125-bd")

    sc = Scorecard(job_id="B2", verdict="GREEN", evidence={"oracle_status": "passed"},
                   run_id="20260729-230125-bd", repo="sandbox/b2")
    out = tmp_path / "scorecards"
    out.mkdir()
    summary = bat.BatterySummary(scorecards=[sc], out_dir=str(out))
    summary.classify(runs_dir=runs_dir, out_dir=out, log=lambda *_: None)

    banked = run / tr.TRACEABILITY_SIDECAR_NAME
    assert banked.is_file(), "battery close must bank the traceability sidecar"
    assert sc.evidence["green_class"] == ftax.CLASS_GREEN_PARTIAL
    assert "undecidable:1" in sc.evidence["green_fingerprint"]
    # The advisory invariant still holds through the added stage.
    assert sc.verdict == "GREEN" and sc.attribution == ""


# ---------------------------------------------------------------------------
# The CLI's corpus summary — the structural control for a measured reading failure
# ---------------------------------------------------------------------------
#
# On 2026-07-30 three independent readers each ran the `--all` sweep over 221 run dirs, read
# the last 25-40 lines of 223, and reported the sample as the corpus. The tool printed one
# line per run and nothing else, so nothing on screen distinguished the whole result from its
# tail. These lock the control: the summary exists, it is LAST, and its arithmetic closes.


def _sweep(tmp_path: Path, capsys, *args: str) -> str:
    from tools.dispatch_harness.green_quality import traceability as trmod

    code = trmod.main([str(tmp_path), "--all", *args])
    assert code == 0, f"a balanced sweep must exit 0, got {code}"
    return capsys.readouterr().out


def test_the_corpus_summary_is_the_last_thing_printed(tmp_path, capsys):
    """The control itself. A reader who truncates must lose the per-run detail and KEEP the
    conclusion — the truncation that caused the failure now yields the most useful output
    instead of the most misleading."""
    _seed_run(tmp_path / "run-a")
    _seed_run(tmp_path / "run-b")
    (tmp_path / "run-empty").mkdir()

    out = _sweep(tmp_path, capsys).rstrip().splitlines()
    # The window is the summary block's own height; it grew by one line when the block gained
    # its L4 row (#1195 item 3). Widening it as the block grows keeps the control ("the
    # conclusion survives truncation") intact — the control is that no per-run line reaches
    # this window, which the second assertion below is what actually enforces.
    tail = out[-15:]
    assert any("CORPUS SUMMARY" in line for line in tail)
    assert not any(line.startswith("run-a:") or line.startswith("run-b:") for line in tail), (
        "a per-run line inside the tail window means the summary is not last")
    # The figures every one of the three readers got wrong or recomputed by hand.
    body = "\n".join(out)
    for token in ("criteria", "L3+ verified", "weak (L1/L2)", "gap (L0)", "undecidable",
                  "GREEN-VERIFIED", "not assessable"):
        assert token in body, f"{token!r} missing from the summary"


def test_the_summary_arithmetic_is_self_checking(tmp_path, capsys):
    """`denominator == verified + weak + gap + undecidable` is an invariant of the ladder, and
    it was verified BY HAND during the audit. The summary now shows the equation, so a mismatch
    is visible rather than reconstructable."""
    _seed_run(tmp_path / "run-a")
    out = _sweep(tmp_path, capsys)
    assert "  OK" in out and "DOES NOT BALANCE" not in out

    totals = tr.aggregate([("r", tr.assess_run(tmp_path / "run-a"))])
    assert totals.balances
    assert totals.criteria == totals.verified + totals.weak + totals.gap + totals.undecidable


def test_an_unbalanced_summary_is_loud_and_exits_non_zero(tmp_path, capsys):
    """The toggle half. A summary whose own arithmetic does not close is not a smaller problem
    than a failed sweep — it is a figure that still READS as authoritative. It must say so on
    screen and refuse a clean exit, or the self-check is decoration."""
    from tools.dispatch_harness.green_quality import traceability as trmod

    broken = tr.CorpusAggregate(runs=1, assessable=1, criteria=99, verified=1, weak=0,
                                gap=0, undecidable=0, verified_class=0)
    assert not broken.balances
    assert "** DOES NOT BALANCE **" in "\n".join(broken.render())

    real = trmod.aggregate
    trmod.aggregate = lambda _results: broken
    try:
        _seed_run(tmp_path / "run-a")
        assert trmod.main([str(tmp_path), "--all"]) == 2
    finally:
        trmod.aggregate = real
    assert "DOES NOT BALANCE" in capsys.readouterr().out


def test_the_summary_explains_why_runs_were_not_assessable(tmp_path, capsys):
    """The number that explains why the headline denominator is small. Each of the three
    readers reconstructed this breakdown separately from the per-run lines."""
    _seed_run(tmp_path / "run-a")
    (tmp_path / "run-no-oracle").mkdir()
    (tmp_path / "run-no-oracle" / "acceptance.json").write_text(
        json.dumps({"spec": {"goal": "g", "criteria": B2_CRITERIA}}), encoding="utf-8")
    (tmp_path / "run-nothing").mkdir()

    out = _sweep(tmp_path, capsys)
    assert "no seeded job oracle in the run dir" in out
    assert "no readable acceptance.json" in out

    totals = tr.aggregate([(d.name, tr.assess_run(d))
                           for d in sorted(tmp_path.iterdir()) if d.is_dir()])
    assert totals.assessable == 1 and totals.runs == 3
    assert sum(n for _r, n in totals.unavailable) == 2, "every skipped run must be counted"


def test_reason_buckets_classify_without_swallowing_the_distinction():
    """The aggregate groups by reason CLASS — run-specific tails (a path, a vanished tree, an
    exception name) are cut, and two genuinely different causes stay apart."""
    assert tr._reason_bucket("run dir not found: C:/x/y") == "run dir not found"
    assert tr._reason_bucket("oracle does not parse: SyntaxError") == "oracle does not parse"
    assert (tr._reason_bucket("first-party module surface not resolved (unresolved: gone)")
            != tr._reason_bucket("no seeded job oracle in the run dir"))


def test_the_json_sweep_carries_the_same_aggregate(tmp_path, capsys):
    """A machine reader gets the corpus figures from the same document as the per-run blocks,
    so a script cannot accidentally consume the runs without the totals."""
    from tools.dispatch_harness.green_quality import traceability as trmod

    _seed_run(tmp_path / "run-a")
    assert trmod.main([str(tmp_path), "--all", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert set(payload) == {"runs", "aggregate"}
    assert payload["aggregate"]["balances"] is True
    assert payload["aggregate"]["assessable"] == 1
    # A single run dir still emits its bare block — the shape change is scoped to --all.
    assert trmod.main([str(tmp_path / "run-a"), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["schema"] == tr.TRACEABILITY_SCHEMA


# ---------------------------------------------------------------------------
# The stage's OWN faults — advisory means non-fatal, never unrecorded
# ---------------------------------------------------------------------------


def _summary(tmp_path: Path, *cards: Scorecard):
    from tools.dispatch_harness import battery as bat

    out = tmp_path / "scorecards"
    out.mkdir(exist_ok=True)
    return bat.BatterySummary(scorecards=list(cards), out_dir=str(out)), out


def test_a_crash_in_the_stage_is_named_on_the_durable_artifact(tmp_path, monkeypatch):
    """A crash leaves no sidecar, and a missing sidecar is indistinguishable from a run that
    never seeded an oracle. Battery stdout is not a durable record and is not read; the
    scorecard is. So the fault must be nameable on the card itself."""
    from tools.dispatch_harness import battery as bat
    from tools.dispatch_harness.green_quality import traceability as _trace

    def _boom(_run_dir, **_kw):
        raise RuntimeError("sidecar write exploded")

    monkeypatch.setattr(_trace, "assess_and_persist", _boom)

    runs_dir = tmp_path / "runs"
    _seed_run(runs_dir / "run-crash")
    sc = Scorecard(job_id="B2", verdict="GREEN", evidence={"oracle_status": "passed"},
                   run_id="run-crash", repo="sandbox/b2")
    summary, out = _summary(tmp_path, sc)
    summary.classify(runs_dir=runs_dir, out_dir=out, log=lambda *_: None)

    assert "RuntimeError" in sc.evidence[bat.TRACEABILITY_ERROR_KEY]
    # …and it survives onto the two durable artifacts, not just the in-memory card.
    banked = json.loads((out / "B2.scorecard.json").read_text(encoding="utf-8"))
    assert bat.TRACEABILITY_ERROR_KEY in banked["evidence"]
    assert bat.TRACEABILITY_ERROR_KEY in summary.to_dict()["jobs"][0]["evidence"]


def test_a_crash_and_an_honest_no_input_do_not_render_the_same(tmp_path, monkeypatch):
    """The lock the two renderings never had. A crash reports the pre-feature string
    `no traceability map`; a run with nothing to assess reports `unavailable (<reason>)`.
    Collapsing them would hide a broken instrument inside a normal-looking night."""
    from tools.dispatch_harness import battery as bat
    from tools.dispatch_harness.green_quality import traceability as _trace

    runs_dir = tmp_path / "runs"
    (runs_dir / "run-empty").mkdir(parents=True)      # nothing to assess: honest, not broken
    _seed_run(runs_dir / "run-crash")
    # Both carry the #821 sidecar in its real `unknown` shape, so the ONLY difference between
    # the two nights is whether this stage worked.
    for name in ("run-empty", "run-crash"):
        (runs_dir / name / "oracle-qa.json").write_text(
            json.dumps({"oracle_coverage": "unknown", "covered": [], "uncovered": []}),
            encoding="utf-8")

    honest = Scorecard(job_id="B1", verdict="GREEN", evidence={}, run_id="run-empty",
                       repo="sandbox/b1")
    summary, out = _summary(tmp_path, honest)
    summary.classify(runs_dir=runs_dir, out_dir=out, log=lambda *_: None)
    honest_fp = honest.evidence["green_fingerprint"]

    monkeypatch.setattr(_trace, "assess_and_persist",
                        lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("boom")))
    crashed = Scorecard(job_id="B2", verdict="GREEN", evidence={}, run_id="run-crash",
                        repo="sandbox/b2")
    summary, out = _summary(tmp_path, crashed)
    summary.classify(runs_dir=runs_dir, out_dir=out, log=lambda *_: None)
    crashed_fp = crashed.evidence["green_fingerprint"]

    assert honest_fp != crashed_fp
    assert "unavailable" in honest_fp and "no traceability map" in crashed_fp
    # The fingerprints differ, and only the crash carries the fault key.
    assert bat.TRACEABILITY_ERROR_KEY in crashed.evidence
    assert bat.TRACEABILITY_ERROR_KEY not in honest.evidence


def test_a_multiline_fault_still_leaves_a_writable_scorecard(tmp_path, monkeypatch):
    """The S6 evidence contract forbids newlines and caps length, and `write_scorecard` fails
    closed. An unclipped traceback would convert a recorded fault into an unwritable durable
    artifact — the same defect one layer down."""
    from tools.dispatch_harness import battery as bat
    from tools.dispatch_harness.green_quality import traceability as _trace

    def _boom(_run_dir, **_kw):
        raise ValueError("line one\nline two\n" + "x" * 4000)

    monkeypatch.setattr(_trace, "assess_and_persist", _boom)
    runs_dir = tmp_path / "runs"
    _seed_run(runs_dir / "run-messy")
    sc = Scorecard(job_id="B2", verdict="GREEN", evidence={}, run_id="run-messy",
                   repo="sandbox/b2")
    summary, out = _summary(tmp_path, sc)
    summary.classify(runs_dir=runs_dir, out_dir=out, log=lambda *_: None)

    detail = sc.evidence[bat.TRACEABILITY_ERROR_KEY]
    assert "\n" not in detail and len(detail) <= 300
    assert not scorecard_mod.validate(sc), "the stamped card must remain writable"
    assert (out / "B2.scorecard.json").is_file()


def test_an_unimportable_stage_is_loud_on_every_card_and_still_writes_the_summary(
        tmp_path, monkeypatch):
    """The night's results must survive a syntax error in an advisory module. Fail-soft here
    is not fail-silent: the import fault is stamped on EVERY card, which is louder than the
    stdout line it replaces — and unlike the crash it replaces, the summary still exists to
    carry it."""
    import sys

    from tools.dispatch_harness import battery as bat
    from tools.dispatch_harness import green_quality as gq

    runs_dir = tmp_path / "runs"
    _seed_run(runs_dir / "run-1")
    cards = [Scorecard(job_id="B2", verdict="GREEN", evidence={}, run_id="run-1",
                       repo="sandbox/b2"),
             Scorecard(job_id="B4", verdict="PARKED-HONEST", attribution="BUILD",
                       evidence={}, run_id="", repo="sandbox/b4")]
    summary, out = _summary(tmp_path, *cards)

    # The real shape of the fault: the submodule cannot be produced at all, exactly as a
    # syntax error in traceability.py would leave it.
    monkeypatch.delattr(gq, "traceability", raising=False)
    monkeypatch.setitem(sys.modules, "tools.dispatch_harness.green_quality.traceability", None)
    block = summary.classify(runs_dir=runs_dir, out_dir=out, log=lambda *_: None)

    assert block, "an unimportable advisory stage must not cost the taxonomy block"
    for sc in cards:
        assert "unavailable" in sc.evidence[bat.TRACEABILITY_ERROR_KEY]
    # Every card stays writable, so battery close reaches its summary write.
    assert (out / "B2.scorecard.json").is_file() and (out / "B4.scorecard.json").is_file()


def test_toggle_a_healthy_stage_stamps_no_fault_and_banks_the_sidecar(tmp_path):
    """The lock-off half: with nothing broken the key is absent and the sidecar exists, so
    the assertions above measure a real fault rather than a key that is always present."""
    from tools.dispatch_harness import battery as bat

    runs_dir = tmp_path / "runs"
    run = _seed_run(runs_dir / "run-ok")
    sc = Scorecard(job_id="B2", verdict="GREEN", evidence={}, run_id="run-ok",
                   repo="sandbox/b2")
    summary, out = _summary(tmp_path, sc)
    summary.classify(runs_dir=runs_dir, out_dir=out, log=lambda *_: None)

    assert bat.TRACEABILITY_ERROR_KEY not in sc.evidence
    assert (run / tr.TRACEABILITY_SIDECAR_NAME).is_file()


def test_battery_close_is_fail_soft_when_a_run_dir_has_nothing_to_assess(tmp_path):
    """A run that seeded no oracle must not sink battery close, and must leave the incumbent
    classification path untouched."""
    from tools.dispatch_harness import battery as bat

    runs_dir = tmp_path / "runs"
    (runs_dir / "empty-run").mkdir(parents=True)
    sc = Scorecard(job_id="B2", verdict="GREEN", evidence={}, run_id="empty-run",
                   repo="sandbox/b2")
    out = tmp_path / "scorecards"
    out.mkdir()
    summary = bat.BatterySummary(scorecards=[sc], out_dir=str(out))
    block = summary.classify(runs_dir=runs_dir, out_dir=out, log=lambda *_: None)

    assert block, "battery close must still produce a taxonomy block"
    assert sc.evidence["green_class"] == ftax.CLASS_GREEN_UNVERIFIED


# ---------------------------------------------------------------------------
# Ecosystems — the honest floor first, then the node ladder (#1348)
# ---------------------------------------------------------------------------
#
# Two defects, and the second was the worse one. The discovery glob read
# ``job-oracle-*.py``, so a node oracle was invisible; the instrument then recorded
# "no seeded job oracle in the run dir" — a FALSE sentence, banked beside the file it
# denied, that sends anyone chasing low coverage to hunt a seeding step that works fine.
#
# These suites lock both halves against the REAL artifacts of run 20260808-160538-bd (the
# pottery-studio website B9 built and the fleet stamped GREEN). Real, not mocked: a fixture
# proves the code runs, and only the banked artifact proves it runs on what actually shipped.

#: The banked B9 node run. Absent on a machine that never ran the battery — those tests SKIP
#: rather than fail, but every one of them asserts hard when the evidence IS present.
B9_RUN = Path.home() / "agentic-setup" / "state" / "fleet-runs" / "20260808-160538-bd"
B9_ORACLE = B9_RUN / "job-oracle-acceptance.job.test.mjs"

needs_b9 = pytest.mark.skipif(
    not B9_ORACLE.is_file(),
    reason=f"the real B9 node run is not on this machine ({B9_RUN})")

#: The node first-party surface exactly as that run's own resolve-probe banked it.
B9_SPECS = ("../src/contact/enquiries.js", "../src/pieces/data.js")

#: A criterion whose wording DOES contain the tokens of a symbol the real B9 oracle imports.
#: The B9 criteria contain none, which is why that run measures 0/6 — so this is the fixture
#: that proves the difference is the wording and not a path that cannot score.
B9_BINDING_CRITERION = [{
    "id": "x1", "text": "The get pieces list should come from the saved data.",
    "tier": "behavior", "check": "Read the pieces and check one of them.",
}]


def _node_index(*specs: str) -> tr.FirstPartyIndex:
    """A resolved node first-party surface, standing in for what a probe established."""
    return tr.FirstPartyIndex.from_specifiers(set(specs), source="test fixture")


def _seed_node_run(d: Path, *, oracle: str, criteria: "list[dict]",
                   specs: "tuple[str, ...]" = ("../src/app.js",),
                   unresolved: "list[dict] | None" = None,
                   suffix: str = ".mjs") -> Path:
    """A node run directory in the shape a dispatch actually banks — the spec, the seeded
    ``.mjs`` oracle, and the #822 resolve-probe pair carrying ``kind: node`` rows."""
    d.mkdir(parents=True, exist_ok=True)
    (d / "acceptance.json").write_text(
        json.dumps({"spec": {"goal": "g", "criteria": criteria}}), encoding="utf-8")
    (d / f"job-oracle-acceptance.job.test{suffix}").write_text(oracle, encoding="utf-8")
    (d / "import-probe-targets.json").write_text(
        json.dumps([{"kind": "node", "module": "", "spec": s, "level": 0, "names": [],
                     "raw": f"import '{s}'"} for s in specs]), encoding="utf-8")
    (d / "import-probe-verdict.json").write_text(
        json.dumps({"ok": not unresolved, "unresolved": unresolved or []}), encoding="utf-8")
    return d


#: A small node oracle in the shape the fleet seeds: one test that asserts through a local
#: read back from the subject (the commonest SOUND shape), one that only calls.
NODE_ORACLE = """
import test from 'node:test'; import assert from 'node:assert';
import { addExpense, loadExpenses } from '../src/app.js';

test('records an expense', async () => {
  const store = await addExpense(12.5, 'lunch');
  assert.equal(store.total, 12.5);
});

test('loads without asserting', async () => {
  await loadExpenses();
});
"""

NODE_CRITERIA = [
    {"id": "c1", "text": "Adding an expense should keep a running total.",
     "tier": "behavior", "check": "Add an expense and check the total."},
    {"id": "c2", "text": "The saved expenses should load again on restart.",
     "tier": "behavior", "check": "Load the expenses and confirm they are present."},
    {"id": "c3", "text": "The layout should look tidy.", "tier": "visual", "check": ""},
]


def _node_test(body: str, *, imports: str = "addExpense") -> str:
    """One node test around ``body``, importing ``imports`` from the deliverable."""
    return (
        "import test from 'node:test'; import assert from 'node:assert';\n"
        f"import {{ {imports} }} from '../src/app.js';\n"
        "test('t', async () => {\n"
        f"{body}\n"
        "});\n"
    )


# --- The floor: three states, three sentences, none of them a false absence -------------


def test_a_run_that_really_seeded_nothing_still_says_so(tmp_path):
    """The one case where "no seeded job oracle" is TRUE keeps saying exactly that. The fix
    must not trade a false absence for a missing one."""
    d = tmp_path / "run-empty"
    d.mkdir()
    (d / "acceptance.json").write_text(
        json.dumps({"spec": {"goal": "g", "criteria": NODE_CRITERIA}}), encoding="utf-8")

    result = tr.assess_run(d)
    assert not result.available
    assert result.reason == "no seeded job oracle in the run dir"
    assert tr.discover_oracle(d) == (None, tr.ECOSYSTEM_UNKNOWN)


@pytest.mark.parametrize("suffix", [".rb", ".ts"])
def test_an_oracle_this_assessor_cannot_read_reports_the_limit_not_an_absence(
        tmp_path, suffix):
    """An ecosystem with no reader names ITSELF, the FILE, and the limit. It must never
    borrow the absence sentence — the oracle is right there."""
    d = _seed_node_run(tmp_path / f"run-alien{suffix}", oracle=NODE_ORACLE,
                       criteria=NODE_CRITERIA, suffix=suffix)

    result = tr.assess_run(d)
    assert not result.available
    assert "no seeded job oracle" not in result.reason
    assert result.reason.startswith("unsupported oracle ecosystem")
    assert "no ecosystem this assessor recognises" in result.reason
    assert f"job-oracle-acceptance.job.test{suffix}" in result.reason
    # The limit rides in the same sentence as the finding, so it cannot be quoted alone.
    assert "this assessor reads" in result.reason


def test_an_oracle_that_cannot_be_tokenised_is_its_own_third_state(tmp_path):
    """Unparseable is neither absent nor unsupported. A reader chasing a missing number
    needs to know which of the three they are looking at."""
    d = _seed_node_run(tmp_path / "run-broken", criteria=NODE_CRITERIA,
                       oracle="import { a } from '../src/app.js';\nconst s = \"never closed\n")

    result = tr.assess_run(d)
    assert not result.available
    assert "does not parse" in result.reason
    assert "no seeded job oracle" not in result.reason
    assert "unsupported oracle ecosystem" not in result.reason


def test_the_three_unreadable_states_are_three_distinct_reason_buckets(tmp_path):
    """The corpus sweep counts reasons by BUCKET (:func:`_reason_bucket`), so three
    different facts that collapsed into one bucket would be three facts a reader could
    never separate again."""
    absent = tmp_path / "a"
    absent.mkdir()
    (absent / "acceptance.json").write_text(
        json.dumps({"spec": {"goal": "g", "criteria": NODE_CRITERIA}}), encoding="utf-8")
    alien = _seed_node_run(tmp_path / "b", oracle=NODE_ORACLE, criteria=NODE_CRITERIA,
                           suffix=".rb")
    broken = _seed_node_run(tmp_path / "c", criteria=NODE_CRITERIA,
                            oracle="const s = 'never closed\n")

    buckets = {tr._reason_bucket(tr.assess_run(d).reason) for d in (absent, alien, broken)}
    assert len(buckets) == 3, f"states collapsed into one bucket: {sorted(buckets)}"


# --- The node ladder, driven over the REAL banked artifacts -----------------------------


@needs_b9
def test_the_real_b9_website_run_is_assessed_instead_of_reported_absent():
    """The measured case. Before #1348 this run banked
    ``oracle_coverage=unavailable (no seeded job oracle in the run dir)`` while
    ``job-oracle-acceptance.job.test.mjs`` sat beside the sidecar that said so."""
    result = tr.assess_run(B9_RUN)

    assert result.available, result.reason
    assert result.reason == ""
    # 8 criteria, 2 of them `visual` -> excluded from the denominator by construction.
    assert result.denominator == 6
    assert result.oracle_test_count == 5
    assert result.symbol_count == 3
    # The honest reading of an exam the fleet stamped GREEN: nothing verified, one weak
    # binding, five criteria this instrument cannot judge either way.
    assert (result.verified, result.weak, result.gap, result.undecidable) == (0, 1, 0, 5)
    assert not result.verified_class, "undecidable > 0 must keep GREEN-VERIFIED unreachable"
    assert "0/6 L3+" in result.fingerprint()
    # First-party status came from the run's OWN banked probe, not from a guess.
    assert "import-probe-targets.json" in result.first_party_source


@needs_b9
def test_the_real_b9_oracle_binds_the_one_criterion_it_touches_and_calls_it_weak():
    """c5 ("store submitted enquiries") is the single criterion whose wording names a symbol
    the exam imports — and the exam calls that symbol and asserts NOTHING about it."""
    rows = {c.criterion_id: c for c in tr.assess_run(B9_RUN).criteria}

    c5 = rows["c5"]
    assert c5.level == tr.LEVEL_BOUND
    assert c5.subjects == ("storeEnquiry",)
    assert not c5.covered
    assert "asserts nothing" in c5.reason


@needs_b9
def test_the_real_b9_oracle_traces_an_assertion_through_two_locals():
    """The positive control for the taint scan. Without it the 0/6 above would be
    indistinguishable from a matcher that never fires: this asserts the matcher DOES reach a
    subject across ``const pieces = await getPieces()`` -> ``pieces.filter(...)`` ->
    ``assert.ok(filtered.length > 0)``, two hops with no mention of the subject."""
    code = B9_ORACLE.read_text(encoding="utf-8")
    symbols = tr.node_symbols(code, _node_index(*B9_SPECS))
    assert symbols == frozenset({"storeEnquiry", "getPieces", "getPieceById"})

    traced = {t.name: t for t in tr.node_oracle_tests(code, tr.node_mask(code), symbols)}
    assert traced["Verify filtering by category works"].asserts_on == frozenset({"getPieces"})

    stores = traced["Verify contact form stores enquiry"]
    assert stores.exercises == frozenset({"storeEnquiry"})
    assert stores.asserts_on == frozenset(), "a call with no assertion is never L3 evidence"
    assert not stores.has_assertion

    empty = traced["Verify all pages are accessible"]
    assert (empty.exercises, empty.asserts_on) == (frozenset(), frozenset())


@needs_b9
def test_a_criterion_worded_to_name_the_real_oracles_subject_reaches_l3():
    """The whole-path positive control: the REAL oracle, a criterion whose wording contains
    the subject's tokens, and the ladder reaches L3-ASSERTED. Proves the 0/6 measured above
    is a fact about that run's criteria wording, not a path that cannot score."""
    result = tr.assess(B9_ORACLE.read_text(encoding="utf-8"), B9_BINDING_CRITERION,
                       ecosystem=tr.ECOSYSTEM_NODE, first_party=_node_index(*B9_SPECS))

    assert result.available, result.reason
    row = result.criteria[0]
    assert row.level == tr.LEVEL_ASSERTED, row.reason
    assert row.subjects == ("getPieces",)
    assert row.covered


# --- Toggles: prove each probe FAILS once its evidence is removed (principle 12) ---------


@needs_b9
def test_toggle_removing_the_node_reader_makes_the_real_run_unassessable(monkeypatch):
    """Disengage the node reader entirely. If the suite above stayed green without it, these
    tests were never reaching the node path at all and prove nothing."""
    monkeypatch.delitem(tr.ORACLE_READERS, tr.ECOSYSTEM_NODE)

    result = tr.assess_run(B9_RUN)
    assert not result.available
    assert result.reason.startswith("unsupported oracle ecosystem")
    assert "JavaScript (node)" in result.reason
    # Even disengaged it refuses HONESTLY: the oracle is still named, never denied.
    assert "job-oracle-acceptance.job.test.mjs" in result.reason


@needs_b9
def test_toggle_disengaging_the_assertion_predicate_drops_the_l3_case_to_l2(monkeypatch):
    """Blind the assert-site rule. The criterion that reached L3 above must fall to L2 — the
    level whose evidence is exactly what was removed."""
    monkeypatch.setattr(tr, "_JS_ASSERT_SITE_RE", re.compile(r"(?!x)x"))

    result = tr.assess(B9_ORACLE.read_text(encoding="utf-8"), B9_BINDING_CRITERION,
                       ecosystem=tr.ECOSYSTEM_NODE, first_party=_node_index(*B9_SPECS))
    assert result.criteria[0].level == tr.LEVEL_BOUND
    assert not result.criteria[0].covered


def test_toggle_cutting_the_node_taint_chain_drops_the_indirect_case_to_l2(monkeypatch):
    """The taint map is what makes an assertion through a local count. Cut it and the same
    oracle scores L2 — the honest reading of ``assert.equal(store.total, …)`` when nothing
    links ``store`` back to ``addExpense``."""
    real = tr._js_expr_subjects
    monkeypatch.setattr(tr, "_js_expr_subjects",
                        lambda text, symbols, taint: real(text, symbols, {}))

    result = tr.assess(NODE_ORACLE, NODE_CRITERIA, ecosystem=tr.ECOSYSTEM_NODE,
                       first_party=_node_index("../src/app.js"))
    assert _levels(result)["c1"] == tr.LEVEL_BOUND


# --- Precision: coverage is never minted ------------------------------------------------


def test_the_node_ladder_scores_the_shapes_it_should():
    """The baseline the precision locks below are measured against: the sound shape reaches
    L3, the call-only shape stops at L2."""
    result = tr.assess(NODE_ORACLE, NODE_CRITERIA, ecosystem=tr.ECOSYSTEM_NODE,
                       first_party=_node_index("../src/app.js"))

    assert result.available, result.reason
    assert result.denominator == 2, "the visual criterion is excluded by construction"
    assert _levels(result) == {"c1": tr.LEVEL_ASSERTED, "c2": tr.LEVEL_BOUND}


@pytest.mark.parametrize("body,label", [
    ("  assert.ok(true);", "a tautology asserts nothing about any subject"),
    ("  const other = 1;\n  assert.equal(other, 1);", "an assertion about an unrelated local"),
    ("  const n = 2;", "no assertion at all"),
    ("  assert.equal(2 + 2, 4);", "an assertion about nothing in the deliverable"),
])
def test_an_oracle_that_does_not_cover_a_criterion_is_never_scored_as_covering_it(body, label):
    """The failure mode that matters here: false coverage would manufacture confidence in an
    exam that tests nothing. Each shape below CALLS the subject (so the criterion binds) and
    must still stop at L2."""
    result = tr.assess(_node_test("  await addExpense(1, 'x');\n" + body),
                       [NODE_CRITERIA[0]], ecosystem=tr.ECOSYSTEM_NODE,
                       first_party=_node_index("../src/app.js"))

    row = result.criteria[0]
    assert not row.covered, f"{label}: scored {row.level} — {row.reason}"
    assert row.level == tr.LEVEL_BOUND


def test_an_assertion_message_is_narration_never_evidence():
    """``assert.ok(flag, `after ${addExpense} ran`)`` names the subject only in the MESSAGE.
    The python path drops the message outright; the node path blanks the interpolation."""
    result = tr.assess(
        _node_test("  await loadExpenses();\n"
                   "  const flag = true;\n"
                   "  assert.ok(flag, `after ${addExpense} ran`);",
                   imports="addExpense, loadExpenses"),
        [NODE_CRITERIA[0]], ecosystem=tr.ECOSYSTEM_NODE,
        first_party=_node_index("../src/app.js"))

    assert not result.criteria[0].covered
    assert result.criteria[0].level == tr.LEVEL_BOUND


def test_element_wise_destructuring_does_not_credit_the_wrong_element():
    """``const [total, label] = [addExpense(1), 'lunch']`` binds element-wise, so an
    assertion about ``label`` must not be credited to ``addExpense``. A broadcast rule —
    the simpler implementation — would mint exactly that."""
    result = tr.assess(
        _node_test("  const [total, label] = [addExpense(1), 'lunch'];\n"
                   "  assert.equal(label, 'lunch');"),
        [NODE_CRITERIA[0]], ecosystem=tr.ECOSYSTEM_NODE,
        first_party=_node_index("../src/app.js"))

    assert not result.criteria[0].covered, "the untouched element credited the subject"


def test_a_property_read_names_its_object_not_its_member():
    """``store.addExpense`` must not be read as the imported ``addExpense`` — the node
    analogue of taking the ROOT of an attribute chain."""
    both = frozenset({"addExpense", "store"})
    assert tr._js_expr_subjects("store.addExpense", both, {}) == frozenset({"store"})
    assert tr._js_expr_subjects("...addExpense", both, {}) == frozenset({"addExpense"}), \
        "a spread is a read, not a property access"


# --- First-party status is RESOLVED for node too, never assumed -------------------------


def test_a_node_specifier_the_probe_could_not_resolve_supplies_no_subject(tmp_path):
    """``./`` is not evidence. A specifier the run's own probe failed to import names a
    module the deliverable did not provide, so its bindings are not subjects."""
    d = _seed_node_run(tmp_path / "run-unresolved", oracle=NODE_ORACLE,
                       criteria=NODE_CRITERIA,
                       unresolved=[{"raw": "import '../src/app.js'",
                                    "spec": "../src/app.js",
                                    "reason": "specifier does not resolve"}])

    result = tr.assess_run(d)
    assert not result.available
    assert "first-party module surface not resolved" in result.reason


def test_a_missing_export_does_not_disqualify_the_module(tmp_path):
    """An unresolved row carrying a ``name`` means the module resolved and one export was
    absent — the same convention the python path follows, so the module stays first-party."""
    d = _seed_node_run(tmp_path / "run-partial", oracle=NODE_ORACLE, criteria=NODE_CRITERIA,
                       unresolved=[{"raw": "import '../src/app.js'", "spec": "../src/app.js",
                                    "name": "loadExpenses", "reason": "export absent"}])

    result = tr.assess_run(d)
    assert result.available, result.reason
    assert result.symbol_count == 2


def test_node_first_party_falls_back_to_the_delivered_tree_then_gives_up(tmp_path):
    """No usable probe -> resolve the oracle's specifiers against the tree the scorecard
    names, POSITIVELY (a file must answer to the specifier). No tree, or a tree that answers
    to none of them -> unresolved, which denies a number."""
    repo = tmp_path / "site"
    (repo / "src").mkdir(parents=True)
    (repo / "src" / "app.js").write_text("export const addExpense = () => {};",
                                         encoding="utf-8")

    assert not tr.resolve_first_party(tmp_path / "nowhere", ecosystem=tr.ECOSYSTEM_NODE,
                                      oracle_code=NODE_ORACLE).resolved

    d = tmp_path / "run-tree"
    d.mkdir()
    (d / "scorecard.json").write_text(json.dumps({"repo": str(repo)}), encoding="utf-8")
    index = tr.resolve_first_party(d, ecosystem=tr.ECOSYSTEM_NODE, oracle_code=NODE_ORACLE)
    assert index.resolved and "../src/app.js" in index
    assert "delivered tree" in index.source

    (repo / "src" / "app.js").unlink()
    index = tr.resolve_first_party(d, ecosystem=tr.ECOSYSTEM_NODE, oracle_code=NODE_ORACLE)
    assert not index.resolved
    assert "holds none of the modules the oracle imports" in index.source


def test_the_python_stdlib_denylist_is_not_applied_to_node_specifiers():
    """A JavaScript specifier tested for membership in the python stdlib inventory is a
    category error that could only ever delete a real subject by coincidence."""
    index = tr.FirstPartyIndex.from_specifiers({"../json.js", "./os.js"}, source="fixture")
    assert index.resolved
    assert "../json.js" in index and "./os.js" in index


# --- The python path is untouched by the seam -------------------------------------------


def test_discovery_still_prefers_a_python_oracle_and_reads_it_unchanged(tmp_path):
    """The widened glob must not shift a corpus already assessed: a run banking both oracles
    still grades the python one, exactly as before."""
    d = _seed_run(tmp_path / "run-both")
    (d / "job-oracle-acceptance.job.test.mjs").write_text(NODE_ORACLE, encoding="utf-8")

    path, ecosystem = tr.discover_oracle(d)
    assert ecosystem == tr.ECOSYSTEM_PYTHON
    assert path.name == "job-oracle-test_job_acceptance.py"
    assert tr.assess_run(d).denominator == 3


def test_assess_defaults_to_python_so_every_incumbent_caller_is_unchanged():
    """``ecosystem`` is keyword-only with a python default: the callers that never heard of
    ecosystems keep grading exactly what they graded before, block-for-block."""
    default = tr.assess(B2_ORACLE, B2_CRITERIA, first_party=B2_INDEX)
    explicit = tr.assess(B2_ORACLE, B2_CRITERIA, ecosystem=tr.ECOSYSTEM_PYTHON,
                         first_party=B2_INDEX)

    assert default.to_block() == explicit.to_block()
    assert _levels(default) == {"c3": tr.LEVEL_ASSERTED, "c4": tr.LEVEL_GAP,
                                "c5": tr.LEVEL_UNDECIDABLE}


# --- Reachability: the node path must reach the PRODUCTION seam ------------------------


def test_battery_close_banks_a_node_runs_sidecar_and_classifies_from_it(tmp_path):
    """The production seam for the half this fixes. `BatterySummary.classify` is the only
    caller that ever produces a sidecar on a real night, and until now every node run
    reaching it banked `available=false` with a false reason. A node reader that worked only
    from `assess_run` in a test would be the built-and-wired-into-nothing shape this project
    keeps meeting."""
    from tools.dispatch_harness import battery as bat

    runs_dir = tmp_path / "runs"
    run = _seed_node_run(runs_dir / "20260808-160538-bd", oracle=NODE_ORACLE,
                         criteria=NODE_CRITERIA)

    sc = Scorecard(job_id="B9", verdict="GREEN", evidence={"oracle_status": "passed"},
                   run_id="20260808-160538-bd", repo="sandbox/b9")
    out = tmp_path / "scorecards"
    out.mkdir()
    bat.BatterySummary(scorecards=[sc], out_dir=str(out)).classify(
        runs_dir=runs_dir, out_dir=out, log=lambda *_: None)

    banked = json.loads((run / tr.TRACEABILITY_SIDECAR_NAME).read_text(encoding="utf-8"))
    assert banked["available"] is True, banked["reason"]
    assert banked["reason"] == ""
    assert banked["verified"] == 1 and banked["weak"] == 1
    # …and the classification the night records comes from it.
    assert sc.evidence["green_class"] == ftax.CLASS_GREEN_PARTIAL
    assert "1/2 L3+" in sc.evidence["green_fingerprint"]
    # The advisory invariant survives the added ecosystem: no verdict moved.
    assert sc.verdict == "GREEN" and sc.attribution == ""
    assert "verdict" not in banked


def test_battery_close_banks_the_honest_reason_when_it_cannot_read_the_ecosystem(tmp_path):
    """The floor, at the seam. An unreadable ecosystem must reach the durable artifact as
    ITSELF — the sidecar a later reader actually opens is where the false absence lived."""
    from tools.dispatch_harness import battery as bat

    runs_dir = tmp_path / "runs"
    run = _seed_node_run(runs_dir / "run-alien", oracle=NODE_ORACLE,
                         criteria=NODE_CRITERIA, suffix=".rb")

    sc = Scorecard(job_id="B9", verdict="GREEN", evidence={"oracle_status": "passed"},
                   run_id="run-alien", repo="sandbox/b9")
    out = tmp_path / "scorecards"
    out.mkdir()
    bat.BatterySummary(scorecards=[sc], out_dir=str(out)).classify(
        runs_dir=runs_dir, out_dir=out, log=lambda *_: None)

    banked = json.loads((run / tr.TRACEABILITY_SIDECAR_NAME).read_text(encoding="utf-8"))
    assert banked["available"] is False
    assert "no seeded job oracle" not in banked["reason"]
    assert banked["reason"].startswith("unsupported oracle ecosystem")
    assert sc.evidence["green_class"] == ftax.CLASS_GREEN_UNVERIFIED
