---
title: Coder DoD - the completion map (measured 2026-08-14)
status: measured-snapshot
area: design
owner: Claude sessions (the measurement); Lead Architect (the decisions it names)
---

> **What this is.** A measurement of every row of `CODER_DEFINITION_OF_DONE.md` against what is
> actually on disk, taken 2026-08-14 by three parallel passes plus a synthesis. It exists because
> the standing goal became *complete the coder per the DoD*, and that is not plannable until
> someone says how far away it is.
>
> **It is a SNAPSHOT, not doctrine.** The DoD itself remains the authority; where this document
> and a DoD row disagree, that disagreement is the finding (see section 6 - fourteen rows
> misstate the repo in one direction or the other). Statuses in the DoD change only by
> measurement with the measurement cited, so this map is INPUT to those corrections, not a
> substitute for them.
>
> **Do not trust its numbers after a night runs.** Every 'tonight?' column and every denominator
> is relative to 2026-08-14 18:00, before the first battery night in six.

---

# THE COMPLETION MAP — BlarAI Coder Definition of Done
Synthesised 2026-08-14 from three measurement passes. No re-measurement. Read-only.

---

## 1. THE SCOREBOARD

Gap class: **A**=absent (nothing built) · **U**=unwired (exists, nothing calls/reads it) · **S**=starved (built + wired, no run reaches it) · **O**=needs the operator · **X**=stale (stated status ≠ disk).

| # | Row | Stated status | True gap class | Tonight? |
|---|---|---|---|---|
| 1 | Builds what was asked | LIVE | X (LIVE by replay, never a natural trigger) | N |
| 2 | Advanced intake / interview | ARMED | **O** + X (sweep ¶ falsified) | N |
| 3 | Secure Python + secure websites | LIVE | **S** + X (both directions) | only if GREEN |
| 4 | Exams must be able to fail | PARTIAL | **X** (headline false) + U (`unexecuted_property`) + A (web) | partial |
| 5 | Proper reviewers | ARMED | **X → should read LIVE** | N |
| 6 | A local corpus | PARTIAL | **U→unreached** (armed 157×, 0 lookups) | partial (informative null) |
| 7 | Every number means what it says | PARTIAL | S + X (undersold) | partial |
| 8 | Finishes across MANY runs | PARTIAL | X (within-run) + **A** (cross-run resume) + **O** | partial |
| 9 | He can SEE and USE it | PARTIAL | X + **A** (review→next-run consumer) + O | partial |
| 10 | Product carries its own content | PARTIAL | **X** (PLANNED is false) + O | N |
| 11 | No LIVE without an executed observable | PARTIAL | **A** (pipeline-wide half) | N |
| 12 | False-negative rate measured | PARTIAL | **A** + X + O | only with him |
| 13 | The graders are graded | PARTIAL (2/15) | **A** ×13 | N |
| 14 | Every gate proven to fail | PARTIAL | **A** (canary cadence) + S + X | partial (denominators) |
| 15 | Product EXERCISED not inspected | PARTIAL | S + **U** (per-page fields unread) + **A** (forms/width/keyboard/SR) + X | **Y** |
| 16 | Measurements reproducible | PARTIAL | **A** (general property) | N |
| 17 | Exam covers what was ASKED | ARMED | **X (worst in doc)** + A (node early-return) | partial |
| 18 | Media generated, placed, graded | PARTIAL | S + **O** (intake) | partial |
| 19 | Candidates scale with difficulty | PARTIAL | **A** (recording) + no `complex` data | N |
| 20 | Decomposition graded | PARTIAL | **A** (cl. 1–2) + S (cl. 3: 61/61 zero) | N |
| 21 | Verdicts are stable | PARTIAL | **A** | marginal |
| AT‑1 | Acceptance test 1 | NEVER | **O** | N |
| AT‑2 | Acceptance test 2 | NEVER + not executable | **O** (decision) | N (adds a data point *against*) |

---

## 2. WHAT TONIGHT CAN MOVE — the morning checklist

New run dir: `C:/Users/mrbla/agentic-setup/state/fleet-runs/<newest>/`; night dir `state/battery/night-<stamp>/`.

