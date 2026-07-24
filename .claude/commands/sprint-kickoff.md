---
description: Sprint Kickoff — the one Lead-Architect-in-the-loop moment that opens a sprint. Grounds on live project state, helps the LA pick and scope a cluster of Vikunja tickets, presents a single comprehension gate, and — only after he confirms — opens the sprint and drives it through the normal build → test → merge → ticket → journal arc. Two modes: fresh scope (`<sprint_id> "<theme>"`) or assemble from existing backlog tickets (`--from-tickets <id,id,...> "<theme>"`).
argument-hint: <sprint_id> "<theme>" [context]   |   --from-tickets <id,id,...> "<theme>"
allowed-tools:
  - Read
  - Write
  - Edit
  - Glob
  - Grep
  - Bash
  - Agent
  - Task
  - mcp__vikunja__project_summary
  - mcp__vikunja__get_task
  - mcp__vikunja__list_tasks
  - mcp__vikunja__search_tasks
  - mcp__vikunja__list_labels
  - mcp__vikunja__add_label_to_task
  - mcp__vikunja__add_task_comment
  - mcp__vikunja__create_task
---

# Sprint Kickoff

A **sprint** here is just a named, scoped cluster of Vikunja tickets with one kickoff gate at the front and one debrief at the end. This command opens that cluster. It does NOT put you in a new persona — you remain the session defined by `CLAUDE.md`, running its standard grounding → comprehension-gate → full-arc protocol. "LA" throughout means the Lead Architect: the non-technical project owner who owns the WHY; you own the HOW.

The kickoff is the single LA-in-the-loop moment at a sprint's start: you help him choose and shape the work, you present one gate, he confirms, then you build.

## Invocation

Inspect `$ARGUMENTS` first:

- **Fresh scope (default)** — `/sprint-kickoff <sprint_id> "<theme>" [context]`
  - `$1` = sprint_id (integer, e.g. `19`); `$2` = theme (quoted); `$3+` = optional context.
- **Assemble from existing tickets** — `/sprint-kickoff --from-tickets <id,id,...> "<theme>"`
  - Use when `/sprint-discovery` or the backlog already holds the tickets this sprint should tackle. Read each named ticket with `mcp__vikunja__get_task` and treat them as the scope seed.

If `sprint_id` is omitted or ambiguous, derive the next number from `docs/sprints/` (highest `sprint_N/` + 1) and confirm it with the LA during the gate — never guess silently.

## Phase 0 — Ground yourself (silent; before any LA-facing message)

Run the `CLAUDE.md` session-start grounding, reading on disk, never from a summary:

1. `CLAUDE.md` — standing doctrine (you are re-confirming it, not assuming it).
2. `git log --oneline main` + `git status` — real HEAD and in-flight work. Untracked files are likely another session's; do not touch or stage them.
3. `mcp__vikunja__project_summary` — the live work queue.
4. `docs/sprints/ACTIVE_SPRINT.md` + `docs/TEST_GOVERNANCE.md` §1 — current sprint pointer and gate scope/baseline.
5. `docs/DECISION_REGISTER.md`, plus any ticket, ADR (Architecture Decision Record), or brief the theme or `--from-tickets` names — read them fully.
6. The last completed sprint's `docs/sprints/sprint_<prev>/` close-out note, if present — what shipped, what carried over. Carry-overs are the strongest signal for this sprint's scope.

Summarize none of this back yet. This is your own preparation.

## Phase 1 — Help the LA scope the cluster

Post ONE message that helps him decide, in plain language, acronyms spelled out on first use:

- **Echo** the sprint number, theme, and any named tickets/context back to him.
- **Predecessor digest** (≤6 sentences): what the last sprint delivered, what it missed, what carried over. If there is no prior close-out note, say so plainly and work without that baseline.
- **Grounding observations** (2–5 bullets): non-obvious things from Phase 0 he may want to weigh — decisions already awaiting him, recent ADRs, known-risk areas, backlog tickets that fit the theme. Mark any idea he did not ask for `[PROPOSED]`.
- **Proposed ticket cluster**: the concrete Vikunja tickets you would pull into this sprint (existing ids + any you would create), each with a one-line "why it's in scope." This is the sprint's shape — cheap to redirect now, before you invest.
- **Questions for the LA** (only ones he can answer): scope in/out, priorities, and any capability / quality / security-posture calls. Never a technical implementation question — you own those; research and decide them yourself.

