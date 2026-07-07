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
import traceback
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
OUTPUT_JSON = EVIDENCE_DIR / "p5_005c_pruned_draft_acquisition.json"

TARGET_DIR = ROOT / "models" / "qwen3-0.6b-pruned-6l" / "openvino-int4-gpu"
TARGET_MODEL_14B = ROOT / "models" / "qwen3-14b" / "openvino-int4-gpu"
BASE_06B_DIR = ROOT / "models" / "qwen3-0.6b" / "openvino-int4-gpu"

EXPECTED_ARCH = "Qwen3ForCausalLM"
EXPECTED_VOCAB = 151936
EXPECTED_HIDDEN = 1024
EXPECTED_LAYERS = 6
MIN_DISK_GB = 5.0


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
        raise RuntimeError("POWER_ENVELOPE_NOT_LOCKED: AC power required for P5-005c acquisition")
    return state


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


def list_python_processes() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for proc in psutil.process_iter(["pid", "name", "create_time", "memory_info", "cmdline"]):
        try:
            info = proc.info
            name = str(info.get("name", "")).lower()
            if "python" not in name:
                continue
            rows.append(
                {
                    "pid": int(info["pid"]),
                    "name": info.get("name"),
                    "rss_mb": round(float(getattr(info.get("memory_info"), "rss", 0.0)) / (1024**2), 2),
                    "command_line": " ".join(str(x) for x in (info.get("cmdline") or [])),
                }
            )
        except Exception:
            continue
    return rows


def dir_has_model(path: Path) -> bool:
    return (path / "openvino_model.xml").exists() and (path / "openvino_model.bin").exists()


def normalize_error(prefix: str, text: str) -> str:
    normalized = "".join(ch if ch.isalnum() else "_" for ch in text.upper())
    normalized = "_".join(part for part in normalized.split("_") if part)
    return f"{prefix}_{normalized[:160]}"


def discover_candidate_repos() -> dict[str, Any]:
    if huggingface_hub is None:
        raise RuntimeError("HUGGINGFACE_HUB_NOT_AVAILABLE")

    api = huggingface_hub.HfApi()
    explicit_ids = [
        "Qwen/Qwen3-0.6B-pruned-6L",
        "Qwen/Qwen3-pruned-6L-from-0.6B",
        "OpenVINO/Qwen3-pruned-6L-from-0.6B-int8-ov",
    ]
    search_queries = [
        "Qwen3 pruned 6L 0.6B",
        "Qwen3 pruned speculative",
        "Qwen3-pruned-6L-from-0.6B",
    ]

    rows: list[dict[str, Any]] = []
    candidate_ids: set[str] = set(explicit_ids)

    for q in search_queries:
        t0 = time.perf_counter()
        found = list(api.list_models(search=q, limit=40))
        elapsed = (time.perf_counter() - t0) * 1000.0
        ids = [m.id for m in found if getattr(m, "id", None)]
        for rid in ids:
            candidate_ids.add(rid)
        rows.append({"query": q, "elapsed_ms": round(elapsed, 2), "result_count": len(ids), "ids": ids})

    return {
        "searches": rows,
        "candidate_ids": sorted(candidate_ids),
    }


