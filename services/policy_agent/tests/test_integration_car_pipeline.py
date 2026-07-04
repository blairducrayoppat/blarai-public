"""
Integration Tests — CAR → Rule Engine → Adjudicator Pipeline
================================================================
P1.1: End-to-end validation of the Policy Agent adjudication data flow.

These tests exercise the **full pipeline**:
  build_car() → run_rule_engine() → adjudicate() → DecisionArtifact

Unlike P1.0 unit tests (which test each component in isolation with
manually-constructed helper objects), these integration tests verify that:
  1. Data flows correctly across module boundaries.
  2. The decision matrix produces correct outcomes for ALL 5 cases.
  3. CAR field values propagate consistently to the final DecisionArtifact.
  4. Boundary conditions on confidence thresholds route correctly.
  5. Sequential adjudications remain independent (no shared state leaks).
  6. The real GPU Fail-Closed stub produces the expected end-to-end result.

Test Groups:
  A. End-to-End with Real GPU Stub (Fail-Closed default behavior)
  B. Full Decision Matrix (simulated GPU results covering all 5 cases)
  C. Pipeline Property Invariants (hash propagation, boundaries, independence)
"""

from __future__ import annotations

import pytest

from shared.schemas.car import (
    ActionVerb,
    AdjudicationDecision,
    CanonicalActionRepresentation,
    DecisionArtifact,
    Sensitivity,
)
from services.policy_agent.src.car import build_car
from services.policy_agent.src.rule_engine import run_rule_engine, RuleEngineResult
from services.policy_agent.src.adjudicator import adjudicate
from services.policy_agent.src.gpu_inference import (
    GPUClassificationResult,
    PolicyGPUInference,
)
from services.policy_agent.src.constants import (
    ESCALATION_CONFIDENCE_RANGE,
    PROBABILISTIC_CONFIDENCE_THRESHOLD,
)


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

# A permissive ACL matrix used by most integration tests.
# Maps source_agent → list of allowed destination_services.
ACL_MATRIX: dict[str, list[str]] = {
    "assistant_orchestrator": ["substrate", "semantic_router", "code_agent"],
    "code_agent": ["substrate"],
    "semantic_router": [],
}


def _build_valid_car(
    source: str = "assistant_orchestrator",
    dest: str = "substrate",
    verb: ActionVerb | str = ActionVerb.READ,
    resource: str = "substrate.vector_store",
    sensitivity: Sensitivity | str = Sensitivity.INTERNAL,
    session_id: str = "sess-integ-001",
) -> CanonicalActionRepresentation:
    """Build a CAR that passes all 3 deterministic rules."""
    return build_car(
        source_agent=source,
        destination_service=dest,
        verb=verb,
        resource=resource,
        sensitivity=sensitivity,
        session_id=session_id,
    )


def _run_pipeline(
    car: CanonicalActionRepresentation,
    npu_result: GPUClassificationResult,
    acl_matrix: dict[str, list[str]] | None = ACL_MATRIX,
) -> tuple[RuleEngineResult, DecisionArtifact]:
    """Run the full pipeline: rule engine → adjudicate.

    Returns both intermediate and final results for assertion.
    """
    rule_result = run_rule_engine(car, acl_matrix=acl_matrix)
    decision = adjudicate(car, rule_result, npu_result)
    return rule_result, decision


# ---------------------------------------------------------------------------
# Group A: End-to-End with Real GPU Stub
# ---------------------------------------------------------------------------

