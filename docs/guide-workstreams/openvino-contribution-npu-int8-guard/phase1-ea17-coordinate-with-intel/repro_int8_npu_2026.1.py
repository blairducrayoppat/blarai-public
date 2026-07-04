"""
Retest harness for openvino issue #35641 against OpenVINO 2026.1.0.
Subprocess-style direct invocation; the parent agent captures the exit code.
Usage:
    python repro_int8_npu_2026.1.py --ir <ir-dir> --device NPU --tokens 16
"""
import argparse, os, sys, time
import openvino_genai as ov_genai
import openvino as ov

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--ir", required=True)
    p.add_argument("--device", required=True)
    p.add_argument("--tokens", type=int, default=16)
    p.add_argument("--prompt", default="What is the capital of France?")
    args = p.parse_args()

    print(f"READY device={args.device} ir={args.ir}", flush=True)
    print(f"openvino={ov.__version__}", flush=True)
    print(f"openvino_genai={ov_genai.__version__}", flush=True)

    t0 = time.time()
    pipe = ov_genai.LLMPipeline(args.ir, args.device)
    construct_elapsed = time.time() - t0
    print(f"CONSTRUCT_OK elapsed={construct_elapsed:.2f}s", flush=True)

    t1 = time.time()
    cfg = ov_genai.GenerationConfig()
    cfg.max_new_tokens = args.tokens
    out = pipe.generate(args.prompt, cfg)
    gen_elapsed = time.time() - t1
    print(f"GENERATE_OK tokens={args.tokens} elapsed={gen_elapsed:.2f}s output={out!r}", flush=True)

if __name__ == "__main__":
    main()
