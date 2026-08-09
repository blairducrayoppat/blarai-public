---
title: "P2 verification memo — §B pass + specimen-count derivation"
piece: P2
status: for-review-panel-and-ceremony
prepared: 2026-07-19 (P2 author session); revised 2026-07-19/20 (panel disposition appended; §2 Step 3b, §3.5, §5 updated)
---

# P2 verification memo

What this memo is: the Author Kit §B date-and-number pass for the P2 draft, the specimen-count
derivation the fact sheet mandated ("the count that prints is the count you derive"), the author's
written novelty GO affirmation, and the open items the panel must close. Every derivation below was
run this session (2026-07-19) in a clean worktree at main `c4eff36f`.

## 1. Corpus ground truth

| Item | Value | Derivation |
|---|---|---|
| Journal record read | docs/archive/journal/2026-05.md (282 lines) · docs/archive/journal/2026-06.md (11,105 lines) · BUILD_JOURNAL.md hot (9,975 lines) · docs/BUILD_JOURNAL_ANTHOLOGY.md (3,544) · LESSONS.md (563) · docs/journal_fragments/ (14 files) | `wc -l`, `ls` |
| Entry-header scan | full `grep -n '^### '` over both volumes + hot journal (May volume has no June/July-class incidents; contains no collision-language hits) | grep sweeps recorded in session |
| Public mirror copy | `blairducrayoppat/blarai-public` BUILD_JOURNAL.md = pre-rotation monolith, 19,167 lines, 402 entries; all 8 specimen titles present (lines 3479 · 6091 · 6905 · 11836 · 12173 · 12749 · 12781 · 14220) | raw fetch + grep this session |

## 2. The specimen-count derivation (the load-bearing §B item)

**Criteria applied** (from the program dispatch, consistent with the piece definition):
(1) both colliding parts individually correct — each would pass review on its own;
(2) fully documented — dated journal entry written at the time + reconstructable commits/tickets;
(3) structural fix shipped — a structure change, landed and test-locked (not a threshold tweak).

**Step 1 — verify the audit's seven.** All seven enumerated in `synthesis_journal_gems.md` §B2 and
VERIFIED_FACTS verify on disk with entry + collision framing + shipped fix + regression lock:

| # | Specimen | Entry (date · title · location) | Fix commit(s), re-derived |
|---|---|---|---|
| 1 | Replay window | 2026-06-09 "The replay window between two correct components" · 2026-06.md:3196 | `73746050` (2026-06-09) — `git log -S aligned_nonce_ttl --reverse` first hit; on main |
| 2 | SSRF-precheck kill-switch | 2026-06-12 "The door that would have tripped its own alarm" · 2026-06.md:5808 | `c6fe7e97` (2026-06-12) — `git log -S real_getaddrinfo --reverse` first hit |
| 3 | Write-only knowledge bank | 2026-06-14 "The knowledge bank that could only be written to" · 2026-06.md:6622 | `6bc0994a` (2026-06-14) — `git log -S UNTRUSTED_KNOWLEDGE --reverse` first hit; ADR-023 Am.2 |
| 4 | Unreachable ALLOW | 2026-07-02 "The over-denial that turned out to be unreachable ALLOW" · BUILD_JOURNAL.md:486 | `24a1ebd4` → merge `51182e4e` (both 2026-07-02) — `git log --grep 717`; evidence `c70a3aba` |
| 5 | Leak-validator swallow | 2026-07-02 "The answer the door let through and the validator swallowed" · BUILD_JOURNAL.md:823 | `4373e95d` (2026-07-02) — `git log -S UNTRUSTED_WEB --reverse` first hit; ADR-023 Am.3 |
| 6 | Instance-lock gate kill | 2026-07-04 "The gate that vanished at 76 percent and reported green" · BUILD_JOURNAL.md:1399 | `3df53522` + merge `b9e0aca2` (2026-07-04) — SHAs in entry, confirmed `git log -1` |
| 7 | Recovery-killed-the-swap | 2026-07-07 "The recovery that killed the patient" · BUILD_JOURNAL.md:2870 | `72de8d40` (2026-07-07) — SHA in entry, confirmed `git log -1` |

