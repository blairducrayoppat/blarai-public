"""Quick dump of P5-005a results table — full per-band breakdown."""
import json
from pathlib import Path

d = json.loads(
    Path("phase2_gates/evidence/p5_005a_unified_draft_feasibility_matrix.json")
    .read_text(encoding="utf-8")
)

for t in d["tests"]:
    if t["status"] != "completed":
        continue
    tid = t["id"]
    name = t["name"]
    compile_ms = t.get("pipeline_compile_ms", 0)
    print(f"=== {tid}: {name} (compile={compile_ms:.0f}ms) ===")
    for p in t.get("points", []):
        band = p.get("prompt_length_user_tokens_target")
        s = p.get("summary", {})
        tps = s.get("decode_tokens_per_sec", {}).get("mean", 0)
        ttft = s.get("ttft_ms", {}).get("mean", 0)
        rss_mean = s.get("rss_peak_mb", {}).get("mean", 0)
        rss_max = s.get("rss_peak_mb", {}).get("max", 0)
        valid = s.get("valid_count", 0)
        gen_tok = s.get("generated_tokens", {}).get("mean", 0)
        print(
            f"  band={band}: tps={tps:.2f}, ttft={ttft:.0f}ms, "
            f"rss_mean={rss_mean:.0f}MB, rss_max={rss_max:.0f}MB, "
            f"valid={valid}/5, gen_tok={gen_tok:.0f}"
        )
    print()
