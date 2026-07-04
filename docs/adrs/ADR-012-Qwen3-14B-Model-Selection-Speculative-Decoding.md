# ADR-012: Qwen3-14B Model Selection with Speculative Decoding

**Status:** ACCEPTED — Configuration Locked (Task 4 Complete)  
**Date:** 2026-02-28  
**Author:** Lead Architect + Copilot Agent (Claude Opus 4.6)  
**Supersedes:** ADR-011 §2.2 Model Selection Status (resolves PENDING state)  
**Branch:** `feature/p5-feasibility-005b-context-optimization`

---

## 1. Context

ADR-011 (2026-02-27) moved all LLM inference to GPU and reopened model selection,
marking PA and AO models as **PENDING** — contingent on P5-005a feasibility results.

The following empirical studies have now completed:

| Study | Key Finding | Evidence |
|-------|-------------|----------|
| P5-005a | Qwen3-14B INT4 loads on Arc 140V, speculative decoding with Qwen3-0.6B operational, \~10 tps at 4K context | `p5_005a_viability_check.json` |
| P5-005b | Extended context feasible through 20,480 tokens, no OOM, peak RSS 12,517 MB (within 15,507 MB budget) | `p5_005b_context_optimization_matrix.json` |
| P5-005b | XAttention (SDPA optimization) does NOT help speculative decoding (9.74 vs 10.02 tps) | `p5_005b_context_optimization_matrix.json` |
| P5-005b | `num_assistant_tokens=3` optimal (10.72 tps at 4K vs NAT=5: 10.02, NAT=7: 10.65, NAT=10: 8.22) | `p5_005b_context_optimization_matrix.json` |
| P5-005b | TPS degrades gracefully: 4K→10.72, 8K→7.74, 16K→4.94, 20K→4.17 | `p5_005b_context_optimization_matrix.json` |

Qwen3-14B with speculative decoding on Arc 140V is empirically validated as viable.

---

## 2. Decision

**Qwen3-14B (OpenVINO INT4, GPU) is the confirmed target model for the Assistant
Orchestrator (AO), Policy Agent (PA), and USE-CASE-005 (Code Agent).**

A speculative-decoding draft model is confirmed as a required component of the
inference pipeline. The exact draft model and full runtime configuration are
under active optimization (see §2.2).

### 2.1 Locked Model Selection

| Parameter | Value | Source |
|-----------|-------|--------|
| Target model | Qwen3-14B | P5-005a/005b empirical evidence |
| Architecture | `Qwen3ForCausalLM` | `models/qwen3-14b/openvino-int4-gpu/config.json` |
| Quantization | INT4 symmetric (group_size=128) | OpenVINO weight compression |
| Layers | 40 | config.json `num_hidden_layers` |
| Hidden size | 5120 | config.json `hidden_size` |
| Vocab size | 151,936 | config.json `vocab_size` (shared across Qwen3 family) |
| KV heads | 8 (GQA) | config.json `num_key_value_heads` |
| Device | GPU (Arc 140V) | ADR-011 (locked) |
| Weight file size | \~9.1 GB | Measured `openvino_model.bin` |
| Path | `models/qwen3-14b/openvino-int4-gpu/` | Acquired in P5-005a |
| Consumers | PA (M2), AO (M3), USE-CASE-005 (Code Agent) | Unified model — single compilation, shared weights |

### 2.2 Configuration Optimization — Complete

The following runtime parameters were empirically optimized across Tasks 4.1–4.9d
(11 sub-sessions, 10 locked decisions). All parameters are LOCKED, ADVISORY, DEFERRED,
or MEASURED. Zero EVALUATING rows remain. Task 4.10 closed this table on 2026-03-05.

