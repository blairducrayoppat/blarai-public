"""
GPU Inference Benchmark — BlarAI Qwen3-14B INT4
=================================================
Repeatable inference-performance benchmark for BlarAI's production model.
Measures throughput (tokens/sec), TTFT (time-to-first-token), and total
latency across two engine configurations:
  (a) Speculative decoding OFF
  (b) Speculative decoding ON  (falls back silently if draft model absent)

The benchmark uses the PRODUCTION load path — ``OrchestratorGPUInference``
from ``services/assistant_orchestrator/src/gpu_inference.py`` — so numbers
reflect how BlarAI actually runs, not a synthetic harness.

Prompt set is version-controlled in this script so every run is comparable.
Re-measure after: speculative decoding toggles, EAGLE3 integration,
OpenVINO/driver upgrades, model swaps.

Usage (from repo root with BlarAI venv):
  .venv\\Scripts\\python.exe scripts\\benchmark_gpu_inference.py
  .venv\\Scripts\\python.exe scripts\\benchmark_gpu_inference.py --runs 3 --warmup 1
  .venv\\Scripts\\python.exe scripts\\benchmark_gpu_inference.py --configs spec_off
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

# ---------------------------------------------------------------------------
# Repo root resolution — allow import of shared / services packages.
# ---------------------------------------------------------------------------
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

# ---------------------------------------------------------------------------
# Optional dependency probe — openvino (for version strings).
# ---------------------------------------------------------------------------
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

from shared.constants import (
    DRAFT_MODEL_OV_PATH,
    NUM_ASSISTANT_TOKENS,
    TARGET_MODEL_OV_PATH,
)
from services.assistant_orchestrator.src.gpu_inference import (
    GenerationConfig,
    GenerationResult,
    OrchestratorGPUInference,
)

# ---------------------------------------------------------------------------
# Fixed prompt set — version-controlled for repeatability.
# Every run uses exactly these prompts so results are comparable over time.
# Prompt set v1 (2026-05-21): 2 short factual + 2 medium explanatory.
# ---------------------------------------------------------------------------
PROMPT_SET_VERSION: str = "v1"

PROMPTS: list[str] = [
    # P1 — short factual: single-word / one-line expected answer
    "What is the capital city of France?",
    # P2 — short factual: numeric / brief
    "How many bytes are in one kilobyte?",
    # P3 — medium explanatory: ~2-4 sentences expected
    "Explain what a transformer neural network is in plain language.",
    # P4 — medium explanatory: multi-sentence, slightly more depth
    "What is quantization in the context of machine learning models, "
    "and why does it help with inference speed?",
]

# Generation parameters — match production defaults (greedy, no sampling).
_GEN_CONFIG = GenerationConfig(
    max_new_tokens=256,
    temperature=0.0,
    top_k=0,
    top_p=1.0,
    do_sample=False,
)

# ---------------------------------------------------------------------------
# Prefill (prompt-processing) probe — version-controlled for repeatability.
# Measures pp (prompt-processing throughput, tok/s) — the same metric
# llama.cpp's llama-bench reports as pp512 — so BlarAI's prefill rate can be
# compared directly against community Arc 140V figures (see the 2026-06-27
# cross-runtime comparison in PERFORMANCE_LOG.md). pp is config-independent
# (prefill is the same forward pass with or without speculative decoding).
# Method: feed this fixed ~450-token passage through the production generate
# path with max_new_tokens=1, so the measured latency is essentially the
# prefill time; pp = formatted_input_tokens / prefill_seconds. Each run gets a
# unique prefix so prefix-caching cannot serve the body from cache.
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

# Single-token generation: isolates prefill so total latency ~= prefill time.
_PREFILL_GEN_CONFIG = GenerationConfig(
    max_new_tokens=1,
    temperature=0.0,
    top_k=0,
    top_p=1.0,
    do_sample=False,
)

# ---------------------------------------------------------------------------
# Per-generation measurement
# ---------------------------------------------------------------------------


@dataclass
class SingleRunMetrics:
    """Raw metrics from one generate_text() call."""

    prompt_index: int
    token_count: int
    latency_first_token_ms: float
    latency_total_ms: float
    throughput_tok_per_sec: float
    error: str | None


@dataclass
class PrefillRunMetrics:
    """Raw metrics from one prompt-processing (prefill) probe run."""

    input_tokens: int
    """Number of formatted input tokens the model prefilled (-1 if uncounted)."""

    prefill_ms: float
    """Measured prefill time (ms) — latency of a max_new_tokens=1 generation."""

    prefill_tok_per_sec: float
    """Prompt-processing throughput = input_tokens / prefill_seconds (pp)."""

    error: str | None


def _measure_one(
    engine: OrchestratorGPUInference,
    prompt: str,
    prompt_index: int,
) -> SingleRunMetrics:
    """Run generate_text() and return raw metrics.

    TTFT is measured directly: a streaming callback records a
    high-resolution timestamp on its first invocation (the first streamed
    token), and TTFT is that timestamp minus the moment generation was
    dispatched. This is a real hardware-timed measurement — not the
    engine's bounded ``latency_first_token_ms`` approximation.
    """
    first_token_perf: list[float] = []

    def _on_token(_chunk: str) -> bool:
        if not first_token_perf:
            first_token_perf.append(time.perf_counter())
        return True

    t_dispatch = time.perf_counter()
    result: GenerationResult = engine.generate_text(
        prompt=prompt,
        config=_GEN_CONFIG,
        stream_callback=_on_token,
    )
    if result.error:
        return SingleRunMetrics(
            prompt_index=prompt_index,
            token_count=0,
            latency_first_token_ms=0.0,
            latency_total_ms=0.0,
            throughput_tok_per_sec=0.0,
            error=result.error,
        )
    if first_token_perf:
        ttft_ms = (first_token_perf[0] - t_dispatch) * 1000.0
    else:
        # The stream callback never fired — TTFT is not measurable for this
        # generation. This happens on the speculative / ContinuousBatching
        # backend, which does not deliver incremental tokens through the
        # callback. Report a sentinel (-1.0) rather than substituting total
        # latency, which would be a misleading number.
        ttft_ms = -1.0
    tps = (
        result.token_count / (result.latency_total_ms / 1000.0)
        if result.latency_total_ms > 0
        else 0.0
    )
    return SingleRunMetrics(
        prompt_index=prompt_index,
        token_count=result.token_count,
        latency_first_token_ms=ttft_ms,
        latency_total_ms=result.latency_total_ms,
        throughput_tok_per_sec=tps,
        error=None,
    )


# ---------------------------------------------------------------------------
# Statistics helpers (pure functions — also unit-tested)
# ---------------------------------------------------------------------------


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
    """95th-percentile of a non-empty list. Returns 0.0 for empty input.

    Uses the nearest-rank method (ceiling of 0.95 * N).
    """
    if not values:
        return 0.0
    s = sorted(values)
    rank = math.ceil(0.95 * len(s))
    rank = max(1, min(rank, len(s)))
    return s[rank - 1]


def tokens_per_sec(token_count: int, latency_total_ms: float) -> float:
    """Output throughput in tokens/second (token_count / total generation time)."""
    if latency_total_ms <= 0:
        return 0.0
    return token_count / (latency_total_ms / 1000.0)


def prefill_tokens_per_sec(num_input_tokens: int, prefill_ms: float) -> float:
    """Prompt-processing throughput in tokens/second (pp).

    ``num_input_tokens / prefill_seconds`` — the same metric llama.cpp's
    llama-bench reports as ``pp512``. Returns 0.0 for non-positive inputs
    (guard case: an unmeasured prefill must not produce a misleading rate).
    """
    if prefill_ms <= 0 or num_input_tokens <= 0:
        return 0.0
    return num_input_tokens / (prefill_ms / 1000.0)


def _derive_model_name(model_dir: str) -> str:
    """Best-effort human model name from a model directory path.

    ``.../models/qwen3-8b/openvino-int4-gpu`` -> ``qwen3-8b``. Falls back to
    the parent directory name. Lets one script label 14B / 8B / other runs
    correctly instead of hardcoding 'Qwen3-14B'.
    """
    parts = Path(model_dir).parts
    if "models" in parts:
        idx = parts.index("models")
        if idx + 1 < len(parts):
            return parts[idx + 1]
    parent = Path(model_dir).parent.name
    return parent or Path(model_dir).name


def _fmt_ms(value: float) -> str:
    """Format a millisecond metric; 'n/a' for the -1.0 unmeasured sentinel."""
    return "n/a" if value < 0 else f"{value:.0f}"


# ---------------------------------------------------------------------------
# Per-config aggregation
# ---------------------------------------------------------------------------


@dataclass
class AggregateStats:
    """Aggregated statistics for one benchmark configuration."""

    mean_tps: float
    median_tps: float
    p95_tps: float
    mean_ttft_ms: float
    median_ttft_ms: float
    p95_ttft_ms: float
    mean_total_ms: float
    median_total_ms: float
    p95_total_ms: float
    total_runs: int
    error_runs: int


def aggregate(runs: list[SingleRunMetrics]) -> AggregateStats:
    """Compute aggregate statistics from a list of measured runs.

    TTFT statistics are computed only over runs where TTFT was actually
    measured (``latency_first_token_ms >= 0``). If no run measured TTFT,
    the three TTFT aggregates are -1.0 (unmeasured) — see ``_measure_one``.
    """
    good = [r for r in runs if r.error is None]
    tps_vals = [r.throughput_tok_per_sec for r in good]
    ttft_vals = [r.latency_first_token_ms for r in good if r.latency_first_token_ms >= 0]
    total_vals = [r.latency_total_ms for r in good]
    ttft_measured = bool(ttft_vals)
    return AggregateStats(
        mean_tps=compute_mean(tps_vals),
        median_tps=compute_median(tps_vals),
        p95_tps=compute_p95(tps_vals),
        mean_ttft_ms=compute_mean(ttft_vals) if ttft_measured else -1.0,
        median_ttft_ms=compute_median(ttft_vals) if ttft_measured else -1.0,
        p95_ttft_ms=compute_p95(ttft_vals) if ttft_measured else -1.0,
        mean_total_ms=compute_mean(total_vals),
        median_total_ms=compute_median(total_vals),
        p95_total_ms=compute_p95(total_vals),
        total_runs=len(runs),
        error_runs=len(runs) - len(good),
    )


@dataclass
class PrefillStats:
    """Aggregated prompt-processing (prefill) statistics for one config."""

    mean_pp: float
    median_pp: float
    p95_pp: float
    mean_input_tokens: float
    total_runs: int
    error_runs: int
    measured: bool
    """False when no run produced a usable token count (e.g. tokenizer absent)."""


def aggregate_prefill(runs: list[PrefillRunMetrics]) -> PrefillStats:
    """Compute aggregate prefill (pp) statistics from a list of probe runs.

    Only runs with a real token count and a positive prefill time contribute.
    ``measured`` is False if none qualified — callers must not present pp as a
    real number in that case (it would be a misleading 0.0).
    """
    good = [
        r
        for r in runs
        if r.error is None and r.input_tokens > 0 and r.prefill_ms > 0
    ]
    pp_vals = [r.prefill_tok_per_sec for r in good]
    tok_vals = [float(r.input_tokens) for r in good]
    return PrefillStats(
        mean_pp=compute_mean(pp_vals),
        median_pp=compute_median(pp_vals),
        p95_pp=compute_p95(pp_vals),
        mean_input_tokens=compute_mean(tok_vals),
        total_runs=len(runs),
        error_runs=len(runs) - len(good),
        measured=bool(good),
    )


def _count_formatted_input_tokens(engine: OrchestratorGPUInference, probe: str) -> int:
    """Count the tokens the engine will actually prefill for ``probe``.

    Uses the engine's own chat formatter + tokenizer so the count matches the
    production prefill exactly. Returns -1 if the tokenizer is unavailable or
    counting fails (prefill pp is then reported as unmeasured, never crashing
    the generation benchmark).
    """
    tok = getattr(engine, "_tokenizer", None)
    if tok is None:
        return -1
    text = probe
    fmt = getattr(engine, "_format_chat_prompt", None)
    if callable(fmt):
        try:
            text = fmt(probe)
        except Exception:  # noqa: BLE001 — formatting is best-effort here
            text = probe
    try:
        return len(tok.encode(text))
    except Exception:  # noqa: BLE001 — fall back to the callable form
        try:
            import numpy as _np  # noqa: F401  (only to satisfy return_tensors)

            enc = tok(text, return_tensors="np")
            return int(enc["input_ids"].shape[-1])
        except Exception:  # noqa: BLE001
            return -1


def measure_prefill(
    engine: OrchestratorGPUInference,
    num_runs: int,
    run_cooldown: int = 0,
) -> list[PrefillRunMetrics]:
    """Measure prompt-processing (prefill) throughput over the fixed probe.

    For each run: build a unique probe (a per-run prefix forces a cold prefill
    past any prefix cache), count the formatted input tokens, run a
    max_new_tokens=1 generation (its total latency ~= the prefill time), and
    compute pp = input_tokens / prefill_seconds. Prefill is config-independent,
    so one measurement per config is representative (and gives a cross-check).
    """
    runs: list[PrefillRunMetrics] = []
    for i in range(num_runs):
        if i > 0 and run_cooldown > 0:
            time.sleep(run_cooldown)
        # Per-run prefix -> the ~450-token body diverges early, so prefix
        # caching cannot serve it; each run pays a real cold prefill.
        probe = f"(prefill probe, iteration {i}) {_PREFILL_PROBE}"
        n_in = _count_formatted_input_tokens(engine, probe)
        result = engine.generate_text(
            prompt=probe,
            max_new_tokens=1,
            config=_PREFILL_GEN_CONFIG,
        )
        if result.error:
            runs.append(PrefillRunMetrics(n_in, 0.0, 0.0, result.error))
            continue
        pp = prefill_tokens_per_sec(n_in, result.latency_total_ms)
        runs.append(PrefillRunMetrics(n_in, result.latency_total_ms, pp, None))
    return runs


# ---------------------------------------------------------------------------
# Markdown entry formatter (pure function — unit-tested)
# ---------------------------------------------------------------------------


def format_markdown_entry(
    timestamp: str,
    config_stamp: dict[str, object],
    spec_off_stats: AggregateStats,
    spec_off_load_ms: float,
    spec_on_stats: AggregateStats,
    spec_on_load_ms: float,
    spec_off_achieved: bool,
    spec_on_achieved: bool,
    num_runs: int,
    num_warmup: int,
    spec_off_prefill: PrefillStats | None = None,
    spec_on_prefill: PrefillStats | None = None,
) -> str:
    """Return a ready-to-paste Markdown section for PERFORMANCE_LOG.md."""
    model_name = str(config_stamp.get("model_name", "Qwen3-14B"))
    model_dir = str(config_stamp.get("model_dir", ""))
    quant = str(config_stamp.get("quantization", "INT4"))
    device = str(config_stamp.get("device", "GPU"))
    ov_ver = str(config_stamp.get("openvino_version", ""))
    ov_genai_ver = str(config_stamp.get("openvino_genai_version", ""))
    nat = str(config_stamp.get("num_assistant_tokens", ""))
    draft_dir = str(config_stamp.get("draft_model_dir", ""))
    driver = str(config_stamp.get("driver_version", "*(fill manually)*"))
    prompt_ver = str(config_stamp.get("prompt_set_version", PROMPT_SET_VERSION))

    off_achieved_str = "off" if not spec_off_achieved else "on"
    on_achieved_str = "on" if spec_on_achieved else "off (fallback)"

    def _pp_row(p: PrefillStats | None) -> list[str]:
        if p is None or not p.measured:
            return []
        return [
            f"| Prefill pp (tok/s) | {p.mean_pp:.1f} | "
            f"{p.median_pp:.1f} | {p.p95_pp:.1f} |"
        ]

    off_pp_rows = _pp_row(spec_off_prefill)
    on_pp_rows = _pp_row(spec_on_prefill)
    _pp_src = (
        spec_off_prefill
        if spec_off_prefill is not None and spec_off_prefill.measured
        else (
            spec_on_prefill
            if spec_on_prefill is not None and spec_on_prefill.measured
            else None
        )
    )
    pp_note = (
        f"*Prefill (pp) measured over ~{_pp_src.mean_input_tokens:.0f} formatted "
        f"input tokens via a max_new_tokens=1 generation on probe "
        f"{PREFILL_PROBE_VERSION}; pp = input_tokens / prefill_time, comparable "
        f"to llama-bench pp512.* "
        if _pp_src is not None
        else ""
    )

    lines: list[str] = [
        f"### {timestamp[:10]}",
        "",
        f"**Date:** {timestamp[:10]}  ",
        f"**Triggered by:** *(fill in)*  ",
        f"**Benchmark script version:** `scripts/benchmark_gpu_inference.py` "
        f"(prompt-set {prompt_ver})  ",
        f"**Runs per config:** {num_runs} measured + {num_warmup} warmup  ",
        "",
        "#### Config stamp",
        "",
        "| Field | Value |",
        "|-------|-------|",
        f"| Model | `{model_name}` |",
        f"| Model dir | `{model_dir}` |",
        f"| Quantization | {quant} |",
        f"| Device | {device} |",
        f"| OpenVINO version | {ov_ver} |",
        f"| openvino-genai version | {ov_genai_ver} |",
        f"| num_assistant_tokens | {nat} |",
        f"| Draft model dir | `{draft_dir}` |",
        f"| Driver version | {driver} |",
        "",
        f"#### Results — speculative decoding OFF (achieved: {off_achieved_str})",
        "",
        "| Metric | mean | median | P95 |",
        "|--------|------|--------|-----|",
        f"| Throughput (tok/s) | {spec_off_stats.mean_tps:.1f} | "
        f"{spec_off_stats.median_tps:.1f} | {spec_off_stats.p95_tps:.1f} |",
        *off_pp_rows,
        f"| TTFT (ms) | {_fmt_ms(spec_off_stats.mean_ttft_ms)} | "
        f"{_fmt_ms(spec_off_stats.median_ttft_ms)} | {_fmt_ms(spec_off_stats.p95_ttft_ms)} |",
        f"| Total latency (ms) | {spec_off_stats.mean_total_ms:.0f} | "
        f"{spec_off_stats.median_total_ms:.0f} | {spec_off_stats.p95_total_ms:.0f} |",
        "",
        f"Model load time: {spec_off_load_ms:.0f} ms  ",
        f"Runs: {spec_off_stats.total_runs - spec_off_stats.error_runs} ok, "
        f"{spec_off_stats.error_runs} errors",
        "",
        f"#### Results — speculative decoding ON (achieved: {on_achieved_str})",
        "",
        "| Metric | mean | median | P95 |",
        "|--------|------|--------|-----|",
        f"| Throughput (tok/s) | {spec_on_stats.mean_tps:.1f} | "
        f"{spec_on_stats.median_tps:.1f} | {spec_on_stats.p95_tps:.1f} |",
        *on_pp_rows,
        f"| TTFT (ms) | {_fmt_ms(spec_on_stats.mean_ttft_ms)} | "
        f"{_fmt_ms(spec_on_stats.median_ttft_ms)} | {_fmt_ms(spec_on_stats.p95_ttft_ms)} |",
        f"| Total latency (ms) | {spec_on_stats.mean_total_ms:.0f} | "
        f"{spec_on_stats.median_total_ms:.0f} | {spec_on_stats.p95_total_ms:.0f} |",
        "",
        f"Model load time: {spec_on_load_ms:.0f} ms  ",
        f"Runs: {spec_on_stats.total_runs - spec_on_stats.error_runs} ok, "
        f"{spec_on_stats.error_runs} errors",
        "",
        f"**Notes:** {pp_note}*(add any observations here)*",
        "",
        "---",
        "",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Engine construction + benchmark runner
# ---------------------------------------------------------------------------


@dataclass
class ConfigSpec:
    """One benchmark configuration to run."""

    key: str
    label: str
    speculative_decoding_enabled: bool


_ALL_CONFIGS: list[ConfigSpec] = [
    ConfigSpec(
        key="spec_off",
        label="Speculative decoding OFF",
        speculative_decoding_enabled=False,
    ),
    ConfigSpec(
        key="spec_on",
        label="Speculative decoding ON",
        speculative_decoding_enabled=True,
    ),
]


def run_config(
    cfg: ConfigSpec,
    model_dir: str,
    draft_model_dir: str,
    num_warmup: int,
    num_runs: int,
    draft_device: str | None = None,
    run_cooldown: int = 0,
    enable_prefix_caching: bool = True,
    measure_pp: bool = True,
    phase_sink: list | None = None,
) -> tuple[float, bool, list[SingleRunMetrics], list[PrefillRunMetrics]]:
    """Load engine, warm up, measure, unload.

    ``phase_sink`` (opt-in, Session-2 single-model UT telemetry): when a list is
    passed, this records ``[name, t0_unix_s, t1_unix_s]`` boundaries around the
    measured-generation and prefill windows (epoch seconds, so they align with
    Intel UT socwatch samples). It is purely additive — it changes no measured
    number and is None for the comparable UT-free spine, so default behaviour is
    byte-identical to the baseline harness.

    Returns (load_ms, achieved, gen_runs, prefill_runs). ``prefill_runs`` is
    empty when ``measure_pp`` is False or the model failed to load.
    """
    print(f"\n{'=' * 68}")
    print(f"  Config: {cfg.label}")
    print(f"  speculative_decoding_enabled={cfg.speculative_decoding_enabled}")
    print(f"  enable_prefix_caching={enable_prefix_caching}")
    print(f"{'=' * 68}")

    print(f"  [LOAD] Loading model from {model_dir} ...")
    t_load_start = time.perf_counter()
    engine = OrchestratorGPUInference(
        model_dir=model_dir,
        device="GPU",
        draft_model_dir=draft_model_dir if draft_model_dir else None,
        speculative_decoding_enabled=cfg.speculative_decoding_enabled,
        draft_device=draft_device,
        enable_prefix_caching=enable_prefix_caching,
    )
    ok = engine.load_model()
    t_load_end = time.perf_counter()
    load_ms = (t_load_end - t_load_start) * 1000.0

    if not ok:
        print("  [LOAD] FAILED — model did not load.")
        return load_ms, False, [], []

    achieved = engine.speculative_decoding_active
    print(f"  [LOAD] Done in {load_ms:.0f} ms | speculative_decoding_active={achieved}")

    # Warmup — discarded
    if num_warmup > 0:
        print(f"  [WARMUP] {num_warmup} pass(es) over all {len(PROMPTS)} prompts ...")
        for w in range(num_warmup):
            for i, prompt in enumerate(PROMPTS):
                r = engine.generate_text(prompt=prompt, config=_GEN_CONFIG)
                if r.error:
                    print(f"    warmup pass {w + 1}, prompt {i}: {r.error}")
        print("  [WARMUP] Done.")

    # Measured runs
    print(
        f"  [BENCH] {num_runs} run(s) × {len(PROMPTS)} prompts "
        f"= {num_runs * len(PROMPTS)} total generations ..."
    )
    all_runs: list[SingleRunMetrics] = []
    _measured_t0 = time.time()
    for run_idx in range(num_runs):
        if run_idx > 0 and run_cooldown > 0:
            print(
                f"    [RUN-COOLDOWN] idling {run_cooldown}s so sustained load "
                f"does not thermally throttle the later runs ..."
            )
            time.sleep(run_cooldown)
        for p_idx, prompt in enumerate(PROMPTS):
            m = _measure_one(engine, prompt, p_idx)
            all_runs.append(m)
            if m.error:
                print(
                    f"    run {run_idx + 1}/{num_runs}, prompt {p_idx}: ERROR {m.error}"
                )
            else:
                print(
                    f"    run {run_idx + 1}/{num_runs}, prompt {p_idx}: "
                    f"{m.token_count} tok | "
                    f"tps={m.throughput_tok_per_sec:.1f} | "
                    f"ttft={_fmt_ms(m.latency_first_token_ms)}ms | "
                    f"total={m.latency_total_ms:.0f}ms"
                )

    if phase_sink is not None:
        phase_sink.append([f"{cfg.key}_measured", round(_measured_t0, 3), round(time.time(), 3)])

    # Streaming status — whether the stream callback delivered incremental
    # tokens. TTFT is only measurable when it did.
    stream_fired = any(r.latency_first_token_ms >= 0 for r in all_runs)
    print(
        f"  [STREAM] incremental token streaming: "
        f"{'yes' if stream_fired else 'NO -- callback never fired, TTFT not measured'}"
    )

    # Prompt-processing (prefill / pp) measurement — pp = input_tokens /
    # prefill_time over the fixed probe. Prefill is config-independent, so the
    # number should track across configs; per-config measurement is a cross-check.
    prefill_runs: list[PrefillRunMetrics] = []
    if measure_pp:
        print(f"  [PREFILL] {num_runs} pp probe run(s) (max_new_tokens=1) ...")
        _prefill_t0 = time.time()
        prefill_runs = measure_prefill(engine, num_runs, run_cooldown)
        if phase_sink is not None:
            phase_sink.append([f"{cfg.key}_prefill", round(_prefill_t0, 3), round(time.time(), 3)])
        pstats = aggregate_prefill(prefill_runs)
        if pstats.measured:
            print(
                f"  [PREFILL] pp tok/s: mean={pstats.mean_pp:.1f} "
                f"median={pstats.median_pp:.1f} P95={pstats.p95_pp:.1f} "
                f"(~{pstats.mean_input_tokens:.0f} input tokens)"
            )
        else:
            print("  [PREFILL] pp NOT measured (tokenizer unavailable / probe error).")

    engine.unload()
    return load_ms, achieved, all_runs, prefill_runs


# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------


def print_summary(
    label: str,
    stats: AggregateStats,
    load_ms: float,
    achieved: bool,
    prefill: PrefillStats | None = None,
) -> None:
    """Print a human-readable summary block for one config."""
    print(f"\n  --- {label} ---")
    print(f"  Speculative achieved : {achieved}")
    print(f"  Model load time      : {load_ms:.0f} ms")
    print(f"  Runs (ok/err)        : {stats.total_runs - stats.error_runs}/{stats.error_runs}")
    print(f"  Throughput (tok/s)   : mean={stats.mean_tps:.1f}  "
          f"median={stats.median_tps:.1f}  P95={stats.p95_tps:.1f}")
    if prefill is not None and prefill.measured:
        print(f"  Prefill pp (tok/s)   : mean={prefill.mean_pp:.1f}  "
              f"median={prefill.median_pp:.1f}  P95={prefill.p95_pp:.1f}  "
              f"(~{prefill.mean_input_tokens:.0f} input tok)")
    print(f"  TTFT (ms)            : mean={_fmt_ms(stats.mean_ttft_ms)}  "
          f"median={_fmt_ms(stats.median_ttft_ms)}  P95={_fmt_ms(stats.p95_ttft_ms)}")
    print(f"  Total latency (ms)   : mean={stats.mean_total_ms:.0f}  "
          f"median={stats.median_total_ms:.0f}  P95={stats.p95_total_ms:.0f}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> int:  # noqa: PLR0912, PLR0915
    parser = argparse.ArgumentParser(
        description=(
            "BlarAI GPU inference benchmark — Qwen3-14B INT4 via OrchestratorGPUInference. "
            "Runs spec-off and spec-on configs; outputs JSON + Markdown entry."
        )
    )
    parser.add_argument(
        "--model-dir",
        default=str(_REPO_ROOT / TARGET_MODEL_OV_PATH),
        help="Path to the main model directory (default: repo-relative TARGET_MODEL_OV_PATH).",
    )
    parser.add_argument(
        "--model-name",
        default=None,
        help="Human model name for the config stamp / output filename "
        "(default: derived from the model dir, e.g. 'qwen3-8b'). Prevents the "
        "old hardcoded 'Qwen3-14B' label on non-14B runs.",
    )
    parser.add_argument(
        "--draft-model-dir",
        default=str(_REPO_ROOT / DRAFT_MODEL_OV_PATH),
        help="Path to the draft model directory for speculative decoding.",
    )
    parser.add_argument(
        "--draft-device",
        default=None,
        help="Device for the speculative draft model (e.g. NPU). "
        "Default: same device as the target (GPU).",
    )
    parser.add_argument(
        "--runs",
        type=int,
        default=5,
        help="Number of measured runs per config (default: 5).",
    )
    parser.add_argument(
        "--warmup",
        type=int,
        default=2,
        help="Number of warmup runs per config, discarded (default: 2).",
    )
    parser.add_argument(
        "--configs",
        default="both",
        choices=["both", "spec_off", "spec_on"],
        help="Which configs to run: both (default), spec_off, or spec_on.",
    )
    parser.add_argument(
        "--cooldown",
        type=int,
        default=90,
        help="Seconds to idle between configs so the GPU returns toward a "
        "common thermal baseline (default: 90). Prevents the second config "
        "from being measured on a hotter GPU than the first.",
    )
    parser.add_argument(
        "--run-cooldown",
        type=int,
        default=0,
        help="Seconds to idle between each measured run within a config "
        "(default: 0). A sustained burst of runs heats an integrated GPU "
        "enough to throttle the later ones; set this (e.g. 30) for a "
        "thermally-clean sustained measurement.",
    )
    parser.add_argument(
        "--prefix-caching",
        default="on",
        choices=["on", "off"],
        help="OV GenAI SchedulerConfig.enable_prefix_caching (default: on, "
        "matches current AO production behaviour). Set to 'off' to reproduce "
        "ADR-012 DEC-06 baseline. Used for the Phase 0 prefix-caching "
        "re-check on OV GenAI 2026.1+.",
    )
    parser.add_argument(
        "--prefill",
        default="on",
        choices=["on", "off"],
        help="Measure prompt-processing (pp / prefill) throughput in tok/s "
        "(default: on) — comparable to llama-bench pp512. Set 'off' to skip "
        "the prefill probe and only measure generation + TTFT.",
    )
    parser.add_argument(
        "--emit-phases",
        default=None,
        help="Opt-in (Session-2 single-model UT telemetry): write Unix-epoch "
        "phase boundaries [[name, t0, t1], ...] to this path for "
        "extract_ut_metrics.py --phases. Off by default — the comparable "
        "UT-free spine run is byte-identical without it. Used by "
        "capture_single_ut.ps1 to segment per-phase GPU power/freq/busy.",
    )
    args = parser.parse_args()

    # Select configs
    if args.configs == "both":
        configs_to_run = _ALL_CONFIGS
    elif args.configs == "spec_off":
        configs_to_run = [c for c in _ALL_CONFIGS if c.key == "spec_off"]
    else:
        configs_to_run = [c for c in _ALL_CONFIGS if c.key == "spec_on"]

    model_dir = str(Path(args.model_dir).resolve())
    draft_model_dir = str(Path(args.draft_model_dir).resolve())
    model_name = args.model_name or _derive_model_name(model_dir)
    timestamp = time.strftime("%Y-%m-%dT%H:%M:%S")

    print("=" * 68)
    print("  BlarAI GPU Inference Benchmark")
    print(f"  Timestamp         : {timestamp}")
    print(f"  OpenVINO          : {_OV_VERSION}")
    print(f"  openvino-genai    : {_OV_GENAI_VERSION}")
    print(f"  Model name        : {model_name}")
    print(f"  Model dir         : {model_dir}")
    print(f"  Draft model dir   : {draft_model_dir}")
    print(f"  Draft device      : {args.draft_device or 'GPU (same as target)'}")
    print(f"  Prompt set        : {PROMPT_SET_VERSION} ({len(PROMPTS)} prompts)")
    print(f"  Runs / warmup     : {args.runs} / {args.warmup}")
    print(f"  Run cooldown      : {args.run_cooldown}s")
    print(f"  num_assistant_tokens: {NUM_ASSISTANT_TOKENS}")
    print("=" * 68)

    # Verify model path
    model_xml = Path(model_dir) / "openvino_model.xml"
    if not model_xml.exists():
        print(f"\nFATAL: Model not found at {model_dir}")
        print("  Expected: openvino_model.xml / openvino_model.bin")
        return 1

    enable_prefix_caching = args.prefix_caching == "on"
    measure_pp = args.prefill == "on"

    # Build config stamp (shared between JSON + MD)
    config_stamp: dict[str, object] = {
        "timestamp": timestamp,
        "model_name": model_name,
        "model_dir": model_dir,
        "quantization": "INT4",
        "device": "GPU",
        "openvino_version": _OV_VERSION,
        "openvino_genai_version": _OV_GENAI_VERSION,
        "num_assistant_tokens": NUM_ASSISTANT_TOKENS,
        "draft_model_dir": draft_model_dir,
        "driver_version": "",
        "prompt_set_version": PROMPT_SET_VERSION,
        "prefill_probe_version": PREFILL_PROBE_VERSION,
        "measure_prefill": measure_pp,
        "num_runs": args.runs,
        "num_warmup": args.warmup,
        "run_cooldown_s": args.run_cooldown,
        "enable_prefix_caching": enable_prefix_caching,
    }

    # Opt-in single-model UT telemetry: collect per-phase Unix-epoch boundaries.
    phase_log: list | None = [] if args.emit_phases else None

    # Run each config
    results: dict[str, dict[str, object]] = {}
    spec_off_stats: AggregateStats | None = None
    spec_off_load_ms: float = 0.0
    spec_off_achieved: bool = False
    spec_off_prefill: PrefillStats | None = None
    spec_on_stats: AggregateStats | None = None
    spec_on_load_ms: float = 0.0
    spec_on_achieved: bool = False
    spec_on_prefill: PrefillStats | None = None

    for cfg_index, cfg in enumerate(configs_to_run):
        if cfg_index > 0 and args.cooldown > 0:
            print(
                f"\n  [COOLDOWN] idling {args.cooldown}s so the GPU returns "
                f"toward a common thermal baseline before the next config ..."
            )
            time.sleep(args.cooldown)
        load_ms, achieved, runs, prefill_runs = run_config(
            cfg=cfg,
            model_dir=model_dir,
            draft_model_dir=draft_model_dir,
            num_warmup=args.warmup,
            num_runs=args.runs,
            draft_device=args.draft_device,
            run_cooldown=args.run_cooldown,
            enable_prefix_caching=enable_prefix_caching,
            measure_pp=measure_pp,
            phase_sink=phase_log,
        )
        stats = aggregate(runs)
        prefill_stats = aggregate_prefill(prefill_runs)
        results[cfg.key] = {
            "config": cfg.label,
            "speculative_decoding_requested": cfg.speculative_decoding_enabled,
            "speculative_decoding_achieved": achieved,
            "load_ms": round(load_ms, 1),
            "aggregate": {
                "mean_tps": round(stats.mean_tps, 2),
                "median_tps": round(stats.median_tps, 2),
                "p95_tps": round(stats.p95_tps, 2),
                "mean_ttft_ms": round(stats.mean_ttft_ms, 1),
                "median_ttft_ms": round(stats.median_ttft_ms, 1),
                "p95_ttft_ms": round(stats.p95_ttft_ms, 1),
                "mean_total_ms": round(stats.mean_total_ms, 1),
                "median_total_ms": round(stats.median_total_ms, 1),
                "p95_total_ms": round(stats.p95_total_ms, 1),
                "total_runs": stats.total_runs,
                "error_runs": stats.error_runs,
            },
            "raw_runs": [
                {
                    "prompt_index": r.prompt_index,
                    "token_count": r.token_count,
                    "latency_first_token_ms": round(r.latency_first_token_ms, 1),
                    "latency_total_ms": round(r.latency_total_ms, 1),
                    "throughput_tok_per_sec": round(r.throughput_tok_per_sec, 2),
                    "error": r.error,
                }
                for r in runs
            ],
            "prefill": {
                "measured": prefill_stats.measured,
                "mean_pp": round(prefill_stats.mean_pp, 2),
                "median_pp": round(prefill_stats.median_pp, 2),
                "p95_pp": round(prefill_stats.p95_pp, 2),
                "mean_input_tokens": round(prefill_stats.mean_input_tokens, 1),
                "probe_version": PREFILL_PROBE_VERSION,
                "total_runs": prefill_stats.total_runs,
                "error_runs": prefill_stats.error_runs,
                "raw_runs": [
                    {
                        "input_tokens": pr.input_tokens,
                        "prefill_ms": round(pr.prefill_ms, 1),
                        "prefill_tok_per_sec": round(pr.prefill_tok_per_sec, 2),
                        "error": pr.error,
                    }
                    for pr in prefill_runs
                ],
            },
        }

        if cfg.key == "spec_off":
            spec_off_stats = stats
            spec_off_load_ms = load_ms
            spec_off_achieved = achieved
            spec_off_prefill = prefill_stats
        elif cfg.key == "spec_on":
            spec_on_stats = stats
            spec_on_load_ms = load_ms
            spec_on_achieved = achieved
            spec_on_prefill = prefill_stats

    # Human-readable summary
    print(f"\n\n{'=' * 68}")
    print("  BENCHMARK SUMMARY")
    print(f"{'=' * 68}")
    if spec_off_stats is not None:
        print_summary(
            "Spec OFF", spec_off_stats, spec_off_load_ms, spec_off_achieved, spec_off_prefill
        )
    if spec_on_stats is not None:
        print_summary(
            "Spec ON", spec_on_stats, spec_on_load_ms, spec_on_achieved, spec_on_prefill
        )

    # JSON output
    output_dir = _REPO_ROOT / "docs" / "performance"
    output_dir.mkdir(parents=True, exist_ok=True)
    ts_file = timestamp.replace(":", "-").replace("T", "_")
    json_path = output_dir / f"benchmark_{ts_file}.json"

    evidence: dict[str, object] = {
        "benchmark": f"gpu_inference_{model_name}",
        "config_stamp": config_stamp,
        "results": results,
        "prompts": {
            "version": PROMPT_SET_VERSION,
            "texts": PROMPTS,
        },
    }
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(evidence, f, indent=2)
    print(f"\n[SAVE] JSON results -> {json_path}")

    # Opt-in: write the per-phase Unix-epoch boundaries for UT segmentation.
    if args.emit_phases and phase_log is not None:
        with open(args.emit_phases, "w", encoding="utf-8") as f:
            json.dump(phase_log, f, indent=2)
        print(f"[SAVE] UT phase boundaries -> {args.emit_phases} ({len(phase_log)} phases)")

    # Markdown entry
    # Build placeholder stats for any configs that weren't run.
    _empty = AggregateStats(
        mean_tps=0.0,
        median_tps=0.0,
        p95_tps=0.0,
        mean_ttft_ms=0.0,
        median_ttft_ms=0.0,
        p95_ttft_ms=0.0,
        mean_total_ms=0.0,
        median_total_ms=0.0,
        p95_total_ms=0.0,
        total_runs=0,
        error_runs=0,
    )
    md_entry = format_markdown_entry(
        timestamp=timestamp,
        config_stamp=config_stamp,
        spec_off_stats=spec_off_stats if spec_off_stats is not None else _empty,
        spec_off_load_ms=spec_off_load_ms,
        spec_on_stats=spec_on_stats if spec_on_stats is not None else _empty,
        spec_on_load_ms=spec_on_load_ms,
        spec_off_achieved=spec_off_achieved,
        spec_on_achieved=spec_on_achieved,
        num_runs=args.runs,
        num_warmup=args.warmup,
        spec_off_prefill=spec_off_prefill,
        spec_on_prefill=spec_on_prefill,
    )

    print(f"\n{'=' * 68}")
    print("  PERFORMANCE_LOG.md ENTRY (paste into PERFORMANCE_LOG.md)")
    print(f"{'=' * 68}\n")
    print(md_entry)

    return 0


if __name__ == "__main__":
    sys.exit(main())
