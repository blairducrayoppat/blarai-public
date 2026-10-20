# MXC denied-subtree probe: pre-run review, round 6 (fx-c variant)

- Reviewed: branch `feat/mxc-denied-subtree`, commit `261737de`, `tools/probes/mxc_denied_subtree/` only; diff against `b1cb40e3` (the round-5-approved harness).
- Reviewer: independent, non-elevated, 2026-10-15 (22:54-23:29 UTC).
- **Verdict: FAIL.** Approval NOT written; `APPROVED_SHA256.txt` still carries the round-5 hashes for `b1cb40e3`, so `launch.ps1` refuses the `261737de` files.
- Self-test at `261737de` under the non-elevated runner: `187 passed, 0 failed`, exit 0, including all 16 new fx-c checks. The probe directory still holds only `.py` and `.ps1` files, and `git status` of `tools/` is clean. The lock "fx-c verdict STOPPED-STATE-CHANGE (toolchain ACL not restored)" covers more than it tests: every fixture behind it is a completed launch (`payload_present: True`), so it does not reach finding 1.

## Findings, most severe first

1. **MEDIUM-HIGH. The summary verdict contradicts the record when an fx-c launch fails and leaves host state.** `summarise.py` runs the fx-c state checks (`state_left`: DENY ACE or ACL change left on T/sub, toolchain ACL not restored, MXC state changed) only over `done`, the completed launches. If a launch runs but no report comes back, `run_probe.py` prints `STOP: STOPPED-STATE-CHANGE: ...` and keeps the tree, but `summary.json` reads `LAUNCH-FAILED` with `state_left: []`.
   - When it fires: the first Tier-3 run with `leastPrivilege` (a less-privileged AppContainer) is the run most likely to fail to start Python. If MXC also leaves its grant on the toolchain, the closing verdict, which is the line people act on, does not say so.
   - Reproduced by building synthetic records with the self-test's own helpers and passing them to `S.verdict`. The record was launched, had no payload, `ace_left=True`, `tc_ok=False`, plus a smoke record on appcontainer-dacl:
     `failed launch + ACE left + toolchain changed -> LAUNCH-FAILED state_left= [] variant= fx-c` (the same result with three such launches).
   - The same shape exists for fx-a at `b1cb40e3`, but there it is inert: Tier 1 does not change any DACL.
2. **MEDIUM. The smoke launch is a Tier-3 launch and nothing checks its cleanup.** `run_smoke` (run_probe.py:213-296) runs the fx-c policy: grants on the toolchain and payload, and a DENY ACE on the smoke tree's sub. It checks only the MXC state directory; `acl_capture` appears 0 times in that function. The toolchain baseline is taken per launch (`tc_before`, line 317), and the header has no toolchain ACL at batch start or end. So a grant the smoke launch leaves on the toolchain becomes fx-c-r1's "before", and every later comparison reports it as unchanged.
   - Status: hypothesis about the consequence. The absence is fact (grep count 0; the header keys are listed in the run-20261015-2 header). Not run, because the fake launcher has no smoke mode that leaves an ACE.
3. **MEDIUM. The check for "toolchain ACL restored" compares only the toolchain root directory.** `acl_capture(tools["toolchain"])` reads one SDDL. The container interpreter `C:\blarai-spike-1740\toolchain\Python314\python.exe` and every other descendant are never captured, so the brief's "container python: confirm restored" is not measured.
   - Today every toolchain entry carries inherited ACEs only (icacls, run during this review), so a root restore normally re-propagates. A propagation that fails on a child would still be invisible.
4. **LOW. The host-prep detector is looser than its question.** `sddl_grants_appcontainer` accepts any allow ACE for AC or S-1-15-2-2, with any mask, inherited or not, and either SID alone. Reproduced: `AC wrong mask (0x1) -> True`, `inherited AC (ID) -> True`, `AC only, no RAP -> True`.
   - Under `leastPrivilege` the token draws on ALL RESTRICTED APPLICATION PACKAGES (S-1-15-2-2), not AC, so an AC-only grant passes the detector without being the prep the run needs.
   - Reachability is low: the detector is consulted only when MXC's own dry-run still recommends the prep, and the operator's real prep adds the exact pair.
5. **LOW. The batch holds no evidence of the host prep it depends on.** After `prepare-system-drive`, MXC stops printing the recommendation, so `host_prep` is `[]`. The header's hard-coded `"host_prep_ran": false` then reads as "host not prepared", and the harness never records the system-drive root SDDL. The result depends on a host change that no batch file shows.
6. **LOW. Docstring prose has not caught up with fx-c.** WHAT IT DOES NOT MEASURE (run_probe.py:44-55) does not name:
   - that fx-c has no denial capture;
   - that fx-c differs from fx-a in three things at once (tier, leastPrivilege, captureDenials), so neither a HOLD nor a FAIL can be attributed to one of them;
   - the toolchain descendants;
   - the `\Device\Null` prep state.

   The header records `variant` and the per-launch `config`, but it has no departure note. The spec's captureDenials block is absent from fx-c with no recorded departure beyond the docstring.
7. **INFO (operator check). The two SDDL readers disagree on ACE order.** `(Get-Acl C:\).Sddl` returns the ACEs in a different order than the native `GetNamedSecurityInfoW` read that the probe uses. The same ACEs come back in both, and the saved `c-root-sddl-before.txt` matches `Get-Acl` today (True). `unprepare-system-drive` revokes the SID and replays the remaining ACEs, which can reorder them. Compare as a set, as in the commands below.

## Attacked and not broken

