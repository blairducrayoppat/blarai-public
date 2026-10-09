---
title: What OpenVINO 2026.3 and 2026.3.1 give us
status: research
area: substrate
date: 2026-08-29
author: claude-code session (interactive)
---

# What the two new OpenVINO releases give us

**Plain summary: your own bug fix shipped in this release, and it unblocks a security
control we switched off in July. That is the headline. Two further things are worth real
work — a faster way of generating text that Intel happened to measure on our exact
graphics chip, and a memory feature that attacks the limit which has been keeping larger
models out. Nothing here changes the model we run, and nothing needs a network door.**

Two releases landed since our current version: **2026.3.0** on 4 August (the major one)
and **2026.3.1** on 26 August (the patch). We run **2026.2.1**, from 17 June. This
report says what is genuinely new *for this project* — not what is new in general.

Every claim below was checked against the actual artifact: the release bodies through
the GitHub Application Programming Interface (API), the package index for what is
actually installable, and our own source tree for what we actually call. Where I could
not establish something, I say so rather than filling the gap.

---

## 1. The headline: your fix is in, and it reopens a door we closed

**In OpenVINO GenAI 2026.3.0.0, published 5 August, is this line:**

> *Fix xgrammar structured-output crash at EOS under speculative decoding by
> @blairducrayoppat in .../pull/4082*

and, in the new-contributors section of the same release:

> *@blairducrayoppat made their first contribution in .../pull/4082*

The pull request merged on 8 July, merged by the Intel maintainer `apaniukov`. This is
the fix from ticket #725 — the crash you hit live on 2 July during the web-search
go-live ceremony.

**Why this matters more than a credit line.** That crash is the *sole* reason a security
control has been switched off for eight weeks. In
`services/assistant_orchestrator/config/default.toml:68` we carry
`tool_call_grammar = false`. With that flag on, when the assistant tries to call a tool,
the decoder is physically constrained so that a malformed or unknown tool call is
*impossible to produce* — not caught afterwards, but unable to be generated in the first
place. With it off, we fall back to checking the tool call after the model has written
it. That check is sound and fails closed, so we are not exposed. But the design calls
for two independent locks there and we have been running on one.

**Ticket #725 states its own re-enable condition:** *"upstream fix released in the
pinned GenAI version AND the repro script passes 20/20 boundary-case runs on this box
AND one live tool turn."* The first of those three is now satisfiable. It has been since
5 August, and nobody noticed — the ticket's newest note still reads *"The upstream PR
isn't merged/released yet."* I have corrected that on the ticket.

