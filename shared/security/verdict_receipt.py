"""Verdict receipts: the tamper-evident record every adjudication door writes.

#1542 Gap B. The two live doors — the AO tool-dispatch adjudicator and the
guarded-fetch egress door — previously recorded allow/deny/escalate with the
application logger alone. A refusal, which is the most security-relevant event
either door produces, left nothing a later reader could verify. This module
defines what they write instead, and the receipt goes into the signed,
hash-chained ``AuditLog`` beside the ingest records already there.

Vocabulary from ``docs/research/acs-vocabulary-adoption-design-2026-09-16.md``
(sections "The receipt" and "The five items").

Design constraints, each of which is enforced below rather than asserted:

* **DENY-BY-DEFAULT ON THE FIELD SET.** ``build_receipt`` accepts exactly the
  thirteen names in ``RECEIPT_FIELDS`` and refuses anything else. A door cannot
  smuggle a new field into the signed bytes by passing it, and a field added
  here is a deliberate schema change that versions the canonicalisation.
* **NO PAYLOAD IN ANY FIELD.** Every value is a short identifier, never
  content: values are length-capped and must be ``str``/``bool``/``None``.
  A receipt is a statement that a decision happened, not a copy of what was
  decided about. The full URL at the egress door contributes through
  ``input_identity`` only; ``resource`` carries the host.
* **RESERVED NAMESPACES ARE NOT INVENTABLE.** ``host_error:*`` and
  ``runtime_error:*`` belong to the Agent Hooks specification. A reason inside
  either prefix must be one the suites actually name; anything else is a host
  inventing vocabulary it does not own, and is refused here at construction
  rather than caught later by a tree scan.
* **THE TWO IDENTITIES MUST AGREE.** ``input_identity`` is what was adjudicated
  and ``enforced_identity`` is what the decision was applied to. They are equal
  by construction in a correct door; a mismatch means the action changed between
  the ruling and its enforcement, which is the #1541 Gap A defect, so it refuses.
"""

from __future__ import annotations

from typing import Any, Final, Mapping

# ---------------------------------------------------------------------------
# Vocabulary
# ---------------------------------------------------------------------------

ACS_VOCABULARY_VERSION: Final[str] = "agent-hooks/1.0"
"""The specification version whose vocabulary these receipts use.

Carried in every receipt so a later reader can tell which vocabulary a record
was written against, rather than inferring it from the record's age.
"""

RESERVED_PREFIXES: Final[tuple[str, ...]] = ("host_error:", "runtime_error:")
"""Reason prefixes the specification owns. A host may not invent inside them."""

KNOWN_RESERVED_REASONS: Final[frozenset[str]] = frozenset(
    {
        "host_error:approval_identity_mismatch",
        "host_error:approval_resolver_failed",
        "host_error:composition_disagreement",
        "host_error:context_invalid",
        "host_error:interceptor_failed",
        "host_error:no_interceptor",
        "host_error:streaming_unsupported",
        "host_error:transform_conflict",
        "host_error:transform_invalid",
        "host_error:transform_target_forbidden",
        "host_error:verdict_invalid",
        "runtime_error:intervention_point_unknown",
        "runtime_error:policy_invocation_failed",
        "runtime_error:policy_output_invalid",
        "runtime_error:resource_limit_exceeded",
        "runtime_error:tool_unknown",
        "runtime_error:transform_target_forbidden",
    }
)
"""The seventeen identifiers the two ACS suites name.

This module is the runtime owner of the list, and
``tests/security/test_acs_vocabulary_alignment.py`` IMPORTS it rather than
keeping a second copy — two hand-maintained copies drift, and the one that
drifts permissively is the one nobody notices. Adding an entry means a suite
added one: say which suite version, in the same change.
"""

INTERVENTION_POINTS: Final[frozenset[str]] = frozenset(
    {"pre_tool_call", "output"}
)
"""The points BlarAI adjudicates at. ``pre_tool_call`` covers both live doors;
``output`` is the post-generation screen (PGOV)."""

DECISIONS: Final[frozenset[str]] = frozenset({"allow", "deny"})
"""A receipt records a binary outcome. An escalation that the operator approved
is ``allow`` with ``approval_outcome="approved"``; one they refused, or that was
never answered, is ``deny``. 'Escalate' is a route, not a verdict."""

SOURCE_DOORS: Final[frozenset[str]] = frozenset(
    {"ao_tool_dispatch", "guarded_fetch_egress", "pgov_output"}
)
"""Which door wrote the receipt. Deny-by-default: a door not named here cannot
write, so a new adjudication point is a deliberate addition and not a surprise
in the chain."""

