# Disposition of the durability-without-distribution adversarial review

**Author:** proposal author (this session) — evaluating the independent reviewer's findings
**Date:** 2026-07-11
**Review under disposition:** `docs/reviews/durability-distribution-tenet-adversarial-review-2026-07-11.md` (verdict REFINE, 13 findings)
**Verification:** all six load-bearing premises re-verified on disk (plan lines 62/65/67/90/124/127; #842 desc items (a)–(k); #846 desc items (1)–(5); `shared/fleet/` residuals grep; LESSONS.md lesson 10). No overclaims found.
**Status:** DRAFTED — nothing applied. Awaiting LA go/no-go.

## Concurrence

I concur with **REFINE**. The core tenet is sound and correctly homed; the review found real defects that would have shipped into ADR-039. Every CONFIRMED finding is verified. The two PLAUSIBLE-labelled findings (F6, F7) are honest — real gaps, not proven regressions — and I accept both. The review respected draft-not-apply and did not touch the tree.

The two irony traps the LA named are both live and both handled below: (a) don't fix bloat by adding sprawl — the apply-plan re-scopes and points rather than duplicating, and F13 adds the anti-bloat counterweight as a *sibling* tenet rather than overloading the anti-drop bullet; (b) distribute the fix where the author reads it — the F3 edits put the requirement into the ticket **descriptions** (the (a)–(k)/(1)–(5) checklists), not only comments.

## Per-finding verdict

| # | Review verdict | My verdict | Note |
|---|---|---|---|
| F1 | CONFIRMED | **CONFIRMED** | Sharpest finding. Example triple conflates 3 predicate kinds; "upstream fix" is unevaluable *by design* (polling = egress, forbidden). False-confidence regression is real. |
| F2 | CONFIRMED | **CONFIRMED** | Relation-encoding is inert under DoR (built-not-wired trap). Label encoding is the only workable one; must be said. |
| F3 | CONFIRMED | **CONFIRMED (verified)** | Both descriptions verified. The proposal fails its own distribution test. Highest-value quick fix. |
| F4 | CONFIRMED | **CONFIRMED (verified)** | Line 90 verbatim contradicts the tenet. Strongest evidence the distinction is load-bearing. |
| F5 | CONFIRMED | **CONFIRMED (verified)** | No `residuals[]` field exists; bridge comment admits follow-ups die untracked. |
| F6 | PLAUSIBLE | **CONFIRMED as refinement** | My binary missed the 3rd option: a report-contract *field* (not a prompt line). Sharpens, doesn't reverse, my "no coder prompt" call. |
| F7 | PLAUSIBLE | **CONFIRMED premise** | Handoff template has zero queue/carry-forward language — the exact surface in hand when #769 dropped. Interim gap, one line from closed. |
| F8 | PLAUSIBLE | **CONFIRMED as gap** | Gated cards poison aging alarms + preempt on release. A real design consequence I didn't consider. |
| F9 | PLAUSIBLE | **CONFIRMED** | "re-appears" permits drop-and-re-add → reintroduces the drop window the mechanism exists to exclude. |
| F10 | steelman refuted | **CONCUR** | Over-engineering steelman fails. One trim: "state" → "marking" (avoids a needless new bucket/lane). |
| F11 | PASS + 2 nits | **CONCUR** | No new write path. The suppression-attack nit (an injected predicate hiding a card forever) is a genuine new vector — worth locking. |
| F12 | recurrence of L10 | **CONFIRMED (verified)** | Tally lesson 10, don't mint. L10 → 2 instances; the NEXT recurrence mandates a control, and #846 is that control in flight. |
| F13 | genuine gap | **CONFIRMED — this is the LA's own question answered** | Paired anti-bloat tenet as a sibling. Directly answers "will the structure be cleaned up so there isn't bloat and signal loss?" |

## The apply list (grouped by where + risk class)

### Category A — distribution fixes (defect-shaped: the proposal failing its own test). Apply on the word.

**A1 (F3) — ticket description edits (durable board, not code).**
- **#842 description, item (b):** name the two tenets in the enumeration so an ADR author working the (a)–(k) checklist cannot miss them. Tight pointer, not the full spec (spec stays in the comment + plan — anti-bloat).
- **#846 description, items (1)/(2):** add resource-gated deferral to (1) and dispatch-residual replenishment to (2).
- NOTE: `update_task` is a full PUT — carry the full existing description + priority (4 for #842, 3 for #846) on each edit.

**A2 (F4) — plan doc, Phase C2 line (line 90).** Amend so comments/ledger = the durable half and board placement = distribution; harvest writes both.

### Category B — mechanism refinements (design decisions; I own the technical HOW, recommend applying all).

- **B1 (F1+F10):** re-scope the tenet bullet — "state" → "marking"; the example triple re-scoped to registry-evaluable resources only; "wheel rebuild" reclassified as a DoR blocker relation; "upstream fix" reclassified as an external-event human-check line. ADR-039 defines a **closed, enumerated resource-predicate registry**, each key shipping a deterministic evaluator, unknown predicates refused at staging (fail-closed).
- **B2 (F2):** encoding decision named as an ADR-039 item — resource-gate = **registry-keyed label set by deterministic code**; card **stays in the Ready bucket**; DoR checklist explicitly states resource labels are NOT blocker relations; **pull-eligibility** (not bucket membership) is what the predicate suspends.
- **B3 (F8):** gated-time metrics decision, stated with the alternative — gated time **excluded** from stall/aging alarms, reported as a distinct "gated inventory" digest line (visibility without alarm); age **does** accrue for pull ordering (catch-up on release).
- **B4 (F9):** tighten the #846 acceptance lock to assert BOTH halves — (a) while gated: present in the computation, visible in digest, **ineligible** to pull; (b) the cycle after free: **eligible** + correctly class-then-age ordered. Presence is the invariant; eligibility flips.
- **B5 (F5+F6):** name the interlock — a structured `residuals[]` field on the run report (interlock with #740/M2 run-report schema, plan item 15) populated at run end; #846 harvest consumes that field; the acceptance lock tests the field, not a prose fixture. Restate the "no coder" call: **no behavioral prompt instruction; yes a report-contract field enforced by the fleet gate.** — *This one carries a genuine scope flag: the field lands in #740/M2 territory. See "LA-facing" below.*
- **B6 (F11 nits):** the `blocked_on` predicate VALUE is **registry-validated at staging, never model free-text** (the CaMeL property extended from action targets to gating predicates — an injected predicate could otherwise hide a card indefinitely, a suppression attack); the predicate registry + evaluators are **ruler definitions → governed core** (cite as a named instance of the existing line).

### Category C — the anti-bloat counterweight (the LA's question, answered).

- **C1 (F13.1):** a **paired tenet** — *"Scaffolding is retired by the thing that replaces it."* Added as a **sibling bullet** in the plan §Kanban method (NOT overloaded into the anti-drop bullet) and named in #842 item (b): every interim mechanism / board structure / one-off doctrine is created carrying its supersession predicate; the superseding change's Definition of Done includes executing the retirement (the #859 pattern generalized; same shape as shipping-closes-the-ticket).
- **C2 (F13.2, optional / lower priority):** bidirectional substrate-setup migration (design item 11) — discover-or-create AND flag-orphans (labels/buckets/filters no doctrine references), reported in the digest as curation candidates, human-approved removal. Recommend as a smaller ADR-039 note, not blocking.

### Category D — interim control (tracked file → commit → quiet tree + LA word).

- **D1 (F7):** one required line in `docs/governance/handoff-brief-template.md`. This is the interim guard until the board exists — it lives on the exact surface that was in hand when #769 dropped. Tracked file, so it needs a commit on a quiet tree.

### Category E — integrator note only (no change to seeds now).

- **E1 (F12):** update the fragment's proposed-lesson integrator note to name **lesson 10** specifically (recurrence-tally, not mint), and record the consequence: L10 → 2 instances; the next recurrence mandates a structural control, and #846 is that control already in flight.

---

## Drafts

### Draft B1+F10 — replacement for plan line 67 (the tenet bullet)

> **Durability without distribution is half the job (the anti-drop tenet).** Recording work durably — a ticket comment, the outcome ledger, a doc — does NOT guarantee the next actor acts on it; the board must also DISTRIBUTE it into the pull view they read. **Cross-session continuity is a property of the durable board, never of session memory or a verbal handoff.** Two consequences the method enforces: (1) every defer/handoff writes BOTH halves — the durable record AND the queue placement with its unblock condition; (2) **resource-gated deferral is a first-class, still-visible marking** — a card that is Ready-in-principle but waiting on a RESOURCE the board can deterministically observe (a GPU/lean-box window, disk space, model residency) carries a **registry-keyed resource label** (set by code, never model free-text), stays in the Ready bucket, is never dropped from the pull computation, and becomes pull-eligible again automatically the cycle after its resource frees (distinct from the DoR ticket-dependency blocker above, which correctly gates *out* of Ready). Two neighbours it is NOT: a card blocked on other WORK (a wheel rebuild, a dependency PR) is a **DoR blocker relation**, not a resource marking; a card waiting on an EXTERNAL event the runtime cannot observe without egress (an upstream fix landing) cannot be auto-re-surfaced by design — it is carried as an explicit **human-check line in the briefing/digest** at a bounded cadence, honestly, rather than falsely promised as automatic. The resource-predicate vocabulary is a **closed, enumerated registry** — each key shipping a deterministic evaluator over host/board state, an unknown predicate refused at staging (fail-closed) — the "gate as JUDGE, model as SIGNAL" law applied to the anti-drop mechanism itself. Origin: the 2026-07-11 #769 catch — the follow-up benches were durable on their ticket but absent from the pull queue, one forgotten verbal handoff from silent loss across the night→next-daytime-GPU session chain.

### Draft C1 — new sibling bullet, inserted directly after the anti-drop bullet

> **Scaffolding is retired by the thing that replaces it (the paired anti-bloat tenet).** Distribution's counterweight: every interim mechanism, board structure, or one-off doctrine the method introduces is created CARRYING its supersession predicate — the condition under which it is no longer needed and the thing that will replace it. The change that ships the replacement owns the retirement: executing it (deleting the scaffold, the resource label, the interim queue entry) is part of that change's Definition of Done, exactly as shipping-closes-the-ticket makes closure part of the merge. This generalizes the #859 pattern — which already names its own supersession by the Coordinator board — into a standing rule, so the board accretes structure and retires it symmetrically. Distribution without curation is how a signal surface becomes noise.

### Draft A2+F4 — replacement for plan line 90 (Phase C2 durability line)

> - Information durability AND distribution (the anti-drop tenet, applied): the per-project outcome ledger append + ticket comments are the DURABLE half; distribution is the board/queue placement the next actor pulls from — the harvest/hygiene steps write BOTH halves, never a comment in place of a queue entry. Feed the #712-lineage WinUI typed progress feed.

### Draft A1 — #842 description, append inside item (b)

Insert immediately before `digest=standup, briefing=replenishment` in item (b):

> ticket-as-context-home; **the anti-drop tenet (durability without distribution is half the job) and its paired anti-bloat tenet (scaffolding is retired by the thing that replaces it) — see plan §Kanban + this ticket's requirement comments: every defer writes both the durable record AND the queue placement with its unblock condition; resource-gated deferral is a first-class still-visible MARKING via a closed registry-keyed resource-label vocabulary (deterministic evaluators, fail-closed on unknown; label set by code; card stays in Ready; pull-eligibility not bucket membership is suspended); work-blockers → DoR relations, external-event waits → a human-check briefing line; gated time excluded from stall/aging alarms but shown as a distinct gated-inventory digest line while age still accrues for catch-up ordering; every interim scaffold carries its supersession predicate and the superseding change's DoD executes the retirement**;

### Draft A1 — #846 description, appends

Append to scope item (1), after `per-project WIP caps optional policy on top`:

> **Resource-gated deferral (anti-drop tenet): a card waiting on a registry-evaluable resource carries a code-set resource LABEL, stays in the Ready bucket, is never dropped from the pull computation, and becomes pull-eligible again the cycle after its resource frees. Closed predicate registry with deterministic evaluators (unknown predicate refused at staging, fail-closed); predicate value registry-validated, never model free-text (suppression-attack closure). Gated time excluded from stall/aging alarms, shown as a distinct gated-inventory digest line; age still accrues for catch-up ordering.**

Append to scope item (2), after the work-origination sentence:

> **Dispatch-run residuals are a first-class replenishment source: a structured `residuals[]` field on the run report (INTERLOCK with #740/M2 run-report schema — see plan item 15) is populated at run end and harvested into staged proposals — follow-ups never left to die in the transcript. The coder/critic layer owns POPULATING the field (a report-contract obligation enforced by the fleet gate — NOT a behavioral prompt line); the harvest step consumes it.**

Append to the ACCEPTANCE SHAPE (replacing/expanding the resource-gating fixture wording):

> **resource-gated fixture lock asserts BOTH halves — (a) while gated: the card is present in the pull computation, visible in the digest's gated-inventory line, and INELIGIBLE to pull; (b) the cycle after its resource frees: ELIGIBLE and correctly class-then-age ordered (presence is the invariant, eligibility is what flips — a drop-and-re-add implementation that opens a loss window is REFUSED by the lock); an unknown/free-text resource predicate refused at staging; a dispatch `residuals[]` entry provably becomes a staged proposal.**

### Draft D1 — handoff-brief-template.md, new required line

Add as a bullet under the "Scope remaining + closure criteria" section (or a short dedicated block):

> **Deferred / blocked items — both halves required.** Every item this brief defers or leaves blocked carries BOTH: the durable record (its ticket / a CURRENT-STATE comment) AND a queue placement in the forward view the next actor reads (#859 today; the Coordinator board when live) with its unblock condition. **List the queue entries here.** A deferral mentioned only in this brief's prose is not distributed and will drop — that is the #769 failure this line exists to prevent.

### Draft E1 — fragment proposed-lesson integrator note (replacement)

> *(Integrator: this is a **recurrence of lesson 10** — "continuity of intent across agents is a file-system property, not a memory property; write it down where the next session will read it, not where you will remember it" — sharpened one notch: the #769 information WAS written down, but where the author could point to it, not in the pull view the reader reads first. Add a dated recurrence-tally to lesson 10; do NOT mint a new number. Consequence to record: lesson 10 reaches its SECOND instance — the next recurrence mandates a structural control, and the #846 resource-gated-deferral mechanism is that control already in flight. Origin incident: the #769 follow-up-benches queue-drop, 2026-07-11.)*

---

## LA-facing (what actually needs a decision, vs what I own)

Per the operating model (I own the technical HOW; the LA owns scope/impact/posture and never gets asked a technical encoding question):

- **A, B1–B4, B6, C1, E1** — sound refinements, my recommendation is apply all. These are the technical HOW; no posture call needed. One go/no-go covers them.
- **B5 (residuals interlock)** — the one genuine **scope flag**: it adds a `residuals[]` field to the #740/M2 run-report schema, so it couples this refinement into the sibling M2 program's surface. Recommendation: name it as an interlock in the #846 requirement now (design-only, costs nothing), and let the implementing sessions sequence it per plan item 15. Not a blocker; flagged for visibility.
- **C2** — optional, lower priority; recommend as a small ADR-039 note.
- **D1** — needs a commit to a tracked file. Recommend applying on the next quiet tree with the LA's word.

**Nothing here is applied.** On the word, A + B + C1 + E1 apply as durable-board + plan-doc edits (no code, no gate run needed); D1 waits for a quiet tree.
