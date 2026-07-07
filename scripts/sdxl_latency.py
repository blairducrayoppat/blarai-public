"""
SDXL latency + peak-RAM harness (Session-2 §3) — 3 styles on 2026.2.1.
======================================================================
Measures single-image generate latency + peak shared-RAM (In-Use = Total -
Available) for the three production SDXL styles on the Arc 140V via BlarAI's
own image_gen module (faithful production footprint): photoreal (SDXL-uncensored
INT8), illustration (SDXL-illustration INT8), cartoon (illustration + DD-vector
LoRA). 1024x1024, 20 steps, fixed seed. Runs on the runtime .venv (2026.2.1).

Usage (repo root, runtime venv, LOCALAPPDATA redirected, GPU clean):
  .venv/Scripts/python.exe scratchpad/sdxl_latency.py
"""

from __future__ import annotations

import json
import statistics
import sys
import threading
import time
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if not (_REPO_ROOT / "shared").exists():
    _REPO_ROOT = Path.cwd()
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import psutil  # noqa: E402
import openvino_genai as ov_genai  # noqa: E402
from shared.inference import image_gen  # noqa: E402
from shared.inference.image_gen import (  # noqa: E402
    ImageGenConfig, VARIANT_PHOTOREAL_SDXL, VARIANT_ILLUSTRATION, VARIANT_ILLUSTRATION_CARTOON,
)

_CARTOON_LORA = _REPO_ROOT / "models" / "sdxl-illustration" / "lora" / "DD-vector-v2.safetensors"
_CARTOON_LORA_SHA = "b4c8132f85ab7d75f5789eaf0054153a6011b505719f1253fb7d8837a498fe89"
STEPS = 20

STYLES = {
    "photoreal": dict(model_dir="models/sdxl-uncensored/openvino-int8-gpu",
                      variant=VARIANT_PHOTOREAL_SDXL, lora=None),
    "illustration": dict(model_dir="models/sdxl-illustration/openvino-int8-gpu",
                         variant=VARIANT_ILLUSTRATION, lora=None),
    "cartoon": dict(model_dir="models/sdxl-illustration/openvino-int8-gpu",
                    variant=VARIANT_ILLUSTRATION_CARTOON,
                    lora=(_CARTOON_LORA if _CARTOON_LORA.exists() else None)),
}
PROMPT = "a serene mountain lake at sunrise, detailed, high quality"


class MemSampler(threading.Thread):
    def __init__(self, interval=0.1):
        super().__init__(daemon=True)
        self.interval = interval; self._ev = threading.Event()
        self.total = psutil.virtual_memory().total
        self.min_avail = psutil.virtual_memory().available

    def run(self):
        while not self._ev.is_set():
            a = psutil.virtual_memory().available
            if a < self.min_avail:
                self.min_avail = a
            time.sleep(self.interval)

    def stop(self):
        self._ev.set(); self.join(timeout=2)

    @property
    def peak_used_gb(self):
        return (self.total - self.min_avail) / 1e9


def main() -> int:
    ov_ver = ov_genai.__version__
    print(f"== SDXL latency == ov={ov_ver} steps={STEPS} 1024x1024 seed=42")
    results = []
    for name, s in STYLES.items():
        lora = s["lora"]
        print(f"\n=== {name} (variant={s['variant']}, lora={'yes' if lora else 'no'}) ===")
        image_gen.configure(ImageGenConfig(
            enabled=True, model_dir=_REPO_ROOT / s["model_dir"], weight_manifest=None,
            require_signed_manifest=False, model_variant=s["variant"], steps=STEPS,
            hires_enabled=False, lora_adapter_path=lora,
            lora_adapter_sha256=(_CARTOON_LORA_SHA if lora is not None else ""),
        ))
        if not image_gen.is_available():
            print(f"   [skip] {name}: image_gen not available")
            results.append({"style": name, "available": False})
            continue
        t0 = time.perf_counter()
        warm = image_gen.generate_text2image(PROMPT, seed=42)  # load + 1st gen
        load_plus_first = time.perf_counter() - t0
        print(f"   load+first-gen: {load_plus_first:.1f}s (bytes={len(warm) if warm else 0})")
        lat, peaks, sizes = [], [], []
        for r in range(2):
            ms = MemSampler(); ms.start()
            t = time.perf_counter()
            png = image_gen.generate_text2image(PROMPT, seed=42 + r)
            dt = time.perf_counter() - t
            ms.stop()
            lat.append(dt); peaks.append(ms.peak_used_gb); sizes.append(len(png) if png else 0)
            print(f"   gen r{r}: {dt:.2f}s peak_used={ms.peak_used_gb:.2f}GB png={sizes[-1]}B")
        results.append({
            "style": name, "available": True, "variant": s["variant"], "lora": bool(lora),
            "load_plus_first_s": round(load_plus_first, 2),
            "gen_latency_s_median": round(statistics.median(lat), 2),
            "peak_used_gb_median": round(statistics.median(peaks), 2),
            "png_bytes_median": int(statistics.median(sizes)), "n": len(lat),
        })
        image_gen.unload()
        time.sleep(2)

    print("\n=== SUMMARY ===")
    for r in results:
        if r.get("available"):
            print(f"   {r['style']:13}: gen {r['gen_latency_s_median']}s | peak {r['peak_used_gb_median']}GB | load+1st {r['load_plus_first_s']}s")

    out = {"harness": "sdxl_latency", "openvino_genai_version": ov_ver,
           "openvino_version": __import__("openvino").__version__,
           "config": {"steps": STEPS, "dims": "1024x1024", "prompt": PROMPT}, "results": results}
    ts = time.strftime("%Y-%m-%d_%H-%M-%S")
    outpath = _REPO_ROOT / "docs" / "performance" / f"sdxl_latency_{ts}.json"
    outpath.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(f"\n[SAVE] {outpath}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
