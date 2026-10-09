"""Continuous system-conditions sampler for measurement campaigns (#1663).

A number without its conditions is not a measurement. This records, once per
``--interval`` seconds, the things that were running while a measurement ran:

* CPU % (whole machine), process count, thread count
* RAM In-Use = Total - Available (never working-set sums), plus commit
* the top processes by CPU in that interval (name + %)
* whether Bitdefender and OneDrive processes are present, and their CPU %
* thermal-zone temperature, passive limit %, throttle reasons, CPU perf %
* the GPU engine utilisation is NOT sampled here (not measured: no stable
  counter on this driver); a campaign report must say so.

One JSON object per line; stop it with Ctrl-C / process kill. Summarise with
``--summarise FILE`` (min / mean / max per field over the file).
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

WATCHED = {
    "bitdefender": ("bdservicehost", "bdagent", "vsserv", "bdredline", "epsecurityservice", "epintegrationservice", "bdntwrk"),
    "onedrive": ("onedrive",),
}


_THERMAL_COUNTERS = (
    r"\Thermal Zone Information(*)\Temperature",
    r"\Thermal Zone Information(*)\% Passive Limit",
    r"\Thermal Zone Information(*)\Throttle Reasons",
    r"\Processor Information(_Total)\% Processor Performance",
)


def read_thermal(timeout: float = 8.0) -> dict:
    """Thermal-zone temperature (C), passive limit %, throttle reasons, CPU perf %.

    Read through ``typeperf`` (one sample). Sustained GPU decode on this laptop
    throttles by ~3x within a minute (#1663 variance probe), so every speed
    measurement carries these next to it. Returns ``{}`` when the counters are
    unavailable - never raises, and a reader must treat a missing field as
    NOT MEASURED, not as zero.
    """
    import csv
    import io
    import subprocess

    try:
        out = subprocess.run(
            ["typeperf", "-sc", "1", *_THERMAL_COUNTERS],
            capture_output=True, text=True, timeout=timeout,
        ).stdout
        rows = [r for r in csv.reader(io.StringIO(out)) if r]
        vals = [float(v) for v in rows[1][1:5]]
    except Exception:  # noqa: BLE001 - absent counters are reported as absent
        return {}
    return {
        "temp_c": round(vals[0] - 273.15, 1),
        "passive_limit_pct": vals[1],
        "throttle_reasons": vals[2],
        "cpu_perf_pct": round(vals[3], 1),
    }


def sample(psutil, last_cpu: dict) -> dict:
    vm = psutil.virtual_memory()
    procs = []
    present = {k: 0 for k in WATCHED}
    present_cpu = {k: 0.0 for k in WATCHED}
    threads = 0
    n = 0
    for p in psutil.process_iter(["pid", "name", "num_threads"]):
        try:
            name = (p.info["name"] or "").lower()
            cpu = p.cpu_percent(None)
            threads += p.info["num_threads"] or 0
            n += 1
            procs.append((cpu, name))
            for key, needles in WATCHED.items():
                if any(name.startswith(x) for x in needles):
                    present[key] += 1
                    present_cpu[key] += cpu
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    procs.sort(reverse=True)
    thermal = read_thermal()
    return {
        **{f"thermal_{k}": v for k, v in thermal.items()},
        "t": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "cpu_pct": psutil.cpu_percent(None),
        "in_use_gb": round((vm.total - vm.available) / 2**30, 3),
        "available_gb": round(vm.available / 2**30, 3),
        "processes": n,
        "threads": threads,
        "top": [{"name": nm, "cpu": round(c, 1)} for c, nm in procs[:5]],
        "bitdefender_procs": present["bitdefender"],
        "bitdefender_cpu": round(present_cpu["bitdefender"], 1),
        "onedrive_procs": present["onedrive"],
        "onedrive_cpu": round(present_cpu["onedrive"], 1),
    }


def summarise(path: Path) -> dict:
    rows = [json.loads(ln) for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    out: dict = {"samples": len(rows)}
    if not rows:
        return out
    out["first"], out["last"] = rows[0]["t"], rows[-1]["t"]
    for key in ("cpu_pct", "in_use_gb", "processes", "threads", "bitdefender_cpu", "onedrive_cpu"):
        vals = [r[key] for r in rows if key in r]
        out[key] = {"min": min(vals), "mean": round(sum(vals) / len(vals), 3), "max": max(vals)}
    out["bitdefender_present_samples"] = sum(1 for r in rows if r.get("bitdefender_procs", 0) > 0)
    out["onedrive_present_samples"] = sum(1 for r in rows if r.get("onedrive_procs", 0) > 0)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(allow_abbrev=False)
    ap.add_argument("--out", type=Path)
    ap.add_argument("--interval", type=float, default=5.0)
    ap.add_argument("--summarise", type=Path)
    a = ap.parse_args()
    if a.summarise:
        print(json.dumps(summarise(a.summarise), indent=2))
        return 0
    if a.out is None:
        ap.error("--out is required unless --summarise is given")
    import psutil

    a.out = a.out.resolve()
    a.out.parent.mkdir(parents=True, exist_ok=True)
    psutil.cpu_percent(None)
    for p in psutil.process_iter():
        try:
            p.cpu_percent(None)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    last: dict = {}
    while True:
        time.sleep(a.interval)
        row = sample(psutil, last)
        with open(a.out, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(row) + chr(10))


if __name__ == "__main__":
    sys.exit(main())
