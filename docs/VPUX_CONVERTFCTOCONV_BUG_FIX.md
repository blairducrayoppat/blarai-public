# VPUX Compiler ConvertFCToConv Zero-Dim Guard — Bug Report and Fix

**Date discovered:** 2026-03-02 (BlarAI Task 4.2b)
**Date fixed:** 2026-03-03 (Option A guard); 2026-03-04 (Option B `addDynamicallyLegalOp` + PR #2 defense-in-depth)
**Status:** Two patches submitted upstream as PRs [#265](https://github.com/openvinotoolkit/npu_compiler/pull/265) and [#266](https://github.com/openvinotoolkit/npu_compiler/pull/266) — awaiting review
**Upstream repo:** `openvinotoolkit/npu_compiler`
**PR #1 Branch:** `fix/convert-fc-to-conv-zero-dim-guard` @ `956d5e65`
**PR #2 Branch:** `fix/unroll-fc-zero-dim-guard` @ `2e75db65`
**Base:** `develop` @ `e0af5371` (`npu_ud_2026_08_rc2`)

---

## 1. Summary

The VPUX compiler's `ConvertFCToConv` MLIR pass crashes with `LLVM ERROR: Failed to infer result type(s)` (SIGABRT) when it encounters an `IE::FullyConnectedOp` whose channel dimension is zero. This occurs during model compilation — before any inference — and kills the host process immediately. The failure is deterministic and uncatchable from Python.

The root cause is a multi-pass interaction: per-group INT4 quantization decomposition (via `UnrollFullyConnected` / `fc_decomposed` canonicalization) produces FC ops with zero-channel dimensions (`group_size=128` on Qwen3-0.6B). `ConvertFCToConv` unconditionally marks all `IE::FullyConnectedOp` as illegal via `addIllegalOp`, then `FullyConnectedOpConverter::matchAndRewrite()` reshapes 2-D FC operands to 4-D `{N, C, 1, 1}` without validating `C > 0`. The resulting `tensor<Nx0x1x1>` fails `IE::ConvolutionOp` type inference, triggering a process-killing `abort()`.

The fix uses `addDynamicallyLegalOp<IE::FullyConnectedOp>` with a shape predicate to exempt zero-dim FC ops from the conversion requirement. These ops remain as `IE::FullyConnectedOp` in the IR — no crash, no `failed to legalize`. A defense-in-depth guard in `matchAndRewrite()` provides belt-and-suspenders protection. A second patch adds a guard in `UnrollFullyConnected::splitLeftInput` to prevent zero-dim shapes from propagating through unrolled sub-FCs.

---

## 2. Discovery Context (BlarAI Project)

### 2.1 How the Bug Was Encountered

During BlarAI Phase 5 Task 4.2b (NPU Draft Device Comparison), the project attempted heterogeneous speculative decoding with:

- **Target model:** Qwen3-14B INT4 on GPU (Arc 140V)
- **Draft model:** Qwen3-0.6B 28-layer INT4 on NPU (Intel AI Boost, Lunar Lake)

The `LLMPipeline` constructor invoked the VPUX compiler to compile the draft model for NPU. The compiler aborted during the `ConvertFCToConv` pass at the `self_attn.v_proj` linear layer in transformer block 0.

### 2.2 Observed Error Output

```
[ERROR] 00:12:40.147 [vpux-compiler] Got Diagnostic at loc(fused<{name =
"__module.model.layers.0.self_attn.v_proj/ov_ext::linear/MatMul",
type = "MatMul"}>["...", "fc_decomposed", "matmul_0", "as_convolution"]) :
Channels count of input tensor shape and filter shape must be the same: 0 != 8

loc(...): error: Channels count of input tensor shape and filter shape must be
the same: 0 != 8

LLVM ERROR: Failed to infer result type(s):
"IE.Convolution"(...) {} : (tensor<1x0x1x1xf16>, tensor<1x8x1x1xf16>) -> ( ??? )
```

### 2.3 Reproduction Code

```python
import openvino_genai as ov_genai
from openvino_genai import LLMPipeline, SchedulerConfig

TARGET_PATH = "models/qwen3-14b/openvino-int4-gpu/"
DRAFT_NPU_PATH = "models/qwen3-0.6b/openvino-int4-npu/"

scheduler = SchedulerConfig()
scheduler.cache_size = 3  # GB

# This line triggers the VPUX compiler crash:
pipeline = LLMPipeline(
    TARGET_PATH,
    "GPU",
    draft_model=ov_genai.draft_model(DRAFT_NPU_PATH, "NPU"),
    scheduler_config=scheduler,
)
```

### 2.4 Environment

| Field | Value |
|-------|-------|
| Hardware | Intel Core Ultra 7 258V (Lunar Lake) |
| NPU | Intel AI Boost (integrated, Lunar Lake) |
| GPU | Intel Arc 140V (Xe2, 16 GB shared LPDDR5X) |
| Memory | 32 GB LPDDR5X-8533 unified |
| OS | Windows 11 Pro, Build 26200 |
| NPU Driver | 32.0.100.4514 (2025-12-17) |
| GPU Driver | 32.0.101.6987 |
| OpenVINO | 2026.0.0-20965-c6d6a13a886-releases/2026/0 |
| OpenVINO GenAI | 2026.0.0.0-2820-dab5b993a38 |
| Model | Qwen/Qwen3-0.6B (28 layers, INT4 grouped quantization) |

### 2.5 Project Impact

- **Ledger Entry 15** (2026-03-02): Task 4.2b disposition — `REJECTED`
- **ADR-011 §2.4:** `EVALUATING` → `REJECTED` — NPU draft device not viable
- **ADR-011 §2.1:** Scope extended — GPU is sole viable device for all LLM inference including draft
- **Carry-forward:** Draft model runs on GPU for all subsequent Task 4 profiles

---

## 3. Root Cause Analysis

### 3.1 Affected Pass

**File:** `src/vpux_compiler/src/dialect/IE/transforms/passes/convert_fc_to_conv.cpp`
**Pass:** `ConvertFCToConv`
**Pattern:** `FullyConnectedOpConverter` (inherits `mlir::OpRewritePattern<IE::FullyConnectedOp>`)

This pass rewrites `IE::FullyConnectedOp` as `IE::ConvolutionOp` to exploit NPU hardware convolution units. It reshapes 2-D FC operands `tensor<NxC>` to 4-D `tensor<NxCx1x1>`, creates a 1×1 convolution, then reshapes the output back to 2-D.

### 3.2 The Defect

The `matchAndRewrite()` method had no validation of operand shapes before performing the reshape. The pre-fix code was:

```cpp
const auto inputShape = mlir::cast<vpux::NDTypeInterface>(
    origOp.getInput().getType()).getShape().raw();

const std::array<int64_t, 4> newInShape = {inputShape[0], inputShape[1], 1, 1};
// ... reshape and create IE::ConvolutionOp ...

const auto weightsShape = mlir::cast<vpux::NDTypeInterface>(
    origOp.getWeights().getType()).getShape().raw();
const std::array<int64_t, 4> newWeightsShape = {weightsShape[0], weightsShape[1], 1, 1};
```

When `inputShape[1]` is `0` (or any dimension is zero/negative), the created `IE::ConvolutionOp` receives `tensor<1x0x1x1xf16>` as input and `tensor<Kx0x1x1xf16>` (or mismatched) as filter. The convolution's type inference correctly rejects this impossible shape — but does so via `LLVM ERROR`, which calls `llvm::report_fatal_error()` → `abort()`.

### 3.3 Trigger Condition

Per-group INT4 quantization with `group_size=128` (as used by Qwen3-0.6B) causes the upstream `fc_decomposed` canonicalization to produce `IE::FullyConnectedOp` nodes where the channel dimension is zero. This is a degenerate intermediate shape that should not reach the reshape logic.

### 3.4 Classification

| Field | Value |
|-------|-------|
| Failure class | `LLVM_ABORT_VPUX_COMPILER` |
| Compiler pass | `ConvertFCToConv` (`as_convolution` location tag) |
| Stage | Model compilation — before inference |
| Shape conflict | Input `tensor<1x0x1x1xf16>` vs filter `tensor<1x8x1x1xf16>` |
| Deterministic | Yes |
| Catchable in Python | No — SIGABRT from LLVM error handler |
| Driver at fault | No |
| Framework API broken | No — the API is valid; compiler has a model-specific bug |

---

## 4. The Fix

### 4.1 Approach (Option B — `addDynamicallyLegalOp`)

The original Option A added a guard in `matchAndRewrite()` that converted the crash into `mlir::failure()`. This prevented the abort but produced a `failed to legalize` error because `addIllegalOp<IE::FullyConnectedOp>()` still required all FC ops to be converted.

Option B replaces `addIllegalOp` with `addDynamicallyLegalOp<IE::FullyConnectedOp>` using a shape predicate. Zero-dim FC ops are declared **legal** (exempt from conversion) and survive the pass unchanged. Valid FC ops remain **illegal** and are converted to `IE::ConvolutionOp` as before. This is the same pattern already used by `AdjustNCEOpsWithI32Inputs` in the codebase (`adjust_nce_ops_with_i32_inputs.cpp` lines 118-124).

A defense-in-depth guard is retained in `matchAndRewrite()` as belt-and-suspenders protection.

### 4.2 Patched Code — `safeRunOnFunc()` (Primary Fix)

```cpp
void ConvertFCToConvPass::safeRunOnFunc() {
    auto& ctx = getContext();

    mlir::ConversionTarget target(ctx);
    target.addLegalDialect<Const::ConstDialect>();
    target.addLegalDialect<IE::IEDialect>();

    // Exempt FC ops with degenerate shapes from the conversion requirement.
    // Per-group INT4 quantization can produce intermediate FC ops where the
    // channel dimension is zero — these cannot be reshaped to 4-D for
    // convolution and must be allowed to survive this pass unchanged.
    // See openvinotoolkit/openvino#34450.
    target.addDynamicallyLegalOp<IE::FullyConnectedOp>([](IE::FullyConnectedOp op) -> bool {
        const auto inShape = mlir::cast<vpux::NDTypeInterface>(
            op.getInput().getType()).getShape().raw();
        const auto wShape = mlir::cast<vpux::NDTypeInterface>(
            op.getWeights().getType()).getShape().raw();

        // Non-rank-2 operands cannot be reshaped to {N,C,1,1} — exempt.
        if (inShape.size() != 2 || wShape.size() != 2)
            return true;   // legal → exempt

        // Zero or negative dims would produce tensor<Nx0x1x1> — exempt.
        for (auto d : inShape)
            if (d <= 0) return true;
        for (auto d : wShape)
            if (d <= 0) return true;

        return false;  // illegal → must be converted to ConvolutionOp
    });

    // ... remainder unchanged ...
}
```

### 4.2.1 Patched Code — `matchAndRewrite()` (Defense-in-Depth)

```cpp
mlir::LogicalResult ConvertFCToConvPass::FullyConnectedOpConverter::matchAndRewrite(
        IE::FullyConnectedOp origOp, mlir::PatternRewriter& rewriter) const {
    const auto inputShape = mlir::cast<vpux::NDTypeInterface>(
        origOp.getInput().getType()).getShape().raw();
    const auto weightsShape = mlir::cast<vpux::NDTypeInterface>(
        origOp.getWeights().getType()).getShape().raw();

    // Defense-in-depth: reject FC ops with degenerate shapes.
    // The addDynamicallyLegalOp predicate in safeRunOnFunc() already
    // exempts these from conversion; this guard is belt-and-suspenders
    // for robustness.
    if (inputShape.size() != 2 || weightsShape.size() != 2) {
        return mlir::failure();
    }
    for (auto dim : inputShape) {
        if (dim <= 0) return mlir::failure();
    }
    for (auto dim : weightsShape) {
        if (dim <= 0) return mlir::failure();
    }

    // ... remainder of reshape + convolution creation unchanged ...
}
```

### 4.3 Changes Summary — PR #1 (`fix/convert-fc-to-conv-zero-dim-guard`)

| File | Change |
|------|--------|
| `convert_fc_to_conv.cpp` | `addIllegalOp` → `addDynamicallyLegalOp` with shape predicate; defense-in-depth guard in `matchAndRewrite()` |
| `convert_fc_to_conv_zero_dim_guard.mlir` | Positive regression test — zero-dim FC survives the pass |

### 4.3.1 Changes Summary — PR #2 (`fix/unroll-fc-zero-dim-guard`)

| File | Change |
|------|--------|
| `unroll_fully_connected.cpp` | +18 lines: zero-dim guard in `splitLeftInput` rejects degenerate shapes before unrolled sub-FCs are created |

### 4.4 Behavioral Change (Option B vs. Original Option A)

| | Before (crash) | Option A (guard-only) | Option B (current) |
|---|--------|--------|--------|
| Zero-dim FC op | `LLVM ERROR` → `abort()` → process death | `mlir::failure()` → `failed to legalize` | Exempted as legal → survives as `IE::FullyConnectedOp` |
| Valid FC op | Converted to `IE::ConvolutionOp` | Unchanged | Unchanged |
| Process survival | No | Yes | Yes |
| Pass result | N/A (crash) | Pass failure (non-zero exit) | Pass succeeds cleanly |
| Error catchable | No (SIGABRT) | Yes (MLIR diagnostic) | No error produced |

---

## 5. Regression Test

**File:** `tests/lit/NPU/dialect/IE/passes/convert_fc_to_conv_zero_dim_guard.mlir`

```mlir
//
// Copyright (C) 2022-2026 Intel Corporation.
// SPDX-License-Identifier: Apache-2.0
//

// Regression test: ConvertFCToConv must not crash (SIGABRT) when an
// IE.FullyConnected has a zero-sized channel dimension.  This can occur
// when per-group INT4 quantization decomposition produces intermediate
// FC operations with degenerate shapes.
//
// With the addDynamicallyLegalOp predicate, zero-dim FC ops are declared
// legal and survive the pass unchanged — no crash, no "failed to legalize".

// RUN: vpux-opt --split-input-file --init-compiler="vpu-arch=%arch%" --convert-fc-to-conv %s | FileCheck %s
// REQUIRES: arch-NPU37XX || arch-NPU40XX || arch-NPU50XX

// CHECK-LABEL: @PreserveZeroDimFC
// CHECK: IE.FullyConnected
func.func @PreserveZeroDimFC(%arg0: tensor<1x0xf16>) -> tensor<1x64xf16> {
    %weights = const.Declare tensor<64x0xf16> = dense<0.0> : tensor<64x0xf16>
    %0 = IE.FullyConnected(%arg0, %weights) : tensor<1x0xf16>, tensor<64x0xf16> -> tensor<1x64xf16>
    return %0 : tensor<1x64xf16>
}
```

**Test logic (Option B — positive test):**
- `vpux-opt ...` — expects **zero exit** (pass succeeds)
- `FileCheck` — confirms `IE.FullyConnected` survives in the output IR (not converted, not error)
- `REQUIRES: arch-NPU37XX || arch-NPU40XX || arch-NPU50XX` — matches existing test conventions

**Change from Option A:** The old test used `not vpux-opt ...` and checked for `failed to legalize`. Option B makes the pass succeed cleanly — zero-dim FCs are exempted, not rejected.

---

## 6. Build and Validation Environment

The fix was built and validated from source using:

| Component | Version / Commit |
|-----------|-----------------|
| OpenVINO | `4922c4955f9d5c457cf9d4ebbbc8bf6502167ada` |
| NPU Compiler | `fix/convert-fc-to-conv-zero-dim-guard` (develop + patch) |
| LLVM | Intel staging fork @ `8d12776e7faf75fb6fa9db1734d5728ef2f6acf2` |
| CMake | 3.31.7 (portable) |
| Ninja | 1.13.2 |
| MSVC | 19.44.35222 x64 |
| ccache | 4.12.3 |
| OS | Windows 11 Pro |

**Build configuration:**
```
cmake --preset developer-build-release \
  -DENABLE_NPU_MICRO_BENCHMARKS=OFF \
  -DENABLE_FUNCTIONAL_TESTS=OFF \
  -DENABLE_TESTS=OFF \
  -DENABLE_PRIVATE_TESTS=OFF \
  -DLLVM_ENABLE_DIA_SDK=OFF
```

**Build target:** `vpux-opt` — 6,425 ninja targets, produced 97.3 MB binary.

**DLL dependencies for runtime:** `openvino.dll` (`openvino/bin/intel64/Release/`), `tbb12.dll` (`openvino/temp/Windows_AMD64/tbb/bin/`).

---

## 7. Scope and Limitations

### 7.1 What the Fix Does

**PR #1 (`ConvertFCToConv`):** Uses `addDynamicallyLegalOp<IE::FullyConnectedOp>` with a shape predicate to exempt zero-dim FC ops from the illegality constraint. These ops survive the pass as `IE::FullyConnectedOp` — no crash, no conversion error. Valid FC ops remain illegal and are converted to `IE::ConvolutionOp` as before. A defense-in-depth guard in `matchAndRewrite()` provides redundant protection.

**PR #2 (`UnrollFullyConnected`):** Adds a guard in `splitLeftInput()` that rejects FC ops with zero-dim batch or weight dimensions before unrolled sub-FCs are created. This prevents degenerate shapes from propagating through the unrolling logic.

### 7.2 What the Fix Does NOT Do

This fix does **not** make Qwen3-0.6B INT4 compilable for NPU. The zero-dim FC ops survive `ConvertFCToConv` unchanged, but downstream passes may still encounter issues with these degenerate shapes. The model compilation may still fail at a later pass, but through a normal error path instead of a process-killing abort.

### 7.3 Upstream Fix Paths (Beyond This Patch)

For full NPU compilation of per-group INT4 models, the VPUX team would need to address either:
1. **Upstream decomposition fix:** The `fc_decomposed` canonicalization (or `UnrollGroupQuantize`) should not produce zero-channel FC ops as intermediate shapes. This is the root cause but involves complex multi-pass interactions.
2. **Downstream handling:** Passes after `ConvertFCToConv` need to handle unconverted `IE::FullyConnectedOp` nodes gracefully. With Option B, these ops now survive in the IR.

### 7.4 Impact on ADR-011 §2.4 (NPU Draft Device)

The fix changes the failure mode but not the outcome. ADR-011 §2.4 `REJECTED` disposition remains valid — the NPU cannot run Qwen3-0.6B INT4 as a speculative decoding draft model. Even with the crash prevented, the model likely fails at later compilation stages.

---

## 8. Upstream PRs

### 8.1 PR #1 — ConvertFCToConv (`addDynamicallyLegalOp`)

- **Repository:** `openvinotoolkit/npu_compiler`
- **Target branch:** `develop`
- **Source branch:** `fix/convert-fc-to-conv-zero-dim-guard`
- **Commit:** `956d5e65`
- **Scope:** `convert_fc_to_conv.cpp` + `convert_fc_to_conv_zero_dim_guard.mlir`
- **PR description:** `C:\Users\mrbla\npu-compiler-fix\npu_compiler\PR_DESCRIPTION.md`

### 8.2 PR #2 — UnrollFullyConnected (Defense-in-Depth Guard)

- **Repository:** `openvinotoolkit/npu_compiler`
- **Target branch:** `develop`
- **Source branch:** `fix/unroll-fc-zero-dim-guard` (based on PR #1 commit)
- **Commit:** `2c4f58cc`
- **Scope:** `unroll_fully_connected.cpp` (+18 lines in `splitLeftInput`)
- **Rationale:** Different pass, different file, different failure vector — submitted separately to keep review scope minimal.

### 8.3 Related Issues

- **Primary:** https://github.com/openvinotoolkit/openvino/issues/34450
- **Related:** https://github.com/openvinotoolkit/openvino.genai/issues/3429, #30683, #28171, #27965, #30316

### 8.4 Submission Steps

```powershell
cd C:\Users\mrbla\npu-compiler-fix\npu_compiler

# PR #1
git remote add fork https://github.com/<username>/npu_compiler.git
git push fork fix/convert-fc-to-conv-zero-dim-guard
# Open PR on GitHub against openvinotoolkit/npu_compiler develop

# PR #2
git push fork fix/unroll-fc-zero-dim-guard
# Open second PR on GitHub against openvinotoolkit/npu_compiler develop
```

---

## 9. Cross-References (BlarAI Project)

| Artifact | Location |
|----------|----------|
| Bug discovery evidence | `phase2_gates/evidence/p5_task4_2b_npu_draft_comparison.json` |
| Bug discovery harness | `phase2_gates/scripts/run_p5_task4_2_combined.py` (T-05 section) |
| Ledger — bug recorded | `docs/POST_OPERATIONAL_MATURATION_LEDGER.md` Entry 15 |
| Ledger — fix recorded | `docs/POST_OPERATIONAL_MATURATION_LEDGER.md` Entry 19 |
| ADR disposition | `docs/adrs/ADR-011-All-LLM-Inference-GPU-NPU-Retirement.md` §2.4 |
| Task 4.2b specification | `docs/P5_TASK4_PRODUCTION_CONFIG_FEASIBILITY.md` §4.2b |
| Fix workspace | `C:\Users\mrbla\npu-compiler-fix\npu_compiler` |
| PR #1 branch | `fix/convert-fc-to-conv-zero-dim-guard` @ `956d5e65` |
| PR #2 branch | `fix/unroll-fc-zero-dim-guard` @ `2c4f58cc` |
| PR #1 description | `C:\Users\mrbla\npu-compiler-fix\npu_compiler\PR_DESCRIPTION.md` |
| PR #2 description | `C:\Users\mrbla\npu-compiler-fix\npu_compiler\PR2_DESCRIPTION.md` |
| PR #1 (GitHub) | [openvinotoolkit/npu_compiler#265](https://github.com/openvinotoolkit/npu_compiler/pull/265) |
| PR #2 (GitHub) | [openvinotoolkit/npu_compiler#266](https://github.com/openvinotoolkit/npu_compiler/pull/266) |
| Validation evidence | `phase2_gates/evidence/vpux_fix_validation.json` |

### Architectural Impact — Heterogeneous Speculative Decoding

The current production configuration runs both target (Qwen3-14B) and draft (Qwen3-0.6B)
models on GPU because the VPUX compiler crash prevents NPU compilation of the draft model.
This is not the architecturally optimal configuration for Lunar Lake: the intended design
is heterogeneous speculative decoding with the NPU running the draft model concurrently on
NCE while the GPU processes the target model's KV cache, using zero-copy LPDDR5X handoff.

**If both upstream PRs merge** (or an equivalent fix ships in an OpenVINO release) **and**
OpenVINO GenAI exposes per-model device placement in the `draft_model()` API, the following
BlarAI governance documents should be re-evaluated:

| Document | Section | Action |
|----------|---------|--------|
| ADR-011 | §2.4 (Heterogeneous Spec-Decode) | Re-benchmark NPU draft vs GPU draft; amend REJECTED → ADOPTED if NPU wins |
| ADR-012 | §2.2 (Draft model row) | Update device from GPU to NPU if re-benchmark confirms |
| ADR-012 | §3.3 (Residual Risks) | Close heterogeneous spec-decode risk entry |
| `shared/constants.py` | Draft model path | Point to NPU-compiled variant |