class TestEndToEndWithGPUStub:
    """Integration tests using the real PolicyGPUInference stub.

    The GPU stub is Fail-Closed: classify() returns DENY/0.0 with an
    error message because the model is not loaded. A valid CAR that passes
    all deterministic rules will therefore receive a final DENY from the
    adjudicator (GPU error → Fail-Closed).
    """

    def test_valid_car_full_pipeline_stub_npu_denies(self) -> None:
        """Valid CAR + all rules pass + real GPU stub → DENY (Fail-Closed).

        This is the canonical end-to-end path when the NPU model has not
        been loaded yet (P1.3 will implement model loading).
        """
        car = _build_valid_car()
        npu = PolicyGPUInference("dummy_dir")
        npu_result = npu.classify_car(car)

        rule_result, decision = _run_pipeline(car, npu_result)

        # Rule engine passes all 3 rules
        assert rule_result.passed is True
        assert rule_result.blocking_rule is None
        assert len(rule_result.results) == 3

        # NPU stub error → Fail-Closed → DENY
        assert npu_result.error is not None
        assert decision.decision == AdjudicationDecision.DENY
        assert decision.deterministic_pass is True
        assert decision.probabilistic_pass is False
        assert decision.confidence == 0.0

    def test_incomplete_car_short_circuits_before_npu(self) -> None:
        """Incomplete CAR → STRUCTURAL DENY at rule engine (NPU irrelevant).

        Even though the NPU stub would also DENY, the rule engine DENY
        takes precedence and is non-appealable.
        """
        # Build CAR with empty source_agent → is_complete() returns False
        car = build_car(
            source_agent="",
            destination_service="substrate",
            verb=ActionVerb.READ,
            resource="substrate.vector_store",
            sensitivity=Sensitivity.INTERNAL,
        )
        npu = PolicyGPUInference("dummy_dir")
        npu_result = npu.classify_car(car)

        rule_result, decision = _run_pipeline(car, npu_result)

        assert rule_result.passed is False
        assert rule_result.blocking_rule == "STRUCTURAL_COMPLETENESS"
        assert decision.decision == AdjudicationDecision.DENY
        assert decision.deterministic_pass is False

    def test_unclassified_sensitivity_short_circuits(self) -> None:
        """UNCLASSIFIED sensitivity → SENSITIVITY DENY (Fail-Closed).

        UNCLASSIFIED is the default when sensitivity is not explicitly set.
        The security contract requires this to be denied.
        """
        car = _build_valid_car(sensitivity=Sensitivity.UNCLASSIFIED)
        npu = PolicyGPUInference("dummy_dir")
        npu_result = npu.classify_car(car)

        rule_result, decision = _run_pipeline(car, npu_result)

        assert rule_result.passed is False
        assert rule_result.blocking_rule == "SENSITIVITY_CLASSIFICATION"
        assert decision.decision == AdjudicationDecision.DENY
        assert decision.deterministic_pass is False

    def test_acl_denied_agent_short_circuits(self) -> None:
        """Source agent not in ACL matrix → ACL DENY.

        semantic_router has an empty allowed list, so any destination
        triggers ACL DENY.
        """
        car = _build_valid_car(
            source="semantic_router",
            dest="substrate",
            sensitivity=Sensitivity.INTERNAL,
        )
        npu = PolicyGPUInference("dummy_dir")
        npu_result = npu.classify_car(car)

        rule_result, decision = _run_pipeline(car, npu_result)

        assert rule_result.passed is False
        assert rule_result.blocking_rule == "ACL_PERMISSION"
        assert decision.decision == AdjudicationDecision.DENY
        assert decision.deterministic_pass is False

    def test_no_acl_matrix_fail_closed(self) -> None:
        """ACL matrix is None → Fail-Closed DENY.

        This simulates a boot-race condition where the ACL config has
        not been loaded yet. Fail-Closed rejects.
        """
        car = _build_valid_car()
        npu = PolicyGPUInference("dummy_dir")
        npu_result = npu.classify_car(car)

        rule_result, decision = _run_pipeline(car, npu_result, acl_matrix=None)

        assert rule_result.passed is False
        assert rule_result.blocking_rule == "ACL_PERMISSION"
        assert decision.decision == AdjudicationDecision.DENY


# ---------------------------------------------------------------------------
# Group B: Full Decision Matrix (Simulated NPU Results)
# ---------------------------------------------------------------------------

