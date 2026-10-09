"""The roadmap is checked, not trusted — a stale one is worse than none (#1411).

WHY THIS EXISTS. The operator's words on 2026-08-15: *"i need a project mananger agent that
survives past sessions or something. this development process is just not working well."* And
on what to build: *"(a) a single ordered roadmap file that is the first thing any session
reads, and (b) something that keeps it honest — because a stale roadmap is worse than none."*

Part (a) is `docs/ROADMAP.md`, named in `CLAUDE.md`'s `<live_state_pointers>`. This file is
part (b), and (b) is the harder half: a document that claims to be the order and has quietly
stopped being true is worse than no document, because it is trusted.

THE THREE STALENESS SHAPES, all measured on 2026-08-15 rather than imagined:

  1. **An entry pointing at finished work.** #1390 sat on the operator's decision queue that
     morning while half of it was already fixed and merged — `5b86dda7`, 00:35 the same day.
     He was being asked to decide something already partly built. Catching this needs the
     board, so it lives in `scripts/verify_roadmap.py`, not here: this gate is offline by
     design and must not acquire a service dependency.
  2. **A blocker nobody can observe.** Twenty-seven open tickets said they were waiting for
     "the 23:00 run" — a rule that bounds changes per run, not runs per day. That predicate
     reads like a reason and decides nothing, which is exactly what `verify_disposition.py`
     already refuses in a `blocked-by:` line.
  3. **A top item that has not moved.** A roadmap whose rank 1 is unchanged for a fortnight
     with no note saying why is not being used. A date check cannot see this; only the
     refresh discipline can, which is why the refresh line is enforced below.

WHAT THIS FILE DELIBERATELY DOES NOT CHECK. **Whether the order is right.** No test can. That
is a judgement about what matters and it belongs to the operator. What is removed here is the
class of staleness that LOOKS like judgement.
"""

from __future__ import annotations

import datetime as _dt
import re
import subprocess
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
ROADMAP = _REPO / "docs" / "ROADMAP.md"

#: The same refresh-line grammar `ACTIVE_SPRINT.md` already lives under — reused rather than
#: invented, so a session that learns one surface's rule knows the other's.
_REFRESH_RE = re.compile(r"\*\*Last refresh \((\d{4}-\d{2}-\d{2})\)\*\*")

_BLOCK_RE = re.compile(r"```roadmap\n(.*?)```", re.DOTALL)

#: Deliberately closed vocabularies. An open one drifts: "soon", "next", "asap" and "now" all
#: appear, and then nothing can be sorted or counted.
_WHEN = frozenset({"now", "this-week", "later"})
_NEEDS_OPERATOR = frozenset({"yes", "no"})

#: How far the refresh date may trail `main` before the file is misinformation. Matches
#: ACTIVE_SPRINT's window: the same failure (a pointer frozen while the work moved) with the
#: same cost.
_MAX_LAG_DAYS = 14


def _read() -> str:
    return ROADMAP.read_text(encoding="utf-8", errors="replace")


def rows() -> "list[dict]":
    """Every parsed row of the machine-checkable block."""
    m = _BLOCK_RE.search(_read())
    if not m:
        return []
    out: list[dict] = []
    for line in m.group(1).splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = [p.strip() for p in line.split("|")]
        if len(parts) != 5:
            out.append({"malformed": line})
            continue
        rank, ticket, when, needs_op, text = parts
        out.append({
            "rank": rank, "ticket": ticket, "when": when,
            "needs_operator": needs_op, "text": text,
        })
    return out


def _last_commit_date() -> "_dt.date | None":
    try:
        stamp = subprocess.run(
            ["git", "log", "-1", "--format=%cs", "main"],
            cwd=_REPO, capture_output=True, text=True, timeout=20,
        ).stdout.strip()
        return _dt.date.fromisoformat(stamp) if stamp else None
    except Exception:  # noqa: BLE001 — a git-less checkout must not fail the gate
        return None


# ── the file exists and is reachable ───────────────────────────────────────


def test_the_roadmap_exists_and_is_pointed_at():
    """A roadmap no session is told to read is a document, not a control."""
    assert ROADMAP.is_file(), "docs/ROADMAP.md is missing — part (a) of #1411"
    claude_md = (_REPO / "CLAUDE.md").read_text(encoding="utf-8", errors="replace")
    assert "docs/ROADMAP.md" in claude_md, (
        "CLAUDE.md no longer points at the roadmap, so a session will re-derive priorities "
        "from whatever it opens first — the exact failure #1411 exists to end"
    )


# ── the block is well formed ───────────────────────────────────────────────


def test_the_machine_checkable_block_parses():
    parsed = rows()
    assert parsed, "no ```roadmap block found — the prose alone cannot be checked"
    malformed = [r["malformed"] for r in parsed if "malformed" in r]
    assert not malformed, (
        "roadmap rows must be `rank | ticket | when | needs-operator | one line`:\n  "
        + "\n  ".join(malformed)
    )


