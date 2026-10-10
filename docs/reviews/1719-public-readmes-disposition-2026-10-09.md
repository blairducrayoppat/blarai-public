# Disposition — independent review of the October 2026 README rewrites before merge (#1719)

**Review:** an independent adversarial-reviewer agent (did not author the text), 2026-10-09 about 20:45 -04:00,
against BlarAI commit `9fcdb1fb` (branch `vikunja-1719-campaign-2f5b49`, over `main` `979c8eff`) and agentic-setup
commit `3c6e5e0` (branch `docs/1719-readme-october`, over `main` `2fdd6b9`). It read every owning surface the added
text cites (ADR-043, ADR-045 with its 2026-10-09 amendment, ADR-049, the containment design overview, the 2026-10-05
evidence record, `docs/TEST_GOVERNANCE.md` section 1, the LESSONS index, the agentic-setup scripts and the two
published reviews with their dispositions), grepped every named function, checked every relative link target, and ran
the two tests that read the BlarAI README (74 passed).
**Author of the text and of this disposition:** this session.
**Outcome:** five findings; all five fixed: BlarAI `6c20a94e` and
agentic-setup `425cb2a`; none deferred, none rejected. Verdict before the fixes: MERGE-READY after
findings 1-3.

```disposition
F1 both READMEs attributed every WFP window to "that account" (the coder account); the evidence record's claims table keys only the three five-second runs (C1) to blarai-coder, and the two-minute run (C3b) and the six alternated runs (C7, C8) to a throwaway account of the same kind | FIXED | 6c20a94e README.md "One measurement of the egress gap" bullet names the coder account for the three runs and a throwaway account of the same kind for the others; agentic-setup@425cb2a README.md egress bullet, same attribution
F2 the journal fragment said the two old gate-figure copies "disagreed with each other"; they were the same figure, one without its deselected column, both stale against the baseline | FIXED | 6c20a94e docs/journal_fragments/2026-10-09_1719-a-public-surface-states-the-switch-position-before-the-design.md paragraph 4
F3 the agentic-setup egress bullet carried the windows and the dynamic session but not the "evidence, not a control" clause the register requires in the same bullet | FIXED | agentic-setup@425cb2a README.md egress bullet
F4 the fragment said the profile README "went live this morning"; the profile repository's commits run from 12:07 to 18:41 -04:00 on 2026-10-09, so "today" is what the record shows | FIXED | 6c20a94e docs/journal_fragments/2026-10-09_1719-a-public-surface-states-the-switch-position-before-the-design.md paragraph 2
F5 docs/TEST_GOVERNANCE.md section 1 said "The figure above is the ELEVATED reading, so 0 skipped is expected" under a LIVE_GATE_BASELINE that is non-elevated with 3 skips, and both READMEs now send readers to that section for the run conditions | FIXED | 6c20a94e docs/TEST_GOVERNANCE.md section 1 "READ THE SKIP COLUMN" paragraph: the elevation is read from the figure's parenthetical, with the reconciliation rule non_elevated_passed + 3 = elevated_passed
```

## What the review attacked and could not break (recorded so a later pass does not re-litigate)

- The gate figure, its condition, the "last elevated full run" sentence and the lesson-index figure against
  `docs/TEST_GOVERNANCE.md` section 1 and `LESSONS.md` (380 lines, highest number 385, 344-348 reserved).
- Every ADR claim (ADR-043 "24+ ways around the text guard" over four rounds; ADR-045 flag off, ACL stage merged and
  not applied, account boundary not a kernel or VM boundary, no complete dispatch run; ADR-049 one dimension, one
  machine, limits in Context, claim/form/licence undecided, no runtime change).
- Every agentic-setup code claim by grep on `3c6e5e0`: `Get-WtGit`, `Get-HardenedGitArgs` (the five command-line
  settings), `Assert-FusedWorktreeTrusted` and the fingerprint's coverage, `Lock-FusedWorktree` and the share-read
  handle on the `.git` pointer, the result-acceptance checks in `Invoke-FusedCoderRun`, `Start-ProcessInJob`
  (CREATE_SUSPENDED, kill-on-close, no breakaway), the funnel lint mutants, the ACL stage's modes, the tool-chain
  stage's content and handle-based stamping, `Test-CoderOpencodeConfigSafe`.
- Review 775 finding L1 and review 1678 finding X1 are each the first finding of its review; the 173-call race is the
  disposition's `n1-swap-window` row.
- The register bounds: no present-tense "contained" or "sandboxed", no "zero egress" or "no network" about the
  fleet, no "every" about the audit, no vendor or product proper noun (the security suite is unnamed in both
  READMEs), the vision sentence verbatim exactly once per README, `demo.html` still linked, no Liquid syntax, every
  relative link target present.
- No unchanged sentence in either README contradicts the added text.

## What this cost, and what caught it

The review ran about eight minutes. F1 is the one to keep: the evidence record's own section 1 says "a dedicated
low-privilege account" for all four windows, and the profile README says "that account", so three surfaces agreed
with each other and disagreed with the claims table. The table is the stricter record and the READMEs now follow it.
