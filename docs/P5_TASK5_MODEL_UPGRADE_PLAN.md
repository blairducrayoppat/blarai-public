# Task 5 — Qwen3-14B Production Model Upgrade Plan

**Status:** v5 — COMPLETE (all milestones M5.1–M5.5 closed)  
**Date:** 2026-04-18 (updated 2026-04-20)  
**Author:** SDO (Claude Opus 4.6)  
**HEAD at planning:** `b6689fc` (main)  
**M5.4 HEAD:** `53764b0` (feature/p5-task5-m5.4-config-hardening)  
**M5.5 HEAD:** `2801db4` (feature/p5-task5-m5.5-e2e-validation)  
**Test baseline:** 835 passed, 0 failed, 2 skipped  
**LEDGER entries:** 34a (M5.1), 34 (M5.2), 35 (M5.3), 36 (M5.4), 37 (M5.5)

---

## 1. Executive Summary

Task 5 upgrades BlarAI's production inference pipeline from **Qwen3-1.7B INT4** (PA on GPU, AO on NPU) to **Qwen3-14B INT4** (both PA and AO on GPU) with mandatory speculative decoding using **Qwen3-0.6B INT4** as the draft model. This is the first production model swap since Phase 4 operational sign-off.

The scope encompasses:
- **PA (USE-CASE-001):** Wire speculative decoding into the existing GPU inference harness.
- **AO (USE-CASE-004):** Full file rename (`npu_inference.py` → `gpu_inference.py`), class rename (`OrchestratorNPUInference` → `OrchestratorGPUInference`), GPU rewrite with speculative decoding, entrypoint config resolver overhaul (`npu` → `gpu` section reads, device validation flip, error code renames), and TOML config updates (`model_dir`, `weight_manifest`).
- **Import cascade:** Update all references across tests, integration files, and scripts.
- **End-to-end validation:** Root-cause and fix the `GATEWAY_HANDSHAKE_FAILED` regression, re-validate full runtime pipeline.

All 10 locked decisions (DEC-01 through DEC-10) and 6 ADRs (ADR-005 through ADR-012) remain in effect.

---

## 2. Preconditions

All preconditions are MET:

| Precondition | Status | Evidence |
|-------------|--------|----------|
| ADR-012 model selection locked | ✅ LOCKED | Qwen3-14B INT4 GPU + Qwen3-0.6B draft |
| Task 4 configuration optimization complete | ✅ CLOSED | 10 locked decisions (DEC-01–DEC-10) |
| Task 4.11 security hardening complete | ✅ CLOSED | All 7 actionable SECURITY_ASSESSMENT.md findings closed |
| Task 4.12g PA quality gate | ✅ PASS | 0.9483 (55/58 cases) |
| Model weights acquired on disk | ✅ PRESENT | `models/qwen3-14b/openvino-int4-gpu/`, `models/qwen3-0.6b/openvino-int4-gpu/` |
| shared/constants.py updated for 14B | ✅ DONE | `TARGET_MODEL_OV_PATH`, `DRAFT_MODEL_OV_PATH`, `SPECULATIVE_DECODING_ENABLED`, `NUM_ASSISTANT_TOKENS` all locked |

---

## 3. Locked Configuration Reference (ADR-012 §2.6)

### 3.1 Shared Parameters (PA + AO)

| Parameter | Value | Decision |
|-----------|-------|----------|
| Target model | Qwen3-14B INT4 GPU | ADR-012 §2.1 |
| Draft model | Qwen3-0.6B 28L INT4 GPU | DEC-01 (Task 4.2) |
| `num_assistant_tokens` | 3 | DEC-01 (Task 4.3) |
| `INFERENCE_PRECISION_HINT` | `"f16"` | DEC-07 (Task 4.7) |
| `GPU_ENABLE_SDPA_OPTIMIZATION` | `"ON"` | DEC-05 (Task 4.4) |
| `enable_prefix_caching` | OFF | DEC-06 (Task 4.6) |
| `do_sample` | False | Project mandate |
| `stop_token_ids` | [151645] | ADR-012 §2.4 / DEC-09b |
| Pipeline construction | `LLMPipeline(path, device, draft_model=ov_genai.draft_model(draft_path, device), **config)` | ADR-012 §2.2 |
| `SchedulerConfig` | `cache_size=3, enable_prefix_caching=False` | DEC-06 |