| Parameter | Best Known | Status | Notes |
|-----------|-----------|--------|-------|
| **Draft model** | Qwen3-0.6B INT4 (28 layers, 1024 hidden) | **LOCKED** | Task 4.2: Draft-A 10.87 tps / 3.18× baseline. Draft-B eliminated (9.50 tps, -12.6%). NPU draft REJECTED (LLVM_ABORT — VPUX compiler bug, upstream fix submitted: PRs [#265](https://github.com/openvinotoolkit/npu_compiler/pull/265)/[#266](https://github.com/openvinotoolkit/npu_compiler/pull/266)). Re-evaluate NPU draft if fix merges and OV GenAI supports heterogeneous device placement. Evidence: p5_task4_2_draft_model_comparison.json, p5_task4_2b_npu_draft_comparison.json. |
| `num_assistant_tokens` | 3 | **LOCKED** | Task 4.3: NAT=3 wins weighted TPS across 512–8K production range (score 4.847, highest). Wins bands 2K/4K/8K. At 12K: NAT=1 is 61% faster (4.01 vs 2.48 tps) but 12K is USE-CASE-005-only and not yet in production. Adaptive NAT deferred as post-Task-5 optimization. At ≥16K: AR=0.000 for ALL NAT values — speculative decoding is inert. Evidence: p5_task4_3_nat_sweep_matrix.json. |
| Max context window | 16,384 tokens | **LOCKED** | Task 4.3: no OOM through 20,480. Peak RSS 3,562 MB at 16K (within 15,507 MB budget). Speculative decoding inert above \~12K (AR=0.000 at 16K/20K) but system degrades gracefully to autoregressive. 20K proven safe but TPS too low for diminishing contextual value. Evidence: p5_task4_3_nat_sweep_matrix.json. |
| Input/output split | \~12,288 input / \~4,096 output | **ADVISORY** | Heuristic guideline (75/25 split of 16,384 max context). Not empirically optimized. PA: irrelevant (output 3-10 tokens). AO/CODE: revisit if output truncation observed in production. |
| `KV_CACHE_PRECISION` | Not set (default FP16) | **LOCKED** | INT8 KV cache empirically ruled out: 19% TPS drop, 30% TTFT increase, negligible memory savings (P5-005a T-02/T-03). FP16 is the production default. |
| `GPU_ENABLE_SDPA_OPTIMIZATION` | ON | **LOCKED** | Task 4.4: Full context sweep [4K–16K] reverses P5-005b finding. ON wins or ties at every band: 4K +5.8% TPS / +26.1% TTFT, 8K +1.8% TPS / +7.4% TTFT, 12K +0.7% TPS / +5.1% TTFT, 16K +2.3% TPS / +5.8% TTFT. Property verified effective (compile-time 4.5% delta + 4K TPS 5.8% delta). G-01..G-08 all PASS. Disposition: XATTENTION_ON_LOCKED. Evidence: p5_task4_4_xattention_sweep.json. |
| Pipeline construction | Keyword `draft_model=ov_genai.draft_model()` | **LOCKED** | Dict-config deprecated (DeprecationWarning in OpenVINO GenAI). Production pattern: `LLMPipeline(path, device, draft_model=ov_genai.draft_model(draft_path, device), **kwargs)`. Locked 2026-03-01. |
| `do_sample` | False | **LOCKED** | Deterministic execution (temperature=0 equivalent). Per project mandate. |
| `temperature` | 0.0 | **LOCKED** | Deterministic execution. |
| Runtime properties | `INFERENCE_PRECISION_HINT = "f16"` (default) | **LOCKED** | Task 4.7: BF16 not supported on Arc 140V. Plugin error: "Invalid value: bf16 for property: INFERENCE_PRECISION_HINT. Supported values: { f16, f32, dynamic }". FP16 locked as default compute precision. `NUM_STREAMS` and `INFERENCE_PRECISION` (deprecated name) are not applicable. Disposition: BF16_NOT_SUPPORTED. Evidence: p5_task4_7_precision_study.json. |
| GenConfig fields | `max_new_tokens`, `num_assistant_tokens`, `do_sample`, `stop_token_ids` | **LOCKED** | Sub-parameter resolution: PA `max_new_tokens=10` **RESTORED 2026-04-17** (DEC-08; was 256 during thinking experiment). PA `stop_token_ids=[151645, 151668]` **RESTORED 2026-04-17** (DEC-09b; was [151645] during thinking experiment). AO `stop_token_ids=[151645]` **LOCKED** (§2.4). AO/CODE `max_new_tokens` **DEFERRED_TO_TASK5**. `num_assistant_tokens=3` **LOCKED** (DEC-01, Task 4.3). `do_sample=False` **LOCKED** (project mandate). PA quality gate: Task 4.9d 1.000 (40/40); Task 4.12e 0.6055 (155/256) under /no_think — FAILED; 4.12f 0.7227 (185/256) under /think — FAILED; §2.4 Amendment 2 reverts to /no_think + DPC expansion (Task 4.12g). Historical: DEC-09 (0.575) → DEC-09a (0.775) → DEC-09b (/no_think) → DEC-10 (0.925) → 4.9d (1.000) → **4.12e (0.6055 FAIL) → 4.12f (0.7227 FAIL, thinking) → §2.4 Amendment 2 (revert /no_think + DPC ESCALATE)**. |
| Pipeline kwargs | None beyond draft_model | **LOCKED** | Task 4.6: `enable_prefix_caching` INCOMPATIBLE with speculative decoding in OV GenAI 2026.0 (AR collapse on warm calls: AO 12K AR 0.402→0.003→0.000, PA 12K AR 0.167→0.000→0.000). Lock OFF for all profiles. TTFT warm reduction was MODEST (5–10%) in 3/4 groups but speculative decoding compatibility overrides. Evidence: p5_task4_6_prefix_cache_study.json. **AMENDED 2026-05-22 (§6 Amendment 3 Phase 0):** re-checked empirically on OV GenAI 2026.1 — no AR-collapse signature, +23% median TPS, –49% median TTFT with prefix caching ON; DEC-06 lock changed to ON for the shared pipeline. See §6.3 for evidence. |
| `SchedulerConfig.use_sparse_attention` | OFF (default) | **EVALUATED — DEFERRED** | Task 4.3b: TRISHAPE delivers 27–54% TTFT reduction across 4K–16K context bands (substantial). However, TRISHAPE completely suppresses speculative decoding (AR=0.000 at all bands, including 4K where dense AR=0.457). Net effect: TPS degrades 31% at 4K (5.54 vs 8.07). XATTENTION mode ALL_FAILED on Arc 140V / Qwen3-14B (driver/model incompatibility — `CHECK_GETPORT` inference error). G-05 SPEC_DECODE_INTERACTION fired at severity. G-04 TPS_DEGRADATION at 4K. G-01 FAIL (XATTENTION total failure). Disposition: INSUFFICIENT_EVIDENCE (XATTENTION) / SPARSE_DEFERRED (TRISHAPE). Sparse attention remains OFF in production. Re-evaluate if future OV GenAI release fixes XATTENTION compatibility or a TRISHAPE mode that preserves spec-decode acceptance is identified. Evidence: p5_task4_3b_sparse_attention_ab_test.json. |
| Memory budget | 12,051 MB peak RSS (band 512, NAT=1) | **MEASURED** | Task 4.3: peak RSS across all 42 configs. Within 15,507 MB tier budget (ADR-006). Headroom: 3,456 MB. KV cache eviction reduces RSS at long context (20K: 1,835 MB). |

### 2.3 Draft Model Candidates

| Candidate | Layers | Hidden | Quant | Size | Status |
|-----------|--------|--------|-------|------|--------|
| Qwen3-0.6B (full) | 28 | 1024 | INT4 | \~367 MB | **OPERATIONAL** — validated in P5-005a/005b |
| Qwen3-pruned-6L-from-0.6B | 22 | 1024 | INT8_ASYM | \~300 MB (est.) | **ELIMINATED** — P5-005c acquisition aborted. Repository `OpenVINO/Qwen3-pruned-6L-from-0.6B-int8-ov` not available. Draft-A (full 28L INT4) confirmed as sole draft candidate. |
| Qwen3-1.7B | 28 | 2048 | INT4 | \~1 GB (est.) | **NOT TESTED** — larger draft, higher quality predictions, higher per-token cost. Candidate for future evaluation. |

Draft model selection is **LOCKED**: Draft-A (Qwen3-0.6B full 28L INT4) is the sole validated draft. Draft-B (pruned 22L INT8_ASYM) is eliminated due to unavailable acquisition target. No further draft model evaluation is required before Task 5.

> **AMENDED 2026-05-22 (§6 Amendment 3 §6.6):** Draft-B (Qwen3-pruned-6L INT8) is **no longer eliminated**. The OpenVINO-published variant (`OpenVINO/Qwen3-pruned-6L-from-0.6B-int8-ov`) was acquired and integrated to enable speculative-decoded streaming on the Orchestrator. Under the shared pipeline (Sprint 2026-05-22), both PA and AO use Draft-B as the unified draft. Draft-A is retained on disk; Draft-B is the operational selection.

### 2.4 Qwen3 Thinking Mode and Stop Token Strategy — AMENDED 2026-04-17

> **Amendment 1 (2026-03-07):** PA thinking mode enabled by Lead Architect decision
> following Task 4.12e quality gate failure. Evidence: 0/207 LLM-path cases produced
> any chain-of-thought reasoning under `/no_think`, yielding M-1=0.6055, M-2=0.7976,
> M-5=0.7763 (3 BLOCKING failures). Security classification requires deliberation.
> `MAX_CLASSIFICATION_TOKENS` raised from 32 to 256. See `Task4.12e_Failure_Report.md`.

> **Amendment 2 (2026-04-17): PA REVERTED to `/no_think` — thinking experiment concluded.**
> Task 4.12f (thinking mode re-gate, 256 cases × 3 runs = 768 LLM calls) proved that
> thinking mode is **insufficient and introduces regressions** for PA classification:
>
> - G-02 LABEL_EXTRACTION **FAIL**: 14 null labels from `<think>` block exhausting
>   MAX_NEW_TOKENS=1024 at band≥8192. Token budget of ≥4096 would be required,
>   violating the 2,000ms P95 latency budget (§2.5).
> - G-04 AGREEMENT_GATE **FAIL**: 0.7227 < 0.90. ESCALATE recall only 38.6% (17/44).
>   Thinking mode improved overall agreement by +0.117 (0.6055→0.7227) but did not
>   resolve the fundamental ESCALATE under-detection problem.
> - M-2 adversarial security resolved (0.7976→1.0000) — but this was achieved by the
>   DENY_AUTHORITY_CLAIM DPC prefilter, not by thinking mode itself.
>
> **Disposition:** Thinking mode provides marginal quality improvement (+11.7%) at
> unacceptable cost (TRUNC regression, latency violation, non-deterministic reasoning).
> The DPC prefilter is the proven mechanism (adversarial: 0.7976→1.0000). The correct
> path is DPC ESCALATE expansion, not LLM reasoning for classification.
>
> **PA reverted to:** `/no_think` MANDATORY, `max_new_tokens=10` (DEC-08 restored),
> `stop_token_ids=[151645]` only — `<|im_end|>` only (DEC-09b base; further corrected
> during Task 4.12g smoke gate debugging — see correction note below). DPC ESCALATE
> rules expanded in Task 4.12g (Rules 7–10). Task 4.12g smoke gate: 0.9483 (55/58), PASS.
>
> **Amendment 2 stop_token_ids correction (Task 4.12g, 2026-04-17):** The initial
> Amendment 2 text stated `stop_token_ids=[151645, 151668]` (DEC-09b restored). This
> was further corrected during Task 4.12g smoke gate debugging. The correct operational
> value is `stop_token_ids=[151645]` ONLY. Reason: OV GenAI suppresses stop-token
> checking for any token ID that appears in the input context. Because the canonical
> Qwen3 thinking-suppression prefill (`<think>\n\n</think>\n\n`) contains both
> `<think>` (151667) and `</think>` (151668), neither thinking token can be used as a
> stop target — the stop would be silently skipped. `<|im_end|>` (151645) never appears
> in the input context, so it fires correctly. See §2.4 Lessons Learned items 6–10 and
> `docs/LESSONS_LEARNED_QWEN3_THINKING_SUPPRESSION.md` for the full failure analysis.
>
> **Lessons learned (for rebuild reference):**
> 1. Qwen3 `/no_think` produces zero reasoning tokens — the model strictly obeys the directive.
> 2. Thinking mode at high context bands (8K+) generates 7,000–11,000 thinking tokens,
>    making any practical MAX_NEW_TOKENS ceiling impractical for a latency-constrained classifier.
> 3. DPC (deterministic regex prefilter) is strictly superior to LLM reasoning for
>    high-confidence classification patterns — zero latency variance, 100% recall, deterministic.
> 4. For a 3-label classifier (ALLOW/DENY/ESCALATE), ESCALATE is the hardest label for the LLM
>    because it requires meta-reasoning ("can I determine safety from the request alone?").
>    This is better expressed as deterministic rules than as LLM chain-of-thought.
> 5. The quality gate trajectory (DEC-09: 0.575 → DEC-10: 0.925 → 4.9d: 1.000 on 40 cases →
>    4.12e: 0.6055 on 256 cases) demonstrates that small-corpus gates mask DPC dependency.
>    Always test with corpus sizes that expose the LLM-path independently.
> 6. **OV GenAI stop-token suppression constraint:** OpenVINO GenAI suppresses stop-token
>    checking for any token ID that appears anywhere in the input context string. This makes
>    it impossible to use thinking token IDs as stop targets when the prompt contains a
>    thinking-suppression prefill. The only safe stop token is one that cannot appear in input
>    context — `<|im_end|>` (151645).
> 7. **Canonical Qwen3 thinking-suppression recipe (verified, Task 4.12g Run 6):**
>    (a) Append ` /no_think` to the user turn text.
>    (b) Prefill the assistant turn: `<|im_start|>assistant\n<think>\n\n</think>\n\n` — this
>        is consumed as INPUT context, not generated output. The model begins generating AFTER
>        this prefill is consumed, so its generation budget starts at the first label token.
>    (c) Set `stop_token_ids = [151645]` — `<|im_end|>` ONLY. No thinking token IDs.
>    This mirrors `apply_chat_template(enable_thinking=False)` from Qwen3 official tooling.
> 8. **Qwen3 token ID correction:** The original code used `QWEN3_THINK_START_TOKEN_ID = 151_668`
>    — this is WRONG. `151668` = `</think>` (CLOSE). `151667` = `<think>` (OPEN). Both were
>    verified via `tokenizer.decode([151667])` = `'<think>'` and `tokenizer.decode([151668])`
>    = `'</think>'`. The correct mapping is: `151645` = `<|im_end|>`, `151667` = `<think>`,
>    `151668` = `</think>`.
> 9. **Run failure taxonomy (6 runs to PASS):** Approaches that fail: (a) No prefill + stop on
>    think-close token → model generates 7K+ thinking tokens, TRUNC at budget. (b) `/no_think`
>    user turn only, no prefill, stop on `</think>` → `</think>` (151668) fires on first
>    generated token (model chose `<think>` first; wrong token ID meant stop fired on next).
>    (c) Empty `<think></think>` prefill + stop on thinking tokens → OV GenAI suppresses stop
>    (tokens in input context). (d) Full prefill + stop on `<think>` (151667) → same suppression.
>    (e) `/no_think` only, no prefill, stop on `<think>` (151667) → fires on token 1 (model
>    chooses `<think>` as first generated token regardless of `/no_think` without prefill).
>    Only approach (f) works: full dual-signal (items a+b+c above).
> 10. **Why `think_block_present=True` in harness output is cosmetic:** The parse harness flags
>     `think_block_present=True` because the prefill string `<think>\n\n</think>\n\n` appears
>     in the raw prompt that is prepended to output for logging. The model itself did NOT
>     generate these tokens. Label extraction is correct — this is a display artifact on
> **Lessons learned (for rebuild reference):**
> 1. Qwen3 `/no_think` produces zero reasoning tokens — the model strictly obeys the directive.
> 2. Thinking mode at high context bands (8K+) generates 7,000think>` (token ID 151667)
before its reasoning chain, consuming output tokens for internal chain-of-thought before
producing the visible response. This has distinct implications for each BlarAI consumer:

| Component | Thinking Mode | Stop Token Strategy | Rationale |
|-----------|--------------|--------------------|-----------|
| **Policy Agent** (classifier) | `/no_think` MANDATORY | `stop_token_ids=[151645]` (`<\|im_end\|>` only) | **REVERTED 2026-04-17 + corrected Task 4.12g.** Thinking experiment (4.12e/4.12f) concluded: marginal quality gain (+11.7%), unacceptable TRUNC regression, latency violation. Canonical Qwen3 suppression: `/no_think` user turn + empty `<think>\n\n</think>\n\n` assistant prefill (consumed as input context). `stop_token_ids=[151645]` ONLY — thinking token IDs cannot be stop targets when they appear in the input prefill (OV GenAI suppresses stop for tokens present in input). DPC Rules 7–10 added (Task 4.12g). Quality: 0.9483 (55/58). |
| **Assistant Orchestrator** (conversational) | Default (thinking allowed) | `stop_token_ids=[151645]` (`<\|im_end\|>` only) | Thinking mode improves response quality for complex multi-step queries. The AO generates variable-length conversational output where reasoning depth is valuable. Let the model think when it determines it's beneficial. |
| **USE-CASE-005** (code generation) | Context-dependent: `/think` for complex tasks, `/no_think` for simple completions | `stop_token_ids=[151645]` (`<\|im_end\|>` only) | Complex code synthesis benefits from chain-of-thought reasoning. Simple completions (boilerplate, formatting) should skip thinking to save tokens and latency. The Code Agent dispatcher selects the mode based on task complexity classification. |

**Token IDs (Qwen3 tokenizer — VERIFIED via `tokenizer.decode()`):**
- `151645` — `<|im_end|>` (chat turn terminator) — SAFE as stop token
- `151667` — `<think>` (thinking mode OPEN) — **CANNOT be stop token when prefill is used**
- `151668` — `</think>` (thinking mode CLOSE) — **CANNOT be stop token when prefill is used**

> **CORRECTION NOTE:** Early code used `QWEN3_THINK_START_TOKEN_ID = 151_668` — this is
> WRONG. `151668` = `</think>` (CLOSE). `151667` = `<think>` (OPEN). Fixed in Task 4.12g.
> Previous ADR text showed `<|think|>` token 151668 and `</|think|>` token 151669 —
> both are incorrect. The actual tag strings are `<think>` and `</think>` (no pipe chars).
> Token 151669 is not used in BlarAI inference.t cannot appear in input
>    context — `<|im_end|>` (151645).
> 7. **Canonical Qwen3 thinking-suppression recipe (verified, Task 4.12g Run 6):**
>    (a) Append ` /no_think` to the user turn text.
>    (b) Prefill the assistant turn: `<|im_start|>assistant\n<think>\n\n</think>\n\n` — this
>        is consumed as INPUT context, not generated output. The model begins generating AFTER
>        this prefill is consumed, so its generation budget starts at the first label token.
>    (c) Set `stop_token_ids = [151645]` — `<|im_end|>` ONLY. No thinking token IDs.
>    This mirrors `apply_chat_template(enable_thinking=False)` from Qwen3 official tooling.
> 8. **Qwen3 token ID correction:** The original code used `QWEN3_THINK_START_TOKEN_ID = 151_668`
>    — this is WRONG. `151668` = `</think>` (CLOSE). `151667` = `<think>` (OPEN). Both were
>    verified via `tokenizer.decode([151667])` = `'<think>'` and `tokenizer.decode([151668])`
>    = `'</think>'`. The correct mapping is: `151645` = `<|im_end|>`, `151667` = `<think>`,
>    `151668` = `</think>`.
> 9. **Run failure taxonomy (6 runs to PASS):** Approaches that fail: (a) No prefill + stop on
>    think-close token → model generates 7K+ thinking tokens, TRUNC at budget. (b) `/no_think`
>    user turn only, no prefill, stop on `</think>` → `</think>` (151668) fires on first
>    generated token (model chose `<think>` first; wrong token ID meant stop fired on next).
>    (c) Empty `<think></think>` prefill + stop on thinking tokens → OV GenAI suppresses stop
>    (tokens in input context). (d) Full prefill + stop on `<think>` (151667) → same suppression.
>    (e) `/no_think` only, no prefill, stop on `<think>` (151667) → fires on token 1 (model
>    chooses `<think>` as first generated token regardless of `/no_think` without prefill).
>    Only approach (f) works: full dual-signal (items a+b+c above).
> 10. **Why `think_block_present=True` in harness output is cosmetic:** The parse harness flags
>     `think_block_present=True` because the prefill string `<think>\n\n</think>\n\n` appears
>     in the raw prompt that is prepended to output for logging. The model itself did NOT
>     generate these tokens. Label extraction is correct — this is a display artifact only.

Qwen3 models support dual-mode operation via system prompt directives (`/think` and
`/no_think`). When thinking mode is active, the model emits `<think>` (token ID 151667)
before its reasoning chain, consuming output tokens for internal chain-of-thought before
producing the visible response. This has distinct implications for each BlarAI consumer:

| Component | Thinking Mode | Stop Token Strategy | Rationale |
|-----------|--------------|--------------------|-----------|
| **Policy Agent** (classifier) | `/no_think` MANDATORY | `stop_token_ids=[151645]` (`<\|im_end\|>` only) | **REVERTED 2026-04-17 + corrected Task 4.12g.** Thinking experiment (4.12e/4.12f) concluded: marginal quality gain (+11.7%), unacceptable TRUNC regression, latency violation. Canonical Qwen3 suppression: `/no_think` user turn + empty `<think>\n\n</think>\n\n` assistant prefill (consumed as input context). `stop_token_ids=[151645]` ONLY — thinking token IDs cannot be stop targets when they appear in the input prefill (OV GenAI suppresses stop for tokens present in input). DPC Rules 7–10 added (Task 4.12g). Quality: 0.9483 (55/58). |
| **Assistant Orchestrator** (conversational) | Default (thinking allowed) | `stop_token_ids=[151645]` (`<\|im_end\|>` only) | Thinking mode improves response quality for complex multi-step queries. The AO generates variable-length conversational output where reasoning depth is valuable. Let the model think when it determines it's beneficial. |
| **USE-CASE-005** (code generation) | Context-dependent: `/think` for complex tasks, `/no_think` for simple completions | `stop_token_ids=[151645]` (`<\|im_end\|>` only) | Complex code synthesis benefits from chain-of-thought reasoning. Simple completions (boilerplate, formatting) should skip thinking to save tokens and latency. The Code Agent dispatcher selects the mode based on task complexity classification. |

**Token IDs (Qwen3 tokenizer — VERIFIED via `tokenizer.decode()`):**
- `151645` — `<|im_end|>` (chat turn terminator) — SAFE as stop token
- `151667` — `<think>` (thinking mode OPEN) — **CANNOT be stop token when prefill is used**
- `151668` — `</think>` (thinking mode CLOSE) — **CANNOT be stop token when prefill is used**

> **CORRECTION NOTE:** Early code used `QWEN3_THINK_START_TOKEN_ID = 151_668` — this is
> WRONG. `151668` = `</think>` (CLOSE). `151667` = `<think>` (OPEN). Fixed in Task 4.12g.
> Previous ADR text showed `<|think|>` token 151668 and `</|think|>` token 151669 —
> both are incorrect. The actual tag strings are `<think>` and `</think>` (no pipe chars).
> Token 151669 is not used in BlarAI inference.

**Defense-in-depth principle:** The PA relies on `ClassificationParser` to strip all
`<think>...</think>` blocks from model output before label extraction. Labels mentioned
inside think blocks are ignored. Multi-label output → fail-closed DENY. This ensures
reasoning content cannot inject or smuggle classification labels.

---

### 2.5 Policy Agent Latency Budget — LOCKED

**Decision date:** 2026-03-01 (Task 4.1)  
**Replaces:** ADR-010 §3.2 P] | DEC-09b base; corrected Task 4.12g (2026-04-17): `<\|im_end\|>` only — OV GenAI suppresses thinking token stops when they appear in input prefill |
| Thinking mode | `/no_think` MANDATORY + canonical prefill | DEC-09b restored 2026-04-17 (§2.4 Amend 2); prefill strategy locked Task 4.12g

| Budget item | Value | Status |
|-------------|-------|--------|
| **PA inference P95** | **2,000ms flat** | **LOCKED** |
| Budget components | TTFT (\~300–408ms at 2K–4K) + decode (\~470–935ms for 5–10 tokens) + pipeline overhead (\~100–200ms) + P95 variance headroom (\~400ms) | Reference |
| Worst-case ceiling at max_new_tokens=32 | \~2,987ms (EXCEEDS budget) | Drives Task 4.8 |
| Realistic best-case E2E | \~8710 rules (4 DENY + 6 ESCALATE — Rules 7–10 added Task 4.12g) | DEC-10 (Tasks 4.9c–4.9d); expanded Task 4.12g |
| Quality gate | 4.9d: 1.000 (40/40); 4.12e: 0.6055 (256); 4.12f: 0.7227 (256) FAIL; **4.12g: 0.9483 (55/58) PASS** | DEC-10, §2.4 Amend 2, Task 4.12g
| Total PA authorization latency (inference + signing) | \~2,030–2,050ms | Reference |

**Derivation basis:**
- Empirical baseline: 10.72 tps (P5-005b D-01, NAT=3, XAttention=OFF, KV FP16, 4K context).
- At 10.72 tps: 5 tokens ≈ 467ms, 10 tokens ≈ 933ms, 32 tokens ≈ 2,987ms.
- TTFT at 4K context: 408ms (P5-005b D-01).
- P5-005b results are provisional pending Task 4 optimization — budget is set
  conservatively to hold regardless of configuration changes within Task 4.

**Implication for max_new_tokens (Task 4.8):**
The 2,000ms budget cannot be satisfied with max_new_tokens=32 if EOS does not fire
before the ceiling is reached. Task 4.8 must determine the lowest max_new_tokens
value that produces zero classification truncation events across the PA quality
gate input bands (512 / 1K / 2K / 4K). Candidates: 8, 10, 15, 32 (baseline).
Expected result: max_new_tokens ≤ 15 will satisfy both the quality (no truncation)
and latency (≤ 2,000ms worst-case) requirements simultaneously.

**Gate dependency:**
- Task 4.8: max_new_tokens lock (feeds this budget)
- Task 4.9: PA classification quality gate (validates truncation = 0 at locked value)
- UAT-4b: live PA classification round-trip ≤ 2,000ms in TUI

---

### 2.6 Production Workload Profiles (Task 4 Exit State)

> **§6 Amendment 3 (Sprint 2026-05-22) supersedes the following per-profile
> rows:** `enable_prefix_caching` (now ON for both PA and AO under the shared
> pipeline — DEC-06 amended on fresh OV GenAI 2026.1 evidence), draft model
> (now Qwen3-0.6B-pruned-6L INT8 for both consumers — §2.3 elimination is
> superseded), and `MODEL_PRIORITY` (now `"HIGH"` at the shared-pipeline level
> — PA security-gate posture inherited). The Task 4 values below are retained
> as the historical record of how the profiles were locked pre-unification.

These profiles represent the Task 4 exit state. Parameters locked during Tasks 4.1–4.9d.
Values marked DEFERRED_TO_TASK5 will be resolved during Task 5 model upgrade.

#### USE-CASE-001 — Policy Agent (PA)

| Parameter | Value | Source |
|-----------|-------|--------|
| Model | Qwen3-14B INT4 | ADR-012 §2.1 |
| Device | GPU (Arc 140V) | ADR-011 |
| Draft model | Qwen3-0.6B INT4 28L | DEC-01 (Task 4.2) |
| `num_assistant_tokens` | 3 | DEC-01 (Task 4.3) |
| `max_new_tokens` | 10 | DEC-08 (Task 4.8), restored 2026-04-17 |
| `stop_token_ids` | [151645] | DEC-09b base; corrected Task 4.12g (2026-04-17): `<\|im_end\|>` only — OV GenAI suppresses thinking token stops when they appear in input prefill |
| Thinking mode | `/no_think` MANDATORY + canonical prefill | DEC-09b restored 2026-04-17 (§2.4 Amend 2); prefill strategy locked Task 4.12g |
| `INFERENCE_PRECISION_HINT` | f16 | DEC-07 (Task 4.7) |
| `GPU_ENABLE_SDPA_OPTIMIZATION` | ON | DEC-05 (Task 4.4) |
| `enable_prefix_caching` | OFF | DEC-06 (Task 4.6) |
| `use_sparse_attention` | OFF | DEFERRED (Task 4.3b) |
| `do_sample` | False | Project mandate |
| `temperature` | 0.0 | Project mandate |
| DeterministicPolicyChecker | 10 rules (4 DENY + 6 ESCALATE — Rules 7–10 added Task 4.12g) | DEC-10 (Tasks 4.9c–4.9d); expanded Task 4.12g |
| Quality gate | 4.9d: 1.000 (40/40); 4.12e: 0.6055 (256); 4.12f: 0.7227 (256) FAIL; **4.12g: 0.9483 (55/58) PASS** | DEC-10, §2.4 Amend 2, Task 4.12g |
| Latency budget | 2,000ms P95 | ADR-012 §2.5 (Task 4.1) |

#### USE-CASE-004 — Assistant Orchestrator (AO)

| Parameter | Value | Source |
|-----------|-------|--------|
| Model | Qwen3-14B INT4 | ADR-012 §2.1 |
| Device | GPU (Arc 140V) | ADR-011 |
| Draft model | Qwen3-0.6B INT4 28L | DEC-01 (Task 4.2) |
| `num_assistant_tokens` | 3 | DEC-01 (Task 4.3) |
| `max_new_tokens` | DEFERRED_TO_TASK5 | Q-2 (no 14B data) |
| `stop_token_ids` | [151645] | §2.4 |
| Thinking mode | Default (thinking allowed) | §2.4 |
| `INFERENCE_PRECISION_HINT` | f16 | DEC-07 (Task 4.7) |
| `GPU_ENABLE_SDPA_OPTIMIZATION` | ON | DEC-05 (Task 4.4) |
| `enable_prefix_caching` | OFF | DEC-06 (Task 4.6) |
| `use_sparse_attention` | OFF | DEFERRED (Task 4.3b) |
| `do_sample` | False | Project mandate |
| `temperature` | 0.0 | Project mandate |

#### USE-CASE-005 — Code Agent (not yet in production)

Inherits AO shared parameters. Component-specific differences:

| Parameter | Value | Source |
|-----------|-------|--------|
| Thinking mode | Context-dependent (`/think` complex, `/no_think` simple) | §2.4 |
| `max_new_tokens` | DEFERRED_TO_TASK5 | Q-2 (no 14B data) |

CODE profile inherits all other AO parameters. Component-specific tuning deferred
to Task 5 when Qwen3-14B is deployed for code generation.

#### Security Caveats — Pending Task 4.11

The following security gaps were identified in `docs/SECURITY_ASSESSMENT.md` (2026-03-05).
They do not invalidate the Task 4 configuration decisions but must be resolved before
Task 5 (Model Upgrade) proceeds.

1. **mTLS CN → source_agent validation (P0):** The PA DeterministicPolicyChecker
   ESCALATE_CROSS_AGENT_OWNERSHIP rule depends on `source_agent` integrity. Currently
   `source_agent` is self-asserted — no code extracts the peer cert CN to validate it.
   A compromised agent holding a valid mTLS cert can spoof `source_agent` and bypass
   ownership-based ESCALATE rules. Fix scoped to Task 4.11.
   (AI Risk Assessment §Recommendation 3; SECURITY_ASSESSMENT.md P0-1)

2. **parameters_schema prompt injection (P0):** `car.parameters_schema` is serialized
   via `json.dumps()` and concatenated directly into the LLM prompt with no schema
   validation or sanitization. The DeterministicPolicyChecker's string-match rules
   catch narrow patterns but do not defend against general prompt injection payloads
   embedded in `parameters_schema`. Fix scoped to Task 4.11.
   (AI Risk Assessment §Recommendation 1; SECURITY_ASSESSMENT.md P0-2)

3. **Authority claim regex bypass (HIGH):** Unicode homoglyphs and synonym
   substitution bypass the 5-pattern `_AUTHORITY_CLAIM_RE`. Fix scoped to Task 4.11.
   (SECURITY_ASSESSMENT.md P1-1)

These caveats do not invalidate the Task 4 configuration decisions. They document
known security gaps that Task 4.11 (Security Hardening) must resolve before Task 5
(Model Upgrade). **Task 5 is blocked on Task 4.11 completion.**

---

## 3. Consequences

### 3.1 What Changes

1. **Model selection resolved.** ADR-011 §2.2 PENDING state is superseded — target
   model is Qwen3-14B. Qwen2.5-1.5B-Instruct is demoted from "operational fallcanonical dual-signal suppression (user turn ` /no_think` + empty `<think>\n\n</think>\n\n` assistant prefill consumed as input) prevents thinking output. Stop list `[151645]` only — thinking token IDs cannot be stop targets when present in input prefill (OV GenAI suppression). See §2.4 Lessons 6–9 and `docs/LESSONS_LEARNED_QWEN3_THINKING_SUPPRESSION.md`.
   to "legacy reference" (retained on disk for rollback but not loaded by default).

2. **Unified model confirmed.** PA, AO, and USE-CASE-005 all share the same Qwen3-14B
   target model. This simplifies weight loading (single GPU compilation), memory
   budgeting, and operational maintenance.

3. **Speculative decoding is mandatory.** The inference pipeline requires a draft model —
   standalone Qwen3-14B generation without speculative decoding is too slow for
   interactive use (measured: \~2-3 tps solo vs \~10 tps with draft at 4K context).

4. **Context window cap LOCKED at 16,384 tokens.** The 4,096 hard cap (P5-001) is superseded.
   Task 4.3 proved 20K is safe (no OOM, RSS 1,835 MB) but speculative decoding is inert above
   \~12K (AR=0.000). The 16K cap balances Code Agent context needs with practical throughput.

5. **Speculative decoding collapse documented.** Task 4.3 discovered that speculative decoding
   acceptance rate collapses to exactly 0.000 at ≥16K context for ALL NAT values. This means
   the Qwen3-0.6B draft model provides zero speculative acceleration beyond \~12K. The system
   degrades gracefully to autoregressive generation (TPS 2.3–3.5 at 16K, functional but slower).
   This is a known limitation of the 0.6B/14B capacity gap at long context. No code change
   required — the pipeline handles rejection gracefully. Task 4.3b (2026-03-03) measured
   the collapse boundary impact: TRISHAPE sparse attention does NOT shift the collapse
   boundary — instead it completely suppresses speculative decoding at ALL context bands
   (AR=0.000 from 4K through 20K). XATTENTION is incompatible with Arc 140V / Qwen3-14B
   in OV GenAI 2026.0. Sparse attention DEFERRED. See §2.2 and evidence artifact.

5. **Constants marked PROVISIONAL updated.** `PA_MODEL_SIZE_PARAMS`, `ORCH_MODEL_SIZE_PARAMS`,
   `PA_OV_PATH`, etc. now reference Qwen3-14B with "configuration optimization in progress"
   annotation. Final constants will be locked when the optimization phase completes.

### 3.2 What Does NOT Change

1. **Device allocation (ADR-011).** All inference on GPU. NPU retired. No change. **Note:** If upstream merges the VPUX compiler fix (PRs [#265](https://github.com/openvinotoolkit/npu_compiler/pull/265)/[#266](https://github.com/openvinotoolkit/npu_compiler/pull/266)) and OpenVINO GenAI exposes per-model device placement for heterogeneous speculative decoding, ADR-011 §2.4 and this ADR's draft device allocation would be re-evaluated — NPU as draft device is the architecturally optimal Lunar Lake configuration. See ADR-011 §2.4 re-evaluation trigger and `docs/VPUX_CONVERTFCTOCONV_BUG_FIX.md`.
2. **Fail-Closed architecture.** GPU timeout → DENY. Same guarantee.
3. **Deterministic execution.** `do_sample=False`, `temperature=0.0`. Locked.
4. **31.323 GB memory ceiling (ADR-005).** Unchanged.
5. **Measured Boot Sequence.** PA still boots first.
6. **Action Authorization Boundary.** JWT lifecycle unchanged.
7. **Semantic Router.** BGE-small-en-v1.5 on CPU. Unchanged.

### 3.3 Residual Risks

| Risk | Severity | Mitigation |
|------|----------|------------|
| Draft model selection may shift NAT optimum | LOW | Empirical: P5-005c will produce comparative data; NAT sweep repeatable |
| Heterogeneous spec-decode becomes viable | LOW | If VPUX compiler fix merges upstream (PRs #265/#266) and OV GenAI exposes per-model device placement, re-benchmark NPU draft vs GPU draft. If NPU-draft TPS > 10.87, amend ADR-011 §2.4 and this ADR's draft device to NPU. See `docs/VPUX_CONVERTFCTOCONV_BUG_FIX.md`. |
| Context cap increase may expose new PGOV attack surface | MEDIUM | PGOV security analysis required for any cap above 4,096 |
| Qwen3-14B is sole model — no diversity | LOW | Acceptable for personal single-user system; model can be swapped via config change + recompile |
| Qwen3 thinking mode ignores `/no_think` directive | LOW | Defense-in-depth: canonical dual-signal suppression (user turn ` /no_think` + empty `<think>\n\n</think>\n\n` assistant prefill consumed as input) prevents thinking output. Stop list `[151645]` only — thinking token IDs cannot be stop targets when present in input prefill (OV GenAI suppression). See §2.4 Lessons 6–9 and `docs/LESSONS_LEARNED_QWEN3_THINKING_SUPPRESSION.md`. |

---

## 4. Evidence

- P5-005a viability: `phase2_gates/evidence/p5_005a_viability_check.json`
- P5-005a model acquisition: `phase2_gates/evidence/p5_005a_model_acquisition.json`
- P5-005b optimization matrix: `phase2_gates/evidence/p5_005b_context_optimization_matrix.json`
- P5-005b summary: `phase2_gates/evidence/p5_005b_context_optimization_summary.md`
- ADR-011 (device allocation): `docs/adrs/ADR-011-All-LLM-Inference-GPU-NPU-Retirement.md`
- ADR-010 (PA on GPU): `docs/adrs/ADR-010-PA-Device-Allocation-GPU-Classification.md`
- Task 4.2 draft model comparison: `phase2_gates/evidence/p5_task4_2_draft_model_comparison.json`
- Task 4.2b NPU draft device: `phase2_gates/evidence/p5_task4_2b_npu_draft_comparison.json`
- Task 4.3 NAT sweep matrix: `phase2_gates/evidence/p5_task4_3_nat_sweep_matrix.json`
- Task 4.3 execution report: `docs/Task4.3_EXECUTION_REPORT.xml`
- Task 4.3b sparse attention A/B test: `phase2_gates/evidence/p5_task4_3b_sparse_attention_ab_test.json`
- Task 4.4 XAttention (GPU SDPA) sweep: `phase2_gates/evidence/p5_task4_4_xattention_sweep.json`
- Task 4.6 prefix cache study: `phase2_gates/evidence/p5_task4_6_prefix_cache_study.json`
- Task 4.7 compute precision study: `phase2_gates/evidence/p5_task4_7_precision_study.json`
- Task 4.8 PA max_new_tokens study: `phase2_gates/evidence/p5_task4_8_pa_max_tokens_study.json`
- Task 4.9 PA quality gate: `phase2_gates/evidence/p5_task4_9_pa_quality_gate.json`
- Task 4.9a PA quality gate re-gate (prompt revision): `phase2_gates/evidence/p5_task4_9a_prompt_revision_quality_gate.json`
- Task 4.9b /no_think removal measurement: `phase2_gates/evidence/p5_task4_9b_no_think_measurement.json`
- Task 4.9c deterministic pre-filter + ESCALATE refinement: `phase2_gates/evidence/p5_task4_9c_deterministic_prefilter.json`
- Task 4.9d ESCALATE hardening + RISK-1 carve-out: `phase2_gates/evidence/p5_task4_9d_escalate_hardening.json`
- Task 4.12g DPC ESCALATE expansion + /no_think smoke gate (Run 6 PASS): `phase2_gates/evidence/p5_task4_12_corpus_hardening.json`
- Task 4.12g smoke gate transcript: `phase2_gates/evidence/p5_task4_12g_smoke_run.txt`
- Task 4.12g lessons learned (OV GenAI suppression + canonical recipe): `docs/LESSONS_LEARNED_QWEN3_THINKING_SUPPRESSION.md`

---

## 5. Rollback

If Qwen3-14B proves unsuitable after configuration optimization:

1. Revert model constants to Qwen2.5-1.5B-Instruct values
2. Remove speculative decoding from pipeline config
3. Restore `PA_OV_PATH` to `models/qwen2.5-1.5b-instruct/openvino-int4-npu`
4. Mark ADR-012 as SUPERSEDED with rollback rationale
5. ADR-011 model selection returns to PENDING state

---

## 6. Amendment 3 — Shared LLMPipeline (Sprint 2026-05-22)

### 6.1 Trigger and scope

§2.1 and §3.1 specified "single compilation, shared weights" across the
Qwen3-14B's consumers. The implementation diverged after the streaming
and draft-model work and held two compiled `LLMPipeline` instances — one
per service — at \~17 GB combined GPU residency, with two \~15–18 s GPU
compiles per boot. The investigation in
`docs/MODEL_SHARING_INVESTIGATION.md` (commit `5c5201d`) measured the
state and surfaced the drift.

This amendment re-affirms the locked "single compilation" architecture
and records the construction-config reconciliation required to merge the
two pipelines into one. Per-call settings (`max_new_tokens`,
thinking-mode prefill, stop tokens) remain per-consumer via
`GenerationConfig`; only construction-time config is unified.

### 6.2 Locked changes

| Setting | Pre-amendment PA | Pre-amendment AO | Locked (this amendment) | Rationale |
|---|---|---|---|---|
| Pipeline construction | Each service builds its own | Each service builds its own | One `ov_genai.LLMPipeline` built at launcher boot, threaded into both via `SharedInferencePipeline` wrapper | ADR-012 §2.1/§3.1 mandate; \~8 GB GPU memory + \~15–18 s boot recovered |
| Concurrency | n/a (separate pipelines) | n/a (separate pipelines) | `threading.Lock` serialises `.generate()` between PA and AO | One pipeline cannot serve two concurrent generations; see §6.4 |
| `enable_prefix_caching` | OFF (DEC-06) | ON (drift) | **ON** | OV GenAI 2026.1 empirical re-check; §6.3 |
| Draft model | `qwen3-0.6b` full 28L INT4 | `qwen3-0.6b-pruned-6l` INT8 | **Pruned-6L INT8** | AO streaming requirement; PA latency budget (§2.5) absorbs the small cost (current PA P95 ≈ 125 ms vs 2 000 ms budget) |
| `MODEL_PRIORITY` | `"HIGH"` (priority 0) | `"MEDIUM"` (priority 1) | **`"HIGH"`** | PA security-gate posture inherited; under serialised shared pipeline the priority is moot for scheduling but documents the security frame |

### 6.3 DEC-06 amendment — empirical Phase 0 re-check (OV GenAI 2026.1)

**Method.** `scripts/benchmark_gpu_inference.py --configs spec_on --runs 6
--warmup 2`, invoked twice (once per `--prefix-caching` value),
same-process per invocation, 90 s GPU cooldown between conditions, warm
state after the script's own 2 warmup passes. 6 measured runs × 4 prompts
= 24 samples per condition. Same target (Qwen3-14B INT4), same draft
(Qwen3-0.6B pruned-6L INT8), same hardware (Intel Arc 140V).

**Stack.** OpenVINO 2026.1.0-21367-63e31528c62, openvino-genai
2026.1.0.0-2957-1dabb8c2255.

**Results.**

| Metric | prefix=ON | prefix=OFF | Δ (OFF vs ON) |
|---|---|---|---|
| Median throughput | 14.3 tok/s | 11.0 tok/s | **−23%** |
| Mean throughput | 13.5 tok/s | 10.0 tok/s | −26% |
| P95 throughput | 18.2 tok/s | 14.5 tok/s | −20% |
| Median TTFT | 760 ms | 1 491 ms | **+96%** |
| Mean TTFT | 774 ms | 1 516 ms | +96% |
| P95 TTFT | 912 ms | 1 723 ms | +89% |
| Median total latency | 3 905 ms | 5 713 ms | +46% |
| Successful runs | 24 / 24 | 24 / 24 | — |

**Disposition.** DEC-06 was locked OFF on OV GenAI 2026.0 because prefix
caching collapsed speculative-decoding acceptance rate to zero on warm
calls (AO 12K AR 0.402 → 0.003 → 0.000; PA 12K AR 0.167 → 0.000 →
0.000). On OV GenAI 2026.1 — which shipped a "GPU prefix caching
improved" release note — that signature is absent: 24/24 runs succeeded
in both conditions, with no per-run AR collapse pattern, and prefix
caching delivers \~23 % higher TPS and \~50 % lower TTFT (the system
prompt prefill is reused across turns, exactly the property prefix
caching exists for). **DEC-06 is hereby amended: `enable_prefix_caching`
is ON for the shared pipeline (and therefore both PA and AO) on OV
GenAI 2026.1+.**

**Evidence.** `docs/performance/benchmark_2026-05-22_15-55-48.json`
(prefix=ON) and `docs/performance/benchmark_2026-05-22_16-03-44.json`
(prefix=OFF).

### 6.4 Concurrency and PA latency budget

Both PA and AO run synchronously in one process; the
`SharedInferencePipeline.generate()` wrapper acquires a `threading.Lock`
around the underlying `ov_genai.LLMPipeline.generate()`. Single-user
behaviour is unchanged in the no-contention case (PA classification and
AO conversation are sequential in normal use). When they do overlap, the
later caller waits.

The PA's 2 000 ms P95 latency budget (§2.5) must henceforth be tracked
**two ways**:

- **PA-internal**: P95 of classification work *excluding* lock-wait —
  the budget the PA is responsible for.
- **User-visible**: P95 of classification *including* lock-wait — the
  delay the operator perceives.

Live-verification on closure records both. The lock-wait component is
expected to be near-zero in steady-state single-user operation; it
becomes observable only when a PA classification fires while AO is
mid-generation.

### 6.5 Security frame

The shared-pipeline refactor **raises** PA's effective security floor:

- Pre-amendment, the PA's boot-time SHA-256 weight integrity check
  (Red Team ISSUE-003 mitigation Layer 1) covered the target (Qwen3-14B)
  and the PA's *own* draft (Qwen3-0.6B full). The AO's pruned-6L draft
  was loaded without a manifest at all.
- Post-amendment, the launcher's `build_shared_pipeline` runs the
  integrity check against **both** the target and the unified
  pruned-6L draft before pipeline construction. Each consumer's
  `load_model` also still runs its own integrity check on the target
  bin path — defence in depth retained.

PA classification remains isolated from AO conversation state: both
`.generate()` call sites pass self-contained prompts and do not use
`start_chat` / `finish_chat` (verified by grep across the codebase, this
sprint). The wrapper's `.raw` accessor is reserved for boot-time and
unload-time use; no hot-path call should bypass the lock.

The "Red Team ISSUE-003" coupling note in
`shared/models/weight_integrity.py` continues to govern the
PA/consumer-weight-sharing posture; this amendment is consistent with
its already-mitigated coupling assumption.

### 6.6 Draft-model provenance

The Qwen3-0.6B-pruned-6L INT8 draft was acquired via the
OpenVINO-published HuggingFace channel
(`OpenVINO/Qwen3-pruned-6L-from-0.6B-int8-ov`). It is the official Intel
pruning of the Qwen3-0.6B parent (22 hidden layers, 1024 hidden_size,
INT8_ASYM weight compression), intended for use as a speculative draft
against Qwen3-8B-class targets. The §2.3 row's earlier "ELIMINATED"
disposition (P5-005c) is superseded — the OpenVINO repository was
published later and the artifact is now operational.

A Known-Good Manifest covering `openvino_model.bin`,
`openvino_tokenizer.bin`, and `openvino_detokenizer.bin` was committed
in this sprint (commit `32c60de`) to the same on-disk path as the
weights. The detokenizer SHA-256 matches the Qwen3-14B and
Qwen3-0.6B-full manifests — the Qwen3 family detokenizer is identical
across variants. The tokenizer SHA differs (compiled OpenVINO IR
metadata varies across distinct model exports even when vocab is
identical).

The pruned-6L is distributed under the **Intel Research Use License
Agreement**, narrower than the parent Qwen3-0.6B's Apache 2.0. This is
acceptable for the personal-use BlarAI system; future redistribution or
external sharing would need to reconcile the license.

### 6.7 Memory and boot impact

**Pre-amendment, measured** (investigation doc, commit `5c5201d`):
- \~17 GB GPU memory ("Local Usage", BlarAI idle with model loaded)
- \~44 s of model compile per boot (PA \~27 s + AO \~17 s, sequential per
  the pre-sprint launcher.log entries)
- System RAM: 24.5 / 31.32 GB used, < 7 GB free
- Total boot: 43–56 s

**Post-amendment, measured on hardware closure** (2026-05-22, commit
`29bab02` + launcher restart at 16:35:36):
- **8.7 GB GPU memory** (per `scripts/perf_snapshot.py`,
  `gpu = 8694.1 MB`) — **−8.3 GB**
- **\~18 s of one shared model compile** (launcher.log: `Building shared
  LLMPipeline…` at 16:35:38.388 → `Shared pipeline built…` at
  16:35:56.994) — **−26 s vs the pre-sprint two-compile pattern**
- System RAM: **20.4 / 31.32 GB used** — **\~4 GB freed**
- Total boot: **29.9 s** (`perf_snapshot.py boot 29.9s`) — **−13 to
  −26 s vs the 43–56 s pre-sprint band**
- Launcher.log confirms architecture engaged:
  - Exactly one `Shared pipeline built: device=GPU, model_priority=HIGH,
    enable_prefix_caching=True, draft=...models/qwen3-0.6b-pruned-6l/...`
  - Both `PA attached to shared LLMPipeline (single-compilation path).`
    and `AO attached to shared LLMPipeline (single-compilation path).`
    appear; neither service emits the standalone
    `Speculative decoding enabled` log line.
- Behavioural verification: an ordinary AO turn ("What is OpenVINO?")
  streamed a real answer; a follow-up turn ("Summarize it") carried
  context; a PA-routed `/load` of `marketplace_aca_obamacare.txt`
  succeeded ("Loaded marketplace_aca_obamacare.txt (0.1 KB) — ask me
  about it").

**PA P95 latency distributions** (lock-excluded vs. lock-included) are
not yet captured — they require a longer-running session with PA fires
during AO generations to populate the contention distribution. To be
recorded on a later commit once the operator has used the system for
a normal day and the launcher.log holds enough PA classify events to
make the two P95s meaningful.

**Perf-history reference row**: `docs/performance/perf_history.jsonl`
at timestamp `2026-05-22T23:39:13+00:00 (git 29bab02)`. The TTFT cell
in that row reports the latest *benchmark* file (the Phase 0 prefix=OFF
run that landed last by filename mtime), not the operational state —
the live system runs with `enable_prefix_caching=True`, which the
Phase 0 prefix=ON benchmark measured at 760 ms median TTFT (§6.3).

### 6.8 Implementation references

The amendment lands on `feature/shared-pipeline`. Commit chain:

| Commit | Phase | Scope |
|---|---|---|
| `32c60de` | 0 (security prep) | Integrity manifest for the pruned-6L draft |
| `56aaee1` | 0 (seam) | `enable_prefix_caching` param + `--prefix-caching` CLI flag for the benchmark |
| `e713cd8` | 1 | `SharedInferencePipeline` wrapper + `build_shared_pipeline` + 10 unit tests |
| `bc9487d` | 2 | `PolicyGPUInference` and `OrchestratorGPUInference` accept `shared_pipeline` kwarg, branch in `load_model()` |
| `4f2e09e` | 3 | Launcher builds the shared pipeline between VM start and PA boot; threads it through both services' `from_runtime_mode` |
| `bb00fa9` | 4 | Service-side shared-path tests (PA + AO) |
| *(this commit)* | 5 | ADR-012 Amendment 3 + BUILD_JOURNAL entry |

Files: `shared/inference/shared_pipeline.py`,
`services/policy_agent/src/{gpu_inference,entrypoint}.py`,
`services/assistant_orchestrator/src/{gpu_inference,entrypoint}.py`,
`launcher/__main__.py`,
`scripts/benchmark_gpu_inference.py`,
`shared/tests/test_shared_pipeline.py`,
`services/policy_agent/tests/test_gpu_inference.py`,
`services/assistant_orchestrator/tests/test_gpu_inference.py`,
`models/qwen3-0.6b-pruned-6l/openvino-int8-gpu/manifest.json`.

Test outcome at amendment commit: **1247 passed, 2 skipped** on
`pytest shared/ services/ launcher/`. The 2 skipped tests are the
pre-existing baseline skip-triggers; this work added 0 skips and 13
tests (3 service-side shared-path + 10 wrapper).

Closure is gated on live verification of GPU memory, boot time, and an
AO turn plus a PA-routed action on the operator's Lunar Lake hardware,
per `CLAUDE.md` § "Comprehension Gate" and the journal rule that *tests
passing is not a feature working*.
