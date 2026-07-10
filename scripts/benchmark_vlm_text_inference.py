"""
VLMPipeline Text-Generation Benchmark — Qwen3.6-27B successor eval (Stage 1)
=============================================================================
Measures text-only decode throughput (tok/s), TTFT, and prompt-processing (pp)
throughput for a VLMPipeline-class model on the GPU — the pipeline class
OpenVINO GenAI assigns to the natively-multimodal Qwen3.6 generation.

Methodology mirrors ``scripts/benchmark_gpu_inference.py`` (prompt set v1,
pp probe pp-v1, N measured + warmup runs, greedy, per-run cooldown) so the
numbers are directly comparable with the standing Qwen3-14B/8B entries in
PERFORMANCE_LOG.md. Differences forced by the pipeline class:

- VLMPipeline has no draft-model speculative decoding — there is exactly one
  configuration (spec-decode does not exist for this model family on OpenVINO
  GenAI as of 2026-07; see docs/MODEL_EVALUATION_QWEN36_27B.md).
- Full generated texts are captured into the result JSON: openvino.genai
  issue #3870 reports Qwen3.6-27B incoherent output on GenAI, and this run
  doubles as our own reproduction check. Coherence is judged by the reviewer
  from the captured texts, never by this script.

A pre-load headroom guard refuses to start when system-available memory is
below the safe floor for a ~15.7 GB INT4 load (the load-bearing lesson from
the 2026-06-21 swap measurement: check headroom BEFORE the load, because a
sub-threshold load death-spirals the host instead of failing cleanly).

Usage (from repo root with BlarAI venv, app closed / AO stopped):
  .venv\\Scripts\\python.exe scripts\\benchmark_vlm_text_inference.py
  .venv\\Scripts\\python.exe scripts\\benchmark_vlm_text_inference.py --runs 3 --warmup 1
  .venv\\Scripts\\python.exe scripts\\benchmark_vlm_text_inference.py --model-dir models/qwen3.6-27b-int4-ov
"""

from __future__ import annotations

import argparse
import gc
import json
import math
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

try:
    import openvino as ov  # type: ignore[import-untyped]
    _OV_VERSION: str = ov.__version__
except ImportError:
    ov = None  # type: ignore[assignment]
    _OV_VERSION = "unavailable"

try:
    import openvino_genai as ov_genai  # type: ignore[import-untyped]
    _OV_GENAI_VERSION: str = ov_genai.__version__
except ImportError:
    ov_genai = None  # type: ignore[assignment]
    _OV_GENAI_VERSION = "unavailable"

try:
    import psutil  # type: ignore[import-untyped]
except ImportError:
    psutil = None  # type: ignore[assignment]

DEFAULT_MODEL_DIR = "models/qwen3.6-27b-int4-ov"
_DEVICE = "GPU"

# Safe floor for loading ~15.7 GB INT4 weights: the 2026-06-21 measurement
# showed model loads transiently stage weights on CPU + GPU simultaneously,
# so available memory must comfortably exceed the weight size before load.
_HEADROOM_FLOOR_GB = 20.0

# ---------------------------------------------------------------------------
# Prompt set v1 — byte-identical to scripts/benchmark_gpu_inference.py so
# generation numbers are comparable across model families.
# ---------------------------------------------------------------------------
PROMPT_SET_VERSION: str = "v1"

PROMPTS: list[str] = [
    "What is the capital city of France?",
    "How many bytes are in one kilobyte?",
    "Explain what a transformer neural network is in plain language.",
    "What is quantization in the context of machine learning models, "
    "and why does it help with inference speed?",
]

MAX_NEW_TOKENS = 256

# ---------------------------------------------------------------------------
# Prefill (pp) probe — byte-identical body to pp-v1 in
# scripts/benchmark_gpu_inference.py; unique per-run prefix defeats
# prefix-caching exactly as the original does.
# ---------------------------------------------------------------------------
PREFILL_PROBE_VERSION: str = "pp-v1"

