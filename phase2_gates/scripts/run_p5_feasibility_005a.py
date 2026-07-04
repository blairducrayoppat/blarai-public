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
OUTPUT_JSON = EVIDENCE_DIR / "p5_005a_unified_draft_feasibility_matrix.json"
OUTPUT_SUMMARY_MD = EVIDENCE_DIR / "p5_005a_unified_draft_feasibility_summary.md"
ACQ_JSON = EVIDENCE_DIR / "p5_005a_model_acquisition.json"
DISCOVERY_JSON = EVIDENCE_DIR / "p5_005a_cross_device_draft_discovery.json"

MODEL_14B = ROOT / "models" / "qwen3-14b" / "openvino-int4-gpu"
MODEL_8B = ROOT / "models" / "qwen3-8b" / "openvino-int4-gpu"
DRAFT_06B_GPU = ROOT / "models" / "qwen3-0.6b" / "openvino-int4-gpu"
DRAFT_17B_GPU = ROOT / "models" / "qwen3-1.7b" / "openvino-int4"
DRAFT_06B_NPU = ROOT / "models" / "qwen3-0.6b" / "openvino-int4-npu"
DRAFT_17B_NPU = ROOT / "models" / "qwen3-1.7b" / "openvino-int4-npu"
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


def write_markdown_summary(path: Path, matrix: dict[str, Any]) -> None:
    tests = cast(list[dict[str, Any]], matrix.get("tests", []))
    completed = [t for t in tests if t.get("status") == "completed"]
    skipped = [t for t in tests if t.get("status") == "skipped"]

    lines: list[str] = []
    lines.append("# P5-005a Unified Draft Feasibility Summary")
    lines.append("")
    lines.append("## Outcome")
    lines.append("")
    lines.append(f"- Finished UTC: `{matrix.get('finished_utc', 'unknown')}`")
    lines.append(f"- Disposition: `{matrix.get('quality_gate', {}).get('disposition', 'unknown')}`")
    lines.append(f"- Total tests in matrix: `{len(tests)}`")
    lines.append(f"- Completed: `{len(completed)}`")
    lines.append(f"- Skipped: `{len(skipped)}`")
    lines.append("")

    lines.append("## Completed Tests")
    lines.append("")
    if completed:
        for test in completed:
            tps_512 = 0.0
            for point in cast(list[dict[str, Any]], test.get("points", [])):
                if int(point.get("prompt_length_user_tokens_target", -1)) == 512:
                    tps_512 = float(point.get("summary", {}).get("decode_tokens_per_sec", {}).get("mean", 0.0))
                    break
            lines.append(f"- {test.get('id')}: {test.get('name')} (tps@512={tps_512:.2f})")
    else:
        lines.append("- None")
    lines.append("")

    lines.append("## Skipped Tests")
    lines.append("")
    if skipped:
        for test in skipped:
            lines.append(f"- {test.get('id')}: {test.get('name')} ({test.get('skip_reason', 'unknown')})")
    else:
        lines.append("- None")
    lines.append("")

    lines.append("## Quality Gate Checks")
    lines.append("")
    checks = cast(dict[str, Any], matrix.get("quality_gate", {}).get("checks", {}))
    if checks:
        for check_id, payload in checks.items():
            passed = bool(cast(dict[str, Any], payload).get("passed"))
            detail = str(cast(dict[str, Any], payload).get("detail", ""))
            lines.append(f"- {check_id}: {'PASS' if passed else 'FAIL'} — {detail}")
    else:
        lines.append("- None")
    lines.append("")

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


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
        raise RuntimeError("POWER_ENVELOPE_NOT_LOCKED: AC power required for P5-005a benchmark")
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
            config.assistant_confidence_threshold = 0.0
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


def path_has_model(path: Path) -> bool:
    return path.exists() and (path / "openvino_model.xml").exists() and (path / "openvino_model.bin").exists()


