"""The coder Definition of Done speaks a closed status vocabulary — machine-checked.

Ratified with capability 11 and the status legend (LA, 2026-08-07, #1325): every
capability row in ``docs/design/CODER_DEFINITION_OF_DONE.md`` carries a status, the
status leads with a legend word, a LIVE claim carries a dated citation, and the two
acceptance tests state whether they have ever been executed. Before this gate existed
the document was scanned by nothing, and three of its rows drifted within days of
being written (capability 2 read LIVE for a week on flags alone; capability 6's
headline outlived its own correction by hours; capability 7's residuals list was
overtaken by the board the evening it merged).

The checker itself is exercised on synthetic bad inputs below, because a lock that
has never been seen to fail is not a lock (capability 14's own rule).

Honest limit: this gate checks FORM, not truth — a fabricated "as of" date passes
it. The defenses against a false status are the ratified re-measurement cadence and
event-driven review, not this file.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DOD = REPO_ROOT / "docs" / "design" / "CODER_DEFINITION_OF_DONE.md"

#: The ratified legend. A status line's FIRST legend word is its claim.
LEGEND = ("LIVE", "ARMED", "PARTIAL", "UNKNOWN", "STOOD-DOWN")
#: Retired status dialects that must never reappear in a status line.
BANNED = ("MOSTLY LIVE", "FLAGS LIVE")
#: Highest capability number the document defines.
TOP_CAPABILITY = 21

_HEADING_RE = re.compile(r"^### (\d+)\.", re.MULTILINE)
_LEGEND_RE = re.compile("|".join(re.escape(w) for w in LEGEND))
_LIVE_CITE_RE = re.compile(r"as of \d{4}-\d{2}-\d{2}")

#: Absolute NEGATIVE claims. These are the sentences that went stale silently on 2026-08-14:
#: row 5 said the withdrawal event had "never been observed" two days AFTER it happened; row 19
#: said a correlation "cannot be computed from banked state at all" while 580 log lines and 694
#: draw records already carried it; row 14's table said an instrument had fired 0 times when it
#: had fired 11.
#:
#: The asymmetry is the point, and it is invisible in the writing: "this happened" needs ONE
#: witness, while "this has never happened" is a claim about the ENTIRE search space and needs
#: to have looked everywhere. Both sentences are the same length and sound equally measured.
#: Every one of those three was written by someone reading a real surface and reporting honestly
#: what was on it — from one corner of the space.
#:
#: So a negative claim earns the same burden `LIVE` already carries: name WHEN you looked. A
#: date or a run id does not prove the search was exhaustive, but it stops a claim from
#: outliving the evidence in silence, which is how all three survived.
_NEGATIVE_CLAIM_RE = re.compile(
    r"\bnever\b|\bcannot\b|\bno run\b|\bnot once\b|\b0 of\b|\bzero\b|\bhas not\b", re.IGNORECASE
)
#: Any dated evidence: an ISO date, or a run id like `20260805-000122-bd`.
_ANY_CITE_RE = re.compile(r"\d{4}-\d{2}-\d{2}|\d{8}-\d{6}-bd")
_EXECUTED_RE = re.compile(r"\*\*Executed: (NEVER|\d{4}-\d{2}-\d{2})")


def _read() -> str:
    assert DOD.exists(), f"the Definition of Done moved or vanished: {DOD}"
    return DOD.read_text(encoding="utf-8")


def _capability_sections(text: str) -> dict[int, str]:
    """Each ``### N.`` capability heading mapped to its section body."""
    sections: dict[int, str] = {}
    matches = list(_HEADING_RE.finditer(text))
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        n = int(m.group(1))
        # A renumbered or duplicated capability is a structural break, not a merge.
        assert n not in sections, f"capability {n} appears more than once"
        sections[n] = text[m.start():end]
    return sections


def _status_window(section: str) -> str | None:
    """The first ``Status:`` claim in a section, flattened to one line."""
    idx = section.find("Status:")
    if idx < 0:
        return None
    return " ".join(section[idx : idx + 300].split())


def _status_violations(section: str, n: int | str = "?") -> list[str]:
    """Grammar violations for one capability section. Empty means conforming."""
    violations: list[str] = []
    window = _status_window(section)
    if window is None:
        return [f"capability {n}: no Status: line at all"]
    for banned in BANNED:
        if banned in window:
            violations.append(f"capability {n}: retired dialect {banned!r} in status")
    first = _LEGEND_RE.search(window)
    if first is None:
        violations.append(
            f"capability {n}: status speaks no legend word {LEGEND}: {window[:80]!r}"
        )
        return violations
    neg = _NEGATIVE_CLAIM_RE.search(window)
    if neg is not None and not _ANY_CITE_RE.search(window):
        violations.append(
            f"capability {n}: absolute negative claim {neg.group(0)!r} with no dated citation "
            f"— 'never' is a claim about the whole search space and must say WHEN it was "
            f"checked (a date or a run id): {window[:80]!r}"
        )
    if first.group(0) == "LIVE" and not _LIVE_CITE_RE.search(window):
        violations.append(
            f"capability {n}: LIVE claim without a dated citation "
            f"('as of YYYY-MM-DD'): {window[:80]!r}"
        )
    return violations


def _beyond_range(sections: dict[int, str]) -> list[int]:
    """Capability numbers above the ratified range — rows nothing else here checks."""
    return sorted(n for n in sections if n > TOP_CAPABILITY)


