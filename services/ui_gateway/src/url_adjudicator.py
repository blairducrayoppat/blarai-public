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
#: adjudicator + the operator factory's per-URL allowlist self-population release
#: the "adjudicator-not-registered" and "empty-allowlist" locks for the TEXT door,
#: but the image purpose stays denied here.  So the image path remains welded by
#: purpose-deny + ``[knowledge].images_enabled``, independent of text go-live.
#: Lifting a purpose out of this set is part of the image go-live ceremony — never
#: silent.
IMAGE_INGEST_DENY_PURPOSES: frozenset[str] = frozenset({"uc003-image-ingest"})

#: A PA call: given a CAR, return the adjudication decision.  Injected so this
#: module never imports the Policy Agent package at module load (leaf-level +
#: testable).  The production implementation is
#: :func:`make_deterministic_url_adjudicate` — the in-process
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


def make_deterministic_url_adjudicate(
    egress_allowlist: frozenset[str] | None = None,
) -> PolicyAdjudicateFn:
    """The production PA adjudicate function for URL fetches — in-process.

    Runs the CAR through ``services.policy_agent.src.gpu_inference.
    DeterministicPolicyChecker.check`` — the SAME deterministic rule engine the
    AO already runs for every tool dispatch
    (``assistant_orchestrator.src.entrypoint._adjudicate_tool_dispatch``).  This
    is the verified-correct pathway: NOT a vsock round-trip to the PA service
    (the live runtime has no per-CAR client path) and NOT a second in-process
    ``HybridAdjudicator`` (which would load the GPU policy model a second time —
    untenable against the 31 GB memory ceiling).

    THE DOOR-OPENING KNOB is *egress_allowlist* — the ADR-027 §2 egress
    carve-out, already built and STAGED/DORMANT in the checker.  RULE 3
    (``DENY_EXTERNAL_NETWORK``) denies every external URL UNLESS its host is in
    this allowlist, in which case the checker auto-approves (``check`` returns
    ``None`` → ALLOW).  The live default ``None`` resolves to the checker's
    EMPTY class allowlist → **every URL denied** (the air-gap stays welded).
    Populating the allowlist for an operator-directed fetch is the governance
    act of opening the door — owned by the LA via ADR-027 Amendment 1, NOT
    decided here.  This function only adapts whatever policy the allowlist
    expresses onto the door's :class:`Verdict`.

    Decision mapping (fail-closed): ``None`` (no deny/escalate rule fired —
    allowlisted host) → ALLOW; ``("ESCALATE", rule)`` → ESCALATE; anything else
    (``("DENY", rule)``) → DENY.  Synchronous + performs no egress (the door's
    contract), so it is safe to call from inside ``guarded_fetch.fetch_external``.
    """

    def _adjudicate(car: CanonicalActionRepresentation) -> AdjudicationDecision:
        # Lazy import: keep this leaf module free of the Policy Agent package at
        # import time (the checker lives in the PA's gpu_inference module).
        from services.policy_agent.src.gpu_inference import (
            DeterministicPolicyChecker,
        )

        result = DeterministicPolicyChecker.check(
            car, egress_allowlist=egress_allowlist
        )
        if result is None:
            return AdjudicationDecision.ALLOW
        decision, _rule = result
        if decision == "ESCALATE":
            return AdjudicationDecision.ESCALATE
        return AdjudicationDecision.DENY

    return _adjudicate


def make_operator_url_adjudicate() -> PolicyAdjudicateFn:
    """The LIVE operator "URL = authorization" adjudicate fn (ADR-027 Amendment 1).

    This is ADR-027 Amendment 1 — "the paste IS the consent for that ONE URL" —
    made literal for the live runtime.  There is NO autonomous caller of the
    egress door: a URL fetch happens ONLY because the operator pasted a URL into
    ``/ingest <url>``.  So each operator-pasted URL authorizes ONLY its own host,
    and ONLY for that one adjudication — the allowlist is rebuilt per-CAR from the
    CAR's own URL, never a fixed standing host.  A second URL on a different host,
    adjudicated by the SAME registered adjudicator, authorizes ITS host and not the
    first one's (proven per-CAR, not a stuck allowlist).

    Mechanics (zero normalization drift): the host is extracted from the CAR's URL
    using the checker's OWN normalization
    (``DeterministicPolicyChecker._egress_host``), so the host this function puts
    in the one-entry allowlist matches byte-for-byte the host the checker compares
    against inside ``check`` (no divergence between "what we allowed" and "what the
    rule engine sees").  A non-web / unparseable resource yields ``None`` →
    ``frozenset()`` (empty) → RULE 3 (``DENY_EXTERNAL_NETWORK``) denies it
    (fail-closed: an operator paste that is not a fetchable https/http URL is
    refused, never silently allowed).

    Every OTHER guard is UNCHANGED and still applies in series:
      * the door's SSRF guard (https-only, no userinfo, no raw-IP host, no
        internal-resolving host) in :func:`shared.security.guarded_fetch._validate_url`
        + :func:`...._resolution_blocked_reason`;
      * GET-only + the per-fetch widen/revoke + the armed egress guard + the W4
        resolution pin in ``_fetch_body``;
      * the ADR-013 injection scan on the returned body;
      * and the checker's NON-egress deny/escalate rules (restricted paths,
        exfiltration, authority claims, cross-agent ownership, etc.) — those fire
        on the CAR exactly as for any other action, regardless of the one-host
        egress allowlist.

    Synchronous + performs NO egress (the door's contract — safe to call from
    inside ``guarded_fetch.fetch_external``).  Returns the PA decision
    (ALLOW/DENY/ESCALATE) for :func:`make_url_adjudicator` to map onto a Verdict.
    """

    def _adjudicate(car: CanonicalActionRepresentation) -> AdjudicationDecision:
        # Lazy import: keep this leaf module free of the Policy Agent package at
        # import time (the checker lives in the PA's gpu_inference module).
        from services.policy_agent.src.gpu_inference import (
            DeterministicPolicyChecker,
        )

        # The paste IS the consent for THIS one host: build a one-entry allowlist
        # from the CAR's own URL, using the checker's OWN host normalization so the
        # allowlist entry matches the host the rule engine compares against inside
        # check() (zero normalization drift).  A non-web / unparseable resource ->
        # None -> empty allowlist -> RULE 3 DENY (fail-closed).
        host = DeterministicPolicyChecker._egress_host(car.resource)
        allowlist = frozenset({host}) if host else frozenset()

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
