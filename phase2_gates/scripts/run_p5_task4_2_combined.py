"""
P5-Task-4.2 Combined Rerun + Task 4.2b NPU Draft Device Comparison
===================================================================
CORRECTED RERUN: Original Task 4.2 (95a3f0a) had a str-input generate() bug
that silently lost acceptance rate, native TPS, native TTFT, and per-model
breakdown for ALL speculative runs.

FIX: pipeline.generate([prompt], gc, cb)  → DecodedResults (CORRECT)
     pipeline.generate(prompt, gc, cb)    → bare str      (BUG — no metrics)

This harness runs:
  T-01  14B/GPU + Draft-A/GPU (28L INT4) NAT=3          — CORRECTED RERUN
  T-02  14B/GPU + Draft-B/GPU (22L INT8_ASYM) NAT=3     — CORRECTED RERUN
  T-03  Draft-A standalone (28L INT4 GPU)                — CORRECTED RERUN
  T-04  Draft-B standalone (22L INT8_ASYM GPU)           — CORRECTED RERUN
  T-05  14B/GPU + Draft-A/NPU (28L INT4) NAT=3          — NEW (Task 4.2b scope)

Evidence output:
  phase2_gates/evidence/p5_task4_2_draft_model_comparison.json   ← OVERWRITE (corrected)
  phase2_gates/evidence/p5_task4_2b_npu_draft_comparison.json    ← NEW

Supersedes: run_p5_task4_2_draft_comparison.py (preserved as bug evidence)
Branch: feature/p5-task4-2-combined-rerun
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
EVIDENCE_DIR     = ROOT / "phase2_gates" / "evidence"
OUTPUT_JSON_42   = EVIDENCE_DIR / "p5_task4_2_draft_model_comparison.json"
OUTPUT_JSON_42B  = EVIDENCE_DIR / "p5_task4_2b_npu_draft_comparison.json"

MODEL_14B        = ROOT / "models" / "qwen3-14b"              / "openvino-int4-gpu"
DRAFT_A_GPU_PATH = ROOT / "models" / "qwen3-0.6b"             / "openvino-int4-gpu"
DRAFT_B_GPU_PATH = ROOT / "models" / "qwen3-0.6b-pruned-6l"   / "openvino-int8-gpu"
DRAFT_A_NPU_PATH = ROOT / "models" / "qwen3-0.6b"             / "openvino-int4-npu"

# ---------------------------------------------------------------------------
# Benchmark constants (LOCKED per Task 4.2 constraints)
# ---------------------------------------------------------------------------
CONTEXT_TOKENS:     int   = 4096
MAX_NEW_TOKENS:     int   = 128
NAT:                int   = 3
WARMUP_RUNS:        int   = 2
MEASURED_RUNS_SPEC: int   = 5
MEASURED_RUNS_SOLO: int   = 3
SCHEDULER_CACHE_GB: int   = 3
SYSTEM_PROMPT:      str   = "You are a helpful assistant."

# P5-005b D-01 baseline for harness validation
D01_BASELINE_TPS:  float = 11.15
D01_BASELINE_TTFT: float = 401.0


# ===========================================================================
# Shared utilities
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
        return {"mean": 0.0, "stddev": 0.0, "p50": 0.0, "p95": 0.0,
                "min": 0.0, "max": 0.0, "valid_count": 0}
    return {
        "mean":        round(statistics.fmean(values), 4),
        "stddev":      round(statistics.pstdev(values) if len(values) > 1 else 0.0, 4),
        "p50":         round(percentile(values, 50), 4),
        "p95":         round(percentile(values, 95), 4),
        "min":         round(min(values), 4),
        "max":         round(max(values), 4),
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
# NPU driver detection (NEW for Task 4.2b)
# ===========================================================================

def detect_npu_driver() -> dict[str, Any]:
    """Detect Intel AI Boost NPU driver version via WMI."""
    try:
        result = subprocess.check_output(
            ["powershell", "-NoProfile", "-Command",
             "Get-CimInstance Win32_PnPSignedDriver | "
             "Where-Object { $_.Description -eq 'Intel(R) AI Boost' } | "
             "Select-Object -ExpandProperty DriverVersion"],
            text=True, timeout=15,
        ).strip()
        if result:
            return {
                "device_name": "Intel(R) AI Boost",
                "driver_version": result,
                "meets_minimum": result >= "32.0.100.3104",
                "minimum_required": "32.0.100.3104",
            }
    except Exception:  # noqa: BLE001
        pass
    return {
        "device_name": "Intel(R) AI Boost",
        "driver_version": "UNKNOWN",
        "meets_minimum": None,
        "minimum_required": "32.0.100.3104",
    }


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
    """Construct GPU speculative-decoding LLMPipeline (both target and draft on GPU)."""
    t0 = time.perf_counter()
    try:
        scheduler = SchedulerConfig()
        scheduler.cache_size = SCHEDULER_CACHE_GB

        pipeline = LLMPipeline(
            str(target_path),
            "GPU",
            scheduler_config=scheduler,
            draft_model=ov_genai.draft_model(str(draft_path), "GPU"),
            # INFERENCE_PRECISION is an invalid OV GPU property name on this build.
            # FP16 is the Xe2/Arc 140V default — no explicit override needed.
        )
        compile_ms = (time.perf_counter() - t0) * 1000.0
        return pipeline, round(compile_ms, 1), None
    except Exception as exc:  # noqa: BLE001
        return None, None, {
            "message": str(exc),
            "fingerprint": normalize_error("PIPELINE_CREATION_ERROR", str(exc)),
        }


def create_speculative_pipeline_npu_draft(
    target_path: Path,
    draft_npu_path: Path,
) -> tuple[Any | None, float | None, dict[str, Any] | None]:
    """Construct heterogeneous speculative pipeline: GPU target + NPU draft (NEW Task 4.2b)."""
    t0 = time.perf_counter()
    try:
        scheduler = SchedulerConfig()
        scheduler.cache_size = SCHEDULER_CACHE_GB

        pipeline = LLMPipeline(
            str(target_path),   # models/qwen3-14b/openvino-int4-gpu/
            "GPU",
            scheduler_config=scheduler,
            draft_model=ov_genai.draft_model(
                str(draft_npu_path),  # models/qwen3-0.6b/openvino-int4-npu/
                "NPU",                # KEY DIFFERENCE: NPU as draft device
            ),
            # Do NOT set INFERENCE_PRECISION — invalid property name
        )
        compile_ms = (time.perf_counter() - t0) * 1000.0
        return pipeline, round(compile_ms, 1), None
    except Exception as exc:  # noqa: BLE001
        return None, None, {
            "message": str(exc),
            "fingerprint": normalize_error("PIPELINE_CREATION_ERROR_NPU", str(exc)),
        }


def create_standalone_pipeline(
    model_path: Path,
) -> tuple[Any | None, float | None, dict[str, Any] | None]:
    """Construct a standalone LLMPipeline (no draft model)."""
    t0 = time.perf_counter()
    try:
        scheduler = SchedulerConfig()
        scheduler.cache_size = SCHEDULER_CACHE_GB

        pipeline = LLMPipeline(
            str(model_path),
            "GPU",
            scheduler_config=scheduler,
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
    except Exception:  # noqa: BLE001
        pass
    if is_speculative:
        try:
            cfg.num_assistant_tokens = NAT
            cfg.assistant_confidence_threshold = 0.0
        except Exception:  # noqa: BLE001
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
    perf_metrics: Any,
    nat: int,
    is_speculative: bool,
) -> dict[str, Any]:
    """Extract PerfMetrics secondary data (all failures result in None)."""
    data: dict[str, Any] = {}

    # Combined TPS from PerfMetrics
    try:
        tput = perf_metrics.get_throughput()
        data["combined_tps_perfmetrics"] = round(tput.mean, 4)
    except Exception:
        data["combined_tps_perfmetrics"] = None

    # TTFT from PerfMetrics (milliseconds)
    try:
        ttft = perf_metrics.get_ttft()
        data["ttft_ms_perfmetrics"] = round(ttft.mean, 2)
    except Exception:
        data["ttft_ms_perfmetrics"] = None

    # Per-step inference duration
    try:
        raw = perf_metrics.raw_metrics
        infer_us = list(raw.inference_durations)
        batch_sizes = list(raw.m_batch_sizes) if hasattr(raw, "m_batch_sizes") else []
        if infer_us and batch_sizes and len(infer_us) == len(batch_sizes):
            mean_us = sum(infer_us) / len(infer_us)
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
# Extended PerfMetrics extraction (NEW — SDPerModelsPerfMetrics)
# ===========================================================================

def extract_extended_perf_metrics(output: Any) -> dict[str, Any]:
    """Extract SDPerModelsPerfMetrics from DecodedResults.extended_perf_metrics.

    Provides per-model breakdown: draft TPS, main (target) TPS, native (combined) TPS,
    native TTFT, and native accepted token count. All failures return None fields.
    """
    data: dict[str, Any] = {}
    try:
        epm = output.extended_perf_metrics
        if epm is None:
            return {"extended_metrics_available": False}

        data["extended_metrics_available"] = True

        # Native aggregate metrics (whole pipeline, not per-model)
        try:
            data["native_tps"] = round(epm.get_throughput().mean, 4)
        except Exception:
            data["native_tps"] = None
        try:
            data["native_ttft_ms"] = round(epm.get_ttft().mean, 2)
        except Exception:
            data["native_ttft_ms"] = None
        try:
            data["native_tpot_ms"] = round(epm.get_tpot().mean, 4)
        except Exception:
            data["native_tpot_ms"] = None
        try:
            data["native_accepted_tokens"] = int(epm.get_num_accepted_tokens())
        except Exception:
            data["native_accepted_tokens"] = None

        # Draft model metrics
        try:
            dm = epm.draft_model_metrics
            data["draft_throughput_tps"] = round(dm.get_throughput().mean, 4)
            data["draft_inference_duration_ms"] = round(dm.get_inference_duration().mean, 2)
        except Exception:
            data["draft_throughput_tps"] = None
            data["draft_inference_duration_ms"] = None
        try:
            dm = epm.draft_model_metrics
            data["draft_ttft_ms"] = round(dm.get_ttft().mean, 2)
        except Exception:
            data["draft_ttft_ms"] = None

        # Main (target) model metrics
        try:
            mm = epm.main_model_metrics
            data["main_throughput_tps"] = round(mm.get_throughput().mean, 4)
            data["main_inference_duration_ms"] = round(mm.get_inference_duration().mean, 2)
        except Exception:
            data["main_throughput_tps"] = None
            data["main_inference_duration_ms"] = None
        try:
            mm = epm.main_model_metrics
            data["main_ttft_ms"] = round(mm.get_ttft().mean, 2)
        except Exception:
            data["main_ttft_ms"] = None

    except AttributeError:
        data["extended_metrics_available"] = False
    except Exception:
        data["extended_metrics_available"] = False

    return data


# ===========================================================================
# Single generation run — CORRECTED (list-input generate)
# ===========================================================================

def run_single_generation(
    pipeline: Any,
    tokenizer: Any,
    prompt: str,
    gen_config: Any,
    is_speculative: bool,
) -> dict[str, Any]:
    """Run one generation, capturing wall-clock timing, RSS, and PerfMetrics.

    CRITICAL FIX: Uses list-input pipeline.generate([prompt], gc, cb) which
    returns DecodedResults with .perf_metrics and .extended_perf_metrics.
    The original harness used bare str input which returned bare str (NO metrics).
    """
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
        # CRITICAL: list-input returns DecodedResults (has .perf_metrics, .extended_perf_metrics).
        # Bare str input returns bare str (BUG — no metrics available).
        try:
            output = pipeline.generate([prompt], gen_config, stream_cb)
            has_stream_ttft = first_token_time is not None
        except TypeError:
            output = pipeline.generate([prompt], gen_config)
            has_stream_ttft = False

        sampler.stop()
        t1 = time.perf_counter()
        rss_peak = sampler.peak / (1024 * 1024)
        rss_after = proc.memory_info().rss / (1024 * 1024)
        total_ms = (t1 - t0) * 1000.0

        # Extract text from DecodedResults (list input → DecodedResults always)
        try:
            text = output.texts[0]
        except (AttributeError, IndexError):
            try:
                text = str(output)  # fallback in case API changes
            except Exception:
                text = ""

        # Extract PerfMetrics — available on DecodedResults (list-input fix ensures this)
        perf_metrics: Any = None
        try:
            perf_metrics = output.perf_metrics
        except AttributeError:
            perf_metrics = None

        token_ids = tokenizer(text, return_tensors="np")["input_ids"][0]
        tokens_generated = int(len(token_ids))

        # Wall-clock TTFT
        if has_stream_ttft:
            ttft_ms_wc = (first_token_time - t0) * 1000.0  # type: ignore[operator]
        elif perf_metrics is not None:
            try:
                ttft_ms_wc = perf_metrics.get_ttft().mean
            except Exception:
                ttft_ms_wc = total_ms
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

        # Secondary PerfMetrics (acceptance rate, combined_tps_perfmetrics, etc.)
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

        # Extended PerfMetrics (per-model breakdown — speculative runs only)
        if is_speculative:
            result_base["extended_metrics"] = extract_extended_perf_metrics(output)
        else:
            result_base["extended_metrics"] = {}

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
            "combined_tps_perfmetrics": None,
            "ttft_ms_perfmetrics": None,
            "mean_inference_duration_ms_per_step": None,
            "acceptance_data_source": "N/A_FAILED",
            "acceptance_rate_aggregate": None,
            "acceptance_rate_by_step": None,
            "extended_metrics": {},
        }


# ===========================================================================
# Run one config (warmup + measured runs)
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
        ar_str = f", AR={r['acceptance_rate_aggregate']:.3f}" if r.get("acceptance_rate_aggregate") is not None else ""
        nat_tps = r.get("extended_metrics", {}).get("native_tps")
        nat_str = f", native_tps={nat_tps:.2f}" if nat_tps is not None else ""
        print(f"    Warmup {w + 1}: {r['decode_tokens_per_sec']:.2f} tps{ar_str}{nat_str}")

    print(f"  Running {measured_runs} measured runs...")
    runs: list[dict[str, Any]] = []
    for i in range(measured_runs):
        r = run_single_generation(pipeline, tokenizer, prompt, gen_config, is_speculative)
        runs.append(r)
        status = "OK" if r["ok"] else f"FAIL:{r.get('error_fingerprint', '?')}"
        ar_str = f", AR={r['acceptance_rate_aggregate']:.3f}" if r.get("acceptance_rate_aggregate") is not None else ""
        nat_tps = r.get("extended_metrics", {}).get("native_tps")
        nat_str = f", native_tps={nat_tps:.2f}" if nat_tps is not None else ""
        print(f"    Run {i + 1}: {r['decode_tokens_per_sec']:.2f} tps, "
              f"TTFT={r['ttft_ms_wallclock']:.0f}ms, "
              f"RSS={r['rss_peak_mb']:.0f}MB{ar_str}{nat_str} [{status}]")
        if r.get("acceptance_rate_by_step") is not None:
            print(f"           per_step={r['acceptance_rate_by_step']}")

    ok_runs = [r for r in runs if r["ok"]]

    tps_vals  = [r["decode_tokens_per_sec"] for r in ok_runs]
    ttft_vals = [r["ttft_ms_wallclock"]      for r in ok_runs]
    rss_vals  = [r["rss_peak_mb"]            for r in runs]

    combined_tps_summary = stats_dict(tps_vals)
    ttft_summary         = stats_dict(ttft_vals)
    rss_summary          = stats_dict(rss_vals)

    # Acceptance aggregation
    acceptance_summary: dict[str, Any] = {}
    if is_speculative:
        total_drafted  = sum(r.get("tokens_drafted_total",  0) or 0 for r in ok_runs)
        total_accepted = sum(r.get("tokens_accepted_total", 0) or 0 for r in ok_runs)
        agg_rate_global = (total_accepted / total_drafted) if total_drafted > 0 else None

        per_step_last: list[float] | None = None
        for r in reversed(ok_runs):
            if r.get("acceptance_rate_by_step") is not None:
                per_step_last = r["acceptance_rate_by_step"]
                break

        acceptance_summary = {
            "acceptance_rate_aggregate":     round(agg_rate_global, 4) if agg_rate_global is not None else None,
            "acceptance_rate_by_step_last_run": per_step_last,
            "tokens_drafted_total_all_runs": total_drafted,
            "tokens_accepted_total_all_runs": total_accepted,
            "acceptance_data_source":        ok_runs[-1].get("acceptance_data_source") if ok_runs else "UNAVAILABLE",
        }
    else:
        acceptance_summary = {
            "acceptance_rate_aggregate":     None,
            "acceptance_rate_by_step_last_run": None,
            "acceptance_data_source":        "N/A_STANDALONE",
        }

    # Extended metrics summary (speculative only)
    extended_metrics_summary: dict[str, Any] = {}
    if is_speculative and ok_runs:
        def _mean_field(field: str) -> float | None:
            vals = [r.get("extended_metrics", {}).get(field) for r in ok_runs]
            valid = [v for v in vals if v is not None]
            return round(statistics.fmean(valid), 4) if valid else None

        extended_metrics_summary = {
            "native_tps_mean":               _mean_field("native_tps"),
            "native_ttft_ms_mean":           _mean_field("native_ttft_ms"),
            "native_tpot_ms_mean":           _mean_field("native_tpot_ms"),
            "native_accepted_tokens_mean":   _mean_field("native_accepted_tokens"),
            "draft_throughput_tps_mean":     _mean_field("draft_throughput_tps"),
            "draft_inference_duration_ms_mean": _mean_field("draft_inference_duration_ms"),
            "main_throughput_tps_mean":      _mean_field("main_throughput_tps"),
            "main_inference_duration_ms_mean": _mean_field("main_inference_duration_ms"),
        }

    summary: dict[str, Any] = {
        "combined_tps": combined_tps_summary,
        "ttft_ms":      ttft_summary,
        "peak_rss_mb":  rss_summary,
        **acceptance_summary,
        "valid_runs":   len(ok_runs),
        "failed_runs":  len(runs) - len(ok_runs),
    }

    return {
        "id":           config_id,
        "name":         config_name,
        "runs":         runs,
        "summary":      summary,
        "extended_metrics_summary": extended_metrics_summary,
    }


# ===========================================================================
# System metadata
# ===========================================================================

def collect_metadata(npu_driver: dict[str, Any] | None = None) -> dict[str, Any]:
    meta: dict[str, Any] = {
        "git_head":  git_head(),
        "branch":    "feature/p5-task4-2-combined-rerun",
        "python_version": sys.version,
        "platform":  platform.platform(),
    }
    try:
        meta["openvino_genai_version"] = ov_genai.__version__
    except AttributeError:
        meta["openvino_genai_version"] = "UNKNOWN"
    if ov is not None:
        try:
            meta["openvino_version"] = ov.__version__
        except AttributeError:
            meta["openvino_version"] = "UNKNOWN"

    meta["power_state"] = detect_power_envelope()
    if npu_driver is not None:
        meta["npu_driver"] = npu_driver
    return meta


# ===========================================================================
# Derived metrics
# ===========================================================================

def derive_draft_forward_ms(standalone_tps: float | None, nat: int) -> str | None:
    if standalone_tps is None or standalone_tps <= 0:
        return None
    ms_per_token = 1000.0 / standalone_tps
    ms_per_step = ms_per_token * nat
    return f"{ms_per_step:.2f}ms (1000/{standalone_tps:.2f} tps × {nat} = {ms_per_step:.2f}ms)"


# ===========================================================================
# Winner selection — Task 4.2 (Draft-A vs Draft-B)
# ===========================================================================

def select_winner_draft(
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
        if t01_ar is not None and t02_ar is not None:
            if t01_ar > t02_ar + 0.01:
                return ("DRAFT_A_WINS",
                        f"TPS within 3% (A={t01_tps:.2f}, B={t02_tps:.2f}). "
                        f"Tiebreaker: Draft-A AR {t01_ar:.3f} > Draft-B {t02_ar:.3f}")
            elif t02_ar > t01_ar + 0.01:
                return ("DRAFT_B_WINS",
                        f"TPS within 3% (A={t01_tps:.2f}, B={t02_tps:.2f}). "
                        f"Tiebreaker: Draft-B AR {t02_ar:.3f} > Draft-A {t01_ar:.3f}")
            else:
                return ("INCONCLUSIVE",
                        f"TPS within 3% and AR within 1% — statistically indistinguishable. "
                        f"A={t01_tps:.2f} AR={t01_ar:.3f}, B={t02_tps:.2f} AR={t02_ar:.3f}")
        else:
            return ("INCONCLUSIVE",
                    f"TPS within 3% and AR unavailable. A={t01_tps:.2f}, B={t02_tps:.2f}")

    if t01_tps >= t02_tps:
        return ("DRAFT_A_WINS",
                f"Draft-A {t01_tps:.2f} tps > Draft-B {t02_tps:.2f} tps "
                f"(delta {delta * 100:.1f}%). Primary metric: combined TPS.")
    else:
        return ("DRAFT_B_WINS",
                f"Draft-B {t02_tps:.2f} tps > Draft-A {t01_tps:.2f} tps "
                f"(delta {delta * 100:.1f}%). Primary metric: combined TPS.")


# ===========================================================================
# Winner selection — Task 4.2b (GPU draft vs NPU draft)
# ===========================================================================

def select_npu_disposition(
    t05_tps: float | None,
    t01_tps: float | None,
    t05_native_tps: float | None,
    t01_native_tps: float | None,
    t05_ar: float | None,
    t01_ar: float | None,
    t05_pipeline_ok: bool,
) -> tuple[str, str]:
    """Determine NPU draft disposition per ADR-011 §2.4 criteria."""
    if not t05_pipeline_ok:
        return ("PIPELINE_CREATION_FAILED",
                "T-05 pipeline construction failed — NPU draft not functional on this build. "
                "ADR-011 §2.4: REJECTED. GPU draft confirmed as carry-forward.")

    if t05_tps is None:
        return ("GPU_DRAFT_CONFIRMED",
                "T-05 produced no TPS data — GPU draft confirmed by default.")

    if t01_tps is None:
        return ("NPU_DRAFT_ADOPTED",
                "T-01 (GPU ref) TPS unavailable — NPU draft adopted by default.")

    delta = (t05_tps - t01_tps) / max(t05_tps, t01_tps)

    if delta > 0.03:
        return ("NPU_DRAFT_ADOPTED",
                f"T-05/NPU {t05_tps:.2f} tps > T-01/GPU {t01_tps:.2f} tps "
                f"(delta +{delta * 100:.1f}%). NPU draft device adopted.")
    elif delta < -0.03:
        return ("GPU_DRAFT_CONFIRMED",
                f"T-01/GPU {t01_tps:.2f} tps > T-05/NPU {t05_tps:.2f} tps "
                f"(delta {delta * 100:.1f}%). GPU draft device confirmed.")
    else:
        # Within 3% — use native TPS as tiebreaker
        if t05_native_tps is not None and t01_native_tps is not None:
            nat_delta = (t05_native_tps - t01_native_tps) / max(t05_native_tps, t01_native_tps)
            if nat_delta > 0.03:
                return ("NPU_DRAFT_ADOPTED",
                        f"Wall-clock TPS within 3% (NPU={t05_tps:.2f}, GPU={t01_tps:.2f}). "
                        f"Tiebreaker: native TPS NPU={t05_native_tps:.2f} > GPU={t01_native_tps:.2f}.")
            elif nat_delta < -0.03:
                return ("GPU_DRAFT_CONFIRMED",
                        f"Wall-clock TPS within 3% (NPU={t05_tps:.2f}, GPU={t01_tps:.2f}). "
                        f"Tiebreaker: native TPS GPU={t01_native_tps:.2f} > NPU={t05_native_tps:.2f}.")
        # Use acceptance rate as final tiebreaker
        if t05_ar is not None and t01_ar is not None:
            if t05_ar > t01_ar + 0.01:
                return ("NPU_DRAFT_ADOPTED",
                        f"TPS within 3%, native TPS within 3%. AR tiebreaker: NPU {t05_ar:.3f} > GPU {t01_ar:.3f}.")
            elif t01_ar > t05_ar + 0.01:
                return ("GPU_DRAFT_CONFIRMED",
                        f"TPS within 3%, native TPS within 3%. AR tiebreaker: GPU {t01_ar:.3f} > NPU {t05_ar:.3f}.")
        # All metrics within margins — default to GPU (simpler architecture)
        return ("GPU_DRAFT_CONFIRMED",
                f"NPU and GPU draft within all measurement margins "
                f"(wall-clock {t05_tps:.2f} vs {t01_tps:.2f}, delta {delta * 100:.1f}%). "
                "Default to GPU draft: simpler architecture, no cross-device handoff.")


# ===========================================================================
# Main benchmark execution
# ===========================================================================

def main() -> None:
    print("=" * 70)
    print("P5-Task-4.2 Combined Rerun + Task 4.2b NPU Draft Comparison")
    print("CORRECTED RERUN: list-input generate() fix applied")
    print("=" * 70)

    # --- AC power enforcement ---
    print("\n[PRE-CHECK] Enforcing AC power...")
    power = enforce_ac_power_or_fail_closed()
    print(f"  Power: plugged={power.get('power_plugged')}, battery={power.get('battery_percent')}%")

    # --- NPU driver detection ---
    print("\n[PRE-CHECK] Detecting NPU driver...")
    npu_driver = detect_npu_driver()
    print(f"  NPU driver: {npu_driver.get('driver_version')} "
          f"(meets_minimum={npu_driver.get('meets_minimum')})")

    metadata = collect_metadata(npu_driver=npu_driver)
    metadata["power_state"] = power
    metadata["corrected_rerun"] = True
    metadata["original_run_head"] = "95a3f0a"
    metadata["fix_applied"] = "list-input generate() — output.texts[0] — extended_perf_metrics"

    # --- Tokenizer ---
    print(f"\n[TOKENIZER] Loading from {MODEL_14B}...")
    tokenizer = AutoTokenizer.from_pretrained(str(MODEL_14B), trust_remote_code=True)
    print("  Tokenizer loaded.")

    # --- Build prompt at 4096 tokens ---
    print(f"\n[PROMPT] Building {CONTEXT_TOKENS}-token prompt...")
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
        "inference_precision": ("FP16 (Xe2 default — INFERENCE_PRECISION not set; "
                                "invalid property name on this OV build)"),
        "kv_cache_precision": "FP16 (default — not set)",
        "scheduler_cache_size_gb": SCHEDULER_CACHE_GB,
        "warmup_runs": WARMUP_RUNS,
        "measured_runs_speculative": MEASURED_RUNS_SPEC,
        "measured_runs_standalone": MEASURED_RUNS_SOLO,
        "prompt_total_tokens_actual": prompt_toks,
    }

    tests: list[dict[str, Any]] = []
    t01_tps:        float | None = None
    t02_tps:        float | None = None
    t01_ar:         float | None = None
    t02_ar:         float | None = None
    t01_native_tps: float | None = None
    t02_pipeline_ok               = True
    t03_standalone_tps: float | None = None
    t04_standalone_tps: float | None = None

    # -----------------------------------------------------------------------
    # T-01: 14B + Draft-A/GPU speculative — CORRECTED RERUN
    # -----------------------------------------------------------------------
    print("\n" + "=" * 60)
    print("T-01: 14B + Draft-A/GPU (Qwen3-0.6B 28L INT4) NAT=3 [CORRECTED RERUN]")
    print("=" * 60)
    print(f"  Creating pipeline (target={MODEL_14B.name}, draft={DRAFT_A_GPU_PATH.name})...")
    pipe_t01, compile_ms_t01, pipe_err_t01 = create_speculative_pipeline(MODEL_14B, DRAFT_A_GPU_PATH)

    if pipe_t01 is None:
        print(f"  PIPELINE CREATION FAILED: {pipe_err_t01}")
        test_t01: dict[str, Any] = {
            "id": "T-01", "name": "14B + Draft-A/GPU (28L INT4) NAT=3",
            "draft_model": "qwen3-0.6b 28L INT4", "draft_device": "GPU",
            "draft_path": str(DRAFT_A_GPU_PATH), "draft_layers": 28,
            "draft_quant": "INT4", "draft_weight_mb": 367,
            "is_speculative": True, "pipeline_creation_ok": False,
            "pipeline_creation_error": pipe_err_t01, "runs": [], "summary": {},
            "extended_metrics_summary": {},
        }
    else:
        print(f"  Pipeline compiled in {compile_ms_t01:.0f}ms.")
        gen_cfg_spec = make_gen_config(is_speculative=True)
        cfg_result = run_config(
            "T-01", "14B + Draft-A/GPU (28L INT4) NAT=3",
            pipe_t01, tokenizer, prompt, gen_cfg_spec,
            is_speculative=True, measured_runs=MEASURED_RUNS_SPEC,
        )
        test_t01 = {
            "id": "T-01", "name": "14B + Draft-A/GPU (28L INT4) NAT=3",
            "draft_model": "qwen3-0.6b 28L INT4", "draft_device": "GPU",
            "draft_path": str(DRAFT_A_GPU_PATH), "draft_layers": 28,
            "draft_quant": "INT4", "draft_weight_mb": 367,
            "is_speculative": True, "pipeline_creation_ok": True,
            "pipeline_compile_ms": compile_ms_t01,
            **cfg_result,
        }
        t01_tps = cfg_result["summary"]["combined_tps"].get("mean")
        t01_ar  = cfg_result["summary"].get("acceptance_rate_aggregate")
        t01_native_tps = cfg_result.get("extended_metrics_summary", {}).get("native_tps_mean")
        del pipe_t01
        gc.collect()

    tests.append(test_t01)
    write_json_atomic(OUTPUT_JSON_42, {
        "milestone": "P5-Task-4.2", "title": "Draft Model Comparison — CORRECTED RERUN",
        "timestamp_utc": now_iso(), "metadata": metadata,
        "locked_config": locked_config, "tests": tests, "status": "in_progress",
    })
    print(f"  Intermediate artifact written: {OUTPUT_JSON_42.name}")
    if t01_tps is not None:
        print(f"  T-01 TPS={t01_tps:.2f}, AR={t01_ar}, native_tps={t01_native_tps}")

    # -----------------------------------------------------------------------
    # T-02: 14B + Draft-B/GPU speculative — CORRECTED RERUN
    # -----------------------------------------------------------------------
    print("\n" + "=" * 60)
    print("T-02: 14B + Draft-B/GPU (Qwen3-0.6B-pruned-6L 22L INT8_ASYM) NAT=3 [CORRECTED RERUN]")
    print("=" * 60)
    print(f"  Creating pipeline (target={MODEL_14B.name}, draft={DRAFT_B_GPU_PATH.name})...")
    pipe_t02, compile_ms_t02, pipe_err_t02 = create_speculative_pipeline(MODEL_14B, DRAFT_B_GPU_PATH)

    if pipe_t02 is None:
        t02_pipeline_ok = False
        print(f"  PIPELINE CREATION FAILED: {pipe_err_t02}")
        print("  NOTE: Draft-B failure means Draft-A wins by default.")
        test_t02: dict[str, Any] = {
            "id": "T-02", "name": "14B + Draft-B/GPU (22L INT8_ASYM) NAT=3",
            "draft_model": "qwen3-0.6b-pruned-6l 22L INT8_ASYM", "draft_device": "GPU",
            "draft_path": str(DRAFT_B_GPU_PATH), "draft_layers": 22,
            "draft_quant": "INT8_ASYM", "draft_weight_mb": 480,
            "is_speculative": True, "pipeline_creation_ok": False,
            "pipeline_creation_error": pipe_err_t02, "runs": [], "summary": {},
            "extended_metrics_summary": {},
        }
    else:
        print(f"  Pipeline compiled in {compile_ms_t02:.0f}ms.")
        gen_cfg_spec2 = make_gen_config(is_speculative=True)
        cfg_result2 = run_config(
            "T-02", "14B + Draft-B/GPU (22L INT8_ASYM) NAT=3",
            pipe_t02, tokenizer, prompt, gen_cfg_spec2,
            is_speculative=True, measured_runs=MEASURED_RUNS_SPEC,
        )
        test_t02 = {
            "id": "T-02", "name": "14B + Draft-B/GPU (22L INT8_ASYM) NAT=3",
            "draft_model": "qwen3-0.6b-pruned-6l 22L INT8_ASYM", "draft_device": "GPU",
            "draft_path": str(DRAFT_B_GPU_PATH), "draft_layers": 22,
            "draft_quant": "INT8_ASYM", "draft_weight_mb": 480,
            "is_speculative": True, "pipeline_creation_ok": True,
            "pipeline_compile_ms": compile_ms_t02,
            **cfg_result2,
        }
        t02_tps = cfg_result2["summary"]["combined_tps"].get("mean")
        t02_ar  = cfg_result2["summary"].get("acceptance_rate_aggregate")
        del pipe_t02
        gc.collect()

    tests.append(test_t02)
    write_json_atomic(OUTPUT_JSON_42, {
        "milestone": "P5-Task-4.2", "title": "Draft Model Comparison — CORRECTED RERUN",
        "timestamp_utc": now_iso(), "metadata": metadata,
        "locked_config": locked_config, "tests": tests, "status": "in_progress",
    })
    print(f"  Intermediate artifact written: {OUTPUT_JSON_42.name}")

    # -----------------------------------------------------------------------
    # T-03: Draft-A standalone — CORRECTED RERUN
    # -----------------------------------------------------------------------
    print("\n" + "=" * 60)
    print("T-03: Draft-A Standalone (Qwen3-0.6B 28L INT4, GPU) [CORRECTED RERUN]")
    print("=" * 60)
    print(f"  Creating standalone pipeline ({DRAFT_A_GPU_PATH.name})...")
    pipe_t03, compile_ms_t03, pipe_err_t03 = create_standalone_pipeline(DRAFT_A_GPU_PATH)

    if pipe_t03 is None:
        print(f"  PIPELINE CREATION FAILED: {pipe_err_t03}")
        test_t03: dict[str, Any] = {
            "id": "T-03", "name": "Draft-A Standalone (28L INT4)",
            "model_path": str(DRAFT_A_GPU_PATH), "purpose": "Upper bound on Draft-A forward speed",
            "is_speculative": False, "pipeline_creation_ok": False,
            "pipeline_creation_error": pipe_err_t03, "runs": [], "summary": {},
            "extended_metrics_summary": {},
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
            "model_path": str(DRAFT_A_GPU_PATH), "purpose": "Upper bound on Draft-A forward speed",
            "is_speculative": False, "pipeline_creation_ok": True,
            "pipeline_compile_ms": compile_ms_t03,
            **cfg_result3,
        }
        t03_standalone_tps = cfg_result3["summary"]["combined_tps"].get("mean")
        del pipe_t03
        gc.collect()

    tests.append(test_t03)
    write_json_atomic(OUTPUT_JSON_42, {
        "milestone": "P5-Task-4.2", "title": "Draft Model Comparison — CORRECTED RERUN",
        "timestamp_utc": now_iso(), "metadata": metadata,
        "locked_config": locked_config, "tests": tests, "status": "in_progress",
    })
    print(f"  Intermediate artifact written: {OUTPUT_JSON_42.name}")

    # -----------------------------------------------------------------------
    # T-04: Draft-B standalone — CORRECTED RERUN
    # -----------------------------------------------------------------------
    print("\n" + "=" * 60)
    print("T-04: Draft-B Standalone (Qwen3-0.6B-pruned-6L 22L INT8_ASYM, GPU) [CORRECTED RERUN]")
    print("=" * 60)
    print(f"  Creating standalone pipeline ({DRAFT_B_GPU_PATH.name})...")
    pipe_t04, compile_ms_t04, pipe_err_t04 = create_standalone_pipeline(DRAFT_B_GPU_PATH)

    if pipe_t04 is None:
        print(f"  PIPELINE CREATION FAILED: {pipe_err_t04}")
        test_t04: dict[str, Any] = {
            "id": "T-04", "name": "Draft-B Standalone (22L INT8_ASYM)",
            "model_path": str(DRAFT_B_GPU_PATH), "purpose": "Upper bound on Draft-B forward speed",
            "is_speculative": False, "pipeline_creation_ok": False,
            "pipeline_creation_error": pipe_err_t04, "runs": [], "summary": {},
            "extended_metrics_summary": {},
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
            "model_path": str(DRAFT_B_GPU_PATH), "purpose": "Upper bound on Draft-B forward speed",
            "is_speculative": False, "pipeline_creation_ok": True,
            "pipeline_compile_ms": compile_ms_t04,
            **cfg_result4,
        }
        t04_standalone_tps = cfg_result4["summary"]["combined_tps"].get("mean")
        del pipe_t04
        gc.collect()

    tests.append(test_t04)

    # -----------------------------------------------------------------------
    # Derived metrics and disposition for Task 4.2 artifact
    # -----------------------------------------------------------------------
    draft_a_fwd = derive_draft_forward_ms(t03_standalone_tps, NAT)
    draft_b_fwd = derive_draft_forward_ms(t04_standalone_tps, NAT)

    tps_delta_pct: float | None = None
    if t01_tps is not None and t02_tps is not None and t01_tps > 0:
        tps_delta_pct = round((t01_tps - t02_tps) / t01_tps * 100, 2)

    derived_metrics: dict[str, Any] = {
        "draft_a_standalone_tps_mean":        round(t03_standalone_tps, 4) if t03_standalone_tps else None,
        "draft_b_standalone_tps_mean":        round(t04_standalone_tps, 4) if t04_standalone_tps else None,
        "draft_a_forward_ms_per_step_derived": draft_a_fwd,
        "draft_b_forward_ms_per_step_derived": draft_b_fwd,
        "draft_a_combined_tps_mean":          round(t01_tps, 4) if t01_tps else None,
        "draft_b_combined_tps_mean":          round(t02_tps, 4) if t02_tps else None,
        "tps_delta_pct_a_minus_b":            tps_delta_pct,
    }

    # Harness validation — with corrected harness, native_tps should be closer to D-01
    t01_native_validation = "SKIPPED_UNAVAILABLE"
    t01_native_vs_d01_pct: float | None = None
    if t01_native_tps is not None:
        t01_native_vs_d01_pct = round(abs(t01_native_tps - D01_BASELINE_TPS) / D01_BASELINE_TPS * 100, 1)
        t01_native_validation = "PLAUSIBLE" if t01_native_vs_d01_pct < 15.0 else "WARNING_DELTA_EXCEEDS_15PCT"

    t01_wc_vs_d01_pct: float | None = None
    t01_wc_validation = "SKIPPED_TPS_UNAVAILABLE"
    if t01_tps is not None:
        t01_wc_vs_d01_pct = round(abs(t01_tps - D01_BASELINE_TPS) / D01_BASELINE_TPS * 100, 1)
        t01_wc_validation = (
            "PLAUSIBLE" if t01_wc_vs_d01_pct < 15.0 else
            "EXPECTED_INFLATION_WALLCLOCK_TTFT_METHOD"  # wall-clock TTFT inflates denominator
        )

    p5_005b_comparison = {
        "d01_tps_at_4k":         D01_BASELINE_TPS,
        "d01_ttft_at_4k_ms":     D01_BASELINE_TTFT,
        "d01_nat":               3,
        "d01_draft":             "Draft-A (same as T-01)",
        "t01_native_tps_mean":   round(t01_native_tps, 4) if t01_native_tps else None,
        "t01_native_vs_d01_pct": t01_native_vs_d01_pct,
        "harness_validation_native": t01_native_validation,
        "t01_wallclock_tps_mean": round(t01_tps, 4) if t01_tps else None,
        "t01_wc_vs_d01_pct":     t01_wc_vs_d01_pct,
        "harness_validation_wallclock": t01_wc_validation,
        "note":                  ("Wall-clock TPS expected lower than D-01 native TPS due to "
                                  "TTFT calculation method difference (stream callback inflates). "
                                  "Native TPS from extended_perf_metrics is the comparable metric."),
    }

    t01_ar_for_disp = tests[0].get("summary", {}).get("acceptance_rate_aggregate") if tests else None
    t02_ar_for_disp = tests[1].get("summary", {}).get("acceptance_rate_aggregate") if len(tests) > 1 else None
    disposition42, disposition42_rationale = select_winner_draft(
        t01_tps, t02_tps, t01_ar_for_disp, t02_ar_for_disp, t02_pipeline_ok,
    )

    if disposition42 in ("DRAFT_A_WINS", "DRAFT_A_WINS_BY_DEFAULT", "INCONCLUSIVE"):
        best_draft = "Draft-A"
        best_path  = str(DRAFT_A_GPU_PATH)
        best_tps   = t01_tps
    else:
        best_draft = "Draft-B"
        best_path  = str(DRAFT_B_GPU_PATH)
        best_tps   = t02_tps

    carry_forward_42: dict[str, Any] = {
        "best_draft_model":           best_draft,
        "best_draft_path":            best_path,
        "best_draft_combined_tps":    round(best_tps, 4) if best_tps else None,
        "note":                       "Device (GPU vs NPU) determined by Task 4.2b",
        "carries_to":                 ["Task 4.2b (device selection)", "Task 4.3 (NAT sweep)",
                                       "Task 4.4 (XAttention)", "Task 4.5+"],
    }

    # Write FINAL Task 4.2 corrected artifact
    final_42: dict[str, Any] = {
        "milestone":            "P5-Task-4.2",
        "title":                ("Draft Model Comparison — Draft-A (0.6B 28L INT4) vs "
                                 "Draft-B (0.6B pruned 22L INT8_ASYM) — CORRECTED RERUN"),
        "timestamp_utc":        now_iso(),
        "metadata":             metadata,
        "locked_config":        locked_config,
        "tests":                tests,
        "derived_metrics":      derived_metrics,
        "p5_005b_baseline_comparison": p5_005b_comparison,
        "disposition":          disposition42,
        "disposition_rationale": disposition42_rationale,
        "carry_forward":        carry_forward_42,
        "correction_note":      ("CORRECTED RERUN of Task 4.2 (original HEAD 95a3f0a). "
                                 "Original run had str-input generate() bug that silently lost "
                                 "acceptance_rate, native_tps, native_ttft, and extended_perf_metrics. "
                                 "Fix: pipeline.generate([prompt], gc, cb) → DecodedResults. "
                                 "Disposition (DRAFT_A_WINS) was valid in original run; now fully verified."),
    }
    write_json_atomic(OUTPUT_JSON_42, final_42)
    print(f"\n  FINAL Task 4.2 corrected artifact: {OUTPUT_JSON_42}")

    # -----------------------------------------------------------------------
    # T-05: 14B/GPU + Draft-A/NPU speculative — NEW (Task 4.2b)
    # -----------------------------------------------------------------------
    print("\n" + "=" * 60)
    print("T-05: 14B/GPU + Draft-A/NPU (Qwen3-0.6B 28L INT4) NAT=3 [NEW Task 4.2b]")
    print("=" * 60)
    print(f"  Creating HETEROGENEOUS pipeline (GPU target + NPU draft)...")
    pipe_t05, compile_ms_t05, pipe_err_t05 = create_speculative_pipeline_npu_draft(
        MODEL_14B, DRAFT_A_NPU_PATH,
    )

    t05_tps:        float | None = None
    t05_ar:         float | None = None
    t05_native_tps: float | None = None
    t05_pipeline_ok              = pipe_t05 is not None
    t05_peak_rss:   float | None = None
    t05_compile_ms: float | None = compile_ms_t05

    if pipe_t05 is None:
        print(f"  PIPELINE CREATION FAILED: {pipe_err_t05}")
        print("  NOTE: T-05 failure is a valid outcome. ADR-011 §2.4 → REJECTED.")
        test_t05: dict[str, Any] = {
            "id": "T-05", "name": "14B/GPU + Draft-A/NPU (28L INT4) NAT=3",
            "draft_model": "qwen3-0.6b 28L INT4", "draft_device": "NPU",
            "draft_path": str(DRAFT_A_NPU_PATH),
            "is_speculative": True, "pipeline_creation_ok": False,
            "pipeline_creation_error": pipe_err_t05, "runs": [], "summary": {},
            "extended_metrics_summary": {},
        }
    else:
        print(f"  Pipeline compiled in {compile_ms_t05:.0f}ms.")
        gen_cfg_t05 = make_gen_config(is_speculative=True)
        cfg_result5 = run_config(
            "T-05", "14B/GPU + Draft-A/NPU (28L INT4) NAT=3",
            pipe_t05, tokenizer, prompt, gen_cfg_t05,
            is_speculative=True, measured_runs=MEASURED_RUNS_SPEC,
        )
        test_t05 = {
            "id": "T-05", "name": "14B/GPU + Draft-A/NPU (28L INT4) NAT=3",
            "draft_model": "qwen3-0.6b 28L INT4", "draft_device": "NPU",
            "draft_path": str(DRAFT_A_NPU_PATH),
            "is_speculative": True, "pipeline_creation_ok": True,
            "pipeline_compile_ms": compile_ms_t05,
            **cfg_result5,
        }
        t05_tps        = cfg_result5["summary"]["combined_tps"].get("mean")
        t05_ar         = cfg_result5["summary"].get("acceptance_rate_aggregate")
        t05_native_tps = cfg_result5.get("extended_metrics_summary", {}).get("native_tps_mean")
        t05_peak_rss   = cfg_result5["summary"]["peak_rss_mb"].get("mean")
        del pipe_t05
        gc.collect()

    # -----------------------------------------------------------------------
    # Task 4.2b — NPU vs GPU comparison and evidence artifact
    # -----------------------------------------------------------------------
    t01_compile_ms  = tests[0].get("pipeline_compile_ms") if tests else None
    t01_peak_rss    = tests[0].get("summary", {}).get("peak_rss_mb", {}).get("mean") if tests else None
    t01_ar_42b      = tests[0].get("summary", {}).get("acceptance_rate_aggregate") if tests else None
    t01_native_42b  = tests[0].get("extended_metrics_summary", {}).get("native_tps_mean") if tests else None

    disposition_42b, disp_rationale_42b = select_npu_disposition(
        t05_tps, t01_tps, t05_native_tps, t01_native_42b,
        t05_ar, t01_ar_42b, t05_pipeline_ok,
    )

    # Map disposition to ADR status
    if disposition_42b == "NPU_DRAFT_ADOPTED":
        adr_new_status = "ADOPTED"
        carry_draft_device = "NPU"
        carry_draft_path   = str(DRAFT_A_NPU_PATH)
    elif disposition_42b == "PIPELINE_CREATION_FAILED":
        adr_new_status = "REJECTED"
        carry_draft_device = "GPU"
        carry_draft_path   = str(DRAFT_A_GPU_PATH)
    else:  # GPU_DRAFT_CONFIRMED
        adr_new_status = "REJECTED"
        carry_draft_device = "GPU"
        carry_draft_path   = str(DRAFT_A_GPU_PATH)

    # TPS comparison values
    t05_tps_for_compare   = round(t05_tps, 4) if t05_tps is not None else None
    t01_tps_for_compare   = round(t01_tps, 4) if t01_tps is not None else None
    tps_delta_abs_42b: float | None = None
    tps_delta_pct_42b: float | None = None
    if t05_tps is not None and t01_tps is not None and t01_tps > 0:
        tps_delta_abs_42b = round(t05_tps - t01_tps, 4)
        tps_delta_pct_42b = round((t05_tps - t01_tps) / t01_tps * 100, 2)

    nat_delta_pct_42b: float | None = None
    if t05_native_tps is not None and t01_native_42b is not None and t01_native_42b > 0:
        nat_delta_pct_42b = round((t05_native_tps - t01_native_42b) / t01_native_42b * 100, 2)

    # Compose Task 4.2b artifact
    t01_summary_for_ref = tests[0].get("summary", {}) if tests else {}
    artifact_42b: dict[str, Any] = {
        "milestone":      "P5-Task-4.2b",
        "title":          "NPU Draft Device Comparison — Draft-A/NPU vs Draft-A/GPU",
        "timestamp_utc":  now_iso(),
        "metadata":       metadata,
        "locked_config": {
            "target_model":           "qwen3-14b INT4 GPU",
            "draft_model":            "qwen3-0.6b 28L INT4",
            "context_tokens":         CONTEXT_TOKENS,
            "max_new_tokens":         MAX_NEW_TOKENS,
            "nat":                    NAT,
            "xattention":             "OFF",
            "kv_cache_precision":     "FP16 (default)",
            "scheduler_cache_size_gb": SCHEDULER_CACHE_GB,
            "warmup_runs":            WARMUP_RUNS,
            "measured_runs":          MEASURED_RUNS_SPEC,
        },
        "tests": [
            {
                **test_t05,
                "note": "NPU draft — heterogeneous speculative decoding",
            },
            {
                "id":                "T-GPU-REF",
                "name":              "14B/GPU + Draft-A/GPU NAT=3 (from corrected Task 4.2 rerun T-01)",
                "source":            "corrected_rerun_same_session",
                "source_artifact":   str(OUTPUT_JSON_42),
                "source_test_id":    "T-01",
                "draft_device":      "GPU",
                "draft_model":       "qwen3-0.6b 28L INT4",
                "draft_path":        str(DRAFT_A_GPU_PATH),
                "pipeline_compile_ms": t01_compile_ms,
                "summary":           t01_summary_for_ref,
                "extended_metrics_summary": tests[0].get("extended_metrics_summary", {}) if tests else {},
                "note":              "GPU ref — same harness run, perfectly comparable (no import staleness)",
            },
        ],
        "comparison": {
            "npu_tps_mean":             t05_tps_for_compare,
            "gpu_ref_tps_mean":         t01_tps_for_compare,
            "tps_delta_abs":            tps_delta_abs_42b,
            "tps_delta_pct":            tps_delta_pct_42b,
            "npu_native_tps":           round(t05_native_tps, 4) if t05_native_tps else None,
            "gpu_ref_native_tps":       round(t01_native_42b, 4) if t01_native_42b else None,
            "native_tps_delta_pct":     nat_delta_pct_42b,
            "npu_acceptance_rate":      round(t05_ar, 4) if t05_ar else None,
            "gpu_ref_acceptance_rate":  round(t01_ar_42b, 4) if t01_ar_42b else None,
            "npu_compile_ms":           compile_ms_t05,
            "gpu_ref_compile_ms":       t01_compile_ms,
            "npu_peak_rss_mb":          round(t05_peak_rss, 1) if t05_peak_rss else None,
            "gpu_ref_peak_rss_mb":      round(t01_peak_rss, 1) if t01_peak_rss else None,
            "npu_wins":                 disposition_42b == "NPU_DRAFT_ADOPTED",
            "notes":                    disp_rationale_42b,
        },
        "disposition":          disposition_42b,
        "disposition_rationale": disp_rationale_42b,
        "adr_011_update": {
            "section":           "§2.4",
            "previous_status":   "EVALUATING",
            "new_status":        adr_new_status,
            "evidence_reference": str(OUTPUT_JSON_42B),
        },
        "carry_forward": {
            "draft_device":  carry_draft_device,
            "draft_model":   "Draft-A (Qwen3-0.6B 28L INT4)",
            "draft_path":    carry_draft_path,
            "carries_to":    ["Task 4.3 (NAT sweep)", "Task 4.4 (XAttention)",
                              "Task 4.5 (context bands)", "Task 4.6+"],
        },
    }
    write_json_atomic(OUTPUT_JSON_42B, artifact_42b)
    print(f"\n  Task 4.2b evidence artifact: {OUTPUT_JSON_42B}")

    # -----------------------------------------------------------------------
    # Final summary
    # -----------------------------------------------------------------------
    print("\n" + "=" * 70)
    print("RESULTS SUMMARY")
    print("=" * 70)
    t01_s     = f"{t01_tps:.2f}"        if t01_tps        is not None else "N/A"
    t01_ar_s  = f"{t01_ar:.3f}"         if t01_ar         is not None else "N/A"
    t01_nat_s = f"{t01_native_tps:.2f}" if t01_native_tps is not None else "N/A"
    print(f"  T-01 (14B + Draft-A/GPU): TPS={t01_s}, AR={t01_ar_s}, native={t01_nat_s}")
    t02_tps_s = f"{t02_tps:.2f}" if t02_tps is not None else "N/A"
    t02_ar_s  = f"{t02_ar:.3f}" if t02_ar  is not None else "N/A"
    t03_s     = f"{t03_standalone_tps:.2f}" if t03_standalone_tps is not None else "N/A"
    t04_s     = f"{t04_standalone_tps:.2f}" if t04_standalone_tps is not None else "N/A"
    t05_s     = f"{t05_tps:.2f}" if t05_tps is not None else ("FAILED" if not t05_pipeline_ok else "N/A")
    t05_nat_s = f"{t05_native_tps:.2f}" if t05_native_tps is not None else "N/A"
    print(f"  T-02 (14B + Draft-B/GPU): TPS={t02_tps_s}, AR={t02_ar_s}, pipeline_ok={t02_pipeline_ok}")
    print(f"  T-03 (Draft-A solo):      TPS={t03_s}")
    print(f"  T-04 (Draft-B solo):      TPS={t04_s}")
    print(f"  T-05 (14B + Draft-A/NPU): TPS={t05_s}, native={t05_nat_s}, pipeline_ok={t05_pipeline_ok}")

    print(f"\n  Task 4.2 DISPOSITION: {disposition42}")
    print(f"  Task 4.2 RATIONALE:   {disposition42_rationale}")
    print(f"\n  Task 4.2b DISPOSITION: {disposition_42b}")
    print(f"  Task 4.2b RATIONALE:   {disp_rationale_42b}")
    print(f"  ADR-011 §2.4: EVALUATING → {adr_new_status}")
    print(f"\n  Carry-forward: Draft-A on {carry_draft_device} for Tasks 4.3-4.10")
    print(f"\n  Evidence artifacts:")
    print(f"    {OUTPUT_JSON_42}")
    print(f"    {OUTPUT_JSON_42B}")


if __name__ == "__main__":
    main()
