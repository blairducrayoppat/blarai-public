"""
Voice Model RAM-Delta Benchmark — BlarAI Whisper STT + Kokoro TTS (#660)
=========================================================================
Measures the system-RAM footprint of LOADING vs. UNLOADING each voice half so
the #660 "on-demand load on enable / unload on disable to reclaim RAM" toggles
can be proven to actually return memory on the real hardware — this is the
genuine gate the in-process unload was built against (the headless tests prove
the Python object is dropped; ONLY a real-model run on the Arc 140V proves the
RAM comes back).

It drives the PRODUCTION engine surface — ``VoiceEngine.with_paths`` then the
runtime ``load_stt`` / ``unload_stt`` / ``load_tts`` / ``unload_tts`` methods
(``services/voice/src/engine.py``) — so the numbers reflect exactly what the
WinUI toggles trigger, not a synthetic harness.

What IS measured
  - Process RSS (resident set) + system available RAM at each phase boundary.
  - The load delta (baseline -> loaded) and the reclaim delta (loaded ->
    unloaded) for STT and TTS independently.

What is NOT measured (named explicitly, per the data-capture discipline)
  - GPU / iGPU device memory specifically: psutil reports SYSTEM RAM. On the
    Arc 140V (shared system RAM, no discrete VRAM) the model's device memory IS
    drawn from the same 32 GB pool, so the system-RAM delta is a meaningful
    proxy — but it is NOT a driver-level GPU-allocation readout. For a true GPU
    breakdown, capture Task Manager's "GPU memory" or `xpu-smi`/`intel_gpu_top`
    alongside a run (note it in the PERFORMANCE_LOG entry).
  - Co-residency cost with the resident Qwen3-14B + on-demand VLM: this harness
    measures voice in ISOLATION (no model loaded). The interesting
    production number — voice load delta WHILE the 14B is resident — must be
    measured by loading the 14B first (run the launcher / the GPU inference
    benchmark) and then running this harness in the same process tree, OR by
    reading total system In-Use before/after a toggle in the live app.
  - Steady-state inference cost (a transcribe / synthesize call): footprint
    here is the LOADED-IDLE model, not peak during inference.

Usage (from repo root with the BlarAI venv; models must be present under
models/whisper-small/openvino + models/kokoro/):
  .venv\\Scripts\\python.exe scripts\\benchmark_voice_ram.py
  .venv\\Scripts\\python.exe scripts\\benchmark_voice_ram.py --halves stt
  .venv\\Scripts\\python.exe scripts\\benchmark_voice_ram.py --device CPU
  .venv\\Scripts\\python.exe scripts\\benchmark_voice_ram.py --settle-s 3

Output:
  - A community-grade JSON under docs/performance/voice_ram_<timestamp>.json
  - A human summary to stdout (paste the headline deltas into PERFORMANCE_LOG.md)

This is a HEAVY real-model run (loads Whisper + Kokoro onto the GPU). It is the
Lead-Architect on-hardware live-verify for #660 — NOT run by the build agent.
"""

from __future__ import annotations

import argparse
import gc
import json
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

try:
    import psutil  # type: ignore[import-untyped]
except ImportError:  # pragma: no cover - harness-only dependency
    print("ERROR: psutil is required (pip install psutil).", file=sys.stderr)
    raise

try:
    import openvino as ov  # type: ignore[import-untyped]
    _OV_VERSION = ov.__version__
except ImportError:
    _OV_VERSION = "unavailable"

from services.voice.src.engine import VoiceEngine  # noqa: E402

_MB = 1024 * 1024


@dataclass
class MemSample:
    """A single memory reading (MB)."""

    label: str
    process_rss_mb: float
    system_available_mb: float
    system_used_mb: float


@dataclass
class HalfResult:
    """Load + reclaim measurement for one voice half."""

    half: str                       # "stt" | "tts"
    available_after_load: bool
    samples: list[MemSample] = field(default_factory=list)
    load_delta_rss_mb: float = 0.0          # baseline -> loaded (RSS grew)
    reclaim_delta_rss_mb: float = 0.0       # loaded -> unloaded (RSS shrank)
    reclaim_fraction: float = 0.0           # reclaimed / loaded (1.0 = full)


def _sample(label: str, proc: "psutil.Process") -> MemSample:
    vm = psutil.virtual_memory()
    return MemSample(
        label=label,
        process_rss_mb=round(proc.memory_info().rss / _MB, 1),
        system_available_mb=round(vm.available / _MB, 1),
        system_used_mb=round(vm.used / _MB, 1),
    )


def _settle(seconds: float) -> None:
    """Give the allocator/driver a moment to return memory after an unload."""
    gc.collect()
    time.sleep(seconds)
    gc.collect()


