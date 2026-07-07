"""
KV-cache precision sweep — long-context (16K/32K) standing harness.
====================================================================
Measures how KV-cache precision (FP16 / INT8 / INT4) trades off against
TTFT, per-token latency, and memory on the Arc 140V at LONG context, on the
PLAIN target pipeline (no draft — pure prefill + decode), prefix-caching OFF.

WHY THIS HARNESS WAS REWRITTEN (2026-06-29, Vikunja #709)
---------------------------------------------------------
The first long-context sweep was pathological — TTFT 47s @ 16K and 310s @ 32K,
N=2, wild run-to-run variance — and its memory column was flat (~20.85 GB)
across every precision, so it answered neither the speed nor the memory question
it was built for. Root cause: it copied the PRODUCTION ``SchedulerConfig``
(``cache_size = 3`` GB), which is right for short conversational turns but
*starves* the KV cache at long context. Qwen3-14B needs ~160 KiB/token of KV at
FP16 (2 x 40 layers x 8 KV-heads x 128 head_dim x 2 bytes), so 32K FP16 needs
~5.1 GiB — it does not fit in a 3 GiB budget, forcing block eviction + prefill
recompute/preemption (the 10x-slow, high-variance TTFT). A fixed 3 GiB pool also
pins the allocation regardless of precision, which is why the memory readout
could not see the precision lever.

THE FIXES (all four, plus a real GPU-memory instrument)
-------------------------------------------------------
1. RIGHT-SIZE the scheduler per (precision, context): ``cache_size`` is sized
   from the ANALYTICAL KV requirement x a safety margin (never the fixed 3).
   This removes the eviction pathology AND lets the pool track actual need.
2. FRESH PIPELINE per (precision, context) — build, ``del``, ``gc.collect()``,
   settle — so KV-pool growth/fragmentation from 16K never bleeds into 32K.
3. WARM AT THE ACTUAL CONTEXT LENGTH before timing (one untimed generate at the
   real prompt length), so the first measured run does not eat one-time
   compile/allocation cost.
4. N>=5 repeats, report median + std (N=2 could not tame the 47s-vs-311s noise).

MEMORY — three instruments, each labelled for what it can and cannot see:
  * analytical_kv_gib  — ground truth from model geometry x precision bytes.
  * gpu_mem_*          — OpenVINO ``GPU_MEMORY_STATISTICS`` (usm_device etc.),
                         the GPU-allocation-level instrument. PRIMARY when it
                         tracks the pipeline's allocations in-process.
  * sys_peak_used_gib  — system-RAM proxy (avail-RAM delta). On this shared-LPDDR5X
                         iGPU, GPU allocations come from system RAM, so this is a
                         coarse proxy (it can be blind to a driver-pre-reserved
                         pool — see benchmark_coresident.py's note).

Usage (repo root, runtime venv, LOCALAPPDATA redirected):
  .venv\\Scripts\\python.exe scripts\\benchmark_kv_cache_sweep.py \
      --model-dir models\\qwen3-14b\\openvino-int4-gpu
  # smoke one combo first (fail fast before the full sweep):
  .venv\\Scripts\\python.exe scripts\\benchmark_kv_cache_sweep.py \
      --model-dir models\\qwen3-14b\\openvino-int4-gpu \
      --contexts 32768 --precisions fp16_unset --repeats 2
"""

from __future__ import annotations

import argparse
import gc
import json
import math
import statistics
import sys
import time
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

# Heavy/optional imports are guarded so the PURE helpers below (and their unit
# tests) import on any machine, even without the OpenVINO runtime or a GPU.
try:
    import openvino as ov  # noqa: E402
except Exception:  # noqa: BLE001
    ov = None
try:
    import openvino_genai as ov_genai  # noqa: E402
except Exception:  # noqa: BLE001
    ov_genai = None
try:
    import psutil  # noqa: E402
except Exception:  # noqa: BLE001
    psutil = None


# ---------------------------------------------------------------------------
# Constants / model geometry
# ---------------------------------------------------------------------------

MEM_CEILING_GIB = 31.323  # effective system RAM (ADR; 32 GB - 693 MB firmware)

