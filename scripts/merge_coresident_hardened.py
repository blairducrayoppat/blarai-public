"""
Aggregate the HARDENED co-residency multi-sweep into a publishing dataset
=========================================================================
Reads N repeats per pairing (harness JSON + per-phase socwatch.metrics.json +
per-phase l0.metrics.json) and reports mean +/- std (+ min/max/n) for every
metric, segmented by phase where applicable:

  throughput : baseline / partner-idle / contention generation tok/s, pp, TTFT
  memory     : partner-resident GiB, peak co-resident GiB, partner op seconds
  power (W)  : iGPU rail (VCCGT) idle vs contention (avg + 1s windowed peak),
               package, NPU (idle confirm)
  gpu        : core frequency (MHz) idle vs contention, GPU-busy %, memory
               read/write rate (the LPDDR5X contention signal)
  thermal    : SoC + CPU temp peak, iGPU throttle

Usage:
  python scripts/merge_coresident_hardened.py --perf-dir docs/performance \\
    --ut-dir <scratch>/ut_hardened --partners photoreal illustration cartoon vlm \\
    --repeats 3 --out docs/performance/coresident_14b_pairings_hardened_<date>.json
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import statistics as st
import sys
import time
from pathlib import Path

PARTNER_MODEL = {
    "photoreal": "SDXL-uncensored (RealVisXL V5.0) INT8 [/imagine]",
    "illustration": "base SDXL 1.0 INT8 [/illustrate]",
    "cartoon": "base SDXL 1.0 INT8 + DD-vector LoRA (runtime) [/cartoon]",
    "vlm": "Qwen3-VL-8B-Instruct INT4 [vision]",
}


def _agg(vals: list):
    vals = [v for v in vals if v is not None]
    if not vals:
        return None
    return {"mean": round(st.mean(vals), 3),
            "std": round(st.pstdev(vals), 3) if len(vals) > 1 else 0.0,
            "min": round(min(vals), 3), "max": round(max(vals), 3), "n": len(vals)}


def _latest(pattern: str):
    fs = glob.glob(pattern)
    return max(fs, key=os.path.getmtime) if fs else None


def _g(d: dict, *path):
    """Nested get; returns None if any key missing."""
    for k in path:
        if not isinstance(d, dict):
            return None
        d = d.get(k)
        if d is None:
            return None
    return d


def _run_fields(hj: str, sw: dict, l0: dict) -> dict:
    H = json.load(open(hj, encoding="utf-8"))
    base = H.get("14b_baseline", {})
    pr = (H.get("partners") or [{}])[0]
    idle = pr.get("idle_14b", {})
    cont = pr.get("contention_14b", {})
    return {
        # throughput
        "baseline_gen_tps": base.get("gen_tps"),
        "baseline_pp_tps": base.get("pp_tps"),
        "baseline_ttft_ms": base.get("ttft_ms"),
        "idle_gen_tps": idle.get("gen_tps"),
        "idle_pp_tps": idle.get("pp_tps"),
        "idle_ttft_ms": idle.get("ttft_ms"),
        "contention_gen_tps": cont.get("gen_tps"),
        "contention_ttft_ms": cont.get("ttft_ms"),
        "contention_tokens": cont.get("tokens"),
        # memory
        "partner_resident_gib": pr.get("partner_resident_gib"),
        "peak_co_resident_gib": pr.get("peak_used_gib"),
        "headroom_gib": pr.get("headroom_gib"),
        "partner_op_s": pr.get("partner_op_s"),
        "partner_gens_during_contention": pr.get("partner_gens_during"),
        # socwatch power (per phase)
        "vccgt_idle_w": _g(sw, "PMT-VCCGT-PWR", "idle", "avg_w"),
        "vccgt_contention_w": _g(sw, "PMT-VCCGT-PWR", "contention", "avg_w"),
        "vccgt_contention_peak_w": _g(sw, "PMT-VCCGT-PWR", "contention", "peak_w_1s"),
        "pkg_idle_w": _g(sw, "PKG-PWR", "idle", "avg_w"),
        "pkg_contention_w": _g(sw, "PKG-PWR", "contention", "avg_w"),
        "npu_whole_w": _g(sw, "PMT-NPU-PWR", "whole", "avg_w"),
        "soc_temp_contention_peak_c": _g(sw, "PMT-SOC-TEMP", "contention", "peak"),
        "cpu_temp_contention_peak_c": _g(sw, "TEMP", "contention", "peak"),
        "igfx_throttle_max": _g(sw, "IGFX-THROT-RSN", "whole", "peak"),
        # level-zero GPU (per phase)
        "freq_idle_mhz": _g(l0, "GPU.CoreFrequencyMHz", "idle", "avg"),
        "freq_contention_mhz": _g(l0, "GPU.CoreFrequencyMHz", "contention", "avg"),
        "busy_idle_pct": _g(l0, "GPU.GPU_BUSY", "idle", "avg"),
        "busy_contention_pct": _g(l0, "GPU.GPU_BUSY", "contention", "avg"),
        "mem_read_idle": _g(l0, "GPU.GPU_MEMORY_BYTE_READ_RATE", "idle", "avg"),
        "mem_read_contention": _g(l0, "GPU.GPU_MEMORY_BYTE_READ_RATE", "contention", "avg"),
        "mem_read_contention_peak": _g(l0, "GPU.GPU_MEMORY_BYTE_READ_RATE", "contention", "peak"),
        "mem_write_contention": _g(l0, "GPU.GPU_MEMORY_BYTE_WRITE_RATE", "contention", "avg"),
        "xve_active_contention_pct": _g(l0, "GPU.XVE_ACTIVE", "contention", "avg"),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Aggregate the hardened co-residency multi-sweep.")
    ap.add_argument("--perf-dir", required=True)
    ap.add_argument("--ut-dir", required=True)
    ap.add_argument("--partners", nargs="*", default=["photoreal", "illustration", "cartoon", "vlm"])
    ap.add_argument("--repeats", type=int, default=3)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    pairings = []
    notes = []
    for p in args.partners:
        runs = []
        for r in range(1, args.repeats + 1):
            tag = f"{p}_r{r}"
            hj = _latest(os.path.join(args.perf_dir, f"benchmark_coresident_{tag}_*.json"))
            swp = os.path.join(args.ut_dir, f"ut_{tag}.socwatch.metrics.json")
            l0p = os.path.join(args.ut_dir, f"ut_{tag}.l0.metrics.json")
            if not hj:
                notes.append(f"{tag}: missing harness JSON")
                continue
            sw = json.load(open(swp, encoding="utf-8")) if os.path.exists(swp) else {}
            l0 = json.load(open(l0p, encoding="utf-8")) if os.path.exists(l0p) else {}
            if not sw:
                notes.append(f"{tag}: missing socwatch metrics")
            if not l0:
                notes.append(f"{tag}: missing l0 metrics")
            runs.append(_run_fields(hj, sw, l0))
        if not runs:
            pairings.append({"partner": p, "error": "no runs"})
            continue
        keys = runs[0].keys()
        aggd = {k: _agg([run.get(k) for run in runs]) for k in keys}
        pairings.append({"partner": p, "model": PARTNER_MODEL.get(p, p),
                         "n_runs": len(runs), "metrics": aggd})

    out = {
        "study": "14b_coresidency_hardened_multirun",
        "date": time.strftime("%Y-%m-%d"),
        "hardware": {"cpu": "Intel Core Ultra 7 258V (Lunar Lake)",
                     "gpu": "Intel Arc 140V (Xe2, iGPU, shared LPDDR5X-8533)",
                     "mem_ceiling_gib": 31.323, "gpu_driver": "32.0.101.8826"},
        "methodology": {
            "14b": "spec-on (production); idle probe 128 tok; SUSTAINED contention = 14B "
                   "back-to-back for a fixed 15s window while the partner generates "
                   "continuously (kills overlap-timing noise); pp probe pp-v1.",
            "repeats": args.repeats,
            "aggregation": "mean +/- std (+ min/max/n) across repeats",
            "thermal": "inter-run cooldown between every pairing run",
            "telemetry": "Intel UT (ut.exe) socwatch (VCCGT/PKG/NPU power, SoC/CPU temp, "
                         "throttle) + level-zero (GPU CoreFrequencyMHz, GPU_BUSY, "
                         "GPU_MEMORY_BYTE_*_RATE, XVE_ACTIVE), config-level medium.",
            "per_phase": "samples segmented by Unix-epoch timestamp into baseline/idle/"
                         "partner_op/contention using harness-emitted wall-clock boundaries.",
            "power": "energy mJ/sample -> W; avg = total mJ/total ms; peak = max over 1s windows.",
            "units_caveat": "GPU_MEMORY_BYTE_*_RATE unit is reported N/A by UT (likely GB/s "
                            "given the ~108 peak vs the ~136 GB/s LPDDR5X ceiling) — UNCONFIRMED.",
            "reproduce": "docs/performance/README_coresident_ut.md",
        },
        "notes": notes,
        "pairings": pairings,
    }
    Path(args.out).write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(f"[SAVE] {args.out}\n")

    def _m(a):
        return f"{a['mean']}±{a['std']}" if a else "n/a"

    print(f"{'partner':<13}{'runs':>5}{'genIdle':>10}{'genCont':>10}{'gpuBusy%':>10}"
          f"{'freqMHz':>9}{'memRd':>8}{'vccgtW':>9}")
    for r in pairings:
        if "metrics" not in r:
            print(f"  {r['partner']:<13} ERROR {r.get('error')}")
            continue
        m = r["metrics"]
        print(f"{r['partner']:<13}{r['n_runs']:>5}{_m(m['idle_gen_tps']):>10}"
              f"{_m(m['contention_gen_tps']):>10}{_m(m['busy_contention_pct']):>10}"
              f"{_m(m['freq_contention_mhz']):>9}{_m(m['mem_read_contention']):>8}"
              f"{_m(m['vccgt_contention_w']):>9}")
    if notes:
        print("\nnotes:", "; ".join(notes[:8]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
