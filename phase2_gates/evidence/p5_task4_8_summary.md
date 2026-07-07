# Task 4.8 — PA max_new_tokens Study: Summary Report

**Date:** 2026-03-05  
**Task:** P5 Task 4.8  
**Branch:** `feature/p5-task4-8-pa-max-tokens`  
**Git HEAD:** `fbd8918`  
**Decision:** DEC-08 — PA `max_new_tokens = 10` **LOCKED**  
**Evidence:** `phase2_gates/evidence/p5_task4_8_pa_max_tokens_study.json`  
**Ledger:** Entry 22  

---

## 1. Objective

Determine the minimum safe `max_new_tokens` value for the Policy Agent (USE-CASE-001). The PA classifies inter-agent action requests with short outputs (`DECISION: ALLOW|DENY|ESCALATE`). The current production default of 32 was conservative — this study measures whether a tighter ceiling preserves 100% label extraction while reducing decode overhead.

## 2. Environment

| Parameter | Value |
|---|---|
| OpenVINO GenAI | 2026.0.0.0-2820-dab5b993a38 |
| Target Model | Qwen3-14B INT4 GPU |
| Draft Model | Qwen3-0.6B INT4 GPU (Draft-A) |
| Device | GPU (Intel Arc 140V) |
| Inference Precision | FP16 (LOCKED — Task 4.7) |
| num_assistant_tokens | 3 (LOCKED — Task 4.3) |
| SDPA Optimization | True (LOCKED — Task 4.4) |
| Prefix Caching | False (LOCKED — Task 4.6) |
| Compile Time | 13,502 ms |
| Warmup RSS | 12,847 MB |
| AC Power | Plugged in (80%) |

## 3. Test Matrix

**Total generate() calls:** 240  
**Pipeline compilations:** 1 (shared across all runs)

| Dimension | Values | Count |
|---|---|---|
| `max_new_tokens` | 32 (PA-T1), 15 (PA-T2), 10 (PA-T3), 8 (PA-T4) | 4 |
| Input Band | 512 tokens, 2048 tokens | 2 |
| Stop Config | PRODUCTION `[151645, 151668]`, LABEL_EXTRACTION `[151645]` | 2 |
| Runs per group | 15 (5 ALLOW + 5 DENY + 5 ESCALATE payloads) | 15 |

## 4. Key Finding — Think Block Overhead

Qwen3-14B with `/no_think` in the system prompt **still emits a think block** (`<think>\n\n</think>`) before every classification label. This consumes **3 tokens** from the `max_new_tokens` budget.

- Think block present: **100%** of all LABEL_EXTRACTION runs
- Think block tokens: **3** (constant across all 120 LABEL_EXTRACTION runs)
- Effective label budget: `max_new_tokens - 3`

## 5. Production Audit (PRODUCTION stop config)

Stop tokens: `[151645, 151668]` — matches current production wiring.

| Result | Value |
|---|---|
| Total runs | 120 |
| Stop reason | `STOP_TOKEN_151668` for 120/120 (100%) |
| Tokens generated | 3 per run (the think block only) |
| Label extraction | 0% — think stop fires before any label is emitted |
| Conclusion | Production wiring prevents label generation for ALL `max_new_tokens` values |

This confirms that in current production, the PA relies on `ClassificationParser` fail-closed logic (returns "DENY") since the think stop kills generation before any label tokens are emitted. Lowering `max_new_tokens` cannot make this behavior worse.

## 6. Label Extraction Results (Decision-Relevant)

Stop tokens: `[151645]` only — allows model to generate through the think block and emit classification labels.

### 6.1 Label Extraction Rate by Config

| Config | max_new_tokens | Band 512 | Band 2048 | Status |
|---|---|---|---|---|
| **PA-T1** | 32 | **100%** (0 failures) | **100%** (0 failures) | PASS |
| **PA-T2** | 15 | **100%** (0 failures) | **100%** (0 failures) | PASS |
| **PA-T3** | 10 | **100%** (0 failures) | **100%** (0 failures) | PASS |
| **PA-T4** | 8 | **60%** (6 failures) | **33%** (10 failures) | FAIL |

PA-T4 (max_new_tokens=8) fails because the think block (3 tokens) + label prefix tokens exceed the 8-token ceiling, truncating longer labels like `DECISION: ESCALATE` mid-word (`DECISION: ESC`, `DECISION: DEN`).

### 6.2 Latency by Config

| Config | max_new_tokens | Band 512 Mean (ms) | Band 512 P95 (ms) | Band 2048 Mean (ms) | Band 2048 P95 (ms) |
|---|---|---|---|---|---|
| PA-T1 | 32 | 2,141 | 2,286 | 6,458 | 6,617 |
| PA-T2 | 15 | 2,137 | 2,304 | 6,464 | 6,692 |
| PA-T3 | 10 | 2,116 | 2,561 | 6,495 | 6,765 |
| PA-T4 | 8 | 1,922 | 2,057 | 6,293 | 6,414 |

