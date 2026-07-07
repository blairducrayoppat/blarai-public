"""
Whisper STT Device Benchmark — whisper-small on GPU vs NPU (#720)
==================================================================
Measures the OpenVINO GenAI ``WhisperPipeline`` (the exact production STT
surface — ``services/voice/src/engine.py`` ``_load_whisper``) on the Arc 140V
GPU (today's device) and the Intel AI Boost NPU, on real speech synthesized
locally by the production Kokoro TTS model (no network, no external audio).

What IS measured
  - Pipeline load/compile wall time per device (cold in-process).
  - Warm transcribe latency over N runs for a ~9 s spoken utterance.
  - Transcript fidelity per device (the decoded text is recorded verbatim in
    the JSON so accuracy regressions are visible, not just speed).
  - Process RSS delta across the load (system-RAM proxy; Lunar Lake iGPU/NPU
    share system LPDDR5X, so this covers device memory too).

What is NOT measured (named explicitly, per the data-capture discipline)
  - Co-resident Qwen3-14B contention (runs in isolation).
  - Word-error-rate over a real corpus: fidelity here is one synthesized
    utterance, a smoke-grade accuracy signal only.
  - Streaming/chunked transcription; microphone capture path.

Usage (repo root, BlarAI venv; models under models/whisper-small/openvino +
models/kokoro/ — pass --models-root to borrow the main checkout's models):
  .venv\\Scripts\\python.exe scripts\\benchmark_whisper_device.py
  .venv\\Scripts\\python.exe scripts\\benchmark_whisper_device.py --devices GPU
  .venv\\Scripts\\python.exe scripts\\benchmark_whisper_device.py --models-root C:/Users/mrbla/blarai/models

Output:
  - Community-grade JSON under docs/performance/whisper_device_<ts>.json
  - A human summary to stdout.
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

_UTTERANCE = (
    "The quick brown fox jumps over the lazy dog. "
    "Please summarize the quarterly report and list the three main risks "
    "for the local inference project."
)


def _synthesize_16k(models_root: Path) -> "np.ndarray":
    """Synthesize the test utterance with the production Kokoro TTS (CPU).

    Returns float32 mono samples at 16 kHz (Whisper's expected rate),
    linearly resampled from Kokoro's native 24 kHz.
    """
    from kokoro_onnx import Kokoro  # noqa: PLC0415 — harness-only import

    kokoro = Kokoro(
        str(models_root / "kokoro" / "kokoro-v1.0.onnx"),
        str(models_root / "kokoro" / "voices-v1.0.bin"),
    )
    samples, rate = kokoro.create(_UTTERANCE, voice="af_heart", speed=1.0)
    samples = np.asarray(samples, dtype=np.float32)
    if rate != 16_000:
        duration = samples.shape[0] / rate
        target_n = int(duration * 16_000)
        x_old = np.linspace(0.0, duration, samples.shape[0], endpoint=False)
        x_new = np.linspace(0.0, duration, target_n, endpoint=False)
        samples = np.interp(x_new, x_old, samples).astype(np.float32)
    return samples


def benchmark_device(
    device: str, whisper_dir: Path, samples_16k: "np.ndarray",
    warmup: int, runs: int,
) -> dict[str, Any]:
    import openvino_genai as og  # noqa: PLC0415 — harness-only import

    proc = psutil.Process()
    gc.collect()
    rss_before = proc.memory_info().rss

    result: dict[str, Any] = {"device": device}
    t0 = time.perf_counter()
    try:
        pipe = og.WhisperPipeline(str(whisper_dir), device=device)
    except Exception as exc:  # noqa: BLE001 — record the failure, keep going
        result["load_ok"] = False
        result["error"] = f"{type(exc).__name__}: {str(exc)[:400]}"
        return result
    result["load_ok"] = True
    result["load_s"] = round(time.perf_counter() - t0, 2)
    result["load_rss_delta_mb"] = round(
        (proc.memory_info().rss - rss_before) / _MB, 1
    )

    try:
        for _ in range(warmup):
            out = pipe.generate(samples_16k)
        latencies: list[float] = []
        for _ in range(runs):
            t0 = time.perf_counter()
            out = pipe.generate(samples_16k)
            latencies.append((time.perf_counter() - t0) * 1_000.0)
        result["transcribe"] = {
            "n": runs,
            "mean_ms": round(statistics.fmean(latencies), 1),
            "median_ms": round(statistics.median(latencies), 1),
            "min_ms": round(min(latencies), 1),
            "max_ms": round(max(latencies), 1),
        }
        result["transcript"] = str(out)
    except Exception as exc:  # noqa: BLE001
        result["transcribe_error"] = f"{type(exc).__name__}: {str(exc)[:400]}"

    del pipe
    gc.collect()
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--devices", nargs="+", default=["GPU", "NPU"])
    parser.add_argument("--warmup", type=int, default=2)
    parser.add_argument("--runs", type=int, default=5)
    parser.add_argument(
        "--models-root", type=Path, default=_REPO_ROOT / "models",
        help="Directory holding whisper-small/openvino and kokoro/.",
    )
    args = parser.parse_args()

    whisper_dir = args.models_root / "whisper-small" / "openvino"
    if not whisper_dir.is_dir():
        print(f"ERROR: whisper model not found at {whisper_dir}", file=sys.stderr)
        return 2

    print("Synthesizing test utterance with Kokoro (CPU)...", flush=True)
    samples = _synthesize_16k(args.models_root)
    duration_s = round(samples.shape[0] / 16_000.0, 1)
    print(f"Utterance: {duration_s}s @16 kHz", flush=True)

    results = []
    for device in args.devices:
        print(f"--- benchmarking Whisper on {device} ---", flush=True)
        results.append(
            benchmark_device(device, whisper_dir, samples, args.warmup, args.runs)
        )

    try:
        import openvino as ov

        ov_version = ov.__version__
    except Exception:  # noqa: BLE001
        ov_version = "unavailable"

    payload = {
        "benchmark": "whisper_stt_device_720",
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "model": "whisper-small OpenVINO (models/whisper-small/openvino)",
        "surface": "openvino_genai.WhisperPipeline (production _load_whisper path)",
        "environment": {"openvino": ov_version, "python": sys.version.split()[0]},
        "utterance": {
            "text": _UTTERANCE,
            "duration_s": duration_s,
            "source": "Kokoro-82M local TTS (af_heart), 24k->16k linear resample",
        },
        "methodology": {"warmup_runs": args.warmup, "timed_runs": args.runs},
        "results": results,
        "not_measured": [
            "co-resident Qwen3-14B contention",
            "corpus-level word-error-rate (single-utterance fidelity only)",
            "streaming transcription / mic capture path",
        ],
    }
    out_dir = _REPO_ROOT / "docs" / "performance"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"whisper_device_{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}.json"
    out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    print(f"\nJSON written: {out_path}\n")
    for r in results:
        if not r.get("load_ok"):
            print(f"{r['device']}: LOAD FAILED — {r.get('error', '?')}")
            continue
        line = f"{r['device']}: load {r['load_s']}s rss+{r['load_rss_delta_mb']}MB"
        if "transcribe" in r:
            t = r["transcribe"]
            line += f"  transcribe mean {t['mean_ms']}ms median {t['median_ms']}ms (n={t['n']})"
        else:
            line += f"  transcribe FAILED — {r.get('transcribe_error', '?')}"
        print(line)
        if "transcript" in r:
            print(f"  transcript: {r['transcript'][:160]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
