# Disposition: round 5 of the adversarial review of the public-identifier scrub and lock (#1765 / #1767 / #1741)

Review: `docs/reviews/review-1765-public-identifier-scrub-2026-10-14.md`, section "Round 5" (independent Opus reviewer, 2026-10-15, verdict PASS at `d44738fe` on condition of a `--no-ff` merge, 5 findings R5-1 to R5-5; all eight round-4 fixes re-verified by execution, each new lock fails when its fix is reverted). Review text committed in `e2c7b32d`. The branch merges `--no-ff`, as the verdict requires; the five findings go to #1781, which must be on main before the LA is asked for the real public snapshot.

```disposition
R5-1-fast-forward-puts-the-legacy-list-baseline-in-mains-window | DEFERRED | #1781 - blocked-by: #1781 closed with its merge commit on main; until then the merge of this branch and of every branch touching scripts/identity_user_baseline.json is --no-ff, which the reviewer reproduced as reading 557 files and --check 0 (first-parent history never carries 373e9685)
R5-2-index-claim-check-is-a-prefix-match | DEFERRED | #1781 - blocked-by: #1781 closed; on the merged tree the six-path hook sample in tests/security/test_doctrine_rules.py still fails a narrowed surface, as the reviewer showed
R5-3-main-dropped-message-skips-the-fork-comparison | DEFERRED | #1781 - blocked-by: #1781 closed; the gate still fails on the growth, only the message names the wrong cause
R5-4-run-arm-call-site-locked-only-by-substring | DEFERRED | #1781 - blocked-by: #1781 closed; run_arm_e.py and arm_a_operator.ps1 are parse-locked on their real expressions today, and the reviewer's five extra profile shapes arrive intact through argv_tail
R5-5-ratchet-window-of-twenty-unnamed-in-the-honest-limit | DEFERRED | #1781 - blocked-by: #1781 closed; hypothesis-grade (not reproduced), and bounded meanwhile by the --no-ff merge rule
```
