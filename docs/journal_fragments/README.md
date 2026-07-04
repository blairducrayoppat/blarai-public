# Journal Fragments — a parallel-safe inbox for BUILD_JOURNAL.md

`BUILD_JOURNAL.md` (repo root) is a single curated narrative — the load-bearing
portfolio surface. That single file is also a merge-conflict magnet the moment two
sessions append to it on different branches: the append region collides on every
integration. It has bitten repeatedly — the Tier-1 security wave, the web-search
branch's merge of `main`, the 2026-06-05 spec-decode commit.

This directory is the fix. It costs nothing when you work alone and removes the
conflict entirely when you don't.

## When to use a fragment

- **Parallel / multi-session work** (separate worktrees, separate Claude sessions,
  a fleet of agents): **always** write your entry as a fragment here. Never edit
  `BUILD_JOURNAL.md` directly while others might.
- **A single session alone on a quiet tree**: you may still write `BUILD_JOURNAL.md`
  directly, or use a fragment — your call.

## Writing a fragment

One file per entry:

    docs/journal_fragments/YYYY-MM-DD_<short-slug>.md

Because every session writes a *different* filename, fragments never conflict — they
merge cleanly in any order. A fragment carries exactly what a journal entry carries:

- the dated header `### YYYY-MM-DD — Title that names the lesson or arc`;
- a one-line plain-language subtitle (`*Plain summary: …*` — required since
  2026-07-03; the poetic title is the voice, the subtitle is the index);
- the first-person narrative (failures kept in — see the journal's own discipline);
- a closing `**Next:**` line;
- **if it earned a lesson**, first check `LESSONS.md` for the class:
  - a **recurrence** of an existing lesson is proposed as
    `**Recurrence of lesson N:** <one-line variant note>`;
  - a **genuinely new class** gets a `**Proposed lesson:** <text>` block —
    *described, not numbered*. Numbering is assigned at fold-in, serially, so two
    parallel sessions can never grab the same number (the exact collision that made
    this directory necessary);
  - a **mechanical gotcha** (API trap, engine dialect, driver quirk) is proposed as
    `**Proposed field note:** <text>` for `FIELD_NOTES.md` instead.

## Fold-in (the integrator's job)

At a quiet point — sprint close, or any time the main tree is uncontended — one
session folds every fragment in:

1. append each fragment's `###` entry into `BUILD_JOURNAL.md`'s Journal section,
   in date order;
2. apply each lesson block under the curation rules at the top of `LESSONS.md`:
   recurrences become dated tallies on the existing lesson (a THIRD tally
   requires shipping the structural control the rule demands); new lessons get
   the next number; field notes land in `FIELD_NOTES.md`;
3. **downstream consumers**: if any folded fragment has study-deck units in
   `docs/learning/lessons_deck/acts/act8.json`, run that deck's README
   migration (move units to thematic acts, set numbers, update `EXPECTED`,
   `python run_checks.py`) in the same fold — the 2026-07-02 fold skipped
   this and left the deck validator red (#731, lesson 44 recurrence);
4. delete the folded fragment files;
5. commit the fold-in as a single, serial operation.

The fold-in touches `BUILD_JOURNAL.md`, `LESSONS.md`, and `FIELD_NOTES.md` from
exactly one session, so it never conflicts. Those files remain the canonical
record; fragments are only their staging area.
