"""Show exact configuration of each test."""
import json
from pathlib import Path

d = json.loads(
    Path("phase2_gates/evidence/p5_005a_unified_draft_feasibility_matrix.json")
    .read_text(encoding="utf-8")
)

cap = d.get("feature_discovery", {})
print("=== Detected Capabilities ===")
print(f"  kv_cache_precision_property_present: {cap.get('kv_cache_precision_property_present')}")
print(f"  xattention_property_present:         {cap.get('xattention_property_present')}")
print(f"  prefix_cache_api_present:            {cap.get('prefix_cache_api_present')}")
print(f"  draft_model_api_present:             {cap.get('draft_model_api_present')}")
print()
print("=== Per-Test Configuration ===")
for t in d["tests"]:
    rp = t.get("runtime_properties", {})
    pk = t.get("pipeline_kwargs", {})
    dm = t.get("draft_model_path")
    dd = t.get("draft_device")
    spec = t.get("is_speculative", False)
    print(f"{t['id']:6} {t['name']:35} runtime_props={rp or '{}'}")
    print(f"       {'':35} pipeline_kwargs={pk or '{}'}")
    if spec:
        draft_name = Path(dm).name if dm else "N/A"
        print(f"       {'':35} draft={draft_name} on {dd}")
    print()