def model_paths_ok() -> dict[str, Any]:
    checks: dict[str, Any] = {}
    for name, path in {
        "qwen3-14b": MODEL_14B,
        "qwen3-8b": MODEL_8B,
        "qwen3-0.6b-gpu": DRAFT_06B_GPU,
        "qwen3-1.7b-gpu": DRAFT_17B_GPU,
        "qwen3-0.6b-npu": DRAFT_06B_NPU,
        "qwen3-1.7b-npu": DRAFT_17B_NPU,
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
            config["draft_model"] = ov_genai.draft_model(str(draft_model_path), draft_device or "GPU")

        pipe = ov_genai.LLMPipeline(str(model_dir), "GPU", config, **kwargs)
        compile_ms = (time.perf_counter() - t0) * 1000.0
        return pipe, compile_ms, None
    except Exception as exc:  # noqa: BLE001
        return None, None, {
            "message": str(exc),
            "fingerprint": normalize_error("PIPELINE_CREATION_ERROR", str(exc)),
        }


def generation_config_for_test(test_id: str) -> Any:
    assisted = test_id in {"T-09", "T-10", "T-11", "T-12", "T-13", "T-14", "T-15", "T-16", "T-17", "T-18"}
    return make_generation_config(assisted=assisted)


def build_capabilities() -> dict[str, Any]:
    gpu_props = supported_gpu_properties()
    gen_attrs = dir(ov_genai.GenerationConfig)

    discovery = read_json(DISCOVERY_JSON) or {}

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
        "cross_device_discovery": discovery,
    }


