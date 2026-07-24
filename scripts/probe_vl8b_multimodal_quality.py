"""
Qwen3-VL-8B multimodal QUALITY probe — the head-to-head twin of the 35B probe
==============================================================================
The decisive retire-VL comparison (#769 consolidation / #550 gate): the SAME
three images and prompts as scripts/probe_35b_multimodal_quality.py (imported,
not copied — byte-identity is the head-to-head contract), run through the
PRODUCTION vision model (Qwen3-VL-8B INT4, the IR the runtime's
shared/inference/vlm.py loads), same OpenVINO GenAI VLMPipeline on GPU, same
greedy decoding and token budget. Outputs captured verbatim for the operator's
quality judgment (never judged by this script); latencies recorded per the
capture rule.

Usage (box lean, BlarAI down):
  .venv\\Scripts\\python.exe scripts\\probe_vl8b_multimodal_quality.py
"""

from __future__ import annotations

import json
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import openvino as ov
import openvino_genai as ov_genai
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
from probe_35b_multimodal_quality import CASES, MAX_TOKENS  # noqa: E402 — the head-to-head contract

_REPO_ROOT = Path(__file__).resolve().parent.parent
MODEL_DIR = _REPO_ROOT / "models" / "qwen3-vl-8b-instruct" / "openvino-int4-ov"


def main() -> int:
    results: dict[str, Any] = {
        "purpose": "Qwen3-VL-8B multimodal quality probe — head-to-head twin of the 35B probe "
                   "(retire-VL decision evidence; operator judges quality)",
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "hardware": "Intel Core Ultra 7 258V / Arc 140V, driver 32.0.101.8826",
        "openvino_genai_version": ov_genai.__version__,
        "model": "qwen3-vl-8b-instruct openvino-int4-ov (production vision model), VLMPipeline, GPU",
        "max_new_tokens": MAX_TOKENS,
        "note": "cases + prompts + token budget imported from probe_35b_multimodal_quality.py "
                "(byte-identical head-to-head); outputs verbatim, quality judged by the operator",
        "pair": "compare against probe_35b_multimodal_quality_*.json (2026-07-16 run)",
        "cases": [],
    }
    print("loading VLMPipeline (GPU)…", flush=True)
    t0 = time.perf_counter()
    pipe = ov_genai.VLMPipeline(str(MODEL_DIR), "GPU")
    results["load_seconds"] = round(time.perf_counter() - t0, 1)
    print(f"loaded in {results['load_seconds']}s", flush=True)

    cfg = ov_genai.GenerationConfig()
    cfg.max_new_tokens = MAX_TOKENS
    cfg.do_sample = False

    for case in CASES:
        rec: dict[str, Any] = {"label": case["label"], "image": case["path"].name,
                               "prompt": case["prompt"]}
        try:
            img = Image.open(case["path"]).convert("RGB")
            rec["image_size"] = list(img.size)
            tensor = ov.Tensor(np.array(img))
            t0 = time.perf_counter()
            out = str(pipe.generate(case["prompt"], images=[tensor], generation_config=cfg))
            rec["seconds"] = round(time.perf_counter() - t0, 1)
            rec["output"] = out
            print(f"[{case['label']}] {rec['seconds']}s, {len(out)} chars", flush=True)
        except Exception as exc:  # noqa: BLE001 — a failing case is a datum
            rec["error"] = str(exc)[:400]
            print(f"[{case['label']}] ERROR {str(exc)[:120]}", flush=True)
        results["cases"].append(rec)

    stamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    out_path = _REPO_ROOT / "docs" / "performance" / f"probe_vl8b_multimodal_quality_{stamp}.json"
    out_path.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"results: {out_path}")
    return 0 if any("output" in c for c in results["cases"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
