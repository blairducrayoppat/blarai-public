# ADR-039 — The Coordinator: Self-Governance Boundary, Agent Architecture, and Project-Management Doctrine (C0)

> **PROMOTED FROM DRAFT — LA CONTENT-REVIEW COMPLETE (2026-07-12).** The Lead Architect read this ADR in
> full and approved it ("I read adr-039 and I love it! approved! proceed!"), promoting it from the `DRAFT_`
> file to this final `ADR-039-Coordinator-Self-Governance-Boundary.md`. The two spots the draft flagged for
> review are **coordinator-owned operational dispositions, not doctrine gaps** (per the LA's own-the-HOW
> directive — a non-technical operator should not be asked to pick a metric definition): §2.14.3 / §5.2
> (resource-label clearing) adopts the **"ignored outside Ready"** reading as the simpler, deterministic
> one, consistent with the already-decided eligibility-not-membership encoding; §2.14.2 / §5.1 (the
> flow-metric "age" definition + its timestamp source) is **deferred to the C1/C3 metrics build**, where the
> Vikunja-transition-history capture mechanism is chosen with implementation context in hand — recorded
> there as an open C1/C3-kickoff decision, both options on the table, with no doctrine dependency. No
> implementation is authorized by this document — it is C0, doctrine-only, exactly as scoped.

**Status:** ACCEPTED 2026-07-11 (design doctrine; LA design-approval recorded at `#841` c.1812 "DESIGN
APPROVED... design-only, no implementation authorized... priorities per c.1815: C0/SG urgent, all other
phases high"; this document is the formal ADR record the approval authorized C0 to produce). **Docs-only —
changes no live behavior.** Every mechanism this ADR describes ships in a later phase (C1–C5, `#843`–`#847`)
or the cross-cutting `#848`/`#855`, each **dormant behind `[coordinator]` config flags**, default off.
**Amendment 1 (2026-07-12):** adds the scoped `blarai-coder` Vikunja documentation account
(per-coding-project) — see §Amendment 1 at the end of this ADR. Docs-only; no live behavior change.
**Author:** design specialist subagent (Claude Sonnet 5) for Lead Architect (Blair) review — formalizing
already-approved doctrine; no new policy invented in this pass (see the DRAFT-status note above for the two
exceptions, both flagged, neither invented-and-hidden).
**Deciders:** Lead Architect (blarai); Orchestrator (facilitation).
**Builds on:** ADR-034 (model-swap driver — the propose→dispose pattern and the containment model `#848`
control 1 mirrors), ADR-035 (Acceptance Layer — "model proposes, deterministic ruler disposes," mandatory
confirm, never rubber-stamp an unrun check), ADR-036 (Operator-Feedback-Memory Governance — the
`propose_preference` stage-then-confirm template §2.4 reuses, and the cross-repo cf-program **ADR-022
self-modification-surface taxonomy** this ADR stamps a second time in §2.16), ADR-023 (Provenance-Based
Trust Model — the `RiskTier.GUARDED` tier, the `#570` AO→PA tool-dispatch mediation, the CAR/`ActionVerb`/
`AdjudicationDecision` schema §2.6 maps onto, the `UNTRUSTED_*` provenance tiers §2.7 extends), ADR-027 §1a
(the one-door egress seam and the loopback-is-not-egress baseline §2.3 relies on), ADR-018 (TPM trust root —
the signed-manifest machinery control 7 extends beyond model weights).
**Relates to:** Vikunja `#841` (epic — Coordinator program C0–C5), `#842` (this ticket, C0 — ADR-039 +
DECISION_REGISTER row), `#848` (SG — implements the seven controls this ADR names), `#843` (C1 read
surface), `#844` (C2 lifecycle coordination), `#845` (C3 heartbeat), `#846` (C4 two-lane work origination),
`#847` (C5 graduated autonomy), `#855` (CV — shadow-mode validation harness, the go-live gate for C3/C4),
`#749` (the vikunja_bridge build this ADR explicitly amends the "no ticket tools" invariant of), `#770`/`#792`
(ADR-036 `propose_preference` — the staging template reused), `#740` (M2 fleet maturation — sibling program,
shared `shared/fleet/` surface, coordinates via ticket not merge order).
**Design doc (SSOT):** `docs/research/coordinator-program-plan-2026-07.md` (LA-approved 2026-07-11, `#841`
c.1812; adversarially reviewed same day, verdict SOUND-WITH-GAPS, 13 findings, all dispositioned into the
doc revision — call this **the SG-boundary review** below, to distinguish it from a second, later review).
**Research + adversarial-review record:** `docs/research/coordinator-self-governance-research-2026-07.md`
(external-literature synthesis + the SG-boundary review's 10 open questions, Q1–Q10). **A second,
narrower adversarial review** — of the Kanban durability-without-distribution tenet specifically — is
recorded at `docs/reviews/durability-distribution-tenet-adversarial-review-2026-07-11.md` (its own F1–F13;
disposition on `#842` c.1833). **Operator-facing companion (plain language):**
`docs/research/coordinator-operator-guide-2026-07.md`.

---

## 0. What this ADR is and is not

This is the **C0 doctrine ADR** for the Coordinator program: the record of *what BlarAI's project-coordinator
role is, what it may never do, and what governs it*, before a line of implementation code exists. It is
**not** a design document — the design already happened (the SSOT plan doc, LA-approved 2026-07-11,
adversarially reviewed the same day) — this ADR **formalizes that approved design into the project's
governing-decision record**, in the same role ADR-037 played for the grading/integration machinery and
ADR-038 for the model-evaluation protocol: a later phase implements *under* this doctrine rather than
re-deriving it.

Everything below traces to one of: the SSOT plan doc; the research/review record; four requirement batches
LA-added to `#842` on 2026-07-11/12 (comments c.1814, c.1822, c.1833, c.1838 — cited inline at each
subsection they ground); or the seven downstream phase tickets, which restate scope in implementation terms
and occasionally sharpen a spec the plan doc left general. Where a source left a genuine open question
rather than a decision, this ADR says so explicitly (§2.14, §5) rather than resolving it — formalizing
approved doctrine is not license to invent the parts that were never decided.

## 1. Context

BlarAI's operator (the Lead Architect) has defined the mature role the AI side of a coding effort must
eventually fill: not just executing tasks, but **coordinating the entire effort** — monitoring live
processes each cycle, keeping the work queue full ("a quiet queue is a broken queue"), taking direct action
in the gaps, running Vikunja as a living single source of truth, making information durable *and*
distributed, and proactively finding/assigning the next work — all behind periodic, reasonable
LA-approval gates. This program maps that role onto BlarAI itself, in BlarAI's own idiom: fail-closed,
deterministic-ruler, approval-gated, loopback-only.

BlarAI has two structural gaps against that role today: **no heartbeat** (it is entirely turn-driven —
nothing wakes to check monitored processes or queue depth) and **no work-origination loop** (nothing
harvests outcomes, proposes next work, drives tickets to completion, or notices an idle fleet). Closing
them is what Phases C1–C4 build.

Designing toward that role surfaced a latent risk the LA named directly (`#841` c.1798, 2026-07-11,
second governance decision of the session): **"BlarAI must not be able to modify its own code,
configuration, instructions, policy, models, or governing documents."** A coordinator that proposes work on
BlarAI's own backlog sits one short step from a coordinator that dispatches a coding fleet *against* BlarAI
itself — the industry's recognized "agentic self-modification" risk class (Pillar Security's taxonomy;
documented incidents of agents editing their own timeout logic or self-improving agents rewriting their own
codebases to game benchmarks — full citations in the research doc §1). The driver for treating this as
constitutional rather than a tunable is stated by the LA on the same record: BlarAI is eventually intended
for **non-technical operators** building their own software, so every control must be **structural and
default-deny**, never dependent on operator vigilance or expertise. A rule a careful operator could work
around is not a control.

The design that answers this — the two-domain model and seven structural controls in §2.1–§2.2 — has direct
precedent in the field (mapped in full in the research doc, summarized here because it is *why* the
doctrine takes this shape rather than a lighter one): OWASP's LLM06 "Excessive Agency" decomposition
(complete mediation — never let the model decide whether its own action is authorized); Google DeepMind's
CaMeL pattern (control flow derived only from trusted input; untrusted data can shape content, never target
selection); Meta's "Agents Rule of Two" (never combine untrusted input + a sensitive system + autonomous
state change in one uncontrolled step); and the Darwin Gödel Machine research line's standing rule that **the
judge must not be improvable by the judged** — the frozen-evaluator principle this ADR applies to the
fleet's own verify-gate and oracle machinery, not just to BlarAI's runtime code.

## 2. Decision

### 2.1 The two-domain model — governed core vs. workspace

*(`#841` c.1798, the LA's constitutional decision; `coordinator-program-plan-2026-07.md` §Self-governance
boundary.)*

The system is split into two domains with **structurally different write rules**, effective at every phase
of this program and every autonomy level, with no exception:

**The governed core** — everything that defines what BlarAI *is* and how it behaves. BlarAI has **zero
write path** to any item in this list, in any phase, at any autonomy level:

