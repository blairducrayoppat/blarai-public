"""
URL-fetch Policy-Agent adjudicator — the UC-003 consumer wiring for the one
egress door (Vikunja #655 sub-task 6c; guarded_fetch registration seam;
ADR-027 Amendment 1).
=============================================================================
:mod:`shared.security.guarded_fetch` is the single sanctioned external-fetch
door, and it ships WITHOUT a built-in Policy-Agent adjudicator — fabricating a
verdict in that leaf module would be a silent open door.  A consumer must wire
the real adjudication at its entry point via ``register_url_adjudicator``.

This module is that consumer wiring for UC-003 URL ingest, and the REUSABLE
CORE of sub-task 6c: it builds the :class:`CanonicalActionRepresentation` for a
URL fetch and maps the Policy Agent's :class:`AdjudicationDecision` onto the
door's local :class:`Verdict`.  The PA call itself is INJECTED
(``PolicyAdjudicateFn``) so this module never imports the GPU Policy Agent —
leaf-level, acyclic, and unit-testable with a fake PA.

WHY IT IS NOT REGISTERED AT IMPORT/STARTUP (binding, ADR-030 §8 + the LA's
go-live reservation): registering a *working* adjudicator is exactly what lets
the door ALLOW a fetch.  The first real outbound GET is the in-person go-live
ceremony — so :func:`register_url_ingest_adjudicator` exists to make that a
single reviewed call, and is deliberately NOT invoked anywhere in the runtime
startup path by this change.  Until it runs, ``guarded_fetch`` denies every
fetch (the fail-closed default); the egress door stays deny-by-default.

The Windows-Hello ESCALATE verifier half of 6c is already wired at launcher
startup (``launcher.__main__`` registers ``BiometricApprovalVerifier``), so a
PA ESCALATE on a URL fetch routes to the operator's fingerprint automatically.
"""

from __future__ import annotations

import logging
import uuid
from typing import Callable

from shared.schemas.car import (
    ActionVerb,
    AdjudicationDecision,
    CanonicalActionRepresentation,
    Sensitivity,
)
from shared.security.guarded_fetch import Verdict

logger = logging.getLogger(__name__)

#: The agent identity recorded on the CAR for an operator-initiated URL fetch.
URL_INGEST_SOURCE_AGENT: str = "uc003_url_ingest"
#: The destination "service" — the external web reached via the one egress door.
URL_INGEST_DESTINATION: str = "external_web"

#: Fetch purposes the door DENIES regardless of the registered adjudicator's
#: verdict, until a SEPARATE image go-live (UC-003 Workstream B; LA decision
#: 2026-06-15, BED-1).  ``fetch_external_binary(purpose="uc003-image-ingest")`` is
#: the only producer (``ingest_coordinator._IMAGE_FETCH_PURPOSE``); kept here as a
#: literal to avoid importing a sibling-module private.  This is the image-SPECIFIC
#: weld lock that SURVIVES text URL-ingest go-live: registering this (shared)
#: adjudicator + the per-URL allowlist the paste-is-consent branch builds release
#: the "adjudicator-not-registered" and "empty-allowlist" locks for the TEXT door,
#: but the image purpose stays denied here.  So the image path remains welded by
#: purpose-deny + ``[knowledge].images_enabled``, independent of text go-live.
#: Lifting a purpose out of this set is part of the image go-live ceremony — never
#: silent.
IMAGE_INGEST_DENY_PURPOSES: frozenset[str] = frozenset({"uc003-image-ingest"})

