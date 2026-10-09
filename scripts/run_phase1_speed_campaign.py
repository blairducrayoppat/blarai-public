"""Interleaved speed campaign for #1663 Phase 1 (GPU-exclusive, serial).

One invocation per arm in the interleave on the 2026.4 interpreter (the three
arms of each ``--sizes`` size, any ``--reference`` arms, and the 14B as a
runtime-confound control; arm order rotated each invocation and the first arm
repeated at the end for ABA drift bracketing) alternating with one on the 2026.2.1
interpreter (the 14B exactly as it ships). The default (``--sizes 4b``, no
reference) is eight invocations. A cool-down separates invocations. One status
file; the campaign writes the single ``{"done": true}`` line at the very end.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))

import phase1_sizes as sizes  # noqa: E402

PY_2026_4 = "C:/Users/mrbla/BlarAI/.venv-2026.4/Scripts/python.exe"
PY_SHIP = "C:/Users/mrbla/BlarAI/.venv/Scripts/python.exe"
import tempfile

SANDBOX = str(Path(tempfile.gettempdir()) / "blarai_eval_localappdata")



def build_orders(size_list: list[str], reference: list[str]) -> list[list[str]]:
    """Arm orders of the 2026.4 invocations: the base interleave (each size's three
    CB arms in canonical order, then the reference arms, then ``14b-ship``) rotated
    one place per invocation, the first arm of each rotation repeated at the end."""
    base: list[str] = []
    for s in dict.fromkeys(size_list):  # a repeated size must not repeat its arms
        base.extend(sizes.cb_arms(s))
    for r in reference:
        if r not in base:
            base.append(r)
    base.append(sizes.ARM_14B)
    return [base[i:] + base[:i] + [base[i]] for i in range(len(base))]


ORDERS = build_orders(["4b"], [])  # the Phase 1 default


def main() -> int:
    ap = argparse.ArgumentParser(allow_abbrev=False)
    ap.add_argument("--out-dir", type=Path, required=True)
    ap.add_argument("--status-file", type=Path, required=True)
    ap.add_argument("--cooldown", type=int, default=120)
    ap.add_argument("--cold-temp", type=float, default=72.0)
    ap.add_argument("--sizes", default="4b", help="comma list of sizes whose three CB arms are interleaved")
    ap.add_argument("--reference", default="", help="comma list of extra CB arms interleaved as references, e.g. 4b-mtp-on")
    for s in sizes.SIZES:
        ap.add_argument(f"--model-{s}", default=None, help=f"override the {s} model directory")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    size_list = [x.strip() for x in a.sizes.split(",") if x.strip()]
    reference = list(dict.fromkeys(x.strip() for x in a.reference.split(",") if x.strip()))
    if not size_list:
        ap.error("--sizes is empty: name at least one size (known: " + ", ".join(sizes.SIZES) + ")")
    for s in size_list:
        if s not in sizes.SIZES:
            ap.error(f"unknown size {s!r}; known: {', '.join(sizes.SIZES)}")
    for r in reference:
        if sizes.parse_arm(r) is None:
            ap.error(f"--reference {r!r} is not a CB arm name")
    dir_flags: list[str] = []
    for s in sizes.SIZES:
        if getattr(a, f"model_{s}"):
            dir_flags += [f"--model-{s}", getattr(a, f"model_{s}")]
    out_dir = a.out_dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    status = a.status_file.resolve()

    jobs = []
    for i, order in enumerate(build_orders(size_list, reference), 1):
        jobs.append((f"A{i}-2026.4", PY_2026_4, order))
        jobs.append((f"B{i}-2026.2.1", PY_SHIP, ["14b-ship"]))
    if a.dry_run:
        for tag, py, arms in jobs:
            print(tag, py, arms)
        return 0

    def log(row: dict) -> None:
        with open(status, "a", encoding="utf-8") as fh:
            fh.write(json.dumps({"t": time.strftime("%Y-%m-%dT%H:%M:%S%z"), **row}) + chr(10))

    env = dict(os.environ, LOCALAPPDATA=SANDBOX)
    Path(SANDBOX).mkdir(parents=True, exist_ok=True)
    for n, (tag, py, arms) in enumerate(jobs):
        if n:
            time.sleep(a.cooldown)
        log({"job_start": tag, "arms": arms})
        cmd = [
            py, str(REPO / "scripts/bench_qwen35_speed.py"),
            "--arms", ",".join(arms), "--rounds", "1", "--protocol", "both", "--reps", "3",
            "--cells", "pa,ao-long,multiturn", "--multiturn-turns", "1,3,6",
            "--cold-temp", str(a.cold_temp), "--cold-cells", "pa,ao-long,multiturn:t1",
            "--status-file", str(out_dir / f"{tag}_status.jsonl"),
            "--out", str(out_dir / f"{tag}.json"), "--tag", tag,
        ]
        cmd += dir_flags
        with open(out_dir / f"{tag}.out", "w", encoding="utf-8") as so, open(out_dir / f"{tag}.err", "w", encoding="utf-8") as se:
            code = subprocess.run(cmd, stdout=so, stderr=se, env=env, cwd=str(REPO)).returncode
        log({"job_end": tag, "exit": code})
        if code != 0:
            log({"job_failed": tag, "exit": code})
    log({"done": True, "campaign": "speed"})
    return 0


if __name__ == "__main__":
    sys.exit(main())
