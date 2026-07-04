# Lessons Teaching Deck — what building BlarAI taught, one lesson at a time

A self-contained HTML study deck over the project's `LESSONS.md` lessons
(formerly the top of `BUILD_JOURNAL.md`; moved 2026-07-03),
built for the Lead Architect's IAPP AIGP (Artificial Intelligence Governance
Professional) certification track. **Pedagogical, NOT gate-critical** — it
teaches the journey; it is not a posture review (that is the capstone deck at
`docs/security/capstone_2026-06/`).

## What it teaches and how

**126 study units** — the journal's 107 numbered lessons plus 19 units drafted
from the June 2026 fragments not yet folded into the numbered list (those
carry no numbers; numbers are assigned only at fold-in). Each unit is a small
slide cluster:

1. **The failure** — the real story that caused the lesson (real numbers, real
   commit SHAs, unsanitised), ending in a think-first question.
2. **The mechanism, drawn** — where the failure has moving parts, a diagram of
   them (most units), plus big-number stat callouts for the measured ones.
3. **The lesson + growing from it** — the distilled principle, then the
   mechanism underneath it and how to recognise the pattern anywhere.
4. **The AIGP connection** — the governance idea the failure exemplifies,
   in verified Body of Knowledge v2.1 / NIST AI RMF / ISO-IEC 42001 / OECD /
   EU-AI-Act vocabulary, with a one-line exam-ready takeaway.

**The core path.** The deck OPENS on a curated 31-lesson track
(`core_path.json` — selection criteria recorded there): the most
governance-loaded lessons, roughly 2–3 hours of study. Navigation in core mode
walks only those units; press `c` (or the bar button) for the full 126-unit
archive. Honest scope note, also on the deck's AIGP-frame slide: the lessons
map mostly to Domains I, III and IV — Domain II (laws as applied to AI) needs
the official IAPP materials; this deck complements them, it does not replace
them.

Structure: a prologue (lesson #1, the founding failure) + seven thematic acts
(each with its own accent color) + the June 2026 arc. Sequential study is the
intended default; the journey index (`i`) supports jumping. Study progress
("mark studied", resume position, core/full mode) lives only in the browser's
localStorage — nothing leaves the machine.

## Viewing

Double-click `lessons_deck.html` (everything is local — `mermaid.min.js` is
vendored; no network at view time), or serve the directory:

    python -m http.server 8763 --bind 127.0.0.1 -d docs/learning/lessons_deck

Keys: arrows/space/PgUp/PgDn move slides; `n`/`p` jump a whole lesson; `c`
toggles core path / full deck; `i` opens the index; `Home` returns to the
title.

## Pipeline (regenerating after the journal grows)

    acts/act1.json .. act8.json     # teaching content, one file per act
    core_path.json                  # the curated default study track (+criteria)
    aigp_vocabulary.md              # the ONLY allowed framework vocabulary
    SCHEMA.md                       # the act-file contract + drafting disciplines
    validate_acts.py                # mechanical gate: schema, rosters, budgets,
                                    #   vocabulary allowlist, diagram/stat lint,
                                    #   core-path cross-check, anti-hallucination
                                    #   (every cited entry + SHA must exist in
                                    #   BUILD_JOURNAL.md + LESSONS.md / the
                                    #   source fragment);
                                    #   emits aigp_mapping_report.md for review
    build_lessons_deck.py           # renders lessons_deck.html
    verify_deck_html.mjs            # parses every diagram EMBEDDED in the HTML
                                    #   (borrows the capstone _validate Node
                                    #   toolchain from the main checkout)
    run_checks.py                   # ONE COMMAND: validate -> build -> diagram
                                    #   parse -> headless render audit (paint
                                    #   spills, overflow, per-slide) -> headless
                                    #   functional self-test [-> --shots]

    python run_checks.py            # the full battery; add --shots sample|all
                                    # for a screenshot sweep at 1440x810

When June fragments fold into the numbered list: move their units from
`acts/act8.json` into the thematic act where each lesson lands, set the
assigned `number`, update `EXPECTED` in `validate_acts.py` (and `core_path.json`
if the new lesson belongs on the core track), then `python run_checks.py`.
The deck is a living study artifact — it grows with the journal.

The headless audit exists because of a real bug class: the 2026-06-10 build
caught a mermaid diagram whose PAINT overflowed its layout box (nodes drawn
over later content) — layout-geometry checks alone do not see it. The audit
measures rendered ink against its card on every slide; `?audit=1` /
`?selftest=1` are the in-page hooks it drives (they use a separate
localStorage key, so tests never touch real study progress).

## Companion files

- `learning_log.md` — the cross-session study record, kept by the presenter
  session (the deck's localStorage is per-browser convenience; the log is the
  canonical record). Coverage table marks the core path ◆.
- `aigp_mapping_report.md` — generated per-unit mapping table (act, lesson,
  core/mech flags, domains, frameworks, takeaway) for review.
- `_audit_report.json` — the latest headless audit result (generated).

Vikunja ticket: #650. Sources: `LESSONS.md` (numbered lessons; moved out of
BUILD_JOURNAL.md 2026-07-03), `BUILD_JOURNAL.md` (dated entries) and
`docs/journal_fragments/*.md` (June 2026).
