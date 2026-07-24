---
title: Publication Program — Author Kit
status: living
area: research
---

# Author Kit — working rules for every piece in the publication program

Binds every author session, surveyor, and reviewer in the program. The README's §0
standards expanded into operating procedure. Where a rule here and a venue's own rules
conflict, the stricter rule wins.

---

## A. Claim discipline — every claim is typed

Every factual statement in a draft is one of three types, and the draft's claims table
(handed to the review panel) types each one:

- **MEASURED** — a number from a recorded run. Cite the exact source:
  `PERFORMANCE_LOG.md` dated entry and/or the `docs/performance/*.json` row. State the
  conditions with the number (model, precision, context length, device, driver). A
  measured claim without its conditions is an overclaim.
- **DOCUMENTED-EVENT** — something that happened, evidenced on disk: journal entry
  (date + title + archive volume), commit SHA, ticket, PR URL. Quotes verbatim only —
  no reconstructed dialogue, no paraphrase presented as quote.
- **INTERPRETATION** — our reading of what the events mean. Always marked as ours
  ("we read this as…", "our conclusion from this incident…"), always hedged to the
  evidence scope, never load-bearing for a MEASURED or DOCUMENTED-EVENT claim.

Rules: no claim types itself; if a sentence mixes types, split it. If a claim cannot
be typed, it does not ship.

## B. The date-and-number verification pass (mandatory, LA amendment 1)

Before any draft goes to the review panel, the author re-derives **every** date,
count, duration, version, and figure from its primary artifact and lists each in the
ceremony memo with its source. Known traps, named because they were actually hit:

1. **Journal age ≠ project age.** The journal was born 2026-05-21 (465 entries through
   2026-07-17 — 58 days). The project's first commit is 2026-02-04. Neither is "years."
2. **Upstream state moves.** "Merged" is claimed only after checking the PR via the
   GitHub API (`pulls/{n}` → `merged`, `merged_at`) ON THE DAY the claim is made.
   Release-inclusion is a separate fact — verify against the release notes/tags, never
   inferred from the merge.
3. **Superseded figures.** PERFORMANCE_LOG entries supersede each other (e.g. the
   2026-05-22 spec-decode figure was later superseded by the tuned-draft result; a
   same-evening addendum superseded a cross-runtime comparison). Always take the
   LATEST entry for a figure and check for addenda before citing.
