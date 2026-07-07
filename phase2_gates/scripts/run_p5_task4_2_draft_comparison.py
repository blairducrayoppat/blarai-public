"""
P5-Task-4.2: Draft Model Comparison — Draft-A vs Draft-B Baseline
==================================================================
Compares Qwen3-0.6B 28L INT4 (Draft-A) vs Qwen3-0.6B-pruned-6L 22L INT8_ASYM (Draft-B)
as speculative decoding draft models for Qwen3-14B on Intel Arc 140V.

Test configurations:
  T-01  14B + Draft-A (28L INT4) speculative NAT=3, 4K context
  T-02  14B + Draft-B (22L INT8_ASYM) speculative NAT=3, 4K context
  T-03  Draft-A standalone TPS (upper bound on draft forward speed)
  T-04  Draft-B standalone TPS (upper bound on draft forward speed)

Parent: Task 4.1 (HEAD c4b6d4c, feature/p5-task4-1-adr-addendum)
Branch: feature/p5-task4-2-draft-model-comparison
Evidence: phase2_gates/evidence/p5_task4_2_draft_model_comparison.json
"""
from __future__ import annotations

import datetime as dt
import gc
import json
import math
import platform
import statistics
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Root path setup
# ---------------------------------------------------------------------------
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import psutil
from transformers import AutoTokenizer

try:
    import openvino as ov
except Exception:  # noqa: BLE001
    ov = None  # type: ignore[assignment]

import openvino_genai as ov_genai
from openvino_genai import LLMPipeline, SchedulerConfig

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
EVIDENCE_DIR = ROOT / "phase2_gates" / "evidence"
OUTPUT_JSON = EVIDENCE_DIR / "p5_task4_2_draft_model_comparison.json"

MODEL_14B        = ROOT / "models" / "qwen3-14b"       / "openvino-int4-gpu"
DRAFT_A_PATH     = ROOT / "models" / "qwen3-0.6b"       / "openvino-int4-gpu"
DRAFT_B_PATH     = ROOT / "models" / "qwen3-0.6b-pruned-6l" / "openvino-int8-gpu"

# ---------------------------------------------------------------------------
# Benchmark constants (LOCKED per Task 4.2 constraints)
# ---------------------------------------------------------------------------
CONTEXT_TOKENS:    int   = 4096
MAX_NEW_TOKENS:    int   = 128
NAT:               int   = 3
WARMUP_RUNS:       int   = 2
MEASURED_RUNS_SPEC: int  = 5
MEASURED_RUNS_SOLO: int  = 3
INFERENCE_PRECISION: str = "f16"
SCHEDULER_CACHE_GB: int  = 3
SYSTEM_PROMPT:     str   = "You are a helpful assistant."

# P5-005b D-01 baseline for harness validation
D01_BASELINE_TPS: float = 11.15
D01_BASELINE_TTFT: float = 401.0


# ===========================================================================
# Shared infrastructure (adapted from run_p5_feasibility_005b.py)
# ===========================================================================

def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def git_head() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True,
        ).strip()
    except Exception:  # noqa: BLE001
        return "UNKNOWN"


def write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2)
    tmp.replace(path)


def normalize_error(prefix: str, text: str) -> str:
    normalized = "".join(ch if ch.isalnum() else "_" for ch in text.upper())
    normalized = "_".join(p for p in normalized.split("_") if p)
    return f"{prefix}_{normalized[:120]}"


def percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    xs = sorted(values)
    k = (len(xs) - 1) * (p / 100.0)
    f, c = math.floor(k), math.ceil(k)
    return xs[f] if f == c else xs[f] * (c - k) + xs[c] * (k - f)


def stats_dict(values: list[float]) -> dict[str, float]:
    if not values:
        return {"mean": 0.0, "stddev": 0.0, "p50": 0.0, "p95": 0.0, "min": 0.0, "max": 0.0,
                "valid_count": 0}
    return {
        "mean":       round(statistics.fmean(values), 4),
        "stddev":     round(statistics.pstdev(values) if len(values) > 1 else 0.0, 4),
        "p50":        round(percentile(values, 50), 4),
        "p95":        round(percentile(values, 95), 4),
        "min":        round(min(values), 4),
        "max":        round(max(values), 4),
        "valid_count": len(values),
    }


def detect_power_envelope() -> dict[str, Any]:
    state: dict[str, Any] = {"sensor_available": False, "power_plugged": None,
                              "battery_percent": None}
    try:
        battery = psutil.sensors_battery()
    except Exception as exc:  # noqa: BLE001
        state["sensor_error"] = str(exc)
        return state
    if battery is None:
        return state
    state["sensor_available"] = True
    state["power_plugged"] = bool(battery.power_plugged)
    state["battery_percent"] = float(battery.percent) if battery.percent is not None else None
    return state


def enforce_ac_power_or_fail_closed() -> dict[str, Any]:
    state = detect_power_envelope()
    if state.get("sensor_available") and state.get("power_plugged") is False:
        raise RuntimeError(
            "AC_POWER_REQUIRED: battery-only operation detected — fail closed per benchmark mandate",
        )
    return state


# ===========================================================================
# RSS sampler
# ===========================================================================

class RssSampler:
    def __init__(self, interval_s: float = 0.01) -> None:
        self._proc = psutil.Process()
        self._interval_s = interval_s
        self._stop = threading.Event()
        self.peak = float(self._proc.memory_info().rss)
        self._thread: threading.Thread | None = None

    def _loop(self) -> None:
        while not self._stop.is_set():
            rss = float(self._proc.memory_info().rss)
            if rss > self.peak:
                self.peak = rss
            time.sleep(self._interval_s)

    def start(self) -> None:
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=3)


