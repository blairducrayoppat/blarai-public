"""
Operator-preference PROPOSAL card — the shared card builder (#770 M2 W1).
==========================================================================
D-2 (LA, 2026-07-10): the confirm card is built ONCE here in the shared backend
so every front end shares it — the WinUI renders it richly and any text-only
surface (the TUI, tests, the plain-text fallback) shows the exact same readable
text.  This module is a LEAF: it holds NO store handle, NO cipher, NO model —
it turns an already-decided proposal into (1) the machine-detectable card block
the AO streams to the operator and (2) the readable fallback text.  It NEVER
writes anything (P8 — the sole write door is the AO PREFERENCE_WRITE handler; a
confirmed card rides that door with the store-side STAGED verbatim bytes, never
a model re-statement).

Security posture (study §5.2, verdict row 19): the proposed body is model-
emitted and may have been derived in a turn that carried untrusted grounded
content (D-1(a) — propose from anywhere, disclose provenance, flag untrusted-
context proposals).  So the card:

  * shows the proposed body VERBATIM but DISPLAY-sanitized — spotlighting
    delimiters, forged datamark shapes, and the proposal markers themselves are
    neutralized out of the shown text so a body can never break the card's own
    framing; the STAGED bytes the commit uses stay byte-verbatim in the AO
    staging store, not here;
  * names the PROVENANCE ("your last message" vs "after reading a document") so
    the operator judges the one plain-language question with the origin visible;
  * carries a visible UNTRUSTED-CONTEXT flag when untrusted content was in the
    conversation — the weak-signal defense (study §5.2: a prompt-injection
    screen catches only 42.5% of weak-signal cases, so a card-reading operator
    is the last line against a plausible-preference nudge).

Confirm/dismiss is operator-typed/clicked (P8): the readable text always spells
out the ``/remember-confirm <token>`` / ``/remember-dismiss <token>`` commands,
and the WinUI card's buttons send those exact commands — never a model turn.
"""

from __future__ import annotations

import re
from enum import Enum
from typing import NamedTuple

#: Machine-detectable card framing streamed inline in the assistant message.
#: ASCII + byte-stable so the WinUI C# regex and the Python/text surfaces parse
#: the same shape.  The opaque staging token rides the OPEN marker so a front
#: end extracts it without parsing the readable body.
PROPOSAL_BLOCK_OPEN_PREFIX: str = "[[PREFERENCE-PROPOSAL token="
PROPOSAL_BLOCK_OPEN_SUFFIX: str = "]]"
PROPOSAL_BLOCK_CLOSE: str = "[[/PREFERENCE-PROPOSAL]]"

#: The staging token grain: 16 lowercase hex (64 bits, ``secrets.token_hex(8)``).
#: Anchored everywhere it is validated (the gateway confirm/dismiss parse, this
#: module's extractor) — the forged-id gate pattern.
PROPOSAL_TOKEN_RE: re.Pattern[str] = re.compile(r"\A[0-9a-f]{16}\Z")

#: Extractor for a streamed card block: (token, inner_text).  Non-greedy DOTALL
#: so a multi-line card body is captured; the token group is hex-anchored.
_PROPOSAL_BLOCK_RE: re.Pattern[str] = re.compile(
    r"\[\[PREFERENCE-PROPOSAL token=([0-9a-f]{16})\]\](.*?)\[\[/PREFERENCE-PROPOSAL\]\]",
    re.DOTALL,
)

# Display-hostile shapes neutralized out of the SHOWN body so a proposed
# preference can never break the card's framing or impersonate a datamark.
# (The STAGED bytes stay verbatim — this hygiene is display-only.)
_DISPLAY_STRIP_SHAPES: tuple[str, ...] = (
    "<|GROUNDED_CONTEXT_BEGIN|>",
    "<|GROUNDED_CONTEXT_END|>",
    "<|SYSTEM_BEGIN|>",
    "<|SYSTEM_END|>",
)
_DISPLAY_MARKER_RE: re.Pattern[str] = re.compile(r"<\|(?:DOC|PREF)-[0-9a-f]{8}\|>")
# The proposal block markers themselves (defanged of the literal so a body that
# embeds "[[PREFERENCE-PROPOSAL" / "[[/PREFERENCE-PROPOSAL]]" cannot forge or
# terminate the frame it sits inside).
_DISPLAY_BLOCK_MARKER_RE: re.Pattern[str] = re.compile(
    r"\[\[/?PREFERENCE-PROPOSAL[^\]]*\]\]"
)


class ProposalAction(str, Enum):
    """What a confirmed proposal does to the tier (decided by the AO probe)."""

    ADD = "add"          # save a NEW standing preference
    REPLACE = "replace"  # supersede an existing near-duplicate/contradicting row
    RETRACT = "retract"  # remove an existing row (removals-as-removals, §2.2a)


