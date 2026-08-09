---
title: Overnight driver summary — 2026-07-23 23:00 through 2026-07-24 ~06:15
status: record
area: governance
---

# Overnight summary — 2026-07-24

**Plain summary:** the queue moved a lot. Four real pieces of work landed on `main` (dormant
where required), two extra battery validation windows ran beyond the nightly, the accumulated
journal fragments got folded, and a genuinely interesting recurring bug got found and reported —
nothing was rushed, nothing risky was left half-done, and nothing needs your attention before you
read this except three normal LA-decision items at the bottom.

## What shipped (all on `main`, gate re-measured MEASURED at every step)

1. **S3 slices D + E** (advanced-intake bad-input floor + coherence gate, #1069/#1044/#1054) —
   merged DORMANT behind their own sub-flags, both independently reviewed twice (the build, then
   the merge commit itself, since the merge needed a hand-written docstring fix). #1044/#1054
   close INTO #1069 per your framing, not standalone — F and G still unbuilt, batched ceremony
   still yours.
2. **The mutation-testing tool** (`tools/mutation-harness-1044`) — merged, verdict MERGE, one
   small hardening follow-up filed (#1103).
3. **#1075** (run-fleet's dedup guard — the bug that parked B4's `add-card` three nights running)
   — both halves merged in one motion. Landing it surfaced a real gap (a classification table
   was stale by two RESULT shapes #1074 had added) — found and fixed same night.
4. **#746 slice 2** (plan-time research grounding) — both halves now on `main`, dormant
   (`research_grounding=false`). Re-resolved a fresh 3-file conflict against a fast-moving `main`.

Gate baseline: **9047 → 9206** (0 failed, 0 skipped throughout), synced in every commit.

## Battery windows run beyond the 23:00 nightly

- **23:00 nightly**: B2 + B4 both GREEN — first unattended proof for #1074 + #1076's BlarAI half.
- **#1075's own B4 window**: PARKED-HONEST, but NOT a problem with #1075 — the repair mechanism
  was never exercised; a real, unrelated bug surfaced instead (see below).
- **#1076's still-owed agentic-setup-half window**: same unrelated bug, reproduced identically.

I held off a third window (would have finished ~8am, too tight against your wake time) and held
off designing #746's before/after measurement from scratch at 4am — both are queued cleanly
rather than rushed.

## The interesting find: a recurring, likely-systemic bug (not related to anything I built)

Two independent fresh builds of the B4 flashcards job, three hours apart, hit the **identical**
failure: the `quiz` task improvises the whole `score_tracker.py` file (which belongs to a
different task) with its own guess at a parameter order, and the hidden grading test expects the
opposite order — so scores come out in the wrong order every time. Two-for-two on fresh builds is
strong evidence this will keep failing. Filed as **#1109** (priority raised to match), with the
root cause pinned down precisely: the coder is never told what internal signature the hidden test
expects, so it's guessing blind. Two lesson-worthy patterns also got flagged into their own
tickets rather than fixed on the spot (**#1106**, **#1107**) — both are "third instance,
doctrine says build a control" findings that deserve real design attention, not a 4am patch.

## Housekeeping

- 14 outstanding journal fragments folded into `BUILD_JOURNAL.md`; 6 new lessons minted
  (308–313); several recurrences tallied. Two hit the third-instance threshold with no control
  yet — that's #1106/#1107 above.
- 9 fully-merged worktrees cleaned up in both repos; everything else left alone (other sessions'
  work).
- One process note for myself, not urgent: I dispatched a docs-only fold to a subagent without
  pre-emptively specifying worktree isolation, and it merged into the primary checkout before a
  correction reached it. Verified afterward it only ever touched pure documentation files — zero
  risk in practice — but I should specify isolation up front next time rather than correct after.

## Three things that are yours, whenever you're ready — nothing urgent

1. **#746's docset go-live ceremony** (flip `research_grounding=true` + install the coder tool +
   `BLARAI_RESEARCH_DOCS=1`) — code is dormant and ready whenever you want that ceremony.
2. **The batched S3 ceremony** (D/E/F/G) — D and E are dormant and ready; F and G still need
   building first.
3. **#1109's fix direction** — I named two candidate approaches (extend the coder's contract to
   include function signatures, or test through the public CLI instead of an internal API) but
   left the actual choice for whoever picks it up, since it's a real trade-off, not an obvious call.

Both repos are clean, on `main`, gate green, nightly armed for 23:00 tonight. Nothing is stranded.
