"""
P5-Task-4.3b: Dynamic Sparse Attention A/B Test (AO/Code Agent)
================================================================
A/B test sparse attention (TRISHAPE + XATTENTION) against the Task 4.3
dense baseline at AO/Code Agent context bands [4096, 8192, 12288, 16384, 20480].

NAT=3 LOCKED (Task 4.3 decision). Baseline imported from Task 4.3 evidence JSON
— NOT re-run (dense pipeline only used for calibration check).

PA is EXCLUDED — sparse attention MUST NEVER be enabled on the Policy Agent.
See pa_security_constraint in Task4.3b_v1.xml for full rationale.

Pipeline compilations: 3 total
  1. Dense (calibration check only — 1 generate call, then discarded)
  2. TRISHAPE (5 bands × 7 runs = 35 calls)
  3. XATTENTION (5 bands × 7 runs = 35 calls)

Evidence output:
  phase2_gates/evidence/p5_task4_3b_sparse_attention_ab_test.json
  (intermediate: p5_task4_3b_sparse_attention_ab_test.json.partial)

API CRITICAL PATTERNS (violation = silent data loss):
  - pipeline.generate([prompt], gc, cb)   → DecodedResults (CORRECT)
  - pipeline.generate(prompt, gc, cb)     → bare str, NO metrics (WRONG)
  - m_batch_sizes[i] = accepted_tokens + 1 for speculative episode i

NAMING DISAMBIGUATION: SparseAttentionMode (TRISHAPE/XATTENTION) is a
SchedulerConfig KV-cache eviction pattern — completely separate from
GPU_ENABLE_SDPA_OPTIMIZATION (a device plugin SDPA kernel switch tested
in P5-005b as OFF=better). These are NOT the same feature.

Branch: feature/p5-task4-3b-sparse-attention
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
OUTPUT_JSON   = EVIDENCE_DIR / "p5_task4_3b_sparse_attention_ab_test.json"
PARTIAL_JSON  = EVIDENCE_DIR / "p5_task4_3b_sparse_attention_ab_test.json.partial"
TASK43_JSON   = EVIDENCE_DIR / "p5_task4_3_nat_sweep_matrix.json"

MODEL_14B     = ROOT / "models" / "qwen3-14b"  / "openvino-int4-gpu"
DRAFT_A_PATH  = ROOT / "models" / "qwen3-0.6b" / "openvino-int4-gpu"
TOKENIZER_DIR = MODEL_14B

# ---------------------------------------------------------------------------
# Benchmark constants (locked per Task 4.3b spec)
# ---------------------------------------------------------------------------
NAT:                int      = 3            # LOCKED — Task 4.3 DEC-01
PROMPT_BANDS:       list[int] = [4096, 8192, 12288, 16384, 20480]
WARMUP_RUNS:        int       = 2
MEASURED_RUNS:      int       = 5
MAX_NEW_TOKENS:     int       = 128
SCHEDULER_CACHE_GB: int       = 3
SYSTEM_PROMPT:      str       = "You are a helpful assistant."
BAND_20K:           int       = 20480
RSS_WARNING_MB:     float     = 26_000.0
RSS_BUDGET_MB:      float     = 15_507.0

# Task 4.3 calibration reference (NAT=3, 4K, dense)
TASK43_CALIB_TPS:   float     = 8.065
CALIB_TOLERANCE_PCT: float    = 15.0      # ±15% acceptable

# Sparse attention defaults (per Task4.3b_v1.xml spec)
SPARSE_DEFAULTS = {
    "num_retained_start_tokens_in_cache": 128,
    "num_retained_recent_tokens_in_cache": 1920,
    "num_last_dense_tokens_in_prefill": 100,
    "xattention_block_size": 64,
    "xattention_stride": 8,
    "xattention_threshold": 0.80,
}


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
# Baseline import from Task 4.3
# ===========================================================================

def load_task43_baseline() -> dict[str, Any]:
    """Load Task 4.3 NAT=3 entries for bands [4096,8192,12288,16384,20480].

    Returns dict keyed by band with extracted summary fields.
    """
    if not TASK43_JSON.exists():
        raise FileNotFoundError(f"Task 4.3 evidence not found: {TASK43_JSON}")

    with open(TASK43_JSON, "r", encoding="utf-8") as fh:
        data = json.load(fh)

    results = data.get("results", [])
    baseline: dict[int, dict[str, Any]] = {}

    for r in results:
        if r.get("nat") != NAT:
            continue
        band = r.get("band")
        if band not in PROMPT_BANDS:
            continue
        s = r.get("summary", {})
        tps_info = s.get("combined_tps", {})
        ttft_info = s.get("ttft_ms", {})
        baseline[band] = {
            "band": band,
            "combined_tps": tps_info if isinstance(tps_info, dict) else {"mean": tps_info},
            "ttft_ms": ttft_info if isinstance(ttft_info, dict) else {"mean": ttft_info},
            "acceptance_rate_aggregate": s.get("acceptance_rate_aggregate"),
            "acceptance_rate_by_step": s.get("acceptance_rate_by_step"),
            "peak_rss_mb": s.get("peak_rss_mb"),
            "draft_forward_ms_per_step": s.get("draft_forward_ms_per_step"),
            "tokens_drafted_total": s.get("tokens_drafted_total"),
            "tokens_accepted_total": s.get("tokens_accepted_total"),
            "valid_count": s.get("valid_count"),
        }

    if len(baseline) < 4:
        raise ValueError(
            f"Expected at least 4 NAT=3 entries in Task 4.3 baseline, found {len(baseline)}. "
            f"Bands found: {sorted(baseline.keys())}"
        )

    print(f"\n[BASELINE IMPORT] Loaded {len(baseline)} NAT=3 entries from Task 4.3:")
    for band in PROMPT_BANDS:
        if band in baseline:
            b = baseline[band]
            tps = b["combined_tps"].get("mean", "?")
            ttft = b["ttft_ms"].get("mean", "?")
            ar = b.get("acceptance_rate_aggregate", "?")
            rss = b.get("peak_rss_mb", "?")
            print(f"  Band {band:>5}: tps={tps:.3f}  ttft={ttft:>10.1f}ms  "
                  f"ar={ar:.3f}  rss={rss:.1f}MB")
        else:
            print(f"  Band {band:>5}: MISSING — will be excluded from delta analysis")

    return baseline


# ===========================================================================
# Prompt construction (byte-identical to Task 4.3)
# ===========================================================================

def build_user_content_to_token_len(tokenizer: Any, target_tokens: int) -> str:
    """Build user content string padded to approximately target_tokens tokens.

    MUST be byte-identical construction to Task 4.3 to ensure only the
    sparse attention config varies across A/B comparison.
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

