# How to Run a Sprint Discovery Session — Lead Architect Guide

> ## SUPERSEDED — `/sprint-discovery` was rewritten on 2026-07-19. Read the command, not this guide.
>
> The authoritative description of what `/sprint-discovery` does is
> [`.claude/commands/sprint-discovery.md`](../../.claude/commands/sprint-discovery.md).
> The command was rewritten by the #945 D7 doc restructure (commit `28dd039a`).
> This guide was written against the old shape and has **not** been rewritten to
> match; it is flagged whole rather than partially refreshed.
>
> **The one that matters most — the safety model is described backwards.** This
> guide says tickets you file will be "picked up by the fleet autonomously" once
> they carry the right labels, because "SDO's proactive scan catches them". That
> is wrong twice: SDO is retired, and **no label makes a ticket run.** The current
> boundary is structural — *nothing executes a ticket until `/sprint-kickoff`
> pulls it into an active sprint* — which is what keeps drafts safe to edit.
>
> So a filed ticket sits until somebody picks it up. That can be a kickoff, or it
> can be you or a session handling it directly in normal flow (the command's own
> handoff explicitly offers an ad-hoc path with no kickoff needed). What will
> **not** happen is a scheduled agent noticing it and starting work unprompted.
>
> **Also wrong:**
>
> - **The command can no longer edit or delete a ticket it created.**
>   `update_task` and `delete_task` are not among its allowed tools, so the
>   "just say: update ticket #X" instruction here will not work. Fix tickets in
>   the Vikunja web UI instead.
> - **The handoff form changed.** It is now
>   `/sprint-kickoff --from-tickets <ids> "<theme>"`, started fresh. That mode
>   makes the named tickets the scope seed; the positional form given here only
>   passes the ids as free-text context.
> - **There is a cap of roughly 15 tickets per session**, which this guide does
>   not mention (so its "the agent proposed 20 tickets" troubleshooting cannot
>   arise).
> - **The `[agent:ba]` description prefix is gone**; what is required now is a
>   work-type label (Testing, Architecture, Infrastructure, Documentation,
>   Security) plus a plain statement that the ticket is a discovery draft.
> - **Sizing is in tickets, not "EA milestones."** The current command asks for a
>   rough count of tickets (small / medium / large each).
> - **Do not rely on the numeric priority mapping given here.** The command says
>   only to set priority deliberately and reserve the top urgency for real
>   blockers; it pins no scale, and project doctrine deliberately keeps the
>   numeric scale out of docs so it cannot drift. Check the board itself.
> - **Tickets are not auto-assigned to you**; the command lacks the assignment
>   tool despite its own text implying otherwise.
> - **"The 9 Use Cases"** is stale — UC-010 (local image generation) is a
>   deliberate tenth, recorded in `Use Cases_FINAL.md` and ADR-033.
>
> Still accurate: the hardware ceiling figure, the runtime-privacy mandate, that
> structure is proposed in chat before any ticket is written, that each created
> ticket id is read back to you, and that you re-run discovery after spikes.

> **Who this is for**: you, the Lead Architect (LA), when you have an idea, a customer need, or a strategic direction you want to explore BEFORE committing to a sprint. You're wearing the Product Manager / voice-of-customer hat; the agent is the Business Analyst / technical translator.
>
> **What you'll learn**: when discovery is the right step (vs. going straight to kickoff), how to frame an exploratory conversation, how the agent grounds aspirational ideas, how Vikunja tickets get produced, and how you transition to `/sprint-kickoff` with confidence.
>
> **How long it takes**: 30–90 minutes typical. An aspirational-vision exploration might take 2–3 sessions before ticket-drafting feels right. Don't rush.

---

## Table of contents

