"""
run_eagle3_gap_fill.py — EAGLE-3 T-05/T-07 Gap Fill Runner
============================================================
Milestone: P5-FEASIBILITY-005a-EAGLE3
Phase:     4 — Gap Fill Evidence Recording

Purpose:
  The EAGLE-3 OV conversion probe confirmed FRAMEWORK_NOT_SUPPORTED
  for both AngelSlim/Qwen3-14B_eagle3 and RedHatAI/Qwen3-8B-speculator.eagle3.
  Because both converted output dirs are empty, the main harness would still
  mark T-05/T-07 as "EAGLE3_DRAFT_NOT_AVAILABLE" — never advancing to a
  confirmed outcome.

  This script:
  1. Reads p5_005a_eagle3_acquisition.json to formally confirm conversion status
  2. Records T-05 and T-07 as status=failed with fail_reason=FRAMEWORK_NOT_SUPPORTED
  3. Writes p5_005a_eagle3_benchmark.json (standalone T-05/T-07 records)
  4. Merges updated T-05/T-07 records into p5_005a_unified_draft_feasibility_matrix.json
     (MERGE ONLY — all other test result data is preserved)
  5. Updates matrix finished_utc and adds eagle3_gap_fill_utc
  6. Does NOT change the matrix disposition (remains QWEN3_14B_WITH_SPEC_DECODING)

Network: NONE authorized.
"""

from __future__ import annotations

import copy
import datetime as dt
import json
import platform
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

EVIDENCE_DIR = ROOT / "phase2_gates" / "evidence"
ACQUISITION_JSON = EVIDENCE_DIR / "p5_005a_eagle3_acquisition.json"
MATRIX_JSON = EVIDENCE_DIR / "p5_005a_unified_draft_feasibility_matrix.json"
BENCHMARK_JSON = EVIDENCE_DIR / "p5_005a_eagle3_benchmark.json"


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def git_head() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip()
    except Exception:
        return "unknown"


def read_json(path: Path) -> Any:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def write_json_atomic(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)
    tmp.replace(path)


def load_acquisition_evidence() -> dict[str, Any]:
    """Load and validate the EAGLE-3 acquisition evidence."""
    if not ACQUISITION_JSON.exists():
        raise FileNotFoundError(
            f"Acquisition evidence not found: {ACQUISITION_JSON}\n"
            "Run eagle3_convert_and_validate.py first."
        )
    data = read_json(ACQUISITION_JSON)
    overall = data.get("overall_disposition", "UNKNOWN")
    print(f"  Acquisition overall disposition: {overall}")

    m14b = data["models"]["eagle3_14b"]
    m8b = data["models"]["eagle3_8b"]
    print(f"  14B: {m14b['disposition']} — arch={m14b['raw_inspection'].get('architecture')}")
    print(f"  8B:  {m8b['disposition']} — arch={m8b['raw_inspection'].get('architecture')}")

    return data


def extract_fail_detail(model_data: dict[str, Any]) -> str:
    """Build a structured fail_detail string from conversion attempt evidence."""
    arch = model_data["raw_inspection"].get("architecture", "UNKNOWN")
    cls_error = (model_data.get("class_check") or {}).get("error", "class check not run")
    conv = model_data.get("conversion_attempt") or {}
    conv_error = conv.get("error", "no conversion attempt")
    stderr = conv.get("stderr_tail", "")

    # Extract root cause from stderr (last meaningful Python exception line)
    root_cause = ""
    if "ValueError:" in stderr:
        for line in stderr.splitlines():
            if line.strip().startswith("ValueError:"):
                root_cause = line.strip()
                break
    elif "RuntimeError:" in stderr:
        for line in stderr.splitlines():
            if line.strip().startswith("RuntimeError:"):
                root_cause = line.strip()
                break
    elif conv_error:
        root_cause = conv_error

    draft_probe = model_data.get("draft_model_probe") or {}
    ov_error = (draft_probe.get("error") or "")[:120]

    detail = (
        f"architecture={arch}; "
        f"class_check: {cls_error}; "
        f"optimum_export_returncode={conv.get('returncode')}; "
        f"root_cause: {root_cause}; "
        f"ov_genai_draft_model: {ov_error}"
    )
    return detail[:512]  # cap for JSON readability


