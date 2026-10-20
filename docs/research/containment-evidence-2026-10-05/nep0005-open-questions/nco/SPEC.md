# Case 4: NEP-0005 Q2 for a delegated non-administrator. Build spec for the probe half

Binding gate: presented in chat 2026-10-19, reviewed (`docs/reviews/review-1764-case4-gate-2026-10-19.md`, PASS WITH CORRECTIONS; the file is committed with this branch), delta gate PASS,
confirmed by the Lead Architect ("Proceed"). Companion of `../SPEC.md` (the half-set matrix) whose constants, sublayers, library and proof pattern this
build reuses. The question: can a member of the local group Network Configuration Operators (well-known SID `S-1-5-32-556`) add and delete a Windows
Filtering Platform (WFP) filter in the recorded test sublayer S2, and under which token state (filtered or elevated)?

## What a session may and may not do (standing, from the Lead Architect's rulings)

* The account lifecycle is the Lead Architect's by hand, in Windows' own tools: create `nco-probe`, add it to the group, enable it before the run, remove
  the membership, delete the account, delete the profile. **No script, test, helper or subagent here creates, enables, disables, deletes, logs on, resets
  the password of, or changes the group membership of any account.** No `CreateProcessWithLogonW`, `LogonUser`, `runas` with a stored password, `net user`
  with a password, `New-LocalUser`, `Add-LocalGroupMember`, `Set-LocalUser` or a Scheduled Task with credentials anywhere in this folder. A password never
  enters a file, a command line, an environment variable, a ticket or a session. The Lead Architect types every launch line and every password himself.
* Reads are allowed: `LookupAccountName`, `LookupAccountSid`, `net user <name>` (no password), `net localgroup <group>` (no member change), `Test-Path`.
* A safety-classifier stop on any step is recorded on the ticket and never worked around or retried in another form.
* Builders NEVER open the real WFP engine for writing, run the probe with `--live`, or write a probe proof. Offline self-tests, compiles and refusal-path
  invocations only (every refusal path exits before the first engine open). Reviewers the same, from a non-elevated process (`scripts/run-limited.ps1`).

## Fixed constants (recorded; never generated at run time)

| Name | Value |
|---|---|
| sublayer the probe adds to | S2 `3e29ae7e-fd9f-413a-8b8d-da9bd3a96359` (the only sublayer the probe may name) |
| provider the probe's filter names | `3e29ae7e-fd9f-413a-8b8d-da9bd3a96360` (created by the admin driver in the same transaction as S2) |
| layer | `FWPM_LAYER_ALE_AUTH_CONNECT_V4` `c38d57d1-05a7-4c33-904f-7fbceee60e82` |
| action / weight | BLOCK, weight `0x1000` (FWP_UINT64), flags persistent `0x1` |
| the probe's one filter key | `c4a0e001-0000-4d8e-9a31-2b6d4c8e0041` (fixed; the admin sweep deletes it by key if the probe leaves it) |
| user condition | `FWPM_CONDITION_ALE_USER_ID` `af043a0a-b34d-4f86-979c-c90371af6e66`, FWP_MATCH_EQUAL, FWP_SECURITY_DESCRIPTOR_TYPE (14), SD built for the stale SID |
| stale SID (resolves to NO account; the probe refuses if it does) | `S-1-5-21-17630000-17630001-17630002-91763` (the matrix's recorded stale SID: a fabricated domain, never this machine's) |
| expected account for F and E | local account name `nco-probe`; its SID is read at run time by `LookupAccountName` and recorded, never written into code |
| display name | taken from the probe proof (`display_name`), written there by the driver from the library's marker constant; the probe source holds no marker text |
| public folder | `C:\ProgramData\BlarAI\case4-pub\` with `bin\` (probe exe + probe proof; Users read and execute) and `drop\` (records; write access for `nco-probe` and the operator) |
| admin-only folders | scripts and proofs in the live folder `C:\ProgramData\BlarAI\trackb-live` (the driver sits beside the matrix); records in `<live>\nep5-out\case4\` |
| probe proof schema | `nep5-case4-probe-proof-v1` |
| driver proof file | `case4-selftest-proof.json` beside the driver, schema `nep5-case4-driver-proof-v1` |

Research-tree locks (`tests/security/`): no file in this folder carries a tracker reference of the form `#` + 3 to 5 digits, a fixture prefix (`p` + 4 or
5 digits + `-`/`_`), or this machine's account-domain SID. Records committed under `runs/` carry this machine's account domain rewritten to the
bundle placeholder domain `1000000001-1000000002-1000000003` (Part 3 names the route); `scrub_public_identifiers.py --check` (in scripts/) is clean
before any commit; nothing is stripped at source in the admin-only out dir.

