# Adversarial review, round 4: the case-4 admin driver E-rule amendment (`2ef3e009`)

Date: 2026-10-20. Local clock at the start: 09:52 -04:00; at the end: 10:02 -04:00. Reviewer: independent adversarial reviewer (did not write the
code; reports, never repairs). Nothing here ran elevated, opened the engine, wrote a proof, or touched `C:\ProgramData\BlarAI\trackb-live`,
any account, task or right. Every execution went through `scripts/run-limited.ps1` (the launcher's own gate confirmed Medium integrity before each
command ran; a refusal would have been exit 4).

## Verdict: PASS WITH CORRECTIONS

The amended E rule does what the amendment says: type 2, or type 1 with `S-1-5-32-556` present, enabled and not deny-only, all three read as
booleans. Every malformed shape I built (missing keys, strings, numbers, null, non-integer elevation values, type 3, type 0/4, an unreadable
group) is invalid by token state. Three of four mutants fail the self-test on the new rows, so the rows have teeth. The driver still carries no
task, right or account verb.

Two MEDIUM corrections, each a one-place change, before the next live step:

- **R4-1** the run sheet now promises a read-only check of the task and the batch-logon right after part C that no code performs; `-PartD`
  reports "all gone" (exit 20) with both still in place.
- **R4-2** the E and F rules accept a record whose token also holds BUILTIN\Administrators enabled: a counted E that answers "an administrator can
  add a filter", not "a member with the group enabled can". The `-Prepare` lock covers prepare time only.

## What was reviewed, at which hash

Worktree `%USERPROFILE%/BlarAI-worktrees/nco-probe`, branch `feat/1764-nco-task-route`, HEAD `2ef3e009c3aebedf999317db64684a91cc9bb5de`
(diff against `main`: 4 files, +96/-18). `<nco>` is `docs/research/containment-evidence-2026-10-05/nep0005-open-questions/nco`. Line numbers
are at this hash.

| File | sha256 (first 16) |
|---|---|
| `<nco>/scripts/spike-nep5-c4-driver.ps1` | `8970EF8C6622617B` |
| `<nco>/scripts/case4-lock-corpus.json` | `F98304092C2E4AC0` (unchanged from round 3) |
| `<nco>/scripts/README.md` | `2235F82C9B3FA930` |
| `<nco>/RUN_SHEET.md` | `6B5325921A79ED21` |
| `<nco>/SPEC.md` | `E080910AC3BAED2D` |
| `<nco>/probe/NcoProbe.cs` | `28BC05D583135C44` (unchanged; the probe PASS hash) |

## Suites run

1. **The shipped driver's `-SelfTest`**, non-elevated, from the worktree (libraries by the repository fallback):

```
pwsh -NoProfile -File .\run-limited.ps1 -TimeoutSec 900 -Command 'pwsh -NoProfile -File <nco>\scripts\spike-nep5-c4-driver.ps1 -SelfTest'
case 4 driver self-test: all passed (144 checks run, 0 failed)
```

2. **Four mutants** of a scratch copy (the whole `scripts/` and `probe/` folders, RUN_SHEET.md and SPEC.md, the four libraries and the wrapped
   script placed beside the driver; the driver keeps its own name so the self-name check holds), each run the same way. Control `m0` = the
   unmutated copy.

| Mutant | Change | Result |
|---|---|---|
| m0 control | none | 144 run, 0 failed |
| m1 | `Test-C4NcoEnabled` returns `$true` | **4 failed**: the 12-row wrong-token check (:2396), the E type-1 row (:2410), the batch-logon collect row (:2702), the required tag `record-validation` |
| m2 | the deny-only clause dropped (`present -and enabled` only) | **0 failed** (see R4-3) |
| m3 | `Test-C4ETokenShown` returns true for any type 1 | **3 failed**: :2410, :2702, the tag |
| m4 | E elevation reverted to `@(2)` (the pre-amendment rule) | **4 failed**: the `$good` row (:2385, count 5), :2410, :2702, the tag |

3. **34 counter-records** through the real `Test-C4Record`, `Test-C4NcoEnabled`, `Test-C4ETokenShown` and `Get-C4RecordRow`, loaded by AST from the
   driver text (pure functions and constants only; harness
   `%LOCALAPPDATA%\Temp\claude\C--__USER__-BlarAI\293654b4-6614-41f4-9660-694afe984b83\scratchpad\r4-records.ps1`, output
   `r4-records-out.txt` beside it). Each record round-trips through JSON as `-Collect` reads it. Results are quoted per finding below.

## Findings

### R4-1 MEDIUM: the run sheet promises a post-part-C check of the task and the right that no code performs

