"""Command-line entry point for the documentation frontmatter lint (Vikunja #267).

Usage::

    python -m tools.doc_lint                 # scan top-level docs/*.md (report)
    python -m tools.doc_lint docs services   # scan explicit paths
    python -m tools.doc_lint --json docs     # machine-readable report
    python -m tools.doc_lint --recursive docs
    python -m tools.doc_lint --strict docs   # warnings also fail the run

Exit code is 0 when the run passes (no violations; under --strict, no warnings
either) and 1 otherwise — so the tool can be gated later without code changes, while
staying advisory (unwired from the standing gate) today.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

from tools.doc_lint.lint import LintReport, check_paths

_DEFAULT_PATHS: tuple[str, ...] = ("docs",)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m tools.doc_lint",
        description=(
            "Advisory frontmatter lint for the BlarAI doc-lifecycle convention "
            "(docs/governance/doc-lifecycle.md). Reports docs missing required "
            "lifecycle frontmatter."
        ),
    )
    parser.add_argument(
        "paths",
        nargs="*",
        default=list(_DEFAULT_PATHS),
        help="files or directories to scan (default: docs). Directories scan their "
        "direct *.md children unless --recursive is given.",
    )
    parser.add_argument(
        "-r",
        "--recursive",
        action="store_true",
        help="descend into subdirectories (skips node_modules/_validate/.git/etc.)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="emit a machine-readable JSON report instead of text",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="treat warnings as failures (exit non-zero on warnings too)",
    )
    parser.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        help="suppress the per-finding text lines; print only the summary",
    )
    return parser


def _render_text(report: LintReport, *, strict: bool, quiet: bool) -> str:
    lines: list[str] = []
    if not quiet:
        for file_report in report.files:
            for finding in file_report.findings:
                marker = "FAIL" if finding.level == "violation" else "warn"
                lines.append(
                    f"{marker}: {finding.path.as_posix()}: "
                    f"[{finding.code}] {finding.message}"
                )
    verdict = "PASS" if report.passed(strict=strict) else "FAIL"
    lines.append(
        f"{verdict}: {len(report.files)} scanned, "
        f"{len(report.compliant_files)} compliant, "
        f"{len(report.violations)} violation(s), "
        f"{len(report.warnings)} warning(s)"
    )
    if report.ok and not report.warnings:
        return "\n".join(lines)
    if report.ok and report.warnings and not strict:
        lines.append(
            "note: no violations; warnings are advisory (use --strict to fail on them)"
        )
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    report = check_paths(
        [Path(p) for p in args.paths], recursive=args.recursive
    )

    if args.json:
        payload = report.to_dict()
        payload["passed"] = report.passed(strict=args.strict)
        print(json.dumps(payload, indent=2))
    else:
        print(_render_text(report, strict=args.strict, quiet=args.quiet))

    return 0 if report.passed(strict=args.strict) else 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
