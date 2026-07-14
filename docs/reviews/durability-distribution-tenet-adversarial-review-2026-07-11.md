# Adversarial review — the "durability-without-distribution" Coordinator-program proposal

**Reviewer:** independent Claude Code session (author ≠ verifier; did not write the proposal)
**Date:** 2026-07-11 (late; comments referenced carry 2026-07-12 server timestamps, -05:00)
**Anchor verified:** `main` HEAD = `cbb0bf5f` (the exact author-time anchor; no drift). Proposal artifacts confirmed uncommitted working tree: `docs/research/coordinator-program-plan-2026-07.md` (one inserted bullet, plan line 67) + `docs/journal_fragments/2026-07-11_durability-distribution-tenet.md` (untracked).
**Under review:** (A) the anti-drop tenet bullet in the plan's §Kanban method; (B) the #842 c.1822 ADR-039 requirement; (C) the #846 c.1823 pull-policy requirement + acceptance shape; (D) the two deliberate NON-actions (no coder instruction, no CLAUDE.md line); (E) the fragment's proposed lesson.
**Handoff:** `docs/handoffs/durability-distribution-adversarial-review-handoff-20260711.md` (all 9 attack angles serviced below).

---

## Verdict: REFINE

The core tenet is sound, correctly homed in the Coordinator program, and NOT redundant
with the existing cousin rules — it names a distinction ("durable record" vs "placed in
the pull view the next actor reads") that the existing doctrine genuinely lacks, and the
plan's own Phase-C2 text proves the distinction matters by getting it wrong (F4). The
over-engineering steelman fails (F10): the program's constitution is structure-over-
vigilance, and the LESSONS discipline itself is one tally away from *forcing* a
structural control of exactly this shape.

But the proposal ships with real defects: the auto-re-surface mechanism is
deterministically evaluable for only one of its own three named examples (F1); the
`blocked_on` encoding is unspecified and its most natural implementation is inert under
the plan's own Definition-of-Ready gate (F2); and both seeds are comment-only while the
parent ticket descriptions enumerate their scope without the tenet — the proposal
under-distributes itself (F3). None of these require rework of the shape; all should be
fixed before ADR-039 authoring.

---

## Ranked findings

### F1 — CONFIRMED — The resource-predicate class is not deterministically evaluable for most of its own named examples
**Where:** plan line 67; #842 c.1822; #846 c.1823 point 1. All three give the same
example triple: "a lean-box/GPU-daytime window, a wheel rebuild, an upstream fix."
**The defect:** the Coordinator's hard law is *gate as JUDGE, model as SIGNAL* — every
mechanism must be code-computable from Vikunja/host state. Of the three examples:
- **GPU/lean-box window** — computable: schedule config + fleet-swap `current.json` +
  battery-campaign state all exist on disk today, and the plan's quiet-queue tripwire
  already assumes schedule-awareness. This example is fine.
- **A wheel rebuild** — not a resource: it is *work*, i.e. a ticket dependency. Its
  correct encoding is a blocker relation handled by the existing DoR semantics. Placing
  it in the resource class conflates the two blocker taxonomies the tenet itself insists
  are distinct.
- **An upstream fix** — an external event with no host signal. Worse than "not yet
  built": the runtime Coordinator is structurally FORBIDDEN from checking it. Zero new
  egress, one-network-client invariant, loopback-only Vikunja (plan §Security posture)
  — polling GitHub for a fix landing is an egress action the architecture refuses. This
  predicate is unevaluable *by design*, permanently.
**Failure scenario:** a card marked `blocked_on: resource=upstream-fix-#25116` never
auto-re-surfaces, because nothing can evaluate the predicate. The operator, having been
promised "the board re-surfaces gated work when the resource frees," stops carrying it
mentally — so the drop is now MORE silent than before the mechanism existed. A
false-confidence regression: the mechanism's failure mode is the exact failure it was
built to prevent, plus misplaced trust.
**Proposed fix:** ADR-039 defines a **closed, enumerated resource-predicate registry**,
each entry shipping with a deterministic evaluator over host/board state (initial set:
`gpu-window`, `lean-box`, `disk-space`, `model-resident` — whatever C1's snapshot
composer can actually read). Marking a card resource-gated with a predicate not in the
registry is REFUSED at staging (fail-closed). Blockers that are work go to relations/DoR;
external events (upstream fixes) get an honest third treatment: a recurring
line in the briefing/digest ("N cards awaiting external events — human check"), i.e.
explicitly human-checked at a bounded cadence rather than falsely promised as automatic.
The registry and its evaluators are ruler definitions → governed core (see F11).

### F2 — CONFIRMED — The `blocked_on` encoding is unspecified, and the natural encoding is inert under the plan's own DoR gate
**Where:** #846 c.1823 point 1 (`blocked_on: resource=…` — a syntax with no named
substrate); plan line 62 (DoR: Ready requires "no unresolved blocker relation").
**The defect:** Vikunja v2.3.0 has no custom fields wired (plan pins buckets, relations,
labels, saved filters). The two candidate encodings:
- **A blocker relation** — the natural reading of "blocked_on" — is exactly what the DoR
  gate excludes from Ready. A relation-encoded resource gate pulls the card OUT of Ready;
  the pull computation (over Ready items) never sees it; the mechanism is inert. This is
  lesson-class C6 (built-not-wired) waiting to happen, and the tenet's "Ready-but-waiting"
  language directly contradicts it.
