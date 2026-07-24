---
title: Task4.9b_EXECUTION_REPORT
status: archived
area: portfolio
---

# Task 4.9b Execution Report — /no_think Removal Measurement + Parser Hardening C-3

**Branch:** `feature/p5-task4-9-pa-quality-gate`
**HEAD:** `e37cbc3`
**Date:** 2026-03-05
**Ledger:** Entry 25 | **Impl Plan:** §1.19 | **ADR-012:** §2.2 DEC-09b + §4
**Test Suite:** 251/251 PA passed

---

## Objective

Empirically measure PA classification quality when `/no_think` is removed from the system prompt, enabling Qwen3-14B Chain-of-Thought reasoning. This was escalated from Task 4.9a (Entry 24) after identifying residual DENY↔ESCALATE confusion as the remaining classification error under `/no_think`.

## What Was Done

**Production code (2 files):**
1. **ClassificationParser hardened (C-3)** in `services/policy_agent/src/gpu_inference.py` — think-block stripping via `<think>.*?</think>` regex + multi-label rejection (2+ labels → DENY). BUG-1 from v1 prompt fixed before execution: empty think-block-only input returns DENY immediately, no fallback to raw text.
2. **6 new unit tests** in `services/policy_agent/tests/test_gpu_inference.py` — covering think strip, multi-label rejection, think-block-only, empty think-block, stray token regression.

**Harness (1 file):**
3. **`phase2_gates/scripts/run_p5_task4_9_pa_quality_gate.py`** — 5 measurement overrides applied: `/no_think` stripped from system prompt (K-2: production retains it), `max_new_tokens=64` (K-4: production stays at 10), tokenizer-based think-block counting, multi-label detection, expanded evidence fields.

**Evidence artifact:**
4. **`phase2_gates/evidence/p5_task4_9b_no_think_measurement.json`** — 40 cases × 3 runs = 120 `generate()` calls. Full run completed (first attempt timed out at case 29, harness auto-resumed from checkpoint).

**Governance (3 files):**
5. ADR-012 §2.2 — DEC-09b annotation LOCKED. §4 — evidence ref added.
6. POST_OPERATIONAL_MATURATION_LEDGER — Entry 25 (full measurement report).
7. IMPLEMENTATION_PLAN — §1.19 added.

---

## Disposition: MEASUREMENT_HARD_FAIL_LABEL_EXTRACTION

Removing `/no_think` **destroys PA classification completely.**

## Mandatory Measurements (7/7 collected)

| # | Metric | Result | Threshold | Verdict |
|---|--------|--------|-----------|---------|
| M-1 | `decision_agreement_rate` | **0.025** (1/40) | ≥ 0.775 (4.9a baseline) | **HARD FAIL** |
| M-2 | `adversarial_security_rate` | **0.125** (1/8) | ≥ 0.875 | **HARD FAIL** |
| M-3 | `think_block_token_count` | 0/120 completed blocks | INFO | Catastrophic |
| M-4 | `total_output_token_count` | 64/64/64.0/64 (min/max/mean/P50) | INFO | All ceiling-hit |
| M-5 | `latency_per_band` | 512→5859ms, 1024→8034ms, 2048→10460ms, 4096→18908ms | INFO | 3–6× worse |
| M-6 | `label_extraction_rate` | 9/120 (7.5%) | ≥ 120/120 | **HARD FAIL** |
| M-7 | `multi_label_rejection_count` | 111/120 | INFO | Dominant failure mode |

## Baseline Comparison (4.9a → 4.9b)

| Metric | 4.9a (with /no_think) | 4.9b (without /no_think) | Delta |
|--------|----------------------|-------------------------|-------|
| Agreement rate | 0.775 (31/40) | 0.025 (1/40) | **−0.750** |
| Adversarial security | 1.000 (8/8) | 0.125 (1/8) | **−0.875** |
| Label extraction | 120/120 | 9/120 | **−111** |
| P50 latency (512-band) | 1,885 ms | 5,859 ms | **+3.1×** |

## Confusion Matrix

```
                 ALLOW  DENY  ESCALATE  NO_LABEL
Exp ALLOW(12)       0     1         0        11
Exp DENY(22)        1     1         0        20
Exp ESCALATE(6)     0     0         0         6
```

39/40 cases disagreed. 37 were `no_label`. Only Case 9 (adversarial DENY, band 512) matched.

## Root Cause

Without `/no_think`, Qwen3-14B opens `<think>` but **never closes `</think>`** within 64 tokens. The model enters unbounded CoT reasoning that consumes the entire token budget. Since `</think>` never appears, the think-block regex finds no completed block to strip. The remaining raw text mentions multiple classification labels as part of reasoning, triggering the multi-label rejection path (111/120 runs). The 9 "extracted" labels were false positives where reasoning text happened to contain exactly one label keyword before truncation.

## Constraint Verification

| ID | Constraint | Status |
|----|-----------|--------|
| K-1 | `stop_token_ids=[151645]` only (151668 NEVER added) | **PASS** |
| K-2 | Production `SYSTEM_PROMPT` retains `/no_think` | **PASS** |
| K-3 | `uat2_real_runtime_activation.json` not in commit | **PASS** |
| K-4 | Production `max_new_tokens=10` unchanged (DEC-08 LOCKED) | **PASS** |

## Architectural Conclusion

**`/no_think` is MANDATORY for Qwen3-14B PA classification. DEC-09b is LOCKED in ADR-012 §2.2.**

CoT reasoning is not a viable path for improving the residual DENY↔ESCALATE confusion from Task 4.9a (77.5% agreement). The 7 label_swap errors must be addressed through alternative mechanisms — prompt engineering refinement, ensemble approaches, or acceptance of the current 77.5% agreement rate pending model upgrades.

## Verification Commands

```powershell
git log --oneline -1
# e37cbc3 Task 4.9b: /no_think removal measurement + parser hardening C-3

git show --stat HEAD --format="%H %s"
# 7 files changed, 3804 insertions(+), 31 deletions(-)

pytest services/policy_agent/ --tb=short -q
# 251 passed
```
