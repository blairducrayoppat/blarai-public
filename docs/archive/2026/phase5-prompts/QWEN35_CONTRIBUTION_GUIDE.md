---
title: QWEN35_CONTRIBUTION_GUIDE
status: archived
area: portfolio
---

# Qwen3.5 Dense Variant Contribution Guide

## Situation Assessment

**You do NOT need to build Qwen3.5 export support from scratch.** `@rkazants` (Intel, optimum-intel Collaborator) has an active Draft PR ([optimum-intel#1634](https://github.com/huggingface/optimum-intel/pull/1634)) that already handles:
- GatedDeltaNet → `RecurrentAttentionCellOp` conversion via ModuleExtension
- Hybrid cache (conv + recurrent + KV) input/output wiring
- Both text-only and VLM inference paths
- Dummy input generators for the hybrid cache shape
- Model patcher for forward replacement
- Tests with `optimum-intel-internal-testing/tiny-random-qwen3.5`

The PR is 955+ lines across 8 files and requires `transformers >= 4.57.0`. It targets the `transformers-v5` branch.

**What's NOT covered** — and where contribution opportunities exist:

---

## Contribution Opportunity 1: Testing PR #1634 on Real Models

**Impact:** High — @rkazants likely tests on server hardware, not consumer Intel Arc GPUs.

### What to do

1. **Fork and check out the PR branch:**
   ```powershell
   git clone https://github.com/rkazants/optimum-intel.git
   cd optimum-intel
   git checkout support_qwen3_5
   pip install -e ".[openvino]"
   ```

2. **Install transformers >= 4.57.0:**
   ```powershell
   pip install "transformers>=4.57.0"
   ```

3. **Export Qwen3.5-0.8B (smallest dense variant) to OpenVINO IR:**
   ```python
   from optimum.intel import OVModelForCausalLM
   # Text-only export (uses Qwen3_5TextOpenVINOConfig internally)
   model = OVModelForCausalLM.from_pretrained(
       "Qwen/Qwen3.5-0.8B",
       export=True,
       device="CPU",  # export on CPU first
   )
   model.save_pretrained("./qwen3.5-0.8b-ov")
   ```

4. **Test inference on CPU (baseline):**
   ```python
   from optimum.intel import OVModelForCausalLM
   from transformers import AutoTokenizer
   
   model = OVModelForCausalLM.from_pretrained("./qwen3.5-0.8b-ov", device="CPU")
   tokenizer = AutoTokenizer.from_pretrained("Qwen/Qwen3.5-0.8B")
   
   inputs = tokenizer("Hello, my name is", return_tensors="pt")
   outputs = model.generate(**inputs, max_new_tokens=50)
   print(tokenizer.decode(outputs[0]))
   ```

5. **Test on GPU (Arc 140V) — expect potential issues per #34532:**
   ```python
   model = OVModelForCausalLM.from_pretrained("./qwen3.5-0.8b-ov", device="GPU")
   ```

6. **Report results** as a comment on optimum-intel#1634, including:
   - Export success/failure
   - CPU inference output quality
   - GPU inference output quality (or crash details)
   - Hardware: Intel Arc 140V, driver version, OpenVINO version

### Why 0.8B first
At 24 layers with hidden_size 1024, Qwen3.5-0.8B fits comfortably in Arc 140V's \~8GB VRAM even at FP16. It exercises the full hybrid architecture (18 linear + 6 full attention layers). If it works, move to 9B.

---

## Contribution Opportunity 2: GPU ScatterUpdate Bug Triage (#34532)

**Impact:** Critical — this is the **blocking bug** for Qwen3.5 on GPU.

Issue [#34532](https://github.com/openvinotoolkit/openvino/issues/34532) by `@Blackwood416` reports:
- ScatterUpdate on GPU has FP16 down-cast precision loss (\~0.001 per operation)
- Inside a Loop body (used by recurrent state updates), the GPU plugin **crashes**: `ProgramBuilder build failed! Check 'correct_layout_selected' failed`
- The reporter explicitly identifies Qwen3.5 GatedDeltaNet as the blocked use case

### What you can contribute
- **Reproduce on Arc 140V**: Run Blackwood416's repro script on your hardware. Their bug was reported on Arc A580 — confirming on Xe2 adds weight.
- **Cross-reference with PR #1634**: Once you have a Qwen3.5-0.8B IR exported, attempt GPU compile and report the specific stacktrace. This connects the abstract ScatterUpdate bug to a concrete model.
- **Test `INFERENCE_PRECISION_HINT: f32` workaround**: Blackwood416 shows standalone ScatterUpdate works with FP32 hint. Test whether full-model inference produces correct output with this hint (at the cost of performance).

---

## Contribution Opportunity 3: openvino.genai Pipeline Support

**Impact:** High — this is the largest gap. No work has started.

The [openvino.genai](https://github.com/openvinotoolkit/openvino.genai) C++ inference pipelines (LLMPipeline, ContinuousBatchingPipeline) currently handle standard KV-cache models only. Qwen3.5 requires a **hybrid cache pipeline** that manages:

1. **conv_state** tensors: `[batch, d_inner, conv_kernel_size]` per linear attention layer
2. **recurrent_state** tensors: `[batch, num_v_heads, head_k_dim, head_v_dim]` per linear attention layer
3. **key/value cache** tensors: `[batch, num_kv_heads, seq_len, head_dim]` per full attention layer (standard)

### Where to look in openvino.genai

The relevant C++ code is in:
- `src/cpp/src/llm_pipeline.cpp` — main pipeline, handles KV-cache allocation
- `src/cpp/src/cache_manager.hpp` — cache allocation and management
- `src/cpp/src/model_runner.hpp` — handles infer request tensor binding
- `src/cpp/src/sequence_group.hpp` — manages per-sequence state

The pattern to follow is how **Mamba** (another SSM model) was added. Search for `mamba` in the genai codebase — it also has non-standard state (conv + SSM states instead of KV-cache). Qwen3.5's hybrid cache is a superset: SSM-like states for linear layers PLUS standard KV-cache for full attention layers.

### Concrete steps
1. File a feature request on `openvinotoolkit/openvino.genai` requesting Qwen3.5 hybrid-cache pipeline support
2. Reference the optimum-intel PR #1634 cache format (conv + recurrent + KV naming scheme)
3. Study the Mamba implementation pattern in genai
4. Prototype: a minimal Python-level inference loop that manually manages the hybrid cache tensors (using `openvino` directly, not genai) to validate the exported model works end-to-end

---

## Contribution Opportunity 4: NNCF Quantization Configs

**Impact:** Medium — needed for practical deployment but can wait until export works.

Once PR #1634 merges and Qwen3.5 exports correctly:
- Define default INT4 quantization configs for each dense variant
- Test quantization accuracy (perplexity benchmarks)
- Submit as a follow-up PR to optimum-intel (pattern: see `ljaljushkin`'s Qwen3-30B-A3B config in PR #1506)

---

## Architecture Quick Reference

### Layer pattern (Qwen3.5-9B, 32 layers)
```
L0:  linear_attention  (GatedDeltaNet)
L1:  linear_attention  (GatedDeltaNet)
L2:  linear_attention  (GatedDeltaNet)
L3:  full_attention    (GQA, partial_rotary_factor=0.25)
L4:  linear_attention
L5:  linear_attention
L6:  linear_attention
L7:  full_attention
...
L28: linear_attention
L29: linear_attention
L30: linear_attention
L31: full_attention
```
→ 24 linear attention layers, 8 full attention layers

### Key config fields (beyond standard transformer)
```json
{
  "model_type": "qwen3_5",
  "architectures": ["Qwen3_5ForConditionalGeneration"],
  "layer_types": ["linear_attention", "linear_attention", "linear_attention", "full_attention", ...],
  "linear_conv_kernel_dim": 4,
  "linear_key_head_dim": 128,
  "linear_value_head_dim": 128,
  "linear_num_key_heads": 16,
  "linear_num_value_heads": 32,
  "attn_output_gate": true,
  "partial_rotary_factor": 0.25,
  "mtp_num_hidden_layers": 1,
  "rope_interleaved": true
}
```

### How PR #1634 handles GatedDeltaNet
The `Qwen3_5ModelPatcher` replaces the Gated DeltaNet forward with a **recurrent formulation** that processes one token at a time:
1. Projects hidden state → mixed QKV via `in_proj_qkv`, processes through causal conv1d
2. Splits into Q, K, V; computes forget gate `g` and input gate `beta`
3. Calls `recurrent_gated_delta_rule` — a single-step recurrent update: `state = g * state + beta * (k^T @ v)`
4. The recurrent cell is wrapped as `RecurrentAttentionCell` module → `RecurrentAttentionCellOp` via ModuleExtension → OpenVINO IR via `convert_recurrent_attention_cell` ConversionExtension
5. The conv1d is handled via `ov_causal_conv1d` (existing utility for Mamba-style causal convolutions)

This means **no new OpenVINO core ops are needed** — the recurrent attention cell decomposes into existing elementwise ops (matmul, multiply, add, sigmoid, softplus) at the conversion layer. The GPU blocker (#34532) is about ScatterUpdate precision in the existing op implementations, not missing ops.

---

## Prioritized Action Plan

| Priority | Action | Effort | Blocked by |
|---|---|---|---|
| 1 | Reproduce #34532 ScatterUpdate bug on Arc 140V | Low | Nothing |
| 2 | Test PR #1634 export with Qwen3.5-0.8B on CPU | Medium | PR #1634 branch setup |
| 3 | Test exported model on GPU (expect issues per #34532) | Low | Action 2 |
| 4 | Comment on PR #1634 with Arc 140V test results | Low | Actions 2-3 |
| 5 | File openvino.genai feature request for hybrid cache | Low | Nothing |
| 6 | Prototype Python-level hybrid cache inference loop | High | Action 2 |
| 7 | Study genai Mamba implementation for hybrid cache port | Medium | Nothing |
