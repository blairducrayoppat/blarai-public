# P5-FEASIBILITY-001 — Context Window Expansion Study (Input + Output)

**Date:** 2026-02-25  
**Branch:** `feature/p1-uat1-launcher`  
**Scope:** Analytical feasibility only (no implementation changes)

---

## 1) Objective and Constraints

This study evaluates whether the Assistant Orchestrator token hard-caps can be expanded beyond current limits:

- **Input context window:** 4,096 tokens
- **Output generation cap:** 4,096 tokens (host profile), 256 tokens (guest runtime profile)

Locked constraints applied:

- **ADR-005:** Effective memory ceiling = 31.323 GB
- **ADR-006:** Worst-case headroom = 1,459 MB (with architecturally committed reservations)
- **ADR-010:** PA on GPU, Orchestrator on NPU
- **Privacy / fail-closed:** no external network calls, deny on ambiguity/failure
- **PGOV:** 6-stage output-only validator; no input-token validation stage

Non-goals respected:

- No changes to source/config/constants
- No VM startup or live runtime experiments
- No model migration proposal (Qwen3 presence noted only)
- No Semantic Router context-limit expansion analysis

---

## 2) Current Limit Architecture (Verified)

### Input context

- **Primary enforcement:** `ContextManager.trim_to_budget()` FIFO eviction in `services/assistant_orchestrator/src/context_manager.py`
- **Config limits:** `[context].max_context_tokens=4096` and `[npu].max_context_tokens=4096` in both orchestrator TOML profiles
- **Composition:** system prompt (~270 tokens) + conversation turns + grounded chunks

### Output generation

- **Primary enforcement:** `effective_max = min(request_max, instance_cap)` in `services/assistant_orchestrator/src/npu_inference.py`
- **Secondary enforcement:** `CircuitBreaker(max_output_tokens)` in `services/assistant_orchestrator/src/circuit_breaker.py`
- **Post-generation enforcement:** PGOV Stage 1 (`token_count <= max_tokens`) in `services/assistant_orchestrator/src/pgov.py`
- **Config-load hard ceiling:** `max_new_tokens` in range `[1, 4096]` in `services/assistant_orchestrator/src/entrypoint.py`

### Security gate placement

- **Input path:** Policy Agent adjudicates CAR payload before Orchestrator handling (`services/policy_agent/src/entrypoint.py`)
- **Output path:** PGOV validates generated output before release (`services/assistant_orchestrator/src/pgov.py`)

---

## 3) Step 1 — KV-Cache Memory Analysis

## 3.1 Verified model architecture (from `models/qwen2.5-1.5b-instruct/openvino-int4-npu/config.json`)

- `num_hidden_layers = 28`
- `num_attention_heads = 12`
- `num_key_value_heads = 2` (**critical: grouped-query/multi-query KV, not 12**)
- `hidden_size = 1536`
- `max_position_embeddings = 32768`

Derived head dimension:

- `head_dim = hidden_size / num_attention_heads = 1536 / 12 = 128`

## 3.2 KV-cache bytes per token

Using FP16 KV cache:

- `bytes_per_token = 2 (K+V) * layers * kv_heads * head_dim * 2 bytes`
- `bytes_per_token = 2 * 28 * 2 * 128 * 2 = 28,672 bytes/token`

## 3.3 KV-cache size by context length

| Context tokens | KV bytes | KV MiB | KV MB (decimal) |
|---:|---:|---:|---:|
| 4,096 | 117,440,512 | 112.0 | 117.44 |
| 8,192 | 234,881,024 | 224.0 | 234.88 |
| 16,384 | 469,762,048 | 448.0 | 469.76 |
| 32,768 | 939,524,096 | 896.0 | 939.52 |

## 3.4 Budget threshold checks

- **KV-only vs 1,024 MB budget:**
  - 1,024 MB / 28,672 B ≈ **35,714 tokens** (decimal MB basis)
  - 1 GiB / 28,672 B ≈ **37,449 tokens** (binary basis)
  - Model hard cap is 32,768, so **KV-cache alone does not exceed 1,024 MB within model range**.

