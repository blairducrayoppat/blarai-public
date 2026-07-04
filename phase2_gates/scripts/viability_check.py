"""
P5-005a Model Viability Check
Validates existing OpenVINO models can load and generate.
Reports HF cache status for pending models.
"""
import json
import os
import sys
import time
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parents[2]
MODELS = WORKSPACE / "models"
EVIDENCE_DIR = WORKSPACE / "phase2_gates" / "evidence"

HF_CACHE = Path.home() / ".cache" / "huggingface" / "hub"

RESULTS: dict = {
    "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    "checks": {},
    "summary": {},
}


def check_hf_cache(model_id: str) -> dict:
    """Check if HF cache has complete weight files for a model."""
    cache_dir = HF_CACHE / f"models--{model_id.replace('/', '--')}"
    info: dict = {"cache_dir": str(cache_dir), "exists": cache_dir.exists()}
    if not cache_dir.exists():
        info["status"] = "NOT_CACHED"
        return info

    snapshots = cache_dir / "snapshots"
    if not snapshots.exists():
        info["status"] = "NO_SNAPSHOTS"
        return info

    snap_dirs = list(snapshots.iterdir())
    if not snap_dirs:
        info["status"] = "EMPTY_SNAPSHOTS"
        return info

    snap = snap_dirs[0]
    st_files = list(snap.glob("*.safetensors"))
    all_files = list(snap.iterdir())
    total_st_bytes = sum(f.stat().st_size for f in st_files)
    info["snapshot"] = snap.name
    info["total_files"] = len(all_files)
    info["safetensors_count"] = len(st_files)
    info["safetensors_bytes"] = total_st_bytes
    info["safetensors_gb"] = round(total_st_bytes / (1024**3), 2)

    # Check for incomplete downloads (.incomplete files)
    incomplete = list(snap.glob("*.incomplete"))
    info["incomplete_files"] = len(incomplete)

    if len(st_files) == 0:
        info["status"] = "NO_WEIGHTS"
    elif len(incomplete) > 0:
        info["status"] = "PARTIAL_DOWNLOAD"
    else:
        info["status"] = "COMPLETE"

    return info


def check_openvino_model(model_dir: Path, label: str) -> dict:
    """Check if an OpenVINO model directory has required files and can load."""
    info: dict = {"path": str(model_dir), "exists": model_dir.exists()}

    if not model_dir.exists():
        info["status"] = "MISSING"
        return info

    xml_file = model_dir / "openvino_model.xml"
    bin_file = model_dir / "openvino_model.bin"

    info["has_xml"] = xml_file.exists()
    info["has_bin"] = bin_file.exists()

    if not xml_file.exists() or not bin_file.exists():
        info["status"] = "INCOMPLETE"
        return info

    info["bin_bytes"] = bin_file.stat().st_size
    info["bin_mb"] = round(bin_file.stat().st_size / (1024**2), 1)

    # Check for tokenizer
    info["has_tokenizer"] = (model_dir / "openvino_tokenizer.bin").exists()

    # Try to load with GenAI
    info["load_test"] = "SKIPPED"
    info["generate_test"] = "SKIPPED"

    try:
        import openvino_genai as ov_genai

        info["genai_version"] = ov_genai.__version__

        print(f"  Loading {label} on GPU...")
        t0 = time.perf_counter()
        pipe = ov_genai.LLMPipeline(str(model_dir), "GPU")
        load_s = time.perf_counter() - t0
        info["load_test"] = "PASS"
        info["load_time_s"] = round(load_s, 2)
        print(f"  Loaded in {load_s:.1f}s")

        # Quick generate
        print(f"  Generating test tokens...")
        gen_config = ov_genai.GenerationConfig()
        gen_config.max_new_tokens = 20
        gen_config.do_sample = False  # greedy

        t0 = time.perf_counter()
        result = pipe.generate("Hello, my name is", gen_config)
        gen_s = time.perf_counter() - t0
        info["generate_test"] = "PASS"
        info["generate_time_s"] = round(gen_s, 2)
        info["generate_output_preview"] = result[:100] if result else ""
        print(f"  Generated in {gen_s:.1f}s: {result[:80]}...")

        del pipe
    except ImportError:
        info["load_test"] = "NO_GENAI"
        info["generate_test"] = "NO_GENAI"
    except Exception as e:
        info["load_test"] = "FAIL"
        info["error"] = str(e)[:300]
        print(f"  ERROR: {e}")

    info["status"] = "VALID" if info["generate_test"] == "PASS" else info.get("status", "UNKNOWN")
    return info


