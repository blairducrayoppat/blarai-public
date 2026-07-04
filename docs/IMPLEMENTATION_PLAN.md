# BlarAI — Priority 1 Core Loop Implementation Plan

**Version:** 3.18
**Last Updated:** 2026-04-18
**Branch:** `feature/p5-task5-m5.5-e2e-validation` (HEAD: `2801db4`)
**Author:** Copilot Agent (Principal Engineer) + Lead Architect
**Operational Baseline:** USE-CASE-001 + USE-CASE-004 OPERATIONAL (sign-off HEAD: `8f60259` on `feature/p1-uat1-launcher`)
**Target Model (ADR-012):** Qwen3-14B INT4 GPU — unified model for PA, AO, USE-CASE-005

---

## 1. Project Overview

BlarAI is a privacy-first, multi-agent AI system running entirely on local hardware.
The Priority 1 Core Loop implements **USE-CASE-001** (Policy Agent) and **USE-CASE-004**
(Assistant Orchestrator + Semantic Router) — the foundational security and conversational
infrastructure that all other use cases depend on.

### 1.6 Phase 5 Feasibility Snapshot (P5-FEASIBILITY-001)

P5-FEASIBILITY-001 (Context Window Expansion Study) completed as a documentation-only
analytical milestone.

- Study artifact created:
   - `docs/FEASIBILITY_CONTEXT_WINDOW.md`
- Scope executed per prompt:
   - independent feasibility analysis for input context expansion and output cap expansion
   - KV-cache sizing from verified model config (`num_key_value_heads=2`)
   - latency scaling and PGOV security-surface analysis
   - system memory budget impact synthesis against ADR-005/006/010 constraints
- Disposition:
   - Input context window: **DO-NOT-EXPAND** (retain 4,096)
   - Output generation cap: **DO-NOT-EXPAND** (retain host 4,096 / guest 256)
- Date: 2026-02-25
- Commit: `HEAD` (this milestone documentation commit)

### 1.7 Phase 5 Evidence Upgrade Snapshot (P5-FEASIBILITY-002)

P5-FEASIBILITY-002 (Re-Decision Evidence Upgrade) completed as an
evidence-collection milestone with no token-limit implementation changes.

- Primary synthesis artifact:
   - `docs/FEASIBILITY_CONTEXT_WINDOW_ADDENDUM.md`
- Evidence artifacts produced:
   - `phase2_gates/evidence/p5_redecision_protocol.json`
   - `phase2_gates/evidence/p5_input_length_latency_matrix.json`
   - `phase2_gates/evidence/p5_output_length_latency_matrix.json`
   - `phase2_gates/evidence/p5_memory_pressure_matrix.json`
   - `phase2_gates/evidence/p5_pgov_stage5_long_output_coverage.json`
   - `phase2_gates/evidence/p5_pa_long_input_stability.json`
   - `phase2_gates/evidence/p5_redecision_quality_gate.json`
- Evidence quality gate:
   - **FAIL** (EQG-02 unmet)
   - enforced disposition: **NO_DECISION**
   - reason_code: `INSUFFICIENT_EVIDENCE`
- Key blocker observed:
   - stateful NPU prompt-length runtime ceiling failure (`MAX_PROMPT_LEN` path)
      causing unsampled high-band input/output points in this run.
- Date: 2026-02-26 (UTC)
- Commit: `HEAD` (this milestone evidence/docs commit)

### 1.8 Phase 5 Runtime Ceiling Snapshot (P5-FEASIBILITY-003)

P5-FEASIBILITY-003 (Runtime Ceiling Characterization + Containment Validation)
completed as an evidence milestone with no context-window/token-limit implementation
changes.

- Primary synthesis artifact:
   - `docs/FEASIBILITY_CONTEXT_WINDOW_CEILING_ADDENDUM.md`
- Evidence artifacts produced:
   - `phase2_gates/evidence/p5_runtime_ceiling_probe_protocol.json`
   - `phase2_gates/evidence/p5_runtime_ceiling_characterization.json`
   - `phase2_gates/evidence/p5_runtime_ceiling_containment_validation.json`
   - `phase2_gates/evidence/p5_runtime_ceiling_containment_contract.json`
- Dual outcome (required by milestone scope):
   - runtime ceiling characterization: **NOT CHARACTERIZED**
   - over-ceiling containment behavior: **VALIDATED (sampled bands)**
- Evidence quality gate:
   - **FAIL** (critical coverage requirements unmet; `EQG-02`/`EQG-09`)
   - enforced disposition: **NO_DECISION**
   - reason_code: `INSUFFICIENT_EVIDENCE`
- Key empirical boundary observed in this run:
   - `last_passing_band_user_tokens=null`
   - `first_failing_band_user_tokens=768`
   - deterministic fail-closed fingerprint family dominated by `AO_MAX_PROMPT_LEN_*`
   - `partial_release_failures=0` across sampled failing bands
- Date: 2026-02-26 (UTC)
- Commit: `HEAD` (this milestone evidence/docs commit)

### 1.9 Phase 5 Multi-Device Capability Snapshot (P5-FEASIBILITY-004)

P5-FEASIBILITY-004 (Multi-Device Capability Matrix) completed as an empirical
evidence milestone with no production service code changes.

- Primary synthesis artifact:
   - `docs/FEASIBILITY_MULTI_DEVICE_CAPABILITY.md`
- Evidence artifact produced:
   - `phase2_gates/evidence/p5_multi_device_capability_matrix.json`
- Benchmark harness added:
   - `phase2_gates/scripts/run_p5_feasibility_004.py`
- Scope executed:
   - NPU generation re-tested with explicit `MAX_PROMPT_LEN` pipeline configs
      (`1024, 2048, 3072, 4096, 6144, 8192`) using fresh compile per config
   - GPU generation tested for Qwen2.5 and Qwen3
   - CPU generation tested for Qwen2.5 and Qwen3
   - AC power enforcement + fail-closed per-run capture
   - Device Capability Gate evaluation (`DCG-01..DCG-07`)
- Gate result:
   - `all_required_pass=true`
   - disposition: `READY_FOR_ARCH_RECOMMENDATION`
   - `npu_1024_wall_overturned=true`
- Key empirical finding:
   - Prior 1024-token NPU wall was software-default constrained
      (no explicit `MAX_PROMPT_LEN`) and is overturned in this milestone.
   - NPU demonstrated successful generation through 8000 user tokens with
      `MAX_PROMPT_LEN=8192` in this environment.
- Milestone disposition:
   - **HYBRID_NPU_GPU** (recommendation in summary artifact)
   - Any production architecture/device-routing change remains ADR-gated.
- Date: 2026-02-26 (UTC)
- Commit: `HEAD` (this milestone evidence/docs commit)

### 1.10 Phase 5 Unified Model Feasibility Snapshot (P5-FEASIBILITY-005)

P5-FEASIBILITY-005 (Unified Model Feasibility Matrix) executed with fail-closed
evidence capture and produced an **INSUFFICIENT_EVIDENCE** disposition for this run.

- Primary synthesis artifact:
   - `docs/FEASIBILITY_UNIFIED_MODEL.md`
- Evidence artifacts produced:
   - `phase2_gates/evidence/p5_005_model_acquisition.json`
   - `phase2_gates/evidence/p5_unified_model_feasibility_matrix.json`
- Harness/scripts added:
   - `phase2_gates/scripts/acquire_p5_005_models.py`
   - `phase2_gates/scripts/run_p5_feasibility_005.py`
- Environment/feature discovery captured:
   - OpenVINO GenAI draft-model API presence (`openvino_genai.draft_model`)
   - assistant-generation config fields in `GenerationConfig`
   - GPU runtime property support including `KV_CACHE_PRECISION` and
      `GPU_ENABLE_SDPA_OPTIMIZATION`
- Blocking empirical issue observed:
   - `optimum` / `optimum-intel` import incompatibility in `.venv`
   - fingerprint family: `OPTIMUM_INTEL_IMPORT_FAILED`
   - model acquisition for `qwen3-14b`, `qwen3-8b`, and `qwen3-0.6b` did not complete
- Benchmark run outcome:
   - blocked precheck due missing model assets
   - benchmark artifact status: `blocked`
   - quality-gate disposition: `INSUFFICIENT_EVIDENCE`
   - reason_code: `MISSING_MODEL_ASSETS`
- Date: 2026-02-27 (UTC)
- Commit: `HEAD` (this milestone evidence/docs commit)

### 1.11 Phase 5 — ADR-011 NPU Retirement (P5-006)

ADR-011 enacted: ALL LLM inference moved to GPU (Arc 140V). NPU retired from P1 Core Loop.

- **Decision:** Qwen2.5-1.5B-Instruct on NPU is ABANDONED. GPU provides superior
  throughput for 14B-class models. NPU retained only for future lightweight tasks
  (embedding, time-series) outside the P1 Core Loop.
- **Branch:** `feature/p5-feasibility-005-unified-model`
- **Date:** 2026-02-27
- **Ledger Entry:** P5-006

### 1.12 Phase 5 — Extended Context Optimization (P5-005b)

P5-005b (Extended Context + Optimization Characterization) completed on
`feature/p5-feasibility-005b-context-optimization`.

- Evidence artifact: `phase2_gates/evidence/p5_005b_context_optimization_matrix.json`
- Summary artifact: `phase2_gates/evidence/p5_005b_context_optimization_summary.md`
- Best configuration: XAttention=OFF, num_assistant_tokens=3, KV_CACHE_PRECISION=FP16
  - **UPDATE (Task 4.4):** XAttention finding reversed — full 4-band sweep confirms `GPU_ENABLE_SDPA_OPTIMIZATION=ON` is universally better (+5.8% TPS / +26.1% TTFT at 4K). ADR-012 §2.2 updated to ON LOCKED.
- Maximum safe context: 20,480 tokens (OOM at 24K)
- Memory peak at 20K context: 12,517 MB
- TPS degradation: 4K→8K minimal, 16K→20K moderate, 24K OOM
- Disposition: `CONTEXT_EXPANSION_FEASIBLE` (16K recommended cap, 20K max safe)
- Commit: `62b44a2`
- Date: 2026-02-28

### 1.13 Phase 5 — ADR-012 Qwen3-14B Model Selection Lock

ADR-012 enacted: Qwen3-14B (INT4, GPU) locked as unified target model for PA, AO, and
USE-CASE-005. Speculative decoding with a draft model is mandatory.

- **Model:** Qwen3-14B — 40 layers, 5120 hidden, 8 KV heads (GQA), ~9.1 GB INT4 symmetric
- **Path:** `models/qwen3-14b/openvino-int4-gpu/`
- **Consumers:** Policy Agent (M2), Assistant Orchestrator (M3), USE-CASE-005 Code Agent
- **Draft model (operational):** Qwen3-0.6B INT4 — 28 layers, 1024 hidden, ~367 MB
- **Configuration optimization in progress:** draft model selection, context window cap,
  num_assistant_tokens, runtime properties (see ADR-012 §2.2)
- **Previous model demoted:** Qwen2.5-1.5B-Instruct → legacy reference
- **Branch:** `feature/p5-feasibility-005b-context-optimization`
- **Date:** 2026-02-28
- **Ledger Entry:** ADR-012 (Entry 8)

### 1.14 Phase 5 — ADR-012 §2.4 Thinking Mode Strategy Lock

Thinking mode strategy locked per ADR-012 §2.4. KV_CACHE_PRECISION locked at FP16.

- **Policy Agent:** `/no_think` system prompt + `stop_token_ids=[151645, 151668]`
  (defense-in-depth: blocks `<|think|>` token at decode level)
- **Assistant Orchestrator:** Thinking allowed (default) + `stop_token_ids=[151645]`
- **USE-CASE-005 Code Agent:** Context-dependent `/think` or `/no_think` +
  `stop_token_ids=[151645]`
- **Qwen3 Token IDs:** `151645`=`<|im_end|>`, `151668`=`<|think|>`, `151669`=`</think>`
- **KV_CACHE_PRECISION:** FP16 LOCKED (INT8 ruled out empirically)
- **Branch:** `feature/p5-005c-pruned-draft-acquisition`
- **Date:** 2026-02-28
- **Ledger Entry:** ADR-012 §2.4 (Entry 9)

### 1.15 Phase 5 — Thinking Mode M1: Policy Agent Implementation

PA thinking mode implementation per ADR-012 §2.4 lock. `/no_think` enforcement +
dual stop-token defense-in-depth wired into GPU inference pipeline.

- **Files modified:**
  - `services/policy_agent/src/gpu_inference.py` — `/no_think` prompt injection,
    `stop_token_ids=[151645, 151668]` in GenerationConfig
  - `services/policy_agent/tests/test_gpu_inference.py` — thinking mode coverage
  - `shared/constants.py` — `PA_THINKING_MODE`, `PA_STOP_TOKEN_IDS`, Qwen3 token constants
- **Branch:** `feature/p5-m1-pa-thinking-mode`
- **Commits:** `601eb71`, `d452003`, `add0a05`
- **Test count:** 772/772 passing

### 1.16 Phase 5 — Thinking Mode M2: Assistant Orchestrator Implementation

AO thinking mode implementation per ADR-012 §2.4 lock. Default thinking allowed +
`stop_token_ids=[151645]` wired into orchestrator inference pipeline.

- **Files modified:**
  - `services/assistant_orchestrator/src/npu_inference.py` — thinking-allowed mode,
    `stop_token_ids=[151645]` in GenerationConfig
  - `services/assistant_orchestrator/tests/test_npu_inference.py` — thinking mode coverage
  - `shared/constants.py` — `AO_THINKING_MODE`, `AO_STOP_TOKEN_IDS`
- **Branch:** `feature/p5-m2-ao-thinking-mode`
- **Commit:** `155ea61`
- **Test count:** 784/784 passing

### 1.17 Phase 5 — Task 4.1: AO /no_think Default + ADR-012 §2.5 PA Latency Budget

AO /no_think default implemented. Task 4 specification and governance artifacts committed.
ADR-012 §2.5 PA latency budget locked at 2,000ms P95 flat (replaces invalid 125ms baseline).

- **Branch:** `feature/p5-task4-1-adr-addendum`
- **Date:** 2026-03-01
- **LEDGER Entry:** 13
- **Files committed:**
  - `services/assistant_orchestrator/src/npu_inference.py` — /no_think in _DEFAULT_SYSTEM_PROMPT
  - `services/assistant_orchestrator/tests/test_npu_inference.py` — inverted assertion
  - `docs/adrs/ADR-012-Qwen3-14B-Model-Selection-Speculative-Decoding.md` — §2.5 added
  - `docs/P5_TASK4_PRODUCTION_CONFIG_FEASIBILITY.md` — Task 4 full specification (new)
  - `docs/P5_TASK4_SDO_HANDOFF.xml` — SDO handoff v3.4 (new)
  - `.github/copilot-instructions.md` — v3.2 update
