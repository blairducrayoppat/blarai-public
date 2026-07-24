### 2026-07-23 — The retry erased the record of what it was retrying

*Plain summary: our automatic repair step was overwriting the log of the failure it existed to repair, so three nights of forensics could not say what actually broke; logs are now appended instead of overwritten, and git's own error messages are no longer thrown away.*

The #1066 investigation ended with a hole in it. Three consecutive parked runs, the same three
unresolved modules each time, and the write-up had to say that "which git command failed, and with
what message" was NOT ESTABLISHED. Not because nobody looked — because the evidence had been
deleted by our own code, twice over, on the two paths that only ever run when something has already
gone wrong.

The first deletion was in `shared/fleet/swap_ops.py`. The per-task log path is
`<runs_dir>/<run_id>/run-fleet-<task-slug>.log` — one task, one filename — and it was opened
`mode="w"`. The layout fix cycle re-dispatches the SAME task inside the SAME run, so the second
dispatch truncated the first. On run `20260723-001147-bd` the surviving `run-fleet-add-card.log`
was nine lines containing only the refused re-run; the original 00:33–01:05 attempt, the only place
git's swallowed error had ever been written, was gone at 01:05. The second deletion was in
`new-agent-task.ps1`, where a failed `git worktree add` piped git's message to `Out-Null` and threw
a sentence naming the path and the branch but never the reason. A locked worktree, a stale
administrative entry and a path already in use all produce that identical sentence.

The ticket named one truncating open, at `swap_ops.py:376`. There is a second at `:326`, and it
carries the same defect at five call sites, not one: `start-llm.log` is rewritten by the 30B reload
on every critic and design fix lap; `start-14b.log` by every critic lap; `critic-run.log` and
`design-critique.log` are per-lap logs written by loops that exist precisely to iterate; and
`exec-smoke-web.log` is overwritten by `_run_exec_smoke`'s post-fix re-check, which the driver
itself calls a fix cycle. Every one of those files is re-entered only because the previous attempt
failed, which is what makes truncation there so expensive — the content destroyed is always a
failure record.

The obvious fix is a suffixed filename per attempt, `run-fleet-add-card.2.log`, and I nearly took
it: attempts stay trivially separable, which is what the forensics wanted. Reading the consumers
first killed it. `doom_check.newest_progress_mtime` and `tools/dispatch_harness/monitor` both read
`<run>/design-critique.log` by exact path as a run-is-alive signal, and three more readers open a
capped set of `run-fleet-*.log` files. A second attempt writing to a new filename freezes that
liveness signal while a perfectly healthy design lap is running — a change made to improve
diagnosis would have handed the doom check a reason to kill a working run. That is the wrong
direction to be wrong in, so I appended instead: one growing file, a plain-prose banner between
attempts, and a single-attempt run byte-identical to before.

Appending has its own trap, and it is nastier than the one it replaces. `real_run_critic` and
`real_run_design_loop` read their own logfile back to parse a verdict. Append plus a whole-file
read means a lap that crashes before printing anything inherits the PREVIOUS lap's verdict — the
critic would report "MERGE" for a lap that never ran. A lost log is bad; a confidently wrong
verdict is worse. So `_run_to_logfile_at` now returns the byte offset where this attempt's output
begins and `_read_log_from` slices from there: the record on disk is cumulative, the parse sees
only this attempt. The lock for that is a real two-lap critic run where lap two prints nothing and
must come back with the fallback.

The locks drive real child processes through the real entry points — `real_run_task` twice for one
task in one run, with only the child's argv substituted, so the file open, the handle inheritance
and the writes are the shipped ones. All five go red when the truncating open is restored, which is
the only way to know the probe can see the defect at all. On the PowerShell side the verify suite
extracts the fixed block out of `new-agent-task.ps1` and executes that exact text against a real
repository whose `worktree add` genuinely fails, rather than testing a retyped copy of it; the
control runs the historical `| Out-Null` form against the same failure and proves it loses git's
words. Sixteen checks, and one of them found a third instance the ticket had not named: the
best-of-N candidate worktree creation at `:332` discarded git's output AND never checked the exit
code, so a candidate whose workspace was never created went on to "build" in a directory that did
not exist. Eight silent workspace failures is exactly the shape #1066 saw. That one now reports
git's reason; I deliberately left its control flow alone, because whether a failed workspace should
abandon the candidate outright is a quality call and not mine to make quietly.

I have to be straight about a consequence I originally wrote up in only one direction, and it is the
more important one. `swap_driver._samples_consumed_from_run_dir` SUMS every
`Best-of-N: N candidate(s)` line it finds across `run-fleet-*.log`. Three fix-cycle sites re-run
`run_task` with the same task dict — the layout cycle, the static pre-gate cycle and the
executability cycle — so the same slug, so the same file. Under truncation only the surviving
attempt's line counted. Under append both do. I measured it rather than reasoned about it: the same
two attempts, three candidates then two, report **2 before and 5 after**. The new number is the more
honest one — those candidates really were consumed and the old figure silently missed them — but
honesty is not the point here. The point is that it is a **confounder against every previously
banked battery run**. Under the one-change-per-RUN cadence, a metric that moves for a reason
unrelated to the thing being measured is exactly what that cadence exists to prevent, so comparisons
across this merge boundary are not like-for-like and this change needs its own attribution window
rather than riding along with another.

What I had written up was only the opposite direction: `_read_run_fleet_logs` caps its per-file read
at 256 KiB from the START of each file, so on a large multi-attempt log a later attempt's best-of-N
line can now fall outside the cap and be missed. Both effects are real, they push opposite ways, and
I do not know which dominates on a real run — which is itself an argument for the separate window.
Neither produces a false measurement: the metric is documented as an honest lower bound with a `-1`
"not measured" sentinel, so the failure mode is a differently-biased number, never a fabricated one.
That was the price of protecting a liveness signal that could otherwise kill a healthy run.

Recording only the flattering half of a consequence is its own small dishonesty, and I nearly shipped
it — the under-count reads as a cost I accepted with open eyes, while the over-count reads as a
metric I moved without telling anyone. The second is the one a reader of the battery ledger needs.

One more property, because the next author will assume otherwise: none of this is concurrency-safe.
A measured four-way concurrent write to one of these paths keeps a single payload. That is not a
regression — the truncating open loses identically, and nothing in the driver writes these paths from
two places at once — but "append" reads like a safety property it does not have. Making it one needs
a lock, not a mode flag.

**Proposed lesson (unnumbered):** evidence-handling on a repair path deserves the same scrutiny as
the repair itself — a retry that overwrites its predecessor's record makes every future diagnosis of
that failure class strictly harder, and the cost lands on a session that cannot see what it lost.
The tell is a fixed filename plus a loop, and the first thing to read is not the writer but every
consumer that opens that path by name.

**Next:** #1066's root cause is still not established retroactively — nothing recovers the deleted
01:05 log. The next B4 park has the instrumentation to answer it; #1074's git-swallow fix and this
one need to be live together before that run for the answer to be complete.
