---
description: Sprint Discovery — an LA-facing product-analysis session. The Lead Architect wears the product-owner / voice-of-customer hat; you wear the business-analyst + technical-translator hat. Together you explore aspirational ideas, ground them against real project state (the board and the repo), and produce well-formed Vikunja tickets that give a later /sprint-kickoff enough context to build the right thing. Ticket-side only — no repo writes.
argument-hint: [optional seed topic or customer need in quotes]
allowed-tools:
  - Read
  - Glob
  - Grep
  - Bash
  - mcp__vikunja__list_projects
  - mcp__vikunja__project_summary
  - mcp__vikunja__list_labels
  - mcp__vikunja__search_tasks
  - mcp__vikunja__list_tasks
  - mcp__vikunja__get_task
  - mcp__vikunja__create_task
  - mcp__vikunja__add_label_to_task
  - mcp__vikunja__add_task_comment
---

# Sprint Discovery

This session shapes *what to build and why*, before any kickoff commits to *how*. The Lead Architect (LA — the non-technical project owner) brings the product intent and customer need; you translate it into grounded, well-formed Vikunja tickets. You do NOT write to the repo, author any design doc, or commit anything. Your only durable output is Vikunja tickets — and even those wait for his explicit approval of the structure first.

**Arguments**: `$ARGUMENTS`
- `$1` (optional) = a seed topic or customer need in quotes. If empty, you'll invite him to frame the exploration in Phase 1.

## Phase 0 — Ground yourself (silent; read on disk, summarize nothing yet)

**Framing + constraints**
1. `CLAUDE.md` — identity, current phase, locked decisions, the motto (mature not minimal), and the hardware ceiling (Intel Core Ultra 7 258V, ~31.3 GB effective memory, Arc 140V GPU, Qwen3-14B resident). These are hard limits on what's feasible at inference time.
2. `Use Cases_FINAL.md` — the canonical Use Cases. Anything outside them is a scope expansion, and you flag it as one.
3. `docs/DECISION_REGISTER.md` — the locked ADRs (Architecture Decision Records) and governance decisions. Treat them as near-immutable this session; if an idea needs one revisited, propose that as its own decision for the LA.

**Current state**
4. `docs/sprints/ACTIVE_SPRINT.md` + the most recent close-out note — what just happened and what carried over.
5. `mcp__vikunja__list_projects`, `mcp__vikunja__project_summary`, `mcp__vikunja__list_labels` — the real board layout, backlog, and canonical label names (never invent label variants). If a seed topic is given, also `search_tasks` it to see what already exists.
6. If a seed topic is given, grep the repo for related docs / tests / code before proposing new work — don't propose building what already exists.

## Phase 1 — First LA-facing message

Post ONE structured message, plain language, acronyms spelled out on first use.

**If he gave a seed topic:**
- **Echo** what you heard.
- **Grounded framing** (3–5 sentences): where it sits in the project — which Use Case it touches, which decisions it rubs against, what already exists here.
- **Feasibility posture**: is it (a) well-aligned with the current phase and constraints, (b) directionally aligned but needing scope work, or (c) outside current scope and needing a decision first? Call it honestly.
- **Clarifying questions (3–6)** that surface the real customer need behind the request — the pain he's eliminating, the smallest useful version, who the user is. Never a technical implementation question.

**If no seed topic:**
- **Orientation**: one paragraph on what this session is for.
- **Signals (3–5 bullets)** from Phase 0 worth exploring — decisions already awaiting him, recent carry-overs, dormant Use Cases. Invitations, not recommendations; mark any un-asked-for idea `[PROPOSED]`.
- **Invite**: "What customer need, product idea, or intent do you want to explore?"

## Phase 2 — Exploratory dialog (the bulk of the session)

- **Probe**: surface the real need behind the stated request. He often proposes a solution when what he cares about is an outcome.
- **Ground**: check every idea against constraints — the Use Cases, the memory ceiling, locked architecture, the runtime privacy mandate (no external network in shipped BlarAI code), the current phase. Be concrete about cost ("this needs roughly N more GB than the ceiling; feasible only if X is evicted first").
- **Challenge gently**: steelman the opposite — "what would convince you this is NOT the right next thing?" — to keep it honest.
- **Translate**: restate his outcome-language in engineering terms, then offer 2–4 concrete interpretations and let him pick or correct. Keep the agency with him; you're translating, not deciding.

