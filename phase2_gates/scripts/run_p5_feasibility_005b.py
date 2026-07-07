"""
P5-FEASIBILITY-005b: Extended Context Window + Optimization Characterization
=============================================================================
Qwen3-14B + speculative decoding (Qwen3-0.6B draft) on Intel Arc 140V (Xe2).

Groups:
  A — Extended context baseline (14B solo + 14B+0.6B draft) to 20480 tokens
  B — XAttention isolation + XAttention+draft combination
  C — num_assistant_tokens sweep (3, 7, 10)
  D — Best config extended run (auto-selected from A-C results)

Parent: P5-005a (commit e6a64c4, disposition QWEN3_14B_WITH_SPEC_DECODING)
Branch: feature/p5-feasibility-005b-context-optimization
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
from collections import Counter
from pathlib import Path
from typing import Any, Callable, cast

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

# ---------------------------------------------------------------------------
# Evidence paths
# ---------------------------------------------------------------------------
EVIDENCE_DIR = ROOT / "phase2_gates" / "evidence"
OUTPUT_JSON = EVIDENCE_DIR / "p5_005b_context_optimization_matrix.json"
OUTPUT_SUMMARY_MD = EVIDENCE_DIR / "p5_005b_context_optimization_summary.md"

# ---------------------------------------------------------------------------
# Model paths (only models used in P5-005b)
# ---------------------------------------------------------------------------
MODEL_14B = ROOT / "models" / "qwen3-14b" / "openvino-int4-gpu"
DRAFT_06B_GPU = ROOT / "models" / "qwen3-0.6b" / "openvino-int4-gpu"

# ---------------------------------------------------------------------------
# Benchmark constants
# ---------------------------------------------------------------------------
WARMUP_RUNS: int = 2
MEASURED_RUNS: int = 5
MAX_NEW_TOKENS: int = 128
MEMORY_WARN_MB: float = 15_800.0  # Tighter than 005a — probing the ceiling
MEMORY_BUDGET_MB: float = 15_507.0


# ===================================================================
# Reused infrastructure (verbatim from run_p5_feasibility_005a.py)
# ===================================================================

def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def git_head() -> str:
    return subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True,
    ).strip()


def write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)
    tmp.replace(path)


def read_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    with open(path, "r", encoding="utf-8") as handle:
        data = json.load(handle)
    return data if isinstance(data, dict) else None


def normalize_error(prefix: str, text: str) -> str:
    normalized = "".join(ch if ch.isalnum() else "_" for ch in text.upper())
    normalized = "_".join(part for part in normalized.split("_") if part)
    return f"{prefix}_{normalized[:120]}"


def detect_power_envelope() -> dict[str, Any]:
    state: dict[str, Any] = {
        "sensor_available": False,
        "power_plugged": None,
        "battery_percent": None,
        "seconds_left": None,
    }
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
    state["seconds_left"] = int(battery.secsleft) if battery.secsleft is not None else None
    return state


def enforce_ac_power_or_fail_closed() -> dict[str, Any]:
    state = detect_power_envelope()
    if state.get("sensor_available") and state.get("power_plugged") is False:
        raise RuntimeError(
            "POWER_ENVELOPE_NOT_LOCKED: AC power required for P5-005b benchmark",
        )
    return state


def percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    xs = sorted(values)
    k = (len(xs) - 1) * (p / 100.0)
    f = math.floor(k)
    c = math.ceil(k)
    if f == c:
        return xs[int(k)]
    return xs[f] * (c - k) + xs[c] * (k - f)


def stats(values: list[float], valid_count: int, invalid_count: int) -> dict[str, float | int]:
    if not values:
        return {
            "mean": 0.0,
            "stddev": 0.0,
            "p50": 0.0,
            "p95": 0.0,
            "p99": 0.0,
            "min": 0.0,
            "max": 0.0,
            "valid_count": valid_count,
            "invalid_count": invalid_count,
        }
    return {
        "mean": statistics.fmean(values),
        "stddev": statistics.pstdev(values) if len(values) > 1 else 0.0,
        "p50": percentile(values, 50),
        "p95": percentile(values, 95),
        "p99": percentile(values, 99),
        "min": min(values),
        "max": max(values),
        "valid_count": valid_count,
        "invalid_count": invalid_count,
    }


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


def call_generate_with_optional_stream(
    pipeline: Any,
    prompt: str,
    generation_config: Any,
    stream_callback: Callable[[str], bool],
) -> Any:
    try:
        return pipeline.generate(prompt, generation_config, stream_callback)
    except TypeError:
        return pipeline.generate(prompt, generation_config)


def run_single_generation(
    pipeline: Any,
    tokenizer: Any,
    prompt: str,
    generation_config: Any,
) -> dict[str, Any]:
    proc = psutil.Process()
    rss_before = proc.memory_info().rss / (1024 * 1024)
    sampler = RssSampler()
    sampler.start()

    t0 = time.perf_counter()
    first_token_time: float | None = None

    def stream_cb(token_chunk: str) -> bool:
        nonlocal first_token_time
        if first_token_time is None and token_chunk:
            first_token_time = time.perf_counter()
        return False

    try:
        output = call_generate_with_optional_stream(
            pipeline=pipeline,
            prompt=prompt,
            generation_config=generation_config,
            stream_callback=stream_cb,
        )
        sampler.stop()
        t1 = time.perf_counter()
        rss_after = proc.memory_info().rss / (1024 * 1024)

        text = str(output)
        token_ids = tokenizer(text, return_tensors="np")["input_ids"][0]
        tokens_generated = int(len(token_ids))
        total_ms = (t1 - t0) * 1000.0
        ttft_ms = (
            ((first_token_time - t0) * 1000.0) if first_token_time is not None else total_ms
        )

        decode_ms = max(total_ms - ttft_ms, 1.0)
        tps = (tokens_generated / (decode_ms / 1000.0)) if decode_ms > 0 else 0.0

        return {
            "ok": True,
            "latency_first_token_ms": ttft_ms,
            "latency_total_ms": total_ms,
            "tokens_generated": tokens_generated,
            "decode_tokens_per_sec": tps,
            "rss_before_mb": rss_before,
            "rss_peak_mb": sampler.peak / (1024 * 1024),
            "rss_after_mb": rss_after,
            "error": None,
            "error_fingerprint": None,
        }
    except Exception as exc:  # noqa: BLE001
        sampler.stop()
        rss_after = proc.memory_info().rss / (1024 * 1024)
        msg = str(exc)
        return {
            "ok": False,
            "latency_first_token_ms": 0.0,
            "latency_total_ms": 0.0,
            "tokens_generated": 0,
            "decode_tokens_per_sec": 0.0,
            "rss_before_mb": rss_before,
            "rss_peak_mb": sampler.peak / (1024 * 1024),
            "rss_after_mb": rss_after,
            "error": msg,
            "error_fingerprint": normalize_error("GENERATION_ERROR", msg),
        }


def summarize_runs(runs: list[dict[str, Any]]) -> dict[str, Any]:
    ok = [row for row in runs if row.get("ok")]
    fail = [row for row in runs if not row.get("ok")]
    return {
        "valid_count": len(ok),
        "invalid_count": len(fail),
        "ttft_ms": stats(
            [float(row["latency_first_token_ms"]) for row in ok], len(ok), len(fail),
        ),
        "latency_total_ms": stats(
            [float(row["latency_total_ms"]) for row in ok], len(ok), len(fail),
        ),
        "decode_tokens_per_sec": stats(
            [float(row["decode_tokens_per_sec"]) for row in ok], len(ok), len(fail),
        ),
        "rss_peak_mb": stats(
            [float(row["rss_peak_mb"]) for row in runs], len(runs), 0,
        ),
        "fingerprint_distribution": dict(
            Counter(
                row["error_fingerprint"]
                for row in fail
                if row.get("error_fingerprint")
            ),
        ),
    }


def path_has_model(path: Path) -> bool:
    return (
        path.exists()
        and (path / "openvino_model.xml").exists()
        and (path / "openvino_model.bin").exists()
    )


def model_paths_ok() -> dict[str, Any]:
    checks: dict[str, Any] = {}
    for name, path in {
        "qwen3-14b": MODEL_14B,
        "qwen3-0.6b-gpu": DRAFT_06B_GPU,
    }.items():
        checks[name] = {
            "path": str(path),
            "dir_exists": path.exists(),
            "xml_exists": (path / "openvino_model.xml").exists(),
            "bin_exists": (path / "openvino_model.bin").exists(),
        }
    return checks


def available_devices() -> list[str]:
    if ov is None:
        return []
    try:
        core = ov.Core()
        return list(core.available_devices)
    except Exception:
        return []


def supported_gpu_properties() -> list[str]:
    if ov is None:
        return []
    try:
        core = ov.Core()
        return list(core.get_property("GPU", "SUPPORTED_PROPERTIES"))
    except Exception:
        return []


def build_user_content_to_token_len(
    tokenizer: Any, target_tokens: int, seed: str,
) -> str:
    chunk = (
        " local privacy deterministic benchmark payload "
        "context window feasibility matrix repeated segment "
    )
    text = seed
    for _ in range(200_000):
        toks = tokenizer(text, return_tensors="np")["input_ids"][0]
        if len(toks) >= target_tokens:
            break
        text += chunk
    toks = tokenizer(text, return_tensors="np")["input_ids"][0]
    if len(toks) > target_tokens:
        text = tokenizer.decode(toks[:target_tokens], skip_special_tokens=True)
    return text


def build_chat_prompt(
    tokenizer: Any, user_content: str, system_prompt: str,
) -> str:
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_content},
    ]
    return tokenizer.apply_chat_template(
        messages, tokenize=False, add_generation_prompt=True,
    )


def create_pipeline(
    model_dir: Path,
    pipeline_kwargs: dict[str, Any] | None,
    runtime_properties: dict[str, Any] | None,
    draft_model_path: Path | None,
    draft_device: str | None,
) -> tuple[Any | None, float | None, dict[str, Any] | None]:
    t0 = time.perf_counter()
    try:
        kwargs: dict[str, Any] = {}
        if runtime_properties:
            kwargs.update(runtime_properties)

        config: dict[str, Any] = {}
        if pipeline_kwargs:
            config.update(pipeline_kwargs)

        if draft_model_path is not None:
            if not path_has_model(draft_model_path):
                raise RuntimeError(f"DRAFT_MODEL_NOT_FOUND: {draft_model_path}")
            if not hasattr(ov_genai, "draft_model"):
                raise RuntimeError("DRAFT_MODEL_API_NOT_AVAILABLE")
            config["draft_model"] = ov_genai.draft_model(
                str(draft_model_path), draft_device or "GPU",
            )

        pipe = ov_genai.LLMPipeline(str(model_dir), "GPU", config, **kwargs)
        compile_ms = (time.perf_counter() - t0) * 1000.0
        return pipe, compile_ms, None
    except Exception as exc:  # noqa: BLE001
        return None, None, {
            "message": str(exc),
            "fingerprint": normalize_error("PIPELINE_CREATION_ERROR", str(exc)),
        }


# ===================================================================
# P5-005b specific: generation config with tunable NAT
# ===================================================================

def make_generation_config(
    assisted: bool = False,
    num_assistant_tokens: int = 5,
    assistant_confidence_threshold: float = 0.0,
) -> Any:
    """Build GenerationConfig with parameterised speculation depth."""
    config = ov_genai.GenerationConfig()
    config.max_new_tokens = MAX_NEW_TOKENS
    config.do_sample = False
    try:
        config.temperature = 0.0
        config.top_k = 1
        config.top_p = 1.0
    except Exception:
        pass

    if assisted:
        try:
            config.num_assistant_tokens = num_assistant_tokens
            config.assistant_confidence_threshold = assistant_confidence_threshold
        except Exception:
            pass

    return config


# ===================================================================
# P5-005b test specifications
# ===================================================================

def test_specifications() -> list[dict[str, Any]]:
    """Return the 8-test P5-005b matrix (Groups A-D).

    Group D (D-01) is included with placeholder bands; its configuration
    is finalised at runtime by ``select_best_config_for_d01()``.
    """
    return [
        # ---- Group A: Extended Context Baseline ----
        {
            "id": "A-01",
            "name": "14B Baseline Extended",
            "group": "A",
            "model_path": MODEL_14B,
            "draft_model_path": None,
            "draft_device": None,
            "runtime_properties": {},
            "pipeline_kwargs": {},
            "num_assistant_tokens": None,
            "assistant_confidence_threshold": None,
            "is_speculative": False,
            "bands": [4096, 6144, 8192, 12288, 16384, 20480],
        },
        {
            "id": "A-02",
            "name": "14B + 0.6B Draft Extended",
            "group": "A",
            "model_path": MODEL_14B,
            "draft_model_path": DRAFT_06B_GPU,
            "draft_device": "GPU",
            "runtime_properties": {},
            "pipeline_kwargs": {},
            "num_assistant_tokens": 5,
            "assistant_confidence_threshold": 0.0,
            "is_speculative": True,
            "bands": [4096, 6144, 8192, 12288, 16384, 20480],
        },
        # ---- Group B: Missing Optimization Combinations ----
        {
            "id": "B-01",
            "name": "14B + XAttention Only",
            "group": "B",
            "model_path": MODEL_14B,
            "draft_model_path": None,
            "draft_device": None,
            "runtime_properties": {"GPU_ENABLE_SDPA_OPTIMIZATION": True},
            "pipeline_kwargs": {},
            "num_assistant_tokens": None,
            "assistant_confidence_threshold": None,
            "is_speculative": False,
            "bands": [512, 2048, 4096, 8192],
        },
        {
            "id": "B-02",
            "name": "14B + 0.6B Draft + XAttention",
            "group": "B",
            "model_path": MODEL_14B,
            "draft_model_path": DRAFT_06B_GPU,
            "draft_device": "GPU",
            "runtime_properties": {"GPU_ENABLE_SDPA_OPTIMIZATION": True},
            "pipeline_kwargs": {},
            "num_assistant_tokens": 5,
            "assistant_confidence_threshold": 0.0,
            "is_speculative": True,
            "bands": [512, 2048, 4096, 8192],
        },
        # ---- Group C: Speculation Depth Tuning ----
        {
            "id": "C-01",
            "name": "14B + 0.6B Draft (NAT=3)",
            "group": "C",
            "model_path": MODEL_14B,
            "draft_model_path": DRAFT_06B_GPU,
            "draft_device": "GPU",
            "runtime_properties": {},
            "pipeline_kwargs": {},
            "num_assistant_tokens": 3,
            "assistant_confidence_threshold": 0.0,
            "is_speculative": True,
            "bands": [512, 4096, 8192],
        },
        {
            "id": "C-02",
            "name": "14B + 0.6B Draft (NAT=7)",
            "group": "C",
            "model_path": MODEL_14B,
            "draft_model_path": DRAFT_06B_GPU,
            "draft_device": "GPU",
            "runtime_properties": {},
            "pipeline_kwargs": {},
            "num_assistant_tokens": 7,
            "assistant_confidence_threshold": 0.0,
            "is_speculative": True,
            "bands": [512, 4096, 8192],
        },
        {
            "id": "C-03",
            "name": "14B + 0.6B Draft (NAT=10)",
            "group": "C",
            "model_path": MODEL_14B,
            "draft_model_path": DRAFT_06B_GPU,
            "draft_device": "GPU",
            "runtime_properties": {},
            "pipeline_kwargs": {},
            "num_assistant_tokens": 10,
            "assistant_confidence_threshold": 0.0,
            "is_speculative": True,
            "bands": [512, 4096, 8192],
        },
        # ---- Group D: Best Config Extended (configured at runtime) ----
        {
            "id": "D-01",
            "name": "Best Config Extended",
            "group": "D",
            "model_path": MODEL_14B,
            "draft_model_path": DRAFT_06B_GPU,
            "draft_device": "GPU",
            "runtime_properties": {},  # overwritten at runtime
            "pipeline_kwargs": {},
            "num_assistant_tokens": 5,  # overwritten at runtime
            "assistant_confidence_threshold": 0.0,
            "is_speculative": True,
            "bands": [4096, 8192, 12288, 16384, 20480],
        },
    ]


# ===================================================================
# Group D selection logic
# ===================================================================

def _extract_mean_tps_at_band(
    tests: list[dict[str, Any]], test_id: str, band: int,
) -> float:
    """Return mean decode TPS for *test_id* at *band*, or 0.0 if missing."""
    for test in tests:
        if test.get("id") != test_id or test.get("status") != "completed":
            continue
        for point in test.get("points", []):
            if int(point.get("prompt_length_user_tokens_target", -1)) == band:
                return float(
                    point.get("summary", {})
                    .get("decode_tokens_per_sec", {})
                    .get("mean", 0.0),
                )
    return 0.0


def select_best_config_for_d01(
    completed_tests: list[dict[str, Any]],
) -> dict[str, Any]:
    """Determine winning config from Groups A-C for D-01.

    Returns dict with keys: runtime_properties, num_assistant_tokens,
    assistant_confidence_threshold, rationale (str).
    """
    # A-02 is the reference baseline (NAT=5, no XAttention)
    a02_tps = _extract_mean_tps_at_band(completed_tests, "A-02", 4096)
    b02_tps = _extract_mean_tps_at_band(completed_tests, "B-02", 4096)

    # Determine best runtime properties
    use_xattention = b02_tps > a02_tps and b02_tps > 0.0
    best_runtime_props: dict[str, Any] = (
        {"GPU_ENABLE_SDPA_OPTIMIZATION": True} if use_xattention else {}
    )

    # Determine best num_assistant_tokens from Group C at band 4096
    nat_candidates: list[tuple[int, float]] = []
    for test_id, nat_val in [("C-01", 3), ("C-02", 7), ("C-03", 10)]:
        tps = _extract_mean_tps_at_band(completed_tests, test_id, 4096)
        if tps > 0.0:
            nat_candidates.append((nat_val, tps))

    # Also include NAT=5 from A-02 (or B-02 if XAttention won)
    reference_nat5_tps = b02_tps if use_xattention else a02_tps
    if reference_nat5_tps > 0.0:
        nat_candidates.append((5, reference_nat5_tps))

    best_nat = 5  # default
    best_nat_tps = 0.0
    for nat_val, tps in nat_candidates:
        if tps > best_nat_tps:
            best_nat = nat_val
            best_nat_tps = tps

    parts: list[str] = []
    parts.append(
        f"XAttention={'ON' if use_xattention else 'OFF'} "
        f"(B-02={b02_tps:.2f} vs A-02={a02_tps:.2f} tps @4096)",
    )
    parts.append(
        f"NAT={best_nat} selected (best {best_nat_tps:.2f} tps @4096 from "
        + ", ".join(f"NAT={n}={t:.2f}" for n, t in sorted(nat_candidates))
        + ")",
    )

    return {
        "runtime_properties": best_runtime_props,
        "num_assistant_tokens": best_nat,
        "assistant_confidence_threshold": 0.0,
        "rationale": "; ".join(parts),
    }


# ===================================================================
# Test execution (OOM-safe band iteration)
# ===================================================================

def run_test(
    test: dict[str, Any],
    matrix: dict[str, Any],
) -> dict[str, Any]:
    """Execute a single test across all its bands with OOM-safe iteration."""
    model_path = Path(test["model_path"])
    tokenizer = AutoTokenizer.from_pretrained(str(model_path), local_files_only=True)

    system_prompt = (
        "You are BlarAI in an offline local-only environment. Answer deterministically."
    )

    pipe, compile_ms, creation_error = create_pipeline(
        model_dir=model_path,
        pipeline_kwargs=dict(test.get("pipeline_kwargs", {})),
        runtime_properties=dict(test.get("runtime_properties", {})),
        draft_model_path=(
            Path(test["draft_model_path"]) if test.get("draft_model_path") is not None else None
        ),
        draft_device=cast(str | None, test.get("draft_device")),
    )

    result: dict[str, Any] = {
        "id": test["id"],
        "name": test["name"],
        "group": test.get("group"),
        "is_speculative": bool(test.get("is_speculative")),
        "model_path": str(model_path),
        "runtime_properties": test.get("runtime_properties", {}),
        "pipeline_kwargs": test.get("pipeline_kwargs", {}),
        "draft_model_path": (
            str(test["draft_model_path"]) if test.get("draft_model_path") else None
        ),
        "draft_device": test.get("draft_device"),
        "num_assistant_tokens": test.get("num_assistant_tokens"),
        "assistant_confidence_threshold": test.get("assistant_confidence_threshold"),
        "pipeline_creation_ok": pipe is not None,
        "pipeline_compile_ms": compile_ms,
        "pipeline_creation_error": creation_error,
        "status": "completed" if pipe is not None else "pipeline_creation_error",
        "points": [],
    }

    if pipe is None:
        return result

    bands: list[int] = list(test.get("bands", []))
    is_speculative = bool(test.get("is_speculative"))
    nat = int(test.get("num_assistant_tokens") or 5)
    act = float(test.get("assistant_confidence_threshold") or 0.0)

    gen_cfg = make_generation_config(
        assisted=is_speculative,
        num_assistant_tokens=nat,
        assistant_confidence_threshold=act,
    )

    any_band_succeeded = False

    for band in bands:
        print(f"  [{test['id']}] Band {band} ...", flush=True)

        try:
            user_content = build_user_content_to_token_len(
                tokenizer,
                band,
                seed=f"P5-FEASIBILITY-005b {test['id']} prompt band {band}.",
            )
            user_tokens = int(
                len(tokenizer(user_content, return_tensors="np")["input_ids"][0]),
            )
            prompt = build_chat_prompt(tokenizer, user_content, system_prompt)
            formatted_tokens = int(
                len(tokenizer(prompt, return_tensors="np")["input_ids"][0]),
            )

            # Warmup
            for _ in range(WARMUP_RUNS):
                _ = run_single_generation(pipe, tokenizer, prompt, gen_cfg)

            # Measured runs
            measured = [
                run_single_generation(pipe, tokenizer, prompt, gen_cfg)
                for _ in range(MEASURED_RUNS)
            ]

            summary = summarize_runs(measured)

            point: dict[str, Any] = {
                "prompt_length_user_tokens_target": band,
                "prompt_length_user_tokens_actual": user_tokens,
                "formatted_prompt_tokens": formatted_tokens,
                "runs": measured,
                "summary": summary,
                "status": "ok",
                "error_fingerprint": None,
            }

            # Memory warning (record but do NOT abort)
            peak_rss = float(summary.get("rss_peak_mb", {}).get("max", 0.0))
            if peak_rss > MEMORY_WARN_MB:
                point["memory_warning"] = (
                    f"RSS {peak_rss:.0f} MB > MEMORY_WARN_MB {MEMORY_WARN_MB:.0f} MB"
                )
                print(f"    WARNING: {point['memory_warning']}", flush=True)

            any_band_succeeded = True
            tps_mean = float(
                summary.get("decode_tokens_per_sec", {}).get("mean", 0.0),
            )
            print(
                f"    Band {band}: {tps_mean:.2f} tps, "
                f"TTFT {float(summary.get('ttft_ms', {}).get('mean', 0.0)):.0f}ms, "
                f"RSS peak {peak_rss:.0f} MB",
                flush=True,
            )

        except Exception as exc:  # noqa: BLE001
            # OOM or other band-level failure
            proc = psutil.Process()
            rss_at_fail = proc.memory_info().rss / (1024 * 1024)
            err_msg = str(exc)
            fp = normalize_error("BAND_OOM_OR_ERROR", err_msg)
            point = {
                "prompt_length_user_tokens_target": band,
                "prompt_length_user_tokens_actual": None,
                "formatted_prompt_tokens": None,
                "runs": [],
                "summary": {},
                "status": "oom_or_error",
                "error_fingerprint": fp,
                "error_message": err_msg[:500],
                "rss_at_failure_mb": rss_at_fail,
            }
            print(
                f"    Band {band} FAILED: {err_msg[:200]} (RSS {rss_at_fail:.0f} MB)",
                flush=True,
            )

        result["points"].append(point)

    # Final status: completed if any band succeeded
    if any_band_succeeded:
        result["status"] = "completed"
    elif result["status"] != "pipeline_creation_error":
        result["status"] = "all_bands_failed"

    # Cleanup
    pipe = None  # type: ignore[assignment]
    gc.collect()
    time.sleep(2)

    return result


# ===================================================================
# Quality gate evaluation (P5-005b specific)
# ===================================================================

def evaluate_quality_gate(matrix: dict[str, Any]) -> dict[str, Any]:
    """Evaluate P5-005b-specific quality gates G-01 through G-05."""
    tests = matrix.get("tests", [])

    def get_test(tid: str) -> dict[str, Any] | None:
        for t in tests:
            if t.get("id") == tid:
                return t
        return None

    def count_valid_bands_above(test: dict[str, Any] | None, threshold: int) -> int:
        """Count bands > threshold with status='ok'."""
        if test is None:
            return 0
        count = 0
        for point in test.get("points", []):
            band = int(point.get("prompt_length_user_tokens_target", 0))
            if band > threshold and point.get("status") == "ok":
                count += 1
        return count

    def count_valid_bands(test: dict[str, Any] | None) -> int:
        if test is None:
            return 0
        return sum(
            1 for p in test.get("points", []) if p.get("status") == "ok"
        )

    def any_band_failed(test: dict[str, Any] | None) -> bool:
        if test is None:
            return False
        return any(
            p.get("status") == "oom_or_error" for p in test.get("points", [])
        )

    def peak_rss_at_highest_ok_band(test: dict[str, Any] | None) -> float:
        """Return peak RSS at the highest successful band, or 0.0."""
        if test is None:
            return 0.0
        best_band = -1
        best_rss = 0.0
        for point in test.get("points", []):
            if point.get("status") != "ok":
                continue
            band = int(point.get("prompt_length_user_tokens_target", 0))
            if band > best_band:
                best_band = band
                best_rss = float(
                    point.get("summary", {}).get("rss_peak_mb", {}).get("max", 0.0),
                )
        return best_rss

    def best_config_tps_at_band(band: int) -> float:
        """Return best TPS at *band* across D-01, A-02."""
        best = 0.0
        for tid in ["D-01", "A-02"]:
            tps = _extract_mean_tps_at_band(tests, tid, band)
            if tps > best:
                best = tps
        return best

    # --- G-01: A-02 completed with >=3 valid bands above 4096
    a02 = get_test("A-02")
    a02_valid_above_4k = count_valid_bands_above(a02, 4096)
    g01 = a02_valid_above_4k >= 3
    g01_detail = (
        f"A-02 has {a02_valid_above_4k} valid bands above 4096 (need >=3)"
    )

    # --- G-02: D-01 completed with >=3 valid bands
    d01 = get_test("D-01")
    d01_valid = count_valid_bands(d01)
    g02 = d01_valid >= 3
    g02_detail = f"D-01 has {d01_valid} valid bands (need >=3)"

    # --- G-03: OOM boundary identified OR all bands through 20480 passed
    a01 = get_test("A-01")
    oom_found = any_band_failed(a01) or any_band_failed(a02) or any_band_failed(d01)
    all_pass_20k = (
        count_valid_bands(a02) == len((a02 or {}).get("points", []))
        and count_valid_bands(d01) == len((d01 or {}).get("points", []))
    )
    g03 = oom_found or all_pass_20k
    if oom_found:
        g03_detail = "OOM boundary identified (at least one band failed)"
    elif all_pass_20k:
        g03_detail = "All bands through 20480 passed — ceiling not reached"
    else:
        g03_detail = "Neither OOM nor full pass — inconclusive"

    # --- G-04: Peak RSS at highest successful band <= 15,507 MB
    # Check D-01 first, fall back to A-02
    rss_check_test = d01 if d01 and d01.get("status") == "completed" else a02
    peak_rss = peak_rss_at_highest_ok_band(rss_check_test)
    g04 = peak_rss <= MEMORY_BUDGET_MB
    g04_detail = (
        f"Peak RSS {peak_rss:.0f} MB at highest band "
        f"({'<=' if g04 else '>'} {MEMORY_BUDGET_MB:.0f} MB budget)"
    )

    # --- G-05: Best config TPS at band 8192 >= 5.0
    tps_8192 = best_config_tps_at_band(8192)
    g05 = tps_8192 >= 5.0
    g05_detail = f"Best config TPS at 8192 = {tps_8192:.2f} (need >=5.0)"

    # --- Disposition ---
    all_pass = g01 and g02 and g03 and g04 and g05
    if all_pass:
        disposition = "CONTEXT_EXPANSION_FEASIBLE"
    elif g01 and g05:
        disposition = "CONTEXT_EXPANSION_PARTIAL"
    elif g01:
        disposition = "CONTEXT_EXPANSION_MARGINAL"
    else:
        disposition = "INSUFFICIENT_EVIDENCE"

    # --- Identify OOM boundary ---
    oom_boundary: dict[str, Any] = {"identified": False}
    for tid in ["A-02", "D-01", "A-01"]:
        t = get_test(tid)
        if t is None:
            continue
        ok_bands: list[int] = []
        fail_bands: list[int] = []
        for p in t.get("points", []):
            band = int(p.get("prompt_length_user_tokens_target", 0))
            if p.get("status") == "ok":
                ok_bands.append(band)
            else:
                fail_bands.append(band)
        if fail_bands:
            oom_boundary = {
                "identified": True,
                "test_id": tid,
                "last_successful_band": max(ok_bands) if ok_bands else None,
                "first_failing_band": min(fail_bands),
            }
            break

    # --- Best configuration tuple ---
    d01_selection = matrix.get("d01_selection_rationale", {})
    best_config_tuple: dict[str, Any] = {
        "xattention": bool(
            d01_selection.get("runtime_properties", {}).get("GPU_ENABLE_SDPA_OPTIMIZATION"),
        ),
        "num_assistant_tokens": d01_selection.get("num_assistant_tokens", 5),
        "max_safe_context_band": (
            oom_boundary.get("last_successful_band")
            if oom_boundary.get("identified")
            else 20480
        ),
    }

    return {
        "checks": {
            "G-01": {"passed": g01, "detail": g01_detail},
            "G-02": {"passed": g02, "detail": g02_detail},
            "G-03": {"passed": g03, "detail": g03_detail},
            "G-04": {"passed": g04, "detail": g04_detail},
            "G-05": {"passed": g05, "detail": g05_detail},
        },
        "disposition": disposition,
        "oom_boundary": oom_boundary,
        "best_config_tuple": best_config_tuple,
    }


# ===================================================================
# Markdown summary writer
# ===================================================================

def write_markdown_summary(path: Path, matrix: dict[str, Any]) -> None:
    """Generate the P5-005b summary markdown."""
    tests = cast(list[dict[str, Any]], matrix.get("tests", []))
    completed = [t for t in tests if t.get("status") == "completed"]
    qg = matrix.get("quality_gate", {})

    lines: list[str] = []

    # Header
    lines.append("# P5-005b Context Window + Optimization Characterization Summary")
    lines.append("")
    lines.append("## Outcome")
    lines.append("")
    lines.append(f"- Finished UTC: `{matrix.get('finished_utc', 'unknown')}`")
    lines.append(f"- Disposition: `{qg.get('disposition', 'unknown')}`")
    lines.append(f"- Total tests: `{len(tests)}`")
    lines.append(f"- Completed: `{len(completed)}`")
    lines.append("")

    # TPS Degradation Table
    lines.append("## TPS Degradation Table")
    lines.append("")
    all_bands: set[int] = set()
    for t in completed:
        for p in t.get("points", []):
            if p.get("status") == "ok":
                all_bands.add(int(p.get("prompt_length_user_tokens_target", 0)))
    sorted_bands = sorted(all_bands)

    if sorted_bands:
        header = "| Test | " + " | ".join(str(b) for b in sorted_bands) + " |"
        sep = "| --- | " + " | ".join("---" for _ in sorted_bands) + " |"
        lines.append(header)
        lines.append(sep)

        for t in completed:
            row_parts: list[str] = [f"{t.get('id')} {t.get('name', '')}"]
            for b in sorted_bands:
                cell = "—"
                for p in t.get("points", []):
                    if int(p.get("prompt_length_user_tokens_target", -1)) == b:
                        if p.get("status") == "ok":
                            tps = float(
                                p.get("summary", {})
                                .get("decode_tokens_per_sec", {})
                                .get("mean", 0.0),
                            )
                            ttft = float(
                                p.get("summary", {}).get("ttft_ms", {}).get("mean", 0.0),
                            )
                            rss = float(
                                p.get("summary", {})
                                .get("rss_peak_mb", {})
                                .get("max", 0.0),
                            )
                            cell = f"{tps:.1f} tps / {ttft:.0f}ms / {rss:.0f}MB"
                        elif p.get("status") == "oom_or_error":
                            cell = "OOM/ERR"
                        break
                row_parts.append(cell)
            lines.append("| " + " | ".join(row_parts) + " |")
    lines.append("")

    # OOM Boundary
    lines.append("## OOM Boundary Identification")
    lines.append("")
    oom = qg.get("oom_boundary", {})
    if oom.get("identified"):
        lines.append(
            f"- Test: `{oom.get('test_id')}`"
        )
        lines.append(
            f"- Last successful band: `{oom.get('last_successful_band')}`"
        )
        lines.append(
            f"- First failing band: `{oom.get('first_failing_band')}`"
        )
    else:
        lines.append("- No OOM boundary reached — all bands through 20480 passed.")
    lines.append("")

    # Group D Selection Rationale
    lines.append("## Group D Selection Rationale")
    lines.append("")
    d01_sel = matrix.get("d01_selection_rationale", {})
    lines.append(f"- Rationale: {d01_sel.get('rationale', 'N/A')}")
    lines.append(
        f"- XAttention: `{bool(d01_sel.get('runtime_properties', {}).get('GPU_ENABLE_SDPA_OPTIMIZATION'))}`"
    )
    lines.append(f"- num_assistant_tokens: `{d01_sel.get('num_assistant_tokens', 'N/A')}`")
    lines.append("")

    # Best Configuration Tuple
    lines.append("## Best Configuration")
    lines.append("")
    bct = qg.get("best_config_tuple", {})
    lines.append(f"- XAttention: `{bct.get('xattention')}`")
    lines.append(f"- num_assistant_tokens: `{bct.get('num_assistant_tokens')}`")
    lines.append(f"- Max safe context band: `{bct.get('max_safe_context_band')}`")
    lines.append("")

    # Memory Growth Curve
    lines.append("## Memory Growth Curve (RSS peak MB)")
    lines.append("")
    for tid in ["A-02", "D-01"]:
        t_data = None
        for t in tests:
            if t.get("id") == tid:
                t_data = t
                break
        if t_data is None:
            continue
        lines.append(f"### {tid}: {t_data.get('name', '')}")
        lines.append("")
        lines.append("| Band | RSS Peak (MB) | Status |")
        lines.append("| --- | --- | --- |")
        for p in t_data.get("points", []):
            band = int(p.get("prompt_length_user_tokens_target", 0))
            status = p.get("status", "unknown")
            if status == "ok":
                rss = float(
                    p.get("summary", {}).get("rss_peak_mb", {}).get("max", 0.0),
                )
                lines.append(f"| {band} | {rss:.0f} | ok |")
            else:
                rss_fail = p.get("rss_at_failure_mb", "N/A")
                lines.append(f"| {band} | {rss_fail} | {status} |")
        lines.append("")

    # Quality Gate Matrix
    lines.append("## Quality Gate Pass/Fail Matrix")
    lines.append("")
    checks = qg.get("checks", {})
    if checks:
        lines.append("| Gate | Pass/Fail | Detail |")
        lines.append("| --- | --- | --- |")
        for gid, payload in sorted(checks.items()):
            passed = "PASS" if payload.get("passed") else "FAIL"
            detail = payload.get("detail", "")
            lines.append(f"| {gid} | {passed} | {detail} |")
    lines.append("")

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


# ===================================================================
# Main
# ===================================================================

def main() -> None:
    print("=" * 70)
    print("P5-FEASIBILITY-005b: Context Window + Optimization Characterization")
    print("=" * 70)
    print(flush=True)

    power_state = enforce_ac_power_or_fail_closed()
    print(f"AC power: plugged={power_state.get('power_plugged')}", flush=True)

    env: dict[str, Any] = {
        "timestamp_utc": now_iso(),
        "commit_hash": git_head(),
        "python_version": sys.version,
        "platform": platform.platform(),
        "openvino_version": (
            getattr(ov, "__version__", "unknown") if ov is not None else "unavailable"
        ),
        "openvino_genai_version": getattr(ov_genai, "__version__", "unknown"),
        "available_devices": available_devices(),
        "power_envelope": power_state,
        "memory_limits": {
            "warning_rss_mb": MEMORY_WARN_MB,
            "budget_rss_mb": MEMORY_BUDGET_MB,
        },
        "model_checks": model_paths_ok(),
    }

    # Validate models exist
    for name, check in env["model_checks"].items():
        if not check.get("bin_exists"):
            raise RuntimeError(f"REQUIRED_MODEL_MISSING: {name} at {check.get('path')}")

    matrix: dict[str, Any] = {
        "milestone": "P5-FEASIBILITY-005b",
        "timestamp_utc": now_iso(),
        "metadata": env,
        "prior_art_reference": {
            "parent_milestone": "P5-FEASIBILITY-005a",
            "parent_commit": "e6a64c4",
            "parent_disposition": "QWEN3_14B_WITH_SPEC_DECODING",
            "parent_evidence": "phase2_gates/evidence/p5_005a_unified_draft_feasibility_matrix.json",
        },
        "benchmark_policy": {
            "runs_per_point_measured": MEASURED_RUNS,
            "warmup_runs_discarded": WARMUP_RUNS,
            "max_new_tokens": MAX_NEW_TOKENS,
            "temperature": 0.0,
            "device": "GPU (Intel Arc 140V)",
            "memory_warn_mb": MEMORY_WARN_MB,
            "memory_budget_mb": MEMORY_BUDGET_MB,
            "ordered_execution": [],
        },
        "tests": [],
        "d01_selection_rationale": {},
        "quality_gate": {},
    }

    all_tests = test_specifications()
    matrix["benchmark_policy"]["ordered_execution"] = [t["id"] for t in all_tests]

    # Partition: Groups A-C execute first, then D-01 is configured and executed
    groups_abc = [t for t in all_tests if t["group"] in ("A", "B", "C")]
    groups_d = [t for t in all_tests if t["group"] == "D"]

    write_json_atomic(OUTPUT_JSON, matrix)

    # ---- Execute Groups A, B, C ----
    for test in groups_abc:
        print(f"\n{'='*60}", flush=True)
        print(f"Test {test['id']}: {test['name']} (Group {test['group']})", flush=True)
        print(f"  Bands: {test['bands']}", flush=True)
        print(f"  Speculative: {test['is_speculative']}", flush=True)
        if test["is_speculative"]:
            print(f"  NAT: {test['num_assistant_tokens']}", flush=True)
        print(f"  Runtime props: {test['runtime_properties']}", flush=True)
        print(f"{'='*60}", flush=True)

        result = run_test(test, matrix)
        matrix["tests"].append(result)
        write_json_atomic(OUTPUT_JSON, matrix)

        print(f"  => Status: {result['status']}", flush=True)

    # ---- Select best config for D-01 ----
    print(f"\n{'='*60}", flush=True)
    print("Selecting best config for D-01 from Groups A-C results ...", flush=True)
    print(f"{'='*60}", flush=True)

    d01_config = select_best_config_for_d01(matrix["tests"])
    matrix["d01_selection_rationale"] = d01_config
    print(f"  Rationale: {d01_config['rationale']}", flush=True)
    print(f"  runtime_properties: {d01_config['runtime_properties']}", flush=True)
    print(f"  num_assistant_tokens: {d01_config['num_assistant_tokens']}", flush=True)

    write_json_atomic(OUTPUT_JSON, matrix)

    # ---- Execute Group D ----
    for test in groups_d:
        # Apply the selected configuration
        test["runtime_properties"] = d01_config["runtime_properties"]
        test["num_assistant_tokens"] = d01_config["num_assistant_tokens"]
        test["assistant_confidence_threshold"] = d01_config["assistant_confidence_threshold"]

        print(f"\n{'='*60}", flush=True)
        print(
            f"Test {test['id']}: {test['name']} (Group {test['group']}) "
            f"[SELECTED CONFIG]",
            flush=True,
        )
        print(f"  Bands: {test['bands']}", flush=True)
        print(f"  NAT: {test['num_assistant_tokens']}", flush=True)
        print(f"  Runtime props: {test['runtime_properties']}", flush=True)
        print(f"{'='*60}", flush=True)

        result = run_test(test, matrix)
        matrix["tests"].append(result)
        write_json_atomic(OUTPUT_JSON, matrix)

        print(f"  => Status: {result['status']}", flush=True)

    # ---- Evaluate quality gates ----
    matrix["quality_gate"] = evaluate_quality_gate(matrix)
    matrix["finished_utc"] = now_iso()
    write_json_atomic(OUTPUT_JSON, matrix)
    write_markdown_summary(OUTPUT_SUMMARY_MD, matrix)

    # ---- Final output ----
    qg = matrix["quality_gate"]
    print(f"\n{'='*70}", flush=True)
    print("P5-005b COMPLETE", flush=True)
    print(f"{'='*70}", flush=True)
    print(
        json.dumps(
            {
                "status": "ok",
                "artifact": str(OUTPUT_JSON),
                "summary": str(OUTPUT_SUMMARY_MD),
                "disposition": qg.get("disposition"),
                "oom_boundary": qg.get("oom_boundary"),
                "best_config_tuple": qg.get("best_config_tuple"),
                "quality_gates": {
                    k: v.get("passed") for k, v in qg.get("checks", {}).items()
                },
            },
            indent=2,
        ),
    )


if __name__ == "__main__":
    main()