4. **Counts drift.** Gate counts, lesson counts, entry counts change weekly. Cite them
   AS OF a date, re-checked on that date (`grep -c` the artifact, don't trust prose).

`VERIFIED_FACTS.md` holds the program's checked sheet with per-fact sources and
verification dates. Volatile facts there are marked and MUST be re-verified at draft
time; the sheet is a starting point, never a substitute for this pass.

## C. Citation formats

- **Repo artifact:** `path` @ short-SHA (public-mirror path in print, never a local
  absolute path). Verify the SHA against file history (`git log -- <path>`) before
  print — no placeholders, ever.
- **Journal:** entry date + exact title, naming the archive volume
  (`docs/archive/journal/2026-MM.md`) or the anthology. Quotes diffed verbatim.
- **Dataset:** the `docs/performance/<file>.json` filename + the PERFORMANCE_LOG.md
  dated entry it pairs with. Methods cited with the data.
- **Upstream:** full URL + state ("merged 2026-07-08" / "open") + how verified (API) +
  access date.
- **External sources:** T1/T2 (see rubric §I) with access date; take an archive
  snapshot (web.archive.org) of anything load-bearing before citing it.

## D. Privacy / leak screen (per draft; same standard as the public-mirror leak gate)

- Source ONLY from content classes that are already public or clear the public-mirror
  leak gate: the anthology text, the performance dataset, the public mirrors, merged
  upstream PRs/issues. When unsure whether something clears, EXCLUDE and flag it in
  the ceremony memo.
- Never in print: personal data beyond the LA's chosen public handles
  (blairducrayoppat on GitHub); local usernames, hostnames, absolute paths; device
  identifiers beyond the published hardware spec; security-sensitive residuals (open
  vulnerabilities, unpatched gaps, key material, live configuration details of the
  egress/policy machinery beyond what the public mirror exposes).
- Framing compliance: "personal research project" / "long-term local AI system" —
  never "prototype," never "nearly done."
- Tone compliance: no vendor-bashing, no praise-seeking; collaborative-upstream
  register wherever a community or maintainer is named; softened certainty in public
  prose — exact numbers stay exact.

## E. Single-case (n=1) framing language

Standing phrases (adapt, don't weaken): "a documented single-project case study" ·
"one build, fully instrumented" · "this is what happened on one system, recorded as it
happened — not a controlled study" · measurements scoped "on this hardware/software"
· "in this project we observed…" never "systems generally…". The strength IS the
documentation: everything cited, everything checkable. Claims about generality are
INTERPRETATION-typed and hedged, or cut.

## F. AI-authorship disclosure — DECIDED (LA ceremony 2026-07-19): full transparency

The stance is **full transparency, uniform across every piece**. Standing boilerplate
(placement adapts to venue; the substance never weakens):

> This piece was drafted with the AI development fleet it describes, working from the
> project's build journal, decision records, and measured performance logs; the human
> author directed, reviewed, and approved every claim.

Venue interactions: **IAPP** bars content created "in whole or in part" by generative
AI without prior written consent — the decided path is that the LA authors IAPP
variants himself, by hand (which also embodies P5's thesis). Disclosure is venue
compliance as well as integrity. Per-piece LA approval before any publishing action
remains the standing rule regardless of stance.

## G. Voice guide per tier

- **Technical / data-first (P1):** precise, numbers-forward, methodology visible, zero
  hype. The reader is a practitioner who may try to reproduce. Lead with the result,
  then conditions, then method. Tables for numbers; prose for meaning.
- **Security education (P2, P4):** specimen-report register — setup, collision, root
  cause, structural fix, transferable rule. The reader wants the failure class, not
  drama. Name principles (fail-closed, deny-by-default) precisely.
- **Engineering epistemology (P3):** essay register; every abstraction cashed out in a
  documented incident within a paragraph of its introduction. No incident, no claim.
- **Flagship / governance case study (P5):** measured, specific, respectful. The LA's
  role described with precision and dignity — a governance layer that worked — never
  cutesy, never condescending, never self-congratulatory on the fleet's behalf.
- **Accessible narrative (P6):** warm, concrete, honest about limits and costs. Same
  claim discipline — simplification never changes a claim's truth value.
- **Practitioner short (P7):** rule-first, example-backed, tight. One idea, one page.

## H. Structural requirements (LA amendment 4)

- **Every expert-facing piece (P1–P5, P7):** a prior-work treatment fed by the novelty
  survey verdict and deepened by the author session's own pass — name the closest
  prior work and say plainly what this piece adds. P6 links out instead.
- **Every data piece:** a methods section in the existing community-grade format —
  hardware (CPU/GPU/NPU, RAM), OS + driver + OpenVINO versions, model + precision,
  methodology (prompt set, config, run counts), the measured numbers with conditions,
  AND a "what was not measured" paragraph.
- **Every piece:** n=1 framing (§E); the claims table (§A); the §B pass; the privacy
  screen (§D); the venue's own rules honored (from the survey verdict).

## I. The shared novelty + venue survey rubric (LA amendment 3)

Given verbatim to all seven surveyors so verdicts are comparable. Authors re-run the
same rubric deeper at Phase 1.

### I.1 What counts as prior art

A published item is PRIOR ART for a piece only if it substantially overlaps on ALL
three axes: (a) thesis/claim, (b) evidence type (measured data vs anecdote vs survey
vs opinion), (c) audience/register. Overlap on one or two axes = RELATED WORK (goes in
the map, doesn't block). "Someone mentioned this idea once" is not prior art; "someone
published substantially this piece, credibly" is.

### I.2 Recency windows

- Hardware/model performance claims: hard scan of the last **18 months**; older
  material is context, not competition (the substrate moves too fast).
- Security architecture / agent-governance: last **3 years** + canonical classics.
- Epistemology / process essays: last **5 years** + classics.
- Venue mechanics (rules, submission process): **current pages only, fetched live**,
  access-dated.

### I.3 Source-quality tiers

- **T1 — primary:** peer-reviewed papers; official vendor/project docs; first-party
  measurements with published methodology; a venue's own rules/about/FAQ pages.
- **T2 — expert practitioner:** named authors with a track record; substantive
  engineering blogs; maintainer posts.
- **T3 — community threads:** Reddit/HN/forum discussions. Evidence of interest and
  demand, NEVER of truth. T3 alone cannot support a "this already exists" kill —
  saturation claims need T1/T2 instances.

### I.4 Required verdict structure (one page per piece, exactly these sections)

1. **Prior-art map** — who, what, where, when, tier, link (access-dated).
2. **The gap** — what our data/story adds that the named prior art lacks; or
   "nothing — saturated," with the T1/T2 instances that prove it.
3. **Verdict** — STRONG-GO / GO / RESHAPE (say what to change) / KILL, with reasoning
   an expert in that space would accept.
4. **Venue fit** — for EACH candidate channel: fit judgment; submission mechanics (how
   to post/submit, account/karma/age requirements, moderation gates, review
   timelines); the venue's posting AND self-promotion rules, from its own pages,
   quoted or tightly paraphrased with link + access date; **2–3 gold-standard exemplar
   posts** (link + one line on why each is the bar).
5. **Piece-specific risks** — overclaim traps, saturated angles, sensitive content,
   framing hazards.

### I.5 Survey conduct

Read-only everywhere (README §0.3): no posting, commenting, voting, subscribing, or
account creation. Primary sources for venue rules — the venue's own pages, not
secondhand summaries. If a rules page is inaccessible (bot-blocked, login-walled), SAY
SO explicitly and mark the gap — never guess or fill from memory. Access date recorded
for every cited URL. Facts about OUR project come from `VERIFIED_FACTS.md`, not from
memory or this kit's examples.

## J. Research conduct (standing, all phases)

Web research is Claude-side dev-tool work and fully permitted — but READ-ONLY. The
identity split holds: nothing about this program touches BlarAI's runtime, and no
session ever engages a community (post/comment/vote/DM) without the LA's explicit
per-piece approval of that specific action. GitHub API reads are fine; GitHub writes
(comments, issues, PRs) are out of scope for this program's sessions.
