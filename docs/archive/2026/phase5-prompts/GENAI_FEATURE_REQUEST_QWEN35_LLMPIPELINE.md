---
title: GENAI_FEATURE_REQUEST_QWEN35_LLMPIPELINE
status: archived
area: portfolio
---

# Feature Request — openvino.genai — Qwen3.5 in LLMPipeline / ContinuousBatching / Speculative Decoding

**Target repo**: https://github.com/openvinotoolkit/openvino.genai/issues/new
**Type**: Feature request (text-only LLM path; complements PR #3717's VLM-only scope)
**Filing prerequisite**: Wait until both #3717 and optimum-intel#1689 have merged so the issue isn't filed against a moving target. Status check before filing: confirm `qwen3_5_text` exports land in optimum-intel and `cache_types_models.csv` exists in main.

---

## Title

`[Feature] Enable Qwen3.5 / Qwen3.5-MoE in LLMPipeline + ContinuousBatchingPipeline (text-only, hybrid GatedDeltaNet + GQA)`

## Issue body (paste as-is)

### Summary

PR [#3717](https://github.com/openvinotoolkit/openvino.genai/pull/3717) enables Qwen3.5 in the **VLM** pipeline, SDPA-only. The text-only path through `LLMPipeline` and `ContinuousBatchingPipeline` is not yet covered. PR [#3359](https://github.com/openvinotoolkit/openvino.genai/pull/3359) (merged) provides the hybrid-cache infrastructure needed to support Qwen3.5's GatedDeltaNet + GQA layout, but Qwen3.5 itself is not validated against it.

This issue tracks the four concrete gaps for text-only consumption.

### Model context

`qwen3_5_text` (the text sub-model of Qwen3.5) is hybrid:

- 24 layers in 3:1 layout — `[linear, linear, linear, full] × 6`
- 18 `linear_attention` layers using GatedDeltaNet (recurrent: `conv_state` + `recurrent_state`)
- 6 `full_attention` layers using GQA (`num_key_value_heads=2`, `head_dim=256`, `partial_rotary_factor=0.25`)
- `mamba_ssm_dtype: float32` required for SSM stability

Per-layer stateful tensor naming from optimum-intel#1689 export:
- `cache_params.past.conv.{i}` — 3D, `(batch, d_inner, 4)`
- `cache_params.past.ssm.{i}` — 4D, `(batch, 16, 128, 128)`
- `cache_params.past.key.{i}` / `.value.{i}` — 4D, `(batch, 2, seq, 256)`

Total stateful tensors: **48** for Qwen3.5-0.8B, **64** for Qwen3.5-9B.

### Requested work

#### 1. Validate `get_cache_types()` classification on Qwen3.5 IR

Once optimum-intel#1689 produces a stable `qwen3_5_text` IR, run `get_cache_types()` from #3359 against it and confirm:

```
is_hybrid()    == true
has_kvcache()  == true
has_linear()   == true
```

Add the result as a new row in `tests/cpp/data/cache_types_models.csv` next to the existing Phi3 / LFM2 / Mamba entries. This is the smallest possible change that makes Qwen3.5 a first-class hybrid model in the test matrix.

#### 2. Add `LLMPipeline` Python coverage

Mirror the existing LFM2 / Mamba test in `tests/python_tests/test_llm_pipeline.py`. Tiny-random Qwen3.5 export is sufficient — the goal is dispatch-path coverage, not generation quality.

#### 3. ContinuousBatching / PagedAttention backend

#3359's PR description explicitly downgrades hybrid models to the SDPA backend. Long-running batched serving for Qwen3.5 requires either:

- (a) PagedAttention support for the GatedDeltaNet recurrent state (non-trivial — the recurrent state has no notion of paged blocks), or
- (b) an explicit "no PA for hybrid" check with a clear runtime error message rather than silent fallback.

Even (b) would be a usability improvement — currently the failure mode for `ContinuousBatchingPipeline.add_request(...)` against a hybrid model isn't documented.

#### 4. Speculative decoding draft/target pair

Qwen3.5-0.8B and Qwen3.5-9B share tokenizer and architecture family — natural draft/target pair for speculative decoding. The hybrid state-management correctness through Eagle3 / fast-draft paths is unvalidated. Specifically:

- On a draft-rejection event, the recurrent state must roll back to the pre-speculation snapshot. SSM state rollback semantics in #3359's draft path are not exercised by Mamba/LFM2 because they're not used as draft models in the existing test suite.
- `cache_types_models.csv` currently doesn't encode the draft/target pairing — if you'd accept a column extension for that, I can include it in the validation PR.

### Hardware availability

Intel Core Ultra 7 258V (Lunar Lake), 32 GB LPDDR5X, Arc 140V iGPU (Xe2). I can run validation for items (1), (2), and (4) on this hardware once #1689 lands. Item (3) is design work that needs an Intel decision before implementation.

### Related

- [openvinotoolkit/openvino.genai#3359](https://github.com/openvinotoolkit/openvino.genai/pull/3359) — hybrid cache infra (merged)
- [openvinotoolkit/openvino.genai#3717](https://github.com/openvinotoolkit/openvino.genai/pull/3717) — Qwen3.5 VLM SDPA (open, near merge)
- [openvinotoolkit/openvino.genai#3644](https://github.com/openvinotoolkit/openvino.genai/pull/3644) — referenced as VLM follow-on
- [huggingface/optimum-intel#1689](https://github.com/huggingface/optimum-intel/pull/1689) — Qwen3.5 / 3.5-MoE / 3.6 export (open)
- [openvinotoolkit/openvino#34532](https://github.com/openvinotoolkit/openvino/issues/34532) — `ScatterUpdate` FP16 down-cast on GPU; affects iterative SSM state on Xe2 specifically

---

## Author's notes (do not paste)

**Why this issue is useful to Intel**:
- Carves a clean, non-overlapping scope vs. #3717. The VLM team can ship #3717 without thinking about LLMPipeline; this issue parks the LLM-pipeline backlog explicitly so it doesn't get lost.
- Item (1) is the smallest possible ask — one CSV row — and gates everything downstream. Easy to accept.
- Item (3) names a real gap in #3359's framing: "downgrades to SDPA" is fine for single-user, but `ContinuousBatchingPipeline` users will hit it without warning.
- Item (4) is the only item where I'm flagging a specific correctness concern (state rollback on draft rejection) rather than a coverage gap. That's the highest-value point because it's not obvious from the existing test surface.

**Filing order**:
1. Wait for #3717 to merge (avoids duplicating their CSV / test additions)
2. Wait for #1689 to merge (avoids filing against a non-existent model_type)
3. File this issue, link to both as completed prerequisites
4. Offer to send a validation PR for items (1) + (2)

**Why no architecture deep-dive**: same reason as the #1689 comment — Intel knows the model. The value here is naming the four gaps and offering Xe2 hardware, not re-deriving the spec.

**Tone**: enumerate gaps, propose smallest viable contributions, offer hardware, no project marketing.
