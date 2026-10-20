# Adversarial review, round 2: the case-4 admin driver (`spike-nep5-c4-driver.ps1`)

Date: 2026-10-19/20. Local clock at the start: 23:41 -04:00; at the end: 00:12 -04:00. Reviewer: independent adversarial reviewer (did not write the
code; reports, never repairs).

## Verdict: PASS for live use, with three MEDIUM corrections I recommend landing before the run

Round 1's blocking finding is fixed and verified. A record must now carry the token its condition names, the four round-1 rows are invalid by token
state, and the defined rows still count. Nothing at this hash blocks a live run on safety or on a counted wrong answer under ordinary use.

Three new MEDIUM findings are each a one-place change, and each fires as a wrong or unusable result:

- **D2-1:** the `elevation_refused` note is counted beside an E record that proves Windows did elevate the account.
- **D2-2:** every mode, `-Finish` included, refuses to run without the lock corpus, a data file only the self-test uses. That file holds the forms
  Bitdefender has already quarantined three times.
- **D2-3:** the documented mitigation for the record-tamper residual does not exist. The probe prints no record sha256, and the run sheet never
  asks for one.

D2-4 answers the corpus acceptance criteria. A missing, truncated or key-removed corpus fails closed, and a corpus edit invalidates the proof. But
removing alternatives INSIDE a pattern does not fail the self-test, so that criterion is not met. This does not affect a run made with the reviewed
corpus `404921c9...`. D2-5 to D2-11 do not block.

## What was reviewed, at which hash

`<nco>` is `docs/research/containment-evidence-2026-10-05/nep0005-open-questions/nco`. Every test ran against snapshot 3, a frozen copy taken at
23:41 of the files below in the repository layout. I re-hashed the tree at 00:11: commit `892701dc` (SPEC.md only) had landed, and every file below
was unchanged.

| File | sha256 |
|---|---|
| `<nco>/scripts/spike-nep5-c4-driver.ps1` (305,568 bytes, commit `574712d1`) | `450b1a556694c6eb7fe92e6c680e8a781287a80a8fb9254b1e6cdd16a6b37ec8` |
| `<nco>/scripts/case4-lock-corpus.json` (9,856 bytes) | `404921c922772dbdfdcd5de956a369f8212f550b0502be68d568e875d95694dc` |
| `<nco>/scripts/README.md` | `8938920bc6f5c034ab81c4ca4f5477d1e9bb0567fa2d5c821da7d15ef3e485a2` |
| `<nco>/scripts/run-limited.ps1` | `ddb9e88e40793fe8a780bde07da92330fef8c1489bfd007864a6650236f7c9b1` |
| `<nco>/probe/NcoProbe.cs` | `28bc05d583135c446ae5dff073907b42c855e522123ba7106c76ff185a42f794` |
| `<nco>/RUN_SHEET.md` | `cdff28a994183fe5f9ce1b4f7f15c663ed16253feea1a98d4e22ebff6e8db369` |
| libraries | unchanged since round 1 (`63a80843`, `0193b0fc`, `d4f80e78`, `56b6418d`, wrapped `eee26686`) |

The stale `spike-nep5-nco.ps1` and `spike-nep5-case4.ps1` were ignored as instructed, except for one check under "could not break". Driver line
numbers are at `450b1a55`.

## Round-1 findings, re-verified

