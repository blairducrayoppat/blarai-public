# enforces-rule: decision_boundary.deferral_discipline.any-review-audit-verification
# enforces-rule: decision_boundary.deferral_discipline.a-deferral-is-a
"""
BlarAI finding-disposition verifier
===================================
The control for the failure mode named on 2026-07-20: a defect surfaces, the
session files a ticket instead of fixing it, and the ticket carries no reason
that would survive being asked "what concrete failure does the delay prevent?"

Doctrine already forbade this (``decision_boundary``: *"Reporting a defect
without fixing it = incomplete response"*; the standing directive: *"Before
deferring, name the concrete failure the delay prevents; 'it feels safer' is
not a reason"*). It was violated anyway, twice in one session, on findings that
needed no decision at all - because by then the change had merged and the box
felt closed. **Momentum, not judgement.** A rule that is already written and
already ignored does not need restating; it needs teeth.

WHAT THIS ENFORCES

Any review, audit, or verification pass that produces findings must record a
DISPOSITION for every one of them, and every deferral must name a predicate
that could actually be observed to come true. The verifier reads a required,
machine-checkable ``disposition`` block and FAILS LOUD on:

  * a finding with no disposition at all (deny-by-default: silence is the
    failure mode, so an absent row can never pass);
  * a FIXED row that names no commit-ish evidence - "fixed" is a claim, and a
    claim without an artifact is what this whole class of defect is made of;
  * a DEFERRED row with no ticket - deferral without a durable queue entry is
    the *"durability requires distribution"* failure, not a deferral;
  * a DEFERRED row whose ``blocked-by:`` predicate is a FILLER PHRASE. This is
    the teeth. "follow-up", "lower priority", "next session", "out of scope for
    now" are not predicates - they are momentum wearing the costume of a
    decision, and they are what actually gets written;
  * a DEFERRED row whose predicate names nothing observable. A real predicate
    references something a later session can CHECK: a ticket, a date, a file,
    a named gate or symbol. "when the design settles" cannot be observed;
    "when #989 is decided" can.

THE BLOCK (fenced ```disposition), pipe-delimited. Each row:

    <finding> | <status> | <evidence-or-predicate>

  - ``FIXED``    - requires a commit-ish token in evidence: a 7-40 hex SHA, or
                   a ``branch/name`` ref. Every SHA is additionally RESOLVED
                   against the repository it claims to live in (see below).
  - ``DEFERRED`` - requires BOTH a ``#NNN`` ticket AND a ``blocked-by:`` clause
                   that is neither filler nor unobservable.
  - ``REJECTED`` - a finding judged not to be a defect. Requires a reason of
                   >= MIN_REASON_WORDS words, because "not a defect" asserted
                   without argument is the same silence in a different hat.

EVIDENCE IN A SIBLING REPOSITORY (``<repo>@<sha>``)

A bare SHA is resolved against BlarAI. Work that lands in a sibling repository
of the constellation is cited by NAMING that repository:

    finding | FIXED | agentic-setup@59fc51d - one line on what the fix does

and the SHA is then resolved *in agentic-setup*. This exists because half of a
cross-repo arc could previously not be recorded honestly at all: a sibling SHA
was rejected by a check that only knew BlarAI, so the only way to make a record
green was to cite a BRANCH NAME instead - and a branch name in a repository
nobody resolves is a label, not evidence. That substitution is the failure this
control was built to refuse, arriving through the control's own door. The fix
is to check the citation, not to tolerate it.

Consequences, all deliberate:

  * only the names in ``KNOWN_REPOS`` are accepted - an allowlist, because a
    citation into a repository nobody can locate is an unchecked claim;
  * a repository the machine cannot open is a FAILURE, never a skip. Absence
    is the one thing a verifier must never read as consent;
  * the sibling door takes a SHA only. A ``branch/name`` still satisfies the
    BlarAI form (records predating this rely on it), but it is not admitted
    across a repository boundary, where it is exactly the evasion above;
  * the qualified token is consumed FIRST, so the SHA half of a sibling
    citation is never re-read as a BlarAI SHA - and, symmetrically, a BlarAI
    SHA mislabelled ``agentic-setup@...`` fails, because the check follows the
    name it was given rather than looking for somewhere the SHA does resolve.

HONEST LIMIT, stated because a control that overstates its coverage is the
exact defect class this repository keeps re-learning (see #978 probe 2, whose
own comment discloses that it passes vacuously once corrected):

    This verifies the FORM of a disposition once one exists. It cannot detect
    a review whose findings were never written down at all. That gap is closed
    by doctrine (CLAUDE.md <decision_boundary>) and by the ship motion, NOT by
    this script. Do not read a green run as "every finding was dispositioned" -
    read it as "every finding that was recorded was dispositioned honestly."

Exit code: 0 only when every row passes; non-zero on any violation, malformed
row, or missing/duplicate block.

Usage (from repo root, or anywhere with ``--repo``):
  python scripts/verify_disposition.py docs/reviews/<disposition>.md
  python scripts/verify_disposition.py <file> --repo C:/Users/mrbla/BlarAI
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from functools import lru_cache
from pathlib import Path

BLOCK_RE = re.compile(r"```disposition\s*\n(.*?)```", re.S)

STATUSES = ("FIXED", "DEFERRED", "REJECTED")

#: A commit-ish: a 7-40 hex SHA, or a ``kind/branch-name`` ref.
COMMITISH_RE = re.compile(r"\b(?:[0-9a-f]{7,40}\b|[a-z]+/[A-Za-z0-9._-]+)")

#: A SHA with no repository named. Resolved against BlarAI.
BARE_SHA_RE = re.compile(r"\b[0-9a-f]{7,40}\b")

#: ``<repo>@<sha>`` - evidence in a NAMED sibling repository. The trailing
#: lookahead keeps a hex-looking domain (``x@deadbeef.com``) from reading as a
#: citation; the hex half is required, per the sibling-door rule in the module
#: docstring.
QUALIFIED_RE = re.compile(r"\b([A-Za-z][A-Za-z0-9._-]*)@([0-9a-f]{7,40})(?![0-9A-Za-z._-])")

#: The repository whose history a bare SHA is read against.
HOME_REPO = "blarai"

#: The repositories a row may cite, lowercased, per CLAUDE.md
#: <repo_constellation>, plus windows-containment-evidence, the public
#: repository the containment measurements are published to (a review of a
#: folder there is dispositioned here). An allowlist: a name that is not here
#: is refused rather than searched for, so a typo cannot become a directory probe.
KNOWN_REPOS: tuple[str, ...] = (HOME_REPO, "agentic-setup", "devplatform", "windows-containment-evidence")

#: A named repository followed by something that is not a resolvable SHA -
#: the branch-name substitution arriving through the sibling door. Scanned
#: only after the valid citations have been struck out.
SIBLING_NON_SHA_RE = re.compile(r"\b([A-Za-z][A-Za-z0-9._-]*)@(\S*)")

#: Overrides the directory the sibling repositories are looked up under.
#: Unset, it is the parent of the BlarAI checkout that owns this script. It
#: moves WHERE a citation is resolved, never WHETHER it is.
CONSTELLATION_ROOT_ENV = "BLARAI_CONSTELLATION_ROOT"

TICKET_RE = re.compile(r"#\d{1,6}\b")
BLOCKED_BY_RE = re.compile(r"blocked-by:\s*(.+)$", re.I)

#: Tokens that make a predicate OBSERVABLE - a later session can check one.
OBSERVABLE_RE = re.compile(
    r"#\d{1,6}\b"  # a ticket
    r"|\b\d{4}-\d{2}-\d{2}\b"  # a date
    r"|`[^`]+`"  # a backticked file, symbol, flag or command
    r"|\b[\w./-]+\.(?:py|ps1|toml|md|json|jsonl|ya?ml)\b"  # a path
)

#: The teeth. Phrases that read like a reason and decide nothing. Matched on
#: the PREDICATE only, so prose elsewhere in the row is unaffected.
FILLER_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("bare follow-up", re.compile(r"^\W*(?:a\s+)?follow[-\s]?up\W*$", re.I)),
    ("priority hand-wave", re.compile(r"\b(?:low(?:er)?|not a?\s*high)\s+priorit(?:y|ies)\b", re.I)),
    ("comfort", re.compile(r"\b(?:feels?|seems?|is)\s+(?:safer|risky|cleaner|better)\b", re.I)),
    ("later", re.compile(r"\b(?:next\s+(?:session|time|sprint)|another\s+day|when\s+time\s+permits|"
                         r"when\s+convenient|eventually|at\s+some\s+point|down\s+the\s+line)\b", re.I)),
    ("scope dodge", re.compile(r"\b(?:out\s+of\s+scope\s+for\s+now|not\s+urgent|nice\s+to\s+have|"
                               r"can\s+wait|no\s+rush)\b", re.I)),
    ("vague settling", re.compile(r"\b(?:when|once|after)\s+(?:things?|it|this|that)\s+"
                                  r"(?:settle|settles|calm|calms|stabilis|stabiliz)\w*\b", re.I)),
)

MIN_REASON_WORDS = 6


class Row:
    __slots__ = ("lineno", "finding", "status", "evidence", "raw")

    def __init__(self, lineno: int, finding: str, status: str, evidence: str, raw: str) -> None:
        self.lineno = lineno
        self.finding = finding
        self.status = status
        self.evidence = evidence
        self.raw = raw


@lru_cache(maxsize=1)
def home_checkout() -> Path:
    """The BlarAI working tree owning this script; a worktree resolves to its main tree.

    ``--git-common-dir`` is what makes a linked worktree name the same
    constellation as the checkout it was cut from. Without it every worktree
    would look for siblings under ``.worktrees/``, where the fallback below
    leaves it - which makes sibling citations FAIL rather than pass, the safe
    direction for a lookup that could not be completed.
    """
    here = Path(__file__).resolve().parents[1]
    try:
        out = subprocess.run(
            ["git", "-C", str(here), "rev-parse", "--path-format=absolute", "--git-common-dir"],
            capture_output=True, text=True,
        )
    except OSError:
        return here
    if out.returncode != 0 or not out.stdout.strip():
        return here
    return Path(out.stdout.strip()).resolve().parent


def constellation_root() -> Path:
    """The directory the sibling repositories are looked up under."""
    override = os.environ.get(CONSTELLATION_ROOT_ENV)
    return Path(override).resolve() if override else home_checkout().parent


def repo_root_for(name: str) -> Path:
    """The working tree a citation naming ``name`` is resolved against."""
    return home_checkout() if name == HOME_REPO else constellation_root() / name


def citations(evidence: str) -> tuple[list[tuple[str, str]], list[str]]:
    """Split evidence into ``(repo, sha)`` citations, plus any shape errors.

    Qualified ``<repo>@<sha>`` tokens are consumed first and struck from the
    text, so a sibling SHA is never also read as a BlarAI SHA. Whatever hex
    survives that pass named no repository and belongs to ``HOME_REPO``.
    """
    found: list[tuple[str, str]] = []
    errors: list[str] = []

    def _take(m: re.Match[str]) -> str:
        name, sha = m.group(1), m.group(2)
        if name.lower() in KNOWN_REPOS:
            found.append((name.lower(), sha))
        else:
            errors.append(
                f"{m.group(0)!r} names repository {name!r}, which is not one of "
                f"{', '.join(KNOWN_REPOS)} - a citation into a repository nobody can "
                f"locate is an unchecked claim wearing the shape of evidence"
            )
        return " "

    remainder = QUALIFIED_RE.sub(_take, evidence)

    # Every well-formed citation is gone by now, so a surviving ``<known>@...``
    # is one that was reached for and missed the only form the door takes.
    for m in SIBLING_NON_SHA_RE.finditer(remainder):
        if m.group(1).lower() in KNOWN_REPOS:
            errors.append(
                f"{m.group(0)!r} cites {m.group(1)} with {m.group(2)!r}, which is not a "
                f"7-40 hex SHA - across a repository boundary only a SHA is evidence, "
                f"because a branch name there is a label nobody resolves"
            )

    found.extend((HOME_REPO, sha) for sha in BARE_SHA_RE.findall(remainder))
    return found, errors


def resolve_citation(repo: str, sha: str) -> str | None:
    """Return why ``sha`` fails to name a commit in ``repo``, or None when it does.

    Deny-by-default: an unreachable repository, an absent git, and a SHA that
    does not resolve are all failures. Absence is never read as consent.
    """
    root = repo_root_for(repo)
    if not (root / ".git").exists():
        return (
            f"repository {repo!r} is not reachable at {root} - a citation this machine "
            f"cannot open is unchecked, and an unchecked claim is what this control "
            f"refuses (set {CONSTELLATION_ROOT_ENV} if the constellation lives elsewhere)"
        )
    try:
        out = subprocess.run(
            ["git", "-C", str(root), "cat-file", "-e", f"{sha}^{{commit}}"],
            capture_output=True, text=True,
        )
    except OSError as exc:
        return f"cannot run git to resolve {sha} in {repo}: {exc}"
    if out.returncode != 0:
        return (
            f"{sha} does not resolve to a commit in {repo} ({root}) - evidence that "
            f"cannot be checked is not evidence"
        )
    return None


def resolve_row(row: Row) -> list[str]:
    """Every citation in a FIXED row that does not resolve. Empty list == pass.

    Only FIXED rows make an evidence claim, so only FIXED rows are resolved;
    a malformed repository NAME is caught for every status by ``check_row``,
    which needs no git to see it.
    """
    if row.status != "FIXED":
        return []
    found, _ = citations(row.evidence)
    return [reason for repo, sha in found if (reason := resolve_citation(repo, sha)) is not None]


def extract_block(text: str) -> tuple[list[Row] | None, str | None]:
    """Return (rows, error). Deny-by-default: absent or duplicate block is an error."""
    blocks = BLOCK_RE.findall(text)
    if not blocks:
        return None, (
            "no ```disposition block found - an absent block is exactly the "
            "silence this control exists to retire (deny-by-default)"
        )
    if len(blocks) > 1:
        return None, f"{len(blocks)} ```disposition blocks found - expected exactly 1"

    rows: list[Row] = []
    for i, line in enumerate(blocks[0].splitlines(), 1):
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("#"):
            # A COMMENT ONLY IF IT IS NOT A ROW. Findings are routinely written starting with
            # the ticket they belong to — "#1391 item 3 | FIXED | <sha>" — and those were
            # silently dropped here, after which this verifier printed a self-consistent
            # "N ok of N" over a population it had quietly shrunk. That is the exact defect
            # class this gate exists to catch, committed by the gate: a denominator derived
            # from what was counted rather than from what was there. Caught 2026-08-15 when a
            # record with eight rows was reported as three.
            #
            # A comment cannot be mistaken for a row and vice versa: a row has the two pipes
            # that make it parseable as one. Anything else beginning with # stays a comment.
            #
            # The one # line that HAS two pipes and is not a row is the block's own column
            # header, recognised by its literal middle field. Deliberately not "skip any #
            # line I fail to parse" — that is the silent-drop being fixed, wearing a
            # tolerance. A #-row with a typo'd status must still fail loudly.
            fields = [p.strip().lower() for p in stripped.lstrip("#").split("|")]
            is_header = len(fields) >= 2 and fields[1] == "status"
            if stripped.count("|") < 2 or is_header:
                continue
        parts = [p.strip() for p in stripped.split("|")]
        if len(parts) < 3:
            return None, f"line {i}: expected '<finding> | <status> | <evidence>', got: {stripped!r}"
        rows.append(Row(i, parts[0], parts[1].upper(), "|".join(parts[2:]).strip(), stripped))
    if not rows:
        return None, "the ```disposition block is empty - a review with no findings says so explicitly"
    return rows, None


def check_row(row: Row) -> list[str]:
    """Every failure reason for this row. Empty list == pass."""
    fails: list[str] = []

    if row.status not in STATUSES:
        return [f"unknown status {row.status!r} (expected one of {', '.join(STATUSES)})"]

    if not row.finding:
        fails.append("empty finding name")

    if "<" in row.evidence and ">" in row.evidence:
        fails.append("evidence still carries a <placeholder>")

    fails.extend(citations(row.evidence)[1])

    if row.status == "FIXED":
        if not COMMITISH_RE.search(row.evidence):
            fails.append(
                "FIXED names no commit-ish evidence (a 7-40 hex SHA or a branch/name ref) - "
                "'fixed' asserted without an artifact is the defect class this control targets"
            )

    elif row.status == "DEFERRED":
        if not TICKET_RE.search(row.evidence):
            fails.append(
                "DEFERRED names no #ticket - a deferral that is not in the durable queue the "
                "next actor reads is a dropped finding, not a deferral"
            )
        m = BLOCKED_BY_RE.search(row.evidence)
        if not m:
            fails.append(
                "DEFERRED has no 'blocked-by:' predicate - name the concrete failure the delay "
                "prevents; if you cannot name one, that is the signal to fix it now"
            )
        else:
            predicate = m.group(1).strip()
            for label, pat in FILLER_PATTERNS:
                if pat.search(predicate):
                    fails.append(
                        f"blocked-by is a filler phrase ({label}): {predicate!r} - this reads like "
                        f"a reason and decides nothing"
                    )
                    break
            else:
                if not OBSERVABLE_RE.search(predicate):
                    fails.append(
                        f"blocked-by names nothing observable: {predicate!r} - a predicate must "
                        f"reference something a later session can CHECK (a #ticket, a date, a "
                        f"`symbol`, or a file path)"
                    )

    elif row.status == "REJECTED":
        words = len(row.evidence.split())
        if words < MIN_REASON_WORDS:
            fails.append(
                f"REJECTED gives only {words} word(s) of reason (need >= {MIN_REASON_WORDS}) - "
                f"'not a defect' asserted without argument is silence in a different hat"
            )

    return fails


def verify(path: Path) -> tuple[int, list[str]]:
    """Return (exit_code, report_lines)."""
    out: list[str] = [f"Finding-disposition verification: {path}", ""]
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        return 2, out + [f"RESULT: FAIL - cannot read {path}: {exc}"]

    rows, err = extract_block(text)
    if err is not None:
        return 1, out + [f"  [FAIL] {err}", "", "RESULT: FAIL - the disposition block itself is invalid"]

    assert rows is not None
    n_fail = 0
    for row in rows:
        fails = check_row(row) + resolve_row(row)
        if fails:
            n_fail += 1
            out.append(f"  [FAIL] {row.finding} ({row.status})")
            out.extend(f"         - {f}" for f in fails)
        else:
            out.append(f"  [PASS] {row.finding:<44.44} {row.status}")

    out.append("")
    verdict = "PASS" if n_fail == 0 else "FAIL"
    out.append(f"RESULT: {verdict} - {len(rows) - n_fail} ok / {n_fail} unjustified of {len(rows)}")
    if n_fail:
        out.append(
            "  A deferral you cannot justify is a fix you have not done. "
            "Either name a checkable predicate, or do it now."
        )
    return (0 if n_fail == 0 else 1), out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Verify a BlarAI finding-disposition record.")
    ap.add_argument("path", help="the disposition markdown file")
    ap.add_argument("--repo", default=".", help="repo root (default: cwd)")
    args = ap.parse_args(argv)

    path = Path(args.path)
    if not path.is_absolute():
        candidate = Path(args.repo) / path
        path = candidate if candidate.exists() else path

    code, report = verify(path)
    print("\n".join(report))
    return code


if __name__ == "__main__":
    sys.exit(main())