Then let him react and adjust the cluster with you. Iterate here as long as he wants; this phase is free.

## Phase 2 — The comprehension gate (single, then STOP)

When the cluster is settled, present the `CLAUDE.md` comprehension gate in your own words — substantive and substrate-grounded (built from what you read in Phase 0, naming the surfaces; a paraphrase of the kickoff prompt is NOT a gate), mature-not-minimal, sized to the sprint, no point-count cap:

1. **ROLE & AUTHORITY** — who you are for this sprint; which calls you make yourself vs. which are his.
2. **CONTEXT** — where the project stands, as relevant to this sprint (proves grounding).
3. **GOAL** — what the sprint achieves and why he wants it.
4. **TASK + PLAN** — the ticket cluster, the order you'll work it, the resources (subagents, worktree builders, local scripts) you'll spend, and what a closed sprint looks like.
5. **SCOPE** — explicitly in, explicitly out.
6. **INHERITED CONSTRAINTS** — the standing rules that bind this sprint's work (dormant-merge, fleet-pause, LOCALAPPDATA redirect, …) — only the ones that apply.
7. **RISKS + DECISION POINTS** — what could go wrong; which capability / quality / security-posture flips you expect to escalate to him mid-sprint.
8. **ASSUMPTIONS & AMBIGUITIES** — your own reads: what you are assuming, what the theme left open, how you resolved each.
9. **OPEN QUESTIONS** — only ones a non-technical LA can answer.

Then **STOP AND WAIT** for his explicit confirmation. Do not combine the gate and any downstream work in one turn. Authorization to do the work is not authorization to skip the gate.

## Phase 3 — Open the sprint, then drive the arc

Only after he confirms:

1. Create `docs/sprints/sprint_$1/` and write a lightweight **kickoff brief** there (`kickoff-brief.md`) capturing the agreed goal, the ticket cluster, scope in/out, and the decision points you flagged — plain prose, no heavyweight template, just the shape he approved. Leave it as a working-tree file; it ships with the sprint's normal commits.
2. In Vikunja: mark each in-scope ticket "Doing" with a one-line comment, and update `docs/sprints/ACTIVE_SPRINT.md` to point at this sprint. Use canonical label names — verify via `mcp__vikunja__list_labels`, never invent variants.
3. Drive the normal autonomy arc from `CLAUDE.md` — build → test → commit (feature branch) → merge to main → ticket closed citing the shipping SHA → journal entry → regression lock — fanning out subagents and worktree builders across disjoint tickets. Every ship is one atomic motion. Anything that is a new capability, a quality change, or a security/governance posture flip merges DORMANT behind a config flag and waits for his go-live ceremony; work inside an already-approved capability ships LIVE.

Do not return to him for permission on technical choices or obvious next steps. After the gate, the only legitimate stops are the genuine decision-boundary escalations named in `CLAUDE.md`.

## Rules

- **One gate, at the front.** Never manufacture mid-sprint approval gates; the real decision-boundary escalations are not gates, and remain mandatory.
- **Never ask the LA a technical question.** Research, decide, report the decision in plain language.
- **Never commit work directly to main.** Feature branches only; the sole main commit is the reviewed, gate-green merge with its atomic ticket + journal companions. No destructive git, ever.
- **If he changes the sprint_id mid-kickoff**, re-point cleanly before writing anything under the old number.
- **Outputs longer than ~30 lines** go to a workspace file with a short chat pointer — his attention is a managed resource.
- No praise or commendation sections anywhere.

## See also

- [./sprint-discovery.md](./sprint-discovery.md) — shapes the tickets a kickoff assembles.
- [./sprint-debrief.md](./sprint-debrief.md) — closes the sprint this one opens.
- [../../CLAUDE.md](../../CLAUDE.md) — the session doctrine this command runs under.