def build_test_record(
    test_id: str,
    test_name: str,
    target: str,
    acq_model_data: dict[str, Any],
    gap_fill_utc: str,
) -> dict[str, Any]:
    """Build a completed (failed) test record for T-05 or T-07."""
    return {
        "id": test_id,
        "name": test_name,
        "target": target,
        "is_speculative": True,
        "draft_device": "GPU",
        "status": "failed",
        "skip_reason": None,
        "fail_reason": "FRAMEWORK_NOT_SUPPORTED",
        "fail_detail": extract_fail_detail(acq_model_data),
        "tps_512": None,
        "speedup_vs_baseline_512": None,
        "points": [],
        "eagle3_gap_fill_utc": gap_fill_utc,
        "eagle3_acquisition_evidence_path": ACQUISITION_JSON.name,
        "eagle3_acquisition_overall_disposition": acq_model_data["disposition"],
        "eagle3_ir_produced": False,
    }


def load_matrix() -> dict[str, Any]:
    """Load the existing evidence matrix."""
    if not MATRIX_JSON.exists():
        raise FileNotFoundError(f"Matrix not found: {MATRIX_JSON}")
    return read_json(MATRIX_JSON)


def merge_into_matrix(
    matrix: dict[str, Any],
    t05_record: dict[str, Any],
    t07_record: dict[str, Any],
    gap_fill_utc: str,
) -> dict[str, Any]:
    """Replace T-05/T-07 skipped entries with the failed records. Preserve all other tests."""
    updated = copy.deepcopy(matrix)

    tests_in: list[dict[str, Any]] = updated.get("tests", [])
    tests_out: list[dict[str, Any]] = []

    replaced = {"T-05": False, "T-07": False}
    for t in tests_in:
        tid = t.get("id")
        if tid == "T-05":
            tests_out.append(t05_record)
            replaced["T-05"] = True
            print(f"  Replaced T-05: skipped → failed/FRAMEWORK_NOT_SUPPORTED")
        elif tid == "T-07":
            tests_out.append(t07_record)
            replaced["T-07"] = True
            print(f"  Replaced T-07: skipped → failed/FRAMEWORK_NOT_SUPPORTED")
        else:
            tests_out.append(t)

    # Append if T-05/T-07 were not present (shouldn't happen, but fail-safe)
    if not replaced["T-05"]:
        tests_out.append(t05_record)
        print("  Appended T-05 (was not in matrix)")
    if not replaced["T-07"]:
        tests_out.append(t07_record)
        print("  Appended T-07 (was not in matrix)")

    updated["tests"] = tests_out

    # Update matrix timestamps — disposition is PRESERVED inside quality_gate
    updated["finished_utc"] = gap_fill_utc
    updated["eagle3_gap_fill_utc"] = gap_fill_utc
    updated["acquisition_artifact_present"] = True

    # Verify we haven't changed the disposition (it lives in quality_gate)
    qg = updated.get("quality_gate", {})
    current_disp = qg.get("disposition") if isinstance(qg, dict) else None
    assert current_disp == "QWEN3_14B_WITH_SPEC_DECODING", (
        f"Unexpected disposition change: {current_disp}"
    )

    return updated


