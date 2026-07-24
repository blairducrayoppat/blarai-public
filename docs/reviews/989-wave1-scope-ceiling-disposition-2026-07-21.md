---
title: "Disposition — independent review of e56138a0 + fix rounds (#989 wave-1 scope ceiling)"
date: 2026-07-21
review_of: "feat/989-wave1-scope-ceiling (e56138a0 → 9016569d → efb7f17e); review-complete, merge pending the daytime B4 baseline run per the c.2333 plan of record"
reviewer: independent subagent (author≠verifier; empirical mutant probes both rounds — the F1 blocker was PROVEN with an injected wrong-refs mutant both old-lock-missed and new-lock-caught; fix-round F1 re-verified with the reviewer's original mutant re-applied)
---

# Disposition — #989 wave-1 scope-ceiling review (2026-07-21)

Round 1 (e56138a0): 1 BLOCKING + 2 SHOULD-FIX + 4 NOTEs. Round 2 (9016569d): all fixes VERIFIED + 1 new SHOULD-FIX (N1). Round 3 (efb7f17e): N1 VERIFIED on all four items. This record rides the #989 merge; verify_disposition green before the merge is reported.

```disposition
f1-repinned-lock-weaker-than-original | FIXED | 9016569d
f2-coverage-crash-path-silent-skip | FIXED | 9016569d
f3-sprawl-conflates-editing-with-authoring | FIXED | 9016569d
f4-ceiling-lists-sibling-init-for-same-package-tasks | REJECTED | Correct ownership-wise and benign under the driver's sequential within-wave merging (the init exists once its owner merges); becomes prompt-level friction only if wave execution ever parallelizes, which is a design change that would revisit the ceiling's rendering anyway.
f5-sprawl-evidence-unsanitized | FIXED | 9016569d
f6-re-pin-location-mislabeled-in-review-brief | REJECTED | A brief-labeling slip by the coordinating session (tests/integration vs shared/tests), not a code finding; the reviewer located the real file and nothing was hidden.
f7-single-task-ceiling-test-drives-fleet-task-for-directly | FIXED | efb7f17e
n1-f2-f5-fixes-shipped-without-locks | FIXED | efb7f17e
n1b-dep-delta-timeout-budget-doubled-unregistered | FIXED | efb7f17e
```

Evidence chain: F1's fix re-pins the exact 4-read delta sequence and the reviewer's re-applied mutant now goes RED at the pack-read position ("At index 2 diff" — the regression class the membership form provably missed). F3's decision (added-only keying via a second `--diff-filter=A` read, absent-key = unmeasured records-nothing) was adversarially probed: re-export-edit no longer fires; pure renames excluded; rename-with-rewrite fires only when the new path is a sibling's contracted file (correct firing); the pre-existing `files` read byte-identical. N1's locks were verified with the F2 caplog lock's teeth demonstrated (blanked warning → only the caplog assert fails) and the F5 control-strip asserted over the full 0x00–0x1F+0x7F range on output. Module counts at efb7f17e: wave1 module 23, registry gate 67, integration-gate re-pins green; full affected surface 562+ per builder, three-module 167 per reviewer.