- **PA latency budget locked:** 2,000ms P95 flat (ADR-012 §2.5). Derivation: 10.72 tps
  empirical + TTFT 408ms at 4K + overhead + P95 variance headroom. Worst-case at
  max_new_tokens=32 (~2,987ms) EXCEEDS budget — Task 4.8 must reduce max_new_tokens.
- **UAT gate opened:** UAT-4a (AO /think toggle — Qwen3-14B/GPU prerequisite)
- **Test baseline:** 786 collected / 755 passed (31 deferred p114 asyncio — pre-existing)

### 1.18 Phase 5 — Task 4.9a: PA System Prompt Revision + Quality Gate Re-Gate

PA system prompt revised per SDO directive (D-1): DENY/ESCALATE boundary sharpened
(determinable-from-request principle), path-based rules added (RC-2), authority-claim
resistance clause added (RC-3). 4 ground truth labels recalibrated (cases 14, 19, 37, 39:
ESCALATE→DENY). Quality gate re-run: agreement 0.775 (31/40), up from 0.575 baseline.
Adversarial security 1.000 (was 0.625 — security gap closed). Still below 0.90 threshold.

- **Branch:** `feature/p5-task4-9-pa-quality-gate`
- **Date:** 2026-03-05
- **LEDGER Entry:** 24
- **Disposition:** QUALITY_GATE_FAIL (DEC-09a) — 0.775 < 0.90
- **Key metric deltas:** +0.200 agreement, +0.375 adversarial security
- **Remaining pattern:** 7 DENY→ESCALATE label_swap + 2 ESCALATE→ALLOW false_positive_allow
- **Next:** Escalate to SDO for D-3 (/no_think removal evaluation)

### 1.19 Phase 5 — Task 4.9b: /no_think Removal Measurement

Measurement task: empirical test of PA classification quality when `/no_think` is removed
from system prompt (CoT enabled). Parser hardened with think-block stripping (C-3) and
multi-label rejection. Harness overrides: `/no_think` stripped, `max_new_tokens=64`.

Results: **MEASUREMENT_HARD_FAIL_LABEL_EXTRACTION**. Removing `/no_think` causes Qwen3-14B
to enter unbounded CoT reasoning chains. All 120/120 runs hit the 64-token ceiling.
0/120 completed think blocks. 111/120 multi-label rejected. 9/120 label extraction.
agreement_rate=0.025 (1/40), adversarial_security=0.125. Latency 3-6× worse than baseline.

- **Branch:** `feature/p5-task4-9-pa-quality-gate`
- **Date:** 2026-03-05
- **LEDGER Entry:** 25
- **Disposition:** MEASUREMENT_HARD_FAIL_LABEL_EXTRACTION
- **Key finding:** `/no_think` is MANDATORY for PA classification (DEC-09b LOCKED)
- **Baseline delta:** -0.750 agreement (4.9a=0.775 → 4.9b=0.025)
- **Parser hardening:** ClassificationParser C-3 committed (think-strip + multi-label rejection)
- **Production impact:** None — production `SYSTEM_PROMPT` retains `/no_think` (K-2 preserved)

### 1.20 Phase 5 — Task 4.9c: Deterministic Pre-filter + ESCALATE Refinement

Deterministic pre-filter (4 DENY rules) short-circuits 23/40 cases before LLM inference.
ESCALATE prompt refinement adds cross-agent ownership mismatch and 100MB write threshold
bullets. Harness reverted to production config (`max_new_tokens=10`, `/no_think` retained).

Results: **PASS** (agreement=0.925, adversarial_security=1.000). 37/40 correct. 8/9 prior
disagreements resolved (7 by prefilter, 1 by LLM). 2 new disagreements: case 17 (ESCALATE->ALLOW,
boundary regression) and case 27 (RISK-1 /certs/ substring -> prefilter DENY instead of ESCALATE).

- **Branch:** `feature/p5-task4-9-pa-quality-gate`
- **Date:** 2026-03-05
- **LEDGER Entry:** 26
- **Disposition:** PASS
- **Measurements:**
  - M-1 decision_agreement_rate: 0.925 (threshold 0.90) — PASS
  - M-2 adversarial_security_rate: 1.000 (threshold 1.000) — PASS
  - M-3 prefilter_coverage: 23 cases (DENY_RESTRICTED_PATH:19, DENY_EXTERNAL_NETWORK:1, DENY_EXFILTRATION:3)
  - M-4 label_extraction_rate: 40/40
  - M-5 delta_from_4_9a: +8 resolved, -2 regressed (net +6)
  - M-6 latency: prefilter P50=0ms, LLM band-512 P50~2450ms, band-4096 P50~13500ms
- **Decision:** DEC-10 LOCKED. DR-02 resolved. Task 4.10 UNBLOCKED.
- **Evidence:** `phase2_gates/evidence/p5_task4_9c_deterministic_prefilter.json`

### 1.21 Phase 5 — Task 4.9d: ESCALATE Hardening + RISK-1 Carve-Out

Deterministic ESCALATE rules (cross-agent ownership, infra config write) + /certs/renew/
carve-out. Prompt bullet revert (cross-agent bullet caused Case 17 regression). Harness
bug fixes (stub_car field extraction, ESCALATE label propagation). 16 new unit tests.

Results: **PASS** (agreement=1.000, adversarial_security=1.000). 40/40 correct. All 3
residual ESCALATE disagreements from 4.9c resolved. ESCALATE per-class accuracy 100% (6/6).
Prefilter coverage expanded from 22/40 to 25/40 (22 DENY + 3 ESCALATE).

- **Branch:** `feature/p5-task4-9-pa-quality-gate`
- **Commit:** `40443b0`
- **Date:** 2026-03-05
- **LEDGER Entry:** 27
- **Disposition:** PASS
- **Measurements:**
  - M-1 decision_agreement_rate: 1.000 (threshold 0.95) — PASS
  - M-2 adversarial_security_rate: 1.000 (threshold 1.000) — PASS
  - M-3 prefilter_coverage: 25 cases (DENY: 22, ESCALATE: 3)
  - M-4 label_extraction_rate: 40/40
  - M-5 delta_from_4_9c: +3 resolved, 0 regressed
  - M-6 latency: prefilter P50=0ms, LLM P50 within budget
- **Evidence:** `phase2_gates/evidence/p5_task4_9d_escalate_hardening.json`

### 1.22 Phase 5 — Task 4.11: Security Hardening (Pre-Task-5)

Security audit (docs/SECURITY_ASSESSMENT.md, 2026-03-05) identified critical gaps that must
be closed before the Task 5 model upgrade to Qwen3-14B. Scoped as a single-session EA task.

**P0 — Critical:**
- mTLS CN → `source_agent` validation: extract peer cert CN via `getpeercert()`, validate
  against `car.source_agent`, Fail-Closed DENY on mismatch. The ESCALATE_CROSS_AGENT_OWNERSHIP
  rule (Task 4.9d) depends on `source_agent` integrity.
- `parameters_schema` JSON Schema vocabulary validation + prompt boundary delimiters to
  defend against prompt injection via serialized CAR fields.

**P1 — High:**
- Authority claim regex: Unicode normalization + expanded pattern set.
- `sensitivity` field: remove default, make required (API-breaking, coordinate with callers).

**P2 — Low:**
- NonceStore: `time.time()` → `time.monotonic()`.
- Config path: symlink check.
- Confidence fallback: fail-closed instead of 0.995 default.

- **Branch:** feature/p5-task4-11-security-ea1 (EA-1) / feature/p5-task4-11-security-ea2 (EA-2)
- **Date:** 2026-03-07 (EA-1) / 2026-03-08 (EA-2)
- **LEDGER Entry:** 33 (POST_OPERATIONAL_MATURATION_LEDGER)
- **Disposition:** COMPLETE (EA-1 + EA-2 scope)
- **Gate (EA-1):** P0-1 + P0-2 closed. pytest shared/ services/ → 742/744 passed (2 pre-existing).
  All new tests pass (Group I vsock, Group G ipc CN, Group J gpu schema/boundary).
  RECON-1 sensitivity audit: docs/P5_TASK4_11_SENSITIVITY_RECON.md written.
- **Gate (EA-2):** P1 + P2 + DOC-1 closed. pytest shared/ services/ → 749/751 passed (2 pre-existing).
  7 new tests pass (2 Unicode homoglyph NFKD, 4 symlink guard / config path, 1 sensitivity required).
- **Deliverables (EA-1):**
  - D-1: shared/ipc/vsock.py — `_extract_cn()`, `peer_cn` property, CN extraction in `accept()`
  - D-2: services/policy_agent/src/ipc.py — Fail-Closed CN validation block in `handle_request()`
  - D-3: services/policy_agent/src/gpu_inference.py — `_SCHEMA_ALLOWLIST`, `validate_parameters_schema()`, boundary markers in `format_car()`, SYSTEM_PROMPT updated
  - D-4: docs/P5_TASK4_11_SENSITIVITY_RECON.md — sensitivity fixture audit
  - D-5: This section update
- **Deliverables (EA-2):**
  - D-6: services/policy_agent/src/gpu_inference.py — NFKD normalization (RULE 2 + RULE 4) + `ensure_ascii=False` + `_DEFAULT_LABEL_CONFIDENCE` → 0.0
  - D-7: shared/schemas/car.py — `sensitivity` field made required (no default; explicit `UNCLASSIFIED` still accepted)
  - D-8: services/policy_agent/src/car.py — `build_car()` `sensitivity` promoted to required positional parameter
  - D-9: shared/crypto/jwt_validator.py — NonceStore `time.time()` → `time.monotonic()`
  - D-10: shared/runtime_config.py — symlink guard (`CFG_SYMLINK_REJECTED`) in `resolve_service_config_path()`
  - D-11: services/policy_agent/tests/test_gpu_inference.py — 2 Unicode homoglyph tests (RULE 2 + RULE 4 NFKD paths); mock confidence fix
  - D-12: services/policy_agent/tests/test_car.py — sensitivity required fixture updates; new `test_build_car_sensitivity_required`
  - D-13: services/policy_agent/tests/test_rule_engine.py — sensitivity field added to all direct CAR constructions
  - D-14: shared/tests/test_runtime_config.py — NEW: symlink guard, missing file, mode mismatch tests
  - D-15: docs/adrs/ADR-012-Qwen3-14B-Model-Selection-Speculative-Decoding.md — Draft-B ACQUIRING → ELIMINATED; decision locked

### 1.23 Phase 5 — Task 4.10: Workload Profile Lock + ADR-012 §2.2 Finalization

DOCS-ONLY milestone. Task 4 Production Configuration Feasibility Study closure.
All remaining EVALUATING parameters in ADR-012 §2.2 resolved: input/output split
to ADVISORY (per Q-1), GenConfig composite to LOCKED with AO/CODE max_new_tokens
DEFERRED_TO_TASK5 (per Q-2). Zero EVALUATING rows remain.

Three production workload profiles compiled (PA, AO, CODE) in ADR-012 §2.6.
Decision registry evidence artifact generated with all 10 locked decisions
(DEC-01 through DEC-10).

- **Type:** DOCS-ONLY
- **Branch:** feature/p5-task4-9-pa-quality-gate
- **Commit:** (pending)
- **Date:** 2026-03-05
- **LEDGER Entry:** 28
- **Disposition:** COMPLETE
- **Deliverables:**
  - D-1: ADR-012 §2.2 zero EVALUATING rows
  - D-2: ADR-012 §2.6 production workload profiles
  - D-3: phase2_gates/evidence/p5_task4_10_profile_lock_summary.json
  - D-4: LEDGER Entry 28
  - D-5: This section (IMPLEMENTATION_PLAN §1.23)
  - D-6: P5_TASK4_PRODUCTION_CONFIG_FEASIBILITY.md §0 update
  - D-7: ADR-012 header status change
- **Evidence:** phase2_gates/evidence/p5_task4_10_profile_lock_summary.json

### 1.24 Phase 5 — Task 4.12: PA Quality Gate Corpus Hardening

IMPLEMENTATION + MEASUREMENT milestone. SDO coverage audit of Task 4.9d evidence
revealed that the DeterministicPolicyChecker absorbs 25/40 test cases before the LLM,
leaving only 15 LLM-classified cases (12 ALLOW, 0 DENY, 3 ESCALATE). Zero adversarial
or boundary cases reach the LLM. DENY_AUTHORITY_CLAIM rule has zero empirical validation
(masked by DENY_RESTRICTED_PATH firing first on /system/ resources).

Corpus expanded from 40 → 256 cases across 5 EA sessions (EA-1 scaffolding, EA-2 Cat A,
EA-3 Cat B, EA-4 Cat C/D/E, EA-5 upper-band 8K+12K). EA-5 ran the full quality gate
(256 × 3 = 768 LLM calls) and computed all 8 measurements.
Categories: '?':40 (original), A:70, B:70, C:24, D:12, E:12, F:14 (8K), G:14 (12K).
Label distribution: ALLOW=24, DENY=194, ESCALATE=38.

- **Type:** IMPLEMENTATION + MEASUREMENT (harness expansion, no production code changes)
- **Branch:** `feature/p5-task4-12-corpus-hardening` → `feature/p5-task4-12-thinking-regate`
- **Commit:** EA-5 (/no_think baseline), EA-6 (thinking mode re-gate)
- **Date:** 2026-03-06 → 2026-04-17
- **LEDGER Entry:** 29 (4.12e /no_think), 30 (4.12f thinking re-gate)
- **Disposition:** **QUALITY_GATE_FAIL** — 2 BLOCKING gates remain after thinking mode re-gate
  - 4.12e (/no_think): M-1=0.6055, M-2=0.7976, M-5=0.7763 — 3 BLOCKING
  - 4.12f (thinking): M-1=0.7227, G-02 LABEL_EXTRACTION (14 TRUNC) — 2 BLOCKING; M-2/M-5 RESOLVED
- **Predecessor:** Task 4.10 (Entry 28)
- **Gap Analysis:** docs/Task4.12_PA_QUALITY_GATE_COVERAGE_ANALYSIS.md
- **Evidence:** `phase2_gates/evidence/p5_task4_12_corpus_hardening.json` (4.12f results)
  `phase2_gates/evidence/p5_task4_12_corpus_hardening_nothink_baseline.json` (4.12e /no_think)

### 1.25 Phase 5 — Task 4.12g: PA /no_think Revert + DPC ESCALATE Expansion + Quality Gate Re-Run

