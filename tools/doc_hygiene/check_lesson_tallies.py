"""Reconcile every LESSONS.md index flag against the archive's recurrence markers.

WHY THIS EXISTS
---------------
`LESSONS.md` Rule 2 splits one fact across two surfaces: a recurrence appends a dated
``*(recurred: …)*`` marker to the lesson's full text in
``docs/archive/lessons/LESSONS_ARCHIVE.md``, and bumps the ``↺n`` flag on that lesson's
one-line index entry in the hot file. The index legend defines ``↺n`` as "recorded
recurrences", so the two must agree by construction.

Nothing enforced that. The 2026-07-22 journal fold found a drifted flag on lesson 46 the
only way it could be found — by hand, while bumping it — and a repo-wide sweep then showed
seven more index lines disagreeing with their archive text.

The drift matters because ``↺`` is what Rule 3 keys on: a lesson at its third instance
(``↺2``) MUST ship a structural control in the same change. An over-counting flag
manufactures an obligation that is not owed; an under-counting flag HIDES one that is. Both
failures are silent, and the index is the surface a session searches before minting a
number, so a wrong flag is read as fact at exactly the moment it decides something.

USAGE
-----
    python tools/doc_hygiene/check_lesson_tallies.py            # report drift
    python tools/doc_hygiene/check_lesson_tallies.py --strict   # exit 1 on any drift
    ... [--hot PATH] [--archive PATH]                           # override the surfaces
                                                                # (fixtures/gate toggle-off)

HONEST LIMITS — two, and the second is the one that will bite you
------------------------------------------------------------------
1. It reconciles the two surfaces against EACH OTHER and cannot tell which is right. A
   drifted row means "these disagree, go read the lesson's history" — the fix is either a
   missing archive marker or an over-counted flag. Same class of gap #970 names for the
   gate-figure pair, stated here rather than left for someone to discover: a
   wrong-but-CONSISTENT pair passes clean, and only per-lesson history archaeology (the
   #1059 method: `git log -p` on both surfaces plus the journal's narration of each
   incident) can catch that.

2. **A recurrence written in any dialect other than `*(recurred: …)*` is invisible to the
   count.** Rule 2 prescribes `*(recurred: …)*` and Rule 3 `*(control: …)*`; those are all
   this tool counts or trusts. The archive also carries older ordinal-form markers
   (`*(third instance — …)*` and kin), and prose alone says whether such a marker is a
   recurrence or a control note on an existing one. This was learned the expensive way on
   2026-07-22: an independent reviewer's broadened regex cleared one real ordinal-form
   recurrence, so the tool was broadened to match — and promptly manufactured five NEW
   false positives by counting control notes as recurrences. Two instruments, three
   totals, same corpus. The tool therefore counts only the canonical dialect and SURFACES
   ordinal forms in the `ordinal?` column for human adjudication; the #1059 reconcile
   normalised the two ordinal markers that were load-bearing (lesson 64's recurrence,
   lesson 222's control) into the canonical forms, so a remaining ordinal marker is
   expected to be a control note — but adjudicate it by reading, never by widening the
   regex.

GATE-ENFORCED since #1059: `tests/security/test_lesson_tally_sync.py` drives this module's
real functions over the live corpus in the standing gate and proves on planted fixtures
that the drift detection has teeth. The gate inherits limit 1 verbatim.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
HOT = REPO / "LESSONS.md"
ARCHIVE = REPO / "docs" / "archive" / "lessons" / "LESSONS_ARCHIVE.md"

INDEX_HEADING = "## Index of every lesson"
LESSON_LINE = re.compile(r"^(\d+)\. ")
FLAG = re.compile(r"↺(\d+)")

# CANONICAL dialect — the one Rule 2 actually prescribes. Counted.
RECURRED = re.compile(r"\*\(recurred:")

# AMBIGUOUS dialects — reported, never counted. The archive also carries ordinal-form
# markers (`*(third instance — control: …)*` and kin), and only prose says whether such a
# marker records a recurrence or a control note on an existing one — so no regex counts
# them reliably.
#
# This tool briefly tried to. On 2026-07-22, broadening the matcher to include ordinal
# forms fixed one false positive (lesson 64's then-ordinal recurrence marker, since
# normalised to the canonical dialect at #1059) and immediately manufactured five NEW
# false positives (8, 130, 188, 213, 221, 222 as then written) by counting control notes
# as recurrences. Two instruments produced three different totals for the same corpus,
# which is the actual finding: an ordinal marker's meaning lives in its prose.
#
# So the tool counts only the canonical dialect and SURFACES the ambiguous ones for human
# adjudication rather than folding them into a number. An instrument that reports a precise
# figure its input cannot support is the failure this repo calls "a control that measures
# nothing" — and the fix for that is never a cleverer regex.
AMBIGUOUS_MARKER = re.compile(
    r"\*\(\s*(?:SECOND|THIRD|FOURTH|FIFTH|SIXTH|SEVENTH|EIGHTH|NINTH|TENTH)\s+"
    r"(?:INSTANCE|RECURRENCE)",
    re.IGNORECASE,
)


def archive_recurrence_counts(archive: Path = ARCHIVE) -> dict[int, tuple[int, int]]:
    """Map lesson -> (canonical recurrence count, ambiguous ordinal-marker count)."""
    counts: dict[int, tuple[int, int]] = {}
    for line in archive.read_text(encoding="utf-8").splitlines():
        m = LESSON_LINE.match(line)
        if m:
            counts[int(m.group(1))] = (
                len(RECURRED.findall(line)),
                len(AMBIGUOUS_MARKER.findall(line)),
            )
    return counts


def index_flags(hot: Path = HOT) -> dict[int, int]:
    """Map lesson number -> its index line's ``↺n`` flag (absent flag reads as 0)."""
    lines = hot.read_text(encoding="utf-8").splitlines()
    try:
        start = next(i for i, l in enumerate(lines) if l.startswith(INDEX_HEADING))
    except StopIteration:  # pragma: no cover - structural change to the hot file
        sys.exit(f"'{INDEX_HEADING}' not found in {hot.name} — the index moved or was renamed.")
    flags: dict[int, int] = {}
    for line in lines[start:]:
        m = LESSON_LINE.match(line)
        if not m:
            continue
        f = FLAG.search(line)
        flags[int(m.group(1))] = int(f.group(1)) if f else 0
    return flags


