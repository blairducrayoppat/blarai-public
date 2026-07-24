"""Does OpenVINO's compiled-blob cache remove the load spike? (#1005 lever 2)

Hypothesis under test: the ~22 GB transient measured on the 26B-A4B is GRAPH COMPILE, not
weights. If so, setting CACHE_DIR makes the spike a one-time cost and a cached reload should
peak far lower - which would turn "fits by 11 MB" into a usable operational envelope.

Run twice with the same cache_dir: first COLD (cache empty, must compile), then WARM.
Reports load time and peak for each separately.
"""
from __future__ import annotations

import ctypes
import gc
import json
import sys
import threading
import time
from pathlib import Path

import numpy as np
import openvino as ov
import openvino_genai as ov_genai
from PIL import Image


class _MemStatus(ctypes.Structure):
    _fields_ = [
        ("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
        ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
        ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
        ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
        ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
    ]


GB = 1024.0**3


def host_in_use() -> float:
    st = _MemStatus(); st.dwLength = ctypes.sizeof(_MemStatus)
    ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(st))
    return (st.ullTotalPhys - st.ullAvailPhys) / GB


_peak = {"v": 0.0, "stop": False}


def _sampler() -> None:
    while not _peak["stop"]:
        _peak["v"] = max(_peak["v"], host_in_use())
        time.sleep(0.05)


def main() -> int:
    model_dir, device, cache_dir, label = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
    Path(cache_dir).mkdir(parents=True, exist_ok=True)

    cache_bytes_before = sum(f.stat().st_size for f in Path(cache_dir).rglob("*") if f.is_file())

    rec: dict = {
        "label": label, "model": Path(model_dir).name, "device": device,
        "cache_dir": cache_dir,
        "cache_bytes_before_gb": round(cache_bytes_before / GB, 3),
        "baseline_host_in_use_gb": round(host_in_use(), 3),
        "openvino_genai_version": ov_genai.__version__,
    }
    print(json.dumps({"stage": "start", **{k: rec[k] for k in
                      ("label", "baseline_host_in_use_gb", "cache_bytes_before_gb")}}), flush=True)

    threading.Thread(target=_sampler, daemon=True).start()

    t0 = time.perf_counter()
    try:
        pipe = ov_genai.VLMPipeline(model_dir, device, CACHE_DIR=cache_dir)
    except Exception as exc:  # noqa: BLE001 - verbatim error IS the finding
        rec["load_error"] = f"{type(exc).__name__}: {exc}"
        rec["peak_before_failure_gb"] = round(_peak["v"], 3)
        print(json.dumps({"stage": "LOAD_FAILED", "peak_before_failure_gb":
                          rec["peak_before_failure_gb"], "error": rec["load_error"]}), flush=True)
        Path(f"cache_{label}.json").write_text(json.dumps(rec, indent=2), encoding="utf-8")
        return 1

    rec["load_seconds"] = round(time.perf_counter() - t0, 2)
    rec["after_load_host_in_use_gb"] = round(host_in_use(), 3)
    rec["steady_delta_gb"] = round(
        rec["after_load_host_in_use_gb"] - rec["baseline_host_in_use_gb"], 3)
    rec["peak_host_in_use_gb"] = round(_peak["v"], 3)
    rec["transient_delta_gb"] = round(
        rec["peak_host_in_use_gb"] - rec["baseline_host_in_use_gb"], 3)

    # one real vision call to prove the cached pipeline actually works
    img = Image.open(str(Path(__file__).parent / "subjects" / "cook_broken.png")).convert("RGB")
    arr = np.array(img)[None]
    cfg = ov_genai.GenerationConfig(); cfg.max_new_tokens = 64; cfg.do_sample = False
    t1 = time.perf_counter()
    out = pipe.generate(
        "This is a screenshot of a web page. Does the page appear correctly rendered and styled, "
        "or does it look broken / unstyled / missing its layout?\n"
        'Reply with ONLY this JSON: {"render": "ok" or "broken", "reason": "<brief>"}',
        images=[ov.Tensor(arr)], generation_config=cfg)
    rec["vision_seconds"] = round(time.perf_counter() - t1, 2)
    rec["vision_text"] = out.texts[0] if out.texts else ""

    del pipe
    gc.collect(); time.sleep(3.0); _peak["stop"] = True

    cache_after = sum(f.stat().st_size for f in Path(cache_dir).rglob("*") if f.is_file())
    rec["cache_bytes_after_gb"] = round(cache_after / GB, 3)

    Path(f"cache_{label}.json").write_text(json.dumps(rec, indent=2), encoding="utf-8")
    print(json.dumps({"RESULT": {
        "label": label, "load_seconds": rec["load_seconds"],
        "steady_delta_gb": rec["steady_delta_gb"],
        "transient_delta_gb": rec["transient_delta_gb"],
        "peak_host_in_use_gb": rec["peak_host_in_use_gb"],
        "cache_gb_after": rec["cache_bytes_after_gb"],
        "vision_seconds": rec["vision_seconds"],
        "vision_text": rec["vision_text"][:160]}}, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
