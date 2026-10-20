---
title: "MXC denied-subtree probe: pre-run review rounds 1 to 7 and the post-run review, finding disposition"
status: closed
area: reviews
date: 2026-10-15
---

# MXC denied-subtree probe: review disposition

**Subject:** the probe `tools/probes/mxc_denied_subtree/` on branch `feat/mxc-denied-subtree` and the records made from its live batch. Seven independent pre-run reviews, all in this folder:
`mxc-denied-subtree-prerun-review-round1-2026-10-15.md` (at `288cf104`, FAIL, two HIGH), `...-round2-...` (at `4abd6442`, FAIL, two HIGH), `...-round3-...` (at `42fd5f1c`, PASS, one MEDIUM),
`...-round4-...` (at `bd3694d6`, FAIL, one HIGH) and `...-round5-...` (at `b1cb40e3`, PASS after an addendum; the self-test closed at 167 passed, 0 failed on a quiet machine)), `...-round6-...` (at `261737de`, the fx-c variant, FAIL, one MEDIUM-HIGH) and `...-round7-...` (at `d1de3242`, PASS, 213 passed, 0 failed).

**Fix commits (BlarAI):** `4abd6442` (round 1), `42fd5f1c` (round 2), `ef422b21` (round 3, plus the smoke launch and UI lockdown off), `bd3694d6` (payload hang watchdog and a per-process self-test tree root; not a fix for a finding),
`b1cb40e3` (round 4; the harness the live batch used, approved by sha256 after round 5). `261737de` (the fx-c variant) and `d1de3242` (round 6 fixes; the harness for the Tier-3 attempt, approved by sha256 after round 7). Rows `R6-n` and `R7-n` follow each review's own numbering.
**Ticket:** #1797 (filed here: the open round-4 and round-5 residuals).
**Post-run review:** `mxc-denied-subtree-postrun-review-2026-10-15.md` (PASS, ten findings, rows `PR-1` to `PR-10`). Rows 1, 2, 4, 5 and 6 were applied to the operator's private register on 2026-10-15, which is outside this repository and has no commit here; they are recorded as REJECTED because there is nothing in this repository to fix, with the argument in the row. Rows 3, 7 and 10 are fixed in this repository by the branch named in their evidence. Rows 8 and 10 are also fixed in the public evidence repository: the README row was deleted and the allowDaclMutation wording changed in its commit `59dd344`, merged to its main as `9fa86af`.

Rows are `R<round>-<n>` by each review's own numbering. The self-test counts: 47 passed at `288cf104` (round 1), 95 at `4abd6442`, 123 at `42fd5f1c`, 142 at `bd3694d6`, 167 at `b1cb40e3`. The self-test was not run during or after the live batch.