# ===========================================================================
# Prompt construction
# ===========================================================================

def build_user_content_to_token_len(tokenizer: Any, target_tokens: int) -> str:
    chunk = (
        " local privacy deterministic benchmark payload "
        "draft model comparison acceptance rate throughput "
    )
    text = "Benchmark prompt for Task 4.2 draft model comparison. "
    for _ in range(200_000):
        toks = tokenizer(text, return_tensors="np")["input_ids"][0]
        if len(toks) >= target_tokens:
            break
        text += chunk
    toks = tokenizer(text, return_tensors="np")["input_ids"][0]
    if len(toks) > target_tokens:
        text = tokenizer.decode(toks[:target_tokens], skip_special_tokens=True)
    return text


def build_chat_prompt(tokenizer: Any, user_content: str) -> str:
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]
    return tokenizer.apply_chat_template(
        messages, tokenize=False, add_generation_prompt=True,
    )


# ===========================================================================
# Pipeline construction — SchedulerConfig API (dict-config DEPRECATED)
# ===========================================================================

def create_speculative_pipeline(
    target_path: Path,
    draft_path: Path,
) -> tuple[Any | None, float | None, dict[str, Any] | None]:
    """Construct a speculative-decoding LLMPipeline with SchedulerConfig API.

    Note: INFERENCE_PRECISION is not a valid OV GPU property. The correct name
    is INFERENCE_PRECISION_HINT; however on Xe2/Arc 140V the default is already
    FP16, so no explicit override is needed. Do NOT pass INFERENCE_PRECISION as
    a kwarg — it will cause a plugin config error.
    """
    t0 = time.perf_counter()
    try:
        scheduler = SchedulerConfig()
        scheduler.cache_size = SCHEDULER_CACHE_GB

        pipeline = LLMPipeline(
            str(target_path),
            "GPU",
            scheduler_config=scheduler,
            draft_model=ov_genai.draft_model(str(draft_path), "GPU"),
            # INFERENCE_PRECISION_HINT defaults to FP16 on Xe2 — explicit override omitted
            # to avoid plugin config validation error on this OV build.
        )
        compile_ms = (time.perf_counter() - t0) * 1000.0
        return pipeline, round(compile_ms, 1), None
    except Exception as exc:  # noqa: BLE001
        return None, None, {
            "message": str(exc),
            "fingerprint": normalize_error("PIPELINE_CREATION_ERROR", str(exc)),
        }


def create_standalone_pipeline(
    model_path: Path,
) -> tuple[Any | None, float | None, dict[str, Any] | None]:
    """Construct a standalone LLMPipeline (no draft model) with SchedulerConfig API."""
    t0 = time.perf_counter()
    try:
        scheduler = SchedulerConfig()
        scheduler.cache_size = SCHEDULER_CACHE_GB

        pipeline = LLMPipeline(
            str(model_path),
            "GPU",
            scheduler_config=scheduler,
            # INFERENCE_PRECISION_HINT defaults to FP16 on Xe2 — explicit override omitted
        )
        compile_ms = (time.perf_counter() - t0) * 1000.0
        return pipeline, round(compile_ms, 1), None
    except Exception as exc:  # noqa: BLE001
        return None, None, {
            "message": str(exc),
            "fingerprint": normalize_error("PIPELINE_CREATION_ERROR", str(exc)),
        }


# ===========================================================================
# GenerationConfig
# ===========================================================================

def make_gen_config(is_speculative: bool) -> Any:
    cfg = ov_genai.GenerationConfig()
    cfg.max_new_tokens = MAX_NEW_TOKENS
    cfg.do_sample = False
    try:
        cfg.temperature = 0.0
        cfg.top_k = 1
        cfg.top_p = 1.0
    except Exception:
        pass
    if is_speculative:
        try:
            cfg.num_assistant_tokens = NAT
            cfg.assistant_confidence_threshold = 0.0
        except Exception:
            pass
    return cfg


# ===========================================================================
# Acceptance rate extraction
# ===========================================================================

def extract_acceptance_metrics(perf_metrics: Any, nat: int) -> dict[str, Any]:
    """Extract speculative decoding acceptance from PerfMetrics.raw_metrics.m_batch_sizes."""
    try:
        raw = perf_metrics.raw_metrics
        batch_sizes = list(raw.m_batch_sizes) if hasattr(raw, "m_batch_sizes") else []
    except Exception:
        batch_sizes = []

    if not batch_sizes:
        return {
            "acceptance_data_source": "UNAVAILABLE",
            "total_speculative_episodes": None,
            "tokens_drafted_total": None,
            "tokens_accepted_total": None,
            "acceptance_rate_aggregate": None,
            "acceptance_rate_by_step": None,
        }

    total_episodes = len(batch_sizes)
    tokens_drafted = nat * total_episodes
    tokens_accepted = sum(b - 1 for b in batch_sizes)
    agg_rate = tokens_accepted / tokens_drafted if tokens_drafted > 0 else 0.0

    per_step = []
    for step in range(1, nat + 1):
        accepted = sum(1 for b in batch_sizes if b >= step + 1)
        per_step.append(round(accepted / total_episodes, 4))

    return {
        "acceptance_data_source": "m_batch_sizes",
        "total_speculative_episodes": total_episodes,
        "tokens_drafted_total": tokens_drafted,
        "tokens_accepted_total": tokens_accepted,
        "acceptance_rate_aggregate": round(agg_rate, 4),
        "acceptance_rate_by_step": per_step,
    }


