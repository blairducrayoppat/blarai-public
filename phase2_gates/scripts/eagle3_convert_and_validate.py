"""
eagle3_convert_and_validate.py — EAGLE-3 OpenVINO Conversion Probe
====================================================================
Milestone: P5-FEASIBILITY-005a-EAGLE3
Phase: 2 (Acquisition Evidence) + Phase 3 (OpenVINO Conversion)

Purpose:
  Models already downloaded to -raw directories. This script:
  1. Inspects the raw directories and documents architecture metadata (Phase 2)
  2. Attempts optimum-cli + ov_genai conversion for each model (Phase 3)
  3. Validates whether ov_genai.LLMPipeline accepts the converted EAGLE-3 head
     as a draft_model
  4. Records all findings to p5_005a_eagle3_acquisition.json

  Does NOT re-download models. Fails closed if raw dirs are empty.

Usage:
  python phase2_gates/scripts/eagle3_convert_and_validate.py

Network: NOT authorized in this script.
"""

from __future__ import annotations

import datetime as dt
import json
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
    import openvino_genai as ov_genai  # type: ignore[import]
    _OVGENAI_VERSION = getattr(ov_genai, "__version__", "unknown")
except Exception:
    ov_genai = None  # type: ignore[assignment]
    _OVGENAI_VERSION = "unavailable"

EVIDENCE_DIR = ROOT / "phase2_gates" / "evidence"
OUTPUT_JSON = EVIDENCE_DIR / "p5_005a_eagle3_acquisition.json"

RAW_14B = ROOT / "models" / "eagle3-qwen3-14b-raw"
DEST_14B = ROOT / "models" / "eagle3-qwen3-14b"
TARGET_14B = ROOT / "models" / "qwen3-14b" / "openvino-int4-gpu"

RAW_8B = ROOT / "models" / "eagle3-qwen3-8b-raw"
DEST_8B = ROOT / "models" / "eagle3-qwen3-8b"
TARGET_8B = ROOT / "models" / "qwen3-8b" / "openvino-int4-gpu"


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def git_head() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip()
    except Exception:
        return "unknown"


def write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)
    tmp.replace(path)


def inspect_dir(path: Path) -> dict[str, Any]:
    """Describe the contents of a model directory without loading weights."""
    if not path.exists():
        return {"exists": False, "files": [], "total_size_mb": 0.0,
                "architecture": None, "model_type": None, "config": None}

    files: list[dict[str, Any]] = []
    total: int = 0
    config_data: dict[str, Any] | None = None

    for f in sorted(path.iterdir()):
        if f.is_file():
            sz = f.stat().st_size
            total += sz
            files.append({"name": f.name, "size_mb": round(sz / (1024 * 1024), 3)})
            if f.name == "config.json":
                try:
                    config_data = json.loads(f.read_text(encoding="utf-8"))
                except Exception:
                    pass
        elif f.is_dir():
            files.append({"name": f.name + "/", "size_mb": 0.0})

    result: dict[str, Any] = {
        "exists": True,
        "path": str(path),
        "files": files,
        "total_size_mb": round(total / (1024 * 1024), 2),
        "config": config_data,
        "architecture": None,
        "model_type": None,
        "num_hidden_layers": None,
        "hidden_size": None,
        "vocab_size": None,
        "has_custom_code": any(f["name"].endswith(".py") for f in files),
        "has_auto_map": False,
        "has_safetensors": any(f["name"].endswith(".safetensors") for f in files),
        "has_pytorch_bin": any("pytorch_model" in f["name"] for f in files),
    }

    if config_data:
        archs = config_data.get("architectures", [])
        result["architecture"] = archs[0] if archs else None
        result["model_type"] = config_data.get("model_type")
        result["num_hidden_layers"] = config_data.get("num_hidden_layers")
        result["hidden_size"] = config_data.get("hidden_size")
        result["vocab_size"] = config_data.get("vocab_size")
        result["has_auto_map"] = bool(config_data.get("auto_map"))

    return result


def check_class_in_transformers(arch: str) -> dict[str, Any]:
    """Check whether an architecture class exists in the installed transformers."""
    try:
        import transformers
        cls = getattr(transformers, arch, None)
        return {
            "architecture": arch,
            "found": cls is not None,
            "transformers_version": transformers.__version__,
            "error": None if cls is not None else f"'{arch}' not in transformers {transformers.__version__}",
        }
    except Exception as exc:
        return {"architecture": arch, "found": False, "error": str(exc)}


