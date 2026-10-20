# MXC denied-subtree probe: pre-run review, round 7 (fx-c variant, targeted verification)

- Reviewed: branch `feat/mxc-denied-subtree`, commit `d1de3242`, `tools/probes/mxc_denied_subtree/` only. The diff against `261737de` (round 6) touches only `fixtures.py`, `run_probe.py`, `self_test.py` and `summarise.py`.
- Reviewer: independent, non-elevated, 2026-10-15 (23:33-23:45 UTC). I did not write this code and did not do round 6.
- **Verdict: PASS.** No BLOCKER or HIGH findings. The round-5 approval is kept as `APPROVED_SHA256.round5.txt`. The new `APPROVED_SHA256.txt` is headed `# approved 2026-10-15T23:38:42Z commit d1de3242 reviewer non-elevated round 7`. Its hashes come from certutil run under the non-elevated runner.
- `launch.ps1 -CheckOnly` under the runner: `hash check passed for 8 scripts`, exit 0.
- Self-test, run once under the non-elevated runner at `d1de3242`: `213 passed, 0 failed`, exit 0. All 10 fx-c end-to-end cases passed, including `t3failleft`, `t3smokeace` and `t3tcchild`. Afterwards the probe directory holds only `.py` and `.ps1` files, `git status tools/` is clean, and I created no `__pycache__`.

## Round-6 findings: re-verified

