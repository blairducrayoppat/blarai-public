#!/usr/bin/env python3
"""
acquire_models.py — One-time model download + conversion pipeline.

Models:
  M1+M4: BAAI/bge-small-en-v1.5  (33M params, 384-dim embedding)
         → ONNX FP16  (CPU inference for Semantic Router)
         → OpenVINO IR INT8 (NPU inference for Substrate bi-encoder)

  M2+M3: Qwen/Qwen3-1.7B  (1.7B params, instruction-tuned)
         → OpenVINO IR INT4 weight-only (NPU inference for Policy Agent + Orchestrator)

Output layout:
  models/bge-small-en-v1.5/onnx-fp16/
  models/bge-small-en-v1.5/openvino-int8/
  models/qwen3-1.7b/openvino-int4/

Evidence:
  phase2_gates/evidence/model_acquisition.json
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# ── Paths ──────────────────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parent.parent.parent  # BlarAI/
MODELS_DIR = ROOT / "models"
BGE_ONNX_DIR = MODELS_DIR / "bge-small-en-v1.5" / "onnx-fp16"
BGE_OV_DIR = MODELS_DIR / "bge-small-en-v1.5" / "openvino-int8"
QWEN_OV_DIR = MODELS_DIR / "qwen3-1.7b" / "openvino-int4"
EVIDENCE_DIR = ROOT / "phase2_gates" / "evidence"
EVIDENCE_FILE = EVIDENCE_DIR / "model_acquisition.json"

BGE_HF_ID = "BAAI/bge-small-en-v1.5"
QWEN_HF_ID = "Qwen/Qwen3-1.7B"


def log(msg: str) -> None:
    """Timestamped console log."""
    ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


def sha256_file(path: Path) -> str:
    """Compute SHA-256 of a single file."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(1 << 20):  # 1 MB chunks
            h.update(chunk)
    return h.hexdigest()


def sha256_directory(directory: Path) -> dict[str, str]:
    """Compute SHA-256 hashes for all files in a directory (non-recursive)."""
    hashes: dict[str, str] = {}
    for p in sorted(directory.iterdir()):
        if p.is_file():
            hashes[p.name] = sha256_file(p)
    return hashes