RECEIPT_FIELDS: Final[tuple[str, ...]] = (
    "acs_vocabulary_version",
    "intervention_point",
    "mode",
    "decision",
    "liftable",
    "reason",
    "error_class",
    "detail",
    "input_identity",
    "enforced_identity",
    "approval_outcome",
    "approver_identity",
    "source_door",
)
"""The exact field set. Order is irrelevant to the hash (the canonical bytes
sort keys) but fixed here so the schema is readable in one place."""

_MAX_VALUE_LEN: Final[int] = 200
"""Cap for every string value except ``detail``.

This is the no-payload control with teeth. Identifiers, rule names, hashes and
host names all fit comfortably; a tool argument, a prompt or a fetched body does
not. A value over the cap REFUSES rather than truncating, because a silently
truncated payload is still a payload and a truncation that passes is a control
that degraded quietly."""

_MAX_DETAIL_LEN: Final[int] = 300
"""Slightly larger cap for ``detail``, which carries a short human-readable
clause. Still far below anything that could hold content."""

_IDENTITY_PREFIX: Final[str] = "sha256:"
_IDENTITY_LEN: Final[int] = len(_IDENTITY_PREFIX) + 64


class ReceiptError(ValueError):
    """A receipt could not be built. Always fatal to the write, never a warning.

    A door that cannot construct its receipt has not proved its decision, and
    fail-closed means the door refuses rather than proceeding unrecorded.
    """


def _check_identity(name: str, value: str) -> None:
    """A ``sha256:``-prefixed CAR hash, or the empty string.

    Empty is permitted only for ``approver_identity`` (no approver) and is
    rejected for the two action identities by :func:`build_receipt`, because an
    action identity that could not be derived is a mismatch and never a pass.
    """
    if value == "":
        return
    if len(value) != _IDENTITY_LEN or not value.startswith(_IDENTITY_PREFIX):
        raise ReceiptError(
            f"{name} is not a canonical action identity: expected "
            f"{_IDENTITY_PREFIX!r} + 64 hex characters, got {len(value)} characters"
        )
    if any(c not in "0123456789abcdef" for c in value[len(_IDENTITY_PREFIX):]):
        raise ReceiptError(f"{name} contains non-lowercase-hex characters")


def _check_reason(reason: str) -> None:
    """Refuse an invented identifier inside a reserved namespace."""
    for prefix in RESERVED_PREFIXES:
        if reason.startswith(prefix):
            if reason not in KNOWN_RESERVED_REASONS:
                raise ReceiptError(
                    f"reason {reason!r} invents an identifier in the reserved "
                    f"namespace {prefix!r}, which the Agent Hooks specification "
                    "owns. Use one of the seventeen it names, or a BlarAI rule "
                    "name outside the reserved prefixes."
                )
            return


