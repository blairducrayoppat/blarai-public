"""
BlarAI handoff-brief anchor verifier
====================================
Grounding step 0 for any session inheriting a handoff brief. A brief is a
*map*, not the *territory* (LESSONS.md lesson 14): its factual anchors -
commit SHAs, file paths, live-state counts, ticket references - drift out
from under the prose the moment the tree moves on. This tool re-derives
every anchor against the real repository and FAILS LOUD on any drift, so a
successor never grounds itself on a stale fact.

It enforces a required, machine-checkable ``anchors`` block in the brief
(schema below). A brief with no valid block FAILS - deny-by-default: an
absent block is exactly the ungrounded state the control exists to retire.

The ANCHORS block (fenced ```anchors) is a pipe-delimited table. Each row:

    <type> | <value> | <label> [| <derivation>]

  - ``sha``    - a commit SHA (7-40 hex). Verified: must be an ancestor of
                 ``main`` (``git merge-base --is-ancestor <sha> main``). A
                 non-ancestor means the brief predates a history change or
                 names the wrong repo.
  - ``path``   - a repo-relative file or directory path. Verified: exists.
  - ``count``  - an integer live-state count (e.g. "0 fragments awaiting
                 fold", "284 lessons"). REQUIRES a 4th field: the shell
                 command that RE-DERIVES the count on disk. Verified: the
                 command's output equals the declared integer.
  - ``ticket`` - a ``#NNN`` reference. Verified: structural well-formedness
                 only (a plain script has no board access). An optional,
                 off-by-default board probe degrades to a warning and never
                 fails - an unreachable board must never block grounding.

Any value still carrying a ``<placeholder>`` is treated as unfilled -> FAIL.

Exit code: 0 only when every hard check passes (warnings are allowed);
non-zero on any drift, malformed anchor, or missing/duplicate block.

Usage (from repo root, or anywhere with ``--repo``):
  python scripts/verify_handoff_brief.py docs/handoffs/<brief>.md
  python scripts/verify_handoff_brief.py <brief> --repo C:/Users/mrbla/BlarAI
  python scripts/verify_handoff_brief.py <brief> --main-ref main --check-board
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Literal

# A board resolver maps a ticket number to True (exists) / False (not found)
# / None (board unreachable). None and False are BOTH non-fatal - the board
# is an optional convenience, never a grounding gate.
BoardResolver = Callable[[int], "bool | None"]

AnchorType = Literal["sha", "path", "count", "ticket"]
_ANCHOR_TYPES: frozenset[str] = frozenset({"sha", "path", "count", "ticket"})

Status = Literal["PASS", "FAIL", "WARN"]

_FENCE_OPEN_RE = re.compile(r"^\s*```anchors\s*$")
_FENCE_CLOSE_RE = re.compile(r"^\s*```\s*$")
_SHA_RE = re.compile(r"^[0-9a-fA-F]{7,40}$")
_TICKET_RE = re.compile(r"^#\d+$")
_INT_RE = re.compile(r"^\d+$")
_PLACEHOLDER_RE = re.compile(r"[<>]")

_DERIVATION_TIMEOUT_S = 30


class AnchorsError(Exception):
    """A structural fault in the ANCHORS block - missing, duplicated, empty,
    or a malformed row. Fatal: the block cannot be trusted at all, so the
    whole brief fails rather than partially verifying."""


@dataclass(frozen=True)
class Anchor:
    """One parsed anchor row."""

    kind: AnchorType
    value: str
    label: str
    derivation: str | None
    lineno: int


@dataclass(frozen=True)
class AnchorResult:
    """The verdict for one anchor after checking it against reality."""

    anchor: Anchor
    status: Status
    detail: str


@dataclass
class BriefReport:
    """The full verification result for a brief."""

    brief_path: Path
    repo_root: Path
    main_ref: str
    results: list[AnchorResult] = field(default_factory=list)
    fatal: str | None = None

    @property
    def ok(self) -> bool:
        """True iff there is no fatal block error and no anchor FAILED.
        Warnings do not fail the brief."""
        if self.fatal is not None:
            return False
        return all(r.status != "FAIL" for r in self.results)

    def counts(self) -> dict[str, int]:
        out = {"PASS": 0, "FAIL": 0, "WARN": 0}
        for r in self.results:
            out[r.status] += 1
        return out


# ---------------------------------------------------------------------------
# Parsing (pure - unit-tested)
# ---------------------------------------------------------------------------


def find_anchors_block(text: str) -> tuple[str, int]:
    """Locate the single ```anchors fenced block.

    Returns ``(block_body, first_body_lineno)`` where ``first_body_lineno``
    is the 1-based line number of the first line inside the fence (so parse
    errors can cite real file lines). Raises :class:`AnchorsError` if the
    block is missing, unterminated, or appears more than once - an ambiguous
    or absent block is a fail-closed condition, not a warning.
    """
    lines = text.splitlines()
    opens = [i for i, ln in enumerate(lines) if _FENCE_OPEN_RE.match(ln)]
    if not opens:
        raise AnchorsError(
            "no ```anchors block found - every handoff brief MUST carry a "
            "machine-checkable ANCHORS block (see "
            "docs/governance/handoff-brief-template.md)"
        )
    if len(opens) > 1:
        raise AnchorsError(
            f"{len(opens)} ```anchors blocks found (lines "
            f"{', '.join(str(o + 1) for o in opens)}) - a brief must have "
            f"exactly one so verification is unambiguous"
        )
    start = opens[0]
    body: list[str] = []
    for offset, ln in enumerate(lines[start + 1 :], start=start + 1):
        if _FENCE_CLOSE_RE.match(ln):
            return "\n".join(body), start + 2
        body.append(ln)
    raise AnchorsError(
        f"```anchors block opened at line {start + 1} is never closed with a "
        f"``` fence"
    )


