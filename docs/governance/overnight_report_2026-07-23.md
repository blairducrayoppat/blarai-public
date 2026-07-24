# Overnight report — night of 2026-07-22 → 23

Good morning. The night delivered everything queued and measured what could honestly be
measured. Nothing needs urgent attention; three things wait for your judgment when you're
ready (at the end).

## The battery, and your faster-cycle direction in action

The 23:00 nightly fired on schedule and banked cleanly: **B2 GREEN** (4,170 s — 13% faster
than the previous night), **B4 parked honestly** at the integration seam. The scheduled task
re-armed itself for tonight (verified: Ready, next run 23:00, last result 0), and the campaign
counters are untouched.

Per your before-bed direction — one change per RUN, not per day — I then chained **three
targeted runs** through the rest of the night, each with a side config, each measuring exactly
one change:

1. **Validation run: GREEN.** The new sandbox-freshness gate's first wrapper-path pass,
   condition recorded into the scorecard both directions (a separate live test proved the real
   command REFUSES a dirty sandbox at zero seconds spent).
2. **#1049 window: banked.** The wave-retry honesty change interfered with nothing; its
   honest-skip occasions didn't arise this run, so its locks remain the standing evidence.
3. **Scaffold window: banked.** Same result — non-interference proven; the "is our dead seed
   code gone from the quality readings" question honestly waits for B4's next GREEN run,
   because forcing a reading would be the score-gaming you rejected on the ticket.

**The night's sharpest finding:** B4 parked **three consecutive runs on the same three
unresolved contract modules, across three different code versions**. Tonight's changes are
provably not the cause (the failure is byte-identical before and after each). One of the coder's
build steps stopped delivering three of the five parts the job asked for, and that wants a
daylight look.

> **Correction added 2026-07-23 morning (the explanation above was wrong when this report was
> written).** The original sentence read: *"Something in how the model authors B4's plan flipped
> at the 07-22 nightly — the module names it demands changed …"* **That is retracted.** The plan
> did not change at all: the job asks for the same five parts, in the same six steps, on the good
> nights and the bad ones — I had compared two different lists and mistaken them for the same
> kind of thing. What actually changed is that one build step ("add-card") now finishes having
> produced nothing, the steps waiting on it are skipped, and three parts never get built. Worse,
> when the repair pass tried to re-run that step, the machinery refused it as "already processed
> in this run" — a safeguard against duplicate work is blocking the repair. Both are now under
> investigation as #1066. Nothing else in this report is affected; the measurements were right,
> only my explanation of them was wrong.

## What shipped to main (all independently reviewed; gate walked 8780 → 8852, every step measured)

1. **#855's precision report + verified corrections** — the coordinator's *decisions* are now
   14/14 across both graded windows. Its *words* have their first live record: the guard missed
   the one real false statement ("acceptance tests passed" on a run whose exam failed) and its
   only firing was a false alarm on an accurate sentence. The miss is fixed and locked as
   permanent golden cases; the false-alarm bias is deliberately kept and priced (~3% of
   cycles) — loosening it is your ceremony call.
2. **#1021** — the journal's duplicate entry deleted, TWO misplaced entries reseated (one the
   diagnosis never saw — consecutive misplacements hide each other from simple checks), and a
   chronology gate now guards the file. It caught its first real mistake — mine — within
   minutes of merging.
3. **#1059** — the seven "drifted" lesson tallies reconciled by archaeology: six flags were
   RIGHT (the archive was owed its markers), one was a real over-count. The checker is now a
   standing gate; it too caught a mistake of mine the same hour it merged.
4. **#1060** — every go-live flag in both config files (19 ceremony flags, including the
   guest-parser weld) now carries a machine-checked declaration of what it actually enables.
   The comment you read at a ceremony can no longer promise capabilities the code doesn't
   contain. Review found a fail-open inside the first version of this very control; fixed with
   planted locks.
