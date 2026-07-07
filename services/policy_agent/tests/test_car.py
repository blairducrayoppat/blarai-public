"""
CAR Schema Tests — Policy Agent
==================================
Tests for Canonical Action Representation construction, hashing, and
completeness validation.
"""

from __future__ import annotations

import pytest

from shared.schemas.car import (
    ActionVerb,
    CanonicalActionRepresentation,
    Sensitivity,
)
from services.policy_agent.src.car import build_car


class TestCARConstruction:
    """Test CAR building from raw fields."""

    def test_build_car_minimal(self) -> None:
        """A CAR with all required fields should be complete."""
        car = build_car(
            source_agent="orchestrator",
            destination_service="substrate",
            verb=ActionVerb.QUERY,
            resource="substrate.vector_store",
            sensitivity=Sensitivity.INTERNAL,
        )
        assert car.is_complete()
        assert car.verb == ActionVerb.QUERY
        assert car.sensitivity == Sensitivity.INTERNAL

    def test_build_car_string_verb(self) -> None:
        """String verbs should be normalized to ActionVerb enum."""
        car = build_car(
            source_agent="orchestrator",
            destination_service="substrate",
            verb="execute",
            resource="skill.calendar",
            sensitivity=Sensitivity.INTERNAL,
        )
        assert car.verb == ActionVerb.EXECUTE

    def test_build_car_sensitivity_required(self) -> None:
        """Omitting sensitivity must raise TypeError — no silent default."""
        with pytest.raises(TypeError):
            build_car(  # type: ignore[call-arg]
                source_agent="orchestrator",
                destination_service="substrate",
                verb=ActionVerb.READ,
                resource="substrate.vector_store",
            )

    def test_build_car_unclassified_explicit_accepted(self) -> None:
        """UNCLASSIFIED must still be accepted when set explicitly (Fail-Closed trigger)."""
        car = build_car(
            source_agent="orchestrator",
            destination_service="substrate",
            verb=ActionVerb.READ,
            resource="substrate.vector_store",
            sensitivity=Sensitivity.UNCLASSIFIED,
        )
        assert car.sensitivity == Sensitivity.UNCLASSIFIED

    def test_build_car_string_sensitivity(self) -> None:
        """String sensitivity should be normalized to the Sensitivity enum.

        Mirror of test_build_car_string_verb. Pins the string-to-enum
        normalization so a regression (e.g. removing the isinstance branch)
        would fail loudly rather than crashing at enum comparison sites.
        """
        car_internal = build_car(
            source_agent="orchestrator",
            destination_service="substrate",
            verb=ActionVerb.READ,
            resource="substrate.vector_store",
            sensitivity="INTERNAL",
        )
        assert car_internal.sensitivity == Sensitivity.INTERNAL

        car_public = build_car(
            source_agent="orchestrator",
            destination_service="substrate",
            verb=ActionVerb.READ,
            resource="substrate.vector_store",
            sensitivity="PUBLIC",
        )
        assert car_public.sensitivity == Sensitivity.PUBLIC

        car_sensitive = build_car(
            source_agent="orchestrator",
            destination_service="substrate",
            verb=ActionVerb.READ,
            resource="substrate.vector_store",
            sensitivity="SENSITIVE",
        )
        assert car_sensitive.sensitivity == Sensitivity.SENSITIVE

    def test_build_car_parameters_schema_propagated(self) -> None:
        """parameters_schema passed to build_car should land on the CAR field
        unchanged. Regression guard: a silent drop of the parameters_schema
        argument would not be caught by any existing test.
        """
        schema = {"arg1": "str", "arg2": "int"}
        car = build_car(
            source_agent="orchestrator",
            destination_service="substrate",
            verb=ActionVerb.EXECUTE,
            resource="skill.calendar",
            sensitivity=Sensitivity.INTERNAL,
            parameters_schema=schema,
        )
        assert car.parameters_schema == schema

    def test_build_car_parameters_schema_defaults_to_empty_dict(self) -> None:
        """When parameters_schema is omitted, build_car maps None to {} so the
        field is always a dict (consistent with the CAR schema default_factory).
        """
        car = build_car(
            source_agent="orchestrator",
            destination_service="substrate",
            verb=ActionVerb.READ,
            resource="substrate.vector_store",
            sensitivity=Sensitivity.INTERNAL,
        )
        assert car.parameters_schema == {}


class TestCARHash:
    """Test deterministic canonical hashing."""

    def test_same_input_same_hash(self) -> None:
        """Identical CARs (ignoring timestamp/request_id) should hash identically."""
        car1 = build_car(
            source_agent="a", destination_service="b",
            verb=ActionVerb.READ, resource="r",
            sensitivity=Sensitivity.PUBLIC,
        )
        car2 = build_car(
            source_agent="a", destination_service="b",
            verb=ActionVerb.READ, resource="r",
            sensitivity=Sensitivity.PUBLIC,
        )
        assert car1.canonical_hash() == car2.canonical_hash()

    def test_different_verb_different_hash(self) -> None:
        """Different verbs should produce different hashes."""
        car_read = build_car(
            source_agent="a", destination_service="b",
            verb=ActionVerb.READ, resource="r",
            sensitivity=Sensitivity.INTERNAL,
        )
        car_write = build_car(
            source_agent="a", destination_service="b",
            verb=ActionVerb.WRITE, resource="r",
            sensitivity=Sensitivity.INTERNAL,
        )
        assert car_read.canonical_hash() != car_write.canonical_hash()


class TestCARCompleteness:
    """Test Fail-Closed completeness checks."""

    def test_incomplete_car_missing_source(self) -> None:
        """CAR with empty source_agent should be incomplete."""
        car = CanonicalActionRepresentation(
            source_agent="",
            destination_service="substrate",
            verb=ActionVerb.READ,
            resource="r",
            sensitivity=Sensitivity.INTERNAL,
            request_id="req-1",
        )
        assert not car.is_complete()

    def test_incomplete_car_missing_request_id(self) -> None:
        """CAR with empty request_id should be incomplete."""
        car = CanonicalActionRepresentation(
            source_agent="orch",
            destination_service="substrate",
            verb=ActionVerb.READ,
            resource="r",
            sensitivity=Sensitivity.INTERNAL,
            request_id="",
        )
        assert not car.is_complete()
