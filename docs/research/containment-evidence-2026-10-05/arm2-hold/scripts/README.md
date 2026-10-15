# Arm 2: the long hold

RAN 2026-10-11 (claim C9; results in `../runs/`). `spike-wfp.ps1`, `spike-run-test.ps1` and `spike-lib.ps1` here are as run. `Start-ElevatedOnce.ps1` gained the admin-only
folder check after the run (the run was started from an admin-only copy, which passes it): the wrapper now refuses to register or run from a folder a non-administrator
can write to. Put these scripts under an administrator-only folder such as `C:\ProgramData\BlarAI` before using the wrapper.

Question: with the raw Windows Filtering Platform (WFP) block keyed to the throwaway account's SID in place, does it stay
enforced for an hour or more while Bitdefender runs, or does the suite's sublayer win the flow back over time?

Only the files below are here: the
rest of the working set (provision, cleanup, `spike_model.py`, the verify script) is `../../arm1-permit/scripts/` and
`../../confined-model-spike/post-run-hardened/`, unchanged.

## What changed against `arm1-permit/scripts/` (line counts are in `CHANGES.md`)

| File | Change |
|---|---|
| `spike-wfp.ps1` | `-LongHold` (with `-HoldSeconds` 60..7200, default 3600; `-SampleSeconds` 30..300, default 60; `-NoLoopbackPermit`; `-HoldOutDir`). One dynamic engine session holds the filter set; dead-man at hold+30; the operator watchdog every 2 s (two failures in a row = remove everything, exit 3); the account's outbound probe once per sample, one JSON line per sample appended to `<run>-samples.txt` the moment it finishes; `netsh wfp show filters` exported at start, at hold/2, before close (and at once on the first sample that is not blocked), each searched for the `BlarAI #1671` marker and every filter key; Bitdefender process list and install-folder timestamps at start and end with a named update signal; `wsl --shutdown` first, recorded; a keep-awake request (released at the end); removal verified; the account's egress must be open again. `Assert-SpikePreflight -NeedModel $false` skips the 14 GB RAM check (probe mode loads no model). `-SelfTest` covers the new logic (see below); `-DryRun` prints the whole sequence. `-TestA/-TestB/-TestC` are unchanged. |
| `spike-run-test.ps1` | `probe` mode: identity + outbound probe only. The operator starts the task once per sample, so the task's 30-minute execution limit never bounds the hold. |
| `spike-lib.ps1` | the strict result schema knows `mode=probe` (steps `identity`, `outbound_probe`). |
| `Start-ElevatedOnce.ps1` | new. Runs ONE allowlisted script elevated through a Scheduled Task (RunLevel Highest, interactive logon of the current user) that logs, runs an optional follow-up whatever happened, and unregisters itself as its last act. `-DryRun` (alias `-WhatIf`) prints the exact definition and registers nothing. |
| `Convert-ToLive.ps1` | new. Bundled files hold `_OPERATOR_` in every default path; this writes the live copies (placeholder -> the real user name, CRLF), never overwriting a differing file without `-Force`. |
| `Run-Arm2-AsAdmin.cmd` | attended fallback (UAC prompt, dry run, then the hold). |

## Run order (elevated; Windows PowerShell 5.1 or PowerShell 7)

1. Live copies: `Convert-ToLive.ps1 -Source <this folder> -Dest <the live confined-model-spike folder> -DryRun`, then `-Apply`. The live folder must hold the
   arm 1 files too (provision, cleanup, `spike_model.py`).
2. The task runs the copies `spike-provision.ps1 -Apply` puts into `C:\blarai-spike\bin` (it copies `spike-run-test.ps1` and `spike_model.py` from the folder it runs
   from every time), so provision AFTER step 1 from the live folder (the account is removed by the arm 1 cleanup, so a fresh provision is needed anyway). The
   preflight compares the bytes of `bin\spike-run-test.ps1` and `bin\spike_model.py` with the live folder's and refuses on a difference or when the copy has no probe mode.
3. `spike-wfp.ps1 -SelfTest`, `-DryRun -HoldSeconds 3600`, `-DryRun -NoLoopbackPermit` (nothing changes).
4. Unattended: `Start-ElevatedOnce.ps1 -Name blarai-arm2-hold -Script spike-wfp.ps1 -ScriptArgs '-LongHold','-HoldSeconds','3600' -LogPath <log>` (add `-DryRun` first).
   Registering a Highest task needs an elevated session. Or attended: `Run-Arm2-AsAdmin.cmd`. The wrapper's inner process deletes its own task as its last act; the log's
   last line before that is `unregistering this task (last act)`, and deleting a running task may end the process before the line `task unregistered`. If a task named
   `blarai-arm2-hold` is still listed (`Get-ScheduledTask -TaskPath '\BlarAI\'`) the inner process died: read the log, then `Unregister-ScheduledTask`.
5. Cleanup as in arm 1: `spike-cleanup.ps1 -DryRun`, `-Apply`, `spike-verify-cleanup.ps1`.

## What each run records (`<HoldOutDir>\hold-<on|off>-<stamp>.json`, beside `-samples.txt` and the raw exports)

`filter_set`; `hold_seconds`, `sample_seconds`, `samples_expected`, `dead_man_seconds`; `env` (clock, uptime, OS, Windows build, PowerShell host, Bitdefender
processes, firewall profiles, BFE and mpssvc, WSL state); `wsl_shutdown` (list before and after); `steps.operator_baseline`, `steps.account_baseline`,
`steps.bitdefender_start`, `steps.filters_added` (timestamp, ids, names), `samples[]` (n, timestamp, offset, outcome blocked|open|no_result|wrong_sid, socket
error code, probe ms, run id), `sample_stats` (counts, error-code histogram of the blocked samples, first open sample), `exports[]` (label, path, bytes,
SHA-256, marker count, keys found and missing), `steps.watchdog` (connects, failures, longest run of failures, longest gap between ticks, failure events),
`steps.bitdefender_end`, `steps.bitdefender_update` (processes added or removed, update-named processes started during the hold, install folders whose
timestamp moved, a signal, and the caveat that none observed is not proof that none ran), `steps.engine_closed_at`, `steps.filters_stood_seconds`,
`steps.removal_engine_check`, `steps.operator_after_removal`, `steps.account_after_removal`, `decision_inputs`, `exit_code`, `exit_reason`.
The raw `*.xml` exports carry other products' filters and local paths and are NOT bundled; the result JSON keeps their hashes and counts.

## Exit codes

0 every valid sample blocked for the whole hold (at least 90% of the expected samples, never fewer than 3), the filters in all three exports, removal verified.
1 at least one sample connected (the block did not hold: a result). 2 precondition. 3 operator traffic affected (aborted, removed) or the target SID is the
operator's or one of his groups (refused before anything is added). 4 inconclusive (engine closed early, too few valid samples, an export missing a filter).
5 no baseline. 7 removal not verified.

## Caveats that still bind

The probe counts ANY failure as blocked: the baseline and post-removal runs attribute the block to the filters; the socket error code (10013 in arm 1) is
recorded per sample. Bitdefender's own sublayers are the unknown. Isolated operator-connect failures over a long hold are recorded but do not change the
verdict (two in a row abort). Samples are 60 s apart from one process: one hold is one observation, not independent replications. The watchdog's
`GetNewClosure()` form in `-TestB/-TestC` (unchanged here) does not propagate its abort flag to the waiting functions; `-LongHold` does not use it.
