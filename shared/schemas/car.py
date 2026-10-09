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


class ActionCategory(str, Enum):
    """Coarse class of what an action DOES (#1545, from CAVA's ``category``).

    Distinct from :class:`ActionVerb`, which says how the action is *performed*.
    Two actions can share a verb and differ entirely in category: ``EXECUTE
    tool:calculate`` and ``EXECUTE tool:web_search`` are both EXECUTE, and only
    one of them leaves the machine.

    ``UNKNOWN`` is the default and means **not yet classified**, never "harmless".
    Any rule that comes to read this field must treat UNKNOWN as it would treat
    the most restrictive value — deny-by-default (security_by_design principle 2).
    Nothing adjudicates on it today; it contributes to ``canonical_hash()`` so the
    approval binding in #1541 covers it from the start.
    """

    UNKNOWN = "UNKNOWN"
    COMPUTE = "COMPUTE"
    """Pure local computation with no store and no egress (``calculate``, clocks)."""
    RETRIEVE = "RETRIEVE"
    """Reads on-box operator data (``search_knowledge``)."""
    GENERATE = "GENERATE"
    """Produces a local artifact (``generate_image``)."""
    MUTATE = "MUTATE"
    """Changes on-box state the operator owns."""
    EGRESS = "EGRESS"
    """Leaves the machine. The only category whose blast radius is not local."""


class Reversibility(str, Enum):
    """Whether the action's effect can be undone (#1545, from CAVA's ``reversible``).

    ``UNKNOWN`` is the default and is **not** a synonym for reversible. An action
    whose reversibility has never been classified must be treated as IRREVERSIBLE
    by any rule that reads this, for the same reason ``Sensitivity`` has no
    permissive default: a silent misclassification here is the expensive kind.
    """

    UNKNOWN = "UNKNOWN"
    REVERSIBLE = "REVERSIBLE"
    """The operator can undo the effect (a generated image is a deletable file)."""
    IRREVERSIBLE = "IRREVERSIBLE"
    """Cannot be undone once performed — an egress has happened, a secure-delete
    has zeroed rows. This is the property that earns an action a dry run (#1548)."""


class Sensitivity(str, Enum):
    """Payload sensitivity classification.

    The Policy Agent's probabilistic classifier refines this after the
    deterministic rule engine sets a baseline.
    """

    PUBLIC = "PUBLIC"
    INTERNAL = "INTERNAL"
    SENSITIVE = "SENSITIVE"
    UNCLASSIFIED = "UNCLASSIFIED"


# Fields deliberately EXCLUDED from ``canonical_hash()``. Two requests for the
# same action must hash identically or the Hello envelope's N=3 approval lease
# (LA decision 2026-07-02) breaks silently, so these three stay out.
#
# Every OTHER model field must be inside the hash. That is asserted by
# ``tests/security/test_car_externality_fields.py`` against
# ``model_fields`` — a new field is hashed or the gate fails.
VOLATILE_FIELDS: frozenset[str] = frozenset({"timestamp", "request_id", "session_id"})


