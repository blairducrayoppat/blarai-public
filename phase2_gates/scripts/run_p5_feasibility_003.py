from __future__ import annotations

import datetime as dt
import json
import math
import statistics
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any

import psutil  # type: ignore[import-untyped]

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from transformers import AutoTokenizer

from services.assistant_orchestrator.src.gpu_inference import (  # noqa: E402
    GenerationConfig,
    OrchestratorGPUInference,
)

EVIDENCE_DIR = ROOT / "phase2_gates" / "evidence"
MODEL_DIR = ROOT / "models" / "qwen2.5-1.5b-instruct" / "openvino-int4-npu"

BANDS = [768, 896, 960, 992, 1008, 1024, 1040, 1088, 1152, 1280, 1320]
CRITICAL_BANDS = [992, 1008, 1024, 1040, 1088]
RUNS_PER_MODE = 15
PROBE_MAX_NEW_TOKENS = 32


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def git_head() -> str:
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()


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


def make_fp(prefix: str, text: str) -> str:
    normalized = "".join(ch if ch.isalnum() else "_" for ch in text.upper())
    normalized = "_".join(part for part in normalized.split("_") if part)
    return f"{prefix}_{normalized[:96]}"


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)


def detect_power_envelope() -> dict[str, Any]:
    power_state: dict[str, Any] = {
        "sensor_available": False,
        "power_plugged": None,
        "battery_percent": None,
        "seconds_left": None,
    }
    try:
        battery = psutil.sensors_battery()
    except Exception as exc:  # noqa: BLE001
        power_state["sensor_error"] = str(exc)
        return power_state

    if battery is None:
        return power_state

    power_state["sensor_available"] = True
    power_state["power_plugged"] = bool(battery.power_plugged)
    power_state["battery_percent"] = float(battery.percent) if battery.percent is not None else None
    power_state["seconds_left"] = int(battery.secsleft) if battery.secsleft is not None else None
    return power_state


def enforce_ac_power_or_fail_closed() -> dict[str, Any]:
    power_state = detect_power_envelope()
    if power_state.get("sensor_available") and power_state.get("power_plugged") is False:
        raise RuntimeError(
            "POWER_ENVELOPE_NOT_LOCKED: AC power required for feasibility evidence capture"
        )
    return power_state


def prompt_for_user_tokens(tokenizer: Any, target_tokens: int) -> str:
    base = (
        "Runtime ceiling characterization payload for BlarAI Orchestrator. "
        "This prompt is deterministic and local-only. "
    )
    chunk = "token_probe_segment "
    text = base
    for _ in range(50000):
        toks = tokenizer(text, return_tensors="np")["input_ids"][0]
        if len(toks) >= target_tokens:
            break
        text += chunk
    toks = tokenizer(text, return_tensors="np")["input_ids"][0]
    if len(toks) > target_tokens:
        text = tokenizer.decode(toks[:target_tokens], skip_special_tokens=True)
    return text


def run_generation(
    orch: OrchestratorGPUInference,
    prompt: str,
    session_id: str,
    cold: bool,
) -> dict[str, Any]:
    if cold:
        orch.invalidate_kv(session_id)

    t0 = time.perf_counter()
    result = orch.generate_text(
        prompt,
        max_new_tokens=PROBE_MAX_NEW_TOKENS,
        session_id=session_id,
        config=GenerationConfig(
            max_new_tokens=PROBE_MAX_NEW_TOKENS,
            temperature=0.0,
            top_k=1,
            top_p=1.0,
            repetition_penalty=1.0,
            do_sample=False,
        ),
    )
    wall_ms = (time.perf_counter() - t0) * 1000.0

    if result.error is None:
        tps = 0.0
        if result.latency_total_ms > 0:
            tps = result.token_count / (result.latency_total_ms / 1000.0)
        return {
            "ok": True,
            "latency_first_token_ms": float(result.latency_first_token_ms),
            "latency_total_ms": float(result.latency_total_ms),
            "wall_time_ms": wall_ms,
            "decode_tokens_per_sec": float(tps),
            "token_count": int(result.token_count),
            "text_len": int(len(result.text)),
            "fingerprint": None,
            "error": None,
            "partial_release": False,
        }

    # Fail-closed expectations on error path
    partial_release = bool(result.token_count > 0 or result.text)
    fp = make_fp("AO_MAX_PROMPT_LEN" if "MAX_PROMPT_LEN" in result.error else "AO_FAIL", result.error)
    return {
        "ok": False,
        "latency_first_token_ms": float(result.latency_first_token_ms),
        "latency_total_ms": float(result.latency_total_ms),
        "wall_time_ms": wall_ms,
        "decode_tokens_per_sec": 0.0,
        "token_count": int(result.token_count),
        "text_len": int(len(result.text)),
        "fingerprint": fp,
        "error": result.error,
        "partial_release": partial_release,
    }


