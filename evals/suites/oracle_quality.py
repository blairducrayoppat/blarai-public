"""
Eval Suite — Acceptance-Oracle Quality (#765)
==============================================
Measures the QUALITY of the 14B-written acceptance oracles — the tests that
grade every dispatch — in the two directions an oracle can fail:

  soundness    — a wrong oracle FAILS CORRECT CODE: the case runs an oracle
                 against the frozen known-good reference implementation
                 (evals/fixtures/oracle_quality/) and must come back
                 ``passed``. A failure here is an oracle defect that would
                 have parked a good job and blamed the coder.
  sensitivity  — a weak oracle PASSES BROKEN CODE: the case runs the same
                 oracle against a deliberately broken mutant of the
                 reference and must come back ``failed``. A pass here is
                 the silent direction — the oracle cannot catch the break.

Plus four deterministic layers:
  static             — structural trust findings over the oracle source
                        (real tests, real assertions, no degenerate
                        ``assert True``, no module-level skip) via
                        evals/oracle_checks.py.
  contract           — the #752-F3 class: does the oracle import only
                        first-party symbols the job's declared task
                        contracts (``declared_exports``) actually export?
                        Thin wrapper over the real #821 production check
                        (``shared.fleet.oracle_qa.scan_invented_contracts``).
  criteria-coverage   — does every ``[behavior]``/``[smoke]`` acceptance
                        criterion (``criteria``) map to >=1 test? A
                        self-contained keyword/structure-match heuristic
                        (documented, with a pinned known limitation) — NOT
                        the model-assisted #821 traceability matrix, which
                        needs a live coverage-map call.
  failure-mode        — the executor's outcome VOCABULARY itself is pinned:
                        ``collection-error`` (the #752-F3 plumbing class)
                        must be distinguished from ``failed`` (real
                        assertions) — the same vocabulary #765 Layer 2 adds
                        to live scorecard evidence.

Two case modes (the ``mode`` field):

  offline — the case carries a FIXTURE oracle (``oracle_fixture_file`` under
      evals/fixtures/oracle_quality/, or ``oracle_inline``). HONESTY NOTE:
      offline cases measure the CHECK ENGINE and pin recorded known-good /
      known-bad oracle exemplars — they do NOT measure the live 14B. Only
      ``mode: "model"`` cases on hardware do.

  model — the oracle is GENERATED live via the real production generator
      paths (per-task ``generate_acceptance_oracle`` / the W4 job-level
      generator) for the case's gold goal, then graded through the SAME
      soundness/sensitivity/static/contract/criteria-coverage machinery
      (the dispatcher is category-generic — a future model-mode contract or
      criteria-coverage case needs no engine change, only a golden case).
      Skipped unless ``include_hardware=True``. The real-generator wiring
      lands at the first live 14B slot (#765 sequencing); until then a
      hardware run without an injected ``oracle_generator`` reports ERROR
      honestly rather than faking a measurement.

Golden case schema (evals/golden/oracle_quality.jsonl):
  {"id": "oq-sound-001", "description": "...",
   "category": "static" | "contract" | "criteria-coverage" | "soundness"
             | "sensitivity" | "failure-mode",
   "mode": "offline" | "model",
   "goal_id": "b2",                            # model mode: which gold goal
   "oracle_fixture_file": "b2_job_oracle.py",  # offline: fixture source, or
   "oracle_inline": "...",                     #   inline source (small cases)
   "reference": "b2_reference",                # run categories: impl tree
   "mutations": [{"file": "app/x.py", "append": "..."}],   # sensitivity
   "declared_exports": ["tokenize", "..."],    # contract: union of task
                                                #   contract.exports
   "criteria": [{"id": "c1", "tier": "behavior", "text": "...",
                 "check": "..."}],             # criteria-coverage: the
                                                #   AcceptanceCriterion dicts
   "expect": {"run_status": "passed"}          # or {"flags_include": [...]}
             }                                 # or {"flags_empty": true}
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from evals.loader import GoldenDataError, golden_path, load_golden
from evals.oracle_checks import (
    contract_import_findings,
    criteria_coverage_findings,
    run_oracle_against,
    static_oracle_findings,
)
from evals.types import CaseResult, CaseStatus, SuiteReport

SUITE_NAME: str = "oracle_quality"

_FIXTURES_DIR: Path = Path(__file__).resolve().parents[1] / "fixtures" / "oracle_quality"

_VALID_MODES: frozenset[str] = frozenset({"offline", "model"})
_VALID_CATEGORIES: frozenset[str] = frozenset(
    {"static", "contract", "criteria-coverage", "soundness", "sensitivity", "failure-mode"}
)


def _validate_case(case: dict) -> "str | None":
    """Return a problem description for a malformed golden case, else None."""
    if not case.get("id"):
        return "missing id"
    if case.get("mode") not in _VALID_MODES:
        return f"mode must be one of {sorted(_VALID_MODES)}"
    if case.get("category") not in _VALID_CATEGORIES:
        return f"category must be one of {sorted(_VALID_CATEGORIES)}"
    expect = case.get("expect")
    if not isinstance(expect, dict) or not expect:
        return "expect block is required"
    if case["mode"] == "offline":
        has_source = bool(case.get("oracle_fixture_file")) or bool(case.get("oracle_inline"))
        if not has_source:
            return "offline case needs oracle_fixture_file or oracle_inline"
    else:
        if not case.get("goal_id"):
            return "model case needs goal_id"
    if case["category"] in ("soundness", "sensitivity", "failure-mode") and not case.get("reference"):
        return f"{case['category']} case needs a reference"
    if case["category"] == "sensitivity" and not case.get("mutations"):
        return "sensitivity case needs mutations"
    if case["category"] == "contract" and not case.get("declared_exports"):
        return "contract case needs declared_exports"
    if case["category"] == "criteria-coverage" and not case.get("criteria"):
        return "criteria-coverage case needs criteria"
    return None


def _flags_verdict(flags: "tuple[str, ...]", expect: dict) -> "tuple[bool, str]":
    """Shared flags_empty / flags_include comparison for the three
    flag-based categories (static, contract, criteria-coverage)."""
    if "flags_empty" in expect:
        ok = (len(flags) == 0) is bool(expect["flags_empty"])
        return ok, f"flags={list(flags)}"
    wanted = list(expect.get("flags_include", []))
    ok = all(f in flags for f in wanted)
    return ok, f"wanted {wanted} in flags={list(flags)}"


def _oracle_source(case: dict) -> str:
    """Resolve the case's oracle source text (offline modes)."""
    fixture = case.get("oracle_fixture_file")
    if fixture:
        return (_FIXTURES_DIR / str(fixture)).read_text(encoding="utf-8")
    return str(case["oracle_inline"])


