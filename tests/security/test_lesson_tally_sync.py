"""Gate lock for LESSONS.md recurrence-tally sync (#1059, promoted 2026-07-23).

WHAT FAILURE THIS EXISTS FOR
----------------------------
LESSONS.md Rule 2 splits one fact across two surfaces: a recurrence appends a dated
``*(recurred: …)*`` marker to the lesson's full text in
``docs/archive/lessons/LESSONS_ARCHIVE.md`` and bumps the ``↺n`` flag on its index
line in the hot file. Nothing enforced the agreement, and on 2026-07-22 a repo-wide
sweep found SEVEN index rows disagreeing with the archive — six of them born in a
single hand-built index creation, undetected for three days. ``↺`` is the number
Rule 3 keys on (third instance => a structural control is OWED), so an over-count
manufactures an obligation and an under-count HIDES one, both silently, on the exact
surface a session reads before minting a lesson number.

The #1059 reconcile settled each row by history archaeology (five real recurrences
written as markers, one over-counted flag corrected, two ordinal-dialect markers
normalised); this gate keeps the surfaces from drifting apart again. The checker is
``tools/doc_hygiene/check_lesson_tallies.py`` — these tests drive its REAL functions
and its REAL command-line entry point, over the live corpus and over planted-drift
fixtures, so the gate is known to have teeth (security_by_design principle 12).

HONEST LIMIT, carried forward from the tool's own docstring
-----------------------------------------------------------
The check reconciles the two surfaces AGAINST EACH OTHER and cannot tell which is
right: a wrong-but-CONSISTENT pair passes clean — the same class of gap #970 names
for the gate-figure pair. A green run here means "the surfaces agree", never "the
count is true"; only per-lesson history archaeology can establish truth, and
``test_wrong_but_consistent_pair_passes_by_design`` documents the limit rather than
letting someone discover it.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
TOOL = REPO_ROOT / "tools" / "doc_hygiene" / "check_lesson_tallies.py"

sys.path.insert(0, str(REPO_ROOT / "tools" / "doc_hygiene"))
from check_lesson_tallies import (  # noqa: E402
    archive_recurrence_counts,
    canon32_headline_drift,
    index_flags,
    tally_drift,
)

# The tool prints ``↺``/``…``; a cp1252 pipe would kill the child with
# UnicodeEncodeError before it could report anything, so the subprocess legs pin
# the child's stdout encoding rather than inherit the shell lottery.
_UTF8_ENV = {**os.environ, "PYTHONIOENCODING": "utf-8"}


def _run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(TOOL), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=_UTF8_ENV,
        timeout=60,
        check=False,
    )


# --- the live corpus stays reconciled ---------------------------------------


def test_index_flags_match_archive_recurrence_counts() -> None:
    """Every ``↺n`` index flag equals its lesson's canonical archive marker count.

    On failure, NEVER force one surface to match the other: a missing archive
    marker and an over-counted flag look identical here, and blind-matching
    silently erases real recurrences. Read the lesson's history (git log -p on
    both surfaces + the journal) and fix the surface that is actually wrong —
    the #1059 per-row records are the worked example.
    """
    drift = tally_drift(index_flags(), archive_recurrence_counts())
    assert drift == [], (
        "LESSONS.md index ↺ flags disagree with the archive's *(recurred: …)* "
        "counts — rows are (lesson, index flag, archive count, uncounted ordinal "
        f"markers): {drift}. Adjudicate each by reading its history; do not "
        "force-match (see this test's docstring and #1059)."
    )


def test_canon32_headlines_match_archive() -> None:
    """The Canon-32 residency copies' HEADLINES agree with the archive authority.

    Marker-count deltas on Canon-32 copies are correct by design (Rule 2, amended
    2026-07-22); a diverged headline is real drift on the copy read first.
    """
    assert canon32_headline_drift() == []


def test_every_indexed_lesson_has_archive_full_text() -> None:
    """No index line points at a lesson the archive volume does not carry."""
    missing = sorted(set(index_flags()) - set(archive_recurrence_counts()))
    assert missing == [], (
        f"indexed lessons with no archive full text: {missing} — the index is the "
        "pre-mint search surface and every entry must resolve to its authority"
    )


def test_strict_cli_exits_zero_on_live_corpus() -> None:
    """The ticket's own predicate, through the real entry point: --strict exits 0."""
    proc = _run_cli("--strict")
    assert proc.returncode == 0, (
        f"check_lesson_tallies --strict failed on the live corpus:\n"
        f"{proc.stdout}\n{proc.stderr}"
    )


# --- toggle-off proofs: planted drift MUST fail ------------------------------
#
# Fixtures reproduce the hot file's structural skeleton (Canon-32 tier, then the
# index heading the parser anchors on) and the archive's one-line-per-lesson
# form, then plant exactly one defect each. Every probe drives the REAL parser
# and the REAL CLI — no reimplemented detection logic (the 2026-07-22 fold
# review caught a toggle-off that reimplemented its detector; not repeated).

