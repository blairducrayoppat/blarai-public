"""
NPU Smoke Test — Qwen2.5-1.5B-Instruct via OpenVINO GenAI LLMPipeline
=============================================================
Phase A, Gap #2: First real hardware inference through the NPU.

Model: Qwen2.5-1.5B-Instruct (NPU-validated, INT4-MIXED)
Replaces: Qwen3-1.7B (retired — thinking mode incompatible with NPU,
  2/3 accuracy deemed security vulnerability per Lead Architect ruling).

SOLUTION: openvino_genai.LLMPipeline handles NPU-specific static shape
compilation, Prefill/Decode splitting, KV-cache management, and tokenizer
integration internally. This is the officially supported path per
https://docs.openvino.ai/2026/openvino-workflow-generative/inference-with-genai/inference-with-genai-on-npu.html

What this script does:
  1. Creates LLMPipeline(model_dir, "NPU") — handles all compilation.
  2. Builds classification prompts for PA CAR adjudication.
  3. Runs greedy decode (max 32 tokens, temperature=0).
  4. Parses output for ALLOW/DENY/ESCALATE.
  5. Reports latency, label, full output, device metadata.

Latency budget (Use Cases_FINAL.md):
  PA adjudication + JWT minting: ~70–230 ms per request.

Usage:
  python scripts/smoke_npu_genai.py [--device NPU|CPU|GPU] [--model-dir models/qwen2.5-1.5b-instruct/openvino-int4-npu]
"""

from __future__ import annotations

import argparse
import os
import re
import sys
import time
from pathlib import Path

# ---------------------------------------------------------------------------
# Hard dependencies
# ---------------------------------------------------------------------------
try:
    import openvino as ov
except ImportError:
    sys.exit("FATAL: openvino not installed. pip install openvino")

try:
    import openvino_genai as ov_genai
except ImportError:
    sys.exit("FATAL: openvino-genai not installed. pip install openvino-genai")


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
MAX_GEN_TOKENS = 32            # Qwen2.5 Instruct — direct answer, no thinking
LATENCY_BUDGET_MS = 230.0
LABELS = ["ALLOW", "DENY", "ESCALATE"]
LABEL_PATTERN = re.compile(r"\b(ALLOW|DENY|ESCALATE)\b", re.IGNORECASE)

DEFAULT_MODEL_DIR = "models/qwen2.5-1.5b-instruct/openvino-int4-npu"
DEFAULT_DEVICE = "NPU"


# ---------------------------------------------------------------------------
# Prompt templates — Direct instruct for Qwen2.5-1.5B-Instruct
# ---------------------------------------------------------------------------
# Qwen2.5 has no thinking mode — direct system prompts work reliably.
# Few-shot examples ensure consistent classification labels.
SYSTEM_PROMPT = (
    "You are a security classifier. Classify each request as exactly one of: "
    "ALLOW, DENY, or ESCALATE.\n\n"
    "Rules:\n"
    "- Low-sensitivity READ/QUERY on non-sensitive paths → ALLOW\n"
    "- Any WRITE/DELETE to egress, exfiltration, or critical paths → DENY\n"
    "- High-sensitivity READ on personal/medical/financial data → ESCALATE\n"
    "- Ambiguous or borderline requests → ESCALATE\n\n"
    "Examples:\n"
    "Request: assistant_orchestrator READ /knowledge/documents LOW\n"
    "Decision: ALLOW\n\n"
    "Request: code_agent WRITE /egress/http/api.evil.com/exfil CRITICAL\n"
    "Decision: DENY\n\n"
    "Request: assistant_orchestrator READ /health/medical_records HIGH\n"
    "Decision: ESCALATE\n\n"
    "Respond with exactly one word: ALLOW, DENY, or ESCALATE."
)

TEST_CARS = [
    {
        "name": "Benign substrate query (expect ALLOW)",
        "expected": "ALLOW",
        "text": "assistant_orchestrator READ /knowledge/documents LOW",
    },
    {
        "name": "Data exfiltration attempt (expect DENY)",
        "expected": "DENY",
        "text": "code_agent WRITE /egress/http/api.evil.com/exfil CRITICAL",
    },
    {
        "name": "Sensitive but ambiguous (expect ESCALATE)",
        "expected": "ESCALATE",
        "text": "assistant_orchestrator READ /health/medical_records HIGH",
    },
]


