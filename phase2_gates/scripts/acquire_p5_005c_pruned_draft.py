"""
P5-005c v2: Acquire Qwen3-pruned-6L-from-0.6B-int8-ov draft model.

Direct download of pre-built OpenVINO IR model from HuggingFace.
No conversion or quantization needed — INT8_ASYM format is correct.
"""
from __future__ import annotations

import datetime as dt
import gc
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import psutil

try:
    import openvino_genai as ov_genai
except Exception:  # noqa: BLE001
    ov_genai = None  # type: ignore[assignment]

try:
    import huggingface_hub
except Exception:  # noqa: BLE001
    huggingface_hub = None  # type: ignore[assignment]

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
EVIDENCE_DIR = ROOT / "phase2_gates" / "evidence"
OUTPUT_JSON = EVIDENCE_DIR / "p5_005c_pruned_draft_acquisition.json"

HF_REPO_ID = "OpenVINO/Qwen3-pruned-6L-from-0.6B-int8-ov"
TARGET_DIR = ROOT / "models" / "qwen3-0.6b-pruned-6l" / "openvino-int8-gpu"
RAW_HF_DIR = ROOT / "models" / "qwen3-0.6b-pruned-6l" / "raw-hf"
EXISTING_06B_DIR = ROOT / "models" / "qwen3-0.6b" / "openvino-int4-gpu"
MODEL_14B_DIR = ROOT / "models" / "qwen3-14b" / "openvino-int4-gpu"

# Expected architecture
EXPECTED_VOCAB_SIZE = 151936
EXPECTED_HIDDEN_LAYERS = 22
EXPECTED_HIDDEN_SIZE = 1024
EXPECTED_ARCHITECTURE = "Qwen3ForCausalLM"


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def git_head() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True,
        ).strip()
    except Exception:
        return "UNKNOWN"


def write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, default=str)
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


def detect_power_envelope() -> dict[str, Any]:
    state: dict[str, Any] = {
        "sensor_available": False,
        "power_plugged": None,
        "battery_percent": None,
    }
    try:
        battery = psutil.sensors_battery()
    except Exception:
        return state
    if battery is None:
        return state
    state["sensor_available"] = True
    state["power_plugged"] = bool(battery.power_plugged)
    state["battery_percent"] = float(battery.percent) if battery.percent is not None else None
    return state


def enforce_ac_power_or_fail_closed() -> dict[str, Any]:
    state = detect_power_envelope()
    if state.get("sensor_available") and state.get("power_plugged") is False:
        raise RuntimeError("FAIL_CLOSED: AC power not connected. Aborting to protect battery.")
    return state


def free_disk_gb(path: str = "C:\\") -> float:
    usage = psutil.disk_usage(path)
    return float(usage.free) / (1024**3)