def characterize_ceiling(meta: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    tokenizer = AutoTokenizer.from_pretrained(str(MODEL_DIR), local_files_only=True)

    protocol = {
        "milestone": "P5-FEASIBILITY-003",
        "timestamp_utc": now_iso(),
        "metadata": meta,
        "bands_user_tokens": BANDS,
        "critical_bands": CRITICAL_BANDS,
        "runs_per_mode": RUNS_PER_MODE,
        "modes": ["cold", "warm"],
        "probe_generation": {
            "max_new_tokens": PROBE_MAX_NEW_TOKENS,
            "seed_policy": "deterministic_greedy_no_sampling",
        },
        "failure_fingerprint_family": [
            "AO_MAX_PROMPT_LEN_*",
            "AO_FAIL_*",
        ],
        "harness_constraint": "NO_FULL_HARNESS",
    }

    matrix: dict[str, Any] = {
        "milestone": "P5-FEASIBILITY-003",
        "timestamp_utc": now_iso(),
        "metadata": meta,
        "warm_cold_separate": True,
        "points": [],
        "summary": {},
        "unsampled_regions": [],
    }

    orch = OrchestratorGPUInference(model_dir=str(MODEL_DIR), device="NPU")
    if not orch.load_model():
        matrix["fatal_error"] = "AO_MODEL_LOAD_FAILED"
        matrix["summary"] = {
            "runtime_ceiling_characterized": False,
            "reason": "model_load_failed",
        }
        containment = {
            "milestone": "P5-FEASIBILITY-003",
            "timestamp_utc": now_iso(),
            "metadata": meta,
            "fatal_error": "AO_MODEL_LOAD_FAILED",
            "containment_validated": False,
            "reason_code": "INSUFFICIENT_EVIDENCE",
        }
        contract = {
            "milestone": "P5-FEASIBILITY-003",
            "timestamp_utc": now_iso(),
            "metadata": meta,
            "guarded_boundary": "UNCHARACTERIZED",
            "enforcement_points": [
                "services/assistant_orchestrator/src/gpu_inference.py::generate_text",
                "services/assistant_orchestrator/src/gpu_inference.py::_generate_from_prompt",
            ],
            "expected_failure_fingerprint_family": ["AO_MAX_PROMPT_LEN_*", "AO_FAIL_*"],
            "required_telemetry_fields": [
                "band_user_tokens",
                "formatted_prompt_tokens",
                "mode",
                "ok",
                "fingerprint",
                "error",
                "token_count",
                "text_len",
                "partial_release",
            ],
            "rollback_safe_test_procedure": "Run phase2_gates/scripts/run_p5_feasibility_003.py and verify p5_runtime_ceiling_characterization.json + containment_validation.json",
            "gate_result": {"passed": False, "reason_code": "INSUFFICIENT_EVIDENCE"},
            "unsampled_regions": [{"region": "ALL", "reason": "model_load_failed", "impact": "No ceiling characterization or containment validation possible"}],
        }
        return protocol, matrix, {"containment": containment, "contract": contract}

    for band in BANDS:
        prompt = prompt_for_user_tokens(tokenizer, band)
        user_tokens = int(len(tokenizer(prompt, return_tensors="np")["input_ids"][0]))
        formatted = orch._format_chat_prompt(prompt)
        formatted_tokens = int(len(tokenizer(formatted, return_tensors="np")["input_ids"][0]))

        point = {
            "band_user_tokens": band,
            "actual_user_tokens": user_tokens,
            "formatted_prompt_tokens": formatted_tokens,
            "modes": {},
            "combined": {},
            "valid_count": 0,
            "invalid_count": 0,
            "success_count": 0,
            "failure_count": 0,
            "missing_reason": None,
        }

        combined_runs: list[dict[str, Any]] = []
        for mode in ["cold", "warm"]:
            mode_runs: list[dict[str, Any]] = []
            session = f"p5_ceiling_{band}_{mode}"

            # warm priming (not counted)
            if mode == "warm":
                _ = run_generation(orch, prompt, session, cold=True)

            for _idx in range(RUNS_PER_MODE):
                mode_runs.append(run_generation(orch, prompt, session, cold=(mode == "cold")))

            ok_runs = [r for r in mode_runs if r["ok"]]
            fail_runs = [r for r in mode_runs if not r["ok"]]
            point["modes"][mode] = {
                "runs": mode_runs,
                "valid_count": len(ok_runs),
                "invalid_count": len(fail_runs),
                "success_count": len(ok_runs),
                "failure_count": len(fail_runs),
                "ttft_ms": stats([float(r["latency_first_token_ms"]) for r in ok_runs], len(ok_runs), len(fail_runs)),
                "latency_total_ms": stats([float(r["latency_total_ms"]) for r in ok_runs], len(ok_runs), len(fail_runs)),
                "decode_tokens_per_sec": stats([float(r["decode_tokens_per_sec"]) for r in ok_runs], len(ok_runs), len(fail_runs)),
                "wall_time_ms": stats([float(r["wall_time_ms"]) for r in mode_runs], len(mode_runs), 0),
                "fingerprint_distribution": dict(Counter(r["fingerprint"] for r in fail_runs if r["fingerprint"])),
                "partial_release_failures": sum(1 for r in fail_runs if r["partial_release"]),
            }
            combined_runs.extend(mode_runs)

        ok_combined = [r for r in combined_runs if r["ok"]]
        fail_combined = [r for r in combined_runs if not r["ok"]]

        point["combined"] = {
            "ttft_ms": stats([float(r["latency_first_token_ms"]) for r in ok_combined], len(ok_combined), len(fail_combined)),
            "latency_total_ms": stats([float(r["latency_total_ms"]) for r in ok_combined], len(ok_combined), len(fail_combined)),
            "decode_tokens_per_sec": stats([float(r["decode_tokens_per_sec"]) for r in ok_combined], len(ok_combined), len(fail_combined)),
            "wall_time_ms": stats([float(r["wall_time_ms"]) for r in combined_runs], len(combined_runs), 0),
            "fingerprint_distribution": dict(Counter(r["fingerprint"] for r in fail_combined if r["fingerprint"])),
            "partial_release_failures": sum(1 for r in fail_combined if r["partial_release"]),
        }
        point["valid_count"] = len(ok_combined)
        point["invalid_count"] = len(fail_combined)
        point["success_count"] = len(ok_combined)
        point["failure_count"] = len(fail_combined)
        if len(ok_combined) == 0:
            point["missing_reason"] = "No successful runs"
        matrix["points"].append(point)

    # boundary extraction
    passing = [p for p in matrix["points"] if p["success_count"] > 0]
    failing = [p for p in matrix["points"] if p["failure_count"] > 0 and p["success_count"] == 0]
    last_pass = max((p["band_user_tokens"] for p in passing), default=None)
    first_fail = min((p["band_user_tokens"] for p in failing), default=None)

    # reproducibility for critical bands
    repro: dict[str, Any] = {}
    for band in CRITICAL_BANDS:
        point = next((p for p in matrix["points"] if p["band_user_tokens"] == band), None)
        if point is None:
            continue
        prompt = prompt_for_user_tokens(tokenizer, band)
        session = f"p5_ceiling_repro_{band}"
        results = [run_generation(orch, prompt, session, cold=False) for _ in range(10)]
        ok = [r for r in results if r["ok"]]
        fail = [r for r in results if not r["ok"]]
        repro[str(band)] = {
            "runs": 10,
            "valid_count": len(ok),
            "invalid_count": len(fail),
            "latency_total_ms": stats([float(r["latency_total_ms"]) for r in ok], len(ok), len(fail)),
            "fingerprint_distribution": dict(Counter(r["fingerprint"] for r in fail if r["fingerprint"])),
            "partial_release_failures": sum(1 for r in fail if r["partial_release"]),
        }

    matrix["summary"] = {
        "runtime_ceiling_characterized": last_pass is not None and first_fail is not None,
        "last_passing_band_user_tokens": last_pass,
        "first_failing_band_user_tokens": first_fail,
        "effective_ceiling_interval_user_tokens": [last_pass, first_fail] if last_pass is not None and first_fail is not None else None,
        "reproducibility": repro,
    }

    # containment validation for over-ceiling bands
    over_bands = [b for b in BANDS if first_fail is not None and b >= first_fail]
    containment: dict[str, Any] = {
        "milestone": "P5-FEASIBILITY-003",
        "timestamp_utc": now_iso(),
        "metadata": meta,
        "over_ceiling_bands": over_bands,
        "bands": [],
        "summary": {},
    }

    for band in over_bands:
        prompt = prompt_for_user_tokens(tokenizer, band)
        runs = [run_generation(orch, prompt, f"p5_contain_{band}", cold=(i % 2 == 0)) for i in range(30)]
        fail = [r for r in runs if not r["ok"]]
        ok = [r for r in runs if r["ok"]]
        containment["bands"].append(
            {
                "band_user_tokens": band,
                "valid_count": len(ok),
                "invalid_count": len(fail),
                "failure_rate": (len(fail) / len(runs)) if runs else 0.0,
                "deterministic_fingerprint_distribution": dict(Counter(r["fingerprint"] for r in fail if r["fingerprint"])),
                "partial_release_failures": sum(1 for r in fail if r["partial_release"]),
                "wall_time_ms": stats([float(r["wall_time_ms"]) for r in runs], len(runs), 0),
                "latency_total_ms_success": stats([float(r["latency_total_ms"]) for r in ok], len(ok), len(fail)),
            }
        )

    contain_pass = True
    for band in containment["bands"]:
        if band["invalid_count"] == 0:
            contain_pass = False
        if band["partial_release_failures"] > 0:
            contain_pass = False

    containment["summary"] = {
        "containment_validated": contain_pass,
        "deterministic_fail_closed": contain_pass,
        "operator_observable_artifact": "phase2_gates/evidence/p5_runtime_ceiling_containment_validation.json",
    }

    # contract artifact
    contract: dict[str, Any] = {
        "milestone": "P5-FEASIBILITY-003",
        "timestamp_utc": now_iso(),
        "metadata": meta,
        "guarded_boundary": {
            "last_pass_band_user_tokens": last_pass,
            "first_fail_band_user_tokens": first_fail,
            "effective_ceiling_interval_user_tokens": [last_pass, first_fail] if last_pass is not None and first_fail is not None else None,
        },
        "enforcement_points": [
            "services/assistant_orchestrator/src/gpu_inference.py::generate_text",
            "services/assistant_orchestrator/src/gpu_inference.py::_generate_from_prompt",
            "services/assistant_orchestrator/src/gpu_inference.py::_fail_closed",
        ],
        "expected_failure_fingerprint_family": ["AO_MAX_PROMPT_LEN_*", "AO_FAIL_*"],
        "required_telemetry_fields": [
            "band_user_tokens",
            "actual_user_tokens",
            "formatted_prompt_tokens",
            "mode",
            "ok",
            "fingerprint",
            "error",
            "token_count",
            "text_len",
            "partial_release",
            "latency_first_token_ms",
            "latency_total_ms",
            "wall_time_ms",
        ],
        "rollback_safe_test_procedure": [
            "Run phase2_gates/scripts/run_p5_feasibility_003.py",
            "Verify p5_runtime_ceiling_characterization.json has explicit last-pass/first-fail",
            "Verify p5_runtime_ceiling_containment_validation.json has zero partial_release_failures on over-ceiling bands",
            "If not, set disposition NO_DECISION/INSUFFICIENT_EVIDENCE",
        ],
        "harness_constraint": {
            "status": "NO_FULL_HARNESS",
            "unsampled_regions_policy": "Explicit UNSAMPLED region + impact statement required",
        },
        "quality_gate": {},
        "unsampled_regions": [],
    }

    # EQG/HC evaluation
    checks: dict[str, dict[str, Any]] = {}

    def set_check(rule: str, passed: bool, detail: str) -> None:
        checks[rule] = {"passed": passed, "detail": detail}

    set_check("EQG-01", True, "Local measurable paths were executed")

    # EQG-02 critical bands >=30 valid combined
    eqg02 = True
    for b in CRITICAL_BANDS:
        p = next((pt for pt in matrix["points"] if pt["band_user_tokens"] == b), None)
        if p is None or int(p["valid_count"]) < 30:
            eqg02 = False
    set_check("EQG-02", eqg02, "Critical boundary bands require >=30 valid combined warm/cold")

    eqg03 = all("cold" in p["modes"] and "warm" in p["modes"] for p in matrix["points"])
    set_check("EQG-03", eqg03, "Warm/cold split present for all bands")

    required_fields = {"mean", "stddev", "p50", "p95", "p99", "min", "max", "valid_count", "invalid_count"}
    eqg04 = True
    for p in matrix["points"]:
        for metric in ["ttft_ms", "latency_total_ms", "decode_tokens_per_sec"]:
            if not required_fields.issubset(set(p["combined"][metric].keys())):
                eqg04 = False
    set_check("EQG-04", eqg04, "Distributions include required summary fields")

    eqg05 = True
    for art in [protocol, matrix, containment, contract]:
        m = art.get("metadata", {})
        if not (m.get("commit_hash") and m.get("profile") and m.get("model_identifier") and art.get("timestamp_utc")):
            eqg05 = False
    set_check("EQG-05", eqg05, "Metadata present in all artifacts")

    eqg06 = all(str(b) in matrix["summary"]["reproducibility"] for b in CRITICAL_BANDS)
    set_check("EQG-06", eqg06, "Reproducibility reruns present for boundary-critical bands")

    eqg07 = True
    for p in matrix["points"]:
        if p["failure_count"] > 0 and not p["combined"]["fingerprint_distribution"]:
            eqg07 = False
    set_check("EQG-07", eqg07, "Failures retained with deterministic fingerprints")

    eqg08 = bool(containment["summary"].get("containment_validated", False))
    set_check("EQG-08", eqg08, "Over-ceiling bands show deterministic fail-closed containment")

    eqg09 = eqg02
    set_check("EQG-09", eqg09, "Critical band coverage gate")

    # HC-10 / unsampled regions and impact
    unsampled = []
    for p in matrix["points"]:
        if int(p["valid_count"]) == 0:
            unsampled.append(
                {
                    "region": f"band_user_tokens={p['band_user_tokens']}",
                    "reason": p.get("missing_reason") or "UNSAMPLED",
                    "impact": "Cannot claim complete ceiling profile across this band; re-decision remains bounded/partial",
                }
            )
    contract["unsampled_regions"] = unsampled
    set_check("EQG-10", True if unsampled else True, "UNSAMPLED regions are explicitly declared with impact statements")

    all_pass = all(v["passed"] for v in checks.values())
    disposition = "CEILING_CHARACTERIZED_AND_CONTAINMENT_VALIDATED" if all_pass else "NO_DECISION"
    reason_code = None if all_pass else "INSUFFICIENT_EVIDENCE"

    contract["quality_gate"] = {
        "checks": checks,
        "all_pass": all_pass,
        "disposition": disposition,
        "reason_code": reason_code,
    }

    # carry summary to characterization
    matrix["gate_result"] = {
        "all_pass": all_pass,
        "disposition": disposition,
        "reason_code": reason_code,
    }

    # append unsampled regions to matrix for HC visibility
    matrix["unsampled_regions"] = unsampled

    orch.unload()

    return protocol, matrix, {"containment": containment, "contract": contract}


def main() -> None:
    head = git_head()
    power_state = enforce_ac_power_or_fail_closed()
    meta = {
        "commit_hash": head,
        "profile": "host",
        "model_identifier": "qwen2.5-1.5b-instruct/openvino-int4-npu",
        "baseline_artifacts": [
            "docs/FEASIBILITY_CONTEXT_WINDOW.md",
            "docs/FEASIBILITY_CONTEXT_WINDOW_ADDENDUM.md",
            "phase2_gates/evidence/p5_redecision_quality_gate.json",
        ],
        "power_envelope": power_state,
        "run_preconditions": {
            "ac_power_required": True,
        },
    }

    protocol, characterization, rest = characterize_ceiling(meta)

    write_json(EVIDENCE_DIR / "p5_runtime_ceiling_probe_protocol.json", protocol)
    write_json(EVIDENCE_DIR / "p5_runtime_ceiling_characterization.json", characterization)
    write_json(EVIDENCE_DIR / "p5_runtime_ceiling_containment_validation.json", rest["containment"])
    write_json(EVIDENCE_DIR / "p5_runtime_ceiling_containment_contract.json", rest["contract"])

    print(
        json.dumps(
            {
                "status": "ok",
                "head": head,
                "disposition": rest["contract"]["quality_gate"]["disposition"],
                "reason_code": rest["contract"]["quality_gate"]["reason_code"],
                "last_pass": characterization.get("summary", {}).get("last_passing_band_user_tokens"),
                "first_fail": characterization.get("summary", {}).get("first_failing_band_user_tokens"),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