def parse_anchor_line(line: str, lineno: int) -> Anchor:
    """Parse one non-comment anchor row into an :class:`Anchor`.

    Splits on ``|`` into at most four fields (``type | value | label |
    derivation``); the derivation field keeps any internal ``|`` (pipelines
    such as ``... | wc -l``) because only the first three delimiters split.
    Raises :class:`AnchorsError` on any structural fault.
    """
    parts = [p.strip() for p in line.split("|", 3)]
    if len(parts) < 2 or not parts[0] or not parts[1]:
        raise AnchorsError(
            f"line {lineno}: malformed anchor row {line!r} - expected "
            f"'<type> | <value> | <label> [| <derivation>]'"
        )
    kind = parts[0].lower()
    if kind not in _ANCHOR_TYPES:
        raise AnchorsError(
            f"line {lineno}: unknown anchor type {parts[0]!r} - must be one "
            f"of {', '.join(sorted(_ANCHOR_TYPES))}"
        )
    value = parts[1]
    label = parts[2] if len(parts) >= 3 else ""
    derivation = parts[3] if len(parts) >= 4 and parts[3] else None
    if kind == "count" and not derivation:
        raise AnchorsError(
            f"line {lineno}: count anchor {value!r} has no derivation command "
            f"- a count MUST carry the on-disk command that re-derives it "
            f"(4th '|' field), so the successor never trusts a bare number"
        )
    return Anchor(
        kind=kind,  # type: ignore[arg-type]
        value=value,
        label=label,
        derivation=derivation,
        lineno=lineno,
    )


def parse_anchors(block_body: str, first_body_lineno: int = 1) -> list[Anchor]:
    """Parse the ANCHORS block body into anchors.

    Blank lines and ``#`` comment lines are ignored. Raises
    :class:`AnchorsError` if the block declares no anchors at all (an empty
    allowlist of facts defeats the control) or on any malformed row.
    """
    anchors: list[Anchor] = []
    for offset, raw in enumerate(block_body.splitlines()):
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        anchors.append(parse_anchor_line(raw, first_body_lineno + offset))
    if not anchors:
        raise AnchorsError(
            "the ```anchors block is empty - a brief must declare at least "
            "one anchor to verify (deny-by-default)"
        )
    return anchors


# ---------------------------------------------------------------------------
# Derivation execution (shell, cwd = repo root)
# ---------------------------------------------------------------------------


def _shell_argv(command: str) -> list[str]:
    """Resolve a shell to run a derivation command.

    Prefers ``bash`` (Git for Windows ships it on every BlarAI dev box), so
    POSIX one-liners with pipes (``... | wc -l``, ``grep -c ...``) work
    identically across the Windows dev machines. Falls back to the platform
    default shell only if no bash is present.
    """
    bash = shutil.which("bash")
    if bash:
        return [bash, "-c", command]
    # Fallback: platform default shell (cmd.exe on Windows).
    return command  # type: ignore[return-value]  # used with shell=True


