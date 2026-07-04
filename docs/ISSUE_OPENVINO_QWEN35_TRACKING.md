# Paste-Ready: Qwen3.5 Tracking Issue for openvinotoolkit/openvino

> **Target repo:** `openvinotoolkit/openvino`
> **Issue type:** Feature Request
> **Filed by:** @blairducrayoppat

---

## Title

🙏 [Feature Request]: Qwen3.5 (Gated DeltaNet hybrid) — end-to-end support tracking

---

## Body

### Request Description

Requesting end-to-end Qwen3.5 support across the OpenVINO ecosystem. Qwen3.5 introduces a fundamentally new **hybrid architecture** that combines [Gated DeltaNet](https://arxiv.org/abs/2412.06464) linear attention (75% of layers) with standard grouped-query full attention (25% of layers), repeating in a `[linear_attention × 3, full_attention × 1]` pattern. This is architecturally distinct from prior Qwen generations and requires new operator support.

**Dense model variants of interest:**

| Model | Layers | Hidden | GQA Heads | Linear K Heads | Linear V Heads | Context |
|---|---|---|---|---|---|---|
| Qwen3.5-0.8B | 24 | 1024 | 8 / 2 | 16 | 16 | 262K |
| Qwen3.5-4B | — | — | — | — | — | 262K |
| Qwen3.5-9B | 32 | 4096 | 16 / 4 | 16 | 32 | 262K |
| Qwen3.5-27B | — | — | — | — | — | 262K |

All Qwen3.5 models are natively multimodal (`Qwen3_5ForConditionalGeneration`) with a built-in vision encoder. Dense variants use a single model (no MoE routing). HuggingFace collection: https://huggingface.co/collections/Qwen/qwen35

### New architectural concepts requiring support

1. **Gated DeltaNet (linear attention):** Recurrent state-space-style attention with:
   - Causal 1D convolution (`linear_conv_kernel_dim: 4`)
   - Separate linear key/value head counts (`linear_num_key_heads`, `linear_num_value_heads`)
   - Per-head recurrent state (`head_k_dim × head_v_dim`)
   - Delta rule update with learned forget gate (`A_log`, `dt_bias`)
   - `attn_output_gate` normalization

2. **Hybrid KV-cache:** Mixed cache format:
   - Linear attention layers: `conv_state` (causal conv buffer) + `recurrent_state` (per-head state matrix)
   - Full attention layers: Standard `key_cache` + `value_cache` (GQA with `partial_rotary_factor: 0.25`, interleaved mRoPE)

3. **Multi-Token Prediction (MTP):** `mtp_num_hidden_layers: 1` — additional prediction head for speculative decoding compatibility.

### Current ecosystem status

| Component | Status | Reference |
|---|---|---|
| **HuggingFace transformers** | ✅ Merged | [transformers#43830](https://github.com/huggingface/transformers/pull/43830) — `model_type: qwen3_5` |
| **optimum-intel (export)** | 🔄 Draft PR | [optimum-intel#1634](https://github.com/huggingface/optimum-intel/pull/1634) by @rkazants — RecurrentAttentionCellOp conversion, hybrid cache, VLM + text-only |
| **optimum-intel (feature request)** | 📋 Open | [optimum-intel#1628](https://github.com/huggingface/optimum-intel/issues/1628) — Qwen3.5 Family Support |
| **OpenVINO GPU (blocker)** | 🐛 Open | [#34532](https://github.com/openvinotoolkit/openvino/issues/34532) — ScatterUpdate fp16 precision loss + Loop body crash blocks GatedDeltaNet on GPU |
| **openvino.genai** | ❌ No work | No issue or PR for hybrid-cache pipeline support |

### What this issue tracks

1. **OpenVINO core ops:** Does the `RecurrentAttentionCellOp` conversion in optimum-intel#1634 decompose cleanly into existing OpenVINO operations, or are new GPU/CPU kernel implementations needed?

2. **GPU ScatterUpdate blocker:** Issue #34532 reports that the GPU plugin's ScatterUpdate kernel has precision loss (\~0.001 per op) that accumulates across 24+ layers of iterative state updates, producing garbled output. Inside a Loop body it crashes entirely. This directly blocks Qwen3.5's recurrent attention on GPU.

3. **openvino.genai pipeline:** The GenAI C++ inference pipeline currently has no support for hybrid cache formats (conv_state + recurrent_state + KV-cache). This is needed for optimized inference with continuous batching, speculative decoding, etc.

4. **Quantization (NNCF):** INT4/INT8 quantization configs for the dense variants (particularly 9B and 27B for consumer GPU inference).

### My context

I'm working on a local-first AI system targeting Intel Arc 140V (Xe2, Lunar Lake) and have been contributing NPU-related fixes:
- [#34617](https://github.com/openvinotoolkit/openvino/issues/34617) / [#34651](https://github.com/openvinotoolkit/openvino/pull/34651) — NPU unbounded dynamic shape guard
- [openvinotoolkit/npu_compiler#265](https://github.com/openvinotoolkit/npu_compiler/pull/265) / [openvinotoolkit/npu_compiler#266](https://github.com/openvinotoolkit/npu_compiler/pull/266) — VPUX compiler INT4 per-group fix

I'd like to contribute to Qwen3.5 support — particularly testing, validation on Arc GPU, and potentially openvino.genai pipeline work. Filing this issue to track the cross-component effort and offer to help where it's useful.

### Feature Use Case

Qwen3.5 dense variants (9B especially) are strong candidates for local inference on consumer Intel GPUs. The hybrid linear/full attention architecture provides better throughput than pure-transformer models at equivalent parameter counts, which is particularly relevant for memory-constrained consumer hardware.

### Issue submission checklist

- [x] The feature request or improvement must be related to OpenVINO
