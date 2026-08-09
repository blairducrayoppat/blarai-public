# Draft — PR #4139 thread comment (collaborator announce + retest), v1

Status: DRAFT — Blair posts after the test commit is pushed (or authorizes both).
Sequence: push commit first, then post this (the comment says "I've pushed").

---

Re-ran the full matrix on the new head (cea6c5f2) — Arc 140V, same model
(`OpenVINO/Qwen3.6-35B-A3B-int4-ov`), same probe, greedy, full ID-sequence comparison
against my 8cf5e45 runs. Quick results:

- **Auto-detect for `reasoning_budget_tokens` (edbd242) works on this model:**
  budget-without-ids no longer raises — and the output is byte-identical (full
  ID-sequence equality) to the explicit-ids budget runs. Nice fix, confirmed on hardware.
- **Everything else is byte-identical between 8cf5e45 and cea6c5f2** on this VLM
  non-chat path — as expected, since the reverse scan sees the same (empty) prompt ids
  there. So the open scope question for @apaniukov is unchanged. One small note: with
  auto-detect, budget-without-ids on this path went from a loud validate() error to the
  same silent no-op as explicit ids — worth remembering when that path gets decided.

Since the scan's new semantics can't be observed on my VLM path, I pinned them at unit
level instead. Taking you up on the collaborator invite — thank you! — I've pushed one
small commit adding 11 gtest cases for `ThinkingBudgetTransform` to
`tests/cpp/logit_filtering.cpp` (test-only, no production changes). They cover the
reverse scan as @apaniukov specified: last think-related token wins; trailing prompt
tokens pre-count against the budget; `</think>`-last → DONE with re-arm on a newly
generated `<think>`; plus budget==0 forcing (including the closed-block case you
confirmed as deliberate), natural close, think-free prompts, unlimited budget, and the
vector logits path. All 11 green at cea6c5f2 on Windows/MSVC; the full
`tests_continuous_batching` suite passes locally too. Feel free to reword/rework any of
it — your PR, your style.

One edge I deliberately did NOT pin, since it's a design call for you: if the prompt's
trailing count already reaches the budget at construction (e.g. `continue_final_message`
with a long partial thought and a small budget), the transform stays in COUNTING and
admits one more generated token before forcing, because the count-vs-budget check only
runs in `accept_token`. Might be fine, might deserve a constructor check — your call;
happy to add the test either way once decided.

Tiny housekeeping note: the new comments in edbd242 are in Chinese — the codebase is
English-commented, so a reviewer will likely flag it. Happy to push a small follow-up
translating them (keeping your content 1:1), or leave it to you — whichever you prefer.

---
*AI assistance disclosure: tests and measurements prepared with AI assistance (Claude);
all results are from real runs on the stated hardware and were human-reviewed before
posting.*
