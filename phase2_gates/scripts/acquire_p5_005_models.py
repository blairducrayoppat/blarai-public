from __future__ import annotations

import datetime as dt
import gc
import hashlib
import json
import platform
import shutil
import subprocess
import sys
import time
import warnings
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import psutil

try:
    import openvino as ov
except Exception:  # noqa: BLE001
    ov = None  # type: ignore[assignment]

import openvino_genai as ov_genai
from transformers import AutoTokenizer

try:
    import huggingface_hub
except Exception:  # noqa: BLE001
    huggingface_hub = None  # type: ignore[assignment]


EVIDENCE_DIR = ROOT / "phase2_gates" / "evidence"
OUTPUT_JSON = EVIDENCE_DIR / "p5_005_model_acquisition.json"

MODEL_LAYOUT: dict[str, dict[str, Any]] = {
    "qwen3-14b": {
        "hf_id": "Qwen/Qwen3-14B",
        "output_dir": ROOT / "models" / "qwen3-14b" / "openvino-int4-gpu",
        "size_min_mb": 6500.0,
        "size_max_mb": 9000.0,
        "quantization_config": {
            "bits": 4,
            "sym": False,
            "group_size": 128,
            "ratio": 1.0,
            "scale_estimation": True,
            "dataset": "wikitext2",
        },
    },
    "qwen3-8b": {
        "hf_id": "Qwen/Qwen3-8B",
        "output_dir": ROOT / "models" / "qwen3-8b" / "openvino-int4-gpu",
        "size_min_mb": 3500.0,
        "size_max_mb": 5500.0,
        "quantization_config": {
            "bits": 4,
            "sym": False,
            "group_size": 128,
            "ratio": 1.0,
            "scale_estimation": True,
            "dataset": "wikitext2",
        },
    },
    "qwen3-0.6b": {
        "hf_id": "Qwen/Qwen3-0.6B",
        "output_dir": ROOT / "models" / "qwen3-0.6b" / "openvino-int4-gpu",
        "size_min_mb": 300.0,
        "size_max_mb": 600.0,
        "quantization_config": {
            "bits": 4,
            "sym": False,
            "group_size": 128,
            "ratio": 1.0,
        },
    },
}


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


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        while True:
            chunk = handle.read(1 << 20)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def dir_has_required_files(path: Path) -> bool:
    return (path / "openvino_model.xml").exists() and (path / "openvino_model.bin").exists()


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
        raise RuntimeError("POWER_ENVELOPE_NOT_LOCKED: AC power required for P5-005 acquisition phase")
    return state


def free_disk_gb(path: str = "C:\\") -> float:
    usage = psutil.disk_usage(path)
    return float(usage.free) / (1024**3)


def quick_inference_smoke(model_dir: Path) -> dict[str, Any]:
    prompt = "Give one short sentence confirming offline benchmark readiness."
    t0 = time.perf_counter()
    pipe = ov_genai.LLMPipeline(str(model_dir), "GPU")
    config = ov_genai.GenerationConfig()
    config.max_new_tokens = 10
    config.do_sample = False
    try:
        config.temperature = 0.0
        config.top_p = 1.0
        config.top_k = 1
    except Exception:
        pass

    output = pipe.generate(prompt, config)
    elapsed_ms = (time.perf_counter() - t0) * 1000.0
    text = str(output).strip()

    del pipe
    gc.collect()
    time.sleep(1)

    if not text:
        raise RuntimeError("QUICK_INFERENCE_EMPTY_OUTPUT")

    return {
        "ok": True,
        "latency_total_ms": elapsed_ms,
        "output_preview": text[:300],
    }