IMPLEMENTATION + MEASUREMENT milestone. Lead Architect accepted Option B (2026-04-17) following
Task 4.12f thinking mode experiment failure. Thinking mode produced +11.7% agreement but
introduced G-02 TRUNC regression (14 nulls) and ESCALATE recall only 38.6% (17/44).

**Scope — 3 deliverables:**
1. **Revert PA to /no_think:** Restore `MAX_NEW_TOKENS=10`, `STOP_TOKEN_IDS=[151645, 151668]`
   in production code + quality gate harness. Remove thinking mode prompt modifications.
2. **DPC ESCALATE expansion:** Add ESCALATE rules to `DeterministicPolicyChecker` for 6
   identified sub-types: Cat B-E1 (crypto boundary), Cat B-E2 (delegation chain), Cat B-E3
   (privilege boundary), Cat B-E4 (auth scope), Cat B-E5 (resource ownership), Cat E
   (multi-axis ambiguity). Target: move high-confidence ESCALATE patterns from LLM path to DPC.
3. **Quality gate re-run:** Execute full 256-case × 3-run quality gate under /no_think with
   expanded DPC. Must meet all 5 quality gates (G-01..G-05) to close Task 4.12.

- **Type:** IMPLEMENTATION + MEASUREMENT (production code change + quality gate)
- **Branch:** `feature/p5-task4-12-thinking-regate` (continuation)
- **Predecessor:** Task 4.12f / Ledger Entry 30 (QUALITY_GATE_FAIL), Entry 31 (DECISION)
- **LEDGER Entry:** 31 (decision), 32 (TBD — execution results)
- **Disposition:** PENDING EXECUTION
- **ADR-012:** §2.4 Amendment 2 recorded. §2.2 GenConfig LOCKED. §2.6 PA profile restored.

### 1.26 Phase 5 — Task 5: Qwen3-14B Production Model Upgrade (COMPLETE)

Production model upgrade from Qwen3-1.7B INT4 (PA on GPU, AO on NPU) to Qwen3-14B INT4
(both PA and AO on GPU) with speculative decoding using Qwen3-0.6B INT4 draft model.
Full plan: `docs/P5_TASK5_MODEL_UPGRADE_PLAN.md`.

**Milestones completed:**

| Milestone | Description | Branch | Commit | Tests |
|-----------|-------------|--------|--------|-------|
| M5.1 | PA Speculative Decoding Wire-Up | `feature/p5-task5-m5.1-pa-spec-decode` | `a4a4b17` | PA focused PASS |
| M5.2 | AO File Rename + GPU Rewrite | `feature/p5-task5-m5.2-ao-gpu-rewrite` | `3763f5a` | 753 passed, 2 failed (pre-existing), 2 skipped |
| M5.3 | Import Cascade + Test Rename + Regression | `feature/p5-task5-m5.3-import-cascade` | `1a7ab25` | 835 passed, 2 skipped |
| M5.4 | Config Pipeline Hardening (injected) | `feature/p5-task5-m5.4-config-hardening` | `53764b0` | 835 passed, 2 skipped |
| M5.5 | E2E Runtime Validation + Handshake Confirmation + Test Streamlining | `feature/p5-task5-m5.5-e2e-validation` | `2801db4` | 755 passed, 2 skipped, 80 deselected (152s); boot PASS; PA 5/5; AO 3/3 |

- **Type:** IMPLEMENTATION (M5.1–M5.4) + VALIDATION (M5.5)
- **LEDGER Entries:** 34a (M5.1), 34 (M5.2), 35 (M5.3), 36 (M5.4), 37 (M5.5)
- **Key outcomes:** GATEWAY_HANDSHAKE_FAILED root cause confirmed (M5.2 config resolver fix), 10 locked decisions wired, all stale qwen2.5 references eliminated, TOML-driven config pipeline hardened
- **ADR-012:** All §2.6 profiles wired. DEC-01 through DEC-10 implemented.

### 1.4 Operational Gap Closure Snapshot (Priority 8)

Priority 8 (functional measured-boot ordering) is complete for this session
scope at code and validation level, with deterministic fail-closed behavior:

- Functional measured-boot sequencing implemented for Policy Agent startup:
   - `services/policy_agent/src/boot.py`
   - ordered gate phases enforced: attestation → weight integrity → model load
     → rules load → listener start
   - deterministic bounded retry policy (`max_attempts=3`, `retry_delay_s=0.25`)
   - hard-lock state emitted after exhaustion (`hard_locked=true`)
- Policy Agent entrypoint now treats measured boot as authoritative gate:
   - `services/policy_agent/src/entrypoint.py`
   - startup fails closed until measured-boot phases complete in order
   - retry/hard-lock outcomes surfaced via deterministic failure fingerprints
   - post-exhaustion startup attempts are blocked in-process (`PA_BOOT_HARD_LOCKED`)
- Launcher startup now explicitly gates dependent service boot on PA measured-boot:
   - `launcher/__main__.py`
   - fail-closed abort on measured-boot failure before orchestrator startup
   - PA-first trust chain preserved for runtime bring-up
- Focused regression coverage added for measured-boot retry/lock semantics:
   - `services/policy_agent/tests/test_boot.py`
   - `services/policy_agent/tests/test_entrypoint.py`
   - `launcher/tests/test_launcher.py`

Validation evidence (session):
- `python -m py_compile services/policy_agent/src/boot.py services/policy_agent/src/constants.py services/policy_agent/src/entrypoint.py launcher/__main__.py launcher/tests/test_launcher.py services/policy_agent/tests/test_boot.py services/policy_agent/tests/test_entrypoint.py`
- `.venv\Scripts\python.exe -m pytest launcher/tests/test_launcher.py services/policy_agent/tests/test_boot.py services/policy_agent/tests/test_entrypoint.py -q` → `18 passed`
- `.venv\Scripts\python.exe -m pytest tests/integration/test_p110_end_to_end.py -q` → `49 passed`

### 1.4a Operational Exit Milestone 1 Snapshot (UAT-2 Real-Runtime Activation)

Operational Exit Milestone 1 is complete for this session scope at launcher
operational-path wiring, fail-closed behavior, and deterministic evidence level:

- Explicit launcher profile switch added for UAT staging:
   - `BLARAI_LAUNCH_PROFILE=uat1_mock|uat2_real`
   - default remains `uat1_mock` to preserve UAT-1.
- UAT-2 operational path no longer depends on mock backend startup:
   - `uat2_real` bypasses `MockPAServer`.
   - `TransportGateway` is initialized for real-runtime path (`dev_mode=False`).
- UAT-2 fail-closed startup requirements enforced pre-UI:
   - VM start required in `uat2_real`; failure aborts startup deterministically.
   - real-runtime handshake preflight required before TUI launch.
- Deterministic activation evidence file added:
   - `phase2_gates/evidence/uat2_real_runtime_activation.json`
   - includes profile, runtime mode, per-step state, disposition, and failure code.
- Focused launcher coverage updated:
   - `launcher/tests/test_launcher.py` validates UAT-2 mock bypass and fail-closed
      VM/handshake failure behavior.

Validation evidence (session):
- `python -m py_compile launcher/__main__.py launcher/tests/test_launcher.py services/ui_gateway/src/transport.py services/ui_gateway/tests/test_transport.py services/policy_agent/src/entrypoint.py services/policy_agent/tests/test_entrypoint.py services/assistant_orchestrator/src/entrypoint.py services/assistant_orchestrator/tests/test_entrypoint.py`
- `.venv\Scripts\python.exe -m pytest launcher/tests/test_launcher.py services/ui_gateway/tests/test_transport.py services/policy_agent/tests/test_entrypoint.py services/assistant_orchestrator/tests/test_entrypoint.py -q` → `75 passed`
- `.venv\Scripts\python.exe -m pytest tests/integration/test_p110_end_to_end.py -q` → `49 passed`
- `BLARAI_LAUNCH_PROFILE=uat2_real .venv\Scripts\python.exe -m launcher` in non-elevated host context produced deterministic evidence:
   - disposition: `ELEVATION_HANDOFF`
   - code: `UAC_PROMPT_TRIGGERED`

Residual blocker (Milestone-1 bounded scope):
- Elevated continuation path execution is required to capture full in-process
   UAT-2 handshake/prompt flow evidence beyond UAC handoff.

### 1.4b Operational Exit Milestone 2 Snapshot (Elevated In-Process UAT-2 Execution)

Operational Exit Milestone 2 is **complete** for this session scope at elevated
in-process runtime execution and deterministic evidence capture:

- Mandatory validation order completed:
   - compile gate PASS
   - focused regression gate PASS (`75 passed`)
   - integration guardrail PASS (`49 passed`)
- Elevated in-process launcher execution completed with `uat2_real` profile:
   - `phase2_gates/evidence/uat2_real_runtime_activation.json`
   - `startup_profile=uat2_real`, `runtime_mode=host`
   - `steps.admin_ok=true`
   - `steps.vm_running=true`
   - `steps.policy_agent_started=true`
   - `steps.assistant_orchestrator_started=true`
   - `steps.gateway_initialized=true`
   - `steps.gateway_handshake_ok=true`
   - `steps.prompt_flow_ok=true`
   - `disposition=PASS`, `failure=null`
- Minimal prompt-flow evidence captured through real runtime path:
   - `phase2_gates/evidence/uat2_milestone2_prompt_flow.json`
   - deterministic request/session IDs captured with PGOV result payload
- Session evidence summary updated:
   - `phase2_gates/evidence/uat2_milestone2_summary.md`

Validation evidence (session):
- `python -m py_compile launcher/__main__.py launcher/tests/test_launcher.py services/ui_gateway/src/transport.py services/ui_gateway/tests/test_transport.py services/policy_agent/src/entrypoint.py services/policy_agent/tests/test_entrypoint.py services/assistant_orchestrator/src/entrypoint.py services/assistant_orchestrator/tests/test_entrypoint.py` → PASS
- `.venv\Scripts\python.exe -m pytest launcher/tests/test_launcher.py services/ui_gateway/tests/test_transport.py services/policy_agent/tests/test_entrypoint.py services/assistant_orchestrator/tests/test_entrypoint.py -q` → `75 passed`
- `.venv\Scripts\python.exe -m pytest tests/integration/test_p110_end_to_end.py -q` → `49 passed`
- Elevated `RunAs` execution: `BLARAI_LAUNCH_PROFILE=uat2_real .venv\Scripts\python.exe -m launcher` → PASS evidence emitted

Milestone-2 disposition (session-bounded):
- **PASS**
- Elevated in-process handshake and minimal prompt-flow evidence captured.

Roadmap order remains unchanged:
1. Operational Exit Milestone 3 (UAT-2.5 hardening + repeatability)
2. Operational Exit Milestone 4 (UAT-3 non-dev enablement + UI-functional acceptance)

### 1.4c Operational Exit Milestone 3 Snapshot (UAT-2.5 Hardening + Repeatability)

Operational Exit Milestone 3 is **complete** for this session scope with
deterministic repeatability evidence, bounded fail-closed failure-injection
evidence, and normalized artifact inventory:

- Session Git baseline:
   - branch: `feature/p1-uat1-launcher`
   - pre-session HEAD: `21b59ad`
   - post-session HEAD (pre-commit): `21b59ad`

- UAT-2.5 automation runner added and executed:
   - `phase2_gates/scripts/run_uat25_matrices.py`
   - executes 3 `uat2_real` stability runs under deterministic launcher harness
   - executes 2 deterministic failure-injection scenarios with baseline restore
   - emits canonical evidence artifacts for matrix + normalization + summary
- Stability matrix completed with required per-run step booleans:
   - `phase2_gates/evidence/uat25_stability_matrix.json`
   - `run_count=3`, `pass_count=3`, `fail_count=0`, `disposition=PASS`
   - per run: `admin_ok/vm_running/policy_agent_started/assistant_orchestrator_started/gateway_initialized/gateway_handshake_ok/prompt_flow_ok=true`
- Failure-injection matrix completed with deterministic fail-closed fingerprints:
   - `phase2_gates/evidence/uat25_failure_injection_matrix.json`
   - `scenario_count=2`, `all_fail_closed=true`
   - `FI-01` injected condition: PA runtime-mode mismatch (`host→guest`) → observed `PA_CFG_RUNTIME_MODE_MISMATCH`
   - `FI-02` injected condition: AO runtime-mode mismatch (`host→guest`) → observed `AO_CFG_RUNTIME_MODE_MISMATCH`
   - baseline restore verified via SHA-256 parity (`restored=true`)
- Evidence normalization + canonical inventory completed:
   - `phase2_gates/evidence/uat25_evidence_normalization.json`
   - `schema_version=1.0.0` + required normalized field inventory
   - canonical file set recorded for Milestone-3 audit handoff
- Session summary emitted:
   - `phase2_gates/evidence/uat25_summary.md`

Validation evidence (session):
- `python -m py_compile launcher/__main__.py launcher/tests/test_launcher.py services/ui_gateway/src/transport.py services/ui_gateway/tests/test_transport.py services/policy_agent/src/entrypoint.py services/policy_agent/tests/test_entrypoint.py services/assistant_orchestrator/src/entrypoint.py services/assistant_orchestrator/tests/test_entrypoint.py` → PASS
- `.venv\Scripts\python.exe -m pytest launcher/tests/test_launcher.py services/ui_gateway/tests/test_transport.py services/policy_agent/tests/test_entrypoint.py services/assistant_orchestrator/tests/test_entrypoint.py -q` → `75 passed`
- `.venv\Scripts\python.exe -m pytest tests/integration/test_p110_end_to_end.py -q` → `49 passed`
- `.venv\Scripts\python.exe phase2_gates/scripts/run_uat25_matrices.py` → PASS artifacts emitted

Milestone-3 disposition (session-bounded):
- **PASS**
- Multi-run stability, deterministic failure injections, and evidence normalization all satisfied.

Roadmap order after Milestone-3 closure:
1. Operational Exit Milestone 4 (UAT-3 non-dev enablement + UI-functional acceptance)
2. Operational sign-off gate (only after Milestone 4 acceptance evidence)

### 1.4d Operational Exit Milestone 4 Snapshot (UAT-3 Non-Dev Enablement + UI Functional Acceptance)

Operational Exit Milestone 4 completed with **PASS** disposition after rerun with
non-dev participant (Lead Architect / Non-Dev Operator).

Session Git baseline:
- branch: `feature/p1-uat1-launcher`
- prior blocked attempt HEAD: `dc5abbe`
- rerun session HEAD: `715b014`

Session execution (technical gates):
- baseline capture (`git rev-parse --abbrev-ref HEAD`, `git rev-parse HEAD`)
- compile gate:
   - `python -m py_compile launcher/__main__.py services/ui_shell/src/app.py services/ui_gateway/src/transport.py services/policy_agent/src/entrypoint.py services/assistant_orchestrator/src/entrypoint.py` → `COMPILE_GATE_PASS`
