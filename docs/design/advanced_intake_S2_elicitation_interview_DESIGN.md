---
title: "Advanced Intake S2 — the elicitation interview"
status: DESIGN — independently reviewed 2026-07-28 (APPROVE-WITH-FIXES, all 8 findings folded in; disposition in docs/reviews/) — pending LA morning read; the plain-language read is §0
area: design
date: 2026-07-28
ticket: "#1031 (advanced-intake programme; design-sketch build-slice S2)"
grounded_at: "main 8c386771; every line anchor below read on disk at that commit tonight"
grounding_reads: "S3 design doc (docs/design/advanced_intake_S3_criteria_and_exam_authoring_DESIGN.md); 2026-07-21 design sketch §3/§5.3; shared/fleet/clarify.py whole (458 lines); services/ui_gateway/src/dispatch_coordinator.py 88-560, 560-951, 951-1140, 1266-1274; shared/fleet/acceptance.py 380-514, 1152-1178, 3772-3980; services/assistant_orchestrator/src/entrypoint.py 600-700, 1195-1260, 2230-2260, 3240-3340; services/assistant_orchestrator/config/default.toml 420-615; shared/fleet/dispatch.py 511-530; launcher/__main__.py 2062-2093; services/ui_gateway/src/transport.py 495-548, 1577-1585"
---

# Advanced Intake S2 — how the fuller requirements interview works

## 0. Plain-language read (for the Lead Architect)

Today, when you ask BlarAI to build something, it may ask you a few quick
questions first — at most five, about where it runs, whether data is saved,
the one must-work feature, the look, and the size. That stage works, and it
stays exactly as it is.

**What S2 adds is a fuller interview you can ask for.** Typing
`/dispatch advanced my-project | what to build` (the word `advanced` after
`/dispatch`) runs a longer version of the same conversation — still one
screenful at most, still answerable in one plain-language reply, still with
the "just decide for me" escape — that also asks about three things the quick
questions never cover:

- **Content** — what real text, items, or starting data it should contain.
  This is the question whose absence made a build invent fake portfolio
  projects and present them as real (the Blair's Lab lesson): nobody asked,
  so the machine made things up silently.
- **The awkward cases** — what should happen when something odd or wrong is
  entered, in your own words, before the build starts.
- **Non-goals** — what this first version should deliberately NOT include,
  so the scope fence is yours instead of guessed.

**You are never interviewed without asking for it.** A normal `/dispatch` is
byte-for-byte today's behaviour. The only nudge is one honest hint line: when
a big, ambiguous ask comes in on the quick path, the questions may end with
"this looks like a bigger build — the `advanced` form asks a fuller set." A
long goal silently triggering a longer interview was considered and rejected:
being quizzed by surprise is how a tool stops being used.

**Everything you say lands on the record.** Your answers already ride the
plan card and the run's acceptance record; S2 additionally tags which decision
area each answer covered, so a later reader of a run can see what was asked
and what was assumed. No new file, no new store — the same run record it
already writes.

**If the interview machinery ever fails, you lose nothing:** the dispatch
falls back to exactly the quick behaviour that works today. An interview
failure can slow you down by zero questions, never block a build.

This merges **dormant behind its own new flag, off by default** — the live
`advanced_intake` switch you flipped on 2026-07-22 does not and cannot turn
this on. Go-live is a ceremony you run, exactly like S1's was. The one
decision I need from you is at the end, §6: what `advanced` should do on a
project that already has remembered answers.

---

## 1. Scope, naming, and where the sketch had drifted

Naming, restated from the S3 design doc's reconciliation so a successor is
not confused: the 2026-07-21 design sketch numbers build slices S1–S4. Its
**S1** (delivery floor + realism guard) is the shipped, LIVE `advanced_intake`
front. Its **S3/S4/Stage-2** material became the LA's "S3" authoring redesign
(#1069, its own design doc; slices D and E of that doc are BUILT — the
`bad_input_floor` and `coherence_gate` sub-flags exist in source today, and
slice F is in flight in a parallel session). **This document is the sketch's
S2** — the elicitation interview, the last unbuilt limb of the programme.

**In scope:** the mode-selected fuller interview — token parsing, the three
new decision axes, the raised intake-mode question cap, threading the mode
across the gateway→AO seam, the transcript on the acceptance record, and the
sub-flag wiring. **Out of scope:** everything the S3 doc owns (criteria/exam
authoring, coverage gate, criteria-revise); voice-driven intake (open LA
experience call, unchanged from the sketch); spec-reuse templates (open
product question, unchanged).

**Where the sketch contradicted or trailed current source** — each verified
tonight; treat the sketch's §5.3 as intent, this section as fact:

1. **Every line anchor in sketch §2/§5.3 has drifted.** `clarify.py` is 458
   lines, not 415 — `operator_answers_from_block` (:389-415, the #1043 review
   F1 fix) was inserted after the sketch, moving `compose_planning_goal` from
   the sketch's :374-381 to :418-425. `parse_dispatch_command` is at
   :346-419, not :161-219; `PendingRequirements` at :211-233, not :136-158;
   the render/answer/decide handlers at :951 / :876 / :898, not
   :488 / :429 / :453; the acceptance-record write call at :1266-1274, not
   :772-779; `generate_plan` at acceptance.py:3772, not :2904. The
   coordinator grew ~185 lines of #1116/#1120/#1126 machinery above the
   parser; acceptance.py grew ~870 lines of S3-D/E. Section 7 carries the
   verified current anchors.
2. **The sketch's flag plan is superseded by events.** §5.1 designs ONE flag,
   `advanced_intake = false`, gating everything. That flag is now LIVE
   (`default.toml:484`, go-live 2026-07-22), and the house has since split
   sub-capabilities into their own keys (`advanced_intake_bad_input_floor`
   :523, `advanced_intake_coherence_gate` :610). S2 on the sketch's plan
   would go live at merge. This design therefore gives the interview its own
   sub-flag (§3.1) — the S1 flag comment at `default.toml:462` explicitly
   promises "NO wider elicitation interview" from the live key, and that
   promise binds this slice.
3. **"No new session state class" survives, but not for the sketch's
   reason.** The sketch assumed `PendingRequirements` carries the extended
   interview as-is. It carries the questions, but the reconstruction seam
   does not: `questions_from_dicts` (clarify.py:291-309) coerces any axis
   outside the five-member `CLARIFY_AXES` to `feature`, so a parked
   `content` question would come back mislabeled and its "just decide"
   default would be the wrong one. The hold state needs one additive boolean
   (§3.4); the class survives.
4. **The sketch's §2 pipeline description predates the #1152 park-until-
   success rule** — the requirements slot now clears only when the re-plan
   returns a plan (`dispatch_coordinator.py:909-949`), a contract the
   interview inherits and must not disturb.
5. **Sketch §5.5's claim that the multi-task job-oracle receives the clean
   goal** was already retired by #1032 (the S3 doc verified this; recorded
   here only so no one re-fixes it from the sketch).
