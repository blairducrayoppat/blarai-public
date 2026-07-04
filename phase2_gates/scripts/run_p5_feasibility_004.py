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
from typing import Any, Callable

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
OUTPUT_JSON = EVIDENCE_DIR / "p5_multi_device_capability_matrix.json"

MODEL_QWEN25 = ROOT / "models" / "qwen2.5-1.5b-instruct" / "openvino-int4-npu"
MODEL_QWEN3 = ROOT / "models" / "qwen3-1.7b" / "openvino-int4"

NPU_CONFIGS = [1024, 2048, 3072, 4096, 6144, 8192]
NPU_PROMPT_BANDS: dict[int, list[int]] = {
    1024: [256, 512, 768, 896, 960],
    2048: [256, 512, 1024, 1536, 1800, 2000],
    3072: [256, 512, 1024, 1536, 2048, 2560, 2900, 3000],
    4096: [256, 512, 1024, 2048, 3072, 3800, 4000],
    6144: [256, 512, 1024, 2048, 3072, 4096, 5120, 5800, 6000],
    8192: [256, 512, 1024, 2048, 3072, 4096, 6144, 7600, 8000],
}

GPU_CPU_PROMPT_BANDS = [128, 256, 512, 1024, 2048, 3072, 4096]

WARMUP_RUNS = 2
MEASURED_RUNS = 5
MAX_NEW_TOKENS = 128
MEMORY_WARN_MB = 28_000.0


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def git_head() -> str:
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)


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
        raise RuntimeError("POWER_ENVELOPE_NOT_LOCKED: AC power required for feasibility evidence capture")
    return state


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


def model_paths_ok() -> dict[str, Any]:
    checks: dict[str, Any] = {}
    for name, path in {
        "qwen2.5-1.5b-instruct": MODEL_QWEN25,
        "qwen3-1.7b": MODEL_QWEN3,
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
    except Exception:  # noqa: BLE001
        return []


def build_qwen25_chat_prompt(user_content: str) -> str:
    system_prompt = (
        "You are BlarAI in an offline, local-only environment. "
        "Answer deterministically and do not mention external networks."
    )
    return (
        f"<|im_start|>system\n{system_prompt}<|im_end|>\n"
        f"<|im_start|>user\n{user_content}<|im_end|>\n"
        "<|im_start|>assistant\n"
    )


def build_qwen3_chat_prompt(tokenizer: Any, user_content: str) -> str:
    messages = [
        {
            "role": "system",
            "content": "You are BlarAI in an offline, local-only environment. Answer deterministically.",
        },
        {"role": "user", "content": user_content},
    ]
    return tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)


def build_user_content_to_token_len(tokenizer: Any, target_tokens: int, seed: str) -> str:
    chunk = (
        " local privacy deterministic benchmark payload "
        "context window expansion verification repeated token segment "
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


def make_generation_config() -> Any:
    config = ov_genai.GenerationConfig()
    config.max_new_tokens = MAX_NEW_TOKENS
    config.do_sample = False
    try:
        config.temperature = 0.0
        config.top_k = 1
        config.top_p = 1.0
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
    pipeline_config: dict[str, Any] | None,
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
            generation_config=make_generation_config(),
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
        tps = (tokens_generated / (total_ms / 1000.0)) if total_ms > 0 else 0.0

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
            "pipeline_config": pipeline_config,
        }
    except Exception as exc:  # noqa: BLE001
        sampler.stop()
        rss_after = proc.memory_info().rss / (1024 * 1024)
        msg = str(exc)
        prefix = "AO_MAX_PROMPT_LEN" if "MAX_PROMPT_LEN" in msg else "GENERATION_ERROR"
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
            "error_fingerprint": normalize_error(prefix, msg),
            "pipeline_config": pipeline_config,
        }


def summarize_runs(runs: list[dict[str, Any]]) -> dict[str, Any]:
    ok = [row for row in runs if row["ok"]]
    fail = [row for row in runs if not row["ok"]]
    return {
        "valid_count": len(ok),
        "invalid_count": len(fail),
        "ttft_ms": stats([float(row["latency_first_token_ms"]) for row in ok], len(ok), len(fail)),
        "latency_total_ms": stats([float(row["latency_total_ms"]) for row in ok], len(ok), len(fail)),
        "decode_tokens_per_sec": stats([float(row["decode_tokens_per_sec"]) for row in ok], len(ok), len(fail)),
        "rss_peak_mb": stats([float(row["rss_peak_mb"]) for row in runs], len(runs), 0),
        "fingerprint_distribution": dict(Counter(row["error_fingerprint"] for row in fail if row["error_fingerprint"])),
    }