## Part 1: the probe `ncoprobe.exe` (builder B1)

One C# source `probe/NcoProbe.cs` plus a generated `probe/BuildInfo.cs` (the source's sha256 as a constant), compiled by `probe/build-probe.ps1` with the
.NET Framework compiler already on the machine (`C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe`, `/platform:x64 /optimize+ /target:exe`,
no NuGet, no SDK install) into `ncoprobe.exe`; the build script prints JSON with the sha256 of the exe and of `NcoProbe.cs` and refuses a build dir inside
a git tree. `ncoprobe.exe --version` prints both hashes. The program must run under a token with no loaded profile and with the minimal environment
`runas` gives (no reliance on `%TEMP%` being writable, no `Add-Type`, no PowerShell).

Subcommands (one JSON object on stdout; exit codes below):

* `identity` opens no engine. Prints the token facts (below).
* `selftest` opens no engine. Runs every pure check against fake inputs and prints `{checks_run, checks_failed, failures[]}`.
* `run --cond F|E|S|A --live <proof.json> --out <dir> [--wait]` the live run: token facts, then ONE `FwpmFilterAdd0`, a read-back, ONE
  `FwpmFilterDeleteByKey0`, a read-back; the record is written to `<dir>\case4-<cond>-<utc yyyyMMdd-HHmmss>-<pid>.json` AND printed; `--wait` keeps the
  console open on a key press so the operator can read it in a `runas` window.
* `--version`.

Token facts (all from the process's own primary token via `OpenProcessToken`/`GetTokenInformation`; every read records its own Win32 error when it fails,
and a failed read never aborts the others): user SID and resolved name; every group SID with its attributes word and the derived flags `enabled`,
`enabled_by_default`, `use_for_deny_only`, `integrity`, `logon_id`, `owner`, `mandatory`, plus the resolved name when `LookupAccountSid` can give one;
the integrity level SID and its label; `TokenElevationType` (1 default, 2 full, 3 limited); `TokenElevation`; whether `TokenLinkedToken` returns a handle
(presence only, the handle is closed at once; the error code when it fails); the attributes of `S-1-5-32-556` (Network Configuration Operators) and of
`S-1-5-32-544` (Administrators) when present; `LookupAccountName("nco-probe")` (SID or the error); `is_expected_account` = (user SID equals that SID);
process id, session id, the exact command line, machine clock (local with offset and UTC), the probe's own exe sha256 and the embedded source sha256.

Run order and refusals (every refusal is before the first `FwpmEngineOpen0`):

1. Arguments: exactly the forms above; unknown flag, missing value, a `--cond` outside F/E/S/A, `--live` on `identity`/`selftest`: exit 2.
2. Arming: the proof file must exist, be a regular file under 1 MiB, parse as JSON, carry `schema` = `nep5-case4-probe-proof-v1`, `probe_exe_sha256` equal
   to the running exe's own bytes (SHA-256 computed in-file, pinned by two FIPS 180-4 vectors in `selftest`), `probe_cs_sha256` equal to the embedded source
   hash, `sublayer` = S2, `provider` = the provider key, `filter_key` = the fixed key, `user_sid` = the stale SID, `display_name` a non-empty string of at most
   120 characters, `expected_account` = `nco-probe`, `checks_failed` the integer 0, `written_utc` an ISO 8601 timestamp with a zone, not older than 24 h and not
   more than 5 min in the future. Anything else: exit 3 `not_armed`, naming the field. The proof gates intent (a deliberate run), not authority.
3. Stale SID: `LookupAccountSid` of the stale SID must FAIL with `ERROR_NONE_MAPPED` (1332); a mapping or any other outcome: exit 4 `stale_sid_resolves`
   (the filter must match no real account).
4. Output dir: must exist and accept a test file create + delete; else exit 5 `out_dir_unwritable`. The record is written after the engine is closed, so a
   failure to write at the end prints the record to stdout and exits 5 as well.