- **Where:** `RUN_SHEET.md` :34-35 (step 4b item 5): "The session checks both read-only after part C (the task list and the exported policy)."
  `Invoke-C4PartD` :1803-1838 reads `net user`, `LookupAccountName`, `net localgroup`, the profile folder, the ProfileList key and the profile
  folders, and nothing else. `SPEC.md` :169-170 (`-PartD`) was not amended. `Get-C4PartDExit` takes six booleans, none about a task or a right.
- **What is wrong:** a cleanup promise with no reader. Exit 20 prints "the account, its membership, its ProfileList entry and every profile folder
  of its name are gone" while the task named `nco-probe` (holding the account's stored credential, under a deleted account's SID) and the
  batch-logon line (an orphaned SID in Local Security Policy) can both remain.
- **Failure scenario:** the Lead Architect deletes the account in part C and skips item 5 of 4b (it is in a different window than part C); `-PartD`
  exits 20; the session reports Part D clean; the task and the right survive the run.
- **Reproduced?** By reading only (I never ran `-PartD`). Grep of the driver for `schtasks|Register-ScheduledTask|ScheduledTask|secedit|ntrights|batch`
  finds only the comments at :634, :683, the check texts at :2410 and :2702, and nothing in `Invoke-C4PartD`. Hypothesis for the runtime path.
- **Note on the fix shape (for the author, not a fix):** the lock corpus bans the `*-ScheduledTask` write cmdlets and `New-ScheduledTask\w*`; a
  read through `schtasks /query` or `Get-ScheduledTask` is not on the lists I grepped, but anything added must be re-checked against the corpus
  and go through a seam. If the check is meant to be the Claude session's by hand, the sheet must say so and name the two commands, and the
  SPEC `-PartD` line must not be read as covering it.
- **Precedent:** D1-14 (a promised matrix hash the driver never wrote) and D1-15 (an unrun Part D hypothesis) were both FIXED as this class.

### R4-2 MEDIUM: an E (or F) record whose token also holds Administrators enabled is valid and counted

- **Where:** `$script:C4TokenState` :624-629 and `Get-C4TokenStateProblems` :631-662: E checks `elevation_type.value` and the NCO group only; F
  checks the elevation type and `nco_group.present` only. Neither reads `administrators`.
- **What is wrong:** the question E answers is the group's effect. A token that also holds BUILTIN\Administrators enabled answers a different
  question, and the count does not exclude it. The row shows it (`admins_group`), but `n` does not.
- **Failure scenario:** the account is in Administrators at run time (added after `-Prepare`, which refuses an admin member at :322, or the
  `-AdminsReadable` false path). Under the task route "highest privileges" then yields a type-2 token with Administrators enabled; under UAC off,
  type 1 with Administrators enabled. Both count as E with add 0x0.
- **Reproduced** (harness, at `8970EF8C`):

```
C24 type 1, group enabled, ADMINISTRATORS present and ENABLED too   VALID   row: et='1 default' nco='0x00000007 enabled' adm='0x0000000F enabled'
C25 type 2, group enabled, ADMINISTRATORS present and ENABLED too   VALID   row: et='2 full'    nco='0x00000007 enabled' adm='0x0000000F enabled'
C34 F with type 1, group enabled, Administrators enabled            VALID   row: et='1 default' nco='0x00000007 enabled' adm='0x0000000F enabled'
```

- **Incidence:** the three live E records as the team lead described them read `administrators absent`, so no live record is affected. I did not
  read the live records (the live folder is out of bounds for this review).
- **Why MEDIUM and not LOW:** S and A are each defined by the Administrators state; E and F are not defined by its absence, and the one existing
  lock (prepare-time membership) is a different moment from the run. A one-line rule (F/E: `administrators.present` false or deny-only) closes it
  and the existing `-Admins 'enabled'` fixture gives the row.

### R4-3 LOW: the deny-only clause of `Test-C4NcoEnabled` is not tested OFF

- **Where:** `Test-C4NcoEnabled` :673-679; the fixtures `-NcoDenyOnly` :2199 set `enabled=false` AND `use_for_deny_only=true` together.
- **What is wrong:** every self-test row that claims "a deny-only group is invalid" is rejected by the `enabled` clause alone. Mutant m2 (the
  deny-only clause removed) passes 144/144. The only record the clause rejects on its own is attributes 0x14 (enabled AND deny-only), which Windows
  never produces.
- **Reproduced:** `r4-m2.txt`: `case 4 driver self-test: all passed (144 checks run, 0 failed)`. Harness against the m2 driver:
  `C10 type 1, enabled TRUE and deny-only TRUE (0x14) VALID` (invalid at the shipped driver).
