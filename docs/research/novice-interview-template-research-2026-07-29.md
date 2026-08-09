---
title: "The novice interview — a reusable template for eliciting software requirements from a non-technical person"
status: RESEARCH — for the Lead Architect's consideration; no build implied
area: research
date: 2026-07-29
ticket: "advanced-intake programme (#1031 family) — operator question on the best reusable interview template"
grounded_at: "current-system facts read on disk 2026-07-29: shared/fleet/clarify.py (axes, caps, defaults, one-reply corridor), docs/design/advanced_intake_S2_elicitation_interview_DESIGN.md (the dormant 8-axis interview)"
---

# The best reusable interview between a solutions architect and a novice

**The question this answers** (the operator's words): what would make for the best
interview template that can be reused over and over, between a solutions architect
or business analyst and a novice individual consumer or business person who has
objectives to accomplish or problems to resolve via software built by the advanced
interview and the larger agentic coder process.

**How to read this document.** Part 1 is the template itself — plain language,
concrete enough to run tomorrow. Part 2 explains why each piece is shaped the way
it is, with the research behind it. Part 3 maps the template onto the system as it
exists today and proposes a maturation path. Part 4 lists every source, separating
the ones actually read from the ones only seen in search results.

---

# Part 1 — The template

## The seven rules the whole template obeys

1. **Ask about their life, never about software.** "Where will you be when you use
   this — at a desk, or out and about on your phone?" — never "what platform?"
2. **One decision per question.** Never two questions fused into one; a person
   answering a double question silently drops half of it.
3. **Every question is answerable three ways:** in their own words, by picking an
   offered option, or by saying "you decide" — and "you decide" always has a
   sensible default written out in plain words, which is recorded as an assumption
   they get to see.
4. **Concrete beats abstract.** "Tell me about the last time this happened" beats
   "how often does this happen?" "Show me one you like" beats "describe the style
   you want."
5. **The interviewer proposes, the person vetoes.** For anything a novice cannot
   be expected to think of (awkward edge cases, what to leave out, things people
   who want X usually also need), the interviewer offers a concrete proposal and
   asks yes/no — it never asks the novice to invent from a blank page.
6. **"I don't know" and "nothing" are always acceptable answers** and never stop
   the interview. They convert to a stated default plus a flag, not a blocker.
7. **Nothing is final until the playback.** The interview ends with the
   interviewer restating the whole plan in the person's own vocabulary and asking
   "did I get anything wrong?" — that restatement, corrected, is the contract.

## Phase 0 — Setting the table (no questions; four sentences)

Before the first question, the interviewer says, in roughly these words:

> "I'm going to ask you a short set of questions so I build the right thing. There
> are no wrong answers and no technical answers — everything is in everyday words.
> For any question you can answer in your own words, pick one of the options I
> offer, or just say 'you decide' and I'll choose something sensible and tell you
> what I chose. At the end I'll read my understanding back to you, and nothing is
> final until you've corrected it."

Why it exists: it defuses the two things that make novices freeze — fear of
answering "wrong," and fear that a technical question is coming. It also makes the
escape hatch discoverable before it is needed.

## Phase 1 — The story (open questions; no options offered yet)

The goal of this phase is the problem as it actually occurs in their life, told as
a story — because people are accurate about specific past events and inaccurate
about generalities and hypotheticals. Five questions, in this order:

1. **"Tell me about the last time this problem came up. What happened, step by
   step?"**
   (If they answer in generalities, the one follow-up is: "and the most recent
   time — what day was that, roughly, and what did you actually do?")
2. **"What do you do about it today — even if that's pen and paper, a
   spreadsheet, asking someone, or just remembering?"**
   (The current workaround IS the requirements document a novice cannot write:
   it names the real steps, the real data, and the real pain points.)
3. **"Who else is involved — who uses this, sees it, or is affected by it,
   besides you?"**
   (Consumer answers: just me / my family / people I share a link with. Business
   answers: my staff / my customers / my suppliers. The answer forks the build
   more than almost anything else.)
4. **"Imagine it's three months from now and this worked out perfectly. What's
   different for you? What are you not doing anymore, or doing for the first
   time?"**
   (This elicits the outcome, not a feature list. Features come from the
   interviewer later; outcomes can only come from the person.)
5. **"What's the one thing this absolutely must get right? And what's the one
   thing you're worried it will get wrong?"**
   (Asked as a pair. The first is the top acceptance criterion in their words.
   The second surfaces the anxiety — often the real requirement nobody would
   otherwise state: "I'm worried it will lose my data," "I'm worried it will
   look amateurish in front of clients.")

What the interviewer does with the story: it extracts, silently, everything the
story already answered — and never asks about those again. A story that says "on
my phone at client sites" has answered the where-will-you-use-it question; asking
it again teaches the person their story wasn't listened to.

## Phase 2 — The shape of the thing (one decision per question; options plus a default)

These are the decisions that most change what gets built. Each is asked ONLY if
the story didn't already answer it. Each offers concrete options AND the "you
decide" default, written out. The eight decision areas:

| # | Decision | The question, in novice words | The "you decide" default (read back and recorded) |
|---|---|---|---|
| 1 | Where it runs | "Where will you be when you use this — at a computer, on your phone out and about, or both?" | a simple app on this computer |
| 2 | Remembering | "Should it remember your information between uses, or start fresh each time?" | it remembers; your information is saved and there next time |
| 3 | The one job | "Of everything you've described, what's the ONE thing it must do well, even if the rest waits?" | the main thing you described works reliably |
| 4 | Look and feel | "Should it feel more like A or B: calm and professional, or colorful and friendly? Plain and dense with information, or spacious and simple?" (paired opposites, pick per pair) | a clean, simple, easy-to-read look |
| 5 | First-version size | "For the first version: the smallest thing that solves the core problem, or closer to the full vision at once?" | small and focused, covering the essentials |
| 6 | What it holds | "What real things should be in it on day one — your actual items, text, or numbers? Or should it start with clearly-labelled examples for you to replace?" | labelled example content — nothing invented that pretends to be real |
| 7 | When things go wrong | (Asked in Phase 4 as propose-and-veto, not as an open question — see below.) | wrong or odd input gets a clear message, never a crash or a silent guess |
| 8 | What it is NOT | (Also Phase 4, propose-and-veto.) | nothing beyond what you described — no speculative extras |

Two notes on this table. First, decision areas 1–8 correspond one-to-one to the
eight question areas the current system already defines (surface, persistence,
feature, visual, scope, content, edge, non-goal) — the template re-words and
re-sequences them; it does not replace them. Second, the look-and-feel question
works far better as paired opposites ("calm/colorful, dense/spacious") than as an
open "describe the style" — novices reliably pick between concrete poles and
reliably fail to describe aesthetics from scratch. The strongest look-and-feel
answer of all, though, is an example — which is what the next phase collects.

## Phase 3 — "Show me what you have" (the asset inventory)

This is the phase the operator explicitly asked for, and the one real agencies
never skip: before anything is built, walk through what already exists. Each item
is a yes/no/"not yet" — never homework that blocks the interview. The walk:

1. **Pictures.** "Do you have photos or images that should appear in it — of you,
   your products, your work, your places?"
2. **Brand or identity.** Business: "Do you have a logo, brand colors, or fonts
   you already use — even just 'the colors on my business card'?" Consumer: "Is
   there a look you already love — a favorite app, a color, a style?"
3. **Documents that hold the content.** "Is the information this thing needs
   already written down somewhere — a price list, a menu, a CV, a brochure, a
   Word document, notes on your phone?"
4. **Data.** "Do you have existing records it should start with or connect to —
   a spreadsheet, an export from another program, a list somewhere?" Follow-up:
   "where does that live today, and roughly how many entries is it?"
5. **Things to emulate.** "Are there websites or apps — anyone's, in any field —
   that you'd point at and say 'like THAT'? Screenshots are perfect too."
   Then, for each one, the load-bearing follow-up: **"What is it you like about
   it — the way it LOOKS, or the way it WORKS? Say a little about which part."**
   (A person pointing at a site may mean its colors, its layout, its simplicity,
   or one specific feature. The look-versus-works split is the single question
   that turns a vague gesture into a usable design instruction.)
6. **Previous attempts.** "Has anyone tried to build or buy something for this
   before — an old website, a half-finished app, code someone wrote, a tool you
   abandoned? Even a failed attempt tells me a lot."
7. **Things it must live with.** "Does it need to work alongside anything you
   already use — an email account, a calendar, a program you're not willing to
   give up?"

For every asset offered, the interviewer asks one disposition question: **"Should
I use this as-is, treat it as inspiration, or pull the information out of it?"**
— and records the answer next to the asset.

Standing rules for this phase: "nothing" is a normal answer and never blocks
(missing content becomes labelled placeholders, per decision area 6); an asset
promised "later" is recorded as a promise with a placeholder in the meantime; and
an asset the system cannot directly read (today, that includes images — see Part
3) is handled by asking the person to SAY what matters about it: "describe what's
in that screenshot that I should copy."

## Phase 4 — The awkward cases and the fence (interviewer proposes, person vetoes)

Novices cannot enumerate edge cases or scope boundaries from a blank page — those
are exactly the "unstated needs" that requirements research says people assume
rather than state. So the interviewer does the enumerating, concretely, from the
domain of the request, and the person only confirms or vetoes:

1. **Awkward cases, proposed.** Three to five concrete scenarios with a proposed
   behavior each, phrased like: "If someone types a price with a comma instead of
   a dot, I'll have it politely ask again rather than guess. OK?" / "If you open
   it with no internet, I'll have it show your saved information and say it can't
   update. OK?" Each is one yes/no, with "you decide" defaulting to the safe
   behavior in decision area 7.
2. **The fence, proposed.** "Here's what I'm planning to LEAVE OUT of this first
   version: [three or four named things adjacent to the request — e.g. user
   accounts, payments, a phone app]. Is anything on that list something you
   actually need? And is there anything I've included you'd rather drop?"
3. **The anticipation offer.** One question, clearly labelled as a suggestion:
   "People who ask for [this] often also want [X] — for example, a printable
   version, or a way to share it. Want that, skip it, or decide later?"
   (At most two such offers. More than two and the interview starts selling
   instead of listening.)

## Phase 5 — The playback (the contract)

The interviewer reads the whole understanding back, in the person's own
vocabulary, structured as:

- **Who it's for and the problem it solves** — one sentence, reusing their words
  from Phase 1.
- **What it does** — the one job, plus the supporting pieces, as a short plain
  list.
- **Where it runs, what it remembers, how it looks** — one line each.
- **What's in it on day one** — the real content and assets by name, each with
  its agreed disposition.
- **What it deliberately does NOT do** — the confirmed fence.
- **"Here's what I chose for you"** — every "you decide" default and every "I
  don't know," listed explicitly as assumptions.
- **"You'll know it works when…"** — five to eight checkable statements in
  everyday words ("…you can add a booking from your phone in under a minute";
  "…a wrong price gets a polite message, not a crash"). These become the
  acceptance checklist the build is graded against.

And it ends with the two questions that requirements research says to end every
elicitation with: **"Did I get anything wrong?"** and **"Is there anything I
should have asked you about that I didn't?"**

## What the interviewer INFERS and never asks, versus what it ASKS and never infers

| Always inferred (never asked) | Always asked (never inferred) | Proposed-with-veto (never open-ended) |
|---|---|---|
| Programming language, framework, database, file formats, hosting, architecture, security mechanics | Who it's for; the problem story; the one must-work thing; what it should remember; what it holds on day one; what already exists (assets); what it must live with | Awkward-case behavior; what's out of scope; anticipated extras |

The rule underneath the table: a question is askable only if a person with no
technical vocabulary can answer it from their own life. Everything else is the
builder's job — decided silently, recorded openly.

## The escape hatches (restated in one place)

- **Per question:** "you decide" — default applied, read back in plain words at
  the playback, recorded as an assumption.
- **Whole interview:** "just build it" at any point — every remaining question
  takes its default, and the playback is still shown (the playback is never
  skippable, because it is where silent wrong guesses get caught cheaply).
- **"I don't know":** treated exactly like "you decide," plus a flag so the
  playback draws their eye to that item specifically.
- **Walk away and come back:** an unfinished interview holds its state; nothing
  is lost by stopping mid-way.

---

# Part 2 — Why this shape (the research behind each choice)

**Stories before decisions (Phase 1 before Phase 2).** The most consistent
finding across user-research practice: opening with closed fact-questions
suppresses everything an interview is for. The Nielsen Norman Group's "6 Mistakes
When Crafting User Interview Questions" (read in full) puts "starting with closed
questions" as mistake #1 and "asking only about typical behaviors" as #2 — the
fix in both cases being "tell me about the last time you…", the concrete-episode
anchor this template opens with. The same source's mistake #3 — hypothetical
questions get confident but worthless answers — is why Phase 4 proposes concrete
scenarios instead of asking "what edge cases matter to you?". Business-analysis
practice agrees on sequence: open questions to expose vocabulary and unseen
steps, closed questions afterwards to lock down specifics (the funnel), per the
Business Analysis Body of Knowledge (BABOK — the professional standard for
business analysts; its interview technique chapter is paywalled, so this claim
rests on consistent secondary summaries, seen in search results).

**The switch-interview timeline shape.** The Jobs-to-be-Done school (the
"switch interview") reconstructs a real purchase/change as a timeline — first
thought, weighing options, decision, aftermath — precisely because memory of a
specific episode is reliable where opinion is not. Michele Hansen's published
switch-interview script (read in full) contributed Phase 1's questions 1–2
almost directly ("how did you get to needing something for this?", "what other
tools or things have you done manually?"). Her tone guidance — conversational,
imperfect grammar, validate liberally — is baked into the template's phrasings.

**"Three months from now" and the one-thing pair.** Consultant discovery
practice contributes the outcome-projection question (Louder Than Ten's
191-question scoping bank, read: "You're sitting across from me three years from
now… what has happened to make you so happy?") — compressed here to three
months, a horizon a consumer can actually picture — and the paired questions
"the one thing we need to get right / the one thing you're afraid we won't get
right" (their Q25/Q26, quoted nearly verbatim in Phase 1 question 5). That pair
consistently surfaces the top acceptance criterion and the top unstated risk in
a form novices answer easily.

**Context-free questions and the closing metaquestions.** Gause & Weinberg's
*Exploring Requirements* (the primary text; chapter 6 read in full from the
publisher's excerpt) is the classical source for questions that work before any
technical context exists: "What problems does this system solve?", "What
problems could this system create?", "What environment is this system likely to
encounter?" — echoed in Phases 1–2 — and, most importantly here, the
metaquestions the template closes with, nearly verbatim: "Is there anything else
I should be asking?" and "May I return with more questions later?" Their stated
reason to ask these explicitly: the issues "most likely to be resolved
implicitly, and thus ambiguously" are exactly the ones tradition or assumption
would otherwise settle silently.

**Why the interviewer proposes edge cases and the fence (Kano).** The Kano
model's central observation (multiple consistent secondary sources; seen in
search results, not read in the original) is that basic expectations are
*unspoken* — nobody states "it shouldn't crash on a typo" or "it shouldn't lose
my data," they assume it, and their absence dissatisfies while their presence
goes unnoticed. A novice interview that asks "what should happen on bad input?"
open-endedly is asking the person to state the unstatable. Propose-and-veto
inverts it: the machine states, the person judges — which is also the division
of labor this project's consent doctrine already uses (humans judge what humans
can judge; controls own the rest).

**Assets: universal agency practice.** Every real client questionnaire read for
this research asks for existing material before design starts. Paige Brunton's
web-design questionnaire (read): custom branding, brand colors/fonts/logos,
"which websites are you currently crushing on?" with specific reasons per site,
and a mood-board request. Marker.io's questionnaire guide (read): branding
guidelines, logos, fonts, palettes, plus the warning that undiscovered
functionality surfaces six weeks in ("oh, and we'll need a blog too"). HTML
Burger's template (read): a structured "which of the following assets can you
provide us with?" checklist — logos, images, brand guidelines, sitemaps, written
content — "clarifying responsibility for each deliverable," plus paired-opposite
image questions (colorful/greyscale, modern/classic) that directly inspired this
template's look-and-feel question. The disposition question (as-is / inspiration
/ extract) and the LOOKS-versus-WORKS probe on reference sites are this
document's synthesis, not a sourced pattern — marked as such — though the
"reference sites with reasons" practice they extend is universal in the read
sources.

**Defaults-with-veto.** The Nielsen Norman Group's "The Power of Defaults"
(read): users overwhelmingly keep defaults, so defaults must be the most
representative value, and a stated default doubles as just-in-time instruction —
it teaches the person what kind of answer the question wants. That is exactly
the role of the written-out "you decide" defaults in the Phase 2 table: even a
person who answers everything themselves reads the defaults and learns the
question's shape from them. The current system's practice of recording
escape-hatch defaults as visible assumptions is retained unchanged — it is the
honest half of the pattern.

**One decision per question; plain words.** The GOV.UK service manual's form
guidance (read) — one of the few novice-facing question systems tested at
national scale — contributes: one thing per page ("one decision they have to
make, one question they have to answer"), a question protocol justifying every
question's existence (mirrored in this template's rule that a question the story
already answered is never asked), branching so users only see relevant
questions, and eligibility-style ordering. The Nielsen Norman leading-questions
article (read) contributes the phrasing hygiene: never embed the desired answer,
never assume feelings ("when you were struggling…"), never name interface
jargon, invite elaboration in the person's own words.

**What is known about AI-conducted requirements interviews.** Two 2025–2026
studies, both read: LLMREI (arXiv 2507.02564) built a large-language-model
interviewer and evaluated it across 33 simulated stakeholder interviews against
a taxonomy of common human interviewer mistakes (question formulation, question
omission, interview order, communication skills, customer interaction). Findings
that shaped this template: the structured, guideline-carrying prompt variant
made fewer mistakes and produced better final summaries than the minimal prompt
(supporting the fixed phase structure and the mandatory playback); explicitly
instructing the model to ask ONE question at a time prevented overwhelming users
(supporting the one-decision-per-question rule, and a genuine tension with
today's all-questions-at-once screen — Part 3 addresses it); and the model's
strength was context-dependent follow-ups, its risk boundary-crossing
(supporting a closed question vocabulary with room for follow-up within it). The
companion finding (arXiv 2507.02858, abstract read): LLM-generated follow-up
questions matched human quality on clarity/relevancy/informativeness and
*exceeded* human questions when generation was guided by the common-mistakes
framework — direct support for baking a "never do" mistake list into the
interviewer's own prompt, which Part 3 recommends as a cheap immediate step.

**Single screen versus steps.** Vendor-published form research consistently
reports multi-step forms out-converting long single forms (claims in the range
of tens of percent to several-fold; read at involve.me and ivyforms via search
summaries — vendor-grade evidence, hedged accordingly), with the mechanism being
perceived effort per step. The GOV.UK one-thing-per-page guidance (read) is the
reputable version of the same instinct. Against this stands the abandonment
cost of *conversation length* in chat interfaces and LLMREI's observation that
methodical one-at-a-time questioning can feel like interrogation if unbounded.
The honest net: the field supports STAGED disclosure over both extremes — a few
small screens beat one big screen AND beat a twenty-turn conversation. Part 3's
maturation path follows that.

---

# Part 3 — Fitting the template to the system that exists

**What exists today, read from source.** The live quick path asks at most five
plain-language questions (one per decision area: where it runs, whether data is
saved, the one must-work feature, look, first-version size), rendered as ONE
screenful, answered in ONE free-text reply, with "just decide for me" filling
recorded per-area defaults; a sufficiency check skips anything the goal already
answered, and any interview failure falls back to building directly. The dormant
S2 interview (built, awaiting its go-live ceremony) widens this to eight decision
areas — adding content, awkward cases, and non-goals — still one screenful, one
reply, with the answers tagged by decision area on the run's permanent record.

The template above is deliberately a superset of that: its Phase 2 decision
areas ARE the eight S2 areas, re-worded; its escape hatches ARE the existing
ones. What the template adds is Phase 1 (the story), Phase 3 (assets), Phase 4's
propose-and-veto form, and Phase 5's explicit playback-and-correct turn.

## Fit A — everything on today's single screen (no structural change)

Compress the template into the existing shape: keep the eight areas, upgrade
their wording per Part 1, and add ONE new question area — **assets**: *"Do you
have anything I should work from — photos, a logo, documents with the real
content, a spreadsheet of records, links or screenshots of things you'd like
this to look or work like, or code from a previous attempt? Paste or name them,
or say 'nothing yet'."* The reply is free text like every other answer; named
files, pasted links, and descriptions all land in the build brief.

- **Gains:** the operator's asset requirement, immediately, at the cost of one
  question; zero new machinery (the cap is structurally the number of question
  areas, so it moves 8 → 9 with the new area).
- **Loses versus the full template:** the story phase (the model must infer the
  problem narrative from the goal text alone); propose-and-veto becomes
  propose-in-the-question ("…or say 'you decide' and I'll do the safe thing");
  the playback remains the existing plan card, which the person can already
  approve or revise but is not explicitly invited to correct.
- Also cheap and immediate, independent of any structure: bake the
  interviewer-mistake list (no compound questions, no jargon, no leading
  phrasing, no hypotheticals, concrete over general) into the question-writing
  prompt itself — the arXiv 2507.02858 finding says exactly this guidance is
  what lifts machine-written questions above human-written ones.

## Fit B — three small screens (staged rounds)

Round 1: the story (Phase 1's five questions, one screenful, one reply).
Round 2: shape + assets (Phases 2–4), generated FROM the story so that
everything the story answered is skipped — the existing sufficiency rule,
applied across rounds. Round 3: the playback (Phase 5), which is the existing
plan card plus the explicit "did I get anything wrong / what should I have
asked?" invitation, answered with the verbs that already exist (approve /
revise / reject).

- **Gains:** the story-first funnel the research is near-unanimous on; visibly
  fewer questions in round 2 (the story pre-answers several); staged disclosure
  matches both the government-scale guidance and the form-conversion evidence.
- **Loses versus today:** the one-shot simplicity that is the current design's
  stated virtue; the parked-interview state must survive two more round-trips
  (more state, more park/resume paths, more ways to abandon mid-way — and
  abandonment mid-interview is the chat-interface failure mode the AI-interview
  literature warns about).

## Fit C — fully conversational, one question at a time

The research-maximal shape (and what LLMREI implements). Best question quality
— every question can react to the previous answer — and the highest cost:
longest time-to-build, largest state machine, heaviest reliance on the local
model's conversational judgment, and the interrogation risk if the turn count
is not hard-capped.

## Recommended maturation path

1. **Now (fits inside the dormant S2 before its ceremony, or immediately after
   as a same-shape wording change):** Fit A — the assets question area, the
   Part 1 question wordings, and the mistake-list guidance in the
   question-writing prompt. No new structure; the ceremony story is unchanged
   ("a fuller set of questions, still one screen, still one reply").
2. **Next:** the playback turn — one added invitation line on the plan card
   ("Did I get anything wrong? Anything I should have asked?") wired to the
   existing revise path. This is the single highest-value/lowest-cost piece of
   the whole template: it converts silent wrong assumptions into cheap
   pre-build corrections.
3. **Later, evidence-gated:** staged rounds (Fit B), adopted only if the
   single-screen interview measurably under-elicits. The S2 design already tags
   every answer with its decision area on the permanent record — so
   "under-elicits" is measurable as the rate at which areas fall to defaults or
   builds get revised after delivery. (Using the tags this way is this
   document's suggestion, not a sourced practice.)

**One honest capability boundary, flagged for the operator rather than decided
here:** the interview can ASK for screenshots and images today, but the
build-side machinery reads text; an image's content reaches the build either
through the person's own words ("describe what's in that screenshot that I
should copy" — which the template's phrasing already does) or through a future
image-reading step, which would be a new capability and therefore a
Lead-Architect decision, not something this template smuggles in.

---

# Part 4 — Sources

## Read in full (fetched and used; contribution noted)

1. Gause & Weinberg, *Exploring Requirements* ch. 6 excerpt (publisher PDF,
   assets.ctfassets.net/.../Gause_-_Context-Free_Questions.pdf) — the verbatim
   context-free process/product questions and the closing metaquestions;
   "resolved implicitly, and thus ambiguously."
2. Nielsen Norman Group, "6 Mistakes When Crafting Interview Questions"
   (nngroup.com/articles/interview-questions-mistakes/) — closed openings,
   typical-behavior questions, hypotheticals, compound and ambiguous questions,
   with rewrites.
3. Nielsen Norman Group, "Avoid Leading Questions"
   (nngroup.com/articles/leading-questions/) — what makes phrasing leading;
   don't assume feelings; don't use jargon; invite elaboration.
4. Nielsen Norman Group, "The Power of Defaults"
   (nngroup.com/articles/the-power-of-defaults/) — users keep defaults;
   defaults as just-in-time instruction; choose representative values.
5. GOV.UK Service Manual, "Structuring forms"
   (gov.uk/service-manual/design/form-structure) — one thing per page, question
   protocol, branching, question ordering.
6. LLMREI, arXiv 2507.02564 (abstract + full HTML) — LLM interviewer vs the
   Bano et al. mistake taxonomy across 33 interviews; structured prompts beat
   minimal; one-question-at-a-time; strong summaries; boundary risks.
7. "Requirements Elicitation Follow-Up Question Generation," arXiv 2507.02858
   (abstract) — LLM follow-ups match human quality; exceed it when guided by
   the common-mistakes framework.
8. Michele Hansen, Deploy Empathy switch-interview script
   (deployempathy.substack.com/p/customer-interview-script-template-…) — the
   opening, the manual-workaround question, timeline sequencing, tone guidance.
9. Paige Brunton, "Web design client questionnaire"
   (paigebrunton.com/blog/web-design-client-questionnaire-questions) — brand
   assets, adjectives, "websites you're crushing on" with reasons, mood boards.
10. Marker.io, "Website Design Questionnaire" (marker.io/blog/website-design-questionnaire)
    — purpose/audience/branding-assets questions; late-surfacing functionality
    warning.
11. HTML Burger, "Website Design Questionnaire" (htmlburger.com/blog/website-design-questionnaire/)
    — the asset-checklist form ("which of the following can you provide"),
    paired-opposite style questions.
12. Louder Than Ten, "191 project scoping questions"
    (louderthanten.com/resources/communication/project-life-cycle-questions) —
    "three years from now…", the get-right/afraid pair (Q25/Q26), asset and
    audience-transition questions.

## Seen in search results only (not read in full; weighted accordingly)

- IIBA BABOK Guide §10.25 Interviews (iiba.org — paywalled; open/closed and
  structured-interview claims rest on consistent secondary summaries).
- thoughtbot Playbook, "Switch Interviews" (page shell fetched, content not
  reachable) and jobstobedone.org — the three-phase switch timeline.
- Webflow, Bonsai, Jotform, ClientManager, ReqBrief questionnaire articles —
  corroborate the agency asset/reference-site practice.
- involve.me / ivyforms / orbitforms multi-step-form statistics — vendor-grade
  conversion claims (hedged in Part 2 accordingly).
- Kano-model summaries (t2informatik, iSixSigma, productschool, Wikipedia) —
  unstated basic needs.
- "A Comparative Study of Traditional and Chatbot-Based Interviews in User
  Requirements Elicitation" (lorojournals.com — HTTP 403; engagement claim from
  its abstract as surfaced in search only).
- ReqElicitGym (arXiv, search result) — systematic evaluation of LLM interview
  competence exists as a research direction.

## Claims that are this document's synthesis (no direct source)

- The LOOKS-versus-WORKS probe on reference examples (extends the sourced
  "sites you like and why" practice).
- The per-asset disposition question (as-is / inspiration / extract).
- Assets as a ninth question area inside today's single-screen shape.
- Using the S2 record's decision-area tags as the under-elicitation metric that
  gates the move to staged rounds.
- The infer/ask/propose three-column boundary as stated (assembled from the
  sourced pieces; the specific three-way split is mine).
