# How to Review Fleet Reports — Lead Architect Guide

> # ⛔ RETIRED — THE FLEET THIS DESCRIBES NO LONGER RUNS
>
> **No agent is writing these reports, and no agent is reviewing anyone's work.**
>
> Verified 2026-07-19: `Wake EA Code`, `Wake SDO` and `Wake Co-Lead Architect` are all **Disabled**
> scheduled tasks, disabled deliberately when the autonomous EA/SDO/Co-Lead fleet was retired. Two
> claims in this guide are therefore false and worth naming, because believing them means trusting a
> protection that is not engaged:
>
> - **"Peer review (EA↔SDO, SDO↔Co-Lead) catches the common mistakes"** — no such review happens.
> - **"Within 15 minutes, Co-Lead's next scheduled wake will run"** after you flag `[CAR]` — nothing
>   runs. A `[CAR]` comment is read by nobody. See
>   [LA_CAR_WORKFLOW_HOWTO.md](LA_CAR_WORKFLOW_HOWTO.md), also retired.
>
> **What to do instead:** work through your Claude session directly. Ask what happened overnight, say
> what looks wrong in plain language, and it investigates and reports back in the same conversation.
> Vikunja is still the live work board — that part is real — but the board is driven by you and the
> session, not by a wake-cycle fleet.
>
> On paths: Vikunja does **not** live at `C:\Users\mrbla\BlarAI\tools\vikunja` (that
> path does not exist). The real binary is
> `C:\Users\mrbla\devplatform\tools\vikunja\vikunja-v2.3.0-windows-4.0-amd64.exe`, and
> the start-Vikunja step below has been corrected to use it. The
> `AUTONOMOUS_FLEET_OPERATIONS.md` this file links to was archived under
> `docs/archive/2026/retired_fleet_runbooks/`. Other links below are not maintained
> and some are dead.
>
> **Kept only as historical record.** Do not follow the instructions below.

---

## Table of contents

