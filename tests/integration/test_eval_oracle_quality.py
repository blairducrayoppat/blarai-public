"""
Oracle-Quality Eval Suite — Standing-Gate Integration Tests (#765)
===================================================================
Locks the oracle_quality suite (evals/suites/oracle_quality.py + the check
engine evals/oracle_checks.py) into the standing gate:

  A. Check engine — the execution-outcome CLASSIFIER maps every pytest exit
     shape onto the #765 failure-mode vocabulary (collection-error, the
     #752-F3 plumbing class, must never read as a plain test failure), and
     every static-trust flag has a firing case.
  B. Real-fixture execution — the recorded known-good B2 job oracle passes
     the frozen known-good reference through the REAL subprocess runner
     (soundness), and an append-override mutation flips it to failed
     (sensitivity) — the engine's teeth proven in-gate, no model needed.
  C. Suite semantics over the REAL golden file — offline cases green, the
     model case hardware-skipped, malformed cases fail-closed.
  D. Honest hardware posture — include_hardware without an injected
     generator reports ERROR naming the #765 live-slot step, never a faked
     measurement (the real-generator wiring is deliberately not built yet).
  E. Contract + criteria-coverage checks — the ticket's remaining two
     offline static-check bullets: the #752-F3 import/contract class
     (reused verbatim from the real #821 production check, locked as the
     SAME function object, not a copy) and the criteria-coverage lexical
     heuristic (a genuine gap flags, a real-world tier filter holds, and
     the documented paraphrase blind spot is pinned, not hidden).

(The generic per-suite locks — golden loads, baseline compares clean, exit
codes — fire from tests/integration/test_eval_harness.py, which
parametrizes over SUITE_NAMES and now includes oracle_quality.)
"""

from __future__ import annotations

from pathlib import Path

import pytest

from evals import oracle_checks as oc
from evals.loader import GoldenDataError
from evals.suites.oracle_quality import _FIXTURES_DIR, run_suite
from evals.types import CaseStatus
from shared.fleet import oracle_qa as fleet_oracle_qa

_REFERENCE = _FIXTURES_DIR / "b2_reference"
_ORACLE = (_FIXTURES_DIR / "b2_job_oracle.py")

#: The real B2 job oracle's behavior criteria, in the AcceptanceCriterion
#: dict shape (mirrors evals/golden/oracle_quality.jsonl's oq-covg-* cases).
_B2_CRITERIA = [
    {"id": "c1", "tier": "behavior", "text": "the tool splits text into lowercase words",
     "check": "tokenize returns a list of lowercase tokens"},
    {"id": "c2", "tier": "behavior", "text": "the tool counts how often each word appears",
     "check": "word_frequencies returns counts per word"},
    {"id": "c3", "tier": "behavior", "text": "the tool counts adjacent word pairs",
     "check": "neighbor_pairs returns counts per adjacent pair"},
    {"id": "c4", "tier": "behavior", "text": "the tool combines both findings into one report",
     "check": "combined_report returns a joined string"},
]


# ---------------------------------------------------------------------------
# A. The check engine
# ---------------------------------------------------------------------------


def test_classifier_maps_every_exit_shape():
    assert oc._classify(0, "").status == oc.RUN_PASSED
    assert oc._classify(1, "1 failed").status == oc.RUN_FAILED
    assert oc._classify(5, "no tests ran").status == oc.RUN_COLLECTION_ERROR
    assert oc._classify(2, "!! Errors during collection !!").status == oc.RUN_COLLECTION_ERROR
    assert oc._classify(3, "INTERNALERROR").status == oc.RUN_CRASH


def test_static_flags_each_fire():
    assert oc.FLAG_DEGENERATE_ASSERT in oc.static_oracle_findings(
        "def test_x():\n    assert True\n").flags
    assert oc.FLAG_MODULE_SKIP in oc.static_oracle_findings(
        "import pytest\npytest.skip('x', allow_module_level=True)\n").flags
    assert oc.FLAG_NO_TESTS in oc.static_oracle_findings("def helper():\n    pass\n").flags
    assert oc.FLAG_SYNTAX_ERROR in oc.static_oracle_findings("def test_(:\n").flags
    assert oc.FLAG_LOW_ASSERTIONS in oc.static_oracle_findings(
        "def test_no_asserts():\n    x = 1\n").flags