def _evaluate(case: dict, oracle_code: str) -> CaseResult:
    """Grade one oracle source against the case's expectation."""
    case_id = str(case["id"])
    description = str(case.get("description", ""))
    expect: dict = case["expect"]

    category = case["category"]
    if category == "static":
        findings = static_oracle_findings(oracle_code)
        actual: Any = findings.to_dict()
        ok, why = _flags_verdict(findings.flags, expect)
    elif category == "contract":
        c_findings = contract_import_findings(oracle_code, case.get("declared_exports", []))
        actual = c_findings.to_dict()
        ok, why = _flags_verdict(c_findings.flags, expect)
    elif category == "criteria-coverage":
        cov_findings = criteria_coverage_findings(oracle_code, case.get("criteria", []))
        actual = cov_findings.to_dict()
        ok, why = _flags_verdict(cov_findings.flags, expect)
    else:
        reference = _FIXTURES_DIR / str(case["reference"])
        result = run_oracle_against(
            reference, oracle_code, mutations=case.get("mutations", ())
        )
        actual = {"run_status": result.status, "detail": result.detail}
        ok = result.status == str(expect.get("run_status"))
        why = f"run_status={result.status} ({result.detail})"

    if ok:
        return CaseResult(case_id=case_id, status=CaseStatus.PASS,
                          description=description, expected=expect, actual=actual)
    return CaseResult(case_id=case_id, status=CaseStatus.FAIL,
                      description=description, expected=expect, actual=actual,
                      detail=why)


def run_suite(
    golden_file: Path | None = None,
    *,
    include_hardware: bool = False,
    oracle_generator: "Callable[[str], str] | None" = None,
) -> SuiteReport:
    """Run the oracle-quality suite.

    Args:
        golden_file: Override golden path (defaults to
            evals/golden/oracle_quality.jsonl).
        include_hardware: When True, model-mode cases are attempted (they
            need the Qwen3-14B on the Arc 140V). NEVER set in CI.
        oracle_generator: Injectable generator for model-mode cases — takes
            the case's ``goal_id``, returns the generated oracle SOURCE.
            The real-generator wiring is the #765 live-slot step; until it
            lands, hardware runs without an injected generator report ERROR
            honestly (never a faked measurement).
    """
    path = golden_file or golden_path(SUITE_NAME)
    cases = load_golden(path)

    report = SuiteReport(suite=SUITE_NAME)
    for case in cases:
        problem = _validate_case(case)
        if problem is not None:
            raise GoldenDataError(f"{path.name} case {case.get('id')}: {problem}")

        case_id = str(case["id"])
        description = str(case.get("description", ""))

        if case["mode"] == "offline":
            try:
                report.results.append(_evaluate(case, _oracle_source(case)))
            except Exception as exc:  # noqa: BLE001 — scoring must not abort the run
                report.results.append(CaseResult(
                    case_id=case_id, status=CaseStatus.ERROR,
                    description=description, detail=f"harness error: {exc}"))
            continue

        # mode == "model"
        if not include_hardware:
            report.results.append(CaseResult(
                case_id=case_id, status=CaseStatus.SKIPPED_HARDWARE,
                description=description, expected=case["expect"],
                detail="model-in-the-loop case; requires --include-hardware on the Arc 140V"))
            continue

        if oracle_generator is None:
            report.results.append(CaseResult(
                case_id=case_id, status=CaseStatus.ERROR,
                description=description, expected=case["expect"],
                detail=("real oracle-generator wiring lands at the first live 14B "
                        "slot (#765); inject oracle_generator to run this case")))
            continue

        try:
            generated = oracle_generator(str(case["goal_id"]))
            report.results.append(_evaluate(case, generated))
        except Exception as exc:  # noqa: BLE001
            report.results.append(CaseResult(
                case_id=case_id, status=CaseStatus.ERROR,
                description=description, expected=case["expect"],
                detail=f"generation/harness error: {exc}"))

    return report
