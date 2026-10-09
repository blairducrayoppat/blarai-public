# Disposition — independent review of the #1699 write-up and its banked data

**Review:** independent adversarial-reviewer session (did not author the write-up), run against `6a0acf33`: it
recomputed every number in `PERFORMANCE_LOG.md`, `docs/TEST_GOVERNANCE.md`, the dataset README and the `CLAUDE.md`
snapshot from the raw logs, and looked for overclaims. Verdict: block until the attribution errors were fixed.
**Author of the write-up and of this disposition:** this session. The record is written after the fact: the fixes
were made and merged first, and the missing record was found by checking the work against the disposition rule.
**Outcome:** all eight findings resolved in `6e97403e`; a ninth item, a related unexplained effect, is ticketed.

```disposition
W1 the headline said nine new test files for the git-hook tooling and six more between 10 and 54 s, but there are twelve, and the 884 s sum holds only with all twelve | FIXED | 6e97403e - PERFORMANCE_LOG.md, the dataset README and the journal fragment now say twelve, with eight between 10 and 54 s and one under 10 s
W2 finding (4) quoted the post-fix per-file seconds 111/104/132 from a git-files-only branch gate run at another commit, not from the banked post-fix runs | FIXED | 6e97403e - replaced with the means of the two banked post-fix worktree runs, 119.5/101.2/102.9 s
W3 finding (3) paired the author's single uncontrolled profile (2.8 s, 75 processes) with the reviewer's median after (0.97 s, 18) as one before and after | FIXED | 6e97403e - the matched interleaved pair (3.05 s and 76 processes before, 0.97 s and 18 after, median of 8) is cited and the single profile is labelled as such
W4 the real-checkout figures fell by about 360 s and non-git about 200 s slower were the extreme pairings, not arm means | FIXED | 6e97403e - arm means 895 s to 557 s (337 s) and 685 s to 866 s (180 s), net 157 s, stated with the uncontrolled-arm caveat
W5 the arms were called 2.4 to 2.5 times apart; the arithmetic gives 2.3 to 2.4 | FIXED | 6e97403e - PERFORMANCE_LOG.md and the dataset README corrected
W6 ticket #1706 said 2 of 8 timed runs and passed in both real-checkout runs, and the stamp paragraph said the worktree runs read 5 failed; the logs show 3 of 8 including a real-checkout run, and one worktree run read 6 failed | FIXED | 6e97403e - TEST_GOVERNANCE.md now says 5 or 6 failed; the ticket was corrected by comment 3956 on #1706
W7 the diff retired the #1699 ROADMAP row without stating the technical call the ticket asked for (trim, split or parallelise) | FIXED | 6e97403e - TEST_GOVERNANCE.md section 1 rule 9 states it; comment 3957 on #1699 records the decision and the answers
W8 provenance gaps in the banked corpus: the 1424 s figure appeared nowhere in the data, the post-fix tick log was not banked, the per_file_summary.json invocation was unstated, and the first plan's prediction time rested on an excerpt | FIXED | 6e97403e - 1424 dropped, post_fix_runs/ticks.log banked, the invocation and the prediction provenance written in the dataset README
W9 the non-git test files read about 180 s slower in the idle post-fix real-checkout runs than in the earlier operator-present runs, with no cause found | DEFERRED | #1708 blocked-by: #1708 closed - an experiment is defined on the ticket (CPU temperature sampled in the runner, with and without a cool-down between runs); it is a new measurement, not a defect in the write-up, and the write-up already lists it under Not measured
```

## What the review confirmed

Every wall clock, count, start time and idle-at-start in both state files matched the logs; all eight sampler
files show AC power and input never resuming; no run was voided; the prediction files precede the runs they
predict; the exploratory parallel split sums to the standing 13250; the stamp equality between `CLAUDE.md` and
`TEST_GOVERNANCE.md` holds; the ROADMAP block stayed contiguous with exactly one row removed.
