# #1237 — the operator's platform answer was structurally discarded: finding disposition

**Date:** 2026-07-30 (LOCAL, Pacific — session clocks report 07-31)
**Branch:** `fix/1197-quick-path-attribution`, merged WHOLE as `888b1b02`
**Verifier:** the session lead, who did not author the branch. The dispatched reviewer
(`review-1237`) never delivered a report across two pulls; silence was not read as a clean
verdict, so the verification was redone on disk.

## What the finding set was about

On the #1174/#1197 forced-question path the operator is shown a platform menu and his answer
never reached the build. `_parse_build_plan` attaches `candidates` ONLY to an `ambiguous`
surface, and that question fires only when the surface is NON-ambiguous — so
`apply_clarification` found an empty allowlist by construction and returned the plan
semantically unchanged. He tapped "In a web browser" and the fleet got `command-line`, under a
card that said both in two lines.

## Evidence this disposition rests on

- Branch gate on the exact merged tip `2172b8b5`, isolated worktree, `LOCALAPPDATA` redirected:
  `== 9932 passed, 21 skipped, 128 deselected, 16 warnings in 299.80s (0:04:59) ==`. 0 failed;
  the 21 are the documented model skips.
- Post-merge gate on merged main `c6f6af23`, primary checkout, models present — recorded in
  `docs/TEST_GOVERNANCE.md` §1.
- Production call-path traced by reading, not by test: `dispatch_coordinator.py:1803`.

```disposition
F1 the operator's answer reached the seed through only ONE of the two doors the platform menu opens; through the model-flagged fork it burned a full model chain and regenerated a plan that never heard him | FIXED | 888b1b02 (carrier 1470881a, 9201d427) - apply_clarification gains `offered`, validated against the menu ACTUALLY RENDERED (dispatch_coordinator.py:1803 builds offered_surfaces from `options`, not from build_plan candidates - the circularity that would have made the fix inert is absent), still intersected with _REAL_SURFACES, and `raw = offered if offered is not None else ...` rather than a truthiness coalesce so `offered=[]` denies everything instead of falling through
F2 the answer landed on the build signal but not on the requirements block the coder actually reads, so the prompt still carried the assumed "a simple command-line tool" while build_plan said web | FIXED | 888b1b02 - recompose_task_requirements re-derives that ONE section from the corrected clarifications; the answer now lands on both carriers in the same motion
F3 the card's "Got it - building it for: X" was emitted unconditionally, including when apply_clarification returned None because the re-plan produced no parseable build_plan - the card omitted the platform line while the sentence above it said the choice had been applied | FIXED | 888b1b02 - the note is DERIVED from the build signal (dispatch_coordinator.py:1903); the else-branch says exactly what is true, that his words reached the instructions but the plan itself could not be classified this time
F4 the F3 derivation `refined_plan.get("surface") == chosen_surface` was flagged by its own builder as near-tautological | REJECTED | not a tautology, and the self-flag was over-cautious. `refined_plan` is legitimately None on a build_plan-less re-plan - that is precisely the state the else-branch exists for. Verified by reading dispatch_coordinator.py:1875-1910 in full: there is no fallback to the pre-choice plan, deliberately, because falling back to the pre-choice build_plan after a re-plan would assert a classification the current plan does not have
F5 the review framed the gradeability steer as an LA decision | REJECTED | reclassified as a defect with one correct fix (carry both the chosen label AND the #1161 gradeability steer into the seed) and handed to the builder before the merge; recorded on #1237. A decision has trade-offs only the LA can weigh - this had one correct answer
F6 the _PlanFn / _PlaybackPlanFn fixtures returned a re-plan spec with NO build_plan, which is production's unparseable-output shape, so two menu tests asserted happy-path wording against the degraded path | FIXED | 888b1b02 - both fixtures gain `replan_build_plan` and the two menu tests (test_F3_inc4_question_suppresses_the_notice, test_M4_inc4_interposed_intake_keeps_its_invitation_after_choose) now pass a real classified build_plan. Same mock-shape class as the withdrawn test_dispatch_coordinator.py:1048 accusation - which was withdrawn correctly: `_questioning_plan` there builds through the REAL _parse_build_plan and supplies no candidates, so :1048 is green because `offered` genuinely works
F7 SURFACE_GRADEABILITY_STEER's effect on the planner is UNMEASURED against the real model - every lock on it is a string or composition lock, and nothing has run the text past the resident 14B | DEFERRED | #1248 blocked-by: the next @hardware ceremony window (model-loaded, real Arc 140V) - this cannot be measured on a models-absent worktree and must not be marked done from a string test. Merged knowingly and disclosed rather than hidden: it is deny-by-default (unknown surface yields ""), it names no platform so it cannot override his answer, and the #1161 operator-words scan drops it. #1248 states the falsifying condition - if the measurement shows no effect the constant is deleted, not kept because it sounds right
```

## Retraction carried forward

Earlier in the session I told the LA that the platform answer "already works — it reaches the
build signal." That was **false of main** and I corrected it to him. It was then reported as
false of the branch too, which was wrong in the other direction: the fix existed at `1470881a`
on the branch and not on main. The accurate statement, which is what this record rests on, is
**true of main as it stood tonight before `888b1b02`, false of the branch**. Both halves were
verified on disk before this record was written.

## Honest limit of this record

The disposition gate checks the FORM of a record that exists. It cannot see a finding that was
never written down. The finding set here is the one on ticket #1237 plus the three items the
builder flagged against itself; no independent adversarial pass was run against the merged tree
beyond the gate and my own read of the production call path.
