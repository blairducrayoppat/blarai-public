#!/usr/bin/env python3
"""P5-Task-4.6: Prefix Caching Study — prefix_cache {OFF, ON} × {PA, AO} × {4K, 12K}.

Tests SchedulerConfig.enable_prefix_caching across PA and AO profiles at 4096 and
12288 context bands.  Primary metric: TTFT cold vs warm-1 vs warm-2 progression.
Secondary metrics: TPS, acceptance rate, RSS.

Each (cache_setting, profile, band) group = 3 sequential calls:
  Call 1 (cold)   — KV cache empty, prefix not stored.
  Call 2 (warm-1) — system prompt prefix should be in KV cache.
  Call 3 (warm-2) — system prompt still cached.

All 3 calls use the SAME system prompt but DIFFERENT user content (seed CALL_1/2/3).

Pipeline A: enable_prefix_caching = False (explicit baseline)
Pipeline B: enable_prefix_caching = True  (test condition)

Locked constants:
  NAT=3, GPU_ENABLE_SDPA_OPTIMIZATION=True, KV_CACHE_PRECISION=FP16,
  do_sample=False, temperature=0.0, sparse_attention=OFF.

Evidence artifact: phase2_gates/evidence/p5_task4_6_prefix_cache_study.json
"""
from __future__ import annotations

import datetime
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

import psutil
from transformers import AutoTokenizer

try:
    import openvino as ov
except ImportError:
    ov = None

import openvino_genai as ov_genai

# ===========================================================================
# Paths
# ===========================================================================
REPO_ROOT = Path(__file__).resolve().parents[2]
EVIDENCE_DIR = REPO_ROOT / "phase2_gates" / "evidence"
EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)

OUTPUT_JSON = EVIDENCE_DIR / "p5_task4_6_prefix_cache_study.json"
PARTIAL_JSON = EVIDENCE_DIR / "p5_task4_6_prefix_cache_study.json.partial"

MODEL_14B = REPO_ROOT / "models" / "qwen3-14b" / "openvino-int4-gpu"
DRAFT_A_PATH = REPO_ROOT / "models" / "qwen3-0.6b" / "openvino-int4-gpu"
TOKENIZER_DIR = MODEL_14B

# ===========================================================================
# Constants (LOCKED from prior tasks)
# ===========================================================================
NAT = 3                        # LOCKED (Task 4.3 DEC-01)
SCHEDULER_CACHE_GB = 3         # Scheduler KV cache budget
PROMPT_BANDS: list[int] = [4096, 12288]
PREFIX_CACHE_SETTINGS: list[str] = ["OFF", "ON"]
PROFILES: list[str] = ["PA", "AO"]
CALL_TYPES: list[str] = ["cold", "warm-1", "warm-2"]

# Per-profile GenConfig
MAX_NEW_TOKENS_PA = 32         # Current PA production value
MAX_NEW_TOKENS_AO = 128        # Standard AO generation length
STOP_TOKEN_IDS_PA = {151645, 151668}  # im_end + think — PA fail-closed (ADR-012 §2.4)
STOP_TOKEN_IDS_AO = {151645}          # im_end only — AO standard

# System prompts (fixed per profile)
PA_SYSTEM_PROMPT = (
    "You are a security policy enforcement agent. Your task is to classify each "
    "Action Authorization Request (AAR) into one of exactly three categories: "
    "ALLOW, DENY, or ESCALATE. "
    "ALLOW: the requested action is within policy and should be permitted. "
    "DENY: the requested action violates policy and must be blocked. "
    "ESCALATE: the request is ambiguous or requires human review before proceeding. "
    "Output ONLY the label (ALLOW, DENY, or ESCALATE) on a single line. "
    "Do not include any reasoning, explanation, or additional text. /no_think"
)

AO_SYSTEM_PROMPT = (
    "You are a helpful AI assistant. Provide clear, accurate, and concise responses. "
    "/no_think"
)

# Calibration reference (Task 4.4, XAttention ON, 4K, cold)
TASK44_CALIB_TTFT_MS = 7216.0
CALIB_TOLERANCE_PCT = 30.0

# Memory
RSS_WARNING_MB = 14_000.0
RSS_BUDGET_MB = 15_507.0


# ===========================================================================
# Utilities
# ===========================================================================

def now_iso() -> str:
    return datetime.datetime.now(tz=datetime.timezone.utc).isoformat()


def git_head() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=str(REPO_ROOT), text=True, timeout=5,
        ).strip()
    except Exception:
        return "UNKNOWN"


def write_json_atomic(path: Path, data: Any) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
    tmp.replace(path)


def normalize_error(category: str, msg: str) -> str:
    msg_clean = msg[:200].replace("\n", " ").strip()
    return f"{category}::{msg_clean}"


def stats_dict(vals: list[float]) -> dict[str, Any]:
    if not vals:
        return {"mean": None, "stdev": None, "min": None, "max": None, "n": 0}
    return {
        "mean": round(statistics.fmean(vals), 4),
        "stdev": round(statistics.stdev(vals), 4) if len(vals) > 1 else 0.0,
        "min": round(min(vals), 4),
        "max": round(max(vals), 4),
        "n": len(vals),
    }


# ===========================================================================
# Crash-resilient resumption
# ===========================================================================

def load_completed_from_partial() -> tuple[
    list[dict[str, Any]], set[tuple[str, str, int]],
    dict[str, Any] | None, dict[str, Any] | None,
]:
    """Load completed groups from partial JSON for crash recovery.

    Returns (results_list, completed_keys, calibration, pipeline_compile_ms)
    where each key is (cache_setting, profile, band). Only groups with
    status='completed' are considered resumable.
    """
    if not PARTIAL_JSON.exists():
        return [], set(), None, None

    try:
        with open(PARTIAL_JSON, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (json.JSONDecodeError, OSError) as exc:
        print(f"[RESUME] WARNING: Could not read partial JSON: {exc}")
        return [], set(), None, None

    results = data.get("results", [])
    completed: set[tuple[str, str, int]] = set()
    valid_results: list[dict[str, Any]] = []

    for r in results:
        cache_setting = r.get("cache_setting")
        profile = r.get("profile")
        band = r.get("band")
        status = r.get("status")
        if (
            status == "completed"
            and cache_setting is not None
            and profile is not None
            and band is not None
        ):
            completed.add((cache_setting, profile, band))
            valid_results.append(r)
            ttfts = [c.get("ttft_ms", "N/A") for c in r.get("calls", [])]
            print(f"[RESUME] Recovered: {cache_setting}/{profile}/{band}  "
                  f"TTFT={ttfts}")

    if completed:
        print(f"[RESUME] {len(completed)} groups recovered — will skip these.")
    else:
        print("[RESUME] No completed groups found in partial — starting fresh.")

    calibration = data.get("calibration")
    compile_ms = data.get("pipeline_compile_ms")
    return valid_results, completed, calibration, compile_ms


# ===========================================================================
# Power check
# ===========================================================================

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
        self._stop.clear()
        self.peak = float(self._proc.memory_info().rss)
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=3)


