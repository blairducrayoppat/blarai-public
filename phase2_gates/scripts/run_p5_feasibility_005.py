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

EVIDENCE_DIR = ROOT / "phase2_gates" / "evidence"
OUTPUT_JSON = EVIDENCE_DIR / "p5_unified_model_feasibility_matrix.json"
ACQ_JSON = EVIDENCE_DIR / "p5_005_model_acquisition.json"

MODEL_14B = ROOT / "models" / "qwen3-14b" / "openvino-int4-gpu"
MODEL_8B = ROOT / "models" / "qwen3-8b" / "openvino-int4-gpu"
MODEL_DRAFT_06B = ROOT / "models" / "qwen3-0.6b" / "openvino-int4-gpu"
EAGLE3_8B = ROOT / "models" / "eagle3-qwen3-8b"
EAGLE3_14B = ROOT / "models" / "eagle3-qwen3-14b"

PROMPT_BANDS = [128, 256, 512, 1024, 2048, 3072, 4096]
WARMUP_RUNS = 2
MEASURED_RUNS = 5
MAX_NEW_TOKENS = 128
MEMORY_WARN_MB = 26_000.0
MEMORY_BUDGET_MB = 15_507.0


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def git_head() -> str:
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()


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
        raise RuntimeError("POWER_ENVELOPE_NOT_LOCKED: AC power required for P5-005 benchmark")
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


def make_generation_config(assisted: bool = False) -> Any:
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
            config.num_assistant_tokens = 5
            config.assistant_confidence_threshold = 0.35
        except Exception:
            pass

    return config


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
        ttft_ms = ((first_token_time - t0) * 1000.0) if first_token_time is not None else total_ms

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
        "ttft_ms": stats([float(row["latency_first_token_ms"]) for row in ok], len(ok), len(fail)),
        "latency_total_ms": stats([float(row["latency_total_ms"]) for row in ok], len(ok), len(fail)),
        "decode_tokens_per_sec": stats([float(row["decode_tokens_per_sec"]) for row in ok], len(ok), len(fail)),
        "rss_peak_mb": stats([float(row["rss_peak_mb"]) for row in runs], len(runs), 0),
        "fingerprint_distribution": dict(Counter(row["error_fingerprint"] for row in fail if row.get("error_fingerprint"))),
    }


def model_paths_ok() -> dict[str, Any]:
    checks: dict[str, Any] = {}
    for name, path in {
        "qwen3-14b": MODEL_14B,
        "qwen3-8b": MODEL_8B,
        "qwen3-0.6b": MODEL_DRAFT_06B,
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


def build_user_content_to_token_len(tokenizer: Any, target_tokens: int, seed: str) -> str:
    chunk = (
        " local privacy deterministic benchmark payload "
        "context window feasibility matrix repeated segment "
    )
    text = seed
    for _ in range(60000):
        toks = tokenizer(text, return_tensors="np")["input_ids"][0]
        if len(toks) >= target_tokens:
            break
        text += chunk
    toks = tokenizer(text, return_tensors="np")["input_ids"][0]
    if len(toks) > target_tokens:
        text = tokenizer.decode(toks[:target_tokens], skip_special_tokens=True)
    return text


def build_chat_prompt(tokenizer: Any, user_content: str, system_prompt: str) -> str:
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_content},
    ]
    return tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)