- **A label** (e.g. `Resource:gpu-window`) — workable, consistent with design item 11
  (IDs name-resolved, labels code-set), but labels carry no parameters: the label can
  name a registry key, never an arbitrary predicate string. This constrains F1's fix in
  a good way (closed registry ⇒ closed label vocabulary) but must be SAID.
**Failure scenario:** the C4 implementer, reading "blocked_on predicate," reaches for
relations; DoR de-Readies every gated card; the multi-project fixture lock is written
against the same wrong mental model (both test and code agree — lesson-class C3) by
asserting the card re-enters Ready when the resource frees, which passes while the
visible-while-gated half silently never worked.
**Proposed fix:** the #846 requirement names the encoding decision as an explicit
ADR-039 item: resource-gate = **registry-keyed label set by deterministic code**; the
card **remains in the Ready bucket**; the DoR checklist explicitly states resource
labels are not blocker relations; pull eligibility (not bucket membership) is what the
predicate suspends.

### F3 — CONFIRMED — The seeds fail the proposal's own distribution test (the irony check has teeth)
**Where:** #842 description vs c.1822; #846 description vs c.1823.
**The defect:** both requirements live only as comments. #842's description enumerates
the ADR's content as items (a)–(k) — the tenet is not among them. #846's description
enumerates the pull policy in scope items (1)–(5) — resource-gating and
residual-replenishment appear nowhere. House convention (ADR-021 comment streams,
ticket-as-context-home) makes comments load-bearing, which mitigates — but the
description is the canonical scope statement, and #842 already carries one prior
scope-add comment (c.1814), so a fresh ADR author faces a description checklist plus a
comment stream of unequal apparent authority. The proposal preaches "put it in the view
the next actor reads first"; for an ADR author that view is the description.
**Failure scenario:** the C0 session works down (a)–(k), ships ADR-039 without the
tenet, closes #842 — the exact drop, on the ticket that was supposed to encode its
prevention.
**Proposed fix:** two one-line, LA-approved description edits: append the tenet to
#842's item (b) (the method enumeration) and append resource-gating + dispatch-residual
replenishment to #846's items (1)/(2). (Note Vikunja `update_task` is a full PUT —
carry the existing description + priority when editing.)

### F4 — CONFIRMED — Phase C2's "durability" line contradicts the tenet
**Where:** plan Phase C2: "Information durability: per-project outcome ledger append +
**ticket comments as the distribution channel**."
**The defect:** by the tenet's own definitions a ticket comment is the durable record,
NOT distribution — #769 c.1679 was a ticket comment, and it is the incident's exhibit A.
C2's line encodes precisely the pre-tenet conflation the proposal exists to kill, one
section below the tenet.
**Failure scenario:** the C2 implementer satisfies "distribution" by writing comments;
queue placement is skipped as out-of-scope; the #769 class recurs *with doctrine cover*
("distributed — see the comment").
**Proposed fix:** amend the C2 line when the tenet lands (same edit pass): comments +
ledger = the durable half; distribution = board/queue placement; C2's harvest/hygiene
steps write BOTH halves. ADR-039 mirrors the distinction.