def extract_perf_metrics_secondary(
    perf_metrics: Any, nat: int, is_speculative: bool,
) -> dict[str, Any]:
    """Extract PerfMetrics secondary data (may fail — all failures result in None)."""
    data: dict[str, Any] = {}

    # Combined TPS from PerfMetrics
    try:
        tput = perf_metrics.get_throughput()
        data["combined_tps_perfmetrics"] = round(tput.mean, 4)
    except Exception:
        data["combined_tps_perfmetrics"] = None

    # TTFT from PerfMetrics (in ms)
    try:
        ttft = perf_metrics.get_ttft()
        # OpenVINO GenAI reports TTFT in milliseconds
        data["ttft_ms_perfmetrics"] = round(ttft.mean, 2)
    except Exception:
        data["ttft_ms_perfmetrics"] = None

    # Per-step inference duration (microseconds to ms)
    try:
        raw = perf_metrics.raw_metrics
        infer_us = list(raw.inference_durations)
        batch_sizes = list(raw.m_batch_sizes) if hasattr(raw, "m_batch_sizes") else []
        if infer_us and batch_sizes and len(infer_us) == len(batch_sizes):
            mean_us = sum(infer_us) / len(infer_us)
            data["mean_inference_duration_us_per_step"] = round(mean_us, 2)
            data["mean_inference_duration_ms_per_step"] = round(mean_us / 1000.0, 4)
        else:
            data["mean_inference_duration_ms_per_step"] = None
    except Exception:
        data["mean_inference_duration_ms_per_step"] = None

    # Acceptance (speculative only)
    if is_speculative:
        data.update(extract_acceptance_metrics(perf_metrics, nat))
    else:
        data["acceptance_data_source"] = "N/A_STANDALONE"
        data["acceptance_rate_aggregate"] = None
        data["acceptance_rate_by_step"] = None

    return data


# ===========================================================================
# Single generation run
# ===========================================================================

def run_single_generation(
    pipeline: Any,
    tokenizer: Any,
    prompt: str,
    gen_config: Any,
    is_speculative: bool,
) -> dict[str, Any]:
    """Run one generation, capturing wall-clock timing, RSS, and PerfMetrics."""
    proc = psutil.Process()
    rss_before = proc.memory_info().rss / (1024 * 1024)
    sampler = RssSampler()
    sampler.start()

    first_token_time: float | None = None

    def stream_cb(token_chunk: str) -> bool:
        nonlocal first_token_time
        if first_token_time is None and token_chunk:
            first_token_time = time.perf_counter()
        return False

    t0 = time.perf_counter()
    try:
        # Try with stream callback for wall-clock TTFT; fall back if API doesn't support it
        try:
            output = pipeline.generate(prompt, gen_config, stream_cb)
            has_stream_ttft = first_token_time is not None
        except TypeError:
            output = pipeline.generate(prompt, gen_config)
            has_stream_ttft = False

        sampler.stop()
        t1 = time.perf_counter()
        rss_peak = sampler.peak / (1024 * 1024)
        rss_after = proc.memory_info().rss / (1024 * 1024)
        total_ms = (t1 - t0) * 1000.0

        # Extract PerfMetrics (available on DecodedResults when no stream callback used,
        # or possibly still accessible when stream callback version returns DecodedResults)
        perf_metrics: Any = None
        try:
            perf_metrics = output.perf_metrics
        except AttributeError:
            perf_metrics = None

        # Decode output text — handle both str and DecodedResults
        try:
            text = str(output)
        except Exception:
            text = ""

        token_ids = tokenizer(text, return_tensors="np")["input_ids"][0]
        tokens_generated = int(len(token_ids))

        # Wall-clock TTFT
        if has_stream_ttft:
            ttft_ms_wc = (first_token_time - t0) * 1000.0  # type: ignore[operator]
        elif perf_metrics is not None:
            try:
                ttft_ms_wc = perf_metrics.get_ttft().mean
            except Exception:
                ttft_ms_wc = total_ms  # fallback
        else:
            ttft_ms_wc = total_ms

        decode_ms = max(total_ms - ttft_ms_wc, 1.0)
        tps_wc = (tokens_generated / (decode_ms / 1000.0)) if decode_ms > 0 else 0.0

        result_base = {
            "ok": True,
            "tokens_generated": tokens_generated,
            "total_ms": round(total_ms, 1),
            "ttft_ms_wallclock": round(ttft_ms_wc, 1),
            "decode_tokens_per_sec": round(tps_wc, 4),
            "latency_first_token_ms": round(ttft_ms_wc, 1),
            "rss_before_mb": round(rss_before, 1),
            "rss_peak_mb": round(rss_peak, 1),
            "rss_after_mb": round(rss_after, 1),
            "ttft_source": "stream_callback" if has_stream_ttft else "perf_metrics_or_total",
            "error": None,
            "error_fingerprint": None,
        }

        # Secondary PerfMetrics
        if perf_metrics is not None:
            secondary = extract_perf_metrics_secondary(perf_metrics, NAT, is_speculative)
        else:
            secondary = {
                "combined_tps_perfmetrics": None,
                "ttft_ms_perfmetrics": None,
                "mean_inference_duration_ms_per_step": None,
                "acceptance_data_source": "UNAVAILABLE" if is_speculative else "N/A_STANDALONE",
                "total_speculative_episodes": None,
                "tokens_drafted_total": None,
                "tokens_accepted_total": None,
                "acceptance_rate_aggregate": None,
                "acceptance_rate_by_step": None,
            }
        result_base.update(secondary)
        return result_base

    except Exception as exc:  # noqa: BLE001
        sampler.stop()
        rss_peak = sampler.peak / (1024 * 1024)
        rss_after = proc.memory_info().rss / (1024 * 1024)
        msg = str(exc)
        return {
            "ok": False,
            "tokens_generated": 0,
            "total_ms": 0.0,
            "ttft_ms_wallclock": 0.0,
            "decode_tokens_per_sec": 0.0,
            "latency_first_token_ms": 0.0,
            "rss_before_mb": round(rss_before, 1),
            "rss_peak_mb": round(rss_peak, 1),
            "rss_after_mb": round(rss_after, 1),
            "ttft_source": "N/A_FAILED",
            "error": msg,
            "error_fingerprint": normalize_error("GENERATION_ERROR", msg),
            "acceptance_data_source": "N/A_FAILED",
            "acceptance_rate_aggregate": None,
            "acceptance_rate_by_step": None,
        }


