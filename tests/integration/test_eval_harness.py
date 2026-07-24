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

    # -- #1000: the hardware tier must have teeth ---------------------------
    # A case BASELINED as skipped_hardware that later RUNS and FAILS was
    # absorbed into known_failures by a branch fall-through, so the run exited
    # 0.  That is how the 2026-07-07 ceremony reported "0 regressions" while
    # 3 of 4 injection-resistance cases were failing.  These lock both
    # directions: the failure is caught, and the neighbouring semantics that
    # were correct are provably unchanged.

    @pytest.mark.parametrize("status", [CaseStatus.FAIL, CaseStatus.ERROR])
    def test_unbaselined_hardware_case_that_fails_is_a_regression(
        self, status: CaseStatus
    ) -> None:
        base = {"cases": {"case-1": "skipped_hardware"}}
        comparison = compare(self._report_with(status), base)
        assert comparison.has_regressions, (
            "a case the baseline never measured cannot fail silently"
        )
        assert any("unbaselined failure" in r for r in comparison.regressions)
        # It must NOT be laundered into known_failures — that list means
        # "a deficiency somebody consciously recorded", and nobody did.
        assert comparison.known_failures == []

    def test_unbaselined_hardware_case_that_passes_is_not_a_regression(
        self,
    ) -> None:
        # The first successful measurement of a never-measured case is good
        # news, not a regression. Guards against over-correcting #1000 into
        # failing every newly-run hardware case.
        base = {"cases": {"case-1": "skipped_hardware"}}
        comparison = compare(self._report_with(CaseStatus.PASS), base)
        assert not comparison.has_regressions
        assert comparison.known_failures == []

    def test_recorded_known_failure_still_is_not_a_regression(self) -> None:
        # The #1000 fix must not swallow the genuine known-failure path: a
        # baseline that actually RECORDED a fail is a tracked deficiency.
        base = {"cases": {"case-1": "fail"}}
        comparison = compare(self._report_with(CaseStatus.ERROR), base)
        assert not comparison.has_regressions
        assert comparison.known_failures == ["case-1"]

    @pytest.mark.parametrize(
        "bogus",
        [
            "skipped",              # a plausible-looking wrong status
            "SKIPPED_HARDWARE",     # right word, wrong case
            "skipped_hardware ",    # trailing whitespace from a hand-edit
            "passed",               # one-char typo of the PASS status
            "",                     # empty string
            "skipped_missing_model",  # a status that does not exist yet
        ],
    )
    def test_noncanonical_baseline_status_cannot_absorb_a_failure(
        self, bogus: str
    ) -> None:
        # #1000 is an ALLOWLIST: only a recorded fail/error earns silence.
        # Baselines are hand-editable JSON, and `load_baseline` validates
        # only that `cases` is a dict — never the status values. Under the
        # old "known shapes, else benign" form every string below silently
        # absorbed a real failure. Note "passed" in particular: a one-char
        # typo of the PASS status also disabled the primary
        # baseline-pass -> fail regression branch.
        base = {"cases": {"case-1": bogus}}
        comparison = compare(self._report_with(CaseStatus.FAIL), base)
        assert comparison.has_regressions, (
            f"baseline status {bogus!r} absorbed a real failure"
        )
        assert comparison.known_failures == []

    # -- #1010: compare() validates its own baseline values ------------------
    # #1000 rejects malformed baselines at load time, which protects every
    # caller that reads a committed FILE.  ``compare`` itself takes a plain
    # dict and used to die with an unhashable-type TypeError on a non-string
    # value — a crash held closed only by the absence of a caller that
    # bypasses ``load_baseline``.  These drive ``compare`` DIRECTLY with each
    # malformed shape: a failure is never absorbed, nothing raises, and a
    # well-formed baseline's result is provably unchanged.

    @pytest.mark.parametrize(
        "bad_value",
        [
            ["fail"],            # the ticket's confirmed crash (unhashable)
            {"status": "fail"},  # unhashable mapping
            3,                   # number
            None,                # JSON null — present, NOT absent
            True,                # bool
        ],
    )
    def test_non_string_baseline_value_cannot_absorb_a_failure(
        self, bad_value: object
    ) -> None:
        base = {"cases": {"case-1": bad_value}}
        comparison = compare(self._report_with(CaseStatus.FAIL), base)
        assert comparison.has_regressions, (
            f"baseline value {bad_value!r} absorbed a real failure"
        )
        assert any(
            "malformed baseline value" in r for r in comparison.regressions
        )
        # Never laundered into known_failures — that list means "a deficiency
        # somebody consciously recorded", and a broken value records nothing.
        assert comparison.known_failures == []

    def test_present_and_null_is_not_reported_as_absent(self) -> None:
        # ``dict.get``'s None default used to conflate {"case-1": null}
        # (present, malformed) with an id absent from the baseline entirely.
        # Both are regressions, but they earn different messages — a null is
        # a broken recording to repair, not a new case to baseline.
        base = {"cases": {"case-1": None}}
        comparison = compare(self._report_with(CaseStatus.FAIL), base)
        assert any(
            "malformed baseline value" in r for r in comparison.regressions
        )
        assert not any(
            "new failing case" in r for r in comparison.regressions
        )

    def test_non_string_baseline_value_with_passing_case_is_inert(self) -> None:
        # A baseline value can only matter through the known-failure or
        # improvement branches; a passing case must neither crash on a
        # malformed one nor mint an "improvement" from garbage.  (Rejecting
        # the malformed FILE is load_baseline's job, exit 2.)
        base = {"cases": {"case-1": ["fail"]}}
        comparison = compare(self._report_with(CaseStatus.PASS), base)
        assert not comparison.has_regressions
        assert comparison.improvements == []
        assert comparison.known_failures == []

    @pytest.mark.parametrize(
        "bad_baseline",
        [
            {"cases": ["case-1"]},       # list where the object should be
            {"cases": "case-1: pass"},   # string
            {"cases": 3},                # number
            {"cases": None},             # JSON null
            ["cases"],                   # the whole baseline is not an object
        ],
    )
    def test_structurally_wrong_cases_block_is_a_regression_not_a_crash(
        self, bad_baseline: object
    ) -> None:
        # Strongest direction: even an all-green run must not report clean
        # against a baseline that cannot be read — silence there is
        # indistinguishable from "compared and found clean".  Before #1010
        # these shapes raised TypeError/ValueError out of dict().
        comparison = compare(self._report_with(CaseStatus.PASS), bad_baseline)
        assert comparison.has_regressions
        assert any(
            "malformed baseline" in r for r in comparison.regressions
        )
        assert comparison.known_failures == []

    def test_well_formed_baseline_result_is_unchanged(self) -> None:
        # The #1010 validation must be invisible to a well-formed baseline:
        # one composite run exercising every branch — known-fail,
        # improvement, pass->fail regression, new failing case, vanished
        # case, hardware skips on both sides — produces exactly the
        # pre-#1010 comparison.
        base = {
            "cases": {
                "known-1": "fail",
                "improved-2": "error",
                "regressed-3": "pass",
                "steady-4": "pass",
                "vanished-5": "pass",
                "hw-6": "skipped_hardware",
            }
        }
        report = SuiteReport(suite="probe")
        for case_id, status in (
            ("known-1", CaseStatus.FAIL),
            ("improved-2", CaseStatus.PASS),
            ("regressed-3", CaseStatus.ERROR),
            ("steady-4", CaseStatus.PASS),
            ("new-7", CaseStatus.FAIL),
            ("hw-8", CaseStatus.SKIPPED_HARDWARE),
        ):
            report.results.append(
                CaseResult(case_id=case_id, status=status, detail="probe")
            )
        comparison = compare(report, base)
        assert comparison.known_failures == ["known-1"]
        assert comparison.improvements == ["improved-2"]
        assert len(comparison.regressions) == 3
        assert any(
            "regressed vs baseline: regressed-3" in r
            for r in comparison.regressions
        )
        assert any(
            "new failing case not in baseline: new-7" in r
            for r in comparison.regressions
        )
        assert any(
            "baselined case missing from run: vanished-5" in r
            for r in comparison.regressions
        )