def run_optimum_export(src: Path, dst: Path, label: str) -> dict[str, Any]:
    """Attempt optimum-cli export to OpenVINO IR. Returns structured result."""
    dst.mkdir(parents=True, exist_ok=True)
    optimum_cli = ROOT / ".venv" / "Scripts" / "optimum-cli.exe"

    if not optimum_cli.exists():
        return {
            "label": label,
            "ok": False,
            "method": "optimum-cli",
            "error": f"OPTIMUM_CLI_NOT_FOUND at {optimum_cli}",
            "ir_produced": False,
        }

    cmd = [
        str(optimum_cli),
        "export",
        "openvino",
        "--model",
        str(src),
        "--task",
        "text-generation-with-past",   # force task; EAGLE-3 heads aren't standard CausalLM
        "--trust-remote-code",          # needed for Eagle3Speculator (eagle3.py / auto_map)
        "--weight-format",
        "int4",
        str(dst),
    ]

    print(f"  [convert] Running: {' '.join(cmd)}")
    t0 = time.perf_counter()
    proc = subprocess.run(cmd, cwd=ROOT, text=True, capture_output=True, check=False)
    elapsed = round(time.perf_counter() - t0, 2)

    ir_present = (dst / "openvino_model.xml").exists() and (dst / "openvino_model.bin").exists()

    return {
        "label": label,
        "ok": proc.returncode == 0,
        "method": "optimum-cli export openvino --task text-generation-with-past --trust-remote-code --weight-format int4",
        "returncode": proc.returncode,
        "elapsed_s": elapsed,
        "stdout_tail": proc.stdout[-3000:] if proc.stdout else "",
        "stderr_tail": proc.stderr[-3000:] if proc.stderr else "",
        "ir_produced": ir_present,
        "error": None if proc.returncode == 0 else f"EXIT_CODE_{proc.returncode}",
    }


def try_draft_model_creation(draft_path: Path, label: str) -> dict[str, Any]:
    """Attempt to create ov_genai.draft_model(...) from a path."""
    if ov_genai is None:
        return {"label": label, "ok": False, "error": "OV_GENAI_UNAVAILABLE"}

    t0 = time.perf_counter()
    try:
        dm = ov_genai.draft_model(str(draft_path), "GPU")
        del dm
        return {
            "label": label,
            "ok": True,
            "elapsed_s": round(time.perf_counter() - t0, 2),
            "error": None,
        }
    except Exception as exc:
        return {
            "label": label,
            "ok": False,
            "elapsed_s": round(time.perf_counter() - t0, 2),
            "error": str(exc),
            "error_type": type(exc).__name__,
        }


def try_llm_pipeline_with_draft(target: Path, draft: Path, label: str) -> dict[str, Any]:
    """Attempt to create an LLMPipeline with the EAGLE-3 as draft_model."""
    if ov_genai is None:
        return {"label": label, "ok": False, "error": "OV_GENAI_UNAVAILABLE"}

    t0 = time.perf_counter()
    try:
        config = {"draft_model": ov_genai.draft_model(str(draft), "GPU")}
        pipe = ov_genai.LLMPipeline(str(target), "GPU", config)
        del pipe
        return {
            "label": label,
            "ok": True,
            "elapsed_s": round(time.perf_counter() - t0, 2),
            "error": None,
        }
    except Exception as exc:
        return {
            "label": label,
            "ok": False,
            "elapsed_s": round(time.perf_counter() - t0, 2),
            "error": str(exc),
            "error_type": type(exc).__name__,
        }


