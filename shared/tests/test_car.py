"""Sprint 8 EA-4 WI-10: tests for shared.schemas.car."""
from __future__ import annotations

import pytest

from shared.schemas.car import (
    ActionVerb,
    AdjudicationDecision,
    CanonicalActionRepresentation,
    DecisionArtifact,
    Sensitivity,
)


def _make_car(**overrides) -> CanonicalActionRepresentation:
    defaults = dict(
        source_agent="agent-a",
        destination_service="svc.vector",
        verb=ActionVerb.READ,
        resource="substrate.vector_store",
        parameters_schema={"query": {"type": "string"}},
        sensitivity=Sensitivity.INTERNAL,
        request_id="req-42",
    )
    defaults.update(overrides)
    return CanonicalActionRepresentation(**defaults)


class TestCanonicalHash:
    """WI-10: canonical_hash determinism + sensitivity to field changes."""

    def test_identical_cars_produce_identical_hash(self) -> None:
        a = _make_car()
        b = _make_car()
        assert a.canonical_hash() == b.canonical_hash()

    def test_resource_change_changes_hash(self) -> None:
        a = _make_car(resource="substrate.vector_store")
        b = _make_car(resource="skill.calendar")
        assert a.canonical_hash() != b.canonical_hash()


class TestIsComplete:
    """WI-10: is_complete true/false branches."""

    def test_complete_car_is_complete(self) -> None:
        assert _make_car().is_complete() is True

    def test_empty_source_agent_incomplete(self) -> None:
        assert _make_car(source_agent="").is_complete() is False

    def test_empty_request_id_incomplete(self) -> None:
        assert _make_car(request_id="").is_complete() is False


class TestDecisionArtifact:
    """WI-10: DecisionArtifact construction + field access."""

    def test_construction_fields_accessible(self) -> None:
        car = _make_car()
        artifact = DecisionArtifact(
            car_hash=car.canonical_hash(),
            decision=AdjudicationDecision.ALLOW,
            request_id=car.request_id,
            deterministic_pass=True,
            probabilistic_pass=True,
            confidence=0.95,
        )
        assert artifact.car_hash == car.canonical_hash()
        assert artifact.decision == AdjudicationDecision.ALLOW
        assert artifact.request_id == "req-42"
        assert artifact.deterministic_pass is True
        assert artifact.probabilistic_pass is True
        assert artifact.confidence == 0.95
        assert artifact.issuer == "policy_agent"
        assert artifact.expiry_seconds == 5


class TestEnums:
    """WI-10: Canonical enum membership checks."""

    def test_action_verb_members(self) -> None:
        values = {v.value for v in ActionVerb}
        assert values == {"READ", "WRITE", "EXECUTE", "DELETE", "QUERY", "DISPATCH", "EGRESS"}

    def test_sensitivity_members(self) -> None:
        values = {s.value for s in Sensitivity}
        assert values == {"PUBLIC", "INTERNAL", "SENSITIVE", "UNCLASSIFIED"}

    def test_adjudication_decision_members(self) -> None:
        values = {d.value for d in AdjudicationDecision}
        assert values == {"ALLOW", "DENY", "ESCALATE"}
