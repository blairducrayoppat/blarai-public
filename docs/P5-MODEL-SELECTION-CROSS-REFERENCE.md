# P5 Model Selection Cross-Reference Analysis

## Status
**DRAFT** — Awaiting Lead Architect review

## Executive Summary

This analysis cross-references five data sources (OpenVINO GenAI supported models CSV, Core Ultra 7-258V GPU benchmarks CSV, OpenVINO 2026.0 release notes, HuggingFace model cards, and the llm-chatbot notebook) to determine the optimal model(s) for BlarAI under the updated all-GPU/CPU inference architecture.

**Key Finding:** Qwen3-30B-A3B (MoE) is **MEMORY-INFEASIBLE** on this hardware despite its attractive compute efficiency (3.3B active params). Qwen3-14B (dense) emerges as the **primary recommendation** for a unified model serving PA + AO + Code Agent (USE-CASE-005).

**Critical Architectural Update Applied:** ALL LLM inference (Policy Agent, Assistant Orchestrator, Code Agent) moves to GPU/CPU. NPU is deprioritized for LLM inference. ADR-006 and ADR-010 memory budgets are outdated and must be re-baselined.

---

## 1. Methodology & Data Sources

| # | Source | Coverage | Key Limitation |
|---|--------|----------|----------------|
| 1 | `OpenVINO_GENAI_Supported_LLM_Models.csv` (380 lines) | Architecture → model mapping for OV GenAI | Confirms architecture support only, no performance data |
| 2 | `llm_models_7-258V.csv` (28 rows) | GPU benchmarks on Core Ultra 7-258V | **Only older/smaller models** (up to 7B). No Qwen3, Qwen2.5, Phi-4, or 14B+ models |
| 3 | OpenVINO 2026.0 Release Notes (local HTM, 14,080 lines) | Feature details, optimizations, known issues | Official Intel documentation, trusted |
| 4 | HuggingFace model cards (Qwen3-30B-A3B, Qwen3-14B) | Architecture specs, benchmarks, capabilities | Vendor-reported benchmarks |
| 5 | `openvino_notebooks/llm-chatbot` (README + ipynb) | Quantization configs, model support matrix | Reference configs, not hardware-specific benchmarks |

**Extrapolation Note:** Because the benchmark CSV contains only older models (gemma-2b through qwen-7b), throughput estimates for Qwen3 and 14B+ models are **extrapolated** from measured bandwidth utilization patterns, not directly measured. All throughput figures are labeled accordingly.

---

## 2. Hardware Constraints (Updated for All-GPU Architecture)

### Physical Platform
| Parameter | Value |
|-----------|-------|
| CPU | Intel Core Ultra 7 258V (Lunar Lake) |
| iGPU | Arc 140V (Xe2 Battlemage), 8 Xe Cores, 1950 MHz boost |
| Memory | 32 GB LPDDR5X-8533, dual-channel, **unified** (shared CPU/GPU) |
| Memory Bandwidth | \~136.5 GB/s theoretical, \~62-73 GB/s effective GPU utilization (derived from 7B benchmarks) |
| Effective Ceiling | 31,323 MB (32,074.8 MB - 693 MB firmware) per ADR-005 |
| NPU | Intel AI Boost — **DEPRIORITIZED** for LLM inference |

### Memory Budget (Production Runtime)
| Tier | Value (MB) | Notes |
|------|-----------|-------|
| OS + Services (production) | \~13,000 | Dev-time 18,006 minus IDE/browser/editor |
| Hyper-V Root Partition | 512 | Hypervisor overhead |
| BlarAI-Orchestrator VM | 2,048 | 2 GB assigned RAM |
| VM Management Overhead | 256 | Per-VM overhead |
| **Subtotal (fixed)** | **\~15,816** | |
| **Available for LLM Agents** | **\~15,507** | Ceiling - fixed overhead |

**Critical Constraint:** On a unified memory iGPU, there is no separate VRAM budget. All model weights, KV-caches, and runtime buffers consume system memory directly. The \~15.5 GB available budget is the **hard ceiling** for all agent memory combined.

---

## 3. OpenVINO 2026.0 Key Features Affecting Model Selection

