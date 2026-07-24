---
title: Task4.8_EXECUTION_REPORT
status: archived
area: portfolio
---

# Task 4.8 Execution Report — SDO Handoff

**Branch:** `feature/p5-task4-8-pa-max-tokens`
**Commit:** `8d334dd`
**Date:** 2026-03-04
**Status:** COMPLETE

---

## What Was Executed

Task 4.8 PA max_new_tokens feasibility study — 240 `generate()` calls across:
- 4 max_new_tokens configs: {32, 15, 10, 8}
- 2 input bands: {512, 2048}
- 2 stop_configs: PRODUCTION [151645, 151668] and LABEL_EXTRACTION [151645]
- 15 runs per cell — 30 CAR payloads (5 ALLOW, 5 DENY, 5 ESCALATE per band)

Model: Qwen3-14B INT4 GPU + Qwen3-0.6B INT4 Draft-A. All Task 4.3–4.7 LOCKED configs applied.

---

## Decision — DEC-08

**PA `max_new_tokens=10` LOCKED** (disposition: PA_T3_LOCKED).

Lowest ceiling with 100% label extraction at both input bands.

---

## Critical Findings

1. **Think block always present.** Even with `/no_think` at system prompt START (production placement), Qwen3-14B emits `<think>\n\n</think>` (3 tokens, 100% of runs). Effective label budget = `max_new_tokens - 3`.

2. **PRODUCTION stop config confirmed at scale.** 120/120 PRODUCTION runs: token 151668 fires before any label is emitted (0% label extraction). This is a known architectural property — the dual-stop defense-in-depth functions as designed but suppresses label emission entirely. The `MAX_CLASSIFICATION_TOKENS=32` constant in `gpu_inference.py` line 80 is dead budget under current wiring.

3. **PA-T4 (8) fails.** At max_new_tokens=8, only 5 tokens remain post-think. DENY (\~6t) and ESCALATE (\~7t) labels are truncated. Extraction rate: 60% at band 512, 33% at band 2048.

4. **PA-T3 (10) passes clean.** 7 effective tokens — sufficient for all three label variants. 100% extraction at both bands, 15/15 runs each.

5. **G-05 LATENCY_WARNING.** P95 at band 2048 = 6616ms > 2000ms PA budget. Expected — worst-case 2048-token input prefill dominates. Not a blocker.

---

## LABEL_EXTRACTION Results Table

| Config | max_new_tokens | Band 512 | Band 2048 | Disposition |
|--------|---------------|----------|-----------|-------------|
| PA-T1  | 32            | 100%     | 100%      | Too generous |
| PA-T2  | 15            | 100%     | 100%      | Safe margin |
| PA-T3  | 10            | 100%     | 100%      | **LOCKED** — lowest safe ceiling |
| PA-T4  | 8             | 60%      | 33%       | FAILS — insufficient for DENY/ESCALATE |

---

## Quality Gates

| Gate | Result | Notes |
|------|--------|-------|
| G-01 MINIMUM_DATA | PASS | 240/240 runs completed, 0 errors |
| G-02 LABEL_SANITY | PASS | PA-T1 (32) ≥ 80% at both bands |
| G-03 PRODUCTION_AUDIT_CONSISTENT | PASS | 100% think stop in PRODUCTION runs |
| G-04 THINK_OVERHEAD_CHARACTERIZATION | PASS | 3 tokens, 100% presence |
| G-05 LATENCY_BUDGET | LATENCY_WARNING | P95@2048=6616ms > 2000ms; expected for worst-case band |

---

## Artifacts Committed (4 files)

| File | Status |
|------|--------|
| `phase2_gates/scripts/run_p5_task4_8_pa_max_tokens_study.py` | Created (\~1642 lines) |
| `phase2_gates/evidence/p5_task4_8_pa_max_tokens_study.json` | Created (240-run evidence) |
| `docs/adrs/ADR-012-Qwen3-14B-Model-Selection-Speculative-Decoding.md` | §2.2 GenConfig row (DEC-08 note) + §4 evidence ref |
| `docs/POST_OPERATIONAL_MATURATION_LEDGER.md` | Entry 22 appended |

---

## ADR-012 §2.2 Status After Task 4.8

The GenConfig row remains EVALUATING. PA `max_new_tokens=10` is now noted as LOCKED (DEC-08). AO and CODE handler max_new_tokens are still to be measured (Tasks 4.9–4.10). The row can only be fully LOCKED when all three components are decided.

---

## Open Item Flagged for SDO

The `MAX_CLASSIFICATION_TOKENS=32` constant in `services/policy_agent/src/gpu_inference.py` line 80 is currently dead budget under the production dual-stop wiring. DEC-08 (`max_new_tokens=10`) cannot be wired into production code without first resolving the dual-stop behavior for PA classification. This is a **Task 5 implementation concern** — flagged for SDO awareness when scoping the Model Upgrade execution prompt.

---

## Test Baseline

786 collected / 755 passed (31 deferred p114 asyncio — pre-existing, not a regression). No regressions introduced.