def create_pipeline(
    model_dir: Path,
    device: str,
    pipeline_config: dict[str, Any] | None,
) -> tuple[Any | None, float | None, dict[str, Any] | None]:
    t0 = time.perf_counter()
    try:
        if pipeline_config is None:
            pipe = ov_genai.LLMPipeline(str(model_dir), device)
        else:
            pipe = ov_genai.LLMPipeline(str(model_dir), device, pipeline_config)
        compile_ms = (time.perf_counter() - t0) * 1000.0
        return pipe, compile_ms, None
    except Exception as exc:  # noqa: BLE001
        return None, None, {
            "message": str(exc),
            "fingerprint": normalize_error("PIPELINE_CREATION_ERROR", str(exc)),
        }


def run_npu_campaign(tokenizer_q25: Any) -> dict[str, Any]:
    campaign: dict[str, Any] = {
        "campaign": "A",
        "name": "NPU with configured MAX_PROMPT_LEN",
        "model": "qwen2.5-1.5b-instruct",
        "device": "NPU",
        "runs_per_point": MEASURED_RUNS,
        "warmup_runs_discarded": WARMUP_RUNS,
        "output_tokens": MAX_NEW_TOKENS,
        "temperature": 0.0,
        "configs": [],
    }

    for max_prompt_len in NPU_CONFIGS:
        pipe_config = {
            "MAX_PROMPT_LEN": max_prompt_len,
            "MIN_RESPONSE_LEN": 512,
            "PREFILL_HINT": "DYNAMIC",
            "GENERATE_HINT": "BEST_PERF",
            "NPUW_LLM_PREFILL_CHUNK_SIZE": 1024,
            "CACHE_DIR": ".npucache",
        }

        config_result: dict[str, Any] = {
            "max_prompt_len": max_prompt_len,
            "pipeline_config": pipe_config,
            "pipeline_creation_ok": False,
            "pipeline_compile_ms": None,
            "pipeline_creation_error": None,
            "points": [],
        }

        pipeline, compile_ms, create_error = create_pipeline(MODEL_QWEN25, "NPU", pipe_config)
        if pipeline is None:
            config_result["pipeline_creation_error"] = create_error
            campaign["configs"].append(config_result)
            gc.collect()
            continue

        config_result["pipeline_creation_ok"] = True
        config_result["pipeline_compile_ms"] = compile_ms

        for band in NPU_PROMPT_BANDS[max_prompt_len]:
            user_content = build_user_content_to_token_len(
                tokenizer_q25,
                band,
                seed="P5-FEASIBILITY-004 NPU MAX_PROMPT_LEN scaling test payload.",
            )
            user_tokens = int(len(tokenizer_q25(user_content, return_tensors="np")["input_ids"][0]))
            prompt = build_qwen25_chat_prompt(user_content)
            formatted_tokens = int(len(tokenizer_q25(prompt, return_tensors="np")["input_ids"][0]))

            for _ in range(WARMUP_RUNS):
                _ = run_single_generation(pipeline, tokenizer_q25, prompt, pipe_config)

            measured_runs = [
                run_single_generation(pipeline, tokenizer_q25, prompt, pipe_config)
                for _ in range(MEASURED_RUNS)
            ]

            point: dict[str, Any] = {
                "prompt_length_user_tokens_target": band,
                "prompt_length_user_tokens_actual": user_tokens,
                "formatted_prompt_tokens": formatted_tokens,
                "runs": measured_runs,
                "summary": summarize_runs(measured_runs),
                "missing_reason": None,
            }
            summary = point["summary"]
            if isinstance(summary, dict) and int(summary.get("valid_count", 0)) == 0:
                point["missing_reason"] = "No successful runs"
            config_result["points"].append(point)

        campaign["configs"].append(config_result)

        pipeline = None
        gc.collect()

    return campaign