def probe_model(
    label: str,
    raw_dir: Path,
    dest_dir: Path,
    target_dir: Path,
) -> dict[str, Any]:
    """Full probe for one EAGLE-3 model: inspect → convert → validate."""
    print(f"\n[probe:{label}] Starting probe")

    # Step 1: Inspect raw dir
    insp = inspect_dir(raw_dir)
    arch = insp.get("architecture")
    print(f"  architecture: {arch}")
    print(f"  files: {len(insp['files'])}, total: {insp['total_size_mb']} MB")
    print(f"  has_custom_code: {insp['has_custom_code']}, has_auto_map: {insp['has_auto_map']}")

    if not insp["exists"] or not insp["files"]:
        return {
            "label": label,
            "raw_inspection": insp,
            "disposition": "RAW_DIR_EMPTY",
            "class_check": None,
            "conversion_attempt": None,
            "draft_model_probe": None,
            "pipeline_probe": None,
        }

    # Step 2: Check transformers class
    cls_check = check_class_in_transformers(arch or "") if arch else None
    print(f"  transformers class found: {cls_check.get('found') if cls_check else 'N/A'}")

    # Step 3: Attempt optimum-cli conversion
    print(f"  [convert] Attempting optimum-cli export to {dest_dir} ...")
    dest_dir.mkdir(parents=True, exist_ok=True)
    conv = run_optimum_export(raw_dir, dest_dir, f"optimum_{label}")
    print(f"  [convert] returncode={conv['returncode']}, ir_produced={conv['ir_produced']}")
    if conv["stderr_tail"]:
        print(f"  [convert] stderr tail: {conv['stderr_tail'][-400:]}")

    # Step 4: If IR produced, try draft_model creation
    draft_probe: dict[str, Any] | None = None
    pipeline_probe: dict[str, Any] | None = None

    if conv["ir_produced"]:
        print(f"  [validate] IR produced — trying ov_genai.draft_model ...")
        draft_probe = try_draft_model_creation(dest_dir, f"draft_model_{label}")
        print(f"  [validate] draft_model ok={draft_probe['ok']}, error={draft_probe.get('error', '')[:120]}")

        if draft_probe["ok"]:
            print(f"  [validate] draft_model loaded — trying LLMPipeline + draft ...")
            pipeline_probe = try_llm_pipeline_with_draft(target_dir, dest_dir, f"pipeline_{label}")
            print(f"  [validate] pipeline ok={pipeline_probe['ok']}, error={pipeline_probe.get('error', '')[:120]}")
    else:
        # Even without full conversion, try draft_model against raw dir directly
        # (in case ov_genai can directly load pytorch/safetensors)
        print(f"  [validate] No IR — trying ov_genai.draft_model against raw dir directly ...")
        draft_probe = try_draft_model_creation(raw_dir, f"draft_model_raw_{label}")
        print(f"  [validate] draft_model(raw) ok={draft_probe['ok']}, error={draft_probe.get('error', '')[:120]}")

    # Step 5: Determine disposition
    if conv["ir_produced"] and draft_probe and draft_probe["ok"] and pipeline_probe and pipeline_probe["ok"]:
        disposition = "EAGLE3_OV_PIPELINE_SUPPORTED"
    elif conv["ir_produced"] and draft_probe and not draft_probe["ok"]:
        disposition = "EAGLE3_NOT_CONVERTIBLE"  # IR produced but draft_model rejects it
    elif conv["ir_produced"] and draft_probe and draft_probe["ok"] and pipeline_probe and not pipeline_probe["ok"]:
        disposition = "FRAMEWORK_NOT_SUPPORTED"  # draft_model ok but LLMPipeline rejects
    else:
        # Conversion failed (no IR produced)
        disposition = "FRAMEWORK_NOT_SUPPORTED"

    return {
        "label": label,
        "raw_inspection": insp,
        "class_check": cls_check,
        "conversion_attempt": conv,
        "draft_model_probe": draft_probe,
        "pipeline_probe": pipeline_probe,
        "disposition": disposition,
    }


def main() -> None:
    started = now_iso()
    print(f"[P5-005a-EAGLE3 Phase 2+3] Conversion probe started: {started}")

    import psutil  # type: ignore[import]
    battery = psutil.sensors_battery()
    power_state = {
        "sensor_available": battery is not None,
        "power_plugged": bool(battery.power_plugged) if battery else None,
        "battery_percent": float(battery.percent) if battery else None,
    }

    if power_state.get("sensor_available") and power_state.get("power_plugged") is False:
        print("FAIL-CLOSED: AC power not detected. Benchmarking requires AC power.")
        sys.exit(1)

    metadata: dict[str, Any] = {
        "timestamp_utc": started,
        "commit_hash": git_head(),
        "platform": platform.platform(),
        "python_version": sys.version,
        "openvino_genai_version": _OVGENAI_VERSION,
        "power_envelope": power_state,
    }

    # Probe both models
    result_14b = probe_model("14b", RAW_14B, DEST_14B, TARGET_14B)
    result_8b = probe_model("8b", RAW_8B, DEST_8B, TARGET_8B)

    # Overall disposition
    dispositions = {result_14b["disposition"], result_8b["disposition"]}
    if "EAGLE3_OV_PIPELINE_SUPPORTED" in dispositions:
        overall = "PARTIAL_OR_FULL_OV_SUPPORT"
    else:
        overall = "FRAMEWORK_NOT_SUPPORTED"

    evidence: dict[str, Any] = {
        "milestone": "P5-FEASIBILITY-005a-EAGLE3",
        "phase": "acquisition_and_conversion_probe",
        "metadata": metadata,
        "models": {
            "eagle3_14b": result_14b,
            "eagle3_8b": result_8b,
        },
        "overall_disposition": overall,
        "started_utc": started,
        "finished_utc": now_iso(),
        "summary": {
            "14b_disposition": result_14b["disposition"],
            "8b_disposition": result_8b["disposition"],
            "14b_architecture": result_14b["raw_inspection"].get("architecture"),
            "8b_architecture": result_8b["raw_inspection"].get("architecture"),
            "14b_ir_produced": result_14b.get("conversion_attempt", {}).get("ir_produced", False),
            "8b_ir_produced": result_8b.get("conversion_attempt", {}).get("ir_produced", False),
        },
    }

    write_json_atomic(OUTPUT_JSON, evidence)
    print(f"\n[P5-005a-EAGLE3] Evidence written: {OUTPUT_JSON}")
    print(f"  14B disposition: {result_14b['disposition']}")
    print(f"  8B disposition:  {result_8b['disposition']}")
    print(f"  Overall:         {overall}")
    print(f"  Finished: {evidence['finished_utc']}")


if __name__ == "__main__":
    main()
