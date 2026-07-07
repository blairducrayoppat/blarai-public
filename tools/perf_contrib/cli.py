"""CLI entry-point for the BlarAI perf-contribution pipeline.

Usage
-----
    python -m tools.perf_contrib validate [<path>...]
    python -m tools.perf_contrib aggregate [--perf-dir <dir>] [--out-dir <dir>]

Subcommands
-----------
validate
    Validate one or more perf JSON files against the community schema.
    Exits 0 if all pass, 1 if any fail.
    When no paths are given, validates all ``harness_*.json`` files in
    ``docs/performance/``.

aggregate
    Validate + scrub + aggregate all harness records into the publishable
    dataset (JSONL + CSV).  Reports what was included and what was skipped.

Neither subcommand makes any network calls or writes outside the repo tree.
Submission to OpenVINO / HuggingFace is a deliberate manual act by the
User-Operator after reviewing the output.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from tools.perf_contrib.aggregator import PERF_DIR, aggregate
from tools.perf_contrib.schema import validate


def _cmd_validate(args: argparse.Namespace) -> int:
    paths: list[Path]
    if args.paths:
        paths = [Path(p) for p in args.paths]
    else:
        paths = sorted(PERF_DIR.glob("harness_*.json"))
        if not paths:
            print(f"No harness_*.json files found in {PERF_DIR}", file=sys.stderr)
            return 1

    all_valid = True
    for path in paths:
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            print(f"FAIL  {path.name}: could not parse — {exc}")
            all_valid = False
            continue

        result = validate(record)
        status = "PASS" if result.valid else "FAIL"
        print(f"{status}  {path.name}")
        if not result.valid:
            all_valid = False
            for err in result.errors:
                print(f"      ERROR: {err}")
        for warn in result.warnings:
            print(f"      WARN:  {warn}")

    return 0 if all_valid else 1


def _cmd_aggregate(args: argparse.Namespace) -> int:
    perf_dir = Path(args.perf_dir) if args.perf_dir else None
    out_dir = Path(args.out_dir) if args.out_dir else None

    report = aggregate(perf_dir=perf_dir, out_dir=out_dir)
    report.print_summary()
    return 0 if report.valid_count > 0 else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="perf_contrib",
        description="BlarAI perf-contribution pipeline: validate + aggregate perf records.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # validate subcommand
    p_val = sub.add_parser("validate", help="Validate perf JSON files against the community schema.")
    p_val.add_argument(
        "paths",
        nargs="*",
        metavar="FILE",
        help="JSON files to validate. Defaults to all harness_*.json in docs/performance/.",
    )

    # aggregate subcommand
    p_agg = sub.add_parser(
        "aggregate",
        help="Aggregate valid harness records into publishable CSV + JSONL.",
    )
    p_agg.add_argument(
        "--perf-dir",
        default=None,
        metavar="DIR",
        help="Override the docs/performance/ source directory.",
    )
    p_agg.add_argument(
        "--out-dir",
        default=None,
        metavar="DIR",
        help="Directory to write outputs (default: same as perf-dir).",
    )

    args = parser.parse_args(argv)
    if args.command == "validate":
        return _cmd_validate(args)
    if args.command == "aggregate":
        return _cmd_aggregate(args)
    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