#: Fetch purposes that carry ADR-027 Amendment 1 semantics — *the paste IS the
#: consent for that ONE URL* — and therefore have their egress allowlist rebuilt
#: PER REQUEST from the request's own URL.  Every other purpose is adjudicated
#: against the STANDING allowlist instead (#1586/#977).
#:
#: **ALLOWLIST, NEVER A BLOCKLIST, and the asymmetry is the whole safety
#: argument.** An unrecognised purpose gets the standing allowlist, which is the
#: restrictive branch; paste-is-consent is reachable only by being named here.
#: Getting that backwards would mean any purpose nobody thought about authorises
#: its own destination — "the model said the operator pasted this".
#:
#: **This is safe only because `purpose` is unforgeable from the model side**, and
#: that is not an assumption: `tests/security/test_purpose_unforgeable.py` proves
#: every runtime path into the door pins a module-level literal, fails CLOSED on
#: any indirection it cannot resolve, and is off-tested against five synthetic
#: forgeries.  If that lock is ever weakened, THIS set is what it was protecting.
PASTE_IS_CONSENT_PURPOSES: frozenset[str] = frozenset({"uc003-url-ingest"})

#: A PA call: given a CAR, return the adjudication decision.  Injected so this
#: module never imports the Policy Agent package at module load (leaf-level +
#: testable).  The production implementation is
#: :func:`make_request_keyed_url_adjudicate` — the in-process
#: ``DeterministicPolicyChecker`` the AO already runs for every tool dispatch
#: (verified pathway; NOT a vsock round-trip — there is no per-CAR client path
#: in the live runtime — and NOT a second in-process ``HybridAdjudicator``,
#: which would load the GPU policy model a second time against the 31 GB
#: ceiling).  It runs the deterministic rule engine + the ADR-027 §2 egress
#: carve-out and returns ALLOW/DENY/ESCALATE.
PolicyAdjudicateFn = Callable[[CanonicalActionRepresentation], AdjudicationDecision]


def build_url_car(url: str, purpose: str) -> CanonicalActionRepresentation:
    """Build the CAR describing an operator-initiated external URL fetch.

    ``verb = EGRESS`` (the canonical off-box verb), ``resource = url`` (action
    metadata the PA reasons over — the destination, never payload content),
    ``sensitivity = PUBLIC`` (a public web page).  A fresh ``request_id``
    correlates the adjudication audit row.  The *purpose* is recorded in the
    parameters schema (a descriptor, not a value).
    """
    return CanonicalActionRepresentation(
        source_agent=URL_INGEST_SOURCE_AGENT,
        destination_service=URL_INGEST_DESTINATION,
        verb=ActionVerb.EGRESS,
        resource=url,
        parameters_schema={"purpose": str(purpose), "method": "GET"},
        sensitivity=Sensitivity.PUBLIC,
        request_id=str(uuid.uuid4()),
    )


def decision_to_verdict(decision: AdjudicationDecision) -> Verdict:
    """Map a PA :class:`AdjudicationDecision` onto the door's local Verdict.

    Total + fail-closed: an unrecognised decision maps to DENY (the door then
    refuses the fetch).
    """
    if decision is AdjudicationDecision.ALLOW:
        return Verdict.ALLOW
    if decision is AdjudicationDecision.ESCALATE:
        return Verdict.ESCALATE
    return Verdict.DENY


