---
title: "Disposition - independent review of the #1755 nono 9P control, rounds 1 and 2"
date: 2026-10-15
review_of: "docs/reviews/review-1755-nono-9p-control-2026-10-14.md on feat/1755-nono-9p-control (round 1 at 73086d4c, round 2 at ded319d1)"
reviewer: independent (author is not the verifier; round 2 reproduced the fixes by mutation)
---

# Disposition - #1755 review, rounds 1 and 2 (2026-10-15)

R1-4 and R1-6 are reading rules for the live record, not defects with a code fix; they are recorded as REJECTED with the rule stated.

```disposition
R1-1-started-rule-no-lock | FIXED | dcd4b3f9 - not-started rows run exit 0/1/2/127 with no banner per probe (120 checks); round-2 mutations M04b and M04c fail 90 checks each
R1-2-live-plumbing-modes | FIXED | 804651ad - M10, M11, M19, M20 caught in round 2; M12 closed here: --self-test runs prepare_windows, preflight_windows and cleanup_windows against a temporary fixture, and a runner that denies everything must fail the pre-flight (exit 1); with the expectation read from the result, that check fails
R1-3-supersession-evidence-wording | FIXED | 6d5abe0f - README 2026-10-12 section supersedes on the 500-character limit and the kernel/WSL move and says plainly it is not evidence the sandbox failed to start
R1-4-started-means-banner | REJECTED | A hypothesis that cannot be reproduced without nono; it is a reading rule: a case with W_IN and L_IN both denied is read from its output tails before it is counted. Round 2 applied it: all 63 OVERDENIAL and 222 DENIED rows carry the inner command's own error, 0 DENIED rows without the banner.
R1-5-fixture-name-gate | FIXED | dcd4b3f9 - the name gate runs on --live, --preflight-windows, --dry-run and load_prepare, with the trailing-newline form closed (round-2 mutations G1 12 failed, G2 12, G3 4)
R1-6-strict-unexpected-entry | REJECTED | The strict direction is the design: an unexpected entry in an ungranted folder must route to the private-advisory notice, never to a clean result. The entry is named on the row and the notice says "or an ungranted folder changed"; the rule for the live run is that the fixture folder is not shared with Explorer.
R1-7-env-facts-empty | FIXED | dcd4b3f9 - command_fact reads "missing" for an absent, silent or failing command (round-2 mutation F1 3 failed)
R1-8-ads-stream-wsl-sweep | REJECTED | Nothing in the matrix writes to the ads_stream stream (ADS_W creates a new stream name), so no verdict depends on the WSL-side sweep reading it; the Windows-side sweep compares it and runs at --cleanup-windows.
R2-1-abort-lock-cannot-fail | FIXED | 804651ad - a matrix that aborts after judged rows (20 faithful runs, then timeouts) must read INCONCLUSIVE in the record and exit 4; with conclude passing aborted=False the record check fails, with run_live returning the conclusion's code the exit check fails
R2-2-volume-serial-published | FIXED | 804651ad - the script records only dir /x entry lines; the self-test builds a real fixture and fails if the record carries the volume header; both banked run JSONs redacted, original and redacted sha256 recorded in the README
R2-3-list-claim-from-stored-fields | FIXED | 804651ad - the README says the list-verdict claim is inferred and adds the limit that piped rows do not store stdout
R2-4-not-granted-wording | FIXED | 804651ad - the log reads 30 operations, 27 of them not granted in at least one configuration
R2-5-no-disposition-record | FIXED | this file, checked by scripts/verify_disposition.py
R2-6-merge-conflict-performance-log | REJECTED | Not a defect in the branch: both sides prepend at the same line, and the resolution (keep both, the #1755 entry above main's two 2026-10-13 entries) is made at merge time by whoever merges; the reviewer's scratch merge shows it resolves with nothing else conflicting.
```
