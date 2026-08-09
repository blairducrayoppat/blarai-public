---
title: Coder Definition of Done — full review, errors, gaps and maturation guidance
status: complete
area: design
date: 2026-08-07
ticket: "#1323"
---

# Review of the coder Definition of Done (2026-08-07)

**Asked by the Lead Architect:** are elements missing, are additional criteria needed, are there
errors, and how should this document mature so the work checked against it produces the working,
reliable, robust, secure agentic coder he described.

**Verdict, in one paragraph.** The document is fundamentally sound and its honesty discipline —
statuses only by measurement, corrections kept in view, `UNKNOWN` preferred over optimism — is its
best feature and worth protecting. The review verified its load-bearing claims with three
independent sweeps (code, deployed configs and state ledgers, and the ticket board) in the hour
after it merged, and found: **ten errors or drifts, all fixed the same evening** (the largest: a capability
row whose headline contradicted its own correction block, and a residuals list the board had
overtaken); **five missing capabilities**, each traceable to a clause of the operator's own goal
statements that no row expressed — the largest being requirement coverage, which the overhaul
programme called "the single largest gap against proper exams" and which had quietly lost its home
when this document replaced that programme as the target; and **one structural weakness**: nothing
machine-checks this file, so its statuses rot silently between the moments someone happens to
re-measure — which is exactly how three of its rows went stale within days of being written. The
fixes are merged; the new capabilities and the enforcement are PROPOSED and queued for the
operator's ratification on #1325.

---

## 1. What was verified, and how

Three read-only verification agents ran in parallel within the hour after the document merged
(`e7628176`, 16:54 local):

- **Code sweep (BlarAI repo):** all nine advanced-intake flags and their line numbers; the
  missing GUI path (`MainWindow.xaml.cs:322`); the unreachable property-execution finding; the
  undatamarked research paths; the docset index (102,858,752 bytes) and manifest (15 artifacts,
  134.6 MB); the recipe-site single commit `311cd66`; the disposition-verifier grammar.
- **Config/state sweep (agentic-setup + deployed):** the pytest invocation with no statistics
  flag; the deliberately omitted `-StatsPath`; zero `search_docs` mentions in the deployed brief,
  repo HEAD and the pinned battery tree; the add-then-revert commit pair (`219d899` 10:12 →
  `609a925` 17:13, both 2026-08-06, author `harness-sync` on the revert); the usage ledger
  (1,989 records, 3 developer probes, zero coder lookups — confirmed by a sweep of all 887 coder
  transcripts); the acceptance corpus (206 records through 08-06, zero clarification axes, zero
  operator assets, and no clarification key in the schema at all). Ledgers were snapshotted at
  17:48, before the 23:00 battery window.
- **Board sweep (Vikunja):** all 24 tickets the document cites, read at description level.
  Five had closed the same afternoon, 15:15–17:02 local — #1318 and #1231 before the document
  merged, #1197/#1201/#1198 after it — which is what made capability 7's residuals list wrong
  within hours.

**Substance held everywhere.** Every conclusion the document draws survived verification. The
errors below are in citations, headlines and board-lag — which is the document behaving exactly
as it warns statuses behave, and the argument for section 5.

## 2. Errors found — all FIXED in `6b8e55db`

