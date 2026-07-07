"""CLI — run real-model latency scenarios and record community-grade perf data.

    python -m tests.harness                  # all scenarios, record a perf JSON each
    python -m tests.harness --scenario vlm   # just the image-question scenario
    python -m tests.harness --scenario chat  # just the 14B chat scenario
    python -m tests.harness --no-record      # print only; write nothing

This is the "boot BlarAI and see the issue without the User-Operator" entry
point. An agent runs it to measure chat / image / routing latency on the REAL
models; the numbers land in ``docs/performance/`` as the OpenVINO-on-Lunar-Lake
dataset the User-Operator contributes upstream (CLAUDE.md testing-data mandate).

Run heavy GPU scenarios one at a time (``--scenario vlm`` / ``--scenario chat``)
when measuring in isolation — co-residency on the 31.3 GB ceiling is its own
slowness driver and should not contaminate a single-model number by accident.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from typing import Any, Callable

from tests.harness import scenarios
from tests.harness.latency import write_perf_record

_SKIP_PRINT = {"samples", "methodology", "reply_preview", "description_preview"}


def _run(name: str, fn: Callable[[], dict[str, Any]], record: bool) -> dict[str, Any]:
    print(f"\n=== scenario: {name} ===")
    try:
        result = fn()
    except Exception as exc:  # noqa: BLE001 — a present-but-broken model FAILS, not skips
        print(f"  FAIL — {type(exc).__name__}: {exc}")
        return {"available": False, "failed": True, "reason": str(exc)}
    if not result.get("available"):
        print(f"  SKIP — {result.get('reason')}")
        return result

    for key, value in result.items():
        if key not in _SKIP_PRINT:
            print(f"  {key}: {value}")
    preview = result.get("reply_preview") or result.get("description_preview")
    if preview:
        print(f"  preview: {preview!r}")

    if record:
        path = write_perf_record(
            name,
            result,
            when_iso=datetime.now(timezone.utc).isoformat(),
            model=str(result.get("model", name)),
            precision=str(result.get("precision", "unknown")),
            methodology=str(result.get("methodology", "")),
        )
        print(f"  recorded -> {path}")
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m tests.harness",
        description="BlarAI headless real-model latency harness (#563).",
    )
    parser.add_argument(
        "--scenario",
        choices=[*scenarios.SCENARIOS, "all"],
        default="all",
        help="which scenario(s) to run (default: all)",
    )
    parser.add_argument(
        "--no-record",
        action="store_true",
        help="print only; do not write a perf JSON to docs/performance/",
    )
    args = parser.parse_args(argv)

    if args.scenario == "all":
        # Run each scenario in its OWN process so OpenVINO GPU memory is fully
        # reclaimed between heavy scenarios (only process exit frees it —
        # BUILD_JOURNAL lesson 29), keeping co-residency out of the numbers.
        import subprocess
        import sys

        rc = 0
        for name in scenarios.SCENARIOS:
            cmd = [sys.executable, "-m", "tests.harness", "--scenario", name]
            if args.no_record:
                cmd.append("--no-record")
            rc |= subprocess.run(cmd).returncode
        return rc

    _run(args.scenario, scenarios.SCENARIOS[args.scenario], record=not args.no_record)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