# ===========================================================================
# Prompt construction (adapted for dual system prompts + seeded user content)
# ===========================================================================

def build_user_content_to_token_len(
    tokenizer: Any,
    target_tokens: int,
    system_prompt: str,
    seed: str = "",
) -> str:
    """Build user content string padded to reach approximately target_tokens total.

    The target_tokens is the total prompt token count (system + user + template tokens).
    This function iteratively grows user content until the full chat prompt reaches
    target_tokens, accounting for system prompt and chat template overhead.
    """
    chunk = (
        f" local privacy deterministic benchmark payload {seed} "
        "nat sweep context bands acceptance rate throughput "
        "speculative decoding draft target model qwen3 "
    )
    text = f"Benchmark prompt for Task 4.6 prefix cache study seed={seed}. "
    messages_template = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": ""},
    ]
    # Measure template overhead (system prompt + chat markup)
    template_str = tokenizer.apply_chat_template(
        messages_template, tokenize=False, add_generation_prompt=True,
    )
    template_toks = len(tokenizer(template_str, return_tensors="np")["input_ids"][0])
    # Target tokens for user content only
    user_target = max(target_tokens - template_toks, 100)

    for _ in range(500_000):
        toks = tokenizer(text, return_tensors="np")["input_ids"][0]
        if len(toks) >= user_target:
            break
        text += chunk
    # Trim to exact length if overshot
    toks = tokenizer(text, return_tensors="np")["input_ids"][0]
    if len(toks) > user_target:
        text = tokenizer.decode(toks[:user_target], skip_special_tokens=True)
    return text


def build_chat_prompt(tokenizer: Any, system_prompt: str, user_content: str) -> str:
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_content},
    ]
    return tokenizer.apply_chat_template(
        messages, tokenize=False, add_generation_prompt=True,
    )


def get_system_prompt(profile: str) -> str:
    return PA_SYSTEM_PROMPT if profile == "PA" else AO_SYSTEM_PROMPT


def build_all_prompts(
    tokenizer: Any,
) -> dict[tuple[str, int, str], tuple[str, int]]:
    """Build all prompts for all (profile, band, call_seed) combinations.

    Returns dict mapping (profile, band, seed) -> (prompt_str, token_count).
    """
    prompts: dict[tuple[str, int, str], tuple[str, int]] = {}
    seeds = ["CALL_1", "CALL_2", "CALL_3"]

    for profile in PROFILES:
        sys_prompt = get_system_prompt(profile)
        for band in PROMPT_BANDS:
            for seed in seeds:
                user_content = build_user_content_to_token_len(
                    tokenizer, band, sys_prompt, seed=seed,
                )
                prompt = build_chat_prompt(tokenizer, sys_prompt, user_content)
                tok_count = len(tokenizer(prompt, return_tensors="np")["input_ids"][0])
                prompts[(profile, band, seed)] = (prompt, tok_count)
    return prompts


# ===========================================================================
# Pipeline construction
# ===========================================================================

def create_pipeline(
    target_path: Path,
    draft_path: Path,
    enable_prefix_caching: bool,
    label: str,
) -> tuple[Any | None, float | None, str | None]:
    """Create LLMPipeline with given prefix caching setting.

    Returns (pipeline, compile_ms, error_msg).
    """
    print(f"\n[PIPELINE {label}] Compiling (prefix_cache={'ON' if enable_prefix_caching else 'OFF'})...")
    try:
        scheduler = ov_genai.SchedulerConfig()
        scheduler.cache_size = SCHEDULER_CACHE_GB
        scheduler.enable_prefix_caching = enable_prefix_caching

        t0 = time.perf_counter()
        pipeline = ov_genai.LLMPipeline(
            str(target_path),
            "GPU",
            scheduler_config=scheduler,
            draft_model=ov_genai.draft_model(str(draft_path), "GPU"),
            **{"GPU_ENABLE_SDPA_OPTIMIZATION": True},
        )
        compile_ms = (time.perf_counter() - t0) * 1000.0
        print(f"  Compiled in {compile_ms:.0f}ms")
        return pipeline, compile_ms, None
    except Exception as exc:  # noqa: BLE001
        msg = str(exc)
        print(f"  COMPILATION FAILED: {msg}")
        return None, None, msg


# ===========================================================================
# Generation configs
# ===========================================================================

def make_gen_config_pa() -> Any:
    cfg = ov_genai.GenerationConfig()
    cfg.max_new_tokens = MAX_NEW_TOKENS_PA
    cfg.do_sample = False
    cfg.temperature = 0.0
    cfg.top_k = 1
    cfg.top_p = 1.0
    cfg.num_assistant_tokens = NAT
    cfg.assistant_confidence_threshold = 0.0
    cfg.stop_token_ids = set(STOP_TOKEN_IDS_PA)
    return cfg


def make_gen_config_ao() -> Any:
    cfg = ov_genai.GenerationConfig()
    cfg.max_new_tokens = MAX_NEW_TOKENS_AO
    cfg.do_sample = False
    cfg.temperature = 0.0
    cfg.top_k = 1
    cfg.top_p = 1.0
    cfg.num_assistant_tokens = NAT
    cfg.assistant_confidence_threshold = 0.0
    cfg.stop_token_ids = set(STOP_TOKEN_IDS_AO)
    return cfg


def make_gen_config(profile: str) -> Any:
    return make_gen_config_pa() if profile == "PA" else make_gen_config_ao()


