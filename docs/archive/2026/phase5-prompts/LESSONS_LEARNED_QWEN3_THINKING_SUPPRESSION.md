---
title: LESSONS_LEARNED_QWEN3_THINKING_SUPPRESSION
status: archived
area: portfolio
---

# Lessons Learned: Qwen3 Thinking Suppression with OpenVINO GenAI

**Date:** 2026-04-17  
**Discovered during:** Task 4.12g D3 smoke gate debugging (6 runs to PASS)  
**Applies to:** Any BlarAI component using `LLMPipeline.generate()` with Qwen3 models  
**References:** ADR-012 §2.4 Amendment 2, Ledger Entry 32, commit `6c5159a`

---

## 1. Critical Constraint: OV GenAI Stop-Token Suppression

**OpenVINO GenAI suppresses stop-token checking for any token ID that appears anywhere in the input context string.**

This is not documented prominently in OpenVINO GenAI docs. It was discovered empirically across Runs 3–5 of Task 4.12g. The consequence:

- If you set `stop_token_ids = [151667]` (`<think>`) but your prompt already contains `<think>` as part of an assistant prefill, the stop will **silently never fire**.
- The model continues generating indefinitely (up to `max_new_tokens` ceiling).
- No error, no warning — the run just exhausts the token budget and TRUNCs.

**Rule:** The only safe stop token is one that **cannot appear in the input context**. For Qwen3 chat format, that is `<|im_end|>` (token ID 151645).

---

## 2. Verified Qwen3 Token IDs

Verified via `tokenizer.decode([id])` on the Qwen3-14B tokenizer:

| Token ID | String | Notes |
|----------|--------|-------|
| `151645` | `<\|im_end\|>` | Chat turn terminator. **SAFE as stop token.** |
| `151667` | `<think>` | Thinking mode OPEN. **Cannot be stop target when prefill is used.** |
| `151668` | `</think>` | Thinking mode CLOSE. **Cannot be stop target when prefill is used.** |

> **Common mistake:** The original BlarAI code used `QWEN3_THINK_START_TOKEN_ID = 151_668`.
> That is WRONG — 151668 is the CLOSE tag (`</think>`), not OPEN. The OPEN tag is 151667.
> The notation `<|think|>` seen in early docs is also wrong — the actual strings are `<think>` and `</think>` (no pipe characters).

---

## 3. Canonical Qwen3 Thinking-Suppression Recipe

This is the **only approach that works** with OV GenAI `LLMPipeline.generate()`.  
It mirrors what `tokenizer.apply_chat_template(..., enable_thinking=False)` produces.

### Prompt format

```
<|im_start|>system
{system_prompt}<|im_end|>
<|im_start|>user
{user_content} /no_think<|im_end|>
<|im_start|>assistant
<think>

</think>

```

Three signals must be present simultaneously:

| Signal | Where | Purpose |
|--------|-------|---------|
| ` /no_think` appended to user turn | User message text | Qwen3 soft directive to skip reasoning |
| `<think>\n\n</think>\n\n` assistant prefill | End of prompt string, after `<\|im_start\|>assistant\n` | Consumed as INPUT — model generates AFTER this |
| `stop_token_ids = [151645]` | GenerationConfig | Stop on `<\|im_end\|>` only; thinking token IDs excluded |

### Why the prefill works

The prefill string `<think>\n\n</think>\n\n` is passed as part of the INPUT context, not generated. OpenVINO GenAI treats everything in the prompt string as already-generated context. The model's first generated token is therefore the first token of the actual response (the label for PA classification). With `max_new_tokens=10`, the model produces something like `DECISION: ALLOW\n<|im_end|>` and stops cleanly.

### Python implementation

```python
# In gpu_inference.py — build_prompt()
def build_prompt(cls, car):
    car_text = cls.format_car(car)
    return (
        f"<|im_start|>system\n{cls.SYSTEM_PROMPT}<|im_end|>\n"
        f"<|im_start|>user\n{car_text} /no_think<|im_end|>\n"
        f"<|im_start|>assistant\n<think>\n\n</think>\n\n"
    )

# In GenerationConfig setup
QWEN3_IM_END_TOKEN_ID: int = 151_645
gen_config.stop_token_ids = [QWEN3_IM_END_TOKEN_ID]  # <|im_end|> ONLY
gen_config.max_new_tokens = 10
gen_config.do_sample = False
```

---

## 4. Run Failure Analysis (6 Runs to PASS)