6. **The sketch's mode-select mentions "size/ambiguity heuristics" as a
   co-equal entry path.** Decided against (§3.2): heuristics demote to a
   deterministic hint line; they never enter the mode.

## 2. The gap, in source — why the quick path cannot carry this

The quick interview's axis vocabulary is closed and five-strong by design:
`CLARIFY_AXES` (clarify.py:60-63) is a frozenset the question grammar
enum-pins (`clarify_questions_emission_json_schema`, :135), the parser
enforces (unknown axis → coerced to `feature`, :213-214, deduped one-per-axis
:215-217), and the cap seals (`DEFAULT_MAX_QUESTIONS = 5`, :67). That is the
right shape for the quick path — "a few, not a quiz" — and it is exactly why
three measured defect classes cannot be asked about there:

- **Content is never elicited.** No axis asks what the thing should contain,
  so under-specified content is invented silently (the Blair's Lab
  placeholder-projects row in the quality ledger; sketch §1). The
  `DEFAULT_AXIS_ANSWERS` table (:75-81) has no content entry to even assume.
- **Edge behaviour is never elicited.** The operator's own awkward cases
  never reach the spec, so the exam asserts nothing about them — the #1044
  class the S3 bad-input floor now catches mechanically, but a machine floor
  asserts "does not crash", not "does what the operator wanted".
- **Non-goals are never elicited.** The scope fence is inferred, and the
  revise wall is deliberately one-way (revision edits FEATURE tasks only;
  criteria are immutable across a revision — the safety asymmetry, sketch §1,
  verified in the S3 doc). The intake is structurally the ONLY place a scope
  fence can be born with the operator's authority behind it.

One missing property — *the interview's vocabulary is sized for the smallest
ask* — expressed three ways. The fix is not to widen the quick path (its
smallness is a guard, not a gap); it is a second, operator-selected mode over
the same skeleton.

## 3. The design

Shape summary: the operator opts in with an `advanced` token; the gateway
rides the existing goal-string seam to tell the AO; `generate_plan`'s
existing clarify stage runs with a wider closed axis set and a higher cap;
answers flow back through the unchanged #819 corridor; the record gains axis
tags. No new IPC verb, no new store, no new session-state class, no new
model call shape.

### 3.1 The sub-flag (house style, three worked precedents copied exactly)

