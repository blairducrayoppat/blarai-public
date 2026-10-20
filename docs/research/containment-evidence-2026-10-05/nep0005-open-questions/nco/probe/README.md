# ncoprobe: the case-4 probe

`ncoprobe.exe` answers one question for the token it runs under: can this principal add, and then delete, one Windows
Filtering Platform (WFP) filter in the recorded test sublayer S2? It is Part 1 of `../SPEC.md`, with the amendments listed
at the end of this file. It is one C# file, `NcoProbe.cs`, compiled by the .NET Framework compiler already on the
machine. `run` needs no PowerShell, no `Add-Type`, no writable `%TEMP%` and no loaded profile, so it runs in the minimal
console a secondary logon gives.

## Build

```
pwsh probe/build-probe.ps1            # the shipped exe
pwsh probe/build-probe.ps1 -Toggle    # the guard-toggle exe, used only by the tests
pwsh probe/run-probe-selftest.ps1     # builds both into a temp folder and runs every offline test
```

- Default build dir: `%USERPROFILE%\rust-bootstrap\ncoprobe-build`, with `shipped\` and `toggle\` inside it. The script
  refuses a build dir inside a git tree. `-BuildDir` names another one.
- Compiler: `C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe /platform:x64 /optimize+ /target:exe /warnaserror+`,
  `/noconfig` with `System.dll` and `System.Core.dll` as the only extra references. No NuGet and no SDK install.
- The script reads `NcoProbe.cs` once, writes those bytes as a snapshot beside the exe, generates `BuildInfo.cs` there,
  compiles the snapshot and hashes it again afterwards. Nothing is generated inside the git tree.
- `BuildInfo.SourceSha256` is the sha256 of `NcoProbe.cs` with each CRLF normalised to LF. That is the convention the
  case-4 driver uses for text files, so a checkout's line endings do not change it. The raw-bytes hash is in the build
  record too. `BuildInfo.cs` holds only that hash, so it is byte-identical across rebuilds of the same source.
- Output: one JSON object (the build record) on stdout, also saved beside the exe as `build-record-shipped.json` or
  `build-record-toggle.json`. It carries the exe path, the exe sha256, both source hashes and `toggle_build`.
- This compiler does not build reproducibly, so every build gives a new exe sha256. A probe proof must name the exe that
  is actually deployed.

## Subcommands

`stdout` carries one JSON object for every subcommand. All JSON output is ASCII, with everything else escaped.

| Command | Effect |
|---|---|
| `identity` | Token facts only. Opens no engine. |
| `selftest` | Every pure check against fake inputs: `checks_run`, `checks_failed`, `failures[]`, `engine_opens`. Opens no engine. |
| `selftest-process --exe-dir <dir>` | The process-level rows (see Tests): starts the shipped and toggle exes of the build dir `<dir>` as child processes with refusal vectors only. Same output keys as `selftest`. Opens no engine. |
| `run --cond F\|E\|S\|A --live <proof.json> --out <dir> [--wait]` | The live run: token facts, ONE `FwpmFilterAdd0`, a read-back, ONE `FwpmFilterDeleteByKey0`, a read-back. The record is written to `<dir>\case4-<cond>-<utc yyyyMMdd-HHmmss>-<pid>.json` and printed. `--wait` waits for a key press after printing, unless input is redirected. |
| `--version` | Version, own exe path and sha256, embedded source sha256, `toggle_build`, the schemas and the fixed constants. |

Token facts all come from the process's own primary token. Each read records its own Win32 error, and a failed read never
stops the others. The facts are:
- the user SID, recorded as a SID only, with no name;
- every group SID with its attributes word and the derived flags;
- the integrity SID and label;
- `TokenElevationType` and `TokenElevation`;
- whether `TokenLinkedToken` returns a handle (closed at once);
- the attributes of `S-1-5-32-556` and `S-1-5-32-544` when present;
- the `nco-probe` SID from `LookupAccountName` (no domain) and `is_expected_account`;
- the process id, session id and exact command line;
- the clock in local time with offset and in UTC;
- both hashes.

**Least data.** A group's name is looked up and recorded only when its SID belongs to a well-known family: `S-1-1-*`,
`S-1-2-*`, `S-1-3-*`, `S-1-5-<rid of at most three digits>`, `S-1-5-32-*`, `S-1-5-64-*`, `S-1-5-80-*`, `S-1-15-*` or
`S-1-16-*`. Every other SID keeps `name: null` and `name_withheld: true`, and its name is never looked up. That covers
account SIDs (`S-1-5-21-*`), Microsoft-account SIDs (`S-1-11-*`, whose name is a person's e-mail address), Entra ID SIDs
(`S-1-12-*`) and logon SIDs.

## Exit codes

| Code | Meaning |
|---|---|
| 0 | `run`: the sequence ran and every call returned (whatever the add and delete classes). Other subcommands: ok. |
| 1 | `selftest` or `selftest-process` failed. |
| 2 | Usage: unknown subcommand or flag, missing or repeated value, `--cond` outside F/E/S/A, `--live` on `identity`, `selftest` or `selftest-process`. |
| 3 | `not_armed`: the proof is absent or invalid; `field` names the first failing field (`live`, `json` or a proof field). |
| 4 | `stale_sid_resolves`: the stale SID did not fail with `ERROR_NONE_MAPPED` (1332). |
| 5 | `out_dir_unwritable`: the output dir is missing or refuses a test file create and delete; also a record that could not be written at the end (the record is then printed with `exit_after_write`). |
| 6 | `user_sid_unreadable`. |
| 7 | The engine open returned a failure status (`overall` open_failed, rc verbatim). This is not a write verdict. |
| 8 | The sequence ran and the filter is, or may be, still there. Either the delete read-back still sees it (`filter_left_behind`), or the add returned 0 (or threw), the delete did not return 0, and the delete read-back did not show it gone (`filter_possibly_left_behind`). The admin sweep removes it. Ends with the STOP line. |
| 10 | Pre-engine fault: the trace file cannot be appended, or the x64 layout check failed. The engine was not touched. |
| 11 | Internal error, or `overall` incomplete: a WFP call threw. Ends with the STOP line when the engine had been opened. |
| 12 | `wrong_principal`: the token does not fit the condition (see step 5). The engine was not touched, and the record is written. Ends with `STOP: wrong principal; tell the session before the next run`. |

Refusals 2 to 6, 10 and 12 all happen before the first engine open.

## The run, in order

1. Arguments (exit 2). `run` without `--live` parses, and the arming interlock refuses it (exit 3), so the interlock
   alone owns "no proof".
2. Arming proof (exit 3). It must be a regular file (not a folder, link or device) under 1 MiB, strict UTF-8 JSON
   (duplicate keys refused), with these eleven fields, checked in this order:
   - `schema` is `nep5-case4-probe-proof-v1`.
   - `probe_exe_sha256` is the running exe's own sha256, computed in-file.
   - `probe_cs_sha256` is the embedded source hash.
   - `sublayer`, `provider` and `filter_key` are the recorded GUIDs, each in exact 36-character form (any hex case).
   - `user_sid` is the stale SID.
   - `display_name` is a non-empty string of at most 120 characters with no control characters.
   - `expected_account` is `nco-probe`.
   - `checks_failed` is the JSON integer `0`, literally.
   - `written_utc` is a string, ISO 8601 with a zone, at most 24 h old and at most 5 min ahead.

   Extra keys are allowed and listed in the record. The proof gates intent, not authority: its inputs are public.
3. The stale SID `S-1-5-21-17630000-17630001-17630002-91763` must fail `LookupAccountSid` with 1332 (exit 4).
4. The output dir must exist and accept a create and delete of `case4-writetest-<pid>-<ticks>.tmp` (exit 5).
5. Token facts (exit 6 if the user SID cannot be read), then the x64 layout check (exit 10). Then the principal check
   (exit 12; the record is still written, with `overall` `wrong_principal`):
   - F and E run only when the user SID equals the `nco-probe` SID.
   - S and A never run when it does.
   - An `nco-probe` SID that cannot be looked up makes F and E refuse and leaves S and A free.
6. `FwpmEngineOpen0(null, RPC_C_AUTHN_DEFAULT, null, {flags 0, txnWaitTimeoutInMSec 10000})`, a non-dynamic session.
   A failure status is exit 7 and its record is still written. A throw is exit 11, `overall` incomplete.
7. ONE `FwpmFilterAdd0`, with no explicit transaction. The filter:
   - key `c4a0e001-0000-4d8e-9a31-2b6d4c8e0041` in S2, under the provider key, at `ALE_AUTH_CONNECT_V4`;
   - BLOCK, weight `0x1000` (FWP_UINT64), flags persistent `0x1`;
   - one `ALE_USER_ID` equal condition whose security descriptor names only the stale SID;
   - the display name from the proof.

   Then `FwpmFilterGetByKey0`, giving `add.present_after` true, false or `unreadable`.
8. ONE `FwpmFilterDeleteByKey0`, always, even after a failed or throwing add. Then a second read-back gives
   `delete.present_after`.
9. The engine is closed in every case. The classes:
   - `succeeded` (0);
   - `denied` (0x5 or 0x80070005);
   - `not_found` (delete only, 0x80320003);
   - `other` (everything else, including 0x80320028 FWP_E_OUT_OF_BOUNDS).

   The rc is kept verbatim beside the class. A call that threw has `rc` null, class `other` and the exception text in
   `error`, never 0 or `succeeded`. `sequence_complete` is false and `overall` is `incomplete` (exit 11), unless the
   filter is or may still be present (exit 8 wins). "May still be present" means: the add returned 0 or threw, the delete
   did not return 0, and the delete read-back is not `false`. That is `filter_possibly_left_behind`, with `residue`
   `unknown`.
10. The record is written with `CreateNew`, so it never overwrites. It is printed with `record_write` added. On exit 8,
    and on exit 11 once the engine was opened, `operator_action` carries `STOP: tell the session before the next run`.
    On exit 12 it carries `STOP: wrong principal; tell the session before the next run`. The same line is the last line
    printed, on stderr, after the JSON and after the `--wait` prompt.

The record (`schema` `nep5-case4-record-v1`) has no wrapper object. Its top level carries:
- `cond`, `pid`, `stamp_utc`, `record_file_name`, `probe_exe_sha256`, `probe_cs_sha256`;
- `user_sid`, `is_expected_account` and every token fact;
- `principal` (`accepted`, `detail`), `proof`, `stale_sid` (no name), `filter`;
- `engine` (`open.call`, `open.rc`, `open.opened`, `open.error`, `closed`, `close_rc`, `close_error`);
- `add`, `delete`, `sequence_complete`;
- `overall` (`ok`, `filter_left_behind`, `filter_possibly_left_behind`, `open_failed`, `incomplete` or `wrong_principal`);
- `residue` (`absent`, `present`, `unknown` or `none_added`; the admin sweep is the authority);
- `operator_action` and `exit`.

The only WFP calls are `FwpmEngineOpen0`, `FwpmFilterAdd0`, `FwpmFilterGetByKey0`, `FwpmFilterDeleteByKey0`,
`FwpmFreeMemory0` and `FwpmEngineClose0`. Each has one call site: the open in `Engine.Open`, the rest in
`NativeWfpCalls`. The probe makes no network call and changes no account, group, service or registry value. `run` writes
nothing except its record and the out-dir test file. The only processes the probe starts are the two `ncoprobe.exe`
builds, from `selftest-process`, under its own token.

## Guards and instruments

- **Engine-open trace.** Every engine open passes through `Engine.Trace` first. When `NCOPROBE_ENGINE_OPEN_TRACE` names
  a file, one line is appended before the engine is touched. If the append fails, the probe exits 10 and the engine is
  never touched. `selftest` and `selftest-process` also count engine entries in-process and assert zero.
- **Toggle build.** `build-probe.ps1 -Toggle` compiles with `/define:NCOPROBE_TOGGLE`, and only that build reads these
  variables:
  - `NCOPROBE_TOGGLE_OFF=<guard>[,<guard>]`, with the guards `interlock`, `stale_sid` and `principal`;
  - `NCOPROBE_TOGGLE_STALE_SUBJECT`, which points the stale-SID lookup at a SID that maps;
  - `NCOPROBE_TOGGLE_EXPECTED_SID`, which stands a SID in for the `nco-probe` SID.

  The last two make the stale-SID refusal and both branches of the principal guard reachable without any account
  change. The toggle build's engine entry writes the trace line and returns `toggle_build_never_opens_engine`, because
  the `FwpmEngineOpen0` call is compiled only into the shipped build. `--version` reports `toggle_build: true`.
- **The shipped build reads no toggle variable.** It names two of them only so that `selftest-process` can set them for a
  toggle-build child. Two pieces of evidence. First, the shipped exe refuses identically with them set. Second, the
  `C.scan.toggle_branch` scan, outside the toggle branch, allows only two forms of environment access:
  - the trace-variable read, in the exact form `GetEnvironmentVariable(K.TraceVariable)`;
  - `psi.EnvironmentVariables` on lines inside `ProcessTest.RunChild`.

  `RunChild` is located by its line span. The scan reads text, so it is a tripwire against accident, not a proof.
- **P/Invoke allowlist.** `selftest` reflects over its own assembly and requires its P/Invoke table to equal a fixed
  list. That list is the six WFP calls above, plus token, lookup and SDDL reads from advapi32 and handle and module
  helpers from kernel32.

## Tests

`ncoprobe.exe selftest`: 87 checks.
- **SHA-256.** The standard example vectors (`abc`, the 448-bit message, empty, one million `a`), plus agreement with the
  platform implementation for lengths 0 to 200.
- **The proof.** Each of the eleven fields planted wrong and missing, one at a time, refused with that field named. The
  boundary forms of every field. The valid proof accepted.
- **JSON.** The strict parser and writer.
- **Constants.** The fixed constants compared as text. Two further checks compare against GUIDs built from parts, so a
  text replace of the GUID fails them:
  - the layer equals the IPv4 ALE connect layer, and the filter image carries no IPv6 connect layer;
  - the user condition equals `ALE_USER_ID`, in the constant and in the filter image.

  The action, weight and flags are still compared only with literals in the same file.
- **Layout.** x64 sizes and offsets: `FWPM_FILTER0` 200, `FWPM_FILTER_CONDITION0` 40, `FWPM_SESSION0` 72.
- **Filter image.** The marshalled filter read back field by field.
- **Security descriptor.** The builder's output round-tripped through
  `ConvertSecurityDescriptorToStringSecurityDescriptorW` and `ConvertStringSecurityDescriptorToSecurityDescriptorW`. The
  result is `D:(A;;CC;;;<stale SID>)`, one ACE naming exactly the stale SID, byte-identical.
- **Classifiers.** The rc classifier (0, 0x5 and 0x80070005 denied; 0x80320028, 0x80320003 on an add, 0x80320007 and
  0xdeadbeef other). The overall classifier and the STOP rule.
- **The engine sequence on a fake.** `Engine.Sequence` driven by a fake of the post-open calls, with a fake handle (the
  real engine is never reached). The happy path, a denied add that still deletes, a filter left behind, and a throw at
  the add, the delete (with and without the filter present), the read-back and the close. Each throw is checked for rc
  null, class `other`, the exception in `error`, every later call still made, and exit 11 or 8. The not-deleted-and-unseen
  cases stop with exit 8 and `filter_possibly_left_behind`: an add of 0 or a throw, then a delete denied or `other`,
  with every read-back unreadable. An add and delete of 0, and a denied add with a denied delete, do not stop.
- **STOP lines.** Exit 8, and exit 11 after the open, give the STOP line. Exit 12 gives the wrong-principal STOP line.
  Exits 0, 3, 5 and 7 give none, and neither does exit 11 before the open.
- **Least data.** A Microsoft-account, an Entra ID, an account-domain and a logon SID, each with a lookup that would
  return an e-mail-like name: never looked up, recorded with no name. Twelve well-known SIDs resolved.
- **The principal guard.** F and E only as `nco-probe`; S and A never as `nco-probe`; an unknown `nco-probe` SID.
- **The rest.** The record file name builder, the argument parser, the stale-SID decision, the token flag derivations,
  the out-dir guard against unusable paths, the P/Invoke allowlist, and zero engine entries.

`ncoprobe.exe selftest-process --exe-dir <build dir>`: 123 checks, run by the shipped exe of that build dir.

Engine safety. Every shipped-exe child is held back from the engine by three independent barriers:
1. Every proof is planted wrong in exactly one field. Before the proof is written, `Proof.Validate` must refuse it and
   name that field; otherwise the whole run aborts.
2. `--out` names a folder that does not exist.
3. The trace variable names a file inside a folder that does not exist, so reaching the engine entry would show as
   exit 10, and the file stays absent.

Toggle-exe children get a writable trace file: it stays empty for a refusal and gets exactly one line when the engine
entry is reached. All temporary files live in a fresh folder under the temp path, outside any git tree, and are deleted
at the end.

The rows:
- **Source binding.** Both exes match their build records. The runner is the shipped build. Both source snapshots and the
  embedded hash agree. `--version` on both reports its own hash, `toggle_build` and the constants.
- **Shipped `selftest` and `identity`.** `selftest` passes, and passes again with the toggle variables set. `identity` is
  cross-checked against this process's own token:
  - user SID; every group .NET sees present, enabled and not deny-only;
  - elevation against the Administrators role; integrity; pid; hashes; the `nco-probe` lookup; the membership fields;
  - least data: no user name, no account domain, no name on any withheld group, and no `@` or `MicrosoftAccount`
    anywhere in the output.
- **Shipped refusals.**
  - 19 usage refusals (exit 2).
  - The file-level not-armed refusals: no proof, a missing path, a folder (refused as a folder), non-JSON, invalid UTF-8,
    oversize.
  - Each proof field planted wrong in a proof otherwise matching this exe: schema, exe hash, source hash, the forged proof
    with the right exe hash and the wrong sublayer, provider, filter key, user SID, display name, expected account,
    `checks_failed`, a stale proof and a future proof. Each is exit 3 with that field named.
  - `--wait` with redirected input; the toggle variables ignored; the barrier trace never created.
- **Toggle rows.**
  - Untoggled, the no, forged, stale and future proofs are refused. With `interlock` off, the same vectors reach the
    engine entry: one trace line, exit 7, `toggle_build_never_opens_engine`.
  - The recorded stale SID is unmapped on this machine (1332). The stale-SID guard refuses a SID that maps (exit 4), and
    switched off it reaches the engine entry.
  - The principal guard. F and E as this tester refuse: exit 12, record written, no trace line, and the wrong-principal
    STOP line both as the last stderr line and in `operator_action`. S and A with this tester stood in for `nco-probe`
    refuse the same way. F and E stood in, and A as this tester, reach the engine entry. With `principal` off, F
    reaches it.
  - An output folder that is missing, is a file, or denies file creation gives exit 5, also with `--wait`.
  - An unwritable trace gives exit 10.
  - The thirteen records written are named and shaped as specified: four `wrong_principal` and nine `open_failed`, with
    no user name, domain or e-mail-like text.
  - `selftest` under each of the three toggles exits 1 and names the check that caught it, and passes untoggled.
- **Source scans of the snapshot.** Tokens may be separated by whitespace in every scan.
  - Every preprocessor `#if` is exactly the toggle define; only `#else`, `#endif` and `#pragma` besides. `#elif`,
    `#define` and `#undef` are refused.
  - Each WFP call has exactly one `Native.` call site, and there is no other Fwpm name.
  - The engine open sits in the non-toggle branch and the toggle sentinel in the toggle branch. Outside the toggle
    branch, the only environment access is the two named above. `GetEnvironmentVariable`, `GetEnvironmentVariables`,
    `ExpandEnvironmentVariables` and `EnvironmentVariables` are all covered.
  - Exactly one start-info construction, qualified or not, and exactly one `.Start(` call, counted over the whole
    text. Both sit inside `RunChild`, and the call is `Process.Start`. The start-info type and the `psi` variable appear
    only inside `RunChild`, setting only allowlisted properties. No process object is constructed, and no start-info is
    reached through one.
  - The `using` allowlist; no `Microsoft.Win32`, `System.Net`, `System.Management`, `System.DirectoryServices`,
    `System.ServiceProcess` or registry API.
  - Hygiene: the repository tracker-reference pattern; no operator account name; no account-domain SID other than the
    stale SID; no Microsoft-account or Entra ID SID.
  - No IPv6 ALE connect layer GUID.
