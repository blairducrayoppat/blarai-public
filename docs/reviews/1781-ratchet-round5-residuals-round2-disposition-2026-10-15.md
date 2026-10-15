# Disposition: round 2 of the review of the ratchet's round-5 residuals (#1781)

Review: `docs/reviews/review-1781-ratchet-round5-residuals-2026-10-15.md`, section "# Round 2 (2026-10-15)" (independent Opus reviewer, verdict PASS at `b0ecf677`, fix `4837ffac`; R1-1 to R1-4 hold by execution, each revert fails a named test; no other path to FIRST_LANDING or a silent skip found). Two LOW findings.

```disposition
R2-1-claim-check-probes-only-x-md | DEFERRED | #1783 - blocked-by: #1783 closed with a test that fails when identity.md's glob is narrowed to docs/**/*.md; today identity.md's globs are docs/**, scripts/**, tools/**, tests/** (no extension filter), so no delivery gap exists on the merged tree
R2-2-fragment-sentence-describes-the-old-check | FIXED | 4177ecbb - the fragment sentence in docs/journal_fragments/2026-10-15_1781-ratchet-round5-residuals.md now says the check asks the matcher about two sample paths per claimed directory, and names the residual (#1783)
```
