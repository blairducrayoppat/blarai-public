# Adversarial review, round 1: the case-4 admin driver (`spike-nep5-nco.ps1`)

Date: 2026-10-19 (local clock read at the start: 17:44 -04:00). Reviewer: independent adversarial reviewer (did not write the code; reports, never repairs).

## Verdict: FAIL for live use

One finding blocks a live run: **D1-1**. A record is certified valid and counted under its condition without the token the condition names, so the
most ordinary operator slip (the A line typed into the non-elevated console) produces a counted, wrong answer to the exact question the run asks.
D1-3 and D1-4 are cheap, one-place changes whose cost when they fire is a wasted attended session or a false "rollback did not verify"; I recommend
they land in the same fix round. D1-2 is a residual that the claim must state if it is not closed. D1-5 and D1-6 are locks that certify more than they
test; nothing in the current code trips them, so they do not block the run, but their check texts must stop claiming completeness. D1-7 to D1-15 do
not block.

The machine-safety design held under every attack I could make without opening the engine: the plan adds only the provider and S2, the driver proof
binds every file it names, the planned DACLs read back exactly on a real folder, a junction planted in `drop\` by the limited token redirected neither
the ACE removal nor the tree delete, and no engine, harness, export, ACL, account or process call sits outside a `-C4Real` seam at either hash.

## What was reviewed, at which hash

`<nco>` is `docs/research/containment-evidence-2026-10-05/nep0005-open-questions/nco`. The tree moved three times during the review (commit `fa96f8e7`
at 17:44, commit `f12f1b00` at 17:48, then uncommitted edits to the driver, its README, SPEC, RUN_SHEET and the probe source up to 18:06). I froze two
snapshots and ran everything against a snapshot, never against the moving tree.

| File | Snapshot A = commit `f12f1b00` | Snapshot B = working copy at 18:06 (uncommitted) |
|---|---|---|
| `<nco>/scripts/spike-nep5-nco.ps1` | `51e543ee85fe9aa2db94473e99811624f1b7547af086b9a279de25cba3b8edf7` | `eb71fb4e2fac04c4a3f3591d583e0d18b9f2db35cb8acfde88a3c99566010099` |
| `<nco>/scripts/run-limited.ps1` | `ddb9e88e40793fe8a780bde07da92330fef8c1489bfd007864a6650236f7c9b1` | same |
| `<nco>/scripts/README.md` | `eaad9f1fafb62b5e476dabeb354922cbb7072fce65b35d36cb2578862c45a77c` | `f67837e216b0c27749b3c86b9856aaa8ce26dfeee5391cd3d7324ebc34eaf44c` |
| `<nco>/RUN_SHEET.md` | `fac974cf9db705d4577cc12b546cf6da092c107e5fe548dbbc6f122a1de33dda` | `ece1e076f67de59ecb30aff94767e0e0e7b1ad7e49ac2b7707d9823f30df316c` |
| `<nco>/SPEC.md` | `0fb1c9f2665181c7922caf099243b38bde460db63b4266cad2adcef381091520` | `ed3a09adcd868bb72dc9a4cc40c09a76dc3f34b383c9279afe4f6d6187ba97b9` |
| `<nco>/probe/NcoProbe.cs` | `52afc31fbffb61e0080cb0499e78f74b8dd537ea26022a533dafba2c5eea0848` | `52afc31f...` in the snapshot; the tree's later `f44ba37d...` was scanned for lifecycle APIs only |
| libraries (both snapshots) | `spike-lib.ps1` `63a80843...`, `spike-persist-lib.ps1` `0193b0fc...`, `spike-task-driver.ps1` `d4f80e78...`, `spike-nep5-lib.ps1` `56b6418d...`, `wfp-coder-egress-spike.ps1` `eee26686...` | |

Snapshot A is the builder's 17:47 revision: driver 235,390 bytes, README 17,133 bytes, both byte-identical to commit `f12f1b00`. Snapshot B is
the later working copy: driver 240,010 bytes, README 17,737 bytes, last written 18:06. I re-read both from disk at 18:15, and both still match these hashes.
Driver line numbers below are at snapshot B (`eb71fb4e`). Every finding was re-run at snapshot B and still holds there unless the finding says otherwise.

## Findings

### D1-1 BLOCKING: a valid record does not have to carry the token its condition names

- **Where:** `Test-C4Record` (`spike-nep5-nco.ps1:441`) and the -Collect table (`Format-C4Table`, `:604`). `-Prepare` only warns when the account is not in
  Network Configuration Operators (`:1164`).
- **What is wrong:** validity checks the principal (the account for F and E, the operator for S and A) but never the token state the condition is defined
  by: elevation type 3 (filtered) for F and S, 2 (full) for E and A, and S-1-5-32-556 present for F and E.
- **Failure scenario:** the run sheet has the Lead Architect keep two consoles open, one elevated and one not, and type twelve lines. The A line typed
  into the non-elevated console runs as the operator with a filtered token, is VALID, and is counted as an A (administrator control) result with the add
  denied. The E probe line pasted directly into the `nco-probe` console, without the elevation wrapper, is VALID and counted as an elevated result with
  the add denied: the answer to "under which token state" comes out wrong with exit 0. A forgotten group membership (part A) only prints a warning, and
  every F and E record of a plain user is then counted as an NCO result. The probe's new `wrong_principal` refusal (working copy) checks the account
  only, so it does not catch any of these.
- **Cost when it fires:** a counted, wrong research result (claim C27), or a re-run of the Lead Architect's attended session once someone notices the
  elevation column. The table prints the elevation type, but the validity verdict and `n = 3` are what the claim is built from.
- **Reproduced** at both snapshots, with the driver's own `New-C4TestRecord` and `Test-C4Record` (record shape mirrors `NcoProbe.cs` `RunCmd`, checked):

```
E record, elevation type 3 (limited), integrity medium                        -> VALID (counted)
A record, elevation type 3 (limited) = typed in a NON-elevated console        -> VALID (counted)
S record, elevation type 2 (full) = typed in the ELEVATED console             -> VALID (counted)
F record whose token does NOT contain S-1-5-32-556 (account not in the group) -> VALID (counted)
```

- **Incidence:** no live record exists yet. The mistake needs no unusual input: it is one line typed into the wrong one of two open consoles.

### D1-2 MEDIUM: any process of the operator's limited token, and `nco-probe`, can rewrite any record in `drop\` undetectably

- **Where:** the `drop\` plan in `Get-C4AclPlan` (operator Modify and account Modify, container and object inherit); record validation in `Test-C4Record`.
- **What is wrong:** every record, including one an elevated A run writes, inherits both Modify ACEs, and validation checks only that a record is
  self-consistent. Nothing binds the bytes a run wrote to the bytes `-Collect` reads.
- **Failure scenario:** between a run and `-Collect`, any non-elevated process in the operator's session (or the `nco-probe` account) edits an F record from
  `0x80070005 denied` to `0x00000000 succeeded` with matching class, read-back and overall fields. `-Collect` counts it, exit 0.
- **Cost when it fires:** the evidence for the claim rests on nobody touching `drop\` between run and collection. That is an unstated assumption today.
- **Reproduced.** Real folder, throwaway, under the session scratchpad: root, `bin\` and `drop\` created elevated with the driver's own planned SDDL
  (`Get-C4AclPlan`, the operator's real SID, a fabricated account SID) through `[IO.FileSystemAclExtensions]::Create`, as `NewProtectedDir` does; an
  "A record" written by the elevated process; then, through `run-limited.ps1` (Medium integrity, Administrators deny-only):

```
planned drop : O:BAD:P(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)(A;OICI;0x1301bf;;;OPERATOR)(A;OICI;0x1301bf;;;NCO)
A record owner: S-1-5-32-544
A record DACL : D:(A;ID;FA;;;SY)(A;ID;FA;;;BA)(A;ID;0x1301bf;;;OPERATOR)(A;ID;0x1301bf;;;NCO)
running elevated: False
rewrite the elevated A record in drop\ (add.class -> denied)           SUCCEEDED
replace the probe exe in bin\                                          refused (MethodInvocationException)
create a file in bin\                                                  refused (MethodInvocationException)
change drop\ DACL (WRITE_DAC)                                          refused (MethodInvocationException)
```

  Then with the driver's fakes: a consistent edit of a denied F record to succeeded gives `collect code 0; valid 1; row add = 0x00000000 succeeded`.
- **Incidence:** zero banked; the run is attended, so the realistic writer is malware or a mistaken tool in the operator's session.

### D1-3 MEDIUM: `-Prepare` exits 0 and prints PREPARED when the prepare record could not be written

- **Where:** `spike-nep5-nco.ps1:1227-1229` (`Save-C4Record`'s `$null` return is discarded on the success path).
- **What is wrong:** the prepare record is the only thing `-Collect` validates against (exe hash, proof hash, SIDs, clock window). Its absence is printed
  as one red line and then reported as success.
- **Failure scenario:** the out dir write fails (disk full, an endpoint-protection lock on a fresh JSON file). The session hands over the run sheet, the
  Lead Architect makes twelve runs, and `-Collect` lists every record invalid: "no prepare record to validate against". If an older successful prepare
  record from an earlier attempt is in the out dir, `-Collect` validates against that one instead (see D1-11).
- **Cost when it fires:** the Lead Architect's attended session is wasted.
- **Reproduced** with the fakes (`WriteJson` made to throw for `case4-prepare-*`):

```
(1) prepare record write fails: -Prepare exit 0; provider+S2 in place: True; prepare records in the out dir: 0
COULD NOT WRITE the record ...\case4-prepare-20261019-181002.json: ... "stand-in: disk full"
PREPARED: provider and S2 in place (no filter), the public folder made with its planned DACLs, the probe exe and its proof in bin\.
    -Collect would then validate against: ok False (no successful case4-prepare-*.json in ...)
