---
title: "Advanced Intake — novice interview maturation (the approved template, fitted)"
status: DESIGN — review fix round applied 2026-07-29 (independent review F1–F12 dispositioned in-doc; §6 SETTLED per #1165 c.2649); pending reviewer re-verification. The plain-language read is §0; LA confirmed the template + its maturation path 2026-07-29 ("i read the interview template and approve. proceed.")
area: design
date: 2026-07-29
ticket: "#1165 (umbrella: A operator assets, B reference emulation, C interview maturation); template SSOT docs/research/novice-interview-template-research-2026-07-29.md"
grounded_at: "main 88ce3953; every anchor below read on disk at that commit today. NOTE: fix/1161-1160-plan-time-brittleness is in flight against the same coordinator corridor and merges FIRST — build slices cut from main AFTER it lands and re-verify §9's anchors then."
grounding_reads: "the approved template (all four parts); #1165 description + c.2643 (the LA's verbatim requirements); shared/fleet/clarify.py WHOLE (591 lines, post-S2); services/ui_gateway/src/dispatch_coordinator.py 850-1236 + 1560-1568 + 1704 + 1912-1914; docs/design/advanced_intake_S2_elicitation_interview_DESIGN.md; docs/design/advanced_intake_S3_criteria_and_exam_authoring_DESIGN.md; docs/runbooks/advanced_intake_interview_go_live.md (EXECUTED banner — the flag is LIVE and the §6 memory question is SETTLED: defer); services/assistant_orchestrator/config/default.toml 460-745 (six advanced_intake* keys, ALL true as of the two 2026-07-29 ceremonies); shared/fleet/acceptance.py 2300-2327 (VLM loop fields + UC-010 asset_specs seam), 2885-2902 (visual_criteria_texts), 65-71 (tiers); shared/fleet/critique.py 1-80 (loop-signal rule, fail-soft contract, LENSES); fix round additionally verified: #1165 c.2649 (the settled B-1/B-2 record), dispatch_coordinator.py 174-233 (PendingDispatch + PendingClarification — no intake carrier today), parse_dispatch_command :409 (pipe-less reply ⇒ kind=run, empty repo), acceptance.py 3956-3970 (generate_plan receives repo + projects_dir — the AO-side enumeration plumbing)"
---

# Novice interview maturation — fitting the approved template to the shipped interview

## 0. Plain-language read (for the Lead Architect)

You read the interview template and approved it, including its recommended
order of adoption. This is the build design for that adoption, plus the two
capabilities you named at the ceremony close: your own photos and files landing
in builds, and "make it like THIS screenshot." Nothing here is built yet;
everything below merges switched off and goes live only at a ceremony you run.

**What changes for you, phase by phase, once it is live:**

- **Setting the table.** The fuller interview now opens with the promise the
  template makes: no wrong answers, no technical answers, "you decide" always
  available, and nothing final until you have corrected the read-back.
- **The questions get better, not more numerous.** Same one screenful, same
  one reply in your own words. The wording follows the template — questions
  about your life, never about software; the look-and-feel question offers
  paired choices (calm or colorful, dense or spacious) instead of asking you
  to describe a style from nothing; and the question-writing rules the
  research found (one decision per question, nothing hypothetical, no jargon)
  are baked into the machinery that writes them. "I don't know" becomes a
  first-class answer, treated exactly like "you decide": the safe choice is
  made for you and shown on the card. Today only the "you decide" phrasings
  are recognized; a plain "I don't know" is misread as a real answer.
- **It asks what you already have.** A new question — photos, a logo,
  documents with the real content, spreadsheets of records, code from a
  previous attempt, and screenshots or links of things to emulate — with
  "nothing yet" always a normal answer. There is now a real place to PUT those
  things: an `assets` folder inside each project's folder. Drop files in;
  the plan card tells you exactly what it found ("working from your 12 photos
  and prices.xlsx"), and the build is graded on actually using them.
- **The awkward cases flip around.** Instead of asking you to invent edge
  cases, it proposes them concretely — "if someone types a price with a comma,
  it politely asks again rather than guessing. OK?" — and you just veto. Same
  for what gets left out, plus at most two clearly-labelled suggestions of
  things people asking for this usually also want.
- **The read-back becomes a contract.** The plan card ends by asking "Did I
  get anything wrong? Anything I should have asked?" — and you can answer it
  in plain words right there; your correction revises the plan before
  anything is built.
- **"Make it like this screenshot."** You put a screenshot in the project's
  `assets/reference` folder and say whether you mean the way it LOOKS or the
  way it WORKS. A small picture-reading model (a vision-language model, VLM —
  it already critiques builds visually) turns the reference into written
  design notes and checkable look-and-feel criteria, and then judges the
  build against them during construction. The two questions about this were
  yours, and you settled both the same day (§6): "emulate" means
  inspiration — only written descriptions ever cross from the reference into
  the build — and anything you can screenshot may inspire, with everything
  staying on this machine.

**What does not change:** a normal `/dispatch` stays byte-for-byte today's
behaviour; the fuller interview stays something you explicitly ask for; every
escape hatch ("you decide," "just build it," walking away mid-interview)
stays; and the interview still defers to what a project already remembers,
exactly as you settled at the go-live ceremony. The template's staged-rounds
idea (story first, then the shape) is deliberately NOT built now — per the
path you approved, it waits for evidence that the one-screen interview
under-asks, and this program builds the measuring stick for that.

---

## 1. Template → system mapping

The LA's verbatim requirements (c.2643 on #1165): novice-first, anticipatory,
structured and reusable, with asset-gathering first-class in the interview
itself. The approved template satisfies all four; this section maps its six
phases onto the shipped machinery — what EXISTS, what EXTENDS, what is NEW,
and where each lands.

The substrate (all live on main today): the 8-axis interview —
`INTAKE_AXES` (clarify.py:78), `INTAKE_MAX_QUESTIONS = 8` (:87),
`_INTAKE_TEMPLATE` (:154-173), per-axis defaults (:95-115) — riding the
one-reply corridor (`answered_from_free_text` :415-438: ONE free-text reply
answers everything), the "just decide" hatch (:339-361), the sufficiency rule
(the model returns `[]` for an already-clear goal, :299-307), the absolute
fail-soft (:308-311), the `advanced` token + hint line + defer-to-memory
notice (dispatch_coordinator.py:898-1008), the parked-interview hold state
(`PendingRequirements.intake`, :237), and axis tags on the acceptance record
(`record_axes`, clarify.py:392-438).

| Template phase | Exists today | Extends | NEW | Lands in |
|---|---|---|---|---|
| 0 Setting the table | nothing — the render opens straight into questions (:1114) | — | the four-sentence preamble, deterministic text on the intake render; the "I don't know" hatch (template rule 6) — a LIVE gap: `_DECIDE_PHRASES` (clarify.py:339-355) has no I-don't-know variant, so a whole-reply "I don't know" records today as a substantive answer (`assumed=False`) | M1; preamble is render-only; the hatch routes to the existing decide-defaults path, flag-gated |
| 1 The story | the GOAL free-text is where the story lives; the sufficiency rule already skips what it answered | — | NOT BUILT NOW — staged rounds are the approved path's evidence-gated LATER step (§2 M-horizon) | the under-elicitation metric (M2/M4 tags) is built now; the rounds are not |
| 2 The shape | all 8 decision areas ARE the 8 axes (the template's own Part 3 says so) | per-axis wording per the template's Part 1 table (paired-opposites visual question; life-not-software phrasing); the question-writing mistake list into the prompt | — | M1 (`_INTAKE_TEMPLATE` successor); answers land exactly as today: requirements block → criteria/assumptions/tasks |
| 3 Asset inventory | the `content` axis asks what it should HOLD; files in a project folder already ride into the fleet worktree (proven, #1165 A) | the content question stays; assets get their OWN axis (the template's ninth area); a promised-later asset collapses into the recorded answer + the next plan's fresh manifest (no promise ledger — argued in M2); item 7, "things it must live with", lands as M3 fence proposals, not a question area (argued in M3) | `assets` axis + question + default; the folder contract, manifest, card acknowledgment, use-verification (capability A) | M2 (ask + record), M5 (folder/manifest/card/exam), M3 (coexistence proposals) |
| 4 Propose-and-veto | `edge` + `nongoal` axes exist as OPEN questions | both flip to propose-form (concrete proposals, yes/no veto) | the anticipation offer (≤2, labelled suggestions) as an `extras` axis | M3; proposals ride the same {axis, question} emission — the question text carries the proposal |
| 5 The playback | the plan card already reads back criteria, assumptions (tagged), clarifications, non-goals; approve/revise/reject exist | the card's intake render closes with the template's two questions | free text at the approval turn becomes a REVISE in intake mode (today the pipe-less shape returns the #1116 usage line, KEEPING the text — see M4 for the verified baseline) | M4; rides the existing bounded revise path |
| Reference emulation | visual-tier criteria are first-class (`TIER_VISUAL`, acceptance.py:65); `visual_criteria_json` rides every task dict (:2317); the multi-lens VLM critique exists (critique.py, loop-signal-only) | the assets question names screenshots-to-emulate + the LOOKS-vs-WORKS probe inline | reference → written design notes → authored visual criteria + a reference-fidelity lens (capability B) | M2 (ask), M5 (folder), M6 (extraction + lens) |

Two structural constraints bind everything in the table:

1. **The c.2512 constraint, now at full strength.** EVERY flag in the
   advanced-intake family is LIVE as of the two 2026-07-29 ceremonies —
   `advanced_intake` (default.toml:484), `bad_input_floor` (:523),
   `coherence_gate` (:610), `coverage_gate` (:656), `criteria_revise` (:697),
   and `advanced_intake_interview` (:740). A slice gating on ANY existing key
   would go live at merge. Every slice below therefore carries its OWN
   sub-flag defaulting false, in the house register, engaging only in
   conjunction with the live front (§7 table).
2. **The one-reply corridor is a keep, not a casualty.** The approved path's
   NOW step (the template's Fit A) deliberately compresses phases 0–4 into
   the existing one-screen, one-reply shape. Follow-up questions (the
   per-asset disposition walk, the story funnel) compress into richer
   question TEXT, not extra turns. Where the template loses something by that
   compression, the mapping row says so rather than pretending.

## 2. The fit path as slices (the interview-side program)

The approved sequencing (template Part 3): **Now** = Fit A (assets area,
Part 1 wordings, mistake-list guidance) → **Next** = the playback turn →
**Later, evidence-gated** = staged rounds. Slices M1–M4 implement Now + Next.
Slice constraints common to all: own sub-flag defaulting false in dataclass
AND `is True` parse AND resolved property AND every new function keyword (the
S2 §3.1 chain, entrypoint.py precedent); flag-off byte-identical BY
CONSTRUCTION (defaults select the existing code path, not a restoring
branch); config-parse lock (`"true"`/`1`/garbage resolve False, #1042); every
control tested off.

### M1 — the interview voice (`advanced_intake_interview_voice`)

**Scope.** (a) The intake prompt's successor: the eight axis areas re-worded
per the template's Part 1 table — life-not-software phrasing, the visual axis
as paired opposites ("calm and professional or colorful and friendly? plain
and dense or spacious and simple?") — plus the interviewer-mistake list as
prompt guidance (one decision per question; never compound, leading,
hypothetical, or jargon-bearing; concrete beats abstract; the arXiv
2507.02858 finding that exactly this guidance lifts machine-written questions
above human-written ones). (b) The Phase-0 preamble: four deterministic
sentences prepended to the intake question render — promise of no wrong
answers, the "you decide" hatch, the read-back. (c) The "I don't know" hatch
(template rule 6): `is_decide_for_me` gains a `dont_know: bool = False`
keyword admitting a small explicit I-don't-know phrase set ("i don't know" /
"no idea" / "not sure" — the same small-explicit-never-fuzzy discipline as
`_DECIDE_PHRASES`, clarify.py:339-355); the coordinator's answer path passes
the M1 flag, so a WHOLE-reply "I don't know" routes to the existing
decide-defaults turn (`assumed=True` — the card's "here's what I chose"
already draws the eye, which is the template's flag-for-attention compressed
into the existing render). A PARTIAL "I don't know about the colors" stays a
substantive answer — the one-reply corridor cannot split it per-axis without
manufacturing a split from guesswork (named compression). Default False
keeps the live recognizer byte-identical on both paths. (d) To make (a)
composable with M2/M3's area additions, `_INTAKE_TEMPLATE` becomes the
all-off output of a pure template builder (`intake_template_for(axes, *,
voice=False, proposals=False)`): with every parameter at default it returns
TODAY'S CONSTANT BYTE FOR BYTE (locked); each flag swaps or adds only its
own lines. Byte-identity needs a canonical ORDER, not just a set (F11a): a
new `INTAKE_AXES_ORDER: tuple` pins the live template's area sequence
(surface, persistence, feature, visual, scope, content, edge, nongoal;
M2/M3 append assets, extras), the frozensets derive from it, and the builder
iterates the tuple — never the frozenset — so output bytes are deterministic.

**One inherited hazard, named:** the template's Part 2 table writes out the
"you decide" defaults per area, and #1161's in-flight fix exists because one
of those defaults (`surface` → "a simple app that runs on this computer")
steered an empty project onto the fleet's weakest stack. M1's wording
NEVER restates a default inline — every default rendering reads
`DEFAULT_AXIS_ANSWERS` (clarify.py:95), so whatever #1161 lands as the
surface default is automatically what the interview speaks. A lock pins the
template builder against inline default text.

**Tests.** Template-builder identity lock (all-off bytes == the live
constant, driven through the ORDER tuple); voice-on prompt carries the
mistake list + paired-opposite visual wording; preamble renders only when
intake AND flag; I-don't-know phrases route to decide-defaults ONLY with
`dont_know=True` and only on a whole-reply match (partial replies stay
substantive; every live `_DECIDE_PHRASES` case byte-identical flag-off);
toggle-off render byte-identical; no `DEFAULT_AXIS_ANSWERS` value string
duplicated into any template output (the #1161 guard).

### M2 — the assets axis (`advanced_intake_interview_assets_axis`)

**Scope.** `AXIS_ASSETS = "assets"` — the ninth area, the template's Phase 3
compressed to one question in the interview's register: *"Do you have
anything I should work from — photos, a logo, documents with the real
content, a spreadsheet of records, code from a previous attempt, or links and
screenshots of things you'd like this to look or work like? Name or describe
them — and for each, say whether to use it as-is, as inspiration, or to pull
the information out of it; for anything to emulate, say whether you mean the
way it LOOKS or the way it WORKS. Or just say 'nothing yet'."* The per-asset
disposition walk and the looks-vs-works probe ride INSIDE the question text
(the one-reply compression, §1). Default (the "you decide"/"nothing yet"
answer, honest with or without the M5 pipeline): *"starting without any of
your own material — clearly-labelled examples stand in until you add real
content."* When M5 is live, one deterministic hint line joins the question:
*"(files go in the project's `assets` folder — I'll list what I find on the
plan card)"*.

**The promised-later asset (template Phase 3 standing rule), argued rather
than dropped:** the template records a promise-with-placeholder per asset.
This design deliberately builds NO promise ledger — the promise IS the
operator's recorded answer ("I'll add the photos this weekend" rides the
requirements block and the record verbatim), the labelled-placeholder
posture (the `content` default) covers the gap exactly as it covers
"nothing yet", and the next dispatch's fresh manifest picks the files up
the moment they exist (M5 re-enumerates at every plan; §5). A ledger would
add a store, a staleness problem, and a nag surface to deliver what the
answer text + re-enumeration already deliver.

**Vocabulary mechanics.** `INTAKE_AXES_ORDER` (M1's canonical tuple) gains
`assets` at its tail; the widened frozenset derives from the tuple
(`INTAKE_AXES_FULL` — grown again by M3; one program-wide constant, not
per-flag sets) with the cap staying structural
(`== len(...)`, the axis-dedupe ruler makes over-emission top out).
`INTAKE_AXES` itself is UNTOUCHED — it is what the live flag speaks.
Engagement passes the wider set only when the sub-flag is on. **The
reconstruction seam** (`questions_from_dicts` axis selection at
dispatch_coordinator.py:1030-1058): intake parks reconstruct with
`INTAKE_AXES_FULL` UNCONDITIONALLY once M2 lands — provably
behaviour-invariant for every existing park (a stored 8-axis set contains no
member outside the eight, so the wider allowlist coerces nothing
differently), and it makes a parked ninth-axis question restore correctly
even across a mid-park flag flip. No new hold-state field; `intake: bool`
stays sufficient. Record tags ride the existing `record_axes` machinery
unchanged — `"assets"` simply appears among the tag names.

**Tests.** Axis-default lock (assets self-answers to its recorded
assumption); cap lock (9-axis over-emission rules to ≤9, one per axis);
reconstruction-invariance lock (an 8-axis park reconstructs byte-identically
under the full vocabulary); park round-trip with a ninth-axis question;
record carries the `assets` tag; toggle-off — fresh interviews emit 8-axis
questions byte-identical to today.

### M3 — propose-and-veto (`advanced_intake_interview_proposals`)

**Scope.** The template's Phase 4. (a) The `edge` and `nongoal` template
areas flip from open-question form to propose-form: the model authors
CONCRETE proposals grounded in the goal — 2-4 awkward-case behaviours
("if someone types a price with a comma instead of a dot, it politely asks
again rather than guessing — OK?") and a named leave-out fence ("I'm planning
to LEAVE OUT accounts, payments, and a phone app — need any of those?") —
each a veto, never an invitation to invent. The fence guidance explicitly
includes COEXISTENCE assumptions — the template's Phase 3 item 7 ("does it
need to work alongside anything you already use — an email account, a
calendar, a program you're not willing to give up?") lands here in
propose-form ("I'm assuming it doesn't need to talk to your email or
calendar — right?") rather than as its own question area: novices cannot
enumerate integrations any more than edge cases (the same Kano unstated-need
class), propose-and-veto is exactly the shape for it, and it keeps M2 honest
as the Now step's ONE new area. Proposals ride the existing
`{axis, question}` emission; the question TEXT carries the proposal, so no
schema, parser, or corridor change. The one-reply corridor already lets the
operator veto selectively in their own words. (b) `AXIS_EXTRAS = "extras"` —
the anticipation offer: ONE question naming at most two adjacent wants
("people who ask for this often also want a printable version or a way to
share it — want either, or skip them?"), clearly labelled a suggestion,
default *"skipped — nothing beyond what you described."* The template's
at-most-two-offers rule is enforced in the prompt and is honest about its
one-screen compression: two candidates share one question slot, and the
operator's reply may split them ("printable yes, sharing no") — the corridor
already supports that. `INTAKE_AXES_ORDER` gains `extras` at its tail;
`INTAKE_AXES_FULL` reaches its final ten members here; the cap follows
structurally.

**Two path deviations, argued (review F9):** (a) `extras` is a SECOND new
question area where the approved Now step named ONE — deliberate and
consistent: the "ONE new area" scoping described Fit A (M2's slice); the
extras axis implements Phase 4.3 of the SAME approved template and lands in
the propose-and-veto slice it belongs to, sequenced after the Now slices. A
capped tenth axis is the minimal carrier that survives the one-per-axis
dedupe ruler — the alternative (riding `nongoal`'s slot) would displace the
fence question it must accompany. (b) "2-4 awkward-case behaviours" versus
the template's "three to five": the template's band assumes standalone
yes/no turns; here the proposals ride as sub-items of ONE question slot in a
screenful that may carry up to ten areas, so the band shifts down one to
keep that single question answerable in one breath. A one-screen adaptation,
not a disagreement.

**"Just decide" on a proposal means the SAFE side, recorded:** the
edge/nongoal/extras defaults (existing rows :105-115 + the new extras row)
ARE the safe sides — clear-message-never-crash, nothing-beyond-described,
no-extras. Propose-form changes what the model ASKS, never what a default
DOES.

**Tests.** Prompt lock (proposal form + fence + ≤2 offers guidance present
flag-on, absent flag-off); extras default lock; a veto-shaped one-reply flows
the corridor unchanged; toggle-off byte-identity.

### M4 — the playback turn (`advanced_intake_interview_playback`)

**Scope.** The template's Phase 5, the path's highest-value/lowest-cost
piece. (a) The intake-mode plan card closes with the two template questions:
*"Did I get anything wrong? Is there anything I should have asked you about
that I didn't? Tell me in plain words and I'll fix the plan — or /dispatch
approve when it reads right."* (b) The wiring that makes the invitation
TRUE — with the TODAY baseline stated from source, not assumption (review
F1): a pipe-less free-text reply while a card awaits approval parses as
`kind="run"` with an EMPTY repo and the whole text as goal
(`parse_dispatch_command`, :409 region), so `_plan`'s not-repo branch
answers it with the #1116 usage line while KEEPING the operator's text
(`_keep_operator_text`, :905-914). The "a dispatch is already waiting for
your approval" nag (:931-937) fires only on the PIPED `<repo> | <goal>`
shape — an attempt to start a NEW dispatch — and M4 does NOT re-route that
shape: the nag stays its right answer. M4's re-route is exactly the
pipe-less shape: in intake mode with the flag on, that free text routes to
the EXISTING revise path as feedback. Reserved verbs keep absolute
precedence — approve / reject / revise / status parse first, exactly as
today. Quick path and flag-off keep the usage/keep-text reply BYTE-IDENTICAL
(that reply, not a nag, is the toggle bar). The revise budget (3, #820) is
unchanged and shared — a playback correction IS a revision, and the card
says so when the budget is exhausted. (c) The intake CARRIER at the approval
turn (review F2) — none exists today and the shortcut is wrong:
`PendingRequirements.intake` dies with the question turn, and deriving the
bit from the spec's clarification tags would misfire because banked tagged
answers replay onto QUICK dispatches of remembered projects (the S2 F6 pin,
§5) — a tag-derived playback would light up exactly where it must not. So
`PendingDispatch` gains an additive `intake: bool = False` (:174-198 today
carries none), and `PendingClarification` gains the same (:201-233 — the
Inc-4 platform-question hold interposes between plan and card, :1164-1179,
and must not launder the bit away; `_choose` re-stamps it onto the
`PendingDispatch` it finalizes). Threading: `_finalize_plan` receives the
bit from its two callers — `advanced_active` on `_plan`'s no-question path,
`pending_req.intake` on the replan path — and stamps whichever hold it
parks. The store codecs emit the key ONLY when True (a quick-path park's
payload stays byte-identical; a pre-M4 row restores False). This is a
store-payload change and the slice budget names it.

**The #1160 dependency, explicit and hard.** The in-flight
fix/1161-1160-plan-time-brittleness branch is re-shaping reserved-verb
honesty in exactly this corridor (the LA's `/dispatch revise …` consumed as
a free-text ANSWER at the question turn — the collision class M4 now
extends to the approval turn). That branch merges FIRST; M4 is designed
against its LANDED shape, inherits whatever honesty notice it establishes
for verb-shaped text, and its parse locks extend the #1160 suite rather
than duplicating it. M4's builder re-verifies this section's line anchors
against post-merge main before cutting.

**Tests.** Invitation renders only intake+flag; pipe-less
free-text-at-approval routes to revise intake-only, and the toggle lock
pins the flag-off/quick-path baseline as the #1116 USAGE/KEEP-TEXT reply
verbatim (the F1 correction — never "the nag"); the piped shape still nags
on EVERY path; reserved verbs win on every path (extending the #1160
locks); carrier round-trips — `intake=True` survives payload → restore on
BOTH holds, a pre-M4 row restores False, a quick-path park emits no key
(store bytes identical); an Inc-4-interposed intake dispatch keeps its
invitation after `_choose`; revise-budget exhaustion message honest; a
playback revise re-renders the card still carrying the invitation.

### The M-horizon — staged rounds (Fit B), deliberately not a slice

The approved path adopts staged rounds ONLY on evidence of
under-elicitation. This program builds the measuring stick and the trigger,
not the rounds: the record's axis tags (live) + M2/M3's wider tag vocabulary
make "areas falling to defaults" and "post-delivery revisions" countable per
run. A follow-on ticket carries the predicate — `blocked-by:` a measured
default-rate/revision-rate report over ≥10 real intake runs read from the
acceptance records — so the next actor OBSERVES the gate rather than
re-arguing it. No sub-flag is reserved now; the rounds get their own design
when the evidence calls for them.

## 3. The asset inventory phase — capability A's boundary

The split the umbrella ticket draws: the INTERVIEW asks and records (this
program, M2); the PIPELINE makes assets real in builds (the A-slices, M5).
The seam between them is designed here; M5 carries the build detail.

**The folder contract (M5).** `<project>/assets/` under the fleet projects
root (`_repo_path`, dispatch_coordinator.py:1912-1914 — `projects_dir /
<slug>`; `fleet.create_project` scaffolds the project folder, :1197-1236).
The operator drops files in with File Explorer; nothing is imported,
uploaded, or registered — the folder IS the interface, and the corridor
already carries it (project-folder files ride into the fleet worktree —
proven, #1165 A). `create_project` seeds an empty `assets/` with a
plain-language README one line long ("put photos, documents, and other
material for the build in here; screenshots to emulate go in `reference`").
Reference material gets the `assets/reference/` subfolder (M6's input).

**The manifest — ONE enumeration, AO-side, and it is the only trust source
(review F11b).** `generate_plan` already receives `repo` and `projects_dir`
(acceptance.py:3956-3961), so the manifest is enumerated ONCE, inside
`generate_plan` beside the authoring it feeds — a pure helper over the
resolved assets directory, injected/fake-able so the stage stays
GPU-free-testable, engaged only when the M5 flag is on. No goal-string
crossing exists: an earlier draft's `[[BLARAI_OPERATOR_ASSETS]]` sentinel is
DELETED from this design — nothing manifest-shaped ever rides the goal, so
the operator-words corpus (`operator_answers_from_block`, clarify.py:521-547
— the #1043 seam) is never near machine prose by construction; a hygiene
lock still asserts the manifest renders into no clarification or
requirements channel. Enumeration mechanics, deny-by-default at every step:

- rooted walk with ALL reparse points excluded fail-closed — junctions and
  mount points, not just symlinks: junctions are creatable WITHOUT elevation,
  so they are the live traversal class on Windows (review F6) — plus a
  containment check after resolution (every resolved path must remain under
  the assets root, else the entry is skipped with a named notice);
- filename hygiene (review F5): names must clear a conservative ALLOWLISTED
  character class (letters, digits, space, dash, underscore, dot; no
  leading/trailing dot or space; length-capped). Bidirectional-override,
  zero-width, and control characters cannot appear in a conforming name, so
  card-line spoofing dies at the walk; non-conforming files are SKIPPED
  fail-closed with a named card notice ("2 files skipped — rename them to
  plain names");
- extensions classified against a closed allowlist (images / documents /
  data / code / other), per-file and total size caps, RELATIVE paths only;
- names are DATA everywhere they render — always quoted inside the
  manifest's structured list, so an instruction-shaped name ("ignore the
  criteria.xlsx") stays a quoted filename in card and prompt alike, never
  prose. The hygiene lock probes exactly these shapes: bidi override,
  zero-width, control characters, instruction-shaped names, over-length —
  plus the walk's own exclusions: a planted junction/reparse point and a
  containment-escaping resolution, each locked as skipped-fail-closed.

The manifest — never anything parsed out of an answer — is what the system
acts on. File paths the operator TYPES in an interview answer are recorded
words, never dereferenced (§8).

**Where the manifest lands** (in dependency order — the spec is the single
carrier; everything else reads it, so no two surfaces can disagree):

1. **The spec:** `AcceptanceSpec` gains an additive `operator_assets` field
   — absent ⇒ `to_dict` byte-identical, carried through the round-trip
   whitelist discipline (the `_coerce_*` class, acceptance.py:1152-1178; the
   spec-side additive-field precedent is the `asset_specs` FIELD itself,
   not the :2322 stamp — review F11d). Authored AO-side in `generate_plan`,
   it rides `PlanResult.spec` back to the coordinator.
2. **The criteria and exam:** a deterministic asset-use floor, same shape as
   the S1/S3 floors — injected in the same `generate_plan` pass when the
   manifest is non-empty, never hoped for from the model. Machine-checkable
   half: for web-surface builds, at least one provided asset file is
   referenced by the built pages (filename-presence check over the build
   output). Honest limit, named now: presence-in-markup asserts wiring, not
   rendering — the rendered half is an injected VISUAL-tier criterion
   ("the operator's provided photos appear on the page"), judged by the
   existing eyeball tier and seen by the VLM critique loop. Non-web
   surfaces get the visual/human criterion only.
3. **The task dicts:** `operator_assets_json` stamped at compile ONLY when
   non-empty — the UC-010 SEAM A conditional-stamp pattern
   (`_thread_build_fields`, acceptance.py:2319-2323) — so the coder prompt
   knows the real filenames.
4. **The plan card:** one acknowledgment line — *"Working from your assets
   folder: 12 photos, logo.svg, prices.xlsx"* (name-capped listing; count
   summary beyond the cap) — rendered FROM `spec.operator_assets` at
   `_finalize_plan` (:1132-1140), the single convergence the no-question
   and replan paths already share (ONE seam, review F11b). Empty or absent
   manifest ⇒ nothing prints — byte-identical card.

**The operator's control surface is the folder — and the two injected
checks sit on opposite sides of the machine wall, deliberately (review
F8).** The MACHINE-tier markup floor is a true floor: the wall keeps
machine tiers keep-only (default.toml:697; dispatch_coordinator.py:1704)
and re-injection restores it after any revision — two independent locks.
The VISUAL-tier criterion is OPERATOR-tier and therefore DROPPABLE by a
criteria revision — deliberately: "your photos appear on the page" is
taste-adjacent judgment, and judged checklist items stay the operator's to
edit (the S3-G posture). Dropping it never weakens the machine gate — the
markup floor still asserts wiring. Both derive from the CURRENT manifest at
each plan: remove the files and neither injects.

**Interview-facing seam, restated:** M2 asks and records dispositions in the
operator's words; M5 acknowledges what physically exists and grades its use.
The two never disagree because they never share a source — words on the
record, files in the manifest, and the card shows both.

## 4. Reference emulation — capability B's seam and slice family

**The interview-facing seam (rides M2 + M5, no new machinery):** the assets
question names "links and screenshots of things you'd like this to look or
work like" and asks the LOOKS-vs-WORKS + disposition probe inline; the
screenshot itself goes in `assets/reference/`. The record carries the
operator's own words about what to emulate and in which sense. That is the
WHOLE interview-side surface — everything else in this section is the
extraction family (M6), sequenced last per the approved path, because the
research names image-reading as the one capability boundary the template
could not smuggle in.

**M6 — reference extraction (`advanced_intake_reference_extraction`).**
Shape, built on the existing critique substrate (shared/fleet/critique.py —
the multi-lens VLM pass whose loop-signal rule is NON-NEGOTIABLE):

1. **Sanitize before trust (§8):** each file in `assets/reference/` passes,
   in order: the closed format allowlist (png/jpg), the byte-size cap, a
   PIXEL-DIMENSION cap read from the image HEADER before any full decode
   (byte caps alone do not stop decompression bombs — a tiny file can
   declare enormous dimensions; review F7), and only then the
   decode-and-re-encode step to a clean bitmap. A file that fails any step
   is SKIPPED fail-closed with a named card notice, never half-used.
2. **Extraction:** the VLM describes the sanitized reference into structured
   DESIGN NOTES — palette, layout grid, density, component inventory, tone —
   as text. The output is descriptive prose/tokens; it is structurally
   incapable of carrying the original bitmap into the build (load-bearing
   for §6's emulation-grade decision).
3. **Authoring:** the notes author reference-derived VISUAL-tier criteria
   ("uses a calm two-column layout like the reference; dark header, spacious
   density"), tagged with their provenance, joining the spec like any visual
   criterion — operator-tier, revisable, NEVER machine-floor. The notes also
   ride the coder's task context so the build aims at them from the first
   iteration, and the LOOKS-vs-WORKS answer scopes what gets authored (WORKS
   extracts flow/structure notes, not palette).
4. **The judging half:** a reference-fidelity lens joins the critique pass —
   and because `LENSES` (critique.py:73) is a STATIC dict while this lens
   needs the per-run design notes, it is built by a parameterized
   lens-builder at call time, not added to the dict (review F11c). The
   carrier: the module's command-line contract (`python -m
   shared.fleet.critique`, invoked by the fleet's `critique-loop.ps1` in
   agentic-setup) gains an OPTIONAL reference-notes input, and the loop
   passes it only when the task dict carries a new conditional
   reference-notes field (the `visual_criteria_json` pattern). Absent input
   ⇒ the critique pass is byte-identical to today (the toggle bar). The
   builder budgets the CROSS-REPO touch: the ps1 edit lands in
   agentic-setup, coordinated at merge time. The loop-signal rule is
   inherited untouched: the VLM drives fix iterations, never verdicts;
   visual criteria remain `STATUS_EYEBALL` at approval
   (acceptance.py:2898-2901). Extraction failure fails soft to
   no-reference-criteria with a card notice, exactly the `VlmCritique`
   contract (critique.py:14-19).

**Banner rot retired in M6's motion (review F10):** critique.py:2-5 still
says "DORMANT — not wired into any live caller" and acceptance.py:2307-2313
still says "No live caller reads them yet" — both ROTTED: the critique loop
is LIVE fleet-side (`critique-loop.ps1`; `new-agent-task.ps1` step [6/6]).
M6 touches both files and retires the banners per the coding standard
(docstrings state contracts, never wiring state — point at the authority),
so the next reader is not told a live surface is dormant.

**Engagement:** `advanced_intake` AND `advanced_intake_assets_pipeline` AND
`advanced_intake_reference_extraction` — the extraction cannot exist without
the folder contract that feeds it. Everything is local files and the
resident local VLM; no network anything, structurally.

**Both reserved decisions are SETTLED** (LA in-chat 2026-07-29, banked
#1165 c.2649; recorded in §6): emulation is INSPIRATION-GRADE, and
anything-screenshotable-may-inspire with everything local. The shape above
IS the ratified shape — the notes-only channel (step 2) is B-1's structural
enforcement, not a default awaiting confirmation — and M6 is fully
unblocked behind M5.

## 5. Interactions with the live system

- **Project memory (SETTLED posture — composes, never reopens):** `advanced`
  DEFERS to remembered answers with `/dispatch forget` as the fresh-interview
  escape (runbook EXECUTED banner; DECISION_REGISTER row). Every M-slice
  inherits that: on a remembered project the fuller interview self-suppresses
  and the notice line renders, unchanged. New composition rules: banked
  answers replay with their tags (the S2 F6 behaviour, pinned) — a banked
  `assets` ANSWER replays like any answer; the asset MANIFEST is never
  banked — re-enumerated fresh at every plan, because files change between
  dispatches and a stale manifest would be a false card claim.
- **The machine wall (S3-G, live):** M5's injected floors are machine-tier —
  the wall keeps them keep-only and re-injection restores them, two
  independent locks. M6's reference-derived criteria are operator-tier by
  design: taste is revisable; floors are not. The wall itself is untouched.
- **The coherence gate (live):** new-axis answers ride the enriched goal into
  the SAME single-pass authoring — no new authoring pass is added anywhere in
  this program, so the gate's cannot-disagree-with-itself guarantee covers
  asset and reference criteria for free.
- **The coverage gate (live):** injected asset floors join the criteria the
  coverage machinery already reads; the gate's blocking behaviour is
  unchanged and no slice widens or narrows what it refuses.
- **#1160/#1161 (in flight, merges first):** M4 extends the reserved-verb
  corridor #1160 is re-shaping and builds on its landed honesty notice;
  M1 defers every default rendering to `DEFAULT_AXIS_ANSWERS` so #1161's
  surface-default fix propagates into the new wording automatically. All
  slices cut from main after that branch lands; §9 anchors re-verified then.
- **The S2 record tags (live):** new axis names (`assets`, `extras`) ride
  `record_axes` unchanged — additive tag vocabulary on the same record
  field; the round-trip whitelist already carries `axes` conditionally
  (acceptance.py:1152-1178 discipline), so no record-schema work exists
  outside M5's `operator_assets` field.
- **The hint line + no-questions notices (live):** untouched; M-flags do not
  alter when the quick path hints or what the zero-questions notice says.
- **The battery corridor (review F12):** battery-card dispatches ride the
  same `_plan` corridor. No interview slice can reach them (a card carries
  `decomposition_override` — the existing suppression, already locked), and
  battery projects carry no `assets/` folder, so M5's absent-folder no-op
  keeps every battery plan byte-identical once the flags flip. The
  card-suppression and absent-folder locks pin both halves.

## 6. The two reserved LA decisions — SETTLED (LA in-chat 2026-07-29; record: #1165 c.2649)

The template, its wordings, the assets axis, propose-and-veto, the playback,
the folder contract, and the dormant-merge program shape are all inside the
2026-07-29 approval. The two decisions the umbrella ticket reserved for
design time were put to the LA with recommendations and settled the same
day. The record of both is #1165 c.2649; the DECISION_REGISTER row rides
M6's merge motion together with this section.

**B-1 — what "emulate" may mean: INSPIRATION-GRADE.** The LA delegated the
call to the better-outcomes criterion ("whichever would likely to
consistently have better outcomes"), adding his own reasoning: a small
model cannot copy exactly regardless — "it's almost like having a small
model has built-in differential privacy but for other people's work and not
PII." Under his criterion the resolution is inspiration-grade, which wins
on outcomes as well as posture: describing is the small vision-language
model's strength while pixel-faithful reproduction is its weakness, so
notes-grade criteria are achievable and consistently gradeable where a
copy-closely bar would mint unachievable fidelity checks and blocked
approvals. Design note recorded with the decision: his built-in-variation
observation is right in direction, and the inspiration channel UPGRADES it
from a property of model weakness to a property of construction — only
written design notes ever cross from reference to build (§4 step 2), so the
guarantee survives future model upgrades. A closer-copy grade, if ever
wanted, is a future decision with its own design.

**B-2 — provenance: anything he can screenshot may INSPIRE, and everything
stays home.** The LA saw no question in the locality half — "of course
everything should stay on the device" — and locality is structural, not
configured: no network path exists. The posture proceeds as recommended,
standing-unless-redirected: the reference file and the stated disposition
ride the run's permanent record, and inspiration-grade output never carries
the original's pixels or text into the build. If a closer-copy grade is
ever ratified, own-material-only binds THAT grade from birth.

## 7. Slice, build, and ceremony plan

| # | slice | sub-flag (all default false) | engagement conjunction | depends on |
|---|---|---|---|---|
| M1 | interview voice: template builder + Part 1 wordings + mistake list + Phase-0 preamble | `advanced_intake_interview_voice` | clarify AND front AND interview AND own | fix/1161-1160 merged (wording defers to its default fix) |
| M2 | assets axis: ninth area + default + reconstruction vocabulary + tags | `advanced_intake_interview_assets_axis` | clarify AND front AND interview AND own | M1 (template builder) |
| M3 | propose-and-veto: edge/nongoal propose-form + `extras` axis | `advanced_intake_interview_proposals` | clarify AND front AND interview AND own | M1 (template builder); M2 (final vocabulary) |
| M4 | playback: card invitation + free-text-at-approval → revise (intake only) + the intake carrier on both hold classes (store-codec change, §2 M4) | `advanced_intake_interview_playback` | front AND interview AND own | fix/1161-1160 merged (hard — same corridor) |
| M5 | asset pipeline: folder contract + manifest + card acknowledgment + spec/task fields + use floors | `advanced_intake_assets_pipeline` | front AND own (interview-independent: the folder is explicit intent on any advanced-front dispatch, and the card acknowledgment keeps it visible + vetoable) | fix/1161-1160 merged (shared coordinator surface) |
| M6 | reference extraction: sanitize + VLM design notes + reference criteria + fidelity lens + banner-rot retirement (F10) | `advanced_intake_reference_extraction` | front AND assets_pipeline AND own | M5 (folder + manifest); B-1/B-2 SETTLED (c.2649) — no open gate |

**Build order.** After fix/1161-1160-plan-time-brittleness merges and anchors
re-verify: wave 1 in parallel worktrees on disjoint surfaces — M1
(clarify template + render), M4 (coordinator card corridor), M5
(acceptance/plan + folder) — then wave 2: M2 → M3 (sequential on the
template/vocabulary), then M6 last. Merge coordination at merge time as
S2/S3 practiced (additive keywords; no semantic collision expected, verified
at each merge).

**Review discipline, per slice:** author ≠ verifier — an independent
reviewer per slice who did not write it, findings dispositioned
(`docs/reviews/`, machine-checkable block, verifier run), fixes
fix-VERIFIED by the reviewer, never self-certified. The merged whole re-runs
the standing gate on merged main after each merge; every slice ships its
toggle-off suite in the same change.

**What merges dormant, and the ceremony.** All six slices merge DORMANT
behind their own sub-flags. ONE batched LA-present ceremony (the proven
D/E/F/G shape): runbook
`docs/runbooks/advanced_intake_maturation_batched_ceremony.md` (written in
the program's first merge motion, authored from the c.2649 record — not
from a decide-script; review F3). Its opening step RATIFIES the settled
B-1/B-2 on the witnessed record — nothing is decided at the ceremony,
because both decisions are already made — then: flip M1–M6 → gate → merge
live → drive one witnessed `advanced` intake end to end (preamble,
nine-plus-one areas, a seeded assets folder acknowledged on the card, a
playback correction, and one reference extraction under the ratified
inspiration grade) → evidence to #1165. Recommended as ONE ceremony;
splitting M6 to its own later ceremony is equally buildable if the LA
prefers to drive A first — the flags make either grouping a flip-set
choice, not a build choice.

**Tickets.** #1165 stays the umbrella; each slice opens its own build ticket
at kickoff citing this design; the M-horizon (staged rounds) gets its
evidence-gated ticket with the §2 predicate; every merge closes its slice
ticket citing the shipping SHA and comments what it unblocks.

## 8. Security by design — named at design time (doctrine requirement)

**Trust boundaries.** All local. (1) The operator-facing dispatch front
inside the resident-model PLAN window — the S1/S2/S3 boundary, unchanged.
(2) NEW with M5: the `assets/` folder — operator-controlled FILES entering
prompts, manifests, and worktrees. (3) NEW with M6: reference images —
files that may ORIGINATE elsewhere (downloaded screenshots) even though they
arrive by the operator's hand, feeding a model's image decoder. No network
client, no egress, no coordinator write path anywhere in the program; the
self-governance boundary (ADR-039) is not in any path. If any future
enrichment appeared to want egress (fetching a URL the operator named
instead of a screenshot), that is a decision_boundary escalation, not a
design choice — this design's answer is the screenshot.

- **Validate before trust — the load-bearing new rule:** file paths typed in
  interview ANSWERS are recorded words, NEVER dereferenced; the only path
  the system acts on is its own rooted enumeration of `assets/` — closed
  extension AND filename-character allowlists (the F5 hygiene class: bidi
  override, zero-width, and control characters cannot survive the walk),
  ALL reparse points excluded fail-closed (symlinks, junctions, mount
  points — junctions need no elevation, F6) with containment-after-
  resolution, per-file and total size caps, relative paths only in every
  manifest, card line, prompt, and record. A forged or hostile path in an
  answer dies as prose; a hostile NAME dies at the walk. M5's lock suite
  probes the junction/reparse and containment exclusions explicitly, not
  only the name shapes.
- **Untrusted content stays data:** reference images and asset documents get
  the sanitize step (format allowlist, byte caps, header-first
  pixel-dimension gate, decode-and-re-encode to a clean bitmap) BEFORE any
  model sees them; extraction output is provenance-tagged design-notes text
  that authors criteria through the SAME rulers as any authored criterion.
  No file content gains instruction authority; filenames render only as
  quoted list entries; the operator-words corpus
  (`operator_answers_from_block`) never ingests manifest or machine prose
  (hygiene lock, §3).
- **Principle-9 deviation, argued at design time (review F7):** the doctrine
  prefers guest-VM isolation for parsing untrusted input; M6 decodes
  reference images HOST-SIDE, deliberately: (1) the files are
  operator-placed in his own project folder, never network-arriving
  content; (2) the decode surface is ONE allowlisted decoder over two
  formats behind the header-first dimension gate and byte caps; (3) only
  the sanitize step's output — a re-encoded clean bitmap — travels onward,
  so the sanitize step IS the boundary control; (4) the VLM is
  host-resident on the GPU, so pixels must reach the host regardless — a VM
  hop would relocate the decoder yet return the same bitmap, adding a
  channel without removing the class. Residual risk — a decoder
  vulnerability triggered by an operator-placed file — is named and
  accepted; the allowlist, caps, and re-encode bound it.
- **Fail-closed at every new decision point:** sub-flags resolve False on
  missing/garbage config; a file failing the allowlist, name hygiene, caps,
  or decode is skipped with a named notice, never half-used; the machine
  wall keeps the injected MACHINE floor keep-only with re-injection as the
  second independent lock (the visual-tier asset criterion sits deliberately
  OUTSIDE the wall — operator-tier, droppable; §3, review F8).
- **Fail-SOFT only in the convenience layer, and loudly:** manifest
  enumeration failure plans WITHOUT assets and says so on the card (a broken
  folder read must not block a build the quick path would serve); VLM
  extraction failure yields no reference criteria plus a card notice (the
  `VlmCritique` contract). Nothing fails open; the distinction copies S2 §4
  verbatim: control-shaped paths CLOSED, convenience paths SOFT to the
  proven baseline.
- **Deny-by-default vocabularies:** the axis sets stay closed frozensets at
  every width; the extension allowlist admits named classes only; the
  emulation grade ships as the single inspiration grade (§6 B-1) — a wider
  grade is an LA ratification, not a config value.
- **Least data across boundaries:** manifests carry names, classes, and
  sizes — never file contents; design notes carry descriptions — never
  bitmaps; the record carries the operator's words and relative names only.
- **Dormant by construction, every slice:** default False in dataclass AND
  parse AND property AND every new keyword; OFF is the untouched existing
  code path. **Every control tested off:** each slice's toggle suite proves
  flag-off byte-identity at its seams AND that the probes fail when the flag
  is on — "off" stays distinguishable from "unreachable".
- **Loop-signal rule preserved:** the VLM never verdicts; visual criteria
  remain eyeball-tier at approval. M6 adds a lens, not an authority.

## 9. Grounding reads for the building sessions (≤8, in order; anchors verified 2026-07-29 at 88ce3953 — RE-VERIFY after fix/1161-1160 merges)

1. `shared/fleet/clarify.py` — WHOLE (591 lines): axes + intake constants
   :51-115, templates :133-173, schema/parse/ruler :179-285, generator
   :288-328, decide/reconstruction/answers :339-438, sentinel seams
   :445-483, block/corpus discipline :487-547.
2. `services/ui_gateway/src/dispatch_coordinator.py` — `:174-233`
   (`PendingDispatch` + `PendingClarification`, M4's carriers — neither
   holds an intake bit today), `:409` (`parse_dispatch_command` — the
   pipe-less run shape behind M4's verified baseline), `:846-1236` — the
   command routing, `_plan` (advanced gate :898-1008, hint :976-986,
   notices :988-1000, the #1116 usage/keep-text branch :905-914),
   answer/decide states :1012-1059, replan + #1152 contract :1061-1101,
   renders :1103-1130, `_finalize_plan` :1132-1140 (M5's card seam + M4's
   threading point), create :1197-1236; `PendingRequirements` + codec at
   :237 region; `_repo_path` :1912-1914.
3. `services/assistant_orchestrator/config/default.toml:460-745` — the six
   live advanced_intake* blocks whose register every new sub-flag copies.
4. `shared/fleet/acceptance.py:3956-3970` (`generate_plan` — receives
   `repo` + `projects_dir`, the plumbing M5's AO-side enumeration rides),
   `:2300-2327` (`_thread_build_fields` — the VLM loop fields + the
   task-dict conditional-stamp precedent :2319-2323), `:2885-2902`
   (`visual_criteria_texts` + the eyeball rule), `:65-71` (tiers),
   `:1152-1178` (the round-trip whitelist discipline — the spec-side
   additive-field pattern `operator_assets` copies).
5. `shared/fleet/critique.py` — WHOLE: the loop-signal rule, the fail-soft
   contract, `LENSES` (static — M6's reference lens is call-time-built, not
   a dict entry), the module CLI the fleet loop invokes. WARNING (review
   F10): its "DORMANT / not wired" banner and acceptance.py:2307-2313's "no
   live caller" note are ROTTED — the loop is LIVE fleet-side
   (agentic-setup `critique-loop.ps1`; `new-agent-task.ps1` step [6/6]); M6
   retires both banners in its motion.
6. `docs/design/advanced_intake_S2_elicitation_interview_DESIGN.md` §3-§5 —
   the flag chain, seam style, and toggle-lock register every M-slice
   copies; `docs/design/advanced_intake_S3_criteria_and_exam_authoring_DESIGN.md`
   §3.2 — the floor-injection shape M5's asset floor mirrors.
7. `docs/runbooks/advanced_intake_interview_go_live.md` (EXECUTED banner —
   the settled memory posture) + `docs/runbooks/advanced_intake_s3_batched_ceremony.md`
   — the batched-ceremony pattern §7's runbook copies.
8. The post-merge shape of fix/1161-1160-plan-time-brittleness (its branch
   diff on main once landed) + #1160/#1161 ticket records — the corridor
   M4 extends and the default fix M1 must not re-pin.