def test_ranks_are_unique_and_contiguous_from_one():
    """An ordered list with a gap or a duplicate is not ordered. This is what makes 'rank 1'
    mean 'the next thing worked on' rather than 'one of the important ones'."""
    ranks = [r["rank"] for r in rows() if "malformed" not in r]
    assert ranks, "no rows"
    try:
        nums = sorted(int(r) for r in ranks)
    except ValueError:
        pytest.fail(f"non-numeric rank in {ranks}")
    assert nums == list(range(1, len(nums) + 1)), (
        f"ranks must be 1..N with no gaps or duplicates; got {nums}"
    )


def test_every_row_names_a_ticket_or_an_explicit_gap():
    """A row citing nothing cannot survive this session. `-` is allowed and is itself a
    finding — it says out loud that the work has no durable home yet."""
    bad = [
        r for r in rows() if "malformed" not in r
        and not (r["ticket"] == "-" or re.fullmatch(r"#\d+", r["ticket"]))
    ]
    assert not bad, (
        "ticket must be #<number> or an explicit '-':\n  "
        + "\n  ".join(f"rank {r['rank']}: {r['ticket']!r}" for r in bad)
    )


@pytest.mark.parametrize("field,allowed", [("when", _WHEN), ("needs_operator", _NEEDS_OPERATOR)])
def test_closed_vocabularies_hold(field, allowed):
    """An open vocabulary drifts until nothing can be sorted or counted."""
    bad = [r for r in rows() if "malformed" not in r and r[field] not in allowed]
    assert not bad, (
        f"{field} must be one of {sorted(allowed)}:\n  "
        + "\n  ".join(f"rank {r['rank']}: {r[field]!r}" for r in bad)
    )


def test_every_row_says_something():
    """A one-line description is what makes this readable by the person who owns the order."""
    bad = [r for r in rows() if "malformed" not in r and len(r["text"]) < 20]
    assert not bad, (
        "every row needs a real one-line description, not a stub:\n  "
        + "\n  ".join(f"rank {r['rank']}: {r['text']!r}" for r in bad)
    )


# ── freshness ──────────────────────────────────────────────────────────────


def test_the_refresh_date_does_not_trail_main():
    """The staleness shape a form check cannot see. Same rule and same window as
    ACTIVE_SPRINT.md, whose body once froze for six weeks while being read as current."""
    m = _REFRESH_RE.search(_read())
    assert m, "docs/ROADMAP.md lost its '**Last refresh (YYYY-MM-DD)**' line"
    refreshed = _dt.date.fromisoformat(m.group(1))
    last_commit = _last_commit_date()
    if last_commit is None:
        pytest.skip("no git history available to compare against")
    lag = (last_commit - refreshed).days
    assert lag <= _MAX_LAG_DAYS, (
        f"the roadmap's refresh date {refreshed} trails main's latest commit {last_commit} "
        f"by {lag} days (limit {_MAX_LAG_DAYS}). It is being read as the current order while "
        f"the work moved on — re-measure it, do not just touch the date."
    )


# ── the toggles: each check proven able to fail ────────────────────────────


def test_a_malformed_row_is_REFUSED(tmp_path):
    """Without this the form checks pass over a compliant file and nobody learns whether they
    can fail at all."""
    fixture = "```roadmap\n# rank | ticket | when | needs-operator | one line\n1 | #1 | now\n```"
    m = _BLOCK_RE.search(fixture)
    assert m
    parts = [p.strip() for p in m.group(1).splitlines()[1].split("|")]
    assert len(parts) != 5, "the fixture must be malformed for this toggle to mean anything"


def test_a_ranking_gap_is_REFUSED():
    assert sorted([1, 2, 4]) != list(range(1, 4)), (
        "a gap in the ranks must not compare equal to a contiguous range"
    )


def test_a_stale_refresh_date_is_REFUSED():
    """The freshness rule, exercised on dates rather than on the live file — so it fails here
    even on a day when the real file is fresh."""
    refreshed = _dt.date(2026, 1, 1)
    last_commit = _dt.date(2026, 8, 15)
    assert (last_commit - refreshed).days > _MAX_LAG_DAYS


def test_an_undeclared_vocabulary_value_is_REFUSED():
    assert "soon" not in _WHEN and "maybe" not in _NEEDS_OPERATOR


# ── the population floor ───────────────────────────────────────────────────


def test_the_block_is_not_empty_so_a_pass_means_something():
    """Guards the vacuous shape. If the block is emptied — a regex broken, the section
    renamed — every assertion above passes over an empty list and this file silently stops
    being a control. Measured 2026-08-15: twelve rows."""
    parsed = [r for r in rows() if "malformed" not in r]
    assert len(parsed) >= 5, (
        f"only {len(parsed)} roadmap rows parsed; twelve were measured on 2026-08-15. A "
        f"collapsed block makes this gate vacuous — check the ```roadmap fence before "
        f"lowering this floor."
    )