class ProposalCard(NamedTuple):
    """One decided proposal, ready to render (the AO builds this; this module
    renders it).  ``body`` is the proposed verbatim text (ADD/REPLACE) and is
    display-sanitized at render time; ``target_body`` is the existing row's
    verbatim text (REPLACE/RETRACT)."""

    token: str                    # opaque staging token (16 hex) — the confirm handle
    action: ProposalAction
    body: str                     # proposed verbatim body (ADD/REPLACE); '' for RETRACT
    type_tag: str
    provenance_label: str         # "your last message" / "after reading a document" ...
    untrusted_context: bool       # True when UNTRUSTED_* content was in the turn
    target_pref_id: str = ""      # existing row id (REPLACE/RETRACT); '' for ADD
    target_number: int = 0        # existing row's 1-based /preferences number (0 if unknown)
    target_body: str = ""         # existing row's verbatim body (REPLACE/RETRACT); '' for ADD


def sanitize_for_display(body: str) -> str:
    """One-line, framing-safe form of a body for the shown card (display-only).

    Newlines flatten to single spaces; spotlighting delimiters, forged
    ``<|DOC-…|>``/``<|PREF-…|>`` datamark shapes, and the proposal block markers
    are neutralized so the body cannot break the card frame.  The STORED /
    STAGED body is untouched by this — P2 lives in the staging store, not here.
    """
    cleaned = body
    for shape in _DISPLAY_STRIP_SHAPES:
        cleaned = cleaned.replace(shape, " ")
    cleaned = _DISPLAY_MARKER_RE.sub(" ", cleaned)
    cleaned = _DISPLAY_BLOCK_MARKER_RE.sub(" ", cleaned)
    return " ".join(cleaned.split())


def _untrusted_line(card: "ProposalCard") -> list[str]:
    if not card.untrusted_context:
        return []
    return [
        "  ! Proposed while untrusted content (a document or web result) was in "
        "the conversation - read it carefully before saving."
    ]


def _target_number_label(card: "ProposalCard") -> str:
    """'preference N' when the row number is known, else 'this preference'."""
    return f"preference {card.target_number}" if card.target_number > 0 else "this preference"


def render_proposal_text(card: "ProposalCard") -> str:
    """The readable card body (no block markers) — the text fallback + the text
    the WinUI card renders.  Deterministic and self-sufficient: it always names
    the exact confirm/dismiss commands so an operator on any surface can act.
    """
    shown = sanitize_for_display(card.body)
    existing = sanitize_for_display(card.target_body)
    tag = f"  ({card.type_tag})" if card.type_tag else ""
    lines: list[str]
    if card.action is ProposalAction.RETRACT:
        lines = [
            f"Remove {_target_number_label(card)}?",
            f'  "{existing}"',
        ]
    elif card.action is ProposalAction.REPLACE:
        lines = [
            f"This looks like it replaces {_target_number_label(card)}:",
            f'  existing: "{existing}"',
            f'  new:      "{shown}"{tag}',
        ]
    else:  # ADD
        lines = [
            "Save this as a standing preference?",
            f'  "{shown}"{tag}',
        ]
    lines.append(f"  Noticed from: {card.provenance_label}")
    lines.extend(_untrusted_line(card))
    verb = "remove" if card.action is ProposalAction.RETRACT else (
        "replace" if card.action is ProposalAction.REPLACE else "save"
    )
    lines.append(f"To {verb} it, confirm below or reply: /remember-confirm {card.token}")
    lines.append(f"To dismiss, ignore it or reply: /remember-dismiss {card.token}")
    return "\n".join(lines)


def render_proposal_block(card: "ProposalCard") -> str:
    """The full card block the AO streams inline: the token-bearing OPEN marker,
    the readable text, then the CLOSE marker.  The WinUI detects the markers and
    renders a card with Save/Dismiss buttons (which send the exact
    ``/remember-confirm``/``/remember-dismiss`` commands); a text-only surface
    shows the readable text (the markers are inert framing there).
    """
    if not PROPOSAL_TOKEN_RE.fullmatch(card.token):
        raise ValueError(f"proposal token is not 16-hex: {card.token!r}")
    open_marker = (
        f"{PROPOSAL_BLOCK_OPEN_PREFIX}{card.token}{PROPOSAL_BLOCK_OPEN_SUFFIX}"
    )
    return f"{open_marker}\n{render_proposal_text(card)}\n{PROPOSAL_BLOCK_CLOSE}"


def extract_proposal_block(text: str) -> tuple[str, str] | None:
    """Return ``(token, inner_text)`` for the FIRST card block in *text*, or
    ``None``.  The token is hex-anchored by the pattern; front ends and tests
    use this to locate the card and its confirm handle without re-parsing the
    readable body."""
    match = _PROPOSAL_BLOCK_RE.search(text)
    if not match:
        return None
    return match.group(1), match.group(2).strip()


__all__ = [
    "PROPOSAL_BLOCK_OPEN_PREFIX",
    "PROPOSAL_BLOCK_OPEN_SUFFIX",
    "PROPOSAL_BLOCK_CLOSE",
    "PROPOSAL_TOKEN_RE",
    "ProposalAction",
    "ProposalCard",
    "sanitize_for_display",
    "render_proposal_text",
    "render_proposal_block",
    "extract_proposal_block",
]
