---
paths:
  - "BUILD_JOURNAL.md"
  - "LESSONS.md"
  - "FIELD_NOTES.md"
  - "docs/journal_fragments/**"
  - "docs/archive/journal/**"
  - "docs/archive/lessons/**"
  - "docs/BUILD_JOURNAL_ANTHOLOGY.md"
  - "tools/doc_hygiene/**"
  - ".claude/rules/journal.md"
---
<journal_discipline priority="non-negotiable">
- Three surfaces: BUILD_JOURNAL.md (narrative — HOT = current month only; prior months live verbatim in docs/archive/journal/ volumes + one-line INDEX; docs/BUILD_JOURNAL_ANTHOLOGY.md is the curated 64-gem front shelf), LESSONS.md (three-tier since 2026-07-19: hot = Rules + Canonical Tier + Canon-32 + one-line index of every lesson; full text append-only in docs/archive/lessons/LESSONS_ARCHIVE.md; its Rules section is the authoritative curation SOP; numbers are permanent, never renumber), FIELD_NOTES.md (mechanical gotchas — grep it before touching a named surface).
- Entry form: dated `### YYYY-MM-DD — <title naming the LESSON, not the change>` header, plain-language subtitle (`*Plain summary: …*` — the searchable index line), first-person narrative prose (not bullets, not changelog), specific numbers, real commit SHAs (no placeholders except self-reference), trade-offs with the rejected path named, ends with **Next:**. No emoji. Sized to the judgment, not the bookkeeping.
- Anti-patterns (forbidden): vague entries with no measurement/trade-off/lesson; changelog bullets as narrative; trade-off-free entries; sanitized entries hiding the failure path; status-shaped entries (no failure, no trade-off, no lesson → belongs in the ledger, not the journal); minting a lesson number without searching LESSONS.md first.
- Failures stay in. Sanitized journals don't compound; mock-passed-but-prod-crashed entries are the most valuable.
- Lesson curation: search LESSONS.md's hot index + Canonical Tier before minting a number; recurrence → dated tally on the lesson's full text in the archive volume + bump its ↺ flag on the index line; THIRD instance MUST ship a structural control (gate test / CI check / hook) in the same change. Mechanics → FIELD_NOTES.md; transferable judgment → the lesson. Quarterly consolidation pass next due 2026-10-01.
- Monthly retrospective: at each month's end (or first quiet tree after), one session writes a `### YYYY-MM-DD — Monthly retrospective: <arc title>` entry — the wide shot that makes the arc legible. The SAME session runs the rotation (tools/doc_hygiene/rotate_log.py): prior month → its docs/archive/ volume + INDEX line-batch (journal now; PERFORMANCE_LOG once its rotation ships), and promotes any new gems into the anthology.
- Parallel sessions: write fragments to docs/journal_fragments/ (one file per entry; lessons proposed, never pre-numbered), NEVER append BUILD_JOURNAL.md directly. One integrator folds fragments proactively at lulls (after a merge cluster, not sprint close), numbers lessons serially, deletes fragments. A single session alone on a quiet tree may write BUILD_JOURNAL.md directly.
</journal_discipline>
