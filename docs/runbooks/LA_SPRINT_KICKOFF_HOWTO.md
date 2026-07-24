# How to Kick Off a New Sprint — Lead Architect Guide

> ## SUPERSEDED — `/sprint-kickoff` was rewritten on 2026-07-19. Read the command, not this guide.
>
> The authoritative description of what `/sprint-kickoff` does is
> [`.claude/commands/sprint-kickoff.md`](../../.claude/commands/sprint-kickoff.md).
> The command was rewritten by the #945 D7 doc restructure (commit `28dd039a`),
> which stripped the retired fleet personas and paperwork. This guide was written
> against the old shape and has **not** been rewritten to match — a partial
> refresh would make the stale remainder look maintained, so it is flagged whole.
>
> **The four things here that would actually cost you something:**
>
> 1. **"You can now close the Claude Code session. The fleet takes over."** — §7.
>    False, and the most expensive error in this file. The persona fleet this
>    refers to (EA / SDO / Co-Lead, on scheduled wakes) is retired, and nothing
>    picks a sprint up on its own. The same session drives the whole arc after the
>    gate: build → test → commit → merge → ticket closed → journal. **Closing the
>    session abandons the sprint.**
>
>    (A headless *coding* fleet does still exist and is live — but a session
>    invokes it deliberately via `/dispatch` for a scoped coding job. It is not a
>    thing that takes a sprint over while you are away.)
> 2. **The comprehension gate is missing entirely.** The current command's Phase 2
>    presents the full `CLAUDE.md` gate — ROLE & AUTHORITY / CONTEXT / GOAL /
>    TASK + PLAN / SCOPE / INHERITED CONSTRAINTS / RISKS + DECISION POINTS /
>    ASSUMPTIONS & AMBIGUITIES / OPEN QUESTIONS — and then **stops and waits for
>    you**. This guide describes an "approve the SDV" step instead. The gate is
>    your real decision point.
> 3. **No Strategic Design Vision (SDV) is produced.** The command writes a
>    lightweight `kickoff-brief.md` in plain prose. Everything here about 14 SDV
>    sections, SDV frontmatter, committing the SDV, and `Gate:Pending-Human`
>    label flips describes work that no longer happens.
> 4. **§8 "What happens autonomously after sign-off" is void.** SDO wakes, EA
>    Code, the peer-review lattice, the Fleet Reports inbox and
>    `docs/scheduled/ea_queue/` are all retired; `docs/scheduled/` does not exist.
>
> **Also:** the `claude.exe` path in §4 pins version `2.1.111`, which is not
> installed. And there is a second invocation mode this guide never mentions —
> `/sprint-kickoff --from-tickets <id,id,…> "<theme>"` — which is how
> `/sprint-discovery` now hands off.
>
> Kept for historical reference. The dead links below are left as-is rather than
> repointed, because the procedures they belong to are themselves retired.

> **Who this is for**: you, the Lead Architect (LA), at the moment a new sprint is starting. This is your single biggest strategic touchpoint — the Strategic Design Vision (SDV) you sign off here is the contract the fleet measures itself against for the entire sprint.
>
> **What you'll learn**: when a sprint kickoff is triggered, where exactly to do the kickoff (which app, which window), how to use the `/sprint-kickoff` slash command, how to iterate the SDV to sign-off, and what happens after.
>
> **How long it takes**: roughly 30–60 minutes of focused collaboration with Co-Lead for the SDV itself. Then you're hands-off until reports start coming in.

---

## Table of contents

