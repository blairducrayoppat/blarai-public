"""Build the publishable form of docs/performance/gate_runtime_2026-10-07/ (#1699).

scripts/hf_publish.py accepts only .json/.jsonl/.csv/.md/.txt, CSV columns from a fixed metric list, and no
raw logs. The raw gzip logs stay in the repository; this writes the derived tables the public dataset carries:

  runs.csv            one row per timed run: arm, rep, status, wall_ms, passed, failed, total
  parallel_runs.csv   the same columns for every parallel-gate run (#1707), failed ones included
  per_file_ms.csv     one row per (arm, rep, test file): summed setup+call+teardown milliseconds
  summary.json        conditions, per-arm statistics, idle/power/CPU facts from the samplers, authored notes

Usage: python scripts/build_gate_runtime_dataset.py [--src DIR] [--out DIR]
"""
from __future__ import annotations

import argparse
import csv
import gzip
import json
import re
import statistics
from pathlib import Path

SRC_DEFAULT = Path("docs/performance/gate_runtime_2026-10-07")
ARMS = {  # arm id -> (state file, run arm key, log directory)
    "old_3be0e22e_wt": ("timing_runs/state.json", "old", "timing_runs"),
    "new_ca4fab46_wt": ("timing_runs/state.json", "new", "timing_runs"),
    "fixed_f407d2af_wt": ("post_fix_runs/state.json", "fixed", "post_fix_runs"),
    "fixed_f407d2af_real": ("post_fix_runs/state.json", "real", "post_fix_runs"),
}
PARALLEL_RUNS = {  # file number -> arm id; the runner's own output files in parallel_gate/
    "01": "parallel_g4_pre_order_fix", "02": "parallel_g6_pre_order_fix", "03": "parallel_g3_pre_order_fix",
    "04": "parallel_g3_canary_leak", "05": "parallel_g3_canary_leak", "06": "parallel_g3_canary_leak",
    "08": "parallel_g3_tail", "09": "parallel_g3_tail", "10": "parallel_g3_tail",
    "11": "parallel_g5_tail", "12": "parallel_g6_tail", "13": "parallel_g6_tail", "14": "parallel_g6_tail",
}
RESULT = re.compile(r"^= (?P<body>.*?) in (?P<secs>[\d.]+)s \(parallel x\d+\) =", re.M)
ROW = re.compile(r"^([\d.]+)s (call|setup|teardown)\s+(\S+)", re.M)


def per_file_ms(log: Path) -> dict[tuple[str, str], int]:
    text = gzip.open(log, "rt", encoding="utf-8", errors="replace").read()
    out: dict[tuple[str, str], float] = {}
    for dur, _k, node in ROW.findall(text):
        path = node.split("::")[0].replace("\\", "/")
        suite, _, name = path.rpartition("/")
        # hf_publish accepts an id cell of at most 48 characters: drop ".py" and abbreviate the longest directory
        suite, name = suite.replace("assistant_orchestrator", "ao"), name.removesuffix(".py")
        out[(suite, name)] = out.get((suite, name), 0.0) + float(dur) * 1000
    return {k: round(v) for k, v in out.items()}


def parallel_rows(src: Path) -> list[list]:
    rows, reps = [], {}
    for path in sorted((src / "parallel_gate").glob("[0-9][0-9]_*.out")):
        arm = PARALLEL_RUNS.get(path.name[:2])
        if arm is None:
            continue
        m = None
        for m in RESULT.finditer(path.read_text(encoding="utf-8", errors="replace")):
            pass
        if m is None:
            raise SystemExit(f"{path.name} has no parallel result line")
        counts = {k: int(n) for n, k in re.findall(r"(\d+) (passed|failed)", m.group("body"))}
        reps[arm] = reps.get(arm, 0) + 1
        passed, failed = counts.get("passed", 0), counts.get("failed", 0)
        rows.append([arm, reps[arm], "clean" if not failed else "failed", round(float(m.group("secs")) * 1000), passed, failed, passed + failed])
    return rows


