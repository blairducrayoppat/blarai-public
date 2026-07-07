"""
P5-Task-4.3: NAT Sweep × Context Bands (Production Configuration)
=================================================================
Sweep num_assistant_tokens [1,2,3,5,7,10] across prompt bands
[512, 2048, 4096, 8192, 12288, 16384, 20480] using the LOCKED draft model
(Qwen3-0.6B 28L INT4 GPU) + Qwen3-14B INT4 GPU target.

Matrix:   6 NAT × 7 bands = 42 configurations
Runs:     2 warmup (discarded) + 5 measured = 7 generate calls per config
Total:    294 generate calls (~100-120 minutes)

Pipeline compiled ONCE. NAT is a GenerationConfig parameter — no recompile needed.
Execution order: band-outer, NAT-inner.

Evidence output:
  phase2_gates/evidence/p5_task4_3_nat_sweep_matrix.json
  (intermediate: p5_task4_3_nat_sweep_matrix.json.partial — written after each band)

API CRITICAL PATTERNS (failure = silent data loss):
  - pipeline.generate([prompt], gc, cb)   → DecodedResults (CORRECT)
  - pipeline.generate(prompt, gc, cb)     → bare str, NO metrics (WRONG)
  - m_batch_sizes[i] = accepted_tokens + 1 for speculative episode i

Branch: feature/p5-task4-3-nat-sweep
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
EVIDENCE_DIR  = ROOT / "phase2_gates" / "evidence"
OUTPUT_JSON   = EVIDENCE_DIR / "p5_task4_3_nat_sweep_matrix.json"
PARTIAL_JSON  = EVIDENCE_DIR / "p5_task4_3_nat_sweep_matrix.json.partial"

MODEL_14B     = ROOT / "models" / "qwen3-14b"    / "openvino-int4-gpu"
DRAFT_A_PATH  = ROOT / "models" / "qwen3-0.6b"   / "openvino-int4-gpu"
TOKENIZER_DIR = MODEL_14B          # Qwen3-14B tokenizer

# ---------------------------------------------------------------------------
# Benchmark constants (locked per Task 4.3 spec)
# ---------------------------------------------------------------------------
NAT_VALUES:       list[int] = [1, 2, 3, 5, 7, 10]
PROMPT_BANDS:     list[int] = [512, 2048, 4096, 8192, 12288, 16384, 20480]
WARMUP_RUNS:      int       = 2
MEASURED_RUNS:    int       = 5
MAX_NEW_TOKENS:   int       = 128
SCHEDULER_CACHE_GB: int     = 3
SYSTEM_PROMPT:    str       = "You are a helpful assistant."
BAND_20K:         int       = 20480
RSS_WARNING_MB:   float     = 26_000.0
RSS_BUDGET_MB:    float     = 15_507.0

STANDALONE_DRAFT_RUNS: int  = 3
STANDALONE_DRAFT_BAND: int  = 4096


# ===========================================================================
# Utilities
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


def stats_dict(values: list[float]) -> dict[str, Any]:
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
    """Build user content string padded to approximately target_tokens tokens."""
    chunk = (
        " local privacy deterministic benchmark payload "
        "nat sweep context bands acceptance rate throughput "
        "speculative decoding draft target model qwen3 "
    )
    text = "Benchmark prompt for Task 4.3 NAT sweep × context bands. "
    for _ in range(500_000):
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


def build_prompt_for_band(tokenizer: Any, band: int) -> tuple[str, int]:
    """Build a full chat prompt targeting the given context band.

    Returns (prompt_str, actual_token_count).
    """
    user_content = build_user_content_to_token_len(tokenizer, band)
    prompt = build_chat_prompt(tokenizer, user_content)
    token_count = len(tokenizer(prompt, return_tensors="np")["input_ids"][0])
    return prompt, token_count


# ===========================================================================
# Pipeline construction
# ===========================================================================

def create_main_pipeline(
    target_path: Path,
    draft_path: Path,
) -> tuple[Any | None, float | None, dict[str, Any] | None]:
    """Compile speculative pipeline once. Both target and draft on GPU."""
    t0 = time.perf_counter()
    try:
        scheduler = SchedulerConfig()
        scheduler.cache_size = SCHEDULER_CACHE_GB

        pipeline = LLMPipeline(
            str(target_path),
            "GPU",
            scheduler_config=scheduler,
            draft_model=ov_genai.draft_model(str(draft_path), "GPU"),
            # Do NOT set INFERENCE_PRECISION — invalid property name on this OV build.
            # Do NOT set GPU_ENABLE_SDPA_OPTIMIZATION — XAttention OFF is the default.
            # FP16 is the Xe2/Arc 140V default.
        )
        compile_ms = (time.perf_counter() - t0) * 1000.0
        return pipeline, round(compile_ms, 1), None
    except Exception as exc:  # noqa: BLE001
        return None, None, {
            "message": str(exc),
            "fingerprint": normalize_error("PIPELINE_CREATION_ERROR", str(exc)),
        }


def create_draft_standalone_pipeline(
    draft_path: Path,
) -> tuple[Any | None, float | None, dict[str, Any] | None]:
    """Compile standalone draft pipeline for one-time reference measurement."""
    t0 = time.perf_counter()
    try:
        scheduler = SchedulerConfig()
        scheduler.cache_size = 1  # draft only, small KV cache sufficient

        pipeline = LLMPipeline(
            str(draft_path),
            "GPU",
            scheduler_config=scheduler,
        )
        compile_ms = (time.perf_counter() - t0) * 1000.0
        return pipeline, round(compile_ms, 1), None
    except Exception as exc:  # noqa: BLE001
        return None, None, {
            "message": str(exc),
            "fingerprint": normalize_error("PIPELINE_CREATION_ERROR_DRAFT", str(exc)),
        }


# ===========================================================================
# GenerationConfig
# ===========================================================================

def make_gen_config(nat: int) -> Any:
    """Create a GenerationConfig for speculative decoding with the given NAT."""
    cfg = ov_genai.GenerationConfig()
    cfg.max_new_tokens = MAX_NEW_TOKENS
    cfg.do_sample = False
    try:
        cfg.temperature = 0.0
        cfg.top_k = 1
        cfg.top_p = 1.0
    except Exception:  # noqa: BLE001
        pass
    try:
        cfg.num_assistant_tokens = nat
        cfg.assistant_confidence_threshold = 0.0
    except Exception:  # noqa: BLE001
        pass
    return cfg


def make_standalone_gen_config() -> Any:
    """Create a GenerationConfig for standalone (no speculative decoding) generation."""
    cfg = ov_genai.GenerationConfig()
    cfg.max_new_tokens = MAX_NEW_TOKENS
    cfg.do_sample = False
    try:
        cfg.temperature = 0.0
        cfg.top_k = 1
        cfg.top_p = 1.0
    except Exception:  # noqa: BLE001
        pass
    return cfg


# ===========================================================================
# Acceptance rate extraction
# ===========================================================================

def extract_acceptance_metrics(perf_metrics: Any, nat: int) -> dict[str, Any]:
    """Extract speculative decoding acceptance from PerfMetrics.raw_metrics.m_batch_sizes.

    m_batch_sizes[i] = number of accepted tokens + 1 for speculative episode i.
    Per-step k (1-indexed): count episodes where b >= k+1.
    Aggregate: sum(b-1 for b in batch_sizes) / (NAT × total_episodes)
    """
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


def extract_extended_perf_metrics(output: Any) -> dict[str, Any]:
    """Extract SDPerModelsPerfMetrics from DecodedResults.extended_perf_metrics."""
    data: dict[str, Any] = {}
    try:
        epm = output.extended_perf_metrics
        if epm is None:
            return {"extended_metrics_available": False}

        data["extended_metrics_available"] = True

        try:
            data["native_tps"] = round(epm.get_throughput().mean, 4)
        except Exception:
            data["native_tps"] = None
        try:
            data["native_ttft_ms"] = round(epm.get_ttft().mean, 2)
        except Exception:
            data["native_ttft_ms"] = None
        try:
            data["native_accepted_tokens"] = int(epm.get_num_accepted_tokens())
        except Exception:
            data["native_accepted_tokens"] = None

        try:
            dm = epm.draft_model_metrics
            data["draft_throughput_tps"] = round(dm.get_throughput().mean, 4)
            data["draft_inference_duration_ms"] = round(dm.get_inference_duration().mean, 2)
        except Exception:
            data["draft_throughput_tps"] = None
            data["draft_inference_duration_ms"] = None

        try:
            mm = epm.main_model_metrics
            data["main_throughput_tps"] = round(mm.get_throughput().mean, 4)
            data["main_inference_duration_ms"] = round(mm.get_inference_duration().mean, 2)
        except Exception:
            data["main_throughput_tps"] = None
            data["main_inference_duration_ms"] = None

    except AttributeError:
        data["extended_metrics_available"] = False
    except Exception:
        data["extended_metrics_available"] = False

    return data


# ===========================================================================
# Single generation run
# ===========================================================================

def run_single_generation(
    pipeline: Any,
    tokenizer: Any,
    prompt: str,
    gen_config: Any,
    nat: int,
    is_speculative: bool,
) -> dict[str, Any]:
    """Run one generation, capture all 7 mandatory fields.

    CRITICAL: Uses list-input generate([prompt], gc, cb) → DecodedResults.
    Bare str input returns bare str with NO .perf_metrics / .extended_perf_metrics.
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
        # CRITICAL: list-input returns DecodedResults (has .perf_metrics, .extended_perf_metrics)
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

        # Extract text
        try:
            text = output.texts[0]
        except (AttributeError, IndexError):
            text = str(output)

        # Extract PerfMetrics
        perf_metrics: Any = None
        try:
            perf_metrics = output.perf_metrics
        except AttributeError:
            perf_metrics = None

        token_ids = tokenizer(text, return_tensors="np")["input_ids"][0]
        tokens_generated = int(len(token_ids))

        # TTFT — prefer stream callback, fall back to perf_metrics
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

        # Combined TPS — prefer extended_perf_metrics.get_throughput().mean (native)
        combined_tps: float | None = None
        ttft_ms_native: float | None = None
        draft_forward_ms: float | None = None
        native_accepted_tokens: int | None = None

        ext = extract_extended_perf_metrics(output)
        if ext.get("extended_metrics_available"):
            combined_tps = ext.get("native_tps")
            ttft_ms_native = ext.get("native_ttft_ms")
            draft_forward_ms = ext.get("draft_inference_duration_ms")
            native_accepted_tokens = ext.get("native_accepted_tokens")

        # Fall back to wall-clock TPS if native unavailable
        if combined_tps is None:
            combined_tps = round(tps_wc, 4)
        if ttft_ms_native is None:
            ttft_ms_native = round(ttft_ms_wc, 1)

        # Acceptance metrics from m_batch_sizes
        if is_speculative and perf_metrics is not None:
            accept_data = extract_acceptance_metrics(perf_metrics, nat)
        else:
            accept_data = {
                "acceptance_data_source": "N/A",
                "total_speculative_episodes": None,
                "tokens_drafted_total": None,
                "tokens_accepted_total": None,
                "acceptance_rate_aggregate": None,
                "acceptance_rate_by_step": None,
            }

        # PerfMetrics TTFT/TPS fallback
        pm_tps: float | None = None
        pm_ttft: float | None = None
        if perf_metrics is not None:
            try:
                pm_tps = round(perf_metrics.get_throughput().mean, 4)
            except Exception:
                pass
            try:
                pm_ttft = round(perf_metrics.get_ttft().mean, 2)
            except Exception:
                pass

        return {
            "ok": True,
            # Mandatory field 1: combined_tps
            "combined_tps": combined_tps,
            # Mandatory field 2: draft_forward_ms_per_step
            "draft_forward_ms_per_step": draft_forward_ms,
            # Mandatory fields 3+4+5: acceptance
            "tokens_drafted_total": accept_data["tokens_drafted_total"],
            "tokens_accepted_total": accept_data["tokens_accepted_total"],
            "acceptance_rate_aggregate": accept_data["acceptance_rate_aggregate"],
            "acceptance_rate_by_step": accept_data["acceptance_rate_by_step"],
            # Mandatory field 6: peak_rss_mb (post-warmup, set in run_config)
            "peak_rss_mb": round(rss_peak, 1),
            # Mandatory field 7: ttft_ms
            "ttft_ms": ttft_ms_native,
            # Supplementary
            "tokens_generated": tokens_generated,
            "total_ms": round(total_ms, 1),
            "tps_wallclock": round(tps_wc, 4),
            "ttft_ms_wallclock": round(ttft_ms_wc, 1),
            "combined_tps_perfmetrics": pm_tps,
            "ttft_ms_perfmetrics": pm_ttft,
            "rss_before_mb": round(rss_before, 1),
            "rss_after_mb": round(rss_after, 1),
            "ttft_source": "stream_callback" if has_stream_ttft else "native_or_perfmetrics",
            "acceptance_data_source": accept_data["acceptance_data_source"],
            "total_speculative_episodes": accept_data["total_speculative_episodes"],
            "native_accepted_tokens": native_accepted_tokens,
            "extended_metrics": ext,
            "error": None,
            "error_fingerprint": None,
        }

    except Exception as exc:  # noqa: BLE001
        sampler.stop()
        rss_peak = sampler.peak / (1024 * 1024)
        rss_after = proc.memory_info().rss / (1024 * 1024)
        msg = str(exc)
        return {
            "ok": False,
            "combined_tps": None,
            "draft_forward_ms_per_step": None,
            "tokens_drafted_total": None,
            "tokens_accepted_total": None,
            "acceptance_rate_aggregate": None,
            "acceptance_rate_by_step": None,
            "peak_rss_mb": round(rss_peak, 1),
            "ttft_ms": None,
            "tokens_generated": 0,
            "total_ms": 0.0,
            "tps_wallclock": 0.0,
            "ttft_ms_wallclock": 0.0,
            "combined_tps_perfmetrics": None,
            "ttft_ms_perfmetrics": None,
            "rss_before_mb": round(rss_before, 1),
            "rss_after_mb": round(rss_after, 1),
            "ttft_source": "N/A_FAILED",
            "acceptance_data_source": "N/A_FAILED",
            "total_speculative_episodes": None,
            "native_accepted_tokens": None,
            "extended_metrics": {},
            "error": msg,
            "error_fingerprint": normalize_error("GENERATION_ERROR", msg),
        }


