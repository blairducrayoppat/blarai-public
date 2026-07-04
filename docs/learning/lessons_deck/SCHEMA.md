# Lessons Deck — act content schema + drafting disciplines

Each act of the deck is one JSON file at `acts/act<N>.json`, drafted from
`BUILD_JOURNAL.md` + `LESSONS.md` evidence (the numbered lessons list moved to
`LESSONS.md` on 2026-07-03; entry narratives stay in the journal). The build script (`build_lessons_deck.py`) consumes
all act files plus `core_path.json` and renders the deck. This file is the
contract.

## JSON schema

```json
{
  "act": 1,
  "title": "Show me it running — honest verification & measurement",
  "subtitle": "one-line act framing",
  "aigp_intro": "60-120 words: what this act's theme is, and which AIGP domain(s)/framework ideas it trains. Uses ONLY aigp_vocabulary.md vocabulary.",
  "aigp_domains": ["Domain III — Understanding How to Govern AI Development"],
  "lessons": [
    {
      "number": 2,
      "prologue": false,
      "fragment": null,
      "title": "\"Show me it running.\"",
      "failure": "90-150 words. The concrete story from the journal that CAUSED the lesson: what was believed, what was done, what actually happened. Real numbers, real commit SHAs, real file names — verbatim from the journal, never invented. This is the hook; it must read as a story, not a summary.",
      "evidence": ["2025-12-04 — Entry title as it appears in the journal", "commit abc1234"],
      "lesson": "40-80 words. The distilled principle. Start from the journal's own bold lead-in and its paragraph; tighten, do not dilute.",
      "growth": "90-150 words. The beat the learner asked for: WHY the failure happened (the mechanism underneath, not the surface mistake), and how to recognize/prevent the pattern in any future project. Address the learner directly as 'you'. Generalize beyond this codebase.",
      "growth_question": "One Socratic question shown BEFORE the lesson is revealed, e.g. 'What property did the green suite actually prove — and what property was being claimed?'",
      "aigp_text": "50-90 words. The governance principle this lesson exemplifies, named accurately per aigp_vocabulary.md. Say how the lived failure maps to the named domain/framework idea.",
      "aigp_domains": ["Domain III — Understanding How to Govern AI Development"],
      "aigp_frameworks": ["NIST AI RMF — MEASURE (TEVV)"],
      "aigp_takeaway": "≤25 words, one line, the exam-ready takeaway.",
      "diagram": "OPTIONAL mermaid string — the failure's mechanism, drawn (see Visual fields)",
      "stat": [{"before": "259 sessions", "after": "15 shipped code", "label": "the factory's real output"}]
    }
  ]
}
```

Field notes:
- `number`: the lesson's number in `LESSONS.md` (the Lessons Learned list, formerly at the top of BUILD_JOURNAL.md); `null` for Act VIII June units (numbers are assigned only at fold-in).
- `fragment`: for Act VIII units whose source fragment still exists on disk, the fragment filename; `null` otherwise — a unit whose fragment has since been folded into the journal anchors its `evidence` to the folded dated entry instead.
- `title`: the journal's bold lead-in phrase, verbatim (trailing period optional).
- `evidence`: pointers a reader can follow — the dated journal entry (its `### YYYY-MM-DD — Title` header) and any commit SHA the journal itself cites. Never cite a SHA the journal does not contain.

## Visual fields (v2, 2026-06-11)

- `diagram` (optional): a mermaid string rendered on the unit's own "mechanism"
  slide between the failure and the lesson. Include ONLY where the failure has
  real mechanism — a flow across components, a seam, a sequence/race, a
  topology. Constraints (mechanically linted by `validate_acts.py`, then
  genuinely parsed by `verify_deck_html.mjs` and rendered by the headless
  audit):
  - first line exactly `flowchart TD`, `flowchart LR`, or `sequenceDiagram`;
  - every node label double-quoted (`A["label"]`), `<br/>` for line breaks,
    label lines ≤38 chars and ≤3 lines per node, ≤12 nodes/participants;
  - NO `classDef`/`style`/`linkStyle`/`click`/`%%{` directives (the deck theme
    owns the styling); write `and` rather than `&`;
  - the diagram must show the MECHANISM (what talked to what, where it broke),
    never restate the title. A diagram that adds nothing is left out — a unit
    without mechanism simply has no mechanism slide.
- `stat` (optional): 1–3 big-number callouts, each
  `{"before": "...", "after": "...", "label": "..."}` or
  `{"value": "...", "label": "..."}` — ONLY figures the journal/fragment states
  verbatim. Rendered on the mechanism slide when one exists, else on the
  failure slide.

## The core path (`core_path.json`)

The curated default study track lives in `core_path.json` (sibling file), NOT
in unit fields — selection is the integrator's call, with criteria recorded
there. The validator cross-checks that every named unit exists; the build
fails on unknown units.

## Drafting disciplines (non-negotiable)

1. **Honesty.** Failures stay in, fully. No sanitising, no softening, no "this
   was actually fine". The teaching value IS the failure path.
2. **Specificity.** Exact measurements (`17 GB → 8.7 GB`), exact counts, exact
   SHAs — copied from the journal. If the journal gives no number, write none.
3. **Evidence-bound.** Every `failure` beat must trace to the journal: the
   lesson's own paragraph and, where one exists, the dated entry that tells
   the fuller story. Search the journal body for the lesson's key phrases to
   find its entry before drafting.
4. **Readable by a non-developer.** The learner is a self-taught builder, not a
   career engineer. Briefly gloss any term of art the first time a unit uses it
   ("mock (a stand-in object that fakes a dependency)"). Each unit is studied
   in isolation — expand acronyms on first use PER UNIT.
5. **Voice.** Failure/lesson/aigp beats: factual third person about the project
   ("the agent", "the suite", "the operator"). Growth beat: second person
   ("you"), coaching tone.
6. **No emoji. No bullet lists inside beats — prose only.**
7. **AIGP accuracy.** Use ONLY `aigp_vocabulary.md` vocabulary. Frameworks are
   voluntary — lessons "exemplify" them, are never "required by" them. All
   mappings are draft until the integrator verifies them.
8. **JSON validity.** Before finishing, run
   `python -c "import json; json.load(open(r'<your file>', encoding='utf-8'))"`
   and fix any error. UTF-8, no BOM, no trailing commas.
9. **Verify the whole deck after content changes** — one command:
   `python run_checks.py` (validate → build → diagram parse → headless
   render audit + functional self-test). See README.
