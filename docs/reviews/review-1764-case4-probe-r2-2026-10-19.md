# Adversarial review, round 2: the case-4 probe (`ncoprobe.exe`)

Date: 2026-10-19 (local evening, -04:00). Reviewer: the round-1 reviewer, independent of the builder; reports, never repairs.

## Verdict: PASS for live use

No finding blocks a live run. All eight round-1 findings are fixed or reduced:

- **Fixed:** P1-1 (e-mail in records), P1-2 (out-of-bounds classed as denied), P1-3 (a throw recorded as success), P1-4 (wrong principal
  reaching the engine), P1-6 for every form I used in round 1, and P1-8 (prose).
- **Partly fixed:** P1-5 (the layer is now anchored, the user-condition GUID is not) and P1-7 (the stop line misses one case).

Each new lock fails when its fix is reverted (mutants MB8 to MB11).

I recommend two one-place changes before the ceremony, because each protects the Lead Architect's time at the keyboard:

- **P2-1:** a filter that was added but not deleted, where both read-backs are denied, still ends with exit 0 and no stop line.
- **P2-2:** the run sheet tells him to stop when a window ends with `wrong_principal`, but an exit-12 window does not end with it.

P2-3 and P2-4 do not block. Two items outside the probe need the lead before later phases: the driver seam (N-1) before `-Collect`, and
round 1's P1-9 (N-2) before the Part 3 sanitisation.

## What was reviewed, at which hash

`<nco>` is `docs/research/containment-evidence-2026-10-05/nep0005-open-questions/nco`. The probe files are committed at `8387e047`
and the worktree copy matches. During the review the driver file showed as deleted in the working tree. That is another agent's
in-flight work, and I did not touch it.

| File | sha256 |
|---|---|
| `<nco>/probe/NcoProbe.cs` (211,498 bytes; raw and LF-normalised identical) | `a32bcc5c795cc7136a58c04269986ef4896e40128adc2140eeca2de34a3e05de` |
| `<nco>/probe/README.md` | `f7d00a54e8b3079956ce0ea254238a8874e18fc8188bddfe73b7d115c8aab521` |
| `<nco>/probe/build-probe.ps1` (unchanged since round 1) | `182d7ca17258adf27c5636d3ebaa969053ea17492361e7fb62d8c3eae9cbf944` |
| `<nco>/probe/run-probe-selftest.ps1` (unchanged since round 1) | `d1c10b4201b6017f0f9049dfd4d19e5cdbee40064f3068183ae4b73ad1779b3b` |

My build of this source, with `build-probe.ps1 -BuildDir <scratch>\build2`, produced the shipped exe
`49ab164a8eff62684ca32ddcc843d238a9c228dd41a4babc5fc07eb85d54056c` and the toggle exe
`c1c938fb7799d2e931d17da2a40142f624be1bedb03b0104a0fa668d0ddfd511`.

## Round-1 findings, re-verified with the input that demonstrated each

| Round 1 | Status | Evidence at `a32bcc5c` |
|---|---|---|
| P1-1 e-mail in S and A records | **FIXED** | Details in the first list below. |
| P1-2 0x80320028 classed `denied` | **FIXED** | Harness H10: `ClassifyAdd`/`ClassifyDelete(0x80320028)` give `other`; `IsDenied` is true only for 0x5 and 0x80070005. Harness H3, a full fake sequence with that add status, gives `0x80320028/other`, exit 0. Mutant MB11 (the code put back in the denied set) fails three checks. The SPEC and README amendments are corrected. `halfset.rs:86` still carries the mislabel; the SPEC now says so. |
| P1-3 a throw recorded as `0x00000000 succeeded` | **FIXED** | Details in the second list below. |
| P1-4 no principal check before the engine | **FIXED** | Details in the third list below. |
| P1-5 constant locks compare the file with itself | **PARTLY FIXED** | My round-1 mutant MB4 (IPv4 connect layer GUID replaced by the IPv6 one) now fails `selftest` (2 checks) and `selftest-process` (5 checks). The same class remains for the user-condition GUID: see P2-4. |
| P1-6 scans miss ordinary evasions | **FIXED for every round-1 form** | All seven round-1 forms are now found by the probe's own `RunScans`: plain and `Expand` environment reads, `#elif`, a spaced second add, an add split across a line break, `System .Net`, and a tracker reference glued to a letter. `#undef`, `#region` and an aliased `using` are also found. Three further ordinary forms pass: see P2-3. |
| P1-7 left-behind filter collides with the next run | **PARTLY FIXED** | The stop line prints on exit 8 and on exit 11 after the engine was opened (harness H4, H5), and the run sheet gained a "Stop lines" section. One branch is uncovered: see P2-1. |
| P1-8 prose | **FIXED** | `NcoProbe.cs:196-197` now says the shipped build reads none of the toggle variables and names two of them in `ProcessTest`. A folder given as `--live` is refused with "the proof path is a folder, not a regular file" (P02, and P28 for a junction). |

