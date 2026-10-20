# Pre-merge review: feat/1764-nco-probe docs and records (#1764, case 4)

**Reviewed:** branch head `212f39ae` (worktree `C:/Users/__USER__/BlarAI-worktrees/nco-probe`) against main `f08d8f67`; 40 files, 18,456 insertions, no deletions. Scope per the brief: the claim, the performance entry and JSON, `runs/AS_RUN.md` and `results-summary.json`, the journal fragment, `nco/SPEC.md` and `nco/RUN_SHEET.md`, the disposition record, and anything that should not merge. The probe and driver code were not re-reviewed (three rounds each, already dispositioned).
**Reviewer:** independent session; nothing written to the branch; no git state changed; no engine opened; nothing under `C:/ProgramData/BlarAI` or any account touched. Every record was loaded with a script from the worktree files (`python -I`), never read from the prose.

## Verdict: DO NOT MERGE (one blocking finding, one gate-red companion; both one-line fixes)

Two tests in `tests/security/test_public_snapshot_excludes_private_material.py` FAIL on the branch and PASS on main at `f08d8f67` (same invocation, same machine): the branch is not gate-green. Everything else in the records traces; the measurement itself is sound.

## Lock outputs (run from the worktree at `212f39ae`)

```
python scripts/scrub_public_identifiers.py --check
scrub_public_identifiers --check: 0 finding(s) in 4177 tracked files            exit 0
python scripts/rewrite_sid_domain.py --check
0 tracked file(s) carry the domain                                               exit 0
python scripts/research_tracker_lock.py --check
research tracker lock: ok (0 finding(s))                                         exit 0
python scripts/verify_disposition.py docs/reviews/1764-case4-review-disposition-2026-10-20.md
RESULT: PASS - 45 ok / 0 unjustified of 45                                        exit 0
pytest tests/security/test_public_snapshot_excludes_private_material.py tests/security/test_disposition_discipline.py
       tests/security/test_no_machine_sid_domain_in_tree.py tests/security/test_no_host_identity_in_tree.py  (LOCALAPPDATA redirected)
2 failed, 246 passed in 558 s
  FAILED ...::test_no_journal_file_carries_the_marker
  FAILED ...::test_every_path_an_anchored_document_cites_is_anchored_or_allowlisted
Control on main f08d8f67, the same two tests: 2 passed in 55 s
```

## Findings

### M-1 BLOCKING (gate red; a PRIVATE fragment would reach the public snapshot). `docs/journal_fragments/2026-10-20_nep0005-case4-nco.md:1` and `.publicignore`

The fragment's first line carries the held-back marker (the comment line the public-snapshot lock defines as FRAGMENT_MARKER), but `.publicignore` (index copy, lines 41 to 46) lists only `*1741*`, two 2026-10-13 fragments, one 2026-10-12 and the 2026-10-09 ones. The file is therefore a PUBLISHED file that carries the marker core, and the lock reads that as a held-back fragment folded into the public journal. Reproduced:

```
E  AssertionError: a held-back fragment was folded into the public journal: docs/journal_fragments/2026-10-20_nep0005-case4-nco.md
```

The fragment carries the account-lifecycle ruling, the Bitdefender quarantine trail with detection names, and the live-folder paths; whether it is private is the author's call, but the header and the list must agree either way. Fix is one line in `.publicignore` (or drop the marker line if the entry is meant to be public).

### M-2 BLOCKING (gate red; same test file). `docs/reviews/case4-sid-rewrite-log-2026-10-20.md` is cited by an anchored document and is not anchored or allowlisted

`test_every_path_an_anchored_document_cites_is_anchored_or_allowlisted` fails naming `docs/reviews/case4-sid-rewrite-log-2026-10-20.md` and `scripts/scrub_public_identifiers.py`. `runs/AS_RUN.md` and `results-summary.json` (anchored evidence) cite both. The 2026-10-13 arc's equivalent log is covered; this one is new. Fix: add the log to `scripts/publicignore_anchors.txt` below the cited-only line (and the scrub script to `scripts/publicignore_cited_unanchored.txt` with a reason, as the assertion text says). Reproduced above.

### M-3 MEDIUM (a number in the community dataset is a placeholder, not a reading). `docs/performance/nep5_case4_nco_2026-10-20.json`, field `clock`

