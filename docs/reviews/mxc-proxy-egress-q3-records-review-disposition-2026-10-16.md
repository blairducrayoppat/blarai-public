---
title: "MXC proxy egress, Q3 and variant 4 finishing records: review disposition"
status: closed
area: reviews
date: 2026-10-16
---

# Q3 and variant 4 finishing records review: disposition

**Subject:** the records review rounds of 2026-10-16. Round 1 (`a57f2aef`, FAIL) reviewed the records at `2de6ae39`; round 2 (`b7bdd767`, PASS) reviewed them at `9c5f2965`. Round 1 had seven findings; round 2 had two non-blocking LOW items and one wording point on the correction appended to the variant 4 post-run review.

```disposition
R1-1-mxc-loopback-ownership-claims-wrong | FIXED | b1923fd5 rewrites PERFORMANCE_LOG.md variant 4 entry, the variant 4 JSON and the journal fragment: the constant package SID is the AppContainer SID derived from MXC-Loopback, MXC's own named loopback peer; verified in round 2 b7bdd767
R1-2-variant4-disposition-F4-deferred-for-nothing | FIXED | 06484a51 marks variant 4 disposition F4 FIXED, citing b1923fd5 and the offline derivation; verified in round 2 b7bdd767
R1-3-harness-sha256-note-crlf-claim-false-for-proxy-py | FIXED | b1923fd5 variant 4 JSON harness_sha256_note states the mixed working tree; verified in round 2 b7bdd767
R1-4-in-container-token-elevated-difference-unstated | FIXED | b1923fd5 records elevated true in 6 of 6 variant 4 runs against false in 6 of 6 Q3 runs; verified in round 2 b7bdd767
R1-5-changed-set-omits-launch-ps1-and-launch-standard-cmd | FIXED | b1923fd5 lists launch.ps1 and the new launch-standard.cmd in the changed set; verified in round 2 b7bdd767
R1-6-fragment-says-variant4-added-that-evening | FIXED | b1923fd5 journal fragment gives 07:25 EDT added and 07:58 run; verified in round 2 b7bdd767
R1-7-q3-disposition-F4-F5-deferred-to-a-file-outside-the-repo | FIXED | 06484a51 marks both rows FIXED by bebb33da with in-repo locations; verified in round 2 b7bdd767
R2-correction-wording-on-variant4-postrun-review | FIXED | 9c5f2965 names the verdict paragraph sentence and says the records are on this branch; verified in round 2 b7bdd767
R2-L1-fragment-records-line-says-all-four-deferred | FIXED | 77d81c2f journal fragment records line credits b1923fd5 and states finding 4 fixed
R2-L2-q3-disposition-F4-credits-wrong-commit-for-wfp-layer | FIXED | 77d81c2f Q3 disposition F4 credits bebb33da for the variant 4 entry and b1923fd5 for the ownership correction
```
