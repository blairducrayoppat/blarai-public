### 2026-10-04 — Three silent ways the measuring setup lied before the small model and the big one could be compared

*Plain summary: I measured the small Qwen3.5-4B model with its built-in "guess ahead" head against the 14B
that ships. The result is a strong speed and memory win and a Policy Agent regression. But the interesting
part is that three separate faults in my own measuring setup each produced a clean, plausible, wrong
answer, and two of them were found only because an independent reviewer ran the code instead of reading
it.*

The question (#1663) was whether Qwen3.5-4B INT8 with Multi-Token Prediction could be the shared brain.
I had a reviewed plan and a "go". What I did not have was an instrument, because the only thing the
harness could do with a multimodal checkpoint was load it through `VLMPipeline`, which cannot use the
guess-ahead head and which the Policy Agent suite deliberately skipped (13 of its 35 cases silently
unevaluated, the pattern where "checked and clean" is indistinguishable from "could not check"). I built
an engine arm (`de0d2b72`) that wraps a `ContinuousBatchingPipeline` in exactly the surface the real
`PolicyGPUInference` and `OrchestratorGPUInference` already attach to, so every suite drives production
code rather than a re-implementation. The first honest number it gave was 114 of 123 draft tokens
accepted and not one `<think>` first token.

The first fault was the machine. The speed benchmark came back with decode speed varying twofold between
cells inside one process, and not with context length: a short multi-turn prompt decoded slower than an
838-token one. I did not argue about it; I ran the same prompt thirty times in a row. It went from 48 ms
per token to about 160, as the thermal zone climbed from 77 to 96 C, and a fresh process started hot
started slow. A rest of 20 to 60 seconds fixed it. Any A/B run back to back would have measured which arm
went first. I rejected the cheap repair (a fixed cool-down between arms) because the faster arm also
finishes sooner and therefore heats less, so even a perfectly interleaved plateau comparison favours it.
The campaign instead cools to 72 C before every generation, records thermal state on every row, and keeps
the two protocols apart. I pre-registered the minimum detectable effect on the ticket before the campaign
ran, then put the limits where I could see them: 5 percent for decode, 30 percent for first-token delay,
refuse any ratio whose arm varies by more than 15 percent.

The second and third faults I did not find; the reviewer did, by running my analysis against the raw
files. The 14B's runtime label was `14b-ship@2026.2.1.0` and the ratio table looked for
`14b-ship@2026.2.1`, and the code skipped any pair it could not form without saying so, so the three
comparisons the ticket exists for were never computed and the summary looked complete. And the V1
perturbation, one trailing space, the exact test that disqualified the 35B, changed 0 of 23 conversation
prompts for the 4B, because its chat template trims every message body; my analysis printed "no verdict
flipped" over a test that had touched nothing. The 14B's template does not trim, so the comparison was
asymmetric too. Both are fixed (`cd8572e5`): pairs that cannot be formed are reported, the analysis counts
prompts actually changed and refuses to read zero flips over zero changes, and V3 (a space before the final
punctuation mark) survives the trim. The V3 result is the one I did not expect. The 14B, the incumbent, flipped
5 of 22 conversation cases under a harmless one-space change; the 4B flipped none. I had assumed the fragility
that disqualified the 35B was the candidate's property. Here it is the incumbent's.

The result itself: with MTP the 4B decodes 1.5 to 3.5 times faster than the shipping 14B on about half the
memory (+9.7 GB against +17.4 GB), ~~the guess-ahead head changes no byte of output in any check I ran~~ [retracted 2026-10-04, see the end of this fragment], and
the price is that it needs prefix caching off, so at turn 6 of a conversation it waits 2.3 times as long
for its first token. On quality the 4B misses two Policy Agent cases the 14B passes, both expected DENY
answered ALLOW, ~~byte-identical in three of three runs~~ [reworded 2026-10-04: parsed label and confidence identical in three of three runs; the raw text was not compared across runs]. ~~That is a security-posture difference and goes to
the LA, not into a flag. I could not say why the 4B misses them, and I did not try to find out: INT4 and
the 9B are Phase 3.~~ [framing retracted 2026-10-04, see the second retraction at the end of this fragment]

Trade-offs I took and would take again: I spent about twenty minutes of GPU time on instrument variance before any
comparison, and I stopped a quality campaign two minutes in to run speed first while the box was fresh from
its reboot. Trade-offs I would not repeat: the first pre-registration comment on the ticket carries a
timestamp I estimated instead of reading (05:46 against a clock of 05:43), and the second carries 07:20
against 07:16. Both are corrected where they were made.

Lessons proposed, not numbered: (1) an analysis that skips what it cannot compute is a silent failure;
every expected pair must appear as a result or as a named absence. (2) A perturbation is only a perturbation
if it reaches the model; count the prompts that changed, not the verdicts that did not. (3) On a thermally
limited laptop the heat history is a variable, and an interleaved order does not remove it when one arm
finishes faster than another.

The merge itself then broke the gate that both parents had passed, the same way the 2026-09-16 merge did:
`test_roadmap_is_not_stale` measures the roadmap's refresh date against the `main` ref, so it was green on my
branch (main was still dated 2026-09-23) and red the moment the merge advanced main to 2026-10-04, 18 days past
a stamp of 2026-09-16. I had already caught its sibling, the sprint-pointer test, because it reads HEAD; I had
not noticed that this one reads a different ref. The fix was the documented one, not a date bump: run
`scripts/verify_roadmap.py` against the live board (21 of 21 rows open), say in the file what that did and did
not re-measure, and stamp it. A lesson I propose, not numbered: a freshness gate anchored to a ref other than
HEAD cannot be tested on the branch; predict it before the merge by computing the lag against the date the
merged ref will have.

**Next:** the LA decides whether anything about the Policy Agent gap warrants more work (Phase 3, #1665: the
9B and INT4 of the 4B). #1664 (coder offload) is unblocked.

**Retraction (2026-10-04, independent review of #1665, finding F2).** The struck sentence above is wrong. The comparison behind it looked at one run (V0 run 1) and I read its `identical: true` as covering every check. Recomputed 2026-10-04 over every pinned run that both the MTP-on and MTP-off arms have (agentic and conversation, V0 repeats 1 to 3 and the V1, V2 and V3 perturbations: 12 runs, 377 model calls): the prompts were identical in all 377 calls, and the outputs were identical in 376 and DIFFERENT in 1 (agentic V3 run 1, call 17 of 40: 448 characters with MTP, 442 without; the two outputs share their first 402 characters). The first figure checked V0 run 1 only (63 calls). Not investigated: why that call differs. The lesson is the one this entry is about, applied to my own instrument: a comparison that can only see one run will say identical, and I reported it before asking what else the comparison could have seen.

**Second retraction (2026-10-04, Policy Agent variant probe, #1665; evidence
`docs/performance/qwen35_small_9b_2026-10-04/raw/pa_variants/`, probe commit `81fd40b4`).** The struck sentences
about the two Policy Agent cases ("a security-posture difference"; "I could not say why") are corrected. The
33 of 35 and the same two cases stand (the "byte-identical runs" wording is corrected: parsed label and confidence identical in 3 of 3 runs; raw text not compared across runs). The cause: in `pa-mdl-007` and `pa-mdl-013` the
dangerous text is in a `command` field that the Policy Agent's schema check rejects, so the prompt carries
`[SCHEMA_REJECTED: Disallowed schema key: command]` and no model is shown the command (a prompt with the command
replaced by `echo ok` is byte-identical on all 13 cases for the 4B, the 9B and the 14B). With the command made
visible the 4B DENYs both; on the evaluation prompt the 14B DENYs because of the marker, so its 35 of 35 on these
two cases is not evidence of understanding. The lesson is about my own habit: I reported a model "miss" and a
posture difference from a pass-or-fail count without reading what the model was actually shown; the prompt was one
`format_car` call away. ~~Not checked: whether real requests carry commands under rejected fields.~~ **Checked from the
code 2026-10-04 (round-2 review G1; static evidence, no runtime trace):** live tool calls carry their arguments under
the rejected key `args`, and no production path was found that sends a request to the model-backed classifier, so the
14B's reaction to the marker is not shown to be the live path; do not build a deterministic DENY on schema rejection
before the live request shapes are traced (see the 9B fragment and verdict).