### F5 — CONFIRMED (absence verified by grep) — Dispatch-residual replenishment has no structured source channel
**Where:** #846 c.1823 point 2: run residuals "converted into staged queue items by the
work-origination loop — never left to die in the transcript."
**The defect:** grep across `shared/fleet/` finds no residuals/follow-ups field in the
report surfaces (`acceptance.py`'s only "residual" is an oracle comment; `dispatch.py`'s
is an S4 note). What exists structurally: per-criterion MET/NOT-MET in the honest report,
and the PARKED-HONEST outcome. Those cover *couldn't-finish*; they do not cover
*discovered follow-ups* or *deferred hardening* — new work found mid-run, which today
lives only in transcript/SUMMARY prose. The harvest step would have to model-read prose
with unverifiable recall; the acceptance lock "a dispatch residual becomes a staged
proposal" can then only ever test a happy-path fixture, not the property.
**Failure scenario:** C4 ships, the lock is green on its fixture, and real runs' deferred
hardening keeps dying in transcripts — durable-but-not-distributed at the coder layer,
now with a green gate asserting otherwise (lesson-class C14: a claim the code does not
enforce).
**Proposed fix:** the requirement names its interlock: the run-report schema (M2/#740
territory — plan item 15 already flags the collision surface) gains a structured
`residuals[]` field populated at run end; the #846 harvest consumes that field.
Model-summarization can *augment* recall; the structured field is what the lock tests.

### F6 — PLAUSIBLE — The "no coder instruction" call is half-right
The reasoning (queue concern lives at the harvest layer) is correct against a *prompt
exhortation* — behavioral instructions to the coder are the vigilance pattern the
program forbids. But F5's fix reveals the residual: someone must POPULATE `residuals[]`
at run end, and that is a coder/critic-layer **report-contract obligation** — a schema
field with a gate, not a prompt line. The predecessor's binary (coder instruction vs
harvest-layer) missed the third option that is actually needed. Refinement: restate the
"no" call as "no behavioral prompt instruction; yes a report-contract field enforced by
the fleet gate."

