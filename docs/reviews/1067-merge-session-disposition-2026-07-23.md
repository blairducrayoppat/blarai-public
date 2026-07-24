---
title: "#1067 v7 merge-session review — finding disposition"
status: closed
area: reviews
date: 2026-07-23
---

# #1067 v7 merge-session review — disposition

**Subject:** the successor merge session's own additions to `feat/1067-v7-run-derived-vocabulary`
on top of the already-cold-passed guard (`9cff8f30`) — commits `ab787d5f`, `58d2bb9f`, `6bac1c85`,
`9292d3d6`. The v7 guard's own V/W/X findings are dispositioned in their own commit messages and are
NOT re-litigated here.

**Reviewers:** two independent agents, neither of which authored the code. `reviewer-1067-y-fixes`
cold-passed `ab787d5f` then re-passed `58d2bb9f`; `reviewer-1067-fresh` cold-passed `58d2bb9f`
independently and reached the central conclusion by a different route (the ratified definition of
false, not the oracle defect). Both returned MERGE-AFTER-FIXES. Neither wrote a fix.

**This record is author-written**, which is the weaker arrangement — an author-written disposition is
where a finding gets quietly downgraded. Read the rows against the commits, not against my summary.
The findings here are unusually load-bearing because several of them are defects in MY OWN claims and
tests, caught by the reviewers and not by me; the pattern is recorded in the journal fragment
(`docs/journal_fragments/2026-07-23_1067-the-control-that-could-only-pass.md`), not smoothed over.

## The findings

`Y-*` = first pass on `ab787d5f`. `F-*` = second pass (both reviewers) on `58d2bb9f`/`6bac1c85`.
Numbering follows each reviewer's own labels.

| id | sev | one line | disposition |
|---|---|---|---|
| Y-1 | HIGH | grader's two-pass screen counted mixed-vocabulary sentences as caught while production excuses them | FIXED |
| Y-2 | HIGH | fail-closed test asserted an absence; green whenever the cycle drafts no prose for any reason | FIXED |
| F-1 | HIGH | my claim "no false statement the carve-out excuses exists" was false; four counter-examples | FIXED |
| F-1b | HIGH | my replacement claim "guard and oracle AGREE" was also false, same flattering direction; I kept only the two witnesses that held 100% | FIXED |
| F-2 | HIGH | the exact-screen cost comment claimed "still fast"/point figures it had not measured | FIXED |
| F-3 | MED | the screen is not fully exact (run-id slot + digit-leading names unenumerated); comment over-claimed "any vocabulary" | FIXED |
| F-6 | MED | the figure-lock test observed a helper, not the reported measurement; blind to a truncation below the cap | FIXED |
| F-8 | LOW | the figure-lock fixture carried `expected_false=True` on two oracle-TRUE statements | FIXED |
| F-5 | LOW | disposition record for the pass was missing | FIXED |
| F-7 | LOW | a measured ~2× screen speedup (strip the echo before tokenising) not taken | DEFERRED |
| F-9 | INFO | `_grade_words` never reads `expected_false`; a mislabel silently distorts the denominator | DEFERRED |
| OD | — | the claim oracle matches success substrings and ignores the governing negation/limiter — ground truth wrong in both directions | DEFERRED |
| GVD | — | guard-vs-oracle divergence on limited-pass claims (which side is right) | DEFERRED |

