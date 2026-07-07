"""
Eval Suite — Policy Agent Classification (ISS-3)
=================================================
Measures the PA's classification judgment over golden CARs (Canonical
Action Representations) with expected ALLOW / DENY / ESCALATE labels.

Two case modes (the ``mode`` field of each golden case):

  deterministic — the verdict is decided by the REAL deterministic
      pipeline: ``DeterministicPolicyChecker`` pre-filter, then the rule
      engine, then the ``adjudicate`` decision matrix with a mocked-ALLOW
      GPU result (so a rules-pass ALLOW case exercises the real matrix).
      No model, no GPU — runs anywhere, including CI. A DENY/ESCALATE
      verdict here is decided by the rules alone; the mocked GPU can never
      overturn it (rule DENY is non-appealable — proven by the existing
      tests/pa_quality_benchmark suite this adapter mirrors).

  model — the verdict requires the real Qwen3-14B classifier on the
      Arc 140V (the ISS-3 territory: nuanced CARs where no deterministic
      rule fires). These cases are SKIPPED unless ``include_hardware=True``
      (the orchestrator runs hardware tiers serially after merge — a CI or
      builder run never loads the model).

Golden case schema (evals/golden/pa_classification.jsonl):
  {"id": "pa-det-001", "description": "...", "mode": "deterministic",
   "label": "DENY", "expected_rule": "DENY_RESTRICTED_PATH",   # optional
   "car": {"source_agent": ..., "destination_service": ..., "verb": ...,
           "resource": ..., "sensitivity": ..., "parameters_schema": {...}}}

``expected_rule`` (optional, deterministic cases only) additionally pins
WHICH pre-filter rule fired — a label match with the wrong rule is a FAIL
(the verdict was right for the wrong reason).
"""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any, Callable

from evals.loader import GoldenDataError, golden_path, load_golden
from evals.types import CaseResult, CaseStatus, SuiteReport

SUITE_NAME: str = "pa_classification"

_VALID_LABELS: frozenset[str] = frozenset({"ALLOW", "DENY", "ESCALATE"})
_VALID_MODES: frozenset[str] = frozenset({"deterministic", "model"})

# ACL matrix matching the golden corpus (mirrors the shape used by
# tests/pa_quality_benchmark — source_agent -> allowed destination services).
# unknown_agent_xyz is deliberately absent so ACL-deny cases exercise the
# fail-closed path.
EVAL_ACL_MATRIX: dict[str, list[str]] = {
    "orchestrator": ["substrate", "skill_calendar", "egress_gateway"],
    "assistant_orchestrator": ["assistant_orchestrator", "substrate"],
    "policy_agent": ["substrate"],
}


def _build_car(car_dict: dict[str, Any]) -> Any:
    """Construct a real CanonicalActionRepresentation from a golden dict."""
    from shared.schemas.car import (
        ActionVerb,
        CanonicalActionRepresentation,
        Sensitivity,
    )

    return CanonicalActionRepresentation(
        source_agent=car_dict.get("source_agent", ""),
        destination_service=car_dict.get("destination_service", ""),
        verb=ActionVerb(car_dict["verb"]) if car_dict.get("verb") else ActionVerb.READ,
        sensitivity=(
            Sensitivity(car_dict["sensitivity"])
            if car_dict.get("sensitivity")
            else Sensitivity.UNCLASSIFIED
        ),
        resource=car_dict.get("resource", ""),
        parameters_schema=car_dict.get("parameters_schema") or {},
        request_id=str(uuid.uuid4()),
        session_id=car_dict.get("session_id", ""),
    )


def make_deterministic_classifier() -> Callable[[dict[str, Any]], tuple[str, str | None]]:
    """Build the deterministic classifier over the REAL PA functions.

    Pipeline (single source of truth — the PA's own code, not a copy):
      1. ``DeterministicPolicyChecker.check`` (pre-filter; empty live
         egress allowlist — the welded air-gap posture).
      2. ``run_rule_engine`` (STRUCTURAL / SENSITIVITY / ACL / RESOURCE;
         no rate limiter so runs are order-independent).
      3. ``adjudicate`` decision matrix with a mocked ALLOW/0.9 GPU result,
         so rules-pass ALLOW cases exercise the real matrix while every
         rule verdict remains non-appealable.

    Returns:
        A callable ``car_dict -> (decision, prefilter_rule_or_None)``.
    """
    from services.policy_agent.src.adjudicator import adjudicate
    from services.policy_agent.src.gpu_inference import (
        DeterministicPolicyChecker,
        GPUClassificationResult,
    )
    from services.policy_agent.src.rule_engine import run_rule_engine

    mock_gpu_allow = GPUClassificationResult(
        label="ALLOW", confidence=0.9, latency_ms=0.0, error=None
    )

    def classify(car_dict: dict[str, Any]) -> tuple[str, str | None]:
        car = _build_car(car_dict)
        prefilter = DeterministicPolicyChecker.check(car)
        if prefilter is not None:
            decision, rule = prefilter
            return decision, rule
        rule_result = run_rule_engine(car, acl_matrix=EVAL_ACL_MATRIX)
        artifact = adjudicate(car, rule_result, mock_gpu_allow)
        return artifact.decision.value, None

    return classify