def export_openvino_model(model_key: str, spec: dict[str, Any]) -> dict[str, Any]:
    output_dir = Path(spec["output_dir"])
    output_dir.mkdir(parents=True, exist_ok=True)

    t0 = time.perf_counter()
    status = "cached" if dir_has_required_files(output_dir) else "converted"

    if status == "converted":
        ensure_optimum_openvino_compatibility()
        from optimum.intel import OVModelForCausalLM

        with warnings.catch_warnings():
            warnings.filterwarnings("ignore", category=FutureWarning)
            warnings.filterwarnings("ignore", category=DeprecationWarning)
            model = OVModelForCausalLM.from_pretrained(
                spec["hf_id"],
                export=True,
                compile=False,
                load_in_4bit=True,
                quantization_config=spec["quantization_config"],
            )
        model.save_pretrained(str(output_dir))
        tokenizer = AutoTokenizer.from_pretrained(spec["hf_id"])
        tokenizer.save_pretrained(str(output_dir))

    elapsed_s = time.perf_counter() - t0
    xml_path = output_dir / "openvino_model.xml"
    bin_path = output_dir / "openvino_model.bin"

    checks: dict[str, Any] = {
        "xml_exists": xml_path.exists(),
        "bin_exists": bin_path.exists(),
    }

    if not checks["xml_exists"] or not checks["bin_exists"]:
        raise RuntimeError(f"MODEL_EXPORT_INCOMPLETE_{model_key.upper()}")

    bin_size_mb = float(bin_path.stat().st_size) / (1024**2)
    size_ok = float(spec["size_min_mb"]) <= bin_size_mb <= float(spec["size_max_mb"])

    smoke: dict[str, Any]
    try:
        smoke = quick_inference_smoke(output_dir)
    except Exception as exc:  # noqa: BLE001
        smoke = {
            "ok": False,
            "error": str(exc),
        }

    return {
        "model": model_key,
        "hf_id": spec["hf_id"],
        "output_dir": str(output_dir),
        "status": status,
        "elapsed_s": round(elapsed_s, 2),
        "quantization_config": spec["quantization_config"],
        "checks": checks,
        "bin_size_mb": round(bin_size_mb, 2),
        "bin_size_expected_mb": {
            "min": spec["size_min_mb"],
            "max": spec["size_max_mb"],
            "within_expected_range": size_ok,
        },
        "sha256": {
            "openvino_model.bin": sha256_file(bin_path),
            "openvino_model.xml": sha256_file(xml_path),
        },
        "quick_inference": smoke,
    }


def investigate_eagle3_candidates(limit: int = 30) -> dict[str, Any]:
    if huggingface_hub is None:
        return {
            "api_available": False,
            "error": "huggingface_hub_not_installed",
            "queries": [],
        }

    api = huggingface_hub.HfApi()
    queries = ["eagle3 qwen3", "eagle-3 qwen3", "EAGLE3_Qwen3", "qwen3 draft head"]
    entries: list[dict[str, Any]] = []

    for query in queries:
        q0 = time.perf_counter()
        try:
            models = list(api.list_models(search=query, limit=limit))
            elapsed = (time.perf_counter() - q0) * 1000.0
            entries.append(
                {
                    "query": query,
                    "ok": True,
                    "elapsed_ms": round(elapsed, 2),
                    "matches": [
                        {
                            "id": m.id,
                            "sha": getattr(m, "sha", None),
                            "downloads": getattr(m, "downloads", None),
                            "likes": getattr(m, "likes", None),
                        }
                        for m in models
                    ],
                }
            )
        except Exception as exc:  # noqa: BLE001
            elapsed = (time.perf_counter() - q0) * 1000.0
            entries.append(
                {
                    "query": query,
                    "ok": False,
                    "elapsed_ms": round(elapsed, 2),
                    "error": str(exc),
                    "matches": [],
                }
            )

    flattened_ids = [m["id"] for e in entries if e.get("ok") for m in e.get("matches", []) if isinstance(m, dict)]
    lower_ids = [value.lower() for value in flattened_ids]

    found_8b = any("qwen3" in value and "8b" in value and "eagle" in value for value in lower_ids)
    found_14b = any("qwen3" in value and "14b" in value and "eagle" in value for value in lower_ids)

    return {
        "api_available": True,
        "queries": entries,
        "draft_head_inference": {
            "qwen3_8b_candidate_found": found_8b,
            "qwen3_14b_candidate_found": found_14b,
            "total_unique_ids": len(set(flattened_ids)),
        },
        "recommendation": {
            "t07_status": "candidate_found" if found_8b else "EAGLE3_DRAFT_NOT_AVAILABLE",
            "t05_status": "candidate_found" if found_14b else "EAGLE3_14B_DRAFT_NOT_AVAILABLE",
        },
    }


def detect_genai_capabilities() -> dict[str, Any]:
    llm_attrs = dir(ov_genai.LLMPipeline)
    gen_attrs = dir(ov_genai.GenerationConfig)

    gpu_supported_props: list[str] = []
    if ov is not None:
        try:
            core = ov.Core()
            gpu_supported_props = list(core.get_property("GPU", "SUPPORTED_PROPERTIES"))
        except Exception:
            gpu_supported_props = []

    return {
        "openvino_genai_version": getattr(ov_genai, "__version__", "unknown"),
        "draft_model_api_present": hasattr(ov_genai, "draft_model"),
        "generation_config_has_assistant_fields": any(
            key in gen_attrs for key in ["assistant_confidence_threshold", "num_assistant_tokens", "is_assisting_generation"]
        ),
        "generation_config_assistant_fields": [
            key for key in ["assistant_confidence_threshold", "num_assistant_tokens", "is_assisting_generation"] if key in gen_attrs
        ],
        "gpu_supported_properties": gpu_supported_props,
        "kv_cache_precision_property_present": "KV_CACHE_PRECISION" in gpu_supported_props,
        "xattention_property_candidates": [
            key for key in gpu_supported_props if "SDPA" in key or "XATTENTION" in key or "SPARSE" in key
        ],
    }