1. [The one-minute mental model](#1-the-one-minute-mental-model)
2. [When to run discovery (vs. go straight to kickoff)](#2-when-to-run-discovery-vs-go-straight-to-kickoff)
3. [Starting the discovery session](#3-starting-the-discovery-session)
4. [The conversation patterns](#4-the-conversation-patterns)
5. [How the agent grounds aspirational ideas](#5-how-the-agent-grounds-aspirational-ideas)
6. [Ticket-drafting phase](#6-ticket-drafting-phase)
7. [Handoff options at the end](#7-handoff-options-at-the-end)
8. [Troubleshooting](#8-troubleshooting)

---

## 1. The one-minute mental model

Before a sprint starts, you need enough clarity about what to build and why. The **Sprint Discovery** session is for that clarity.

You bring: a topic, a customer need, a pain point, or just a vague "I want X to work better." The agent brings: full project context (Use Cases, ADRs, hardware constraints, recent sprint lessons), Vikunja-writing ability, and a Business-Analyst skepticism that grounds aspiration in reality.

Together you produce: **Vikunja tickets** that describe the work in enough detail that a future `/sprint-kickoff` session can author a well-grounded Strategic Design Vision (SDV) from them.

The session does NOT produce code, repo docs, or an SDV. It produces **tickets** plus a decision about what to do next with them.

---

## 2. When to run discovery (vs. go straight to kickoff)

### Run discovery when any of these is true

- You have an **aspirational idea** but you're not sure how it lands technically.
- You have a **customer need** stated in outcome-vocabulary (*"I want it to feel snappier"*) that needs translating.
- You're coming off a sprint whose SWAGR surfaced **carry-overs** you need to decide how to structure.
- You have **multiple competing ideas** and you want a neutral third-party (the agent) to help you pick.
- You **don't know what the next sprint should be** and you want to discover it instead of picking arbitrarily.

### Skip discovery, go straight to `/sprint-kickoff`, when

- You already know exactly what the next sprint is and its theme is obvious (e.g., "Package A from Sprint 7's debrief — the 13 HIGH items").
- You're doing pure cleanup/maintenance work that doesn't need product-level shaping.
- You ran a discovery session recently and the tickets still reflect current intent.

**Rule of thumb**: if you could write a good two-sentence sprint theme in 30 seconds, skip discovery. If you'd need to think for 5 minutes, run discovery.

---

## 3. Starting the discovery session

### Step 3.1 — Open PowerShell and launch Claude Code

```powershell
cd 'C:\Users\mrbla\BlarAI'
claude
```

### Step 3.2 — Invoke the slash command

Two flavors:

**With a seed topic** (recommended if you have one):

```
/sprint-discovery "I want Task 8 to focus on fail-closed test coverage because Sprint 7 flagged 13 HIGH items around it"
```

**No seed** (you want the agent to observe the state and propose directions):

```
/sprint-discovery
```

### Step 3.3 — Let the agent load context silently

Takes 45–90 seconds. The agent reads CLAUDE.md, the 9 Use Cases, ADRs, recent SWAGR, ledger, `docs/sprints/ACTIVE_SPRINT.md`, Vikunja project summary, and any grep-matches for the seed topic.

---

## 4. The conversation patterns

The agent will probe, ground, and challenge — gently. You should expect questions like:

### Probing questions

- *"When you say you want fail-closed coverage, do you mean the structured error-code pattern specifically, or broader behavioral coverage of every fail-closed path?"*
- *"What's the smallest version of this that would be useful if we only had 2 days?"*
- *"Who's the user for this — you, or future BlarAI deployments generally?"*

### Grounding statements

- *"Sprint 7 flagged 13 HIGH items; shipping all of them is \~10-12 EA milestones which is heavy for one sprint. Alternatives: (a) Package A as-is, (b) Package A minus the launcher cluster, (c) split across Sprint 8 + 9. Which fits your risk posture?"*
- *"ADR-011 retired the NPU path. If we're touching those tests, we can also rename the stale NPU identifiers in the same sprint cheaply, or defer as a separate cleanup pass."*

### Challenging back

- *"What would convince you this is NOT the right next thing to build?"*
- *"If we don't do this, what breaks — concretely?"*

### You're allowed to push back

The agent is deliberately steelmanning the opposite of whatever you just said. Don't take it personally — it's the job. Your response can be *"I already considered that; the answer is X"* and the agent moves on.

---

## 5. How the agent grounds aspirational ideas

You're a vibe coder. You may describe things in outcome-vocabulary:

> *"I want the system to feel more aware of my context."*

The agent doesn't say "great idea." It does three things:

1. **Restates** in its own words: *"Hearing: you want the assistant to reference prior interactions or recent repo state more often in its responses."*
2. **Proposes concrete interpretations**:
   - *(A) Session-state persistence enhancement: the Assistant Orchestrator keeps more cross-session context.*
   - *(B) Claude Code project-side memory expansion: more things written to CLAUDE.md auto-maintenance.*
   - *(C) PA/AO pipeline awareness: policy agent pre-checks incorporate session history.*
3. **Lets you pick or correct**: *"Which of these matches, or am I off?"*

This is the translation loop. Aspirational → grounded → technical → Vikunja ticket.

### When it hits a hard constraint

The agent will flag it immediately:

- *"That would require \~8 GB beyond the 31.3 GB memory ceiling — not feasible without removing Y. Do you want to adjust the idea or consider the ceiling work a prerequisite?"*
- *"Any external network call in runtime code is out-of-scope per the privacy mandate. Is there an offline equivalent of what you want?"*
- *"This doesn't map to any of the 9 Use Cases. Either it's a scope expansion (needs an explicit project-level decision), or it's a new UC candidate. Which?"*

You can still proceed — but the constraint is now explicit.

---

## 6. Ticket-drafting phase

When conversation reaches enough clarity, the agent proposes a **ticket structure in chat first** (not yet written to Vikunja). Typically:

```
Proposed sprint-scale theme: "<theme>"
Estimated sprint size: <X> EA milestones
Target Use Case alignment: <UC numbers>

Tickets:
1. [Epic] <title>          — <1-paragraph>
2. [Sub-ticket of 1] <title> — <description>
3. ...

Research spikes (if any):
S1. [Spike] <question>
```

### Your job at this stage

Review each proposed ticket:
- Is the title accurate?
- Is the description specific enough that a future EA reading it knows what to build?
- Is the priority right?
- Are there missing tickets? Extraneous ones?

Redirect freely. *"Combine 2 and 3; split 4 into 4a/4b; drop the research spike."* The agent iterates.

### Approve → the agent writes tickets to Vikunja

Only after you approve does the agent actually create tickets. Each ticket:
- Description starts with `[agent:ba]` prefix (audit trail).
- Frontmatter-style section with customer intent, technical interpretation, acceptance criterion, dependencies.
- Correct labels applied.
- Priority set (2 = backlog-ish, 3 = sprint-candidate, 4 = urgent).
- Assigned to `blarai` so you see it in your list.

The agent reads back each ticket ID after creating — you can verify in Vikunja immediately.

---

## 7. Handoff options at the end

Three paths the session can close on:

### Path A — Tickets are sprint-sized

The agent gives you a ready-to-paste command:

```
Close this session. Fresh PowerShell. Then:
    cd 'C:\Users\mrbla\BlarAI'
    claude
    /sprint-kickoff <N> "<theme>" "Context tickets: #<ids>. Discovery session <date> explored <summary>."
```

You move into sprint kickoff with tickets as prior context. The kickoff agent reads the tickets as part of its Phase 0 load.

### Path B — Tickets are smaller than a sprint

Maybe it's 2-3 tickets fitting inside another sprint's slack, or a couple of tasks a human can knock out quickly. The agent tells you:
- Which tickets can be picked up by the fleet autonomously (if they're in the right project with the right labels, SDO's proactive scan catches them).
- Which tickets LA or a teammate handles directly.
- No sprint kickoff needed; no SDV needed.

### Path C — Tickets include research spikes

If there's enough uncertainty that committing to a sprint would be premature, the agent suggests running the spikes first:
- Spike tickets go into Infrastructure or Core Development project at priority 3.
- Fleet picks them up in normal flow.
- After results, you re-run `/sprint-discovery` with the new grounding, then kickoff with high confidence.

### Clean-session break

Same pattern as debrief → kickoff. Close the discovery session. Open a fresh terminal. The next agent (whether kickoff, or fleet-autonomous work, or human work) starts with no discovery-session bias.

---

## 8. Troubleshooting

### "The agent keeps proposing small technical interpretations; I want it to think bigger"

Tell it: *"Step back. What's the largest strategic move here that's still bounded by the 9 Use Cases?"* It'll recalibrate.

### "The agent is too skeptical / grounding everything too hard"

Push back: *"Let's say budget and time aren't constraints. What's the best version of this idea?"* Then separately: *"Now let's reality-check each piece. Which survives our actual constraints?"*

### "I don't have a seed topic and the agent's 'observed signals' don't resonate"

Say so. *"None of those signals are what's on my mind. I'm actually thinking about `<new topic>`. Let's start there."* The observed-signals list is a starter, not a cage.

### "We've been talking for 45 minutes and I'm not sure what to write as tickets"

The agent should propose. If it hasn't, ask: *"What's your current best guess at a ticket structure given what we've discussed? Show me a draft even if it's rough."*

### "I want to bail and think more before writing tickets"

Say: *"Let's pause here. Summarize where we landed and what's still open. I'll come back to a new session when I've thought more."* The agent gives you a recap; you exit cleanly; next session picks up from the recap.

### "I wrote tickets but now realize they're wrong — can the agent edit them?"

Yes. Say: *"Update ticket #X to say Y."* It uses `mcp__vikunja__update_task`. For deletions, ask explicitly (*"Delete ticket #X, we decided against it"*).

### "The agent proposed 20 tickets; that feels like too much"

Good instinct. Say: *"This is too many. Pick the 5-7 most important for this sprint. Everything else goes to backlog with priority 1."* The agent will re-rank and adjust priorities.

### "I want to discuss something that violates an ADR"

Totally fine to discuss. The agent will flag the ADR violation. If you want to proceed, the proper path is: (1) create a proposed ADR revision or new ADR, (2) in a separate workstream decide whether to ratify it, (3) then discovery can produce tickets under the new ADR. The agent will guide you to that sequence.

---

## See also

- [LA_OPERATIONS_INDEX.md](LA_OPERATIONS_INDEX.md) — master runbook index, which doc to open for which situation.
- [LA_SPRINT_KICKOFF_HOWTO.md](LA_SPRINT_KICKOFF_HOWTO.md) — the typical next step after successful discovery.
- [LA_SPRINT_DEBRIEF_HOWTO.md](LA_SPRINT_DEBRIEF_HOWTO.md) — retrospective for completed sprints; often a good precursor to discovery.
- [LA_FLEET_REPORTS_HOWTO.md](LA_FLEET_REPORTS_HOWTO.md) — where in-flight reports land.
- [LA_CAR_WORKFLOW_HOWTO.md](LA_CAR_WORKFLOW_HOWTO.md) — how to flag issues once sprints are running.
- [.claude/commands/sprint-discovery.md](../../.claude/commands/sprint-discovery.md) — the slash command source (for reference).