def run_gpu_cpu_campaign(tokenizer_q25: Any, tokenizer_q3: Any) -> dict[str, Any]:
    combos = [
        {
            "device": "GPU",
            "model": "qwen2.5-1.5b-instruct",
            "model_path": MODEL_QWEN25,
            "tokenizer": tokenizer_q25,
            "prompt_builder": "qwen25",
        },
        {
            "device": "CPU",
            "model": "qwen2.5-1.5b-instruct",
            "model_path": MODEL_QWEN25,
            "tokenizer": tokenizer_q25,
            "prompt_builder": "qwen25",
        },
        {
            "device": "GPU",
            "model": "qwen3-1.7b",
            "model_path": MODEL_QWEN3,
            "tokenizer": tokenizer_q3,
            "prompt_builder": "qwen3",
        },
        {
            "device": "CPU",
            "model": "qwen3-1.7b",
            "model_path": MODEL_QWEN3,
            "tokenizer": tokenizer_q3,
            "prompt_builder": "qwen3",
        },
    ]

    campaign: dict[str, Any] = {
        "campaign": "B",
        "name": "GPU and CPU generation",
        "runs_per_point": MEASURED_RUNS,
        "warmup_runs_discarded": WARMUP_RUNS,
        "output_tokens": MAX_NEW_TOKENS,
        "temperature": 0.0,
        "combinations": [],
    }

    for combo in combos:
        combo_result: dict[str, Any] = {
            "device": combo["device"],
            "model": combo["model"],
            "model_path": str(combo["model_path"]),
            "pipeline_creation_ok": False,
            "pipeline_compile_ms": None,
            "pipeline_creation_error": None,
            "points": [],
        }

        pipeline, compile_ms, create_error = create_pipeline(combo["model_path"], combo["device"], None)
        if pipeline is None:
            combo_result["pipeline_creation_error"] = create_error
            campaign["combinations"].append(combo_result)
            gc.collect()
            continue

        combo_result["pipeline_creation_ok"] = True
        combo_result["pipeline_compile_ms"] = compile_ms

        tokenizer = combo["tokenizer"]
        for band in GPU_CPU_PROMPT_BANDS:
            user_content = build_user_content_to_token_len(
                tokenizer,
                band,
                seed=f"P5-FEASIBILITY-004 {combo['device']} {combo['model']} generation benchmark payload.",
            )
            user_tokens = int(len(tokenizer(user_content, return_tensors="np")["input_ids"][0]))

            if combo["prompt_builder"] == "qwen25":
                prompt = build_qwen25_chat_prompt(user_content)
            else:
                prompt = build_qwen3_chat_prompt(tokenizer, user_content)

            formatted_tokens = int(len(tokenizer(prompt, return_tensors="np")["input_ids"][0]))

            for _ in range(WARMUP_RUNS):
                _ = run_single_generation(pipeline, tokenizer, prompt, None)

            measured_runs = [
                run_single_generation(pipeline, tokenizer, prompt, None)
                for _ in range(MEASURED_RUNS)
            ]

            point: dict[str, Any] = {
                "prompt_length_user_tokens_target": band,
                "prompt_length_user_tokens_actual": user_tokens,
                "formatted_prompt_tokens": formatted_tokens,
                "runs": measured_runs,
                "summary": summarize_runs(measured_runs),
                "missing_reason": None,
            }
            summary = point["summary"]
            if isinstance(summary, dict) and int(summary.get("valid_count", 0)) == 0:
                point["missing_reason"] = "No successful runs"

            combo_result["points"].append(point)

        campaign["combinations"].append(combo_result)
        pipeline = None
        gc.collect()

    return campaign