| R1 | Status at `450b1a55` | Evidence |
|---|---|---|
| D1-1 token state | **FIXED** (but see D2-1, D2-7) | E type 3, A type 3 with Administrators deny-only, S type 2 with Administrators enabled, and F without S-1-5-32-556 are each `INVALID [by-token-state]`. The four defined rows are `VALID (counted)`. |
| D1-2 tamper | **residual, but the documented mitigation is false** | A consistent edit still counts (`collect code 0; valid 1`); see D2-3. |
| D1-3 PREPARED without a record | **FIXED** | With the prepare-record write failing: `exit 2; PREPARED printed: False; provider+S2 left: 0; public folder left: False`. |
| D1-4 exit 7 before the add | **FIXED** | A token read that throws, and an account lookup that throws, each return 2 with the manual rollback printed and 0 engine opens. |
| D1-5 lifecycle lock | **FIXED for all 13 round-1 forms**; new forms in D2-5 | All 13 plus both controls `found True`, including `"Logon" + "UserW"`. |
| D1-6 seams lock | **FIXED for the 4 round-1 forms** (halfset by path, Remove-Item, CreateDirectory, takeown); residual in D2-6 | |
| D1-7 `n` | **FIXED** | `F: n = 0 (no write verdict: ... listed, not counted: 3)` |
| D1-8 misnamed STOP | **FIXED** | A `.json.bak` operator F success gives `collect code 9`, then `-Finish` exits 9. |
| D1-9 sub-folder | **FIXED** | A record in `drop\sub` gives `-Finish exit 7; public folder kept: True`. |
| D1-10 launch lines | **FIXED** | The self-test compares every printed line with RUN_SHEET.md character for character, and S and A have no `--wait`. Under `-WriteProof` in the live folder the sheet is absent and the comparison is skipped with a printed NOTE. |
| D1-11 prepare selection | **FIXED** | It now picks the later UTC instant (`083000.json`, `CURRENT`). |
| D1-12 README owner claim | **FIXED** | Both observations are recorded. |
| D1-13 checks that cannot fail | **clock order FIXED** (mutant M4 now fails 2 checks); **acl-plan-pure still misses instance members** (D2-9) | |
| D1-14 matrix hash | **FIXED** | The prepare record carries `matrix_sha256` for five live matrix files (`:1432-1435`). |
| D1-15 PartD profile | **FIXED** | Only `nco-probe.TESTPC` left gives `exit 21`. With no prepare record and no live lookup, PartD reads 21 (fail closed). |

## New findings

### D2-1 MEDIUM: the `elevation_refused` note is counted beside an E record that proves Windows elevated the account

- **Where:** `Invoke-C4Collect` `:1578` (`EReachedEngine` = E files with `engine.open.opened` true) and `Get-C4ElevationRefused` `:668`. The self-test
  check at `:2385` and `:2595` asserts this very predicate, so the lock mandates the defect.
- **What is wrong:** "reached the engine" stands in for "Windows elevated the account", and the two disagree in both directions.
- **Failure scenario, false count:** one E attempt is refused at the prompt, and another elevates as `nco-probe` (elevation type 2) but its engine open
  fails or throws. The note is counted as the E result, and `-Collect` exits 0. The table says `E result: elevation_refused` while it lists a record whose
  token is elevated.
- **Failure scenario, false contradiction:** the E probe line is pasted into the unelevated `nco-probe` console (type 3, invalid by token state). The run
  reaches the engine, so a genuine refusal note is reported as contradicted, with exit 4.
- **Cost:** a counted wrong E answer, "the account cannot elevate", or a correct note rejected.
- **Reproduced** with the fakes. Each case below had the note given to `Invoke-C4Collect`:

```
E run ELEVATED as nco-probe (elevation type 2), engine open failed  + note: counted True; collect code 0
E run ELEVATED as nco-probe (elevation type 2), engine open threw   + note: counted True; collect code 0
E line pasted UNELEVATED (type 3, invalid by token), reached engine + note: counted False; collect code 4; invalid kinds: by-token-state
```

- **Incidence:** none banked. It needs mixed E outcomes, which three attempts per condition make possible.

### D2-2 MEDIUM: without the lock corpus every mode exits 2, `-Finish`, `-Collect`, `-Check`, `-DryRun` and `-PartD` included

- **Where:** the top-level load at `:898-899` runs before the argument check and the mode dispatch. README `:256` says "Without a usable corpus every
  mode exits 2."
- **What is wrong:** the corpus feeds only the parser locks, which only `-SelfTest` runs. The removal and collection modes now depend on it, and so does
  `-DryRun`, which the run sheet names as the place the manual rollback is printed.
