# Measurement record — PR #4139 commit `8cf5e450` vs `5166cd3e` on Arc 140V

**Question:** does commit `8cf5e4502f330e423794aca8a1f7e299eed7c061` ("Determine initial
ThinkingBudgetTransform state by scanning prompt_ids" — implementing maintainer apaniukov's
2026-07-22 suggestion) behave correctly on Qwen3.6-35B-A3B, the model of linked issue #3937?

**Answer in one line:** it fixes real spurious-forcing bugs, but on the VLMPipeline non-chat
path the scan reads **pad-token placeholders instead of real prompt tokens**, so
`reasoning_budget_tokens > 0` silently no-ops — a regression vs its parent commit, measured
byte-exactly on hardware.

---

## Provenance

| Field | Value |
|---|---|
| Date (local) | 2026-07-22 evening |
| Operator | Blair (`blairducrayoppat`), requested reviewer on PR #4139 (requested 2026-07-23T01:38:52Z) |
| Hardware | Intel Core Ultra 7 258V / **Arc 140V (Xe2, Lunar Lake)**, driver 32.0.101.8826, Windows 11 Pro 26200 |
| `openvino` | 2026.4.0-22479-f7a1b8249a9 (dev nightly) |
| Build A wheel | `2026.4.0.0-50-8cf5e4502f3` — **PR head** `8cf5e4502f330e423794aca8a1f7e299eed7c061` |
| Build B wheel | `2026.4.0.0-49-5166cd3e4c7` — **parent** `5166cd3e4c719ee85924759a55c0f75a87d8e144` (only 2 files differ: `logit_processor.hpp`, `logit_transformers.hpp`) |
| Model | `OpenVINO/Qwen3.6-35B-A3B-int4-ov` (official IR, INT4_ASYM g64), local `C:/Users/mrbla/models/qwen36-35b-a3b-int4-ov-OFFICIAL` |
| Pipeline | `VLMPipeline`, device `GPU`, greedy (`do_sample=False`) |
| Prompt | `"How many bytes are in one kilobyte?"` (byte-identical to all standing probes) |
| Probe | `probe_pr4139_35b_v2.py` (repo root, untracked) |
| Raw JSONs | `docs/performance/probe_pr4139_v2_2026.4.0.0-50-8cf5e4502f3-feat-thinking-suppression_2026-07-22_20-24-08.json` (A); `...-49-5166cd3e4c7_2026-07-22_20-33-54.json` (B) |
| Load times | 33.9 s (A) / 40.5 s (B); per-condition 20–47 s (provenance only, NOT a perf claim) |

**Why VLMPipeline:** the path validated in the 2026-07-17 run on this exact model; the PR's
auto-detect fix modified `py_vlm_pipeline.cpp`; and this model ships only as a VLM IR.

**Methodology:** a `StreamerBase` subclass captured **every generated token ID**, so all
positions/counts below are exact stream indices (0-based), not re-tokenization estimates.
Full outputs sha256-hashed; byte-identity claims verified over full ID sequences, never prefixes.
Token IDs: `<think>` = 248068, `</think>` = 248069, pad `<|endoftext|>` = 248044 (all from
`tokenizer.json` `added_tokens`).

**Prompt renders** (via `Tokenizer.apply_chat_template`): default = 20 tokens, tail
`[..., 248068, 198]` (`<think>` at index 18, **last token is `\n`=198**); closed-block
(`extra_context={"enable_thinking": False}`) = 22 tokens, tail `[..., 248068, 271, 248069, 271]`.
D/E passed the pre-rendered closed-block prompt with `cfg.apply_chat_template=False`;
`perf_num_input_tokens=22` matched the render exactly ⇒ no double-templating.

---

## Results matrix

max_new_tokens: 220 for A/B/B2 (cross-run comparability), 300 for C/D/E (room for post-think answer).

| Cond | Config | Build A (head `8cf5e450`) | Build B (parent `5166cd3e`) |
|---|---|---|---|
| A | default | naked reasoning, no 248068/248069 in 220 ids, sha `492c6a24` | — |
| B | `enable_thinking=False`, **no IDs** | **248069 forced at index 0**, then coherent direct answer; sha `c24d78c8` | — |
| B2 | same + explicit IDs | **byte-identical to B** (full ID equality) — auto-detect ≡ manual IDs | — |
| C0 | `budget=32`, no IDs | **loud error**: `Check 'thinking_start_token_id >= 0 && thinking_end_token_id >= 0' failed` (generation_config.cpp:321) | — |
| C8/C32/C128 | budget sweep + IDs | **never fires**: all three byte-identical to each other (sha `87805ecb`) AND first-220 ids ≡ condition A. Silent no-op at every N | C32: **248069 forced at exactly index 32**; first-32 ids ≡ head's C32 |
| D | closed-block + `budget=32` + IDs | clean direct answer, **no reasoning, no forcing** (sha `77c19e99`) — correct | **spurious 248069 at index 32, mid-answer**: `"### 1</think>"` — visible corruption |
| E | closed-block + `enable_thinking=False` + IDs | redundant 248069 at index 0, then clean answer (sha `a1f20871`) | **byte-identical to head** (full ID equality) |

