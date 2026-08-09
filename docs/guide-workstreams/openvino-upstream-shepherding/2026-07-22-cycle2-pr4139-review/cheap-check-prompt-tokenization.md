# Measurement record — PR #4139 pre-build tokenization check

**Purpose:** predict, before spending hours on a build, whether commit `8cf5e450`'s new
prompt-scan initial-state logic engages on Qwen3.6-35B-A3B — i.e. whether
`reasoning_budget_tokens = N > 0` will actually cap generation or silently no-op.

**Status:** tokenizer-level only. **No hardware execution. No generation measured.**

---

## Provenance

| Field | Value |
|---|---|
| Date (local) | 2026-07-22 |
| Operator | Blair (`blairducrayoppat`), requested reviewer on PR #4139 |
| Machine | Windows 11 Pro 10.0.26200 |
| Hardware exercised | **None** — CPU-only tokenizer IR load; the Arc 140V was not used |
| `openvino` | `2026.4.0-22479-f7a1b8249a9` (dev nightly) |
| `openvino_genai` | `2026.4.0.0-1-f3e59fb36bf-feat/thinking-suppression` (wheel built from `f3e59fb`) |
| Model | `OpenVINO/Qwen3.6-35B-A3B-int4-ov` (official IR), local copy `C:/Users/mrbla/models/qwen36-35b-a3b-int4-ov-OFFICIAL` |
| Precision | INT4 (irrelevant here — tokenizer only) |
| Prompt | `"How many bytes are in one kilobyte?"` (byte-identical to the standing probes) |
| Script | `scratchpad/cheap_check_prompt_tokens.py` |
| Raw output | `scratchpad/cheap_check_result.json` |

**Note on the wheel version:** the installed genai wheel is built from `f3e59fb`, two commits
behind PR head `8cf5e450`. This does **not** affect validity — nothing in this check exercises
the transform. Only `Tokenizer` (encode + `apply_chat_template`) is used, and the PR does not
modify the tokenizer. The `8cf5e450` constructor scan is *simulated in Python* over the real
token IDs, not executed.

---

## Method

1. Read ground-truth `<think>` / `</think>` IDs from the model's `tokenizer.json` `added_tokens`.
2. Replicate the PR's auto-detect exactly as written in `py_vlm_pipeline.cpp` /
   `py_llm_pipeline.cpp`: `tok.encode("<think>")`, accept only if `input_ids` size == 1.
3. Render the chat prompt two ways via `Tokenizer.apply_chat_template(history, True, ...)`:
   thinking enabled (default) and `extra_context={"enable_thinking": False}`.
4. Encode each with `add_special_tokens=False`; dump the token IDs.
5. Simulate the `8cf5e450` constructor scan verbatim over those IDs.

---

## Results

### Token IDs

`<think>` = **248068**, `</think>` = **248069** — both present as real single `added_tokens`.

### PR auto-detect: **SUCCEEDS**

```
encode('<think>')  [default]                  -> [248068]   size==1  ACCEPTED
encode('<think>')  [add_special_tokens=False] -> [248068]   size==1  ACCEPTED
encode('</think>') [default]                  -> [248069]   size==1  ACCEPTED
encode('</think>') [add_special_tokens=False] -> [248069]   size==1  ACCEPTED
```

So `thinking_start_token_id = 248068`, `thinking_end_token_id = 248069` are set automatically;
the transform *is* constructed (`logit_processor.hpp:126` gate passes).

### Prompt A — thinking ENABLED (default template)

Rendered tail: `...<|im_start|>assistant\n<think>\n`
20 tokens. Last 12: `[799, 14609, 26148, 647, 30, 248046, 198, 248045, 74455, 198, 248068, 198]`

- `<think>` (248068) present at **index 18 of 20**
- **Last token is 198 (`\n`), NOT 248068**
- Last *think-related* token = 248068 (start) → `found_open_think = True`

**→ initial state: `COUNTING`** (budget N>0) / `FORCING` (budget==0)

### Prompt B — thinking DISABLED via `extra_context`

Rendered tail: `...<|im_start|>assistant\n<think>\n\n</think>\n\n`
22 tokens. Last 12: `[26148, 647, 30, 248046, 198, 248045, 74455, 198, 248068, 271, 248069, 271]`

- Both 248068 (idx 18) and 248069 (idx 20) present
- Last think-related token = 248069 (end) → `found_open_think = False`

**→ initial state: `IDLE`** (budget N>0) / `FORCING` (budget==0)

---

## Findings

**1. My stated prediction was FALSIFIED — and that is a good outcome.**
I predicted `reasoning_budget_tokens` might silently no-op on this model under the new scan
(state landing in IDLE). It does not. On the default template the scan lands in **COUNTING**,
because it searches the *whole* prompt rather than only the last token. `8cf5e450` works
correctly here.

**2. Independent hard-data confirmation of the author's 07-17 root cause.**
The author diagnosed the old `input_ids.back() == start_id` check as always-false because the
prompt ends with a newline. Confirmed exactly: the final token is **198 (`\n`)** and 248068 sits
at index 18 of 20. Their diagnosis was right, with token-level evidence.

**3. `8cf5e450` is behaviourally a NO-OP on the standing probe's conditions.**
Comparing initial state before (`5166cd3e`, always-COUNTING) and after (`8cf5e450`, scan):

| Condition | `5166cd3e` | `8cf5e450` | Changed? |
|---|---|---|---|
| default template + `enable_thinking=False` | FORCING | FORCING | no |
| default template + `reasoning_budget_tokens=N>0` | COUNTING | COUNTING | **no** |
| `extra_context` disabled + `reasoning_budget_tokens=N>0` | COUNTING | **IDLE** | **YES** |
| `extra_context` disabled + `enable_thinking=False` | FORCING | FORCING | no |

The existing probe (conditions A/B/C, default template only) **cannot show a pre/post delta**.
Demonstrating the improvement empirically requires adding an `extra_context` condition.

**4. Open observation — the scan result is discarded when `budget == 0`.**
`if (m_budget == 0) m_state = FORCING;` runs unconditionally *after* the scan. So when a user
combines `extra_context={"enable_thinking": False}` (prompt already contains a closed block)
with `generate(enable_thinking=False)` (→ budget 0), the transform still forces a **second,
redundant `</think>`** as the first generated token. The scan has just computed exactly the
information needed to avoid that (`found_open_think == False`) and then throws it away.

This is the border case Copilot raised on 07-11 and the author consciously deferred as rare.
**It is not obviously a bug to fix:** for Qwen3.5/3.6, which emit "naked" untagged reasoning,
starting in a non-forcing state when `found_open_think == False` would break the very
suppression measured as working on 07-17. The trade-off is real and the author's simple choice
may be deliberate. **Flagged for measurement, not asserted as a defect.**

---

## What was NOT measured

- Any generation. No tokens were produced by the model.
- Any GPU / Arc 140V execution. Nothing ran on the Xe2 hardware.
- Whether the VLM sampling path reaches `ThinkingBudgetTransform` at all at runtime.
- Whether `reasoning_budget_tokens=N` actually truncates reasoning in practice (COUNTING is a
  *necessary* precondition, not proof of the end-to-end effect).
- The C++-only path — this reflects the Python binding path the probe uses.
- Any model other than Qwen3.6-35B-A3B-int4-ov.

These all require the rebuild at `8cf5e450` and a run on the 140V.
