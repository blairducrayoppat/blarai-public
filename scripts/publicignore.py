"""The one implementation of the ``.publicignore`` matching rules.

``.publicignore`` (repository root, tracked) lists the tracked paths the public snapshot leaves out. The publisher in the
agentic-setup repository re-implements these rules in PowerShell; this module is the REFERENCE, and the conformance table
``scripts/publicignore_cases.json`` is the shared test of both (the Python lock reads it here, the publisher runs it before it
trusts its own matcher).

THE RULES (the same text heads ``.publicignore``)
-------------------------------------------------
* One pattern per line. Blank lines and lines whose first non-space character is ``#`` are ignored. No inline comments.
* A pattern is matched against the whole repository-relative path of a tracked file, forward slashes, no leading ``/``.
* Matching ignores ASCII letter case (``A-Z`` fold to ``a-z`` on both sides; nothing else folds).
* ``*`` matches any run of characters except ``/``. ``**`` matches any run including ``/``; ``**/`` also matches nothing, so
  ``a/**/b`` matches ``a/b``. ``?`` matches one character except ``/``. Every other character matches itself.
* A pattern that matches a directory matches everything beneath it, so ``docs/old`` and ``docs/old/`` exclude the tree.
* Anything else is an ERROR, never a guess: a leading ``!`` or ``/``, a backslash, a ``.`` or ``..`` segment, a control or
  non-ASCII character. A file that does not parse excludes nothing and the caller must stop.

``load`` raises ``PublicIgnoreError`` when the file is missing or malformed; an empty list (no pattern lines) is valid and
excludes nothing. ``Ruleset.excluded_paths`` is the filter the publisher applies; the CLI prints it for a revision.

Run:  python scripts/publicignore.py                  excluded paths of the working checkout (``git ls-files``)
      python scripts/publicignore.py --rev main       the list as the publisher computes it (rules read from the revision)
Exit 1 when the list has patterns and excludes nothing (a list that matches nothing is a broken list).
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

REPO_ROOT = Path(__file__).resolve().parents[1]
IGNORE_FILE = ".publicignore"

_ASCII_FOLD = {c: c + 32 for c in range(ord("A"), ord("Z") + 1)}


class PublicIgnoreError(ValueError):
    """The list cannot be read, or a line or a path is outside the rules. Callers stop; they never fall back."""


def fold(text: str) -> str:
    """ASCII-only lower-casing, identical to what the publisher does."""
    return text.translate(_ASCII_FOLD)


def _glob_to_regex(pattern: str) -> str:
    out: list[str] = []
    i, n = 0, len(pattern)
    while i < n:
        c = pattern[i]
        if c == "*":
            if pattern.startswith("**/", i):
                out.append("(?:.*/)?")
                i += 3
            elif pattern.startswith("**", i):
                out.append(".*")
                i += 2
            else:
                out.append("[^/]*")
                i += 1
        elif c == "?":
            out.append("[^/]")
            i += 1
        else:
            out.append(re.escape(c))
            i += 1
    return "".join(out)


def _check_pattern(line: str, where: str) -> None:
    if line[0] in "!/":
        raise PublicIgnoreError(f"{where}: a pattern may not start with {line[0]!r} (negation and absolute paths are not supported)")
    if "\\" in line:
        raise PublicIgnoreError(f"{where}: a backslash is not allowed; write forward slashes")
    if any(ord(ch) < 32 or ord(ch) > 126 for ch in line):
        raise PublicIgnoreError(f"{where}: only printable ASCII is allowed (a byte-order mark or a control character is a defect)")
    if any(seg in (".", "..") for seg in line.split("/")):
        raise PublicIgnoreError(f"{where}: a '.' or '..' segment is not allowed")


@dataclass(frozen=True)
class Rule:
    line_no: int
    text: str
    regex: "re.Pattern[str]"

    def matches(self, folded_path: str) -> bool:
        return self.regex.fullmatch(folded_path) is not None


@dataclass(frozen=True)
class Ruleset:
    rules: tuple[Rule, ...]

    def __len__(self) -> int:
        return len(self.rules)

    def matches(self, path: str) -> bool:
        check_path(path)
        folded = fold(path)
        return any(r.matches(folded) for r in self.rules)

    def excluded_paths(self, tracked: Iterable[str]) -> list[str]:
        return [p for p in tracked if self.matches(p)]


def check_path(path: str) -> None:
    if not path or path.startswith("/") or "\\" in path or any(seg in (".", "..") for seg in path.split("/")):
        raise PublicIgnoreError(f"not a repository-relative forward-slash path: {path!r}")


def parse(text: str, source: str = IGNORE_FILE) -> Ruleset:
    rules: list[Rule] = []
    for line_no, raw in enumerate(text.split("\n"), 1):
        line = raw.strip(" \t\r")
        if not line or line.startswith("#"):
            continue
        _check_pattern(line, f"{source}:{line_no}")
        body = line[:-1] if line.endswith("/") else line
        if not body:
            raise PublicIgnoreError(f"{source}:{line_no}: empty pattern")
        regex = re.compile(_glob_to_regex(fold(body)) + "(?:/.*)?", re.DOTALL)
        rules.append(Rule(line_no, line, regex))
    return Ruleset(tuple(rules))


def load(path: str | Path | None = None) -> Ruleset:
    p = Path(path) if path is not None else REPO_ROOT / IGNORE_FILE
    try:
        data = p.read_bytes()
    except OSError as exc:
        raise PublicIgnoreError(f"cannot read {p}: {exc}") from exc
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise PublicIgnoreError(f"{p} is not UTF-8: {exc}") from exc
    return parse(text, str(p))


def matches(path: str, rules: Ruleset | None = None) -> bool:
    return (rules if rules is not None else load()).matches(path)


def excluded_paths(tracked: Iterable[str], rules: Ruleset | None = None) -> list[str]:
    return (rules if rules is not None else load()).excluded_paths(tracked)


def _git(root: Path, *args: str) -> bytes:
    try:
        done = subprocess.run(["git", "-C", str(root), "-c", "core.quotepath=false", *args], capture_output=True, check=True)
    except (OSError, subprocess.CalledProcessError) as exc:
        detail = exc.stderr.decode("utf-8", "replace").strip() if isinstance(exc, subprocess.CalledProcessError) else str(exc)
        raise PublicIgnoreError(f"git {' '.join(args)} failed: {detail}") from exc
    return done.stdout


def tracked_paths(root: Path, rev: str | None = None) -> list[str]:
    """Tracked paths of the index (``rev`` None) or of a revision's tree, NUL-separated so no path is ever quoted."""
    raw = _git(root, "ls-files", "-z") if rev is None else _git(root, "ls-tree", "-r", "--name-only", "-z", rev)
    return [p.decode("utf-8") for p in raw.split(b"\0") if p]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", type=Path, default=REPO_ROOT)
    ap.add_argument("--rev", help="read the list and the tracked paths from this revision instead of the working checkout")
    args = ap.parse_args(argv)
    try:
        if args.rev:
            text = _git(args.root, "show", f"{args.rev}:{IGNORE_FILE}").decode("utf-8")
            rules = parse(text, f"{args.rev}:{IGNORE_FILE}")
        else:
            rules = load(args.root / IGNORE_FILE)
        hit = rules.excluded_paths(tracked_paths(args.root, args.rev))
    except PublicIgnoreError as exc:
        print(f"publicignore: {exc}", file=sys.stderr)
        return 2
    for p in hit:
        print(p)
    if len(rules) and not hit:
        print("publicignore: the list has patterns and excludes nothing", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