def test_specifications(capabilities: dict[str, Any]) -> list[dict[str, Any]]:
    kv_supported = bool(capabilities.get("kv_cache_precision_property_present"))
    xattention_supported = bool(capabilities.get("xattention_property_present"))
    prefix_supported = bool(capabilities.get("prefix_cache_api_present"))

    optimized_props = (
        {"KV_CACHE_PRECISION": "u8", "GPU_ENABLE_SDPA_OPTIMIZATION": True}
        if kv_supported and xattention_supported
        else ({"KV_CACHE_PRECISION": "u8"} if kv_supported else {})
    )
    optimized_kwargs = {"ENABLE_PREFIX_CACHING": True} if prefix_supported else {}

    return [
        {"id": "T-01", "name": "14B Baseline", "model_path": MODEL_14B, "runtime_properties": {}, "pipeline_kwargs": {}, "draft_model_path": None, "draft_device": None, "target": "14B", "is_speculative": False},
        {"id": "T-02", "name": "14B + INT8 KV", "model_path": MODEL_14B, "runtime_properties": {"KV_CACHE_PRECISION": "u8"} if kv_supported else {}, "pipeline_kwargs": {}, "draft_model_path": None, "draft_device": None, "target": "14B", "is_speculative": False, "required_feature": "INT8_KV"},
        {"id": "T-03", "name": "14B + INT8 KV + XAttention", "model_path": MODEL_14B, "runtime_properties": optimized_props, "pipeline_kwargs": {}, "draft_model_path": None, "draft_device": None, "target": "14B", "is_speculative": False, "required_feature": "XATTENTION"},
        {"id": "T-04", "name": "14B Full Optimization", "model_path": MODEL_14B, "runtime_properties": optimized_props, "pipeline_kwargs": optimized_kwargs, "draft_model_path": None, "draft_device": None, "target": "14B", "is_speculative": False},
        {"id": "T-05", "name": "14B + EAGLE-3", "model_path": MODEL_14B, "runtime_properties": {}, "pipeline_kwargs": {}, "draft_model_path": EAGLE3_14B, "draft_device": "GPU", "target": "14B", "is_speculative": True, "eagle": True},
        {"id": "T-06", "name": "8B Baseline", "model_path": MODEL_8B, "runtime_properties": {}, "pipeline_kwargs": {}, "draft_model_path": None, "draft_device": None, "target": "8B", "is_speculative": False},
        {"id": "T-07", "name": "8B + EAGLE-3", "model_path": MODEL_8B, "runtime_properties": {}, "pipeline_kwargs": {}, "draft_model_path": EAGLE3_8B, "draft_device": "GPU", "target": "8B", "is_speculative": True, "eagle": True},
        {"id": "T-08", "name": "8B Full Optimization", "model_path": MODEL_8B, "runtime_properties": optimized_props, "pipeline_kwargs": optimized_kwargs, "draft_model_path": None, "draft_device": None, "target": "8B", "is_speculative": False},
        {"id": "T-09", "name": "14B + 0.6B draft GPU", "model_path": MODEL_14B, "runtime_properties": {}, "pipeline_kwargs": {}, "draft_model_path": DRAFT_06B_GPU, "draft_device": "GPU", "target": "14B", "is_speculative": True},
        {"id": "T-10", "name": "8B + 0.6B draft GPU", "model_path": MODEL_8B, "runtime_properties": {}, "pipeline_kwargs": {}, "draft_model_path": DRAFT_06B_GPU, "draft_device": "GPU", "target": "8B", "is_speculative": True},
        {"id": "T-11", "name": "14B + 1.7B draft GPU", "model_path": MODEL_14B, "runtime_properties": {}, "pipeline_kwargs": {}, "draft_model_path": DRAFT_17B_GPU, "draft_device": "GPU", "target": "14B", "is_speculative": True},
        {"id": "T-12", "name": "8B + 1.7B draft GPU", "model_path": MODEL_8B, "runtime_properties": {}, "pipeline_kwargs": {}, "draft_model_path": DRAFT_17B_GPU, "draft_device": "GPU", "target": "8B", "is_speculative": True},
        {"id": "T-13", "name": "14B + 0.6B draft NPU", "model_path": MODEL_14B, "runtime_properties": {}, "pipeline_kwargs": {}, "draft_model_path": DRAFT_06B_NPU, "draft_device": "NPU", "target": "14B", "is_speculative": True, "cross_device": True},
        {"id": "T-14", "name": "14B + 1.7B draft NPU", "model_path": MODEL_14B, "runtime_properties": {}, "pipeline_kwargs": {}, "draft_model_path": DRAFT_17B_NPU, "draft_device": "NPU", "target": "14B", "is_speculative": True, "cross_device": True},
        {"id": "T-15", "name": "8B + 0.6B draft NPU", "model_path": MODEL_8B, "runtime_properties": {}, "pipeline_kwargs": {}, "draft_model_path": DRAFT_06B_NPU, "draft_device": "NPU", "target": "8B", "is_speculative": True, "cross_device": True},
        {"id": "T-16", "name": "8B + 1.7B draft NPU", "model_path": MODEL_8B, "runtime_properties": {}, "pipeline_kwargs": {}, "draft_model_path": DRAFT_17B_NPU, "draft_device": "NPU", "target": "8B", "is_speculative": True, "cross_device": True},
        {"id": "T-17", "name": "14B + 1.7B draft CPU", "model_path": MODEL_14B, "runtime_properties": {}, "pipeline_kwargs": {}, "draft_model_path": DRAFT_17B_GPU, "draft_device": "CPU", "target": "14B", "is_speculative": True, "cpu_fallback": True},
        {"id": "T-18", "name": "8B + 1.7B draft CPU", "model_path": MODEL_8B, "runtime_properties": {}, "pipeline_kwargs": {}, "draft_model_path": DRAFT_17B_GPU, "draft_device": "CPU", "target": "8B", "is_speculative": True, "cpu_fallback": True},
    ]


