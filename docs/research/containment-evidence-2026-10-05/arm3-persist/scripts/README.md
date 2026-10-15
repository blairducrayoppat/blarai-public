# Arm 3: a persistent filter set, a restart, and fail-closed on absence

Read `../DESIGN.md` first (it was written before these scripts and revised after the 2026-10-11 review). Arm 3a RAN on 2026-10-11 (claims C10a and C11);
arm 3b RAN on 2026-10-12 (claim C10) after the Lead Architect accepted a forced restart (below). Machine-wide state: these objects survive a
restart. The subject is the throwaway spike account only.

**The 3b restart is forced.** `shutdown /r /t 600` has no `/f` in its arguments, but `shutdown /?` on Windows 11 says a timeout above 0 implies `/f`: applications
are closed without forewarning when the ten minutes end. The idle gate and the input watch are the only protection for unsaved work.

**Scripts that a SYSTEM or elevated task runs must live in an admin-only folder** (for example under `C:\ProgramData\BlarAI`). `Start-ElevatedOnce.ps1`, the 3a dead-man
and the 3b arming script refuse to register or run from a folder that a non-administrator can write to (`Test-AdminOnlyFolder`; `-DryRun` shows the verdict).

## Files

| File | Role |
|---|---|
| `spike-persist-lib.ps1` | the persistent C# (fixed keys, persistent flags, non-dynamic session, delete by key), `Get-FenceState`, `Test-FenceAllowsAccount`, `Remove-FenceSet`, the only add function `Add-FenceSet`, the rollback proof and its hash binding (scripts AND the wrapped #1671 script), the admin-only folder check, the self-contained fallback rollback, the fake engine used by the self-tests, the filter export |
| `spike-task-driver.ps1` | how the operator side starts the account's task in probe mode (copied from `spike-wfp.ps1`), the preflight, `Invoke-GuardedProbe` (starts the account only if the fence is PRESENT) |
| `spike-wfp-persist.ps1` | `-SelfTest [-WriteProof]`, `-DryRun`, `-Check`, `-Remove`, `-Arm3a` |
| `spike-arm3b-arm.ps1` | `-SelfTest`, `-DryRun`, `-Live`: the arming script (idle gate, countdown, add, two SYSTEM tasks, `shutdown /r /t 600`) |
| `spike-arm3b-post-reboot.ps1` | `-SelfTest`, `-DryRun`, `-Live`: the one-shot SYSTEM startup task |
| `spike-arm3b-veto.ps1` | `-SelfTest`, `-DryRun`, `-Live`: the 30-minute veto watchdog |
| `spike-arm3b-common.ps1`, `arm3-idle-gate.ps1` | shared task definitions and state file; the idle and countdown gates (injected clocks, tested with fakes) |
| `spike-lib.ps1`, `Start-ElevatedOnce.ps1` | byte-identical to the arm 2 copies (a bundle test asserts it) |
| `Run-Arm3a-AsAdmin.cmd` | attended fallback for 3a |

## The gate in front of every add

`-SelfTest -WriteProof` runs the whole self-test, then every sibling's self-test, and only if everything passed writes `rollback-selftest-proof.json` BESIDE the scripts
(the admin-only folder): the SHA-256 (LF-normalised) of each of the ten scripts above that can add, remove or gate, the SHA-256 of the wrapped #1671 script (the code that
builds the security descriptor), the 13 rollback checks that passed, the number of checks run and passed, and each sibling's result. `-Arm3a` and
`spike-arm3b-arm.ps1 -Live` re-hash all of it and refuse (exit 2) if any script or the wrapped script differs, if a file is missing, if a check or the self-test evidence is
missing, or if the proof is older than 24 hours. After ANY edit re-run `-SelfTest -WriteProof`. There is no standalone `-Add`.
Libraries are loaded through `Get-VerifiedLibBlock` (read once; the hash is of the bytes that ran) and the wrapped script is read once by `Import-WfpHelpers`
(the proof is compared with the hash of those bytes). The 3b SYSTEM tasks get `-WfpSha256` and `-CodeSetId` and refuse to proceed on any other code set; the arming script and
`-DeadManTask` require BOTH the script folder and the output/state folder to be admin-only, and every elevated write refuses a junction, symlink or hard-linked target.

## Run order (elevated; the live folder holds the arm 1 and arm 2 files too)

1. `Convert-ToLive.ps1` (in `../../arm2-hold/scripts/`) `-Source <this folder> -Dest <live folder> -DryRun`, then `-Apply`. Provision (`spike-provision.ps1 -Apply`) after the
   arm 2 files are live so the task has the probe-mode `spike-run-test.ps1`.
2. `spike-wfp-persist.ps1 -SelfTest -WriteProof`, then `-DryRun` (it prints exactly what would be added and says whether a valid proof exists).
3. Arm 3a (the optional SYSTEM dead-man is OFF unless you add `-DeadManTask`, which also needs an admin-only folder): `Start-ElevatedOnce.ps1 -Name blarai-arm3a-run -Script spike-wfp-persist.ps1 -ScriptArgs '-Arm3a' -ThenScript spike-wfp-persist.ps1 -ThenArgs '-Remove' -LogPath <log>`
   (`-DryRun` first). The follow-up `-Remove` runs whatever the run did. `spike-wfp-persist.ps1 -Check` afterwards must exit 20 (ABSENT).