# ===========================================================================
# Acceptance rate extraction (from m_batch_sizes — speculative decoding)
# ===========================================================================

def extract_acceptance_metrics(perf_metrics: Any, nat: int) -> dict[str, Any]:
    """Extract acceptance rate from raw perf_metrics.m_batch_sizes."""
    try:
        raw = perf_metrics.raw_metrics
        batch_sizes = list(raw.m_batch_sizes)
    except (AttributeError, TypeError):
        return {
            "acceptance_data_source": "N/A",
            "total_speculative_episodes": None,
            "tokens_drafted_total": None,
            "tokens_accepted_total": None,
            "acceptance_rate_aggregate": None,
            "acceptance_rate_by_step": None,
        }

    if not batch_sizes:
        return {
            "acceptance_data_source": "m_batch_sizes_empty",
            "total_speculative_episodes": 0,
            "tokens_drafted_total": 0,
            "tokens_accepted_total": 0,
            "acceptance_rate_aggregate": 0.0,
            "acceptance_rate_by_step": None,
        }

    episodes = len(batch_sizes)
    tokens_accepted = sum(b - 1 for b in batch_sizes)
    tokens_drafted = nat * episodes
    ar_aggregate = tokens_accepted / tokens_drafted if tokens_drafted > 0 else 0.0

    # Per-step acceptance (simplified — aggregate per position not possible from m_batch_sizes alone)
    # This gives a single aggregate rate, not per-step breakdown.
    return {
        "acceptance_data_source": "m_batch_sizes",
        "total_speculative_episodes": episodes,
        "tokens_drafted_total": tokens_drafted,
        "tokens_accepted_total": tokens_accepted,
        "acceptance_rate_aggregate": round(ar_aggregate, 4),
        "acceptance_rate_by_step": None,  # Not decomposable from m_batch_sizes
    }


# ===========================================================================
# Extended perf metrics extraction
# ===========================================================================

def extract_extended_perf_metrics(output: Any) -> dict[str, Any]:
    """Extract native throughput/TTFT/accepted from perf_metrics."""
    result: dict[str, Any] = {"extended_metrics_available": False}
    try:
        pm = output.perf_metrics
    except AttributeError:
        return result

    try:
        result["native_tps"] = round(pm.get_throughput().mean, 4)
    except Exception:
        pass

    try:
        result["native_ttft_ms"] = round(pm.get_ttft().mean, 2)
    except Exception:
        pass

    try:
        result["native_accepted_tokens"] = int(pm.get_num_accepted_tokens())
    except Exception:
        pass

    if any(k in result for k in ("native_tps", "native_ttft_ms", "native_accepted_tokens")):
        result["extended_metrics_available"] = True

    return result


# ===========================================================================
# Single generation call
# ===========================================================================

def run_single_call(
    pipeline: Any,
    tokenizer: Any,
    prompt: str,
    gen_config: Any,
) -> dict[str, Any]:
    """Execute a single generate() call and collect all metrics."""
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
        # CRITICAL: list-input returns DecodedResults with all metrics
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

        # Prefer native metrics
        combined_tps: float | None = None
        ttft_ms_native: float | None = None
        native_accepted_tokens: int | None = None

        ext = extract_extended_perf_metrics(output)
        if ext.get("extended_metrics_available"):
            combined_tps = ext.get("native_tps")
            ttft_ms_native = ext.get("native_ttft_ms")
            native_accepted_tokens = ext.get("native_accepted_tokens")

        if combined_tps is None:
            combined_tps = round(tps_wc, 4)
        if ttft_ms_native is None:
            ttft_ms_native = round(ttft_ms_wc, 1)

        # Acceptance rate from m_batch_sizes
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

        return {
            "ok": True,
            "ttft_ms": ttft_ms_native,
            "combined_tps": combined_tps,
            "acceptance_rate": accept_data["acceptance_rate_aggregate"],
            "peak_rss_mb": round(rss_peak, 1),
            "tokens_output": tokens_generated,
            # supplementary
            "total_ms": round(total_ms, 1),
            "tps_wallclock": round(tps_wc, 4),
            "ttft_ms_wallclock": round(ttft_ms_wc, 1),
            "ttft_source": "stream_callback" if has_stream_ttft else "native_or_perfmetrics",
            "rss_before_mb": round(rss_before, 1),
            "rss_after_mb": round(rss_after, 1),
            "acceptance_data_source": accept_data["acceptance_data_source"],
            "total_speculative_episodes": accept_data["total_speculative_episodes"],
            "tokens_drafted_total": accept_data["tokens_drafted_total"],
            "tokens_accepted_total": accept_data["tokens_accepted_total"],
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
            "ttft_ms": None,
            "combined_tps": None,
            "acceptance_rate": None,
            "peak_rss_mb": round(rss_peak, 1),
            "tokens_output": 0,
            "total_ms": 0.0,
            "tps_wallclock": 0.0,
            "ttft_ms_wallclock": 0.0,
            "ttft_source": "N/A_FAILED",
            "rss_before_mb": round(rss_before, 1),
            "rss_after_mb": round(rss_after, 1),
            "acceptance_data_source": "N/A_FAILED",
            "total_speculative_episodes": None,
            "tokens_drafted_total": None,
            "tokens_accepted_total": None,
            "native_accepted_tokens": None,
            "extended_metrics": {},
            "error": msg,
            "error_fingerprint": normalize_error("GENERATION_ERROR", msg),
        }


# ===========================================================================
# Run one (profile, band) group — 3 sequential calls
# ===========================================================================

