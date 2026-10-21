# Independent pre-merge review: `feat/1764-nco-task-route` (case 4, the task route for condition E)

**Reviewed:** branch tip `7888e709` (7 commits ahead of `main` at `32ec86a8`), worktree `%USERPROFILE%/BlarAI-worktrees/nco-probe`, 2026-10-20 (-04:00).
**Reviewer:** an independent session that did not author the branch. Nothing fixed; nothing committed; this file is the only write.
**Hard limits kept:** the driver ran in `-SelfTest` only (worktree copy, and three tracked-only copies extracted with `git archive HEAD` into the session scratch folder); no engine opened; `C:\ProgramData\BlarAI\` not touched; no account, task or policy touched; the three Bitdefender-held untracked files were neither opened, copied nor staged (`git archive` carries tracked files only); `git` read-only; `LOCALAPPDATA` redirected for pytest.

## Verdict: DO NOT MERGE (one blocking defect; the measurement itself holds)

The records and the numbers derived from them are sound (see "could not break"). The block is finding 1: the regenerated bundle table cites three files that are not in the repository, so the bundle lock fails on any tracked-only checkout, which is what `main` is.

## Findings, most severe first

### 1. HIGH (gate-red on merged main) · `docs/research/containment-evidence-2026-10-05/CHANGES.md` (commit `7888e709`)

**What is wrong.** The regenerated table carries rows for `nep0005-open-questions/nco/probe/selftest-probe.ps1`, `nep0005-open-questions/nco/scripts/spike-nep5-case4.ps1` and `nep0005-open-questions/nco/scripts/spike-nep5-nco.ps1`. None of the three is tracked at `main` or at `7888e709` (`git ls-tree -r HEAD` lists none of them); they exist only as Bitdefender-held untracked files in this worktree (ticket #1764 comment 4493 names them as "three stale files Bitdefender refuses to delete"). The generator walks the disk, so it banked the worktree's leftovers as bundle content.

**Failure scenario.** After the merge, the primary checkout (which does not hold the three files; verified by listing) runs `tests/security/test_containment_evidence_bundle.py::test_changes_table_matches_the_files` and gets three `in CHANGES.md but missing` rows; `test_changes_and_manifest_are_what_the_generator_produces` and the CRLF-copy test fail with it, because the generator's output on a tracked-only tree has no such rows. The teammate's note that "the two CRLF-copy bundle tests fail in this worktree because the held file is copied" is the mirror image of the same defect: in the worktree the table matches the disk and the copy fails; on `main` the copy would succeed and the table would not match.

**Reproduced.** `changes_mismatches()` from the test module, pointed at a tracked-only extraction of `7888e709`:

```
tracked-only copy (what main will hold after merge):
   nep0005-open-questions/nco/probe/selftest-probe.ps1: in CHANGES.md but missing
   nep0005-open-questions/nco/scripts/spike-nep5-case4.ps1: in CHANGES.md but missing
   nep0005-open-questions/nco/scripts/spike-nep5-nco.ps1: in CHANGES.md but missing
worktree on disk:
   (no mismatches)
