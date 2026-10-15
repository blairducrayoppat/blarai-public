---
title: "#1777 public snapshot excludes: disposition of review round 2"
status: closed
area: reviews
date: 2026-10-15
---

# #1777 round 2: review disposition

**Subject:** BlarAI `feat/1777-public-snapshot-excludes` (fixes in `8b693a65`) and agentic-setup `feat/1777-publisher-publicignore` (fixes in `31dd5a7`), against round 2 of `review-1777-public-snapshot-excludes-2026-10-14.md`. Lock: 137 tests in the private-material lock plus 3 in the ADR quotation lock; publisher scratch test 51 checks; removing the anchor check, the backslash view or the percent view each fails it. Branch dry run after the fixes: 24 paths excluded, gate fails only on the register pin's two patterns and the host-name pattern.

```disposition
R2-1-merge-order-and-identity-ratchet-after-1765-merge | FIXED | 0cfc336b - main (fc5d2383) merged in; the four files reworded, the baseline drops the three held-back draft paths (the name is written __USER__ in those drafts), KNOWLEDGE_MAP_BATCH4 lowered to 18, the 1777 review written with __USER__; scrub --check 0 findings
R1-1-four-files-on-the-1765-branch-carry-the-numbered-phrase | FIXED | 0cfc336b - same change as R2-1; lock and branch dry run clean of the phrase; the dry run fails only on the register pin's two patterns
R2-2-adr-045-misquotes-the-proposal | FIXED | 8b693a65 - ADR-045 line 131 quotes the sentence word for word; tests/security/test_adr045_nep_quotation.py checks it against ws0-nono-srt.md and fails on the paraphrase
R2-3-a-list-matching-everything-publishes-the-empty-tree | FIXED | 8b693a65 lock (anchors_lost, tree_is_empty, toggle with a list of one star) and agentic-setup@31dd5a7 publisher (empty tree and lost anchor refused; scratch cases 15)
R2-4-phrase-set-can-shrink-silently | FIXED | 8b693a65 - the lock reads scripts/publicignore_phrases.json from the index and pins the sha256 of the sorted phrase set (PHRASE_SET_DIGEST); toggles for a changed phrase and for an unstaged edit
R2-5-markdown-and-percent-forms-unseen-and-unnamed | FIXED | 8b693a65 lock and agentic-setup@31dd5a7 publisher - backslash-before-punctuation and percent-decode views on both sides with a toggle each; both honest-limit texts name every remaining miss from the review's table
R2-6-toggle-fixtures-republish-the-removed-wording | FIXED | 8b693a65 - fixtures built from parts, the test covers every unexcluded docs/reviews file, and the review of this control is on the list (test_the_one_review_of_this_control_is_held_back_by_the_list)
R2-7-two-fail-closed-paths-no-test-reaches | FIXED | agentic-setup@31dd5a7 - -PrivatePatternsPath and -ViewScanBlobCapOverride (dry run only, refused otherwise); scratch case 14 covers the no-phrase refusal, the cap report and both refusals
R2-8-fold-tripwire-covers-two-of-the-fold-targets | FIXED | 8b693a65 - the marker is searched in every unexcluded tracked file in the same pass as the phrases; parametrized toggle over lessons, field notes, anthology, archive paths and the journal
R2-9-normalized-view-doubles-the-dry-run | REJECTED | a weekly job that takes about 25 seconds longer; the views are the control, and a cheaper pass that skips a view or a blob would reduce what the gate reads for a saving nobody waits on
R2-10-self-exclusion-message-names-the-wrong-cause | FIXED | agentic-setup@31dd5a7 - the message now says the list must hold back its own file
```
