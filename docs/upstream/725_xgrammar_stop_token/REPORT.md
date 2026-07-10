# xgrammar `IsStopTokenAccepted` crash under speculative decoding (OpenVINO GenAI)

**Status:** ready to file at `openvinotoolkit/openvino.genai` (search first — see §8).
**Local tracking:** BlarAI Vikunja #725.
**Prepared:** 2026-07-04 (evidence runs), this repo `docs/upstream/725_xgrammar_stop_token/`.

---

## 1. Summary

When a **triggered structural-tags (xgrammar) grammar** is attached to a
`GenerationConfig` and the pipeline runs with **speculative decoding** (a
`draft_model`), generation intermittently aborts at end-of-sequence with:

```
grammar_matcher.cc:627: Check failed: (!IsStopTokenAccepted()) is false:
GrammarMatcher has terminated after accepting the stop token, but is trying
to find the next token mask
```

The generation raises (fail-closed in our app; the turn is discarded). It is
**intermittent** (~2–5% of generations on our workload) and
**nondeterministic across identical greedy runs** — a different prompt
crashes each time.

It **disappears** when speculative decoding is removed (draft model detached),
with the grammar and everything else unchanged. That is the load-bearing
control result below.

## 2. Root-cause hypothesis (supported by the evidence)

The xgrammar `GrammarMatcher` accepts the stop token and **terminates**. The
speculative-decoding path then asks the terminated matcher for the next-token
mask (to validate/mask the **draft model's proposed tokens past the stop
position**), tripping the `!IsStopTokenAccepted()` assertion.

Two observations point at the draft proposals specifically, not the grammar
body:

- A companion warning fires at `grammar_matcher.cc:493` feeding the terminated
  matcher **ordinary vocabulary token ids** (observed `498`, and separately
  `151658` = `</tool_call>`) — i.e. whatever the draft proposed after the stop,
  not a token the constrained region required.
- In 57 streamed generations that we captured token-by-token, **none emitted
  the `<tool_call>` trigger in the output text** — the grammar body never
  actually engaged — yet the crash still occurred in the equivalent
  non-streamed runs. So the trigger firing is **not** a precondition; a
  configured (but un-triggered) grammar plus a draft model plus end-of-sequence
  is enough.