def _measure_half(
    engine: VoiceEngine, half: str, proc: "psutil.Process", settle_s: float
) -> HalfResult:
    load = engine.load_stt if half == "stt" else engine.load_tts
    unload = engine.unload_stt if half == "stt" else engine.unload_tts
    avail = (lambda: engine.stt_available) if half == "stt" else (lambda: engine.tts_available)

    res = HalfResult(half=half, available_after_load=False)
    res.samples.append(_sample(f"{half}:baseline", proc))

    t0 = time.perf_counter()
    load()
    load_s = time.perf_counter() - t0
    _settle(settle_s)
    res.available_after_load = bool(avail())
    res.samples.append(_sample(f"{half}:loaded", proc))

    unload()
    _settle(settle_s)
    res.samples.append(_sample(f"{half}:unloaded", proc))

    base, loaded, unloaded = res.samples
    res.load_delta_rss_mb = round(loaded.process_rss_mb - base.process_rss_mb, 1)
    res.reclaim_delta_rss_mb = round(loaded.process_rss_mb - unloaded.process_rss_mb, 1)
    if res.load_delta_rss_mb > 0:
        res.reclaim_fraction = round(res.reclaim_delta_rss_mb / res.load_delta_rss_mb, 3)

    print(
        f"  [{half}] load={res.load_delta_rss_mb:+.1f} MB (in {load_s:.1f}s, "
        f"available={res.available_after_load}) | "
        f"reclaim={res.reclaim_delta_rss_mb:+.1f} MB "
        f"({res.reclaim_fraction * 100:.0f}% of load returned)"
    )
    return res


def main() -> int:
    ap = argparse.ArgumentParser(description="Voice model RAM-delta benchmark (#660)")
    ap.add_argument("--halves", choices=["both", "stt", "tts"], default="both")
    ap.add_argument("--device", default="GPU", help="Inference device for STT (default GPU)")
    ap.add_argument("--settle-s", type=float, default=2.0,
                    help="Seconds to wait after load/unload for the allocator to settle")
    ap.add_argument("--models-root", default=None,
                    help="Override the repo-root models/ location")
    args = ap.parse_args()

    models_root = Path(args.models_root) if args.models_root else _REPO_ROOT / "models"
    whisper_dir = models_root / "whisper-small" / "openvino"
    kokoro_model = models_root / "kokoro" / "kokoro-v1.0.onnx"
    kokoro_voices = models_root / "kokoro" / "voices-v1.0.bin"

    engine = VoiceEngine.with_paths(
        whisper_dir=str(whisper_dir) if whisper_dir.is_dir() else None,
        kokoro_model=str(kokoro_model) if kokoro_model.is_file() else None,
        kokoro_voices=str(kokoro_voices) if kokoro_voices.is_file() else None,
        device=args.device,
    )

    proc = psutil.Process()
    print("BlarAI Voice RAM-Delta Benchmark (#660)")
    print(f"  device={args.device}  settle={args.settle_s}s  openvino={_OV_VERSION}")
    print(f"  whisper_dir={'present' if whisper_dir.is_dir() else 'MISSING'}  "
          f"kokoro={'present' if kokoro_model.is_file() else 'MISSING'}")
    print()

    halves = ["stt", "tts"] if args.halves == "both" else [args.halves]
    results = [_measure_half(engine, h, proc, args.settle_s) for h in halves]

    payload = {
        "benchmark": "voice_ram_delta",
        "ticket": "#660",
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "device": args.device,
        "settle_s": args.settle_s,
        "openvino_version": _OV_VERSION,
        "python_version": sys.version.split()[0],
        "cpu": _cpu_name(),
        "measured": "process RSS + system RAM (psutil); NOT a driver-level GPU readout",
        "not_measured": [
            "GPU device-memory breakdown (Arc 140V shares system RAM)",
            "co-residency cost with the resident Qwen3-14B + on-demand VLM",
            "peak footprint during a transcribe/synthesize call",
        ],
        "results": [asdict(r) for r in results],
    }

    out_dir = _REPO_ROOT / "docs" / "performance"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"voice_ram_{datetime.now():%Y-%m-%d_%H-%M-%S}.json"
    out.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    print()
    print("Headline (paste into PERFORMANCE_LOG.md):")
    for r in results:
        verdict = (
            "RECLAIM CONFIRMED" if r.reclaim_fraction >= 0.5
            else "WEAK/NO RECLAIM — investigate (the #660 gate fails here)"
        )
        print(f"  {r.half.upper()}: +{r.load_delta_rss_mb:.0f} MB on load, "
              f"-{r.reclaim_delta_rss_mb:.0f} MB on unload "
              f"({r.reclaim_fraction * 100:.0f}% returned) -> {verdict}")
    print(f"\nJSON: {out}")
    return 0


def _cpu_name() -> str:
    try:
        import platform
        return platform.processor() or platform.machine()
    except Exception:  # noqa: BLE001
        return "unknown"


if __name__ == "__main__":
    raise SystemExit(main())