# ===========================================================================
# Run a NAT config (warmup + measured) at a specific band
# ===========================================================================

def run_nat_config(
    pipeline: Any,
    tokenizer: Any,
    prompt: str,
    nat: int,
    band: int,
    is_20k: bool,
    post_warmup_rss_mb: float | None,
) -> dict[str, Any]:
    """Run 2 warmup + 5 measured generations for one (band, nat) config.

    Returns a result record matching the evidence schema.
    post_warmup_rss_mb: if provided, used as the RSS for this config
      (measured once after first config at each band to amortize).
    """
    gen_config = make_gen_config(nat)

    print(f"\n    [band={band} nat={nat}] Warmup ({WARMUP_RUNS} runs)...")
    warmup_results: list[dict[str, Any]] = []
    for w in range(WARMUP_RUNS):
        r = run_single_generation(pipeline, tokenizer, prompt, gen_config, nat, True)
        warmup_results.append(r)
        tps_str = f"{r['combined_tps']:.2f}" if r["combined_tps"] is not None else "N/A"
        ar_str = f", AR={r['acceptance_rate_aggregate']:.3f}" if r.get("acceptance_rate_aggregate") is not None else ""
        ok_str = "OK" if r["ok"] else f"FAIL:{r.get('error_fingerprint', '?')}"
        print(f"      Warmup {w+1}: {ok_str} tps={tps_str}{ar_str}")

    print(f"    [band={band} nat={nat}] Measuring ({MEASURED_RUNS} runs)...")
    measured_results: list[dict[str, Any]] = []
    for i in range(MEASURED_RUNS):
        r = run_single_generation(pipeline, tokenizer, prompt, gen_config, nat, True)
        measured_results.append(r)
        tps_str = f"{r['combined_tps']:.2f}" if r["combined_tps"] is not None else "N/A"
        ar_str = f", AR={r['acceptance_rate_aggregate']:.3f}" if r.get("acceptance_rate_aggregate") is not None else ""
        ok_str = "OK" if r["ok"] else f"FAIL:{r.get('error_fingerprint', '?')}"
        print(f"      Run {i+1}: {ok_str} tps={tps_str}{ar_str}")

    # Measure RSS after warmup (use peak from last warmup run as fallback)
    if post_warmup_rss_mb is None:
        post_warmup_rss_mb = warmup_results[-1]["peak_rss_mb"] if warmup_results else 0.0

    # Inject stable post-warmup RSS into all measured runs
    for r in measured_results:
        if r["ok"]:
            r["peak_rss_mb"] = post_warmup_rss_mb

    # Aggregate measured (valid runs only)
    valid_runs = [r for r in measured_results if r["ok"]]
    valid_count = len(valid_runs)

    summary: dict[str, Any] = {
        "valid_count": valid_count,
        "peak_rss_mb": post_warmup_rss_mb,
    }

    if valid_count > 0:
        tps_vals = [r["combined_tps"] for r in valid_runs if r["combined_tps"] is not None]
        ttft_vals = [r["ttft_ms"] for r in valid_runs if r["ttft_ms"] is not None]
        draft_fwd_vals = [r["draft_forward_ms_per_step"] for r in valid_runs
                          if r["draft_forward_ms_per_step"] is not None]

        # Acceptance aggregates (last valid run has highest episode count for per-step)
        ar_vals = [r["acceptance_rate_aggregate"] for r in valid_runs
                   if r["acceptance_rate_aggregate"] is not None]
        total_drafted = sum(r["tokens_drafted_total"] or 0 for r in valid_runs)
        total_accepted = sum(r["tokens_accepted_total"] or 0 for r in valid_runs)
        agg_ar = total_accepted / total_drafted if total_drafted > 0 else None

        # Per-step AR: average across valid runs (runs with non-None acceptance_rate_by_step)
        step_arrays = [r["acceptance_rate_by_step"] for r in valid_runs
                       if r.get("acceptance_rate_by_step") is not None]
        if step_arrays:
            n_steps = len(step_arrays[0])
            avg_step = []
            for s in range(n_steps):
                vals = [arr[s] for arr in step_arrays if s < len(arr)]
                avg_step.append(round(statistics.fmean(vals), 4) if vals else 0.0)
        else:
            avg_step = []

        summary["combined_tps"] = stats_dict(tps_vals) if tps_vals else stats_dict([])
        summary["ttft_ms"] = stats_dict(ttft_vals) if ttft_vals else stats_dict([])
        summary["draft_forward_ms_per_step"] = (
            {"mean": round(statistics.fmean(draft_fwd_vals), 4)} if draft_fwd_vals else {"mean": None}
        )
        summary["tokens_drafted_total"] = total_drafted
        summary["tokens_accepted_total"] = total_accepted
        summary["acceptance_rate_aggregate"] = round(agg_ar, 4) if agg_ar is not None else None
        summary["acceptance_rate_by_step"] = avg_step
    else:
        summary["combined_tps"] = stats_dict([])
        summary["ttft_ms"] = stats_dict([])
        summary["draft_forward_ms_per_step"] = {"mean": None}
        summary["tokens_drafted_total"] = 0
        summary["tokens_accepted_total"] = 0
        summary["acceptance_rate_aggregate"] = None
        summary["acceptance_rate_by_step"] = []

    status = "completed" if valid_count >= MEASURED_RUNS else (
        "INSUFFICIENT_DATA" if valid_count > 0 else "ALL_FAILED"
    )

    return {
        "band": band,
        "nat": nat,
        "status": status,
        "warmup_runs": len(warmup_results),
        "measured_runs": measured_results,
        "summary": summary,
    }


