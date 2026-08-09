---
title: "P1-S4 draft — The crash we found and fixed upstream"
status: draft-v2-post-panel-disposition
area: research
piece: P1-S4
venue: home base (canonical long-form); HN link candidate after LA ceremony
author_session: P1 author dispatch, 2026-07-19
all_access_dates: 2026-07-19
---

# The crash we found and fixed upstream

*A field report: how an intermittent crash on one Lunar Lake laptop became a
merged fix in OpenVINO GenAI, with every number on the public record.*

---

On 2026-07-02, a local AI assistant running on a single laptop crashed once,
mid-answer. Six days later, the fix was merged into
[openvino.genai](https://github.com/openvinotoolkit/openvino.genai) — reviewed
and approved upstream, with a standalone reproducer, a matched before/after
verification (1 crash in 95 generations before; 0 in 95 after), and the full
measurement trail committed to a public repository.

This post is the story of those six days, told with the discipline of the
series it belongs to — a field-report corpus documenting one long-term local
AI build: exact numbers, stated conditions, and a plain account of what was
*not* proven. It is a documented single-project case study — one build,
one box, fully instrumented — not a controlled study, and not a general claim
about anyone else's workload.

- Issue: [openvinotoolkit/openvino.genai#4081](https://github.com/openvinotoolkit/openvino.genai/issues/4081) (filed 2026-07-05; closed as completed 2026-07-08)
- Fix: [openvinotoolkit/openvino.genai#4082](https://github.com/openvinotoolkit/openvino.genai/pull/4082) (merged to `master` 2026-07-08; **not yet in a tagged release as of 2026-07-19** — the latest release, 2026.2.1.0, predates the merge)
- Evidence: the [verification record (JSON)](https://github.com/blairducrayoppat/blarai-public/blob/main/docs/performance/xgrammar_stop_token_fix_verify_2026-07-05_15-34-27.json) and the [reproducer package](https://github.com/blairducrayoppat/blarai-public/tree/main/docs/upstream/725_xgrammar_stop_token) in the project's public mirror

## The crash

The system involved is a personal research project: a long-term, local AI
assistant on one Windows 11 laptop (Intel Core Ultra 7 258V "Lunar Lake", Arc
140V integrated GPU, 32 GB LPDDR5X). The inference stack is OpenVINO GenAI
running Qwen3-14B INT4 on the GPU with speculative decoding — a pruned
Qwen3-0.6B draft model proposes tokens, the 14B verifies them. The day before
the crash, the assistant's tool calling had moved onto a decoder-level grammar:
an xgrammar *triggered structural-tags* constraint, which leaves free text
untouched but, the moment the model emits `<tool_call>`, makes anything but
schema-valid JSON structurally impossible to generate.

Each feature had been tested on its own and in combination — an offline
composition probe on the same pipeline shape, then a clean live tool-calling
turn on the full 14B stack. Then, during a live session on 2026-07-02, one
generation aborted with an assertion from deep inside the vendored grammar
engine:

```
grammar_matcher.cc:627: Check failed: (!IsStopTokenAccepted()) is false:
GrammarMatcher has terminated after accepting the stop token, but is trying
to find the next token mask
```

The application's fail-closed error handling did its job — the turn was
discarded and the assistant answered again without the tool; nothing was
corrupted. But a generation-killing crash in the substrate is not something to
live with, and the same day the grammar constraint was switched off in
production pending a real diagnosis. Everything after that flip happened on the
same box, off the production path.

## Isolating the pair

The crash was intermittent — identical greedy re-runs crashed on different
prompts, and short runs were often clean, which is exactly the profile that
tempts you to shrug and move on. The alternative was elimination on real
silicon: a fixed generic prompt set, greedy decoding, grammar configured
throughout, toggling one variable per arm. Two of the table's entries — the
2/38 fraction and the no-grammar 0/19 row — came not from that deliberate
protocol but from parallel evaluation-harness runs that happened to hold the
right configurations; the issue publishes all of it together. The evidence
table, condensed from the issue:

| Configuration (same box, greedy decoding) | Crashes / generations |
|---|---|
| Speculative decoding ON, non-streamed | crashes every run — e.g. 1/76, 1/57, 2/38 (~1–5%) |
| Speculative decoding ON, streamed | 0/57 (small sample — see below) |
| Speculative decoding OFF (no draft model) | **0/57** |
| Grammar not attached at all | 0/19 |

The speculative-decoding-OFF row is the whole result: grammar plus draft model
crashes; remove the draft and it goes quiet with everything else identical.

Two further observations sharpened the picture beyond "tool calling is broken":

1. **The grammar never has to fire.** In 57 token-by-token captured
   generations, not one emitted the `<tool_call>` trigger — the constrained
   region never engaged — yet equivalent non-streamed runs still crashed. A
   *configured but un-fired* grammar, plus a draft model, plus end-of-sequence
   is sufficient.
2. **The offending token is whatever the draft guessed.** A companion non-fatal
   warning at the same site names the token being fed to the terminated
   matcher, and it was an ordinary word-piece (id `498`) as often as a grammar
   tag. The problem is not in the constrained content; it is positional —
   tokens *past the stop*.

Together these argue for reading the bug not as "tool-call grammar crash" but
— in the issue's own hedged words, what the failure "appears to be" — as
structured output under speculative decoding in general: a wider blast radius
than the first stack trace suggested.

One honesty note that survived into the upstream report verbatim: the streamed
arm's 0/57 *looks* like streaming avoids the bug, but the original production
crash **was** streamed. From the issue: "a real crash in my app *was* streamed,
so I do **not** claim streaming avoids this — likely undersampled." Handing a
maintainer a false "streaming is safe" claim would have been worse than handing
them nothing.

## A reproducer strangers can run

The characterization runs used the project's real pipeline; the filed
reproducer could not. The first draft embedded the production system prompt —
841 tokens of internal instructions — so it was rebuilt around a generic set
of 19 conversational prompts and a stock two-tool JSON schema (a clock lookup
and a note search), and re-run to confirm *that* still crashes; those 19
prompts are the unit behind every figure in the verification arms. The issue
additionally carries a self-contained inline script with its own 15-question
set and a single generic schema, so a reader needs nothing beyond the issue
text to try it. Neither artifact ships anything internal: any OpenVINO model
export plus any compatible draft export reproduces it.

Prior art mattered here too. The same failure signature — "GrammarMatcher has
terminated after accepting the stop token" — had appeared in the sglang
project and was fixed there in
[sgl-project/sglang#14464](https://github.com/sgl-project/sglang/pull/14464)
(merged 2025-12-06): same class of seam, grammar-constrained decoding under
speculative execution, resolved by not querying a terminated matcher. Citing
that in the issue handed the OpenVINO GenAI maintainers a proven direction
rather than just a symptom.

## Root cause: a guard one line too late

With the characterization pointing at the seam, reading the integration source
settled it quickly. In openvino.genai's `xgrammar_backend.cpp` (the bug is in
the integration layer, not in xgrammar itself):

```cpp
// BEFORE
void XGrammarLogitsTransformer::apply(Logits& logits) {
    m_grammar_matcher.FillNextTokenBitmask(m_token_bitmask.get());
    if (m_grammar_matcher.IsTerminated()) {
        return;
    }
    ...
```

`FillNextTokenBitmask()` runs *before* the `IsTerminated()` check — and
`FillNextTokenBitmask` is precisely the call that asserts
`!IsStopTokenAccepted()`. Without a draft model the mis-ordering never bites:
the matcher terminates on the final token and `apply()` is never called again.
With speculative decoding, the draft proposes tokens *past* the accepted stop,
so `apply()` runs once more on an already-terminated matcher, and the check
fires. The fix is to swap the two lines — check termination first, fill the
bitmask second — plus the equivalent guard in `accept_tokens()`, which also
silences the companion warning from the same root cause. Net diff: **+4/−1
lines in one file.**

That is the anticlimax at the center of this story, and it is worth stating
plainly: a day of controlled elimination bought a one-minute source read.
The isolation table is what turned "intermittent crash somewhere in a
14-billion-parameter stack" into "look at the order of two calls."

## Verifying a fix on a machine that couldn't run it where it broke

Proving the fix was harder than writing it, and the constraint is worth
documenting because it will be familiar to anyone verifying substrate patches
from the outside.

The obvious plan — rebuild the patched library, drop it into the installed
Python environment, re-run the crashing workload on the GPU — hit an
application-binary-interface (ABI) wall: the official Python extension module
is compiled against the exact release build, so a rebuilt DLL fails to load
against it. The fallback — rebuild the Python bindings from source too — moved
the same wall one layer down: the local from-source OpenVINO checkout had never
linked its GPU plugin at all.

The honest recalibration: this bug is a sampler state-machine ordering error.
It lives entirely in *when* a C++ guard is checked relative to a matcher call —
no GPU-specific numerics are involved — so we judged it device-independent,
and disclosed that judgment upstream as a judgment, not a fact. The
verification therefore ran as a same-commit before/after with one disclosed
substitution:

- **Rebuilt from source at `7dea045`** — the exact commit the installed,
  crashing wheel (`2026.2.1.0-3123-7dea0459b2a`) was built from. Before/after
  differ by the patch alone, not by version drift.
- **Baseline (unpatched, official wheel), GPU** — the originally affected
  device: **1 crash / 95 generations** (5 passes × 19 prompts), same case and
  same assertion as the original report.
- **Patched (rebuilt), CPU** via a standalone C++ reproducer mirroring the
  Python one — fully self-consistent, no ABI crossing: **0 crashes / 95
  generations**, truncated to the baseline's sample size (on which, below).
- **Control (patched, speculative decoding OFF):** 0/19 — the fix leaves the
  no-draft path alone.

Both the issue and the pull request state the device substitution and the
reasoning in full, rather than glossing it. One sizing judgment is also on the
record: the patched run was planned at 323 generations and truncated to 95 —
a time-budget call, plainly (CPU inference on a 14B model ran at roughly 53
seconds per generation), not a methodological strength.

That is the honest place to say what the numbers do and do not prove. At a
crash rate this low, 0/95 against 1/95 is a demonstration, not statistical
proof: at the ~1–2% rate measured on this prompt set, an *unfixed* build would
come up clean across 95 generations roughly 15–38% of the time by chance
alone, and for showing the absence of a rare event a larger patched arm is
more informative than a matched one. The proof in this story is the mechanism:
the reorder makes the asserting call unreachable on a terminated matcher — a
deterministic, code-level argument — and the 95-run before/after stands as a
regression check that the patched build behaves as that argument predicts,
with the control confirming the no-draft path is untouched.

What this verification is not: a GPU re-run of the patched build (not possible
in this environment at the time), or a performance measurement (none attempted
— the change is a branch reorder, with no expected throughput effect).

## Upstream, in the open

The issue and the pull request went up together on the evening of 2026-07-05 —
[#4081](https://github.com/openvinotoolkit/openvino.genai/issues/4081) five
minutes before [#4082](https://github.com/openvinotoolkit/openvino.genai/pull/4082).
The pull request is signed off under the Developer Certificate of Origin, and
both carry an explicit AI-assistance disclosure (this project is built with an AI development
fleet, and its upstream contributions say so; the observations and runs behind
the report are first-hand and were reproduced on the hardware described before
filing).

One framing choice in the issue is worth passing on. Nothing in the
documentation said structured output and speculative decoding were supported
*together*, so the issue asks, in so many words: if this combination simply
isn't supported yet, that's completely understandable — but then the failure
deserves a clear message rather than an internal assertion. Filing "your
feature pair crashes" as a question rather than a verdict costs nothing and
matches what an outside contributor actually knows.

The review itself was quick and ordinary in the best sense:

- **2026-07-05:** an automated reviewer flagged one nit — a code comment
  referencing a vendored file and line number, brittle across dependency
  updates.
- **2026-07-06:** the nit fixed in a follow-up commit; first approving review
  (apaniukov); CI triggered. One wheel test failed — a GGUF-reader job
  cancelled at its one-hour timeout while downloading a model. Triaged in a
  comment: unrelated infrastructure timeout, path untouched by the patch, no
  assertion failed.
- **2026-07-07:** the merge queue ejected the PR on a required-status error
  (two of eight platform builds, both Windows, had failed that morning);
  triaged in a second comment naming the exact failing statuses.
- **2026-07-08:** second approving review (pavel-esir); merged to `master` at
  13:07 UTC. The issue auto-closed as completed two seconds later.

Elapsed: about 62 hours from filing to merge; six calendar days from the first
live crash to the merged fix. The two triage comments are part of the story —
an outside contributor who investigates the red X on their own PR, names what
failed and why it is unrelated, is doing a small share of the maintainers' work
for them, and that is precisely the currency an unknown contributor has.

## Where it stands, and the discipline of waiting

As of 2026-07-19 (verified against the repository's tags and releases via the
GitHub API on that date): the fix is merged on `master` and **not yet in any
published release** — the newest release, 2026.2.1.0, was published 2026-06-17,
three weeks before the merge.

Which means the production posture on this box is unchanged: the grammar
constraint stays off. The re-enable criterion was written down the day the
crash happened and still governs: the fix ships in the pinned release, a
20-out-of-20 boundary-case soak passes on this machine, and one live
grammar-constrained tool turn succeeds. Merged upstream is a milestone, not a
deployment. (A from-source GPU plugin build completed on this machine on
2026-07-06 — after the CPU verification — so an independent GPU re-verification
of the patched build is now possible locally and is on the project's queue.)

## What this adds (prior work, honestly)

Fix write-ups are not rare; engine and vendor teams publish them regularly, and
the sglang project fixed this same failure class in its own engine first
([#14464](https://github.com/sgl-project/sglang/pull/14464), credited in our
issue as the precedent that suggested the direction). Published benchmarks on
this silicon exist too — Intel's first-party enablement posts, an Intel Labs
paper covering the same Core Ultra 258V/Arc 140V
([arXiv:2508.06753](https://arxiv.org/abs/2508.06753)), and practitioner
snapshots — and this piece is deliberately not one of them; there is no
throughput headline here.

Debugging narratives with the false leads left in are not rare either — the
genre's best-loved entries (the "500-mile email," Hector Martin's Go-runtime
hunt) are celebrated precisely for their dead ends and wrong guesses, so
narrative honesty is not what this piece claims to add. What it adds is
narrower, and in a written scan of the genre we could not find it done
end-to-end: the provenance chain as *committed, machine-readable artifacts*,
not only as story — a verification record in JSON, a sanitized reproducer and
its prompt set, and a matched-condition before/after dataset, all in a public
repository and cross-linked to the upstream issue and PR, so every number in
this post can be re-derived rather than taken on faith. In this project we
treat that chain as the product; the fix is almost incidental.

## Methods and environment

The environment, workload, and run figures below are recorded in the
[machine-readable verification record](https://github.com/blairducrayoppat/blarai-public/blob/main/docs/performance/xgrammar_stop_token_fix_verify_2026-07-05_15-34-27.json)
and the project's dated performance log
([PERFORMANCE_LOG.md](https://github.com/blairducrayoppat/blarai-public/blob/main/PERFORMANCE_LOG.md),
2026-07-05 entry), both written at the time the runs happened; the streaming
limitation below is recorded in the issue itself.

- **Hardware:** Intel Core Ultra 7 258V (Lunar Lake); Intel Arc 140V integrated
  GPU (Xe2), driver 32.0.101.8826; 32 GB LPDDR5X. Windows 11 Pro (build 26200).
- **Software:** OpenVINO GenAI 2026.2.1.0-3123-7dea0459b2a (win_amd64, cp311
  wheel) as the crashing baseline; patched build compiled from source at the
  same commit (`7dea045`, `releases/2026/2`). Python 3.11.9. xgrammar as
  vendored in the GenAI build.
- **Models:** target Qwen3-14B, OpenVINO INT4; draft Qwen3-0.6B (pruned,
  6-layer), INT8; `num_assistant_tokens=3` when the draft is attached.
- **Workload:** triggered structural-tags grammar (trigger `<tool_call>`,
  JSON-schema body), greedy decoding (`do_sample=false`),
  `max_new_tokens=512`; 19 generic conversational prompts
  ([public](https://github.com/blairducrayoppat/blarai-public/blob/main/docs/upstream/725_xgrammar_stop_token/repro_prompts_generic.json)),
  none of which requires a tool call. The before/after verification arms ran 5
  passes each = 95 generations per arm; the earlier isolation runs used
  varying pass counts (the fractions shown in the evidence table).
- **Reproducers:** Python
  ([xgrammar_standalone_repro.py](https://github.com/blairducrayoppat/blarai-public/blob/main/docs/upstream/725_xgrammar_stop_token/xgrammar_standalone_repro.py))
  and a mirroring standalone C++ sample used for the patched-build runs.

**What was not measured.** The patched build was not run on GPU (no local GPU
plugin build existed at verification time; the GPU baseline is the unpatched
official wheel). No throughput or latency deltas from the fix were measured
(expected zero — a branch reorder — but expected is not measured). The crash
rate was not characterized beyond 95 generations per arm; 0/95 versus 1/95 at
matched sample size proves the comparison that matters here, not a precise
underlying rate. The streamed configuration remains undersampled (0/57 against
one known streamed crash in production). All figures are from this one machine
and these exact versions; on different hardware, versions, or workloads the
rate — though not, we believe, the mechanism — may differ.

---

*This piece was drafted with the AI development fleet it describes, working
from the project's build journal, decision records, and measured performance
logs; the human author directed, reviewed, and approved every claim.*

*This piece is part of a series documenting a long-term local AI system on
Lunar Lake hardware as a single-project field corpus: everything dated,
conditioned, and checkable against the
[public dataset](https://github.com/blairducrayoppat/blarai-public/tree/main/docs/performance).*
