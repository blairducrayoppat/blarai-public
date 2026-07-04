# Directing the Machine — the Fable 5 Authored Edition

A **10–15 minute presented talk** (13 slides), distinct in kind from the study
deck at `docs/learning/lessons_deck/` (126 self-study units). This one is
rationalized for a live audience: hiring managers evaluating the operator's
ability to **manage AI-assisted development to a professional-grade product**,
blended with the AIGP (IAPP AI-governance) frame. Authored by Claude Fable 5
under LA direction, 2026-07-03 — itself an instance of the method it presents.

## Story spine

Cold open on the founding failure (259 autonomous sessions → 15 real code
commits) → the verify-live loop that replaced it → what shipped (credibility
montage) → the operating model (agents own mechanics; the human owns
capability/quality/risk/consent; the two questions) → four paid-for failures
(tests that shared the bug's blind spot; built-but-switched-off; the
flattering benchmark; security that fought the product) → the capstone (the
air-gap reversed as one reviewed act) → the evidence layer (journal/lessons
discipline) → what this means for a team → close.

Content budget is research-derived: rehearsed delivery ≈ 130–145 words/min,
≈ 1 slide/min ceiling → 13 slides, \~1,880 speaker-note words ≈ 13–14.5 min
with transitions. Rehearse against the built-in timer at the 13:00 pace.

## Using it

Double-click `fable5_deck.html` — fully local, zero network requests, system
fonts only, and **deliberately silent**.

| Key | Action |
|---|---|
| `→` / `space` / click | advance (staged reveals first, then next slide) |
| `←` | back |
| `N` | speaker-notes drawer |
| `T` | rehearsal timer (pace chip: ahead / on pace / behind vs 13:00) |
| `F` | fullscreen |
| `D` | **self-check** — verifies slide count, notes coverage, word budget, diagrams, silence, locality |
| `?` | help overlay |

**Why silent** (decided 2026-07-03 after the LA's live run judged the first
cut's synthesized ambient+cues counter-productive, and the research agreed):
professional-deck consensus is that sound effects trivialize content and
nothing in a transition should call attention to itself, and the
cognitive-science literature on the *Irrelevant Sound Effect* shows
task-irrelevant background audio measurably impairs verbal working memory —
and listening to the presenter IS a verbal task. The polish channel is
motion; the audio channel is the presenter's voice. (This also removes the
Zoom "share computer audio" failure mode entirely.)

**Zoom/Meet**: go fullscreen (`F`) before sharing; rehearse once with the
timer (`T`).

Respects `prefers-reduced-motion` (kills drift/reveal animation, renders
final states). Deep-linkable: `fable5_deck.html#7` opens slide 7.

## Editing

`fable5_deck.html` is the single source of truth (hand-authored — no build
step). `SPEAKER_NOTES.md` is **generated** from it for phone rehearsal;
regenerate after any notes edit:

    python extract_notes.py

Verification: `node --check` on the extracted script + the in-deck `D`
self-check + a human run-through. Every stat on a slide traces to
`BUILD_JOURNAL.md` / `LESSONS.md` / `CLAUDE.md` (259→15 lesson 1; 1,483
lesson 30; 1 Critical + 18 High the 2026-06-03 audit; 2.0×→1.4× lesson 7;
4,919 the 2026-07-02 standing gate; 256 entries / 196 lessons the 2026-07-03
restructure; three locks lesson 189; first packet 2026-06-12; fingerprint
egress 2026-07-02).