```disposition
R1-1-hold-predicate-looser-than-fail-definition-high | FIXED | 4abd6442 whole-subtree equality (sub_changes) drives the stop and the verdict; extra files, changed rename source, move-in and streams now FAIL
R1-2-no-win32-error-for-create-append-s1-s3-high | FIXED | 4abd6442 every attempt is a Win32 call and its error is recorded; error text keeps 600 characters
R1-3-payload-that-never-ran-reported-refused | FIXED | 4abd6442 REFUSED only when dry_run_rc is nonzero; a launch with no report is LAUNCH-FAILED
R1-4-per-request-tier-recorded-not-compared | FIXED | 4abd6442 per-launch tier set in the summary, pre-launch stop on a tier mismatch, state change or leftover ACL becomes INSTRUMENT-BLIND
R1-5-hash-binding-missed-winsec-and-interpreter | FIXED | 4abd6442 winsec vendored, explicit python argument, interpreter sha256 recorded; the bytecode-cache gap was R2-5
R1-6-dacl-tier-toolchain-aces-uncaptured-and-restore-journal-deleted | FIXED | 4abd6442 state directory never deleted or redirected, toolchain ACL captured before and after, a DACL tier needs --allow-dacl-tier
R1-7-selftest-never-exercised-run-probe | FIXED | 4abd6442 end-to-end cases through run_probe.main with a fake launcher (FAIL open, HOLD held and others)
R1-8-append-and-delete-shared-one-marker | FIXED | 4abd6442 separate delete_me.txt
R1-9-move-in-rename-sub-streams-spellings-not-in-not-measured | FIXED | 4abd6442 added to the not-measured list; attribute and timestamp writes completed in R2-6
R1-10-smaller-items-tree-kept-after-stop-s5-gate-paths-host-prep-field | FIXED | 4abd6442 tree kept after a stop, s5 gated on a DACL tier, launcher and interpreter paths explicit, S3 and error codes in the summary, host_prep_ran field; the security-suite version residual is R3-8
R2-1-remove-privileges-silent-noop-high | FIXED | 42fd5f1c correct token-privileges layout, secure_token reads the token back and refuses if a guarded privilege stays enabled, the list is recorded in the header and every launch
R2-2-landing-with-no-report-labelled-launch-failed-high | FIXED | 42fd5f1c every launched record is judged, so a change wins over LAUNCH-FAILED
R2-3-snapshot-errors-silent-false-fail-and-blind-hold | FIXED | 42fd5f1c blind hold closed; the false FAIL remainder was R3-1 fixed in ef422b21, and the over-correction that followed was R4-1
R2-4-hold-did-not-check-refusals-were-refusals-of-the-deny | FIXED | 42fd5f1c HOLD needs Win32 error 5 on every refused attempt; codes 2, 3, 32 and 1920 give INSTRUMENT-BLIND
R2-5-bytecode-cache-outside-hash-binding | FIXED | 42fd5f1c pycache or any pyc refused by both entry points, python runs with -I -B and a pycache prefix; package-directory shadowing was R3-4
R2-6-attribute-timestamp-and-per-entry-acl-changes-not-compared | FIXED | 42fd5f1c attributes and file write times compared with the archive bit masked; per-entry ACL changes remain a stated bound
R2-7-tier-mismatch-stop-summarised-as-incomplete | FIXED | 42fd5f1c TIER-MISMATCH verdict with both tiers; the privilege-skip variant was R3-3
R2-8-ace-parser-appcontainer-scope-absolute-tool-paths | FIXED | 42fd5f1c conditional and callback ACEs refused, AppContainer registry check scoped to the container id, system tools by absolute path
R3-1-host-read-error-still-yields-false-fail-medium | FIXED | ef422b21 unreadable entries are INSTRUMENT-BLIND; the over-correction this introduced was R4-1
R3-2-directory-last-write-time-dropped-on-false-premise | REJECTED | A create-then-delete inside the subtree is visible only in the directory write time, but that gap can only hide a change from a FAIL and can never make a HOLD wrong in the unsafe direction when the five named attempts are also judged, and it is now stated as a bound in landing.py and in the not-measured lists of the records, so the limit is on record where a reader looks.
R3-3-privilege-refusal-summarised-as-incomplete | FIXED | ef422b21 INSTRUMENT-BLIND with a reason in the record shape run_probe writes
R3-4-package-directory-or-extension-module-shadows-hashed-module | FIXED | ef422b21 launch.ps1 and run_probe.py refuse any directory or non-py and non-ps1 entry in the probe folder
R3-5-token-locks-pass-vacuously-under-non-elevated-runner | REJECTED | The privileges are absent in the binding context, so a non-elevated runner cannot exercise the removal; the control rests on the round 2 elevated fixture and on the live batch, whose header records the four guarded privileges disabled and read back, so the residual is stated and the live evidence is the check.
R3-6-code-5-rule-stricter-than-the-specification | REJECTED | The native Tier 1 deny error code is undocumented, so requiring error 5 can turn a different refusing code into an INSTRUMENT-BLIND run but never into a false HOLD; stricter fails toward no result, and the rule is documented in the summarise.py docstring in ef422b21; all 15 live refusals were error 5.
R3-7-not-measured-list-missed-per-entry-acls-change-time-archive-bit | FIXED | ef422b21 added, with the directory time and the write-data open, and the stale sentence corrected
R3-8-security-suite-record-lacked-versions-and-bitdefender | FIXED | ef422b21 Bitdefender and its version are recorded; Defender version stays null and the stale McAfee entry is stated as such in the records
R4-1-skipped-paths-hide-existence-evidence-high | FIXED | b1cb40e3 an entry that appears or vanishes in a successful listing counts as a change and a landing regardless of readability; round 5 confirmed FAIL in cases A to D and the end-to-end hiddenland case
R4-2-host-read-errors-invisible-with-no-report-stop-line-says-unchanged | FIXED | b1cb40e3 INSTRUMENT-BLIND with a named reason and a stop line that names the read error
R4-3-ui-lockdown-off-departs-from-the-policy-line | DEFERRED | #1797 blocked-by: a ruling line on #1797 from the case owner on whether a UI-lockdown-on run is wanted; until then every record states the departure and lists UI lockdown on as not measured
R4-4-smoke-launch-state-change-summarised-as-incomplete | FIXED | b1cb40e3 STOPPED-STATE-CHANGE verdict and a smoke_state_changed field
R4-5-container-payload-broken-covers-launcher-failures-and-stale-prose | FIXED | b1cb40e3 smoke records carry a cause (payload-import-failure, launcher-timeout, no-report) and the prose is updated
R4-6-e2e-tiermismatch-lock-lost-its-subject-and-dead-line | FIXED | b1cb40e3 dead line removed and a tiermeasured fake mode reaches the per-launch branch
R5-1-unattributed-only-fail-reads-like-a-bypass | DEFERRED | #1797 blocked-by: tools/probes/mxc_denied_subtree/summarise.py verdict and stop lines mark unattributed_changes, with a re-approved hash list; no wrong HOLD is possible from it and the FAIL is kept so evidence is not hidden
R5-2-authenticode-check-timeout-crashes-harness-under-load | DEFERRED | #1797 blocked-by: tools/probes/mxc_denied_subtree/fixtures.py Get-AuthenticodeSignature call returns a record or a named blind reason on timeout; it fails loud and launches nothing so no verdict can be wrong
R5-3-nonelevated-runner-reports-exit-0-for-a-dead-child | DEFERRED | #1797 blocked-by: run_nonelevated.ps1 (outside the probe) returns the failure of the child, or the probe README says to read the self-test closing tally; the closing tally was read for round 5 approval
PR-1-psec-version-causal-claim-contradicted-medium | REJECTED | Applied in the operator's private register (case-1 entry), 2026-10-15; the register is outside this repository and holds no text here to change. This repository's three records (log entry, JSON, journal fragment) now say the logged PSEC version is a per-launch reading of the policy launched, never a host property, in fix/mxc-denied-subtree-records
PR-2-psec-advertised-deny-support-never-read-medium | REJECTED | Applied in the operator's private register, 2026-10-15; the sentence about PSEC advertising deny support is in the register only, and no record in this repository makes that claim (the log entry reports the launcher flag baseContainerSupportsDenyPaths and says the vendor document was not re-read)
PR-3-process-sandboxes-count-of-absence-sentinel-medium | FIXED | fix/mxc-denied-subtree-records the JSON key is process_sandboxes_key with two absence entries, checked against the raw header.json of the second run folder
PR-4-second-launcher-commit-stated-as-fact-low | REJECTED | Applied in the operator's private register, 2026-10-15; the attribution sentence is in the register only, and this repository's records state the second launcher by its sha256 and call it probed only
PR-5-ui-lockdown-reads-causal-low | REJECTED | Applied in the operator's private register, 2026-10-15; the causal parenthetical is in the register only, and this repository's log entry lists UI lockdown on as not measured and says the first attempt stopped for the container Python failing to load ctypes
PR-6-register-status-stale-and-operator-only-launch-claim-low | REJECTED | Applied in the operator's private register, 2026-10-15 (STATUS and the launch attribution); register text only, no record in this repository carries either sentence
PR-7-windows-itself-enforces-stated-as-fact-low | FIXED | fix/mxc-denied-subtree-records the plain summary now says the tier the vendor documents as enforced natively by Windows
PR-8-run-verdict-row-has-no-raw-source-low | FIXED | fix/mxc-denied-subtree-records the row was deleted from the public README results table (evidence repository commit named above); this repository's records state only the batch verdict
PR-9-summarise-ui-lockdown-constant-low | DEFERRED | #1797 blocked-by: tools/probes/mxc_denied_subtree/summarise.py reads ui_lockdown from each record's config.ui instead of the constant False, with a re-approved hash list; no effect on this batch where lockdown was off in every record
PR-10-allowdaclmutation-value-not-stated-low | FIXED | fix/mxc-denied-subtree-records the log entry and the JSON say absent in the submitted policy and resolved true in the launcher's log; the public README says the same (evidence repository commit named above)
R6-1-failed-fx-c-launch-with-state-left-summarised-as-launch-failed-medium-high | FIXED | d1de3242 state_left is evaluated over every launched record, failed launches included; round 7 reproduced STOPPED-STATE-CHANGE with synthetic records and the self-test case t3failleft passes
R6-2-smoke-launch-cleanup-unchecked-medium | FIXED | d1de3242 run_smoke captures ACLs before the launch and compares after it and applies state_left for fx-c; self-test case t3smokeace; the live smoke launch of the third run folder was read by it as STOPPED-STATE-CHANGE
R6-3-toolchain-acl-restored-compared-root-only-medium | FIXED | d1de3242 python.exe is captured per launch and the whole toolchain tree is saved with icacls at batch start and end (22744 objects in the third run folder, no difference); self-test case t3tcchild
R6-4-host-prep-detector-looser-than-its-question-low | FIXED | d1de3242 sddl_has_host_prep requires both SIDs with mask 0x00120088, non-inherited and allow; wrong mask, inherited, deny and one-SID cases are rejected by the self-test
R6-5-batch-holds-no-evidence-of-host-prep-low | FIXED | d1de3242 the header records host_prep_evidence at start and end, with the system-drive root SDDL and the detector result, and host_prep_ran is derived from them
R6-6-docstring-prose-not-caught-up-with-fx-c-low | FIXED | d1de3242 the not-measured list names no denial capture, three variables changed together and the null-device prep state; the remaining stale sentences are R7-3
R6-7-sddl-readers-disagree-on-ace-order-info | FIXED | 763e1952 the operator command sequence in the round 6 and round 7 review files compares the SDDL set-wise
R7-1-per-launch-acl-comparison-order-sensitive-low | DEFERRED | #1797 blocked-by: tools/probes/mxc_denied_subtree/fixtures.py same_acl compares ACE sets and not the ordered list, with a re-approved hash list; it can only add a false stop, never hide a change, and the record shows the before and after SDDL
R7-2-created-or-deleted-toolchain-object-reads-as-acl-change-low | DEFERRED | #1797 blocked-by: tools/probes/mxc_denied_subtree/summarise.py names an object only at one end of the toolchain saves as such in the verdict line and state_left, with a re-approved hash list; incidence zero in the live batch (22744 objects at both ends) and the differences list already carries the text only at end
R7-3-docstring-prose-still-describes-round-5-behaviour-low | DEFERRED | #1797 blocked-by: the summarise.py verdict table and the run_probe.py SMOKE LAUNCH paragraph state that a smoke launch that also left state stops with STOPPED-STATE-CHANGE, with a re-approved hash list; prose only, and a docstring edit changes the approved sha256 of two files
R7-4-uncaught-exception-skips-end-of-batch-records-info | REJECTED | The pattern predates this change and a traceback is loud, so nothing is presented as a value; the batch files already on disk (start save, per-launch records) stay readable and no verdict can be wrong because none is written.
R7-5-icacls-save-records-dacls-only-no-owner-info | REJECTED | The vendor documentation does not describe MXC changing owners and the root and python.exe owners are compared per launch; an owner change on a descendant is a stated bound of the instrument, and the third run folder shows no difference in the toolchain DACLs.
```

## Reading the table

- Every FIXED row names a commit on this branch. The three REJECTED rows of rounds 3 to 5 and the two of round 7 are argued bounds that cannot make a HOLD wrong in the unsafe direction; the five post-run REJECTED rows are register text outside this repository.
- The eight DEFERRED rows (the post-run PR-9 and R7-1 to R7-3 included) are all in #1797 and none can produce a wrong HOLD (R7-1 and R7-2 can only add a false stop); R4-3 is closed by a ruling, the others by the observable changes named in their predicates.
- Round 6 withheld approval for the fx-c variant (`261737de`); round 7 approved `d1de3242` and the Tier-3 attempt ran under it (see the journal fragment 2026-10-15_mxc-denied-subtree-tier3-attempt).
- Round 5 withheld approval on the first self-test run (a timeout in its third end-to-end case, 148 passed and 0 failed printed) and approved on a complete run, 167 passed, 0 failed; the approved hashes are the eight in `docs/performance/mxc_denied_subtree_2026-10-15.json`.
- The first round question whether `baseContainerSupportsDenyPaths` faithfully reads the OS capability was answered yes for the main build and inferred from documentation for v1.0.0; the records say so.