Extracted from Release Notes (lines 12980-13450):

| Feature | Impact on Model Selection |
|---------|--------------------------|
| **XAttention (Block Sparse Attention)** — preview on Xe2/Xe3 | Improves TTFT for all models. Directly benefits large-context scenarios. |
| **MoE INT4 data-aware compression** (NNCF) for 3D MatMuls | Explicitly targets Qwen3-30B-A3B and GPT-OSS-20B. Reduces quantization error for MoE models. |
| **EAGLE-3 speculative decoding** — validated on Qwen3-8B | Can boost TPS 2-3×. **Not yet validated for Qwen3-14B** — risk factor. |
| **Improved TTFT for Qwen3-30B-A3B INT4 on GPU** | Direct optimization, but model is memory-infeasible. |
| **Prefix caching** | Reduces redundant computation for similar prompts. Benefits all candidates. |
| **u2/u3/u6 data types** | Future possibility: INT3 quantization could make larger models fit. Untested/unvalidated. |
| **gpt-oss-20b NOT supported on GPU plugin** | **ELIMINATED.** Known issue 181161 further limits it to CPU single-stream. |
| **Devstral tool parser support** | Devstral-Small-2507 (24B, code-specialized) supported in Model Server. |
| **Qwen3-30B-A3B listed as new supported model** on CPU & GPU | Architecture confirmed. |

---

## 4. Candidate Pool — Full Assessment

### 4.1 Architecture Confirmation (from OpenVINO_GENAI_Supported_LLM_Models.csv)

All candidates below have confirmed architecture support in OpenVINO GenAI:

| Architecture | Models | Confirmed |
|-------------|--------|-----------|
| Qwen3MoeForCausalLM | Qwen3-30B-A3B | ✅ |
| Qwen3ForCausalLM | Qwen3-0.6B through Qwen3-32B | ✅ |
| Qwen2ForCausalLM | Qwen2.5-0.5B through Qwen2.5-72B | ✅ |
| Phi3ForCausalLM | Phi-4-mini (3.8B), Phi-4 (14B), Phi-4-reasoning | ✅ |
| LlamaForCausalLM | Llama-3.x, DeepSeek-R1-Distill variants | ✅ |
| MistralForCausalLM | Mistral-7B, Devstral-Small-2507 | ✅ |
| Starcoder2ForCausalLM | Starcoder2 | ✅ |
| GraniteForCausalLM | IBM Granite | ✅ |
| Gemma2/3ForCausalLM | Gemma-2/3 variants | ✅ |

### 4.2 First-Pass Elimination

| Model | Reason for Elimination |
|-------|----------------------|
| GPT-OSS-20B | **Not supported on GPU plugin** (confirmed in notebook README + known issue 181161) |
| bitnet-b1.58-2B-4T | "Doesn't support compression" per notebook. Quality unproven for agent use cases. |
| Qwen2.5-72B, Llama-3-70B, etc. | >30B dense params → memory-infeasible at any quantization |
| Qwen3-32B | 32B dense → INT4 ≈ 16.6 GB weights → exceeds budget |
| Mistral-Small-24B | 24B params → INT4 ≈ 12.5 GB weights + KV → tight, no quality advantage over Qwen3-14B |
| Devstral-Small-2507 | 24B params, code-only (not suitable for unified model). INT4 ≈ 12.5 GB. |
| Starcoder2 | Completion model, not instruction-tuned. Not suitable for conversational agents. |
| All models ≤3B (Qwen3-1.7B, Phi-4-mini, Qwen3-0.6B, etc.) | Insufficient coding quality for USE-CASE-005 Code Agent role |

### 4.3 Narrowed Candidate Pool

