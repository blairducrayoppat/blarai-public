---
title: "Advanced Intake — design sketch"
status: matured for LA review — source-grounded at efb7f17e, future-agent-ready build appendix in §5 (build is a capability decision, not started)
area: research
date: 2026-07-21
author: evening-watch session, LA-directed
companion: coder-capability-assessment-2026-07-21.md
---

# Advanced Intake — AI-assisted specification front for dispatch jobs

**Plain summary:** a design sketch for the "advanced setup" the LA proposed on
2026-07-21: instead of one-shotting a build from a short prompt, an assisted
intake interviews the operator, co-authors a complete specification with
machine-pinned acceptance criteria, and only then decomposes and builds. The
measured record says specification quality is the single strongest predictor
of build quality this system has — stronger than anything about the coder
itself.

## 1. Why this is the highest-leverage build (evidence, not opinion)

- **Contract quality decided seven nights of B4.** One module missing from the
  exam's import contract produced seven consecutive parked nights and a
  worsening wave-1 sprawl (44.2% median share). Repairing the contract (#1008)
  removed the defect's expression *before* the #989 code fix ran (measured
  today: run-1 wave-1 authored exactly its contract, 16.5% vs 20% even split).
- **The predictor generalizes across all 8 cards** (#989 c.2299): 1:1
  contract coverage → clean builds (B2, B7, early-B6); contract gaps → sprawl
  (B4, B5, late-B6). Not language, not size, not task count.
- **Under-specification leaks placeholder junk.** Blair's Lab shipped invented
  placeholder projects and a generic About because the clarify stage asked
  nothing about content (ledger 07-15, operator-experience row).
- **Checks must ride the original ask.** The revise wall structurally cannot
  add machine-gated checks (safety asymmetry, by design — #877 c.2332;
  verified in source: revision edits FEATURE tasks only, the acceptance-tests
  task is never offered for editing, and the spec's criteria are immutable
  across a revision — `dispatch_coordinator.py:829-870`). The intake is
  therefore the *only* place a complete check set can be born.
- **A human reading the spec catches what machinery misses.** The LA's
  dimension-4 grade on the Bill Splitter front surfaced the
  result-reaches-the-page seam before the build started.

## 2. What exists today (the skeleton to evolve, not replace)

*(Corrected 2026-07-21 evening against source at commit `efb7f17e` — the
original paragraph here was written from ticket narratives and understated the
existing skeleton. The intake is an EXTENSION of stages that already run, not
a new front.)*

The live `/dispatch` pipeline, in source order:

1. **Parse** — `parse_dispatch_command`
   (`services/ui_gateway/src/dispatch_coordinator.py:161-219`): the verb set
   is run / new / approve / reject / revise / stop / status plus the
   clarification-answer forms (answer, "just decide for me", a bare option
   number).
2. **Requirements clarify (#819, LIVE — `[fleet_dispatch].clarify = true`)** —
   `shared/fleet/clarify.py`: the 14-billion-parameter orchestrator ("the
   14B") proposes a FEW plain-language questions over five fixed decision
   axes (surface, persistence, must-work feature, look, size;
   `clarify.py:51-62`); a sufficient goal is asked nothing; "just decide for
   me" self-answers with recorded defaults. The answers become an enriched
   requirements block that rides the goal into planning
   (`compose_planning_goal`, `clarify.py:374-381`).
3. **Plan** — `generate_plan` (`shared/fleet/acceptance.py:2904-3253`), one
   14B-resident sequence: decompose (`shared/fleet/decompose.py` — the model
   proposes, a deterministic right-sizing ruler disposes) → acceptance
   criteria, ALREADY typed at birth into five tiers (build / behavior /
   smoke = machine-gated; visual / human = operator-judged;
   `acceptance.py:58-71`) → product assumptions → platform build-signal →
   acceptance-oracle authoring (single-task at `:3154-3157`, multi-task job
   oracle at `:3204-3208`) → the #989 plan-time contract-coverage check,
   warn-loud (`:3210-3222`) → `compile_prompts`.
4. **Platform fork (increment 4)** — one curated question when the surface is
   genuinely ambiguous (`resolve_clarifying_question`, `acceptance.py:276`;
   `PendingClarification`, `dispatch_coordinator.py:104-133`).
5. **Card** — `render_criteria_preview` (`acceptance.py:2079-2207`): goal,
   platform line, build plan, assumptions, clarification record, automatic
   checks vs check-yourself checks, ecosystem-honesty disclosure, the
   approve / reject / revise footer. The LA grades the six quality-ledger
   dimensions aloud against this card.
6. **Approve → build** — the spec is persisted run-id-keyed BEFORE firing
   (`write_acceptance_record`, `dispatch_coordinator.py:772-779`), then the
   swap driver composes each task's production prompt: oracle notice + exact
   import contract + the #989 scope ceiling + context pack
   (`shared/fleet/swap_driver.py:1970-2029`, `_scope_ceiling` at
   `:2031-2086`).
7. **Revise (#820, LIVE — `[fleet_dispatch].revise = true`)** — free-text
   feedback on a pending card produces edit operations over the FEATURE tasks
   only; the acceptance-tests task is never offered for editing and the
   spec's criteria are untouched by revision
   (`dispatch_coordinator.py:829-870`) — so a revision can narrow scope but
   structurally cannot add or remove machine-gated checks. Bounded at 3
   revisions (`shared/fleet/revise.py:52`). The 2026-07-21 live defect (a
   revised task minting a bare repo name the forbidden-root guard then
   refused) is fixed at `dispatch_coordinator.py:847-853` (merge `9c972dcc`).

Proven wins: 1-task grain on the Bill Splitter re-front (best card on
record); the clarification→exam channel verified live on 2026-07-21 — **on
the single-task oracle shape**, where the enriched goal reaches the exam
author (`acceptance.py:3155-3156`). On the multi-task shape the job-oracle
author receives the CLEAN goal, not the enriched one (`:3204-3208`,
`:2736-2741`) — the channel is partial there today; see §5 S4.

## 3. The design: a staged intake, mode-selected

**Stage 0 — mode select.** Trivial asks keep the quick one-shot path
(unchanged). `"advanced"` (or size/ambiguity heuristics) enters the staged
intake. Nothing below removes the fast path.

**Stage 1 — elicitation interview (14B-driven, operator answers in plain
language).** Purpose and audience; delivery target (CLI / web page / service)
— which selects the *scaffold profile* explicitly instead of inferring it (the
#886 scaffold-fit lesson); content inventory (real content vs. deliberate
placeholder — never invented silently); the awkward cases in the operator's
own words; explicit non-goals (scope fence). The interview is bounded (one
screenful of questions, skippable) — an interrogation would kill the tool.

**Stage 2 — acceptance-criteria co-authoring.** *(Corrected against source:
criterion typing is NOT new — every criterion is already typed at birth into
the five-tier taxonomy at `acceptance.py:58-71`: build/behavior/smoke are the
machine-gated tiers, visual/human the operator-judged tiers, and the card
already renders them as "Automatic checks" vs "You check these yourself"
(`:2159-2167`). The intake does not mint a new type system.)* What Stage 2
adds is the CO-AUTHORING loop and two authoring rules on top of the existing
tiers:
- **Delivery floor authored in.** For web targets the spec MUST carry a
  machine-gated criterion asserting delivery ("the served page boots and
  shows X" — the #1025 class, promoted from post-hoc floor to authored
  criterion), injected deterministically by the ruler when absent — the same
  pattern as the existing never-zero-tests floor (`_ensure_test_floor`,
  called at `acceptance.py:3073-3076`).
- **Realism guard.** A criterion claiming a machine-gated tier whose check
  cannot name a mechanically runnable verification is DEMOTED to the
  operator-judged tiers, never dressed up with a manufactured check (the
  check-realism defect class, ledger dimension 2). Honestly subjective asks
  ("feels premium") stay judge-yourself by design.

**Stage 3 — contract synthesis with coverage by construction.** The module
map is derived from the criteria, and the exam's import contract is emitted
**1:1 with build tasks by construction** — the #989 predictor becomes a
design rule instead of a hoped-for property. The #989 plan-time
contract-coverage check (`context_pack.contract_coverage`,
`shared/fleet/context_pack.py:708-779`, surfaced by
`_plan_contract_coverage_warning`, `acceptance.py:2852-2902`) then runs as a
pre-render gate. *(Corrected against source: the check is warn-loud today for
a DOCUMENTED reason, not as a stopgap — its docstring at
`acceptance.py:2862-2866` says refusing a plan "would silently change what a
dispatch can do, which is a capability call this layer must not make." The
intake may make it blocking ONLY inside its own mode, whose go-live is itself
an LA ceremony — that is the capability call being made properly. The quick
path stays warn-loud; retrofitting a block there is exactly the silent
capability change the docstring forbids.)* Blocking shape, fail-closed but
never a dead-end: a coverage gap triggers ONE bounded re-synthesis; if still
gapped, the card renders in a blocked state — approve refused with the gap
named, revise and reject still available.

**Stage 4 — plan card + grading (existing machinery, unchanged).** The six
quality-ledger dimensions (decomposition grain, check realism, scope
fidelity, honesty lines, assumption quality, acceptance-criteria pinning —
`docs/quality/dispatch-quality-ledger.md:31-50`), the revise wall's
asymmetry, approve → build. *(Corrected against source: no new `spec.json`
is needed — a run-id-keyed acceptance record is ALREADY persisted before
firing (`write_acceptance_record`, `dispatch_coordinator.py:772-779`), and
`AcceptanceSpec.to_dict` already carries criteria, assumptions, build-signal,
and the clarification record (`acceptance.py:426-434`). The intake EXTENDS
that record, never a parallel file.)* The exam is authored FROM the spec —
which requires closing the partial channel named in §2: today only the
single-task oracle sees the enriched goal; the multi-task job-oracle author
receives the clean goal (`acceptance.py:3204-3208`). §5 S4 closes it.

## 4. What it should buy (expected, hedged) and what it cannot

Expected, from the evidence: complex-Python first-run pass rate up (spec-gap
parks removed); web apps crossing from "logic built" to "delivered" (the
delivery floor authored in); placeholder surprises gone; less GPU burned on
ambiguous tasks (empty first attempts correlate with under-specified asks);
every run's exam trustworthy by construction.

It cannot: raise the 30B coder's per-task ceiling (tasks stay bounded and
machine-verifiable); make aesthetics machine-checkable (judged stays judged);
substitute for the operator on egress/privacy/capability decisions.

## 5. Build shape — future-agent-ready appendix (when/if the LA green-lights)

*(Matured 2026-07-21 evening from source read at commit `efb7f17e`. A build
agent should be able to implement each slice from this section plus the
grounding reads in §5.6 without re-deriving the front path.)*

BlarAI-side, on the existing dispatch front path — no new egress, no
coordinator write path, self-governance boundary untouched. Everything runs
in the existing 14B-resident PLAN window; no new model, no new process, no
new IPC (inter-process communication) verb (both prior stages proved the
goal-string sentinel pattern instead — `clarify.py:351`, `revise.py:83`).
Nature: a capability addition to the operator-facing front → **merges dormant
behind a config flag; go-live is an LA ceremony** per standing doctrine.

### 5.1 The dormant flag (one flag, house style)

Key: `[fleet_dispatch].advanced_intake = false` in
`services/assistant_orchestrator/config/default.toml` — a sibling of the
existing stage flags `clarify` (`default.toml:363`) and `revise` (`:374`),
with the same comment register (ticket number first, plain-language behavior,
what `false` preserves). Dormant default is `false`, unlike those two
(proven-features-default-LIVE applied to them only after their go-lives).

Wiring, copying the proven `clarify`/`revise` chain in
`services/assistant_orchestrator/src/entrypoint.py` exactly:
- config dataclass field `fleet_dispatch_advanced_intake_enabled: bool =
  False` (sibling of `:592` / `:601` — note those default `True`; this one
  MUST default `False` in BOTH the dataclass and the parse);
- parse `bool(fleet_dispatch.get("advanced_intake", False))` (sibling of
  `:2007-2008`);
- resolved property (sibling of `:1047-1072`);
- threaded into `generate_plan(advanced_intake=...)` at the plan-handler call
  (sibling of `:3051-3056`).

`generate_plan` gains one keyword `advanced_intake: bool = False`; every
intake behavior below checks it there (one gate point, mirroring how
`clarify`/`revise` gate their stages inside `generate_plan` at
`acceptance.py:2970-3011`). Flag off ⇒ byte-identical planning — the standing
toggle-off bar for every slice.

### 5.2 Slice S1 — delivery-floor authoring + realism guard (spec-side substrate)

- **Touches:** `shared/fleet/acceptance.py` only — the criteria ruler
  (`rule_spec`) and a new deterministic floor helper beside
  `_ensure_test_floor` (caller at `:3073-3076`); the criteria prompt
  `_CRITERIA_TEMPLATE` gains the delivery-floor and realism instructions
  (model proposes); the ruler enforces (ruler disposes).
- **Contract added:** (1) a spec whose `build_plan.surface` resolves web /
  web-static carries ≥1 machine-gated criterion asserting the served page
  boots and shows a named output — injected when the model omitted it;
  (2) a criterion claiming tier build/behavior/smoke whose `check` field
  names no mechanically runnable verification is demoted to `human`, never
  auto-passed and never given a manufactured check.
- **Tests:** regression lock — web-target spec without a floor criterion gets
  exactly one injected (assert tier + text shape); demotion lock — a
  fake-objective criterion lands in `spec.human`. Toggle-off proof —
  `advanced_intake=False` yields byte-identical specs on the same inputs
  (drive `generate_plan` with injected `generate_fn` fakes, the established
  GPU-free pattern).
- **Depends on:** nothing. Build first — S3 and S4 consume typed, floored
  criteria.

### 5.3 Slice S2 — elicitation interview (front-side)

- **Touches:** `shared/fleet/clarify.py` — extend the axis vocabulary
  (`CLARIFY_AXES`, `:51-62`) with `content` (real content vs deliberate
  placeholder — the Blair's-Lab invented-placeholder lesson), `edge`
  (the awkward cases in the operator's own words), and `nongoal` (the scope
  fence), each with a "just decide" default in `DEFAULT_AXIS_ANSWERS`
  (`:75-81`) and the question cap raised only in intake mode (the existing
  5-question cap stays on the quick path — `DEFAULT_MAX_QUESTIONS`, `:67`).
  `services/ui_gateway/src/dispatch_coordinator.py` — Stage-0 mode select in
  `parse_dispatch_command` (`:161-219`; an explicit `advanced` token after
  the verb, plus size/ambiguity heuristics the coordinator owns), riding the
  existing `PendingRequirements` hold state (`:136-158`) and its render /
  answer / decide handlers (`:488`, `:429`, `:453`) — no new session state
  class.
- **Contract added:** intake mode asks the extended axis set, bounded to one
  screenful, skippable ("just decide for me" already parses —
  `clarify.py:266-288`); the quick path's five-axis behavior is untouched.
- **Tests:** parse lock for the mode token; cap lock (extended interview
  never exceeds the intake cap); axis-default lock (each new axis
  self-answers to a recorded assumption). Toggle-off proof — flag off ⇒
  today's five axes and cap, byte-identical questions on the same fake
  emissions.
- **Depends on:** nothing (disjoint files from S1; parallel-safe).

### 5.4 Slice S3 — coverage by construction + blocking pre-render check

- **Touches:** `shared/fleet/acceptance.py` — a contract-synthesis step
  between criteria and job-oracle authoring: derive the module map FROM the
  floored criteria set and emit the oracle import contract 1:1 with build
  tasks (today the decompose emission proposes contracts and the oracle is
  authored against them — `:2723-2741`; the intake inverts the derivation so
  coverage holds by construction). Then harden step 2h (`:3210-3222`): in
  intake mode a non-empty coverage warning triggers ONE bounded
  re-synthesis; still-gapped ⇒ the `PlanResult` carries a blocking marker.
  `services/ui_gateway/src/dispatch_coordinator.py` — `_finalize_plan` /
  `_approve` (`:504`, `:765`) refuse approval while the marker is set (gap
  named in the refusal; revise and reject remain open).
  `shared/fleet/context_pack.py` — `contract_coverage` (`:708-779`) is the
  measurement substrate and should not need changes.
- **Contract added:** in intake mode, an approved plan has zero uncovered
  tasks and zero orphan oracle imports, by construction or not at all. The
  quick path stays warn-loud (the `acceptance.py:2862-2866` capability
  boundary — see §3 Stage 3).
- **Tests:** lock — a gapped plan in intake mode cannot be approved (drive
  the coordinator with a fake plan_fn returning a gapped plan; assert the
  refusal names the gap); re-synthesis lock — one retry, never a loop.
  Toggle-off proof — flag off ⇒ warn-loud text in the card message,
  approval permitted (the #989 behavior the `efb7f17e` F2/F5 locks already
  pin; those existing tests double as the substrate's regression net).
- **Depends on:** S1 (typed+floored criteria are the derivation input);
  full value with S2's richer answers, but S2 is not a hard dependency.

### 5.5 Slice S4 — spec→exam channel hardening

- **Touches:** `shared/fleet/acceptance.py:3204-3208` — thread the enriched
  `planning_seed` (not the clean `goal`) into `author_and_qa_job_oracle` →
  `generate_job_acceptance_oracle` (`:2683-2741`), giving the multi-task
  job-oracle author the same visibility the single-task oracle already has
  (`:3155-3156`). Extend the persisted acceptance record
  (`write_acceptance_record` call, `dispatch_coordinator.py:772-779`) with
  the intake's interview record — `spec.clarifications` already rides
  `to_dict` (`acceptance.py:426-434`), so this is additive fields, not a new
  store.
- **Contract added:** the exam author sees the complete typed criteria set
  AND the clarified requirements for BOTH oracle shapes; the acceptance
  record is the durable intake transcript, run-id-keyed.
- **Tests:** lock — the job-oracle authoring prompt contains the
  requirements block when requirements are present (assert on the fake
  `generate_fn`'s captured prompt); record round-trip lock. Toggle-off — the
  seed-threading half is arguably a DEFECT FIX against the `generate_plan`
  docstring's existing "both oracles" claim (`:2948-2951`) and may ship
  ahead of the flag if the LA agrees; the report of this document flags it
  as a finding.
- **Depends on:** S1 (a complete criteria set is what makes the channel
  worth carrying); the seed-threading sub-item is independent.

### 5.6 Grounding reads for the build agent (in order, ≤8)

1. `shared/fleet/acceptance.py:2904-3253` — `generate_plan`, the whole plan
   sequence and both stage-gate patterns.
2. `shared/fleet/acceptance.py:2079-2207` — `render_criteria_preview`, the
   card the operator approves.
3. `shared/fleet/clarify.py` (whole file, 415 lines) — the interview
   skeleton: axes, ruler, defaults, sentinel seam.
4. `services/ui_gateway/src/dispatch_coordinator.py:80-260, 375-560,
   765-930` — session states, plan flow, approve/revise/reject verbs.
5. `shared/fleet/context_pack.py:702-779` +
   `shared/fleet/acceptance.py:2852-2902` — the coverage check and its
   warn-loud rationale.
6. `shared/fleet/swap_driver.py:1955-2087` — how an approved plan becomes
   per-task production prompts (oracle notice, import contract, #989
   ceiling, context pack).
7. `services/assistant_orchestrator/src/entrypoint.py:592-608, 1047-1072,
   2007-2008, 3051-3056` — the flag-wiring chain to copy.
8. `services/assistant_orchestrator/config/default.toml:342-468` +
   `docs/quality/dispatch-quality-ledger.md:31-50` — flag house style; the
   six grading dimensions Stage 4 references.

## 6. Open questions (kept honest — resolved only where source settles them)

- **RESOLVED by source — interview transcript home:** a run-id-keyed
  acceptance record already persists before firing and already carries the
  clarification record (`dispatch_coordinator.py:772-779`,
  `acceptance.py:407-414, 426-434`). The transcript lives there; no new
  store. (Remaining sub-question for the LA: none — it is the operator's own
  data on the operator's own disk.)
- **RESOLVED by source — battery bypass:** a card dispatch never clarifies
  and never revises (`generate_plan:2988-2993` skips clarify when a
  `decomposition_override` is present; revision is operator-initiated only).
  The battery bypasses the intake by construction, no work needed.
- **OPEN — spec reuse:** do accepted specs become templates for similar
  asks? (A product question; nothing in source settles it.)
- **OPEN — voice-driven intake:** the voice stack exists; whether the
  interview should ride it is an LA experience call.
- **OPEN — card-authoring mode:** the battery's cards are pre-specified, but
  a "card authoring" mode reusing Stage 2/3 could keep future card contracts
  clean (#1008 showed what a dirty card contract costs). Needs its own
  scoping — the battery lives in the sibling agentic-setup install.