def tally_drift(
    flags: dict[int, int], archive: dict[int, tuple[int, int]]
) -> list[tuple[int, int, int, int]]:
    """Rows (lesson, index flag, canonical count, ordinal count) where the surfaces disagree.

    A lesson indexed but absent from the archive is a different defect (surfaced
    separately by ``main``), not a drift row.
    """
    drift: list[tuple[int, int, int, int]] = []
    for num, flag in sorted(flags.items()):
        if num not in archive:
            continue
        canonical, ambiguous = archive[num]
        if flag != canonical:
            drift.append((num, flag, canonical, ambiguous))
    return drift


CANON_HEADING = "## Canon-32"
BOLD_HEADLINE = re.compile(r"\*\*(.+?)\*\*", re.S)


def canon32_headline_drift(
    hot: Path = HOT, archive: Path = ARCHIVE
) -> list[tuple[int, str]]:
    """Canon-32 full texts whose HEADLINE no longer matches the archive's.

    THE THIRD SURFACE. `LESSONS.md` carries duplicate full text for 32 lessons in the
    Canon-32 residency tier, and an independent reviewer found this tool blind to it —
    it compared index-vs-archive and nothing else, so a checker covering two of three
    mirrors would be trusted as covering all three.

    What is checked here is the HEADLINE, not the marker count, because Rule 2 (amended
    2026-07-22) makes the marker delta CORRECT BY DESIGN: the archive is the incident log,
    the index `↺` is the count, and the Canon-32 copy carries the judgment under a hard
    120 KB hot-file budget that backfilling every marker provably breaks (measured: +3,393
    bytes over). So a Canon-32 copy with fewer markers is fine; one whose lesson TEXT has
    diverged from the authority is not — that is the drift a reader actually gets burned by,
    since the hot tier is the copy read first.
    """
    hot_lines = hot.read_text(encoding="utf-8").splitlines()
    try:
        start = next(i for i, l in enumerate(hot_lines) if l.startswith(CANON_HEADING))
        end = next(
            i for i, l in enumerate(hot_lines) if i > start and l.startswith(INDEX_HEADING)
        )
    except StopIteration:
        return []

    archive_text: dict[int, str] = {}
    for line in archive.read_text(encoding="utf-8").splitlines():
        m = LESSON_LINE.match(line)
        if m:
            archive_text[int(m.group(1))] = line

    drift: list[tuple[int, str]] = []
    for line in hot_lines[start:end]:
        m = LESSON_LINE.match(line)
        if not m:
            continue
        num = int(m.group(1))
        if num not in archive_text:
            drift.append((num, "no archive full text"))
            continue
        hot_head = BOLD_HEADLINE.search(line)
        arc_head = BOLD_HEADLINE.search(archive_text[num])
        if not hot_head or not arc_head:
            continue  # a copy without a bold headline is a different (formatting) question
        norm = lambda s: " ".join(s.split()).rstrip(".").lower()
        if norm(hot_head.group(1)) != norm(arc_head.group(1)):
            drift.append((num, "headline differs from the archive"))
    return drift


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--strict", action="store_true", help="exit 1 when any row drifts")
    ap.add_argument("--hot", type=Path, default=HOT, help="hot-file override (fixtures)")
    ap.add_argument(
        "--archive", type=Path, default=ARCHIVE, help="archive-volume override (fixtures)"
    )
    args = ap.parse_args()

    archive = archive_recurrence_counts(args.archive)
    flags = index_flags(args.hot)
    drift = tally_drift(flags, archive)

    missing = sorted(set(flags) - set(archive))
    canon_drift = canon32_headline_drift(args.hot, args.archive)

    print(f"index lines scanned: {len(flags)}   archive full texts: {len(archive)}")
    if missing:
        print(f"\nindexed but no archive full text ({len(missing)}): {missing}")

    if canon_drift:
        print(f"\nCanon-32 surface: {len(canon_drift)} entr(y/ies) drifted from the archive:")
        for num, why in canon_drift:
            print(f"  lesson {num}: {why}")
    else:
        print("Canon-32 surface: headlines match the archive.")

    if not drift and not canon_drift:
        print("\nOK - index flags match archive counts, and Canon-32 headlines match too.")
        return 0
    if not drift:
        print("\n(no index/archive count drift; see the Canon-32 rows above)")
        return 1 if args.strict else 0

    print(f"\n{len(drift)} index line(s) disagree with the archive:\n")
    print(f"  {'lesson':>7}  {'index':>6}  {'recurred:':>10}  {'ordinal?':>9}")
    for num, flag, canonical, ambiguous in drift:
        print(f"  {num:>7}  {flag:>6}  {canonical:>10}  {(ambiguous or '-'):>9}")
    print(
        "\nCOUNTED: the canonical `*(recurred: …)*` dialect only.\n"
        "ordinal? = ordinal-form markers PRESENT but NOT counted. Since the #1059\n"
        "normalisation these are expected to be control notes on an existing recurrence\n"
        "(e.g. lesson 8), but only prose says so — a row with a non-zero ordinal? count\n"
        "may not be drift at all. Adjudicate it by reading, never by widening this regex.\n\n"
        "A genuine drift row is EITHER a missing archive marker OR an over-counted index\n"
        "flag. This tool cannot tell which — read the lesson's history."
    )
    return 1 if args.strict else 0


if __name__ == "__main__":
    raise SystemExit(main())