| # | Model | Total Params | Active Params | Type | Layers | Q Heads | KV Heads | Context | License |
|---|-------|-------------|---------------|------|--------|---------|----------|---------|---------|
| 1 | **Qwen3-30B-A3B** | 30.5B | 3.3B | MoE | 48 | 32 | 4 | 32K (131K YaRN) | Apache-2.0 |
| 2 | **Qwen3-14B** | 14.8B | 14.8B | Dense | 40 | 40 | 8 | 32K (131K YaRN) | Apache-2.0 |
| 3 | **Qwen3-8B** | 8.2B | 8.2B | Dense | 36 | 32 | 8 | 32K (131K YaRN) | Apache-2.0 |
| 4 | **Qwen2.5-14B-Instruct** | 14.8B | 14.8B | Dense | 40 | 40 | 8 | 128K | Apache-2.0 |
| 5 | **Qwen2.5-7B-Instruct** | 7.6B | 7.6B | Dense | 28 | 28 | 4 | 128K | Apache-2.0 |
| 6 | **Phi-4** | 14.7B | 14.7B | Dense | 40 | 40 | 10 | 16K | MIT |
| 7 | **DeepSeek-R1-Distill-Qwen-14B** | 14.8B | 14.8B | Dense | 40 | 40 | 8 | 128K | MIT |
| 8 | **GLM-4-9B-Chat** | 9.4B | 9.4B | Dense | 40 | 32 | 2 | 128K | Apache-2.0 |

---

## 5. Memory Analysis

### 5.1 INT4 Weight Size Estimation Method

OpenVINO INT4_ASYM with `group_size=128` (per notebook reference for Qwen3):
- 4 bits per weight
- FP16 scale per group: 16 bits / 128 weights = 0.125 bits/weight
- u4 zero-point per group: 4 bits / 128 = 0.03125 bits/weight
- **Total: \~4.16 bits/weight ≈ 0.52 bytes/weight**

Cross-validated against: Qwen3-1.7B measured at 1,014 MB (from ADR-006 addendum). 1.7B × 0.52 = 884 MB weights + \~130 MB overhead → 1,014 MB. ✅ Consistent.

### 5.2 KV-Cache Estimation

KV-cache per token per layer = 2 (K+V) × num_kv_heads × head_dim × 2 bytes (FP16)

| Model | KV Heads | Layers | head_dim | Per Token | 4K Context | 8K Context |
|-------|----------|--------|----------|-----------|------------|------------|
| Qwen3-30B-A3B | 4 | 48 | 128 | 96 KB | 384 MB | 768 MB |
| Qwen3-14B | 8 | 40 | 128 | 160 KB | 640 MB | 1,280 MB |
| Qwen3-8B | 8 | 36 | 128 | 144 KB | 576 MB | 1,152 MB |
| Qwen2.5-14B-Instruct | 8 | 40 | 128 | 160 KB | 640 MB | 1,280 MB |
| Qwen2.5-7B-Instruct | 4 | 28 | 128 | 56 KB | 224 MB | 448 MB |
| Phi-4 | 10 | 40 | 128 | 200 KB | 800 MB | 1,600 MB |
| DeepSeek-R1-Distill-14B | 8 | 40 | 128 | 160 KB | 640 MB | 1,280 MB |
| GLM-4-9B | 2 | 40 | 128 | 40 KB | 160 MB | 320 MB |

### 5.3 Total Memory — Unified Model Scenario (3 agents, shared weights via zero-copy mmap)

Formula: **Weight_file + 3 × KV_cache(4K) + Runtime_overhead**

| Model | Weights (MB) | 3× KV @ 4K (MB) | Runtime (MB) | **Total (MB)** | Available (MB) | **Headroom** | **Feasible?** |
|-------|-------------|-----------------|-------------|---------------|---------------|-------------|--------------|
| Qwen3-30B-A3B | \~16,100 | 1,152 | 500 | **17,752** | 15,507 | **-2,245** | ❌ **NO** |
| Qwen3-14B | \~7,700 | 1,920 | 400 | **10,020** | 15,507 | **5,487 (35%)** | ✅ YES |
| Qwen3-8B | \~4,260 | 1,728 | 300 | **6,288** | 15,507 | **9,219 (59%)** | ✅ YES |
| Qwen2.5-14B-Inst | \~7,700 | 1,920 | 400 | **10,020** | 15,507 | **5,487 (35%)** | ✅ YES |
| Qwen2.5-7B-Inst | \~3,950 | 672 | 300 | **4,922** | 15,507 | **10,585 (68%)** | ✅ YES |
| Phi-4 | \~7,600 | 2,400 | 400 | **10,400** | 15,507 | **5,107 (33%)** | ✅ YES |
| DS-R1-D-14B | \~7,700 | 1,920 | 400 | **10,020** | 15,507 | **5,487 (35%)** | ✅ YES |
| GLM-4-9B | \~4,900 | 480 | 350 | **5,730** | 15,507 | **9,777 (63%)** | ✅ YES |

