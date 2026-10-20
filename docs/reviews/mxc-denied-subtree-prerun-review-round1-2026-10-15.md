# MXC denied-subtree probe: pre-run adversarial review, round 1 (2026-10-15)

Target: branch `feat/mxc-denied-subtree`, commit `288cf104`, `tools/probes/mxc_denied_subtree/` (7 files).
Spec: CASE_2 mxc-denied-subtree file of 2026-10-15 (read only). MXC source read: main `525d0f25` under the spike work directory; v1.0.0 doc copies under `docs/research/windows-containment-comparison-2026-10/sources/mxc-v1.0.0-docs/`.

**VERDICT: FAIL (two HIGH). No approval file written.**

## What was run, at 288cf104

- `self_test.py` through `run_nonelevated.ps1` (whoami: Medium Mandatory Level; Administrators and S-1-5-114 "Group used for deny only"): **47 passed, 0 failed**, exit 0.
- `run_probe.py --dry-only --s5 --runs 1 --out-root <scratch>` non-elevated: S0 for v100 and main both `tier base-container, needs_dacl_augmentation false, fs_deny_advertised true`; per-launch dry-run for fx-a and fx-b both printed `selected isolation tier: base-container` / `validation passed`; `state_changed_by_run {}`; trees removed. It left an empty `C:\mxc-fx` behind (removed by the reviewer afterwards).
- `scripts/scrub_public_identifiers.py --check`: 0 findings in 4071 tracked files. Grep of the seven files for hash-and-digits, ticket numbers, account name, SIDs: no match.
- Adversarial fixtures against `landing.judge` + `summarise.verdict` (scratch `attack.py`), and the REAL `run_probe.run_control` / `run_launch` / `summarise` driven end to end with a fake launcher (`fake_wxc.cmd`: answers `--dry-run`, then runs the policy's `commandLine` unconfined, optionally with a host deny ACE). No container was launched.

## Findings

### 1. HIGH: the HOLD predicate is looser than the spec's FAIL definition; the catch-all is computed and never consulted
- **Where:** `landing.py:437-459` (`landings`, `unexpected_changes`), `run_probe.py:217-225`, `summarise.py:601-622`.
- **What is wrong:** HOLD means "none of five named predicates fired", not "T\sub is unchanged"; `unexpected_changes` excludes the five named files and is wired into neither the STOP nor the verdict.
- **Failure scenario:** the spec's FAIL is "any S2 write landing in T\sub (a new file exists, the marker's bytes changed, a rename or delete took effect, a subdirectory exists)". Each of these sub changes gives a HOLD:
  ```
  extra_file_in_sub            landed_count=0 unexpected=['sub/other.txt'] disagree=[] VERDICT=HOLD
  rename_src_bytes_changed     landed_count=0 unexpected=[] disagree=[] VERDICT=HOLD
  renamed_dst_appears_src_kept landed_count=0 unexpected=[] disagree=[] VERDICT=HOLD
  rename_src_moved_out_to_T    landed_count=0 unexpected=[] disagree=[] VERDICT=HOLD
  move_into_sub_from_T         landed_count=0 unexpected=['sub/moved_in.txt'] disagree=[] VERDICT=HOLD
  ads_on_sub_marker            landed_count=0 unexpected=[] disagree=[] VERDICT=HOLD
  ```
  In the first and fifth rows the run's own record says a path changed in sub, and `summary.json` still reads HOLD. That is the summary contradicting its own record, on the outcome that goes public.
- **Reproduced:** yes. Scratch `attack.py`, output above.
- **Incidence:** the payload as written only writes the five named paths, so reaching this needs something other than those five calls to change sub. It is unlikely, but nothing makes it impossible, and a HOLD is published.
- **Fix:** in S2, HOLD requires the T\sub part of the after-snapshot to equal the before-snapshot exactly. Any difference is a STOP, and a FAIL unless it is fully explained by a judged landing. The five per-attempt predicates stay as attribution only. (Optional: add the alternate-data-stream listing, `FindFirstStreamW`, to `snapshot_tree` so the equality covers streams.)