4. Arm 3b (ran 2026-10-12; repeat only after 3a is clean AND the Lead Architect has accepted a forced restart): `spike-arm3b-arm.ps1 -DryRun`, then
   `Start-ElevatedOnce.ps1 -Name blarai-arm3b-arm-run -Script spike-arm3b-arm.ps1 -ScriptArgs '-Live','-OutDir',<admin-only folder> -LogPath <log>` (pass the script arguments as separate items, and note `-OutDir` must itself be admin-only). The task name must be `blarai-arm3b-arm-run`
   (the post-reboot task deletes it, because the restart kills the arming process before it can). Leave the machine alone: 30 minutes of idle (the 2026-10-12 run used `-IdleMinutes 2` at the Lead Architect's instruction, with the earlier floor lowered for that run only; the bundled script has 30 again), a 10-minute
   countdown, a 10-minute restart timer. Then nothing: the restart, the post-reboot task and its result file.
5. After 3b: `spike-wfp-persist.ps1 -Check` (expect 20), the result file, and the second restart + egress check from brief section 5 (the post-reboot task already
   probes the account unguarded after removal; a second restart is the LA's, to confirm nothing persists).

## Manual rollback (if `-Remove` cannot run)

From an elevated PowerShell, with no other file: `spike-wfp-persist.ps1 -DryRun` prints the self-contained snippet (it is also in `spike-persist-lib.ps1` as
`$script:ManualRollbackSnippet`; `-SelfTest` compiles it, under another type name, but never runs it). It deletes the two filters, then the sublayer, then the provider,
by their fixed keys and prints each status (`0x00000000` deleted; `0x80320003`, `0x80320005`, `0x80320007` already gone). CHECK with
`netsh wfp show filters file=check.xml` and search `check.xml` for `BlarAI #1682`; `netsh wfp` has no delete verb. Keys:
provider `7e1f6a10-5c0b-4d8e-9a31-2b6d4c8e3f01`, sublayer `7e1f6a10-5c0b-4d8e-9a31-2b6d4c8e3f02`, filters `f1300003-0000-4d8e-9a31-2b6d4c8e3f21` and
`f1300004-0000-4d8e-9a31-2b6d4c8e3f22`. Also delete any left-over task: `Get-ScheduledTask -TaskPath '\BlarAI\'` then `Unregister-ScheduledTask`
(`blarai-arm3a-run`, `blarai-arm3a-deadman`, `blarai-arm3b-arm-run`, `blarai-arm3b-post-reboot`, `blarai-arm3b-veto`), and cancel a pending restart with `shutdown /a`.

## Exit codes

`spike-wfp-persist.ps1`: 0 ok; 1 `-Arm3a` account not blocked; 2 refusal (no proof, stale objects, not elevated, preflight); 3 unsafe target (the account SID is the
operator's or one of his groups) or operator traffic affected; 4 inconclusive; 5 no baseline; 6 the absence check did not refuse; 7 removal not verified;
`-Check` 20 ABSENT, 21 PARTIAL, 22 UNKNOWN. `spike-arm3b-arm.ps1`: 2, 3, 4, 5, 7 as above; 10 refused by the idle gate or no visible warning; 11 aborted by input
(rolled back); 12 armed, restart not started when the watch ended (the veto fires). `spike-arm3b-post-reboot.ps1`: 0 survived and clean; 1 survived but the account was
not blocked; 4 inconclusive (no confirmed restart, no recorded add, a repeat run, no network, engine unreadable); 6 gate did not refuse; 7 removal not verified (task kept for up to 3 attempts / 24 h, then deleted with a manual-rollback demand); 8 did NOT survive (first run, confirmed restart, add recorded); 9 partial.

## Outputs (`<StateDir>`, default `C:\Users\<user>\blarai-research-data\arm3-persist`)

`rollback-selftest-proof.json` (beside the scripts); 3a: `arm3a-<stamp>.json`, `remove-<stamp>.json`, exports `arm3a-<stamp>-filters-*.xml`; 3b: `arm3b-armed.json`,
`arm3b-arm-result-<stamp>.json`, `post-reboot-result.json` (an earlier one is renamed), `arm3b-veto-result.json` (only if it fired), exports `arm3b-filters-*.xml`.
Raw exports are not bundled (other products' filters, local paths); the JSON keeps their hashes, marker counts and keys found.

## Wrapped script and the restart decision (added 2026-10-11 after the second review)

- `-WfpScript` defaults to `wfp-coder-egress-spike.ps1` BESIDE these scripts (the admin-only folder). Its text becomes code in the calling process, so it is read once and is accepted only if pinned by hash (`-WfpSha256`) or if its folder passes the admin-only check (owners, write and delete rights on the folder and every ancestor, no links); otherwise nothing is evaluated. `-SelfTest` alone may evaluate the repository copy (`-Unverified` inside); `-WriteProof` may not.
- The proof file's folder must be admin-only too, also for an attended `-Arm3a`, and a proof that records failed checks or more checks than the self-test has is refused.
- Arm 3b `-Live` needs `arm3b-restart-decision.json` in this folder: `{"decision":"accept-forced-restart","decided_by":"<name>","decided_at":"<ISO date, at most 14 days old>","reference":"<where recorded, e.g. #1682 comment>"}`. An administrator writes it after the Lead Architect decides; no script writes it. `Start-ElevatedOnce.ps1` will not run `spike-arm3b-arm.ps1` without it.