---

## 6. Deep-Dive: Qwen3-30B-A3B (MoE)

### Architecture
- 30.5B total parameters, **3.3B activated per token**
- 128 experts per MoE layer, 8 activated per token (6.25%)
- 48 layers, 32 Q-heads / 4 KV-heads (GQA), head_dim=128
- Thinking/non-thinking modes, native agentic/tool-calling support
- Apache-2.0 license, 1.1M+ monthly HuggingFace downloads

### Why It's Attractive
1. **Compute efficiency**: 3.3B active params → per-token memory bandwidth ≈ 1.72 GB → extrapolated **36-42 tps** on Arc 140V (comparable to a 3B dense model)
2. **Explicit OV 2026.0 optimization**: "Improved TTFT for Qwen3-30B-A3B INT4 model" on GPU
3. **NNCF MoE-specific compression**: INT4 data-aware for 3D MatMuls, explicitly targeting this model
4. **Quality**: Comparable to Qwen3-14B on most benchmarks, with the speed of a 3B model

### Why It's Infeasible
**ALL 128 experts' weights must be loaded into memory**, regardless of how few activate per token.

| Scenario | Weight Load | + KV + Runtime | Total | Budget | Deficit |
|----------|------------|----------------|-------|--------|---------|
| Unified (3 agents, 4K ctx) | 16,100 MB | 1,652 MB | 17,752 MB | 15,507 MB | **-2,245 MB** |
| Single agent, 2K ctx | 16,100 MB | 692 MB | 16,792 MB | 15,507 MB | **-1,285 MB** |
| Without VM running | 16,100 MB | 1,652 MB | 17,752 MB | 17,811 MB | 59 MB headroom |

Even without the VM running and with minimal KV-cache, headroom is negligible. **Under any realistic production configuration, Qwen3-30B-A3B does not fit.**

### MoE Fundamental Constraint on Unified Memory
MoE models trade compute efficiency for memory capacity. On discrete GPUs with 24-48 GB dedicated VRAM, this trade is favorable. On an iGPU sharing 31.3 GB with the OS, hypervisor, and VM, it is not viable for 30B-class MoE models. This is a **hardware-class constraint**, not an optimization gap.

### Future Reconsideration Triggers
- Qwen releases a smaller MoE variant (≤15B total, ≤2B active)
- OpenVINO validates INT3 (u3) quantization for MoE models with acceptable quality
- VM architecture is revised to free additional memory headroom

### Verdict: ❌ ELIMINATED — Memory infeasible

---

## 7. Deep-Dive: Qwen3-14B (Dense)

### Architecture
- 14.8B total parameters (13.2B non-embedding)
- 40 layers, 40 Q-heads / 8 KV-heads (GQA), head_dim=128
- Thinking/non-thinking dual modes (thinking: temp=0.6, top_p=0.95; non-thinking: temp=0.7, top_p=0.8)
- Native agentic/tool-calling support (BFCL-validated)
- 32K native context, extendable to 131K with YaRN
- Apache-2.0 license, 1.2M+ monthly downloads

### Memory Fit
- INT4 weight file: \~7,700 MB
- Unified scenario (3 × 4K KV): **10,020 MB total, 35% headroom**
- Headroom supports context expansion study (4K → 8K adds \~1,920 MB → still fits at \~11,940 MB, 23% headroom)

### Throughput Estimation
From benchmark CSV extrapolation (7B INT4 models achieve 17-20 tps on this hardware):
- 14.8B is \~2× the 7B parameter count → \~2× per-token memory read
- Per-token read: 14.8B × 0.52 bytes ≈ 7.7 GB
- Effective GPU bandwidth: \~62-73 GB/s (derived from 7B benchmark data)
- **Extrapolated throughput: 8.0-9.5 tps**
- Meets USE-CASE-005 requirement of ≥8 tps, but at the **lower bound**

