"""
CAR Ingestion — Policy Agent
==============================
USE-CASE-001: Receives raw inter-agent action requests and normalizes
them into Canonical Action Representations (CARs).

This module is the ingestion front-end. It validates incoming requests,
constructs CanonicalActionRepresentation instances, and feeds them to
the adjudication pipeline.

Security:
  - Incomplete CARs are Fail-Closed DENIED.
  - No raw user data enters the CAR — only action metadata.
"""

from __future__ import annotations

import uuid
from typing import Any

from shared.schemas.car import (
    ActionVerb,
    CanonicalActionRepresentation,
    Sensitivity,
)


def build_car(
    source_agent: str,
    destination_service: str,
    verb: ActionVerb | str,
    resource: str,
    sensitivity: Sensitivity | str,
    parameters_schema: dict[str, Any] | None = None,
    session_id: str = "",
) -> CanonicalActionRepresentation:
    """Construct a validated CAR from raw request fields.

    Args:
        source_agent: mTLS Common Name of the requesting agent.
        destination_service: Target microservice identifier.
        verb: Canonical action verb (string or enum).
        resource: Target resource identifier.
        sensitivity: Declared payload sensitivity (required — no default to prevent silent misclassification).
        parameters_schema: JSON Schema of action parameters.
        session_id: Multi-turn session ID (empty for stateless).

    Returns:
        A validated CanonicalActionRepresentation.

    Note:
        Fail-Closed: if the CAR is incomplete (is_complete() returns False),
        the adjudicator will reject it. This function does not raise.
    """
    # Normalize string verb/sensitivity to enums
    if isinstance(verb, str):
        verb = ActionVerb(verb.upper())
    if isinstance(sensitivity, str):
        sensitivity = Sensitivity(sensitivity.upper())

    return CanonicalActionRepresentation(
        source_agent=source_agent,
        destination_service=destination_service,
        verb=verb,
        resource=resource,
        parameters_schema=parameters_schema or {},
        sensitivity=sensitivity,
        request_id=str(uuid.uuid4()),
        session_id=session_id,
    )
