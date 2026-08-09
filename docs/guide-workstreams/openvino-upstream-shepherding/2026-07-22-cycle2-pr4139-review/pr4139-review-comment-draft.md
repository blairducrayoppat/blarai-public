# DRAFT v3 — PR #4139 review comment (post as `blairducrayoppat`)

*Status: DRAFT v3 for Blair's review. Not posted. Plain comment (no formal verdict),
collaborator-with-evidence framing. v2: §3+§4 merged as one mechanism; "regression" softened
+ scope question; first-behavioral-measurement point; C0 cited by message text. v3: scope
question routed to @apaniukov (Intel maintainer) while staying warm to the author (community
member); responsiveness credit added; conditional prototyping offer appended.*
*SHAs verified against the PR commits API: head `8cf5e4502f330e423794aca8a1f7e299eed7c061`,
parent `5166cd3e4c719ee85924759a55c0f75a87d8e144`. Code line refs verified by reading both
files at those exact commits.*

---

Re-tested the updated branch on Arc 140V as promised — this time comparing the new head
(8cf5e45) against its parent (5166cd3) so the effect of the prompt-scan change is isolated
exactly. Model: `OpenVINO/Qwen3.6-35B-A3B-int4-ov` (official IR, the #3937 model),
VLMPipeline on GPU, greedy, prompt `"How many bytes are in one kilobyte?"`, openvino 2026.4
dev nightly, both wheels built from source from this branch. A streamer captured every
generated token ID, so all positions below are exact stream indices, not text heuristics.
Raw JSONs for every run available as before. And before the details — turning around
@apaniukov's design suggestion overnight, with the state machine reworked cleanly, is great
responsiveness; this PR keeps getting better with each pass.

**TL;DR:** `enable_thinking=False` now works cleanly with no manual IDs — nice. The
prompt-scan change reads as sound where the sampler sees real prompt ids, and I can show
empirically that it removes a real output-corruption case. On the VLMPipeline non-chat path,
though, the ids the scan receives appear to be pad placeholders (the LM consumes
embeddings), which makes the scan inert there — that inertness is what removes the
corruption on this path, and it also leaves `reasoning_budget_tokens > 0` unengaged (it did
engage on the parent). Main scope question — probably @apaniukov's call: is budget-capping
meant to be supported on the VLM non-chat path? Details and, I believe, the first behavioral
measurements of the cap actually firing, below.

## 1. Your root-cause diagnosis from the 17th — confirmed at token level

The default chat template renders `...assistant\n<think>\n` → 20 tokens ending
`[..., 248068, 198]`: `<think>` (248068) sits at index 18 and the **last token is the
newline (198)**, exactly as you diagnosed. A last-token-only check is structurally
always-false on this template, and the new whole-prompt scan is the right generalization of
that check at the logic level (though see §3 for whether the sampler actually receives these
template tokens at runtime).

## 2. `enable_thinking=False` — works, now ID-less ✅

- No manual IDs: forced `</think>` (248069) at index 0, then a coherent direct answer.
- With explicit IDs: **byte-identical output** (full ID-sequence equality) — auto-detect
  resolves exactly the right IDs (248068/248069) on this model.

This closes the last gap I'd measured on this model. Nice work on the auto-detect.

## 3. The prompt-scan change on this VLM path — one mechanism, two measured effects

What I believe is happening (please correct me if I'm misreading the flow): on the
VLMPipeline non-chat path, the sequence group's prompt ids are built as a pad-filled
placeholder — `visual_language/pipeline.cpp` (L802–806 at 8cf5e45) fills the tensor with
`get_pad_token_id()` (248044 here) and copies in `tokenized_history`, which is empty for a
one-shot `generate()`. The sampler passes exactly these ids to `LogitProcessor`
(`sampler.cpp` L1701), so the constructor scan sees only pad tokens regardless of what the
prompt actually contains, finds neither 248068 nor 248069, and always starts in IDLE. And
since this model never emits `<think>` during generation (confirmed again at ID level:
248068 never appears in any of my runs, either build), the transform then never leaves IDLE.
`budget==0` bypasses the scan (`if (m_budget == 0) m_state = FORCING;`), which is why
`enable_thinking=False` in §2 still works.

If that reading is right, the scan being inert on this path has two visible effects — one
welcome, one that raises a scope question:

**3a. The closed-block corruption is gone (measured before/after).** Closed-block prompt
(rendered with `extra_context={"enable_thinking": False}`, ending `<think>\n\n</think>\n\n`)
+ `reasoning_budget_tokens=32`:

- **Parent (5166cd3):** spurious `</think>` forced at index 32, landing mid-answer — the
  output visibly corrupts: `"...two different standards:\n\n### 1</think>"`.
- **Head (8cf5e45):** clean direct answer, no spurious forcing.

Same prompt, same silicon, only the two changed files differ between the builds — empirical
confirmation that the unconditional-COUNTING behavior @apaniukov flagged caused a real
failure mode, and that the change removes it. One honesty note: on *this* path the clean
result comes from the scan seeing pad ids (IDLE for every prompt) rather than from it
reading the closed block; on paths where the sampler has real prompt ids, the same clean
result should come from the scan proper.

**3b. `reasoning_budget_tokens > 0` no longer engages on this path (measured before/after).**
Budget sweep at head, explicit IDs set, 300 new tokens, greedy:

| budget | head (8cf5e45) | parent (5166cd3) |
|---|---|---|
| 8 | never fires | — |
| 32 | never fires | **`</think>` forced at exactly index 32** |
| 128 | never fires | — |

At head, all three budgets produce output **byte-identical to the default run** (sha-verified
over full ID sequences — a silent no-op). On the parent, the counter is exact: 32 reasoning
tokens, then 248069 at index 32 — no off-by-one.

Worth noting for scope: the PR's unit tests cover the config-validation plumbing for these
fields (which they do well — the invalid combinations all raise), and as far as I can tell
the runs above are the first behavioral measurement of the cap actually firing — so this
isn't something an existing test contradicts; it just hadn't been visible yet. That's
exactly the gap a hardware test bench is for, and the parent-commit data shows the counting
mechanism itself is precise.

**So my main question — and this is probably a scope call for @apaniukov:** is
`reasoning_budget_tokens > 0` intended to be supported on the VLM non-chat path? Relative to
the parent commit this is a behavior change on that specific combination (default-template
prompt + budget > 0, VLMPipeline non-chat) — whether to call it a regression depends on
whether that combination is meant to work, which I'll defer to you on. If it is meant to
work, the fix probably belongs at the VLM layer —
threading the real tokenized prompt ids into the sequence group where available — rather
than in the transform itself; if it isn't (or is deferred), a docs note or a loud error
might spare users the silent no-op. I couldn't test an LLMPipeline path with this model (it
ships only as a VLM IR), so I'd guess paths with real prompt ids are unaffected, but that's
untested here.

## 4. Smaller observations

- **Budget-cap coherence (this model):** when the cap fires (parent, budget=32), the model
  continues its numbered reasoning *after* the forced `</think>` rather than pivoting to an
  answer — the cap inserts the tag but doesn't redirect generation. Anyone splitting on the
  first `</think>` would read continuing reasoning as the answer. By contrast, forcing at
  index 0 (`enable_thinking=False`) does yield an immediate clean answer. May be inherent to
  mid-stream forcing on a naked-reasoning model; worth a line in the docs perhaps.
- **API asymmetry:** `enable_thinking=False` without IDs auto-detects; `reasoning_budget_tokens`
  without IDs raises the validate() error ("thinking_start_token_id and thinking_end_token_id
  must both be set when reasoning_budget_tokens is enabled"). The loud error is good — but
  the asymmetry may surprise budget-only users, since auto-detect is gated on
  `!enable_thinking` in the bindings.
- **Closed-block + `enable_thinking=False`:** still emits one redundant `</think>` at index 0
  (byte-identical on both builds). The scan actually computes the needed information
  (`found_open_think=false`) but `budget==0` overrides it. I can see this may be deliberate —
  on this model, *not* forcing would break suppression entirely, since it reasons untagged
  regardless of the prompt — so just flagging the trade-off for a maintainer's eye.

Happy to re-run any of this on revisions, same hardware and model — the harness makes
re-tests cheap now.

Separately — if threading the real prompt_ids through on the VLM path turns out to be in
scope (@apaniukov's call) and you'd find it useful, I'm happy to prototype that and validate
it on the same Arc 140V / Qwen3.6-35B-A3B setup. Whatever's easiest for you — a small PR
against your branch, or you adding me so I can push. Your PR and your call; just offering
the hardware and the hands. Really nice work getting this in front of the maintainers.

---
*AI assistance disclosure: measurement harness and analysis prepared with AI assistance
(Claude); all numbers are from real runs on the stated hardware and were human-reviewed
before posting.*
