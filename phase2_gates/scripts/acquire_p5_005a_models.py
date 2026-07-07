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
    from openvino_tokenizers import convert_tokenizer
except Exception:  # noqa: BLE001
    convert_tokenizer = None  # type: ignore[assignment]

try:
    import huggingface_hub
except Exception:  # noqa: BLE001
    huggingface_hub = None  # type: ignore[assignment]


EVIDENCE_DIR = ROOT / "phase2_gates" / "evidence"
OUTPUT_JSON = EVIDENCE_DIR / "p5_005a_model_acquisition.json"
PRIOR_ACQ_JSON = EVIDENCE_DIR / "p5_005_model_acquisition.json"

MODEL_LAYOUT: dict[str, dict[str, Any]] = {
    "qwen3-14b": {
        "hf_id": "Qwen/Qwen3-14B",
        "output_dir": ROOT / "models" / "qwen3-14b" / "openvino-int4-gpu",
        "size_min_mb": 6500.0,
        "size_max_mb": 9000.0,
        "quantization_config_default": {
            "bits": 4,
            "sym": False,
            "group_size": 128,
            "ratio": 1.0,
            "scale_estimation": True,
            "dataset": "wikitext2",
        },
        "quantization_config_light": {
            "bits": 4,
            "sym": False,
            "group_size": 128,
            "ratio": 1.0,
        },
        "optimum_cli_calibration_samples": 32,
    },
    "qwen3-8b": {
        "hf_id": "Qwen/Qwen3-8B",
        "output_dir": ROOT / "models" / "qwen3-8b" / "openvino-int4-gpu",
        "size_min_mb": 3500.0,
        "size_max_mb": 5500.0,
        "quantization_config_default": {
            "bits": 4,
            "sym": False,
            "group_size": 128,
            "ratio": 1.0,
            "scale_estimation": True,
            "dataset": "wikitext2",
        },
        "quantization_config_light": {
            "bits": 4,
            "sym": False,
            "group_size": 128,
            "ratio": 1.0,
        },
        "optimum_cli_calibration_samples": 32,
    },
    "qwen3-0.6b": {
        "hf_id": "Qwen/Qwen3-0.6B",
        "output_dir": ROOT / "models" / "qwen3-0.6b" / "openvino-int4-gpu",
        "size_min_mb": 300.0,
        "size_max_mb": 600.0,
        "quantization_config_default": {
            "bits": 4,
            "sym": False,
            "group_size": 128,
            "ratio": 1.0,
        },
        "quantization_config_light": {
            "bits": 4,
            "sym": False,
            "group_size": 128,
            "ratio": 1.0,
        },
        "optimum_cli_calibration_samples": 16,
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


def read_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    with open(path, "r", encoding="utf-8") as handle:
        payload = json.load(handle)
    return payload if isinstance(payload, dict) else None


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
        raise RuntimeError("POWER_ENVELOPE_NOT_LOCKED: AC power required for P5-005a acquisition phase")
    return state


def list_python_processes() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for proc in psutil.process_iter(["pid", "name", "create_time", "memory_info", "cmdline"]):
        try:
            info = proc.info
            name = str(info.get("name", "")).lower()
            if "python" not in name:
                continue
            cmdline = info.get("cmdline") or []
            rows.append(
                {
                    "pid": int(info["pid"]),
                    "name": info.get("name"),
                    "create_time_utc": dt.datetime.fromtimestamp(float(info.get("create_time", 0.0)), tz=dt.timezone.utc).isoformat(),
                    "rss_mb": round(float(getattr(info.get("memory_info"), "rss", 0.0)) / (1024**2), 2),
                    "command_line": " ".join(str(x) for x in cmdline),
                }
            )
        except Exception:
            continue
    return rows


def free_disk_gb(path: str = "C:\\") -> float:
    usage = psutil.disk_usage(path)
    return float(usage.free) / (1024**3)


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


def quick_inference_smoke(model_dir: Path, device: str, max_prompt_len: int | None = None) -> dict[str, Any]:
    prompt = "Give one short sentence confirming offline benchmark readiness."
    t0 = time.perf_counter()
    config_kwargs: dict[str, Any] = {}
    if max_prompt_len is not None:
        config_kwargs["MAX_PROMPT_LEN"] = int(max_prompt_len)

    ensure_openvino_tokenizer_assets(model_dir)

    pipe = ov_genai.LLMPipeline(str(model_dir), device, config_kwargs)
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
        "device": device,
        "latency_total_ms": elapsed_ms,
        "output_preview": text[:300],
    }


def model_integrity_snapshot(path: Path, spec: dict[str, Any]) -> dict[str, Any]:
    xml_path = path / "openvino_model.xml"
    bin_path = path / "openvino_model.bin"
    checks = {
        "dir_exists": path.exists(),
        "xml_exists": xml_path.exists(),
        "bin_exists": bin_path.exists(),
    }
    if not checks["xml_exists"] or not checks["bin_exists"]:
        return {"checks": checks}

    bin_size_mb = float(bin_path.stat().st_size) / (1024**2)
    return {
        "checks": checks,
        "tokenizer_xml_exists": (path / "openvino_tokenizer.xml").exists(),
        "tokenizer_bin_exists": (path / "openvino_tokenizer.bin").exists(),
        "detokenizer_xml_exists": (path / "openvino_detokenizer.xml").exists(),
        "detokenizer_bin_exists": (path / "openvino_detokenizer.bin").exists(),
        "bin_size_mb": round(bin_size_mb, 2),
        "bin_size_expected_mb": {
            "min": spec["size_min_mb"],
            "max": spec["size_max_mb"],
            "within_expected_range": float(spec["size_min_mb"]) <= bin_size_mb <= float(spec["size_max_mb"]),
        },
        "sha256": {
            "openvino_model.bin": sha256_file(bin_path),
            "openvino_model.xml": sha256_file(xml_path),
        },
    }


def ensure_openvino_tokenizer_assets(model_dir: Path) -> None:
    tok_xml = model_dir / "openvino_tokenizer.xml"
    tok_bin = model_dir / "openvino_tokenizer.bin"
    detok_xml = model_dir / "openvino_detokenizer.xml"
    detok_bin = model_dir / "openvino_detokenizer.bin"

    if tok_xml.exists() and tok_bin.exists() and detok_xml.exists() and detok_bin.exists():
        return

    if convert_tokenizer is None or ov is None:
        raise RuntimeError("OPENVINO_TOKENIZER_CONVERTER_NOT_AVAILABLE")

    tokenizer = AutoTokenizer.from_pretrained(str(model_dir), local_files_only=True)
    tok_model, detok_model = convert_tokenizer(tokenizer, with_detokenizer=True)
    ov.save_model(tok_model, str(tok_xml))
    ov.save_model(detok_model, str(detok_xml))


def search_prequantized_openvino_model(hf_id: str, output_dir: Path) -> dict[str, Any]:
    if huggingface_hub is None:
        raise RuntimeError("HUGGINGFACE_HUB_NOT_AVAILABLE")

    api = huggingface_hub.HfApi()
    query = f"{hf_id.split('/')[-1]} openvino int4"
    models = list(api.list_models(search=query, limit=50))
    candidates = [m for m in models if m.id and "qwen3" in m.id.lower() and "openvino" in m.id.lower()]

    if not candidates:
        raise RuntimeError("NO_PREQUANTIZED_OPENVINO_INT4_CANDIDATE_FOUND")

    selected = candidates[0]
    output_dir.mkdir(parents=True, exist_ok=True)
    downloaded = huggingface_hub.snapshot_download(
        repo_id=selected.id,
        local_dir=str(output_dir),
        local_dir_use_symlinks=False,
        allow_patterns=["*openvino_model.xml", "*openvino_model.bin", "*.json", "tokenizer*", "*.model", "*.txt"],
    )

    return {
        "selected_repo": selected.id,
        "download_path": downloaded,
        "query": query,
        "candidate_count": len(candidates),
    }


def export_with_optimum_cli(hf_id: str, output_dir: Path, num_calibration_samples: int) -> dict[str, Any]:
    cmd = [
        str(ROOT / ".venv" / "Scripts" / "optimum-cli.exe"),
        "export",
        "openvino",
        "--model",
        hf_id,
        "--weight-format",
        "int4",
        "--group-size",
        "128",
        "--ratio",
        "1.0",
        "--sym",
        "false",
        "--num-calibration-samples",
        str(num_calibration_samples),
        str(output_dir),
    ]
    t0 = time.perf_counter()
    proc = subprocess.run(cmd, cwd=ROOT, text=True, capture_output=True, check=False)
    elapsed_s = time.perf_counter() - t0
    if proc.returncode != 0:
        raise RuntimeError(f"OPTIMUM_CLI_EXPORT_FAILED: rc={proc.returncode} stderr={proc.stderr[-1200:]}")
    return {
        "elapsed_s": round(elapsed_s, 2),
        "stdout_tail": proc.stdout[-2000:],
    }


def export_with_python_api(hf_id: str, output_dir: Path, quantization_config: dict[str, Any]) -> dict[str, Any]:
    ensure_optimum_openvino_compatibility()
    from optimum.intel import OVModelForCausalLM

    t0 = time.perf_counter()
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", category=FutureWarning)
        warnings.filterwarnings("ignore", category=DeprecationWarning)
        model = OVModelForCausalLM.from_pretrained(
            hf_id,
            export=True,
            compile=False,
            load_in_4bit=True,
            quantization_config=quantization_config,
        )
    model.save_pretrained(str(output_dir))
    tokenizer = AutoTokenizer.from_pretrained(hf_id)
    tokenizer.save_pretrained(str(output_dir))
    elapsed_s = time.perf_counter() - t0
    return {"elapsed_s": round(elapsed_s, 2)}


def acquire_model_with_strategies(model_key: str, spec: dict[str, Any]) -> dict[str, Any]:
    output_dir = Path(spec["output_dir"])
    output_dir.mkdir(parents=True, exist_ok=True)

    attempts: list[dict[str, Any]] = []
    initial = model_integrity_snapshot(output_dir, spec)
    if bool(initial.get("checks", {}).get("xml_exists") and initial.get("checks", {}).get("bin_exists")):
        try:
            smoke = quick_inference_smoke(output_dir, "GPU")
            return {
                "model": model_key,
                "hf_id": spec["hf_id"],
                "output_dir": str(output_dir),
                "device_target": "GPU",
                "status": "cached",
                "strategy": "cached",
                **initial,
                "quick_inference": smoke,
            }
        except Exception as exc:  # noqa: BLE001
            attempts.append(
                {
                    "strategy": "cached",
                    "status": "failed",
                    "error": f"CACHED_MODEL_SMOKE_FAILED: {exc}",
                    "timestamp_utc": now_iso(),
                }
            )

    for strategy_name in ["A_PREQUANTIZED", "B_OPTIMUM_CLI_REDUCED_CALIBRATION", "C_PYTHON_WEIGHT_ONLY"]:
        try:
            if strategy_name == "A_PREQUANTIZED":
                details = search_prequantized_openvino_model(spec["hf_id"], output_dir)
            elif strategy_name == "B_OPTIMUM_CLI_REDUCED_CALIBRATION":
                details = export_with_optimum_cli(
                    spec["hf_id"],
                    output_dir,
                    int(spec.get("optimum_cli_calibration_samples", 32)),
                )
            else:
                details = export_with_python_api(spec["hf_id"], output_dir, dict(spec["quantization_config_light"]))

            snap = model_integrity_snapshot(output_dir, spec)
            if not bool(snap.get("checks", {}).get("xml_exists") and snap.get("checks", {}).get("bin_exists")):
                raise RuntimeError("MODEL_EXPORT_INCOMPLETE")

            smoke = quick_inference_smoke(output_dir, "GPU")
            return {
                "model": model_key,
                "hf_id": spec["hf_id"],
                "output_dir": str(output_dir),
                "device_target": "GPU",
                "status": "converted",
                "strategy": strategy_name,
                "strategy_details": details,
                "attempts": attempts,
                **snap,
                "quick_inference": smoke,
            }
        except Exception as exc:  # noqa: BLE001
            attempts.append(
                {
                    "strategy": strategy_name,
                    "status": "failed",
                    "error": str(exc),
                    "timestamp_utc": now_iso(),
                }
            )

    return {
        "model": model_key,
        "hf_id": spec["hf_id"],
        "output_dir": str(output_dir),
        "device_target": "GPU",
        "status": "failed",
        "strategy": "D_ACQUISITION_FAILED",
        "attempts": attempts,
    }


def ensure_06b_npu_variant() -> dict[str, Any]:
    gpu_dir = ROOT / "models" / "qwen3-0.6b" / "openvino-int4-gpu"
    npu_dir = ROOT / "models" / "qwen3-0.6b" / "openvino-int4-npu"
    npu_dir.mkdir(parents=True, exist_ok=True)

    if not dir_has_required_files(gpu_dir):
        return {
            "model": "qwen3-0.6b-npu",
            "status": "failed",
            "error": "GPU_VARIANT_MISSING_FOR_NPU_COPY",
            "output_dir": str(npu_dir),
        }

    copied: list[str] = []
    for name in ["openvino_model.xml", "openvino_model.bin", "config.json", "generation_config.json", "special_tokens_map.json", "tokenizer.json", "tokenizer_config.json", "tokenizer.model", "vocab.json", "merges.txt"]:
        src = gpu_dir / name
        if src.exists():
            dst = npu_dir / name
            shutil.copy2(src, dst)
            copied.append(name)

    snap = model_integrity_snapshot(npu_dir, MODEL_LAYOUT["qwen3-0.6b"])

    return {
        "model": "qwen3-0.6b-npu",
        "status": "copied_unvalidated",
        "strategy": "COPY_GPU_VARIANT_AND_NPU_COMPILE",
        "device_target": "NPU",
        "output_dir": str(npu_dir),
        "copied_files": copied,
        "npu_validation": {
            "status": "skipped",
            "reason": "NPU_RUNTIME_VALIDATION_SKIPPED_TO_AVOID_FATAL_COMPILER_ABORT",
        },
        **snap,
    }


def verify_existing_17b_assets() -> dict[str, Any]:
    gpu_path = ROOT / "models" / "qwen3-1.7b" / "openvino-int4"
    npu_path = ROOT / "models" / "qwen3-1.7b" / "openvino-int4-npu"

    gpu_checks = {
        "path": str(gpu_path),
        "xml_exists": (gpu_path / "openvino_model.xml").exists(),
        "bin_exists": (gpu_path / "openvino_model.bin").exists(),
    }
    npu_checks = {
        "path": str(npu_path),
        "xml_exists": (npu_path / "openvino_model.xml").exists(),
        "bin_exists": (npu_path / "openvino_model.bin").exists(),
    }

    return {
        "model": "qwen3-1.7b",
        "status": "verified" if all([gpu_checks["xml_exists"], gpu_checks["bin_exists"], npu_checks["xml_exists"], npu_checks["bin_exists"]]) else "failed",
        "gpu_variant": gpu_checks,
        "npu_variant": npu_checks,
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
        "milestone": "P5-FEASIBILITY-005a",
        "phase": "1",
        "name": "Model acquisition and blocker resolution",
        "metadata": metadata,
        "phase0_state": {
            "python_processes": list_python_processes(),
            "prior_acquisition_artifact": read_json(PRIOR_ACQ_JSON),
        },
        "models": [],
        "npu_variant": {},
        "existing_assets": {},
        "eagle3_investigation": {},
        "status": "in_progress",
        "started_utc": now_iso(),
    }
    write_json_atomic(OUTPUT_JSON, evidence)

    for model_key in ["qwen3-14b", "qwen3-8b", "qwen3-0.6b"]:
        result = acquire_model_with_strategies(model_key, MODEL_LAYOUT[model_key])
        evidence["models"].append(result)
        write_json_atomic(OUTPUT_JSON, evidence)

    try:
        evidence["npu_variant"] = ensure_06b_npu_variant()
    except Exception as exc:  # noqa: BLE001
        evidence["npu_variant"] = {
            "model": "qwen3-0.6b-npu",
            "status": "failed",
            "error": str(exc),
        }
    write_json_atomic(OUTPUT_JSON, evidence)

    evidence["existing_assets"] = verify_existing_17b_assets()
    evidence["eagle3_investigation"] = investigate_eagle3_candidates()

    statuses = [str(item.get("status")) for item in evidence["models"] if isinstance(item, dict)]
    all_failed = all(status == "failed" for status in statuses) if statuses else True
    evidence["status"] = "blocked" if all_failed else "completed"
    evidence["failure_reason"] = "MODEL_ACQUISITION_ALL_FAILED" if all_failed else None
    evidence["finished_utc"] = now_iso()
    write_json_atomic(OUTPUT_JSON, evidence)

    print(json.dumps({"status": evidence["status"], "artifact": str(OUTPUT_JSON)}, indent=2))


if __name__ == "__main__":
    main()
