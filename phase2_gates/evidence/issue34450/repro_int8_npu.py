"""Subprocess-isolated NPU repro for INT8 weight-only Qwen3-0.6B.

Constructs LLMPipeline(ir, "NPU"), then attempts a 16-token generate().
Construct succeeds; the generate() call dies with native 0xC0000005.
"""
from __future__ import annotations
import argparse, sys, time, traceback
from pathlib import Path

def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--ir", required=True, type=Path)
    p.add_argument("--device", default="NPU", choices=["CPU", "GPU", "NPU"])
    p.add_argument("--prompt", default="The capital of France is")
    p.add_argument("--tokens", type=int, default=16)
    args = p.parse_args()

    import openvino_genai as ov_genai
    from openvino_genai import LLMPipeline

    print(f"READY device={args.device} ir={args.ir}", flush=True)
    t0 = time.monotonic()
    try:
        pipe = LLMPipeline(str(args.ir), args.device)
    except BaseException as exc:
        print(f"PYTHON_EXCEPTION:{type(exc).__name__}:{exc}".replace("\n", " | "),
              file=sys.stderr, flush=True)
        traceback.print_exc(file=sys.stderr)
        return 1
    print(f"CONSTRUCT_OK elapsed={time.monotonic()-t0:.2f}s", flush=True)

    t1 = time.monotonic()
    try:
        out = pipe.generate(args.prompt, max_new_tokens=args.tokens)
    except BaseException as exc:
        print(f"PYTHON_EXCEPTION:{type(exc).__name__}:{exc}".replace("\n", " | "),
              file=sys.stderr, flush=True)
        traceback.print_exc(file=sys.stderr)
        return 1
    print(f"GENERATE_OK tokens={args.tokens} elapsed={time.monotonic()-t1:.2f}s "
          f"output={str(out).replace(chr(10),' | ')!r}", flush=True)
    return 0

if __name__ == "__main__":
    sys.exit(main())
