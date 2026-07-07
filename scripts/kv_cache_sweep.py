"""
KV-cache precision sweep (Session-2, §4 catalog A3) — the headline memory lever.
================================================================================
On OpenVINO 2026.2 the GPU plugin accepts a KV_CACHE_PRECISION hint; on the Arc
140V (XMX) KV-cache quant is opt-in. This sweeps {unset/FP16, u8, INT4} × {16K,
32K}-token contexts on the 14B and measures the peak SHARED-RAM footprint
(In-Use = Total - Available, NOT working-set sums), TTFT and TPOT, so we can see
how much RAM INT8/INT4 KV-cache saves at long context (could let the hires-SDXL
path stop evicting the resident 14B).

Method: plain LLMPipeline (NO draft — isolates the target's KV cache), prefix
caching off, CACHE_DIR="". A background thread samples system Available RAM during
the generation; peak_used = total - min(available). The weight footprint is
constant across precisions, so the per-precision DELTA at a fixed context is the
KV-cache saving. First it PROBES which INT4 token the GPU plugin accepts (u4/i4).

Usage (repo root, runtime venv, LOCALAPPDATA redirected, GPU clean):
  .venv/Scripts/python.exe scratchpad/kv_cache_sweep.py
  .venv/Scripts/python.exe scratchpad/kv_cache_sweep.py --contexts 16384,32768 --gen 128
"""

from __future__ import annotations

import argparse
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

import openvino_genai as ov_genai  # noqa: E402
import psutil  # noqa: E402
from transformers import AutoTokenizer  # noqa: E402

from shared.constants import TARGET_MODEL_OV_PATH  # noqa: E402

_BASE = (
    "The quick brown fox jumps over the lazy dog near the river bank while the "
    "sun sets slowly behind the distant mountains and a gentle wind carries the "
    "scent of pine across the quiet valley below. "
)


class MemSampler(threading.Thread):
    """Sample system Available RAM; expose min_available (=> peak used)."""

    def __init__(self, interval: float = 0.05):
        super().__init__(daemon=True)
        self.interval = interval
        self._stopev = threading.Event()
        self.min_available = psutil.virtual_memory().available
        self.total = psutil.virtual_memory().total

    def run(self):
        while not self._stopev.is_set():
            a = psutil.virtual_memory().available
            if a < self.min_available:
                self.min_available = a
            time.sleep(self.interval)

    def stop(self):
        self._stopev.set()
        self.join(timeout=2.0)

    @property
    def peak_used_gb(self) -> float:
        return (self.total - self.min_available) / 1e9


