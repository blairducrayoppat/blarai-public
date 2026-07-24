# BlarAI — Lessons Learned

*The distilled list, moved out of `BUILD_JOURNAL.md` on 2026-07-03 so it can be
curated as well as appended. Each numbered lesson was paid for by a real,
documented incident; the journal entries in `BUILD_JOURNAL.md` are the evidence.
This file is the compounding portfolio surface.*

## Rules of this file (the curation discipline)

1. **Never renumber or delete a ratified lesson.** Lesson numbers are cited
   throughout `BUILD_JOURNAL.md` and the ADRs; they are permanent identifiers.
   Consolidation happens by cross-reference and by the canonical tier below,
   never by renumbering.
2. **Search before you mint.** Before adding a new lesson, search the **Index of
   every lesson** below (plus the Canonical Tier) for the class. If the incident
   is a recurrence of an existing lesson, do NOT mint a new number — append a
   dated recurrence tally to that lesson's full text **in the archive volume**
   (`docs/archive/lessons/LESSONS_ARCHIVE.md`):
   `*(recurred: YYYY-MM-DD — <entry title>)*` — and bump the `↺` flag on its
   index line here.
   **Three surfaces, and only two of them take the tally — this is deliberate,
   not an omission** (amended 2026-07-22 after an independent review found 7 of
   the 32 Canon-32 full texts silently stale, 4 of them made staler that same
   day by a curator following this rule exactly and correctly):
   - **archive volume** — the incident LOG. Every `*(recurred: …)*` marker goes
     here. This is the authority for how many times a class has recurred.
   - **index line here** — the COUNT. Bump `↺n`. This is the pre-mint search
     surface, so it is what a future session actually reads before deciding.
   - **Canon-32 residency tier** (below) — the JUDGMENT, not the log. Its full
     texts carry what the lesson *teaches*; they do **NOT** accumulate
     recurrence markers, because this is a hot always-loaded file under a hard
     120 KB budget and appending every tally to 32 duplicated full texts blows
     it (measured: backfilling all 7 stale copies took the file 3,393 bytes
     OVER budget, which is why that backfill was reverted rather than shipped).
     A Canon-32 entry that has fewer markers than the archive is therefore
     CORRECT BY DESIGN. Read `↺` on the index for the count and the archive for
     the history; never infer a recurrence count from a Canon-32 copy.
   What a Canon-32 copy MUST stay in sync on is the lesson's own text — if the
   archive's headline or judgment is revised, revise the hot copy in the same
   change, and take the trim needed to stay under budget at the same time.
3. **The third-instance rule.** A lesson that reaches its third instance
   (original + two recurrences) is no longer a lesson — it is a missing
   control. The change that records the third tally MUST also ship a
   structural enforcement (a gate test, a CI check, a hook, a required
   checklist line) and record it on the lesson:
   `*(control: <what was built, file/test name>)*`. A lesson that keeps
   recurring with no control is a documented failure of this discipline.
4. **Judgment here; mechanics in `FIELD_NOTES.md`.** This list is for
   transferable judgment — things an engineer could apply at a different
   company. Environment-specific gotchas (a Windows API trap, a regex-engine
   dialect, a driver quirk) go to `FIELD_NOTES.md` instead. When an incident
   yields both, the lesson carries the judgment and links the field note.
5. **Quarterly consolidation pass.** Once a quarter (next due: 2026-10-01),
   one session re-reads additions since the last pass, refreshes the canonical
   tier below AND the Canon-32 residency tier, places any lessons still listed
   as unassigned in the tier addendum, adds missing recurrence tallies, and
   verifies every third-instance lesson has its control. This is scheduled work, not
   willpower. The same pass walks `shared/timeout_registry.py` (LA-directed
   2026-07-07): per entry — is the incident still the binding rationale, can
   the budget shrink (measured, never guessed), can the timeout be retired for
   an event/health signal; BACKLOG rows get promoted or consciously retired.
6. **Numbering at fold-in only.** Journal fragments propose lessons described,
   never pre-numbered (see `docs/journal_fragments/README.md`); the integrator
   assigns the next number serially — one line added to the Index below, full
   text appended to the archive volume.
7. **Three tiers (2026-07-19, #945 D2).** This hot file carries the Rules, the
   Canonical Tier, the Canon-32 residency tier (full text), and the one-line
   Index of every lesson. The full text of all lessons lives append-only in
   `docs/archive/lessons/LESSONS_ARCHIVE.md`. Mechanics live in
   `FIELD_NOTES.md` (Rule 4). Hot-file budget: **120 KB** — the
   doctrine-freshness gate enforces it; growth beyond that is consolidated at
   the quarterly pass, never waved through.

---

## The Canonical Tier — twenty classes that own the list

*The page to read first. Each canonical class names the constituent numbered
lessons that earned it. Curated 2026-07-03 from lessons 1–195; refreshed at
each quarterly pass.*

**C1. Process is not progress.** Activity — documents, sessions, audits of
audits — is not product. Build the smallest thing that genuinely runs, then
grow. Of \~259 autonomous fleet sessions, 15 committed real code. *(Lessons 1, 4.)*

**C2. "Show me it running" — the live screen is the only proof.** A green
suite proves the plumbing; only the real system doing the real thing proves
the feature. Live-verify is a bug-finding instrument, not a rubber stamp, and
the fixes it finds are the verification. *(Lessons 2, 24, 171, 176, 182, 194.)*

**C3. A test that shares the code's blind spot certifies the bug.** Code and
test written from the same wrong mental model agree with each other. A test
double must mirror the real contract (shape, async-ness, variance); a
regression lock earns trust only once you have watched it fail against the
fault it guards. *(Lessons 3, 30, 114, 150, 167, 186.)*

**C4. The bug lives in the seam, not the parts.** Component-green is not
system-green: mocked seams, individually-correct components with an
unspecified contract between them, and standalone benches all hide the defect
that only a test driving the real connected path can catch. *(Lessons 30, 56,
65, 90, 92, 119, 175, 187.)*

**C5. What you configure is not what runs.** A setting is a request; a
constant may be overridden; a knob may be wired to nothing. Instrument the
system to report what it actually did and believe the instrument. *(Lessons 6,
44, 79, 156.)*

**C6. Built is not wired; wired is not activated; activated is not exercised;
exercised is not operator-reachable.** Five separate claims, each needing its
own proof — the security audit's "built but switched off" theme, and the
`/images` command the operator couldn't type. *(Lessons 46, 57, 61, 73, 94,
95, 133, 147.)*

**C7. Get the instrument right before trusting what it tells you.** Confounds
(thermal drift, page-cache warmth), premises that rot when the stack moves,
costs measured on a bench the assembled system never pays, and measurements
attached to the wrong scenario have each flattered or panicked this project.
Re-measure the path you actually shipped. *(Lessons 7, 8, 17, 37, 39, 145,
151, 169, 195.)*

**C8. Verify the premise on disk before building on it.** Briefs, tickets,
docstrings, trackers, handoffs, and your own remembered architecture are
hypotheses. Read the code, the row count, the call graph — the cheapest sprint
is the one whose mechanism already shipped, and the worst build is one on a
premise four documents inherited and none checked. *(Lessons 14, 48, 69, 76,
82, 107, 108, 125, 146, 154, 163, 165, 193.)*

**C9. The log decides, not the hypothesis.** A plausible failure mechanism is
a hypothesis to test against the evidence the system wrote, not a conclusion
to build a fix on. Read the log before touching the code; ground heuristics in
real artifacts. *(Lessons 24, 160, 168.)*

**C10. Provenance is not trust — grounded data is never instruction.** Your
own stored documents, a subordinate model's output, retrieved memory, and web
content are all data to be datamarked, never instructions to obey; the
leakage/locking axis is provenance, never a similarity score. *(Lessons 13,
26, 132, 190.)*

**C11. Fail-closed needs a proven allow-path, and the posture must match the
threat.** A deny-by-default control that nobody verified against legitimate
traffic is a self-inflicted outage; an over-eager control is a regression
wearing a security badge; an optimisation should fail soft where a boundary
fails closed. *(Lessons 22, 27, 36, 63, 93, 135, 184.)*

**C12. Ship dangerous capability behind one door, opened as a single reviewed
act — and default the PROVEN to live.** Build the seam before the feature,
weld it with independent locks, make release one auditable governance act. But
dormancy is for the unproven and the security-sensitive: a mature,
gate-green, hardware-verified feature ships enabled. *(Lessons 111, 124, 181,
189.)*

**C13. Escalate capability, quality, and security; own the mechanics.** A
decision is only a decision if the options differ on something the operator
governs. Burying a capability cut in a "recommended option" and handing a
novice a git question are the same error in opposite directions. *(Lessons 29,
38, 66, 72, 84, 99.)*

**C14. A claim the code does not enforce is governance debt.** Comments
asserting validations that don't run, docs naming controls that don't exist,
"zeroization" that rebinds a name — encode every claimed property as something
a reader can watch fail, and when the honest guarantee is weak, say so.
*(Lessons 47, 51, 97, 142, 146.)*

**C15. Close the class, not the instance.** Two components built from one
template carry the same defect; a fix that lands on one sibling is a half-fix.
Scan for the shape before closing, and audit every branch that produces a
guarded value. *(Lessons 64, 138, 141, 170.)*

**C16. Shared state between concurrent actors needs a mechanism, not
carefulness.** One HEAD, one journal file, one certs directory, one shared
`main` — every "be careful" eventually lost to a worktree, an `--ff-only`, a
fragments inbox, a single-instance lock, or a staged-diff read. Scale the
mechanism when the actor count grows. *(Lessons 9, 35, 41, 42, 52, 89, 98,
113, 158, 172.)*

**C17. For the layer you cannot unit-test, instrument it — observability is
the verification.** Across a GUI, a device, an elevated process, or a vendor
binary, artifacts-on-disk and dual-sided logs turn guessing into single-step
diagnosis; the "untestable" layer is usually just untested. *(Lessons 16, 32,
83, 174.)*

**C18. Verify silicon and external contracts on the real thing.** Spec
sheets, vendor docs, and inherited designs describe an intended device; the
trust root is built on the measured one, and a documented API endpoint can be
dead by go-live. Only a live probe settles it. *(Lessons 18, 96, 103, 126,
128, 188.)*

**C19. A control that depends on a human remembering is not a control — and a
human step must be proven necessary.** Make the safe posture the enforced
default, guard cross-language mirrors with gate tests, and route a step to the
human only when it genuinely needs human hands. *(Lessons 44, 86, 149.)*

**C20. Ask the human only what the human can judge, at the coarsest
meaningful grain.** An unjudgeable consent degrades to a rubber stamp; route
danger to deterministic controls and put the question on the action, not the
content. When the non-expert operator's gut says a design is wrong, that is a
design-review trigger. *(Lessons 38, 191, 193.)*

---


### Canonical-Tier addendum — class placements for lessons 196–284 (2026-07-19 tiering, #945 D2)

*The tier above was curated 2026-07-03 from lessons 1–195. Audit-pass placements for the newer third, by class; the 2026-10-01 quarterly consolidation refines them into the class prose above.*

- **C2** gains: 264, 267
- **C3** gains: 215, 237, 265, 281
- **C4** gains: 237
- **C5** gains: 275
- **C6** gains: 242, 243, 266, 276
- **C7** gains: 201, 204, 250, 279, 280, 281
- **C8** gains: 269, 271, 282
- **C9** gains: 262
- **C10** gains: 273
- **C11** gains: 259
- **C14** gains: 275, 278
- **C15** gains: 259, 265
- **C16** gains: 221
- **C18** gains: 213
- **C20** gains: 267
- **Unplaced (quarterly pass to assign):** 196, 197, 198, 199, 200, 202, 203, 205, 206, 207, 208, 209, 210, 211, 212, 214, 216, 217, 218, 219, 220, 222, 223, 224, 225, 226, 227, 228, 229, 230, 231, 232, 233, 234, 235, 236, 238, 239, 240, 241, 244, 245, 246, 247, 248, 249, 251, 252, 253, 254, 255, 256, 257, 258, 260, 261, 263, 268, 270, 272, 274, 277, 283, 284, 285, 286, 287, 288, 289, 290, 291, 292, 293, 294, 295

## Canon-32 — the residency tier (full text, 2026-07-19)

