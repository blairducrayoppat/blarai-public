# Journal Mining — Chunk 1 of 7

**Range:** BUILD_JOURNAL.md lines 1–2598 · **Entries:** ~123 · **Dates:** 2026-05-21 → 2026-06-07

---

## 1. ERA

This is BlarAI's **origin era** — the founding two-and-a-half weeks in which the project's entire engineering culture was forged in public. It opens on a pivot: abandoning a failed "agent factory" (259 automated sessions, only 15 that touched real code) for direct product-building, one verified-live capability at a time. From there BlarAI matures fast — core chat fixes, first tool use, an honest benchmark baseline (~8 tok/s), speculative decoding, document loading, then a whole **native WinUI 3 Windows app** with streaming markdown, multimodal attachments, persistent semantic memory, voice (Whisper+Kokoro), and vision (Qwen3-VL-8B). Then the pivot that defines the rest of the corpus: a **16-agent adversarial security audit** (2026-06-03) finds one Critical + eighteen High, nearly all of the shape "built but switched off" (TPM trust-root wired to nothing, PA signing key in git cleartext, air-gap enforced only by *absence* of code, plaintext at rest). The Lead Architect (LA) sets the campaign gate — build the walls **before** the air-gap ever comes off — and the back half is a relentless hardening arc: TPM-sealed keys, an egress kill-switch, an at-rest encryption spine (DEK envelope, born-encrypted stores), per-boot mTLS, signed weight manifests, provenance-based trust (ADR-023). It culminates in **the first production-posture prompt answered on real hardware (2026-06-06)** and an "Automation Wave" (Sprint 16) that starts making the seams self-test. The through-line motif — coined and re-coined here — is *"the screen is the only oracle; mocks lie."*

---

## 2. GEMS

1. **2026-05-21 — The pivot, and the first real shipping.** Counted honestly, a fleet of "autonomous" agents had run 259 committing sessions and only 15 touched real code — the rest was "a machine for producing the appearance of work." The fix was a working loop: agent builds → reviewed against real code → **human verifies live** → commit only if it survives. *The origin decision of the whole project.* `[process][human-AI-collaboration][failure-story]`

2. **2026-05-21 — Measuring before improving: the baseline.** The very first benchmark deleted two false beliefs in two minutes: speculative decoding silently wasn't running (it errored and fell back), and the GPU thermally throttles (9.4→8.1 tok/s), which nearly got mis-recorded as "spec-decode is slower." "A benchmark's job is not to make you feel good about your project — it is to tell you what is true." `[engineering][process]`

3. **2026-05-22 — An overnight session: faster, and measured honestly.** Spec-decode fixed by moving one option (`num_assistant_tokens`) to the right engine layer; the seductive first number said "2× faster" and was thermal contamination — the honest figure was **1.4× (15s vs 22s)**, and "the true number is the one that goes in the log even though 2 looked better." Same night, the prompt-injection "PWNED" test failed honestly and the feature was parked on a branch rather than shipped. `[engineering][failure-story][governance/security]`

4. **2026-05-22 — Document reading works — and a lesson I had just written, repeated.** Lesson 6 ("what you configure is not what runs") recurred hours after being used elsewhere; includes a remarkable **first-person confession** of the agent reading past the literal word `else` in `draft_model_dir if draft_model_dir else DRAFT_MODEL_OV_PATH`. Caught by reading the runtime startup log, not any test. `[engineering][failure-story][human-AI-collaboration]`

