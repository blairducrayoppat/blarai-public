---
title: "#1076 evidence-preservation review — finding disposition"
status: closed
area: reviews
date: 2026-07-23
---

# #1076 evidence-preservation review — disposition

**Subject:** `feat/1076-preserve-attempt-logs` (BlarAI) and `fix/1076-worktree-add-fail-loud`
(agentic-setup), both unmerged, base `main` @ `ec787787` / `c6a8285`.

**Reviewer:** an independent agent that did not author either branch. It reported only and wrote
no fixes. Verdict MERGE-AFTER-FIXES, no code-correctness blockers. Nine findings: 1 MODERATE,
2 MINOR, 4 LOW, 1 INFO, 1 nit — none blocking.

**This record is author-written**, which is the weaker arrangement: the reviewer correctly did not
write it, and an author-written disposition is exactly where a finding gets quietly downgraded.
Read the rows against the commits, not against my summary of them.

## Provenance of the finding text — read before trusting this record

An earlier revision of this file carried **four rows against a stated nine**, marked PROVISIONAL.
The review existed only as a message to the team lead; nothing was on disk (I searched
`docs/reviews/`, the repo for `*1076*`, and the shared session scratchpad — `gate_1076.txt` there
is a captured pytest run, not the review). I declined to reconstruct the missing five from the
hand-back's prose, because a disposition whose finding text the author invented is worth less than
no record, and it is precisely the gap `verify_disposition.py` documents it cannot see: *"It cannot
detect a review whose findings were never written down."*

The full F1–F9 text was then relayed verbatim and is the basis of the rows below. That sequence is
recorded because it is the reason this record can be trusted at all — and because a green verifier
run on the four-row version would have looked identical to a green run on this one.

## The findings

| id | sev | one line | disposition |
|---|---|---|---|
| F1 | MODERATE | appending silently moves `samples_consumed` UP; the fragment named only the opposite direction | FIXED |
| F2 | MINOR | `_open_append_log` docstring asserts current wiring, with counts | FIXED |
| F3 | MINOR | the agentic-setup `:332` residual is a verbal deferral with no ticket | FIXED |
| F4 | LOW | the one non-run-scoped log path now appends forever with no rotation | FIXED |
| F5 | LOW | battery-close attribution can fingerprint a failure the run recovered from | DEFERRED |
| F6 | LOW | the truncation lock greps a literal; a renamed variable or `write_text` slips through | FIXED |
| F7 | INFO | concurrency undefended — 4 concurrent writers, 3 payloads lost | REJECTED |
| F8 | LOW | the harness sets `ErrorActionPreference` `Stop`; production sets `Continue` | FIXED |
| F9 | nit | a test comment generalises the fixed-path argument to a file where all readers glob | FIXED |

### F1 — the metric that moved

`_samples_consumed_from_run_dir` SUMS every `Best-of-N: N candidate(s)` match; the three fix-cycle
sites re-run `run_task(base)` with the same task name → same slug → same file. Truncation counted
only the last attempt; append counts both. **Measured 2 → 5** on a two-attempt case. More honest,
but a confounder against banked runs under one-change-per-RUN, so this change needs its own
attribution window. Recorded in the fragment, in the docstring, and as a standalone #1076 comment.

### F2 — the rotting docstring

The counts were accurate the day they were written, which is the rot pattern. Replaced with the
contract — a per-run log path is an interface; readers bind by exact filename for liveness and by
capped glob — plus "grep the basename; that search, not a number here, is the authority."

### F3 — the undeferred deferral

Now **#1084**, three options costed, observable predicate, and the code comment names it so the
deferral is discoverable at the code rather than only on the board.

### F4 — the one path that is not run-scoped

`probe.py:307` calls `real_load_30b(config, run_id="")` → `<runs_dir>/start-llm.log`, outside any
run dir, rewritten per battery-admission probe. Truncation bounded it nightly; append does not.
Fixed by rolling one generation aside at an 8 MiB ceiling. The rolled name is `<path>.prev` —
suffix AFTER the extension, so `run-fleet-x.log.prev` does not match the `run-fleet-*.log` glob and
is not the exact path the liveness readers stat. Invisible to every consumer, bounded at ~2×, and
unreachable on a run-scoped path (~3000 nights at the measured 1.4–2.9 KiB per probe).

### F5 — deferred, and why it is a decision rather than a defect

