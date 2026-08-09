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