- **Scan teeth.** Each scan is run on 22 mutated copies of the snapshot text (never compiled or run) and must find the
  mutation aimed at it. The mutations:
  - the plain, spaced, expand and enumerate forms of an environment read;
  - `#elif`, `#define`, and a spaced `# if` with an extra condition;
  - an engine open outside its branch, a spaced second add, and another WFP call;
  - a start-info property set directly or through a process object;
  - a `psi`-named start-info taken from the current process outside `RunChild`, aimed at both the environment scan and
    the process-start scan;
  - a fully qualified start-info construction;
  - a constructed process with an instance `.Start()`, and an instance `.Start()` alone;
  - a spaced denied namespace and a denied `using`;
  - a tracker reference glued to a word, an account SID, and the IPv6 layer GUID.

`run-probe-selftest.ps1` is the plain runner. It builds both exes into a fresh temp folder, runs `--version` on both and
`selftest` and `selftest-process` on the shipped exe, prints `checks_run / checks_failed` and a final JSON line, and
exits 1 on any failure.

## Not covered by any offline test

Everything that needs the real engine runs only in the live run and is not exercised by the tests above:

- `FwpmEngineOpen0` success and its failure codes.
- The real `FwpmFilterAdd0`, both `FwpmFilterGetByKey0` read-backs, `FwpmFilterDeleteByKey0`, `FwpmFreeMemory0` and
  `FwpmEngineClose0`. Their recording logic is exercised on the fake, not on the engine.