def run_group(
    pipeline: Any,
    tokenizer: Any,
    prompts: dict[tuple[str, int, str], tuple[str, int]],
    cache_label: str,
    profile: str,
    band: int,
) -> dict[str, Any]:
    """Run cold → warm-1 → warm-2 for one (cache_setting, profile, band) group."""
    gen_config = make_gen_config(profile)
    seeds = ["CALL_1", "CALL_2", "CALL_3"]
    call_types = ["cold", "warm-1", "warm-2"]

    print(f"\n  [{cache_label} {profile} {band}] Starting 3 sequential calls...")

    calls: list[dict[str, Any]] = []
    for i, (seed, call_type) in enumerate(zip(seeds, call_types)):
        prompt, tok_count = prompts[(profile, band, seed)]
        print(f"    Call {i + 1} ({call_type}, seed={seed}, {tok_count} tokens)...")

        result = run_single_call(pipeline, tokenizer, prompt, gen_config)

        ttft_str = f"{result['ttft_ms']:.0f}ms" if result["ttft_ms"] is not None else "N/A"
        tps_str = f"{result['combined_tps']:.2f}" if result["combined_tps"] is not None else "N/A"
        ar_str = (f", AR={result['acceptance_rate']:.3f}"
                  if result.get("acceptance_rate") is not None else "")
        ok_str = "OK" if result["ok"] else f"FAIL:{result.get('error_fingerprint', '?')}"
        print(f"      {ok_str} ttft={ttft_str}  tps={tps_str}  "
              f"tokens={result['tokens_output']}  RSS={result['peak_rss_mb']:.0f}MB{ar_str}")

        call_record = {
            "call_idx": i + 1,
            "call_type": call_type,
            "seed": seed,
            "ttft_ms": result["ttft_ms"],
            "combined_tps": result["combined_tps"],
            "acceptance_rate": result["acceptance_rate"],
            "peak_rss_mb": result["peak_rss_mb"],
            "tokens_output": result["tokens_output"],
            "ok": result["ok"],
            "error": result.get("error"),
        }
        calls.append(call_record)

    # Determine group status
    valid_calls = [c for c in calls if c["ok"] and c["ttft_ms"] is not None]
    if len(valid_calls) >= 2:
        status = "completed"
    else:
        status = "INSUFFICIENT_DATA"

    # Summary line
    if valid_calls:
        ttfts = [c["ttft_ms"] for c in valid_calls]
        print(f"    [{cache_label} {profile} {band}] TTFT: {' → '.join(f'{t:.0f}ms' for t in ttfts)}  "
              f"valid={len(valid_calls)}/3  status={status}")
    else:
        print(f"    [{cache_label} {profile} {band}] No valid calls. status={status}")

    return {
        "cache_setting": cache_label,
        "profile": profile,
        "band": band,
        "status": status,
        "calls": calls,
    }


# ===========================================================================
# Calibration check
# ===========================================================================

def calibration_check(results_off: list[dict[str, Any]]) -> dict[str, Any]:
    """Compare Pipeline A PA 4K cold TTFT with Task 4.4 reference (7,216ms ON)."""
    # Find PA 4K group in Pipeline A (OFF) results
    pa_4k = [r for r in results_off if r["profile"] == "PA" and r["band"] == 4096]
    if not pa_4k or not pa_4k[0]["calls"]:
        return {
            "pipeline_a_pa_4k_cold_ttft_ms": None,
            "task44_reference_ttft_ms": TASK44_CALIB_TTFT_MS,
            "delta_pct": None,
            "status": "NO_PA_4K_DATA",
        }

    cold_call = pa_4k[0]["calls"][0]
    if cold_call["ttft_ms"] is None:
        return {
            "pipeline_a_pa_4k_cold_ttft_ms": None,
            "task44_reference_ttft_ms": TASK44_CALIB_TTFT_MS,
            "delta_pct": None,
            "status": "COLD_TTFT_MISSING",
        }

    cold_ttft = cold_call["ttft_ms"]
    delta_pct = ((cold_ttft - TASK44_CALIB_TTFT_MS) / TASK44_CALIB_TTFT_MS) * 100.0
    status = "PASS" if abs(delta_pct) <= CALIB_TOLERANCE_PCT else "CALIBRATION_WARNING"

    print(f"\n[CALIBRATION] Pipeline A PA 4K cold TTFT: {cold_ttft:.0f}ms vs "
          f"Task 4.4 ref: {TASK44_CALIB_TTFT_MS:.0f}ms")
    print(f"  Delta: {delta_pct:+.1f}% (threshold: ±{CALIB_TOLERANCE_PCT}%)")
    print(f"  Status: {status}")

    return {
        "pipeline_a_pa_4k_cold_ttft_ms": round(cold_ttft, 1),
        "task44_reference_ttft_ms": TASK44_CALIB_TTFT_MS,
        "delta_pct": round(delta_pct, 2),
        "status": status,
    }


# ===========================================================================
# Spec-decode compatibility check
# ===========================================================================

def check_spec_decode_compatibility(
    results_on: list[dict[str, Any]],
    results_off: list[dict[str, Any]],
) -> dict[str, Any]:
    """Check indicators of spec-decode incompatibility with prefix caching."""
    issues: list[str] = []

    # Indicator 2: warm-1 TTFT >= cold TTFT at ALL (profile, band) groups in Pipeline B
    all_warm_worse = True
    for r in results_on:
        if len(r["calls"]) >= 2:
            cold_ttft = r["calls"][0].get("ttft_ms")
            warm1_ttft = r["calls"][1].get("ttft_ms")
            if cold_ttft is not None and warm1_ttft is not None:
                if warm1_ttft < cold_ttft:
                    all_warm_worse = False
                    break
    if all_warm_worse and results_on:
        issues.append("WARM_TTFT_NEVER_IMPROVED")

    # Indicator 3: AR collapse in Pipeline B but not Pipeline A
    ar_collapse = False
    for r_on in results_on:
        matching_off = [r for r in results_off
                        if r["profile"] == r_on["profile"] and r["band"] == r_on["band"]]
        if not matching_off:
            continue
        r_off = matching_off[0]
        for call_on in r_on["calls"]:
            ar_on = call_on.get("acceptance_rate")
            if ar_on is not None and ar_on == 0.0:
                # Check if Pipeline A had non-zero AR
                for call_off in r_off["calls"]:
                    ar_off = call_off.get("acceptance_rate")
                    if ar_off is not None and ar_off > 0.05:
                        ar_collapse = True
                        break
            if ar_collapse:
                break
        if ar_collapse:
            break
    if ar_collapse:
        issues.append("AR_COLLAPSE_ON_ONLY")

    if "AR_COLLAPSE_ON_ONLY" in issues:
        return {"status": "SPEC_DECODE_INCOMPATIBLE", "issues": issues}
    if "WARM_TTFT_NEVER_IMPROVED" in issues:
        return {"status": "PREFIX_CACHE_NO_BENEFIT", "issues": issues}
    return {"status": "COMPATIBLE", "issues": []}


