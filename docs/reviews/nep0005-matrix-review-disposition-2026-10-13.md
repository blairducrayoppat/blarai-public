---
title: "NEP-0005 open-questions half-set matrix scripts: independent review, finding disposition"
status: closed
area: reviews
date: 2026-10-13
---

# half-set matrix review disposition (#1763)

**Subject:** `spike-nep5-matrix.ps1`, `spike-nep5-lib.ps1`, `spike-nep5-run-lib.ps1`, `spike-nep5-connect-probe.ps1` and their README under
`docs/research/containment-evidence-2026-10-05/nep0005-open-questions/scripts/`, reviewed in three rounds by an independent agent (round 1 PASS with M1 to M13; round 2 PASS with
R2-1 to R2-5; round 3 PASS with R3-1). Review files (main checkout, `docs/reviews/`): `review-nep0005-matrix-1763-2026-10-12.md`, `-rev2-1763-2026-10-12.md`, `-rev3-1763-2026-10-13.md`.

**Fix commit:** `481713ee`. Checked on disk: at that commit `spike-nep5-lib.ps1`, `spike-nep5-run-lib.ps1` and the README hash to the round 3 values (`15780b73`, `5a63d955`, `a4b8a1f3`); the matrix
script differs from the round 3 hash by exactly the R3-1 change (`$FixedDir = $PSScriptRoot` at line 91), which round 3 asked for after it hashed the file. The account-session
redesign that later changed these files (`0654307a`, `716fd87a`) is dispositioned in the account-logon record, not here. The scripts have not run against the real engine in the state `481713ee`;
the account-side redesign superseded the task-retarget mechanism that rows M2 and R2-1 to R2-5 describe, and its live results are not claimed here.

## Disposition