1. **Capability 6's headline contradicted its own correction.** The status line still read
   "armed … and instructed" while the correction block beneath it had established ARMED + MUTE
   (#1320: the instruction was reverted by a harness-sync seven hours after it shipped). The row's
   own closing lesson — *"the status line is what gets read"* — convicted its own headline.
2. **Capability 7's residuals were overtaken by the board.** "#1198, #1200, #1203 open" was wrong
   by evening: #1198 CLOSED (fixed 2026-07-30 as agentic `5d1d5db`, ticket unclosed for a week —
   the same shape as capability 1's week of false PARTIAL); #1200 and #1203 have their fixes
   MERGED (`24878d88`, `b5d881a4`) and stay open only on named verification predicates (a real
   @slow-tier parity run; a pinned-tree battery night, #1301).
3. **Capability 4's citations had drifted.** `property_execution_finding()` is defined at
   `coder_test_qa.py:659` (sole call `:1003`), not `:995`; the production call sites are
   `new-agent-task.ps1:601`/`:713`, not `:592`; and `PropertyExecutionMeasured` is the DISCLOSURE
   field, not the gate — the gate is that no production call passes `-StatsPath`/`-RequireProperty`.
4. **Capability 3 under-cited its own evidence — an error in the cautious direction, still an
   error.** The planted-defect observable HAS been executed at instrument level
   (`test_green_quality_security.py`: planted Stripe-shaped key, f-string SQL, `innerHTML` sink →
   findings + band C; plus a seed-proof against a REAL archived delivery). The row cited only the
   field data. The row also now carries the overhaul programme's still-true caveat that craft
   grading is Python-centric (node/web coverage thinner) — an addition, disclosed here and in the
   disposition block.
5. **Capability 5 called a function-level proof "end-to-end."** The review-skip decision function
   was exercised with a real delivery's inputs; an actual withdrawal inside a live dispatch has
   never been observed. The status now says which of those is true.
6. **Capability 2's sweep figures tightened** (206 exact, not "~200") and strengthened: the
   acceptance schema holds no clarification key of any spelling — the record cannot even express
   the thing whose absence the row reports.
7. **Capability 8's tracked list** was missing #1285 (parked work preserved but unfindable), and
   its "none of it exists" now quotes #1277's own record so the fixed-handle/no-resume split
   cannot be misread.
8. **Two small figure/site corrections:** 62 gate tests → 63; the plan-time injection lives in
   `decompose.py:1248` (plan_grounding is pull-only).
9. **"It is deliberately short" was no longer true** — replaced with the rule that made it true
   ("if a criterion cannot be OBSERVED, it does not belong here").
10. **Neither acceptance test carried an execution status.** Both now state **Executed: NEVER** —
    the document's two headline observables were the only observables in it without a status.
    (These two lines are measured facts and are FIXED, not proposals — nothing about them awaits
    ratification on #1325.)

**Errors suspected and REJECTED under verification** (recorded because a review that only reports
hits teaches nothing about its misses): the capability-8 "#1277 fixed / none of it exists"
tension is real ticket language, not a contradiction — #1277's description explicitly separates
the fixed recovery handle from the nonexistent resume path; and the add/revert commit-date chain
in capability 6 is exact (both commits 2026-08-06, lifespan seven hours and one minute).

## 3. Missing elements — five new capabilities, PROPOSED on #1325

Method: every clause of the operator's two quoted goal statements was mapped against the rows (the
map is now in the document). Five clauses had no row:

- **17. Requirement coverage** — the largest. "Proper exams" today means the exam can fail
  (capability 4). Nothing asks whether it covers what was asked: every GREEN ever produced is
  `GREEN-UNVERIFIED`, meaning *the oracle passed*, not *the deliverable does what was asked*. The
  overhaul programme called this the single largest gap; the instrument has since shipped
  (`green_quality/traceability.py`) — and no row claimed it, so tickets #967/#1015 were serving no
  numbered capability, which by the document's own "How to use this" makes them questionable.
  This is how a target document loses a goal: the programme that owned it was superseded by a
  document that never picked it up.
- **18. Media content** — "image, voice, narration, and animation generation as content" is a
  direct operator clause; capability 10 covers words and waved media to "the roadmap," which is
  not an observable.
- **19. Difficulty-scaled candidates** — "proper multiple candidates based on how difficult";
  nowhere in rows 1-16.
- **20. Decomposition graded** — "proper decomposition"; its only trace was a defect (#1279's
  silent 8-task truncation that cut the pottery site's plan from 9 units to 8).
- **21. Verdict stability** — the operator's word "reliable"; was a "lower confidence" footnote,
  now promoted to a row: a grader whose band flips across identical runs invalidates every number
  in the document.

Plus two amendments to ratified rows (his call): row 6 gains *code seeds* (a clause of his goal
absent from the whole document) and research-at-every-step; row 8 gains *proper error handling*
(any failure parks honestly; no failure path ends in a silent pass).

## 4. The proposed capabilities 11-16 — ratification aid

All six are sound and worth ratifying. Three were sharpened in place (review notes in the
document): **11** gains *re-execution when the instrument changes* (an observable executed once on
an instrument since repaired is UNVOUCHED, not LIVE — capability 4's exact case); **14** gains a
*re-proof cadence* via planted-defect canary deliveries through the real pipeline (a control
proven to fail once can still be edited into silence later — the #1142 README-marker case);
**15** gains a *named isolation boundary* (exercising a built site executes untrusted code — where
it runs is a security-by-design decision to make first, not after). One dependency worth knowing
at ratification: **12 cannot start before 9 exists** — the operator's eyeball verdict is the
ground truth the false-negative count needs; 9 and 12 are one loop.

## 5. Maturation guidance — how this document stops rotting

1. **Adopt the status legend** (in the document, ratifies with 11): LIVE / ARMED / PARTIAL /
   UNKNOWN / STOOD-DOWN + the UNVOUCHED modifier. Three different rows drifted within days
   partly because "LIVE", "FLAGS LIVE", "MOSTLY LIVE" and "armed and instructed" had no agreed
   meaning.
2. **Machine-check the file.** Verified today: this document is in no size budget, no vocabulary
   scan, no freshness check — nothing fails when a status here goes stale, which is a weaker
   standard than the repo applies to CLAUDE.md or ACTIVE_SPRINT. After ratification, a gate test
   should parse every row against the legend grammar and fail any LIVE without a cited run.
3. **Re-measure at named events, not on inspiration** — before any related go-live, and at the
   monthly retrospective. Capability 1 read wrong for a week, 2 for a week, 6 for seven hours,
   7 for three hours: drift between measurements is the norm, so the measurements need a cadence.
4. **Citation discipline:** a status names its instrument AND its run artifact (the
   start-and-finish stamp lesson from the test-governance baseline applies here unchanged).
5. **Row hygiene:** rows are accreting history (capability 6 is ~60 lines). Keep DONE-means +
   observable + current status + one lesson line; the narrative belongs on tickets and in the
   journal — with the deliberate exception that corrections stay visible until re-measured.
6. **Keep the coverage map current:** it is the instrument that found gaps 17-20, and it only
   works if a new operator goal statement is folded in when he makes one.

## 6. Context notes for whoever reads the numbers later

A battery run on **B9 — the pottery site, the operator's own goal shape** — went live at 17:47
during this review (run `20260807-174202-bd`, dispatch budget 4). Every ledger figure above was read
and snapshotted at 17:48 (snapshot in the session scratchpad; figures reproduced here and in the
document). Artifacts newer than that run's start postdate this review's evidence. Two defects
found outside the document (config prose asserting DORMANT beside a `true` flag; a docstring
claiming a consumer that does not exist) are ticketed as #1326 rather than fixed, because the
live run was reading one of the files concerned.

---

```disposition
# finding | status | evidence-or-predicate
cap6 headline contradicted its own ARMED+MUTE correction | FIXED | 6b8e55db
cap7 residuals list overtaken by the board (1198 closed; 1200/1203 landed-in-code) | FIXED | 6b8e55db
cap4 citations drifted (:995/:592; disclosure field misnamed as the gate) | FIXED | 6b8e55db
cap3 under-cited its planted-defect and real-archive proofs | FIXED | 6b8e55db
cap5 status called a function-level proof end-to-end | FIXED | 6b8e55db
cap2 sweep figures loose; schema cannot express a clarification | FIXED | 6b8e55db
cap8 missing #1285; fixed-handle/no-resume split made explicit | FIXED | 6b8e55db
62 gate tests are 63; plan-time injection site is decompose.py:1248 | FIXED | 6b8e55db
"deliberately short" no longer true | FIXED | 6b8e55db
cap3 gains the sourced Python-centric craft caveat (addition disclosed post-review) | FIXED | 6b8e55db
acceptance tests carried no execution status (both now Executed: NEVER) | FIXED | 6b8e55db
missing capability: requirement coverage (proposed row 17) | DEFERRED | #1325 blocked-by: LA ratification decision recorded on #1325
missing capability: media content generated placed graded (proposed row 18) | DEFERRED | #1325 blocked-by: LA ratification decision recorded on #1325
missing capability: difficulty-scaled candidate count (proposed row 19) | DEFERRED | #1325 blocked-by: LA ratification decision recorded on #1325
missing capability: decomposition graded not just performed (proposed row 20) | DEFERRED | #1325 blocked-by: LA ratification decision recorded on #1325
missing capability: verdict stability promoted to a row (proposed row 21) | DEFERRED | #1325 blocked-by: LA ratification decision recorded on #1325
row 6/8 amendments: code seeds, research-at-every-step, error handling | DEFERRED | #1325 blocked-by: LA ratification decision recorded on #1325
status legend + machine-check gate test for this file | DEFERRED | #1325 blocked-by: ratification on #1325, then ships tests/security/test_coder_dod_grammar.py
fleet-driver research_docs_note says DORMANT beside research_docs true | DEFERRED | #1326 blocked-by: #1326 and no dispatch reading configs/fleet-driver.json
BlarAI tools/search_docs.py docstring claims a consumer it does not have | DEFERRED | #1326 blocked-by: #1326
suspected cap8 contradiction (#1277 fixed vs none exists) | REJECTED | verified consistent: the ticket's own description separates the fixed recovery handle from the nonexistent resume path
suspected date error in the add/revert commit chain | REJECTED | verified exact: both commits 2026-08-06, section lifespan seven hours one minute, harness-sync authored the revert
cap4 LIVE wording vs PARTIAL under the proposed legend | DEFERRED | #1325 blocked-by: legend ratification on #1325 relabels statuses in one pass
```