**Step 2 — the "~8" reconciliation.** The synthesis's own §B2 paragraph says "~8 instances" and then
lists exactly seven dated instances — the discrepancy is internal to that paragraph (an estimate
written before/above its own enumeration). Nothing was lost; there was never a named eighth.

**Step 3 — sweep for additional qualifiers.** Full header-title scan of both volumes + hot journal +
fragments + LESSONS collision-language grep (`collide|collision|individually correct|two correct|composition`).
Candidates evaluated against the criteria:

| Candidate | Date/entry | Verdict | Reason |
|---|---|---|---|
| **xgrammar × speculative decoding (#725)** | 2026-07-04 "The crash that only happens when two right things run together" | **QUALIFIES — admitted as specimen 8** | Both parts individually correct, established by controlled elimination on real hardware (spec-OFF 0/57; spec-ON ~1–2% crash) — the cleanest "individually correct" evidence in the whole set. Fully documented (entry + docs/upstream/725_xgrammar_stop_token/ + issue #4081). Structural fix shipped UPSTREAM: openvino.genai PR #4082 merged 2026-07-08T13:07:36Z (GitHub API re-verified this session). Caveats flagged in §5: substrate mechanisms rather than policy controls (draft's scope note handles it); P1-S4 overlap (below). |
| Fail-closed lockout (bulk decrypt) | 2026-06-06 "When 'fail closed' becomes a door that locks you out of your own house" | EXCLUDED | One principle applied at the wrong granularity (leaf fail-closed semantics reused in bulk loops). The second party (legacy rows under a dev key) is residual data, not a correct control. Fix (quarantine-and-continue, `145f2b1`/`4af2033`) is real but the shape is mis-scoped policy, not two-control collision. |
| Per-boot CA × multi-instance | 2026-06-22 "The swap assumed it was alone" | EXCLUDED as specimen; USED as specimen-6 setup | The collision is one control (per-boot CA mint into a shared dir) meeting more instances of itself — an unstated single-instance assumption (lesson 158), not two distinct correct controls. It is the documented origin of the instance lock, so it appears as specimen 6's setup paragraph, cited. |
| Scorecard fail-closed writer | 2026-07-08 "The certificate that killed the night" | EXCLUDED | One party defective: the consumption half wrote a dict where the contract says string. Composition-never-exercised class (lesson 46 fifth instance), not both-correct. |
| Doom window × verify budget | 2026-07-09 "The detector that doomed the verify…" | EXCLUDED as separate specimen; INCLUDED in recurrence coda | Passes criterion 1 by the corpus's own words (lesson 221: "Neither number was wrong in isolation") — but it is a recurrence of specimen 1's class (independently-set time values whose pair defines a guarantee), not a new collision shape. Cataloged in the coda with its two siblings rather than duplicated as a specimen. |
| Boot handshake × cold-start ceiling (#808) | 2026-07-11 | EXCLUDED as specimen; recurrence coda | Same class, second recurrence (lesson 221 tally). |
| Nightly ceiling × six-job worst case (#833) | 2026-07-15 | EXCLUDED as specimen; recurrence coda | Same class, third recurrence — the one that shipped the structural control (registry relation lock + derived outer bound). |
| Import-armed teardown (#783) | 2026-07-09 "The import that armed the teardown" | EXCLUDED | One party defective: module-scope `atexit` registration is an import-time side effect (the fix relocated it inside `main()`) — the arming point was wrong, so not both-correct. |
| DETACHED_PROCESS × venv shim (#761) | 2026-07-07 "The flag that worked, one process too early" | EXCLUDED | Property-propagation failure across a platform hop (flag honored at the spawn site, property lost one process down), not a two-control collision. |
| ISO rebuild × Hyper-V ACL | 2026-06-13 | EXCLUDED | One party was incorrect guidance (skip the re-attach); ordinary operational error. |
| Windows auto-restart × live run | 2026-07-15 | EXCLUDED | External-event interruption; the reconciler behaved correctly (it is specimen 7's fix working). |
| #953 harvest blindness / #946 prose divergence (fragments) | 2026-07-19 | EXCLUDED | In each, one party was defective (a lock that missed a sibling shape; model prose contradicting the deterministic layer) — not both-correct. |

**Step 3b — panel-completion rows (added 2026-07-19/20, closing fact-auditor RED-1).** The fact
auditor's independent sweep surfaced five hits absent from the table above. Each is now
dispositioned; the count of eight is certified only with these closed:

| Candidate | Date/entry | Verdict | Reason |
|---|---|---|---|
| **Oracle × coder module layout (#752 F3)** | 2026-07-06 "The oracle and the coder never agreed where the code lived" (BUILD_JOURNAL.md:2673) | **EXCLUDED** | Read in full this session. Matches the sweep pattern ("Both halves were individually correct") but fails on system boundary and shape: (a) it is the DEVELOPMENT FLEET's dispatch harness (a plan-time acceptance oracle and a coder scaffold convention in `shared/fleet/acceptance.py`) — builder-fleet tooling that codes against the project, not a control of the AI system or of its own verification gate; specimens 6–7 qualify because the standing gate verifies the SYSTEM, whereas this seam verifies fleet-generated code. (b) The entry self-classifies as "Recurrence of Canonical C4 (the seam, not the parts)" — a documented recurrence of an existing seam-class lesson, not a new collision shape; admitting recurrences as specimens is exactly what the coda structure exists to avoid (cf. the three specimen-1-class recurrences, also excluded as specimens). (c) Marginal on criterion 3 as documented: the entry's own footer records "Branch fix/752-f3-oracle-app-package — not merged" at writing. The auditor's offered reasoning (dev-fleet tooling, C4 self-classification) is adopted and extended with (a)'s boundary argument. |
| Resolve-grain review discussion (#666) | 2026-06-16 "The least-authority instinct that didn't pay rent" (2026-06.md:7417; sweep hit "two correctly-different grains") | EXCLUDED — auditor's face-read confirmed | No collision incident occurred: it is a design-review trade-off (per-session vs global-by-id image resolution) resolved by RECORDING a deliberate default (ADR-033 note + register row; "No code change"). Fails criterion 1's premise (nothing collided) and criterion 3 (no structural fix — a documentation decision). |
| Action-lock × GUARDED web_search (#719 rung 3) | 2026-07-02 "A fingerprint on the way out: the egress envelope, and the lock I forgot to remove" (BUILD_JOURNAL.md:996) | EXCLUDED — auditor's face-read confirmed | The nearest miss of the five: two individually-defensible controls (Layer-3 action-lock on untrusted-content sessions; web_search classified GUARDED) whose composition would have demanded an unjudgeable per-session `/trust` rubber-stamp. But it was diagnosed in design (rung 1 had already named the rubber-stamp problem) BEFORE any failure event — no incident, so criterion 2's documented-collision reading fails — and the resolution is an LA-decided consent CAPABILITY (the turn-scoped Windows-Hello envelope), a governance design, not a structural fix to a collision defect. Including it would blur the catalog's definition of specimen (caught failures) with roadmap work. |
| Spec-decode "net-negative" scare (#778) | 2026-07-10 "The slowdown that was three measurement bugs in a coat" (BUILD_JOURNAL.md:5619) | EXCLUDED — auditor's face-read confirmed | All three parties defective, not individually correct: nonce prompts a 0.6B draft cannot predict by construction, an acceptance metric read off a NONEXISTENT API method, and a non-interleaved A/B that let thermal drift ride the comparison. A measurement-error post-mortem (lesson 222 family — instruments earn belief), not a control collision. Fails criterion 1 outright. |
| Cross-repo static-page fix (#886/#888) | 2026-07-15 "The static-page fix that only half-existed in each repo, and the mirror that had quietly drifted" (BUILD_JOURNAL.md:9525) | EXCLUDED — auditor's face-read confirmed | The underlying defect was ONE mis-scoped scaffold profile (unconditionally seeding a server for a static ask) — one party defective. The entry's "individually safe" language describes the FIX's two-repo landing shape (lesson 272: each half a harmless no-op until both mains carry it), which is a deployment-coordination lesson, not two correct controls composing into failure. Also dev-fleet scope, per the oracle×coder boundary argument above. |

Outcome: all five dispositioned, none qualifies, **the derived count of EIGHT stands** — now
certified against the auditor's sweep as well as the author's.

**Derived count: EIGHT specimens** (the audit's seven + #725), plus a three-instance recurrence arc
of specimen 1's class documented in the coda. The draft prints eight and explains the derivation in
its "How specimens qualified" section; the title carries no number (HN rule).

## 3. Date/SHA/figure re-derivations (trap log)

1. **`bd8c378` "2025-era" — SOURCE ERROR CAUGHT.** The specimen-4 journal entry calls the
   confidence-zeroing hardening "the 2025-era fail-closed hardening (`bd8c378`, P2-3)". Re-derivation:
   `git log -1 bd8c378` → **2026-04-17** ("P5-TASK4.11-EA2: P1+P2 Security Hardening + Doc Cleanup").
   The repo's first commit is 2026-02-04, so nothing in it is 2025-era. The draft prints 2026-04-17 and
   deliberately does not quote the erroneous phrase. This is exactly the §B trap class (LA amendment 1).
2. **PR #4082 merge state** re-verified via GitHub API this session (not carried from the fact sheet):
   state=closed, merged=true, merged_at=2026-07-08T13:07:36Z, title matches. **Release inclusion is NOT
   claimed anywhere in the draft** (VERIFIED_FACTS marks it VOLATILE/unverified).
3. **All eight fix commits** re-derived from `git log` (pickaxe or direct SHA), never from entry prose
   alone; dates in §2 table. Entry-embedded SHAs (`3df5352`, `b9e0aca`, `72de8d4`) confirmed to resolve
   on main with matching dates/subjects.
4. **Quotes** diffed against source text; two quoted sentences span the journal's hard line-wraps
   ("…individually correct and / together fatal…", "…but the / seam between them was never specified") —
   re-flowed in print, no word changes. One quote drops source italics (noted in claims table S6.8);
   S5.5/S8.4 preserve source italics.
5. **Measured figures carried (updated 2026-07-19/20 for the compact specimen 8):** 26/30 · 31/35 ·
   35/35 · 4→0 · 0→0 (specimen 4 — conditions now stated INLINE in the draft prose: Qwen3-14B on
   Arc 140V, same golden set, 13 of 35 cases on the model path; the earlier version of this memo
   overstated the draft's inline conditions, per rigor Y7 — now true); 0.85 / 0.930 / 0.97 cosine
   (specimens 3/5); 5 s / 30 s / 25-second window (specimen 1); 90 s / 600 s, ~15–18 s / 180 s, 16 h
   (coda). Specimen 8's figures (~1–2% crash rate, 0-for-57, 57 streamed) are NO LONGER PRINTED in
   this draft — deferred entirely to P1-S4 as the canonical account, which also dissolves the
   crash-rate discrepancy between the two pieces (RED-3). Each remaining figure traced to its entry
   in the claims table; none is a performance benchmark requiring a PERFORMANCE_LOG event.
6. **Counts as-of dates:** journal corpus figures (465 entries / 58 days / 2026-05-21 birth) carried
   from VERIFIED_FACTS (verified 2026-07-19) and scoped in-draft as "first 58 days of journaling."
   Marked volatile for re-check at publish ceremony.

## 4. Author-pass novelty affirmation (§I deep pass → written GO)

The survey (P2-verdict.md) ran the full §I rubric TODAY, 2026-07-19, with all URLs access-dated
today; a same-day re-survey cannot move the map materially. The author pass therefore consisted of:
(a) re-reading the verdict's prior-art map against the finished draft's actual claims — the draft
claims only the artifact (single-system security-control specimen catalog with shipped fixes), which
no mapped item provides; (b) spot re-verification of load-bearing externals this session:
how.complexsystems.fail HTTP 200 + title confirmed (closing the verdict's named gap);
hillelwayne.com/post/feature-interaction/ HTTP 200; pamelazave.com/fi.html HTTP 406 on refetch
(bot-block — flagged in claims table PW1; survey's same-day access stands; workshop-series citation
is stable print anchor); PR #4082 via API. **Verdict affirmed: GO**, under the survey's binding
framing (ancestors up front; artifact-not-idea) — which the draft implements structurally (its
second section is the ancestor credit; the novelty claim is confined to the artifact and stated in
exactly those terms).

## 5. Open items — status after the panel round (updated 2026-07-19/20)

1. **P1-S4 overlap — RESOLVED (panel + LA-bounded decision: presentation B).** Both audience editors
   independently converged: seven specimens treated fully, specimen 8 as a compact entry explicitly
   cross-referencing P1-S4 ("The crash we found and fixed upstream") as the canonical full account,
   printed count stays EIGHT everywhere. Implemented this revision. The cross-link is a home-base
   RELATIVE placeholder (`/posts/the-crash-we-found-and-fixed-upstream`) — **ceremony packaging must
   pin the final path**; it must remain portable (never a hard-coded github.io URL — the home base
   may move to a standalone domain).
2. **Cook heading wording — CLOSED.** The fact auditor diffed the quote word-for-word against the
   live page: verbatim (panel GREEN list).
3. **Zave page — CLOSED.** pamelazave.com/fi.html re-fetched live in the revision session
   (2026-07-19): HTTP 200, title "About Feature Interaction," content confirmed. Access date now
   printed in the draft. Standard publish-day re-check still applies.
4. **Search-provider naming (S5.2) — STILL OPEN for the integrity reviewer/LA:** draft keeps the
   generic phrase; the mirror entry publicly names kagi.com. Errs narrow pending the call.
5. **Mirror path volatility (RC1) — STILL OPEN at publish:** re-pin any file-path-level links when
   the weekly sync picks up the journal rotation; do not cite archive-volume paths externally until
   they exist on the mirror.
6. **"five weeks" figure — CLOSED (fact-panel Y):** now "recurred three more times as live failures
   over the following five-plus weeks" (2026-06-09 → 2026-07-15 = 5.1 weeks; the old literal claim
   was off by a day against the program's exact-numbers bar).
7. **Fragment-fold dependency: none.** No quoted content comes from unfolded fragments; all quotes are
   from committed volumes/hot journal at `c4eff36f`.
8. **NEW — ceremony amplification note (privacy panel, for the LA to decide knowingly):** the draft
   prints two CURRENT live control thresholds — the 0.85 output-leakage cosine threshold (specimens
   3/5) and the 0.75 policy-confidence gate (specimen 4). The privacy reviewer independently
   confirmed BOTH are already public on the mirror in equal-or-greater detail, so there is no §D
   violation — but publication to HN/home base is a large amplification of that exposure, and the
   LA's approval at ceremony should be made knowing these are live values, not historical ones.
   (Historical-only values elsewhere: specimen 1's 5 s/30 s token constants are pre-fix values.)
9. **NEW — journal citations do not name archive volumes (fact Y-6), stated as a decision:** the
   Author Kit §C journal format asks for the archive volume, but the only reader-reachable copy is
   the public mirror's PRE-ROTATION MONOLITH (`BUILD_JOURNAL.md`), where archive-volume paths do not
   exist; printing `docs/archive/journal/2026-06.md` would send readers to a 404. The draft
   deliberately cites date + exact title (stable in both layouts) and names the mirror generically.
   Revisit at publish when the sync picks up the rotation (item 5).

## 6. What was deliberately left out of the draft

- Lesson numbers (132/158/209/210/221 etc.) — internal curation numbering; draft says "a numbered
  lesson" without printing numbers. (Panel may overrule; numbers are public on the mirror.)
- Ticket numbers in prose (kept only where the fix commit subject carries them); full mapping lives
  here and in the claims table.
- The `BLARAI_GUEST_PARSER_ENABLED` env override, go-live shortcut mechanics, per-session re-weld
  details from the specimen-2 entry (public on the mirror, but operational egress mechanics — excluded
  under §D "when unsure, exclude and flag"; see prescreen F-4).
- Any live-config values not already fixed in the public journal text (see prescreen).
- Release-inclusion claims for the upstream fix (unverified).

---

# Panel disposition (2026-07-19/20)

One entry per panel finding, per README §4's shipping gate ("the author has dispositioned every
panel finding in writing"). Verdicts: **accept-fix** / **accept-fix-partial** / **rebut**.

## Cross-piece decision (mandatory)

**D-0. Specimen-8 presentation.** *"Both independent audience editors converged on presentation (B)
— seven specimens treated fully, the eighth presented as a COMPACT entry that explicitly
cross-references P1-S4 as the canonical full account. The printed specimen count stays EIGHT
everywhere — a hard bound."* — **accept-fix (implemented).** The ~640-word specimen 8 is now a
compact entry: miniature skeleton (setup / collision / root cause / fix), no independent crash
rate (RED-3 dissolved), the transferable rule kept verbatim in full including the "it found us
from below" control-against-misreading close, explicit "Specimen 8 of 8" + specimen-4-pattern
classification, portable relative cross-link to P1-S4 (placeholder path
`/posts/the-crash-we-found-and-fixed-upstream`, to be pinned at ceremony packaging — never a
hard-coded github.io URL), and the full PR URL kept as venue-independent secondary evidence.
Cut per spec: 0-for-57 counts, streamed-capture detail, word-piece observation, streaming honesty
note, sglang sibling, the maintainer-collaboration line, and the interim-mitigation coda. Count of
eight verified intact at subtitle, intro, qualification section, new index table, "what eight
specimens agree on," fix-grammar move (8), and finder list. Honest note: the compact section
measures ~430 words against the ~200–350 guidance — the overage is the mandated verbatim rule
(~80 words) plus the mandated count/classification/cross-link plumbing; the narrative skeleton
itself is ~230. I judged cutting mandated elements worse than the overage.

## RED findings (all resolved — zero unresolved reds)

**RED-1 (fact auditor) — derivation completeness.** *"A candidate NOT in the exclusion table:
2026-07-06 'The oracle and the coder never agreed where the code lived'… plus four more sweep hits
absent from the table."* — **accept-fix.** All five added as Step 3b of §2 with written
dispositions after reading each entry on disk this session. The 07-06 item: EXCLUDED — I adopt the
auditor's offered reasoning (dev-fleet dispatch tooling; self-classified Canonical-C4 recurrence)
and add the system-boundary argument: the colliding parts belong to the builder fleet's acceptance
harness, not to the AI system or the gate that verifies the SYSTEM (which is what qualified
specimens 6–7); its entry footer also records the fix branch as not-merged at writing. The other
four: EXCLUDED on their face as the auditor judged, each now with a stated reason (no incident /
one-party-defective / measurement post-mortem / fix-deployment shape). **The count of eight is now
certified against the auditor's independent sweep.**

**RED-2 (fact auditor) — false exact-title receipts claim.** *"…true for 7 of 8 specimens, false
for specimen 4."* — **accept-fix (recommended form).** Specimen 4's header is now the real entry
title, "The over-denial that turned out to be unreachable ALLOW." No descriptive subtitle kept —
the body's opening already carries the classifier framing, and two titles on one specimen would
cost more than they add. The receipts sentence is now true for 8 of 8.

**RED-3 (cross-piece crash-rate conflict).** — **accept-fix (resolved structurally).** The compact
entry states no independent rate ("rare crashes at end-of-sequence"); the isolation table, run
counts, and crash rates are deferred wholesale to P1-S4. The two pieces can no longer disagree.

**RED-4 (fact auditor) — SHA resolution false in the only reachable repo.** *"All nine
specimen-header fix-commit SHAs return 404/422 against the public mirror… falsifies 'The fix
commits named in the specimen headers are in the repository history.'"* — **accept-fix.** The
receipts paragraph now states plainly that the mirror is a snapshot-synced repository with its own
separate git history, that the hashes are project-history identifiers recorded in the public
journal entries (checkable as quoted text against entry content — which the auditor confirmed
appears verbatim), and it anchors "check it yourself" on what the mirror DOES resolve: entry
titles and the named public source files (already HTTP-200-verified in the prescreen).

**RED-5 (rigor skeptic + fact auditor Y-4) — near-miss promise false.** *"The near-misses that
failed criterion 1 are never discussed anywhere."* — **accept-fix (amend option).** The
qualification sentence now claims only what the draft delivers: near-misses "failed criterion 1 on
inspection… and were excluded rather than rounded up," with only the recurrences promised
post-catalog discussion. The receipts "the working notes enumerate them" clause is deleted (it
pointed at no public location). The alternative — adding a real near-miss discussion — was
declined deliberately: the piece is already at its venue's length ceiling, and the strongest
near-miss material is dev-fleet-scoped (see Step 3b), which would require fresh mirror-exposure
verification the panel has not run; the derivation table in this memo serves the ceremony instead.

## Audience editor findings

**A-1. Length (~6,100 words at the HN upper edge).** — **accept-fix-partial, with the honest
numbers.** Raw `wc -w` on the file: 6,700 before revision → 7,026 after (the compaction bought
~330 words back; the panel's mandated additions — index table ~150, lesson-221 reconciliation,
silent-hole scoping, receipts rewording, disposition-driven hedges — spent ~660). Of the net
growth, ~150 words are the skimmable index table, not linear prose, and cross-cut #5 (the editor's
named tightening candidate) was compressed in the same pass. My judgment, stated for the ceremony:
the piece reads as a catalog (readers skim to specimens), the HN submission is a link not a wall
of text, and cutting accuracy-bearing panel fixes to hit a word target would invert the program's
priorities. If the LA wants it shorter, the named candidates are cross-cuts #1 and #4.

**A-2. Frontmatter venue line omits the LessWrong crosspost.** — **accept-fix.** Added to the
target line, cited to ROADMAP §5c's approved list.

**A-3. Up-front specimen index table (optional).** — **accept (added).** An eight-row table after
"How specimens qualified": number, exact entry title, date, colliding pair, fix class. It also
makes the count-of-eight structurally visible, which the cross-piece decision hardens.

## Rigor skeptic findings

**Y1. Categorical aphorisms in supposedly-hedged rules; only specimen 1 tagged.** — **accept-fix
(tag option).** All eight Transferable rule headers now carry "(ours, hedged)" uniformly. The
categorical phrasings ("won't, forever" / "will eventually") stay — under a uniform hedge tag they
read as deliberately-pointed field rules rather than unhedged laws, and blunting them would cost
the register the piece is written in.

**Y2. Gap paragraph narrower than the delivered catalog.** — **accept-fix.** Now "a curated
collection of *control-composition* failures — security and policy controls, the verification
apparatus around them, and the substrate under them —", matching both the scope note and the
closing novelty sentence.

**Y3. 'Strongest argument we have' overreach in cross-cut 5.** — **accept-fix.** Softened to "we
read it as evidence… with the honest caveat that this argument cannot distinguish 'the posture
makes failures loud' from 'the quiet holes are still unfound.' A catalog of caught collisions has
no denominator, and neither does this inference."

**Y5. Uncited "e.g." in the most-timely-neighbors bullet.** — **accept-fix.** Named anchors added:
"Provably Secure Agent Guardrail" (arXiv:2605.29251) and the 2026-04-20 practitioner survey "AI
Agent Security in 2026," both access-dated 2026-07-19 (sources per P2-verdict row H).

**Y6. "Shipped" vocabulary implying release-inclusion for specimen 8.** — **accept-fix.** Scope
note now "its fix was merged upstream"; the compact entry's fix header is "Structural fix — merged
upstream" and its text prints "merged, with no claim here about tagged-release inclusion."
Generic uses of "shipped" for LOCAL fixes (which did land on main) are unchanged — the finding's
risk is specific to the upstream merge/release distinction.

**Y7. Memo overstated the draft's inline measurement conditions for specimen 4.** — **accept-fix
(conditions added inline, the stronger option).** Draft now reads "Measured with the production
model (Qwen3-14B on the Arc 140V GPU), same golden set, 13 of the 35 cases exercising the model
path." §3.5 of this memo corrected to match.

## Fact auditor yellows

**F-Y1. "five weeks" literal error (5.1 weeks).** — **accept-fix.** Now "three more times as live
failures over the following five-plus weeks."

**F-Y2. Lesson 221's fourth tally (#744) omitted; THIRD-INSTANCE control marker misattributed.** —
**accept-fix (adopting the lesson's own counting).** The coda now (a) scopes the three-item list
to live failures, (b) names the fourth same-class encounter — the 2026-07-11 design-time catch
where every window/budget pair was enumerated and proven before shipping, and (c) attributes the
structural response in two installments exactly as the lesson records it: relation locks at the
class's third instance by lesson 221's count (the boot-handshake recurrence, #808 — where the
THIRD INSTANCE marker sits), derived outer limits at the fourth (the nightly ceiling, #833).
Claims-table rows R5/R6 updated.

**F-Y3. Specimen 6's "silent hole" wording vs pattern 5's specimen-1-only claim.** — **accept-fix.**
Pattern 5 now scopes the claim ("a silent gap in a shipped control's production guarantee") and
quotes specimen 6's own "three sound decisions composing into one silent hole" while
distinguishing its plane: the gate reporting green while absent is a verification-plane hole, not
a production-guarantee hole.

**F-Y5. PR #4082 never gets a full URL.** — **accept-fix.**
github.com/openvinotoolkit/openvino.genai/pull/4082 printed in the compact entry with the
API-re-verification note dated to drafting.

**F-Y6. Journal citations don't name the archive volume.** — **accept (dispositioned as a stated
decision, no draft change).** See open item 9: the reader-reachable copy is the pre-rotation
monolith; volume paths would 404. Deliberate, revisit at publish with item 5.

**F-Y7. Zave citation: no access date, 406 on refetch.** — **accept-fix (re-verified live).**
Fetched pamelazave.com/fi.html in this revision session: HTTP 200, title "About Feature
Interaction," feature-interaction content confirmed. Access date 2026-07-19 now printed in the
draft; claims-table PW1 unflagged.

## Integrity/privacy findings

**P-Y2. "no cloud in the runtime path" vs specimen 5's live web fetch.** — **accept-fix.** Scoped
to inference: "no cloud anywhere in the model-inference path; the system's only network access is
a single deliberate, policy-gated door, whose first live use is specimen 5." The tension is now a
signpost instead of a contradiction. Claims-table G7 resolved.

**P-Y3. Prescreen F-7 overstated the draft's disclosure (claimed CURRENT 5-second validity).** —
**accept-fix.** F-7 corrected: the draft prints only the HISTORICAL pre-fix constants (5 s nonce
window / 30 s validity); the 30→5 change lives in the non-publishing claims table; correction
noted in-place in the annex.

**P-note. Current live thresholds (0.85 leak-validator, 0.75 policy confidence).** — **accept
(memo line added, no draft change needed).** Open item 8 states it plainly for the ceremony: both
are current live values, both independently confirmed already public on the mirror in
equal-or-greater detail; the LA's amplification decision at ceremony is to be made knowing that.

## Summary line for the gate

All 5 REDs (incl. the consolidated rigor/fact near-miss RED) resolved; the mandatory cross-piece
specimen-8 decision implemented to its hard bounds; 15 yellows dispositioned — 13 accept-fix,
1 accept-fix-partial (length, with stated judgment), 1 accept-as-stated-decision (archive-volume
citation form). No rebuttals in the strict sense; where a finding offered options, the chosen
option and the declined one are named above. Zero unresolved reds → the README §4 shipping gate's
author-side condition is met.