def make_url_adjudicator(
    adjudicate: PolicyAdjudicateFn,
) -> Callable[[str, str], Verdict]:
    """Build the ``(url, purpose) -> Verdict`` callable the egress door consults.

    Wraps *adjudicate* (the real in-process Policy Agent at go-live; a fake in
    tests): build the CAR → run the PA → map the decision.  Fail-closed: any
    exception from the PA, or a non-:class:`AdjudicationDecision` return, maps
    to DENY (the door never opens on an error or a malformed verdict).  MUST be
    synchronous and MUST NOT itself perform egress (the door's contract).
    """

    def _adjudicator(url: str, purpose: str) -> Verdict:
        # BED-1 (UC-003 Workstream B image go-live lock; LA decision 2026-06-15):
        # DENY the image-ingest purpose up front — BEFORE the PA is even consulted —
        # so the image door stays welded even after the shared adjudicator is
        # registered for TEXT URL ingest.  The image path's defense-in-depth then
        # rests on this purpose-deny + [knowledge].images_enabled, not on the
        # shared adjudicator-not-registered / empty-allowlist locks that text
        # go-live releases.  Lifting the purpose is part of the image go-live
        # ceremony (see IMAGE_INGEST_DENY_PURPOSES).
        if purpose in IMAGE_INGEST_DENY_PURPOSES:
            logger.warning(
                "url adjudicator: image-ingest purpose %r DENIED — image egress "
                "stays welded until the separate image go-live (BED-1)",
                purpose,
            )
            return Verdict.DENY
        try:
            car = build_url_car(url, purpose)
            decision = adjudicate(car)
        except Exception as exc:  # noqa: BLE001 — a failing PA fails closed
            logger.error(
                "url adjudicator: Policy Agent call raised (%s) — DENY "
                "(fail-closed)",
                type(exc).__name__,
            )
            return Verdict.DENY
        if not isinstance(decision, AdjudicationDecision):
            logger.error(
                "url adjudicator: Policy Agent returned a non-decision (%s) — "
                "DENY (fail-closed)",
                type(decision).__name__,
            )
            return Verdict.DENY
        return decision_to_verdict(decision)

    return _adjudicator


#: **Superseded and REMOVED (#1586/#977):** ``make_deterministic_url_adjudicate``
#: (standing allowlist) and ``make_operator_url_adjudicate`` (paste-is-consent)
#: were two factories competing for ONE first-wins registration slot, so process
#: startup ORDER decided which policy both postures got.
#: :func:`make_request_keyed_url_adjudicate` replaces both by choosing the policy
#: from the request. They are deleted rather than deprecated because a factory
#: with no caller is the shape this project keeps having to re-find, and one of
#: them carried a fail-closed claim its code did not implement (see the
#: no-extractable-host branch below). ADR-027 and the journal record them by name;
#: that history stays accurate about what WAS.


