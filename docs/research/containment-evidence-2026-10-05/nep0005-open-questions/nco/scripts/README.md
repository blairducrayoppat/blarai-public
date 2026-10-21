# Case 4: the admin driver and the reviewer's launcher

Read `../SPEC.md` first: this folder is its Part 2. The driver prepares what the probe (`../probe/`) needs and nothing more. That is our provider and
the test sublayer S2, with no filter, a public folder, and the probe's arming proof. It then collects and validates the probe's records, removes
everything by key and proves the removal. After the Lead Architect's own part C it reads back that the account is gone.

The driver never creates, enables, disables, deletes, logs on, resets the password of, or changes the group membership of any account. Its account
operations are reads only:
- the .NET `NTAccount` name translation, the LSA lookup that `LookupAccountName` also uses;
- `Get-LocalUser`, `Get-LocalGroup` and `Get-LocalGroupMember` by SID;
- `net user <name>` and `net localgroup <group>`.

A parser check in `-SelfTest` holds this for the driver, `run-limited.ps1`, the probe source and the probe's two scripts. The driver compiles no C# of
its own. The library's `Initialize-Nep5Type` is the only compile, and a parser check holds that too.

## Files

| File | Role |
|---|---|
| `spike-nep5-c4-driver.ps1` | The driver (PowerShell 7). Modes: `-SelfTest [-WriteProof]`, `-DryRun`, `-Check`, `-Prepare`, `-Collect`, `-Finish`, `-PartD`. |
| `case4-lock-corpus.json` | The lock corpus: both parser locks' pattern tables and every planted form the self-test proves them with. Data only, read with `ConvertFrom-Json` and never executed. |
| `run-limited.ps1` | The reviewer's non-elevated launcher: `-Command '<text>'` or `-SelfCheck`. |

## Where it runs

The live copy sits beside the matrix in the admin-only live folder (`C:\ProgramData\BlarAI\trackb-live`), and every file it binds sits there too.

| Kind | Files |
|---|---|
| Libraries, loaded through `Get-VerifiedLibBlock` (read once, hashed, evaluated from those bytes) | `spike-lib.ps1`, `spike-persist-lib.ps1`, `spike-task-driver.ps1`, `spike-nep5-lib.ps1` |
| Read for its helpers and C# (never run) | `wfp-coder-egress-spike.ps1` |
| The harness | `halfset.exe`, `halfset.rs`, and the matrix's `harness-live-proof-1763.json` |
| The probe | `ncoprobe.exe`, `NcoProbe.cs`, `BuildInfo.cs` (from the build dir), `build-probe.ps1`, `run-probe-selftest.ps1` |
| This folder | `spike-nep5-c4-driver.ps1`, `case4-lock-corpus.json`, `run-limited.ps1` |

Deployment, run by the author after review:

1. Copy `spike-nep5-c4-driver.ps1`, `case4-lock-corpus.json`, `run-limited.ps1`, `build-probe.ps1` and `run-probe-selftest.ps1` into the live folder with
   `Convert-ToLive.ps1 -Apply`.
2. Convert-ToLive skips `.cs` files and the exe, so copy those raw:
   - `NcoProbe.cs` from `../probe/`;
   - `BuildInfo.cs` and `ncoprobe.exe` from the build dir's `shipped\` (`%USERPROFILE%\rust-bootstrap\ncoprobe-build\shipped\` by default).

   A CRLF copy of the source still matches, because the probe embeds the LF-normalised source hash and the driver accepts the raw or the LF-normalised
   hash.
3. The exe changes on every build, because csc is not deterministic. The driver proof therefore binds the deployed copy's own hash, read from the file
   and from its `--version`. It never uses a pinned value or the throwaway build that `run-probe-selftest.ps1` makes and tests.

Outputs:

- Records go to `<live>\nep5-out\case4\`, which is admin-only and guarded against junctions, symlinks and hard links. They are
  `case4-prepare-<stamp>.json`, `case4-collect-<stamp>.json`, `case4-final-<stamp>.json` and `case4-partd-<stamp>.json`.
- The originals from `drop\` are copied byte for byte into `case4-runs\` there.
- Nothing is stripped at source. Machine SIDs and the host name are scrubbed later, when copies go to `runs/`.

The public folder is `C:\ProgramData\BlarAI\case4-pub\`. It holds `bin\`, with the probe exe and its proof `nco-probe-live.json`, and `drop\`, where
the records land.

## Modes

| Mode | What it does | Exit |
|---|---|---|
| `-SelfTest` | Every mode below, run against the library's fake engine, fake harness and fake export, plus this file's fake file system and fake account reads. Also the parser checks and the proof logic on a temporary folder of stand-in files. | 0 passed, 1 failed |
| `-SelfTest -WriteProof` | Live folder only. The same checks, then the probe's own `run-probe-selftest.ps1` and `ncoprobe.exe --version` (both open no engine), then the matrix's harness proof checked fresh. If everything passed, it writes `case4-selftest-proof.json` and validates it at once. | 0, 1 |
| `-DryRun` | Prints the constants, the ACL plan, whether the driver proof is valid, the probe proof `-Prepare` would write, the steps of every mode, the four probe command lines and the manual rollback. Opens no engine and writes nothing. | 0 |
| `-Check` | Read-only. Runs the direct sweep (S1/S2/S3, provider, export hits) and reads the probe's filter key. Then reads the public folder and its drop files, `net user nco-probe`, the membership of S-1-5-32-556 and the profile folder. | 20 absent, 21 present, 22 unreadable |
| `-Prepare` | See below. | 0, 2, 7, 9 |
| `-Collect [-ElevationRefused '<note>']` | Copies every file in `drop\` into `case4-runs\`, prints and records each file's sha256, and validates every record. Reads S1/S2/S3 for a filter left behind and prints one table per condition. The note is the Lead Architect's, for an E run Windows refused to elevate (see "The E result `elevation_refused`"). | 0; 4 invalid record or a contradicted note; 21 left behind (by the engine read, or by a record saying the filter was or may have been left behind) or engine unreadable; 9 STOP |
| `-Finish [-ElevationRefused '<note>']` | Runs `-Collect` first (with the note, if given), then removes by key: the probe's key on our engine, then `Remove-Nep5All` (every filter in S1/S2/S3, the library's fixed keys, the sublayers, the provider). The direct sweep must then read clean, and the engine security descriptor is compared with `-Prepare`'s. Then the public folder: evidence check, drop ACEs removed and read back, tree deleted. | 0; 7 not verified; 9 STOP |
| `-PartD` | Read-only, after part C: `net user nco-probe`, `LookupAccountName`, the membership of S-1-5-32-556, the default profile folder, the account's `ProfileList` registry entry and the folder it names, and every `nco-probe` or `nco-probe.<suffix>` folder in the profiles folder. | 20 all gone, 21 something remains or unreadable |

Every live mode exits 2 when it is refused before reading or changing anything: not elevated, bad arguments, or the file running under
another name than `spike-nep5-c4-driver.ps1`, the name the driver proof binds. Only the attended `-SelfTest` runs under any name, and its `self name`
check then fails. `-ElevationRefused` is accepted with `-Collect` and `-Finish` only, as one line of printable ASCII of 1 to 300 characters,
and never with `@` or `MicrosoftAccount` in it: the session writes the note, and it never quotes an account.

An unexpected error that escapes a mode exits as follows:

| Mode | Exit | Why |
|---|---|---|
| `-Prepare` | 2 | Its own entry classifies every error inside the steps (below), so only building the context can escape, before anything is added. |
| `-Collect` | 21 | Nothing is claimed about the engine. |
| `-Finish` | 7 | The removal is not verified. |
| `-Check` | 22 | Unreadable. |
| `-PartD` | 21 | Not proven gone. |
| `-DryRun` | 2 | Nothing was read or changed. |

### `-Prepare`, in order

Each refusal adds nothing.

1. The process must be elevated and 64-bit. The scripts folder and the out dir must be admin-only (`Test-AdminOnlyFolder`).
2. The driver proof must be valid. `Test-C4DriverProof` gives a per-process nonce token, the same pattern as `Test-N5Proof`. The add path accepts only
   that token. The sha256 of each live matrix file beside the driver goes into the prepare record: `spike-nep5-matrix.ps1`, `spike-nep5-lib.ps1`,
   `spike-nep5-run-lib.ps1`, `spike-nep5-connect-probe.ps1` and `halfset.exe`. A missing one is printed as a warning and recorded as missing.
3. The stale SID must not resolve (`Get-Nep5SidProblems`). `nco-probe` must resolve to a local user (SID_NAME_USE 1) that is not the operator, not in
   his token and not in Administrators. The last three are a STOP (9).
4. The direct sweep must read clean, the probe's key must read absent and the public folder must be absent. A foreign filter of ours or srt-win's is a
   STOP (9), and nothing is removed.
5. `netsh wfp show security type=engine` is read. If it is unreadable, that is a refusal, because it is the `-Finish` baseline. The filter, sublayer
   and provider containers are also read and recorded.
6. One transaction adds our provider and S2, which names the provider. There is no filter. This runs through `Add-Nep5OurPlan`, behind the library's
   plan gate and this driver's plan gate (provider and S2 only, no filter, no attempt), and is read back.
7. S2's and the provider's security descriptors are read. Which form `netsh` accepts for a GUID is not documented. The braced form is tried first, then
   the bare one, and every attempt (command, exit code, output) is recorded.
8. The public folder is created. Root, `bin\` and `drop\` are each created with their planned owner and DACL, read back and compared:
   - Owner: Administrators, for all three. The rule and its reason are under "Departures from the SPEC" below.
   - root and `bin\`: SYSTEM and Administrators full control, Users read and execute.
   - `drop\`: SYSTEM and Administrators full control, `nco-probe` Modify, the operator Modify (for the S control).
   - Every DACL is protected. The plan is a pure function of the account's SID and how it resolved, the operator's SID and groups, and the members of
     Administrators.
9. The probe exe is copied into `bin\` and must hash like the exe the driver proof verified. The probe proof is written and read back. It carries
   exactly the eleven SPEC fields, and `display_name` is the library marker plus ` case4 nco probe`. Administrators are made owner of both files, and
   then `bin\` must read admin-only for writes.
10. The prepare record is written, then read back. `PREPARED` is printed only when the record is on disk and its `ok`, stamp, account SID and
    probe-proof hash read back as written. The run sheet lines are printed with it.

A record that cannot be written or read back is a failure after the add. Any failure after the add starts rolls back: the public folder, the probe's
key, then S1/S2/S3 and the provider by key, then the direct sweep. The exit is 2 when the read-back is clean. It is 7 when it is not, with the manual
rollback printed. An error before the add, including an exception, exits 2: nothing was added, and the manual rollback is printed for reference only.
Exit 7 means one thing: a rollback that did not read back clean.

### Record validation (`-Collect`)

A record must be the probe's own `run` output (schema `nep5-case4-record-v1`) from a non-toggle build. Each of these must hold:

- The exe hash, the embedded source hash and `proof.sha256` are the ones `-Prepare` placed.
- `cond` is one of F, E, S or A.
- F and E ran as `nco-probe`, with `is_expected_account` true and `user_sid` equal to the SID `-Prepare` resolved. S and A ran as the operator.
- `expected_account.sid` is the SID `-Prepare` resolved.
- `clock_start.utc` and `clock_end.utc` fall inside the prepare-to-now window, with 5 min of slack.
- `stamp_utc` is within 2 s of `clock_start.utc`.
- `record_file_name` is the file's own name, and that name's cond, stamp and pid are the record's. No pid and stamp pair appears twice.
- Every class agrees with its status, using the SPEC's classes. `denied` is 0x5 or 0x80070005 only. 0x80320028 is FWP_E_OUT_OF_BOUNDS, so it is
  `other`.
- The engine section follows the probe's own rules:
  - An open that threw has a null `engine.open.rc`, its text in `engine.open.error`, `overall` `incomplete` and exit 11.
  - An open that returned a status other than 0 is `open_failed`, exit 7.
  - Neither kind of open failure carries an add or delete status.
  - Once the engine is open, a call that threw has a null `rc`, class `other` and its text in `error`.
  - `sequence_complete` is true only when every call after the open returned a status and no error was recorded, the close included.
  - A filter still present after the delete is `filter_left_behind`, exit 8, even when a later call threw.
  - Otherwise, when the add returned 0 or threw, the delete did not return 0, and the delete read-back is not false, the record is
    `filter_possibly_left_behind`, exit 8, with residue `unknown`.
  - Otherwise an incomplete sequence is `incomplete`, exit 11, and a complete one is `ok`, exit 0. `residue` agrees with `delete.present_after`.
  - `operator_action` is the probe's STOP line on exit 8, and on exit 11 once the engine was opened. A `wrong_principal` record carries the probe's
    wrong-principal STOP line instead. Every other record carries null.
  - `-Collect` prints and records every file that carries either STOP line. A record saying the filter was or may have been left behind keeps
    `-Collect` at exit 21, even when the engine reads clean. `-Finish` settles it by removing by key and verifying by enumeration.
- The token is the one the condition names. A record from the right principal under the wrong token is invalid by token state:

  | Cond | `elevation_type.value` | Group |
  |---|---|---|
  | F | 3 (limited) or 1 (no split token) | `nco_group.present` true; `administrators` absent or deny-only |
  | E | 2 (full) or 1 (no split token) | `nco_group.present` true, `enabled` true, `use_for_deny_only` false; `administrators` absent or deny-only |
  | S | 3 (limited) | `administrators.present` true and deny-only |
  | A | 2 (full) | `administrators.present` true and enabled, not deny-only |

  A line typed into the wrong console, such as A's line in the non-elevated one, is therefore listed and never counted. F accepts type 1 as well as 3,
  because "Network Configuration Operators membership gives no split token on this build" would be a measurement, not an invalid record. The row and
  the collect record carry the elevation type, so the table shows which one each F run had. Only type 2 invalidates an F record.
  E accepts type 1 as well as 2, and under either the group must be ENABLED: a batch logon (the Task Scheduler route, RUN_SHEET step 4b) is never
  split, so its token is type 1 with the group enabled, which is the token condition E is about; a deny-only group under either type is the F token
  mislabelled and is invalid by token state (2026-10-20 amendment; the first live run measured elevation type 1, integrity medium-plus, session 0).
  F and E also require Administrators absent or deny-only: a token with Administrators enabled could add the filter as an administrator, which is
  condition A's question, not the group's (review round 4). An F line run through the task route is the batch token (type 1, group enabled): it is a
  valid F record whose row says so, and it is never counted as E (the count keys on `cond`).
- The probe refuses a run made by the wrong principal: F or E not as `nco-probe`, or S or A as `nco-probe`. A record of a run it should have refused,
  but that reached the engine, is invalid.

Invalid records are listed with the reason and never counted. Each carries a kind:

- **by-principal:** the probe refused the principal, or the principal is wrong. This kind wins when a record has more than one problem.
- **by-token-state:** the right principal under the wrong token.
- **misnamed:** a file whose name is not a record name. It is still parsed and checked for the STOP below, so a renamed record cannot hide one.
- **sub-folder:** refused. Its contents are never read or copied, and `-Finish` keeps the public folder while it is there.
- **link:** listed and never followed.
- **unreadable** and **invalid:** everything else.

In the table, `n` counts only valid records with a write verdict: the engine opened and the add returned a status. Engine-open failures and adds
that threw are listed under their condition with their own count and are never counted.

Each file's sha256 is printed, as read from `drop\`, and recorded with its copy. The prepare record the window and hashes come from is the latest one
by the UTC instant it records, not by its local-time file name.

A `wrong_principal` record is the probe's own refusal: `overall` `wrong_principal`, exit 12, the engine never opened, nothing attempted. It carries
the probe's wrong-principal STOP line, which `-Collect` prints. `-Collect` lists it as invalid by principal. It is never counted, and it is not the
driver's STOP finding, because nothing reached the engine. A record that claims
`wrong_principal` for the right account, or that carries an add status, is flagged as well.

The validator requires no resolved account or group name. The probe no longer records names for machine-domain SIDs or the user's name.

An F or E record whose add SUCCEEDED, or whose filter read present after the add, under a principal that is not `nco-probe` is a STOP. This is checked on every parseable file, valid or not,
misnamed or not. `-Finish` still removes everything and then exits 9.

### The E result `elevation_refused`

When Windows refuses to elevate `nco-probe` at condition E, that refusal is itself the E result. The session records it with
`-Collect -ElevationRefused '<note>'`, or the same on `-Finish`, writing the note itself from what the Lead Architect reports. RUN_SHEET step 6
shows the plain `-Collect`, so the session adds this form when E was refused.

The note is judged on the token. It is counted as the E result only when no E file in `drop\`, valid or not, shows the token E is about: the
account's elevated token (elevation type 2), or an unsplit token (type 1) with `S-1-5-32-556` enabled (`Test-C4ETokenShown`). What happened after
does not matter: an engine open that failed or threw under that token still proves the token. An E line run in the account's unelevated console (type 3, invalid by token state) does not contradict the note, and
neither does another principal's record. When an E record showing either token exists, the note is listed as contradicted, not counted,
and `-Collect` exits 4. The note, whether it was counted and why are in the collect record.

### Known limit: the record-tamper window

A record sits in `drop\` from the moment the probe writes it until `-Collect` copies it. `drop\` grants Modify to `nco-probe` and to the operator,
because the probe runs as each. Anything running as either could change a record in that window, and the validator cannot tell, because a
consistent edit passes every rule.

What exists against it is partial. `-Collect` prints the sha256 of each file as it read it and records it with the copy in `case4-runs\`, which
fixes the bytes from that moment on. The probe prints its record in its console, so the Lead Architect sees every record as written. It prints the
record, not a hash, and the printed JSON carries a field added after the file was written, so the two cannot be compared byte for byte. A consistent
edit made between the probe's write and `-Collect`'s copy is therefore not detected. This residual is accepted.

## Gates and their controls-off tests

Each gate is a replaceable scriptblock on the context, so `-SelfTest` switches each one off and shows the bad outcome is then reachable:

- the proof gate
- the plan gate
- the clean gate, against a stale S3, which the library's own pre-state read does not cover
- the STOP gate
- the ACL refusals
- the ACL read-back
- the exe binding
- the `bin\` admin-only gate
- the record validator
- the `-Finish` sweep gate
- the ACE-removal read-back
- the evidence gate (no folder is deleted over records that were not copied)
- both locks on writing the driver proof over a stale harness proof
- the seam check
- the lifecycle check

## Seams

Every machine-touching call sits inside a function whose name contains `-C4Real`. That covers the engine, the harness, the export, ACL reads and
writes, account and token reads, `netsh`, `net` and process starts. `New-C4RealCtx` builds the real context exactly once, in the entry's live branch.
The two proof-time seams, the probe's self-test and `--version`, are called only under `if ($WriteProof)`.

The `seams` check proves this with the PowerShell parser. It covers commands by parsed name and by an `.exe` name written in the command text,
member calls, and type uses. Its honest limit: an executable run through a variable is not seen, so every executable here is invoked with its path
written inline. That covers `net.exe`, `netsh.exe`, `ncoprobe.exe` and `pwsh.exe`.

The check also covers:

- `halfset.exe` and `ncoprobe.exe` by path, and `pwsh`, `powershell`, `cmd`, `net`, `net1`, `netsh`, `icacls`, `cacls`, `takeown`, `attrib`,
  `fsutil`, `reg` and `sc` by name;
- registry types, and the ACL members `SetAccessControl`, `GetAccessControl` and `Translate`;
- file creation and deletion, by the cmdlets and by the static writers of `IO.File`, `IO.Directory` and `FileSystemAclExtensions`. These are allowed
  only in a seam, in the self-test (its own temporary folders) and in `Invoke-C4WriteProof` (the proof file).

The seven ACL-plan functions are held pure by a separate check. They may call only each other, the arms' SID check, pipeline cmdlets and static
methods of the in-memory security types. An instance-member call named like a file write, such as `.Create()` on a `DirectoryInfo`, is a finding too.

Accepted residuals of the seams lock: an instance-member or stream file write outside the seams (`([IO.FileInfo]$p).Delete()`,
`[IO.FileStream]::new($p, 'Create')`, `[IO.StreamWriter]::new($p)`) is not seen, because the lock cannot tell the object's type. The common cmdlet
aliases (`ri`, `rni`, `ni`, `rm`, `del` and the rest) and `wevtutil` are covered.

The two proof-time children run through the call operator. There is no hidden-window process start, no encoded command, no literal byte array and no
`Add-Type` anywhere in the driver, because endpoint protection on this machine quarantines scripts on those patterns.

## The lock corpus

Both parser locks take their patterns from `case4-lock-corpus.json`, beside the driver. Every planted form the self-test drives them with lives
there too, so the executed script carries no working example of a forbidden form.

- **Only `-SelfTest` parses it.** The entry loads it under `if ($SelfTest)`, through `ConvertFrom-Json`, and never executes it. Without a usable
  corpus `-SelfTest` exits 2. The live modes never parse it: the driver proof binds its sha256 like every other bound file, so a missing or changed
  corpus refuses `-Prepare` (as any bound file does), while `-DryRun`, `-Check`, `-Collect`, `-Finish` and `-PartD` run without it.
- **Every pattern is a template with one slot and a list of alternatives.** Each alternative carries the one plant it alone catches and the finding that
  proves it. The self-test plants each alternative's form and requires it to be found, and then not found with that alternative removed. The driver pins
  how many alternatives each pattern must have, so a corpus that drops an alternative with its plant fails the self-test too. Dropping an alternative
  and keeping its plant fails the per-alternative check, and dropping both fails the count. This was checked offline on weakened copies, with the
  self-test's own loop, on 2026-10-20.
- **The loader refuses** a key given twice in one object, which `ConvertFrom-Json` would otherwise resolve silently by keeping the last. It also refuses a
  missing pattern, an alternative that does not compile, a pattern with no alternatives, a template without its slot, an alternative without a plant,
  another schema, an empty fixture set, and a switch allowlist that is not a list.

Why a data file: on 2026-10-19 Bitdefender quarantined three versions of the driver that carried these tables and plants in the script itself.
Two quarantine records name the detection `Generic.PWSH.CoinStealer.B.900C832E`, a static signature family for PowerShell scripts. The third record
was cleared when the operator restored the file. Keeping the patterns and plants out of the executed script makes its surface smaller, whatever the
scanner does.

The self-test proves each of those refusals on a modified copy, and checks that no planted lifecycle form appears in the driver's own text.

## The account-lifecycle lock

A parser check over the driver, `run-limited.ps1`, `build-probe.ps1`, `run-probe-selftest.ps1` and the probe's C# source. In PowerShell it finds:

- the account, group and task cmdlets, the credential cmdlets, `Invoke-Expression` and `iex`, and the CIM and WMI writes;
- `net` and `net1` in any form but the two reads, `net user <name>` and `net localgroup <group>`, where the name is a literal or a `[string]`
  parameter. An untyped or array parameter, or a splat, can carry a switch, so each is a finding.
- an interpreter or process start (`cmd`, `powershell`, `pwsh`, `Start-Process`, `Invoke-Command`) whose arguments name `net`, an account or task
  tool, a slash switch, a COM object, a CIM or WMI write, a credential or a profile load;
- any slash switch on any command. This is deny by default, and the allowlist is empty, because none of the checked files passes one. Any tool's
  credential-storing or other-user switch is therefore a finding without being named.
- any COM object, by `New-Object -ComObject` or by `GetTypeFromProgID` or `GetTypeFromCLSID`;
- a .NET process start, `[Diagnostics.Process]::Start`, `[Diagnostics.ProcessStartInfo]::new` or `New-Object` of either, whose arguments name `net`
  or another listed tool;
- a credential, directory or account type by short or fully qualified name, the whole `System.DirectoryServices.AccountManagement` namespace included;
- the dot-sourced libraries' functions that start, run or unregister the credentialed task or mint a password. The self-test computes that set from
  the loaded library texts, holds the driver's list to it, and checks that the driver calls none of them.

In C# it finds the logon, process-as-user and account APIs, and a `DllImport` entry point that is not one plain string. A `//` right after a colon,
as in `WinNT://`, is not taken for a comment.