```

The public snapshot would carry the same three orphan rows. The remedy is the author's; the shape of it is a regeneration from a tracked-only tree (or from the primary checkout), not an edit of the table by hand.

### 2. MEDIUM (wrong spare: the owner fix covers one of the two write paths into the out dir) · `nco/scripts/spike-nep5-c4-driver.ps1` `Save-C4Record` (fixed at `e4383096`) vs `Invoke-C4Collect` (the copy loop, around line 1668)

**What is wrong.** `Test-AdminOnlyFolder` (arm3-persist `spike-persist-lib.ps1:673`) fails a folder when any file under it, recursively, is owned by a non-administrator. The fix gives the records written through `Save-C4Record` to Administrators. But `-Collect` also writes into the same admin-only tree: every drop record is copied into `<out dir>\case4-runs\` through `Fs.WriteBytesOnce`, which creates the folder with `New-Item` and the file with `File.WriteAllBytes`, and no `SetOwnerAdmins` follows (the only callers are the record writer and the two bin\ files in `-Prepare`). On a session whose default owner is the user SID (the condition the D-OWN row describes), the three copies written at 10:28:24 would be user-owned; and because the copies are written BEFORE the admin-only check of the script folder (line 1698), a first `-Collect` on such a session makes itself untrusted and skips the enumeration (exit 21), fix or no fix.

**Reproduced?** Hypothesis from the code; the fake file system's `Owners` map is written only by `SetOwnerAdmins`, so no self-test row sees the copies' owner either. Incidence in the banked corpus: the one exit-21 collect (`case4-collect-20261020-102824.json`, `copies[*].status = written`, `enum_skipped = true`) is consistent with this path as well as with the stated one (finding 4).

### 3. MEDIUM (lock certifies less than its sentence says) · the two `record-owner` self-test rows (`e4383096`, lines 2770 to 2775)

**What is wrong.** Row 1's sentence says the record "was given to Administrators as owner through the file seam, so the out dir still reads admin-only for the next mode". The assertion reads the fake's `Owners` map for the one `-PartD` record; nothing in the self-test asks the admin-only predicate about the out dir, and the copies of finding 2 are outside the map. The row holds the function; the "so the out dir still reads admin-only" clause is not what it tests. Row 2 ("the mode still returns its reading, exit 20") is accurate.

**Reproduced.** The rows do fail for the two mutants that matter (SetOwnerAdmins call removed; owner failure swallowed): see the mutant table under "what I ran". The over-claim is in the sentence, not in the teeth.

### 4. LOW (prose that contradicts the driver's own gates) · `runs/AS_RUN.md` second-run timeline; `runs/results-summary.json` `second_run_records.collect[0]`; `scripts/README.md` departure 1; the new `Save-C4Record` comment (line 1378)

**What is wrong.** Three claims about the 10:28 exit 21:
- "a record of the first run was owned by the writing token" (AS_RUN, results-summary). `-Prepare` refuses when the out dir is not admin-only (lines 1529 to 1530) and it ran clean at 09:28:24 with every first-run record already in that folder. So the file that broke the 10:28 check was written after 09:28:24: the 09:28 prepare record, or the 10:28 copies of finding 2. Which one is unrecorded (no record carries owners); the attribution to a first-run record is a derivation that the prepare gate contradicts.
- "the next mode refused to run until the owner was corrected" (README departure 1, the function comment, the journal fragment). Only `-Prepare` refuses. `-Collect` proceeds with the enumeration skipped (exit 21, which is what the banked record shows); `-Finish` proceeds with the harness untrusted ("removal falls back to our own engine", line 1753); `-PartD` has no admin-only check at all. README departure 1 says both in one paragraph ("refused to run" and "one such pass, with the engine enumeration skipped").
- Ticket #1764 comment 4496 banks "worked around three times today" without naming the three occasions; the records cannot confirm or deny the count.

**Reproduced.** Read from the driver at `7888e709` (lines cited); no run needed.

### 5. LOW (provenance imprecise in two of the four surfaces) · claim C27 (`docs/research/account-level-containment-evidence-2026-10-05.md:79`) and `PERFORMANCE_LOG.md` (top entry, Setup)

**What is wrong.** Both say the driver was `1ed25f50` "for the first run and `1881f15d` for the second". The second run's `-Prepare` (09:28:24) ran on the first run's bytes: the branch's first commit is 09:52:21 and `1881f15d` is 10:25:05, and the prepare record's embedded `run_sheet` is the `1ed25f50` text (no step 4b). `AS_RUN.md` and `docs/performance/nep5_case4_nco_2026-10-20.json` say this exactly ("the second run's -Prepare ran on the first run's bytes"); C27 and the log do not. The claim "every version independently reviewed before it ran" survives (the `-Prepare` bytes were the round-3 PASS bytes); the commit attribution for the second run's prepare phase does not.

**Reproduced.** `git log --format='%h %ci'` on the branch; the prepare record's `run_sheet[1].how` compared with the driver text at `1ed25f50` and `HEAD`.

### 6. LOW (a claim with no banked artifact) · `AS_RUN.md` second-run timeline, `nep5_case4_nco_2026-10-20.json` `cleanup`

"matrix `-Check` 20" after the second run's `-Finish` has no record in `runs/` or `runs/controls/` (the only taskcheck record is 2026-10-19 16:49:08, before the first run). The first run carries the same unbanked claim on `main`; the second instance is new on this branch. Ticket comment 4496 states it; the matrix's own record, if one was written, is not in the bundle.

## What I attacked and could not break

- **Every number in the prose against the records.** The three E records differ only in pid, clocks, logon-session SID, stamp, file name and filter id (537392, 537393, 537394, consecutive); each reads elevation type 1 "default", integrity `S-1-16-8448` medium_plus, linked token absent (1312), session 0, `S-1-5-32-556` attributes 0x00000007 enabled, Administrators absent, `is_expected_account` true, add 0x0 read back present, delete 0x0 read back absent (`get_rc` 0x80320003), residue absent, exit 0. The three collect records list exactly these three as valid with elevation_type 1, zero invalid, `elevation_refused.given false`; 102824 exit 21 with `enum_skipped true`, 102913 and 102929 exit 0 with `enum_skipped false`. The final record: collect code 0, 3 valid, the probe key not found, S1/S2/S3 and the provider deleted, sweep clean, export 0 hits over 2,000,945 bytes, engine SD `compare.same true` against `case4-prepare-20261020-092824.json`, drop ACEs for RID 2251 and RID 1001 removed and read back `O:BAD:PAI(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)`, folder removed, verified, code 0. Part D 110756: code 20, account absent (`net user` 2221, lookup 1332), group empty, RID 2251, profile absent, ProfileList absent, no folders. The first-run collect 012313 carries the four-refusal note verbatim. C27, the log, the JSON, results-summary and the journal fragment agree with all of it: "3 of 3", "4 of 4 refusals", the filter ids, the attributes, the timeline (09:28:24, 09:33:12, 09:37:10, 09:42:29, 10:28:24, 10:29:13, 10:29:28, 11:07:56), RID 2250 then 2251, the 52 disposition rows. No statement in the five surfaces still says the full token was unreachable or the group-enabled token unmeasured without the task-route result beside it; the "Not measured" list was rewritten and names the two logons that were not attempted.
- **AS_RUN file table.** 28 rows; every raw byte size and LF sha256 recomputed from disk: 0 mismatches.
- **Hashes cited.** Driver at `1ed25f50` `47fcd179...`, at `1881f15d` `4c0b559e...` (LF) and `18f2262a...` (CRLF form), at `e4383096`/HEAD `c48019a3...`; corpus `f9830409...`; `NcoProbe.cs` `28bc05d5...`: all match the files in git. The probe exe hash is not in the tree and was not checked.
- **The E rule and its locks.** `Test-C4NcoEnabled`, `Test-C4AdminsEnabled`, `Test-C4ETokenShown` read as their comments say; the wrong-token rows include type 1 deny-only, type 2 deny-only, the contradictory 0x14 read, Administrators enabled under E (both types) and under F; the note-contradiction row for the batch token exits 4 when a valid type-1 enabled record is present and stays counted beside a deny-only one.
- **Seams lock.** `-SelfTest` at `7888e709` (worktree and tracked-only copy): "seams: every engine, harness, export, ACL, account, netsh, net and process call of this file sits inside a *-C4Real* seam" PASS; the 4 named plants and the 14 planted machine or file calls are found. The new `SetOwnerAdmins` call sits on `$Ctx.Fs`; the real implementation sets the owner and reads it back, throwing when it does not read `S-1-5-32-544`.
- **`Writes` counters.** The fake's `SetOwnerAdmins` increments `Writes`; the only rows asserting a count assert zero (`-Check`, `-DryRun`), and neither mode calls the record writer. No row passes for the wrong reason.
- **Failure path of the fix.** A write failure returns `$null` with the message (unchanged); an owner failure returns `$null` with a red line that names the consequence. Fail-closed for the callers that read the return (`-Prepare` refuses to print PREPARED without the saved record); the `[void]` callers (`-Collect`, `-Finish`, `-PartD`) keep their exit code, which is their reading of the system, not of the record. Honest, with the caveat of finding 3's sentence.
- **Disposition.** `verify_disposition.py --repo .` PASS 52/52. R4-1, R4-2, R4-3, R4-5, R4-6 cite `1881f15d`; the branch diff shows those changes in that commit (the Administrators rule, the 0x14 row, the reason text, README and SPEC prose, RUN_SHEET 4b item 5). D-OWN cites `e4383096`, which holds exactly the function change and the two rows. R4-4 REJECTED: the argument (the four booleans derive from one uint in `GroupFlags.From`, so a contradiction needs a hand edit, the D1-2 residual) is sound as an argument about probe-written records; the row prints both fields so an edit is visible. Accepted.
- **Identifier hygiene.** `scrub_public_identifiers.py --check` 0 findings in 4195 files; `rewrite_sid_domain.py --check` 0; `research_tracker_lock.py --check` ok. The branch diff of `docs/research/` carries only the placeholder domain `1000000001-1000000002-1000000003` (52) and the fabricated stale domain (12), no e-mail, `__HOST__` for the host. The string `BlarAI #1763 case4 nco probe` (the probe's display name) is in every E record and the prepare record; it is also in every first-run record on `main` and the tracker lock accepts it.
- **Review r4/r5 file.** Round 4 PASS WITH CORRECTIONS, round 5 PASS at `1881f15d` with the hash table, present as the disposition says.