I built my own synthetic records (not the self-test's helpers) and passed them through `S.verdict`.

| R6 | Attack | Result at d1de3242 |
|---|---|---|
| 1 | fx-c launch that failed (no report), left the DENY ACE and changed the toolchain, with a smoke record | `STOPPED-STATE-CHANGE`, 2 entries in `state_left` (was `LAUNCH-FAILED`, `[]`). Three such launches give 6 entries. With no batch record it is still `STOPPED-STATE-CHANGE`. The e2e `t3failleft` case passes on both the console and `summary.json`. **Fixed.** |
| 2 | Smoke launch completed OK but left a toolchain grant, or left a changed interpreter ACL, or broke and also left an ACE. Also: a smoke record only, with no `variant` field and no S2 records | `STOPPED-STATE-CHANGE` in every case. `run_smoke` now calls `capture_acls` before the launch and `record_acl_comparison` after it, and applies `state_left` for fx-c. The e2e `t3smokeace` case passes. **Fixed.** |
| 3 | Every launch clean, but the toolchain tree differs between the batch-start and batch-end saves | `STOPPED-STATE-CHANGE` (`batch:` entry). `python.exe` is captured per launch. The e2e `t3tcchild` case passes with the root unchanged. **Fixed.** |
| 4 | Detector tightened to `sddl_has_host_prep` | Wrong mask, inherited, inheriting, deny, object, one SID alone and AC alone are all rejected (self-test). **Fixed.** |
| 5 | Host-prep evidence | The header now records `host_prep_evidence` start and end (root SDDL plus the detector result), and `host_prep_ran` is derived from those reads. **Fixed.** |
| 6 | Docstring | WHAT IT DOES NOT MEASURE now names: no denial capture, three variables changed at once, and the `\Device\Null` state. The descendants are covered by the batch saves. **Fixed** (see finding 3 below for remaining prose). |

Fail-closed probe: a launched record that is missing the three `*_acl_unchanged` fields, or the whole `deny_ace_cleanup`, reads `STOPPED-STATE-CHANGE`. A clean record set reads `HOLD`.

## Landing and precedence

- `git diff --quiet b1cb40e3 d1de3242` is clean for `landing.py`, `payload.py`, `smoke_payload.py` and `launch.ps1`. Their on-disk certutil hashes match the round-5 approval byte for byte.
- FAIL is first in `verdict`. FAIL plus every kind of state left, plus a broken smoke launch, plus a batch difference, gives `FAIL`. A FAIL on a failed launch plus a broken smoke launch also gives `FAIL`. `run_launch` checks FAIL before `state_left`.
- The precedence changed from round 5: STOPPED-STATE-CHANGE now outranks CONTAINER-PAYLOAD-BROKEN, for fx-a too. A broken smoke launch that also changed MXC state used to read BROKEN and now reads STOPPED. That is the more conservative reading, and I accept it.

## Can the icacls /save comparison stop a batch falsely?

- I saved the real toolchain twice in a row with the harness's own `F.icacls_save`. It holds 22,744 objects, the saves took 7.9 s and 4.7 s, rc was 0 both times, and `compare_icacls_saves` returned `unchanged: True`. 0 of the 22,744 objects fell back to raw text.
- The save files hold only an object name and its `D:` DACL line. There are no timestamps, no owner, no size and no content, so Bitdefender scans, reads and timestamp changes cannot register. The comparison sorts ACEs per object, so a reorder alone reads unchanged (reproduced).
- If a save fails, or is unreadable, `unchanged` is None. That reads INSTRUMENT-BLIND, not STOPPED.
- The only non-ACL event that fires it is an object created or deleted in the toolchain during the batch (finding 2).

## Host-prep detector against what prepare-system-drive writes

host-prep.md (sources/mxc-v1.0.0-docs, `docs__backends__process-container__host-prep.md.txt`:82-85) documents two allow ACEs: S-1-15-2-1 and S-1-15-2-2, mask `0x00120088`, no inheritance.

Against the live `C:\` SDDL, read natively:

| Case | Detector reads |
|---|---|
| Live `C:\` as it stands today | False |
| + `(A;;0x120088;;;AC)(A;;0x120088;;;S-1-15-2-2)` | True |
| Same pair, SID spelled `S-1-15-2-1` | True |
| Same pair, mask written `0X120088` | True |
| Pair plus a third-party `(A;OICI;FR;;;AC)` (which unprepare is documented to preserve) | True |
| Pair plus a deny ACE for AC | True (this question is about presence) |

**PASSES on exactly the documented entries.**

## Findings, most severe first

1. **LOW. The per-launch ACL comparison is order-sensitive. The batch comparison is order-insensitive.** `fixtures.py:254` `same_acl` compares the ordered ACE list. It is used for T/sub, T, the toolchain root and `python.exe`. `compare_icacls_saves` sorts.
   - Reproduced: `same_acl` on the same two ACEs reversed returns `False`. The same reorder in a save file reads `unchanged: True`.
   - Consequence (hypothesis): if MXC's restore replays ACEs in a different order, every launch stops with STOPPED-STATE-CHANGE although the set is restored. MXC documents "original DACLs are restored on exit" (schema), so I expect the same order. The cost is one re-run, and the record shows the before and after SDDL.
   - The same behaviour existed for T/sub at round 5.
2. **LOW. The batch comparison counts an object created or deleted in the toolchain as a state change.** Reproduced: adding one object to a save file gives `["...: only at end"]` and `unchanged: False`. The verdict line says "toolchain tree ACL differs" although the cause is a new file. The differences list does name `only at end`.
   - Incidence: 0. The container runs `-I -B`, `interpreter_info` only hashes the file, and the host control uses the host interpreter.
   - It fires only if something else writes into `C:\blarai-spike-1740\toolchain` during the batch. The cost is a re-run.
3. **LOW (prose).** Some docstring text still describes round-5 behaviour:
   - The verdict table in `summarise.py:12-13` still describes STOPPED-STATE-CHANGE as a smoke-only MXC-state verdict with "no S2 run was made". The fx-c paragraph below it is correct.
   - The SMOKE LAUNCH paragraph in `run_probe.py` says a smoke launch that did not complete stops with CONTAINER-PAYLOAD-BROKEN. It now stops with STOPPED-STATE-CHANGE when it also left state.
4. **INFO.** An uncaught exception inside the batch loop runs `finally` and then propagates past the end-of-batch save, the header and the summary. That pattern predates this change, and the traceback is loud, so it is not an absence presented as a value.
5. **INFO.** `icacls /save` records only DACLs. An owner change on a toolchain descendant is not compared; the root and `python.exe` owners are compared per launch. MXC is not documented to change owners.

## Attacked and not broken

- **Variant detection** holds with only smoke and batch records present.
- **No false attribution:** a batch record that differs, when nothing was launched, does not become STOPPED; it reads HOST-PREP-REQUIRED in that case.
- **Fail-closed on missing fields** (see above).
- **Ordering in a smoke launch:** the comparison is recorded before the BROKEN decision, and STOPPED is printed first.
- **rc mapping:** a summary verdict of STOPPED forces rc 4 when rc was 0.
- **A save fails:** INSTRUMENT-BLIND, not STOPPED.
- **The toolchain root and `python.exe`** both parse cleanly today (`{'A': 4}` each), so `acl_parse_ok` will not read blind.

## Operator command sequence (elevated PowerShell 7)

This is unchanged from round 6, and still matches `run_probe.py`'s argparse at `d1de3242`: `--v100-launcher`, `--main-launcher`, `--container-python`, `--toolchain`, `--variant {fx-a,fx-c}`, `--allow-dacl-tier`, `--runs`. Step 0's external save is now redundant with the harness's own batch saves, but it also covers the prep window, so keep it.

```powershell
# 0. snapshot: C:\ root and the whole toolchain
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

Nothing blocks the run. All six round-6 findings reproduce as fixed. The landing judgement is byte-identical to round 5, and FAIL still outranks everything. The new tree comparison showed no difference across two real saves of 22,744 objects.

- Findings 1 and 2 can only produce a false stop, never a missed change. Each costs at most a re-run, with the evidence in the record.
- Finding 3 is prose.

Suites run at `d1de3242`:
- `self_test.py` once, under the non-elevated runner.
- Two ad-hoc attack scripts (synthetic `S.verdict` records, plus a real `icacls_save` and detector probe), from the scratchpad, with `-I -B`.
- `launch.ps1 -CheckOnly` under the runner.
