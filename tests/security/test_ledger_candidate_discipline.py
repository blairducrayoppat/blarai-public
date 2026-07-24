"""Gate lock: a ledger tuning candidate must reach the durable queue (#1047).

WHAT FAILURE THIS EXISTS FOR
----------------------------
``docs/quality/dispatch-quality-ledger.md`` is where dispatch runs get their
narrative record, and along the way it names **tuning candidates** — real,
specific, actionable findings, written in prose. Nothing required any of them to
become queue state, so they did not.

Measured on 2026-07-22, four candidate blocks existed in that file. Exactly ONE
carried a ticket reference inline (the #820 revise persona), and it is the only
one that was never lost:

* candidates (a) + (b), the wave-retry honesty pair — **un-ticketed** from the
  seed run until #1049 was filed the day this gate was written;
* candidates (c) + (d), the python-scaffold pair — un-ticketed from 2026-07-18
  until #1036, and only because the User-Operator asked a question that exposed
  them;
* the scaffold-hygiene candidate — un-ticketed until #1048, again only because
  the User-Operator asked.

Three of four recovered by someone happening to ask. ``<deferral_discipline>``
already covers findings from a *review* — they get a disposition record with an
observable predicate. The ledger is a different surface and had no such rule, so
findings written here fell outside the discipline entirely. This is that gap,
closed mechanically rather than by intending to remember.

WHAT IS LOCKED HERE
-------------------
Every ``tuning candidate`` mention in the ledger must name a ``#NNN`` ticket
within its own block, or carry an explicit ``no-ticket:`` marker giving a reason.
The escape hatch is deliberate and load-bearing: a control with no honest way to
say "this one genuinely does not need a ticket" gets satisfied with a junk ticket
instead, which is worse than the gap — it launders a dropped finding into a queue
entry, the exact anti-pattern ``<deferral_discipline>`` names.

Both directions are proven (``security_by_design`` principle 12): the checker
must REFUSE a candidate with no reference AND PASS the honest forms.

HONEST LIMIT
------------
This locks the FORM — that a candidate points somewhere. It cannot tell whether
the ticket it names is any good, whether it describes the same finding, or
whether it is ever worked. And it only sees candidates written with the words
this gate greps for: a finding recorded in different prose is invisible to it,
exactly as a review whose findings were never written down is invisible to
``verify_disposition.py``. Both gaps close in the same place — the session
writing the record — not here.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_LEDGER = _REPO_ROOT / "docs" / "quality" / "dispatch-quality-ledger.md"

#: The phrase the ledger actually uses for a finding it is handing forward. Applied to
#: WHITESPACE-NORMALISED block text, never to a raw line: the ledger is hard-wrapped at
#: ~78 columns, so a 16-character phrase straddles a wrap boundary roughly one time in
#: five. The first version of this gate matched line-by-line and was therefore blind to
#: 2 of the 8 real mentions (25%) — and BOTH of the ones it could not see were violations
#: of its own rule, so it reported a clean file while two findings sat untracked in it.
_CANDIDATE_RE = re.compile(r"tuning\s+candidate", re.I)
#: A Vikunja reference. 3-4 digits matches the live id range without matching years,
#: percentages, or the run-id stamps that fill this file — all verified against every
#: match in the live ledger, none of which is a false positive.
_TICKET_RE = re.compile(r"#\d{3,4}(?!\d)")
#: The honest escape hatch: `no-ticket: <reason>`, with a real reason behind it. The word
#: floor mirrors verify_disposition.py's MIN_REASON_WORDS so a bare `no-ticket: n/a`
#: cannot satisfy the gate — an escape hatch with no floor is just a bypass.
_NO_TICKET_RE = re.compile(r"no-ticket:\s*(\S+(?:\s+\S+){5,})", re.I)


def _blocks(lines: list[str]) -> list[tuple[int, str]]:
    """Split into (1-indexed start line, normalised text) BLOCKS.

    A block is a list item or a paragraph — a new one begins at a blank line or at a
    ``- ``/``* `` bullet. This replaced a +/-8-LINE WINDOW, which measured ~83% ineffective
    on the real file: the ledger is dense with ticket references, so an un-ticketed
    candidate planted at 539 of 648 insertion points sailed through on a neighbour's
    unrelated ticket. Scoping to the candidate's OWN block is what the ticket described
    all along; the window was the implementation drifting from it.

    Whitespace is normalised within a block so a hard-wrapped phrase is still seen (F1).
    """
    blocks: list[tuple[int, list[str]]] = []
    for i, line in enumerate(lines):
        # Only a TOP-LEVEL bullet starts a new block. An INDENTED sub-bullet continues its
        # parent — review finding R2: writing the tracking note as a nested sub-bullet is a
        # natural authoring shape and the first version REFUSED it. That direction matters
        # more than tightening: a wrongly-refused honest note teaches the next author to
        # route around the gate, and a gate people route around is worse than none.
        starts_new = (not line.strip()) or re.match(r"^[-*]\s", line)
        if starts_new or not blocks:
            blocks.append((i + 1, []))
        blocks[-1][1].append(line)
    return [(n, re.sub(r"\s+", " ", " ".join(body)).strip()) for n, body in blocks]


def _lines() -> list[str]:
    assert _LEDGER.exists(), f"ledger missing: {_LEDGER}"
    return _LEDGER.read_text(encoding="utf-8").splitlines()


def _covered(block: str) -> bool:
    return bool(_TICKET_RE.search(block) or _NO_TICKET_RE.search(block))


def _uncovered(lines: list[str]) -> list[tuple[int, str]]:
    return [
        (n, text[:110])
        for n, text in _blocks(lines)
        if _CANDIDATE_RE.search(text) and not _covered(text)
    ]


def _mention_count(lines: list[str]) -> tuple[int, int]:
    """(per-line count, normalised-text count). They must agree — see F1."""
    per_line = sum(1 for ln in lines if _CANDIDATE_RE.search(ln))
    joined = re.sub(r"\s+", " ", " ".join(lines))
    return per_line, len(_CANDIDATE_RE.findall(joined))


def test_every_ledger_tuning_candidate_reaches_the_queue() -> None:
    """The control. A candidate with nowhere to go is a dropped finding."""
    offenders = _uncovered(_lines())
    assert not offenders, (
        "ledger tuning candidate(s) with no #ticket and no `no-ticket:` reason — a finding "
        "recorded in prose and nowhere else is a dropped finding, which is what this gate "
        "exists to prevent.\n"
        "Put a `#NNN` — or `no-ticket: <reason of 6+ words>` — in the candidate's OWN "
        "block. A block ends at a blank line or the next TOP-LEVEL bullet, so a "
        "continuation line or a NESTED sub-bullet counts; a separate paragraph after a "
        "blank line does not:\n"
        + "\n".join(f"  line {n}: {t}" for n, t in offenders)
    )


def test_the_checker_refuses_an_unreferenced_candidate() -> None:
    """Toggle-off: prove the gate FAILS on the defect. Without this, a passing run
    cannot be distinguished from a checker that cannot reach anything."""
    planted = [
        "Some run narrative that mentions no ticket at all.",
        "- **Tuning candidates:** (z) something real that nobody ticketed.",
        "  continuation of that same bullet, still no reference.",
        "",
        "- An unrelated later bullet that DOES mention #1234.",
    ]
    offenders = _uncovered(planted)
    assert len(offenders) == 1, f"planted violation not caught: {offenders}"
    assert offenders[0][0] == 2, "wrong block reported"


@pytest.mark.parametrize(
    "reference",
    [
        "tracked as #1049.",
        "no-ticket: subsumed by the fix that lands in this same change.",
    ],
)
def test_the_checker_passes_both_honest_forms(reference: str) -> None:
    """Negative control. A gate nobody has watched ACCEPT the correct fix is as
    dangerous as one nobody has watched reject the defect — this control's value
    depends on a low false-positive rate, so both honest forms are pinned."""
    # The reference must live in the candidate's OWN block, so it is a continuation
    # line rather than a new bullet — a new bullet would start a new block, which is
    # exactly the scoping this control depends on.
    planted = [
        "Run narrative.",
        "- **Tuning candidates:** (z) something real.",
        "  " + reference,
    ]
    assert _uncovered(planted) == []


def test_a_ticket_in_a_DIFFERENT_block_does_not_satisfy_a_candidate() -> None:
    """Replaces a +/-8-LINE WINDOW that measured ~83% ineffective on the real file.

    The ledger is dense with ticket references, so a window almost always caught a
    neighbour's unrelated ticket: an un-ticketed candidate planted at 539 of 648
    insertion points passed. Scoping to the candidate's own block is what the control
    was always documented to do; the window was the implementation drifting from it.
    """
    planted = [
        "- **Tuning candidates:** (z) something real, with no reference of its own.",
        "",
        "- A completely separate bullet that happens to mention #1234.",
    ]
    offenders = _uncovered(planted)
    assert len(offenders) == 1, "a ticket in a neighbouring block wrongly satisfied a candidate"
    assert offenders[0][0] == 1


def test_a_hard_wrapped_candidate_phrase_is_still_seen() -> None:
    """The F1 lock. The ledger is hard-wrapped at ~78 columns, so the 16-character
    phrase straddles a line break roughly one time in five. The first version of this
    gate matched line-by-line and was blind to 2 of 8 real mentions — and both were
    violations, so it reported a clean file while two findings sat untracked in it.
    A mechanical blind spot, far likelier than the lexical one the docstring warns of.
    """
    wrapped = [
        "  something something and this names a scaffold-hygiene tuning",
        "  candidate with no reference at all.",
    ]
    assert len(_uncovered(wrapped)) == 1, "a wrapped candidate phrase was not seen"

    per_line, normalised = _mention_count(wrapped)
    assert per_line == 0 and normalised == 1, (
        "this fixture must actually be wrapped, or the lock is vacuous")

    # Deliberately NOT locked: that the LIVE ledger never wraps the phrase. The review
    # offered that as an alternative to the structural fix; the structural fix is the one
    # taken, so wrapping is now harmless and forbidding it would impose a formatting rule
    # on a narrative document for no safety gain. Two live mentions are wrapped right now
    # and the gate reads both correctly.


def test_the_escape_hatch_has_a_reason_floor() -> None:
    """An escape hatch with no floor is a bypass. Mirrors verify_disposition.py's
    MIN_REASON_WORDS so `no-ticket: n/a` cannot satisfy the gate."""
    bare = ["- **Tuning candidate:** (z) real.", "  no-ticket: n/a"]
    assert len(_uncovered(bare)) == 1, "a bare no-ticket: reason was accepted"

    real = ["- **Tuning candidate:** (z) real.",
            "  no-ticket: subsumed by the fix that lands in this same change."]
    assert _uncovered(real) == [], "an honest no-ticket: reason was refused"


def test_a_nested_sub_bullet_reference_is_accepted() -> None:
    """Review finding R2. Writing the tracking note as an indented sub-bullet is a natural
    authoring shape, and the first version of this gate REFUSED it — a false positive on
    an honest note. False positives are what get a gate disabled or routed around, so this
    direction is pinned as deliberately as the toggle-off."""
    nested = [
        "- **Tuning candidate:** (z) something real.",
        "  - tracked as #1049.",
    ]
    assert _uncovered(nested) == [], "a nested sub-bullet reference was wrongly refused"


def test_a_reference_in_a_SEPARATE_paragraph_is_still_refused() -> None:
    """The other half of R2, and this one is intentional rather than fixed.

    A blank line genuinely ends a block, so a note written as its own paragraph does not
    cover the candidate. Accepting it would re-open F2 — 'the next paragraph' is how a
    neighbour's unrelated ticket satisfied a candidate in the first place. The assertion
    message states the rule, so the refusal teaches instead of merely blocking."""
    separated = [
        "- **Tuning candidate:** (z) something real.",
        "",
        "tracked as #1049.",
    ]
    assert len(_uncovered(separated)) == 1
