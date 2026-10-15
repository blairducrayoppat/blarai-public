---
title: "Track B arm 3b record: independent review, finding disposition"
status: closed
area: reviews
date: 2026-10-12
---

# Track B arm 3b record: review disposition

**Subject:** branch `feat/1682-arm3b-run` at `6b98e8b7` (the arm 3b result files, claims row C10, handoff, as-run record, journal fragment and the one script change that lowered the arming script's idle floor from 30 to 2 minutes for the run), reviewed by an independent agent on 2026-10-12. Verdict of the review: block on nothing security-relevant; the run's evidence is sound and sanitised; three findings required before merge. Ten findings, numbered as in the review's list.

**Fix commit:** `8940b398`. The bundle test passes at it (92 passed, LOCALAPPDATA redirected). The reviewed numbers in the result files were checked by the reviewer against the raw JSON and all matched.

## Disposition

Finding 1 (the test pin mandated the weakened floor while the prose called it a one-run exception): the decision is that it was a one-run exception, so the floor is restored. Finding 2's fix is code that can only be shown to work by another run, so it is ticketed with that predicate. Finding 10 is outside this diff and on main.

```disposition
F1-the-test-pin-mandated-the-lowered-idle-floor-while-prose-said-one-run | FIXED | 8940b398 spike-arm3b-arm.ps1 has the 30-minute floor again (Test-ArmArgs, its self-test and the header), the bundle test pins $Idle -lt 30, and AS_RUN.md, ARMS_HANDOFF.md and the journal say the 2-minute value was for this run only and that the bundled script is not the as-run file
F2-the-arming-steps-record-is-never-written-on-the-success-path | DEFERRED | #1761 blocked-by: #1682 (the next arm 3b run decision); the C10 not-measured column and the handoff now state that idle seconds at the gate, the countdown record, the pre-arm baseline, the shutdown exit code and the veto task deletion are unrecorded (8940b398)
F3-inferred-facts-presented-as-records | FIXED | 8940b398 the countdown, the veto registration and the restart command are marked inferred in the C10 row and the handoff; the 16:42 check is replaced by a banked re-run (arm3-persist/runs/post-3b-verification.txt, 16:57, exit 20, 0 tasks)
F4-prose-that-outlived-the-code-30-minute-and-not-run | FIXED | 8940b398 DESIGN.md (the 3b not-run sentences), the NOT RUN headers of the arming, post-reboot and veto scripts, and scripts/README.md (the as-run command and the 2-minute note); the idle-gate header says 30 minutes, which is true again after F1
F5-comment-claims-the-veto-task-protects-unsaved-work | FIXED | 8940b398 the line 86 comment was part of the lowered-floor edit and the restored text does not say it; the script's lines 33 and 34 say the idle gate and the input watch are the only protection
F6-limits-sentence-says-the-block-is-gone-when-the-script-exits | FIXED | 8940b398 the sentence is scoped to the dynamic-session claims (C1 to C9) and names the persistent set of C10 and C10a as removed by key
F7-c6b-row-inconsistent-after-the-rewrite | FIXED | 8940b398 the C6b not-measured column now lists what C10 leaves open
F8-journal-summary-overstates-the-bitdefender-condition | FIXED | 8940b398 the plain summary says two of Bitdefender's five processes were up at the 88 s mark, and "booted at" replaces "restart at"
F9-decision-file-shows-an-absent-time-as-midnight | REJECTED | the file's decided_at is a date by the README's own specification (line 80 permits a bare date), and the time of the decision is recorded where it can be read, in Vikunja #1682 comment 4065; writing a clock time into the file would put an approximation into a record that does not need one, and the file expires after 14 days
F10-real-machine-sid-domain-committed-in-a-test-fixture | DEFERRED | #1762 blocked-by: #1762 (its first step reads scripts/check_public_mirror_sync.py and the public sync procedure for whether tests/security/test_containment_evidence_bundle.py, docs/performance/containment_probe_2026-10-10/summary-phase1.md and docs/research/windows-containment-comparison-2026-10/ are mirrored; the verifier found two more files holding the value, codex-installed/codex-accounts-effective-access.json and effective-access/effective-access-fixtures-20261010T221241.json, added to the ticket); the value is on main and pre-dates this branch
```
