---
title: "P1-S4 verification memo (AUTHOR_KIT §B date/number pass)"
status: companion-to-S4-draft-v2
area: research
piece: P1-S4
pass_run: 2026-07-19 (author session, pre-panel)
---

# S4 §B verification memo — every date, number, and version re-derived

Method: every figure in the draft was re-derived from its primary artifact
during this session (2026-07-19), not carried from memory, the fact sheet, or
prior prose. GitHub facts were read live via the REST API on 2026-07-19.
Artifacts read at worktree commit `c4eff36f` (current main at session start).

Abbreviations: **JSON** =
`docs/performance/xgrammar_stop_token_fix_verify_2026-07-05_15-34-27.json` ·
**LOG** = `PERFORMANCE_LOG.md` 2026-07-05 xgrammar entry ·
**J-0704a/J-0704b/J-0705** = BUILD_JOURNAL.md entries 2026-07-04 ("The first
time anyone measured the words" incl. same-night correction / "The crash that
only happens when two right things run together") and 2026-07-05 ("The fix that
couldn't be proven on the machine that broke") ·
**T725** = Vikunja ticket #725 (internal corroboration only) ·
**API** = GitHub REST API, read 2026-07-19.

## 1. Dates

| Item in draft | Value | Re-derived from |
|---|---|---|
| Live crash date | 2026-07-02 | T725 description ("LIVE crash, 2026-07-02 15:22:38, web_search go-live ceremony"); consistent with J-0704a correction (grammar off "on 2026-07-02") and ticket created 2026-07-02T17:39:14-05:00 |
| Grammar-off flip date | 2026-07-02 (same evening) | J-0704a correction ("production had turned the grammar OFF on 2026-07-02 (the #725 flip, `ad05047`)"); T725 (flip commit 1befbb1 / merge ad05047). "Same evening" = crash 15:22 local, ticket+flip same day |
| Characterization runs | 2026-07-04 | J-0704b entry date; upstream package assembled per its plain summary |
| Fix + verification runs | 2026-07-05 | LOG entry date; JSON timestamp 2026-07-05T15:34:27 |
| Issue #4081 filed | 2026-07-05T23:01:19Z | API issues/4081 created_at |
| PR #4082 filed | 2026-07-05T23:06:08Z ("five minutes later") | API pulls/4082 created_at; 23:06:08 − 23:01:19 = 4m49s ≈ five minutes |
| Copilot review + nit | 2026-07-05T23:08:57Z | API pulls/4082/reviews + /comments |
| apaniukov approval | 2026-07-06T07:54:06Z | API pulls/4082/reviews |
| CI triage comment 1 | 2026-07-06T17:41:52Z | API issues/4082/comments |
| Merge-queue ejection | 2026-07-07, 09:21 UTC | Contributor comment 2026-07-07T17:02:13Z (API), quoting the queue removal at "09:21 UTC today" |
| pavel-esir approval | 2026-07-08T11:09:06Z | API pulls/4082/reviews |
| Merge | 2026-07-08T13:07:36Z | API pulls/4082 merged_at (merged=true, base=master) |
| Issue auto-close | 2026-07-08T13:07:38Z ("two seconds later") | API issues/4081 closed_at; 13:07:38 − 13:07:36 = 2 s |
| Latest upstream release | 2026.2.1.0 published 2026-06-17T15:15:48Z | API releases list (newest row) |
| From-source GPU plugin build | 2026-07-06 | PERFORMANCE_LOG 2026-07-06 GPU-plugin entry ("built from source at last") |
| sglang precedent merged | 2025-12-06 (T14:15:22Z) | API sgl-project/sglang pulls/14464 merged_at |
| Access dates in draft | 2026-07-19 | Session date confirmed via local clock (2026-07-19 17:12, local UTC−05:00 — the zone every local artifact timestamp carries; v1 of this row misstated it as PDT, caught by the panel as fact Y6) |

Derived date arithmetic:
- **"Six calendar days"** first crash → merge: 2026-07-02 → 2026-07-08 = 6 days. ✔
- **"About 62 hours"** filing → merge: 2026-07-05T23:06:08Z → 2026-07-08T13:07:36Z = 62h 01m 28s. ✔
- **"Three weeks before the merge"** (release 2026-06-17 vs merge 2026-07-08) = 21 days exactly. ✔
- **"The day before the crash"** (grammar shipped ON 2026-07-01; crash 2026-07-02): J-0701 "Retiring the homemade dialect" entry date + commit 748cd0a. ✔
- **"Six days later" in the lede** = the same 07-02→07-08 span as above. ✔

## 2. Counts and measurements

| Item | Value in draft | Re-derived from |
|---|---|---|
| Baseline crashes | 1 / 95 generations, GPU, 5 passes | JSON results[0]: passes 5, generations 95, crashes 1, device GPU, crash_case generic-11 |
| Patched crashes | 0 / 95, CPU, matched sample | JSON results[1]: passes 5, generations 95, crashes 0 |
| Control (spec-decode OFF, patched) | 0 / 19 | JSON results[2]: passes 1, generations 19, crashes 0 |
| Isolation figures | 1/76, 1/57, 2/38 (~1–5%); streamed 0/57; spec-OFF 0/57; no-grammar 0/19 | Live issue #4081 Evidence table (API); cross-checked: J-0704b gives 0-for-57 spec-OFF + ~1–2% generic-set rate; J-0704a correction gives 2 crashes/38 grammar-ON + 0/19 grammar-OFF (the 2/38 and 0/19 rows' origin) |
| Rate arithmetic | 1/76=1.3%, 1/57=1.8%, 2/38=5.3%, 1/95=1.1% → "~1–5%" envelope | Direct arithmetic; envelope matches the issue's own "~1–5%" |
| Token-capture run | 57 streamed generations, zero `<tool_call>` emissions | J-0704b finding 1; issue #4081 observation 2 (same 57) |
| Companion warning token id | 498 (ordinary word-piece) | Issue #4081 warning block; J-0704b finding 2 |
| Prompt set (measured arms) | 19 generic conversational prompts | JSON methodology.prompt_set; LOG methodology line. 5×19=95 ✔ |
| Inline issue reproducer set | 15 questions (kept distinct from the 19) | Live issue #4081 QUESTIONS list (counted: 15) |
| Diff size | +4/−1, 1 file, in `src/cpp/src/sampling/structured_output/xgrammar_backend.cpp` | API pulls/4082: additions 4, deletions 1, changed_files 1; /files confirms the single filename |
| PR commits | 2 (fix 4c797722 + nit-fix 5200f1eb) — count not printed in draft; "a follow-up commit" is | API pulls/4082/commits |
| Approving reviews | 2 (apaniukov, pavel-esir) | API pulls/4082/reviews: exactly two APPROVED states |
| Jenkins triage numbers | 2 of 8 platform builds failed (win vs2022 release + debug); all GitHub Actions passed | Contributor PR comment 2026-07-07 (API, body names 6 of 8 passed + the two failures) |
| GGUF timeout triage | 1-hour job timeout while downloading a model; cases that ran all SKIPPED | Contributor PR comment 2026-07-06 (API body) |
| CPU per-generation cost | "roughly 53 seconds" | JSON results[1].elapsed_s 5075.9 ÷ 95 = 53.43 s; LOG states ~53.4 s/gen with the "not a throughput claim" framing the draft mirrors |
| Truncation history | planned 17 passes / 323 generations → truncated to 5 / 95 | J-0705 ("sized at 17 passes (323 generations)… truncated to 5 passes (95 generations)"). Note 17×19=323 ✔ |
| System-prompt size kept out of reproducer | 841 tokens | J-0704b ("the 841-token production system prompt") |
| RAM spec | 32 GB LPDDR5X | JSON environment.cpu/CLAUDE.md host row; VERIFIED_FACTS "the box" row |
| Re-enable criterion | pinned-release fix + 20/20 boundary soak + 1 live tool turn | T725 work item 3; J-0705 **Next:** block (identical criterion) |

## 3. Versions

| Item | Value in draft | Re-derived from |
|---|---|---|
| Crashing wheel | OpenVINO GenAI 2026.2.1.0-3123-7dea0459b2a (win_amd64, cp311) | JSON environment.openvino_genai_baseline; issue #4081 Environment block |
| Rebuild commit | `7dea045` on `releases/2026/2` — the exact commit the wheel was built from | JSON environment.openvino_genai_source_commit; LOG methodology |
| Python | 3.11.9 | JSON environment.python. (Deliberate: the app layer's 3.12 is irrelevant here — the reproducer venv is cp311, matching the wheel tag.) |
| OS | Windows 11 Pro, build 26200 | JSON environment.os |
| GPU driver | 32.0.101.8826 | JSON environment.gpu |
| Models | Qwen3-14B INT4 (target); Qwen3-0.6B pruned 6-layer INT8 (draft); num_assistant_tokens=3 | JSON models + methodology.decode |
| Decode config | greedy do_sample=false, max_new_tokens=512 | JSON methodology.decode; issue #4081 Environment |
| Latest upstream release at access | 2026.2.1.0 | API releases + tags (newest both lists) |
| xgrammar | "as vendored in the GenAI build" (no version number printed) | Issue #4081 Environment ("vendored … _deps/xgrammar-src"); no separate version is asserted anywhere, so none is printed |

## 4. §B trap checks (AUTHOR_KIT §B 1–4)

1. **Journal/project age:** not referenced in S4. No age claims printed. ✔
2. **Upstream state:** "merged" re-verified via API on the day of writing
   (pulls/4082 merged=true). **Release inclusion separately verified NOT-shipped
   on 2026-07-19** via three independent reads: releases list (newest =
   2026.2.1.0, 2026-06-17), tags list (nothing newer), and commit-containment
   compares (2026.2.1.0...eed42c80 = diverged → not contained;
   master...eed42c80 = behind, ahead_by 0 → contained in master). The draft
   states merged-not-released with its access date and never names a future
   release. **VOLATILE — re-run this exact check at panel, at ceremony, and on
   posting day.** ✔
3. **Superseded figures:** the crash/verification figures have no later
   supersession — searched PERFORMANCE_LOG for xgrammar/#725/4082 mentions
   after 2026-07-05: the only later touches are the 2026-07-06 GPU-plugin entry
   (names the future GPU re-verify unlock; reflected in the draft's "on the
   project's queue" sentence) and a 2026-07-14 region ISS-3 note attributing an
   unrelated eval improvement "most plausibly" to the #725 fix-adjacent
   substrate work — deliberately NOT used in the draft (attribution is
   explicitly non-definitive in the source). No tok/s figures appear in the
   draft at all, so the 1.8×/1.2× and 14B-decode supersession traps are not in
   play. ✔
4. **Counts as-of dates:** the one count that drifts (release inclusion) is
   access-dated in print. All run counts are frozen historical measurements
   tied to their JSON. ✔

## 5. Quote verification

- The assertion string, the BEFORE code block, and the streaming-caveat
  sentence are quoted from the **live** issue #4081 body fetched via API on
  2026-07-19 (saved to session scratchpad). The live body was diffed against
  the committed local copy `docs/upstream/725_xgrammar_stop_token/ISSUE_BODY_FINAL.md`:
  word-identical; the only differences are dash/multiplication-glyph encoding
  artifacts introduced by the diff harness's console decoding, not by content.
  Draft quotes use the live (em-dash) form.
- The disclosure boilerplate is AUTHOR_KIT §F verbatim.
- No dialogue is reconstructed anywhere; the two maintainer interactions are
  described from API-fetched records (review states, comments), not quoted.

## 6. Privacy / leak screen notes (§D) for the panel

- No local usernames, hostnames, or absolute paths appear in the draft. The
  verbatim assertion is quoted in the short form the public issue uses (the
  launcher.log variant in ticket #725 embeds OpenVINO's own CI build path —
  intentionally not used).
- Internal component names (Assistant Orchestrator, Policy Agent, PGOV, ticket
  numbers #718/#725, commit SHAs of the private repo) are excluded from the
  draft; "the application's fail-closed error handling" is the public-register
  description. Vikunja/journal/log citations in the companions are
  panel-internal; the draft itself cites only public-mirror URLs + GitHub.
- All repo links in the draft point at `blairducrayoppat/blarai-public`
  (existence of each cited path on the mirror API-verified 2026-07-19:
  PERFORMANCE_LOG.md, the verification JSON, the upstream package incl.
  reproducer + generic prompts). **Mirror freshness caveat:** the mirror syncs
  weekly and leak-gated; before posting, confirm the mirror's PERFORMANCE_LOG
  copy includes the 2026-07-05 entry text current at that date. §C's
  "path @ short-SHA" is intentionally deferred to publish time: the public
  mirror is an unrelated git history, so pinning mirror-side SHAs is a
  ceremony-packet step, not a draft step.
- The draft names the project only as "a personal research project" / "a
  long-term local AI system" — no "prototype," no "nearly done," no BlarAI
  branding decision pre-empted (the mirror URL itself carries the name; that
  is existing public state).

## 7. Known open items for the review panel

1. **Release-inclusion re-check** on panel day + ceremony day + posting day
   (trap 2 above) — the single most likely fact to move.
2. **Venue variant:** this is the home-base canonical long-form. If the LA
   approves an HN submission it is a plain link to home base (no Show HN — the
   survey's rule read; no numbers in the title per HN guidance). No short
   variant drafted yet.
3. **Maintainer-name usage:** the draft credits the two approving reviewers by
   GitHub handle with no role claims. Panel should confirm this reads as
   credit, not name-dropping, per the collaborative-upstream rule.
4. **The 2/38 grammar-ON figure** (from the eval harness's accidental
   grammar-ON runs) is inside the issue's evidence envelope and printed only
   as part of that quoted envelope, not narrated separately — the fuller
   eval-posture story (the config-fidelity correction of 2026-07-04) belongs
   to P3's instrument-trust material, not S4. Deliberate scope cut.
5. **Fact-sheet correction candidates for the program session:** none found —
   VERIFIED_FACTS' #4082 row matched the live API on every field re-checked
   (merged_at, approvals, DCO, disclosure, head branch, commit 4c797722).
   Suggested ADDITION (not correction): a row for the release-inclusion
   check's three-read method (releases + tags + containment compares) so S2/S3
   authors re-run it identically.
6. **External references re-verified first-hand this session** (not inherited
   from the survey): arXiv:2508.06753 — title "Pushing the Envelope of LLM
   Inference on AI-PC and Intel GPUs" (Georganas et al.) confirmed from the
   abs page, and "Intel Core Ultra 7 258V" + "Intel Arc 140V … Lunar Lake
   (LNL) platform" confirmed present in the v2 HTML full text (fetched
   2026-07-19). sglang PR #14464 merged_at re-read via API (2025-12-06). The
   draft's "Intel's first-party enablement posts" stays generic and unlinked
   on purpose: the survey's specific Intel page returned HTTP 403 on all
   routes (P1-verdict §1C), so no specific Intel URL is cited.
7. **Author self-audit edits applied before the panel** (v1, this session):
   lede "two-line fix" → "the fix" (diff is +4/−1; "two-line reorder" applies
   to `apply()` only); "same evening" → "same day" (only same-day flip is
   evidenced); isolation narrative no longer scopes all four evidence-table
   rows to the 19-prompt set (the 2/38 and 0/19 rows originate from the
   2026-07-04 eval-harness grammar-posture runs per the journal correction;
   the table is now explicitly attributed "as published in the issue");
   "first-time contributor" → "unknown contributor" (first-time status not
   verified); series footer un-numbered (S4 may publish first); methods block
   now scopes 5×19=95 to the verification arms only.

---

## Panel disposition (2026-07-19/20)

Every finding from the four-reviewer adversarial panel, dispositioned in
writing per README §4. Verdicts: **accept-fix** (implemented in draft v2
and/or claims table v2), **accept-fix-partial**, **rebut**. All fixes referenced
below land in the same commit as this section.

### RED findings (all five fixed — zero unresolved reds)

**R1 (fact auditor; independently found as rigor Y7 — one fix).** Finding:
"'Both are signed off under the Developer Certificate of Origin' is false for
the issue — DCO sign-off is commit-level; only the PR's commit (4c797722)
carries Signed-off-by. The issue has an AI-assistance disclosure, not a DCO
sign-off." **Accept-fix.** The draft now reads "The pull request is signed off
under the Developer Certificate of Origin, and both carry an explicit
AI-assistance disclosure." Claims row 30 rewritten to state the commit-level
mechanism and the issue/PR asymmetry explicitly. The panel is right on the
mechanism: DCO is a per-commit attestation and an issue has no commits to
attest.

**R2 (fact auditor).** Finding: the prose in "A reproducer strangers can run"
conflated the COMMITTED reproducer (19 prompts, two-tool enum schema — what
was re-run and measured; every isolation figure is a multiple of 19) with the
ISSUE's inline script (15 questions, single generic schema, no tool enum),
violating the claims table's own "do not merge them" note. **Accept-fix.** The
section now states both artifacts separately: the rebuilt/measured reproducer
as 19 prompts + two-tool schema ("those 19 prompts are the unit behind every
figure in the verification arms"), and the issue's inline script as a distinct
self-contained artifact with its own 15-question set. No claim is made that
the inline script's crash behavior was independently re-measured. Claims
row 14 rewritten to match; the auditor note under the table now records that
v1 violated it and v2 does not.

**R3 (fact auditor).** Finding: "two days of controlled elimination" does not
re-derive — the documented elimination work is dated to exactly one day
(2026-07-04); and the claim appeared in no claims-table row. **Accept-fix.**
Re-derived from the journal: all characterization runs live in the single
2026-07-04 entry ("The crash that only happens when two right things run
together"), and the mirror's copy of that entry was fetched raw this session
to confirm. The draft now reads "a day of controlled elimination bought a
one-minute source read" — the one-minute half was already verified (journal
2026-07-05: "confirmed it in under a minute") and is kept. New claims-table
row 46 types the sentence. The "three days from crash to root cause"
alternative was considered and rejected: the crash-to-merge arc is already
carried by the verified "six calendar days" claim, and the sentence's point is
the elimination-vs-read contrast, which the one-day form states most precisely.

**R1 (rigor skeptic).** Finding: the verification section overclaimed — at a
~1–5% crash rate, 0/95 vs 1/95 is statistically empty as "proof"; the "matched
sample beats a lopsided one" framing is backwards for demonstrating absence of
a rare event; the real proof is the mechanism argument; the 323→95 truncation
was a time-budget call. **Accept-fix, in full.** The rewritten passage: (a)
names the truncation a time-budget call "plainly … not a methodological
strength"; (b) states the chance-clean probability honestly — "at the ~1–2%
rate measured on this prompt set, an unfixed build would come up clean across
95 generations roughly 15–38% of the time by chance alone" (derivation:
(1−p)^95 for p ∈ [0.01, 0.02] → 0.385/0.147; new claims row 47; the ~1–2%
scope is the journal's generic-set rate — the same 19-prompt configuration the
95-generation arms ran — rather than the issue's all-runs ~1–5% envelope,
which includes the differently-configured 2/38 arm); (c) relocates "proof" to
the mechanism (guard reorder makes the asserting call unreachable on a
terminated matcher — deterministic, code-level); (d) reframes the 95-run
comparison as a demonstration / regression check; (e) drops the "beats a
lopsided one" sentence and concedes a larger patched arm would have been more
informative; (f) adjusts the patched-arm bullet ("truncated to the baseline's
sample size") so the bullet no longer pre-claims the virtue the next paragraph
disclaims.
**[PROPOSED item — GPU re-verification at larger N: NOT run this session.]**
Decision and reasoning: tonight's 23:00 GPU window is already committed to the
#790 gate-scoping A/B night, a large model-loaded run cannot share it, and the
GPU re-verify is already queued on the project's board (and named in the
draft). If it runs before the LA ceremony its result strengthens this section
and should be folded in at the ceremony-packaging pass; the draft as revised
is honest without it.

**R2 (rigor skeptic).** Finding: the brief's required written novelty GO/NO-GO
pass for S4's own genre was never produced, and the draft's gap claim ("what
such write-ups usually omit…") was an unsupported generalization — many
celebrated postmortems DO include false leads; what is plausibly rarer is the
machine-readable artifact trail. **Accept-fix.** The pass now exists:
`S4-novelty-pass.md` (same directory, this commit) — eight named genre
instances (six fetched/API-verified with access date 2026-07-19, two
reputation-known and marked as such), the danluu/debugging-stories index as
saturation evidence, and a two-candidate gap analysis. Outcome: the "usually
omit false leads" claim is DEAD (refuted by the 500-mile email, marcan's
Go-runtime hunt, GitHub's k8s post) and has been removed from the draft; the
gap is narrowed to the committed machine-readable artifact trail, scoped as
"in a written scan of the genre we could not find it done end-to-end" — never
"first" or "only." Draft's "What this adds" section rewritten; claims row 41
updated to cite the pass. Verdict in the pass: GO with the narrowed gap.

### YELLOW findings

**Audience editor — trim ~15–20% for the credibility-handshake positioning.**
**Accept-fix-partial.** Both named candidates are done: the sample-sizing
paragraph (53 s/gen, 323→95) is compressed into one sentence inside the
rewritten verification passage, and the merge-queue bullet is tightened to a
single sentence that keeps the CI-triage lesson. A full 15–20% cut was not
taken: the panel's own REDs added disclosure text (the statistics paragraph,
the reproducer separation, the protocol-provenance half-sentence), and cutting
elsewhere to hit a percentage would have removed exactly the hedging and
provenance material the rigor findings required. Net v2 length ≈ v1. If the
LA wants a shorter variant for a different venue, that is the ceremony
conversation; for home-base canonical long-form, completeness is the
positioning.

**Audience editor — "the discipline this series commits to" lands before any
series context exists.** **Accept-fix.** The lede sentence now carries the
naming clause: "told with the discipline of the series it belongs to — a
field-report corpus documenting one long-term local AI build." Deliberately
un-numbered (S4 may publish first; memo item 7 already records that choice).

**Privacy screen — drop "-only" from "local-only."** **Accept-fix.** Now "a
long-term, local AI assistant," matching the standing public framing; the
panel is also right that the public record itself documents the egress arc, so
"local-only" was contradicted as well as off-framing.

**Rigor Y1 — "device-independent by construction" stated as flat fact.**
**Accept-fix.** Now "we judged it device-independent, and disclosed that
judgment upstream as a judgment, not a fact" — the hedge sits in the sentence
itself, not 15 paragraphs later. Claims row 23 already typed it
INTERPRETATION; the prose now matches its own table.

**Rigor Y2 — isolation-table intro implied all four rows came from the
deliberate one-variable protocol.** **Accept-fix.** The intro now carries the
disclosure: the 2/38 fraction and the no-grammar 0/19 row "came not from that
deliberate protocol but from parallel evaluation-harness runs that happened to
hold the right configurations." The piece's stated identity is the false leads
left visible; this is one of them.

**Rigor Y3 — subtitle "every number on the public record"; two numbers
(841-token prompt, 323→95) trace only to BUILD_JOURNAL entries.**
**Accept-verified, subtitle stands.** The mirror's BUILD_JOURNAL.md was
fetched raw (raw.githubusercontent.com, 2026-07-19, this session): the
2026-07-04 crash entry (841-token sentence verbatim) and the 2026-07-05 fix
entry (17 passes / 323 generations / truncated to 5 passes (95)) are both
present in the public copy. Both numbers are therefore on the public record
and the subtitle is literally true. Standing instruction stays: re-confirm the
mirror copy at ceremony packaging (§6 mirror-freshness caveat, unchanged).

**Fact Y1 — table introduced "as published in the issue" but rows are
reworded.** **Accept-fix.** Now "condensed from the issue."

**Fact Y2 — the nit-fix commit (5200f1eb, 2026-07-06T07:53:58Z) sat under the
2026-07-05 bullet.** **Accept-fix.** The 07-05 bullet now carries only the
flag; the fix moved to the 07-06 bullet.

**Fact Y3 — the "reframe" sentence stated as narrative fact though
INTERPRETATION-typed, and the issue itself hedges.** **Accept-fix.** Now
attributed to the issue's own hedged wording: "in the issue's own hedged
words, what the failure 'appears to be.'"

**Fact Y4 — methods lead-in claimed everything is in the JSON+log, but the
JSON's `not_measured` array has 3 items, not 4 (row 44 wrong).**
**Accept-fix.** JSON re-read this session: three items (patched-GPU
performance, throughput/latency deltas, rate beyond n=95); the streaming
limitation lives in the issue, not the JSON. Row 44 corrected; the lead-in now
reads "the environment, workload, and run figures below are recorded in
[JSON+log] … the streaming limitation below is recorded in the issue itself."

**Fact Y5 — mirror-path citations carry no @short-SHA.** **Accept (already
flagged), no draft change.** §6 of this memo already defers mirror-side SHA
pinning to ceremony packaging with the reasoning (the public mirror is an
unrelated git history; pinning now would mint SHAs that the weekly sync can
strand). The finding's own alternative — "explicitly flag for the ceremony
packaging pass (task tracked separately)" — is the standing state.

**Fact Y6 — memo clock note said "17:12 PDT" but every local artifact
timestamp is −05:00.** **Accept-fix.** §1's access-date row corrected to
"local UTC−05:00" with a note naming the v1 error. Draft unaffected (no
printed claim depends on the zone label).

**Fact Y7 — "written down the day of the crash and hasn't moved" not fully
provable (Vikunja exposes no description-edit history).** **Accept-fix
(soften).** Now "was written down the day the crash happened and still
governs" — "written that day" is evidenced (ticket #725 created
2026-07-02T17:39:14−05:00 with the criterion; journal 2026-07-05 Next: block
restates it identically), and "still governs" is a present-state claim
checkable on the board today. The unprovable non-edit assertion is gone.
Residual accepted: we cannot prove the ticket text never changed between those
two independently dated records; the two-record consistency is the evidence.

### Standing re-checks run this session (the program's third independent check)

- **PR #4082 / release-inclusion, API, 2026-07-19 (revision session):**
  `pulls/4082` → merged=true, merged_at 2026-07-08T13:07:36Z, base=master,
  merge_commit eed42c806b70…; releases list newest = 2026.2.1.0 (published
  2026-06-17T15:15:48Z); tags list nothing newer; compare
  `2026.2.1.0...eed42c80` = diverged (not contained). Unchanged from the
  survey-day and panel-day reads: **merged 2026-07-08, not in any release.**
  The draft's sentences stand as written. Next checks: ceremony day, posting
  day.
- **Mirror journal raw fetch** (Y3 above): 07-04 and 07-05 entries present in
  the public copy, both journal-only numbers included.
- **JSON `not_measured` re-read** (Y4 above): three items, verbatim captured.
