# Overnight report — 2026-07-28 → 29: the complete advanced intake, landed

## What landed (all merged to main, all DORMANT behind their own switches)

The whole remaining advanced-intake program was built, independently reviewed, fixed,
re-verified, and merged tonight:

| piece | merge | dormant switch | review |
|---|---|---|---|
| S3-F coverage gate ("won't let you sign what it couldn't check") | `cf7b5273` | `advanced_intake_coverage_gate` | NEEDS-FIXES → 7 fixed + 1 ticketed (#1155) → **VERIFIED** |
| S3-G criteria revision (the machine wall) | `6f661d10` | `advanced_intake_criteria_revise` | NEEDS-FIXES → 4 fixed + 1 ticketed (#1156) → **VERIFIED, verdict MERGE** |
| S2 elicitation interview design (reviewed BEFORE build, per your instruction) | `e8620a46` | — | APPROVE-WITH-FIXES → all 8 folded pre-build |
| S2 elicitation interview build | `5848469e` | `advanced_intake_interview` | NEEDS-FIXES → all 5 fixed → **VERIFIED** |
| Journal fold + doctrine sync | `b59253e9` | — | 14 entries folded; lessons 315–326 minted |

**Final measured gate on merged main: 9417 passed / 0 failed / 0 skipped** (was 9315 —
+102 new locks). Every slice's reviewer verified the fix round personally; disposition
records are in `docs/reviews/*-2026-07-28.md`, all machine-checked PASS.

The review process earned its keep three separate times tonight:
- The **design** review caught a bug before the code existed (F1: the `advanced` token
  would have eaten the first word of an operator's answer — the exact
  eats-operator-text class that cost you 2,200 characters on 07-27).
- The **F code** review caught a genuine fail-open I wrote: the gate's release decisions
  read "could not measure" as "measured clean." Fixed with a measured-clean-only rule.
- The **G code** review caught that revised visual criteria never reached the VLM design
  loop — you'd have approved one checklist while the build optimised another.

## What the battery did

**B2 GREEN (1,995s) and B4 GREEN (2,972s) — B4's first green after three consecutive
parked nights.** Lean pass 8 banked, runner exit 0, task re-armed for 23:00. The one
change of record was the frame-cap fix (`4553912a`), and B4 went green via
"already-satisfied" skips — an unusual signature I banked on #1066 as evidence, not a
conclusion; that diagnostic arc still owes its forensics.

Your freeze-line discrepancy, localized: the **nightly** report now prints the correct
two-counter line ("LEAN pass 8 BANKED … 3/5"); the stale "FROZEN at 0/5" text comes from
the **daytime/targeted-run report path** only. The fix belongs in agentic-setup's
instrument — not touched tonight (Rule 2).

## Dormant awaiting your ceremonies — the honest evidence split

Per your instruction, per slice: **proven by test** vs **executed against the real model**.

- **D, E, F, G, S2**: proven by test only (comprehensively — every behaviour, every
  toggle-off, through the real corridor and the real encrypted store), fix-verified by
  independent reviewers. **None has yet run against the real 14B**, deliberately: the
  overnight permission layer blocked even a backup copy of `default.toml`, so I flipped
  nothing while you slept — the conservative reading of your "no posture flips" rule. The
  dormant slices' first real-model exercise is the ceremonies' own live-verify step, with
  you present, which is where the runbooks always put it.
- **S1 + the live quick path**: exercised against the real model in tonight's live-verify
  window (running as you read this): merged main boots, serves, and plans a real dispatch
  end-to-end through every seam rewritten tonight, with the S1 floors firing and every
  dormant default measurably INERT live.

## Deliberately left for you

1. **The batched S3 ceremony** — `docs/runbooks/advanced_intake_s3_batched_ceremony.md`.
   Four independent switches, one sitting, one real dispatch per behaviour; each is
   yours to decline individually. Includes timing a gapped-plan cold PLAN against the
   720s budget (review F8).
2. **The S2 ceremony** — `docs/runbooks/advanced_intake_interview_go_live.md`, where its
   one open decision is settled: what `advanced` does on a project with remembered
   answers (built as defer-to-memory + honest notice; override is buildable if you
   prefer).
3. **The machine wall ratification** — G ships stricter than the design doc (machine
   criteria keep-only; the argument is in the config comment). Ratify or loosen at the
   ceremony.
4. #746 and the multi-page-website work: untouched, per your brief. #1066 forensics:
   untouched, new evidence banked.
5. Residual tickets filed tonight: #1155 (QA-regeneration pin), #1156 (parked
   pre-ceremony plans × floor injection — closes with the ceremony), #1158 (the dispatch
   harness LIVE mode needs S2's two gateway kwargs — land before the S2 ceremony if you
   want to drive it through the harness).
6. My five worktrees (wt-1069-f/g, wt-1031-s2/s2docs, wt-fold) — merged and reported;
   I'll remove them as post-ceremony cleanup. ~20 older worktrees from prior sessions
   remain inventoried and untouched.

## Incidents & corrections (kept in, per the journal rule)

- I posted two board comments with derived (wrong) timestamps early in the night;
  corrected on-ticket within minutes (#1069 c.2614). Measured every stamp after.
- `test_graduation_reset_stamps_current_mode_immediately` failed ONCE in six full gate
  runs (interaction-only; passes standalone; never recurred). Recorded in
  TEST_GOVERNANCE — re-observe before ticketing.
- The auto-mode classifier blocked config-file touches (including a plain backup copy);
  I stopped rather than work around it, and the flags-on live exercise moved to your
  ceremonies. If you want overnight sessions able to do bounded verify windows, that's a
  permission-settings decision for daylight.
