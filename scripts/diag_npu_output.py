"""
NPU output diagnostic — isolate why Qwen3-1.7B generates empty strings on NPU.

Tests:
  1. Simple "Hello" prompt (no chat template)
  2. Chat-format prompt without <think> tags
  3. Chat-format prompt with <think> tags (current smoke test format)
  4. Same tests with PREFER_PLUGIN compiler
  5. Check raw output bytes

Usage:
  .venv\Scripts\python.exe scripts\diag_npu_output.py --device NPU --model-dir models/qwen3-1.7b/openvino-int4-npu-v2
"""
from __future__ import annotations
import argparse, sys, time
from pathlib import Path

import openvino as ov
import openvino_genai as ov_genai


def run_test(pipe, prompt: str, label: str, max_tokens: int = 32,
             use_stop_strings: bool = True) -> None:
    """Run a single generation and print raw diagnostics."""
    gc = ov_genai.GenerationConfig()
    gc.max_new_tokens = max_tokens
    gc.do_sample = False
    if use_stop_strings:
        try:
            gc.stop_strings = {"<|im_end|>"}
        except Exception:
            pass

    print(f"\n{'─'*60}")
    print(f"  TEST: {label}")
    print(f"  Prompt ({len(prompt)} chars): {prompt[:120]}{'...' if len(prompt)>120 else ''}")
    print(f"  max_new_tokens={max_tokens}, stop_strings={'YES' if use_stop_strings else 'NO'}")
    print(f"{'─'*60}")

    t0 = time.perf_counter()
    try:
        output = pipe.generate(prompt, gc)
    except Exception as exc:
        print(f"  ERROR: {exc}")
        return
    elapsed = (time.perf_counter() - t0) * 1000

    print(f"  Raw output type : {type(output).__name__}")
    print(f"  Raw output repr : {output!r}")
    print(f"  Raw output bytes: {output.encode('utf-8', errors='replace')!r}")
    print(f"  Output length   : {len(output)} chars")
    print(f"  Latency         : {elapsed:.0f} ms")

    if not output.strip():
        print(f"  *** EMPTY OUTPUT — model generated nothing ***")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-dir", required=True)
    parser.add_argument("--device", default="NPU")
    args = parser.parse_args()

    model_dir = Path(args.model_dir).resolve()
    device = args.device

    print(f"OpenVINO: {ov.__version__}")
    print(f"GenAI:    {ov_genai.__version__}")
    print(f"Device:   {device}")
    print(f"Model:    {model_dir}")

    # ── Pipeline creation (default config) ──
    print(f"\n[1] Creating pipeline with default config...")
    cfg: dict[str, str] = {}
    if device == "NPU":
        cfg["CACHE_DIR"] = str(model_dir / ".npucache")

    t0 = time.perf_counter()
    pipe = ov_genai.LLMPipeline(str(model_dir), device, **cfg)
    print(f"    Pipeline created in {(time.perf_counter()-t0)*1000:.0f} ms")

    # ── Test 1: Raw text, no template ──
    run_test(pipe, "Hello!", "Raw 'Hello!' (no chat template)",
             max_tokens=32, use_stop_strings=False)

    # ── Test 2: Chat format WITHOUT <think> tags ──
    prompt_no_think = (
        "<|im_start|>system\nYou are a helpful assistant.<|im_end|>\n"
        "<|im_start|>user\nWhat is 2+2?<|im_end|>\n"
        "<|im_start|>assistant\n"
    )
    run_test(pipe, prompt_no_think, "Chat format, NO think tags, WITH stop_strings",
             max_tokens=32, use_stop_strings=True)

    # ── Test 3: Same but WITHOUT stop_strings ──
    run_test(pipe, prompt_no_think, "Chat format, NO think tags, NO stop_strings",
             max_tokens=32, use_stop_strings=False)

    # ── Test 4: Chat format WITH <think> tags ──
    prompt_think = (
        "<|im_start|>system\nYou are a helpful assistant.<|im_end|>\n"
        "<|im_start|>user\nWhat is 2+2?<|im_end|>\n"
        "<|im_start|>assistant\n<think>\n\n</think>\n"
    )
    run_test(pipe, prompt_think, "Chat format, WITH think tags, WITH stop_strings",
             max_tokens=32, use_stop_strings=True)

    # ── Test 5: Larger token budget ──
    run_test(pipe, prompt_no_think, "Chat format, NO think, max_tokens=128",
             max_tokens=128, use_stop_strings=False)

    # ── Test 6: Minimal prompt ──
    run_test(pipe, "1+1=", "Minimal '1+1=' (no template)",
             max_tokens=16, use_stop_strings=False)

    print(f"\n{'='*60}")
    print(f"  Diagnostic complete. Review raw outputs above.")
    print(f"{'='*60}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