def run_derivation(command: str, cwd: Path) -> tuple[int | None, str]:
    """Run a count-derivation command and extract its integer output.

    Returns ``(value, detail)`` where ``value`` is the derived integer, or
    ``(None, reason)`` on any failure - a non-zero exit, a timeout, or output
    that is not a single integer. Fail-closed: a derivation that cannot
    produce a clean count is a FAILURE, never a silently-skipped anchor.
    """
    argv = _shell_argv(command)
    use_shell = isinstance(argv, str)
    try:
        proc = subprocess.run(
            argv,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=_DERIVATION_TIMEOUT_S,
            shell=use_shell,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return None, f"derivation could not run: {exc}"
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "").strip()
        return None, (
            f"derivation exited {proc.returncode}"
            + (f": {err[:120]}" if err else "")
        )
    out = proc.stdout.strip()
    if not _INT_RE.match(out):
        return None, (
            f"derivation did not emit a single integer (got {out[:60]!r}) - "
            f"make it print just the count (e.g. append '| wc -l')"
        )
    return int(out), ""


# ---------------------------------------------------------------------------
# Verification (per anchor)
# ---------------------------------------------------------------------------


def _is_ancestor(sha: str, main_ref: str, repo_root: Path) -> tuple[bool | None, str]:
    """``git merge-base --is-ancestor`` probe.

    Returns ``(True, "")`` if *sha* is an ancestor of *main_ref*,
    ``(False, "")`` if it is a resolvable object that is NOT an ancestor, and
    ``(None, reason)`` if git could not resolve it at all (unknown object /
    git error) - an unresolvable SHA is fail-closed, not treated as present.
    """
    try:
        proc = subprocess.run(
            ["git", "-C", str(repo_root), "merge-base", "--is-ancestor", sha, main_ref],
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return None, f"git error: {exc}"
    if proc.returncode == 0:
        return True, ""
    if proc.returncode == 1:
        return False, ""
    # returncode 128 (or other): bad object, unknown ref, not a repo.
    return None, (proc.stderr or "git could not resolve the object").strip()


def verify_anchor(
    anchor: Anchor,
    repo_root: Path,
    main_ref: str,
    board_resolver: BoardResolver | None = None,
) -> AnchorResult:
    """Check one anchor against the real repository/disk/board."""
    if _PLACEHOLDER_RE.search(anchor.value):
        return AnchorResult(
            anchor,
            "FAIL",
            f"unfilled placeholder value {anchor.value!r} - fill in the anchor",
        )

    if anchor.kind == "sha":
        if not _SHA_RE.match(anchor.value):
            return AnchorResult(
                anchor, "FAIL", f"{anchor.value!r} is not a 7-40 char hex SHA"
            )
        ok, reason = _is_ancestor(anchor.value, main_ref, repo_root)
        if ok is True:
            return AnchorResult(anchor, "PASS", f"ancestor of {main_ref}")
        if ok is False:
            return AnchorResult(
                anchor,
                "FAIL",
                f"NOT an ancestor of {main_ref} - brief predates a history "
                f"change, or names another repo",
            )
        return AnchorResult(
            anchor, "FAIL", f"git could not resolve {anchor.value} ({reason})"
        )

    if anchor.kind == "path":
        rel = anchor.value
        if Path(rel).is_absolute() or ".." in Path(rel).parts:
            return AnchorResult(
                anchor,
                "FAIL",
                f"path {rel!r} must be repo-relative (no absolute paths, no "
                f"'..' escapes)",
            )
        target = repo_root / rel
        if target.exists():
            kind = "dir" if target.is_dir() else "file"
            return AnchorResult(anchor, "PASS", f"exists ({kind})")
        return AnchorResult(anchor, "FAIL", "MISSING on disk")

    if anchor.kind == "count":
        try:
            expected = int(anchor.value)
        except ValueError:
            return AnchorResult(
                anchor, "FAIL", f"count value {anchor.value!r} is not an integer"
            )
        assert anchor.derivation is not None  # guaranteed by parse
        derived, reason = run_derivation(anchor.derivation, repo_root)
        if derived is None:
            return AnchorResult(anchor, "FAIL", reason)
        if derived == expected:
            return AnchorResult(
                anchor, "PASS", f"derived {derived} == {expected}"
            )
        return AnchorResult(
            anchor,
            "FAIL",
            f"derived {derived} != {expected} (declared) - count has drifted",
        )

    # ticket
    if not _TICKET_RE.match(anchor.value):
        return AnchorResult(
            anchor, "FAIL", f"malformed ticket ref {anchor.value!r} (want '#NNN')"
        )
    if board_resolver is None:
        return AnchorResult(anchor, "PASS", "well-formed (board check off)")
    number = int(anchor.value[1:])
    try:
        exists = board_resolver(number)
    except Exception as exc:  # noqa: BLE001 - board must never fail grounding
        return AnchorResult(
            anchor, "WARN", f"well-formed; board probe errored ({exc}) - ignored"
        )
    if exists is True:
        return AnchorResult(anchor, "PASS", "well-formed; board: ticket exists")
    if exists is False:
        return AnchorResult(
            anchor,
            "WARN",
            "well-formed; board reports no such ticket (closed/renumbered?)",
        )
    return AnchorResult(anchor, "WARN", "well-formed; board unreachable")


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def detect_repo_root(start: Path) -> Path:
    """Best-effort repo root via ``git rev-parse --show-toplevel``.

    Falls back to the current working directory if *start* is not inside a
    git work tree.
    """
    base = start if start.is_dir() else start.parent
    try:
        proc = subprocess.run(
            ["git", "-C", str(base), "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if proc.returncode == 0 and proc.stdout.strip():
            return Path(proc.stdout.strip())
    except (OSError, subprocess.SubprocessError):
        pass
    return Path.cwd()


def verify_brief(
    brief_path: Path,
    repo_root: Path,
    main_ref: str = "main",
    board_resolver: BoardResolver | None = None,
) -> BriefReport:
    """Verify every anchor in *brief_path* and return a :class:`BriefReport`.

    Never raises for a fault in the brief itself: a structural block error
    becomes ``report.fatal`` (and ``report.ok`` is False), so the CLI always
    prints a clean report and exits non-zero.
    """
    report = BriefReport(brief_path=brief_path, repo_root=repo_root, main_ref=main_ref)
    try:
        text = brief_path.read_text(encoding="utf-8")
    except OSError as exc:
        report.fatal = f"cannot read brief: {exc}"
        return report
    try:
        body, first_line = find_anchors_block(text)
        anchors = parse_anchors(body, first_line)
    except AnchorsError as exc:
        report.fatal = str(exc)
        return report
    for anchor in anchors:
        report.results.append(
            verify_anchor(anchor, repo_root, main_ref, board_resolver)
        )
    return report


def render_report(report: BriefReport) -> str:
    """Human-readable report. Lead with the verdict; one line per anchor."""
    lines: list[str] = []
    lines.append(f"Handoff-brief anchor verification: {report.brief_path}")
    lines.append(f"  repo: {report.repo_root}   main-ref: {report.main_ref}")
    lines.append("")
    if report.fatal is not None:
        lines.append(f"  [FATAL] {report.fatal}")
        lines.append("")
        lines.append("RESULT: FAIL - the ANCHORS block itself is invalid")
        return "\n".join(lines)
    for r in report.results:
        a = r.anchor
        label = f"  {a.label}" if a.label else ""
        lines.append(f"  [{r.status}] {a.kind:6} {a.value:<28} {r.detail}{label}")
    lines.append("")
    c = report.counts()
    verdict = "PASS" if report.ok else "FAIL"
    lines.append(
        f"RESULT: {verdict} - {c['PASS']} ok / {c['FAIL']} drifted-or-malformed "
        f"/ {c['WARN']} warning(s)"
    )
    return "\n".join(lines)


def _null_board_resolver(_number: int) -> bool | None:
    """The CLI's --check-board resolver: this script carries no network
    client by design (BlarAI dev tooling stays off the wire unless a feature
    requires it), so every ticket reports 'board unreachable' -> WARN. Tests
    inject a real resolver to exercise the exists/missing paths."""
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Verify a handoff brief's factual anchors against the live repo."
    )
    parser.add_argument("brief", help="path to the handoff brief markdown file")
    parser.add_argument(
        "--repo",
        default=None,
        help="repo root (default: auto-detected from the brief's location)",
    )
    parser.add_argument(
        "--main-ref",
        default="main",
        help="the ref SHAs must be ancestors of (default: main)",
    )
    parser.add_argument(
        "--check-board",
        action="store_true",
        help="attempt an optional board probe for ticket anchors (degrades "
        "to a warning; never fails - this script has no network client)",
    )
    args = parser.parse_args(argv)

    brief_path = Path(args.brief)
    if not brief_path.exists():
        print(f"error: brief not found: {brief_path}", file=sys.stderr)
        return 2
    repo_root = Path(args.repo) if args.repo else detect_repo_root(brief_path)
    board = _null_board_resolver if args.check_board else None

    report = verify_brief(brief_path, repo_root, args.main_ref, board)
    print(render_report(report))
    return 0 if report.ok else 1


if __name__ == "__main__":
    sys.exit(main())
