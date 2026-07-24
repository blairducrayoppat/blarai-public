---
title: "Does the answer reach the screen, and how big should a task be? — research read"
date: 2026-07-21
audience: Lead Architect (plain language)
provenance: high-trust sources only (peer-reviewed, primary framework docs, major-lab engineering); every claim cited; read-level noted per source by the researching agent
origin: LA questions during the #877 Bill Splitter front (dimension-4 seam question; dimension-1 "what grain should I expect")
---

# Does the answer reach the screen, and how big should a task be?

*Both of the questions you raised this morning turn out to sit on well-mapped ground — and on both, the published evidence says your instincts were right.*

## Question 1 — "Do we need a check that a result was even sent to the user?"

**Yes — and the testing field's central principle is aimed at exactly the gap you spotted.** The most-cited guidance in modern UI testing says: *"The more your tests resemble the way your software is used, the more confidence they can give you"* — and specifically, that tests should examine the **page structure the user sees** (the DOM — Document Object Model, the browser's live tree of everything on the page), not the internal functions that compute what *should* appear. Our generated exams currently assert that the display *function returns* the right sentence; the failure you're worried about — computed correctly, never placed on the page — passes that test and is a named, studied failure class called a **false positive**: tests green, app broken.

**The cheap fix exists and is standard practice.** A simulated page (tools called jsdom or happy-dom) lets a test actually render the app, type into its fields, and then check the visible text landed in the page — at ordinary unit-test speed, no browser involved. This mechanically catches "computed but never inserted." Its honest limit, documented by the tools themselves: it can't tell if the text is present but *invisible* (hidden by styling), because simulated pages don't do visual layout. Only a real browser check (e.g. Playwright's "is this visible" assertion) covers that last step — worth having as a heavier second tier, not as the default.

**The strongest independent evidence:** a 2025 benchmark (WebGen-Bench) evaluated AI-generated websites *only* by operating them in a real browser and checking user-visible outcomes — code inspection wasn't trusted at all. The best system tested passed just **27.8%** of those user-visible checks. Separately, controlled studies found AI-generated tests tend to encode *what the code does* rather than *what it should do*, and skew toward superficial assertions. Moving our assertion point to the user-visible seam is therefore not just more coverage — it makes the exam harder for the code's author-model to fool with its own blind spot, because the oracle becomes "what a person observes."

**What we do with this:** the fleet's web scaffold should render generated apps into a simulated page and assert visible output as a *standard* generated check — ticketed today (#1025, below). Your eyeball check stays as the visibility/layout tier above it.

## Question 2 — "What's an appropriately sized piece of work? I have no baseline."

**The literature's answer: bigger pieces than intuition suggests — often one.** The strongest peer-reviewed result (Agentless, FSE 2025) found that keeping the *whole* problem in one context, with a structured process around it, beat every autonomous multi-step agent framework it was compared against. A 2026 controlled study measured that splitting a job into a fixed upfront plan *increased* retry cost by 33–80% over just doing it as one piece, because one failed step forces redoing everything after it. And the team behind a leading commercial coding agent reports that splitting one job across parallel workers produces *conflicting implicit decisions* — components that don't fit together — concluding that a single continuous worker is the reliable default.

**The two principled sizing rules that do exist:**
1. **Split only along real seams** — a piece must be independently buildable *and independently checkable* (a module of its own, a dependency boundary). Never split inside one file: five tasks editing the same file is five decision-makers on one object.
2. **Split only when the whole is too big to do reliably in one go** — and current measurement (METR, 2025) puts that reliability horizon far above a one-file page for frontier models.

**Your calibration, concretely:** for a one-file tool like the Bill Splitter, the right expectation is **one build task** (plus its exam). This morning's cards showed you the whole spectrum — 1 was right, 3 was mild over-split, and July 15th's 7 was the measured failure (~80 wasted minutes). This also independently confirms the #989 diagnosis: the clean battery cards are exactly the ones where each task owns its own module — the literature's "real seams" rule, discovered by our own instrument.

## Honesty section — what the research could NOT establish

- No published study isolates the exact "logic right, page wiring absent" defect class in AI-generated code, and nobody has quantified simulated-page vs real-browser defect-catch rates head-to-head.
- No one has published the direct experiment our fleet keeps running informally: same goal, one task vs. several, measured success. Our own ledger data is genuinely ahead of the literature here.
- The evidence is not unanimous: one program-synthesis paper (different regime, not autonomous agents; the agent saw only its excerpt) reportedly found finer splitting *helped*. Named rather than hidden.
- The 33–80% retry-cost figures come from one recent group with a small evaluation — one data point, not settled science.

*Full source list with links and read-level notes preserved in the research agent's report (session record, 2026-07-21). Key sources: testing-library.com guiding principles; jsdom documented limits; Playwright best practices; Vitest browser-mode rationale; arXiv 2505.03733 (WebGen-Bench); 2410.21136 (oracle quality); 2407.01489/FSE'25 (Agentless); 2605.15425 (runtime decomposition); 2505.06120 (fragmented-spec cost); 2309.12499 (CodePlan); 2503.14499 (METR horizons); cognition.com "Don't Build Multi-Agents"; Anthropic "Building Effective Agents".*