# ===========================================================================
# Run one config (warmup + measured)
# ===========================================================================

def run_config(
    config_id: str,
    config_name: str,
    pipeline: Any,
    tokenizer: Any,
    prompt: str,
    gen_config: Any,
    is_speculative: bool,
    measured_runs: int,
) -> dict[str, Any]:
    print(f"\n  Warming up {config_id} ({WARMUP_RUNS} warmup runs)...")
    for w in range(WARMUP_RUNS):
        r = run_single_generation(pipeline, tokenizer, prompt, gen_config, is_speculative)
        print(f"    Warmup {w + 1}: {r['decode_tokens_per_sec']:.2f} tps", end="")
        if r.get("acceptance_rate_aggregate") is not None:
            print(f", AR={r['acceptance_rate_aggregate']:.3f}", end="")
        print()

    print(f"  Running {measured_runs} measured runs...")
    runs: list[dict[str, Any]] = []
    for i in range(measured_runs):
        r = run_single_generation(pipeline, tokenizer, prompt, gen_config, is_speculative)
        runs.append(r)
        status = "OK" if r["ok"] else f"FAIL:{r.get('error_fingerprint','?')}"
        print(f"    Run {i + 1}: {r['decode_tokens_per_sec']:.2f} tps, "
              f"TTFT={r['ttft_ms_wallclock']:.0f}ms, "
              f"RSS={r['rss_peak_mb']:.0f}MB [{status}]")
        if r.get("acceptance_rate_aggregate") is not None:
            print(f"           AR_agg={r['acceptance_rate_aggregate']:.3f}, "
                  f"per_step={r.get('acceptance_rate_by_step')}")

    ok_runs = [r for r in runs if r["ok"]]

    tps_vals   = [r["decode_tokens_per_sec"] for r in ok_runs]
    ttft_vals  = [r["ttft_ms_wallclock"]     for r in ok_runs]
    rss_vals   = [r["rss_peak_mb"]           for r in runs]

    combined_tps_summary = stats_dict(tps_vals)
    ttft_summary = stats_dict(ttft_vals)
    rss_summary = stats_dict(rss_vals)

    # Aggregate acceptance across all ok_runs (use last run's per-step since it's consistent)
    acceptance_summary: dict[str, Any] = {}
    if is_speculative:
        agg_rates = [r["acceptance_rate_aggregate"] for r in ok_runs
                     if r.get("acceptance_rate_aggregate") is not None]
        per_step_last = None
        for r in reversed(ok_runs):
            if r.get("acceptance_rate_by_step") is not None:
                per_step_last = r["acceptance_rate_by_step"]
                break

        # Sum totals for aggregate acceptance rate
        total_drafted = sum(r.get("tokens_drafted_total") or 0 for r in ok_runs)
        total_accepted = sum(r.get("tokens_accepted_total") or 0 for r in ok_runs)
        agg_rate_global = (total_accepted / total_drafted) if total_drafted > 0 else None

        acceptance_summary = {
            "acceptance_rate_aggregate": round(agg_rate_global, 4) if agg_rate_global is not None else None,
            "acceptance_rate_by_step_last_run": per_step_last,
            "tokens_drafted_total_all_runs": total_drafted,
            "tokens_accepted_total_all_runs": total_accepted,
            "acceptance_data_source": ok_runs[-1].get("acceptance_data_source") if ok_runs else "UNAVAILABLE",
        }
    else:
        acceptance_summary = {
            "acceptance_rate_aggregate": None,
            "acceptance_rate_by_step_last_run": None,
            "acceptance_data_source": "N/A_STANDALONE",
        }

    summary: dict[str, Any] = {
        "combined_tps":  combined_tps_summary,
        "ttft_ms":       ttft_summary,
        "peak_rss_mb":   rss_summary,
        **acceptance_summary,
        "valid_runs": len(ok_runs),
        "failed_runs": len(runs) - len(ok_runs),
    }

    return {
        "id": config_id,
        "name": config_name,
        "runs": runs,
        "summary": summary,
    }


# ===========================================================================
# System metadata
# ===========================================================================

