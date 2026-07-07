from __future__ import annotations

import datetime as dt
import json
import os
import platform
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    import huggingface_hub
except Exception:  # noqa: BLE001
    huggingface_hub = None  # type: ignore[assignment]

try:
    import openvino_genai as ov_genai
except Exception:  # noqa: BLE001
    ov_genai = None  # type: ignore[assignment]

EVIDENCE_DIR = ROOT / "phase2_gates" / "evidence"
OUTPUT_JSON = EVIDENCE_DIR / "p5_005a_eagle3_acquisition.json"

TARGETS: dict[str, dict[str, Any]] = {
    "8b": {
        "target_model": ROOT / "models" / "qwen3-8b" / "openvino-int4-gpu",
        "raw_dir": ROOT / "models" / "eagle3-qwen3-8b-raw",
        "final_dir": ROOT / "models" / "eagle3-qwen3-8b",
        "primary_repo": "RedHatAI/Qwen3-8B-speculator.eagle3",
        "fallback_repo": "AngelSlim/Qwen3-8B_eagle3",
    },
    "14b": {
        "target_model": ROOT / "models" / "qwen3-14b" / "openvino-int4-gpu",
        "raw_dir": ROOT / "models" / "eagle3-qwen3-14b-raw",
        "final_dir": ROOT / "models" / "eagle3-qwen3-14b",
        "primary_repo": "AngelSlim/Qwen3-14B_eagle3",
        "fallback_repo": "RedHatAI/Qwen3-14B-speculator.eagle3",
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


def ac_power_state() -> dict[str, Any]:
    try:
        import psutil  # noqa: PLC0415

        battery = psutil.sensors_battery()
    except Exception as exc:  # noqa: BLE001
        return {
            "sensor_available": False,
            "power_plugged": None,
            "battery_percent": None,
            "error": str(exc),
        }

    if battery is None:
        return {
            "sensor_available": False,
            "power_plugged": None,
            "battery_percent": None,
            "error": None,
        }

    return {
        "sensor_available": True,
        "power_plugged": bool(battery.power_plugged),
        "battery_percent": float(battery.percent) if battery.percent is not None else None,
        "error": None,
    }


def list_files_snapshot(path: Path, max_entries: int = 300) -> list[dict[str, Any]]:
    if not path.exists():
        return []

    rows: list[dict[str, Any]] = []
    for file_path in sorted(path.rglob("*")):
        if not file_path.is_file():
            continue
        rel = file_path.relative_to(path).as_posix()
        rows.append(
            {
                "path": rel,
                "size_bytes": int(file_path.stat().st_size),
            }
        )
        if len(rows) >= max_entries:
            break
    return rows


def read_config_info(path: Path) -> dict[str, Any]:
    config_path = path / "config.json"
    if not config_path.exists():
        return {
            "exists": False,
            "error": None,
            "model_type": None,
            "architectures": [],
            "raw": None,
        }

    try:
        with open(config_path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except Exception as exc:  # noqa: BLE001
        return {
            "exists": True,
            "error": str(exc),
            "model_type": None,
            "architectures": [],
            "raw": None,
        }

    return {
        "exists": True,
        "error": None,
        "model_type": payload.get("model_type"),
        "architectures": payload.get("architectures", []),
        "raw": payload,
    }


def detect_weight_format(path: Path) -> dict[str, Any]:
    files = [p.name for p in path.glob("*") if p.is_file()]
    return {
        "has_safetensors": any(name.endswith(".safetensors") for name in files),
        "has_pytorch_bin": "pytorch_model.bin" in files,
        "has_openvino_ir": (path / "openvino_model.xml").exists() and (path / "openvino_model.bin").exists(),
        "file_count": len(files),
    }


def ensure_clean_dir(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)


def download_repo(repo_id: str, output_dir: Path) -> dict[str, Any]:
    if huggingface_hub is None:
        return {"ok": False, "error": "HUGGINGFACE_HUB_NOT_AVAILABLE", "repo": repo_id}

    ensure_clean_dir(output_dir)
    t0 = time.perf_counter()

    try:
        download_path = huggingface_hub.snapshot_download(
            repo_id=repo_id,
            local_dir=str(output_dir),
            local_dir_use_symlinks=False,
        )
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False,
            "repo": repo_id,
            "elapsed_s": round(time.perf_counter() - t0, 2),
            "error": str(exc),
        }

    info = {
        "ok": True,
        "repo": repo_id,
        "download_path": download_path,
        "elapsed_s": round(time.perf_counter() - t0, 2),
        "files": list_files_snapshot(output_dir),
        "config": read_config_info(output_dir),
        "weights": detect_weight_format(output_dir),
    }

    try:
        api = huggingface_hub.HfApi()
        model_info = api.model_info(repo_id)
        info["repo_sha"] = model_info.sha
    except Exception as exc:  # noqa: BLE001
        info["repo_sha"] = None
        info["repo_sha_error"] = str(exc)

    return info


def run_optimum_export(model_source: Path, destination: Path) -> dict[str, Any]:
    destination.mkdir(parents=True, exist_ok=True)
    optimum_cli = ROOT / ".venv" / "Scripts" / "optimum-cli.exe"
    if not optimum_cli.exists():
        return {
            "ok": False,
            "method": "optimum-cli",
            "error": f"OPTIMUM_CLI_NOT_FOUND:{optimum_cli}",
        }

    cmd = [
        str(optimum_cli),
        "export",
        "openvino",
        "--model",
        str(model_source),
        str(destination),
    ]

    t0 = time.perf_counter()
    proc = subprocess.run(cmd, cwd=ROOT, text=True, capture_output=True, check=False)
    elapsed_s = round(time.perf_counter() - t0, 2)

    return {
        "ok": proc.returncode == 0,
        "method": "optimum-cli",
        "returncode": proc.returncode,
        "elapsed_s": elapsed_s,
        "stdout_tail": proc.stdout[-4000:],
        "stderr_tail": proc.stderr[-4000:],
        "has_ir": (destination / "openvino_model.xml").exists() and (destination / "openvino_model.bin").exists(),
    }


def try_direct_draft_load(draft_path: Path) -> dict[str, Any]:
    if ov_genai is None:
        return {
            "ok": False,
            "method": "ov_genai.draft_model",
            "error": "OPENVINO_GENAI_NOT_AVAILABLE",
        }

    t0 = time.perf_counter()
    try:
        model = ov_genai.draft_model(str(draft_path), "GPU")
        del model
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False,
            "method": "ov_genai.draft_model",
            "elapsed_s": round(time.perf_counter() - t0, 2),
            "error": str(exc),
        }

    return {
        "ok": True,
        "method": "ov_genai.draft_model",
        "elapsed_s": round(time.perf_counter() - t0, 2),
    }


def validate_pipeline_accepts_draft(target_model_path: Path, draft_model_path: Path) -> dict[str, Any]:
    if ov_genai is None:
        return {
            "ok": False,
            "method": "LLMPipeline+draft_model",
            "error": "OPENVINO_GENAI_NOT_AVAILABLE",
        }

    t0 = time.perf_counter()
    try:
        pipe = ov_genai.LLMPipeline(
            str(target_model_path),
            "GPU",
            {"draft_model": ov_genai.draft_model(str(draft_model_path), "GPU")},
        )
        del pipe
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False,
            "method": "LLMPipeline+draft_model",
            "elapsed_s": round(time.perf_counter() - t0, 2),
            "error": str(exc),
        }

    return {
        "ok": True,
        "method": "LLMPipeline+draft_model",
        "elapsed_s": round(time.perf_counter() - t0, 2),
    }