1. Runtime code (`shared/`, `services/`, `launcher/`, `tools/`) and its tests.
2. Configuration — `default.toml` and every `[coordinator]`/autonomy/policy flag.
3. System prompts, Policy Agent rules, PA governance (`pgov`) policy, tool registrations, risk tiers.
4. **The operator-preference tier and any prompt-injected memory** — the `propose_preference` staging path
   (ADR-036) writes into future system prompts, ADR-036's own classification calling it the highest-risk
   auto-injected surface in the agentic-memory literature; a coordinator-role model instance must not carry
   that write-staging tool, and its proposals (if any ever existed) would pass the same staging-time ruler
   this ADR requires of every governed-core-adjacent write.
5. **The knowledge substrate and session memory insofar as they are injected as standing instructions** —
   the "operational memory" self-instruction leg of the self-modification taxonomy (§2.16).
6. Model weights, signed manifests, and signing keys.
7. Governing documents — ADRs, `DECISION_REGISTER.md`, CLAUDE.md-tier doctrine, and the Coordinator program
   plan itself.
8. The coordinator's own ruler definitions, forbidden-target set, proposal-queue mechanics, the autonomy
   flag ladder, **and the heartbeat's own trigger definition** (the timer/task that wakes it, §2.13.1).
9. **The acting limb's judge** — the agentic-setup fleet's verify-gate, oracle machinery, and harness config
   (`opencode.json`, agent definitions). The judge must not be improvable by the judged (the Gödel-machine
   frozen-evaluator rule); severance is enforced from **both** sides — BlarAI cannot dispatch against the
   fleet's own gate/oracle files, and the fleet's containment does not trust BlarAI to police itself either.
10. The proposal-staging store itself — appended to only via the sanctioned staging API, never by direct
    write.

**The workspace** — what BlarAI coordinates and, with approval, acts on: target project repos inside the
configured projects directory, their fleet jobs, and Vikunja ticket data.

Changes to the governed core travel exactly **one channel**: the human-governed development path (the Lead
Architect plus Claude dev sessions, feature branches, gates, ceremonies — the same path every other ADR in
this repo travels). BlarAI may *observe* its own backlog and *advise* on it; it may never *execute* against
itself. This is the fence the rest of this ADR, and every phase built under it, exists to make real rather
than aspirational.

### 2.2 The seven structural controls

*(plan doc §Self-governance boundary; sharpened by the SG-boundary adversarial review and restated in
implementation terms at `#848`.)* Each control is designed to become a **regression-locked** mechanism at
`#848` implementation; none may rely on operator vigilance.

1. **Self-target severance at every action chokepoint — identity-based, not name-based.** The existing
   anchor, `_FORBIDDEN_REPO_ROOTS` at `shared/fleet/dispatch.py:40` (today: a casefolded name-component
   check plus `resolved.relative_to(projects_dir)` containment — refuses `BlarAI`/`.openclaw` as fleet
   targets), is **generalized and strengthened**: every coordinator action class — redispatch proposals,
   work-origination proposals, any future class — passes a governed-core target check **at staging time**,
   re-run **at execution time** (closing the TOCTOU window named in §2.12.4). Membership is decided by
   **canonical realpath containment** (symlinks, junctions, worktrees, and renamed clones resolved) — never
   by path-component name matching, which a renamed clone or junction can evade (SG-review F5). The
   execution **target** of any proposal is separately **re-derived by deterministic code from trusted,
   structured fields** (e.g., a validated ticket-carried repo id checked against `projects_dir`) — **never**
   taken from model free text, so untrusted content can shape a proposal's *content* but can never select
   its *target* (the CaMeL property). A proposal failing either check is refused before it reaches the
   proposal queue. The forbidden-target set is config-defined but **not modifiable via any BlarAI surface**
   (controls 4 and 7 make that hold).
2. **Self-work is advisory-only.** BlarAI-originated tickets about BlarAI itself carry a **structural**
   provenance marking, never a text convention (a text marker is forgeable by any injection that can author
   a comment) — the dedicated **`blarai-coordinator` Vikunja account's immutable `created_by`** (SG-review
   F13: the runtime bridge today shares the `blarai` account with the MCP server and all human writes, which
   makes `created_by` provenance inert as designed; §2.12.1 names the fix) **plus a label set by
   deterministic code**. BlarAI's own dispatch path refuses these tickets categorically, even post-approval:
   approval routes a self-advisory item to humans, never to the fleet. Closure of these tickets is a
   **human-dev-channel responsibility** — exempt from any BlarAI auto-close and from the shipping-closes-
   the-ticket automation, which would otherwise leave them silently drifting.
3. **Instruction-channel integrity.** Ticket/comment content BlarAI authors is provenance-marked, and every
   consumer — including BlarAI itself on a later read, and Claude dev sessions — treats it as untrusted
   proposal-grade input, closing the loop where the ticket store could become a covert self-instruction
   channel.
4. **Configuration immutability from inside.** No tool, proposal class, or preference-write surface
   (`propose_preference` explicitly included, SG-review F3) may read-write any `[coordinator]`, autonomy,
   policy, or security config. Flag changes are operator-only, made outside BlarAI; ladder flips remain LA
   ceremonies with `DECISION_REGISTER` rows (§2.10).
5. **Multi-operator readiness.** The autonomy ladder ships **fully OFF** on any new installation; go-live
   ceremonies are owner-level actions, not user-level; the governed-core boundary is identical for a
   non-technical operator — nothing they can click hands BlarAI a write path to itself. Approval UX is sized
   for that operator: proposals render as **outcomes in plain language**, batch size is bounded, and
   high-impact classes require per-item confirmation — batched approval must never become a rubber stamp
   (approval fatigue is a vigilance failure, and vigilance is disallowed as a control by this ADR's own
   premise).
6. **Boot-time boundary canary + refuse-to-start.** At every backend boot, a deterministic self-check probes
   that the coordinator surface **cannot** reach a governed-core write path (the OpenParallax canary
   pattern). Any probe *succeeding* means misconfiguration, and the coordinator **refuses to start** — the
   same fail-closed idiom the egress guard already uses. This proves the **negative** (cannot reach what it
   must not); §2.14.6 adds the paired **positive** probe (can reach what it needs).
7. **Signed policy verification — the out-of-process anchor.** The forbidden-target set and the
   `[coordinator]`/autonomy/policy config are **signature-verified at boot**, extending the existing
   signed-manifest machinery (ADR-018/ADR-021) beyond model weights — so a corrupted- or patched-on-disk
   policy file is *detected*, not trusted. This is the enforcement layer that does not depend on human code
   review, and it is the control that makes the boundary hold for a non-technical operator, for whom the
   dev-channel write barrier does not meaningfully exist (SG-review F1). **Claim discipline (§2.17): until
   control 7 ships, the boundary is honestly stated as "safe under expert operation," never "safe for
   distribution."**

**Also in `#848` scope, adjacent to the seven controls:** a **live adversarial probe** of the OpenCode
coder-harness permission ring (attempt a governed-core edit through the coder; SG-review Q9/Q10 — documented
Windows enforcement bugs, upstream opencode issues #16126/#6396/#8832, mean this ring is **defense-in-depth
only, never load-bearing**); and a **deterministic ACP `session/request_permission` responder** that refuses
governed-core-touching tool calls mid-run — **never the 14B**, which would make the responder itself an
injectable judge — with **wedge-safe refusal**: a bare refusal can hang an ACP agent on an unreturned tool
call, so refusal translates to a clean cancel + run teardown + a `PARKED-HONEST` outcome, with its own
timeout (SG-review F10). Together with staging-time refusal (control 1, *before*) and the worktree/merge
gate (*after*), this makes **three rings**: before, during, after. No single ring is trusted alone.

### 2.3 Loopback-is-not-egress, preserved

The Coordinator introduces **zero new egress**. `shared/fleet/vikunja_bridge.py` (`#749`) is
**loopback-pinned** (`assert_loopback`), **fail-soft** (a 2-second cap, swallowing errors rather than
degrading chat), and **outcomes-only** (anti-firehose — never a per-heartbeat comment). Its socket transport
lives in `tools/dispatch_harness/vikunja_http.py`, **outside** the egress import-scan
(`test_no_external_egress.py`); `shared/` itself imports only `urllib.parse`. This is the same
bridge/transport split ADR-027 §1a already relies on for `guarded_fetch` — loopback traffic to a
local-only service (Vikunja on `localhost:3456`) is not "egress" under ADR-027/ADR-020's allowlist model
(loopback was always inside the base allowlist), and the **one-network-client invariant** (`httpx` imported
by exactly one module, `guarded_fetch`) is untouched: the Coordinator's read surface (C1, `#843`) extends
`vikunja_bridge` with more read operations over the **same** loopback/fail-soft/transport-split pattern, not
a second network path.

### 2.4 The `#749` invariant amendment — read-only GUARDED ticket tools, amended explicitly

