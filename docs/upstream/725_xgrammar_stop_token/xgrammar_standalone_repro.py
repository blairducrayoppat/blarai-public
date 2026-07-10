"""Standalone repro — xgrammar stop-token crash under speculative decoding.

OpenVINO GenAI only (no app code). Reproduces:

    grammar_matcher.cc:627: Check failed: (!IsStopTokenAccepted()) is false:
    GrammarMatcher has terminated after accepting the stop token, but is
    trying to find the next token mask

Setup: LLMPipeline on GPU with a draft model (continuous-batching
SpeculativeDecodingImpl path) + a TRIGGERED StructuralTagsConfig grammar
(trigger "<tool_call>"). Prompts are ordinary conversational turns; none of
them needs to emit a tool call — a companion warning (grammar_matcher.cc:493)
shows the terminated matcher being fed token id 151658 ("</tool_call>",
never present in the sampled output), consistent with the draft model's
speculative proposals past the accepted stop token being validated against
the already-terminated matcher.

Observed rate: ~3% of generations (3/95) with the draft model attached;
0/57 with the identical config minus the draft model. Nondeterministic
across identical greedy runs (different prompt crashes each time).

Usage:
    python xgrammar_standalone_repro.py --model <qwen3-14b-int4-ov-dir> \
        --draft <qwen3-0.6b-int8-ov-dir> --prompts repro_prompts.json \
        [--passes 5] [--no-draft]
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import openvino_genai as ov_genai


def build_pipeline(model: str, draft: str | None) -> ov_genai.LLMPipeline:
    scheduler = ov_genai.SchedulerConfig()
    scheduler.cache_size = 3
    scheduler.enable_prefix_caching = True
    kwargs: dict[str, object] = {
        "scheduler_config": scheduler,
        "PERFORMANCE_HINT": "LATENCY",
        "INFERENCE_PRECISION_HINT": "f16",
        "GPU_ENABLE_SDPA_OPTIMIZATION": "ON",
        "CACHE_DIR": "",
    }
    if draft:
        kwargs["draft_model"] = ov_genai.draft_model(
            draft,
            "GPU",
            PERFORMANCE_HINT="LATENCY",
            INFERENCE_PRECISION_HINT="f16",
            GPU_ENABLE_SDPA_OPTIMIZATION="ON",
            CACHE_DIR="",
        )
    return ov_genai.LLMPipeline(model, "GPU", **kwargs)


def build_config(schema: dict, use_draft: bool) -> ov_genai.GenerationConfig:
    cfg = ov_genai.GenerationConfig()
    cfg.max_new_tokens = 512
    cfg.do_sample = False
    if use_draft:
        cfg.num_assistant_tokens = 3
    tags = ov_genai.StructuralTagsConfig(
        structural_tags=[
            ov_genai.StructuralTagItem(
                begin="<tool_call>",
                schema=json.dumps(schema),
                end="</tool_call>",
            )
        ],
        triggers=["<tool_call>"],
    )
    structured = ov_genai.StructuredOutputConfig()
    structured.structural_tags_config = tags
    cfg.structured_output_config = structured
    return cfg


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("--draft", default=None)
    ap.add_argument("--no-draft", action="store_true")
    ap.add_argument("--prompts", type=Path, required=True)
    ap.add_argument("--passes", type=int, default=5)
    args = ap.parse_args()

    data = json.loads(args.prompts.read_text(encoding="utf-8"))
    prompts = data["prompts"]
    use_draft = bool(args.draft) and not args.no_draft

    t0 = time.time()
    pipe = build_pipeline(args.model, args.draft if use_draft else None)
    print(f"[repro] loaded in {time.time()-t0:.1f}s draft={'ON' if use_draft else 'OFF'}", flush=True)
    cfg = build_config(data["schema"], use_draft)

    gens = crashes = 0
    for p in range(1, args.passes + 1):
        for item in prompts:
            gens += 1
            try:
                pipe.generate(item["prompt"], cfg)
            except Exception as exc:  # noqa: BLE001
                msg = str(exc)
                if "GrammarMatcher" in msg or "IsStopTokenAccepted" in msg:
                    crashes += 1
                    print(f"[repro] CRASH #{crashes} gen={gens} case={item['id']}\n{msg[:300]}", flush=True)
                else:
                    print(f"[repro] other error gen={gens}: {msg[:200]}", flush=True)
        print(f"[repro] pass {p}: {gens} gens, {crashes} crashes", flush=True)
    print(f"[repro] DONE gens={gens} crashes={crashes}", flush=True)
    return 0 if crashes else 1


if __name__ == "__main__":
    sys.exit(main())