Key: `[fleet_dispatch].advanced_intake_interview = false` — sibling of
`advanced_intake_bad_input_floor` (default.toml:523) and
`advanced_intake_coherence_gate` (:610), with the same comment register:
ticket first, THIS-COMMENT-IS-THE-CEREMONY'S-ARTIFACT note, WHAT true DOES /
WHAT IT DOES NOT DO, the VALIDATED-NOT-COERCED (#1042) note, and
`capabilities(fleet_dispatch.advanced_intake_interview):` lines naming the
token parser, the extended-axes generator, and the transcript tagger.

Wiring copies the #1054 chain verbatim, current anchors:

- dataclass field `fleet_dispatch_advanced_intake_interview_enabled: bool =
  False` beside entrypoint.py:659 (the coherence-gate field — the newer
  naming convention that keeps the `advanced_intake` stem);
- parse `fleet_dispatch.get("advanced_intake_interview", False) is True`
  beside :2252-2254 (validated, not coerced — #1042);
- resolved property beside :1239-1257, same `is True` shape, same docstring
  posture: the property answers only "what does the config say"; the
  conjunction lives at the places that act (§3.3, §3.5);
- threaded into `generate_plan(interview=...)` at the call site beside
  :3327-3329, and into the gateway at construction (§3.5).

**Requires the front AND itself — AND the clarify stage (review F5):** like
both sub-flag precedents, the interview engages only when `advanced_intake`
AND `advanced_intake_interview` are both `True` — a sub-flag may not engage
a capability inside a front that is off, and the front being live is not
consent for what lands inside it later (entrypoint.py:661-663 states the
rule; this slice inherits it). The interview additionally rides the existing
clarify gate, so real engagement is `clarify AND advanced_intake AND
advanced_intake_interview` (plus no-requirements, no-override — the :3901
predicate). `clarify = true` is live today (default.toml:389) and has its
own documented off-switch; the go-live runbook names it a ceremony
precondition, and with it false an `advanced` dispatch asks nothing and
renders the §3.7 notice.

**Flag off ⇒ byte-identical, by construction not by discipline:** every new
parameter in this design defaults to today's value (`axes=CLARIFY_AXES`,
`max_questions=DEFAULT_MAX_QUESTIONS`, `interview=False`,
`intake_token=False`, `record_axes=False`, `intake=False`), so the OFF state
is not a branch that restores old behaviour — it is the old code path,
untouched.

### 3.2 Mode selection — explicit token; heuristics demoted to a hint (decided)

**The decision:** entry into the fuller interview is the explicit `advanced`
token only: `/dispatch advanced <repo> | <goal>` and
`/dispatch advanced new <name> | <goal>`. Size/ambiguity heuristics do NOT
enter the mode. Instead, ONE deterministic hint line rides the quick path's
question render when (a) the interview flag is on and (b) the goal is ≥ 40
words (`_INTAKE_HINT_MIN_WORDS`, a named judgment constant): *"Bigger build?
`/dispatch reject`, then `/dispatch advanced <project> | <same goal>` for a
fuller interview."* The hint is honest about the mechanics (reject, then
re-dispatch) rather than pretending an in-corridor switch exists.