- The classes of real engine statuses, and the persistent filter's behaviour.
- The record written after a real engine run. Record writing is exercised only through the toggle build's records.
- The interactive key press of `--wait`.
- Running under a secondary-logon token with no loaded profile.
- In the shipped exe, the stale-SID, output-dir and principal refusals are reached only through the toggle build. The same
  source compiles both builds, and only the `NCOPROBE_TOGGLE` blocks differ.
- The source scans read text. An evasion beyond the covered forms (a Unicode escape inside an identifier, reflection, a
  call through a delegate) is not seen by them. The P/Invoke allowlist and the process-level rows are the other legs of
  that evidence. The statement that the probe starts only its own two builds rests on reading `RunChild` and its
  callers; the scans only guard against an accidental second start site.

## Amendments to ../SPEC.md Part 1 (accepted by the case-4 lead, 2026-10-19)

1. `BuildInfo.cs` is generated beside the exe in the build dir, not in `probe/`. A deployment takes it from there.
2. Exit codes added:
   - 10, a pre-engine fault (trace file unusable or x64 layout mismatch; the engine is not touched);
   - 11, an internal error or an engine sequence that could not complete because a WFP call threw;
   - 12, `wrong_principal`;
   - 1, `selftest` or `selftest-process` failed.
3. `run` without `--live` exits 3 with `field` `live`, not 2, so the arming interlock alone owns "no proof".
4. The toggle build reads `NCOPROBE_TOGGLE_STALE_SUBJECT` and `NCOPROBE_TOGGLE_EXPECTED_SID`, so the stale-SID refusal
   and both branches of the principal guard are reachable without any account change.