def test_static_clean_oracle_has_no_flags():
    findings = oc.static_oracle_findings(_ORACLE.read_text(encoding="utf-8"))
    assert findings.flags == ()
    assert findings.test_count >= 3          # the real B2 oracle grades several criteria


def test_mutation_naming_missing_file_raises():
    # A silently-unapplied mutation would turn a sensitivity case into a false
    # pass — the engine must refuse loudly instead.
    with pytest.raises(FileNotFoundError):
        oc.run_oracle_against(
            _REFERENCE, "def test_x():\n    assert 1\n",
            mutations=[{"file": "app/does_not_exist.py", "append": "x = 1\n"}],
        )


# ---------------------------------------------------------------------------
# B. Real-fixture execution (the engine's teeth, in-gate, no model)
# ---------------------------------------------------------------------------


def test_soundness_known_good_oracle_passes_known_good_reference():
    result = oc.run_oracle_against(_REFERENCE, _ORACLE.read_text(encoding="utf-8"))
    assert result.status == oc.RUN_PASSED, result


def test_sensitivity_mutated_reference_fails():
    result = oc.run_oracle_against(
        _REFERENCE, _ORACLE.read_text(encoding="utf-8"),
        mutations=[{"file": "app/word_frequencies.py",
                    "append": "def word_frequencies(tokens):\n    return {}\n"}],
    )
    assert result.status == oc.RUN_FAILED, result


def test_failure_mode_missing_import_is_collection_error_not_failed():
    result = oc.run_oracle_against(
        _REFERENCE,
        "from app.nonexistent_module import missing\n\n"
        "def test_x():\n    assert missing() == 1\n",
    )
    assert result.status == oc.RUN_COLLECTION_ERROR, result


# ---------------------------------------------------------------------------
# C. Suite semantics over the real golden file
# ---------------------------------------------------------------------------


def test_suite_offline_green_model_skipped():
    report = run_suite()
    statuses = {r.case_id: r.status for r in report.results}
    assert statuses["oq-model-b2-job-001"] is CaseStatus.SKIPPED_HARDWARE
    offline = {k: v for k, v in statuses.items() if k != "oq-model-b2-job-001"}
    assert offline and all(s is CaseStatus.PASS for s in offline.values()), statuses


def test_malformed_case_fails_closed(tmp_path: Path):
    bad = tmp_path / "golden.jsonl"
    bad.write_text(
        '{"id": "oq-bad-001", "description": "sensitivity case missing mutations", '
        '"mode": "offline", "category": "sensitivity", '
        '"oracle_inline": "def test_x():\\n    assert 1\\n", '
        '"reference": "b2_reference", "expect": {"run_status": "failed"}}\n',
        encoding="utf-8",
    )
    with pytest.raises(GoldenDataError, match="mutations"):
        run_suite(bad)


# ---------------------------------------------------------------------------
# D. Honest hardware posture (no faked measurement)
# ---------------------------------------------------------------------------


def test_hardware_without_generator_is_honest_error():
    report = run_suite(include_hardware=True)
    model = {r.case_id: r for r in report.results}["oq-model-b2-job-001"]
    assert model.status is CaseStatus.ERROR
    assert "#765" in model.detail and "oracle_generator" in model.detail


def test_hardware_with_injected_generator_runs_the_real_machinery():
    # An injected generator drives the model-mode case end-to-end through the
    # REAL soundness runner — proving the hardware path needs only the
    # generator wiring, nothing else.
    oracle_text = _ORACLE.read_text(encoding="utf-8")
    report = run_suite(include_hardware=True,
                       oracle_generator=lambda goal_id: oracle_text)
    model = {r.case_id: r for r in report.results}["oq-model-b2-job-001"]
    assert model.status is CaseStatus.PASS, model


# ---------------------------------------------------------------------------
# E. Contract + criteria-coverage checks (the ticket's remaining two offline
#    static-check bullets)
# ---------------------------------------------------------------------------


def test_contract_check_is_the_real_821_function_not_a_copy():
    # Reuse, not reimplementation: the wrapper delegates to the SAME function
    # object the live dispatch fleet's authorship-time QA gate (#821) calls —
    # a regression here would mean the eval silently drifted onto a parallel
    # (and possibly divergent) copy of the check.
    assert oc.scan_invented_contracts is fleet_oracle_qa.scan_invented_contracts