def should_skip_test(test: dict[str, Any], capabilities: dict[str, Any], t01_failed: bool) -> tuple[bool, str | None]:
    if t01_failed and str(test["id"]).startswith("T-0") and str(test["id"]) != "T-06":
        return True, "DEPENDENCY_T01_PIPELINE_FAILED"

    if not path_has_model(Path(test["model_path"])):
        return True, "TARGET_MODEL_NOT_AVAILABLE"

    if test.get("required_feature") == "INT8_KV" and not bool(capabilities.get("kv_cache_precision_property_present")):
        return True, "INT8_KV_NOT_AVAILABLE"

    if test.get("required_feature") == "XATTENTION" and not bool(capabilities.get("xattention_property_present")):
        return True, "XATTENTION_NOT_AVAILABLE"

    if test.get("eagle"):
        if not path_has_model(Path(test["draft_model_path"])):
            return True, "EAGLE3_DRAFT_NOT_AVAILABLE"
        return False, None

    if test.get("draft_model_path") is not None:
        if not bool(capabilities.get("draft_model_api_present")):
            return True, "DRAFT_MODEL_API_NOT_AVAILABLE"
        if not bool(capabilities.get("assistant_gen_fields_present")):
            return True, "ASSISTED_FIELDS_NOT_AVAILABLE"
        if not path_has_model(Path(test["draft_model_path"])):
            return True, "DRAFT_MODEL_NOT_AVAILABLE"

    discovery = capabilities.get("cross_device_discovery", {})
    npu_supported = bool(cast(dict[str, Any], discovery).get("draft_on_npu_target_on_gpu", {}).get("supported")) if isinstance(discovery, dict) else False
    cpu_supported = bool(cast(dict[str, Any], discovery).get("draft_on_cpu_target_on_gpu", {}).get("supported")) if isinstance(discovery, dict) else False

    if test.get("cross_device") and not npu_supported:
        return True, "CROSS_DEVICE_DRAFT_NOT_SUPPORTED"

    if test.get("cross_device"):
        return True, "CROSS_DEVICE_DRAFT_DISABLED_FATAL_NATIVE_ABORT"

    if test.get("draft_device") == "NPU" and Path(test.get("draft_model_path", "")) == DRAFT_06B_NPU:
        return True, "NPU_DRAFT_06B_UNVALIDATED"

    if test.get("cpu_fallback"):
        if npu_supported:
            return True, "CPU_FALLBACK_NOT_REQUIRED_NPU_SUPPORTED"
        if not cpu_supported:
            return True, "CPU_CROSS_DEVICE_NOT_SUPPORTED"

    return False, None


def baseline_tps(matrix: dict[str, Any], target: str) -> float:
    baseline_id = "T-01" if target == "14B" else "T-06"
    for test in matrix.get("tests", []):
        if test.get("id") != baseline_id or test.get("status") != "completed":
            continue
        for point in test.get("points", []):
            if int(point.get("prompt_length_user_tokens_target", -1)) == 512:
                return float(point.get("summary", {}).get("decode_tokens_per_sec", {}).get("mean", 0.0))
    return 0.0