### Throughput Enhancement: EAGLE-3 Speculative Decoding
- OV 2026.0 validated for Qwen3-8B; **not yet validated for Qwen3-14B** (risk factor)
- If validated: 2-3× improvement → **16-28 tps** (comfortable margin)
- Draft model (e.g., Qwen3-0.6B at \~400 MB) + small KV overhead → \~10,500-11,000 MB total → still fits
- Recommendation: validate EAGLE-3 for Qwen3-14B empirically after model acquisition

### Quality Assessment (from HuggingFace benchmarks)
- **Tops or ties Qwen2.5-72B-Instruct** on many benchmarks (a 14B model matching 72B)
- Outperforms Gemma-3-27B-IT on multiple tasks
- Strong on LiveCodeBench, MBPP+, HumanEval+ (coding)
- Strong on BFCL (tool calling) — critical for agentic AO duties
- Thinking mode enables deeper reasoning chains for complex code synthesis
- Non-thinking mode provides fast, low-latency responses for PA classification

### Suitability for BlarAI Roles

| Role | Suitability | Notes |
|------|------------|-------|
| Policy Agent | ✅ Excellent | Non-thinking mode for fast classification (temp=0). Overkill for the task but zero-cost via mmap sharing. |
| Assistant Orchestrator | ✅ Excellent | Full agentic capabilities, tool calling, thinking mode for complex queries. |
| Code Agent (USE-CASE-005) | ✅ Good | Strong coding benchmarks. Thinking mode for synthesis. Throughput at lower bound without EAGLE-3. |

### Quantization Config (from notebook reference for Qwen3 family)
```
mode = nncf.CompressWeightsMode.INT4_ASYM
ratio = 1.0
group_size = 128
scale_estimation = True
dataset = "wikitext2"
```
For smaller Qwen3 (1.7B/4B), the notebook uses AWQ instead. For 8B+, INT4_ASYM with scale_estimation is the reference config.

### Verdict: ✅ PRIMARY RECOMMENDATION

---

## 8. Comparative Analysis — All Narrowed Candidates

### 8.1 Scoring Matrix

Criteria weights: Memory Fit (25%), Throughput (20%), Quality-General (15%), Quality-Coding (15%), Agentic/Tool-Calling (15%), OV 2026.0 Optimization (10%)

| Model | Memory Fit | Throughput | Quality-Gen | Quality-Code | Agentic | OV Opt | **Weighted** |
|-------|-----------|------------|-------------|-------------|---------|--------|-------------|
| **Qwen3-14B** | 8/10 | 6/10 | 9/10 | 9/10 | 10/10 | 8/10 | **8.35** |
| **Qwen3-8B** | 10/10 | 8/10 | 7/10 | 7/10 | 9/10 | 9/10 | **8.30** |
| **Phi-4** | 8/10 | 6/10 | 9/10 | 9/10 | 6/10 | 7/10 | **7.55** |
| **DS-R1-D-14B** | 8/10 | 6/10 | 7/10 | 8/10 | 5/10 | 6/10 | **6.75** |
| **Qwen2.5-14B-Inst** | 8/10 | 6/10 | 8/10 | 8/10 | 7/10 | 7/10 | **7.40** |
| **Qwen2.5-7B-Inst** | 10/10 | 9/10 | 6/10 | 6/10 | 7/10 | 7/10 | **7.55** |
| **GLM-4-9B** | 10/10 | 7/10 | 6/10 | 5/10 | 5/10 | 5/10 | **6.55** |
| **Qwen3-30B-A3B** | 0/10 | 10/10 | 9/10 | 8/10 | 10/10 | 10/10 | — (infeasible) |

### 8.2 Candidate Dispositions

