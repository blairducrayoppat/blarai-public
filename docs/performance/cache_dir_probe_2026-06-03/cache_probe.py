#!/usr/bin/env python
"""Throwaway CACHE_DIR empirical probe — BlarAI Vikunja #545 (voice handoff §7.1).

Settles whether enabling the OpenVINO GPU compile cache (CACHE_DIR=<dir>)
changes greedy generation output vs the production CACHE_DIR="" fresh compile,
and measures the cold-vs-warm pipeline load-time delta on the Arc 140V.

The construction below MIRRORS shared/inference/shared_pipeline.py lines
197-223 EXACTLY (LATENCY / f16 / SDPA ON / MODEL_PRIORITY=HIGH, spec-decode
draft, scheduler cache_size=3 + prefix_caching=True per launcher/__main__.py:529)
with ONE variable changed: CACHE_DIR. This file does NOT import or modify any
committed pipeline code; it is read-only w.r.t. the runtime and lives under
gitignored userdata/. Each `run` builds ONE pipeline in a FRESH PROCESS so the
cold/warm load timing is not contaminated by in-process GPU/runtime state.

Governance question (gpu-runtime.md:99-102 claims a fresh compile gives
"guaranteed identical compiled state"): does prod-output == warm-cache-output,
token-for-token? Greedy + identical input + same tokenizer => exact-string
identity is token identity; SHA-256 of the output string is the crisp witness.
"""
from __future__ import annotations

import argparse
import gc
import hashlib
import json
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
TARGET_DIR = REPO_ROOT / "models" / "qwen3-14b" / "openvino-int4-gpu"
DRAFT_DIR = REPO_ROOT / "models" / "qwen3-0.6b-pruned-6l" / "openvino-int8-gpu"

# Fixed deterministic prompts. Greedy decoding => deterministic; identical
# across all modes, so any output divergence is attributable to the compiled
# state (cache vs fresh), which is the only variable.
PROMPTS = [
    "List the first 10 prime numbers.",
    "If a train travels 60 km in 1.5 hours, what is its average "
    "speed in km/h? Show your reasoning.",
    "Write a haiku about a lighthouse.",
]

MAX_NEW_TOKENS = 128
NUM_ASSISTANT_TOKENS = 3  # spec-decode; shared/constants.py:173


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _dir_size(p: Path) -> tuple[int, int]:
    files = [f for f in p.rglob("*") if f.is_file()]
    return len(files), sum(f.stat().st_size for f in files)


def build_pipeline(cache_dir: str):
    """Mirror build_shared_pipeline construction, CACHE_DIR parametrised.

    Returns (pipeline, load_seconds) where load_seconds spans the FULL
    draft+target construction (what the operator experiences as cold start).
    """
    import openvino_genai as ov_genai

    scheduler = ov_genai.SchedulerConfig()
    scheduler.cache_size = 3
    scheduler.enable_prefix_caching = True  # launcher/__main__.py:529

    t0 = time.perf_counter()
    draft = ov_genai.draft_model(
        str(DRAFT_DIR),
        "GPU",
        PERFORMANCE_HINT="LATENCY",
        INFERENCE_PRECISION_HINT="f16",
        GPU_ENABLE_SDPA_OPTIMIZATION="ON",
        CACHE_DIR=cache_dir,
    )
    target_config: dict[str, object] = {
        "PERFORMANCE_HINT": "LATENCY",
        "MODEL_PRIORITY": "HIGH",
        "INFERENCE_PRECISION_HINT": "f16",
        "GPU_ENABLE_SDPA_OPTIMIZATION": "ON",
        "CACHE_DIR": cache_dir,
        "scheduler_config": scheduler,
        "draft_model": draft,
    }
    pipe = ov_genai.LLMPipeline(str(TARGET_DIR), "GPU", **target_config)
    return pipe, time.perf_counter() - t0


def do_run(args: argparse.Namespace) -> None:
    import openvino
    import openvino_genai as ov_genai

    cache_dir = "" if args.mode == "prod" else args.cache_dir
    if args.mode == "cache":
        Path(cache_dir).mkdir(parents=True, exist_ok=True)

    pipe, load_seconds = build_pipeline(cache_dir)

    gen = ov_genai.GenerationConfig()
    gen.max_new_tokens = MAX_NEW_TOKENS
    gen.do_sample = False  # greedy
    gen.num_assistant_tokens = NUM_ASSISTANT_TOKENS
    if hasattr(gen, "rng_seed"):
        gen.rng_seed = 0
    if hasattr(gen, "apply_chat_template"):
        gen.apply_chat_template = False  # raw prompt in == raw text out

    results = []
    for prompt in PROMPTS:
        g0 = time.perf_counter()
        res = pipe.generate(prompt, gen)
        gen_seconds = time.perf_counter() - g0
        try:
            text = res.texts[0]
        except AttributeError:
            text = str(res)
        results.append({
            "prompt": prompt,
            "text": text,
            "sha256": _sha(text),
            "n_chars": len(text),
            "gen_seconds": round(gen_seconds, 3),
        })

    cache_files, cache_bytes = (0, 0)
    if args.mode == "cache":
        cache_files, cache_bytes = _dir_size(Path(cache_dir))

    out = {
        "label": args.label,
        "mode": args.mode,
        "cache_dir": cache_dir,
        "openvino": openvino.__version__,
        "openvino_genai": ov_genai.__version__,
        "load_seconds": round(load_seconds, 3),
        "max_new_tokens": MAX_NEW_TOKENS,
        "num_assistant_tokens": NUM_ASSISTANT_TOKENS,
        "cache_dir_files": cache_files,
        "cache_dir_bytes": cache_bytes,
        "prompts": results,
    }
    Path(args.out).write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(
        f"[{args.label}] mode={args.mode} load={load_seconds:.2f}s "
        f"cache_files={cache_files} cache_bytes={cache_bytes:,} "
        f"shas={[r['sha256'][:8] for r in results]}"
    )
    del pipe
    gc.collect()


