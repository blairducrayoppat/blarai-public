# Disposition — #1283 the two-lock write path, independent pre-merge review (2026-08-06)

Review: independent author≠verifier subagent over commit `a621d34` on
`fix/1283-campaign-end-date-one-write-path` (agentic-setup), verdict **DO-NOT-MERGE** —
three blockers each independently breaking the "both locks or neither" invariant that is
the sole reason the file exists, plus two HIGH and three MODERATE findings.

**The branch does NOT merge. Nothing here is deferred-and-forgotten: every row below is
blocking work on an unmerged branch, and the branch's own merge is the predicate.**

I re-verified the two central claims against the file myself rather than accepting them:
`$daily[0]` is identified at `:295` and `$task.Triggers[0]` is written at `:337`, `:356`
and `:392`; the rollback's `Set-ScheduledTask` at `:356-357` sits unguarded inside the
`catch` under `$ErrorActionPreference = 'Stop'`. Both hold exactly as reported.

The reviewer executed rather than asserted: `-SelfTest` (17/17), four `-WhatIf` variants,
the standalone verifier (8/8), and two isolated probes to test its own hypotheses — one of
which **refuted its own suspicion** that the regex could corrupt prose (escaped-quote case
yields 1 match, not 2). That is the review working correctly and is why its remaining
findings carry weight.

**Nothing in this review touches the live fix.** The trigger `EndBoundary` correction is
already applied to production, verified 8/8, and does not depend on this branch.