def sampler_facts(csv_path: Path, idle_at_start: float) -> dict:
    rows = list(csv.DictReader(csv_path.open(encoding="utf-8")))
    return {"samples": len(rows), "all_ac": all(r["power"] == "AC" for r in rows),
            "max_cpu_pct": max(int(r["cpu_pct"]) for r in rows),
            "idle_never_below_start_idle": all(float(r["idle_s"]) >= idle_at_start for r in rows)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default=str(SRC_DEFAULT))
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    src = Path(a.src)
    out = Path(a.out) if a.out else src / "hf_publish"
    out.mkdir(parents=True, exist_ok=True)
    runs_rows, file_rows, arm_stats, sampler = [], [], {}, {}
    for arm_id, (state_rel, key, logdir) in ARMS.items():
        state = json.loads((src / state_rel).read_text(encoding="utf-8"))
        runs = [r for r in state["runs"] if r["arm"] == key and r["status"] == "clean"]
        for rep, r in enumerate(runs, 1):
            stem = f"run{r['n']:02d}-{key}"
            runs_rows.append([arm_id, rep, "clean", round(r["wall_s"] * 1000), r.get("passed", 0), r.get("failed", 0),
                              r.get("passed", 0) + r.get("failed", 0) + r.get("skipped", 0)])
            for (suite, name), ms in sorted(per_file_ms(src / logdir / f"{stem}.log.gz").items()):
                file_rows.append([arm_id, rep, suite, name, ms])
            sampler[f"{arm_id}#{rep}"] = {"idle_at_start_s": r["idle_at_start_s"],
                                          **sampler_facts(src / logdir / f"{stem}.samples.csv", r["idle_at_start_s"])}
        walls = [r["wall_s"] for r in runs]
        arm_stats[arm_id] = {"runs": len(runs), "wall_s": walls, "mean_s": round(statistics.mean(walls), 1),
                             "spread_pct": round(100 * (max(walls) - min(walls)) / min(walls), 1),
                             "skipped": runs[0].get("skipped"), "deselected": runs[0].get("deselected")}
    with (out / "runs.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["arm", "rep", "status", "wall_ms", "passed", "failed", "total"])
        w.writerows(runs_rows)
    par = parallel_rows(src) if (src / "parallel_gate").is_dir() else []
    if par:
        with (out / "parallel_runs.csv").open("w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["arm", "rep", "status", "wall_ms", "passed", "failed", "total"])
            w.writerows(par)
    with (out / "per_file_ms.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["arm", "rep", "suite", "case_id", "wall_ms"])
        w.writerows(file_rows)
    mean_ms: dict[str, dict[tuple[str, str], float]] = {}
    for arm_id in ("old_3be0e22e_wt", "new_ca4fab46_wt"):
        rows = [r for r in file_rows if r[0] == arm_id]
        reps = len({r[1] for r in rows})
        acc: dict[tuple[str, str], float] = {}
        for _a, _rep, suite, name, ms in rows:
            acc[(suite, name)] = acc.get((suite, name), 0.0) + ms / reps
        mean_ms[arm_id] = acc
    keys = set(mean_ms["old_3be0e22e_wt"]) | set(mean_ms["new_ca4fab46_wt"])
    delta = sorted(((mean_ms["new_ca4fab46_wt"].get(k, 0.0) - mean_ms["old_3be0e22e_wt"].get(k, 0.0), k) for k in keys), reverse=True)
    git_files = [(d, k) for d, k in delta if k[1].startswith("test_git_")]
    difference = {
        "from": "old_3be0e22e_wt", "to": "new_ca4fab46_wt",
        "summed_test_s_old": round(sum(mean_ms["old_3be0e22e_wt"].values()) / 1000, 1),
        "summed_test_s_new": round(sum(mean_ms["new_ca4fab46_wt"].values()) / 1000, 1),
        "net_s": round(sum(d for d, _ in delta) / 1000, 1),
        "test_git_files_s": round(sum(d for d, _ in git_files) / 1000, 1), "test_git_files": len(git_files),
        "largest": [{"suite": k[0], "case_id": k[1], "old_s": round(mean_ms["old_3be0e22e_wt"].get(k, 0.0) / 1000, 1),
                     "new_s": round(mean_ms["new_ca4fab46_wt"].get(k, 0.0) / 1000, 1)} for _d, k in delta[:12]],
    }
    summary = {
        "conditions": {
            "cpu": "Intel Core Ultra 7 258V (Lunar Lake), 8 cores / 8 threads", "memory_gb": 31.32,
            "os": "Windows 11 Pro 10.0.26200", "python": "3.11.9", "pytest": "8.4.2", "git": "2.55.0.windows.1",
            "selection": "shared/ services/ launcher/ tests/integration/ tests/security/ -m not hardware and not winui and not slow",
            "flags": "-p no:cacheprovider --durations=0 -rfs; LOCALAPPDATA redirected per run; elevated; AC power",
            "start_rule": "input idle >= 900 s, AC, CPU < 15 %, no other pytest; void on any input, non-AC, intruder, 300 s silent log",
            "voided_runs": 0,
        },
        "arms": arm_stats,
        "parallel": {a: {"runs": [r[3] / 1000 for r in par if r[0] == a], "failed": [r[5] for r in par if r[0] == a]}
                     for a in dict.fromkeys(r[0] for r in par)},
        "difference": difference,
        "sampler": sampler,
        "notes": {
            "what_this_is": "Wall clock of a software test suite on a laptop; it is CPU and process-spawn bound, not an inference measurement.",
            "controlled": "old_3be0e22e_wt and new_ca4fab46_wt alternated on one idle box; fixed_* ran later the same evening.",
            "worktrees": "Worktree arms have no model weights, so 5-6 tests fail and 26 skip for environmental reasons in each.",
            "real_vs_worktree": "The real-checkout arm runs 26 more tests (models present); its wall clock is not comparable to the worktree arms.",
            "not_measured": "Variance across days, thermal and scanner state, the slow tier, a real-checkout run before the fix under the instrument.",
            "per_file_ms": "Sum of setup, call and teardown from pytest --durations=0; tests under 5 ms are omitted, so sums sit 2 to 5 % under wall clock.",
            "parallel": "parallel_runs.csv rows come from scripts/run_standing_gate.py output; the _tail arms run the fixed-port files alone afterwards; canary_leak rows are the runs that failed on a test-order leak, kept as evidence.",
            "ids": "case_id is the test file name without .py; suite is its directory with assistant_orchestrator abbreviated to ao.",
        },
    }
    (out / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"{len(runs_rows)} runs, {len(file_rows)} per-file rows -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
