"""ADR-013 Layer-2 prompt-injection heuristic scanner — the single in-tree detector.

Untrusted content (a loaded document, a cleaned ingest, an external fetch, a
web-search page) may carry text crafted to manipulate the assistant ("prompt
injection"). This module owns the ONE pattern table and scan function every
surface uses — moved here from ``services.ui_gateway.src.document_loader``
(#896), which had grown three cross-boundary importers treating it as "the
single in-tree implementation" (``shared.security.guarded_fetch``,
``services.cleaner.src.sanitize``, and now the web-search loop). The gateway
module keeps a byte-compatible re-export, so its public surface is unchanged.

The scan is a heuristic WARNING signal, not a load-blocking guard: heuristics
false-positive, and content may legitimately discuss these phrasings (a page
*about* prompt injection, for instance). It is one layer of defense-in-depth —
the deterministic layer is delimiter neutralization in the context manager,
and the output backstop is the PGOV delimiter-echo check. Consumers choose the
response: the document path surfaces the findings to the user; the web-search
path truncates the flagged page (ADR-024 §2.5).
"""

from __future__ import annotations

import re

# (description, pattern) -- description is surfaced to the user if the pattern hits.
_INJECTION_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("an instruction to ignore prior instructions",
     re.compile(r"(?i)\bignore\s+(?:\w+\s+){0,3}(?:instruction|prompt|context|rule|direction)s?\b")),
    ("an instruction to disregard prior instructions",
     re.compile(r"(?i)\bdisregard\s+(?:\w+\s+){0,3}(?:instruction|prompt|context|rule|direction)s?\b")),
    ("an instruction to override prior instructions",
     re.compile(r"(?i)\boverride\s+(?:\w+\s+){0,3}(?:instruction|prompt|rule)s?\b")),
    ("a role-reassignment attempt (\"you are now ...\")",
     re.compile(r"(?i)\byou\s+are\s+now\b")),
    ("a reference to the \"system prompt\"",
     re.compile(r"(?i)\bsystem\s+prompt\b")),
    ("a new- or updated-instructions directive",
     re.compile(r"(?i)\b(?:new|updated|revised)\s+(?:instruction|directive)s?\b")),
    ("a \"reply only with ...\" directive",
     re.compile(r"(?i)\b(?:reply|respond|answer|output|say|print)\s+(?:only|exclusively)\s+with\b")),
    ("a forged internal framing token (<|...|>)",
     re.compile(r"<\|[A-Za-z0-9_]+\|>")),
]


def scan_for_injection(text: str) -> list[str]:
    """Heuristically scan untrusted content for prompt-injection patterns.

    Args:
        text: Content to scan.

    Returns:
        Human-readable descriptions of suspicious patterns found, deduplicated
        and in a stable order. An empty list means nothing matched. This is a
        warning signal -- not, by itself, a blocking guard (each consuming
        surface decides its response).
    """
    found: list[str] = []
    for description, pattern in _INJECTION_PATTERNS:
        if pattern.search(text) and description not in found:
            found.append(description)
    return found
