---
title: "#1032 pre-merge review — finding disposition"
status: closed
area: reviews
date: 2026-07-22
---

# #1032 pre-merge review — disposition

**Subject:** `fix/1032-job-oracle-requirements-channel` @ `488e968c` (2 commits; production
change is one argument plus a docstring paragraph in `shared/fleet/acceptance.py`).

**Reviewer:** independent — it did not author this change (the day session did). It wrote no
fixes. It is the same reviewer that returned DO-NOT-MERGE on #1031 S1 earlier the same day,
re-tasked here because it already knew `shared/fleet/acceptance.py` cold and had proven it
delivers findings incrementally; it is independent of #1032 regardless.

**Verdict: MERGE-AFTER-FIXES.** *"The production change is correct, minimal, correctly scoped,
and genuinely locked. The mutant claim holds exactly as stated. Nothing found that would make
me withhold the merge on the production change itself."*

Two reviewers were stopped before this one for producing nothing — the incremental-to-disk
rule is what made the failure visible within minutes instead of at the end.

## What was verified, not asserted

- **Q3 mutant claim — CONFIRMED exactly as predicted.** Reverting `planning_seed` → `goal` in
  a detached scratch worktree turns `test_requirements_reach_the_MULTI_task_job_oracle_author`
  RED, leaves the byte-identity lock GREEN, and **nothing else in `shared/` notices** —
  3053 tests indifferent, so the change has exactly one behavioural consumer and it is the one
  claimed. `RESTORE VERIFIED BYTE-EXACT: True`.
- **The vacuity guards are REAL** — proven by two independent unreachability mutants (require
  ≥3 tasks; disable the 2g gate). Both kill both new tests, so neither test can pass while the
  branch it targets is dead.
- **The rewrite was a correction, not a weakening.** The reviewer's call, as commissioned:
  switching the arm to a sufficient goal models the real control flow, and the rewrite *added*
  the two vacuity guards the mutants prove are load-bearing.
- **Five downstream surfaces examined clean:** the #989 contract-coverage check, the
  criterion→test traceability matrix, the coverage-map request, the #821 QA gate entry point
  (none takes a goal parameter at all), and prompt length (+116 chars, +8.4%, uncapped path,
  and the identical block already rides the single-task oracle and every task prompt).

## Disposition

```disposition
Q3-mutant-claim-verification | REJECTED | Not a defect - the reviewer independently reproduced the author's claimed mutant result exactly, including that nothing else in shared/ reacts. Recorded here because a verification that CONFIRMS is evidence and belongs in the record, not because anything needed fixing.
Q2-1-vacuous-sentinel-assertion | FIXED | fix/1032-job-oracle-requirements-channel
Q2-2-byte-identity-docstring-overclaims-inertness | FIXED | fix/1032-job-oracle-requirements-channel
Q1-1-oracle-qa-corpus-grounds-on-clean-goal-while-oracle-authored-from-seed | DEFERRED | #1043 blocked-by: `_spec_corpus` in `shared/fleet/oracle_qa.py` grounding on the same text the oracle was authored from (the enriched seed or `spec.clarifications`)
```

### Q2-1 — the vacuous assertion (FIXED)

`assert clr.REQUIREMENTS_SENTINEL not in clarify_off[0]` could not fail under any input:
`generate_plan` builds the seed inline (`planning_seed = (goal + "\n\n" + req) if req else
goal`) and never calls `compose_planning_goal`, so the sentinel is absent from that prompt
always. Replaced with an assertion on `compose_requirements_block`'s real header, and the
**positive** half of the pair added to the sibling test so the string is proven to
discriminate — neither assertion can now be vacuous.

### Q2-2 — the docstring overclaim (FIXED)

The docstring claimed the test proved #1032's inertness "by equality, not by inspection". It
does not: both arms pass `requirements=""`, so `planning_seed` **is** `goal` in both and the
equality holds with or without the fix — which the mutant run confirms empirically. Docstring
rewritten to state what the test actually proves (clarify-ON-with-a-sufficient-goal is
byte-identical to clarify-OFF) and to say plainly that inertness is proved by reading the
mint-site conditional, which is the stronger proof. Same class as the S1 finding L3-3: a real
lock aimed at a smaller target than its docstring claimed.

### Q1-1 — the corpus asymmetry (DEFERRED to #1043, with reasoning)

Real, reproduced, and isolated by a control. Deferred rather than fixed because it is a SOFT
class (`CLASS_INVENTED_RETURN in HARD_CLASSES → False`) that never refuses an oracle and never
blocks a plan, and because **the asymmetry predates this change** — the single-task oracle has
always been authored from `planning_seed` against a corpus built from `spec.goal`. #1032
extended the class rather than creating it, so the fix belongs in `_spec_corpus` and wants its
own scope, not a rider on a one-argument defect fix.

## Honest limit

The standing gate was **not** re-run by the reviewer, by instruction (it was already measured
at 8735 on this branch and a second full run would have contended with GPU work in flight).
The reviewer did the cheap cross-check it could: 8733 + 2 new tests = 8735, and both doctrine
surfaces agree at 8735. That is arithmetic consistency, not an independent measurement — the
independent measurement is the author's, re-confirmed on merged main after the merge.