**Rejected: heuristic mode entry** (the sketch's "or size/ambiguity
heuristics"). A novice typing a long goal and receiving an eight-question
interview they never asked for is the least-surprise violation in its purest
form, and it burns the one asset the interview has — the operator's patience
— on dispatches that never consented to spend it. The sketch's own §3 warning
("an interrogation would kill the tool") argues against its own heuristic
clause. The hint keeps the heuristics' entire value (discoverability) at the
cost of one line of text and zero surprise. Ambiguity heuristics specifically
would also need model judgment on the gateway side, where no model lives —
only the deterministic size ruler is even implementable at this seam.

**Parser mechanics, fail-closed** (`parse_dispatch_command`,
dispatch_coordinator.py:346-419): the function gains a keyword
`intake_token: bool = False`. When False (the default — every existing call
site), the parse is today's, byte for byte. When True and the rest begins
with `advanced` followed by whitespace (the same any-whitespace rule #1126
established for the prefix, :358-367), the token is stripped and the
remainder parsed by the normal verb logic — and **the `advanced` flag
attaches ONLY when that remainder parses to `create`, or to `run` with a
NON-EMPTY repo (the piped `<repo> | <goal>` form)**. For ANY other remainder
— a verb like `approve`, and especially the pipe-less run-with-empty-repo
shape — the ORIGINAL rest is parsed exactly as today, nothing stripped.
The pipe-less carve-out is the load-bearing half (review F1): a pipe-less
remainder parses as `run` with the whole text as `goal`, and that exact
shape is how a pending requirements ANSWER arrives at the corridor — so a
free-text answer that happens to begin with the word "advanced" ("advanced
look with dark mode…") would otherwise reach `handle_command` with its first
word eaten, mutating what the operator said (the #1116/#1126
eats-operator-text class, whose third shipped instance would owe a
structural control per the LESSONS rule). With the carve-out, answers and
usage-nag echoes stay verbatim on every path; the token costs exactly the
two forms it buys, and a dedicated parse lock drives the
answer-starting-with-"advanced" shape.
`DispatchCommand` gains `advanced: bool = False` (additive field on a frozen
dataclass that is never persisted — no round-trip surface). A repo literally
named `advanced` becomes reachable only by another name when the flag is on —
the same documented one-ambiguous-case trade-off the parser already carries
for `new`, `revise`, and `forget` (:380-382, :393-395, :398-400), recorded in
the same comment register.

### 3.3 The extended interview — closed vocabulary, structural cap, same ruler

All in `shared/fleet/clarify.py`, all parameterized with today's values as
defaults:

**Three new axes**, same discipline as the five (:44-49 — product-level
decisions that fork WHAT gets built, unanswerable-by-assumption,
answerable by a non-developer, never technical):

| axis | asks | "just decide" default (recorded as an assumption) |
|---|---|---|
| `content` | what real text, items, or starting data it should contain | "starts with clearly-labelled example content for you to replace — nothing invented that pretends to be real" |
| `edge` | what should happen when something odd or wrong is entered | "unusual or wrong input gets a clear message instead of a crash or a silent guess" |
| `nongoal` | what this first version should deliberately NOT include | "nothing beyond what you described — no extra features added on speculation" |

The `content` default bakes the Blair's-Lab lesson into the escape hatch
itself: even an operator who answers nothing gets labelled-placeholder
posture, never silent invention. The sketch's Stage-1 "purpose and audience"
and "delivery target" items are deliberately NOT new axes: delivery target IS
the existing `surface` axis (the scaffold-profile selection rides the
existing build-signal machinery), and purpose/audience folds into
`feature`/`scope` — three genuinely uncovered axes, not five renamed ones.

**Vocabulary:** a new `INTAKE_AXES: frozenset = CLARIFY_AXES | {content,
edge, nongoal}` (8 members). `CLARIFY_AXES` itself is UNTOUCHED — it is
load-bearing in three places that must not move flag-off (the grammar enum
:135, the parser coercion :213-214, the reconstruction coercion :306-307).
`generate_clarifying_questions`, `_parse_questions`,
`clarify_questions_emission_json_schema`, and `questions_from_dicts` each
gain `axes: frozenset[str] = CLARIFY_AXES`; the intake path passes
`INTAKE_AXES`. Unknown axes still coerce to `feature` — the extended set is a
WIDER closed vocabulary, not an open one (deny-by-default holds in both
modes). `DEFAULT_AXIS_ANSWERS` gains the three rows above; safe
unconditionally, because on the quick path the five-axis coercion makes the
new keys unreachable.

**Cap and the one-screenful bound:** `INTAKE_MAX_QUESTIONS = 8 ==
len(INTAKE_AXES)`. The bound is structural, not aspirational: the ruler
dedupes one question per axis (:215-217), so eight axes cannot yield nine
questions no matter what the model emits. Rendered, that is at most 14 lines
(title + blank + 8 questions + blank + 3 instruction lines) — one screenful
in the WinUI transcript. `DEFAULT_MAX_QUESTIONS = 5` and the quick path's use
of it are untouched.

**Prompt:** a new `_INTAKE_TEMPLATE` describing all eight axes in the
existing template's register (:99-115) — plain language, no jargon, the same
"SKIP any the request already answers" sufficiency instruction, the same
return-`[]`-when-clear contract. `_CLARIFY_TEMPLATE` is untouched. The
sufficiency check therefore survives in intake mode: a fully-specified
`advanced` ask gets zero questions and proceeds straight to the card, exactly
as #819 promised ("never a mandatory quiz" — the verbatim phrase at
clarify.py:236 and acceptance.py:3827; the module header's wording at
:16-17 is "ZERO questions, no quiz"; review F8).

**Failure:** `generate_clarifying_questions`'s absolute fail-soft (:22-23,
:238-240 — ANY failure returns `()`) is inherited untouched. An interview
that cannot run degrades to direct planning; it can never block a dispatch
the quick path would have served.

### 3.4 Crossing the seams — marker on the goal string, one additive hold field

**Gateway → AO (the mode signal).** The plan seam is `plan_fn(repo, goal)`
(dispatch_coordinator.py:138-140); both prior stages refused to widen it and
rode the goal string instead (`REQUIREMENTS_SENTINEL`, clarify.py:345-351;
`REVISE_SENTINEL` detected inside `generate_plan`, acceptance.py:3878). S2
does the same: a new `INTAKE_SENTINEL` marker constant in clarify.py beside
the requirements sentinel, with pure+total `compose_intake_goal` /
`split_intake_goal` helpers mirroring :418-437. The coordinator appends it
for an `advanced` dispatch; **compose order is marker-then-requirements** —
the marker rides the goal HEAD so that the AO-side `split_planning_goal`
(entrypoint.py:3279) leaves it on the `clean_goal` that becomes
`generate_plan`'s `idea`, never in the requirements block.