### 3.2 PA-Specific Parameters

| Parameter | Value | Decision |
|-----------|-------|----------|
| `max_new_tokens` | 10 | DEC-08 (restored 2026-04-17) |
| Thinking mode | `/no_think` MANDATORY + canonical prefill | DEC-09b (§2.4 Amend 2) |
| DPC rules | 10 (4 DENY + 6 ESCALATE) | DEC-10 + Task 4.12g |
| Latency budget | 2,000ms P95 | ADR-012 §2.5 |

### 3.3 AO-Specific Parameters

| Parameter | Value | Decision |
|-----------|-------|----------|
| `max_new_tokens` | 4,096 (circuit breaker cap) | DEFERRED_TO_TASK5 — see §7.1 |
| Thinking mode | `/no_think` default in system prompt; user may append `/think` per-turn | ADR-012 §2.4, copilot-instructions.md |
| System prompt | Existing `_DEFAULT_SYSTEM_PROMPT` (retained, ends with `/no_think`) | Unchanged |

---

## 4. File Inventory

### 4.1 Files to MODIFY (production source)

| # | File | Change Description | Milestone |
|---|------|--------------------|-----------|
| 1 | `services/policy_agent/src/gpu_inference.py` | Wire draft_model + SchedulerConfig + runtime properties into `load_model()`. Add `num_assistant_tokens` to GenerationConfig in `classify_car()`. | M5.1 |
| 2 | `services/assistant_orchestrator/src/npu_inference.py` | **RENAME** to `gpu_inference.py`. Rename class `OrchestratorNPUInference` → `OrchestratorGPUInference` (+ backward-compat alias). Rewrite `load_model()` for GPU + speculative decoding. Update `GenerationConfig` defaults: `do_sample=False`, `temperature=0.0`. Wire `stop_token_ids=[151645]`, `num_assistant_tokens=3`. Remove NPU-specific config (`PERFORMANCE_HINT`, `MODEL_PRIORITY`). | M5.2 |
| 3 | `services/assistant_orchestrator/src/constants.py` | Update `MODEL_DIR` from `"models/qwen2.5-1.5b-instruct/openvino-int4-npu"` to `"models/qwen3-14b/openvino-int4-gpu"`. Deprecate `NPU_PRIORITY` re-export. | M5.2 |
| 4 | `services/assistant_orchestrator/src/entrypoint.py` | **Config resolver overhaul** (not just an import update): (a) `_load_entrypoint_config()`: change `config_data.get("npu", {})` → `config_data.get("gpu", {})` (line 319). (b) `_validate_config_data()`: change `self._require_section_dict(config_data, "npu", ...)` → `"gpu"` (line 423). (c) Flip device validation from `device.upper() != "NPU"` → `!= "GPU"` (line 425). (d) Update error codes: `AO_CFG_NPU_SECTION_MISSING` → `AO_CFG_GPU_SECTION_MISSING`, `AO_CFG_NPU_DEVICE_MISSING` → `AO_CFG_GPU_DEVICE_MISSING`. (e) Update ADR reference in validation error message from ADR-010 → ADR-011. (f) Update import from `npu_inference` → `gpu_inference`, `OrchestratorNPUInference` → `OrchestratorGPUInference`. Note: TOML files already use `[gpu]` section headers (updated during ADR-011) — the code lags behind. | M5.2 |
| 5 | `services/assistant_orchestrator/config/default.toml` | Update `model_dir` from `"models/qwen2.5-1.5b-instruct/openvino-int4-npu"` → `"models/qwen3-14b/openvino-int4-gpu"`. Update `weight_manifest` from `"models/qwen2.5-1.5b-instruct/openvino-int4-npu/manifest.json"` → `"models/qwen3-14b/openvino-int4-gpu/manifest.json"`. Remove `PROVISIONAL` comments. | M5.2 |
| 6 | `services/assistant_orchestrator/config/guest_runtime.toml` | Same `model_dir` and `weight_manifest` updates as `default.toml`. | M5.2 |

