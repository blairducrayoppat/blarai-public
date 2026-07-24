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
from evals.model_target import Capability, ModelTarget
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
    *,
    speculative_decoding_enabled: bool | None = None,
) -> Callable[[dict[str, Any]], tuple[str, str | None]]:
    """Build the model-in-the-loop classifier (Arc 140V required).

    Loads the real ``PolicyGPUInference`` (Qwen3-14B, ADR-012) once and
    runs the FULL pipeline: pre-filter -> rule engine -> real GPU
    classification -> ``adjudicate`` decision matrix. This is the
    production classification path; misses here are the measurable form
    of ISS-3.

    Args:
        model_dir: The PA model directory to load.
        speculative_decoding_enabled: When ``None`` (the default), construct
            ``PolicyGPUInference`` EXACTLY as before (byte-identical). A #931
            ``text-llm`` override passes the declared speculative-decode
            contract explicitly.

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
    if speculative_decoding_enabled is None:
        gpu = PolicyGPUInference(str(model_dir))
    else:
        gpu = PolicyGPUInference(
            str(model_dir),
            speculative_decoding_enabled=speculative_decoding_enabled,
        )
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


# A ``multimodal-vlm`` #931 override targets a natively multimodal checkpoint
# that OpenVINO GenAI serves through a VLMPipeline. The PA classifier path is
# ``PolicyGPUInference`` (LLMPipeline-bound: ``classify_car`` formats a
# classification prompt and parses a verdict), so a faithful VLM PA classifier
# is a distinct build, not a one-line pipeline swap. Until it lands, VLM model
# cases here are SKIPPED (loud, explained) so an ``--suite all`` VLM parity run
# stays usable and never silently mis-pipelines PA. See #931 follow-on.
_VLM_PA_NOT_WIRED_DETAIL: str = (
    "multimodal-vlm capability is not wired for the PA classifier "
    "(PolicyGPUInference is LLMPipeline-bound) — skipped, not mis-pipelined "
    "(#931 follow-on). Use --capability text-llm for a dense PA override, or the "
    "answer_quality suite for VLM answer-parity."
)


def run_suite(
    golden_file: Path | None = None,
    *,
    include_hardware: bool = False,
    hardware_classifier: Callable[[dict[str, Any]], tuple[str, str | None]] | None = None,
    model_target: ModelTarget | None = None,
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
        model_target: The #931 OPT-IN hardware model-target override. ``None``
            keeps the byte-identical default 14B path. A ``text-llm`` target
            loads its directory (honoring the speculative-decode contract)
            through the same ``PolicyGPUInference`` path. A ``multimodal-vlm``
            target SKIPS the model cases (loud, explained) — the VLM PA
            classifier is a #931 follow-on.

    Returns:
        SuiteReport with one CaseResult per golden case.
    """
    path = golden_file or golden_path(SUITE_NAME)
    cases = load_golden(path)

    report = SuiteReport(suite=SUITE_NAME)
    deterministic_classify = make_deterministic_classifier()
    model_classify = hardware_classifier
    vlm_target = (
        model_target is not None
        and model_target.capability is Capability.MULTIMODAL_VLM
    )

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
            if vlm_target and hardware_classifier is None:
                report.results.append(
                    CaseResult(
                        case_id=str(case["id"]),
                        status=CaseStatus.SKIPPED_HARDWARE,
                        description=str(case.get("description", "")),
                        expected=str(case["label"]),
                        detail=_VLM_PA_NOT_WIRED_DETAIL,
                    )
                )
                continue
            if model_classify is None:
                model_classify = make_real_gpu_classifier(
                    _resolve_model_dir(model_target),
                    speculative_decoding_enabled=(
                        model_target.speculative_decode
                        if model_target is not None
                        else None
                    ),
                )
            report.results.append(_evaluate_case(case, model_classify))
        else:
            report.results.append(_evaluate_case(case, deterministic_classify))

    return report


def _resolve_model_dir(model_target: ModelTarget | None) -> Path:
    """The PA model directory to load: the #931 override's, else the default 14B."""
    return model_target.model_dir if model_target is not None else default_model_dir()
