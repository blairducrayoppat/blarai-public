---
title: "Advanced Intake S3 — criteria & exam authoring redesign"
status: DESIGN (draft-first per LA #1069) — not built; the plain-language read is §0
area: design
date: 2026-07-23
ticket: "#1069 (umbrella); retires #1043, #1044, #1054, #1055"
supersedes_scope_of: "the four member tickets as standalone patches (LA decision 2026-07-23)"
grounded_at: "main b5633482; source read at that commit"
---

# Advanced Intake S3 — how acceptance criteria and exams get authored

## 0. Plain-language read (for the Lead Architect)

You decided to build S3 as one coherent slice rather than patching four bugs one
at a time. This document is why that was the right call and what the one design
is — a read for you to react to, not a thing being built yet.

**The four bugs are one bug wearing four hats.** Today the system writes a job's
acceptance criteria and its exam in a handful of separate, uncoordinated passes:
one pass invents the criteria, a different pass writes the assumptions, a third
writes the exam. Nothing checks that these passes agree with each other, that
they cover the whole job, that they test bad input, or that you can correct them
after the fact. Each of the four tickets is one consequence of that same missing
coordination:

- **#1054** — the assumptions pass decided "no reset button needed" while the
  criteria pass made a reset button a graded requirement. The plan literally
  contradicted itself, because the two passes never saw each other's output.
- **#1044** — an exam certified a flashcards build GREEN while asserting nothing
  about bad input; the shipped code crashed on two ordinary inputs and every
  automated grader passed it. GREEN meant "the happy path works," and every
  capability number built on GREEN inherits that caveat.
- **#1043** — the checker that decides whether the exam "invented" a requirement
  reads from the *clean* goal, while the exam is now written from the *enriched*
  goal that carries your answers. So the exam can be convicted for asserting
  exactly the thing you asked for. (This is the small residue of a bigger fix you
  already have — #1032 closed the main channel; this is the one grounding blob it
  didn't reach.)
- **#1055** — when you tried to fix an over-scoped plan by revising it, the tool
  silently couldn't: revise edits the task list, never the criteria, and its
  error message invited you to rephrase — a loop that could never succeed.

**What "structurally retired" means for each.** Not "add a rule that usually
catches it" — a design where the defect cannot be expressed:

- Coherence is retired by making the assumptions and criteria a *single*
  authoring act that cannot disagree with itself, with a deterministic
  contradiction gate behind it.
- The bad-input gap is retired by a deterministic requirement — a web/CLI job's
  exam must assert at least one malformed input per public entry point, injected
  by machinery, not hoped for from the model.
- The clean-vs-enriched mismatch is retired by grounding the checker on the same
  text the exam was authored from — one source, not two.
- The revise dead-end is retired in two moves: an honest failure message now (a
  small, standalone fix), and a real criteria-revise path as part of the slice.

**What this cannot do**, so the expectations are honest: it does not raise the
coder's per-task ceiling, it does not make aesthetics machine-checkable, and it
does not decide anything about egress, privacy, or capability — those stay
yours. It ships **dormant behind a config flag** and goes live only at a ceremony
you run, exactly like S1 did.

**The one thing I want your eye on** is at the end, §6: whether the
coverage-by-construction gate should be able to *block* an approval inside
advanced-intake mode. That is a capability call — it changes what a dispatch can
refuse — and it is yours, not mine. The rest is technical and I own it.

---

## 1. Scope and the naming reconciliation (read this before the slice map)

There is a numbering collision in the record that will confuse a successor if it
is not stated plainly:

- The **2026-07-21 design sketch**
  (`docs/research/coder-capability-2026-07/advanced-intake-design-sketch-2026-07-21.md`)
  numbers *build* slices S1–S4, where its **S1** = delivery-floor + realism
  guard, **S2** = elicitation interview, **S3** = coverage-by-construction,
  **S4** = spec→exam channel hardening.
- The **shipped #1031 "S1"** (`advanced_intake=true`, `72c0990c`) is the design
  sketch's build-slice S1.
- The **LA's "S3"** (#1069) is not the design sketch's narrow S3. It is the
  **criteria & exam authoring redesign** — the coherent program slice that
  retires #1043/#1044/#1054/#1055 — and it spans the design sketch's Stage 2
  (co-authoring), Stage 3 (coverage), and S4 (channel). The elicitation
  interview (design-sketch S2) is a **separate** future slice and is **out of
  scope here**.

This document owns the authoring redesign. Where it reuses a design-sketch build
slice it says so; it does not renumber anything already on the board.

**In scope:** the authoring of criteria, assumptions, and exams inside
`generate_plan`, and the operator's ability to correct criteria. Structurally
retiring #1043, #1044, #1054, #1055.

**Out of scope:** the elicitation interview (its own slice); the coder's
per-task capability; anything touching egress, the coordinator write path, or the
self-governance boundary (none of this slice goes near them — §4). **#1066 does
NOT join this corpus** — its 2026-07-23 forensics (c.2446) put its causes in the
build/repair machinery (a leaked worktree file, a swallowed commit step, a dedup
guard), not in authoring. Its conditional membership is now resolved: NO.

## 2. The single root cause, in source

`generate_plan` (`shared/fleet/acceptance.py:3100`) runs the authoring passes as
independent 14B calls with no cross-pass consistency and two different text
sources feeding two different consumers:

- criteria from `_CRITERIA_TEMPLATE` (`acceptance.py:530`, formatted at `:3249`)
  over the enriched `planning_seed`;
- assumptions from `_ASSUMPTIONS_TEMPLATE` (`:562`, formatted at `:3285`) over
  the same seed but in a **separate call that never sees the criteria** — the
  #1054 contradiction is born here;
- the invented-contract scanner's grounding corpus built from the **clean**
  `spec.goal` (`_spec_corpus`, `oracle_qa.py:499-508`) while the oracle is now
  authored from the **enriched** seed — the #1043 asymmetry. *(Verified on
  current source, and it corrects a stale premise inherited from the 2026-07-21
  design sketch: the sketch said the multi-task job-oracle itself receives the
  clean goal. #1032 CLOSED that — `author_and_qa_job_oracle(planning_seed, …)`
  at `acceptance.py:3444`, with the comment at `:3436-3439` citing #1032. So the
  exam channel is already fixed; #1043 is its narrow downstream residual, in the
  QA scanner's corpus only. This is why reading source beat inheriting the
  sketch — a whole slice was already done.)*;
- no authoring rule requires a negative-path assertion anywhere — the #1044 gap;
- `render_criteria_preview` (`:2079`) then shows criteria the operator can only
  accept, reject, or revise-the-tasks-not-the-criteria (`dispatch_coordinator.py`
  revise path) — the #1055 dead-end.

One missing property — *the authoring passes are not a coordinated whole* —
expressed four ways.

## 3. The design — four structural retirements on one authoring spine

Everything below gates on `generate_plan(advanced_intake=...)`, the single gate
point the shipped stages already use. **Flag off ⇒ byte-identical planning** —
the standing toggle-off bar. This slice merges dormant; go-live is an LA ceremony
(`advanced_intake` is already a live flag, so this rides its existing runbook —
but a NEW capability inside it, the blocking gate of §3.3, is the ceremony's
subject, §6).

### 3.1 Coherence by single authorship — retires #1054

**Retirement:** the assumptions and criteria stop being two passes that can
disagree. In intake mode they are authored in **one pass** whose prompt carries
both jobs, so the model cannot decide "reset is out of scope" in one place and
"reset is required" in another — the two live in one generated document with one
context. Behind that, a **deterministic coherence gate** parses the produced
(assumption, criteria) set and refuses a plan where a criterion requires a
capability an assumption explicitly excluded (or the reverse). The gate is the
structural half: even if a future model regresses, a self-contradicting plan
cannot pass. Scope-anchoring rides the same prompt — criteria must assert only
behaviours the goal (+ clarified requirements) names, retiring #1054's
scope-creep defect (the goal-only features the model invented).

**Why a gate and not just a better prompt:** a prompt is vigilance; the gate is
the deny-by-default control. Both ship, prompt for quality, gate for the
guarantee.

### 3.2 Bad-input coverage as a deterministic floor — retires #1044

**Retirement:** the exam-authoring path gains a machine-injected requirement,
the same shape as the existing never-zero-tests floor (`_ensure_test_floor`,
called at `acceptance.py:3073`) and the S1 delivery floor: for every public
entry point the oracle imports, the exam MUST carry at least one machine-gated
assertion over a malformed/edge input (empty, None, wrong-type, missing-key).
Injected deterministically when the model omitted it, not requested and hoped
for. The rubric already NAMES `bad_input_handling` as a quality dimension; this
makes the exam actually test the property the jury is asked to score.

**The honest limit, named at design time:** this asserts that *a* bad-input
check exists, not that it is the *right* one — a model can satisfy the floor with
a shallow check. That is acceptable as the structural floor; the stronger form
(a deterministic fuzz probe over each declared entry point, model-free) is
recorded as a **follow-on**, not folded in, because it is a new grading layer and
a new grading layer is a capability question. Flagged for the LA in §6.

### 3.3 Coverage by construction + a blocking pre-render gate — the S4/Stage-3 spine

**Retirement of the clean-vs-enriched mismatch (#1043):** `_spec_corpus`
(`oracle_qa.py:499`) — the grounding blob the invented-contract scanner reads —
is grounded on the **same text the oracle was authored from**. The measured
isolating control on #1043 shows the finding is produced *solely* by the
corpus/author asymmetry, so aligning the source retires it with zero effect on a
genuinely-bad oracle. The cleanest form uses `spec.clarifications`, a field the
spec already carries (`AcceptanceSpec`, #819), so no new parameter threads
through the QA gate.

**The S4 channel is already closed — do not rebuild it.** The 2026-07-21 design
sketch listed "thread the enriched seed into the multi-task job-oracle author" as
an unbuilt slice. On current source that shipped as **#1032**: the job-oracle
author receives `planning_seed`, not the clean goal (`acceptance.py:3444`). So the
only residual is the QA-scanner corpus alignment above (#1043). What was two
halves of one defect in the sketch is now one half, already fixed, and one half
remaining. Slice C in §5 is therefore **already done** and struck.

**Coverage by construction (design-sketch S3):** in intake mode the module map is
derived FROM the floored criteria and the import contract emitted 1:1 with build
tasks, so the #989 predictor (contract coverage → build quality) becomes a design
rule. The existing coverage check (`context_pack.contract_coverage:708`, surfaced
`acceptance.py:2852`) then runs as a pre-render gate: a gap triggers ONE bounded
re-synthesis; still gapped ⇒ the card renders BLOCKED — approve refused with the
gap named, revise and reject still open. **This blocking behaviour is the one
capability change and is §6's ceremony subject.** The quick path stays warn-loud;
retrofitting a block there is the silent capability change the check's own
docstring (`:2862-2866`) forbids.

### 3.4 Criteria-revise + an honest failure message — retires #1055

**Two moves, deliberately split by cost:**

1. **Now, standalone, no flag (ship ahead of the slice):** when
   `/dispatch revise` yields no task ops, detect whether the feedback referenced
   criteria/scope vocabulary and, if so, tell the operator plainly that criteria
   are set by the goal and the way to change them is reject + re-dispatch — or,
   once (2) lands, criteria-revise. This turns a dead-end loop into a correct next
   step and is a pure message fix. **This is the cheapest retirement on the board
   and I recommend it lands first, independent of everything else here.**
2. **In the slice:** a criteria-revise capability — keep/drop/re-scope ops over
   the CRITERIA, mirroring #820's task-revise, bounded like it (3 revisions). The
   **safety asymmetry is preserved and re-examined at design time**: today the
   acceptance-tests task is never offered for editing so a revision cannot weaken
   the machine gate (`dispatch_coordinator.py`). Criteria-revise MUST keep that
   invariant — an operator may narrow scope or fix a wrong criterion, but may not
   delete the delivery floor or the bad-input floor. The floors are re-injected
   after any criteria revision, so a revise cannot strip them (§3.2/S1 floors are
   deterministic and idempotent — re-running the ruler restores them).

## 4. Security by design — named at design time (doctrine requirement)

**Trust boundary touched:** the operator-facing dispatch front, inside the
existing 14B-resident PLAN window. **What can reach it:** the operator, through
the existing `/dispatch` verbs. **What it can reach:** the plan/spec objects and
the acceptance record store — nothing else.

- **No new egress.** Nothing here opens a network door; the plan window is local
  and this slice adds no client. (If any sub-step appeared to need one, that is a
  decision_boundary escalation, not a design choice — none does.)
- **No coordinator write path, self-governance boundary untouched.** This is
  operator-initiated authoring; the coordinator's advisory-only severance
  (ADR-039) is not in the path.
- **Fail-closed / deny-by-default.** The coherence gate, the coverage gate, and
  the bad-input floor all default to *refuse/inject*, never to *pass hopefully*.
  A gate that cannot verify its precondition blocks the plan; it never renders a
  plan it could not check as if it were checked.
- **The one privilege-shaped invariant** is the revise safety asymmetry (§3.4):
  criteria-revise must not become a path to weaken a machine gate. Designed in as
  a re-injection-after-revise rule + a lock that a revised criteria set still
  carries every deterministic floor, not bolted on after.
- **Dormant by construction.** Flag defaults `false`; the blocking gate has no
  code path to fire until the flag is flipped at a ceremony. Structural absence,
  not just a disabled boolean.
- **Every control tested off:** each gate ships a test proving it BLOCKS when
  engaged and a toggle-off proving the plan is byte-identical (or the probe goes
  RED) when the flag is off.

## 5. Build plan (slices, dependencies, tests) — for the building session

Ordered by dependency and by cost-to-value. Each is one atomic ship with its
regression lock; battery-instrument-touching limbs take their own attribution
window (none here touches the battery instrument — this is spec-side).

| # | slice | retires | touches | depends on |
|---|---|---|---|---|
| A | honest revise-failure message | #1055 (1) | `dispatch_coordinator.py` revise path | nothing — **ship first, no flag** |
| B | `_spec_corpus` corpus/author alignment | #1043 | `oracle_qa.py:499-508`, its call site | nothing — **GPU-free, no flag, small** |
| ~~C~~ | ~~spec→exam seed channel~~ | ~~#1043/S4~~ | **ALREADY DONE — #1032, `acceptance.py:3444`** | — |
| D | bad-input floor | #1044 | `acceptance.py` criteria ruler + a floor helper by `_ensure_test_floor` (`:1414`) | flag-gated |
| E | coherence gate + single-pass authoring + scope anchor | #1054 | `acceptance.py` `_CRITERIA_TEMPLATE` (`:530`) / `_ASSUMPTIONS_TEMPLATE` (`:562`) + a deterministic gate | flag-gated |
| F | coverage-by-construction + blocking pre-render gate | S3 spine | `acceptance.py` synthesis step + `contract_coverage` (`context_pack.py:708`), `dispatch_coordinator.py` approve refusal | D (floored criteria are the input); **§6 ceremony** |
| G | criteria-revise capability | #1055 (2) | a revise sibling over criteria + floor re-injection | D, E (floors + coherence must exist to preserve) |

**A and B can land immediately** — defect fixes, no capability change, no flag.
That retires #1043 and the loop half of #1055 before the flag work begins, and
is the highest value-per-line on the board. **C is already shipped (#1032).**
**D, E, F, G are the flag-gated authoring redesign**, merged dormant.

**Toggle-off bar, every flag-gated slice:** drive `generate_plan` with injected
`generate_fn` fakes (the GPU-free pattern), `advanced_intake=False`, assert
byte-identical specs on the same inputs. **Blocking bar, F:** a gapped plan in
intake mode cannot be approved and the refusal names the gap; one re-synthesis,
never a loop.

## 6. The single operator decision (everything else is mine)

**Should the coverage gate (F) be able to BLOCK an approval inside
advanced-intake mode?** Today the #989 coverage check is warn-loud everywhere,
for a documented reason: refusing a plan "would silently change what a dispatch
can do" (`acceptance.py:2862-2866`). Making it blocking *inside intake mode* is
the capability call being made properly — a new refusal, scoped to a mode whose
go-live is your ceremony. That is the thing to ratify (or decline in favour of
warn-loud-everywhere) at the ceremony, and it is the only decision in this design
that is yours rather than mine.

One smaller thing I am flagging, not asking:
- The bad-input **fuzz probe** (§3.2 stronger form) is a new grading layer and
  therefore a future capability decision — recorded as a follow-on, not folded in.

*(An earlier draft of this section asked about slice C's seed-threading. That
was written from the stale premise; #1032 already shipped it. Removed rather than
left as a phantom question.)*

## 7. Grounding reads for the building session (≤8, in order)

1. `shared/fleet/acceptance.py:3100-3253` — `generate_plan`, the authoring
   sequence and its stage-gate pattern.
2. `shared/fleet/acceptance.py:530-600` — `_CRITERIA_TEMPLATE` +
   `_ASSUMPTIONS_TEMPLATE`, the two passes that must become one.
3. `shared/fleet/oracle_qa.py:499-550` — `_spec_corpus` +
   `scan_invented_return_contracts` (#1043's mechanism).
4. `shared/fleet/acceptance.py:3386` (single-task oracle) + `:3444`
   (`author_and_qa_job_oracle`, fed `planning_seed` since #1032) — confirm the
   channel is closed before touching anything here; #1043 lives in `oracle_qa.py`,
   not in this split.
5. `shared/fleet/context_pack.py:702-779` + `acceptance.py:2852-2902` — the
   coverage check and its warn-loud rationale (F's substrate + the boundary).
6. `services/ui_gateway/src/dispatch_coordinator.py` revise path — what revise
   can and cannot touch (#1055's mechanism + the safety asymmetry).
7. `docs/research/coder-capability-2026-07/advanced-intake-design-sketch-2026-07-21.md`
   §5 — the flag-wiring chain and the design-sketch slice definitions.
8. The four member tickets' DESCRIPTIONS (#1043/#1044/#1054/#1055) — the measured
   evidence and the fix directions their finders recorded.

Each member ticket closes citing the S3 commit that structurally retires its
class — not before.