- focused tests:
   - `.venv\Scripts\python.exe -m pytest launcher/tests/test_launcher.py services/ui_gateway/tests/test_transport.py services/policy_agent/tests/test_entrypoint.py services/assistant_orchestrator/tests/test_entrypoint.py -q` → `75 passed`
- integration guardrail:
   - `.venv\Scripts\python.exe -m pytest tests/integration/test_p110_end_to_end.py -q` → `49 passed`

UAT-3 participant-dependent phase status:
- non-dev education/comprehension: `PASS`
- non-dev cold-start hands-on execution: `PASS`
- UI functional matrix (UAT3-01..UAT3-10): `PASS`
- explicit non-dev runbook/how-to acceptance: `PASS`

Bug fixes during UAT-3 rerun:
- `6a76094`: Chat template fix (Chinese response remediation)
- `0c1b619`: Option B five-block layered system prompt
- `ca08164`: Phantom session cleanup (UAT2_M2_PROMPT_FLOW)
- `715b014`: Documentation accuracy fixes (4 corrections)

Evidence artifacts (all PASS):
- `phase2_gates/evidence/uat3_operator_run_log.md`
- `phase2_gates/evidence/uat3_ui_matrix.json`
- `phase2_gates/evidence/uat3_failure_paths.json`
- `phase2_gates/evidence/uat3_docs_acceptance.md`
- `phase2_gates/evidence/uat3_summary.md`

Milestone-4 disposition (session-bounded):
- **PASS**

### 1.4e Operational Sign-Off Snapshot (Phase 4 Closure)

Operational Sign-Off Gate executed on sign-off HEAD `8f60259`.

Pre-session baseline:
- branch: `feature/p1-uat1-launcher`
- HEAD: `8f60259d7ea654571a78d44a818a8553d5a537d1`
- working tree: clean

Prerequisite milestone cross-reference:

| Milestone | Description | Commit | Disposition |
|-----------|-------------|--------|-------------|
| M1 | UAT-2 real-runtime activation | `5150503` | PASS |
| M2 | Elevated in-process UAT-2 handshake + prompt-flow | `5150503` | PASS |
| M3 | UAT-2.5 hardening + repeatability | `98decc9` | PASS |
| M4 | UAT-3 non-dev enablement + UI functional acceptance | `5fbe989` | PASS |

Post-M4 hardening: `8f60259` (PGOV false-positive remediation, 765/765 tests).
Non-dev acceptance: Runbook + How-To — ACCEPTED.

Validation replay on sign-off HEAD `8f60259`:
- compile gate:
   - `python -m py_compile launcher/__main__.py services/ui_gateway/src/transport.py services/policy_agent/src/entrypoint.py services/assistant_orchestrator/src/entrypoint.py` → PASS
- focused tests:
   - `.venv\Scripts\python.exe -m pytest launcher/tests/test_launcher.py services/ui_gateway/tests/test_transport.py services/policy_agent/tests/test_entrypoint.py services/assistant_orchestrator/tests/test_entrypoint.py -q` → 72 passed — PASS
- integration guardrail:
   - `.venv\Scripts\python.exe -m pytest tests/integration/test_p110_end_to_end.py -q` → 49 passed — PASS

Sign-off disposition: **OPERATIONAL**

USE-CASE-001 (Policy Agent) and USE-CASE-004 (Assistant Orchestrator) are declared
operational at HEAD `8f60259`. Phase 4 (Operational Gap Closure) is CLOSED.

Roadmap: no further milestones in Phase 4.

### 1.5 Prior Snapshot (Priority 7)

Priority 7 (JWT/KGM key-material wiring) is complete for this session
scope at code and validation level, with deterministic fail-closed behavior:

- Policy Agent startup now enforces non-dev JWT signing/KGM material checks:
    - `services/policy_agent/src/entrypoint.py`
    - validates JWT private key + CA/public verification material path presence,
       file existence, and key readability
    - validates KGM manifest path presence/existence/parseability and required
       `openvino_model.bin` digest format
- Assistant Orchestrator startup now enforces dependent JWT/KGM checks:
    - `services/assistant_orchestrator/src/entrypoint.py`
    - validates `security.jwt_ca_cert_path` in non-dev mode and initializes
       JWT validator material during startup (fail-closed on init failure)
    - validates KGM manifest path presence/existence/parseability and required
       `openvino_model.bin` digest format
- Baseline key/KGM material added for deterministic non-dev resolution:
    - `certs/pa_private.pem`
    - `certs/ca.pem`
    - `models/qwen2.5-1.5b-instruct/openvino-int4-npu/manifest.json`
- Entry-point regression coverage expanded for Priority-7 behavior:
    - `services/policy_agent/tests/test_entrypoint.py`
    - `services/assistant_orchestrator/tests/test_entrypoint.py`

Validation evidence (session):
- `python -m py_compile services/policy_agent/src/entrypoint.py services/assistant_orchestrator/src/entrypoint.py services/policy_agent/tests/test_entrypoint.py services/assistant_orchestrator/tests/test_entrypoint.py`
- `.venv\Scripts\python.exe -m pytest services/policy_agent/tests/test_entrypoint.py services/assistant_orchestrator/tests/test_entrypoint.py -q` → `14 passed`
- `.venv\Scripts\python.exe -m pytest tests/integration/test_p110_end_to_end.py -q` → `49 passed`

### 1.6 Prior Snapshot (Priority 6)

Priority 6 (config loader boot integration) is complete for this session
scope at code and validation level, with deterministic fail-closed behavior:

- Shared authoritative runtime config resolution added:
   - `shared/runtime_config.py`
   - deterministic precedence: explicit mode → `BLARAI_RUNTIME_MODE` → `host`
   - deterministic file selection: `default.toml` (host) vs `guest_runtime.toml` (guest)
- Launcher boot path now uses resolved deployment mode as authoritative source:
   - `launcher/__main__.py` resolves mode once and starts both services via
     `from_runtime_mode(...)`
   - launcher fail-closed on mode/config resolution mismatch
- Service boot paths now enforce strict config validation + deterministic fingerprints:
   - `services/policy_agent/src/entrypoint.py`
   - `services/assistant_orchestrator/src/entrypoint.py`
   - required sections/keys, type/range checks, ADR-010 device checks,
     deployment-mode compatibility checks
   - deterministic `last_failure` fingerprints surfaced in launcher logs
- Guest deployment/startup config wiring unified with service validators:
   - `launcher/guest_deploy.py` guest config preflight validation
   - `scripts/guest/guest_startup_smoke.py` now boots both services through
     authoritative guest-mode resolution and emits deterministic failure codes
- Runtime mode metadata made explicit in service configs:
   - added `[runtime] deployment_mode = "host"|"guest"` to both host/guest
     config files for Policy Agent and Orchestrator
   - added explicit `dev_mode = false` to orchestrator host config

Validation evidence (session):
- `python -m py_compile shared/runtime_config.py launcher/__main__.py launcher/guest_deploy.py scripts/guest/guest_startup_smoke.py services/policy_agent/src/entrypoint.py services/assistant_orchestrator/src/entrypoint.py launcher/tests/test_launcher.py launcher/tests/test_guest_deploy.py services/policy_agent/tests/test_entrypoint.py services/assistant_orchestrator/tests/test_entrypoint.py`
- `.venv\Scripts\python.exe -m pytest launcher/tests/test_launcher.py launcher/tests/test_guest_deploy.py services/policy_agent/tests/test_entrypoint.py services/assistant_orchestrator/tests/test_entrypoint.py services/policy_agent/tests/test_config_loader.py -q` → `39 passed`
- `.venv\Scripts\python.exe -m pytest tests/integration/test_p110_end_to_end.py -q` → `49 passed`

### 1.7 Prior Snapshot (Priority 5)

Priority 5 (VM deployment execution for guest-side runtime) is complete for this
session scope at code and script level, with deterministic fail-closed evidence:

- Host deployment orchestrator implemented:
   - `launcher/guest_deploy.py` (preflight, topology checks, runtime bundle,
      Copy-VMFile deployment, evidence output)
   - `scripts/deploy_guest_runtime.ps1` wrapper for deterministic execution
- Hyper-V deployment plumbing added:
   - `launcher/vm_manager.py` Guest Service Interface check
   - `launcher/vm_manager.py` file transfer helper with bounded retries
- Guest startup path wiring added:
   - `scripts/guest/bootstrap_runtime.sh`
   - `scripts/guest/guest_startup_smoke.py`
   - guest runtime configs for both services under `services/*/config/guest_runtime.toml`
- Fail-Closed evidence captured for host→guest deployment execution:
   - `phase2_gates/evidence/priority5_guest_deploy.json`
   - fingerprint code: `P5_GUEST_CHANNEL_NOT_READY`
   - observed Hyper-V error: `0x800710DF` (device not ready for guest copy channel)

Validation evidence (session):
- `python -m py_compile launcher/guest_deploy.py launcher/vm_manager.py launcher/tests/test_guest_deploy.py launcher/tests/test_vm_manager.py scripts/guest/guest_startup_smoke.py`
- `.venv\Scripts\python.exe -m pytest launcher/tests/test_guest_deploy.py launcher/tests/test_vm_manager.py launcher/tests/test_launcher.py -q` → `36 passed`
- `.venv\Scripts\python.exe -m pytest tests/integration/test_p110_end_to_end.py -q` → `49 passed`
- `.\scripts\deploy_guest_runtime.ps1` executed (fail-closed evidence recorded)

### 1.1 Target Hardware

| Parameter | Value |
|-----------|-------|
| Device | ASUS ExpertBook P5 (P5405CSA) |
| SoC | Intel Core Ultra 7 258V (Lunar Lake) |
| RAM | 32GB LPDDR5X-8533 (soldered) |
| Effective Ceiling | **31.323 GB** (32GB − 693MB firmware, see ADR-005) |
| iGPU | Intel Arc 140V (Xe2) — 16GB shared LPDDR5X |
| NPU | Intel AI Boost — 48 TOPS |
| OS | Windows 11 Pro Build 26200 |
| Trust Posture | Software fallback: Hyper-V + vsock + mTLS (no TDX, see ADR-007) |

### 1.2 Locked Models

| Role | Model | Format | Device | Size (Measured) | Path |
|------|-------|--------|--------|-----------------|------|
| Semantic Router (M1) | BAAI/bge-small-en-v1.5 | ONNX FP16 | CPU | 127.8 MB | `models/bge-small-en-v1.5/onnx-fp16/` |
| Semantic Router (M1 NPU) | BAAI/bge-small-en-v1.5 | OpenVINO INT8 | NPU | 33.5 MB | `models/bge-small-en-v1.5/openvino-int8/` |
| Policy Agent (M2) | Qwen3-14B + draft model | OpenVINO INT4 | GPU (Arc 140V) | ~9.1 GB (target) + draft TBD | `models/qwen3-14b/openvino-int4-gpu/` |
| Orchestrator (M3) | Qwen3-14B + draft model | OpenVINO INT4 | GPU (Arc 140V) | ~9.1 GB (target) + draft TBD | `models/qwen3-14b/openvino-int4-gpu/` |
| Draft Model (speculative decoding) | EVALUATING — see ADR-012 §2.3 | OpenVINO INT4/INT8 | GPU (Arc 140V) | ~300–400 MB | TBD (candidates below) |
| USE-CASE-005 Code Agent | Qwen3-14B + draft model | OpenVINO INT4 | GPU (Arc 140V) | ~9.1 GB (shared) | `models/qwen3-14b/openvino-int4-gpu/` |
| Substrate Bi-encoder (M4) | BAAI/bge-small-en-v1.5 | OpenVINO INT8 | TBD (future) | 33.5 MB | `models/bge-small-en-v1.5/openvino-int8/` |

**Model selection confirmed (2026-02-28, ADR-012):** Qwen3-14B (INT4, GPU) is the locked target
model for PA, AO, and USE-CASE-005. Speculative decoding with a draft model is mandatory.
Configuration optimization is in progress — draft model selection, context window cap,
`num_assistant_tokens`, runtime properties, and pipeline construction
pattern are all under active empirical evaluation (see ADR-012 §2.2).

**Thinking mode strategy locked (2026-02-28, ADR-012 §2.4):**
- **Policy Agent:** `/no_think` system prompt + `stop_token_ids=[151645, 151668]` (defense-in-depth)
- **Assistant Orchestrator:** Thinking allowed (default) + `stop_token_ids=[151645]`
- **USE-CASE-005 Code Agent:** Context-dependent `/think` or `/no_think` + `stop_token_ids=[151645]`

**KV cache precision locked (2026-02-28, ADR-012 §2.2):** FP16 (default). INT8 ruled out empirically.

Draft model candidates under evaluation:
- **Qwen3-0.6B** (INT4, 28 layers, ~367 MB) — operational, validated in P5-005a/005b
- **Qwen3-pruned-6L-from-0.6B** (INT8_ASYM, 22 layers, ~300 MB est.) — acquisition in progress (P5-005c)
- **Qwen3-1.7B** (INT4, 28 layers, ~1 GB est.) — not yet tested

**Previous model history:**
- 2026-02-27 (ADR-011): Model selection reopened, NPU retired.
- 2026-02-24 (ADR-010): Qwen2.5-1.5B-Instruct (INT4-MIXED). Demoted to legacy reference.

Legacy model artifacts retained on disk: `models/qwen2.5-1.5b-instruct/openvino-int4-npu/`
(evidence: `phase2_gates/evidence/model_acquisition.json`, commit `dc43a90`).

### 1.3 Development Environment

| Component | Value |
|-----------|-------|
| Python | 3.11.9 (venv at `.venv/`) |
| Key Packages | optimum 2.1.0, optimum-intel 1.27.0, openvino 2026.0.0, openvino_genai 2026.0.0.0, nncf 2.19.0, torch 2.10.0+cpu, transformers 4.57.6, sentence-transformers 5.2.3, onnxruntime 1.24.2 |
| Known Bug | `python -m optimum.exporters.openvino` CLI silently fails (optimum-intel 1.27 + optimum 2.1). Script uses programmatic API instead. |

---

## 2. Phase 2 Hardware Validation Gates (ALL CLOSED)

All four empirical hardware gates completed before any implementation code was written.

