---
title: Day session report — 2026-07-22
status: record
area: governance
---

# Day session report — 2026-07-22

Written to disk rather than chat per the LA's standing instruction (2026-07-22): durable
artifacts get a path, rendering is never load-bearing.

---

## What shipped

**Six merges to `main`.** Standing gate re-measured on merged main after the one code merge:
**8735 passed / 0 failed / 0 skipped / 125 deselected** (237.81s, app down, bash runner).
Prior 8733. Doctrine pair updated in the count-changing commit; freshness gate 19 passed.

| # | Merge | What |
|---|---|---|
| `666c48d4` | perf-log-orphaned-entries | Five orphaned measurement narratives landed |
| `cfd28569` | 1005-grading-and-s1-review | The grading measurement + S1 disposition |
| `31c03495` | status-snapshot-refresh | Snapshot to the day cluster, 639 bytes paid down |
| `9d19cc9b` | **#1032 (code)** | The multi-task job exam no longer authored blind |
| `0c4c13ac` | battery-cadence-runbook | The cadence gets a documented home |

### #1032 — SHIPPED and closed

`planning_seed` (goal + clarified requirements) fed eight consumers; the multi-task
job-oracle author got the bare `goal`. So on any ≥2-task dispatch with clarified
requirements, the job-level exam — the thing the whole job is graded against — was authored
without the operator's answers **while the coder was building to them**. One-argument fix.

Independent review returned MERGE-AFTER-FIXES and found two real nits in my own tests (a
**vacuous assertion** that could never fail, and a **docstring overclaiming** what its test
proved). Both fixed. Its load-bearing evidence: reverting the argument turns the intended
lock RED and leaves **3053 other `shared/` tests indifferent**.

One downstream finding ticketed as **#1043**: the oracle-QA grounding corpus is built from
the clean `spec.goal` while the oracle is now authored from the enriched seed, so an
operator-supplied value can be convicted as an "invented return contract". Reproduced with
an isolating control. SOFT class, and the asymmetry **predates** #1032.

### #1005 — grading MEASURED, both directions

The brief said grading was "never started". **It had been run** — artifacts were sitting in
the researcher's scratchpad. Checking the owning surface first saved re-running an hour of
GPU work.

- **Gemma caught two real defects in shipped 30B battery code our 14B scored clean** —
  `KeyError` on a card missing its keys, `AttributeError` on a non-string answer. Both
  confirmed **by execution** against the real sandbox file, not by finding the reasons
  plausible.
- **The reverse also holds.** On a synthetic defective module the 14B correctly said
  `wrong` and **Gemma said `none`** — that module raises three exception classes on ordinary
  input. Each caught what the other missed, which is exactly the independence #1005 asks for.

**The caveat I measured rather than inherited:** the existing arm put our production juror at
**0/9** determinism. That would have been a wrong and alarming claim — the arm emitted
free-text JSON and production emits grammar-constrained. I added a third arm on the real
production path: **8/9 stable**, one field moving on one cell on the first call. Consequently
the 13/36 cross-model disagreement is an **upper bound, not a rate**.

### #1031 S1 — DO-NOT-MERGE

7 BLOCKERs, 3 findings, 3 nits, all 8 lines examined, 32 mutants (26 killed, 6 survived).
13 rows dispositioned, verifier PASS. Split to **#1041** (delivery-floor redesign — five
findings sharing one root cause, needing a design decision not a patch) and **#1042**
(dormancy fail-open, three untested defaults, ceremony-surface misdescription).

Nothing fixed, deliberately: branch unmerged, flag never true, nothing live, and patching
four findings around a pending redesign of the same functions churns them twice.

**The sharpest finding is not code.** `default.toml` — the artifact read AT the ceremony —
describes four capabilities S1 does not ship, including the realism guard in its *withdrawn*
form. Dormant-merge is safe only because the ceremony is an informed decision.

---

## Battery work (LA-directed mid-session)

**#1035 B1 targeted daytime run — IN FLIGHT** (`night-20260722-122749`), monitored.

The pre-launch freshness probe caught something the ticket's own plan would have walked into:
its PLAN says *"one daytime targeted run each (`--jobs B1`…) … FRESH SANDBOX per the nightly
script's archive+init pattern"*, and **the command named does not do the thing the same
sentence requires** — the archive+init block is in the wrapper, not the harness. B1's sandbox
was measured **dirty** (4 inherited `agent:` commits). Running through the wrapper archived
and re-initialised it; confirmed live in the log.

Isolation verified throughout: side config, nightly task still `Ready`, default campaign
counters unchanged at `completed_passes` 3 / `lean_passes` 3.

**New runbook:** `docs/runbooks/battery_cadence_and_targeted_runs.md` — the 23:00 anchor, the
one-change-per-RUN rule, the correct invocation, and three launch gotchas that each cost a
failed launch today (`powershell.exe` vs `pwsh.exe`; a side config must carry `end_date`; the
2026-07-09 template's pre-satisfied counters exit immediately).

---

## Tickets opened (7)

| # | What |
|---|---|
| #1039 | Battery-card clarify suppression covers 3 of 8 cards — measurement integrity, NOT a stall |
| #1040 | Performance-capture gate: a committed JSON must have a same-dated narrative (5 instances) |
| #1041 | S1 delivery-floor redesign |
| #1042 | S1 dormancy + spec-integrity blockers |
| #1043 | Oracle-QA corpus/author asymmetry |
| #1044 | **The job exam certifies GREEN with zero bad-input coverage** (LA-asked) |
| #1045 | `run-battery-night.ps1` side-config `end_date` throws under pwsh |

---

## Corrections to the record

Four inherited claims were wrong, plus two of my own:

1. **"Four docs merges landed today"** (brief, twice) — actually 11 merges. Corrected in the brief.
2. **"Grading has never been measured"** (brief) — it had been, that morning. Corrected in the brief.
3. **"`report.asked_requirements` makes it observable"** (my own #1039 description) — it does
   not. Not in the scorecard, and `battery-runner.log` is the *wrapper's* transcript, not the
   harness's. Corrected on the ticket; searching 185 runs and finding nothing is **not**
   evidence it never fired.
4. **"Six docs merges today"** (mine, inherited from the brief without checking) — recounted.
5. **A vacuous assertion and an overclaiming docstring** in my own #1032 tests — found by the
   independent reviewer, both fixed.
6. **`run-battery-night.ps1` looked corrupted** — it is not; I used the wrong interpreter.

---

## Not done, and why

- **#1036, #969** — battery-path changes, each needs its own attribution window; B1 owns
  today's.
- **#746** — multi-day build; recorded on the ticket with two observable predicates.
- **#855** — sized on the ticket (the eval suite is BUILT, 83 cases; only the precision report
  remains) with the artifact itself as the watchable predicate.
- **Journal fold** — still blocked on lesson 225's third-instance control. 12 fragments now,
  all dispositioned, with an addendum naming the two that may also be third instances.