def fetch_repo_config(repo_id: str) -> tuple[dict[str, Any] | None, str | None]:
    if huggingface_hub is None:
        return None, "HUGGINGFACE_HUB_NOT_AVAILABLE"

    try:
        cfg_path = huggingface_hub.hf_hub_download(repo_id=repo_id, filename="config.json")
    except Exception as exc:  # noqa: BLE001
        return None, str(exc)

    with open(cfg_path, "r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        return None, "CONFIG_NOT_OBJECT"
    return payload, None


def validate_config(repo_id: str, config: dict[str, Any]) -> dict[str, Any]:
    arch_value = config.get("architectures")
    architectures = arch_value if isinstance(arch_value, list) else []
    arch_ok = EXPECTED_ARCH in architectures
    vocab = int(config.get("vocab_size", -1)) if isinstance(config.get("vocab_size"), int | float) else None
    hidden = int(config.get("hidden_size", -1)) if isinstance(config.get("hidden_size"), int | float) else None
    layers = int(config.get("num_hidden_layers", -1)) if isinstance(config.get("num_hidden_layers"), int | float) else None
    vocab_ok = vocab == EXPECTED_VOCAB
    hidden_ok = hidden == EXPECTED_HIDDEN
    layers_close = layers is not None and 0 < layers < 28
    layers_exact = layers == EXPECTED_LAYERS

    return {
        "repo_id": repo_id,
        "architectures": architectures,
        "model_type": config.get("model_type"),
        "vocab_size": vocab,
        "hidden_size": hidden,
        "num_hidden_layers": layers,
        "validation": {
            "architecture_ok": arch_ok,
            "vocab_ok": vocab_ok,
            "hidden_ok": hidden_ok,
            "layers_exact": layers_exact,
            "layers_close": layers_close,
            "compatible": arch_ok and vocab_ok and hidden_ok and layers_close,
        },
    }


def select_repo(discovery: dict[str, Any]) -> dict[str, Any]:
    evaluations: list[dict[str, Any]] = []
    selected: dict[str, Any] | None = None
    best_score = -1

    for repo_id in discovery.get("candidate_ids", []):
        config, error = fetch_repo_config(repo_id)
        if error is not None:
            evaluations.append({"repo_id": repo_id, "fetch_ok": False, "error": error})
            continue
        assert config is not None
        validation = validate_config(repo_id, config)
        score = 0
        v = validation["validation"]
        if v["architecture_ok"]:
            score += 4
        if v["vocab_ok"]:
            score += 4
        if v["hidden_ok"]:
            score += 3
        if v["layers_exact"]:
            score += 4
        elif v["layers_close"]:
            score += 2

        evaluations.append({"repo_id": repo_id, "fetch_ok": True, "config": config, **validation})
        if validation["validation"]["compatible"] and score > best_score:
            best_score = score
            selected = {"repo_id": repo_id, "config": config, "validation": validation, "score": score}

    return {
        "evaluations": evaluations,
        "selected": selected,
    }


def strategy_a_prequantized_download(repo_id: str, output_dir: Path) -> dict[str, Any]:
    if huggingface_hub is None:
        raise RuntimeError("HUGGINGFACE_HUB_NOT_AVAILABLE")

    if "int4" not in repo_id.lower():
        raise RuntimeError("PREQUANTIZED_REPO_NOT_INT4")

    output_dir.mkdir(parents=True, exist_ok=True)
    downloaded = huggingface_hub.snapshot_download(
        repo_id=repo_id,
        local_dir=str(output_dir),
        local_dir_use_symlinks=False,
        allow_patterns=["*openvino_model.xml", "*openvino_model.bin", "*.json", "tokenizer*", "*.model", "*.txt"],
    )
    if not dir_has_model(output_dir):
        raise RuntimeError("PREQUANTIZED_OPENVINO_FILES_MISSING")
    return {"download_path": downloaded}


def strategy_b_optimum_cli_export(repo_id: str, output_dir: Path) -> dict[str, Any]:
    cmd = [
        str(ROOT / ".venv" / "Scripts" / "optimum-cli.exe"),
        "export",
        "openvino",
        "--model",
        repo_id,
        "--weight-format",
        "int4",
        "--group-size",
        "128",
        "--ratio",
        "1.0",
        "--sym",
        "false",
        "--num-calibration-samples",
        "16",
        str(output_dir),
    ]
    t0 = time.perf_counter()
    proc = subprocess.run(cmd, cwd=ROOT, text=True, capture_output=True, check=False)
    elapsed = time.perf_counter() - t0
    if proc.returncode != 0:
        raise RuntimeError(f"OPTIMUM_CLI_EXPORT_FAILED: rc={proc.returncode} stderr={proc.stderr[-2500:]}")
    if not dir_has_model(output_dir):
        raise RuntimeError("OPTIMUM_CLI_EXPORT_INCOMPLETE")
    return {"elapsed_s": round(elapsed, 2), "stdout_tail": proc.stdout[-2000:]}


def strategy_c_python_api_export(repo_id: str, output_dir: Path) -> dict[str, Any]:
    ensure_optimum_openvino_compatibility()
    from optimum.intel import OVModelForCausalLM

    t0 = time.perf_counter()
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", category=FutureWarning)
        warnings.filterwarnings("ignore", category=DeprecationWarning)
        model = OVModelForCausalLM.from_pretrained(
            repo_id,
            export=True,
            compile=False,
            load_in_4bit=True,
            quantization_config={"bits": 4, "sym": False, "group_size": 128, "ratio": 1.0},
        )
    model.save_pretrained(str(output_dir))
    tokenizer = AutoTokenizer.from_pretrained(repo_id)
    tokenizer.save_pretrained(str(output_dir))
    elapsed = time.perf_counter() - t0
    if not dir_has_model(output_dir):
        raise RuntimeError("PYTHON_API_EXPORT_INCOMPLETE")
    return {"elapsed_s": round(elapsed, 2)}


def strategy_d_raw_then_convert(repo_id: str, output_dir: Path) -> dict[str, Any]:
    if huggingface_hub is None:
        raise RuntimeError("HUGGINGFACE_HUB_NOT_AVAILABLE")

    raw_dir = output_dir.parent / "raw-hf"
    raw_dir.mkdir(parents=True, exist_ok=True)
    downloaded = huggingface_hub.snapshot_download(
        repo_id=repo_id,
        local_dir=str(raw_dir),
        local_dir_use_symlinks=False,
    )

    try:
        details = strategy_b_optimum_cli_export(str(raw_dir), output_dir)
        return {"raw_download_path": downloaded, "convert_path": "int4_direct", **details}
    except Exception as first_exc:  # noqa: BLE001
        fp16_dir = output_dir.parent / "fp16-export"
        cmd_fp16 = [
            str(ROOT / ".venv" / "Scripts" / "optimum-cli.exe"),
            "export",
            "openvino",
            "--model",
            str(raw_dir),
            "--weight-format",
            "fp16",
            str(fp16_dir),
        ]
        proc = subprocess.run(cmd_fp16, cwd=ROOT, text=True, capture_output=True, check=False)
        if proc.returncode != 0:
            raise RuntimeError(
                f"RAW_FP16_EXPORT_FAILED after int4 failure ({first_exc}): rc={proc.returncode} stderr={proc.stderr[-2000:]}"
            )
        details = strategy_c_python_api_export(str(raw_dir), output_dir)
        return {
            "raw_download_path": downloaded,
            "convert_path": "fp16_then_python_quant",
            "fp16_stdout_tail": proc.stdout[-1000:],
            **details,
        }


def strategy_e_copy_modify_placeholder() -> dict[str, Any]:
    raise RuntimeError("STRATEGY_E_NOT_IMPLEMENTED: Layer-pruning from existing OpenVINO weights is non-trivial and unsafe")


def ensure_openvino_tokenizer_assets(model_dir: Path) -> dict[str, Any]:
    tok_xml = model_dir / "openvino_tokenizer.xml"
    tok_bin = model_dir / "openvino_tokenizer.bin"
    detok_xml = model_dir / "openvino_detokenizer.xml"
    detok_bin = model_dir / "openvino_detokenizer.bin"

    if tok_xml.exists() and tok_bin.exists() and detok_xml.exists() and detok_bin.exists():
        return {"status": "present"}

    if convert_tokenizer is not None and ov is not None:
        tokenizer = AutoTokenizer.from_pretrained(str(model_dir), local_files_only=True)
        tok_model, detok_model = convert_tokenizer(tokenizer, with_detokenizer=True)
        ov.save_model(tok_model, str(tok_xml))
        ov.save_model(detok_model, str(detok_xml))
        return {"status": "generated_with_convert_tokenizer"}

    copied: list[str] = []
    for name in ["openvino_tokenizer.xml", "openvino_tokenizer.bin", "openvino_detokenizer.xml", "openvino_detokenizer.bin"]:
        src = BASE_06B_DIR / name
        dst = model_dir / name
        if src.exists():
            shutil.copy2(src, dst)
            copied.append(name)

    if tok_xml.exists() and tok_bin.exists() and detok_xml.exists() and detok_bin.exists():
        return {"status": "copied_from_qwen3_0_6b", "copied_files": copied}

    raise RuntimeError("TOKENIZER_ASSETS_UNAVAILABLE")


def quick_inference_smoke(model_dir: Path, device: str, max_new_tokens: int) -> dict[str, Any]:
    prompt = "Confirm offline draft-model readiness in one short sentence."
    proc = psutil.Process()
    rss_before = proc.memory_info().rss / (1024 * 1024)
    t0 = time.perf_counter()

    pipe = ov_genai.LLMPipeline(str(model_dir), device, {})
    config = ov_genai.GenerationConfig()
    config.max_new_tokens = max_new_tokens
    config.do_sample = False
    try:
        config.temperature = 0.0
        config.top_p = 1.0
        config.top_k = 1
    except Exception:
        pass

    first_token_t: float | None = None

    def stream_cb(chunk: str) -> bool:
        nonlocal first_token_t
        if first_token_t is None and chunk:
            first_token_t = time.perf_counter()
        return False

    try:
        output = pipe.generate(prompt, config, stream_cb)
    except TypeError:
        output = pipe.generate(prompt, config)
    elapsed_ms = (time.perf_counter() - t0) * 1000.0
    ttft_ms = ((first_token_t - t0) * 1000.0) if first_token_t is not None else elapsed_ms
    text = str(output).strip()
    if not text:
        raise RuntimeError("EMPTY_GENERATION")

    rss_after = proc.memory_info().rss / (1024 * 1024)
    del pipe
    gc.collect()

    return {
        "ok": True,
        "latency_total_ms": elapsed_ms,
        "ttft_ms": ttft_ms,
        "decode_tps": 0.0,
        "rss_before_mb": rss_before,
        "rss_after_mb": rss_after,
        "output_preview": text[:400],
    }


def speculative_smoke(main_model_dir: Path, draft_model_dir: Path) -> dict[str, Any]:
    proc = psutil.Process()
    rss_before = proc.memory_info().rss / (1024 * 1024)
    prompt = "List three words confirming speculative decoding startup."

    if not hasattr(ov_genai, "draft_model"):
        raise RuntimeError("DRAFT_MODEL_API_NOT_AVAILABLE")

    pipeline_kwargs = {"draft_model": ov_genai.draft_model(str(draft_model_dir), "GPU")}
    t0 = time.perf_counter()
    pipe = ov_genai.LLMPipeline(str(main_model_dir), "GPU", pipeline_kwargs)

    cfg = ov_genai.GenerationConfig()
    cfg.max_new_tokens = 50
    cfg.do_sample = False
    try:
        cfg.temperature = 0.0
        cfg.top_p = 1.0
        cfg.top_k = 1
        cfg.num_assistant_tokens = 3
        cfg.assistant_confidence_threshold = 0.0
    except Exception:
        pass

    first_token_t: float | None = None

    def stream_cb(chunk: str) -> bool:
        nonlocal first_token_t
        if first_token_t is None and chunk:
            first_token_t = time.perf_counter()
        return False

    try:
        out = pipe.generate(prompt, cfg, stream_cb)
    except TypeError:
        out = pipe.generate(prompt, cfg)

    total_ms = (time.perf_counter() - t0) * 1000.0
    ttft_ms = ((first_token_t - t0) * 1000.0) if first_token_t is not None else total_ms
    text = str(out).strip()
    if not text:
        raise RuntimeError("SPECULATIVE_EMPTY_OUTPUT")

    tokenizer = AutoTokenizer.from_pretrained(str(main_model_dir), local_files_only=True)
    token_count = int(len(tokenizer(text, return_tensors="np")["input_ids"][0]))
    decode_ms = max(total_ms - ttft_ms, 1.0)
    decode_tps = (token_count / (decode_ms / 1000.0)) if decode_ms > 0 else 0.0
    rss_after = proc.memory_info().rss / (1024 * 1024)

    del pipe
    gc.collect()

    return {
        "ok": True,
        "ttft_ms": ttft_ms,
        "latency_total_ms": total_ms,
        "decode_tps": decode_tps,
        "rss_before_mb": rss_before,
        "rss_after_mb": rss_after,
        "output_text": text[:700],
    }


def model_integrity_snapshot(path: Path) -> dict[str, Any]:
    xml_path = path / "openvino_model.xml"
    bin_path = path / "openvino_model.bin"
    cfg_path = path / "config.json"
    base_bin_path = BASE_06B_DIR / "openvino_model.bin"

    checks = {
        "dir_exists": path.exists(),
        "xml_exists": xml_path.exists(),
        "bin_exists": bin_path.exists(),
        "config_exists": cfg_path.exists(),
    }
    listing = []
    if path.exists():
        for p in sorted(path.glob("*")):
            if p.is_file():
                listing.append({"name": p.name, "size_bytes": p.stat().st_size})

    result: dict[str, Any] = {"checks": checks, "file_listing": listing}
    if not checks["xml_exists"] or not checks["bin_exists"]:
        return result

    bin_size_mb = float(bin_path.stat().st_size) / (1024**2)
    base_size_mb = float(base_bin_path.stat().st_size) / (1024**2) if base_bin_path.exists() else None
    ratio = (bin_size_mb / base_size_mb) if base_size_mb and base_size_mb > 0 else None

    cfg_payload: dict[str, Any] | None = None
    if cfg_path.exists():
        with open(cfg_path, "r", encoding="utf-8") as handle:
            loaded = json.load(handle)
        if isinstance(loaded, dict):
            cfg_payload = loaded

    result.update(
        {
            "bin_size_mb": round(bin_size_mb, 2),
            "baseline_06b_bin_size_mb": round(base_size_mb, 2) if base_size_mb is not None else None,
            "size_ratio_vs_06b": round(ratio, 4) if ratio is not None else None,
            "expected_pruned_size_mb": {"min": 50.0, "max": 80.0},
            "sha256": {
                "openvino_model.bin": sha256_file(bin_path),
                "openvino_model.xml": sha256_file(xml_path),
            },
            "config": cfg_payload,
        }
    )
    return result


def environment_metadata() -> dict[str, Any]:
    disk = shutil.disk_usage("C:\\")
    return {
        "timestamp_utc": now_iso(),
        "commit_hash": git_head(),
        "platform": platform.platform(),
        "python": sys.version,
        "openvino_version": getattr(ov, "__version__", "unavailable") if ov is not None else "unavailable",
        "openvino_genai_version": getattr(ov_genai, "__version__", "unknown"),
        "ac_power": enforce_ac_power_or_fail_closed(),
        "disk": {
            "path": "C:\\",
            "free_bytes": int(disk.free),
            "free_gb": round(float(disk.free) / (1024**3), 2),
            "required_min_gb": MIN_DISK_GB,
            "requirement_met": float(disk.free) / (1024**3) >= MIN_DISK_GB,
        },
    }


def acquire_model(repo_id: str, evidence: dict[str, Any]) -> tuple[str, str | None]:
    attempts: list[dict[str, Any]] = []
    strategy_used: str | None = None

    def run_strategy(name: str, fn: Any) -> bool:
        nonlocal strategy_used
        t0 = time.perf_counter()
        try:
            details = fn()
            attempts.append(
                {
                    "strategy": name,
                    "status": "success",
                    "elapsed_s": round(time.perf_counter() - t0, 2),
                    "details": details,
                }
            )
            strategy_used = name
            return True
        except Exception as exc:  # noqa: BLE001
            attempts.append(
                {
                    "strategy": name,
                    "status": "failed",
                    "elapsed_s": round(time.perf_counter() - t0, 2),
                    "error": str(exc),
                    "error_fingerprint": normalize_error("ACQUIRE", str(exc)),
                    "traceback": traceback.format_exc(),
                }
            )
            return False

    if run_strategy("A_PREQUANTIZED_OPENVINO_DOWNLOAD", lambda: strategy_a_prequantized_download(repo_id, TARGET_DIR)):
        evidence["acquisition"] = {"attempts": attempts, "strategy_used": strategy_used}
        return "converted", strategy_used

    if run_strategy("B_OPTIMUM_CLI_EXPORT_INT4", lambda: strategy_b_optimum_cli_export(repo_id, TARGET_DIR)):
        evidence["acquisition"] = {"attempts": attempts, "strategy_used": strategy_used}
        return "converted", strategy_used

    if run_strategy("C_PYTHON_API_EXPORT_INT4", lambda: strategy_c_python_api_export(repo_id, TARGET_DIR)):
        evidence["acquisition"] = {"attempts": attempts, "strategy_used": strategy_used}
        return "converted", strategy_used

    if run_strategy("D_RAW_DOWNLOAD_THEN_CONVERT", lambda: strategy_d_raw_then_convert(repo_id, TARGET_DIR)):
        evidence["acquisition"] = {"attempts": attempts, "strategy_used": strategy_used}
        return "converted", strategy_used

    run_strategy("E_COPY_AND_MODIFY_FROM_06B", strategy_e_copy_modify_placeholder)
    evidence["acquisition"] = {"attempts": attempts, "strategy_used": strategy_used}
    return "failed", strategy_used


def main() -> None:
    metadata = environment_metadata()
    if not metadata["disk"]["requirement_met"]:
        raise RuntimeError("DISK_SPACE_INSUFFICIENT: Require at least 5GB free on C:\\")

    evidence: dict[str, Any] = {
        "milestone": "P5-005c-ACQUIRE",
        "name": "Qwen3 pruned 6L draft model acquisition and readiness validation",
        "metadata": metadata,
        "phase0_state": {
            "python_processes": list_python_processes(),
        },
        "discovery": {},
        "acquisition": {},
        "tokenizer_assets": {},
        "integrity": {},
        "standalone_smoke": {},
        "speculative_smoke": {},
        "status": "in_progress",
        "disposition": None,
        "started_utc": now_iso(),
    }
    write_json_atomic(OUTPUT_JSON, evidence)

    discovery = discover_candidate_repos()
    selection = select_repo(discovery)
    evidence["discovery"] = {
        **discovery,
        "selection": selection,
    }
    write_json_atomic(OUTPUT_JSON, evidence)

    selected = selection.get("selected")
    if not isinstance(selected, dict):
        evidence["status"] = "blocked"
        evidence["disposition"] = "ACQUISITION_FAILED"
        evidence["failure_reason"] = "MODEL_NOT_FOUND_ON_HF"
        evidence["finished_utc"] = now_iso()
        write_json_atomic(OUTPUT_JSON, evidence)
        print(json.dumps({"status": evidence["status"], "disposition": evidence["disposition"], "artifact": str(OUTPUT_JSON)}, indent=2))
        return

    selected_repo = str(selected["repo_id"])
    selected_validation = selected["validation"]["validation"]
    if not bool(selected_validation["compatible"]):
        evidence["status"] = "blocked"
        evidence["disposition"] = "INCOMPATIBLE"
        evidence["failure_reason"] = "ARCH_OR_VOCAB_OR_DIMENSION_MISMATCH"
        evidence["finished_utc"] = now_iso()
        write_json_atomic(OUTPUT_JSON, evidence)
        print(json.dumps({"status": evidence["status"], "disposition": evidence["disposition"], "artifact": str(OUTPUT_JSON)}, indent=2))
        return

    acquisition_status, strategy_used = acquire_model(selected_repo, evidence)
    write_json_atomic(OUTPUT_JSON, evidence)

    if acquisition_status != "converted" or not dir_has_model(TARGET_DIR):
        evidence["status"] = "blocked"
        evidence["disposition"] = "ACQUISITION_FAILED"
        evidence["failure_reason"] = "MODEL_ACQUISITION_ALL_STRATEGIES_FAILED"
        evidence["finished_utc"] = now_iso()
        write_json_atomic(OUTPUT_JSON, evidence)
        print(json.dumps({"status": evidence["status"], "disposition": evidence["disposition"], "artifact": str(OUTPUT_JSON)}, indent=2))
        return

    try:
        evidence["tokenizer_assets"] = ensure_openvino_tokenizer_assets(TARGET_DIR)
    except Exception as exc:  # noqa: BLE001
        evidence["tokenizer_assets"] = {
            "status": "failed",
            "error": str(exc),
            "traceback": traceback.format_exc(),
        }

    evidence["integrity"] = model_integrity_snapshot(TARGET_DIR)

    try:
        evidence["standalone_smoke"] = quick_inference_smoke(TARGET_DIR, "GPU", 20)
    except Exception as exc:  # noqa: BLE001
        evidence["standalone_smoke"] = {
            "ok": False,
            "error": str(exc),
            "error_fingerprint": normalize_error("STANDALONE", str(exc)),
            "traceback": traceback.format_exc(),
        }

    try:
        evidence["speculative_smoke"] = speculative_smoke(TARGET_MODEL_14B, TARGET_DIR)
    except Exception as exc:  # noqa: BLE001
        evidence["speculative_smoke"] = {
            "ok": False,
            "error": str(exc),
            "error_fingerprint": normalize_error("SPECULATIVE", str(exc)),
            "traceback": traceback.format_exc(),
        }

    standalone_ok = bool(evidence.get("standalone_smoke", {}).get("ok"))
    speculative_ok = bool(evidence.get("speculative_smoke", {}).get("ok"))

    if standalone_ok and speculative_ok:
        disposition = "READY_FOR_BENCHMARK"
        status = "completed"
    elif standalone_ok and not speculative_ok:
        disposition = "STANDALONE_ONLY"
        status = "completed"
    elif acquisition_status != "converted":
        disposition = "ACQUISITION_FAILED"
        status = "blocked"
    else:
        disposition = "ACQUISITION_FAILED"
        status = "blocked"

    evidence["status"] = status
    evidence["disposition"] = disposition
    evidence["strategy_used"] = strategy_used
    evidence["finished_utc"] = now_iso()
    write_json_atomic(OUTPUT_JSON, evidence)

    print(
        json.dumps(
            {
                "status": evidence["status"],
                "disposition": evidence["disposition"],
                "strategy_used": evidence.get("strategy_used"),
                "artifact": str(OUTPUT_JSON),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