248068 was never generated in any condition on either build — ID-level confirmation of the
07-17 text-level finding that this model emits naked (untagged) reasoning.

---

## Findings

**F1 — The author's 07-17 root-cause diagnosis is confirmed at token level.** The default
prompt's last token is 198 (`\n`); `<think>`=248068 sits at index 18 of 20. Any
last-token-only check is structurally always-false on this template.

**F2 — `enable_thinking=False` works, now without manual IDs.** Auto-detect (`5166cd3e`)
verified: B ≡ B2 byte-identical, forced `</think>` at index 0, coherent direct answer.
This closes the gap measured here on 07-17 (that run's wheel predated auto-detect).

**F3 — HEADLINE: `reasoning_budget_tokens > 0` silently no-ops at head on the VLM non-chat
path; it worked on the parent commit.** Head: budgets 8/32/128 all produce output
ID-identical to default. Parent: budget fires at exactly N=32 (no off-by-one: 32 reasoning
tokens, index 32 is 248069).

**Root cause (code-level, verified at `8cf5e450`):** `src/cpp/src/visual_language/pipeline.cpp:802-806`
builds the sequence group's `prompt_ids` as a **pad-filled placeholder** (`fill_n` with
`get_pad_token_id()`=248044; `tokenized_history` is empty for non-chat one-shot generate) —
the LM consumes embeddings, so real token IDs aren't threaded through. `sampler.cpp:1701`
passes exactly these ids to `LogitProcessor`, so the new constructor scan sees 20×248044,
finds neither 248068 nor 248069 → `found_open_think=false` → IDLE → with the model never
emitting 248068, COUNTING is never entered and the budget never trips. `budget==0` bypasses
the scan (`if (m_budget == 0) m_state = FORCING;`), which is why B/B2/E still work.

**F4 — apaniukov's suggested change fixes a real, measured bug.** Parent build D: forced
`</think>` at index 32 lands mid-answer (`"### 1</think>"`) on a closed-block prompt —
spurious corruption. Head build D: clean passthrough. Empirical before/after on the same
prompt, same silicon. (Caveat: on this VLM path, head-D's IDLE comes from the pad scan, so it
is right-for-the-wrong-reason here; on paths with real prompt_ids the scan logic itself is sound.)

**F5 — Budget-cap coherence (usability observation, this model).** When the cap fires
(parent C32), the forced `</think>` lands mid-sentence and the model **continues its numbered
reasoning after the tag** (`"2. **Recall/Verify Knowledge**..."`) rather than pivoting to a
final answer. The mechanism caps the *tag*, not the reasoning. Consumers splitting on first
`</think>` would read continuing reasoning as the answer. Contrast: budget==0 forcing (B/E)
does produce an immediate clean answer.

**F6 — API asymmetry.** `enable_thinking=False` without IDs → auto-detected (silent success).
`reasoning_budget_tokens` without IDs → hard validation error (C0). Loud beats silent, but
the asymmetry (auto-detect is gated on `!enable_thinking` in the bindings) may surprise
budget-only users.

**F7 — Redundant forcing on closed-block prompts (known border case, now measured).**
E: closed-block prompt + `enable_thinking=False` → a second `</think>` forced at index 0,
byte-identical on both builds. The scan computes `found_open_think=false` — exactly the
information needed to skip the redundant token — then `budget==0` discards it. Possibly a
deliberate trade-off: on this naked-reasoning model, NOT forcing when the scan says "closed"
would break the suppression itself (the model reasons regardless). Recorded as an
observation, not asserted as a defect.

## What was NOT measured

- LLMPipeline path (this model ships only as a VLM IR) — the budget may work correctly there,
  where sequence groups carry real prompt ids; the author's own models were tested on other
  pipelines. The F3 regression claim is scoped to **VLMPipeline non-chat**.
- VLM **chat mode** (`start_chat`), where `tokenized_history` is non-empty and the scan may
  see real ids.
- C++-only API, other models, sampling (non-greedy), throughput/latency as a claim.
- Whether `8cf5e450` changes behaviour on models that DO emit `<think>` during generation.
