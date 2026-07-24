# Journal Mining — Chunk 5 of 7

Range: BUILD_JOURNAL.md lines 10074–12562 (+small spillover to 12715 to see the era's turn).
Entries covered: 33 in-range (2026-06-26 → 2026-07-02), reader read 4 more spillover entries (2026-07-02 night → 2026-07-03).

---

## 1. ERA — dates + what the project was becoming

**2026-06-26 to 2026-07-02** (one intense week; the densest, highest-value span I'd expect across the whole corpus). Two landmark arcs run in parallel and both cross a threshold in this window.

**Arc A — the headless coding dispatch grows up and goes LIVE.** The fleet that turns a natural-language goal into merged, gate-passed software matures from "builds a compiling app" to a disciplined generate-and-verify machine. The pivot of the era is intellectual, not mechanical: prompted by the LA's question "is this fundamentally flawed, or are the local models just not smart enough?", a grounded research pass finds the effort had been over-invested in the *review* side (which METR data shows is saturated, +8pp statistically insignificant) while the single highest-leverage local lever — best-of-N generation sampled into the deterministic gate they *already own* — sat unpulled. That reframe drives the whole #688→#689 (best-of-N) → #690 (cross-model shared oracle) → #691 (task envelope) → #695 (measured concurrency) sequence. The dispatch flips `enabled=true` (LA correction: "stop making the mature functions dormant"), gets image-generation wired in (SEAM A, #714), and a New-Project UX so the non-coder operator can actually start a repo (#712).

**Arc B — BlarAI's first governed egress, plus the instruments to trust it.** The system builds its first *model-quality* measurement (`evals/`, #717 — closing the ISS-3 blind spot where 4000 software tests measured zero intelligence), migrates tool-calling from a homemade regex dialect to Qwen3-native JSON + xgrammar decoder constraint (#718), offloads embeddings to the idle NPU (#720, fail-SOFT), and then crosses the big line: `web_search` go-live (#719/#723) — the first BlarAI runtime socket ever to leave the box under governance, after months air-gapped. The go-live cascades into a run of live-verify-caught defects that are the era's richest failure material (Kagi 401, the leak-validator swallowing legit answers, the trust-friction rework, chat-poisoning, hires OOM). A community-grade performance thread runs underneath throughout (MoE bargain, co-residency telemetry, KV-cache precision sweep). The spillover shows the era closing with the journal auditing *itself* (LESSONS.md split) and authoring a Fable 5 portfolio deck.

---

## 2. GEMS (13 — a stranger would stop on these)

1. **2026-06-26 — The lever I'd built three reviewers to avoid finding.** *The era's centerpiece.* A research-driven strategic *reversal*: the whole review apparatus was the saturated half; best-of-N generation fed to the owned verifier was the unpulled lever (DeepSeek-Coder-V2 went 15.9%→56% on SWE-bench Lite from sampling alone, beating frontier single-shot; local marginal sample is electricity, not API dollars). Names all three rejected alternatives and admits the prior critic/VLM work was near-wasted. *Insight:* when a weak component is expensive to improve, add generation coverage and let the verifier you already own pick the winner — and ride the capability curve (METR reliable-task horizon doubles ~every 7 months) instead of building a fourth reviewer. [engineering][process][human-AI-collaboration]

2. **2026-06-27 — The four bugs the green suite swore weren't there.** Code went to main proven by units (gate 4250/0); the on-hardware verify then found *four* real defects in a row, each structurally invisible to an all-green suite (aspirational-but-false pythonpath comment; critic agent never synced to where opencode looks; `git diff base...HEAD` empty post-merge; Python-only test instruction leaking into a C# task). *Insight:* "the verify wasn't a rubber stamp applied after the build; it was a bug-finding instrument, and the four fixes *were* the verification." Canonical mock-vs-live. [failure-story][engineering]

3. **2026-07-02 — The over-denial that turned out to be unreachable ALLOW.** A measured Policy-Agent "quality miss" (86.7%, all four misses false-DENIES) was NOT the model being cautious — three individually-correct fail-closed defaults (fallback confidence zeroed 0.995→0.0 by prior hardening; a one-line output format that never asked for confidence; `MAX_CLASSIFICATION_TOKENS=10`) *composed* into a classifier that could never emit ALLOW. Fixed inside the prompt-tune mandate; 31/35 → 35/35, false-ALLOWs stayed 0. *Insight:* "when a measured model quality miss is 100% one-sided, audit the deterministic plumbing before tuning the model" — and only a full-pipeline eval (not the model in isolation) makes the composition visible. [failure-story][governance/security][engineering]

4. **2026-07-02 — The answer the door let through and the validator swallowed.** The web_search go-live proved the entire egress chain live (first governed outbound GET, HTTP 200) — and then PGOV Stage-5 leakage held the answer on the way out (cosine 0.930 ≥ 0.85) because a faithful relay of *public* search results is ~verbatim to its source. Two individually-correct decisions (web content stays untrusted; don't echo untrusted content) collided. Fixed with a fifth provenance tier `UNTRUSTED_WEB` (untrusted for the action-lock, exempt from the leak feed only) — a one-line behavioural delta. *Insight:* "the output validator has a direction, not just a similarity"; a verbatim-echo control keyed on cosine alone cannot tell "leaked what you didn't ask for" from "answered with the public thing you did ask for." [governance/security][failure-story]

5. **2026-06-26 — The "done" signal that fired once per task.** The harness reported COMPLETE at the first per-task SUMMARY while a *second* build ran orphaned and the 14B wasn't restored; the agent saw "done," went to look, and killed the run that was about to finish cleanly — the confident-but-early "done" is what caused the interference. Fixing it surfaced three more bugs only a live run shows (terminal-phase-without-SUMMARY hang; stale per-box swap-state falsely completing a fresh run; cumulative-SUMMARY shape mismatch). *Insight:* "a completion signal has to be the thing that's true once, at the end — not the thing that's true after every step," and a false 'done' is dangerous precisely because a human or agent acts on it. [failure-story][engineering]

6. **2026-06-28 — The two clocks and the reaper.** Co-residency telemetry study (community-grade). Intel level-zero stamps GPU samples on a clock ~27.7h offset from socwatch; rescued by trusting the unreliable clock's *linearity* (anchor its [min,max] onto the reliable clock's window), never its zero — validated because the remapped GPU-busy spike landed exactly on the power spike. Separately, a "reaper" silently killed background sweeps twice → diagnose what survives (foreground) and switch modes. *Finding:* concurrent SDXL starves the resident 14B to ~1% throughput via GPU compute *scheduling* exhaustion, not bandwidth or thermal (GPU pinned 1.95 GHz, zero throttle); NPU read 0.0 W twelve times over, proving the pure-GPU stack. [engineering][community/OSS][failure-story]

7. **2026-06-29 — The upgrade that didn't speed up generation, and the browser that faked a regression.** A background browser compositor faked a 14% speculative-decoding regression that survived three internal-consistency checks; nearly written up as a version regression until the operator noted the box wasn't quiet. *Insight:* "measure the environment, not just the model" — and a single up-or-down number lies: generation throughput was flat across the OpenVINO bump while prefill was ~30% faster and VLM TTFT ~19% faster. Includes two honest *negatives* (CPU-draft spec-decode a 13% loss on unified memory; KV-precision RAM a reported null because a load-time GPU pool is invisible to host sampling). [failure-story][engineering][community/OSS]

8. **2026-06-27 — The style pack that ate the prompt.** Fusing a strong flat-vector LoRA into base SDXL produced "gorgeous, confident, prompt-deaf" images — coherent but unconditioned, because fusion algebraically overwrites the cross-attention weights that carry text conditioning (INT8 quantization compounds it). Cracked by a *control*, not another knob: run known-good RealVisXL through the identical harness (it behaved → harness innocent). Product changed shape to a runtime-applied, never-fused adapter. *Insight:* "coherent is not conditioned — when a generative model produces confident output that ignores the input, suspect the weights, not the prompt, and prove it with a control." [failure-story][engineering]

9. **2026-06-29 — The benchmark that copied production's homework.** A sibling's KV-cache sweep produced numbers that looked like data but weren't — it inherited production's `cache_size=3`, correct for short chat turns and catastrophic for a 32K context (needs 5.0 GiB → eviction thrash → TTFT 310s with minute-scale variance; flat memory column). Rebuilt as a standing harness sizing the pool per regime; 32K FP16 went 310,715ms → 175,725ms (std 217ms). Also a mis-called "thermal" confound that was really a cold-clock ramp (warm-up gets *faster*, throttle gets slower) — a mechanism narrated with more confidence than the temperature trace carried. *Insight:* "a benchmark harness must not inherit production config it doesn't understand; when a result is both slow and high-variance, suspect the harness before the hardware." Invalid run quarantined, not deleted. [failure-story][engineering][community/OSS]

10. **2026-06-26 — Shipping the proven thing live, not dormant-with-a-flip.** The LA's correction — "stop making the mature functions dormant" — after the agent had turned "ship dormant" into a blanket reflex and applied it to a demonstrably-working feature, forcing the operator to babysit an uncommitted `enabled=true` flip while the repo *lied* about what functioned. Produces the durable three-bucket doctrine: proven→live; unproven-on-hardware→prove then live; air-gap/privacy egress→welded until the operator's deliberate ceremony. [human-AI-collaboration][process][governance/security]

11. **2026-07-02 — The approval I was about to build for a button that does nothing.** An LA-decided rung-2 approval gate was about to ship for a `generate_image` tool that — on reading the code — is a *directive shim* that generates nothing (real generation only runs in the operator-typed `/imagine` path). A per-batch approval on it would train the operator to click through while claiming a protection the system doesn't have. Stopped and surfaced the moved premise; LA approved the reframe. *Insight:* "verify the premise on disk before building the decision — a control that protects a threat the code cannot express is friction, not security"; a decided premise meeting contradicting code is a stop-and-surface, not a build-faithfully-around. [governance/security][process][human-AI-collaboration]

12. **2026-07-02 — The endpoint the docs swore was fine returned 401.** The egress ceremony worked perfectly and Kagi answered 401 — an inherited, never-re-verified fact: v0 was deprecated. A four-axis correction that had to move as one unit (v0→v1, GET→POST, Bot→Bearer, query-param→JSON-body). Held the "exactly one network client, exactly one door" invariant by extending the frozen egress door *additively* (keyword-only `method`/`json_body`, every prior GET caller byte-identical on the wire) rather than adding a second HTTP client — "the easier diff and the worse architecture." *Insight:* re-verify every axis of an external contract against the live service with the real credential before depending on it; the controls were all correct, the inherited fact was the whole defect. [failure-story][community/OSS][governance/security]

13. **2026-07-01 — Measuring the intelligence, not just the software.** Genesis of `evals/` — the first model-quality harness (three golden suites, `python -m evals.run`, fail-closed exit codes with teeth). The judgment gem is the *regression grammar*: a case that failed in the baseline and still fails is NOT a regression — it's a tracked deficiency, which is exactly how ISS-3-shaped model misses become data instead of noise; refreshing a baseline is a deliberate reviewed act whose git diff names every changed verdict. Directly AIGP-relevant (measuring, baselining, and governing model behaviour). [engineering][governance/security][process]

*Runner-up gems (strong, but a notch below): 2026-07-01 "Retiring the homemade dialect for the format the model was trained on" (regex tool-format silently failing on its own documentation; native JSON + xgrammar composes with spec-decode+streaming, proven empirically) [engineering][governance/security]; 2026-07-01 "Packing the house before the fire" (first off-box backup in 8 months; not one of five live repos had a git remote — "disaster-recovery posture is part of security posture") [governance/security][failure-story]; 2026-07-02 "A fingerprint on the way out: the egress envelope" (Windows-Hello turn-scoped egress consent; the behaviour-level test caught that the old lock wasn't removed — "when you replace a control, delete the old one in the same breath") [governance/security][failure-story]; 2026-07-02 "The idle 48 TOPS finally earns its keep" (NPU offload 13.6×; fail-SOFT in a fail-closed codebase — "the failure mode has to fit the feature: an optimisation that bricks boot is worse than a slower embedder") [engineering][governance/security].*

---

## 3. LA MOMENTS (the human-behaviour gold)

The through-line: the non-technical LA repeatedly (a) asks the *strategic* question that reframes the technical work, (b) corrects over-caution and over-engineering, (c) catches operational waste, (d) owns every posture/ceremony/permission call, and (e) supplies a "this feels wrong" gut check that research then vindicates.

- **The question that started the pivot** (2026-06-26, The lever): "is this thing fundamentally flawed, is there engineering we're missing, or are the local models simply not smart enough? — use your expertise and trusted sources, not your impressions." Then approved the whole re-weight with one line: "I approve of the full recommendation." The best-of-N era exists because the LA asked the right question and demanded evidence over impressions.
- **"stop making the mature functions dormant"** (2026-06-26, Shipping the proven thing live): the LA had been carrying an uncommitted `enabled=true` flip on every merge; his correction became the three-bucket doctrine.
- **"task 1 was already finished and parked again yet you didn't automatically do anything. very wasteful."** (2026-06-26, The system that parked good work): caught the agent watching the wrong signal for twelve minutes → produced `watch.py` (fire-and-wait-90-min became watch-and-react-in-seconds).
- **Governance sign-off on widening a coder's destructive permissions** (2026-06-26, same): letting the sandboxed coder `rm` its own temp files was a governance call the classifier rightly blocked until the LA approved.
- **Comprehension-gate pushback that collapsed an over-designed phase** (2026-06-30, SEAM A): the LA challenged the one measured-fact assumption ("never co-reside") the whole "ASSETS swap phase" rested on; the real fact (14B + image-gen co-reside fine at ~26 GB) collapsed a week-old design into a few lines at the approve seam.
- **Content-attestation ceremony judgment** (2026-06-27, The style pack): the LA reasoned /illustrate and /cartoon aren't uncensored finetunes so there's nothing for that gate to attest — drop the ceremony that attests nothing, keep every cryptographic integrity control that's load-bearing.
- **SSH-keys-to-cloud call** (2026-07-01, backup): the permission classifier balked at SSH keys heading to OneDrive; rather than route around the objection, the agent put it to the LA, who chose the air-gapped USB leg over convenience.
- **The web_search egress ceremony itself** — LA-present, the first BlarAI runtime socket to leave the box; and the string of decisions D3 (retire legacy fallback now, no soak), D4 (CAR carries the real URL for defense-in-depth), D5 (the whole trust-friction rework), and the N=3 dial on the egress envelope.
- **The rung-1 framing correction** (2026-07-02, The lock I lifted): the LA pushed back on a "provenance-keyed" exemption as ambiguous under mixed content; the honest axis turned out to be the *tool's* bounded danger, not the content's provenance — a sharper design than the one inherited.
- **The reframe approval on rung 2** (2026-07-02): the operating model working as designed — a decided shape met contradicting code, the agent stopped and surfaced, the LA approved the reframe rather than forcing a friction-only gate.
- **"looks really good" + the sound defect** (spillover 2026-07-03, the deck): the LA's live run returned one visual pass and one gut-level design objection (synthesized sound felt counter-productive); research then vindicated him twice (professional-deck consensus + the Irrelevant Sound Effect literature). "The as-built was evidence of what was tried, not proof it was right."

---

## 4. MOTIFS (in-chunk + cross-era checks for the synthesizer)

1. **Live-verify as a bug-finding instrument (mock-vs-live).** The single densest motif here — the four-bugs entry, the done-signal, coherent-not-conditioned, chat-poisoning (spillover), hires-OOM (spillover). *Cross-era:* this is the canonical lesson class (15+ numbers, per the self-audit); a synthesizer should collect every era's "green suite / live run caught X" and treat this chunk as the class's high-water mark.
2. **Composition bugs — individually-correct parts, wrong whole.** The unreachable ALLOW (three fail-closed defaults), the leak-validator swallowing a relay, the done-signal, the SEAM-A over-generalized constraint. *Cross-era:* grep for "each individually correct" / "composed into"; likely echoes in PA-adjudication and fail-closed-hardening eras.
3. **Structural absence / dormant-done-right / built-not-registered.** The dormant critic, web_search Part B ("everything except the door-opening"), the inert generation-consent seam, the generate_image shim. Explicitly cites the #655 url_adjudicator pattern and the security_by_design "structural absence over configuration" principle. *Cross-era:* check the air-gap-removal and egress eras and the security-principles doctrine.
4. **Measure-the-environment / benchmark hygiene.** Browser faking a regression, inherited `cache_size=3`, two-clock skew, cold-clock-not-thermal, MoE prefill/decode asymmetry. Feeds the OpenVINO community-contribution thread. *Cross-era:* trace the perf-dataset lineage forward and back; this chunk is a perf-methodology cluster.
5. **Route around the weak model's worst skill (lesson 180).** Best-of-N vs serial self-correction. *Cross-era:* other model-capability / dispatch eras.
6. **Verify the premise/contract before building on it.** SEAM A (design doc is a hypothesis), Kagi 401 (docs vs live service), rung-2 shim (decided premise vs code), EAGLE-3 (release-note vs usable binding). *Cross-era:* recurring; pairs with the LA's "treat technical claims as hypotheses."
7. **Consent grain / judgeability lives on the action, not the content.** The entire #723 D5 rework (rungs 1/2/3). Deeply AIGP-relevant. *Cross-era:* the governance thread — air-gap-removal ceremony, PA single-adjudication-door doctrine.
8. **Captured-pipe deadlock recurrence (lesson 161).** Tee-Object hung the OVMS launcher wrapper; the codebase had already solved it (#670). *Cross-era:* grep #670 / "captured pipe" / "file-redirect".
9. **The lessons-list stops compounding (meta).** Surfaces in spillover (self-audit): lessons learned faster than practice, third-instance-rule born, LESSONS.md/FIELD_NOTES.md split. *Cross-era:* every chunk should feed the canonical-tier consolidation.

---

## 5. WASTE PROFILE (est. % of chunk tokens)

This chunk is unusually *high-signal* — most entries are genuinely narrative with named trade-offs — but the entries are also long, and each carries a heavy bookkeeping trailer.

- **Genuinely-narrative ~60%.** The bulk. The gem entries and most failure narratives earn their length.
- **Changelog-shaped ~15%.** The `*(commits … gate N/0 …)*` trailer on every single entry, plus two entries that are mostly enumerated bookkeeping: *"Retiring the dialect the day after it stopped being spoken"* (a full 22-case tc-parse/tc-disp/tc-adv re-baseline ledger — very high token cost, near-zero stranger value), and the enumerated golden-case flips inside *"Building everything except the door-opening"* and *"A fingerprint on the way out."*
- **Duplicated-in-LESSONS ~10%.** The **Lesson N** / **Recurrence of lesson N** / **Proposed lesson** blocks — by design also in LESSONS.md (the distilled value, but duplicated for a cold archive). Examples: lessons 199/200/201 blocks, the lesson-8/161/183/188 recurrence tallies.
- **Status-shaped ~8%.** Entries that are more measurement/state-report than lesson: *"Measuring the ceiling instead of guessing it"* (#695, partly), *"The MoE bargain"* (partly a numbers report), *"Building everything except the door-opening"* (a dormant-build status wrapped around one real lesson).
- **Superseded-by-later-events ~7%.** Intermediate dormant/pending states and corrected overclaims: the rung-1 entry's payoff claim was corrected by rung-3; rung-3's ADR claim was corrected by the chat-poisoning entry; several "Next:" dormant-pending states resolved at the actual ceremony. Examples: *"The lock I lifted by naming what it was actually guarding"* (overclaim later corrected), the pre-401 dormant Kagi build state, *"Building everything except the door-opening."*

---

## 6. CURATION VERDICTS

### KEEP-HOT (must stay instantly findable — the exceptional few)
- **2026-06-26 — The lever I'd built three reviewers to avoid finding** (the strategic-reversal centerpiece; portfolio + AIGP gold)
- **2026-06-27 — The four bugs the green suite swore weren't there** (canonical live-verify-as-instrument)
- **2026-07-02 — The over-denial that turned out to be unreachable ALLOW** (the composition-bug masterpiece; audit-plumbing-before-tuning)
- **2026-07-02 — The answer the door let through and the validator swallowed** (governance: the validator has a direction, not just a similarity)
- **2026-06-26 — Shipping the proven thing live, not dormant-with-a-flip** (the three-bucket doctrine + the LA's defining correction)
- **2026-07-01 — Measuring the intelligence, not just the software** (evals-harness genesis; the regression-grammar judgment — directly AIGP)

### ARCHIVE-WHOLE (safe in a cold volume — the default)
All remaining in-range entries, including several strong-but-archivable narratives whose lessons already live in KEEP-HOT or LESSONS.md:
- 2026-06-26 — The critic that costs nothing when silent
- 2026-06-26 — Moving the design critique to where the GPU is actually free
- 2026-06-26 — The "done" signal that fired once per task *(strong; its lesson is well-covered by the KEEP-HOT four-bugs + done-signal class)*
- 2026-06-26 — The system that parked good work, and learning to watch it
- 2026-06-27 — Routing around the weak model's worst skill (best-of-N, #689)
- 2026-06-27 — The test the coder isn't allowed to write (the shared oracle, #690)
- 2026-06-27 — Bounding the run from both sides (the task envelope, #691)
- 2026-06-27 — Measuring the ceiling instead of guessing it (concurrency, #695)
- 2026-06-27 — The style pack that ate the prompt *(memorable; "coherent is not conditioned" is safely captured in LESSONS 202)*
- 2026-06-28 — The MoE bargain, and the pipe I'd been warned about
- 2026-06-28 — The two clocks and the reaper *(excellent methodology; archive with the perf dataset it produced)*
- 2026-06-29 — The version-lag that closed onto a deeper wall (OpenVINO/EAGLE-3, #707)
- 2026-06-29 — The upgrade that didn't speed up generation, and the browser that faked a regression *(borderline KEEP; "measure the environment" is lesson 8, already canonical)*
- 2026-06-29 — The benchmark that copied production's homework (#709)
- 2026-06-30 — The seam that wasn't where the map said it was (SEAM A, #714)
- 2026-06-30 — Giving the buttons back to the operator (#712)
- 2026-07-01 — Retiring the homemade dialect for the format the model was trained on (#718)
- 2026-07-01 — Packing the house before the fire (backup)
- 2026-07-02 — The idle 48 TOPS finally earns its keep (#720)
- 2026-07-02 — Giving the model hands that cannot open the door (#719)
- 2026-07-02 — The yardstick caught its first bug the night it was built
- 2026-07-02 — Retiring the dialect the day after it stopped being spoken *(mostly a re-baseline ledger; archive)*
- 2026-07-02 — Building everything except the door-opening
- 2026-07-02 — The endpoint the docs swore was fine returned 401 *(strong failure story; archive — external-contract lesson is transferable but bounded)*
- 2026-07-02 — The lock I lifted by naming what it was actually guarding (#723 rung 1)
- 2026-07-02 — A fingerprint on the way out: the egress envelope (#723 rung 3)
- 2026-07-02 — The approval I was about to build for a button that does nothing (#723 rung 2) *(strong; "verify the premise on disk" is well-covered)*

*Note for the synthesizer:* three near-adjacent entries (2026-06-26 "The lever", 2026-06-26 "Shipping the proven thing live", 2026-06-27 the best-of-N build) tell one continuous strategy-pivot story; if the archive keeps only the pivot, keep "The lever" as its anchor. The #723 rung-1/2/3 + chat-poisoning entries (last four, some in spillover) form one self-correcting sequence best read together.
