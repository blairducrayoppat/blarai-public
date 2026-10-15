# Disposition: round 4 of the review of the public-snapshot exclusion control (#1777)

Review: `docs/reviews/review-1777-public-snapshot-excludes-2026-10-14.md`, section "# Round 4 (2026-10-15)" (independent Opus reviewer, verdict PASS at BlarAI `ed1ff1fd` / agentic-setup `1c847ad`, no blocker). The text is committed in `87af1dfc`. Each R3 fix, reverted alone, fails a named test. Every anchor attack tried was caught, and R3-6's probes reach no real repo. A simulated `--no-ff` merge into main `8f54b61f` has no conflict: `--check` 0, lock/ADR/identity/doctrine 281/281, and the dry run fails only on the register pin. Two LOW findings go to #1785, which must land before the weekly snapshot task's next unattended run.

```disposition
R4-1-paths-cited-by-anchored-evidence-are-not-anchored | DEFERRED | #1785 - blocked-by: #1785 closed, due 2026-10-19 before the weekly snapshot task's next unattended run; every one of the ~38 cited paths is in the filtered tree today (no .publicignore line matches them, round-4 dry run), so no evidence is held back by this snapshot
R4-2-publisher-skips-anchor-and-phrase-checks-silently-when-a-file-is-absent | DEFERRED | #1785 - blocked-by: #1785 closed, due 2026-10-19; the snapshot this branch enables runs on a source tree that carries both files (the dry run reads them), so the silent skip cannot fire for it, and the BlarAI lock fails the gate on a missing anchor file
```
