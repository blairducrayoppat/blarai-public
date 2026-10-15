# Disposition: independent review of the #1740 phase-1 interim before merge

**Review:** an independent adversarial-reviewer agent that did not write the change, 2026-10-10 about 22:45 -04:00. It
reviewed branch `docs/1740-containment-comparison` at `5d41ba97` over `docs/1739-adr045-appcontainer-alternatives`
`712d8411`, in an elevated shell. It re-ran `analyse.py` (byte-identical to the banked summary) and `effective_access.py`
(every mask and SDDL matched the banked inventory). It re-ran `deny_ace_check.py`, then reproduced the deny-entry finding
with a real `CreateFileW` under the AppContainer token. It ran `wfp_fence.ps1 -SelfTest` (0 failures) and `-DryRun`,
including the operator SID as target (refused). It read every phase-2 script without arming any of them and checked the
raw data for credentials (none). A first reviewer attempt stopped on a billing error before reporting.
**Author of the change and of this disposition:** the #1740 session.
**Outcome:** one blocker and nine further findings; the reviewer then verified the fixes (blocker verified fixed, no recommendation left in the summary) and raised eight follow-ups, seven fixed in `cd9f75c6` and one rejected below. A second verification round confirmed all of them and raised one reproducibility nit, fixed in `590ead67`. All were fixed in `9a487a43`, except one design item deferred to
phase 2. That item needs a decision the Lead Architect owns.

```disposition
finding-1-blocker-interim-gives-the-restricted-token-verdict-the-LA-forbade | FIXED | 9a487a43
finding-1b-fence-on-the-synthetic-sid-cannot-discriminate-inverse-permit-construction | DEFERRED | #1740 blocked-by: the #775 flip AND the LA accepting, at phase 2, a hold-time block naming the operator and the synthetic SID under an operator permit (exposure: the operator's own traffic, watchdog-covered; wfp_fence.ps1 refuses the operator SID by design); the construction is written into report section 6
finding-2-openai-writeup-listed-as-read-but-banked-file-says-not-read | FIXED | 9a487a43
finding-3-codex-cap-sid-format-settled-and-repo-root-write-grant-missed | FIXED | 9a487a43
finding-4-appcontainer-read-reach-stated-as-measured-and-program-files-inconsistent | FIXED | 9a487a43
finding-5-arm-a-column-is-a-model-and-its-validation-was-overstated | FIXED | 9a487a43
finding-6-toolchain-location-and-launch-instrument-move-with-the-arm | FIXED | 9a487a43
finding-7-analyse-scores-errors-and-absences-as-agreement-and-picks-the-newest-inventory | FIXED | 9a487a43
finding-8-1742-upper-bound-unreliable-and-hazard-unstated | FIXED | 9a487a43
finding-9-no-egress-block-rests-on-firewall-cmdlets-and-codex-script-not-banked | FIXED | 9a487a43
finding-10-teardown-guard-tautological-perf-log-token-wording-no-timings-json | FIXED | 9a487a43
verify-D-deferral-exposure-overstated-block-can-name-operator-and-synthetic-sid | FIXED | cd9f75c6
verify-E-b3-not-wired-into-inventory-analysis-or-fixtures | FIXED | cd9f75c6
verify-F-section-9-omits-b3 | FIXED | cd9f75c6
verify-9-leftover-offline-account-has-no-egress-block-sentence | FIXED | cd9f75c6
verify-header-item-1-still-reframes-the-question | FIXED | cd9f75c6
verify-journal-plain-summary-lacks-the-counterweight | FIXED | cd9f75c6
verify-deny-entry-wording-too-broad-user-sid-deny-still-refuses | FIXED | cd9f75c6
verify2-analyse-default-run-differs-from-banked-summary-flag-unrecorded | FIXED | 590ead67
post-merge-teardown-failed-on-read-only-git-objects | FIXED | 23a4aa8c
post-merge-review-readonly-retry-could-follow-a-link-target | FIXED | 629c20ae
verify-openai-quotes-two-unverifiable-after-snapshot-deletion | REJECTED | the lead session read the full article text before deleting its scratch copy and the two quotes are verbatim from it; the reviewer verified the other two against the snapshot and found them exact; re-banking the article itself would store a copyrighted work in the repository, so the read record keeps the citation and short quotes only
```

Notes on fixes that also live off the branch: the corrections for findings 3, 8 and 9 were also posted on the tickets at
the event: #1742 comment 4021 and #1743 comment 4022. Finding 7's rule now lives in `analyse.agrees()`, checked on eight
cases including error, absent and undeletable outcomes. The phase-1 summary was regenerated with the inventory pinned by
name and is unchanged apart from naming it.

After the merge, the first real teardown of the fixtures failed on a read-only git object (the payload's task repos). The fix and the reviewer's nit on it are the two post-merge rows; the reviewer verified the handler deletes nothing outside ROOT.