_CONSISTENT_HOT = (
    "# LESSONS (fixture)\n\n"
    "## Canon-32 — fixture tier\n\n"
    "7. **A headline both surfaces share.** Judgment text.\n\n"
    "## Index of every lesson (fixture)\n\n"
    "7. A headline both surfaces share  · ↺1\n"
    "8. A lesson with no recurrences\n"
)
_CONSISTENT_ARCHIVE = (
    "# ARCHIVE (fixture)\n\n"
    "7. **A headline both surfaces share.** Full text. "
    "*(recurred: 2026-01-01 — an incident.)*\n"
    "8. **A lesson with no recurrences.** Full text.\n"
)


def _write(tmp_path: Path, hot: str, archive: str) -> tuple[Path, Path]:
    hot_p = tmp_path / "LESSONS.md"
    arc_p = tmp_path / "ARCHIVE.md"
    hot_p.write_text(hot, encoding="utf-8")
    arc_p.write_text(archive, encoding="utf-8")
    return hot_p, arc_p


def test_consistent_fixture_passes_strict_cli(tmp_path: Path) -> None:
    """Negative control: agreeing surfaces exit 0 under --strict."""
    hot_p, arc_p = _write(tmp_path, _CONSISTENT_HOT, _CONSISTENT_ARCHIVE)
    proc = _run_cli("--strict", "--hot", str(hot_p), "--archive", str(arc_p))
    assert proc.returncode == 0, f"clean fixture failed:\n{proc.stdout}\n{proc.stderr}"


def test_strict_cli_fails_on_over_counted_flag(tmp_path: Path) -> None:
    """A flag bumped past the archive count (the 2026-07-22 shape) is refused."""
    hot_p, arc_p = _write(
        tmp_path,
        _CONSISTENT_HOT.replace("share  · ↺1", "share  · ↺2"),
        _CONSISTENT_ARCHIVE,
    )
    proc = _run_cli("--strict", "--hot", str(hot_p), "--archive", str(arc_p))
    assert proc.returncode == 1, f"planted over-count passed:\n{proc.stdout}"
    assert "disagree with the archive" in proc.stdout and "7" in proc.stdout


def test_strict_cli_fails_on_missing_archive_marker(tmp_path: Path) -> None:
    """The mirror direction: a marker the index never counted is also drift."""
    hot_p, arc_p = _write(
        tmp_path,
        _CONSISTENT_HOT,
        _CONSISTENT_ARCHIVE.replace(
            "*(recurred: 2026-01-01 — an incident.)*",
            "*(recurred: 2026-01-01 — an incident.)* "
            "*(recurred: 2026-02-02 — a second incident the flag missed.)*",
        ),
    )
    proc = _run_cli("--strict", "--hot", str(hot_p), "--archive", str(arc_p))
    assert proc.returncode == 1, f"planted uncounted marker passed:\n{proc.stdout}"


def test_strict_cli_fails_on_canon32_headline_drift(tmp_path: Path) -> None:
    """A Canon-32 copy whose headline diverged from the archive is refused."""
    hot_p, arc_p = _write(
        tmp_path,
        _CONSISTENT_HOT.replace(
            "7. **A headline both surfaces share.** Judgment text.",
            "7. **A headline only the hot copy rewrote.** Judgment text.",
        ),
        _CONSISTENT_ARCHIVE,
    )
    proc = _run_cli("--strict", "--hot", str(hot_p), "--archive", str(arc_p))
    assert proc.returncode == 1, f"planted headline drift passed:\n{proc.stdout}"
    assert "headline differs from the archive" in proc.stdout


def test_ordinal_marker_is_reported_never_counted(tmp_path: Path) -> None:
    """An ordinal-dialect marker must not enter the count — only the ordinal? column.

    Locks the 2026-07-22 lesson in code: widening the recurrence regex to ordinal
    forms once manufactured five false positives by counting control notes as
    recurrences. Ordinal markers are surfaced for human adjudication instead.
    """
    _, arc_p = _write(
        tmp_path,
        _CONSISTENT_HOT,
        _CONSISTENT_ARCHIVE.replace(
            "8. **A lesson with no recurrences.** Full text.",
            "8. **A lesson with no recurrences.** Full text. "
            "*(THIRD INSTANCE — a control note in the old ordinal dress.)*",
        ),
    )
    counts = archive_recurrence_counts(arc_p)
    assert counts[8] == (0, 1), (
        f"lesson 8 counted {counts[8]} — ordinal markers must stay out of the "
        "canonical count and appear only in the ambiguous column"
    )


def test_wrong_but_consistent_pair_passes_by_design(tmp_path: Path) -> None:
    """HONEST LIMIT (not a defect): surfaces that agree on a wrong number pass.

    Same class as #970's gate-figure gap. If both the flag and the archive miss
    the same real recurrence, this gate is structurally blind to it — truth
    enters only through the curation discipline (Rule 2's tally-at-fold and the
    quarterly Rule-5 pass), never through this comparison. Documented as an
    executable statement so nobody reads a green run as more than agreement.
    """
    hot_p, arc_p = _write(
        tmp_path,
        # Lesson 7 "really" recurred twice, but both surfaces recorded one.
        _CONSISTENT_HOT,
        _CONSISTENT_ARCHIVE,
    )
    proc = _run_cli("--strict", "--hot", str(hot_p), "--archive", str(arc_p))
    assert proc.returncode == 0