1. [The one-minute mental model](#1-the-one-minute-mental-model)
2. [When does a sprint kickoff happen?](#2-when-does-a-sprint-kickoff-happen)
3. [Pre-kickoff prep (5 minutes)](#3-pre-kickoff-prep-5-minutes)
4. [Starting the kickoff session](#4-starting-the-kickoff-session)
5. [The `/sprint-kickoff` slash command walkthrough](#5-the-sprint-kickoff-slash-command-walkthrough)
6. [Iterating the SDV draft](#6-iterating-the-sdv-draft)
7. [Signing off](#7-signing-off)
8. [What happens autonomously after sign-off](#8-what-happens-autonomously-after-sign-off)
9. [Alternative: without the slash command](#9-alternative-without-the-slash-command)
10. [Troubleshooting](#10-troubleshooting)

---

## 1. The one-minute mental model

Every sprint starts with a signed Strategic Design Vision (SDV). The SDV is a markdown document authored collaboratively by you and the Co-Lead Architect, committed to git, and referenced by every agent in the fleet for the duration of the sprint.

The key principle: **LA is in the loop at sprint boundaries, not during work.** You spend \~30–60 minutes here, then the fleet runs autonomously for days until the next sprint boundary. DEC-15 added Strategic Completion Report (SCR) and Strategic Work Analysis and Gap Report (SWAGR) at sprint *end* so you also get a retrospective read; those require no LA action, just reading.

---

## 2. When does a sprint kickoff happen?

You'll know it's time when **both** of these show up in Vikunja:

1. A new **Fleet Reports** task titled `[Co-Lead Completion] Sprint <N+1> Continuation — <date>` at **priority 4 (urgent, red)**, assigned to `blarai`. This is Co-Lead telling you "I've detected the previous sprint is complete and staged the next one; your SDV sign-off is needed."
2. A **new tracking task** in **BlarAI Core Development** project (or a dedicated sprint project if you've moved to per-sprint Vikunja projects) tagged with `Gate:Pending-Human`, with Co-Lead's authored continuation XML referenced in the description.

The Fleet Reports task is your reader-friendly surface; the tracking task is the actual gate that closes when you sign off.

---

## 3. Pre-kickoff prep (5 minutes)

Before starting the session, **read these so you arrive informed**:

### 3.1 Predecessor sprint's SWAGR

If there is one: `docs/sprints/sprint_<previous>/Strategic_Work_Analysis_and_Gap_Report_Sprint_<previous>_*.md`.

The Sprint Auditor's gap-report is the single most valuable input for the next sprint. It tells you what went wrong last time, what was missed, what risks are carrying over. If there are CRITICAL gaps, consider whether this sprint should address them.

*(For Sprint 8 specifically: predecessor is Sprint 7, which opted out of DEC-15 artifacts, so no SWAGR will exist. You'll kick off Sprint 8 without a predecessor gap-report. All future sprints have one.)*

### 3.2 Active Sprint pointer

Open `docs/sprints/ACTIVE_SPRINT.md` — the human-readable state of the fleet. Confirms the current sprint is finished and the new one is being kicked off.

### 3.3 Your own strategic intent

Spend 5 minutes thinking: **what's this sprint *for*?** Write down 2–3 sentences in your own words before opening the kickoff session. Having your own clear intent prevents Co-Lead's drafting from anchoring you.

### 3.4 Anything from stakeholders / open issues

If there are specific requests driving this sprint (e.g., "we need to address ISS-3 before the next use-case rollout"), have those ISS or Vikunja task IDs handy to mention in the kickoff.

---

## 4. Starting the kickoff session

**Always use Claude Code CLI from the BlarAI repo directory.** Not Claude Desktop, not Claude Chat. The reason: Claude Code can read files, edit files, commit to git, AND call the Vikunja MCP server — all in one session. Other interfaces can discuss but can't produce the SDV artifact end-to-end.

### Step 4.1 — Open PowerShell

Click the **PowerShell 7 (x64)** shortcut from your Start menu or taskbar.

### Step 4.2 — Navigate to the BlarAI repo

```powershell
cd 'C:\Users\mrbla\BlarAI'
```

### Step 4.3 — Launch Claude Code

```powershell
& 'C:\Users\mrbla\AppData\Roaming\Claude\claude-code\2.1.111\claude.exe'
```

The first-time prompt asks to trust this folder — answer **yes**. Claude Code auto-loads `CLAUDE.md` which already contains the DEC-15 convention, so the session already knows about sprints, SDV templates, Fleet Reports, assignee conventions, etc.

---

## 5. The `/sprint-kickoff` slash command walkthrough

At the Claude Code prompt (`>`), type:

```
/sprint-kickoff 8 "Test governance hardening"
```

### What the arguments mean

- `8` — the new sprint number. Must match the `sprint_id` Co-Lead assigned to the new continuation (you'll see it in the new tracking task's title or in `docs/active_tasks.yaml`).
- `"Test governance hardening"` — your theme in quotes. A 2–5 word working title. Can be refined during the session.

### Optional third argument

You can add strategic context in the third argument:

```
/sprint-kickoff 8 "Test governance hardening" "Focus on EA-5's carry-overs; defer any new test infrastructure to Sprint 9"
```

### What the slash command does

The skill runs a pre-written prompt that tells Co-Lead to:
1. Load its full context (CLAUDE.md, DEC-15 proposal, templates, predecessor SWAGR, recent ledger, active tracking task in Vikunja).
2. Post a **first LA-facing message** containing:
   - A confirmation echo of what you said.
   - A predecessor digest (\~8 sentences of what last sprint did and missed).
   - 2–5 strategic-context observations (open gates, unresolved issues, risks).
   - A proposed **outline** of all 14 SDV sections.
   - 3–7 **specific questions** for you to answer before full drafting.
3. Wait for your answers before drafting the full SDV.

This is intentional: the outline is a cheap iteration surface. If you redirect a whole section at outline stage, Co-Lead doesn't waste effort on a full draft that won't survive.

---

## 6. Iterating the SDV draft

### Step 6.1 — Answer Phase 1 questions

Reply to Co-Lead's first message answering each question directly. Short answers are fine. If a question doesn't apply or you don't care, say so ("defer to your judgment").

### Step 6.2 — Review the outline

Co-Lead's proposed SDV outline will list all 14 sections with 1–3 sentences each. **Call out**:
- Sections that look right (you're signaling these to lock in).
- Sections you want rewritten (say what's wrong).
- Sections to delete (rare but valid).
- Sections to add (usually scope boundaries or risks you saw they missed).

### Step 6.3 — Receive the full SDV draft

After your outline feedback, Co-Lead writes the complete SDV to `docs/sprints/sprint_<N>/strategic_design_vision.md` and tells you where to find it.

### Step 6.4 — Read it in a second window

Don't try to review it inside the terminal. Open it in VS Code or any markdown viewer for easier reading. Keep Claude Code open in the other window for replies.

### Step 6.5 — Give focused feedback

For each section, you want:
- **Accurate** (reflects your intent).
- **Specific** (measurable success criteria, not vague goals).
- **Honest** (risks called out, unknowns acknowledged).
- **Proportional** (effort estimate tracks the scope).

Don't chase perfection. 2–3 revision rounds is normal. If you're at round 4+, that's a signal something's fundamentally misaligned — back up and restate the theme.

### Step 6.6 — Say "approve" / "sign off" when done

Co-Lead waits for clear approval language. Examples: "looks good, commit it", "sign off", "approved", "go ahead and commit".

---

## 7. Signing off

When you approve, Co-Lead automatically:

1. Fills `la_approved_on` and `la_approved_by` in the SDV frontmatter.
2. Commits the SDV: `git add docs/sprints/sprint_<N>/strategic_design_vision.md && git commit ...`.
3. Updates `docs/sprints/ACTIVE_SPRINT.md` (the human-pointer) to mark the SDV ✅ and reflect the sprint is formally underway.
4. Closes `Gate:Pending-Human` on the tracking task and applies `Gate:Approved`.
5. Adds a comment on the tracking task announcing sprint start.
6. Emits a Fleet Reports task announcing the kickoff, assigned to you.
7. Sends you a compact closing message summarizing all of the above with commit hashes.

You can now close the Claude Code session. The fleet takes over.

---

## 8. What happens autonomously after sign-off

Over the next hours / days:

- **SDO next wake**: reads your SDV, cross-references against planned EA milestones, authors EA-1's prompt to `docs/scheduled/ea_queue/staging/`.
- **Co-Lead next wake**: Phase 1b reviews SDO's EA-1 staged prompt.
- **SDO subsequent wake**: Phase 3 moves EA-1 prompt from staging → queue.
- **EA Code**: picks up EA-1, posts comprehension, waits for SDO review, executes, posts completion.
- **Full DEC-12 peer-review lattice** fires for every milestone.
- **Fleet Reports inbox** accumulates entries as the sprint progresses, all assigned to you.

Your next LA touchpoints during the sprint (NOT required, all optional):
- Read reports at your pace.
- Flag any concerning report with `[CAR]` for remediation (see `LA_CAR_WORKFLOW_HOWTO.md`).
- Approve merge-gate escalations if Co-Lead trips the runaway-LOC (Lines of Code) threshold (roughly: a mostly-docs sprint may trip if ≥500 lines change; a mostly-code sprint probably fits under).

Your next **required** LA touchpoint: **Sprint <N+1> kickoff**, when Sprint <N> finishes and the cycle repeats.

---

## 9. Alternative: without the slash command

If the `/sprint-kickoff` slash command isn't available or fails:

### Manual kickoff procedure

1. Open Claude Code from the repo (per §4).
2. Your first message, verbatim:
   > *"Kick off Sprint `<N>` per DEC-15. Theme: `<your theme>`. Read `docs/sprints/ACTIVE_SPRINT.md`, the predecessor SWAGR at `docs/sprints/sprint_<prev>/Strategic_Work_Analysis*` (if it exists), and the SDV template at `docs/sprints/_templates/strategic_design_vision_template.md`. Before drafting the full SDV, give me an outline of all 14 sections with 1–3 sentences each plus 3–5 questions. We'll iterate."*
3. From there, follow §5 onward — same iteration flow, just without the skill's pre-priming.

This is functionally equivalent; the skill just pre-packages the prompt.

---

## 10. Troubleshooting

### "I don't see a Fleet Reports task asking me to kick off"

- Check `docs/active_tasks.yaml` — if the previous sprint's entry is still present without being marked complete, the fleet hasn't finished the predecessor yet. Wait.
- Check Co-Lead's scheduled-task logs for errors (`tools/scheduled-tasks/logs/`).
- If you WANT to kick off Sprint `<N+1>` ahead of the previous one completing: ask Claude Desktop to help pause the fleet and manually advance the roster. Not recommended — safer to let the fleet finish.

### "I don't know what sprint_id to use"

Open `docs/sprints/ACTIVE_SPRINT.md` — the "Currently active" section shows the in-flight sprint number. The new sprint is one higher. Or check the new tracking task Co-Lead created in Vikunja; its description includes the sprint_id.

### "The SDV template feels like too much structure for a small sprint"

Fill every section anyway. Use `N/A — <reason>` liberally for sections that don't apply. The structure has downstream consumers (Sprint Auditor's SWAGR template mirrors it section-for-section). Short `N/A` entries are preferable to missing sections.

### "I approved but nothing committed / gate didn't close"

- Check `git log --oneline -3` — was the commit actually made?
- Check Task 28's (or the new sprint's tracking task) labels — did `Gate:Pending-Human` clear?
- If either failed, tell Claude Code in the same session: *"Retry the Phase 4 sign-off steps."*

### "Co-Lead drafted the SDV but I want to start over with a different theme"

Tell Claude Code: *"Abandon this SDV draft. Delete the sprint_<N>/ directory and let me restart with a new theme."* Co-Lead will clean up and you re-run `/sprint-kickoff <N> "<new theme>"`.

### "Something feels fundamentally wrong with this sprint's scope"

That's what the kickoff is for — catch it here. Tell Co-Lead explicitly what's wrong. Don't sign off until you're convinced the SDV reflects what you actually want. A bad SDV = a bad sprint; the gate is thin after this.

---

## See also

- [LA_FLEET_REPORTS_HOWTO.md](LA_FLEET_REPORTS_HOWTO.md) — how to read the reports that come in during the sprint.
- [LA_CAR_WORKFLOW_HOWTO.md](LA_CAR_WORKFLOW_HOWTO.md) — how to flag issues found in reports.
- [LA_REBOOT_CHECKLIST.md](LA_REBOOT_CHECKLIST.md) — post-reboot verification.
- [AUTONOMOUS_FLEET_OPERATIONS.md](AUTONOMOUS_FLEET_OPERATIONS.md) — pause/resume and infrastructure.
- [docs/DEC15_SPRINT_STRATEGIC_REVIEW_PROPOSAL_v1.xml](../DEC15_SPRINT_STRATEGIC_REVIEW_PROPOSAL_v1.xml) — the full DEC-15 architectural spec.
- [docs/sprints/_templates/strategic_design_vision_template.md](../sprints/_templates/strategic_design_vision_template.md) — the SDV template Co-Lead fills for you.
- [.claude/commands/sprint-kickoff.md](../../.claude/commands/sprint-kickoff.md) — the slash command's pre-written prompt (for reference).
