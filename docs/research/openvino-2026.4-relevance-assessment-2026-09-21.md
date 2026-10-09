---
title: What OpenVINO 2026.4, GenAI 2026.4, NNCF 3.4 and Optimum Intel 2.2 give us, and the order to take them in
status: research
area: substrate
date: 2026-09-21
author: claude-code session (interactive; plan reviewed by an independent adversarial reviewer, a build blueprint and an evidence record, all read-only)
---

# What the September releases give us, and the order to take them in

**Plain summary: the software you were waiting for has arrived — the speculative-decoding path
for the 35B model that the model-upgrade watch named as its trigger shipped on 17 September, and
the "thinking cannot be switched off" blocker was very likely never tested through the mechanism
built for it. But before any of that can be measured, the machine has to be put back the way it
was in July: the registry setting that decides how much memory the graphics chip may use reads
57% today, the same value that collapsed the coder thirteen-fold in August, and every Intel
display-driver install so far has silently reset it. Under 57% the 35B cannot even be resident;
under 87% it fits with room for the new draft pool. That one setting is the first decision, and it
is yours.**

Every claim below was read at the artifact — the release bodies through the GitHub application
programming interface (API), the package index, the raw source at the 2026.4 tag, the model export
on disk, the registry and the event log of this laptop, and our own records — never from a summary.
Where I derived something rather than read it, the line says so. Section 10 lists what was read.

---

## 1. Where we stand and what shipped

| Component | Running today (`.venv`) | Export toolchain (`.export-venv`) | Available |
|---|---|---|---|
| OpenVINO runtime | 2026.2.1 (17 June) | 2026.0.0 | **2026.4.0** (16 September) |
| OpenVINO GenAI (the generative-AI pipeline library) | 2026.2.1.0 | none | **2026.4.0.0** (17 September) |
| NNCF (the compression toolkit) | 3.0.0 | 3.0.0 | **3.4.0** (17 September) |
| Optimum Intel (the export tool) | a fork pin from June | 1.27.0 | **2.2.0** (17 September) |
| Python | 3.11.9 | 3.11.9 | 3.10 is dropped only in 2026.5 |
| Graphics driver | 32.0.101.8831 | | see section 2 |

A new dev-side export environment now exists (`.export-venv-2026.4`: OpenVINO 2026.4.0, NNCF
3.4.0, optimum-intel 2.2.0, transformers 5.2.0 — the version the official 35B export was made
with — and torch 2.14 CPU). A side copy of the new runtime (`.venv-2026.4`) is being built from a
draft of the next lock file so measurement never waits on a ceremony; the first attempt exposed a
stray local-project line inside the current lock file, recorded on #1455. The production runtime is
untouched.

