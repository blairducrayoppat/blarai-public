# Arms 2 and 3a: the scripts as they ran

Both arms ran on 2026-10-11 from an admin-only live copy (`C:\ProgramData\BlarAI\trackb-live`) made from commit `aab46664` by replacing the user-name placeholder `_OPERATOR_` with the real name
(`Convert-ToLive.ps1`), started through `Start-ElevatedOnce.ps1`. Arm 2 started 14:48:39, arm 3a 16:51:27. The live copy was compared with that commit after the runs (this file records the result);
the bundled scripts have since CHANGED (commits `02cb0953`, `aa3b46e7` and the follow-up commits after the independent reviews). The results here come from the as-run versions, not from today's files.

| File (in this bundle) | SHA-256 as run (LF-normalised, live copy) | live copy equals `aab46664` with the name substituted | arm 3a proof recorded this hash | changed in the bundle since the run |
|---|---|---|---|---|
| `arm3-persist/scripts/spike-lib.ps1` | `D3CAC17824EAAEFE2FE76B48CC031D0E63DC2A9E8143A0D139394122E51189A1` | yes | yes | no |
| `arm3-persist/scripts/spike-task-driver.ps1` | `D4F80E78055E2256F1E0F536DAACDDC5CA0106EA3DD3EEA6E5E81C0C97BC1CCE` | yes | yes | no |
| `arm3-persist/scripts/spike-persist-lib.ps1` | `BF027A02DD311A63B2FE0D2FACC859C94D6F1A7FD1B2B14DC525E46C62CE65E9` | yes | yes | yes |
| `arm3-persist/scripts/spike-wfp-persist.ps1` | `9B377E3336B9EBE39A803590BF66356F6CE6D28E5A700D0163FF838D6765A70F` | yes | yes | yes |
| `arm3-persist/scripts/spike-arm3b-common.ps1` | `0C396569343C699DDB3C941B0A279760DFEE02D586C017318063C6044928C3F5` | yes | yes | yes |
| `arm3-persist/scripts/spike-arm3b-arm.ps1` | `ED375CD365C16DDF9D74D36156DFDE81CBA1706747B9BC9900C7FE905CD2F753` | yes | yes | yes |
| `arm3-persist/scripts/spike-arm3b-post-reboot.ps1` | `814B13249923C51156423C18D9AE4F464C7E65AF5E5272E6056A216FECF8002B` | yes | yes | yes |
| `arm3-persist/scripts/spike-arm3b-veto.ps1` | `1EF9F32856453BC831CE83A199D7CF9EC861703893079C824138FEF7664CCB8A` | yes | yes | yes |
| `arm3-persist/scripts/arm3-idle-gate.ps1` | `52862DD9BEE4F72D9EA70ACB98C95F0FBA6BC3CCF9D866C7DF27D67ACBC3D580` | yes | yes | yes |
| `arm3-persist/scripts/Start-ElevatedOnce.ps1` | `41BF5357C5C6BB37F7EDDB86542FA5654D044FAFFB627C95F80E0F5709BD9A64` | yes | yes | yes |
| `arm2-hold/scripts/spike-wfp.ps1` | `51C0B76D2A0D14549C41F04265B02DF5CE1CB754D628E9FCE99CAEB2F05C01DE` | yes | not applicable (not in the arm 3 code set) | no |
| `arm2-hold/scripts/spike-run-test.ps1` | `2B1D0D6417EBE726F096B232836F426F0ECA335308BCC876B3A9EBE1C6644D0A` | yes | not applicable (not in the arm 3 code set) | no |

The wrapped #1671 script used in both arms was the admin-only copy `wfp-coder-egress-spike.ps1` in the same folder; its SHA-256 (LF-normalised) is `EA3E03A37D0DB00570927B8F1C98D2EFAB53EA5BD203909BBBB70A3DE0CFDA6D`, equal to the arm 1 live copy and to the bundled `wfp-spike/wfp-coder-egress-spike.ps1`
(`EEE26686DFCD1B83B5EE731E14C9A07173F42C6E724CEAF2937C59F1D86179FE`) with the user-name placeholder substituted.

Arm 3a was run with `-WfpScript` naming that admin-only copy explicitly and with `-NoDeadManTask` (the parameter of the as-run script; the current scripts have the opt-in `-DeadManTask` instead). This
comes from the lead's account of the run; the banked wrapper log records the outcome but not the command-line arguments. In the as-run scripts the default `-WfpScript` was the user-writable
`blarai-research-data\wfp-spike` path and the wrapped script's text was evaluated before any hash or proof check; both are fixed in the current scripts (the review of 2026-10-11 found it).

Accounts: arm 1 (2026-10-09) ran against a throwaway account named `blarai-spike` with relative id 1011; its cleanup deleted it. Arms 2 and 3a ran against a newly provisioned account of the same
name with relative id 1271: two different accounts (and two different SIDs), not one.

## Arm 3b (2026-10-12)

Run `arm3b-20261012-150113` ran from the admin-only live copy of commit `68106f0f` (branch `feat/1682-arm3b-run`; the live copy was compared with the commit through `Convert-ToLive.ps1 -DryRun`, all twelve files `same`). It differs from the 2026-10-11 main by one change: the idle floor of `spike-arm3b-arm.ps1` was lowered from 30 to 2 minutes at the Lead Architect's instruction for this run only, and the run passed `-IdleMinutes 2`. After the independent review the bundled script has the 30-minute floor again (so the bundled `spike-arm3b-arm.ps1` is NOT the as-run file: it differs by that floor and by header comments that said NOT RUN), and the bundled `spike-arm3b-post-reboot.ps1` and `spike-arm3b-veto.ps1` differ from the as-run copies in a header comment only. The rollback proof (116 checks) was written for these files before the run. The wrapped script was the admin-only copy beside the scripts. The output folder was `C:\ProgramData\BlarAI\arm3b-out` (admin-only); an output folder writable by the operator's account is refused by the arming script (that refusal is the second launch attempt in `wrapper-arm3b-attempts.txt`). The account was the arm 2 and 3a account (relative id 1271).
