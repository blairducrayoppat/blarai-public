from __future__ import annotations

import datetime as dt
import json
import platform
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import openvino_genai as ov_genai

try:
    import openvino as ov
except Exception:  # noqa: BLE001
    ov = None  # type: ignore[assignment]


EVIDENCE_DIR = ROOT / "phase2_gates" / "evidence"
OUTPUT_JSON = EVIDENCE_DIR / "p5_005a_cross_device_draft_discovery.json"
TARGET_GPU = ROOT / "models" / "qwen3-1.7b" / "openvino-int4"
DRAFT_GPU = ROOT / "models" / "qwen3-1.7b" / "openvino-int4"
DRAFT_NPU = ROOT / "models" / "qwen3-1.7b" / "openvino-int4-npu"


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


def probe_combo(target_path: Path, target_device: str, draft_path: Path, draft_device: str) -> dict[str, Any]:
    if not target_path.exists():
        return {"supported": False, "error": f"TARGET_MODEL_PATH_MISSING: {target_path}"}
    if not draft_path.exists():
        return {"supported": False, "error": f"DRAFT_MODEL_PATH_MISSING: {draft_path}"}

    t0 = time.perf_counter()
    try:
        config: dict[str, Any] = {}
        config["draft_model"] = ov_genai.draft_model(str(draft_path), draft_device)
        pipe = ov_genai.LLMPipeline(str(target_path), target_device, config)

        gen_cfg = ov_genai.GenerationConfig()
        gen_cfg.max_new_tokens = 10
        gen_cfg.do_sample = False
        try:
            gen_cfg.num_assistant_tokens = 5
            gen_cfg.assistant_confidence_threshold = 0.0
        except Exception:
            pass

        output = pipe.generate("Reply with one short sentence.", gen_cfg)
        text = str(output).strip()

        del pipe
        elapsed_ms = (time.perf_counter() - t0) * 1000.0

        if not text:
            return {"supported": False, "error": "EMPTY_OUTPUT", "latency_total_ms": elapsed_ms}

        return {
            "supported": True,
            "error": None,
            "latency_total_ms": elapsed_ms,
            "output_preview": text[:200],
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "supported": False,
            "error": str(exc),
            "latency_total_ms": (time.perf_counter() - t0) * 1000.0,
        }


def main() -> None:
    payload: dict[str, Any] = {
        "milestone": "P5-FEASIBILITY-005a",
        "name": "Cross-device draft model API discovery",
        "timestamp_utc": now_iso(),
        "commit_hash": git_head(),
        "platform": platform.platform(),
        "python": sys.version,
        "openvino_version": getattr(ov, "__version__", "unavailable") if ov is not None else "unavailable",
        "openvino_genai_version": getattr(ov_genai, "__version__", "unknown"),
        "target_model": str(TARGET_GPU),
        "draft_models": {
            "gpu": str(DRAFT_GPU),
            "npu": str(DRAFT_NPU),
        },
        "draft_on_npu_target_on_gpu": probe_combo(TARGET_GPU, "GPU", DRAFT_NPU, "NPU"),
        "draft_on_cpu_target_on_gpu": probe_combo(TARGET_GPU, "GPU", DRAFT_GPU, "CPU"),
        "draft_on_gpu_target_on_gpu": probe_combo(TARGET_GPU, "GPU", DRAFT_GPU, "GPU"),
    }

    write_json_atomic(OUTPUT_JSON, payload)
    print(json.dumps({"status": "ok", "artifact": str(OUTPUT_JSON)}, indent=2))


if __name__ == "__main__":
    main()
