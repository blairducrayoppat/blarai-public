"""#1170 — coder-test-integrity locks.

The regression lock for the 2026-07-29 ``ceremony-check`` merge: a green gate certified a
conversion that was wrong by 2.5x, because the coder authored the tests that were the
gate. Every fingerprint here is pinned in BOTH directions — the defect shape must FIRE,
and the honest shape that most resembles it must STAY SILENT.

The negative half is the load-bearing half. A test-integrity gate that cries wolf gets
switched off, and a switched-off gate protects nothing, so each fixture below pairs the
defect with the nearest legitimate construct: the dead property test against the SAME
nested idiom with its trailing call intact (which is what battery-b1 and battery-b6
actually ship); the accommodated assertion against an honest tolerance whose comment
names the very bound it asserts.

Fixtures are transcribed from the real delivered files, not invented, so a future edit
that stops catching the original defect fails here.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from shared.fleet import coder_test_qa as ctq

_REPO_ROOT = Path(__file__).resolve().parents[2]

# ---------------------------------------------------------------------------
# Fixtures — the defect shapes, and their honest near-twins
# ---------------------------------------------------------------------------

#: The 07-29 defect verbatim in shape: the property is defined, decorated, and dropped.
DEAD_PROPERTY = '''
from hypothesis import given, strategies as st
from app.converter import convert

def test_property_based_conversions():
    """Property-based test for conversion invariants"""
    @given(st.floats(min_value=0.001, max_value=1000),
           st.sampled_from(['teaspoon', 'cup']),
           st.sampled_from(['teaspoon', 'cup']))
    def test_conversion_consistency(value, from_unit, to_unit):
        result = convert(value, from_unit, to_unit)
        assert result >= 0
'''

#: battery-b1/b6's real idiom: same nesting, trailing call present. MUST NOT fire.
LIVE_PROPERTY = '''
from hypothesis import given, strategies as st
from app.inventory import add_item

def test_property_based_persistence():
    """Property-based test for the persistence invariant."""
    @given(st.text(min_size=1), st.integers(min_value=0, max_value=1000))
    def test_item_consistency(name, quantity):
        inventory = {}
        add_item(inventory, name, quantity)
        assert name in inventory

    test_item_consistency()
'''

#: A plain module-level property test — the textbook shape. MUST NOT fire.
MODULE_LEVEL_PROPERTY = '''
from hypothesis import given, strategies as st
from app.converter import convert

@given(st.floats(min_value=0.001, max_value=1000))
def test_round_trip(value):
    assert convert(convert(value, 'cup', 'teaspoon'), 'teaspoon', 'cup') == pytest.approx(value)
'''

#: battery-b4's two, in shape: call it, survive, declare victory.
VACUOUS = '''
from app.data_storage import save_cards

def test_requirement_4_default_path_cards_json():
    """Test that default path is cards.json in working directory."""
    # Just verify the function can be called without error
    save_cards([{"question": "test", "answer": "test"}], None)
    # If we got here without error, the default path handling works
'''

#: A smoke test that legitimately carries its verdict via pytest.raises. MUST NOT fire.
RAISES_SMOKE = '''
import pytest
from app.converter import convert

def test_invalid_unit_rejected():
    with pytest.raises(ValueError):
        convert(1, 'nonsense', 'cup')
'''

#: unittest-style assertions carry a verdict too. MUST NOT fire.
UNITTEST_STYLE = '''
import unittest
from app.converter import convert

class TestConvert(unittest.TestCase):
    def test_cup_to_tablespoon(self):
        self.assertEqual(convert(1, 'cup', 'tablespoon'), 16.0)
'''

#: The 07-29 assertion verbatim: the right answer is in the comment, not the assert.
ACCOMMODATED = '''
from app.converter import convert

def test_basic_conversions():
    # Test gram to ounce (approximate)
    # The exact conversion should be ~0.0353 oz per gram, but we'll accept a reasonable range
    result = convert(1, 'gram', 'ounce')
    assert 0.01 <= result <= 0.1
'''

#: An honest tolerance: the comment names the bound the assertion actually uses.
HONEST_TOLERANCE = '''
from app.converter import convert

def test_cup_to_millilitres():
    # 240 ml per cup, exact to within 0.5 ml of rounding
    result = convert(1, 'cup', 'millilitre')
    assert abs(result - 240.0) < 0.5
'''

#: A band whose endpoints ARE the named expectation. MUST NOT fire.
HONEST_BAND = '''
from app.stats import mean_latency

def test_latency_window():
    # the measured mean should be between 0.25 and 0.75 seconds on this box
    assert 0.25 <= mean_latency() <= 0.75
'''

#: hypothesis imported, nothing that can run it.
DECORATIVE = '''
from hypothesis import given, strategies as st
from app.converter import convert

def test_basic():
    assert convert(1, 'cup', 'tablespoon') == 16.0
'''


# ---------------------------------------------------------------------------
# Fingerprint 1 — dead property test
# ---------------------------------------------------------------------------


def test_dead_property_fires_on_the_uncalled_nested_given():
    findings = ctq.scan_dead_property_tests(DEAD_PROPERTY)
    assert len(findings) == 1
    assert findings[0].cls == ctq.CLASS_DEAD_PROPERTY
    assert "test_conversion_consistency" in findings[0].message
    assert findings[0].hard, "a provably-never-executed property test must be blocking-eligible"


def test_dead_property_silent_when_the_nested_given_is_called():
    """battery-b1/b6 ship exactly this idiom and DO execute — flagging it would be a
    false block on the fleet's normal, correct output."""
    assert ctq.scan_dead_property_tests(LIVE_PROPERTY) == []