**AO-side engagement** (`generate_plan` gains `interview: bool = False`, the
config sub-flag, threaded from the entrypoint property like its two sub-flag
siblings :3323, :3327-3329): when `advanced_intake AND interview`, the marker
is detected and stripped from `idea` first (the :3878 revise-sentinel
precedent), and the existing clarify stage (:3901-3919) runs with
`axes=INTAKE_AXES, max_questions=INTAKE_MAX_QUESTIONS`, the intake template —
same validate_repo pre-check, same early return, same fail-soft. When either
flag is False the marker is INERT TEXT: nothing strips it, nothing acts on
it, and the byte-identical bar holds on every input including an
operator-typed marker (the toggle-off test's subject). The marker is stripped
before `planning_seed` forms (:3921-3924), so it can never reach `spec.goal`,
a prompt, or a compiled task — a hygiene lock pins this.

**Card-driven dispatches self-suppress by construction, not by a new rule:**
the interview runs inside the existing clarify gate, whose predicate is
`clarify and not req and decomposition_override is None` (acceptance.py:3901)
— a battery card carries a `decomposition_override`
(entrypoint.py:3289-3296), so a card dispatch cannot reach the interview any
more than it can reach today's questions. Verified in source; locked by a
test anyway, because inherited guarantees are the ones that silently break.

**The hold state** (`PendingRequirements`, dispatch_coordinator.py:211-233):
gains ONE additive field `intake: bool = False`, with the codec carrying it
(`_requirements_to_payload`/`_from_payload`, :248-260). The writer emits the
key ONLY when True — a flag-off quick-path park stays byte-identical at the
store seam, the same discipline §3.6 applies to the record (review F2) — and
the reader is `d.get("intake", False)`, so every pre-S2 parked row restores
as a quick-path question set, which is what it is. This is the minimal extension §1 item 3
argued: without it, the answer/decide turn cannot know which axis vocabulary
to reconstruct with, and a restored `content` question would mislabel as
`feature` and self-answer with the wrong default. `_answer_requirements`
(:876-896) and `_decide_requirements` (:898-907) pass
`axes=INTAKE_AXES if pending_req.intake else CLARIFY_AXES` into
`questions_from_dicts`. No new slot, no new codec entry, no new store — the
`_SLOT_CODECS` table (:339-343) is untouched.

**The corridor is otherwise unchanged**, verified end to end: answers ride
`answered_from_free_text` (one reply answers all — the novice shape, :325-339)
or `decide_defaults` (:312-322); the re-plan threads them through
`compose_requirements_block` → `compose_planning_goal` → the AO's
`split_planning_goal` → `generate_plan(requirements=...)` → `planning_seed`
(acceptance.py:3924) with **no schema change** — extended answers are more
text in the same block. The re-plan needs no marker: `requirements` non-empty
already suppresses the clarify stage (:3901), and nothing else in this slice
is per-dispatch. The #1152 park-until-success contract (:909-949) is
inherited untouched — an intake answer lost to a transport failure stays
parked and retryable, same as a quick-path answer.

### 3.5 Flag threading to the gateway — one config read, the launcher chain

The gateway never parses TOML: every dispatch flag it holds is threaded from
the AO's resolved properties at construction (launcher/__main__.py:2077-2087,
"read off the already-started orchestrator service, never a second TOML
parse"; transport.py:350-351 → :534-544). S2 adds
`fleet_dispatch_advanced_intake_interview_enabled` to that chain: entrypoint
property → launcher kwarg → transport ctor param (default False) →
(a) the `parse_dispatch_command(..., intake_token=...)` call at
transport.py:1581, and (b) a `DispatchCoordinator` ctor param beside
`project_memory_enabled` (:439) gating the hint line and the sentinel
append. One config read for both processes, so the gateway's token gate and
the AO's engagement gate cannot disagree about what the file says; they
remain two independent locks in two processes, each failing closed on its
own default-False.

**AND the front flag, gateway-side too:** the launcher threads
`advanced_intake AND advanced_intake_interview` resolved values
independently; the transport passes the interview flag to the parser only
when both are true — mirroring the AO-side conjunction, so a live interview
key inside a (hypothetically re-welded) dormant front stays dark at both
seams.

### 3.6 The transcript — axis tags on the record it already writes

The acceptance record is `{"spec": spec.to_dict(), "repo": ...}`, written
run-id-keyed before EXECUTE fires (`write_acceptance_record`,
dispatch.py:511-520; called in `_approve`, dispatch_coordinator.py:1266-1274)
— and `spec.clarifications` already rides `to_dict` (acceptance.py:437), so
the Q&A transcript is ALREADY persisted today. What is missing is which
decision area each entry covered.

**Additive field:** clarification dicts gain `"axes": [<axis>, ...]` —
written ONLY in intake mode. `decide_defaults` and `answered_from_free_text`
gain `record_axes: bool = False`; when True, a decide-path dict carries its
question's single axis, and the free-text path's one merged dict carries the
full asked-axes list (the one-reply-answers-all shape has no per-axis split
to record, and manufacturing one from a free reply would be model guesswork
presented as fact). Default False keeps every quick-path dict — and thus
every flag-off record — byte-identical.

**The round-trip is a whitelist and must be extended, not assumed:**
`_coerce_clarifications` (acceptance.py:1152-1178) rebuilds each dict with
exactly `{question, answer, assumed, remembered}` — an unlisted key is
silently dropped on every `from_dict`, which crosses the IPC and the record
read. The #1120 `remembered` key hit exactly this and its comment (:1171-1175)
is the precedent: S2 adds a conditional carry — `axes` survives only when
present as a list, coerced fail-closed to its well-shaped subset (non-blank
strings), and is NEVER emitted for a dict that arrived without it (an
unconditional `"axes": []` would change every flag-off record's bytes). A
round-trip lock drives dict → `to_dict` → `from_dict` → record write → record
read and asserts both fidelity (intake dicts keep their tags) and absence
(quick dicts gain nothing).

**No new data class crosses any boundary:** the record already carries the
operator's Q&A on the operator's own disk (sketch §6 resolved this); S2 adds
axis LABELS to entries that already exist. The parked interview rides the
born-encrypted dispatch state store like every #819 question set
(dispatch_coordinator.py:236-245).

**Project-memory replay, named rather than discovered (review F6):**
`remember_answers`/`recall_answers` (dispatch_state_store.py:350-406) bank
and replay FULL dicts with no key whitelist, so an intake answer banked with
`axes` replays its tags onto later dispatches — including quick ones — once
memory is live. The labels stay truthful and grant nothing, and both
features' go-lives are LA-held (§6 already owns the intersection); the
transcript round-trip lock covers the banked-answer path so the behaviour is
pinned, not discovered.

### 3.7 The no-questions notice — honest in both directions

When an `advanced` dispatch comes back with a plan and zero questions, the
operator who asked for an interview deserves one line explaining why there
was none: the plan card is prefixed *"No further questions — planning
directly."* via the existing `clarified_note` seam
(`_finalize_pending`'s parameter, :1094; rendered :1135-1136). The wording is
chosen to be TRUE on both paths that produce it — a sufficient goal (the
model returned `[]`) and a failed generation (fail-soft `()`) — because the
two are deliberately indistinguishable at this seam (#819's absolute
fail-soft collapses them, and un-collapsing would widen the failure surface
the collapse exists to close). Gated on `command.advanced`, so no flag-off or
quick-path render changes.

Mechanics, stated so the builder does not discover them at the seam (review
F3): `_finalize_plan` (:967-1020) gains a passthrough `clarified_note`
parameter that it forwards ONLY on its direct tail call to
`_finalize_pending` (:1016-1020) — that is the sole path the notice rides.
When the Inc-4 platform question interposes instead (:998-1014), the notice
is deliberately SUPPRESSED: a question DID appear, so no explanation is
owed, and the later `_choose` path keeps its own "Got it — building it
for…" note uncollided. A lock case covers the Inc-4-follows shape. With
`clarify = false` (see §3.1's precondition, review F5) no dispatch asks
anything and the same notice renders — accurate there too; the go-live
runbook names `clarify = true` as a ceremony precondition so that state is
deliberate, never a mystery.

## 4. Security by design — named at design time (doctrine requirement)

**Trust boundary touched:** the operator-facing dispatch front, inside the
existing 14B-resident PLAN window — the same boundary as S1/S3, no new one.
**What can reach it:** the operator, through the existing `/dispatch` verbs
in the existing gateway corridor. **What it can reach:** the plan/spec
objects, the parked-state store, and the acceptance record — all existing
surfaces, all local.

- **No egress, none, and no path to add one.** The interview asks the
  OPERATOR questions; no network client, no fetch, no external lookup exists
  anywhere in this design. If any future enrichment appeared to want one,
  that is a decision_boundary escalation, not a design choice.
- **No coordinator write path; self-governance boundary untouched.** This is
  operator-initiated authoring on the operator's own dispatch; ADR-039's
  advisory-only severance is not in the path.
- **Fail-closed at every NEW decision point.** The parser token falls
  through to today's parse on anything but a well-formed run/create (§3.2 —
  a garbled `advanced approve` nags, nothing fires). The sub-flag resolves
  False on missing/garbage/unparsed config (`is True`, both parse and
  property). `questions_from_dicts` keeps its coerce-don't-drop posture with
  the axes parameter. `_coerce_clarifications` drops a malformed axes value
  rather than propagating it.
- **Fail-SOFT exactly where the doctrine demands it, and nowhere else:** an
  interview generation failure degrades to the quick path (a dispatch the
  quick path would have served is never blocked — the brief's named
  requirement), inheriting #819's absolute fail-soft. The distinction is
  deliberate: control-shaped paths (flags, parsing, coercion) fail CLOSED;
  the convenience layer fails SOFT to the proven baseline. Nothing fails
  open.
- **Deny-by-default vocabulary:** both axis sets are closed frozensets; the
  grammar schema enum-pins whichever set is active; an axis outside the
  active set coerces to `feature`, never passes through. The extended set is
  a second allowlist, not a loosened one.
- **Validate before trust on operator input — unchanged posture, stated
  honestly:** the operator is the TRUSTED principal on this boundary (their
  goal, their machine, their build). Their free-text answers become DATA in
  the requirements block exactly as #819 ships today — house-prose separation
  via `operator_answers_from_block` (:389-415) already exists for consumers
  that must not confer authority on non-operator words, and S2 changes
  nothing about that seam. The `advanced` token and the sentinel grant no
  privilege beyond MORE QUESTIONS; an operator typing the raw sentinel into
  a goal (both existing sentinels share this property, :345-351) invokes at
  most the interview they could invoke by typing `advanced`.
- **Dormant by construction:** default False in dataclass AND parse AND
  property AND both new function keywords; the OFF state is the untouched
  existing code path (§3.1), not a restoring branch. The strongest available
  form short of structural absence, and the same form both shipped sub-flags
  use.
- **Every control tested off:** §5's toggle locks prove flag-off
  byte-identity at each seam (parser, questions, schema bytes, planning,
  record) and prove the probes FAIL when the flag is on (the token parses,
  the axes widen) — so "off" is distinguishable from "unreachable".
- **Failure leaks nothing new:** the park/log posture is inherited — session
  ids in logs, never goal text (:497-524); the #1116 keep-operator-text
  guarantee applies to every new nag path because they reuse
  `_keep_operator_text`.

## 5. Build plan (slices, dependencies, tests) — for the building session

Ordered by dependency; each slice is one atomic ship with its locks. All are
GPU-free (injected `generate_fn`/fakes — the established pattern). None
touches the battery instrument. NOTE for the builder: S3-F AND S3-G (both in
flight tonight) also touch `generate_plan`'s signature, the entrypoint call
site, the coordinator, and default.toml — coordinate merge ORDER at merge
time (all touch points are additive keywords/blocks; no semantic collision;
review F8).

| # | slice | builds | tests (locks) |
|---|---|---|---|
| S2a | clarify.py vocabulary + seam helpers | 3 axis constants, `INTAKE_AXES`, `INTAKE_MAX_QUESTIONS=8`, 3 default answers, `_INTAKE_TEMPLATE` + a `template: str = _CLARIFY_TEMPLATE` parameter on `generate_clarifying_questions` (the function hardcodes the template today, :244 — review F7), `axes=` parameterization of the four functions, `record_axes=` on the two producers, `INTAKE_SENTINEL` + `compose_intake_goal`/`split_intake_goal` | **axis-default lock** — each new axis self-answers to its recorded assumption; **cap lock** — 8-axis emission of 20 questions rules to ≤8, one per axis; **toggle lock** — default-args calls are byte-identical to today on the same fake emissions (questions, schema bytes, parse results); sentinel helpers pure+total round-trip |
| S2b | AO-side engagement | `generate_plan(interview=False)` + marker detect/strip + extended clarify call passing `axes=INTAKE_AXES`, `max_questions=INTAKE_MAX_QUESTIONS`, `template=_INTAKE_TEMPLATE` explicitly (the existing `max_questions` parameter, default 5 at :3786, is the carrier — no new plumbing, review F7); entrypoint dataclass field + `is True` parse + property + call-site kwarg; default.toml block (house style) | **card-suppression lock** — `decomposition_override` + marker + all flags on ⇒ zero questions; **marker-hygiene lock** — engaged marker never reaches `spec.goal`/`planning_seed`/any compiled prompt; **toggle lock** — `interview=False` (or front off) with a marker-carrying goal is byte-identical planning incl. the marker riding as inert text; config-parse lock — `"true"`/1/garbage resolve False |
| S2c | gateway front | parser `intake_token=` + token grammar + `DispatchCommand.advanced`; coordinator ctor flag + sentinel append (marker-then-requirements order) + `PendingRequirements.intake` + codec + axes selection at answer/decide + the `record_axes=True` call sites at those SAME two functions (S2d's producer half — review F4) + hint line + no-questions note; launcher + transport threading | **parse lock** — token recognized only with `intake_token=True` and only on run/create; `advanced approve` nags, fires nothing; **park round-trip lock** — `intake=True` survives payload → restore, pre-S2 rows restore False; **hint lock** — hint only when flag on AND ≥40 words, absent otherwise; **toggle lock** — flag off ⇒ parser, renders, and coordinator replies byte-identical |
| S2d | transcript | `_coerce_clarifications` conditional `axes` carry (the producing call sites live in S2c — review F4) | **transcript round-trip lock** — intake dicts keep `axes` through to_dict → from_dict → `write_acceptance_record` → `read_acceptance_record`, INCLUDING the project-memory banked-answer path (review F6); quick dicts gain NOTHING (byte-identical record flag-off); malformed axes values dropped fail-closed |

S2a has no dependencies; S2b and S2c depend on S2a and are mutually
independent; S2d depends on S2a AND S2c (its producer half lives in S2c's
functions — review F4). The merged whole re-runs the standing gate plus the full
toggle-off suite as one motion; the slice merges DORMANT and the ceremony
runbook (`docs/runbooks/advanced_intake_interview_go_live.md`, written in
S2b's motion beside its two sibling runbooks) is the go-live artifact.

## 6. The single operator decision (everything else here is mine)

**What should `/dispatch advanced` do on a project that already has
remembered answers?** Project memory (#1120/#1124 — dormant today, its
go-live yours) suppresses ALL clarifying questions once a project has any
banked answer: the remembered block rides the first plan call
(dispatch_coordinator.py:840-845), `requirements` arrives non-empty, and the
clarify stage self-suppresses (acceptance.py:3901). That reach extends to
this interview: on a remembered project, `advanced` would ask NOTHING — the
operator explicitly requests a fuller interview and gets zero questions.

- **My recommendation for this slice: defer to memory, say so honestly.**
  The card already shows remembered answers under their own heading; S2 adds
  one notice line on the `advanced` path: *"Using what you've told me about
  this project — `/dispatch forget <project>` first if you want the full
  interview fresh."* This preserves both ceremonied features' current
  semantics, costs one line, and leaves a working escape hatch.
- **The alternative: `advanced` overrides the suppression** — the interview
  runs anyway and fresh answers supersede banked ones (the #1120 merge rule
  already gives fresh-wins). More powerful, but it changes what a
  privacy-posture feature you ratified DOES with what you told it, on a
  keyword — that interaction is yours to weigh, not mine to default in.

This is the decision to settle at (or before) the interview's go-live
ceremony. It is the only decision in this design that is yours; note that
because memory is itself dormant, nothing about it blocks the build.

*(Two §6 candidates were examined and rejected as manufactured: the
one-screenful bound is a technical call made structural by the axis-dedupe
cap, and "should the interview exist dormant" is the standing default arc,
not a question.)*

## 7. Grounding reads for the building session (≤8, in order, anchors verified 2026-07-28 (local PDT) at 8c386771)

1. `shared/fleet/clarify.py` — WHOLE file (458 lines): axes :51-81, template
   :99-115, schema :121-141, parse/ruler :185-221, generator :224-255,
   decide phrases :266-288, reconstruction :291-322, free-text answer
   :325-339, sentinel seam :345-437.
2. `services/ui_gateway/src/dispatch_coordinator.py:346-419` (parser),
   `:734-794` (routing incl. the requirements corridor), `:798-872` (_plan:
   remembered-thread :840-845, question park :852-865), `:876-949`
   (answer/decide/replan + the #1152 park-until-success contract),
   `:211-233` + `:248-260` (hold state + codec), `:951-965` + `:1091-1137`
   (renders + `clarified_note` seam).
3. `shared/fleet/acceptance.py:3772-3793` (generate_plan signature — the
   flag-keyword pattern), `:3878` (revise-sentinel precedent), `:3895-3924`
   (clarify stage, its gate predicate, planning_seed).
4. `services/assistant_orchestrator/src/entrypoint.py:619-684` (the three
   dataclass fields), `:1200-1257` (properties incl. the
   conjunction-lives-at-generate_plan rationale), `:2232-2254` (`is True`
   parse), `:3254-3333` (_handle_plan_request: goal split :3279, call site).
5. `services/assistant_orchestrator/config/default.toml:444-610` — the three
   worked flag blocks whose register the new block copies.
6. `shared/fleet/acceptance.py:380-465` (AcceptanceSpec; clarifications
   field + to_dict/from_dict), `:1152-1178` (`_coerce_clarifications`
   whitelist + the #1120 carry precedent), `:482-504` (PlanResult.questions).
7. `shared/fleet/dispatch.py:511-530` (acceptance record write/read) +
   `dispatch_coordinator.py:1266-1274` (the call in `_approve`).
8. `launcher/__main__.py:2076-2091` + `services/ui_gateway/src/transport.py:
   344-359, 534-548, 1577-1585` — the no-second-TOML-parse flag threading
   chain and the parse call site.
