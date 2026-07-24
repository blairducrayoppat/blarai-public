"""Gate: BUILD_JOURNAL.md chronology and entry uniqueness (#1021's lock).

Drives the real checker (``tools/doc_hygiene/check_journal_order.py``) over the
REAL journal, plus planted-violation proofs that the checker detects each
defect class it exists for — including the masking shape a pairwise check
misses (#1021: a 07-04 entry hidden behind a misplaced 07-01 neighbour).
"""
from __future__ import annotations

from pathlib import Path

from tools.doc_hygiene.check_journal_order import find_violations

_REPO = Path(__file__).resolve().parents[2]


def test_build_journal_is_chronological_and_duplicate_free() -> None:
    text = (_REPO / "BUILD_JOURNAL.md").read_text(encoding="utf-8")
    violations = find_violations(text)
    assert not violations, "BUILD_JOURNAL.md integrity violations:\n" + "\n".join(
        violations
    )


def test_checker_detects_out_of_order_entry() -> None:
    planted = (
        "### 2026-07-09 — A\n\nbody\n\n"
        "### 2026-07-01 — B\n\nbody\n\n"
        "### 2026-07-10 — C\n\nbody\n"
    )
    violations = find_violations(planted)
    assert any("out of chronological order" in v for v in violations)


def test_checker_detects_masked_consecutive_misplacements() -> None:
    """The #1021 shape: 07-04 after a misplaced 07-01 is locally increasing —
    a pairwise check stays silent on the second entry; this one must not."""
    planted = (
        "### 2026-07-09 — A\n\nbody\n\n"
        "### 2026-07-01 — B\n\nbody\n\n"
        "### 2026-07-04 — C\n\nbody\n\n"
        "### 2026-07-09 — D\n\nbody\n"
    )
    violations = find_violations(planted)
    flagged = [v for v in violations if "out of chronological order" in v]
    assert len(flagged) == 2, f"expected BOTH masked entries flagged: {violations}"


def test_checker_detects_duplicate_entry() -> None:
    planted = (
        "### 2026-07-01 — Same title\n\nbody\n\n"
        "### 2026-07-02 — Other\n\nbody\n\n"
        "### 2026-07-01 — Same title\n\ndegraded copy\n"
    )
    violations = find_violations(planted)
    assert any("duplicate entry" in v for v in violations)


def test_checker_passes_clean_text() -> None:
    clean = (
        "### 2026-07-01 — A\n\nbody\n\n"
        "### 2026-07-01 — B\n\nbody\n\n"
        "### 2026-07-02 — C\n\nbody\n"
    )
    assert find_violations(clean) == []