def create_pipeline(
    model_dir: Path,
    pipeline_kwargs: dict[str, Any] | None,
    runtime_properties: dict[str, Any] | None,
    draft_model_path: Path | None,
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
            if not draft_model_path.exists():
                raise RuntimeError(f"DRAFT_MODEL_NOT_FOUND: {draft_model_path}")
            if not hasattr(ov_genai, "draft_model"):
                raise RuntimeError("EAGLE3_API_NOT_AVAILABLE")
            config["draft_model"] = ov_genai.draft_model(str(draft_model_path), "GPU")

        pipe = ov_genai.LLMPipeline(str(model_dir), "GPU", config, **kwargs)
        compile_ms = (time.perf_counter() - t0) * 1000.0
        return pipe, compile_ms, None
    except Exception as exc:  # noqa: BLE001
        return None, None, {
            "message": str(exc),
            "fingerprint": normalize_error("PIPELINE_CREATION_ERROR", str(exc)),
        }


def generation_config_for_test(test_id: str) -> Any:
    if test_id in {"T-09", "T-10"}:
        return make_generation_config(assisted=True)
    return make_generation_config(assisted=False)


def test_specifications(capabilities: dict[str, Any]) -> tuple[list[dict[str, Any]], bool, bool]:
    kv_supported = bool(capabilities.get("kv_cache_precision_property_present"))
    xattention_supported = bool(capabilities.get("xattention_property_present"))
    prefix_supported = bool(capabilities.get("prefix_cache_api_present"))
    draft_api_supported = bool(capabilities.get("draft_model_api_present"))
    assisted_fields = bool(capabilities.get("assistant_gen_fields_present"))

    specs: list[dict[str, Any]] = [
        {
            "id": "T-01",
            "name": "14B Baseline",
            "model_path": MODEL_14B,
            "features_requested": [],
            "runtime_properties": {},
            "pipeline_kwargs": {},
            "draft_model_path": None,
            "requires": [],
            "fallback_if_missing": False,
        },
        {
            "id": "T-02",
            "name": "14B + INT8 KV",
            "model_path": MODEL_14B,
            "features_requested": ["INT8_KV"],
            "runtime_properties": {"KV_CACHE_PRECISION": "u8"} if kv_supported else {},
            "pipeline_kwargs": {},
            "draft_model_path": None,
            "requires": ["INT8_KV"],
            "fallback_if_missing": False,
        },
        {
            "id": "T-03",
            "name": "14B + INT8 KV + XAttention",
            "model_path": MODEL_14B,
            "features_requested": ["INT8_KV", "XATTENTION"],
            "runtime_properties": (
                {"KV_CACHE_PRECISION": "u8", "GPU_ENABLE_SDPA_OPTIMIZATION": True}
                if kv_supported and xattention_supported
                else {}
            ),
            "pipeline_kwargs": {},
            "draft_model_path": None,
            "requires": ["INT8_KV", "XATTENTION"],
            "fallback_if_missing": False,
        },
        {
            "id": "T-04",
            "name": "14B Full Optimization Stack",
            "model_path": MODEL_14B,
            "features_requested": ["INT8_KV", "XATTENTION", "PREFIX_CACHING"],
            "runtime_properties": (
                {"KV_CACHE_PRECISION": "u8", "GPU_ENABLE_SDPA_OPTIMIZATION": True}
                if kv_supported and xattention_supported
                else ({"KV_CACHE_PRECISION": "u8"} if kv_supported else {})
            ),
            "pipeline_kwargs": {"ENABLE_PREFIX_CACHING": True} if prefix_supported else {},
            "draft_model_path": None,
            "requires": [],
            "fallback_if_missing": True,
        },
        {
            "id": "T-05",
            "name": "14B + EAGLE-3",
            "model_path": MODEL_14B,
            "features_requested": ["EAGLE3"],
            "runtime_properties": {},
            "pipeline_kwargs": {},
            "draft_model_path": EAGLE3_14B,
            "requires": ["EAGLE3"],
            "fallback_if_missing": False,
        },
        {
            "id": "T-06",
            "name": "8B Baseline",
            "model_path": MODEL_8B,
            "features_requested": [],
            "runtime_properties": {},
            "pipeline_kwargs": {},
            "draft_model_path": None,
            "requires": [],
            "fallback_if_missing": False,
        },
        {
            "id": "T-07",
            "name": "8B + EAGLE-3",
            "model_path": MODEL_8B,
            "features_requested": ["EAGLE3"],
            "runtime_properties": {},
            "pipeline_kwargs": {},
            "draft_model_path": EAGLE3_8B,
            "requires": ["EAGLE3"],
            "fallback_if_missing": False,
        },
        {
            "id": "T-08",
            "name": "8B Full Optimization Stack",
            "model_path": MODEL_8B,
            "features_requested": ["INT8_KV", "XATTENTION", "PREFIX_CACHING"],
            "runtime_properties": (
                {"KV_CACHE_PRECISION": "u8", "GPU_ENABLE_SDPA_OPTIMIZATION": True}
                if kv_supported and xattention_supported
                else ({"KV_CACHE_PRECISION": "u8"} if kv_supported else {})
            ),
            "pipeline_kwargs": {"ENABLE_PREFIX_CACHING": True} if prefix_supported else {},
            "draft_model_path": None,
            "requires": [],
            "fallback_if_missing": True,
        },
        {
            "id": "T-09",
            "name": "14B + Qwen3-0.6B Assisted Generation",
            "model_path": MODEL_14B,
            "features_requested": ["ASSISTED_GEN"],
            "runtime_properties": {},
            "pipeline_kwargs": {},
            "draft_model_path": MODEL_DRAFT_06B,
            "requires": ["ASSISTED_GEN"],
            "fallback_if_missing": False,
        },
        {
            "id": "T-10",
            "name": "8B + Qwen3-0.6B Assisted Generation",
            "model_path": MODEL_8B,
            "features_requested": ["ASSISTED_GEN"],
            "runtime_properties": {},
            "pipeline_kwargs": {},
            "draft_model_path": MODEL_DRAFT_06B,
            "requires": ["ASSISTED_GEN"],
            "fallback_if_missing": False,
        },
    ]
    return specs, draft_api_supported, assisted_fields


def build_capabilities() -> dict[str, Any]:
    gpu_props = supported_gpu_properties()
    gen_attrs = dir(ov_genai.GenerationConfig)

    return {
        "openvino_genai_version": getattr(ov_genai, "__version__", "unknown"),
        "gpu_supported_properties": gpu_props,
        "kv_cache_precision_property_present": "KV_CACHE_PRECISION" in gpu_props,
        "xattention_property_present": "GPU_ENABLE_SDPA_OPTIMIZATION" in gpu_props,
        "prefix_cache_api_present": False,
        "draft_model_api_present": hasattr(ov_genai, "draft_model"),
        "assistant_gen_fields_present": all(
            name in gen_attrs for name in ["assistant_confidence_threshold", "num_assistant_tokens"]
        ),
        "generation_config_fields": [
            name
            for name in [
                "assistant_confidence_threshold",
                "num_assistant_tokens",
                "is_assisting_generation",
            ]
            if name in gen_attrs
        ],
    }


def should_skip_test(test: dict[str, Any], draft_api_supported: bool, assisted_fields: bool) -> tuple[bool, str | None]:
    test_id = str(test["id"])
    features = set(test.get("features_requested", []))

    if "EAGLE3" in features and not draft_api_supported:
        return True, "EAGLE3_API_NOT_AVAILABLE"

    if test_id in {"T-05", "T-07"} and test.get("draft_model_path") is not None:
        draft_model_path = Path(test["draft_model_path"])
        if not draft_model_path.exists():
            return True, "EAGLE3_DRAFT_NOT_AVAILABLE"

    if test_id in {"T-09", "T-10"}:
        if not draft_api_supported:
            return True, "ASSISTED_GEN_NOT_AVAILABLE"
        if not assisted_fields:
            return True, "ASSISTED_GEN_NOT_AVAILABLE"
        draft_model_path = Path(test["draft_model_path"])
        if not draft_model_path.exists():
            return True, "ASSISTED_DRAFT_MODEL_NOT_FOUND"

    requires = set(test.get("requires", []))
    if "INT8_KV" in requires and not bool(test.get("runtime_properties")):
        return True, "INT8_KV_NOT_AVAILABLE"
    if "XATTENTION" in requires and "GPU_ENABLE_SDPA_OPTIMIZATION" not in test.get("runtime_properties", {}):
        return True, "XATTENTION_NOT_AVAILABLE"

    return False, None


def evaluate_umfg(matrix: dict[str, Any]) -> dict[str, Any]:
    tests_raw = matrix.get("tests", [])
    tests = tests_raw if isinstance(tests_raw, list) else []
    by_id: dict[str, dict[str, Any]] = {}
    for test in tests:
        if not isinstance(test, dict):
            continue
        test_id = test.get("id")
        if isinstance(test_id, str):
            by_id[test_id] = test

    def tps_mean(test_id: str, band: int) -> float:
        test = by_id.get(test_id, {})
        if test.get("status") != "completed":
            return 0.0
        for point in test.get("points", []):
            if int(point.get("prompt_length_user_tokens_target", -1)) == band:
                summary = point.get("summary", {})
                decode = summary.get("decode_tokens_per_sec", {})
                return float(decode.get("mean", 0.0))
        return 0.0

    def valid_count(test_id: str, band: int) -> int:
        test = by_id.get(test_id, {})
        if test.get("status") != "completed":
            return 0
        for point in test.get("points", []):
            if int(point.get("prompt_length_user_tokens_target", -1)) == band:
                summary = point.get("summary", {})
                return int(summary.get("valid_count", 0))
        return 0

    def peak_rss_test(test_id: str) -> float:
        test = by_id.get(test_id, {})
        peaks: list[float] = []
        for point in test.get("points", []):
            summary = point.get("summary", {})
            rss = summary.get("rss_peak_mb", {})
            peaks.append(float(rss.get("max", 0.0)))
        return max(peaks) if peaks else 0.0

    completed_ids: list[str] = [tid for tid, test in by_id.items() if test.get("status") == "completed"]

    best_14b = max([tps_mean(tid, 512) for tid in ["T-01", "T-02", "T-03", "T-04", "T-05", "T-09"]], default=0.0)
    best_8b = max([tps_mean(tid, 512) for tid in ["T-06", "T-07", "T-08", "T-10"]], default=0.0)

    g01_pass = best_14b >= 8.0 or best_8b >= 8.0

    speculative_pairs = [("T-05", "T-01"), ("T-07", "T-06"), ("T-09", "T-01"), ("T-10", "T-06")]
    g02_pass = False
    for test_id, baseline_id in speculative_pairs:
        baseline = tps_mean(baseline_id, 512)
        current = tps_mean(test_id, 512)
        if baseline > 0 and current >= baseline * 1.3:
            g02_pass = True
            break

    recommended_candidates = [tid for tid in ["T-01", "T-02", "T-03", "T-04", "T-05", "T-06", "T-07", "T-08", "T-09", "T-10"] if tid in by_id]
    candidate_scores = {tid: tps_mean(tid, 512) for tid in recommended_candidates}
    recommended_id = ""
    best_score = -1.0
    for candidate_id, score in candidate_scores.items():
        if score > best_score:
            best_score = score
            recommended_id = candidate_id

    g03_pass = bool(recommended_id) and peak_rss_test(recommended_id) <= MEMORY_BUDGET_MB

    g04_pass = False
    if recommended_id:
        g04_pass = all(valid_count(recommended_id, band) >= 4 for band in PROMPT_BANDS)

    g05a_pass = tps_mean("T-09", 512) >= 1.3 * tps_mean("T-01", 512) if tps_mean("T-01", 512) > 0 else False
    g05b_pass = tps_mean("T-10", 512) >= 1.3 * tps_mean("T-06", 512) if tps_mean("T-06", 512) > 0 else False

    comparability_count = 0
    for tid in completed_ids:
        if valid_count(tid, 512) > 0:
            comparability_count += 1
    g06_pass = comparability_count >= 3

    if not g06_pass:
        disposition = "INSUFFICIENT_EVIDENCE"
    elif best_14b >= 8.0 and g03_pass and g04_pass:
        if max(tps_mean("T-05", 512), tps_mean("T-09", 512)) >= 1.3 * tps_mean("T-01", 512):
            disposition = "QWEN3_14B_WITH_SPEC_DECODING"
        else:
            disposition = "QWEN3_14B_CONFIRMED"
    elif 6.0 <= best_14b < 8.0 and g03_pass and g04_pass:
        disposition = "QWEN3_14B_MARGINAL"
    elif best_8b >= 8.0 and g03_pass and g04_pass:
        if tps_mean("T-07", 512) >= 1.3 * tps_mean("T-06", 512):
            disposition = "QWEN3_8B_WITH_EAGLE3"
        else:
            disposition = "QWEN3_8B_FALLBACK"
    elif best_14b < 8.0 and best_8b < 8.0 and g06_pass:
        disposition = "BOTH_INFEASIBLE"
    else:
        disposition = "INSUFFICIENT_EVIDENCE"

    return {
        "checks": {
            "G-01": {"passed": g01_pass, "detail": "Primary throughput threshold at band 512 (>=8 tps)"},
            "G-02": {"passed": g02_pass, "detail": "At least one speculative path >=1.3x baseline"},
            "G-03": {"passed": g03_pass, "detail": f"Recommended config RSS <= {MEMORY_BUDGET_MB}MB"},
            "G-04": {"passed": g04_pass, "detail": "Recommended config has >=4/5 valid runs for all bands"},
            "G-05a": {"passed": g05a_pass, "detail": "14B assisted generation speedup"},
            "G-05b": {"passed": g05b_pass, "detail": "8B assisted generation speedup"},
            "G-06": {"passed": g06_pass, "detail": f"Comparability count at band 512: {comparability_count}"},
        },
        "recommended_test_id": recommended_id,
        "best_tps_512": {
            "qwen3_14b": best_14b,
            "qwen3_8b": best_8b,
        },
        "disposition": disposition,
    }


def run_test(test: dict[str, Any]) -> dict[str, Any]:
    model_path = Path(test["model_path"])
    tokenizer = AutoTokenizer.from_pretrained(str(model_path), local_files_only=True)

    system_prompt = "You are BlarAI in an offline local-only environment. Answer deterministically."
    if test["id"] == "T-04":
        system_prompt = "BlarAI stable prefix prompt for cache reuse. Maintain deterministic and concise style."

    pipe, compile_ms, creation_error = create_pipeline(
        model_dir=model_path,
        pipeline_kwargs=dict(test.get("pipeline_kwargs", {})),
        runtime_properties=dict(test.get("runtime_properties", {})),
        draft_model_path=Path(test["draft_model_path"]) if test.get("draft_model_path") is not None else None,
    )

    result: dict[str, Any] = {
        "id": test["id"],
        "name": test["name"],
        "model_path": str(model_path),
        "features_requested": test.get("features_requested", []),
        "runtime_properties": test.get("runtime_properties", {}),
        "pipeline_kwargs": test.get("pipeline_kwargs", {}),
        "draft_model_path": str(test["draft_model_path"]) if test.get("draft_model_path") else None,
        "pipeline_creation_ok": pipe is not None,
        "pipeline_compile_ms": compile_ms,
        "pipeline_creation_error": creation_error,
        "status": "completed" if pipe is not None else "pipeline_creation_error",
        "points": [],
    }

    if pipe is None:
        return result

    for band in PROMPT_BANDS:
        user_content = build_user_content_to_token_len(
            tokenizer,
            band,
            seed=f"P5-FEASIBILITY-005 {test['id']} prompt band {band}.",
        )
        user_tokens = int(len(tokenizer(user_content, return_tensors="np")["input_ids"][0]))
        prompt = build_chat_prompt(tokenizer, user_content, system_prompt)
        formatted_tokens = int(len(tokenizer(prompt, return_tensors="np")["input_ids"][0]))

        gen_cfg = generation_config_for_test(str(test["id"]))

        for _ in range(WARMUP_RUNS):
            _ = run_single_generation(pipe, tokenizer, prompt, gen_cfg)

        measured = [run_single_generation(pipe, tokenizer, prompt, gen_cfg) for _ in range(MEASURED_RUNS)]

        point: dict[str, Any] = {
            "prompt_length_user_tokens_target": band,
            "prompt_length_user_tokens_actual": user_tokens,
            "formatted_prompt_tokens": formatted_tokens,
            "runs": measured,
            "summary": summarize_runs(measured),
            "missing_reason": None,
        }
        point_summary = point.get("summary", {})
        point_summary_dict = point_summary if isinstance(point_summary, dict) else {}
        if int(point_summary_dict.get("valid_count", 0)) == 0:
            point["missing_reason"] = "No successful runs"

        for run in measured:
            if float(run.get("rss_peak_mb", 0.0)) > MEMORY_WARN_MB:
                if "warnings" not in point or not isinstance(point["warnings"], list):
                    point["warnings"] = []
                cast(list[Any], point["warnings"]).append("RSS_GT_26GB_WARNING")
                break

        result["points"].append(point)

    pipe = None
    gc.collect()
    time.sleep(2)

    return result


def main() -> None:
    power_state = enforce_ac_power_or_fail_closed()

    env: dict[str, Any] = {
        "timestamp_utc": now_iso(),
        "commit_hash": git_head(),
        "python_version": sys.version,
        "platform": platform.platform(),
        "openvino_version": getattr(ov, "__version__", "unknown") if ov is not None else "unavailable",
        "openvino_genai_version": getattr(ov_genai, "__version__", "unknown"),
        "available_devices": available_devices(),
        "power_envelope": power_state,
        "memory_limits": {
            "warning_rss_mb": MEMORY_WARN_MB,
            "budget_rss_mb": MEMORY_BUDGET_MB,
        },
        "model_checks": model_paths_ok(),
    }

    model_checks = env.get("model_checks")
    if not isinstance(model_checks, dict):
        blocked: dict[str, Any] = {
            "milestone": "P5-FEASIBILITY-005",
            "timestamp_utc": now_iso(),
            "metadata": env,
            "status": "blocked",
            "failure_reason": "MODEL_ASSET_PRECHECK_FAILED: model check structure invalid",
            "tests": [],
            "quality_gate": {
                "disposition": "INSUFFICIENT_EVIDENCE",
                "reason_code": "MISSING_MODEL_ASSETS",
            },
        }
        write_json_atomic(OUTPUT_JSON, blocked)
        print(json.dumps({"status": "blocked", "artifact": str(OUTPUT_JSON), "reason": blocked["failure_reason"]}, indent=2))
        return

    required_models = ["qwen3-14b", "qwen3-8b", "qwen3-0.6b"]
    missing_models: list[str] = []
    for model_key in required_models:
        item = model_checks.get(model_key, {})
        if not bool(item.get("dir_exists") and item.get("xml_exists") and item.get("bin_exists")):
            missing_models.append(model_key)

    if missing_models:
        blocked_missing: dict[str, Any] = {
            "milestone": "P5-FEASIBILITY-005",
            "timestamp_utc": now_iso(),
            "metadata": env,
            "status": "blocked",
            "failure_reason": "MODEL_ASSET_PRECHECK_FAILED",
            "missing_models": missing_models,
            "acquisition_artifact_present": ACQ_JSON.exists(),
            "tests": [],
            "quality_gate": {
                "disposition": "INSUFFICIENT_EVIDENCE",
                "reason_code": "MISSING_MODEL_ASSETS",
            },
        }
        write_json_atomic(OUTPUT_JSON, blocked_missing)
        print(json.dumps({"status": "blocked", "artifact": str(OUTPUT_JSON), "missing_models": missing_models}, indent=2))
        return

    capabilities = build_capabilities()
    tests, draft_api_supported, assisted_fields = test_specifications(capabilities)

    matrix: dict[str, Any] = {
        "milestone": "P5-FEASIBILITY-005",
        "timestamp_utc": now_iso(),
        "metadata": env,
        "acquisition_artifact_present": ACQ_JSON.exists(),
        "feature_discovery": capabilities,
        "benchmark_policy": {
            "runs_per_point_measured": MEASURED_RUNS,
            "warmup_runs_discarded": WARMUP_RUNS,
            "max_new_tokens": MAX_NEW_TOKENS,
            "temperature": 0.0,
            "prompt_bands": PROMPT_BANDS,
            "device": "GPU",
            "ordered_execution": [test["id"] for test in tests],
        },
        "tests": [],
        "quality_gate": {},
    }

    write_json_atomic(OUTPUT_JSON, matrix)

    for test in tests:
        skip, reason = should_skip_test(test, draft_api_supported=draft_api_supported, assisted_fields=assisted_fields)
        if skip:
            matrix["tests"].append(
                {
                    "id": test["id"],
                    "name": test["name"],
                    "status": "skipped",
                    "skip_reason": reason,
                    "features_requested": test.get("features_requested", []),
                }
            )
            write_json_atomic(OUTPUT_JSON, matrix)
            continue

        result = run_test(test)
        matrix["tests"].append(result)
        write_json_atomic(OUTPUT_JSON, matrix)

        if test["id"] == "T-01" and result.get("pipeline_creation_ok") is False:
            matrix.setdefault("critical_abort", {})["reason"] = "T-01_PIPELINE_CREATION_FAILED"
            break

    matrix["quality_gate"] = evaluate_umfg(matrix)
    matrix["finished_utc"] = now_iso()
    write_json_atomic(OUTPUT_JSON, matrix)

    print(
        json.dumps(
            {
                "status": "ok",
                "artifact": str(OUTPUT_JSON),
                "disposition": matrix["quality_gate"].get("disposition"),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
