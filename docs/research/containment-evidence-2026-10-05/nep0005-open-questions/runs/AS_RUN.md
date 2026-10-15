# NEP-0005 open questions (#1763): the half-set matrix as it ran

Run on 2026-10-13 (all times -04:00, the machine's local clock) from the admin-only live copy `C:\ProgramData\BlarAI\trackb-live` of commit `716fd87a6e1f4b530185fcebfcf0b052ccad6120` (branch `feat/1763-nep0005-open-questions`, committed 10:44:53). The four matrix scripts, `spike-persist-lib.ps1` and `spike-task-driver.ps1` in that commit hash-equal the values the run's rollback proof recorded (table below). Results are in this folder; `results-summary.json` is derived by script from the sanitised copies, one row per state. The earlier arms' sanitising convention was followed (`../../CHANGES.md`): user name -> `_OPERATOR_`, machine name -> `_MACHINE_`, the real account-domain SID part -> `1000000001-1000000002-1000000003` (relative id unchanged), JSON re-serialised (indent 2, UTF-8 without BOM, LF), no number, timestamp or verdict changed.

## What ran and when

| Phase | Started | Finished | Exit | Records | Code |
|---|---|---|---|---|---|
| taskcheck, first (`taskcheck-first-20261013-102658.json`) | 10:26:58.381 | 10:27:27.945 | 0 | 1, class ok | commit `0654307a` (committed 10:25:35): INFERRED from the commit time, the live file times and the self-test log written at that stage (306 checks); the run file does not record a commit |
| halfset, R0 to R7, 3 passes each | 10:46:31.331 | 10:49:05.182 | 0 | 24, all class ok | `716fd87a` |
| ours, O1 to O6, 3 passes each | 10:49:30.558 | 10:51:15.325 | 0 | 18, all class ok | `716fd87a` |
| n1, 3 passes | 10:51:27.384 | 10:52:51.211 | 0 | 3, all class ok | `716fd87a` |
| taskcheck, second (`taskcheck-20261013-104554.json`; bundled in addition to the four files asked for, because it is the taskcheck that ran the code the three phases ran) | 10:45:54.554 | 10:46:21.030 | 0 | 1, class ok | `716fd87a` |
| final `-Check` (`nep5-check-final.log`, file time 10:53) | not recorded | not recorded | 20 (everything reads absent / original) | | `716fd87a` |

The rollback proof for `716fd87a` was written 10:45:42.655 (310 of 310 checks, 33 rollback tags; host recorded by the proof: `ConsoleHost 7.6.6 Core on 10.0.26200.0`). The taskcheck record that opened the gate for the halfset, ours and n1 phases was written 10:46:21.018 against that proof stamp.

Runs in the output folder that are NOT bundled: a taskcheck at 07:56:41 (exit 2, refused: `SetArguments` failed with "The user name or password is incorrect"; the design of commit `481713ee`, which edited the password task, replaced by `0654307a`; nothing was added) and a halfset invocation at 10:28:04 (exit 2, refused 18 ms after start because the first taskcheck's record belonged to another proof: the stamp-comparison defect `716fd87a` fixed; nothing was added). The dry-run and self-test console logs (`nep5-dryrun*.log`, `nep5-selftest*.log`) are not bundled either.

**Launch commands (supplied by the author from the launcher script that ran them; not stored in the result files).** Each phase was started from an elevated PowerShell 7 session (`IsInRole(Administrator)` read True at the start of the session) in the admin-only live folder as `pwsh -NoProfile -File ./spike-nep5-matrix.ps1 -Run -Phase <taskcheck|halfset|ours|n1> -OutDir <admin-only folder>`, with no `-Passes` argument: the console header of each run reads "3 pass(es)", so 3 was the default. `-SelfTest -WriteProof` and `-DryRun` were run from the same folder immediately before. The halfset invocation at 10:28 and the taskcheck at 07:56 were refused before adding anything. The Bitdefender state during the runs is not recorded.

## What the run was made of

| Item | Value |
|---|---|
| Pinned srt-win source | anthropics/sandbox-runtime `24eb39e94a6de386e83d126c52317d8e0fa49522`, dir `vendor/srt-win-src` |
| Pinned `Cargo.lock` sha256 | `c41cf41050c2b1e2986ed7ca690a703415cabadfed9219788a451df0da0967ec` (equals the proof's value and the live file, read 2026-10-13 10:56) |
| Harness source `halfset.rs` sha256 | `e0d560fcb24bbe49f87509c272cd3ed8d058623601732e0d17a7d72c4bd1d44f` (equals the proof and the live file: the bytes that were built and ran). The bundled `harness/halfset.rs` hashes `cbd6ad65760bf2f297a35c5330f7ca23b0ef5339098f0818a3c910b227be7b2c` since 2026-10-13: its three SID constants were rewritten from the real machine domain to the placeholder domain (#1765), nothing else changed. `harness/tests/refusals.ps1` likewise: reviewed `fe8679451c88cc8df18791e13659ef2c3d50520196d007c5f9eb87325a5fcb67`, bundled `11b49f47ba6a1b526f6f4534b9de2364d10281c7b0920b6d7251511bd9f5c3c3` (one constant) |
| Shipped exe `halfset.exe` sha256 | `ebe029802387a86f986bab161b1903f30d24d6c4583d8016d426152d6d07229f` (equals the proof and the live file; file time 2026-10-12 19:48) |
| S1, srt-win harness sublayer | `c971a69f-d6ab-4885-9b49-506d8aa51c86` |
| S2, our own sublayer | `3e29ae7e-fd9f-413a-8b8d-da9bd3a96359` |
| S3, different-sublayer case | `6cf901ba-a6cd-4846-81a5-2598c55bdef5` |
| Our provider (S2 and S3 objects) | `3e29ae7e-fd9f-413a-8b8d-da9bd3a96360`, name `BlarAI #1763 provider` |
| Missing sublayer for O6 (never created) | `3e29ae7e-fd9f-413a-8b8d-da9bd3a96361` (from the O6 record; SPEC.md does not list it) |
| Our filter keys | `f1763001-0000-4d8e-9a31-2b6d4c8e00NN` (NN 01 to 06, 11, 12, 21, as the records name them); display names carry the marker `BlarAI #1763`; srt-win's own filter keys are generated per install |
| Test account | `blarai-spike`, relative id 1271 (the arm 2, 3a and 3b account); the identity probe returned token SID `S-1-5-21-1000000001-1000000002-1000000003-1271` (sanitised domain) |
| Stale test SID (no such account; fabricated, not sanitised) | `S-1-5-21-17630000-17630001-17630002-91763` |
| Probe targets | loopback listeners on `127.0.0.1` and `[::1]` at ports 61763 and 61764 (both outside 60080-60089) and 60085 (inside); all six reported bound in every console log |

Script hashes the rollback proof recorded (sha256 of LF-normalised bytes) and whether the bundled copy in this repository hash-equals them:

| File | sha256 | Bundled copy equals it |
|---|---|---|
| `spike-nep5-matrix.ps1` | `0a9d603504c23a022504c678a2e736abb529623f58c306b66d0a259e7586d3e5` | yes |
| `spike-nep5-lib.ps1` | `50325accd3765aa5716e97032340552d215860605424b4eecdb78defe090c50c` | equal until 2026-10-13; the bundled copy now hashes `56b6418df986d80858b160b4b47c520fcefd21f329f384d2c3b44a41e2d2dfe2` (two SID constants rewritten to the placeholder domain, #1765; nothing else) |
| `spike-nep5-run-lib.ps1` | `dd696dce58eab735fef9fb60dfab2f7569ea1a961b6dfb1e5ea3281519d9fd84` | yes |
| `spike-nep5-connect-probe.ps1` | `545333e507704d6e98cac19ee3eff803dc704c76b2fb4bd395c821bdd6cc3c66` | equal until 2026-10-13; the bundled copy now hashes `eccfd60bf5892dc24f713147f10e911785444c765d986cc7e1bf0b65ff84b1ee` (one SID constant rewritten to the placeholder domain, #1765; nothing else) |
| `spike-persist-lib.ps1` | `0193b0fcf9b8776d353a744c78880e280eb7b8a1e4333bdba4297bc1644ed97d` | yes |
| `spike-task-driver.ps1` | `d4f80e78055e2256f1e0f536daacddc5ca0106ea3dd3eea6e5e81c0c97bc1cce` | yes |
| `spike-lib.ps1` | `d3cac17824eaaefe2fe76b48cc031d0e63dc2a9e8143a0d139394122e51189a1` | no: the live copy carries the real user name, the bundled arm 3 copy `_OPERATOR_`; the proof's value equals the live-copy value in `../../arm3-persist/runs/AS_RUN.md` |
| `spike-provision.ps1` (arm 1) | `46834b333897a12e0bd7deae90ff141e94d8c2cd87f52a7ca04127754702e52e` | no, same reason (not compared further) |
| wrapped `wfp-coder-egress-spike.ps1` | `ea3e03a37d0db00570927b8f1c98d2efab53ea5bd203909bbbb70a3de0cfda6d` | not compared here; equals the arm 3 `AS_RUN.md` live-copy value |

## Interactive logon, not the earlier arms' batch logon

The account-side probes in this run ran as `blarai-spike` through a secondary logon (`CreateProcessWithLogonW`, `LOGON_WITH_PROFILE`), recorded in every probe record as "interactive (CreateProcessWithLogonW, LOGON_WITH_PROFILE); NOT the batch logon the existing task uses"; working folder `C:\blarai-spike\bin`. Arms 1 to 3b probed through the account's scheduled task (a batch logon). The token shape is therefore different from the earlier arms'. The child's environment was an explicit block; the records list the variable names only (`APPDATA`, `ComSpec`, `LOCALAPPDATA`, `PATH`, `PATHEXT`, `PSModulePath`, `SystemDrive`, `SystemRoot`, `TEMP`, `TMP`, `USERPROFILE`, `windir`), never values. For each phase a fresh session password was set on the account and held in memory only (the record says so; no value is recorded anywhere); at the end of each session `spike-provision.ps1 -Apply -ForceNewPassword` reset the account password again and re-registered the account's scheduled task `\BlarAI\BlarAI-Spike-Model` with a new vaulted password. All three phases and both taskchecks record the restore: task now `original`, definition equal to the recorded baseline, restored task started as the account, no files left in the bin folder, reprovision exit code 0.

## What was running

Not recorded in the run files. Read afterwards, at 10:58 the same day: processes `bdagent, bdntwrk, bdredline, bdservicehost, bduserhost` present (Bitdefender; the earlier bundle's name list is the same). Whether Bitdefender was in the same state at 10:46 to 10:53 is an inference from that read and from its presence in arms 1 to 3b. Other load (this machine's other sessions, the operator desktop, a model load) is not recorded.

Host: Intel Core Ultra 7 258V, 31.3 GB (read 10:58); Windows 11 Pro 10.0.26200, display version 25H2, update build revision 9457 (read 10:56, i.e. 26200.9457, the build the earlier arms record); last boot 2026-10-12 14:59:49 per `Win32_OperatingSystem` (the arm 3b record has 14:59:46), so uptime at the halfset start was 19.8 h (computed). That boot is the arm 3b restart's boot; no other restart between it and these runs is known.

## Results

Copied by script from `results-summary.json`. Account columns are the account's connect results with the state in place (blocked = Windows error 10013 in every case; the other result was `connected`, error 0). Before every state's filters the account connected to all six targets in every one of the 42 connect cycles (252 of 252 control rows connected). The operator connected during and before in all 42 cycles (operator control 42 of 42 before, 42 of 42 during, and 3 of 3 outside the permit range before each); the watchdog made 1 or 2 connects per cycle and recorded 0 failures. Across the 42 cycles the account's during-state rows were 150 connected and 102 blocked (252 rows), probe time 1 to 41 ms.

srt-win's own status word and filter count in S1 (first pass; identical in all three passes): R0 absent, 0 filters; R1 installed, 4; R2 installed, 3; R3 installed, 3; R4 `absent`, 2 (both permits stand); R5 installed, 2 (both blocks stand; its parsed status carries no port range); R6 installed, 4 (tagged with the stale SID); R7 absent, 0 (S1 empty while the account is blocked by our unlabelled blocks in S3). In the S2 rows (O1 to O6) S1 is empty, so its status reads absent by construction.

O4 detail: the exact-port permit (`127.0.0.1:61763`, no user condition) beside both blocks left only the v4 connect to 61763 open; the neighbour port 61764 on v4, and every v6 target, stayed blocked. O5: the engine answered `added` for a block with no provider (`s2-noprov-block-v4`), and the account was blocked on v4 only. O6: the engine refused the add (`FwpmFilterAdd0 0x80320007`, recorded as the engine's own text), nothing stood, and the account connected everywhere.

N1 detail (3 passes, identical): the sublayer, provider and one block were added by us first (elevated, key `f1763001-0000-4d8e-9a31-2b6d4c8e0001`); the account's own standard token then made one direct `FwpmFilterAdd0` and one direct `FwpmFilterDeleteByKey0`. Add: denied, `0x00000005`, at the call, and no filter of that attempt was present afterwards. Delete: denied, `0x00000005`, at the call, and the test filter was still present afterwards (then removed by key by us). Neither succeeded.

Post-state direct removal checks (every state and pass, 42 of 42 cycles plus 3 N1): after removal by key, S1, S2 and S3 each enumerated 0 filters and read as absent sublayers, the provider read absent, `netsh wfp show filters` had 0 hits for the marker, `srt-win`, the three sublayer GUIDs and the provider, and the sweep read clean with no foreign filter. The console logs of all phases end with the same direct checks (`S1: 0 filter(s); sublayer present: False` and the same for S2 and S3, `provider present: False`, `export hits: ... 0`), and the final `-Check` exited 20.

## Exports (not bundled)

95 `netsh wfp show filters` XML exports were written by the runs (halfset 49, ours 37, n1 7, the two taskchecks 1 each): the pre-clean and a before and an after export for every state and pass. Every one is 3,557,094 bytes and every one has the same sha256, `2fd651444b67f5de3592191dafadede2b8e907afc83fadeb4a0a0622ee48b310`. All were taken with no test filter standing (before adding and after removal); none was taken while a state stood. `exports-manifest.json` lists each file name, byte size and sha256; the files stay in `C:\ProgramData\BlarAI\arm3b-out\` (admin-only). The three arm 3b exports in the same folder are covered by the arm 3b record, not this one.

## Files in this folder

| File | Bytes | sha256 | Raw source (read-only) and its sha256 |
|---|---|---|---|
| `halfset-20261013-104631.json` | 1,050,497 | `62cf6bdd893dd5eb1e791d35c892e3deedaebff6e070978c27c5aa3e1bb7a0a7` | `nep5-run-halfset/nep5-results-halfset-20261013-104631.json` (1,074,607 bytes) `85dfe75252fb0f382e22863b7e6062cba2d473c6cdf7df9ac259f00c65633e30` |
| `ours-20261013-104930.json` | 530,393 | `0099bcf0e39c09f990574cf3a207299b7521222b604548ff1df6ad97b443981f` | `nep5-run-ours/nep5-results-ours-20261013-104930.json` (545,887 bytes) `36d270dc2f908ca5bd01701cb6de98984fe34925ec8d7d1147e7892a33ad0ba6` |
| `n1-20261013-105127.json` | 65,488 | `3115eb9048e9903e36b46eea2b3fc38b92adb0371ea896110051e9019da04f4e` | `nep5-run-n1/nep5-results-n1-20261013-105127.json` (67,210 bytes) `83420d42e833fd4c4950322eef98ffedd1a0a1c872d667c66d6b571a5b416f3a` |
| `taskcheck-first-20261013-102658.json` | 6,449 | `28035d645b74dc79b81f2ef3b92ab45bf105581a8b3b4a36a67823a0f350b527` | `nep5-run2/nep5-results-taskcheck-20261013-102658.json` (6,608 bytes) `db01bfb99250fe9db63396ff909189899089e2a89ad8aa87b35ccc1857d7b5f4` |
| `taskcheck-20261013-104554.json` | 6,364 | `ebbb40d096531160a4990429ca3f705352da811ec0239cfd4ad05dd30dc4b61c` | `nep5-run-taskcheck/nep5-results-taskcheck-20261013-104554.json` (6,522 bytes) `004e560b2edc4a3cb0f7c848e3d9ca8687685e94ef5278118f215a91e09c9fda` |
| `results-summary.json` | 126,172 | `fab0d76a2eea65df504f3fea9b8992de027e3799d0c7fcd891ca9bcff08b4a0c` | derived by script from the sanitised copies and the console logs |
| `exports-manifest.json` | 19,366 | `4311d21a960d6fc293529f0d43a6e9713ff72ee0417bd4c143dae13d6d3fdda8` | derived from the 95 raw XML exports |

Console logs read for the final direct checks and the bound-listener lines (their name, size and sha256 are in `results-summary.json`, `console_logs`): `nep5-halfset.log`, `nep5-ours.log`, `nep5-n1.log`, `nep5-taskcheck.log` (second taskcheck), `nep5-taskcheck2.log` (first), `nep5-check-final.log`.

## Sanitising in this bundle

Replacements made (counts from the script): account-domain SID part: halfset 645, ours 21, each taskcheck 1, n1 0; user name: n1 6 and each taskcheck 2 (all inside the `spike-provision.ps1 -DryRun` tail paths), halfset 0, ours 0; machine name: 0 in every file. The stale test SID is fabricated and was left as it is. Paths under `C:\ProgramData\BlarAI\` (the output and live folders) and `C:\blarai-spike\` were kept, as in the earlier bundles. The harness proof file is named by path only in the harness command lines; its contents are not here. No password, token or environment value is in any file: the records hold the word "password" only as the key `password` with `ok`, `reason` and `changed`, and as prose ("held in memory only"). Not stripped: the harness stdout copies inside each record, the per-command argument lists and the sweep records.

## Not measured

- Anything beyond loopback: every target was a loopback listener on `127.0.0.1` or `[::1]`; no internet address (the earlier arms' `1.1.1.1:443`), no other host, no UDP, no DNS, no other ports than 61763, 61764 and 60085.
- Persistence or time: each state stood for seconds (the cycle for one pass took 4 to 6 s), added and removed in the same pass; no restart, no hold, no sleep, no second boot or day. The three passes of a state ran back to back on one boot; "identical" means identical across those three, not variation across conditions.
- The probe's token is an interactive-logon token with a minimal environment, not the batch logon of the account's scheduled task; whether the task's batch token behaves the same under these states was not run.
- The Network Configuration Operators row (Part 3 of `../SPEC.md`) was not run.
- The Bitdefender state during the runs, and other machine load: not recorded.
- Engine access list or security descriptor dumps (SDDL): not recorded in these runs.
- Exports while a state stood: none taken; the state is evidenced by the harness `enum` and `status` readings and our key reads.
- The meaning of `0x80320007` and `0x00000005` beyond the record's own text; the record does not name them.
- Speed: a connect refusal or success takes 1 to 41 ms here; this is not a latency measurement.

## srt-win's own command line on half-sets (2026-10-13, 16:39 to 17:03 -04:00)

What ran: `srtcli/srtcli-halfset.ps1` from the admin-only live folder, deployed by `srtcli/Deploy-Srtcli.ps1` as it stood at `7097fbec` (its `-BuildRoot` default was removed afterwards, in `099c05b6`), after `-SelfTest -WriteProof` and a clean `-DryRun`. srt-win's own `install` created its own `srt-sandbox` account and filters in test sublayer S1 (Lead Architect approval, #1763 comment 4095; the wider install footprint is listed in comment 4096). Reviews: Opus, six rounds, disposition `docs/reviews/nep0005-srtcli-halfset-review-disposition-2026-10-13.md`.

| Run | Driver | Build | Window | Exit | Raw record (admin-only, not committed) | Bytes | sha256 |
|---|---|---|---|---|---|---|---|
| first cycle (not counted) | `819b4d9a` (commit `70b9c877`) | stock | 16:39:32 to 16:42:24 | 10: stopped on its ACL check after pass 1 | `arm3b-out/nep5-srtcli-stock-20261013-163932/record.json` | 180,183 | `14fa02f3cba8b3182e907a6e1bc268c83793ff03e758390f32449ebe6d16ca56` |
| counted | `baaa8764` (commit `7097fbec`) | stock | 16:52:47 to 16:57:46 | 0, 3 passes | `arm3b-out/nep5-srtcli-stock-20261013-165247/record.json` | 519,561 | `2022306e51e940774328718014ad23e1d5537d23cfcbabce79f3399a1e528b17` |
| counted | `baaa8764` (commit `7097fbec`) | patched | 16:58:02 to 17:03:13 | 0, 3 passes | `arm3b-out/nep5-srtcli-patched-20261013-165802/record.json` | 549,459 | `d5ce5808aec322065d7708faaaf89ad1421200e163ecf8571b1002fec3b30ba0` |

An earlier `-Run` at 16:36 refused at its own proof gate before touching anything (the proof's time stamp, round-tripped through JSON, was read through local time; fixed as `Test-ProofFresh`, review round 4).

The counted runs' directories also hold the ACL snapshots (`acl-baseline.tsv`, `acl-after-p<N>.tsv`, about 45 MB each). The first cycle's changes were classified against a read-only scratch snapshot taken about 45 minutes earlier with the same enumeration (127,850 entries, reparse points skipped); the driver's own back-to-back baselines inside that run agreed on the count (577 changed, churn 0).

After the last run, srt-win's leftover `C:\ProgramData\sandbox-runtime` (empty; DACL `D:PAI(D;OICI;FA;;;<deleted group SID>)(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)(A;OICI;0x1301bf;;;BU)`) was recorded and removed by hand at 17:03, the one manual removal named in comment 4096; a final `-DryRun` at 17:03 then read every footprint item absent, the store folder included, and the WFP state export 0 for srt-win, S1, S2, S3 and the default sublayer. The two counted runs began with the store folder already present (left by the first cycle; the preflight allows it and records it).

Repository copy: `srtcli-results-summary.json` (40657 bytes, sha256 `744f67640a0267e165445f5315dae0cfea1e45d7392e7ab69849a2ce94ea14ad`, LF line endings as committed; the exporter reproduces these bytes), written by `srtcli/Export-SrtcliSummary.ps1`, which replaces every machine SID domain and the user name, cuts the ACL example paths to the stamped directory, and refuses to write if either remains.

Not measured in these runs: real IPv6 or internet egress; another machine or Windows build; a restart with a half-set in place; a non-elevated caller; the TypeScript consumer of `partial` (`checkWindowsDependencies`); file ownership (only the access section of each DACL was snapshotted); the antivirus state and machine load.