def test_dead_property_silent_on_a_module_level_given():
    assert ctq.scan_dead_property_tests(MODULE_LEVEL_PROPERTY) == []


def test_dead_property_silent_on_a_file_with_no_property_tests():
    assert ctq.scan_dead_property_tests(VACUOUS) == []


# ---------------------------------------------------------------------------
# Fingerprint 2 — vacuous test
# ---------------------------------------------------------------------------


def test_vacuous_fires_on_the_no_assertion_test():
    findings = ctq.scan_vacuous_tests(VACUOUS)
    assert len(findings) == 1
    assert findings[0].cls == ctq.CLASS_VACUOUS_TEST
    assert findings[0].subject == "test_requirement_4_default_path_cards_json"
    assert findings[0].hard


@pytest.mark.parametrize("source", [RAISES_SMOKE, UNITTEST_STYLE, ACCOMMODATED, HONEST_TOLERANCE])
def test_vacuous_silent_when_a_verdict_is_borne(source):
    """pytest.raises, unittest assertions and plain asserts all carry a verdict."""
    assert ctq.scan_vacuous_tests(source) == []


def test_vacuous_does_not_double_report_a_dead_property_test():
    """The dead-property outer function has no assert of its own. Reporting it as
    vacuous TOO would inflate the count the operator steers by — one defect, one row."""
    assert ctq.scan_vacuous_tests(DEAD_PROPERTY) == []
    assert len(ctq.scan_dead_property_tests(DEAD_PROPERTY)) == 1


# ---------------------------------------------------------------------------
# Fingerprint 3 — accommodated assertion
# ---------------------------------------------------------------------------


def test_accommodated_fires_when_the_comment_names_an_unpinned_value():
    findings = ctq.scan_accommodated_assertions(ACCOMMODATED)
    assert len(findings) == 1
    assert findings[0].cls == ctq.CLASS_ACCOMMODATED_ASSERTION
    assert "0.0353" in findings[0].message


def test_accommodated_is_soft_never_blocking_on_its_own():
    """It reads prose, and prose is not proof. It must summon a look, not park a night."""
    findings = ctq.scan_accommodated_assertions(ACCOMMODATED)
    assert findings and not findings[0].hard


def test_accommodated_silent_on_an_honest_tolerance():
    """The comment names 0.5 and the assertion uses 0.5 — nothing is being dodged."""
    assert ctq.scan_accommodated_assertions(HONEST_TOLERANCE) == []


def test_accommodated_silent_when_the_band_endpoints_are_the_named_values():
    assert ctq.scan_accommodated_assertions(HONEST_BAND) == []


def test_accommodated_silent_on_an_equality_assertion():
    """A plain `==` pins the answer by construction and can never be an accommodation."""
    src = '''
def test_exact():
    # the exact conversion should be 16.0 tablespoons per cup
    assert convert(1, 'cup', 'tablespoon') == 16.0
'''
    assert ctq.scan_accommodated_assertions(src) == []


def test_accommodated_silent_without_hedging_vocabulary():
    src = '''
def test_band():
    # bounds from the spec table, row 4
    assert 0.01 <= convert(1, 'gram', 'ounce') <= 0.1
'''
    assert ctq.scan_accommodated_assertions(src) == []


# ---------------------------------------------------------------------------
# Fingerprint 4 — decorative hypothesis
# ---------------------------------------------------------------------------


def test_decorative_hypothesis_fires_when_nothing_can_run():
    findings = ctq.scan_decorative_hypothesis(DECORATIVE)
    assert len(findings) == 1
    assert findings[0].cls == ctq.CLASS_DECORATIVE_HYPOTHESIS
    assert not findings[0].hard


@pytest.mark.parametrize("source", [LIVE_PROPERTY, MODULE_LEVEL_PROPERTY])
def test_decorative_hypothesis_silent_when_a_property_test_can_execute(source):
    assert ctq.scan_decorative_hypothesis(source) == []


def test_decorative_hypothesis_silent_without_the_import():
    assert ctq.scan_decorative_hypothesis(VACUOUS) == []


# ---------------------------------------------------------------------------
# Runtime proof — Hypothesis statistics
# ---------------------------------------------------------------------------

STATS_REAL = """
tests/test_converter.py::test_round_trip:
  - during generate phase (0.14 seconds):
    - Typical runtimes: < 1ms, ~ 47% in data generation
    - 100 passing examples, 0 failing examples, 3 invalid examples
"""

STATS_ZERO = """
tests/test_converter.py::test_property_based_conversions:
  - during generate phase (0.00 seconds):
    - 0 passing examples, 0 failing examples, 0 invalid examples
"""