### 4.2 Files to MODIFY (tests + scripts)

| # | File | Change Description | Milestone |
|---|------|--------------------|-----------|
| 7 | `services/assistant_orchestrator/tests/test_npu_inference.py` | **RENAME** to `test_gpu_inference.py`. Update class references and import paths. | M5.3 |
| 8 | `tests/integration/test_p110_end_to_end.py` | Update import `from services.assistant_orchestrator.src.npu_inference import OrchestratorNPUInference` → `gpu_inference` / `OrchestratorGPUInference`. Update latency metric references (`npu_inference_ms` → `gpu_inference_ms` if applicable). | M5.3 |
| 9 | `phase2_gates/scripts/run_p5_feasibility_002.py` | Update import for AO inference class from `npu_inference` → `gpu_inference`. | M5.3 |
| 10 | `services/policy_agent/tests/test_gpu_inference.py` | Verify/update tests for draft_model in `load_model()`, speculative decoding GenConfig params. | M5.1 |

### 4.3 Files to VERIFY (no changes expected)

| # | File | Verification |
|---|------|-------------|
| 11 | `shared/constants.py` | All Qwen3-14B + speculative decoding constants already locked. Confirm `TARGET_MODEL_OV_PATH`, `DRAFT_MODEL_OV_PATH`, `SPECULATIVE_DECODING_ENABLED=True`, `NUM_ASSISTANT_TOKENS=3`. |
| 12 | `shared/models/weight_integrity.py` | Model-agnostic. Works for any `.bin` file. No changes. |
| 13 | `services/ui_gateway/src/transport.py` | `TransportGateway.check_pa_status()` — verify during M5.4 runtime validation. No code changes unless GATEWAY_HANDSHAKE_FAILED persists. |
| 14 | `launcher/__main__.py` | Gateway handshake flow unchanged. Re-validated during M5.4. |
| 15 | `services/policy_agent/src/adjudicator.py` | DPC prefilter + LLM path. No model-specific changes. |
| 16 | `services/assistant_orchestrator/src/pgov.py` | PGOV output validation. No model-specific changes. |
| 17 | `services/assistant_orchestrator/src/circuit_breaker.py` | Circuit breaker cap (4096 tokens). Architectural constant, not model-specific. |

### 4.4 Additional Import References (to scan during M5.3)

These files may contain `npu_inference` or `OrchestratorNPUInference` references that the M5.3 EA must grep and update:

- `services/policy_agent/tests/test_integration_car_pipeline.py` — has `PolicyGPUInference as PolicyNPUInference` legacy alias
- `services/policy_agent/tests/test_hybrid_adjudicator.py` — has `PolicyGPUInference as PolicyNPUInference` legacy alias
- Any other file matching `grep -r "npu_inference\|OrchestratorNPUInference\|PolicyNPUInference"` in the workspace

---

## 5. EA Milestone Decomposition

### M5.1 — PA Speculative Decoding Wire-Up

**Objective:** Upgrade the Policy Agent's GPU inference harness to use Qwen3-14B with speculative decoding per ADR-012 §2.6 PA profile.

**Files changed:** 1 production file (`gpu_inference.py`), 1 test file (`test_gpu_inference.py`)

**Work items:**
1. Modify `PolicyGPUInference.load_model()`:
   - Add `draft_model=ov_genai.draft_model(draft_path, device)` kwarg to `LLMPipeline` constructor.
   - Add `SchedulerConfig(cache_size=3, enable_prefix_caching=False)` as `scheduler_config` kwarg to `LLMPipeline` constructor.
   - **Merge** new runtime properties into the existing `config` dict (which already contains `PERFORMANCE_HINT="LATENCY"` and `MODEL_PRIORITY="HIGH"/"LOW"`): add `INFERENCE_PRECISION_HINT="f16"` and `GPU_ENABLE_SDPA_OPTIMIZATION="ON"`. Do NOT replace the existing dict — the merged dict is still passed via `**config` to `LLMPipeline`. `draft_model` and `scheduler_config` are separate named kwargs, not part of the config dict.
   - Accept `draft_model_dir` parameter in `__init__()` (default from `DRAFT_MODEL_OV_PATH`).