- **But total Orchestrator memory is constrained by weights + KV + runtime overhead:**
  - Measured model weights ≈ **975.6 MB**
  - At 4K context, weights + KV ≈ **1,093.0 MB** (already above 1,024 MB before runtime overhead)

**Step-1 conclusion:** KV-cache-only is not the binding constraint; **combined Orchestrator memory footprint is**.

---

## 4) Step 2 — NPU Inference Latency Analysis

Evidence baseline: `phase2_gates/evidence/npu_latency_benchmark.json`

Relevant measured points (NPU):

- Config `F` (`max_new_tokens=32`): mean **579.7 ms**, P95 **735.9 ms**, P99 **750.8 ms**
- Config `I` (`max_new_tokens=8`): mean **543.4 ms**, P95 **646.2 ms**, P99 **703.3 ms**

## 4.1 Input context expansion impact (theoretical scaling)

For transformer attention:

- Prefill complexity ~ `O(n^2)` with sequence length `n`
- Decode per-token complexity ~ `O(n)` with existing KV length

Relative multipliers vs 4K baseline:

| Context | Prefill factor (`n^2`) | Decode/token factor (`n`) |
|---:|---:|---:|
| 8K | 4x | 2x |
| 16K | 16x | 4x |
| 32K | 64x | 8x |

Implications:

- **TTFT (time-to-first-token)** is prefill-dominated and therefore trends with the quadratic factor.
- Existing warm/cold operational budgets (`ORCH_FIRST_TOKEN_WARM_MS=1000`, `ORCH_FIRST_TOKEN_COLD_MS=1500`) are likely violated if context is materially increased without architectural changes.
- Intel NPU SRAM constraints increase risk of KV spill to system memory at higher lengths, which can produce latency cliffs; exact spill thresholds are not determinable from current artifacts alone.

## 4.2 Output cap expansion impact (empirical wall-clock projection)

Output cap increases do **not** raise prefill cost; they extend decode duration.

Using NPU benchmark points (`8 -> 543.4 ms`, `32 -> 579.7 ms`) and fitting:

- `total_time_ms ≈ 531.3 + 1.5125 * output_tokens`
- Implied steady-state decode ≈ **661 tokens/sec** after fixed overhead

Projected generation times:

| Output tokens | Projected total time |
|---:|---:|
| 256 | 0.92 s |
| 4,096 | 6.73 s |
| 8,192 | 12.92 s |

Interpretation:

- Increasing output cap from 4,096 to 8,192 approximately doubles response wall-clock under this model.
- Long-output requests increase runtime occupancy and reduce interactive responsiveness even if TTFT is unchanged.

---

## 5) Step 3 — Security Surface Analysis

## 5.1 Input context expansion

1. **Policy Agent coverage boundary:** PA adjudicates the raw request CAR before orchestration. Expanding retained conversation context does not proportionally increase PA visibility because PA is not validating the full assembled model context window.
2. **Multi-turn injection persistence:** Larger retained history allows adversarial prompt fragments to survive longer across turns, increasing long-horizon injection surface.
3. **System prompt dilution:** At 4,096 tokens, ~270-token system prompt is ~6.6% of context. At 16K, ~1.7%. Lower instruction ratio can reduce instruction-following robustness in long contexts.

## 5.2 Output cap expansion

4. **PGOV Stage 1 token gate:** Expanding cap permits longer outputs by policy; this increases potential exposure volume per response.
5. **Stages 2-6 scaling:** Regex/delimiter/tool checks process full text; cost scales roughly with output length, increasing validation latency and CPU cost.
6. **Leakage detector truncation risk:** Stage 5 embedding path tokenizes with `truncation=True, max_length=128`; long outputs are only partially represented in the leakage embedding check, increasing bypass risk as output grows.

## 5.3 Combined expansion

7. Larger input + larger output increases per-request token throughput and sustained compute occupancy, raising local resource-exhaustion risk (single-user DoS-by-workload), even without external adversary traffic.

---

## 6) Step 4 — System Memory Budget Impact

Baseline references from ADR-006:

- Effective ceiling: 31.323 GB
- Worst-case headroom: 1,459 MB
- Orchestrator budget placeholder: 1,024 MB