Its honest limit: a command or type name built at run time, or run through a variable or a script block made from text, is not seen. The self-test's
check text says so.

## The attended self-test

Under `-SelfTest` without `-WriteProof`, a file missing beside the driver is read from the repository layout:

- `spike-lib.ps1`, `spike-persist-lib.ps1` and `spike-task-driver.ps1` from `..\..\..\arm3-persist\scripts\`
- `spike-nep5-lib.ps1` from `..\..\scripts\`
- the wrapped script from `..\..\..\wfp-spike\`
- the probe files from `..\probe\`

The matrix does the same. `-WriteProof` never falls back, and refuses a library loaded from any other folder.

## `run-limited.ps1`

It writes a temporary `.cmd` in a fresh folder under `%TEMP%` and hands it to `explorer.exe`. The running shell opens it with its own medium-integrity
token: no credential, no password, no trust-level switch. It then waits for a done marker, prints the output, deletes the temporaries and exits with
the command's exit code.

Before the command runs, the `.cmd` reads its own token and refuses to run (exit 4) when the High label is present or the Medium label is absent.
That happens, for example, when no shell is running and `explorer.exe` itself starts elevated.

`-SelfCheck` runs `whoami /groups /fo csv`. It asserts `Mandatory Label\Medium Mandatory Level`, no High label, and `BUILTIN\Administrators` as
`Group used for deny only`.

Exit codes:

- 2: bad arguments. The command must be one line of printable ASCII.
- 3: no done marker in time. The temporary folder is kept.
- 4: refused as not limited.
- 1: the self-check failed.

## Departures from the SPEC

1. **Owner Administrators.** The plan sets Administrators as the owner of the three folders, and `-Prepare` makes Administrators the owner of the exe
   and the proof. It then requires `bin\` to read admin-only. Without an explicit owner, a new folder or file is owned by the creating token's default
   owner, and that differs by session:
   - In the builder's sessions it was the user's own SID, elevated and not, under both PowerShell 7 installs.
   - In the reviewer's elevated session it was Administrators.

   A user-SID owner can rewrite the DACL from a non-elevated process, and so could replace the exe that condition A runs elevated. The explicit owner
   makes the result the same whichever default applies. The DACLs themselves are exactly the SPEC's.

   The same default applies to everything the driver writes into the out dir: the records, and the copies `-Collect` makes in `case4-runs\`.
   `Save-C4Record` therefore gives every record (prepare, collect, final, part D) to Administrators as owner through the file seam, and reports a record
   whose owner could not be set as not written; `-Collect` gives the `case4-runs\` folder and every copy in it to Administrators the same way, lists a
   copy whose owner could not be set as not copied (its record is then invalid, exit 4), and its record names the folder's owner. Before this (the
   2026-10-20 live runs), a file owned by the writing token's user SID made the out dir read non-admin-only. In that state `-Prepare` refuses, `-Collect`
   runs with the engine enumeration skipped (exit 21), `-Finish` runs with the harness untrusted and falls back to its own engine, and `-PartD` has no
   admin-only check. The owner was corrected by hand (`icacls /setowner`) between modes that morning; the one instance the records show is the collect
   of 10:28 (banked, exit 21, enumeration skipped). Which file broke that check is unrecorded (no record carries owners): the 09:28 `-Prepare` had passed
   with every first-run record in place, so it was a file written after it, the 09:28 prepare record or the copies that collect wrote. The self-test rows
   tagged `record-owner` and `copy-owner` hold both fixes.
2. **Account checks first.** `-Prepare` resolves and checks `nco-probe` before the sweep and the add, not when the folder is made, so a refusal or
   STOP over the account adds nothing.
3. **Probe runner name.** The probe's runner is `run-probe-selftest.ps1`, renamed from the SPEC's `selftest-probe.ps1` (amendment 7 there).
   `BuildInfo.cs` comes from the build dir (amendment 1). The driver binds both, plus `halfset.rs`, so the harness proof can be checked.
4. **Launch lines.** `-DryRun` and `-Prepare` print the probe lines exactly as `RUN_SHEET.md` has them, with the real paths:
   - F: `cmd /k <probe line> --wait`;
   - E: `<probe line> --wait`, which the elevation request wraps;
   - S and A: `<probe line>`, with no `--wait`.

   The self-test checks that each printed line appears character for character in `RUN_SHEET.md` when the sheet is reachable. The launcher text for F
   and E (Windows' secondary-logon command, and the elevation request for E) lives verbatim in `RUN_SHEET.md`, not in these scripts. Endpoint protection
   on this machine quarantines scripts that combine that command's name with token enumeration.
5. **Account lookup.** The account is looked up through .NET's `NTAccount` translation, and its kind is read with `Get-LocalUser` or `Get-LocalGroup`
   by SID. It is not a compiled `LookupAccountName` call, because the driver compiles nothing. Only a local user (kind 1) may be granted anything.
6. **ACL read-back.** The ACL read-back uses the .NET security object (`Get-PathSecurityObject`), not the `Get-Acl` cmdlet, as the arm 3 libraries do.
   Its SDDL is the same.
7. **The Task Scheduler route for E (2026-10-20).** The elevation prompt of step 4 offers only this machine's administrators to a non-administrator,
   so the account's full token was unreachable by that route (four refusals, 2026-10-19). Step 4b runs the E line without `--wait` as a scheduled
   task created by the Lead Architect in Task Scheduler (run as `nco-probe`, whether logged on or not, highest privileges; the batch-logon right
   granted by hand in Local Security Policy). A batch logon is not split, so the record shows elevation type 1 with the group enabled, and the E rule
   accepts that token. The driver prints the task route beside the E line; the task's action is the printed line without `--wait`. The driver still
   creates, runs and deletes no task and grants no right: those are the Lead Architect's, by hand, like the account. `-PartD` does not read the
   task list or the user-rights policy; after part C the session reads both itself (`Get-ScheduledTask` filtered on the principal, and a `secedit`
   export to a scratch file) and records the result in `runs/AS_RUN.md`.

## What the self-test does not cover

The builder never opened the engine, ran a mutating harness verb, ran a live mode, or wrote under `C:\ProgramData\BlarAI`.

Tested outside the self-test, by hand, on the development box:

- The real file and ACL seam on a throwaway folder under `%TEMP%`: creation with owner and DACL, read-back equality, the owner change, the copy, the
  write-once copy, the capped read, the ACE removal and its propagation to a file, and the tree removal.
- The real account reads.
- `ncoprobe.exe --version` of B1's build, through the driver's proof-time seam.
- B1's `run-probe-selftest.ps1` through the driver's proof-time seam and parser: passed, 163 checks.
- `run-limited.ps1 -SelfCheck` and a command with a pipe and an exit code.

Not tested anywhere:

- **The engine.** Every call against the real engine: `New-Nep5RealBackend`, the add and its read-back, `Remove-Nep5All` and the sweep against real
  objects, real `netsh wfp show filters` exports, and the manual rollback snippet's run.
- **netsh security.** `netsh wfp show security` for real, including which GUID form it accepts and whether its text carries a DACL in the form
  `Test-C4SddlText` expects.
- **The live folder.** `Test-AdminOnlyFolder` on the live folder, the out dir and `bin\`, including the real `C:\ProgramData\BlarAI` ancestors.
- **-WriteProof end to end** in the live folder, and every live mode end to end.
- **Real records.** Records written by a real probe run under each token. The validator was driven with records in the probe's shape, built from its
  source; the real record writer has run only for the toggle build's open-failed records, in B1's tests.
- **The STOP paths against real state.** The wrong-principal STOP and the foreign-filter STOP against real engine state.
- **Untimed children.** The proof-time children, `ncoprobe.exe --version` and `run-probe-selftest.ps1`, run without a timeout. `-WriteProof` is
  attended, and a hang shows at the console.
- **The profile reads of `-PartD`.** The `ProfileList` registry read and the listing of the profiles folder have run only against the self-test's
  fakes.
- **Group-member fallback.** The `Get-LocalGroupMember` fallback path (`net localgroup` names resolved one by one), which runs only when
  `Get-LocalGroupMember` throws.

Accepted residuals from driver review round 2:

- **The record-tamper window** (D2-3), as above.
- **Instance-member and stream file writes** are not seen by the seams lock (D2-6), as above.
- **The proof file name** (D2-11). SPEC.md names it `case4-selftest-proof.json`, and every driver generation writes that name. A stale copy's
  `-SelfTest -WriteProof` in the live folder would overwrite the current proof. `-Prepare` then refuses, because each driver binds its own name and this
  one also binds the corpus. That fails closed and costs a re-run.