- **Cost:** none for a probe-written record (the probe derives both booleans from one `uint`, `GroupFlags.From` NcoProbe.cs :1046-1058). The cost is
  the claim: SPEC :195 and README :163 name the deny-only rule as the control, and security_by_design principle 12 wants each clause shown to
  fail off. Either drop the redundant clause or add the 0x14 row.

### R4-4 LOW: the validator trusts the derived booleans and never cross-checks `attributes` or `nco_group.sid`

- **Where:** `Test-C4NcoEnabled` :673 reads `present`, `enabled`, `use_for_deny_only`; nothing reads `nco_group.attributes` or `nco_group.sid`.
- **Reproduced** (harness):

```
C7  type 1, enabled true + deny-only false but attributes 0x00000010   VALID   row: nco='0x00000010 enabled'
C8  type 1, enabled true + deny-only false but attributes 0x00000000   VALID   row: nco='0x00000000 enabled'
C9  type 1, enabled true + deny-only false, attributes KEY MISSING     VALID   row: nco='enabled'
C29 type 1, group enabled, nco_group.sid is S-1-5-32-544               VALID
C30 type 1, group enabled, nco_group.sid KEY MISSING                   VALID
```

- **Reachability:** only by a hand-edited record (the D1-2 residual, REJECTED with reasons). From the probe the three fields and the SID come
  from one entry (`GroupEntry` :1150-1153, `Membership` :1165-1170). The row prints the contradiction ("0x00000010 enabled"), so a reader sees it;
  the count does not.

### R4-5 LOW: prose that outlived the code, in human-facing closing text

- `Get-C4ElevationRefused` :700: the reason recorded in the collect record for a type-1 contradiction reads "E record(s) show the account's
  **elevated** token"; a batch record is type 1 "default", not elevated. This is the sentence the session quotes when the note is rejected.
- `Invoke-C4Collect` :1711: the collect record field `e_elevated_as_account` now lists type-1 records.
- README :202: "When an E record under the account's elevated token exists, the note is listed as contradicted" (the amended definition two lines
  above says "either token"; this sentence still says one).
- The self-test check text at :2385/:2650 ("when no E record shows the account's elevated token") describes the pre-amendment predicate.

### R4-6 LOW (documentation): an F run through the task route is the batch token labelled F, and nothing says so

- `-Collect` keys the contradiction list on `cond -ceq 'E'` only (:1664) and the STOP on principal only (`Test-C4WrongAccountAdd` :703-713), so
  an F-labelled task run is counted as F with its row reading `1 default | 0x00000007 enabled` (harness C31 VALID). That is the same token as the
  batch E; the label is the only difference. README :158-160 explains type 1 under F as "no split token on this build", which is a different
  mechanism from the task route. Acceptable as a measurement; it should be stated in the README F paragraph so a later reader does not take an
  F type-1 row as evidence about the interactive logon.

## What I attacked and could not break

- **Malformed E fields fail closed.** `enabled` missing, `"true"`, `1`; `use_for_deny_only` missing, `"false"`, `null`; `present` false or
  `"unreadable"`: all invalid by token state (C1-C6, C14, C15). `elevation_type.value` as `"1"`, `1.5`, `true`, 0, 4, or absent: all invalid
  (C18-C23). Type 3 under E is invalid whatever the group (C16, C17). Type 2 with the group deny-only is invalid (C13), and `Test-C4ETokenShown`
  still returns true for it, so a deny-only type-2 record still contradicts the note (by design: the token was elevated).
- **The new rows have teeth** for the enabled clause, the `Test-C4ETokenShown` enabled clause and the type list: m1, m3 and m4 each fail the
  new checks and lose the `record-validation` tag. The `$good` row counts 5 and fails when E is type-2-only.
- **No pre-existing row was weakened.** The 12-row wrong-token check still rejects every earlier row (it failed under m1 for the new rows, not
  for the old). The elevation_refused rows at :2650 and :2697 are unchanged and pass. F's type 1 or 3 row is unchanged.