# ---------------------------------------------------------------------------
# Step 2: Download / copy model to target directory
# ---------------------------------------------------------------------------
def acquire_model() -> dict[str, Any]:
    """Download from HF or copy from v1 raw-hf if already present."""
    result: dict[str, Any] = {
        "method": None,
        "hf_repo_id": HF_REPO_ID,
        "target_dir": str(TARGET_DIR),
        "ok": False,
        "error": None,
        "elapsed_s": None,
        "files": [],
    }

    t0 = time.perf_counter()

    # Check if target already has the model files
    if (TARGET_DIR / "openvino_model.xml").exists() and (TARGET_DIR / "openvino_model.bin").exists():
        result["method"] = "already_present"
        result["ok"] = True
        result["elapsed_s"] = time.perf_counter() - t0
        result["files"] = [f.name for f in TARGET_DIR.iterdir() if f.is_file()]
        print(f"[ACQUIRE] Model already present at {TARGET_DIR}")
        return result

    # Check if v1 raw-hf download has the files
    if (RAW_HF_DIR / "openvino_model.xml").exists() and (RAW_HF_DIR / "openvino_model.bin").exists():
        print(f"[ACQUIRE] Copying from v1 raw-hf download: {RAW_HF_DIR} -> {TARGET_DIR}")
        result["method"] = "copy_from_raw_hf"
        try:
            TARGET_DIR.mkdir(parents=True, exist_ok=True)
            for item in RAW_HF_DIR.iterdir():
                if item.is_file() and not item.name.startswith("."):
                    shutil.copy2(str(item), str(TARGET_DIR / item.name))
            result["ok"] = True
            result["elapsed_s"] = time.perf_counter() - t0
            result["files"] = [f.name for f in TARGET_DIR.iterdir() if f.is_file()]
            print(f"[ACQUIRE] Copied {len(result['files'])} files.")
            return result
        except Exception as exc:
            result["error"] = str(exc)
            print(f"[ACQUIRE] Copy failed: {exc}, falling through to HF download.")

    # Fresh download from HuggingFace
    if huggingface_hub is None:
        result["error"] = "huggingface_hub not installed"
        return result

    result["method"] = "huggingface_hub_snapshot_download"
    try:
        print(f"[ACQUIRE] Downloading {HF_REPO_ID} to {TARGET_DIR} ...")
        huggingface_hub.snapshot_download(
            repo_id=HF_REPO_ID,
            local_dir=str(TARGET_DIR),
            local_dir_use_symlinks=False,
        )
        result["ok"] = True
        result["elapsed_s"] = time.perf_counter() - t0
        result["files"] = [f.name for f in TARGET_DIR.iterdir() if f.is_file()]
        print(f"[ACQUIRE] Downloaded {len(result['files'])} files in {result['elapsed_s']:.1f}s")
    except Exception as exc:
        result["error"] = str(exc)
        result["elapsed_s"] = time.perf_counter() - t0
        print(f"[ACQUIRE] Download failed: {exc}")

    return result


# ---------------------------------------------------------------------------
# Step 3: Architecture validation
# ---------------------------------------------------------------------------
def validate_architecture() -> dict[str, Any]:
    """Read config.json and verify architecture compatibility."""
    config_path = TARGET_DIR / "config.json"
    result: dict[str, Any] = {
        "ok": False,
        "config_json": None,
        "checks": {},
        "error": None,
    }

    if not config_path.exists():
        result["error"] = "config.json not found in target directory"
        return result

    with open(config_path, "r", encoding="utf-8") as f:
        config = json.load(f)

    result["config_json"] = config

    archs = config.get("architectures", [])
    vocab = config.get("vocab_size")
    layers = config.get("num_hidden_layers")
    hidden = config.get("hidden_size")

    result["checks"] = {
        "architecture_match": EXPECTED_ARCHITECTURE in archs,
        "architecture_found": archs,
        "vocab_size_match": vocab == EXPECTED_VOCAB_SIZE,
        "vocab_size_found": vocab,
        "vocab_size_expected": EXPECTED_VOCAB_SIZE,
        "num_hidden_layers_match": layers == EXPECTED_HIDDEN_LAYERS,
        "num_hidden_layers_found": layers,
        "num_hidden_layers_expected": EXPECTED_HIDDEN_LAYERS,
        "hidden_size_match": hidden == EXPECTED_HIDDEN_SIZE,
        "hidden_size_found": hidden,
        "hidden_size_expected": EXPECTED_HIDDEN_SIZE,
    }

    # Critical gate: vocab_size MUST match for speculative decoding
    if vocab != EXPECTED_VOCAB_SIZE:
        result["error"] = f"INCOMPATIBLE: vocab_size={vocab} != {EXPECTED_VOCAB_SIZE}"
        print(f"[ARCH] FAIL: {result['error']}")
        return result

    result["ok"] = True
    print(f"[ARCH] PASS: Qwen3ForCausalLM, {layers} layers, hidden={hidden}, vocab={vocab}")
    return result