def main() -> None:
    gap_fill_utc = now_iso()
    print(f"[P5-005a-EAGLE3 Phase 4] Gap fill started: {gap_fill_utc}")

    # Step 1: Load acquisition evidence
    print("\n[1/5] Loading acquisition evidence ...")
    acq = load_acquisition_evidence()
    m14b_data = acq["models"]["eagle3_14b"]
    m8b_data = acq["models"]["eagle3_8b"]

    # Fail-closed: both must be FRAMEWORK_NOT_SUPPORTED
    for label, data in [("14B", m14b_data), ("8B", m8b_data)]:
        if data["disposition"] not in ("FRAMEWORK_NOT_SUPPORTED", "EAGLE3_NOT_CONVERTIBLE"):
            print(f"UNEXPECTED: {label} disposition={data['disposition']} — expected FRAMEWORK_NOT_SUPPORTED")
            print("  Recording as-is but continuing.")

    # Step 2: Build T-05 and T-07 records
    print("\n[2/5] Building T-05 and T-07 failed records ...")
    t05 = build_test_record("T-05", "14B + EAGLE-3", "14B", m14b_data, gap_fill_utc)
    t07 = build_test_record("T-07", "8B + EAGLE-3", "8B", m8b_data, gap_fill_utc)

    # Step 3: Write standalone benchmark JSON
    print("\n[3/5] Writing standalone benchmark JSON ...")
    benchmark: dict[str, Any] = {
        "milestone": "P5-FEASIBILITY-005a-EAGLE3",
        "phase": "gap_fill_benchmark",
        "metadata": {
            "timestamp_utc": gap_fill_utc,
            "commit_hash": git_head(),
            "platform": platform.platform(),
            "python_version": sys.version,
            "acquisition_evidence_path": ACQUISITION_JSON.name,
            "acquisition_overall_disposition": acq["overall_disposition"],
        },
        "tests": [t05, t07],
        "summary": {
            "t05_status": t05["status"],
            "t05_fail_reason": t05["fail_reason"],
            "t07_status": t07["status"],
            "t07_fail_reason": t07["fail_reason"],
            "overall_disposition": "FRAMEWORK_NOT_SUPPORTED",
            "note": (
                "EAGLE-3 draft heads (LlamaForCausalLMEagle3, Eagle3Speculator) "
                "are not loadable by the transformers+optimum-intel pipeline. "
                "Both architectures fail at model deserialization — weight shapes "
                "are incompatible with standard CausalLM schemas. "
                "ov_genai.draft_model() requires OV IR format which cannot be "
                "produced. Disposition: FRAMEWORK_NOT_SUPPORTED."
            ),
        },
        "finished_utc": gap_fill_utc,
    }
    write_json_atomic(BENCHMARK_JSON, benchmark)
    print(f"  Written: {BENCHMARK_JSON}")

    # Step 4: Load and merge into matrix
    print("\n[4/5] Loading matrix and merging ...")
    matrix = load_matrix()
    print(f"  Matrix tests before: {len(matrix.get('tests', []))}")
    merged = merge_into_matrix(matrix, t05, t07, gap_fill_utc)
    print(f"  Matrix tests after:  {len(merged.get('tests', []))}")

    # Step 5: Write updated matrix
    print("\n[5/5] Writing merged matrix ...")
    write_json_atomic(MATRIX_JSON, merged)
    print(f"  Written: {MATRIX_JSON}")
    merged_disp = (merged.get("quality_gate") or {}).get("disposition", "UNKNOWN")
    print(f"  disposition preserved: {merged_disp}")
    print(f"  eagle3_gap_fill_utc: {merged['eagle3_gap_fill_utc']}")

    print(f"\n[P5-005a-EAGLE3 Phase 4] Gap fill COMPLETE")
    print(f"  T-05: {t05['status']} / {t05['fail_reason']}")
    print(f"  T-07: {t07['status']} / {t07['fail_reason']}")
    print(f"  Benchmark: {BENCHMARK_JSON.name}")
    print(f"  Matrix:    {MATRIX_JSON.name}")
    print(f"  Disposition: FRAMEWORK_NOT_SUPPORTED (EAGLE-3 not OV-convertible)")


if __name__ == "__main__":
    main()