def evaluate_dcg(matrix: dict[str, Any]) -> dict[str, Any]:
    npu_configs = matrix["campaigns"]["npu"]["configs"]
    gpu_cpu_combos = matrix["campaigns"]["gpu_cpu"]["combinations"]

    def point_valid_count(point: Any) -> int:
        if not isinstance(point, dict):
            return 0
        summary = point.get("summary")
        if not isinstance(summary, dict):
            return 0
        return int(summary.get("valid_count", 0))

    def check_dcg_01() -> bool:
        for config in npu_configs:
            if not config.get("pipeline_creation_ok"):
                continue
            for point in config.get("points", []):
                if point.get("prompt_length_user_tokens_target") == 512 and point_valid_count(point) >= 5:
                    return True
        for combo in gpu_cpu_combos:
            if not combo.get("pipeline_creation_ok"):
                continue
            for point in combo.get("points", []):
                if point.get("prompt_length_user_tokens_target") == 512 and point_valid_count(point) >= 5:
                    return True
        return False

    def check_dcg_02() -> tuple[bool, bool]:
        tested = [cfg for cfg in npu_configs if cfg.get("pipeline_creation_ok")]
        has_default = any(int(cfg.get("max_prompt_len", -1)) == 1024 for cfg in tested)
        has_ge_2048 = any(int(cfg.get("max_prompt_len", -1)) >= 2048 for cfg in tested)
        enough_configs = len(tested) >= 3 and has_default and has_ge_2048

        npu_2048_runtime_success = False
        for cfg in tested:
            if int(cfg.get("max_prompt_len", -1)) < 2048:
                continue
            for point in cfg.get("points", []):
                if point_valid_count(point) > 0:
                    npu_2048_runtime_success = True
                    break
            if npu_2048_runtime_success:
                break
        return enough_configs, npu_2048_runtime_success

    def check_dcg_03() -> tuple[bool, int]:
        bands = 0
        for combo in gpu_cpu_combos:
            if combo.get("device") != "GPU" or not combo.get("pipeline_creation_ok"):
                continue
            for point in combo.get("points", []):
                if point_valid_count(point) > 0:
                    bands += 1
        return bands >= 3, bands

    def check_dcg_04() -> tuple[bool, int]:
        bands = 0
        for combo in gpu_cpu_combos:
            if combo.get("device") != "CPU" or not combo.get("pipeline_creation_ok"):
                continue
            for point in combo.get("points", []):
                if point_valid_count(point) > 0:
                    bands += 1
        return bands >= 3, bands

    def check_dcg_05() -> bool:
        prompt_map: dict[int, set[str]] = {}
        for config in npu_configs:
            if not config.get("pipeline_creation_ok"):
                continue
            for point in config.get("points", []):
                if point_valid_count(point) > 0:
                    prompt_map.setdefault(int(point["prompt_length_user_tokens_target"]), set()).add("NPU")
        for combo in gpu_cpu_combos:
            if not combo.get("pipeline_creation_ok"):
                continue
            dev = str(combo.get("device"))
            for point in combo.get("points", []):
                if point_valid_count(point) > 0:
                    prompt_map.setdefault(int(point["prompt_length_user_tokens_target"]), set()).add(dev)
        return any(len(devices) >= 2 for devices in prompt_map.values())

    def check_dcg_06() -> tuple[bool, bool, float]:
        max_rss = 0.0
        over_warn = False
        for config in npu_configs:
            for point in config.get("points", []):
                for run in point.get("runs", []):
                    rss = float(run.get("rss_peak_mb", 0.0))
                    max_rss = max(max_rss, rss)
                    if rss > MEMORY_WARN_MB:
                        over_warn = True
        for combo in gpu_cpu_combos:
            for point in combo.get("points", []):
                for run in point.get("runs", []):
                    rss = float(run.get("rss_peak_mb", 0.0))
                    max_rss = max(max_rss, rss)
                    if rss > MEMORY_WARN_MB:
                        over_warn = True
        return True, over_warn, max_rss

    def check_dcg_07() -> tuple[bool, list[str]]:
        qwen3_combos = [c for c in gpu_cpu_combos if c.get("model") == "qwen3-1.7b"]
        errors: list[str] = []
        for combo in qwen3_combos:
            if combo.get("pipeline_creation_ok"):
                for point in combo.get("points", []):
                    if point_valid_count(point) > 0:
                        return True, errors
            err = combo.get("pipeline_creation_error")
            if err is not None:
                errors.append(str(err.get("fingerprint") or err.get("message") or "unknown"))
        return False, errors

    dcg01 = check_dcg_01()
    dcg02, npu_2048_success = check_dcg_02()
    dcg03, gpu_bands = check_dcg_03()
    dcg04, cpu_bands = check_dcg_04()
    dcg05 = check_dcg_05()
    dcg06, mem_warn, max_rss = check_dcg_06()
    dcg07, qwen3_errors = check_dcg_07()

    checks = {
        "DCG-01": {
            "passed": dcg01,
            "detail": "At least one combination had >=5 valid runs at prompt length 512.",
        },
        "DCG-02": {
            "passed": dcg02,
            "detail": "NPU tested with >=3 MAX_PROMPT_LEN values including 1024 and >=2048.",
        },
        "DCG-03": {
            "passed": dcg03,
            "detail": f"GPU valid generation bands: {gpu_bands}",
        },
        "DCG-04": {
            "passed": dcg04,
            "detail": f"CPU valid generation bands: {cpu_bands}",
        },
        "DCG-05": {
            "passed": dcg05,
            "detail": "At least one prompt length has valid results from >=2 devices.",
        },
        "DCG-06": {
            "passed": dcg06,
            "detail": f"Max observed RSS peak MB: {max_rss:.2f}; over_28GB_warning={mem_warn}",
            "warning": "RSS_GT_28GB" if mem_warn else None,
        },
        "DCG-07": {
            "passed": dcg07,
            "detail": "Qwen3 tested on at least GPU or CPU with >=1 successful prompt band.",
            "errors": qwen3_errors,
        },
    }

    if not dcg01:
        disposition = "HARNESS_ERROR"
    elif dcg01 and dcg02 and dcg03 and dcg04 and dcg05:
        disposition = "READY_FOR_ARCH_RECOMMENDATION"
    elif (not dcg03) and (not dcg04) and (not npu_2048_success):
        disposition = "DO_NOT_EXPAND"
    else:
        disposition = "PARTIAL_EVIDENCE"

    overturn_1024_wall = bool(npu_2048_success)

    return {
        "checks": checks,
        "all_required_pass": dcg01 and dcg02 and dcg03 and dcg04 and dcg05,
        "npu_1024_wall_overturned": overturn_1024_wall,
        "disposition": disposition,
    }


