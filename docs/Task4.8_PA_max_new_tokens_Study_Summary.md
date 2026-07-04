# Task 4.8 — PA max_new_tokens Study

**Execution Prompt:** `docs/Task4.8_v1.xml`
**Branch:** `feature/p5-task4-8-pa-max-tokens`
**Pre-condition:** Task 4.6 COMPLETE

## Objective

Determine the lowest safe `max_new_tokens` ceiling for the Policy Agent that still achieves 100% label extraction. The PA classifier outputs a short label (e.g., `ALLOW`, `DENY`) but the `max_new_tokens` ceiling must account for Qwen3's think block overhead — even with `/no_think`, the model emits \~3 think tokens before the classification label, consuming effective budget.

- **Candidates (PA-T1 through PA-T4):** [32, 15, 10, 8]
- **PA bands:** [512, 2048]
- **Stop configs:** PRODUCTION (`/no_think` + dual stop tokens `[151645, 151668]`) and LABEL_EXTRACTION (stop tokens removed to observe full output)
- **Total:** 240 `generate()` calls (4 candidates × 2 bands × 2 stop_configs × 15 runs)

## Key Measurements

- Label extraction rate per candidate per band (% of runs where valid classification label appears)
- Think block token count (tokens consumed before label begins)
- PRODUCTION audit: whether think stop fires before label under production config (should be 100%)
- P95 latency per candidate per band vs 2,000ms PA budget

## Quality Gates

| Gate | Criterion |
|------|-----------|
| G-01 | All 240 generate() calls complete |
| G-02 | PRODUCTION config: 100% think stop fires before label (0% extraction = correct) |
| G-03 | LABEL_EXTRACTION: identifies highest-passing and lowest-failing candidate |
| G-04 | Deterministic label output across runs |
| G-05 | P95 latency ≤ 2,000ms at locked candidate, or LATENCY_WARNING |

## Disposition Logic

- Lock lowest `max_new_tokens` candidate achieving 100% label extraction across all bands
- Think block overhead (3 tokens) means effective label budget = `max_new_tokens - 3`
- PA-T4 (8) → effective budget 5 tokens — insufficient for multi-token labels
- PA-T3 (10) → effective budget 7 tokens — sufficient for all observed labels

## Governance Actions

- Lock ADR-012 §2.2 PA `max_new_tokens` row
- Update ADR-012 §2.4 with think block overhead finding
- Append LEDGER Entry 22

## Evidence Artifact

`phase2_gates/evidence/p5_task4_8_pa_max_tokens_study.json`