_PREFILL_PROBE: str = (
    "This is a fixed, version-controlled prefill probe used to measure the "
    "prompt-processing throughput of a local language model on integrated "
    "graphics hardware. Prompt processing, sometimes called prefill, is the "
    "phase in which the model reads and encodes every token of the input "
    "prompt before it begins to generate a single new token. On a memory "
    "bandwidth limited device such as an integrated graphics processor that "
    "shares system memory with the host, the prefill phase behaves very "
    "differently from the token generation phase. Prefill is compute bound and "
    "highly parallel, because the model can process all of the prompt tokens "
    "together in large batched matrix multiplications, whereas generation is "
    "memory bound and sequential, because each new token depends on the one "
    "produced before it. For this reason the two phases are reported as two "
    "separate numbers in most benchmarking tools, one for prompt processing "
    "throughput and one for generation throughput, and they can differ by more "
    "than an order of magnitude on the same hardware. The purpose of this "
    "passage is simply to provide a stable and reasonably long block of "
    "natural language text so that the prefill measurement reflects a "
    "realistic prompt length rather than a trivial one. A trivial prompt of "
    "only a handful of tokens is dominated by fixed dispatch overhead and does "
    "not reveal the true sustained prefill rate of the device. By holding the "
    "wording of this passage constant across every run and every release, the "
    "benchmark keeps its prompt processing numbers comparable over time, in "
    "the same way that holding the generation prompts constant keeps the "
    "generation numbers comparable. The text deliberately avoids unusual "
    "symbols, code, or formatting so that the token count remains stable "
    "across tokenizer revisions. When this probe is run through the production "
    "generation path, the model first encodes all of these tokens during "
    "prefill, then produces exactly one new token, so the measured latency "
    "closely approximates the pure prefill time. Dividing the number of input "
    "tokens by that time yields the prompt processing throughput, expressed in "
    "tokens per second, which can then be compared directly against the "
    "community reported prefill figures for the same class of integrated "
    "graphics hardware."
)


@dataclass
class SingleRunMetrics:
    """Raw metrics from one text generation."""

    prompt_index: int
    token_count: int
    latency_first_token_ms: float
    latency_total_ms: float
    throughput_tok_per_sec: float
    output_text: str
    error: str | None


@dataclass
class PrefillRunMetrics:
    """Raw metrics from one prompt-processing probe run."""

    input_tokens: int
    prefill_ms: float
    prefill_tok_per_sec: float
    error: str | None


def compute_mean(values: list[float]) -> float:
    """Arithmetic mean of a non-empty list. Returns 0.0 for empty input."""
    if not values:
        return 0.0
    return sum(values) / len(values)


def compute_median(values: list[float]) -> float:
    """Median of a non-empty list. Returns 0.0 for empty input."""
    if not values:
        return 0.0
    s = sorted(values)
    n = len(s)
    mid = n // 2
    if n % 2 == 1:
        return s[mid]
    return (s[mid - 1] + s[mid]) / 2.0


def compute_p95(values: list[float]) -> float:
    """95th-percentile (nearest-rank). Returns 0.0 for empty input."""
    if not values:
        return 0.0
    s = sorted(values)
    rank = math.ceil(0.95 * len(s))
    rank = max(1, min(rank, len(s)))
    return s[rank - 1]


def _sys_available_gb() -> float:
    """System available memory in GB; -1.0 when psutil is unavailable."""
    if psutil is None:
        return -1.0
    return psutil.virtual_memory().available / (1024.0**3)


def _greedy_config(max_new_tokens: int) -> "ov_genai.GenerationConfig":
    cfg = ov_genai.GenerationConfig()
    cfg.max_new_tokens = max_new_tokens
    cfg.do_sample = False
    return cfg