1. [The one-minute mental model](#1-the-one-minute-mental-model)
2. [Opening your inbox](#2-opening-your-inbox)
3. [What a Fleet Report looks like](#3-what-a-fleet-report-looks-like)
4. [Reading a report step by step](#4-reading-a-report-step-by-step)
5. [Decision: Pass or Flag](#5-decision-pass-or-flag)
6. [Passing a report (no issue)](#6-passing-a-report-no-issue)
7. [Flagging a report (issue found)](#7-flagging-a-report-issue-found)
8. [Common report types, explained in plain English](#8-common-report-types-explained-in-plain-english)
9. [When in doubt, ask Claude Desktop](#9-when-in-doubt-ask-claude-desktop)
10. [Acronym reference](#10-acronym-reference)

---

## 1. The one-minute mental model

The fleet has three kinds of agents that work together:

- **EA** (Execution Agent) — writes code.
- **SDO** (Strategic Development Orchestrator) — plans what EAs should do; reviews their work.
- **Co-Lead** (Co-Lead Architect) — plans what SDOs should do; reviews their work; does merges.

Every time an agent does something meaningful, it writes a **report**. Reports are:

- Saved to disk at `docs/reports/` (permanent audit trail).
- Posted as a task in your Vikunja **Fleet Reports** project (your inbox).

Your job during routine operation:

1. Read reports at your own pace.
2. If nothing looks wrong → mark done.
3. If something looks wrong → flag it with a `[CAR]` comment. Go read [LA_CAR_WORKFLOW_HOWTO.md](LA_CAR_WORKFLOW_HOWTO.md) when that happens.

That's it. No approvals, no merges, no blocking the fleet. You're catching issues after the fact, not gating work before the fact.

---

## 2. Opening your inbox

### Step 2.1 — Make sure Vikunja is running

Vikunja is the task-tracker you already use. It runs locally on your machine. If it's not running, the easiest way to start it is to open your terminal (PowerShell) and run:

```
cd C:\Users\mrbla\devplatform\tools\vikunja
.\vikunja-v2.3.0-windows-4.0-amd64.exe
```

Leave that window minimized. It's serving Vikunja on your local machine.

> **Shortcut**: Vikunja autostarts if you followed the setup in [AUTONOMOUS_FLEET_OPERATIONS.md §2](AUTONOMOUS_FLEET_OPERATIONS.md#2-install-vikunja-autostart-shortcut-path). If it's already running, skip this step.

### Step 2.2 — Open Vikunja in your browser

Open any web browser and go to:

```
http://localhost:3456
```

Log in with the credentials you set up for Vikunja.

### Step 2.3 — Navigate to Fleet Reports

- Look at the **left sidebar** in Vikunja. You'll see a list of projects.
- Click the project titled **Fleet Reports**.
- You are now in your report inbox.

### Step 2.4 — Sort by newest first (recommended)

- At the top of the task list, there's a **sort** icon (usually looks like two arrows stacked).
- Click it and choose **Created — newest first** (or whatever Vikunja calls it in your version).
- Now the most recent reports are at the top.

---

## 3. What a Fleet Report looks like

Each report is a Vikunja task. You'll see a title like:

> **[EA-4 Completion] Task 28 — 2026-04-21 15:45**

Decoded:

- `[EA-4 Completion]` — the report type. This one is EA's completion report for the fourth execution batch (EA-4) of the current sprint.
- `Task 28` — the tracking task for the sprint (Task 28 is Task 7 — the Audit Test Suite work).
- `2026-04-21 15:45` — when the report was posted.

Other titles you'll see:

| Title pattern | Meaning |
|---|---|
| `[EA-N Comprehension]` | EA's recitation of what it understood before doing the work |
| `[SDO Comprehension-Review]` | SDO's verdict on EA's comprehension |
| `[EA-N Completion]` | EA's summary of the work it did |
| `[SDO Completion-Review]` | SDO's independent audit of EA's finished work |
| `[SDO Comprehension]` | SDO's own recitation of the sprint continuation |
| `[Co-Lead Comprehension-Review]` | Co-Lead's verdict on SDO's comprehension |
| `[Co-Lead Completion-Review]` | Co-Lead's audit of SDO's authored EA prompt |
| `[Co-Lead Completion]` | Co-Lead authored a new sprint continuation — **pay attention, priority 4** |
| `[CAR Plan]` | A remediation plan Co-Lead drafted in response to your flag — **pay attention, priority 4** |

Priority 2 (medium) = routine report, review at your leisure.
Priority 4 (urgent) = your action wanted. Look at these first.

---

## 4. Reading a report step by step

### Step 4.1 — Click the task title

Opens the task detail view.

### Step 4.2 — Read the description

The description is a **short summary** written for you — 3 to 5 sentences. It will tell you:

- What the agent did / decided.
- A **verdict** (APPROVED, ADJUST, or REJECTED) if this is a review-type report.
- A **link to the full content on disk** (a path like `docs/reports/task_28/20260421_154532_ea_code_completion_v1.md`).
- A **link to the source Vikunja comment** so you can see it in the tracking task's thread.

### Step 4.3 — If the summary is enough, decide now

If the summary is clear and you trust the agent's call:

- **No issue** → [Pass the report](#6-passing-a-report-no-issue). Done in 30 seconds.
- **Something feels off** → [Flag it](#7-flagging-a-report-issue-found).

### Step 4.4 — If you need more detail, open the disk file

The disk file has the FULL content the agent posted. Every work item, every verdict reason, every commit hash.

To open it:

- In File Explorer, navigate to the path shown in the description.
  - Example: `C:\Users\mrbla\BlarAI\docs\reports\task_28\20260421_154532_ea_code_completion_v1.md`
- Open it with any markdown viewer or text editor. VS Code is great for this.
- Or: ask Claude Desktop to summarize it for you (see [§9](#9-when-in-doubt-ask-claude-desktop)).

### Step 4.5 — Or open the source Vikunja comment

The description has a link like `task/28#comment-54`. Clicking it takes you to the exact comment in the tracking task's thread. Useful if you want to see the surrounding conversation (other comments before and after).

---

## 5. Decision: Pass or Flag

After reading, you have exactly two choices:

| Choice | When | How | Time |
|---|---|---|---|
| **Pass** | Nothing looks wrong. Work looks reasonable. Verdict looks sound. | Click the checkbox next to the task title (marks Done). | 5 seconds |
| **Flag** | Something is off. Scope creep, missing work item, weak review, wrong verdict, anything that makes you go "hmm". | Add a comment starting with `[CAR] <your reason>`. | 2–5 minutes |

If you're unsure, **flag it**. Co-Lead will drill in and either confirm your concern is valid (and remediate) or explain why it's not an issue (and you learn something).

> **Rule of thumb**: your time is worth more than the fleet's time. If a report makes you pause for more than 20 seconds trying to understand it, that's a signal to flag — either the agent didn't explain itself well enough, or there's a real issue.

---

## 6. Passing a report (no issue)

### Step 6.1 — Click the checkbox

In the task detail view (or in the task list), click the checkbox next to the task title. The task moves from "open" to "done".

### Step 6.2 — That's it

The report is dequeued. You won't see it in your list unless you explicitly look at completed tasks.

The disk file at `docs/reports/task_N/...md` stays forever. It's the permanent audit trail. Your "done" status in Vikunja just means *you* have reviewed it.

---

## 7. Flagging a report (issue found)

### Step 7.1 — Leave the task open

Do **NOT** click the checkbox. Keep the task open.

### Step 7.2 — Scroll to the comments section

In the task detail view, scroll down. You'll see a comments area with an input box.

### Step 7.3 — Write your CAR comment

Type your comment starting EXACTLY with `[CAR]` (the brackets matter — this is how Co-Lead recognizes your flag):

```
[CAR] <your reason here>
```

### Step 7.4 — Writing a good CAR reason

**Good**:

> `[CAR] EA-4's completion skipped Work Item 7 (integration Coverage Map). The commit only touches shared/ and launcher/ but never adds the cross-service coverage doc that WI-7 required.`

> `[CAR] SDO's review verdict says APPROVED but the diff includes changes to tools/fleet_observability/ which the EA prompt's negative constraint #3 explicitly forbade.`

> `[CAR] This report looks fine but I don't understand what "ORACLE_5 timing" means and it's central to the work. Please explain.`

**Less helpful** (still works, but Co-Lead will have to guess more):

> `[CAR] Something seems wrong`

> `[CAR] Fix this`

You don't need to be technical. Describe the symptom in plain English. Co-Lead is good at diagnosing root causes from symptoms.

### Step 7.5 — Submit the comment

Click the **Send** / **Submit** button (or press Enter if your Vikunja is set to send-on-enter).

### Step 7.6 — What happens next

- Within 15 minutes, Co-Lead's next scheduled wake will run.
- Co-Lead scans Fleet Reports for `[CAR]` flags.
- Co-Lead reads your reason + the original report.
- Co-Lead drafts a remediation plan, saves it to disk at `docs/reports/corrective_actions/`, and creates a new Fleet Reports task titled `[CAR Plan] ...`.
- The CAR Plan task has **priority 4 (urgent)** and **Gate:Pending-Human** label. You'll spot it easily.

**Go to [LA_CAR_WORKFLOW_HOWTO.md](LA_CAR_WORKFLOW_HOWTO.md)** for what to do when the CAR Plan task shows up.

---

## 8. Common report types, explained in plain English

### Comprehension Report

**What it is**: agent's structured recitation of what it thinks it's supposed to do, BEFORE it does any work.

**Who posts**: EA (of its prompt), SDO (of the sprint's continuation XML).

**What to look for**:
- Does it correctly list all the Work Items?
- Does it respect the negative constraints (things the prompt said NOT to do)?
- Does its "plan of work" make sense?

If the agent misunderstands scope at the comprehension stage, the completion will be wrong too. This is the cheapest place to catch mistakes.

### Comprehension-Review Report

**What it is**: the tier-above agent's verdict on the comprehension.

**Who posts**: SDO (reviewing EA), Co-Lead (reviewing SDO).

**What to look for**:
- The verdict: `APPROVED`, `ADJUST`, or `REJECTED`.
- The observations: is the reviewer being thorough, or rubber-stamping?
- If `ADJUST`: what specific guidance did the reviewer give?
- If `REJECTED`: is the reason sound?

A shallow review is a red flag. Reviews should be specific, not just "looks good."

### Completion Report

**What it is**: agent's summary of the work it just did.

**Who posts**: EA (after committing code), SDO (after authoring a prompt).

**What to look for**:
- Commit hash and file list — does the scope match what the prompt asked for?
- Acceptance checks — did all of them pass?
- Deviations from plan — are any explained?

### Completion-Review Report

**What it is**: an independent audit of the completion against the original goals.

**Who posts**: SDO (auditing EA's commit), Co-Lead (auditing SDO's authored prompt).

**What to look for**:
- Did the reviewer actually check each Work Item, or just the commit message?
- Did they look at the diff? (Good reviews cite specific file changes.)
- Verdict: `APPROVED` or `REJECTED`. Reasons should be specific.

### Co-Lead Completion (sprint continuation)

**What it is**: Co-Lead authored a new sprint's continuation XML. This is the transition between sprints.

**Why it's priority 4 (urgent)**: this is a strategic decision. The continuation XML defines what the next sprint will do. You should actually read it and agree before the fleet commits to a sprint.

**What to do**: open the disk file, read the XML, decide. If you have questions, **work with Claude Desktop** to review it interactively. See the Design-gate section in the main operations runbook (future).

### CAR Plan

**What it is**: Co-Lead's response to a flag you raised. A remediation plan.

**Why it's priority 4**: the fleet will NOT execute this plan until you approve it.

**What to do**: see [LA_CAR_WORKFLOW_HOWTO.md](LA_CAR_WORKFLOW_HOWTO.md).

---

## 9. When in doubt, ask Claude Desktop

You don't have to interpret reports alone. Open Claude Desktop and say things like:

- *"Summarize the disk report at docs/reports/task_28/20260421_154532_ea_code_completion_v1.md and tell me if anything looks risky."*
- *"I see a Completion-Review that APPROVED a commit but the diff includes a file I didn't expect. Help me decide if this is a problem."*
- *"I want to write a CAR flag but I'm not sure how to explain what's wrong. Here's what I observed: <paste>. Can you help me phrase it?"*

Claude Desktop can read the files, look at the git history, and help you form a decision. It's your staff architect. Use it.

---

## 10. Acronym reference

| Acronym | Full term | Role |
|---|---|---|
| **LA** | Lead Architect | You |
| **EA** | Execution Agent | Writes code |
| **SDO** | Strategic Development Orchestrator | Authors prompts for EAs, reviews EA work |
| **Co-Lead** | Co-Lead Architect | Authors prompts for SDO, reviews SDO work, runs merges |
| **CAR** | Corrective Action Report | Remediation flow kicked off by your flag |
| **WI** | Work Item | A single numbered task within an EA prompt |
| **DEC-N** | Locked architectural decision #N | Formal decisions stored as XML |
| **Vikunja** | Your task-tracker | Runs at `http://localhost:3456` |
| **Fleet Reports** | Vikunja project id 8 | Your report inbox |

---

## What's next

- Got a CAR Plan task to review? → [LA_CAR_WORKFLOW_HOWTO.md](LA_CAR_WORKFLOW_HOWTO.md).
- Need to pause/resume the fleet? → [AUTONOMOUS_FLEET_OPERATIONS.md §13–§14](AUTONOMOUS_FLEET_OPERATIONS.md#13-pause-the-fleet-vacation--emergency).
- Want the architectural background? → [docs/DEC13_REPORT_QUEUE_PROPOSAL_v1.xml](../DEC13_REPORT_QUEUE_PROPOSAL_v1.xml).