def collect_metadata() -> dict[str, Any]:
    meta: dict[str, Any] = {
        "git_head": git_head(),
        "branch": "feature/p5-task4-2-draft-model-comparison",
        "python_version": sys.version,
        "platform": platform.platform(),
    }

    # OpenVINO GenAI version
    try:
        meta["openvino_genai_version"] = ov_genai.__version__
    except AttributeError:
        meta["openvino_genai_version"] = "UNKNOWN"

    # OpenVINO version
    if ov is not None:
        try:
            meta["openvino_version"] = ov.__version__
        except AttributeError:
            meta["openvino_version"] = "UNKNOWN"

    meta["power_state"] = detect_power_envelope()
    return meta


# ===========================================================================
# Derive draft_forward_ms_per_step from standalone TPS
# ===========================================================================

def derive_draft_forward_ms(standalone_tps: float | None, nat: int) -> str | None:
    if standalone_tps is None or standalone_tps <= 0:
        return None
    ms_per_token = 1000.0 / standalone_tps
    ms_per_step = ms_per_token * nat
    return f"{ms_per_step:.2f}ms (1000/{standalone_tps:.2f} tps × {nat} = {ms_per_step:.2f}ms)"


# ===========================================================================
# Winner selection
# ===========================================================================

def select_winner(
    t01_tps: float | None,
    t02_tps: float | None,
    t01_ar: float | None,
    t02_ar: float | None,
    t02_pipeline_ok: bool,
) -> tuple[str, str]:
    if not t02_pipeline_ok:
        return ("DRAFT_A_WINS_BY_DEFAULT",
                "Draft-B pipeline creation failed — Draft-A wins by default")

    if t01_tps is None and t02_tps is None:
        return ("INCONCLUSIVE", "Both speculative configs failed to produce TPS data")

    if t01_tps is None:
        return ("DRAFT_B_WINS", f"Draft-A TPS unavailable. Draft-B: {t02_tps:.2f} tps")

    if t02_tps is None:
        return ("DRAFT_A_WINS", f"Draft-B TPS unavailable. Draft-A: {t01_tps:.2f} tps")

    delta = abs(t01_tps - t02_tps) / max(t01_tps, t02_tps)
    if delta < 0.03:
        # Within 3% — use acceptance rate as tiebreaker
        if t01_ar is not None and t02_ar is not None:
            if t01_ar > t02_ar + 0.01:
                return ("DRAFT_A_WINS",
                        f"TPS within 3% (A={t01_tps:.2f}, B={t02_tps:.2f}). "
                        f"Tiebreaker: Draft-A acceptance {t01_ar:.3f} > Draft-B {t02_ar:.3f}")
            elif t02_ar > t01_ar + 0.01:
                return ("DRAFT_B_WINS",
                        f"TPS within 3% (A={t01_tps:.2f}, B={t02_tps:.2f}). "
                        f"Tiebreaker: Draft-B acceptance {t02_ar:.3f} > Draft-A {t01_ar:.3f}")
            else:
                return ("INCONCLUSIVE",
                        f"TPS within 3% and acceptance within 1% — statistically indistinguishable. "
                        f"A={t01_tps:.2f} tps AR={t01_ar:.3f}, B={t02_tps:.2f} tps AR={t02_ar:.3f}")
        else:
            return ("INCONCLUSIVE",
                    f"TPS within 3% and acceptance data unavailable. "
                    f"A={t01_tps:.2f}, B={t02_tps:.2f}")

    if t01_tps >= t02_tps:
        return ("DRAFT_A_WINS",
                f"Draft-A {t01_tps:.2f} tps > Draft-B {t02_tps:.2f} tps "
                f"(delta {delta * 100:.1f}%). Primary metric: combined TPS.")
    else:
        return ("DRAFT_B_WINS",
                f"Draft-B {t02_tps:.2f} tps > Draft-A {t01_tps:.2f} tps "
                f"(delta {delta * 100:.1f}%). Primary metric: combined TPS.")


# ===========================================================================
# Main benchmark execution
# ===========================================================================