def _measure_one(pipe: object, prompt: str, prompt_index: int) -> SingleRunMetrics:
    """One greedy text-only generate through VLMPipeline, hardware-timed.

    TTFT and token count come from the streamer callback (first-invocation
    timestamp; one invocation per decoded chunk). The streamer returns False
    to continue — the raw openvino_genai contract, inverse of the production
    engine's wrapper convention.
    """
    first_token_perf: list[float] = []
    chunks: list[str] = []

    def _streamer(subword: str) -> bool:
        if not first_token_perf:
            first_token_perf.append(time.perf_counter())
        chunks.append(subword)
        return False  # continue generation

    cfg = _greedy_config(MAX_NEW_TOKENS)
    t_dispatch = time.perf_counter()
    try:
        result = pipe.generate(prompt, generation_config=cfg, streamer=_streamer)
    except Exception as exc:  # noqa: BLE001 — benchmark records, never crashes the sweep
        return SingleRunMetrics(
            prompt_index=prompt_index,
            token_count=0,
            latency_first_token_ms=0.0,
            latency_total_ms=0.0,
            throughput_tok_per_sec=0.0,
            output_text="",
            error=f"{type(exc).__name__}: {exc}",
        )
    t_done = time.perf_counter()

    total_ms = (t_done - t_dispatch) * 1000.0
    ttft_ms = (first_token_perf[0] - t_dispatch) * 1000.0 if first_token_perf else -1.0
    token_count = len(chunks)
    # Prefer the backend's own perf metrics when exposed (authoritative count).
    try:
        pm = result.perf_metrics
        token_count = int(pm.get_num_generated_tokens())
    except Exception:  # noqa: BLE001 — streamer count is the documented fallback
        pass
    decode_ms = total_ms - ttft_ms if ttft_ms > 0 else total_ms
    tps = token_count / (decode_ms / 1000.0) if decode_ms > 0 and token_count > 0 else 0.0
    return SingleRunMetrics(
        prompt_index=prompt_index,
        token_count=token_count,
        latency_first_token_ms=ttft_ms,
        latency_total_ms=total_ms,
        throughput_tok_per_sec=tps,
        output_text="".join(chunks) if chunks else str(result),
        error=None,
    )