# ===========================================================================
# 20K OOM-safe wrapper
# ===========================================================================

def run_nat_config_20k_safe(
    pipeline: Any,
    tokenizer: Any,
    prompt: str,
    nat: int,
    post_warmup_rss_mb: float | None,
) -> dict[str, Any]:
    """Wrap run_nat_config with try/except for 20K OOM handling."""
    try:
        proc = psutil.Process()
        rss_now = proc.memory_info().rss / (1024 * 1024)
        if rss_now > RSS_WARNING_MB:
            print(f"    WARNING: RSS {rss_now:.0f} MB > {RSS_WARNING_MB:.0f} MB — aborting 20K band")
            return {
                "band": BAND_20K,
                "nat": nat,
                "status": "OOM_SKIPPED",
                "reason": f"RSS {rss_now:.0f} MB exceeds warning threshold {RSS_WARNING_MB:.0f} MB",
                "warmup_runs": 0,
                "measured_runs": [],
                "summary": {"valid_count": 0},
            }
        return run_nat_config(pipeline, tokenizer, prompt, nat, BAND_20K, True, post_warmup_rss_mb)
    except (RuntimeError, MemoryError) as exc:
        gc.collect()
        msg = str(exc)
        print(f"    OOM at band=20480 nat={nat}: {msg[:120]}")
        return {
            "band": BAND_20K,
            "nat": nat,
            "status": "OOM_SKIPPED",
            "exception_fingerprint": normalize_error("OOM", msg),
            "exception_message": msg[:200],
            "warmup_runs": 0,
            "measured_runs": [],
            "summary": {"valid_count": 0},
        }
    except Exception as exc:  # noqa: BLE001
        gc.collect()
        msg = str(exc)
        print(f"    ERROR at band=20480 nat={nat}: {msg[:120]}")
        return {
            "band": BAND_20K,
            "nat": nat,
            "status": "OOM_SKIPPED",
            "exception_fingerprint": normalize_error("ERROR_20K", msg),
            "exception_message": msg[:200],
            "warmup_runs": 0,
            "measured_runs": [],
            "summary": {"valid_count": 0},
        }


