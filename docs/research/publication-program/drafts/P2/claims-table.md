---
title: "P2 claims table — When two correct things collide"
piece: P2
status: for-review-panel
prepared: 2026-07-19 (P2 author session); revised 2026-07-19/20 (post-panel: S4/S8/G7/PW/R rows updated)
convention: every load-bearing claim in the draft, typed per AUTHOR_KIT §A (MEASURED / DOCUMENTED-EVENT / INTERPRETATION), with primary source and verification state
---

# P2 claims table

Verification commands and derivations for every row live in `verification-memo.md` (same directory).
"Mirror-public: YES" = the quoted/cited text is verbatim-present in the public mirror's
`BUILD_JOURNAL.md` as checked 2026-07-19 (see privacy-prescreen.md for the exposure audit).

## Global / framing claims

| # | Claim in draft | Type | Primary source | Verified |
|---|---|---|---|---|
| G1 | Project first commit 2026-02-04; ~5.5 months old at writing | DOCUMENTED-EVENT | `git log --reverse` first commit `fc0eda64` (2026-02-04); VERIFIED_FACTS row | 2026-07-19 |
| G2 | Journal: 465 dated entries over first 58 days of journaling, 2026-05-21 → 2026-07-17 | DOCUMENTED-EVENT | VERIFIED_FACTS row (audit pack README ¶ plain-summary); journal born 2026-05-21 | 2026-07-19 (carried; volatile — re-count at publish) |
| G3 | Hardware: Intel Core Ultra 7 258V, Arc 140V iGPU, 32 GB RAM, Windows 11; OpenVINO GenAI runtime; local 14B resident model | DOCUMENTED-EVENT | VERIFIED_FACTS §Hardware (published spec level — same as prior public posts, e.g. OV Discussion #36484) | 2026-07-19 |
| G4 | Audit enumerated seven specimens; synthesis headline said "~8"; re-derivation admitted an eighth | DOCUMENTED-EVENT | `synthesis_journal_gems.md` §B lines 38–45 (lists 7 dated instances under "~8 instances"); VERIFIED_FACTS specimen row; this session's derivation (verification-memo §2) | 2026-07-19 |
| G5 | Specimen criteria (both parts individually correct; fully documented; structural fix shipped) | DOCUMENTED-EVENT (program instruction) | P2 author brief / dispatch scope; applied derivation in verification-memo §2 | 2026-07-19 |
| G6 | "control density / security-first posture" description (fail-closed, deny-by-default, one adjudication door, provenance tags, output validator, signed manifests, multiple locks on egress) | DOCUMENTED-EVENT | CLAUDE.md security_by_design + stack (internal doctrine); all named mechanisms appear in public-mirror journal entries | 2026-07-19 |
| G7 | "no cloud anywhere in the model-inference path; the system's only network access is a single deliberate, policy-gated door, whose first live use is specimen 5" | DOCUMENTED-EVENT (public framing) | Standing doctrine; egress = policy-gated named doors only. RESOLVED 2026-07-19/20 (privacy Y-2 fix): claim scoped to model inference specifically, and the policy-gated door named up front so specimen 5 creates no internal tension | 2026-07-19 |

## Specimen 1 — replay window (2026-06-09)

| # | Claim | Type | Source | Verified |
|---|---|---|---|---|
| S1.1 | Entry exists: 2026-06-09 "The replay window between two correct components" | DOCUMENTED-EVENT | docs/archive/journal/2026-06.md:3196; mirror BUILD_JOURNAL.md:3479. Mirror-public: YES | 2026-07-19 |
| S1.2 | ES256 capability JWTs; 128-bit unique nonce per token; validator rejects seen nonces | DOCUMENTED-EVENT | entry text (jwt_minter.py:294 referenced in entry) | 2026-07-19 |
| S1.3 | Nonce store TTL default 5.0 s; token validity 30 s; defaulted independently in different files | DOCUMENTED-EVENT | entry text | 2026-07-19 |
| S1.4 | Replay accepted in the 5–30 s window; "25-second hole" | DOCUMENTED-EVENT | entry text (incl. deliberately-failing contrast test `test_old_default_would_have_leaked` documenting acceptance) | 2026-07-19 |
| S1.5 | Quote: "existed precisely because the two components were each individually correct… the seam between them was never specified" | DOCUMENTED-EVENT (verbatim quote) | entry lines 3230–3232 (hard-wrap re-flowed) | 2026-07-19 |
| S1.6 | Fix: `aligned_nonce_ttl(validity) = validity + skew_margin`; `JWT_VALIDITY_SECONDS` promoted to shared constants; validity 30→5; contrast regression test kept | DOCUMENTED-EVENT | entry text + commit `73746050` (2026-06-09, "[#638] token containment: 5s lifetime + nonce-TTL alignment + revoke() caller"); shared/constants.py public on mirror | 2026-07-19 |
| S1.7 | Only one live runtime destination validator existed (the AO's); PA's validator construction was a boot-time check | DOCUMENTED-EVENT | entry text | 2026-07-19 |
| S1.8 | Rule ("the pair is the control; derive one value from the other") | INTERPRETATION | ours, hedged in draft | — |

## Specimen 2 — kill-switch × SSRF pre-check (2026-06-12)

| # | Claim | Type | Source | Verified |
|---|---|---|---|---|
| S2.1 | Entry exists: 2026-06-12 "The door that would have tripped its own alarm" | DOCUMENTED-EVENT | 2026-06.md:5808; mirror:6091. Mirror-public: YES | 2026-07-19 |
| S2.2 | Kill-switch armed at process entry, before main() | DOCUMENTED-EVENT | entry text | 2026-07-19 |
| S2.3 | Door resolves host before per-fetch allowlist widen (anti-SSRF ordering); a test asserts internal-resolving host refused with allowlist never widened | DOCUMENTED-EVENT | entry text | 2026-07-19 |
| S2.4 | Quote: "Those two facts are individually correct and together fatal…" (full sentence in draft opening) | DOCUMENTED-EVENT (verbatim quote) | entry lines 5820–5824 (hard-wrap re-flowed) | 2026-07-19 |
| S2.5 | First live /ingest would have denied + tripped kill-switch → re-arm ceremony state; smoke harness had never armed the guard; "the request was the test" | DOCUMENTED-EVENT | entry text | 2026-07-19 |
| S2.6 | Rejected fix: widen-before-resolve, rejected to preserve the never-briefly-widened property | DOCUMENTED-EVENT | entry text (trade-off named) | 2026-07-19 |
| S2.7 | Shipped fix: inspect-and-refuse lookup through the guard's pre-arm resolver; never connects; real egress unchanged; armed-guard regression test | DOCUMENTED-EVENT | entry text + commit `c6fe7e97` (2026-06-12, "[#655] feat(go-live): operator-driven /ingest activation + armed-guard egress-door fix"); guarded_fetch.py + egress_guard.py public on mirror | 2026-07-19 |
| S2.8 | Rule (decide which control owns each read; give the pre-check an auditable seam) | INTERPRETATION | ours | — |

## Specimen 3 — write-only knowledge bank (2026-06-14)

| # | Claim | Type | Source | Verified |
|---|---|---|---|---|
| S3.1 | Entry exists: 2026-06-14 "The knowledge bank that could only be written to" | DOCUMENTED-EVENT | 2026-06.md:6622; mirror:6905. Mirror-public: YES | 2026-07-19 |
| S3.2 | Quote: "Two controls I would defend separately, each correct on its own terms, met in the knowledge bank and quietly turned it write-only." | DOCUMENTED-EVENT (verbatim, re-flowed) | entry lines 6624–6625 | 2026-07-19 |
| S3.3 | Operator discovery path (ingest article → fresh session → recall → held); held message text "Response held by the output validator — LEAKAGE_DETECTED." | DOCUMENTED-EVENT (verbatim) | entry text | 2026-07-19 |
| S3.4 | Cosine threshold 0.85 on untrusted chunks; action-lock stays armed for saved articles (UNTRUSTED_EXTERNAL grounding) | DOCUMENTED-EVENT | entry text (entrypoint.py:2385 referenced) | 2026-07-19 |
| S3.5 | Rejected fixes: trust-promotion (drops action-lock), global disable, threshold raise (recall trends to cosine 1.0) | DOCUMENTED-EVENT | entry text | 2026-07-19 |
| S3.6 | Fix: fourth tier UNTRUSTED_KNOWLEDGE, leak-feed exempt only; teeth tests both directions incl. rigged 0.97 recall delivered vs UNTRUSTED_EXTERNAL 0.97 still held | DOCUMENTED-EVENT | entry text + commit `6bc0994a` (2026-06-14, "fix(ao,#664): knowledge-bank recall leakage carve-out (ADR-023 Am.2)") | 2026-07-19 |
| S3.7 | "minted it as a numbered lesson that day" — lesson 132 "When two individually-correct controls collide, add a tier, don't lower a bar" | DOCUMENTED-EVENT | LESSONS.md index line 407 (lesson 132, ↺1); minted in fold `4a3a4dc3` (lessons 108–135). NOTE: lesson number itself deliberately NOT printed in draft (internal numbering); draft says "minted it as a numbered lesson that day" | 2026-07-19 |
| S3.8 | Rule (add a distinction the controls can see) | INTERPRETATION (quoting the documented lesson) | LESSONS.md 132 | 2026-07-19 |

## Specimen 4 — unreachable ALLOW (2026-07-02)

| # | Claim | Type | Source | Verified |
|---|---|---|---|---|
| S4.1 | Entry exists: 2026-07-02 "The over-denial that turned out to be unreachable ALLOW" — draft's specimen-4 header now cites this exact title (RED-2 fix, 2026-07-19/20; previously a descriptive title that broke the receipts claim) | DOCUMENTED-EVENT | BUILD_JOURNAL.md:486; mirror:11836. Mirror-public: YES | 2026-07-19 |
| S4.2 | Decision matrix requires label==ALLOW and confidence ≥ 0.75 | DOCUMENTED-EVENT | entry text | 2026-07-19 |
| S4.3 | Fallback confidence defaults zeroed 0.995 → 0.0 by hardening commit `bd8c378`, **dated 2026-04-17** | DOCUMENTED-EVENT | `git log -1 bd8c378` = 2026-04-17 "P5-TASK4.11-EA2: P1+P2 Security Hardening + Doc Cleanup". **CORRECTION vs source text:** the journal entry calls this "the 2025-era fail-closed hardening" — WRONG (repo's first commit is 2026-02-04; bd8c378 is 2026-04-17). Draft prints the correct date and does NOT quote the erroneous phrase. Panel: confirm handling | 2026-07-19 |
| S4.4 | Prompt demanded exactly one line "DECISION: <LABEL>"; MAX_CLASSIFICATION_TOKENS = 10 could not fit a second line | DOCUMENTED-EVENT | entry text | 2026-07-19 |
| S4.5 | Every model ALLOW parsed at confidence 0.0 → failed 0.75 gate → fell through ESCALATE → DENY; ALLOW structurally unreachable on model path | DOCUMENTED-EVENT | entry text | 2026-07-19 |
| S4.6 | Measured before: 26/30, all four misses false-DENIES (86.7%); measured after: 35/35 on expanded set; false-DENIES 4→0; false-ALLOWs 0→0; before-state 31/35 on the expanded 35-case set. Conditions now stated INLINE in draft prose (Qwen3-14B on Arc 140V, same golden set, 13 of 35 cases on the model path — rigor Y7 fix 2026-07-19/20) | MEASURED | entry text (before/after same day); evidence commit `24a1ebd4` + evidence doc commit `c70a3aba`; committed baseline evals/baselines/pa_classification.json | 2026-07-19 |
| S4.7 | Unit tests had modeled two-line format all along (mock outputs `DECISION: X\nCONFIDENCE: 0.9`) | DOCUMENTED-EVENT | entry text (test_gpu_inference.py referenced) | 2026-07-19 |
| S4.8 | Quote: "it was three components each individually fail-closed composing into a policy that could never say yes" | DOCUMENTED-EVENT (verbatim; clause quoted from the sentence beginning "The 86.7% wasn't…") | BUILD_JOURNAL.md:504–505 | 2026-07-19 |
| S4.9 | Fix sequence: five deny-side probes added FIRST (pa-mdl-009..013), then two-line prompt + calibration guidance + cap 10→24; thresholds/matrix/rules byte-untouched | DOCUMENTED-EVENT | entry text + `24a1ebd4` (2026-07-02) → merge `51182e4e` (2026-07-02) | 2026-07-19 |
| S4.10 | Named trade-off: making ALLOW reachable opens the false-ALLOW surface the broken composition had welded shut by accident | DOCUMENTED-EVENT | entry text | 2026-07-19 |
| S4.11 | Rule (100% one-sided miss → audit plumbing first; test the pipeline as a pipeline) | INTERPRETATION (echoing entry's proposed lesson) | entry "Proposed lesson" block | 2026-07-19 |

## Specimen 5 — validator swallowed the web answer (2026-07-02)

| # | Claim | Type | Source | Verified |
|---|---|---|---|---|
| S5.1 | Entry exists: 2026-07-02 "The answer the door let through and the validator swallowed" | DOCUMENTED-EVENT | BUILD_JOURNAL.md:823; mirror:12173. Mirror-public: YES | 2026-07-19 |
| S5.2 | Go-live chain: model reached for web_search unprompted; deterministic allowlist released the approved search domain; HTTP 200; faithful answer composed | DOCUMENTED-EVENT | entry text. NOTE: draft says "the approved search domain" rather than naming kagi.com — provider name IS public in the mirror entry; panel may allow naming it; draft errs narrow | 2026-07-19 |
| S5.3 | Held: "PGOV DENIED — Leakage score 0.930 >= threshold 0.85"; operator never saw the answer | DOCUMENTED-EVENT (verbatim log line as quoted in entry) | entry text | 2026-07-19 |
| S5.4 | Quote: "The feature we had just proven worked had, in the same breath, proven it could not deliver an answer." | DOCUMENTED-EVENT (verbatim, re-flowed) | entry lines 832–833 | 2026-07-19 |
| S5.5 | Quote: "The control was not wrong about the similarity; it was wrong about the direction." | DOCUMENTED-EVENT (verbatim; draft italicizes "direction" as source does) | entry lines 844–845 | 2026-07-19 |
| S5.6 | Fix: fifth tier UNTRUSTED_WEB (leak-feed exempt only; action-lock/datamark/deny intact); one-line behavioral delta | DOCUMENTED-EVENT | entry text + commit `4373e95d` (2026-07-02, "fix(719): web_search Stage-5 leakage carve-out — new UNTRUSTED_WEB provenance tier (ADR-023 Amendment 3)") | 2026-07-19 |
| S5.7 | Rejected: reuse UNTRUSTED_KNOWLEDGE (audit legibility; future per-source policy); broaden exemption to all UNTRUSTED_EXTERNAL (would un-screen pasted /external content); regression pins the split | DOCUMENTED-EVENT | entry text | 2026-07-19 |
| S5.8 | "the specimen-3 lesson earned its first recurrence tally" (lesson 132 ↺1) | DOCUMENTED-EVENT | LESSONS.md line 407 "↺1"; entry's Proposed lesson block naming both instances | 2026-07-19 |
| S5.9 | Rule (validator has a direction; provenance, never thresholds) | INTERPRETATION (echoing entry's proposed lesson) | entry text | 2026-07-19 |

## Specimen 6 — gate vanished at 76% (2026-07-04)

| # | Claim | Type | Source | Verified |
|---|---|---|---|---|
| S6.1 | Entry exists: 2026-07-04 "The gate that vanished at 76 percent and reported green" | DOCUMENTED-EVENT | BUILD_JOURNAL.md:1399; mirror:12749. Mirror-public: YES | 2026-07-19 |
| S6.2 | Origin of the lock: 2026-06-22 four live launcher instances; per-boot CA re-mint into one shared certs dir stomped trust chains | DOCUMENTED-EVENT | 2026-06.md:8259 "The swap assumed it was alone" (entry public on mirror) | 2026-07-19 |
| S6.3 | Refusal path deliberately `os._exit(1)` without cleanup (refused instance running teardown would stop the live instance's VM) — reasoned, correct in production | DOCUMENTED-EVENT | both entries (06-22 + 07-04) | 2026-07-19 |
| S6.4 | Gate output stopped at 76%, no failure, no summary; piped exit code read back as the pipe's → believed green | DOCUMENTED-EVENT | entry text | 2026-07-19 |
| S6.5 | Quote: "not red, not green, but absent, wearing green's clothes" (draft adjusts surrounding syntax; italics as source) | DOCUMENTED-EVENT (verbatim fragment) | BUILD_JOURNAL.md:1403 | 2026-07-19 |
| S6.6 | Second passenger: real privilege strip removed twenty privileges from the pytest process token | DOCUMENTED-EVENT | entry text (#652 referenced) | 2026-07-19 |
| S6.7 | Fix: autouse isolation conftest (lock trio + privilege strip patched as bound); direct suites untouched; TestInstanceLockRefusal pins os._exit(1) + no VM start + release never called; production exit NOT softened | DOCUMENTED-EVENT | entry text + commit `3df53522` (2026-07-04) + merge `b9e0aca2` (2026-07-04); launcher/tests/conftest.py public on mirror | 2026-07-19 |
| S6.8 | Quote: "an intentionally violent exit path and a test that drives real code are each fine alone — the audit question is what stands between them" | DOCUMENTED-EVENT (verbatim, italics dropped) | BUILD_JOURNAL.md:1411 | 2026-07-19 |
| S6.9 | Rule (explicit boundary + pin production semantics; no-summary = failed run) | INTERPRETATION (echoing entry) | entry text | 2026-07-19 |

## Specimen 7 — recovery killed the patient (2026-07-07)

| # | Claim | Type | Source | Verified |
|---|---|---|---|---|
| S7.1 | Entry exists: 2026-07-07 "The recovery that killed the patient" | DOCUMENTED-EVENT | BUILD_JOURNAL.md:2870; mirror:14220. Mirror-public: YES | 2026-07-19 |
| S7.2 | Reconcile premise (boot during in-flight swap ⇒ crashed ⇒ recover); stopped real OVMS mid-request; stamped RECOVERED over live run; driver kept dispatching | DOCUMENTED-EVENT | entry text | 2026-07-19 |
| S7.3 | Empty [fleet_dispatch] roots in minimal test config fall back to the box's real fleet root; LOCALAPPDATA redirect never covered fleet state dir; prior session-db corruption incident motivated that redirect | DOCUMENTED-EVENT | entry text | 2026-07-19 |
| S7.4 | Diagnosis: RECOVERED stamp 11:09:17 inside author's 11:07–11:12 gate run; three wrong suspects first; quote "The killer was me" | DOCUMENTED-EVENT (verbatim fragment) | entry text | 2026-07-19 |
| S7.5 | Quote: "and night-2 never had one because nobody runs pytest at 3 a.m." | DOCUMENTED-EVENT (verbatim) | entry text | 2026-07-19 |
| S7.6 | Production premise false for real case: operator opening app at ~23:30 during nightly battery would have killed the battery job | DOCUMENTED-EVENT | entry text | 2026-07-19 |
| S7.7 | Fix: root-conftest autouse reconcile guard (+opt-out for seam tests) + scoped-run belt + identity-lock test (deliberately not calling the seam); driver stamps pid + create-time; reconciler probes liveness, create-time match guards PID reuse; fail-closed to recovery; live driver hands-off | DOCUMENTED-EVENT | entry text + commit `72de8d40` (2026-07-07); shared/fleet/swap_state.py public on mirror | 2026-07-19 |
| S7.8 | Rejected cheaper path: test-side-only gating — rejected because operator-boots-mid-battery is real and imminent | DOCUMENTED-EVENT | entry text | 2026-07-19 |
| S7.9 | Rule (recovery is an actuator; verify the death certificate; fail closed to recovery) | INTERPRETATION (echoing entry) | entry text | 2026-07-19 |

## Specimen 8 — grammar × speculative decoding (2026-07-04 / upstream merge 2026-07-08) — COMPACT ENTRY (presentation B, panel decision 2026-07-19)

Rows revised 2026-07-19/20: the compact entry no longer prints crash rates, run counts, the
streamed-capture analysis, the word-piece observation, the streaming honesty note, the sglang
sibling, the interim-mitigation coda, or the maintainer-collaboration line — all deferred to
P1-S4 as the canonical full account (former rows S8.2/S8.4/S8.5/S8.6/S8.9/S8.10 retired with it).

| # | Claim | Type | Source | Verified |
|---|---|---|---|---|
| S8.1 | Entry exists: 2026-07-04 "The crash that only happens when two right things run together" | DOCUMENTED-EVENT | BUILD_JOURNAL.md:1431; mirror:12781. Mirror-public: YES | 2026-07-19 |
| S8.2 | Pair individually proven: spec-decode production default for weeks; grammar crash-free with speculation off in controlled elimination runs (no counts printed) | DOCUMENTED-EVENT | entry text; counts live in P1-S4 | 2026-07-19 |
| S8.3 | Elimination isolated the crash to the pair; quote: "where the draft model proposes tokens past a stop the grammar matcher has already terminated on, and the runtime asks the terminated matcher to mask them" | DOCUMENTED-EVENT (verbatim) | entry text | 2026-07-19 |
| S8.4 | Root cause: each feature keeps its own terminal state, integration never consults the other's; specimen-4 pattern at substrate scale | INTERPRETATION anchored to entry | entry text | 2026-07-19 |
| S8.5 | Sanitized reproducer: generic prompts + stock tool schema; nothing internal shipped | DOCUMENTED-EVENT | entry text | 2026-07-19 |
| S8.6 | Upstream: openvino.genai PR #4082 MERGED 2026-07-08 (full URL printed with access-date note); NO release-inclusion claim ("merged, with no claim here about tagged-release inclusion" printed verbatim) | DOCUMENTED-EVENT + guard row | GitHub API `pulls/4082` re-verified 2026-07-19 (state closed, merged true, merged_at 2026-07-08T13:07:36Z, title match); VERIFIED_FACTS marks release-inclusion UNVERIFIED/VOLATILE | 2026-07-19 |
| S8.7 | Cross-reference to the P1-S4 companion piece ("The crash we found and fixed upstream") as canonical full account, via home-base RELATIVE link placeholder `/posts/the-crash-we-found-and-fixed-upstream` — deliberately not a hard-coded github.io URL (home base may move domains); final path pinned at ceremony packaging | editorial/navigation row | panel cross-piece decision (presentation B); P1-S4 draft title verified on disk 2026-07-19 | 2026-07-19 |
| S8.8 | Rule (soak the pair; substrate has feature pairs too; "it found us from below" control-against-misreading) — kept in full per panel bound | INTERPRETATION | ours | — |

## Recurrence coda + patterns section

| # | Claim | Type | Source | Verified |
|---|---|---|---|---|
| R1 | 2026-07-09 doom-window incident: 90 s no-progress window inside a 600 s verify budget; healthy B4 killed at one-seventh of promised time; workers write nothing until finish | DOCUMENTED-EVENT | BUILD_JOURNAL.md:3629 "The detector that doomed the verify…" + LESSONS.md lesson 221 text; fix merged `8a9e725d` | 2026-07-19 |
| R2 | 2026-07-11 boot handshake ~15–18 s inside documented 180 s ceiling ("promised three minutes, granted eighteen seconds") | DOCUMENTED-EVENT | BUILD_JOURNAL.md:6064 entry + lesson 221 recurrence tally (#808) | 2026-07-19 |
| R3 | 2026-07-15 nightly task 16-hour ceiling (~PT16H) sat ~3 h under six-job worst case | DOCUMENTED-EVENT | BUILD_JOURNAL.md:9483 entry + lesson 221 tally (#833) | 2026-07-19 |
| R4 | Quote: "Neither number was wrong in isolation; the PAIR was incoherent, and nothing owned the question." | DOCUMENTED-EVENT (verbatim) | LESSONS.md:265 (lesson 221) | 2026-07-19 |
| R5 | Third-instance escalation rule (a third instance of a lesson's class must ship a structural control) and the two-installment structural response: relation locks at the class's third instance by lesson 221's own count (the 2026-07-11 boot-handshake recurrence, #808 — where the lesson's THIRD INSTANCE marker actually sits), derived outer limits at the fourth (2026-07-15 nightly ceiling, #833). Rewritten 2026-07-19/20 (fact Y-2 fix): previously the draft bundled both controls at "the third instance" of its own three-item list, misplacing the attribution | DOCUMENTED-EVENT | CLAUDE.md journal_discipline (rule); lesson 221 tally chain (LESSONS.md archive text: #740 base → #744 → #808 THIRD INSTANCE control → #833 fourth + derived-limit control) | 2026-07-19 (re-read) |
| R6 | Fourth same-class encounter, caught at design time: 2026-07-11 "Running is not ready" (#744) — a readiness wait shipped only after every window/budget pair was enumerated and proven to fit; draft now names it as a design-time catch, distinct from the three live-failure recurrences (fact Y-2 fix) | DOCUMENTED-EVENT | lesson 221 first recurrence tally (LESSONS.md) | 2026-07-19 |
| P1–P5 | The five cross-specimen patterns (review-approves-parts; seam ownership; fix grammar; composition-time detection; fail-closed→fail-shut asymmetry incl. survivorship read) | INTERPRETATION | ours; each anchored to specimens cited inline; hedged ("offered as interpretation… not laws") | — |

## Prior-work section

| # | Claim | Type | Source | Verified |
|---|---|---|---|---|
| PW1 | Zave feature-interaction framing + FI Workshop series (IOS Press); draft now prints access date 2026-07-19 | DOCUMENTED-EVENT (external) | P2-verdict prior-art map (T1). RESOLVED: pamelazave.com/fi.html RE-FETCHED LIVE 2026-07-19 in the revision session (HTTP 200, page title "About Feature Interaction", feature-interaction problem content confirmed) — the earlier 406 was transient/bot-block; fact Y-7 closed | 2026-07-19 (live re-fetch) |
| PW2 | Perrow, Normal Accidents (1984) — interactive complexity + tight coupling | DOCUMENTED-EVENT (external, classic) | P2-verdict map | 2026-07-19 |
| PW3 | Cook, "How Complex Systems Fail" (1998); "catastrophe requires multiple failures" | DOCUMENTED-EVENT (external) | how.complexsystems.fail fetched 2026-07-19 (HTTP 200). RESOLVED: the fact auditor's independent pass diffed the Cook quote word-for-word against the live page — verbatim confirmed (panel GREEN list) | 2026-07-19 (panel-diffed) |
| PW4 | Canetti UC (eprint 2000/067) — non-composability formalization | DOCUMENTED-EVENT (external) | P2-verdict map (T1) | 2026-07-19 |
| PW5 | Shortridge/Rinehart Security Chaos Engineering (O'Reilly 2023); draft PARAPHRASES ("factors working in concert"), does not quote | DOCUMENTED-EVENT (external) | P2-verdict map (T1/T2). Direct quote deliberately avoided pending source diff | 2026-07-19 |
| PW6 | Hillel Wayne "Feature Interaction Bugs" — modern practitioner essay, constructed case, explicitly not security-focused | DOCUMENTED-EVENT (external) | hillelwayne.com/post/feature-interaction/ fetched this session (HTTP 200); characterization per P2-verdict | 2026-07-19 |
| PW7 | danluu/post-mortems as genre model (cross-org, general reliability) | DOCUMENTED-EVENT (external) | P2-verdict map | 2026-07-19 |
| PW8 | 2025–2026 agent-guardrail literature characterization (defenses/taxonomies, not single-system field catalogs); named anchors now printed inline — "Provably Secure Agent Guardrail" (arXiv:2605.29251) + the 2026-04-20 practitioner survey "AI Agent Security in 2026", both access-dated 2026-07-19 (rigor Y5 fix) | INTERPRETATION over surveyed sources | P2-verdict map row H (arxiv.org/html/2605.29251v1; slavadubrov.github.io/blog/2026/04/20/ai-agent-security/) | 2026-07-19 |
| PW9 | "the only thing this piece claims as new is the artifact" | INTERPRETATION (novelty claim) | P2-verdict §2–3 (GO, gap = the artifact); author-pass affirmation in verification-memo §4 | 2026-07-19 |

## Receipts section

| # | Claim | Type | Source | Verified |
|---|---|---|---|---|
| RC1 | Public mirror carries the build journal with all eight specimen entries | DOCUMENTED-EVENT | GitHub API checks this session: mirror BUILD_JOURNAL.md HTTP 200; all 8 titles grep-present (mirror line numbers in prescreen). VOLATILE: mirror layout will change at next weekly sync post-rotation — re-pin paths at publish | 2026-07-19 |
| RC2 | Disclosure boilerplate (drafted with the AI fleet it describes; human directed/reviewed/approved) | program standard | AUTHOR_KIT §F (ACTIVE per LA decision 2026-07-19a) | 2026-07-19 |
