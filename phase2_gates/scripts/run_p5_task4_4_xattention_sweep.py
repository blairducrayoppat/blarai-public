"""
P5-Task-4.4: XAttention (GPU SDPA Optimization) Independent Sweep
===================================================================
Sweep GPU_ENABLE_SDPA_OPTIMIZATION {OFF, ON} across 4 context bands
[4096, 8192, 12288, 16384] with all other parameters fixed (NAT=3,
Draft-A, sparse_attention=OFF, do_sample=False).

Determines whether the P5-005b finding (XAttention OFF is better at 4K)
holds at longer context, or whether XAttention ON becomes beneficial
where speculative decoding is weak or inert.

NAMING DISAMBIGUATION (CRITICAL):
  GPU_ENABLE_SDPA_OPTIMIZATION = GPU plugin SDPA kernel optimization.
  This is COMPLETELY SEPARATE from SchedulerConfig.use_sparse_attention /
  SparseAttentionMode.XATTENTION (tested in Task 4.3b, DEFERRED).
  "XAttention" in this task = GPU SDPA kernel, NOT scheduler eviction.

Pipeline compilations: 2 total
  1. Pipeline A: XAttention OFF (no GPU_ENABLE_SDPA_OPTIMIZATION property)
  2. Pipeline B: XAttention ON  (GPU_ENABLE_SDPA_OPTIMIZATION=True)

Execution order:
  Pipeline A (OFF) at all 4 bands → calibration check → save intermediate →
  delete Pipeline A → Pipeline B (ON) at all 4 bands → compute deltas →
  quality gates G-01..G-08 → disposition → final JSON

Evidence output:
  phase2_gates/evidence/p5_task4_4_xattention_sweep.json
  (intermediate: p5_task4_4_xattention_sweep.json.partial)

API CRITICAL PATTERNS (violation = silent data loss):
  - pipeline.generate([prompt], gc, cb)   → DecodedResults (CORRECT)
  - pipeline.generate(prompt, gc, cb)     → bare str, NO metrics (WRONG)
  - m_batch_sizes[i] = accepted_tokens + 1 for speculative episode i

Branch: feature/p5-task4-4-xattention-sweep
"""
from __future__ import annotations

import datetime as dt
import gc as gc_mod
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
OUTPUT_JSON   = EVIDENCE_DIR / "p5_task4_4_xattention_sweep.json"
PARTIAL_JSON  = EVIDENCE_DIR / "p5_task4_4_xattention_sweep.json.partial"
TASK43_JSON   = EVIDENCE_DIR / "p5_task4_3_nat_sweep_matrix.json"

MODEL_14B     = ROOT / "models" / "qwen3-14b"  / "openvino-int4-gpu"
DRAFT_A_PATH  = ROOT / "models" / "qwen3-0.6b" / "openvino-int4-gpu"
TOKENIZER_DIR = MODEL_14B

# ---------------------------------------------------------------------------
# Benchmark constants (locked per Task 4.4 spec)
# ---------------------------------------------------------------------------
NAT:                int       = 3            # LOCKED — Task 4.3 DEC-01
PROMPT_BANDS:       list[int] = [4096, 8192, 12288, 16384]
WARMUP_RUNS:        int       = 2
MEASURED_RUNS:      int       = 5
MAX_NEW_TOKENS:     int       = 128
SCHEDULER_CACHE_GB: int       = 3
SYSTEM_PROMPT:      str       = "You are a helpful assistant."
RSS_WARNING_MB:     float     = 26_000.0
RSS_BUDGET_MB:      float     = 15_507.0

# Task 4.3 calibration reference (NAT=3, 4K, dense)
TASK43_CALIB_TPS:     float = 8.065
CALIB_TOLERANCE_PCT:  float = 15.0  # ±15% acceptable

# XAttention settings
XATTENTION_SETTINGS: list[str] = ["OFF", "ON"]


# ===========================================================================
# Crash-resilient resumption
# ===========================================================================