def do_compare(args: argparse.Namespace) -> None:
    d = Path(args.dir)
    runs: dict[str, dict] = {}
    for jf in sorted(d.glob("run_*.json")):
        data = json.loads(jf.read_text(encoding="utf-8"))
        runs[data["label"]] = data
    if not runs:
        print("no run_*.json found")
        return

    labels = list(runs.keys())
    n_prompts = len(next(iter(runs.values()))["prompts"])

    print("=== CACHE_DIR PROBE — COMPARISON ===")
    print(f"ov={next(iter(runs.values()))['openvino']}  "
          f"genai={next(iter(runs.values()))['openvino_genai']}")
    print(f"labels: {labels}\n")

    print("LOAD TIMES (full draft+target pipeline construction):")
    for lab in labels:
        r = runs[lab]
        print(f"  {lab:6s} mode={r['mode']:5s} load={r['load_seconds']:8.2f}s "
              f"cache_bytes={r['cache_dir_bytes']:,}")
    print()

    print("PER-PROMPT OUTPUT SHA-256 (first 16 hex):")
    for i in range(n_prompts):
        p = runs[labels[0]]["prompts"][i]["prompt"]
        print(f"  prompt[{i}] {p[:55]!r}")
        for lab in labels:
            print(f"      {lab:6s} {runs[lab]['prompts'][i]['sha256'][:16]}")
    print()

    def all_match(a: str, b: str):
        ra, rb = runs.get(a), runs.get(b)
        if not ra or not rb:
            return None
        return all(
            ra["prompts"][i]["sha256"] == rb["prompts"][i]["sha256"]
            for i in range(n_prompts)
        )

    determinism = all_match("prod1", "prod2")
    cache_identity = all_match("prod1", "warm1")
    coldwarm = all_match("cold", "warm1")
    warm_stable = all_match("warm1", "warm2")

    prod_loads = [runs[l]["load_seconds"] for l in ("prod1", "prod2") if l in runs]
    warm_loads = [runs[l]["load_seconds"] for l in ("warm1", "warm2") if l in runs]
    cold_load = runs["cold"]["load_seconds"] if "cold" in runs else None
    prod_mean = sum(prod_loads) / len(prod_loads) if prod_loads else None
    warm_mean = sum(warm_loads) / len(warm_loads) if warm_loads else None

    print("VERDICT:")
    print(f"  run-to-run determinism (prod1==prod2): {determinism}")
    print(f"  cache identity        (prod1==warm1):  {cache_identity}")
    print(f"  cold==warm            (cold ==warm1):  {coldwarm}")
    print(f"  warm stability        (warm1==warm2):  {warm_stable}")
    if prod_mean and warm_mean:
        delta = prod_mean - warm_mean
        pct = 100 * delta / prod_mean
        print(f"  load: prod_mean={prod_mean:.2f}s  cold={cold_load:.2f}s  "
              f"warm_mean={warm_mean:.2f}s  delta={delta:.2f}s ({pct:.1f}% faster)")

    verdict = {
        "openvino": next(iter(runs.values()))["openvino"],
        "openvino_genai": next(iter(runs.values()))["openvino_genai"],
        "labels": labels,
        "determinism_prod1_prod2": determinism,
        "cache_identity_prod1_warm1": cache_identity,
        "coldwarm_cold_warm1": coldwarm,
        "warm_stable_warm1_warm2": warm_stable,
        "load_seconds_by_label": {l: runs[l]["load_seconds"] for l in labels},
        "load_prod_mean_s": prod_mean,
        "load_cold_s": cold_load,
        "load_warm_mean_s": warm_mean,
        "load_delta_prod_minus_warm_s": (prod_mean - warm_mean) if (prod_mean and warm_mean) else None,
    }
    (d / "_verdict.json").write_text(json.dumps(verdict, indent=2), encoding="utf-8")
    print(f"\nwrote {d / '_verdict.json'}")


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    rp = sub.add_parser("run")
    rp.add_argument("--mode", choices=["prod", "cache"], required=True)
    rp.add_argument("--cache-dir", default="", dest="cache_dir")
    rp.add_argument("--label", required=True)
    rp.add_argument("--out", required=True)
    cp = sub.add_parser("compare")
    cp.add_argument("--dir", required=True)
    args = ap.parse_args()
    if args.cmd == "run":
        do_run(args)
    else:
        do_compare(args)


if __name__ == "__main__":
    main()
