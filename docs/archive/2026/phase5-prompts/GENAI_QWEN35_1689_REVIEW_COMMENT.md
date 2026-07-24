---
title: GENAI_QWEN35_1689_REVIEW_COMMENT
status: archived
area: portfolio
---

# Review Comment — optimum-intel#1689 (Qwen3.5 / Qwen3.5-MoE / Qwen3.6 export)

**Target**: https://github.com/huggingface/optimum-intel/pull/1689
**Author of comment**: BlarAI (downstream consumer, Lunar Lake / Arc 140V)
**Intent**: Flag two concrete downstream-consumption risks before the IR contract solidifies, and offer Xe2 hardware for validation.

---

## Comment body (paste as-is)

Thanks for re-opening this after #1634 — happy to see Qwen3.5/3.6 land. Two narrow concerns from a downstream consumer perspective (text-only `LLMPipeline` / `ContinuousBatchingPipeline` on Lunar Lake), and an offer at the bottom.

### 1. SSM state dtype contract (`mamba_ssm_dtype`)

`Qwen/Qwen3.5-0.8B/config.json` declares `"mamba_ssm_dtype": "float32"` and the upstream HF `Qwen3_5GatedDeltaNet` implementation maintains `recurrent_state` / `conv_state` in FP32 even when the rest of the model runs FP16/BF16 — this is required for numerical stability of the recurrent update.

I noticed the `ix mamba expected int8` commit (61d85b3) and the recent `add test to ensure dtype` / `Fix bf16 patching` commits. Could you confirm one of the following holds in the exported IR for `qwen3_5_text`:

- **(a)** the per-layer `cache_params.past.conv.{i}` and `cache_params.past.ssm.{i}` `ReadValue` element types remain `f32` independent of `--weight-format` and any `INFERENCE_PRECISION_HINT` the runtime applies, **or**
- **(b)** the model_patcher explicitly upcasts the SSM update region so the iterative state lives in FP32 even when surrounding weights are BF16/INT8.

If neither, FP16/BF16 SSM state will accumulate error across long contexts and silently degrade quality without any obvious failure signal — particularly painful for the 9B model where the regression vs. HF baseline would only show up in WWB-style comparison runs.

A `test_export_dtype` row asserting `f32` for `cache_params.past.ssm.*` and `cache_params.past.conv.*` (mirroring the existing dtype assertion pattern from `2f38fd8`) would lock the contract.

### 2. Downstream interaction with openvino#34532 on GPU

Independent of this PR, but worth flagging because the IR contract you're freezing is the input to the bug:

[openvinotoolkit/openvino#34532](https://github.com/openvinotoolkit/openvino/issues/34532) — `ScatterUpdate` silently down-casts FP32 inputs to FP16 on the GPU plugin under default `INFERENCE_PRECISION_HINT=f16`. Reproduced on Xe HPG (Arc A580) and Xe2 iGPU (Arc 140V, Lunar Lake).

The recurrent-state update path for GatedDeltaNet lowers through `ScatterUpdate`-shaped subgraphs in the existing Mamba/LFM2 patterns. If the exported IR keeps FP32 SSM state per (1) but the runtime plugin demotes it on GPU per #34532, the contract you set here becomes a no-op on the most likely consumer GPU.

I don't think it's this PR's responsibility to fix that — but a one-line note in the model card / docs ("for GPU inference, set `INFERENCE_PRECISION_HINT=f32` for SSM-bearing models until openvino#34532 lands") would save downstream users a debugging round-trip.

### 3. Validation offer

If it's useful, I can run the exported IR (Qwen3.5-0.8B at FP16 and INT4) through:

- `LLMPipeline` text-only generation (CPU and Xe2 GPU)
- WWB similarity vs. the HF baseline (matching the methodology yatarkan used for #3717)
- `get_cache_types()` classification check against the merged #3359 infra to confirm `is_hybrid()==true`, `has_kvcache()==true`, `has_linear()==true`

Hardware: Intel Core Ultra 7 258V (Lunar Lake), 32 GB LPDDR5X, Arc 140V iGPU. Happy to post artifacts on either this PR or openvino.genai/#3717's follow-on issue.

---

## Author's notes (do not paste)

**Why this is useful to Intel**:
- (1) is a real risk: the dtype-test pattern they're already using (`bf1f377`, `2f38fd8`) doesn't cover SSM tensors specifically, and the int8 mamba commit suggests an implicit default that may not match HF.
- (2) is a heads-up they'll appreciate because the GPU bug is owned by a different team — they don't necessarily track #34532, and the model_card suggestion is cheap.
- (3) is the honest bid: no Intel team has many Lunar Lake / Xe2 testers, and offering WWB on the consumer SKU saves them CI time.

**Why this is the right venue (vs #3717)**:
- #3717 is VLM-only, near merge, Intel-approved by as-suvorov 4 days ago. Posting architecture facts there is scope creep.
- #1689 has no reviewers assigned yet, is the *upstream* of the IR contract, and the author (rkazants) is the right person to address dtype questions.

**Why no architecture spec dump**: rkazants and echarlaix know Qwen3.5 architecture better than we do. Re-stating the 24-layer 3:1 ratio would be condescending. Stick to the two concrete contract risks and the validation offer.

**Tone**: deferential to maintainers, technical, no Lead-Architect-of-BlarAI framing, no project marketing.