2. Modify `PolicyGPUInference.classify_car()`:
   - Add `gen_config.num_assistant_tokens = 3` (DEC-01).
   - Verify `stop_token_ids=[151645]` (already correct per Task 4.12g fix).
   - Verify `max_new_tokens=10` (already correct per DEC-08 restoration).
3. Update module-level docstring to reflect Qwen3-14B + speculative decoding.
4. Update/add PA tests for draft_model parameter handling, SchedulerConfig, mocked pipeline construction.

**Gate:** `pytest services/policy_agent/ --tb=short -q` — all tests pass.

**Risk:** LOW. PA is already on GPU. This adds speculative decoding config to an existing, working harness.

---

### M5.2 — AO File Rename + GPU Rewrite

**Objective:** Rename the AO inference module from NPU to GPU, rewrite `load_model()` for Qwen3-14B with speculative decoding, and update constants + entrypoint.

**Files changed:** 3 production files + 2 config files (`npu_inference.py` → `gpu_inference.py`, `constants.py`, `entrypoint.py`, `config/default.toml`, `config/guest_runtime.toml`)

**Work items:**
1. **File rename:** `services/assistant_orchestrator/src/npu_inference.py` → `services/assistant_orchestrator/src/gpu_inference.py` (via `git mv`).
2. **Class rename:** `OrchestratorNPUInference` → `OrchestratorGPUInference`. Add backward-compat alias: `OrchestratorNPUInference = OrchestratorGPUInference`.
3. **Rewrite `load_model()`:**
   - Change default device from `"NPU"` to `"GPU"`.
   - Add `draft_model=ov_genai.draft_model(draft_path, "GPU")` to `LLMPipeline` constructor.
   - Add `SchedulerConfig(cache_size=3, enable_prefix_caching=False)`.
   - Add runtime properties: `INFERENCE_PRECISION_HINT="f16"`, `GPU_ENABLE_SDPA_OPTIMIZATION="ON"`.
   - **Retain** `PERFORMANCE_HINT="LATENCY"` and `MODEL_PRIORITY` — these are device-agnostic OpenVINO compile hints (not NPU-specific), aligned with PA config dict for cross-service consistency.
   - Accept `draft_model_dir` parameter in `__init__()`.
4. **Update `GenerationConfig` defaults:**
   - `do_sample=False` (was `True` — project mandate).
   - `temperature=0.0` (was `0.7`).
   - `top_k`, `top_p`, `repetition_penalty` — set to neutral/disabled values since `do_sample=False`.
5. **Wire generation config in `generate()`:**
   - Add `stop_token_ids=[151645]` to generation config.
   - Add `num_assistant_tokens=3` (DEC-01).
6. **Update `constants.py`:** Change `MODEL_DIR` to `"models/qwen3-14b/openvino-int4-gpu"`.
7. **Update `entrypoint.py` config resolver (CRITICAL — not just imports):**
   - `_load_entrypoint_config()`: Change `config_data.get("npu", {})` → `config_data.get("gpu", {})` and all downstream references from `npu` variable to `gpu`.
   - `_validate_config_data()`: Change `self._require_section_dict(config_data, "npu", ...)` → `"gpu"`. Update error codes: `AO_CFG_NPU_SECTION_MISSING` → `AO_CFG_GPU_SECTION_MISSING`, `AO_CFG_NPU_DEVICE_MISSING` → `AO_CFG_GPU_DEVICE_MISSING`.
   - Flip device validation from `device.upper() != "NPU"` → `device.upper() != "GPU"`. Update error message ADR reference from ADR-010 → ADR-011.
   - Update import from `npu_inference` → `gpu_inference`, `OrchestratorNPUInference` → `OrchestratorGPUInference`.
   - Note: TOML files already use `[gpu]` section headers (updated during ADR-011 work). The Python code lags behind — this fix resolves a latent config/code mismatch.
8. **Update TOML configs:**
   - `config/default.toml`: Update `model_dir` → `"models/qwen3-14b/openvino-int4-gpu"`, `weight_manifest` → `"models/qwen3-14b/openvino-int4-gpu/manifest.json"`. Remove `PROVISIONAL` comments.
   - `config/guest_runtime.toml`: Same `model_dir` and `weight_manifest` updates.
