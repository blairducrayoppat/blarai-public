"""
Canonical Action Representation (CAR) Schema
=============================================
USE-CASE-001: Policy Agent — Action Authorization Boundary

Every inter-agent tool call is reduced to a CAR before the Policy Agent
adjudicates it. The CAR is the lingua franca of the Action Authorization
Boundary (AAB). Both the deterministic rule engine and the NPU-resident
probabilistic classifier consume CARs.

A CAR is:
  1. A normalized, hashable representation of an agent's requested action.
  2. Transport-agnostic — the same CAR is produced regardless of whether
     the request arrived via vsock, in-process call, or test harness.
  3. Deterministically serializable for audit logging.

Privacy: CARs never contain raw user data. They contain action metadata
(verb, resource, destination, parameters schema) sufficient for the
Policy Agent to adjudicate intent without seeing payload content.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class ActionVerb(str, Enum):
    """Canonical action verbs for the CAR schema.

    Extensible — new verbs require Policy Agent rule engine updates.
    """

    READ = "READ"
    WRITE = "WRITE"
    EXECUTE = "EXECUTE"
    DELETE = "DELETE"
    QUERY = "QUERY"
    DISPATCH = "DISPATCH"
    EGRESS = "EGRESS"


class Sensitivity(str, Enum):
    """Payload sensitivity classification.

    The Policy Agent's probabilistic classifier refines this after the
    deterministic rule engine sets a baseline.
    """

    PUBLIC = "PUBLIC"
    INTERNAL = "INTERNAL"
    SENSITIVE = "SENSITIVE"
    UNCLASSIFIED = "UNCLASSIFIED"


class CanonicalActionRepresentation(BaseModel):
    """Normalized representation of an inter-agent action request.

    All fields are required. Missing fields cause Fail-Closed rejection —
    the Policy Agent will not adjudicate incomplete CARs.
    """

    # --- Identity ---
    source_agent: str = Field(
        ...,
        description="Cryptographic identity of the requesting agent (mTLS CN).",
    )
    destination_service: str = Field(
        ...,
        description="Target microservice for the action.",
    )

    # --- Action ---
    verb: ActionVerb = Field(
        ...,
        description="Canonical action verb.",
    )
    resource: str = Field(
        ...,
        description="Target resource identifier (e.g., 'substrate.vector_store', 'skill.calendar').",
    )
    parameters_schema: dict[str, Any] = Field(
        default_factory=dict,
        description="JSON Schema of the action parameters (not the values — the schema).",
    )

    # --- Classification ---
    sensitivity: Sensitivity = Field(
        ...,
        description="Declared payload sensitivity. UNCLASSIFIED triggers Fail-Closed. Must be set explicitly — no default prevents silent misclassification.",
    )

    # --- Metadata ---
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="UTC timestamp of CAR creation.",
    )
    request_id: str = Field(
        ...,
        description="Unique request identifier for audit trail correlation.",
    )
    session_id: str = Field(
        default="",
        description="Session identifier for multi-turn context (empty for stateless).",
    )

    def canonical_hash(self) -> str:
        """Produce a deterministic SHA-256 hash of this CAR.

        The hash covers identity + action fields only (not timestamp/request_id)
        to enable deduplication and replay detection.
        """
        hashable = json.dumps(
            {
                "source_agent": self.source_agent,
                "destination_service": self.destination_service,
                "verb": self.verb.value,
                "resource": self.resource,
                "parameters_schema": self.parameters_schema,
                "sensitivity": self.sensitivity.value,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(hashable.encode("utf-8")).hexdigest()

    def is_complete(self) -> bool:
        """Check whether this CAR has all required fields populated.

        Incomplete CARs are Fail-Closed rejected.
        """
        return bool(
            self.source_agent
            and self.destination_service
            and self.resource
            and self.request_id
        )


class AdjudicationDecision(str, Enum):
    """Policy Agent adjudication outcomes."""

    ALLOW = "ALLOW"
    DENY = "DENY"
    ESCALATE = "ESCALATE"


class DecisionArtifact(BaseModel):
    """Agentic JWT payload — the unforgeable receipt of adjudication.

    Minted by the Policy Agent after hybrid adjudication (deterministic +
    probabilistic). Destination microservices validate this before executing
    any request.
    """

    car_hash: str = Field(
        ...,
        description="SHA-256 of the adjudicated CAR.",
    )
    decision: AdjudicationDecision = Field(
        ...,
        description="Adjudication outcome.",
    )
    request_id: str = Field(
        ...,
        description="Correlates to the originating CAR.",
    )
    deterministic_pass: bool = Field(
        ...,
        description="Whether the deterministic rule engine approved.",
    )
    probabilistic_pass: bool = Field(
        ...,
        description="Whether the NPU probabilistic classifier approved.",
    )
    confidence: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Probabilistic classifier confidence score.",
    )
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
    )
    expiry_seconds: int = Field(
        default=5,
        description="JWT validity window in seconds (Use Cases §3: 5s hard TTL).",
    )
    issuer: str = Field(
        default="policy_agent",
        description="Issuer identity (always the Policy Agent).",
    )
