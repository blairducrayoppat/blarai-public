"""Dump per-band detail for 14B tests and 8B+0.6B."""
import json
from pathlib import Path

d = json.loads(
    Path("phase2_gates/evidence/p5_005a_unified_draft_feasibility_matrix.json")
    .read_text(encoding="utf-8")
)

targets = ["T-01", "T-02", "T-03", "T-04", "T-09", "T-10", "T-11", "T-06", "T-08"]

fmt = "{:<6} {:<35} {:<6} {:<10} {:<10} {:<10} {:<10} {:<10}"
print(fmt.format("ID", "Name", "Band", "TPS", "TTFT_ms", "Total_ms", "RSS_pk", "Tokens"))
print("-" * 100)

for t in d["tests"]:
    if t["id"] not in targets:
        continue
    if t["status"] != "completed":
        continue
    for p in t.get("points", []):
        band = p.get("prompt_length_user_tokens_target", "?")
        s = p.get("summary", {})
        if not s:
            continue
        tps = s.get("decode_tps", {}).get("mean", 0)
        ttft = s.get("ttft_ms", {}).get("mean", 0)
        total = s.get("latency_total_ms", {}).get("mean", 0)
        rss = s.get("rss_peak_mb", {}).get("mean", 0)
        tokens = s.get("tokens_generated", {}).get("mean", 0)
        missing = p.get("missing_reason")
        if missing:
            print(f"{t['id']:<6} {t['name']:<35} {band:<6} {'MISSING: ' + missing}")
        else:
            print(fmt.format(t["id"], t["name"], band, f"{tps:.2f}", f"{ttft:.0f}", f"{total:.0f}", f"{rss:.0f}", f"{tokens:.0f}"))
    print()
