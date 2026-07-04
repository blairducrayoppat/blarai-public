# Task 4.3 — NAT Sweep × Context Bands

**Execution Prompt:** `docs/Task4.3_v1.xml`
**Branch:** `feature/p5-task4-3-nat-sweep`
**Pre-condition:** Task 4.2 COMPLETE (Draft-A LOCKED)

## Objective

Sweep `num_assistant_tokens` [1, 2, 3, 5, 7, 10] across context bands [512, 2048, 4096, 8192, 12288, 16384, 20480] using Draft-A only (Qwen3-0.6B 28L INT4 GPU). Draft-B was eliminated in Task 4.2. Original spec was 4K-only with two draft models — scope expanded to full production range with 6 NAT values after Draft-B elimination.

- **Total:** 42 configurations × 7 runs (2 warmup + 5 measured) = 294 `generate()` calls
- **Estimated runtime:** ~2 hours
- **Pipeline:** Compiled once. NAT varies per-request via `GenerationConfig.num_assistant_tokens`
- **XAttention:** OFF (default — not varied in this task)
- **KV cache precision:** FP16 (locked)
- **max_new_tokens:** 128 per config

## Key Measurements

- Mean TPS per config (5 measured runs)
- Aggregate acceptance rate per config
- Peak RSS per band
- Per-band winner identification (highest TPS)
- Global weighted TPS score across bands (weighted by production band frequency)
- Standalone draft TPS baseline (3 runs @ 4K)
- Pipeline compile time

## Quality Gates

| Gate | Criterion |
|------|-----------|
| G-01 | All 42 configs complete, no OOM_SKIPPED |
| G-02 | TPS at 4K/NAT=3 exceeds P5-005b baseline directionally |
| G-03 | Minimum 5 valid measured runs per config |
| G-04 | Deterministic execution confirmed (AR identical across runs) |
| G-05 | Per-band winners converge to single NAT, or SDO_DECISION_REQUIRED if >10% cost |
| G-06 | AR ≥ 0.25 at all bands, or FAIL_WARNING |
| G-07 | Peak RSS within ADR-006 tier budget (15,507 MB) |

## Disposition Logic

- If single NAT wins all bands → `NAT_LOCKED`, update ADR-012 §2.2
- If per-band winners diverge with >10% TPS cost at any band → `SDO_DECISION_REQUIRED` (adaptive NAT needed)

## Governance Actions

- GOV-01: If NAT_LOCKED → lock ADR-012 §2.2 `num_assistant_tokens`
- GOV-02: If SDO_DECISION_REQUIRED → retain PROVISIONAL BEST, append note to ADR-012
- GOV-03: Confirm pipeline construction row LOCKED
- GOV-04: Append LEDGER Entry 17

## Evidence Artifact

`phase2_gates/evidence/p5_task4_3_nat_sweep_matrix.json`
