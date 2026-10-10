# Disposition — adversarial review of the arm 1 spike scripts before their live run (#1718)

**Review:** an independent adversarial-reviewer agent (did not author the scripts), 2026-10-09 17:24 -04:00,
against the live copies under the operator's research-data folder (the sanitised copies are
`docs/research/containment-evidence-2026-10-05/arm1-permit/scripts/`; the fixes are commit 8db95d00 on branch track-b-arms-brief-b802c9). It ran every `-SelfTest` on both PowerShell
hosts, `-DryRun -NoLoopbackPermit`, the python self-test, a batch-file simulation with a stub, and same-shape fixtures
for the control-flow and typing findings; it opened no WFP engine and loaded no model.
**Author of the scripts and of this disposition:** this session.
**Outcome:** nine findings; all nine fixed in the same change, none deferred, none rejected. The live run had not
started when the review ran, so nothing banked rests on the pre-fix verdict table.

```disposition
F1 the exit-5 (no-baseline) path returned from inside the try, so the finally ran but the report was never saved: the likeliest first-live-run outcome would have thrown away its evidence | FIXED | 8db95d00 docs/research/containment-evidence-2026-10-05/arm1-permit/scripts/spike-wfp.ps1 Invoke-TestC - no return inside the try; the block, removal and after-run phases sit under `if ($obs.BaselineOk)` and every path reaches Save-OperatorReport
F2 exit 9 (POST failed under the block, a counted result) was reachable on an HTTP 500 or a read timeout, which carry the same ok/status shape as a WFP-denied connect | FIXED | 8db95d00 spike-wfp.ps1 Get-TestCVerdict + Invoke-TestC - 9 now requires a non-zero Windows socket error code on the POST (ClientSocketDenied); a failure without one is 4; self-test rows 'client failed WITH a socket error code -> 9' and 'WITHOUT -> 4, never 9'
F3 under PowerShell 7 every real result failed the strict schema (ConvertFrom-Json yields [datetime], Test-IsoTimestamp required [string]) while -SelfTest passed because its fixtures never crossed JSON | FIXED | 8db95d00 docs/research/containment-evidence-2026-10-05/arm1-permit/scripts/spike-lib.ps1 Test-IsoTimestamp accepts [datetime]/[datetimeoffset]; ConvertTo-DateTimeOffset replaces the Parse calls; spike-wfp.ps1 self-test now round-trips a client result through ConvertTo-Json/ConvertFrom-Json on the running host
F4 preflight checked only the presence of the task's copies of spike-run-test.ps1 and spike_model.py; a stale copy without client mode would wait out the full result timeout and, with F1, leave no report | FIXED | 8db95d00 spike-wfp.ps1 Assert-SpikePreflight compares SHA-256 of bin\spike-run-test.ps1 and bin\spike_model.py with this folder's files and names the re-provision step
F5 after a watchdog abort the block-phase wait continued up to 230 s with the engine already closed, and no watchdog ticks ran during the task-ready and start-proof waits (up to about 52 s of live filters with no operator probe; the dead-man still covered it) | FIXED | 8db95d00 spike-wfp.ps1 Wait-SpikeResult, Wait-SpikeTaskReady and Start-SpikeTaskProved take the tick and return as soon as $script:opAbort is set
F6 exit 7 (removal NOT verified) was also produced when removal WAS verified but the after-run did not start, so the summary line misstated the report | FIXED | 8db95d00 spike-wfp.ps1 - a separate AfterRunValid observation returns 4; RemovalVerified is false only for an object left, an operator connect failure, or a valid after-run that still shows the account blocked; self-test row 'after-run invalid -> 4, not 7'
F7 report file names carried neither the condition nor the run id, so six interleaved files were indistinguishable from the listing | FIXED | 8db95d00 spike-wfp.ps1 Save-OperatorReport -FileName; Test C reports are named testc-on-STAMP.json or testc-off-STAMP.json; the arm README says so
F8 a lingering account process could pre-plant results\result-<id>-block.json during phase 1 (the id is readable from bin\request.json) and Wait-SpikeResult returned the first file that existed | FIXED | 8db95d00 spike-wfp.ps1 Invoke-ClientTaskRun refuses a result whose started timestamp predates the request (5 s skew allowance) or whose run_id differs; outside the experiment's threat model, closed anyway
F9 $args assigned as a local in Start-OperatorServer shadowed an automatic variable (worked on both hosts) | FIXED | 8db95d00 spike-wfp.ps1 - renamed to $argv
```

## What the review attacked and could not break (recorded so a later pass does not re-litigate)

- Trust boundary: no field of the account-written `client_connect`, `outbound_probe` or `identity` data is used as
  a path, host, command or port by the operator; the server port the operator trusts comes from its own folder's
  port file, validated as an integer in 1024..65535, host pinned to the literal 127.0.0.1, and flows to the account
  through the read-only `bin\request.json`.
- Run-id keying per phase (`-base`, `-block`, `-after`) with a per-invocation second stamp: no cross-phase read.
- `ClientOkUnderBlock` cannot be true with `model_loaded=false`; a server without its model returns 8 before the
  client observations are consulted.
- Engine lifetime: every path out of the try closes the engine in `finally`; `AddAll` aborts its transaction on any
  add failure; the dead-man (BlockMaxSeconds+30) outlasts the block-phase wait by 40 s.
- `-NoLoopbackPermit`: the two-filter plan is refused by `Test-ArmPlanInvariants` before `AddAll` if a permit entry
  survived; `Marshalled.Build` iterates the filtered list, so FwpmFilterAdd0 sees exactly it; the removal check
  looks up all four keys regardless of set.
- Both hosts parse and self-test the scripts; the batch file's subroutine, error-level capture, delayed expansion
  and stop-on-non-result behaviour were simulated with a stub for the sequences 0 9 0 9 0 9, 0 9 1, 3, 0 9 9 0 0 7
  and 2.

## What this cost, and what caught it

The review ran about ten minutes and reproduced F1, F2 and F3 with fixtures rather than asserting them. F3 is the
one to remember: a self-test whose fixtures are built in memory certifies nothing about the file the real run
reads; the lock now crosses the same JSON boundary the run does.
