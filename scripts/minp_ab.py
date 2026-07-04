"""
min_p A/B (Session-2 §4) — AO answer-quality knob, SCOPED as a non-default what-if.
===================================================================================
`[generation].min_p` (OV GenAI 2026.2, PR #3752) drops tokens with prob <
min_p * p_max before sampling. It ONLY affects do_sample=True; BlarAI production
runs greedy (temp=0, do_sample=False), so this is a what-if for a non-default
sampling mode — measured, scoped, NOT gating the campaign.

A/B: same prompts, same fixed rng_seed + temperature, sweep min_p {0.0, 0.05, 0.1}
with do_sample=True. min_p is meant to suppress low-probability "tail" tokens that
cause incoherence/derailment at higher temperature, so the signal to watch is
coherence + degenerate repetition. Reproducible quality proxy: distinct-trigram
ratio (unique 3-grams / total; LOWER = more repetition). Full texts captured for
qualitative read. No latency cost is expected (min_p is a cheap filter).

Usage (repo root, runtime venv, LOCALAPPDATA redirected, GPU clean):
  .venv/Scripts/python.exe scratchpad/minp_ab.py
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if not (_REPO_ROOT / "shared").exists():
    _REPO_ROOT = Path.cwd()
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import openvino_genai as ov_genai  # noqa: E402
from shared.constants import TARGET_MODEL_OV_PATH  # noqa: E402

# Longer-generation prompts where sampling tails actually matter (a factual-only
# set wouldn't exercise min_p). Fixed = reproducible.
PROMPTS = [
    "Write a short paragraph describing a walk through a forest in autumn.",
    "Explain, in a few sentences, how a bicycle stays upright when moving.",
    "Describe an imaginary city built on the surface of the ocean.",
]


def distinct_trigram_ratio(text: str) -> float:
    toks = text.split()
    if len(toks) < 3:
        return 1.0
    grams = [tuple(toks[i:i + 3]) for i in range(len(toks) - 2)]
    return round(len(set(grams)) / len(grams), 4)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model-dir", default=str(_REPO_ROOT / TARGET_MODEL_OV_PATH))
    ap.add_argument("--min-ps", default="0.0,0.05,0.1")
    ap.add_argument("--temperature", type=float, default=0.8)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--max-new-tokens", type=int, default=200)
    args = ap.parse_args()

    model_dir = str(Path(args.model_dir).resolve())
    min_ps = [float(x) for x in args.min_ps.split(",")]
    ov_ver = ov_genai.__version__
    print(f"== min_p A/B == ov={ov_ver} temp={args.temperature} seed={args.seed}")

    sched = ov_genai.SchedulerConfig()
    sched.cache_size = 3
    sched.enable_prefix_caching = False
    pipe = ov_genai.LLMPipeline(
        model_dir, "GPU",
        PERFORMANCE_HINT="LATENCY", INFERENCE_PRECISION_HINT="f16",
        GPU_ENABLE_SDPA_OPTIMIZATION="ON", CACHE_DIR="", scheduler_config=sched,
    )

    rows = []
    for mp in min_ps:
        for i, prompt in enumerate(PROMPTS):
            gen = ov_genai.GenerationConfig()
            gen.max_new_tokens = args.max_new_tokens
            gen.do_sample = True
            gen.temperature = args.temperature
            gen.top_p = 1.0
            gen.top_k = 0
            gen.min_p = mp
            gen.rng_seed = args.seed
            t = time.perf_counter()
            res = pipe.generate([prompt], gen)
            dt = time.perf_counter() - t
            text = res.texts[0] if hasattr(res, "texts") else str(res)
            dtr = distinct_trigram_ratio(text)
            rows.append({"min_p": mp, "prompt_index": i, "wall_s": round(dt, 2),
                         "n_words": len(text.split()), "distinct_trigram_ratio": dtr,
                         "text": text})
            print(f"  min_p={mp:<5} p{i}: words={len(text.split())} distinct3gram={dtr} ({dt:.1f}s)")

    # Aggregate the repetition proxy per min_p
    print("\n=== distinct-trigram ratio (higher = less repetition) ===")
    for mp in min_ps:
        vals = [r["distinct_trigram_ratio"] for r in rows if r["min_p"] == mp]
        print(f"  min_p={mp}: mean distinct-3gram = {round(sum(vals)/len(vals),4)}")

    out = {"harness": "minp_ab", "openvino_genai_version": ov_ver, "model_dir": model_dir,
           "config": {"min_ps": min_ps, "temperature": args.temperature, "seed": args.seed,
                      "max_new_tokens": args.max_new_tokens, "do_sample": True,
                      "note": "non-default sampling mode; production is greedy (temp=0)"},
           "rows": rows}
    ts = time.strftime("%Y-%m-%d_%H-%M-%S")
    outpath = _REPO_ROOT / "docs" / "performance" / f"minp_ab_{ts}.json"
    outpath.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(f"\n[SAVE] {outpath}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