**The scope is wider than the ticket title suggests.** #725's own investigation
(comment of 5 July) established that the crash needed only a *configured* grammar plus a
draft model plus an end-of-sequence token — the tool-call trigger never had to fire. So
this also touched the whole-response schema path (#845 C3) and plan emission (#743). The
recorded damage was real: per the code's own docstring, the planning call hit this crash,
returned an empty string, and **silently degraded every multi-task plan to the
single-task fallback** (#748).

**What I did not do:** nothing was upgraded and no flag was flipped. Moving a runtime
dependency and re-arming a capability are both yours to decide. The work is queued as
**#1455**, and #725 remains the owner of the re-enable decision.

---

## 2. The upgrade is far safer than the release notes make it look

The release notes carry an alarming list of removals — the `openvino.runtime` namespace
gone, Whisper stateless decoder support gone, preset generation configs gone, and a
processor-instruction-set requirement raised.

**Nearly all of it is already behind us.** I diffed the 2026.2.0 release notes against
the 2026.3.0 ones. The deprecation section is *cumulative* and carries the header
"Discontinued in 2026.0" — those removals happened in **2026.0**, and our 2026.2.1
absorbed them long ago. The only genuinely new removals in 2026.3 are Debian 10 (a Linux
distribution we do not use), a Model Server serving-protocol drop, and a Kubernetes
operator deprecation. None touch us.

Reading the summary instead of the artifact would have produced a false alarm here. This
is the same failure mode the roadmap keeps recording, so it is worth naming.

**A full sweep of our own code found zero hard breaks:**

| Removed or deprecated thing | Our exposure |
|---|---|
| `openvino.runtime` namespace | Not used anywhere — every import is the modern form |
| `openvino.Type.undefined` | Not used; we never construct types directly |
| `PostponedConstant` signature | Not used; we never build graphs programmatically |
| Preset generation configs (`greedy()` etc.) | Not used; we use the plain constructor everywhere |
| Whisper stateless decoder | **Safe** — our model is the stateful export |
| `start_chat()` / `finish_chat()` deprecation | `start_chat` never called; the one `finish_chat` site is already a defensive probe with fallbacks |

On Whisper specifically: I checked the model files on disk rather than trusting a
setting. `models/whisper-small/openvino/` holds a single decoder with 48 state-read and
48 state-write operations and **no** separate "with past" decoder file — that is the
signature of a stateful export, which is the kind that survives. It is an inference from
file structure rather than a declared flag, so it deserves one runtime confirmation
before the upgrade rather than being taken as settled.

**One loose thread worth knowing.** The version bounds in our service configuration files
say `>=2026.2,<2027`, which does **not** block 2026.3 — and the top-level file has no
upper bound at all. The lock file is the only thing actually holding us at 2026.2.1. A
routine install without the lock would pull 2026.3 today. That is worth tightening
regardless of whether we upgrade.

**Where the real risk sits: speculative decoding.** Speculative decoding is the technique
where a small fast model guesses the next few words and the big model checks them; it is
mandatory in our architecture (ADR-012). We construct it in three places, and **all three
wrap construction in a "if that fails, try again without the extra settings" fallback.**
That means a changed function signature would not crash — it would quietly drop us to
ordinary decoding and cost throughput silently. That is a fail-loud violation, and it is
why the upgrade's acceptance test must prove speculative decoding is still *active*, not
merely that the system starts.

**Versions all line up.** `openvino==2026.3.1`, `openvino-genai==2026.3.1.0` and
`openvino-tokenizers==2026.3.1.0` are all published and mutually compatible. One trap:
GenAI's GitHub releases page stops at 2026.3.0.0 and shows no 2026.3.1 entry — the patch
shipped as packages only. Reading that page alone would wrongly suggest GenAI has no
patch release.

---

## 3. New models: two that matter, and a hard constraint that has not moved

**Qwen3.8-27B** is now functionally enabled on processor, graphics and neural
accelerator, with a ready-made compressed version published by Intel. **Muse-Glimmer-30B**
likewise. Both arrived in the 2026.3.1 patch — unusual, since patches rarely add models.

One practical change worth noting: Intel now publishes a **ready-made 4-bit version** of
the 27B itself. The #923 work had the raw weights on the B: drive and a compression run
under way locally, with running out of memory flagged in advance as an acceptable
outcome given the size. I have *not* checked how that run ended. Either way it is now
largely moot — the conversion no longer has to be done here.

**This does not reopen the model-swap question, and I want to be precise about why.** Our
standing position is that Qwen3-14B stays, with two named signals that would trigger a
revisit. Neither has moved:

- The physics has not changed. Our own measurements put this machine's effective memory
  bandwidth at about 90 gigabytes per second. A dense 27-billion-parameter model at
  4-bit precision must stream roughly 14 gigabytes per generated word, giving about 6.4
  words per second — against about 11 for the current 14B with guessing off. The
  theoretical ceiling of the memory itself is about 9.7. **A dense 27B cannot reach the
  current model's speed on this hardware, no matter what the software does.**
- **I checked both new models' actual architecture files rather than their
  descriptions, because a mixture-of-experts model would break that arithmetic** — such
  models hold many "experts" but use only a few per word, so they stream far less than
  their size suggests. **Neither qualifies.** The published 27B is 14.87 gigabytes and
  the 30B is 16.99 gigabytes, and Muse-Glimmer-30B's configuration shows a *dense*
  vision-language model with no expert routing at all. At 17 gigabytes per word it lands
  near 5.3 words per second — slower still. Both new models are bandwidth losers here,
  and that is a property of this machine, not of the software.
- ~~The thinking-suppression defect (#3937/#4139), which is the *hardest* blocker on that
  swap, is **not fixed in either release**.~~ **[RETRACTED 2026-09-22 — NOT a blocker: our probe opened a reasoning block in the prompt and then measured it. The exports' chat template emits the closed empty block only when `enable_thinking` is defined AND false, a bare opening `<think>` otherwise, and the probe passed it as a `generate()` kwarg where it is dropped. Whether these models honour a correct prompt is UNMEASURED — #1611 S0c. See `docs/MODEL_EVALUATION_QWEN36_27B.md` top-of-file retraction, PERFORMANCE_LOG 2026-07-17 CORRECTION, lesson 369, #1618.]**

So the correct reading is: more models are available; the reason we are not taking them
is unchanged and is about this machine's memory bandwidth, not about software support.

Also new: compatibility with a newer version of the Hugging Face model library
(Transformers v5.5). We are on 5.0. This is relevant because #923 recorded an export
path that only works within a narrow version window — a wider supported range may ease
that, but I have not verified that it does, and I am not claiming it.

---

## 4. The one feature that genuinely attacks a limit we have

This is the most consequential item after the fix, and it needs care, because it is easy
to over-read in both directions.

**What shipped.** OpenVINO 2026.3 can keep part of a "mixture-of-experts" model on disk
and stream the pieces in as needed. Such models hold many specialist sub-networks but use
only a few per word, so most of the weights sit idle at any moment — which makes them the
one model family where leaving some on disk is not obviously ruinous. A new setting
controls what percentage is offloaded, and the system keeps the most recently used
experts in graphics memory.

**Three things I verified in the source rather than the announcement:**
- **It is a graphics-processor feature, not a processor one.** Every changed file lives in
  the Intel graphics plugin, and there is no processor-side equivalent. That is the
  question that decides whether it helps us at all, and the answer is favourable.
- **It was verified by its author on an integrated graphics chip of our own class** — an
  Arc 140T, the same shared-memory design as our 140V — not on a discrete card. So the
  memory saving is a real saving of system memory on a machine like ours.
- **It reads from disk on every cache miss**, using ordinary file reads. So miss cost is
  our drive's random-read latency.

**Why this matters here.** Our constraint with larger models has been memory, not speed.
Our own banked measurement has a 30-billion-parameter mixture-of-experts coder model
running at **38.6 words per second on this very machine** — far faster than the current
14B, precisely because only a fraction of it activates per word. The thing that kept such
models out was fitting them alongside everything else. This feature attacks exactly that.

**And the honest limits, which are significant:**
- **No before-and-after measurement has been published anywhere.** The single published
  figure is about 12.8 words per second for a 30B mixture-of-experts model at 37 percent
  offloaded. Set against the resident numbers above, that implies a substantial slowdown,
  but nobody has published a controlled comparison and I will not manufacture one. The
  release note's phrase "maintaining acceptable" rates has no benchmark behind it.
- **Automatic tuning of the offload percentage is not in this release** — the pull request
  that adds it is still open. Today the number must be chosen by hand.
- **The underlying complaint about mixture-of-experts efficiency on integrated graphics
  (issue #36270) is still open**, and Intel's on-record position is that much of the gap
  is expected behaviour rather than a defect.
- ~~**None of this touches the thinking-suppression blocker** that actually disqualifies the
  Qwen3.6 family for the Policy Agent role.~~ **[RETRACTED 2026-09-22 — NOT a blocker: our probe opened a reasoning block in the prompt and then measured it. The exports' chat template emits the closed empty block only when `enable_thinking` is defined AND false, a bare opening `<think>` otherwise, and the probe passed it as a `generate()` kwarg where it is dropped. Whether these models honour a correct prompt is UNMEASURED — #1611 S0c. See `docs/MODEL_EVALUATION_QWEN36_27B.md` top-of-file retraction, PERFORMANCE_LOG 2026-07-17 CORRECTION, lesson 369, #1618.]**

One genuinely useful discovery from tracing this: an official OpenVINO article reports
**42-43 words per second for a 35-billion-parameter mixture-of-experts model on an
integrated graphics chip**, and says the single most important setting is the attention
backend — *"the first thing to check"* when numbers look low. **Two caveats before that
reads as a promise:** it was measured on a *newer* chip generation than ours (Panther
Lake, one graphics generation ahead of our Lunar Lake), so it is not a number to expect
here; and it is vendor prose, not something we have verified. What survives both caveats
is the configuration lead — that setting is cheap to test on our own hardware, and worth
testing independently of any upgrade.

Ticket **#1454** already owns the benchmark for this, opened yesterday. I have not
duplicated it.

**Also new and quietly useful:** the memory optimisation that reduces the peak during
model loading now covers **Windows** in this release (Linux got it in 2026.2). It removes
the moment where a model briefly exists twice in memory while being handed to the graphics
processor. It does not reduce steady-state memory on our shared-memory design, so it helps
with load spikes rather than with the resident footprint.

---

## 5. Compression: three sub-4-bit options we did not have

The compression toolkit (NNCF) has moved from our pinned 3.0.0 to **3.3.0**, three
releases we have skipped. The substantive additions:

- **2-bit and 3-bit compression types** for OpenVINO, which did not exist before.
- **Quality-preserving compression methods extended to every width below 4 bits** — the
  techniques that make aggressive compression survive contact with reality.

This is the one lever that could genuinely change the memory arithmetic, because it
attacks the *size* of what must be streamed rather than the speed of streaming it.
Whether 3-bit costs unacceptable answer quality is an open, measurable question and not
one I can settle from documentation. This is compression-time tooling only, so it can be
bumped independently of the runtime and carries no runtime risk.

---

## 6. Text-to-speech: a consolidation we can now make

We already ship **Kokoro** for the assistant's voice — but through a separate
non-OpenVINO package, running on the processor. Lesson 14 records the measured reason:
the runtime we use for it has no graphics support in this environment, so it runs on the
processor at a real-time factor of 0.30 (fast enough, but on the wrong hardware).

**OpenVINO GenAI now speaks Kokoro natively**, through the speech pipeline that already
existed for a different voice model, and Intel publishes a ready-converted version at
about 114 megabytes. So this is a tidy-up opportunity rather than a new capability: the
same voice, one fewer dependency, and a plausible route onto the graphics processor.

Two things to know before anyone acts on it. Whether it is actually *faster* is a
measurement nobody has taken — upstream tests it on the processor only, and some of its
tests were being skipped at release time. And there is a **licensing detail worth
deciding deliberately** (see section 8): English is clean, other languages are not.

The honest position: current speech speed is already adequate, so this is housekeeping
with a possible bonus, not a priority. I have not ticketed it.

---

## 7. A faster way to generate text — and the piece we were missing now exists

This is the item I would act on second, after the fix. It is also the one where the
release notes are most misleading, so the correction matters.

**Background in one sentence.** We already use a technique where a small fast model
guesses several words ahead and the big model checks them in one pass; our small model is
a trimmed-down 0.6-billion-parameter copy, and it roughly doubles throughput.

**EAGLE-3 is a better version of that idea** — instead of a separate small *model*, it
uses a single trained layer that sees the big model's internal state, so it guesses far
more accurately at a fraction of the cost.

**Correcting the release notes:** EAGLE-3 is *not* new in 2026.3. It arrived in 2026.0,
so **our current version already has the basic form**. What 2026.3 adds is "tree"
guessing — proposing a branching set of candidate continuations rather than one line, and
checking them all in a single pass.

**The measurement that makes this worth doing.** Intel's own results for the tree feature
are labelled *"perf gain on LNL 64XVE, global bandwidth 101GB/s"* — that is Lunar Lake
with 64 execution units, **the identical graphics configuration to our Arc 140V**. It is
rare to get a vendor number on precisely our silicon. On an 8-billion-parameter Qwen3
model at 4-bit, tree guessing gave **32.32 words per second against 26.91 for the existing
chain method — a 1.20x gain**, with accepted-guesses-per-step rising from 2.22 to 3.02.

**A precision note on that evidence, because it is weaker than it looks.** I confirmed the
hardware description and the settings as *text* in the pull request. The throughput figures
themselves are inside an **attached results image**, not written text, and they are the
author's own numbers with no independent reproduction. So treat 1.20x as a vendor
indication worth testing, not as a measurement we hold. Our own run is what would make it
real — which is the point of the ticket rather than an objection to it.

**The blocker I expected to find, and did not.** EAGLE-3 needs a *separately trained*
component for each specific model — it cannot be derived. Intel only validated the 8B
model, so the obvious fear was that nothing exists for our 14B. **It does.** There is a
publicly published, permissively licensed (Apache 2.0) EAGLE-3 head for Qwen3-14B from
Tencent's AngelSlim project, and I verified its configuration file directly rather than
trusting the listing: single layer, hidden size 5120 matching Qwen3-14B, with the
vocabulary-mapping table OpenVINO looks for. It is the same publisher and format as the
8B head Intel validated. At least three other Qwen3-14B heads exist besides.

**Why this could matter more than the raw percentage.** Ticket #778 measured our current
speculative decoding as **net negative on short turns** — 3.97 versus 5.06 words per
second — because a 0.6-billion-parameter guesser is too expensive to pay off before a
short answer ends. An EAGLE-3 head is a *single layer* rather than a whole small model,
so its per-step overhead is far lower. That is precisely the shape of problem it should
fix, and it would matter most on the assistant's short conversational and tool-calling
turns.

**The honest gaps, and they are real:**
- **Nobody has published running the 14B head under OpenVINO.** Its architecture matches
  the validated 8B head, so it should convert the same way — but that is reasoning, not a
  demonstrated artifact, and this project's standing rule is that documentation is not
  evidence. First conversion is the proof.
- **No published comparison of EAGLE-3 against the classic small-model approach we use
  today** on any hardware. Intel's table compares tree against chain, not against our
  setup. The gain over *our* baseline is unmeasured.
- **There is no ready-made converted version** — we would convert it ourselves.
- **Constraints:** single-request only, and no random sampling with tree search (greedy or
  tree only). Our Policy Agent runs greedy, so it fits; the Assistant's sampling settings
  would need checking.
- **The tree feature gives us nothing without an EAGLE head.** The documentation is
  explicit that classic small-model guessing ignores the tree settings entirely. So this
  is not a free win from upgrading — it requires the conversion experiment.

**This is entirely self-serviceable**: convert, measure against our existing baseline, and
the answer is a number rather than an opinion. No decision from you, no network door, no
new capability. I have queued it.

---

## 8. Smaller things worth knowing

- **Embeddings.** There is a new embedding pipeline, and it does support our BGE model
  (through a text-only path, confirmed by the project's own tests naming
  `bge-small-en-v1.5`). But it largely delegates to an older pipeline that already
  existed, so this is not the leap it sounds like. The real gain would be replacing our
  hand-written averaging and normalising code with a supported implementation — and that
  collides directly with a documented requirement that our 128-token privacy-screening
  path stay **byte-identical**, because its thresholds are calibrated on the current
  numbers. Upstream also has an open accuracy problem for text embeddings on the neural
  accelerator. **Recommendation: leave this alone.** Effort is high, benefit is
  presentational, and the risk lands on a calibrated security path.
- **Speech recognition.** The new speech pipeline is an *adapter* over the existing
  Whisper one, not a replacement; Whisper remains fully supported with no deprecation. So
  this changes nothing for us unless we want the new Qwen3 speech model.
- **Better performance instrumentation.** New per-stage timings are now exposed —
  separate encode and decode durations for speech, and per-step sampling duration for text
  generation. Given how much this project rests on measurement, that is a genuine small
  win for the performance log. **One caution:** I checked specifically, and this does *not*
  appear to expose the draft **acceptance rate**, which is the number #778 actually wanted
  and could not get. I am not claiming that gap is closed.
- **A silent behaviour change to be aware of.** The tokenizer's "truncate long input"
  default flipped from effectively on to **off**, to match the wider ecosystem. Anything
  relying on automatic truncation would now silently pass over-long input instead. **We
  are not exposed** — I checked, and there are zero such calls in our runtime code; only
  benchmark scripts touch it.
- **Kokoro licensing, worth recording before anyone adopts it.** The voice model itself is
  permissively licensed (Apache 2.0), and an official pre-converted version exists at about
  114 megabytes. But the general-purpose pronunciation helper it can use is **GPLv3**. For
  English, the pipeline has a built-in pronunciation path that avoids that dependency
  entirely. So English-only use is clean; other languages would pull in a licence we should
  think about deliberately rather than by accident.
- **The all-in-one multimodal model is not for us.** Qwen3-Omni's only real published form
  is roughly 35 billion parameters. Its own documentation says such models may exceed
  graphics memory and should run on the processor. It cannot coexist with our resident 14B
  on a 31-gigabyte machine — it is a whole-machine experiment, not a component.

---

## 9. What is NOT in these releases

Stated explicitly so nobody has to rediscover it:

- **The thinking-suppression fix (#4139)** — the work you have been reviewing on the
  upstream thread. It targets the 2026.4 development line. Neither 2026.3.0 nor 2026.3.1
  contains it, and #930's blocker is unchanged.
- **Anything requiring a network door.** No egress, no posture change, nothing needing a
  go-live ceremony is proposed anywhere in this report.
- **Any reason to change the model.** See section 3.

---

## 10. What I recommend, and what is yours to decide

**Mine, and queued:**
- **#1455** — the version bump to 2026.3.1, with the full exposure sweep, the acceptance
  tests that would catch a silent speculative-decoding degradation, and the lock-file
  work. Merged dormant: the new lock file lands and is *not* adopted until you say so.
- **#1456** — the EAGLE-3 conversion experiment from section 7. Self-serviceable, produces
  a number, needs nothing from you.
- Tighten the version bounds that currently fail to pin anything.
- Test the attention-backend setting named in section 4, which costs a run and no code.

**Yours, and I am not deciding them:**
1. **Adopting the upgraded runtime.** Runtime dependencies are a capability-affecting
   change, so the adoption is yours even though the preparation is mine.
2. **Re-arming grammar-constrained tool calls** (#725). This restores a security control
   to its designed two-lock state. It is a real go-live ceremony: I would run the 20-run
   repro first, then ask you for one live tool turn to witness it.

**One sequencing constraint I will hold to without being asked:** ticket #1449 has an Arc
graphics driver update held pending other work. Changing the driver and the OpenVINO
version at the same time would make any performance change unattributable to either. They
go one at a time.

---

## 11. What I did not measure

- **Nothing was run on hardware for this report.** Every performance number quoted is
  from our existing logs, not fresh. No benchmark was executed, because the nightly coder
  run was live throughout and the two interfere.
- I did not verify that the newer model-library support actually eases the export
  constraint from #923; I flagged it as plausible and unconfirmed.
- I did not evaluate whether 3-bit compression costs acceptable quality. That needs a
  measurement run.
- The Whisper stateful conclusion is read from file structure, not a declared flag.
- **Nobody, anywhere, has published running the Qwen3-14B EAGLE-3 head under OpenVINO.**
  Section 7's case rests on an architecture match to a head Intel did validate. That is
  reasoning, not evidence, and the conversion is what would settle it.
- **No before-and-after measurement of the memory-offload feature exists publicly** — not
  in the pull request, its review thread, the release notes, or any article. The one
  published figure has no control arm.
- Whether moving speech synthesis to OpenVINO is actually faster than our current setup is
  unmeasured; upstream tests it on the processor only.
- I checked whether the new instrumentation exposes the guess **acceptance rate** that
  #778 wanted and could not find it. I am recording that as "not found", not as "absent" —
  I did not read the whole metrics surface.

---

## 12. How to check this report

Every external claim above came from an artifact rather than a summary, and the specific
artifacts were: the GitHub release bodies and pull requests through the application
programming interface (not the rendered web pages, which omit review data); the package
index for what is actually installable; model configuration files read directly; and our
own source tree, configuration and performance log.

This report was written by the session that did the research, so it was also checked by an
independent reviewer that did not write it, against the same artifacts. Where that review
changed a claim, the claim is stated as corrected rather than quietly rewritten.