```

### D1-4 MEDIUM: an exception before the add makes `-Prepare` exit 7, "a failure after the add whose rollback did not verify"

- **Where:** the entry's catch, `spike-nep5-nco.ps1:2255`; the steps before the `try` in `Invoke-C4Prepare` (`:1133` onward: the operator-token read, the proof
  check, the account lookup and the member reads).
- **What is wrong:** any of these that throws escapes `Invoke-C4Prepare`, and the entry maps every escaped exception of `-Prepare` to 7. The docstring (`:32`)
  defines 7 as an unverified rollback after the add. The manual rollback is not printed on this path either. `-Collect` likewise maps a throw to 21,
  "a filter is left behind". Neither mapping is listed among the README's departures.
- **Failure scenario:** `Get-LocalUser` fails to load, or the token read throws. Nothing was added, but the session reads "7: the engine may hold our
  objects" and runs a manual rollback and a `-Check` for nothing.
- **Reproduced** with the fakes:

```
operator token read throws               returned [] threw [stand-in: token read failed]; engine opened 0 times; sublayers 0; providers 0
account lookup throws                    returned [] threw [... "stand-in: Get-LocalUser is not recognized"]; engine opened 0 times; sublayers 0; providers 0
line 2255: $c4rc = $(if ($Check) { 22 } elseif ($PartD) { 21 } elseif ($Finish -or $Prepare) { 7 } elseif ($Collect) { 21 } else { 2 })
```

### D1-5 MEDIUM: the `no-account-lifecycle` lock certifies more than it tests

- **Where:** `Get-C4LifecycleHits` (`:800`) with `$script:C4LifecycleCommands` (`:734`); the check text "this driver and run-limited.ps1 create, enable,
  disable, delete, log on, reset or change the membership of no account".
- **What is wrong:** the check matches cmdlet names and a narrow `net` shape. Eleven of thirteen ordinary lifecycle forms pass it unseen. It also never
  scans the four libraries the driver dot-sources, and those put credentialed-task helpers into the driver's own scope: `Unregister-TaskIfPresent`
  (`spike-persist-lib.ps1:608`, wraps `Unregister-ScheduledTask`), `Start-SpikeTaskProved` (`spike-task-driver.ps1:15`, starts the credentialed spike task),
  `New-StrongPassword` (`spike-lib.ps1:77`). The README's "a parser check in `-SelfTest` holds this" therefore overstates the guarantee.
- **Reproduced** at both snapshots: one line planted in `Get-C4PrepPlan`, the whole driver text then given to `Get-C4LifecycleHits -Kind ps`:

```
control: Disable-LocalUser nco-probe                             parses True  found True
control: net user nco-probe /active:no                           parses True  found True
net1 user nco-probe /active:no (net.exe's own worker)            parses True  found False
cmd /c net user nco-probe /delete                                parses True  found False
Start-Process net -ArgumentList 'user nco-probe /delete'         parses True  found False
net user with an array variable (splats to argv)                 parses True  found False
Invoke-Expression 'Remove-LocalUser nco-probe'                   parses True  found False
runas /savecred (stored password)                                parses True  found False
Task Scheduler COM object (credentialed task)                    parses True  found False
Set-CimInstance on Win32_UserAccount                             parses True  found False
library helper: Unregister-TaskIfPresent (dot-sourced)           parses True  found False
library helper: Start-SpikeTaskProved (dot-sourced)              parses True  found False
library helper: New-StrongPassword (dot-sourced)                 parses True  found False
C#: EntryPoint built from two literals ("Logon" + "UserW")                 found False
```

  `cmd`, `Start-Process` and `pwsh` are seam-listed, so these forms are caught by the seams check outside a seam, but inside a `-C4Real` seam the
  lifecycle check is the only lock, and it misses them.
- **Incidence:** zero. The driver, `run-limited.ps1`, both probe scripts and both probe sources (`52afc31f`, `f44ba37d`) have no hit.

### D1-6 MEDIUM: the `seams` lock does not see the harness exe by path, file creation or deletion, and four of its own list entries are unlocked

- **Where:** `$script:C4MachineCommands` (`:730`) and `Get-C4SeamProblems` (`:748`).
- **What is wrong:** three gaps.
  - `& (Join-C4Path $PSScriptRoot 'halfset.exe') delete-sublayer ... --live ...` in a pure function is not found. That is the mutating harness verb
    behind the 2026-10-12 incident class.
  - `Remove-Item -Recurse` and `[IO.Directory]::CreateDirectory` on `C:\ProgramData\BlarAI\case4-pub`, and `takeown`, are not found.
  - Deleting `ncoprobe|pwsh|powershell|cmd` from the list (mutant M5) leaves the whole self-test green, 104/0 at A and 106/0 at B: no planted-call test
    covers those entries.
- **Reproduced:** plants appended to the function body, whole text given to `Get-C4SeamProblems`:

```
control: New-Nep5RealBackend in Get-C4PrepPlan               found True   line 282: New-Nep5RealBackend outside a seam
probe exe --live run, end of Invoke-C4SelfTest               found True   line 2236: ncoprobe outside a seam
matrix -Remove via pwsh child, end of Invoke-C4SelfTest      found True   line 2236: pwsh outside a seam
harness exe by path, end of Get-C4PrepPlan                   found False
Remove-Item -Recurse of the public folder in Get-C4PrepPlan  found False
[IO.Directory]::CreateDirectory of the public folder         found False
takeown on the public folder                                 found False
M5 exit=0 :: case 4 driver self-test: all passed (106 checks run, 0 failed)
```

- **Incidence:** zero. A parser inventory of every command and static IO/Diagnostics call outside the `-C4Real` functions finds only reads, the
  self-test's own temp folder and the `-WriteProof` proof write.

### D1-7 LOW: the per-condition `n` counts runs that carry no write verdict, and the self-test mandates it

- **Where:** `Format-C4Table`, `:610`; the self-test's table check asserts `F: n = 2` for one real row plus one engine-open failure.
- **What is wrong:** the summary line counts engine-open failures, while each such row says "not a write verdict".
- **Reproduced:** three open-failed F rows print `F: n = 3`, and every row reads `add engine open failed 0x80070005 (not a write verdict)`.

### D1-8 LOW: the wrong-principal STOP is skipped for a file whose name is not a record name

- **Where:** `Invoke-C4Collect`, `:1271` (`continue` before the STOP test at `:1273`). The README (`:129`) and the docstring of `Test-C4WrongAccountAdd`
  say the STOP "is checked on every parseable record, valid or not".
- **Reproduced:** an F record under the operator's SID, add succeeded, saved as `case4-F-...-7001.json.bak`: `collect code 4; wrong_account []`, and
  `-Finish` exits 0. The same record under its own name gives 9 and 9.

### D1-9 LOW: the evidence gate ignores sub-folders of `drop\`, so `-Finish` deletes records it never copied

- **Where:** `Get-C4UncopiedEvidence`, `:1316` (`-not $_.IsDir`). The README (`:147`) claims "no folder is deleted over records that were not copied".
  The fake file system cannot represent a sub-folder, so the self-test cannot reach this case.
- **Reproduced** with the real file seam's read methods on a throwaway folder:

```
drop listing (real ListFiles): case4-F-20261019-120000-11.json dir=False link=False; sub dir=True link=False
Get-C4UncopiedEvidence: [] -> EvidenceGate passes: True (the E record in drop\sub was never copied)
```

### D1-10 LOW: the driver's S and A lines do not match RUN_SHEET.md

- **Where:** `Get-C4RunSheetLines`, `:718` (`--wait` on all four), against `RUN_SHEET.md:79` and `:85` (S and A without `--wait`). The driver says "RUN_SHEET.md
  holds each launch line verbatim", and the self-test asserts `--wait` on all four.
- **Reproduced:** the F and E probe parts appear verbatim in the run sheet; the S and A parts do not. Paths, flags, `nco-probe-live.json` and `drop\` otherwise
  match.

### D1-11 LOW: `-Collect` and `-Finish` pick the prepare record by name, and the name is a local-time stamp

- **Where:** `Get-C4LatestPrepare`, `:1038`.
- **Failure scenario:** two successful prepares on one day across a westward timezone change. The Lead Architect changes timezone every few weeks. The
  earlier attempt sorts last and is cited.
- **Reproduced** with the fakes: an earlier attempt at 14:00Z (stamp `100000`) is picked over the current one at 15:30Z (stamp `083000`). Records then fail
  closed on `proof.sha256`, but `-Finish` compares the engine security descriptor with the wrong baseline.

### D1-12 LOW: README departure 1 gives a reason that does not reproduce here

- **Where:** `scripts/README.md:198`: "A folder or file an elevated process creates is otherwise owned by the operator's own user SID ... observed on a
  throwaway folder."
- **Reproduced:** an elevated pwsh 7.6.7 on this machine creates files and folders owned by `S-1-5-32-544`. That covers `[IO.File]::WriteAllText`,
  `New-Item`, `FileSystemAclExtensions.Create` with an owner-less SD, and a child file; the token's default owner is `S-1-5-32-544`. The explicit owner is
  harmless defence in depth, but the stated reason is wrong.

### D1-13 LOW: two checks that cannot fail

- **The clock order check:** mutant M4 deletes the `clock_end.utc: before clock_start.utc` check (`:494`). The self-test stays green at both snapshots (104/0, 106/0).
- **`acl-plan-pure`:** it counts only command calls, so `[void][IO.Directory]::CreateDirectory(...)` planted in `Get-C4AclPlan` gives `0 impure call(s)
  -> PASS (missed)`. A planted `Remove-Item` is caught.

### D1-14 LOW: the run sheet promises a hash the prepare record does not hold

- **Where:** `RUN_SHEET.md:18` and SPEC Part 3 (0): "the sha256 of the live matrix bytes recorded in the prepare record". The driver writes no matrix
  hash anywhere: a grep finds only the harness proof and the matrix proof file name. The matrix's own proof binds those bytes, so the evidence exists
  elsewhere, but the sentence the Lead Architect reads is false.

### D1-15 LOW (hypothesis, not reproduced): `-PartD` derives the profile folder from the name

- **Where:** `New-C4RealAcct.ProfileDir` (`ProfilesDirectory` + name).
- **What is wrong:** a profile created as `nco-probe.<COMPUTERNAME>`, which happens when a `C:\Users\nco-probe` folder already exists from an earlier
  attempt, reads as gone. The `ProfileList\<SID>` entry that part C deletes is never read, although the prepare record holds the SID. Not run: it needs a
  real account.

## Not a defect, recorded for the author

- **Classifier agreement:** at `f12f1b00` the driver and probe `52afc31f` both classed `0x80320028` as `denied`. At the working copy, driver `eb71fb4e`
  and probe `f44ba37d` both class it `other`. A driver from one revision paired with a probe from the other marks every record carrying that status
  invalid. Nothing binds the two classifiers together; a mismatch fails closed, record by record.

## What I attacked and could not break

- **The plan.** `AddSet` and `AddOne` exist only inside the library's `Add-Nep5OurPlan`. The driver's one call site is `Invoke-C4Prepare`, with
  `Get-C4PrepPlan` (`Ctx.Plan` is `$null` live). The driver's own plan gate is the real lock: mutant M3, which removes its filter refusal, fails three
  checks, because the library gate accepts a filter plan.
- **Driver proof binding.** A one-byte edit of each bound file is refused by name. The self-test covers this, and I added the file it does not edit, the
  matrix harness proof: `harness-live-proof-1763.json: changed since the self-test ... re-run -SelfTest -WriteProof`. Hand-made, nonce-less and other-kind
  tokens are refused.
- **The ACL plan on a real folder.** Each planned SDDL reads back equal (owner BA, protected). The limited token cannot write `bin\` or the root, or
  change `drop\`'s DACL. The `-Finish` ACE removal propagates to the records and passes `Test-C4AceRemoval`. A junction `drop\j` to a victim folder, made
  by the limited token with `mklink /J`, did not redirect the propagation: the victim's DACL was unchanged. `Remove-TreeNoFollow` deleted the junction,
  not its target, and the victim survived.
- **Wrong-principal STOP** for a properly named record: `-Collect` 9, `-Finish` 9 after a verified removal. Such a record is never counted.
- **Seams at both hashes:** no engine, harness, export, ACL, account or process call sits outside a `-C4Real` function (parser inventory).
- **The record seam with the probe:** every field the validator and the table read (`clock_start.utc`, `stamp_utc`, `record_file_name`,
  `engine.open.opened`, the add and delete `rc`/`class`/`present_after`, `overall`, `residue`, `exit`, `proof.sha256`, `expected_account.sid`,
  `elevation_type.value/label`, `integrity.label`, `nco_group`) is written under that name and form by the `RunCmd` writer in `NcoProbe.cs`.
- **Standing scans** of the driver, `run-limited.ps1` and the README, plus the probe source and its README: no `#` + 3-5 digits, no `p` fixture prefix, no
  operator name, no S-1-5-21 SID other than the library's fabricated stale domain. No `runas` string appears in the three files; RUN_SHEET and SPEC carry
  it by design.
- **Mutants killed:** M1 (no F/E user_sid check), M2 (operator FullControl on `drop\`), M3 (no filter refusal), M6 (no subcommand check). Survivors are
  M4 and M5, above.

## What I ran (all non-elevated through `run-limited.ps1` unless marked; nothing against `C:\ProgramData\BlarAI`, any account, group, task or the engine)

- `run-limited.ps1 -SelfCheck`: passed, Medium label, Administrators deny-only.
- `spike-nep5-nco.ps1 -SelfTest`, never with `-WriteProof`, run from a snapshot folder:
  - snapshot A: 104 checks, 0 failed, all 24 required tags passed;
  - snapshot B: 106 checks, 0 failed, all 24 tags.
- The same self-test on six mutated copies (M1 to M6) at A, and on M4 and M5 at B.
- Pure functions and the driver's own fakes, by dot-sourcing a copy of the driver cut before its entry block: record validation, Collect and Finish
  against `New-C4TestCtx`, the parser checks with planted lines, the run-sheet lines, the driver proof on a temp folder of stand-in files, the prepare
  exit paths and the prepare-record selection.
- ELEVATED, confined to a throwaway folder under the session scratchpad:
  - the planned public folder built with the driver's own SDDL;
  - the driver's `-Finish` ACE removal (`Assert-AclTargetPlain`, `Get-DirSecurity`, `SetSecurityDescriptorSddlForm`, `Set-DirSecurity`) with a planted
    junction;
  - `Remove-TreeNoFollow`;
  - an owner probe of newly created objects.
- Read-only module discovery of `Get-LocalUser`: it loads natively from the System32 LocalAccounts module.

## What I could not test

- Anything against the real engine, a mutating harness verb, `netsh wfp show security` forms, `Test-AdminOnlyFolder` on the live folder and its real
  ancestors, `-WriteProof`, and every live mode. The real account seam (`Invoke-C4RealLookup`, `Invoke-C4RealMemberSids`) was not run, by the brief's
  rule.
- **Users read-and-execute on `bin\` for the `runas` child:** this could not be run, because no account may be created and `runas` is out of bounds.
  By the DACL, `nco-probe` gets read and execute on the exe and the proof through BUILTIN\Users, and Modify on `drop\`. Traversal of
  `C:\ProgramData\BlarAI` (not read) then relies on the default bypass-traverse privilege.
- **Hypothesis: `runas` working directory.** `runas` started from a console whose current directory is the operator's profile may fail for an account
  that cannot open that directory. Two web searches did not confirm this for `runas` specifically. It would surface at run-sheet steps 3 and 4.
- **The UAC prompt** a non-administrator split-token account gets at step 4 (its own credentials, or administrators only).

## Merge read

- **Block live use on D1-1.** It is the one finding whose ordinary trigger produces a counted wrong answer, and the fix lives in one validator.
- **Land D1-3 and D1-4 in the same round.** Each is a one-place change, and each fires as a wasted or misread attended session.
- **D1-2:** either separate the two writers' folders, or state the residual in the claim.
- **D1-5 and D1-6** do not block a run: there is zero incidence and every seam is verified by inventory. The check texts and the README must still stop
  claiming coverage the predicates do not have, or the predicates must widen. The lifecycle check needs the dot-sourced helpers and the harness exe.
- **D1-7 to D1-15** are LOW: prose, a summary count, a narrow sub-folder path and one hypothesis.

Suites run: the driver `-SelfTest` at `51e543ee` (commit `f12f1b00`) and at `eb71fb4e` (working copy), both from frozen snapshots and non-elevated;
`run-limited.ps1 -SelfCheck` at `ddb9e88e`. The reviewer's scripts and outputs are throwaway files in the session scratchpad, not committed.
