"""Documentation frontmatter lint for the BlarAI doc-lifecycle convention.

Convention: ``docs/governance/doc-lifecycle.md``. Ticket: Vikunja #267.
Advisory/report tool — not wired into the standing test gate (see the convention doc
and this package's README for why).
"""
from __future__ import annotations

from tools.doc_lint.lint import (
    CANONICAL_STATUSES,
    REQUIRED_FIELDS,
    STATUS_ALIASES,
    Finding,
    FileReport,
    LintReport,
    check_file,
    check_paths,
    iter_markdown,
    parse_frontmatter,
)

__all__ = [
    "CANONICAL_STATUSES",
    "REQUIRED_FIELDS",
    "STATUS_ALIASES",
    "Finding",
    "FileReport",
    "LintReport",
    "check_file",
    "check_paths",
    "iter_markdown",
    "parse_frontmatter",
]
