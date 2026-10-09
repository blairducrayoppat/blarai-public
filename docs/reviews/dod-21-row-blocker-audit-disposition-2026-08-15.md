# Disposition — independent audit of all 21 Definition-of-Done rows, 2026-08-15

**Why this pass happened.** Tonight proved the DoD's own status text can be flatly wrong: row 7
said #1203 was *"fix merged, ticket open only pending a pinned-tree battery night"*, that night
ran, and the fix turned out never to have executed in production at all. A document wrong about
one row's blocker may be wrong about others, so four independent read-only auditors checked all
21 rows against disk, each asked specifically to hunt for blockers that are stale, already
satisfied, or self-serviceable.

**The headline correction is to my own reporting.** I had told the operator that "nine rows need
a run". That figure was a summary of my own earlier reasoning, never a measurement. Measured:

| bucket | rows | count |
|---|---|---|
| ALREADY-LIVE (correctly marked) | 1, 3, 5 | 3 |
| **SELF-SERVICEABLE** — stale, satisfied, or code/tests/docs with no run and no decision | 4, 6, 8, 9, 10, 11, 13, 15, 16, 20, 21 | **11** |
| NEEDS-RUN — genuinely requires a battery night or GPU dispatch | 2, 14, 17 | 3 |
| NEEDS-OPERATOR — a judgement only the Lead Architect can make | 12, 18, 19 | 3 |
| MIXED | 7 (#1200 deferred by decision per #1385; #1203 self-serviceable) | 1 |

So the dominant blocker across the Definition of Done is **not** scarce overnight runs and **not**
the operator's queue. It is unbuilt engineering and stale documentation — eleven rows of it.

```disposition
# finding | status | evidence-or-predicate
row 7 claimed #1203 was fixed and awaiting a pinned night; the night ran and the dispatch still resolved the PRIMARY checkout, because the validator reads a declaration directory nothing has ever written | FIXED | 6bf104c1 — row 7 rewritten with the measurement; the only writer anywhere is a test fixture (test_fleet_dir_resolution.py:498-500), swept across both agentic trees, blarai-ops and BlarAI launcher/services/tools
craft grading compared EVERY delivery against the python seed alone, so a web delivery shipping its untouched seed README was reported clean | FIXED | 6ff14420 — all_seed_roots() sweeps build-infra/*/reference; verified on the 2026-08-14 B9 delivery, whose README normalises character-for-character identical to web/reference/README.md and mentions the pottery studio zero times
my own #1279 fix wired truncated_tasks into decompose.py's DEBUG-ONLY diagnostics, not the decompose-decision/v1 artifact every real run writes | DEFERRED | #1279 blocked-by: the 2026-08-15 23:00 battery run completing. The fix alters execute_swap_dispatch's signature on the live dispatch path and two grading-path changes already land tonight; a third makes a bad result unattributable (RULE 2 / #740). Observable: grep truncated_tasks shared/fleet/swap_ops.py returns 0 today
#1280's (b) blocked-by names #1277, which is CLOSED and was never the resume capability | DEFERRED | #1280 blocked-by: its DESCRIPTION field still ending "(b) blocked-by: #1277" — observable by reading #1280's description. The correction is recorded as comment 3126 naming #1321 as the real blocker, but a comment does not change the field a future session greps, and `update_task` is a full PUT that would wipe the ticket's other fields to edit it
I recommended a Python probe run, against a standing LA decision (#1385) dated the previous day that no Python night is to be scheduled | FIXED | probe config deleted; retraction recorded as comment 3123 on #1200; state/battery-campaign.json verified still ["B9"]
row 4's stated blocker (no hypothesis statistics artifact, -StatsPath unpassed) was fixed in agentic-setup aad2070, merged 04:06 tonight, and the row's text and line citations are now stale | DEFERRED | #1404 blocked-by: row 4 of `docs/design/CODER_DEFINITION_OF_DONE.md` still citing the stale citations fleet-lib.ps1:3526 / new-agent-task.ps1:601,713 no longer matching the code
row 13's status table still marks link_lint, green_audit and image_placement DEFECTIVE, and names none of the six further instances fixed tonight nor the new sibling-parity control | DEFERRED | #1404 blocked-by: row 13's status table still marking those three DEFECTIVE — observable against against #1389 and #1391 both being done on the board
row 6's trigger condition ("the next complete dispatch") fired on the 2026-08-14 B9 run and answered NO — zero coder lookups across six tasks, state/research-usage.jsonl unchanged at 1,990 lines — and the row still reads "as of 2026-08-14" | DEFERRED | #1404 blocked-by: row 6 still reading "as of 2026-08-14" — observable against research-usage.jsonl holding only 4 search_docs_cli records, all pre-2026-08-08
#1370's discard path is gone from a real run but its predicate is NOT witnessed — the bounded passes produced empty output, so no bounded-pass-WITH-work was kept | DEFERRED | #1370 blocked-by: a `state/fleet-runs/*/run-fleet-*.log` carrying BOTH "applied + re-merged" and "time-bounded" on the same fix pass. Today every "time-bounded" line in `20260814-230237-bd` also says "produced no changes", so the conjunction has never been observed
row 19's table does not reconcile with its own stated total (313+233+1+0 = 547, not 580 of 618) | DEFERRED | #1404 blocked-by: row 19 of `docs/design/CODER_DEFINITION_OF_DONE.md` stating "580 of 618" above a table summing to 547 — observable by re-deriving both from `state/fleet-runs/*/acceptance.json`. Not corrected here because I have not measured which figure is right, and replacing one unmeasured number with another is this document's own defect
row 21's "eight runs" tally does not show its grouping method against 17 matching run directories on disk, and its "no ticket" claim is stale | DEFERRED | #1404 blocked-by: row 21 of `docs/design/CODER_DEFINITION_OF_DONE.md` claiming "eight runs" without stating its grouping rule, against 17 directories in `state/fleet-runs/` matching the row's own selection — observable by counting them. The row's "no ticket exists" clause is already false: #1392 does
row 16's control is genuinely LIVE but its ticket citations (#1355, #1385) are both unrelated, so no ticket tracks it | DEFERRED | #1404 blocked-by: row 16 citing #1355 and #1385 — observable by reading both, neither of which mentions the enumerator ratchet
```

## What this pass did NOT cover

It classified blockers; it did not re-derive every row's LIVE/PARTIAL verdict from first
principles. A row marked ALREADY-LIVE here was checked against its own stated observable and its
cited evidence, not re-litigated. And four auditors reading in parallel cannot see a row whose
defect is that it asks the wrong question — that failure mode is invisible to this method, as it
was to every method applied to row 7 before tonight.