# ===========================================================================
# Analysis + Quality Gates
# ===========================================================================

def compute_analysis(
    results_off: list[dict[str, Any]],
    results_on: list[dict[str, Any]],
    sys_prompt_token_counts: dict[str, int],
    prompt_token_counts: dict[str, dict[str, int]],
) -> dict[str, Any]:
    """Compute TTFT cold/warm comparison and summary analysis."""

    def _get_ttfts(group: dict[str, Any]) -> tuple[float | None, float | None, float | None]:
        calls = group.get("calls", [])
        cold = calls[0]["ttft_ms"] if len(calls) > 0 else None
        warm1 = calls[1]["ttft_ms"] if len(calls) > 1 else None
        warm2 = calls[2]["ttft_ms"] if len(calls) > 2 else None
        return cold, warm1, warm2

    ttft_comparison: dict[str, Any] = {}
    for profile in PROFILES:
        for band in PROMPT_BANDS:
            key = f"{profile}_{band}"
            off_group = [r for r in results_off
                         if r["profile"] == profile and r["band"] == band]
            on_group = [r for r in results_on
                        if r["profile"] == profile and r["band"] == band]

            if not off_group or not on_group:
                ttft_comparison[key] = {"verdict": "MISSING_DATA"}
                continue

            off_cold, off_warm1, off_warm2 = _get_ttfts(off_group[0])
            on_cold, on_warm1, on_warm2 = _get_ttfts(on_group[0])

            # Compute ON warm reductions
            on_reduction_warm1 = None
            on_reduction_warm2 = None
            if on_cold is not None and on_cold > 0:
                if on_warm1 is not None:
                    on_reduction_warm1 = round(
                        (on_cold - on_warm1) / on_cold * 100.0, 2,
                    )
                if on_warm2 is not None:
                    on_reduction_warm2 = round(
                        (on_cold - on_warm2) / on_cold * 100.0, 2,
                    )

            # OFF warm reductions (inherent sequential optimization check)
            off_reduction_warm1 = None
            if off_cold is not None and off_cold > 0 and off_warm1 is not None:
                off_reduction_warm1 = round(
                    (off_cold - off_warm1) / off_cold * 100.0, 2,
                )

            # Verdict based on ON warm-1 reduction
            if on_reduction_warm1 is None:
                verdict = "MISSING_DATA"
            elif on_reduction_warm1 > 20.0:
                verdict = "STRONG_BENEFIT"
            elif on_reduction_warm1 >= 5.0:
                verdict = "MODEST_BENEFIT"
            elif on_reduction_warm1 >= -5.0:
                verdict = "NO_BENEFIT"
            else:
                verdict = "CACHE_OVERHEAD"

            ttft_comparison[key] = {
                "off_cold": round(off_cold, 1) if off_cold is not None else None,
                "off_warm1": round(off_warm1, 1) if off_warm1 is not None else None,
                "off_warm2": round(off_warm2, 1) if off_warm2 is not None else None,
                "on_cold": round(on_cold, 1) if on_cold is not None else None,
                "on_warm1": round(on_warm1, 1) if on_warm1 is not None else None,
                "on_warm2": round(on_warm2, 1) if on_warm2 is not None else None,
                "on_reduction_warm1_pct": on_reduction_warm1,
                "on_reduction_warm2_pct": on_reduction_warm2,
                "off_reduction_warm1_pct": off_reduction_warm1,
                "verdict": verdict,
            }

    # Spec-decode compatibility
    compat = check_spec_decode_compatibility(results_on, results_off)

    # AR interaction check (within Pipeline B: cold vs warm)
    ar_interaction = "NONE"
    for r in results_on:
        calls = r.get("calls", [])
        if len(calls) >= 2:
            ar_cold = calls[0].get("acceptance_rate")
            for c in calls[1:]:
                ar_warm = c.get("acceptance_rate")
                if ar_cold is not None and ar_warm is not None:
                    if abs(ar_warm - ar_cold) > 0.05:
                        ar_interaction = "SPEC_DECODE_INTERACTION"
                        break

    # RSS overhead
    rss_overhead_12k = None
    off_12k = [r for r in results_off if r["band"] == 12288]
    on_12k = [r for r in results_on if r["band"] == 12288]
    if off_12k and on_12k:
        off_rss_max = max(
            (c["peak_rss_mb"] for c in off_12k[0]["calls"] if c.get("peak_rss_mb") is not None),
            default=None,
        )
        on_rss_max = max(
            (c["peak_rss_mb"] for c in on_12k[0]["calls"] if c.get("peak_rss_mb") is not None),
            default=None,
        )
        if off_rss_max is not None and on_rss_max is not None:
            rss_overhead_12k = round(on_rss_max - off_rss_max, 1)

    # Shared prefix fractions
    shared_prefix_fractions: dict[str, float | None] = {}
    for profile in PROFILES:
        sp_tokens = sys_prompt_token_counts.get(profile.lower(), 0)
        for band in PROMPT_BANDS:
            key = f"{profile.lower()}_{band}"
            total = prompt_token_counts.get(profile, {}).get(str(band), band)
            if total > 0:
                shared_prefix_fractions[key] = round(sp_tokens / total * 100.0, 2)
            else:
                shared_prefix_fractions[key] = None

    return {
        "ttft_comparison": ttft_comparison,
        "spec_decode_compatibility": compat["status"],
        "spec_decode_issues": compat["issues"],
        "ar_interaction": ar_interaction,
        "rss_overhead_12k_mb": rss_overhead_12k,
        "shared_prefix_fractions": shared_prefix_fractions,
    }