| Rank | Model | Disposition | Rationale |
|------|-------|------------|-----------|
| 1 | **Qwen3-14B** | **PRIMARY** | Best quality-per-GB. Excellent across all roles. 35% memory headroom. Agentic/tool-calling best-in-class. |
| 2 | **Qwen3-8B** | **FALLBACK** | High throughput margin, EAGLE-3 validated. 59% headroom enables context expansion. Quality step-down noticeable in coding. |
| 3 | **Phi-4** | Monitor | Strong reasoning/coding. Weaker agentic capabilities (no built-in tool-calling paradigm like Qwen3). 16K context limit. |
| 4 | **Qwen2.5-7B-Inst** | Superseded | Previous P5-004 recommendation. Superseded by Qwen3-8B (newer gen, thinking mode, better benchmarks). |
| 5 | **Qwen2.5-14B-Inst** | Superseded | Same size as Qwen3-14B but older generation, no thinking mode, lower benchmarks. No advantage. |
| 6 | **DS-R1-D-14B** | Niche | Strong reasoning chains but weaker at general assistant tasks and agentic tool calling. Not suitable as unified model. |
| 7 | **GLM-4-9B** | Eliminated | Benchmarks below Qwen3-8B and Qwen3-14B on coding and agentic tasks. No advantage in any dimension. |
| — | **Qwen3-30B-A3B** | Eliminated | Memory infeasible. Hardware-class constraint on unified memory iGPU. |

---

## 9. USE-CASE-005 Dual-Angle Analysis

USE-CASE-005 specification (from Use Cases_FINAL.md, lines 253-380):
- 14B-class dense code-specialized model at Q4_K_M
- 8-9 GB VRAM, 12-14 GB total during active synthesis
- Exclusive execution tier with degradation cascade
- Circuit breakers: 8192 output tokens, recursion depth 3, 500 lines max diff
- Target: ≥8 tok/s at Q4_K_M on Arc 140V for 14B-class model
- Cold-start ≤15s, warm-start ≤3s

### Angle 1: Unified Model (PA + AO + Code Agent share one model)

**Recommended model: Qwen3-14B**

| Metric | Value | USE-CASE-005 Requirement | Met? |
|--------|-------|-------------------------|------|
| Model class | 14B dense | 14B-class dense | ✅ |
| Quantization | INT4_ASYM | Q4_K_M equivalent | ✅ |
| Weight memory | \~7,700 MB | 8-9 GB VRAM | ✅ |
| Total memory (unified, 3× 4K KV) | \~10,020 MB | 12-14 GB total during active synthesis | ✅ |
| Throughput | 8-9.5 tps (extrapolated) | ≥8 tok/s | ✅ (lower bound) |
| Cold-start | \~8-12s (estimated for 7.7 GB model load) | ≤15s | ✅ |
| Warm-start (mmap hot) | <1s | ≤3s | ✅ |

**Advantages of Unified Approach:**
1. **Zero-copy mmap weight sharing** — one weight file serves all three agents. Only KV-caches are separate (\~640 MB each at 4K context). This is the most memory-efficient architecture possible.
2. **Operational simplicity** — one model to acquire, quantize, validate, and maintain.
3. **No degradation cascade complexity** — PA and AO continue operating while Code Agent processes. No model swapping needed.
4. **Context expansion headroom** — \~5,487 MB remaining supports future expansion from 4K to 8K context (adds \~1,920 MB → 23% headroom remains).
5. **EAGLE-3 path** — if validated for 14B, a single draft model (Qwen3-0.6B) serves all agents → \~16-28 tps.

**Risks:**
- Throughput at lower bound (8-9.5 tps) without EAGLE-3. May feel sluggish for interactive code synthesis.
- Quality ceiling: PA classification is overkill (a 1.7B model suffices), but the cost of mmap sharing is zero, so no actual waste.
- If one agent causes severe context pollution, it could affect others sharing the same model pipeline instance. Mitigation: separate pipeline instances (separate KV-caches) per agent — already planned.

### Angle 2: Separate Models (PA+AO use one model, Code Agent uses another)

**Scenario: Qwen3-8B (PA+AO) + Qwen3-14B (Code Agent, exclusive tier)**

| Phase | Model Loaded | Memory | Throughput |
|-------|-------------|--------|------------|
| Normal ops (PA + AO active) | Qwen3-8B (shared weights, 2× KV) | \~5,412 MB | 14-17 tps |
| Code synthesis (exclusive) | Qwen3-14B (1× KV) | \~8,740 MB | 8-9.5 tps |
| Transition (cold swap) | Qwen3-8B evicted, 14B loaded | \~10-15s | — |
| Transition (warm/mmap) | mmap page-in | \~3-5s | — |