5. **#1058** — the battery refuses to spend the GPU on a used sandbox, live-verified in both
   directions; the one escape hatch can only waive a condition that was observed and recorded.
   This discharged the oldest outstanding lesson-control debt (lesson 225's third instance).
6. **#1049** — the coder fleet can now say "the work is already done" honestly: an oracle-backed
   pre-check skips satisfied waves without spending the model, and "NO CHANGE NEEDED" is a
   legal retry answer — because the measured alternative was the machinery manufacturing junk
   diffs that merged.
7. **#1036 + #1048 + companion** — the scaffold seed is neutral (nothing we seed ships dead
   anymore), seeded tests demonstrate the isolation pattern, and the dispatch prompts no longer
   assert a starter module that no longer exists (a stale premise the review caught before it
   could ship).

Journal: every fragment folded, lessons **296–307** on the books, the fold-plan retired.
Board: #1021, #1036, #1048, #1049, #1058, #1059, #1060 closed citing their shipping commits;
#855 stays open for your ceremony.

## Decisions I made (technical, reversible, yours to know)

- Fixed only the guard's tighten-direction defect; preserved the loosen-direction trade-off
  for your ceremony, with a measured price tag.
- Serialized every heavy test run behind the battery to keep baseline walls clean (one overlap
  slipped through early — noted honestly in B4's ledger row; the verdict is load-independent).
- Compressed branch-side full gates into per-merge merged-main gates (each branch carried
  targeted suites + independent review). The one failure this could have hidden was caught by
  exactly the merged-main re-run the doctrine mandates — a pre-existing test that pinned a
  retired module name; re-pinned to the intent and re-measured green.

## Faults fixed without waking you

Two broken battery watchers (replaced with file-keyed monitoring); a false "task stopped"
alarm and a false "run quiet" alarm (both measured against artifacts and dismissed); two
stranded 10–12 GB assistant processes after manual runs (the known #1053 class — stopped
through the audited seam both times); a stale prompt premise caught by review; my own
archive-format slip and a doctrine-file budget overrun — each caught by a gate that shipped
tonight, which is the system working.

## Waiting on YOU (no action taken)

> **Status update, later on 2026-07-23: you have since decided items 1 and 2.** They are left
> below as written — this is a dated morning report, not a live board — but do not read them as
> still open. Item 1: you **HELD** graduation; shadow mode stays on, and the path is #1067
> (fixing the guard's word layer) then #1068 (graduation criteria you ratify before the next
> measurement window). Item 2: you chose to build S3 as **one program slice** (#1069), with the
> four exam tickets closing into it rather than being patched one at a time. Item 3 is still
> open. The live queue is the board, not this file.

1. **#855 graduation ceremony** — the report is on main, independently verified, with priced
   options (extend the guarded shadow window with a pre-specified threshold, or graduate
   actions-only while words stay shadowed). The action side has earned it; the words have not.
2. **The exam-authoring thesis** — #1044 (exams lack bad-input coverage) and #1043/#1054
   (exams over-specify) look like two faces of one root cause in how the 14B authors exams;
   tonight's B4 park may or may not belong with them — the corrected diagnosis (see the
   correction above) puts it in the build/repair machinery, not in exam authoring, so it joins
   this group only if the root cause lands there. Whether to solve that
   wholesale as advanced-intake S3 or patch ticket-by-ticket is your scoping decision. The
   four exam tickets sit unbuilt on the board, deliberately.
3. **Coordinator headline granularity** (small, ceremony-day): the deterministic headline
   renders "all merged, exam failed" as "run did not complete" — truthful but coarse.

## Residuals, each with a real predicate

- Scaffold band-B readout: B4's next GREEN under the neutral seed.
- #1036 prompt-hint: builds only if interactive-I/O parks persist (they have not — tonight's
  parks are a different class).
- Harvest-ordering anomaly + the B4 park diagnosis (#1066): daylight diagnostics, evidence recorded.
- wave_share.py evidence tooling [PROPOSED, inherited from the fold-plan]: land as a shared
  instrument when convenient.

Everything is recorded where it lives: ledger rows for all five runs, PERFORMANCE_LOG +
machine-readable JSON for the precision measurement, journal entries for every ship, the
board current, and a fresh handoff brief for the next session.
