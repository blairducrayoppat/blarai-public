# How to Run a Sprint Debrief — Lead Architect Guide

> **Who this is for**: you, the Lead Architect (LA), at the moment a sprint has just completed and you want to understand what happened and decide what to do next.
>
> **What you'll learn**: when a debrief is worth running, how to launch the `/sprint-debrief` slash command, how to navigate the interactive Q&A, and how to transition cleanly into the next workstream.
>
> **How long it takes**: typically 20–45 minutes of focused reading + conversation. Longer if you want to go deep on specific deliverables; shorter if you're already familiar with the sprint's output.

---

## Table of contents

1. [The one-minute mental model](#1-the-one-minute-mental-model)
2. [When to run a debrief](#2-when-to-run-a-debrief)
3. [What a debrief is NOT](#3-what-a-debrief-is-not)
4. [Starting the debrief session](#4-starting-the-debrief-session)
5. [The first message — what to expect](#5-the-first-message--what-to-expect)
6. [The interactive Q&A phase](#6-the-interactive-qa-phase)
7. [Transitioning to the next workstream](#7-transitioning-to-the-next-workstream)
8. [Why the clean-agent break matters](#8-why-the-clean-agent-break-matters)
9. [Troubleshooting](#9-troubleshooting)

---

## 1. The one-minute mental model

A **Sprint Debrief** is a guided walkthrough of a just-completed sprint, run as an interactive session with an agent that has loaded all the relevant context. Its three jobs:

1. **Make the sprint legible** — explain what work was done, what findings came out, and how it connects to the project as a whole.
2. **Surface decisions** — tell you what you now need to decide (blocking next work, strategic direction, carry-overs).
3. **Set up the next workstream** — hand you off, cleanly, to either the next sprint kickoff or whatever alternative you choose.

It does **not** write artifacts, does **not** modify code, does **not** gate the fleet. It's a conversation that ends with you knowing what to do next.

---

## 2. When to run a debrief

Run a debrief when any of the following is true:

- A sprint just closed (the tracking task marked complete + the SCR/SWAGR exist if post-DEC-15).
- You're about to kick off the next sprint but haven't read all the predecessor's outputs and want to be informed going in.
- You've been away from the project for a while and need to catch up on a sprint that ran autonomously.
- A Sprint Auditor's SWAGR surfaced CRITICAL or MAJOR gaps and you want an interactive guide through them rather than reading the SWAGR cold.

You do NOT have to run a debrief every sprint. The **SCR** and **SWAGR** are archived artifacts you can always read directly. The debrief is a *synthesis and guidance layer on top* — use it when synthesis adds value.

---

## 3. What a debrief is NOT

For clarity, three things that look similar but are not this:

| Thing | What it is | When to use |
|---|---|---|
| **Debrief (this)** | Interactive walkthrough + decision-surfacing + next-workstream transition | You want to understand and decide |
| **Sprint Auditor SWAGR** | Autonomous independent gap analysis, archived to disk | You want the artifact (read it yourself) |
| **Sprint kickoff** | Interactive SDV authoring for the NEXT sprint | You've decided what's next |

A common flow is: **SWAGR lands in Fleet Reports** → you read it → (optionally) run **Debrief** to synthesize → run **Sprint Kickoff** to start the next sprint.

---

## 4. Starting the debrief session

Debriefs run in Claude Code CLI from the BlarAI repo — same place you run `/sprint-kickoff`. The reason: Claude Code has full file-read access and loads `CLAUDE.md` automatically, which gives the agent project-wide context for free.

### Step 4.1 — Open PowerShell

Click **PowerShell 7 (x64)** from Start menu or taskbar.

### Step 4.2 — Navigate to the BlarAI repo

```powershell
cd 'C:\Users\mrbla\BlarAI'
```

### Step 4.3 — Launch Claude Code

```powershell
claude
```

*(This command is available once `C:\Users\mrbla\AppData\Local\Python\bin` is on your PATH — which it is since your Python install set that up. If it doesn't resolve, use the full path: `& 'C:\Users\mrbla\AppData\Roaming\Claude\claude-code\2.1.111\claude.exe'`.)*

### Step 4.4 — Run the debrief

At the `>` prompt:

```
/sprint-debrief 7
```

The argument is the sprint number you want debriefed. **Omit it** to debrief the most-recently-completed sprint automatically (recommended for routine use).

The agent will silently load **a lot** of context: CLAUDE.md, ADRs, DECs, Use Cases, the sprint's SDV/SCR/SWAGR (if DEC-15-era), all milestone reports, primary deliverables (like `docs/TEST_AUDIT_FINDINGS.md` for Sprint 7), ledger entries, git log for the sprint's merge ancestry, open Vikunja Pending-Human items, and related downstream task state. This takes 30-90 seconds.

---

## 5. The first message — what to expect

After context loading, the agent posts a single structured message with nine sections:

| § | Section | What it gives you |
|---|---|---|
| 1 | Orientation | 3-5 sentences: sprint name, dates, strategic driver, overall outcome |
| 2 | What this sprint was for | Project-wide context: which Use Cases it touched, which ADRs it leaned on |
| 3 | What was actually delivered | Commit-backed deliverable table with file links |
| 4 | Headline findings | The 3-7 most impactful things the sprint produced or discovered |
| 5 | **Impact on known dependencies** | How this sprint affects the next planned sprint and adjacent work |
| 6 | Open carry-overs | Things identified but not done — backlog for future work |
| 7 | Decisions awaiting LA action | What you actually need to decide: must-do / should-do / nice-to-do |
| 8 | Proposed next workstream options | 2-4 genuine options, framed as different paths |
| 9 | Q&A invite | "What would you like me to dig into?" |

**Read it slowly.** Most useful sections: §4 (findings), §5 (dependency impacts), §7 (decisions), §8 (options).

---

## 6. The interactive Q&A phase

After the first message, the session is yours. Ask anything.

### Useful question patterns

- *"Walk me through theme 2 in more detail — what are the actual tests that need adding?"*
- *"What exactly did EA-3 deliver? Show me the commit."*
- *"How does this affect Task 8 specifically? Which carry-overs are blocking?"*
- *"Why was this item labeled LOW priority instead of MEDIUM?"*
- *"Show me the 5 biggest gaps, ranked."*
- *"I don't understand the 'stale NPU nomenclature' thing — walk me through what's there now and what it should be."*

### What the agent can do in Q&A

- Quote specific line numbers / commit hashes.
- Explain architectural connections you may not have seen (e.g., "this ties to ADR-011 because…").
- Re-read files if its initial read missed detail.
- Admit when something wasn't in its context window and offer to dig.

### What the agent shouldn't do in Q&A

- Invent findings. If you ask about a topic the sprint didn't cover, it should say so.
- Pressure you toward a specific next decision. It proposes options; you decide.
- Write to disk. Debrief is read-only.

Stay in Q&A as long as you need. You're not paying by the minute.

---

## 7. Transitioning to the next workstream

When you've decided, the agent helps you transition. Three paths:

### Path A — Start the next planned sprint

Tell the agent: *"Let's kick off Sprint 8, theme is `<X>`."* (Or whatever sprint + theme.)

The agent will:
1. Confirm the theme (may push back gently if the theme is vague).
2. Give you the exact commands for the next step.

The exact handoff you'll get:

```
Close this Claude Code session. Open a fresh PowerShell terminal
(new session for a new sprint — clean context). Run:

    cd 'C:\Users\mrbla\BlarAI'
    claude
    /sprint-kickoff 8 "<agreed theme>"
```

### Path B — Pick a different workstream

Tell the agent: *"I want to focus on `<thing>` instead of the next planned sprint."*

The agent will help you scope it:
- Sprint-sized? → treat it as a new sprint, use `/sprint-kickoff` with the new theme.
- Single-task workstream? → it'll outline the steps (create Vikunja task / delegate to fleet / handle manually).
- Short spike? → same.

### Path C — Pause the fleet, no new work yet

Tell the agent: *"I need time to think. Don't start anything new."*

The agent will:
1. Confirm the previous sprint is closed out properly.
2. Offer to help you pause the fleet (sets `pause_after_current` or `fleet_paused` in `state.json`) so it doesn't burn Max quota idling.
3. Give you the exit instruction.

---

## 8. Why the clean-agent break matters

The debrief session loads a LOT of context. By the time you decide to kick off Sprint 8, the agent's working memory is saturated with Sprint 7 detail. That's great for the debrief — bad for the next sprint's SDV authoring, which should form its own independent reading.

**Always start Sprint Kickoff in a fresh Claude Code session.** Close the debrief session. Open a new terminal. Relaunch `claude`. Run `/sprint-kickoff`. The Kickoff skill does its own Phase 0 context load and will re-read everything from a clean slate — which is what you want for unbiased SDV drafting.

This is the "clean-agent start" pattern. It's a good habit across all major workstream transitions.

---

## 9. Troubleshooting

### "The agent's first message is missing §5 (dependency impacts)"

Tell it: *"You skipped §5. Please add the dependency-impact analysis — specifically, how does this sprint affect Sprint `<N+1>` and any open ISS items?"*

The agent has the context; it just needs the prompt.

### "The agent says the sprint has no SDV/SCR/SWAGR"

That's correct for Sprint 7 (pre-DEC-15 opt-out). The debrief will reconstruct from ledger + audit-findings doc + milestone reports + git log — still useful, just a degraded structure in §1.

### "The agent proposes next-workstream options that all feel wrong"

Push back: *"None of your options fit. Here's what I'm actually thinking: `<your idea>`. Help me scope that instead."* The agent should pivot.

### "I want to bail and think more before deciding"

Close the session with: *"I need to think. Give me the exit summary."* The agent will give you a compact recap + "resume with `/sprint-debrief <N>` any time" message. You can come back later.

### "I already read the SWAGR — do I need a debrief?"

Maybe not. If the SWAGR was clear and the decisions obvious to you, skip the debrief and run `/sprint-kickoff` directly. The debrief earns its keep when you want the synthesis-and-connections layer on top of the raw artifacts.

### "The agent cites a file/commit/finding and I want to see it myself"

Open it in a second window (VS Code for files, terminal with `git show <hash>` for commits, browser for Vikunja). The debrief session is one window; don't try to view artifacts inside the Claude terminal.

---

## See also

- [LA_SPRINT_KICKOFF_HOWTO.md](LA_SPRINT_KICKOFF_HOWTO.md) — the sibling runbook for starting a new sprint after debrief.
- [LA_FLEET_REPORTS_HOWTO.md](LA_FLEET_REPORTS_HOWTO.md) — reading reports as they arrive during a sprint.
- [LA_CAR_WORKFLOW_HOWTO.md](LA_CAR_WORKFLOW_HOWTO.md) — flagging issues for remediation.
- [docs/DEC15_SPRINT_STRATEGIC_REVIEW_PROPOSAL_v1.xml](../DEC15_SPRINT_STRATEGIC_REVIEW_PROPOSAL_v1.xml) — the architectural basis of SDV/SCR/SWAGR.
- [.claude/commands/sprint-debrief.md](../../.claude/commands/sprint-debrief.md) — the slash command's pre-written prompt.
- [.claude/commands/sprint-kickoff.md](../../.claude/commands/sprint-kickoff.md) — the sibling slash command for next-sprint kickoff.