- **Failure scenario:** the corpus holds every planted lifecycle and seam form: credential cmdlets, `net user x /add`, `Invoke-Expression`, COM objects.
  README `:261` records that Bitdefender quarantined three driver versions carrying exactly these tables on 2026-10-19. If the corpus is quarantined
  after `-Prepare`, every case-4 mode refuses. `drop\` (Modify for `nco-probe` and the operator), S2 and the provider stay until someone restores the
  file or cleans up by hand.
- **Cost:** cleanup and evidence collection stall in the middle of the Lead Architect's session. The matrix's `-Remove` and the library's manual rollback
  still cover the engine.
- **Reproduced** for `-SelfTest`: a snapshot copy without the corpus gives `REFUSED: the lock corpus is missing (...). Nothing was read or changed.`, exit
  2. For the other modes this is by reading only: the load is top-level script code at `:898`, which runs before the entry at `:2756`. I did not run any
  live mode.

### D2-3 MEDIUM: the documented mitigation for the record-tamper residual does not exist

- **Where:** README `:204`: "The probe prints its record in its console, with the record's sha256 on the last line ... The Lead Architect compares the
  two for each run."
- **What is wrong:** `NcoProbe.cs` at `28bc05d5` (`WriteAndFinish`, then `Finish`) prints the record JSON and then the STOP line or
  `ncoprobe: press any key to close`. It prints no record hash. The JSON it prints also carries a `record_write` field added after the file was written,
  so its bytes are not the file's. RUN_SHEET.md never asks the Lead Architect to note anything, and steps 3 and 4 tell him to close each window after
  reading it.
- **Cost:** the residual is presented as mitigated, and a claim built on the README would repeat that. The validator still cannot see a consistent edit.
- **Reproduced:** by reading the probe's console path, and a grep of `NcoProbe.cs` finds no record hash. The driver half (`-Collect` prints each file's
  sha256) is present.

### D2-4 MEDIUM: the corpus lock fails closed on a missing, truncated or key-removed corpus, but not on alternatives removed inside a pattern

- **Where:** `Test-C4LockCorpus` `:863` checks keys, types, compilation and non-empty fixture sets. The fixture floors (38, 6, 14, 4) pin counts, not
  coverage.
- **Loader results**, on temporary copies of the shipped corpus:

```
missing                                   REFUSED: the lock corpus is missing
truncated (first half)                    REFUSED: the lock corpus is not JSON
a pattern key removed                     REFUSED: ... patterns.machine_types: missing or empty
an extra pattern key                      ACCEPTED (ignored)
takeown removed INSIDE machine_commands   ACCEPTED
machine_commands reduced to match nothing ACCEPTED (the self-test's fixtures would then fail)
switch allowlist with two entries         ACCEPTED (the self-test's "allowlist is empty" check would then fail)
machine_types given twice, weak second    ACCEPTED, and the LAST value wins: a reader of the file sees the first
```

- **Mutation analysis.** I removed one top-level alternative at a time and replayed the self-test's own fixture assertions for that lock. The
  alternatives removable with every assertion still true:
  - `machine_commands`: 32 of 42, among them `Start-Process`, `Add-Type`, `Invoke-Expression`, `iex`, `Get-LocalUser`, `Get-Acl`, `Set-Acl`, `whoami`,
    `fsutil` and `reg`;
  - `machine_types`: 5 of 6 (`N5Engine`, `FileSystemAclExtensions`, `Diagnostics.Process`, `Diagnostics.ProcessStartInfo`, `RegistryKey`);
  - `machine_members`: 3 of 3;
  - `fs_commands`: 22 of 24;
  - `fs_members`: 12 of 14;
  - `lifecycle_commands`: 15 of 26;
  - `lifecycle_interpreters`: 6 of 8;
  - `lifecycle_arg_text`: 13 of 16;
  - `lifecycle_types`: only `pscredential` has a fixture.
- **End to end:** I built a snapshot copy whose corpus drops `N5Engine`, both `Diagnostics.Process` types, `Start-Process`, `Invoke-Expression`, `iex`,
  `Get-LocalUser` and `Add-Type`. Its `-SelfTest` gives `all passed (137 checks run, 0 failed)` with 24/24 tags, so `-WriteProof` would bind that corpus.
  With it, a planted `[BlarAI.Nep5.N5Engine]::Open('x')`, a `Start-Process` of `halfset.exe` and a `[Diagnostics.Process]::Start('netsh.exe', ...)` in
  a pure function are each `found False`. The shipped corpus finds all three.
- **What holds:** the proof binds the corpus. Removing `takeown|`, adding one trailing space, or deleting the file each make `Test-C4DriverProof`
  refuse (`case4-lock-corpus.json: changed since the self-test` or `missing now`).
- **Cost:** the lock certifies its whole pattern table while testing about a quarter of it. A corpus edit that weakens an untested alternative passes
  every gate and is then bound as good.

### D2-5 MEDIUM: the lifecycle lock still misses non-cmdlet process and account APIs, while its check text claims "no account"

- **Where:** `Get-C4LifecycleHits` `:993`. The check text at `:2696` says "this driver and run-limited.ps1 create, enable, disable, delete, log on, reset
  or change the membership of no account".
- **Reproduced:** one line planted in `Get-C4PrepPlan`, whole driver scanned:

```
[Diagnostics.Process]::Start('net.exe', 'user nco-probe /delete')            found False
ProcessStartInfo('net.exe', ...) + Process.Start                             found False
[System.DirectoryServices.AccountManagement.UserPrincipal]::FindByIdentity(...).Delete()   found False
GroupPrincipal ... Members.Add(..., 'nco-probe'); Save()                     found False
$v = 'Remove-CimInstance'; ... | & $v                                        found False
& ([scriptblock]::Create('Remove-' + 'LocalUser nco-probe'))                 found False
& $n user nco-probe $s   (path and switch in variables)                      found False
Start-Job { net user nco-probe /delete }                                     found True
Microsoft.PowerShell.LocalAccounts\Remove-LocalUser                          found True
```

- **Why they pass:** the type pattern is anchored to short names, so the full `AccountManagement` names miss. .NET process starts are only
  seam-listed, so inside a `-C4Real` seam neither lock sees them. The last three are dynamic and belong to the honest limit, which the check text should
  state.
- **Incidence:** zero in the driver, run-limited, both probe scripts and `NcoProbe.cs`.

### D2-6 LOW: the seams lock misses instance-member and stream file writes and cmdlet aliases

- **Not found:**
  - `([IO.FileInfo]'...').Delete()` and `([IO.DirectoryInfo]'...').Create()`;
  - `[IO.FileStream]::new(..., 'Create')` and `[IO.StreamWriter]::new(...)`;
  - `ri ... -Recurse` and `rni`, aliases of the listed `Remove-Item` and `Rename-Item`;
  - `wevtutil`.
- **README wording:** it limits the static coverage to `IO.File`, `IO.Directory` and `FileSystemAclExtensions`, which is accurate. "By the cmdlets"
  misses their aliases. Zero incidence.

### D2-7 LOW (premise not verified): the token rule turns "NCO gives a split token" into a validity requirement

- **What the rule requires:** F records elevation type 3 and E records type 2. That holds only if Network Configuration Operators membership makes
  Windows create a filtered/linked token pair.
- **Evidence for the premise:** a secondary source lists the group among the filtered-token groups (Info Support, "UAC and tokens"). Current Microsoft
  pages do not list it, and I could not test it without an account.
- **If the premise is false:** every F record (type 1) is `INVALID [by-token-state]`. That is visible and fails closed, but the core measurement would
  be filed as invalid instead of reported as the finding.
- **Reproduced:** an F record with type 1 and the group present is `INVALID [by-token-state] ... elevation_type.value is 1`.

### D2-8 LOW (hypothesis): the `-ElevationRefused` note invites quoting a dialog that can carry the operator's Microsoft-account e-mail

- **The path:** the parameter text is `'<what Windows showed>'` (`:21`), and the note is recorded verbatim in the collect record. A UAC credential prompt
  that "only offers your own account" (RUN_SHEET step 4) shows that account.
- **The validation:** printable ASCII up to 300 characters, so an e-mail address passes. This is the leak class of probe finding P1-1. The repository
  scrub does not rewrite e-mail addresses.
- **Not reproduced:** I did not raise a UAC prompt.

### D2-9 LOW: `acl-plan-pure` misses instance-member calls

- **Not found:** `([IO.DirectoryInfo]'C:\...\case4-pub').Create()` planted in `Get-C4AclPlan`: `impure found: 0`.
- **Caught:** a static `[IO.Directory]::CreateDirectory` and `[IO.FileInfo]::new` are each found.

### D2-10 LOW: prose

- **Dangling comment:** `:140` "A C# sample for the lifecycle check's own tests" is followed by nothing; the sample moved to the corpus.
- **Corpus refusal message:** it says "Nothing was read or changed", but the four libraries have already been read and dot-sourced.
- **Self-name check text:** "and it is running under that name (spike-nep5-c4-driver-copy.ps1)" reads as a pass on the line that fails.
- **Collect step:** README `:191` says "The RUN_SHEET's collect step needs this form when E was refused", but RUN_SHEET step 6 shows only `-Collect`.

### D2-11 LOW: the proof file name is shared by three driver generations

- **What is shared:** `spike-nep5-nco.ps1`, `spike-nep5-case4.ps1` and `spike-nep5-c4-driver.ps1` all write `case4-selftest-proof.json`.
- **What still holds:** cross-acceptance cannot happen. Each driver binds its own name, and the new one also binds the corpus.
- **What goes wrong:** a stale copy's `-SelfTest -WriteProof` in the live folder would overwrite the new proof, and `-Prepare` would then refuse. That
  fails closed, but it costs a re-run.

## The probe record shapes the driver must accept (`NcoProbe.cs` at `28bc05d5`)

I wrote an independent PowerShell port of the probe's `Engine.Sequence`, `Outcome.Overall/Residue/PossiblyLeftBehind/StopLineFor`,
`EngineOutcome.SequenceComplete` and `AddTo`. The grid covered:

- add status 0, 0x5, 0x80320028 or a throw;
- each read-back 0, not-found, 0x5 or a throw;
- delete status 0, not-found, 0x5 or a throw;
- close 0 or a throw.

That gives 512 opened-engine records: 128 `filter_left_behind`, 96 `filter_possibly_left_behind`, 240 `incomplete` and 48 `ok`. **Test-C4Record
rejected none of them.**

- **`wrong_principal` (exit 12):** the operator's F is invalid by principal and is not a STOP. Its shape matches `AddTo(new EngineOutcome())`: open call
  null, rc null, `sequence_complete` null, the wrong-principal STOP line.
- **Open threw (`incomplete`, exit 11):** valid, with no write verdict.
- **`open_failed` (exit 7):** valid, with no write verdict.

## What I attacked and could not break

- **The token rows:** all 10 of the self-test's wrong-token rows, and my four round-1 rows.
- **The prepare record:** written and read back before PREPARED, with a rollback when either fails.
- **Name guard:** under another name, `-SelfTest` fails its self-name check (`137 checks run, 1 failed`). Live modes and `-WriteProof` refuse with exit
  2; that is by reading, since I ran no live mode.
- **The proof binding of the corpus:** an edit, one appended byte or a deletion each invalidates the proof.
- **The record seam:** the 512-record grid above.
- **The STOP for a misnamed wrong-principal record**, in both `-Collect` and `-Finish`.
- **The sub-folder evidence gate** and the UTC prepare selection.
- **The 13 round-1 lifecycle forms and 4 seam forms.**
- **Standing scans:** clean on the driver, the corpus, run-limited.ps1, the README and the probe source. There is no `#` + 3-5 digits, no fixture prefix,
  no operator name, no machine SID, no e-mail address, and no `runas` outside RUN_SHEET and SPEC.
- **The run sheet's `cd /d C:\ProgramData\BlarAI\case4-pub` before `runas`:** it addresses round 1's working-directory hypothesis. Users have read and
  execute on that folder.

## What I ran (non-elevated through `run-limited.ps1`; nothing against `C:\ProgramData\BlarAI`, any account, group, task or the engine)

- **`-SelfTest` at snapshot 3:** `all passed (137 checks run, 0 failed)`, 24/24 tags.
- **`-SelfTest` on four snapshot copies:**
  - the weakened corpus: 137/0;
  - no corpus: exit 2;
  - the driver renamed: 137 run, 1 failed (self name);
  - mutant M4: 2 failed.
- **Pure functions and the driver's own fakes**, from a function-only copy of the driver cut before its entry block: the record rows,
  elevation_refused, prepare failures, collect and finish cases, PartD, the parser plants, the corpus loader on temporary files, the alternative mutation
  analysis, the 512-record grid, and the corpus proof binding on a temporary folder of stand-in files.
- **Web:**
  - two searches and one fetch of Microsoft Learn's "How User Account Control works", for the NCO filtered-token premise (D2-7);
  - the only direct statement found is Info Support, "UAC and tokens" (https://www.infosupport.com/uac-and-tokens/);
  - Microsoft's "User Account Control settings and configuration" page
    (https://learn.microsoft.com/en-us/windows/security/application-security/application-control/user-account-control/settings-and-configuration)
    does not mention the group.

## What I could not test

- Anything against the real engine, the live folder, `-WriteProof`, the real account seam, or the real UAC prompt for a non-administrator split-token
  account.
- Whether Bitdefender quarantines `case4-lock-corpus.json` (D2-2).
- Whether NCO membership produces a split token on this Windows build (D2-7).

## Merge read

- **Live use: PASS.** No finding blocks the run itself.
- **D2-1, D2-2 and D2-3: land them first.** Each is cheap, and each fires as a wrong E result, a stalled cleanup or a false mitigation claim.
  - D2-1: the contradiction predicate should be "an E record under the account's elevated token".
  - D2-2: the corpus is needed only by `-SelfTest`.
  - D2-3: either the probe prints a hash of the file bytes and the run sheet asks for it, or the README stops claiming the comparison.
- **D2-4:** this does not touch this run, because the reviewed corpus `404921c9...` is the one to deploy. The README's "pattern-removed corpus fails
  closed" is true only per key, and the alternatives without a fixture should get one or be named as untested.
- **D2-5 to D2-11:** LOW or honest-limit items.

## Round 3 (delta): verdict PASS

Date: 2026-10-20, 00:33 to 00:45 -04:00. Everything was tested against snapshot 4, a frozen copy of commit `1ed25f50`. I re-hashed the tree at 00:45
and nothing had changed.

| File | sha256 |
|---|---|
| `<nco>/scripts/spike-nep5-c4-driver.ps1` (320,296 bytes) | `47fcd179b28f15b6deb9d9bfeb41ee501f7e43ee8824364c2bc757707f6c031a` |
| `<nco>/scripts/case4-lock-corpus.json` (schema v2, 46,315 bytes) | `f98304092c2e4ac06feba76cbcc5f9c0bb86fea4f8d0aed7c9a8c4b70b3f97bc` |
| `<nco>/scripts/README.md` | `6dfaf88533dd5cbbd3918a4a2740adf5db7022c1890d012916b1de7498d08747` |
| `<nco>/probe/NcoProbe.cs`, `RUN_SHEET.md`, `run-limited.ps1`, libraries | unchanged since round 2 |

The self-test, run non-elevated through `run-limited.ps1`, reads `all passed (142 checks run, 0 failed)`, with all 24 required tags.

### The D2 findings, re-run with the round-2 inputs

| R2 | Status | Evidence |
|---|---|---|
| D2-1 elevation_refused | **FIXED** | (a) E by the account, type 2, engine open failed, plus the note: `counted False; collect code 4`. (b) The same with the open threw: `counted False`. (c) E by the account, type 3, reached the engine: `counted True` (the record itself is invalid by token state, exit 4). (f) Case (a) with no prepare record: `counted False`, through the fallback to `is_expected_account`. |
| design choice: the operator's mis-elevated E | **sound** | (d) E by the operator, type 2, `wrong_principal`: `counted True`, listed by principal. A token of another principal says nothing about whether Windows elevates the account, so it does not contradict the note. |
| D2-2 corpus coupling | **FIXED** | `Initialize-C4LockCorpus` is called once, under the entry's `if ($SelfTest)`. Every parser-lock function throws if the corpus is not loaded, and no live mode calls one; I checked every call site. `-Prepare` still refuses a missing or changed corpus through the proof binding, which fails closed. The live modes are verified by reading only; I ran none. |
| D2-3 tamper mitigation | **FIXED (prose)** | The README now states the residual as accepted. It says the probe prints the record, not a hash, and that the printed JSON differs from the file. That matches `NcoProbe.cs` `28bc05d5`. |
| D2-4 corpus coverage | **FIXED for removal**; substitution remains (R3-1) | Removing my round-2 weakened set with its plants (`machine_commands` 43 to 38, `machine_types` 6 to 3) gives `FAILED (142 checks run, 2 failed)` on the pinned floors. A template lookahead that excludes `Start-Process` fails the per-alternative check (`its plant is not found`). A duplicate key, including one differing only in case (`"Template"`), is refused: `the lock corpus gives a key twice: $.patterns.machine_types`. |
| D2-5 lifecycle forms | **FIXED** | `[Diagnostics.Process]::Start('net.exe', 'user nco-probe /delete')`, `ProcessStartInfo::new` with `Process::Start`, `AccountManagement.UserPrincipal` by its full name with `.Delete()`, `GroupPrincipal.Members.Add`, and `Process::Start` with the tool in a variable: each `found True`. |
| D2-6 seams forms | **FIXED for the aliases**, the rest an accepted residual | `ri` and `rni`: `found True`. `.Create()` on a `DirectoryInfo`: `found False`, as the README now states. |
| D2-7 F premise | **FIXED** | F of type 1 and type 3 are `VALID`. F of type 2 is invalid by token state. |
| D2-8 note | **FIXED** | A note with `x@example.com` is refused, and so is `MICROSOFTACCOUNT\someone`. Plain notes are accepted, and so are `AzureAD\SomeOne` and a spelled-out "someone at example dot com" (see R3-4). |
| D2-9 acl-plan-pure | **FIXED** | `.Create()` gives `impure found: 1`. `$d.Delete($true)` gives `impure found: 2`. |
| D2-10 prose | **FIXED** | The dangling comment is gone. The self-name text and the corpus refusal message are corrected, and the README's collect-step sentence matches RUN_SHEET. |
| D2-11 proof file name | **documented residual** | |
| Mutants M1, M2, M3, M4, M6 | **all killed** | 2, 2, 3, 2 and 2 checks failed. |

### New in round 3 (all LOW; none blocks)

- **R3-1 LOW: substitution passes the corpus floors.**
  - **Where:** the driver pins the number of alternatives per pattern, not which ones.
  - **What I built:** a corpus whose `Start-Process`, `Add-Type`, `Invoke-Expression`, `iex`, `Get-LocalUser`, `N5Engine` and both `Diagnostics.Process`
    alternatives are each renamed to a decoy (`Start-Processzz` and so on). Each decoy carries a matching plant and finding, so the counts are unchanged.
  - **Result:** `all passed (142 checks run, 0 failed)`, so `-WriteProof` would bind it. With it, a `Start-Process` of `halfset.exe` and a
    `[BlarAI.Nep5.N5Engine]::Open` in a pure function are each `found False`. The shipped corpus finds both.
  - **Why LOW:** removal and accidental drift are now caught. A substitution takes a deliberate, consistent edit of three fields. The reviewed corpus
    `f9830409...` is the one to deploy.
  - **What would close it:** a pinned digest of each pattern's alternatives in the driver, which carries no forms.
- **R3-2 LOW: a token type that cannot be read lets the note count.** An E record by the account whose `elevation_type` could not be read (case (e)),
  and that reached the engine, leaves the note `counted True`. An unknown elevation is treated as "not elevated". The record itself is invalid by token
  state, and collect exits 4.
- **R3-3 LOW: more forms both locks miss.**
  - The lifecycle lock misses a `ProcessStartInfo` built empty and given `FileName` and `Arguments` afterwards.
  - The seams lock misses `mkdir` (a function, not an alias), `md`, and output redirection (`'x' > path`).
  - `acl-plan-pure` also misses the redirection.
  - Zero incidence in the code.
- **R3-4 LOW: the note still accepts some account forms.** It refuses `@` and `MicrosoftAccount` but accepts `AzureAD\Name` and a spelled-out address.
  The session writes the note, so this rests on the session.

### Attacked and could not break

- **Templates without `(?i)`:** dropping it from `machine_commands` and `lifecycle_commands` is accepted by the loader and passes the self-test, but changes
  nothing. Lower-case `start-process` and `new-localuser` are still found, because the locks compare with PowerShell's case-insensitive `-match`.
- **Exclusion by template:** a lookahead in the template fails.
- **Duplicate keys:** case-folded duplicates and a weak second value are both refused.
- **The record shapes and token rows:** unchanged since round 2, and re-verified through the self-test's own checks.

### Merge read, round 3

**PASS for live use.** Every round-2 finding is fixed or documented as an accepted residual. R3-1 to R3-4 are LOW.

Suites run:

- `-SelfTest` at `47fcd179`: 142/0;
- `-SelfTest` on four corpus variants (removal fails, substitution passes, no `(?i)` passes harmlessly, lookahead fails);
- `-SelfTest` on five driver mutants, all killed;
- the fakes, pure functions and text-only plants for every D2 input.

All of it ran non-elevated through `run-limited.ps1`. No live mode was run, and nothing touched `C:\ProgramData\BlarAI`, the engine or any account.
