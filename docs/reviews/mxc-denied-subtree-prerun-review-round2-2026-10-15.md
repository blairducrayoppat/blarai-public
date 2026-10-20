# MXC denied-subtree probe: pre-run adversarial review, round 2 (2026-10-15)

Target: branch `feat/mxc-denied-subtree`, commit `4abd6442` (round-1 fixes on `288cf104`), `tools/probes/mxc_denied_subtree/` (7 files). Spec: the CASE_2 mxc-denied-subtree file of 2026-10-15 (read only). MXC source read: v1.0.0 and main `525d0f25` under the spike work directory (`filesystem_dacl.rs` `state_dir()`).

**VERDICT: FAIL (two HIGH). No approval file written.**

## What was run, at 4abd6442

- `self_test.py` through `run_nonelevated.ps1` (whoami: Medium Mandatory Level; Administrators and S-1-5-114 deny-only): **95 passed, 0 failed**, exit 0. This includes the end-to-end split through the real `run_probe.main` with a fake launcher: open tree gives FAIL, ACL-held tree gives HOLD with three completed launches.
- `run_probe.py --dry-only --s5 --runs 1` against the real v1.0.0 and main launchers, non-elevated: S0 base-container on both, `fs_deny_advertised true`; fx-a dry-run `selected isolation tier: base-container`, `validation passed`; `S5 not applicable on Tier 1`; trees and `C:\mxc-fx` removed; MXC state directory listing empty before and after.
- Round-1 fixtures re-run against the new code (adapted `attack.py` as `attack2.py`), a new fake launcher (`fake2.py`) driving the real `run_probe.py` non-elevated, a host-blind-subtree fixture, a privilege fixture under the reviewer's elevated Git Bash, an alternate-data-stream survey of 163,334 entries on this machine, and a bytecode-cache proof of concept on a scratch copy of the directory. No container was launched.

## Round-1 findings

| R1 | Severity | Status at 4abd6442 | Evidence |
|----|----------|--------------------|----------|
| 1 | HIGH | FIXED | Every round-1 row now gives FAIL: extra file, rename source bytes changed, rename destination appears with source kept, source moved out to T, move into sub, stream on the marker, sub renamed away (plus new rows: empty stream on the sub directory, hard link into sub). `sub_changes` is whole-subtree equality and drives both the STOP and the verdict. New gaps in the same area: findings 2 and 3 below. |
| 2 | HIGH | FIXED | All five S2 attempts, both S1 writes and the S3 read and listing are Win32 calls. Self-test non-elevated: error 5 on every attempt against an ACL-held sub, 3 on missing paths, 80, 183 and 2 on existing targets. Error text now kept to 600 characters. |
| 3 | MEDIUM | FIXED, with a new wrong spare | REFUSED only on `dry_run_rc != 0`; a launch with no report is LAUNCH-FAILED (self-test e2e and synthetic). But LAUNCH-FAILED now also covers a run whose writes LANDED (finding 2). |
| 4 | MEDIUM | FIXED | Per-launch tier set in `summary.json`; pre-launch STOP if the dry-run tier differs from S0 or is not base-container; state change, ACL left on sub and toolchain ACL change are INSTRUMENT-BLIND. Residual: a tier-mismatch stop yields INCOMPLETE with no reason (finding 7). |
| 5 | MEDIUM | FIXED, with a residual | `winsec` vendored (`read_sddl` in `fixtures.py`, no import outside the directory); explicit `-Python`, its sha256 printed and both interpreters' sha256 in the header. Residual: the bytecode cache is outside the hash (finding 5). |
| 6 | MEDIUM | FIXED | `MXC_DACL_STATE_DIR` popped from the launcher env, never deleted; the state directory is listed with names, sizes and sha256. The harness path matches MXC's `state_dir()` in both v1.0.0 and main (`MXC_DACL_STATE_DIR`, else `LOCALAPPDATA`, else `USERPROFILE\AppData\Local`, then `Microsoft\MXC\dacl-restore`), and the launcher gets the harness's own environment, so the two agree whatever `LOCALAPPDATA` is. Toolchain ACL is captured before and after. A DACL tier needs `--allow-dacl-tier`. |
| 7 | MEDIUM | FIXED | Self-test drives `run_probe.main` end to end: FAIL (open), HOLD (held), LAUNCH-FAILED, REFUSED, tier-mismatch stop, S0-tier stop, S5 not applicable. The split is demonstrated, but only under a token without enabled backup or restore privileges (finding 1). |
| 8 | LOW | FIXED | Delete target is a separate file (`delete_me.txt`); append and delete no longer share a marker. |
| 9 | LOW | FIXED | Move-in, renaming sub, stream writes and other spellings are in the NOT MEASURED list. Attribute and timestamp writes are not (finding 6). |
| 10 | LOW | FIXED, one residual | Tree kept after a stop that follows a launch; `C:\mxc-fx` removed at the end; `--s5` gated on a DACL tier; launcher and interpreter paths explicit; S3 and codes in the summary; `host_prep_ran` explicit. The security suite's VERSION is still not recorded (process names only). |