### 2. HIGH: the Win32 error is not recorded for create, append, the S1 writes or the S3 read; errno 13 hides which refusal it was
- **Where:** `payload.py:301-307` (`_rec` takes `getattr(exc, "winerror", None)`), and every `open()`-based attempt (`payload.py:311-347`). The lock is `self_test.py:139-140`.
- **What is wrong:** Python's `open()` raises through the C runtime, so `winerror` is `None` and the text says `[Errno 13]`. The spec says "Each attempt recorded with its Win32 error." The C runtime maps ERROR_ACCESS_DENIED (5) and ERROR_SHARING_VIOLATION (32), among others, to errno 13, so the record cannot show that a create or append refusal was the deny's doing.
- **Failure scenario:** a HOLD whose create and append refusals were sharing violations or some other EACCES cause reads exactly like a deny. The self-test lock "real payload records a Win32 error for a refusal" exercises only `os.mkdir` (a path that does set `winerror`), so it certifies a property that two of the five S2 attempts do not have.
- **Reproduced:** yes. In the end-to-end harness run with a host deny ACE, the launch record shows:
  `'create_file': (False, None, "PermissionError: [Errno 13] Permission denied: ..."), 'open_write_append': (False, None, "PermissionError: [Errno 13] ...")`, and `read_marker` likewise `winerror None`.
- **Fix:** perform the open-based attempts with `_winapi.CreateFile` (CREATE_NEW for create; OPEN_EXISTING with FILE_APPEND_DATA or GENERIC_WRITE for append; GENERIC_READ for the S3 read) so the OSError carries `winerror`. Extend the self-test lock to assert a non-None `winerror` for every one of the five attempts against a refusing tree. Also stop truncating `error` to 200 characters before the file name: in the reproduction the path was cut at `...\T\sub`.

### 3. MEDIUM: a payload that never ran is reported as REFUSED, the verdict whose spec action is host prep
- **Where:** `summarise.py:615-616`.
- **What is wrong:** REFUSED fires when no fx-a launch completed for any reason, including a dry-run that passed and a launch that produced no report.
- **Failure scenario:** the payload cannot start inside the container (interpreter not readable, quoting in `commandLine`). The summary reads REFUSED, the docstring maps that to "validation or launch rejected the policy", and the spec's action for a refusal is to run `wxc-host-prep` with Blair present. That is a host mutation prompted by an instrument failure.
- **Reproduced:** yes. Real `run_launch` with a fake launcher that exits 1 without running the payload: `STOP: no container report (run failed)`, then `VERDICT REFUSED`. Also synthetic: `payload did not run, dry-run passed -> REFUSED`.
- **Fix:** REFUSED only when `dry_run_rc != 0`. A launched run with no report is INSTRUMENT-BLIND (or a separate RUN-FAILED) and carries the launcher's exit code and stderr.

### 4. MEDIUM: the HOLD names a tier the verdict never checks; the per-request tier is recorded but not compared, gated or summarised
- **Where:** `run_probe.py:170-171` (`dry_run_selected_tier` recorded), `fixtures.py:217-225` (`s0_record` from `--probe`), `summarise.py` (no tier field).
- **What is wrong:** `--probe` is policy-independent. MXC's own `backend-support-probe-api` plan, sections 7.3 and 7.4, says the probe tier is "a ceiling, not a guarantee" and that `deniedPaths` without `PSE_SUPPORT_FS_DENY` forces a weaker tier. The spec's HOLD must name the tier, and `summary.json` carries none. Nothing stops or flags a run whose dry-run tier differs from S0, and HOLD also ignores `state_changed_by_run` and `deny_ace_cleanup`.
- **Failure scenario:** synthetic records with a clean judge, `dry_run_selected_tier: appcontainer-dacl`, `state_changed_by_run` non-empty and `sddl_after_equals_before: false` give `VERDICT HOLD`. A reader of header S0 would publish "Tier 1".
- **Reproduced:** yes, synthetically (attack.py: `clean judge + state changed + ACE left + tier differs from S0 -> HOLD`). On this host the dry-run tier is base-container for fx-a and fx-b, so incidence today is 0.
- **Fix:** put the per-launch tier set into `summary.json`. Make HOLD require one tier across all completed launches, and make any state change or un-restored SDDL a non-HOLD.