def create_dense_calibration_pipeline(
    target_path: Path,
    draft_path: Path,
) -> tuple[Any | None, float | None, dict[str, Any] | None]:
    """Compile dense pipeline (no sparse attention) for calibration check only."""
    t0 = time.perf_counter()
    try:
        scheduler = SchedulerConfig()
        scheduler.cache_size = SCHEDULER_CACHE_GB
        # No sparse attention — identical to Task 4.3 construction
        pipeline = LLMPipeline(
            str(target_path),
            "GPU",
            scheduler_config=scheduler,
            draft_model=ov_genai.draft_model(str(draft_path), "GPU"),
        )
        compile_ms = (time.perf_counter() - t0) * 1000.0
        return pipeline, round(compile_ms, 1), None
    except Exception as exc:  # noqa: BLE001
        return None, None, {
            "message": str(exc),
            "fingerprint": normalize_error("DENSE_PIPELINE_ERROR", str(exc)),
        }


def create_trishape_pipeline(
    target_path: Path,
    draft_path: Path,
) -> tuple[Any | None, float | None, dict[str, Any] | None]:
    """Compile TRISHAPE sparse attention pipeline."""
    t0 = time.perf_counter()
    try:
        scheduler = SchedulerConfig()
        scheduler.cache_size = SCHEDULER_CACHE_GB
        scheduler.use_sparse_attention = True
        scheduler.sparse_attention_config.mode = ov_genai.SparseAttentionMode.TRISHAPE
        # All other sparse_attention_config fields use defaults per Task4.3b spec:
        #   num_retained_start_tokens_in_cache = 128  (attention sinks)
        #   num_retained_recent_tokens_in_cache = 1920
        #   num_last_dense_tokens_in_prefill = 100
        #   xattention_block_size = 64
        #   xattention_stride = 8
        #   xattention_threshold = 0.80
        pipeline = LLMPipeline(
            str(target_path),
            "GPU",
            scheduler_config=scheduler,
            draft_model=ov_genai.draft_model(str(draft_path), "GPU"),
        )
        compile_ms = (time.perf_counter() - t0) * 1000.0
        return pipeline, round(compile_ms, 1), None
    except Exception as exc:  # noqa: BLE001
        return None, None, {
            "message": str(exc),
            "fingerprint": normalize_error("TRISHAPE_PIPELINE_ERROR", str(exc)),
        }


def create_xattention_pipeline(
    target_path: Path,
    draft_path: Path,
) -> tuple[Any | None, float | None, dict[str, Any] | None]:
    """Compile XATTENTION sparse attention pipeline."""
    t0 = time.perf_counter()
    try:
        scheduler = SchedulerConfig()
        scheduler.cache_size = SCHEDULER_CACHE_GB
        scheduler.use_sparse_attention = True
        scheduler.sparse_attention_config.mode = ov_genai.SparseAttentionMode.XATTENTION
        pipeline = LLMPipeline(
            str(target_path),
            "GPU",
            scheduler_config=scheduler,
            draft_model=ov_genai.draft_model(str(draft_path), "GPU"),
        )
        compile_ms = (time.perf_counter() - t0) * 1000.0
        return pipeline, round(compile_ms, 1), None
    except Exception as exc:  # noqa: BLE001
        return None, None, {
            "message": str(exc),
            "fingerprint": normalize_error("XATTENTION_PIPELINE_ERROR", str(exc)),
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
# Acceptance rate extraction (identical to Task 4.3)
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
# Single generation run (identical pattern to Task 4.3)
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
# Run a sparse config (warmup + measured) at a specific band
# ===========================================================================

def run_sparse_config(
    pipeline: Any,
    tokenizer: Any,
    prompt: str,
    sparse_mode_name: str,
    band: int,
) -> dict[str, Any]:
    """Run 2 warmup + 5 measured generations for one (band, sparse_mode) config."""
    gen_config = make_gen_config()

    print(f"\n    [{sparse_mode_name} band={band}] Warmup ({WARMUP_RUNS} runs)...")
    warmup_results: list[dict[str, Any]] = []
    for w in range(WARMUP_RUNS):
        r = run_single_generation(pipeline, tokenizer, prompt, gen_config)
        warmup_results.append(r)
        tps_str = f"{r['combined_tps']:.2f}" if r["combined_tps"] is not None else "N/A"
        ttft_str = f"{r['ttft_ms']:.0f}ms" if r["ttft_ms"] is not None else "N/A"
        ar_str = f", AR={r['acceptance_rate_aggregate']:.3f}" if r.get("acceptance_rate_aggregate") is not None else ""
        ok_str = "OK" if r["ok"] else f"FAIL:{r.get('error_fingerprint', '?')}"
        print(f"      Warmup {w+1}: {ok_str} tps={tps_str}  ttft={ttft_str}{ar_str}")

    # Stable RSS after warmup
    post_warmup_rss = warmup_results[-1]["peak_rss_mb"] if warmup_results else 0.0

    print(f"    [{sparse_mode_name} band={band}] Measuring ({MEASURED_RUNS} runs)...")
    measured_results: list[dict[str, Any]] = []
    for i in range(MEASURED_RUNS):
        r = run_single_generation(pipeline, tokenizer, prompt, gen_config)
        # Inject stable post-warmup RSS
        if r["ok"]:
            r["peak_rss_mb"] = post_warmup_rss
        measured_results.append(r)
        tps_str = f"{r['combined_tps']:.2f}" if r["combined_tps"] is not None else "N/A"
        ttft_str = f"{r['ttft_ms']:.0f}ms" if r["ttft_ms"] is not None else "N/A"
        ar_str = f", AR={r['acceptance_rate_aggregate']:.3f}" if r.get("acceptance_rate_aggregate") is not None else ""
        ok_str = "OK" if r["ok"] else f"FAIL:{r.get('error_fingerprint', '?')}"
        print(f"      Run {i+1}: {ok_str} tps={tps_str}  ttft={ttft_str}{ar_str}")

    valid_runs = [r for r in measured_results if r["ok"]]
    valid_count = len(valid_runs)

    summary: dict[str, Any] = {
        "valid_count": valid_count,
        "peak_rss_mb": post_warmup_rss,
    }

    if valid_count > 0:
        tps_vals = [r["combined_tps"] for r in valid_runs if r["combined_tps"] is not None]
        ttft_vals = [r["ttft_ms"] for r in valid_runs if r["ttft_ms"] is not None]
        draft_fwd_vals = [r["draft_forward_ms_per_step"] for r in valid_runs
                          if r["draft_forward_ms_per_step"] is not None]
        total_drafted = sum(r["tokens_drafted_total"] or 0 for r in valid_runs)
        total_accepted = sum(r["tokens_accepted_total"] or 0 for r in valid_runs)
        agg_ar = total_accepted / total_drafted if total_drafted > 0 else None

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
        "sparse_mode": sparse_mode_name,
        "status": status,
        "warmup_runs": len(warmup_results),
        "measured_runs": measured_results,
        "summary": summary,
    }