def test_example_count_sums_every_property_test():
    assert ctq.parse_hypothesis_example_count(STATS_REAL) == 103


def test_example_count_is_none_when_no_statistics_block_exists():
    """Absent is not zero. Reporting an unmeasured run as a measured zero would invent
    a failure — the same sin, pointed the other way."""
    assert ctq.parse_hypothesis_example_count("12 passed in 0.20s") is None


def test_property_execution_fires_on_a_measured_zero():
    finding = ctq.property_execution_finding(STATS_ZERO, property_test_required=True)
    assert finding is not None
    assert finding.cls == ctq.CLASS_UNEXECUTED_PROPERTY
    assert finding.hard, "Hypothesis' own count is proof, not inference"


def test_property_execution_silent_when_examples_were_generated():
    assert ctq.property_execution_finding(STATS_REAL, property_test_required=True) is None


def test_property_execution_silent_when_statistics_are_absent():
    assert ctq.property_execution_finding("12 passed", property_test_required=True) is None


def test_property_execution_silent_when_no_property_test_was_required():
    assert ctq.property_execution_finding(STATS_ZERO, property_test_required=False) is None


# ---------------------------------------------------------------------------
# Result shape, severity split and the kill-switch
# ---------------------------------------------------------------------------


def test_scan_source_qualifies_subjects_with_the_file_name():
    findings = ctq.scan_source(VACUOUS, path="test_data_storage.py")
    assert findings
    assert all(f.subject.startswith("test_data_storage.py::") for f in findings)


def test_counts_carry_the_full_taxonomy_even_at_zero():
    """A stable evidence shape: a class that did not fire reads 0, never absent."""
    result = ctq.CoderTestQAResult(findings=list(ctq.scan_source(VACUOUS)))
    counts = result.counts()
    assert set(counts) == set(ctq.ALL_CODER_TEST_CLASSES)
    assert counts[ctq.CLASS_VACUOUS_TEST] == 1
    assert counts[ctq.CLASS_DEAD_PROPERTY] == 0


def test_only_provable_classes_are_hard():
    """The severity split is the whole safety argument: AST- and statistics-provable
    defects may block; prose heuristics may only report."""
    assert ctq.is_hard(ctq.CLASS_DEAD_PROPERTY)
    assert ctq.is_hard(ctq.CLASS_VACUOUS_TEST)
    assert ctq.is_hard(ctq.CLASS_UNEXECUTED_PROPERTY)
    assert not ctq.is_hard(ctq.CLASS_ACCOMMODATED_ASSERTION)
    assert not ctq.is_hard(ctq.CLASS_DECORATIVE_HYPOTHESIS)


def test_finding_hard_resolves_against_the_coder_test_taxonomy():
    """The reason this module does not reuse OracleFinding: that type's `hard` resolves
    against the job-oracle taxonomy, which contains none of these classes, so every
    provable defect would have answered `hard == False` — a silent fail-open."""
    from shared.fleet.oracle_qa import OracleFinding

    assert not OracleFinding(ctq.CLASS_DEAD_PROPERTY, "x").hard
    assert ctq.CoderTestFinding(ctq.CLASS_DEAD_PROPERTY, "x").hard


def test_hard_findings_filter_selects_only_the_provable():
    result = ctq.CoderTestQAResult(findings=list(ctq.scan_source(ACCOMMODATED)))
    assert result.findings, "the accommodated fixture must produce a finding"
    assert result.hard_findings == []


def test_kill_switch_defaults_on_and_honours_falsey_tokens():
    assert ctq.coder_test_qa_enabled({})
    assert ctq.coder_test_qa_enabled({"BLARAI_CODER_TEST_QA": "1"})
    for token in ("0", "false", "no", "off", "OFF", " False "):
        assert not ctq.coder_test_qa_enabled({"BLARAI_CODER_TEST_QA": token}), token


def test_unparseable_source_never_raises():
    """A syntax error in a test file is the TEST gate's business — already red there.
    This layer must degrade quietly rather than crash the dispatch."""
    assert ctq.scan_source("def test_(:\n  pass") == []


# ---------------------------------------------------------------------------
# The original evidence — the defect this ticket was opened for
# ---------------------------------------------------------------------------


def test_the_07_29_ceremony_check_defect_is_caught():
    """End-to-end over the exact merged shape: the dead property test AND the widened
    band both surface, and the dead one is blocking-eligible. If a future refactor stops
    catching this, the merge that started #1170 would sail through again."""
    findings = ctq.scan_source(DEAD_PROPERTY + ACCOMMODATED)
    classes = {f.cls for f in findings}
    assert ctq.CLASS_DEAD_PROPERTY in classes
    assert ctq.CLASS_ACCOMMODATED_ASSERTION in classes
    assert any(f.hard for f in findings)


# ---------------------------------------------------------------------------
# #1201 — attribution: a task answers for the exam IT wrote
# ---------------------------------------------------------------------------
#
# The scan used to read the whole delivered tree, so on any repo with history every
# green-gated task was charged for tests it never touched: 419 files / hard=48 on a
# clean BlarAI checkout, and inside the battery's own use case task N paid the review
# laps for the vacuous tests of tasks 1..N-1 (the scaffold is fresh per NIGHT, not per
# TASK). Everything below drives the REAL git plumbing and the REAL CLI over REAL repos
# on disk — the defect was in what the scanner was pointed AT, which a fixture string
# cannot reproduce.