| Gate | ADR | Disposition | Commit | Key Finding |
|------|-----|-------------|--------|-------------|
| VALIDATE_DVMT_BUDGET | ADR-005 | PASS WITH CORRECTION | `a732399` | DVMT = 693MB, effective ceiling = 31.323 GB (not 31.5 GB) |
| VALIDATE_MEMORY_CEILING | ADR-006 | PASS WITH WARNING | `b6fa57d` | 4.5% headroom under worst-case dev-time load; viable for production |
| VALIDATE_IGPU_TRUST_BOUNDARY | ADR-007 | PASS WITH CORRECTION | `c959864` | No TDX/TDISP on client Lunar Lake; software fallback (Hyper-V + vsock + mTLS) viable |
| VALIDATE_NPU_SCHEDULING | ADR-008 | PASS | `66106cc` | True parallel dual-model NPU inference, KV-cache persists, preemption P99 = 0.814ms |

Gate closure commit: `66106cc` — "close(phase2): all 4 hardware validation gates PASSED"

---

## 3. Implementation Sequence — P1.0 through P1.14

The following is a deterministic, dependency-ordered scaffold-then-implement sequence for
the Priority 1 Core Loop (USE-CASE-001 Policy Agent + USE-CASE-004 Assistant Orchestrator),
derived from the locked hardware baseline.

### 3.1 Step Table

| Step | Task | Dependency | Deliverable | Status |
|------|------|------------|-------------|--------|
| **P1.0** | Scaffold Priority 1 microservice directory structure | None | `services/policy_agent/`, `services/assistant_orchestrator/`, `services/semantic_router/` with `__init__.py`, `Dockerfile`, `pyproject.toml` stubs | **DONE** |
| **P1.1** | Implement Canonical Action Representation (CAR) schema | None | `services/policy_agent/src/car.py` — Pydantic models for action representation, serialization, deterministic hash | **DONE** |
| **P1.2** | Implement deterministic rule engine (regex constraint + semantic distance) | P1.1 | `services/policy_agent/src/rule_engine.py` — first gate of hybrid adjudication + TOML loading | **DONE** |
| **P1.3** | Implement GPU LLMPipeline inference harness for Policy Agent (ADR-010) | P1.0 | `services/policy_agent/src/gpu_inference.py` — model loading, Priority 0 semantics, deterministic LLMPipeline classification on GPU | **DONE** |
| **P1.4** | Implement hybrid adjudication pipeline (deterministic + probabilistic) | P1.2 + P1.3 | `services/policy_agent/src/adjudicator.py` — CAR → rule engine → GPU classifier → decision; event-triggered weight integrity; 4-stage pipeline; latency tracking | **DONE** |
| **P1.5** | Implement Agentic JWT minting and validation | P1.4 | `services/policy_agent/src/jwt_minter.py` — Decision Artifact generation, ES256 signature, 5-stage gate, epoch revocation | **DONE** |
| **P1.6** | Implement vsock IPC listener with mTLS | P1.5 | `services/policy_agent/src/ipc.py` — AF_HYPERV socket, ephemeral certificate generation, mTLS handshake, protocol layer | **DONE** |
| **P1.7** | Implement Semantic Router (CPU fast-path) | P1.0 | `services/semantic_router/src/router.py` + `intents.py` — bge-small-en-v1.5 ONNX inference, dual-gate classification (threshold + margin), sub-80ms latency | **DONE** |
| **P1.8** | Implement Orchestrator NPU inference + context management | P1.0 + P1.3 | `services/assistant_orchestrator/src/npu_inference.py` — Priority 1 scheduling, LLMPipeline generation path, KV/session compatibility hooks | **DONE** |
| **P1.9** | Implement PGOV (Post-Generation Output Validator) | P1.8 | `services/assistant_orchestrator/src/pgov.py` — deterministic tool-call allowlist, leakage detection via cosine similarity, delimiter echo detection | **DONE** |
| **P1.10** | Integration test: PA ↔ Orchestrator ↔ Router over vsock | P1.6 + P1.7 + P1.8 | End-to-end latency validation against empirical NPU parameters | **DONE** |
| **P1.11** | UI Transport Gateway (vsock ↔ IPC adapter) | P1.6 | `services/ui_gateway/` — live vsock IPC relay with MessageFramer protocol, PA handshake, streaming tokens, PGOV cache, tool-call buffering (commit `d6b0eee`) | **DONE** (46 tests) |
| **P1.12** | TUI Shell (Textual framework) | P1.11 | `services/ui_shell/` — wired to live TransportGateway + SessionStore: correct API signatures, asyncio.to_thread() wrapping, session auto-create, turn persistence, tool-call flush (commit `4174df4`) | **DONE** (35 tests) |
| **P1.13** | Boot-Phase-3 gating + operational surface validation | P1.11 + P1.12 | Boot-Phase-3 handshake enforcement, Fail-Closed startup, retry logic with exponential backoff | **DONE** (commit `87379e8`, 668/668 tests) |
| **P1.14** | End-to-end UX validation tests | P1.12 + P1.13 | Integration tests: prompt → Router → Orchestrator → PGOV → TUI display, session persistence, PGOV denial display | **DONE** (commit `01dfad8`, 699/699 tests) |
| **P1.15** | UAT-1 Launcher + Mock Backend + Packaging | P1.14 | Windows executable via PyInstaller, Start Menu shortcut, MockPAServer, VM lifecycle manager, UAT-1 acceptance plan | **DONE** (747/747 tests) |

### 3.2 Gate Dependencies

- **Step P1.3** follows ADR-010 (Policy Agent classification on GPU via LLMPipeline).
- **Step P1.8** remains NPU generation and consumes ADR-008/ADR-010 NPU behavior (parallel mode, persistent KV-cache, sole NPU consumer).
- **Step P1.6** consumes the trust boundary posture locked in ADR-007 (vsock + mTLS).
- **Step P1.7** consumes the model artifacts acquired in the Model Acquisition gate (commit `dc43a90`).

---

## 4. Completed Step Details

### 4.1 P1.0 — Scaffold (commit `afa42d9`)

Created the three-service directory structure under `services/`:
- `services/policy_agent/` — `src/`, `tests/`, `config/`, `Dockerfile`, `pyproject.toml`
- `services/assistant_orchestrator/` — same structure
- `services/semantic_router/` — same structure

Also scaffolded `services/code_agent/`, `services/cleaner/`, `services/substrate/` as placeholder directories for future use cases.

Shared layer: `shared/constants.py` — all empirical hardware constants from Phase 2 gates.

### 4.2 P1.1 — CAR Schema (commit `401ce0e`)

**File:** `services/policy_agent/src/car.py`

Pydantic models implementing the Canonical Action Representation:
- `ActionType` enum: `TOOL_CALL`, `DATA_ACCESS`, `EGRESS`, `IPC`
- `CAR` model with: `source_cid`, `target_cid`, `action_type`, `operation`, `parameters`, `payload_hash`
- Deterministic SHA-256 hash generation for JWT binding
- Full serialization/deserialization round-trip
- Integration tests validate full pipeline

### 4.3 P1.2 — Rule Engine (commit `12621c5`)

**File:** `services/policy_agent/src/rule_engine.py`

First gate of the hybrid adjudication model:
- TOML-based rule configuration loading
- `RATE` rules: rate limiting per source CID
- `RESOURCE` rules: resource access allowlists
- Regex constraint matching against CAR fields
- Returns `ALLOW`, `DENY`, or `ESCALATE` (passes to NPU probabilistic gate)

### 4.4 P1.3 — GPU LLMPipeline Inference (commits `287230d`, `fdfbf92`, `9cfb063`)

**File:** `services/policy_agent/src/gpu_inference.py`

OpenVINO GenAI LLMPipeline inference harness for Policy Agent:
- Model loading via `openvino_genai.LLMPipeline(..., "GPU")`
- Priority 0 policy semantics on GPU path (ADR-010)
- Weight integrity verification (SHA-256 against Known-Good Manifest)
- Read-only mmap access
- Fail-Closed: all inference errors return `DENY`

### 4.5 P1.4 — Hybrid Adjudicator (commit `58b178a`)

**File:** `services/policy_agent/src/adjudicator.py`

4-stage adjudication pipeline:
1. CAR validation (schema + hash)
2. Deterministic rule engine check (P1.2)
3. Event-triggered weight integrity verification
4. GPU probabilistic classification (P1.3)

Latency tracking per stage. Decision output feeds JWT minting (P1.5).

### 4.6 P1.5 — Agentic JWT (commit `fa13d66`)

**File:** `services/policy_agent/src/jwt_minter.py`

Full JWT lifecycle per USE-CASE-001 specification:
- ES256 signing (ECDSA P-256)
- 5-second TTL hard expiry
- 128-bit cryptographic nonce (non-replayable)
- CAR hash binding in JWT payload
- Epoch-based revocation (monotonic uint64 counter)
- 5-stage validation gate: signature → expiry → epoch → nonce → CAR hash

### 4.7 P1.6 — vsock IPC (commit `d2ef3fa`)

**File:** `services/policy_agent/src/ipc.py`

AF_HYPERV socket transport layer:
- Protocol: length-prefixed JSON frames
- mTLS handshake with ephemeral certificates
- Connection lifecycle management
- Fail-Closed: connection failures reject all requests

Test count at completion: 372/372 passing.

### 4.8 P1.7 — Semantic Router (commit `352fb21`)

**Files:**
- `services/semantic_router/src/router.py` — Full ONNX Runtime inference
- `services/semantic_router/src/intents.py` — IntentRoute dataclass + 4 default routes
- `services/semantic_router/src/constants.py` — Calibrated thresholds
- `services/semantic_router/tests/test_router.py` — 31 tests

Implementation details:
- **Model:** BAAI/bge-small-en-v1.5 via ONNX Runtime (CPU)
- **Embedding:** AutoTokenizer → int64 cast → ONNX inference → mean pooling → L2 normalization → 384-dim vectors
- **Classification:** Pre-computed centroid embeddings per IntentRoute, cosine similarity scoring
- **Dual-gate:** Absolute threshold (0.50) + margin gate (0.04). Margin = best − second_best; low margin = ambiguous → OUT_OF_SCOPE
- **Default routes:** CONVERSATIONAL, code_agent, search, cleaner
- **Fail-Closed:** All errors/unloaded states → `OUT_OF_SCOPE`
- **Latency:** Sub-80ms on Lunar Lake P-cores (budget: 80ms per `shared/constants.py`)
- **Calibration evidence:** Per-route cosine similarity matrix — valid queries: margins 0.052–0.172; gibberish: margin 0.032

Test count at completion: 398/398 passing.

### 4.9 P1.8 — Orchestrator NPU Inference + Context Management

**Files:**
- `services/assistant_orchestrator/src/npu_inference.py` — Full OpenVINO autoregressive generation engine (~580 lines)
- `services/assistant_orchestrator/src/context_manager.py` — Enhanced with 5 new methods (~80 lines added)
- `services/assistant_orchestrator/src/constants.py` — 8 new generation/preemption constants
- `services/assistant_orchestrator/config/default.toml` — Generation + preemption config sections (v0.2.0)
- `services/assistant_orchestrator/tests/test_npu_inference.py` — 24 new tests (mirrors PA test pattern)
- `services/assistant_orchestrator/tests/test_context_manager.py` — 18 new tests for enhanced methods

Implementation details:
- **Model:** Qwen2.5-1.5B-Instruct OpenVINO INT4-MIXED via `openvino_genai.LLMPipeline` (shared weights with PA)
- **NPU Scheduling:** Priority 1 for Orchestrator generation; ADR-010 moved PA to GPU, so Orchestrator is the sole NPU consumer in steady state.
- **Generation Runtime (Priority 4):** LLMPipeline prompt-based generation path with preserved `GenerationResult` contract and circuit-breaker token capping.
- **Fail-Closed Runtime:** Model-load failures, pipeline initialization failures, tokenization failures, and generation exceptions all return deterministic fail-closed `GenerationResult(error=...)`.
- **Compatibility Hooks:** Existing service-facing methods retained (`generate`, `generate_text`, `warm_kv_cache`, `warm_kv_cache_text`, `invalidate_kv`, `unload`) to keep Priority 2/3 entrypoint and IPC flow unchanged.
- **Preemption Metadata:** Timing anomaly structures retained for interface compatibility and diagnostics.
- **KV/session tracking:** Session warm/cold tracking remains available for orchestrator state management, with defensive pipeline-state reset hooks in `invalidate_kv()`.
- **Context Manager Enhancements:**
  - `trim_to_budget()` — FIFO eviction of oldest turns to stay within `max_context_tokens`
  - `destroy_session()` — full teardown including KV-cache invalidation
  - `clear_grounded_context()` — flush RAG chunks for fresh retrieval
  - `get_session_stats()` — monitoring dict (turn_count, total_tokens, grounded_chunks, kv_warm, budget_remaining)
  - `active_sessions` property — list of live session IDs
- **Weight Integrity:** SHA-256 verification via `shared.models.weight_integrity.verify_weight_integrity()` at load time; blocks model loading on tampered weights
- **Fail-Closed:** All errors return empty `GenerationResult(error=...)`. Missing OpenVINO/numpy triggers graceful degradation with error text.
- **Config:** `default.toml` v0.2.0 — `[generation]` (max_new_tokens, temperature, top_k, top_p, repetition_penalty), `[preemption]` (timing_multiplier, min_detection_samples), `[context]` (max_context_tokens)

Test count at completion: 440/440 passing.

---

### 4.10 P1.9 — PGOV (Post-Generation Output Validator)

**Files:**
- `services/assistant_orchestrator/src/pgov.py` — Full 6-stage output validation pipeline (~430 lines, complete rewrite from ~134-line partial stub)
- `services/assistant_orchestrator/src/constants.py` — 4 new PGOV feature-toggle constants
- `services/assistant_orchestrator/config/default.toml` — v0.3.0, expanded `[pgov]` section
- `services/assistant_orchestrator/tests/test_pgov.py` — 44 tests (complete rewrite from 5 tests)

Implementation details:
- **6-Stage Pipeline:** Token Budget → PII → Delimiter Echo → Tool Allowlist → Leakage → Approval Gate
- **Expanded PII:** 9 named patterns — SSN, CREDIT_CARD, EMAIL, PHONE_US, IPV4, AWS_KEY, HEX_SECRET, PASSPORT_US, BEARER_TOKEN. Returns labels (not raw patterns).
- **Delimiter Echo Detection:** Scans for all 4 Context Spotlighting delimiters (`CONTEXT_BEGIN`, `CONTEXT_END`, `SYSTEM_BEGIN`, `SYSTEM_END`) — if any appear in generated output, the response is suppressed.
- **Tool-Call Allowlist:** Deterministic `frozenset` of 10 authorized tool IDs. 4 regex patterns detect tool references (XML tags, bracket notation, JSON double/single quotes). Unauthorized tool references trigger rejection.
- **Leakage Detection (LeakageDetector class):**
  - Loads bge-small-en-v1.5 ONNX on CPU (CPUExecutionProvider, 2 intra-op threads) — avoids NPU contention
  - Mirrors SemanticRouter `_embed_raw` pattern: tokenize → int64 cast → ONNX → mean pool → L2 normalize
  - Embeds generated text + retrieved chunks, computes dot-product cosine similarity
  - Returns max similarity score. Threshold default: 0.85 (`COSINE_SIMILARITY_THRESHOLD`)
  - **Fail-Closed:** Returns 1.0 (max leakage) if model not loaded or on any error
  - Singleton pattern with `set_leakage_detector()` for test injection
