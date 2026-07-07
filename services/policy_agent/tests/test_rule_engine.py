"""
Rule Engine Tests — Policy Agent
===================================
Tests for the deterministic rule pipeline: STRUCTURAL, SENSITIVITY, ACL.
"""

from __future__ import annotations

import pytest

from shared.schemas.car import ActionVerb, CanonicalActionRepresentation, Sensitivity
from services.policy_agent.src.rule_engine import (
    RuleVerdict,
    evaluate_acl,
    evaluate_sensitivity,
    evaluate_structural,
    run_rule_engine,
)


class TestStructuralRule:
    """STRUCTURAL rule: CAR completeness."""

    def test_complete_car_passes(self) -> None:
        car = CanonicalActionRepresentation(
            source_agent="orch",
            destination_service="substrate",
            verb=ActionVerb.READ,
            resource="r",
            request_id="req-1",
            sensitivity=Sensitivity.INTERNAL,
        )
        result = evaluate_structural(car)
        assert result.verdict == RuleVerdict.ALLOW

    def test_incomplete_car_denied(self) -> None:
        car = CanonicalActionRepresentation(
            source_agent="",
            destination_service="substrate",
            verb=ActionVerb.READ,
            resource="r",
            request_id="req-1",
            sensitivity=Sensitivity.INTERNAL,
        )
        result = evaluate_structural(car)
        assert result.verdict == RuleVerdict.DENY


class TestSensitivityRule:
    """SENSITIVITY rule: UNCLASSIFIED = Fail-Closed DENY."""

    def test_unclassified_denied(self) -> None:
        car = CanonicalActionRepresentation(
            source_agent="orch",
            destination_service="sub",
            verb=ActionVerb.READ,
            resource="r",
            request_id="req-1",
            sensitivity=Sensitivity.UNCLASSIFIED,
        )
        result = evaluate_sensitivity(car)
        assert result.verdict == RuleVerdict.DENY

    def test_internal_allowed(self) -> None:
        car = CanonicalActionRepresentation(
            source_agent="orch",
            destination_service="sub",
            verb=ActionVerb.READ,
            resource="r",
            request_id="req-1",
            sensitivity=Sensitivity.INTERNAL,
        )
        result = evaluate_sensitivity(car)
        assert result.verdict == RuleVerdict.ALLOW


class TestACLRule:
    """ACL rule: permission matrix enforcement."""

    def test_no_acl_matrix_denied(self) -> None:
        car = CanonicalActionRepresentation(
            source_agent="orch",
            destination_service="sub",
            verb=ActionVerb.READ,
            resource="r",
            request_id="req-1",
            sensitivity=Sensitivity.INTERNAL,
        )
        result = evaluate_acl(car, acl_matrix=None)
        assert result.verdict == RuleVerdict.DENY

    def test_permitted_agent_allowed(self) -> None:
        acl = {"orch": ["sub", "skill"]}
        car = CanonicalActionRepresentation(
            source_agent="orch",
            destination_service="sub",
            verb=ActionVerb.READ,
            resource="r",
            request_id="req-1",
            sensitivity=Sensitivity.INTERNAL,
        )
        result = evaluate_acl(car, acl_matrix=acl)
        assert result.verdict == RuleVerdict.ALLOW

    def test_unpermitted_agent_denied(self) -> None:
        acl = {"orch": ["skill"]}
        car = CanonicalActionRepresentation(
            source_agent="orch",
            destination_service="sub",
            verb=ActionVerb.READ,
            resource="r",
            request_id="req-1",
            sensitivity=Sensitivity.INTERNAL,
        )
        result = evaluate_acl(car, acl_matrix=acl)
        assert result.verdict == RuleVerdict.DENY


class TestRuleEnginePipeline:
    """Full pipeline: STRUCTURAL → SENSITIVITY → ACL."""

    def test_full_allow(self) -> None:
        acl = {"orch": ["sub"]}
        car = CanonicalActionRepresentation(
            source_agent="orch",
            destination_service="sub",
            verb=ActionVerb.READ,
            resource="r",
            request_id="req-1",
            sensitivity=Sensitivity.PUBLIC,
        )
        result = run_rule_engine(car, acl_matrix=acl)
        assert result.passed

    def test_structural_deny_short_circuits(self) -> None:
        """A STRUCTURAL DENY should make the pipeline fail even if ACL would allow."""
        acl = {"": ["sub"]}
        car = CanonicalActionRepresentation(
            source_agent="",
            destination_service="sub",
            verb=ActionVerb.READ,
            resource="r",
            request_id="req-1",
            sensitivity=Sensitivity.PUBLIC,
        )
        result = run_rule_engine(car, acl_matrix=acl)
        assert not result.passed
        assert result.blocking_rule == "STRUCTURAL_COMPLETENESS"