# ---------------------------------------------------------------------------
# Step 4: Tokenizer asset validation
# ---------------------------------------------------------------------------
def validate_tokenizer() -> dict[str, Any]:
    """Ensure openvino_tokenizer/detokenizer assets exist."""
    tok_xml = TARGET_DIR / "openvino_tokenizer.xml"
    tok_bin = TARGET_DIR / "openvino_tokenizer.bin"
    detok_xml = TARGET_DIR / "openvino_detokenizer.xml"
    detok_bin = TARGET_DIR / "openvino_detokenizer.bin"

    result: dict[str, Any] = {
        "ok": False,
        "method": None,
        "tok_xml": tok_xml.exists(),
        "tok_bin": tok_bin.exists(),
        "detok_xml": detok_xml.exists(),
        "detok_bin": detok_bin.exists(),
        "error": None,
    }

    all_present = all([tok_xml.exists(), tok_bin.exists(), detok_xml.exists(), detok_bin.exists()])

    if all_present:
        result["ok"] = True
        result["method"] = "downloaded_with_model"
        print("[TOKENIZER] All OpenVINO tokenizer assets present from download.")
        return result

    # Try generating from tokenizer.json in the target dir
    try:
        import openvino as ov
        from openvino_tokenizers import convert_tokenizer
        from transformers import AutoTokenizer

        if (TARGET_DIR / "tokenizer.json").exists() or (TARGET_DIR / "tokenizer_config.json").exists():
            print("[TOKENIZER] Generating from local tokenizer files...")
            tokenizer = AutoTokenizer.from_pretrained(str(TARGET_DIR), local_files_only=True)
            tok_model, detok_model = convert_tokenizer(tokenizer, with_detokenizer=True)
            ov.save_model(tok_model, str(tok_xml))
            ov.save_model(detok_model, str(detok_xml))
            result["method"] = "generated_from_local_tokenizer"
            result["ok"] = True
            result["tok_xml"] = tok_xml.exists()
            result["tok_bin"] = tok_bin.exists()
            result["detok_xml"] = detok_xml.exists()
            result["detok_bin"] = detok_bin.exists()
            print("[TOKENIZER] Generated OpenVINO tokenizer assets.")
            return result
    except Exception as exc:
        print(f"[TOKENIZER] Generation failed: {exc}")

    # Fallback: copy from existing 0.6B model (same vocab)
    if EXISTING_06B_DIR.exists():
        print("[TOKENIZER] Copying from existing qwen3-0.6b model...")
        try:
            for fname in ["openvino_tokenizer.xml", "openvino_tokenizer.bin",
                          "openvino_detokenizer.xml", "openvino_detokenizer.bin"]:
                src = EXISTING_06B_DIR / fname
                dst = TARGET_DIR / fname
                if src.exists() and not dst.exists():
                    shutil.copy2(str(src), str(dst))
            result["method"] = "copied_from_qwen3_06b"
            result["ok"] = True
            result["tok_xml"] = tok_xml.exists()
            result["tok_bin"] = tok_bin.exists()
            result["detok_xml"] = detok_xml.exists()
            result["detok_bin"] = detok_bin.exists()
            print("[TOKENIZER] Copied from qwen3-0.6b.")
            return result
        except Exception as exc:
            result["error"] = str(exc)

    result["error"] = "Could not obtain tokenizer assets"
    return result


