---
title: Finding disposition — journal fold 2026-07-22
status: record
area: reviews
---

# Disposition — journal fold (#1057), independent review findings

**Change under review:** `docs/journal-fold-20260722` — 16 journal fragments folded into
`BUILD_JOURNAL.md`, lessons 296–300 minted, 12 recurrence tallies, lesson 156's
third-instance control shipped, one fragment deliberately held.

**Reviewers:** three independent passes, none of them the author.

- `docs/reviews/journal-fold-20260722-review.md` — full-scope, two rounds
- `docs/reviews/curation-review-20260722.md` — lesson curation only
- `docs/reviews/control-review-20260722.md` — the shipped control + execution record, two rounds

**Verdicts:** round 1 of the full-scope pass returned **DO-NOT-MERGE** on a doctrine-staleness
blocker; that blocker was fixed and all three passes ended at **MERGE**.

Every finding below was reproduced by its reviewer before being reported, and every FIXED row
names the commit that carries the fix. Two rows are REJECTED with argument rather than silently
dropped.

## Why this record exists

`<deferral_discipline>` binds any pass that returns findings. It is also the case that the
reviewers found **more real defects in my own work than I found in the fragments** — including
one where I marked a lesson as controlled in the same change that recorded an instance the
control does not cover, and one where I shipped a checking tool with the exact blind spot the
lesson I had just folded warns about. That is the value of author ≠ verifier, and it belongs in
the record rather than in a summary.

```disposition
canon32-third-surface-drift-7-of-32     | FIXED    | 53eebb1f — Rule 2 amended to name all three surfaces; cause fixed rather than symptom
lesson-46-second-tally-ordinal-wrong    | FIXED    | 944d08c3 — "SEVENTH" -> "EIGHTH" on the scheduled-task tally
stale-status-snapshot-journal-bullet    | FIXED    | 4a57e237 — battery + journal snapshot lines replaced
lesson-47-fourth-instance-gap-unfiled   | FIXED    | b854d476 — index now ctrl(partial); gap ticketed #1060 with a predicate
lesson-225-obligation-not-on-225        | FIXED    | b854d476 — PENDING-control marker + debt flag on the index line
lesson-298-runbook-claimed-as-control   | FIXED    | 53eebb1f — relabelled a mitigation; a runbook is vigilance, not structure
control-blind-to-laundered-goal         | FIXED    | b854d476 — one-hop alias tracking; mutation-proven on the laundered shape
control-blind-to-annotated-assign       | FIXED    | 53eebb1f — ast.AnnAssign handled; locked in the planted source
control-docstring-limit-inaccurate      | FIXED    | 53eebb1f — limits replaced with the reviewer's measured tracked/untracked lists
toggle-off-reimplemented-the-detector   | FIXED    | b854d476 — now drives the shipped helper via monkeypatch; negative control added
lesson-156-headline-too-narrow          | FIXED    | 944d08c3 — headline widened so the shipped control's class is findable
tally-tool-blind-to-marker-dialects     | FIXED    | 944d08c3 — counts the canonical dialect, REPORTS ordinal forms for adjudication
tally-tool-blind-to-third-surface       | FIXED    | 53eebb1f — Canon-32 headline agreement now checked
gate-figure-wrong-8780-then-8779        | FIXED    | 53eebb1f — set to the MEASURED 8780; both corrections recorded in the chain
seven-preexisting-index-tally-drifts    | DEFERRED | #1059 blocked-by: each row needs per-lesson history archaeology to say whether the archive is missing a marker or the index over-counted; the observable predicate is `python tools/doc_hygiene/check_lesson_tallies.py --strict` exiting 0 on merged main
eight-lessons-3plus-instances-no-ctrl   | DEFERRED | #1059 blocked-by: Rule 5's quarterly consolidation pass, next due 2026-10-01, which the rule already charges with verifying every third-instance lesson has its control
lesson-222-nonstandard-ctrl-marker      | DEFERRED | #1059 blocked-by: normalising the marker convention is a prerequisite to gating on it; predicate is the `*(control: …)*` form present on lesson 222 in the archive
lesson-225-third-instance-control       | DEFERRED | #1058 blocked-by: a sandbox-freshness precondition existing in `tools/dispatch_harness/battery.py` that refuses a card whose sandbox git log carries `agent:` commits, plus its toggle-off test — this control changes the battery INSTRUMENT so it must not share an attribution window with anything being measured
build-journal-duplicate-entry-1021      | DEFERRED | #1021 blocked-by: the ticket understates the defect — diagnosed as a duplicate PLUS a misordering cluster, so the scoped one-line fix would close a ticket whose real defect survives; predicate is `grep -c "Packing the house before the fire" BUILD_JOURNAL.md` returning 1 AND a monotonic date sequence
two-folded-fragments-never-tracked      | REJECTED | Both fragments' prose was verified present in BUILD_JOURNAL.md verbatim by the reviewer's own paragraph-level differ across all 151 narrative paragraphs, so nothing was lost. The risk it names is real but retrospective: git could not have recovered them had the fold dropped a paragraph, and the scratchpad copy was the only backup. Recorded as a method note for future folds rather than a defect in this one, because the outcome is verified rather than assumed.
lesson-33-tally-fits-first-clause-only  | REJECTED | Lesson 33 reads "capturing data and publishing data are two separate disciplines - and a record that implies more coverage than it has is worse than none at all". The perf-log incident is a record that was ABSENT rather than overstating, so the fit is to the first clause only. Kept as a tally rather than a mint because the standing instruction was default-to-tally, the first clause fits literally and squarely, and minting a near-duplicate of 33 would dilute the index that Rule 2 makes the pre-mint search surface. The reviewer explicitly declined to overturn it on the same reasoning.
lesson-222-subclass-obligation-buried   | REJECTED | The armed obligation on 222 is for the never-wired-instrument sub-class. The tally added by this fold is a different shape - an instrument artefact produced by an unconstrained probe, where the instrument itself was sound. The sub-class obligation is therefore not triggered and nothing is owed by this change. Recorded here because the reviewer was right that the armed note is now buried under a newer tally, and the next session to tally 222 needs to see it.
```

## Notes on two rows a later session may want to re-open

**`canon32-third-surface-drift-7-of-32` is marked FIXED, and that deserves scrutiny.** The
seven stale Canon-32 copies were **not** brought into line — the backfill was written, measured
at 3,393 bytes over the hot-file budget, and reverted. What was fixed is the *cause*: Rule 2 now
states that the Canon-32 tier carries the judgment and deliberately does not accumulate
recurrence markers, so a hot copy with fewer markers is correct by design rather than drift.
If a future session decides that reading is wrong — that the hot tier SHOULD carry the full
recurrence log — then this row reverts to an open finding and the budget question has to be
answered instead of designed around. The reasoning is written into Rule 2 itself so that
decision can be made with the measurement in hand.

**`eight-lessons-3plus-instances-no-ctrl` is deferred to a dated pass, not to a vibe.** Rule 5
already charges the quarterly consolidation (2026-10-01) with verifying every third-instance
lesson has its control, and two of the eight admit the debt in their own text. That is a real
owner and a real date. It is still a deferral of eight live Rule-3 obligations, and if the
quarterly pass slips, this row is where a later session should look first.