def test_contract_findings_clean_when_all_imports_declared():
    findings = oc.contract_import_findings(
        _ORACLE.read_text(encoding="utf-8"),
        ["tokenize", "word_frequencies", "neighbor_pairs", "combined_report"],
    )
    assert findings.flags == (), findings


def test_contract_findings_flags_the_752_f3_example():
    # The literal #752 ticket example: "the seeded per-task oracle does
    # `from text_analyzer import analyze_text`; the coder named its module
    # differently" — analyze_text is not a declared export.
    findings = oc.contract_import_findings(
        "from text_analyzer import analyze_text\n\n"
        "def test_x():\n    assert analyze_text('a') is not None\n",
        ["tokenize", "summarize"],
    )
    assert oc.FLAG_IMPORT_NOT_IN_CONTRACT in findings.flags
    assert "analyze_text" in findings.invented_symbols


def test_contract_findings_empty_declared_exports_disables_check():
    # Mirrors the production fail-soft in scan_invented_contracts: no
    # contract to judge against -> never invent a false invention.
    findings = oc.contract_import_findings(
        "from text_analyzer import analyze_text\n\n"
        "def test_x():\n    assert analyze_text('a') is not None\n",
        [],
    )
    assert findings.flags == ()


def test_criteria_coverage_all_real_b2_criteria_covered():
    findings = oc.criteria_coverage_findings(_ORACLE.read_text(encoding="utf-8"), _B2_CRITERIA)
    assert findings.flags == (), findings
    assert set(findings.covered) == {"c1", "c2", "c3", "c4"}


def test_criteria_coverage_flags_a_genuine_gap():
    extra = _B2_CRITERIA + [{
        "id": "c5", "tier": "behavior",
        "text": "the tool prints its version number when given a --version flag",
        "check": "running with --version exits printing a semantic version string",
    }]
    findings = oc.criteria_coverage_findings(_ORACLE.read_text(encoding="utf-8"), extra)
    assert oc.FLAG_UNCOVERED_CRITERIA in findings.flags
    assert "c5" in findings.uncovered
    assert set(findings.covered) == {"c1", "c2", "c3", "c4"}


def test_criteria_coverage_ignores_non_test_tiers():
    # A visual/human criterion is outside TEST_TIERS (mirrors
    # shared.fleet.acceptance.AcceptanceSpec.human) — never counted covered
    # or uncovered, so an oracle with zero test-tier criteria reads clean.
    findings = oc.criteria_coverage_findings(
        "def test_x():\n    assert 1 == 1\n",
        [{"id": "c1", "tier": "visual", "text": "the app looks professional and modern"}],
    )
    assert findings.flags == ()
    assert findings.covered == () and findings.uncovered == ()


def test_criteria_coverage_syntax_error_is_a_measured_finding():
    findings = oc.criteria_coverage_findings("def test_(:\n", _B2_CRITERIA)
    assert oc.FLAG_SYNTAX_ERROR in findings.flags


def test_malformed_contract_case_fails_closed(tmp_path: Path):
    bad = tmp_path / "golden.jsonl"
    bad.write_text(
        '{"id": "oq-bad-002", "description": "contract case missing declared_exports", '
        '"mode": "offline", "category": "contract", '
        '"oracle_inline": "def test_x():\\n    assert 1\\n", '
        '"expect": {"flags_empty": true}}\n',
        encoding="utf-8",
    )
    with pytest.raises(GoldenDataError, match="declared_exports"):
        run_suite(bad)


def test_malformed_criteria_coverage_case_fails_closed(tmp_path: Path):
    bad = tmp_path / "golden.jsonl"
    bad.write_text(
        '{"id": "oq-bad-003", "description": "criteria-coverage case missing criteria", '
        '"mode": "offline", "category": "criteria-coverage", '
        '"oracle_inline": "def test_x():\\n    assert 1\\n", '
        '"expect": {"flags_empty": true}}\n',
        encoding="utf-8",
    )
    with pytest.raises(GoldenDataError, match="criteria"):
        run_suite(bad)
