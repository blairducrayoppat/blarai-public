# Arm 1: the permit filter's role, and the confined account as a CLIENT of a real local server

Question: with the raw WFP block keyed to the throwaway account in place, can that account reach a real local model
server over loopback, and does that depend on the loopback PERMIT filter (ALE_AUTH_CONNECT, IS_LOOPBACK + user)?

## What changed against `post-run-hardened/` (the line counts are in `CHANGES.md`)

| File | Change |
|---|---|
| `spike-wfp.ps1` | `-TestC` (one invocation = one engine session: operator-run server, account baseline, block, account run under the block, removal, account run after) and `-NoLoopbackPermit` (the two BLOCK filters only; the #1671 C# is read, never edited: the permit entries are dropped from the plan list in PowerShell). Exit 0 / 9 are both results. Exit 9 needs a Windows socket error code on the POST (the block's signature); an HTTP error or read timeout is exit 4, not a result. `-SelfTest` covers both sets, the verdict table, the client schema and a JSON round-trip on the running host; `-DryRun` prints both sets. |
| `spike-run-test.ps1` | `client` mode: identity, ONE POST to `http://127.0.0.1:<server_port>/` (port validated, host fixed), the 1.1.1.1:443 probe with the Windows socket error code. No model, no memory or file steps. |
| `spike-lib.ps1` | the strict result schema knows `mode=client` and its step list; `Resolve-PrivilegeLine` takes `-Name` (see the cleanup row). |
| `spike_model.py` | `--stop-file`: the operator ends the server it started, so its request log is written. |
| `Run-Arm1-AsAdmin.cmd` | elevation prompt, `wsl --shutdown`, six runs interleaved (on, off, on, off, on, off), each its own process. |

| `spike-cleanup.ps1`, `spike-provision.ps1` | one call-site change: the batch-logon right is matched by the account NAME as well as its SID. Found after the arm's cleanup: `secedit` writes a holder whose account still exists by name, so the SID-only match said "already absent" at step 5 and the verify found the orphaned SID after the account was deleted at step 7. The cleanup also reads the SID from `spike-state.cleaned.json` when the live state file and the account are both gone (as the verify does), so a re-run can still remove that SID's traces; and when `icacls` returns 1332 (it refuses a SID it can no longer map to an account, even in `*SID` form) the ACEs are purged by SID through the .NET ACL API instead. |

`spike-verify-cleanup.ps1` is unchanged from `post-run-hardened/`.

## Run order (elevated, Lead Architect present; only on a machine you can reboot)

1. Finish any earlier cleanup: `spike-verify-cleanup.ps1`; if the profile folder is left from an earlier run, reboot,
   `spike-cleanup.ps1 -DryRun` then `-Apply`, verify again.
2. `Run-Spike-AsAdmin.cmd` (provision the throwaway account). At least 14 GB free RAM.
3. `spike-wfp.ps1 -SelfTest`, `spike-wfp.ps1 -DryRun`, `spike-wfp.ps1 -DryRun -NoLoopbackPermit` (nothing changes).
4. `Run-Arm1-AsAdmin.cmd` (the six runs; Windows PowerShell 5.1), or by hand in either host: `spike-wfp.ps1 -TestC [-NoLoopbackPermit] -BlockMaxSeconds 240`. Reports are named `testc-<on|off>-<stamp>.json`.
5. `spike-cleanup.ps1 -DryRun`, `-Apply`, `spike-verify-cleanup.ps1`.

## What each run records (`runs/testC-<on|off>-<stamp>.json`)

`filter_set`; `env` (clock, uptime, OS, Windows build, PowerShell host, Bitdefender processes, firewall profiles, BFE and
mpssvc, WSL state); `server` (type, port, pid, bound address, model_loaded, health, stop record with the server's own
request log); `steps.operator_baseline`; `steps.account_baseline` (the full task result: identity, client_connect,
outbound_probe); `steps.filters_added` (timestamp, ids, names: 4 or 2); `steps.account_during` (its `client_connect.error_code` is what separates a socket-level denial from a server-side failure); `steps.watchdog`;
`steps.operator_during`; `steps.engine_closed_at`; `steps.removal_engine_check`; `steps.operator_after_removal`;
`steps.account_after_removal`; `decision_inputs`; `exit_code`, `exit_reason`.

## Caveats that still bind

The probe counts ANY failure as blocked: the account's baseline (filters absent) and post-removal runs are what attribute
a block to the filters. Bitdefender's own sublayers are the unknown; a block in another sublayer cannot be undone by our
permit. The dead-man (BlockMaxSeconds+30) and the operator watchdog are not optional. Three runs per condition on one
machine inside one sitting are a repeat, not independent replications.