def test_all_capabilities_present_exactly_once() -> None:
    sections = _capability_sections(_read())
    missing = [n for n in range(1, TOP_CAPABILITY + 1) if n not in sections]
    assert not missing, f"capability rows missing from the document: {missing}"


def test_no_capability_beyond_the_ratified_range() -> None:
    """A 22nd row would silently escape every per-row check in this file: the range
    checks iterate 1..TOP_CAPABILITY, so an unratified row would be the one row the
    gate never reads. Adding a capability = LA ratification + bumping TOP_CAPABILITY
    in the same change."""
    extra = _beyond_range(_capability_sections(_read()))
    assert not extra, (
        f"capability rows beyond the ratified range 1..{TOP_CAPABILITY}: {extra} — "
        "ratify first (DECISION_REGISTER + #ticket), then raise TOP_CAPABILITY here"
    )


def test_every_capability_carries_a_status() -> None:
    sections = _capability_sections(_read())
    unstatused = [n for n in range(1, TOP_CAPABILITY + 1) if _status_window(sections[n]) is None]
    assert not unstatused, (
        f"rows with no Status: line: {unstatused} — an unstated status is not UNKNOWN, "
        "it is unreadable"
    )


def test_status_lines_speak_the_legend() -> None:
    sections = _capability_sections(_read())
    violations = [
        v for n in range(1, TOP_CAPABILITY + 1) for v in _status_violations(sections[n], n)
    ]
    assert not violations, "status grammar violations:\n" + "\n".join(violations)


def test_acceptance_tests_state_their_execution() -> None:
    hits = _EXECUTED_RE.findall(_read())
    assert len(hits) == 2, (
        f"expected exactly 2 '**Executed:' lines (one per acceptance test), found "
        f"{len(hits)} — the document's two headline observables must carry a status too"
    )


def test_legend_section_defines_the_full_vocabulary() -> None:
    text = _read()
    idx = text.find("### Status legend")
    assert idx >= 0, "the ratified status-legend section is gone"
    legend_section = text[idx : idx + 1500]
    absent = [w for w in (*LEGEND, "UNVOUCHED") if w not in legend_section]
    assert not absent, f"legend section no longer defines: {absent}"


def test_no_row_is_marked_proposed_after_ratification() -> None:
    """Ratification removed the banner; a re-grown PROPOSED capability heading means
    someone added a row without the LA's decision recorded."""
    text = _read()
    assert "## PROPOSED capabilities" not in text, (
        "a PROPOSED capabilities banner is back — new rows need an LA ratification "
        "recorded in DECISION_REGISTER before the banner drops"
    )


# --- the checker is proven able to fail (capability 14 applied to this lock) ---


def test_checker_flags_an_uncited_live_claim() -> None:
    bad = "### 3. X\n\n**Status: LIVE — everything is wonderful.**\n"
    assert any("without a dated citation" in v for v in _status_violations(bad, 3))


def test_checker_flags_a_retired_dialect() -> None:
    bad = "### 7. X\n\n**Status: MOSTLY LIVE, and improving.**\n"
    assert any("retired dialect" in v for v in _status_violations(bad, 7))


def test_checker_flags_a_status_outside_the_vocabulary() -> None:
    bad = "### 9. X\n\n**Status: excellent progress this sprint.**\n"
    assert any("speaks no legend word" in v for v in _status_violations(bad, 9))


def test_checker_flags_a_missing_status_line() -> None:
    bad = "### 12. X\n\nA row of prose with no claim at all.\n"
    assert _status_violations(bad, 12) == ["capability 12: no Status: line at all"]


def test_checker_passes_a_conforming_row() -> None:
    good = "### 1. X\n\n**Status: LIVE as of 2026-07-30** (`888b1b02`).\n"
    assert _status_violations(good, 1) == []


def test_checker_flags_a_row_beyond_the_range() -> None:
    text = "### 21. X\n\n**Status: UNKNOWN.**\n\n### 22. Smuggled\n\n**Status: UNKNOWN.**\n"
    assert _beyond_range(_capability_sections(text)) == [22]


def test_checker_flags_an_uncited_negative_claim() -> None:
    """'Never' without a date is the sentence that went stale three times on 2026-08-14."""
    bad = "### 9. Row\n**Status: ARMED — the observable has never fired.**\n"
    v = _status_violations(bad, 9)
    assert any("absolute negative claim" in x for x in v), v


def test_checker_accepts_a_negative_claim_that_says_when_it_looked() -> None:
    """The toggle. A rule that rejects every negative claim would just be noise."""
    ok_date = "### 9. Row\n**Status: ARMED — never fired, re-measured 2026-08-14.**\n"
    assert not any("absolute negative claim" in x for x in _status_violations(ok_date, 9))
    ok_run = "### 9. Row\n**Status: ARMED — never fired; swept to 20260811-232102-bd.**\n"
    assert not any("absolute negative claim" in x for x in _status_violations(ok_run, 9))


def test_a_positive_claim_needs_no_such_citation() -> None:
    """The asymmetry this rule exists for: one witness settles a positive claim."""
    pos = "### 9. Row\n**Status: PARTIAL — the mechanism is wired and the artifact is banked.**\n"
    assert not any("absolute negative claim" in x for x in _status_violations(pos, 9))
