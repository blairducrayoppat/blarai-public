---
title: Task4.12e_Summary
status: archived
area: portfolio
---

# Task 4.12e — EA-5 Execution Summary

**Date:** 2026-03-07
**Branch:** `feature/p5-task4-12-corpus-hardening`
**Predecessor:** EA-4 (bcd6a66), 228 cases
**Type:** IMPLEMENTATION + MEASUREMENT (harness expansion + full quality gate run)
**Constraint K-1:** No production code changes — only harness + governance docs

## Scope

Add 28 upper-band test cases (IDs 228–255) across two new context bands (8192 and 12288),
then run the full quality gate (256 cases × 3 determinism runs = 768 LLM calls). Compute
all 8 measurements (M-1 through M-8). Update governance docs. Commit.

## Cases Added

| ID Range | Band | Count | Composition (O-1 adjusted) |
|----------|------|-------|---------------------------|
| 228–241 | 8192 | 14 | 6 DENY (Cat A), 4 DENY (Cat B adversarial), 2 ESCALATE (Cat B), 2 ALLOW (Cat D) |
| 242–255 | 12288 | 14 | 6 DENY (Cat A), 4 DENY (Cat B adversarial), 2 ESCALATE (Cat B), 2 ALLOW (Cat D) |

All 28 cases use `_make_car()` with `source="blarai-code-agent"`, `expected_path="LLM"`.
All 28 cases verified to bypass DPC (pre-filter check: 256/256 PASS).

## Final Corpus

- **Total:** 256 cases (IDs 0–255)
- **Label distribution:** ALLOW=24, DENY=194, ESCALATE=38
- **Prefiltered (DPC bypass):** 49 cases
- **LLM-path:** 207 cases
- **Context bands:** 512 (10), 1024 (10), 2048 (10), 4096 (10), 8192 (14), 12288 (14)

## Measurements

| ID | Metric | Value | Threshold | Disposition |
|----|--------|-------|-----------|-------------|
| M-1 | Overall agreement | **0.6055** (155/256) | ≥ 0.90 | **FAIL** (BLOCKING) |
| M-2 | Adversarial security | **0.7976** (67/84) | ≥ 0.95 | **FAIL** (BLOCKING) |
| M-3 | LLM-path agreement | **0.5121** (106/207) | INFO | INFO |
| M-4 | LLM-path DENY accuracy | **0.5000** (42/84) | INFO | INFO |
| M-5 | LLM-path adversarial security | **0.7763** (59/76) | ≥ 0.95 | **FAIL** (BLOCKING) |
| M-6 | DENY_AUTHORITY_CLAIM coverage | 24/24 Cat C DENY (5 branches) | ≥ 5 branches | PASS |
| M-7 | Determinism | 256/256 identical × 3 runs | 100% | PASS |
| M-8 | Original-40 regression | 40/40 (0 adversarial ALLOW) | 40/40 | PASS |

## Confusion Matrix (LLM-path, 207 cases)

|              | Pred ALLOW | Pred DENY | Pred ESCALATE |
|--------------|-----------|-----------|---------------|
| **Exp ALLOW** (28) | **24** | 2 | 2 |
| **Exp DENY** (103) | 13 | **42** | 48 |
| **Exp ESCALATE** (76) | 17 | 34 | **25** |

## Key Findings

1. **DENY→ESCALATE over-escalation** is the dominant error: 48/103 DENY-expected cases
   predicted ESCALATE (46.6%). Model consistently fails toward more restrictive under /no_think.
2. **17 adversarial ALLOW violations** across Cat B LLM-path cases — security gap requiring
   Task 4.11 intervention.
3. **Original 40 cases stable**: 40/40 agreement, 0 adversarial ALLOW regressions (M-8 PASS).
4. **Perfect determinism**: All 256 cases identical across 3 runs (M-7 PASS).
5. **DPC Rule 4 validated**: 24/24 Cat C cases correctly prefiltered as DENY_AUTHORITY_CLAIM,
   all 5 AUTHORITY_CLAIM_RE branches covered (M-6 PASS).

## Disposition

**COMPLETE — QUALITY_GATE_FAIL (3 BLOCKING gates: M-1, M-2, M-5)**

This establishes the LLM classification baseline for the 256-case corpus on Qwen3-14B
with /no_think. Task 4.11 (Security Hardening) will use these measurements as its starting
point.

## Evidence

`phase2_gates/evidence/p5_task4_12_corpus_hardening.json` (416 KB, 768 run entries)

## Governance Updates

- LEDGER: Entry 29 updated (COMPLETE)
- IMPLEMENTATION_PLAN: §1.24 updated (COMPLETE, QUALITY_GATE_FAIL)
- P5_TASK4_PRODUCTION_CONFIG_FEASIBILITY.md: 4.12 row updated (COMPLETE)
