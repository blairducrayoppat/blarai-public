# P5-005a Full Rerun Summary

## Outcome

- Run status: **Completed**
- Finished UTC: `2026-02-28T04:01:39.302515+00:00`
- Final disposition: **QWEN3_14B_WITH_SPEC_DECODING**
- Evidence artifact: `phase2_gates/evidence/p5_005a_unified_draft_feasibility_matrix.json`

## Test Completion Matrix

- Total scheduled tests: **18**
- Completed: **10**
- Skipped: **8**

### Completed

T-01, T-02, T-03, T-04, T-06, T-08, T-09, T-10, T-11, T-12

### Skipped + Reason

- T-05: `EAGLE3_DRAFT_NOT_AVAILABLE`
- T-07: `EAGLE3_DRAFT_NOT_AVAILABLE`
- T-13: `CROSS_DEVICE_DRAFT_DISABLED_FATAL_NATIVE_ABORT`
- T-14: `CROSS_DEVICE_DRAFT_DISABLED_FATAL_NATIVE_ABORT`
- T-15: `CROSS_DEVICE_DRAFT_DISABLED_FATAL_NATIVE_ABORT`
- T-16: `CROSS_DEVICE_DRAFT_DISABLED_FATAL_NATIVE_ABORT`
- T-17: `CPU_FALLBACK_NOT_REQUIRED_NPU_SUPPORTED`
- T-18: `CPU_FALLBACK_NOT_REQUIRED_NPU_SUPPORTED`

## Why EAGLE-3 Tests Skipped

The EAGLE-3 acquisition artifact shows both targets failed conversion with disposition
`FRAMEWORK_NOT_SUPPORTED`:

- 8B target repo: `RedHatAI/Qwen3-8B-speculator.eagle3`
- 14B target repo: `AngelSlim/Qwen3-14B_eagle3`

Observed failure pattern in conversion attempts:

1. Direct raw draft load via `ov_genai.draft_model(...)` failed because raw downloads did not
   include OpenVINO IR files (`openvino_model.xml/.bin`).
2. `optimum-cli export openvino` failed with
   `RuntimeError: Cannot infer the task from a local directory yet, please specify the task manually`.

This left EAGLE-3 models unavailable to the benchmark harness, which then correctly skipped
T-05 and T-07.

## Why So Many Other Tests Were Skipped

- T-13..T-16 are intentionally blocked by an unconditional guard:
  `CROSS_DEVICE_DRAFT_DISABLED_FATAL_NATIVE_ABORT`.
- T-17..T-18 are intentionally skipped when NPU cross-device support is already detected
  (`CPU_FALLBACK_NOT_REQUIRED_NPU_SUPPORTED`).

These are harness policy outcomes, not runtime crashes.

## Missing Summary File Root Cause

The benchmark harness writes a JSON evidence matrix but does **not** generate a standalone
human-readable summary markdown file by default. This file is that missing summary.

## Recommended Follow-up (If Required)

1. Add a post-run summary writer to `run_p5_feasibility_005a.py` so each run always emits
   `phase2_gates/evidence/p5_005a_unified_draft_feasibility_summary.md` automatically.
2. For EAGLE-3, add fallback conversion path that passes explicit task (e.g. `--task text-generation`)
   and supports non-standard speculator packaging before final `FRAMEWORK_NOT_SUPPORTED`.
3. If you want T-13..T-16 coverage, replace unconditional cross-device skip with a feature flag
   and run behind an explicit risk-accepted mode.
