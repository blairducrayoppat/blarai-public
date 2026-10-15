---
title: "NEP-0005 open question 3 with srt-win's own command line: driver and candidate fixes, independent review, finding disposition"
status: closed
area: reviews
date: 2026-10-13
---

# srt-win command-line half-set driver review disposition (#1763)

**Subject:** `docs/research/containment-evidence-2026-10-05/nep0005-open-questions/srtcli/`. It contains:
- the live driver `srtcli-halfset.ps1`: srt-win's own install, status, wfp verify, re-install and uninstall against half-sets in sublayer S1, with after-uninstall checks;
- `Deploy-Srtcli.ps1`;
- the three candidate patches in `fix/`.

The Lead Architect approved srt-win's installer creating its own `srt-sandbox` account and its uninstaller removing it (#1763 comment 4095). The wider install footprint is recorded in comment 4096.

An independent Opus agent reviewed offline only, in six rounds:

| Round | Verdict | Findings |
|---|---|---|
| 1 | FAIL | F1 to F13 |
| 2 | PASS | R2-1 to R2-4 |
| 3 | PASS | R3-1 to R3-2 |
| 4 | PASS | the proof-stamp fix, one nit |
| 5 | FAIL | R5-1 to R5-2: the new ACL change classifier |
| 6 | PASS | two non-blocking notes |

All six rounds are in `docs/reviews/review-nep0005-srtcli-halfset-1763-2026-10-13.md`.

**Fix commits:** `70b9c877` (rounds 1 to 4; driver `819b4d9a`) and `7097fbec` (rounds 5 and 6; driver `baaa8764`). Rounds 5 and 6 followed the first live stock pass, which stopped on 577 changed access lists after srt-win's uninstall (#1763 comments 4099 and 4100); the classifier they review decides which such changes stop a run. `baaa8764` is the copy deployed for the counted live runs.

IDs: F1 to F13 and R2-1 to R5-2 are the review file's own labels. The review file does not number the round 4 nit or the three round 6 notes; R4-1 and R6-1 to R6-3 are this record's labels for them, in the order the review lists them. R4-0 is the defect the first `-Run` found at its own gate, fixed by the author and verified in round 4.

## Disposition

