"""
Embedding Device Benchmark — bge-small-en-v1.5 on CPU / GPU / NPU (#720)
=========================================================================
Measures the shared BlarAI embedding workload (substrate memory, knowledge
bank, PGOV Stage-5 leakage — all ride ONE ``LeakageDetector`` session) across
the three inference devices reachable through the ``[embeddings].device``
knob, on the real Lunar Lake silicon:

  - CPU  — the ONNX Runtime CPUExecutionProvider path (pre-#720 production).
  - GPU  — OpenVINO dynamic-shape compile on the Arc 140V (Xe2 iGPU).
  - NPU  — OpenVINO static-window compile on the Intel AI Boost NPU
           (the plugin is static-shape only: texts are padded to a
           128/512-token window and inferred at batch size 1).

It drives the PRODUCTION surface — ``LeakageDetector(device=...)`` then
``_embed`` (the calibrated 128-token leakage window) and
``embed_documents(max_length=512)`` (the knowledge/substrate document window)
— so the numbers reflect exactly what the AO runs, not a synthetic harness.

What IS measured
  - Full ``load_model()`` wall time per device (tokenizer + compile; the NPU
    number includes BOTH static-window compiles).
  - Warm embedding latency, N timed runs after warmup, for:
      single short text @128, single long text @512,
      batch-8 @128, batch-32 @128, batch-8 @512.
  - Numerical parity: cosine similarity of each device's embeddings against
    the CPU (ONNX Runtime) reference — the PGOV Stage-5 thresholds were
    calibrated on the CPU numerics, so parity is a release criterion.
  - Process RSS delta across ``load_model()`` (psutil; system-RAM proxy).

What is NOT measured (named explicitly, per the data-capture discipline)
  - Co-resident Qwen3-14B contention: this harness runs in ISOLATION (no LLM
    loaded). The production question — embedding latency WHILE the 14B is
    generating on the GPU — is precisely where the NPU should shine and must
    be measured separately (a follow-up with the 14B resident).
  - The semantic router path (services/semantic_router — separate ORT session,
    CPU-targeted, not wired into the live turn path per Sprint-18 C3).
  - OpenVINO-on-CPU and the openvino-int8 IR variant (not reachable through
    the production knob; the knob is a device knob, not a precision knob).
  - Sustained/thermal behaviour: runs are seconds-scale bursts.

Usage (from repo root with the BlarAI venv; the gitignored model must be
present under models/bge-small-en-v1.5/onnx-fp16/):
  .venv\\Scripts\\python.exe scripts\\benchmark_embedding_device.py
  .venv\\Scripts\\python.exe scripts\\benchmark_embedding_device.py --devices CPU NPU
  .venv\\Scripts\\python.exe scripts\\benchmark_embedding_device.py --runs 30

Output:
  - Community-grade JSON under docs/performance/embedding_device_<ts>.json
  - A human summary table to stdout (paste into PERFORMANCE_LOG.md).
"""

from __future__ import annotations

import argparse
import gc
import json
import statistics
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

try:
    import psutil  # type: ignore[import-untyped]
except ImportError:  # pragma: no cover - harness-only dependency
    print("ERROR: psutil is required.", file=sys.stderr)
    raise

import numpy as np

_MB = 1024 * 1024

_SHORT_TEXT = "What did the quarterly report say about the memory ceiling?"
_LONG_TEXT = (
    "BlarAI is a personal, locally-run, security-first AI system designed "
    "for decades of use on Intel Lunar Lake hardware. It runs entirely on "
    "local silicon with zero external network dependency and hardware-rooted "
    "trust. The assistant orchestrator serves conversational generation on "
    "the Arc 140V GPU with speculative decoding, while the policy agent "
    "classifies content through the same shared Qwen3-14B pipeline. "
) * 12  # ~420 words — exercises the full 512-token document window.

_BATCH_SEED = [
    "The substrate stores every approved conversation turn as an embedding.",
    "Knowledge bank chunks are embedded at the 512-token document window.",
    "PGOV stage five compares generated text against retrieved chunks.",
    "The memory ceiling on this machine is 31.323 gigabytes effective.",
    "Speculative decoding roughly doubled generation throughput last month.",
    "The semantic router classifies intents with cosine similarity gates.",
    "Encrypted stores use a TPM-sealed data encryption key envelope.",
    "The launcher provisions the Hyper-V guest before the gateway starts.",
]