**P1-1 evidence:**
- `identity` on the operator's token, through `run-limited.ps1`: 16 groups, 14 named and 2 withheld (families `S-1-11-96` and `S-1-5-5`).
  The cloud-account group is not named.
- The `user` object holds only `sid`, `attributes` and `error`. `expected_account` holds no `domain`.
- The whole output has no `@`, no `MicrosoftAccount` and no host name. The account name appears only in `probe_exe_path` and
  `command_line`, because my test exe lived under the profile's temp folder; the live exe is under ProgramData.
- I ran the scrub in directory mode on copies of that output and of four real exit-12 records. Before the rewrite, `--check` flagged all six
  files (SIDs and paths). After it, none had `@`, the account name or the host name, and `--check` exited 0.
- Mutant MB10 (names resolved for every SID) fails `names.account_sids_never_resolved_or_recorded`.

**P1-3 evidence:**
- My own `IWfpCalls` fake, written independently of the builder's, drove `Engine.Sequence` with a throw at each of add, first read-back,
  free, delete, second read-back and close (harness H5).
- Every throw renders as `rc null` and class `other`, never `succeeded`.
- Every later call is still attempted, and close is always attempted.
- `overall` is `incomplete` with exit 11, or `filter_left_behind` with exit 8 when the filter is still seen. The stop rule is true for each.
- `NativeWfpCalls` (`NcoProbe.cs:1485-1491`) is five one-line pass-throughs with the round-1 arguments (the add still passes a NULL
  security descriptor).
- Mutant MB8 (a thrown add recorded as 0 again) fails `sequence.add_throws`.

**P1-4 evidence:**
- On the toggle build, with a barrier trace on every run, F and E as this (non nco-probe) token, and S and A with this SID stood in for
  nco-probe, all ended with exit 12, `error`/`overall` `wrong_principal`, `engine.open.call` null and `add.attempted` false. Each wrote its
  record, and no trace was created.
- The guard table (harness H8) matches the SPEC: F/E pass only as nco-probe; S/A refuse as nco-probe; an unknown nco-probe SID refuses
  F/E and frees S/A.
- Mutant MB9 (the guard disabled) fails both `principal.*` checks.
- `identity` with `NCOPROBE_TOGGLE_EXPECTED_SID` set to this SID gives `is_expected_account` false on the shipped exe and true on the
  toggle exe. That split shows the shipped build ignores the new variable.

## Findings

### P2-1 MEDIUM: a filter that was added and not deleted, behind denied read-backs, ends with exit 0 and no stop line

- **Where:** `NcoProbe.cs`, `Outcome.Overall` and `Outcome.NeedsStop`. The stop line is tied to exit 8 (the delete read-back sees the
  filter) or to exit 11 after the engine was opened. Neither covers a complete sequence whose add returned 0, whose delete did not return
  0, and whose read-backs returned a status other than 0 or `FWP_E_FILTER_NOT_FOUND`.
- **Concrete failure:** this is the experiment's most interesting outcome: the delegated account can add, but cannot delete or read its own
  filter. That run records `overall ok`, exit 0, `residue unknown` and no `operator_action`, so the operator launches the next run. The
  persistent filter is still there, so every later add with the fixed key returns `FWP_E_ALREADY_EXISTS`, classed `other`. That covers the
  next F runs and also the E runs, whose answer is the expected success. Those measurements are lost and need a second ceremony. Safety
  is unaffected, because the filter matches only the stale SID.
