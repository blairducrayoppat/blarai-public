---
title: ISSUE_GENAI_QWEN35_HYBRID_CACHE
status: archived
area: portfolio
---

# Paste-Ready: Qwen3.5 Hybrid Cache Feature Request for openvino.genai

> **Target repo:** `openvinotoolkit/openvino.genai`
> **Issue type:** Feature Request
> **Filed by:** @blairducrayoppat

---

## Title

🙏 [Feature Request]: Qwen3.5 (Gated DeltaNet hybrid) — LLMPipeline support as a validated hybrid-cache model

---

## Body

### Request Description

Requesting Qwen3.5 (Gated DeltaNet hybrid architecture) as a validated model family in the openvino.genai LLMPipeline, including continuous batching and speculative decoding support.

Qwen3.5 is Qwen's latest dense architecture series ([HuggingFace collection](https://huggingface.co/collections/Qwen/qwen35)), combining **Gated DeltaNet linear attention** (75% of layers) with standard grouped-query full attention (25% of layers) in a repeating `[linear × 3, full × 1]` pattern. This creates a **hybrid cache model** that requires both linear/recurrent state and standard KV-cache management simultaneously.

**Dense variants:**

| Model | Layers | Hidden | Linear / Full Attn Layers | Context |
|---|---|---|---|---|
| Qwen3.5-0.8B | 24 | 1024 | 18 / 6 | 262K |
| Qwen3.5-4B | — | — | — | 262K |
| Qwen3.5-9B | 32 | 4096 | 24 / 8 | 262K |
| Qwen3.5-27B | — | — | — | 262K |

### Relationship to PR #3359

I see that PR #3359 ("Support Linear State in SDPA Pipeline") by @apaniukov is adding exactly the hybrid cache infrastructure this would need:

- `CacheTypes` bitmask with `has_kvcache()` and `has_linear()`
- `CacheState` replacing `KVCacheState`, with hybrid trim behavior (reset linear state, trim KV-cache)
- `get_cache_types()` detecting cache kinds from ReadValue node shapes (4D dynamic = KV-cache, 3D dynamic = linear state)
- Propagation through VLM pipeline, speculative decoding (Eagle3 + fast draft strategies), and continuous batching
- Test models: Phi3 (KV-cache only), LFM2 (hybrid), Mamba (linear only)

**This feature request is specifically asking for Qwen3.5 to be added as a validated hybrid model alongside LFM2 once PR #3359 merges.** The two model families share the hybrid pattern (mixed linear + KV-cache layers) but differ in the linear attention mechanism:

| | LFM2 | Qwen3.5 |
|---|---|---|
| Linear attention type | (LFM-specific) | Gated DeltaNet |
| State per linear layer | Linear state | `conv_state` (causal conv buffer) + `recurrent_state` (per-head state matrix) |
| Hybrid ratio | (varies) | 75% linear / 25% full attention |
| Additional features | — | Multi-Token Prediction head (`mtp_num_hidden_layers: 1`) |

### Qwen3.5 state format

Per linear attention layer:
- `conv_state`: `[batch, d_inner, conv_kernel_size]` — causal 1D convolution buffer (`linear_conv_kernel_dim: 4`)
- `recurrent_state`: `[batch, num_v_heads, head_k_dim, head_v_dim]` — per-head state matrix for the delta rule update

Per full attention layer:
- Standard `key_cache` + `value_cache`: `[batch, num_kv_heads, seq_len, head_dim]`

For Qwen3.5-0.8B this means 18 × (conv_state + recurrent_state) + 6 × (key_cache + value_cache) = 48 stateful variables.

### OpenVINO export path

The optimum-intel export path is being developed in [optimum-intel#1634](https://github.com/huggingface/optimum-intel/pull/1634) by @rkazants (currently Draft). It converts GatedDeltaNet to a recurrent formulation using `RecurrentAttentionCellOp` via ModuleExtension, with conv1d handled via `ov_causal_conv1d`. No new OpenVINO core ops are required — the recurrent attention cell decomposes into existing elementwise ops (matmul, multiply, add, sigmoid, softplus) at the conversion layer.

**Key question:** Once optimum-intel#1634 exports Qwen3.5 to OpenVINO IR, will the ReadValue node shapes produced match PR #3359's detection heuristic (3D dynamic = linear state)? If so, Qwen3.5 may work with the hybrid cache infrastructure with minimal additional changes. If the recurrent cell decomposition produces different state shapes, some adaptation may be needed.

### GPU blocker note

[openvino#34532](https://github.com/openvinotoolkit/openvino/issues/34532) reports that GPU ScatterUpdate has FP16 precision loss that accumulates across recurrent state update layers, and crashes inside Loop bodies. This is a core OpenVINO GPU plugin issue, not a genai issue, but it will block Qwen3.5 GPU inference even after both the export path and genai pipeline support are in place. I mention it here for tracking context — @jgespino has self-assigned the issue.

### What I'm asking for

1. **Test validation:** Once PR #3359 merges, add Qwen3.5 (starting with 0.8B) to the `cache_types_models.csv` test data alongside Phi3, LFM2, and Mamba — confirming that `get_cache_types()` correctly detects it as a hybrid model.

2. **Inference validation:** Once optimum-intel#1634 is also available, validate that the stateful LLM pipeline produces correct output for Qwen3.5 through the hybrid cache path.

3. **Continuous batching:** Verify that the hybrid trim behavior (linear state reset + KV-cache trim) works correctly for Qwen3.5's `[linear × 3, full × 1]` layer pattern under continuous batching.

4. **Speculative decoding:** Qwen3.5 includes a multi-token prediction (MTP) head (`mtp_num_hidden_layers: 1`). Confirm that the speculative decoding wrappers updated in PR #3359 handle the hybrid cache correctly in this mode.

### My context

I'm building a local-first AI system on Intel Arc 140V (Xe2, Lunar Lake) and have been contributing to OpenVINO:
- [openvino#34617](https://github.com/openvinotoolkit/openvino/issues/34617) / [openvino#34651](https://github.com/openvinotoolkit/openvino/pull/34651) — NPU unbounded dynamic shape guard
- [npu_compiler#265](https://github.com/openvinotoolkit/npu_compiler/pull/265) / [npu_compiler#266](https://github.com/openvinotoolkit/npu_compiler/pull/266) — VPUX compiler INT4 per-group fix

Qwen3.5-9B is a strong candidate for consumer Intel GPU inference — the hybrid linear/full attention architecture should provide better throughput than pure-transformer models at equivalent parameter counts, which matters on memory-constrained hardware. Happy to provide testing and validation on Arc 140V once the pieces are in place.

### Feature Use Case

Local inference of Qwen3.5 dense variants on consumer Intel GPUs via openvino.genai's optimized C++ pipeline, with continuous batching and speculative decoding support.

### Issue submission checklist

- [x] The feature request is related to OpenVINO GenAI
- [x] I have searched for existing issues and didn't find a duplicate