class CanonicalActionRepresentation(BaseModel):
    """Normalized representation of an inter-agent action request.

    **Two classes of field, and the difference is load-bearing.**

    The *identity* fields — ``source_agent``, ``destination_service``, ``verb``,
    ``resource``, ``sensitivity`` — are REQUIRED. Missing ones cause fail-closed
    rejection via :meth:`is_complete`; the Policy Agent will not adjudicate an
    incomplete CAR.

    The *externality* fields added by #1545 — ``category``, ``systems_touched``,
    ``reversible``, ``target`` — are OPTIONAL and default to UNKNOWN-equivalents.
    They are **not** in :meth:`is_complete`. Making them required would
    fail-closed every existing construction site the moment they landed, which
    is a capability change wearing a schema change. The cost of that choice is
    real and is stated here rather than left for a reader to discover: until the
    construction sites populate them, a CAR asserts nothing about its own
    externality, and a default must be read as *unclassified*, never as
    *harmless*.

    Both classes are inside :meth:`canonical_hash`, because #1541 binds an
    operator's approval to that hash.
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

    # --- Externality (#1545; CAVA `category` / `systems_touched` / `reversible`
    # / `target`, lifted into first-class fields so the action hash means more) ---
    #
    # All four default to an UNKNOWN-equivalent rather than being required,
    # DELIBERATELY: making them required would fail-closed every existing CAR
    # construction site the moment this merges, which is a capability change
    # wearing a schema change. They are NOT in ``is_complete()`` for the same
    # reason. What they DO enter is ``canonical_hash()``, so the approval binding
    # #1541 adds covers them from its first commit rather than being retrofitted.
    #
    # The default is a gap, and it is named here so nobody mistakes it for a
    # guarantee: until the construction sites populate these, a CAR says only
    # "unclassified", and any future rule reading them must treat the default as
    # the most restrictive value.
    category: ActionCategory = Field(
        default=ActionCategory.UNKNOWN,
        description="Coarse class of what the action does. UNKNOWN means unclassified, never harmless.",
    )
    systems_touched: tuple[str, ...] = Field(
        default=(),
        description=(
            "Sorted, de-duplicated identifiers of the systems this action reaches "
            "(e.g. 'knowledge_bank', 'filesystem', 'network'). Empty means "
            "unclassified, not 'touches nothing'."
        ),
    )
    reversible: Reversibility = Field(
        default=Reversibility.UNKNOWN,
        description="Whether the effect can be undone. UNKNOWN is not a synonym for REVERSIBLE.",
    )
    target: str = Field(
        default="",
        description=(
            "Reserved for a second-level instance identifier. UNPOPULATED and "
            "NOT YET the destination — see the precedence note below. A selector "
            "rather than a value; never payload content."
        ),
    )
    # PRECEDENCE, because two fields can now look like 'the destination' and a
    # docstring that guessed wrong would mislead the operator prompt #1541 builds:
    #
    #   `resource` IS THE DESTINATION TODAY, including for egress.
    #
    # The one production site that builds an egress CAR —
    # services/ui_gateway/src/url_adjudicator.py — puts the full URL in
    # `resource`, and the AO's _adjudicate_tool_dispatch puts KAGI_SEARCH_ENDPOINT
    # there too. `target` is empty everywhere. An earlier version of this comment
    # claimed `resource` "names the KIND" while `target` carries the instance;
    # that describes neither the code nor the project's own measured vocabulary
    # screen, and is withdrawn (#1545 review finding 4).
    #
    # Deciding whether `target` ever takes that role is #1541's business, because
    # #1541 is what shows an operator the thing being approved, and showing them
    # two destination-shaped fields is worse than showing them one.

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

        #1545 added ``category``, ``systems_touched``, ``reversible`` and
        ``target``. They are inside the hash on purpose: #1541 binds an operator's
        approval to this value and re-derives it immediately before
        ``tools.execute``, so anything NOT covered here is something an approval
        cannot be made to mean. Adding them later, after approvals were already
        binding, would have required re-proving the binding against new fixtures —
        which is exactly why #1545 is sequenced before #1541.

        **This changes the hash of an otherwise identical action**, and that is
        safe here for one reason worth stating rather than assuming: the audit
        chain stores ``car_hash`` as an OPAQUE string and never recomputes it
        (``shared/security/audit_log.py::_canonical_bytes`` builds its dict from
        thirteen explicitly named keys), so no existing record's canonical bytes
        change and ``verify()`` still passes over every old segment. The
        compatibility question that DOES bite is #1542's, which adds fields to the
        record itself.

        ``systems_touched`` is sorted before hashing so two CARs describing the
        same action cannot differ by list order alone — an unsorted sequence here
        would make the approval binding rejectable by argument shuffling.
        """
        hashable = json.dumps(
            self._hashable_payload(),
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(hashable.encode("utf-8")).hexdigest()

    def _hashable_payload(self) -> dict[str, Any]:
        """The exact mapping :meth:`canonical_hash` serialises.

        Extracted so a test can compare its KEY SET against
        ``CanonicalActionRepresentation.model_fields`` minus
        :data:`VOLATILE_FIELDS` and fail when a new field is added to the model
        without being hashed.

        The parametrised per-field tests cannot do that job: their list is
        hand-maintained, so the person who forgets to hash a new field is the
        same person who would have to remember to add its row. An adversarial
        review of #1545 falsified exactly that claim by adding a fifth field and
        watching the whole suite stay green. This method is what makes the
        property structural instead of aspirational.
        """
        return {
            "source_agent": self.source_agent,
            "destination_service": self.destination_service,
            "verb": self.verb.value,
            "resource": self.resource,
            "parameters_schema": self.parameters_schema,
            "sensitivity": self.sensitivity.value,
            "category": self.category.value,
            # sorted(set(...)) is INJECTIVE ON SETS — it normalises order and
            # duplicates and nothing else. Any weakening here (taking the first
            # element, taking a length, case-folding) collapses distinct system
            # sets onto one hash and would let an approval for a local read
            # cover a network egress.
            "systems_touched": sorted(set(self.systems_touched)),
            "reversible": self.reversible.value,
            "target": self.target,
        }

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
