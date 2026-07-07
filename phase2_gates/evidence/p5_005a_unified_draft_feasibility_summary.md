# P5-005a Unified Draft Feasibility Summary

## Outcome

- Finished UTC: `2026-02-28T04:01:39.302515+00:00`
- Disposition: `QWEN3_14B_WITH_SPEC_DECODING`
- Total tests in matrix: `18`
- Completed: `10`
- Skipped: `8`

## Completed Tests

- T-01: 14B Baseline (tps@512=4.33)
- T-02: 14B + INT8 KV (tps@512=3.51)
- T-03: 14B + INT8 KV + XAttention (tps@512=3.66)
- T-04: 14B Full Optimization (tps@512=6.37)
- T-06: 8B Baseline (tps@512=11.48)
- T-08: 8B Full Optimization (tps@512=7.58)
- T-09: 14B + 0.6B draft GPU (tps@512=13.77)
- T-10: 8B + 0.6B draft GPU (tps@512=21.12)
- T-11: 14B + 1.7B draft GPU (tps@512=10.31)
- T-12: 8B + 1.7B draft GPU (tps@512=10.48)

## Skipped Tests

- T-05: 14B + EAGLE-3 (EAGLE3_DRAFT_NOT_AVAILABLE)
- T-07: 8B + EAGLE-3 (EAGLE3_DRAFT_NOT_AVAILABLE)
- T-13: 14B + 0.6B draft NPU (CROSS_DEVICE_DRAFT_DISABLED_FATAL_NATIVE_ABORT)
- T-14: 14B + 1.7B draft NPU (CROSS_DEVICE_DRAFT_DISABLED_FATAL_NATIVE_ABORT)
- T-15: 8B + 0.6B draft NPU (CROSS_DEVICE_DRAFT_DISABLED_FATAL_NATIVE_ABORT)
- T-16: 8B + 1.7B draft NPU (CROSS_DEVICE_DRAFT_DISABLED_FATAL_NATIVE_ABORT)
- T-17: 14B + 1.7B draft CPU (CPU_FALLBACK_NOT_REQUIRED_NPU_SUPPORTED)
- T-18: 8B + 1.7B draft CPU (CPU_FALLBACK_NOT_REQUIRED_NPU_SUPPORTED)

## Quality Gate Checks

- G-01: PASS — >=8 tps at band 512 in at least one config
- G-02: PASS — Speculative decoding >=1.3x baseline at band 512
- G-03: PASS — Recommended config peak RSS <= 15,507 MB
- G-04: PASS — Recommended config has >=4/5 valid runs across all bands
- G-05: PASS — Both draft sizes captured in completed tests
- G-06: PASS — NPU offload discovery artifact captured
- G-07: PASS — >=3 completed configs with valid band-512 data