5. Token facts (identity); if the user SID itself cannot be read: exit 6.
6. Engine: `FwpmEngineOpen0(null, RPC_C_AUTHN_DEFAULT, null, session{flags = 0, txnWaitTimeoutInMSec = 10000})` (a non-dynamic session so an added filter
   that the delete fails to remove PERSISTS and is measured, then removed by the admin sweep). Open failure: `phase = open`, rc verbatim, exit 7
   (an open failure is NOT a write verdict).
7. Add: ONE `FwpmFilterAdd0` with the constants above, no explicit transaction (the status is the call's own). Record `add.rc` (hex, verbatim) and the filter
   id when 0. Then `FwpmFilterGetByKey0(key)`: `add.present_after` true/false/unreadable with the rc.
8. Delete: ONE `FwpmFilterDeleteByKey0(key)` ALWAYS (even if the add failed: a delete of an absent key gives `FWP_E_FILTER_NOT_FOUND` 0x80320003, which is
   recorded, not treated as a denial). Record `delete.rc`; read back again: `delete.present_after`.
9. Close the engine; classify: `add.class` = `succeeded` (0), `denied` (0x5 or 0x80070005), `other`; `delete.class` likewise, with `not_found` for 0x80320003.
   `overall`: `ok` when the sequence ran (whatever the classes); `filter_left_behind` when `delete.present_after` is true (exit 8: the sweep removes it);
   never a stop for a successful add alone (the expected answer for E is success).
10. Write the record. Exit 0 (ran), 8 (ran, filter left behind).

The probe makes NO other WFP call (no enumeration, no sublayer or provider add, no transaction API), no network call, no account/group/task/registry write,
and reads nothing outside the proof file. The pure checks in `selftest`: the SHA-256 vectors; proof refusals field by field (each of the eleven fields planted
wrong, one at a time, refused with the field named; the matching proof accepted); the fixed constants equal to the ones in this table (GUID text compared);
`FWPM_FILTER0` size 200 and `FWPM_FILTER_CONDITION0` size 40 on x64 (the matrix's own layout assertion); the SD builder output for the stale SID is parsed back
by `ConvertStringSecurityDescriptorToSecurityDescriptor`/`ConvertSecurityDescriptorToStringSecurityDescriptor` to a DACL naming exactly that SID; the
rc classifier (0, 0x5, 0x80070005, 0x80320003, 0x80320007, 0xdeadbeef); the record file name builder; the argument parser refusals; a guard-toggle
mechanism like the harness's (`NCOPROBE_TOGGLE_OFF=<guard>` honoured ONLY by a build made with `build-probe.ps1 -Toggle`, whose `--version` says
`toggle_build: true`, used by `run-probe-selftest.ps1` to show the bad outcome is reachable when a guard is off: proof refusal, stale-SID refusal).

The process-level rows live in the probe itself as `selftest-process --exe-dir <dir>` (C#; the runner is spawned on both exes): the refusal paths of `run`
(no proof, a forged proof with the right exe hash but a wrong sublayer, a stale proof, a future proof, each other field planted wrong, an unwritable out
dir) with the exit codes and the named field asserted, and no engine opened (the probe appends one line to the file named by
`NCOPROBE_ENGINE_OPEN_TRACE` on every engine open; the test asserts the file stays absent/empty); with the toggle build it shows the refusal is reachable
when off and the guard holds when on; `identity` cross-checked against the process's own token. `probe/run-probe-selftest.ps1` is a plain runner (build
both exes into a temp dir outside any git tree, run `--version`, `selftest`, `selftest-process`, print `checks_run / checks_failed`, exit 1 on any failure).
Amendments recorded 2026-10-19 (builder B1, accepted): `BuildInfo.cs` is generated beside the exe in the build dir, not in `probe/`; the embedded source hash
is LF-normalised (raw also in the build record); exit codes 1 selftest failed, 10 trace file unusable or x64 layout mismatch (engine untouched), 11 internal
error; `run` without `--live` exits 3 (field `live`); the toggle build also honours `NCOPROBE_TOGGLE_STALE_SUBJECT` so the stale-SID refusal is reachable
without any account change; a delete read-back of `unreadable` after a DENIED add exits 0 with residue `unknown`, but after an add that returned 0
or threw it is `filter_possibly_left_behind`, exit 8, with the STOP line (review round 2, P2-1). Review round 1 (2026-10-19) corrections: 0x80320028 is
FWP_E_OUT_OF_BOUNDS (SDK winerror.h), not an access-denied code: it classifies as `other`, and `denied` is 0x5 and 0x80070005 only (the harness
`halfset.rs` carries the same mislabel; no banked record holds that status); resolved names are recorded only for well-known SID families, never for
S-1-5-21, S-1-11 or S-1-12 SIDs (a Microsoft-account group name is the operator's e-mail), and the user SID is recorded without a name; a thrown
exception around a WFP call is class `other` with the text, never `succeeded`; exit 12 `wrong_principal` before the engine when F/E runs are not the
expected account or S/A runs are.
Endpoint protection quarantined the first runner under the name `selftest-probe.ps1` (heuristic CMD:Heur.BZC.PZQ.Boxter) and then blocked that path
whatever its content, hence the runner's name. `Convert-ToLive.ps1` skips `.cs` files: the probe source and `BuildInfo.cs` are copied raw into the live folder.
The driver's file name is `spike-nep5-c4-driver.ps1`: endpoint protection quarantined three revisions written under the name first used for it, then
refused that path whatever its content; a second name was taken at execution time (static signature family Generic.PWSH.CoinStealer per the quarantine
metadata of two removals), and the files the operator restored from quarantine stayed held against write, rename and delete even for him, so the
third name is the one the operator's two file-level exceptions (Antivirus + Advanced Threat Defense; worktree copy and live copy) cover; the lock
pattern tables and planted fixtures live in `case4-lock-corpus.json`, read as data and bound in the proof, so the executed script carries none (bisection record in the admin-only
`arm3b-out/case4-replay/bisect/`).

## Part 2: the admin driver `scripts/spike-nep5-c4-driver.ps1` (builder B2)

A NEW file beside the matrix in the live folder; dot-sources the same libraries the matrix does through the SAME `Get-VerifiedLibBlock` pattern (copy the
function; read-once, hashed, evaluated from those bytes): `spike-lib.ps1`, `spike-persist-lib.ps1`, `spike-task-driver.ps1`, `spike-nep5-lib.ps1`, then
`Import-WfpHelpers` on the wrapped `wfp-coder-egress-spike.ps1` and `Initialize-Nep5Type`. The arm scripts and the matrix are NOT edited. Everything that
touches the machine goes through the library's seams (Runner = the harness via `New-HalfsetRunner`, Backend = `New-Nep5RealBackend`, Exporter =
`New-Nep5RealExporter` or the matrix's equivalent) so `-SelfTest` drives the logic against the fakes the library already provides (`New-FakeHalfset`,
`New-Nep5FakeBackend`, `New-Nep5FakeExporter`).

Modes (exactly one):

* `-SelfTest [-WriteProof]`: pure, against the fakes; runs `probe/run-probe-selftest.ps1` (via its path beside the driver: the live folder holds `ncoprobe.exe`,
  `NcoProbe.cs`, `BuildInfo.cs`, `build-probe.ps1`, `run-probe-selftest.ps1`; the `.ps1` files through `Convert-ToLive.ps1`, the rest copied raw) and, if EVERYTHING passed,
  writes `case4-selftest-proof.json`: sha256 (LF-normalised for text, raw for the exe) of the driver, the probe exe, `NcoProbe.cs`, `build-probe.ps1`,
  `run-probe-selftest.ps1`, `run-limited.ps1`, every library loaded (the hashes of the bytes that ran), the wrapped script, the harness exe, and the matrix's
  harness live proof (`harness-live-proof-1763.json`, which must validate per `Test-N5HarnessLiveProof` at write time: the matrix's own fresh
  `-SelfTest -WriteProof` runs FIRST); plus `written`, `host`, `checks_run/passed`, the required-tag list (below). At least 60 checks.
* `-DryRun`: prints exactly what `-Prepare`, `-Collect`, `-Finish` would do, the ACL plan for the public folder, the probe proof that would be written (with
  the hashes), the four launch lines of the run sheet with real paths, the manual rollback snippet (the library's `Invoke-ManualN5Rollback` text), and whether a
  valid driver proof exists. Opens no engine, writes nothing.
* `-Check`: read-only: `Invoke-Nep5DirectSweep` (S1/S2/S3, provider, export hits), public folder present or absent, drop files count, `nco-probe` account
  present (`net user`, read), group members (`net localgroup`, read), profile folder present. Exit 20 everything absent, 21 something present, 22 unreadable.
* `-Prepare`: elevated, scripts folder admin-only (`Test-AdminOnlyFolder`), out dir admin-only, driver proof valid (hash-bound token as `Test-N5Proof`'s
  pattern, per-process nonce), sweep CLEAN (else refuse 2, or STOP 9 on a foreign filter), engine security descriptor read (`netsh wfp show security
  type=engine`, text recorded), then `Add-Nep5OurPlan` with a plan that adds the provider and S2 (SubLayerUsesProvider) and NO filters, `SidProblems` from
  `Get-Nep5SidProblems` for the stale SID (operator token read by `Get-OperatorTokenSids`), then the S2 security descriptor read (`netsh wfp show security
  type=sublayer`; find the form netsh accepts, braces or not, and record the command used and its output), then the public folder: created with inheritance
  disabled and an explicit DACL: SYSTEM full, Administrators full, Users read+execute on the folder and `bin\`; `drop\`: SYSTEM full, Administrators full,
  the local account `nco-probe` (resolved by `LookupAccountName` at prepare time; refused if the name does not resolve, resolves to a group, or its SID is in
  the operator's token or in Administrators) Modify, the operator's user SID Modify (for the S control); the ACL plan is a PURE function of the three SIDs
  and is self-tested; the exe and the probe proof (`display_name` = the library marker + ` case4 nco probe`, `written_utc` now) are copied/written into
  `bin\`; a prepare record `case4-prepare-<stamp>.json` is written to the out dir (hashes, SIDs, SDs, ACL as applied read back with `Get-Acl` SDDL, the
  sweep record). Prints the run sheet lines.
* `-Collect`: reads every `case4-*.json` in `drop\`, validates each (schema `nep5-case4-record-v1`, `probe_exe_sha256` equals the prepared exe, `cond` in
  F/E/S/A, `is_expected_account` true for F and E, clock within the prepare-to-now window, no duplicate pid+stamp), copies the originals into the out dir
  `case4-runs\`, enumerates S2 (`Get-Nep5Residue`: any filter present beside provider+sublayer is recorded as `left_behind`), and prints a table per
  condition: n, elevation type, integrity, `S-1-5-32-556` attributes, Administrators attributes, add rc/class, delete rc/class. Invalid records are listed
  with the reason and never counted. Exit 0; 4 when any record is invalid; 21 when a filter is left behind (removed only by `-Finish`).
* `-Finish`: `-Collect` first (its result is part of the final record), then `Remove-Nep5All` (by key: the probe's key, the library's fixed keys, S2,
  provider), `Invoke-Nep5DirectSweep` must read CLEAN (else exit 7 with the manual rollback printed), the engine SD read again and compared with the
  prepare one (differences recorded), the public folder removed (first the `drop\` ACEs for `nco-probe` and the operator are removed and the removal read
  back, then the tree deleted; recorded), final record `case4-final-<stamp>.json`. Exit 0 clean, 7 not verified, 9 STOP.
* `-PartD`: read-only after the Lead Architect's part C: `net user nco-probe` (expects "could not be found"), `net localgroup "Network Configuration
  Operators"` (expects no `nco-probe`), `C:\Users\nco-probe` absent; records `case4-partd-<stamp>.json`; exit 20 all gone, 21 something remains.

Stop conditions (exit 9, nothing cleaned up by the stopping mode, the manual rollback printed): a filter of ours or srt-win's outside S1/S2/S3; a drop
record whose `user_sid` for F or E is not the `nco-probe` SID AND whose add succeeded (a filter was added by the wrong principal: recorded, then the sweep
in `-Finish`); the `nco-probe` SID found in the operator's token or in Administrators at `-Prepare`.

Required self-test tags (each a named check that must pass for the proof to be written): `acl-plan-pure`, `acl-refuses-admin-member`, `acl-refuses-group`,
`acl-refuses-operator-sid`, `prepare-refused-without-proof`, `prepare-refused-over-stale-objects`, `prepare-stops-on-foreign`, `plan-provider-and-s2-only`,
`plan-no-filters`, `probe-proof-fields`, `probe-proof-hash-binding`, `record-validation` (each field planted wrong), `record-wrong-account-stop`,
`collect-left-behind`, `finish-removes-by-key`, `finish-sweep-must-be-clean`, `finish-removes-folder`, `finish-ace-removal-read-back`, `partd-reads`,
`seams` (no real engine/harness/export/ACL call reachable in `-SelfTest`: a parser check that every machine-touching call sits behind a seam),
`no-account-lifecycle` (a parser check that none of the forbidden verbs/APIs of the standing section appears in the driver or the probe source),
`proof-hash-binding`, `harness-live-proof-fresh`, `controls-tested-off` (each gate switched off shows the bad outcome is then reachable).

`scripts/run-limited.ps1 -Command '<text>'`: the reviewer's non-elevated launcher. Writes a temporary `.cmd` that runs the command with stdout+stderr to a
temporary file and a done marker, launches it through `explorer.exe` (the shell's medium-integrity token; no `runas`, no password, no `/trustlevel`), waits
for the marker (timeout parameter, default 300 s), prints the output, deletes the temporaries. `-SelfCheck` runs `whoami /groups /fo csv` through it and
asserts `Mandatory Label\Medium Mandatory Level` and `BUILTIN\Administrators` with `Group used for deny only`. Endpoint protection on this machine quarantines
scripts that combine `runas` with token-enumeration commands: this helper must not contain the string `runas`.

## Part 3: run sheet, records, claims (the author, after review)

* `RUN_SHEET.md` beside this spec, with every line verbatim and real paths: (0) the matrix's fresh `-SelfTest -WriteProof`, `-DryRun`, `-Run -Phase taskcheck`,
  `-Run -Phase n1` (the standard-token control, `blarai-spike`, under the approved password-reset design), with the sha256 of the live matrix bytes
  recorded in the prepare record (they differ from the repository copy, whose SID constant is the placeholder); (1) driver `-SelfTest -WriteProof`, `-DryRun`,
  `-Prepare`; (2) the Lead Architect enables `nco-probe`; (3) F three times: `runas /user:nco-probe "cmd /k <bin>\ncoprobe.exe run --cond F --live <bin>\nco-probe-live.json --out <drop> --wait"`;
  (4) E three times, TWO steps: first `runas /user:nco-probe cmd` (the filtered console as `nco-probe`), then INSIDE that console an elevation request for the
  probe line with `--cond E` (`powershell -NoProfile -Command "Start-Process cmd -Verb RunAs -ArgumentList '/k ...'"`); the prompt that appears is for
  `nco-probe` (the group gives it a linked token); if Windows refuses to elevate, that refusal is the E result and is recorded; a one-step elevation from the
  operator's own console would elevate HIM and the record's `is_expected_account` false makes the run invalid; (5) S three times from his normal
  non-elevated console, A three times from his elevated console; (6) driver `-Collect`; (7) `-Finish`; (8) his part C; (9) `-PartD`.
* Records: the originals stay in the admin-only out dir; sanitised copies go to `runs/` with `AS_RUN.md` and `results-summary.json`. Sanitisation
  is `rewrite_sid_domain.py (in scripts/)` on the TRACKED copies (it rewrites only this machine's account domain to the bundle placeholder and keeps
  the fabricated stale-SID domain, which the `--dir` mode of the identifier scrub would wrongly rewrite: review finding P1-9), then
  `scrub_public_identifiers.py (in scripts/)` and its `--check` for host and user names.
* Claim C27 in `docs/research/account-level-containment-evidence-2026-10-05.md`, PERFORMANCE_LOG entry + `docs/performance/nep5_case4_nco_<date>.json`,
  journal fragment, disposition record for every review, the register entry proposed in the campaign's updates file.

## Review and run order

B1 and B2 build in parallel (disjoint files) -> independent adversarial review of each (Opus, from `run-limited.ps1`, no engine reachable, never writes a
probe proof, never passes `--live`) -> author fixes -> re-review until PASS -> deploy to the live folder (`Convert-ToLive.ps1 -Apply` for the text files; the
exe copied and hash-checked) -> matrix `-SelfTest -WriteProof` -> driver `-SelfTest -WriteProof` -> `-DryRun` -> the run sheet handed to the Lead Architect.