def build_receipt(
    *,
    intervention_point: str,
    decision: str,
    source_door: str,
    reason: str,
    input_identity: str,
    enforced_identity: str,
    liftable: bool,
    error_class: str = "",
    detail: str = "",
    approval_outcome: str = "",
    approver_identity: str = "",
) -> dict[str, Any]:
    """Build one validated receipt, or raise.

    Every argument is checked before anything is returned, so a door either
    holds a complete valid receipt or holds nothing. There is no partial form.

    Args:
        intervention_point: One of :data:`INTERVENTION_POINTS`.
        decision: ``"allow"`` or ``"deny"``. See :data:`DECISIONS` for why an
            escalation is not a third value.
        source_door: One of :data:`SOURCE_DOORS`.
        reason: A BlarAI rule name, or one of :data:`KNOWN_RESERVED_REASONS`.
        input_identity: ``"sha256:"`` + a 64-hex digest identifying what was
            adjudicated. At the dispatch door that is the CAR's
            ``canonical_hash()``. At the egress door it is a fetch identity over
            ``(purpose, url)``, because ``guarded_fetch`` has no CAR to hash.
            The shapes are identical and the values are NOT interchangeable, so
            a reader correlating the doors must use ``source_door`` to know which
            it is holding. :func:`_check_identity` validates shape only.
        enforced_identity: The same, for what the decision was applied to.
        liftable: Whether an operator could lift this refusal at all. A
            structural denial (an empty allowlist, a barred tool) is NOT
            liftable and saying so is what stops an operator hunting for a
            prompt that never comes.
        error_class: Specification error class, when the decision came from an
            error rather than a rule.
        detail: One short human-readable clause. Never content.
        approval_outcome: ``"approved"`` / ``"refused"`` / ``"unanswered"`` /
            ``""`` when the action never reached an operator.
        approver_identity: The VERIFIER label that established consent, never
            who the operator is. BlarAI has one operator; recording an identity
            here would be recording a person, and the receipt does not need it.

    Returns:
        A new ``dict`` with exactly :data:`RECEIPT_FIELDS` as its keys.

    Raises:
        ReceiptError: On any invalid or over-long value. Fail-closed.
    """
    if intervention_point not in INTERVENTION_POINTS:
        raise ReceiptError(
            f"intervention_point {intervention_point!r} is not one of "
            f"{sorted(INTERVENTION_POINTS)}"
        )
    if decision not in DECISIONS:
        raise ReceiptError(
            f"decision {decision!r} is not one of {sorted(DECISIONS)}. An "
            "escalation is a route to an operator, not a verdict: record the "
            "outcome it reached."
        )
    if source_door not in SOURCE_DOORS:
        raise ReceiptError(
            f"source_door {source_door!r} is not a registered adjudication door "
            f"({sorted(SOURCE_DOORS)}). Adding a door is a deliberate change."
        )
    if not reason:
        raise ReceiptError(
            "reason is empty. A verdict with no stated reason is not auditable, "
            "which is the defect this receipt exists to close."
        )
    _check_reason(reason)

    _check_identity("input_identity", input_identity)
    _check_identity("enforced_identity", enforced_identity)
    if not input_identity or not enforced_identity:
        raise ReceiptError(
            "input_identity and enforced_identity are both required. An identity "
            "that could not be derived is a mismatch, never a pass (#1541 Gap A)."
        )
    if input_identity != enforced_identity:
        raise ReceiptError(
            "input_identity != enforced_identity: the action adjudicated is not "
            "the action enforced. This is the #1541 Gap A defect and the door "
            "must refuse rather than record a receipt for two different actions."
        )
    _check_identity("approver_identity", approver_identity)

    receipt: dict[str, Any] = {
        "acs_vocabulary_version": ACS_VOCABULARY_VERSION,
        "intervention_point": intervention_point,
        "mode": "enforce",
        "decision": decision,
        "liftable": bool(liftable),
        "reason": reason,
        "error_class": error_class,
        "detail": detail,
        "input_identity": input_identity,
        "enforced_identity": enforced_identity,
        "approval_outcome": approval_outcome,
        "approver_identity": approver_identity,
        "source_door": source_door,
    }

    # The no-payload control. Applied to the ASSEMBLED receipt rather than to
    # each argument, so a field added to the literal above cannot skip it.
    if set(receipt) != set(RECEIPT_FIELDS):
        raise ReceiptError(
            "receipt field set does not match RECEIPT_FIELDS: "
            f"{sorted(set(receipt) ^ set(RECEIPT_FIELDS))}. The canonicalisation "
            "is versioned against this set; changing it is a schema change."
        )
    for key, value in receipt.items():
        if isinstance(value, bool):
            continue
        if not isinstance(value, str):
            raise ReceiptError(
                f"{key} is {type(value).__name__}, not str or bool. A receipt "
                "carries identifiers, never structured content."
            )
        cap = _MAX_DETAIL_LEN if key == "detail" else _MAX_VALUE_LEN
        if len(value) > cap:
            raise ReceiptError(
                f"{key} is {len(value)} characters, over the {cap}-character cap. "
                "A receipt states that a decision happened; it does not carry "
                "what was decided about. Pass an identifier, not content."
            )
    return receipt


def canonical_receipt(receipt: Mapping[str, Any]) -> dict[str, Any]:
    """Normalise a receipt for hashing: EVERY key present, not a known subset.

    Read back from disk a record's receipt is untrusted JSON, so this function
    decides what a forged key does to verification. It hashes the mapping as it
    actually is, which means adding, removing or altering any key — known or
    not — changes the canonical bytes and the stored ``record_hash`` then fails
    to match. A tamper is DETECTED.

    The first version of this function filtered to :data:`RECEIPT_FIELDS` and
    claimed in this docstring that an unknown key would therefore be caught.
    That was false and measured false within the hour: filtering makes the extra
    key invisible to the hash, so a receipt carrying ``"smuggled": "payload"``
    verified clean and any reader of the record saw a field nothing had signed.
    Ignoring an attacker's input is not the same as rejecting it.

    Values are normalised to ``str``/``bool`` so the bytes are deterministic;
    anything else stringifies rather than raising, because a verifier's job is
    to report that a record does not verify, never to crash on a malformed one.
    """
    return {
        str(key): (value if isinstance(value, (str, bool)) else str(value))
        for key, value in receipt.items()
    }
