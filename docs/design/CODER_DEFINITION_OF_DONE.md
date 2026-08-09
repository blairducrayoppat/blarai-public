---
title: The coder — what "working" means, and how we know
status: living
area: design
owner: Lead Architect (the WHAT); Claude sessions (the HOW)
---

# The coder: definition of done

**Why this file exists.** On 2026-07-30 the Lead Architect asked *"I need to make sure you all
understand what the goal is right now."* He was right to. There was a defect inventory (#1195),
a measurement-gaps programme (`coder-fleet-overhaul-program-2026-07-30.md`) and thirty tickets —
and **nothing stating what a working coder IS**. Work was being done item-by-item against a list
of broken things rather than against a target, and every agent brief described a task without the
goal it served.

This is the target. Every coder-fleet ticket, agent brief and go-live should be checkable against
it. Its rule of admission: if a criterion cannot be OBSERVED, it does not belong here.

---

## The goal, in the operator's words

> *"a working, reliable, robust secure coder that can do secure python and secure websites, that
> has the advanced intake and advanced interview, a local corpus, and proper exams and reviewers."*
> — LA, 2026-07-30

And, extending it — the priority that this document could not express until capabilities 8-10 were
added:

> *"my current priority is for it to be able to engineer relatively complex website with multiple
> pages … advanced interview; advanced intake; proper user-asset incorporation … proper use of code
> seeds and/or the local corpus; proper ability to research answers it needs at the various steps …
> proper image, voice, narration, and animation generation as content for websites; proper test
> authoring; proper test authoring reviews; proper test execution; proper multiple candidates based
> on how difficult; proper decomposition … proper error handling; proper coordinator reviews;
> proper multiple iterations until a working finished product; proper parking of non-working
> product; proper inspection of parked product and picked up to iterate until completion; proper
> automated testing, including live visual and functional tests … We don't need to one-shot
> websites any more."*
> — LA, 2026-08-06

And the standard it is held to, from `CLAUDE.md`:

> *"A build that works but was not designed to these principles is a defective build — same
> standing as a failing gate."*

---

## The capabilities, and what each means when it is DONE

**1-7 were written for the 2026-07-30 goal above and are about ONE dispatch being honest and
complete. 8-10 were added 2026-08-06 for the multi-page-website goal, which no number of clean
single dispatches can satisfy.** Both goals are live; neither supersedes the other.

Each row is a capability, an **observable** acceptance test, and where it stands. Status is
measured, never asserted — an unmeasured capability is `UNKNOWN`, not `done`.

