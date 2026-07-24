# Journal Mining — Chunk 6 of 7

Lines 12563–15043 (small spillover to finish "Building the instrument before touching the lock" at ~15103). 54 entries, era 2026-07-02 → 2026-07-09.

---

## 1. ERA

This is the **M2 fleet-maturation fortnight** — the span where BlarAI's autonomous coding fleet grew from "dispatch a job" to "run a multi-task job as a dependency graph, verify the composed whole, and refuse to lie about it." The dominant build is the plan-graph program (#740): a deterministic ruler over the 14B's proposed task graphs, evidence-gated status machine, per-wave integration gates, a spec-blind job-level oracle, context packs (a novel worm-shaped channel treated as a security problem first), and a five-layer validation harness authored test-first. Running under and through it is a **reliability campaign** — nightly batteries on the Arc 140V that keep surfacing composition failures no unit test could (timeouts mislabeled as parser misses, readiness signals that lie, tests that kill the live production AO, a load-bearing bug propping up the completion protocol). Alongside the build: the journal restructures itself (LESSONS.md split + canonical tier + third-instance rule), the #725 xgrammar crash is characterized and fixed *upstream* (PR to openvino.genai), the guest-certified oracle goes from dormant to a live LA-supervised ceremony, and the Qwen3.6-27B successor question gets its first real measurement. The through-line: an unusually mature honesty machine (zero-FALSE-DONE, fail-closed, "the screen finds what the gate can't") being stress-tested nightly and hardening at every seam.

---

## 2. GEMS