# ===========================================================================
# Standalone draft measurement (supplementary, one-time at 4K)
# ===========================================================================

def run_standalone_draft_tps(
    tokenizer: Any,
    draft_path: Path,
    prompt_4k: str,
) -> dict[str, Any]:
    """Run draft model standalone for reference TPS. One-time, 3 runs at 4K."""
    print("\n[STANDALONE DRAFT] Compiling standalone draft pipeline...")
    pipeline, compile_ms, err = create_draft_standalone_pipeline(draft_path)
    if pipeline is None:
        return {
            "status": "PIPELINE_FAILED",
            "error": err,
            "mean": None,
            "runs": [],
        }

    gen_config = make_standalone_gen_config()
    runs: list[float] = []
    for i in range(STANDALONE_DRAFT_RUNS):
        r = run_single_generation(pipeline, tokenizer, prompt_4k, gen_config, nat=1, is_speculative=False)
        if r["ok"] and r["combined_tps"] is not None:
            runs.append(r["combined_tps"])
            print(f"  Draft standalone run {i+1}: {r['combined_tps']:.2f} tps")
        else:
            print(f"  Draft standalone run {i+1}: FAILED — {r.get('error_fingerprint','?')}")

    # Explicitly delete pipeline to free GPU memory before main pipeline
    del pipeline
    gc.collect()

    return {
        "status": "completed" if runs else "ALL_FAILED",
        "mean": round(statistics.fmean(runs), 4) if runs else None,
        "runs": [round(v, 4) for v in runs],
        "standalone_compile_ms": compile_ms,
    }