# ── Step 1: BGE → ONNX FP16 ───────────────────────────────────────────
def convert_bge_onnx_fp16() -> dict[str, Any]:
    """Export bge-small-en-v1.5 to ONNX FP16 for CPU inference.

    Uses the optimum CLI (subprocess) which works reliably for ONNX export.
    """
    log("Step 1/3: Converting BGE → ONNX FP16 ...")
    t0 = time.monotonic()

    if _dir_has_artifacts(BGE_ONNX_DIR, [".onnx"]):
        elapsed = time.monotonic() - t0
        log(f"  SKIP (artifacts already exist, {elapsed:.1f}s)")
        return {"step": "bge_onnx_fp16", "status": "PASS", "output_dir": str(BGE_ONNX_DIR), "elapsed_s": round(elapsed, 1), "note": "cached"}

    import subprocess
    BGE_ONNX_DIR.mkdir(parents=True, exist_ok=True)
    cmd = [
        sys.executable, "-m", "optimum.exporters.onnx",
        "--model", BGE_HF_ID,
        "--task", "feature-extraction",
        "--dtype", "fp16",
        str(BGE_ONNX_DIR),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    elapsed = time.monotonic() - t0

    if result.returncode != 0:
        log(f"  FAIL (exit {result.returncode})")
        log(f"  stderr: {result.stderr[-2000:]}")
        return {"step": "bge_onnx_fp16", "status": "FAIL", "exit_code": result.returncode, "stderr_tail": result.stderr[-2000:], "elapsed_s": round(elapsed, 1)}

    log(f"  OK ({elapsed:.1f}s)")
    return {"step": "bge_onnx_fp16", "status": "PASS", "output_dir": str(BGE_ONNX_DIR), "elapsed_s": round(elapsed, 1)}


# ── Step 2: BGE → OpenVINO INT8 ───────────────────────────────────────
def convert_bge_openvino_int8() -> dict[str, Any]:
    """Export bge-small-en-v1.5 to OpenVINO IR INT8 for NPU inference.

    Uses the programmatic API because the optimum.exporters.openvino CLI
    silently fails (exit 0, no output) with optimum-intel 1.27 + optimum 2.1.
    """
    log("Step 2/3: Converting BGE → OpenVINO INT8 ...")
    t0 = time.monotonic()

    if _dir_has_artifacts(BGE_OV_DIR, [".xml", ".bin"]):
        elapsed = time.monotonic() - t0
        log(f"  SKIP (artifacts already exist, {elapsed:.1f}s)")
        return {"step": "bge_openvino_int8", "status": "PASS", "output_dir": str(BGE_OV_DIR), "elapsed_s": round(elapsed, 1), "note": "cached"}

    try:
        from optimum.intel import OVModelForFeatureExtraction
        from transformers import AutoTokenizer

        BGE_OV_DIR.mkdir(parents=True, exist_ok=True)
        model = OVModelForFeatureExtraction.from_pretrained(
            BGE_HF_ID, export=True, compile=False, load_in_8bit=True,
        )
        model.save_pretrained(str(BGE_OV_DIR))
        tokenizer = AutoTokenizer.from_pretrained(BGE_HF_ID)
        tokenizer.save_pretrained(str(BGE_OV_DIR))
        elapsed = time.monotonic() - t0
        log(f"  OK ({elapsed:.1f}s)")
        return {"step": "bge_openvino_int8", "status": "PASS", "output_dir": str(BGE_OV_DIR), "elapsed_s": round(elapsed, 1)}
    except Exception as e:
        elapsed = time.monotonic() - t0
        log(f"  FAIL — {e}")
        return {"step": "bge_openvino_int8", "status": "FAIL", "error": str(e), "elapsed_s": round(elapsed, 1)}


# ── Step 3: Qwen3-1.7B → OpenVINO INT4 ──────────────────────────────
def convert_qwen_openvino_int4() -> dict[str, Any]:
    """Export Qwen3-1.7B to OpenVINO IR INT4 weight-only for NPU inference.

    Uses the programmatic API because the optimum.exporters.openvino CLI
    silently fails (exit 0, no output) with optimum-intel 1.27 + optimum 2.1.
    """
    log("Step 3/3: Converting Qwen3-1.7B → OpenVINO INT4 (this may take 10-30 min) ...")
    t0 = time.monotonic()

    if _dir_has_artifacts(QWEN_OV_DIR, [".xml", ".bin"]):
        elapsed = time.monotonic() - t0
        log(f"  SKIP (artifacts already exist, {elapsed:.1f}s)")
        return {"step": "qwen3_openvino_int4", "status": "PASS", "output_dir": str(QWEN_OV_DIR), "elapsed_s": round(elapsed, 1), "note": "cached"}

    try:
        from optimum.intel import OVModelForCausalLM
        from transformers import AutoTokenizer

        QWEN_OV_DIR.mkdir(parents=True, exist_ok=True)
        model = OVModelForCausalLM.from_pretrained(
            QWEN_HF_ID,
            export=True,
            compile=False,
            load_in_4bit=True,
            quantization_config={"bits": 4, "sym": False, "group_size": 128, "ratio": 1.0},
        )
        model.save_pretrained(str(QWEN_OV_DIR))
        tokenizer = AutoTokenizer.from_pretrained(QWEN_HF_ID)
        tokenizer.save_pretrained(str(QWEN_OV_DIR))
        elapsed = time.monotonic() - t0
        log(f"  OK ({elapsed:.1f}s)")
        return {"step": "qwen3_openvino_int4", "status": "PASS", "output_dir": str(QWEN_OV_DIR), "elapsed_s": round(elapsed, 1)}
    except Exception as e:
        elapsed = time.monotonic() - t0
        log(f"  FAIL — {e}")
        return {"step": "qwen3_openvino_int4", "status": "FAIL", "error": str(e), "elapsed_s": round(elapsed, 1)}


# ── Helpers ────────────────────────────────────────────────────────────
def _dir_has_artifacts(directory: Path, extensions: list[str]) -> bool:
    """Return True if directory exists and contains files with all expected extensions."""
    if not directory.exists():
        return False
    found = {p.suffix for p in directory.iterdir() if p.is_file()}
    return all(ext in found for ext in extensions)


# ── Validation: expected artifacts exist ──────────────────────────────
def validate_artifact(directory: Path, expected_extensions: list[str]) -> dict[str, Any]:
    """Check that at least one file with each expected extension exists."""
    if not directory.exists():
        return {"dir": str(directory), "status": "FAIL", "reason": "directory missing"}

    found_exts = {p.suffix for p in directory.iterdir() if p.is_file()}
    missing = [ext for ext in expected_extensions if ext not in found_exts]
    files = sorted(p.name for p in directory.iterdir() if p.is_file())
    total_bytes = sum(p.stat().st_size for p in directory.iterdir() if p.is_file())

    if missing:
        return {
            "dir": str(directory),
            "status": "FAIL",
            "reason": f"missing extensions: {missing}",
            "files": files,
        }

    return {
        "dir": str(directory),
        "status": "PASS",
        "files": files,
        "total_size_mb": round(total_bytes / (1024 * 1024), 1),
    }


# ── Quick inference tests ─────────────────────────────────────────────
def quick_inference_test_bge_onnx() -> dict[str, Any]:
    """Single forward pass through BGE ONNX FP16 model.

    Uses onnxruntime.InferenceSession directly because the sentence-transformers
    ONNX export names outputs 'token_embeddings' / 'sentence_embedding' rather
    than the HF-style 'last_hidden_state' expected by ORTModelForFeatureExtraction.
    """
    log("Inference test: BGE ONNX FP16 ...")
    try:
        import onnxruntime as ort
        from transformers import AutoTokenizer
        import numpy as np

        tokenizer = AutoTokenizer.from_pretrained(str(BGE_ONNX_DIR))
        onnx_path = str(BGE_ONNX_DIR / "model.onnx")
        session = ort.InferenceSession(onnx_path, providers=["CPUExecutionProvider"])

        inputs = tokenizer(
            "Represent this sentence for retrieval: Hello world",
            return_tensors="np",
            padding=True,
            truncation=True,
            max_length=128,
        )
        feed = {k: v.astype(np.int64) for k, v in inputs.items() if k in {n.name for n in session.get_inputs()}}
        outputs = session.run(None, feed)

        # Outputs: [0]=token_embeddings (batch, seq, 384), [1]=sentence_embedding (batch, 384)
        sentence_emb = outputs[1][0]  # shape (384,)
        dim = int(sentence_emb.shape[0])
        norm = float(np.linalg.norm(sentence_emb))

        log(f"  OK — dim={dim}, norm={norm:.4f}")
        return {
            "test": "bge_onnx_inference",
            "status": "PASS",
            "embedding_dim": dim,
            "embedding_norm": round(norm, 4),
        }
    except Exception as e:
        log(f"  FAIL — {e}")
        return {"test": "bge_onnx_inference", "status": "FAIL", "error": str(e)}


def quick_inference_test_bge_openvino() -> dict[str, Any]:
    """Single forward pass through BGE OpenVINO INT8 model."""
    log("Inference test: BGE OpenVINO INT8 ...")
    try:
        from optimum.intel import OVModelForFeatureExtraction
        from transformers import AutoTokenizer
        import numpy as np

        tokenizer = AutoTokenizer.from_pretrained(str(BGE_OV_DIR))
        model = OVModelForFeatureExtraction.from_pretrained(str(BGE_OV_DIR))

        inputs = tokenizer(
            "Represent this sentence for retrieval: Hello world",
            return_tensors="np",
            padding=True,
            truncation=True,
            max_length=128,
        )
        outputs = model(**inputs)
        embedding = outputs.last_hidden_state[0, 0, :]
        dim = int(embedding.shape[0])
        norm = float(np.linalg.norm(embedding))

        log(f"  OK — dim={dim}, norm={norm:.4f}")
        return {
            "test": "bge_openvino_inference",
            "status": "PASS",
            "embedding_dim": dim,
            "embedding_norm": round(norm, 4),
        }
    except Exception as e:
        log(f"  FAIL — {e}")
        return {"test": "bge_openvino_inference", "status": "FAIL", "error": str(e)}


def quick_inference_test_qwen_openvino() -> dict[str, Any]:
    """Single forward pass (greedy, 16 tokens) through Qwen3 OpenVINO INT4."""
    log("Inference test: Qwen3 OpenVINO INT4 ...")
    try:
        from optimum.intel import OVModelForCausalLM
        from transformers import AutoTokenizer

        tokenizer = AutoTokenizer.from_pretrained(str(QWEN_OV_DIR))
        model = OVModelForCausalLM.from_pretrained(str(QWEN_OV_DIR))

        prompt = "What is 2+2?"
        inputs = tokenizer(prompt, return_tensors="pt")
        t0 = time.monotonic()
        outputs = model.generate(**inputs, max_new_tokens=16, do_sample=False)
        elapsed = time.monotonic() - t0
        decoded = tokenizer.decode(outputs[0], skip_special_tokens=True)

        log(f"  OK — {elapsed:.2f}s, output: {decoded[:100]}")
        return {
            "test": "qwen3_openvino_inference",
            "status": "PASS",
            "generation_time_s": round(elapsed, 2),
            "output_preview": decoded[:200],
        }
    except Exception as e:
        log(f"  FAIL — {e}")
        return {"test": "qwen3_openvino_inference", "status": "FAIL", "error": str(e)}


# ── Main pipeline ─────────────────────────────────────────────────────
def main() -> None:
    log("=" * 60)
    log("BlarAI Model Acquisition Pipeline")
    log(f"  BGE: {BGE_HF_ID}")
    log(f"  Qwen: {QWEN_HF_ID}")
    log(f"  Output: {MODELS_DIR}")
    log("=" * 60)

    pipeline_start = time.monotonic()
    evidence: dict[str, Any] = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "models": {
            "bge": BGE_HF_ID,
            "qwen": QWEN_HF_ID,
        },
        "conversions": [],
        "validations": [],
        "inference_tests": [],
        "hashes": {},
        "overall_status": "IN_PROGRESS",
    }

    # ── Conversions ────────────────────────────────────────────────
    conv_results = []
    conv_results.append(convert_bge_onnx_fp16())
    conv_results.append(convert_bge_openvino_int8())
    conv_results.append(convert_qwen_openvino_int4())
    evidence["conversions"] = conv_results

    any_conv_fail = any(r["status"] == "FAIL" for r in conv_results)
    if any_conv_fail:
        log("!!! One or more conversions FAILED. Skipping inference tests.")
        evidence["overall_status"] = "FAIL"
        _write_evidence(evidence, pipeline_start)
        sys.exit(1)

    # ── Artifact validation ────────────────────────────────────────
    val_results = []
    val_results.append(validate_artifact(BGE_ONNX_DIR, [".onnx"]))
    val_results.append(validate_artifact(BGE_OV_DIR, [".xml", ".bin"]))
    val_results.append(validate_artifact(QWEN_OV_DIR, [".xml", ".bin"]))
    evidence["validations"] = val_results

    any_val_fail = any(r["status"] == "FAIL" for r in val_results)
    if any_val_fail:
        log("!!! Artifact validation FAILED.")
        evidence["overall_status"] = "FAIL"
        _write_evidence(evidence, pipeline_start)
        sys.exit(1)

    # ── SHA-256 hashes ─────────────────────────────────────────────
    log("Computing SHA-256 hashes ...")
    evidence["hashes"]["bge_onnx_fp16"] = sha256_directory(BGE_ONNX_DIR)
    evidence["hashes"]["bge_openvino_int8"] = sha256_directory(BGE_OV_DIR)
    evidence["hashes"]["qwen3_openvino_int4"] = sha256_directory(QWEN_OV_DIR)

    # ── Inference tests ────────────────────────────────────────────
    inf_results = []
    inf_results.append(quick_inference_test_bge_onnx())
    inf_results.append(quick_inference_test_bge_openvino())
    inf_results.append(quick_inference_test_qwen_openvino())
    evidence["inference_tests"] = inf_results

    any_inf_fail = any(r["status"] == "FAIL" for r in inf_results)
    if any_inf_fail:
        log("!!! One or more inference tests FAILED.")
        evidence["overall_status"] = "PARTIAL"
    else:
        evidence["overall_status"] = "PASS"

    _write_evidence(evidence, pipeline_start)

    # ── Summary ────────────────────────────────────────────────────
    log("=" * 60)
    log(f"Pipeline status: {evidence['overall_status']}")
    for c in conv_results:
        log(f"  {c['step']}: {c['status']} ({c['elapsed_s']}s)")
    for v in val_results:
        log(f"  {v['dir']}: {v['status']} — {v.get('total_size_mb', 'N/A')} MB")
    for i in inf_results:
        log(f"  {i['test']}: {i['status']}")
    log(f"Evidence written to: {EVIDENCE_FILE}")
    log("=" * 60)

    if evidence["overall_status"] == "FAIL":
        sys.exit(1)


def _write_evidence(evidence: dict[str, Any], pipeline_start: float) -> None:
    """Write evidence JSON to disk."""
    evidence["total_elapsed_s"] = round(time.monotonic() - pipeline_start, 1)
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    with open(EVIDENCE_FILE, "w", encoding="utf-8") as f:
        json.dump(evidence, f, indent=2, default=str)


if __name__ == "__main__":
    main()