- **Reproduced on a fake** (my harness, driving the probe's own `Engine.Sequence`):

```
H12 added, delete denied, reads denied  calls=add,get,delete,get,close  add=0x00000000/succeeded get1="unreadable" del=0x00000005/denied
    get2="unreadable" closed=true overall=ok exit=0 stop=False residue=unknown
H13 added, delete other, reads denied   ... add=0x00000000/succeeded ... del=0x80320035/other ... overall=ok exit=0 stop=False residue=unknown
```

- **Whether the real engine produces this combination is a hypothesis.** Amendment 5 anticipated denied read-backs.
- **Direction (author's call):** also stop when the add returned 0 (or threw) and the delete did not return 0, unless the delete read-back
  is `false`.

### P2-2 LOW: exit 12 prints no stop line, but the run sheet tells the operator to stop on a window that "ends with" `wrong_principal`

- **Where:** `RUN_SHEET.md:123-124`. Exit 12 calls `WriteAndFinish(..., null)`, so no stop line prints; the README states this correctly.
- **Concrete failure:** the last 12 lines of the exit-12 window I captured (W1) are the tail of `exit`, `operator_action`, `clock_end` and
  `record_write`. `wrong_principal` sits on lines 4 and 406 of a 420-line record, 14 lines from the end. With `--wait`, the key prompt
  follows those lines. A mis-elevated E (the run sheet's own example) can be repeated three times before anyone notices. Nothing reaches
  the engine, so the cost is ceremony time.
- **Reproduced:** W1, quoted in the next list.
- **Direction:** print a stop line on exit 12 too, or change the run sheet's wording to something the window shows.

### P2-3 LOW: three ordinary forms still pass the source scans, and two README sentences claim more than the scans test

The README now names its limits (an identifier Unicode escape, reflection, a call through a delegate); I confirmed the first passes, as
disclosed. These three are not in that list:

```
N1 ProcessStartInfo psi = Process.GetCurrentProcess().StartInfo; string n1 = psi.EnvironmentVariables["NCOPROBE_X"];  -> MISSED by every scan
N2 var n2 = new System.Diagnostics.ProcessStartInfo("cmd.exe");                                                      -> MISSED by every scan
N3 var n3 = new Process(); n3.StartInfo = n2; n3.Start();                                                            -> MISSED by every scan
```

- **The README's environment claim overstates the scan.** It says the toggle-branch scan "allows exactly two accesses",
  `Engine.Trace` and `ProcessTest.RunChild` (README line 162). The exemption matches any variable named `psi`, anywhere (N1).
- **The process-start claim is evaded by ordinary forms.** "One start-info construction and one process start" is bypassed by a fully
  qualified type name (N2) and an instance `.Start()` (N3).
- **Why LOW:** the genuine snapshot has no finding in any scan, and the scans are tripwires against accident. Only reading the code backs
  the "only processes the probe starts" statement.

### P2-4 LOW: the user-condition GUID is still pinned only by the file itself

- **Where:** the fix anchors the layer GUID from parts (`layer.is_the_ipv4_ale_connect_layer`, `layer.no_ipv6_layer_in_the_add_path`, scan
  `ipv6_layer`). The condition GUID, action, weight and flags keep the round-1 self-comparison.
- **Reproduced (MB5):** both occurrences of the `ALE_USER_ID` GUID were replaced with the `ALE_APP_ID` GUID `d78e1e87-...` from
  `fwpmu.h:1865`, with one global replace, as MB4 did. The result passes `selftest` (80/0) and `selftest-process` (118/0).
- **The values are correct today.** The condition GUID still matches the SDK, as verified in round 1.
- **Direction:** anchor the condition GUID from parts as the layer now is, or have the driver compare `--version` constants with the matrix
  library.

### Notes for the case-4 lead (outside the four probe files)

- **N-1 driver seam.** The driver committed at `8387e047` has no handling for the new record shapes: `overall` `incomplete` or
  `wrong_principal`, exit 11 or 12, `sequence_complete`, `operator_action`. A `wrong_principal` record in `drop\` would be listed invalid
  by `Test-C4Record` (its `engine.open.rc` is null where the driver expects a status), and `-Collect` would exit 4. That fails closed but
  is noisy. The driver is being revised now; its reviewer should check these shapes.
- **N-2 round 1's P1-9 is still open.** It is reconfirmed on real records: directory-mode scrubbing rewrote the stale SID to
  `S-1-5-21-__MACHINE__-91763` in all four exit-12 records. The Part 3 sanitisation path needs a decision before any record copy is
  committed.
- **N-3 correction to my round-1 report.** That report said every execution was non-elevated through the launcher. The scan-mutant
  harness, an executable compiled from the probe source that calls only the text scans by reflection, ran in my elevated shell without a
  trace variable. It did so in round 1 and again once in round 2 (`s9`). The round-1 file is corrected where the claim was made. Round 2
  re-ran the harness non-elevated with a barrier (`s13`), with identical verdicts.

## Anything the fixes introduced

**Is the real implementation the only path with engine calls, and is the sequence exactly open, add, get, delete, get, close?**

- **Yes on both counts.** Engine calls go only through `NativeWfpCalls`, and the sequence order is open, add, get, delete, get, close.
- **One construction.** `NativeWfpCalls` is built only in `Engine.Drive` (`NcoProbe.cs:1570`).
- **One source of the handle.** The handle can come only from the single `FwpmEngineOpen0` call site in `Engine.Open` (`:1538`). That
  site is in the non-toggle branch, behind `Engine.Trace`. Any other use of `NativeWfpCalls` would hold no engine handle.
- **Only a fake elsewhere.** `Engine.Sequence` is called only from `Drive` and from the self-test's `RunFake`, which passes `FakeWfp` and
  `IntPtr(1)`.
- **The order, observed:**

```
H1 every call returns 0          calls=add,get,free,delete,get,close        overall=ok exit=0
H4 delete denied (left behind)   calls=add,get,free,delete,get,free,close   overall=filter_left_behind exit=8 stop=True
H5 throw at add / get1 / free / delete / get2 / close: add,get,delete,get,close in every case (plus free after a successful read)
```

  Free follows a read-back that returned a filter.

**Other changes checked:**

- **The principal guard.** It sits after the out-dir test and before the engine entry, and it writes a schema-v1 record.
- **The least-data allowlist.** `NameMayBeResolved` admits `S-1-1`, `S-1-2`, `S-1-3`, `S-1-5-32`, `S-1-5-64`, `S-1-5-80`, `S-1-15`,
  `S-1-16` and `S-1-5-<1 to 3 digits>`. Its edges (bare `S-1-5-21`, `S-1-5-32`, service and capability SIDs) resolve to nothing personal.
- **The stop-line wording.** The probe's `K.StopLine` text is identical to the run sheet's.
- **The new toggle variable.** The shipped build ignores it (the `identity` split above).

**Nothing found that the fixes broke.** The round-1 surface still holds:

- The 34 refusal vectors (P01-P34) all end exit 2 or 3, naming the same fields as in round 1.
- The self-hash via a copy and via a symbolic link (V3, V4) reports the real bytes.
- `--version` reports `toggle_build` correctly on both builds.
- The shipped build ignores every toggle variable (P22-P24, V5, W5).
- Mutants MB1 to MB3 are still caught.

## What I ran

Probe code ran non-elevated through `run-limited.ps1`, with the exception named in N-3. `<scratch>` is the reviewer's session scratchpad
under `%TEMP%`, outside any git tree.

1. Builds: `build-probe.ps1 -BuildDir <scratch>\build2`, with and without `-Toggle`. This ran csc only.
2. The author's runner through the launcher: version.shipped PASS, version.toggle PASS, selftest 80/0, selftest-process 118/0,
   engine_open_trace_absent PASS; **checks_run 203 / checks_failed 0**. The runner's own builds were shipped `6fd724be...` and toggle
   `c9fe63ca...`.
3. The process attack on the shipped exe: rows P01-P34, the `--version` rows V1-V5 and the least-data `identity` (I1). This was 40
   children, each with stdin closed and a 20 s timeout. Every fixture carries a wrong exe hash (64 x `a`) or a number.
4. Exit-12 rows W1-W4 on the toggle build, and W5 (the shipped build with every toggle variable set, refused at arming).
5. The scrub on copies of the I1 output, a copy with the two path fields removed, and the four W records: `--check`, the rewrite with a
   scratch log, then `--check` again.
6. A sequence harness: my own `IWfpCalls` fake driving the probe's `Engine.Sequence` (rows H1-H13), plus pure checks of the principal
   table, `NameMayBeResolved` and the classifier.
7. A scan harness: the probe's `ProcessTest.RunScans` by reflection over 14 appended mutants (R1-R7, N1-N7).
8. Behaviour mutants built from copies:
   - MB1, MB2, MB3, MB8, MB9, MB10 and MB11 were run with `selftest` only.
   - MB4 and MB5 were built with the author's `build-probe.ps1` and run with `--version`, `selftest` and `selftest-process`.
9. `identity` on both builds with and without `NCOPROBE_TOGGLE_EXPECTED_SID`.
10. Reading: the full diff `fa96f8e7..8387e047` of the probe, the SPEC, the run sheet and the README, and the committed driver's handling
    of record shapes.

The standing gate and pytest were not run. Nothing here touches them.

## Trace-file verdict, every invocation

Every probe child and harness run under the launcher had `NCOPROBE_ENGINE_OPEN_TRACE` pointing into a folder that does not exist. That
barrier means reaching the engine entry ends in exit 10 before the engine is touched. The STOP rule fired on any exit outside the
expected set.

**Result: no invocation exited 10 or reported `trace_failed`.** No barrier file or folder was created. This was checked after each of
the 45 children, after each mutant and harness run, and at the outer barrier of each of the 8 launcher sessions.

Inside `selftest-process`, the toggle rows write one line to their own writable trace by design. That build has no engine-open call.
The elevated exception is N-3.

No proof that could validate was written, and `--live` was passed only with wrong-hash fixtures or paths that hold no proof.

## What I could not test

- Everything past `FwpmEngineOpen0`, by rule. That covers the real statuses, whether the P2-1 combination occurs, the real read-back
  rights of the delegated account, and a record written after a real engine run.
- The suites under an elevated token, the `nco-probe` secondary logon, the E elevation path and the interactive `--wait` window. The
  W1 tail is the redirected-output equivalent.
- The revised driver, which was mid-rewrite during this review.

## Merge read

- **No blocker.** The fixes are sound, and each carries a lock that fails when the fix is reverted.
- **Fix P2-1 and P2-2 before the ceremony.** Each is one place: the stop predicate, and the exit-12 stop line or the run-sheet wording.
  Neither is a safety issue; both protect the operator's ceremony time.
- **P2-3 and P2-4 can wait for the next touch of the file.**
- **Settle N-1 before `-Collect` and N-2 before Part 3.**

A round 3 needs only rows H12 and H13, the W1 tail and MB5 at the new hash, plus the runner.

## Round 3 (delta): PASS

Date: 2026-10-19, about 23:00 -04:00. Scope: confirm the P2-1 to P2-4 fixes and check for regressions.

### Tested at

`NcoProbe.cs` sha256 `28bc05d583135c446ae5dff073907b42c855e522123ba7106c76ff185a42f794` (222,621 bytes; raw and LF-normalised identical),
committed at `21cb384d`. README `9486ba9b...`. `build-probe.ps1` and `run-probe-selftest.ps1` are unchanged.

My build: shipped `e07e78f15c3139204ae04a570ac44f4c7061f0994c994fc1e6c117a74b699ef2`, toggle `d01f411707347d33db79e5c9f08a2682e3aed7b51408ebd13700e511bc05db3e`.

All execution ran non-elevated through `run-limited.ps1`, with a barrier trace on every invocation. Only builds and fixture creation ran
elevated, and they execute no probe code. This round the scan harness also compiled and ran inside the launcher.

### The four round-2 findings

| Round 2 | Status | Evidence at `28bc05d5` |
|---|---|---|
| P2-1 added, not deleted, unseen: exit 0 | **FIXED** | Harness H12 (add 0, delete denied, reads denied) and H13 (delete `other`) now end `filter_possibly_left_behind`, exit 8, with the STOP line and `residue unknown`. There is no false stop: H7 (add denied, reads denied) still gives `ok` exit 0, and H1/H2/H3 are unchanged. Mutant MB12 (the new predicate reverted) fails `overall.classify` and three `sequence.*_stops` rows. |
| P2-2 exit 12 has no STOP line | **FIXED** | W1 to W4 (toggle build, exit 12) end with stderr `STOP: wrong principal; tell the session before the next run`, and `operator_action` carries the same text, so it now appears in the last 12 lines of the window. Mutant MB13 (exit 12 given no line) fails `stop.lines`. The process row also asserts the last stderr line. |
| P2-3 ordinary scan evasions | **FIXED** | N1, N2 and N3 are now found. Five new ordinary forms are also found: a static `Process.Start(string)` outside `RunChild`, an instance start split across lines, a `psi` read in another method, a `global::`-qualified `new Process()`, and `.StartInfo` through `GetProcesses()`. Only the two README-disclosed limits still pass: a Unicode escape in an identifier and `Process.Start` through a delegate. The genuine snapshot has no finding in any scan. |
| P2-4 user-condition GUID pinned only by the file | **FIXED** | MB5 (both occurrences replaced with `ALE_APP_ID`) now fails `selftest` (`condition.is_ale_user_id`) and `selftest-process` (3 rows). As the README now states, the action, weight and flags are still compared only with literals in the same file; I did not re-raise that. |

### Regression run

- **Runner:** checks_run 215 / checks_failed 0 (selftest 87, selftest-process 123, 5 runner steps).
- **Refusal set:** P01-P34 give the same exits and fields as rounds 1 and 2. V1-V5 report hashes and `toggle_build` correctly. W5 (shipped,
  every toggle variable set) refuses at arming.
- **Least data:** `identity` on the operator's token withholds the cloud-account group name, with no `@`, no `MicrosoftAccount` and no host.
  The account name appears only in the two path fields, because the test exe lived under the profile's temp folder.
- **Override variable:** `identity` with `NCOPROBE_TOGGLE_EXPECTED_SID` set is ignored by the shipped build and honoured by the toggle build.
- **Sequence:** H1-H11 are unchanged. The order is still add, get, delete, get, close, with a free after each read-back that returned a
  filter. No throw renders as `succeeded`.
- **Mutants:** MB1, MB2, MB3, MB4 and MB8-MB11 are all still caught. With the two new reverts (MB12, MB13) and MB5, every mutant in
  the set fails at least one check.
- **Scans:** round-1 forms R1-R7 and round-2 forms N1-N3 and N5-N7 are all found.

**Trace verdict:** no invocation exited 10 or reported `trace_failed`. No barrier file or folder was created. That covers 45 children,
the harness and mutant runs, and 7 launcher sessions. No valid proof was written.

### New findings (LOW, prose only; none affects a run)

- **P3-1 LOW. The SPEC's amendment line and README amendment 5 are now contradicted by the code.** `SPEC.md:111` and probe `README.md:314-315`
  still say an `unreadable` delete read-back gives exit 0 and that exit 8 is reserved for a read-back that sees the filter. The code, and
  README amendment 12, give exit 8 for `filter_possibly_left_behind` when the add returned 0 or threw and the delete did not return 0.
  Amendment 5 now holds only when nothing was added.
- **P3-2 LOW. The run sheet's stop text does not match the new exit-12 line.** `RUN_SHEET.md:123-124` quotes the exit-8 line and the token
  `wrong_principal`. The exit-12 window now ends with `STOP: wrong principal; tell the session before the next run`. Anyone stopping on a
  line that starts with `STOP:` stops correctly; the run sheet could simply say so.

### Notes for the lead (outside the reviewed files)

- **Driver seam.** The working-tree driver (uncommitted, mid-revision) validates `wrong_principal` records but has no case for
  `filter_possibly_left_behind` (exit 8 with an unreadable delete read-back) or `incomplete` (exit 11). As read, `Test-C4Record` would
  expect `ok`/exit 0 for an unreadable read-back and mark such a record invalid. Those are the records that most need the session's
  attention.
- **Stray file.** An untracked `probe/selftest-probe.ps1` (42,787 bytes, mtime 17:17, not present in my round-1 listing) is back in the
  probe folder. It is the runner name endpoint protection quarantined before, and nothing in the reviewed files or the working-tree driver
  references it. It should be removed or moved out of the deploy path before `Convert-ToLive`, so it is neither deployed nor
  re-quarantined.
- **Round 1's P1-9 is unchanged.** Directory-mode scrubbing still rewrites the stale SID to the machine placeholder. It needs settling
  before the Part 3 sanitisation.

### Merge read

**PASS for live use.** P3-1 and P3-2 are wording; fix them with the next touch of the SPEC and run sheet. The driver seam belongs to the
driver's review, and it must be closed before `-Collect` meets an exit-8 or exit-11 record.
