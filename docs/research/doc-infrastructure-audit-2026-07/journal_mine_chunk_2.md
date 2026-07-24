# Journal Mining — Chunk 2 of 7

**Range:** BUILD_JOURNAL.md lines 2599–5198 (~44 entries). **Era:** 2026-06-07 → 2026-06-10.

---

## 1. ERA

Four days, but the single most consequential arc in the whole corpus: **the decision to remove BlarAI's air-gap**. The project had been "safe by absence" — no runtime module imported a network client, and `egress_guard` welded that shut at the socket layer. This span builds the machinery to open exactly one policy-gated door (Sprint 17's egress stack — allowlist, latched kill-switch, exfil screen — all shipped *dormant*), hardens the boot trust chain and proves it on the real STMicro TPM (recovery-key disaster test, trust-root non-exportability, PCR-seal enforcement), then runs the **#612 capstone deep-dive**: a four-grade-honesty security review the LA reads *before* he signs off. The deep-dive works exactly as designed — it surfaces residuals, and the LA uses it to make the bar *stricter*. The span closes with the #598 GO, the one-door `guarded_fetch` architecture ("URL = authorization"), and the UC-002/003 knowledge-bank + cleaner + ingest program (first real HTML parser, biggest dependency since OpenVINO). It is the transition from *air-gapped-by-construction* to *network-facing-by-deliberate-ceremony*, narrated with unusual candor about what is built vs wired vs proven.

---

## 2. GEMS

1. **2026-06-07 — The recovery key was already there; what was missing was proof it works on a dead machine.** Found the break-glass DEK-recovery *mechanism* already shipped, but every test simulated "TPM gone" by monkeypatching a live sealer one attribute away — not the real disaster. The deliverable was the catastrophe test (provision on machine A, carry only keystore+key to a fresh machine B with a dead chip, decrypt a real payload byte-for-byte). *Mechanism-exists is not disaster-tested; the missing catastrophe test is the actual deliverable* (lesson 78). `[engineering][governance/security][failure-story]`

2. **2026-06-07 — The posture test that passed because the worktree was empty.** A production-security-gate test passed in its worktree only because a `git worktree` has no `models/` dir; on the provisioned main tree the manifest existed and the gate resolved cleanly — the test measured whether models were installed, not whether the gate fired. Fix: assert the *invariant* (fail-closed at *some* security-material gate), never a host-decided error code. *A posture test must own the outcome it asserts on* (lesson 81). `[engineering][failure-story]`

3. **2026-06-07 — The on-chip session: the alarm I withdrew.** Read a `connect(): bad family` symptom correctly (no `socket.AF_HYPERV`) but concluded the architecture was broken and escalated a possible gate re-scope. The LA pushed back in four words — *"didn't we test AF_HYPERV already?"* — and was right: it was a Python 3.11-vs-3.14 interpreter-version gap, mundane. *A conclusion alarming enough to escalate gets checked against evidence already on disk first* (lesson 82). Same session flipped `require_signed_manifest=true` on the real chip. `[governance/security][human-AI-collaboration][failure-story]`

4. **2026-06-07 — The briefing before the irreversible door.** The LA moved the capstone security deep-dive from *after* the air-gap sign-off to *before* it: "a capstone scheduled after the gate can only explain a decision already made; scheduled before it, it can still stop or reshape it," with a remediation loop so his Q&A questions get tasked and resolved before the gate opens (lesson 85). Textbook governance sequencing. `[governance/security][human-AI-collaboration]`

