# Cycle 1 — decisions and outcomes (2026-05-12)

## LA decisions

| # | Decision | LA's words / rationale |
|---|---|---|
| 1 | **Cadence: LA-triggered**, not scheduled. | *"The shepherding workstream is LA-triggered."* The workstream stays reactive — Guide acts when LA pings, not on a recurring auto-check. |
| 2 | **PR #266 follow-up: posted** (with LA edits). | Comment ID `4433149755`, posted 2026-05-12T17:38:18Z. URL: https://github.com/openvinotoolkit/npu_compiler/pull/266#issuecomment-4433149755 |
| 3 | **PR #265: no separate follow-up** (as recommended). | Same reviewer / same architectural concern as #266; one follow-up covers both. |
| 4 | **PR #34651: no follow-up this cycle** (as recommended). | Re-evaluate in 2-3 weeks. If still silent, consider posting on underlying issue #34617 with fresh data (the engagement-first pattern that worked on #35641). |

## LA edits applied to the v1 draft before posting

The LA made tone adjustments before posting. Captured here for future
drafting calibration:

| Draft (Guide v1) | Posted (LA edit) | Calibration takeaway |
|---|---|---|
| *"checking in on the IR-dumping question from my April 17 reply"* | *"when you have a moment, would you have guidance on the IR dumping methodology"* | LA prefers no date anchor in follow-ups. Reads less like a deadline-tracker, more like a sincere ask. Future drafts: drop "from my Date X reply" — the comment thread context makes the back-reference obvious. |
| *"Happy to wait if other items have priority"* | *"Happy to wait as I am sure there are greater priorities for the team"* | Slightly warmer, more deferential framing. Future drafts: presume the team is busy; don't make Intel justify other priorities. |
| (AI Assistance disclosure block at end) | (removed) | LA chose to omit on this short follow-up. See "Observations" below — policy consistency point to revisit. |
| *"commit `9c7526f` *(corrected — see E4 in STATUS; the head SHA `c5f9266` is a docs-only update from 3 min after, not the test commit)*"* (Guide substituted the actual SHA) | *"commit `[SHA]`"* (LA pasted the placeholder unmodified) | Probably a paste oversight, not an editorial choice. Future drafts: do not use `[SHA]`-style placeholders; substitute the actual value in the draft so the LA doesn't have to remember to fill it in. |
| *"Let me know if it's structured the way you'd want, or if it needs adjustments."* | *"Let me know if it's structured the way you'd want."* | LA prefers tighter phrasing. Future drafts: trim trailing "or if it needs X" hedges; the reader infers the open invitation. |

## Observations flagged to LA

1. **`[SHA]` placeholder is live in the posted comment.** Daria will see the literal `[SHA]` rather than the commit SHA `c5f9266`. Recommended fix: edit the comment via GitHub webUI to substitute the value. The pencil icon on your own comment lets you edit.
2. **AI Assistance disclosure removed.** Editorial choice. Policy consistency with the #35641 comment (which included the disclosure) is worth thinking about, but it's LA's call. Future-draft default: include AI Assistance unless LA tells me to omit; LA can always strip it before posting.

These observations were surfaced to LA in chat at cycle close-out; LA decides whether to edit the live comment.

## Cycle close-out

- All 5 cycle-1 artifact files committed under `2026-05-12-cycle1-survey-and-pr266-followup/`.
- Workstream STATUS appended (E2 founding entry → E3 cycle-1 close-out — see STATUS.md).
- Workstream parent ticket #466 updated with cycle-1 outcome comment.
- Per-PR ticket #469 (Shepherd: #266) updated with posted comment URL.
- Per-PR tickets #467, #468 unchanged this cycle (no actions taken).

Next cycle is **LA-triggered**. Workstream stays Active and quietly waits.