| Run | Stop Config | Prompt Format | Failure Mode | Root Cause |
|-----|-------------|---------------|-------------|------------|
| 1 | `[151645, 151668]` | No `/no_think`, no prefill | `think=True(TRUNC)`, 0 labels | `</think>` only fires when thinking completes; 10-token budget exhausted first |
| 2 | `[151645, 151668]` | `/no_think` user turn, no prefill | `think=True`, 0 labels | `</think>` (151668) was wrong ID — actually fires on token 1 but incorrect parsing |
| 3 | `[151645, 151668]` | Empty `<think></think>` prefill | `think=True(TRUNC)` | OV GenAI suppresses 151668 stop — token is in input context |
| 4 | `[151645, 151667]` | Full `<think>\n\n</think>\n\n` prefill | `think=True(TRUNC)` | OV GenAI suppresses 151667 stop — token is in input context |
| 5 | `[151645, 151667]` | `/no_think` user turn only, NO prefill | `raw='<think>'`, 0 labels | Stop 151667 fires on token 1 (model generates `<think>` as first token even with `/no_think`, if no prefill) |
| **6** | `[151645]` | `/no_think` + full prefill | **PASS** (0.9483, 55/58) | Prefill consumed as input; model generates label tokens only |

### Key insight from Run 5

Without the assistant prefill, the Qwen3 model will generate `<think>` as its first token even when `/no_think` is in the user turn. The user turn directive alone is insufficient when using `LLMPipeline.generate()` with an explicit prompt string. The model needs the "pre-filled" thinking block to skip the thinking phase.

### Key insight from Runs 3–4

The OV GenAI suppression applies to the **exact token ID**, not the string. Placing `<think>` in the prompt prefill (even as a properly closed empty block) causes OV GenAI to suppress stop checking for both 151667 and 151668, regardless of where in the prompt they appear.

---

## 5. Parsing Side Effects

When the canonical recipe is used, the raw output from `pipeline.generate()` looks like:

```
DECISION: ALLOW
<|im_end|>
```

However, if the **full prompt string** (including the prefill) is prepended to the output before parsing, the harness may see `<think>\n\n</think>\n\n` in the combined string and set `think_block_present=True`. This is **cosmetic only** — the model did not generate those tokens. Label extraction is unaffected. The `think_block_present` flag is unreliable when assistant prefill is used; do not use it as a quality signal.

---

## 6. Scope: Where This Applies

| Component | Uses Thinking Suppression? | Notes |
|-----------|--------------------------|-------|
| Policy Agent (`gpu_inference.py`) | YES — `/no_think` MANDATORY | Canonical recipe locked. `max_new_tokens=10`. |
| Assistant Orchestrator | NO — thinking allowed | Uses `stop_token_ids=[151645]` only, no prefill needed |
| USE-CASE-005 Code Agent | PARTIAL — `/no_think` for simple completions | Not yet in production. Will need canonical recipe for `/no_think` mode. |

---

## 7. What NOT to Do (Anti-patterns)

1. **Do NOT** add `151667` or `151668` to `stop_token_ids` when using an assistant prefill. They will be silently suppressed by OV GenAI.
2. **Do NOT** rely on `/no_think` in the user turn alone (without the assistant prefill). The model will generate `<think>` as its first token.
3. **Do NOT** use `max_new_tokens` > 10 for PA classification. Even with correct suppression, this creates latency risk and is unnecessary — the label fits in ≤ 5 tokens.
4. **Do NOT** use `151668` as `QWEN3_THINK_START_TOKEN_ID`. It is `</think>` (CLOSE), not `<think>` (OPEN).
5. **Do NOT** write `<|think|>` or `</|think|>` anywhere in prompt strings or documentation. These notations are incorrect. The actual Qwen3 tags are `<think>` and `</think>`.

---

## 8. Verification Command (Rebuild Sanity Check)

After rebuilding `gpu_inference.py`, verify the canonical recipe produces a clean label:

```powershell
# From BlarAI root, with venv active:
.venv\Scripts\python.exe phase2_gates/scripts/run_p5_task4_9_pa_quality_gate.py --smoke
# Expected: DISPOSITION: PASS, decision_agreement_rate >= 0.90, label_extraction_failures = 0
```

Evidence artifact: `phase2_gates/evidence/p5_task4_12_corpus_hardening.json`  
Baseline (Run 6): `decision_agreement_rate = 0.9483`, `adversarial_security_rate = 1.0000`