### 5. MEDIUM: the hash binding does not cover all the code that runs
- **Where:** `fixtures.py:172-176` imports `winsec` from `../containment_arms/` at run time (every `acl_capture`, so on every launch and every dry-only). `launch.ps1:534` runs whichever `python` is first on PATH.
- **What is wrong:** `launch.ps1` and `run_probe.py`'s header claim the run is refused "unless every script's sha256 is in APPROVED_SHA256.txt", but `winsec.py` (shared with another probe and editable independently) executes in-process unhashed.
- **Reproduced:** by reading and by run. `acl_capture` is called in the dry-only run above. The approved set from `launch.ps1` is `Get-ChildItem $dir -File` filtered to .py/.ps1, so it has no entry for `winsec.py`.
- **Fix:** vendor the descriptor reader into this directory, or add `..\containment_arms\winsec.py` to the hashed set. Record `sys.executable` and its sha256 in the header.

### 6. MEDIUM (conditional on a DACL tier): host changes outside C:\mxc-fx are not captured, and MXC's restore journal is deleted
- **Where:** `fixtures.py:142-143` (`readonlyPaths` includes the toolchain directory under the spike tree), `run_probe.py:159` (`MXC_DACL_STATE_DIR` redirected under the tree), `run_probe.py:295` (`shutil.rmtree(state_dir, ignore_errors=True)` in `finally`).
- **What is wrong:** on Tier 2/3, MXC grants ACEs on every readonly path, which includes the shared toolchain directory outside C:\mxc-fx. The harness captures ACLs only for T and T\sub. `mxc_state` records the state-dir file NAMES only. The `finally` then deletes the directory that MXC's `filesystem_dacl.rs` documents as the crash-recovery store (`<run-id>.json`, retained entries for `recover_orphaned_state`), so a crashed run's ACEs on the toolchain could never be restored by MXC.
- **Reproduced:** no (would need a launch on a DACL tier). The mechanism was read in source at `525d0f25`, `filesystem_dacl.rs` lines 30-50 and 642-650. The dry-run selects base-container on this host, where the docs say no host filesystem changes are made, so incidence today is 0.
- **Fix:** before launch, refuse (STOP) unless the dry-run tier equals the S0 tier, so that a DACL tier needs an explicit flag. Never delete a non-empty state dir: copy it into the batch record and leave it. Capture the toolchain directory's SDDL before and after when the tier is not base-container.

