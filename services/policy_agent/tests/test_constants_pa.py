"""Value-anchor tests for Policy Agent behavioral constants.

Task 8 / EA-1 / WI-14: pins the exact values of operational decision
boundaries (confidence threshold, escalation range) and deployment
constants (measured-boot retry, rate limit, JWT TTL, inference device).
A regression changing any of these would not otherwise be caught by a
behavior test that only exercises an in-range confidence.
"""

from __future__ import annotations

from services.policy_agent.src.constants import (
    ESCALATION_CONFIDENCE_RANGE,
    INFERENCE_DEVICE,
    JWT_ISSUER,
    JWT_VALIDITY_SECONDS,
    MEASURED_BOOT_MAX_ATTEMPTS,
    MEASURED_BOOT_REQUIRED,
    MEASURED_BOOT_RETRY_DELAY_S,
    PROBABILISTIC_CONFIDENCE_THRESHOLD,
    RATE_LIMIT_MAX_REQUESTS,
    RATE_LIMIT_WINDOW_SECONDS,
    RULE_ENGINE_VERSION,
    SERVICE_NAME,
)


class TestPolicyAgentConstants:
    """Direct value assertions on PA constants — regression anchors."""

    def test_probabilistic_confidence_threshold(self) -> None:
        assert PROBABILISTIC_CONFIDENCE_THRESHOLD == 0.75

    def test_escalation_confidence_range(self) -> None:
        assert ESCALATION_CONFIDENCE_RANGE == (0.50, 0.75)
        assert ESCALATION_CONFIDENCE_RANGE[0] == 0.50
        assert ESCALATION_CONFIDENCE_RANGE[1] == 0.75
        assert ESCALATION_CONFIDENCE_RANGE[1] == PROBABILISTIC_CONFIDENCE_THRESHOLD

    def test_measured_boot_constants(self) -> None:
        assert MEASURED_BOOT_MAX_ATTEMPTS == 3
        assert MEASURED_BOOT_RETRY_DELAY_S == 0.25
        assert MEASURED_BOOT_REQUIRED is True

    def test_jwt_constants(self) -> None:
        assert JWT_VALIDITY_SECONDS == 5
        assert JWT_ISSUER == "policy_agent"

    def test_rate_limit_constants(self) -> None:
        assert RATE_LIMIT_MAX_REQUESTS == 100
        assert RATE_LIMIT_WINDOW_SECONDS == 60.0

    def test_service_identity_constants(self) -> None:
        assert SERVICE_NAME == "policy_agent"
        assert RULE_ENGINE_VERSION == "1.0.0"

    def test_inference_device_constant(self) -> None:
        # Post-ADR-011: PA classification runs on GPU (re-exported from shared.constants.PA_DEVICE).
        assert INFERENCE_DEVICE == "GPU"