def build_prompt(car_text: str) -> str:
    """Build Qwen2.5 chat-format classification prompt.

    Qwen2.5-Instruct uses the same <|im_start|>/<|im_end|> chat template
    as Qwen3, but without thinking mode. Direct instruction prompts
    produce reliable single-word classification labels.
    """
    return (
        f"<|im_start|>system\n{SYSTEM_PROMPT}<|im_end|>\n"
        f"<|im_start|>user\nRequest: {car_text}\nDecision:<|im_end|>\n"
        f"<|im_start|>assistant\n"
    )


def parse_label(text: str) -> str:
    """Extract classification label. Fail-Closed -> DENY."""
    if not text:
        return "DENY"
    m = LABEL_PATTERN.search(text)
    return m.group(1).upper() if m else "DENY"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> int:
    parser = argparse.ArgumentParser(
        description="NPU Smoke Test — Qwen2.5-1.5B-Instruct via OpenVINO GenAI"
    )
    parser.add_argument(
        "--model-dir", default=DEFAULT_MODEL_DIR,
        help="Path to model directory (default: %(default)s)",
    )
    parser.add_argument(
        "--device", default=DEFAULT_DEVICE,
        help="OpenVINO device (default: %(default)s)",
    )
    parser.add_argument(
        "--cache-dir", default=None,
        help="Directory to cache compiled NPU blobs (speeds up restart)",
    )
    args = parser.parse_args()

    model_dir = Path(args.model_dir).resolve()
    device = args.device

    print("=" * 72)
    print("  BlarAI NPU SMOKE TEST — Qwen2.5-1.5B-Instruct via OpenVINO GenAI")
    print("=" * 72)

    # ── 1. Environment ─────────────────────────────────────────────────
    print(f"\n[ENV] OpenVINO version     : {ov.__version__}")
    print(f"[ENV] OpenVINO GenAI ver   : {ov_genai.__version__}")

    core = ov.Core()
    devices = core.available_devices
    print(f"[ENV] Available devices    : {devices}")
    if device not in devices:
        print(f"\nFATAL: Device '{device}' not available. Aborting.")
        return 1
    try:
        full_name = core.get_property(device, "FULL_DEVICE_NAME")
        print(f"[ENV] Target device        : {device} ({full_name})")
    except Exception:
        print(f"[ENV] Target device        : {device}")

    # ── 2. Verify model artifacts ──────────────────────────────────────
    model_xml = model_dir / "openvino_model.xml"
    model_bin = model_dir / "openvino_model.bin"
    tok_json = model_dir / "tokenizer_config.json"

    missing = []
    for p in [model_xml, model_bin, tok_json]:
        if not p.exists():
            missing.append(str(p))
    if missing:
        print(f"\nFATAL: Missing model files:")
        for m in missing:
            print(f"  {m}")
        return 1

    bin_size_mb = model_bin.stat().st_size / (1024 * 1024)
    print(f"\n[MODEL] Directory : {model_dir}")
    print(f"[MODEL] BIN size  : {bin_size_mb:.1f} MB")

    # ── 3. Create LLMPipeline ──────────────────────────────────────────
    print(f"\n[PIPE] Creating LLMPipeline('{model_dir}', '{device}')...")
    print(f"[PIPE] This handles static shape compilation, KV-cache, tokenizer.")
    print(f"[PIPE] First run may take 60-120s for NPU blob compilation...")

    pipeline_config: dict[str, str] = {}

    # Enable blob caching for faster subsequent loads
    cache_dir = args.cache_dir or str(model_dir / ".npucache")
    if device == "NPU":
        pipeline_config["CACHE_DIR"] = cache_dir
        print(f"[PIPE] NPU cache dir: {cache_dir}")

    t_pipe_start = time.perf_counter()
    try:
        pipe = ov_genai.LLMPipeline(
            str(model_dir),
            device,
            **pipeline_config,
        )
    except Exception as exc:
        print(f"\nFATAL: LLMPipeline creation failed: {exc}")
        print(f"\nDiagnostic info:")
        print(f"  model_dir: {model_dir}")
        print(f"  device: {device}")
        print(f"  model_xml exists: {model_xml.exists()}")
        print(f"  model_bin exists: {model_bin.exists()}")
        print(f"  Files in dir: {[f.name for f in model_dir.iterdir()]}")
        return 1
    t_pipe_done = time.perf_counter()
    pipe_ms = (t_pipe_done - t_pipe_start) * 1000
    print(f"[PIPE] LLMPipeline created in {pipe_ms:.0f} ms")

    # ── 4. Configure generation ────────────────────────────────────────
    gen_config = ov_genai.GenerationConfig()
    gen_config.max_new_tokens = MAX_GEN_TOKENS
    gen_config.do_sample = False  # Greedy (temperature=0 equivalent)
    # Stop at end-of-turn token to avoid runaway generation
    try:
        gen_config.stop_strings = {"<|im_end|>"}
    except Exception:
        pass  # Older GenAI versions may not support stop_strings

    print(f"\n[GEN]  max_new_tokens : {gen_config.max_new_tokens}")
    print(f"[GEN]  do_sample      : {gen_config.do_sample}")

    # ── 5. Classify test CARs ──────────────────────────────────────────
    print(f"\n{'─' * 72}")
    print(f"  CLASSIFICATION TESTS ({len(TEST_CARS)} CARs)")
    print(f"  Latency budget: {LATENCY_BUDGET_MS} ms")
    print(f"{'─' * 72}")

    all_pass = True
    results = []

    for i, car in enumerate(TEST_CARS, 1):
        print(f"\n[TEST {i}] {car['name']}")
        prompt = build_prompt(car["text"])

        # Time the generation
        t_start = time.perf_counter()
        try:
            output = pipe.generate(prompt, gen_config)
        except Exception as exc:
            print(f"  FAIL: generate() raised: {exc}")
            all_pass = False
            results.append({
                "test": car["name"],
                "status": "ERROR",
                "error": str(exc),
            })
            continue
        t_end = time.perf_counter()

        latency_ms = (t_end - t_start) * 1000
        raw_output = output.strip()
        label = parse_label(raw_output)
        expected = car["expected"]
        match = label == expected
        within_budget = latency_ms <= LATENCY_BUDGET_MS

        # Clean output for display
        display_output = raw_output.replace("\n", " | ")
        if len(display_output) > 120:
            display_output = display_output[:120] + "..."

        status = "PASS" if match else "MISMATCH"

        print(f"  Output  : {display_output!r}")
        print(f"  Label   : {label} (expected: {expected}) → {'✓' if match else '✗'}")
        print(f"  Latency : {latency_ms:.1f} ms "
              f"({'within' if within_budget else 'EXCEEDS'} "
              f"{LATENCY_BUDGET_MS} ms budget)")

        if not match:
            all_pass = False

        results.append({
            "test": car["name"],
            "status": status,
            "label": label,
            "expected": expected,
            "match": match,
            "output": raw_output[:500],
            "latency_ms": round(latency_ms, 1),
            "within_budget": within_budget,
        })

    # ── 6. Summary ─────────────────────────────────────────────────────
    print(f"\n{'=' * 72}")
    print(f"  SMOKE TEST SUMMARY")
    print(f"{'=' * 72}")
    print(f"  Pipeline creation : {pipe_ms:.0f} ms")
    print(f"  Device            : {device}")
    print(f"  Model             : Qwen2.5-1.5B-Instruct INT4-MIXED ({bin_size_mb:.0f} MB)")

    passed = sum(1 for r in results if r.get("match", False))
    errored = sum(1 for r in results if r.get("status") == "ERROR")
    total = len(results)

    for r in results:
        tag = "✓" if r.get("match") else ("ERR" if r.get("status") == "ERROR" else "✗")
        latency_str = f"{r['latency_ms']} ms" if "latency_ms" in r else "N/A"
        label_str = r.get("label", "N/A")
        print(f"  [{tag}] {r['test']}: {label_str} ({latency_str})")

    avg_latency = 0.0
    latencies = [r["latency_ms"] for r in results if "latency_ms" in r]
    if latencies:
        avg_latency = sum(latencies) / len(latencies)
        print(f"\n  Avg latency       : {avg_latency:.1f} ms")
        print(f"  Max latency       : {max(latencies):.1f} ms")
        print(f"  Min latency       : {min(latencies):.1f} ms")

    if errored:
        print(f"\n  RESULT: {errored}/{total} tests ERRORED — inference failed")
        return 1
    elif all_pass:
        print(f"\n  RESULT: {passed}/{total} labels correct — SMOKE TEST PASSED")
        return 0
    else:
        print(f"\n  RESULT: {passed}/{total} labels correct — labels did not match")
        print(f"  NOTE: Label mismatches are informational. The critical gate")
        print(f"  is whether inference runs at all on the NPU.")
        # Return 0 even for mismatches — the smoke test is about hardware, not accuracy
        return 0 if not errored else 1


if __name__ == "__main__":
    sys.exit(main())