`#749` shipped BlarAI's Vikunja integration under the invariant that "the coder/planner models get **no**
ticket tools." This ADR **amends that invariant explicitly, not silently**, exactly as `#841` c.1798
required: the Coordinator role (§2.5) is given **read-only** GUARDED-tier ticket tools
(`project_status`/`list_open_work`, landing at C1, `#843`), following the same runner-seam pattern as the
existing `search_knowledge`/`web_search` GUARDED delegates in `services/assistant_orchestrator/src/tools.py`
(`RiskTier.GUARDED` in `_REGISTRY` + `pgov.TOOL_CALL_ALLOWLIST`, `#570` per-dispatch PA adjudication
unchanged). **All writes stay deterministic reporting code or approval-staged proposals** — the amendment is
narrowly a *read* carve-out; it grants no write path, and it does not touch the AO's own tool surface (the
Coordinator is a separate role, §2.5, with a structurally smaller tool surface than the AO's). Recording
this amendment here, on the record, rather than letting `#843` quietly widen `#749`'s scope in a commit
message, is itself part of the "never silently" requirement.

### 2.5 Agent architecture — the third resident role, and the role-charter template

**The Coordinator is a distinct agent role on the shared 14B**, exactly as the Policy Agent and the
Assistant Orchestrator are distinct roles on one model today: its own system prompt, its own (minimal) tool
surface, its own adjudication identity — same weights, same GPU residency, **zero new RAM**. This is not a
new model or process: a separate model is neither affordable under the 31.323 GB ceiling nor architecturally
needed (the roles never run concurrently with different weights), and the multi-agent literature supports
role separation via task-specific system prompts on one shared model as a recognized pattern (research doc
§11).

Why a separate role rather than more duties for the AO:

1. **Tool-surface minimization** — the Coordinator carries **only** read-only ticket/state tools plus
   proposal staging; it **structurally lacks** the AO's `propose_preference`, image-generation, and chat
   tools (SG-review F3 demanded exactly this separation).
2. **Prompt integrity** — a PM persona carrying flow-policy instructions must not share a prompt with a
   conversational assistant whose context is user-shaped.
3. **Auditability** — coordinator actions carry a distinct identity end-to-end: PA adjudication (§2.6), logs,
   and ticket authorship (the `blarai-coordinator` account, §2.12.1) all trace to the Coordinator role
   specifically, never blended with AO traffic.

The AO remains the conversational front door — `/coord …` commands route through it, and it renders digests
and briefings in chat — but **never improvises a PM answer itself** (role non-overlap, §2.14.7).

**The role-charter template** *(`#842` c.1838, item E4(b)).* Because PA/AO predate any formalized pattern
and were each hand-written, the arrival of a third role is the natural factoring moment: every resident role
(PA, AO, and now Coordinator — and any future Nth role) is required to instantiate the same six-field
charter, so adding a role becomes an **additive instantiation**, not a bespoke prompt plus edits to every
existing one:

| Field | What it states |
|---|---|
| **Identity & mandate** | What this role is for, in one paragraph; what it is *not* for. |
| **Tool surface** | The exact registered tool set (by name), each tagged with its `RiskTier`; anything **not** listed is structurally absent, not merely unused. |
| **Provenance posture** | How this role's own output is provenance-marked for downstream consumers, and how it treats *inbound* content's provenance (which tiers lock which tools). |
| **Refusal / escalation** | What this role refuses outright, what it escalates, and to whom (human, PA, another role). |
| **Adjudication identity** | The identity this role presents to the Policy Agent / audit chain — distinct per role, never blended. |
| **Non-overlap statement** | Which peer roles exist, and an explicit statement of what this role never does because a peer owns it. |

The Coordinator's own charter is instantiated in full at C1 (`#843`); retrofitting PA's and AO's existing
prompts into the same six fields (documentation only — no behavior change) is a **named residual**, not
scoped into this program (§5).

### 2.6 PA adjudication verbs for coordinator action classes

*(`#842` item (i); ADR-023's CAR schema, `shared/schemas/car.py`.)* Coordinator dispatches are adjudicated
**first-class**, not as AO look-alikes: every coordinator action that reaches the Policy Agent is reduced to
a `CanonicalActionRepresentation` carrying the Coordinator's own `source_agent` identity (§2.5, distinct from
the AO's), and is adjudicated to one of the existing `AdjudicationDecision` values (`ALLOW`/`DENY`/
`ESCALATE`) — **no new adjudication tier is introduced**. The existing `ActionVerb` enum
(`READ`/`WRITE`/`EXECUTE`/`DELETE`/`QUERY`/`DISPATCH`/`EGRESS`) already covers the Coordinator's action
classes without extension:

| Coordinator action class | `ActionVerb` |
|---|---|
| Ticket/board/state reads (`/coord status`, flow-metric snapshots) | `READ` / `QUERY` |
| Redispatch of an approved workspace proposal | `DISPATCH` (rides the **same** adjudication path `/dispatch` already uses) |
| Proposal staging (append-only, via the sanctioned staging API) | `WRITE` — scoped to the **staging store only**, never governed-core; the CAR's `resource` field names the staging store explicitly so a coordinator-issued `WRITE` CAR targeting anything else is a schema-level impossibility, not a policy call |

`EXECUTE`, `DELETE`, and `EGRESS` are **not** verbs any coordinator action class emits — the Coordinator has
no execution surface of its own (it delegates execution to the existing `/dispatch` path, which is
adjudicated under its own established CARs), no delete authority, and no egress (§2.3). A coordinator CAR
requesting any of those three verbs is, by construction, malformed and fails closed on `is_complete()`/PA
adjudication rather than being a live decision this ADR must make.

### 2.7 Untrusted-input posture for ticket, run, and state content

Everything the Coordinator reads — ticket titles/descriptions/comments, fleet run reports, project files —
is **untrusted** by the same provenance model ADR-023 already applies to documents and web results: it may
influence a proposal's *wording*, never its *target* (§2.2 control 1) or, per the tenet-review disposition
(§2.9), a gating *predicate's value* (extended CaMeL property). `/coord status` output rendered into the AO
conversation enters under the **`UNTRUSTED`** provenance tier — datamarked, GUARDED-tool-lock-eligible — so
a hostile ticket title cannot become a chat-level injection just because it passed through the Coordinator
first (`#842` item (f); `#843` scope). Content BlarAI itself authors on a ticket is separately
provenance-marked per §2.2 control 3, so a later read of its own prior output is never mistaken for operator
instruction.

### 2.8 The project-management method — Kanban with Scrumban cadences

*(plan doc §"The project-management method"; LA directive 2026-07-11, evidence in the research doc §11–12.)*
Governance says what the Coordinator may not do; this section says what it actually **does** as a project
manager. The method is **Kanban** — continuous flow, no fixed sprints or roles — chosen over Scrum
deliberately: Scrum's sprints synchronize *human teams*, which this system does not have; a solo operator
plus AI executors is a continuous-flow shop. The decisive technical fit: every core Kanban mechanism is
**deterministically computable** from Vikunja timestamps and states — the method itself obeys "gate as
JUDGE, model as SIGNAL."

**Vikunja is the PM substrate, mapped concretely:**

- **Workflow = Vikunja kanban buckets per project:** `Backlog → Ready → In Progress → In Review/Verify →
  Done`. Card movement is driven by real events (dispatch started → In Progress; oracle GREEN + merged →
  Done), never by model opinion.
- **Definition of Ready / Definition of Done as deterministic gates.** A ticket enters Ready only when a
  code-checked checklist passes (acceptance criteria present, target repo valid under the SG ruler, no
  unresolved blocker relation); Done only via the existing GREEN-plus-oracle-passed close. The Coordinator
  *proposes* refinements to get Backlog items Ready; it never fakes readiness.
- **WIP limits, ruler-enforced.** Per-stage work-in-progress caps are config policy; the hardware itself sets
  the deepest one (one dispatch at a time — the 14B⇄30B swap is exclusive), and the ruler refuses a pull that
  would breach a limit.
- **Classes of service via labels + due dates, with a deterministic pull policy:** `Expedite` (jump the
  queue, one at a time), `Fixed-date` (pulled early enough to make the Vikunja due date), `Standard`
  (FIFO — oldest Ready item pulls first), `Intangible` (maintenance/docs, pulled when nothing else is Ready).
  Pull **order is computed by code**; the model only drafts *proposals to add or reclassify* work, which the
  operator approves. Pull is **global across projects** (the dispatch WIP=1 is global — one GPU), ordered
  class-then-age, with a starvation guard so an Expedite-heavy project cannot indefinitely starve others
  (Standard items age into priority; §2.12.8).
- **Flow metrics, computed each heartbeat cycle** from ticket timestamps: cycle time, throughput, work-item
  age, aging-WIP. Stall detection becomes principled (an item whose age is a statistical outlier for its
  class); the digest reports flow, not vibes.
- **The ticket is the context home** — proposals, run outcomes, decisions, and evidence live as comments on
  the ticket they concern, so an agent or human picking up a card gets its whole history with it.
