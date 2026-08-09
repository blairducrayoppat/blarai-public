# DRAFT v2 — PR #4139 review at head 4c0e8d6d (review re-requested from Blair). NOT posted.

Target: https://github.com/openvinotoolkit/openvino.genai/pull/4139
Type: COMMENT review (same as 4765132029) — clears the re-request without approving/blocking.
Blair posts.

Trigger: author comment `5065194831` (2026-07-24T01:24:20Z) + commit `4c0e8d6d`
("Add constructor check for trailing count reaching budget") + review re-requested
from `blairducrayoppat`.

v2 changes: four technical claims corrected (see VERIFICATION.md "Self-audit corrections"),
and trimmed ~7.5k → ~5.1k after the volume finding (Blair was running ~3:1 against a
freshman author whose own replies are getting shorter). See ADVERSARIAL-FINDINGS.md.

8< ---------------------------------------------------------------- 8<

Retested at `4c0e8d6d` on Windows / MSVC 19.44 x64, plus an end-to-end run on GPU
(Qwen3-14B INT4, Arc 140V) with and without your five lines.

**On `4c0e8d6d`.** Reads correct to me: the new check uses the same predicate as the
`COUNTING` branch of `accept_token`, so the boundary is identical whether the budget is
reached by trailing prompt tokens or by generated ones — which was exactly the asymmetry.
One note: the `m_budget >= 0` guard is belt-and-braces rather than load-bearing, since a
negative budget converts to a huge `size_t` and the comparison is false anyway. Worth
keeping for readability, just not the thing protecting the disabled case.

Two things that might save the next reviewer a pass. Against the reverse-scan spec asked
for in review — walk backwards, count tokens, break on the first think token found,
`start_id` → `COUNTING` with `m_count` seeded from the counter, `end_id` → `DONE`,
neither → `IDLE` — the implementation now matches all five points. And the new check is
inert on the empty-`prompt_ids` path: with no tokens to scan the state stays `IDLE`, and
the check is gated on `COUNTING`, so it can't misfire on the VLM case while that's still
open.

**Retest.** All 11 existing tests pass here too, so that's your Linux/GCC run and
Windows/MSVC agreeing. Full binary with the three tests below added: 567 of 569, the two
failures being the `CACHE_TYPES_CSV` guards from my earlier correction (the PR without
my three measured 564 of 566 when I ran it at `f90cc87`). Worth knowing if you re-run:
across 10 runs of the full binary I got 567 passing six times and 566 four times, from
two prefix-caching tests this PR doesn't touch flaking intermittently. So don't read the
exact total too closely — mine or yours.

`87acf7b8` also left no CJK anywhere in the nine files this PR touches — I checked all of
them. The seven typographic codepoints that remain are all inside comments and raised no
C4819 here, though that's one toolchain rather than a guarantee.

**End-to-end on hardware.** The unit tests pin the state machine, but they can't show the
transform is actually built with a populated `prompt_ids` on a real inference path —
worth closing given where the VLM half of this PR came from. The fix only engages when
the prompt itself carries an open think block, so I built that prefill shape explicitly:
a raw prompt ending `<think>\n`, giving 17 prompt tokens with the last `<think>` at index
15 and exactly one token trailing it. Then swept the budget on Qwen3-14B INT4 on GPU,
greedy, against builds of this branch with and without your five lines. Exactly one row
moves:

| `reasoning_budget_tokens` | before | after |
|---|---|---|
| 0 | closes immediately | same |
| **1** | **one reasoning token, then `</think>`** | **closes immediately** |
| 2 | one reasoning token | same |
| 3 | two reasoning tokens | same |
| -1 | never closes | same |

The giveaway is that *before* the fix, `budget=1` and `budget=2` emitted byte-identical
token sequences — the prompt's trailing `\n` had already spent a budget of 1, yet one
more token still got through. After, `budget=1` matches `budget=0`.

Two things make that an isolation rather than a build artefact. Only genai's own DLL
differs between the runs — same OpenVINO runtime, same GPU plugin, same model files, and
under greedy decoding the arithmetic all lives in the plugin. And the state machine
predicts all ten cells, not just the one that moved: with a trailing count of 1,
`budget=1` is the only row where the old and new constructors *can* disagree. The two
builds differ by your five lines and nothing else — I diffed `cea6c5f2..4c0e8d6d` across
every path, and the only other changes are comment text.

The `-1` row is the control: it never closes inside 20 tokens, so every close in the
other rows is forced rather than the model stopping on its own. That also means
`prompt_ids` was populated here — had it been empty, the scan would have found no think
token, left the state `IDLE`, and nothing could ever have forced a close. Worth being
precise that this is the LLM encoded-tensor path with a token-input model, so it doesn't
contradict the empty-`prompt_ids` finding — that one lives in the embeddings branch of
the same `SequenceGroup` constructor, which fills `m_prompt_ids` from a separate optional
tensor the VLM path never passes.

What that run doesn't cover, so nobody reads more into it than it holds: only one
trailing token, so only budgets 0 and 1 could ever move and the overshoot case
(trailing > budget) stays unit-test-only; greedy decoding only; and nothing on the VLM
side — your B60 runs are still the evidence there.

**Tests for the new case.** You asked whether test data would be useful — here are
three, in the file's existing style:

```cpp
TEST(ThinkingBudgetTransformTest, TrailingCountReachingBudgetForcesAtConstruction) {
    // A continue_final_message-style prompt whose open <think> block already
    // carries the whole budget: the first generated token must be the forced
    // </think>, otherwise the block overshoots the budget by one token.
    TokenIds prompt{7, THINKING_START_ID, 1, 2};
    auto transform = ThinkingBudgetTransform(2, THINKING_START_ID, THINKING_END_ID, prompt);
    EXPECT_TRUE(thinking_transform_is_forcing(transform))
        << "trailing count == budget must force before the first generated token";

    transform.accept_token(THINKING_END_ID); // the forced </think> is sampled
    EXPECT_FALSE(thinking_transform_is_forcing(transform))
        << "the forced close must return the transform to passthrough";
}

TEST(ThinkingBudgetTransformTest, TrailingCountOverBudgetForcesAtConstruction) {
    // More trailing tokens than the budget allows: still forces immediately.
    TokenIds prompt{THINKING_START_ID, 1, 2, 4, 6};
    auto transform = ThinkingBudgetTransform(2, THINKING_START_ID, THINKING_END_ID, prompt);
    EXPECT_TRUE(thinking_transform_is_forcing(transform))
        << "trailing count > budget must still force immediately";
}

TEST(ThinkingBudgetTransformTest, UnlimitedBudgetIgnoresTrailingCount) {
    // The disabled budget must stay disabled no matter how long the open block is.
    TokenIds prompt{THINKING_START_ID, 1, 2, 4};
    auto transform = ThinkingBudgetTransform(-1, THINKING_START_ID, THINKING_END_ID, prompt);
    EXPECT_FALSE(thinking_transform_is_forcing(transform));
}
```

The first is the direct regression test for `4c0e8d6d`; the second is the overshoot
case. As a negative control I rebuilt with your five lines reverted: those two fail, the
other twelve stay green — so the first two pin this fix specifically rather than passing
everywhere. The third is a guard-rail rather than a regression test — it passes either
way by design, and just stops a later refactor from forcing at construction when the
budget is disabled.

Rewrite, rename or ignore any of them — your PR, your style. They're yours to take into
your own commit if you want them; I think a fix and its test read well landing together.
If you'd rather I push them to the branch, say the word.

One trap if you do add more cases: `THINKING_START_ID` and `THINKING_END_ID` are `3` and
`5`, which overlap the filler IDs the prompts use, so it's easy to write a prompt that
accidentally contains a think token and quietly tests something else. I did exactly that
on my first draft of the second test — `{THINKING_START_ID, 1, 2, 3, 4}` scans back to
the literal `3`. I went back and checked the eleven already on the branch are clean on
this; sticking to `1, 2, 4, 6, 7` as filler avoids it.

**Two doc nits, both non-blocking.**

1. The comment block above `ThinkingBudgetTransform` has drifted from the code: it says
   `last token is end_id → ... → IDLE` where the code sets `DONE`, says "last token"
   where the scan walks in reverse to the last *think-related* token, and doesn't mention
   the new immediate-`FORCING` case. The ASCII diagram just above it has the same drift —
   the re-arm arrow returns to `IDLE` while its own label says `DONE -> COUNTING`, and
   nothing ever goes back to `IDLE`. Might be worth refreshing while you're in there.

2. Reviving one of Copilot's from the first pass, since it never got picked up:
   `generation_config.hpp` says `enable_thinking=false` forces `</think>` "if end token
   ID is known", but `logit_processor.hpp` also requires `thinking_start_token_id >= 0`,
   so both IDs have to be known.

The Gemma result is a useful negative, and tracing it through the code it points at a
small asymmetry rather than a bug: with both IDs left at `-1`, `reasoning_budget_tokens`
trips the `validate()` assert and errors clearly, while `enable_thinking=False` passes
validation and then silently does nothing. Worth a docs line someday; nothing for here.

Agreed on keeping the scope tight and leaving the VLM non-chat path to the maintainers.
The three-model confirmation is a much stronger basis for that call than my single data
point was.

**One last FYI, purely mechanical:** every Actions run on this head except the labeler is
sitting at `action_required`. Fork PRs need a maintainer to approve the workflows before
they run, so Lint / Linux / Windows / macOS / Manylinux / SDL haven't actually executed
on any commit in this PR yet. Nothing for you to fix — just worth knowing that the
absence of a red X isn't the same as a green one.

---
*AI assistance disclosure: retest and review notes prepared with AI assistance (Claude);
all results are from real runs on the stated hardware and were human-reviewed before
posting.*

8< ---------------------------------------------------------------- 8<

## NOT FOR POSTING — notes

- Etiquette: author explicitly offered to write the test. Default is to HAND it over, not
  push. Blair already has one merged commit (f90cc875).
- Do NOT re-raise: `IDLE` re-arm ignoring `budget == 0` — verified UNREACHABLE.
- CUT from v1 and why:
  - "one of the things standing between this and a merge" — only Intel maintainers can
    act on it, so it was third-person commentary on their queue. Also incomplete:
    `mergeable_state` is `behind`, so the branch needs updating too.
  - "good call running it" — approving the author's process decisions on their own PR.
  - "for the reason that matters" — professorial; reads as grading a freshman.
  - "@apaniukov" ping — would have been the 9th on a thread where he's written zero prose
    comments, for a sentence needing nothing from him.
  - The C++-only auto-detect note (true — 3 sites, all in the Python bindings, zero
    `encode("<think>")` under `src/cpp/`) — dropped purely for volume. Hold in reserve.
- ADVERSARY WAS WRONG on one point: it claimed `LLMPipelineBackendRealModel` "almost
  certainly keys on something other than a cache-types CSV". It does not —
  `test_llm_pipeline_backend.cpp:56` and `test_cache_types.cpp:79` both read
  `CACHE_TYPES_CSV` in an identical `get_csv_params()`. Claim kept, wording made precise.