class TestDecisionMatrixEndToEnd:
    """Integration tests covering all 5 rows of the decision matrix.

    These use build_car() → run_rule_engine() with real ACL, then
    inject simulated GPUClassificationResult to exercise each matrix row.
    The CAR is always valid and ACL-permitted, so the final outcome is
    determined by the NPU result.

    Matrix:
      | Rule Engine | NPU Classifier      | Final Decision |
      |-------------|---------------------|----------------|
      | DENY        | (any)               | DENY           |
      | ALLOW       | ALLOW (≥ threshold) | ALLOW          |
      | ALLOW       | ESCALATE range      | ESCALATE       |
      | ALLOW       | DENY label          | DENY           |
      | ALLOW       | Error               | DENY           |
    """

    def test_matrix_row1_rule_deny_overrides_npu_allow(self) -> None:
        """Row 1: Rule DENY + NPU ALLOW → DENY (non-appealable)."""
        # CAR with UNCLASSIFIED sensitivity → rule engine DENY
        car = _build_valid_car(sensitivity=Sensitivity.UNCLASSIFIED)
        npu_result = GPUClassificationResult(
            label="ALLOW", confidence=0.99, latency_ms=0.5,
        )
        rule_result, decision = _run_pipeline(car, npu_result)

        assert rule_result.passed is False
        assert decision.decision == AdjudicationDecision.DENY
        assert decision.deterministic_pass is False
        # NPU said ALLOW but deterministic DENY wins
        assert decision.confidence == 0.99

    def test_matrix_row2_both_allow(self) -> None:
        """Row 2: Rule ALLOW + NPU ALLOW (≥0.75) → ALLOW."""
        car = _build_valid_car()
        npu_result = GPUClassificationResult(
            label="ALLOW", confidence=0.90, latency_ms=0.8,
        )
        rule_result, decision = _run_pipeline(car, npu_result)

        assert rule_result.passed is True
        assert decision.decision == AdjudicationDecision.ALLOW
        assert decision.deterministic_pass is True
        assert decision.probabilistic_pass is True
        assert decision.confidence == 0.90

    def test_matrix_row3_escalate_range(self) -> None:
        """Row 3: Rule ALLOW + NPU in [0.50, 0.75) → ESCALATE."""
        car = _build_valid_car()
        npu_result = GPUClassificationResult(
            label="ALLOW", confidence=0.60, latency_ms=0.7,
        )
        rule_result, decision = _run_pipeline(car, npu_result)

        assert rule_result.passed is True
        assert decision.decision == AdjudicationDecision.ESCALATE
        assert decision.deterministic_pass is True
        assert decision.probabilistic_pass is False
        assert decision.confidence == 0.60

    def test_matrix_row3_escalate_label(self) -> None:
        """Row 3 variant: NPU returns ESCALATE label explicitly."""
        car = _build_valid_car()
        npu_result = GPUClassificationResult(
            label="ESCALATE", confidence=0.65, latency_ms=0.7,
        )
        rule_result, decision = _run_pipeline(car, npu_result)

        assert rule_result.passed is True
        assert decision.decision == AdjudicationDecision.ESCALATE
        assert decision.deterministic_pass is True

    def test_matrix_row4_npu_deny(self) -> None:
        """Row 4: Rule ALLOW + NPU DENY → DENY."""
        car = _build_valid_car()
        npu_result = GPUClassificationResult(
            label="DENY", confidence=0.95, latency_ms=0.6,
        )
        rule_result, decision = _run_pipeline(car, npu_result)

        assert rule_result.passed is True
        assert decision.decision == AdjudicationDecision.DENY
        assert decision.deterministic_pass is True
        assert decision.probabilistic_pass is False

    def test_matrix_row5_npu_error_fail_closed(self) -> None:
        """Row 5: Rule ALLOW + NPU error → DENY (Fail-Closed)."""
        car = _build_valid_car()
        npu_result = GPUClassificationResult(
            label="DENY", confidence=0.0, latency_ms=0.0,
            error="NPU hardware fault — inference timeout",
        )
        rule_result, decision = _run_pipeline(car, npu_result)

        assert rule_result.passed is True
        assert decision.decision == AdjudicationDecision.DENY
        assert decision.deterministic_pass is True
        assert decision.probabilistic_pass is False
        assert decision.confidence == 0.0


# ---------------------------------------------------------------------------
# Group C: Pipeline Property Invariants
# ---------------------------------------------------------------------------