9. Update module-level docstring to reflect GPU + Qwen3-14B + speculative decoding.

**Gate:** `pytest services/assistant_orchestrator/ --tb=short -q` — all tests pass (tests will temporarily break due to import; backward-compat alias covers runtime, but test file still references old module).

**Risk:** MEDIUM. File rename + class rename + load_model rewrite + config resolver overhaul + TOML updates in one session. Backward-compat alias mitigates import breakage. The primary risk is the generate() method's config wiring — the AO's generate path is more complex than PA's (streaming, preemption detection, circuit breaker). Secondary risk: the config resolver changes (`npu` → `gpu` section reads, device validation flip, error code renames) must align exactly with the existing TOML `[gpu]` section structure — mismatch causes `AO_CFG_GPU_SECTION_MISSING` at startup.

**Rollback:** `git mv` is reversible. Branch preserved if tests fail.

---

### M5.3 — Import Cascade + Test Rename + Regression Gate

**Objective:** Update all remaining imports referencing the old NPU module/class names. Rename the AO test file. Clean up legacy aliases. Run full regression.

**Files changed:** 1 test file rename + 3–5 import updates

**Work items:**
1. **Rename test file:** `services/assistant_orchestrator/tests/test_npu_inference.py` → `test_gpu_inference.py` (via `git mv`). Update all class references within.
2. **Update `tests/integration/test_p110_end_to_end.py`:** Change import from `npu_inference` → `gpu_inference`, `OrchestratorNPUInference` → `OrchestratorGPUInference`. Update any latency metric name references.
3. **Update `phase2_gates/scripts/run_p5_feasibility_002.py`:** Change AO import.
4. **Clean up legacy aliases:**
   - `services/policy_agent/tests/test_integration_car_pipeline.py` — remove `PolicyGPUInference as PolicyNPUInference` alias.
   - `services/policy_agent/tests/test_hybrid_adjudicator.py` — remove `PolicyGPUInference as PolicyNPUInference` alias.
5. **Full grep scan:** `grep -r "npu_inference\|OrchestratorNPUInference\|PolicyNPUInference" --include="*.py"` — fix any remaining references.
6. **Regression gate:** `pytest shared/ services/ tests/ --tb=short -q`.

**Gate:** Full regression passes with ≤ 2 pre-existing failures (the same 2 from baseline).

**Risk:** LOW-MEDIUM. Mechanical import updates. The grep scan ensures completeness.

---

### M5.4 — Config Pipeline Hardening (COMPLETE — Injected Milestone)

**Status:** COMPLETE  
**Branch:** `feature/p5-task5-m5.4-config-hardening`  
**Commit:** `53764b0`  
**Date:** 2026-04-19  
**Regression:** 835 passed, 0 failed, 2 skipped  

**Objective:** Harden the TOML-driven configuration pipeline for both PA and AO so that `draft_model_dir` and `speculative_decoding_enabled` are read from TOML config files rather than relying solely on `constants.py` fallback defaults. Eliminate stale `qwen2.5` references from PA config files and `guest_deploy.py`.

**Files changed:** 13 files (4 TOML configs, 2 entrypoints, 2 gpu_inference modules, 1 guest_deploy.py, 3 test files, 1 pytest gate artifact)

**Work items (14 — all DONE):**
1. PA `default.toml` + `guest_runtime.toml`: Add `draft_model_dir` and `speculative_decoding_enabled` keys under `[inference]`
2. AO `default.toml` + `guest_runtime.toml`: Add `draft_model_dir` and `speculative_decoding_enabled` keys under `[gpu]`
3. PA `entrypoint.py`: Read `draft_model_dir` and `speculative_decoding_enabled` from TOML, pass to `PolicyGPUInference.__init__()`
4. AO `entrypoint.py`: Read `draft_model_dir` and `speculative_decoding_enabled` from TOML, pass to `OrchestratorGPUInference.__init__()`
5. PA `gpu_inference.py`: Accept `draft_model_dir` and `speculative_decoding_enabled` in `__init__()`, use in `load_model()`
6. AO `gpu_inference.py`: Accept `draft_model_dir` and `speculative_decoding_enabled` in `__init__()`, use in `load_model()`
7. `launcher/guest_deploy.py`: Update `qwen2.5` references → `qwen3-14b`
8. PA `test_entrypoint.py`: Add coverage for new TOML config keys
9. AO `test_entrypoint.py`: Add coverage for new TOML config keys
10. PA `test_gpu_inference.py`: Add tests for `draft_model_dir` / `speculative_decoding_enabled` parameter handling
11. Verify `constants.py` values remain as fallback defaults only
12. Full `grep` sweep: zero `qwen2.5` matches in PA TOMLs + `guest_deploy.py`
13. Regression gate: `pytest shared/ services/ tests/ --tb=short -q` ≤ 2 pre-existing failures
14. Gate artifact: `pytest_m53_gate.txt` (carried from M5.3 branch — 66 lines)

