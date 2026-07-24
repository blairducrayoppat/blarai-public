# POSTED 2026-07-16 (LA-directed) → https://github.com/openvinotoolkit/openvino.genai/pull/4139#issuecomment-4998838041

> Short by design: a supporting datapoint for the PR reviewers, not a review.
> Post from the operator's account (blairducrayoppat) right after the #3937
> companion comment lands, so the cross-reference resolves.

---

Supporting datapoint for this PR's premise, from the #3937 side.

We probed the same control surface on Qwen3.6-35B-A3B INT4 (Arc 140V / Lunar Lake,
GenAI 2026.2.1 vs llama.cpp b9957, greedy, same prompt): under GenAI,
`generate(enable_thinking=False)` is accepted without error and has no effect, and
`GenerationConfig` exposes no thinking field; under llama.cpp, the equivalent
template-level switch (`chat_template_kwargs: {"enable_thinking": false}`) cleanly
disables thinking with a coherent answer. The Qwen3.6 model card documents the old
`/think`–`/nothink` soft switches as unsupported and names the template parameter as the
intended control — so a first-class `enable_thinking` in `GenerationConfig`, as this PR
adds, looks like exactly the missing piece. Detailed writeup in the #3937 thread
(comment linked there); raw probe JSON available if useful.

---

## Internal notes (strip before posting)

- Sequence: post the #3937 companion FIRST, then this — the "comment linked there"
  reference assumes it exists.
- Evidence: probe_thinking_toggle_llamaserver_2026-07-16_19-39-33.json +
  qwen36_27b_thinking_toggle_probe_2026-07-08.json.
- LA approval (in-chat 2026-07-16): "I approve a short supporting comment on PR #4139
  itself. proceed with that at the appropriate time." Posting itself remains from the
  operator's account per the session's opening instruction ("the upstream posts are
  mine to send").
