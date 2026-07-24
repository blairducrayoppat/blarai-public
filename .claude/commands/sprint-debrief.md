---
description: Sprint Debrief — an LA-facing walkthrough of what a just-completed sprint actually did: headline outcomes with real numbers, decisions taken versus still pending, and downstream impacts. Writes a lightweight close-out note to the sprint folder, surfaces the highlights in chat, answers the LA's questions, then transitions cleanly to the next work. Read-mostly; the only thing it writes is the close-out note.
argument-hint: [sprint_id — defaults to the most-recently-completed sprint if omitted]
allowed-tools:
  - Read
  - Write
  - Glob
  - Grep
  - Bash
  - mcp__vikunja__project_summary
  - mcp__vikunja__get_task
  - mcp__vikunja__list_tasks
  - mcp__vikunja__list_task_comments
---

# Sprint Debrief

Make a just-finished sprint legible to the Lead Architect (LA — the non-technical project owner) and help him decide what comes next. You produce one lightweight artifact, a close-out note in the sprint folder, and otherwise you explain, answer, and transition. You do not build, and you do not commit.

**Arguments**: `$ARGUMENTS`
- `$1` (optional) = sprint_id to debrief. If omitted, default to the most-recently-completed sprint: the highest `docs/sprints/sprint_N/` whose in-scope tickets are closed. Confirm which one you picked in your first line.

## Phase 0 — Ground yourself (silent; read on disk, summarize nothing yet)

**Project framing**
1. `CLAUDE.md` — identity, phase, live decisions.
2. `Use Cases_FINAL.md` — which Use Cases this sprint touched.
3. `docs/DECISION_REGISTER.md` — decisions/ADRs (Architecture Decision Records) relevant to the sprint's work.

**This sprint**
4. `docs/sprints/sprint_<id>/kickoff-brief.md` — what the LA approved at the front (the yardstick for "did we do what we said"). A sprint that predates the kickoff-brief convention won't have one; reconstruct from the journal, closed tickets, and git log, and say so plainly in your orientation.
5. The sprint's tickets in Vikunja (`mcp__vikunja__list_tasks` / `get_task`) — closed vs still open, and the closing comments citing shipping SHAs.
6. `git log --oneline` over the sprint's commit window (kickoff commit or first in-scope ticket → `main`) with `git show --stat` on the significant commits — what actually changed in code versus docs.
7. `BUILD_JOURNAL.md` entries dated in the sprint window, and any `PERFORMANCE_LOG.md` / `docs/performance/` results the sprint produced — the real numbers.

**Downstream + adjacent**
8. `docs/sprints/ACTIVE_SPRINT.md` — current pointer.
9. Open Vikunja items the sprint may have unblocked, blocked, or created — especially anything awaiting an LA decision.

## Phase 1 — Write the close-out note, then surface the highlights

The full walkthrough runs longer than ~30 lines, so it goes to a workspace file, not the chat (his attention is a managed resource). Write `docs/sprints/sprint_<id>/close-out-note.md` — lightweight prose, no heavyweight template — with these sections:

- **Orientation** — sprint number + theme, when it started and finished, the one-sentence driver, and the honest overall outcome (delivered / partially delivered / scope changed).
- **What it was for** — how it advanced BlarAI; which Use Case(s) and ADR(s) it touched.
- **What actually shipped** — a commit-backed list: deliverable, evidence (SHA / file / ticket), type (code / doc / test / config). Real numbers, not adjectives.
- **Headline findings** — the 3–7 things most worth his knowing, each 1–3 sentences with a specific commit or line cite.
- **Impact on dependencies** — how this sprint's output changes the next planned work; anything it was meant to unblock but didn't; new risks or constraints it created. Name the dependent ticket / sprint / Use Case.
- **Open carry-overs** — identified but deliberately not done, with a feel for the backlog size left behind. Each carry-over must already live in a durable queue (a Vikunja ticket); note the id, and if one is missing, flag that as a gap.
- **Decisions awaiting the LA** — split into must-decide-before-next-sprint, should-decide-soon, and nice-to-decide, each one sentence plus a pointer to where the context lives.

Then post a SHORT chat message (not the whole note): 5–10 lines with the outcome, the 2–3 biggest headlines with numbers, the count of decisions waiting on him, and the close-out-note path. Leave the note as a working-tree file; it ships with the sprint's normal commits — do not commit it yourself.

## Phase 2 — Interactive Q&A

Answer his questions in debriefer mode: direct (facts, no marketing language), specific (cite files, line numbers, SHAs), and teacherly (when a question ties to a bigger architectural point, surface the connection). If context wasn't loaded or is ambiguous, say so and offer to dig rather than guessing. Continue until he signals he's ready to move on.

## Phase 3 — Transition to the next work

When he picks a direction, hand off cleanly:

- **Next sprint** — help him settle a one-line theme if he hasn't, then point him at `/sprint-kickoff <N> "<theme>"`. Recommend starting it in a fresh session so kickoff grounds independently with clean context.
- **Something different** — help him scope it in a few questions (a sprint-sized cluster, or a single ticket?), make sure the decision is captured durably in Vikunja, and point him at `/sprint-discovery` if the idea needs shaping first or `/sprint-kickoff` if it's ready.
- **Nothing right now** — confirm the sprint is fully closed out (close-out note written, tickets closed), note that idle is fine, and tell him he can resume any time with `/sprint-debrief <N>` to refresh or `/sprint-kickoff` to start new work.

## Rules

- **Never skip Phase 0.** A debrief without full context misleads him, and he will notice.
- **Never overstate the outcome.** If tickets closed partial or carry-overs are large, say so plainly — his trust in every future debrief rides on this being factual.
- **Never pressure a decision.** Lay out the paths as genuinely different; he picks.
- **Never commit or merge.** The only thing you write is the close-out note, left in the working tree for the normal ship flow.
- **Never ask him a technical question**, and spell out every acronym on first use.
- No praise or commendation sections anywhere.

## See also

- [./sprint-kickoff.md](./sprint-kickoff.md) — opens the sprint this one closes.
- [./sprint-discovery.md](./sprint-discovery.md) — shapes the next sprint's tickets.
- [../../CLAUDE.md](../../CLAUDE.md) — the session doctrine this command runs under.