## New findings

### 1. HIGH: the harness never checks the launching token; the one control for it is a silent no-op that reports success
- **Where:** `fixtures.py:306-332` (`_LuidAttr`, `remove_privileges`), `self_test.py:491-497` (preflight), `run_probe.py:276-362` and `launch.ps1` (no elevation or privilege guard), `fixtures.py:293` (records `elevated` only).
- **What is wrong:** `_LuidAttr` puts a `c_longlong` LUID at offset 8 (struct size 24); `TOKEN_PRIVILEGES` has it at offset 4 (size 16), so `AdjustTokenPrivileges` receives a garbage LUID, returns TRUE with `ERROR_NOT_ALL_ASSIGNED`, and `remove_privileges` reports `{SeBackupPrivilege: True, SeRestorePrivilege: True}` while removing nothing.
- **The builder's question, answered:** the Git-Bash difference is the MSYS runtime ENABLING `SeBackupPrivilege` and `SeRestorePrivilege` in an elevated token (Git Bash here: both Enabled; elevated PowerShell: both present but Disabled); children inherit the enabled state. With them enabled, `CreateDirectoryW`, `MoveFileExW` and `DeleteFileW` pass an ACL that refuses them (they open with backup intent); `CreateFile` without backup semantics is still refused. With the privileges correctly removed (a `_pack_ = 4` struct), all five are refused again. Under the non-elevated runner the privileges do not exist, so the self-test passes there by construction, and its preflight label ("no backup or restore privilege in play") certifies a removal that never happened.
- **Live-run consequence:** none of the harness's own host-side checks depend on ACL enforcement (S4 expects success; snapshots only read). The exposure is the launch itself: `launch.ps1` started from an elevated shell with these privileges enabled (this session's Bash tool is exactly that) hands the enabled privileges to `wxc-exec`, and nothing refuses or records it beyond a bare `elevated` boolean that the verdict never reads. Whether the base container's process inherits enabled backup or restore privileges is a HYPOTHESIS (no container may be launched in this review); if it does, rename, delete and mkdir into T\sub can land through a configuration artefact and give FAIL, which stops the run and starts the private Microsoft route.
- **Reproduced:** yes, for everything except the container inheritance.
  ```
  sizeof _LuidAttr 24 Luid offset 8 Attributes offset 16 (Win32 TOKEN_PRIVILEGES: 16 / 4 / 12)
  as-shipped struct: AdjustTokenPrivileges returned 1 GetLastError 1300
  ['SeBackupPrivilege Enabled', 'SeRestorePrivilege Enabled']        (child whoami after "removal")
  packed struct ... -> after packed: []
  inherited token as-is: mkdir True, create (False,5), append (False,5), rename True, delete True
  elevated High, backup/restore REMOVED: all five (False, 5)
  ```