# ===========================================================================
# 20K OOM-safe wrapper
# ===========================================================================

def run_sparse_config_20k_safe(
    pipeline: Any,
    tokenizer: Any,
    prompt: str,
    sparse_mode_name: str,
) -> dict[str, Any]:
    """Wrap run_sparse_config with try/except for 20K OOM handling."""
    try:
        proc = psutil.Process()
        rss_now = proc.memory_info().rss / (1024 * 1024)
        if rss_now > RSS_WARNING_MB:
            print(f"    WARNING: RSS {rss_now:.0f} MB > {RSS_WARNING_MB:.0f} MB — aborting 20K band")
            return {
                "band": BAND_20K,
                "sparse_mode": sparse_mode_name,
                "status": "OOM_SKIPPED",
                "reason": f"RSS {rss_now:.0f} MB exceeds warning threshold {RSS_WARNING_MB:.0f} MB",
                "warmup_runs": 0,
                "measured_runs": [],
                "summary": {"valid_count": 0},
            }
        return run_sparse_config(pipeline, tokenizer, prompt, sparse_mode_name, BAND_20K)
    except (RuntimeError, MemoryError) as exc:
        gc.collect()
        msg = str(exc)
        print(f"    OOM at band=20480 mode={sparse_mode_name}: {msg[:120]}")
        return {
            "band": BAND_20K,
            "sparse_mode": sparse_mode_name,
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
        print(f"    ERROR at band=20480 mode={sparse_mode_name}: {msg[:120]}")
        return {
            "band": BAND_20K,
            "sparse_mode": sparse_mode_name,
            "status": "OOM_SKIPPED",
            "exception_fingerprint": normalize_error("ERROR_20K", msg),
            "exception_message": msg[:200],
            "warmup_runs": 0,
            "measured_runs": [],
            "summary": {"valid_count": 0},
        }


# ===========================================================================
# Delta computation (vs Test A dense baseline)
# ===========================================================================

def compute_deltas(
    result: dict[str, Any],
    baseline: dict[int, dict[str, Any]],
) -> dict[str, Any]:
    """Compute delta metrics for a result record vs Task 4.3 dense baseline."""
    band = result["band"]
    b = baseline.get(band)
    if b is None:
        return {"baseline_missing": True}

    deltas: dict[str, Any] = {}
    s = result.get("summary", {})

    # TTFT delta (primary metric — positive = improvement)
    b_ttft = b["ttft_ms"].get("mean") if isinstance(b["ttft_ms"], dict) else b["ttft_ms"]
    r_ttft_info = s.get("ttft_ms", {})
    r_ttft = r_ttft_info.get("mean") if isinstance(r_ttft_info, dict) else None
    if b_ttft and r_ttft and b_ttft > 0:
        deltas["ttft_delta_pct"] = round(100.0 * (b_ttft - r_ttft) / b_ttft, 2)
        deltas["ttft_ms_dense"] = round(b_ttft, 1)
        deltas["ttft_ms_sparse"] = round(r_ttft, 1)
    else:
        deltas["ttft_delta_pct"] = None
        deltas["ttft_ms_dense"] = b_ttft
        deltas["ttft_ms_sparse"] = r_ttft

    # TPS ratio
    b_tps = b["combined_tps"].get("mean") if isinstance(b["combined_tps"], dict) else b["combined_tps"]
    r_tps_info = s.get("combined_tps", {})
    r_tps = r_tps_info.get("mean") if isinstance(r_tps_info, dict) else None
    if b_tps and r_tps and b_tps > 0:
        deltas["tps_ratio"] = round(r_tps / b_tps, 4)
        deltas["tps_dense"] = round(b_tps, 4)
        deltas["tps_sparse"] = round(r_tps, 4)
    else:
        deltas["tps_ratio"] = None
        deltas["tps_dense"] = b_tps
        deltas["tps_sparse"] = r_tps

    # AR delta
    b_ar = b.get("acceptance_rate_aggregate")
    r_ar = s.get("acceptance_rate_aggregate")
    if b_ar is not None and r_ar is not None:
        deltas["ar_delta"] = round(r_ar - b_ar, 4)
        deltas["ar_dense"] = b_ar
        deltas["ar_sparse"] = r_ar
    else:
        deltas["ar_delta"] = None
        deltas["ar_dense"] = b_ar
        deltas["ar_sparse"] = r_ar

    # RSS delta
    b_rss = b.get("peak_rss_mb")
    r_rss = s.get("peak_rss_mb")
    if b_rss and r_rss:
        deltas["rss_delta_mb"] = round(r_rss - b_rss, 1)
        deltas["rss_dense_mb"] = b_rss
        deltas["rss_sparse_mb"] = r_rss
    else:
        deltas["rss_delta_mb"] = None
        deltas["rss_dense_mb"] = b_rss
        deltas["rss_sparse_mb"] = r_rss

    return deltas


# ===========================================================================
# Quality gate evaluation
# ===========================================================================

def evaluate_quality_gates(
    results: list[dict[str, Any]],
    baseline: dict[int, dict[str, Any]],
) -> dict[str, Any]:
    """Evaluate all 8 quality gates over the full result set."""
    core_bands = [b for b in PROMPT_BANDS if b != BAND_20K]

    # Index results by (sparse_mode, band)
    idx: dict[tuple[str, int], dict[str, Any]] = {}
    for r in results:
        idx[(r["sparse_mode"], r["band"])] = r

    modes = ["TRISHAPE", "XATTENTION"]

    # G-01: measurement completeness
    g01_pass = True
    g01_failures: list[str] = []
    for mode in modes:
        for band in core_bands:
            rec = idx.get((mode, band))
            if rec is None or rec["status"] in ("OOM_SKIPPED", "ALL_FAILED"):
                g01_failures.append(f"{mode}@{band}:MISSING_OR_FAILED")
                g01_pass = False
                continue
            valid_runs = [r for r in rec.get("measured_runs", []) if r.get("ok")]
            for run in valid_runs:
                mandatory = ["combined_tps", "draft_forward_ms_per_step", "tokens_drafted_total",
                             "tokens_accepted_total", "acceptance_rate_aggregate",
                             "peak_rss_mb", "ttft_ms"]
                for field in mandatory:
                    if run.get(field) is None:
                        g01_failures.append(f"{mode}@{band}:run_missing_{field}")
                        g01_pass = False

    # G-02: valid run count
    g02_pass = True
    g02_failures: list[str] = []
    for mode in modes:
        for band in core_bands:
            rec = idx.get((mode, band))
            if rec is None:
                g02_failures.append(f"{mode}@{band}:MISSING")
                g02_pass = False
                continue
            vc = rec.get("summary", {}).get("valid_count", 0)
            if vc < MEASURED_RUNS:
                g02_failures.append(f"{mode}@{band}:valid_count={vc}")
                if vc < 3:
                    g02_pass = False

    # G-03: TTFT improvement (primary metric)
    g03_per_mode: dict[str, Any] = {}
    g03_status = "MARGINAL"
    ttft_candidates: list[tuple[str, int, float]] = []

    for mode in modes:
        mode_data: dict[str, Any] = {}
        candidates = 0
        strong_candidates = 0
        for band in PROMPT_BANDS:
            rec = idx.get((mode, band))
            if rec is None or rec["status"] == "OOM_SKIPPED":
                mode_data[str(band)] = None
                continue
            delta = rec.get("delta_vs_baseline", {})
            ttft_delta = delta.get("ttft_delta_pct")
            mode_data[str(band)] = ttft_delta
            if band >= 8192 and ttft_delta is not None and ttft_delta >= 10.0:
                candidates += 1
                ttft_candidates.append((mode, band, ttft_delta))
        g03_per_mode[mode] = mode_data

        if candidates >= 2:
            strong_candidates += 1

    if any(v >= 10.0 for _, _, v in ttft_candidates):
        g03_status = "SPARSE_CANDIDATE"
    if sum(
        1 for m in modes for b in PROMPT_BANDS
        if b >= 8192
        and (((idx.get((m, b)) or {}).get("delta_vs_baseline") or {}).get("ttft_delta_pct") or 0.0) >= 10.0
    ) >= 2:
        g03_status = "STRONG_SPARSE_CANDIDATE"

    # Check by mode individually
    for mode in modes:
        mode_count = sum(
            1 for b in PROMPT_BANDS
            if b >= 8192
            and (((idx.get((mode, b)) or {}).get("delta_vs_baseline") or {}).get("ttft_delta_pct") or 0.0) >= 10.0
        )
        if mode_count >= 2:
            g03_status = "STRONG_SPARSE_CANDIDATE"
            break

    # G-04: TPS compatibility
    g04_per_mode: dict[str, Any] = {}
    g04_status = "COMPATIBLE"
    for mode in modes:
        mode_data = {}
        for band in PROMPT_BANDS:
            rec = idx.get((mode, band))
            if rec is None or rec["status"] == "OOM_SKIPPED":
                continue
            delta = rec.get("delta_vs_baseline", {})
            tps_ratio = delta.get("tps_ratio")
            mode_data[str(band)] = tps_ratio
            if tps_ratio is not None:
                if tps_ratio < 0.85:
                    g04_status = "TPS_DEGRADATION"
                elif tps_ratio < 0.95 and g04_status != "TPS_DEGRADATION":
                    g04_status = "MINOR_COST"
        g04_per_mode[mode] = mode_data

    # G-05: spec-decode interaction (CRITICAL)
    g05_status = "PASS"
    g05_details: dict[str, Any] = {}
    ar_collapse_shift = False

    for mode in modes:
        for band in PROMPT_BANDS:
            rec = idx.get((mode, band))
            if rec is None or rec["status"] == "OOM_SKIPPED":
                continue
            delta = rec.get("delta_vs_baseline", {})
            ar_delta = delta.get("ar_delta")
            ar_sparse = delta.get("ar_sparse")
            ar_dense = delta.get("ar_dense")

            # Check AR degradation at production bands (≤12K)
            if band <= 12288 and ar_delta is not None and ar_delta < -0.10:
                g05_status = "SPEC_DECODE_INTERACTION"
                g05_details[f"{mode}@{band}"] = f"AR_DELTA={ar_delta:.4f} (>{-0.10:.2f} threshold)"

            # Check AR collapse boundary shift at ≥16K
            if band >= 16384 and ar_dense == 0.0 and ar_sparse is not None and ar_sparse > 0.0:
                ar_collapse_shift = True
                g05_status = "AR_COLLAPSE_BOUNDARY_SHIFT"
                g05_details[f"{mode}@{band}_SHIFT"] = f"AR_SPARSE={ar_sparse:.4f} vs AR_DENSE=0.000 (MAJOR FINDING)"

    # G-06: RSS validation
    g06_status = "PASS"
    g06_details: dict[str, Any] = {}
    for mode in modes:
        for band in PROMPT_BANDS:
            rec = idx.get((mode, band))
            if rec is None or rec["status"] == "OOM_SKIPPED":
                continue
            delta = rec.get("delta_vs_baseline", {})
            rss_delta = delta.get("rss_delta_mb")
            if rss_delta is not None:
                if rss_delta > 0:
                    g06_status = "UNEXPECTED_RSS_INCREASE"
                    g06_details[f"{mode}@{band}"] = f"rss_delta={rss_delta:.1f}MB"
                elif band >= 8192:
                    b_rss = delta.get("rss_dense_mb") or 1
                    if b_rss > 0 and abs(rss_delta) / b_rss > 0.10:
                        if g06_status == "PASS":
                            g06_status = "RSS_IMPROVEMENT"
                        g06_details[f"{mode}@{band}_improvement"] = f"rss_delta={rss_delta:.1f}MB ({100*abs(rss_delta)/b_rss:.1f}%)"

    # G-07: memory budget
    g07_pass = True
    peak_rss_all: list[float] = []
    for r in results:
        rss = r.get("summary", {}).get("peak_rss_mb")
        if rss is not None and rss > 0:
            peak_rss_all.append(rss)
    overall_peak_rss = max(peak_rss_all) if peak_rss_all else 0.0
    if overall_peak_rss > RSS_BUDGET_MB:
        g07_pass = False

    # G-08: mode comparison
    mode_wins: dict[str, int] = {"TRISHAPE": 0, "XATTENTION": 0, "TIE": 0}
    per_band_winners: dict[str, str] = {}
    for band in PROMPT_BANDS:
        tri_rec = idx.get(("TRISHAPE", band))
        xat_rec = idx.get(("XATTENTION", band))
        if tri_rec is None or xat_rec is None:
            continue
        tri_ttft = (tri_rec.get("delta_vs_baseline") or {}).get("ttft_delta_pct")
        xat_ttft = (xat_rec.get("delta_vs_baseline") or {}).get("ttft_delta_pct")
        if tri_ttft is None and xat_ttft is None:
            per_band_winners[str(band)] = "NO_DATA"
        elif tri_ttft is None:
            per_band_winners[str(band)] = "XATTENTION"
            mode_wins["XATTENTION"] += 1
        elif xat_ttft is None:
            per_band_winners[str(band)] = "TRISHAPE"
            mode_wins["TRISHAPE"] += 1
        elif abs(tri_ttft - xat_ttft) < 3.0:
            per_band_winners[str(band)] = "TIE"
            mode_wins["TIE"] += 1
        elif tri_ttft > xat_ttft:
            per_band_winners[str(band)] = "TRISHAPE"
            mode_wins["TRISHAPE"] += 1
        else:
            per_band_winners[str(band)] = "XATTENTION"
            mode_wins["XATTENTION"] += 1

    overall_winner = max(["TRISHAPE", "XATTENTION", "EQUIVALENT"],
                         key=lambda m: mode_wins.get(m, 0) if m != "EQUIVALENT" else mode_wins.get("TIE", 0))
    if mode_wins["TIE"] > max(mode_wins["TRISHAPE"], mode_wins["XATTENTION"]):
        overall_winner = "EQUIVALENT"

    g08_result = f"{overall_winner}_WINS" if overall_winner not in ("EQUIVALENT",) else "EQUIVALENT"

    # Disposition
    if not g01_pass or not g02_pass:
        disposition = "INSUFFICIENT_EVIDENCE"
    elif g05_status == "AR_COLLAPSE_BOUNDARY_SHIFT":
        # AR collapse shift overrides as MAJOR FINDING — disposition based on other gates
        if g03_status in ("SPARSE_CANDIDATE", "STRONG_SPARSE_CANDIDATE") and g04_status in ("COMPATIBLE", "MINOR_COST"):
            disposition = "SPARSE_ENABLED_AO_CODE"
        else:
            disposition = "SPARSE_DEFERRED"
    elif g05_status == "SPEC_DECODE_INTERACTION":
        disposition = "SPARSE_DEFERRED"
    elif g04_status == "TPS_DEGRADATION":
        disposition = "SPARSE_DEFERRED"
    elif g03_status == "STRONG_SPARSE_CANDIDATE" and g04_status in ("COMPATIBLE", "MINOR_COST"):
        disposition = "SPARSE_ENABLED_AO_CODE"
    else:
        disposition = "SPARSE_DEFERRED"

    return {
        "G-01": "PASS" if g01_pass else f"FAIL:{','.join(g01_failures[:5])}",
        "G-02": "PASS" if g02_pass else f"PARTIAL:{','.join(g02_failures[:5])}",
        "G-03": g03_status,
        "G-03_per_mode_ttft_delta_pct": g03_per_mode,
        "G-03_candidates": [(m, b, v) for m, b, v in ttft_candidates],
        "G-04": g04_status,
        "G-04_per_mode_tps_ratio": g04_per_mode,
        "G-05": g05_status,
        "G-05_details": g05_details,
        "G-05_ar_collapse_shift": ar_collapse_shift,
        "G-06": g06_status,
        "G-06_details": g06_details,
        "G-07": "PASS" if g07_pass else f"FAIL:peak_rss={overall_peak_rss:.0f}MB>{RSS_BUDGET_MB:.0f}MB",
        "G-08": g08_result,
        "G-08_mode_wins": mode_wins,
        "G-08_per_band_winners": per_band_winners,
        "disposition": disposition,
    }


# ===========================================================================
# Analysis: AR collapse shift summary
# ===========================================================================

def build_analysis(
    results: list[dict[str, Any]],
    baseline: dict[int, dict[str, Any]],
) -> dict[str, Any]:
    """Build the analysis block for the evidence artifact."""
    idx: dict[tuple[str, int], dict[str, Any]] = {}
    for r in results:
        idx[(r["sparse_mode"], r["band"])] = r

    ttft_improvement: dict[str, dict[str, Any]] = {}
    tps_compatibility: dict[str, dict[str, Any]] = {}

    for mode in ["TRISHAPE", "XATTENTION"]:
        ttft_improvement[mode] = {}
        tps_compatibility[mode] = {}
        for band in PROMPT_BANDS:
            rec = idx.get((mode, band))
            if rec is None or rec["status"] == "OOM_SKIPPED":
                ttft_improvement[mode][str(band)] = None
                tps_compatibility[mode][str(band)] = None
                continue
            delta = rec.get("delta_vs_baseline", {})
            ttft_improvement[mode][str(band)] = delta.get("ttft_delta_pct")
            tps_compatibility[mode][str(band)] = delta.get("tps_ratio")

    b16k_dense = (baseline.get(16384) or {}).get("acceptance_rate_aggregate", 0.0)
    tri16k = (idx.get(("TRISHAPE", 16384)) or {}).get("summary", {}).get("acceptance_rate_aggregate")
    xat16k = (idx.get(("XATTENTION", 16384)) or {}).get("summary", {}).get("acceptance_rate_aggregate")
    shift = bool(
        (tri16k is not None and tri16k > 0.0 and b16k_dense == 0.0) or
        (xat16k is not None and xat16k > 0.0 and b16k_dense == 0.0)
    )

    rss_deltas: dict[str, dict[str, Any]] = {}
    for mode in ["TRISHAPE", "XATTENTION"]:
        rss_deltas[mode] = {}
        for band in PROMPT_BANDS:
            rec = idx.get((mode, band))
            if rec is None or rec["status"] == "OOM_SKIPPED":
                continue
            delta = rec.get("delta_vs_baseline", {})
            rss_deltas[mode][str(band)] = {
                "rss_delta_mb": delta.get("rss_delta_mb"),
                "rss_dense_mb": delta.get("rss_dense_mb"),
                "rss_sparse_mb": delta.get("rss_sparse_mb"),
            }

    tri_wins = 0
    xat_wins = 0
    for band in PROMPT_BANDS:
        tri = (idx.get(("TRISHAPE", band)) or {}).get("delta_vs_baseline", {}).get("ttft_delta_pct")
        xat = (idx.get(("XATTENTION", band)) or {}).get("delta_vs_baseline", {}).get("ttft_delta_pct")
        if tri is not None and xat is not None:
            if tri > xat + 3.0:
                tri_wins += 1
            elif xat > tri + 3.0:
                xat_wins += 1

    if tri_wins > xat_wins:
        overall_winner = "TRISHAPE"
    elif xat_wins > tri_wins:
        overall_winner = "XATTENTION"
    else:
        overall_winner = "EQUIVALENT"

    per_band_mode_comparison: dict[str, Any] = {}
    for band in PROMPT_BANDS:
        tri = (idx.get(("TRISHAPE", band)) or {}).get("delta_vs_baseline", {}).get("ttft_delta_pct")
        xat = (idx.get(("XATTENTION", band)) or {}).get("delta_vs_baseline", {}).get("ttft_delta_pct")
        if tri is None and xat is None:
            per_band_mode_comparison[str(band)] = "NO_DATA"
        elif tri is None:
            per_band_mode_comparison[str(band)] = "XATTENTION"
        elif xat is None:
            per_band_mode_comparison[str(band)] = "TRISHAPE"
        elif abs(tri - xat) < 3.0:
            per_band_mode_comparison[str(band)] = "EQUIVALENT"
        elif tri > xat:
            per_band_mode_comparison[str(band)] = "TRISHAPE"
        else:
            per_band_mode_comparison[str(band)] = "XATTENTION"

    return {
        "ttft_improvement_bands": ttft_improvement,
        "tps_compatibility": tps_compatibility,
        "ar_collapse_shift": {
            "baseline_collapse_band": 16384,
            "ar_dense_at_16k": b16k_dense,
            "trishape_ar_at_16k": tri16k,
            "xattention_ar_at_16k": xat16k,
            "collapse_boundary_shifted": shift,
        },
        "rss_deltas": rss_deltas,
        "mode_comparison": {
            "overall_winner": overall_winner,
            "per_band_winners": per_band_mode_comparison,
            "trishape_band_wins": tri_wins,
            "xattention_band_wins": xat_wins,
        },
    }


# ===========================================================================
# Main
# ===========================================================================

def main() -> None:
    print("=" * 72)
    print("P5-Task-4.3b: Dynamic Sparse Attention A/B Test")
    print(f"Branch: feature/p5-task4-3b-sparse-attention")
    print(f"Started: {now_iso()}")
    print("=" * 72)

    # -----------------------------------------------------------------------
    # PC-06: AC power check
    # -----------------------------------------------------------------------
    print("\n[CHECK] AC power...")
    power_state = enforce_ac_power_or_fail_closed()
    print(f"  AC power: {power_state}")

    # -----------------------------------------------------------------------
    # Collect metadata
    # -----------------------------------------------------------------------
    try:
        ov_version = ov.__version__ if ov is not None else "unavailable"
    except Exception:
        ov_version = "unavailable"
    try:
        ov_genai_version = ov_genai.__version__
    except Exception:
        ov_genai_version = "unavailable"

    metadata = {
        "commit_hash": git_head(),
        "python_version": platform.python_version(),
        "platform": platform.platform(),
        "openvino_version": ov_version,
        "openvino_genai_version": ov_genai_version,
        "power_envelope": power_state,
        "memory_limits": {
            "warning_rss_mb": RSS_WARNING_MB,
            "budget_rss_mb": RSS_BUDGET_MB,
        },
    }

    # -----------------------------------------------------------------------
    # Step 1: Load Task 4.3 baseline (Test A import)
    # -----------------------------------------------------------------------
    print("\n[STEP 1] Loading Task 4.3 NAT=3 baseline (Test A import)...")
    baseline = load_task43_baseline()

    baseline_entries = [
        {
            "band": band,
            "combined_tps": baseline[band]["combined_tps"],
            "ttft_ms": baseline[band]["ttft_ms"],
            "acceptance_rate_aggregate": baseline[band].get("acceptance_rate_aggregate"),
            "acceptance_rate_by_step": baseline[band].get("acceptance_rate_by_step"),
            "peak_rss_mb": baseline[band].get("peak_rss_mb"),
        }
        for band in PROMPT_BANDS if band in baseline
    ]

    # Build initial partial payload with baseline
    partial_payload: dict[str, Any] = {
        "milestone": "P5-TASK-4.3b",
        "timestamp_utc": now_iso(),
        "metadata": metadata,
        "benchmark_policy": {
            "sparse_modes": ["DENSE_IMPORTED", "TRISHAPE", "XATTENTION"],
            "prompt_bands": PROMPT_BANDS,
            "nat": NAT,
            "warmup_runs": WARMUP_RUNS,
            "measured_runs": MEASURED_RUNS,
            "max_new_tokens": MAX_NEW_TOKENS,
            "scheduler_cache_gb": SCHEDULER_CACHE_GB,
            "xattention_gpu_sdpa": "OFF (default, GPU_ENABLE_SDPA_OPTIMIZATION not set — NOT same as SparseAttentionMode)",
            "sparse_attention_defaults": SPARSE_DEFAULTS,
        },
        "test_a_baseline": {
            "source": "p5_task4_3_nat_sweep_matrix.json",
            "nat": NAT,
            "entries": baseline_entries,
        },
        "calibration": {},
        "pipeline_compile_ms": {},
        "results": [],
    }
    write_json_atomic(PARTIAL_JSON, partial_payload)
    print(f"  Baseline import saved to partial file.")

    # -----------------------------------------------------------------------
    # Step 2: Load tokenizer
    # -----------------------------------------------------------------------
    print("\n[STEP 2] Loading tokenizer...")
    tokenizer = AutoTokenizer.from_pretrained(str(TOKENIZER_DIR), trust_remote_code=True)
    print(f"  Tokenizer loaded from {TOKENIZER_DIR}")

    # -----------------------------------------------------------------------
    # Step 2b: Build prompts for all bands (byte-identical to Task 4.3)
    # -----------------------------------------------------------------------
    print("\n[STEP 2b] Building prompts for all bands...")
    prompts: dict[int, tuple[str, int]] = {}
    for band in PROMPT_BANDS:
        prompt, actual_tokens = build_prompt_for_band(tokenizer, band)
        prompts[band] = (prompt, actual_tokens)
        print(f"  Band {band:>5}: {actual_tokens} tokens (target={band})")
    prompt_4k = prompts[4096][0]

    # -----------------------------------------------------------------------
    # Step 3: Calibration check — dense pipeline, single run at 4K
    # -----------------------------------------------------------------------
    print("\n[STEP 3] Calibration check (dense pipeline, 1x generate at 4K)...")
    print("  Compiling dense calibration pipeline...")
    dense_pipeline, dense_compile_ms, dense_err = create_dense_calibration_pipeline(
        MODEL_14B, DRAFT_A_PATH
    )

    calib_result: dict[str, Any] = {
        "dense_tps_4k": None,
        "baseline_tps_4k": TASK43_CALIB_TPS,
        "delta_pct": None,
        "status": "COMPILE_FAILED",
    }
    compile_ms_dict: dict[str, Any] = {"calibration_dense": dense_compile_ms}

    if dense_pipeline is not None:
        print(f"  Dense pipeline compiled in {dense_compile_ms:.0f} ms")
        calib_gen = make_gen_config()
        print("  Running 1 dense generate at 4K...")
        calib_run = run_single_generation(dense_pipeline, tokenizer, prompt_4k, calib_gen)
        del dense_pipeline
        gc.collect()

        if calib_run["ok"] and calib_run["combined_tps"] is not None:
            calib_tps = calib_run["combined_tps"]
            delta_pct = 100.0 * (calib_tps - TASK43_CALIB_TPS) / TASK43_CALIB_TPS
            calib_status = "PASS" if abs(delta_pct) <= CALIB_TOLERANCE_PCT else "CALIBRATION_WARNING"
            calib_result = {
                "dense_tps_4k": round(calib_tps, 4),
                "baseline_tps_4k": TASK43_CALIB_TPS,
                "delta_pct": round(delta_pct, 2),
                "status": calib_status,
            }
            print(f"  Calibration: tps={calib_tps:.3f}  delta={delta_pct:+.1f}%  status={calib_status}")
        else:
            calib_result["status"] = f"GENERATE_FAILED:{calib_run.get('error_fingerprint','?')}"
            print(f"  Calibration generate failed: {calib_run.get('error_fingerprint')}")
    else:
        print(f"  Dense calibration pipeline FAILED: {dense_err}")
    gc.collect()

    partial_payload["calibration"] = calib_result
    partial_payload["pipeline_compile_ms"] = compile_ms_dict
    write_json_atomic(PARTIAL_JSON, partial_payload)

    # -----------------------------------------------------------------------
    # Step 4: TRISHAPE pipeline — test all bands
    # -----------------------------------------------------------------------
    all_results: list[dict[str, Any]] = []

    print("\n[STEP 4] Compiling TRISHAPE sparse attention pipeline...")
    tri_pipeline, tri_compile_ms, tri_err = create_trishape_pipeline(MODEL_14B, DRAFT_A_PATH)
    compile_ms_dict["trishape"] = tri_compile_ms

    if tri_pipeline is None:
        print(f"  TRISHAPE pipeline FAILED: {tri_err}")
        for band in PROMPT_BANDS:
            rec = {
                "band": band, "sparse_mode": "TRISHAPE",
                "status": "API_NOT_AVAILABLE",
                "error": tri_err,
                "warmup_runs": 0, "measured_runs": [],
                "summary": {"valid_count": 0},
                "delta_vs_baseline": {},
            }
            all_results.append(rec)
    else:
        print(f"  TRISHAPE pipeline compiled in {tri_compile_ms:.0f} ms")
        print("\n[TEST B] TRISHAPE — running all bands band-ascending...")

        for band in PROMPT_BANDS:
            prompt, actual_tokens = prompts[band]
            print(f"\n  Band {band} ({actual_tokens} tokens):")

            if band == BAND_20K:
                rec = run_sparse_config_20k_safe(tri_pipeline, tokenizer, prompt, "TRISHAPE")
            else:
                rec = run_sparse_config(tri_pipeline, tokenizer, prompt, "TRISHAPE", band)

            # Compute deltas vs Task 4.3 baseline
            rec["delta_vs_baseline"] = compute_deltas(rec, baseline)
            all_results.append(rec)

            # Print delta summary
            d = rec["delta_vs_baseline"]
            if d.get("ttft_delta_pct") is not None:
                ar_s = rec["summary"].get("acceptance_rate_aggregate")
                ar_str = f"AR={ar_s:.3f}" if ar_s is not None else "AR=N/A"
                print(f"    => TTFT delta: {d['ttft_delta_pct']:+.1f}%  "
                      f"TPS ratio: {d.get('tps_ratio', 'N/A')}  {ar_str}")

            # Save partial after each band
            partial_payload["results"] = all_results
            partial_payload["pipeline_compile_ms"] = compile_ms_dict
            write_json_atomic(PARTIAL_JSON, partial_payload)

        del tri_pipeline
        gc.collect()
        print("\n  TRISHAPE run complete. Pipeline released.")

    # -----------------------------------------------------------------------
    # Step 5: XATTENTION pipeline — test all bands
    # -----------------------------------------------------------------------
    print("\n[STEP 5] Compiling XATTENTION sparse attention pipeline...")
    xat_pipeline, xat_compile_ms, xat_err = create_xattention_pipeline(MODEL_14B, DRAFT_A_PATH)
    compile_ms_dict["xattention"] = xat_compile_ms

    if xat_pipeline is None:
        print(f"  XATTENTION pipeline FAILED: {xat_err}")
        for band in PROMPT_BANDS:
            rec = {
                "band": band, "sparse_mode": "XATTENTION",
                "status": "API_NOT_AVAILABLE",
                "error": xat_err,
                "warmup_runs": 0, "measured_runs": [],
                "summary": {"valid_count": 0},
                "delta_vs_baseline": {},
            }
            all_results.append(rec)
    else:
        print(f"  XATTENTION pipeline compiled in {xat_compile_ms:.0f} ms")
        print("\n[TEST C] XATTENTION — running all bands band-ascending...")

        for band in PROMPT_BANDS:
            prompt, actual_tokens = prompts[band]
            print(f"\n  Band {band} ({actual_tokens} tokens):")

            if band == BAND_20K:
                rec = run_sparse_config_20k_safe(xat_pipeline, tokenizer, prompt, "XATTENTION")
            else:
                rec = run_sparse_config(xat_pipeline, tokenizer, prompt, "XATTENTION", band)

            rec["delta_vs_baseline"] = compute_deltas(rec, baseline)
            all_results.append(rec)

            d = rec["delta_vs_baseline"]
            if d.get("ttft_delta_pct") is not None:
                ar_s = rec["summary"].get("acceptance_rate_aggregate")
                ar_str = f"AR={ar_s:.3f}" if ar_s is not None else "AR=N/A"
                print(f"    => TTFT delta: {d['ttft_delta_pct']:+.1f}%  "
                      f"TPS ratio: {d.get('tps_ratio', 'N/A')}  {ar_str}")

            partial_payload["results"] = all_results
            partial_payload["pipeline_compile_ms"] = compile_ms_dict
            write_json_atomic(PARTIAL_JSON, partial_payload)

        del xat_pipeline
        gc.collect()
        print("\n  XATTENTION run complete. Pipeline released.")

    # -----------------------------------------------------------------------
    # Step 6: Analysis + quality gates
    # -----------------------------------------------------------------------
    print("\n[STEP 6] Computing analysis and quality gates...")
    analysis = build_analysis(all_results, baseline)
    quality_gate = evaluate_quality_gates(all_results, baseline)

    # Print AR collapse shift prominently if detected
    if quality_gate.get("G-05_ar_collapse_shift"):
        print("\n" + "!" * 72)
        print("  MAJOR FINDING: AR_COLLAPSE_BOUNDARY_SHIFT DETECTED")
        print(f"  Sparse attention has RECOVERED speculative decoding at >=16K context")
        shift_details = quality_gate.get("G-05_details", {})
        for k, v in shift_details.items():
            if "SHIFT" in k:
                print(f"  {k}: {v}")
        print("!" * 72)

    print(f"\n  Disposition: {quality_gate['disposition']}")
    print(f"  G-01 (completeness):  {quality_gate['G-01']}")
    print(f"  G-02 (valid count):   {quality_gate['G-02']}")
    print(f"  G-03 (TTFT improv):   {quality_gate['G-03']}")
    print(f"  G-04 (TPS compat):    {quality_gate['G-04']}")
    print(f"  G-05 (spec decode):   {quality_gate['G-05']}")
    print(f"  G-06 (RSS):           {quality_gate['G-06']}")
    print(f"  G-07 (mem budget):    {quality_gate['G-07']}")
    print(f"  G-08 (mode compare):  {quality_gate['G-08']}")

    # -----------------------------------------------------------------------
    # Print TTFT delta summary table
    # -----------------------------------------------------------------------
    print("\n  TTFT delta table (positive = improvement vs dense baseline):")
    print(f"  {'Band':>6}  {'TRISHAPE':>10}  {'XATTENTION':>10}")
    for band in PROMPT_BANDS:
        tri_d = (analysis["ttft_improvement_bands"].get("TRISHAPE") or {}).get(str(band))
        xat_d = (analysis["ttft_improvement_bands"].get("XATTENTION") or {}).get(str(band))
        tri_s = f"{tri_d:+.1f}%" if tri_d is not None else "     N/A"
        xat_s = f"{xat_d:+.1f}%" if xat_d is not None else "     N/A"
        print(f"  {band:>6}  {tri_s:>10}  {xat_s:>10}")

    print("\n  AR at 16K (collapse boundary):")
    ar_info = analysis["ar_collapse_shift"]
    print(f"    Dense (Task 4.3): {ar_info['ar_dense_at_16k']:.3f}")
    print(f"    TRISHAPE:         {ar_info.get('trishape_ar_at_16k', 'N/A')}")
    print(f"    XATTENTION:       {ar_info.get('xattention_ar_at_16k', 'N/A')}")
    print(f"    Shift detected:   {ar_info['collapse_boundary_shifted']}")

    # -----------------------------------------------------------------------
    # Step 7: Write final evidence artifact
    # -----------------------------------------------------------------------
    finished_ts = now_iso()
    final_payload: dict[str, Any] = {
        "milestone": "P5-TASK-4.3b",
        "timestamp_utc": partial_payload["timestamp_utc"],
        "metadata": metadata,
        "benchmark_policy": partial_payload["benchmark_policy"],
        "calibration": calib_result,
        "pipeline_compile_ms": compile_ms_dict,
        "test_a_baseline": partial_payload["test_a_baseline"],
        "results": all_results,
        "analysis": analysis,
        "quality_gate": quality_gate,
        "finished_utc": finished_ts,
    }

    write_json_atomic(OUTPUT_JSON, final_payload)
    # Clean up partial file
    if PARTIAL_JSON.exists():
        PARTIAL_JSON.unlink()

    print(f"\n[DONE] Evidence artifact: {OUTPUT_JSON}")
    print(f"Finished: {finished_ts}")
    print("=" * 72)


if __name__ == "__main__":
    main()