### F7 — PLAUSIBLE — "No CLAUDE.md line" is right, but the interim distribution has a verified hole: the handoff template
**Where:** `docs/governance/handoff-brief-template.md` — grep confirms ZERO occurrences
of queue/distribute/carry-forward language.
**The defect:** the three cousin rules cover closure (shipping-closes-the-ticket),
partial-land state (CURRENT-STATE), and successor grounding (comprehension gate) — none
covers defer→queue-placement. The predecessor's "already covered" claim is therefore
overstated; what saves the "no CLAUDE.md line" call is bloat discipline plus the
operator-memory, which distributes to Claude sessions in this namespace. But the
**handoff template is the exact surface in the author's hands at the exact moment the
#769 failure happened** (authoring an overnight handoff), and it never asks the
question. The structural control is graduation-gated and far off; the interim control
is one checklist line away.
**Failure scenario:** a session authors a handoff from the template, mentions deferred
work in prose (exactly as the #769 handoff did), and the template — the one checklist
in play — never prompts "is every deferred item IN the queue view with its unblock
condition?" Recurrence before the board exists.
**Proposed fix:** one line in the template's required sections: *"Deferred/blocked
items: each has BOTH halves — the durable record (ticket/CURRENT-STATE) AND a queue
placement (#859 / the board) with its unblock predicate. List the queue entries."* The
template is a tracked file → applying this needs a commit → LA word (and a quiet-tree
moment; a ticket if deferred — which, per the tenet, then goes in #859).

### F8 — PLAUSIBLE — Gated cards poison the plan's own flow metrics and alarms
**Where:** plan line 65 (aging-WIP outlier stall detection) vs the tenet's
never-dropped, still-aging gated cards; also design item 8 (class-then-age global pull).
**The defect:** a card gated for weeks becomes a permanent age outlier → recurring
stall alarms → the alert-fatigue spiral the plan itself warns about (C3: "false alarms
never retrain the operator to ignore it"). Separately, if age accrues during gating, a
long-gated card instantly preempts its whole class on release (probably *desired* — it
is the catch-up property — but the starvation-guard analysis never considered gated
age, so it is an accident, not a decision).
**Proposed fix:** ADR-039 decides both explicitly: gated time is EXCLUDED from
stall/aging alarms but reported as a distinct "gated inventory" line in the digest
(visibility without alarm); age DOES accrue for pull ordering (catch-up on release),
stated as a decision with the alternative named.

### F9 — PLAUSIBLE — The acceptance-lock wording permits a drop-and-re-add implementation
**Where:** #846 c.1823 acceptance shape: "a resource-gated card re-appears in the
computed pull order the cycle AFTER its resource frees."
**The defect:** "re-appears" is satisfiable by an implementation that drops gated cards
and re-adds them on a predicate flip — reintroducing a drop window (a crash or a
predicate-evaluator error between drop and re-add loses the card), which is the exact
risk "never dropped from the pull computation" exists to exclude. The two phrasings in
the same seed pull in opposite directions.
**Proposed fix:** the fixture lock asserts BOTH halves: (a) while gated — present in
the computation, visible in the board/digest, ineligible to pull; (b) the cycle after
the resource frees — eligible and correctly class-then-age ordered. Presence is the
invariant; eligibility is what flips.

### F10 — Adversarial angle 2 (over-engineering) — steelman REFUTED, with one language trim
The steelman ("the #769 failure was discipline — the #859 queue existed and was simply
not used; fix the discipline, skip the machinery") fails on three grounds: (1) the
program's constitution is structure-over-vigilance — lesson-class C19 says a control
that depends on remembering is not a control, and a session is "a human" for this
purpose; (2) discipline-only was ALREADY the standing state when #769 dropped — the
memory-and-queue regime is the thing that failed, not an untried alternative; (3) the
LESSONS discipline itself: this incident is plausibly lesson 10's second instance (see
F12), and a third instance *mandates* a structural control — the #846 mechanism is that
control, built one incident early. The machinery is justified **provided F1's closed
registry keeps it minimal**. One trim: the tenet says resource-gated deferral is "a
first-class, still-visible board **state**" — "state" invites a new bucket/lane, which
is more structure than needed and collides with the bucket workflow. The minimal
sufficient encoding is a *marking* (registry label) + a pull-eligibility rule. Say
"first-class, still-visible marking," and F2's encoding follows naturally.

### F11 — Adversarial angle 7 (self-governance boundary) — PASS, two nits
Traced propose→act: auto-re-surfacing is deterministic pull-order computation (read +
compute, no write); replenishment lands as staged proposals behind approval; card
label writes are the same class as C2's deterministic lifecycle writes. No new write
path, no autonomy increase, no governed-core touch. Two nits to make it airtight in
ADR-039: (1) the `blocked_on` predicate VALUE is registry-validated at staging and
never taken from model free-text — the CaMeL property extended from action *targets*
to gating *predicates* (an injected predicate could otherwise hide a card indefinitely:
a suppression attack); (2) the predicate registry + evaluators are ruler definitions
and therefore governed core — covered by the existing "the coordinator's own ruler
definitions" line, but worth citing as a named instance.

### F12 — Adversarial angle 8 (lesson class) — recurrence of lesson 10, not a new mint
LESSONS.md lesson 10: *"Continuity of intent across agents is a file-system property,
not a memory property… write it down where the next session will read it — not where
you will remember it."* The proposed lesson is this class sharpened by one notch: the
#769 information WAS written down — but where the author could point to it, not in the
pull view the reader reads first. That is the same class (information placed relative
to the author's memory vs the reader's path), second instance. C19 (remembering is not
a control) and C16 (shared state needs a mechanism) are the canonical umbrellas. The
fragment already anticipates exactly this and defers correctly to the integrator.
**Recommendation to the integrator:** tally lesson 10 (`*(recurred: 2026-07-11 — the
#769 queue-drop; durability without distribution is half the job — the durable record
must land in the pull view the next actor reads, not just on the ticket)*`), do not
mint. Note the consequence: lesson 10 is now at two instances — the NEXT recurrence
mandates a structural control, and the #846 mechanism should be named as the control
already in flight.

### F13 — Adversarial angle 9 (distribute AND curate — the LA's counterweight) — genuine gap, fix as a PAIRED tenet, not a rewrite
The existing anti-bloat mechanisms all curate CONTENT surfaces: LESSONS quarterly
consolidation + tally-not-mint, fragments fold-then-DELETE, memory dedup/delete, #267
doc-sprawl. Structure curation exists only as one-offs — #859 names its own
supersession in its description; nothing generalizes it. Two recommendations:
1. Do NOT overload the anti-drop bullet with a curation clause — it is about the drop
   failure, and a bolted-on counterweight muddies both rules. Instead ADR-039's method
   section carries a **paired tenet**: *"Scaffolding is retired by the thing that
   replaces it"* — every interim mechanism, board structure, or one-off doctrine is
   created CARRYING its supersession predicate, and the superseding change's
   Definition-of-Done includes executing the retirement (the #859 pattern generalized;
   same shape as shipping-closes-the-ticket, which is closure-curation for tickets).
   Distribution then has its counterweight as a sibling of equal rank.
2. Board-structure hygiene gets a deterministic home: the substrate-setup migration
   (design item 11) becomes bidirectional — discover-or-create AND flag-orphans (labels,
   buckets, saved filters no current doctrine references), reported in the digest as
   curation candidates, human-approved removals. This closes the "dead board states"
   gap with zero new autonomy.
Seeding the paired tenet onto #842 is a one-comment/one-description-line change —
include it in the F3 edit pass if approved.

---

## Angles with no finding
- **Placement (#842-vs-#846 split, angle 6):** correct as proposed — doctrine in the
  ADR ticket, mechanism + locks in the pull-policy ticket, matching the program's
  C0-implements-under-doctrine shape.
- **Redundancy (angle 6):** the tenet is NOT a restatement. "Ticket is the context
  home" is a durability rule; the tenet is a distribution rule; F4 demonstrates the
  plan itself conflated them, which is the strongest possible evidence the distinction
  is load-bearing rather than decorative.
- **Interim state:** #769 is correctly parked — c.1821 CURRENT-STATE pinned, #859
  TIER-0 entry enumerates the four sub-items with the carry-forward condition. The
  near-term half of the fix is genuinely done (F7's template line is the one interim
  gap found).

## What I'd change and where (the apply list, pending LA approval — none applied)
1. **Plan doc, tenet bullet (line 67):** "board state" → "marking"; example triple
   re-scoped to registry-evaluable resources; "wheel rebuild" moved to the DoR-relation
   class and "upstream fix" to a named external-event/human-check class. (F1, F10)
2. **Plan doc, Phase C2 line:** comments/ledger = durable half; board placement =
   distribution; harvest writes both. (F4)
3. **#842:** description edit appending the tenet to item (b); requirement comment
   addendum naming the closed predicate registry, the label-not-relation encoding
   decision, the metrics/aging decisions, and the paired scaffolding-retirement tenet.
   (F1, F2, F3, F8, F13)
4. **#846:** description edit appending scope items; comment addendum: registry-
   validated predicates (never model free-text), stays-in-Ready encoding, both-halves
   fixture lock wording, `residuals[]` report-schema interlock with #740/M2. (F1, F2,
   F5, F9, F11)
5. **Handoff template:** one deferred-items-both-halves checklist line (tracked file —
   commit needed, quiet tree). (F7)
6. **Fragment:** leave as-is except the integrator note — recommend recurrence-tally on
   lesson 10, not a mint. (F12)

*This review is the deliverable; nothing above was applied at review time. Disposition
below.*

---

## APPLIED (2026-07-11 late — LA approved REFINE with two scope flags)

LA disposition: REFINE concurred; apply list approved; **F5's `residuals[]` fix named as
a #740/M2 interlock now (design-only), implementing sessions sequence it**; **item 5
(template line) deferred to a quiet tree** (tracked file; battery live tonight).

| # | Item | Applied as |
|---|------|-----------|
| 1 | Plan-doc tenet bullet | Rewritten in the working tree: marking-not-state, closed registry, stays-in-Ready, blocker taxonomy (wheel-rebuild → DoR relation; upstream-fix → human-check briefing line, zero-egress rationale), alarm carve-out + age-accrual. Paired scaffolding-retirement bullet added directly after (F13). |
| 2 | Plan-doc Phase C2 line | Un-conflated: ledger + comments = durable half; board/queue placement = distribution; harvest writes both. |
| 3 | #842 | Description item (b) now carries both tenets (F3 closed); disposition comment **c.1833** carries the five hardened ADR-039 requirements. |
| 4 | #846 | Description scope (1)/(2) + acceptance shape updated (resource-gating, `residuals[]` replenishment source, both-halves fixture lock, unregistered-predicate refusal, suppression-attack note in threat model); disposition comment **c.1834**. |
| — | #740 interlock | Cross-comment **c.1835**: `residuals[]` as an M2 run-report-schema requirement, report-contract-not-prompt, sequenced by the implementing sessions. |
| 5 | Template line | DEFERRED per LA → both halves written: ticket **#864** (the edit, its rationale, quiet-tree constraint, and its own retirement predicate per the paired tenet) + #859 queue placement (comment c.1836, TIER 3; comment-not-PUT to avoid racing the live coordinator's description maintenance). |
| 6 | Fragment integrator note | Rewritten to recommend tally-of-lesson-10, not mint, with the two-instances/third-mandates-control consequence named. |

Journal fragment for this review+apply arc:
`docs/journal_fragments/2026-07-11_durability-tenet-adversarial-review.md`.

---

## SECOND PASS (2026-07-12, LA-directed) — on-disk verification, end-to-end process walk, agent-environment findings

### Verification of the applied state (all checked on disk / on server)
- #842 + #846 descriptions verified on the server post-PUT: all inserted text intact,
  formatting survived, labels preserved (#842 Architecture), priorities preserved (4/3).
  #864 + comments c.1833–1836 verified present.
- Defects found in this session's own artifacts, fixed in this pass: two bad sentences
  in this file (F10 heading "angles"→"angle"; "a untried"→"an untried"); and **V4 below**
  (a real interaction seam the refinement itself created — the tripwire definition).
- Pre-existing plan-doc defect found + fixed: Phase C0 said "five structural controls";
  the §Self-governance boundary enumerates SEVEN (controls 6–7 were added by the program
  review). One-word fix, "five"→"seven".

### Process walk — seams found stepping the designed flow end-to-end
(Flow walked: work enters → DoR → Ready → [resource-gate] → heartbeat evaluates →
pull → dispatch → run report → harvest → staged proposal → briefing → approval →
TOCTOU re-validation → execution → close/curation.)

- **V1 — Marking lifecycle is unspecified (spec gap, for ADR-039).** The registry label
  is applied at staging — but nothing says when it is CLEARED. If it rides the card into
  In Progress/Done, the "gated inventory" digest line and gated-time metrics count
  non-Ready cards as gated. Spec needed: marking cleared on successful pull (or ignored
  outside Ready), and a human-applied misspelled `Resource:*` label is caught by the
  paired tenet's orphan-flagging (unknown labels surfaced as curation candidates) — that
  half is already covered by design.
- **V2 — The missed heartbeat has no observer (event-noticed-by-no-one; the sharpest
  gap).** Every notice path in C2–C4 (stall alarms, tripwire, digests, eligibility
  flips) is computed BY the heartbeat cycle. A wedged or dead heartbeat therefore
  cannot fire its own alarm, and the only current detector is the operator noticing
  digests stopped — vigilance, which the program disallows as a control. Needs a
  deterministic dead-man check outside the heartbeat itself (candidates: the launcher
  watchdog or the existing elevated overnight task verifies a last-cycle-completed
  timestamp and surfaces staleness; same pattern as the boot canary — an independent
  process proving a liveness property).
- **V3 — Predicate-evaluator failure semantics unstated.** Design item 6 (tri-state
  OK/EMPTY/UNREACHABLE) covers substrate reads; it must be extended to the resource
  evaluators: an evaluator that throws or reads unreachable state returns UNKNOWN —
  the card stays gated-AND-visible and the condition is surfaced; UNKNOWN never renders
  as "resource free" (spurious release) or silently as "resource busy" (indefinite
  invisible gating).
- **V4 — FIXED THIS PASS: the tripwire false-fires on an all-gated Ready column.** The
  plan defined quiet-queue as "Ready items exist + WIP below limit + nothing pulling."
  With gated cards now staying IN Ready, a fully-gated column met the trigger while
  nothing was pullable. Both statements of the tripwire (§Kanban flow-metrics bullet;
  Phase C3) now require resource-ELIGIBLE work, with an all-gated column reported as
  gated inventory instead.
- **V5 — Flow metrics assume timestamps the substrate does not hold.** "Flow metrics
  from Vikunja timestamps" is under-specified: Vikunja stores created/updated/done_at
  but NO bucket-transition history, so age-in-Ready, per-stage cycle time, and the
  class-then-age "age" all need a defined source. Options ADR-039 must pick from:
  the coordinator journals its own bucket moves (blind to human webUI moves) or the
  heartbeat derives transitions by snapshot-diffing bucket state each cycle
  (cycle-granular, catches all movers) — or both. Also: "age" (created vs
  entered-Ready) must be defined once, since both FIFO fairness and the F8 gated-age
  accrual decision depend on it.
- **V6 — Residual seam in this session's own apply step, mitigated.** The #859 queue
  add rode a COMMENT (c.1836) to avoid racing the live coordinator's description PUT —
  but a coordinator that reads only the description could miss it (the tenet's own
  failure shape, one layer down). Mitigation that makes it acceptable: #864 exists as
  its own open ticket in the same project, so any paged backlog read finds it
  independently of #859; the comment is belt-and-braces, not the sole path.

### Agent-environment findings (the LA's four questions)

- **E1 — Defined lookup locations exist and are the right ones, with one addition
  needed.** The design's answer to "where does the agent look" is deliberately
  inverted for a 14B: the Coordinator model never self-navigates — deterministic code
  composes a bounded context per single decision (small-model discipline) from three
  defined sources: **policy** = `[coordinator]` config + the signed policy file
  (control 7); **state** = the C1 work-state snapshot composer (fleet-swap
  `current.json`, battery campaign, fleet queue, SUMMARY/scorecards, Vikunja
  open-ticket view); **work** = the Vikunja board (paginated reads, #856 prerequisite).
  That inversion should be stated in ADR-039 as an explicit tenet ("the composer is the
  Coordinator's only sensory path — the model is handed context, it never fetches"),
  because it is currently implied by the small-model discipline rather than named.
- **E2 — Asset inventory the program must create** (consolidated; today NONE of these
  exist — the program is design-only): (a) Vikunja substrate: per-project bucket sets,
  class-of-service labels, `Resource:*` registry labels, saved filters, the dedicated
  `blarai-coordinator` account — all created by the item-11 idempotent operator-run
  setup migration, never by the Coordinator; (b) config: `[coordinator]` section +
  the signed policy file (forbidden targets, registry, WIP limits, cadences, TTLs,
  absence mode); (c) stores: proposal-staging store, briefing ledger, shadow journal
  (all born-encrypted), per-project outcome ledger; (d) code: bridge read ops,
  snapshot composer, predicate-evaluator registry, pull-policy module, ruler,
  heartbeat entrypoint + timer, digest/briefing renderer, fixture-board eval suite;
  (e) the Coordinator system prompt (governed core, dev-channel authored); (f) PA
  adjudication verbs for coordinator action classes; (g) ADR-039 + DECISION_REGISTER
  row.
- **E3 — Asset discovery: the boot canary proves only the NEGATIVE.** Control 6 proves
  the coordinator CANNOT reach the governed core; nothing proves it CAN reach what it
  needs. Recommend a symmetric **positive required-assets probe** in the same boot
  self-check: buckets/labels/account resolvable by name, stores openable, policy
  signature valid → else refuse-to-start (or degrade to advisory-only with the
  condition surfaced, matching tri-state semantics). Without it, a half-migrated
  substrate produces the silent-empty failure design item 6 exists to prevent —
  discovered at the first live cycle instead of at boot.
- **E4 — System prompts: yes, two adjustments.** (1) **The AO's prompt needs an
  explicit peer-role section when C1 lands**: route `/coord` to the Coordinator
  surface, render coordinator output as UNTRUSTED-tier display content (design item
  13), and DO NOT improvise PM answers itself — without the non-overlap statement, a
  user asking "what should I work on next?" gets an AO hallucination instead of the
  board, and the two roles blur exactly the way prompt-integrity reasoning (§Agent
  architecture) warns about. (2) **Scaling: adopt a role-charter template in ADR-039**
  — a shared skeleton every resident role instantiates (identity + mandate, tool
  surface, provenance posture, refusal/escalation rules, adjudication identity,
  non-overlap statement naming its peers) with role-specific sections. PA and AO
  prompts predate any such pattern; the third role is the moment to factor it, so
  role N+1 is an additive instantiation rather than a bespoke prompt plus edits to
  every existing one. (The dev-side CLAUDE.md needs no change now; at C1
  implementation it gains a §Coordinator pointer — where status lives, how to read
  the board.)

### Disposition of second-pass findings
Fixed in this pass (clear defects, LA-directed verification): the two sentence defects,
"five"→"seven", and V4 (both tripwire statements). SEEDED on LA direction (2026-07-12,
"update the tickets as needed now"): **#842 c.1838** (the seven ADR-039 requirements —
V1/V2/V3/V5 + E1/E3/E4), **#845 c.1839** (dead-man check, tripwire-eligibility fixture,
evaluator UNKNOWN semantics), **#843 c.1840** (bucket-transition snapshot-diff
derivation, positive required-assets boot probe), **#846 c.1841** (marking-clear
lifecycle, tripwire/age cross-references).