- **Cadences (the Scrumban borrowings):** the heartbeat digest is the standup analog; the periodic briefing
  is the replenishment meeting (the operator's approval gate); the existing monthly retrospective absorbs
  flow-metric trends. **No sprints, no story points, no velocity theater** — rejected on the record as the
  wrong shape for a solo-operator, continuous-flow shop.

### 2.9 The durability-without-distribution tenet, and its paired scaffolding-retirement tenet

*(`#842` c.1822, hardened by the tenet-review disposition at c.1833.)* Recording work durably — a ticket
comment, the outcome ledger, a doc — is only **half** the job; the board must also **distribute** it into
the pull view the next actor actually reads. **Cross-session continuity is a property of the durable board,
never of session memory or a verbal handoff.** Origin: the 2026-07-11 `#769` catch, where follow-up work was
durable on its ticket but absent from the pull queue — one forgotten verbal handoff from silent loss across
a night-to-next-day session chain.

Two enforced consequences:

1. **Every defer/handoff writes both halves** — the durable record *and* the queue placement with its
   unblock predicate.
2. **Resource-gated deferral is a first-class, still-visible marking — not a new bucket or lane, and not a
   blocker relation.** A card that is Ready-in-principle but blocked on a resource window (e.g., a
   GPU-daytime/lean-box window) carries a registry-keyed `Resource:*` label set by deterministic code, and
   **stays in the Ready bucket**: presence in the pull computation is the invariant, and only pull
   **eligibility** — never bucket membership — is suspended (tenet-review F2: a relation-encoded gate would
   be de-Readied by the Definition-of-Ready "no unresolved blocker relation" check and vanish from the pull
   computation entirely, which is inert, not gated).

**The predicate vocabulary is a CLOSED registry**, enumerated here, each entry shipping with a deterministic
evaluator over host/board state (initial candidates, bounded by what C1's snapshot composer can actually
read: `gpu-window`/lean-box, `disk-space`, `model-residency`). **Marking a card with an unregistered
predicate is refused at staging** — fail-closed (tenet-review F1: of the three original examples, only the
GPU window was genuinely host-evaluable; "a wheel rebuild" is a **ticket dependency** — the existing DoR
blocker relation, which correctly gates a card *out* of Ready — and "an upstream fix landing" is an
**external event with no host-evaluable signal**, which the runtime is structurally forbidden from polling
for under the zero-egress mandate; it gets a bounded human-check line in the briefing/digest, never a false
automation promise). **Predicate registry membership and evaluators are governed core** (§2.1 item 8) —
config-immutable from inside; **predicate values are registry-validated at staging and never taken from
model free text** (tenet-review F11 — the CaMeL property extended from action targets to gating predicates,
closing a card-suppression injection vector).

**Metrics decisions (tenet-review F8):** gated time is **excluded** from stall/aging alarms — reported
instead as a distinct **"gated inventory"** digest line, giving visibility without alert fatigue — while age
still **accrues** for pull ordering, so a released card catches up rather than re-queuing at the back
(resetting age on release was considered and rejected as unfair to a card that waited legitimately). The
quiet-queue tripwire (§2.13.4) requires **resource-eligible** Ready work specifically: an all-gated Ready
column is reported as gated inventory, **never** as a quiet-queue alarm.

**The paired tenet (LA-raised counterweight, tenet-review F13): "scaffolding is retired by the thing that
replaces it."** Distribution taken naively becomes sprawl, and sprawl is its own signal loss — so this tenet
is a matched pair with durability-without-distribution, not a standalone addition. Every interim mechanism,
board structure, or one-off doctrine is created **carrying its own supersession predicate** (generalizing the
`#859` queue-ticket pattern: "superseded once the board ships"), and the superseding change's Definition of
Done includes **executing** the retirement — the structural sibling of shipping-closes-the-ticket, applied to
scaffolding rather than tickets. The kanban substrate-setup migration (§2.12.11) runs **bidirectionally**:
discover-or-create *and* flag-orphans (labels/buckets/filters no current doctrine references) as digest
curation candidates, with removals human-approved.

### 2.10 The five phases, and the graduated-autonomy ladder

Each phase is independently shippable and ends **dormant until flag**:

- **C0 — Doctrine** *(this ADR + the design doc + the DECISION_REGISTER row, `#842`).*
- **C1 — Read surface** *(turn-driven, advisory, `#843`).* Extends `vikunja_bridge` with read ops; the
  deterministic work-state snapshot composer; `/coord status` + the GUARDED read-only tools (§2.4); the
  Coordinator role's first instantiation (§2.5).
- **C2 — Lifecycle coordination** *(event-driven, deterministic, `#844`).* Ticket hygiene on existing
  dispatch events: stall detection, PARKED-HONEST → staged redispatch proposal, close-on-GREEN discipline
  extended with dated "CURRENT STATE" comments on partial lands; promotes stall-kill patterns from
  `tools/dispatch_harness/monitor.py` into driver-integrated checks.
- **C3 — The heartbeat** *(the genuinely new surface, `#845`).* A bounded wake cycle, deterministic-first,
  swap- and power-aware; read-and-propose only; the quiet-queue tripwire (§2.9); at most one digest per
  cycle, operator-surface-only, **never** a Vikunja comment.
- **C4 — Work origination** *(model proposes, ruler disposes, LA approves, `#846`).* BlarAI reads the whole
  Vikunja workspace plus the vision docs and drafts next-work proposals into staging, split into the **two
  lanes** §2.2 control 2 already names: workspace proposals (executable via BlarAI's own dispatch path) and
  self-advisory proposals (routed exclusively to the human-governed dev channel). The periodic **coordinator
  briefing** is the batched approval gate, rendering every proposal's lane explicitly.
- **C5 — Graduated autonomy** *(per-class go-live ceremonies, `#847`).* Individual low-risk action classes
  flip propose→auto behind per-class flags, each an LA governance decision, **default off**. Every flip gets
  a `DECISION_REGISTER` row **and** a per-class **Agents-Rule-of-Two re-analysis** — an auto-flip moves that
  class onto all three legs of the Rule of Two (untrusted input, sensitive system, autonomous state change),
  so the ceremony must show which leg is severed or bounded for that specific class.

**Live digests and briefings do not unlock on C3/C4 shipping alone** — graduation to operator-visible output
is gated by `#855`'s shadow-mode measured precision (§2.12.7), a distinct ceremony from "the code merged."

### 2.11 Model & stack tailoring

*(plan doc §"Model & stack tailoring"; research doc §8–10.)*

- **Small-model discipline — the 14B is the brain, design for it.** Every coordinator model call is a
  bounded, **single-decision** task — classify one ticket, draft one proposal for one detected condition,
  summarize one finished run — **never** a holistic workspace judgment; the *composition* of judgments is
  deterministic code. This is both a security posture (injection resistance scales with capability, so the
  quarantined-drafter split matters *more* at 14B, not less) and a small-model necessity (the field's
  documented format/competence gap and "constraint tax" for structured output under a small model). Grammar
  is used fail-soft (the `#743` pattern); **no coordinator correctness ever depends on the grammar path**
  (the `#725` crash is the standing warning against that dependency). **A concrete, exhaustive taxonomy of
  every single-decision call type across C2–C4 is a named residual, not fully enumerated here** — see §5.
- **Dense and MoE both, via capability contracts.** Each model role (coordinator-brain = dense 14B; coder =
  MoE 30B-A3B; future swaps either shape) binds to a declared capability contract — structured-output
  backend, tool-call format, grammar×spec-decode composability, eval-baseline file — never to a model name. A
  swapped-in model re-earns its role on measurement (the `#717` eval-harness pattern, generalized by
  ADR-038); quantization/format-drift differences degrade *quality*, never *safety*, because correctness
  lives entirely in deterministic gates.
- **OpenCode permissions = defense-in-depth ring, never the boundary.** Documented enforcement gaps on this
  project's exact platform (Windows/Git Bash — upstream opencode #16126/#6396/#8832) mean the load-bearing
  severance stays in BlarAI's staging-time ruler plus the fleet's `_FORBIDDEN_REPO_ROOTS`, never the coder
  harness's own config (§2.2, "also in `#848` scope").
- **ACP as the coordinator's sensory nerve and a third chokepoint.** C2/C3 monitoring consumes the typed ACP
  `session/update` event stream (per-tool-call visibility, honest stall detection, real-time progress)
  instead of log-tailing; the `session/request_permission` channel gets the deterministic, wedge-safe
  responder named in §2.2.

### 2.12 Operational-maturity requirements

*(plan doc §"Operational-maturity additions" — a third design pass hardening the fence-and-method for years
of unattended-adjacent operation; items 1–3 verified live against the running Vikunja instance.)*

1. **Dedicated Vikunja identity — verified defect, fixed.** `vikunja_bridge.py:34-37,74` today reuses the
   **same** `blarai` account as the MCP server and all human/dev writes, so `created_by` cannot distinguish
   BlarAI-authored content — the structural-provenance control (§2.2 control 2) is inert under a shared
   account. Fix: a dedicated **`blarai-coordinator`** Vikunja user for all runtime-bridge writes, created by
   the C1 substrate-setup migration (item 11).
2. **Pagination-aware reads — verified defect class, fixed.** Vikunja's server-side `maxitemsperpage`
   (default 50) silently clamps even an explicit `per_page=200` request; the devplatform `project_summary`
   tool is confirmed reading truncated task lists today. Coordinator reads must loop pages until a short
   page; flow metrics over a truncated board are silently wrong, which at a decades horizon is guaranteed to
   bite eventually if left unfixed now.
3. **API-contract pinning.** Buckets (`/projects/{id}/views/{view}/buckets`), relations, and saved filters
   are confirmed present on the live v2.3.0 spec (118 paths). The bridge pins the API contract with
   regression tests against recorded response shapes; a future Vikunja upgrade becomes a gated event, not a
   silent drift.
4. **Execution-time re-validation (TOCTOU closure).** Approval is not freshness. Every approved proposal
   **re-runs the full deterministic ruler at execution time** (target containment, lane, WIP, DoR) — the
   world may have changed between staging and approval (ticket closed, repo moved, limit reached). The
   execution-time run is authoritative; a stale-invalid proposal is refused with a comment, never
   "best-effort executed."
5. **Cross-cycle proposal dedup + expiry.** Proposals carry a deterministic fingerprint (class + target +
   evidence hash); a condition detected every cycle stages **one** proposal, not one per cycle. Un-actioned
   proposals expire after a configured TTL (default 7 days) back to drafts with a note, so an operator's
   absence never returns to a wall of stale asks.
6. **Tri-state substrate reads — fail-soft must never read as empty.** Every board/state read distinguishes
   `OK` / `EMPTY` / `UNREACHABLE`. The bridge's existing swallow-errors idiom is kept, but a `None`
   (unreachable) **never** renders as "no open work": the snapshot shows "PM substrate unreachable," the
   quiet-queue tripwire suppresses (unknown ≠ quiet), and a down Vikunja is itself a surfaced condition.
   Without this, a dead Vikunja looks exactly like a finished backlog — the exact silent-stall this program
   exists to prevent. §2.14.4 extends this same discipline to resource-predicate evaluators specifically.
7. **Shadow mode + measured graduation (`#855`).** Before briefings or digests ever go live, C3/C4 run in
   **shadow mode**: full cycles, proposals drafted and logged, nothing surfaced. The shadow log is graded
   offline (operator review and/or a rubric-graded eval pass); graduation to live output requires measured
   proposal precision at or above a configured threshold over N cycles — the `#717` eval-culture applied to
   the coordinator's own judgment. A fixture-board **coordinator eval suite** (golden boards → expected
   classifications/pulls) joins `evals/` and **re-runs at every model swap** — the capability-contract
   enforcement of §2.11 applied to this role specifically.
8. **Global pull with a starvation guard.** Already stated operationally in §2.8; recorded here as the
   design decision: the pull queue is global (the dispatch WIP=1 is global — one GPU), class-then-age
   ordered, so Standard items age into priority rather than being indefinitely starved by a busy Expedite
   class.
9. **Operator-absence mode.** A config switch (or auto-detection via N unanswered briefings): only
   Expedite-class conditions surface; digests accumulate to a single catch-up brief; proposal TTLs pause.
   Absence must degrade to quiet safety, never to alert debt.
10. **The briefing ledger — governance evidence.** Every briefing — proposals shown, lane, decision,
    timestamp, resulting action, and outcome — appends to a durable per-month ledger file: an AIGP-grade
    audit trail answering "what did I approve, when, and what happened" without archaeology.
11. **Substrate setup is an operator-run migration, never a coordinator action.** The buckets/labels/filters
    the method needs are created by an **idempotent discover-or-create** setup script, executed via the dev
    channel at C1 — the Coordinator never creates its own workflow structure. All Vikunja IDs (labels,
    buckets) are resolved **by name** at runtime, never hardcoded (the project's own stale-label-id lesson).
    Per §2.9's paired tenet, this migration also runs the orphan-flagging half.
12. **Power/thermal-aware cadence.** The heartbeat honors the device: longer intervals on battery, alignment
    with the existing overnight-window schedule, and no model drafting while thermally throttled. A laptop
    coordinator that keeps the GPU warm all day fails the "decades of use" test this project is built for.
13. **Status output is untrusted in chat.** Restated from §2.7: `/coord status` and digest content render
    into the AO conversation under the `UNTRUSTED` provenance tier, so ticket-title injection cannot become
    chat injection.
14. **PA adjudication verbs for coordinator actions.** Fully specified at §2.6.
15. **Program interlock with `#740` (M2).** Both programs modify `shared/fleet/`; C2's driver-integrated
    checks and M2's plan-graph waves must **sequence, not collide** — coordinated via the tickets and the
    existing worktree merge discipline, not by this ADR picking an order in advance.

### 2.13 Runtime topology & ownership

*(`#842` c.1814, the LA's fourth-pass Q&A clarifications.)*

1. **Heartbeat trigger = in-process, launcher-managed timer — the primary path.** No new Windows Scheduled
   Task initially: a timer inside the running BlarAI backend needs no new privilege surface, sees swap state
   natively, and dies with the app (fail-safe). The existing elevated 23:00 overnight task remains the
   **only** app-not-running wake path. The trigger definition is governed core (§2.1 item 8) regardless of
   which mechanism carries it.
2. **At-rest encryption for coordinator stores.** The proposal-staging store, the briefing ledger, and the
   shadow journal are content-bearing (goals, ticket text) and therefore **born-encrypted**, matching the
   default-strict posture already applied to session/knowledge stores. The signed policy file (control 7) is
   *signed* for integrity, not encrypted — its content must be readable to verify, only untamperable. The
   Vikunja database itself stays third-party-native: loopback-only, encrypted disk, and joins the existing
   backup discipline.
3. **Account topology.** Extends the containment Decision 1 of 2026-07-10: the **coder fleet** runs in the
   **restricted** Windows account (untrusted model-written code executes in the contained domain); the
   **Coordinator runs in the operator's own account** (the trusted domain) — **never** in the restricted
   account, so the manager's state and policy stay out of the worker's reach. The account boundary is an
   additional OS-level ring: restricted-account ACL-deny on coordinator state and governed-core policy paths
   (`#848` records it as a supporting, not load-bearing, control).
4. **Merge boundary.** The Coordinator coordinates the lifecycle *around* merges — parked→proposal,
   merged→close-with-evidence, cross-job failure patterns feeding flow metrics — and **never** the merge
   verdict itself, which stays with the deterministic fleet gate. Author-≠-verifier applies to the PM role
   too.
5. **Ownership migrations out of `/dispatch`.** Ticket-lifecycle glue (today's in-dispatch `vikunja_bridge`
   calls) moves to C2; "what runs next" (today: the operator typing `/dispatch`) moves to the C4 pull policy;
   ticket **readiness** (the Definition-of-Ready gate) moves to the PM, ahead of a ticket entering PLAN.
   Staying in `/dispatch`: decomposition, acceptance criteria, `#819` clarify / `#820` revise — those are
   engineering concerns, not management ones. **Single-approval UX:** a dispatch originating from an
   approved briefing item renders its plan-confirm **inside** that briefing — one approval moment per job,
   never two.
6. **Two-layer monitoring doctrine.** *In-run tactical* monitoring (swap-driver watchdogs, budgets, circuit
   breakers — the only layer alive mid-swap; seconds-to-hours timescale) stays exactly as it is today.
   *Cross-run operational* monitoring (aging, cross-job stalls, the quiet-queue tripwire, flow trends —
   hours-to-weeks timescale) is the Coordinator's new territory. Same underlying events, different
   timescales and response authority.
7. **The AO is front door and display only.** The Coordinator is a peer role (§2.5): the heartbeat invokes
   it directly on the shared 14B with no conversational round-trip; C2's lifecycle hooks activate at the
   first dispatch/New-Project event with zero AO participation. The AO's role toward the Coordinator is
   exactly two things — routing `/coord` commands, and rendering digests/briefings in chat (§2.14.7 extends
   this into the AO's own prompt).

### 2.14 Second-pass hardening requirements (2026-07-12)

*(`#842` c.1838 — a fifth, LA-directed verification walk of the full designed flow, after the tenet-review
disposition landed. Full failure-scenario detail:
`docs/reviews/durability-distribution-tenet-adversarial-review-2026-07-11.md` §SECOND PASS.)* These arrived
after the plan doc's last revision and are **formalized here for the first time** — this is the freshest
layer of doctrine this ADR carries, and the one most worth the LA's direct read.

#### 2.14.1 Heartbeat dead-man check (V2 — the sharpest gap)

Every alarm in C2–C4 (the quiet-queue tripwire, stall detection, eligibility flips, digests) is **computed
by** the heartbeat cycle — a wedged or dead heartbeat cannot fire its own alarm, and "the operator notices
digests stopped arriving" is vigilance, which this program's own premise disallows as a control. **Requirement
(decided): a deterministic liveness check outside the heartbeat itself** — a launcher watchdog, or the
existing elevated overnight task, verifying a last-cycle-completed timestamp; the same boot-canary pattern
(§2.2 control 6) applied to *liveness* rather than to boundary containment. Implementation home: `#845`.

#### 2.14.2 Flow-metric timestamp source and the definition of "age" — **OPEN, not decided by this ADR**

Vikunja holds `created`/`updated`/`done_at` timestamps but **no bucket-transition history** — so "age in
Ready," per-stage cycle time, and the class-then-age pull policy's very notion of "age" (§2.8, §2.12.8) have
no native data source today. Two mechanism options are named in the source material — the heartbeat
snapshot-diffing bucket state each cycle, and/or the Coordinator journaling its own bucket moves — and the
choice between "age = ticket-created timestamp" versus "age = entered-Ready timestamp" changes both FIFO
fairness within Standard-class and the gated-age-accrual behavior of §2.9. **This ADR does not pick one** —
doing so would be inventing policy rather than formalizing it, and the source ticket comment explicitly
frames this as a decision "ADR-039 picks," which this drafting pass declines to make unilaterally. It is
recorded here as a **required, single, consistently-applied definition** to be settled at C1/C3
implementation kickoff (`#843`/`#845`), with both named options on the table and no default preference
stated. **See §5 — this is the most load-bearing open item in this document.**

#### 2.14.3 Resource-marking lifecycle (V1 — a judgment call, not a found decision)

The `Resource:*` label (§2.9) is applied at staging. The source ticket comment offers two ways to keep
gated-inventory metrics from ever counting In-Progress/Done cards: actively **clear** the label on a
successful pull, or simply **ignore** it outside the Ready bucket. This drafting pass adopts the *ignored
outside Ready* reading as the one formalized below, because it is the simpler and more deterministic of the
two (no additional mutation to forget on the pull path) and it falls directly out of the "eligibility, not
membership" encoding §2.9 already settled — a label that is only ever *interpreted* while a card sits in
Ready has no observable effect once the card leaves Ready, whether or not the label bytes are still present.
**This is this drafting pass's inference, not a verified pre-existing decision** — flagged for a quick LA
confirm at §5, distinct in kind from §2.14.2's fully open item.

#### 2.14.4 Evaluator failure semantics (V3)

The tri-state discipline of §2.12.6 (`OK`/`EMPTY`/`UNREACHABLE`) is **extended to the resource-predicate
evaluators** of §2.9 specifically: an evaluator that throws or is unreachable resolves to **`UNKNOWN`**, and
a card under an `UNKNOWN` evaluation **stays gated and visible**, with the condition surfaced. `UNKNOWN` must
never render as "free" (a spurious release that could pull work before its resource window truly opens) nor
silently as "busy" (an indefinite, invisible gate with no surfaced condition for the operator to notice).

#### 2.14.5 The composer-only sensory path (E1 — naming an implied tenet explicitly)

The Coordinator model **never self-navigates**. Deterministic code composes a bounded context for each
single decision (§2.11) from exactly three defined sources: **policy** (`[coordinator]` config plus the
signed policy file, control 7), **state** (the C1 snapshot composer), and **work** (the paginated Vikunja
board, §2.12.2). This was already implied by the small-model discipline of §2.11 and the deterministic-first
cycle ordering of Phase C3; it is named here as an explicit, citable tenet so a future implementation cannot
quietly grow a fourth, model-navigated source.

#### 2.14.6 Positive required-assets boot probe (E3 — the paired half of control 6)

Control 6 (§2.2) proves the **negative**: the coordinator surface cannot reach a governed-core write path.
Nothing in the original seven controls proves the coordinator *can* reach what it legitimately needs. The
same boot self-check gains a **positive** probe: buckets/labels/the `blarai-coordinator` account are
name-resolvable, the coordinator's own stores are openable, and the signed policy's signature is valid — any
failure means **refuse-to-start**, or a defined degrade to advisory-only with the condition surfaced (never
a silent partial-function state). This closes a half-migrated-substrate failure mode at boot rather than at
the first live cycle, where it would be far harder to diagnose. Implementation home: `#843`.

#### 2.14.7 Prompt architecture (E4)

**(a)** The AO's own system prompt gains an explicit peer-role section, landing at C1: route `/coord`
commands to the Coordinator; render Coordinator output under the `UNTRUSTED` provenance tier (§2.7, §2.12.13);
**never improvise a PM answer itself** — this is role non-overlap (§2.5's charter field) stated concretely
for the AO's own prompt. **(b)** The role-charter template itself is specified in full at §2.5.

*(Also fixed by this pass, already folded into §2.9/§2.13's text above rather than repeated here: the
quiet-queue tripwire definition requiring resource-**eligible** work explicitly, and the correction of "five
structural controls" to the correct **seven** throughout this document's sources.)*

### 2.15 Single-decision decomposition for the 14B — partial enumeration, residual named

*(`#842` item (h); research doc Q7.)* The plan doc and research doc establish the **pattern** — every
coordinator model call is bounded and single-decision, never a holistic workspace judgment — and name three
concrete example categories: **classify one ticket** (e.g., is this specific item stalled; is it Ready-
worthy), **draft one proposal** (for one detected condition, targeting one ticket), and **summarize one run**
(the outcome digest for one finished job). Research-doc question Q7 asks explicitly whether this
decomposition is specified concretely enough for a 14B's reliable envelope, and the honest answer at C0 time
is: **not yet a complete taxonomy** — a full enumeration of every bounded decision type across C2, C3, and C4
is deferred to those phases' own implementation tickets, where each concrete call site can be named and
budgeted (§2.11's constraint-tax note) rather than pre-guessed here. This ADR fixes the **pattern** as
binding doctrine; it does not invent the missing list.

### 2.16 Self-modification classification — the cross-repo ADR-022 taxonomy stamp

Within the devplatform cf-program **ADR-022 self-modification-surface taxonomy** (the same taxonomy ADR-036
stamped for the operator-preference tier), the Coordinator program is classified as follows:

- **Surface:** the **broadest** self-modification-adjacent surface BlarAI has built to date — a role with
  read access to BlarAI's own backlog, a dispatchable coding fleet, and (from C4) a proposal channel that
  names its own tickets. Higher-reach than the preference tier ADR-036 governs (which is read-into-every-
  prompt but narrowly scoped to operator-authored text); this surface's blast radius, unmitigated, would be
  "propose code changes to BlarAI itself."
- **Control:** killed **structurally**, not behaviorally, by the two-domain model (§2.1) and the seven
  controls (§2.2): the model-reachable write path to the governed core does not exist at any layer (identity-
  based target severance, structural provenance, config immutability, boot canary, signed policy); the
  self-work channel is advisory-only and categorically refused by BlarAI's own dispatch path even when
  approved (§2.2 control 2). This is the DGM research line's "frozen evaluator" principle applied twice —
  once to BlarAI's own runtime (the fleet must not grade or dispatch against its own governing code), and
  once to the fleet's acting limb (agentic-setup's verify-gate/oracle/harness config is *itself* governed
  core, severed from both sides, §2.1 item 9).
- **Residual, tracked:** the weak-signal induced-proposal window — a hostile ticket or run report nudging a
  plausible-looking workspace proposal the operator approves without close reading. Mitigated by §2.2's
  outcome-in-plain-language rendering and the mandatory per-item confirmation for impactful classes; measured
  going forward by the `#855` shadow-mode precision gate, the coordinator-role analog of ADR-036's
  poisoning-redteam eval. **A dedicated coordinator-surface adversarial eval (the `#855` fixture-board suite
  graded for induced-proposal susceptibility, not just classification accuracy) is the arm-on-change control
  this classification requires** — named here so `#855`'s scope inherits it explicitly rather than
  rediscovering the need.
- **Standing residual named by the SG-boundary review, Q1:** the Coordinator's own ruler and forbidden-target
  set live in **BlarAI's own codebase** — host-side, not a separate privilege domain (a hypervisor, a
  guest-side verifier). The compensating layers are the human-only dev channel plus code review (today) and
  signed-policy-at-boot (control 7, once shipped) — **not** a separate enforcement ring BlarAI's own process
  cannot load-time-patch. This is stated honestly rather than papered over: it is exactly why §2.17's claim
  discipline caps the boundary's current claim at "safe under expert operation."

### 2.17 Claim discipline

This ADR and every phase built under it make **exactly one** claim until control 7 (§2.2, signed policy
verification) ships: **the self-governance boundary is safe under expert operation.** It is explicitly
**not yet** claimed safe to hand to a non-technical operator — that claim requires control 7 live, verified,
and itself regression-locked. Any future documentation, marketing framing, or operator guide that states the
stronger claim ahead of control 7 shipping is a doctrine violation of this ADR, not a permissible
simplification.

## 3. Consequences

**Positive:**

- BlarAI's coordination capability is governed by name before a single line of C1–C5 implementation exists —
  every later phase builds under a settled boundary instead of accreting ad hoc judgment calls per pull
  request.
- The `#749` "no ticket tools" invariant is amended narrowly and explicitly (a read-only carve-out), which
  forecloses the invariant silently eroding into a broader write surface over successive phases.
- The two-domain model plus seven controls give the eventual non-technical-operator future a **structural**
  safety story rather than a vigilance-dependent one, honestly capped by §2.17 until control 7 ships.
- The Kanban method keeps the AI out of the project-management control loop entirely — every mechanism is
  arithmetic over Vikunja timestamps/labels, matching the project's standing "gate as JUDGE, model as SIGNAL"
  discipline.
- Untrusted ticket, run, and web-adjacent content can shape proposal wording only, never an action's target
  (§2.2 control 1) nor a gating predicate's value (§2.9) — the CaMeL property is carried through every new
  surface this program adds, not just the ones it was originally designed against.

**Negative / accepted trade-offs:**

- Every phase carries real implementation cost — seven controls, tri-state reads, pagination correctness,
  dedup/TTL, a shadow-mode gate — before any autonomy goes live. This is deliberately slower to first value,
  traded for a structural rather than reputational safety story; the LA has already accepted this trade at
  design-approval time (`#841` c.1812, "no implementation authorized" until this doctrine and `#848` land).
- Control 7 is not yet built. Until it is, the boundary's claim is capped at "safe under expert operation"
  (§2.17) — a real, named limitation, not a caveat buried in a footnote.
- Two decisions are carried forward unresolved rather than settled here (§2.14.2, §2.14.3) — a deliberate
  choice to avoid inventing constitutional policy under this task's own instruction not to design, at the
  cost of leaving C1/C3 implementation with a decision still to make. §5 makes both impossible to miss.
- The Coordinator's ruler and forbidden-target set live in BlarAI's own codebase, not a separate privilege
  domain (§2.16, SG-review Q1) — the compensating layers are process discipline (dev channel + code review)
  and, once shipped, cryptographic verification (control 7) — not architectural isolation. Named honestly as
  a standing residual rather than claimed away.

## 4. Rejected alternatives (on the record)

| # | Rejected | Reason |
|---|---|---|
| 1 | Name-based self-target severance (matching path components) | evadable by a renamed clone or junction; superseded by canonical-realpath identity containment (§2.2 control 1) |
| 2 | Text-convention provenance marking for self-authored tickets | forgeable by any injection that can author a comment; superseded by structural marking — a dedicated account's immutable `created_by` plus a code-set label (§2.2 control 2) |
| 3 | Continuing the shared `blarai` Vikunja account for the runtime bridge | verified defect — makes `created_by` provenance inert by construction; superseded by the dedicated `blarai-coordinator` account (§2.12.1) |
| 4 | A new bucket/lane for resource-gated deferral | breaks "stays in Ready" and complicates the pull computation for no benefit over a marking (§2.9) |
| 5 | Encoding resource-gating as a Vikunja blocker relation | inert against the pull computation — a relation-gated card is de-Readied by the existing DoR check and vanishes from consideration entirely, rather than staying visibly gated (§2.9, tenet-review F2) |
| 6 | Polling for externally-caused conditions (e.g., "did an upstream fix land") | violates the zero-egress mandate structurally; replaced by a bounded human-check line in the briefing (§2.9, tenet-review F1) |
| 7 | Resetting a released resource-gated card's age to zero | unfair to a card that legitimately waited; age accrues through the gate instead, so the card catches up (§2.9, tenet-review F8) |
| 8 | An LLM (the 14B) as the ACP `session/request_permission` responder | makes the responder itself an injectable judge; the responder is deterministic code, always (§2.2) |
| 9 | Treating OpenCode's permission ring as load-bearing | documented Windows enforcement bugs (opencode #16126/#6396/#8832) mean it is defense-in-depth only (§2.11) |
| 10 | One shared prompt/tool-surface for the Coordinator and the AO | breaks tool-surface minimization, prompt integrity, and per-role auditability; the Coordinator is a distinct resident role instead (§2.5) |
| 11 | Scrum (fixed sprints, story points, velocity) as the PM method | sprints synchronize human teams, which this system does not have; Kanban's arithmetic-only machinery keeps the model out of the control loop (§2.8) |
| 12 | An unconditional or default-on autonomy ladder | the ladder ships fully OFF; every promotion is an LA ceremony with a `DECISION_REGISTER` row and a per-class Rule-of-Two re-analysis, never a default (§2.10) |
| 13 | This ADR unilaterally deciding the flow-metric "age" definition | would be inventing constitutional policy rather than formalizing approved doctrine; left explicitly open for C1/C3 implementation (§2.14.2, §5) |

## 5. Open questions carried to implementation — explicitly NOT decided by this ADR

These are named here, deliberately, rather than resolved, because resolving them would exceed this ADR's
formalize-don't-design mandate. Each needs the LA's eyes before — or at latest during — the phase named.

1. **(Load-bearing) Flow-metric "age" definition and its timestamp source (§2.14.2).** Vikunja has no native
   bucket-transition history. The mechanism (heartbeat snapshot-diffing bucket state each cycle, and/or the
   Coordinator journaling its own moves) and the definition itself (age from ticket-`created`, versus age
   from entered-Ready) are both still open. This affects FIFO fairness within the Standard class and the
   gated-age-accrual behavior §2.9 already locked — a real, near-term decision, not a someday item.
   Implementation home: `#843`/`#845`.
2. **(Judgment call, please confirm) Resource-label clearing (§2.14.3).** This drafting pass formalized
   "ignored outside Ready" as the operative rule, inferring it from the already-decided "eligibility, not
   membership" encoding rather than finding it independently pre-decided. A one-line LA confirmation (or
   correction) closes this.
3. **Scope extension beyond coding projects.** `#842`'s own scope description flags, as `[PROPOSED]`, whether
   the Coordinator's mandate eventually extends beyond dispatched coding projects to the broader seven-
   Use-Case vision (non-coding project coordination). The current, LA-decided mandate (`#841`) is dispatched
   coding projects plus BlarAI's own backlog, phased so the coding tier lands first — this ADR states that
   mandate as decided (§1) and explicitly leaves the *extension* question open rather than assuming an
   answer either way. A future ADR amendment, not this one, should close it.
4. **Full single-decision-call taxonomy (§2.15).** The pattern is fixed; the exhaustive list of bounded
   decision types across C2–C4 is not. Left to each phase's own implementation ticket.
5. **Role-charter retrofit for PA and AO.** §2.5's six-field template is binding for the Coordinator from C1
   onward; retrofitting PA's and AO's existing prompts into the same shape is documentation-only, named as a
   residual, and not scoped into any numbered phase of this program.

## References

- **This ADR / program:** Vikunja `#841` (epic), `#842` (C0 — comments c.1798 constitutional decision, c.1812
  design approval, c.1813/c.1814 runtime-topology Q&A, c.1822 durability tenet, c.1833 tenet-review
  disposition, c.1838 second-pass hardening), `#848` (SG), `#843` (C1), `#844` (C2), `#845` (C3), `#846`
  (C4), `#847` (C5), `#855` (CV), `#749` (the amended invariant), `#740` (M2 sibling program).
- **Design doc (SSOT):** `docs/research/coordinator-program-plan-2026-07.md`.
- **Research + SG-boundary adversarial review:** `docs/research/coordinator-self-governance-research-2026-07.md`
  (13 findings dispositioned into the plan doc; Q1–Q10 synthesis).
- **Durability-tenet adversarial review (separate review, separate F-numbering):**
  `docs/reviews/durability-distribution-tenet-adversarial-review-2026-07-11.md`;
  `docs/reviews/durability-distribution-tenet-review-disposition-2026-07-11.md`.
- **Operator-facing companion:** `docs/research/coordinator-operator-guide-2026-07.md`.
- **Journal fragment:** `docs/journal_fragments/2026-07-11_the-coordinator-design.md` (and the tenet-specific
  `2026-07-11_durability-distribution-tenet.md` / `2026-07-11_durability-tenet-adversarial-review.md`).
- **Code referenced:** `shared/fleet/dispatch.py:40` (`_FORBIDDEN_REPO_ROOTS`, the existing anchor §2.2
  control 1 generalizes), `shared/fleet/vikunja_bridge.py` (the loopback/fail-soft/transport-split pattern,
  §2.3), `shared/schemas/car.py` (`CanonicalActionRepresentation`, `ActionVerb`, `AdjudicationDecision`,
  §2.6), `services/assistant_orchestrator/src/tools.py` (`RiskTier`, `_REGISTRY`, the GUARDED runner-seam
  pattern, §2.4).
- **Prior ADRs this builds on:** ADR-034 (model-swap driver), ADR-035 (Acceptance Layer), ADR-036 (Operator-
  Feedback-Memory Governance — the `propose_preference` template and the ADR-022 cross-repo taxonomy this ADR
  stamps a second time, §2.16), ADR-023 (Provenance-Based Trust Model), ADR-027 (Egress Policy — the
  loopback/one-door precedent), ADR-018 (TPM trust root — the signed-manifest machinery control 7 extends).
- **Cross-repo taxonomy:** `C:\Users\mrbla\devplatform\docs\adrs\` ADR-022 (self-modification-surface
  taxonomy, MCP design principles v1.1).
- **External literature (full citation list in the research doc):** OWASP GenAI LLM06:2025 (Excessive
  Agency); Debenedetti et al., "Defeating Prompt Injections by Design" (CaMeL), arXiv:2503.18813; Willison,
  "The lethal trifecta"; Meta's Agents Rule of Two; Zhang et al., "Darwin Gödel Machine," arXiv:2505.22954;
  "Parallax: Why AI Agents That Think Must Never Act," arXiv:2604.12986 (the boot-canary precedent);
  agent-run-kanban practice (Agent Kanban, vibe-kanban, Kanbots); Agent Client Protocol specification
  (agentclientprotocol.com).

---

*Formalized by a design specialist subagent from LA-approved doctrine (`#841` c.1812; explicit ADR-039
authorization relayed 2026-07-11/12). No new constitutional policy was invented in this pass; §2.14.2 and
§2.14.3 are flagged, not silently resolved, per the task's own instruction to surface gaps rather than
paper over them. Promote from `DRAFT_` to final once the LA has read this file directly.*

---

## Amendment 1 (2026-07-12) — Coder Vikunja Documentation Account

*Ratified 2026-07-12 — LA: "yes coordinator drives the board and closures, governance projects
off-limits to the coder. proceed"; the multi-project structure "enthusiastically approved." Docs-only;
the account + shares ship dormant, set up by C1's operator-run migration (`#843`) and wired into C2
(`#844`) behind `[coordinator]` flags. Tracked: `#870` (New-Project → Vikunja-project wiring + the
modest reorganization).*

**Refines** the base ADR-039 agent-architecture / account-topology, which implied the coder (restricted
account) is fully isolated from Vikunja. That was over-restrictive: a coder that documents its progress,
errors, and blockers is *more* auditable, and Vikunja is the right place for that record. This gives the
coder a scoped Vikunja documentation account **without** opening any path to the governed core.

### A1.1 The mechanism — Vikunja per-project permissions
Vikunja's permission model is three rights levels — **Read / Read&Write / Admin** — set **per-project**
when a project is shared with a user or team (verified: vikunja.io/docs/permissions,
/help/sharing-and-teams). There is **no per-action "comment-only"** level (commenting rides Read&Write),
and bucket/status moves now require Admin. So the fine-grained control is **per-project**, not per-action.

### A1.2 The mixed-project problem + the one-project-per-coding-project resolution
The existing Vikunja projects are **mixed** — a single project (e.g. Infrastructure) holds both coding
tickets and governance/security tickets — so per-project Read&Write cannot cleanly separate coder-work
from the governed core. **Resolution: one Vikunja project per coding project, under a "Coding Projects"
parent.** Every coding project BlarAI builds gets its own Vikunja project, created automatically when the
New-Project button fires (`#712` `create_project` also creates the Vikunja project + shares it Read&Write
with `blarai-coder` at creation — tracked `#870`). The coder documents on *its* project's tickets
(progress/errors/blockers, scoped to that project); the coordinator drives the board + relays outcomes to
any origin/governance ticket. BlarAI's own development stays the **governance set** (off-limits to the
coder), optionally grouped under a "Governance" parent so the boundary is self-documenting. Vikunja
supports project nesting; permission inheritance parent→child is unverified, so the coder share is set
per-child at creation. Scope: a **modest reorganization** (add the two parent groupings + tidy
`[auto]`-digest/stale-meta cruft), not a full different-setup migration — existing tickets keep their
history. *(Rejected: coder Read&Write on the existing mixed projects + code-enforced identity-severance —
it works but leans on our own enforcement instead of Vikunja's per-project boundary.)*

### A1.3 Account topology
- **`blarai-coder`**: Read&Write on the dedicated coding-work project(s) ONLY; NO access to governance
  projects. Documents progress / errors / blockers / its own task edits. Its comments are
  **provenance-marked UNTRUSTED** (base control 3 — a ticket title cannot become a coordinator
  instruction).
- **`blarai-coordinator`** (base control 2): broad Read (the read-surface) + approval-staged writes;
  drives the board (status / buckets / closures), originates work, and relays coder outcomes to origin
  tickets.
- The coder does NOT drive its own board (bucket-moves need Admin, which it lacks) — the coordinator
  lifecycles it. **Coder has a voice; coordinator drives the board; neither touches the governed core.**

### A1.4 What stays unchanged
The governed-core boundary (base §2.1 — zero write path to code/config/prompts/policy/keys/governing-docs/
ruler-flag-trigger defs/fleet gate-oracle-harness config) is UNCHANGED; the coding-work project and origin
work-tickets are the WORKSPACE, not the governed core. Base control 3 (instruction-channel integrity)
already provenance-marks BlarAI-authored ticket content as untrusted — this amendment relies on it, does
not weaken it. The coordinator's read-only-GUARDED ticket tools + staged writes (the `#749` amendment) are
unchanged. The identity-based severance (control 1) still applies to any coder attempt to reach a
governed-core target regardless of Vikunja permissions.

### A1.5 Build
The `blarai-coder` account + its project share(s) are set up by **C1's operator-run migration** (`#843`,
alongside `blarai-coordinator`) — discover-or-create, IDs resolved by name. The coder→comment
documentation path + the coordinator-relay are wired in **C2** (`#844`). Both ship dormant behind
`[coordinator]` flags. Account creation is either an operator browser step (recipe handed over) or the
migration via the Vikunja API if the instance permits — settled during the C1 migration design.

## Amendment 2 (2026-07-12) — Control-1 Hardlink Defense: the `st_nlink` Deny Layer (F1 closure)

*Ratified 2026-07-12 — LA: "i officially signoff on 848." Records the doctrine correction the F1 closure
earned. The mechanism ships in `#848` (`feat/848-sg-boundary`, `3f2622c4`; merged to main `c0731036`),
shipped behind `[coordinator]` flags, dormant by default at ratification.*

> **ACTIVATION RECORD (added 2026-07-20) — the wiring the note above calls "not yet live" IS live.**
> `default.toml` now carries `[coordinator] enabled = true` and `heartbeat_enabled = true`, and the
> heartbeat runs in shadow mode. The 2026-07-12 parenthetical is retained above as the record of that
> date, not as a claim about current wiring. Read live flag state from `default.toml`, never from this
> ADR. The severance ratified here binds identically at every flag setting — that is the point of a
> structural boundary, and it is why activation does not weaken the decision.

**Corrects** the base control-1 framing, which treated the hardlink-overwrite vector (SG-review F1) as
covered by an inode-identity comparison against a small set of governed-core **anchor** files (the
`.blarai-governed-core` sentinel + `CLAUDE.md` / `docs/DECISION_REGISTER.md` / `shared/fleet/dispatch.py`).
That check was **anchor-limited**, but the governed core is the WHOLE tree: a hardlink placed under an
allowed workspace path and pointing at a **non-anchor** governed-core file (e.g. `pyproject.toml`,
`launcher/config/default.toml`, `shared/coordinator/config.py` — the boundary's own policy data — or a PA
policy module) aliases no anchor, and its own path passes canonical-realpath containment, so the
anchor-only check returned ALLOW while a write through it would still mutate the linked core file. The
independent SG re-verify proved this at EXECUTION phase; it was owned by neither the original inode check
nor the planned F2 during-ring.

**A2.1 The correction (option a, LA-chosen).** Control 1 gains a deterministic, fail-closed **link-count
layer** (`shared/coordinator/governed_core.py::_is_multiply_linked_existing`): any EXISTING write target
with `st_nlink > 1` (an already-hardlinked file) is governed core → DENY, whatever it aliases — closing
the non-anchor-hardlink class in general rather than enumerating anchors. A not-yet-existing target
(`st_nlink == 1`, the normal new-workspace-file case) is unaffected; an undeterminable count (`0`,
non-NTFS/handle-less) is not `> 1`, so the layer never false-denies and the other identity layers still
apply. Over-denial fires only when overwriting an already-hardlinked existing file — a negligible, correct
cost for a constitutional fail-closed boundary.

**A2.2 What stays unchanged.** The two-domain model (§2.1) and the other six controls are UNCHANGED — this
is an implementation-completeness hardening of control 1, not new policy. `_shares_inode_with_governed_core`
is retained (the new layer is additive); the §2.17 / control-7 claim-discipline is unchanged.

**A2.3 Build + verification.** `feat/848-sg-boundary` `3f2622c4` (merged `c0731036`); +8 adversarial
regression locks (a hardlink to each of the four proven non-anchor targets now DENIES at both
`is_governed_core_target` and `check_target(phase="EXECUTION")`; the `st_nlink == 1` no-over-denial guard;
the fail-closed-on-error guard). Independent author≠verifier re-verify: **PASS, F1 class closed**. Blast-radius
gate 189 passed. Dormant by default at the time of this entry. **Superseded 2026-07-20:** live modules
DO import `shared.coordinator` — `services/assistant_orchestrator/src/entrypoint.py:67` and
`launcher/__main__.py:1169` among them. The import-count claim was a snapshot, not a property; the
boundary's guarantees do not rest on it.