Four defensible answers with different meanings for the battery ledger (scope to last attempt /
prefer-last-with-fallback / leave it / attribute per-attempt), and option 1 would throw away the
evidence this ticket exists to preserve. Advisory-locked, so it cannot move a verdict. **#1085.**

### F6 — the lock that only caught its own author's spelling

The literal `open(log_path, "w"` only sees a site that names its variable `log_path` and calls
`open` positionally. Replaced with an AST walk over any truncating `open` and any `write_text`
whose target mentions a log, plus a toggle proving it fires on both shapes the grep missed.

### F7 — argued, not fixed

Rejected as a defect on this branch; the argument is in the row rather than asserted here.

### F8 — the harness that did not mirror production

Now reads `$ErrorActionPreference` **out of `new-agent-task.ps1`** and runs the extracted block
under that value, so the harness tracks production rather than restating it — the same "pin the
property, not the prose" failure that #1074's re-anchoring commit had just fixed elsewhere.

### F9 — the overstated comment

Correct as reported: every `run-fleet-*.log` consumer globs (`doom_check.py:159`, `monitor.py:327`,
`watch.py:108`, `failure_taxonomy.py:215`, `swap_driver.py:675`). The exact-path liveness argument
stands on `design-critique.log` alone, which is locked separately. The comment now says what that
case actually locks — one file per task keeps the count-bounded readers from spending their file
budget on attempt siblings — and points at the test carrying the real argument.

```disposition
F1-samples-consumed-moves-up-under-append | FIXED | 7636e971 journal fragment + #1076 comment record both directions and the attribution-window consequence; measured 2 -> 5
F2-open-append-log-docstring-asserts-current-wiring-with-counts | FIXED | 7636e971 counts replaced with the interface contract and a grep-the-basename pointer
F3-332-candidate-control-flow-was-a-verbal-deferral | FIXED | #1084 opened with an observable predicate, and the code comment naming it lands on agentic-setup branch fix/1076-worktree-add-fail-loud - CROSS-REPO, cited by ticket and branch rather than by a SHA this repo's git cannot resolve
F4-non-run-scoped-start-llm-log-appends-forever | FIXED | bbacf1f6 _roll_oversized_log bounds growth at an 8 MiB ceiling, rolling one generation to a `.prev` sibling whose suffix follows the extension, so it matches neither the run-fleet-*.log glob nor any exact-path liveness read
F5-taxonomy-can-fingerprint-a-recovered-failure | DEFERRED | #1085 blocked-by: `tools/dispatch_harness/failure_taxonomy.py` stating in `_read_logs` which attempt's text a fingerprint may come from, plus a test in `tests/integration/test_failure_taxonomy.py` driving a recovered-then-clean two-attempt log through `classify`
F6-truncation-lock-greps-a-literal | FIXED | bbacf1f6 replaced with an AST walk over truncating open() and write_text() on any log-ish target, plus a toggle asserting it fires on the two shapes the literal missed
F7-concurrency-undefended | REJECTED | Not a regression and not reachable: the truncating open this replaces loses payloads identically, so no new loss is introduced, and no caller reaches these helpers concurrently - swap_driver's only thread is the budget watchdog, which never calls run_task, _CurrentChild holds one child per run, and best-of-N concurrency lives in new-agent-task.ps1's Start-Job children writing their own per-candidate logs. Recorded in the _open_append_log docstring anyway, because APPEND reads like a concurrency guarantee it does not provide. Making it safe needs a lock, not a mode flag.
F8-harness-erroractionpreference-diverges-from-production | FIXED | agentic-setup branch fix/1076-worktree-add-fail-loud (CROSS-REPO, not resolvable in this repo's git) - verify-worktree-add-fail-loud.ps1 reads $ErrorActionPreference out of new-agent-task.ps1 and runs the extracted block under it
F9-test-comment-overstates-the-fixed-path-argument | FIXED | bbacf1f6 comment corrected to name the five globbing consumers and point at the design-critique.log test that carries the exact-path argument
R1-branch-assertion-satisfied-by-gits-own-output | FIXED | branch fix/1076-worktree-add-fail-loud - re-anchored on the literal "(branch '" prefix that git's "(new branch '" cannot satisfy; re-run against the same mutant goes FAIL exit 1, and 18/18 against the real file
R2-ast-lock-silent-on-path-open-and-write-bytes | FIXED | branch feat/1076-preserve-attempt-logs - the attribute and builtin open() forms are handled separately so the Path spelling's mode is no longer read as its path; write_bytes added; toggle widened to 5 offending shapes plus 3 must-stay-silent controls
R3-roll-preserves-evidence-where-the-globs-cannot-see-it | FIXED | branch feat/1076-preserve-attempt-logs - _roll_oversized_log's docstring now tells a forensic reader to ask for the .prev sibling by name, and records the 19.8 KiB largest-real-log measurement against the 8 MiB ceiling
R4-first-match-read-of-production-erroractionpreference | FIXED | branch fix/1076-worktree-add-fail-loud - the suite asserts exactly one $ErrorActionPreference assignment exists, so a second one added inside a function fails loud instead of silently pinning the wrong scope
```

