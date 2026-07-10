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

_REFERENCE = _FIXTURES_DIR / "b2_reference"
_ORACLE = (_FIXTURES_DIR / "b2_job_oracle.py")


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