5. A delete read-back that is `unreadable` gives exit 0 with `residue` `unknown`. Exit 8 stays reserved for a read-back
   that still sees the filter.
6. `denied` is 0x5 and 0x80070005 only. An earlier revision of this probe also classed 0x80320028 as denied under the
   label FWP_E_ACCESS_DENIED, following the halfset harness. That label was wrong: 0x80320028 is FWP_E_OUT_OF_BOUNDS
   ("an integer value is outside the allowed range", `winerror.h`), and it is now classed `other`.
7. The process-level rows run inside the probe (`selftest-process`), and `run-probe-selftest.ps1` is a plain runner (the
   spec's `selftest-probe.ps1`, renamed).
8. Names are recorded only for the well-known SID families (Least data, above). The user, the `nco-probe` account's
   domain and the stale SID's mapping carry no name.
9. A WFP call that throws is recorded with `rc` null, class `other` and the exception in `error`. It makes `overall`
   `incomplete` and the exit 11, unless the filter is still present (exit 8).
10. The principal check before the engine (exit 12, record written), at the case-4 lead's decision.
11. Exit 8, and exit 11 once the engine was opened, end the printed output with
    `STOP: tell the session before the next run`.
12. Exit 8 also covers a filter that may be left behind (`filter_possibly_left_behind`). That is when the add returned 0
    or threw, the delete did not return 0, and the delete read-back did not show the filter gone.
13. Exit 12 ends the printed output, and fills `operator_action`, with
    `STOP: wrong principal; tell the session before the next run`.
