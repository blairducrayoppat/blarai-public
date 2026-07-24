---
title: PR266_RESPONSE_DRAFT
status: archived
area: portfolio
---

# PR #266 Response Draft

> **Target:** Post as a single consolidated comment on [npu_compiler PR #266](https://github.com/openvinotoolkit/npu_compiler/pull/266)
> **Addresses:** DariaMityagina (LIT test request) + andrey-golubev (root cause / architectural direction)

---

## Response Text (copy-paste below the line)

---

Thank you both for the thorough review.

### LIT test added

@DariaMityagina — A LIT test has been added in this push:

**`tests/lit/NPU/dialect/IE/passes/unroll_fully_connected_zero_dim_guard.mlir`**

The test constructs the same `FakeQuantize → Concat → AffineReshape → Transpose → FullyConnected` pattern used by the existing `@UnrollMatMul` tests, but with a **zero batch dimension** (`tensor<0x3072xf32>`). The `inputChannels` (3072) is evenly divisible by `numChunks` (3), so it passes the existing divisibility check at line 474. The new guard catches `lhsShape[Dim(0)] <= 0` and returns `mlir::failure()`, preserving the entire IR subgraph unchanged.

I verified empirically (against the unpatched `upstream/develop` binary) that **without this guard, the pass unrolls the zero-batch FC into 3 degenerate sub-FCs**:

```
IE.Slice %arg0 [0, 0] [0, 1024] : tensor<0x3072xf32> to tensor<0x1024xf32>
IE.FullyConnected(%6, %9) : tensor<0x1024xf32>, tensor<4096x1024xf32> -> tensor<0x4096xf32>
```

Three such sub-FCs are created and accumulated via `IE.Add`, propagating the degenerate shape downstream.

### Root cause investigation — what I know vs. what I don't

@andrey-golubev — I accept the architectural direction: fixing the source that produces zero-dim shapes is the correct long-term solution, and this guard is defense-in-depth.

**What I can confirm:**

1. The crash location trail from the original bug is `fc_decomposed → matmul_0 → as_convolution`, meaning `GroupWisePatternRewriter` (in `InitialLowPrecisionTransformations`) created the FC, then `UnrollFullyConnected` processed it, then `ConvertFCToConv` crashed.

2. The pipeline order (verified from `NPU40XX/pipelines.cpp`): `InitialLowPrecisionTransformations` runs **early** → dozens of intermediate passes → `UnrollGroupQuantize` → `UnrollFullyConnected` → `ConvertFCToConv`.

3. `GroupWisePatternRewriter` itself (in `decompose_multi_zp_quantization_pattern.cpp`) has a `VPUX_THROW_UNLESS` at line 218 that would **crash** (not produce zero-dim) on invalid inputs at its own execution time. This means the zero-dim is likely **not present when GroupWisePatternRewriter runs**, but is introduced by one of the dozens of intermediate passes between `InitialLowPrecisionTransformations` and `UnrollFullyConnected`.

**What I cannot determine externally:**

I don't have access to an IR dump from a full Qwen3-0.6B INT4 compilation on NPU40XX. Without intermediate IR snapshots, I cannot identify which specific pass between `InitialLowPrecisionTransformations` and `UnrollFullyConnected` introduces the zero-dim shape.

**Request:** Could you point me to the recommended way to dump IR between passes in the NPU pipeline? Something like `--mlir-print-ir-after-all` or a pipeline-specific flag? With that, I can compile Qwen3-0.6B INT4, capture the intermediate IR, identify the pass that introduces the zero-dim, and file a targeted fix at the source.

In the meantime, this guard prevents the degenerate shapes from propagating into unrolled sub-FCs and eventually crashing in `ConvertFCToConv`.

---

## Checklist before posting

- [ ] Push the LIT test commit to the PR #266 branch first
- [ ] Verify the LIT test file appears in the PR diff on GitHub
- [ ] Post the response
- [ ] Optionally add a short cross-reference on PR #265 accepting architectural direction
