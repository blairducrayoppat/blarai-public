---
title: "Baseline-derivation review — disposition"
status: evidence
area: governance
date: 2026-08-06
---

# Disposition — independent review of `docs/0806-baseline-derivation`

Reviewer: an independent session that did not author the change (author != verifier).
Verdict on `5b760d99`: **REFUSE**, 3 BLOCKING / 2 SHOULD-FIX / 3 NIT. All dispositions below.

The review was correct on every blocking point, and one finding matters more than the rest:
**the deferral rationale in `95f3beb6` and in #1300 was false.** I wrote that the addend
collection could not be run because the box was committed to a battery run. The four
collections had in fact completed at **17:03**, thirteen minutes before I authored that
commit — by the very subagent I had stopped, which finished its measurement before it went
idle. I stopped it and then reported its work as impossible. The data was on disk the whole
time, in `scratchpad/out/*.counts`, and folding it in took one command.

That is worth naming precisely, because it is not a deferral-discipline failure of the kind
the gate catches: the predicate was observable, the ticket was real, the record was
well-formed. It was a false *reason*, stated confidently, in a change whose entire subject
is figures that were narrated rather than read. The reviewer found it by checking file
mtimes against the commit's author date — the same move the change itself makes about the
15:52 stamp.

```disposition
FIX-1 BLOCKING "seven seconds of slack" is 46.49 s - an uncomputed derived figure inside the sentence convicting uncomputed derived figures | FIXED | e42563fe - the line now reads 46 s, and the derivation shows 15:44:04.5 vs 15:44:51 so a reader can recompute it
FIX-2 BLOCKING "85677aeb is 20f922be plus TWO docs-only commits" - it is ONE | FIXED | e42563fe - `git log --oneline 20f922be..85677aeb` returns exactly 1; corrected to ONE, and the superset argument is simpler for it
FIX-3 BLOCKING TEST_GOVERNANCE at 39,786/40,000 left 214 bytes, but #1300's definition of done is TWO addend tables in that same section - the change consumed the budget its own follow-up required | FIXED | e42563fe - resolved by compressing my own added prose rather than by dropping the tables: both tables are IN and the file is 39,692/40,000, 308 bytes spare, MORE headroom than before the fix
FIX-4 SHOULD-FIX the deferral rationale is contradicted by artifacts predating the commit by 13 minutes | FIXED | e42563fe - the addends are folded in and #1300 is closed rather than re-justified; the false rationale is retracted on #1300 and named in this record's preamble rather than quietly dropped
FIX-5 SHOULD-FIX "the output file's mtime is the finish stamp" names no file a later session could follow | FIXED | e42563fe - clause removed in the rewrite; the derivation now stands on the two commit author-dates and the run length, all of which are re-derivable from git alone
NIT-6 battery-campaign.json notes still assert end_date is #763's ONLY remaining landing trigger, superseded by #763 c.2826 | DEFERRED | #763 - blocked-by: the next edit to agentic-setup `state/battery-campaign.json`, which is gitignored, lives in a different repo, and must never be edited while a runner is live (a battery run is live now). The stale clause is in a `notes` field that is already an append-only history of superseded directions; c.2826 is the durable correction and is what a reader is pointed at.
NIT-7 CLAUDE.md status_snapshot as_of="2026-08-05" while two of its lines now carry 08-06 content | REJECTED | Bumping that attribute is a claim that every line below it was re-read, and I re-read two. The ACTIVE_SPRINT precedent is explicit that a date bump is a claim and must not be stamped on content merely assumed still true. Both edited lines carry their own inline dates, so the file is not misleading; moving the attribute would make it so. Left deliberately, recorded here so the decision is visible rather than merely unmade.
NIT-8 CLAUDE.md headroom down to 248 bytes | REJECTED | Not a defect of this change - net +79 bytes, and the snapshot's own staleness note already governs consolidation. Raised to visibility rather than actioned; the next session to add a snapshot line should rotate a shipped arc out first.
```

## What the reviewer could not verify, carried forward rather than buried

- **The re-measured pass/fail/skip counts (10313 / 0 / 0 / 129).** Unverifiable without a
  run, which the reviewer correctly declined to make while the battery held the box. It
  corroborated the *timing* independently — a pytest tmpdir tree with 8,940 entries spanning
  16:48:07 to 16:53:39 — but the counts rest on the author. They are, however, now
  cross-checked from a second direction: the addend tables above were measured by collection
  in four separate worktrees and both totals land exactly on 10313 and 10244.
- **"settings 8/8 conform"** — the reviewer verified T7's two locks directly from the
  scheduled task and the campaign file but did not run the script; the other seven checks are
  unchecked by it.
- Inventory columns beyond the seven claims it spot-checked.

## The one thing this review changes about how I work

A stopped subagent is not a subagent that produced nothing. I killed six agents for
contention, correctly, and then assumed their work died with them — so I re-derived one
result by hand, and declared another impossible while it sat completed on disk. Check the
artifacts before inheriting a narrative about them, including your own.