def evaluate_quality_gates(
    results_off: list[dict[str, Any]],
    results_on: list[dict[str, Any]],
    analysis: dict[str, Any],
) -> dict[str, Any]:
    """Evaluate quality gates G-01..G-07 per Task 4.6 spec."""
    gates: dict[str, Any] = {}
    all_results = results_off + results_on

    # G-01: measurement completeness — all 5 mandatory fields for all 24 calls
    missing_ttft = 0
    total_calls = 0
    for r in all_results:
        for c in r.get("calls", []):
            total_calls += 1
            if c.get("ttft_ms") is None:
                missing_ttft += 1
    gates["G-01"] = "PASS" if missing_ttft == 0 else f"FAIL ({missing_ttft}/{total_calls} missing ttft_ms)"

    # G-02: valid group count — each group needs ≥2 valid calls
    invalid_groups: list[str] = []
    for r in all_results:
        valid = sum(1 for c in r.get("calls", []) if c.get("ok") and c.get("ttft_ms") is not None)
        if valid < 2:
            invalid_groups.append(f"{r['cache_setting']}_{r['profile']}_{r['band']}(valid={valid})")
    gates["G-02"] = "PASS" if not invalid_groups else f"FAIL ({'; '.join(invalid_groups)})"

    # G-03: TTFT warm reduction (PRIMARY)
    ttft_comp = analysis["ttft_comparison"]
    g03_per_group: dict[str, str] = {}
    verdicts: list[str] = []
    for key, comp in ttft_comp.items():
        verdict = comp.get("verdict", "MISSING_DATA")
        g03_per_group[key] = verdict
        if verdict != "MISSING_DATA":
            verdicts.append(verdict)

    if all(v in ("STRONG_BENEFIT", "MODEST_BENEFIT") for v in verdicts) and verdicts:
        g03_summary = "ALL_BENEFIT"
    elif all(v == "STRONG_BENEFIT" for v in verdicts) and verdicts:
        g03_summary = "ALL_STRONG"
    elif all(v == "NO_BENEFIT" for v in verdicts) and verdicts:
        g03_summary = "ALL_NO_BENEFIT"
    elif any(v == "CACHE_OVERHEAD" for v in verdicts):
        g03_summary = "CACHE_OVERHEAD_DETECTED"
    elif verdicts:
        g03_summary = "MIXED"
    else:
        g03_summary = "NO_DATA"

    gates["G-03"] = {"per_group": g03_per_group, "summary": g03_summary}

    # G-04: PA budget gate
    pa_4k_on = [r for r in results_on if r["profile"] == "PA" and r["band"] == 4096]
    if pa_4k_on and len(pa_4k_on[0]["calls"]) >= 2:
        warm1_ttft = pa_4k_on[0]["calls"][1].get("ttft_ms")
        if warm1_ttft is not None:
            if warm1_ttft <= 300:
                gates["G-04"] = f"PA_BUDGET_MET (warm1={warm1_ttft:.0f}ms ≤ 300ms)"
            elif warm1_ttft <= 1500:
                gates["G-04"] = f"PA_BUDGET_IMPROVED (warm1={warm1_ttft:.0f}ms ≤ 1500ms)"
            else:
                gates["G-04"] = f"PA_WARM_HIGH (warm1={warm1_ttft:.0f}ms > 1500ms)"
        else:
            gates["G-04"] = "MISSING_DATA"
    else:
        gates["G-04"] = "MISSING_DATA"

    # G-05: AR preservation
    gates["G-05"] = analysis["ar_interaction"]
    if gates["G-05"] == "NONE":
        gates["G-05"] = "PASS"

    # G-06: RSS impact
    rss_overhead = analysis.get("rss_overhead_12k_mb")
    if rss_overhead is not None and abs(rss_overhead) > 1000:
        gates["G-06"] = f"CACHE_MEMORY_OVERHEAD (delta={rss_overhead:.0f}MB at 12K)"
    else:
        overhead_str = f" (delta={rss_overhead:.0f}MB at 12K)" if rss_overhead is not None else ""
        gates["G-06"] = f"PASS{overhead_str}"

    # G-07: Memory budget
    max_rss_any = 0.0
    for r in all_results:
        for c in r.get("calls", []):
            rss = c.get("peak_rss_mb")
            if rss is not None and rss > max_rss_any:
                max_rss_any = rss
    if max_rss_any > RSS_BUDGET_MB:
        gates["G-07"] = f"MEMORY_BUDGET_EXCEEDED (peak={max_rss_any:.0f}MB > {RSS_BUDGET_MB:.0f}MB)"
    else:
        gates["G-07"] = f"PASS (peak={max_rss_any:.0f}MB)"

    # Disposition
    g01_pass = gates["G-01"] == "PASS"
    g02_pass = gates["G-02"] == "PASS"

    if not g01_pass or not g02_pass:
        disposition = "INSUFFICIENT_EVIDENCE"
    elif analysis["spec_decode_compatibility"] == "SPEC_DECODE_INCOMPATIBLE":
        disposition = "SPEC_DECODE_INCOMPATIBLE"
    elif isinstance(gates["G-04"], str) and "PA_BUDGET_MET" in gates["G-04"]:
        disposition = "PREFIX_CACHE_MANDATORY_PA"
    elif g03_summary in ("ALL_BENEFIT", "ALL_STRONG"):
        disposition = "PREFIX_CACHE_BENEFICIAL"
    elif g03_summary == "ALL_NO_BENEFIT":
        disposition = "PREFIX_CACHE_NO_BENEFIT"
    elif g03_summary == "MIXED":
        disposition = "PREFIX_CACHE_CONTEXT_DEPENDENT"
    elif g03_summary == "CACHE_OVERHEAD_DETECTED":
        disposition = "PREFIX_CACHE_NO_BENEFIT"
    else:
        disposition = "INSUFFICIENT_EVIDENCE"

    gates["disposition"] = disposition
    return gates


# ===========================================================================
# Main
# ===========================================================================