5. **2026-05-22 — Provenance-aware redaction: what the tests passed and the screen failed.** 14 green tests, then broken twice on the live screen (the chat window ate square-bracket markers as formatting; the model leaked a phone number in fragments below the detector's shape-match). Introduces the inverse-redaction concept (hide what's *not* verifiably the user's) and is **the first artifact deliberately mapped to the IAPP AIGP certification body of knowledge.** `[governance/security][failure-story]`

6. **2026-05-22 — The instrument, and a hand-off to a second me / Sharing the 14B.** Names "architectural-decision-vs-code drift" (ADR-012 said single shared model; code compiled it twice → 17 GB RAM). Writes a ~300-line handoff brief and hands it to **a second Claude instance in a parallel window**, which independently finds the safety gap (the draft model had no integrity manifest). Also the origin of the worktree lesson: a `git checkout` on the shared tree raced a commit onto the wrong branch. Closure: 17 GB→8.7 GB GPU, boot 43–56s→29.9s, ~26s reclaimed per boot. `[engineering][process][human-AI-collaboration]`

7. **2026-05-26 — Pausing the safety feature, on purpose.** The LA, several days away, returns: *"if we don't get major development done I am going to potentially quit this project altogether."* Layer 3 had grown into a five-commit security architecture guarding a system whose only tool reads a clock — "the trade is on the wrong side." Paused (not deleted) behind a flag; the entry is explicitly the apology for over-build. *The most human, highest-stakes moment in the corpus.* `[process][human-AI-collaboration][failure-story]`

8. **2026-05-22 — Locking the door the documents come through (FrozenInstanceError).** Three full green sweeps blessed code that couldn't run one second in production: the test's `SimpleNamespace` mock allowed attribute assignment while the real frozen dataclass didn't. "A test that uses a mock with different mutability semantics than the production type is, on that exact dimension, no test at all." The canonical mock-shape-divergence gem. `[engineering][failure-story]`

9. **2026-06-03 — The privilege boundary, a fourth time: this time I moved the wall.** The capstone of a running motif (an env var, then package-import context, then UIPI drag-drop all failed to cross a UAC elevation). Here, de-elevating the WinUI window from admin to a hand-built filtered medium-integrity token *was itself* the fix for broken file-attach: "sometimes the hardening **is** the fix, and the thing you were about to debug at the feature layer was a privilege problem the whole time." `[engineering][governance/security]`

10. **2026-06-03 — A trust root built on hardware nobody had checked.** The documented trust root was Intel SGX — hardware Intel removed from client CPUs years ago and this laptop never had; "a phantom, a sentence describing hardware that was never there." Then the LA overruled Claude's own sloppy inference that the chip wasn't Pluton, and was right — "when its owner contradicts your inference, the owner wins." Re-rooted on TPM 2.0; only the real chip revealed `NTE_BAD_FLAGS` on a flag the docs said was valid. `[governance/security][failure-story][human-AI-collaboration]`

11. **2026-06-03 — The security audit I verified, and the presentation I didn't.** A **16-agent adversarial audit** (7 domain auditors, independent verifiers, completeness critic, red-team synthesis, every claim file-cited): 1 Critical + 18 High, theme "built but switched off." Then the deck shipped with broken diagrams twice because it was "verified" with a self-invented lint instead of the real Mermaid parser — "the vehicle that delivers a verified result is its own artifact, and must be verified against the tool that will actually consume it." Sets the whole hardening campaign in motion. `[governance/security][process][failure-story]`

12. **2026-06-04 — The fix that logged a lie, and the capability cut I almost made without asking.** VLM eviction logged "VLM memory released" while the OS reclaimed nothing (OpenVINO's GPU plugin pools native allocations; only process exit frees them) — "not a malicious lie; a hopeful one." The true cause was a 50-megapixel image. The LA stopped the "obvious" downscale fix because it would gut *"read the text on the wall"*, and delivered **the escalation-boundary rule**: *"Design and technical decisions that have large impacts on the quality of the response is the kind of hard escalation we should be having to me, not stuff asking me about Git which I know nothing about."* `[human-AI-collaboration][governance/security][failure-story]`

13. **2026-06-04 — The operator looked at the lock and said it felt wrong, and he was right.** A shipped, green, live-verified action-lock — and the non-developer LA's gut named two security anti-patterns the expert had stopped seeing: locking a *clock* because untrusted text was present (friction, zero benefit), and a `/trust` prompt asking the least-equipped person to vouch (click-through theatre). Lesson 38: "a non-expert's 'this feels wrong' about a security experience is rarely noise — it is the smell test the expert stopped running." `[governance/security][human-AI-collaboration]`

14. **2026-06-05 — The premise nobody checked: there were never "decades of data on disk."** The encryption ADR, the SDV, the roadmap, and the whole review chain (Claude included) all asserted "decades of the user's private data sitting exposed in plaintext." The LA checked the actual files: 107 chunks + 59 sessions of dev scaffolding, no real data yet. A false, plausible premise propagated across four documents because each author inherited it from the last. Reframed to the stronger "encrypt now, **born-encrypted**, before first real use." `[governance/security][failure-story][human-AI-collaboration]`

15. **2026-06-06 — Mocks pass, seams break + The night BlarAI first answered a prompt in production.** A 2,163-green suite, and the first human sentence broke it: the launcher wired the gateway to the Policy Agent's port (5000) not the Orchestrator's (5001), and an *earlier correct fix* (teaching the PA to answer the handshake) had **masked** the misroute — "a correct downstream fix moved the symptom past the gate that used to catch it." The LA turned the night into doctrine (`TEST_GOVERNANCE §2.7`: automate the real seam, don't mock it) rather than three patches — "a blind spot this structural is not a bug to fix, it is a class to outlaw." Ends on the milestone: first production-posture prompt (TPM keys, per-boot mTLS) answered on real hardware. Also lesson 66: "a test can lock a *defect*, not just a feature — 'it's test-locked' is not proof 'it's a decision.'" `[engineering][process][human-AI-collaboration][failure-story]`

16. **2026-06-05 — The anti-pattern the sprint was built to kill, caught inside the sprint.** A pristine tamper-evident audit sink with 38 green teeth-tests — and it was *inert*, because the live PA factory never passed it the sink. The audit's own central finding ("built but wired into nothing") recurred **inside the sprint built to close it**, and a fully green suite hid it completely; a human reading the one production file the suite never exercised caught it. The regression lock added afterward asserts the *real* factory yields `has_audit_log == True`. `[engineering][process][failure-story]`

*(Runners-up worth a glance: 2026-06-04 "Five locks in parallel, and the merge that landed on the wrong branch" — cwd-drift printed "OK" five times while main never moved [lesson 35]; 2026-06-04 "The detector that flagged the assistant for doing its job" — cosine leakage suppressed a correct summary, "off-and-redesign beats on-and-wrong," seeded ADR-023 provenance tiers; 2026-06-02 "Making the journal discipline standing instruction" — "continuity of intent is a file-system property, not a memory property.")*

---

## 3. LA MOMENTS

The non-technical LA visibly steered outcomes again and again — this is the human-behaviour spine of the era:

- **The near-quit (2026-05-26):** "if we don't get major development done I am going to potentially quit this project altogether" — directly forced the Layer-3 pause and the return to shipping visible capability.
- **Frictionless-by-design (2026-05-22, "Engineer for the use case"):** "security and privacy first by design is important but it should also be configurable to a more frictionless setup… my personal AI system." Reframed a locked-correctly-but-unusable control into layered, auditable *informed risk acceptance*. Also gave the misconfiguration-is-an-attack-vector directive ("use best practices").
- **The escalation-boundary correction (2026-06-04):** the "hard escalation… not stuff asking me about Git" line — permanently split what he owns (capability/quality/security-posture) from what Claude owns (wiring). Recurs as his catching Claude *over*-asking: "did you really just stop to ask me if I want you to implement the thing we have been building?" and "I don't see why you can't do this."
- **Owner-of-the-machine wins (2026-06-03):** overruled Claude's wrong "not Pluton" inference from firmware strings; was correct.
- **The security smell test (2026-06-04):** "is this locking mechanism really best practice? this whole trusting process seems bad" — a non-expert caught two shipped anti-patterns.
- **Checking the premise (2026-06-05):** personally verified on disk that there were *not* "decades of data" the review chain claimed.
- **Debt is not a decision (2026-06-06 / 06-07):** "Fix this so it doesn't keep happening — is there really more than one correct answer?" and "why are you even considering not closing the debt fully?" — twice refused Claude's attempts to escalate plumbing/scope as governance.
- **Set the campaign gate:** "real security before real memory," air-gap comes off only after the walls are built (#598); walked the eight air-gap decisions one-per-turn and **chose the strict option at every fork** (ADR-027, ADR-023).
- **Refused the un-testable-UI excuse:** "the whole point is to take the human out of the verification loop" — forcing the pywinauto WinUI harness into existence.
- **Journal discipline as his instrument:** repeatedly asked whether future agents would auto-write portfolio-grade entries (→ codified into CLAUDE.md); "make the journal entries now, leave no loss if the session ends."

---

## 4. MOTIFS

Recurring in this chunk (with what a cross-era synthesizer should verify downstream):

- **"The screen is the only oracle / mocks lie"** — the dominant, near-per-entry lesson. *Check:* does it eventually get *replaced* by real automated seam coverage after the §2.7 mandate (2026-06-06), or does the manual-live-verify pattern persist for months?
- **"Built but wired into nothing"** (TPM root, leakage detector, audit sink, session-store factory, cert mint vs config) — recurs constantly, each time spawning a "production-wiring regression lock." *Check:* does the lock pattern actually stop recurrences in later eras, or does the class keep reappearing?
- **Trust-boundary crossings** — env var, package-import context, UIPI drag-drop, least-privilege all fail to cross a UAC elevation. *Check:* whether the "channel defined to cross the boundary" lesson (11) generalizes to the network-egress boundary later.
- **Measure, don't guess** — the GPU compile cache measured to break-even/nothing **three separate times**; thermal contamination faked "2×" repeatedly. *Check:* whether later eras still re-litigate settled measurements.
- **Provenance ≠ trust** — grows from redaction → retrieved memory → VLM output → the whole ADR-023 trust-tier axis. *Check:* whether this becomes the stable organizing principle it promises to be.
- **Over-build vs "mature not minimal"** — Layer 3 arc, hnswlib→brute-force, isochronous-timing deferral. *Check:* recurrence of scope-creep-into-security.
- **Escalation boundary (LA=capability/quality; Claude=wiring)** — mis-set and corrected several times in this chunk alone. *Check:* does it settle or keep slipping?
- **Parallel-fleet mechanics** — worktrees, journal-fragment inbox, cwd-drift landing on wrong branches. *Check:* the branch-guard's durability across eras.
- **Honest absence** — `not_measured` lists, "committed ≠ done," naming the reasoned-not-measured piece (which then broke exactly there). *Check:* consistency of this discipline under later time pressure.

---

## 5. WASTE PROFILE (by tokens)

- **Genuinely-narrative — ~40%.** The pivot, the two audits, every LA moment, the first production prompt, the honest failure stories. This is the portfolio gold and the reason the era is worth keeping at all.
- **Changelog-shaped — ~25%.** The long June-6 mTLS/cert-provisioning debugging chain and the Sprint-16 stream reports read as single-defect-fix-plus-trade-off-paragraph. Examples: *"The config and the mint were speaking different languages," "The transport path that was designed but never wired," "The protocol argument the docs bury in a footnote,"* and the B1/C/E/F stream entries.
- **Duplicated-in-LESSONS — ~15%.** Most entries restate a now-numbered lesson (6, 11, 12, 13, 16, 30, 32, 35…); the lesson is the compounding surface, the prose is archive. Examples: *"The privilege boundary, a third time," "The reasoned-not-measured piece was exactly the one that broke," "The gate turned back on, pointed the other way."*
- **Superseded-by-later-events — ~12%.** Examples: the whole Layer-3 sub-arc (paused, then dissolved into ADR-023 provenance tiers); *"The detector that was watching nothing"* (reverted the next day by *"The detector that flagged the assistant for doing its job"*); the interim `/external` gateway command (replaced by the proper UI gesture).
- **Status-shaped (no lesson) — ~8%.** Examples: *"Building the door without opening it"* (EA-2, deliberately-don't-activate), *"Testing the door before handing over the key"* (EA-3 staging), *"Wiring the key you already had, not building the one you thought you needed"* (mostly "it was already there").

---

## 6. CURATION VERDICTS

### KEEP-HOT (the exceptional few — must stay instantly findable)
- 2026-05-21 — The pivot, and the first real shipping *(origin story of the whole method)*
- 2026-05-26 — Pausing the safety feature, on purpose *(near-quit; the over-build failure)*
- 2026-06-03 — A trust root built on hardware nobody had checked *(SGX phantom / TPM / owner-wins)*
- 2026-06-03 — The security audit I verified, and the presentation I didn't *(16-agent audit; "built but switched off")*
- 2026-06-04 — The fix that logged a lie, and the capability cut I almost made without asking *(the escalation-boundary rule)*
- 2026-06-04 — The operator looked at the lock and said it felt wrong, and he was right *(non-expert security smell test)*
- 2026-06-05 — The premise nobody checked: there were never "decades of data on disk"
- 2026-06-06 — Mocks pass, seams break — and the harness that mocked the seam too *(birth of the §2.7 test-the-seam doctrine)*
- 2026-06-06 — The night BlarAI first answered a prompt in production *(the milestone)*
- 2026-05-22 — Provenance-aware redaction: what the tests passed and the screen failed *(first AIGP-mapped artifact + canonical screen-caught-what-tests-missed)*

### ARCHIVE-WHOLE (default — safe in a cold volume)
Everything else, notably: the entire June-6 mTLS/cert-provisioning debugging sequence (~10 "door"/handshake/port entries); all Sprint-15 EA-1→4b and Sprint-16 stream A–F entries; the privilege-boundary repeats after the first two; the Layer-3 sub-increments and its `/trust`/`/external` UX tail; the web-search W1–W3 mocked-behind-glass entries; the GPU-cache and boot-time measurement entries; the WinUI phase-by-phase build entries (Phase 1–6). Their transferable content already lives in LESSONS.md; the narratives are archive, not hot.