**GATE 0 — did anything bank?** `<run>/scorecard.json` exists?
- **No** → 4th consecutive night of zero instrument readings. Every check below is void; the answer for rows 3/4/7/14/15/17/18 is "starved again" and the queue in §4 becomes the only path.
- **Yes** → continue.

| Check | File → field | Meaning |
|---|---|---|
| **Row 15 / 14 — the front door** | `link-lint.json` (3rd ever) → `entry-reaches-nothing` | Present as HIGH = the placeholder-front-door class convicted in production for the first time. Absent + clean = `e6047c4`'s web brief reached all seven tasks and the front door is real. **File missing = wave-final floor not reached; rows 15+18 unmoved.** |
| **Row 15 — every page** | `exec-smoke-web.png.console.json` → `pagesRequested` vs `pagesVisited`, per-page `errorText` | First production run of the multi-page walk. Any per-page error here is **invisible to the graders** — nothing reads these fields. Read them by eye; each one is a row-12 escaped defect. |
| **Row 4 — exam can fail** | `oracle-qa.json` → `f2p_baseline` | `all-fail` = 9th consecutive node re-execution, now on the post-`842d7d41` instrument (satisfies row 11's re-vouch). `not-run` = today's #1350 change regressed it. |
| **Row 7 item 5** | `oracle-qa.json` → `stages.coverage_map`, `oracle_coverage` | **Expect `false` / `unknown`, and that is NOT news.** Pass 3 proves `validate_authored_oracle` returns for non-python at `oracle_qa.py:1700-1704`, 30 lines before the #1374 gate. B9 is node. Pass 1's "first chance for the map to emit" is refuted by the 08-11 run, which had `b3a7ecd7` in tree and still stamped unknown. |
| **Row 17 — the real coverage signal** | `traceability.json` → `available`, `denominator`, `undecidable`, `verified_class` | This is the artifact that can move, via `battery.py:2084` at battery close. `available:true` = a banked coverage figure. `verified_class:false` with `undecidable>0` = the blocking clause executing again (already proven 10×). |
| **Rows 3 + 4 — the GREEN gate** | `<run>/scorecard.json` → `verdict` | **GREEN** = `green-quality.json` security block + `oracle-mutation.json` fire for the first time in 13 nights (last GREEN 2026‑08‑07 19:53). **Not GREEN** = rows 3 and 4 stay starved by that one gate, whatever else succeeded. |
| **Row 6 — the corpus** | `state/research-usage.jsonl` → `search_docs_cli` with non-empty `fleet_task`, vs `[research-docs] ARMED` banner count in `run-fleet-*.log` | Any hit = observable met. Another 0 against ~157+ armed spawns = stop calling it "hasn't come up"; it is evidence the web hint's *"ACT FIRST … do NOT spend turns reading"* suppresses the lookup. That hint reaches 7 tasks tonight instead of 1 — the cleanest test yet. |
| **Row 8 — within-run** | `SUMMARY.txt` (park language, branch name) + `RUN-START` / `resume_done` counters in `run-fleet-*.log` | 3rd instance of honest park + within-run continuation. |
| **Row 8/15 — bounded work kept** | per-task logs → `visual FIX #n applied + re-merged` vs `not applied: … FAILED the verify gate` | First night after `0e0bda9`. Any "applied + re-merged" = the loop's repairs can now land (previously 24 of 35 deleted on a time bound). |
| **Row 14 — the unread alarm** | `state/plugin-canary-failed.txt` → new lines dated 08-15 | Third night of a canary firing into a file with no reader. This is row 14's own failure mode in uniform. |
| **Row 20** | `state/battery/night-<stamp>/scorecards/battery-summary.json` → `DECOMPOSE-DOWNGRADE` | Expect `0` (62nd). Add to capability 14's never-fired candidate list. |
| **Rows 9 + 12** | `state/battery/MORNING-REPORT.md` → the served URL | Hand it to him. His click-through is the only ground truth row 12 is defined on. |

**Perishable, 23:00 tonight:** the two parked branches in `C:/Users/mrbla/projects/battery-b9-pottery-site` (`agent/implement-header-menu` @ `28ac9d7`, `agent/integrate-styles`) are the **only surviving parked artifacts in the system** and the sole substrate for demonstrating cross-run resume. They are renamed into `night-<stamp>/repos-archived` (recoverable, off the live path).

---

## 3. THE OPERATOR'S CRITICAL PATH

One sitting for the four decisions, then the read, then the twenty minutes. Ordered so nothing is asked twice.

**Sitting 1 — four questions, answerable in one go:**

1. *"Each night the website job starts from an empty folder. Do you want it to keep doing that — so each night is a fair test of how good one attempt is — or start from last night's site and improve it, so it can actually finish? It can't do both."*
   **BLOCKS: row 8 (cross-run half), AT‑2, row 12's convergence data.** Tonight is attempt 18 from scratch.
2. *"For one night, should the nightly job build a small Python program instead of the website? Several of our safety checks only work on Python, and they haven't been able to run for a week."*
   **BLOCKS: row 4 (Python half), row 5's re-proof, row 3's mutation audit, #1200.**
3. *"Right now the planner can only ever break your website into eight steps. Should I lift that limit, knowing a bigger plan means a longer night and more chances to stop partway?"*
   **BLOCKS: row 20 clause 1.**
4. *"When a check honestly says 'I couldn't tell', should that stop a delivery from being marked as passing — or just be noted?"*
   **BLOCKS: row 17's last open clause.**

**Then 5.** *"Read the interview questions I've prepared and tell me whether they sound like something you'd want to be asked — including the one about which of your own photographs the site should use."*
**BLOCKS: rows 2, 10, 18 (intake), and AT‑1 depends on it landing.** This is the single widest block in the document.

**Then 6.** *"When you have twenty minutes, type an advanced dispatch into the assistant, answer the questions in your own words — including 'I don't know' wherever you mean it — and press Approve & build, then leave it alone and tell me in the morning whether what came back is what you asked for."*
**EXECUTES: AT‑1, rows 2 and 10 and 18's intake clauses, and gives row 1 its first natural trigger (1 assumed-clarification record in 223, from the run that caused the bug).**

**Standing, every morning it delivers.** *"Open the link at the top of the report, click every page, and when the review window asks, type what's wrong in your own words — that saved sentence is the only thing that can move two of these rows."*
**FEEDS: rows 9 and 12.** Note: on 08‑10 he did this twice and **nothing was saved** — fix the capture (§4 item 2) before asking again, or his time evaporates a third time.

---

## 4. THE ENGINEERING QUEUE

Ranked by (rows unblocked) × (verifiable without a night). ⚠ = do not merge before 23:00 — `Sync-MeasuredTree` advances the measured tree to `main`, so anything landed today runs unattended tonight.

| # | Work | Rows | Night needed? | First step |
|---|---|---|---|---|
| 1 | **Correct the stale rows** (§6) + comment #1374, #1350, #1367 | 11 rows | No | One correction commit to `docs/design/CODER_DEFINITION_OF_DONE.md`; re-run `tests/security/test_coder_dod_grammar.py`. Free. |
| 2 | **Fix the operator-review capture** — `scripts/review-website.ps1:52` wrote 1 record for 3 sessions | 9, 12 | No | Drive `Review Website.cmd` end-to-end and assert a JSON lands per session. Do this *before* asking him to click again. |
| 3 | **Build the escaped-defect counter** — `state/operator-reviews/*.json` has one writer, zero readers | 12, 14 | No (backfill 3 deliveries) | Join review records to that run's gate artifacts; attribute each defect to the gate that should have convicted; publish numerator/denominator. |
| 4 | **Row 17: lift the node early-return** at `oracle_qa.py:1700-1704` so coverage runs on a website | 17, 7 | No (fixture) ⚠ | Compute `test_criteria` before the ecosystem return; toggle-test both ecosystems. **⚠ changes a grading path the night reads.** |
| 5 | **Row 15: read the per-page fields** into the verdict (`pagesVisited`/`errorText` written, never read) | 15, 12 | No (fixture) ⚠ | Extend `_web_console_error_lines`; land **advisory-first** so a per-page error cannot flip a band unattended. |
| 6 | **Row 4/#1199: pass `-StatsPath`/`-RequireProperty`** at `new-agent-task.ps1:617,729` | 4 | No ⚠ | Predicate is self-contained; **⚠ adds a HARD finding class that can park runs** — land after tonight. |
| 7 | **Row 19: bank the resolved pass budget** (`Resolve-PassBudget` output is dropped) | 19 | No | Emit `{Build;Review}` into the run record at `new-agent-task.ps1:293`. Note: 211 records, **zero `complex`** — banking is necessary but not sufficient. |
| 8 | **Row 20 cl. 2: thread the dropped-task count** out of `_ruler` into `decompose-diagnostics.json` | 20 | No | The `break` at `decompose.py:1101` and its 15-line comment name the work. |
| 9 | **Row 14: consume `plugin-canary-failed.txt`** — a canary firing into an unread file | 14 | No | Make the canary fail the pass, not a text file. Check whether it is ticketed (open thread). |
| 10 | **Row 16: third reproducibility control** (computed paths / env-reached mutable state) | 16 | No | Cheapest row in the document to close; zero measurement dependency. |
| 11 | **Row 14: the planted-defect CANARY** through the real pipeline | 14, + negative controls for 3/4/15/17 | No (it *is* the run) | Highest structural value in the queue. Plant credential + injection sink + broken href + placeholder front door + vacuous exam; assert each gate convicts. |
| 12 | **Row 13: external reconciliation** for the remaining 13 of 15 instruments | 13 | No | One instrument at a time; the two locked ones (#1231, #1324) are the pattern. This is the long tail. |
| 13 | **Row 8: the resume consumer** — `coord_redispatch` execute seam ("nothing calls this today") + a battery resume mode | 8, AT‑2 | No | **Blocked on operator decision 1.** |
| 14 | **Row 15: forms / phone width / keyboard / screen reader** | 15 | No | Nothing exists (`layout_lint` is WinUI XAML). Offline axe-core in the capture path. |
| 15 | **Row 11: pipeline-wide vouching check** — or decide the row is scoped to this document (technical call, mine) | 11 | No | Grammar gate covers one file; ledger/tickets/runbooks publish status unchecked. |
| 16 | **Row 21: model-driven flake harness** on an immutable archived subject | 21 | GPU time | The 0/30 measured deterministic modules — "chosen for being cheap, not for being where the risk is." |
| 17 | Row 3: node/web **craft** seed (`seed_root` points at a Python reference on a node repo) | 3 | No | Security leg is proven on web; craft leg is not. |
| 18 | Row 6: stale `research_docs_note` says DORMANT while the key reads `true` | 6 | No | Ticket + one-line fix. |

---

## 5. THE HONEST DISTANCE

**Genuinely LIVE today: 2 of 21.** Row 5 (once corrected — withdrawal observed in production, deciding instrument unchanged) and row 1 (LIVE by replay through the real coordinator; the natural trigger has fired once in 223 records, and that was the bug). Row 3's *security* leg and row 7's *honesty* output are executing in production but each row has an unexecuted clause, so neither is LIVE.

**After ONE good night: still 2.** A perfect B9 night does not promote a single row to LIVE. It moves **denominators**: a 3rd/4th `link-lint.json` and `image-placement.json`, a 9th f2p re-execution, a banked `traceability.json`, and — only if it also scores GREEN, which has not happened in 13 nights — the first security and mutation audits since 08‑07. That is real progress and it is not completion.

**Rows whose work has not started: 11** — 8 (resume), 9/12 (the review consumer and the counter), 11 (pipeline-wide), 13 (13 of 15 instruments), 14 (canary cadence), 15 (forms/width/keyboard/screen-reader), 16 (general property), 19 (recording), 20 (clauses 1–2), 21 (model flake).

**Plainly: completing the coder is 8–12 weeks of engineering, and that estimate is optimistic for a reason that is not engineering.**

**The longest pole is not code — it is night completion.** The wave-final floor has been reached **twice in six days**, three consecutive nights banked nothing, and the last GREEN was 2026‑08‑07. Eight rows (3, 4, 7, 14, 15, 17, 18, 20) can only be closed by artifacts a completing night produces. At two nights in six, those eight rows accumulate evidence at roughly a third of the rate the queue assumes. Fixing throughput — the web brief (`e6047c4`), the bounded-work fix (`0e0bda9`), the archive guard (`d0bfe43`) all landed in the last four days — is worth more than any single row on the queue.

**The longest pole no run can shorten is capability 13:** 13 of 15 instruments have no external check on their own arithmetic, and each needs its own reconciliation built by hand. That work scales with the instrument count, is invisible to every night, and is what stands between "the graders say we passed" and "we know the graders are right."

**One structural fact worth stating to the LA in plain language:** two of the coder's exam checks and the reviewer's withdrawal trigger are **Python-only by construction**, and the battery has run only a website card since 08‑07. On his declared priority surface, three of the system's sharpest checks cannot fire at all. That is a cadence decision, not a defect.

---

## 6. STALE ROWS — free wins

| Row | Correction | Evidence |
|---|---|---|
| **17** | **Worst in the document.** Two of three DONE clauses are already met. "No coverage artifact of any name" is false; "the map was skipped on every run" is false; the UNDECIDABLE-blocks-GREEN clause is implemented *and* demonstrated 10×. Only "a `GREEN-VERIFIED` ever stamped" is open. | `20260810-012417-bd/traceability.json` (3,860 B, `available:true`, `undecidable:5`, `verified_class:false`) — **#1374's description enumerates that directory and omits this file while naming ten others.** `oracle_coverage` = `7/8` on 4 runs, `0/6` on 10. |
| **5** | ARMED → **LIVE**, with a named blind spot (Python-only trigger, n=1). | `20260805-000122-bd/run-fleet-store-cards.log:19` *"the green-gate review SKIP was WITHDRAWN"*; `coder_test_qa.py` unchanged since 08‑01. |
| **4** | *"81 of 81 carry `f2p_baseline: not-run`"* is retired. Rewrite: **node working since 08‑09 (8 consecutive `all-fail`); Python 63 of 63 still not-run.** The claim that #1342 "did not make the baseline start working" was falsified by the very next run. | 89-record sweep: 81 not-run / 8 all-fail, `20260809-140620-bd` onward. |
| **10** | *"Nothing in the intake asks what the site should SAY"* is false. | `AXIS_CONTENT` at `clarify.py:63`, in `INTAKE_AXES_ORDER`, shipped `b375286c` 2026‑07‑29 — **11 days before the row measured it as PLANNED**. |
| **2** | Sweep ¶ has two false clauses: the schema *does* express clarifications, and an axes-tagged one exists. | 113 of 223 `acceptance.json` carry `clarifications`; `20260808-104536-bd` carries all eight axes with his verbatim "I don't know". Still true: `operator_assets` in 0 of 223. |
| **15** | #1370 is **fixed** (`0e0bda9`, 08‑10) — the row's longest passage describes a repaired defect. #1367's cause fixed today (`e6047c4` + `2238a1d`): the web brief reached only the seeding task; exactly one banked agent log in the corpus contains "OFFLINE WEB BUILD". | Commit bodies; `verify-critique-loop.ps1` 345 passed incl. VF5c. |
| **9** | *"No path for his judgment to become the next change"* is false as written — the plan-time channel exists and has fired with his real words. The true gap is that the **post-delivery** record has one writer and zero readers. | `dispatch_coordinator.py:2227`, `acceptance.py:353`; `20260712-155713-bd` carries three of his change requests. |
| **8** | Understates itself by a full run: the 08‑11 night repeats honest park + within-run resume, and #1370's judge-don't-delete executed in production (8 of 9 visual fixes applied and re-merged; the 9th was withheld because **the rebuilt app FAILED the verify gate** — a build-verification failure, NOT a merit judgement, corrected 2026-08-14 after an independent verifier read the log line I had paraphrased). | `20260811-232102-bd/SUMMARY.txt`; `create-piece-list-page.log:58`. |
| **3** | Undersells: its own observable **has** executed on a real web delivery (band C refused on a node-web site, two high `unescaped-html-sink` findings). Oversells: "144 real deliveries" is a reviewer's one-off archive sweep, not production — the production corpus is **7** records with a security block. | `20260807-195617-bd/green-quality.json`; disposition doc 2026‑07‑30 line 31. |
| **7** | Undersells eight consecutive runs of live measurement-honesty output. **TRAP:** the eight `collectability: "confirmed"` stamps are **node** and do **not** vouch #1200, a Python/uv defect — Python is 63-for-63 `unconfirmed`, last Python run 08‑06, before the fix merged. | 89-record sweep; `oracle_qa.py::_qa_env`. |
| **12** | "One delivery reviewed" → **~3 reviewed, ≥6 escaped defects** (#1367, #1370, #1375), none of them in the review schema. | `state/operator-reviews/` holds exactly one record; the 08‑10 sessions saved nothing. |
| **14** | Sweep denominators superseded (89/69/105/11/2/2/0); the Python registry structurally cannot see `.mjs`/`.ps1` at all — `importlib.import_module` has nothing to resolve — though CORRECTED 2026-08-14: those two scripts are NOT new (`capture-app.ps1` 2026-06-25 `6c4341c`, `capture-web-cdp.mjs` 2026-07-11 `ffac288`); today added a feature to them, deliberately advisory-only, so the blind spot is pre-existing rather than newly introduced; and **the #762 plugin canary fired 18 times across 6 logs on 08‑10/08‑11 into a file nobody reads** — `command-timeout` not loaded on the visual-fix passes. | `state/plugin-canary-failed.txt`; `capture-web-cdp.mjs` / `capture-app.ps1`. |
| **13** | Denominator grew: **15 instruments, 2 externally locked, 13 UNKNOWN.** #1342/#1350's honesty work is computed *inside* `oracle_qa` — self-verification, not a third lock. | `shared/instrument_registry.py`. |
| **20** | New evidence for its own "ARMED not exercised": **`DECOMPOSE-DOWNGRADE` = 0 across 61 battery nights.** Belongs on capability 14's never-fired candidate list beside `import-probe-verdict` (0/68). | `battery-summary.json` sweep. |
| **AT‑1** | Status date 2026‑08‑07 predates the 08‑08 attempt (`20260808-104536-bd`, delivered **3 of 8** — corrected 2026-08-14 from 3 of 9 — then STALLED on a HARNESS attribution) — the closest this test has come. Restamp. **Note the restamp argument is about a stale evidence trail, not about NEVER becoming false:** the run stalled, so `Executed: NEVER` remains literally true. | Run-directory provenance sweep. |

---

## 7. CORRECTIONS TO THIS MAP — same day, from re-measurement

This map was written from a fast pass and then used to drive a row-by-row audit against disk. The audit disproved three of its own claims. They are corrected here rather than left standing, because the map is what a later session would act on.

| § | This map said | Measured |
|---|---|---|
| §6 row 3 | *"band C **refused** on a node-web site"* and *"the production corpus is **7** records with a security block"* | The band-C record is real (`20260807-195617-bd`, `surface: node-web`, `unescaped-html-sink` high at `public/app.js:25`, 26 files scanned) — but it carries **`advisory: true`** and `mode: det-only`. It **graded**, it did not refuse. Across all **44** production `green-quality.json`, **zero** carry a security block. Bands are B=38, A=5, C=1. "Refused" credits the control with stopping power it does not have and was not built to have. |
| §6 row 20 / row 14 | *"`import-probe-verdict` (0/68)"* — on the never-fired candidate list | **69 records, 11 with `ok: false`**, each naming real unresolved modules (`app.word_frequencies`, `flashcard_app`, `app.card_entry`, `app.quiz_engine`, `app.score_tracker`), spanning 2026-07-12 to 08-05. It fires. It was removed from capability 14's candidate list. |
| queue item 2 | *"`review-website.ps1:52` wrote 1 record for 3 sessions"* — a capture bug to fix before asking him to click again | **Not a bug.** The prompt explicitly offers *"(Or just press Enter now if you would rather look first and come back.)"*, and the one record's own `capture_note` says it was *"Recorded from chat rather than the script's prompt."* There are **8** session directories and **1** record; nothing was lost. The real gap is that his findings arrive by conversation (#1345, #1367, #1375) and the row-12 counter must read both paths. |

Confirmed unchanged by the same audit: `DECOMPOSE-DOWNGRADE` = **0** across all 63 `battery-summary.json` carrying the field; `decompose-diagnostics` = 105 with `degraded:false` in all 105; `oracle-flake` = 11, all `confirmed`; `operator_assets` = 0 of 223; the instrument registry is **15**.

**Why this section exists.** Every figure in §6 that survived is one I re-derived, and every figure that did not is above. A map built to correct a document is not exempt from the standard it is applying — and two of the three errors above are the same shape the map was written to catch: a verb or a denominator asserted from the nearest available evidence rather than measured.
