# MXC denied-subtree probe: pre-run adversarial review, round 4 (2026-10-15)

Target: branch `feat/mxc-denied-subtree`, commit `bd3694d6` (on top of round-3-approved `42fd5f1c`: `ef422b21`, `bd3694d6`), `tools/probes/mxc_denied_subtree/` (8 files, `smoke_payload.py` new), working tree clean against the commit. Spec: the CASE_2 mxc-denied-subtree file of 2026-10-15 (read only). Live-run evidence read only: `%USERPROFILE%\blarai-research-data\mxc-denied-subtree\run-20261015-1\`. MXC v1.0.0 doc copies read under `docs/research/windows-containment-comparison-2026-10/sources/mxc-v1.0.0-docs/`; MXC source was not found on disk this round and was not re-read.

**VERDICT: FAIL (one HIGH). Approval file NOT written; `APPROVED_SHA256.txt` (round 3, `42fd5f1c`) left untouched.**

The HIGH is a regression introduced by the round-3 MEDIUM fix: a write that lands in `T\sub` and whose new entry the host cannot read at the after-snapshot is no longer counted, although the entry is plainly present in a listing that succeeded. At `42fd5f1c` the same input gave FAIL. At `bd3694d6` it gives INSTRUMENT-BLIND when the report came back, and LAUNCH-FAILED with a stop line that reads "T/sub unchanged" when the report did not.

## What was run, at bd3694d6

All of it under `run_nonelevated.ps1`. whoami: Medium Mandatory Level, with Administrators and S-1-5-114 deny-only.
- `self_test.py`: **142 passed, 0 failed**, exit 0. Token line: `guarded privileges enabled before secure_token []; after []`. One run only.
- `attack4.py` (new): the five landings, each with the landed entry held without read sharing at the after-snapshot, judged by `landing.judge` and routed through `summarise.verdict`. Run at `bd3694d6` and again against the `42fd5f1c` copies of `fixtures.py`, `landing.py`, `payload.py` and `summarise.py` (`attack4_old.py`).
- `e2e4.py` drives the real `run_probe.main` with `fake4.cmd`. The fake never starts a container, the tree root is `C:\mxc-fx-review4`, and the smoke launch runs the real smoke payload. Modes: `open`, `lockafter` (round 3's fixture), `hiddenland` and `hiddenland_report` (both new).
- `r3/attack3.py` re-run at the new hash; `verd4.py` checks the smoke-record verdicts.
- `wd4.py` checks the watchdog. The payload has `HANG_SECS` patched to 3 s and hangs after S2.
- No container launched, no `--dry-only` against the real launchers this round, no listener, no firewall change. Scratch: `%TEMP%\claude\...\scratchpad\mxr4\`.

## Round-3 findings

| R3 | Severity | Claimed | Status at bd3694d6 | Evidence |
|----|----------|---------|--------------------|----------|
| 1 | MEDIUM | fixed | **FALSE FAIL FIXED; OVER-CORRECTED into a wrong spare (new finding 1)** | `e2e4 lockafter` (real `run_probe`): `STOP: the host could not read what it judged (instrument blind)`, `VERDICT: INSTRUMENT-BLIND`, `sub_changes []`, `landed []`, `read_errors ['sub/marker.txt']`. `attack3` #2 and #3 (exclusive handle; unlistable `sub` after): INSTRUMENT-BLIND. The fix also removes existence evidence: see finding 1. |
| 2 | LOW | not claimed | open, now documented as a bound | `attack3` #4: create and delete changes the `sub` mtime, `sub_changes []`. The `landing.py` docstring and NOT MEASURED now state it correctly. |
| 3 | LOW | fixed | FIXED | `attack3` #6 (the record shape `run_probe` writes for a privilege skip): `INSTRUMENT-BLIND`, reason `guarded privileges enabled at launch ['SeRestorePrivilege'] (launch refused)`. Self-test lock now uses that shape. |
| 4 | LOW | fixed | FIXED | `launch.ps1` refuses any directory or any non-`.py`/`.ps1` entry. `run_probe.py` refuses the same before any sibling import. Self-test: `run_probe refuses a package directory…`, `…an extension module`, `launch.ps1 refuses…` (both): PASS. `.pyw` cannot shadow an existing `.py` (the source-suffix order puts `.py` first) and is refused anyway. |
| 5 | LOW | not claimed | open (binding context still has the privileges absent) | `attack3` #1: guarded privileges held `[]`, `secure_token` all `absent`. |
| 6 | LOW | documented | documented, unchanged | The `summarise.py` docstring now states the code-5 rule. `attack3` #7: codes 2, 3, 32 and 1920 each give INSTRUMENT-BLIND. |
| 7 | LOW | fixed | FIXED | `run_probe.py` NOT MEASURED now names per-entry ACLs, change time and the archive bit, the directory last-write time, and the `FILE_WRITE_DATA` open. Line 5 says "append-only handle". `attack3` #8 still shows a DENY ACE on the marker gives `sub_changes []`, and it is in the list. |
| 8 | LOW | not claimed | improved incidentally | `security_suite()` now also lists `Bitdefender Antivirus` version `30.0.33.162`. Defender's version is still `null`, and McAfee is still a stale registration. |

## New findings

### 1. HIGH: a landed entry that the host cannot read is dropped from the evidence, although a successful listing shows it appeared. This regression turns a FAIL into INSTRUMENT-BLIND or LAUNCH-FAILED.
- **Where:** `landing.py:155-173` (`skipped_paths`, `is_skipped`), `landing.py:175-180` (`sub_changes` skips the path entirely), `landing.py:194-215` (`landings`: `clear(...)` makes the predicate False), `landing.py:243-252` (`judge` also drops the disagreement for that attempt), `run_probe.py:351-355`.
- **What is wrong:** `skipped_paths` puts every entry flagged `unreadable` into the skip set, and both `sub_changes` and `landings` then ignore it. The decision to skip therefore removes two kinds of evidence. One is the content the host could not read. The other is the existence of the entry, which the parent listing (which succeeded) does prove. A path absent before and present after is a landing whatever its bytes. `42fd5f1c` compared unreadable entries "by kind only", which kept that evidence.
- **Reproduced at the unit level (`attack4.py`, non-elevated):**

  | landed entry held at after-snapshot | `42fd5f1c` | `bd3694d6` |
  |---|---|---|
  | create `s2_new.txt`, report says create ok | FAIL | **INSTRUMENT-BLIND**, disagreement suppressed |
  | create `s2_new.txt`, no report | FAIL | **LAUNCH-FAILED**, `blind []`, stop "no container report (T/sub unchanged)" |
  | rename, `renamed.txt` held, no report | FAIL | FAIL, but only because `rename_me.txt` vanished readably |
  | mkdir `s2_dir`, directory held, no report | FAIL | **LAUNCH-FAILED** |

- **Reproduced end to end (real `run_probe.main`, `e2e4 hiddenland`):** the fake launcher plays a container that creates `sub\s2_new.txt` and dies before its report, which is what the new 90 s watchdog produces. A third party then holds the new file without read sharing:
  ```
  {"tag": "fx-a-r1", ..., "launched": true, "landed_count": 0, "stop": "STOP: no container report (T/sub unchanged); see the record"}
  VERDICT: LAUNCH-FAILED
  launch-fx-a-r1.json | appeared ['sub/s2_new.txt'] | sub_changes [] | landed [] | read_errors ['sub/s2_new.txt']
  SUMMARY LAUNCH-FAILED [] []
  ```
  `hiddenland_report` (report present, then the same held landing): `VERDICT: INSTRUMENT-BLIND`, `changes []`.
- **Lock that over-certifies:** `self_test.py` "a readable landing still counts while another entry is unreadable (read errors do not hide evidence)". The fixture makes `s2_new.txt` readable and holds an unrelated file (`marker.txt`). The parenthetical claims more than the fixture covers. The case it does not exercise, where the landed entry itself is unreadable, is the one that hides evidence.
- **Cost when it fires:** a real denied-path bypass, the outcome the case routes privately to Microsoft, is reported as LAUNCH-FAILED. The stop line asserts "T/sub unchanged", the blind reasons are empty, and the only trace is `tree_after` and `read_errors` in the record. LAUNCH-FAILED is the verdict the operator acted on today by changing the harness and re-running. The probe never produces a false HOLD this way. The tree is kept.
- **Incidence:** 0 banked. It needs a third party to hold the landed entry without read sharing at the after-snapshot (the payload's own handles close when it exits). Bitdefender and Defender are both active on this host; whether either does this is a hypothesis.
- **Fix direction (author's call):** an entry present in one snapshot and absent in the other, whose parent directory was listed on both sides, is a change and a landing regardless of `unreadable`. Only content fields (sha256, streams, size, mtime) of an unreadable entry should be left out. The lock should hold the landed entry itself.

### 2. MEDIUM: on a launch with no report, host read errors are invisible to the verdict, and the stop line asserts "T/sub unchanged"
- **Where:** `summarise.py:102-118` (read errors are added to `blind` only for `done`, that is completed launches), `summarise.py:160` (LAUNCH-FAILED outranks INSTRUMENT-BLIND), `run_probe.py:354-355`. Prose: `summarise.py:30-32` ("A read or listing error on the host never produces FAIL: … the run is INSTRUMENT-BLIND") and the `landing.py` READ ERRORS paragraph ("It makes the run INSTRUMENT-BLIND").
- **What is wrong:** a launched record with no report and non-empty `read_errors` is LAUNCH-FAILED with no blind reason. Both docstrings say it is INSTRUMENT-BLIND. The stop line is computed from `sub_changes`, which already left the unreadable paths out, and it prints "T/sub unchanged" anyway.
- **Reproduced (`attack4.py`, case E):** the marker is appended, with no report, and the marker is held at the after-snapshot. At `bd3694d6`: `landed [] sub_changes [] read_errors ['sub/marker.txt']`, `VERDICT LAUNCH-FAILED`, `blind []`, stop "no container report (T/sub unchanged)". At `42fd5f1c` the same input was a FAIL from unknown content, which is round 3's false-FAIL direction. The correct reading is INSTRUMENT-BLIND, and neither hash gives it.
- **Cost:** a run whose sub content was never verified is filed as a launch failure, with a sentence saying it was unchanged. It never gives a false HOLD.

### 3. MEDIUM (a decision for the spec owner, not a code defect): UI lockdown off departs from the case's policy line
- The spec says "Egress deny, no proxy, no UI: filesystem only." At `bd3694d6` the policy submits `ui: {disable: false, clipboard: none, injection: false}`. The other UI fields are omitted, and the v1.0.0 schema doc says omitted fields default to the most restrictive value.
- **Recorded:** yes. The header has `ui_lockdown: false`, `ui_policy` and `ui_lockdown_note`. `summary.json` has `ui_lockdown: false`. The NOT MEASURED list has "UI lockdown on". The self-test checks that the policy submits exactly that `ui` and that the e2e header and smoke config carry it.
- **Does it change the filesystem question:** the v1.0.0 docs say no. `UIPolicy_Schema.md` maps `ui` to Job Object `JOB_OBJECT_UILIMIT_*` flags plus the `DisallowWin32kSystemCalls` process mitigation. `os-version-support.md` ("UI restrictions") says they are applied in both T1 and T3 from `job_object.rs`. Neither document mentions filesystem enforcement, and `schema.md` puts Tier 1 `deniedPaths` in PSEC (`PSE_SUPPORT_FS_DENY`). The source was not re-read this round. That the PSEC filesystem deny does not depend on the Win32k mitigation is inferred from the docs; it was not verified.
- **Needed:** a line in the case file or the register row that says the policy ran with `ui.disable` false and why. It is not a blocker for the run.

### 4. LOW: a smoke launch that changes MXC state is summarised as INCOMPLETE with no reason
- **Where:** `run_probe.py:243-247` (stop, rc 6), `summarise.py` (smoke hygiene is not checked, and "smoke absent" is only added when `done`).
- **Reproduced (`verd4.py`):** S4 ok plus a smoke record with `ok: true` and `state_changed_by_run` non-empty gives `INCOMPLETE []`. The console STOP line is correct, but `summary.json` gives no reason.

### 5. LOW: CONTAINER-PAYLOAD-BROKEN also covers launcher failures and timeouts; LAUNCH-FAILED prose is stale with the watchdog
- `verd4.py`: a smoke record with `launch: {timeout: true}` (or any launcher-side failure before the payload runs) gives CONTAINER-PAYLOAD-BROKEN. The label blames the payload whatever the cause; the record carries the launcher stderr.
- `summarise.py:11`: LAUNCH-FAILED is "a launch produced no container report (the payload never ran)". With `HANG_SECS`, a payload that ran and was killed at 90 s also lands here (`wd4.py`: rc 1, no report, `Timeout (0:00:03)!` stack on stderr, and the S2 effects on disk).

### 6. LOW: a lock lost its subject, and one dead line
- `self_test.py` e2e `tiermismatch`: the fake's dry-run returns the wrong tier for every call, so the smoke dry-run now trips first. `run_launch`'s own per-launch tier-mismatch branch (`run_probe.py:293-300`) is no longer reached end to end. The lock passes on the smoke record. The unit verdict lock still covers the record shape.
- `self_test.py`: `vv = V([s4_rec()], smoke=False) if False else S.verdict(...)` is dead code.

## The brief's questions

- **Does a broken smoke stop before S2?** Yes. `rc = 6` makes `variants` empty. The e2e `nopayload` gives CONTAINER-PAYLOAD-BROKEN with no `launch-fx-a-*.json` (self-test PASS). A dry-run rejection, a tier mismatch and an enabled privilege on the smoke each stop the batch too.
- **Can a smoke success be faked?** Not by the harness's own inputs. The tree is fresh, the report is at `T\_smoke.json`, and `ok` requires all four imports plus a Win32 listing of T. It certifies importability only. It does not exercise the handshake, the watchdog or any S2 call, so a smoke pass does not show the measured payload will complete; finding 2 matters when it does not.
- **Does the smoke use the same policy shape?** Yes. It is the same `F.policy("fx-a", …)`. Only the script name, the report filename and one extra hashed file in the read-only payload directory differ. It uses the same launcher, the same interpreter and the same toolchain.
- **Can the 90 s watchdog give a false verdict?** Not a false HOLD. The live run's whole launch took 1.6 s (`mxc-fx-a-r1.log`: "Runner completed in 1642 ms"), and the payload's only wait is the 12 s handshake. A kill before the report gives no report, and the judge then runs on the after-snapshot of every launched record (`run_probe.py:326-347`). A readable landing is FAIL (self-test `landnoreport`; `wd4.py` shows the landings stay on disk). The exception is finding 1: an unreadable landed entry plus a watchdog kill gives LAUNCH-FAILED.
- **Can read-error exclusion hide a real landing?** Yes (finding 1). The test case the brief proposed, a payload holding a file open exclusively, cannot happen as written, because the payload's handles close when it exits. A third-party holder at the after-snapshot does produce it (`e2e4 hiddenland`).
- **UI-off recorded and in NOT MEASURED?** Yes (finding 3).

## Attacked and could not break

- **The round-3 false FAIL:** an exclusive handle on an unchanged file, and an unlistable `sub` before, after or both. Each gives INSTRUMENT-BLIND with the change list empty.
- **Judge on every launched record:** the smoke and measured paths both snapshot after any launch, including a launcher timeout. A real `run_probe` `open` run gives FAIL with all six paths and the tree kept.
- **Smoke gating:** no S2 launch follows any smoke stop. The smoke's privilege, tier and dry-run checks match `run_launch`'s.
- **Hash binding:** a package directory, an extension module or any non-source entry is refused by both entry points before import. The smoke payload is in the hashed set.
- **`--tree-root`:** it passes through `assert_local_ntfs`, which refuses OneDrive, the user profile and reparse ancestors, and through `assert_outside_git`. The finally block only `rmdir`s, which removes nothing that is not empty. The self-test uses a per-process root, so it cannot collide with a live run's `C:\mxc-fx` (whose `run-20261015-1` tree is still on disk, kept by the stop).
- **Watchdog mechanics:** exit code 1, a stack dump to stderr, no partial report, and earlier effects left on disk.

## Merge read

Block on finding 1. It is a regression this diff introduced, against the invariant the brief names: never hide a landing. The fix is narrow. Finding 2 should be fixed in the same change, because it is the same predicate seen from the no-report side. With both fixed, the lock should hold the landed entry itself, not a neighbour, and it should route a no-report record through `verdict`. Findings 3 to 6 do not block: 3 needs a ruling line from the spec owner; 4 to 6 are record-quality and lock-hygiene items.

Suites run by this reviewer at `bd3694d6`, all under `run_nonelevated.ps1` (Medium integrity): `self_test.py` (142/0, once); `attack4.py` (and `attack4_old.py` against the `42fd5f1c` copies); `e2e4.py` with `fake4.cmd` (`open`, `lockafter`, `hiddenland`, `hiddenland_report`); `r3/attack3.py`; `verd4.py`; `wd4.py`. Not run: `--dry-only` against the real launchers, certutil hashing, and `launch.ps1 -CheckOnly` (approval withheld). No container launched.
