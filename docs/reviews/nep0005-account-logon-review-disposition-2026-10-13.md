---
title: "NEP-0005 matrix account-session redesign (password reset and logon): independent review, finding disposition"
status: closed
area: reviews
date: 2026-10-13
---

# account-session redesign review disposition (#1763)

**Subject:** the redesign that makes the matrix run its account-side probes as the throwaway account `blarai-spike` through a fresh in-memory password and restore the original task
credential at the end of every session (the Lead Architect approved the design on 2026-10-13, #1763 comment 4080). Four review rounds by an independent agent: round 1 FAIL (A1 to A12),
round 2 PASS (B1 to B7 new), round 3 PASS (go for `-SelfTest -WriteProof`), round 4 PASS (the stamp fix). Review files (main checkout, `docs/reviews/`):
`review-nep0005-account-logon-1763-2026-10-13.md`, `-rev2-`, `-rev3-`, `-rev4-` with the same suffix.

**Fix commits:** `0654307a` (the redesign and the fixes for A1 to A12 and B1 to B7) and `716fd87a` (the stamp fix). Checked on disk: at `0654307a` the matrix, run-lib, lib and README hash to the
round 3 values (`6890f7bc`, `f26bf6fa`, `b36ce223`, `1fdf15f4`), so the reviewed files are the committed files. Round 4 reviewed the delta that became `716fd87a`.
The redesign has been run live only as far as the first `taskcheck` (the round 4 review read the live restore as consistent); halfset, ours and n1 phases with the real account logon are not claimed here.

## Disposition

```disposition
A1-restore-child-cannot-load-convertto-securestring-under-pwsh-7 | FIXED | 0654307a spike-nep5-run-lib.ps1 Start-Nep5Child and New-Nep5StartInfo launch spike-provision with the parent environment where only PSModulePath is replaced by Get-Nep5ProvisionEnvironment (the Windows PowerShell value); the matrix resets its own PSModulePath under 5.1; self-test runs the real launcher against a stand-in calling ConvertTo-SecureString, with a lock-off control on the old shape; round 2 reproduced both
A2-refused-session-deletes-the-session-open-record | FIXED | 0654307a spike-nep5-run-lib.ps1 the OwnsRecord flag means Close deletes the session record only if this Enter wrote it and never reports TaskRestored; the -Remove branch forces the re-provision when the record exists; round 2 drove three runs after a simulated crash
A3-account-child-receives-the-operators-whole-environment | FIXED | 0654307a spike-nep5-run-lib.ps1 Get-Nep5AccountEnvironment (twelve allowlisted names, profile and temp inside the account folder) and New-Nep5AccountStartInfo clear the inherited block; Test-Nep5ChildEnvironment refuses a secret-looking name; round 2 observed a real child seeing exactly those names
A4-exception-in-the-taskcheck-body-loses-the-verdict | FIXED | 0654307a spike-nep5-run-lib.ps1 Invoke-Nep5TaskCheck has a catch (class inconclusive) so the session-exit record sets the class; round 2 driver gave exit 9 with one results file
A5-check-blind-to-an-unproven-session | FIXED | 0654307a spike-nep5-matrix.ps1 Invoke-Check reads the session record through Get-Nep5CheckSessionOpen (unreadable counts as open) and the task last-run result, and Get-Nep5CheckExit returns 21 for either; round 3 mutation N7 caught
A6-nothing-edits-the-task-check-can-never-fire | FIXED | 0654307a spike-nep5-matrix.ps1 Find-Nep5Commands matches command names through the parser CommandAst with a lock-off control; round 2 mutation R19 (a real Set-ScheduledTask call) caught
A7-real-os-actions-untested-and-the-password-write-by-name | FIXED | 0654307a spike-nep5-run-lib.ps1 lookup by Get-LocalUser -SID and the one write by Set-LocalUser -SID, pinned by a parser check (exactly one account write, inside New-Nep5AccountOps, by SID); start-info flags and probe re-hash pinned; round 2 mutations R7 R8 R18 caught
A8-restore-preconditions-checked-after-the-irreversible-step | FIXED | 0654307a spike-nep5-run-lib.ps1 ProvisionDryRun runs spike-provision -DryRun through the verified launcher before the session record and before the password, fail-closed when unwired or non-zero; a parser check pins the order; round 2 mutations N4 N5 N11 caught
A9-spike-provision-effects-beyond-restore-and-unhashed-inputs | FIXED | 0654307a spike-nep5-run-lib.ps1 Test-Nep5ProvisionDependencies re-hashes spike-provision.ps1, spike-lib.ps1 and the two copied files immediately before every start in -Run and -Remove; scripts README Accepted residuals lists the effects
A10-secret-scan-covers-success-paths-only | FIXED | 0654307a spike-nep5-matrix.ps1 the secret scan covers the write-failure, no-start, hang and failed re-provision phases plus a positive control; round 2 mutation R6 caught
A11-readme-control-characters-stale-counts-and-stale-prose | FIXED | 0654307a scripts README rewritten with no backspace or carriage-return bytes (scan is empty), eight scripts, the v2 baseline name, launcher and environment sections; DryRun rollback step 4 and the run-lib and probe headers corrected
A12-nits-dead-switches-vacuous-asserts-5-1-abort-normaliser-gaps | FIXED | 0654307a spike-nep5-run-lib.ps1 dead NoStartCheck and ForceReprovision switches removed; vacuous TaskOps.Sets asserts replaced; the 5.1 abort counted as a failure; every Settings child compared by the normaliser
B1-self-test-runs-the-real-password-write-behind-a-function-shim | FIXED | 0654307a spike-nep5-matrix.ps1 the parser check Test-Nep5SetPasswordWrite runs first, the test requires both command names to resolve to module-less Functions, and it uses the stale SID that does not resolve; round 3 mutations B1-V1 V2 V3 stopped before the write
B2-self-test-writes-into-the-real-account-work-folder | FIXED | 0654307a spike-nep5-matrix.ps1 the real-child environment check uses the stand-in root srRoot and the pure checks a fictitious Z: root; round 3 listing of the real work folder was identical before and after
B3-timeout-kill-reaches-only-the-immediate-child | FIXED | 0654307a spike-nep5-run-lib.ps1 the child wrapper Kill also runs taskkill /PID /T /F; self-test shows a grandchild killed within the limit; mutation B3m caught
B4-normaliser-treats-security-relevant-task-parts-as-changed-by-re-registration | FIXED | 0654307a spike-nep5-run-lib.ps1 normaliser compares every Principals child, the security descriptor and Actions Context; round 3 showed each change compares different while a Date Author Description change compares equal; mutation B4m caught
B5-taskcheck-connect-step-records-no-launch-and-no-way-out-of-a-permanent-refusal | FIXED | 0654307a spike-nep5-run-lib.ps1 the taskcheck connect step records launch (line 1064) and scripts README gives the by-hand procedure to clear a permanent refusal
B6-matrix-rewrites-psmodulepath-for-the-callers-console | FIXED | 0654307a spike-nep5-matrix.ps1 the entry point restores the original PSModulePath in its finally and on the argument-error exit (n5mpOrig); mutation B6m caught
B7-entry-point-wiring-of-three-fixes-is-unlocked | FIXED | 0654307a spike-nep5-run-lib.ps1 New-Nep5ProvisionSeams, spike-nep5-matrix.ps1 Resolve-Nep5RemoveTask and Get-Nep5CheckSessionOpen move the wiring into functions the self-test drives; round 3 mutations N7 N8 N9 N10 N11 N9b caught
Stamp-taskcheck-record-compared-as-a-string-after-a-json-round-trip | FIXED | 716fd87a spike-nep5-run-lib.ps1 ConvertTo-Nep5InstantSeconds and Test-Nep5TaskcheckMarker compare the stamps as instants truncated to the second (found by the first live use, then reviewed in round 4); mutations S-a S-b S-d S-e S-f S-g caught
Rev3-residual-taskkill-tree-may-include-an-unrelated-orphan-and-account-descendants-unproven | REJECTED | The reviewer rated it low and not a blocker: it fires only on a timeout, the direct child is killed through the full-access handle regardless, and whether taskkill reaches the account descendants only a real logon can show; a job object with kill-on-close is the exact form if a timeout ever leaves one.
Rev4-note-1-both-stamps-unreadable-case-not-asserted | REJECTED | Both stamps cannot be unreadable at once in a real run: the run side comes from the written time of a validated proof, so the survived mutation S-c changes no reachable behaviour, and each side alone is already asserted to refuse.
Rev4-note-2-two-proofs-in-the-same-second-count-as-one | REJECTED | A proof takes minutes to write and replaces the previous proof file, so two distinct proofs inside one second cannot occur in practice, and the one-second truncation is what lets the stamp survive the JSON round trip.
Rev4-note-3-stamp-regression-caught-only-by-a-pwsh-7-self-test | REJECTED | The scripts README already directs the self-test and the proof write to PowerShell 7 (lines 6 and 95), which is the host that reproduces the string regression.
Rev3-live-preconditions-secondary-logon-start-and-provision-from-the-matrix | REJECTED | These were stated as untested live, not as defects, and the README says so; the first taskcheck since ran spike-provision from the matrix and the round 4 live read found the restore consistent (password set 10:27:04, task result 0x00000000, no session record).
Rev3-operator-owned-empty-work-appdata-folder-left-by-round-2-self-test-runs | FIXED | The two empty directories under the account's work folder (AppData and AppData/Roaming) were removed by the redeploy step in the session that committed 716fd87a, after a read confirmed them empty; they reappeared once from a reviewer run and were removed again at the 10:44 redeploy; a recursive listing afterwards showed only `tmp`; the self-test now fingerprints that folder before and after (fix in 0654307a, B2).
```

## Honest limit of this record

The verifier checks the form of this record, not whether a fix is right. FIXED means the named function or line was read in the committed file and the reviewer's later round caught a
removal of it, except B5 and A11, which were verified by the reviewer by read and scan. The real secondary-logon start of the account's 5.1 child with the full session (halfset, ours, n1)
has not been run live, and the round 4 read covers the taskcheck phase only.
