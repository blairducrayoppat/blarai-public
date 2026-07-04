r"""Turn-scoped egress consent envelope (ADR-023 Amendment 4, #723 rung 3).

The human-consent layer in FRONT of every model-initiated outbound (egress) tool
call. It replaces the per-session ``/trust`` blanket for egress tools with a
**turn-scoped Windows-Hello envelope**:

  * The Hello fingerprint fires on the **FIRST egress of a user turn**, showing
    that first query and the envelope bound ("up to N searches for this
    question"; N a small configurable default).
  * **One touch covers up to N searches** the assistant makes answering that
    question; every subsequent outgoing query within the window is **disclosed
    in the chat as it leaves** (the caller emits the disclosure line) — no
    re-touch.
  * Exceeding N searches in one turn → a **fresh fingerprint** (a new window).
  * **Fail-closed** everywhere: no envelope begun for the turn → DENY; the
    fingerprint denied / unavailable / timed out → DENY, and the turn's envelope
    latches denied so a later egress in the same turn cannot retry past a refusal.

This module is the **state machine only**. The Hello coupling is injected as a
``consent_fn`` so the manager is unit-testable without a biometric device;
:func:`request_egress_fingerprint` is the production ``consent_fn`` — it builds a
SAFE :class:`~shared.security.escalation_consent.EscalationContext` and routes it
to the SAME operator-approval verifier the PA ESCALATE path already uses
(``escalation_consent.request_escalation_consent`` → the registered
``BiometricApprovalVerifier``), so there is ONE registered operator surface and
ONE fail-closed harness, not two.

Design constraints (match ``shared/security/``): no external network, no new
dependency (stdlib only), importing this module has no side effects, and the safe
state is always DENY.

Why an envelope + live disclosure rather than a fingerprint on literally every
query: agentic search is sequential — the later queries do not exist at the
moment the operator is first prompted, so they cannot be shown in the first
dialog. The faithful implementation of the LA's posture (*nothing leaves the
machine without a fingerprint on the specific query*) is therefore: fingerprint
the first concrete query under an explicit "up to N" bound, and disclose each
subsequent query live as it leaves. With N=1 the envelope degenerates to a
fingerprint on every single query. See ADR-023 §A4.5.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Callable, Optional

logger = logging.getLogger(__name__)

# The consent callback contract: given the query descriptor + the envelope bound
# N, return True iff the operator approved this egress. MUST be fail-closed (any
# failure to obtain an explicit approval is False). The production implementation
# is request_egress_fingerprint; tests inject a stub.
ConsentFn = Callable[[str, int], bool]


@dataclass
class _EnvelopeState:
    """Per-session, per-turn envelope state. Reset by :meth:`begin_turn`."""

    max_searches: int
    """N — the number of searches one fingerprint covers within a window."""

    searches_since_fingerprint: int = 0
    """How many searches have left since the last fingerprint (0 = a fresh
    fingerprint is required on the next egress). Reset to 1 each time a
    fingerprint is taken."""

    denied: bool = False
    """Latched once the operator denies (or a fingerprint fails closed) in this
    turn — a subsequent egress in the same turn is refused without re-prompting,
    so a fooled model cannot retry past a refusal."""


@dataclass(frozen=True)
class EgressDecision:
    """The outcome of gating one outbound query."""

    allowed: bool
    """True iff this query may leave the machine."""

    fingerprinted: bool
    """True iff THIS query required (and passed) a fresh Windows-Hello
    fingerprint. False for a query covered by an already-approved window and for
    a denied query."""

    reason: str
    """A short audit/debug descriptor (labels only — never the query text)."""


class EgressEnvelopeManager:
    """Per-session turn-scoped egress consent envelope (ADR-023 Am.4 rung 3).

    Lifecycle per user turn:
      1. :meth:`begin_turn` at the start of the tool loop (resets the envelope,
         arming it with N for this turn).
      2. :meth:`gate` before each outbound tool executes — it decides allow/deny
         and whether a fresh fingerprint was needed.
      3. (implicitly) the next :meth:`begin_turn` resets it; :meth:`end_turn` is
         available for explicit cleanup.

    Fail-closed: :meth:`gate` on a session with **no envelope begun** returns a
    DENY (an egress tool reaching the gate without a turn having armed the
    envelope is a wiring bug, and the safe answer is to refuse the egress).
    """

    def __init__(self) -> None:
        self._envelopes: dict[str, _EnvelopeState] = {}

    def begin_turn(self, session_id: str, max_searches: int) -> None:
        """Arm (reset) the envelope for a new user turn.

        ``max_searches`` (N) is clamped to at least 1 — an N < 1 would mean "no
        search may ever leave," which is not this control's job (deterministic
        egress denial is), so the floor is a single fingerprinted query.
        """
        n = max(1, int(max_searches))
        self._envelopes[session_id] = _EnvelopeState(max_searches=n)

    def end_turn(self, session_id: str) -> None:
        """Drop the envelope for a session (explicit cleanup; idempotent)."""
        self._envelopes.pop(session_id, None)

    def gate(
        self,
        session_id: str,
        query: str,
        *,
        consent_fn: ConsentFn,
    ) -> EgressDecision:
        """Decide whether one outbound ``query`` may leave, prompting for a
        fingerprint via ``consent_fn`` when the window requires one.

        Fail-closed on every non-approval path.
        """
        env = self._envelopes.get(session_id)
        if env is None:
            # No turn armed the envelope — refuse the egress (wiring bug / a
            # non-turn code path reached the gate). Safe state is DENY.
            logger.error(
                "Egress envelope: no envelope armed for session=%s — DENY "
                "(fail-closed).",
                session_id,
            )
            return EgressDecision(False, False, "no envelope armed (fail-closed)")

        if env.denied:
            # The turn already refused an egress — do not re-prompt; a fooled
            # model must not be able to retry past a refusal within the turn.
            return EgressDecision(False, False, "envelope latched denied this turn")

        need_fingerprint = (
            env.searches_since_fingerprint == 0
            or env.searches_since_fingerprint >= env.max_searches
        )
        if need_fingerprint:
            approved = False
            try:
                approved = bool(consent_fn(query, env.max_searches))
            except Exception as exc:  # noqa: BLE001 — fail-closed: any failure → DENY
                logger.error(
                    "Egress envelope: consent_fn raised %r — DENY (fail-closed) "
                    "for session=%s.",
                    exc, session_id,
                )
                approved = False
            if not approved:
                env.denied = True
                return EgressDecision(False, True, "operator denied / fail-closed")
            # A fresh window opens: this query is the 1st of up to N.
            env.searches_since_fingerprint = 1
            return EgressDecision(True, True, "fingerprinted (new window)")

        # Within an already-approved window: no re-touch, but the caller still
        # discloses the query in chat as it leaves.
        env.searches_since_fingerprint += 1
        return EgressDecision(True, False, "within approved window")


def extract_query(canonical_args: str) -> str:
    """Best-effort pull of the ``query`` field from a tool's canonical-args JSON.

    Returns the query string for the Hello dialog + the chat disclosure. On any
    parse failure / missing field, returns a generic descriptor — the gate never
    depends on this for its allow/deny (that is the envelope + fingerprint), only
    for what the operator is SHOWN, so a degraded descriptor is safe (the operator
    can still deny). The result is length-capped so a pathological query cannot
    bloat the dialog or a stream frame.
    """
    descriptor = "(query unavailable)"
    try:
        parsed = json.loads(canonical_args) if canonical_args else {}
        if isinstance(parsed, dict):
            q = parsed.get("query")
            if isinstance(q, str) and q.strip():
                descriptor = q.strip()
    except (json.JSONDecodeError, TypeError, ValueError):
        pass
    # Cap for the OS dialog + the disclosure stream frame (a query is short by
    # nature; this bounds a pathological one).
    return descriptor[:200]


def request_egress_fingerprint(
    query: str,
    max_searches: int,
    *,
    timeout_s: Optional[float] = None,
) -> bool:
    """Production ``consent_fn``: raise the Windows-Hello prompt for the FIRST
    egress of a turn (or a fresh window) and return the operator's approve/deny.

    Routes to the SAME registered operator-approval verifier the PA ESCALATE path
    uses (``escalation_consent.request_escalation_consent`` → the registered
    ``BiometricApprovalVerifier``), so there is ONE operator surface and ONE
    fail-closed harness. The context carries the query as a SAFE descriptor (the
    operator MUST see the exact query to judge the egress — this is not hidden
    payload; it is the model-generated search text the consent exists to
    authorize) plus the "up to N" bound, and ``source="egress"`` so the Hello
    dialog reads as an egress consent rather than an escalated-action approval.

    Fail-closed: no verifier registered / timeout / cancel / error → False
    (``request_escalation_consent`` guarantees this).
    """
    # Local import: keep this module import-side-effect-free and avoid a hard
    # dependency cycle at module load.
    from shared.security.escalation_consent import (
        DEFAULT_CONSENT_TIMEOUT_S,
        EscalationContext,
        request_escalation_consent,
    )

    n = max(1, int(max_searches))
    context = EscalationContext(
        rule_label="EGRESS_WEB_SEARCH",
        action_summary=(
            f"Search the web: {query} "
            f"(one approval covers up to {n} search"
            f"{'es' if n != 1 else ''} for this question)"
        ),
        tool_name="web_search",
        source="egress",
    )
    result = request_escalation_consent(
        context,
        timeout_s=DEFAULT_CONSENT_TIMEOUT_S if timeout_s is None else timeout_s,
    )
    return bool(result.approved)
