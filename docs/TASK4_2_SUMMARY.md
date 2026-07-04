# Task 4.2 Summary — Draft Model Comparison

**Milestone:** P5-Task-4.2  
**Status:** COMPLETE  
**Disposition:** DRAFT_A_WINS  
**Branch:** `feature/p5-task4-2-combined-rerun` (corrected rerun of original `feature/p5-task4-2-draft-model-comparison`)  
**Commit (corrected):** `95a3f0a` (original), overwritten with corrected evidence on `feature/p5-task4-2-combined-rerun`  
**Ledger:** Entry 14 (+ correction note in Entry 15)

---

## Objective

Compare two draft model candidates for speculative decoding with the Qwen3-14B INT4 target model on Intel Arc 140V (Xe2) GPU. Select the winner to carry forward as the default draft model for Tasks 4.3–4.10.

| Candidate | Architecture | Quantization | Layers | Weight Size |
|-----------|-------------|-------------|--------|-------------|
| **Draft-A** | Qwen3-0.6B | INT4 | 28 (full) | 367 MB |
| **Draft-B** | Qwen3-0.6B-pruned-6L | INT8_ASYM | 22 (pruned) | 480 MB |

---

## Test Configuration (Locked)

| Parameter | Value |
|-----------|-------|
| Target model | Qwen3-14B INT4 GPU |
| NAT (num_assistant_tokens) | 3 |
| XAttention | OFF |
| Inference precision | FP16 (Xe2 default — `INFERENCE_PRECISION` invalid on this build) |
| KV cache precision | FP16 (default) |
| Scheduler cache size | 3 GB |
| Context tokens | \~4,115 (with chat template) |
| max_new_tokens | 128 |
| do_sample | False |
| temperature | 0 |
| Warmup runs | 2 |
| Measured runs (speculative) | 5 |
| Measured runs (standalone) | 3 |

---

## Results

### Speculative Decoding (14B + Draft)

| Metric | T-01: Draft-A (28L INT4) | T-02: Draft-B (22L INT8_ASYM) | Delta |
|--------|:------------------------:|:-----------------------------:|:-----:|
| **Combined TPS (mean)** | **10.87** | **9.50** | **+12.6% A** |
| Combined TPS (stddev) | 0.59 | 1.31 | — |
| Native TPS (mean) | 10.52 | 9.22 | +12.4% A |
| Native TTFT (mean) | 8,935 ms | 13,291 ms | -32.8% A better |
| Native TPOT (mean) | 95.4 ms | 110.8 ms | -13.9% A better |
| Acceptance Rate | **0.457** (370/810) | **0.520** (390/750) | B higher |
| Per-step AR [s0, s1, s2] | [0.722, 0.370, 0.278] | [0.740, 0.480, 0.340] | B higher all steps |
| Peak RSS | 12,646 MB | 12,510 MB | B lower |
| Pipeline compile | 20,834 ms | 19,061 ms | — |
| Valid / Failed runs | 5 / 0 | 5 / 0 | — |

### Draft Model Standalone (Forward Speed Upper Bound)

| Metric | T-03: Draft-A Standalone | T-04: Draft-B Standalone |
|--------|:------------------------:|:------------------------:|
| **TPS (mean)** | **47.43** | **42.19** |
| TPS (stddev) | 0.85 | 0.68 |
| TTFT (mean) | 1,107 ms | 892 ms |
| Peak RSS | 4,149 MB | 4,289 MB |
| Valid / Failed runs | 3 / 0 | 3 / 0 |

### Derived Forward Cost per NAT Cycle

| Draft | Calculation | Result |
|-------|------------|--------|
| Draft-A | 1000 / 47.43 tps × 3 steps | **63.25 ms** |
| Draft-B | 1000 / 42.19 tps × 3 steps | **71.11 ms** |

---

## Harness Validation vs P5-005b Baseline (D-01)

| Metric | T-01 (corrected) | D-01 Baseline | Delta |
|--------|:-----------------:|:-------------:|:-----:|
| Native TPS | 10.52 | 11.15 | -5.7% |
| Wall-clock TPS | 10.87 | 11.15 | -2.5% |
| **Verdict** | PLAUSIBLE | — | Within normal variance ✅ |

---

## Decision: DRAFT_A_WINS

**Draft-A (Qwen3-0.6B 28L INT4)** wins on the primary metric (combined TPS: 10.87 vs 9.50, +12.6%) despite Draft-B having a higher acceptance rate (0.520 vs 0.457).

### Why TPS wins over acceptance rate

Draft-B accepts more tokens per cycle but its forward passes are slower (71.1 ms vs 63.3 ms per NAT cycle). The net effect: Draft-A's faster forward speed more than compensates for its lower acceptance rate, producing higher end-to-end throughput for the user.

---

## Key Findings

1. **INFERENCE_PRECISION is invalid.** The correct OV GPU property is `INFERENCE_PRECISION_HINT`. FP16 is the Xe2 default — no explicit override needed. All subsequent Task 4.x harnesses must NOT pass `INFERENCE_PRECISION` as a kwarg.

2. **Acceptance rate data is available** via `extended_perf_metrics.m_batch_sizes` when using list-input `generate([prompt], ...)`. The original harness used bare-string `generate(prompt, ...)` which silently suppressed all extended metrics — corrected in the rerun.

3. **Draft-B's higher acceptance rate does not compensate for its slower forward speed.** The pruned 22L INT8_ASYM model has \~12.4% lower standalone throughput than the full 28L INT4 model, which dominates the TPS outcome.

4. **TTFT is dominated by speculative-batch streaming.** The stream callback fires only after the first draft acceptance/rejection cycle completes (\~9s for Draft-A, \~13s for Draft-B). This is a structural artifact of OV GenAI speculative decoding, not a real user-perceived latency difference at steady state.

5. **RSS is within budget.** Both speculative configs peak at \~12.5–12.6 GB, well within the 15,507 MB RSS budget.

---

## Carry-Forward

| Item | Value |
|------|-------|
| Default draft model | **Draft-A** (Qwen3-0.6B 28L INT4) |
| Draft model path | `models/qwen3-0.6b/openvino-int4-gpu/` |
| Carries to | Tasks 4.2b, 4.3, 4.4, 4.5+ |
| ADR-012 §2.2 draft model status | EVALUATING (pending Tasks 4.3–4.5 completion) |

---

## Artifacts

| Artifact | Path |
|----------|------|
| Evidence JSON | `phase2_gates/evidence/p5_task4_2_draft_model_comparison.json` |
| Benchmark harness (corrected) | `phase2_gates/scripts/run_p5_task4_2_combined.py` |
| Benchmark harness (original buggy) | `phase2_gates/scripts/run_p5_task4_2_draft_comparison.py` |
| Ledger entries | Entry 14 + correction in Entry 15 in `docs/POST_OPERATIONAL_MATURATION_LEDGER.md` |

---

## Correction Note

The original Task 4.2 run (commit `95a3f0a`) contained a bug: `pipeline.generate(prompt, ...)` (bare string input) returns a bare `str` with no `.perf_metrics` or `.extended_perf_metrics` attributes, silently losing acceptance rate, native TPS, and all extended metrics. The corrected harness uses `pipeline.generate([prompt], ...)`, returning `DecodedResults` with full metrics. The disposition (DRAFT_A_WINS) was valid in both runs; the corrected data provides the definitive numbers.
