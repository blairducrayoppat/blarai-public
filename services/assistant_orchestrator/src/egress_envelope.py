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
import unicodedata
from collections.abc import Iterable
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

    def retain_only(self, active_session_ids: Iterable[str]) -> list[str]:
        """Drop envelopes for every session NOT in *active_session_ids* (#801).

        The session idle-reaper's companion: envelopes are per-session state
        that outlives the turn (``begin_turn`` resets rather than removes), so
        a destroyed session's envelope would otherwise sit until restart.
        Called after ``ContextManager.reap_idle_sessions`` with the surviving
        session ids; deterministic and clock-free — an envelope either belongs
        to a live session or it goes.

        Dropping an envelope is fail-closed by construction: if the session
        somehow egresses again before a new turn, ``gate`` on a missing
        envelope DENIES.

        Returns:
            The session ids whose envelopes were dropped.
        """
        active = set(active_session_ids)
        dropped = [sid for sid in self._envelopes if sid not in active]
        for sid in dropped:
            del self._envelopes[sid]
        return dropped

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


#: The longest query permitted to leave, as a SEND constraint rather than a
#: display one — see :func:`extract_query`. Measured on the DISCLOSURE RENDERING
#: (:func:`render_for_disclosure`), because that is the string the operator
#: actually reads, and an escaped character costs six of it.
#:
#: **THIS NUMBER IS A BOUND I CHOSE, NOT A MEASUREMENT, and saying so is the
#: point.** It rests on an argument — a legitimate search query is short by
#: nature, and an approval must cover every byte it authorises — not on data. An
#: earlier version of this comment presented a fixture census as the measured
#: half and stated it wrongly twice (#1592 review, finding 3: the quoted figures
#: described no single population). A threshold dressed as a measurement is worse
#: than an argued threshold.
#:
#: What the corpus does say, re-runnable via `tools/probes/census_query_literals.py`
#: which states its method: at `e8f682cb`, 117 string literals are bound to a
#: `query` key in tracked .py/.json/.jsonl files, 1 to 49 characters, median 26.
#: That key is shared with SQL — the longest is `SELECT name FROM sqlite_master
#: WHERE type='table'`, not a search — so it is an UPPER BOUND on search-query
#: length rather than a sample of it, and it is a fixture corpus in a system with
#: no production use. It shows the cap is not binding in practice. It does not
#: derive the cap.
#:
#: MEASURED 2026-09-20, with the operator present (#1593): the Windows Hello
#: credential dialog DOES render a 200-character query in full. The real dialog
#: was raised via `tools/hello_verify` carrying the exact 344-character message
#: this path produces at the cap, with the query's first 11 characters and last
#: 9 set to unmistakable markers. Both markers rendered, as did the entire
#: trailing clause after the query. The message wrapped across six lines with no
#: ellipsis and no truncation marker. No search was issued and nothing left the
#: machine.
#:
#: So the SEEN half is no longer a hypothesis: at this cap, what the operator
#: approves is what gets sent, and #1592's fix is not undone one layer down.
#:
#: What that observation does NOT license: raising this number. It establishes
#: that 344 characters render on this machine at its current display settings;
#: it does not locate the ceiling, and it says nothing about other scaling or a
#: narrower window. Raising the cap would need its own observation.
MAX_DISCLOSABLE_QUERY_CHARS: int = 200

#: Unicode general categories whose members are ESCAPED before the query is
#: shown to the operator, because a reader cannot see them: control (Cc),
#: format (Cf — zero-width joiners, bidi overrides like U+202E), surrogate (Cs),
#: private-use (Co), unassigned (Cn), and line/paragraph separators (Zl, Zp).
#:
#: Chosen by character CLASS rather than as a blocklist of code points: the set
#: of characters that can hide text from a reader is not one anybody can
#: enumerate, and the printable set is.
#:
#: **These are escaped, never refused, and that distinction is the whole design.**
#: An earlier version of this control REFUSED any query containing one. It was
#: correct about the danger and wrong about the remedy: U+200C and U+200D are
#: orthographically required in Persian and Devanagari and carried by ordinary
#: emoji sequences, ``Cc`` contains TAB, and ``Cn`` is every code point assigned
#: after the running interpreter's Unicode table — so refusal meant an operator
#: searching in their own language had the turn ended under a security
#: justification (#1592 review, finding 1). Escaping keeps the disclosure
#: guarantee and costs no capability at all.
_INVISIBLE_CATEGORIES: frozenset[str] = frozenset(
    {"Cc", "Cf", "Cs", "Co", "Cn", "Zl", "Zp"}
)


class QueryNotDisclosableError(ValueError):
    """The query cannot be shown to the operator in full, so it must not be sent.

    Raised rather than returned so no caller can treat it as a descriptor and
    proceed. The whole value of the Hello envelope is that a human looked at the
    string; a truncated view is worth exactly the fraction of the string it shows.
    """


