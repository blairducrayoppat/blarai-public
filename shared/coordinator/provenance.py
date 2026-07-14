"""Advisory-only self-work (ADR-039 §2.2 control 2) + instruction-channel integrity (control 3).

Control 2 — **self-work is advisory-only.** BlarAI-originated proposals about BlarAI
itself carry a **structural** provenance marking, never a text convention (a text
marker is forgeable by any injection that can author a comment — ADR-039 rejected alt
#2): the dedicated ``blarai-coordinator`` account's immutable ``created_by`` PLUS a
label set by deterministic code (:data:`~shared.coordinator.config.SELF_ADVISORY_LABEL`).
BlarAI's own dispatch path refuses these categorically — even post-approval: approval
routes a self-advisory item to humans, never to the fleet.

Control 3 — **instruction-channel integrity.** Content BlarAI authors on a ticket is
provenance-marked, and every consumer (BlarAI itself on a later read, and Claude dev
sessions) treats it as untrusted proposal-grade input under the
:data:`~shared.coordinator.config.COORDINATOR_AUTHORED_TIER` tier — so the ticket
store can never become a covert self-instruction channel.

**The account is created by the C1/#843 operator-run migration** — this module builds
the REFUSAL and PROVENANCE logic that keys on the structural provenance, not the
account itself.

**Structural, never textual.** Every predicate here reads only STRUCTURED fields
(``created_by`` identity, the label set). None parses a ticket title or description —
a lock proves it (a title that merely *says* "Advisory:BlarAI" is not treated as
self-advisory; only the structural label is). This is the CaMeL discipline applied to
provenance: untrusted text can never forge a trust signal.

**Defense-in-depth with control 1.** Even if the self-advisory label were stripped,
the governed-core target check (:func:`shared.coordinator.governed_core.check_target`)
independently refuses any dispatch whose target resolves into the governed core. The
two controls are layered, not alternatives.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping

from shared.coordinator.config import (
    COORDINATOR_ACCOUNT_USERNAME,
    COORDINATOR_AUTHORED_TIER,
    SELF_ADVISORY_LABEL,
    AUTHORED_CONTENT_MARKER_DEFAULT,
)


@dataclass(frozen=True)
class TicketProvenance:
    """A STRUCTURED view of a ticket's provenance — the only fields the controls read.

    ``created_by_username`` is the immutable account identity (control 2's authorship
    anchor). ``label_titles`` is the deterministic-code-set label set (the lane
    marker). ``well_formed`` is False when the source object could not be read as a
    ticket at all (fail-closed: an unreadable ticket is treated conservatively).
    ``has_unrecognized_label`` is True when a well-formed-but-opaque label entry was
    seen (a label object carrying no usable title/name, or a labels value of an
    unexpected type) — the dispatch check treats that fail-closed as self-advisory
    (SG-review F4), so an unreadable label lane over-routes to humans, never under."""

    created_by_username: str = ""
    label_titles: frozenset[str] = frozenset()
    well_formed: bool = True
    has_unrecognized_label: bool = False


class DispatchProvenanceDecision(Enum):
    """A provenance-lane dispatch verdict — ALLOW (workspace lane) or REFUSE (self-advisory)."""

    ALLOW = "ALLOW"
    REFUSE = "REFUSE"


@dataclass(frozen=True)
class DispatchProvenanceVerdict:
    """The verdict of the advisory-only dispatch check (control 2)."""

    decision: DispatchProvenanceDecision
    reason: str

    @property
    def allowed(self) -> bool:
        return self.decision is DispatchProvenanceDecision.ALLOW

    @property
    def refused(self) -> bool:
        return self.decision is DispatchProvenanceDecision.REFUSE


# ---------------------------------------------------------------------------
# Structural provenance extraction (fail-closed, never parses free text)
# ---------------------------------------------------------------------------


def _extract_username(created_by: Any) -> str:
    """Pull a username from a Vikunja ``created_by`` value (dict or bare string)."""
    if isinstance(created_by, Mapping):
        for key in ("username", "name"):
            value = created_by.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return ""
    if isinstance(created_by, str):
        return created_by.strip()
    return ""


def _extract_label_titles(labels: Any) -> tuple[frozenset[str], bool]:
    """Pull label titles from a Vikunja ``labels`` collection (fail-closed; SG-review F4).

    Returns ``(titles, saw_unrecognized)``. Accepts labels delivered as a SEQUENCE
    (list/tuple/set/frozenset) OR as a MAPPING (an ``id -> label`` object whose VALUES
    are the labels — Vikunja usually sends a list, but a mapping shape must not let the
    marker slip). Each label may be a bare string, or a mapping carrying its title under
    ``title`` OR ``name`` (matching downstream is case-insensitive).

    ``saw_unrecognized`` is True when a WELL-FORMED-but-opaque label entry was seen — a
    mapping with neither a usable ``title`` nor ``name``, an entry of an unexpected type,
    or a whole labels value that is neither a sequence nor a mapping. The caller then
    fails CLOSED (an unreadable label lane conservatively routes to humans). ``None`` /
    empty / absent labels are a normal no-label ticket, NOT opaque."""
    if labels is None:
        return frozenset(), False
    if isinstance(labels, Mapping):
        entries: list[Any] = list(labels.values())
    elif isinstance(labels, (list, tuple, set, frozenset)):
        entries = list(labels)
    else:
        # A labels value that is neither a sequence nor a mapping (e.g. a bare scalar)
        # cannot be characterised → fail closed.
        return frozenset(), True

    titles: set[str] = set()
    saw_unrecognized = False
    for label in entries:
        if isinstance(label, Mapping):
            title = label.get("title")
            if not (isinstance(title, str) and title.strip()):
                title = label.get("name")
            if isinstance(title, str) and title.strip():
                titles.add(title.strip())
            else:
                saw_unrecognized = True  # a label object with no usable title/name
        elif isinstance(label, str):
            if label.strip():
                titles.add(label.strip())
            # an empty/whitespace string is inert noise, not opaque
        else:
            saw_unrecognized = True  # a label entry of an unexpected type
    return frozenset(titles), saw_unrecognized


def extract_provenance(ticket: Any) -> TicketProvenance:
    """Extract STRUCTURAL provenance from a ticket-shaped mapping (fail-closed).

    Reads ONLY ``created_by`` and ``labels`` — never ``title``/``description`` text.
    A non-mapping input yields ``well_formed=False`` (the dispatch check treats that
    conservatively). A well-formed ticket with no labels is a normal workspace ticket
    (empty label set), NOT an error."""
    if not isinstance(ticket, Mapping):
        return TicketProvenance(well_formed=False)
    titles, saw_unrecognized = _extract_label_titles(ticket.get("labels"))
    return TicketProvenance(
        created_by_username=_extract_username(ticket.get("created_by")),
        label_titles=titles,
        well_formed=True,
        has_unrecognized_label=saw_unrecognized,
    )


def is_coordinator_authored(prov: TicketProvenance) -> bool:
    """True iff the ticket's immutable ``created_by`` is the coordinator account.

    The authorship anchor of control 2's structural provenance — case-sensitive match
    on the dedicated account username (a distinct account, not the shared ``blarai``
    one, is what makes ``created_by`` provenance non-inert; SG-review F13)."""
    return prov.created_by_username == COORDINATOR_ACCOUNT_USERNAME


def carries_self_advisory_label(prov: TicketProvenance) -> bool:
    """True iff the ticket is on the self-advisory lane (the deterministic-code-set marker).

    The self-advisory label (:data:`SELF_ADVISORY_LABEL`) is matched CASE-INSENSITIVELY
    against the structural label set, so a case-variant of the marker still routes to
    humans (SG-review F4). An opaque/unrecognized label shape
    (``prov.has_unrecognized_label``) ALSO returns True: a label lane we cannot read is
    conservatively treated as self-advisory (fail-closed — over-route to humans, never
    under-route a self-item to the fleet)."""
    if prov.has_unrecognized_label:
        return True
    target = SELF_ADVISORY_LABEL.strip().casefold()
    return any(title.strip().casefold() == target for title in prov.label_titles)


def is_self_advisory(ticket: Any) -> bool:
    """True iff *ticket* is on the self-advisory (about-BlarAI, humans-only) lane.

    Keyed on the STRUCTURAL label set — never on title/description text. The label is
    set by deterministic code (control 2), so its presence marks the human-dev-channel
    lane. A refusal fires on the label alone (the conservative, fail-closed direction:
    a stray advisory label over-routes to humans, never under-routes a self-item to
    the fleet)."""
    prov = extract_provenance(ticket)
    return carries_self_advisory_label(prov)


def refuse_self_advisory_dispatch(
    ticket: Any, *, approved: bool = False
) -> DispatchProvenanceVerdict:
    """Control 2 — BlarAI's dispatch path refuses a self-advisory item CATEGORICALLY.

    REFUSE (route to humans, never the fleet) if the ticket is on the self-advisory
    lane — **regardless of ``approved``**: approval of a self-advisory item is
    approval to hand it to the human dev channel, never a license to dispatch it
    against BlarAI. A ticket object that cannot be read at all
    (``well_formed=False``) is also REFUSED (fail-closed — an unreadable dispatch
    request is not dispatched). Everything else passes the provenance lane check (the
    governed-core target check, control 1, still runs independently)."""
    prov = extract_provenance(ticket)
    if not prov.well_formed:
        return DispatchProvenanceVerdict(
            DispatchProvenanceDecision.REFUSE,
            "ticket provenance could not be read — refusing dispatch (fail-closed)",
        )
    if carries_self_advisory_label(prov):
        authored = (
            "coordinator-authored"
            if is_coordinator_authored(prov)
            else "labelled by another author"
        )
        state = "approved" if approved else "unapproved"
        return DispatchProvenanceVerdict(
            DispatchProvenanceDecision.REFUSE,
            f"self-advisory item ({authored}, {state}) — BlarAI may advise on itself "
            f"but never execute against itself; routes to the human dev channel, "
            f"never the fleet, even post-approval (ADR-039 §2.2 control 2)",
        )
    return DispatchProvenanceVerdict(
        DispatchProvenanceDecision.ALLOW,
        "not a self-advisory item (workspace lane); target still gated by control 1",
    )


# ---------------------------------------------------------------------------
# Control 3 — instruction-channel integrity
# ---------------------------------------------------------------------------


def mark_authored(text: str, *, marker: str = AUTHORED_CONTENT_MARKER_DEFAULT) -> str:
    """Prepend the coordinator's human-readable authored-content marker to *text*.

    Transparency for a human reader — NOT the trust anchor (the trust anchor is the
    structural ``created_by`` account, which an injection cannot forge). Idempotent:
    text already carrying the marker is returned unchanged."""
    body = text if isinstance(text, str) else str(text)
    if body.startswith(marker):
        return body
    return f"{marker}\n\n{body}"


def is_coordinator_authored_content(author_username: str | None) -> bool:
    """True iff content authored by *author_username* is coordinator-authored (control 3)."""
    return isinstance(author_username, str) and author_username.strip() == COORDINATOR_ACCOUNT_USERNAME


def provenance_tier_for_author(author_username: str | None) -> str:
    """The provenance tier a consumer stamps on content by *author_username* (control 3).

    Coordinator-authored content → :data:`COORDINATOR_AUTHORED_TIER` (untrusted
    proposal-grade). Any other author → ``""`` (the consumer applies its own tiering;
    this module speaks only to the coordinator-authored case)."""
    if is_coordinator_authored_content(author_username):
        return COORDINATOR_AUTHORED_TIER
    return ""


def treat_as_untrusted(author_username: str | None) -> bool:
    """True iff a consumer must treat content by *author_username* as untrusted (control 3).

    Every consumer — BlarAI on a later read, a Claude dev session — treats
    coordinator-authored ticket/comment content as untrusted proposal-grade input,
    never as operator instruction, closing the covert-self-instruction-channel loop."""
    return is_coordinator_authored_content(author_username)