5. **2026-06-08 — The on-chip session I told the agent to make the operator run.** Handed the operator a "paste each command output back" runbook; he stopped it cold: *"It's having me do testing! ... My time is being wasted, again."* Root cause: a human-phrased runbook carried through four layers, none of which asked whether the *agent on the box with shell access* could just do it. Standing principle: the burden of proof sits on routing a step *out* to the human, not on automating it (lesson 86, #629). `[human-AI-collaboration][process]`

6. **2026-06-08 — The after-bookend, and the audit you have to be honest about.** The pre-sign-off capstone deck graded every claim on a four-tier scale — VERIFIED-LIVE / TESTED / BUILT-DORMANT / DESIGNED-DEFERRED — so "we built it" can never masquerade as "it works in anger." Five parallel verifier subagents; the two that *disagreed* produced the most valuable finding (the exfil-screen was doubly dormant: empty allowlist AND unwired screener). The controls that matter most for going online almost all graded BUILT-DORMANT, and the deck said so on the heart slides. `[governance/security][process]`

7. **2026-06-09 — Tightening the gate from inside the deep-dive.** The LA elevated four hardening items (#638/#639/#640/#637) from "deferrable, fails-safe" to gate-blocking — including #637, whose own ticket marked its items "not gate-blocking, ACCEPTED-RESIDUAL." *A decision-informing review earns its keep precisely when the decision-maker uses it to make the bar stricter, not just to confirm what is already there.* `[governance/security][human-AI-collaboration]`

8. **2026-06-09 — The replay window between two correct components.** Ticket named a mechanism (add a `jti` spent-set); the LA (reading the same code) course-corrected it as redundant — single-use was already enforced by the nonce. The *real* bug was subtler: the nonce TTL defaulted to 5s and token validity to 30s, defaulted independently in different files, leaving a **25-second replay hole** — a bug that existed *because* each component was individually correct. Fix tied the two values together (`aligned_nonce_ttl`). *When a ticket names the mechanism, verify it against the code before you build it.* `[engineering][governance/security][failure-story]`

9. **2026-06-09 — The screen that would have strangled the host it guards.** #634 asked for one line: register the exfil-screen onto the armed guard. Taken literally it would have flagged the runtime's own internal IPC (JWT/PII traffic), tripped the kill-switch on the first internal message, and cut ALL egress — a self-inflicted DoS dressed as a security control. Second trap: a clean `Detection(blocked=False)` is a frozen dataclass, always truthy, so the old normaliser would have read it as a hit and blocked the first clean external send. Fix scoped screening to sockets that actually egress externally. `[engineering][governance/security][failure-story]`

10. **2026-06-09 — Reading the silicon instead of guessing it.** Public datasheets were silent on whether the Lunar Lake Core Ultra 7 258V exposes Intel Key Locker. Rather than infer, wrote a self-validating CPUID probe (machine-code shim via ctypes, no compiler) and read `CPUID.(7,0).ECX[23] = 0` — Key Locker is NOT exposed. Closed a security limb "for good, not deferred," and produced *novel, shareable Lunar Lake data* for an upstream Intel/OpenVINO contributor. `[engineering][community/OSS]`

11. **2026-06-09 — The PCR seal, and the door Windows wouldn't let me forge.** Proving a measured-boot seal on the real TPM, the negative test (extend a PCR, watch the seal refuse) hit `TPM_E_COMMAND_BLOCKED` — Windows blocks user-mode `PCR_Extend`. The reflex was to engineer around it; the right read was the opposite: *that block IS the property* — a process cannot forge PCR state through the OS. Reframed the block as evidence and proved the binding by sealing a second object to a different PCR value. *When the platform refuses your test action, the refusal may be the very property you set out to prove* (lesson 197). `[engineering][governance/security][failure-story]`

12. **2026-06-10 — The door we cut into the wall.** THE air-gap-removal build. One sanctioned external-fetch path (`guarded_fetch.fetch_external`); every future web tool fetches through the same guarded seam. Load-bearing governance call, from the LA: "URL = authorization" — the PA per-URL verdict governs alone; ALLOW proceeds with *no* extra fingerprint. Resisted the reflex to bolt mandatory consent onto every ALLOW because *a fingerprint on every fetch trains the operator to rubber-stamp, corroding the exact signal the ESCALATE tier exists to carry.* Ships with no adjudicator wired, so every fetch DENIES — the honest dormant state, not a faked verdict. `[governance/security][engineering]`

13. **2026-06-10 — Three things the merge gate caught before the door ever opened.** Reviewing the freshly-cut hole while still DENY-by-default (zero exposure): an SSRF where a *named* host DNS-resolving to `169.254.169.254`/private/CGNAT got its internal IP pinned and admitted; a memory-exhaustion DoS where an 8-MiB body cap was *decorative* because `client.get()` read the whole body before the slice (fixed to streamed-read-to-cap); and a DNS-rebinding TOCTOU that was **named-but-not-closed honestly** (the robust fix is a peer-IP-validating transport, ticketed, not half-built). `[engineering][governance/security][failure-story]`

14. **2026-06-10 — The encrypted store that kept a plaintext fingerprint of its own contents.** The knowledge store held a plaintext `content_sha256` of the cleaned article *beside* the AES-256-GCM ciphertext — a deterministic content hash IS content metadata: an attacker with the stolen DB runs any public article through the deterministic in-repo cleaner, hashes it, and tests membership. The store denied "did he ingest this URL" while answering "did he ingest this article" for free. Fix keyed the digest under HMAC (the pattern *already in the same CREATE TABLE*). *A data map that flatters the store is worse than no data map.* `[governance/security][failure-story]`

15. **2026-06-10 — The lock I proved, then declined to fit.** Having proven PCR-key-binding *enforces* on the chip the day before, the LA decided the production trust-root keys will NOT be PCR-bound. Reasoning worth keeping: *"we proved it works and chose not to use it" is a stronger governance position than either "we couldn't" or "we did it because we could"* — PCR-binding would brick the trust root after every routine BIOS/OS update, a brittle fourth layer against an already-covered physical threat. `[governance/security][human-AI-collaboration]`

*Honorable mentions (strong, near-gem):* **The paste that walked in through the front door** (a parallel path that never met the defenses — /ingest persisted as a forwardable user turn; *absence cannot be forwarded*); **The fingerprint, and the decision I tried to hand back** (LA: "Why are you asking me this? I am a novice..."); **The one store I chose not to encrypt** (encrypting the audit log couples the witness to what it witnesses); **The zeroization that never cleared** (a security control that misrepresents itself is worse than an absent one); **Teaching the journal its own lessons** (AIGP Body of Knowledge restructured 7→4 domains; the deck's framework claims would have been stale).

---

## 3. LA MOMENTS

The richest human-behavior vein in the corpus so far. The LA is non-technical but governs through sharp, well-calibrated judgment:

- **Memory correcting a wrong escalation (2026-06-07):** four words — *"didn't we test AF_HYPERV already?"* — overturned the agent's architecture-is-broken diagnosis. His recall of prior evidence beat the agent's fresh symptom-read.
- **Sequencing the irreversible decision (2026-06-07):** insisted the capstone deep-dive precede the air-gap sign-off, with a remediation loop, so his questions could still change the outcome.
- **Rejecting manufactured decisions (2026-06-07):** annoyed that a Sprint-17-vs-18 *sizing/packing* question was dressed as a governance fork; trained "own the obvious call."
- **"My time is being wasted, again" (2026-06-08):** refused to hand-run automatable tests; forced the automate-first / human-exception principle into doctrine (#629).
- **Making the bar stricter (2026-06-09):** elevated four fails-safe residuals to gate-blocking off the honest register.
- **Reading the code alongside the agent (2026-06-09):** *"don't add the jti set, it's redundant"* — caught a duplicate control before it shipped.
- **Un-raising a bar (2026-06-09):** suspended #640 hours after elevating it — the gate record shows motion in *both* directions, not just the ratchet.
- **"Why haven't you activated it?" (2026-06-09):** pushed the agent past over-caution; finishing his already-decided design was completing his call, not a new fork.
- **"Why are you asking me this? I am a novice. Does this impact security, capability, or performance?" (2026-06-10):** the litmus test in his own words; the Windows-Hello *implementation route* was mechanics, not governance.
- **Informed decline of PCR-binding (2026-06-10)** and **ratifying the audit log as signed-but-not-encrypted (2026-06-10):** two deliberate exceptions to strong defaults, each with the expiry/revisit trigger recorded.
- **Inverting zero-NIC from assumption to precondition (2026-06-10):** turned the guest-VM NIC-less posture into a fail-closed enforced check.
- **The trafilatura gate choice (2026-06-10):** weighed supply-chain thinness vs extraction quality, chose quality (+9 packages, incl. a C-extension parsing attacker bytes) — a capability/security trade only he owns.

---

## 4. MOTIFS

- **Build-the-ceremony-before-it-runs (dormant-on-arrival):** egress stack, ESCALATE consumer, Hello verifier, egress re-arm, the fetch door — all built ahead of their producers and welded shut. *Cross-era check:* enumerate every control shipped dormant and the date each actually activated (manifest-signing in Sprint 16 is the template; Kagi/W4 is the awaited trigger).
- **Built-but-wired-into-nothing / mocks-lie:** semantic router never called in an AO turn (#632), TUI only ever tested against a mock, the doubly-dormant exfil-screen, "tests that never ran are hypotheses" (lesson 83). CLAUDE.md flags this as the project's hardest-won lesson class that "recurred repeatedly." *Cross-era:* count recurrences to see if the structural control ever landed.
- **Read-the-code-not-the-ticket / verify-the-premise:** carve-out where the rule fires not where its name says (76), the redundant jti (638), "test Pluton" named the wrong chip, the deck that went stale in two days, the grep that caught a parallel session. *Cross-era:* ties to the memory rules "verify alarms before escalating" and "trust ticket state not narrative."
- **A red test is a claim about your test first (77, 81):** the rotation check that lied, the worktree-empty posture pass. *Cross-era:* the gate-honesty discipline.
- **Honesty-over-flattery as a governance instrument:** the four-grade scale, "a data map that flatters the store is worse than none," "a control that misrepresents itself is worse than an absent one," named-but-not-closed TOCTOU. *Cross-era:* the whole sanitized-journals-don't-compound doctrine.
- **Defect-vs-decision boundary in practice:** recurs almost every entry — own the mechanical fix, escalate the trade-off. *Cross-era:* the calibration the LA keeps training.
- **Parallel-session collision hygiene:** two competing "Amendment 1"s to ADR-027, the grep catch, the write-to-wrong-checkout recovery. *Cross-era:* worktree discipline maturing.

---

## 5. WASTE PROFILE

Unusually low-waste chunk — this is the corpus's high-water mark for narrative density. Rough token split:

- **Genuinely-narrative: ~62%** — the failure stories, trade-offs, and LA moments above.
- **Duplicated-in-LESSONS: ~15%** — entries whose one-line distilled lesson (75–107, 197) lives in LESSONS.md; the rich failure-context is unique to the journal, only the closing aphorism is redundant. *e.g.,* "The two ways dev_mode lies" (88/89), "The posture the file swears to" (79/80).
- **Superseded-by-later-events: ~10%** — the PCR-seal PoC (proved 06-09, declined 06-10); forward "Next:" punch-lists later resolved. *e.g.,* "The PCR seal..." (the harden-or-leave call was later declined), "The gate-blocker that was already green" (currency drift since reconciled).
- **Status-shaped (thin lesson): ~7%** — merge-gate bookkeeping with only a modest invariant. *e.g.,* "Merge-gating the last two Policy-Agent gate items," "Proving the welded door by knocking on the same wall," "The front door gets a doorbell" (mostly design-log).
- **Changelog-shaped: ~6%** — commit/test-count recitation in the trailer parens; content is fine, form is ledger. *e.g.,* the parenthetical trailers across most entries; "The latch that only a fingerprint may lift" (heavy mechanism recitation).

---

## 6. CURATION VERDICTS

**KEEP-HOT (the exceptional few — must stay instantly findable):**
- 2026-06-10 — The door we cut into the wall *(the air-gap-removal architecture — governance landmark)*
- 2026-06-10 — The lock I proved, then declined to fit *(informed-decline governance)*
- 2026-06-10 — The one store I chose not to encrypt *(exception-to-a-good-default reasoning)*
- 2026-06-07 — The briefing before the irreversible door *(review-before-decision sequencing)*
- 2026-06-08 — The on-chip session I told the agent to make the operator run *(automate-first, LA's time)*
- 2026-06-10 — The fingerprint, and the decision I tried to hand back *(the novice-litmus in his own words)*
- 2026-06-09 — The replay window between two correct components *(seam-between-two-correct-parts bug)*
- 2026-06-09 — The screen that would have strangled the host it guards *(literal-ticket self-DoS)*
- 2026-06-10 — The encrypted store that kept a plaintext fingerprint of its own contents *(membership-oracle)*
- 2026-06-10 — Three things the merge gate caught before the door ever opened *(SSRF/DoS/TOCTOU triple)*
- 2026-06-09 — The PCR seal, and the door Windows wouldn't let me forge *(reframe-the-block, lesson 197)*
- 2026-06-09 — Reading the silicon instead of guessing it *(novel Lunar Lake OSS data)*
- 2026-06-07 — The recovery key was already there... *(mechanism-exists ≠ disaster-tested)*
- 2026-06-08 — The after-bookend, and the audit you have to be honest about *(four-grade honesty scale)*
- 2026-06-10 — The paste that walked in through the front door *(the parallel path that met no defenses)*

**ARCHIVE-WHOLE (safe in a cold volume — the default):** all remaining ~29 entries, including the egress-machinery build pair (06-07), the boot/posture-lock cluster (79/80/81), the WinUI UIA-projection saga (83), the process-leak skip detector (87), the dev_mode/worktree write-slip (88/89), the router/TUI mock-gap pair (90), #638/#634/#643/#637/#639 merge-gate entries, the trust-root and privilege-hardening entries, the audit-retention and idle-unload entries, the lessons-deck build, the "gate-blocker already green" reconciliation, the "deck went stale" presenter session, the trafilatura dependency ceremony, the cleaner-pipeline entry, the ingest-UX "doorbell" entry, and the UC-002/003 four-branch merge. All are solid records; none needs to stay hot.
