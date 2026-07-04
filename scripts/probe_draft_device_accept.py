"""
Draft-device acceptance + throughput probe (Session-2 addition #1).
===================================================================
Measures speculative-decoding ACCEPTANCE behaviour + throughput for GPU-draft
vs CPU-draft on Qwen3-14B INT4 target + Qwen3-0.6B-pruned-6L INT8 draft, reading
the OV GenAI 2026.2.1 ``DecodedResults.extended_perf_metrics`` (an
``SDPerModelsPerfMetrics``) — which is exposed only via the LIST form of
generate (``pipe.generate([prompt], cfg)``); the single-string form returns a
bare ``str`` with no metrics.

This is a NEW measurement for the draft-device dimension. The comparable,
baseline-methodology gen tok/s still comes from scripts/benchmark_gpu_inference.py
(--draft-device GPU|CPU); this probe adds the acceptance rate (and corroborating
throughput/TTFT). Run foreground UT separately for the CPU/GPU utilisation split.

Acceptance rate is reported two ways (both stated, so the reader can pick):
  - accepted / draft_proposed   (fraction of speculated tokens the target kept)
  - accepted / generated        (fraction of OUTPUT tokens that came free from draft)

Usage (repo root, runtime venv, LOCALAPPDATA redirected):
  .venv/Scripts/python.exe scratchpad/probe_draft_device_accept.py --draft-device GPU
  .venv/Scripts/python.exe scratchpad/probe_draft_device_accept.py --draft-device CPU
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

from shared.constants import (  # noqa: E402
    DRAFT_MODEL_OV_PATH,
    NUM_ASSISTANT_TOKENS,
    TARGET_MODEL_OV_PATH,
)

# Same version-controlled prompt set as scripts/benchmark_gpu_inference.py (v1)
PROMPTS: list[str] = [
    "What is the capital city of France?",
    "How many bytes are in one kilobyte?",
    "Explain what a transformer neural network is in plain language.",
    "What is quantization in the context of machine learning models, "
    "and why does it help with inference speed?",
]


def _ms_pair(mp) -> dict:
    """Extract a MeanStdPair (.mean/.std) defensively."""
    try:
        return {"mean": round(float(mp.mean), 4), "std": round(float(mp.std), 4)}
    except Exception:  # noqa: BLE001
        return {"mean": None, "std": None}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--draft-device", default="GPU", help="GPU (default) or CPU")
    ap.add_argument("--target-dir", default=None, help="target model dir (repo-relative or absolute); default 14B")
    ap.add_argument("--draft-dir", default=None, help="draft model dir; default 0.6B-pruned-6L")
    ap.add_argument("--label", default="14b", help="short tag for the output filename")
    ap.add_argument("--max-new-tokens", type=int, default=256)
    ap.add_argument("--warmup", type=int, default=1)
    ap.add_argument("--runs", type=int, default=2, help="measured passes over the prompt set")
    ap.add_argument("--num-assistant-tokens", type=int, default=NUM_ASSISTANT_TOKENS)
    args = ap.parse_args()

    def _resolve(p, default):
        if not p:
            return str(_REPO_ROOT / default)
        pp = Path(p)
        return str(pp if pp.is_absolute() else _REPO_ROOT / pp)
    target_dir = _resolve(args.target_dir, TARGET_MODEL_OV_PATH)
    draft_dir = _resolve(args.draft_dir, DRAFT_MODEL_OV_PATH)
    draft_dev = args.draft_device.upper()

    print("== draft-device acceptance + throughput probe ==")
    print(f"  openvino_genai      : {ov_genai.__version__}")
    print(f"  draft device        : {draft_dev}  (target device: GPU)")
    print(f"  num_assistant_tokens: {args.num_assistant_tokens}  max_new_tokens: {args.max_new_tokens}")
    print(f"  warmup/runs         : {args.warmup}/{args.runs}")

    scheduler = ov_genai.SchedulerConfig()
    scheduler.cache_size = 3
    scheduler.enable_prefix_caching = True

    t0 = time.perf_counter()
    # GPU-only props (SDPA opt) must NOT be passed to the CPU plugin.
    draft_props = {"PERFORMANCE_HINT": "LATENCY", "INFERENCE_PRECISION_HINT": "f16", "CACHE_DIR": ""}
    if draft_dev == "GPU":
        draft_props["GPU_ENABLE_SDPA_OPTIMIZATION"] = "ON"
    draft = ov_genai.draft_model(draft_dir, draft_dev, **draft_props)
    pipe = ov_genai.LLMPipeline(
        target_dir, "GPU",
        PERFORMANCE_HINT="LATENCY", MODEL_PRIORITY="HIGH", INFERENCE_PRECISION_HINT="f16",
        GPU_ENABLE_SDPA_OPTIMIZATION="ON", CACHE_DIR="",
        scheduler_config=scheduler, draft_model=draft,
    )
    load_s = time.perf_counter() - t0
    print(f"  load+compile        : {load_s:.1f}s")

    gen = ov_genai.GenerationConfig()
    gen.max_new_tokens = args.max_new_tokens
    gen.num_assistant_tokens = args.num_assistant_tokens
    gen.do_sample = False  # greedy — production posture

    # Warmup (discarded). The draft sub-model's num_generated is CUMULATIVE over
    # the pipeline lifetime, so capture its value at warmup-end as the baseline
    # for per-call differencing below.
    draft_prev = 0
    for _ in range(args.warmup):
        for p in PROMPTS:
            r = pipe.generate([p], gen)
            e = getattr(r, "extended_perf_metrics", None)
            if e is not None and type(e).__name__ == "SDPerModelsPerfMetrics":
                draft_prev = int(e.draft_model_metrics.get_num_generated_tokens())

    per_prompt = []
    sd_ok = True
    for run_idx in range(args.runs):
        for i, prompt in enumerate(PROMPTS):
            t = time.perf_counter()
            res = pipe.generate([prompt], gen)
            wall = time.perf_counter() - t
            epm = getattr(res, "extended_perf_metrics", None)
            row = {"run": run_idx, "prompt_index": i, "wall_s": round(wall, 3)}
            if epm is not None and type(epm).__name__ == "SDPerModelsPerfMetrics":
                gen_tok = int(epm.get_num_generated_tokens())
                acc_tok = int(epm.get_num_accepted_tokens())
                draft_cum = int(epm.draft_model_metrics.get_num_generated_tokens())
                draft_proposed = draft_cum - draft_prev  # per-call (cumulative delta)
                draft_prev = draft_cum
                row.update({
                    "generated": gen_tok,
                    "accepted": acc_tok,
                    "draft_proposed": draft_proposed,
                    "ttft": _ms_pair(epm.get_ttft()),
                    "tpot": _ms_pair(epm.get_tpot()),
                    "throughput": _ms_pair(epm.get_throughput()),
                })
            else:
                sd_ok = False
                row["note"] = f"no SD metrics (epm={type(epm).__name__})"
            per_prompt.append(row)
            print(f"  run {run_idx} prompt {i}: wall={wall:.2f}s "
                  + (f"gen={row.get('generated')} acc={row.get('accepted')} "
                     f"proposed={row.get('draft_proposed')}" if "generated" in row else row.get("note", "")))

    # Aggregate acceptance
    summary: dict = {"draft_device": draft_dev, "sd_metrics_available": sd_ok}
    if sd_ok:
        tot_gen = sum(r["generated"] for r in per_prompt)
        tot_acc = sum(r["accepted"] for r in per_prompt)
        tot_draft = sum(r["draft_proposed"] for r in per_prompt)
        summary.update({
            "total_generated": tot_gen,
            "total_accepted": tot_acc,
            "total_draft_proposed": tot_draft,
            "acceptance_rate_accepted_per_draft": round(tot_acc / tot_draft, 4) if tot_draft else None,
            "acceptance_rate_accepted_per_generated": round(tot_acc / tot_gen, 4) if tot_gen else None,
            "throughput_tok_s_mean": round(
                sum(r["throughput"]["mean"] for r in per_prompt) / len(per_prompt), 3),
        })
        print("\n--- ACCEPTANCE SUMMARY ---")
        print(f"  draft device              : {draft_dev}")
        print(f"  accepted / draft_proposed : {tot_acc}/{tot_draft} = {summary['acceptance_rate_accepted_per_draft']}")
        print(f"  accepted / generated      : {tot_acc}/{tot_gen} = {summary['acceptance_rate_accepted_per_generated']}")
        print(f"  mean throughput (SD)      : {summary['throughput_tok_s_mean']} tok/s")

    out = {
        "probe": "draft_device_accept",
        "openvino_genai_version": ov_genai.__version__,
        "config": {
            "target": target_dir, "draft": draft_dir, "draft_device": draft_dev,
            "num_assistant_tokens": args.num_assistant_tokens,
            "max_new_tokens": args.max_new_tokens, "warmup": args.warmup, "runs": args.runs,
            "load_compile_s": round(load_s, 1), "prompt_set": "v1", "do_sample": False,
        },
        "summary": summary,
        "per_prompt": per_prompt,
    }
    ts = time.strftime("%Y-%m-%d_%H-%M-%S")
    outpath = _REPO_ROOT / "docs" / "performance" / f"draft_device_accept_{args.label}_{draft_dev.lower()}_{ts}.json"
    outpath.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(f"\n[SAVE] {outpath}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
