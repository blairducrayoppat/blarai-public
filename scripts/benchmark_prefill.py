"""
Prefill (prompt-processing) benchmark — STANDING baseline harness.
==================================================================
A dedicated, reproducible prefill-throughput benchmark, part of BlarAI's standing
performance methodology (added 2026-06-29). It exists because the single-shot pp
side-probe inside ``benchmark_gpu_inference.py`` is one sample at one length and
is too noisy to trust for a version A/B; this harness measures prefill at SEVERAL
fixed input lengths, N repeats each, on the PLAIN autoregressive pipeline (no
draft — pure target prefill) with prefix-caching OFF (forced cold prefill via a
per-repeat nonce), so a real engine-level prefill change is cleanly separable from
probe noise or a changed default. Observed run-to-run std is single-digit pp.

pp = input_tokens / prefill_seconds (the llama-bench pp metric); prefill time ~=
the latency of a ``max_new_tokens=1`` generation. The OpenVINO version is stamped
into the output so the same harness run on two OpenVINO releases is a true A/B.

Methodology (hold constant for comparability, mirrors benchmark_gpu_inference.py):
  - plain LLMPipeline, GPU, no draft, prefix-caching OFF, CACHE_DIR=""
  - lengths {512, 2048, 8192} tokens (default), N=5 repeats + 1 warmup
  - report pp mean / median / std per length, prefill_ms median

Usage (repo root, runtime venv, LOCALAPPDATA redirected):
  .venv\\Scripts\\python.exe scripts\\benchmark_prefill.py --model-dir models\\qwen3-14b\\openvino-int4-gpu --model-name 14b
  .venv\\Scripts\\python.exe scripts\\benchmark_prefill.py --model-dir models\\qwen3-8b\\openvino-int4-gpu  --model-name 8b
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import openvino_genai as ov_genai  # noqa: E402
from transformers import AutoTokenizer  # noqa: E402

# Neutral, version-controlled filler. Held constant so token counts and the
# prefill workload are comparable across runs and OpenVINO releases.
_BASE = (
    "The quick brown fox jumps over the lazy dog near the river bank while the "
    "sun sets slowly behind the distant mountains and a gentle wind carries the "
    "scent of pine across the quiet valley below. "
)


def make_prompt(tok, n_tokens: int, nonce: str) -> tuple[str, int]:
    """Build a prompt of ~n_tokens tokens, prefixed with a unique nonce.

    The nonce defeats any residual prefix cache so every repeat pays a real
    cold prefill. Returns (prompt, actual_token_count).
    """
    reps = max(1, (n_tokens // 30) + 4)
    raw = nonce + " " + (_BASE * reps)
    ids = tok(raw)["input_ids"][:n_tokens]
    prompt = tok.decode(ids, skip_special_tokens=True)
    actual = len(tok(prompt)["input_ids"])
    return prompt, actual


def main() -> int:
    ap = argparse.ArgumentParser(description="BlarAI standing prefill benchmark (pp).")
    ap.add_argument("--model-dir", required=True, help="repo-relative or absolute model dir")
    ap.add_argument("--model-name", required=True, help="short tag for the output filename")
    ap.add_argument("--lengths", default="512,2048,8192", help="comma-separated input token lengths")
    ap.add_argument("--repeats", type=int, default=5)
    ap.add_argument("--warmup", type=int, default=1)
    args = ap.parse_args()

    md = Path(args.model_dir)
    model_dir = str(md if md.is_absolute() else (_REPO_ROOT / md).resolve())
    lengths = [int(x) for x in args.lengths.split(",")]
    ov_ver = ov_genai.__version__

    print(f"== prefill benchmark == model={args.model_name} ov={ov_ver}")
    print(f"   lengths={lengths} repeats={args.repeats} (no-draft, prefix-cache OFF, cold prefill)")

    if not (Path(model_dir) / "openvino_model.xml").exists():
        print(f"FATAL: model not found at {model_dir}")
        return 1

    tok = AutoTokenizer.from_pretrained(model_dir)

    sched = ov_genai.SchedulerConfig()
    sched.cache_size = 3
    sched.enable_prefix_caching = False  # force cold prefill
    t0 = time.perf_counter()
    pipe = ov_genai.LLMPipeline(
        model_dir, "GPU",
        PERFORMANCE_HINT="LATENCY", INFERENCE_PRECISION_HINT="f16",
        GPU_ENABLE_SDPA_OPTIMIZATION="ON", CACHE_DIR="",
        scheduler_config=sched,
    )
    print(f"   load+compile: {time.perf_counter() - t0:.1f}s")

    gen = ov_genai.GenerationConfig()
    gen.max_new_tokens = 1
    gen.do_sample = False

    for _ in range(args.warmup):
        p, _ = make_prompt(tok, lengths[0], "warmup")
        pipe.generate(p, gen)

    results: dict[str, dict] = {}
    for L in lengths:
        pps, ms_list, toks = [], [], []
        for r in range(args.repeats):
            prompt, actual = make_prompt(tok, L, f"r{r}L{L}nonce{r * 7 + 13}")
            t = time.perf_counter()
            pipe.generate(prompt, gen)
            dt_ms = (time.perf_counter() - t) * 1000.0
            pp = actual / (dt_ms / 1000.0) if dt_ms > 0 else 0.0
            pps.append(pp); ms_list.append(dt_ms); toks.append(actual)
            print(f"   L~{L} r{r}: in={actual} prefill={dt_ms:.0f}ms pp={pp:.0f}")
        results[str(L)] = {
            "target_len": L,
            "actual_tokens_mean": round(statistics.mean(toks), 1),
            "prefill_ms_median": round(statistics.median(ms_list), 1),
            "pp_mean": round(statistics.mean(pps), 1),
            "pp_median": round(statistics.median(pps), 1),
            "pp_std": round(statistics.pstdev(pps), 1) if len(pps) > 1 else 0.0,
            "n": len(pps),
        }
        print(f"   == L~{L}: pp median={results[str(L)]['pp_median']} "
              f"mean={results[str(L)]['pp_mean']} std={results[str(L)]['pp_std']}")

    out = {
        "harness": "benchmark_prefill",
        "model_name": args.model_name,
        "model_dir": model_dir,
        "openvino_genai_version": ov_ver,
        "openvino_version": __import__("openvino").__version__,
        "config": {"lengths": lengths, "repeats": args.repeats,
                   "prefix_caching": False, "draft": None, "do_sample": False},
        "results": results,
    }
    safe_ov = ov_ver.split("-")[0].replace(".", "_")
    ts = time.strftime("%Y-%m-%d_%H-%M-%S")
    outpath = _REPO_ROOT / "docs" / "performance" / f"prefill_{args.model_name}_ov{safe_ov}_{ts}.json"
    outpath.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(f"\n[SAVE] {outpath}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
