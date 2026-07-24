---
title: Finding disposition — #1079 coordinator graduation grading tool
status: record
area: reviews
---

# Disposition — #1079 grading instrument, independent review findings

**Change under review:** branch `feat/1079-graduation-grading-tool` — the committed
coordinator graduation grading instrument (`shared/grading/`), the `work_state.py`
derivation promotion, and the first live-window report artifact.

**Reviewer:** independent, not the author. **Verdict: MERGE-AFTER-FIXES**, two blockers.

Both decisive items passed under adversarial verification rather than inspection: the
`work_state.py` refactor was driven over 134 scorecard shapes (both writer shapes, all 72
status/result precedence combinations, every `None`-returning case, 27 multi-task mixes,
the `NOTHING` cause token) with zero mismatches; and the positive control was re-verified
with four disconnection mutants, all of which turned it RED.

## Why this record exists

`<deferral_discipline>` binds any pass that returns findings. Worth recording beyond the
rows: **F1 is a case of the author applying his own documented principle inconsistently.**
`DecisionGrade.correct` already stated that a decision whose inputs are unrecoverable is
never counted correct by default, and the tool correctly abstained for stalls and
tripwires on exactly that ground — then asserted INCORRECT for a superseded board move
whose inputs are equally unrecoverable. The reviewer caught a contradiction between the
code and its own docstring, which is the class of defect an author is least able to see.

**F2 is a process finding as much as a technical one.** The report artifact was committed
at `e6edd854`; `b013799a` then changed the fingerprint algorithm and silently invalidated
the artifact's own provenance field. The review was running against a moving tree at the
time. Landing all remaining fixes as ONE commit is the corrective.

**On the evidence form below:** every FIXED row cites the branch ref rather than a SHA,
because all seven fixes land in a single commit whose SHA cannot be known while writing
the record it contains. The branch tip is the artifact; the shipping SHA is reported on
#1079 and in the merge motion.

The rows also deliberately carry **no bare hex tokens**. Writing the regenerated guard
fingerprint (`d26ba354f25f861b`, 16 hex characters) into an evidence cell made
`test_fixed_rows_cite_shas_that_actually_resolve` fail: it pattern-matches as a SHA, and a
non-resolving SHA is precisely the "claim that looks like evidence" shape that gate
exists to catch. The gate was right — the fingerprint belongs in prose like this, not in
a column a reader would parse as a commit.

```disposition
F1-superseded-board-move-scored-incorrect | FIXED    | feat/1079-graduation-grading-tool — only a run's chronologically last decision is graded; earlier ones abstain as SUPERSEDED with correct=None; regression lock test_superseded_board_move_abstains_rather_than_scoring_incorrect
F2-report-fingerprint-no-longer-reproduces | FIXED   | feat/1079-graduation-grading-tool — report REGENERATED from the live journal (not hand-edited); the stamped guard fingerprint now equals the recomputed value, verified after regeneration
F3-report-carries-no-provenance-block     | FIXED    | feat/1079-graduation-grading-tool — Provenance dataclass on the report (journal path, runs-dir, since-seq, since, dev_mode) rendered in text + JSON; wall-clock kept in the CLI envelope so the determinism contract holds
F4-perflog-entry-and-baseline-sync-missing | FIXED   | feat/1079-graduation-grading-tool — PERFORMANCE_LOG.md dated entry added alongside the docs/performance JSON; LIVE_GATE_BASELINE and the CLAUDE.md snapshot synced to the measured figure in this same commit
F5-corpus-docstring-states-sprint-state   | FIXED    | feat/1079-graduation-grading-tool — the "#1067 v4 is expected to relocate it" sentence removed (it was forbidden by coding_standards AND already stale once v4 was rejected); replaced with a contract-only statement
F6-facts-cache-ignores-its-parameter      | FIXED    | feat/1079-graduation-grading-tool — dead helper deleted; the shared per-run scorecard cache is now an inline dict with a comment stating why both layers share it
F7-silent-scorecard-inflates-false-count  | FIXED    | feat/1079-graduation-grading-tool — characterization, not a defect; recorded as a standing note ON the report itself (GradingReport.notes) rather than in prose a reader of the artifact would never see
F8-N-bar-counted-unverified-decisions     | FIXED    | feat/1079-graduation-grading-tool — REGRESSION INTRODUCED BY THE F1 FIX; N now reads graded_decisions and dominant_type_count is graded-only; lock test_N_bar_counts_verified_decisions_not_observed_ones pins 60 observed / 30 verified as NOT MET
```