def _measure_prefill(pipe: object, run_index: int) -> PrefillRunMetrics:
    """pp probe: unique prefix + fixed body, max_new_tokens=1."""
    probe = f"Run {run_index} unique prefix {time.time_ns()}. " + _PREFILL_PROBE
    cfg = _greedy_config(1)
    t0 = time.perf_counter()
    try:
        result = pipe.generate(probe, generation_config=cfg)
    except Exception as exc:  # noqa: BLE001
        return PrefillRunMetrics(
            input_tokens=-1, prefill_ms=0.0, prefill_tok_per_sec=0.0,
            error=f"{type(exc).__name__}: {exc}",
        )
    prefill_ms = (time.perf_counter() - t0) * 1000.0
    input_tokens = -1
    try:
        pm = result.perf_metrics
        input_tokens = int(pm.get_num_input_tokens())
    except Exception:  # noqa: BLE001 — pp reported as latency-only when uncounted
        pass
    pp = input_tokens / (prefill_ms / 1000.0) if input_tokens > 0 and prefill_ms > 0 else 0.0
    return PrefillRunMetrics(
        input_tokens=input_tokens, prefill_ms=prefill_ms,
        prefill_tok_per_sec=pp, error=None,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-dir", default=DEFAULT_MODEL_DIR)
    parser.add_argument("--runs", type=int, default=5)
    parser.add_argument("--warmup", type=int, default=2)
    parser.add_argument("--cooldown", type=float, default=30.0,
                        help="Seconds between measured runs (thermal).")
    parser.add_argument("--force", action="store_true",
                        help="Skip the pre-load memory headroom guard.")
    args = parser.parse_args()

    if ov_genai is None:
        print("FATAL: openvino_genai is not importable in this environment.")
        return 2

    model_dir = (_REPO_ROOT / args.model_dir).resolve()
    if not (model_dir / "openvino_language_model.xml").exists():
        print(f"FATAL: no openvino_language_model.xml under {model_dir}")
        return 2

    available_gb = _sys_available_gb()
    if not args.force and 0 <= available_gb < _HEADROOM_FLOOR_GB:
        print(
            f"ABORT: system available memory {available_gb:.1f} GB is below the "
            f"{_HEADROOM_FLOOR_GB:.0f} GB pre-load floor for a ~15.7 GB INT4 load. "
            "Close the BlarAI app / stop the AO / lean the box, then re-run "
            "(--force overrides, accepting the death-spiral risk)."
        )
        return 3

    print(f"Loading {model_dir.name} on {_DEVICE} (OV {_OV_VERSION} / GenAI {_OV_GENAI_VERSION})")
    mem_before_load = _sys_available_gb()
    t_load = time.perf_counter()
    pipe = ov_genai.VLMPipeline(str(model_dir), _DEVICE)
    load_s = time.perf_counter() - t_load
    mem_after_load = _sys_available_gb()
    print(f"Loaded in {load_s:.1f}s; system available {mem_before_load:.1f} -> {mem_after_load:.1f} GB")

    for w in range(args.warmup):
        print(f"warmup {w + 1}/{args.warmup} ...")
        _measure_one(pipe, PROMPTS[0], 0)

    gen_runs: list[SingleRunMetrics] = []
    pp_runs: list[PrefillRunMetrics] = []
    mem_min_during = mem_after_load
    for r in range(args.runs):
        for i, prompt in enumerate(PROMPTS):
            m = _measure_one(pipe, prompt, i)
            gen_runs.append(m)
            status = m.error or f"{m.token_count} tok, {m.throughput_tok_per_sec:.1f} tok/s"
            print(f"run {r + 1}/{args.runs} P{i + 1}: {status}")
            avail = _sys_available_gb()
            if 0 <= avail < mem_min_during:
                mem_min_during = avail
        pp_runs.append(_measure_prefill(pipe, r))
        if r < args.runs - 1 and args.cooldown > 0:
            time.sleep(args.cooldown)

    ok = [m for m in gen_runs if m.error is None and m.token_count > 0]
    tps_vals = [m.throughput_tok_per_sec for m in ok]
    ttft_vals = [m.latency_first_token_ms for m in ok if m.latency_first_token_ms > 0]
    pp_ok = [p.prefill_tok_per_sec for p in pp_runs if p.error is None and p.prefill_tok_per_sec > 0]

    summary = {
        "benchmark": "vlm_text_inference",
        "model": model_dir.name,
        "device": _DEVICE,
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "openvino_version": _OV_VERSION,
        "openvino_genai_version": _OV_GENAI_VERSION,
        "prompt_set_version": PROMPT_SET_VERSION,
        "prefill_probe_version": PREFILL_PROBE_VERSION,
        "runs": args.runs,
        "warmup": args.warmup,
        "cooldown_s": args.cooldown,
        "max_new_tokens": MAX_NEW_TOKENS,
        "load_seconds": round(load_s, 1),
        "sys_available_gb_before_load": round(mem_before_load, 2),
        "sys_available_gb_after_load": round(mem_after_load, 2),
        "sys_available_gb_min_during": round(mem_min_during, 2),
        "generation": {
            "median_tps": round(compute_median(tps_vals), 2),
            "mean_tps": round(compute_mean(tps_vals), 2),
            "p95_tps": round(compute_p95(tps_vals), 2),
            "median_ttft_ms": round(compute_median(ttft_vals), 0),
            "errors": [m.error for m in gen_runs if m.error],
        },
        "prefill": {
            "median_pp_tok_per_sec": round(compute_median(pp_ok), 0),
            "runs": [asdict(p) for p in pp_runs],
        },
        "coherence_note": (
            "Full output texts below are the openvino.genai #3870 reproduction "
            "evidence — judged by the reviewer, not by this script."
        ),
        "gen_runs": [asdict(m) for m in gen_runs],
        "not_measured": [
            "speculative decoding (does not exist for this pipeline class/model family)",
            "co-resident cost (benchmarked alone)",
            "vision/image inputs (text-only probe)",
            "long-context decode (256-token generations only)",
        ],
    }

    out_dir = _REPO_ROOT / "docs" / "performance"
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    out_path = out_dir / f"benchmark_vlm_text_{model_dir.name}_{stamp}.json"
    out_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    print()
    print(f"=== {model_dir.name} on {_DEVICE} ===")
    print(f"generation: median {summary['generation']['median_tps']} tok/s "
          f"(mean {summary['generation']['mean_tps']}, P95 {summary['generation']['p95_tps']})")
    print(f"TTFT median: {summary['generation']['median_ttft_ms']} ms")
    print(f"prefill pp median: {summary['prefill']['median_pp_tok_per_sec']} tok/s")
    print(f"results: {out_path}")

    del pipe
    gc.collect()
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
