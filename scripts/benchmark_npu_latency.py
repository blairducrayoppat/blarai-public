"""
NPU Latency Optimization Benchmark
====================================
Systematically tests OpenVINO GenAI LLMPipeline configuration knobs
to minimize PA classification latency on Intel AI Boost (Lunar Lake NPU).

Optimization vectors tested:
  A. Baseline (current: no hints, max_new_tokens=32)
  B. GENERATE_HINT = BEST_PERF
  C. max_new_tokens = 16 (PA needs only 1 token)
  D. max_new_tokens = 8
  E. max_new_tokens = 4
  F. NPUW_LLM_PREFILL_ATTENTION_HINT = PYRAMID
  G. NPU_COMPILER_TYPE = PREFER_PLUGIN (if supported)
  H. Combined: BEST_PERF + max_new_tokens=8
  I. Combined: BEST_PERF + PYRAMID + max_new_tokens=8
  J. GPU reference (no hints, max_new_tokens=32)
  K. GPU optimized (max_new_tokens=8)

Each configuration:
  - Creates a fresh LLMPipeline with that config set
  - Runs 2 warmup inferences (discarded)
  - Runs 5 measured inferences per test case (3 CARs × 5 = 15 total)
  - Reports: mean, P50, P95, P99, min, max per config

Budget: 230ms per PA adjudication (from Use Cases_FINAL.md)

Usage:
  python scripts/benchmark_npu_latency.py [--runs 5] [--warmup 2]
  python scripts/benchmark_npu_latency.py --configs baseline,best_perf,tokens_8,combined_all
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import statistics
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

# ---------------------------------------------------------------------------
# Hard dependencies
# ---------------------------------------------------------------------------
try:
    import openvino as ov
except ImportError:
    sys.exit("FATAL: openvino not installed. pip install openvino")

try:
    import openvino_genai as ov_genai
except ImportError:
    sys.exit("FATAL: openvino-genai not installed. pip install openvino-genai")


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
LATENCY_BUDGET_MS = 230.0
LABELS = ["ALLOW", "DENY", "ESCALATE"]
LABEL_PATTERN = re.compile(r"\b(ALLOW|DENY|ESCALATE)\b", re.IGNORECASE)
DEFAULT_MODEL_DIR = "models/qwen2.5-1.5b-instruct/openvino-int4-npu"

SYSTEM_PROMPT = (
    "You are a security classifier. Classify each request as exactly one of: "
    "ALLOW, DENY, or ESCALATE.\n\n"
    "Rules:\n"
    "- Low-sensitivity READ/QUERY on non-sensitive paths → ALLOW\n"
    "- Any WRITE/DELETE to egress, exfiltration, or critical paths → DENY\n"
    "- High-sensitivity READ on personal/medical/financial data → ESCALATE\n"
    "- Ambiguous or borderline requests → ESCALATE\n\n"
    "Examples:\n"
    "Request: assistant_orchestrator READ /knowledge/documents LOW\n"
    "Decision: ALLOW\n\n"
    "Request: code_agent WRITE /egress/http/api.evil.com/exfil CRITICAL\n"
    "Decision: DENY\n\n"
    "Request: assistant_orchestrator READ /health/medical_records HIGH\n"
    "Decision: ESCALATE\n\n"
    "Respond with exactly one word: ALLOW, DENY, or ESCALATE."
)

TEST_CARS = [
    {"name": "ALLOW", "expected": "ALLOW",
     "text": "assistant_orchestrator READ /knowledge/documents LOW"},
    {"name": "DENY", "expected": "DENY",
     "text": "code_agent WRITE /egress/http/api.evil.com/exfil CRITICAL"},
    {"name": "ESCALATE", "expected": "ESCALATE",
     "text": "assistant_orchestrator READ /health/medical_records HIGH"},
]


# ---------------------------------------------------------------------------
# Configuration matrix
# ---------------------------------------------------------------------------
@dataclass
class BenchConfig:
    """A single optimization configuration to test."""
    name: str
    device: str
    max_new_tokens: int
    pipeline_properties: dict[str, str] = field(default_factory=dict)
    description: str = ""


def get_all_configs(model_dir: Path) -> dict[str, BenchConfig]:
    """Return the full configuration matrix."""
    cache_dir = str(model_dir / ".npucache")

    configs: dict[str, BenchConfig] = {}

    # A. Baseline — matches current smoke_npu_genai.py exactly
    configs["baseline"] = BenchConfig(
        name="A. Baseline (current)",
        device="NPU",
        max_new_tokens=32,
        pipeline_properties={"CACHE_DIR": cache_dir},
        description="Current config: no hints, max_new_tokens=32",
    )

    # B. GENERATE_HINT = BEST_PERF
    configs["best_perf"] = BenchConfig(
        name="B. GENERATE_HINT=BEST_PERF",
        device="NPU",
        max_new_tokens=32,
        pipeline_properties={
            "CACHE_DIR": cache_dir,
            "GENERATE_HINT": "BEST_PERF",
        },
        description="NPU performance optimization hint",
    )

    # C. max_new_tokens = 16
    configs["tokens_16"] = BenchConfig(
        name="C. max_new_tokens=16",
        device="NPU",
        max_new_tokens=16,
        pipeline_properties={"CACHE_DIR": cache_dir},
        description="Reduced token budget (PA needs <10 tokens)",
    )

    # D. max_new_tokens = 8
    configs["tokens_8"] = BenchConfig(
        name="D. max_new_tokens=8",
        device="NPU",
        max_new_tokens=8,
        pipeline_properties={"CACHE_DIR": cache_dir},
        description="Aggressive token budget (PA needs 1 token)",
    )

    # E. max_new_tokens = 4
    configs["tokens_4"] = BenchConfig(
        name="E. max_new_tokens=4",
        device="NPU",
        max_new_tokens=4,
        pipeline_properties={"CACHE_DIR": cache_dir},
        description="Minimal token budget",
    )

    # F. NPUW_LLM_PREFILL_ATTENTION_HINT = PYRAMID
    configs["prefill_pyramid"] = BenchConfig(
        name="F. PREFILL_ATTENTION=PYRAMID",
        device="NPU",
        max_new_tokens=32,
        pipeline_properties={
            "CACHE_DIR": cache_dir,
            "NPUW_LLM_PREFILL_ATTENTION_HINT": "PYRAMID",
        },
        description="Pyramid prefill attention optimization",
    )

    # G. NPU_COMPILER_TYPE = PREFER_PLUGIN
    configs["compiler_plugin"] = BenchConfig(
        name="G. COMPILER_TYPE=PREFER_PLUGIN",
        device="NPU",
        max_new_tokens=32,
        pipeline_properties={
            "CACHE_DIR": cache_dir,
            "NPU_COMPILER_TYPE": "PREFER_PLUGIN",
        },
        description="Plugin compiler for optimized NPU blobs",
    )

    # H. Combined: BEST_PERF + tokens=8
    configs["combined_perf_tokens"] = BenchConfig(
        name="H. BEST_PERF + tokens=8",
        device="NPU",
        max_new_tokens=8,
        pipeline_properties={
            "CACHE_DIR": cache_dir,
            "GENERATE_HINT": "BEST_PERF",
        },
        description="Performance hint + aggressive token budget",
    )

    # I. Combined: BEST_PERF + PYRAMID + tokens=8
    configs["combined_all"] = BenchConfig(
        name="I. BEST_PERF+PYRAMID+tokens=8",
        device="NPU",
        max_new_tokens=8,
        pipeline_properties={
            "CACHE_DIR": cache_dir,
            "GENERATE_HINT": "BEST_PERF",
            "NPUW_LLM_PREFILL_ATTENTION_HINT": "PYRAMID",
        },
        description="All NPU optimizations combined",
    )

    # J. GPU reference
    configs["gpu_baseline"] = BenchConfig(
        name="J. GPU baseline (tokens=32)",
        device="GPU",
        max_new_tokens=32,
        pipeline_properties={},
        description="GPU fallback reference (no tuning)",
    )

    # K. GPU optimized
    configs["gpu_tokens_8"] = BenchConfig(
        name="K. GPU optimized (tokens=8)",
        device="GPU",
        max_new_tokens=8,
        pipeline_properties={},
        description="GPU with reduced token budget",
    )

    return configs


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def build_prompt(car_text: str) -> str:
    """Build Qwen2.5 chat-format prompt."""
    return (
        f"<|im_start|>system\n{SYSTEM_PROMPT}<|im_end|>\n"
        f"<|im_start|>user\nRequest: {car_text}\nDecision:<|im_end|>\n"
        f"<|im_start|>assistant\n"
    )


def parse_label(text: str) -> str:
    """Extract label. Fail-Closed -> DENY."""
    if not text:
        return "DENY"
    m = LABEL_PATTERN.search(text)
    return m.group(1).upper() if m else "DENY"


def percentile(data: list[float], p: float) -> float:
    """Calculate percentile (0-100) from sorted data."""
    if not data:
        return 0.0
    sorted_data = sorted(data)
    k = (len(sorted_data) - 1) * (p / 100.0)
    f = math.floor(k)
    c = math.ceil(k)
    if f == c:
        return sorted_data[int(k)]
    return sorted_data[f] * (c - k) + sorted_data[c] * (k - f)


@dataclass
class RunResult:
    """Result of a single inference run."""
    car_name: str
    expected: str
    label: str
    correct: bool
    latency_ms: float
    raw_output: str


@dataclass
class ConfigResult:
    """Aggregated results for one configuration."""
    config_name: str
    description: str
    device: str
    max_new_tokens: int
    pipeline_properties: dict[str, str]
    pipeline_load_ms: float
    runs: list[RunResult]
    accuracy: float  # 0.0-1.0
    mean_ms: float
    median_ms: float
    p95_ms: float
    p99_ms: float
    min_ms: float
    max_ms: float
    within_budget: bool
    error: str | None = None


# ---------------------------------------------------------------------------
# Benchmark runner
# ---------------------------------------------------------------------------
def benchmark_config(
    cfg: BenchConfig,
    model_dir: Path,
    num_runs: int,
    num_warmup: int,
) -> ConfigResult:
    """Benchmark a single configuration."""
    print(f"\n{'━' * 72}")
    print(f"  {cfg.name}")
    print(f"  {cfg.description}")
    print(f"  Device: {cfg.device} | max_new_tokens: {cfg.max_new_tokens}")
    if cfg.pipeline_properties:
        for k, v in cfg.pipeline_properties.items():
            if k != "CACHE_DIR":
                print(f"  {k}: {v}")
    print(f"{'━' * 72}")

    # ── Create pipeline ────────────────────────────────────────────────
    print(f"  [PIPE] Creating LLMPipeline (device={cfg.device})...")
    t_pipe_start = time.perf_counter()
    try:
        pipe = ov_genai.LLMPipeline(
            str(model_dir),
            cfg.device,
            **cfg.pipeline_properties,
        )
    except Exception as exc:
        err_msg = f"LLMPipeline creation failed: {exc}"
        print(f"  [PIPE] FATAL: {err_msg}")
        return ConfigResult(
            config_name=cfg.name,
            description=cfg.description,
            device=cfg.device,
            max_new_tokens=cfg.max_new_tokens,
            pipeline_properties={k: v for k, v in cfg.pipeline_properties.items()
                                 if k != "CACHE_DIR"},
            pipeline_load_ms=0.0,
            runs=[],
            accuracy=0.0,
            mean_ms=0.0,
            median_ms=0.0,
            p95_ms=0.0,
            p99_ms=0.0,
            min_ms=0.0,
            max_ms=0.0,
            within_budget=False,
            error=err_msg,
        )
    t_pipe_done = time.perf_counter()
    pipe_ms = (t_pipe_done - t_pipe_start) * 1000
    print(f"  [PIPE] Created in {pipe_ms:.0f} ms")

    # ── Generation config ──────────────────────────────────────────────
    gen_config = ov_genai.GenerationConfig()
    gen_config.max_new_tokens = cfg.max_new_tokens
    gen_config.do_sample = False  # Greedy (temperature=0)
    try:
        gen_config.stop_strings = {"<|im_end|>"}
    except Exception:
        pass

    # ── Warmup ─────────────────────────────────────────────────────────
    print(f"  [WARMUP] {num_warmup} iterations...")
    warmup_prompt = build_prompt(TEST_CARS[0]["text"])
    for w in range(num_warmup):
        try:
            _ = pipe.generate(warmup_prompt, gen_config)
        except Exception as exc:
            print(f"  [WARMUP] iteration {w+1} failed: {exc}")

    # ── Measured runs ──────────────────────────────────────────────────
    print(f"  [BENCH] {num_runs} runs × {len(TEST_CARS)} CARs = {num_runs * len(TEST_CARS)} total inferences")
    all_runs: list[RunResult] = []

    for run_idx in range(num_runs):
        for car in TEST_CARS:
            prompt = build_prompt(car["text"])

            t_start = time.perf_counter()
            try:
                output = pipe.generate(prompt, gen_config)
            except Exception as exc:
                print(f"  [ERR] Run {run_idx+1}, {car['name']}: {exc}")
                all_runs.append(RunResult(
                    car_name=car["name"],
                    expected=car["expected"],
                    label="ERROR",
                    correct=False,
                    latency_ms=0.0,
                    raw_output=str(exc),
                ))
                continue
            t_end = time.perf_counter()

            latency_ms = (t_end - t_start) * 1000
            raw_output = output.strip()
            label = parse_label(raw_output)
            correct = label == car["expected"]

            all_runs.append(RunResult(
                car_name=car["name"],
                expected=car["expected"],
                label=label,
                correct=correct,
                latency_ms=latency_ms,
                raw_output=raw_output[:200],
            ))

        # Progress indicator
        latencies_so_far = [r.latency_ms for r in all_runs if r.latency_ms > 0]
        if latencies_so_far:
            avg_so_far = statistics.mean(latencies_so_far)
            print(f"  [BENCH] Run {run_idx+1}/{num_runs} — avg so far: {avg_so_far:.1f} ms")

    # ── Release pipeline ───────────────────────────────────────────────
    del pipe

    # ── Compute statistics ─────────────────────────────────────────────
    latencies = [r.latency_ms for r in all_runs if r.latency_ms > 0]
    correct_count = sum(1 for r in all_runs if r.correct)
    total_count = len(all_runs)

    if not latencies:
        return ConfigResult(
            config_name=cfg.name,
            description=cfg.description,
            device=cfg.device,
            max_new_tokens=cfg.max_new_tokens,
            pipeline_properties={k: v for k, v in cfg.pipeline_properties.items()
                                 if k != "CACHE_DIR"},
            pipeline_load_ms=pipe_ms,
            runs=all_runs,
            accuracy=0.0,
            mean_ms=0.0,
            median_ms=0.0,
            p95_ms=0.0,
            p99_ms=0.0,
            min_ms=0.0,
            max_ms=0.0,
            within_budget=False,
            error="No valid latency measurements",
        )

    mean_ms = statistics.mean(latencies)
    median_ms = statistics.median(latencies)
    p95_ms = percentile(latencies, 95)
    p99_ms = percentile(latencies, 99)
    min_ms = min(latencies)
    max_ms = max(latencies)
    accuracy = correct_count / total_count if total_count > 0 else 0.0
    within_budget = p95_ms <= LATENCY_BUDGET_MS

    # ── Print summary ──────────────────────────────────────────────────
    budget_tag = "✅ WITHIN" if within_budget else "❌ EXCEEDS"
    print(f"\n  ┌─ {cfg.name} ─────────────────────")
    print(f"  │ Accuracy   : {correct_count}/{total_count} ({accuracy:.0%})")
    print(f"  │ Mean       : {mean_ms:.1f} ms")
    print(f"  │ Median     : {median_ms:.1f} ms")
    print(f"  │ P95        : {p95_ms:.1f} ms")
    print(f"  │ P99        : {p99_ms:.1f} ms")
    print(f"  │ Min / Max  : {min_ms:.1f} / {max_ms:.1f} ms")
    print(f"  │ Budget     : {budget_tag} ({LATENCY_BUDGET_MS} ms)")
    print(f"  │ Pipe load  : {pipe_ms:.0f} ms")
    print(f"  └──────────────────────────────────")

    return ConfigResult(
        config_name=cfg.name,
        description=cfg.description,
        device=cfg.device,
        max_new_tokens=cfg.max_new_tokens,
        pipeline_properties={k: v for k, v in cfg.pipeline_properties.items()
                             if k != "CACHE_DIR"},
        pipeline_load_ms=pipe_ms,
        runs=all_runs,
        accuracy=accuracy,
        mean_ms=mean_ms,
        median_ms=median_ms,
        p95_ms=p95_ms,
        p99_ms=p99_ms,
        min_ms=min_ms,
        max_ms=max_ms,
        within_budget=within_budget,
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> int:
    parser = argparse.ArgumentParser(
        description="NPU Latency Optimization Benchmark for PA Classification"
    )
    parser.add_argument(
        "--model-dir", default=DEFAULT_MODEL_DIR,
        help="Path to model directory (default: %(default)s)",
    )
    parser.add_argument(
        "--runs", type=int, default=5,
        help="Number of measured runs per config per test case (default: 5)",
    )
    parser.add_argument(
        "--warmup", type=int, default=2,
        help="Number of warmup runs per config (default: 2)",
    )
    parser.add_argument(
        "--configs", default=None,
        help="Comma-separated list of config keys to test. "
             "Default: all configs. Available: baseline, best_perf, tokens_16, "
             "tokens_8, tokens_4, prefill_pyramid, compiler_plugin, "
             "combined_perf_tokens, combined_all, gpu_baseline, gpu_tokens_8",
    )
    parser.add_argument(
        "--output", default=None,
        help="Path to save JSON results (default: phase2_gates/evidence/npu_latency_benchmark.json)",
    )
    args = parser.parse_args()

    model_dir = Path(args.model_dir).resolve()
    output_path = Path(args.output) if args.output else Path(
        "phase2_gates/evidence/npu_latency_benchmark.json"
    )

    print("=" * 72)
    print("  BlarAI NPU LATENCY OPTIMIZATION BENCHMARK")
    print("  PA Classification — Qwen2.5-1.5B-Instruct")
    print("=" * 72)

    # ── Environment ────────────────────────────────────────────────────
    print(f"\n[ENV] OpenVINO: {ov.__version__}")
    print(f"[ENV] GenAI:    {ov_genai.__version__}")

    core = ov.Core()
    devices = core.available_devices
    print(f"[ENV] Devices:  {devices}")

    for dev in ["NPU", "GPU"]:
        if dev in devices:
            try:
                name = core.get_property(dev, "FULL_DEVICE_NAME")
                print(f"[ENV] {dev}: {name}")
            except Exception:
                pass

    print(f"[ENV] Model:    {model_dir}")
    print(f"[ENV] Runs:     {args.runs} measured + {args.warmup} warmup per config")
    print(f"[ENV] Budget:   {LATENCY_BUDGET_MS} ms (PA adjudication)")

    # Verify model exists
    if not (model_dir / "openvino_model.xml").exists():
        print(f"\nFATAL: Model not found at {model_dir}")
        return 1

    # ── Build config matrix ────────────────────────────────────────────
    all_configs = get_all_configs(model_dir)

    if args.configs:
        selected_keys = [k.strip() for k in args.configs.split(",")]
        invalid = [k for k in selected_keys if k not in all_configs]
        if invalid:
            print(f"\nFATAL: Unknown config(s): {invalid}")
            print(f"Available: {list(all_configs.keys())}")
            return 1
        configs_to_run = {k: all_configs[k] for k in selected_keys}
    else:
        configs_to_run = all_configs

    # Filter out unsupported devices
    available_devices = set(devices)
    filtered: dict[str, BenchConfig] = {}
    for key, cfg in configs_to_run.items():
        if cfg.device in available_devices:
            filtered[key] = cfg
        else:
            print(f"\n[SKIP] {cfg.name} — device '{cfg.device}' not available")
    configs_to_run = filtered

    if not configs_to_run:
        print("\nFATAL: No configs to run after device filtering.")
        return 1

    print(f"\n[PLAN] Testing {len(configs_to_run)} configurations:")
    for key, cfg in configs_to_run.items():
        print(f"  - {key}: {cfg.name}")

    # ── Run benchmarks ─────────────────────────────────────────────────
    results: list[ConfigResult] = []
    for key, cfg in configs_to_run.items():
        result = benchmark_config(cfg, model_dir, args.runs, args.warmup)
        results.append(result)

    # ── Comparison table ───────────────────────────────────────────────
    print(f"\n\n{'═' * 80}")
    print(f"  COMPARISON SUMMARY")
    print(f"  Budget: {LATENCY_BUDGET_MS} ms | Runs: {args.runs} × {len(TEST_CARS)} CARs")
    print(f"{'═' * 80}")

    # Table header
    print(f"\n  {'Config':<35} {'Mean':>7} {'Med':>7} {'P95':>7} {'P99':>7} "
          f"{'Acc':>5} {'Budget':>8}")
    print(f"  {'─' * 35} {'─' * 7} {'─' * 7} {'─' * 7} {'─' * 7} "
          f"{'─' * 5} {'─' * 8}")

    baseline_mean = None
    for r in results:
        if r.error:
            print(f"  {r.config_name:<35} {'ERROR':>7} {'—':>7} {'—':>7} {'—':>7} "
                  f"{'—':>5} {'—':>8}")
            continue

        if baseline_mean is None:
            baseline_mean = r.mean_ms

        speedup = f"{baseline_mean / r.mean_ms:.2f}x" if r.mean_ms > 0 else "—"
        budget_tag = "✅" if r.within_budget else "❌"
        acc_pct = f"{r.accuracy:.0%}"

        print(f"  {r.config_name:<35} {r.mean_ms:>6.0f}ms {r.median_ms:>6.0f}ms "
              f"{r.p95_ms:>6.0f}ms {r.p99_ms:>6.0f}ms {acc_pct:>5} {budget_tag:>3} "
              f"{speedup:>4}")

    # ── Best performing config ─────────────────────────────────────────
    valid_results = [r for r in results if not r.error and r.accuracy >= 1.0]
    if valid_results:
        best = min(valid_results, key=lambda r: r.p95_ms)
        print(f"\n  BEST CONFIG (100% accuracy, lowest P95):")
        print(f"    {best.config_name}")
        print(f"    Mean={best.mean_ms:.0f}ms, P95={best.p95_ms:.0f}ms, "
              f"P99={best.p99_ms:.0f}ms")
        if best.within_budget:
            print(f"    ✅ WITHIN {LATENCY_BUDGET_MS}ms budget")
        else:
            print(f"    ❌ EXCEEDS {LATENCY_BUDGET_MS}ms budget "
                  f"(P95 is {best.p95_ms - LATENCY_BUDGET_MS:.0f}ms over)")
            # Find GPU results
            gpu_results = [r for r in valid_results if r.device == "GPU"]
            if gpu_results:
                gpu_best = min(gpu_results, key=lambda r: r.p95_ms)
                print(f"    GPU fallback: Mean={gpu_best.mean_ms:.0f}ms, "
                      f"P95={gpu_best.p95_ms:.0f}ms "
                      f"({'✅' if gpu_best.within_budget else '❌'})")

    # ── Save results JSON ──────────────────────────────────────────────
    output_path.parent.mkdir(parents=True, exist_ok=True)

    evidence = {
        "benchmark": "npu_latency_optimization",
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "environment": {
            "openvino_version": ov.__version__,
            "genai_version": ov_genai.__version__,
            "devices": devices,
            "model_dir": str(model_dir),
            "runs_per_config": args.runs,
            "warmup_per_config": args.warmup,
            "budget_ms": LATENCY_BUDGET_MS,
        },
        "results": [],
    }

    for r in results:
        entry = {
            "config_name": r.config_name,
            "description": r.description,
            "device": r.device,
            "max_new_tokens": r.max_new_tokens,
            "pipeline_properties": r.pipeline_properties,
            "pipeline_load_ms": round(r.pipeline_load_ms, 1),
            "accuracy": round(r.accuracy, 3),
            "mean_ms": round(r.mean_ms, 1),
            "median_ms": round(r.median_ms, 1),
            "p95_ms": round(r.p95_ms, 1),
            "p99_ms": round(r.p99_ms, 1),
            "min_ms": round(r.min_ms, 1),
            "max_ms": round(r.max_ms, 1),
            "within_budget": r.within_budget,
        }
        if r.error:
            entry["error"] = r.error
        # Include per-run latencies for detailed analysis
        entry["latencies_ms"] = [round(run.latency_ms, 1) for run in r.runs
                                  if run.latency_ms > 0]
        evidence["results"].append(entry)

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(evidence, f, indent=2)
    print(f"\n[SAVE] Results written to {output_path}")

    # ── Return code ────────────────────────────────────────────────────
    # 0 if any config meets budget with 100% accuracy
    any_passes = any(r.within_budget and r.accuracy >= 1.0 for r in results)
    if any_passes:
        print(f"\n✅ At least one configuration meets the {LATENCY_BUDGET_MS}ms budget with 100% accuracy.")
        return 0
    else:
        print(f"\n⚠️  No NPU configuration meets the {LATENCY_BUDGET_MS}ms budget with 100% accuracy.")
        print(f"   GPU fallback should be evaluated as an Architectural Decision.")
        return 2


if __name__ == "__main__":
    sys.exit(main())