def _git(repo: Path, *args: str) -> str:
    """A test-side git call. Identity is supplied per-invocation so the suite never
    depends on the box having a configured committer."""
    proc = subprocess.run(
        ["git", "-C", str(repo),
         "-c", "user.email=test@local", "-c", "user.name=test",
         "-c", "commit.gpgsign=false", *args],
        capture_output=True, text=True, check=True, timeout=60,
    )
    return proc.stdout


def _commit(repo: Path, message: str, files: "dict[str, str]") -> str:
    """Write *files* under *repo*, commit them, return the new HEAD."""
    for rel, body in files.items():
        path = repo / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")
    _git(repo, "add", "--", *files)
    _git(repo, "commit", "-m", message)
    return _git(repo, "rev-parse", "HEAD").strip()


@pytest.fixture
def battery_night(tmp_path: Path) -> "dict[str, object]":
    """One night, three tasks against ONE repo — the shape the battery actually runs.

    Task 1 ships a test that cannot fail. Tasks 2 and 3 ship sound ones. Every task's
    baseline is HEAD at the moment it starts, exactly as ``new-agent-task.ps1`` computes
    ``$codeBase``. This is the ticket's own scenario, on disk."""
    repo = tmp_path / "night"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    base = _commit(repo, "baseline before task: task-1", {"README.md": "night\n"})

    task1 = _commit(repo, "task 1", {"tests/test_task1.py": VACUOUS})
    task2 = _commit(repo, "task 2", {"tests/test_task2.py": RAISES_SMOKE})
    task3 = _commit(repo, "task 3", {"tests/test_task3.py": UNITTEST_STYLE})
    return {"repo": repo, "base": base,
            "baseline_of_task1": base, "baseline_of_task2": task1,
            "baseline_of_task3": task2, "head": task3}


def test_a_later_task_is_not_charged_for_an_earlier_tasks_vacuous_test(battery_night):
    """The ticket's predicate, first half: task 3's report does not carry task 1's
    vacuous test."""
    repo = battery_night["repo"]
    scope = ctq.resolve_scope(str(repo), battery_night["baseline_of_task3"])
    assert scope.resolved and scope.mode == ctq.SCOPE_CHANGED_SINCE

    result = ctq.scan_paths(ctq.discover_test_files(str(repo), scope=scope))
    assert [Path(p).name for p in ctq.discover_test_files(str(repo), scope=scope)] == \
        ["test_task3.py"], "task 3 wrote exactly one test file"
    assert result.findings == [], "task 3's exam is sound; nothing may be charged to it"


def test_the_unscoped_scan_really_does_carry_the_earlier_tasks_defect(battery_night):
    """The toggle. Without the scope the SAME tree yields task 1's finding — so the
    test above is proving that scoping WORKS, not that the fixture is toothless or that
    the scanner has gone blind."""
    repo = battery_night["repo"]
    result = ctq.scan_paths(ctq.discover_test_files(str(repo)))
    assert result.files_scanned == 3
    assert [f.cls for f in result.findings] == [ctq.CLASS_VACUOUS_TEST]
    assert "test_task1.py" in result.findings[0].subject


def test_the_task_that_wrote_the_defect_is_still_charged_for_it(battery_night):
    """Scoping must not become a way to escape the finding. Task 1 wrote the vacuous
    test, and task 1's own scope still contains it."""
    repo = battery_night["repo"]
    # Task 1's tree state, examined against task 1's baseline.
    _git(repo, "checkout", "--detach", battery_night["baseline_of_task2"])
    try:
        scope = ctq.resolve_scope(str(repo), battery_night["baseline_of_task1"])
        result = ctq.scan_paths(ctq.discover_test_files(str(repo), scope=scope))
        assert [f.cls for f in result.findings] == [ctq.CLASS_VACUOUS_TEST]
        assert "test_task1.py" in result.findings[0].subject
    finally:
        _git(repo, "checkout", "main")


def test_a_repo_with_unrelated_history_reports_nothing_for_a_task_that_touched_none_of_it(tmp_path):
    """The ticket's predicate, second half — and the failure that outlives the battery:
    point the dispatch at any repo with history and every green-gated task used to lose
    its review-skip forever, on tests the coder never wrote."""
    repo = tmp_path / "with-history"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _commit(repo, "history", {
        "tests/test_legacy_a.py": VACUOUS,
        "tests/test_legacy_b.py": DEAD_PROPERTY,
        "tests/test_legacy_c.py": ACCOMMODATED,
    })
    baseline = _git(repo, "rev-parse", "HEAD").strip()
    _commit(repo, "the task", {"docs/notes.md": "the task changed no test\n"})

    unscoped = ctq.scan_paths(ctq.discover_test_files(str(repo)))
    assert len(unscoped.hard_findings) >= 2, "the history genuinely does carry defects"

    scope = ctq.resolve_scope(str(repo), baseline)
    scoped = ctq.scan_paths(ctq.discover_test_files(str(repo), scope=scope))
    assert scoped.files_scanned == 0
    assert scoped.findings == []