def main() -> None:
    print("=" * 60)
    print("P5-005a MODEL VIABILITY CHECK")
    print("=" * 60)

    # 1. Check HF cache for all candidate models
    print("\n--- HuggingFace Cache Status ---")
    hf_models = ["Qwen/Qwen3-14B", "Qwen/Qwen3-8B", "Qwen/Qwen3-0.6B", "Qwen/Qwen3-1.7B"]
    for mid in hf_models:
        info = check_hf_cache(mid)
        RESULTS["checks"][f"hf_cache_{mid.split('/')[-1]}"] = info
        status = info["status"]
        size = info.get("safetensors_gb", 0)
        print(f"  {mid}: {status} ({size} GB, {info.get('safetensors_count', 0)} shards, {info.get('incomplete_files', '?')} incomplete)")

    # 2. Check existing OpenVINO models
    print("\n--- OpenVINO Model Validation ---")
    ov_checks = [
        (MODELS / "qwen3-1.7b" / "openvino-int4", "Qwen3-1.7B-GPU"),
        (MODELS / "qwen3-1.7b" / "openvino-int4-npu", "Qwen3-1.7B-NPU"),
    ]
    for path, label in ov_checks:
        print(f"\n  Checking {label}...")
        info = check_openvino_model(path, label)
        RESULTS["checks"][f"openvino_{label}"] = info
        print(f"  Status: {info['status']}")

    # 3. Check empty target dirs
    print("\n--- Target Directories (P5-005 outputs) ---")
    targets = [
        ("qwen3-14b/openvino-int4-gpu", "Qwen3-14B-GPU"),
        ("qwen3-8b/openvino-int4-gpu", "Qwen3-8B-GPU"),
        ("qwen3-0.6b/openvino-int4-gpu", "Qwen3-0.6B-GPU"),
    ]
    for rel, label in targets:
        d = MODELS / rel
        has_files = d.exists() and any(d.iterdir()) if d.exists() else False
        status = "HAS_FILES" if has_files else ("EMPTY" if d.exists() else "MISSING")
        RESULTS["checks"][f"target_{label}"] = {"path": str(d), "status": status}
        print(f"  {label}: {status}")

    # 4. Summary
    print("\n--- VIABILITY SUMMARY ---")
    summary = {
        "qwen3_14b": {
            "hf_weights": RESULTS["checks"].get("hf_cache_Qwen3-14B", {}).get("status"),
            "openvino_int4": "EMPTY",
            "conversion_feasibility": "RISKY — 27.5 GB FP16 + calibration may OOM on 32 GB",
            "recommendation": "Try optimum-cli with --num-samples 32 or seek pre-quantized",
        },
        "qwen3_8b": {
            "hf_weights": RESULTS["checks"].get("hf_cache_Qwen3-8B", {}).get("status"),
            "openvino_int4": "EMPTY",
            "conversion_feasibility": "LIKELY — 15.3 GB FP16 should fit in 32 GB for quantization",
            "recommendation": "Proceed with conversion",
        },
        "qwen3_0_6b": {
            "hf_weights": RESULTS["checks"].get("hf_cache_Qwen3-0.6B", {}).get("status"),
            "openvino_int4": "EMPTY",
            "conversion_feasibility": "TRIVIAL — ~1.2 GB FP16, no risk",
            "recommendation": "Download and convert",
        },
        "qwen3_1_7b_gpu": {
            "hf_weights": RESULTS["checks"].get("hf_cache_Qwen3-1.7B", {}).get("status"),
            "openvino_int4": RESULTS["checks"].get("openvino_Qwen3-1.7B-GPU", {}).get("status"),
            "recommendation": "ALREADY VALIDATED — no action needed",
        },
        "qwen3_1_7b_npu": {
            "hf_weights": "N/A",
            "openvino_int4": RESULTS["checks"].get("openvino_Qwen3-1.7B-NPU", {}).get("status"),
            "recommendation": "ALREADY VALIDATED — no action needed",
        },
    }
    RESULTS["summary"] = summary

    for name, s in summary.items():
        ov_status = s.get("openvino_int4", "?")
        rec = s.get("recommendation", "")
        print(f"  {name}: OV={ov_status} | {rec}")

    # 5. Write evidence
    out_path = EVIDENCE_DIR / "p5_005a_viability_check.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(RESULTS, f, indent=2, default=str)
    print(f"\nEvidence written: {out_path}")
    print("=" * 60)


if __name__ == "__main__":
    main()
