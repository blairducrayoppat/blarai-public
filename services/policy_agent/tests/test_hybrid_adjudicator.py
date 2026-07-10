"""
HybridAdjudicator Tests — Policy Agent (P1.4)
================================================
Tests for the stateful pipeline orchestrator: rule engine → integrity
re-verification → GPU inference → decision matrix → AdjudicationContext.

Test Groups:
  A. AdjudicationContext + AdjudicationLatency dataclass properties
  B. HybridAdjudicator construction and properties
  C. Full pipeline with GPU Fail-Closed stub (no model loaded)
  D. Full pipeline with mocked GPU (all 5 decision matrix rows)
  E. Event-triggered integrity re-verification paths
  F. Latency tracking
  G. Pipeline short-circuit behavior
  H. Adjudication counter and sequential independence
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from shared.schemas.car import (
    ActionVerb,
    AdjudicationDecision,
    CanonicalActionRepresentation,
    DecisionArtifact,
    Sensitivity,
)
from services.policy_agent.src.adjudicator import (
    AdjudicationContext,
    AdjudicationLatency,
    HybridAdjudicator,
    adjudicate,
)
from services.policy_agent.src.car import build_car
from services.policy_agent.src.constants import (
    ESCALATION_CONFIDENCE_RANGE,
    PROBABILISTIC_CONFIDENCE_THRESHOLD,
)
from services.policy_agent.src.gpu_inference import (
    GPUClassificationResult,
    PolicyGPUInference,
)
from services.policy_agent.src.rule_engine import (
    RateLimiter,
    RuleEngineResult,
    RuleResult,
    RuleVerdict,
)
from services.policy_agent.src.config_loader import ResourceDenyRule
from shared.models.weight_integrity import IntegrityCheckResult


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

ACL_MATRIX: dict[str, list[str]] = {
    "assistant_orchestrator": ["substrate", "semantic_router", "code_agent"],
    "code_agent": ["substrate"],
    "semantic_router": [],
}


def _make_car(
    source: str = "assistant_orchestrator",
    dest: str = "substrate",
    verb: ActionVerb = ActionVerb.READ,
    resource: str = "substrate.vector_store",
    sensitivity: Sensitivity = Sensitivity.INTERNAL,
) -> CanonicalActionRepresentation:
    return build_car(
        source_agent=source,
        destination_service=dest,
        verb=verb,
        resource=resource,
        sensitivity=sensitivity,
        session_id="sess-p14-test",
    )


def _make_gpu_stub() -> PolicyGPUInference:
    """Create an unloaded GPU stub (Fail-Closed behavior)."""
    return PolicyGPUInference("dummy_dir")


def _make_adjudicator(
    npu: PolicyGPUInference | None = None,
    acl: dict[str, list[str]] | None = ACL_MATRIX,
    manifest_path: str | None = None,
    model_bin_path: str | None = None,
    rate_limiter: RateLimiter | None = None,
    resource_deny_list: list[ResourceDenyRule] | None = None,
    require_signed_manifest: bool = False,
) -> HybridAdjudicator:
    """Create a HybridAdjudicator with sensible defaults."""
    return HybridAdjudicator(
        npu_inference=npu or _make_gpu_stub(),
        acl_matrix=acl,
        rate_limiter=rate_limiter,
        resource_deny_list=resource_deny_list,
        manifest_path=manifest_path,
        model_bin_path=model_bin_path,
        require_signed_manifest=require_signed_manifest,
    )


def _write_temp_bin(content: bytes = b"model-weight-data") -> str:
    """Write temp .bin file and return its path."""
    fd, path = tempfile.mkstemp(suffix=".bin")
    with os.fdopen(fd, "wb") as f:
        f.write(content)
    return path


def _write_manifest(bin_path: str, *, correct: bool = True) -> str:
    """Write a manifest that matches (or doesn't) the bin file."""
    import hashlib

    filename = Path(bin_path).name
    if correct:
        with open(bin_path, "rb") as f:
            digest = hashlib.sha256(f.read()).hexdigest()
    else:
        digest = "0" * 64  # intentionally wrong
    fd, mpath = tempfile.mkstemp(suffix=".json")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump({"version": "1.0.0", "digests": {filename: digest}}, f)
    return mpath


# ---------------------------------------------------------------------------
# Group A: AdjudicationContext + AdjudicationLatency
# ---------------------------------------------------------------------------

class TestAdjudicationLatency:
    """Verify the AdjudicationLatency dataclass."""

    def test_default_values_all_zero(self) -> None:
        lat = AdjudicationLatency()
        assert lat.rule_engine_ms == 0.0
        assert lat.integrity_ms == 0.0
        assert lat.npu_inference_ms == 0.0
        assert lat.total_ms == 0.0

    def test_custom_values(self) -> None:
        lat = AdjudicationLatency(
            rule_engine_ms=1.5,
            integrity_ms=200.0,
            npu_inference_ms=50.0,
            total_ms=251.5,
        )
        assert lat.rule_engine_ms == 1.5
        assert lat.integrity_ms == 200.0
        assert lat.npu_inference_ms == 50.0
        assert lat.total_ms == 251.5

    def test_frozen_immutable(self) -> None:
        lat = AdjudicationLatency()
        with pytest.raises(AttributeError):
            lat.total_ms = 99.0  # type: ignore[misc]


class TestAdjudicationContext:
    """Verify AdjudicationContext properties."""

    def _make_context(
        self,
        decision: AdjudicationDecision = AdjudicationDecision.ALLOW,
        integrity: IntegrityCheckResult | None = None,
    ) -> AdjudicationContext:
        artifact = DecisionArtifact(
            car_hash="a" * 64,
            decision=decision,
            request_id="req-1",
            deterministic_pass=True,
            probabilistic_pass=decision == AdjudicationDecision.ALLOW,
            confidence=0.9 if decision == AdjudicationDecision.ALLOW else 0.3,
        )
        npu = GPUClassificationResult(
            label=decision.value, confidence=0.9, latency_ms=1.0,
        )
        rule = RuleEngineResult(
            passed=True,
            results=(RuleResult("STRUCTURAL", RuleVerdict.ALLOW, "ok"),),
        )
        return AdjudicationContext(
            adjudication_id="test-uuid",
            decision_artifact=artifact,
            rule_engine_result=rule,
            npu_result=npu,
            runtime_integrity=integrity,
            latency=AdjudicationLatency(total_ms=5.0),
        )

    def test_decision_property(self) -> None:
        ctx = self._make_context(AdjudicationDecision.DENY)
        assert ctx.decision == AdjudicationDecision.DENY

    def test_passed_property_allow(self) -> None:
        ctx = self._make_context(AdjudicationDecision.ALLOW)
        assert ctx.passed is True

    def test_passed_property_deny(self) -> None:
        ctx = self._make_context(AdjudicationDecision.DENY)
        assert ctx.passed is False

    def test_passed_property_escalate(self) -> None:
        ctx = self._make_context(AdjudicationDecision.ESCALATE)
        assert ctx.passed is False

    def test_integrity_verified_none(self) -> None:
        ctx = self._make_context()
        assert ctx.integrity_verified is False

    def test_integrity_verified_pass(self) -> None:
        integrity = IntegrityCheckResult(
            verified=True, computed_digest="abc", expected_digest="abc",
            model_path="m.bin",
        )
        ctx = self._make_context(integrity=integrity)
        assert ctx.integrity_verified is True

    def test_integrity_verified_fail(self) -> None:
        integrity = IntegrityCheckResult(
            verified=False, computed_digest="abc", expected_digest="xyz",
            model_path="m.bin", error="mismatch",
        )
        ctx = self._make_context(integrity=integrity)
        assert ctx.integrity_verified is False

    def test_timestamp_populated(self) -> None:
        ctx = self._make_context()
        assert ctx.timestamp is not None


# ---------------------------------------------------------------------------
# Group B: HybridAdjudicator construction and properties
# ---------------------------------------------------------------------------

class TestHybridAdjudicatorProperties:
    """Verify adjudicator construction and property access."""

    def test_initial_count_zero(self) -> None:
        adj = _make_adjudicator()
        assert adj.adjudication_count == 0

    def test_npu_loaded_when_not_loaded(self) -> None:
        adj = _make_adjudicator()
        assert adj.npu_loaded is False

    def test_has_integrity_checking_false_by_default(self) -> None:
        adj = _make_adjudicator()
        assert adj.has_integrity_checking is False

    def test_has_integrity_checking_true_with_paths(self) -> None:
        adj = _make_adjudicator(
            manifest_path="/tmp/manifest.json",
            model_bin_path="/tmp/model.bin",
        )
        assert adj.has_integrity_checking is True

    def test_has_integrity_checking_false_manifest_only(self) -> None:
        adj = _make_adjudicator(manifest_path="/tmp/manifest.json")
        assert adj.has_integrity_checking is False

    def test_from_config_factory(self) -> None:
        npu = _make_gpu_stub()
        adj = HybridAdjudicator.from_config(
            npu_inference=npu,
            acl_matrix=ACL_MATRIX,
        )
        assert adj.adjudication_count == 0
        assert adj.npu_loaded is False


# ---------------------------------------------------------------------------
# Group C: Full pipeline with NPU Fail-Closed stub
# ---------------------------------------------------------------------------

class TestPipelineWithGPUStub:
    """End-to-end tests using unloaded NPU (Fail-Closed behavior).

    A valid CAR that passes all deterministic rules will receive DENY
    because the NPU model is not loaded → classify returns DENY/0.0/error.
    """

    def test_valid_car_npu_stub_denies(self) -> None:
        adj = _make_adjudicator()
        car = _make_car()
        ctx = adj.adjudicate_car(car)

        assert ctx.decision == AdjudicationDecision.DENY
        assert ctx.decision_artifact.deterministic_pass is True
        assert ctx.decision_artifact.probabilistic_pass is False
        assert ctx.npu_result.error is not None
        assert ctx.runtime_integrity is None

    def test_rule_engine_deny_short_circuits_npu(self) -> None:
        """UNCLASSIFIED sensitivity → rule DENY → NPU never called."""
        adj = _make_adjudicator()
        car = _make_car(sensitivity=Sensitivity.UNCLASSIFIED)
        ctx = adj.adjudicate_car(car)

        assert ctx.decision == AdjudicationDecision.DENY
        assert ctx.decision_artifact.deterministic_pass is False
        assert ctx.npu_result.error is not None
        assert "Skipped" in ctx.npu_result.error
        assert ctx.latency.npu_inference_ms == 0.0

    def test_acl_denied_short_circuits(self) -> None:
        adj = _make_adjudicator()
        car = _make_car(source="semantic_router", dest="substrate")
        ctx = adj.adjudicate_car(car)

        assert ctx.decision == AdjudicationDecision.DENY
        assert ctx.rule_engine_result.blocking_rule == "ACL_PERMISSION"

    def test_incomplete_car_short_circuits(self) -> None:
        adj = _make_adjudicator()
        car = build_car(
            source_agent="",
            destination_service="substrate",
            verb=ActionVerb.READ,
            resource="substrate.vector_store",
            sensitivity=Sensitivity.INTERNAL,
        )
        ctx = adj.adjudicate_car(car)

        assert ctx.decision == AdjudicationDecision.DENY
        assert ctx.rule_engine_result.blocking_rule == "STRUCTURAL_COMPLETENESS"

    def test_adjudication_id_is_uuid(self) -> None:
        adj = _make_adjudicator()
        car = _make_car()
        ctx = adj.adjudicate_car(car)

        # UUID4 format: 8-4-4-4-12
        parts = ctx.adjudication_id.split("-")
        assert len(parts) == 5
        assert len(ctx.adjudication_id) == 36


# ---------------------------------------------------------------------------
# Group D: Full pipeline with mocked NPU (all 5 decision matrix rows)
# ---------------------------------------------------------------------------

class TestPipelineWithMockedNPU:
    """Tests where NPU.classify_car is mocked to inject specific results."""

    def _make_mocked_adjudicator(
        self, npu_label: str, npu_confidence: float,
        npu_error: str | None = None,
    ) -> HybridAdjudicator:
        """Create adjudicator with a mocked NPU that returns fixed results."""
        npu = _make_gpu_stub()
        npu.classify_car = MagicMock(  # type: ignore[assignment]
            return_value=GPUClassificationResult(
                label=npu_label,
                confidence=npu_confidence,
                latency_ms=1.0,
                error=npu_error,
            )
        )
        # Mark as loaded so classify_car is called (not short-circuited by stub)
        npu._loaded = True  # type: ignore[attr-defined]
        return _make_adjudicator(npu=npu)

    def test_row1_rule_deny_overrides_npu_allow(self) -> None:
        """Row 1: Rule DENY + NPU ALLOW → DENY."""
        adj = self._make_mocked_adjudicator("ALLOW", 0.99)
        car = _make_car(sensitivity=Sensitivity.UNCLASSIFIED)
        ctx = adj.adjudicate_car(car)

        assert ctx.decision == AdjudicationDecision.DENY
        assert ctx.decision_artifact.deterministic_pass is False
        # NPU was never called (short-circuit)
        assert "Skipped" in ctx.npu_result.error  # type: ignore[operator]

    def test_row2_both_allow(self) -> None:
        """Row 2: Rule ALLOW + NPU ALLOW (≥0.75) → ALLOW."""
        adj = self._make_mocked_adjudicator("ALLOW", 0.90)
        car = _make_car()
        ctx = adj.adjudicate_car(car)

        assert ctx.decision == AdjudicationDecision.ALLOW
        assert ctx.decision_artifact.deterministic_pass is True
        assert ctx.decision_artifact.probabilistic_pass is True
        assert ctx.decision_artifact.confidence == 0.90

    def test_row3_escalate_by_confidence(self) -> None:
        """Row 3: Rule ALLOW + NPU ALLOW in [0.50, 0.75) → ESCALATE."""
        adj = self._make_mocked_adjudicator("ALLOW", 0.60)
        car = _make_car()
        ctx = adj.adjudicate_car(car)

        assert ctx.decision == AdjudicationDecision.ESCALATE
        assert ctx.decision_artifact.deterministic_pass is True
        assert ctx.decision_artifact.probabilistic_pass is False

    def test_row3_escalate_by_label(self) -> None:
        """Row 3 variant: NPU returns ESCALATE label."""
        adj = self._make_mocked_adjudicator("ESCALATE", 0.65)
        car = _make_car()
        ctx = adj.adjudicate_car(car)

        assert ctx.decision == AdjudicationDecision.ESCALATE

    def test_row4_npu_deny(self) -> None:
        """Row 4: Rule ALLOW + NPU DENY → DENY."""
        adj = self._make_mocked_adjudicator("DENY", 0.95)
        car = _make_car()
        ctx = adj.adjudicate_car(car)

        assert ctx.decision == AdjudicationDecision.DENY
        assert ctx.decision_artifact.deterministic_pass is True
        assert ctx.decision_artifact.probabilistic_pass is False

    def test_row5_npu_error_fail_closed(self) -> None:
        """Row 5: Rule ALLOW + NPU error → DENY."""
        adj = self._make_mocked_adjudicator(
            "DENY", 0.0, npu_error="NPU hardware fault"
        )
        car = _make_car()
        ctx = adj.adjudicate_car(car)

        assert ctx.decision == AdjudicationDecision.DENY
        assert ctx.decision_artifact.deterministic_pass is True
        assert ctx.decision_artifact.confidence == 0.0

    def test_confidence_exactly_at_threshold_allows(self) -> None:
        """Confidence == 0.75 → ALLOW (≥ comparison)."""
        adj = self._make_mocked_adjudicator("ALLOW", 0.75)
        car = _make_car()
        ctx = adj.adjudicate_car(car)

        assert ctx.decision == AdjudicationDecision.ALLOW

    def test_confidence_just_below_threshold_escalates(self) -> None:
        """Confidence 0.7499 → ESCALATE."""
        adj = self._make_mocked_adjudicator("ALLOW", 0.7499)
        car = _make_car()
        ctx = adj.adjudicate_car(car)

        assert ctx.decision == AdjudicationDecision.ESCALATE

    def test_confidence_below_escalation_floor_denies(self) -> None:
        """Confidence 0.49 → below [0.50, 0.75) → DENY."""
        adj = self._make_mocked_adjudicator("ALLOW", 0.49)
        car = _make_car()
        ctx = adj.adjudicate_car(car)

        assert ctx.decision == AdjudicationDecision.DENY

    def test_confidence_at_escalation_floor_escalates(self) -> None:
        """Confidence == 0.50 (exact lower bound of ESCALATION_CONFIDENCE_RANGE) → ESCALATE.

        Pins the >= lower-bound behavior. A regression changing the comparison
        to `>` would silently deny at exactly 0.50 without any existing test
        catching it.
        """
        adj = self._make_mocked_adjudicator("ALLOW", 0.50)
        car = _make_car()
        ctx = adj.adjudicate_car(car)

        assert ctx.decision == AdjudicationDecision.ESCALATE

    def test_confidence_just_above_escalation_floor_escalates(self) -> None:
        """Confidence 0.51 → still inside [0.50, 0.75) → ESCALATE.

        Completes the boundary coverage between 0.49 (DENY) and 0.60 (ESCALATE)
        across the escalation floor.
        """
        adj = self._make_mocked_adjudicator("ALLOW", 0.51)
        car = _make_car()
        ctx = adj.adjudicate_car(car)

        assert ctx.decision == AdjudicationDecision.ESCALATE


# ---------------------------------------------------------------------------
# Group E: Event-triggered integrity re-verification
# ---------------------------------------------------------------------------

class TestIntegrityReVerification:
    """Test runtime weight integrity re-verification before NPU inference."""

    def test_integrity_pass_allows_npu_inference(self) -> None:
        """Valid manifest + matching hash → NPU classify is called."""
        bin_path = _write_temp_bin()
        manifest_path = _write_manifest(bin_path, correct=True)
        try:
            npu = _make_gpu_stub()
            npu.classify_car = MagicMock(  # type: ignore[assignment]
                return_value=GPUClassificationResult(
                    label="ALLOW", confidence=0.90, latency_ms=1.0,
                )
            )
            npu._loaded = True  # type: ignore[attr-defined]
            adj = _make_adjudicator(
                npu=npu,
                manifest_path=manifest_path,
                model_bin_path=bin_path,
            )
            car = _make_car()
            ctx = adj.adjudicate_car(car)

            assert ctx.decision == AdjudicationDecision.ALLOW
            assert ctx.runtime_integrity is not None
            assert ctx.runtime_integrity.verified is True
            assert ctx.integrity_verified is True
            npu.classify_car.assert_called_once()
        finally:
            os.unlink(bin_path)
            os.unlink(manifest_path)

    def test_integrity_failure_blocks_npu_returns_deny(self) -> None:
        """Mismatched hash → DENY without calling NPU."""
        bin_path = _write_temp_bin()
        manifest_path = _write_manifest(bin_path, correct=False)
        try:
            npu = _make_gpu_stub()
            npu.classify_car = MagicMock(  # type: ignore[assignment]
                return_value=GPUClassificationResult(
                    label="ALLOW", confidence=0.99, latency_ms=1.0,
                )
            )
            npu._loaded = True  # type: ignore[attr-defined]
            adj = _make_adjudicator(
                npu=npu,
                manifest_path=manifest_path,
                model_bin_path=bin_path,
            )
            car = _make_car()
            ctx = adj.adjudicate_car(car)

            assert ctx.decision == AdjudicationDecision.DENY
            assert ctx.runtime_integrity is not None
            assert ctx.runtime_integrity.verified is False
            assert ctx.integrity_verified is False
            assert "integrity" in ctx.npu_result.error.lower()  # type: ignore[union-attr]
            # NPU was NOT called
            npu.classify_car.assert_not_called()
        finally:
            os.unlink(bin_path)
            os.unlink(manifest_path)

    def test_require_signed_manifest_denies_unsigned_manifest(self) -> None:
        """#571: with require_signed_manifest=True and a CORRECT-but-UNSIGNED
        manifest (matching digest, no .sig), Stage-2 re-verify fails closed →
        DENY without calling NPU. Proves the signed-manifest posture is threaded
        into the per-request path (not just the boot gate); the SAME inputs
        ALLOW when require_signed_manifest defaults False
        (test_integrity_pass_allows_npu_inference)."""
        bin_path = _write_temp_bin()
        manifest_path = _write_manifest(bin_path, correct=True)  # matches; no .sig written
        try:
            npu = _make_gpu_stub()
            npu.classify_car = MagicMock(  # type: ignore[assignment]
                return_value=GPUClassificationResult(
                    label="ALLOW", confidence=0.99, latency_ms=1.0,
                )
            )
            npu._loaded = True  # type: ignore[attr-defined]
            adj = _make_adjudicator(
                npu=npu,
                manifest_path=manifest_path,
                model_bin_path=bin_path,
                require_signed_manifest=True,
            )
            car = _make_car()
            ctx = adj.adjudicate_car(car)

            assert ctx.decision == AdjudicationDecision.DENY
            assert ctx.runtime_integrity is not None
            assert ctx.runtime_integrity.verified is False
            assert ctx.integrity_verified is False
            npu.classify_car.assert_not_called()
        finally:
            os.unlink(bin_path)
            os.unlink(manifest_path)

    def test_integrity_skipped_when_no_manifest(self) -> None:
        """No manifest configured → integrity check skipped entirely."""
        adj = _make_adjudicator()  # no manifest_path
        car = _make_car()
        ctx = adj.adjudicate_car(car)

        assert ctx.runtime_integrity is None
        assert ctx.integrity_verified is False

    def test_integrity_skipped_on_rule_deny(self) -> None:
        """Rule engine DENY → integrity check skipped (short-circuit)."""
        bin_path = _write_temp_bin()
        manifest_path = _write_manifest(bin_path, correct=True)
        try:
            adj = _make_adjudicator(
                manifest_path=manifest_path,
                model_bin_path=bin_path,
            )
            car = _make_car(sensitivity=Sensitivity.UNCLASSIFIED)
            ctx = adj.adjudicate_car(car)

            assert ctx.decision == AdjudicationDecision.DENY
            # Integrity was NOT checked because rules denied first
            assert ctx.runtime_integrity is None
            assert ctx.latency.integrity_ms == 0.0
        finally:
            os.unlink(bin_path)
            os.unlink(manifest_path)

    def test_integrity_missing_bin_file_returns_deny(self) -> None:
        """Model .bin file doesn't exist → integrity failure → DENY."""
        # Create manifest that references a non-existent bin
        fd, manifest_path = tempfile.mkstemp(suffix=".json")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump({
                "version": "1.0.0",
                "digests": {"nonexistent.bin": "a" * 64},
            }, f)
        try:
            npu = _make_gpu_stub()
            npu._loaded = True  # type: ignore[attr-defined]
            adj = _make_adjudicator(
                npu=npu,
                manifest_path=manifest_path,
                model_bin_path="/nonexistent/path/nonexistent.bin",
            )
            car = _make_car()
            ctx = adj.adjudicate_car(car)

            assert ctx.decision == AdjudicationDecision.DENY
            assert ctx.runtime_integrity is not None
            assert ctx.runtime_integrity.verified is False
        finally:
            os.unlink(manifest_path)

    def test_integrity_reverified_each_adjudication(self) -> None:
        """Integrity is re-checked on EVERY adjudication (event-triggered)."""
        bin_path = _write_temp_bin()
        manifest_path = _write_manifest(bin_path, correct=True)
        try:
            npu = _make_gpu_stub()
            npu.classify_car = MagicMock(  # type: ignore[assignment]
                return_value=GPUClassificationResult(
                    label="ALLOW", confidence=0.90, latency_ms=1.0,
                )
            )
            npu._loaded = True  # type: ignore[attr-defined]
            adj = _make_adjudicator(
                npu=npu,
                manifest_path=manifest_path,
                model_bin_path=bin_path,
            )

            # Adjudicate twice
            car1 = _make_car()
            car2 = _make_car(resource="skill.calendar")
            ctx1 = adj.adjudicate_car(car1)
            ctx2 = adj.adjudicate_car(car2)

            # Both should have integrity checked
            assert ctx1.runtime_integrity is not None
            assert ctx1.runtime_integrity.verified is True
            assert ctx2.runtime_integrity is not None
            assert ctx2.runtime_integrity.verified is True
            # NPU called twice
            assert npu.classify_car.call_count == 2
        finally:
            os.unlink(bin_path)
            os.unlink(manifest_path)


# ---------------------------------------------------------------------------
# Group F: Latency tracking
# ---------------------------------------------------------------------------

class TestLatencyTracking:
    """Verify per-stage latency measurement."""

    def test_total_ms_greater_than_zero(self) -> None:
        adj = _make_adjudicator()
        car = _make_car()
        ctx = adj.adjudicate_car(car)

        assert ctx.latency.total_ms > 0.0

    def test_rule_engine_ms_greater_than_zero(self) -> None:
        adj = _make_adjudicator()
        car = _make_car()
        ctx = adj.adjudicate_car(car)

        assert ctx.latency.rule_engine_ms > 0.0

    def test_npu_ms_zero_on_rule_deny(self) -> None:
        adj = _make_adjudicator()
        car = _make_car(sensitivity=Sensitivity.UNCLASSIFIED)
        ctx = adj.adjudicate_car(car)

        assert ctx.latency.npu_inference_ms == 0.0

    def test_npu_ms_nonzero_on_npu_call(self) -> None:
        """When NPU is called, npu_inference_ms > 0."""
        npu = _make_gpu_stub()
        npu.classify_car = MagicMock(  # type: ignore[assignment]
            return_value=GPUClassificationResult(
                label="ALLOW", confidence=0.90, latency_ms=1.0,
            )
        )
        npu._loaded = True  # type: ignore[attr-defined]
        adj = _make_adjudicator(npu=npu)
        car = _make_car()
        ctx = adj.adjudicate_car(car)

        assert ctx.latency.npu_inference_ms > 0.0

    def test_integrity_ms_nonzero_when_checked(self) -> None:
        bin_path = _write_temp_bin()
        manifest_path = _write_manifest(bin_path, correct=True)
        try:
            npu = _make_gpu_stub()
            npu.classify_car = MagicMock(  # type: ignore[assignment]
                return_value=GPUClassificationResult(
                    label="ALLOW", confidence=0.90, latency_ms=1.0,
                )
            )
            npu._loaded = True  # type: ignore[attr-defined]
            adj = _make_adjudicator(
                npu=npu,
                manifest_path=manifest_path,
                model_bin_path=bin_path,
            )
            car = _make_car()
            ctx = adj.adjudicate_car(car)

            assert ctx.latency.integrity_ms > 0.0
        finally:
            os.unlink(bin_path)
            os.unlink(manifest_path)

    def test_integrity_ms_zero_when_not_configured(self) -> None:
        adj = _make_adjudicator()
        car = _make_car()
        ctx = adj.adjudicate_car(car)

        assert ctx.latency.integrity_ms == 0.0


# ---------------------------------------------------------------------------
# Group G: Pipeline short-circuit behavior
# ---------------------------------------------------------------------------

class TestShortCircuit:
    """Verify short-circuit: rule DENY → skip integrity + NPU."""

    def test_structural_deny_skips_everything(self) -> None:
        adj = _make_adjudicator()
        car = build_car(
            source_agent="",
            destination_service="substrate",
            verb=ActionVerb.READ,
            resource="r",
            sensitivity=Sensitivity.INTERNAL,
        )
        ctx = adj.adjudicate_car(car)

        assert ctx.decision == AdjudicationDecision.DENY
        assert ctx.rule_engine_result.blocking_rule == "STRUCTURAL_COMPLETENESS"
        assert ctx.runtime_integrity is None
        assert ctx.latency.integrity_ms == 0.0
        assert ctx.latency.npu_inference_ms == 0.0

    def test_sensitivity_deny_skips_npu(self) -> None:
        adj = _make_adjudicator()
        car = _make_car(sensitivity=Sensitivity.UNCLASSIFIED)
        ctx = adj.adjudicate_car(car)

        assert ctx.decision == AdjudicationDecision.DENY
        assert ctx.rule_engine_result.blocking_rule == "SENSITIVITY_CLASSIFICATION"
        assert ctx.latency.npu_inference_ms == 0.0

    def test_acl_deny_skips_npu(self) -> None:
        adj = _make_adjudicator()
        car = _make_car(source="semantic_router", dest="substrate")
        ctx = adj.adjudicate_car(car)

        assert ctx.decision == AdjudicationDecision.DENY
        assert ctx.rule_engine_result.blocking_rule == "ACL_PERMISSION"
        assert ctx.latency.npu_inference_ms == 0.0

    def test_rate_limit_deny_skips_npu(self) -> None:
        """Rate limit exceeded → DENY, NPU not invoked."""
        rl = RateLimiter(max_requests=1, window_seconds=60.0)
        adj = _make_adjudicator(rate_limiter=rl)

        car = _make_car()
        # First call within budget
        ctx1 = adj.adjudicate_car(car)
        # Second call exceeds budget
        ctx2 = adj.adjudicate_car(car)

        assert ctx2.decision == AdjudicationDecision.DENY
        assert ctx2.rule_engine_result.blocking_rule == "RATE_LIMIT"
        assert ctx2.latency.npu_inference_ms == 0.0

    def test_resource_deny_list_skips_npu(self) -> None:
        rules = [
            ResourceDenyRule(
                verb=None,
                resource_pattern="substrate.dangerous_*",
                reason="Denied by policy",
            ),
        ]
        adj = _make_adjudicator(resource_deny_list=rules)
        car = _make_car(resource="substrate.dangerous_endpoint")
        ctx = adj.adjudicate_car(car)

        assert ctx.decision == AdjudicationDecision.DENY
        assert ctx.rule_engine_result.blocking_rule == "RESOURCE_DENY_LIST"
        assert ctx.latency.npu_inference_ms == 0.0


# ---------------------------------------------------------------------------
# Group H: Adjudication counter and sequential independence
# ---------------------------------------------------------------------------

class TestCounterAndIndependence:
    """Verify adjudication_count and sequential independence."""

    def test_counter_increments(self) -> None:
        adj = _make_adjudicator()
        car = _make_car()

        assert adj.adjudication_count == 0
        adj.adjudicate_car(car)
        assert adj.adjudication_count == 1
        adj.adjudicate_car(car)
        assert adj.adjudication_count == 2

    def test_counter_increments_on_deny(self) -> None:
        adj = _make_adjudicator()
        car = _make_car(sensitivity=Sensitivity.UNCLASSIFIED)

        adj.adjudicate_car(car)
        assert adj.adjudication_count == 1

    def test_counter_increments_on_integrity_failure(self) -> None:
        bin_path = _write_temp_bin()
        manifest_path = _write_manifest(bin_path, correct=False)
        try:
            npu = _make_gpu_stub()
            npu._loaded = True  # type: ignore[attr-defined]
            adj = _make_adjudicator(
                npu=npu,
                manifest_path=manifest_path,
                model_bin_path=bin_path,
            )
            car = _make_car()
            adj.adjudicate_car(car)
            assert adj.adjudication_count == 1
        finally:
            os.unlink(bin_path)
            os.unlink(manifest_path)

    def test_sequential_adjudications_independent(self) -> None:
        """Two sequential adjudications with different NPU outcomes."""
        npu = _make_gpu_stub()
        call_count = [0]
        results = [
            GPUClassificationResult(label="ALLOW", confidence=0.90, latency_ms=1.0),
            GPUClassificationResult(label="DENY", confidence=0.95, latency_ms=1.0),
        ]

        def _side_effect(car: CanonicalActionRepresentation) -> GPUClassificationResult:
            idx = call_count[0]
            call_count[0] += 1
            return results[idx]

        npu.classify_car = MagicMock(side_effect=_side_effect)  # type: ignore[assignment]
        npu._loaded = True  # type: ignore[attr-defined]
        adj = _make_adjudicator(npu=npu)

        car_a = _make_car(resource="substrate.vector_store")
        car_b = _make_car(resource="skill.calendar")

        ctx_a = adj.adjudicate_car(car_a)
        ctx_b = adj.adjudicate_car(car_b)

        assert ctx_a.decision == AdjudicationDecision.ALLOW
        assert ctx_b.decision == AdjudicationDecision.DENY
        assert ctx_a.decision_artifact.car_hash != ctx_b.decision_artifact.car_hash

    def test_adjudication_ids_unique(self) -> None:
        adj = _make_adjudicator()
        car = _make_car()

        ctx1 = adj.adjudicate_car(car)
        ctx2 = adj.adjudicate_car(car)

        assert ctx1.adjudication_id != ctx2.adjudication_id


# ---------------------------------------------------------------------------
# Group I: Backward-compatible adjudicate() pure function
# ---------------------------------------------------------------------------

class TestAdjudicatePureFunction:
    """Verify the standalone adjudicate() function still works (P1.1 compat)."""

    def _rule_pass(self) -> RuleEngineResult:
        return RuleEngineResult(
            passed=True,
            results=(RuleResult("STRUCTURAL", RuleVerdict.ALLOW, "ok"),),
        )

    def _rule_fail(self) -> RuleEngineResult:
        return RuleEngineResult(
            passed=False,
            results=(RuleResult("STRUCTURAL", RuleVerdict.DENY, "fail"),),
            blocking_rule="STRUCTURAL",
        )

    def test_rule_deny_overrides_npu(self) -> None:
        car = _make_car()
        npu = GPUClassificationResult(label="ALLOW", confidence=0.99, latency_ms=1.0)
        result = adjudicate(car, self._rule_fail(), npu)
        assert result.decision == AdjudicationDecision.DENY

    def test_both_allow(self) -> None:
        car = _make_car()
        npu = GPUClassificationResult(label="ALLOW", confidence=0.85, latency_ms=1.0)
        result = adjudicate(car, self._rule_pass(), npu)
        assert result.decision == AdjudicationDecision.ALLOW

    def test_npu_error_deny(self) -> None:
        car = _make_car()
        npu = GPUClassificationResult(
            label="DENY", confidence=0.0, latency_ms=0.0, error="fault"
        )
        result = adjudicate(car, self._rule_pass(), npu)
        assert result.decision == AdjudicationDecision.DENY

    def test_npu_escalate(self) -> None:
        car = _make_car()
        npu = GPUClassificationResult(label="ALLOW", confidence=0.60, latency_ms=1.0)
        result = adjudicate(car, self._rule_pass(), npu)
        assert result.decision == AdjudicationDecision.ESCALATE