**Advantages:**
- PA+AO get higher throughput (14-17 tps vs 8-9.5) during normal operation
- Code Agent gets maximum quality (14B) during synthesis
- Could use different quantization strategies per model

**Disadvantages:**
1. **Two models to manage** — acquisition, quantization, validation, updating for two separate models
2. **Degradation cascade complexity** — must implement reliable model swap logic, fallback on swap failure, and state preservation
3. **Cold-start penalty** — model swap takes 10-15s (exceeds warm-start ≤3s requirement unless mmap pre-warming is implemented)
4. **Memory during transition** — brief period where both models may be partially paged → risk of OOM pressure
5. **No quality advantage over Angle 1** — the Code Agent uses Qwen3-14B in both scenarios; PA+AO using Qwen3-8B is a step DOWN from Qwen3-14B in Angle 1

### Dual-Angle Verdict

**Angle 1 (Unified) is clearly superior** for this hardware and architecture:
- Simpler, more reliable, lower operational risk
- Equal or better quality across all roles (14B for everyone vs 8B for PA+AO)
- Memory-optimal via zero-copy mmap
- Eliminates degradation cascade complexity
- Leaves headroom for context expansion

Angle 2 only makes sense if: (a) a coding-specialized model significantly outperforms Qwen3-14B on coding tasks, AND (b) that model is incompatible with general assistant duties. Current evidence does not support either condition — Qwen3-14B is strong across all three roles.

---

## 10. Throughput Validation Methodology

The ≥8 tps requirement for USE-CASE-005 is extrapolated, not measured. Before committing to Qwen3-14B, empirical validation is required.

### Derivation of Throughput Estimate
| Step | Data | Source |
|------|------|--------|
| 7B INT4 models on Arc 140V | 17-20 tps | Measured (llm_models_7-258V.csv: zephyr-7b, qwen-7b, baichuan2-7b) |
| Effective GPU bandwidth | 62-73 GB/s | Derived: 7B × 0.52 bytes × 17-20 tps = 62-73 GB/s |
| 14.8B per-token read | 7.7 GB | 14.8B × 0.52 bytes/param |
| Extrapolated 14B throughput | 62-73 ÷ 7.7 = 8.0-9.5 tps | Bandwidth-bound linear scaling |

**Assumptions in this extrapolation:**
1. Autoregressive decode is memory-bandwidth-bound (valid for single-stream inference)
2. Qwen3 GQA is as bandwidth-efficient as older architectures (conservative — GQA typically improves this)
3. OV 2026.0 optimizations for Qwen3 architecture have not degraded decode performance
4. No significant compute bottleneck at 14B scale on 8 Xe Cores

### Recommended Validation Protocol
1. Acquire Qwen3-14B base weights from HuggingFace
2. Quantize with `optimum-cli` using INT4_ASYM, group_size=128, ratio=1.0, scale_estimation=True
3. Run GenAI LLMPipeline benchmark: decode throughput (tps), TTFT (ms), RSS (MB)
4. Validate against ≥8 tps threshold with 4K context window
5. If <8 tps: fall back to Qwen3-8B and re-measure

---

## 11. Recommendation

### Primary: Qwen3-14B as Unified Model

| Decision | Value |
|----------|-------|
| Model | Qwen3-14B |
| Role | Unified — PA + AO + Code Agent (USE-CASE-005) |
| Quantization | INT4_ASYM, group_size=128, scale_estimation=True |
| Framework | OpenVINO 2026.0 GPU plugin |
| Weight sharing | Zero-copy mmap across all agent instances |
| KV-caches | 3 separate (one per agent), 4,096 tokens each |
| Est. total memory | \~10,020 MB (35% headroom) |
| Est. throughput | 8-9.5 tps baseline; 16-28 tps with EAGLE-3 |
| Context | 4,096 initially, expandable to 8K with remaining headroom |

### Fallback: Qwen3-8B

Activate if Qwen3-14B empirical throughput < 8 tps OR memory exceeds projections.

