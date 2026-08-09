"""SMOKE TEST — does the operator-facing GREEN-quality path still RUN after #1223?

A green pytest is not evidence that `green_audit` still executes on the real path.
`battery.py:1698-1712` wraps the whole audit in `try/except Exception` and substitutes
`{}` on any fault, and `battery.py:1949` then renders NOTHING when the block is empty.
So a #1223 regression that breaks the audit would show up on the night as a summary with
no green-quality line at all — silent, and indistinguishable from "no GREENs tonight"
(that is #1241 row 3, still open under #1245).

This script therefore calls `audit_greens` DIRECTLY, outside that guard, so a fault is a
traceback rather than an empty dict. Run it before trusting a merge to an unattended run.

Usage:  <venv python> scripts/smoke_green_quality_path.py
Exit 0 = the real path ran and produced a rendered KPI line. Exit 1 = it did not.
"""
from __future__ import annotations

import json
import sys
import tempfile
import traceback
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

FAILURES: list[str] = []


def step(label: str) -> None:
    print(f"\n=== {label} ===", flush=True)


def main() -> int:
    print(f"repo root : {REPO_ROOT}")
    print(f"python    : {sys.executable}")

    # ---- 1. import-time integrity -------------------------------------------------
    step("1. imports (a syntax error here is what silently empties the night)")
    from tools.dispatch_harness import green_quality as ga
    from tools.dispatch_harness import green_audit
    from tools.dispatch_harness.green_quality import layer1
    from tools.dispatch_harness.scorecard import Scorecard
    import shared.instrument_registry as ireg
    print("green_quality, green_audit, layer1, Scorecard, instrument_registry: OK")
    print(f"registered instruments: {len(ireg.REGISTRY)}")

    # ---- 2. a REAL deliverable tree on disk ----------------------------------------
    step("2. build a real deliverable tree")
    tmp = Path(tempfile.mkdtemp(prefix="smoke-green-"))
    projects = tmp / "projects"
    repo_name = "battery-b2-text-stats"
    repo = projects / repo_name
    (repo / "src").mkdir(parents=True)
    (repo / "tests").mkdir(parents=True)
    (repo / "src" / "stats.py").write_text(
        "def mean(xs):\n"
        "    if not xs:\n"
        "        raise ValueError('empty')\n"
        "    return sum(xs) / len(xs)\n",
        encoding="utf-8",
    )
    (repo / "tests" / "test_stats.py").write_text(
        "from src.stats import mean\n\n\n"
        "def test_mean():\n"
        "    assert mean([1, 2, 3]) == 2\n",
        encoding="utf-8",
    )
    (repo / "README.md").write_text("# text stats\n\nComputes a mean.\n", encoding="utf-8")
    runs = tmp / "runs"
    (runs / "r1").mkdir(parents=True)
    out = tmp / "out"
    out.mkdir()
    print(f"tree: {repo}")

    # ---- 3. the real production entry point, NO exception guard ---------------------
    step("3. audit_greens() -- the exact call battery.py:1704 makes")
    sc = Scorecard(job_id="B2", verdict="GREEN", repo=repo_name, run_id="r1")
    block = ga.audit_greens(
        [sc],
        runs_dir=runs,
        out_dir=out,
        projects_dir=projects,
        log=lambda m: print(f"  [log] {m}"),
    )
    print(json.dumps(block, indent=2, default=str)[:2500])
    if not block:
        FAILURES.append(
            "audit_greens returned an EMPTY block. On the real night battery.py swallows "
            "this and the summary carries no green-quality line at all."
        )
    elif not block.get("audited"):
        FAILURES.append(f"audit_greens ran but audited=0 (block keys: {sorted(block)})")

    # ---- 4. the line the operator actually reads ------------------------------------
    step("4. render_kpi() -- the operator-facing line")
    kpi = ga.render_kpi(block)
    for line in kpi:
        print(f"  {line}")
    if not kpi:
        FAILURES.append("render_kpi returned NO lines -- the operator sees nothing.")

    # ---- 5. green_audit directly ----------------------------------------------------
    step("5. green_audit.scan_tree() on the real tree")
    try:
        res = green_audit.scan_tree(repo)
        print(f"  result: {res}")
        # #1223 gives this result an honesty bit: an unscanned tree must not read 'clean'.
        print(f"  audited={getattr(res, 'audited', '<no audited attr>')}  "
              f"gamed={getattr(res, 'gamed', '<no gamed attr>')}")
    except Exception:
        FAILURES.append("green_audit.scan_tree RAISED on a healthy tree")
        traceback.print_exc()

    step("5b. scan_tree() on a directory that does NOT exist -- the honesty case")
    try:
        missing = green_audit.scan_tree(tmp / "does-not-exist")
        print(f"  result: {missing}")
        print(f"  audited={getattr(missing, 'audited', '<no audited attr>')}  "
              f"gamed={getattr(missing, 'gamed', '<no gamed attr>')}")
        if getattr(missing, "audited", None) is True:
            FAILURES.append(
                "scan_tree reported audited=True for a directory that does not exist "
                "-- that is the defect class #1223 exists to close."
            )
    except Exception:
        FAILURES.append("green_audit.scan_tree RAISED on a missing tree")
        traceback.print_exc()

    # ---- 6. the #1244 defect, live on this tree -------------------------------------
    step("6. run_ruff_advisory() -- #1244: does it say 'measured' on a run that failed?")
    val = layer1.run_ruff_advisory(repo)
    print(f"  run_ruff_advisory(clean tree) -> {val!r}   (None = NOT RUN, int = a count)")

    step("VERDICT")
    if FAILURES:
        for f in FAILURES:
            print(f"  FAIL: {f}")
        return 1
    print("  PASS: the real audit path ran end to end and rendered an operator line.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        print("\n=== SMOKE RAISED -- this is the failure battery.py would have hidden ===")
        traceback.print_exc()
        sys.exit(1)
