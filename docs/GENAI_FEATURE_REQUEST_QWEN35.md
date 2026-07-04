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

```
[linear_attention, linear_attention, linear_attention, full_attention] × 6 blocks
```

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

**Total stateful tensors for Qwen3.5-0.8B: 48**
(18 conv_state + 18 recurrent_state + 6 key + 6 value)

**Total stateful tensors for Qwen3.5-9B (32 layers: 24 linear + 8 full): 64**

---

### Relationship to PR #3359

PR #3359 ("Support Linear State in SDPA Pipeline") introduces the infrastructure
that should already handle Qwen3.5 automatically, via shape-based `ReadValue`
classification in `get_cache_types()`:

| Tensor | Shape rank | Dynamic axes | Projected classification |
|---|---|---|---|
| `conv_state` | 3 | 1 (batch) | `has_linear()` ✓ |
| `recurrent_state` | 4 | 1 (batch), 0 zero dims | `has_linear()` ✓ |
| KV key/value | 4 | 1 (batch), 1 zero dim (`seq_len` starts at 0) | `has_kvcache()` ✓ |

If this classification holds for the actual exported IR, Qwen3.5 would be detected
as `is_hybrid() == true` and routed to the SDPA backend automatically — matching
the same path as LFM2 (the current primary driver of PR #3359).

**This validation has not been done.** This issue asks Intel to:
1. Confirm the classification holds for actual Qwen3.5 IR output
2. Add Qwen3.5 to the CI test matrix

---

## What Is Requested

### Required (for Qwen3.5 to work in `LLMPipeline`)

**1. Validate `get_cache_types()` classifies Qwen3.5 IR correctly**

Once [optimum-intel#1634](https://github.com/huggingface/optimum-intel/pull/1634)
exports a valid Qwen3.5 IR, run `get_cache_types()` on it and confirm:
```
is_hybrid()   == true
has_kvcache() == true
has_linear()  == true
```

**2. Add Qwen3.5 entry to `tests/cpp/data/cache_types_models.csv`**

Following the existing pattern for Phi3 (KV-only), LFM2 (hybrid), and Mamba
(linear-only), add a Qwen3.5-0.8B entry verifying hybrid classification.

**3. Verify SSM FP32 state preservation**

`"mamba_ssm_dtype": "float32"` in Qwen3.5's config means `conv_state` and
`recurrent_state` tensors must remain FP32 through the pipeline. This is
particularly relevant given the active GPU ScatterUpdate precision bug
([openvinotoolkit/openvino#34532](https://github.com/openvinotoolkit/openvino/issues/34532)),
which causes silent FP16 downcasting of iterative state updates — confirmed
on both Xe HPG (Arc A580) and Xe2 iGPU (Arc 140V, Lunar Lake). The pipeline
should guard against this downcast for SSM-typed states regardless of
`INFERENCE_PRECISION_HINT` setting.

---

### Follow-on (separate issues, noted for completeness)

- **Paged Attention backend**: PR #3359 explicitly downgrades hybrid models to
  the SDPA backend. A follow-on would be needed for continuous batching support.
- **Speculative decoding**: Qwen3.5-0.8B is a natural draft candidate for
  Qwen3.5-9B. Correctness of hybrid state management through Eagle3 / fast-draft
  paths is unvalidated.
- **Python test coverage**: Add a `test_llm_pipeline.py` case for Qwen3.5
  alongside existing Mamba/LFM2 tests.
- **NNCF INT4 quantization configs**: Needed for practical deployment of 9B
  on consumer hardware; tracked in
  [optimum-intel#1628](https://github.com/huggingface/optimum-intel/issues/1628).

---

## Blocking Dependencies

| Dependency | Status |
|---|---|
| [optimum-intel#1634](https://github.com/huggingface/optimum-intel/pull/1634) — Qwen3.5 IR export | Draft, WIP (@rkazants) |
| [openvino.genai#3359](https://github.com/openvinotoolkit/openvino.genai/pull/3359) — Hybrid pipeline infrastructure | Open, milestone 2026.1 |
| [openvinotoolkit/openvino#34532](https://github.com/openvinotoolkit/openvino/issues/34532) — ScatterUpdate GPU bug | Open, assigned @Munesh-Intel, @Wan-Intel |

CPU inference via the SDPA path should be feasible once #1634 and #3359 merge.
Full GPU inference requires #34532 to be resolved.

---

## Hardware Context

Verified testing platform: **Intel Core Ultra 7 258V (Lunar Lake), Arc 140V (Xe2, 16 GB iGPU)**

- Qwen3.5-0.8B at FP16: \~1.6 GB — fits comfortably
- Qwen3.5-9B at INT4: \~5–6 GB — fits after quantization

The ScatterUpdate GPU blocker was reproduced on this hardware in
[openvino#34532](https://github.com/openvinotoolkit/openvino/issues/34532),
confirming the issue affects Xe2 iGPU, not only Xe HPG dGPU (Arc A580).
This platform is available for validation testing once the blocking PRs land.
