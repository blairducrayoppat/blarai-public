# Disposition — independent review of the §6.1 upstream draft (a3946c58)

**Review:** `docs/reviews/upstream-review-930-genai-draft-2026-09-22.md`, independent session, did
not author the draft. Verdict: **not postable**.
**Author of the draft and of this disposition:** this session.
**Outcome:** the draft is WITHDRAWN. The experiment the review forced disproved its premise.

The review's central finding was that the draft's headline contradicted our own same-day probe.
Chasing that contradiction produced the datamark confound, which dissolved the issue entirely. Nine
of eleven findings are fixed or moot as a result; two are deferred with predicates.

```disposition
F1 the headline claim "the same pipeline, in one process, without reloading, gives different results run to run" is contradicted at the byte level by probe_35b_greedy_determinism_2026-09-22_04-13-38.json, which shows calls 2-4 byte-identical on a repeated prompt and the whole sequence identical across loads | FIXED | docs/performance/datamark_confound_2026-09-22_20-42-44.json - the contradiction was real and chasing it found the cause. context_manager._generate_data_marker() mints a fresh secrets.token_hex(4) per add_grounded_context call, so every grounded case received a DIFFERENT prompt each repeat. Pinning the marker: both brains byte-identical across three runs, zero case disagreement. The claim is withdrawn, not reworded
F2 the ask leads with ag-inject-01, the one case prefix caching explains - it was pass/pass/pass with caching OFF, while the draft simultaneously claimed caching was "ruled out" | FIXED | docs/reviews/qwen36-35b-production-readiness-2026-09-22.md - the ask no longer exists; the issue is withdrawn. The reviewer was right on both halves: at n=3 per arm neither "ruled out" nor "relocates like randomness" was established, and leading with that case was indefensible
F3 "30-case suite" counts 10 ag-det-* cases that are mode:offline and scripted - the model never runs for them, so the 14B's perfect score is partly cases that cannot vary | FIXED | docs/performance/datamark_confound_2026-09-22_20-42-44.json + PERFORMANCE_LOG.md - every measurement since reports the 20 MODEL-DRIVEN cases and excludes ag-det-* explicitly; the readiness doc and PERFORMANCE_LOG carry 20, with the earlier 30 shown as retracted
F4 no byte-level evidence exists to share - "per-case records" means pass/fail rows, with no rendered-prompt or output hashes, so input identity was inferred rather than measured (standing rule: a direct check exists, do not reason from a proxy) | FIXED | docs/performance/datamark_confound_2026-09-22_20-42-44.json records sha256 of every call's input and output, per call per repeat. It is what turned the assumption into the measurement that refuted the draft
F5 #4476 not addressed - @apaniukov's KV_CACHE_PRECISION / KEY_CACHE_QUANT_MODE / DYNAMIC_QUANTIZATION_GROUP_SIZE knobs are the likely first triage reply and take one GPU session to test | FIXED | docs/reviews/qwen36-35b-production-readiness-2026-09-22.md - moot, and recorded as such rather than silently dropped. The arm was built (scratchpad/probe_state_vs_random.py arm C) but never needed: with the datamark pinned there is no instability left for the knobs to explain. If the reproducibility question ever returns, that arm is written and ready
F6 setup does not meet community grade - missing GPU driver version, exact export id, KV-cache and scheduler config, and which of the two installed runtimes ran | FIXED | docs/reviews/qwen36-35b-production-readiness-2026-09-22.md §6.2 - the surviving report carries OpenVINO 2026.2.1-21919 and GenAI 2026.2.1.0-3123 read from the probe's own record rather than from memory. The withdrawn issue needs no setup block
F7 no "What I checked" paragraph - needs the supported-model listing at the release tag, their test coverage, #4367/#4476, and a known-issues check | FIXED | docs/reviews/qwen36-35b-production-readiness-2026-09-22.md §6.1 - moot for the withdrawn issue. The prior-art work it asked for was done and is what made the withdrawal correct rather than lucky: #4367 gave the bit-exactness position, marfrit's ocl::gated_delta_net::ref mechanism, and #4476 gave the precision knobs
F8 the ask over-generalises - "this class of model cannot sit behind the policy gate at all" follows from a plugin-wide statement that covers the 14B too, so a maintainer would apply the same reading to the brain we ship | FIXED | docs/reviews/qwen36-35b-production-readiness-2026-09-22.md §2(b) - the readiness statement now scopes the claim to what was measured: the candidate's SENSITIVITY to an input perturbation the incumbent tolerates. No claim is made about the plugin
F9 sequencing - the same account would be filing about this model family while its 2026-07-09 comment on #3937 stands uncorrected, recorded in the journal as API misuse | DEFERRED | blocked-by: #1630 - the correction is drafted there and must post BEFORE any new issue on this model family. Unblocked by anything external; it is an operator go/no-go on text under his name, which is why it is a ticket and not a silent to-do
F10 attribution - the readiness doc says "Intel has already said"; @diego-villalobos is author_association NONE on #4367 and should be described as the triager, and marfrit pinned his mechanism to ocl::gated_delta_net::ref | FIXED | docs/reviews/qwen36-35b-production-readiness-2026-09-22.md - VERIFIED by grep: the strings 'Intel has already said' and 'diego-villalobos' no longer appear anywhere in the document, so the attribution defect is absent rather than reworded. The §6.1 withdrawal note names the reviewer's catch rather than restating the quote
F11 AI-assistance disclosure - genai has no CONTRIBUTING.md; the workstream precedent (PR_34617_DESCRIPTION_PASTE.md) discloses, the draft did not | DEFERRED | blocked-by: #1630 - carried to the §6.2 cold-start report, which is the only thing now proposed for posting, and decided together with F9 as one operator decision rather than two
```

## Findings the review returned CLEAN (recorded so a later pass does not re-litigate them)

- The @diego-villalobos quote is verbatim and correctly dated (2026-09-04).
- #4367's two arms were each bit-stable across restarts; our claim about that thread was accurate.
- marfrit's two-tokens-in-one-call mechanism is real and he pinned it to `ocl::gated_delta_net::ref`.
- Qwen3.6-35B-A3B is listed as supported at tag `2026.2.1.0`, and their `test_vlm_pipeline.py` at
  that tag covers only `tiny-random-qwen3.5` with no GPU case.
- The engagement shape — an issue asking a question rather than asserting a defect — was right. It
  is simply no longer needed for this.

## What this cost, and what caught it

Four rounds of measurement, three published claims, and a draft taken to 284 words and reviewed for
register before anyone ran the experiment that could refute it. The order was wrong: the refutation
experiment is cheap and should have come first.

Two things caught it. The reviewer noticed the draft contradicted a file we had banked ourselves
sixteen hours earlier. And the instrument built to chase that contradiction was itself vacuous on
its first run — its closure captured the repeat index once, so every call was tagged repeat 0 and
"inputs identical" was true over a single group. It now refuses to compute an identity claim from
fewer than two observed repeats.

Nothing was posted publicly at any point.