# KV-cache precision sweep. "fp16_unset" = leave KV at the FP16 default (do NOT
# set KV_CACHE_PRECISION); "u8"/"u4" set the GPU KV_CACHE_PRECISION property.
PRECISIONS = ("fp16_unset", "u8", "u4")

# Bytes per KV element by sweep precision (one element = one K or V scalar).
_PREC_BYTES = {"fp16_unset": 2.0, "u8": 1.0, "u4": 0.5}

# Qwen3-14B geometry — used only as a fallback if config.json can't be read.
# (Verified 2026-06-29: 40 layers, 8 KV heads, head_dim 128.)
_GEOM_FALLBACK = {"num_hidden_layers": 40, "num_key_value_heads": 8, "head_dim": 128}

# cache_size sizing knobs.
_CACHE_MARGIN = 1.5   # x analytical need (block-allocator slack + safety)
_CACHE_FLOOR_GB = 4   # never smaller than this (so short prompts are never starved)

_GPU_MEM_KEYS = ("cl_mem", "unknown", "usm_device", "usm_host", "usm_shared")

# Neutral, version-controlled filler (held constant for cross-run comparability).
_BASE = (
    "The quick brown fox jumps over the lazy dog near the river bank while the "
    "sun sets slowly behind the distant mountains and a gentle wind carries the "
    "scent of pine across the quiet valley below. "
)


# ---------------------------------------------------------------------------
# PURE helpers (no hardware, no model — unit-tested)
# ---------------------------------------------------------------------------