def test_scope_covers_uncommitted_and_untracked_work(tmp_path):
    """A superset of what the task committed, never a subset. A test left dirty or
    never added is still an exam the task wrote, and missing one would put the defect
    back where nothing looks at it."""
    repo = tmp_path / "dirty"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    baseline = _commit(repo, "baseline", {"tests/test_existing.py": RAISES_SMOKE})

    (repo / "tests" / "test_existing.py").write_text(VACUOUS, encoding="utf-8")   # dirty
    (repo / "tests" / "test_new.py").write_text(DEAD_PROPERTY, encoding="utf-8")  # untracked

    scope = ctq.resolve_scope(str(repo), baseline)
    found = sorted(Path(p).name for p in ctq.discover_test_files(str(repo), scope=scope))
    assert found == ["test_existing.py", "test_new.py"]
    result = ctq.scan_paths(ctq.discover_test_files(str(repo), scope=scope))
    assert {f.cls for f in result.hard_findings} == {ctq.CLASS_VACUOUS_TEST, ctq.CLASS_DEAD_PROPERTY}


def test_gitignored_files_stay_out_of_scope(tmp_path):
    """An ignored file cannot merge, so it is not part of the exam that ships."""
    repo = tmp_path / "ignored"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    baseline = _commit(repo, "baseline", {".gitignore": "scratch/\n"})
    (repo / "scratch").mkdir()
    (repo / "scratch" / "test_scratch.py").write_text(VACUOUS, encoding="utf-8")

    scope = ctq.resolve_scope(str(repo), baseline)
    assert ctq.discover_test_files(str(repo), scope=scope) == []


# ---------------------------------------------------------------------------
# #1201 — the undeterminable scope: no verdict, loudly
# ---------------------------------------------------------------------------


def test_an_unresolved_scope_admits_nothing_and_scans_nothing(tmp_path):
    """The decision this ticket had to make. A baseline that cannot be resolved yields
    NO verdict: not a silent widening to the whole tree (that is the mis-attribution
    wearing a different hat) and not a silent zero (that is worse — it reads as a clean
    exam)."""
    repo = tmp_path / "no-such-baseline"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _commit(repo, "baseline", {"tests/test_bad.py": VACUOUS})

    scope = ctq.resolve_scope(str(repo), "deadbeef" * 5)
    assert not scope.resolved
    assert scope.mode == ctq.SCOPE_UNRESOLVED
    assert "deadbeef" in scope.reason, "the cause is named, not swallowed"
    assert not scope.admits(repo / "tests" / "test_bad.py")
    assert ctq.discover_test_files(str(repo), scope=scope) == []


def test_an_unresolved_scope_is_not_silently_widened(tmp_path):
    """The specific wrong answer, pinned. Falling back to the whole tree would make the
    unresolved path indistinguishable from the pre-#1201 behaviour."""
    repo = tmp_path / "not-a-repo"
    repo.mkdir()
    (repo / "tests").mkdir()
    (repo / "tests" / "test_bad.py").write_text(VACUOUS, encoding="utf-8")

    scope = ctq.resolve_scope(str(repo), "main")
    assert scope.mode == ctq.SCOPE_UNRESOLVED
    assert scope.mode != ctq.SCOPE_FULL_TREE
    assert ctq.discover_test_files(str(repo), scope=scope) == []
    # ...while the tree really does contain a finding, so this is a refusal, not a miss.
    assert ctq.scan_paths(ctq.discover_test_files(str(repo))).hard_findings


def test_the_full_tree_mode_says_what_it_is():
    """No baseline is a legitimate question ("what does this tree contain") and a
    legitimate answer — provided the answer states which question it answered."""
    scope = ctq.full_tree_scope()
    assert scope.resolved and scope.mode == ctq.SCOPE_FULL_TREE
    assert "not to one task" in scope.reason
    assert scope.to_evidence()["mode"] == ctq.SCOPE_FULL_TREE


@pytest.mark.parametrize("ref", [
    "--upload-pack=whoami",     # option injection
    "-x",                       # ...even a short one
    "HEAD..main",               # a range would change what is compared
    "main@{1}",                 # a reflog selector
    "../../../etc/passwd",      # traversal
    "refs/heads/main.lock",     # a lock name
    "main;whoami",              # shell metacharacters (argv is a list, but deny anyway)
    "",                         # empty
    "x" * 300,                  # absurd length
])
def test_a_baseline_that_is_not_a_plain_ref_is_refused_before_git_sees_it(ref, tmp_path):
    assert not ctq._valid_baseline_ref(ref)
    repo = tmp_path / "guard"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _commit(repo, "baseline", {"tests/test_x.py": VACUOUS})
    scope = ctq.resolve_scope(str(repo), ref)
    assert scope.mode == ctq.SCOPE_UNRESOLVED
    assert "refused" in scope.reason or "could not" in scope.reason


