"""
Export Qwen2.5-1.5B-Instruct with INT4-MIXED quantization for NPU.

Model: Qwen/Qwen2.5-1.5B-Instruct (NPU-validated per OpenVINO 2026.0 docs)
Format: INT4-MIXED — mixed INT4/INT8 weights, symmetric, channel-wise
Target: Intel AI Boost (Lunar Lake NPU)

Per https://docs.openvino.ai/2026/openvino-workflow-generative/
    inference-with-genai/inference-with-genai-on-npu.html:
  - Symmetric weights compression (--sym)
  - 4-bit weight format INT4 (--weight-format int4)
  - Channel-wise quantization (--group-size -1)
  - INT4-MIXED uses ratio < 1.0 (default 0.8 — 80% INT4, 20% INT8)

Dependencies (run in .export-venv):
  transformers==4.51.3, optimum-intel==1.25.2, nncf==2.18.0
"""

import sys
import time
from pathlib import Path

print("=" * 70)
print("  Qwen2.5-1.5B-Instruct NPU Export — INT4-MIXED Symmetric")
print("=" * 70)

# Verify dependency versions
import transformers
import nncf
print(f"  transformers: {transformers.__version__}")
print(f"  nncf:         {nncf.__version__}")

assert transformers.__version__ == "4.51.3", (
    f"Expected transformers 4.51.3, got {transformers.__version__}"
)
assert nncf.__version__ == "2.18.0", (
    f"Expected nncf 2.18.0, got {nncf.__version__}"
)

from optimum.intel import OVModelForCausalLM
from optimum.intel.openvino import OVWeightQuantizationConfig
import openvino as ov

print(f"  openvino:     {ov.__version__}")
print()

MODEL_ID = "Qwen/Qwen2.5-1.5B-Instruct"
OUTPUT_DIR = Path("models/qwen2.5-1.5b-instruct/openvino-int4-npu")

# INT4-MIXED: symmetric, channel-wise, ratio=0.8 (80% INT4, 20% INT8)
# This is the NPU-validated format per OpenVINO 2026 model support list
quant_config = OVWeightQuantizationConfig(
    bits=4,
    sym=True,
    group_size=-1,
    ratio=0.8,
)

print(f"[EXPORT] Source model : {MODEL_ID}")
print(f"[EXPORT] Output dir   : {OUTPUT_DIR}")
print(f"[EXPORT] Quant config : bits=4, sym=True, group_size=-1, ratio=0.8 (INT4-MIXED)")
print(f"[EXPORT] NPU-validated format for Qwen2.5-1.5B-Instruct")
print()

t_start = time.perf_counter()
print("[EXPORT] Loading and converting model (this may take 1-2 minutes)...")

model = OVModelForCausalLM.from_pretrained(
    MODEL_ID,
    export=True,
    quantization_config=quant_config,
)

t_convert = time.perf_counter()
print(f"[EXPORT] Model converted in {t_convert - t_start:.1f}s")

print(f"[EXPORT] Saving to {OUTPUT_DIR}...")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
model.save_pretrained(OUTPUT_DIR)

# Also save tokenizer from source
from transformers import AutoTokenizer
tokenizer = AutoTokenizer.from_pretrained(MODEL_ID)
tokenizer.save_pretrained(OUTPUT_DIR)

t_done = time.perf_counter()
print(f"[EXPORT] Saved in {t_done - t_convert:.1f}s (total: {t_done - t_start:.1f}s)")

# Verify output
bin_path = OUTPUT_DIR / "openvino_model.bin"
if bin_path.exists():
    size_mb = bin_path.stat().st_size / (1024 * 1024)
    print(f"\n[VERIFY] openvino_model.bin: {size_mb:.1f} MB")
else:
    print("\n[VERIFY] WARNING: openvino_model.bin not found!")

# Check quantization info
config_path = OUTPUT_DIR / "openvino_config.json"
if config_path.exists():
    import json
    with open(config_path) as f:
        ov_config = json.load(f)
    print(f"[VERIFY] openvino_config.json: {json.dumps(ov_config, indent=2)}")

# List all output files
print(f"\n[FILES] Contents of {OUTPUT_DIR}:")
for p in sorted(OUTPUT_DIR.iterdir()):
    size = p.stat().st_size / 1024
    print(f"  {p.name:40s} {size:>10.1f} KB")

print(f"\n{'=' * 70}")
print(f"  EXPORT COMPLETE — Ready for NPU smoke test")
print(f"  Run: .venv\\Scripts\\python.exe scripts\\smoke_npu_genai.py \\")
print(f"       --device NPU --model-dir {OUTPUT_DIR}")
print(f"{'=' * 70}")