## F8 — the fix that introduced a defect, in the dangerous direction

Recorded at length because the pattern matters more than the line of code.

The F1 fix was correct and stopped superseded moves being scored INCORRECT. But
`meets_criteria` checked N against `distinct_decisions`, which still counted them. The
fix therefore converted **phantom errors that BLOCK graduation** into **phantom trials
that GRANT it**: 29 runs each contributing a superseded move plus a correct end-state
move reported the ratified bar MET on 30 verified trials against a bar of 60.

The direction is what makes this the worst finding of the pass. F1's defect failed
conservatively; F8's failed in the flattering direction, which is the one an instrument
gating an autonomy decision must never fail in. **The author changed the meaning of a
field and did not check the bar that consumed it.**

Substantively: the ratified N ≥ 60 is a rule-of-three argument — 0 errors in 60 trials
bounds the true error rate at ~3/60 = 5%. An abstention can never come out wrong, so it
contributes nothing to that bound; counting it inflates the sample without tightening
anything. At 30 verified trials the bound is 3/30 = 10%, double the tolerance the LA
deliberately chose over the stricter 1% option.

**Signals in N — decided with reasoning, not left implicit.** A signal does NOT count
toward N, and that falls out of the same rule rather than needing a special case: a stall
is never re-derived, so it is never a trial. It DOES count toward `types_seen`, because
§2's fourth row asks that each type be EXERCISED — a different question, and a type can
be exercised without being verifiable. `dominant_type_count` became graded-only for the
identical reason: that bar exists so the precision figure is not carried by a single
type, which is again an argument about evidence rather than observation.

Every part of this is strict in one direction: it can make a window harder to pass, never
easier. **What the ratified wording actually means — 60 verified vs 60 observed, and
whether signals count — is an LA question on #1068 and is deliberately NOT resolved
here.** The code takes the conservative reading so that being wrong costs a delayed
graduation rather than an unearned one.

## Notes on the two rows that were more than a code change

**F1.** The fix had to preserve the instrument's ability to report a failing window — an
abstention rule broad enough to excuse every mismatch would have quietly converted the
grader into the always-100% instrument the positive control exists to rule out. The rule
therefore abstains only where an innocent lifecycle explanation exists: a run with a
single board decision is by definition its own last, so a genuinely wrong move is still
graded INCORRECT. The positive control asserts both halves in the same test.

**F7.** Left as a report-level note rather than a code change because the behaviour is
correct under the ratified definition (`a statement is false iff the scorecard contradicts
it`) — `oracle_passed=False` on a silent scorecard is the production fail-soft default,
and changing it would make the grader disagree with the ruler it grades. What was missing
was disclosure, so the disclosure now travels ON the artifact.

## Residual, disclosed rather than dispositioned

The catch-rate denominator is a moving target: the corpus on branch
`feat/1067-v4-whole-text` has grown to 49 cases and the committed corpus (26) is a strict
subset of it. Which set is canonical is a criteria decision (#1068), not a build decision,
and it is recorded on #1079 c.2490 and #1067 c.2491 rather than settled here. Every report
records its corpus path and sha256 precisely so figures across different sets stay
distinguishable.

Author ≠ verifier still applies to the fixes themselves: they were written by the author
of the code under review, and have not been independently re-reviewed.