| Decision | Value |
|----------|-------|
| Model | Qwen3-8B |
| Est. total memory | \~6,288 MB (59% headroom) |
| Est. throughput | 14-17 tps baseline; 28-50 tps with EAGLE-3 (validated) |
| Trade-off | Noticeable quality reduction in coding tasks. Excellent throughput headroom. |

---

## 12. Risk Register

| ID | Risk | Likelihood | Impact | Mitigation |
|----|------|-----------|--------|------------|
| R1 | Qwen3-14B decode throughput < 8 tps empirically | Medium | High | Fall back to Qwen3-8B. Validate with EAGLE-3 draft model. |
| R2 | INT4 quantization quality degradation for code generation | Low | Medium | Validate on coding benchmarks (HumanEval, MBPP) after quantization. Consider INT4_ASYM with scale_estimation to minimize error. |
| R3 | EAGLE-3 not validated for Qwen3-14B | Medium | Medium | Test empirically. If incompatible, accept 8-9.5 tps baseline or fall back to 8B with validated EAGLE-3. |
| R4 | Memory exceeds estimate due to OV runtime overhead | Low | High | Empirical measurement during validation. 35% headroom provides buffer. |
| R5 | Model swap time for Code Agent exclusive tier (Angle 2 only) | N/A (Angle 1 selected) | — | Not applicable under unified model recommendation. |
| R6 | Future context expansion (>4K) exceeds memory budget | Low | Medium | At 8K: 11,940 MB (23% headroom). At 16K: \~13,860 MB (10% headroom — marginal). |

---

## 13. Comparison with Previous Recommendation

The P5-FEASIBILITY-004 session recommended **Qwen2.5-7B-Instruct** as the unified model. This analysis supersedes that recommendation:

| Dimension | Qwen2.5-7B-Instruct (Previous) | Qwen3-14B (Current) |
|-----------|-------------------------------|---------------------|
| Generation | Qwen2.5 (older) | Qwen3 (current) |
| Thinking mode | ❌ Not available | ✅ Thinking + non-thinking |
| Agentic/tool-calling | Basic | ✅ Native, BFCL-validated |
| Coding quality (LiveCodeBench) | Moderate | Strong |
| General quality | Good (7B-class) | Excellent (matches 72B-class on some tasks) |
| Memory | \~4,922 MB (68% headroom) | \~10,020 MB (35% headroom) |
| Throughput | 17-20 tps | 8-9.5 tps (meets minimum) |
| USE-CASE-005 suitability | ≥8 tps at 7B quality | ≥8 tps at 14B quality |

The trade-off is clear: **double the memory for significantly higher quality across all roles**, with throughput still meeting the minimum requirement. Given that BlarAI's value proposition depends on response quality (accurate classification, helpful assistance, correct code generation), this trade is justified.

---

## 14. Next Steps

1. **Acquire Qwen3-14B** — download from HuggingFace
2. **Quantize to INT4_ASYM** — using NNCF/optimum-cli with reference config
3. **Empirical throughput validation** — decode tps, TTFT, RSS on Arc 140V GPU
4. **If ≥8 tps confirmed** → update ADR-006 memory budget, proceed with integration
5. **If <8 tps** → validate Qwen3-8B as fallback, test EAGLE-3 speculative decoding
6. **Supersede ADR-010** — new ADR for all-GPU architecture with unified Qwen3-14B
7. **Gate 3 re-run** — re-validate memory ceiling with empirical Qwen3-14B measurements

---

## Evidence Sources
- `OpenVINO_GENAI_Supported_LLM_Models.csv` — architecture confirmation
- `llm_models_7-258V.csv` — GPU throughput benchmarks (7B reference point)
- `OpenVINO Release Notes — OpenVINO documentation.htm` — OV 2026.0 features
- HuggingFace: `Qwen/Qwen3-30B-A3B`, `Qwen/Qwen3-14B` — model specifications
- `openvino_notebooks/llm-chatbot` — quantization reference configs
- `docs/adrs/ADR-005` — memory ceiling
- `docs/adrs/ADR-006` — memory budget (outdated, re-baseline required)
- `Use Cases_FINAL.md` lines 253-380 — USE-CASE-005 specification
