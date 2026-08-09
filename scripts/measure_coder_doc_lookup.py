"""Measure what the CODER's doc lookup returns for CODER-shaped questions.

This is deliberately NOT the planner measurement. The planner asks a whole goal
("build me a website where I can track my water intake"); the coder asks a
concrete named gap mid-build -- an error string, an API name, a "how do I X".
#746's own design calls that PULL not PUSH, fired only on a concrete gap.

So the 5-of-9-wrong result measured on planner goals this morning says nothing
about this rung, and inheriting it would be the "documentation is not evidence"
mistake aimed inward.

Reads only. No egress. Prints a table for judgement, and does NOT compute a
pass/fail -- whether a page is ABOUT the question is a human call, and a script
that scored itself here would be exactly the vacuous instrument we keep finding.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(r"C:\Users\mrbla\BlarAI")
sys.path.insert(0, str(REPO))

from shared.research.lookup import search_docs, exact_lookup, RELEVANCE_FLOOR  # noqa: E402
from shared.research.docset_index import load_index  # noqa: E402

# Three classes. The coder hits all three in a real build.
ERROR_TEXT = [
    "TypeError: unsupported operand type(s) for +: 'int' and 'str'",
    "AttributeError: 'NoneType' object has no attribute 'get'",
    "json.decoder.JSONDecodeError: Expecting value",
    "fixture 'tmp_path' not found",
]
API_NAMES = [
    "json.dumps",
    "pathlib.Path.read_text",
    "argparse.ArgumentParser.add_subparsers",
    "unittest.mock.patch",
    "hypothesis.given",
    "pytest.raises",
]
HOW_DO_I = [
    "read a csv file with the csv module",
    "parse command line arguments with subcommands",
    "write a temporary file that is deleted on close",
    "run a subprocess and capture its output",
    "escape html in a template",
    "sort a list of dicts by a key",
]
# Controls: things the corpus should NOT confidently answer.
CONTROLS = [
    "purple elephant birthday cake recipe",
    "how do I change the oil in a 1998 Honda Civic",
    "django queryset annotate",  # plausible-but-absent: django is not in the corpus
]


def show(label: str, queries: list[str]) -> None:
    print(f"\n{'=' * 78}\n{label}\n{'=' * 78}")
    for q in queries:
        exact = exact_lookup(q)
        hits = search_docs(q, k=3)
        ex = f"EXACT:{exact[0].title}" if exact else "exact:-"
        if not hits:
            print(f"  {q[:52]:<54} | {ex:<28} | NOTHING ABOVE FLOOR")
            continue
        top = hits[0]
        rest = ", ".join(h.title[:22] for h in hits[1:3])
        print(f"  {q[:52]:<54} | {ex:<28} | {top.score:.3f} {top.title[:34]}")
        if rest:
            print(f"  {'':<54} | {'':<28} |       then: {rest}")


def main() -> int:
    idx = load_index()
    print(f"corpus: {idx.n_pages} pages   RELEVANCE_FLOOR = {RELEVANCE_FLOOR}")
    show("A. ERROR TEXT -- what the coder pastes when a build fails", ERROR_TEXT)
    show("B. API NAMES -- the deterministic-first rung #746 asked for", API_NAMES)
    show("C. HOW DO I -- plain language, but a NAMED concrete gap", HOW_DO_I)
    show("D. CONTROLS -- must NOT answer confidently", CONTROLS)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
