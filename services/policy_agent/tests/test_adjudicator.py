"""
Adjudicator Tests — Policy Agent
====================================
Tests for the hybrid adjudication pipeline (deterministic + probabilistic).
"""

from __future__ import annotations

import pytest

from shared.schemas.car import (
    ActionVerb,
    AdjudicationDecision,
    CanonicalActionRepresentation,
    Sensitivity,
)
from services.policy_agent.src.adjudicator import adjudicate
from services.policy_agent.src.gpu_inference import GPUClassificationResult
from services.policy_agent.src.rule_engine import RuleEngineResult, RuleResult, RuleVerdict


def _make_car() -> CanonicalActionRepresentation:
    return CanonicalActionRepresentation(
        source_agent="orch",
        destination_service="sub",
        verb=ActionVerb.READ,
        resource="r",
        request_id="req-1",
        sensitivity=Sensitivity.INTERNAL,
    )


def _rule_pass() -> RuleEngineResult:
    return RuleEngineResult(
        passed=True,
        results=(RuleResult("STRUCTURAL", RuleVerdict.ALLOW, "ok"),),
    )


def _rule_fail() -> RuleEngineResult:
    return RuleEngineResult(
        passed=False,
        results=(RuleResult("STRUCTURAL", RuleVerdict.DENY, "fail"),),
        blocking_rule="STRUCTURAL",
    )


class TestAdjudicator:
    """Hybrid adjudication decision matrix."""

    def test_rule_deny_overrides_npu_allow(self) -> None:
        """Deterministic DENY is non-appealable."""
        npu = GPUClassificationResult(label="ALLOW", confidence=0.99, latency_ms=1.0)
        decision = adjudicate(_make_car(), _rule_fail(), npu)
        assert decision.decision == AdjudicationDecision.DENY
        assert not decision.deterministic_pass

    def test_both_allow(self) -> None:
        """Rule ALLOW + NPU ALLOW above threshold → ALLOW."""
        npu = GPUClassificationResult(label="ALLOW", confidence=0.85, latency_ms=1.0)
        decision = adjudicate(_make_car(), _rule_pass(), npu)
        assert decision.decision == AdjudicationDecision.ALLOW
        assert decision.deterministic_pass
        assert decision.probabilistic_pass

    def test_npu_error_fail_closed(self) -> None:
        """NPU inference error → DENY (Fail-Closed)."""
        npu = GPUClassificationResult(
            label="DENY", confidence=0.0, latency_ms=0.0, error="NPU failure"
        )
        decision = adjudicate(_make_car(), _rule_pass(), npu)
        assert decision.decision == AdjudicationDecision.DENY

    def test_npu_low_confidence_escalates(self) -> None:
        """NPU confidence in [0.50, 0.75) → ESCALATE."""
        npu = GPUClassificationResult(label="ALLOW", confidence=0.60, latency_ms=1.0)
        decision = adjudicate(_make_car(), _rule_pass(), npu)
        assert decision.decision == AdjudicationDecision.ESCALATE

    def test_npu_deny_label(self) -> None:
        """NPU predicts DENY → final DENY regardless of confidence."""
        npu = GPUClassificationResult(label="DENY", confidence=0.90, latency_ms=1.0)
        decision = adjudicate(_make_car(), _rule_pass(), npu)
        assert decision.decision == AdjudicationDecision.DENY