def attempt_convert_and_validate(target_key: str, spec: dict[str, Any], chosen_repo: str) -> dict[str, Any]:
    raw_dir = Path(spec["raw_dir"])
    final_dir = Path(spec["final_dir"])
    target_model = Path(spec["target_model"])

    conversion_attempts: list[dict[str, Any]] = []

    direct_raw = try_direct_draft_load(raw_dir)
    conversion_attempts.append({"step": "direct_raw_draft_load", **direct_raw})

    if direct_raw.get("ok"):
        ensure_clean_dir(final_dir)
        for source in raw_dir.rglob("*"):
            if not source.is_file():
                continue
            relative = source.relative_to(raw_dir)
            destination = final_dir / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)

        pipe_validation = validate_pipeline_accepts_draft(target_model, final_dir)
        conversion_attempts.append({"step": "pipeline_validation_raw_copy", **pipe_validation})
        if pipe_validation.get("ok"):
            return {
                "status": "converted",
                "disposition": "DIRECT_DRAFT_LOAD_SUPPORTED",
                "repo": chosen_repo,
                "conversion_attempts": conversion_attempts,
                "final_dir": str(final_dir),
                "final_files": list_files_snapshot(final_dir),
            }

    ensure_clean_dir(final_dir)
    optimum_result = run_optimum_export(raw_dir, final_dir)
    conversion_attempts.append({"step": "optimum_export", **optimum_result})

    if optimum_result.get("ok") and (final_dir / "openvino_model.xml").exists() and (final_dir / "openvino_model.bin").exists():
        pipe_validation = validate_pipeline_accepts_draft(target_model, final_dir)
        conversion_attempts.append({"step": "pipeline_validation_optimum", **pipe_validation})

        if pipe_validation.get("ok"):
            return {
                "status": "converted",
                "disposition": "OPENVINO_IR_VALIDATED",
                "repo": chosen_repo,
                "conversion_attempts": conversion_attempts,
                "final_dir": str(final_dir),
                "final_files": list_files_snapshot(final_dir),
            }

        return {
            "status": "failed",
            "disposition": "EAGLE3_NOT_CONVERTIBLE",
            "repo": chosen_repo,
            "conversion_attempts": conversion_attempts,
            "final_dir": str(final_dir),
            "final_files": list_files_snapshot(final_dir),
        }

    return {
        "status": "failed",
        "disposition": "FRAMEWORK_NOT_SUPPORTED",
        "repo": chosen_repo,
        "conversion_attempts": conversion_attempts,
        "final_dir": str(final_dir),
        "final_files": list_files_snapshot(final_dir),
    }