def main() -> None:
    print("=" * 70)
    print("P5-Task-4.2: Draft Model Comparison — Draft-A vs Draft-B")
    print("=" * 70)

    # --- AC power enforcement ---
    print("\n[PRE-CHECK] Enforcing AC power...")
    power = enforce_ac_power_or_fail_closed()
    plugged = power.get("power_plugged")
    pct = power.get("battery_percent")
    print(f"  Power state: plugged={plugged}, battery={pct}%")

    metadata = collect_metadata()
    metadata["power_state"] = power

    # --- Tokenizer ---
    print(f"\n[TOKENIZER] Loading from {MODEL_14B}...")
    tokenizer = AutoTokenizer.from_pretrained(str(MODEL_14B), trust_remote_code=True)
    print("  Tokenizer loaded.")

    # --- Build prompt at 4096 user tokens ---
    print(f"\n[PROMPT] Building prompt at {CONTEXT_TOKENS} user tokens...")
    user_content = build_user_content_to_token_len(tokenizer, CONTEXT_TOKENS)
    prompt = build_chat_prompt(tokenizer, user_content)
    prompt_toks = len(tokenizer(prompt, return_tensors="np")["input_ids"][0])
    print(f"  Prompt total tokens (with chat template): {prompt_toks}")

    locked_config = {
        "target_model": "qwen3-14b INT4 GPU",
        "context_tokens": CONTEXT_TOKENS,
        "max_new_tokens": MAX_NEW_TOKENS,
        "nat": NAT,
        "xattention": "OFF (not set)",
        "inference_precision": "FP16 (Xe2 default — INFERENCE_PRECISION_HINT not set explicitly; INFERENCE_PRECISION invalid property name on this OV build)",
        "kv_cache_precision": "FP16 (default — not set)",
        "scheduler_cache_size_gb": SCHEDULER_CACHE_GB,
        "warmup_runs": WARMUP_RUNS,
        "measured_runs_speculative": MEASURED_RUNS_SPEC,
        "measured_runs_standalone": MEASURED_RUNS_SOLO,
        "prompt_total_tokens_actual": prompt_toks,
    }

    tests: list[dict[str, Any]] = []
    t01_tps: float | None = None
    t02_tps: float | None = None
    t01_ar: float | None = None
    t02_ar: float | None = None
    t02_pipeline_ok = True
    t03_standalone_tps: float | None = None
    t04_standalone_tps: float | None = None

    # -----------------------------------------------------------------------
    # T-01: 14B + Draft-A speculative
    # -----------------------------------------------------------------------
    print("\n" + "=" * 60)
    print("T-01: 14B + Draft-A (Qwen3-0.6B 28L INT4) — NAT=3")
    print("=" * 60)
    print(f"  Creating pipeline (target={MODEL_14B.name}, draft={DRAFT_A_PATH.name})...")
    pipe_t01, compile_ms_t01, pipe_err_t01 = create_speculative_pipeline(MODEL_14B, DRAFT_A_PATH)

    if pipe_t01 is None:
        print(f"  PIPELINE CREATION FAILED: {pipe_err_t01}")
        test_t01: dict[str, Any] = {
            "id": "T-01", "name": "14B + Draft-A (28L INT4) NAT=3",
            "draft_model": "qwen3-0.6b 28L INT4", "draft_path": str(DRAFT_A_PATH),
            "draft_layers": 28, "draft_quant": "INT4", "draft_weight_mb": 367,
            "is_speculative": True, "pipeline_creation_ok": False,
            "pipeline_creation_error": pipe_err_t01, "runs": [], "summary": {},
        }
    else:
        print(f"  Pipeline compiled in {compile_ms_t01:.0f}ms.")
        gen_cfg_spec = make_gen_config(is_speculative=True)
        cfg_result = run_config(
            "T-01", "14B + Draft-A (28L INT4) NAT=3",
            pipe_t01, tokenizer, prompt, gen_cfg_spec,
            is_speculative=True, measured_runs=MEASURED_RUNS_SPEC,
        )
        test_t01 = {
            "id": "T-01", "name": "14B + Draft-A (28L INT4) NAT=3",
            "draft_model": "qwen3-0.6b 28L INT4", "draft_path": str(DRAFT_A_PATH),
            "draft_layers": 28, "draft_quant": "INT4", "draft_weight_mb": 367,
            "is_speculative": True, "pipeline_creation_ok": True,
            "pipeline_compile_ms": compile_ms_t01,
            **cfg_result,
        }
        t01_tps = cfg_result["summary"]["combined_tps"].get("mean")
        t01_ar = cfg_result["summary"].get("acceptance_rate_aggregate")
        del pipe_t01
        gc.collect()

    tests.append(test_t01)
    # Intermediate write
    write_json_atomic(OUTPUT_JSON, {
        "milestone": "P5-Task-4.2", "title": "Draft Model Comparison",
        "timestamp_utc": now_iso(), "metadata": metadata,
        "locked_config": locked_config, "tests": tests,
        "status": "in_progress",
    })
    print(f"  Intermediate artifact written to {OUTPUT_JSON.name}")

    # -----------------------------------------------------------------------
    # T-02: 14B + Draft-B speculative
    # -----------------------------------------------------------------------
    print("\n" + "=" * 60)
    print("T-02: 14B + Draft-B (Qwen3-0.6B-pruned-6L 22L INT8_ASYM) — NAT=3")
    print("=" * 60)
    print(f"  Creating pipeline (target={MODEL_14B.name}, draft={DRAFT_B_PATH.name})...")
    pipe_t02, compile_ms_t02, pipe_err_t02 = create_speculative_pipeline(MODEL_14B, DRAFT_B_PATH)

    if pipe_t02 is None:
        t02_pipeline_ok = False
        print(f"  PIPELINE CREATION FAILED: {pipe_err_t02}")
        print("  NOTE: Draft-B pipeline failure is a valid outcome — Draft-A wins by default.")
        test_t02: dict[str, Any] = {
            "id": "T-02", "name": "14B + Draft-B (22L INT8_ASYM) NAT=3",
            "draft_model": "qwen3-0.6b-pruned-6l 22L INT8_ASYM", "draft_path": str(DRAFT_B_PATH),
            "draft_layers": 22, "draft_quant": "INT8_ASYM", "draft_weight_mb": 480,
            "is_speculative": True, "pipeline_creation_ok": False,
            "pipeline_creation_error": pipe_err_t02, "runs": [], "summary": {},
        }
    else:
        print(f"  Pipeline compiled in {compile_ms_t02:.0f}ms.")
        gen_cfg_spec2 = make_gen_config(is_speculative=True)
        cfg_result2 = run_config(
            "T-02", "14B + Draft-B (22L INT8_ASYM) NAT=3",
            pipe_t02, tokenizer, prompt, gen_cfg_spec2,
            is_speculative=True, measured_runs=MEASURED_RUNS_SPEC,
        )
        test_t02 = {
            "id": "T-02", "name": "14B + Draft-B (22L INT8_ASYM) NAT=3",
            "draft_model": "qwen3-0.6b-pruned-6l 22L INT8_ASYM", "draft_path": str(DRAFT_B_PATH),
            "draft_layers": 22, "draft_quant": "INT8_ASYM", "draft_weight_mb": 480,
            "is_speculative": True, "pipeline_creation_ok": True,
            "pipeline_compile_ms": compile_ms_t02,
            **cfg_result2,
        }
        t02_tps = cfg_result2["summary"]["combined_tps"].get("mean")
        t02_ar = cfg_result2["summary"].get("acceptance_rate_aggregate")
        del pipe_t02
        gc.collect()

    tests.append(test_t02)
    write_json_atomic(OUTPUT_JSON, {
        "milestone": "P5-Task-4.2", "title": "Draft Model Comparison",
        "timestamp_utc": now_iso(), "metadata": metadata,
        "locked_config": locked_config, "tests": tests,
        "status": "in_progress",
    })
    print(f"  Intermediate artifact written to {OUTPUT_JSON.name}")

    # -----------------------------------------------------------------------
    # T-03: Draft-A standalone
    # -----------------------------------------------------------------------
    print("\n" + "=" * 60)
    print("T-03: Draft-A Standalone (Qwen3-0.6B 28L INT4, no target)")
    print("=" * 60)
    print(f"  Creating standalone pipeline ({DRAFT_A_PATH.name})...")
    pipe_t03, compile_ms_t03, pipe_err_t03 = create_standalone_pipeline(DRAFT_A_PATH)

    if pipe_t03 is None:
        print(f"  PIPELINE CREATION FAILED: {pipe_err_t03}")
        test_t03: dict[str, Any] = {
            "id": "T-03", "name": "Draft-A Standalone (28L INT4)",
            "model_path": str(DRAFT_A_PATH),
            "is_speculative": False, "pipeline_creation_ok": False,
            "pipeline_creation_error": pipe_err_t03, "runs": [], "summary": {},
        }
    else:
        print(f"  Pipeline compiled in {compile_ms_t03:.0f}ms.")
        gen_cfg_solo = make_gen_config(is_speculative=False)
        cfg_result3 = run_config(
            "T-03", "Draft-A Standalone (28L INT4)",
            pipe_t03, tokenizer, prompt, gen_cfg_solo,
            is_speculative=False, measured_runs=MEASURED_RUNS_SOLO,
        )
        test_t03 = {
            "id": "T-03", "name": "Draft-A Standalone (28L INT4)",
            "model_path": str(DRAFT_A_PATH), "purpose": "Standalone draft TPS — upper bound on Draft-A forward speed",
            "is_speculative": False, "pipeline_creation_ok": True,
            "pipeline_compile_ms": compile_ms_t03,
            **cfg_result3,
        }
        t03_standalone_tps = cfg_result3["summary"]["combined_tps"].get("mean")
        del pipe_t03
        gc.collect()

    tests.append(test_t03)
    write_json_atomic(OUTPUT_JSON, {
        "milestone": "P5-Task-4.2", "title": "Draft Model Comparison",
        "timestamp_utc": now_iso(), "metadata": metadata,
        "locked_config": locked_config, "tests": tests,
        "status": "in_progress",
    })
    print(f"  Intermediate artifact written to {OUTPUT_JSON.name}")

    # -----------------------------------------------------------------------
    # T-04: Draft-B standalone
    # -----------------------------------------------------------------------
    print("\n" + "=" * 60)
    print("T-04: Draft-B Standalone (Qwen3-0.6B-pruned-6L 22L INT8_ASYM, no target)")
    print("=" * 60)
    print(f"  Creating standalone pipeline ({DRAFT_B_PATH.name})...")
    pipe_t04, compile_ms_t04, pipe_err_t04 = create_standalone_pipeline(DRAFT_B_PATH)

    if pipe_t04 is None:
        print(f"  PIPELINE CREATION FAILED: {pipe_err_t04}")
        test_t04: dict[str, Any] = {
            "id": "T-04", "name": "Draft-B Standalone (22L INT8_ASYM)",
            "model_path": str(DRAFT_B_PATH),
            "is_speculative": False, "pipeline_creation_ok": False,
            "pipeline_creation_error": pipe_err_t04, "runs": [], "summary": {},
        }
    else:
        print(f"  Pipeline compiled in {compile_ms_t04:.0f}ms.")
        gen_cfg_solo2 = make_gen_config(is_speculative=False)
        cfg_result4 = run_config(
            "T-04", "Draft-B Standalone (22L INT8_ASYM)",
            pipe_t04, tokenizer, prompt, gen_cfg_solo2,
            is_speculative=False, measured_runs=MEASURED_RUNS_SOLO,
        )
        test_t04 = {
            "id": "T-04", "name": "Draft-B Standalone (22L INT8_ASYM)",
            "model_path": str(DRAFT_B_PATH), "purpose": "Standalone draft TPS — upper bound on Draft-B forward speed",
            "is_speculative": False, "pipeline_creation_ok": True,
            "pipeline_compile_ms": compile_ms_t04,
            **cfg_result4,
        }
        t04_standalone_tps = cfg_result4["summary"]["combined_tps"].get("mean")
        del pipe_t04
        gc.collect()

    tests.append(test_t04)

    # -----------------------------------------------------------------------
    # Derived metrics
    # -----------------------------------------------------------------------
    draft_a_forward_derived = derive_draft_forward_ms(t03_standalone_tps, NAT)
    draft_b_forward_derived = derive_draft_forward_ms(t04_standalone_tps, NAT)

    tps_delta_pct: float | None = None
    if t01_tps is not None and t02_tps is not None and t01_tps > 0:
        tps_delta_pct = round((t01_tps - t02_tps) / t01_tps * 100, 2)

    derived_metrics: dict[str, Any] = {
        "draft_a_standalone_tps_mean": round(t03_standalone_tps, 4) if t03_standalone_tps else None,
        "draft_b_standalone_tps_mean": round(t04_standalone_tps, 4) if t04_standalone_tps else None,
        "draft_a_forward_ms_per_step_derived": draft_a_forward_derived,
        "draft_b_forward_ms_per_step_derived": draft_b_forward_derived,
        "draft_a_combined_tps_mean": round(t01_tps, 4) if t01_tps else None,
        "draft_b_combined_tps_mean": round(t02_tps, 4) if t02_tps else None,
        "tps_delta_pct_a_minus_b": tps_delta_pct,
    }

    # Harness validation against P5-005b D-01 baseline
    t01_vs_d01_delta_pct: float | None = None
    t01_validation = "SKIPPED_TPS_UNAVAILABLE"
    if t01_tps is not None:
        t01_vs_d01_delta_pct = round(abs(t01_tps - D01_BASELINE_TPS) / D01_BASELINE_TPS * 100, 1)
        t01_validation = "PLAUSIBLE" if t01_vs_d01_delta_pct < 15.0 else "WARNING_DELTA_EXCEEDS_15PCT"

    p5_005b_comparison = {
        "d01_tps_at_4k": D01_BASELINE_TPS,
        "d01_ttft_at_4k_ms": D01_BASELINE_TTFT,
        "d01_nat": 3,
        "d01_draft": "Draft-A (same as T-01)",
        "t01_tps_mean": round(t01_tps, 4) if t01_tps else None,
        "t01_vs_d01_delta_pct": t01_vs_d01_delta_pct,
        "harness_validation": t01_validation,
    }

    # Winner selection
    disposition, disposition_rationale = select_winner(
        t01_tps, t02_tps, t01_ar, t02_ar, t02_pipeline_ok,
    )

    # Best draft carry-forward
    if disposition == "DRAFT_A_WINS" or disposition == "DRAFT_A_WINS_BY_DEFAULT":
        best_draft = "Draft-A"
        best_path = str(DRAFT_A_PATH)
        best_tps = t01_tps
    elif disposition == "DRAFT_B_WINS":
        best_draft = "Draft-B"
        best_path = str(DRAFT_B_PATH)
        best_tps = t02_tps
    else:
        best_draft = "Draft-A (default — INCONCLUSIVE)"
        best_path = str(DRAFT_A_PATH)
        best_tps = t01_tps

    carry_forward = {
        "best_draft_model": best_draft,
        "best_draft_path": best_path,
        "best_draft_combined_tps": round(best_tps, 4) if best_tps else None,
        "carries_to": ["Task 4.3 (NAT sweep)", "Task 4.4 (XAttention)", "Task 4.5+"],
    }

    # -----------------------------------------------------------------------
    # Final artifact
    # -----------------------------------------------------------------------
    final_payload: dict[str, Any] = {
        "milestone": "P5-Task-4.2",
        "title": "Draft Model Comparison — Draft-A (0.6B 28L INT4) vs Draft-B (0.6B pruned 22L INT8_ASYM)",
        "timestamp_utc": now_iso(),
        "metadata": metadata,
        "locked_config": locked_config,
        "tests": tests,
        "derived_metrics": derived_metrics,
        "p5_005b_baseline_comparison": p5_005b_comparison,
        "disposition": disposition,
        "disposition_rationale": disposition_rationale,
        "carry_forward": carry_forward,
    }

    write_json_atomic(OUTPUT_JSON, final_payload)

    print("\n" + "=" * 70)
    print("RESULTS SUMMARY")
    print("=" * 70)
    t01_tps_str = f"{t01_tps:.2f}" if t01_tps is not None else "N/A"
    t02_tps_str = f"{t02_tps:.2f}" if t02_tps is not None else "N/A"
    t01_ar_str  = f"{t01_ar:.3f}" if t01_ar  is not None else "N/A"
    t02_ar_str  = f"{t02_ar:.3f}" if t02_ar  is not None else "N/A"
    t03_tps_str = f"{t03_standalone_tps:.2f}" if t03_standalone_tps is not None else "N/A"
    t04_tps_str = f"{t04_standalone_tps:.2f}" if t04_standalone_tps is not None else "N/A"
    print(f"  T-01 (14B + Draft-A):   TPS={t01_tps_str}, AR={t01_ar_str}")
    print(f"  T-02 (14B + Draft-B):   TPS={t02_tps_str}, AR={t02_ar_str}, pipeline_ok={t02_pipeline_ok}")
    print(f"  T-03 (Draft-A solo):    TPS={t03_tps_str}")
    print(f"  T-04 (Draft-B solo):    TPS={t04_tps_str}")
    print(f"  Harness validation: T-01 vs D-01 baseline: {t01_validation} "
          f"(delta={t01_vs_d01_delta_pct}%)")
    print(f"\n  DISPOSITION: {disposition}")
    print(f"  RATIONALE:   {disposition_rationale}")
    print(f"  CARRY-FORWARD: {carry_forward['best_draft_model']}")
    print(f"\n  Evidence: {OUTPUT_JSON}")


if __name__ == "__main__":
    main()