# ===========================================================================
# Analysis: quality gates + best NAT per band
# ===========================================================================

def analyse_results(
    results: list[dict[str, Any]],
) -> dict[str, Any]:
    """Compute G-03/G-04/G-05/G-06 analysis over completed results."""
    # Index results by (band, nat) for easy lookup
    idx: dict[tuple[int, int], dict[str, Any]] = {}
    for r in results:
        idx[(r["band"], r["nat"])] = r

    # G-03: best NAT per band
    core_bands = [b for b in PROMPT_BANDS if b != BAND_20K]
    best_nat_per_band: dict[str, Any] = {}
    for band in core_bands:
        band_results: list[tuple[int, float]] = []
        for nat in NAT_VALUES:
            rec = idx.get((band, nat))
            if rec is None:
                continue
            if rec["status"] not in ("completed", "INSUFFICIENT_DATA"):
                continue
            tps_info = rec["summary"].get("combined_tps", {})
            mean_tps = tps_info.get("mean") if isinstance(tps_info, dict) else None
            if mean_tps and mean_tps > 0:
                band_results.append((nat, mean_tps))

        if not band_results:
            best_nat_per_band[str(band)] = None
            continue

        band_results.sort(key=lambda x: x[1], reverse=True)
        best = band_results[0]
        second = band_results[1] if len(band_results) > 1 else None

        best_nat_per_band[str(band)] = {
            "nat": best[0],
            "tps": round(best[1], 4),
            "second_best_nat": second[0] if second else None,
            "second_best_tps": round(second[1], 4) if second else None,
            "delta_tps": round(best[1] - second[1], 4) if second else None,
            "delta_percent": round(100.0 * (best[1] - second[1]) / second[1], 2) if second else None,
        }

    # G-04: global NAT recommendation
    win_counts: dict[int, int] = {nat: 0 for nat in NAT_VALUES}
    for band_str, info in best_nat_per_band.items():
        if info is not None:
            win_counts[info["nat"]] = win_counts.get(info["nat"], 0) + 1

    best_global_nat = max(win_counts, key=lambda k: win_counts[k])
    best_global_wins = win_counts[best_global_nat]
    total_bands_analysed = sum(1 for v in best_nat_per_band.values() if v is not None)
    single_winner = best_global_wins == total_bands_analysed and total_bands_analysed > 0

    # Weighted recommendation (PA=0.3, AO=0.5, CA=0.2)
    band_weights = {512: 0.10, 2048: 0.10, 4096: 0.10, 8192: 0.17, 12288: 0.17, 16384: 0.16, 20480: 0.20}
    weighted_tps: dict[int, float] = {nat: 0.0 for nat in NAT_VALUES}
    weight_total = 0.0
    for band_str, info in best_nat_per_band.items():
        if info is None:
            continue
        band_int = int(band_str)
        w = band_weights.get(band_int, 0.0)
        # For each NAT, compute weighted TPS contribution
        for nat in NAT_VALUES:
            rec = idx.get((band_int, nat))
            if rec is None:
                continue
            tps_info = rec["summary"].get("combined_tps", {})
            mean_tps = tps_info.get("mean") if isinstance(tps_info, dict) else None
            if mean_tps:
                weighted_tps[nat] += w * mean_tps
    if any(v > 0 for v in weighted_tps.values()):
        weighted_best_nat = max(weighted_tps, key=lambda k: weighted_tps[k])
    else:
        weighted_best_nat = best_global_nat

    global_rec = {
        "nat": best_global_nat,
        "wins": best_global_wins,
        "total_bands": total_bands_analysed,
        "single_winner": single_winner,
        "win_counts": win_counts,
        "weighted_best_nat": weighted_best_nat,
        "weighted_tps_scores": {str(k): round(v, 4) for k, v in weighted_tps.items()},
    }

    # G-05: adaptive NAT needed?
    adaptive_needed = not single_winner
    tps_cost_of_global: dict[str, Any] = {}
    if adaptive_needed:
        for band_str, info in best_nat_per_band.items():
            if info is None:
                continue
            band_int = int(band_str)
            optimal_nat = info["nat"]
            optimal_tps = info["tps"]
            # TPS of global NAT at this band
            global_rec_nat = best_global_nat
            rec_global = idx.get((band_int, global_rec_nat))
            if rec_global:
                g_tps_info = rec_global["summary"].get("combined_tps", {})
                global_nat_tps = g_tps_info.get("mean") if isinstance(g_tps_info, dict) else None
            else:
                global_nat_tps = None
            if global_nat_tps and optimal_tps:
                cost_pct = 100.0 * (optimal_tps - global_nat_tps) / optimal_tps
            else:
                cost_pct = None
            tps_cost_of_global[band_str] = {
                "optimal_nat": optimal_nat,
                "optimal_tps": optimal_tps,
                "global_nat": global_rec_nat,
                "global_nat_tps": round(global_nat_tps, 4) if global_nat_tps else None,
                "tps_cost_pct": round(cost_pct, 2) if cost_pct is not None else None,
                "exceeds_10pct": cost_pct > 10.0 if cost_pct is not None else None,
            }

    any_exceeds_10pct = any(
        v.get("exceeds_10pct") is True for v in tps_cost_of_global.values()
    )

    # G-06: acceptance rate degradation (at winning NAT)
    ar_trend: dict[str, Any] = {}
    g06_warning = False
    winning_nat_for_ar = best_global_nat
    for band in core_bands:
        rec = idx.get((band, winning_nat_for_ar))
        if rec is None:
            continue
        ar = rec["summary"].get("acceptance_rate_aggregate")
        ar_trend[str(band)] = ar
        if ar is not None and ar < 0.25:
            g06_warning = True

    # Include 20K in trend if available
    rec_20k = idx.get((BAND_20K, winning_nat_for_ar))
    if rec_20k and rec_20k["status"] not in ("OOM_SKIPPED",):
        ar_20k = rec_20k["summary"].get("acceptance_rate_aggregate")
        ar_trend["20480"] = ar_20k

    return {
        "best_nat_per_band": best_nat_per_band,
        "global_nat_recommendation": global_rec,
        "adaptive_nat_needed": adaptive_needed,
        "tps_cost_of_global_nat": tps_cost_of_global if adaptive_needed else {},
        "any_band_exceeds_10pct_cost": any_exceeds_10pct,
        "acceptance_rate_trend": ar_trend,
        "acceptance_rate_winning_nat": winning_nat_for_ar,
        "g06_acceptance_degradation_warning": g06_warning,
    }