def acquire_target(target_key: str, spec: dict[str, Any]) -> dict[str, Any]:
    target_model = Path(spec["target_model"])
    if not (target_model / "openvino_model.xml").exists() or not (target_model / "openvino_model.bin").exists():
        return {
            "target": target_key,
            "status": "failed",
            "disposition": "TARGET_MODEL_NOT_AVAILABLE",
            "target_model": str(target_model),
        }

    primary = str(spec["primary_repo"])
    fallback = str(spec["fallback_repo"])
    raw_dir = Path(spec["raw_dir"])

    downloads: list[dict[str, Any]] = []
    primary_result = download_repo(primary, raw_dir)
    downloads.append({"candidate": "primary", **primary_result})

    chosen_repo: str | None = None

    if primary_result.get("ok"):
        chosen_repo = primary
    else:
        fallback_result = download_repo(fallback, raw_dir)
        downloads.append({"candidate": "fallback", **fallback_result})
        if fallback_result.get("ok"):
            chosen_repo = fallback

    if chosen_repo is None:
        return {
            "target": target_key,
            "status": "failed",
            "disposition": "ACQUISITION_FAILED",
            "target_model": str(target_model),
            "raw_dir": str(raw_dir),
            "downloads": downloads,
        }

    conversion = attempt_convert_and_validate(target_key, spec, chosen_repo)

    return {
        "target": target_key,
        "status": conversion.get("status"),
        "disposition": conversion.get("disposition"),
        "target_model": str(target_model),
        "raw_dir": str(raw_dir),
        "final_dir": conversion.get("final_dir"),
        "selected_repo": chosen_repo,
        "downloads": downloads,
        "conversion": conversion,
    }


def main() -> None:
    started_utc = now_iso()
    metadata = {
        "timestamp_utc": started_utc,
        "commit_hash": git_head(),
        "platform": platform.platform(),
        "python": sys.version,
        "cwd": str(ROOT),
        "ac_power": ac_power_state(),
        "disk": {
            "path": "C:\\",
            "free_gb": round(float(shutil.disk_usage("C:\\").free) / (1024**3), 2),
        },
        "huggingface_hub_available": huggingface_hub is not None,
        "openvino_genai_available": ov_genai is not None,
    }

    if metadata["ac_power"].get("sensor_available") and metadata["ac_power"].get("power_plugged") is False:
        payload = {
            "milestone": "P5-FEASIBILITY-005a",
            "name": "EAGLE-3 acquisition and conversion",
            "metadata": metadata,
            "status": "failed",
            "failure_reason": "AC_POWER_REQUIRED",
            "started_utc": started_utc,
            "finished_utc": now_iso(),
            "targets": {},
        }
        write_json_atomic(OUTPUT_JSON, payload)
        print(json.dumps(payload, indent=2))
        return

    targets_result: dict[str, Any] = {}
    for target_key, spec in TARGETS.items():
        targets_result[target_key] = acquire_target(target_key, spec)
        write_json_atomic(
            OUTPUT_JSON,
            {
                "milestone": "P5-FEASIBILITY-005a",
                "name": "EAGLE-3 acquisition and conversion",
                "metadata": metadata,
                "status": "in_progress",
                "started_utc": started_utc,
                "finished_utc": None,
                "targets": targets_result,
            },
        )

    target_statuses = [str(v.get("status")) for v in targets_result.values() if isinstance(v, dict)]
    overall_status = "completed" if any(status == "converted" for status in target_statuses) else "completed_with_failures"

    payload = {
        "milestone": "P5-FEASIBILITY-005a",
        "name": "EAGLE-3 acquisition and conversion",
        "metadata": metadata,
        "status": overall_status,
        "started_utc": started_utc,
        "finished_utc": now_iso(),
        "targets": targets_result,
    }
    write_json_atomic(OUTPUT_JSON, payload)
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
