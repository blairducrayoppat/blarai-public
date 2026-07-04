"""
Qwen3-VL-8B perf harness (Session-2 §4) — VLM TTFT/TPOT/load, fixed image+prompt.
================================================================================
Measures the Qwen3-VL-8B-Instruct INT4 VLM on the Arc 140V: model load+compile,
TTFT (includes vision encode + LLM prefill), TPOT, on a FIXED deterministic image
and prompt. OpenVINO version stamped so the same harness on 2026.1.0 vs 2026.2.1
is a true A/B (the PR #3640 slice-before-matmul VLM win has no committed 2026.1.0
reference, so this is measured both sides in the restore window).

Usage (repo root, runtime venv, LOCALAPPDATA redirected, GPU clean):
  .venv/Scripts/python.exe scratchpad/vlm_perf.py
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if not (_REPO_ROOT / "shared").exists():
    _REPO_ROOT = Path.cwd()
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import numpy as np  # noqa: E402
import openvino as ov  # noqa: E402
import openvino_genai as ov_genai  # noqa: E402
from PIL import Image  # noqa: E402

VLM_DIR = _REPO_ROOT / "models" / "qwen3-vl-8b-instruct" / "openvino-int4-ov"


def fixed_image(size: int = 512):
    """Deterministic gradient image so the vision tower does real, repeatable work."""
    img = Image.new("RGB", (size, size))
    px = img.load()
    for y in range(size):
        for x in range(size):
            px[x, y] = ((x * 256) // size, (y * 256) // size, ((x + y) * 128 // size) % 256)
    return img


def _ms(mp):
    try:
        return round(float(mp.mean), 2)
    except Exception:  # noqa: BLE001
        return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-new-tokens", type=int, default=128)
    ap.add_argument("--warmup", type=int, default=1)
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--device", default="GPU")
    args = ap.parse_args()

    ov_ver = ov_genai.__version__
    print(f"== Qwen3-VL-8B perf == ov={ov_ver} device={args.device}")
    if not (VLM_DIR / "openvino_language_model.xml").exists():
        print(f"FATAL: VLM not found at {VLM_DIR}")
        return 1

    img = fixed_image(512)
    img_tensor = ov.Tensor(np.array(img))  # VLMPipeline wants an ov.Tensor, not PIL
    prompt = "Describe this image in detail, including its colors and patterns."

    t0 = time.perf_counter()
    pipe = ov_genai.VLMPipeline(str(VLM_DIR), args.device)
    load_s = time.perf_counter() - t0
    print(f"   load+compile: {load_s:.1f}s")

    gen = ov_genai.GenerationConfig()
    gen.max_new_tokens = args.max_new_tokens
    gen.do_sample = False

    for _ in range(args.warmup):
        pipe.generate(prompt, images=[img_tensor], generation_config=gen)

    rows = []
    for r in range(args.runs):
        t = time.perf_counter()
        res = pipe.generate(prompt, images=[img_tensor], generation_config=gen)
        wall = time.perf_counter() - t
        pm = getattr(res, "perf_metrics", None)
        ttft = _ms(pm.get_ttft()) if pm else None
        tpot = _ms(pm.get_tpot()) if pm else None
        thr = _ms(pm.get_throughput()) if pm else None
        rows.append({"run": r, "wall_s": round(wall, 2), "ttft_ms": ttft,
                     "tpot_ms": tpot, "throughput_tok_s": thr})
        print(f"   run {r}: wall={wall:.2f}s ttft={ttft}ms tpot={tpot}ms thr={thr}tok/s")

    def med(k):
        vals = [r[k] for r in rows if r[k] is not None]
        return round(statistics.median(vals), 2) if vals else None

    summary = {"load_compile_s": round(load_s, 1), "ttft_ms_median": med("ttft_ms"),
               "tpot_ms_median": med("tpot_ms"), "throughput_median": med("throughput_tok_s")}
    print(f"\n   SUMMARY: load={summary['load_compile_s']}s ttft={summary['ttft_ms_median']}ms "
          f"tpot={summary['tpot_ms_median']}ms thr={summary['throughput_median']}tok/s")

    out = {"harness": "vlm_perf", "model": "qwen3-vl-8b-instruct-int4",
           "openvino_genai_version": ov_ver, "openvino_version": __import__("openvino").__version__,
           "device": args.device, "config": {"max_new_tokens": args.max_new_tokens,
           "warmup": args.warmup, "runs": args.runs, "image": "512x512 deterministic gradient",
           "prompt": prompt, "do_sample": False}, "summary": summary, "rows": rows}
    safe_ov = ov_ver.split("-")[0].replace(".", "_")
    ts = time.strftime("%Y-%m-%d_%H-%M-%S")
    outpath = _REPO_ROOT / "docs" / "performance" / f"vlm_perf_ov{safe_ov}_{ts}.json"
    outpath.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(f"[SAVE] {outpath}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
