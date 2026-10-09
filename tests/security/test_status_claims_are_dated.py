"""A LIVE/ARMED/DORMANT claim outside the DoD must be backed by a date (capability 11).

WHAT THIS CLOSES. `CODER_DEFINITION_OF_DONE.md`'s capability 11 says a capability is not LIVE
until its observable has been executed and CITED. A grammar gate enforces that inside the DoD
itself — and it works; it has refused rows that tried to move without a dated citation. Outside
that one file the property was held by **habit**:

    Thirteen files publish a LIVE / ARMED / DORMANT claim — three under docs/ledger/, nine
    under docs/runbooks/, one in DECISION_REGISTER.md. Every one of them carries a date,
    because they are go-live ceremony records and sprint closes, which are dated by
    construction. So the property is conventionally held out there. Nothing checks it.

The row names the two defensible ways forward — extend the check, or decide in writing that a
ceremony record's date IS its citation — and records that neither had been done. This is the
first: the convention becomes a checked property, so the next status claim written into an
undated file fails here instead of being noticed by whoever happens to read it.

WHAT IT DOES NOT CLAIM, stated plainly because overclaiming is capability 11's own subject.
A date is not proof an event occurred; no textual check can be. What this refuses is the
specific failure capability 2 demonstrated — a status asserted with no event reference at all,
which then read as settled for a week. It raises the floor from "someone remembered" to
"the file says when". The stronger property — that the cited date names a real ceremony — is
held by the ceremony records themselves and is out of a linter's reach.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]

#: Where status claims live outside the DoD. Directories are scanned, so a NEW file publishing
#: a claim is picked up automatically — an allowlist of known files would pass forever by
#: simply not listing the offender, which is the shape this test exists to refuse.
_SCANNED: tuple[Path, ...] = (
    _REPO / "docs" / "ledger",
    _REPO / "docs" / "runbooks",
    _REPO / "docs" / "DECISION_REGISTER.md",
)

#: The status vocabulary capability 11 governs.
_CLAIM_RE = re.compile(r"\b(LIVE|ARMED|DORMANT)\b")

#: An ISO date. Deliberately the only accepted form: "August 2026" or "last Tuesday" cannot be
#: checked against a run id or a ledger entry, and a citation nobody can resolve is the thing
#: being replaced.
_DATE_RE = re.compile(r"\b20\d{2}-\d{2}-\d{2}\b")


def _markdown_under(path: Path) -> "list[Path]":
    if path.is_file():
        return [path]
    if not path.is_dir():
        return []
    return sorted(p for p in path.rglob("*.md") if p.is_file())


def files_publishing_a_status_claim() -> "list[Path]":
    """Every scanned markdown file containing a LIVE/ARMED/DORMANT token."""
    out: list[Path] = []
    for root in _SCANNED:
        for f in _markdown_under(root):
            try:
                if _CLAIM_RE.search(f.read_text(encoding="utf-8", errors="replace")):
                    out.append(f)
            except OSError:
                continue
    return out


def claim_is_dated(text: str) -> bool:
    """Does *text* carry an ISO date to back its status claim?"""
    return bool(_DATE_RE.search(text))


def test_every_file_publishing_a_status_claim_carries_a_date():
    """The control. Habit becomes a checked property."""
    offenders = []
    for f in files_publishing_a_status_claim():
        try:
            if not claim_is_dated(f.read_text(encoding="utf-8", errors="replace")):
                offenders.append(str(f.relative_to(_REPO)))
        except OSError:
            offenders.append(f"{f} (unreadable)")
    assert not offenders, (
        "these files publish a LIVE/ARMED/DORMANT claim with no ISO date to back it:\n  "
        + "\n  ".join(offenders)
        + "\n\nCapability 11: a flag is a configuration, an observable is an EVENT. Date the "
        "claim with the ceremony or run that established it, or do not publish the status."
    )


def test_the_population_is_not_empty_so_a_pass_means_something():
    """Guards the vacuous shape. If the scan ever returns nothing — a directory renamed, a
    glob broken — every assertion above passes over an empty set and this control silently
    stops being one. Measured 2026-08-15: thirteen files, matching capability 11's own count
    (three ledger, nine runbooks, one register)."""
    found = files_publishing_a_status_claim()
    assert len(found) >= 10, (
        f"only {len(found)} files scanned as publishing a status claim; capability 11 measured "
        f"13 on 2026-08-15. A collapsed population makes this gate vacuous — check the paths "
        f"in _SCANNED before lowering this floor."
    )


def test_an_undated_status_claim_is_REFUSED(tmp_path):
    """The toggle. Without it, the control above passes on a corpus that is already compliant
    and nobody learns whether it can fail at all."""
    undated = "# Ceremony\n\nThe widget front is LIVE. Flip `enabled = true`.\n"
    assert _CLAIM_RE.search(undated), "fixture must contain a status claim"
    assert not claim_is_dated(undated), (
        "an undated status claim was accepted — the control cannot fail and is decoration"
    )


def test_a_dated_status_claim_is_ACCEPTED(tmp_path):
    """Precision. A control that refused compliant records would be reverted within a day, and
    all thirteen real files are compliant today."""
    dated = "# Ceremony 2026-08-07\n\nThe widget front is LIVE. Flip `enabled = true`.\n"
    assert claim_is_dated(dated)


@pytest.mark.parametrize("word", ["LIVE", "ARMED", "DORMANT"])
def test_the_whole_status_vocabulary_is_covered(word):
    """All three words capability 11 governs, not just the one that prompted the row. ARMED and
    DORMANT are the states most likely to be asserted casually, because they read as modest."""
    assert _CLAIM_RE.search(f"the thing is {word} now")