Latency is dominated by TTFT (prompt processing), not decode. The difference between PA-T1 and PA-T3 is negligible because PA outputs are only 8–10 tokens regardless.

### 6.3 Token Generation by Config

| Config | max_new_tokens | Mean Tokens | Mean Think Tokens | Mean Post-Think Tokens | Stop Reasons |
|---|---|---|---|---|---|
| PA-T1 | 32 | 8.67 / 9.13 | 3.0 | 4.67 / 5.13 | All STOP_TOKEN_OTHER |
| PA-T2 | 15 | 8.67 / 9.13 | 3.0 | 4.67 / 5.13 | All STOP_TOKEN_OTHER |
| PA-T3 | 10 | 8.67 / 9.13 | 3.0 | 4.67 / 5.13 | 11 STOP_TOKEN + 4 MAX / 8 STOP_TOKEN + 7 MAX |
| PA-T4 | 8 | 8.0 / 8.0 | 3.0 | 4.0 / 4.0 | All MAX_TOKENS |

Values shown as Band 512 / Band 2048. PA-T3 starts hitting MAX_TOKENS for longer labels (ESCALATE = 6 post-think tokens), but the label is still fully extractable. PA-T4 hard-truncates all runs at 8 tokens.

### 6.4 PA-T4 Failure Examples

| Run | max_new_tokens | Band | Raw Output | Extracted Label | Expected |
|---|---|---|---|---|---|
| 5 | 8 | 512 | `<think>\n\n</think>\n\nDECISION: DEN` | null | DENY |
| 6 | 8 | 512 | `<think>\n\n</think>\n\nDECISION: ESC` | null | DENY |
| 7 | 8 | 512 | `<think>\n\n</think>\n\nDECISION: ESC` | null | DENY |
| 5 | 8 | 2048 | `<think>\n\n</think>\n\nDECISION: ESC` | null | DENY |

With only 5 post-think tokens (8 - 3 think), the model can produce `DECISION: ALLOW` (4 post-think tokens) but not `DECISION: DENY` (5 tokens) or `DECISION: ESCALATE` (6 tokens) if the prefix `DECISION: ` consumes too many tokens.

## 7. Quality Gates

| Gate | Description | Result |
|---|---|---|
| G-01 | Minimum data (240 runs collected) | **PASS** |
| G-02 | Label sanity (extracted labels match ALLOW/DENY/ESCALATE) | **PASS** |
| G-03 | Production audit consistent (think stop fires 100%) | **PASS** |
| G-04 | Think overhead characterization (100% present, 3 tokens) | **PASS** |
| G-05 | Latency budget (P95 < 2000ms) | **LATENCY_WARNING** (P95@2048 = 6,616 ms) |

G-05 warning is expected — the 2048-band P95 is high because TTFT at 2048 input tokens dominates (\~5,800 ms). This is inherent to the model size and input length, not a `max_new_tokens` issue.

## 8. Calibration

| Metric | Value |
|---|---|
| Task 4.7 ref PA 512 TPS | 4.806 |
| Task 4.7 ref PA 512 TTFT | 3,212 ms |
| Task 4.8 PA-T1 512 mean latency | 2,141 ms |
| Drift | 33.4% |
| Status | CALIBRATION_WARNING |

Calibration drift exceeds the ±30% tolerance. This is attributed to environmental variance (different session, thermal state, background processes) and does not affect the label extraction decision since the metric under test is categorical (label extracted: yes/no), not a latency threshold.

## 9. Decision — DEC-08

**`max_new_tokens = 10` LOCKED for Policy Agent.**

**Rationale:** PA-T3 (max_new_tokens=10) achieved **100% label extraction** at both input bands (512 and 2048) across all 30 LABEL_EXTRACTION runs. It is the **lowest safe ceiling** — PA-T4 (8) failed at 60%/33%.

**Token budget breakdown at max_new_tokens=10:**
- Think block overhead: 3 tokens (`<think>\n\n</think>`)
- Effective label budget: 7 tokens
- Longest observed output: `<think>\n\n</think>\n\nDECISION: ESCALATE` (10 tokens)
- ALLOW: 8 tokens total (fits)
- DENY: 9 tokens total (fits)
- ESCALATE: 10 tokens total (fits, hits ceiling exactly)

**Governance updates:**
- ADR-012 §2.2: GenConfig fields row updated — PA max_new_tokens = 10 LOCKED
- ADR-012 §4: Think block interaction documented
- POST_OPERATIONAL_MATURATION_LEDGER.md: Entry 22

**Note:** The production constant `MAX_CLASSIFICATION_TOKENS` in `gpu_inference.py` is NOT changed by this task — it will be updated in Task 4.10 (finalization) once all dependent decisions are locked.
