"""Subprocess-isolated repro harness for openvinotoolkit/openvino#34450.

Constructs an OpenVINO GenAI heterogeneous speculative-decoding
``LLMPipeline`` with a GPU target and an NPU draft. The VPUX compiler may
abort with ``LLVM ERROR`` (SIGABRT) during pipeline construction; this
process is therefore designed to be invoked as a child via ``subprocess``
so that the parent harness survives an uncatchable abort.

The script writes ``READY`` to stdout once OpenVINO is imported, then
attempts pipeline construction, then writes one of ``OK``,
``PYTHON_EXCEPTION:<class>:<msg>``, or never returns (SIGABRT). The parent
captures the child's exit code and full stderr to reconstruct the failure
mode regardless of which path was taken.

Usage::

    python repro_npu_draft.py --target <gpu_model_dir> --draft <npu_model_dir>

Exits 0 on successful pipeline construction, 1 on Python-level exception,
and a platform-dependent abort code (typically 3221226505 / 0xC0000409 on
Windows for SIGABRT) on VPUX compiler abort.
"""

from __future__ import annotations

import argparse
import sys
import traceback
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", required=True, type=Path,
                        help="Path to GPU target model directory.")
    parser.add_argument("--draft", required=True, type=Path,
                        help="Path to NPU draft model directory.")
    parser.add_argument("--cache-size-gb", type=int, default=3,
                        help="SchedulerConfig.cache_size in GB (default: 3).")
    args = parser.parse_args()

    if not args.target.is_dir():
        print(f"PYTHON_EXCEPTION:FileNotFoundError:target not a directory: {args.target}",
              file=sys.stderr, flush=True)
        return 1
    if not args.draft.is_dir():
        print(f"PYTHON_EXCEPTION:FileNotFoundError:draft not a directory: {args.draft}",
              file=sys.stderr, flush=True)
        return 1

    import openvino_genai as ov_genai
    from openvino_genai import LLMPipeline, SchedulerConfig

    print("READY", flush=True)
    print(f"target={args.target}", flush=True)
    print(f"draft={args.draft}", flush=True)

    scheduler = SchedulerConfig()
    scheduler.cache_size = args.cache_size_gb

    try:
        _pipeline = LLMPipeline(
            str(args.target),
            "GPU",
            draft_model=ov_genai.draft_model(str(args.draft), "NPU"),
            scheduler_config=scheduler,
        )
    except BaseException as exc:  # noqa: BLE001 - we want everything Python can see
        cls = type(exc).__name__
        msg = str(exc).replace("\n", " | ")
        print(f"PYTHON_EXCEPTION:{cls}:{msg}", file=sys.stderr, flush=True)
        traceback.print_exc(file=sys.stderr)
        return 1

    print("OK", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
