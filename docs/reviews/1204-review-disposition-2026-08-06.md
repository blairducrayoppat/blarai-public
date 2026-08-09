---
title: "#1204 salvage-goal-set — independent review disposition"
status: evidence
area: governance
date: 2026-08-06
---

# Disposition — independent review of `fix/1204-salvage-goal-set` @ `95eb90b1`

Reviewer: an independent session that did not author the branch and wrote nothing
(author != verifier). Verdict: **MERGE-WITH-CAVEATS** — 3 SHOULD-FIX / 3 NIT.

## The review arrived after the merge, and that is recorded rather than smoothed over

I merged this branch at `cf6f6ae0` on my own read, having twice pinged a dispatched reviewer
that had gone idle without reporting. I said so on the ticket at the time rather than letting
"reviewed" imply a second pair of eyes. The report then arrived — it had been written in full
and never sent, which the reviewer stated plainly when asked.

The verdict was MERGE-WITH-CAVEATS, so the merge stands and nothing needs reverting. **That is
luck, not process.** Had it returned REFUSE I would have merged a branch a reviewer would have
stopped. The correct lesson is not "it worked out" but that a review whose report never
arrives is indistinguishable from no review, and the merging session must either wait for it
or state that it proceeded without one. I did state it; I should also have waited, because
nothing about this branch was urgent.

## The strongest thing in the review

The reviewer **re-ran the branch's probe against current `main` and it reproduced
byte-identically** — every cosine to four decimals, every page path, every BM25 top, sixty
commits later (the only diff was LF vs CRLF line endings). For an evidence branch that is the
best available proof, and it held. It also confirmed the §1 structural finding against current
source (`lookup.py:375`, `:403`, `:441-442`) and confirmed `research_grounding = false` at
`default.toml:952`, so the "ratified silence" claim matches live config.

```disposition
SF1 SHOULD-FIX the write-up at docs/reviews/1204-semantic-rerank-first-measurement-2026-07-31.md:62-63 puts TWO different pages on one row - it attributes BM25 0.2986 to library/argparse when 0.2986 is library/csv's score, contradicting the branch's own goal-set JSON at :26 and contradicting SS1's whole argument that library/csv is the right page discarded below the floor; reviewer measured argparse at 0.2499, rank 14 of 40 | FIXED | docs/1204-review-disposition - the row now separates embedding-top from BM25-top and states argparse's real 0.2499, with a dated correction note naming the propagation into ticket comment 2775
SF2 SHOULD-FIX the branch's ONLY stated reason for shipping no regression lock - "waits for the in-flight #1223/#1244 merges" - was already void when written, because both are ancestors of the branch tip and 6192049c IS the merge base, so per deferral_discipline it was not a deferral but a fix not done | DEFERRED | #1308 - blocked-by: the absence of any test that fails when docs/reviews/1204-plan-grounding-goal-set-2026-07-31.json loses an entry - observable by deleting one goal and watching the standing gate stay green
SF3 SHOULD-FIX the documentation says the evidence gate is "ticketed separately" and no such ticket existed - reviewer searched project 3 for "evidence gate", "held-out" and "goal set" and found zero matches | FIXED | #1308 filed 2026-08-06 with the gate's definition of done, its toggle-proof requirement, and the baseline/size consequences of adding it
N4 NIT no disposition record for a findings-returning pass, where twenty such records exist on main | FIXED | docs/1204-review-disposition - this record, landed on that branch
N5 NIT the probe hardcodes the primary checkout for pgov at :97 while resolving lookup.py relatively at :20-26, mixing trees | REJECTED | Moot by construction and the reviewer said so: wt-1204-evidence/models/ carries neither docsets nor bge-small-en-v1.5, and both BLARAI_RESEARCH_*_DIR overrides were removed for security, so the probe CANNOT run in the worktree that carries it. Running from the primary checkout is its intended and only fallback. Making the paths uniformly relative would produce a probe that resolves cleanly and then fails on missing models, which is worse - it would look portable and not be. Recorded rather than actioned so the next reader does not re-open it.
N6 NIT SS1 and SS2b score DIFFERENT target pages for the same goal - SS1 treats library/csv as correct for "build a CLI using argparse that reads a csv file" while SS2b marks the embedding right for returning library/argparse | DEFERRED | #1308 - blocked-by: the goal-set JSON carrying no declared correct page per goal - observable by reading docs/reviews/1204-plan-grounding-goal-set-2026-07-31.json, where entries record a measured best_page but never a REQUIRED one
```

## Why SF1 is worth more than its SHOULD-FIX tag

It is a wrong number in the document whose entire argument is that numbers must be **read
rather than narrated**, and it survived the branch's own §2b self-correction pass — because
that pass re-checked the *pages* and not the *figures*. A self-correction scoped to one
dimension leaves the others exactly as trusted as they were before, and reads as if it
checked everything.

The concrete harm was reachable: a reader reproducing "below floor" from that row would chase
0.2986 against argparse, fail to find it, and have no way to tell whether the branch or their
own reproduction was wrong.

## What the review could NOT verify, carried forward

- **The 164 held-out goals.** Genuinely unrecoverable — the reviewer confirmed no goal file was
  ever added or deleted in the branch's history. This is what #1308 exists to prevent recurring.
- **B2's verbatim goal** — needs the battery card.
- **The NPU path** — the probe ran `ort-cpu`, as it states.
- **The standing gate** — not run by the reviewer (instructed); run by me on merged `main`:
  10316 / 0 failed / 0 skipped / 129 deselected. The branch touches no path in the gate
  selection, so the count was expected to be unchanged and was.