This matches a **previously-fixed bug of the same shape in sglang**
(`sgl-project/sglang` #14464, merged 2025-12-06): "GrammarMatcher has
terminated after accepting the stop token" when speculative decoding +
grammar were combined; their fix implemented `is_terminated` so the terminated
matcher is not queried. (Also related: sglang #15050 grammar × EagleWorker,
#14462 spec-decode guided-decoding data race.) OpenVINO GenAI vendors xgrammar
(`_deps/xgrammar-src` in the build path) and drives it from its own
continuous-batching speculative path, so the same class of guard is likely
needed on the OV side of the matcher call.

## 3. Environment

| | |
|---|---|
| OpenVINO GenAI | `2026.2.1.0-3123-7dea0459b2a` (win_amd64 cp311 wheel) |
| OpenVINO | `2026.2.1-21919-ede283a88e3-releases/2026/2` |
| xgrammar | vendored in the GenAI build (`_deps/xgrammar-src`, private-ci vs2022 job) |
| Python | 3.11.9 |
| OS | Windows 11 Pro (build 26200) |
| CPU | Intel Core Ultra 7 258V (Lunar Lake) |
| GPU | Intel Arc 140V (Xe2 integrated), driver **32.0.101.8826** |
| Target model | Qwen3-14B, OpenVINO INT4, device GPU |
| Draft model | Qwen3-0.6B (pruned 6-layer) INT8, device GPU, `num_assistant_tokens=3` |
| Decode | greedy (`do_sample=False`), `max_new_tokens=512`, prefix caching ON |
| Structured output | `StructuredOutputConfig` + `StructuralTagsConfig`, one triggered tag (trigger `<tool_call>`), body a small JSON-schema union, end `</tool_call>` |

## 4. Verbatim error

```
Generation error — Fail-Closed: grammar_matcher.cc:627: Check failed:
(!IsStopTokenAccepted()) is false: GrammarMatcher has terminated after
accepting the stop token, but is trying to find the next token mask
```
Companion warning (non-fatal, same root):
```
grammar_matcher.cc:493: Warning: The matcher has terminated after accepting
the stop token, but is trying to accept new token with id 498.
```

## 5. Evidence table (all: same box, same 19 prompts, greedy, grammar configured)

| Configuration | Crashes / generations | Rate |
|---|---|---|
| Speculative decoding ON, **non-streamed** | crashes in every configuration: sanitized-standalone **1/76**, project-standalone 1/57, app-probe 1/57, first app eval runs 2/38 | ~1.3–5% |
| Speculative decoding ON, **streamed** | 0 / 57 | 0% (small-N; production's live crash *was* streamed, so streaming is not protective — likely undersampled) |
| **Speculative decoding OFF** (no draft), non-streamed | **0 / 57** | **0%** — the control |
| Grammar OFF (our shipped production posture) | 0 / 19 | 0% |

The **spec-decode-OFF = 0 crashes** row against **spec-decode-ON = crashes**,
grammar identical, is the isolation result.

## 6. Minimal standalone reproduction

`xgrammar_standalone_repro.py` in this directory — **OpenVINO GenAI only, no
application code**. It builds an `LLMPipeline` on GPU with a `draft_model`, a
triggered `StructuralTagsConfig`, and runs greedy over the prompt set. It
reproduced the crash with a **fully generic prompt set + generic 2-tool schema
+ stock system prompt** (`repro_prompts_generic.json`, also here — nothing
project-specific), so the report ships no internal content.

```
python xgrammar_standalone_repro.py \
  --model <qwen3-14b-int4-ov-dir> \
  --draft <qwen3-0.6b-int8-ov-dir> \
  --prompts repro_prompts_generic.json --passes 5
# crashes ~1 in 20-60 generations; re-run if a short pass is clean (intermittent)

# control — crash disappears:
python xgrammar_standalone_repro.py \
  --model <qwen3-14b-int4-ov-dir> \
  --draft <qwen3-0.6b-int8-ov-dir> \
  --prompts repro_prompts_generic.json --no-draft --passes 5
```

Qwen3-14B-INT4 + Qwen3-0.6B-INT8 are the public OpenVINO exports; any
target+draft pair on GPU should serve (the crash is at the matcher/spec-decode
seam, not model-specific). If a reproducer with two small public models is
preferred for the issue, that substitution is the only change needed.

## 7. Workaround in place

`[generation].tool_call_grammar = false` (grammar disabled); parse-time strict
JSON-schema validation is the guard instead. Zero crashes since. We re-enable
only when: an upstream fix ships in the pinned GenAI version, the repro passes
a 20/20 boundary soak, and one live tool turn succeeds.

## 8. Before filing (owner: operator, upstream contributor)

1. **Search existing issues** at `openvinotoolkit/openvino.genai` for
   `IsStopTokenAccepted` / `grammar_matcher.cc:627` / "terminated after
   accepting the stop token" (we found none as of 2026-07-04; one xgrammar PR
   #2295 is the *feature*, not this bug). Add to an existing thread if present.
2. Consider CC/linking the sglang precedent (#14464) as the same-shape fix in a
   sibling runtime — it hands the maintainers a proven direction.
3. Attach `xgrammar_standalone_repro.py` + `repro_prompts_generic.json`; paste
   §3 env + §4 verbatim error + §5 table.
4. Title suggestion: *"xgrammar structured output crashes at EOS under
   speculative decoding: GrammarMatcher terminated after stop token
   (grammar_matcher.cc:627)"*.

## 9. Open threads we did NOT fully close (state them honestly in the issue)

- **Streamed 0/57 vs non-streamed 3/~150** is small-N; we do **not** claim
  streaming avoids the bug (production's real crash was streamed). Likely
  sampling noise; flag as unmeasured rather than a finding.
- We did not bisect GenAI versions (only 2026.2.1 tested).
- We did not test a CPU-only pipeline (GPU target + GPU draft throughout).