@pytest.mark.parametrize("ref", ["a1b2c3d", "a" * 40, "main", "feature/1201-scope", "v1.2.3"])
def test_a_plain_commit_id_or_branch_name_is_accepted(ref):
    """The negative half of the guard: a validator that refuses everything protects
    nothing, because the scoping it gates would never run."""
    assert ctq._valid_baseline_ref(ref)


@pytest.mark.parametrize("rel", ["../outside.py", "a/../../outside.py", "C:/windows/x.py",
                                 "/etc/passwd", "\\\\server\\share\\x.py", ""])
def test_a_reported_path_that_escapes_the_repo_is_refused(rel):
    """Git does not emit these from the plumbing reads used here, so one appearing means
    the output is not what it claims to be — and the scope is refused rather than
    trusted. Validated BEFORE normalisation, which would otherwise fold a traversal into
    a legitimate-looking path."""
    assert not ctq._relative_paths_are_safe([rel])


def test_a_git_read_goes_through_the_BLESSED_SPAWN_HELPER_not_raw_subprocess(
        tmp_path, monkeypatch):
    """#1239 — a REACHABILITY lock, which is the only kind that can hold this.

    ``_git`` shipped calling ``subprocess.run`` directly. Every behaviour visible from
    inside this suite was identical, which is why the whole `resolve_scope` suite was
    green over it and why `tests/integration/test_no_new_raw_spawn_sites.py` — a scan of
    the SOURCE, not of behaviour — is what caught it. What differed lives outside the
    process: an inherited stdin a git credential helper or pager can block on forever, and
    a timeout that kills the direct child while leaving its grandchildren alive. Neither is
    observable from a passing test on a healthy box, and both bite on the unattended
    overnight battery path where nobody is watching.

    So this asserts the ROUTE rather than the result: the real git reads still run, and
    every spawn goes through the helper carrying those guarantees. Revert ``_git`` to
    ``subprocess.run`` and ``seen`` is empty."""
    import shared.procspawn as procspawn

    repo = tmp_path / "routed"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    base = _commit(repo, "baseline", {"tests/test_x.py": VACUOUS})
    _commit(repo, "the task's work", {"tests/test_new.py": VACUOUS})

    seen: "list[dict]" = []
    real = procspawn.run_captured

    def recording(argv, **kwargs):
        seen.append({"argv": list(argv), "kwargs": dict(kwargs)})
        return real(argv, **kwargs)

    monkeypatch.setattr(procspawn, "run_captured", recording)
    scope = ctq.resolve_scope(str(repo), base)

    # The reads really ran — a route assertion over a scope that failed to resolve would
    # pass for the wrong reason.
    assert scope.mode == ctq.SCOPE_CHANGED_SINCE, scope.reason
    assert seen, (
        "resolve_scope resolved a scope without calling shared.procspawn.run_captured, so "
        "its git reads are spawning by some other route — that is the #1239 defect"
    )
    for call in seen:
        assert call["argv"][0] == "git", call["argv"]
        assert "timeout_s" in call["kwargs"], (
            f"a git read was spawned with no timeout bound: {call['argv']}"
        )


def test_a_git_read_that_TIMES_OUT_is_an_unresolved_scope_that_names_the_tree_kill(
        tmp_path, monkeypatch):
    """The other half: ``run_captured`` REPORTS a timeout where ``subprocess.run`` RAISED
    one, so the branch that handles it is new code and needs to be watched going red.

    An exam whose scope could not be established must admit nothing and say why — the
    failure that matters here is the one where a timed-out read quietly returns an empty
    change set, which reads exactly like "the task changed nothing" and would grade a
    task on an empty scan.

    NAMED COUPLING: this stubs ``run_captured`` to RETURN a timed-out result, so it proves
    ``_git`` handles the report — NOT that ``run_captured`` reports rather than raises. If
    the helper ever regressed to raising ``TimeoutExpired``, this test would stay green
    while the narrowed ``except OSError`` in ``_git`` let it escape ``resolve_scope``. The
    report-don't-raise contract is locked in the owning module, by
    ``shared/tests/test_procspawn.py::test_r5_run_captured_timeout_tree_kills``, which
    drives the real helper unwrapped. Written down because the dependency is otherwise
    invisible from the test that rests on it."""
    import shared.procspawn as procspawn

    repo = tmp_path / "slow"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    base = _commit(repo, "baseline", {"tests/test_x.py": VACUOUS})

    def timing_out(argv, **kwargs):
        return procspawn.CapturedResult(
            pid=0, returncode=None, stdout="", stderr="",
            timed_out=True, seconds=kwargs["timeout_s"])

    monkeypatch.setattr(procspawn, "run_captured", timing_out)
    scope = ctq.resolve_scope(str(repo), base)

    assert scope.mode == ctq.SCOPE_UNRESOLVED, (
        f"a git read that never finished produced a {scope.mode!r} scope — an exam graded "
        f"on it would be scanning a change set nobody measured"
    )
    assert "did not finish" in scope.reason, scope.reason
    assert "tree was killed" in scope.reason, scope.reason