def make_real_gpu_classifier(
    model_dir: Path,
) -> Callable[[dict[str, Any]], tuple[str, str | None]]:
    """Build the model-in-the-loop classifier (Arc 140V required).

    Loads the real ``PolicyGPUInference`` (Qwen3-14B, ADR-012) once and
    runs the FULL pipeline: pre-filter -> rule engine -> real GPU
    classification -> ``adjudicate`` decision matrix. This is the
    production classification path; misses here are the measurable form
    of ISS-3.

    Raises:
        FileNotFoundError: If the model directory is absent (the model is
            gitignored; only the operator's machine has it).
        RuntimeError: If the model fails to load (fail-closed).
    """
    from services.policy_agent.src.adjudicator import adjudicate
    from services.policy_agent.src.gpu_inference import (
        DeterministicPolicyChecker,
        PolicyGPUInference,
    )
    from services.policy_agent.src.rule_engine import run_rule_engine

    if not model_dir.exists():
        raise FileNotFoundError(f"PA model directory not found: {model_dir}")
    gpu = PolicyGPUInference(str(model_dir))
    if not gpu.load_model():
        raise RuntimeError(f"PA model failed to load from {model_dir}")

    def classify(car_dict: dict[str, Any]) -> tuple[str, str | None]:
        car = _build_car(car_dict)
        prefilter = DeterministicPolicyChecker.check(car)
        if prefilter is not None:
            decision, rule = prefilter
            return decision, rule
        rule_result = run_rule_engine(car, acl_matrix=EVAL_ACL_MATRIX)
        gpu_result = gpu.classify_car(car)
        artifact = adjudicate(car, rule_result, gpu_result)
        return artifact.decision.value, None

    return classify


def default_model_dir() -> Path:
    """Resolve the production PA model directory (repo-root relative)."""
    return (
        Path(__file__).resolve().parents[2]
        / "models"
        / "qwen3-14b"
        / "openvino-int4-gpu"
    )


def _validate_case(case: dict[str, Any]) -> str | None:
    """Return an error string if the golden case is malformed, else None."""
    mode = case.get("mode")
    if mode not in _VALID_MODES:
        return f"invalid mode {mode!r} (must be one of {sorted(_VALID_MODES)})"
    label = case.get("label")
    if label not in _VALID_LABELS:
        return f"invalid label {label!r} (must be one of {sorted(_VALID_LABELS)})"
    if not isinstance(case.get("car"), dict):
        return "missing/invalid 'car' object"
    return None


def _evaluate_case(
    case: dict[str, Any],
    classify: Callable[[dict[str, Any]], tuple[str, str | None]],
) -> CaseResult:
    """Score one golden case against a classifier adapter."""
    case_id = str(case["id"])
    description = str(case.get("description", ""))
    expected_label = str(case["label"])
    expected_rule = case.get("expected_rule")

    try:
        actual_label, actual_rule = classify(case["car"])
    except Exception as exc:  # noqa: BLE001 — harness scoring must not abort the run
        return CaseResult(
            case_id=case_id,
            status=CaseStatus.ERROR,
            description=description,
            expected=expected_label,
            actual=None,
            detail=f"classifier raised: {exc}",
        )

    expected_repr: Any = (
        {"label": expected_label, "rule": expected_rule}
        if expected_rule
        else expected_label
    )
    actual_repr: Any = (
        {"label": actual_label, "rule": actual_rule}
        if expected_rule
        else actual_label
    )

    if actual_label != expected_label:
        return CaseResult(
            case_id=case_id,
            status=CaseStatus.FAIL,
            description=description,
            expected=expected_repr,
            actual=actual_repr,
            detail=f"label mismatch: expected {expected_label}, got {actual_label}",
        )
    if expected_rule and actual_rule != expected_rule:
        return CaseResult(
            case_id=case_id,
            status=CaseStatus.FAIL,
            description=description,
            expected=expected_repr,
            actual=actual_repr,
            detail=(
                f"right label, wrong rule: expected {expected_rule}, "
                f"got {actual_rule}"
            ),
        )
    return CaseResult(
        case_id=case_id,
        status=CaseStatus.PASS,
        description=description,
        expected=expected_repr,
        actual=actual_repr,
    )


def run_suite(
    golden_file: Path | None = None,
    *,
    include_hardware: bool = False,
    hardware_classifier: Callable[[dict[str, Any]], tuple[str, str | None]] | None = None,
) -> SuiteReport:
    """Run the PA classification suite.

    Args:
        golden_file: Override golden path (defaults to
            evals/golden/pa_classification.jsonl).
        include_hardware: When True, model-mode cases run through the real
            GPU classifier instead of being skipped. NEVER set this in CI.
        hardware_classifier: Injectable classifier for model-mode cases
            (built via :func:`make_real_gpu_classifier` when None and
            ``include_hardware`` is True).

    Returns:
        SuiteReport with one CaseResult per golden case.
    """
    path = golden_file or golden_path(SUITE_NAME)
    cases = load_golden(path)

    report = SuiteReport(suite=SUITE_NAME)
    deterministic_classify = make_deterministic_classifier()
    model_classify = hardware_classifier

    for case in cases:
        problem = _validate_case(case)
        if problem is not None:
            raise GoldenDataError(f"{path.name} case {case.get('id')}: {problem}")

        if case["mode"] == "model":
            if not include_hardware:
                report.results.append(
                    CaseResult(
                        case_id=str(case["id"]),
                        status=CaseStatus.SKIPPED_HARDWARE,
                        description=str(case.get("description", "")),
                        expected=str(case["label"]),
                        detail="model-in-the-loop case; requires --include-hardware on the Arc 140V",
                    )
                )
                continue
            if model_classify is None:
                model_classify = make_real_gpu_classifier(default_model_dir())
            report.results.append(_evaluate_case(case, model_classify))
        else:
            report.results.append(_evaluate_case(case, deterministic_classify))

    return report