def main() -> None:
    power_state = enforce_ac_power_or_fail_closed()
    head = git_head()

    env: dict[str, Any] = {
        "timestamp_utc": now_iso(),
        "commit_hash": head,
        "python_version": sys.version,
        "platform": platform.platform(),
        "openvino_version": getattr(ov, "__version__", "unknown") if ov is not None else "unavailable",
        "openvino_genai_version": getattr(ov_genai, "__version__", "unknown"),
        "available_devices": available_devices(),
        "power_envelope": power_state,
        "run_preconditions": {
            "ac_power_required": True,
            "qwen3_npu_test_allowed": False,
        },
        "model_checks": model_paths_ok(),
    }

    model_checks = env.get("model_checks")
    if not isinstance(model_checks, dict):
        raise RuntimeError("MODEL_ASSET_PRECHECK_FAILED: model check structure invalid")

    if not all(
        isinstance(item, dict)
        and bool(item.get("dir_exists") and item.get("xml_exists") and item.get("bin_exists"))
        for item in model_checks.values()
    ):
        raise RuntimeError("MODEL_ASSET_PRECHECK_FAILED: Missing model directories or OpenVINO model files")

    tokenizer_q25 = AutoTokenizer.from_pretrained(str(MODEL_QWEN25), local_files_only=True)
    tokenizer_q3 = AutoTokenizer.from_pretrained(str(MODEL_QWEN3), local_files_only=True)

    matrix: dict[str, Any] = {
        "milestone": "P5-FEASIBILITY-004",
        "timestamp_utc": now_iso(),
        "metadata": env,
        "benchmark_policy": {
            "runs_per_point_measured": MEASURED_RUNS,
            "warmup_runs_discarded": WARMUP_RUNS,
            "max_new_tokens": MAX_NEW_TOKENS,
            "temperature": 0.0,
            "notes": [
                "NPU campaign uses explicit MAX_PROMPT_LEN and fresh pipeline per config.",
                "GPU/CPU campaign uses default dynamic shape behavior with no MAX_PROMPT_LEN override.",
                "Qwen3 intentionally excluded from NPU testing per milestone constraints.",
            ],
        },
        "campaigns": {},
        "quality_gate": {},
    }

    matrix["campaigns"]["npu"] = run_npu_campaign(tokenizer_q25)
    matrix["campaigns"]["gpu_cpu"] = run_gpu_cpu_campaign(tokenizer_q25, tokenizer_q3)
    matrix["quality_gate"] = evaluate_dcg(matrix)

    write_json(OUTPUT_JSON, matrix)

    print(
        json.dumps(
            {
                "status": "ok",
                "artifact": str(OUTPUT_JSON),
                "disposition": matrix["quality_gate"]["disposition"],
                "npu_1024_wall_overturned": matrix["quality_gate"]["npu_1024_wall_overturned"],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