# ---------------------------------------------------------------------------
# Step 5: Standalone GPU smoke test
# ---------------------------------------------------------------------------
def standalone_smoke_test() -> dict[str, Any]:
    """Load pruned model standalone on GPU and run a simple inference."""
    result: dict[str, Any] = {
        "ok": False,
        "device": "GPU",
        "latency_total_ms": None,
        "output_preview": None,
        "rss_after_mb": None,
        "error": None,
    }

    if ov_genai is None:
        result["error"] = "openvino_genai not available"
        return result

    print("[STANDALONE] Loading pruned model on GPU...")
    t0 = time.perf_counter()
    try:
        pipe = ov_genai.LLMPipeline(str(TARGET_DIR), "GPU")
        config = ov_genai.GenerationConfig()
        config.max_new_tokens = 20
        config.do_sample = False

        output = pipe.generate("What is 2+2?", config)
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        text = str(output).strip()

        proc = psutil.Process()
        rss_mb = proc.memory_info().rss / (1024 * 1024)

        result["ok"] = bool(text)
        result["latency_total_ms"] = round(elapsed_ms, 1)
        result["output_preview"] = text[:300]
        result["rss_after_mb"] = round(rss_mb, 1)
        print(f"[STANDALONE] OK: {elapsed_ms:.0f}ms, output={text[:80]!r}")

        del pipe
        gc.collect()
        time.sleep(2)

    except Exception as exc:
        result["error"] = str(exc)
        result["latency_total_ms"] = round((time.perf_counter() - t0) * 1000.0, 1)
        print(f"[STANDALONE] FAIL: {exc}")
        gc.collect()
        time.sleep(2)

    return result


# ---------------------------------------------------------------------------
# Step 6: Speculative decoding smoke test
# ---------------------------------------------------------------------------
def speculative_smoke_test() -> dict[str, Any]:
    """Test pruned INT8 model as draft for Qwen3-14B INT4 target."""
    result: dict[str, Any] = {
        "ok": False,
        "api_pattern": None,
        "latency_total_ms": None,
        "approx_tps": None,
        "output_preview": None,
        "rss_after_mb": None,
        "attempt1_error": None,
        "attempt2_error": None,
    }

    if ov_genai is None:
        result["attempt1_error"] = "openvino_genai not available"
        return result

    if not (MODEL_14B_DIR / "openvino_model.xml").exists():
        result["attempt1_error"] = "Qwen3-14B model not found"
        return result

    max_new_tokens = 50
    prompt = "Write a Python function that adds two numbers."

    # ATTEMPT 1: P5-005b dict-config pattern
    print("[SPEC-DECODE] ATTEMPT 1: P5-005b dict-config pattern...")
    t0 = time.perf_counter()
    try:
        draft = ov_genai.draft_model(str(TARGET_DIR), "GPU")
        pipe = ov_genai.LLMPipeline(
            str(MODEL_14B_DIR), "GPU", {"draft_model": draft},
        )
        gen_config = ov_genai.GenerationConfig()
        gen_config.max_new_tokens = max_new_tokens
        gen_config.num_assistant_tokens = 3
        gen_config.do_sample = False

        output = pipe.generate(prompt, gen_config)
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        text = str(output).strip()

        proc = psutil.Process()
        rss_mb = proc.memory_info().rss / (1024 * 1024)

        result["ok"] = bool(text)
        result["api_pattern"] = "p5_005b_dict_config"
        result["latency_total_ms"] = round(elapsed_ms, 1)
        result["approx_tps"] = round(max_new_tokens / (elapsed_ms / 1000.0), 2) if elapsed_ms > 0 else None
        result["output_preview"] = text[:300]
        result["rss_after_mb"] = round(rss_mb, 1)
        print(f"[SPEC-DECODE] ATTEMPT 1 OK: {elapsed_ms:.0f}ms, ~{result['approx_tps']} TPS")
        print(f"[SPEC-DECODE] Output: {text[:120]!r}")

        del pipe, draft
        gc.collect()
        time.sleep(3)
        return result

    except Exception as exc:
        result["attempt1_error"] = str(exc)
        print(f"[SPEC-DECODE] ATTEMPT 1 FAIL: {exc}")
        gc.collect()
        time.sleep(3)

    # ATTEMPT 2: Model-card SchedulerConfig pattern
    print("[SPEC-DECODE] ATTEMPT 2: SchedulerConfig pattern...")
    t0 = time.perf_counter()
    try:
        draft = ov_genai.draft_model(str(TARGET_DIR), "GPU")
        scheduler_config = ov_genai.SchedulerConfig()
        scheduler_config.cache_size = 2
        pipe = ov_genai.LLMPipeline(
            str(MODEL_14B_DIR), "GPU",
            scheduler_config=scheduler_config,
            draft_model=draft,
        )
        gen_config = ov_genai.GenerationConfig()
        gen_config.max_new_tokens = max_new_tokens
        gen_config.num_assistant_tokens = 3
        gen_config.do_sample = False

        output = pipe.generate(prompt, gen_config)
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        text = str(output).strip()

        proc = psutil.Process()
        rss_mb = proc.memory_info().rss / (1024 * 1024)

        result["ok"] = bool(text)
        result["api_pattern"] = "scheduler_config"
        result["latency_total_ms"] = round(elapsed_ms, 1)
        result["approx_tps"] = round(max_new_tokens / (elapsed_ms / 1000.0), 2) if elapsed_ms > 0 else None
        result["output_preview"] = text[:300]
        result["rss_after_mb"] = round(rss_mb, 1)
        print(f"[SPEC-DECODE] ATTEMPT 2 OK: {elapsed_ms:.0f}ms, ~{result['approx_tps']} TPS")
        print(f"[SPEC-DECODE] Output: {text[:120]!r}")

        del pipe, draft
        gc.collect()
        time.sleep(3)
        return result

    except Exception as exc:
        result["attempt2_error"] = str(exc)
        print(f"[SPEC-DECODE] ATTEMPT 2 FAIL: {exc}")
        gc.collect()
        time.sleep(3)

    return result