def evaluate_umdfg(matrix: dict[str, Any]) -> dict[str, Any]:
    completed = [t for t in matrix.get("tests", []) if t.get("status") == "completed"]

    def point_tps(test: dict[str, Any], band: int) -> float:
        for point in test.get("points", []):
            if int(point.get("prompt_length_user_tokens_target", -1)) == band:
                return float(point.get("summary", {}).get("decode_tokens_per_sec", {}).get("mean", 0.0))
        return 0.0

    def point_valid(test: dict[str, Any], band: int) -> int:
        for point in test.get("points", []):
            if int(point.get("prompt_length_user_tokens_target", -1)) == band:
                return int(point.get("summary", {}).get("valid_count", 0))
        return 0

    def test_peak_rss(test: dict[str, Any]) -> float:
        peaks: list[float] = []
        for point in test.get("points", []):
            peaks.append(float(point.get("summary", {}).get("rss_peak_mb", {}).get("max", 0.0)))
        return max(peaks) if peaks else 0.0

    tps512_all = [(t.get("id"), point_tps(t, 512)) for t in completed]
    best_tps_512 = max((v for _, v in tps512_all), default=0.0)

    recommendation: dict[str, Any] | None = None
    if tps512_all:
        best_id = max(tps512_all, key=lambda x: x[1])[0]
        recommendation = next((t for t in completed if t.get("id") == best_id), None)

    g01 = best_tps_512 >= 8.0

    g02 = False
    for t in completed:
        if not t.get("is_speculative"):
            continue
        target = str(t.get("target", ""))
        base = baseline_tps(matrix, target)
        cur = point_tps(t, 512)
        if base > 0 and cur >= 1.3 * base:
            g02 = True
            break

    g03 = bool(recommendation) and test_peak_rss(cast(dict[str, Any], recommendation)) <= MEMORY_BUDGET_MB

    g04 = False
    if recommendation:
        g04 = all(point_valid(cast(dict[str, Any], recommendation), band) >= 4 for band in PROMPT_BANDS)

    # draft comparison captured
    has_06 = any(t.get("id") in {"T-09", "T-10", "T-13", "T-15"} and t.get("status") == "completed" for t in matrix.get("tests", []))
    has_17 = any(t.get("id") in {"T-11", "T-12", "T-14", "T-16", "T-17", "T-18"} and t.get("status") == "completed" for t in matrix.get("tests", []))
    g05 = has_06 and has_17

    # NPU offload discovery completed
    disc = matrix.get("feature_discovery", {}).get("cross_device_discovery", {})
    g06 = isinstance(disc, dict) and "draft_on_npu_target_on_gpu" in disc

    # At least 3 distinct configs with valid band 512
    g07 = sum(1 for t in completed if point_valid(t, 512) > 0) >= 3

    # Disposition
    best_14 = max((point_tps(t, 512) for t in completed if t.get("target") == "14B"), default=0.0)
    best_8 = max((point_tps(t, 512) for t in completed if t.get("target") == "8B"), default=0.0)

    if not (g01 and g03 and g04 and g07):
        disposition = "INSUFFICIENT_EVIDENCE"
    elif best_14 >= 8.0 and g02:
        disposition = "QWEN3_14B_WITH_SPEC_DECODING"
    elif best_14 >= 8.0:
        disposition = "QWEN3_14B_CONFIRMED"
    elif 6.0 <= best_14 < 8.0:
        disposition = "QWEN3_14B_MARGINAL"
    elif best_8 >= 8.0 and g02:
        disposition = "QWEN3_8B_WITH_SPEC_DECODING"
    elif best_8 >= 8.0:
        disposition = "QWEN3_8B_FALLBACK"
    else:
        disposition = "BOTH_INFEASIBLE"

    return {
        "checks": {
            "G-01": {"passed": g01, "detail": ">=8 tps at band 512 in at least one config"},
            "G-02": {"passed": g02, "detail": "Speculative decoding >=1.3x baseline at band 512"},
            "G-03": {"passed": g03, "detail": "Recommended config peak RSS <= 15,507 MB"},
            "G-04": {"passed": g04, "detail": "Recommended config has >=4/5 valid runs across all bands"},
            "G-05": {"passed": g05, "detail": "Both draft sizes captured in completed tests"},
            "G-06": {"passed": g06, "detail": "NPU offload discovery artifact captured"},
            "G-07": {"passed": g07, "detail": ">=3 completed configs with valid band-512 data"},
        },
        "recommended_test_id": recommendation.get("id") if recommendation else None,
        "best_tps_512": {
            "qwen3_14b": best_14,
            "qwen3_8b": best_8,
            "overall": best_tps_512,
        },
        "disposition": disposition,
    }