**Gate:** 835 passed, 0 failed, 2 skipped ✅

**Risk:** LOW. Additive config plumbing — no behavioral change when TOML values match constants.py defaults.

**Note:** This milestone was injected by the Lead Architect between the original M5.3 and M5.4. The original M5.4 (E2E Runtime Validation) has been renumbered to M5.5.

---

### M5.5 — End-to-End Runtime Validation + GATEWAY_HANDSHAKE_FAILED Resolution

**Status:** COMPLETE  
**Branch:** `feature/p5-task5-m5.5-e2e-validation`  
**Commits:** `d72dfaa`, `b78c246`, `814dfc5`  
**Predecessor:** M5.4 (Config Hardening, commit `53764b0`)  
**LEDGER Entry:** 37

**Objective:** Validate the full production pipeline (PA → AO → Gateway → UI) on Qwen3-14B with speculative decoding. Confirm the `GATEWAY_HANDSHAKE_FAILED` regression is resolved by M5.2's config resolver fix.

**Files changed:** 0 expected (evidence-only). If a secondary issue requires a code fix, up to 2 files.

**Work items:**
1. **Run launcher in dev mode:** `python -m launcher --runtime-mode=dev` (host-loopback gateway). Capture boot log.
2. **Validate gateway handshake:** Confirm `check_pa_status()` returns True. If FAIL:
   - Inspect PA entrypoint log: did `PolicyGPUInference.load_model()` succeed?
   - Inspect AO entrypoint log: did `OrchestratorGPUInference.load_model()` succeed?
   - Inspect vsock listener binding: is PA listening on port 50000?
   - Root-cause, fix, re-run.
3. **Capture evidence artifacts:**
   - `phase2_gates/evidence/task5_runtime_validation.json` — boot sequence, handshake status, model load confirmation.
   - `phase2_gates/evidence/task5_pa_classification_smoke.json` — 5 CAR classifications via PA (3 ALLOW, 1 DENY, 1 ESCALATE).
   - `phase2_gates/evidence/task5_ao_generation_smoke.json` — 3 AO prompts with response, timing, token count.
4. **Update LEDGER:** Record Task 5 completion in `docs/POST_OPERATIONAL_MATURATION_LEDGER.md`.
5. **Update IMPLEMENTATION_PLAN.md:** Mark Task 5 COMPLETE.

**Gate:** Gateway handshake PASS + PA smoke PASS + AO smoke PASS + full `pytest` regression ≤ 2 pre-existing failures.

**Risk:** LOW-MEDIUM. Root cause of `GATEWAY_HANDSHAKE_FAILED` is now **identified and fixed in M5.2**: the TOML configs use `[gpu]` section headers (updated during ADR-011), but `entrypoint.py` was reading `config_data.get("npu", {})` — causing `ConfigResolutionError("AO_CFG_NPU_SECTION_MISSING")`. M5.2's config resolver fix resolves this directly.
- **Likely case (HIGH confidence):** M5.2 fixed the regression. M5.5 confirms and captures evidence.
- **Residual risk:** If a secondary issue exists beyond the config mismatch (e.g., 14B compile-time exceeding handshake timeout), M5.5 diagnosis steps cover it.
- **Worst case:** Transport-layer issue (M2 side effect on vsock protocol handling). May require examining `services/ui_gateway/src/transport.py`.

**Rollback:** If M5.5 fails and root-cause cannot be resolved in-session, preserve branch with evidence + failure log for next EA session.