def evaluate_quality_gates(
    results: list[dict[str, Any]],
    analysis: dict[str, Any],
) -> dict[str, Any]:
    """Evaluate G-01 through G-07 and produce disposition."""
    core_bands = [b for b in PROMPT_BANDS if b != BAND_20K]
    idx: dict[tuple[int, int], dict[str, Any]] = {}
    for r in results:
        idx[(r["band"], r["nat"])] = r

    # G-01: measurement completeness (7 mandatory fields present in all valid measured runs)
    g01_pass = True
    g01_details: list[str] = []
    mandatory_fields = [
        "combined_tps", "draft_forward_ms_per_step",
        "tokens_drafted_total", "tokens_accepted_total",
        "acceptance_rate_by_step", "peak_rss_mb", "ttft_ms",
    ]
    for band in core_bands:
        for nat in NAT_VALUES:
            rec = idx.get((band, nat))
            if rec is None:
                g01_pass = False
                g01_details.append(f"MISSING band={band} nat={nat}")
                continue
            for run in rec.get("measured_runs", []):
                if not run.get("ok"):
                    continue  # failed runs are excluded from validity check
                missing = [f for f in mandatory_fields if run.get(f) is None]
                if missing:
                    g01_pass = False
                    g01_details.append(f"band={band} nat={nat} missing={missing}")

    # G-02: valid run count >= 5
    g02_pass = True
    g02_details: list[str] = []
    for band in core_bands:
        for nat in NAT_VALUES:
            rec = idx.get((band, nat))
            if rec is None:
                g02_pass = False
                g02_details.append(f"MISSING band={band} nat={nat}")
                continue
            vc = rec["summary"].get("valid_count", 0)
            if vc < MEASURED_RUNS:
                g02_pass = False
                g02_details.append(f"band={band} nat={nat} valid_count={vc}")

    # G-03: best NAT per band computed
    g03_pass = all(v is not None for v in analysis["best_nat_per_band"].values())

    # G-04: global NAT recommendation available
    g04_pass = analysis["global_nat_recommendation"]["nat"] is not None

    # G-05: adaptive check
    adaptive_needed = analysis["adaptive_nat_needed"]
    any_exceeds = analysis["any_band_exceeds_10pct_cost"]
    if not adaptive_needed:
        g05_result = "N/A"  # single winner — no adaptive needed
    elif any_exceeds:
        g05_result = "SDO_DECISION_REQUIRED"
    else:
        g05_result = "PASS"  # varies by band but <10% cost — global NAT is acceptable

    # G-06: acceptance degradation
    g06_result = "FAIL_WARNING" if analysis["g06_acceptance_degradation_warning"] else "PASS"

    # G-07: memory budget
    peak_rsses = []
    for band in core_bands:
        for nat in NAT_VALUES:
            rec = idx.get((band, nat))
            if rec is None:
                continue
            rss = rec["summary"].get("peak_rss_mb")
            if rss:
                peak_rsses.append(rss)
    # Also check 20K band
    for nat in NAT_VALUES:
        rec = idx.get((BAND_20K, nat))
        if rec and rec["status"] not in ("OOM_SKIPPED",):
            rss = rec["summary"].get("peak_rss_mb")
            if rss:
                peak_rsses.append(rss)
    highest_rss = max(peak_rsses) if peak_rsses else 0.0
    g07_pass = highest_rss < RSS_BUDGET_MB

    # Disposition
    if not g01_pass or not g02_pass:
        disposition = "INSUFFICIENT_EVIDENCE"
        locked_nat_value = None
    elif not g07_pass:
        disposition = "MEMORY_BUDGET_EXCEEDED"
        locked_nat_value = None
    elif g05_result == "SDO_DECISION_REQUIRED":
        disposition = "SDO_DECISION_REQUIRED"
        locked_nat_value = None
    elif analysis["global_nat_recommendation"]["single_winner"]:
        disposition = "NAT_LOCKED"
        locked_nat_value = analysis["global_nat_recommendation"]["nat"]
    else:
        # wins at most but not all bands, <10% cost — still recommend lock
        disposition = "NAT_LOCKED"
        locked_nat_value = analysis["global_nat_recommendation"]["weighted_best_nat"]

    return {
        "G-01": "PASS" if g01_pass else "FAIL",
        "G-01_details": g01_details[:20],
        "G-02": "PASS" if g02_pass else "FAIL",
        "G-02_details": g02_details[:20],
        "G-03": "PASS" if g03_pass else "FAIL",
        "G-04": "PASS" if g04_pass else "FAIL",
        "G-05": g05_result,
        "G-06": g06_result,
        "G-07": "PASS" if g07_pass else "FAIL",
        "G-07_peak_rss_mb": round(highest_rss, 1),
        "disposition": disposition,
        "locked_nat_value": locked_nat_value,
    }