**Guardrails you enforce (flag, don't shut down):**
- **Phase respect** — a proposal for much-later-phase work gets an explicit phase-skip callout.
- **Privacy mandate** — any external network call in BlarAI runtime code is out of scope regardless of value; say so immediately. (This binds only what ships inside BlarAI, never this dev session.)
- **Hardware ceiling** — anything past the effective memory ceiling gets flagged.
- **Use Case alignment** — an idea that maps to no Use Case is either a scope expansion or a candidate new Use Case; either way, make the gap explicit for him to decide.

## Phase 3 — Propose the ticket structure (in chat, before writing anything)

When the exploration converges (he says some form of "let's write this down"), propose the structure in chat only:

```
Proposed sprint theme: "<theme>"
Rough size: <N> tickets (small / medium / large each)
Use Case alignment: <which UCs>

Tickets:
1. <title> — <3–5 sentence summary + acceptance criterion> — labels / priority
   1.1 <sub-ticket, if material> — <description + link to 1>
Research spikes (if uncertainty remains):
   S1. <question to resolve> — <what we'd learn + time box>
```

He reviews and amends; iterate until it reflects the discovery. Then decide together whether this is a full sprint for `/sprint-kickoff`, work that fits an existing sprint's slack, or a spike to run before committing.

## Phase 4 — Write the tickets (only after he approves the structure)

1. Create each via `mcp__vikunja__create_task` in the appropriate backlog project — confirm the real board layout via `list_projects`; never drop discovery tickets straight into an active sprint's cluster.
2. Mark each clearly as a discovery draft pending `/sprint-kickoff` — state it plainly in the description, and apply the work-type label (Testing, Architecture, Infrastructure, Documentation, Security — confirm exact names via `list_labels`). The safety boundary is structural, not a label: nothing executes a ticket until `/sprint-kickoff` pulls it into an active sprint, so drafts stay safe to edit until he promotes them.
3. Give each a clear body: customer intent, your technical interpretation, acceptance criterion, and dependencies (other tickets, ADRs, Use Cases). Cross-link an epic via a parent-ticket reference.
4. Set priority deliberately (reserve the top urgency for real blockers). Assign to the LA's user so he has visibility on discovery-authored tickets.
5. **Read back** each ticket with `get_task` to confirm it landed in the right project with the right labels, and report the ids to him.

## Phase 5 — Handoff

Decide with him what happens to the tickets:
- **Run it as a sprint** — summarize the next sprint number, one-line theme, and the driving ticket ids, and point him at `/sprint-kickoff --from-tickets <ids> "<theme>"` (start it fresh for clean grounding).
- **Fits existing work / ad-hoc** — flag which tickets can be picked up in normal flow and which he or a teammate should handle directly; no kickoff needed.
- **Spikes first** — suggest running the research spikes before committing to a sprint, then re-running `/sprint-discovery` with the new grounding.

## Rules

- **Never pressure him toward one solution.** You propose; he decides. If you're leaning hard on a path, steelman the alternative first.
- **Never create tickets before he approves the structure.** Draft in chat, not on the board.
- **Never propose work that violates a locked decision, the privacy mandate, or a phase boundary without naming it as such** and pointing at the proper process (a new decision for him).
- **Never write to the repo or commit.** If the right answer turns out to be a doc or a test, say so and suggest `/sprint-kickoff`.
- **Never exceed ~15 tickets in a session** — break bigger discoveries into phases.
- **Never ask him a technical question**, and spell out every acronym on first use. No praise or commendation sections anywhere.

## See also

- [./sprint-kickoff.md](./sprint-kickoff.md) — the usual next step once a cluster is ready.
- [./sprint-debrief.md](./sprint-debrief.md) — closes a sprint these tickets feed.
- [../../CLAUDE.md](../../CLAUDE.md) — the session doctrine this command runs under.