---

## 6. Risk Assessment

| Risk | Severity | Likelihood | Mitigation |
|------|----------|-----------|------------|
| `GATEWAY_HANDSHAKE_FAILED` persists after model swap | LOW-MEDIUM | LOW | Root cause identified and fixed in M5.2: latent TOML/code mismatch (`[gpu]` section vs `config_data.get("npu")`). M5.5 confirms. Residual risk: secondary timing issue with 14B compile time. |
| Qwen3-14B fails to compile on GPU in production context | HIGH | LOW | Model compilation validated in P5-005a/005b feasibility studies. Same `LLMPipeline` API, same device. |
| Import cascade misses a reference | MEDIUM | MEDIUM | M5.3 includes exhaustive `grep` scan. Backward-compat alias in M5.2 provides safety net. |
| AO `GenerationConfig` change (`do_sample=False`) breaks streaming or PGOV | MEDIUM | LOW | Streaming is token-level and independent of sampling strategy. PGOV validates output text, not generation method. |
| Memory contention: PA + AO both on GPU with 14B + draft model | HIGH | LOW | ADR-012 §2.2 measured peak RSS 12,051 MB, within 15,507 MB budget (3,456 MB headroom). Both services share the same compiled model weights (single GPU compilation via unified model path). |
| 2 pre-existing test failures interfere with gate validation | LOW | HIGH | Known and documented. Gate criteria explicitly allow ≤ 2 pre-existing failures. |

---

## 7. Deferred Items

### 7.1 AO `max_new_tokens` Resolution

ADR-012 §2.6 marks AO `max_new_tokens` as `DEFERRED_TO_TASK5`. Resolution:

- **Recommendation:** Set to `OUTPUT_TOKEN_CAP` (4,096) — the existing circuit breaker cap.
- **Rationale:** The circuit breaker already enforces this ceiling as a security measure (OWASP LLM04). Setting `max_new_tokens` to the same value aligns the generation config with the safety net. No empirical optimization required — 4,096 is sufficient for conversational output.
- **Lock in:** M5.2 (wired into `GenerationConfig` defaults).

### 7.2 USE-CASE-005 (Interactive Local Software Engineer) CODE Profile

ADR-012 §2.6 defines a CODE workload profile that inherits AO shared parameters with context-dependent thinking mode. The Code Agent is **not yet in production**. Task 5 wires the unified Qwen3-14B model that CODE will eventually consume, but does not implement the Code Agent dispatcher or thinking mode toggle. CODE profile wiring is a separate future task.

### 7.3 Legacy Model Cleanup

`models/qwen2.5-1.5b-instruct/` is retained on disk for rollback per ADR-012 §3.1. After Task 5 validation is complete and stable for 30 days, the Lead Architect may archive or remove it.

---

## 8. Future Queue

The following use cases are defined in `Use Cases_FINAL.md` and are parked for future phases. They are not in scope for Task 5 but represent the architectural runway that Task 5 enables:

| Use Case | Name | Status | Task 5 Relevance |
|----------|------|--------|-------------------|
| USE-CASE-005 | Interactive Local Software Engineer | Scoped, not in production | Consumes the same Qwen3-14B model wired in Task 5. CODE profile inherits AO shared params. |
| USE-CASE-009 | Autonomous System Maintainer | Parked — Future Phase | Requires controlled outbound network + supply-chain verification. Independent of model swap. |

---

## 9. Milestone Sequencing & Dependencies

```
M5.1 (PA spec decode)  ──┐
                          ├──→  M5.3 (imports + regression)  ──→  M5.4 (config hardening)  ──→  M5.5 (E2E validation)
M5.2 (AO rename+rewrite) ┘
```

- **M5.1 and M5.2 are independent** — can be executed in either order. No cross-dependency.
- **M5.3 depends on both M5.1 and M5.2** — cannot update imports until both modules are in final state.
- **M5.4 depends on M5.3** — TOML config hardening builds on the clean import state from M5.3.
- **M5.5 depends on M5.4** — E2E validation must run on the fully-hardened config pipeline.