## 6.1 Orchestrator combined footprint (weights + KV only)

| Context | Weights MB | KV MB | Weights+KV MB | Delta vs 1,024 MB budget |
|---:|---:|---:|---:|---:|
| 4,096 | 975.6 | 117.44 | 1,093.04 | +69.04 MB |
| 8,192 | 975.6 | 234.88 | 1,210.48 | +186.48 MB |
| 16,384 | 975.6 | 469.76 | 1,445.36 | +421.36 MB |
| 32,768 | 975.6 | 939.52 | 1,915.12 | +891.12 MB |

Because runtime overhead is additional, practical budget requirement is higher than the table values.

## 6.2 System-level implication

- Expansion of input context requires explicit re-baselining of the Orchestrator RSS budget in ADR-006.
- Even 8K context increases pressure and consumes worst-case headroom that is currently thin.
- Code Agent reservation (9,728 MB) is architecturally committed in ADR-006 even if not operational; treating it as free permanent headroom would violate the locked design assumptions.

## 6.3 Input vs output memory profile difference

- **Input expansion:** immediate KV-cache growth from longer prompt/history.
- **Output expansion:** KV-cache grows as tokens are generated; memory increases during long decode, but primary effect is longer compute occupancy rather than immediate prefill KV jump.

---

## 7) Step 5 — Recommendation Synthesis

## 7.1 Input context window

1. **RECOMMENDATION:** **DO-NOT-EXPAND** (retain 4,096)
2. **Binding constraints:**
   - Latency scaling risk (prefill quadratic) against existing warm/cold first-token budgets
   - Orchestrator memory budget model already tight when accounting for weights+KV
   - Expanded multi-turn injection persistence + system prompt dilution risk
3. **What must change before reconsideration:**
   - New empirical profiling campaign with controlled 4K/8K/16K prompts on NPU (TTFT + decode)
   - Revised ADR memory budget for Orchestrator with measured RSS, not placeholders
   - Input-context hardening controls (history trust segmentation and stronger long-context policy controls)

## 7.2 Output generation cap

1. **RECOMMENDATION:** **DO-NOT-EXPAND** (retain host 4,096; guest 256)
2. **Binding constraints:**
   - Longer outputs linearly increase wall-clock occupancy
   - PGOV Stage-5 embedding truncation at 128 tokens increases blind-spot risk for longer outputs
   - Larger output allowance increases leakage surface area per response
3. **What must change before reconsideration:**
   - PGOV leakage stage redesign to chunk/slide across full output (not first 128-token view)
   - PGOV performance characterization at long outputs
   - Explicit product requirement demonstrating value beyond current 4,096/256 caps

## 7.3 ADR requirement and implementation gate

- Current study result is **no expansion recommended** for both dimensions.
- Therefore **no implementation milestone is warranted at this time**.
- If the Lead Architect later overrides and selects expansion, **ADR-011 is mandatory before implementation**, at minimum covering:
  - revised token limits and rationale,
  - updated memory budget and headroom model,
  - latency SLO impact and acceptance criteria,
  - PGOV redesign requirements for long-output leakage coverage,
  - phased rollback plan.

---

## 8) Risk Matrix (Recommended Values)

| Dimension | Recommended value | Memory risk | Latency risk | Security risk |
|---|---|---|---|---|
| Input context | Keep 4,096 | MEDIUM | MEDIUM | MEDIUM |
| Output generation (host) | Keep 4,096 | LOW | MEDIUM | MEDIUM |
| Output generation (guest) | Keep 256 | LOW | LOW | LOW |

Justification summary:

- Input 4,096 keeps KV growth bounded while preserving known operational shape.
- Host output 4,096 is already large but presently bounded by existing PGOV and breaker logic.
- Guest output 256 remains operationally conservative for UAT/runtime safety posture.

---

## 9) Final Disposition

- **Input context expansion:** **DO-NOT-EXPAND**
- **Output generation expansion:** **DO-NOT-EXPAND**
- **Overall:** Study complete; maintain current token limits, capture findings for future ADR-trigger if requirements change.
