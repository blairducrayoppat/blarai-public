---
title: Standing-gate baseline history (rotated)
status: archive
area: testing
---

# Standing-gate baseline history

Rotated out of `docs/TEST_GOVERNANCE.md` §1 on **2026-08-08**, when that file breached its
40,000-byte hot budget. Nothing here is deleted — this is the per-merge measurement
archaeology `CLAUDE.md` names as deliberately excluded from the hot surfaces, kept in full
because it carries corrections that must not be scrubbed (notably the **TIMESTAMP RETRACTION**
of the 10515 stamp, where a clock reading was narrated rather than measured).

§1 keeps the live baseline plus its two most recent confirmations. Everything older is here,
newest first, verbatim.

---

> *(superseded branch stamp — **MEASURED** 2026-08-07, **started 19:33:49, finished 19:40:00**
local, `docs/dod-ratification-20260807` @ `5dcce590`, **368.26 s**, **10537** = 10526 + the 11
grammar tests, taken before #1327/#1324 landed. That run OVERLAPPED the 10547 run on the
primary checkout (19:28:49→19:35:32) by ~103 s — two full gates concurrent on one box, against
the serialize rule; both were clean, and the overlap is named because this section carries
conditions, not luck.)*
>
*(prior — **MEASURED** 2026-08-07, **started 19:46:45, finished 19:52:17** local, branch
`fix/1324-per-run-session-id` @ `9ab30124`, **326.06 s** — primary checkout, models present,
no battery live. **+5 over 10547**, all of it #1324's
`tests/security/test_battery_session_isolation.py` — the locks proving a battery run cannot
inherit another run's pending dispatch. Deselected unchanged at 133.*
>
*(prior — **MEASURED** 2026-08-07, **started 19:28:49, finished 19:35:32** local, branch
`feat/1327-morning-validation-exercise` @ `4f0b0813`, **396.52 s** — primary checkout, models
present, no dispatch. **+21 over 10526**, all of it #1327's
`tests/security/test_validation_exercises.py`. Deselected unchanged at 133.*
>
***A FOUR-SKIP RUN PRECEDED THIS ONE AND WAS NOT WAVED THROUGH.*** *At 19:16:50→19:24:01 the
same selection returned **10543 passed / 4 skipped**. The cause was environmental and is the
documented live-app delta: a B9 battery run held the AO on `:5001` for the whole of that run.
Re-measured on the settled box with no battery live, the same selection returns 0 skipped and
the counts reconcile exactly (10526 + 21 = 10547). Recorded rather than dropped, because "the
skips were probably environmental" is an assumption and this section only carries measurements
— and because a gate run overlapping a live battery is a condition worth recognising next time.*
>
*(prior — **RE-MEASURED on merged `main`** @ `69f59f2c`, 2026-08-07, **started 15:49:45, finished
15:55:34** local, **342.42 s** — primary checkout, models present, AO stopped, no dispatch.
Identical to the branch figure below, which is what a clean merge should look like and is not
assumed: the merge itself can break what both parents passed.*
>
*(branch — **MEASURED** 2026-08-07, **started 15:42:38, finished 15:48:23** local, branch
`fix/1231-budget-honesty-on-main` @ `1e6aa156`, **338.09 s** — primary checkout, models present,
AO stopped, no dispatch. **+11 over 10515**, all of it #1231's budget-honesty locks in
`shared/tests/test_oracle_mutation.py`: the invariant that a tighter budget cannot raise the
coverage band; `planned = ran + not_run + unreachable` reconciliation; the `no-verdict` rows and
the refusal to stamp `run` on an audit that reached only some of its mutants; the
`unknown`-not-`weak` floor when nothing ran; the unit statement of the band rule; and both budget
break sites, the second of which no test had ever reached. Deselected unchanged at 133.*
>
*(the intermediate 10521 at 15:32:15 was real and superseded within the same arc, when an
independent review found the same inflation surviving on the machinery-miss path.)*
>
***TIMESTAMP RETRACTION — the 10515 stamp below said 15:25 and that was NARRATED, not measured.***
*The run actually started **15:03:24** and finished **15:14:05** (task-output file creation and
mtime), and 15:25 also postdates `c27c7b95` at 15:14:49 — the commit that recorded it. A finish
cannot postdate the commit citing it, which is the same impossibility this section convicted twice
on 2026-08-06. The COUNT (10515) was measured and stands; only the clock reading was invented.
Corrected in the block below. Times here are now written as start AND finish, read from the
runner's own artifacts, because a single stamp gives nothing to check against.*
>
*(prior — **MEASURED** 2026-08-07, **started 15:03:24, finished 15:14:05** local, branch
`fix/1318-measurement-subjects` @ `cf05699b`,
**634.07 s** — primary checkout, models present, AO stopped, no dispatch. The wall time is high
for this suite (345–376 s is typical); the box was running a review agent concurrently. Counts are
unaffected, but do not read 634 s as a substrate regression. **+9 over 10506**, all of it #1318's
`tests/security/test_measurement_subjects.py` — the lock that refuses a committed script naming a
repo media file that is not tracked, with its toggle proof, its allowlist-scope proof, a guard
against the scanner going vacuously blind, and three locks on resolution idioms an independent
review found it could not see. Deselected unchanged at 133.*
>
*(prior — **MEASURED** 2026-08-07 **10:12** local, merged `main` @ `fa1d66d3`, **345.43 s** — primary
checkout, models present, **AO stopped**, no dispatch. **+7 over 10499**, all of it
`fa1d66d3` #1313's `tests/security/test_swap_floor_enforced.py` — the behavioural lock on the
coder swap floor (refuses below it, admits above it, and fails when the gate is moved).
Deselected unchanged at 133; the suite carries no marker. Pen handed over by the parallel
session at 10395 and re-read from this file at edit time, not from the handoff figure — it had
moved twice more (10458, 10499) in the interim.*
>
*(prior — **MEASURED** 2026-08-07 **09:25** local, merged `main` @ `b5d881a4`, **345.40 s** — primary
checkout, models present, **AO stopped**, no dispatch. **+41 over 10458** across two merges:
`a98227a7` #763 job-oracle-to-coder **+7**, `b5d881a4` #1181a scripts pin **+34**. Deselected
unchanged at 133.*
>
*(prior — **MEASURED** 2026-08-07 **08:49** local, merged `main` @ `dbbbffb8`, **324.61 s** — primary
checkout, models present, **AO stopped**, no dispatch. The **+63 over 10395** is #746's
BlarAI-side `search_docs` CLI: 62 new tests across an integration suite and a security-tier
controls suite, plus one. Deselected unchanged at 133 — the new suites carry no marker, so
they are all in the standing selection.*
>
*(prior — **MEASURED** 2026-08-07 **08:40** local, merged `main` @ `7207cf45`, **318.56 s** — primary
checkout, models present, **AO stopped**, no dispatch.*
>
***THREE MERGES ACCUMULATED BEFORE THIS BUMP, and the addends reconcile exactly.*** *A second
session on this box was handed the baseline pen for a change of its own, so I merged without
bumping rather than edit a surface someone else was about to. That debt is cleared here in one
motion; each step below was separately measured on merged `main`, not derived:*
>
| merge | measured | delta |
|---|---|---|
| `62675d13` #967 submodule-vs-invented-contract | 10353 | +4 |
| `24878d88` #1200 uv interpreter parity | 10393 | +40, **deselected 130 → 133** |
| `7207cf45` #774 procspawn migration | 10395 | +2 |
| | | **10349 → 10395** |
>
*The deselect move belongs to #1200: its observable predicate lives in two `@slow` tests that
drive real `uv run`, so the standing gate never executes them and its closure must cite a
`@slow` run instead. Both numbers changed and both are accounted for.*
>
*(prior — **MEASURED** 2026-08-07 **07:59** local, merged `main` @ `cfa1c970`, **375.33 s** — primary
checkout, models present, **AO stopped**, no dispatch. **+30 over 10319** is #1195's L4-KILLS
rung and its locks, plus the guard added at merge for rows that never ran.*
>
***DESELECTED MOVED, 129 → 130, and that is the number to check.*** *#1195 adds one `@slow`
seam test (`test_real_runner_attribution_reaches_the_l4_rung`, ~136 s, needs `uv`) which runs
at its own tier. A deselect count that moves without anyone noticing is how a test quietly
leaves the standing selection — so it is stated here rather than left to be rediscovered. Both
numbers changed on this merge and both are accounted for.*
>
*(prior — **MEASURED** 2026-08-07 **07:40** local, merged `main` @ `368f78e7`, **319.52 s** — primary
checkout, models present, **AO stopped**, no dispatch. The **+3 over 10316** is the regression
lock for the red gate this merge fixed.*
>
***THE GATE WENT RED THIS MORNING, AND NOT BECAUSE OF A CODE CHANGE.*** *The 23:00 B4 run
parked before the coder committed anything, leaving an archive of two commits — both from the
harness (`init battery sandbox`, and #740's `seed protected job-level acceptance oracle`).
`test_seed_divergence_returns_a_determinate_answer_on_the_real_deliveries` selected the newest
archive holding "a delivery", and its discriminator asked **`> 1 commit`** — a rule written
when seeding made ONE commit. #740 added a second and nobody revisited it, so a seed-only tree
read as a delivery. The lint then honestly reported `unknown` for a `pyproject.toml` that was
never there, and the assertion was right to reject it.*
>
*The fix asserts the **precondition the measurement needs** (every seed file present to compare
against) rather than counting commits, because a count is a fact about the harness's commit
habits and rots when they change. **This is the second time this test went red for this class**
— its own docstring records 2026-07-30 — and the first fix pinned a count, so the class
survived. Measured across four archived B4 nights, the new rule separates cleanly and agrees
with the lint's own outcome every time.*
>
*(prior — **MEASURED** 2026-08-06 **21:47** local, merged `main` @ `c5edd793`, **328.01 s** — primary
checkout, models present, **AO stopped**, no dispatch. The **+3 over 10313** is #1117's
regression lock: three unmarked source-scan tests over `MainWindow.xaml.cs`, so they land in
the standing selection by construction; deselected unchanged at 129 is the check that they
are selected, not merely collected. **A branch-tip gate is not evidence about the merged
result** — that tip gated 9285/0/21, ~1,000 short, being 280 commits behind.)*
>
*(prior — **RE-MEASURED** 2026-08-06 **16:53:42** local, merged `main` @ `85677aeb`, **340.61 s** —
primary checkout, models present, **AO stopped**, `LOCALAPPDATA` redirected, bash runner.
Start derives as 16:48:01, after `85677aeb`, so it is measurable. `85677aeb` is `20f922be`
plus ONE docs-only commit, so this run is a superset of the tree the entry below claimed.*
>
***TIMESTAMP CORRECTION — two stamps convicted, both retracted.*** *The 15:52 stamp was
impossible (a finish cannot postdate the commit recording it) and the 15:31 stamp was
internally inconsistent. **Treat neither as evidence; both counts stand on re-measurement and
on the addends below.** Full derivation — commit author-dates, run lengths, the 46 s of slack
— in merge `53522b4d` and `docs/reviews/baseline-derivation-disposition-2026-08-06.md`; it is
history now, and this section keeps the verdict rather than re-litigating it.*
>
**ADDENDS — MEASURED, and they sum** (#1300). Collection only, gate selection, at each
merge and its FIRST PARENT: `20f922be`/`66f233b5` and `c2a3f8f0`/`c2426fb5`.
>
| +69 over 10244 — #1281 `20f922be` | addend | how counted |
|---|---|---|
| `tests/integration/test_green_quality_prose.py` | +55 | new file |
| `tests/security/test_instrument_registry.py` | +7 | 1 registry row × 7 tests parametrized over `REGISTRY` |
| `tests/security/test_config_comment_truth.py` | +4 | the four planted cases |
| `tests/security/test_instrument_toggles.py` | +3 | the toggle trio |
| **sum** | **69** | 10244 → 10313 |
>
| +65 over 10179 — #1289 `c2a3f8f0` | addend | how counted |
|---|---|---|
| `tests/integration/test_smoke_contract.py` | +54 | new file |
| `tests/security/test_instrument_registry.py` | +7 | 1 registry row × 7 parametrized tests |
| `tests/security/test_instrument_toggles.py` | +3 | the toggle trio |
| `services/.../tests/test_execute_handler.py` | +1 | |
| **sum** | **65** | 10179 → 10244 |
>
*Both reconcile exactly; no `unattributed` row was needed. The registry rows are the
amplification a reader cannot reconstruct: one row, seven cases. **The band ships DORMANT**
(`[fleet_dispatch].green_quality_prose_band = false`) — measurement is live and
unconditional; this figure includes both halves of that flag's off/on pair.*
>
*(prior — MEASURED 2026-08-06 15:31 local, merged `main` @ `c2a3f8f0`, 333.59 s — primary
checkout, models present, **AO stopped**, and deliberately run with
`BLARAI_FLEET_AGENTIC_SETUP_DIR` UNSET: that override is the documented way to check a
cross-repo branch pair before either half merges, and setting it fails an unrelated test
(`test_load_harness_config_parses_overrides`, pre-existing sensitivity, #1297).
The **+65 over 10179** is #1289's behaviour-smoke contract landing with its paired
agentic-setup half `8a91983`: the contract writer and its integration suite, the
instrument-registry row for the honesty channel (which adds a case to each of the seven
tests parametrized over `REGISTRY`), the ReDoS regression lock with its real time bound,
and the two cross-repo gates. **Those two gates were RED on the branch by design** — they
fail until the reader is on agentic-setup's `main`, which is what the gate they replaced
could not detect — and went green on this merge, which is the merge-order proof.)*
>
*(prior — MEASURED 2026-08-06 09:39 local, branch tip of `fix/1274-ram-gate-stall`, 320.52 s —
primary checkout, models present, **AO stopped for this run**. An earlier attempt at 09:33
read 10172 passed / 7 SKIPPED because the battery had left the AO listening on 5001; that
is the documented live-app category, and it was fixed by stopping the AO rather than waved
through. The **+6 over 10173** is #1274's 5 locks PLUS one parametrized case: 
`test_timeout_registry.py:71` runs one test per REGISTRY row, so registering
`RAM_GATE_STALL_S` adds a test by construction. 5 + 1 = 6, and the count reconciles.)*
>
*(prior — MEASURED 2026-08-06 08:02 local, branch tip of `fix/1270-audit-fault-counter`,
324.92 s — primary checkout, models present. The **+5 over 10168** is #1270's dropped-card
counter locks, including the converse proving a genuinely quiet night still renders nothing.)*
>
*(prior — MEASURED 2026-08-06 00:03 local, branch tip of `fix/1269-probe-empty-is-not-measured`,
324.29 s — primary checkout, models present, battery stood down. The **+6 over 10162** is
#1269's probe-silence locks, including the converse proving a healthy probe still measures.)*
>
*(prior — MEASURED 2026-08-05 22:33 local, branch tip of `fix/1161-fa-operator-vocabulary`,
343.34 s — primary checkout, models present, battery stood down, no dispatch running.
The **+17 over 10145** is #1161 F-A's weak-tier operator-vocabulary control: the table is
the test corpus, so the count moves with the vocabulary by design — a term added without
its exclusions changes this number and fails a test rather than shipping silently.)*
>
*(prior — **MEASURED** 2026-08-05 evening local, merged main `427a5f18`, 356.86 s — app DOWN,
LOCALAPPDATA redirected, bash runner, venv python, no dispatch running, battery stood down.
**The 0-skipped MODELS-PRESENT form, in the PRIMARY CHECKOUT.** Measured on `4514be8b` and
carried to the merge commit by PROOF, not by assumption: `git rev-parse 427a5f18^{tree}` and
`4514be8b^{tree}` are the same object (`fedf4ee9`), so the merge produced a tree byte-identical
to the one measured and §3's post-merge re-run could not have differed. Where the trees are
NOT identical, run it — that is lesson 337 and this note is not a licence to skip it.*
>
***This line replaces a DERIVED figure, and the derivation was right.*** The 2026-07-30 entry
recorded 10145 as arithmetic (branch tip `47193a5e` measured 10124 passed / 21 skipped in an
external worktree; 10124 + 21 = 10145) because the primary checkout was held at land time, and
it labelled itself DERIVED and asked to be re-measured. The measurement now agrees to the test.
**The correction was never about the number — it was about a derived value sitting in the slot
reserved for a measured one.** That is the #1241 class exactly, which is why the debt was paid
before any new work: an instrument that is right by luck is still an instrument nobody checked.)*
>
*(prior entries before **2026-08-05** rotated out 2026-08-07 for the 40 KB budget — a
  second rotation on the same grounds as the 2026-07-30 one below it. They are superseded
  baselines and remain in this file's git history; `git log -p docs/TEST_GOVERNANCE.md`
  recovers any of them. **The §1 chain is not an archive** — it carries the live figure and
  enough provenance to trust it; git carries the rest.)*
>
*(prior entries before 2026-07-23 rotated out 2026-07-30 for the 40 KB budget — they are
  superseded baselines and remain in this file's git history; `git log -p docs/TEST_GOVERNANCE.md`
  recovers any of them.)*


---

## Rotated 2026-08-15 (second rotation)

Moved verbatim from `docs/TEST_GOVERNANCE.md` §1 when that file breached its
40,000-byte budget for the second time — 40,781 bytes, caught by
`tests/security/test_doctrine_freshness.py::test_hot_doctrine_files_respect_size_budgets`
at the moment the 11191 baseline was recorded. A pre-merge reviewer had flagged the
142 bytes of remaining headroom one message earlier; the warning was accurate and the
breach happened anyway, because the entry written was longer than the headroom.

Nothing is edited or trimmed here. These are the stamps as they stood.

> *Previous: **10913** passed / 0 failed / 0 skipped / 133 deselected*
> *(**CONFIRMED on `fix/1357-brief-server-guidance` @ `5414397b`** off `main` `e6a36a0d`,
> 2026-08-09, **started 21:08:54, finished 21:23:57** local, **896.53 s**, `pytest_exit=0`
> — assistant down, box idle. **+2**, `#1357`: the coder brief now says HOW to check a
> server without starting one, and both tests were toggle-proved by actually removing the
> line. **The 896 s is 2.1x the usual ~420 s and the cause is mine** — a subagent was
> running against the gate. FIELD_NOTES already says serialize heavy test loads; a slow
> gate is the cheap symptom, a flaky one would be the expensive version.*
>
> *Previous: **10911** on `fix/1359-freshness-window-cannot-survive-asset-gen` off `main`
> `801ca776`, 2026-08-09, **started 20:02:43, finished 20:10:00** local, **432.37 s**,
> `pytest_exit=0` — assistant down, box verified idle over three samples after a live
> dispatch was cancelled. **+1**, `#1359`: the per-card budget freshness window is a FLOOR
> now, locked against the MEASURED 431 s write→EXECUTE gap. The old 300 s value discarded
> every per-card budget an image-carrying card ever staged — B9 ran on the 10,800 s default
> every night it has ever run.*
>
> *Previous: **10910** @ `fdc9b6a5` — (branched from
> `main` `a454fe44` which did not move. 2026-08-09, **started 19:09:23, finished 19:15:58**
> local, **392.17 s**, `pytest_exit=0` — assistant down (stopped 18:59 after the battery
> ended), no dispatch, no battery. **+11**, `#1359`: a card's 28,800 s run envelope was
> silently replaced by the 10,800 s default and NOTHING recorded the substitution.*
>
> *TWO gate runs before this one were **invalidated by my own mid-run edits**, and the
> failure mode is worth the line: editing a source file while pytest holds it shifts the
> line numbers `inspect.getsource()` maps against, so three source-asserting tests in
> `test_oracle_mutation_stage.py` read back the WRONG FUNCTION and failed. That is not a
> defect in them. **Do not touch the tree while the gate runs** — and note `exit=$?` after
> a redirect chain reported `0` alongside `3 failed`, so the summary line, not the exit
> code, is what settled it (the same trap FIELD_NOTES records for pipes).*
>
> *Previous: **10899** @ `42bd64dd` — (branched from `main`
> `ceae01ee` which did not move — the merged tree is byte-identical to the branch tree, so
> the post-merge re-gate is provably the same run. 2026-08-09, **started 15:29:50, finished
> 15:36:52** local, **418.33 s** — assistant down (stopped 15:32 before the run), no
> dispatch, no battery. **+10**, `#1355`: +8 for the boot preflight that reported `passed ✓`
> eleven milliseconds after `send_prompt: connect failed`, having asserted nothing about what
> came back; +2 registry rows. The 418 s is ~48 s above the recent ~370 s runs — the new
> suite's retry-loop tests sleep on real backoffs (shrunk to 0.01 s, but 8 tests × several
> attempts is not free).*
>
> *Previous: **10889** @ `ff9038d0` — (2026-08-09, **started 13:19:29, finished
> 13:25:43** local, **370.20 s** — assistant down, no dispatch, no battery. **+5**, `#1351`:
> a repetition collapse is a failed generation, not an exam. Two banked oracles are
> BYTE-IDENTICAL (`habits2`..`habits55`, ending mid-token) because generation is
> deterministic — so a retry reproduces the corrupt exam exactly, and retry is not a remedy.)*
>
> *Previous: **10884** @ `6eb78773` — (2026-08-09, **started 13:02:24, finished
> 13:08:40** local, **372.76 s** — assistant down, no dispatch, no battery. **+14**:
> `#1350` (+6, a `not-run` stamp that finally says WHY) and `#1353` (+7 plus one, EXECUTE gets
> a budget covering the work it does).*
>
> *#1353 is the four-lost-nights root cause and it was arithmetic, not a break. EXECUTE
> generates the plan's dispatch assets at a measured 59.9 s/image inside what was the 180 s
> per-prompt default: 2 images = 98 s fit and the night went GREEN; 4 images = 142 s and 152 s
> did not, and both STALLED. `shared/timeout_registry.py` had already NAMED the asymmetry and
> correctly refused to widen the SHARED constant — this gives EXECUTE its own, as #766 did for
> PLAN, and a test locks that `PROMPT_RESPONSE_TIMEOUT_S` stayed at 180.*
>
> *Previous: **10870** @ `25218ab9` — (2026-08-09, **started 10:20:53, finished
> 10:26:56** local, **363.35 s** — assistant down, no dispatch, no battery. **+5**, all
> `#1355`: `tests/security/test_evidence_is_immutable.py`, DoD capability 16's wider class —
> no test may pin exact figures to `~/projects/`, the tree the coder fleet rewrites on every
> dispatch. Written because that class went red on this very gate at 04:56 the same morning.*
>
> *Previous: **10865** @ `e98cac79` — (2026-08-09, **started 06:00:55, finished
> 06:07:08** local, **370.38 s** — assistant down, no dispatch, no battery. **+20**, all
> `#1354`: `link_lint` and `image_placement` brought under `shared/instrument_registry.py`'s
> teeth (13 → 15 instruments), each naming its toggle, seam and quiet test.*
>
> *The +20 was PREDICTED by the authoring agent and deliberately NOT written into doctrine by
> it — "that is a derived figure, and pinning an unmeasured number into a doctrine surface is
> the exact defect this registry exists to refuse." It is stamped here only now that a full
> run produced it. The prediction was right; that is not the point.*
>
> *Previous: **10845** — (2026-08-09, **started 04:59:07, finished 05:05:13**
> local, **362.82 s** — assistant STOPPED, no dispatch, no battery. **+2 over 10843**:
> `6e7a15bd` (#1352 — a dispatch-asset nicety crashed the Assistant Orchestrator and cost
> the 2026-08-08 night; it degrades to no-asset now).*
>
> *This baseline is stamped after a RED gate, and the red is the lesson. Three
> `test_image_placement.py` tests failed at 04:56 with nothing about the grader changed:
> they asserted exact figures against `~/projects/battery-b9-pottery-site`, which the
> overnight battery had rebuilt. **A working directory the fleet rewrites is
> evidence-by-reference, and the reference moved while the tests slept** — capability 16
> (#1318) committed by tests written to enforce it. Retargeted to a dated
> `repos-archived/` snapshot with byte-identical findings. The rule: assert exact numbers
> only against immutable artifacts.*
>
> *Previous: **10843** @ `88a634eb` — (2026-08-08, **started 22:04:53, finished
> 22:12:28** local, **450.47 s** — primary checkout, assistant STOPPED, no dispatch, no
> battery. **+33 over 10810**: `c9fc9633` (#1349, +5 — the grader stopped calling the
> operator's own photographs pipeline waste) and `88a634eb` (#1348, +28 — requirement
> coverage can finally see a website; the assessor globbed `*.py` and then reported "no
> seeded job oracle" while a `.mjs` one sat in the same directory).*
>
> *A merge lesson banked with the figure: the first #1348 merge at 21:55 took only the
> branch's FIRST commit, because I merged while its agent was still working. The second
> commit — the reachability tests proving the node path is reached at BATTERY CLOSE, not
> just from `assess_run` — landed in a second merge. Merging a branch whose author has not
> reported is merging a moving target.*
>
> *Previous: **10810** @ `e8038c95` — (**CONFIRMED on merged `main`**, 2026-08-08, **started
> 21:00:01, finished 21:07:40** local, **455.06 s** — the CONFIRMING run, stamped rather
> than the 20:50:48 run that carried the same count but FAILED on the grammar gate; a
> baseline must cite the run that actually passed. Primary checkout, models
> present, assistant STOPPED, no dispatch and no battery live (the guard's own pattern —
> image AND invocation form — returned 0 driving processes). **+86 over 10724**, from the
> evening's second arc: every instrument that publishes a verdict now has to say what it did
> not measure.*
> - *`83633ce0` (#1342 item 2, +19, `test_oracle_qa_measurement_honesty.py`) — the QA record
>   reported `findings_total: 0` beside `f2p_baseline: "not-run"`. `findings_conclusive` is
>   now false whenever any producing stage did not run.*
> - *`74257ce7` (#1345, +38, `test_image_placement.py`) — grades where a site's pictures
>   LAND. Catches the operator's own two remaining complaints on the real delivery.*
> - *`ca742a99` (#1346, +24, `test_morning_website_section.py`) — the morning report names
>   the site built last night, or says why it cannot.*
> - *`95e007be` (lesson 33's owed control, +5,
>   `test_graders_disclose_what_they_did_not_measure.py`) — deny-by-default: a module that
>   publishes a findings total must carry some way to say a check did not run. Found zero
>   real offenders; it is a ratchet against the next one, proved able to fire by planting one.*
>
> *This run FAILED once before passing, and the failure was worth having:
> `test_coder_dod_grammar.py` rejected a `Status: STARTED` line written into capability 12
> earlier the same evening. STARTED is not in the legend, and PARTIAL was the honest word
> anyway — one reviewed delivery is a data point, not the published rate the row asks for.
> The grammar gate caught a status claim that had drifted past its own legend.*
>
> *Previous: **10724** @ `75e8e24f`, 2026-08-08 19:48:05→19:55:09, 419.62 s, **+69 over
> 10655**, from two merges that give the delivered PRODUCT its first automated examination:*
> - *`32a9ed1f` (#1345, +26, `shared/tests/test_link_lint.py`) — every href/src in a
>   delivered site resolved against the root a server actually mounts. The operator found a
>   broken "View Details" button by hand in under a minute that four gates had passed;
>   nothing was asking whether a link's target existed. Advisory, not a gate: a regression
>   lock proves a broken site and a clean site produce identical verdicts.*
> - *`75e8e24f` (#1343, +43, `tests/integration/test_battery_website_presentation.py`) — a
>   website battery run now ends by leaving him a record and a double-click launcher, after
>   every measurement has landed. Fail-open by design in this one place, proved
>   byte-identical across seven forced failure paths.*
>
> *Previous: **10655** @ `462c55cb`, 2026-08-08 18:37:54→18:43:50, 353.32 s, **+81 over
> 10574**, from the evening's three merges, all of them locks on instruments that were reporting
> passes they had not measured:*
> - *`4a51fb5e` (#1342, +38, `shared/tests/test_oracle_qa_node.py`) — node oracles skipped BOTH
>   execution-stage probes unconditionally, so a website was exactly the case where nobody
>   checked whether the exam could fail. Fail-to-pass baseline + static vacuity for node.*
> - *`7821bab4` (#1342, +19, `test_already_satisfied_precheck.py` 16→35) — an oracle never shown
>   capable of failing may no longer delete work from the plan.*
> - *`462c55cb` (#1341, +27, `tests/integration/test_battery_evidence_capture.py` and its
>   `live_dispatch` witness) — the scorecard cited a mutable file as evidence and stamped a
>   pre-build commit count as a run property.*
>
> *Measured AFTER all three merges, so it is the merge tree's own figure, not inherited from any
> branch. Each of the three ships its refusal case (principle 12): the #1342 precheck lock was
> toggle-proven by forcing its probe to `return True` — 14 locks fail, while the
> still-skips test keeps passing, so the suite tells "correctly gated" from "broken outright".*
>
> *(prior — CONFIRMED on merged `main` @ `0ea1f32b`, 2026-08-08, 14:31:48→14:37:38, 346.57 s,
> **10574**; +9 over 10565, all `test_failure_taxonomy.py`, #1324's honesty split.)*
>
> *(prior — CONFIRMED on merged `main` @ `be0ad99b`, 2026-08-07, 23:28:25→23:33:57, 325.96 s,
> **10565**.)*
>
> *(**RE-MEASURED on the resolved merge tree** of `docs/dod-ratification-20260807` × `main@49e4cb18`,
> 2026-08-07, **started 23:21:58, finished 23:27:32** local, **327.66 s** — worktree
> `blarai-wt-dod-rat` at model parity, venv interpreter, AO stopped, no battery live. **The
> re-merge was CLEAN — no conflicts in this file or in the `CLAUDE.md` snapshot**, contrary to
> the landing brief's expectation, because the branch already carried main's measurement history
> and the four commits main gained since (`cce07cc6`, `43e30e59`, `a6bfd39a`, `49e4cb18`) touched
> neither. The figure the files already carried was therefore MEASURED rather than inherited —
> a clean merge of two independent baseline edits is precisely the case the doctrine-freshness
> gate cannot catch, since it compares the two documents to each other and never to reality.*
>
> *(**MEASURED on the merge tree** of `docs/dod-ratification-20260807` × `main@bcaf2cd7`,
> 2026-08-07, **started 19:56:24, finished 20:04:43** local, **490.93 s** — dedicated worktree
> `blarai-wt-dod-rat` at model parity (junction-completed; an earlier same-tree run skipped ONE
> test, `test_benchmark_kv_cache_sweep.py`, on a missing linked model file — completed, re-run
> 27/27, then clean full runs only), venv interpreter, AO stopped (launcher pid 9752 stopped
> 19:21 for the gate window, restarted after the post-merge confirmation), no dispatch, no
> concurrent gate. **+13 over 10552**, all of it `tests/security/test_coder_dod_grammar.py` —
> the DoD status-grammar gate ratified with capability 11 (#1325): status presence on all 21
> rows, legend vocabulary, LIVE-requires-dated-citation, acceptance-test Executed lines, four
> checker fail-proofs and one conforming-pass proof, plus 2 beyond-range hardening tests from
> the pre-merge review. Reconciles across tonight's three parallel arcs:
> 10526 + 21 (#1327) + 5 (#1324) + 13 = 10565. Deselected unchanged at 133.*

**Documented environmental deltas (benign only because named and bounded):**
non-elevated shell → 2 symlink skips · isolated worktree without the gitignored models →
~21 router env-skips · live app on :5001 → 7 skips · PowerShell tool shell → 3
false-fails (TERM / PYTHONIOENCODING) · a `PYTHONUNBUFFERED`/`-u` override → 2
`launcher/tests/test_import_side_effects.py` false-fails (2026-07-21 — do not add
output-buffering overrides to gate invocations). An unexplained skip is a defect.

**Deselected tiers** run at their own dev-machine ceremonies: `@hardware` (model-loaded,
real Arc 140V), `@winui` (GUI harness), `@slow` (socket E2E). Model-quality eval gate:
`python -m evals.run --suite all` — committed baselines, regression exit codes with teeth.

**History:** every prior baseline chapter and the Sprint-8-era named-scope tables live in
[`docs/archive/testing/baseline_history.md`](archive/testing/baseline_history.md) — do
NOT append chapters here; the live line above and the shipping ticket are the record.


---

## Rotated 2026-09-19 from `docs/TEST_GOVERNANCE.md` §1

Per-merge baseline stamps from 2026-08-17 and earlier, moved verbatim when the live file
reached 42,483 bytes against its 40,000-byte budget and `test_doctrine_freshness.py`
refused the commit. Nothing was edited on the way out.

> *(**CONFIRMED on `fix/agent-calibration-pass-1`**, 2026-08-17, **10:59:28 → 11:06:35** local,
> **423.93 s**, `pytest_exit=0` — box quiet: assistant down, no launcher, no run live. **+8**,
> all in `tests/integration/test_morning_digest.py` (6 → 14): the digest reads only the run's
> own capture (a sibling run's identically-named clean capture is never borrowed; a stray
> directory cannot replace the night; a suffix-less newest run is not displaced), the quoted
> scorecard evidence is bounded and markdown-inert, the verdict sentence cannot contradict the
> counts beside it, and a clean night keeps its one reassuring sentence. Predicted 11275 as
> 11267 + 8; it printed 11275.)*
>
> *(Prior stamp, superseded: 11267 on `fix/1433-forms-per-page`, 2026-08-17 09:06:55 →
> 09:13:42, 403.63 s. **+3**: `tests/integration/test_harvest_run_evidence.py` —
> an old-shape sidecar's missing `pagesChecked` reads ABSENT and never as zero pages checked;
> the new site-wide forms shape banks by row; and "nothing was undecidable" is a measured zero
> rather than an absence. That third lock exists because the first draft of the counter used an
> `and`/`or` chain and a genuine zero is falsy — the absence-as-a-value defect very nearly
> shipped inside the fix for it.)*
>
> ***THE PREDICTION MISSED BY 7, AND THE MISS IS THE FINDING.*** Predicted 11260 as
> `11251 + 6 + 3`; it printed **11267**. Chased before merging rather than shrugged at, which is
> the entire reason the prediction is written down. Collection counts settle it: `main` collects
> **11264**, this branch **11267**, so the `+3` was exact and **the error was in the baseline,
> not the change.**
>
> **`main`'s recorded figure was 11251 while `main` actually collected 11264 — understated by
> 13, not by the 6 first supposed.** The assumption that everything between the 11251 stamp and
> `main` was documentation was false: the dod-audit work (`fcb61ed1`, `e7d10c07`, `1df9dd6e`)
> added tests as well as the three agent commits (`b83213cb`, `73541be9`, `3b1d57fe`), and none
> of those sessions updated either baseline surface.
>
> **The freshness gate could not see any of it**, because it compares this line to `CLAUDE.md`
> and they agreed with each other while both were wrong — *"a stale pair that agrees with each
> other passes green"*, which this section warned about in the abstract and has now happened
> twice in one day. **A prediction that misses is the only instrument that catches it**, and it
> only works if the miss is chased instead of overwritten with the observed number.
>
> *(**#1433**, 2026-08-16 evening: **+3** in `tests/integration/test_harvest_run_evidence.py` —
> an old-shape sidecar's missing `pagesChecked` reads ABSENT and never as zero pages checked; the
> new site-wide shape banks by row; and "nothing was undecidable" is a measured zero rather than
> an absence. That last lock exists because the first draft of the counter used an `and`/`or`
> chain and a genuine zero is falsy — the absence-as-a-value defect very nearly shipped inside
> the fix for it. Stamp recorded on the merge commit.)*
>
> *(**CONFIRMED on `fix/1418-persist-refused-oracle-qa`**, 2026-08-16, **13:26 → 13:34** local,
> **464.54 s**, `pytest_exit=0` — assistant DOWN. **+4**: the #1418 locks in
> `shared/tests/test_integration_gate.py` — every pre-gate refusal banks its evidence, the
> empty-evidence converse, malformed plan-time JSON, and the operator-facing message pinned as
> a STRING because the string is the defect. Predicted 11247 + 4; it printed 11251.*
>
> *(Prior stamp: **CONFIRMED on `fix/1416-node-exam-quality`**, 2026-08-16, **12:54:16 → 13:02:29** local,
> **486.50 s**, `pytest_exit=0` — assistant DOWN, box quiet since the overnight run exited 07:03.
> **+50 over 11197**: `shared/tests/test_coder_test_qa_node.py`, #1416's node exam scanner.
> It reached 16 locks at first green and **50 after six rounds of independent review** — the
> growth is the review, not the feature.*
>
> **Predicted 11247 before reading it: 11213 + 34. It printed 11247.**
>
> ***This figure was measured four times and three were discarded, deliberately.*** Each earlier
> run was invalidated the moment a review round landed a fix, and one was thrown away because I
> edited the tree WHILE it ran — which is the thing this file's own rule forbids, for exactly the
> reason that a stamp taken across a changing tree describes neither state. A gate figure is a
> claim about a specific tree; re-running costs eight minutes and reporting a stale one costs the
> credibility of every number beside it.)*
>
> *(**Re-confirmed on merged `main` @ `2fbb846c` at 11247**, 13:09:57 → 13:18:36, 515.12 s —
> the post-merge run #1416's merge required. Identical to its branch figure, so the merge
> broke nothing.)*
>
> *(Prior stamp: **CONFIRMED on `main` @ `4759d4ef`**, 2026-08-16, **11:08:18 → 11:14:55** local,
> **393.48 s**, `pytest_exit=0` — assistant DOWN and verified absent over an interval (`ovms.exe`
> exited at 07:03 with the overnight run, python process count 0 at 11:07). **+6**:
> `tests/integration/test_night_check.py`, the locks on the 03:00 battery health check.*
>
> ***The staleness this replaces was declared, not discovered***, and the declaration was worth
> more than the number it stood in for. The block here read `11191` with a prose warning that the
> true figure was **11197** and could not be measured because the overnight coder run was live.
> **The prediction was exact.** What matters is the mechanism it named: the freshness gate compares
> this line to `CLAUDE.md`'s snapshot **and nothing else**, so a stale pair that agrees with each
> other passes green. A machine check that both surfaces match is not a check that either is true,
> and the only instrument that closed the gap was a sentence a reader had to read.
>
> **Predicting the count before reading it caught nothing again, which remains the point of doing
> it**: 11191 + 6 = 11197 and the gate printed 11197. A prediction that matches is cheap
> confirmation that no test file was silently dropped; a prediction that misses is the only early
> warning there is.)*
>
> *(Prior stamp, retained for the two-runs lesson below: **CONFIRMED on
> `docs/1414-roadmap-rank1-correction`**, 2026-08-15, **19:13:56 → 19:20:26** local, **387.44 s**,
> `pytest_exit=0`. **+16**: `tools/probes/harvest_run_evidence.py` (11) and
> `tools/probes/requirement_coverage_report.py` (5), both read-only probes over banked artifacts,
> both toggle-proved. The 16th arrived from a pre-merge reviewer who found the coverage probe
> rendering a MISSING acceptance.json as "he stated 0 requirements" — the latent twin of its
> sibling's headline lock, unreachable by any existing test because the fixture always wrote the
> file.)*
>
> ***That figure needed two runs and the first one was wrong in the documented way.*** The 18:40
> run reported **11183 passed / 7 skipped** because the battery's swap-back had restored the
> assistant on port 5001 at 18:39:26 — twenty-one seconds after the coder run ended, and
> fourteen seconds before the gate started. Nothing was leaked and nothing misbehaved: the run
> put the operator's assistant back, correctly, into the window the gate was about to use.
> **A green 11183/7 is not this baseline** — the seven are the port-5001 class, and the bar is
> 0 skipped. Stopped the assistant, re-ran, restarted it after.
>
> The same prediction discipline ran clean on that pair too: 11175 + 15 = 11190 and the gate
> printed 11190; then +1 = 11191 and it printed 11191.
>
> **`xfail(strict=True)` is NOT a skip and is not covered by the 0-skipped bar.** A skip does
> not run; a strict xfail RUNS, asserts the failure, and fails the suite the moment it starts
> passing — so it is a live regression lock on a KNOWN, TICKETED defect, and it forces its own
> deletion when the fix lands. Two exist as of 2026-08-14 (#1396), both asserting that a
> coverage caveat reaches the scorecard field that actually ships. An xfail with no ticket, or
> without `strict=True`, IS rot and should be treated as a skip would be.
>
> **Never pin a test figure to `~/projects/*`.** That tree is the coder fleet's working
> area: every dispatch archives what is there and recreates it, so a test targeting it measures
> whatever last ran. Moved here from CLAUDE.md 2026-08-14 (#1382) because this section owns gate
> mechanics — and because it is now ENFORCED rather than remembered: the root `conftest.py`
> installs an audit hook that fails the run if any test reads that tree, catching paths computed
> at runtime as well as literals (#1355, DoD row 16).
> *(**CONFIRMED on `fix/1350-node-not-run-says-why` `842d7d41`**, 2026-08-14,
> **17:38:42 → 17:45:20** local, **394.32 s**, `pytest_exit=0` — assistant down, no battery
> or dispatch live (the 23:00 night had not started). **+6**: `#1350`'s node diagnostics —
> the node fail-to-pass path returned a bare `("not-run", [])` at all five exits while its
> python sibling had used the `_not_run(cause, detail)` helper, written for that same ticket,
> since it landed. Four locks on the causes, one wiring lock (the dict reaches the banked
> evidence, else it is collected and dropped), one QUIET lock (a baseline that RAN leaves no
> cause behind, so a populated dict cannot come to mean "measured"). The stamp string stays
> exactly `not-run`, kill-tested: gates decide whether an oracle may DELETE work by
> membership against `STAMPS_NOT_MEASURED`, and a decorated `not-run:timeout` would fail that
> test and reinstate the #1342 amputation.)*
>
> *Immediately prior: **10953** on merged `main` `6d88c2fa`, re-confirmed four times on
> 2026-08-14 (383–423 s) across the #1380 battery-guard and #1367/#1375 brief-delivery arcs,
> none of which changed the count.*

> *Previous: **10944** passed / 0 failed / 0 skipped / 133 deselected*
> *(**CONFIRMED on merged `main` `037e0187`**, 2026-08-10, **10:26:36 → 10:34:34** local,
> **478.89 s**, `pytest_exit=0` — assistant down. **+7**, `#1375`: `link_lint` resolves
> `fetch()` targets. Both of the pottery site's central pages fetch a JSON file outside
> the served root — every visitor 404s. `image_placement` had read that same file **off
> the filesystem** and graded it. A file that exists is not a file that is served.*
> *The first attempt returned **1 failed / 7 skipped**: `test_evidence_is_immutable`
> correctly refused tests pinned to `~/projects/`, and the skips were the port-5001 class
> — I gated with the assistant UP. Both on #1375.)*

> *Previous: **10937** passed / 0 failed / 0 skipped / 133 deselected*
> *(**CONFIRMED on MERGED `main` `15a4d125`**, 2026-08-10, **started 08:50:12, finished
> 08:58:27** local, **490.69 s**, `pytest_exit=0` — assistant down (launcher stopped for
> the run), box verified idle across three samples over 55 s after the B9 dispatch ended
> at 08:45:33. **+17**, `#1366`: the registry can now compare two of its own numbers.
> `role` (a required, closed six-word vocabulary) on all 64 rows and `must_exceed` naming
> the durations each must outlast — ten declared, all holding, one generated assertion per
> pair. It replaces roughly thirteen hand-written ordering tests spread across three files,
> **none of which contained the pair that cost the run**: a hand-written test only exists
> where somebody thought of the pair. Registering the doom window's third vantage
> (`DispatchHarness.stall_grace_s`) accounts for one more row — that quantity is declared
> in FIVE places while a comment beside it asserted "two".*
>
> *Previous: **10920** passed / 0 failed / 0 skipped / 133 deselected*
> *(**CONFIRMED on `fix/1366-doom-window`** off `main` `a48d623d`, 2026-08-10, **started
> 01:12:07, finished 01:19:03** local, **412.19 s**, `pytest_exit=0` — assistant down.
> **+7**, `#1366`: the first structural control lesson 221 has ever had, arriving at its
> seventh instance. The doom window sat INSIDE the 600 s judge it was watching, and three
> tests pinned to the old 240 are why it sat there for a month — one of them presented as
> a **25-minute gate hang**, which reads as "you broke production" rather than "this test
> names a number". Verified by CONTROL, not correlation: `shared/tests` without the change
> 3991 passed / 121.97 s, with the change and the test fixes 3991 / 122.15 s.*
>

---

## Rotated 2026-10-07 — the 12086 stamp (merged main `3be0e22e`, 2026-09-22)

> *(**CONFIRMED on MERGED MAIN `3be0e22e` in the REAL checkout**, 2026-09-22, finished 18:37 EDT,
> **ELEVATED**, 12086 passed / 0 failed / 0 skipped / 133 deselected in 554.45 s. Re-run AFTER the
> merge, per the merge guard: the branch read the same figure at 17:53, and the merge itself can
> break what both parents passed. Quiet box, no GPU
> work running. **+33 over the 12053 figure recorded at 15:32**, reconciling as: 12 from the new
> `tests/integration/test_rubric_security_checks_are_reachable.py` (a security check was UNREACHABLE
> behind a content check, so a verbatim system-prompt dump was banked as "none of ['8%'] found in
> answer"), 10 from the new `tests/integration/test_agentic_loop_matches_production.py` (the eval
> loop took production's PLAIN branch for retrieval results, measuring injections with the
> datamarking defence removed), and 11 from new classes in `test_multiturn_prompt_assembly.py` (the
> #1621 fix reverted inside the tool loop from the second iteration; the brain gate now asserts both
> rows). Four separate runs were discarded before this one because each overlapped an edit and its
> figure therefore did not cover the tree it claimed to. Two failures were fixed rather than worked
> around: a lesson-tally mint in the wrong archive dialect, and a fail-closed `break` in the AO tool
> loop with no user-visible notice — caught by
> `test_every_break_sets_a_notice_or_a_rewriting_flag`, which an independent reviewer then showed
> should not have been a `break` at all.)*
>
> *(SUPERSEDED 2026-09-22 — 12053 at 15:32, 12023 at 04:47, 12008 at 01:13, and 11990/0/3
> non-elevated on merged main `bdc313d3` the night before. All reconcile into the figure above.)*
>

## Rotated 2026-10-07 from TEST_GOVERNANCE §1 (#1699)

> *(Previous stamp: **MERGED `main` at `0fadabca`, REAL checkout**, 2026-10-07, 15:16:51 to 15:44:36 -04:00, **ELEVATED**,
> app down, `LOCALAPPDATA` redirected, `--durations=0`: 13233 passed / 0 failed / 0 skipped / 620 deselected
> in 1660.77 s. Predicted before the run: 13189 + 44 tests (`tests/security/test_gate_timing_runner.py`,
> #1699) = 13233; it matched. The operator was at the machine, so the wall-clock is a correctness run's,
> not a timing figure.)*
>
> *(Previous stamp: **MERGED `main` at `7eee19b3`, REAL checkout**, 2026-10-07, 14:13:42 to 14:39:45 -04:00, **ELEVATED**,
> app down, `LOCALAPPDATA` redirected, `--durations=0`: 13189 passed / 0 failed / 0 skipped / 620 deselected
> in 1558.83 s. Predicted before the run: 13179 + 5 tests (#1703, `ca1fb6f8`) + 5 (its review fixes,
> `281d3f33`) = 13189; it matched. The operator was at the machine, so the wall-clock is a correctness
> run's, not a timing figure (see #1699). The previous stamp, below, is the 13179 reading.)*
>
> *(Previous stamp: **BRANCH `feat/1616-corpus-tier` at `05a0ad55`, REAL checkout**, 2026-10-07, 10:28:51 to 10:53:41 -04:00,
> **ELEVATED**, app down, no other heavy work, `LOCALAPPDATA` redirected: 13179 passed / 0 failed /
> 0 skipped / 620 deselected in 1486.39 s. The merged-main re-run of the identical tree is recorded in
> row 7d of `docs/reviews/corpus-tier-slice1-disposition-2026-09-24.md`. The 620 deselected are the
> `hardware` (13) and `slow` (612) markers, counted directly with `-m`; the old 133 predates the `slow`
> growth. Wall-clock is 1486 s, not the 554 s of the previous stamp, under the same conditions. Run 1
> on `81059c29` read 1 failed / 13176 passed (`test_normal_args_cover_every_real_tool_and_property`:
> main's #1685 lock against this branch's `search_reference`, fixed in `05a0ad55`); the 13177 predicted
> before that run + 2 parametrized cases the fixture entry adds = 13179.)*

## Rotated 2026-10-08 from TEST_GOVERNANCE section 1 (#1707)

> **The prediction was derived from COLLECTION, not by adding deltas to 11828.** The
> dry-run arc added, modified and REMOVED tests across six files; summing those by
> hand is how a confident wrong figure gets predicted.
>
> **One test was deliberately removed to keep the zero-skip form reachable at all**
> (`59e6a621`): a symlink-escape probe that skipped on EVERY run, elevated or not,
> because `os.symlink` raises WinError 1314 here — the privilege is granted to the
> Administrators group but not ENABLED in the token. A permanent skip in a zero-skip
> gate is a defect however well explained.
>
> **The stamp sat three merges behind, and the reason is rule 6 rather than neglect.** The
> #1584 post-merge run at `45a4da60` read **11814 passed / 7 skipped** with the desktop app
> UP: those are the documented port-5001 skips, so the run confirmed the merge but could not
> set a baseline, whose form is 0 skipped. Deriving 11814 + 7 = 11821 would have produced the
> right number by the wrong route — a derivation standing in for a measurement when the
> measurement was one quiet run away. Both figures below were MEASURED with the app closed.
>
> **#1581 needed TWO post-merge runs, and the first one is the lesson.** The branch gate at
> `66de7d2f` read 11711/2/26 — predicted exactly. The post-merge gate at `46c44454` read
> **3 failed / 11736 passed**. Three new structural locks walked `repo.rglob("*.py")` from the
> repo root, and the PRIMARY checkout holds six other sessions' worktrees under
> `.claude/worktrees/`, each a full copy of this repo — so they found a second
> `audit_verification.py` in a sibling checkout. In a worktree there is no nested checkout, so
> they passed there. **The branch gate could not have caught it, and neither could the
> adversarial reviewer: both ran in the worktree.** Fixed in `40d04a43` by enumerating with
> `git ls-files` rather than walking the directory.
>
> **This is the cleanest case yet for why the post-merge gate exists.** Neither parent was
> wrong. The difference was entirely the environment the gate runs in — which is exactly the
> variable a worktree figure cannot speak to, and the reason rule 5 above says a worktree
> figure is not the baseline.
>
> **FOUR merges since the last stamp, and every one predicted exactly — including the SKIP
> column, which is the habit that was missing when 11658/3 slipped through.**
>
> | merge | branch gate | primary | predicted |
> |---|---|---|---|
> | #1586 `36bced4f` | 11672/2/26 | **11700** | 11700 — exact |
> | #1594 follow-up | — | — | (rolled into the above) |
> | #1595 `f51c50c9` | 11680/2/26 | **11708** | 11708 — exact |
> | #1596 `eb0af7db` | 11671/2/26 | **11699** | 11699 — exact |
> | #1581 `46c44454` | 11711/2/26 | 11736 + 3 FAILED | 11739 — count exact, 3 broke on merge |
> | #1581 fix `40d04a43` | — | **11739** | 11739 — exact |
> | #1582 `336c620e` | 11735/2/26 | **11763** | 11763 — exact, clean first run |
> | #1583 `7a03379f` | 11749/2/26 | **11777** | 11777 — exact, clean first run |
> | #1593 `60f7c74e` | — | **11777** | docstring + journal only; no count change |
> | #1584 `45a4da60` | — | 11814 / **7 skipped** | app UP: the 7 port-5001 skips. Merge confirmed, baseline NOT settable |
> | #1589 `fe865e12` | — | — | CLAUDE.md principle 9 only; no count change |
> | #1590 `9ec0fb1e` | sec-tier 1473/2 | **11821** | 11821 — exact, skip column too, app closed |
> | #1544 `43066fc6` | sec-tier 1480/2 | **11828** | 11828 — exact; +7 card-vs-code locks, reconciled 1480 = 1473 + 7 |
> | dry-run chain `59e6a621` | 3387/2 | **11965** / 3 skipped | exact, BOTH columns — predicted from collection, NON-ELEVATED (elevated reads 11968/0) |
>
> **#1596 is the only one where the count went DOWN, and the reason is the finding.** −14 dead
> `CircuitBreaker` tests, +5 row-24 locks. That class had no production caller — both breakers
> — while claim-register row 24 cited it as LIVE and a 306-line governance document described
> its trip semantics in detail. Both caps were real, enforced elsewhere, so every check against
> the row passed; **the row would have read identically if nothing bounded the loop at all.**
>
> **A gate ran 21:32 instead of ~11:00 on 2026-09-20** because research agents were running
> alongside it. The result held, but that is the #1597 lesson repeating: a gate is a
> measurement, and anything else on the box is an unrecorded variable in it. The quiet runs
> either side came in at 9:23–10:16.
>
> The reconciliation held for six consecutive merges: branch_passed + skipped + failed =
> primary_passed, written down BEFORE each primary run. At #1581 it held as ARITHMETIC while
> the run was red — 11711 + 26 + 2 = 11739, and the primary produced 11736 passed + 3 failed,
> which is the same 11739 tests. **The reconciliation predicts how many tests RUN, not how
> many pass.** A red gate whose arithmetic checks out is still a red gate.

> *(SUPERSEDED — kept per the retraction rule. Its figure and its retraction of the earlier
> "starvation" diagnosis both stand.)*
> *(**CONFIRMED on merged main `607768a9` in the REAL checkout**, 2026-09-19, **803 s**,
> **ELEVATED**, on a QUIET machine — 0 failed and **0 skipped**.
>
> **RETRACTION, and it is the reason this entry is long.** The entry below this one says the
> 2026-09-19 13:07 run failed `test_graduation_reset_stamps_current_mode_immediately` because
> "a thread-timing test starved" under load I was generating. **That is wrong. It does not
> starve; it RAISES.** Measured on the 14:09 branch gate with full output captured:
> `PermissionError: [Errno 13]` from `read_text` on the stamp file. The heartbeat thread
> rewrites that file atomically and on Windows the target is briefly unopenable during the
> replace, so a tight poll eventually collides with it. Load WIDENS that window — which is why
> the correlation was real — but a deadline can never catch an exception, so #1163's 5 s → 30 s
> widening and the synchronisation-point redesign #1597 first proposed were both aimed at a
> mechanism that was never the cause. **Three sessions diagnosed this without its traceback,
> because the gate script piped pytest through `tail`.** Fixed at the real mechanism (#1597);
> gate scripts now write full output to a file and summarise for display, never the reverse.
> The superseded entry is kept below rather than edited, with the wrong version visible.
>
> **THE PREDICTED SKIP COUNT WAS WRONG AND THAT IS WHAT FOUND THE NEXT DEFECT.** The `d8d47563`
> run read **11658 passed / 3 skipped** against a prediction of 11661 / 0. The total reconciled
> (11658 + 3 = 11661), so the arithmetic was satisfied and the run looked green. **3 skipped has
> two causes with OPPOSITE responses** — three new tests env-skipping, or a NON-elevated run's
> symlink delta — and they are indistinguishable from the count alone. It was the former: an
> env-skip predicate pointing at `parents[1]` (the service directory) rather than `parents[3]`
> (the repo root), a path present in NEITHER checkout, so the skip fired everywhere and the test
> it guarded ran nowhere while its own message claimed it runs in the primary. A test that cannot
> execute is built-but-wired-into-nothing wearing a skip mark, and a green run reports it as
> environmental. Fixed in `1b7c6252`, with a control that derives the path from the shipped config
> and RUNS EVERYWHERE — a control on a conditional skip must not share the skip's condition.
>
> **Predict the skip column, not only the pass column.** Three consecutive merges reconciled the
> pass count exactly and this one hid a defect in the column nobody predicted.
>
> **The worktree/primary reconciliation was predicted before the run and confirmed.** Branch gate
> at `1b7c6252`: **11634 passed / 2 failed / 26 skipped** (670.52 s, elevated, quiet);
> 11634 + 26 + 2 = **11662** written down first. The 23 long-standing worktree skips are the
> gitignored-model router tests and 3 are the Known-Good-Manifest resolver tests, all of which RUN
> in the primary; the 2 failures are the ADR-013 doc-pointer artifact, worktree-only.
>
> The delta over 11654 is #1594's consent-grain locks, #1597's two heartbeat poll locks, and the
> env-skip control.
> A post-merge re-run tells you only that the merge broke nothing, and it has caught a failure
> NEITHER PARENT had before.

> *(SUPERSEDED — kept per the retraction rule. Its explanation of the heartbeat failure as
> load-induced STARVATION is wrong; see the retraction above. Its gate figure stands.)*
> *(**CONFIRMED on merged main `954029bc` in the REAL checkout**, 2026-09-19, **13:21:32 →
> 13:35:00** local, **803.17 s**, **ELEVATED** — 0 failed, 0 skipped, **and the machine held QUIET
> for the whole window**, which this entry treats as a stated run condition rather than an
> afterthought.
>
> **THE SAME COMMIT PRODUCED TWO DIFFERENT RESULTS, AND THE VARIABLE WAS ME.** An earlier run at
> 13:07 on this identical HEAD read **11653 passed / 1 failed** — `test_heartbeat_thread.py::
> test_graduation_reset_stamps_current_mode_immediately`, which polls a background thread. I had an
> 83-test suite and three mutation cycles running in a worktree on the same laptop throughout. Run
> 2, with nothing else running, read 11654 / 0. That test's own comment claims 30 s "is not"
> starvable after #1163 widened it from 5 s; the claim is now falsified and the successor is
> **#1597**, which says plainly that a third deadline increase is the same wrong instrument.
> **A gate run is a MEASUREMENT: anything else running on the box is an unrecorded variable in it,
> and the count reconciled either way (11653 + 1 = 11654), so the arithmetic would not have caught
> it.** The failing assertion was NOT captured, because the gate script piped pytest through
> `tail`; the mechanism above is the supported hypothesis, not a measurement, and gate scripts now
> write full output to a file.
>
> **The worktree/primary reconciliation was PREDICTED before the run and then confirmed, for the
> third consecutive merge.** The pre-merge branch gate in the worktree read **11629 passed / 2
> failed / 23 skipped** (759.79 s, elevated); 11629 + 23 + 2 = **11654** was written down first and
> the primary read exactly that. The 23 worktree skips are the gitignored-model router tests, which
> RUN and pass in the primary; the 2 failures are the ADR-013 doc-pointer artifact, which is
> worktree-only.
>
> **A prediction in this arc was also WRONG, and it is recorded because of its shape.** The round-2
> branch gate was predicted at 11600 and read 11599: I counted the test functions the diff ADDED
> and never grepped for the one it REMOVED (`test_long_query_capped_at_200`, rewritten in place, so
> it is both). Round 3's delta was MEASURED by collecting the changed files rather than counted
> from the diff, and was exact.
>
> **CORRECTION to the previous entry, which is preserved below with this noted.** It states the
> pre-merge worktree gate read **11578** and then reconciles using **11581**; 11578 + 23 + 2 is
> 11603, not the 11606 that was confirmed. 11581 is the correct figure — independently implied by
> this arc's round-2 branch gate (11599 at `dd7177f2`, +18 net tests over `bcb8313d`). The prose
> was right and one digit was wrong.
>
> The +48 over the prior 11606 is #1592: the outbound-query disclosure rendering and its locks (all
> seven invisible-character categories, the astral tag-block escape, four loop-driven caller locks)
> plus the four new locks holding claim-register row 12's TLS blind spot.
> A post-merge re-run tells you only that the merge broke nothing, and it has caught a failure
> NEITHER PARENT had before.

> *(SUPERSEDED — kept per the retraction rule; its 11578/11581 discrepancy is corrected above.)*
> *(**CONFIRMED on merged main `bcb8313d` in the REAL checkout**, 2026-09-18, **17:21:41 →
> 17:33:31** local, **710.12 s**, **ELEVATED** — 0 failed and **0 skipped**.
>
> **The 0 skipped is the prediction on the previous line coming true, and it is a CHANGE, not a
> pass to wave through.** That line read 3 skipped, said the 3 were the documented non-elevated
> symlink delta, and said an elevated run must read 0. This run was elevated and read 0. A reader
> comparing 3 to 0 across these two entries is looking at a different RUN CONDITION, not at three
> skips that were fixed — so every figure here now states its elevation.
>
> **The worktree/primary reconciliation was PREDICTED before the run and then confirmed.** The
> pre-merge branch gate in the worktree read **11578 passed / 2 failed / 23 skipped / 133
> deselected** (659.82 s, elevated); 11581 + 23 + 2 = **11606** was written down first and the
> primary then read exactly that, for the second consecutive merge. The 23 worktree skips are the gitignored-model router tests, which
> RUN and pass in the primary; the 2 failures are the ADR-013 doc-pointer artifact, which is
> worktree-only. Predicting the figure is what makes the reconciliation evidence rather than a sum
> reached after the fact — the arithmetic works either way, and only one order can be wrong.
>
> The +3 over the prior 11603 is #1587's receipts-per-turn locks — the measurement that answered
> how often the verdict-receipt cost is actually paid (one per adjudicated action, none on a plain
> conversational turn), written as a lock because nothing asserted the count.
> A post-merge re-run tells you only that the merge broke nothing, and it has caught a failure
> NEITHER PARENT had before.

>
> The arithmetic: 11342 + the 6 locks in `tests/integration/test_measure_coder_sustained_stamp.py`.
> It read **11347** at 20:10:01 → 20:18:04 (477.19 s) when that file carried 5 locks; it was
> rebuilt to 6 after independent review found four mutations passing clean against it, and a
> fifth — a seconds/milliseconds unit error — that only failed once the machine had been up
> more than 8.76 hours.
>
> **Separating the observed figure from the prediction is the whole point here.** An earlier
> version of this line stamped 11347 as "CONFIRMED on merged main `d483ffef`" and carried that
> run's own timings — but `d483ffef`'s run printed **11342**, and no run had printed 11347 at
> all. A number and a provenance sentence that describe different runs is the same failure this
> section already records twice, wearing a citation.
>
> The prior confirmed stamp, kept: **11342** on merged main `d483ffef` in the REAL checkout,
> 2026-08-31, **17:27:35 → 17:34:02** local, **383.45 s**, 0 failed and 0 skipped.
>
> **THE PREDICTION MISSED BY 25 AND THE MISS IS THE FINDING.** Predicted 11317 from a
> WORKTREE run; the real checkout printed **11342**, and 11317 + 2 failed + 23 skipped =
> 11342 exactly. Those 25 are worktree-depth artifacts — an ADR-013 relative link, 20
> router tests needing the real 46 GB of models rather than 6 KB of stubs, 2 docset, 1
> kv-cache sweep — and they all PASS in the real tree. **So the prior 11286 stamp was
> itself a worktree figure and understated this checkout by 25.** Both baseline surfaces
> had agreed with each other while both were wrong, which is the failure this section
> already warned about in the abstract and has now happened a third time. A worktree
> number must never be recorded here without saying so.
>
> The +31 is real: `tests/integration/test_delivery_criteria_report.py`, the 26 locks the
> #1439 branch carried since 2026-08-17 plus 5 added at merge time for the defect
> independent review found. **+31** in `tests/integration/test_delivery_criteria_report.py`
> — the 26 locks the branch carried since 2026-08-17 plus 5 added at merge time for the defect
> independent review found: c1 was decided by an INBOUND orphan audit alone, so a site got
> better at it by shipping FEWER pages. **Predicted 11317 as 11286 + 31; it printed 11317.**
> Measured in a worktree, where 2 pre-existing failures and 23 skips are depth artifacts present
> identically on pristine main — an ADR-013 relative link that resolves only from the real
> checkout, and gitignored models/docsets. The figure above is the real-checkout expectation and
> was re-measured on merged main.)*
>
> *(Per-merge stamps from 2026-08-17 and earlier are rotated to*
> [`docs/archive/test-governance-baseline-history.md`](archive/test-governance-baseline-history.md)
> *— rotated 2026-09-19 when this file reached 42,483 against its 40,000-byte budget and*
> *`test_doctrine_freshness.py` refused it. The control was not weakened to fit the text;*
> *nothing was deleted, and the retractions and corrections are there in full.)*
>
---