def extract_query(canonical_args: str) -> str:
    """Pull the ``query`` field from a tool's canonical-args JSON, or REFUSE.

    Returns the DISCLOSURE RENDERING of the query — what the Hello dialog and the
    chat disclosure show — which is the query itself for any string containing no
    invisible characters, and otherwise a lossless escaped form of it (see
    :func:`render_for_disclosure`). On any
    parse failure / missing field, returns a generic descriptor — the gate never
    depends on this for its allow/deny (that is the envelope + fingerprint), only
    for what the operator is SHOWN, so a degraded descriptor is safe (the operator
    can still deny).

    **A query that cannot be shown to the operator IN FULL raises rather than
    being shown partially (#1592).** There are two ways a string can fail to be
    disclosed — it can be too LONG to fit, or short enough to fit and still able
    to HIDE its own tail from the reader — and they get different answers. The
    hiding characters are ESCAPED by :func:`render_for_disclosure`, so they cost
    no capability and become visible; only length still refuses, and it is
    measured on the RENDERED string, because that is what the operator actually
    reads. This used to return ``descriptor[:200]``, and that
    200-character string was what the Windows Hello dialog displayed while the
    adapter sent the full, untruncated query — so a 5,000-character query showed
    the operator 200 characters and sent 5,000, with everything after character
    200 approved without ever being displayed. The cap bounded the DISPLAY, not
    the PAYLOAD, and the asymmetry was an exfiltration channel through a control
    whose entire value is that a human read the string.

    Refusing is the fail-closed direction, and it is also the structural control
    the published landscape prefers to content inspection: a bounded field is a
    smaller channel. A legitimate search query is short by nature. A model that
    wants five thousand characters of query is doing something the operator
    should see refused, not approve unseen.

    Raises:
        QueryNotDisclosableError: the query exists but cannot be shown in full.
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

    rendered = render_for_disclosure(descriptor)
    if len(rendered) > MAX_DISCLOSABLE_QUERY_CHARS:
        raise QueryNotDisclosableError(
            f"outbound query renders to {len(rendered)} characters, which exceeds "
            f"the {MAX_DISCLOSABLE_QUERY_CHARS} that can be shown to the operator "
            f"in full. REFUSED rather than truncated: an approval covering only "
            f"the first {MAX_DISCLOSABLE_QUERY_CHARS} characters would approve "
            f"the rest unseen."
        )
    return rendered


def render_for_disclosure(query: str) -> str:
    """Return ``query`` with every character a reader cannot see made visible.

    **The invariant this establishes:** what the operator is shown is a LOSSLESS,
    UNAMBIGUOUS rendering of exactly the bytes that will be sent. Not the same
    string — a faithful one, from which the sent string can be recovered exactly.

    A length cap alone is not a disclosure guarantee. A THIRTY-TWO character
    query — ``"cats" + "\\n" * 12 + " ssn 123-45-6789"`` — passes any cap
    untouched and reaches both the Hello prompt and the chat disclosure verbatim,
    with its tail scrolled off whatever the operator is reading. ``q.strip()``
    removes outer whitespace and nothing else, so control characters, zero-width
    characters and bidi overrides all survive it (#1592 review, finding 3).

    Escaping rather than refusing is the second turn of that review (finding 1).
    Refusal was over-broad in a way that cost capability and bought nothing:
    U+200C/U+200D are orthographically required in Persian and Devanagari,
    ``Cc`` contains TAB, and ``Cn`` membership changes with the interpreter's
    Unicode table — so the same query could be refused on one Python and sent on
    the next. Escaped, all of those searches work, and the hidden-tail attack the
    control exists for becomes *visible to the operator* rather than merely
    blocked: they see the planted tail and deny it, which is strictly more
    information than a refusal message gives them.

    The backslash is escaped too. Without that the encoding is ambiguous — a
    query containing the six literal characters ``\\u200c`` would render
    identically to one containing an actual zero-width non-joiner, and an
    ambiguous rendering is not a disclosure.

    Not covered, stated rather than implied: combining marks (``Mn``) can be
    stacked to obscure neighbouring glyphs, and confusable/homoglyph substitution
    is a different problem entirely. Neither can hide the TAIL of a string, which
    is what this function bounds.
    """
    out: list[str] = []
    for char in query:
        if char == "\\":
            out.append("\\\\")
        elif unicodedata.category(char) in _INVISIBLE_CATEGORIES:
            code_point = ord(char)
            out.append(
                f"\\u{code_point:04x}"
                if code_point <= 0xFFFF
                else f"\\U{code_point:08x}"
            )
        else:
            out.append(char)
    return "".join(out)


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