Executed order: **M5.1 → M5.2 → M5.3 → M5.4 → M5.5** (M5.4 Config Hardening was injected by Lead Architect directive between the original M5.3 and the original M5.4 E2E validation).

---

## 10. Verification Commands (Non-Dev)

After each milestone, the Lead Architect can verify via terminal:

**After M5.1:**
```powershell
git log --oneline -1
pytest services/policy_agent/ --tb=short -q
```

**After M5.2:**
```powershell
git log --oneline -1
pytest services/assistant_orchestrator/ --tb=short -q
```

**After M5.3:**
```powershell
git log --oneline -1
git diff HEAD~1 --name-only
pytest shared/ services/ tests/ --tb=short -q
```

**After M5.4 (Config Hardening):**
```powershell
git log --oneline -1
git diff HEAD~1 --stat
Select-String -Path "services\policy_agent\config\*.toml","launcher\guest_deploy.py" -Pattern "qwen2\.5"
pytest shared/ services/ tests/ --tb=short -q
```

**After M5.5 (E2E Validation):**
```powershell
git log --oneline -1
python -m launcher --runtime-mode=dev 2>&1 | Select-String "handshake|FAIL|ERROR|ready"
Get-Content phase2_gates/evidence/task5_runtime_validation.json | ConvertFrom-Json | Select-Object disposition, gateway_handshake_ok
pytest shared/ services/ tests/ --tb=short -q
```

---

## 11. Commit Templates

**M5.1:**
```
feat(pa): wire speculative decoding for Qwen3-14B (Task 5 M5.1)

- Add draft_model + SchedulerConfig to PolicyGPUInference.load_model()
- Wire num_assistant_tokens=3, INFERENCE_PRECISION_HINT=f16, SDPA=ON
- Update PA tests for speculative decoding config
- ADR-012 §2.6 PA profile fully wired

Test: pytest services/policy_agent/ — all pass
```

**M5.2:**
```
feat(ao): rename npu_inference→gpu_inference, rewrite for Qwen3-14B (Task 5 M5.2)

- git mv npu_inference.py → gpu_inference.py
- Rename OrchestratorNPUInference → OrchestratorGPUInference (+ alias)
- Rewrite load_model() for GPU + speculative decoding (draft_model, SchedulerConfig)
- Wire do_sample=False, stop_token_ids=[151645], num_assistant_tokens=3
- Update MODEL_DIR to models/qwen3-14b/openvino-int4-gpu
- Overhaul entrypoint.py config resolver: npu→gpu section reads, device validation flip, error codes, ADR ref
- Update config/default.toml + config/guest_runtime.toml model_dir and weight_manifest

Test: pytest services/assistant_orchestrator/ — all pass
```
```

**M5.3:**
```
refactor: update import cascade for AO GPU rename (Task 5 M5.3)

- git mv test_npu_inference.py → test_gpu_inference.py
- Update imports in test_p110_end_to_end.py, run_p5_feasibility_002.py
- Remove legacy PolicyNPUInference aliases
- Full grep scan: zero remaining npu_inference references

Test: pytest shared/ services/ tests/ — 835 passed, 2 skipped
```

**M5.4 (Config Hardening):**
```
feat(config): TOML-driven draft_model_dir + speculative_decoding_enabled (Task 5 M5.4)

- PA + AO: draft_model_dir and speculative_decoding_enabled read from TOML
- Entrypoints pass TOML values to gpu_inference __init__()
- Eliminate stale qwen2.5 references from PA TOMLs + guest_deploy.py
- constants.py values remain as fallback defaults only
- 13 files changed, 184 insertions, 17 deletions

Test: pytest shared/ services/ tests/ — 835 passed, 2 skipped
```

**M5.5 (E2E Validation):**
```
feat: Task 5 E2E validation — Qwen3-14B production pipeline (Task 5 M5.5)

- Gateway handshake: PASS
- PA classification smoke: PASS (5 CARs)
- AO generation smoke: PASS (3 prompts)
- GATEWAY_HANDSHAKE_FAILED regression: [RESOLVED/ROOT_CAUSE]
- Evidence: phase2_gates/evidence/task5_*.json

Test: pytest shared/ services/ tests/ — 835 passed, 2 skipped
LEDGER: Entry 37
```
