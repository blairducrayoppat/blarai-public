"""
Eval Harness — Standing-Gate Integration Tests (#717)
======================================================
Locks the model-quality eval harness (evals/) into the standing gate:

  A. Golden-set integrity — files load, validate, and meet minimum sizes.
  B. Deterministic suites green — every CI-safe golden case passes against
     the CURRENT code (a rule/parser change that flips a verdict fails here
     first, before the baseline machinery is even consulted).
  C. Baseline comparison — the committed baselines compare clean (no
     regressions) and the comparison logic has teeth (regressed cases, new
     failing cases, and vanished cases are all flagged; known-fails and
     improvements are not regressions).
  D. Runner exit-code semantics — 0 clean / 1 regression / 2 harness error.
  E. Harness fail-closed guards — loader rejects malformed golden data; the
     dispatch leg refuses to execute non-SAFE tools.
  F. Layer-3 mirror drift tripwire — the governance suite mirrors the AO's
     inline Layer-3 predicate; if the inline predicate's shape changes,
     this test fails loudly and names the mirror to update.
  G. Hardware tier (@hardware, deselected from the standing gate) — the
     model-in-the-loop PA cases on the real Arc 140V.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from evals import baseline as baseline_mod
from evals import run as run_mod
from evals.baseline import BaselineError, compare, load_baseline
from evals.loader import GOLDEN_DIR, GoldenDataError, load_golden
from evals.suites import SUITE_NAMES, get_runner
from evals.suites.governance import layer3_lock_decision
from evals.types import CaseResult, CaseStatus, SuiteReport

_DETERMINISTIC_SUITES: tuple[str, ...] = SUITE_NAMES


# ---------------------------------------------------------------------------
# A. Golden-set integrity
# ---------------------------------------------------------------------------


class TestGoldenIntegrity:
    @pytest.mark.parametrize("suite", _DETERMINISTIC_SUITES)
    def test_golden_file_loads(self, suite: str) -> None:
        cases = load_golden(GOLDEN_DIR / f"{suite}.jsonl")
        assert len(cases) >= 20, f"{suite}: golden set too small ({len(cases)})"

    def test_pa_golden_has_both_modes(self) -> None:
        cases = load_golden(GOLDEN_DIR / "pa_classification.jsonl")
        modes = {c["mode"] for c in cases}
        assert modes == {"deterministic", "model"}
        model_cases = [c for c in cases if c["mode"] == "model"]
        assert len(model_cases) >= 5, "need a meaningful model-in-loop slice"

    def test_tool_calling_golden_has_adversarial_slice(self) -> None:
        cases = load_golden(GOLDEN_DIR / "tool_calling.jsonl")
        adversarial = [c for c in cases if c["category"] == "adversarial"]
        assert len(adversarial) >= 5

    def test_tool_calling_golden_is_format_tagged(self) -> None:
        """Every case names its tool-call format so the Qwen3-native JSON
        migration can filter/re-baseline by tag (format-agnostic design)."""
        cases = load_golden(GOLDEN_DIR / "tool_calling.jsonl")
        assert all(isinstance(c.get("format"), str) and c["format"] for c in cases)

    def test_governance_golden_covers_all_kinds(self) -> None:
        cases = load_golden(GOLDEN_DIR / "governance.jsonl")
        kinds = {c["kind"] for c in cases}
        assert kinds == {
            "risk_tier",
            "pa_prefilter",
            "tool_dispatch_adjudication",
            "escalation_consent_default",
            "layer3_lock",
            "leakage_feed",
            "egress_consent",
            "generation_consent",
        }


# ---------------------------------------------------------------------------
# B. Deterministic suites green against current code
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def suite_reports() -> dict[str, SuiteReport]:
    """Run every suite once (deterministic mode) and share the reports."""
    return {name: get_runner(name)() for name in _DETERMINISTIC_SUITES}


class TestDeterministicSuitesGreen:
    @pytest.mark.parametrize("suite", _DETERMINISTIC_SUITES)
    def test_no_failures_or_errors(
        self, suite: str, suite_reports: dict[str, SuiteReport]
    ) -> None:
        report = suite_reports[suite]
        failing = [
            r.to_dict()
            for r in report.results
            if r.status in (CaseStatus.FAIL, CaseStatus.ERROR)
        ]
        assert not failing, f"{suite}: failing golden cases: {failing}"

    def test_pa_model_cases_are_skipped_without_hardware(
        self, suite_reports: dict[str, SuiteReport]
    ) -> None:
        report = suite_reports["pa_classification"]
        skipped = {
            r.case_id
            for r in report.results
            if r.status is CaseStatus.SKIPPED_HARDWARE
        }
        golden = load_golden(GOLDEN_DIR / "pa_classification.jsonl")
        model_ids = {str(c["id"]) for c in golden if c["mode"] == "model"}
        assert skipped == model_ids, (
            "every model-mode case (and only those) must be hardware-skipped "
            "in a default run"
        )

    @pytest.mark.parametrize("suite", ("tool_calling", "governance"))
    def test_ci_suites_evaluate_everything(
        self, suite: str, suite_reports: dict[str, SuiteReport]
    ) -> None:
        report = suite_reports[suite]
        assert report.skipped_hardware == 0
        assert report.evaluated == report.total


# ---------------------------------------------------------------------------
# C. Baseline comparison — clean, and with teeth
# ---------------------------------------------------------------------------


class TestBaselineComparison:
    @pytest.mark.parametrize("suite", _DETERMINISTIC_SUITES)
    def test_committed_baseline_compares_clean(
        self, suite: str, suite_reports: dict[str, SuiteReport]
    ) -> None:
        base = load_baseline(suite)
        comparison = compare(suite_reports[suite], base)
        assert not comparison.has_regressions, comparison.regressions

    @staticmethod
    def _report_with(status: CaseStatus) -> SuiteReport:
        report = SuiteReport(suite="probe")
        report.results.append(
            CaseResult(case_id="case-1", status=status, detail="probe")
        )
        return report

    def test_regressed_case_is_flagged(self) -> None:
        base = {"cases": {"case-1": "pass"}}
        comparison = compare(self._report_with(CaseStatus.FAIL), base)
        assert comparison.has_regressions
        assert any("regressed" in r for r in comparison.regressions)

    def test_error_counts_as_regression(self) -> None:
        base = {"cases": {"case-1": "pass"}}
        comparison = compare(self._report_with(CaseStatus.ERROR), base)
        assert comparison.has_regressions

    def test_new_failing_case_is_flagged(self) -> None:
        base = {"cases": {}}
        comparison = compare(self._report_with(CaseStatus.FAIL), base)
        assert comparison.has_regressions
        assert any("new failing case" in r for r in comparison.regressions)

    def test_vanished_baselined_case_is_flagged(self) -> None:
        base = {"cases": {"case-1": "pass", "vanished-9": "pass"}}
        comparison = compare(self._report_with(CaseStatus.PASS), base)
        assert comparison.has_regressions
        assert any("missing from run" in r for r in comparison.regressions)

    def test_known_failure_is_not_a_regression(self) -> None:
        base = {"cases": {"case-1": "fail"}}
        comparison = compare(self._report_with(CaseStatus.FAIL), base)
        assert not comparison.has_regressions
        assert comparison.known_failures == ["case-1"]

    def test_improvement_is_not_a_regression(self) -> None:
        base = {"cases": {"case-1": "fail"}}
        comparison = compare(self._report_with(CaseStatus.PASS), base)
        assert not comparison.has_regressions
        assert comparison.improvements == ["case-1"]

    def test_hardware_skips_are_never_compared(self) -> None:
        # Baseline says pass; the run skips (no hardware). Not a regression,
        # and a baselined hardware-skip absent from the run is ignored too.
        base = {"cases": {"case-1": "pass", "hw-2": "skipped_hardware"}}
        comparison = compare(
            self._report_with(CaseStatus.SKIPPED_HARDWARE), base
        )
        assert not comparison.has_regressions


# ---------------------------------------------------------------------------
# D. Runner exit-code semantics
# ---------------------------------------------------------------------------


class TestRunnerExitCodes:
    def test_clean_run_exits_zero(self) -> None:
        assert run_mod.main(["--suite", "governance"]) == run_mod.EXIT_OK

    def test_all_suites_exit_zero(self) -> None:
        assert run_mod.main(["--suite", "all"]) == run_mod.EXIT_OK

    def test_regression_exits_one(self, tmp_path: Path) -> None:
        # Doctor a baseline that claims a nonexistent case passed — the run
        # cannot reproduce it, which must be flagged as a regression.
        base = load_baseline("governance")
        base["cases"]["ghost-case-999"] = "pass"
        (tmp_path / "governance.json").write_text(
            json.dumps(base), encoding="utf-8"
        )
        code = run_mod.main(
            ["--suite", "governance", "--baseline-dir", str(tmp_path)]
        )
        assert code == run_mod.EXIT_REGRESSION

    def test_missing_baseline_exits_two(self, tmp_path: Path) -> None:
        code = run_mod.main(
            ["--suite", "governance", "--baseline-dir", str(tmp_path / "nope")]
        )
        assert code == run_mod.EXIT_HARNESS_ERROR

    def test_malformed_baseline_exits_two(self, tmp_path: Path) -> None:
        (tmp_path / "governance.json").write_text("not json{", encoding="utf-8")
        code = run_mod.main(
            ["--suite", "governance", "--baseline-dir", str(tmp_path)]
        )
        assert code == run_mod.EXIT_HARNESS_ERROR

    def test_report_file_is_written(self, tmp_path: Path) -> None:
        report_path = tmp_path / "report.json"
        code = run_mod.main(
            ["--suite", "governance", "--report", str(report_path)]
        )
        assert code == run_mod.EXIT_OK
        payload = json.loads(report_path.read_text(encoding="utf-8"))
        assert "governance" in payload["suites"]
        assert payload["suites"]["governance"]["aggregates"]["failed"] == 0

    def test_write_baseline_roundtrip(self, tmp_path: Path) -> None:
        code = run_mod.main(
            [
                "--suite",
                "governance",
                "--baseline-dir",
                str(tmp_path),
                "--write-baseline",
            ]
        )
        assert code == run_mod.EXIT_OK
        code = run_mod.main(
            ["--suite", "governance", "--baseline-dir", str(tmp_path)]
        )
        assert code == run_mod.EXIT_OK


# ---------------------------------------------------------------------------
# E. Harness fail-closed guards
# ---------------------------------------------------------------------------


class TestHarnessFailClosed:
    def test_loader_rejects_duplicate_ids(self, tmp_path: Path) -> None:
        p = tmp_path / "dup.jsonl"
        p.write_text(
            '{"id": "x", "description": "a"}\n{"id": "x", "description": "b"}\n',
            encoding="utf-8",
        )
        with pytest.raises(GoldenDataError, match="duplicate"):
            load_golden(p)

    def test_loader_rejects_missing_required_field(self, tmp_path: Path) -> None:
        p = tmp_path / "bad.jsonl"
        p.write_text('{"id": "x"}\n', encoding="utf-8")
        with pytest.raises(GoldenDataError, match="description"):
            load_golden(p)

    def test_loader_rejects_empty_file(self, tmp_path: Path) -> None:
        p = tmp_path / "empty.jsonl"
        p.write_text("\n\n", encoding="utf-8")
        with pytest.raises(GoldenDataError, match="empty"):
            load_golden(p)

    def test_loader_rejects_invalid_json_line(self, tmp_path: Path) -> None:
        p = tmp_path / "broken.jsonl"
        p.write_text('{"id": "x", "description": "a"}\n{oops\n', encoding="utf-8")
        with pytest.raises(GoldenDataError, match="invalid JSON"):
            load_golden(p)

    def test_dispatch_refuses_non_safe_tool(self, tmp_path: Path) -> None:
        """A golden case asking to EXECUTE a GUARDED tool is a harness error,
        not an execution (fail-closed guard)."""
        from evals.suites import tool_calling as tc

        p = tmp_path / "tool_calling.jsonl"
        case = {
            "id": "guard-probe-001",
            "description": "must be refused by the SAFE-only dispatch guard",
            "format": "qwen3_json",
            "category": "dispatch",
            "model_output": (
                '<tool_call>{"name": "generate_image", '
                '"arguments": {"prompt": "a cat"}}</tool_call>'
            ),
            "expect_parse": {
                "name": "generate_image",
                "args": '{"prompt":"a cat"}',
            },
            "dispatch": {"expect_kind": "contains", "expect_value": "anything"},
        }
        p.write_text(json.dumps(case) + "\n", encoding="utf-8")
        with pytest.raises(GoldenDataError, match="non-SAFE"):
            tc.run_suite(p)

    def test_malformed_baseline_raises(self, tmp_path: Path) -> None:
        (tmp_path / "governance.json").write_text(
            '{"no_cases_block": true}', encoding="utf-8"
        )
        with pytest.raises(BaselineError, match="cases"):
            load_baseline("governance", tmp_path)

    def test_escalation_consent_case_restores_verifier_state(self) -> None:
        """The governance suite's hermetic consent probe must not leak
        verifier state (module-global) into other tests."""
        from shared.security.escalation_consent import active_verifier

        before = active_verifier()
        get_runner("governance")()
        assert active_verifier() is before


# ---------------------------------------------------------------------------
# F. Layer-3 mirror drift tripwire
# ---------------------------------------------------------------------------


class TestLayer3MirrorAlignment:
    """The governance suite mirrors the AO's inline Layer-3 predicate
    (evals/suites/governance.py:layer3_lock_decision). The predicate itself
    lives inline in the AO tool loop and is not importable; these tests pin
    (a) the mirror's truth table against ADR-023 Amendment 1 and (b) the
    inline predicate's load-bearing fragments in the entrypoint source, so
    a shape change in either place fails loudly and names the other."""

    def test_mirror_truth_table(self) -> None:
        # SAFE never locked; DANGEROUS locked with NO override; flag off or no
        # untrusted content -> never locked. ADR-023 Amendment 4: the three current
        # GUARDED tools each have a DEDICATED consent instead of the /trust lock, so
        # NONE of them Layer-3-locks — search_knowledge + generate_image are
        # lock-exempt (rungs 1/2, bounded danger), web_search is egress-exempt
        # (rung 3, Hello-fingerprint-gated). The still-locking case is a
        # DANGEROUS/unknown tool.
        cases: list[tuple[bool, bool, str, bool, bool]] = [
            (True, True, "calculate", False, False),          # SAFE never locks
            (True, True, "search_knowledge", False, False),   # rung-1 lock-exempt
            (True, True, "generate_image", False, False),     # rung-2 lock-exempt (shim)
            (True, True, "generate_image", True, False),      # exempt regardless of /trust
            (True, True, "web_search", False, False),         # rung-3 egress-exempt
            (True, True, "totally_unknown", True, True),      # DANGEROUS: no override
            (True, True, "totally_unknown", False, True),     # DANGEROUS locks
            (True, False, "totally_unknown", False, False),   # no untrusted -> no lock
            (False, True, "totally_unknown", False, False),   # flag off -> no lock
        ]
        for flag, untrusted, tool, trust, expected in cases:
            assert (
                layer3_lock_decision(
                    block_tools_on_untrusted_content=flag,
                    has_untrusted_content=untrusted,
                    tool_name=tool,
                    trusted_for_tools=trust,
                )
                is expected
            ), (flag, untrusted, tool, trust)

    def test_inline_predicate_fragments_still_present(self) -> None:
        entrypoint_path = (
            Path(__file__).resolve().parents[2]
            / "services"
            / "assistant_orchestrator"
            / "src"
            / "entrypoint.py"
        )
        source = entrypoint_path.read_text(encoding="utf-8")
        fragments = (
            "resolved.block_tools_on_untrusted_content",
            "context_manager.has_untrusted_content(session_id)",
            "_tool_tier != tools.RiskTier.SAFE",
            "_tool_tier == tools.RiskTier.GUARDED",
            "context_manager.has_trusted_documents_for_tools(session_id)",
        )
        missing = [f for f in fragments if f not in source]
        assert not missing, (
            "The AO's inline Layer-3 predicate changed shape "
            f"(missing fragments: {missing}). Update the mirror in "
            "evals/suites/governance.py:layer3_lock_decision AND its golden "
            "cases (evals/golden/governance.jsonl) in the same change."
        )


# ---------------------------------------------------------------------------
# G. Hardware tier — model-in-the-loop PA classification (Arc 140V)
# ---------------------------------------------------------------------------


@pytest.mark.hardware
@pytest.mark.slow
class TestModelInLoopPAClassification:
    """Runs the pa_classification model-mode golden cases through the REAL
    Qwen3-14B classifier on the Arc 140V (the measurable form of ISS-3).

    Deselected from the standing gate; the orchestrator runs hardware tiers
    serially after merge. Quality misses are DATA (recorded in the evidence
    artifact and comparable against a hardware baseline), not test failures;
    only harness ERRORs fail this test.
    """

    def test_model_cases_run_and_produce_evidence(self) -> None:
        try:
            import openvino_genai  # noqa: F401
        except ImportError:
            pytest.skip("OpenVINO GenAI not available")

        from evals.suites.pa_classification import default_model_dir, run_suite

        model_dir = default_model_dir()
        if not model_dir.exists():
            pytest.skip(f"PA model not present at {model_dir}")

        report = run_suite(include_hardware=True)
        assert report.skipped_hardware == 0
        errors = [
            r.to_dict() for r in report.results if r.status is CaseStatus.ERROR
        ]
        assert not errors, f"harness errors on hardware run: {errors}"

        # Evidence artifact (community-grade capture discipline).
        evidence_dir = (
            Path(__file__).resolve().parents[2] / "phase2_gates" / "evidence"
        )
        evidence_dir.mkdir(parents=True, exist_ok=True)
        sha = baseline_mod._resolve_git_sha()
        artifact = evidence_dir / f"eval_pa_classification_model_{sha}.json"
        artifact.write_text(report.to_json() + "\n", encoding="utf-8")
        assert artifact.exists()