## What I ran, and at which hash

| What | Where | Result |
|---|---|---|
| `spike-nep5-c4-driver.ps1 -SelfTest` | worktree, `7888e709`, non-elevated, pwsh 7.6.7 | all passed (146 checks, 0 failed), 24 required tags |
| `-SelfTest` on a tracked-only copy of `7888e709` | scratch `base/` | all passed (146 checks, 0 failed), 24 tags (the lib fallback to the repository layout works; the held files are not needed) |
| `-SelfTest`, mutant 1: `SetOwnerAdmins` call removed from `Save-C4Record` | scratch `mut1/` | FAILED (146 run, 2 failed): both `record-owner` rows fail (`owners: ` empty; the second row's message never printed) |
| `-SelfTest`, mutant 2: owner failure swallowed (`catch { }`, record reported written) | scratch `mut2/` | FAILED (146 run, 1 failed): the second `record-owner` row fails (no red line); the first still passes, as it should |
| `scripts/verify_disposition.py docs/reviews/1764-case4-review-disposition-2026-10-20.md --repo .` | worktree | PASS 52 ok / 0 unjustified |
| `scrub_public_identifiers.py --check`, `rewrite_sid_domain.py --check`, `research_tracker_lock.py --check` | worktree | 0 / 0 / ok |
| `changes_mismatches()` from the bundle test | tracked-only copy and worktree | 3 orphan rows / 0 (finding 1) |
| AS_RUN file table recompute (28 rows) | worktree | 0 mismatches |
| pytest (bundle, tracker, disposition, SID and host scrubs, public snapshot, nep0005 dataset, doc pointers, measurement subjects, ledger candidates), `LOCALAPPDATA` redirected | worktree, `7888e709` | 4 failed / 989 passed in 865 s: the two CRLF-copy bundle tests (the held file) and the two `test_doc_pointers_and_banners` ADR-013 rows, all four the known worktree artifacts; nothing else failed |

Known worktree artifacts excluded from the findings as instructed: `test_doc_pointers_and_banners.py` (ADR-013 relative link), the CRLF-copy bundle tests failing on the held file (but see finding 1 for what they would do on `main`), router env-skips.

## Merge read

- **Block on finding 1.** It is a committed artifact that turns the bundle lock red on the primary checkout the moment the branch lands, and the public snapshot would carry three rows for files it cannot contain. One regeneration from a tracked-only tree clears it; re-verify with `changes_mismatches()` on a `git archive` extraction before merging, since the worktree will keep passing for the wrong reason while the held files sit in it.
- **Do not block on 2 to 6**, but 2 and 4 belong in the disposition before the ticket closes: 2 as a FIXED row or a DEFERRED row with an observable predicate (the copy path is the same class of write as the one D-OWN fixed), 4 and 5 as in-place corrections of the sentences named (the surfaces that are right, AS_RUN and the JSON, show the wording).
- **The measurement stands.** Nothing in the records contradicts the prose's numbers, and the token facts C27 now states are the ones the probe wrote.

---

# Round 2: the branch at `ac486ca6` (hand-back after the fixes `4e75a9cf`, `4ebad95c`, `b8f4d2df`, `5bbe6d46`, `ac486ca6`)

Same reviewer, same limits (`-SelfTest` only; tracked-only copies from `git archive ac486ca6`; the held files untouched; `git` read-only; `LOCALAPPDATA` redirected). Every check below is my own run at `ac486ca6`; the author's logs in the scratch folder were not used.

## Verdict: DO NOT MERGE (one blocking row; everything from round 1 is closed)

Findings 1 to 6 of round 1 are fixed as the disposition rows R5-1 to R5-6 say, and the new locks bite (mutant table below). The block is a new defect introduced by the fix commits themselves: the AS_RUN file table now misstates `results-summary.json`.

## Findings

### R2-1. MEDIUM, blocking by the precedent this ticket already set · `nco/runs/AS_RUN.md` line 57 (file table row for `results-summary.json`)

**What is wrong.** `b8f4d2df` edited `results-summary.json` (the 10:28 attribution sentence) without regenerating the table. The row says 19271 bytes, sha256 (LF) `a1fe8827...`; the file on disk at `ac486ca6` is 19392 bytes, `42c95550...`. The other 27 rows match. This table is not machine-checked (the bundle test's manifest check covers `confined-model-spike/as-run` only), so nothing in the gate catches it; the first pre-merge review of this ticket blocked on exactly this class (ticket comment 4491: "DO NOT MERGE on a stale as-run hash row").

**Reproduced.** The round-1 recompute script against the tip:
```
MISMATCH results-summary.json 19271 19392 a1fe8827f7b0 42c955505e69
rows 28 bad 1
```

### R2-2. LOW (a disposition row cites evidence that does not exist yet) · `docs/reviews/1764-case4-review-disposition-2026-10-20.md`, row R5-4

R5-4's evidence ends "ticket comment 4496's count is retracted in the POST-CLOSE comment". At the time of this review the newest comment on #1764 is 4497 (11:20 EDT); no POST-CLOSE comment exists, so the retraction is a promise written as a fact. The rest of R5-4 holds: README departure 1, the function comment, the journal fragment and the D-OWN row now say `-Prepare` refuses, `-Collect` skips the enumeration, `-Finish` falls back and `-PartD` has no check (read at the tip); AS_RUN and results-summary name the broken file as unrecorded and written after the 09:28 prepare; the "three times" count is gone from every tracked surface; "the records show one instance" is exact (one exit-21 collect). Correct the sentence to what has happened, or post the comment before the merge motion and keep it.

### What I asked of R5-4 beyond that, and found nothing

The author asked whether R5-4 overstates what the records show. The records show: one collect with `enum_skipped true` (10:28:24), a prepare that passed its out-dir gate at 09:28:24, and no owner on any file. R5-4 and the corrected prose claim nothing beyond those three facts except the ticket-comment sentence above.

## Round-1 findings re-verified at `ac486ca6`

| Round 1 | Status | How verified |
|---|---|---|
| 1 CHANGES.md orphan rows | FIXED (`4e75a9cf`) | `changes_mismatches()` on a `git archive ac486ca6` extraction: none |
| 2 copies written without an owner | FIXED (`4ebad95c`) | the folder and each copy go through `SetOwnerAdmins`; a failed copy owner turns the status into "written, owner not set", the record invalid, exit 4; `copies_folder_owner` in the record; the real seam takes a folder (`DirectoryInfo` when `-PathType Container`) and reads the owner back. Mutants below |
| 3 record-owner row sentence | FIXED (`4ebad95c`) | the sentence now ends at "through the file seam (owners: ...)" |
| 4 "next mode refused" and the first-run attribution | FIXED (`4ebad95c`, `b8f4d2df`) | see R2-2 for the one residual sentence |
| 5 driver commit for the second run's `-Prepare` | FIXED (`4ebad95c`) | C27 and the log: "`1ed25f50` for the first run and for the second run's `-Prepare`, `1881f15d` for the second run's `-Collect`, `-Finish` and `-PartD`" |
| 6 "matrix -Check 20" unbanked | FIXED as an explanation (`b8f4d2df`) | `Invoke-Check` in `spike-nep5-matrix.ps1` (lines 180 to 213) prints and returns the code and writes nothing; only `-Remove` and `-Run` call `Write-JsonGuarded`. The prose now says "an exit code only" in AS_RUN (both runs) and the JSON |

## What I ran at `ac486ca6`

| What | Where | Result |
|---|---|---|
| `-SelfTest` | worktree `nco-probe` | all passed (148 checks, 0 failed), 26 required tags; `seams` row PASS; both `copy-owner` rows PASS |
| `-SelfTest` on a tracked-only copy | scratch `base2/` | all passed (148, 0) |
| mutant 3: the copies' `SetOwnerAdmins` block removed | scratch `mut3/` | FAILED (148 run, 3 failed): both `copy-owner` rows (`owners: S-1-5-32-544, , , , `; exit 0 where 4 is required) and the required-tags row |
| mutant 4: the copy-owner failure swallowed (`catch { }`, status stays "written") | scratch `mut4/` | FAILED (148, 2): the second `copy-owner` row (exit 0) and the required-tags row; the first row still passes, as it should |
| mutant 5: the folder's `SetOwnerAdmins` removed while `copies_folder_owner` still claims Administrators | scratch `mut5/` | FAILED (148, 3): the first `copy-owner` row (folder owner empty) and, because the stand-in no longer throws on the folder, the second row's "folder owner reads as an error" clause; required-tags row |
| `changes_mismatches()` | tracked-only extraction of `ac486ca6` | none |
| AS_RUN file table recompute (28 rows) | worktree | 1 mismatch (R2-1) |
| driver hashes claimed in the new AS_RUN row | git | LF `06d63d97...` and CRLF form `5acc9425...` both match the file at the tip |
| `verify_disposition.py --repo .` | worktree | PASS 58 ok / 0 unjustified |
| `scrub_public_identifiers.py --check` / `rewrite_sid_domain.py --check` / `research_tracker_lock.py --check` | worktree | 0 findings in 4196 files / 0 / ok |
| selected pytest (same twelve files as round 1), `LOCALAPPDATA` redirected | clean worktree `c4-gate` at `ac486ca6` | 2 failed / 991 passed in 763 s; the 2 are `test_doc_pointers_and_banners` (ADR-013 relative link, the known worktree artifact); the bundle tests, including the two CRLF-copy tests, pass on the clean tree |
| ticket #1764 comments | Vikunja, read-only | 18 comments, newest 4497; no POST-CLOSE comment (R2-2) |

## Merge read, round 2

- **Block on R2-1.** A hash table whose one job is to be exact carries a wrong size and a wrong hash for the summary file every reader opens first; it is the class this ticket's first review already blocked on. One regeneration of the row (and a check that no other tracked file in `runs/` moved) clears it. Re-run the recompute before the merge motion, because every edit to a `runs/` file after this point reopens it.
- **Fix R2-2 in the same motion**, either way round.
- **The measurement, the locks and the hygiene are clean**: nothing changed in the records; the E rule, the seams lock, the record-owner and copy-owner rows all hold under mutation; scrub, SID and tracker locks pass; the bundle lock passes on a tracked-only tree.

---

# Round 3: the branch at `8123ab12` (delta `d1657dbb`, `8123ab12` only)

Same reviewer, same limits. Scope as asked: the two commits after `ac486ca6`. `git diff --stat ac486ca6..8123ab12` touches three files: `nco/runs/AS_RUN.md` (one row), the disposition record (R5-4 amended; R2-1 and R2-2 added) and this review file (round 2 appended; the only deletion is the `SEE_PYTEST` placeholder row I had already replaced).

## Verdict: MERGE

| Round 2 | Status | How verified at `8123ab12` |
|---|---|---|
| R2-1 stale AS_RUN row for `results-summary.json` | FIXED (`d1657dbb`) | the row now reads 19392 bytes, `42c95550...`; the round-1 recompute over all 28 rows: 0 mismatches |
| R2-2 R5-4 cited a retraction that did not exist | FIXED (`d1657dbb`) | ticket #1764 comment 4508 (2026-10-20, "RETRACTION ... corrects comment 4496") exists and says what R5-4 now attributes to it: one instance supported by the records, the count withdrawn, the broken file unrecorded, the per-mode behaviour as the driver has it. R5-4 cites 4508 by number |

Also at the tip: `verify_disposition.py --repo .` PASS 60 ok / 0 unjustified; `scrub_public_identifiers.py --check` 0 findings in 4196 files; `rewrite_sid_domain.py --check` 0; `research_tracker_lock.py --check` ok. No driver, record, claim or performance file changed in the delta, so the round-2 results for the self-test (148/0, 26 tags, mutants failing), the bundle lock on a tracked-only tree and the selected pytest stand for `8123ab12` without re-running.

## Merge read, round 3

Nothing blocks. Keep the AS_RUN recompute as the last step before the merge motion if any file under `runs/` is touched again; the table is not machine-checked, and it has gone stale twice on this ticket.