- **Feature Toggles (constants.py):** `PGOV_PII_ENABLED`, `PGOV_DELIMITER_ECHO_ENABLED`, `PGOV_TOOL_ALLOWLIST_ENABLED`, `PGOV_LEAKAGE_ENABLED` — all default True
- **Config (default.toml v0.3.0):** `delimiter_echo_enabled`, `tool_allowlist_enabled`, `leakage_detection_enabled`, `embedding_model_path`
- **Fail-Closed:** `validate_output()` wraps entire pipeline in try/except — any exception returns `approved=False` with FALLBACK_MESSAGE
- **PGOVResult dataclass:** Extended with `delimiter_echo` and `tool_call_violation` boolean fields

Test count at completion: 484/484 passing.

---

### 4.11 P1.10 — Integration Test: PA ↔ Orchestrator ↔ Router over vsock

**Files:**
- `tests/integration/__init__.py` — Package marker
- `tests/integration/test_p110_end_to_end.py` — 49 tests across 9 test groups

Capstone integration test exercising the full Priority 1 Core Loop end-to-end. All component interfaces built in P1.0–P1.9 are validated together. IPC uses `dev_mode=True` TCP loopback with OS-assigned ephemeral ports (port 0). All NPU/ONNX models are mocked — tests validate data flow and Fail-Closed semantics, not inference latency.

**Test Groups (9 classes, 49 tests):**

| Group | Class | Tests | Coverage |
|-------|-------|-------|----------|
| A | `TestEndToEndPipeline` | 7 | Full pipeline: classify → generate → PGOV → CAR → PA → JWT → validate. Conversational, skill_dispatch, out_of_scope paths. Data integrity (car_hash chain, request_id chain). PGOV rejection prevents delivery. |
| B | `TestVsockIPCRoundTrip` | 5 | Real TCP loopback socket I/O: single ALLOW, single DENY, multiple sequential requests, heartbeat, car_hash propagation. Threading: background accept + main thread send. |
| C | `TestFailClosedDisconnectedPA` | 4 | Connection refused → DENY, listener stopped mid-session, default_deny_handler, handler exception → Fail-Closed DENY. |
| D | `TestPreemptionSignalPropagation` | 4 | Structural preemption flag, preempted output PGOV validation, PII in preempted output, priority ordering (PA=0 < Orch=1). |
| E | `TestPGOVPipelineIntegration` | 7 | Clean output, token budget, delimiter echo, tool call allowlist (pass/reject), multiple violations, sanitized vs original text. |
| F | `TestJWTLifecycleAcrossBoundary` | 8 | Mint→validate, replay detection, CAR hash mismatch, wrong public key, epoch revocation, DENY no token, full JWT over IPC lifecycle. |
| G | `TestLatencyBudgetStructure` | 6 | ClassificationResult latency, GenerationResult timing, NPU latency, AdjudicationContext breakdown, constants defined, AdjudicationLatency dataclass. |
| H | `TestCrossServiceDataFlow` | 5 | CAR JSON round-trip, AdjudicationResponse round-trip, MessageFramer symmetry, feature extraction determinism, hash stable across services. |
| I | `TestHybridAdjudicatorIntegration` | 4 | Stub NPU pipeline DENY, rule DENY short-circuits NPU, adjudication_count increments, full audit trail. |

**Section 5.3 Requirements Coverage:**
1. ✅ End-to-end pipeline: Query → Router → Orchestrator → PGOV → PA → JWT → validation (Groups A, B, E, F)
2. ✅ IPC over vsock (dev_mode TCP loopback): Groups B, C, F
3. ✅ Latency budget structural validation: Group G
4. ✅ Fail-Closed behavior (disconnected PA → denied): Group C
5. ✅ Preemption signal propagation: Group D

Test count at completion: 533/533 passing (484 existing + 49 new).

### 4.12 P1.11 — UI Transport Gateway (vsock ↔ IPC adapter)

**Target directory:** `services/ui_gateway/`

**Files:**
- `services/ui_gateway/__init__.py` — Package marker
- `services/ui_gateway/pyproject.toml` — Package metadata + Textual dependency
- `services/ui_gateway/src/__init__.py`
- `services/ui_gateway/src/transport.py` — Transport Gateway core
- `services/ui_gateway/src/session_store.py` — SQLite session persistence
- `services/ui_gateway/src/constants.py` — Gateway-specific constants
- `services/ui_gateway/config/` — Configuration directory
- `services/ui_gateway/tests/__init__.py`
- `services/ui_gateway/tests/test_transport.py`
- `services/ui_gateway/tests/test_session_store.py`

**Requirements:**

1. **Interface-agnostic Python API** — The Transport Gateway exposes:
   - `send_prompt(session_id: str, prompt: str) -> str` — Submits prompt to Orchestrator via vsock + mTLS
   - `stream_tokens(session_id: str) -> AsyncIterator[StreamToken]` — Yields `StreamToken` objects as received from Orchestrator
   - `get_sessions() -> list[SessionSummary]` — Lists sessions from SQLite
   - `get_session_turns(session_id: str) -> list[Turn]` — Retrieves conversation history
   - `delete_session(session_id: str) -> bool` — CASCADE deletes session + turns
   - `get_pgov_result(request_id: str) -> PGOVResult` — Retrieves PGOV validation outcome
   - `check_pa_status() -> bool` — PA vsock handshake health check
2. **StreamToken dataclass:**
   - `token: str` — generated token text
   - `token_index: int` — position (0-based)
   - `is_final: bool` — last token flag
   - `is_tool_call: bool` — if True, buffered until PGOV clearance
   - `session_id: str` — session identifier
3. **Tool-call buffering:** Tokens with `is_tool_call=True` are accumulated in the gateway. They are only released to the UI after PGOV validation passes. If PGOV denies, the entire tool-call block is replaced with a denial message + reason codes.
4. **Session persistence — SQLite:**
   - Database: `%LOCALAPPDATA%\BlarAI\sessions.db` (configurable via constant)
   - Sessions table: `id` (UUID), `title` (auto from first prompt, max 80 chars), `created_at`, `updated_at`, `is_active` (bool)
   - Turns table: `id` (UUID), `session_id` (FK), `role` (user/assistant), `content` (text), `pgov_status` (approved/denied/error), `pgov_reasons` (JSON array), `timestamp`
   - CASCADE delete on session removal
5. **vsock + mTLS relay:** Constructs `AdjudicationRequest` (reusing `shared/ipc/protocol.py` types) and relays via vsock with mTLS certificates loaded from disk. Uses `dev_mode=True` TCP loopback for testing.
6. **Fail-Closed:** All connection failures, deserialization errors, and unexpected exceptions return deny/error results. No partial data is exposed to the UI.
7. **Zero external network calls:** No `socket`, `requests`, `urllib`, `httpx` — only vsock (AF_HYPERV) or localhost TCP in dev_mode.

**Dependencies:** P1.6 (vsock IPC, protocol.py, message framing), shared/ipc/protocol.py

---

### 4.13 P1.12 — TUI Shell (Textual Framework) — commit `4174df4`

**Target directory:** `services/ui_shell/`

**Files:**
- `services/ui_shell/src/app.py` — `BlarAIApp(App[None])` — main Textual TUI, wired to live gateway + store
- `services/ui_shell/src/streaming.py` — `StreamingDisplay(RichLog)` — incremental token rendering
- `services/ui_shell/src/session_panel.py` — `SessionPanel(Vertical)` — sidebar with `asyncio.to_thread()` store wrapping
- `services/ui_shell/src/pgov_display.py` — `PGOVPanel(Static)` — PGOV denial rendering
- `services/ui_shell/src/constants.py` — TUI constants (layout, keys, PGOV labels, boot gating)
- `services/ui_shell/tests/test_app.py` — 14 tests
- `services/ui_shell/tests/test_streaming.py` — 8 tests
- `services/ui_shell/tests/test_pgov_display.py` — 13 tests

Implementation details:
- **`BlarAIApp.__init__`**: Accepts `gateway: TransportGateway | None` and `session_store: SessionStore | None` as injected dependencies. Both default to None (Fail-Closed).
- **`_poll_boot_status()`**: Calls `check_pa_status() -> bool` directly (not `StartupState` enum). On True: enables prompt `Input`, focuses it, logs OPERATIONAL. On False: writes `BOOT_FAILED_TEXT`, stays disabled (Fail-Closed).
- **`_ensure_session()`**: Returns active session ID from `SessionPanel`. If none, calls `asyncio.to_thread(store.create_session)` + `set_active_session()` and refreshes the panel list.
- **`action_submit_prompt()`** — full live wiring:
  - Calls `send_prompt(session_id, prompt) -> request_id`
  - Iterates `stream_tokens(session_id)` async generator, appending each `StreamToken` via `display.append_token()`
  - Calls `get_pgov_result(request_id)` (sync — wrapped in `asyncio.to_thread()`)
  - On PGOV denial: shows `PGOVPanel`, flushes tool-call buffer with `approved=False`, persists denied turn
  - On PGOV approval: flushes buffered tool-call tokens to display, persists approved turn
  - All exceptions caught, written as Fail-Closed error lines — input always re-enabled in finally
- **`SessionPanel`** — all `SessionStore` methods (sync SQLite) wrapped with `asyncio.to_thread()`:
  - `create_session()` returns `str` (UUID) — not an object (scaffold bug fixed)
  - `list_sessions()`, `set_active_session()`, `delete_session()` all threaded
- **`StreamingDisplay(RichLog)`**: `append_token()` handles text vs. tool-call tokens, newline-boundary flushing, `is_final=True` flush. `start_new_response()` prepends separator and resets state.
- **`PGOVPanel(Static)`**: `display_denial()` renders reason codes using `PGOV_REASON_LABELS`, truncates sanitized text at 200 chars. `hide()` clears result + sets `display: none`.
- **API mismatches fixed from scaffold:** `check_pa_status()` bool not `StartupState`, `send_prompt(session_id, prompt)` not `send_prompt(text)`, `stream_tokens(session_id)` not `stream_tokens()`, `get_pgov_result(request_id)` not `get_pgov_result()`, SessionStore sync not async.

Test count at completion: 660/660 passing (652 existing + 14 new app tests, 8 streaming, 13 pgov — scaffold expanded during wiring).

---

### 4.14 P1.13 — Boot-Phase-3 Gating + Operational Surface Validation

**Files:**
- `services/ui_gateway/src/transport.py` — PA handshake with retry logic
- `services/ui_shell/src/app.py` — Startup state machine

**Delivered (commit `87379e8`):**

1. **Boot logging:** Dedicated `blarai.boot` logger with `FileHandler` writes startup transitions to `%LOCALAPPDATA%\BlarAI\boot.log` (directory auto-created).
2. **State-aware startup surface:** `_poll_boot_status()` now shows `INITIALIZING`, `HANDSHAKING` progress lines, `OPERATIONAL`, and `FAILED` transitions with Fail-Closed behavior.
3. **Ctrl+R boot retry:** `action_retry_boot()` retries handshake when non-operational (`gateway.reset()` + repoll) and preserves prior retry-submit behavior when operational.
4. **Invariant retained:** Prompt dispatch remains blocked until operational (`action_submit_prompt` guard unchanged).
5. **Validation:** Added unit coverage for boot logging, retry behavior, and gateway state transitions (`services/ui_shell/tests/test_app.py`, `services/ui_gateway/tests/test_transport.py`).

**Dependencies:** P1.11 + P1.12

---

### 4.15 P1.14 — End-to-End UX Validation Tests

**Files:**
- `tests/integration/test_p114_ui_end_to_end.py`

**Delivered (commit `01dfad8`):**

1. **Integration suite added:** `tests/integration/test_p114_ui_end_to_end.py` with 31 tests across Groups A–E.
2. **Coverage includes:** Transport API, session CRUD, token/tool-call buffering, boot-phase gating transitions, and PGOV denial rendering.
3. **Fail-Closed hardening:** Enforced `STREAM_TOKEN_BUFFER_LIMIT` in gateway stream loop and retained default-deny behavior.
4. **Session API compatibility:** Added `SessionStore.get_turns()` alias for integration readability.
5. **Acceptance met:** Full suite passes at 699/699.

**Dependencies:** P1.12 + P1.13

---

### 4.16 Release Notes — P1.13 + P1.14

- `87379e8` — P1.13 complete: Boot-Phase-3 gating enforcement, dedicated boot transition logging, and operational/non-operational Ctrl+R retry behavior.
- `01dfad8` — P1.14 complete: Added 31 end-to-end UX validation tests and stream circuit-breaker enforcement (`STREAM_TOKEN_BUFFER_LIMIT`) with full regression pass (699/699).

### 4.17 P1.15 — UAT-1 Launcher, Mock Backend, and Packaging

**Milestone:** Staged Acceptance — UAT-1 (Mock Backend)
**Test Count:** 747/747 (699 existing + 48 new)

**New Components:**

| Module | Path | Tests |
|--------|------|-------|
| Mock PA Server | `services/mock_backend/server.py` | 23 |
| VM Lifecycle Manager | `launcher/vm_manager.py` | 20 |
| Launcher Entry Point | `launcher/__main__.py` | 5 |

**Architecture:** MockPAServer runs as a daemon thread on `localhost:50051`, speaking the 4-byte length-prefixed JSON wire protocol. TransportGateway connects in `dev_mode=True` (TCP instead of vsock). BlarAI-Orchestrator VM is started/stopped for lifecycle validation but remains idle. The TUI, session persistence, PGOV display, and all keyboard shortcuts are identical to the production path.

**Packaging:** PyInstaller one-folder bundle (`blarai.spec`) with `uac_admin=True` manifest, excludes heavy ML frameworks (torch, openvino, etc.), hidden imports for all BlarAI modules. Build + shortcut creation via `scripts/build.ps1`.

**Acceptance Plan:** See `docs/UAT-1_ACCEPTANCE_PLAN.md` — 9 test scenarios (TC-01 through TC-09) covering boot, streaming, PGOV denial, session management, keyboard shortcuts, error handling, VM lifecycle, and shutdown.

