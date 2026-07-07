"""Generic compile harness for openvinotoolkit/openvino#34450 expansion (cells D-J).

Modes:
  direct        ov.Core().compile_model(<ir>/openvino_model.xml, <device>, ov_config)
                -> bypasses NPUW (raw NPU plugin / CPU plugin / GPU plugin).
  llmpipeline   openvino_genai.LLMPipeline(<ir>, <device>)
                -> uses NPUW on NPU; no speculative decoding wrapper.
  spec_decode   openvino_genai.LLMPipeline(<target>, "GPU",
                    draft_model=draft_model(<ir>, <device>),
                    scheduler_config=...)
                -> full heterogeneous speculative decoding (matches issue repro).

Subprocess-isolated; survives SIGABRT in parent.
Exit codes: 0 ok / 1 python exception / native-abort code on uncatchable abort.
"""

from __future__ import annotations

import argparse
import sys
import time
import traceback
from pathlib import Path


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--ir", required=True, type=Path,
                   help="Path to draft model directory containing openvino_model.xml")
    p.add_argument("--device", required=True, choices=["CPU", "GPU", "NPU"])
    p.add_argument("--mode", required=True,
                   choices=["direct", "llmpipeline", "spec_decode"])
    p.add_argument("--target", type=Path, default=None,
                   help="GPU target model directory (required for spec_decode mode)")
    p.add_argument("--ov-config", action="append", default=[],
                   help="Repeatable: KEY=VALUE pairs for compile config / pipeline kwargs")
    p.add_argument("--cache-size-gb", type=int, default=3)
    p.add_argument("--generate-tokens", type=int, default=0,
                   help="For llmpipeline mode: after construct, call generate() with this max_new_tokens. "
                        "0 disables (construct-only).")
    p.add_argument("--prompt", type=str, default="The capital of France is",
                   help="Prompt for --generate-tokens.")
    args = p.parse_args()

    if not args.ir.is_dir():
        print(f"PYTHON_EXCEPTION:FileNotFoundError:ir not a directory: {args.ir}",
              file=sys.stderr, flush=True)
        return 1
    if args.mode == "spec_decode" and (args.target is None or not args.target.is_dir()):
        print("PYTHON_EXCEPTION:ValueError:--target required for spec_decode mode",
              file=sys.stderr, flush=True)
        return 1

    ov_config: dict[str, object] = {}
    for kv in args.ov_config:
        if "=" not in kv:
            print(f"PYTHON_EXCEPTION:ValueError:bad --ov-config (need KEY=VALUE): {kv}",
                  file=sys.stderr, flush=True)
            return 1
        k, v = kv.split("=", 1)
        v = v.strip()
        # Coerce numeric values so OpenVINO/NPUW int-typed properties
        # (e.g. MAX_PROMPT_LEN, MIN_RESPONSE_LEN) get int instead of str.
        if v.lstrip("-").isdigit():
            ov_config[k.strip()] = int(v)
        else:
            ov_config[k.strip()] = v

    print(f"READY mode={args.mode} device={args.device} ir={args.ir}", flush=True)
    if ov_config:
        print(f"ov_config={ov_config}", flush=True)
    if args.mode == "spec_decode":
        print(f"target={args.target}", flush=True)

    t0 = time.monotonic()
    exec_devices: str | None = None
    try:
        if args.mode == "direct":
            import openvino as ov
            core = ov.Core()
            xml = args.ir / "openvino_model.xml"
            _cm = core.compile_model(str(xml), args.device, ov_config)
            try:
                exec_devices = str(_cm.get_property("EXECUTION_DEVICES"))
            except Exception as ed_exc:  # noqa: BLE001
                exec_devices = f"<unavailable: {type(ed_exc).__name__}: {ed_exc}>"
        elif args.mode == "llmpipeline":
            import openvino_genai as ov_genai  # noqa: F401
            from openvino_genai import LLMPipeline
            # ov_config passed positionally as third arg to LLMPipeline if non-empty.
            if ov_config:
                _pipe = LLMPipeline(str(args.ir), args.device, ov_config)
            else:
                _pipe = LLMPipeline(str(args.ir), args.device)
            # LLMPipeline does not expose EXECUTION_DEVICES directly. Best-effort
            # introspection: walk attributes for an underlying CompiledModel.
            try:
                for attr in ("get_compiled_model", "compiled_model", "_compiled_model"):
                    obj = getattr(_pipe, attr, None)
                    if obj is None:
                        continue
                    cm = obj() if callable(obj) else obj
                    exec_devices = str(cm.get_property("EXECUTION_DEVICES"))
                    break
                else:
                    exec_devices = "<llmpipeline: no compiled-model accessor exposed>"
            except Exception as ed_exc:  # noqa: BLE001
                exec_devices = f"<unavailable: {type(ed_exc).__name__}: {ed_exc}>"
            # End-to-end decode-path exercise: surfaces failures that only manifest
            # when the generate (decode) submodel actually runs.
            if args.generate_tokens > 0:
                t_gen = time.monotonic()
                gen_out = _pipe.generate(args.prompt, max_new_tokens=args.generate_tokens)
                gen_elapsed = time.monotonic() - t_gen
                # gen_out may be a str or a DecodedResults; coerce safely.
                gen_str = str(gen_out).replace("\n", " | ")
                print(f"GENERATE_OK tokens={args.generate_tokens} "
                      f"elapsed={gen_elapsed:.2f}s output={gen_str!r}", flush=True)
        elif args.mode == "spec_decode":
            import openvino_genai as ov_genai
            from openvino_genai import LLMPipeline, SchedulerConfig
            sched = SchedulerConfig()
            sched.cache_size = args.cache_size_gb
            _pipe = LLMPipeline(
                str(args.target), "GPU",
                draft_model=ov_genai.draft_model(str(args.ir), args.device),
                scheduler_config=sched,
            )
        else:
            raise RuntimeError(f"unreachable mode: {args.mode}")
    except BaseException as exc:  # noqa: BLE001
        elapsed = time.monotonic() - t0
        cls = type(exc).__name__
        msg = str(exc).replace("\n", " | ")
        print(f"PYTHON_EXCEPTION:{cls}:{msg}", file=sys.stderr, flush=True)
        traceback.print_exc(file=sys.stderr)
        print(f"FAILED elapsed={elapsed:.2f}s", flush=True)
        return 1

    elapsed = time.monotonic() - t0
    if exec_devices is not None:
        print(f"EXECUTION_DEVICES={exec_devices}", flush=True)
    print(f"OK elapsed={elapsed:.2f}s", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