```disposition
M1-run-removes-by-key-even-when-the-pre-cleanup-refused-or-stopped | FIXED | 481713ee spike-nep5-run-lib.ps1 Invoke-Nep5Phase sets Ctx.PreCleanupOk only after a successful pre-cleanup and Invoke-Nep5RunCore removes in its finally only when it is set; the matrix Invoke-Run no longer removes itself; README lines 46 to 47 state it; three run-core self-test checks drive the entry point
M2-account-task-restore-proven-by-argument-string-alone | FIXED | 481713ee spike-nep5-run-lib.ps1 task definition snapshot through Export-ScheduledTask with a baseline recorded before the first change, restore needs original arguments plus an equal definition plus a started task, otherwise class task_not_restored (exit 9, names the re-key command); superseded in mechanism by 0654307a which removed the task retarget altogether
M3-harness-arming-file-written-before-the-proof-failure-branches | FIXED | 481713ee spike-nep5-matrix.ps1 write-proof path stages the harness proof as a .staged file, validates the matrix proof against it, renames, and deletes what it wrote on both failure branches; Remove-Nep5StaleHarnessProof deletes an orphaned or older harness proof at the start of -Run and -Remove
M4-probe-and-harness-hashes-are-fresh-reads-not-the-proofs-values | FIXED | 481713ee spike-nep5-lib.ps1 Test-N5Proof returns ProbeSha and HarnessSha it verified and spike-nep5-matrix.ps1 Invoke-Run binds the runner and the probe copy to those; the dead line is gone; self-test check proof-hash-binding
M5-results-and-exports-overwritten-by-every-run | FIXED | 481713ee spike-nep5-run-lib.ps1 results go to nep5-results-phase-stamp.json with a counter if the name exists, exports under an exports-stamp folder (matrix line 366); self-test check asserts two runs write two files
M6-cycle-summary-line-omits-not-run-rows | FIXED | 481713ee spike-nep5-run-lib.ps1 the summary appends NOT RUN with the target keys when the list is non-empty
M7-exit-2-documented-as-nothing-was-added | FIXED | 481713ee spike-nep5-matrix.ps1 header and README line 59 now say the state that refused added nothing and earlier states of the same phase are in the record
M8-listeners-never-accepted-from-backlog-exhaustion | FIXED | 481713ee spike-nep5-run-lib.ps1 Clear-Nep5Backlog accepts and closes pending connections before the control and the during connects; self-test drives 450 connects in batches and shows the failure without the drain
M9-readme-omits-two-files-run-requires | FIXED | 481713ee scripts README line 17 and run order line 65 name spike-run-test.ps1 and spike_model.py
M10-proof-check-count-ceiling-is-a-line-prefix-regex | FIXED | 481713ee spike-nep5-lib.ps1 ceiling counts CommandAst nodes named Chk through the parser with slack 30 (line 1143); round 2 mutation with slack 0 failed the self-test
M11-fake-export-emits-sublayer-and-provider-elements-netsh-does-not | FIXED | 481713ee spike-nep5-lib.ps1 Get-FakeExportText emits filter items only (the sublayer GUID appears as a reference on a filter); README states sublayer and provider absence rests on the key reads
M12-n1-skips-the-control-step-but-docs-say-every-state-runs-it | FIXED | 481713ee spike-nep5-matrix.ps1 header line 22 says N1 has no step 2 because it makes no connects, and the README says the same
M13-remove-prints-not-verified-when-only-the-task-restore-failed | FIXED | 481713ee spike-nep5-matrix.ps1 -Remove reports the engine verdict and the task verdict on separate lines; an unproven task restore is exit 9 with the re-key line
R2-1-remove-never-changed-skip-and-baseline-depend-on-outdir | FIXED | 481713ee spike-nep5-run-lib.ps1 Get-Nep5TaskBaselinePath and the marker path use Ctx.FixedDir (the scripts folder), Test-Nep5TaskFileLocations makes a baseline or marker in OutDir that differs from the fixed one exit 9 task_files_mismatch; the never-changed branch needs no baseline, no marker and original arguments and never prints PROVEN; mutations P1 P2 P4 caught
R2-2-staged-harness-proof-survives-a-crash-as-a-valid-arming-file | FIXED | 481713ee spike-nep5-lib.ps1 Remove-Nep5StagedHarnessProof deletes every staged file beside the harness proof, called from -Run (matrix line 350), -Remove (line 206) and before staging in -SelfTest -WriteProof; mutation P3 caught
R2-3-no-documented-way-back-after-a-deliberate-re-key | FIXED | 481713ee scripts README line 54 and the Enter refusal text say to delete the baseline beside the proof and run taskcheck again after a deliberate re-key
R2-4-remove-tells-the-operator-to-re-key-a-task-never-retargeted | FIXED | 481713ee spike-nep5-matrix.ps1 -Remove prints the re-key line only when a baseline exists, otherwise says there is no baseline so it is not a re-key case; self-test check R2-4
R2-5-xml-normaliser-tested-only-on-a-hand-made-sample | REJECTED | The reviewer found nothing to fix: a wrong normaliser fails in the safe direction (exit 9, no phase runs) and README line 55 states the limit; the first live taskcheck settled it (restore consistent and a v2 baseline recorded at 10:27 on 2026-10-13 per the account review round 4), and 0654307a changed the normaliser, which the account review checked against the real exported task shape.
R3-1-fixed-location-follows-proofpath-not-the-script-folder | FIXED | 481713ee spike-nep5-matrix.ps1 line 91 sets FixedDir to PSScriptRoot, independent of ProofPath; the dead duplicate ProofPath default line is gone
Accepted-residual-harness-live-proof-is-form-only | REJECTED | The harness proof is documented as a seatbelt against a typo and not a lock against an administrator who knows the exe hash; the matrix proof is what binds a self-test to it, so no further control is added.
```

## Honest limit of this record

The verifier checks the form of this record, not whether a fix is right. FIXED means the named function or line was read in `481713ee` and the reviewer's later round attacked it with
a control-removal mutation that the self-test caught, except where the row says it was read only (M4, M5, M6, M7, M9, M11, M12 and M13 were not mutated by the reviewer). No
row claims the matrix has been seen working against the real engine.