def make_request_keyed_url_adjudicate(
    egress_allowlist: frozenset[str] | None = None,
) -> PolicyAdjudicateFn:
    """The ONE adjudicate fn: the allowlist policy is chosen by the REQUEST (#977).

    **The problem this retires.** There are two correct egress postures, and until
    now which one was live depended on PROCESS STARTUP ORDER.
    :func:`register_url_adjudicator` fills a module-global slot first-wins, and two
    different runtime components fill it: the launcher registered the operator
    "paste is consent" policy, the Assistant Orchestrator registered the standing
    allowlist. Whichever booted first decided the policy for BOTH — so a URL the
    operator pasted could be adjudicated against the web-search host, and a
    web-search fetch could be adjudicated as though the operator had pasted it.
    The runbook recorded that as a governance question about "which adjudicator
    wins". It is not one. It was a wiring accident wearing a policy costume
    (#1586), and the answer a request needs is already IN the request.

    **The discriminator.** ``purpose`` is recorded in the CAR's parameters schema
    by :func:`build_url_car`, and it already gates the image weld a few lines
    above, so keying on it here is precedent rather than novelty.

    * ``purpose`` in :data:`PASTE_IS_CONSENT_PURPOSES` → the allowlist is rebuilt
      from THIS request's own URL using the checker's own host normalisation, so
      an operator paste authorises its own host and nothing else, per adjudication.
    * anything else → the STANDING *egress_allowlist* (``None`` resolves to the
      checker's class default, which ships EMPTY = every URL denied).

    **Deny-by-default, and the direction matters.** The paste-is-consent branch is
    an allowlist of purposes; an unrecognised purpose falls to the STANDING
    allowlist, which is the restrictive side. A missing, non-string or malformed
    purpose does the same. The failure mode of a mistake here is a refused fetch,
    never a widened one.

    **What this rests on.** Paste-is-consent for an arbitrary host is only safe if
    the model cannot choose the purpose that selects it — otherwise the model can
    claim the operator pasted something. That is proved, not assumed:
    ``tests/security/test_purpose_unforgeable.py`` resolves every runtime path into
    the door and requires a pinned module-level literal at each, failing CLOSED on
    any indirection it cannot account for.

    Every other guard is unchanged and still applies in series: the door's SSRF
    validation, GET-only, the per-fetch widen/revoke, the armed egress guard, the
    resolution pin, the injection scan on the body, and the checker's non-egress
    deny/escalate rules. Synchronous and performs no egress, per the door's
    contract.
    """

    def _adjudicate(car: CanonicalActionRepresentation) -> AdjudicationDecision:
        # Lazy import: keep this leaf module free of the Policy Agent package at
        # import time (the checker lives in the PA's gpu_inference module).
        from services.policy_agent.src.gpu_inference import (
            DeterministicPolicyChecker,
        )

        schema = car.parameters_schema or {}
        purpose = schema.get("purpose") if isinstance(schema, dict) else None

        # ONE host extraction, ONE refusal, BOTH branches. The first version of
        # this function refused a hostless resource on the paste branch only —
        # while its own comment explained, at length, why relying on RULE 3 to
        # catch it was wrong. The review found the else branch still doing
        # exactly that (#1586 review, finding 2): measured,
        # `purpose="web_search", resource="not-a-url-at-all"` returned ALLOW.
        #
        # RULE 3 only fires on a resource that STARTS WITH an external-network
        # scheme, so a resource with no scheme skips it entirely and falls
        # through the remaining rules to ALLOW. Nothing is exploitable either way
        # — the door's https-only validation refuses such a resource
        # independently — but writing the argument down and then applying it to
        # half the code is worse than not making it, because the comment now
        # certifies the branch it does not cover.
        host = DeterministicPolicyChecker._egress_host(car.resource)
        if not host:
            logger.warning(
                "url adjudicator: purpose %r on a resource with no extractable "
                "host — DENY (fail-closed; this is the EGRESS door and every "
                "resource reaching it is meant to be a fetchable URL)",
                purpose,
            )
            return AdjudicationDecision.DENY

        if isinstance(purpose, str) and purpose in PASTE_IS_CONSENT_PURPOSES:
            # ADR-027 Am.1: this ONE host, for this ONE adjudication. The
            # checker's own normalisation, so the entry matches byte-for-byte
            # what `check` compares against.
            allowlist = frozenset({host})
        else:
            allowlist = egress_allowlist

        result = DeterministicPolicyChecker.check(car, egress_allowlist=allowlist)
        if result is None:
            return AdjudicationDecision.ALLOW
        decision, _rule = result
        if decision == "ESCALATE":
            return AdjudicationDecision.ESCALATE
        return AdjudicationDecision.DENY

    return _adjudicate


def register_url_ingest_adjudicator(adjudicate: PolicyAdjudicateFn) -> None:
    """Register the URL-fetch adjudicator on the one egress door — GO-LIVE STEP.

    NOT called at import or startup by design (see the module docstring):
    registration is the FIRST go-live lock.  Even after registration the door
    stays shut while the deterministic checker's egress allowlist is empty —
    RULE 3 denies every URL — so opening the door is the SEPARATE governance act
    of populating that allowlist (ADR-027 Amendment 1).  Until this runs,
    ``guarded_fetch`` denies every fetch (the fail-closed default).
    """
    from shared.security.guarded_fetch import register_url_adjudicator

    register_url_adjudicator(make_url_adjudicator(adjudicate))
    logger.warning(
        "url adjudicator: REGISTERED on the egress door — external URL fetches "
        "now route to the Policy Agent for an ALLOW/DENY/ESCALATE verdict. "
        "Whether any URL is permitted still depends on the deterministic egress "
        "allowlist (empty = every URL denied; ADR-027 §2/Amendment 1)."
    )