- **Incidence:** 0 in the banked corpus (no live run yet). The reviewer's own default shell meets the trigger.
- **Fix direction:** run_probe refuses to start when the token is elevated or has `SeBackupPrivilege` or `SeRestorePrivilege` enabled (checked with a correctly laid out structure, and the result verified by reading the token back, not by the call's return), records the privilege list in the header, and the self-test asserts the removal took effect.

### 2. HIGH: a landing with no container report is LAUNCH-FAILED, never FAIL; the STOP says the payload did not run
- **Where:** `run_probe.py:243-253` (`judge` and `sub_changes` only when `rep is not None`), `summarise.py:41-55, 102-103` (`changed` only over completed records).
- **What is wrong:** the spec's FAIL is "any S2 write landing in T\sub", independent of whether the payload's report survived; the harness computes T\sub equality only when a report exists, so a run whose writes landed but whose report is missing, truncated or not yet written is summarised as LAUNCH-FAILED with `changes: []`.
- **Failure scenario:** the payload is killed or crashes after S2, the report write is cut short, the 300-second timeout kills the launcher, or the launcher returns before the contained process finishes. The record holds `tree_before` and `tree_after` that differ inside sub; the summary says no change and the STOP line says "the payload did not run". That is the summary contradicting its own record, in the lenient direction, on the outcome that is routed privately.
- **Reproduced:** yes, through the real `run_probe.py` non-elevated with `fake2.cmd` in mode `landnoreport` (runs the policy's command line on an open tree, then removes the report):
  ```
  STOP: no container report; the payload did not run (launch failed)
  VERDICT: LAUNCH-FAILED
  launch-fx-a-r1.json | sub keys differ: ['sub/delete_me.txt', 'sub/marker.txt', 'sub/rename_me.txt', 'sub/renamed.txt', 'sub/s2_dir', 'sub/s2_new.txt']
  SUMMARY verdict LAUNCH-FAILED changes []
  ```
  Mode `earlyexit` (launcher returns while the payload is still waiting at the handshake) also gave LAUNCH-FAILED; whether later writes would then land after the snapshot was not observed (the runner's task ended and took the payload with it), so that variant is a hypothesis.
- **Incidence:** 0 banked. Needs the report to be absent after a landing.
- **Fix direction:** compute `sub_changes` for every launched record whatever the report, and let a change win (FAIL) before LAUNCH-FAILED; word the no-report STOP as "no report" without asserting that nothing ran.

### 3. MEDIUM: snapshot errors are silent; an unreadable entry renders as a change (false FAIL) or as absence (blind HOLD)
- **Where:** `landing.py:39-43` (`sha256_file` returns None on any OSError), `landing.py:46-52` (`streams_of` returns [] on failure), `landing.py:65-75` (`rglob` skips directories it cannot list), no check that the before-snapshot contains the layout `make_tree` wrote.
- **False FAIL:** a process holding `sub\marker.txt` without read sharing during the after-snapshot gives `sha256: None`, which differs from the before value: FAIL and a STOP. Reproduced: `exclusive handle on marker at after-snapshot: ['sub/marker.txt'] -> FAIL`. An on-access scanner is the plausible holder. Not observed in the self-test's six held launches on `C:\mxc-fx` with Bitdefender running; a transient "Device or resource busy" on removing a fresh tree was observed once during this review.
- **Blind HOLD:** if the host cannot list sub (traverse-only), both snapshots contain only `sub` itself, and two files written into sub (one of them `s2_new.txt`, a named attempt) give `landed_count 0`, `sub_changes []`, `sub_unchanged True`. Reproduced non-elevated (`blindsub.py`). Realistic incidence on Tier 1 is ~0 (MXC makes no host change there), but nothing asserts the host could see what it judged.
- **Fix direction:** an unreadable entry or failed stream query is INSTRUMENT-BLIND, not a difference; assert the before-snapshot holds sub, marker, delete_me and rename_me with the bytes `make_tree` wrote.

### 4. LOW: the HOLD does not check that the refusals were refusals of the deny
- **Where:** `summarise.py:118-129`.
- Every attempt failing with error 32 (sharing violation), 3 or 2 still gives HOLD (reproduced synthetically). The codes are in `summary.json`, so a reader can see it; the verdict line cannot. Note for the register row: say which codes the refusals carried.

### 5. LOW: the bytecode cache is outside the hash binding
- **Where:** `launch.ps1:192` hashes `.py`/`.ps1` files only; `-I` does not imply `-B`; `__pycache__` already exists in the probe directory.
- **Reproduced:** on a scratch copy, a `.pyc` compiled from a `landing.py` whose `sub_changes` returns `[]` (same size, same mtime), with the original source restored: `launch.ps1 -CheckOnly` prints `hash check passed for 7 scripts` and the import loads the planted `.pyc` (`sub_changes after a real landing: []`). Needs deliberate tampering; accidental incidence ~0. The approval certifies the sources, not the code that runs. Fix direction: `-B` plus a fresh `-X pycache_prefix`, or refuse when `__pycache__` exists.

### 6. LOW: attribute, timestamp and per-entry ACL changes inside sub are not compared and not listed as not measured
- `os.chmod(marker, 0o444)` inside sub gives `sub_changes []`, HOLD (reproduced). The payload does not attempt these, so this is a bounds statement for the NOT MEASURED list and the register row, not a missed landing.

### 7. LOW: a pre-launch tier-mismatch stop is summarised as INCOMPLETE with no reason
- **Where:** `summarise.py:94-96` (tier check only when a launch completed).
- Synthetic: S4 plus one fx-a record with tier `appcontainer-dacl`, not launched: `INCOMPLETE [] ['appcontainer-dacl']`. The docstring lists a tier mismatch under INSTRUMENT-BLIND. The STOP line on the console is correct; `summary.json` is not.

### 8. LOW: smaller items
- `same_acl` and `ace_types` parse the DACL with `\([^)]*\)`; a conditional ACE (nested parentheses) truncates the parse, and a DENY ACE after it is invisible to both (reproduced: `same_acl True deny_aces after {'A': 1, 'XA': 1}`). The real SDDL of T, T\sub and the toolchain has no conditional ACE, so incidence is 0. Ignoring the DACL control flags (auto-inherited, protected) cannot hide an added ACE: prepended, appended and conditional deny ACEs all give `same_acl False`. Group and SACL are not compared.
- The append attempt opens with `GENERIC_WRITE`; a deny that refused `FILE_WRITE_DATA` but allowed `FILE_APPEND_DATA` would be recorded as an append refusal. Bounds note.
- `appcontainer_mappings` is a count of an HKCU key shared with every packaged app on the machine (217 on this host); an unrelated install or removal during a launch gives "MXC state changed" (hypothesis; costs a stop, not a verdict).
- `icacls`, `reg` and `tasklist` are resolved through the normal executable search (interpreter directory, current directory, then PATH).

## Attacked and could not break

- **Benign host changes cannot produce a FAIL through metadata:** no timestamps or directory sizes are compared; setting atime and mtime on the sub marker with unchanged bytes gives `sub_changes []`.
- **Security-suite streams:** a survey of 163,334 entries found three stream names: `Zone.Identifier` (135, downloads), `BDU` (11, all downloaded installers in Downloads; Bitdefender) and one mail-client property. None on a text file the harness did not download. A `Zone.Identifier` written onto the sub marker is correctly a FAIL (a stream appeared); nothing in the run path writes one. Windows Search does not index `C:\mxc-fx` by default and adds no streams.
- **Whole-subtree equality:** every round-1 FAIL shape, plus hard link into sub and an empty stream on the sub directory, gives FAIL. The HOLD on a held tree in the self-test e2e (three launches, non-elevated) shows the equality does not false-FAIL under ordinary host activity in that sample.
- **MXC state directory:** same resolution as MXC v1.0.0 and main; the launcher receives the harness's own environment; never redirected or deleted (self-test lint and e2e).
- **ACL comparison:** an added DENY ACE is always seen except after a conditional ACE (finding 8).
- **REFUSED versus LAUNCH-FAILED:** REFUSED only on a validation rejection; a passed dry-run with no report is never REFUSED, so host prep cannot be prompted by an instrument failure.
- **Tier gate:** S0 and per-launch tiers recorded and compared; any non-base-container completed launch blocks HOLD; `--s5` on Tier 1 runs nothing.
- **launch.ps1:** refuses missing approval file, missing line, mismatch, tampered script, unlisted script, missing interpreter (self-test, non-elevated); a `#` comment header line is tolerated (`hash check passed for 7 scripts`, exit 0, on a scratch copy).
- **S1 and S4 controls:** host-judged; a virtualised view of T fails S1 and gives INSTRUMENT-BLIND, not HOLD.

## Merge read

Block the live run on 1 and 2. Finding 1: the run's validity depends on a token precondition the harness neither enforces nor records, the only code that claims to handle it is a silent no-op, and the default shell of the session most likely to launch it meets the trigger; a resulting FAIL is routed privately. Finding 2: a landing that loses its report is summarised as no change, which is the round-1 HIGH class (summary contradicting its own record) in a new place. Both fixes are small. Fix 3 in the same round (an unreadable entry should be INSTRUMENT-BLIND in both directions). 4 to 8 are not blocking; 4 and 6 belong in the register row's bounds.

Suites run by the reviewer at `4abd6442`: `self_test.py` non-elevated (95/0); `run_probe.py --dry-only --s5 --runs 1` with the real launchers, non-elevated; reviewer fixtures `attack2.py`, `blindsub.py`, `e2e2.py` with `fake2.cmd` (modes `landnoreport`, `earlyexit`) non-elevated; privilege fixtures `privtest*.py` and the `.pyc` proof of concept in the reviewer's elevated Git Bash on scratch copies. No container launched. No approval file written.