# ---------------------------------------------------------------------------
# Step 7: Model integrity snapshot
# ---------------------------------------------------------------------------
def model_integrity_snapshot() -> dict[str, Any]:
    """Compute SHA-256 hashes and file inventory."""
    xml_path = TARGET_DIR / "openvino_model.xml"
    bin_path = TARGET_DIR / "openvino_model.bin"

    result: dict[str, Any] = {
        "dir_exists": TARGET_DIR.exists(),
        "xml_exists": xml_path.exists(),
        "bin_exists": bin_path.exists(),
        "files": {},
        "sha256": {},
        "bin_size_mb": None,
        "comparison_vs_06b": {},
    }

    if not xml_path.exists() or not bin_path.exists():
        return result

    # File inventory
    for f in sorted(TARGET_DIR.iterdir()):
        if f.is_file():
            result["files"][f.name] = f.stat().st_size

    # SHA-256    
    print("[INTEGRITY] Computing SHA-256 hashes...")
    result["sha256"]["openvino_model.bin"] = sha256_file(bin_path)
    result["sha256"]["openvino_model.xml"] = sha256_file(xml_path)

    bin_size_mb = bin_path.stat().st_size / (1024 * 1024)
    result["bin_size_mb"] = round(bin_size_mb, 2)

    # Compare vs existing 0.6B
    existing_bin = EXISTING_06B_DIR / "openvino_model.bin"
    if existing_bin.exists():
        existing_size_mb = existing_bin.stat().st_size / (1024 * 1024)
        result["comparison_vs_06b"] = {
            "pruned_bin_size_mb": round(bin_size_mb, 2),
            "full_06b_bin_size_mb": round(existing_size_mb, 2),
            "ratio": round(bin_size_mb / existing_size_mb, 3) if existing_size_mb > 0 else None,
            "pruned_layers": 22,
            "full_layers": 28,
            "expected_ratio": round(22 / 28, 3),
            "note": "INT8 vs INT4 quantization affects per-layer size, so ratio may differ from layer ratio",
        }

    print(f"[INTEGRITY] bin_size={bin_size_mb:.1f}MB, xml_hash={result['sha256']['openvino_model.xml'][:12]}...")
    return result


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> None:
    print("=" * 70)
    print("P5-005c v2: Acquire Qwen3-pruned-6L-from-0.6B-int8-ov")
    print("=" * 70)

    # Preconditions
    power = enforce_ac_power_or_fail_closed()
    disk_gb = free_disk_gb()
    print(f"[PRE] AC power: {power}, disk free: {disk_gb:.1f} GB")

    if disk_gb < 2.0:
        raise RuntimeError(f"FAIL_CLOSED: Insufficient disk space ({disk_gb:.1f} GB < 2.0 GB)")

    evidence: dict[str, Any] = {
        "metadata": {
            "milestone": "P5-005c-ACQUIRE-v2",
            "timestamp": now_iso(),
            "git_head": git_head(),
            "ac_power": power,
            "disk_free_gb": round(disk_gb, 1),
            "runtime": {
                "openvino_genai": str(ov_genai.__version__) if ov_genai else "N/A",
            },
        },
        "model_source": {
            "hf_repo_id": HF_REPO_ID,
            "quantization_format": "INT8_ASYM",
            "description": "Pre-built OpenVINO IR model published by Intel OpenVINO team. "
                           "6 layers pruned from Qwen3-0.6B (28 -> 22 layers), INT8 weight compression via NNCF.",
        },
    }

    # Step 2: Acquire
    print("\n--- Step 2: Model Acquisition ---")
    acq = acquire_model()
    evidence["download"] = acq
    if not acq["ok"]:
        evidence["disposition"] = "ACQUISITION_FAILED"
        write_json_atomic(OUTPUT_JSON, evidence)
        print(f"\nDISPOSITION: ACQUISITION_FAILED — {acq.get('error')}")
        return

    # Step 3: Architecture validation
    print("\n--- Step 3: Architecture Validation ---")
    arch = validate_architecture()
    evidence["architecture_validation"] = arch
    if not arch["ok"]:
        evidence["disposition"] = "INCOMPATIBLE"
        write_json_atomic(OUTPUT_JSON, evidence)
        print(f"\nDISPOSITION: INCOMPATIBLE — {arch.get('error')}")
        return

    # Step 4: Tokenizer  
    print("\n--- Step 4: Tokenizer Validation ---")
    tok = validate_tokenizer()
    evidence["tokenizer"] = tok
    if not tok["ok"]:
        print(f"[WARN] Tokenizer issues: {tok.get('error')}. Proceeding — smoke test will reveal if critical.")

    # Step 5: Standalone smoke
    print("\n--- Step 5: Standalone GPU Smoke Test ---")
    standalone = standalone_smoke_test()
    evidence["standalone_smoke"] = standalone

    # Step 6: Speculative decoding smoke
    print("\n--- Step 6: Speculative Decoding Smoke Test ---")
    spec = speculative_smoke_test()
    evidence["speculative_smoke"] = spec

    # Step 7: Integrity
    print("\n--- Step 7: Model Integrity Snapshot ---")
    integrity = model_integrity_snapshot()
    evidence["integrity"] = integrity

    # Determine disposition
    if standalone.get("ok") and spec.get("ok"):
        disposition = "READY_FOR_BENCHMARK"
    elif standalone.get("ok") and not spec.get("ok"):
        disposition = "STANDALONE_ONLY"
    elif not standalone.get("ok") and not spec.get("ok"):
        disposition = "ACQUISITION_FAILED"
    else:
        disposition = "STANDALONE_ONLY"

    evidence["disposition"] = disposition
    evidence["metadata"]["completion_timestamp"] = now_iso()

    write_json_atomic(OUTPUT_JSON, evidence)
    print(f"\n{'=' * 70}")
    print(f"DISPOSITION: {disposition}")
    print(f"Evidence written to: {OUTPUT_JSON}")
    print(f"{'=' * 70}")


if __name__ == "__main__":
    main()