class TestPipelineProperties:
    """Verify cross-cutting properties that must hold across the full pipeline."""

    def test_car_hash_propagates_to_decision_artifact(self) -> None:
        """canonical_hash() computed on the CAR must match DecisionArtifact.car_hash."""
        car = _build_valid_car()
        expected_hash = car.canonical_hash()
        npu_result = GPUClassificationResult(
            label="ALLOW", confidence=0.85, latency_ms=0.5,
        )
        _, decision = _run_pipeline(car, npu_result)

        assert decision.car_hash == expected_hash
        assert len(decision.car_hash) == 64  # SHA-256 hex digest

    def test_request_id_propagates_to_decision_artifact(self) -> None:
        """CAR.request_id must appear in DecisionArtifact.request_id."""
        car = _build_valid_car()
        npu_result = GPUClassificationResult(
            label="ALLOW", confidence=0.85, latency_ms=0.5,
        )
        _, decision = _run_pipeline(car, npu_result)

        assert decision.request_id == car.request_id
        assert decision.request_id != ""

    def test_decision_artifact_fields_complete(self) -> None:
        """Every DecisionArtifact field must be populated (no None/empty)."""
        car = _build_valid_car()
        npu_result = GPUClassificationResult(
            label="ALLOW", confidence=0.85, latency_ms=0.5,
        )
        _, decision = _run_pipeline(car, npu_result)

        assert decision.car_hash
        assert decision.decision is not None
        assert decision.request_id
        assert isinstance(decision.deterministic_pass, bool)
        assert isinstance(decision.probabilistic_pass, bool)
        assert 0.0 <= decision.confidence <= 1.0
        assert decision.timestamp is not None
        assert decision.expiry_seconds > 0
        assert decision.issuer == "policy_agent"

    def test_confidence_boundary_exactly_threshold_allows(self) -> None:
        """Confidence exactly at threshold (0.75) → ALLOW (≥ comparison)."""
        car = _build_valid_car()
        threshold = PROBABILISTIC_CONFIDENCE_THRESHOLD  # 0.75
        npu_result = GPUClassificationResult(
            label="ALLOW", confidence=threshold, latency_ms=0.5,
        )
        _, decision = _run_pipeline(car, npu_result)

        assert decision.decision == AdjudicationDecision.ALLOW
        assert decision.probabilistic_pass is True

    def test_confidence_boundary_just_below_threshold_escalates(self) -> None:
        """Confidence at 0.7499 → below threshold → ESCALATE (in range)."""
        car = _build_valid_car()
        npu_result = GPUClassificationResult(
            label="ALLOW", confidence=0.7499, latency_ms=0.5,
        )
        _, decision = _run_pipeline(car, npu_result)

        assert decision.decision == AdjudicationDecision.ESCALATE

    def test_confidence_boundary_exactly_escalation_floor(self) -> None:
        """Confidence exactly at 0.50 (escalation floor) → ESCALATE."""
        car = _build_valid_car()
        low, _ = ESCALATION_CONFIDENCE_RANGE  # (0.50, 0.75)
        npu_result = GPUClassificationResult(
            label="ALLOW", confidence=low, latency_ms=0.5,
        )
        _, decision = _run_pipeline(car, npu_result)

        assert decision.decision == AdjudicationDecision.ESCALATE

    def test_confidence_below_escalation_floor_denies(self) -> None:
        """Confidence at 0.49 → below escalation range → DENY."""
        car = _build_valid_car()
        npu_result = GPUClassificationResult(
            label="ALLOW", confidence=0.49, latency_ms=0.5,
        )
        _, decision = _run_pipeline(car, npu_result)

        assert decision.decision == AdjudicationDecision.DENY

    def test_sequential_adjudications_independent(self) -> None:
        """Multiple CARs adjudicated sequentially produce independent results.

        No shared state should leak between adjudications.
        """
        car_a = _build_valid_car(resource="substrate.vector_store")
        car_b = _build_valid_car(resource="skill.calendar")

        npu_allow = GPUClassificationResult(
            label="ALLOW", confidence=0.90, latency_ms=0.5,
        )
        npu_deny = GPUClassificationResult(
            label="DENY", confidence=0.95, latency_ms=0.6,
        )

        _, decision_a = _run_pipeline(car_a, npu_allow)
        _, decision_b = _run_pipeline(car_b, npu_deny)

        assert decision_a.decision == AdjudicationDecision.ALLOW
        assert decision_b.decision == AdjudicationDecision.DENY

        # Hashes differ because resource differs
        assert decision_a.car_hash != decision_b.car_hash
        # Request IDs differ (uuid4 per build_car call)
        assert decision_a.request_id != decision_b.request_id

    def test_string_verb_normalization_through_pipeline(self) -> None:
        """build_car() with string verb flows correctly through the pipeline.

        Verifies the string → enum normalization in build_car() does not
        break downstream rule engine or adjudicator processing.
        """
        car = build_car(
            source_agent="assistant_orchestrator",
            destination_service="substrate",
            verb="read",  # lowercase string, not ActionVerb enum
            resource="substrate.vector_store",
            sensitivity="internal",  # lowercase string
            session_id="sess-norm-001",
        )
        npu_result = GPUClassificationResult(
            label="ALLOW", confidence=0.85, latency_ms=0.5,
        )
        rule_result, decision = _run_pipeline(car, npu_result)

        assert car.verb == ActionVerb.READ
        assert car.sensitivity == Sensitivity.INTERNAL
        assert rule_result.passed is True
        assert decision.decision == AdjudicationDecision.ALLOW

    def test_all_action_verbs_pass_structural_validation(self) -> None:
        """Every ActionVerb produces a structurally valid CAR through pipeline."""
        for verb in ActionVerb:
            car = _build_valid_car(verb=verb)
            npu_result = GPUClassificationResult(
                label="ALLOW", confidence=0.85, latency_ms=0.5,
            )
            rule_result, _ = _run_pipeline(car, npu_result)
            assert rule_result.passed is True, f"Verb {verb.value} failed structural check"

    def test_all_sensitivity_levels_except_unclassified_pass(self) -> None:
        """PUBLIC, INTERNAL, SENSITIVE all pass sensitivity rule.

        UNCLASSIFIED is the only sensitivity that triggers Fail-Closed DENY.
        """
        passing_levels = [Sensitivity.PUBLIC, Sensitivity.INTERNAL, Sensitivity.SENSITIVE]
        for level in passing_levels:
            car = _build_valid_car(sensitivity=level)
            npu_result = GPUClassificationResult(
                label="ALLOW", confidence=0.85, latency_ms=0.5,
            )
            rule_result, decision = _run_pipeline(car, npu_result)
            assert rule_result.passed is True, f"Sensitivity {level.value} should pass"
            assert decision.decision == AdjudicationDecision.ALLOW

    def test_car_hash_deterministic_across_pipeline_runs(self) -> None:
        """Same CAR fields produce identical hashes across separate pipeline runs.

        This is critical for audit trail correlation and replay detection.
        """
        # Build two CARs with identical fields (request_id will differ,
        # but canonical_hash excludes request_id by design).
        car_1 = _build_valid_car()
        car_2 = _build_valid_car()

        npu = GPUClassificationResult(
            label="ALLOW", confidence=0.85, latency_ms=0.5,
        )
        _, decision_1 = _run_pipeline(car_1, npu)
        _, decision_2 = _run_pipeline(car_2, npu)

        # Hashes match because identity + action fields are identical
        assert decision_1.car_hash == decision_2.car_hash
        # But request_ids differ (each build_car generates a fresh uuid4)
        assert decision_1.request_id != decision_2.request_id

    def test_rule_engine_result_count_matches_pipeline_rules(self) -> None:
        """Rule engine always evaluates exactly 3 rules (STRUCTURAL, SENSITIVITY, ACL)."""
        car = _build_valid_car()
        npu = GPUClassificationResult(
            label="ALLOW", confidence=0.85, latency_ms=0.5,
        )
        rule_result, _ = _run_pipeline(car, npu)

        assert len(rule_result.results) == 3
        rule_names = [r.rule_name for r in rule_result.results]
        assert rule_names == [
            "STRUCTURAL_COMPLETENESS",
            "SENSITIVITY_CLASSIFICATION",
            "ACL_PERMISSION",
        ]