**The model-upgrade watch's own trigger has fired.** The watch record
(`docs/MODEL_EVALUATION_QWEN36_27B.md`, revisit triggers) named two upstream changes for its first
signal — the GenAI pull request adding Multi-Token Prediction (MTP) for Qwen3.5/3.6 (#4065) and the
Optimum Intel pull request that exports the MTP head (#1814, whose own example exports the
35B-A3B) — and said *"either merging → re-measure."* Both merged (25 August, 3 September) and ship
in the 17 September releases. The alternative path it named, DFlash (#3938), shipped too, including
for the vision-language pipeline class. This is the re-measure event the watch was written for.

---

## 2. The one number that governs everything: the graphics-memory budget key

**What it is.** Windows grants the integrated graphics chip a share of system memory. The share is
a registry percentage, `SystemPartitionCommitLimitPercentage`. OpenVINO *reports* a different key
(`GpuSystemMemoryPinninglimit`). Our 1 September log entry (#1501, #1485) proved the two can
disagree, that the first one is the real budget, and that the formula relating the second to what
OpenVINO prints reproduces two historical readings to the byte.

**What happened, from the event log and the registry (read today at 16:48):**

| When | Event | Real budget | What OpenVINO reports |
|---|---|---|---|
| 29 June | coder at `cache_size 4`, no offload, 38.58 tok/s | 27.25 GiB (87%) | 25.17 GiB |
| **26 Aug 18:04:55** | a display-driver package is configured; **the real key drops to 57** | **17.85 GiB** | 25.17 GiB — the instrument lies |
| 28–31 Aug | the coder collapses 13×; the investigation runs blind | 17.85 GiB | 25.17 GiB |
| 1 Sep 03:26 | the Intel Arc Software app updates; the reported key drops to 57 too | 17.85 GiB | 16.34 GiB |
| 1 Sep 14:55 / 15:45 | both keys restored to 87 by hand, reboot | 27.25 GiB | 25.175 GiB |
| **14 Sep 23:08:17** | **Windows Update installs display driver 32.0.101.8831; the real key is written to 57 again** (the key's last-write time is that second) | **17.85 GiB** | 25.175 GiB — the instrument lies again |
| 16 Sep 17:42 | last reboot; the 57 has been in force since | 17.85 GiB | 25.175 GiB |
| **21 Sep (today)** | real key **57**, reported key **87** | **17.85 GiB** | **25.175 GiB** |

**Who moves it.** Both drops coincide, to the second, with an Intel display-driver package being
configured. Six such configurations landed between 26 August and 14 September (four during the
August offload investigation, one on 1 September, one by Windows Update on 14 September). The
driver installer writes the key; nothing in our system reads it. That answers the question #1485
has carried since August ("the quantity that moved was one nobody was recording") and it is why
you now hold newer GPU and NPU driver packages that must not be installed until a control exists.

**Why it decides the program.** The 35B model's weight files alone are about 18.3 GiB. Under a
17.85 GiB real budget it cannot be resident at all; under 27.25 GiB it fits, and the extra pool the
new speculative-decoding path reserves (about 3 GiB the way we configure it today) still fits with
roughly 4 GiB to spare. The July measurement of "35 tokens per second, fits in memory" was taken at
87%. The coder fleet has been running under the 57% ceiling since the 16 September reboot.

**What I recommend (decision 0, yours).** Restore the real key to 87 with a reboot — the value
every published BlarAI number was taken under, the value the Intel key already holds, and the
1 September fix — and let the runtime bump add a boot-time check that logs both keys and refuses
a model that would not fit the real budget, so the next driver install is caught the same day
instead of weeks later. The alternatives are to leave it at 57 (the 35B and MTP are then
infeasible without expert offload, and the coder stays at its August ceiling) or to wait for
#1485 to explain the mechanism more fully. Nothing else in this program can be interpreted until
this is decided.

**On the newer drivers you have downloaded.** Not first. Nothing in 2026.4 requires a newer
graphics driver (OpenVINO publishes no minimum for it), every driver install so far has reset the
key above, and changing driver and runtime in the same window makes every number unattributable.
The order is: key restored → controls on today's driver → the runtime bump measured on the same
driver → the drivers as their own re-baseline event (#1449) once the boot-time check exists. The
NPU driver rides the same rule: the neural processing unit runs our embedding path, whose output
is a byte-identical gate, so it too is a re-baseline event.

---

## 3. What is genuinely new for this project, ranked

1. **Multi-Token Prediction (MTP) for Qwen3.5/3.6 and Gemma 4, on CPUs and GPUs.** The model
   drafts its own next tokens from a built-in head; no separate draft model with a matching
   vocabulary is needed, which dissolves the blocker that no Qwen3.6-vocabulary draft existed.
   Upstream measured 1.07–1.30× on a desktop CPU; the one report on our graphics generation
   (genai issue #4483) is on a *discrete* Arc Pro card with its own memory, not our shared memory:
   3.4× at 512 tokens and a 3× slowdown past 64K context. Our watch record expects realised gains
   here to stay well below published figures while the model's linear-attention kernels remain
   compute-bound. It must be measured here.
2. **DFlash drafting, including for the vision-language pipeline** (proposed by me, not in your
   ask): a second speculative path using a small 0.4B drafter published for exactly this model.
3. **Graphics-plugin improvements** for the linear-attention model family (model caching to cut
   load time; time-to-first-token work for Qwen3-VL and Gemma 4). Direction unknown until measured.
4. **Everything 2026.3 brought rides along** (we skipped it): expert offload to disk, lazy weight
   loading and a Windows memory optimisation at load time, compiled-blob compatibility checks,
   EAGLE-3 in the vision pipeline, Kokoro speech, an embedding pipeline, and your own accepted
   fix (#4082) for the grammar crash that has kept a security control off since 2 July.
5. **The export toolchain caught up:** optimum-intel 2.2 exports MTP heads and DFlash drafters;
   NNCF 3.4 adds quality-preserving 4-bit compression for grouped-expert models.
6. **Gemma 4 support matured**, and an official 4-bit export of the 26B-A4B (14.3 GB) that already
   ran on this laptop in July was re-published on 17 September.
7. **Not in 2026.4:** the upstream "thinking suppression" pull request (#4139) is still open,
   marked stale on 21 September, and closes automatically around 28 September absent activity.
   Section 4.1 explains why we may not need it.

Caveats on the release notes themselves: the headline graphics optimisations are scoped to Intel
Core Ultra *Series 3* (the next chip generation); our laptop is Series 2. The Intel Community
announcement you linked has zero replies, and its "What's new" bullet list is pasted from an older
release — nothing from it is cited here.

---

## 4. Corrections to the premises, in plain language

### 4.1 The thinking blocker was never tested through the mechanism built for it
The July probe passed the "disable thinking" flag as a keyword to the generate call, where the
library silently accepts and ignores it; the emulation arm never ran. The official export's chat
template carries the switch, the installed library already exposes the proper mechanism
(`set_extra_context` on the chat history), and a check this session confirmed it renders the
empty "think" block correctly. Better still, the Policy Agent already uses the equivalent trick on
the 14B today (a pre-filled empty think block in a hand-built prompt), and the July 35B quality run
was made by a harness that never asked for no-think and very likely wrapped the prompt twice. So
the "hardest blocker" is probably ours to remove, in one measurement window, without waiting on
the upstream pull request. Untested is not "works": the remaining question is whether the 4-bit
model honours the empty block, and that is what stage S0 measures.

> **Sharpened 2026-09-22, and the mechanism above is understated.** Double-wrapping is a side
> effect; it is not the cause. The cause is that the export's chat template has no neutral
> setting. It emits the empty "think" block only when the no-think variable is present and false,
> and **in every other case it emits a bare *opening* think tag** — so a prompt that says nothing
> about thinking is a prompt that has opened a reasoning block and asked the model to fill it in.
> Our harness said nothing, on all forty cases. The July run therefore did not fail to suppress
> reasoning: it requested reasoning and then marked the model down for complying.
>
> Two consequences worth carrying into the window. First, this is why the failure looked like a
> model defect: our clean-up step removes only a *matched* open/close pair, so a block opened by
> the prompt leaves an orphaned closing tag that survives and reaches the scorer — which is
> verbatim what the ten failures reported. Second, and the trap for the re-run: the rubric check
> named after this property **cannot witness it**. A model that reasons inside a well-formed block
> has that block removed before scoring and passes silently. So a green on that check would have
> replaced a false red with a false green. The only sound witness is the first generated token,
> which stage S0's probe reads directly and proves trustworthy before relying on it.
>
> Established by reading the template, the harness and the strip — no GPU, about a minute's work,
> and it would have voided the July conclusion on the day it was drawn (lesson 369; #1618 carries
> the harness fix). What remains genuinely unmeasured is unchanged and is still S0's question:
> whether the 4-bit model honours a correctly built prompt.

### 4.2 The official 35B export has no MTP head
Intel's published export (unchanged since 10 June) predates MTP support and ships no head. The
library needs only the main model's ordinary output from the official export, plus a small head
file we must produce. A full re-export is a 70 GB download that would page the whole laptop; the
plan rehearses on a small sibling model and tries a head-only export first.

### 4.3 "KV_CACHE=4" does little on this model
Only 10 of its 40 layers hold a key-value cache at all (about 20 KB per token against the 14B's
160 KB), so 4-bit caching saves at most a few hundred megabytes at our context sizes and carries a
quality risk. The capability it points at is a longer context window, which is a separate decision
(DEC-03). Two related findings: the graphics plugin already defaults *some* models to a 4-bit
cache when the setting is left empty, so we may not be running the FP16 posture ADR-040 records
(one read-back settles it), and the 16K context setting in the config file is read by nothing —
the enforced budget is 8K.

### 4.4 Offload to disk is real, bug-marked, and mandatory only under the 57% budget
The expert-offload feature exists since 2026.3. Your own August sweep filed two Intel bugs, one of
which (a hang on the second answer under offload) is unreproduced and open. Under 87% the 35B does
not need offload; under 57% it cannot run without it, and that hang becomes a stop condition.

### 4.5 Prefix caching and the draft pool
The speculative path needs the paged-attention backend, which reserves a memory pool up front and
may need prefix caching off for the verifier. Re-reading an 8K context every turn costs about
16 seconds at the prefill speed measured in July. The measurement is therefore a 2×2 — draft on/off
by prefix caching on/off — because "no draft, caching on, 35 tokens per second" may beat "draft on,
caching off" for a chat.

### 4.6 There is no single swap point
The Qwen3 shape is written into more than fifteen files as separate literals: token ids, the
`/no_think` switch in seven places, five different "strip the thinking" implementations (three of
which leave an unterminated tag in the text), three separate builds of the draft pipeline, and the
model directory owned three times over. The model-profiles manifest built for the coder fleet is
deliberately fail-soft and lives outside the repository, so it cannot own runtime ids. The build
therefore starts by creating one fail-closed profile table inside the repository and routing the
duplicates through it — an improvement that outlives this swap. Qwen3.6 also calls tools in an
XML-style format rather than Qwen3's JSON; the installed library already has a decoder constraint
for exactly that format, unproven on this laptop.

### 4.7 Gemma 4 is measurable cheaply and its licence is not a blocker
Apache 2.0. The official 26B-A4B export ran here in July; its cheap half (thinking control,
throughput, memory) needs no export and runs right after S0, so it can retire the candidate before
the expensive 35B head export is spent. Carried caveats from Intel's own notes: a long-prompt
accuracy issue and a failed agentic test on GPU in 2026.3, an accuracy improvement in 2026.4. A
Gemma brain would supersede the "Qwen3 family locked" rows and make the 14B the out-of-family
grader.

### 4.8 Two things to guard in the runtime bump
An open upstream report (#4476) says greedy speculative decoding on 2026.4 can diverge from the
plain model; the Policy Agent is a security control, so the bump's acceptance test proves
byte-identical output with and without the draft. And the pipeline builder today silently falls
back to a slower, draft-less pipeline on any construction error and still reports speculative
decoding as active — that becomes a loud failure in the same change.

### 4.9 The instrument's own variance
One unchanged coder configuration measured three times in one hour in August read 16.55, 11.82 and
9.59 tokens per second — about 40% between passes against about 12% between configurations. Every
comparison in this program reboots first, interleaves its arms, stamps session age, states the
smallest effect it could detect before running, and declares a winner only when the margin exceeds
that day's spread. That is your own standing rule, applied.

### 4.10 Two banking gaps repaired in this change
The July 35B quality measurement (22 of 40 cases, with about twelve failures caused by the
thinking wrapper) existed only in a data file and a ticket comment, not in the performance log; it
is now entered. And a June record that an EAGLE-3 draft conversion for the 14B already failed
(`docs/eagle3_conversion_findings_2026-06-29.md`) was cited by neither the ticket nor the August
assessment that proposed trying it; the ticket now points at it.

---

## 5. The order, and what each stage produces

Principle: settle the two facts nobody recorded (the budget key, the driver) with the cheapest
step; give measurement its own runtime so no ceremony stands in front of a number; retire
candidates before the one expensive uncertain step; batch your decisions at named ceremonies;
nothing irreversible before them.

| Stage | What happens | What exists afterwards | Your part |
|---|---|---|---|
| **S-1** (today, offline) | the side environments; this report; the review's disposition record; the missing log entry; the bench gains session-age and budget-key stamps | evidence you can read; nothing changed in production | decision 0 |
| **S0** (one daytime GPU window) | controls on today's driver and key state; which attention backend the model takes; thinking control by three mechanisms on both runtimes; Gemma's cheap arm | a yes/no on the thinking blocker; the 35B's speed on today's machine; Gemma's first numbers | none |
| **S1** (a day offline + one window) | the runtime bump to 2026.4 on a branch: new lock file, fork pin retired, the silent fallbacks made loud, a boot-time runtime-version and budget-key check, provenance fields in every baseline; full eval suite on the 14B; merged dormant | a lock file on `main`, production untouched, one adoption command with a rollback | **Ceremonies 1 + 2 in one sitting:** adopt the runtime; re-arm the grammar control after a 20-of-20 reproducer and one live tool turn |
| **S2** (1–2 days offline + two windows) | the MTP head and the DFlash drafter for the 35B; the 2×2 speed measurement; first public Lunar Lake numbers | a measured speculative path, or a measured "none is worth it" | none (posts to the community are held for you) |
| **S3** (one window) | memory envelope with the whole stack and your desktop apps up, against the real budget; the 4-bit cache A/B; offload only if load-bearing; a 32K context curve | the fit/no-fit verdict and its margin | none |
| **S3½** (one window) | the 14B's best speculative path (re-test the June EAGLE-3 failure under the new exporter) | the incumbent enters the comparison measured, not assumed | none |
| **S4** (two windows + a day) | full quality suite on the 35B through production loaders (#933); the Gemma arm on the same protocol; one plain-language head-to-head page | the page | **Ceremony 3:** which brain — led by a recommendation |
| **S5** (build; size calibrated after its first steps) | the profile table; the vision-language pipeline construction; XML tool calls; the assistant's image turn through the resident brain; staging and signing; timeout rows; evals; records; merged dormant behind a profile key defaulting to the 14B | a switch that defaults to today | **Ceremony 4:** go-live, with a live multimodal turn, a live tool turn, a policy denial and the speculative-decoding witness |
| **S6** | follow-ons with observable predicates: the coder fleet's server, the driver re-baseline (#1449), the community posts, the vision model's eventual retirement from the assistant's path | | |

Gates are numbers, not feelings (the plan's section 5b): for example, the 35B control must land
within ±15% of the July 34.97 tokens per second at 87% to count as "the July envelope still
holds"; thinking control passes only with zero tag failures on the 40-case set and the first
generated token verified not to be the think tag in at least 39 of 40; the bump merges only with
byte-identical policy-agent output with and without the draft; quality parity means at least 35 of
37 scored cases and zero injected commands obeyed, and anything lower comes to you as a quality
drop, never accepted silently.

Board: epic #1610; limbs #1611 (S-1/S0), #1455 (S1, retargeted), #1612 (S2), #1613 (S3), #1456
(S3½, re-scoped), #1614 + #933 (S4), #1615 (S5).

---

## 6. What is yours to decide

0. **The budget key** (section 2) — today. Recommendation: restore to 87 and reboot.
1. **Ceremonies 1 + 2**, one sitting: adopt the 2026.4 runtime; re-arm the grammar control.
2. **Ceremony 3:** which brain, with data, led by a recommendation.
3. **Ceremony 4:** go-live of the swap (and, later, arming the XML grammar face for the new model).
4. [PROPOSED] Raise the context window beyond 16K once the 32K curve exists.
5. [PROPOSED] Whether the assistant thinks by default on the new model (quality versus latency,
   both measured first).
6. The upstream thinking pull request (#4139) auto-closes around 28 September; keeping it alive is
   a post from your account. Recommendation: decide after S0 — if our own control works, it is a
   nicety for reasoning budgets, not a need.
7. Only if the head-only export fails: whether to park a battery night for a full export.
8. Only if it becomes decisive: rolling back a Windows update (an operating-system change to your
   only machine).

---

## 7. Risks and stop conditions

- **Budget at 57%:** the 35B cannot be resident; the speculative paths need a pool; offload is
  mandatory and the open Intel hang is a stop condition. A "no draft at 35 tokens per second"
  outcome forfeits speculative decoding and is an architecture-decision question for you, never a
  silent downgrade. The coder fleet is already living under this ceiling tonight.
- **Thinking control fails on the real model:** #930 stays gated on upstream; the program stops
  before the build.
- **The 35B head cannot be produced here:** DFlash only, or no draft; a full export never runs
  against the battery or on a paged-out disk; a self-converted main model is never compared against
  the official export's numbers (conversion quality was a 20× variable in July).
- **Injection resistance regresses on the policy role:** a security posture — stop and escalate.
- **The upstream determinism report reproduces here:** no merge until explained.
- **Variance:** a day whose spread exceeds the effect is reported as undecidable, not as a result.
- **GPU contention:** every window is announced on the epic ticket; nothing today refuses a test
  run or a battery launch while a 19 GB model is resident, so the announcement is the control until
  a lock file exists.

---

## 8. What I did not measure

- **Nothing ran on the graphics chip for this report.** Every performance number is from our
  existing records; the registry, event log, package lists and model files were read; two CPU-only
  checks confirmed token ids and the template render.
- Whether the 4-bit model honours the empty think block (S0).
- The 35B's speed on today's driver and budget (S0a).
- Which backend the hybrid model takes here, and what the pool costs (S0b).
- Whether the head-only export is feasible, and whether the June export satisfies the DFlash
  hidden-state requirement (S2).
- Gemma's throughput on this laptop (recorded in July as load time and memory only).
- The exact mechanism by which the driver installer writes the key (the coincidence is to the
  second on two occasions; the write itself was not traced).

---

## 9. How this report was checked

The plan behind it was attacked by an independent read-only reviewer against the repository,
doctrine and the machine (25 findings, all dispositioned in
`docs/reviews/openvino-2026.4-plan-review-disposition-2026-09-21.md`), complemented by a
file-by-file build blueprint and a 1,770-line evidence record. Two of the reviewer's HIGH findings
changed the program's shape; one of them was itself corrected by a later log entry the reviewer had
not reached, and then by the live registry read — which is the reason the key is section 2 rather
than a footnote.

## 10. Artifacts read

Release bodies via the GitHub API (openvino 2026.4.0; openvino.genai 2026.0–2026.4; nncf
3.2–3.4; optimum-intel 2.0–2.2); pull requests #4139 (with reviews, comments and files), #4065,
#4312, #1814, #1756; issues #4483, #4476, #3937; raw source at the 2026.4 tag for the speculative
decoding strategies, the MTP and DFlash transforms, the language and vision-language pipelines, the
chat-scenario and speculative-decoding documentation; the graphics plugin's properties and
execution configuration at three tags; the package index for all four packages; Hugging Face
listings and cards for the Qwen and Gemma exports and the DFlash drafter; on this laptop the
official 35B export (sizes, configs, both templates, output names, token ids through both
tokenizers), both environments, the library's interface stubs, both service configurations, the
eval harness, the July probe script, ADR-012 and ADR-040, the decision register, the performance
log entries of 16 July, 31 August and 1 September, the data files of 16 July, 22 July, 1 September
and 17 September, the June EAGLE-3 finding, the August assessment, both model evaluations, the
roadmap, the sprint pointer, the test governance, the two registry keys, the event log; Vikunja
tickets #550, #715, #725, #769, #834, #923, #930, #931, #933, #1005, #1080, #1449, #1454, #1455,
#1456, #1461, #1485 and their comments.