def main() -> None:  # noqa: C901
    start_time = now_iso()
    print("=" * 72)
    print("P5-Task-4.6: Prefix Caching Study (PA/AO Profiles)")
    print("=" * 72)
    print(f"Start: {start_time}")
    print(f"Profiles: {PROFILES}")
    print(f"Bands: {PROMPT_BANDS}")
    print(f"Prefix cache settings: {PREFIX_CACHE_SETTINGS}")
    print(f"NAT={NAT} (LOCKED), max_new_tokens: PA={MAX_NEW_TOKENS_PA}, AO={MAX_NEW_TOKENS_AO}")
    print(f"Scheduler cache: {SCHEDULER_CACHE_GB}GB")

    # PC-05: AC power check
    power_state = enforce_ac_power_or_fail_closed()
    print(f"\n[POWER] {power_state}")

    # Load tokenizer
    print(f"\n[TOKENIZER] Loading from {TOKENIZER_DIR}...")
    tokenizer = AutoTokenizer.from_pretrained(str(TOKENIZER_DIR), trust_remote_code=True)
    print("  Tokenizer loaded.")

    # Count system prompt tokens
    pa_sp_tokens = len(tokenizer(PA_SYSTEM_PROMPT, return_tensors="np")["input_ids"][0])
    ao_sp_tokens = len(tokenizer(AO_SYSTEM_PROMPT, return_tensors="np")["input_ids"][0])
    sys_prompt_token_counts = {"pa": pa_sp_tokens, "ao": ao_sp_tokens}
    print(f"\n[SYSTEM PROMPTS] PA: {pa_sp_tokens} tokens, AO: {ao_sp_tokens} tokens")

    # Build ALL prompts before pipeline compilation
    print("\n[PROMPTS] Building all prompts (2 profiles × 2 bands × 3 seeds = 12 prompts)...")
    prompts = build_all_prompts(tokenizer)
    prompt_token_counts: dict[str, dict[str, int]] = {}
    for (profile, band, seed), (_, tok_count) in prompts.items():
        if profile not in prompt_token_counts:
            prompt_token_counts[profile] = {}
        # Store first seed's count as representative
        if str(band) not in prompt_token_counts[profile]:
            prompt_token_counts[profile][str(band)] = tok_count
        print(f"  {profile} band={band} seed={seed}: {tok_count} tokens")

    # Compute shared prefix fractions
    shared_prefix_fractions: dict[str, float] = {}
    for profile in PROFILES:
        sp_tok = sys_prompt_token_counts[profile.lower()]
        for band in PROMPT_BANDS:
            total = prompt_token_counts[profile][str(band)]
            frac = round(sp_tok / total * 100.0, 2) if total > 0 else 0.0
            key = f"{profile.lower()}_{band}"
            shared_prefix_fractions[key] = frac
            print(f"  Prefix fraction {profile} {band}: {frac}%")

    # Initialize evidence payload
    payload: dict[str, Any] = {
        "milestone": "P5-TASK-4.6",
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
            "system_prompt_token_counts": sys_prompt_token_counts,
            "shared_prefix_fractions": shared_prefix_fractions,
        },
        "benchmark_policy": {
            "prefix_cache_settings": PREFIX_CACHE_SETTINGS,
            "profiles": PROFILES,
            "prompt_bands": PROMPT_BANDS,
            "sequential_calls_per_group": 3,
            "nat": NAT,
            "max_new_tokens_pa": MAX_NEW_TOKENS_PA,
            "max_new_tokens_ao": MAX_NEW_TOKENS_AO,
            "scheduler_cache_size": SCHEDULER_CACHE_GB,
            "gpu_enable_sdpa_optimization": True,
            "sparse_attention": "OFF (DEFERRED Task 4.3b)",
            "do_sample": False,
            "temperature": 0.0,
        },
        "prompt_token_counts": {
            f"{p}_{b}_{s}": tc
            for (p, b, s), (_, tc) in prompts.items()
        },
        "calibration": None,
        "pipeline_compile_ms": None,
        "results": [],
        "analysis": None,
        "quality_gate": None,
        "finished_utc": None,
    }

    # -----------------------------------------------------------------------
    # Crash-resilient resumption: load any completed groups from partial file
    # -----------------------------------------------------------------------
    resumed_results, completed_keys, resumed_calib, resumed_compile = (
        load_completed_from_partial()
    )

    # Partition resumed results into OFF/ON buckets
    resumed_off = [r for r in resumed_results if r["cache_setting"] == "OFF"]
    resumed_on = [r for r in resumed_results if r["cache_setting"] == "ON"]

    # Determine which pipeline phases still need work
    off_groups_needed = [
        (p, b) for p in PROFILES for b in PROMPT_BANDS
        if ("OFF", p, b) not in completed_keys
    ]
    on_groups_needed = [
        (p, b) for p in PROFILES for b in PROMPT_BANDS
        if ("ON", p, b) not in completed_keys
    ]

    pipeline_a_needed = len(off_groups_needed) > 0
    pipeline_b_needed = len(on_groups_needed) > 0

    if resumed_results:
        print(f"\n[RESUME] OFF groups remaining: {off_groups_needed}")
        print(f"[RESUME] ON groups remaining: {on_groups_needed}")

    compile_off_ms: float | None = None
    compile_on_ms: float | None = None

    # -----------------------------------------------------------------------
    # Pipeline A: prefix_cache = OFF (baseline)
    # -----------------------------------------------------------------------
    results_off: list[dict[str, Any]] = list(resumed_off)

    if pipeline_a_needed:
        print("\n" + "=" * 72)
        print("PHASE 1: Pipeline A — prefix_cache OFF (baseline)")
        print("=" * 72)

        pipeline_a, compile_off_ms, compile_off_err = create_pipeline(
            MODEL_14B, DRAFT_A_PATH, enable_prefix_caching=False, label="A",
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

        for profile, band in off_groups_needed:
            try:
                result = run_group(pipeline_a, tokenizer, prompts, "OFF", profile, band)
            except Exception as exc:  # noqa: BLE001
                print(f"\n  [CRASH] run_group OFF/{profile}/{band} failed: {exc}")
                result = {
                    "cache_setting": "OFF",
                    "profile": profile,
                    "band": band,
                    "status": "FAILED",
                    "calls": [],
                    "error": str(exc)[:300],
                }
            results_off.append(result)

            # Intermediate save after each group
            payload["results"] = results_off
            write_json_atomic(PARTIAL_JSON, payload)
            print(f"  Intermediate saved: {PARTIAL_JSON}")

            # Extra recovery time after 12K groups
            if band >= 12288:
                gc_mod.collect()
                time.sleep(3)
            else:
                gc_mod.collect()
                time.sleep(1)

        # Release Pipeline A
        print("\n[PIPELINE A] Releasing (del + gc.collect)...")
        del pipeline_a
        gc_mod.collect()
        time.sleep(3)
        print("  Pipeline A released.")
    else:
        print("\n[RESUME] All Pipeline A groups already completed — skipping.")
        if resumed_compile and resumed_compile.get("off") is not None:
            compile_off_ms = resumed_compile["off"]

    # Calibration check
    if resumed_calib is not None:
        calib = resumed_calib
        print(f"\n[RESUME] Using recovered calibration: {calib.get('status')}")
    else:
        calib = calibration_check(results_off)
    payload["calibration"] = calib

    # Save full Pipeline A results before proceeding to Pipeline B
    payload["results"] = results_off
    write_json_atomic(PARTIAL_JSON, payload)
    print(f"\n  Pipeline A results saved to {PARTIAL_JSON}")

    # -----------------------------------------------------------------------
    # Pipeline B: prefix_cache = ON (test condition)
    # -----------------------------------------------------------------------
    results_on: list[dict[str, Any]] = list(resumed_on)

    if pipeline_b_needed:
        print("\n" + "=" * 72)
        print("PHASE 2: Pipeline B — prefix_cache ON (test condition)")
        print("=" * 72)

        pipeline_b, compile_on_ms, compile_on_err = create_pipeline(
            MODEL_14B, DRAFT_A_PATH, enable_prefix_caching=True, label="B",
        )
        if pipeline_b is None:
            print(f"\n[WARNING] Pipeline B compilation failed: {compile_on_err}")
            print("  Proceeding with Pipeline A data only — SPEC_DECODE_INCOMPATIBLE")

            payload["pipeline_compile_ms"] = {"off": compile_off_ms, "on": None,
                                               "error_on": compile_on_err}
            payload["quality_gate"] = {
                "G-01": "N/A", "G-02": "N/A", "G-03": "N/A", "G-04": "N/A",
                "G-05": "N/A", "G-06": "N/A", "G-07": "N/A",
                "disposition": "SPEC_DECODE_INCOMPATIBLE",
                "pipeline_b_error": compile_on_err,
            }
            payload["finished_utc"] = now_iso()
            write_json_atomic(OUTPUT_JSON, payload)
            if PARTIAL_JSON.exists():
                PARTIAL_JSON.unlink()
            print(f"\nEvidence written to {OUTPUT_JSON}")
            return

        for profile, band in on_groups_needed:
            try:
                result = run_group(pipeline_b, tokenizer, prompts, "ON", profile, band)
            except Exception as exc:  # noqa: BLE001
                print(f"\n  [CRASH] run_group ON/{profile}/{band} failed: {exc}")
                result = {
                    "cache_setting": "ON",
                    "profile": profile,
                    "band": band,
                    "status": "FAILED",
                    "calls": [],
                    "error": str(exc)[:300],
                }
            results_on.append(result)

            # Intermediate save
            payload["results"] = results_off + results_on
            write_json_atomic(PARTIAL_JSON, payload)
            print(f"  Intermediate saved: {PARTIAL_JSON}")

            # Extra recovery time after 12K groups
            if band >= 12288:
                gc_mod.collect()
                time.sleep(3)
            else:
                gc_mod.collect()
                time.sleep(1)

        # Release Pipeline B
        print("\n[PIPELINE B] Releasing (del + gc.collect)...")
        del pipeline_b
        gc_mod.collect()
        time.sleep(3)
        print("  Pipeline B released.")
    else:
        print("\n[RESUME] All Pipeline B groups already completed — skipping.")
        if resumed_compile and resumed_compile.get("on") is not None:
            compile_on_ms = resumed_compile["on"]

    # -----------------------------------------------------------------------
    # PHASE 3: Analysis + Quality Gates
    # -----------------------------------------------------------------------
    print("\n" + "=" * 72)
    print("PHASE 3: Analysis + Quality Gates")
    print("=" * 72)

    payload["pipeline_compile_ms"] = {
        "off": compile_off_ms,
        "on": compile_on_ms,
        "delta_ms": round(compile_on_ms - compile_off_ms, 1)
        if compile_off_ms is not None and compile_on_ms is not None else None,
    }

    # Compute analysis
    analysis = compute_analysis(
        results_off, results_on, sys_prompt_token_counts, prompt_token_counts,
    )
    payload["analysis"] = analysis

    # Quality gates
    quality_gate = evaluate_quality_gates(results_off, results_on, analysis)
    payload["quality_gate"] = quality_gate

    # Finalize results (all groups, OFF then ON)
    payload["results"] = results_off + results_on

    # Print summary
    print(f"\n{'=' * 72}")
    print("RESULTS SUMMARY")
    print(f"{'=' * 72}")
    off_str = f"{compile_off_ms:.0f}ms" if compile_off_ms is not None else "resumed"
    on_str = f"{compile_on_ms:.0f}ms" if compile_on_ms is not None else "resumed"
    print(f"\nCompile times: OFF={off_str}  ON={on_str}")
    print(f"\nTTFT Comparison (G-03):")
    for key, comp in analysis["ttft_comparison"].items():
        if comp.get("verdict") == "MISSING_DATA":
            print(f"  {key}: MISSING_DATA")
            continue
        print(f"  {key}: OFF cold={comp['off_cold']:.0f}ms  ON cold={comp['on_cold']:.0f}ms  "
              f"ON warm1={comp['on_warm1']:.0f}ms  "
              f"ON reduction={comp['on_reduction_warm1_pct']:+.1f}%  "
              f"=> {comp['verdict']}")
    print(f"\nSpec-decode compatibility: {analysis['spec_decode_compatibility']}")
    print(f"AR interaction: {analysis['ar_interaction']}")
    print(f"RSS overhead at 12K: {analysis.get('rss_overhead_12k_mb')}MB")
    print(f"\nQuality Gates:")
    for k, v in quality_gate.items():
        print(f"  {k}: {v}")

    # Finalize
    payload["finished_utc"] = now_iso()
    write_json_atomic(OUTPUT_JSON, payload)

    if PARTIAL_JSON.exists():
        PARTIAL_JSON.unlink()
        print(f"\nPartial file removed: {PARTIAL_JSON}")

    print(f"\n{'=' * 72}")
    print(f"Evidence written to: {OUTPUT_JSON}")
    print(f"Disposition: {quality_gate['disposition']}")
    print(f"Finished: {payload['finished_utc']}")
    print(f"{'=' * 72}")


if __name__ == "__main__":
    main()
