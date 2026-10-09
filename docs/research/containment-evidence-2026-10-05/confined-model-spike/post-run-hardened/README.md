# #1689 confined-inference spike: can a restricted account run the 4B on the Arc 140V with no network?

Throwaway local account `blarai-spike`; batch logon only (no interactive session); RunLevel Limited; scheduled task
`\BlarAI\BlarAI-Spike-Model`. Question: does OpenVINO GenAI reach the iGPU from that account, and can it serve a
completion over loopback while a raw WFP block keyed to the account denies all its outbound connects?
Everything here was built and self-tested with no system change; the live steps are run by the lead.

## Files

| File | Role |
|---|---|
| `spike-lib.ps1` | pure helpers (ACE plan + safety invariants, privilege-line logic, strict result schema, config) |
| `spike-provision.ps1` | `-SelfTest` / `-DryRun` / `-Apply`: account, right, tree, ACEs, files, task |
| `spike-run-test.ps1` + `spike_model.py` | what the task runs AS the account (copied into `C:\blarai-spike\bin` by provision) |
| `spike-wfp.ps1` | operator side: `-SelfTest` / `-DryRun` / `-TestA` / `-TestB` (wraps the #1671 WFP script) |
| `spike-cleanup.ps1` | `-SelfTest` / `-DryRun` / `-Apply`: removes everything |
| `spike-verify-cleanup.ps1` | read-only: asserts every trace is gone (`-Quick` = top-level ACL scan) |
| `Run-Spike-AsAdmin.cmd` | double-click: UAC prompt, printed dry-run listing, type YES, then `-Apply` |

## Run order (elevated shell, 64-bit; both PowerShell 5.1 and 7 work)

1. `Run-Spike-AsAdmin.cmd` (or `spike-provision.ps1 -DryRun`, then `-Apply`). Check free RAM first: the 4B needs ~10 GB In-Use; the run refuses below 14 GB free.
2. `spike-wfp.ps1 -DryRun` (prints the plan; does not open the WFP engine), then **Test A**: `spike-wfp.ps1 -TestA` (feasibility, no block).
3. **Test B**: `spike-wfp.ps1 -TestB [-BlockMaxSeconds 420] [-ServeHoldSeconds 60]`.
4. `spike-cleanup.ps1 -DryRun`, then `-Apply`, then `spike-verify-cleanup.ps1` (exit 0 = clean).

Outputs: task result `C:\blarai-spike\results\result-<run>.json` (strict schema, validated by `Test-SpikeResultSchema`); operator
reports `runs\testA-*.json`, `runs\testB-*.json` here. Both belong in PERFORMANCE_LOG.md + `docs/performance/` once run (this is a hardware measurement: record load time, first-token, tok/s with free RAM and thermal state; speed numbers need the repo's cold-GPU gate before they are compared with in-process figures).

## What each step changes

* **Provision `-Apply`**: local user `blarai-spike` (Users only; random 24-char password held only in the task credential vault); `SeBatchLogonRight` for its SID; `C:\blarai-spike\{bin,work,work\tmp,results}` with a protected DACL (operator + SYSTEM + Administrators full; spike traverse-only on the root; not Authenticated Users); spike **RX** on the 2026.4 venv, its base interpreter (`...\Python311`) and `B:\models\Qwen3.5-4B-int8-ov`; spike **Modify** on `work` and `results` only; copies of the run script, `spike_model.py`, generated `spike-config.json` into `bin` (read-only to the account); the task; `spike-state.json` (SID + paths, no secret). No ACE on any operator secret path. No firewall rule.
* **Test A**: writes `bin\request.json`, starts the task. No system object created.
* **Test B**: additionally adds a DYNAMIC WFP session (provider, sublayer, 4 filters keyed to the spike SID; same keys and C# as #1671). Removed when the engine handle closes, when the process dies, or by the dead-man at BlockMaxSeconds+30. Operator watchdog: two consecutive failed connects to 1.1.1.1:443 abort and remove (exit 3).

## Rollback

`spike-cleanup.ps1 -Apply` (idempotent; stops at first error; safe to repeat): task, processes owned by the SID, spike-SID ACEs only (`icacls /remove:g` and `/remove:d`, never a reset), `C:\blarai-spike`, `SeBatchLogonRight`, profile registration + `C:\Users\blarai-spike`, the account. Then `spike-verify-cleanup.ps1`. A stuck WFP block: end the `spike-wfp.ps1` process (or reboot): nothing is persistent. Manual check: `netsh wfp show filters` and search for `BlarAI #1671`.

## Findings made while building (read-only observations, 2026-10-05)

* `B:\models` inherits **Authenticated Users: Modify**. The model dir is therefore already readable AND writable by any local account including `blarai-spike`; the spike's ACE there changes nothing today. Test A/B record a write to `B:\models` as informational. For the real `blarai-model` design the model dir needs a protected DACL (read-only for the model account) or the weights are tamperable by the account that loads them.
* The venv carries a pre-existing orphan-SID ACE (`S-1-5-21-1000000004-...-2931813655`, `RX,W`, inherited). Unrelated to this spike; `spike-verify-cleanup` searches for the spike SID only.
* Both PowerShell hosts matter: when `powershell.exe` is launched from pwsh 7 the inherited `PSModulePath` hid `Get-FileHash`; the scripts use .NET instead.

## Not verifiable without the live run

GPU access from a batch-logon session; whether OpenVINO's GPU plugin finds the driver as this account; load time and memory for the account; WMI memory read as a Limited user; the `icacls` propagation behaviour on the 77k-file venv (grant/remove are made without `/T`, relying on inheritance propagation; `spike-verify-cleanup` scans the whole tree to prove removal); that Bitdefender does not interfere with a new account's process or the loopback listener; whether `Start-ScheduledTask` proves started within 22 s on this box.

## Link safety and trust boundaries (added after an automated review of these scripts, 2026-10-05)

* The account could write `C:\blarai-spike\work`, `results` and its own profile. Cleanup therefore never runs `Remove-Item -Recurse` on those trees:
  `Remove-TreeNoFollow` (spike-lib.ps1) enumerates with .NET without entering reparse points, removes every junction or symlink as a link only,
  and refuses (before deleting anything) a hard-linked file with a name outside the tree. `-SelfTest` drives real junctions, hard links and symlinks.
* Every `icacls` target is checked first (`Assert-AclTargetPlain`): no wildcard characters, not a reparse point. Provision refuses a reparse point at `C:\blarai-spike`.
* `secedit` files live in a private temp directory with a protected DACL (`New-PrivateTempDir`), not loose in `%TEMP%` (which can carry a foreign write ACE).
* The operator reads files the account wrote (result, serve-port) only through `Read-UntrustedJson`: no link or hard link, 4 MB cap (64 KB for the port file),
  strict schema, integer port 1024..65535, host fixed to 127.0.0.1; no path, host or command from the content is ever used.
* Password: generated in memory, passed only to `Register-ScheduledTask -Password` (a CIM call, not a process command line), zeroed afterwards, never printed,
  logged or saved. `spike-provision.ps1 -SelfTest` fails if any script uses `schtasks /RP` or `net user`, or writes a password variable to host or file.
* Race reduction in cleanup: it first disables the account and the scheduled task, stops every process owned by the SID and CONFIRMS zero remain (20 s bound; it
  refuses to proceed otherwise). Each tree entry is classified at enumeration and its attributes re-read by literal path immediately before the delete; an entry
  that changed kind (for example a directory swapped for a junction) is a failure: stop, delete nothing further. `-SelfTest` proves this with a hook that swaps a
  directory for a junction between the two steps.
* Residuals: a race between the final attribute re-read and the delete call cannot be closed without handle-based deletion; with the account disabled and processless
  it would need an administrator-level actor, which is out of scope. Only the file and its
  immediate folder are link-checked on read; `spike-verify-cleanup.ps1` runs `icacls /T /C` over the venv, interpreter and model trees, which the account could only read.
