"""Per-file time of a pytest run made with --durations=0, and the difference between two arms (#1699).

Reads the "slowest durations" section of each log (setup + call + teardown per test, summed per
test file) and, for two arms, the mean per file over that arm's logs. A pytest run omits tests
under 5 ms from that section, so the sum is a few percent below the wall clock; the report
prints both so the gap is visible.

Usage: python scripts/gate_duration_report.py --arm old=LOG[,LOG...] --arm new=LOG[,LOG...] [--json OUT] [--top N]
"""
from __future__ import annotations

import argparse
import collections
import gzip
import json
import re
from pathlib import Path

ROW = re.compile(r"^([\d.]+)s (call|setup|teardown)\s+(\S+)", re.M)
SUMMARY = re.compile(r"=+ (?P<body>.*?) in (?P<secs>[\d.]+)s")


def read(path: Path) -> str:
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8", errors="replace") as f:
        return f.read()


def per_file(text: str) -> tuple[dict[str, float], float | None]:
    d: dict[str, float] = collections.defaultdict(float)
    for dur, _kind, node in ROW.findall(text):
        d[node.split("::")[0]] += float(dur)
    wall = None
    for m in SUMMARY.finditer(text):
        wall = float(m.group("secs"))
    return dict(d), wall


def arm_mean(logs: list[Path]) -> tuple[dict[str, float], list[float], list[float | None]]:
    parts = [per_file(read(p)) for p in logs]
    keys = set().union(*[p[0] for p in parts])
    mean = {k: sum(p[0].get(k, 0.0) for p in parts) / len(parts) for k in keys}
    return mean, [sum(p[0].values()) for p in parts], [p[1] for p in parts]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--arm", action="append", required=True, help="NAME=LOG[,LOG...]")
    ap.add_argument("--json")
    ap.add_argument("--top", type=int, default=20)
    a = ap.parse_args()
    arms = {}
    for spec in a.arm:
        name, logs = spec.split("=", 1)
        arms[name] = arm_mean([Path(x) for x in logs.split(",")])
    out: dict = {"arms": {}, "files": {}}
    for name, (mean, sums, walls) in arms.items():
        out["arms"][name] = {"summed_test_seconds_per_run": [round(x, 1) for x in sums],
                             "pytest_wall_seconds_per_run": walls, "runs": len(sums)}
        print(f"{name}: summed test seconds per run {[round(x) for x in sums]}, pytest wall {walls}")
    names = list(arms)
    if len(names) == 2:
        base, new = names
        keys = set(arms[base][0]) | set(arms[new][0])
        rows = sorted(((arms[new][0].get(k, 0.0) - arms[base][0].get(k, 0.0), k) for k in keys), reverse=True)
        out["net_delta_seconds"] = round(sum(r[0] for r in rows), 1)
        print(f"net delta ({new} - {base}): {out['net_delta_seconds']} s")
        for delta, k in rows[: a.top]:
            out["files"][k] = {base: round(arms[base][0].get(k, 0.0), 1), new: round(arms[new][0].get(k, 0.0), 1),
                               "delta": round(delta, 1)}
            print(f"{delta:8.1f}  {base}={arms[base][0].get(k, 0.0):7.1f}  {new}={arms[new][0].get(k, 0.0):7.1f}  {k}")
    if a.json:
        Path(a.json).write_text(json.dumps(out, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