- **No task, right or account verb in the driver.** The lifecycle lock rows pass (the driver, run-limited.ps1, NcoProbe.cs, the two probe
  scripts, the 42 PowerShell and 6 C# corpus forms, the library functions on the forbidden list). A grep for `schtasks`, `Register-ScheduledTask`,
  `ScheduledTask`, `secedit`, `ntrights` in the driver finds comments and check texts only.
- **The E command line is unchanged** (`--wait` kept; the task route is in the `how` text printed by `Write-C4RunSheet` :1379-1383); the
  character-for-character sheet comparison passed from the worktree; the 4b "Add arguments" line is the E line without the exe and without
  `--wait`, as the README says.
- **The docs match the code** on the E table row (README :79), the amendment (SPEC :190-197, README :368-373) and the `Test-C4ETokenShown`
  predicate, with the exceptions in R4-1, R4-5 and R4-6.

## Merge read

- **Block on** R4-1 (a run-sheet promise with no reader; Part D's "all gone" would be wrong) and R4-2 (a one-line rule gap in the lenient direction
  on the count that is the result). Both are one-place changes.
- **Do not block on** R4-3 to R4-6; land them with the same change or disposition them with a predicate.
- The amendment itself (type 1 with the group enabled is E) is sound: the question is the group's effect, a batch logon carries the group enabled,
  and the rule reads exactly the three booleans the probe derives from the attributes word.

Nothing in this review was committed, posted or written outside this file and the scratchpad.

---

# Round 5: the round-4 corrections (`1881f15d`)

Date: 2026-10-20, local clock 10:05 to 10:14 -04:00. Same reviewer, same rules: everything non-elevated through `scripts/run-limited.ps1`,
`-SelfTest` only, no engine, no live folder, no proof, no account, task or right. Diff reviewed: `2ef3e009..1881f15d` (driver +20/-10, README,
SPEC, RUN_SHEET; the author also committed the round-4 report).

## Verdict: PASS

| File (at `1881f15d`) | sha256 (first 16) |
|---|---|
| `<nco>/scripts/spike-nep5-c4-driver.ps1` | `4c0b559eb47014c6` |
| `<nco>/scripts/README.md` | `d71dae383b191ac5` |
| `<nco>/RUN_SHEET.md` | `a4fef956920fe712` |
| `<nco>/SPEC.md` | `f8935de8d1fdca04` |

## Suites run

| Run | Result |
|---|---|
| Shipped driver `-SelfTest`, non-elevated, from the worktree | `all passed (144 checks run, 0 failed)`; the wrong-token check now reads 16 rows |
| Mutant: deny-only clause of `Test-C4NcoEnabled` dropped (the round-4 m2) | **FAILED (2 failed)**: the 16-row wrong-token check (:2396, the new "enabled AND deny-only" row) and the `record-validation` tag |
| Mutant: `Test-C4AdminsEnabled` returns `$false` | **FAILED (2 failed)**: the 16-row wrong-token check (the three Administrators-enabled rows) and the `record-validation` tag |
| 34 counter-records (round-4 harness plus `Test-C4AdminsEnabled`) against the shipped driver | C24, C25, C34 (Administrators enabled under E type 1, E type 2, F) now **invalid** with one `token:` reason each; every other row unchanged from round 4 |

## Findings re-verified

| R4 | Status at `1881f15d` | Evidence |
|---|---|---|
| R4-1 run-sheet promise with no reader | **FIXED as a doc correction** | RUN_SHEET :108-109 says the check is by hand outside the driver and that part D reads the account, group and profile only; SPEC :196-199 says `-PartD` is unchanged and the session records the read in `runs/AS_RUN.md`; README :376-378 names the two reads. `Invoke-C4PartD` is unchanged; the driver still has no `schtasks`, `*-ScheduledTask`, `secedit` or `ntrights` (grep clean). |
| R4-2 Administrators enabled counted under E/F | **FIXED** | `Test-C4AdminsEnabled` :676-681 reads `present` and `enabled` as booleans; the `nco` and `nco-enabled` branches :649, :653 add a `token:` reason; three self-test rows; the mutant fails. README table :154-155 and SPEC :196 state the rule. |
| R4-3 deny-only clause untested off | **FIXED** | the row "E with the group enabled AND deny-only (a contradictory read)" :2406; the m2 mutant now fails. |
| R4-4 booleans not cross-checked against `attributes`/`sid` | **not addressed** (LOW, tamper-only; a disposition row is owed) | C7-C9, C29, C30 still VALID. |
| R4-5 stale "elevated token" prose | **FIXED where it is human-facing** | `Get-C4ElevationRefused` reason :710; the collect check text :2708; README :205. Left as is: the collect record field name `e_elevated_as_account` :1721 and the `Test-C4ETokenShown` comment :692 ("the account's elevated token (elevation_type 2), or ..." reads correctly in context). Not blocking. |
| R4-6 F through the task route unstated | **FIXED** | README :165-167. |

## Could not break

Every malformed E shape from round 4 is still invalid (C1-C6, C10-C23). The elevation_refused rows, the `$good` row (5) and the batch-logon
collect row are unchanged and pass. The E command line and the sheet comparison are unchanged. No task, right or account verb entered the driver.

## Merge read

Nothing blocks. R4-4 stays an open LOW to disposition (REJECTED under the D1-2 reasoning would be consistent). Nothing in this round was
committed or posted.