def load_geometry(model_dir: str | Path) -> dict:
    """Read attention geometry from the model's config.json; fall back to the
    verified Qwen3-14B constants if it can't be read. Only the three fields the
    KV-size math needs are returned."""
    try:
        cfg = json.loads((Path(model_dir) / "config.json").read_text(encoding="utf-8"))
        return {
            "num_hidden_layers": int(cfg["num_hidden_layers"]),
            # GQA: KV heads default to attention heads when not separately given.
            "num_key_value_heads": int(
                cfg.get("num_key_value_heads", cfg["num_attention_heads"])
            ),
            "head_dim": int(
                cfg.get("head_dim", cfg["hidden_size"] // cfg["num_attention_heads"])
            ),
        }
    except Exception:  # noqa: BLE001
        return dict(_GEOM_FALLBACK)


def analytical_kv_gib(context: int, precision: str, geom: dict) -> float:
    """Analytical KV-cache size in GiB for a full ``context`` prompt.

    KV bytes/token = 2 (K+V) x layers x kv_heads x head_dim x bytes_per_element.
    This is the ground-truth memory lever the precision sweep is measuring.
    """
    if precision not in _PREC_BYTES:
        raise ValueError(f"unknown precision {precision!r}")
    bytes_per_token = (
        2
        * geom["num_hidden_layers"]
        * geom["num_key_value_heads"]
        * geom["head_dim"]
        * _PREC_BYTES[precision]
    )
    return context * bytes_per_token / (1024 ** 3)


def size_cache_gb(
    context: int,
    precision: str,
    geom: dict,
    margin: float = _CACHE_MARGIN,
    floor_gb: int = _CACHE_FLOOR_GB,
) -> int:
    """Right-sized ``SchedulerConfig.cache_size`` (GB, integer) for one combo.

    THE FIX: instead of the production ``cache_size = 3`` (which starves long
    context), size to the analytical KV need x a safety margin, with a floor.
    Sizing per-combo (rather than one fixed generous value) also keeps the pool
    proportional to actual need, so the precision lever stays visible.
    """
    need = analytical_kv_gib(context, precision, geom)
    return max(int(floor_gb), int(math.ceil(need * margin)))


def kv_precision_props(precision: str) -> dict:
    """GPU runtime properties for a KV-cache precision. FP16 is the default, so
    "fp16_unset" sets NOTHING (matching how the default is actually exercised)."""
    if precision == "fp16_unset":
        return {}
    if precision not in _PREC_BYTES:
        raise ValueError(f"unknown precision {precision!r}")
    return {"KV_CACHE_PRECISION": precision}


def mem_stats_delta(before: dict, after: dict) -> dict:
    """Per-key (after - before) over the GPU_MEMORY_STATISTICS dict, in bytes."""
    return {k: int(after.get(k, 0)) - int(before.get(k, 0)) for k in _GPU_MEM_KEYS}


def compute_tpot_ms(total_ms: float, ttft_ms: float, n_tokens: int) -> float:
    """Time-per-output-token (ms) = (total - TTFT) / (generated tokens - 1).

    Returns -1.0 when it can't be computed (no first token, or <=1 token), so the
    sentinel is filtered out of the aggregate rather than poisoning the median."""
    if ttft_ms < 0 or n_tokens <= 1 or total_ms < ttft_ms:
        return -1.0
    return (total_ms - ttft_ms) / (n_tokens - 1)


def aggregate(vals: list[float]) -> dict:
    """median / mean / std / n over a list of measurements."""
    clean = [v for v in vals if v is not None]
    if not clean:
        return {"median": 0.0, "mean": 0.0, "std": 0.0, "n": 0}
    return {
        "median": round(statistics.median(clean), 2),
        "mean": round(statistics.mean(clean), 2),
        "std": round(statistics.pstdev(clean), 2) if len(clean) > 1 else 0.0,
        "n": len(clean),
    }


def _b_to_gib(n: int) -> float:
    return round(n / (1024 ** 3), 3)


# ---------------------------------------------------------------------------
# Hardware helpers (need OpenVINO / a GPU — not unit-tested)
# ---------------------------------------------------------------------------

def avail_gib() -> float:
    return psutil.virtual_memory().available / (1024 ** 3) if psutil else 0.0


def gpu_mem_stats(core) -> dict:
    """Best-effort GPU_MEMORY_STATISTICS snapshot (bytes). Empty dict if the
    property is unavailable or the plugin isn't initialised yet."""
    try:
        ms = core.get_property("GPU", "GPU_MEMORY_STATISTICS")
        return {k: int(ms.get(k, 0)) for k in _GPU_MEM_KEYS}
    except Exception:  # noqa: BLE001
        return {}


def make_prompt(tok, n_tokens: int, nonce: str) -> tuple[str, int]:
    """~n_tokens-token prompt prefixed with a unique nonce (defeats any residual
    prefix cache so each repeat pays a real cold prefill). Returns (prompt, count)."""
    reps = max(1, (n_tokens // 30) + 4)
    raw = nonce + " " + (_BASE * reps)
    ids = tok(raw)["input_ids"][:n_tokens]
    prompt = tok.decode(ids, skip_special_tokens=True)
    return prompt, len(tok(prompt)["input_ids"])


def timed_generate(pipe, prompt: str, gen) -> tuple[float, float, int]:
    """Run one generation, measuring TTFT by streamer callback (real hardware-
    timed: the first streamed token's timestamp minus dispatch) and TPOT from the
    total span and the streamed token count. Returns (ttft_ms, tpot_ms, n_tokens).

    The streamer fires on the plain SchedulerConfig (ContinuousBatching) backend
    used here (no draft); the callback returns False to keep generating.
    """
    fired: list[float] = []
    ntok = [0]

    def _cb(_subword: str) -> bool:
        if not fired:
            fired.append(time.perf_counter())
        ntok[0] += 1
        return False  # False = continue generation

    t0 = time.perf_counter()
    pipe.generate(prompt, gen, streamer=_cb)
    t_end = time.perf_counter()
    ttft_ms = (fired[0] - t0) * 1000.0 if fired else -1.0
    total_ms = (t_end - t0) * 1000.0
    return ttft_ms, compute_tpot_ms(total_ms, ttft_ms, ntok[0]), ntok[0]


def kv_precision_supported(core, precision: str) -> bool:
    """Is the KV_CACHE_PRECISION property advertised by the GPU plugin?"""
    if precision == "fp16_unset":
        return True
    try:
        props = [str(p) for p in core.get_property("GPU", "SUPPORTED_PROPERTIES")]
        return "KV_CACHE_PRECISION" in props
    except Exception:  # noqa: BLE001
        return False


def run_combo(
    model_dir: str,
    tok,
    core,
    precision: str,
    context: int,
    geom: dict,
    repeats: int,
    gen_tokens: int,
) -> dict:
    """Build a fresh right-sized pipeline for one (precision, context), warm at
    length, then time N repeats. Returns the result record."""
    cache_gb = size_cache_gb(context, precision, geom)
    kv_props = kv_precision_props(precision)
    kv_ok = kv_precision_supported(core, precision)
    analytical = analytical_kv_gib(context, precision, geom)

    rec: dict = {
        "precision": precision,
        "context": context,
        "input_tokens": context,
        "cache_size_gb": cache_gb,
        "analytical_kv_gib": round(analytical, 3),
        "kv_precision_supported": kv_ok,
        "kv_precision_applied": bool(kv_props) and kv_ok,
    }
    if kv_props and not kv_ok:
        rec["note"] = "KV_CACHE_PRECISION not advertised by the GPU plugin — skipped (would fall back to FP16)"
        rec["skipped"] = True
        return rec

    sched = ov_genai.SchedulerConfig()
    sched.cache_size = cache_gb
    sched.enable_prefix_caching = False  # force cold prefill (isolate the engine)

    mem_before = gpu_mem_stats(core)
    sys_avail_before = avail_gib()

    t0 = time.perf_counter()
    pipe = ov_genai.LLMPipeline(
        model_dir, "GPU",
        PERFORMANCE_HINT="LATENCY",
        INFERENCE_PRECISION_HINT="f16",
        GPU_ENABLE_SDPA_OPTIMIZATION="ON",
        CACHE_DIR="",
        scheduler_config=sched,
        **kv_props,
    )
    rec["load_compile_s"] = round(time.perf_counter() - t0, 1)

    gen = ov_genai.GenerationConfig()
    gen.max_new_tokens = gen_tokens
    gen.do_sample = False

    # WARM AT THE ACTUAL CONTEXT LENGTH (untimed) — pays one-time compile/alloc.
    warm_prompt, _ = make_prompt(tok, context, f"warm{precision}{context}")
    pipe.generate(warm_prompt, gen)

    sys_avail_min = avail_gib()
    mem_peak = gpu_mem_stats(core)

    ttfts: list[float] = []
    tpots: list[float] = []
    in_toks: list[int] = []
    for r in range(repeats):
        prompt, actual = make_prompt(tok, context, f"r{r}c{context}p{precision}n{r * 7 + 13}")
        ttft, tpot, gen_n = timed_generate(pipe, prompt, gen)
        if ttft >= 0:
            ttfts.append(ttft)
        if tpot >= 0:
            tpots.append(tpot)
        in_toks.append(actual)
        sys_avail_min = min(sys_avail_min, avail_gib())
        snap = gpu_mem_stats(core)
        if snap:
            mem_peak = {k: max(mem_peak.get(k, 0), snap.get(k, 0)) for k in _GPU_MEM_KEYS}
        print(f"   {precision} c{context} r{r}: in={actual} gen={gen_n} "
              f"TTFT={ttft:.0f}ms TPOT={tpot:.2f}ms")

    rec["actual_tokens_mean"] = round(statistics.mean(in_toks), 1) if in_toks else 0
    rec["ttft_ms"] = aggregate(ttfts)
    rec["tpot_ms"] = aggregate(tpots)
    # Per-rep TTFT is retained so the COOL-START (first rep after cooldown) vs
    # SUSTAINED (later reps, chip heated) split stays visible — on this fanless
    # iGPU a sustained prefill burst thermally throttles, and the median alone
    # hides it. ttft_ms_first is the coolest, most cross-combo-comparable point.
    rec["ttft_ms_per_rep"] = [round(t, 1) for t in ttfts]
    rec["ttft_ms_first"] = round(ttfts[0], 1) if ttfts else None
    gpu_delta = mem_stats_delta(mem_before, mem_peak) if mem_before and mem_peak else {}
    rec["gpu_mem_peak_bytes"] = mem_peak
    rec["gpu_mem_delta_gib"] = {k: _b_to_gib(v) for k, v in gpu_delta.items()}
    # On this shared-LPDDR5X iGPU, allocations land in cl_mem (the reserved KV
    # pool — tracks cache_size) and usm_host (model weights + working buffers);
    # usm_device is the discrete-GPU field and stays ~0 here.
    rec["gpu_mem_kv_pool_gib"] = _b_to_gib(mem_peak.get("cl_mem", 0)) if mem_peak else None
    rec["gpu_mem_host_gib"] = _b_to_gib(mem_peak.get("usm_host", 0)) if mem_peak else None
    rec["sys_peak_used_gib"] = round(sys_avail_before - sys_avail_min, 2)
    print(f"   == {precision} c{context}: TTFT median={rec['ttft_ms']['median']}ms "
          f"(std {rec['ttft_ms']['std']}) | cache={cache_gb}GB analytical_KV={analytical:.2f}GiB "
          f"| KV-pool {rec['gpu_mem_kv_pool_gib']}GiB host {rec['gpu_mem_host_gib']}GiB")

    del pipe
    gc.collect()
    time.sleep(2.0)  # settle so the next combo starts from a clean pool
    return rec


def warm_to_steady_state(
    model_dir: str, tok, core, geom: dict,
    context: int = 16384, tol: float = 0.04, window: int = 3, max_iter: int = 20,
) -> dict:
    """Drive the fanless iGPU to a THERMAL PLATEAU before measuring, so every
    combo is timed at the same (throttled) steady state instead of an escalating
    temperature. Runs back-to-back prefills at a fixed load until the last
    ``window`` TTFTs agree within ``tol`` (relative), i.e. throttling has settled.

    Uses TTFT itself as the thermal proxy (no on-die temp sensor is wired here):
    while the chip heats, prefill TTFT climbs; when it stops climbing, we're at
    the plateau. Returns the ramp for the record.
    """
    cache_gb = size_cache_gb(context, "fp16_unset", geom)
    sched = ov_genai.SchedulerConfig()
    sched.cache_size = cache_gb
    sched.enable_prefix_caching = False
    pipe = ov_genai.LLMPipeline(
        model_dir, "GPU", PERFORMANCE_HINT="LATENCY", INFERENCE_PRECISION_HINT="f16",
        GPU_ENABLE_SDPA_OPTIMIZATION="ON", CACHE_DIR="", scheduler_config=sched,
    )
    gen = ov_genai.GenerationConfig()
    gen.max_new_tokens = 4  # heat comes from PREFILL; keep decode minimal
    gen.do_sample = False

    ramp: list[float] = []
    reached = False
    print(f"   [steady-state] warming to thermal plateau at {context} tok "
          f"(tol {tol:.0%}, window {window}, max {max_iter}) ...")
    for i in range(max_iter):
        prompt, _ = make_prompt(tok, context, f"ss{i}")
        ttft, _, _ = timed_generate(pipe, prompt, gen)
        ramp.append(round(ttft, 1))
        print(f"      warm {i}: TTFT={ttft:.0f}ms")
        if len(ramp) >= window:
            recent = ramp[-window:]
            spread = (max(recent) - min(recent)) / statistics.mean(recent)
            if spread <= tol:
                reached = True
                print(f"      plateau reached (last {window} within {spread:.1%})")
                break
    del pipe
    gc.collect()
    return {"context": context, "tol": tol, "window": window,
            "iters": len(ramp), "reached": reached, "ttft_ramp_ms": ramp}


def main() -> int:
    ap = argparse.ArgumentParser(description="BlarAI long-context KV-cache precision sweep.")
    ap.add_argument("--model-dir", required=True, help="repo-relative or absolute model dir")
    ap.add_argument("--contexts", default="16384,32768", help="comma-separated context lengths")
    ap.add_argument("--precisions", default=",".join(PRECISIONS),
                    help="comma-separated KV precisions from {fp16_unset,u8,u4}")
    ap.add_argument("--repeats", type=int, default=5)
    ap.add_argument("--gen-tokens", type=int, default=128)
    ap.add_argument("--cooldown-s", type=float, default=120.0,
                    help="idle seconds between combos so the fanless iGPU sheds heat and "
                         "each combo starts from a comparable thermal baseline (0 to disable)")
    ap.add_argument("--steady-state", action="store_true",
                    help="warm the iGPU to a thermal PLATEAU first, then run combos back-to-back "
                         "with NO cooldown so every precision is measured at the same throttled "
                         "steady state (the reproducible way to compare on a fanless chip; forces "
                         "--cooldown-s 0)")
    args = ap.parse_args()
    if args.steady_state:
        args.cooldown_s = 0.0

    if ov is None or ov_genai is None:
        print("FATAL: OpenVINO / OpenVINO GenAI not importable in this environment.")
        return 1

    from transformers import AutoTokenizer  # local import (heavy)

    md = Path(args.model_dir)
    model_dir = str(md if md.is_absolute() else (_REPO_ROOT / md).resolve())
    if not (Path(model_dir) / "openvino_model.xml").exists():
        print(f"FATAL: model not found at {model_dir}")
        return 1

    contexts = [int(x) for x in args.contexts.split(",")]
    precisions = [p.strip() for p in args.precisions.split(",")]
    geom = load_geometry(model_dir)
    tok = AutoTokenizer.from_pretrained(model_dir)
    core = ov.Core()

    print(f"== KV-cache precision sweep == ov={ov_genai.__version__}")
    print(f"   model={model_dir}")
    print(f"   geom={geom}  contexts={contexts} precisions={precisions} repeats={args.repeats}")

    steady_state_ramp = None
    if args.steady_state:
        steady_state_ramp = warm_to_steady_state(model_dir, tok, core, geom)

    results: list[dict] = []
    combos = [(p, c) for p in precisions for c in contexts]
    for idx, (precision, context) in enumerate(combos):
        if idx > 0 and args.cooldown_s > 0:
            print(f"   [cooldown] idling {args.cooldown_s:.0f}s so the iGPU sheds heat ...")
            time.sleep(args.cooldown_s)
        # FRESH PIPELINE PER (precision, context) — run_combo builds + tears down.
        results.append(run_combo(model_dir, tok, core, precision, context,
                                 geom, args.repeats, args.gen_tokens))

    out = {
        "harness": "kv_cache_sweep",
        "schema_version": 2,
        "measurement_state": "steady_state_sustained" if args.steady_state else "cooldown_separated",
        "steady_state_warmup": steady_state_ramp,
        "supersedes": "docs/performance/_invalid/kv_cache_sweep_2026-06-29_13-11-56.json (Vikunja #709)",
        "openvino_genai_version": ov_genai.__version__,
        "openvino_version": ov.__version__,
        "model_dir": model_dir,
        "geometry": geom,
        "methodology": {
            "cache_size": "right-sized per (precision,context) from analytical KV x margin (NOT the production cache_size=3)",
            "cache_margin": _CACHE_MARGIN,
            "cache_floor_gb": _CACHE_FLOOR_GB,
            "pipeline": "fresh per (precision,context), del+gc+settle between combos",
            "warmup": "one untimed generate at the FULL context length before timing",
            "cooldown_s": args.cooldown_s,
            "thermal": ("fanless Arc 140V throttles under sustained long-context prefill; combos are "
                        "cooldown-separated so each starts from a comparable baseline, and per-rep "
                        "TTFT (ttft_ms_first = cool start vs the median = sustained) is retained"),
            "prefix_caching": False,
            "draft": None,
            "do_sample": False,
            "memory_instruments": {
                "analytical_kv_gib": "ground truth from geometry x precision bytes (the true precision lever)",
                "gpu_mem_kv_pool_gib": "GPU_MEMORY_STATISTICS cl_mem — the reserved KV pool (tracks cache_size)",
                "gpu_mem_host_gib": "GPU_MEMORY_STATISTICS usm_host — model weights + working buffers",
                "sys_peak_used_gib": "system-RAM proxy (shared-LPDDR5X iGPU); coarse whole-footprint check",
                "note": "usm_device stays ~0 on this iGPU; the KV pool is pre-reserved to cache_size, so the precision lever is read from analytical_kv_gib, not the reserved-pool size",
            },
        },
        "config": {"contexts": contexts, "precisions": precisions,
                   "repeats": args.repeats, "gen_tokens": args.gen_tokens,
                   "cooldown_s": args.cooldown_s},
        "results": results,
    }
    safe_ov = ov_genai.__version__.split("-")[0].replace(".", "_")
    ts = time.strftime("%Y-%m-%d_%H-%M-%S")
    outpath = _REPO_ROOT / "docs" / "performance" / f"kv_cache_sweep_ov{safe_ov}_{ts}.json"
    outpath.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(f"\n[SAVE] {outpath}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