```disposition
F1-stop-on-refused-vector-or-hash-change-skips-uninstall | FIXED | 70b9c877 srtcli-halfset.ps1 one catch for every stop; srt-win uninstall runs once whenever installed; when it cannot run the record carries left_installed and the footprint and exits 10; self-test cases for a refused vector while installed and for srt-win's hash changing while installed; round 2 probe exit 10 uninstalls 1
F2-exit-10-unreachable | FIXED | 70b9c877 srtcli-halfset.ps1 not_clean_after_uninstall and left_installed exit 10; self-test asserts exit 10 exactly in five cases
F3-after-check-throw-runs-uninstall-twice | FIXED | 70b9c877 srtcli-halfset.ps1 Installed is cleared as soon as the uninstall command returns and the after-checks are wrapped (check_error, clean false); self-test case with a throwing footprint read asserts one uninstall and the error kept
F4-after-check-clean-without-sids | FIXED | 70b9c877 srtcli-halfset.ps1 sids_known false is never clean; SIDs reset per pass and re-read on the stop path; fake world gives fresh SIDs per install; the pass-2 failed-install case catches removal of the reset (round 4 confirmed)
F5-self-test-blind-to-four-mutations | FIXED | 70b9c877 srtcli-halfset.ps1 cases for an ACE left, a right left, delete followed by sweep, TS runner pointed at the build under test; round 2 re-ran the four mutations and each fails
F6-deploy-check-and-header-false | FIXED | 70b9c877 Deploy-Srtcli.ps1 rejects only non-admin allow entries carrying write, delete, permission, ownership or generic write/all rights on the destination and every subfolder outside node_modules; header says it prints hashes and that npm writes its cache under the profile; the deploy that produced the live copy ran this script
F7-typescript-tree-not-pinned-and-node-env-inherited | FIXED | 70b9c877 srtcli-halfset.ps1 NODE_* stripped from every child (round 2 observed it through the real launcher); whole-tree hash per TypeScript tree pinned and checked at preflight and before the first node call per tree, with self-test cases for both sites
F8a-sublayer-leftover-invisible | FIXED | 70b9c877 srtcli-halfset.ps1 export is netsh wfp show state (sublayers included) and the clean verdict needs S1, S2 and S3 counts of zero; a positive control per pass stops the run when the export cannot see the installed set; self-test cases for a blind export and a left sublayer
F8b-profile-left-blocks-later-passes | REJECTED | a profile left by srt-win's uninstall is a stop by design: gate stop condition "srt-sandbox not verified removed: report, do not hand-delete" (#1763 comments 4095 and 4096); clearing it would be our cleanup of srt-win's state, which the gate excludes
F9-store-dir-exclusion-matches-siblings | FIXED | 70b9c877 srtcli-halfset.ps1 the prefix carries the trailing backslash; self-test case keeps a sandbox-runtimeX sibling
F10-typescript-status-type-lacks-partial | FIXED | 70b9c877 fix/status-partial-consumer.patch adds 'partial' to WindowsWfpStatus and names an incomplete set in the dependency-check error; round 2 confirmed the three patches reproduce the patched tree
F11-allowlist-compares-joined-string | FIXED | 70b9c877 srtcli-halfset.ps1 element-by-element comparison; self-test case refuses a re-split vector
F12-no-ipv6-connected-control | FIXED | 70b9c877 srtcli-halfset.ps1 in-range verify on both families in states F and HP; self-test asserts both read connected in F
F13-raw-record-holds-machine-sids | FIXED | 099c05b6 srtcli/Export-SrtcliSummary.ps1 writes the only committed copy (runs/srtcli-results-summary.json) with every machine SID domain and the user name replaced and ACL example paths cut to the stamped directory, and refuses to write if either remains; the raw records stay in the admin-only output root (round 2 marked this ACCEPTED pending the banking review, which found no SID domain, user name or software path in the added lines)
R2-1-preflight-ignores-s2-s3 | FIXED | 70b9c877 srtcli-halfset.ps1 preflight refuses on export S2 or S3 counts other than zero
R2-2-five-new-locks-untested | FIXED | 70b9c877 srtcli-halfset.ps1 cases for a blind export, a left sublayer, pass-specific SIDs, the per-pass reset and both tree-hash sites; round 3 and 4 mutation runs fail each except the stop-path SID re-read, whose absence leaves the verdict not clean (argued by the reviewer, accepted)
R2-3-deploy-mask-misses-generic-rights | FIXED | 70b9c877 Deploy-Srtcli.ps1 GENERIC_ALL and GENERIC_WRITE in the mask and every subfolder checked; round 3 checked inherit-only GW, GA and CREATOR OWNER GA against SDDL-built ACLs
R2-4-header-lags-code | FIXED | 70b9c877 srtcli-halfset.ps1 header lists locks 6 and 7, the left_installed exception and the wider exit 10
R3-1-per-pass-sid-reset-untested | FIXED | 70b9c877 srtcli-halfset.ps1 case: pass 2 install fails after creating the account and leaves a right; removing the reset fails the self-test (author and round 4 both ran the mutation)
R3-2-tree-hash-checks-untested | FIXED | 70b9c877 srtcli-halfset.ps1 cases for a wrong tree at preflight (exit 3, no srt-win call) and a tree changed after preflight (stop at the first node call); removing either check fails the self-test
R4-1-empty-hash-pair-reads-fresh | REJECTED | the gate passes the SHA-256 of the running script file, which cannot be empty while the script runs, and the proof writer writes the same function's value; an empty pair needs an unreadable running script, at which point nothing reaches the gate
R5-1-classifier-ignores-ace-order-and-inherited-mark | FIXED | 7097fbec srtcli-halfset.ps1 ConvertTo-AceList keeps order and ID; with a deny on either side only identical ordered lists are equivalent and only an ordered subsequence with allows removed is narrowed; unit checks for the reviewer's three reorderings; round 6 re-ran them and seven further adversarial pairs, all other
R5-2-flag-and-creator-owner-mutations-survive | FIXED | 7097fbec srtcli-halfset.ps1 unit checks for a Users allow losing inherit-only and for an inheritable CREATOR OWNER full control added; round 6 confirmed both mutants now fail named checks
R6-1-deny-only-list-emptied-reads-other | REJECTED | a false positive in the safe direction: the run stops and reports instead of continuing; an uninstall that empties a deny-only access list is itself worth a stop and a look
R6-2-flag-format-check-mutation-survives | REJECTED | the check only rejects an odd-length flag field, which Windows' SDDL conversion never produces; its absence cannot hide a readable change because every other parse rule still applies
R6-3-owner-not-snapshotted | REJECTED | only the access section is snapshotted; in this run the sandbox account only performs loopback connects through srt-win's runner and writes no files, and its profile (the one place it owns files) is checked absent after every uninstall, so a file owned by the deleted SID has no producer here; the limit is stated in the run record
R4-0-proof-stamp-parsed-through-local-time | FIXED | 70b9c877 srtcli-halfset.ps1 Test-ProofFresh reads a round-tripped DateTime as UTC and a string as an offset; five self-test checks incl. the JSON round trip; found by the first -Run attempt, which refused before touching anything
```