```disposition
Y1-two-pass-screen-counts-mixed-vocab-caught | FIXED | ab787d5f _refused_under_every_bipartition enumerates every disjoint bipartition; mutation-proven (revert to two-pass turns test_the_adversarial_screen_covers_MIXED_vocabulary RED)
Y2-fail-closed-test-asserts-absence | FIXED | ab787d5f test_an_unreadable_harvest_leg runs the identical env twice with only ReadStatus flipped; mutation-proven (drafting-dormant: old test GREEN, new test RED, on the same tree, prose_guard restored byte-identical)
F1-no-false-statement-carve-out-excuses-is-false | FIXED | 58d2bb9f claim retracted in the test docstring, commit message, journal fragment and #1097; four counter-examples verified before acting
F1b-guard-and-oracle-agree-is-also-false | FIXED | 6bac1c85 both counted witnesses WITHDRAWN; corpus restored byte-identical to main (git diff main -- the corpus file is empty); the counted-pass bound is already locked as guard behaviour in test_coordinator_prose_guard.py needing no truth label
F2-exact-screen-cost-comment-unmeasured | FIXED | 58d2bb9f then 9292d3d6 the _MAX_ENUMERATED_TOKENS comment carries the measured RANGE (1.4-2.1 ms, contention-noted) rather than a point figure claimed as fast
F3-screen-not-exact-run-id-and-digit-leading-names | FIXED | 58d2bb9f then 9292d3d6 the comment states the weaker property it actually has ("max over the case's own letter-leading tokens, run-id fixed") and both gaps are named; both LATENT (no shipped case names a run id or a digit-leading task)
F6-figure-lock-observes-helper-not-measurement | FIXED | 6bac1c85 then 9292d3d6 test_grade_window_reports_the_adversarial_catch drives grade_window over a vocabulary-dependent case; mutation-proven RED under both an emptied token extraction and a tokens[:2] truncation below the cap
F8-figure-lock-fixture-mislabelled-expected-false | FIXED | 9292d3d6 fig-excused and fig-mixed set expected_false=False to match verified oracle-TRUE; fig-refused stays True (oracle FALSE); does not move any number (F-9) but corrected because it is the exact mislabel class under review
F5-disposition-record-missing | FIXED | this record, docs/reviews/1067-merge-session-disposition-2026-07-23.md, run through scripts/verify_disposition.py before the work is reported done
F7-echo-strip-2x-screen-speedup-not-taken | DEFERRED | #1097 blocked-by: shared/grading/coordinator_graduation.py _grade_words stripping the "INCOMPLETE:" echo before tokenising (measured 46,944 vs 93,888 screens, identical 28/28); a change to the measurement path earns its own review and this merge stays fixes-of-findings
F9-grade-words-never-reads-expected-false | DEFERRED | #1097 blocked-by: promoting the never-TRUE invariant (test_oracle_never_contradicts_the_adversarial_corpus_labels) to a load-time check in shared/grading/corpus.py, so a case the oracle adjudicates TRUE fails loud at load; NOT an equality check against expected_false, which would fail on the 14 litotes cases the oracle correctly abstains on (measured 12 FALSE / 14 UNDETERMINED / 0 TRUE over the 26 cases)
OD-oracle-ignores-governing-negation-or-limiter | DEFERRED | #1097 blocked-by: shared/grading/claim_oracle.py not reading a determiner-negated subject or an "only N of M" limiter as an assertion that the acceptance oracle passed; blocks #1099 and any measurement window
GVD-guard-vs-oracle-divergence-on-limited-pass | DEFERRED | #1097 blocked-by: an LA/criteria ruling recorded in docs/governance/coordinator_graduation_criteria_2026-07-23.md on whether prose_guard.py:511-516 (accept "only 5 of 10 passed") or claim_oracle (call it false) is the defective side
```

## Notes on the DEFERRED rows — each carries an observable predicate, not a filler phrase

- **F-7 / F-9** are genuine hardening of the instrument, not the corpus content this merge fixes.
  Both name a specific file and change a later session can observe landing.
- **OD / GVD** are the substance of #1097 and #1099. OD is a code fix with a named site; GVD is
  explicitly an LA decision (two components disagree and only the operator rules which moves), so its
  predicate is a ruling recorded in the ratified criteria document, not a code change.
- None of the four is "follow-up" or "lower priority": each states a surface a successor can read to
  confirm it is done.

## Honest limit of this record

`verify_disposition.py` checks the FORM of a record that exists; it cannot see a finding that was
never written down. Two full cold passes and my own probing produced these; a finding a fourth pass
surfaces is not covered here and would need its own row.
