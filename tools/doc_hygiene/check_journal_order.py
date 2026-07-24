"""Check BUILD_JOURNAL.md's chronological integrity.

Two invariants, both violated by real incidents (#1021, fixed 2026-07-22):

1. MONOTONIC DATES — ``### YYYY-MM-DD`` entry headers must be non-decreasing
   top to bottom. Folds that append backdated content at the then-tail
   (the mechanism behind commits ``1cc26adb`` and ``9aa92ece``) break this.
2. NO DUPLICATE ENTRIES — the same (date, title) header must not appear twice.
   The #1021 duplicate was a degraded second copy of an already-folded entry.

Honest limit: a PAIRWISE date check under-reports when consecutive misplaced
entries mask each other (#1021's 07-04 entry sat unflagged behind a misplaced
07-01 neighbour), so this checker reports EVERY entry that is older than the
maximum date seen above it — the masking-proof form — and it cannot know where
a misplaced entry BELONGS; only its history can.

Exit 0 clean; exit 1 with one line per violation.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

_HEADER = re.compile(r"^### (\d{4}-\d{2}-\d{2}) \W? ?(.*)$")


def find_violations(text: str) -> list[str]:
    """Every chronology/duplication violation in a journal text, described."""
    violations: list[str] = []
    seen: dict[tuple[str, str], int] = {}
    max_date = ""
    max_line = 0
    for lineno, line in enumerate(text.splitlines(), 1):
        m = _HEADER.match(line)
        if not m:
            continue
        date, title = m.group(1), m.group(2).strip()
        key = (date, title)
        if key in seen:
            violations.append(
                f"line {lineno}: duplicate entry {date} {title!r} "
                f"(first at line {seen[key]})"
            )
        else:
            seen[key] = lineno
        if date < max_date:
            violations.append(
                f"line {lineno}: entry dated {date} appears after {max_date} "
                f"(line {max_line}) — out of chronological order"
            )
        elif date > max_date:
            max_date, max_line = date, lineno
    return violations


def main(argv: list[str]) -> int:
    path = Path(argv[1]) if len(argv) > 1 else Path("BUILD_JOURNAL.md")
    violations = find_violations(path.read_text(encoding="utf-8"))
    for v in violations:
        print(v)
    if violations:
        print(f"{len(violations)} violation(s) in {path}")
        return 1
    print(f"OK: {path} chronology + uniqueness clean")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