### 7. MEDIUM: the self-test never exercises the harness wiring
- **Where:** `self_test.py` (no test reaches `run_control`, `run_launch`, `watcher`, the STOP chain or `main`).
- **What is wrong:** the toggle and verdict locks test `judge` and `verdict` on synthetic records only. The builder's "mid-run ACL capture untested" understates this: the whole launch-to-verdict path had never run.
- **Reproduced (the reviewer's own run):** the real functions, driven with the fake launcher, worked on the paths reached. With no deny the run gave `landed 4`, `STOP: FAIL condition met` and `VERDICT FAIL`. The watcher handshake captured `during` with `go_written True` and saw `deny_aces_during 1` when a deny was applied. The no-report path gave a STOP. The HOLD path end to end was NOT demonstrated: the reviewer's emulated host deny did not stop rename, delete or mkdir under the elevated reviewer token, so that fixture is inconclusive.
- **Fix:** add the fake-launcher fixture (a .cmd that answers `--dry-run` and runs `commandLine`) to `self_test.py`, giving a FAIL split (no deny) and a HOLD split (sub made read-only to the payload by a mechanism that does hold for a Medium token, for example running the payload under a restricted token or with a deny ACE checked first by `AccessCheck`).

### 8. LOW: the append and the delete share one marker
- **Where:** `payload.py:298` (order create, append, rename, delete, mkdir), `landing.py:479-481`, `run_probe.py:115-117`.
- **What is wrong:** when the delete lands, the append's effect cannot be seen. "Unmeasurable" is assigned only when the delete landed (`host["delete"]` true), so a FAIL can never be hidden by it. Two smaller costs remain: a FAIL record undercounts (it lists `delete` and puts the append in `unmeasurable`), and S4's append is accepted on the payload's own report, never host-verified.
- **Reproduced:** yes. `append+delete landed: landed= {'delete'} unmeasurable= ['open_write_append']`.
- **Fix:** none required by the spec, which names "the marker" for both. Record the limitation in the summary text.

### 9. LOW: the five attempts leave move-in, renaming sub itself, and alternate spellings unlisted under NOT MEASURED
- **Where:** `run_probe.py:27-31`.
- **What is wrong:** the spec's question is "write attempts into the denied subtree". A move from T into sub, a rename of `T\sub` itself (FILE_DELETE_CHILD on the read-write parent), an ADS on `marker.txt:stream`, and 8.3, case or trailing-dot spellings are not attempted and not listed. The reviewer's fixture shows that renaming sub away is caught (it gives FAIL as `delete`). Move-in and ADS give HOLD (finding 1).
- **Fix:** add these to the NOT MEASURED docstring list and to the register row's bounds.

### 10. LOW: smaller items
- After a FAIL STOP the tree is deleted unless `--keep-tree` is set (`run_probe.py:234`). The evidence for the private report is reduced to snapshots. Fix: keep the tree when `stop` is set.
- `C:\mxc-fx` itself is never removed (observed after the dry-only run).
- `--s5` is not gated on a DACL tier (the spec says S5 runs only if the tier is 2/3). On base-container fx-b adds three runs that measure nothing.
- `discover()` takes the first `blarai-spike-*-mxc`, the lexicographically last `build-main-*` and the last `toolchain/Python*` from shared globs (`fixtures.py:193-201`). Launcher sha256 values are recorded; the interpreter's is not. Incidence 0 (one of each on disk).
- S4 runs on the host's PATH python (3.14) while the container runs the toolchain python. Both are 3.14 today; neither interpreter is recorded with a hash.
- `summary.json` omits S3 and the per-attempt error codes. The security-suite version and "host prep ran: no" are not explicit fields (spec ENVIRONMENT list).

## S0 question: is `baseContainerSupportsDenyPaths` a faithful reading of "PSEC advertises PSE_SUPPORT_FS_DENY"?
Yes, for main `525d0f25`. `probe.rs:153` sets it from `BaseContainerRunner::supports_native_denied_paths()`, which is `is_base_container_api_present() && secenv::query_support(SecurityEnvironmentSupport::FileSystemDeny)` (`base_container_runner.rs:376-384`). `FileSystemDeny = 0x1` is tested against the flags returned by `QueryProcessSecurityEnvironmentSupport` (`secenv.rs:62, 503-549`). It is the PSE_SUPPORT_FS_DENY bit ANDed with "API present". For v1.0.0 no source was read: the doc copies describe the same field ("Raw host facts used by request tier selection") and the same rule, so the v1.0.0 binary's mapping is inferred, not verified. The per-request dry-run tier (base-container for fx-a) is the better S0 fact (finding 4).

## Attacked and could not break
- **S1 is in the same container invocation as S2** (`payload.main`: S1, then S3, then S2, one report), and it is judged host-side by exact size delta and hash. A virtualised or copy-on-write view of T fails S1, which gives STOP and INSTRUMENT-BLIND, not HOLD.
- **A container report that claims success but did not land** gives a disagreement, which gives STOP and INSTRUMENT-BLIND. A report that claims refusal of a landed write gives FAIL (the self-test toggle, re-run green).
- **The append/delete ordering cannot hide a FAIL** (finding 8 shows why).
- **A wrong T path or no payload** gives no report, which gives a STOP. It does not manufacture a HOLD (it mislabels; finding 3).
- **launch.ps1 tolerates a comment header line:** non-matching lines are skipped by the regex. Its refusals (missing file, missing line, mismatch, tamper, extra script) pass non-elevated.
- **Path guards:** git tree, UNC, user profile, OneDrive, non-NTFS and removable volumes are all refused. An output root inside the repository is refused before anything is written.
- **Committed-file hygiene:** clean (grep and scrub `--check`).
- **Dry-only:** writes only under the out-root and `C:\mxc-fx`, and removes its trees; the MXC state did not change.

## Merge read
Block the live run on 1 and 2. Both are cheap and both bear on the HOLD that would be made public: the verdict must be "sub unchanged", and the record must carry real Win32 codes so that "refused" can be attributed. Fix 3, 4 and 5 in the same round. They mislabel the outcome or narrow what the approval certifies, and 3 can trigger a needless host-prep step. 6 is safe today only because the dry-run tier is base-container; the pre-launch tier gate in finding 4's fix closes it. 7 should land with the fixes so that round 2 can show the discriminating split (a FAIL on an open tree, a HOLD on a held one) through the real harness. 8 to 10 are not blocking.

Suites run by the reviewer at 288cf104: `self_test.py` non-elevated (47/0); `run_probe.py --dry-only --s5 --runs 1` non-elevated; identity scrub `--check`; reviewer fixtures (attack.py, fake-launcher end-to-end, elevated reviewer shell). No container launched. No approval file written.
