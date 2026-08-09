# Disposition — #1069 S3-G criteria revision, independent pre-merge review (2026-07-28)

Review: independent author≠verifier subagent over commit `03cb7b2e` on
`feat/1069-s3g-criteria-revise`, verdict **NEEDS-FIXES** (2 real defects, both
coordinator-layer; the reviewer EXECUTED the four touched suites — 167 passed — and
attacked the machine wall directly: "no path that mutates, drops, or duplicates a
machine-tier row", the Fail-Closed refusal returns before any model call, the IPC field
is additive and typed-guarded both directions). The reviewer also judged the shipped
machine-wall TIGHTENING of the design doc §3.4(2) SOUND and honestly argued
("invariant-preserving, not a scope cut").

Fixes at `56d369a0` on the branch; fix-verification round returned to the same reviewer.

```disposition
F1 judged-layer edits never reach the VLM design loop - tasks[].visual_criteria_json goes stale, so the operator approves one checklist while the build loop critiques another; the old test pinned the stale behaviour vacuously (fixture carried no stamp) | FIXED | 56d369a0 - the criteria path re-threads build fields from the REVISED spec via acc._thread_build_fields (the clarification path's own precedent: visual/goal/build-signal stamps update, the folded test block is untouched, the machine freeze holds); test reworked to carry the stamp and assert the re-thread PLUS the coder-surface freeze (repo/task/prompt byte-identical)
F2 the wall-only case (keeps + machine rescope only) fell through to the pre-G "criteria can't be edited" message - false once the stage is live, and the promised "reported protected" never rendered in exactly the case the operator aimed at a protected row | FIXED | 56d369a0 - a changed=False outcome WITH protected_titles (the stage is provably on: ops came back) renders the protected report with the untouched card, budget unconsumed; every other fall-through stays None so the dormant reply is byte-identical; locked
F3 a plan parked with intake flags OFF, criteria-revised after the ceremony, first-injects a delivery floor the plan-time exam never saw (one-boundary-event window) | DEFERRED | #1156 blocked-by: the batched S3 D/E/F/G go-live ceremony (docs/runbooks/advanced_intake_s3_batched_ceremony.md, NOT YET PERFORMED) - the fix decision (re-inject-only vs tombstone-at-flip) closes with or before the ceremony that creates the boundary
F4 wire-side criteria_ops_from_dicts admitted shapes the AO parser forbids (duplicate refs double-report a protected title; a blank add mints an empty human row) - unreachable from the shipped AO, sibling-idiom-consistent, but zero-cost to close | FIXED | 56d369a0 - ref dedupe + text floor + step cap at the wire seam, parity-locked (duplicate machine rescope reports protected exactly once; blank adds dropped)
F5 the entrypoint property docstring carried sprint state ("the batched S3 D/E/F/G ceremony") against the coding standard | FIXED | 56d369a0 - parenthetical dropped on the criteria-revise property (the coverage-gate sibling was fixed the same way at 17d52250 on the F branch)
```

## Carried, not dispositioned

The reviewer's untested-paths list beyond F1/F2: the all-adds emission is now locked at
`56d369a0` (legal, loud, wall-respecting); zero-judged-rows through the coordinator, a
real-TOML parse of the new key, the full-equality stage-off tripwire, and the plan_fn
mid-hook raise idiom are recorded here as accepted residuals — each is either covered by
an adjacent lock (the `is True` rule is property-locked; stage-off is code-path-identical
by construction and substring-locked) or inherited pre-existing idiom (#820's unwrapped
plan_fn call), and none moves a security property. The reviewer's F3 run-time consumer
question (does the job oracle read the submitted spec or the frozen exam) is subsumed
into #1156's fix decision.
