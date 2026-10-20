---
title: "MXC proxy egress, standard token (Q3): post-run review, finding disposition"
status: closed
area: reviews
date: 2026-10-16
---

# Q3 standard-token post-run review: disposition

**Subject:** live batch `run-20261016-1` (raw in `%USERPROFILE%\blarai-research-data\mxc-proxy-egress\`), harness at `1c6638aa`, reviewed read-only by an independent agent on 2026-10-16 (`docs/reviews/mxc-proxy-egress-standard-token-postrun-review-2026-10-16.md`, `596f155d`). Answer of the review: ANSWERED-HOLD, both arms, 3 of 3 runs each. Five findings, numbered as in the review.

**Fix commit:** `d89bbed9` (README). The wrapper is outside git (`%USERPROFILE%\blarai-research-data\_tools\run_nonelevated.ps1`, sha256 prefix `b4132ab9eb2d24ec` after the fix); its fix was tested at 05:58 on 2026-10-16: a 24-second command returned `SLEPT_OK` and `exit=0` only after it finished, and a command that never wrote the marker returned `exit=TIMEOUT` and the task was stopped.

```disposition
F1-wrapper-returned-before-the-batch-finished-and-console-lost-probe-output | FIXED | d89bbed9 documents the new wrapper contract in the README; the wrapper itself, run_nonelevated.ps1 (hash in the header; outside git, %USERPROFILE%\blarai-research-data\_tools) now waits for a completion marker the task writes as its last action, prints the real errorlevel, and stops the task with exit=TIMEOUT when no marker appears; tested 2026-10-16 05:58 (24 s command, marker-less command); the lost console lines are not recoverable and the record cites the raw run files, not the console (#1799 comment)
F2-readme-unattended-command-has-control-characters-and-no-exit-suffix | FIXED | d89bbed9 README line 61 rewritten with literal backslashes and the CMD_EXIT suffix; grep -P for control characters returns 0 lines
F3-summary-reads-absent-state-field-and-unreadable-wfp-as-no-change | DEFERRED | #1798 blocked-by: #1798 (the next live run of this probe is a case-1 variant under #1798; summarise.py is under the round-2 approval hash, so the change needs a new pre-run review before that run); incidence 0 of 6 in run-20261016-1, every record carries state_changed_by_run {}; the Q3 record states the WFP filter state was not measured under this token
F4-refusal-not-attributed-to-mxc-by-this-batch-alone | FIXED | bebb33da states it in-repo: PERFORMANCE_LOG.md Q3 entry Not measured ("whether a per-program Bitdefender rule on the container's interpreter path contributed ... this batch alone does not attribute the refusal to MXC") and the Q3 JSON not_measured list; the variant 4 entry (bebb33da, ownership corrected in b1923fd5) adds the WFP layer the fork's capability-only reading missed
F5-token-harness-and-bitdefender-changed-together-vs-the-elevated-batches | FIXED | bebb33da states it in-repo: PERFORMANCE_LOG.md Q3 entry Not measured (isolated token effect) and the Q3 JSON differences_from_the_elevated_case1_batches; b1923fd5 completes the changed set (the launch.ps1 hash change recorded in the Q3 JSON and entry, and the new launch-standard.cmd)
```