# ---------------------------------------------------------------------------
# C2. tool_call status — an honest recording, never silence by default (#1006)
# ---------------------------------------------------------------------------
# Live-caught 2026-07-21: the first hardware answer-quality ceremony scored two
# cases as FAIL on an empty string because the model (correctly) answered with
# a tool call the one-shot harness cannot execute — production runs the tool
# loop and shows a real answer.  These lock the new status end to end:
# detection at the suite seam, every baseline transition loud except the
# recorded steady state, and the allowlist property extended (a tool_call
# baseline can never absorb a real failure).


class TestToolCallStatus:
    @staticmethod
    def _report_with(status: CaseStatus, detail: str = "probe") -> SuiteReport:
        report = SuiteReport(suite="probe")
        report.results.append(
            CaseResult(case_id="case-1", status=status, detail=detail)
        )
        return report

    # -- baseline transitions ------------------------------------------------

    def test_pass_to_tool_call_is_a_regression(self) -> None:
        base = {"cases": {"case-1": "pass"}}
        comparison = compare(self._report_with(CaseStatus.TOOL_CALL), base)
        assert comparison.has_regressions
        assert any(
            "answers with a tool call" in r for r in comparison.regressions
        )

    def test_recorded_tool_call_steady_state_is_silent_but_listed(self) -> None:
        base = {"cases": {"case-1": "tool_call"}}
        comparison = compare(self._report_with(CaseStatus.TOOL_CALL), base)
        assert not comparison.has_regressions
        assert comparison.known_tool_calls == ["case-1"]

    def test_new_tool_call_case_is_a_regression(self) -> None:
        base = {"cases": {}}
        comparison = compare(self._report_with(CaseStatus.TOOL_CALL), base)
        assert comparison.has_regressions
        assert any(
            "new tool-call case" in r for r in comparison.regressions
        )

    def test_skipped_hardware_to_tool_call_is_a_regression(self) -> None:
        # The 2026-07-21 shape exactly: first measurement of a never-measured
        # case discovers it answers with a tool call.  Loud — the operator
        # records it deliberately; it never inherits skipped-silence.
        base = {"cases": {"case-1": "skipped_hardware"}}
        comparison = compare(self._report_with(CaseStatus.TOOL_CALL), base)
        assert comparison.has_regressions

    def test_tool_call_to_pass_is_an_improvement(self) -> None:
        base = {"cases": {"case-1": "tool_call"}}
        comparison = compare(self._report_with(CaseStatus.PASS), base)
        assert not comparison.has_regressions
        assert comparison.improvements == ["case-1"]

    def test_tool_call_baseline_cannot_absorb_a_real_failure(self) -> None:
        # The #1000 allowlist property, extended to the new member: only a
        # RECORDED fail/error earns known_failures.
        base = {"cases": {"case-1": "tool_call"}}
        comparison = compare(self._report_with(CaseStatus.FAIL), base)
        assert comparison.has_regressions
        assert comparison.known_failures == []

    def test_baselined_tool_call_missing_from_run_is_a_regression(self) -> None:
        # Only skipped_hardware is exempt from the vanished-case check — a
        # recorded tool-call case that disappears means the golden set shrank
        # without a conscious refresh.
        base = {"cases": {"case-1": "tool_call"}}
        comparison = compare(SuiteReport(suite="probe"), base)
        assert comparison.has_regressions
        assert any("missing from run" in r for r in comparison.regressions)

    # -- detection at the suite seam ----------------------------------------

    @staticmethod
    def _golden_file(tmp_path: Path) -> Path:
        from evals.suites.answer_quality import SUITE_NAME  # noqa: F401

        path = tmp_path / "answer_quality.jsonl"
        case = {
            "id": "aq-probe-01",
            "description": "probe",
            "category": "factual",
            "mode": "model",
            "prompt": "what is 2+2?",
            "checks": {"must_contain": ["4"]},
        }
        path.write_text(json.dumps(case) + "\n", encoding="utf-8")
        return path

    def _run_with_generator(self, tmp_path: Path, raw: str) -> SuiteReport:
        from evals.suites.answer_quality import run_suite

        return run_suite(
            golden_file=self._golden_file(tmp_path),
            include_hardware=True,
            hardware_generator=lambda composed: raw,
        )

    def test_tool_call_only_generation_records_tool_call_status(
        self, tmp_path: Path
    ) -> None:
        raw = '<tool_call>{"name": "calculate", "arguments": {}}</tool_call>'
        report = self._run_with_generator(tmp_path, raw)
        (result,) = report.results
        assert result.status is CaseStatus.TOOL_CALL
        # Evidence attached: the report must show WHAT the model tried to
        # call, or the status is just a fancier silence.
        assert "calculate" in str(result.actual)

    def test_all_think_empty_generation_stays_a_fail(self, tmp_path: Path) -> None:
        # The principled line: production would display the same emptiness,
        # so an all-<think> answer is a REAL failure, never tool_call.
        raw = "<think>working it out but never answering</think>"
        report = self._run_with_generator(tmp_path, raw)
        (result,) = report.results
        assert result.status is CaseStatus.FAIL

    def test_normal_answer_path_is_unchanged(self, tmp_path: Path) -> None:
        report = self._run_with_generator(tmp_path, "2+2 is 4.")
        (result,) = report.results
        assert result.status is CaseStatus.PASS

    def test_tool_call_with_visible_text_is_scored_normally(
        self, tmp_path: Path
    ) -> None:
        # A tool call ALONGSIDE a visible answer is scoreable — the user sees
        # the text.  Detection fires only on hidden-blocks-only generations.
        raw = '<tool_call>{"name": "x"}</tool_call>The answer is 4.'
        report = self._run_with_generator(tmp_path, raw)
        (result,) = report.results
        assert result.status is CaseStatus.PASS

    # -- aggregates + baseline round-trip ------------------------------------

    def test_tool_call_excluded_from_pass_rate_but_counted(
        self, tmp_path: Path
    ) -> None:
        raw = '<tool_call>{"name": "calculate"}</tool_call>'
        report = self._run_with_generator(tmp_path, raw)
        agg = report.aggregates()
        assert agg["tool_calls"] == 1
        assert agg["evaluated"] == 0
        assert agg["pass_rate"] == 0.0

    def test_tool_call_status_survives_baseline_round_trip(
        self, tmp_path: Path
    ) -> None:
        report = self._report_with(CaseStatus.TOOL_CALL)
        path = baseline_mod.write_baseline(report, tmp_path)
        loaded = load_baseline("probe", tmp_path)
        assert loaded["cases"]["case-1"] == "tool_call"
        assert path.exists()

    def test_unclosed_tool_call_mention_stays_a_fail(self, tmp_path: Path) -> None:
        # Review finding on the first cut: production's parser requires a
        # CLOSED <tool_call>…</tool_call> pair; an unclosed marker MENTION
        # runs no tool — the user sees emptiness, so the eval must score a
        # real FAIL, never launder it into tool_call (the lenient-direction
        # error this status exists to eliminate).
        raw = "<think>maybe emit a <tool_call block here</think>"
        report = self._run_with_generator(tmp_path, raw)
        (result,) = report.results
        assert result.status is CaseStatus.FAIL

    def test_offline_fixture_tool_call_only_records_tool_call(
        self, tmp_path: Path
    ) -> None:
        # The offline path must behave identically to the model path — same
        # helper, locked here so the equivalence is pinned, not incidental.
        from evals.suites.answer_quality import run_suite

        path = tmp_path / "answer_quality.jsonl"
        case = {
            "id": "aq-probe-02",
            "description": "probe",
            "category": "factual",
            "mode": "offline",
            "fixture_response": '<tool_call>{"name": "x"}</tool_call>',
            "checks": {"must_contain": ["4"]},
        }
        path.write_text(json.dumps(case) + "\n", encoding="utf-8")
        report = run_suite(golden_file=path, include_hardware=False)
        (result,) = report.results
        assert result.status is CaseStatus.TOOL_CALL

    def test_detection_tag_matches_the_resolved_strip_binding(self) -> None:
        # Drift lock against the RESOLVED binding, not the hard-coded
        # fallback: the production strip resolves its tags from the model
        # manifest (#834), and a model swap edits the MANIFEST while the
        # compiled default stays byte-identical forever.  Detection depends
        # on the resolved strip removing closed tool-call blocks, so the tag
        # must be present in what the manifest actually resolves to today.
        from evals.suites.answer_quality import _TOOL_CALL_TAG
        from shared.fleet.model_profiles import (
            AO_BRAIN_MODEL_ID,
            resolve_hidden_block_tags,
        )

        assert _TOOL_CALL_TAG in resolve_hidden_block_tags(AO_BRAIN_MODEL_ID)


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

    @pytest.mark.parametrize(
        "bad_value", ['["fail"]', '{"status": "fail"}', "null", "3"]
    )
    def test_non_string_case_status_is_a_harness_error(
        self, tmp_path: Path, bad_value: str
    ) -> None:
        # #1000: a malformed baseline is a HARNESS error (exit 2), never a
        # regression (exit 1) — the codes mean different things. `compare`
        # tests baseline values for set membership, which raises TypeError on
        # an unhashable value; unhandled, the interpreter exits 1 and a
        # malformed baseline arrives wearing a regression's exit code.
        # Rejecting non-string statuses at load time keeps exit 2 exit 2.
        (tmp_path / "governance.json").write_text(
            '{"cases": {"case-1": ' + bad_value + "}}", encoding="utf-8"
        )
        with pytest.raises(BaselineError, match="non-string case statuses"):
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
