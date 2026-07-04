"""
Post-processor for Task 4.3b: reads the partial JSON evidence artifact,
runs analysis + quality gates, and writes the final evidence file.

Usage:
    python phase2_gates/scripts/run_p5_task4_3b_postprocess.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Import functions from the main harness (safe since __name__ != "__main__")
from phase2_gates.scripts.run_p5_task4_3b_sparse_attention import (  # noqa: E402
    PARTIAL_JSON, OUTPUT_JSON, PROMPT_BANDS, now_iso, write_json_atomic,
    build_analysis, evaluate_quality_gates,
)


def main() -> None:
    print(f"[POST-PROCESS] Reading partial JSON: {PARTIAL_JSON}")
    with open(PARTIAL_JSON, "r", encoding="utf-8") as fh:
        payload = json.load(fh)

    results = payload.get("results", [])
    print(f"  Results in partial: {len(results)}")
    for r in results:
        s = r.get("summary", {})
        ar = s.get("acceptance_rate_aggregate", "N/A")
        tps = (s.get("combined_tps") or {}).get("mean") or "N/A"
        ttft = (s.get("ttft_ms") or {}).get("mean") or "N/A"
        print(f"  {r['sparse_mode']:>12} band={r['band']:>5} status={r['status']:>20} "
              f"vc={s.get('valid_count',0)} tps={tps} ttft={ttft} ar={ar}")

    # Load baseline from payload
    baseline_raw = payload.get("test_a_baseline", {}).get("entries", [])
    baseline: dict[int, dict] = {}
    for e in baseline_raw:
        band = e["band"]
        baseline[band] = e

    print("\n[POST-PROCESS] Running analysis...")
    analysis = build_analysis(results, baseline)

    print("[POST-PROCESS] Running quality gates...")
    quality_gate = evaluate_quality_gates(results, baseline)

    print(f"\n[DISPOSITION] {quality_gate['disposition']}")
    print(f"  G-01 (completeness):  {quality_gate['G-01']}")
    print(f"  G-02 (valid count):   {quality_gate['G-02']}")
    print(f"  G-03 (TTFT improv):   {quality_gate['G-03']}")
    print(f"  G-04 (TPS compat):    {quality_gate['G-04']}")
    print(f"  G-05 (spec decode):   {quality_gate['G-05']}")
    print(f"  G-06 (RSS):           {quality_gate['G-06']}")
    print(f"  G-07 (mem budget):    {quality_gate['G-07']}")
    print(f"  G-08 (mode compare):  {quality_gate['G-08']}")

    # AR collapse shift
    if quality_gate.get("G-05_ar_collapse_shift"):
        print("\n[MAJOR FINDING] AR_COLLAPSE_BOUNDARY_SHIFT DETECTED")

    # TTFT delta table
    print("\n  TTFT delta table (positive = improvement vs dense baseline):")
    print(f"  {'Band':>6}  {'TRISHAPE':>10}  {'XATTENTION':>10}")
    for band in PROMPT_BANDS:
        tri_d = (analysis["ttft_improvement_bands"].get("TRISHAPE") or {}).get(str(band))
        xat_d = (analysis["ttft_improvement_bands"].get("XATTENTION") or {}).get(str(band))
        tri_s = f"{tri_d:+.1f}%" if tri_d is not None else "   FAILED"
        xat_s = f"{xat_d:+.1f}%" if xat_d is not None else "   FAILED"
        print(f"  {band:>6}  {tri_s:>10}  {xat_s:>10}")

    # Write final JSON
    finished_ts = now_iso()
    final_payload = dict(payload)
    final_payload["analysis"] = analysis
    final_payload["quality_gate"] = quality_gate
    final_payload["finished_utc"] = finished_ts

    write_json_atomic(OUTPUT_JSON, final_payload)
    if PARTIAL_JSON.exists():
        PARTIAL_JSON.unlink()

    print(f"\n[DONE] Final evidence: {OUTPUT_JSON}")
    print(f"Finished: {finished_ts}")


if __name__ == "__main__":
    main()
