"""
Eval Harness — Runner CLI
==========================
Usage (from the repo root):

    python -m evals.run --suite governance
    python -m evals.run --suite all --report evals_report.json
    python -m evals.run --suite pa_classification --write-baseline
    python -m evals.run --suite pa_classification --include-hardware   # Arc 140V only

Exit codes:
    0 — all evaluated cases compared clean against the committed baselines
        (known-fails tracked in the baseline stay 0 — they are recorded
        deficiencies, not regressions).
    1 — REGRESSION vs baseline: a baseline-passing case now fails/errors, a
        new case fails without being baselined, or a baselined case
        disappeared from the golden set.
    2 — harness error: unknown suite, missing/malformed golden data, or a
        missing/malformed baseline (fail-closed — an uncomparable run is
        never a silent success).

``--write-baseline`` refreshes evals/baselines/<suite>.json from the current
run and exits 0 (no comparison) — refreshing a baseline is a deliberate,
reviewed act: the diff shows exactly which case statuses changed.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from evals import baseline as baseline_mod
from evals.baseline import BaselineError, Comparison
from evals.loader import GoldenDataError
from evals.model_target import (
    CAPABILITY_CHOICES,
    ModelTarget,
    ModelTargetError,
    resolve_model_target,
)
from evals.suites import SUITE_NAMES, get_runner
from evals.types import SuiteReport

EXIT_OK: int = 0
EXIT_REGRESSION: int = 1
EXIT_HARNESS_ERROR: int = 2


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m evals.run",
        description="BlarAI model-quality eval harness (#717).",
    )
    parser.add_argument(
        "--suite",
        required=True,
        choices=(*SUITE_NAMES, "all"),
        help="Suite to run, or 'all' for every suite.",
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=None,
        help="Optional path to write the full JSON report.",
    )
    parser.add_argument(
        "--baseline-dir",
        type=Path,
        default=baseline_mod.BASELINE_DIR,
        help="Baseline directory (default: evals/baselines/).",
    )
    parser.add_argument(
        "--write-baseline",
        action="store_true",
        help="Refresh the committed baseline(s) from this run instead of comparing.",
    )
    parser.add_argument(
        "--include-hardware",
        action="store_true",
        help=(
            "Run model-in-the-loop cases on the real GPU (Arc 140V only; "
            "NEVER in CI — loads the Qwen3-14B model)."
        ),
    )
    parser.add_argument(
        "--model-dir",
        type=Path,
        default=None,
        help=(
            "OPT-IN hardware model-target override (#931): load an arbitrary "
            "OpenVINO model directory instead of the default Qwen3-14B. Requires "
            "--capability. No override => byte-identical default 14B path. Only "
            "affects --include-hardware runs."
        ),
    )
    parser.add_argument(
        "--capability",
        choices=CAPABILITY_CHOICES,
        default=None,
        help=(
            "Capability contract for --model-dir: 'text-llm' (LLMPipeline, the "
            "14B contract) or 'multimodal-vlm' (VLMPipeline, e.g. the 35B-A3B). "
            "Required whenever --model-dir is given — the pipeline class is never "
            "guessed (fail-closed)."
        ),
    )
    parser.add_argument(
        "--no-speculative",
        action="store_true",
        help=(
            "For a 'text-llm' --model-dir override, load WITHOUT speculative "
            "decoding (no pruned draft). Ignored for 'multimodal-vlm' (which has "
            "no draft-model spec-decode for this pipeline class)."
        ),
    )
    return parser


def _print_summary(
    report: SuiteReport, comparison: Comparison | None
) -> None:
    agg = report.aggregates()
    line = (
        f"[{report.suite}] {agg['passed']}/{agg['evaluated']} passed "
        f"({agg['pass_rate']:.1%}), {agg['failed']} failed, "
        f"{agg['errors']} errors, {agg['skipped_hardware']} hardware-skipped, "
        f"{agg['tool_calls']} tool-call"
    )
    print(line)
    if comparison is not None:
        if comparison.regressions:
            print(f"[{report.suite}] REGRESSIONS vs baseline:")
            for item in comparison.regressions:
                print(f"  - {item}")
        if comparison.improvements:
            print(
                f"[{report.suite}] improvements vs baseline (consider "
                f"--write-baseline): {', '.join(comparison.improvements)}"
            )
        if comparison.known_failures:
            print(
                f"[{report.suite}] known-fail cases tracked in baseline: "
                f"{', '.join(comparison.known_failures)}"
            )
        if comparison.known_tool_calls:
            print(
                f"[{report.suite}] known tool-call cases tracked in baseline "
                f"(unscorable one-shot, #1023): "
                f"{', '.join(comparison.known_tool_calls)}"
            )


def main(argv: list[str] | None = None) -> int:
    """Run the eval harness. Returns the process exit code."""
    args = _build_parser().parse_args(argv)
    suites = list(SUITE_NAMES) if args.suite == "all" else [args.suite]

    # Resolve the OPT-IN hardware model-target override once (fail-closed: a
    # malformed override is a harness error, exit 2 — never a silent default).
    try:
        model_target: ModelTarget | None = resolve_model_target(
            model_dir=args.model_dir,
            capability=args.capability,
            no_speculative=args.no_speculative,
        )
    except ModelTargetError as exc:
        print(f"HARNESS ERROR: {exc}", file=sys.stderr)
        return EXIT_HARNESS_ERROR
    if model_target is not None and not args.include_hardware:
        print(
            "HARNESS ERROR: --model-dir/--capability was given without "
            "--include-hardware — the override only affects model-in-the-loop "
            "hardware cases (fail-closed; refusing a run that would silently "
            "ignore the override).",
            file=sys.stderr,
        )
        return EXIT_HARNESS_ERROR

    full_report: dict[str, Any] = {"suites": {}, "regressions": []}
    any_regression = False

    for suite_name in suites:
        try:
            runner = get_runner(suite_name)
            report = runner(
                include_hardware=args.include_hardware, model_target=model_target
            )
        except (GoldenDataError, KeyError) as exc:
            print(f"[{suite_name}] HARNESS ERROR: {exc}", file=sys.stderr)
            return EXIT_HARNESS_ERROR

        suite_block: dict[str, Any] = report.to_dict()

        if args.write_baseline:
            path = baseline_mod.write_baseline(report, args.baseline_dir)
            print(f"[{suite_name}] baseline written: {path}")
            comparison = None
        else:
            try:
                base = baseline_mod.load_baseline(suite_name, args.baseline_dir)
            except BaselineError as exc:
                print(f"[{suite_name}] HARNESS ERROR: {exc}", file=sys.stderr)
                return EXIT_HARNESS_ERROR
            comparison = baseline_mod.compare(report, base)
            suite_block["baseline_comparison"] = comparison.to_dict()
            if comparison.has_regressions:
                any_regression = True
                full_report["regressions"].extend(
                    f"{suite_name}: {r}" for r in comparison.regressions
                )

        full_report["suites"][suite_name] = suite_block
        _print_summary(report, comparison)

    if args.report is not None:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(
            json.dumps(full_report, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        print(f"report written: {args.report}")

    if any_regression:
        print("RESULT: REGRESSION (exit 1)", file=sys.stderr)
        return EXIT_REGRESSION
    print("RESULT: OK (exit 0)")
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