*The 32 lessons that earned permanent hot residency at the #945 D2 tiering: transferable beyond this project, repeat-incident-class, or portfolio-defining. Everything else lives one grep away — index below, full text in [docs/archive/lessons/LESSONS_ARCHIVE.md](docs/archive/lessons/LESSONS_ARCHIVE.md).*

1. **Process is not progress.** I spent months building an "autonomous fleet" — AI agents meant to build software on their own. It generated an enormous amount of documentation: design docs, reports, audits of the reports. It produced almost no working product. Of around 259 automated sessions that committed anything, only 15 committed real code; the other 244 committed only markdown. It *felt* like work. Activity is not progress.

2. **"Show me it running."** A passing test is not proof a feature works. The only proof is the real system doing the real thing, in front of me. Every fix in this project is now verified live before it counts.

3. **A green test suite is only as honest as its assumptions.** BlarAI had tests for hiding the model's internal reasoning. They passed for a long time. The feature never worked: the tests checked for a tag the model never produces — the *same* wrong tag the code looked for. Code and test agreed with each other, and both were wrong. Tests that share the code's blind spot will confirm a bug instead of catching it.

8. **Fixing the instrument once does not make it trustworthy.** After the benchmark was corrected for thermal unfairness *between* configurations, I trusted it. A clean re-run drifted anyway — this time *within* a single configuration: a dozen measurements back-to-back heat an integrated GPU enough to throttle the last of them. One thermal hole had been closed and another left open, and only reading the runs one by one — not the average — caught it. A result is meaningful only with enough samples and its confounds held still, and that is not a fix you apply once; it is a question to ask of every measurement. *(recurred: 2026-06-29 — The upgrade that didn't speed up generation, and the browser that faked a regression)* *(recurred: 2026-06-29 — The benchmark that copied production's homework)* *(third instance — control: the steady-state benchmark protocol in `scripts/benchmark_kv_cache_sweep.py` — warm-to-plateau, inter-combo cooldown, and a first-combo-vs-isolated-smoke cleanliness gate; #709.)* *(recurred: 2026-07-09 — The protocol that could see the coder thinking; the confound was the SUBJECT's own dice, not the instrument: a temp-0.7 coder stochastically spiraled in one A/B leg, and the 10x wall-clock delta would have read as transport overhead — named as unmeasurable-at-N=1 instead of reported as a finding. A confounded number dressed as a measurement is worse than no number.)* *(recurred: 2026-07-11 — The benchmark that couldn't answer the question, and the decision that didn't need it to; rounds 2–3 of the acp-vs-stdin coder A/B stayed confound-dominated — six legs 360–912 s on ONE file-task, a ±550 s temp-0.7 coder-stochastic swing swallowing any transport signal whole at N=3 (round 3's tell: acp ran hot AND both candidates went idle-stuck yet came in fastest, because its stall-detector cut them where stdin let them ride — the drivers' stop-mechanisms moved the wall-clock more than the transport did). So the go-live flip (#775) was decided on the axis that is BOTH measurable and decision-relevant — the proven observability/stall/cancel superiority (ACP-01 §6) — not held hostage to a wall-clock win the noise can't deliver, with the residual (detection-sensitivity vs induced-instability at N=3) named rather than implied-answered. #775.)*

10. **Continuity of intent across agents is a file-system property, not a memory property.** The journal discipline that compounds this portfolio worked while it lived in the head of whichever agent was carrying the work, and stopped working the moment a fresh session opened without it. The Layer 3 over-build was, at root, the same shape: a rule held in one place that should have been held in two. If you want the next session to do the thing this one learned, write it down where the next session will read it — not where you will remember it. `CLAUDE.md` is the right place for standing instructions every agent inherits; the journal entry below it is the evidence the instruction earned its standing. *(recurred: 2026-07-11 — Durability without distribution is half the job / The tenet that failed its own test; the #769 follow-up benches were durable — banked on the ticket and in committed JSON — but never DISTRIBUTED into the #859 pull view the next GPU session reads, one forgotten verbal handoff from silent loss across the night→daytime chain: the original class sharpened one notch (the information WAS written down, but where the author could point to it, not in the reader's first-read path). Under adversarial review the tenet then reproduced its own error — both requirement seeds lived only as ticket comments while the parent descriptions enumerated their scope without them, the #769 drop re-run on the ticket built to prevent it. Distilled into the Coordinator program doctrine (#842/ADR-039 §Kanban, #846 pull policy): every defer writes BOTH halves — the durable record AND the pull-view placement with an unblock predicate — and resource-gated items stay a first-class visible marking that auto-re-surfaces when a CLOSED-registry predicate frees. Second instance; the #846 resource-gated-pull mechanism plus the #864 handoff-template both-halves checklist line are the structural control already in flight for the third. #769/#859.)*

13. **Provenance is not trust: your own stored data can still carry an attack.** When the Substrate began feeding the model the user's past documents and past conversations as retrieved memory, the easy assumption was that this content is "ours" and therefore safe — it came from the user's own files and the user's own earlier turns. That assumption is wrong in a way that matters. A document loaded last week may have carried an injection nobody noticed at the time; a past conversation may contain text the user pasted from a hostile page. Stored-by-us is not authored-by-us, and even authored-by-us is not safe-to-obey. So retrieved memory runs through the exact Layer 1+2 defences a freshly-loaded document gets — forged-delimiter neutralisation and per-load datamarking — and is grounded as data, never trusted as instruction, no matter that it came out of our own database. The general rule, and one the AIGP body of knowledge keeps returning to: the *provenance* of data (where it came from, who stored it) is independent of its *trustworthiness* (whether it is safe to act on). A system that conflates the two — "it's from our own store, so it's clean" — builds a laundering path where yesterday's unnoticed injection becomes today's trusted instruction.

14. **A handoff brief is a map, not proof the terrain is passable — probe the load-bearing unknowns before building on them.** The voice handoff brief was excellent: it named the models, the package, the wire format, even the integration points file-by-file. The temptation was to trust it and start writing the ADR. Blair's correction was the right one — "you leaned on the brief as a map without confirming it's buildable." So before a line of feature code, I ran the three unknowns on the actual hardware: does `WhisperPipeline` really exist in this OpenVINO build (yes); does Kokoro run on the Arc GPU or silently fall to CPU (CPU — onnxruntime here has no GPU execution provider — but measured real-time-factor 0.30, fast enough, so the brief's assumption was wrong in mechanism yet right in outcome); does the elevated app's microphone hit the same UIPI wall as drag-drop (reasoned no — capture is in-process, not a cross-integrity-level message). The probe paid for itself twice: it found that the brief's "Kokoro on GPU" premise was false, and — chasing the STT conversion path — it surfaced a *pre-existing* broken `optimum` exporter (a three-way `transformers`/`optimum`/`optimum-intel` version mismatch) that the brief never mentioned. The governance shape here is the one the cert track rewards: a plan inherited from a predecessor (or a vendor, or last quarter's you) carries assumptions that were true *then*, *there*, or *never* — and the cost of verifying a load-bearing assumption is always smaller than the cost of building a phase on top of one that has quietly rotted. Measure first; the number you get is the one you write down, not the one you were handed. *(recurred: 2026-07-11 — The chunks the ticket thought were already paid for; #807 PGOV Stage-5's ticket premise \"the chunks were already embedded at store time\" was false in mechanism — Stage 5 eats context-manager text, not substrate rows — so probing the feed reshaped the fix from stored-embedding plumbing (which would have changed a security control's numerics) to a numerics-preserving LRU cache; measure first, the number AND the mechanism you get are the ones you write down. #807.)* *(recurred: 2026-07-16 — The probe that found nothing wrong, and the trigger that wasn't there; the #900 measurement plan inherited a runbook whose primary trigger (a hires-fix generate) had been `hires_enabled=false` in the shipped config all along, and a brief wrong on two load-bearing disk facts within a day of being written (a working set deleted ~07-12; an official artifact already fully downloaded 07-11) — a measurement runbook's named trigger is a config-dependent claim, verified live at plan time, same standing as the brief's disk facts. The durability half of the same incident: the deletion WAS sanctioned, but the sanction lived only in a GITIGNORED handoff brief no successor grounding via git and tickets would ever see — a sanctioned-cleanup decision that changes what is on disk must land on the ticket, the durable queue the next actor actually reads. #900.)*

22. **Fail-closed is not fail-shut: a deny-by-default control must still enumerate — and prove — the legitimate-allow set.** BlarAI's "no external network" guarantee was never enforced anywhere; it held only because the machine was air-gapped and the source happened not to call out — and both of those evaporate the day it faces the internet. Turning that habit into a code-enforced egress kill-switch, the handoff brief's framing — "refuse any outbound socket" — would have bricked the app on launch, because the runtime's own IPC *is* sockets: the Hyper-V vsock, the dev-mode loopback TCP, the launcher's 127.0.0.1 handshake. The LA caught it before it shipped. The control had to be an allowlist — permit loopback and Hyper-V, deny the rest — and the test had to assert the *positive* path (the local channels still pass) as rigorously as the negative one (external egress refused), because a fail-closed control whose allow-set nobody verified is one launch away from a self-inflicted outage that no headless test would catch: it lives in the GPU-bound elevated boot only the live screen sees. Two craft corollaries, paid for the same way: a guard must bite at the layer where the real egress happens (the raw socket's connect/bind — which both call sites perform *before* the mTLS wrap, so read the order rather than assume it), and a process-wide monkeypatch must be armed only at the true process entry (`__main__`), never in importable code a test will run, or the global mutation leaks into the suite and breaks things far from where it was set.

29. **Escalate what the user experiences; own how it is wired — a quality or capability tradeoff is the operator's call, never an implementation detail you slip in.** To fix a memory freeze I proposed downscaling a 50 MP photo to \~1.5 MP before the vision model, and framed it as a "low-risk, standard, reversible" recommended option. Blair stopped it: that resize would gut the answer for the very query the photo carried — *read the text on the wall* — and reducing what the product can do is his decision, not mine to bury in a recommendation. His framing is the rule: *"decisions that have large impacts on the quality of the response is the kind of hard escalation we should be having to me, not stuff asking me about Git which I know nothing about."* The non-developer operator cannot adjudicate commit structure or which thread a call runs on — decide those yourself — but whether the assistant can still read the sign in the photo is exactly the call to surface, explicitly, with alternatives, *before* implementing. This sharpens the calibrate-your-asks discipline: "decide implementation yourself" covers the wiring, never the user-visible capability. Two technical corollaries the same round paid for: a memory "fix" I could not measure was a no-op that *logged a lie* ("VLM memory released" while the OS got nothing back — `gc.collect()` does not return a GPU driver's pooled memory intra-process; only process exit does), so I shipped observation (psutil memory + input-size logging) and deferred the behaviour change to when a harness can measure it — a log line is a claim, not proof, and the layer you cannot test is the one that bites (cf. lessons 6, 16, 27).

30. **A guard you have not watched go red against the bug is decoration — and a bug in the interaction between parts is invisible to tests that exercise each part alone.** The image-attach freeze sailed through 1,483 passing tests because not one of them drove an attach and a voice request against the *same* event loop — the contention *was* the bug, and a per-handler suite structurally cannot feel it. Building the regression lock, the easy version passes when the fix is present; the honest version must also *fail when the bug is present*, so the suite carries a meta-test that reconstructs the pre-fix sync-on-loop dispatcher and proves it starves the neighbour. Until I had seen the lock red against the reconstructed regression, I had a test that passed, not a guard that catches — different things. Two corrections from an adversarial review I ran against my own harness sharpened it the same day: my first lock asserted a *timing proxy* (the loop stayed responsive during the attach) rather than the property the fix actually guarantees, so I replaced it with a thread-identity assertion — the blocking call ran on a different thread than the loop — which is both the real invariant and immune to the CI jitter a millisecond budget is exposed to; and the review caught a memory-eviction helper that `del`-ed a *parameter* and freed nothing, the same logged-a-lie no-op as lesson 29, written twice in one week. The shape the cert track rewards: a regression lock earns trust only once you have watched it fail against the very fault it guards, and a contention bug needs a harness that reproduces the contention, because the component suite will keep certifying that every part is fine while the whole stays broken (cf. lessons 3, 21, 25, 29).

37. **A cost measured in isolation can be a cost the running system never pays — profile the component where it lives, not on a bench by itself.** A ticket reported a 5–8 second "embedder first-prompt tax" the Substrate supposedly added, and the profiling that found it (#546) had measured the bge-small embedder *standalone*, in a process that imported nothing else. Decomposed, that 5–8 seconds was \~92% a single `from transformers import AutoTokenizer` — a one-time Python library import, not model I/O, not graph optimization, not tokenizer files (those were 0.2 s and 0.04 s). And in the real Assistant Orchestrator that import is already paid, at boot, by the 14B's own inference module, which imports `transformers` at module load for *its* tokenizer — before the Substrate ever builds. So the embedder, loading after it, finds the library cached and costs \~0.3 seconds, not 5–8; I confirmed it by measuring the load with `transformers` pre-imported (\~0.3 s) versus not (5 177 ms). The "tax" was an artifact of the bench: a shared dependency billed in full to whichever component is measured alone, when the assembled system pays for it exactly once and attributes it to whoever loads first. The trap nearly cost more than a wrong number. The ticket framed three options for *disposing* of the 5–8 seconds — fold it into boot, background it on a thread, leave it — and I began by relaying those options to the operator as a live choice, after my own data had already voided the premise behind them. He stopped me twice: if the tax isn't real there is no choice to make, and presenting one is hedging instead of owning an obvious call. The governance shape is two-edged. Measure a shared cost *in situ* — co-resident, in the real process, in load order — because a component's standalone cost and its marginal cost in the assembled system are different numbers and only the second is real. And when your own measurement dissolves the premise of a decision, report the conclusion and act; do not keep offering the options the dead premise used to justify. (cf. lessons 7, 14, 17.)

38. **When the operator's gut says a design is wrong, that is a design-review trigger — re-derive from best practice, do not defend the as-built.** The provenance sprint shipped a blunt action-lock — any untrusted content turned *every* tool off, and `/trust` turned them back on — and it passed every test and verified live. Then the User-Operator, a self-described non-developer, watched a clock get locked behind a `/trust` prompt and said *"is this really best practice? this whole trusting process seems bad."* He was right, and the reflex to explain why the shipped design was fine would have buried a real flaw: the blunt lock adds friction with zero security benefit on a calculator, and `/trust` pushes an un-evaluable security decision onto exactly the person least equipped to make it — two anti-patterns the literature names. The fix was a different shape, not a tweak: tools carry risk tiers, safe tools are never locked, dangerous *actions* are denied absolutely with no override, and the sharp per-action deny that already existed (the #570 mediation) does the real work while the blunt lock scopes down to where it earns its friction. A non-expert's "this feels wrong" about a security experience is rarely noise — it is the smell test the experts stopped running. Treat the challenge as a prompt to re-derive from first principles and the external state of practice; the as-built is evidence of what was tried, never proof that it was right. (cf. lessons 16, 29, 37.) *(recurred: 2026-07-03 — The deck the fold forgot, and the deck the method built)*

46. **A control wired into a function but not into the boot path is still "built but wired into nothing" — a green suite proves the mechanism, never that the running system invokes it.** The Sprint-13 tamper-evident audit stream was built correctly — hash-chained records, a pluggable signer, fail-closed writes, dependency-injected into all three of the adjudicator's return points — and proved with 38 teeth-tests that all passed. It was still inert: the production Policy Agent is constructed in one factory that called `from_config` without passing the sink, so the running PA would have persisted exactly zero records. That is the 2026-06-03 audit's own central finding — the TPM root with no callers, the leakage detector fed an empty list — recurring *inside* the sprint built to close such gaps, and the full green suite hid it because the tests exercised the part in isolation, not the live boot. Reading the production construction site caught what no passing test could. The fix that makes it stick is a regression test asserting the boot factory yields `has_audit_log == True` — an assertion that fails the day the wiring is removed. When a mechanism's tests prove it in isolation, ask separately whether the live system actually invokes it, and write the test that breaks if it stops. (cf. lessons 16, 23, 30.) *(recurred: 2026-07-07 — Closing the free-text gaps in a sequence that was already half-grammatical; the W2 `structured_generate_fn` decompose grammar hook was built, tested, and unreachable from the live PLAN path — `generate_plan` never threaded it to `decompose_request`, so no production dispatch could ever fire it; fixed same-commit, leaving the future AO adapter exactly one wiring seam. #743.)* *(recurred: 2026-07-07 — The verification line nobody ever read; THIRD INSTANCE. Both opencode fleet plugins ran silently dead in production 2026-06-30→07-07 — the loader rejected their regex named exports and printed nothing on the production path — while their designed-in stderr load-lines ("so the fleet can VERIFY the plugin actually wired in") were never read by anything; the whole June-July battery baseline ran un-pluginned. #759 recon caught it; #764 fixed it. A verification line nobody reads is a verification line that does not exist.)* *(control: the #762 load-line canary — agentic-setup `scripts/fleet-lib.ps1` `Test-PluginLoadLines` + `Write-PluginCanaryVerdict`, wired at the tail of EVERY `Invoke-AgentRun` after the stderr fold: both load-lines must appear in the run transcript and zero loader-error lines, else a loud `PLUGIN-CANARY: FAILED` transcript line + a `state/plugin-canary-failed.txt` marker; `verify-plugin-canary.ps1` 19/19 on PS 5.1+7 incl. source-coupling locks pinning the greped literals against the plugin sources; agentic-setup `b5a89e6`.)* *(recurred: 2026-07-08 — The detector that aimed at production, and the stamp that never survived its first write; FOURTH instance: the #758 driver-alive stamp was written once by the driver entrypoint and clobbered back to 0/0.0 by `SwapDriver._phase`'s fresh-SwapState construction on the very first phase transition — every #758 part proven in isolation, the running composition never checked (live evidence: the real current.json read phase CODE, driver_pid 0 mid-battery). Instance-specific control shipped same-change: `test_driver_phase_writes_carry_the_driver_stamp` drives the real `_phase` twice and asserts `driver_alive` on both read-backs. blarai `a947865`.)* *(recurred: 2026-07-08 — The certificate that killed the night; FIFTH instance, composition-never-exercised shape: the #744 guest-oracle consumption half folded a dict certificate into scorecard evidence and the fail-closed writer refused it — every component proven in isolation, no test ever drove a folded card through the real writer, and the first production execution of that seam killed the whole battery pass. Instance-specific control shipped same-change: the exact killing certificate as a regression case through the REAL scorecard writer, plus the loop-body containment that keeps a refusal from sinking the night (see lesson 220). blarai `d0294595`.)* *(recurred: 2026-07-11 — Giving every session a way to die; `destroy_session` was built, documented by three docstrings, and test-proven, yet no production code called it — the sixth recorded instance of built-but-unwired; wired into the serve loop's session-completion path with a gate test (`test_serve_loop_invokes_the_reaper`) proving the live loop reaches the hook. #801.)*

52. **The worktree-isolation quirk can switch the main checkout's branch, so `git -C <main-path>` is not enough — verify the *branch* before every main-tree commit.** Launching background worktree builders did not merely move my shell's cwd this sprint; it switched the main checkout itself (`C:/Users/mrbla/BlarAI`) onto an EA's feature branch. So a commit I made with an explicit `git -C <main-path>` — believing the path made me safe — landed on the feature branch, not `main`, which never advanced, and I reported it as "on main." The path and the branch are independent: the path can be the main worktree while HEAD is a feature branch. The guard that holds is `git branch --show-current == main` before every commit or merge on the main tree, not the path alone. Recovery stayed inside the never-discard rule and the LA's refinement made it cleaner: preserve the stray staged reversal on a throwaway `wip/` branch, switch the checkout back to `main`, and cherry-pick the real commit — no reset, no force, nothing thrown away. The branch-guard added afterward caught the very next recurrence and blocked a wrong-branch merge. (Sharpens lesson 35.) *(recurred: 2026-07-06 — The verdict the flat queue never got to give; a dispatched worktree builder reported a clean two-file change, tests green — true relative to ITS worktree base, which was 35 commits stale, so `git diff main..branch` was 56 files / 8039 deletions and a blind `--no-ff` merge would have reverted the cert self-heal, the GPU-from-source records, and #746/#748/#749. A builder's "clean N-file diff" is only clean against its own base: before merging, diff it against CURRENT main and read the commit's own `git show --stat`, and recover a stale-based commit by cherry-pick onto fresh main. Extends the verify-branch==main control to "verify the builder's base too." #752 F4.)* *(recurred: 2026-07-11 — Mapping the sprawl before anyone moves a wall; creating the #267 branch by cd-ing the Bash tool into the main checkout and running git checkout -b switched C:/Users/mrbla/BlarAI itself off main while the file tools stayed isolated to the worktree — the same quirk via a Bash cd rather than a background-builder launch. The refused shared-checkout Write caught it; recovery stayed non-destructive (relabel HEAD back to main — both refs at cbb0bf5f, working tree untouched — then adopt the freed branch in the worktree). Path is not branch; the guard is git branch --show-current on the tree you are about to WRITE, before the write. #267.)* *(recurred: 2026-07-12 — The 6,650 deletions that weren't; the Coordinator C1 branch was 27 commits stale, so `git diff main..branch` (+4278/−6650, 77 files, #848's whole `shared/coordinator/` rendered as deletions) read as C1 "carrying its own conflicting governed-core files" — the handoff brief had inherited the wrong base's numbers and narrated them as intent. Reading the commit's OWN base..tip patch showed +3853/−8, additive; recovery was a cherry-pick onto fresh main preserving #811/#848 by construction, proven by an additions-only `git diff main..reconciled`. A proactive SUCCESS: the stale-base clause held BEFORE a bad merge this time. Fifth instance of the class; the wrong-branch shape has its branch-guard control, but the stale-base-merge shape still has no structural control — only the discipline clause — flagged as an open third-instance obligation at the 2026-07-17 fold-in.)*

55. **Never run the test suite against live user data — and the isolation a suite needs must be set before import, not in a fixture.** While verifying each merge of the at-rest encryption work, I repeatedly ran the full suite against my own live environment; a test that calls service startup resolved the real `%LOCALAPPDATA%\BlarAI\`, wrote dev-key-encrypted rows into the operator's actual `sessions.db`, and the next production launch could not decrypt them — the backend refused to start (`[7199c5ab]`). The bitter irony: the suite I was running to *verify* the test-isolation fix was itself the polluter, and it was harmless only because no real data existed yet (cf. lesson 48). The first fix — function-scope autouse fixtures — was too late: pytest imports test modules during collection, so an import-time constant like `SESSION_DB_PATH` has already resolved against the real path before any fixture runs. The durable fix is a root `conftest.py` that redirects the user-data env vars (and unsets the keystore pointer) at module load, before any import — the earliest code pytest executes — with the package fixtures kept as a second layer for call-time reads. Whenever a test process can reach real user data, redirect it at startup; never trust a fixture to guard a constant that resolved at import. (cf. lessons 2, 46.) *(recurred: 2026-07-06 — The AO that answered the socket but not the handshake; the standing gate re-minted the repo `certs/` — live runtime material a running AO depends on — *under* a live AO, orphaning its in-memory CA so every subsequent mTLS turn failed `CERTIFICATE_VERIFY_FAILED`. The lesson-55 control (redirect `LOCALAPPDATA` before import) does NOT reach it: `certs/` lives in the *repo*, not under `LOCALAPPDATA` — the isolation boundary a suite needs is "everything the running system reads at runtime," not just user-data paths. Mitigated by making the consumer self-heal (mTLS-aware readiness re-mints on reboot) since the polluting site was not yet pinned. #750.)* *(recurred: 2026-07-06 — The redirect that didn't reach the certs; the polluting site WAS pinned same-night: `launcher/tests/test_launcher.py::test_production_happy_path` drives the real `main()` whose Step 1.5 mints nine PEMs into the repo `certs/` — repo-relative state no env-var redirect covers, and a call-time-computed path the before-import mechanism cannot reach, so the fix is the other mechanism: an autouse `launcher/tests/conftest.py` fixture redirects the real mint to a tmp dir. Match the isolation mechanism to how the target resolves; the guard surface is any real writable state a test can reach, not just user-data paths. #751.)* *(control: `launcher/tests/conftest.py` autouse cert-mint redirect + two `TestPerBootCertIsolation` regression locks whose fail-fast pre-assert fails BEFORE `main()` can pollute — teeth proven by removing the redirect and watching both locks fail with `certs/` untouched; `149fd34`.)* *(recurred: 2026-07-07 — The recovery that killed the patient; a THIRD real-runtime surface no redirect covered: AO-entrypoint `service.start()` tests run the boot swap-recovery reconcile, whose empty-config fallback resolves to the box's REAL fleet root — a standing-gate run during a live battery dispatch stopped the real OVMS mid-request and stamped RECOVERED over the healthy run. Control shipped same-day: a root-conftest autouse guard stubs `reconcile_at_boot_for_roots` for every test (+ a scoped-run belt in the AO package conftest, a `real_reconcile` opt-out marker, and an identity-lock test that fails loudly if the guard is removed). #758.)*

56. **A harness that mocks the boundary the bug lives past is a unit test in integration clothing — and not knowing your own coverage is part of the coverage problem.** A green 2163-test default suite missed a one-line production-only bug: the launcher wired the gateway to the Policy Agent's port (5000) instead of the Orchestrator's (5001), so every prompt was rejected with `Unsupported message type`. The unit tests mock the seam and the bug lived in the seam. The twist that makes this governance and not just another lesson-3: BlarAI *already had* a deliberate three-layer scenario harness (#563 — dispatcher locks, real-model latency, real pywinauto window automation), and it missed the bug for the *same* reason — its dispatcher layer drives a fake gateway and its window layer a fake backend, so the real gateway→Orchestrator routing was exercised by nothing at any layer, and a `slow` marker had quietly hidden two integration files of bit-rotted tests from CI besides. And I compounded it: I told the operator the GUI had "no tests at all," having scoped my check to the C# project and forgotten the harness I had built a sprint earlier — caught only by checking the whole repo before committing the claim. Coverage is which seam a test *exercises*, never how integration-flavoured it looks; a marker that hides a test is not coverage; and a claim about your own coverage is worth as little as any other unverified claim. The fix is doctrine — `TEST_GOVERNANCE.md` §2.7: every major subsystem has a test that reaches its real production seam, it is part of "done," and minimal-human-in-the-loop is the target — because a blind spot this structural is a class to outlaw, not a bug to patch. (cf. lessons 3, 16, 30, 32.)

72. **Closing the debt a sprint exists to close is act-not-ask — escalate trade-offs, not the obvious completion of the stated goal.** Sprint 16's whole purpose was locks that *actually fire*; I found the production-parity lane (and, one layer worse, the security posture guards) sitting outside the gate that runs, named it lesson 70, and then *escalated the fix as a governance/baseline-scope decision* instead of doing it. The operator's correction was blunt — "why are you even considering not closing the debt fully? obviously that is the goal." He was right: a scope-or-baseline change with a genuine trade-off is the operator's call, but folding a just-built lock into the gate so it does its job has no trade-off — it *is* the work. Before escalating, ask whether the choice has a real downside the operator must weigh, or whether I am merely deferring the obvious completion of what the sprint set out to do. (cf. lesson 70; the Proactive-Defect-Fixing defect/decision boundary.) *(recurred: 2026-07-12 — Midnight is not a reason / An empty queue is a broken queue; running the overnight coordinator role, the same over-caution recurred four times in one night and was corrected four times — deferring a diagnosed, in-scope, night-blocking cert fix as "not a 1am hack" (the clock is not a root cause: a manufactured CATEGORY laundering a deferral the merits could not justify), routing a GPU-context-release nuance to the non-technical operator (own the HOW, escalate only the WHY — cf. lesson 99), writing "I'll hold committing" on a PRE-APPROVED ADR, and sitting idle behind in-flight work with a docs queue untouched. The unifying boundary is decision-versus-defect: a genuine decision (capability/quality/security posture) escalates WITH a recommendation; pre-approved / reversible / diagnosed / in-scope work is executed and reported. Over-deferral is a failure mode with the SAME standing as over-reach — a dropped responsibility wearing safety's clothes. #863/#859/#864.)*

97. **A security control must not claim more than it delivers.** When code documents a protection — zeroization, isolation, validation — the comment is a claim a future reader will trust, and if the implementation cannot honour it the honest move is to say so plainly and point at where the real mitigation is tracked. The #611 study found the DEK break-glass recovery ceremony "zeroizing" recovered key material with `recovery_key = bytes(len(recovery_key))`, which merely rebinds the name to a fresh zero buffer and leaves the original immutable `bytes` in the heap until GC; the governance-honest fix was to correct the comments to the true (weak) guarantee rather than change the code to *look* like it zeroizes, because in pure Python you cannot overwrite an immutable backing store and re-asserting the false claim with more confidence is the worse move. An overclaiming control is worse than an absent one, because it buys false confidence. (cf. lessons 47, 51.) *(recurred: 2026-07-05 — The seal that covered less than the docstring claimed; the M2 `PlanStore` docstring promised whole-artifact tamper-refusal while the hash it verified covered only `{goal, tasks-minus-status}`, leaving the job `oracle_path`, repo, and budget ceilings to load tamper-free — a redirected oracle_path is a textbook FALSE-DONE. Widened the seal to the full immutable identity AND restated the honest guarantee (persisted status is ADVISORY; re-derive done-ness from a fresh oracle run) — a whole-artifact hash was never possible without self-invalidating on the system's own writes. Control ships with it: the H3 tamper/advisory tests + the W9 reference-hash lock. #740.)*

99. **A decision is only a decision if the options differ on security, capability, or quality — otherwise it is mechanics the builder owns.** Handing a novice operator an implementation choice with no governance delta inverts the responsibility the agent is paid to carry, and costs the operator exactly the involvement he is trying to minimize: scoping the #649 Windows-Hello biometric verifier, the route (a tiny C# helper subprocess versus an in-process WinRT binding) changed nothing the operator governs, and the only fork with a real posture delta — adding a new runtime dependency — had an obvious answer under this project's supply-chain posture (don't; the `net8.0-windows10.0.19041.0` `UserConsentVerifier` the WinUI already targets needs no new wheel). The check is cheap: name what each option changes for the operator; if the answer is "nothing he governs," decide, state the call, and keep moving. (cf. lessons 29, 38, 66.)

111. **When you add the first instance of a capability a system was built to forbid, build the seam before the feature** — one guarded door every future caller must pass through, not a socket per feature — and encode the new posture as an ADR amendment, not just code, when it moves where a human gate sits. Two corollaries paid for themselves here: (1) a registration seam with **no** default wired is the honest fail-closed shape when no real in-process authority exists to call — ship the documented TODO, never a fabricated verdict; and (2) a fail-closed control will fight the legitimate use it's meant to allow the moment a real client behaves normally (an HTTP client connects to a resolved IP, not a name) — the fix is to teach the control about the legitimate path narrowly (pin the resolved IP, at the allowlisted port only, dropped on revoke) without ever loosening deny-by-default for everything else. Close an SSRF in both the layer that resolves and the layer that connects — a named host that resolves internal must be refused at the resolver (don't pin the internal IP) *and* re-checked at the door (resolve-and-recheck before any widen), because neither layer alone covers the other's blind spot. And when a fix narrows a class of attack without closing it — DNS rebinding here — name the residual and the robust fix (a peer-IP-validating transport) in code and journal rather than implying full coverage; a half-closed hole you've documented is honest, a half-closed hole you've implied is closed is a trap for the next reader.

124. **Build the door, but make opening it a separate, single, reviewed act.** When a capability is dangerous to activate (here: the first real egress off an air-gapped box), wire it fully and unit-test the wiring, but leave the activation as one uncalled line with the trade-off named — never let "I built it" quietly become "I turned it on." The egress door denies until a consumer registers an adjudicator; building that adjudicator and declining to register it kept the air-gap provably intact while the corridor behind it was finished.

139. **Name the control you actually have, not the one that sounds reassuring.** The instinct on an "uncensored image generator" is to bolt on a content classifier so the project can say it has a guardrail; the honest answer is that a *local* classifier cannot hold the one boundary that matters (no distributable hash database for it, a prompt denylist bypassable three ways while it false-refuses legitimate prompts) and would be memory-costly against a tight ceiling and privacy-invasive against the operator's own output. ADR-033 says the true thing instead, and the go-live ceremony makes it mean something: the boundary is named explicitly, it is a recorded ACCEPTED-RISK the operator *signs sole responsibility* for, the control is governance plus a one-time attestation, and the consequences are bounded structurally (operator-initiated, audited, no-egress, no-distribution). That puts accountability where it actually lives rather than pretending a local model can adjudicate legality. Writing "robust local technical control here is not achievable" into a security ADR feels wrong until you realize the alternative is writing a comforting lie into one — a fiction in a security document is worse than a named, accepted, structurally-bounded, operator-signed risk. (cf. lessons 97, 105.) *(recurred: 2026-07-14 — the agentic-setup-public go-live content pass. Floated an automated "flag private IP addresses" leak-gate pattern as a follow-up hardening idea, then read the actual flagged content and declined to build it: the same reference library legitimately teaches private-IP examples throughout (nginx upstream pools, routing tables), so a private-IP regex would fire on correct, benign content every future publish — indistinguishable from the local content classifier's false-refusal problem, a control that sounds like coverage but can't discriminate. The manual pre-ceremony read that had already caught the one real ambiguity (and separately caught me overcalling it as a live personal disclosure when full-file context showed it was copied third-party example syntax) was the control that actually worked; the fix that shipped was narrowing one example line, not adding a scanner rule. No repo/ticket — ops judgment call, recorded here.)*

149. **A hand-copied cross-language allowlist drifts in silence — guard it with a gate test, not vigilance.** When a set must be mirrored across a language boundary that cannot share a literal — here a WinUI C# `BackendPassthroughCommands` array mirroring the Python-side command set — the mirror is a manual copy with no enforcement, and a missing entry fails *quietly* (the command is handled host-side or errors, no crash, no log). Vigilance is not a control: the array dropped a shipped command twice. The durable fix names ONE source of truth and writes a gate-time test that parses the mirror out of the *other* language's source as text (stripping comments so a mentioned-but-unlisted token isn't miscounted) and fails loudly, naming the specific missing element — and you verify the gate has teeth by simulating a drop and watching it go red before trusting it. A red test is the control; a human remembering to edit two files is not. (cf. lessons 147, 56.) *(recurred: 2026-07-04 — Scoring the words, not just the verdicts; the answer-quality leak checks nearly committed pasted system-prompt fragments into golden data — resolved by the stronger arm of the same class: derive the evidence from the imported production artifact at runtime, so there is no copy left to drift)* *(recurred: 2026-07-11 — One recipe, three consumers, now one source; #822 made grade_env.py the SSOT for the clean-environment grading recipe and host-locked the guest twin to it, but #821's oracle_qa.py still carried its OWN inline copy — two consumers drift-locked, one free to drift, a latent drift no per-consumer test catches because each copy passes its own tests. #839 folded oracle_qa onto grade_env (preserving its one deliberate PYTHONPATH-prepend deviation, byte-behaviour-identical) and extended the drift-lock to assert host grade_env == guest execute_snapshot == oracle_qa as ONE lock. An SSOT is only single while EVERY consumer is equality-locked to it; consolidating onto a shared source must add or extend a parity lock spanning ALL N consumers, not N-1. #839.)* *(recurred: 2026-07-15 — The ceremony found its own missing wire; the /coord command was never added to `shared/ipc/slash_commands.py`, so the hand-copied C# mirror lacked it and the parity gate — whose whole purpose is catching exactly this — had nothing to enforce: a net with the right shape hung on the wrong hook. Third command-drop instance (/imagine and /images were the first two). The gate is only as good as the SSOT feeding it; the fix wired the constant + mirror together so the gate covers /coord permanently, and lesson 266 adds the operator-keystroke acceptance leg — but the upstream intake (a NEW command landing in the SSOT constant at all) still relies on convention, not a control. #887 arc, merge b91af91e.)* *(recurred: 2026-07-15 — The static-page fix that only half-existed in each repo; `repo_will_scaffold` (Python) mirrored the fleet's real `$hasProj` gate (PowerShell `Get-ChildItem -Recurse`) with a shallow glob — divergent only on a marker buried two-plus directories deep, where the card over-claimed coverage for checks that never run. One line (`glob`→`rglob`) plus a regression test pinning the deep-monorepo shape; the "mirrors X" docstring is the first thing to lie when X changes. #888.)*

150. **A test double standing in for an async object must itself be async, or it proves a path production never runs.** The gallery's new dispatcher RPCs were modelled on the sync `_resolve_generated_image` (`asyncio.to_thread(fn, arg)`), but copied onto the gateway's `async def` list/manage legs that runs the async function in a worker thread and returns an *un-awaited coroutine*, which the JSON encoder refused and the fail-closed path turned into an empty list — so inline render (sync) worked while the gallery (async) silently showed nothing. Thirteen green dispatcher tests missed it because the `_FakeGateway` legs were synchronous `def`, so `to_thread` worked fine and the suite validated a path production never executes — the frozen-dataclass mock-shape divergence from this project's early days, back in a new costume. A fake's method signatures (sync vs async, return types, raised exceptions) are part of the contract under test, not incidental scaffolding; mirror the real shape including await-ability, and where the shape is the very thing that can go wrong, make the double the strictest possible version of the real contract so the bug becomes a red test, not a production surprise. (cf. lessons 114, 90.)

160. **The log decides, not the hypothesis — verify the failure mechanism before you fix it.** The run-2 swap hang *looked* like a GPU out-of-memory: this box's 16 GB iGPU can't hold the 14B and 30B together, the symptom was a stuck load, and that mechanism was held confidently. But the OVMS log showed the 30B reaching AVAILABLE in thirty seconds with a zero-byte error log — a clean, successful load — and the real cause was elsewhere entirely: a captured-subprocess-pipe deadlock that hung the driver *after* the model was ready. Fixing the GPU would have shipped a real change against a non-existent bug and left the actual deadlock in place. A plausible failure mechanism is a hypothesis to test against the evidence, not a conclusion to build a fix on; read the log the system actually wrote before you touch the code. (cf. lessons 154, 158.)

188. **Re-verify an external contract against the live service before depending on it, not against the docs.** Kagi's v0 endpoint was documented, proven-shape, and coupling-tested — and deprecated; it 401'd the instant the governed egress chain first opened. Every axis of an external API (URL, method, auth scheme, body shape, response shape) is a fact that can rot between "built dormant" and "go live," and only a live probe with the real credential settles it. The controls around the call were all correct; the inherited fact about the call was the whole defect. (#719.) *(recurred: 2026-06-29 — The version-lag that closed onto a deeper wall; the EAGLE-3 exporter "existed" but could not load the published checkpoints, and `guidance_rescale` shipped in the notes yet was absent from the API)* *(recurred: 2026-07-03 — The deck the fold forgot...; Chrome/Edge 149 emit no console output where v137 did)* *(THIRD INSTANCE — structural control SHIPPED 2026-07-06: the external-contract probe registry + gate test (`shared/security/external_probes.py`, `services/assistant_orchestrator/src/websearch/probe.py`, `tests/security/test_external_probe_registry.py`, +8) — any module reaching the egress door must enroll a `--probe` entrypoint or the standing gate refuses it, and each probe fires through the real door (no second network client). The per-instance follow-up #735 remains for the two out-of-repo cases (the EAGLE-3 exporter, the browser console harness); #739 is the unified in-repo enforcement. See the 2026-07-06 entry "The third time it broke, I built the thing that checks.")* *(recurred: 2026-07-07 — Two protocols share an acronym; one of them points at a graveyard; the PRE-ADOPTION grain of the class: before adopting an external STANDARD, verify the standard itself is alive — IBM's Agent Communication Protocol had been merged away into A2A for eleven months, repos archived, and acronym-familiarity alone would have built on a dead spec; the near-miss cost nothing only because the liveness check preceded adoption. #759.)*

216. **A recovery path is a loaded weapon pointed at whatever it believes crashed — it must verify the death, not infer it from its own start.** The AO's boot reconciler presumed "I am booting while a swap is in flight, therefore the swap crashed" and converged the box: stopped OVMS, disarmed the sentinel, stamped RECOVERED. The presumption is false whenever a recoverer starts beside a HEALTHY peer — here a pytest run booting AO service objects while a live dispatch coded (and, latent, the operator opening the app mid-battery) — and the "recovery" then destroys the thing it exists to protect: OVMS was killed mid-request under a working coder, and the terminal stamp falsely completed the monitor. Any "if I am starting, the other party must be dead" reconciler eventually meets a live peer. The fix is identity plus liveness, fail-closed to recovery: the driver stamps its pid + process-create-time into the swap state at takeover, and the reconciler probes it (create-time match defeats pid reuse; unprobeable ⇒ recover, so a genuinely crashed swap is never stranded) — a live driver gets hands-off and an honest "still running" report. (#758; cf. lessons 55, 213, C16.) *(recurred: 2026-07-08 — The detector that aimed at production; the root-conftest port-5001 leak detector made the same presumption one door over: "the port went free→held during my run, therefore a test leaked it" — false whenever a live battery job's teardown restores the AO mid-gate — and its self-heal TREE-KILLED the pids holding the port, putting the production AO on the kill list (no-op by luck). Fixed: the verdict is fleet-swap-aware (a read-only swap-state fingerprint at session start/end; a dispatch cycle during the session explains free→held) and the kill only touches pids descending from the pytest session itself. blarai `2015c4d`.)* *(recurred: 2026-07-09 — The detector that doomed the verify, and the zombie it left behind; THIRD INSTANCE — the battery monitor's doom detector made the silence-means-death presumption one layer up: 90 seconds of quiet logs and no watched process read as a dead run while the verify gate was legitimately silent inside its own granted 600s budget (write-at-completion checks, unwatched native `uv`/`ruff` workers), and the kill destroyed the healthy B4 it existed to protect. Control shipped with the tally: the verify workers joined `_CODER_PROC_NAMES`, the doom window rose 90→240s across all four default sites with a sibling-drift lock binding them, the exact B4 repro locked both sides (DOOMED-at-90 / WAITING-at-240), and the window is registered in `shared/timeout_registry.py` with the incident + the shrink path (a per-step heartbeat from verify-project.ps1). The class-level distillation is lesson 221. blarai `8a9e725d`.)*

217. **Configuration values that accrete one incident at a time form an invisible taxonomy — when a value CLASS earns its third scar, give the class a registered, gate-locked table.** Every timeout in the system was paid for by a specific incident (the 120→180 vision-turn raise, the #757 run-budget tree-kill, the #766 cold-PLAN hangup), each lives where its consumer lives, each carries its story only in a docstring — so sibling values drift unnoticed (the registry's own seeding inventory caught `monitor.py` still defaulting 5400 the same morning the #757 sweep moved its family to 10800), newcomers rediscover the map constant by constant, and nobody owns the question "can this number shrink or die?" The control shape: one table per value class — each value with the incident that justified it and the condition that would retire it — with a DRIFT lock binding every row to its live constant by import, a DISCOVERY lock so a new member must register or explicitly backlog (never land invisibly), a QUALITY lock (no number without its story), and a standing review cadence that asks shrink-or-retire per row. The table is TEETH, not a config source: moving the constants themselves would churn every live surface at once, while cross-checking them lets the taxonomy become visible without a big-bang migration. A registry that silently covers 40% of reality while implying 100% is the C14 class in a new hat — the backlog is public, in the module, on purpose. Sibling of lesson 195 (era-rot re-measures ONE value; this governs the CLASS). (`shared/timeout_registry.py` + 11 gate locks; #767 carries the promotion/consolidation/shrink/retire program; LESSONS rule 5 amended to walk the table quarterly.)

219. **A process-creation control can be defeated by an intermediary the platform inserts between you and the process you think you are spawning — verify the observable end property, never the flag at the spawn site.** The swap chain's DETACHED_PROCESS flag was verified at every spawn site and the operator still screenshotted a closable console: the Windows venv `python.exe` is a launcher shim that re-spawns the real interpreter as a *child*, and the flag does not inherit — it worked, one process too early. The pythonw fix then proved the lesson's second half live: twelve fresh unit locks pinned the argv and flags faithfully, and the first live swap-back still crashed, because the relaunch had never passed standard handles and the old visible console — the bug itself — had been silently providing working stdio; remove the window and the child inherits a broken cp1252 stderr that kills the banner print. Both halves are one discipline: the property the control exists for (no closable window; the assistant comes back) lives at the end of a chain the platform quietly extends, so the merge gate must observe the END PROPERTY on the final process in the real environment — and when a change inverts the environment (a console-less parent), re-derive the hazard for every child and every assumption ("a stray print is a silent no-op" was false) rather than porting the old analysis. (#761; the C15 sweep + the live merge gate; cf. lessons 46, 73, 218; FIELD_NOTES: the venv-shim/pythonw/CREATE_NO_WINDOW triad.) *(recurred: 2026-07-09 — The five scars, collected into one door; the class earned its structural control.)* *(control: the blessed spawn seam — `shared/procspawn.py` + agentic-setup `scripts/spawn-lib.ps1`, every rule carrying its incident citation, proven by positive-control conformance suites that assert each observable end property on a REAL child — GetConsoleWindow==NULL on the final process, unicode round-trip on both streams, child+grandchild dead after tree-kill; `test_procspawn.py` 9/9 + `verify-spawn-lib.ps1` 18/18. #774.)* *(recurred: 2026-07-10 — The \"clear RAM\" button that only knew half the RAM; a new stop site (`stop-assistant.ps1`) routed its tree-kill through the blessed `Stop-ProcessTree` seam instead of a hand-rolled `taskkill`, pid-confirming a genuine `-m launcher` before killing, with a positive control asserting parent+grandchild dead and a non-launcher decoy left alive. #797.)*

221. **When one component's watchdog window overlaps another component's granted budget, the shorter window silently wins and the budget is fiction — every liveness window must be provably longer than the longest legitimately-silent phase it can observe, or the phase must emit a heartbeat.** The battery monitor's 90-second no-progress doom sat inside the verify gate's own 600-second budget: the gate's checks write nothing until they finish and its native workers were absent from the watched-process names, so a working verify was indistinguishable from a dead run — and the monitor killed a healthy B4 at one-seventh of the time the pipeline had explicitly promised the step. Neither number was wrong in isolation; the PAIR was incoherent, and nothing owned the question. The durable discipline: audit (window, budget) as a unit whenever either changes — enumerate every legitimately-silent phase the window can observe and prove the window exceeds the longest one, or give that phase a heartbeat so the window can stay tight. The timeout-registry row carries both the raised window and the named shrink path (a per-step heartbeat from the verify gate), so the pair stays visible instead of re-diverging one incident at a time. (The detector that doomed the verify, 2026-07-09; #740 c.1517; sibling of lesson 217 — the registry makes the values visible; this governs their COMPOSITION; cf. lessons 213, 216.) *(recurred: 2026-07-11 — Running is not ready; #744's guest-oracle service-readiness wait lengthens the teardown window that the battery monitor, the run budgets, and the VM-footprint spec all observe — every (window, budget) pair was enumerated and either proven to fit or named in the registry row before the budget shipped. #744.)* *(recurred: 2026-07-11 — The boot that promised three minutes and granted eighteen seconds; the Boot-Phase-3 PA-handshake aggregate (~15-18 s) sat inside the system's own documented 180 s cold-14B ceiling and nothing owned the pair until the audit read both numbers together; widened to a 180 s capped-exponential schedule. #808.)* *(THIRD INSTANCE — control shipped with the tally: the registry relation lock binding `PA_HANDSHAKE_BUDGET_S >= real_backend_ready(timeout_s)` plus a shared schedule function that makes the TUI banner and the retry loop one arithmetic, and both new budgets registered in `shared/timeout_registry.py`. #808.)* *(recurred: 2026-07-15 — The nightly ceiling was sized for five jobs while six ran; the scheduled task's PT16H `ExecutionTimeLimit` (hand-typed for FIVE jobs after the PT10H tree-kill) sat ~3 h under the runner's real six-job worst case — the outer window an un-importable, un-registerable Task Scheduler value. The refinement: an outer bound hand-typed rather than DERIVED from the inner budgets it must dominate will silently drift under them the moment the inner set changes; deriving beats documenting. Control shipped with the tally: `tools/dispatch_harness/battery_execution_limit.py` derives the floor from the runner's own constants, `verify-battery-task-settings.ps1` reads the live task and fails loud on drift, and a BACKLOG registry row names the pair for the quarterly walk. #833.)*

222. **A verdict-issuing instrument needs a positive control before its failure class is believed — prove it can produce PASS on a known-good subject under production conditions, or every systematic blindness it has becomes a fleet of plausible failures wearing measurement's authority.** The web design-verify screenshotted apps over `file://`, where browsers block module JavaScript entirely — and the fleet's own web scaffold is a module app, so the instrument could not EVER see a working app: B5's coder built a working habit tracker (proven by serving the same merged code over its own server) and was convicted as a capability failure by a reviewer accurately describing a page that could never live. Nothing had ever demonstrated the tier could pass a known-good app, so its reds carried authority they had not earned — and "the coder can't build charts" nearly entered the capability ledger as a measured fact. Negative controls (B8's rigged tasks) catch false green; only a positive control catches false red. When an instrument's verdicts feed decisions, budget the run that proves it can say yes. (The screenshot that convicted an innocent app, 2026-07-09; #772; cf. lessons 2, 30, 215, 221.) *(recurred: 2026-07-10 — The slowdown that was three measurement bugs in a coat; the S5 \"spec-decode net-negative on short turns\" scare stacked nonce prompts a 0.6B draft cannot predict, an acceptance metric read off a nonexistent API method, and non-interleaved thermal drift — the dedicated A/B measured spec-decode 1.48–1.68x POSITIVE on both shapes and lossless-greedy; ADR-012 unchanged. #778.)* *(recurred: 2026-07-11 — Teaching the battery to name its own leaks; #827's failure-taxonomy classifier is itself a verdict-issuing instrument, so its classes are not believed until it reproduces the known answer on a known subject — the 9 hand-classified job-instances are its positive control (`test_failure_taxonomy.py`), and a golden falling to UNCLASSIFIED is a caught regression. #827.)* *(recurred: 2026-07-11 — Auditing the auditor; #828's mutation-scorer positive control (\"every operator class must produce a mutation site on a fixture that has one of each\") caught a dead operator branch a negative-only suite would have missed — grading tools need positive controls exactly as much as the graded code does. #828.)* *(recurred: 2026-07-11 — Who audits the GREENs; #837's GREEN-QUALITY audit is hermetically reconstructed as fixtures that reproduce the dossier analyst's own B/B/C ranking of the three real B2 archives — its positive control carried even where the archives are absent. #837.)* *(control: the positive-control discipline made structural across the grading-instrument fleet at the class's third instance — every verdict/annotation instrument built in the #819–#838 QUALITY program ships a positive-control test that proves it produces the known answer on a known-good subject (`test_failure_taxonomy.py` 9 goldens, `oracle_mutation` one-of-each fixture, `green_quality` seed proof). #827/#828/#837.)*

257. **When a design gives an agentic system visibility into or influence over its own backlog, roadmap, or configuration, prove the self-targeted branch is structurally SEVERED, not merely approval-gated.** The Coordinator program widened BlarAI's mandate to reading its own development backlog and proposing the next work — and combined with a dispatchable coding fleet, "propose work on your own backlog" is one approval away from "dispatch a coder against your own code": a self-modification loop wearing a project-management badge, and I had documented the blend in my own C4 text as a feature. Approval gates are VIGILANCE controls, and vigilance does not survive handing the system to the non-technical operators the program is aimed at — who cannot audit what they approve. So the design splits a governed core (everything defining what BlarAI is — writable only through the human dev channel) from a workspace (what it coordinates), enforced by structural controls: staging-time refusal of any governed-core target, advisory-only self-work under a provenance marking BlarAI's own dispatch path categorically refuses, config immutability from inside, signed-policy-verified-at-boot, default-deny multi-operator — generalising the one chokepoint that already existed (_FORBIDDEN_REPO_ROOTS refusing BlarAI as a fleet target) into doctrine. The review that catches a capability's shadow must ask not "what can this DO" but "what does this let the system do to ITSELF," and trace the execution path from propose to act to prove the self-branch is severed by construction. (ADR-039 / #841; the mirror lesson rides the same arc — a governance-first designer under-designs capability exactly as a capability-first designer under-designs governance, and the review that catches one won't catch the other unless someone asks both questions. cf. lessons 44, 236; C13/C19/C20.)*


## Index of every lesson (the pre-mint search surface)

*One line per lesson — search HERE before minting a number (Rule 2). ↺n = recorded recurrences · ✓ctrl = a structural control shipped · ✓ctrl(partial) = a control exists but a named sub-class of the lesson escapes it, with that gap ticketed · ⚠debt(#N) = a third-instance control is OWED and tracked on #N; the debt is visible here so a Rule-3 pass finds it without opening another lesson · ★ = Canon-32. Full text: the archive volume.*

1. Process is not progress  · ★
2. "Show me it running."  · ★
3. A green test suite is only as honest as its assumptions  · ↺1 ★
4. Build the smallest thing that genuinely runs, then grow
5. Read the rules, not just the task
6. What you configure is not what runs
7. A measurement can flatter you
8. Fixing the instrument once does not make it trustworthy  · ↺5 ✓ctrl ★
9. Two Claudes on one machine share one HEAD
10. Continuity of intent across agents is a file-system property, not a memory property  · ↺1 ★
11. A setting that must cross a privilege boundary has to travel by a channel that crosses it
12. Build the surface to the shape of the capability you are about to add, and the capability becomes a backend swap instead of a UI rewrite
13. Provenance is not trust: your own stored data can still carry an attack  · ★
14. A handoff brief is a map, not proof the terrain is passable — probe the load-bearing unknowns before building on them  · ↺2 ✓ctrl ★
15. Routing around a broken tool beats fixing it, when the tool is not on your path
16. For the layer your tests cannot reach, instrument it — do not guess across the boundary
17. A decision can be right for a reason that is false — re-test the rationale, not just the result
18. A security design is only as real as the hardware it assumes — verify the silicon, not the spec sheet or your own inference
19. Sell the capability you have, not the one they hope for — name the limits before they build on them
20. The privilege-lowering fix and the capability fix can be the same change
21. Verify the artifact, not just the data inside it — with the real tool, not a proxy
22. Fail-closed is not fail-shut: a deny-by-default control must still enumerate — and prove — the legitimate-allow set  · ★
23. A capability proven is not a control enforced — a finding closes when production points at the strong path and the weak one is gone
24. A problem the live boot surfaces next to your change makes the change a suspect, not a culprit — let the instrument decide before you reach for the fix
25. One shared event loop makes any single blocking call a whole-app freeze — fix it structurally (off the loop), not locally (make the blocker faster)
26. On-demand and context-aware beats eager and generic — and a subordinate model's answer is data, not instruction
27. A deferred resource risk comes due as a hard failure, not a graceful one — and a fail-closed default can disguise it as another subsystem's bug
28. The safest feature flag is the fail-soft path you already built — disable-by-config and degrade-by-failure should be one code path
29. Escalate what the user experiences; own how it is wired — a quality or capability tradeoff is the operator's call, never an implementation detail you slip in  · ★
30. A guard you have not watched go red against the bug is decoration — and a bug in the interaction between parts is invisible to tests that exercise each part alone  · ↺1 ★
31. Fix the symptom with a bound; fix the cause when the bound lets you
32. The layer you call "untestable" is usually just "untested" — hunt for the seam before you fence it off
33. Capturing data and publishing data are two separate disciplines — and a record that implies more coverage than it has is worse than none at all  · ↺1
34. A prefix or allow/deny check on a path you did not canonicalize is a bypass waiting to be typed
35. Verify the merge landed where you meant it to — a shell's working directory can drift, and a loop's "OK" echo is not proof
36. An over-eager control is a regression wearing a security badge — re-enabling a disabled control is not automatically safe
37. A cost measured in isolation can be a cost the running system never pays — profile the component where it lives, not on a bench by itself  · ★
38. When the operator's gut says a design is wrong, that is a design-review trigger — re-derive from best practice, do not defend the as-built  · ↺1 ★
39. A locked decision can stay right while the evidence under it quietly rots — re-measure a premise when the stack beneath it moves, not just when you revisit the decision
40. Reuse the commodity, harvest the method, refuse the framework — a network-touching dependency is a supply-chain liability you import on purpose  · ↺1
41. To land on a branch others are actively pushing to, use an operation that can only fast-forward — it refuses rather than races
42. A coordination discipline that works for one actor becomes the bottleneck when many run at once — scale the mechanism, not just the rule
43. A component's primary purpose is fixed by its use case, not by the sprint you happen to be viewing it through
44. A safety control that depends on a human remembering to do the right thing is not a control  · ↺1 ✓ctrl
45. When a mess keeps reappearing, find the doctrine producing it before you clean it up again  · ↺1
46. A control wired into a function but not into the boot path is still "built but wired into nothing" — a green suite proves the mechanism, never that the running system invokes it  · ↺7 ✓ctrl ★
47. A comment that claims a property the code does not enforce is governance debt that surfaces later as an audit finding  · ↺3 ✓ctrl
48. A load-bearing factual premise gets verified on disk, not inherited through the review chain  · ↺4 ✓ctrl
49. A design gate — the ADR written and reviewed before a line of cipher code — turns the hard seam-choices into translation work, and moves the review surface from the code to the ADR
50. Encrypt the derived representations, not just the raw text — a stored embedding is an invertible shadow of its source
51. Tamper-evident is not non-forgeable, and the difference belongs in a test, not a comment
52. The worktree-isolation quirk can switch the main checkout's branch, so `git -C <main-path>` is not enough — verify the *branch* before every main-tree commit  · ↺4 ★
53. A break-glass recovery path must be correct by design and proven against a dead chip, never correct by accident
54. A factory that reads missing configuration as "dev mode" turns a misconfiguration into a silent downgrade to the weakest posture
55. Never run the test suite against live user data — and the isolation a suite needs must be set before import, not in a fixture  · ↺3 ✓ctrl ★
56. A harness that mocks the boundary the bug lives past is a unit test in integration clothing — and not knowing your own coverage is part of the coverage problem  · ★
57. A control built but never issued its key material is half-armed, which is to say off
58. A side effect placed before the point a process can still fork-and-exit runs more than once
59. Build the mechanism and pin the sentinel before you throw the switch — an unactivated mechanism is a deferred bug, and the test suite is what defines "safe" before you flip the bit
60. Off-chip structural proofs and on-chip ceremony verification are distinct work with distinct value — stub data does not cheapen the structural proof
61. Transport topology and security mechanism are orthogonal decisions — conflating them leaves the real production path unbuilt behind a fully-specified one
62. Config-to-provisioner correspondence must be tested as a unit, or the gap surfaces only at production boot
63. Fail-closed is a property of a call site relative to its unit of accountability, not a uniform property of a component
64. When you fix a defect of a particular shape, scan the codebase for the same shape before you close — finding one and fixing only one is a half-fix  · ↺2 ✓ctrl
65. A correct downstream fix can mask an upstream defect by moving its symptom past the gate that used to catch it — so test the seam between configuration and connection, not each side alone
66. A test can lock a *defect*, not just a feature — so "it's test-locked" is not proof "it's a decision to escalate."
67. An integrity check on a multi-file artifact must cover the whole manifest — and reject whatever the manifest omits
68. A lock you cannot run green yet must still verify everything the missing resource does not gate — so its first real run is a confirmation, not a discovery
69. A gate checklist never re-verified against the code drifts in both directions
70. A regression lock only locks if the gate that actually runs includes its scope
71. Version pins are containment, not supply-chain integrity
72. Closing the debt a sprint exists to close is act-not-ask — escalate trade-offs, not the obvious completion of the stated goal  · ↺2 ★
73. A long-"deferred" code path is where bugs hide from each other — activating it is a discovery exercise, not a one-liner
74. A `@hardware`/`@slow` tier must SKIP on every axis it needs, not just the headline one
75. Cross-stream seams that merge separately must connect by registration, not by import
76. Put a carve-out where the rule actually fires, not where its name says it lives  · ↺1
77. A red test is a claim about your test before it is a claim about the code  · ↺1
78. Mechanism-exists is not disaster-tested — the missing catastrophe test is the actual deliverable
79. A static config lock and a runtime posture guard are not redundant — they catch different regressions
80. A frozen-dataclass exception type masks an unexpected raise behind a confusing secondary error
81. A posture test must own the outcome it asserts on, not borrow it from the environment
82. Verify an alarming conclusion against the evidence you already have before you escalate it — a symptom read correctly can still yield a wrong conclusion
83. A WinUI element is in the UI-Automation tree only when THREE separate conditions hold — and when one is missing, instrument the tree before theorising
84. A sequencing or packing choice that changes nothing built is the orchestrator's to own, not a fork to hand the operator — and offering "or we defer half" reads as proposing they stop short
85. Schedule the human's understanding pass BEFORE the irreversible decision, not after — with a remediation loop so what they learn can still change the outcome
86. Automate by default; a human step must be proven necessary, not inherited from a runbook's wording
87. A process leak that makes tests defensively skip looks like correct behaviour — verify the resource was released by a separate mechanism, because a stable skip count is not a safety net
88. A `dev_mode` round-trip proves the routing, not the posture — and the gap between them is the seam production burns on
89. Reference paths are for reading; writes go to the worktree — verify the file landed where the branch lives, not just that the branch is right
90. A mocked seam plus a standalone test of the seamed component do not cover the path that connects them — only a test that drives both in sequence does
91. Reconcile a large audit with parallel adversarial verifiers, then resolve their disagreements on disk — never average the verdicts
92. The bug lives in the seam, not the parts  · ↺1
93. Wiring a guard onto a hot path means asking what legitimate traffic it will see, not just what it is meant to catch
94. A merged capability is not an activated one — say which it is
95. An activated control is not an exercised one — verify it against the real producers, not assumed ones
96. Prove the property on the load-bearing artifact, not an equivalent of it
97. A security control must not claim more than it delivers  · ↺1 ★
98. When a read contradicts the premise of your task, the read wins — pause before you write
99. A decision is only a decision if the options differ on security, capability, or quality — otherwise it is mechanics the builder owns  · ★
100. An "unbounded by default" comment is often an unclosed gap wearing a decision's clothes
101. Strip authority with an allowlist, not a denylist — and know which lever you're pulling
102. Reuse the project's canonical approval primitive instead of minting a second one
103. Verify the vocabulary you teach against the current source before you teach it
104. An audit log is the one at-rest store where signed-plaintext beats encryption
105. Demonstrating a capability is not deciding to deploy it — a proof-of-concept that ends in a deliberate "no" is a success, not a waste
106. The only secret you can truly erase is a mutable one
107. A "gate-blocking residual" must be reconciled against disk before it drives the plan
108. A security artifact built on an active tree is stale the day after it ships
109. Sanitization order is a verdict-integrity property, not a style choice
110. A deterministic hash of secret content is content metadata, not a label
111. When you add the first instance of a capability a system was built to forbid, build the seam before the feature  · ★
112. Audit the request side of every interception seam, not just the reply side
113. Parallel sessions that each author "Amendment N" to the same ADR collide silently
114. A test double must preserve the variance the assertion depends on
115. When an ADR rejects an alternative that might come back, *hold* it explicitly
116. An ownership-conditional cleanup ("only release what I acquired") is a ratchet whenever the ownership flag can latch off from a transient event
117. A green fit-check can certify an unreadable artifact — gate on the property, not the mechanism
118. When an exception class subclasses a builtin, every `except` of the subclass is a claim that the base class cannot reach that spot
119. A passing test suite proves the code does what the tests ask, never that the tests ask the right question
120. When a transport's bootstrap dependency lives on the far side of the transport itself, stop trying to automate the first hop
121. At a security boundary, prefer a wire format with exactly one legal encoding per payload
122. A runtime pinned below a capability its own new feature needs is a version-bridge problem, not a migration problem
123. A control proven in a harness that relaxes its own environment is not proven
124. Build the door, but make opening it a separate, single, reviewed act  · ★
125. Your confident technical answer is a hypothesis until the disk confirms it — and verifying often reveals the work was already done
126. A host/guest runbook is unproven until the real console runs it
127. Rewriting a file the hypervisor holds open creates a new object — re-grant its ACLs, because the permissions that made it work do not follow the path
128. Dynamic Memory reclaim is set by the floor and the measured demand, not by the ceiling
129. When a feature carries the same content in two fields — an edit buffer and a render field — a visibility toggle that swaps which one is shown will silently display the stale one unless you sync on the transition
130. A regex escaper is only as safe as its parity with the consumer that renders its output  · ↺2 ✓ctrl
131. Before inventing a new transport for a feature, check whether an existing idempotent/dedup contract already carries it
132. When two individually-correct controls collide, add a tier, don't lower a bar  · ↺1
133. Verify the backend before scoping the backend
134. A regex's parity with its consumer includes the regex engine's own dialect, not just the pattern
135. Fail-closed is only *proven* when you watch the control refuse under the exact failure it was built for
136. One threshold can need two predicates, split by who owns the fail-closed  · ↺1
137. A policy decision rewrites the test surface, not just the code
138. When a security primitive doesn't fit the new artifact, add a sibling — don't bend the locked one
139. Name the control you actually have, not the one that sounds reassuring  · ↺1 ★
140. When a value cannot fit the transport frame, model the new chunked channel on the proven one — and pin the cap with a coupling-lock
141. A hardening that touches a shared primitive must be scoped to the path that needs it  · ↺1
142. A docstring that names the wrong control as load-bearing is a defect, not a nicety
143. Least authority is a default, not a dogma
144. An operator-facing ceremony runbook must pin its interpreter and environment explicitly
145. Measure the memory before you believe the design
146. A "zero-change" or "already handled" claim in a docstring is a load-bearing assertion — verify it against the code before trusting it
147. Backend-complete is not operator-reachable
148. A "saved" flag is memory; a content hash is truth
149. A hand-copied cross-language allowlist drifts in silence — guard it with a gate test, not vigilance  · ↺4 ★
150. A test double standing in for an async object must itself be async, or it proves a path production never runs  · ★
151. Confirm the measurement and the ground-truth fact are about the same scenario before you let one override the other  · ↺3
152. Dispatch to the capability; don't become it
153. Inject the danger so you can test the logic
154. Read the system you're dispatching to before you map onto it
155. An unrun check is not a pass
156. When a value becomes centrally-sourced — config-driven, env-overridable, or a computed seed threaded to N sites — audit every consumer; a half-promoted value is worse than a hardcoded one  · ↺2 ✓ctrl
157. Reply before you exit; a daemon thread can't take down its own process
158. A control tested in isolation can still rest on an unstated single-instance assumption  · ↺1 ✓ctrl
159. When you depend on a signal being delivered, guarantee termination — don't widen the window
160. The log decides, not the hypothesis — verify the failure mechanism before you fix it  · ★
161. Capturing a subprocess's output deadlocks if it spawns a long-lived grandchild  · ↺1
162. Red-team the design before the diff, and let an independent gate certify what you certified — your own adversarial pass shares your blind spot
163. Verify the brief's "where," not just its "what."
164. A deterministic gate's dangerous direction is the one that drops work — verify *that* direction adversarially, in a separate pass, never with a green run
165. Verification can shrink a change, not just confirm it
166. Ship the trigger, not a second mechanism
167. An end-state assertion is not a guard on the step that produced it
168. Ground a "smart" heuristic in the real artifacts before you code the predicate
169. OOM is a commit-limit event, not a physical-RAM event — gate memory-risky loads on measured Available-RAM headroom, not on catching an allocation that won't fail
170. Defence-in-depth only defends the paths that run it  · ↺2
171. A built-correct feature can be dormant in practice — the live model probe, not the green unit gate, is the acceptance test  · ↺1
172. In a working tree holding other sessions' uncommitted changes, read the staged diff and commit only your own hunks — `git add -A` is the wrong reflex
173. Decompose a model's output along the axis where it is strong vs weak, and discard the weak half rather than fighting it
174. A stubbed test of a shell-out or a compiled-inline type proves the wiring, not the runtime — exercise the real compile/exec path at least once
175. Unit-green is not seam-green
176. The live test finds the bug the theory rationalized away
177. Take the unreliable judge out of the critical path, don't just demote its verdict
178. Before appending anything to a field that is later re-parsed, read the parser
179. A "done" signal must be terminal, not per-step
180. When a system underperforms, check which half the effort went to before you add more of it  · ↺1
181. Default the PROVEN to live, not dormant
182. Live-verify is a bug-finding instrument, not a rubber stamp — and the fixes are the verification, not a detour from it  · ↺1
183. Prefer the wire format the model was trained on — a homemade dialect taxes both ends
184. Match the failure posture to what failure threatens  · ↺1
185. Tier the dispatch, deny the action — at separate layers
186. A quality yardstick pays for itself at the first seam it guards — and golden sets are commitments, not observations  · ↺2
187. Audit the deterministic plumbing before tuning the model when a quality miss is one-sided
188. Re-verify an external contract against the live service before depending on it, not against the docs  · ↺3 ✓ctrl ★
189. When a build must stop exactly one act short of live, enumerate the merge-time locks and make the release ONE reviewed governance act a tripwire forces into review
190. The output validator has a direction, not just a similarity  · ↺1
191. Consent grain is set by judgeability, and judgeability lives on the action, not the content
192. When you replace a control, delete the old one in the same breath — and let the test that encodes the real goal tell you whether you did
193. Verify the premise on disk before building the decision — a control that protects a threat the code cannot express is friction, not security  · ↺2
194. A green gate proves the code does what you told it; only the live run proves you told it the right thing  · ↺1
195. A memory measurement is valid only for the exact path and era it measured  · ↺2
196. An append-only lessons list dilutes its own signal — curation is part of the discipline  · ↺3
197. When the platform refuses your test action, the refusal may be the very property you set out to prove
198. The verify-the-artifact discipline applies to the critic, not just the coder
199. When you fan out, hand every branch the same ruler — and make the ruler unforgeable
200. Bound the work from both sides, and let the cheapest lever lead  · ↺1 ✓ctrl
201. On integrated hardware, measure the ceiling — and find the real constraint, which is rarely the obvious one  · ↺1
202. Coherent is not conditioned
203. When an execution mode keeps getting killed, diagnose what survives and switch modes — don't re-launch the dying mode
204. A benchmark harness must not inherit production config it doesn't understand
205. Build new UX on the proven seam, not a parallel one
206. A nicety is not worth destabilising a locked contract — revert and surface it as a decision
207. A system's disaster-recovery posture is part of its security posture — and a backup is only as good as its decrypt path
208. A relocation is not complete until the old address stops asserting things
209. A verification run that ends without its summary artifact is FAILED, not green  · ↺1
210. An upstream bug report is only as strong as its smallest self-contained reproducer and its most honest disclaimer  · ↺1
211. A plan whose validation and security work has no owning workstream, no effort line, and no schedule slot is theater at program scale
212. A pinned cross-lane contract that references an operation it does not define is a latent integration break — implement a reference for it, flag it loudly for the owning lane to adopt-or-supersede, and never guess it silently  · ↺1
213. A readiness signal for a slow-starting singleton must verify the property the caller depends on, and the retry that owns it must probe in-flight before it respawns — a false-ready cascades  · ↺2 ✓ctrl
214. Fail-closed is the right posture; fail-closed-and-mute is a defect factory  · ↺3
215. A negative control is only proof if the REAL gate catches it — and a test-only saboteur must be structurally unable to fire in production
216. A recovery path is a loaded weapon pointed at whatever it believes crashed — it must verify the death, not infer it from its own start  · ↺2 ✓ctrl ★
217. Configuration values that accrete one incident at a time form an invisible taxonomy — when a value CLASS earns its third scar, give the class a registered, gate-locked table  · ↺1 ★
218. Before you fix a long-broken behavior, find out what grew around it — a bug that has been failing in the same direction for long enough becomes load-bearing  · ↺1
219. A process-creation control can be defeated by an intermediary the platform inserts between you and the process you think you are spawning — verify the observable end property, never the flag at the spawn site  · ↺2 ✓ctrl ★
220. A fail-closed gate inside a loop needs a containment boundary at the loop body — refusing one record is the gate's job; whether the refusal costs the item or the run is the LOOP's design decision, and leaving it implicit means the strictest gate anywhere becomes a whole-run kill switch
221. When one component's watchdog window overlaps another component's granted budget, the shorter window silently wins and the budget is fiction — every liveness window must be provably longer than the longest legitimately-silent phase it can observe, or the phase must emit a heartbeat  · ↺4 ✓ctrl ★
222. A verdict-issuing instrument needs a positive control before its failure class is believed — prove it can produce PASS on a known-good subject under production conditions, or every systematic blindness it has becomes a fleet of plausible failures wearing measurement's authority  · ↺7 ✓ctrl ★
223. When a workflow forks from a mirror, the mirror's refresh cadence becomes an invisible upper bound on the workflow's correctness — fork from the source of truth, and treat "it worked the other day" as the calendar luck it is
224. A parameterized run's isolation is only as complete as the side effects you enumerated — scoping the DATA while a shared-resource write stays keyed to the code path makes every "safe, isolated" test run carry a loaded global consequence  · ↺1
225. Gate the expensive resource on the cheapest probe of the experiment's validity precondition — and read the system's own emitted evidence, never an assumption  · ↺2 ✓ctrl
226. A system's disaster-recovery posture is part of its security posture — and a backup is only as good as its decrypt path  · ↺1 =207-dup
227. When a generated artifact must sound or look "human grade," change the KIND of content generated to match the synthesis method's strengths before turning quality knobs — polish cannot rescue the wrong content type
228. A production side effect that fires from a module import or a moved point-of-use seam will cross the pytest boundary the day a test mocks the wrong site — mock the site the code actually reads, prove a bare import reaches no live seam, and scope the mocks a test shares with a fixture  · ✓ctrl
229. Timestamps are not a sequence
230. A fix that must update several copies of a truth but updates only one gets silently reverted by whatever treats the others as authoritative — enforce the invariant in a layer no background process rewrites, not in a copy one does  · ✓ctrl
231. Reap the whole process tree on NORMAL exit, not only on timeout or kill
232. A model-callable tool may *name* a high-risk surface as long as it is source-isolated from that surface's write path
233. A confirm hop that must survive a model restatement should carry an opaque token, never the body
234. Keep a version-incompatible or heavy dependency out of a module's top-level imports when the module must also be flag-dormant and gate-tested
235. A deliberately "powerless" account still needs its positive capabilities enumerated precisely — "denied everything" and "denied everything except exactly what the job requires" are different postures, and only the live run finds the gap between them
236. A control that governs a delegated agent's tool surface does not govern the processes that agent spawns — assess containment at the layer the OS enforces (the account/SID), because a child process routes around every policy that lives above it
237. A component that consumes "the whole history" has an unbounded input the moment the history grows — design the batching, the cross-batch aggregation, AND the resumability in from the start, not after the first long run strands you
238. When the only callers of a symbol are the tests written to exercise it, those tests are its tombstone, not coverage — deleting them is the deletion, not collateral
239. Validate a machine-generated artifact against the semantics of the system that will execute it, not merely its syntax
240. A control written into an enforcement plane is a claim about the PLANE, not just the rule — verify the plane enforces *anything at all* (a one-rule positive control) before trusting any rule written into it
241. Surface the grader's contract to the builder — a hidden acceptance interface guarantees layout divergence
242. Session-keyed in-RAM state needs a named death path at the moment it is born
243. An enumeration that covers a subset while implying the whole is a false-clean — and a probe that cannot see must not report clean  · ↺1 ✓ctrl
244. Order a new pre-flight stage AFTER the cheap validity gate it front-runs
245. When "preserve the parts the user didn't change" is a requirement, have the model emit an EDIT over the existing artifact — references to keep plus adds — and apply it deterministically, never a full rewrite you hope doesn't churn  · ✓ctrl
246. A gate protects the *artifact* it inspects, but the party under test often owns the gate's *execution environment* — grade in a hermetic environment the subject cannot influence (deny its config, hooks, and path), or the environment becomes the evasion
247. A gate can only catch what its sensors read — when a failure mode is invisible to the current sensor, add a sensor, don't tune the blind one; and put the sensor where the artifact can't reach it
248. An error-triggered repair is blind to a malformation that parses cleanly into the wrong shape — guard on the divergence between intent and result, not on the exception
249. An invented interface has more than one axis — the NAME, the SIGNATURE, and the RETURN — and enforcing only the layer you can see cheaply leaves the others as silent parks; enforce the contract at the grain the failure actually occupies, not the grain that is easy to check
250. A second instrument that judges the first only has signal if it is strictly cleaner than the first — a same-state re-run of a deterministic grade proves nothing
251. An automated gate must be calibrated to the ACTOR that consumes it, not to the linter's defaults
252. The suppression/allowlist for a control that audits an artifact must be sourced from the TRUSTED side, never from the artifact being audited — otherwise the audited party can ship its own exoneration
253. A manifest that claims to be *descriptive of today* must record what the system actually does, never a research dossier's recommended future — the two must not be conflated in a data file the next consumer will read as ground truth
254. A deterministic diff can prove *changed*, never *worse* — severity that distinguishes a lateral reformat from a data-loss regression needs a second deterministic signal (here, material output shrink), decided by a formula, not deferred to a model
255. Freeze the test set the day you start tuning, not the day you evaluate — a protective split against overfitting is time-sensitive, and it needs a fail-loud gate shipped WITH the rule, not documented and deferred
256. Bounding an unbounded wait means WAKING it, not killing it — distinguish a wait unbounded in TIME from one merely un-woken in MECHANISM
257. When a design gives an agentic system visibility into or influence over its own backlog, roadmap, or configuration, prove the self-targeted branch is structurally SEVERED, not merely approval-gated  · ★
258. A path-only identity check fails open on hardlinks — canonicalize the path AND check the filesystem's own identity
259. When the protected thing is "everything of a kind," refuse the attack primitive — an enumerated target list is never complete
260. A threshold measured from a spike is not a production default until the spike sampled the production distribution — and right-censored failure data licenses only raising a bound, never tuning it down
261. A repair loop must be able to target the thing that failed — audit its candidate set, not just its matcher
262. A namespace with semantics must be guarded at the reader — writers multiply
263. A retry loop needs a first-class "nothing to do" exit, or it converts honesty into manufactured work
264. A live-verify whose observed result is "nothing to report" proves candor, not aim — only the first real event proves the read is pointed at the right target
265. A defect fix inherits the defect's own blind spot unless someone else looks — the reviewer's first move is to enumerate the writers  · ↺1
266. Accept an operator-facing surface through the operator's own entry point — reachability is not transitive across UI layers
267. The first honest reading of a new observability surface by its actual user generates design findings at a rate no review pass matches — schedule the user's first look as part of the ship
268. Exit codes are not judgments — any automation shaped "check X then do Y" must route X through something that actually reads it
269. A fresh recommendation is a hypothesis until checked against the project's own decision and measurement record
270. Reclaim lives where the accounting hides it
271. Size a fix — and its proof — from the code, not the ticket's framing of it
272. A cross-repo fix whose halves are each a safe no-op needs ONE ticket that stays open until BOTH mains carry it
273. A plain string returned from a self-contained untrusted-content loop is a latent fail-open until its relay grounds it — make the relay correct by construction
274. Sign only what a code path verifies — and read the served set on disk before wiring integrity to a model or scrubbing it
275. Reusing a security control's config flag on a new surface is safe only if the surface flows through the same enforcement function AND the flag still has a dormant state to give
276. A control belongs on any code path that genuinely loads the asset it protects — reachability by a real ceremony or smoke path, not membership in the default production path, is the test for "dead code vs. real gap."
277. A hash-pinned lock listing multiple digests per version is satisfied by pip if the artifact matches ANY of them — a "tampered artifact fails closed" proof must invalidate EVERY recorded hash of the chosen distribution
278. An index that asserts a sibling EXISTS — a matrix row, a "catalogues N docs" count, an authority reference — must run a resolving-link check against the actual directory before it merges
279. Instrumentation for "does X actually happen" must leave X byte-for-byte unchanged when the probe is off — and never relocate a load-bearing step to fit a tidy wrapper
280. Every recorded benchmark headline gets a same-session magnitude cross-check against the nearest in-house production baseline before it is written down
281. A verdict must be computed from verified content, never from a container — a summary flag, a parsed field's presence, or a prefix — and an instrument ported to a new backend measures the old backend's shape until its detection path is audited
282. A unit test that mocks the services can still run the machine — when a suite drives a real entry point, enumerate the entry point's side effects, not the test's mocks
283. Dead and reused both read as "not alive" — but they demand opposite responses: recovery wants presumed-dead, kills demand proven-identity
284. A harness gate that re-implements a language rule must implement the language's ACTUAL rule — a "close enough" approximation manufactures unfixable failures downstream
285. When a parser has no built-in size or depth limit, bound the untrusted input BEFORE the parser, not with the parser's own hooks — a completion hook observes the attack; a non-recursive pre-scan prevents it, and a cap downstream of a wire cap is a tighter independent lock with the ordering test-locked
286. A memory/KV projection must be driven by the model's actual attention topology read from its config, never the dense-model default — an over-projecting fail-closed guard silently deletes capability
287. When an autonomous system has a deterministic layer and a model layer, grade them SEPARATELY against the same ground truth — an aggregate precision number averages a graduation-grade actor with a disproven speaker
288. A document whose stated maintainer is a retired role is stale by definition — re-own it or retire it the day the role dies; and a cleanup ends when its freshness gate ships, not when the files look tidy  · ✓ctrl
289. An approval list is an allowlist — treat silence as denial
290. An obligation with no owner is not a process, it is a hope — it fails silently every time rather than loudly once
291. A verdict that assigns fault must adjudicate the instrument before it attributes the finding — an instrument that measured nothing has produced evidence about itself, not about its subject
292. A documentation correction is a claim-generating act — verify the fix to the same standard as the defect, with an independent verifier, until a round returns empty; diff-scoped review cannot see a defect that has stopped appearing in diffs
293. A structural control's trust is engineered, not free — measure the false-positive rate before gating, prefer a self-describing declaration cross-checked against the authority over any hand-maintained map, and pin the honest form passing as an equal partner to the defect failing  · ↺1
294. An adversarial review panel graded against a rubric verifies that a piece is TRUE and INTERNALLY CONSISTENT, never that it is WORTH READING — only a human with a real stake can judge the second axis, and a clean panel pass must never read as validation of it
295. An unmeasured "now" is a fabricated input that every downstream duration inherits — and durations are what kill decisions are made of; measure the clock in the same breath as the judgment, cross-check one independent timestamp source, and treat contradicting evidence as a probe of your premise before inventing a mechanism to rescue the theory
296. Migrating doctrine out of a repo being sunset is COPY-THEN-VERIFY, not rewrite-from-memory — diff the new text against the source and account for every dropped clause, because the retired repo will not be there to check against later  · ✓ctrl
297. Name the surface that OWNS a claim and read THAT — a ticket's DESCRIPTION is its spec (comments are only history), a sentinel's meaning belongs to its own docstring, a duration to the timeout registry, and what happened in a repo to git history  · ✓ctrl
298. An instruction that names a command and also demands a precondition that command does not establish is worse than no instruction — it manufactures false confidence in the exact step it was written to protect  · ↺1
299. A destructive command is most dangerous during CLEANUP, because cleanup does not feel like an operation — pair every "put it back" with the same non-destructive tool used to take it out, and note that a destructive command which succeeds is quieter than one that fails  · ✓ctrl
300. A handoff is authored at maximum attachment to your own in-flight work, so the QUEUE is the predictable omission — especially what your own ship just unblocked; the predecessor is structurally the worst-placed person to notice  · ✓ctrl
301. A bulk-derived index is a measurement event — reconcile it against its authority the day it is born, with the instrument that will later gate it  · ✓ctrl
302. Fix the exam before fixing the student — a repaired contract can remove the behaviour a code fix was built for; sequence contract quality first
303. A measurement cadence is a design choice, not a law of nature — attribution belongs to conditions, not calendars
304. An opt-out from a precondition gate must be narrower than the gate — waive only what was OBSERVED and recorded; a waiver covering "unknown" turns fail-closed into fail-open
305. An instrument that demands output will be given output — a loop whose only legal outcomes are "produced X" and "failed" manufactures the evidence it demands
306. A skip the verdict arithmetic cannot represent becomes a punishment — walk the aggregation code for where a new outcome class falls through before shipping it
307. Dead code with a seeded test looks alive to every tool except judgment — reference-counting cannot distinguish product logic from furniture you bolted to the floor yourself

---

*Full text of every numbered lesson: [docs/archive/lessons/LESSONS_ARCHIVE.md](docs/archive/lessons/LESSONS_ARCHIVE.md). Tiered 2026-07-19 (#945 D2); hot-file budget: 120 KB.*