def make_prompt(tok, n_tokens: int) -> tuple[str, int]:
    reps = max(1, (n_tokens // 30) + 4)
    ids = tok(_BASE * reps)["input_ids"][:n_tokens]
    prompt = tok.decode(ids, skip_special_tokens=True)
    return prompt, len(tok(prompt)["input_ids"])


def build_pipe(model_dir: str, precision: str | None):
    sched = ov_genai.SchedulerConfig()
    sched.cache_size = 3
    sched.enable_prefix_caching = False
    props = {
        "PERFORMANCE_HINT": "LATENCY", "MODEL_PRIORITY": "HIGH",
        "INFERENCE_PRECISION_HINT": "f16", "GPU_ENABLE_SDPA_OPTIMIZATION": "ON",
        "CACHE_DIR": "", "scheduler_config": sched,
    }
    if precision:
        props["KV_CACHE_PRECISION"] = precision
    return ov_genai.LLMPipeline(model_dir, "GPU", **props)


def probe_int4_token(model_dir: str) -> str | None:
    """Return the first INT4 token the GPU plugin accepts (u4/i4), else None."""
    for tok in ("u4", "i4"):
        try:
            p = build_pipe(model_dir, tok)
            del p
            print(f"   [probe] KV_CACHE_PRECISION='{tok}' ACCEPTED")
            return tok
        except Exception as exc:  # noqa: BLE001
            print(f"   [probe] KV_CACHE_PRECISION='{tok}' rejected: {str(exc)[:80]}")
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model-dir", default=str(_REPO_ROOT / TARGET_MODEL_OV_PATH))
    ap.add_argument("--contexts", default="16384,32768")
    ap.add_argument("--gen", type=int, default=128)
    ap.add_argument("--repeats", type=int, default=2)
    args = ap.parse_args()

    model_dir = str(Path(args.model_dir).resolve())
    contexts = [int(x) for x in args.contexts.split(",")]
    ov_ver = ov_genai.__version__
    print(f"== KV-cache precision sweep == ov={ov_ver}")
    print(f"   model={model_dir}")
    print(f"   contexts={contexts} gen={args.gen} repeats={args.repeats}")

    tok = AutoTokenizer.from_pretrained(model_dir)

    print("  [probe] confirming the INT4 token the GPU plugin accepts ...")
    int4_tok = probe_int4_token(model_dir)
    precisions: list[str | None] = [None, "u8"]
    if int4_tok:
        precisions.append(int4_tok)
    print(f"   sweep precisions: {['FP16(unset)' if p is None else p for p in precisions]}")

    results = []
    for precision in precisions:
        label = "fp16_unset" if precision is None else precision
        print(f"\n=== precision={label} ===")
        t0 = time.perf_counter()
        pipe = build_pipe(model_dir, precision)
        print(f"   load+compile: {time.perf_counter()-t0:.1f}s")
        gen = ov_genai.GenerationConfig()
        gen.max_new_tokens = args.gen
        gen.do_sample = False
        # warmup (short)
        pipe.generate(["warmup short prompt"], gen)
        for ctx in contexts:
            prompt, actual = make_prompt(tok, ctx)
            peaks, ttfts, tpots = [], [], []
            for r in range(args.repeats):
                sampler = MemSampler()
                sampler.start()
                res = pipe.generate([prompt], gen)
                sampler.stop()
                pm = res.perf_metrics
                ttft = pm.get_ttft().mean
                tpot = pm.get_tpot().mean
                peaks.append(sampler.peak_used_gb); ttfts.append(ttft); tpots.append(tpot)
                print(f"   ctx~{ctx} (in={actual}) r{r}: peak_used={sampler.peak_used_gb:.2f}GB "
                      f"ttft={ttft:.0f}ms tpot={tpot:.1f}ms")
            results.append({
                "precision": label, "context": ctx, "input_tokens": actual,
                "peak_used_gb_median": round(statistics.median(peaks), 2),
                "peak_used_gb_max": round(max(peaks), 2),
                "ttft_ms_median": round(statistics.median(ttfts), 1),
                "tpot_ms_median": round(statistics.median(tpots), 2),
                "n": len(peaks),
            })
        del pipe
        time.sleep(2)  # let the allocator settle before the next precision

    print("\n=== SUMMARY (peak shared-RAM = In-Use = Total - Available) ===")
    for row in results:
        print(f"   {row['precision']:11} ctx~{row['context']:>6}: "
              f"peak {row['peak_used_gb_median']:.2f}GB | ttft {row['ttft_ms_median']:.0f}ms | tpot {row['tpot_ms_median']:.2f}ms")

    out = {
        "harness": "kv_cache_sweep", "openvino_genai_version": ov_ver,
        "openvino_version": __import__("openvino").__version__,
        "model_dir": model_dir, "int4_token": int4_tok,
        "config": {"contexts": contexts, "gen": args.gen, "repeats": args.repeats,
                   "draft": None, "prefix_caching": False, "do_sample": False,
                   "system_total_gb": round(psutil.virtual_memory().total / 1e9, 2)},
        "results": results,
    }
    ts = time.strftime("%Y-%m-%d_%H-%M-%S")
    outpath = _REPO_ROOT / "docs" / "performance" / f"kv_cache_sweep_{ts}.json"
    outpath.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(f"\n[SAVE] {outpath}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