def load_completed_from_partial() -> tuple[list[dict[str, Any]], set[tuple[int, str]]]:
    """Load completed configs from partial JSON for crash recovery.

    Returns (results_list, set_of_completed_tuples) where each tuple is
    (band, xattention_label). Only configs with status='completed' and
    valid_count >= MEASURED_RUNS are considered complete.
    """
    if not PARTIAL_JSON.exists():
        return [], set()

    try:
        with open(PARTIAL_JSON, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (json.JSONDecodeError, OSError) as exc:
        print(f"[RESUME] WARNING: Could not read partial JSON: {exc}")
        return [], set()

    results = data.get("results", [])
    completed: set[tuple[int, str]] = set()
    valid_results: list[dict[str, Any]] = []

    for r in results:
        band = r.get("band")
        xa = r.get("xattention")
        status = r.get("status")
        vc = r.get("summary", {}).get("valid_count", 0)
        if status == "completed" and vc >= MEASURED_RUNS and band is not None and xa is not None:
            completed.add((band, xa))
            valid_results.append(r)
            print(f"[RESUME] Recovered: band={band}, XAtt={xa}, "
                  f"valid={vc}, tps={r['summary']['combined_tps']['mean']:.3f}")

    if completed:
        print(f"[RESUME] {len(completed)} configs recovered — will skip these.")
    else:
        print("[RESUME] No completed configs found in partial — starting fresh.")

    return valid_results, completed


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
# Prompt construction (byte-identical to Task 4.3 / 4.3b)
# ===========================================================================

def build_user_content_to_token_len(tokenizer: Any, target_tokens: int) -> str:
    """Build user content string padded to approximately target_tokens tokens.

    MUST be byte-identical construction to Task 4.3 to ensure only the
    XAttention config varies across A/B comparison.
    """
    chunk = (
        " local privacy deterministic benchmark payload "
        "nat sweep context bands acceptance rate throughput "
        "speculative decoding draft target model qwen3 "
    )
    text = "Benchmark prompt for Task 4.3 NAT sweep \u00d7 context bands. "
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
    """Build full chat prompt targeting the given context band.

    Returns (prompt_str, actual_token_count).
    """
    user_content = build_user_content_to_token_len(tokenizer, band)
    prompt = build_chat_prompt(tokenizer, user_content)
    token_count = len(tokenizer(prompt, return_tensors="np")["input_ids"][0])
    return prompt, token_count


# ===========================================================================
# Pipeline construction
# ===========================================================================

def create_pipeline_off(
    target_path: Path,
    draft_path: Path,
) -> tuple[Any | None, float | None, dict[str, Any] | None]:
    """Compile Pipeline A: XAttention OFF (no GPU_ENABLE_SDPA_OPTIMIZATION)."""
    print("\n[PIPELINE A] Compiling XAttention OFF (no GPU_ENABLE_SDPA_OPTIMIZATION)...")
    t0 = time.perf_counter()
    try:
        scheduler = SchedulerConfig()
        scheduler.cache_size = SCHEDULER_CACHE_GB
        # No GPU_ENABLE_SDPA_OPTIMIZATION — default OFF behavior
        # sparse_attention=OFF (fixed constant for Task 4.4)
        pipeline = LLMPipeline(
            str(target_path),
            "GPU",
            scheduler_config=scheduler,
            draft_model=ov_genai.draft_model(str(draft_path), "GPU"),
        )
        compile_ms = (time.perf_counter() - t0) * 1000.0
        print(f"  Pipeline A compiled in {compile_ms:.0f} ms")
        return pipeline, round(compile_ms, 1), None
    except Exception as exc:  # noqa: BLE001
        return None, None, {
            "message": str(exc),
            "fingerprint": normalize_error("PIPELINE_OFF_ERROR", str(exc)),
        }


def create_pipeline_on(
    target_path: Path,
    draft_path: Path,
) -> tuple[Any | None, float | None, dict[str, Any] | None]:
    """Compile Pipeline B: XAttention ON (GPU_ENABLE_SDPA_OPTIMIZATION=True).

    Uses the **kwargs API proven in P5-005b: pass device property as keyword arg.
    """
    print("\n[PIPELINE B] Compiling XAttention ON (GPU_ENABLE_SDPA_OPTIMIZATION=True)...")
    t0 = time.perf_counter()
    try:
        scheduler = SchedulerConfig()
        scheduler.cache_size = SCHEDULER_CACHE_GB
        # GPU_ENABLE_SDPA_OPTIMIZATION=True enables SDPA kernel fusion
        # sparse_attention=OFF (fixed constant for Task 4.4)
        pipeline = LLMPipeline(
            str(target_path),
            "GPU",
            scheduler_config=scheduler,
            draft_model=ov_genai.draft_model(str(draft_path), "GPU"),
            **{"GPU_ENABLE_SDPA_OPTIMIZATION": True},
        )
        compile_ms = (time.perf_counter() - t0) * 1000.0
        print(f"  Pipeline B compiled in {compile_ms:.0f} ms")
        return pipeline, round(compile_ms, 1), None
    except Exception as exc:  # noqa: BLE001
        return None, None, {
            "message": str(exc),
            "fingerprint": normalize_error("PIPELINE_ON_ERROR", str(exc)),
        }


# ===========================================================================
# GenerationConfig (NAT=3 LOCKED)
# ===========================================================================

def make_gen_config() -> Any:
    """Create GenerationConfig with NAT=3 LOCKED per Task 4.3 decision."""
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
        cfg.num_assistant_tokens = NAT
        cfg.assistant_confidence_threshold = 0.0
    except Exception:  # noqa: BLE001
        pass
    return cfg


# ===========================================================================
# Acceptance rate extraction (identical to Task 4.3 / 4.3b)
# ===========================================================================

def extract_acceptance_metrics(perf_metrics: Any, nat: int) -> dict[str, Any]:
    """Extract speculative decoding acceptance from PerfMetrics.raw_metrics.m_batch_sizes.

    m_batch_sizes[i] = accepted_tokens + 1 for speculative episode i.
    Aggregate: sum(b-1 for b in batch_sizes) / (NAT * total_episodes)
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

    per_step: list[float] = []
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
# Single generation run (identical pattern to Task 4.3 / 4.3b)
# ===========================================================================

def run_single_generation(
    pipeline: Any,
    tokenizer: Any,
    prompt: str,
    gen_config: Any,
) -> dict[str, Any]:
    """Run one generation capturing all 7 mandatory fields.

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
        # CRITICAL: list-input returns DecodedResults with all metrics attached
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

        try:
            text = output.texts[0]
        except (AttributeError, IndexError):
            text = str(output)

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

        # Combined TPS, TTFT — prefer extended_perf_metrics native values
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

        if combined_tps is None:
            combined_tps = round(tps_wc, 4)
        if ttft_ms_native is None:
            ttft_ms_native = round(ttft_ms_wc, 1)

        # Acceptance from m_batch_sizes (speculative decoding)
        if perf_metrics is not None:
            accept_data = extract_acceptance_metrics(perf_metrics, NAT)
        else:
            accept_data = {
                "acceptance_data_source": "N/A",
                "total_speculative_episodes": None,
                "tokens_drafted_total": None,
                "tokens_accepted_total": None,
                "acceptance_rate_aggregate": None,
                "acceptance_rate_by_step": None,
            }

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
            "combined_tps": combined_tps,
            "draft_forward_ms_per_step": draft_forward_ms,
            "tokens_drafted_total": accept_data["tokens_drafted_total"],
            "tokens_accepted_total": accept_data["tokens_accepted_total"],
            "acceptance_rate_aggregate": accept_data["acceptance_rate_aggregate"],
            "acceptance_rate_by_step": accept_data["acceptance_rate_by_step"],
            "peak_rss_mb": round(rss_peak, 1),
            "ttft_ms": ttft_ms_native,
            # supplementary
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
# Run one XAttention config (warmup + measured) at a specific band
# ===========================================================================

def run_xattention_config(
    pipeline: Any,
    tokenizer: Any,
    prompt: str,
    xatt_label: str,
    band: int,
) -> dict[str, Any]:
    """Run 2 warmup + 5 measured generations for one (band, xattention) config."""
    gen_config = make_gen_config()

    print(f"\n    [XAtt={xatt_label} band={band}] Warmup ({WARMUP_RUNS} runs)...")
    warmup_results: list[dict[str, Any]] = []
    for w in range(WARMUP_RUNS):
        r = run_single_generation(pipeline, tokenizer, prompt, gen_config)
        warmup_results.append(r)
        tps_str = f"{r['combined_tps']:.2f}" if r["combined_tps"] is not None else "N/A"
        ttft_str = f"{r['ttft_ms']:.0f}ms" if r["ttft_ms"] is not None else "N/A"
        ar_str = (f", AR={r['acceptance_rate_aggregate']:.3f}"
                  if r.get("acceptance_rate_aggregate") is not None else "")
        ok_str = "OK" if r["ok"] else f"FAIL:{r.get('error_fingerprint', '?')}"
        print(f"      Warmup {w + 1}: {ok_str} tps={tps_str}  ttft={ttft_str}{ar_str}")

    # Stable RSS after warmup
    rss_post_warmup = psutil.Process().memory_info().rss / (1024 * 1024)
    if rss_post_warmup > RSS_WARNING_MB:
        print(f"      WARNING: RSS {rss_post_warmup:.0f} MB exceeds warning threshold "
              f"({RSS_WARNING_MB:.0f} MB)")

    print(f"    [XAtt={xatt_label} band={band}] Measured ({MEASURED_RUNS} runs)...")
    measured_results: list[dict[str, Any]] = []
    for m in range(MEASURED_RUNS):
        r = run_single_generation(pipeline, tokenizer, prompt, gen_config)
        measured_results.append(r)
        tps_str = f"{r['combined_tps']:.2f}" if r["combined_tps"] is not None else "N/A"
        ttft_str = f"{r['ttft_ms']:.0f}ms" if r["ttft_ms"] is not None else "N/A"
        ar_str = (f", AR={r['acceptance_rate_aggregate']:.3f}"
                  if r.get("acceptance_rate_aggregate") is not None else "")
        rss_str = f", RSS={r['peak_rss_mb']:.0f}MB" if r.get("peak_rss_mb") else ""
        ok_str = "OK" if r["ok"] else f"FAIL:{r.get('error_fingerprint', '?')}"
        print(f"      Measured {m + 1}: {ok_str} tps={tps_str}  ttft={ttft_str}{ar_str}{rss_str}")

    # Filter valid measured runs (all 7 mandatory fields present)
    valid_runs: list[dict[str, Any]] = []
    for r in measured_results:
        if (r["ok"]
                and r["combined_tps"] is not None
                and r["draft_forward_ms_per_step"] is not None
                and r["tokens_drafted_total"] is not None
                and r["tokens_accepted_total"] is not None
                and r["acceptance_rate_by_step"] is not None
                and r["peak_rss_mb"] is not None
                and r["ttft_ms"] is not None):
            valid_runs.append(r)

    valid_count = len(valid_runs)
    status = "completed" if valid_count >= MEASURED_RUNS else (
        "INSUFFICIENT_DATA" if valid_count < 3 else "partial"
    )

    # Build summary from valid runs
    tps_vals = [r["combined_tps"] for r in valid_runs]
    ttft_vals = [r["ttft_ms"] for r in valid_runs]
    draft_fwd_vals = [r["draft_forward_ms_per_step"] for r in valid_runs
                      if r["draft_forward_ms_per_step"] is not None]
    rss_vals = [r["peak_rss_mb"] for r in valid_runs]

    # Aggregate acceptance
    total_drafted = sum(r["tokens_drafted_total"] for r in valid_runs
                        if r["tokens_drafted_total"] is not None)
    total_accepted = sum(r["tokens_accepted_total"] for r in valid_runs
                         if r["tokens_accepted_total"] is not None)
    agg_ar = round(total_accepted / total_drafted, 4) if total_drafted > 0 else 0.0

    # Average per-step acceptance across valid runs
    ar_by_step_runs = [r["acceptance_rate_by_step"] for r in valid_runs
                       if r["acceptance_rate_by_step"] is not None
                       and len(r["acceptance_rate_by_step"]) == NAT]
    avg_ar_by_step: list[float] = []
    if ar_by_step_runs:
        for step_i in range(NAT):
            step_vals = [ar[step_i] for ar in ar_by_step_runs]
            avg_ar_by_step.append(round(statistics.fmean(step_vals), 4))

    summary = {
        "combined_tps": stats_dict(tps_vals),
        "ttft_ms": stats_dict(ttft_vals),
        "draft_forward_ms_per_step": stats_dict(draft_fwd_vals),
        "tokens_drafted_total": total_drafted,
        "tokens_accepted_total": total_accepted,
        "acceptance_rate_aggregate": agg_ar,
        "acceptance_rate_by_step": avg_ar_by_step if avg_ar_by_step else None,
        "peak_rss_mb": round(max(rss_vals), 1) if rss_vals else None,
        "valid_count": valid_count,
    }

    tps_mean = summary["combined_tps"]["mean"]
    ttft_mean = summary["ttft_ms"]["mean"]
    print(f"    [XAtt={xatt_label} band={band}] Summary: tps={tps_mean:.3f}  "
          f"ttft={ttft_mean:.0f}ms  AR={agg_ar:.3f}  "
          f"RSS={summary['peak_rss_mb']}MB  valid={valid_count}/{MEASURED_RUNS}")

    return {
        "band": band,
        "xattention": xatt_label,
        "status": status,
        "warmup_runs": WARMUP_RUNS,
        "measured_runs": [
            {
                "run_idx": i + 1,
                "combined_tps": r["combined_tps"],
                "draft_forward_ms_per_step": r["draft_forward_ms_per_step"],
                "tokens_drafted_total": r["tokens_drafted_total"],
                "tokens_accepted_total": r["tokens_accepted_total"],
                "acceptance_rate_by_step": r["acceptance_rate_by_step"],
                "peak_rss_mb": r["peak_rss_mb"],
                "ttft_ms": r["ttft_ms"],
            }
            for i, r in enumerate(measured_results)
        ],
        "summary": summary,
        # Keep full detail for debugging
        "_raw_measured": measured_results,
        "_raw_warmup": warmup_results,
    }


# ===========================================================================
# Calibration check
# ===========================================================================

def calibration_check(results_off: list[dict[str, Any]]) -> dict[str, Any]:
    """Compare Pipeline A 4K TPS with Task 4.3 NAT=3 reference (8.065 tps)."""
    band_4k = [r for r in results_off if r["band"] == 4096]
    if not band_4k:
        return {
            "pipeline_a_tps_4k": None,
            "task43_reference_tps_4k": TASK43_CALIB_TPS,
            "delta_pct": None,
            "status": "NO_4K_DATA",
        }

    tps_4k = band_4k[0]["summary"]["combined_tps"]["mean"]
    delta_pct = ((tps_4k - TASK43_CALIB_TPS) / TASK43_CALIB_TPS) * 100.0
    status = "PASS" if abs(delta_pct) <= CALIB_TOLERANCE_PCT else "CALIBRATION_WARNING"

    print(f"\n[CALIBRATION] Pipeline A 4K TPS: {tps_4k:.3f} vs Task 4.3 ref: {TASK43_CALIB_TPS}")
    print(f"  Delta: {delta_pct:+.1f}% (threshold: ±{CALIB_TOLERANCE_PCT}%)")
    print(f"  Status: {status}")

    return {
        "pipeline_a_tps_4k": round(tps_4k, 4),
        "task43_reference_tps_4k": TASK43_CALIB_TPS,
        "delta_pct": round(delta_pct, 2),
        "status": status,
    }


# ===========================================================================
# Analysis + Quality Gates
# ===========================================================================

def compute_analysis(
    results_off: list[dict[str, Any]],
    results_on: list[dict[str, Any]],
) -> dict[str, Any]:
    """Compute per-band deltas and summary analysis."""
    off_by_band = {r["band"]: r for r in results_off}
    on_by_band = {r["band"]: r for r in results_on}

    tps_comparison: dict[str, Any] = {}
    ttft_comparison: dict[str, Any] = {}
    ar_comparison: dict[str, Any] = {}
    rss_comparison: dict[str, Any] = {}

    per_band_verdicts: list[str] = []

    for band in PROMPT_BANDS:
        b_str = str(band)
        r_off = off_by_band.get(band)
        r_on = on_by_band.get(band)

        if r_off is None or r_on is None:
            tps_comparison[b_str] = {"off": None, "on": None, "delta_pct": None,
                                     "verdict": "MISSING_DATA"}
            ttft_comparison[b_str] = {"off_ms": None, "on_ms": None, "delta_pct": None}
            ar_comparison[b_str] = {"off": None, "on": None, "delta": None, "flag": "MISSING_DATA"}
            rss_comparison[b_str] = {"off_mb": None, "on_mb": None, "delta_mb": None}
            per_band_verdicts.append("MISSING_DATA")
            continue

        tps_off = r_off["summary"]["combined_tps"]["mean"]
        tps_on = r_on["summary"]["combined_tps"]["mean"]
        tps_delta = ((tps_on - tps_off) / tps_off * 100.0) if tps_off > 0 else 0.0

        if tps_delta > 3.0:
            verdict = "ON_WINS"
        elif tps_delta < -3.0:
            verdict = "OFF_WINS"
        else:
            verdict = "EQUIVALENT"
        per_band_verdicts.append(verdict)

        tps_comparison[b_str] = {
            "off": round(tps_off, 4),
            "on": round(tps_on, 4),
            "delta_pct": round(tps_delta, 2),
            "verdict": verdict,
        }

        # TTFT comparison: positive delta_pct => ON is faster prefill
        ttft_off = r_off["summary"]["ttft_ms"]["mean"]
        ttft_on = r_on["summary"]["ttft_ms"]["mean"]
        ttft_delta = ((ttft_off - ttft_on) / ttft_off * 100.0) if ttft_off > 0 else 0.0
        ttft_comparison[b_str] = {
            "off_ms": round(ttft_off, 1),
            "on_ms": round(ttft_on, 1),
            "delta_pct": round(ttft_delta, 2),
        }

        # AR comparison
        ar_off = r_off["summary"]["acceptance_rate_aggregate"]
        ar_on = r_on["summary"]["acceptance_rate_aggregate"]
        ar_delta = (ar_on - ar_off) if (ar_on is not None and ar_off is not None) else None
        ar_flag = "NONE"
        if ar_delta is not None and abs(ar_delta) > 0.05:
            ar_flag = "AR_INTERACTION"
        if band == 16384 and ar_on is not None and ar_on > 0 and (ar_off is None or ar_off == 0):
            ar_flag = "AR_RECOVERY"
        ar_comparison[b_str] = {
            "off": ar_off,
            "on": ar_on,
            "delta": round(ar_delta, 4) if ar_delta is not None else None,
            "flag": ar_flag,
        }

        # RSS comparison
        rss_off = r_off["summary"]["peak_rss_mb"]
        rss_on = r_on["summary"]["peak_rss_mb"]
        rss_delta = (rss_on - rss_off) if (rss_on is not None and rss_off is not None) else None
        rss_comparison[b_str] = {
            "off_mb": rss_off,
            "on_mb": rss_on,
            "delta_mb": round(rss_delta, 1) if rss_delta is not None else None,
        }

    # Overall verdict
    real_verdicts = [v for v in per_band_verdicts if v != "MISSING_DATA"]
    if not real_verdicts:
        overall = "NO_DATA"
    elif all(v == "OFF_WINS" for v in real_verdicts):
        overall = "OFF_WINS_ALL"
    elif all(v == "ON_WINS" for v in real_verdicts):
        overall = "ON_WINS_ALL"
    elif all(v == "EQUIVALENT" for v in real_verdicts):
        overall = "EQUIVALENT"
    elif all(v in ("OFF_WINS", "EQUIVALENT") for v in real_verdicts):
        overall = "OFF_WINS_ALL"  # OFF wins or tied at all bands
    elif all(v in ("ON_WINS", "EQUIVALENT") for v in real_verdicts):
        overall = "ON_WINS_ALL"   # ON wins or tied at all bands
    else:
        overall = "MIXED"

    return {
        "tps_comparison": tps_comparison,
        "ttft_comparison": ttft_comparison,
        "ar_comparison": ar_comparison,
        "rss_comparison": rss_comparison,
        "overall_verdict": overall,
    }


def evaluate_quality_gates(
    results_off: list[dict[str, Any]],
    results_on: list[dict[str, Any]],
    analysis: dict[str, Any],
    compile_off_ms: float | None,
    compile_on_ms: float | None,
) -> dict[str, Any]:
    """Evaluate all 8 quality gates per Task 4.4 spec."""
    gates: dict[str, Any] = {}
    all_results = results_off + results_on

    # G-01: measurement completeness
    invalid_runs = 0
    for r in all_results:
        for mr in r.get("measured_runs", []):
            missing = any(
                mr.get(f) is None
                for f in ["combined_tps", "draft_forward_ms_per_step",
                           "tokens_drafted_total", "tokens_accepted_total",
                           "acceptance_rate_by_step", "peak_rss_mb", "ttft_ms"]
            )
            if missing:
                invalid_runs += 1
    gates["G-01"] = "PASS" if invalid_runs == 0 else f"FAIL ({invalid_runs} invalid runs)"

    # G-02: valid_run_count >= 5 for all configs
    insufficient = []
    for r in all_results:
        vc = r["summary"]["valid_count"]
        if vc < 5:
            insufficient.append(f"XAtt={r['xattention']} band={r['band']} valid={vc}")
    gates["G-02"] = "PASS" if not insufficient else f"FAIL ({'; '.join(insufficient)})"

    # G-03: TPS comparison (PRIMARY)
    tps_comp = analysis["tps_comparison"]
    band_details: list[str] = []
    for b_str, comp in tps_comp.items():
        band_details.append(f"{b_str}={comp['verdict']}({comp['delta_pct']:+.1f}%)")
    gates["G-03"] = f"{analysis['overall_verdict']} [{', '.join(band_details)}]"

    # G-04: TTFT comparison
    ttft_comp = analysis["ttft_comparison"]
    sdpa_prefill = False
    ttft_details: list[str] = []
    for b_str, comp in ttft_comp.items():
        band_int = int(b_str)
        dp = comp["delta_pct"]
        ttft_details.append(f"{b_str}={dp:+.1f}%")
        if dp is not None and dp > 10.0 and band_int >= 8192:
            sdpa_prefill = True
    gates["G-04"] = (
        f"SDPA_PREFILL_BENEFIT [{', '.join(ttft_details)}]" if sdpa_prefill
        else f"PASS [{', '.join(ttft_details)}]"
    )

    # G-05: AR interaction
    ar_comp = analysis["ar_comparison"]
    ar_flags = [comp["flag"] for comp in ar_comp.values()
                if comp["flag"] not in ("NONE", "MISSING_DATA")]
    gates["G-05"] = ar_flags[0] if ar_flags else "PASS"

    # G-06: RSS comparison
    rss_comp = analysis["rss_comparison"]
    rss_anomaly = False
    for comp in rss_comp.values():
        if comp["delta_mb"] is not None and abs(comp["delta_mb"]) > 500:
            rss_anomaly = True
    gates["G-06"] = "RSS_ANOMALY" if rss_anomaly else "PASS"

    # G-07: Memory budget
    max_rss_16k = None
    for r in all_results:
        if r["band"] == 16384 and r["summary"]["peak_rss_mb"] is not None:
            rss = r["summary"]["peak_rss_mb"]
            if max_rss_16k is None or rss > max_rss_16k:
                max_rss_16k = rss
    if max_rss_16k is not None and max_rss_16k > RSS_BUDGET_MB:
        gates["G-07"] = f"MEMORY_BUDGET_EXCEEDED (peak={max_rss_16k:.0f}MB > {RSS_BUDGET_MB:.0f}MB)"
    else:
        gates["G-07"] = "PASS"

    # G-08: Compile time impact
    if compile_off_ms is not None and compile_on_ms is not None and compile_off_ms > 0:
        compile_delta_ms = compile_on_ms - compile_off_ms
        compile_delta_pct = (compile_delta_ms / compile_off_ms) * 100.0
        overhead = compile_on_ms > (2.0 * compile_off_ms)
        gates["G-08"] = (
            f"{'COMPILE_OVERHEAD' if overhead else 'PASS'} "
            f"(OFF={compile_off_ms:.0f}ms, ON={compile_on_ms:.0f}ms, "
            f"delta={compile_delta_pct:+.1f}%)"
        )
    else:
        gates["G-08"] = "PASS (compile times unavailable)"

    # Disposition
    g01_pass = gates["G-01"] == "PASS"
    g02_pass = gates["G-02"] == "PASS"
    overall = analysis["overall_verdict"]

    if not g01_pass or not g02_pass:
        disposition = "INSUFFICIENT_EVIDENCE"
    elif overall in ("OFF_WINS_ALL", "EQUIVALENT"):
        disposition = "XATTENTION_OFF_LOCKED"
    elif overall == "ON_WINS_ALL":
        disposition = "XATTENTION_ON_LOCKED"
    elif overall == "MIXED":
        disposition = "CONTEXT_DEPENDENT"
    else:
        disposition = "INSUFFICIENT_EVIDENCE"

    gates["disposition"] = disposition
    return gates


# ===========================================================================
# Property verification (config_verification from Task 4.4 spec)
# ===========================================================================

def verify_property_took_effect(
    compile_off_ms: float | None,
    compile_on_ms: float | None,
    results_off: list[dict[str, Any]],
    results_on: list[dict[str, Any]],
) -> dict[str, Any]:
    """Check whether GPU_ENABLE_SDPA_OPTIMIZATION actually changed pipeline behavior.

    Two signals:
    1. Compile time delta (SDPA changes compilation strategy — non-trivial delta expected)
    2. 4K TPS delta (even a small non-zero delta across 5 runs confirms effect)

    Returns dict with status and details.
    """
    verification: dict[str, Any] = {"compile_time_check": None, "tps_check": None,
                                     "status": "UNKNOWN"}

    # Check 1: Compile time delta
    if compile_off_ms is not None and compile_on_ms is not None:
        ct_delta_pct = abs(compile_on_ms - compile_off_ms) / compile_off_ms * 100.0
        verification["compile_time_check"] = {
            "off_ms": compile_off_ms,
            "on_ms": compile_on_ms,
            "abs_delta_pct": round(ct_delta_pct, 1),
            "signal": ct_delta_pct > 1.0,  # >1% compile time change
        }

    # Check 2: 4K TPS comparison
    off_4k = [r for r in results_off if r["band"] == 4096]
    on_4k = [r for r in results_on if r["band"] == 4096]
    if off_4k and on_4k:
        tps_off = off_4k[0]["summary"]["combined_tps"]["mean"]
        tps_on = on_4k[0]["summary"]["combined_tps"]["mean"]
        if tps_off > 0:
            tps_delta_pct = abs(tps_on - tps_off) / tps_off * 100.0
            # Identical within 0.1% across 5 runs suggests property was ignored
            verification["tps_check"] = {
                "off_tps": round(tps_off, 4),
                "on_tps": round(tps_on, 4),
                "abs_delta_pct": round(tps_delta_pct, 2),
                "signal": tps_delta_pct > 0.1,  # >0.1% difference
            }

    # Determine status
    ct_signal = (verification.get("compile_time_check") or {}).get("signal", False)
    tps_signal = (verification.get("tps_check") or {}).get("signal", False)

    if ct_signal or tps_signal:
        verification["status"] = "PROPERTY_EFFECTIVE"
    else:
        verification["status"] = "PROPERTY_POSSIBLY_IGNORED"

    return verification


# ===========================================================================
# Main
# ===========================================================================

def main() -> None:
    start_time = now_iso()
    print("=" * 72)
    print("P5-Task-4.4: XAttention (GPU SDPA Optimization) Independent Sweep")
    print("=" * 72)
    print(f"Start: {start_time}")
    print(f"Bands: {PROMPT_BANDS}")
    print(f"XAttention settings: {XATTENTION_SETTINGS}")
    print(f"NAT={NAT} (LOCKED), warmup={WARMUP_RUNS}, measured={MEASURED_RUNS}")
    print(f"max_new_tokens={MAX_NEW_TOKENS}, scheduler_cache_gb={SCHEDULER_CACHE_GB}")

    # PC-05: AC power check
    power_state = enforce_ac_power_or_fail_closed()
    print(f"\n[POWER] {power_state}")

    # Load tokenizer
    print(f"\n[TOKENIZER] Loading from {TOKENIZER_DIR}...")
    tokenizer = AutoTokenizer.from_pretrained(str(TOKENIZER_DIR), trust_remote_code=True)
    print("  Tokenizer loaded.")

    # Build prompts for all bands (reuse across both pipelines)
    prompts: dict[int, tuple[str, int]] = {}
    print("\n[PROMPTS] Building prompts for all bands...")
    for band in PROMPT_BANDS:
        prompt, token_count = build_prompt_for_band(tokenizer, band)
        prompts[band] = (prompt, token_count)
        print(f"  Band {band}: {token_count} tokens")

    # Initialize evidence payload
    payload: dict[str, Any] = {
        "milestone": "P5-TASK-4.4",
        "timestamp_utc": start_time,
        "metadata": {
            "commit_hash": git_head(),
            "python_version": platform.python_version(),
            "platform": platform.platform(),
            "openvino_version": getattr(ov, "__version__", "N/A") if ov else "N/A",
            "openvino_genai_version": ov_genai.__version__,
            "power_envelope": {
                "ac_connected": power_state.get("power_plugged", True),
                "battery_check_passed": True,
            },
            "memory_limits": {
                "warning_rss_mb": RSS_WARNING_MB,
                "budget_rss_mb": RSS_BUDGET_MB,
            },
        },
        "benchmark_policy": {
            "xattention_settings": XATTENTION_SETTINGS,
            "prompt_bands": PROMPT_BANDS,
            "nat": NAT,
            "warmup_runs": WARMUP_RUNS,
            "measured_runs": MEASURED_RUNS,
            "max_new_tokens": MAX_NEW_TOKENS,
            "scheduler_cache_gb": SCHEDULER_CACHE_GB,
            "sparse_attention": "OFF (fixed — DEFERRED from Task 4.3b)",
            "do_sample": False,
            "temperature": 0.0,
        },
        "prompt_token_counts": {b: tc for b, (_, tc) in prompts.items()},
        "calibration": None,
        "pipeline_compile_ms": None,
        "results": [],
        "property_verification": None,
        "analysis": None,
        "quality_gate": None,
        "finished_utc": None,
    }

    # -----------------------------------------------------------------------
    # Pipeline A: XAttention OFF
    # -----------------------------------------------------------------------
    print("\n" + "=" * 72)
    print("PHASE 1: Pipeline A — XAttention OFF")
    print("=" * 72)

    pipeline_a, compile_off_ms, compile_off_err = create_pipeline_off(
        MODEL_14B, DRAFT_A_PATH,
    )
    if pipeline_a is None:
        print(f"\n[FATAL] Pipeline A compilation failed: {compile_off_err}")
        payload["pipeline_compile_ms"] = {"off": None, "on": None,
                                           "error_off": compile_off_err}
        payload["quality_gate"] = {"disposition": "PIPELINE_COMPILATION_FAILED",
                                    "error": compile_off_err}
        payload["finished_utc"] = now_iso()
        write_json_atomic(OUTPUT_JSON, payload)
        print(f"\nFailed evidence written to {OUTPUT_JSON}")
        return

    # Load any previously completed results (crash recovery)
    resumed_results, completed_configs = load_completed_from_partial()
    results_off: list[dict[str, Any]] = [
        r for r in resumed_results if r["xattention"] == "OFF"
    ]

    off_bands_remaining = [b for b in PROMPT_BANDS if (b, "OFF") not in completed_configs]
    if not off_bands_remaining:
        print("\n  All OFF bands already completed (resumed). Skipping Pipeline A.")
        # Still need pipeline for calibration check if we resumed
        if pipeline_a is not None:
            del pipeline_a
            pipeline_a = None
            gc_mod.collect()
    else:
        for band in PROMPT_BANDS:
            if (band, "OFF") in completed_configs:
                print(f"\n    [XAtt=OFF band={band}] SKIPPED (resumed from partial)")
                continue
            prompt, _ = prompts[band]
            result = run_xattention_config(pipeline_a, tokenizer, prompt, "OFF", band)
            results_off.append(result)

            # Save intermediate after each band
            payload["results"] = results_off
            write_json_atomic(PARTIAL_JSON, payload)
            print(f"  Intermediate saved: {PARTIAL_JSON}")

            # Inter-band GC to relieve memory pressure
            gc_mod.collect()
            time.sleep(1)

    # Calibration check
    calib = calibration_check(results_off)
    payload["calibration"] = calib

    # Release Pipeline A
    print("\n[PIPELINE A] Releasing (del + gc.collect)...")
    if pipeline_a is not None:
        del pipeline_a
    gc_mod.collect()
    time.sleep(3)  # Extra settle time to release GPU memory
    print("  Pipeline A released.")

    # -----------------------------------------------------------------------
    # Pipeline B: XAttention ON
    # -----------------------------------------------------------------------
    print("\n" + "=" * 72)
    print("PHASE 2: Pipeline B — XAttention ON")
    print("=" * 72)

    pipeline_b, compile_on_ms, compile_on_err = create_pipeline_on(
        MODEL_14B, DRAFT_A_PATH,
    )
    if pipeline_b is None:
        print(f"\n[WARNING] Pipeline B compilation failed: {compile_on_err}")
        print("  Proceeding with Pipeline A data only — disposition: XATTENTION_NOT_AVAILABLE")

        payload["pipeline_compile_ms"] = {
            "off": compile_off_ms,
            "on": None,
            "error_on": compile_on_err,
        }
        # Finalize with Pipeline A data only
        payload["results"] = results_off
        payload["quality_gate"] = {
            "G-01": "N/A",
            "G-02": "N/A",
            "G-03": "N/A — Pipeline B failed",
            "G-04": "N/A",
            "G-05": "N/A",
            "G-06": "N/A",
            "G-07": "N/A",
            "G-08": "N/A",
            "disposition": "XATTENTION_NOT_AVAILABLE",
            "pipeline_b_error": compile_on_err,
        }
        payload["finished_utc"] = now_iso()
        write_json_atomic(OUTPUT_JSON, payload)
        print(f"\nEvidence written to {OUTPUT_JSON}")
        return

    results_on: list[dict[str, Any]] = [
        r for r in resumed_results if r["xattention"] == "ON"
    ]

    on_bands_remaining = [b for b in PROMPT_BANDS if (b, "ON") not in completed_configs]
    if not on_bands_remaining:
        print("\n  All ON bands already completed (resumed). Skipping Pipeline B runs.")
        if pipeline_b is not None:
            del pipeline_b
            pipeline_b = None
            gc_mod.collect()
    else:
        for band in PROMPT_BANDS:
            if (band, "ON") in completed_configs:
                print(f"\n    [XAtt=ON band={band}] SKIPPED (resumed from partial)")
                continue
            prompt, _ = prompts[band]
            result = run_xattention_config(pipeline_b, tokenizer, prompt, "ON", band)
            results_on.append(result)

            # Save intermediate after each band
            payload["results"] = results_off + results_on
            write_json_atomic(PARTIAL_JSON, payload)
            print(f"  Intermediate saved: {PARTIAL_JSON}")

            # Inter-band GC to relieve memory pressure
            gc_mod.collect()
            time.sleep(1)

    # Release Pipeline B
    print("\n[PIPELINE B] Releasing (del + gc.collect)...")
    if pipeline_b is not None:
        del pipeline_b
    gc_mod.collect()
    time.sleep(3)  # Extra settle time to release GPU memory
    print("  Pipeline B released.")

    # -----------------------------------------------------------------------
    # Analysis + Quality Gates
    # -----------------------------------------------------------------------
    print("\n" + "=" * 72)
    print("PHASE 3: Analysis + Quality Gates")
    print("=" * 72)

    payload["pipeline_compile_ms"] = {
        "off": compile_off_ms,
        "on": compile_on_ms,
        "delta_ms": round(compile_on_ms - compile_off_ms, 1) if (
            compile_off_ms is not None and compile_on_ms is not None) else None,
        "delta_pct": round(
            (compile_on_ms - compile_off_ms) / compile_off_ms * 100.0, 1
        ) if (compile_off_ms and compile_on_ms and compile_off_ms > 0) else None,
    }

    # Property verification
    prop_verify = verify_property_took_effect(
        compile_off_ms, compile_on_ms, results_off, results_on,
    )
    payload["property_verification"] = prop_verify
    print(f"\n[PROPERTY VERIFICATION] {prop_verify['status']}")
    if prop_verify["status"] == "PROPERTY_POSSIBLY_IGNORED":
        print("  WARNING: GPU_ENABLE_SDPA_OPTIMIZATION may not have taken effect.")
        print("  Both compile time and 4K TPS show no meaningful difference.")
        print("  Proceeding with analysis — disposition may be PROPERTY_IGNORED.")

    # Strip _raw_* from results for clean JSON (keep summary + measured_runs)
    clean_results_off: list[dict[str, Any]] = []
    for r in results_off:
        clean = {k: v for k, v in r.items() if not k.startswith("_raw_")}
        clean_results_off.append(clean)

    clean_results_on: list[dict[str, Any]] = []
    for r in results_on:
        clean = {k: v for k, v in r.items() if not k.startswith("_raw_")}
        clean_results_on.append(clean)

    payload["results"] = clean_results_off + clean_results_on

    # Compute analysis
    analysis = compute_analysis(results_off, results_on)
    payload["analysis"] = analysis

    # Quality gates
    quality_gate = evaluate_quality_gates(
        results_off, results_on, analysis, compile_off_ms, compile_on_ms,
    )

    # Override disposition if property was possibly ignored
    if (prop_verify["status"] == "PROPERTY_POSSIBLY_IGNORED"
            and quality_gate["disposition"] not in ("INSUFFICIENT_EVIDENCE",)):
        quality_gate["disposition"] = "PROPERTY_IGNORED"
        quality_gate["property_verification_override"] = True

    payload["quality_gate"] = quality_gate

    # Print analysis summary
    print(f"\n{'='*72}")
    print("RESULTS SUMMARY")
    print(f"{'='*72}")
    print(f"\nCompile times: OFF={compile_off_ms:.0f}ms  ON={compile_on_ms:.0f}ms")
    print(f"\nTPS Comparison (G-03):")
    for b_str, comp in analysis["tps_comparison"].items():
        print(f"  Band {b_str}: OFF={comp['off']:.3f}  ON={comp['on']:.3f}  "
              f"delta={comp['delta_pct']:+.1f}%  => {comp['verdict']}")
    print(f"\nTTFT Comparison (G-04):")
    for b_str, comp in analysis["ttft_comparison"].items():
        print(f"  Band {b_str}: OFF={comp['off_ms']:.0f}ms  ON={comp['on_ms']:.0f}ms  "
              f"delta={comp['delta_pct']:+.1f}%")
    print(f"\nAR Comparison (G-05):")
    for b_str, comp in analysis["ar_comparison"].items():
        print(f"  Band {b_str}: OFF={comp['off']}  ON={comp['on']}  "
              f"delta={comp['delta']}  flag={comp['flag']}")
    print(f"\nRSS Comparison (G-06):")
    for b_str, comp in analysis["rss_comparison"].items():
        print(f"  Band {b_str}: OFF={comp['off_mb']}MB  ON={comp['on_mb']}MB  "
              f"delta={comp['delta_mb']}MB")
    print(f"\nOverall verdict: {analysis['overall_verdict']}")
    print(f"\nQuality Gates:")
    for k, v in quality_gate.items():
        print(f"  {k}: {v}")

    # Finalize
    payload["finished_utc"] = now_iso()
    write_json_atomic(OUTPUT_JSON, payload)

    # Clean up partial
    if PARTIAL_JSON.exists():
        PARTIAL_JSON.unlink()
        print(f"\nPartial file removed: {PARTIAL_JSON}")

    print(f"\n{'='*72}")
    print(f"Evidence written to: {OUTPUT_JSON}")
    print(f"Disposition: {quality_gate['disposition']}")
    print(f"Finished: {payload['finished_utc']}")
    print(f"{'='*72}")


if __name__ == "__main__":
    main()