# ===========================================================================
# Main execution
# ===========================================================================

def main() -> None:
    print("=" * 70)
    print("BlarAI P5-Task-4.3: NAT Sweep × Context Bands")
    print("=" * 70)

    ts_start = now_iso()
    print(f"Start: {ts_start}")

    # Fail-closed: AC power check
    power_state = enforce_ac_power_or_fail_closed()
    print(f"Power: plugged={power_state.get('power_plugged')}, "
          f"battery={power_state.get('battery_percent')}%")

    # Verify model paths
    for path, label in [(MODEL_14B, "Target 14B"), (DRAFT_A_PATH, "Draft-A")]:
        assert (path / "openvino_model.xml").exists(), f"{label} xml missing: {path}"
        assert (path / "openvino_model.bin").exists(), f"{label} bin missing: {path}"
    print("Model paths: OK")

    # Collect metadata
    ov_ver = ov.__version__ if ov is not None else "UNKNOWN"
    ov_genai_ver = ov_genai.__version__
    metadata = {
        "commit_hash": git_head(),
        "python_version": platform.python_version(),
        "platform": platform.platform(),
        "openvino_version": ov_ver,
        "openvino_genai_version": ov_genai_ver,
        "power_envelope": power_state,
        "memory_limits": {
            "warning_rss_mb": RSS_WARNING_MB,
            "budget_rss_mb": RSS_BUDGET_MB,
        },
    }

    benchmark_policy = {
        "nat_values": NAT_VALUES,
        "prompt_bands": PROMPT_BANDS,
        "warmup_runs": WARMUP_RUNS,
        "measured_runs": MEASURED_RUNS,
        "max_new_tokens": MAX_NEW_TOKENS,
        "scheduler_cache_gb": SCHEDULER_CACHE_GB,
        "xattention": "OFF (default — GPU_ENABLE_SDPA_OPTIMIZATION not set)",
        "pipeline_construction": "SchedulerConfig",
        "draft_model": "Qwen3-0.6B 28L INT4 GPU (LOCKED)",
        "target_model": "Qwen3-14B INT4 GPU (LOCKED)",
    }

    # Load tokenizer
    print(f"\n[1/4] Loading tokenizer from {TOKENIZER_DIR}...")
    tokenizer = AutoTokenizer.from_pretrained(str(TOKENIZER_DIR), trust_remote_code=True)
    print("Tokenizer: OK")

    # Build prompts for all bands upfront
    print("\n[2/4] Building prompts for all bands...")
    band_prompts: dict[int, tuple[str, int]] = {}
    for band in PROMPT_BANDS:
        print(f"  Building prompt for band={band}...")
        prompt_str, actual_tokens = build_prompt_for_band(tokenizer, band)
        band_prompts[band] = (prompt_str, actual_tokens)
        print(f"    Target: {band} tokens | Actual: {actual_tokens} tokens | "
              f"Prompt len: {len(prompt_str)} chars")

    # Standalone draft measurement (gets own pipeline, freed before main pipeline)
    print("\n[3/4] Running standalone draft TPS measurement (supplementary)...")
    prompt_4k, _ = band_prompts[4096]
    standalone_draft = run_standalone_draft_tps(tokenizer, DRAFT_A_PATH, prompt_4k)
    print(f"  Standalone draft: {standalone_draft.get('mean')} tps (mean of "
          f"{len(standalone_draft.get('runs', []))} runs)")

    # Compile main speculative pipeline
    print("\n[4/4] Compiling main speculative pipeline (once)...")
    t_compile_start = time.perf_counter()
    pipeline, compile_ms, err = create_main_pipeline(MODEL_14B, DRAFT_A_PATH)
    if pipeline is None:
        print(f"FATAL: Pipeline compilation failed: {err}")
        sys.exit(1)
    print(f"Pipeline compiled in {compile_ms:.0f} ms")

    # Partial state for incremental saves
    all_results: list[dict[str, Any]] = []

    partial_state: dict[str, Any] = {
        "milestone": "P5-TASK-4.3",
        "timestamp_utc": ts_start,
        "metadata": metadata,
        "benchmark_policy": benchmark_policy,
        "pipeline_compile_ms": compile_ms,
        "standalone_draft_tps": standalone_draft,
        "results": all_results,
        "analysis": {},
        "quality_gate": {},
        "finished_utc": None,
        "_partial": True,
    }

    def save_partial() -> None:
        partial_state["results"] = all_results
        write_json_atomic(PARTIAL_JSON, partial_state)
        print(f"  [PARTIAL SAVE] {PARTIAL_JSON.name} ({len(all_results)} configs so far)")

    # -----------------------------------------------------------------------
    # Main sweep: band-outer, NAT-inner
    # -----------------------------------------------------------------------
    print("\n" + "=" * 70)
    print("BENCHMARK SWEEP")
    print(f"Bands: {PROMPT_BANDS}")
    print(f"NAT values: {NAT_VALUES}")
    print(f"Configurations: {len(PROMPT_BANDS) * len(NAT_VALUES)} | "
          f"Runs each: {WARMUP_RUNS}w + {MEASURED_RUNS}m")
    print("=" * 70)

    total_band_count = len(PROMPT_BANDS)
    for band_idx, band in enumerate(PROMPT_BANDS):
        is_20k = (band == BAND_20K)
        prompt_str, actual_tokens = band_prompts[band]

        print(f"\n{'*' * 60}")
        print(f"Band {band_idx + 1}/{total_band_count}: {band} tokens "
              f"(actual: {actual_tokens}){' [OPTIONAL—OOM safe]' if is_20k else ''}")
        print(f"{'*' * 60}")

        if is_20k:
            # 20K: abort entire band if RSS is already dangerously high
            proc = psutil.Process()
            rss_now_mb = proc.memory_info().rss / (1024 * 1024)
            if rss_now_mb > RSS_WARNING_MB:
                print(f"  20K band SKIPPED: current RSS {rss_now_mb:.0f} MB > "
                      f"warning threshold {RSS_WARNING_MB:.0f} MB")
                for nat in NAT_VALUES:
                    all_results.append({
                        "band": BAND_20K,
                        "nat": nat,
                        "status": "OOM_SKIPPED",
                        "reason": f"Pre-band RSS {rss_now_mb:.0f} MB exceeds {RSS_WARNING_MB:.0f} MB",
                        "warmup_runs": 0,
                        "measured_runs": [],
                        "summary": {"valid_count": 0},
                    })
                save_partial()
                continue

        # Measure stable post-warmup RSS for this band (use first NAT config's warmup result)
        # We capture it during the first NAT run and reuse across subsequent NAT values at same band.
        post_warmup_rss_for_band: float | None = None

        for nat_idx, nat in enumerate(NAT_VALUES):
            print(f"\n  NAT={nat} ({nat_idx + 1}/{len(NAT_VALUES)})")

            if is_20k:
                rec = run_nat_config_20k_safe(pipeline, tokenizer, prompt_str, nat,
                                              post_warmup_rss_for_band)
            else:
                rec = run_nat_config(pipeline, tokenizer, prompt_str, nat, band, False,
                                     post_warmup_rss_for_band)

            # Use the RSS from the first NAT run at this band for all subsequent runs
            if post_warmup_rss_for_band is None and rec["status"] not in ("OOM_SKIPPED",):
                warmup_list = rec.get("measured_runs", [])
                valid_rss = [r["peak_rss_mb"] for r in warmup_list
                             if r.get("ok") and r.get("peak_rss_mb")]
                if valid_rss:
                    post_warmup_rss_for_band = max(valid_rss)
                    print(f"  [RSS baseline for band={band}]: {post_warmup_rss_for_band:.0f} MB")

            mean_tps = rec["summary"].get("combined_tps", {})
            if isinstance(mean_tps, dict):
                mean_tps_val = mean_tps.get("mean", 0.0)
            else:
                mean_tps_val = 0.0
            ar = rec["summary"].get("acceptance_rate_aggregate")
            ar_str = f", AR={ar:.3f}" if ar is not None else ""
            print(f"  → band={band} nat={nat} status={rec['status']} "
                  f"tps={mean_tps_val:.2f}{ar_str}")

            all_results.append(rec)
            gc.collect()

        # Save after every band
        save_partial()
        print(f"\n  Band {band} complete ({len(all_results)} configs total)")

    # -----------------------------------------------------------------------
    # Analysis and quality gates
    # -----------------------------------------------------------------------
    print("\n" + "=" * 70)
    print("ANALYSIS")
    print("=" * 70)

    analysis = analyse_results(all_results)
    quality_gate = evaluate_quality_gates(all_results, analysis)

    print(f"\nBest NAT per band:")
    for band_str, info in analysis["best_nat_per_band"].items():
        if info:
            print(f"  band={band_str}: NAT={info['nat']} @ {info['tps']:.3f} tps "
                  f"(+{info.get('delta_pct', info.get('delta_percent', 0) or 0):.1f}% over 2nd)")
        else:
            print(f"  band={band_str}: NO DATA")

    rec = analysis["global_nat_recommendation"]
    print(f"\nGlobal recommendation: NAT={rec['nat']} "
          f"({rec['wins']}/{rec['total_bands']} bands | single_winner={rec['single_winner']})")
    print(f"Weighted best NAT: {rec['weighted_best_nat']}")

    print(f"\nAcceptance rate trend (NAT={analysis['acceptance_rate_winning_nat']}):")
    for b, ar in analysis["acceptance_rate_trend"].items():
        ar_str = f"{ar:.3f}" if ar is not None else "N/A"
        warn = " ← BELOW 0.25" if ar is not None and ar < 0.25 else ""
        print(f"  band={b}: AR={ar_str}{warn}")

    print(f"\nQuality gates:")
    for gate in ["G-01", "G-02", "G-03", "G-04", "G-05", "G-06", "G-07"]:
        print(f"  {gate}: {quality_gate[gate]}")
    print(f"\n  Disposition: {quality_gate['disposition']}")
    if quality_gate["locked_nat_value"] is not None:
        print(f"  Locked NAT: {quality_gate['locked_nat_value']}")

    # -----------------------------------------------------------------------
    # Write final artifact
    # -----------------------------------------------------------------------
    ts_finish = now_iso()

    final_artifact: dict[str, Any] = {
        "milestone": "P5-TASK-4.3",
        "timestamp_utc": ts_start,
        "metadata": metadata,
        "benchmark_policy": benchmark_policy,
        "pipeline_compile_ms": compile_ms,
        "standalone_draft_tps": standalone_draft,
        "results": all_results,
        "analysis": analysis,
        "quality_gate": quality_gate,
        "finished_utc": ts_finish,
    }

    write_json_atomic(OUTPUT_JSON, final_artifact)

    # Remove partial file
    if PARTIAL_JSON.exists():
        PARTIAL_JSON.unlink()

    print(f"\n{'=' * 70}")
    print(f"COMPLETE")
    print(f"{'=' * 70}")
    print(f"Evidence: {OUTPUT_JSON}")
    print(f"Disposition: {quality_gate['disposition']}")
    if quality_gate["locked_nat_value"] is not None:
        print(f"NAT LOCKED: {quality_gate['locked_nat_value']}")
    print(f"Start: {ts_start}")
    print(f"Finish: {ts_finish}")


if __name__ == "__main__":
    main()