## Re-pass (R1–R4), 2026-07-24

A second independent pass over the fix round. It confirmed no lock was neutered by the fixes — the
surgical `"a"` → `"w"` toggle re-run post-fix put 7 of 10 red, and the 3 staying green are correctly
mode-independent — and returned four further findings. All four FIXED; none deferred, none argued
away. Their fix and this record land in the same commit, which `git log -1` on either branch
resolves. The R-rows live in the single combined block below — the verifier requires exactly one
per file, which is the right constraint: two blocks is two places for a row to hide.

**R1 was a gate that could not fail**, and it is the one that matters. `$thrown -match
[regex]::Escape($branch)` was satisfied by *git's own* captured output — `Preparing worktree (new
branch 'agent/probe-task')` — never by our sentence. Deleting `(branch '$branch')` from the shipped
throw left the suite at **17/17 against the mutant**. It survived unchanged from `16e0ef5`, so it
was not introduced by the fix round; the first review missed it too. Now anchored on the literal
`(branch '` prefix, which git's text cannot satisfy because it reads `(new branch '` in that
position. **Re-run against the same mutant after the fix: FAIL, exit 1**; 18/18 against the real
file.

That is the third gate-that-passes-against-the-bug found in one night across three tickets. In a
change whose entire subject is preserving evidence, an assertion that cannot fail is the wrong
artifact to leave behind — which is why it was worth holding a merge for rather than ticketing.

**R2 was the same class one level down.** The AST lock's first version read `path.open("w")`'s
*mode* as its *path*, so the `Path` spelling was silent — in a module where every log path is a
`Path`. That is the shape most likely to appear next, in the very family the lock exists to close.
Both `open` forms are now handled explicitly, `write_bytes` added, and the toggle grew from 2
offending shapes to 5, with three must-stay-silent controls (append, read, non-log) so the lock
cannot start firing on correct code and get disabled.

## The strongest thing in this change, recorded because the disposition should say so

`:326` is the *worse* of the two truncating sites, not the lesser one. `real_run_critic` and
`real_run_design_loop` read back the file they wrote, so a naive append there would have upgraded a
lost-log defect into a **wrong-verdict** defect: a lap crashing before it printed anything would
have inherited the previous lap's `VERDICT: MERGE`. The byte-offset slicing
(`_run_to_logfile_at` → `_read_log_from`) is what prevents that, and it is locked by a two-lap
`real_run_critic` where lap 2 says nothing and must answer with the fallback.

## Verification after the fixes

- `tests/integration/test_swap_ops.py` + `test_swap_ops_attempt_evidence.py`: **130 passed**.
- `scripts/verify-worktree-add-fail-loud.ps1`: **18/18**, exit 0; `new-agent-task.ps1` parses clean.
- R1 mutant (the `(branch '...')` clause deleted from the shipped throw): **FAIL, exit 1** — the
  assertion now discriminates. Before the fix the same mutant scored 17/17.
- `verify_disposition.py`: **PASS 13/13** (9 F-rows + 4 R-rows).
  `tests/security/test_disposition_discipline.py`: 28 passed.

*(R5, 2026-07-24: the line above read `9/9` until now. The R round added four rows to the
block directly above it and left the count beneath unchanged. The verifier was printing
13/13 the whole time, so nothing was hidden and nobody was misled — but it was a stated
number that no longer matched the measured one, in the record whose entire credibility
rests on its numbers, and it went unnoticed through my own re-read. On correcting it I
re-measured every other figure in this section rather than assuming the rest had aged
better: 130, 18/18, 17/17 and 28 all still hold.)*
