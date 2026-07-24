"""
Qwen3.6-35B-A3B multimodal QUALITY probe (#769 consolidation branch, gate B evidence)
=====================================================================================
First vision-path exercise of the official 35B IR on this box — every 2026-07-16
record named "vision path not benched" as a gap; this closes the qualitative half.
Three images with different demands (rendered scene, real photograph, detail-heavy
render), one descriptive prompt each, full outputs captured verbatim for the
operator's quality judgment (never judged by this script). Latencies recorded per
the capture rule. Runtime substrate (OpenVINO GenAI 2026.2.1 — the consolidation
target), thinking ON (no working disable exists on this substrate — the outputs
honestly show what a swap would feel like today).

Usage (box lean, BlarAI down):
  .venv\\Scripts\\python.exe scripts\\probe_35b_multimodal_quality.py
"""

from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import openvino as ov
import openvino_genai as ov_genai
from PIL import Image

_REPO_ROOT = Path(__file__).resolve().parent.parent
MODEL_DIR = Path("C:/Users/mrbla/models/qwen36-35b-a3b-int4-ov-OFFICIAL")

CASES = [
    {
        "label": "rendered_scene",
        "path": _REPO_ROOT / "blarai_lighthouse3.png",
        "prompt": "Describe this image in detail: setting, style, lighting, and mood.",
    },
    {
        "label": "logo_graphic",
        "path": _REPO_ROOT / "branding" / "blair_glow.png",
        "prompt": "Describe this graphic: what it depicts, its style, colors, and what kind "
                  "of project or product it would suit.",
    },
    {
        "label": "detail_render",
        "path": _REPO_ROOT / "hand2.png",
        "prompt": "Describe exactly what this image shows, including any anatomical or "
                  "structural details, and note anything that looks wrong or artificial.",
    },
]
MAX_TOKENS = 420


def main() -> int:
    results: dict[str, Any] = {
        "purpose": "35B-A3B multimodal quality probe (consolidation gate B — operator judges quality)",
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "hardware": "Intel Core Ultra 7 258V / Arc 140V, driver 32.0.101.8826",
        "openvino_genai_version": ov_genai.__version__,
        "model": "OpenVINO/Qwen3.6-35B-A3B-int4-ov (official), VLMPipeline, GPU",
        "max_new_tokens": MAX_TOKENS,
        "note": "thinking ON (no working disable on this substrate — genai #3937 / PR #4139); "
                "outputs are verbatim, quality judged by the operator, never by this script",
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
    out_path = _REPO_ROOT / "docs" / "performance" / f"probe_35b_multimodal_quality_{stamp}.json"
    out_path.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"results: {out_path}")
    return 0 if any("output" in c for c in results["cases"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