def test_a_test_file_the_task_DELETED_is_named_by_git_and_costs_nothing(tmp_path):
    """The production shape behind the "never opened" claim, in place of the claim.

    A task that deletes a test file makes git name a path that is not on disk. A scanner
    that opened its scope's paths would raise here; one that only ever uses them as
    comparison keys does not notice. This is a shape the real dispatch emits — a coder
    removing its own bad test during a review-FIX lap does exactly it."""
    repo = tmp_path / "deleted"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    baseline = _commit(repo, "baseline", {"tests/test_gone.py": VACUOUS,
                                          "tests/test_kept.py": RAISES_SMOKE})
    _git(repo, "rm", "-q", "--", "tests/test_gone.py")
    _git(repo, "commit", "-m", "the task deleted its own bad test")

    scope = ctq.resolve_scope(str(repo), baseline)
    assert scope.resolved
    assert any("test_gone" in k for k in scope.keys), "git really does name the deletion"
    assert ctq.discover_test_files(str(repo), scope=scope) == [], "and nothing is opened for it"
    assert ctq.scan_paths(ctq.discover_test_files(str(repo), scope=scope)).findings == []


def test_a_baseline_that_also_names_a_file_is_read_as_a_revision(tmp_path):
    """The `--` separator, proved rather than commented.

    A name that is BOTH a ref and a path in the same repo is ambiguous to git, and the
    separator is what settles it. The toggle is inside the test: the identical argument
    is handed to git with and without the separator, and only one of them answers."""
    repo = tmp_path / "ambiguous"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    baseline = _commit(repo, "baseline", {"snapshot": "a file whose name is also a ref\n",
                                          "tests/test_old.py": RAISES_SMOKE})
    _git(repo, "branch", "snapshot", baseline)      # now `snapshot` is a ref AND a path
    _commit(repo, "the task", {"tests/test_new.py": VACUOUS})

    by_name = ctq.resolve_scope(str(repo), "snapshot")
    by_sha = ctq.resolve_scope(str(repo), baseline)
    assert by_name.resolved and by_sha.resolved
    assert by_name.keys == by_sha.keys, "the ref name and its commit id must agree"
    assert [Path(p).name for p in ctq.discover_test_files(str(repo), scope=by_name)] == \
        ["test_new.py"]

    # The toggle: the same read WITHOUT the separator this module always passes.
    bare = subprocess.run(["git", "-C", str(repo), "diff", "--name-only", "snapshot"],
                          capture_output=True, text=True, timeout=60)
    assert bare.returncode != 0 and "ambiguous" in bare.stderr.lower(), (
        "if git ever stops refusing the bare form, this test is no longer proving the "
        f"separator is load-bearing: {bare.returncode} {bare.stderr!r}")


def test_the_legacy_payload_keys_all_survive_in_the_new_one(battery_night):
    """The cross-repo contract, pinned to an OBSERVED shape. These six keys are what the
    pre-#1201 scanner emitted — verified by running that module out of git history, not
    recalled — and every one must still be present. The harness's version-skew guard keys
    on the ADDITION of `scope`, so a dropped legacy key would break an old consumer
    silently instead of loudly."""
    legacy_keys = {"counts", "enabled", "files_scanned", "findings", "hard", "unparsed"}
    payload = _run_cli(battery_night["repo"], "--since", battery_night["baseline_of_task3"])
    assert legacy_keys <= set(payload)
    assert "scope" in payload, "and the one addition the guard detects is present"


def test_the_scope_is_a_filter_never_a_source_of_paths(tmp_path):
    """Why traversal cannot reach a file even if the guard above were bypassed: the
    scanner only ever asks whether a path IT discovered is admitted. A key naming a file
    outside the scanned root can therefore never cause that file to be read.

    Note the fixture builds a TestScope by hand — this is a unit test of the structural
    property, not a production path; the production shapes are covered above."""
    outside = tmp_path / "outside" / "test_secret.py"
    outside.parent.mkdir(parents=True)
    outside.write_text(VACUOUS, encoding="utf-8")
    root = tmp_path / "root"
    (root / "tests").mkdir(parents=True)
    (root / "tests" / "test_inside.py").write_text(RAISES_SMOKE, encoding="utf-8")

    scope = ctq.TestScope(ctq.SCOPE_CHANGED_SINCE, since="x",
                          keys=frozenset({ctq._scope_key(outside)}))
    assert scope.admits(outside), "the key is present..."
    assert ctq.discover_test_files(str(root), scope=scope) == [], \
        "...and still nothing outside the scanned root is opened"


# ---------------------------------------------------------------------------
# #1201 — the directories that are never this coder's exam
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("excluded", [".worktrees", ".claude", ".git", ".venv", ".tox"])
def test_another_checkouts_tests_are_not_this_coders_exam(excluded, tmp_path):
    """Nested agent worktrees inflated an ad-hoc scan of the live BlarAI checkout to
    9,791 files / hard=3242 / 81 s, every one of them another session's work."""
    root = tmp_path / "root"
    (root / excluded / "nested" / "tests").mkdir(parents=True)
    (root / excluded / "nested" / "tests" / "test_other.py").write_text(VACUOUS, encoding="utf-8")
    assert ctq.discover_test_files(str(root)) == []


