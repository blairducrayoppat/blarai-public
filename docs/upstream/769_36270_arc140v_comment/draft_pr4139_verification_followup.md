# POSTED 2026-07-16 (LA go) → https://github.com/openvinotoolkit/openvino.genai/pull/4139#issuecomment-4999078156

> Substantive critical review findings (compile error + does-not-engage on the issue's
> model) — needs the operator's read before posting, unlike tonight's supporting note.
> Posts as a SECOND comment on PR #4139, from the operator's account.

---

Thanks for building this — it's the control this model family has been missing, and I
wanted to help move it forward, so I built the branch from source and put it on real
Xe2 hardware (Arc 140V / Lunar Lake) against the hardest target: the exact model the
linked issue is about, `OpenVINO/Qwen3.6-35B-A3B-int4-ov`. Sharing what I found so it
can feed the next iteration — and I'm happy to keep re-testing revisions of this branch
on this hardware/model as you go.

1. **Small build break on Windows/MSVC** — I've left an inline suggestion on the diff
   (the `OPENVINO_ASSERT` at `sampling/logit_processor.hpp:55` is missing its closing
   `);`, which MSVC reports as C1057 in every unit that includes the header). With that
   one character the wheel builds clean here (Ninja, openvino 2026.4 dev nightly), and
   all four new `GenerationConfig` fields come through the bindings as expected.

2. **A datapoint from the issue's model that may shape the design:** on this model +
   VLMPipeline text path, greedy, 220 new tokens, same prompt across conditions —
   `enable_thinking=false` alone, with explicit `thinking_start/end_token_id`
   (248068/248069, from the model's own tokenizer.json), and
   `reasoning_budget_tokens=32` with IDs — all produced output byte-identical to the
   default run (sha256-verified across the full 220-token outputs; visible untagged
   reasoning, no truncation). One thing the raw outputs show that may explain it: no
   `<think>` token ids (248068/248069) ever appear in the generated stream on this
   path — the reasoning text comes out untagged, and every probe of this IR here since
   early July shows the same. If the state machine keys on those ids, that would leave
   it nothing to trigger on; it's also possible the transform simply isn't reached
   from the VLMPipeline sampling path — I don't know the internals well enough to say
   which. Either way the practical effect on this model is no suppression, and since
   the Qwen3.6 model card documents the chat template's `enable_thinking` parameter as
   the family's supported control, reaching that (in addition to, or instead of,
   logit-level forcing) may be what this model needs. Your verified results on
   Qwen3-14B / 30B-MoE / DeepSeek are consistent with those paths tagging their
   thinking in-stream — so this may be a per-model-family difference rather than a
   flaw in the mechanism as such.

3. **One UX thought:** with the relaxed validation, `enable_thinking=false` without
   token ids is accepted and (on this model) has no effect — which lands users back in
   the accepted-but-ineffective behavior the original issue describes. If the ID-less
   form can't act, a loud error or warning might serve users better than silence.

Raw probe JSONs (both runs, all conditions) available if useful — and again, glad to
be a standing test bench for this branch on Arc 140V.

---

## Internal notes (strip before posting)

- Evidence: `docs/performance/probe_pr4139_enable_thinking_35b_2026-07-16_21-10-31.json`
  + `..._21-13-41.json`; PERFORMANCE_LOG 2026-07-16 (PR #4139 verification entry).
- Probe script copy: `docs/upstream/769_36270_arc140v_comment/probe_pr4139_35b.py`.
- Tone: constructive-reviewer register; every claim scoped to this model/path; the
  author's own verified models explicitly not contradicted.