def _percentile(values: list[float], pct: float) -> float:
    ordered = sorted(values)
    k = (len(ordered) - 1) * pct / 100.0
    lower = int(k)
    upper = min(lower + 1, len(ordered) - 1)
    frac = k - lower
    return ordered[lower] * (1.0 - frac) + ordered[upper] * frac


def _stats(samples_ms: list[float]) -> dict[str, float]:
    return {
        "n": len(samples_ms),
        "mean_ms": round(statistics.fmean(samples_ms), 2),
        "median_ms": round(statistics.median(samples_ms), 2),
        "p95_ms": round(_percentile(samples_ms, 95.0), 2),
        "stdev_ms": round(statistics.stdev(samples_ms), 2) if len(samples_ms) > 1 else 0.0,
        "min_ms": round(min(samples_ms), 2),
        "max_ms": round(max(samples_ms), 2),
    }


def _time_case(fn: Any, warmup: int, runs: int) -> list[float]:
    for _ in range(warmup):
        fn()
    samples: list[float] = []
    for _ in range(runs):
        t0 = time.perf_counter()
        fn()
        samples.append((time.perf_counter() - t0) * 1_000.0)
    return samples


def _env_info() -> dict[str, Any]:
    info: dict[str, Any] = {
        "python": sys.version.split()[0],
        "os": f"Windows {sys.getwindowsversion().major}.{sys.getwindowsversion().build}",  # type: ignore[attr-defined]
    }
    try:
        import onnxruntime as ort

        info["onnxruntime"] = ort.__version__
    except Exception:  # noqa: BLE001
        info["onnxruntime"] = "unavailable"
    try:
        import openvino as ov

        info["openvino"] = ov.__version__
        core = ov.Core()
        info["devices"] = {}
        for dev in core.available_devices:
            entry: dict[str, str] = {}
            try:
                entry["name"] = str(core.get_property(dev, "FULL_DEVICE_NAME"))
            except Exception:  # noqa: BLE001
                pass
            for key in ("GPU_DRIVER_VERSION", "DRIVER_VERSION", "NPU_DRIVER_VERSION"):
                try:
                    entry["driver"] = str(core.get_property(dev, key))
                    break
                except Exception:  # noqa: BLE001
                    continue
            info["devices"][dev] = entry
    except Exception:  # noqa: BLE001
        info["openvino"] = "unavailable"
    return info