1. **2026-07-02 — "What the live-verify caught that every green test missed"** — A rework passed 5051 tests, three merges, an ADR amendment, committed eval evidence — then the live box showed the model *writing its own tool-refusal* by imitating an older `/trust` message in chat history (the #726 chat-poisoning), falsifying an ADR claim. Lesson: a green gate proves the code does what you told it; only the live run proves you told it the right thing. `[failure-story][engineering][human-AI-collaboration]`

2. **2026-07-04 — "The gate that vanished at 76 percent and reported green"** — The standing gate *disappeared* at 76% (a live app held the repo's `launcher.lock`; the production refusal path's deliberate `os._exit(1)` killed pytest itself) and, piped through `tail`, returned the pipe's exit code — "not red, not green, but absent, wearing green's clothes." Never trust a piped exit code as a gate verdict. `[failure-story][engineering]`

3. **2026-07-04 — "The crash that only happens when two right things run together"** — Characterized the #725 xgrammar `IsStopTokenAccepted` crash by elimination on real silicon: grammar-ON + speculative-decoding is necessary and sufficient (spec-ON ~1-2% of generations crash; spec-OFF 0-for-57). Kept the honest non-finding (streamed 0/57 *looks* safe but N is tiny and production's real crash was streamed — "stated as unmeasured, not as a finding"). `[engineering][community/OSS][failure-story]`

4. **2026-07-05 — "The fix that couldn't be proven on the machine that broke"** — Two-line guard reorder fixed #725, but the official Python wheel's ABI wall made GPU re-verification impossible; pivoted to a standalone CPU C++ reproducer (baseline 1 crash/95 on GPU, patched 0/95 on CPU) and filed issue #4081 + PR #4082 under the operator's account with the device substitution disclosed plainly rather than glossed. Truncated a 5-6h CPU run to match the baseline's exact sample size after checking in on the trade-off. `[community/OSS][engineering][failure-story]`

5. **2026-07-05 — "The plan that had to survive four rounds of its own medicine"** — The non-technical LA's four review rounds caught the two classic ways engineering plans lie to themselves: a maturity claim backed by a demo not a validation scheme (→ five-layer §9), and a validation scheme with no owner and uncosted effort (honest 20-29h → 24-34h — "the delta *is* the previously-invisible validation build"). Round four's question ("could the Hyper-V guest close the residual?") produced a *better* design than the plan had (#744). `[process][governance/security][human-AI-collaboration]`

6. **2026-07-05 — "The seal that covered less than the docstring claimed"** — Adversarial review found a `PlanStore` integrity docstring three-quarters true: the hash covered `{goal, tasks-minus-status}` but not `oracle_path`, repo, or budget ceilings — a redirected oracle_path is a textbook FALSE-DONE. Fix seals the *immutable identity* and declares an explicit contract that on-disk status is ADVISORY. "The worst kind of security comment because a reader trusts the guarantee that isn't there." `[governance/security][failure-story]`

7. **2026-07-06 — "The queue the run dirs never kept"** — Built the dispatch→Vikunja bridge as **outcomes, not heartbeats**, pointing at a graveyard: Project 8 "Fleet Reports" is Defunct because an earlier fleet posted per-phase-per-wake, "a notification firehose the operator learned to ignore inside a day. A queue you ignore is worse than no queue, because it *looks* like coverage." Also corrected the task's own premise — the air-gap import control on disk proved `shared/` was the wrong home. `[process][engineering][governance/security]`

8. **2026-07-06 — "The trailer cut in the shadow of the battery"** — A promotional cut deliberately *shows a failing gate* because the honest acceptance posture IS the differentiator ("sanitizing it out of the marketing would contradict the very journal this project keeps"). Then the night's real failure was in *publishing*: a silently-broken Windows long-path clone made a three-path `git add` commit the rest of the tree as `1786 files changed, 593828 deletions(-)` — pushed because the push line was read and the stat line wasn't. Recovery 6 min, non-destructive; permanent field note. "The marketing constraint and the governance constraint turned out to be the same constraint: say only what the frame can prove." `[failure-story][process][community/OSS]`

9. **2026-07-07 — "The recovery that killed the patient"** — Running the standing pytest gate during a live battery made the AO boot swap-recovery reconcile "recover" the healthy swap — stopping the real OVMS mid-request. The LOCALAPPDATA redirect (built after a prior test-corruption incident) never covered the fleet state dir. Fix verifies the death certificate first (driver stamps its own pid/create-time; live driver = hands-off), chosen over test-only patching because "the operator opening his app at 23:30 while the nightly battery runs would have killed the battery job exactly the way my pytest run did." `[failure-story][engineering][governance/security]`

10. **2026-07-07 — "Two protocols share an acronym; one of them points at a graveyard"** — Two protocols both called "ACP"; the trap is the acronym. IBM's Agent Communication Protocol stopped existing as an independent standard on 2025-08-29 (merged into A2A, repos archived, SDK deprecated). "Had we adopted by acronym recognition rather than checked liveness first, we would have built on an archived spec." A2A watchlisted with two concrete revisit triggers; the one genuinely agent-shaped seam is file-mediated *because the client process dies on purpose mid-job*. `[governance/security][process][community/OSS]`

11. **2026-07-07 — "The verification line nobody ever read"** — An ACP recon handshake (run with `--print-logs`) caught both coder-fleet opencode plugins silently dead in production since 2026-06-30 — "Plugin export is not a function" (a regex named export rejected by the loader). The production invocation never passes `--print-logs`, so the failure printed nothing for a week; both plugins even ship a stderr load-line whose whole purpose is verification, but "nothing ever grepped for it. A verification line nobody reads is a verification line that does not exist." Third instance of lesson 46 → shipped its structural control (the #762 load-line canary). `[failure-story][engineering]`

12. **2026-07-08 — "The healthy run that could never end"** — Fixing the clobbered #758 driver-alive stamp exposed that the fleet's terminal-phase stamp had *only ever* come from a reconcile branch the clobber itself kept firing. "A bug had been load-bearing, and I had knocked it out from under a protocol that never knew it was leaning on one." Durable fix: a healthy driver stamps its own terminal phase; a failed restore stays in-flight for the reconcile. `[failure-story][engineering]`

13. **2026-07-08 — "The estimate the kernels cut in half"** — First measured Qwen3.6-27B run: 3.59 tok/s vs a ~6.5 first-principles bandwidth estimate the LA had accepted. The tell was prefill (219 tok/s vs the 14B's ~1960 on identical silicon) — immature Gated-DeltaNet kernels, not weight streaming. "My bandwidth model wasn't wrong — it was an upper bound dressed as a central estimate." Same-evening: a *primary-source thread-read* killed a claim ("open bug on our exact runtime") that had "survived three documents"; and an LA question surfaced the real swap-blocker — the model *quotes the `/no_think` constraint inside its own thinking trace and reasons on* (genai #3937, reproduced). `[engineering][community/OSS][failure-story]`

14. **2026-07-08 — "The clean room takes its first exam"** — The #744 guest-certified oracle went LIVE in an LA-supervised ceremony whose ordering rule was "prove the observable end property before trusting any wiring": the NIC-less Alpine guest returned *passed* then *failed-with-real-assertion-text* before a single production line was registered. "A guest that cannot say no proves nothing, and this one said no before it was asked to say yes." First light was honest, not triumphant (a flat-queue job with nothing to grade). `[governance/security][process][engineering]`

*(Runners-up worth a mention: "The taxonomy of scars" — the timeout registry as a table-with-teeth not a config source; "The issue that fixed itself" — ISS-3 closed on N=3 side-effect evidence with the closure bar raised *because* the fix was unattributable; "The saboteur you can only run in the lab" — test-only sabotage that must be structurally unreachable in production.)*

---

## 3. LA MOMENTS

The non-technical Lead Architect's judgment is unusually visible and consequential in this chunk:

- **The four-round plan review (07-05)** is the crown jewel: a non-technical operator caught an unvalidated maturity claim, an ownerless validation scheme with uncosted effort, and a missing threat model — then his "could the Hyper-V guest close the residual?" question *designed* the guest-isolation executor (#744). Domain-blind but rigor-literate.
- **The deck's sound (07-03):** watched it run, returned "looks really good" + one design defect — the synthesized audio felt counter-productive; research confirmed him twice over (professional-deck consensus + the Irrelevant Sound Effect literature). His "this feels wrong" about a shipped, verified choice recurred as a lesson-38 instance.
- **The trailer (07-06):** "not impressed" with the surface-only cut (describe/approve/merge), freed the GPU and said "use BlarAI"; then a cascade of truthfulness notes ("This is BlarAI" over a title card; credit the Kokoro voice; "one laptop" not "this laptop") and the "banging for soooo long" note that was actually a *score-geometry bug* diagnosis, not taste.
- **Governance questions that opened whole workstreams:** "if the 14B writes the tests that grade every dispatch, who grades the tests?" (→ oracle_quality suite #765); "does the thinking toggle actually break the Policy Agent?" (→ genai #3937); the ACP liveness question; delegating the command-line→Python default while clarifying "language" meant the *programming* language, not his English.
- **The permission layer as a brake he endorsed (07-08):** two attempts to hand-unstick a wedged run were blocked as mutations of shared runtime state — "It was right to make me stop and think." Later the Stop-Process denial cost a night ~2.5h until he woke and authorized it — a deliberate, accepted cost of the containment posture.
- **Estimate → obligation:** his weighing capability against ~6.5 tok/s and *accepting* it "converted an estimate into an obligation: measure it." He also asked to read the actual #3870 thread before citing it, which corrected two records same-day.
- **Ceremony attendance:** he readily supervised the guest-oracle go-live and ruled what composes "the campaign's first full-set bank" (a clean five-job pass + an honest standalone B6).

---

## 4. MOTIFS

- **"A green suite proves the mechanism, never that the running system still invokes it"** (built-but-wired-into-nothing / lesson 46) — the single dominant motif, recurring at least five times in-chunk: opencode plugins dead since 06-30, the #758 driver stamp clobbered on first write, the W2 decompose grammar hook never threaded to the live entrypoint, the guest-oracle consumption seam never driven through the real writer, the #571 flag that had to be wired at its call site. *Cross-era check: this lesson's instance count and whether its third-instance structural control fired; likely spans every era.*
- **The gate must not touch — or be killed by — the live system.** Tests killing production OVMS/AO (07-07 reconcile, 07-08 port-5001 leak detector "aiming at" the AO, the cert re-mint orphan), plus test-isolation blind spots beyond LOCALAPPDATA (`certs/`, the fleet state dir). *Cross-era check: earlier LOCALAPPDATA/sessions.db corruption incident that these all descend from.*
- **The screen finds what the gate structurally cannot** — the operator's screen surfaced the OOM cascade, the pythonw/OVMS closable windows, and the flat-queue certificates. "The gate and the screen are different instruments."
- **Read the code / primary source, not the ticket, narrative, or summary** — the #750 readiness ticket was confidently wrong, the #748 empty-plan was three stacked mechanical defects (not model capability), the 27B thread-read overturned three documents, ACP liveness. Pairs with the [PROPOSED]/verify-premises discipline.
- **Honest labeling of self-inflicted kills** — a harness kill must never leave its victim looking self-caused (TIMEOUT vocab, #757/#766/#771 timeout cascade); FALSE-DONE zero-tolerance expressed as a pure verdict function.
- **Structural absence over configuration** — guest oracle built-not-registered, the B8 saboteur structurally unreachable from production, dormancy locks amended in the same commit that flips them live.
- **Upstream/OSS honesty** — device-substitution disclosure in PR #4082, engagement-first recon, softened-certainty upstream comments (openvino #36270, genai #3937/#3938). *Cross-era check: the earlier Kagi/EAGLE-3/browser external-contract-rot instances that minted lesson 188.*

---

## 5. WASTE PROFILE

This is a high-signal chunk (lots of genuine failure narrative), but heavy on dense M2 build bookkeeping.

- **Genuinely-narrative ~45%** — the failure stories in §2, the LA-shaped entries, the honesty-machine set pieces. Unusually high for this corpus.
- **Changelog-shaped ~20%** — the dense M2 build entries where insight is real but buried under commit/test-count trailers: *"Teaching the dispatch to see a job as a graph it still refuses to trust"*, *"Teaching the fleet to finish a job, not just its pieces"*, *"Building the net before the thing it catches"*, *"Closing the free-text gaps in a sequence that was already half-grammatical."*
- **Superseded-by-later-events ~18%** — intermediate fixes overtaken within days: *"The flag that worked, one process too early"* (#761 pythonw, superseded next entry by the cp1252 banner fix), *"The certificate that must never touch the verdict"* / *"The bridge built beside the door it must not open"* (dormant #744 slices, superseded by the live ceremony), *"The readiness signal that lied"* (fix 1 vs fix 2).
- **Duplicated-in-LESSONS ~12%** — recurrence-tally entries whose transferable lesson lives in LESSONS.md: *"The redirect that didn't reach the certs"* (L55), *"The certificate that killed the night"* (L46 fifth instance), *"The little toolkit that was really four things"* (L200 tally).
- **Status-shaped ~5%** — few pure status entries; the closest are *"Closing the residuals the door I never opened was hiding"* (bucket-A sweep) and parts of *"The issue that fixed itself"* — both salvaged by a real embedded lesson.

---

## 6. CURATION VERDICTS

**KEEP-HOT** (the exceptional few — must stay instantly findable):
- 2026-07-02 — What the live-verify caught that every green test missed
- 2026-07-04 — The gate that vanished at 76 percent and reported green
- 2026-07-05 — The fix that couldn't be proven on the machine that broke
- 2026-07-05 — The plan that had to survive four rounds of its own medicine
- 2026-07-06 — The trailer cut in the shadow of the battery
- 2026-07-07 — The recovery that killed the patient
- 2026-07-07 — Two protocols share an acronym; one of them points at a graveyard
- 2026-07-07 — The verification line nobody ever read
- 2026-07-08 — The estimate the kernels cut in half
- 2026-07-08 — The clean room takes its first exam

**ARCHIVE-WHOLE** (default — safe in a cold volume, findable via LESSONS.md tallies): all remaining ~44 entries, including the entire M2 build sequence (plan_graph, W9 net, W3-W6 context packs, simulate_job_plan wiring, #748 empty-plan root-cause, node ESM oracle seed, research substrate #746, Vikunja bridge #749, B8 rig seam, OVMS cache #747, B2 decomposition, headless capture, cert re-mint/#751 isolation, F3/F1/F2 oracle-coder contract, the #757/#766/#771 timeout cascade, #761 pythonw + cp1252 followup, OVMS-window/#B3-budget, bucket-A security #571/#633/#641/#636, ISS-3 self-fix, oracle_quality #765, the timeout registry #767, both #744 dormant slices, the port-5001 detector + stamp-clobber, "healthy run that could never end", "certificate that killed the night", the 27B measurement, and the prefix-caching harness #711). Most are strong engineering entries; they simply don't need hot-shelf immediacy.
