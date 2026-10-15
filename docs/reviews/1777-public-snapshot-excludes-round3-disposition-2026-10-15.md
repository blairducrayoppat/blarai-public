---
title: "#1777 public snapshot excludes: disposition of review round 3"
status: closed
area: reviews
date: 2026-10-15
---

# #1777 round 3: review disposition

**Subject:** BlarAI `feat/1777-public-snapshot-excludes` (fixes in `73bf0190`) and agentic-setup `feat/1777-publisher-publicignore` (fixes in `1c847ad`), against round 3 of `review-1777-public-snapshot-excludes-2026-10-14.md`. Branch dry run after the fixes: 25 paths excluded, gate fails only on the register pin's two patterns. Publisher scratch test 57 checks; removing the empty-tree refusal, the anchor refusal, the phrase-parity refusal or the lower-casing order each fails it.

```disposition
R3-1-the-list-can-remove-the-public-evidence-with-every-control-green | FIXED | 73bf0190 scripts/publicignore_anchors.txt, read from the index by the lock (test_the_list_excludes_no_anchored_path, toggle with a broad name line that reaches a run-data folder, stale-anchor and index-read toggles) and agentic-setup@1c847ad from the source ref by the publisher (scratch case 16 with the same broad line)
R3-2-publisher-needles-are-not-pinned-to-the-phrase-file | FIXED | agentic-setup@1c847ad - the publisher reads scripts/publicignore_phrases.json from the source ref and refuses the repository when an assembled phrase is not a needle; scratch case 17 with a private file one phrase short
R3-3-lower-case-before-decode-and-overclaiming-honest-limit | FIXED | 73bf0190 lock and agentic-setup@1c847ad publisher decode first and lower-case after (toggle for percent and JSON escapes of a capital; scratch plants a percent-encoded capital for every phrase); both honest-limit texts name the remaining forms and the lock docstring claims one view each
R3-4-index-read-of-the-phrase-file-tested-on-the-helper-only | FIXED | 73bf0190 - _load_phrases takes a root and test_toggle_load_phrases_reads_the_index_copy_of_the_root_it_is_given drives it
R3-5-empty-tree-refusal-never-reached | FIXED | agentic-setup@1c847ad - scratch case 18 (no README or LICENSE, list of one star) reaches the refusal; removing it fails the case
R3-6-real-run-probes-aimed-at-the-real-blarai-repository | FIXED | agentic-setup@1c847ad - the case-10 and case-14 probes run a publisher copy whose repository table lists only a scratch repository
R3-7-a-toggle-compares-two-constants | REJECTED | the test still bites through its first assert (mutation recorded in the review); the second assert only restates it and costs nothing
```