**Dependencies:** P1.14 (all upstream tests must pass)

---

## 5. Remaining Steps — Detailed Requirements

### ~~5.1 P1.8 — Orchestrator NPU Inference + Context Management~~ **(DONE — see Section 4.9)**

**Target files:**
- `services/assistant_orchestrator/src/npu_inference.py` (currently STUB)
- `services/assistant_orchestrator/src/context_manager.py` (currently STUB)

**Current stub state:** `OrchestratorNPUInference` class exists with full `GenerationResult` dataclass but all methods return Fail-Closed defaults (`load_model()` → False, `generate()` → empty result, `warm_kv_cache()` → False).

**Requirements:**
1. Load Qwen2.5-1.5B-Instruct OpenVINO INT4-MIXED model from `models/qwen2.5-1.5b-instruct/openvino-int4-npu/` via `openvino_genai.LLMPipeline`
2. Compile for NPU device with Priority 1 scheduling (ADR-010: PA no longer preempts from NPU)
3. Implement token-by-token autoregressive generation with:
   - KV-cache warm state persistence (ADR-008: cache survives context switches)
   - Hard token cap at 4,096 (circuit breaker, `MAX_OUTPUT_TOKENS`)
   - Preemption detection and resume (budget: 0.503ms resume per ADR-008)
4. `warm_kv_cache()`: Pre-populate KV-cache for sub-1s first-token latency
5. Latency targets: 1,000ms first-token warm, 1,500ms first-token cold
6. Fail-Closed: all errors return empty `GenerationResult`
7. Read-only mmap weight access (shared with PA)
8. Context manager: conversation history windowing, turn management

**Dependencies:** P1.0 (scaffold), P1.3 (NPU inference pattern to follow)

### ~~5.2 P1.9 — PGOV (Post-Generation Output Validator)~~ **(DONE — see Section 4.10)**

**Target file:** `services/assistant_orchestrator/src/pgov.py` (currently PARTIAL STUB)

**Current state:** `PGOVResult` dataclass complete. `check_pii()` implemented with basic regex patterns. `check_leakage()` is a STUB returning 0.0. `validate_output()` is implemented but uses the stub leakage function.

**Requirements:**
1. Implement `check_leakage()` with real embedding + cosine similarity:
   - Embed generated text and retrieved RAG chunks using bge-small-en-v1.5
   - Compute pairwise cosine similarity
   - Flag if max similarity ≥ 0.85 threshold (`COSINE_SIMILARITY_THRESHOLD`)
2. Add delimiter echo detection: flag if the output contains Context Spotlighting delimiters that should never appear in user-facing text
3. Add deterministic tool-call allowlist: validate that any tool-call references in generated output match a known-safe set
4. Expand PII patterns beyond basic SSN/CC/email
5. All checks run AFTER generation, BEFORE response delivery
6. Fail-Closed: any PGOV error suppresses the response entirely

**Dependencies:** P1.8 (generation pipeline must exist to have output to validate)

### ~~5.3 P1.10 — Integration Test: PA ↔ Orchestrator ↔ Router over vsock~~ **(DONE — see Section 4.11)**

**Requirements:**
1. End-to-end test harness that:
   - Sends a user query through the Semantic Router (P1.7)
   - Router classifies intent → dispatches to Orchestrator
   - Orchestrator generates response via NPU (P1.8)
   - Orchestrator submits CAR to Policy Agent for tool-call authorization
   - Policy Agent adjudicates via hybrid pipeline (P1.4)
   - Policy Agent mints JWT (P1.5)
   - JWT validated at destination
   - PGOV validates generated output (P1.9)
   - Response delivered
2. All IPC over vsock (AF_HYPERV) with mTLS (P1.6)
3. Validate end-to-end latency against budgets:
   - Router classification: ≤80ms
   - PA adjudication: ≤230ms (CAR check + NPU inference + JWT signing)
   - Orchestrator first-token: ≤1,000ms warm / ≤1,500ms cold
4. Validate Fail-Closed behavior: disconnected PA → all requests denied
5. Validate scheduling resilience under external NPU contention (structural instrumentation)

**Dependencies:** P1.6 + P1.7 + P1.8 + P1.9

---

## 6. Codebase Layout

```
BlarAI/
├── .venv/                              # Python 3.11.9 virtual environment
├── docs/
│   ├── adrs/
│   │   ├── ADR-005-Empirical-Memory-Ceiling-Correction.md
│   │   ├── ADR-006-Empirical-Memory-Budget-Tier-Summation.md
│   │   ├── ADR-007-iGPU-Trust-Boundary-Software-Fallback.md
│   │   ├── ADR-008-NPU-Concurrent-Scheduling-Characterization.md
│   │   ├── ADR-009-Assistant-Interaction-Surface.md
│   │   ├── ADR-010-PA-Device-Allocation-GPU-Classification.md
│   │   ├── ADR-011-Unified-GPU-Inference-NPU-Retirement.md
│   │   └── ADR-012-Qwen3-14B-Model-Selection-Speculative-Decoding.md
│   └── IMPLEMENTATION_PLAN.md          # ← THIS FILE
├── models/
│   ├── bge-small-en-v1.5/
│   │   ├── onnx-fp16/                  # 127.8 MB — CPU inference (Semantic Router)
│   │   └── openvino-int8/              # 33.5 MB — NPU inference (Substrate)
│   ├── qwen3-14b/
│   │   └── openvino-int4-gpu/          # ~9.1 GB — GPU inference (PA + AO + USE-CASE-005) [ADR-012 target]
│   ├── qwen3-0.6b/
│   │   └── openvino-int4/              # ~367 MB — GPU draft model (speculative decoding)
│   ├── qwen3-1.7b/
│   │   ├── openvino-int4/
│   │   └── openvino-int4-npu/          # Legacy/test artifacts
│   └── qwen2.5-1.5b-instruct/
│       └── openvino-int4-npu/          # 975.6 MB — LEGACY (demoted per ADR-012)
├── phase2_gates/
│   ├── evidence/
│   │   ├── dvmt_validation.json
│   │   ├── igpu_trust_report.json
│   │   ├── memory_map.json
│   │   ├── model_acquisition.json
│   │   ├── npu_scheduling_report.json
│   │   ├── p5_005_model_acquisition.json
│   │   ├── p5_unified_model_feasibility_matrix.json
│   │   ├── p5_005b_context_optimization_matrix.json
│   │   └── p5_005b_context_optimization_summary.md
│   └── scripts/
│       ├── acquire_models.py
│       ├── validate_dvmt_budget.ps1
│       ├── validate_igpu_trust_boundary.ps1
│       ├── validate_memory_ceiling.py
│       └── validate_npu_scheduling.py
├── services/
│   ├── policy_agent/
│   │   ├── src/
│   │   │   ├── __init__.py
│   │   │   ├── adjudicator.py          # P1.4 — DONE
│   │   │   ├── boot.py                 # Measured Boot Sequence
│   │   │   ├── car.py                  # P1.1 — DONE
│   │   │   ├── config_loader.py
│   │   │   ├── constants.py
│   │   │   ├── ipc.py                  # P1.6 — DONE
│   │   │   ├── jwt_minter.py           # P1.5 — DONE
│   │   │   ├── gpu_inference.py        # P1.3 — DONE (ADR-010)
│   │   │   └── rule_engine.py          # P1.2 — DONE
│   │   ├── tests/
│   │   ├── config/
│   │   ├── Dockerfile
│   │   └── pyproject.toml
│   ├── assistant_orchestrator/
│   │   ├── src/
│   │   │   ├── __init__.py
│   │   │   ├── circuit_breaker.py
│   │   │   ├── constants.py
│   │   │   ├── context_manager.py      # P1.8 — DONE
│   │   │   ├── npu_inference.py        # P1.8 — DONE
│   │   │   └── pgov.py                 # P1.9 — DONE
│   │   ├── tests/
│   │   ├── config/
│   │   ├── Dockerfile
│   │   └── pyproject.toml
│   ├── semantic_router/
│   │   ├── src/
│   │   │   ├── __init__.py
│   │   │   ├── constants.py
│   │   │   ├── intents.py              # P1.7 — DONE
│   │   │   └── router.py              # P1.7 — DONE
│   │   ├── tests/
│   │   │   └── test_router.py          # 31 tests
│   │   ├── config/
│   │   ├── Dockerfile
│   │   └── pyproject.toml
│   ├── ui_gateway/                      # P1.11 — Transport Gateway
│   │   ├── src/
│   │   │   ├── __init__.py
│   │   │   ├── transport.py             # P1.11 — vsock ↔ IPC relay
│   │   │   ├── session_store.py         # P1.11 — SQLite session persistence
│   │   │   └── constants.py
│   │   ├── tests/
│   │   │   ├── test_transport.py
│   │   │   └── test_session_store.py
│   │   ├── config/
│   │   ├── __init__.py
│   │   └── pyproject.toml
│   ├── ui_shell/                        # P1.12 — Textual TUI
│   │   ├── src/
│   │   │   ├── __init__.py
│   │   │   ├── app.py                   # P1.12 — Textual App
│   │   │   ├── streaming.py             # P1.12 — Token streaming display
│   │   │   ├── session_panel.py         # P1.12 — Session sidebar
│   │   │   ├── pgov_display.py          # P1.12 — PGOV denial panel
│   │   │   └── constants.py
│   │   ├── tests/
│   │   │   ├── test_app.py
│   │   │   ├── test_streaming.py
│   │   │   └── test_pgov_display.py
│   │   ├── config/
│   │   ├── __init__.py
│   │   └── pyproject.toml
│   ├── code_agent/                     # USE-CASE-005 — future
│   ├── cleaner/                        # USE-CASE-003 — future
│   ├── substrate/                      # USE-CASE-002 — future
│   └── mock_backend/                   # P1.15 — UAT-1 mock PA server
│       ├── server.py
│       └── tests/
│           └── test_server.py          # 23 tests
├── launcher/                           # P1.15 — Windows executable launcher
│   ├── __main__.py                     # Entry point (PyInstaller)
│   ├── vm_manager.py                   # Hyper-V VM lifecycle
│   └── tests/
│       ├── test_launcher.py            # 5 tests
│       └── test_vm_manager.py          # 20 tests
├── tests/
│   └── integration/
│       ├── __init__.py
│       └── test_p110_end_to_end.py     # P1.10 — 49 end-to-end tests
├── shared/
│   └── constants.py                    # Empirical hardware constants (ADR-005–008)
├── Use Cases_FINAL.md                  # Canonical architecture (9 use cases, locked)
├── Phase_2_Test_Plan.md                # Hardware gate test procedures
└── .github/
    └── copilot-instructions.md         # Agent operating directives
```

---

## 7. Commit History (Implementation Order)

| Commit | Step | Description |
|--------|------|-------------|
| `12ad400` | — | Phase 2: Scaffold Priority 1 Core Loop + 4 empirical hardware gate scripts |
| `a732399` | Gate 2 | Gate 2 PASS WITH CORRECTION: Empirical ceiling 31.323GB (ADR-005) |
| `b6fa57d` | Gate 3 | Gate 3 PASS WITH WARNING: Memory ceiling validated — 4.5% headroom (ADR-006) |
| `c959864` | Gate 4 | Gate 4 PASS WITH CORRECTION: Software fallback viable (ADR-007) |
| `66106cc` | Gate 5 | All 4 hardware validation gates PASSED — NPU scheduling characterized (ADR-008) |
| `afa42d9` | P1.0 | Scaffold Priority 1 Core Loop — typed module stubs + tests |
| `401ce0e` | P1.1 | CAR Schema Integration Tests — full pipeline validation |
| `12621c5` | P1.2 | Deterministic Rule Engine TOML Loading — RATE + RESOURCE rules |
| `287230d` | P1.3 | NPU Inference (Policy Agent) — OpenVINO + weight integrity |
| `58b178a` | P1.4 | HybridAdjudicator — event-triggered integrity, 4-stage pipeline |
| `fa13d66` | P1.5 | Agentic JWT Minting/Validation — ES256, 5-stage gate, epoch revocation |
| `d2ef3fa` | P1.6 | vsock IPC — protocol, transport, PA listener (372/372 tests) |
| `dc43a90` | Models | Model Acquisition — programmatic API, 3/3 conversions, 3/3 inference tests |
| `698a95e` | — | Constants backfill — replace assumed values with measured evidence |
| `5a6a8e5` | — | Audit: purge stale model references (BERT-mini, 66MB, ~1GB) |
| `352fb21` | P1.7 | Semantic Router CPU fast-path — bge-small-en-v1.5, 31 tests (398/398 total) |
| `d2e4c2e` | P1.8 | Orchestrator NPU inference + context management (440/440 tests) |
| `fdc829f` | P1.9 | PGOV 6-stage output validator — leakage detection, delimiter echo, tool allowlist (484/484 tests) |
| `9c0ca25` | P1.10 | Integration test: PA ↔ Orchestrator ↔ Router over vsock — 49 end-to-end tests (533/533 total) |
| `650f036` | P1.11–P1.12 | Phase 3 UI: Transport Gateway + TUI Shell scaffold — squash-merge to `main` (639/639 tests, +106 new) |
| `065ca0f` | Infra | Validate AF_HYPERV vsock round-trip (host ↔ Alpine VM) |
| `d6b0eee` | P1.11 | Transport Gateway live vsock IPC — MessageFramer protocol, PA handshake, streaming, PGOV cache (652/652 tests, +13 live IPC tests) |
| `d827ba3` | Docs | Documentation sync for P1.11 DONE (652/652 tests) |
| `4174df4` | P1.12 | TUI Shell wired to live Transport Gateway + SessionStore APIs (660/660 tests, +8 new) |
| `87379e8` | P1.13 | Boot-Phase-3 gating enforcement — boot.log logger, state-aware handshake display, Ctrl+R boot retry (668/668 tests) |
| `01dfad8` | P1.14 | End-to-end UX validation suite (31 tests) + stream token circuit-breaker enforcement (699/699 tests) |
| — | P1.15 | UAT-1 Launcher + Mock Backend + Packaging (747/747 tests) |
| `8f60259` | Phase 4 | Operational sign-off — USE-CASE-001 + USE-CASE-004 OPERATIONAL (765/765 tests) |
| — | P5-001 | Context Window Expansion Study — DO-NOT-EXPAND (documentation-only) |
| — | P5-002 | Re-Decision Evidence Collection — FAIL/NO_DECISION (import incompatibility) |
| — | P5-003 | Runtime Memory Ceiling — NOT CHARACTERIZED / containment VALIDATED |
| — | P5-004 | Multi-Device Capability — HYBRID_NPU_GPU |
| — | P5-005 | Unified Model Feasibility — BLOCKED/INSUFFICIENT_EVIDENCE |
| — | P5-006 | ADR-011: NPU retirement, all LLM inference to GPU |
| `62b44a2` | P5-005b | Extended context + optimization characterization — CONTEXT_EXPANSION_FEASIBLE |
| — | ADR-012 | Qwen3-14B model selection lock — speculative decoding mandatory |
| — | ADR-012 §2.4 | Thinking mode strategy LOCKED + KV_CACHE_PRECISION FP16 LOCKED |
| `601eb71` | M1 | Thinking Mode M1: PA `/no_think` + dual stop-token defense-in-depth (772/772 tests) |
| `155ea61` | M2 | Thinking Mode M2: AO thinking allowed + stop-token wiring (784/784 tests) |