def benchmark_device(
    device: str, model_path: str, warmup: int, runs: int
) -> dict[str, Any]:
    """Benchmark one device through the production LeakageDetector surface."""
    from services.assistant_orchestrator.src.pgov import LeakageDetector

    proc = psutil.Process()
    gc.collect()
    rss_before = proc.memory_info().rss

    det = LeakageDetector(model_path=model_path, device=device)
    t0 = time.perf_counter()
    ok = det.load_model()
    load_s = time.perf_counter() - t0
    rss_after = proc.memory_info().rss

    result: dict[str, Any] = {
        "requested_device": device,
        "load_ok": ok,
        "backend": det.backend,
        "active_device": det.active_device,
        "load_s": round(load_s, 2),
        "load_rss_delta_mb": round((rss_after - rss_before) / _MB, 1),
    }
    if not ok:
        det.unload()
        return result

    batch8 = _BATCH_SEED
    batch32 = (_BATCH_SEED * 4)[:32]

    cases: dict[str, Any] = {
        "single_short_128": lambda: det._embed([_SHORT_TEXT]),
        "single_long_512": lambda: det.embed_documents([_LONG_TEXT], max_length=512),
        "batch8_128": lambda: det._embed(batch8),
        "batch32_128": lambda: det._embed(batch32),
        "batch8_512": lambda: det.embed_documents(batch8, max_length=512),
    }
    result["cases"] = {
        name: _stats(_time_case(fn, warmup, runs)) for name, fn in cases.items()
    }

    # Parity vectors (returned for cross-device comparison by the caller).
    result["_vectors_128"] = det._embed([_SHORT_TEXT] + batch8)
    result["_vectors_512"] = det.embed_documents([_LONG_TEXT], max_length=512)

    det.unload()
    gc.collect()
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--devices", nargs="+", default=["CPU", "GPU", "NPU"],
        help="Devices to benchmark (CPU = ONNX Runtime; GPU/NPU = OpenVINO).",
    )
    parser.add_argument("--warmup", type=int, default=3)
    parser.add_argument("--runs", type=int, default=20)
    parser.add_argument(
        "--model",
        default=str(_REPO_ROOT / "models" / "bge-small-en-v1.5" / "onnx-fp16" / "model.onnx"),
    )
    args = parser.parse_args()

    if not Path(args.model).is_file():
        print(f"ERROR: model not found at {args.model}", file=sys.stderr)
        return 2

    results: list[dict[str, Any]] = []
    for device in args.devices:
        print(f"--- benchmarking {device} ---", flush=True)
        results.append(benchmark_device(device, args.model, args.warmup, args.runs))

    # Cross-device parity vs the CPU (ONNX Runtime) reference numerics.
    ref = next((r for r in results if r.get("load_ok") and r["backend"] == "ort-cpu"), None)
    for r in results:
        if (
            r.get("load_ok")
            and ref is not None
            and r is not ref
            and "_vectors_128" in r
        ):
            v128, r128 = r["_vectors_128"], ref["_vectors_128"]
            v512, r512 = r["_vectors_512"], ref["_vectors_512"]
            r["parity_vs_cpu"] = {
                "min_cosine_128": round(float(np.min(np.sum(v128 * r128, axis=1))), 6),
                "min_cosine_512": round(float(np.min(np.sum(v512 * r512, axis=1))), 6),
            }
    for r in results:
        r.pop("_vectors_128", None)
        r.pop("_vectors_512", None)

    payload = {
        "benchmark": "embedding_device_offload_720",
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "model": "BAAI/bge-small-en-v1.5 ONNX fp16 (127.8 MB, 384-dim)",
        "surface": "services.assistant_orchestrator.src.pgov.LeakageDetector",
        "methodology": {
            "warmup_runs": args.warmup,
            "timed_runs": args.runs,
            "cases": {
                "single_short_128": "1 short sentence, 128-token leakage window",
                "single_long_512": "1 ~420-word text, 512-token document window",
                "batch8_128": "8 sentences, 128-token window",
                "batch32_128": "32 sentences, 128-token window",
                "batch8_512": "8 sentences, 512-token window",
            },
            "npu_note": (
                "NPU plugin is static-shape only: two static compiles "
                "(128 + 512 windows), inputs padded to the window, batch "
                "processed one text per infer request."
            ),
        },
        "environment": _env_info(),
        "results": results,
        "not_measured": [
            "co-resident Qwen3-14B contention (harness runs in isolation; the "
            "production win case — embedding while the 14B generates on the "
            "GPU — needs a separate resident-14B run)",
            "semantic router ORT session (separate consumer, CPU-targeted, "
            "not in the live turn path)",
            "openvino-int8 IR precision variant (knob is device-only)",
            "OpenVINO-on-CPU executor (not reachable via the production knob)",
            "sustained/thermal behaviour",
        ],
    }

    out_dir = _REPO_ROOT / "docs" / "performance"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"embedding_device_{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}.json"
    out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    print(f"\nJSON written: {out_path}\n")
    print(f"{'device':10} {'case':18} {'mean':>8} {'median':>8} {'p95':>8}")
    for r in results:
        label = f"{r['requested_device']}({r['active_device']})"
        if not r.get("load_ok"):
            print(f"{label:10} LOAD FAILED")
            continue
        print(f"{label:10} {'load':18} {r['load_s']*1000:>7.0f}ms  rss+{r['load_rss_delta_mb']}MB")
        for name, s in r["cases"].items():
            print(f"{label:10} {name:18} {s['mean_ms']:>7.2f} {s['median_ms']:>8.2f} {s['p95_ms']:>8.2f}")
        if "parity_vs_cpu" in r:
            p = r["parity_vs_cpu"]
            print(f"{label:10} parity_vs_cpu      cos128>={p['min_cosine_128']} cos512>={p['min_cosine_512']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
