"""
Extract PER-PHASE + windowed-peak metric aggregates from an Intel UT ``.bin``
=============================================================================
Handles BOTH ``*.socwatch.bin`` (power / thermal) and ``*.l0_gpu.bin`` (GPU
frequency / bandwidth / busy) — they share the bin2perfetto console format.

STREAMING (parses bin2perfetto ``-f console`` line-by-line; the dump is hundreds
of MB to GB). Each sample carries a Unix-epoch nanosecond timestamp, so samples
are segmented into PHASES (baseline / idle / partner_op / contention) given the
wall-clock phase boundaries the harness emits — power/freq/bandwidth are reported
per phase AND whole-run.

  * Energy rails (unit contains 'J', i.e. mJ) -> ``avg_w`` (total mJ / total ms)
    + ``peak_w_1s`` (max power over any 1-second window — robust vs the sub-ms
    sample glitches that produce spurious kilowatt spikes).
  * Instantaneous metrics (frequency MHz, GPU busy %, bandwidth, temperature) ->
    avg / peak / min.

Usage:
  python scripts/extract_ut_metrics.py --bin <run>.socwatch.bin \\
    --bin2perfetto <ut>/bin/bin2perfetto.exe --phases <run>.phases.json \\
    --out <run>.metrics.json

``--phases`` is a JSON list of ``[name, t_start_unix_s, t_end_unix_s]``.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from pathlib import Path

_DESC = re.compile(
    r"Metric ID:\s*(\d+),\s*Metric Name:\s*([^,]+),.*?Metric Unit:\s*([^,]+)")
_SAMP = re.compile(
    r"Metric ID:\s*(\d+),\s*Device ID:.*?Sample:\s*([0-9.eE+-]+),"
    r"\s*Timestamp:\s*(\d+),\s*Duration:\s*(\d+)")

_WINDOW_S = 1.0  # peak-power averaging window


def _phase_of(ts_sec: float, phases: list) -> "str | None":
    for name, t0, t1 in phases:
        if t0 <= ts_sec <= t1:
            return name
    return None


def _scan_ts_range(bin_path: str, bin2perfetto: str, timeout: float = 1800.0):
    """Min/max sample timestamp in a UT bin — the anchors for a linear clock remap."""
    proc = subprocess.Popen(  # noqa: S603 — local trusted tool
        [bin2perfetto, "-i", bin_path, "-f", "console"],
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, bufsize=1 << 20)
    lo = hi = None
    t0 = time.monotonic()
    try:
        for line in proc.stdout:  # type: ignore[union-attr]
            if "Sample:" not in line:
                continue
            m = _SAMP.search(line)
            if not m:
                continue
            ts = int(m.group(3))
            lo = ts if lo is None else (ts if ts < lo else lo)
            hi = ts if hi is None else (ts if ts > hi else hi)
            if (time.monotonic() - t0) > timeout:
                proc.kill()
                break
    finally:
        try:
            proc.wait(timeout=10)
        except Exception:  # noqa: BLE001
            proc.kill()
    return lo, hi


def extract(bin_path: str, bin2perfetto: str, phases: list, timeout: float = 2400.0,
            remap=None) -> dict:
    """Stream + segment by phase. ``phases`` = [[name, t0_unix_s, t1_unix_s], ...].
    ``remap`` (optional) maps a raw timestamp -> wall-clock ns (the l0 clock fix)."""
    proc = subprocess.Popen(  # noqa: S603 — local trusted tool
        [bin2perfetto, "-i", bin_path, "-f", "console"],
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, bufsize=1 << 20)
    names: dict[str, str] = {}
    units: dict[str, str] = {}
    acc: dict[str, dict] = {}  # mid -> phase -> bucket

    def _bucket(mid: str, ph: str) -> dict:
        return acc.setdefault(mid, {}).setdefault(
            ph, {"e": 0.0, "dur": 0, "sum": 0.0, "n": 0, "max": None, "min": None, "win": {}})

    t_start = time.monotonic()
    try:
        for line in proc.stdout:  # type: ignore[union-attr]
            if "Metric ID:" not in line:
                continue
            if "Sample:" in line:
                s = _SAMP.search(line)
                if not s:
                    continue
                mid = s.group(1)
                v = float(s.group(2))
                ts_raw = int(s.group(3))
                ts_sec = (remap(ts_raw) if remap else ts_raw) / 1e9
                dur = int(s.group(4))
                ph = _phase_of(ts_sec, phases)
                for bucket_name in ("whole", ph):
                    if bucket_name is None:
                        continue
                    b = _bucket(mid, bucket_name)
                    b["e"] += v
                    b["dur"] += dur
                    b["sum"] += v
                    b["n"] += 1
                    b["max"] = v if b["max"] is None else (v if v > b["max"] else b["max"])
                    b["min"] = v if b["min"] is None else (v if v < b["min"] else b["min"])
                    wsec = int(ts_sec / _WINDOW_S)
                    w = b["win"].setdefault(wsec, [0.0, 0])
                    w[0] += v
                    w[1] += dur
                if (time.monotonic() - t_start) > timeout:
                    proc.kill()
                    break
            else:
                d = _DESC.search(line)
                if d:
                    mid = d.group(1)
                    names[mid] = d.group(2).strip()
                    units[mid] = d.group(3).strip()
    finally:
        try:
            proc.wait(timeout=10)
        except Exception:  # noqa: BLE001
            proc.kill()

    out: dict[str, dict] = {}
    for mid, phbuckets in acc.items():
        name = names.get(mid, mid)
        unit = units.get(mid, "")
        is_energy = "J" in unit
        out[name] = {}
        for ph, b in phbuckets.items():
            if b["n"] == 0:
                continue
            if is_energy:
                avg_w = (b["e"] / (b["dur"] / 1e6)) if b["dur"] > 0 else 0.0
                # windowed peak: max power over 1s windows with >= half coverage
                peaks = [we / (wd / 1e6) for we, wd in b["win"].values()
                         if wd >= _WINDOW_S * 1e9 * 0.5]
                peak_w = max(peaks) if peaks else round(avg_w, 3)
                out[name][ph] = {"avg_w": round(avg_w, 3), "peak_w_1s": round(peak_w, 3),
                                 "n_samples": b["n"]}
            else:
                out[name][ph] = {"avg": round(b["sum"] / b["n"], 3),
                                 "peak": round(b["max"], 3), "min": round(b["min"], 3),
                                 "unit": unit, "n_samples": b["n"]}
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="Per-phase + windowed UT metric extractor (streaming).")
    ap.add_argument("--bin", required=True)
    ap.add_argument("--bin2perfetto", required=True)
    ap.add_argument("--phases", help="JSON file: [[name, t0_unix_s, t1_unix_s], ...]")
    ap.add_argument("--harness", help="harness JSON; derive phases from baseline_phase + the partner's phases")
    ap.add_argument("--out", required=True)
    ap.add_argument("--remap-from", help="anchor bin (socwatch, Unix-epoch ts); linearly remaps "
                    "THIS bin's clock onto wall-clock for phase segmentation (the level-zero "
                    "timestamp-units fix).")
    args = ap.parse_args()

    if not Path(args.bin).exists():
        print(f"FATAL: bin not found: {args.bin}")
        return 1
    if args.harness:
        h = json.loads(Path(args.harness).read_text(encoding="utf-8"))
        phases = [["baseline"] + h["baseline_phase"]] if h.get("baseline_phase") else []
        prs = h.get("partners") or []
        pr = prs[0].get("phases", {}) if prs else {}
        for k, v in pr.items():
            if k != "partner_load" and v and v[1]:
                phases.append([k] + v)
    elif args.phases:
        phases = json.loads(Path(args.phases).read_text(encoding="utf-8"))
    else:
        print("FATAL: need --harness or --phases")
        return 1
    remap = None
    if args.remap_from:
        au0, au1 = _scan_ts_range(args.remap_from, args.bin2perfetto)
        bl0, bl1 = _scan_ts_range(args.bin, args.bin2perfetto)
        if None not in (au0, au1, bl0, bl1) and bl1 > bl0 and au1 > au0:
            _su, _sl, _a0, _b0 = (au1 - au0), (bl1 - bl0), au0, bl0

            def remap(ts):  # noqa: E306 — linear l0-clock -> wall-clock ns
                return _a0 + (ts - _b0) * _su / _sl
            print(f"  [remap] this-bin [{bl0}..{bl1}] -> wall-clock [{au0}..{au1}] Unix-ns")
        else:
            print("  [remap] could not derive ranges — raw timestamps (no segmentation)")
    t0 = time.monotonic()
    metrics = extract(args.bin, args.bin2perfetto, phases, remap=remap)
    dt = time.monotonic() - t0
    Path(args.out).write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    # highlight a few headline metrics per phase
    print(f"  --- metrics ({dt:.0f}s, {len(metrics)} metrics, phases={[p[0] for p in phases]}) ---")
    for k in ("PMT-VCCGT-PWR", "PKG-PWR", "GPU.CoreFrequencyMHz", "GPU.GPU_BUSY",
              "GPU.GPU_MEMORY_BYTE_READ_RATE", "PMT-SOC-TEMP"):
        if k in metrics:
            comp = {ph: metrics[k][ph] for ph in ("idle", "contention") if ph in metrics[k]}
            print(f"  {k:<32} {comp if comp else metrics[k].get('whole')}")
    print(f"  [SAVE] {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