- **Tier assertion.** `expected_tier` is appcontainer-dacl for fx-c. It is used for the smoke dry-run, for every S2 dry-run, and for `S.verdict`. A dry-run tier of base-container under fx-c gives TIER-MISMATCH with nothing launched (e2e `held` mode). fx-c without `--allow-dacl-tier` is refused before anything is written.
- **DENY ACE during the run.** `watcher` captures T/sub (and now T, the dacl-restore directory and the toolchain) only after the payload's ready flag, while `proc.poll() is None`. The payload holds its S2 attempts until it is released, so the capture is taken while the container is alive and before the attempts. MXC documents T3 `deniedPaths` as a host DENY ACE (os-version-support.md:109), so "no DENY ACE observed" reading INSTRUMENT-BLIND matches the docs. That check is in both `run_probe` and `summarise`, and only over completed launches, so the smoke record does not trip it.
- **Landing judgement is unchanged from `b1cb40e3`.** `landing.py`, `payload.py`, `smoke_payload.py` and `launch.ps1` have no diff. FAIL still comes first in both `run_launch` and `verdict`. ACL changes are not landings: the snapshot covers kind, size, sha256, read-only/hidden/system, file mtime and streams, with no ACL and no change time, and "per-entry ACL changes inside T/sub" is listed as not measured. So the expected Tier-3 DENY ACE, and anything Bitdefender does to ACLs, cannot count as a landing. The e2e `t3ok` mode applies an inheritable deny to sub and expects HOLD.
- **No false HOST-PREP-REQUIRED after the prep.**
  - MXC's string in `wxc-exec.exe` is ``Run `wxc-host-prep prepare-system-drive` (elevated)``, which the regex matches.
  - The live `C:\` reads False today.
  - The live `C:\` plus `(A;;0x120088;;;AC)(A;;0x120088;;;S-1-15-2-2)` reads True, appended or prepended.
  - After the prep, MXC suppresses the recommendation, so nothing is checked at all.
  - If a reboot happens after the null-device prep and `\Device\Null` resets, the dry-run would name `prepare-null-device`, which counts as not in effect. That is a fail-closed stop, not a false PASS.
- **S5 is disabled for fx-c** (`s5_applicable` requires fx-a).

## Elevation

Run fx-c elevated, the same as fx-a. Reasons:
- It holds every variable fx-a held except the policy: tree ownership under `C:\mxc-fx` (owned by BUILTIN\Administrators, created elevated), the same token, and the same guarded-privilege check (SeBackup and SeRestore present but disabled in the elevated token, refused if enabled).
- MXC's Tier-3 DACL writer needs WRITE_DAC on every granted or denied path. The elevated token has it on the BA-owned tree, and the operator owns the toolchain.
- The operator is already elevated for the host prep, so one window covers both.

## Operator command sequence (elevated PowerShell 7), for when an approved harness exists

```powershell
# 0. snapshot (also closes findings 2-3 externally): C:\ root and the whole toolchain
$hp="$env:USERPROFILE\blarai-research-data\mxc-denied-subtree\host-prep"
icacls 'C:\blarai-spike-1740\toolchain' /save "$hp\toolchain-acl-before.txt" /T /Q
# 1. host prep
& 'C:\blarai-spike-1740-mxc\dl\x64\wxc-host-prep.exe' prepare-system-drive
(Get-Acl C:\).Access | ? { [uint32]$_.FileSystemRights -eq 0x00120088 -and -not $_.IsInherited } | ft IdentityReference,FileSystemRights
# 2. the batch (3 runs)
pwsh -NoProfile -File "$env:USERPROFILE\BlarAI-worktrees\mxc-denied-subtree\tools\probes\mxc_denied_subtree\launch.ps1" `
  --v100-launcher 'C:\blarai-spike-1740-mxc\dl\x64\wxc-exec.exe' `
  --main-launcher 'C:\blarai-spike-1740-mxc\build-main-20261015\target\x86_64-pc-windows-msvc\release\wxc-exec.exe' `
  --container-python 'C:\blarai-spike-1740\toolchain\Python314\python.exe' `
  --toolchain 'C:\blarai-spike-1740\toolchain' --variant fx-c --allow-dacl-tier --runs 3
# 3. undo host prep
& 'C:\blarai-spike-1740-mxc\dl\x64\wxc-host-prep.exe' unprepare-system-drive
# 4. compare (set-wise; expect both True and no output from the last line)
$b=(Get-Content "$hp\c-root-sddl-before.txt" -Raw).Trim(); $a=(Get-Acl C:\).Sddl
$aces={ param($s) ([regex]::Matches(($s -split 'D:',2)[1],'\([^)]*\)').Value | sort) -join '' }
($a -split 'D:')[0] -eq ($b -split 'D:')[0]; (& $aces $a) -eq (& $aces $b)
Compare-Object (Get-Content "$hp\c-root-acl-before.txt" | % Trim | sort) ((icacls C:\) | % Trim | sort)
icacls 'C:\blarai-spike-1740\toolchain' /save "$hp\toolchain-acl-after.txt" /T /Q
Compare-Object (Get-Content "$hp\toolchain-acl-before.txt") (Get-Content "$hp\toolchain-acl-after.txt")
```

## Merge read

Block on 1 and 2. Both are the brief's own requirement, that Tier-3 host state left behind reads STOPPED-STATE-CHANGE, and both fail in the most plausible first-run shapes: a failed LPAC launch, and the smoke launch. Finding 3 should ride with them: capture `python.exe`, or a recursive toolchain listing, at batch start and end. Findings 4-6 do not block alone. Finding 7 is operator procedure. The landing judgement, tier assertion, DENY-ACE timing and host-prep pass-after-prep held under attack.