def run_test(test: dict[str, Any], matrix: dict[str, Any]) -> dict[str, Any]:
    model_path = Path(test["model_path"])
    tokenizer = AutoTokenizer.from_pretrained(str(model_path), local_files_only=True)

    system_prompt = "You are BlarAI in an offline local-only environment. Answer deterministically."

    pipe, compile_ms, creation_error = create_pipeline(
        model_dir=model_path,
        pipeline_kwargs=dict(test.get("pipeline_kwargs", {})),
        runtime_properties=dict(test.get("runtime_properties", {})),
        draft_model_path=Path(test["draft_model_path"]) if test.get("draft_model_path") is not None else None,
        draft_device=cast(str | None, test.get("draft_device")),
    )

    result: dict[str, Any] = {
        "id": test["id"],
        "name": test["name"],
        "target": test.get("target"),
        "is_speculative": bool(test.get("is_speculative")),
        "model_path": str(model_path),
        "runtime_properties": test.get("runtime_properties", {}),
        "pipeline_kwargs": test.get("pipeline_kwargs", {}),
        "draft_model_path": str(test["draft_model_path"]) if test.get("draft_model_path") else None,
        "draft_device": test.get("draft_device"),
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
            seed=f"P5-FEASIBILITY-005a {test['id']} prompt band {band}.",
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
                cast(list[Any], point["warnings"]).append("RSS_GT_26GB_ABORT_TEST")
                result["status"] = "aborted_memory_warning"
                break

        result["points"].append(point)
        if result.get("status") == "aborted_memory_warning":
            break

    # speedup metric at band 512
    base = baseline_tps(matrix, str(test.get("target")))
    tps_512 = 0.0
    for p in result["points"]:
        if int(p.get("prompt_length_user_tokens_target", -1)) == 512:
            tps_512 = float(p.get("summary", {}).get("decode_tokens_per_sec", {}).get("mean", 0.0))
            break
    result["tps_512"] = tps_512
    result["speedup_vs_baseline_512"] = (tps_512 / base) if base > 0 else 0.0

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

    capabilities = build_capabilities()

    matrix: dict[str, Any] = {
        "milestone": "P5-FEASIBILITY-005a",
        "timestamp_utc": now_iso(),
        "metadata": env,
        "acquisition_artifact_present": ACQ_JSON.exists(),
        "cross_device_discovery_present": DISCOVERY_JSON.exists(),
        "feature_discovery": capabilities,
        "benchmark_policy": {
            "runs_per_point_measured": MEASURED_RUNS,
            "warmup_runs_discarded": WARMUP_RUNS,
            "max_new_tokens": MAX_NEW_TOKENS,
            "temperature": 0.0,
            "prompt_bands": PROMPT_BANDS,
            "device": "GPU target with draft GPU/NPU/CPU per test",
            "ordered_execution": [],
        },
        "tests": [],
        "quality_gate": {},
    }

    tests = test_specifications(capabilities)
    matrix["benchmark_policy"]["ordered_execution"] = [test["id"] for test in tests]

    write_json_atomic(OUTPUT_JSON, matrix)

    t01_failed = False
    for test in tests:
        skip, reason = should_skip_test(test, capabilities=capabilities, t01_failed=t01_failed)
        if skip:
            matrix["tests"].append(
                {
                    "id": test["id"],
                    "name": test["name"],
                    "target": test.get("target"),
                    "is_speculative": bool(test.get("is_speculative")),
                    "status": "skipped",
                    "skip_reason": reason,
                    "draft_device": test.get("draft_device"),
                }
            )
            write_json_atomic(OUTPUT_JSON, matrix)
            continue

        result = run_test(test, matrix)
        matrix["tests"].append(result)
        write_json_atomic(OUTPUT_JSON, matrix)

        if test["id"] == "T-01" and result.get("pipeline_creation_ok") is False:
            t01_failed = True

    matrix["quality_gate"] = evaluate_umdfg(matrix)
    matrix["finished_utc"] = now_iso()
    write_json_atomic(OUTPUT_JSON, matrix)
    write_markdown_summary(OUTPUT_SUMMARY_MD, matrix)

    print(
        json.dumps(
            {
                "status": "ok",
                "artifact": str(OUTPUT_JSON),
                "summary": str(OUTPUT_SUMMARY_MD),
                "disposition": matrix["quality_gate"].get("disposition"),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
