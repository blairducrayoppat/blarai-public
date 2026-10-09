"""How long are the search queries this repository has actually banked? (#1592)

`MAX_DISCLOSABLE_QUERY_CHARS` is a cap on what may leave, and a cap that nobody
can re-derive is a threshold somebody picked wearing the clothes of a
measurement. The #1592 review found exactly that: the record stated "97 literals,
3 to 46 characters, median 13", and no single population produces all four
figures — 97 belongs to one corpus and (3, 46, 13) to another. Every number was
individually real and together they described nothing.

This script is the method, committed so the figure is re-runnable by whoever
doubts it.

**THE METHOD, stated exactly, because that is the part that was missing.**

  population : every string literal bound to the key or keyword ``query`` in a
               TRACKED file (``git ls-files``) with extension .py / .json /
               .jsonl, parsed per-language rather than by regex — Python via
               ``ast`` (keyword arguments and dict literals), JSON/JSONL via
               ``json`` (object members, at any depth)
  excluded   : nothing. No minimum length, no maximum, no directory filter
  dedup      : NONE — a query used in ten fixtures counts ten times, because the
               question is what queries this repository contains, not how many
               distinct ones. The deduplicated figures are printed alongside so
               the choice is visible rather than silent
  reported   : n, min, max, median, and the longest literal itself

What it does NOT measure, said plainly: this is a corpus of FIXTURES. There has
been no production use of this system, so it bounds what queries developers
WRITE, not what an operator would ask. It is silent on the tail of the real
distribution, and it is partly self-referential — test fixtures added by the very
commit that cites it are counted.

Usage:  python tools/probes/census_query_literals.py [--repo PATH] [--json]
"""

from __future__ import annotations

import argparse
import ast
import json
import statistics
import subprocess
import sys
from pathlib import Path

_EXTENSIONS = frozenset({".py", ".json", ".jsonl"})
_KEY = "query"


def _tracked_files(repo: Path) -> list[Path]:
    """Every file git tracks, so an untracked scratch file cannot move the figure."""
    out = subprocess.run(
        ["git", "-C", str(repo), "ls-files"],
        capture_output=True,
        text=True,
        check=True,
    )
    return [
        repo / line
        for line in out.stdout.splitlines()
        if line and Path(line).suffix in _EXTENSIONS
    ]


def _from_python(source: str) -> list[str]:
    """Keyword arguments named ``query`` and dict entries keyed ``"query"``.

    AST rather than regex: a regex cannot tell a call from a comment, and cannot
    tell a dict key from a parameter that happens to share its name.
    """
    found: list[str] = []
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return found
    for node in ast.walk(tree):
        if isinstance(node, ast.keyword) and node.arg == _KEY:
            if isinstance(node.value, ast.Constant) and isinstance(
                node.value.value, str
            ):
                found.append(node.value.value)
        elif isinstance(node, ast.Dict):
            for key, value in zip(node.keys, node.values):
                if (
                    isinstance(key, ast.Constant)
                    and key.value == _KEY
                    and isinstance(value, ast.Constant)
                    and isinstance(value.value, str)
                ):
                    found.append(value.value)
    return found


def _from_json_object(obj: object, found: list[str]) -> None:
    """Every ``query`` member at any depth."""
    if isinstance(obj, dict):
        for key, value in obj.items():
            if key == _KEY and isinstance(value, str):
                found.append(value)
            _from_json_object(value, found)
    elif isinstance(obj, list):
        for item in obj:
            _from_json_object(item, found)


def _from_json(source: str, jsonl: bool) -> list[str]:
    found: list[str] = []
    chunks = source.splitlines() if jsonl else [source]
    for chunk in chunks:
        if not chunk.strip():
            continue
        try:
            _from_json_object(json.loads(chunk), found)
        except json.JSONDecodeError:
            continue
    return found


def census(repo: Path) -> dict[str, object]:
    literals: list[str] = []
    for path in _tracked_files(repo):
        try:
            source = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if path.suffix == ".py":
            literals.extend(_from_python(source))
        else:
            literals.extend(_from_json(source, jsonl=path.suffix == ".jsonl"))

    lengths = sorted(len(literal) for literal in literals)
    unique = sorted({literal for literal in literals}, key=len)
    unique_lengths = [len(literal) for literal in unique]
    longest = max(literals, key=len) if literals else ""
    return {
        "n": len(literals),
        "min": lengths[0] if lengths else 0,
        "max": lengths[-1] if lengths else 0,
        "median": statistics.median(lengths) if lengths else 0,
        "n_unique": len(unique),
        "median_unique": (
            statistics.median(unique_lengths) if unique_lengths else 0
        ),
        "longest": longest,
        "repo_head": subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip(),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=None, help="repo root (default: this file's)")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    args = parser.parse_args(argv)

    repo = Path(args.repo) if args.repo else Path(__file__).resolve().parents[2]
    result = census(repo)

    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0

    print(f"query-literal census at {result['repo_head']}  (tracked .py/.json/.jsonl)")
    print(f"  n         {result['n']}   (deduplicated: {result['n_unique']})")
    print(f"  min       {result['min']}")
    print(f"  max       {result['max']}")
    print(f"  median    {result['median']}   (deduplicated: {result['median_unique']})")
    print(f"  longest   {result['longest']!r}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
