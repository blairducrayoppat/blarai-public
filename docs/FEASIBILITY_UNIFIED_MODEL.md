# P5-FEASIBILITY-005 — Unified Model Feasibility Matrix

**Date (UTC):** 2026-02-27  
**Branch:** `feature/p5-feasibility-005-unified-model`  
**Disposition:** `INSUFFICIENT_EVIDENCE`

---

## 1) Model Acquisition Results

Acquisition harness executed and produced:
- `phase2_gates/evidence/p5_005_model_acquisition.json`

Environment prechecks:
- AC power: `PASS` (`power_plugged=true`)
- Disk free on `C:\`: `415.75 GB` (>= 20 GB requirement)
- OpenVINO: `2026.0.0-20965-c6d6a13a886-releases/2026/0`
- OpenVINO GenAI: `2026.0.0.0-2820-dab5b993a38`
- Available devices: `CPU`, `GPU`, `NPU`

Acquisition outcome:
- `qwen3-14b`: `FAILED`
- `qwen3-8b`: `FAILED`
- `qwen3-0.6b`: `FAILED`

Blocking failure fingerprint:
- `OPTIMUM_INTEL_IMPORT_FAILED`
- Import stack indicates version incompatibility in local Python packages:
  - `cannot import name 'sdpa_mask_without_vmap' from optimum.exporters.onnx.model_patcher`

Impact:
- No OpenVINO IR artifacts were produced for the three required models.
- Size-range validation, SHA-256 capture, and quick inference smoke tests could not execute.

---

## 2) EAGLE-3 / Assisted Generation Investigation Results

The acquisition artifact includes HuggingFace query evidence for EAGLE-3 candidate discovery.
Observed candidates include both 8B and 14B naming patterns (for example:
`AngelSlim/Qwen3-8B_eagle3`, `AngelSlim/Qwen3-14B_eagle3`).

API-surface discovery in this environment:
- `openvino_genai.draft_model(...)`: present
- `GenerationConfig` assistant fields: present
  - `assistant_confidence_threshold`
  - `num_assistant_tokens`
  - `is_assisting_generation`
- OpenVINO GPU supported properties include:
  - `KV_CACHE_PRECISION`
  - `GPU_ENABLE_SDPA_OPTIMIZATION`

Interpretation:
- Local API capability discovery is positive for speculative/assisted wiring.
- Execution remains blocked by model acquisition failure before any benchmark test can run.

---

## 3) Qwen3-14B Results (T-01..T-05, T-09)

No executable measurements collected.

Reason:
- Required model path missing at benchmark precheck:
  - `models/qwen3-14b/openvino-int4-gpu`

Status:
- `T-01`..`T-05` and `T-09`: `NOT EXECUTED (blocked by model assets)`

---

## 4) Qwen3-8B Results (T-06..T-08, T-10)

No executable measurements collected.

Reason:
- Required model path missing at benchmark precheck:
  - `models/qwen3-8b/openvino-int4-gpu`

Status:
- `T-06`..`T-08` and `T-10`: `NOT EXECUTED (blocked by model assets)`

---

## 5) Cross-Model Comparison

Not available in this run.

Cause:
- Neither primary nor fallback model artifacts exist in local OpenVINO IR form.

---

## 6) Speculative Decoding Comparison

Not available in this run.

Cause:
- Draft/head capability discovery completed, but no base model acquisition succeeded.

---

## 7) Production Configuration Recommendation

No production recommendation can be made from this run.

Prerequisite to continue P5-005:
1. Resolve local package incompatibility (`optimum` / `optimum-intel` / exporters stack).
2. Re-run `phase2_gates/scripts/acquire_p5_005_models.py` until all three models are exported and validated.
3. Re-run `phase2_gates/scripts/run_p5_feasibility_005.py` to collect the 10-test matrix.

---

## 8) Disposition

`INSUFFICIENT_EVIDENCE`

Reason:
- Unified Model Feasibility Gate could not be evaluated because required model assets were absent.
- Benchmark artifact reports:
  - `status=blocked`
  - `failure_reason=MODEL_ASSET_PRECHECK_FAILED`
  - `reason_code=MISSING_MODEL_ASSETS`

Artifacts:
- `phase2_gates/evidence/p5_005_model_acquisition.json`
- `phase2_gates/evidence/p5_unified_model_feasibility_matrix.json`
