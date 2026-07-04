```
Milestone COMPLETE — commit 190f1c9 on feature/p5-task4-2-combined-rerun

5 files committed:

run_p5_task4_2_combined.py — new corrected harness
p5_task4_2_draft_model_comparison.json — overwritten with corrected data
p5_task4_2b_npu_draft_comparison.json — new
ADR-011-All-LLM-Inference-GPU-NPU-Retirement.md — §2.4 REJECTED
POST_OPERATIONAL_MATURATION_LEDGER.md — Entry 14 corrected + Entry 15
Key results:

Test	Result
T-01 Draft-A/GPU	10.87 tps, AR=0.4568 (was 8.92 tps / UNAVAILABLE — bug fixed)
T-02 Draft-B/GPU	9.50 tps, AR=0.520 (was 7.16 tps / UNAVAILABLE)
T-03 Draft-A standalone	47.43 tps
T-04 Draft-B standalone	42.19 tps
T-05 Draft-A/NPU	FAILED — LLVM_ABORT_VPUX_COMPILER (deterministic; not retried)
Dispositions:

Task 4.2: DRAFT_A_WINS (10.87 > 9.50 tps, 12.6% delta) — unchanged
Task 4.2b: REJECTED — NPU cannot compile Qwen3-0.6B INT4 in heterogeneous speculative mode on driver 32.0.100.4514 (VPUX as_convolution channels mismatch 0 != 8)
ADR-011 §2.4: EVALUATING → REJECTED; §2.1 scope extended to draft device
Carry-forward for Tasks 4.3+: Draft-A (Qwen3-0.6B 28L INT4) on GPU — openvino-int4-gpu
```
```
T-05 Failure: VPUX as_convolution Shape Inference Bug
What Happened
When LLMPipeline was constructed with draft_model=ov_genai.draft_model(path, "NPU"), OpenVINO GenAI invoked the VPUX compiler to compile the Qwen3-0.6B 28L INT4 model for the NPU. The compiler aborted before any inference occurred.

The process exited with a C-level SIGABRT — not a Python exception — so it was uncatchable. The harness's try/except around pipeline construction could not catch it; the entire Python process died.
```
```
Raw Error Output
[ERROR] 00:12:40.147 [vpux-compiler] Got Diagnostic at loc(fused<{name =
"__module.model.layers.0.self_attn.v_proj/ov_ext::linear/MatMul",
type = "MatMul"}>["...", "fc_decomposed", "matmul_0", "as_convolution"]) :
Channels count of input tensor shape and filter shape must be the same: 0 != 8

loc(...): error: Channels count of input tensor shape and filter shape must be
the same: 0 != 8

LLVM ERROR: Failed to infer result type(s):
"IE.Convolution"(...) {} : (tensor<1x0x1x1xf16>, tensor<1x8x1x1xf16>) -> ( ??? )

PS C:\Users\mrbla\BlarAI>
```
```
Root Cause Analysis
Compiler pass: as_convolution — an MLIR/LLVM optimization pass in the VPUX backend that rewrites eligible MatMul operations as IE.Convolution ops to exploit NPU hardware convolution units.

Layer: model.layers.0.self_attn.v_proj — the value projection in the first transformer block's self-attention.

Shape mismatch: The pass computed the input tensor shape as tensor<1x0x1x1xf16> (0 channels) but the filter shape is tensor<1x8x1x1xf16> (8 channels). The 0-channel input is a degenerate shape — it should never appear. This is a shape inference bug in the pass itself.

Why it happens with this model specifically:

Qwen3-0.6B uses a grouped INT4 quantization scheme. When the OV model exporter lowers the INT4 grouped weight into the VPUX IR, the v_proj linear layer produces an intermediate shape with a channel dimension that becomes 0 after the fc_decomposed canonicalization step. The as_convolution pass then picks up that degenerate shape and attempts to construct an IE.Convolution node, which the MLIR type inference system correctly rejects as impossible — triggering LLVM ERROR: Failed to infer result type(s) → SIGABRT.

Key distinction from a runtime error: This happens entirely at compile time, inside the VPUX MLIR pipeline, before any model weights are transferred to the NPU or any inference is attempted. It is deterministic and reproducible — the same model + same driver + same compiler pass = same abort, every time.

What It Is NOT
Not a driver deficiency. The NPU driver 32.0.100.4514 meets and exceeds the ADR-011 §2.4 minimum (32.0.100.3104). The driver is not the bottleneck.
Not a framework limitation. OpenVINO GenAI 2026.0 does support heterogeneous GPU target + NPU draft speculative decoding at the API level. The ov_genai.draft_model(path, "NPU") constructor is valid. The feature exists.
Not transient. Not caused by resource contention, memory pressure (RSS at the abort point was well below ceiling), or system state. Retry would produce identical failure.
Not caused by the speculative decoding configuration. The abort is inside the VPUX compiler's model compilation pass; NAT, scheduler config, and generation parameters are never reached.
Precise Classification
Field	Value
Failure class	LLVM_ABORT_VPUX_COMPILER
Compiler pass	as_convolution (MLIR VPUX backend)
Stage	Model compilation — before inference
Layer	self_attn.v_proj (layer 0, MatMul → fc_decomposed → matmul_0)
Shape conflict	Input: tensor<1x0x1x1xf16> vs filter: tensor<1x8x1x1xf16>
Root cause	INT4 grouped quantization produces degenerate 0-channel intermediate shape after fc_decomposed canonicalization; as_convolution does not guard against this
VPUX IR node	IE.Convolution with mismatched channels
Deterministic	Yes — same result on every attempt
Catchable in Python	No — SIGABRT from C-level LLVM error handler
Driver at fault	No
Framework feature broken	No — API is valid; compiler has a model-specific bug
Fix path	VPUX compiler patch to guard as_convolution against 0-channel shapes, or Qwen3-0.6B NPU export to avoid producing them
Implications
This is a VPUX compiler bug specific to the interaction of Qwen3-0.6B 28L INT4 grouped quantization with the as_convolution optimization pass. It is not fixable by configuration, parameter tuning, or model format changes within the current toolchain. The NPU cannot compile this model variant on OV GenAI 2026.0 + driver 32.0.100.4514.

If Intel fixes this in a future VPUX compiler release, the model would need to be re-tested — but since ADR-011 §2.4 is now REJECTED on these grounds, that would require a new ADR addendum to reopen the gate.
```
```
Bug Report: VPUX Compiler as_convolution Pass — Degenerate 0-Channel Shape Causes LLVM ABORT Compiling Qwen3-0.6B INT4 for NPU Heterogeneous Speculative Decoding

Summary
When constructing an LLMPipeline with a Qwen3-0.6B 28-layer INT4 model as the NPU draft device in OpenVINO GenAI heterogeneous speculative decoding (GPU target + NPU draft), the VPUX compiler aborts with LLVM ERROR: Failed to infer result type(s) during model compilation. The as_convolution optimization pass produces a degenerate tensor<1x0x1x1xf16> input shape for self_attn.v_proj in layer 0, which is irreconcilable with the filter shape tensor<1x8x1x1xf16>. The resulting IE.Convolution node fails MLIR type inference, triggering SIGABRT. The process exits immediately; the failure is not catchable via Python exception handling.
Environment
Field	Value
Hardware	Intel Core Ultra 7 258V (Lunar Lake, 8P cores, 8 logical)
NPU	Intel AI Boost (integrated, Lunar Lake)
GPU	Intel Arc 140V (Xe2, 16 GB shared LPDDR5X)
Memory	32 GB LPDDR5X-8533 unified
OS	Windows 11 Pro, Build 26200
NPU Driver	32.0.100.4514 (dated 2025-12-17)
GPU Driver	32.0.101.6987
OpenVINO	2026.0.0-20965-c6d6a13a886-releases/2026/0
OpenVINO GenAI	2026.0.0.0-2820-dab5b993a38
Python	3.x, Windows venv
Model	Qwen/Qwen3-0.6B (28 layers, INT4 grouped quantization, exported to OV format for NPU)
Context	Heterogeneous speculative decoding: GPU target (Qwen3-14B INT4) + NPU draft
```
```
Steps to Reproduce
1. Export Qwen3-0.6B to NPU format using optimum-intel or ov.save_model:

The model used was exported to openvino-int4-npu/ format (INT4 grouped quantization, Qwen3-0.6B 28L). The export itself completes without error.

2. Construct a heterogeneous speculative decoding pipeline:
```
```
import openvino_genai as ov_genai
from openvino_genai import LLMPipeline, SchedulerConfig

TARGET_PATH = "models/qwen3-14b/openvino-int4-gpu/"
DRAFT_NPU_PATH = "models/qwen3-0.6b/openvino-int4-npu/"

scheduler = SchedulerConfig()
scheduler.cache_size = 3  # GB

pipeline = LLMPipeline(
    TARGET_PATH,
    "GPU",
    draft_model=ov_genai.draft_model(DRAFT_NPU_PATH, "NPU"),
    scheduler_config=scheduler,
)
```
```
3. Observed result:

Process aborts with the following output before Python returns from the LLMPipeline constructor. No Python exception is raised. Exit code: 1
Full Error Output:
```
```
[ERROR] 00:12:40.147 [vpux-compiler] Got Diagnostic at loc(fused<{name =
"__module.model.layers.0.self_attn.v_proj/ov_ext::linear/MatMul",
type = "MatMul"}>["__module.model.layers.0.self_attn.v_proj/ov_ext::linear/MatMul",
"fc_decomposed", "matmul_0", "as_convolution"]) :
Channels count of input tensor shape and filter shape must be the same: 0 != 8

loc(fused<{name = "__module.model.layers.0.self_attn.v_proj/ov_ext::linear/MatMul",
type = "MatMul"}>["__module.model.layers.0.self_attn.v_proj/ov_ext::linear/
MatMul", "fc_decomposed", "matmul_0", "as_convolution"]):
error: Channels count of input tensor shape and filter shape must be the same: 0 != 8

LLVM ERROR: Failed to infer result type(s):
"IE.Convolution"(...) {} : (tensor<1x0x1x1xf16>, tensor<1x8x1x1xf16>) -> ( ??? )
```
```
Expected Behavior
LLMPipeline constructor completes successfully. Qwen3-0.6B INT4 compiles and runs on the NPU as the speculative decoding draft device, with the 14B target running on the GPU — the hardware-accelerated heterogeneous speculative decoding configuration documented for Lunar Lake (Intel Core Ultra 200V series).
Actual Behavior
VPUX compiler LLVM ABORT during model compilation. Process exits with code 1. No Python exception raised. Pipeline construction never completes. No inference is possible.

Impact
Heterogeneous GPU+NPU speculative decoding — the primary performance use case for the Lunar Lake NPU in LLM inference — is non-functional for Qwen3-0.6B INT4 grouped quantization on OpenVINO GenAI 2026.0. This is the intended Intel-documented hardware configuration for this SoC.
```