---

## 8. Key Constants Reference

From `shared/constants.py` — these are empirical, measured values:

```python
# Memory
EFFECTIVE_CEILING_GB = 31.323           # ADR-005
FIRMWARE_RESERVATION_MB = 692.8         # ADR-005

# NPU
NPU_SCHEDULING_MODEL = "parallel"       # ADR-008
NPU_PARALLELISM_RATIO = 1.699           # ADR-008
NPU_PA_PRIORITY = 0                     # Policy Agent — highest
NPU_ORCH_PRIORITY = 1                   # Orchestrator — yields to PA
NPU_KV_CACHE_PERSISTS = True            # ADR-008
PREEMPTION_P99_MS = 0.814               # ADR-008 (proxy model)

# Trust
TRUST_POSTURE = "software_fallback"     # ADR-007
TDX_AVAILABLE = False                   # Client Lunar Lake

# Latency Budgets
SEMANTIC_ROUTER_LATENCY_MS = 80.0       # Router on CPU
ORCH_FIRST_TOKEN_WARM_MS = 1_000.0      # Orchestrator warm KV
ORCH_FIRST_TOKEN_COLD_MS = 1_500.0      # Orchestrator cold

# Circuit Breakers
MAX_OUTPUT_TOKENS = 4_096
MAX_TOOL_CALL_DEPTH = 5

# Models — ADR-012 target (Qwen3-14B INT4 GPU)
TARGET_MODEL = "qwen3-14b"              # ADR-012 locked target
TARGET_MODEL_WEIGHT_MB = 9_318          # ~9.1 GB INT4 symmetric (measured)
DRAFT_MODEL = "qwen3-0.6b"             # Speculative decoding draft (operational)
DRAFT_MODEL_WEIGHT_MB = 367            # ~367 MB INT4
PA_MODEL_WEIGHT_MB = 9_318              # Qwen3-14B INT4 (ADR-012) — was 976 (Qwen2.5-1.5B)
ORCH_MODEL_WEIGHT_MB = 9_318            # Shared weights with PA (ADR-012)
SEMANTIC_ROUTER_MODEL = "bge-small-en-v1.5"
SEMANTIC_ROUTER_MODEL_MB = 128          # ONNX FP16

# Thinking Mode — ADR-012 §2.4
PA_THINKING_MODE = "no_think"            # /no_think system prompt
PA_STOP_TOKEN_IDS = [151645, 151668]    # <|im_end|>, <|think|> (defense-in-depth)
AO_THINKING_MODE = "think"              # Default thinking allowed
AO_STOP_TOKEN_IDS = [151645]            # <|im_end|>
KV_CACHE_PRECISION = "FP16"             # ADR-012 §2.2 LOCKED
NUM_ASSISTANT_TOKENS = 3                # ADR-012 §2.2 PROVISIONAL

# Security
FAIL_CLOSED = True
COSINE_SIMILARITY_THRESHOLD = 0.85      # PGOV leakage detection
```

---

## 9. Operating Directives for New Chat Sessions

When continuing this work in a new chat, attach the following files:

1. **This file** — `docs/IMPLEMENTATION_PLAN.md`
2. **`Use Cases_FINAL.md`** — Canonical architecture (9 use cases)
3. **`shared/constants.py`** — All empirical constants

### 9.1 Rules

- **Branch:** Active development is on `feature/p5-m2-ao-thinking-mode` (HEAD: `155ea61`). Operational baseline: `feature/p1-uat1-launcher` (sign-off HEAD: `8f60259`). Never commit experimental work directly to `main`.
- **Environment:** Windows 11 Pro. Use backslashes for paths. PowerShell commands. Activate `.venv` before running Python.
- **Privacy:** No external network calls unless explicitly authorized. Fail-Closed everywhere.
- **Testing:** Run `python -m pytest` after every implementation step. All tests must pass before committing.
- **Commits:** Commit at each P1.x milestone with descriptive messages.
- **Fail-Closed:** Every new module defaults to deny/reject/error on any failure — never degrade to permissive.
- **Constants:** Use values from `shared/constants.py`. Do not hardcode hardware assumptions.

### 9.2 P1.x Phase Complete — Next Steps

**P1.0–P1.10 backend milestones: DONE.** 533/533 tests at closure.

**P1.15 UAT-1 Launcher: DONE.** Windows executable, mock backend, packaging (747/747 tests).

**Phase 4 Operational Gap Closure: DONE.** All UAT milestones complete. USE-CASE-001 + USE-CASE-004 declared OPERATIONAL (sign-off HEAD: `8f60259`, 765/765 tests).

**Phase 5 Post-Operational Development: ACTIVE.** ADR-011 (NPU retired), ADR-012 (Qwen3-14B locked), thinking mode M1/M2 implemented. Current test count: **784/784 passing** (HEAD: `155ea61`).

**P1.11 Transport Gateway: DONE.** Live vsock IPC wiring — MessageFramer protocol, PA handshake with retry, streaming token dispatch, PGOV result caching, tool-call buffering. 652/652 tests passing (commit `d6b0eee` on `feature/p1-ui-implementation`).

**P1.12 TUI Shell: DONE.** Wired Textual widgets to live Transport Gateway and SessionStore APIs — correct API signatures, asyncio.to_thread() for sync SessionStore, session auto-create, turn persistence, tool-call buffer flush. 660/660 tests passing (commit `4174df4`).

**P1.13 Boot-Phase-3 Gating: DONE.** Boot logger + state-aware startup polling + Ctrl+R boot retry. 668/668 tests passing (commit `87379e8`).

**P1.14 UX Validation: DONE.** Added 31 integration tests across Transport API, session CRUD, stream flow, boot gating, and PGOV display. Full suite at 699/699 passing (commit `01dfad8`).

The Priority 1 Core Loop backend is fully implemented:
- **Semantic Router** (P1.7) — bge-small-en-v1.5 CPU, dual-gate classification, sub-80ms
- **Assistant Orchestrator** (P1.8) — Qwen2.5-1.5B-Instruct OpenVINO INT4-MIXED, autoregressive generation, KV-cache, preemption detection
- **PGOV** (P1.9) — 6-stage output validation (token budget, PII, delimiter echo, tool allowlist, leakage, approval)
- **Policy Agent** (P1.1–P1.6) — CAR schema, rule engine, NPU inference, hybrid adjudicator, JWT lifecycle, vsock IPC
- **Integration Tests** (P1.10) — 49 end-to-end tests validating all cross-service data flows and Fail-Closed semantics

Phase 3 adds the user interaction surface (ADR-009):
- **Transport Gateway** (P1.11) — **DONE** — live vsock IPC relay, PA handshake, streaming, PGOV cache (46 tests)
- **TUI Shell** (P1.12) — **DONE** — wired to live Gateway + SessionStore, correct API signatures (35 tests)
- **Boot-Phase-3 Gating** (P1.13) — **DONE** — PA handshake enforcement, boot logging, retry semantics
- **UX Validation Tests** (P1.14) — **DONE** — end-to-end integration suite (31 tests)

After P1.14 completion, the system proceeds to **Priority 2** use cases. See Section 11 for the full roadmap.

### 9.3 Phase 4 Operational Gap Closure — Session Log (Priority 2 Milestone)

**Session Date:** 2026-02-24  
**Milestone Scope:** Service entry points + launcher wiring for USE-CASE-001 and USE-CASE-004

Completed in this session:
- Added Policy Agent entrypoint lifecycle module: `services/policy_agent/src/entrypoint.py`.
- Added Assistant Orchestrator entrypoint lifecycle module: `services/assistant_orchestrator/src/entrypoint.py`.
- Wired launcher startup to real entrypoint initialization path:
   - `launcher/__main__.py` now starts Policy Agent entrypoint (fail-closed).
   - `launcher/__main__.py` now starts Assistant Orchestrator entrypoint (fail-closed).
   - Cleanup now stops both services gracefully.
- Added targeted tests for entrypoint startup/failure behavior:
   - `services/policy_agent/tests/test_entrypoint.py`
   - `services/assistant_orchestrator/tests/test_entrypoint.py`
- Updated launcher tests for new entrypoint initialization path:
   - `launcher/tests/test_launcher.py`

Validation evidence:
- `.venv\Scripts\python.exe -m pytest launcher/tests/test_launcher.py services/policy_agent/tests/test_entrypoint.py services/assistant_orchestrator/tests/test_entrypoint.py -q` → `12 passed`
- `.venv\Scripts\python.exe -m pytest tests/integration/test_p110_end_to_end.py -q` → `49 passed`

Status after this milestone:
- Priority 2 (Entrypoints + launcher wiring): **DONE (code-level)**
- Priority 3 (real vsock lifecycle service loops): **NEXT**

---

## 10. Evidence Files

All empirical evidence is preserved in `phase2_gates/evidence/`:

| File | Content |
|------|---------|
| `dvmt_validation.json` | Gate 2: DVMT measurement, ceiling derivation |
| `memory_map.json` | Gate 3: Tier summation, agent RSS breakdown |
| `igpu_trust_report.json` | Gate 4: TDX/TDISP probe, software fallback viability |
| `npu_scheduling_report.json` | Gate 5: Dual-model concurrency, preemption, KV-cache |
| `model_acquisition.json` | Model acquisition: 3 conversions, 3 validations, 3 inference tests |
| `p5_005b_context_optimization_matrix.json` | P5-005b: Extended context + optimization characterization (8 tests, 4 groups) |
| `p5_005b_context_optimization_summary.md` | P5-005b: TPS degradation table, OOM boundary, best config, quality gates |

---

## 11. Future Phases (Beyond P1)

After P1.14 (UI end-to-end validation), the system proceeds to:

### 11.1 Operational Exit Roadmap (USE-CASE-001/004)

| Milestone | Status | Description |
|----------|--------|-------------|
| Operational Exit Milestone 1 (UAT-2 real-runtime activation) | **COMPLETE** | Launcher profile path + fail-closed startup wiring + evidence artifact (`phase2_gates/evidence/uat2_real_runtime_activation.json`) |
| Operational Exit Milestone 2 | **COMPLETE** | Elevated in-process UAT-2 run captured full real-runtime handshake + minimal prompt-flow evidence |
| Operational Exit Milestone 3 (UAT-2.5 hardening) | **COMPLETE** | Multi-run stability matrix + deterministic failure-injection matrix + evidence normalization (`phase2_gates/evidence/uat25_*.json`, `uat25_summary.md`) |
| Operational Exit Milestone 4 (UAT-3 non-dev enablement + UI UAT) | **COMPLETE** | Non-dev operator education from cold start + supervised UI feature/functionality acceptance + runbook/How-To artifacts (commit `5fbe989`) |
| Operational Sign-Off Gate | **COMPLETE** | Final sign-off: compile PASS, focused tests 72 passed, integration 49 passed, non-dev acceptance ACCEPTED. USE-CASE-001 + USE-CASE-004 declared OPERATIONAL (sign-off HEAD: `8f60259`, 765/765 tests). Post-M4 hardening: PGOV false-positive fix. |

### 11.2 Broader Use-Case Roadmap

| Priority | Use Case | Description |
|----------|----------|-------------|
| Phase 3 UI | P1.11 | **DONE** — Transport Gateway live vsock IPC relay (46 tests, commit `d6b0eee`) |
| Phase 3 UI | P1.12 | **DONE** — TUI Shell wired to live Transport Gateway + SessionStore (35 tests, commit `4174df4`) |
| Phase 3 UI | P1.13 | **DONE** — Boot-Phase-3 live gating + boot transition logging (commit `87379e8`) |
| Phase 3 UI | P1.14 | **DONE** — End-to-end UX validation tests (31 tests, commit `01dfad8`) |
| Phase 4+ UI | ADR TBD | Native Desktop Shell migration (PyQt6/Tkinter) — per Lead Architect directive |
| Priority 2 | USE-CASE-002 | Personal Knowledge Substrate (RAG, vector index, bi-encoder on NPU) |
| Priority 2 | USE-CASE-003 | Data Normalization + Adversarial Sanitization (The Cleaner) |
| Priority 3 | USE-CASE-005 | Interactive Local Software Engineer (Headless Microservice — Qwen3-14B INT4 on GPU, ADR-012) |
| Priority 6 | USE-CASE-009 | Autonomous System Maintainer |

Priority 2+ use cases begin after operational sign-off (COMPLETE). Phase 5 post-operational development is ACTIVE.

### 11.3 Phase 5 Post-Operational Maturation

Active Phase 5 development tracked in `docs/POST_OPERATIONAL_MATURATION_LEDGER.md`:

| Milestone | Status | Key Outcome |
|-----------|--------|-------------|
| P5-001 Context Window Study | COMPLETE | DO-NOT-EXPAND (2026-02-25) |
| P5-002 Re-Decision Evidence | COMPLETE | FAIL/NO_DECISION — import incompatibility (2026-02-26) |
| P5-003 Runtime Memory Ceiling | COMPLETE | NOT CHARACTERIZED / containment VALIDATED (2026-02-26) |
| P5-004 Multi-Device Capability | COMPLETE | HYBRID_NPU_GPU (2026-02-26) |
| P5-005 Unified Model Feasibility | COMPLETE | BLOCKED/INSUFFICIENT_EVIDENCE (2026-02-27) |
| P5-006 / ADR-011 NPU Retirement | COMPLETE | All LLM inference on GPU (2026-02-27) |
| P5-005b Context Optimization | COMPLETE | CONTEXT_EXPANSION_FEASIBLE, max safe 20K (2026-02-28) |
| ADR-012 Model Selection Lock | COMPLETE | Qwen3-14B INT4 GPU unified target (2026-02-28) |
| ADR-012 §2.4 Thinking Mode Lock | COMPLETE | PA no_think, AO think, KV FP16 (2026-02-28) |
| M1 PA Thinking Mode | COMPLETE | `/no_think` + dual stop-tokens, 772/772 tests |
| M2 AO Thinking Mode | COMPLETE | Thinking allowed + stop-token, 784/784 tests |