def test_the_exclusion_is_about_the_directory_not_the_file(tmp_path):
    """The toggle for the case above: the identical file OUTSIDE those directories is
    found. Without this, the exclusion tests would pass just as well against a scanner
    that had stopped finding anything at all."""
    root = tmp_path / "root"
    (root / "tests").mkdir(parents=True)
    (root / "tests" / "test_other.py").write_text(VACUOUS, encoding="utf-8")
    found = ctq.discover_test_files(str(root))
    assert [Path(p).name for p in found] == ["test_other.py"]


# ---------------------------------------------------------------------------
# #1201 — the CLI contract the PowerShell harness reads
# ---------------------------------------------------------------------------


def _run_cli(repo: Path, *args: str) -> dict:
    """Drive the REAL entry point the harness drives — `python -m shared.fleet.coder_test_qa`
    — and parse the single JSON object it prints, exactly as `Invoke-CoderTestQa` does."""
    env = dict(os.environ)
    env["PYTHONPATH"] = str(_REPO_ROOT)
    proc = subprocess.run(
        [sys.executable, "-m", "shared.fleet.coder_test_qa", str(repo), *args],
        cwd=str(_REPO_ROOT), capture_output=True, text=True, timeout=180, env=env,
    )
    assert proc.returncode == 0, f"the CLI must always exit 0: {proc.stderr[-400:]}"
    line = [ln for ln in proc.stdout.splitlines() if ln.strip().startswith("{")][-1]
    return json.loads(line)


def test_the_cli_scopes_to_the_baseline_and_says_that_it_did(battery_night):
    """The seam itself: what the harness passes in and what it can read back out."""
    payload = _run_cli(battery_night["repo"], "--since", battery_night["baseline_of_task3"])
    assert payload["enabled"] is True
    assert payload["hard"] == 0
    assert payload["findings"] == []
    assert payload["files_scanned"] == 1
    assert payload["scope"]["mode"] == ctq.SCOPE_CHANGED_SINCE
    assert payload["scope"]["resolved"] is True
    assert payload["scope"]["since"] == battery_night["baseline_of_task3"]


def test_the_cli_without_a_baseline_reports_the_whole_tree_and_flags_it_as_such(battery_night):
    """The toggle at the seam. The same repo, no --since: the earlier task's finding
    comes back AND the payload states that this is a reading of the tree."""
    payload = _run_cli(battery_night["repo"])
    assert payload["hard"] == 1
    assert payload["scope"]["mode"] == ctq.SCOPE_FULL_TREE
    assert payload["scope"]["resolved"] is True


def test_the_cli_emits_an_unresolved_scope_rather_than_a_clean_looking_zero(battery_night):
    """A consumer that reads only `hard` sees 0 here — which is why `scope.resolved` is
    a first-class field and the harness gates on it. The zero is honest about being the
    absence of a measurement, not the result of one."""
    payload = _run_cli(battery_night["repo"], "--since", "deadbeef" * 5)
    assert payload["enabled"] is True
    assert payload["hard"] == 0
    assert payload["files_scanned"] == 0
    assert payload["scope"]["resolved"] is False
    assert payload["scope"]["mode"] == ctq.SCOPE_UNRESOLVED
    assert payload["scope"]["reason"]


def test_the_kill_switch_payload_still_carries_a_scope_field(battery_night):
    """Every exit carries every field, so no consumer ever reads a missing key as a
    zero — the convention `New-CoderTestQaResult` holds on the PowerShell side."""
    env_before = os.environ.get("BLARAI_CODER_TEST_QA")
    os.environ["BLARAI_CODER_TEST_QA"] = "0"
    try:
        payload = _run_cli(battery_night["repo"], "--since", battery_night["baseline_of_task3"])
    finally:
        if env_before is None:
            os.environ.pop("BLARAI_CODER_TEST_QA", None)
        else:
            os.environ["BLARAI_CODER_TEST_QA"] = env_before
    assert payload["enabled"] is False
    assert payload["scope"]["resolved"] is False


def test_every_cli_exit_carries_the_same_keys(battery_night):
    """The shape the harness parses is stable across the scoped, unscoped, unresolved
    and switched-off exits. A key that appears on only some paths is a key some caller
    will read as absent-meaning-zero."""
    expected = {"enabled", "hard", "findings", "counts", "files_scanned", "unparsed", "scope"}
    env_before = os.environ.get("BLARAI_CODER_TEST_QA")
    payloads = [
        _run_cli(battery_night["repo"], "--since", battery_night["baseline_of_task3"]),
        _run_cli(battery_night["repo"]),
        _run_cli(battery_night["repo"], "--since", "deadbeef" * 5),
    ]
    os.environ["BLARAI_CODER_TEST_QA"] = "0"
    try:
        payloads.append(_run_cli(battery_night["repo"]))
    finally:
        if env_before is None:
            os.environ.pop("BLARAI_CODER_TEST_QA", None)
        else:
            os.environ["BLARAI_CODER_TEST_QA"] = env_before
    for payload in payloads:
        assert expected <= set(payload), sorted(expected - set(payload))
        assert set(payload["counts"]) == set(ctq.ALL_CODER_TEST_CLASSES)
        assert set(payload["scope"]) == {"mode", "resolved", "since", "changed_files", "reason"}
