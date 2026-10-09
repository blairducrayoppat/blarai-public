# Disposition — live monitoring of run `20260815-230306-bd`, 2026-08-15/16

**Why this pass happened.** The operator asked for active monitoring of the overnight run —
*"i want you to be actively monitoring it"*, *"check it like every 15 minutes"*, *"can't you get
real-time event feed?"* — rather than a morning post-mortem. Watching a run that was expected to
produce nothing useful turned out to produce four findings and three retractions.

**The honest headline is the ratio.** Six claims were made from live observation. **Three were
wrong and were retracted within the hour**, two of them after being written up with confidence.
Every retraction came from checking an artifact, never from re-reading the claim.

```disposition
# finding | status | evidence-or-predicate
visual FIX passes produce no change 68% of the time (120 of 177 across 631 task logs, 28 runs); of the 120, only 39 state a reason, so a starved pass and a correct no-op are indistinguishable | DEFERRED | #1425 blocked-by: a state/reports/*.fixN.agent.log with no "tool":"write" and no "tool":"edit", ending "reason":"tool-calls", whose run-fleet log line reads "the FIX pass produced no changes". fleet-lib.ps1 is battery-path so it lands before a run or after one, never during
the spin detector cannot fire on an agent that never edits: `$spinning = ($edits -ge 1) -and ...` at fleet-lib.ps1:443, so reconnaissance-only passes fall through to a blunt 240 s idle timer and are reported as "time-bounded" | DEFERRED | #1425 blocked-by: fleet-lib.ps1:443 carrying the `($edits -ge 1)` guard — observable by reading the line. Established by elimination: 60 min wall clock unused, 6-10 steps against a 45 cap, zero edits so spin is false by construction, leaving the idle branch as the only one that sets $timedOut
the fix pass emits no run record at all, so which bound fired cannot be recovered even in hindsight | DEFERRED | #1425 blocked-by: `scripts/new-agent-task.ps1` `$rebuildAutoFix` discarding the `$b.Run` hashtable it already receives from `Invoke-BuildWithRetry` instead of logging it — observable at that symbol. The candidate path logs the same record; the fix path does not
nothing outside the run observes it between TriggerWatch (23:30) and Deadman (09:00) — a wedge at 01:00 is found at 09:00 | FIXED | 8712bbd8 — tools/probes/night_check.py + BlarAI-Battery-3amCheck (daily 03:00). Fired autonomously at 03:00:01, exit 0, wrote its report. Reports and never kills; that is locked by a source scan for kill calls
my own 3am check called every run "finished" after its first task, because RUN-END is written per TASK (4 times by 03:20) and SUMMARY.txt is rewritten per task (present at 435 bytes mid-run) — inverting STOPPED-WITHOUT-FINISHING into FINISHED | FIXED | commit `19321014` — keyed on `scorecard.json`; verified present on three completed runs, absent on a reaped run and on a run in flight. Toggle-proved
the test guarding that check passed while it was broken, because its fixture wrote RUN-END only when the author meant the run to be finished — the assumption tested against itself | FIXED | 19321014 — fixture now always writes RUN-END and SUMMARY.txt as a real mid-run state does, so it passes only if the classifier keys on the scorecard
"the design reviewer says UNCLEAR 96% of the time and the work merges anyway" | REJECTED | FALSE and retracted 25 minutes after filing. new-agent-task.ps1:683 initialises $verdict = 'UNCLEAR' and the review leg runs ONLY when the gates are not both green; 554 UNCLEAR records mean 554 tasks passed and correctly skipped review. Corroborated by there being no *.review.log for any B9 run. #1426 c.3175
a skipped review is nonetheless reported as "REVIEW VERDICT: UNCLEAR", so a deliberate skip and an undecided reviewer share one string | DEFERRED | #1426 blocked-by: a task report containing REVIEW VERDICT: UNCLEAR with no review findings, no tail, and no corresponding *.review.log. new-agent-task.ps1 is battery-path
"a review timeout is forcing UNCLEAR" | REJECTED | tested and refuted with data before it was published: 3 logs corpus-wide mention "review agent timed out", 2 of them UNCLEAR — 0.4%, not 96%. Recorded because refuting it CORRECTLY increased confidence in a surrounding framing that had never been checked at all
"2 merged" reported to the operator when 1 had merged | REJECTED | not a defect in the system and deliberately not dispositioned as FIXED: its only correction was a chat message, and this gate is right that chat is not evidence. Recorded here as the durable artifact instead. Cause: "visual FIX #1 applied + re-merged" describes a fix merging into the candidate, not the task completing — the same over-reading that called a parked task "done" earlier the same day
the circuit breaker fired twice and RETRIED rather than spending the task, which is what DoD row 8 asks for | REJECTED | not a defect: this is the behaviour DoD row 8 asks for — *"a wedged candidate must be retried rather than spent"* — and it fired twice tonight and retried both times. 108 firings and 153 fresh candidates across 52 runs. Recorded so a later reader does not mistake "CIRCUIT BREAKER" in the logs for a fault. One caveat left open rather than argued away: on `implement-header-menu` the discarded candidate carried `verify: pass`, so gate-passing work was thrown out because the agent had stalled
```

## What this pass did NOT cover

It watched one run. Every rate quoted is over banked logs, not over verified outcomes — a fix
pass recorded as `applied` is **assumed** to have changed something, and that assumption got the
same transcript check only for the five passes observed live.

It also cannot say whether the 68% waste is *harmful*. A fix pass that changes nothing on a
delivery that needed nothing is correct behaviour, and **the record cannot distinguish that case
from a starved one** — which is the finding, and the reason the rate alone is not an indictment.

## The pattern worth carrying forward

Four of the night's findings are the same shape, and it is the shape the whole
instrument-honesty arc keeps meeting: **an absence rendered as a confident value.**

- a skipped review reported as a verdict
- a starved fix pass reported as "produced no changes"
- a run's own `not_measured: []` on a run that measured almost nothing
- `DEFAULT_ORACLE_PATH` standing in for an oracle that was never generated

**The failure is never a blank. It is a plausible value where a blank belonged** — and that is
also how two of tonight's three wrong claims were made, by me, reading such a value as real.
