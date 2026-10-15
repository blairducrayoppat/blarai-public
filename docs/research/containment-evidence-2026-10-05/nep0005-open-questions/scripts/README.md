# NEP-0005 open questions (#1763): the half-set matrix

Read `../SPEC.md` and the binding gate first. Machine-wide state exists while a state is in place: persistent Windows Filtering Platform (WFP) filters in three test
sublayers, keyed to the throwaway account `blarai-spike` (never the operator, never a real `blarai-coder`). The Rust harness `halfset` (`../harness/`) does the srt-win
installs, enumerations and single deletes; these scripts drive it, add our own objects, connect as the account and the operator, remove by key and prove the removal.
Run them from an already-elevated PowerShell 7 session in the admin-only live folder (there is no wrapper).

## Files

| File | Role |
|---|---|
| `spike-nep5-matrix.ps1` | entry: `-SelfTest [-WriteProof]`, `-DryRun`, `-Check`, `-Remove`, `-Run -Phase taskcheck\|halfset\|ours\|n1 [-Passes 1..3] [-Only R1+R2]` |
| `spike-nep5-lib.ps1` | recorded constants, our adder (C#), the harness contract (argument allowlist, outcome mapping, JSON reading), the direct sweep, removal by key, the proofs, the proof-gated add paths, the fakes |
| `spike-nep5-run-lib.ps1` | state table, listeners, the child-process launcher (clean module path; explicit minimal environment for the account's child), the account session (session password, probe run as the account, `spike-provision.ps1 -DryRun` before and `-Apply -ForceNewPassword` after, the proof of the restore), account and operator connects, the cycle, N1, the pre-cleanup, the phase runner, the run core |
| `spike-nep5-connect-probe.ps1` | what runs AS `blarai-spike` (started by the matrix with the session password): `identity`, `connect` (v4 and v6 loopback), `direct` (N1: one `FwpmFilterAdd0`, one `FwpmFilterDeleteByKey0`) |
| `spike-lib.ps1`, `spike-persist-lib.ps1`, `spike-task-driver.ps1` | the arm 3 files, loaded through `Get-VerifiedLibBlock` (read once, hashed, evaluated from those bytes) and bound into the proof. NOT edited. |
| `spike-provision.ps1` (arm 1) | run by the matrix as a child process: `-DryRun` BEFORE any password change (its own read-only precondition report; a failed precondition means no password change) and `-Apply -ForceNewPassword` at the end of every session to restore the original task credential; its hash and the hash of the `spike-lib.ps1` it dot-sources are bound in the proof and re-checked immediately before each start; NOT edited. Side effects of `-Apply`: see "Accepted residuals" |
| `spike-run-test.ps1`, `spike_model.py` (arm 2) | not run by these scripts, but `-Run` refuses (`Assert-SpikePreflight`) unless both sit beside the scripts and hash-equal the copies in `C:\blarai-spike\bin` |

Everything lives in ONE admin-only folder next to the harness files `halfset.exe`, `halfset.rs`, `Cargo.lock` (the pinned one) and the wrapped `wfp-coder-egress-spike.ps1`
(`Convert-ToLive.ps1` from arm 2 turns the bundle into the live copies). `-SelfTest -WriteProof` writes `rollback-selftest-proof-1763.json` and, only after that proof is written and
validated, `harness-live-proof-1763.json`.

## States (each: sweep, control, add, record, connects, remove by key, sweep; three passes)

R0 none; R1 srt-win full set; R2 V4 block deleted; R3 V6 block deleted; R4 both blocks deleted; R5 permits deleted; R6 stale SID; R7 our unlabelled blocks in S3 with srt-win's
status read on S1. Ours (S2): O1 V4 only; O2 V6 only; O3 permit without block; O4 exact-port permit on 127.0.0.1:61763 beside both blocks; O5 a block with no provider (attempted);
O6 a filter naming a missing sublayer (attempted). N1: the account's own token; it makes no connects, so it has no control step (step 2). Probe targets: ports 61763, its neighbour
61764 and 60085 (inside 60080-60089), each on 127.0.0.1 and [::1]; a listener that does not bind makes its rows NOT RUN (listed in the console summary and the record), never "blocked";
a timeout is recorded as a timeout and never as blocked. The accept queues of the listeners are drained before every batch of connects so a phase cannot run into the queue limit.

## Gates

* **Proof.** Every add path demands a token from `Test-N5Proof`, which re-hashes: the eight scripts of the code set, the wrapped script, the harness exe, `halfset.rs`, `Cargo.lock` (also equal
  to the pin in the library) and the harness proof file; it also needs a real self-test record (at least 120 checks, the probe's self-test passed, the harness refusal self-test with an empty
  engine-open trace) not older than 24 h. The token carries a per-process nonce and the probe-script and exe hashes it verified (the run binds to those). Edit anything and it is invalid:
  re-run `-SelfTest -WriteProof`.
* **Harness arming.** The harness refuses install, delete-filter, delete-sublayer and uninstall (exit 12) without `--live <harness proof>`. Only `-SelfTest -WriteProof` writes that file: after the
  matrix proof is written and validated (with the harness proof still staged), by rename, never in a "NO PROOF WRITTEN" branch. `-Run` and `-Remove` delete a harness proof that is older than the
  matrix proof, orphaned or not the one the matrix proof recorded. `Invoke-Halfset` appends `--live` to those four verbs and nothing else.
* **Sublayer and SID allowlists** in three places (argument vector, plan gate, C#): only S1/S2/S3; only blarai-spike's SID (which must resolve to itself) or the stale SID (which must not
  resolve); the arms' `Test-CoderSidSafe` refuses the operator's SID and every group in his token. A block without the user condition is refused in C#.
* **Direct sweep before every add** (S1/S2/S3 enumerate zero and are absent, provider absent, `netsh wfp show filters` has 0 hits for `BlarAI #1763` and `srt-win`, and for the sublayer GUIDs
  as references on filters). The export lists filters only: the absence of a bare sublayer or provider rests on the key reads (`FwpmSubLayerGetByKey0`, `FwpmProviderGetByKey0`), not on the export.
  A filter of ours or srt-win's outside S1/S2/S3 is a STOP (9), never cleaned.
* **First live action of every `-Run`: the pre-cleanup.** If S1 holds the srt-win set for the test account and nothing else is there (the reviewer-probe leftovers), `halfset uninstall --sublayer S1`
  runs and S1 must read absent by the direct checks. Any other leftover is a refusal (2) or STOP (9). **A run the pre-cleanup refused or stopped (and a run the taskcheck gate refused) removes
  NOTHING**, not even in its finally: what is there is left as found for a human; only a run that got past the pre-cleanup removes by key in its finally.
* **The account session (Lead Architect approved this design, 2026-10-13).** The task `BlarAI-Spike-Model` is a password task and cannot be re-saved without the password, so the matrix NEVER edits it. For a `-Run`
  session it (1) checks that no `session-open-1763.json` exists, that the task is in its original state and unchanged against the baseline, and that **`spike-provision.ps1 -DryRun` passes** (the restore's own read-only
  preconditions; a failure here means no password change), (2) installs the hash-checked probe copy and writes the session-open record, (3) looks the local account up **by its recorded SID**, requires its name and SID to be the
  recorded ones (anything else is refused, nothing set), and sets a fresh random password on that exact account object **by SID** (`Set-LocalUser -SID`; `New-StrongPassword`), held in a SecureString in memory: never in a file,
  task, log, record, environment variable or command line, (4) runs each account-side probe as that account (`System.Diagnostics.Process` with the account's name, domain and password = `CreateProcessWithLogonW`, profile loaded,
  hidden, working folder `C:\blarai-spike\bin`, the fixed command line printed by `-DryRun`, hard timeout, child killed at the limit, the WHOLE process tree (`taskkill /T`), so a `secedit`, `icacls` or `csc.exe` grandchild cannot outlive a timeout); the probe writes its result into `C:\blarai-spike\results` where the account already has
  Modify (no ACE is added or removed), and (5) at the end of the session, on every exit path, runs `spike-provision.ps1 -Apply -ForceNewPassword` in a child **Windows PowerShell 5.1 started with the Windows PowerShell
  module path** (a 5.1 child that inherits PowerShell 7's `PSModulePath` cannot load `ConvertTo-SecureString`), which resets the account password (invalidating the session password) and re-registers the original task with a
  new vaulted password. While the password is live a `session-open-1763.json` record sits beside the proof. **Only the session that wrote the record may delete it, and only after a proven restore** (or `-Remove` after a
  proven restore): a run refused because a record already exists leaves it untouched and reports no restore, so every later run is refused the same way until `-Remove` has re-provisioned and proven the task.
* **What the account's child is started with (token shape and environment).** The logon is an INTERACTIVE-type logon (secondary logon, `CreateProcessWithLogonW`, profile loaded), **not** the batch logon the existing scheduled task
  uses; evidence from these runs states the token shape they were taken under. The child gets an EXPLICIT environment block of exactly these variables and nothing else: `SystemRoot`, `windir`, `SystemDrive`, `ComSpec`,
  `PATHEXT`, a system-only `PATH`, the Windows PowerShell `PSModulePath`, and `USERPROFILE`, `APPDATA`, `LOCALAPPDATA`, `TEMP`, `TMP` pointing inside `C:\blarai-spike\work` (which the account can write). The operator's own
  variables (tokens, passwords, key-store paths, his profile and temp folders) are never handed over: the start info is cleared and then set, the block is built by a pure function, and the self-test starts real children
  to show what they see. Every probe run records the logon type and the environment variable NAMES supplied (names only, never values) in its record (`launch`). The probe script itself is unchanged, so what the child
  *saw* is what the self-test measured for the same launcher, not a read-back from the live child.
* **The restore is proven, never assumed.** Before the first change the task definition is recorded as `task-baseline-1763-v2.xml` beside the proof: the fields principal (UserId, LogonType, RunLevel and every other child of Principal such as GroupId and RequiredPrivileges), the Context attribute of Actions, RegistrationInfo/SecurityDescriptor when the export carries one, action
  (Command, Arguments, WorkingDirectory), every child element of Settings (MultipleInstancesPolicy, DisallowStartIfOnBatteries, StopIfGoingOnBatteries, ExecutionTimeLimit, StartWhenAvailable, Enabled, Hidden, Priority, AllowHardTerminate, RestartOnFailure, the idle settings, ...), and the number of triggers.
  EXCLUDED: RegistrationInfo (Date, Author, URI, Description) and every element outside Principals, Actions, Settings and Triggers, because a re-registration legitimately changes them (spike-provision sets none of the compared extras, so a difference there is a real change). After every session the restore needs
  all of: spike-provision exit 0; the arguments read `original`; the definition equals the baseline; and the restored task, started in its ORIGINAL form (the arms' own probe), returns a valid result as the
  account. Anything else is **TASK NOT RESTORED** (exit 9): the record and console print the manual command (`spike-provision.ps1 -Apply -ForceNewPassword`), the taskcheck record is deleted and no other phase
  will start. `-Run -Phase taskcheck` (set password, identity probe, one connect probe against a bound listener, re-provision, prove) is the first live step and must pass (for the current proof, within 24 h) before
  any other phase starts. `-Check` also compares the definition to the baseline, reads the session-open record (present = exit 21, never 20) and reports the task's last run result (a read of Task Scheduler's record of the last run, not a start: a logon-failure code reads as 21). `-Remove` reports "engine removal verified" and "task restore proven" separately. The baseline, the taskcheck record and the session
  record live beside the proof (not in the output folder); a copy in the output folder that does not match is exit 9. With no baseline, no record and no session record `-Remove` says "TASK NEVER CHANGED BY THIS MATRIX
  (no baseline on record)", still requires the arguments to read original, and only removes residue files.
* **If a restore can never be proven (a permanent refusal).** A session-open record that `-Remove` cannot clear stops every later session (fail closed), and `-Check` reads 21. When the cause is not the password (for example the task definition was changed on purpose), clear it by hand from an elevated prompt: (1) run `spike-provision.ps1 -Apply -ForceNewPassword`; (2) confirm the task starts as the account (`Start-ScheduledTask`, then its last result, or the arms' own probe); (3) delete `session-open-1763.json`, `task-baseline-1763-v2.xml` and `taskcheck-passed-1763.json` beside the proof; (4) run `-Run -Phase taskcheck` to record a new baseline. Nothing deletes the session record for you except a proven restore.
* **Self-test isolation.** `-SelfTest` builds every account environment on a stand-in root, drives the real password-write code only behind stand-in functions after a parser check that exactly one guarded write exists (with a SID that does not exist here, and only if the stand-ins are what the command names resolve to), and compares a read-only fingerprint of the real `C:\blarai-spike\work` before and after: it must leave that folder as it found it.
* **After a deliberate re-key by hand** (`spike-provision.ps1 -Apply -ForceNewPassword`) and only once you have confirmed the task works, delete `task-baseline-1763-v2.xml` beside the proof and run `-Run -Phase taskcheck` to record a new baseline; until then every session is refused as "differs from the baseline".
* **Accepted residuals of re-running `spike-provision.ps1 -Apply -ForceNewPassword` at the end of every session.** It does more than restore the task credential. Before each start the matrix hashes `spike-provision.ps1`, the
  `spike-lib.ps1` it dot-sources (both against the proof) and the two files it copies (`spike-run-test.ps1`, `spike_model.py`, which must hash like the copies already in the account's bin folder); the generated
  `spike-config.json` has no source to hash. The side effects each session accepts: it resets the account password; re-asserts Users membership and removes the account from Administrators and Power Users; REWRITES arm 1's
  rollback state file `spike-state.json` in the research-data folder (new timestamp, the operator SID of whoever ran it); runs `secedit /export` and, when needed, `/configure` on the machine's user rights (SeBatchLogonRight);
  runs `icacls /inheritance:r` on `C:\blarai-spike` and re-grants read on the operator's `.venv-2026.4`, his Python folder and the model folder (a no-op while they are present); overwrites `spike-run-test.ps1`,
  `spike_model.py` and `spike-config.json` in the bin folder; and re-registers the task with a new Description. `-DryRun` before the password change covers the preconditions it checks (venv python, base interpreter, model
  folder, account marker, ACE plan safety, SIDs); it cannot cover a later failure of the state-file write, secedit, icacls or a copy, which would leave the task unregistered (exit 9, session record kept, `-Remove` retries).
* **The first live taskcheck may report `task_not_restored` if the XML normaliser is wrong** (it was tested on hand-made samples and on the first live run's exported definition): that blocks in the safe direction; the fix is one more element in the normaliser, tested against the real exported XML.

## Exit codes

0 ok; 2 refusal / precondition (the state that refused added nothing; earlier states of the same phase are in the record); 3 unsafe target; 4 inconclusive; 5 a control failed before any filter;
7 removal NOT verified; 9 STOP (foreign filter, operator traffic affected, a finding: the account's token added or deleted a filter, or the account's task NOT RESTORED); `-Check` 20 absent /
21 present / 22 unreadable; `-SelfTest` 1 failed.

## Run order

1. `Convert-ToLive.ps1` the bundle into the live folder; place `halfset.exe`, `halfset.rs`, `Cargo.lock`, and the arm 2 `spike-run-test.ps1` and `spike_model.py` (provisioned into `C:\blarai-spike\bin`).
2. `-SelfTest -WriteProof` (under PowerShell 7; see below), then `-DryRun`.
3. `-Run -Phase taskcheck`, then `halfset`, `ours`, `n1`.
4. After every run `-Check` (20) and the removal evidence in the results file; `-Remove` at any time.

## What was NOT tested here (the builder never opens the real engine, starts the account's task or registers a task)

* **Running a child as `blarai-spike` from an elevated session** (`CreateProcessWithLogonW` through `System.Diagnostics.Process`) needs the account to be allowed an interactive logon and the Secondary Logon service to run; the account was provisioned for BATCH logon only. If it is refused, `taskcheck` reports it, the restore still runs and is proven. Also untested live: whether the hidden window and the minimal environment block behave the same under the secondary-logon path as under the plain `CreateProcess` path the self-test uses, `spike-provision.ps1` (`-DryRun` and `-Apply -ForceNewPassword`) on this machine from the matrix's child Windows PowerShell 5.1, and that the re-registered task differs from the baseline only in excluded fields.
* All engine-facing paths: our adder against the real engine, the real enumeration, the account's real denial codes (accepted as denied: 0x5 or 0x80070005 at the call; anything else is recorded and
  inconclusive), `netsh wfp show filters`, `Export-ScheduledTask`'s real XML (the normaliser was tested on a hand-made sample only), the arms' original-task probe run.
* The v6 account probe and `[::1]` listeners were exercised only against local sockets.

## Windows PowerShell 5.1 and the manual snippet

The manual rollback snippet (printed by `-DryRun`) compiles in memory under PowerShell 7. Under Windows PowerShell 5.1 `Add-Type` writes a DLL under `%TEMP%` and on this machine endpoint protection
refused to load that snippet's DLL ("Access ... is denied", reproduced with `csc` compiling it fine). The rest compiles and runs under 5.1: the matrix resets `PSModulePath` to the machine value for its own process when it starts under Windows PowerShell, so a 5.1 session started from a PowerShell 7 environment works. The self-test passes from both hosts (the snippet compile is the only skip under 5.1). Run the snippet under PowerShell 7.

## Outputs (`nep5-out` beside the scripts, admin-only, guarded against junctions, symlinks and hard links)

`nep5-results-<phase>-<run stamp>.json` (one per run, rewritten after every cycle: timestamps, clock, exact harness commands with `--live`, statuses, enumerations, account and operator rows, the sweeps
before and after, the removal steps, `pre_cleanup`), `exports-<run stamp>/export-<state>-p<n>-{before,after}.xml` (kept unless `-DropCleanExports`; each is the whole machine's filter set, a few MB),
`remove-<stamp>.json`. (`task-baseline-1763-v2.xml`, `taskcheck-passed-1763.json` and `session-open-1763.json` are beside the proof, not here.) Nothing is stripped at source; sanitise later.

## Manual rollback

`-DryRun` prints a self-contained snippet: it enumerates every filter, deletes those under S1/S2/S3 by key, REPORTS (never deletes) any other filter named `srt-win` or `BlarAI #1763`,
deletes the three sublayers and the provider. Then `netsh wfp show filters file=check.xml` and search it for `BlarAI #1763`, `srt-win` and the three sublayer GUIDs. If a run died, also restore the
task: run `spike-provision.ps1 -Apply -ForceNewPassword` from an elevated prompt (the task's arguments are `-NoProfile -NonInteractive -ExecutionPolicy Bypass -File "C:\blarai-spike\bin\spike-run-test.ps1" -RequestFile "C:\blarai-spike\bin\request.json"`), and delete
`spike-nep5-connect-probe.ps1`, `nep5-request.json` and `halfset.exe` from `C:\blarai-spike\bin`. `-Remove` does all of it, and then says whether the task restore is proven.