### 1. It builds what was actually asked for
**Done when:** the plan the operator approves is the plan that gets built, and no requirement is
attributed to him that he did not give.
**Observable:** a dispatch on a fresh repo never prints "The person clarified these requirements"
above an answer the system invented.
**Status: LIVE as of 2026-07-30** (`888b1b02`). Fixed on the advanced-intake path by #1174
(`de136b3c`), then on the default quick path by #1197 — verified by replaying
`20260729-164648-bd` through the real `DispatchCoordinator` on a plain `/dispatch` with no
`advanced` token (platform question `False`→`True`), and across a restart. The quick path now
records axes and separates operator-authored answers from system-chosen ones. Residual #1216
(surface provenance not threaded to the fleet queue) is a different hole.
*(Re-measured 2026-08-07. This row read PARTIAL for a week after the fix shipped, because
#1197's ticket was never closed and this document reads the board.)*

### 2. Advanced intake and interview
**Done when:** a non-technical operator is interviewed in plain language, can say "I don't know",
and sees his own words played back in the plan.
**Observable:** the live flags are on and an operator-driven dispatch completes without a
technical question being asked of him.
**Status: ARMED — all nine flags live; the observable was ATTEMPTED for the first time on
2026-08-08 and did not complete.**

**2026-08-08, the first attempt ever made.** The LA ran the exercise: the interview asked in
plain language, he answered `I don't know` and it moved on, the plan card played his own
words back, and he pressed **Approve & build** — the step this row had recorded as taken
zero times. The dispatch then delivered and merged **3 of 9 tasks** (`home-page`,
`pieces-list-page`, `individual-piece-page`; 10 commits, 5 pages in
`C:/Users/mrbla/projects/pottery-studio`) before `contact-page` parked. Run
`20260808-104536-bd`. **No technical question was asked of him at any point** — the intake
half of the observable held.

**It is still ARMED, not LIVE, because the observable says a dispatch COMPLETES and this one
did not.** What stopped it is capability 8's gap, demonstrated live rather than argued from
source: the park produced a `coord_redispatch` proposal at 14:02:35 that nothing consumes,
and there is no path that would let a later run pick the work up (#1321).

The exercise also worked as an instrument and found four defects, **three of them in its own
instructions rather than in the product**: the printed command was the run-an-existing form
and cannot work on a new project; BlarAI's own footer prints the same broken command; the
`advanced` token was silently absorbed into the project name when it came second; and step
1's guidance would have had him file a false report (#1335). New rule earned: **an
exercise's commands must be executed before they are printed.** All nine flags verified `true` on
disk 2026-08-07 (`default.toml:484, 523, 610, 656, 697, 740, 788, 824, 870`), each behind an
LA-present ceremony.

**But the observable above says a dispatch *completes*, and none ever has.** Measured
2026-08-07: `C:/Users/mrbla/projects/recipe-site` holds exactly one commit (`311cd66`, created
by BlarAI, assets in place and never consumed), and across **all 206**
`agentic-setup/state/fleet-runs/*/acceptance.json` records through 2026-08-06 (re-swept 2026-08-07
17:48 local; a 207th run was in flight that evening), **zero** carry an axes-tagged clarification,
**zero** carry `spec.operator_assets` — and the schema holds no clarification key of any spelling,
so the record cannot even EXPRESS one. The interview has been
driven to the plan card twice (#1031 S2; #1165 c.2665, 2026-07-29) and **approved zero times**.
The assets use-floor, exam grading on operator photos, and the entire BUILD half of this
capability have never executed on a real dispatch.

This row read `LIVE` for a week. It was true of the flags and false of the capability, and the
distinction is the whole point of an observable — see capability 11 below.

Known scope limits for a first run: #1165's **M2** (the interview's assets QUESTION), **M3**
(propose-and-veto) and **M6** (reference emulation) are unbuilt — no branches, no commits — so
the interview will not ask about assets and `assets/reference/` is read by nothing. There is
also **no GUI path**: the New-project button emits `/dispatch new` with no `advanced` token
(`services/ui_winui/MainWindow.xaml.cs:322`); the only route is typing
`/dispatch advanced <project> | <goal>` into the composer.

### 3. Secure Python and secure websites
**Done when:** the coder is TOLD what secure means and GRADED on whether it complied, on every
surface it can build.
**Observable:** a planted credential or injection sink in a delivery is reported, not banded A.
**Status: LIVE as of 2026-07-30** (#1182). Brief rules 4–8 + `green_quality/security.py`.
Measured across 144 real deliveries: 141 band A, 5 findings, all genuine. The planted-defect
observable has itself been executed at instrument level — this row under-cited its own evidence
until 2026-08-07: `tests/integration/test_green_quality_security.py` plants a Stripe-shaped key,
an f-string SQL query and an `innerHTML` sink and asserts findings plus band C, and
`test_seed_proof_real_b5_archive_has_an_html_injection` proves the scanner fires on a REAL
archived delivery, not only on defects its own author planted. Residuals #1188, #1193. Caveat
carried from the overhaul programme and not yet retired: craft grading is Python-centric — node/web
coverage is thinner than Python's.

### 4. Proper exams — the exam must be able to fail
**Done when:** an exam that cannot detect a wrong implementation is reported as such, and the
coder is told not to write one.
**Observable, three parts:**
- a delivered test that provably cannot fail is flagged → **LIVE** (`coder_test_qa`, #1170/#1195)
- the coder is instructed not to write one → **LIVE** (brief rule 8, 2026-07-30)
- an exam that survives a deliberately broken implementation is graded weak → **LIVE**
  (`oracle_mutation`, #1195 item 2). Its band was found INFLATING on 2026-08-07: budget-expired
  and machinery-missed mutants fell into neither `killed` nor `ran`, so the score and coverage
  band rose as the audit ran LESS. Fixed `69f59f2c` (#1231).

**Status: PARTIAL — the three checks above are LIVE as instruments, but `unexecuted_property`
(half the capability's proof set) cannot fire in production, and the first mutation measurement
is UNVOUCHED.**
`unexecuted_property`, half the proof set, still cannot fire: the dispatch path runs
`uv run … pytest -x -q` with no `--hypothesis-show-statistics`
(`agentic-setup/scripts/fleet-lib.ps1:3526`), no statistics artifact is produced (`:3508-3535`),
and neither production call site passes `-StatsPath` or `-RequireProperty`
(`new-agent-task.ps1:601`, `:713`; the omission is deliberate, commented at `:593-595`), so
`PropertyExecutionMeasured` — the DISCLOSURE field, set from `[bool]$StatsPath`
(`fleet-lib.ps1:1200`, defaulted false `:1080`) — is always false in production and
`property_execution_finding()` is unreachable there (defined `shared/fleet/coder_test_qa.py:659`,
sole in-module call `:1003`; citations re-derived 2026-08-07 — the prior `:995`/`:592` had
drifted). #1199 is
now UNBLOCKED — its own `blocked-by` (#1195 item 1) has landed — and simply not done. The gap
is at least DISCLOSED rather than printed as a zero (`fleet-lib.ps1:1080/1312/1334`), which is
honesty, not capability. #1201 (whole-tree attribution) is FIXED — `db7b2525`, `--since` scoping
with `SCOPE_UNRESOLVED` failing closed, verified on a real five-worktree night.

**The first measurement — b4 17/20 *adequate*, b2 15/20 **weak**, 5 survivors — was produced by
the PRE-#1231 scorer and must be treated as UNVOUCHED until re-derived.** Whether those runs
were budget-complete cannot be determined from the recorded figures.
*(Re-measured 2026-08-07.)*

**2026-08-08, #1350 — the strongest check this row owns has never once produced a result.**
The fail-to-pass baseline (run the exam against a tree where the product does not exist and
require it to FAIL) is *the* instrument for "an exam that cannot fail". Reading every banked
`oracle-qa.json` in `state/fleet-runs/`: **81 of 81 records carry `f2p_baseline: "not-run"`**,
across both ecosystems, since 2026-07-12. 67 of the 81 also report `findings_total: 0` while
neither execution probe ran. #1342 diagnosed a node-only early return and fixed it correctly,
but the Python rows are stamped `not-run` just as consistently, so the node skip was one of at
least two causes and closing it did not make the baseline start working. `BLARAI_ORACLE_QA` is
unset at every scope, so the kill-switch is not the cause. **The static half is real and does
catch vacuous oracles** — the escaped B9 oracle grades `verdict: refuse` on
`collectability`/`adequacy_floor` findings today — so this is not a claim that the QA does
nothing. It is the EXTENT of #1342's finding: every GREEN this project has banked rests on an
exam never shown able to fail, and the field saying so has read `not-run` since it was written.

### 5. Proper reviewers
**Done when:** work is not merged on the strength of an exam the candidate wrote for itself.
**Observable:** a green-gated task with a proof-grade exam defect has its review-skip withdrawn.
**Status: ARMED — the decision gate is proven with real inputs; the withdrawal event has never
been observed.** Verified 2026-07-30 against a real delivery's inputs: `hard=2`,
`Test-ShouldRunReview(green, green, hard=2) => True` — the decision FUNCTION exercised with real
data; a review-skip actually being WITHDRAWN inside a live dispatch has not yet been observed,
and that live event is the row's real observable. The clean-room second grader and the guest-VM
oracle predate this.

### 6. A local corpus
**Done when:** the planner works from real API documentation rather than recall, the coder can
look up an API it does not know without leaving the machine, code seeds are part of the same
grounding substrate (the operator's clause: "code seeds and/or the local corpus"), and research
is reachable at EVERY step that needs an answer — plan, build, fix, exam-author — not only the
two wired today. *(Seeds and every-step reach ratified 2026-08-07.)*
**Observable:** a plan cites names and semantics that exist, on a library the model does not know
well; and a coder lookup returns a real page rather than "dormant".

**Status: PLAN-TIME STOOD-DOWN (LA, 2026-07-30); BUILD-TIME ARMED + MUTE (#1320) — armed 2026-08-06, its instruction reverted the same evening, zero coder lookups ever.** This row read *"Blocked on the
operator: #746 docset approval"* until 2026-07-30 pm. That was wrong on both facts, and it was
steering sessions to wait for a decision already made. #746's design was **LA-APPROVED on
2026-07-05**, in his own words, naming the two research points and the deterministic-first
lookups; its one gated item was the docset DOWNLOAD, and the corpus has been **staged and
hash-verified since 2026-07-06** — 15 artifacts, 134.6 MB, index 13,803 pages, zero egress
(`models/docsets/MANIFEST.sha256.json`; `docs/DECISION_REGISTER.md:106`).

The two halves are separate rungs, blocked on different things, and neither is an approval:
- **Plan-time grounding** (`research_grounding = false`) went LIVE 2026-07-30 am and was STOOD
  DOWN the same evening at the LA's direction, because nobody had measured what the retrieval
  actually returned before arming it. Re-arming is gated on the #1204 relevance fix **and a fresh
  measurement on the operator's own goal shapes** — not on time passing. With the flag false the
  decompose prompt is byte-identical and `shared.research` is never imported.
- **Build/fix-time lookup** (#1206, `research_docs` in `configs/fleet-driver.json`) was **ARMED
  2026-08-06** at the LA's in-person direction, after sitting installed-but-unused since 07-24.
  Live-verified before and after against the real 13,803-page index (`collections.Counter` → exact
  hit, score 1.0), and `state/research-usage.jsonl` gained its first-ever `search_docs_cli` records.
  **Then measured again during a live run and found ARMED BUT UNUSED**: the arming ledger said
  `armed:true` on every candidate spawn while the usage ledger recorded zero coder lookups, because
  `search_docs` was named nowhere in the coder's brief. Fixed the same day (agentic `f92a4ef`).
  **Status is therefore ARMED + INSTRUCTED, still UNMEASURED for whether it helps** — that is a
  count in `research-usage.jsonl` on the next run and nothing else. Note the shape: *switched off*
  and *switched on and never mentioned* are indistinguishable in every artifact except that ledger,
  which itself could not tell a coder's lookup from a developer's probe until `2a4796a`.

  **CORRECTION, measured 2026-08-07 — "INSTRUCTED" is no longer true (#1320).** The 23-line
  section naming `search_docs` (`219d899`, 10:12) was **deleted the same day** by `609a925`
  (17:13, author `harness-sync`). The fix edited the *repo* copy of `configs/AGENTS.md`; the coder
  reads the *deployed* copy at `~/.config/opencode/AGENTS.md`, never updated (dated Jul 30);
  `sync-harness.ps1` syncs live→repo, so the sync faithfully captured the unfixed live file and
  reverted the commit. `grep -c search_docs ~/.config/opencode/AGENTS.md` → **0**, and 0 in both
  agentic-setup HEAD and the pinned battery tree. The 2026-08-06/07 overnight battery ran with
  `armed:true` on **every** spawn and the usage ledger gained **nothing**.
  **Real status as of 2026-08-08: ARMED + INSTRUCTED again — the revert was undone, live copy
  FIRST this time. Still zero coder lookups, so still short of the observable.** Re-measured
  2026-08-08 16:0x: `grep -c search_docs` returned **0** in the deployed brief, **0** in
  agentic-setup HEAD and **0** in the pinned battery tree — #1320's revert was still fully in
  force nine days on. Restored to `~/.config/opencode/AGENTS.md` **before** the repo, both
  verified byte-identical, so `sync-harness.ps1` (live→repo) cannot revert it a second time —
  that ordering is the fix, the text is secondary. Merged `01a528f`-line, agentic
  `fix/1320-restore-search-docs-instruction`. Tool proven live before claiming anything:
  `search_docs "URLSearchParams.getAll"` → EXACT 1.00 on both `[dom]` and `[node]`, offline,
  from the 13,803-page index. **The observable is a `search_docs_cli` record whose caller is a
  coder** — the ledger holds 1,989 records of which 3 are lookups, all developer probes.
  Arming, instructing and helping are three different things; this closes the second only.
  *(Prior state, retained: ARMED + MUTE. Zero coder lookups had ever occurred* (3 `search_docs_cli`
  records exist; all are developer probes — re-verified 2026-08-07 17:48: 1,989 ledger records,
  and a sweep of all 887 coder transcripts finds zero `search_docs` calls ever, while 8
  "Invalid Tool" listings prove the tool WAS offered to coders). #1206 was closed on a predicate
  the revert un-met.
  The fix survived seven hours and every artifact still reported success — the arming ledger, the
  ticket, and this row.

- **SECURITY, both halves (#1312, measured 2026-08-07):** the LIVE lookup
  (`agentic-setup/tools/search_docs.py:287-312`) does **not** datamark; the datamarking
  implementation (`BlarAI/tools/search_docs.py:103-113`, 63 gate tests) is wired to nothing — the
  JS wrapper default-resolves to agentic-setup's copy and `BLARAI_RESEARCH_TOOL` is set nowhere,
  while BlarAI's file's own docstring claims the wrapper shells out to it (that false prose is
  ticketed). The plan-time half does not datamark either: `shared/fleet/decompose.py:1248`
  prefixes the block `shared/research/plan_grounding.py` returns ABOVE the planner's
  instructions, unlabeled. #746 requires `UNTRUSTED_EXTERNAL` provenance on retrieved
  docs; **neither live path meets it**, and that is mitigated today only by the accident that one
  half is off and the other is mute. The plan-time datamark must land BEFORE `research_grounding`
  is re-armed.

- **The corpus itself is the right substrate and is not the problem.** Index measured directly
  2026-08-07 (`models/docsets/index/docset_index.sqlite3`, 102.9 MB): 13,803 pages / 26,329
  symbols, of which **web sources are 10,475 pages — 76%** (dom 7,766, javascript 1,291, css
  1,101, html 252, node 65). This is not a Python-only corpus.
  **But note:** every plan-time disproof was run on PYTHON goals. #1204 c.2736 asserts web goals
  clear the floor unaided, which means plan-time grounding would actually PRODUCE blocks on
  website goals — and **nobody has measured whether those blocks are right**. The website case is
  the least validated corner of the half that is already switched off.

**The lesson this row now carries:** an approval recorded in one place and a status line written in
another drift apart, and the status line is what gets read. A blocker naming a person should name
the artifact that proves it — a ticket, a date, a decision row — or it will outlive the block.

### 7. It is measurable — every number means what it says
**Done when:** no instrument in the pipeline can report a pass it did not measure.
**Observable:** every grader distinguishes "did not run" from "ran and found nothing".
**Status: PARTIAL — the instrument-honesty fixes are LIVE as of 2026-07-30 and that is where the
day was spent; two verification predicates outstanding (#1200, #1203).** Fixed: the battery now executes
merged code (#1181a); `assert True` can no longer mint GREEN-VERIFIED (#1184); an unmeasured
security scan cannot render clean (#1182); the advisory ruff lint runs at all for the first time
and says so when it cannot (#1189). The three holes this row listed as open have all LANDED IN
CODE (board re-measured 2026-08-07 evening): #1198 CLOSED (fixed 2026-07-30, agentic `5d1d5db`,
ticket unclosed for a week — the same shape as capability 1's week of false PARTIAL); #1200 fix
merged (`24878d88`), ticket open only pending a real @slow-tier run of
`test_oracle_qa_uv_parity.py` (the standing gate deselects it); #1203 fix merged (`b5d881a4`),
ticket open only pending a pinned-tree battery night (#1301) plus its owed disposition record.

**2026-08-08 — a PRODUCTION demonstration of this row's own observable** (*"every grader
distinguishes 'did not run' from 'ran and found nothing'"*). `_rule_harness_budget` filed every
HARNESS fault as budget exhaustion on the attribution alone, reading neither elapsed nor
budget — 49%, 102% and 0.9% of budget all wore the one label. Fixed (#1324, `0550dcb6`) and
proven the same day on a real run: scorecard `20260808-160538-bd` reads `HARNESS-ENVIRONMENT`
with fingerprint `elapsed 295s of 28800s (1%) - NOT budget exhaustion`, and the battery
summary's taxonomy counter moved `HARNESS-BUDGET Δ-1 / HARNESS-ENVIRONMENT Δ+1`. The label can
now be CHECKED rather than believed, because the numbers travel with it. Honest limit: the run
this proves it on still FAILED, for a cause root-caused separately (#1341) — an honest
instrument is not a working system.

**2026-08-08, second instance the same day — the highest-authority grader in the system was
the one violating this row.** `oracle-qa.json` reported `validated: true, findings_total: 0`
with `f2p_vacuous: 0` sitting beside `f2p_baseline: "not-run"` and `collectability:
"skipped"` — a count of zero from a check that never ran, against an oracle that was
three-fifths vacuous. Downstream, `already_satisfied` read that pass and deleted two tasks
from the plan. Fixed (#1342 item 2, `83633ce0`): `CLASS_STAGE` maps every finding class to
the stage that produces it, and `findings_conclusive` is false whenever any producing stage
did not run — a total from unrun checks is a floor, not a count. `not_measured` names what
did not happen in sentences a person can read, and the operator's own review page now shows
it (agentic `9413f7f`), so *"this site was graded by an exam nobody checked"* reaches the
one reader whose verdict is this document's ground truth. Toggle-proved. **What is still
open on this row: item 5 — requirement coverage (`oracle_coverage: "unknown"`) does not gate
GREEN, so a delivery can still be certified against an exam that covers none of what was
asked.**

---

### 8. It finishes a product across MANY runs, not one

A complex multi-page site does not fit in one dispatch and never will. Today the system has no way
to express that: `parked` is a terminal task state, no resume path exists (#1277), the planner
re-decomposes the whole goal from text on every run with no memory of what a prior run built or
why, and there is no measure of *how much of the product is finished*.

**DONE means:** a run that does not finish parks honestly with its work recoverable; a later run
picks that work up, knows what was already built and decided, and continues rather than restarting;
and at any moment the operator can be told how much of the product exists. **Proper error handling
is part of this row (ratified 2026-08-07):** a run that fails for ANY reason — including
infrastructure failure — parks honestly and visibly; no failure path may end in a silent pass or a
vanished run. **A goal with no
progress measure has no finish line, and "iterate until complete" cannot terminate.** Status:
UNKNOWN — the resume path, run-to-run memory and progress measure do not exist (#1277's own
record: "It does not create a resume path. None exists"). **DEMONSTRATED LIVE 2026-08-08** — no longer an argument from source reading. The LA's own
9-task dispatch (`20260808-104536-bd`) delivered and merged 3 tasks, then `contact-page`
parked. `coord_redispatch` staged a proposal at 14:02:35; **nothing consumed it**, exactly as
#1321 records (`coord_redispatch.py:481-485`, *"THE SEAM, not the hook: nothing calls this
today"*). `state/fleet-swap/task-queue.json` still holds the parked task — the intent
survived and there is no path that reads it. Re-dispatching would rebuild the three finished
pages from zero, and the operator cannot be told what fraction exists without reading
`done-reasons.txt` against `dispatches.txt` by hand. All five of this row's gaps, observed in
one run. Tracked: #1277 (the recovery handle,
fixed and live-verified 2026-08-06), #1279 (the 8-task cap that bounds how complex a product can
even be described — `DEFAULT_MAX_TASKS=8` at `decompose.py:87`, silent truncation `:1101`, B9
authored at 9 units and cut to 8), #1285 (parked work is preserved but unfindable from its own
run record).

### 9. He can SEE and USE the result

Every capability above is about *building*. None of them puts the product in front of him. A
finished website sitting in a sandbox repo he never opens is not a website, and a site he cannot
click through is one he cannot judge.

**DONE means:** he can view and use the built site without knowing git, and the way he does that
survives a reboot. **And it includes his own review loop** — *"the nav should be on the left, the
photos are too big"* — fed back as a next iteration. The system has coordinator reviews (machine
reviewing machine) and an eyeball tier that hands him a verdict; it has no path for his judgment to
become the next change. For a website, that judgment is most of the product.
**Status: PARTIAL as of 2026-08-08 — the SEEING half is done and was exercised for real; the
FEEDING-BACK half is not.** He opened a built site on 2026-08-08 for the first time and
recorded a verdict (`state/operator-reviews/20260808-185500-battery-b9-pottery-site.md`,
#1345). The loop that carried it is live: `Review Website.cmd` finds every build including
the archived ones that would otherwise vanish by morning, serves it, refuses to present
anything it cannot prove is the right build, shows the run's claims leading with what was
NOT built, hands him his own goal clause by clause, reports which links lead nowhere, and
saves his words against the run id (agentic `724b321`). A website battery run now fires this
automatically instead of relying on him remembering (`75e8e24f`). What remains is (b): his
judgment reaching the next run, ordered AFTER resume (#1321) because feeding back "make the
nav bigger" is worthless if the next run rebuilds the site from scratch. Tracked at #1280.

### 10. The product carries its own content

Generated images, voice, narration and animation are on the roadmap. **Words are not.** A pottery
site is mostly text — the studio description, the piece blurbs, the contact copy — and nothing in
the intake, the plan, or the exams asks for any of it, so the coder invents placeholder prose or
leaves lorem ipsum and every gate passes.

**DONE means:** written content is planned, authored and graded like any other deliverable, and the
operator's own words are used where he supplied them. Status: UNKNOWN — tracked at #1281.

---

## Capabilities 11-21 — RATIFIED 2026-08-07

**Provenance: 11-16 proposed by a Claude session 2026-08-07 am, at the LA's direct question
("are there any capabilities that are obviously missing... especially involving QA, review, and
testing?"); 17-21, the sharpenings to 11/14/15, the status legend, the goal-coverage map and the
row 6/8 amendments added the same evening by the DoD review session (#1323). RATIFIED by the LA
the same evening — the full proposed set, selection delegated to the review session's judgment in
his words: "I approve of all the proposed ones that you think are good." Recorded on #1325 and in
docs/DECISION_REGISTER.md; statuses document-wide follow the ratified legend, enforced by
`tests/security/test_coder_dod_grammar.py`.**

Capabilities 1-10 ask whether each instrument is honest. **Not one of them asks whether the
instruments are RIGHT**, and every gap below was found by hand rather than by anything in the
pipeline — which is itself the argument for adding them.

### 11. A capability is not LIVE until its own observable has been executed

Capability 2 read `LIVE` for a week on the strength of nine `true` flags while its observable — a
dispatch that *completes* — had never once happened. Capability 4's status cites a measurement
(`b4 17/20`) produced by a scorer later found to be inflating. **A flag is a configuration; an
observable is an event.** DONE means: no row here claims LIVE until the stated observable has
been run end to end at least once, with the run cited — and re-executed when the instrument that
grades it changes: an observable executed once, on an instrument since repaired, is `UNVOUCHED`,
not `LIVE` (capability 4's exact case). Everything else is `ARMED`.
**Status: PARTIAL — enforced for THIS document by the grammar gate; as a pipeline-wide
discipline, UNKNOWN.**

### 12. The gates' false-negative rate is measured — escaped defects are counted

Capability 3 records *144 deliveries, 141 band A, 5 findings*. That is either excellent work or a
weak grader, and **nothing in this document can distinguish those two.** Every capability above
measures whether an instrument ran honestly; none measures whether it was correct. DONE means:
defects found AFTER a delivery was banded are counted against the gate that missed them, and the
false-negative rate is a published number. Without it, a rising band average is not evidence of a
rising product. The operator's own eyeball verdict (capability 9) is the natural ground truth,
which is why 9 and 12 are one loop rather than two features.
**Status: PARTIAL as of 2026-08-08 (#1345) — the column has its first row, and it is not
encouraging. PARTIAL, not LIVE: this row's observable is a PUBLISHED RATE, and one reviewed
delivery is a data point.** One delivery reviewed (B9, run `20260807-195617-bd`, banded GREEN). Seven
observations from the operator; **three were real defects and none had been caught by any
gate**: the same image reused across products, product descriptions not matching the image
shown, and a "View Details" button on every gallery item leading to a JSON error. All three
verified on disk. The third is #1342's amputation seen from outside — the page was deleted
from the plan by an oracle that could not fail — and he found it in under a minute by
clicking a link, while the instrumentation took hours. **One delivery, three escaped
defects, four gates.** That is a rate of one reviewed delivery, so it is a data point and
not yet a rate; what it retires is the claim that the number is unknowable. One of the three
(the image mismatch) had already self-corrected by the following night's build, which is
only known because it was re-measured rather than assumed to carry.

### 13. The graders are themselves graded

#1231 (2026-08-07): `oracle_mutation`'s score and coverage band ROSE as the audit ran LESS,
because budget-expired and machinery-missed mutants fell out of the denominator. It measured
honestly and reported a partial result as a complete one — which capability 7's framing ("no
instrument can report a pass it did not measure") does not catch. It was found by reading the
file. DONE means: a grader's own arithmetic is verified by something that is not that grader,
and a partial result can never present as a whole one.
**Status: PARTIAL — the #1231 reconciliation invariants lock `oracle_mutation`; every other
grader is UNKNOWN.**

**Second instance, 2026-08-08 (#1324):** the failure classifier presented an unmeasured
conclusion as a measured one — asserting budget exhaustion without reading the budget. Same
class as #1231, different grader, and again found by reading the file rather than by anything
in the pipeline. Its arithmetic is now verified by data it does not own (the card's
`run_budget_s`, stamped onto the scorecard) rather than by its own attribution field, and the
fingerprint publishes the inputs so a reader can re-derive the verdict. Two graders locked,
the rest still UNKNOWN — and two independent instances make this a class, not a coincidence.

### 14. Every gate is proven to fail — the standard we hold the coder to

Capability 4 rightly demands the coder's exams be able to fail. **We apply no such rule to our
own.** In one session on 2026-08-07: two new locks passed for the wrong reason and only mutation
caught them; a pre-existing test asserted `mutation_audit == "run"` for a run that reached NO
mutants (the defect written down as expected behaviour); and a live code path had no test at all,
so deleting its logic left the suite green. `CLAUDE.md` security_by_design principle 12 already
requires every control to ship with proof it fails when disengaged — it is not a coder capability
and it is not enforced. DONE means: a lock that has never been seen to fail is not a lock, and
the proof has a CADENCE — a control proven to fail once can still be edited into silence later
(the overhaul programme's #1142 case: a README-marker lint neutralised by a seed-text change,
"the band-A reading recorded a detector that stopped detecting"); periodic planted-defect CANARY
deliveries through the REAL pipeline re-prove the whole gate chain, which a one-time proof
cannot.
**Status: PARTIAL as of 2026-08-09 — the RECORD exists and is enforced; the CADENCE does not.
Re-measured, because this row read UNKNOWN while the mechanism it asks for was already live.**

`shared/instrument_registry.py` carries **13 instruments**, and for each one the proven-to-fail
pair is a REQUIRED, RESOLVED field — not a convention. It goes further than principle 12 asks,
naming THREE cases rather than two: a `toggle_test` (a renderer refuses to report clean over an
unmeasured result), a `seam_test` (the REAL entrypoint, driven for real, RETURNS unmeasured —
it may not construct the result type, because that is where mocks lie), and a `quiet_test` (the
instrument does NOT convict a healthy input, because a control that fires on correct
configurations gets muted). `test_instrument_registry` fails if any named test is renamed or
deleted, and `unclaimed_reads` surfaces BY NAME any unregistered grader wired into a registered
renderer — so a new gate's choice is "register it or argue why it is not an instrument", never
"nobody noticed". 143 tests, in `tests/security/`, inside the standing gate. Verified passing
2026-08-09.

So *"no gate has a systematic proven-to-fail record"* was false when written or has been false
since; either way this row was sending readers to build something that exists. The same failure
mode as an index line understating its own repo — and worth more than the correction, because a
DoD row that undersells the system is as misleading as one that oversells it.

**What is genuinely still missing, and it is the harder half.** The row asks for a CADENCE: *"a
control proven to fail once can still be edited into silence later"* (#1142 — a README-marker
lint neutralised by a seed-text change, so *"the band-A reading recorded a detector that stopped
detecting"*). The registry proves each control could fail **at the moment its test was
written**. Nothing re-proves the chain since. Periodic planted-defect CANARY deliveries through
the REAL pipeline are unbuilt, and no instrument shipped 2026-08-08 (`link_lint`,
`image_placement`) is registered yet — both carry toggle-proofs, neither is under the registry's
teeth, and the registry's contract assumes a result type where those emit a dict.

### 15. The built product is EXERCISED, not just inspected

The LA asked for *"proper automated testing, including live visual and functional tests"*
(2026-08-06) and **no row above expresses it.** Capability 3 grades security by scanning;
capability 4 grades the exams. Nothing opens the thing. For a website that means: links resolve,
forms submit, the console is free of errors, the layout survives a phone width, and the page is
navigable by keyboard and screen reader. A site can pass every gate in this document and be
broken the moment it is opened. This capability names its isolation boundary at design time:
exercising a built site means EXECUTING untrusted code — the coder's own output — and where that
runs (guest VM, sandboxed browser context) is a security_by_design principle-9 decision made
before the first line, not after.
**Status: PARTIAL as of 2026-08-08 (#1345, `32a9ed1f`) — the LINKS half is measured. Every
`href`/`src` in a delivered site is now resolved against the root a server actually mounts
(`shared/fleet/link_lint.py`), wired into the per-build web floor and banked as
`link-lint.json`. It found, on the real delivered tree, the broken "View Details" link the
operator had found by hand — in both the `.js` and the inline-`<script>` copy. It is
ADVISORY, not blocking: a regression lock proves a broken site and a clean site produce
identical verdicts, because a new way for a build to fail is his ceremony, not a wiring
decision. What is still UNKNOWN, and named rather than implied: forms are not submitted, the
console is read only by the existing CDP smoke tier, no phone-width layout check exists, and
nothing tests keyboard or screen-reader navigation. A link check is the cheapest slice of
this row, not the row.**

### 16. Every recorded measurement is reproducible

#1318 (2026-08-07): three recorded probes named image subjects that were never committed, so
results still being cited — including gate B evidence for the 35B consolidation decision — could
not be re-derived on any machine. Honest numbers, unverifiable. DONE means: a recorded result can
be re-run from the repository alone. Structural control shipped
(`tests/security/test_measurement_subjects.py`); the capability is stated here because the class
is wider than the one fix.
**Status: PARTIAL — the control is LIVE as of 2026-08-07 for the known class (#1318); the wider
class is UNKNOWN.**

### 17. The exam covers what was ASKED — requirement coverage

The overhaul programme (2026-07-30) called this **"the single largest gap against 'proper exams
and reviewers'"**: every GREEN to date has classified `GREEN-UNVERIFIED` with
`oracle_coverage=unknown` — a GREEN means *the oracle passed*, not *the deliverable does what was
asked*. Capability 4 measures whether the exam CAN FAIL (mutation adequacy); nothing in rows 1-16
measures whether it covers the requirements — a different axis, and the instrument for it has
since shipped (`green_quality/traceability.py`, the `GREEN-VERIFIED` classification, the
dashboard coverage card) while no capability row claims it, leaving #967/#1015 serving no
numbered capability. DONE means: every delivery carries a requirements→assertions coverage
figure, an `UNDECIDABLE` criterion blocks `GREEN-VERIFIED`, and the first `GREEN-VERIFIED` ever
stamped on a real run is a cited event.
**Status: ARMED — the instrument is shipped and reachable; no run has ever stamped
`GREEN-VERIFIED` (#967, #1015).**

### 18. The product's media content is generated, placed and graded

The operator's stated goal includes *"proper image, voice, narration, and animation generation as
content for websites."* Capability 10 covers WORDS and waves media to "the roadmap" with no
observable — a named goal clause with no row. The generators exist elsewhere in BlarAI (UC-010
image generation, voice). DONE means: the media a site needs is planned at intake, produced
through the pipeline (or its absence recorded as a decision), and graded like any other
deliverable — a pottery site with an empty gallery or placeholder images is reported, not banded
clean.
**Status: UNKNOWN — the generators exist elsewhere (UC-010, voice); the pipeline path does not.**

### 19. Candidate count scales with difficulty

*"Proper multiple candidates based on how difficult"* (LA, 2026-08-06) appears nowhere in rows
1-16. DONE means: the dispatcher chooses HOW MANY independent candidates to build from the
declared or measured difficulty of the task, the choice and its reason are recorded on the run,
and hard tasks demonstrably get more attempts than trivial ones.
**Status: PARTIAL as of 2026-08-09 — the MECHANISM is live and predates this row; the
DEMONSTRATION is not. Re-measured, because UNKNOWN was understating the repo.**

`agentic-setup/scripts/fleet-lib.ps1::Resolve-PassBudget` already maps a coarse difficulty
label onto the build-pass budget, which IS the best-of-N candidate count:

```
simple   -> 2 build / 1 review
moderate -> 3 build / 2 review
complex  -> 8 build / 3 review
```

Its own comment records the provenance: *"complex BUILD raised 5→8 on 2026-06-27, LA decision:
more total best-of-N shots at hard tasks … Sampling is near-free locally; best-of-N coverage is
the weak-model bottleneck."* A staged desktop-GUI surface floors BUILD at 5 regardless of label.
An absent or unrecognised label keeps the caller's defaults, so the signal is backward
compatible. `Add-ComplexityHint` additionally tells the coder the assessment *before pass 1*, as
a calibration signal that never prescribes an implementation.

The label is a SIGNAL from the upstream 14B, deliberately not a pass count — *"it is NOT a
coder, so it sends a signal, never a pass count. The SYSTEM maps that label"* — which is the
right split and worth preserving.

**Recorded, partially.** A run's own JSON carries `"complexity": "moderate"` (verified on
`20260807-195617-bd`), so the REASON is on the run. The resolved budget — the choice itself —
is not: no run artifact records "8 build passes because complex". Half of this row's recording
clause is met.

**What is genuinely missing: the demonstration.** *"Hard tasks demonstrably get more attempts
than trivial ones"* has never been measured. Nothing compares candidate counts across
difficulty bands, and the sampler's own summary line only prints when a task's best-of-N loop
actually drew more than one (`swap_driver.py:704`), so absence of the line is ambiguous between
"drew one" and "did not report". Until a run banks the resolved budget beside the label, the
correlation cannot be computed from banked state at all.

### 20. Decomposition is graded, not just performed

*"Proper decomposition"* has no row; its only trace today is a defect (#1279:
`DEFAULT_MAX_TASKS=8`, silent truncation — B9 was authored at 9 units and cut to 8 without
saying so). DONE means: the plan's task graph is sized by the goal rather than capped by a
constant, any truncation is LOUD, and a decomposition that produced an unbuildable or overlapping
task set is counted against the planner, not against the coder who inherited it.
**Status: UNKNOWN — #1279 is the only measured trace.**

### 21. Verdicts are stable — the "reliable" in the operator's own words

Promoted from this section's former "lower confidence" footnote. A grader that returns different
bands for the same delivery across runs makes every number in this document meaningless, and
nothing measures flake. DONE means: re-grading a fixed delivery N times yields the same band, the
flake rate is a published number, and a grader whose verdict flips is treated as a broken
instrument. (Capability 13's sibling: 13 checks the arithmetic, this checks the repeatability.)
**Status: UNKNOWN — flake has never been measured; not claimed broken.**

### Status legend — ratified with capability 11

`LIVE` (observable executed end to end at least once, run cited, on the current instrument
version) · `ARMED` (configured and reachable; observable never executed) · `PARTIAL` (a named
subset executed) · `UNKNOWN` (unmeasured — legitimate and preferred over optimism) · `STOOD-DOWN`
(deliberately off; by whom and why) · modifier `UNVOUCHED` (the measurement exists but its
instrument was later found defective; re-derive before citing). One vocabulary, so "FLAGS LIVE",
"MOSTLY LIVE" and "armed and instructed" stop meaning whatever the row's author felt. Enforced
since ratification by `tests/security/test_coder_dod_grammar.py`, which parses every row against
this grammar and fails any `LIVE` lacking a dated citation — before which NOTHING machine-checked
this file (verified 2026-08-07: no size budget, no vocabulary scan, no freshness check).

### Goal-coverage map (ratified) — every clause of the operator's words, mapped or exposed

| Operator's clause (2026-08-06 + 2026-07-30) | Row |
|---|---|
| complex multi-page website | 8 (+#1279) |
| advanced interview / advanced intake | 2 |
| proper user-asset incorporation | 2 (sub-item; M2 unbuilt) |
| code seeds and/or local corpus | 6 — **seeds: amendment below** |
| research answers at the various steps | 6 (two steps of several) |
| image, voice, narration, animation as content | **row 18** |
| proper test authoring (+ reviews) | 4, 5 |
| proper test execution | 4 (known hole), 15 |
| multiple candidates by difficulty | **row 19** |
| proper decomposition | **row 20** |
| proper error handling | **amendment to 8 below** |
| coordinator reviews | 5, 9 |
| iterations until finished / parking / inspection+pickup | 8 |
| live visual and functional tests | 15 |
| working / secure python + websites | 1, 3 |
| **reliable**, robust | **row 21** |
| proper exams and reviewers | 4, 5, **17** |

### Amendments to rows 6 and 8 — ratified 2026-08-07 and applied in place

Row 6 now names code seeds and research-at-every-step; row 8 now names proper error handling.
The amended text lives in the rows themselves, above.

---

## The single acceptance test

Everything above collapses to one thing the operator can do himself:

> **He runs an advanced dispatch on a real goal. The interview asks in plain language. The plan
> reflects what he said. The coder builds it. The exams could have failed and did not. Nothing in
> the report claims a measurement that was not taken. He reads the result and it is true.**

**Executed: NEVER** (as of 2026-08-07 — no operator-driven advanced dispatch has ever completed;
capability 2's evidence).

Until that has happened end to end, on a real goal, the coder is not done — regardless of how many
tickets are closed.

## The SECOND acceptance test — the one the website goal needs

The test above is a **one-dispatch** test, and it always was. It cannot express the operator's
stated priority (2026-08-06):

> *"my current priority is for it to be able to engineer relatively complex website with multiple
> pages … proper multiple iterations until a working finished product, proper parking of
> non-working product, proper inspection of parked product and picked up to iterate until
> completion … We don't need to one-shot websites any more."*

So it needs a second, and the first does not satisfy it no matter how many times it passes:

> **He asks for a real multi-page site. It does not finish in one run, and that is expected and
> fine. It parks honestly with the work kept. He looks at what exists, says what is wrong in his
> own words, and dispatches again. The next run continues rather than restarting. Across however
> many runs it takes, the site converges — and at every point he can see how much of it is built.
> At the end he opens it in a browser, uses it, and it is the site he asked for.**

**Executed: NEVER** (as of 2026-08-07 — no multi-run product has been attempted; the resume path
does not exist, #1277).

**Nothing in the seven capabilities is sufficient for this**, and a system that scores DONE on all
seven can still fail it completely — which is precisely why it is written down separately rather
than folded into the first.

---

## What is NOT in scope here

Model choice and the 30B/14B question (#742, #923, #930); battery cadence and campaign design;
the coder's raw capability ceiling. This document is about whether the system around the coder is
honest and complete, not about how clever the model is.

---

## How to use this

- A ticket that does not advance a numbered capability above should say which one it serves, or be
  questioned.
- An agent brief should name the capability it is working toward, not just the task.
- A status here is only ever changed by a MEASUREMENT, with the measurement cited. `UNKNOWN` is a
  legitimate and preferred value over an optimistic one.
- Statuses speak the ratified legend — LIVE / ARMED / PARTIAL / UNKNOWN / STOOD-DOWN, modifier
  UNVOUCHED — and `tests/security/test_coder_dod_grammar.py` fails the gate when a status line
  leaves the vocabulary or a LIVE claim lacks a dated citation.
- Maintenance rules, ratified 2026-08-07 with the rest (#1325, disposition §5 items 3-6):
  statuses are RE-MEASURED at named events — the monthly retrospective, and before any go-live a
  row bears on — never on inspiration; a status cites its instrument AND its run artifact
  (start→finish, the test-governance stamp lesson); rows keep DONE-means + observable + current
  status + one lesson line, history lives on tickets, and corrections stay visible until
  re-measured; the goal-coverage map folds in each new operator goal statement when he makes one.