`"standard-token control (matrix phase n1) 2026-10-19 16:49:53 to 16:50:xx"`. The record `runs/controls/nep5-results-n1-20261019-164952.json` carries `started 2026-10-19T16:49:52.656-04:00`, pass starts 16:49:53, 16:50:21, 16:50:50, `finished 2026-10-19T16:51:17.526-04:00`. The real end is 16:51:17. A literal `xx` in a published JSON clock field is the one shape a reader cannot repair.

### M-4 MEDIUM (false provenance for the OS build). `docs/performance/nep5_case4_nco_2026-10-20.json`, `hardware.os`

Says the build revision 9711 comes from the probe records' console banner. No per-run record has a console field and `grep 9711` over every file under `runs/` returns nothing; the only tracked carriers of `9711` are PERFORMANCE_LOG entries and ticket comment 4490. The build revision is probably right (the 10-15 and 10-16 entries read the same build) but the stated source does not exist. Same class, lower weight: `hardware.cpu` and `ram_gb` are the host facts, not record facts.

### M-5 LOW (numbers that trace only to the ticket, not to any banked record). `runs/AS_RUN.md`, `PERFORMANCE_LOG.md`, the performance JSON

Not carried by any file under `runs/`: driver proof `144 checks, 24 tags, probe runner 215 checks` (AS_RUN "Driver proof" row; JSON `software.reviews`); matrix `310 checks at 16:48:31` (JSON `standard_token_control`); `-Prepare 00:48:45` (AS_RUN timeline; the prepare record's `at` is 00:48:48.9, its sweep 00:48:52; JSON `clock`); `matrix -Check 20` (AS_RUN cleanup row; JSON `cleanup`); the engine ACE `present as on 2026-10-13` (JSON `engine_access_list`: no tracked 10-13 record carries `0x307ff`). Each traces to ticket comments 4482, 4489 and 4490, which the brief did not count as records, and the proof files sit in the admin-only live folder. These should either cite the ticket comment as their source or be dropped; as written AS_RUN presents them beside hashes that do reproduce.

### M-6 LOW (provenance pointer to a record not in the bundle). `runs/case4-final-20261020-012312.json`, `collect.record`

The final record's embedded collect names `nep5-out\case4\case4-collect-20261020-012313.json` (the collect that `-Finish` ran itself at 01:23:13). The bundle carries `case4-collect-20261020-012258.json` (the operator-facing `-Collect` of 01:22:58) and AS_RUN's timeline names only that one. The two collects agree (10 valid, 0 invalid, the same elevation_refused note), so nothing is wrong in substance, but the as-run note should say that `-Finish` re-collected and that its collect record is not banked.

### M-7 LOW (AS_RUN's header contradicts its size column). `runs/AS_RUN.md`, "Files" table

Header: "sizes and sha256 of the LF-normalised bytes". Every sha256 matches the LF-normalised bytes (18 of 18 recomputed). The sizes do not: for the 8 files written with CRLF by the driver and the matrix, the column holds the raw size (collect 10091 vs 9783 LF; final 7129 vs 6948; partd 1181 vs 1149; prepare 20171 vs 19925; n1 67220 vs 65467; taskcheck 6512 vs 6343; remove 4700 vs 4523; the probe's own records are LF already and match). Say "raw bytes" or normalise the column.

### M-8 LOW (stale text in SPEC.md). `nco/SPEC.md`

- "Fixed constants" paragraph on research-tree locks: "Records committed under `runs/` carry every machine-domain SID in the placeholder form `S-1-5-21-__MACHINE__-<rid>` (the scrub rewrites them...)". Part 3 (settled at `892701dc`, P1-9) and the records say the opposite: `rewrite_sid_domain.py` writes `S-1-5-21-1000000001-1000000002-1000000003-<rid>`, and the scrub's `--dir` mode is never used on these copies. The earlier paragraph was not updated when Part 3 was.
- Part 2, `-SelfTest` mode: still says the driver "runs `probe/selftest-probe.ps1`" and lists `selftest-probe.ps1` among the live-folder files. The runner shipped and ran as `run-probe-selftest.ps1` (probe README amendment 7; Part 1's own last paragraph explains the rename without naming the new file).
- Part 3: the performance JSON is named `docs/performance/nep0005_case4_nco_<date>.json`; the file is `docs/performance/nep5_case4_nco_2026-10-20.json`.
- "Binding gate" line cites `docs/reviews/review-1764-case4-gate-2026-10-19.md`; that file exists only as an untracked file in the primary checkout (`C:/Users/__USER__/BlarAI/docs/reviews/`, 9,391 bytes) and is on neither main nor the branch. A reader of the merged tree cannot open it.

RUN_SHEET.md is consistent with what ran (file names, the E two-step, `STOP:` stop line, the "cancel if the prompt only offers your own account" instruction that became the E result); no stale names found in it.

### M-9 LOW (disposition prose). `docs/reviews/1764-case4-review-disposition-2026-10-20.md`, row D1-11

"FIXED | 574712d1 - UTC stamp". The fix on disk is different: `Get-C4LatestPrepare` (driver line 1363 onward) selects the prepare record by the UTC instant in its `at` field, "never by its file name (a local-time stamp...)", and the file name stays local-time (`case4-prepare-20261020-004848.json` is 00:48 local, the proof stamp is 04:48Z). The fix is real and better than the row says; the row misdescribes it. Also: three reviewer notes have no row and arguably need none, recorded so the next pass does not re-litigate: probe r2 N-1 and the round-3 "driver seam" note (superseded by the driver rounds), N-3 (the reviewer's own correction), and the round-3 "stray file" note (the untracked `probe/selftest-probe.ps1`, still present untracked in the worktree, not in the diff, not deployed: the prepare record lists no such file in `bin\`).

### M-10 LOW (wording that does not match the record). Claim C27 and the fragment

- C27, Conditions column: the standard-token control is "the matrix's N1 phase re-run the same evening". The record is 2026-10-19 16:49 to 16:51 -04:00; the case-4 runs are 2026-10-20 01:05 to 01:22. PERFORMANCE_LOG says "the same afternoon" and the fragment "that afternoon"; C27 should match.
- Fragment plain summary: "two review rounds per limb". Each limb had three rounds (FAIL, PASS, PASS appended), as the disposition, PERFORMANCE_LOG and the JSON say.

## What traced (attacked and could not break)

- **Every per-run token fact and return code.** 10 records loaded: F x4 `elevation_type 3`, integrity medium, linked token present, `S-1-5-32-556` present `0x00000010` deny-only, Administrators absent, add `0x00000005`, delete `0x80320003`, exit 0, residue absent; S x3 type 3, Administrators `0x00000010`, NCO absent, same rcs; A x3 type 2, high, Administrators `0x0000000F`, add and delete `0x00000000`, `present_after` true then false. Counts 4/0/3/3 are what the files hold; `results-summary.json` per-condition fields match every record field by field, and its record hashes match the files.
- **The control.** `controls/nep5-results-n1-20261019-164952.json`: 3 passes, each `class ok`, "both denied (add: 0x00000005; delete: 0x00000005)"; 3 of 3 as claimed. `controls/remove-20261019-164737.json` holds the four deleted srt-win keys the fragment describes.
- **E.** The collect record's `elevation_refused` block: `given true, counted true, contradicted_by []`, note "cancelled it, four times"; `e_elevated_as_account []`. "0 runs, 4 refusals" is what the record says.
- **Clocks.** F 01:05:15, 01:14:00, 01:14:24, 01:14:40; S 01:21:45 to 01:21:48; A 01:22:40 to 01:22:43; collect 01:22:58; final 01:23:12; part D 01:42:16; proof `written_utc 2026-10-20T04:48:52Z`; driver proof written 00:47:44: all read from `clock_start`, `at` and `proof` fields. The only clocks not in a record are the five in M-3 and M-5.
- **Engine and cleanup.** Prepare and final `netsh wfp show security type=engine` texts both carry `(A;;0x307ff;;;NO)`; final sweep `clean true`, export hits all 0; `probe_key_after false`; drop ACEs removed and read back; `code 7` with the "being used by another process" error exactly as AS_RUN states; part D `code 20`, account 1332, group members empty, ProfileList absent.
- **Hashes.** 18 of 18 AS_RUN sha256 values recomputed over LF-normalised bytes match. `NcoProbe.cs` at `21cb384d` and at head = `28bc05d5...`; `spike-nep5-c4-driver.ps1` at `1ed25f50` and at head = `47fcd179...`; `case4-lock-corpus.json` at `1ed25f50` = `f9830409...`; every record's `probe_exe_sha256` = `4fde1ad6...`; the sanitisation chain closes (collect's pre-sanitisation hash 52651cf1 = sid-rewrite "before", its "after" = scrub "before", scrub "after" = AS_RUN).
- **Sanitisation.** All three locks clean (outputs above). No `@`, no `MicrosoftAccount`, no operator name, no host name, no `C:\Users\<operator>` anywhere in the 10 records (every account-domain, S-1-11 and logon-session group is `name_withheld`; the only `C:\Users\` paths are `nco-probe` and `__USER__` in the matrix control's provisioning tail). The stale SID is unchanged in every record.
- **Disposition.** 45 rows = 45 finding ids across the four review files (P1-1..9, P2-1..4, P3-1..2, D1-1..15, D2-1..11, R3-1..4; none missing, none extra). All six cited commits exist on the branch; spot-checked diffs carry the fix (P1-1 `name_withheld` in `8387e047`; D1-1 token-state validation in `574712d1`; D2-8 the `MicrosoftAccount` refusal in `1ed25f50`; P1-9 the SPEC Part 3 edit in `892701dc`). The five REJECTED rows argue from mechanism (D1-2, D2-11, R3-1..4), not assertion.
- **Corpus count.** `case4-lock-corpus.json` holds 248 alternatives-plus-plants, as the fragment and PERFORMANCE_LOG say.
- **The diff.** No scratch files; the three stale untracked files (`probe/selftest-probe.ps1`, `scripts/spike-nep5-case4.ps1`, `scripts/spike-nep5-nco.ps1`) are not in it; no secrets, no password, no operator name, no operator profile path.
- **Status words.** C27 uses OBSERVED 4 of 4, NOT REACHABLE 4 of 4, NOT ESTABLISHED, per the table's rules; the "not tested" column names the group-enabled routes, other builds, domain join, the group's other rights; the JSON `not_measured` list adds the interactive-session prompt, timing and the replication caveat. Honest.

## Merge read

Block on M-1 and M-2: the branch fails two standing-gate tests that main passes, and M-1 is a privacy control (a file marked PRIVATE would publish). Both are one-line list edits. M-3 and M-4 are the kind of thing the performance dataset is published for and should land in the same fix. M-5 through M-10 are prose and provenance; none changes a number a reader would act on, and I would not hold the merge for them, but the SPEC's `__MACHINE__` sentence (M-8) actively contradicts the records and should not survive a second reader.

Suites run: the three lock scripts and the disposition verifier (worktree, `212f39ae`); pytest on the four security lock files above (worktree, LOCALAPPDATA redirected); the two failing tests re-run on main `f08d8f67` as the control. The standing gate was not run on the branch.

## Round 2: branch tip `0ecfccf6` (re-verified from disk; the tree was moving, the index held staged edits beyond the tip)

**Verdict at the committed tip `0ecfccf6`: DO NOT MERGE** on one new finding (M-11); M-1 and M-2 are fixed at the tip.

Lock outputs at `0ecfccf6` (worktree): the three scripts and the disposition verifier unchanged (0 / 0 / 0 findings, 45 of 45). `tests/security/test_containment_evidence_bundle.py`: 94 passed (the `netsh_text` rename satisfies the bundle lock). The two public-snapshot tests, run in a clean clone of the branch checked out at `0ecfccf6` (scratchpad, `core.longpaths`, empty status): **2 passed**. Run in the worktree itself they still fail, because the lock reads the INDEX and the index holds staged files beyond the tip: a staged copy of this review (its M-1 quoted the marker line verbatim, which the lock counts as a published file carrying the marker; this file no longer quotes it) and the staged, uncommitted `docs/reviews/review-1764-case4-gate-2026-10-19.md`, cited by SPEC.md and anchored nowhere. Whoever commits those must add the gate review to `scripts/publicignore_anchors.txt` and restage this review from the primary checkout.

### M-11 BLOCKING (an AS_RUN hash does not match the bytes it certifies). `runs/AS_RUN.md`, row `results-summary.json`

AS_RUN at `0ecfccf6` lists `results-summary.json | 12438 | a62f37cabe5c...`. The committed file (last changed in the same commit, its `sanitisation` string edited to drop the `scripts/` path) is 12609 bytes and LF-sha256 `7f278eda1162...`. The staged AS_RUN in the index carries the same stale row. 17 of the other 18 rows match (recomputed: the three renamed copies now hash `990256ae...`, `b2efc5f5...`, `ac2f6ce5...` as listed). The summary is the one file the claim's Evidence column points at, so its hash row must be regenerated after every edit; this is the second time in two commits it moved under the table.

### Re-checked at the tip

- The JSON record diffs `212f39ae..0ecfccf6` are key renames only (`text` to `netsh_text`, 14 in prepare, 2 in final, 2 in part D) plus the summary's `sanitisation` string; no value changed. AS_RUN says so.
- M-1 fixed (marker line dropped; the fragment is now public by decision). M-2 fixed (sid-rewrite log anchored). M-7 fixed in the staged AS_RUN header. M-8 partly fixed in the staged SPEC (`__MACHINE__` sentence, runner name, JSON file name, gate-review note). M-9 fixed in the staged disposition row. M-3 fixed in the staged JSON (`16:51:17`); still `16:50:xx` at the committed tip. M-4 reworded in the staged JSON to name a screenshot of the E attempt as the source and to say the records carry no build number.
- **New, LOW:** `docs/research/containment-evidence-2026-10-05/CHANGES.md` (regenerated by `make_changes.py` from the working tree) now lists `nco/probe/selftest-probe.ps1`, `nco/scripts/spike-nep5-case4.ps1` and `nco/scripts/spike-nep5-nco.ps1` as bundle files. All three are untracked and are the quarantine-held stale generations; a tracked manifest names files the tree does not hold. Regenerate after removing or ignoring them.
- M-5, M-6, M-10 unchanged at the tip.

## Round 3: branch tip `99b241da` (clean clone in the scratchpad, `git status` empty)

**Verdict: MERGE.** Nothing blocks.

- **M-11 fixed.** `results-summary.json` row reads 12609 / `7f278eda1162...`; recomputed from the committed bytes: 12609 / `7f278eda1162...`.
- **AS_RUN hashes: 18 of 18 match** the LF-normalised committed bytes. The `Bytes (raw)` column matches for 11 rows; for 7 (collect, final, part D, prepare, the three controls) it holds the CRLF size of the author's working copy (e.g. collect 10091) while the committed blob is LF (9783; `.gitattributes` sets `text eol=lf` on these paths) and a clean checkout yields the LF size. LOW, not blocking: the hashes are the certificate, and the header already says "as checked out"; a later edit could say "as written by the driver (CRLF)" or drop the column.
- **CHANGES.md** at `99b241da` names none of the three held files (0 hits).
- **M-3, M-4, M-7, M-8, M-9 committed** at `b3e7cfe1`: no `16:50:xx`; the build-revision source names the screenshot and says the records carry no build number; SPEC's `__MACHINE__` sentence, runner name and JSON file name corrected; the gate review committed and anchored (`scripts/publicignore_anchors.txt:33`); D1-11 row reworded.
- **Public-snapshot lock:** `tests/security/test_public_snapshot_excludes_private_material.py` 151 passed in the clean clone (the two round-1 failures included).
- **Scripts:** `rewrite_sid_domain.py --check` 0; `research_tracker_lock.py --check` 0; `verify_disposition.py` 45 of 45. `scrub_public_identifiers.py --check` reports 1 finding in the clone, which is the ratchet's own "main does not resolve in this checkout" line (the clone has no `main` ref); in the worktree at the same `99b241da`, clean index, it reports 0 findings in 4179 tracked files.
- The committed copy of this review is byte-identical (LF) to the primary-checkout file before this section was appended.
- M-5, M-6, M-10 remain as recorded: provenance prose, none changes a number a reader acts on.

Suites run at `99b241da`: the lock file above and the four scripts (clean clone, LOCALAPPDATA redirected); the scrub check additionally in the worktree. The standing gate was not run by this reviewer; the author's figure at `dff247de` is theirs.