def ensure_optimum_openvino_compatibility() -> None:
    try:
        import optimum.exporters.onnx.model_patcher as onnx_model_patcher
    except Exception:
        return

    if hasattr(onnx_model_patcher, "sdpa_mask_without_vmap"):
        return

    def _sdpa_mask_without_vmap(*args: Any, **kwargs: Any) -> Any:
        prepare_mask = getattr(onnx_model_patcher, "_prepare_4d_causal_attention_mask_for_sdpa", None)
        if callable(prepare_mask):
            return prepare_mask(*args, **kwargs)
        raise RuntimeError("sdpa_mask_without_vmap compatibility shim unavailable")

    setattr(onnx_model_patcher, "sdpa_mask_without_vmap", _sdpa_mask_without_vmap)


def environment_metadata() -> dict[str, Any]:
    disk = shutil.disk_usage("C:\\")
    optimum_check: dict[str, Any] = {"importable": False, "error": None}
    try:
        ensure_optimum_openvino_compatibility()
        from optimum.intel import OVModelForCausalLM as _OVModelForCausalLM  # noqa: F401

        optimum_check = {"importable": True, "error": None}
    except Exception as exc:  # noqa: BLE001
        optimum_check = {"importable": False, "error": str(exc)}

    return {
        "timestamp_utc": now_iso(),
        "commit_hash": git_head(),
        "platform": platform.platform(),
        "python": sys.version,
        "openvino_version": getattr(ov, "__version__", "unavailable") if ov is not None else "unavailable",
        "openvino_genai_version": getattr(ov_genai, "__version__", "unknown"),
        "optimum_intel": optimum_check,
        "available_devices": list(ov.Core().available_devices) if ov is not None else [],
        "ac_power": enforce_ac_power_or_fail_closed(),
        "disk": {
            "path": "C:\\",
            "free_bytes": int(disk.free),
            "free_gb": round(float(disk.free) / (1024**3), 2),
            "required_min_gb": 20.0,
            "requirement_met": float(disk.free) / (1024**3) >= 20.0,
        },
    }


def main() -> None:
    metadata = environment_metadata()
    if not metadata["disk"]["requirement_met"]:
        raise RuntimeError("DISK_SPACE_INSUFFICIENT: Require at least 20GB free on C:\\")

    evidence: dict[str, Any] = {
        "milestone": "P5-FEASIBILITY-005",
        "phase": "1",
        "name": "Environment setup and model acquisition",
        "metadata": metadata,
        "feature_discovery": detect_genai_capabilities(),
        "models": [],
        "eagle3_investigation": {},
        "status": "in_progress",
        "started_utc": now_iso(),
    }
    write_json_atomic(OUTPUT_JSON, evidence)

    optimum_ok = bool(metadata.get("optimum_intel", {}).get("importable"))
    if not optimum_ok:
        for model_key in ["qwen3-14b", "qwen3-8b", "qwen3-0.6b"]:
            spec = MODEL_LAYOUT[model_key]
            evidence["models"].append(
                {
                    "model": model_key,
                    "hf_id": spec["hf_id"],
                    "output_dir": str(spec["output_dir"]),
                    "status": "failed",
                    "error": f"OPTIMUM_IMPORT_ERROR: {metadata.get('optimum_intel', {}).get('error')}",
                }
            )
        evidence["eagle3_investigation"] = investigate_eagle3_candidates()
        evidence["status"] = "blocked"
        evidence["failure_reason"] = "OPTIMUM_INTEL_IMPORT_FAILED"
        evidence["finished_utc"] = now_iso()
        write_json_atomic(OUTPUT_JSON, evidence)
        print(json.dumps({"status": "blocked", "artifact": str(OUTPUT_JSON), "reason": evidence["failure_reason"]}, indent=2))
        return

    model_results: list[dict[str, Any]] = []
    for model_key in ["qwen3-14b", "qwen3-8b", "qwen3-0.6b"]:
        spec = MODEL_LAYOUT[model_key]
        try:
            result = export_openvino_model(model_key, spec)
            model_results.append(result)
        except Exception as exc:  # noqa: BLE001
            model_results.append(
                {
                    "model": model_key,
                    "hf_id": spec["hf_id"],
                    "output_dir": str(spec["output_dir"]),
                    "status": "failed",
                    "error": str(exc),
                }
            )
        evidence["models"] = model_results
        write_json_atomic(OUTPUT_JSON, evidence)

    evidence["eagle3_investigation"] = investigate_eagle3_candidates()
    evidence["status"] = "completed"
    evidence["finished_utc"] = now_iso()
    write_json_atomic(OUTPUT_JSON, evidence)

    print(json.dumps({"status": "ok", "artifact": str(OUTPUT_JSON)}, indent=2))


if __name__ == "__main__":
    main()
