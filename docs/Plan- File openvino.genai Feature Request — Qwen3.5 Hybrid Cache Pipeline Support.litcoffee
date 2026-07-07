Plan: File openvino.genai Feature Request — Qwen3.5 Hybrid Cache Pipeline Support

Context
Opportunity 3 from docs/QWEN35_CONTRIBUTION_GUIDE.md. Intel is actively building hybrid-cache pipeline support in openvino.genai (PR #3359, milestone 2026.1) but has no Qwen3.5-specific work planned. The feature request validates Qwen3.5 fits the in-progress infrastructure and formally puts it on Intel's radar for 2026.1.

Step 1: Create the feature request markdown file
File to create: c:\Users\mrbla\BlarAI\docs\GENAI_FEATURE_REQUEST_QWEN35.md
Full content is in the section below. Nothing else needs to be done in code.

Step 2: Submit on GitHub
Navigate to: https://github.com/openvinotoolkit/openvino.genai/issues/new

1. Click "Get started" next to "Bug report" — if there is no template chooser, you will land directly on a blank issue form.
2. Title field: paste exactly:
[Feature Request] Qwen3.5 hybrid cache pipeline support (conv_state + recurrent_state + KV-cache)
3. Body field: paste the full contents of docs/GENAI_FEATURE_REQUEST_QWEN35.md
4. Labels: Click the gear icon next to "Labels" on the right sidebar. Type LLM and select "category: LLM" if available. Also select "feature request" if available.
5. Leave Assignees, Projects, and Milestone blank — Intel triagers will assign.
6. Click "Submit new issue"

Feature Request Content
<CONTENT>
## Summary

Add `LLMPipeline` and `ContinuousBatchingPipeline` support for **Qwen3.5** models
(`model_type: qwen3_5`, `qwen3_5_text`), which use a hybrid attention architecture
combining GatedDeltaNet linear attention layers (recurrent state) with standard GQA
full attention layers (KV-cache). This is a validation and test-coverage request
against the hybrid pipeline infrastructure already being built in PR #3359.

---

## Background

### Model Architecture

Qwen3.5 is a **hybrid SSM+attention model** with 24 total layers in the text
sub-model (`qwen3_5_text`), arranged in a 3:1 linear-to-full ratio:

`[linear_attention, linear_attention, linear_attention, full_attention] × 6 blocks`

The 24 linear attention layers use **GatedDeltaNet** recurrent cells. The 8 full
attention layers use standard **GQA** with `partial_rotary_factor=0.25`.

Concrete numbers for Qwen3.5-0.8B (`Qwen/Qwen3.5-0.8B`):

| Config Field | Value | Meaning |
|---|---|---|
| `model_type` | `qwen3_5` / `qwen3_5_text` | Model family identifier |
| `num_hidden_layers` | 24 | Total layers |
| `layer_types` | 18× `linear_attention`, 6× `full_attention` | Hybrid layout |
| `full_attention_interval` | 4 | 1 full attention per 4 layers |
| `linear_conv_kernel_dim` | 4 | `conv_state` window size |
| `linear_key_head_dim` | 128 | `recurrent_state` key dimension |
| `linear_value_head_dim` | 128 | `recurrent_state` value dimension |
| `linear_num_key_heads` | 16 | `recurrent_state` head count |
| `num_key_value_heads` | 2 | GQA ratio for full attention layers |
| `head_dim` | 256 | KV-cache head dimension |
| `mamba_ssm_dtype` | `float32` | SSM states must remain FP32 |

---

### OpenVINO IR Tensor Format (from optimum-intel PR #1634)

[huggingface/optimum-intel#1634](https://github.com/huggingface/optimum-intel/pull/1634)
(by @rkazants, Intel) exports Qwen3.5 to OpenVINO IR with the following stateful
tensor naming convention:

**Per `linear_attention` layer `i` (18 layers in 0.8B):**

| Tensor | Name | Shape | Dynamic axes |
|---|---|---|---|
| Input | `cache_params.past.conv.{i}` | `(batch, d_inner, 4)` | batch |
| Input | `cache_params.past.ssm.{i}` | `(batch, 16, 128, 128)` | batch |
| Output | `cache_params.present.conv.{i}` | same | batch |
| Output | `cache_params.present.ssm.{i}` | same | batch |

**Per `full_attention` layer `i` (6 layers in 0.8B):**

| Tensor | Name | Shape | Dynamic axes |
|---|---|---|---|
| Input | `cache_params.past.key.{i}` | `(batch, 2, past_seq_len, 256)` | batch, seq_len |
| Input | `cache_params.past.value.{i}` | `(batch, 2, past_seq_len, 256)` | batch, seq_len |
| Output | `cache_params.present.key.{i}` | `(batch, 2, past_seq_len + seq_len, 256)` | batch, seq_len |
| Output | `cache_params.present.value.{i}` | `(batch, 2, past_seq_len + seq_len, 256)` | batch, seq_len |

**Total stateful tensors for 0.8B: 48**
(18 conv_state + 18 recurrent_state + 6 key + 6 value)

For Qwen3.5-9B (32 layers: 24 linear + 8 full): **64 stateful tensors**

---

### Relationship to PR #3359

PR #3359 ("Support Linear State in SDPA Pipeline") introduces the infrastructure
that should already handle Qwen3.5 automatically, via shape-based `ReadValue`
classification in `get_cache_types()`:

| Tensor | Shape rank | Dynamic axes | Projected classification |
|---|---|---|---|
| `conv_state` | 3 | 1 (batch) | `has_linear()` ✓ |
| `recurrent_state` | 4 | 1 (batch), 0 zero dims | `has_linear()` ✓ |
| KV key/value | 4 | 1 (batch), 1 zero dim (seq_len starts at 0) | `has_kvcache()` ✓ |

If this classification holds for the actual exported IR, Qwen3.5 would be detected
as `is_hybrid() == true` and routed to the SDPA backend automatically — matching
the same path as LFM2 (the primary driver of PR #3359).

**This validation has not been done.** This feature request asks Intel to:
1. Confirm the classification holds for Qwen3.5 IR
2. Add Qwen3.5 to the test coverage

---

## What Is Requested

### Required (for Qwen3.5 to work)

1. **Validate `get_cache_types()` classifies Qwen3.5 IR correctly**
   Once [optimum-intel#1634](https://github.com/huggingface/optimum-intel/pull/1634)
   exports a valid Qwen3.5 IR, run `get_cache_types()` on it and confirm
   `is_hybrid() == true`, `has_kvcache() == true`, `has_linear() == true`.

2. **Add Qwen3.5 entry to `tests/cpp/data/cache_types_models.csv`**
   Following the existing pattern for Phi3 (KV-only), LFM2 (hybrid), and
   Mamba (linear-only), add a Qwen3.5-0.8B entry verifying hybrid classification.

3. **Verify SSM FP32 preservation**
   `mamba_ssm_dtype: "float32"` in the model config means conv_state and
   recurrent_state tensors must remain FP32 through the pipeline. The GPU
   ScatterUpdate bug ([openvinotoolkit/openvino#34532](https://github.com/openvinotoolkit/openvino/issues/34532))
   causes silent FP16 downcasting here — the pipeline should not silently
   downcast these states even with `INFERENCE_PRECISION_HINT` set.

### Follow-on (separate issues, listed for completeness)

- **Paged Attention backend**: PR #3359 explicitly downgrades hybrid models to
  SDPA. A follow-on PA backend extension would be needed for continuous batching
  with Qwen3.5.
- **Speculative decoding**: Qwen3.5-0.8B is a natural speculative draft candidate
  for Qwen3.5-9B. Correctness of hybrid state management through the speculative
  decoding path (Eagle3, fast draft) is unvalidated.
- **Python test coverage**: Add `test_llm_pipeline.py` case for Qwen3.5 alongside
  existing Mamba/LFM2 tests.

---

## Blocking Dependencies

| Dependency | Status |
|---|---|
| [optimum-intel#1634](https://github.com/huggingface/optimum-intel/pull/1634) — Qwen3.5 IR export | DRAFT (WIP, @rkazants) |
| [openvino.genai#3359](https://github.com/openvinotoolkit/openvino.genai/pull/3359) — Hybrid pipeline infra | OPEN, milestone 2026.1 |
| [openvinotoolkit/openvino#34532](https://github.com/openvinotoolkit/openvino/issues/34532) — ScatterUpdate GPU bug | OPEN, assigned @Munesh-Intel, @Wan-Intel |

All three must land before Qwen3.5 GPU inference through `LLMPipeline` is possible.
CPU inference via the SDPA path should be unblocked once #1634 and #3359 merge.

---

## Hardware Context

Testing on **Intel Core Ultra 7 258V (Lunar Lake), Arc 140V (Xe2 iGPU)**:

Qwen3.5-0.8B at BF16: ~1.6 GB — fits in Arc 140V 16 GB shared memory.
Qwen3.5-9B at INT4: ~5–6 GB — fits after quantization
([NNCF config follow-up needed, see optimum-intel#1628](https://github.com/huggingface/optimum-intel/issues/1628)).

The Arc 140V result from the ScatterUpdate repro
([#34532 comment](https://github.com/openvinotoolkit/openvino/issues/34532))
confirms the GPU blocker affects Xe2 iGPU, not only Xe HPG dGPU (Arc A580).
</CONTENT>

File	
docs/GENAI_FEATURE_REQUEST_QWEN35.md	
Purpose
Feature request content, paste-ready

Verification (after posting)
Save the issue URL to docs/ISSUE_OPENVINO_QWEN35_TRACKING.md.

UI Submission Steps (detailed)
1. Go to https://github.com/openvinotoolkit/openvino.genai/issues/new
2. If a template chooser appears, click "Open a blank issue" at the bottom
3. Title: [Feature Request] Qwen3.5 hybrid cache pipeline support (conv_state + recurrent_state + KV-cache)
4. Body: Paste all content from docs/GENAI_FEATURE_REQUEST_QWEN35.md (everything between the outer triple-backtick fences in the plan above — i.e., everything from ## Summary through the final closing paragraph)
5. Right sidebar → Labels gear → select category: LLM if present
6. Leave all other fields blank
7. Click "Submit new issue"
8. Copy the resulting issue URL and report back