```disposition
F1 the script identifies the governing trigger carefully (filters daily-at-23:00, refuses on 0, refuses on >1, reads origEb from daily[0]) and then writes a DIFFERENT object - task.Triggers[0] at :337, :356 and :392 - so with more than one trigger the governing trigger's EndBoundary is never updated while end_date is, manufacturing the exact silent half-applied divergence this script exists to make impossible, and the rollback then stamps daily[0]'s old boundary onto an unrelated trigger that may never have had one | DEFERRED | #1283 blocked-by: `fix/1283-campaign-end-date-one-write-path` does not merge until `$daily[0]` is the write target at all three sites - latent today (live task has TriggerCount 1) and therefore invisible to every current test, which is precisely why it must not merge unfixed
F2 the fail-closed claim at :41-43 ("a partial application must never be a possible outcome") is false - both rollback paths call Set-ScheduledTask unguarded under ErrorActionPreference=Stop, so a throw during restore escapes and leaves trigger-new/campaign-old (catch path) or campaign-old/trigger-new (verify path), and the "Restored. Both locks are as they were" line never prints with nothing in its place - the one path where the operator most needs a named remediation emits a raw stack trace, violating principle 11 | DEFERRED | #1283 blocked-by: `scripts/set-campaign-end-date.ps1` on branch `fix/1283-campaign-end-date-one-write-path` (agentic-setup) does not merge until: needs a finally that re-reads BOTH locks and states which one is wrong by name, and the docstring claim must match whatever the code actually guarantees
F3 the post-write verification shells out to the ENTIRE verifier T1-T8 and rolls back on any non-zero exit, so a correct two-lock write is undone by an unrelated drift (T6 MultipleInstances, T8 action re-point) or by python being absent for T4's derivation; and "the verifier must be green" is the largest precondition in the design yet is discovered only AFTER both locks are mutated, contradicting the script's own posture at :39-40 and falsifying the -WhatIf contract at :59-61, which never touches the verifier | DEFERRED | #1283 blocked-by: `scripts/set-campaign-end-date.ps1` on branch `fix/1283-campaign-end-date-one-write-path` (agentic-setup) does not merge until: scope the post-write check to the two-lock question (T7) and move any genuine precondition ahead of the first write; includes the sibling case where duplicate-end_date detection runs at :342, after lock 2 is already written, so a duplicate key causes a write-then-undo of a production scheduled task rather than a refusal
F4 the verifier is invoked at :373 with -CampaignConfig only - no -TaskPath, -TaskName or -ExpectedTriggerHour, all three of which are parameters of this script and exist on the verifier - so against a non-default task the write goes to task A and the verification reads task B, either printing DONE for a write it never verified or rolling back A because B is red for its own reasons; the fallback branch at :380-385 uses TaskPath/TaskName correctly, and that asymmetry is itself the evidence | DEFERRED | #1283 blocked-by: `scripts/set-campaign-end-date.ps1` on branch `fix/1283-campaign-end-date-one-write-path` (agentic-setup) does not merge until: thread the task identity into the verifier call, or delete the parameters that invite the mismatch
F5 -SelfTest locks the pure derivation and the JSON edit (17 real checks) but nothing that decides WHETHER to write - seven header claims have no test at all, including every refusal path and BOTH rollbacks, so the code the entire fail-closed claim rests on is never executed by any test; principle 12 requires a lock ship with a test proving it blocks AND a toggle proving the probe fails when the lock is off, and "verified live: the refusal paths refuse" is an unrepeatable manual check that gives the next editor no signal | DEFERRED | #1283 blocked-by: `scripts/set-campaign-end-date.ps1` on branch `fix/1283-campaign-end-date-one-write-path` (agentic-setup) does not merge until: the verifier this file is modelled on already solved it with -EndDateOverride/-EndBoundaryOverride/-ActionOverride injection seams; the writer ships no equivalent
F6 the comment at :115-116 claims the boundary convention is "expressed once so the writer and the checker cannot disagree" - it is expressed twice (Get-ExpectedEndBoundary here, $t7EndDate.AddDays(1) at verifier :345 and :358) and the two already disagree on IDENTIFICATION: this script matches on hour only while T3 additionally requires Minute -eq 0, and this script refuses >1 daily-at-hour trigger while T7 ACCEPTS >1 when their boundaries agree - so the one write path cannot fix a state its own checker calls conformant | DEFERRED | #1283 blocked-by: `scripts/set-campaign-end-date.ps1` on branch `fix/1283-campaign-end-date-one-write-path` (agentic-setup) does not merge until: either share the derivation or delete the "cannot disagree" claim; a false invariant claim is worse than none
F7 the side-config guard compares against a $PSScriptRoot-relative default, and `state/` is line 1 of .gitignore, so NO worktree has a campaign file - from any worktree the guard refuses the canonical production campaign as "NOT the default campaign" and the only way forward is -IOwnTheSharedTask, the escape hatch designed to be rare and frightening; worse, the pinned tree the battery actually runs from (agentic-battery-measured, #1181a/T8) has no state/ directory either, so the guard is keyed to a proxy that breaks in exactly the topology #1181a established | DEFERRED | #1283 blocked-by: `scripts/set-campaign-end-date.ps1` on branch `fix/1283-campaign-end-date-one-write-path` (agentic-setup) does not merge until: compare against the canonical path, not a $PSScriptRoot-relative one; I hit this myself during testing and worked around it with BLARAI_BATTERY_AGENTIC_STATE_ROOT rather than noticing it was a design defect
F8 nothing anywhere references this script - grepped both repos, no .md, .ps1 or .py outside the file names it, and the operator-facing runbook that owns cadence and discusses end_date in seven places does not mention the new write path; the defect being fixed is that "remember to do both" was the whole control at write time, and replacing it with "remember this script exists", discoverable only by ls scripts/, is the built-but-wired-into-nothing failure CLAUDE.md names as recurring | DEFERRED | #1283 blocked-by: `scripts/set-campaign-end-date.ps1` on branch `fix/1283-campaign-end-date-one-write-path` (agentic-setup) does not merge until: docs/runbooks/battery_cadence_and_targeted_runs.md must name it at the point where an operator would otherwise hand-edit; this is the finding that would have made the whole change pointless in practice
F9 `#Requires -Version 7.0` at :1 versus $PSNativeCommandUseErrorActionPreference at :370, which does not exist before 7.4 and throws under StrictMode - and :370 sits OUTSIDE the write try/catch, so on a 7.0-7.3 host both locks are written and never verified before a raw crash; latent (box runs 7.6.4) and the #Requires line is what is wrong | DEFERRED | #1283 blocked-by: `scripts/set-campaign-end-date.ps1` on branch `fix/1283-campaign-end-date-one-write-path` (agentic-setup) does not merge until: raise #Requires to 7.4, the version the code actually needs
F10 comment rot: :24-29 pins current values as facts (campaign extended to 2026-11-11, EndBoundary left at 2026-08-12) which read as statements about present contents and are wrong after the first use; :20-22 states a repo-wide-search wiring claim with a shelf life; :51 and :246-248 restate the runner's default resolution three times instead of pointing at the authority, against <coding_standards> | DEFERRED | #1283 blocked-by: `scripts/set-campaign-end-date.ps1` on branch `fix/1283-campaign-end-date-one-write-path` (agentic-setup) does not merge until: convert the incident narration to a dated past-tense reference and point at the authority rather than restating it
F11 no past-date guard - EXECUTED by the reviewer: `-EndDate 2020-01-01 -IOwnTheSharedTask -WhatIf` reports "every precondition passed", and run for real it writes BOTH locks consistently, so T7 PASSES and the post-write verification SUCCEEDS, leaving the nightly battery permanently unable to fire while the script exits with only a warning; this is the one path where every existing guard is satisfied and the outcome is still a dead battery, and none of F1-F10 reaches it | DEFERRED | #1283 blocked-by: `scripts/set-campaign-end-date.ps1` on branch `fix/1283-campaign-end-date-one-write-path` (agentic-setup) does not merge until: a refusal on any date at or before today sits in the precondition block, not as a post-hoc warning
F12 the "judged sound" section of this very record claims the blast radius cannot destroy anything - that is WRONG: `:345` is a non-atomic Set-Content truncate-and-write on state/battery-campaign.json, whose only copy of the original is $origText in process memory; git check-ignore confirms .gitignore:1 state/, the file's own notes say "this file is gitignored and a corrupted count cannot be reconstructed", and it currently holds ~8 KB of accumulated LA-direction prose, so a kill mid-write destroys it with no recovery path | DEFERRED | #1283 blocked-by: `scripts/set-campaign-end-date.ps1` on branch `fix/1283-campaign-end-date-one-write-path` (agentic-setup) does not merge until: the campaign write is temp-file + Move-Item with a .bak beside it
```

## Judged sound by the reviewer, recorded so it is not re-litigated

The regex value-replace **held under attack**: the reviewer tried to break it with
escaped-quote prose, unicode-escaped keys, nested duplicate keys and encoding round-trips,
and reports it correct against valid JSON — explicitly refuting its own opening hypothesis.
Elevation is checked before any write and the docstring's ordering argument for it is
right. The scope limit (changes an existing cutoff; does not introduce or remove one) is
stated openly rather than half-implemented. The arithmetic matches T7 today. `-WhatIf`
wrote nothing — campaign SHA and `EndBoundary` unchanged across all its runs. Blast radius
cannot destroy anything: no file deletion, no unregister, no git.

The reviewer's summary is the fair one: **the design intent is right and the implementation
does not yet hold the invariant it claims.**

## The uncomfortable part, recorded because it is the transferable lesson

This branch was written to fix a defect whose whole shape is *"a change with two write
sites, where doing one and not the other fails silently."* The review found the same defect
**inside the fix** (F1), a fail-closed guarantee that is not fail-closed (F2), and a tool
nobody can discover (F8) — which would have left the next person hand-editing exactly as
before. A fix that reproduces the class it targets is worth more as a lesson than the fix
would have been as a merge, and it was caught only because author≠verifier was actually
enforced rather than waived for a small single-file change.

---

## SECOND independent review (merge-guard-2), 2026-08-06 — blind to the above

A second reviewer, with no sight of this record, independently reached **F1, F2, F3, F5, F6,
F8, F9 and F10**. Two-reviewer agreement on F1 and F2 in particular. It missed F4 and F7's
second half, and found two things this record did not. Both are added below rather than
filed separately, because a disposition that does not carry the second review is the same
partial record this arc is about.

**F12 CORRECTS A ROW IN THE "judged sound, do not re-litigate" SECTION ABOVE.** That
section says *"Blast radius cannot destroy anything: no file deletion, no unregister, no
git."* **That is wrong and it must not stand**, precisely because it sits where nobody will
look again.


**Sharper sub-case to fold into F2's remediation:** `$origEb` is captured as a STRING and is
`''` when the trigger has no `EndBoundary` — which is the script's *likeliest real use case*
(T7 reports the boundary lost, operator runs the writer to repair it). The reviewer tested
the assignment in memory on an unregistered trigger: it does not throw but yields an empty
string, **not "absent"**. Whether `Set-ScheduledTask` accepts that in the task XML it could
not settle without registering a throwaway task, which it judged outside a read-only remit.
**That gap is honest and remains open** — either the rollback throws unhandled, or it writes
a malformed boundary. Neither is "restored".

Minor correction to F9: `$PSNativeCommandUseErrorActionPreference` arrived in 7.3, not 7.4.
The remediation is unchanged, and 7.4 remains the safe `#Requires` floor.
