"""
Semantic Router Constants — Direct Wiring Assertions
=====================================================
Regression guard that pins Semantic Router constants to their empirical
baseline (P1.7 calibration) and shared-hardware source of truth. Catches
accidental drift in confidence-gate thresholds or device routing.
"""

from __future__ import annotations

from shared import constants as shared_constants
from services.semantic_router.src import constants as sr_constants


class TestSRWiringFromShared:
    """Direct equality between SR re-exports and shared-hardware truth."""

    def test_model_name_matches_shared(self) -> None:
        assert sr_constants.MODEL_NAME == shared_constants.SEMANTIC_ROUTER_MODEL

    def test_model_size_matches_shared(self) -> None:
        assert sr_constants.MODEL_SIZE_MB == shared_constants.SEMANTIC_ROUTER_MODEL_MB

    def test_latency_target_matches_shared(self) -> None:
        assert (
            sr_constants.LATENCY_TARGET_MS
            == shared_constants.SEMANTIC_ROUTER_LATENCY_MS
        )

    def test_fail_closed_matches_shared(self) -> None:
        assert sr_constants.SECURITY_POSTURE_FAIL_CLOSED == shared_constants.FAIL_CLOSED


class TestSRConfidenceGates:
    """Empirically-calibrated (P1.7) dual-gate thresholds."""

    def test_confidence_threshold_locked(self) -> None:
        assert sr_constants.CONFIDENCE_THRESHOLD == 0.50

    def test_confidence_margin_locked(self) -> None:
        assert sr_constants.CONFIDENCE_MARGIN == 0.04

    def test_confidence_threshold_is_float(self) -> None:
        assert isinstance(sr_constants.CONFIDENCE_THRESHOLD, float)

    def test_confidence_margin_is_float(self) -> None:
        assert isinstance(sr_constants.CONFIDENCE_MARGIN, float)


class TestSRServiceMetadata:
    """Service-identification and device-routing constants."""

    def test_service_name(self) -> None:
        assert sr_constants.SERVICE_NAME == "semantic_router"

    def test_inference_device_is_cpu(self) -> None:
        assert sr_constants.INFERENCE_DEVICE == "CPU"

    def test_inference_runtime_is_onnx(self) -> None:
        assert sr_constants.INFERENCE_RUNTIME == "ONNX"

    def test_default_intent_fail_closed_to_out_of_scope(self) -> None:
        assert sr_constants.DEFAULT_INTENT == "OUT_OF_SCOPE"

    def test_fail_closed_is_true(self) -> None:
        assert sr_constants.SECURITY_POSTURE_FAIL_CLOSED is True
