# DRAFT (SHORT, voice-matched) — PR #4139 review at 4c0e8d6d. COMMENT review. Blair posts. NOT posted.

Target: https://github.com/openvinotoolkit/openvino.genai/pull/4139
Voice calibrated against Blair's actual posts (4998838041, 5054376503, 5060021475):
substance-first opener, measurements stated flatly, exact token IDs / indices, hedges
attached to interpretation only, warm specific close. Deference = precise scoping, NOT
vagueness. Credit NOT mentioned (tests-as-commit is the path). Gemma/doc-nits/CI dropped.
Numbers in sibling VERIFICATION.md + DEVICE-PROBE-before-after.md.

8< ---------------------------------------------------------------- 8<

Re-tested `4c0e8d6d` on Arc 140V (Lunar Lake), this time end-to-end on real weights
before/after the fix so the effect is isolated: Qwen3-14B INT4, LLMPipeline on GPU, greedy,
both wheels built from source from this branch with and without the five lines.

The new constructor check reads as sound to me — it uses the same predicate as the
`COUNTING` branch of `accept_token`, so the budget boundary comes out the same whether it's
reached by trailing prompt tokens or generated ones. I'm still finding my way around this
part of the sampler, though, so please take that as a reading rather than a verdict —
corrections very welcome.

Behaviorally, on a prompt ending in an open `<think>\n` (17 tokens; `<think>` = 151667 at
index 15, one trailing token after it): with `reasoning_budget_tokens=1`, the parent build
emits one reasoning token (`Okay`, 32313) before forcing `</think>` (151668), and
`4c0e8d6d` forces immediately — matching `budget=0`. Budgets 2/3/-1 come out byte-identical
across both builds (full ID-sequence equality). Only the five lines differ between the two
wheels, so the change is isolated.

Three small tests if they're useful, in the file's existing style — the first two are red
on the parent and green at `4c0e8d6d`, the third just guards the disabled-budget case:

```cpp
TEST(ThinkingBudgetTransformTest, TrailingCountReachingBudgetForcesAtConstruction) {
    // Open <think> block whose trailing prompt tokens already reach the budget:
    // the first generated token should be the forced </think>, no overshoot.
    TokenIds prompt{7, THINKING_START_ID, 1, 2};
    auto transform = ThinkingBudgetTransform(2, THINKING_START_ID, THINKING_END_ID, prompt);
    EXPECT_TRUE(thinking_transform_is_forcing(transform));

    transform.accept_token(THINKING_END_ID); // the forced </think> is sampled
    EXPECT_FALSE(thinking_transform_is_forcing(transform));
}

TEST(ThinkingBudgetTransformTest, TrailingCountOverBudgetForcesAtConstruction) {
    TokenIds prompt{THINKING_START_ID, 1, 2, 4, 6};
    auto transform = ThinkingBudgetTransform(2, THINKING_START_ID, THINKING_END_ID, prompt);
    EXPECT_TRUE(thinking_transform_is_forcing(transform));
}

TEST(ThinkingBudgetTransformTest, UnlimitedBudgetIgnoresTrailingCount) {
    TokenIds prompt{THINKING_START_ID, 1, 2, 4};
    auto transform = ThinkingBudgetTransform(-1, THINKING_START_ID, THINKING_END_ID, prompt);
    EXPECT_FALSE(thinking_transform_is_forcing(transform));
}
```

Yours to take into a commit, rework, or ignore — your PR and your call on style. Happy to
push them to the branch or just leave them here, whatever's easiest. Nice work turning the
edge case around so quickly.

---
*AI assistance disclosure: retest and tests prepared with AI assistance (Claude); all
results are from real runs on the stated hardware and were human-reviewed before posting.*

8< ---------------------------------------------------------------- 8<
