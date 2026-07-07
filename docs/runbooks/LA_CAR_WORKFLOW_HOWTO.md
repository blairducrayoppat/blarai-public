# How to Run a Corrective Action — Lead Architect Guide

> **Who this is for**: you, the Lead Architect (LA), when you've found an issue in a Fleet Report and want it fixed.
>
> **What you'll learn**: the full Corrective Action Report (CAR) workflow — from flagging an issue, to reviewing Co-Lead's remediation plan, to approving it, to verifying the fix.
>
> **How long the whole cycle takes**: about 20–40 minutes of your active time spread across 1–3 hours (fleet does most of the work in between your touches).

Before reading this, read [LA_FLEET_REPORTS_HOWTO.md](LA_FLEET_REPORTS_HOWTO.md) first — it covers basic report-reading and the point where you decide to flag something.

---

## Table of contents

1. [What a CAR is, and why it exists](#1-what-a-car-is-and-why-it-exists)
2. [The five stages of a CAR](#2-the-five-stages-of-a-car)
3. [Stage 1 — You flag an issue](#3-stage-1--you-flag-an-issue)
4. [Stage 2 — Co-Lead drafts a plan](#4-stage-2--co-lead-drafts-a-plan)
5. [Stage 3 — You review the plan](#5-stage-3--you-review-the-plan)
6. [Stage 4 — Fleet executes](#6-stage-4--fleet-executes)
7. [Stage 5 — You verify and close](#7-stage-5--you-verify-and-close)
8. [What if the plan is wrong?](#8-what-if-the-plan-is-wrong)
9. [What if the fix doesn't fix it?](#9-what-if-the-fix-doesnt-fix-it)
10. [Full worked example](#10-full-worked-example)

---

## 1. What a CAR is, and why it exists

**CAR = Corrective Action Report.** It's a structured way for you to say "this agent work isn't right, please fix it" without having to know or write the technical fix yourself.

The fleet is designed so that 95% of the time, agents work correctly. Peer review (EA↔SDO, SDO↔Co-Lead) catches the common mistakes. But sometimes an issue slips through and only a human eye notices it. That's what CARs are for.

**The promise of CAR**:

- You don't need to write code.
- You don't need to know git.
- You describe the problem in plain English.
- Co-Lead figures out the fix and writes the plan.
- You approve or reject the plan.
- Fleet executes.
- You verify the fix.

**What CAR is NOT for**:

- Bugs in the fleet infrastructure itself (scheduled tasks broken, wake templates wrong). For those, talk to Claude Desktop directly.
- New features or scope changes. Those go through sprint-continuation authoring, not CAR.
- Quick one-off questions ("what does this mean?"). For those, just ask Claude Desktop.

---

## 2. The five stages of a CAR

A complete CAR cycle has these stages. You are active in stages 1, 3, and 5. The fleet does stages 2 and 4 autonomously.

| Stage | Who's active | What happens | Your time |
|---|---|---|---|
| **1. Flag** | You | Comment `[CAR] <reason>` on a Fleet Reports task | 2–5 min |
| **2. Plan** | Co-Lead | Reads your flag, drafts remediation plan, creates CAR Plan task | 0 — autonomous |
| **3. Review** | You | Read the CAR Plan, approve or reject | 5–15 min |
| **4. Execute** | SDO + EA | Authors corrective prompt, EA executes it, all peer-reviewed | 0 — autonomous |
| **5. Verify** | You | Read the final completion-review, confirm the fix works | 5–10 min |

Total of your active time: roughly **20–40 minutes** across 1–3 hours of real time.

---

## 3. Stage 1 — You flag an issue

### Step 3.1 — Find the problematic report

In Vikunja → **Fleet Reports** project → find the task you're concerned about.

This could be any report type: a comprehension, a review, a completion. If the report made you stop and think "this doesn't look right", that's a CAR candidate.

### Step 3.2 — Leave the task open

Do NOT mark the task as Done. You want to keep it open as the "originating" report for the CAR.

### Step 3.3 — Add a `[CAR]` comment

Scroll down in the task to the comments area. Type a comment that starts EXACTLY with `[CAR]` (brackets matter):

```
[CAR] <your reason here>
```

### Step 3.4 — Phrasing your reason

A good CAR reason has three parts:

1. **What you observed** (the symptom, not the diagnosis).
2. **Why it concerns you** (what you expected vs. what you see).
3. **What would satisfy you** (what the fixed version would look like).

**Example 1 — scope concern**:

```
[CAR] EA-4's completion report says 20 files changed but only 12 match
the EA prompt's scope list. 8 files are outside scope.

I'm concerned this violates the EA prompt's negative constraint #3
which said "no changes to tools/fleet_observability/".

I'd want either (a) those 8 files reverted, or (b) an explanation
of why they're actually in-scope that I missed.
```

**Example 2 — weak review**:

```
[CAR] SDO's completion-review verdict was APPROVED in two sentences.
I'd expect a more thorough audit — specifically re-checking the
Coverage Map format that was WI-7.

Please re-do the completion review with actual diff inspection
and verify WI-7's Coverage Map exists in the committed files.
```

**Example 3 — unclear report (a valid CAR!)**:

```
[CAR] The report mentions "ORACLE_5 timing" as the key deliverable
but I don't understand what that means or how to verify it was done.

Please explain in plain English what ORACLE_5 timing is, why it
matters for this sprint, and how we'd know if it was done correctly.
```

You're allowed to ask for **explanation** as a CAR. You don't have to demand code changes.

### Step 3.5 — Submit

Click Send. Your flag is live.

### What NOT to do

- **Don't** click the Done checkbox. That dequeues the report without action.
- **Don't** use informal slang Co-Lead might misread: `[car]` (lowercase), `(CAR)`, `CAR:`. Only `[CAR]` with capitals and square brackets works.
- **Don't** delete or edit the original report — you're commenting on it, not modifying it.

---

## 4. Stage 2 — Co-Lead drafts a plan

You don't do anything in this stage. Here's what happens so you know what to expect.

Within about 15 minutes (Co-Lead's next scheduled wake cycle), it will:

1. Find your `[CAR]` comment on the Fleet Reports task.
2. Read your reason.
3. Read the original disk report the flag is on.
4. Read any related reports for context (e.g., the original EA prompt, any earlier reviews).
5. Write a **remediation plan** as a markdown file at:

   ```
   C:\Users\mrbla\BlarAI\docs\reports\corrective_actions\car_<timestamp>_<origin>_<N>.md
   ```

6. **Create a new Fleet Reports task** titled:

   ```
   [CAR Plan] Task N — <short title of originating report>
   ```

   With **priority 4 (urgent)** and the **Gate:Pending-Human** label.

7. Put a short summary in the task description + the disk path to the full plan.

That new task is your signal to move to Stage 3.

> **How long should Stage 2 take?** Typically 5–10 minutes. If it's been 30+ minutes and no CAR Plan task has appeared, check:
> - Is the fleet paused? (look at `tools/autonomy_budget/state.json` — `fleet_paused: false`)
> - Did Co-Lead fire? (check `tools/scheduled-tasks/logs/` for recent `co_lead_architect` files)
> - Ask Claude Desktop: *"Why hasn't my CAR plan appeared yet? I flagged task X in Fleet Reports at <time>."*

---

## 5. Stage 3 — You review the plan

### Step 5.1 — Open the CAR Plan task

In Vikunja → **Fleet Reports** → you'll see the new task at the top (sorted by newest first). It has priority 4 (urgent / usually red), which makes it obvious.

Click to open it.

### Step 5.2 — Read the description

The description is a 3–5 sentence summary of the plan. It tells you:

- What Co-Lead heard you say.
- What Co-Lead thinks the root cause is.
- What Co-Lead proposes to do about it.
- A link to the full plan on disk.

### Step 5.3 — Read the full plan (recommended)

Open the disk file at the path shown in the description, e.g.:

```
C:\Users\mrbla\BlarAI\docs\reports\corrective_actions\car_20260421_154900_task28_ea4_1.md
```

Open with VS Code or any markdown viewer. The plan has this structure:

1. **YAML frontmatter** — metadata (who authored, when, origin).
2. **What LA observed** — your exact CAR reason, quoted.
3. **Root-cause hypothesis** — Co-Lead's theory of what went wrong and why.
4. **Stepwise remediation** — numbered steps of what needs to change.
5. **Which agent executes** — typically EA (via a new EA prompt authored by SDO).
6. **Acceptance check** — how we'll know the fix is actually fixed.
7. **Risk summary** — what could still go wrong, what it touches.

### Step 5.4 — Decide

You have three options:

| Decision | How to act | What happens next |
|---|---|---|
| **Approve as-is** | Click the checkbox (marks Done) OR add comment `[CAR-APPROVED]` | Fleet executes the plan on next SDO wake (\~15 min) |
| **Reject / ask for revision** | Add a comment starting with `[CAR]` explaining what's wrong with THE PLAN | Co-Lead re-drafts the plan on next wake |
| **Defer** | Do nothing; leave task open | Plan stays in queue. Fleet does not execute until you approve |

### Step 5.5 — How to evaluate a plan

Ask yourself:

- **Does the root-cause hypothesis match the symptom I observed?** If Co-Lead misdiagnosed, the fix will be off-target.
- **Are the remediation steps specific?** Vague plans ("update the file") usually go sideways. Good plans say what file and what change.
- **Does the scope of the fix feel proportional?** A one-line issue shouldn't need a 100-file refactor. A systemic issue might need significant work.
- **Does the acceptance check actually test for the fix?** If the check is "tests still pass", that's weak — tests might have passed while the issue existed. A good check targets the specific concern.
- **Does anything in the risk summary scare you?** "Might require follow-on work" or "touches sensitive module X" = slow down and ask questions.

When in doubt, **ask Claude Desktop to critique the plan for you**:

> *"Open docs/reports/corrective_actions/car_20260421_154900_task28_ea4_1.md. I'm about to approve this. Poke holes in the plan — what could go wrong, what's vague, what's missing?"*

### Step 5.6 — Submit your decision

- **Approve**: click the checkbox at the top of the task. That closes (completes) the task. That's your signal to the fleet.
- **Reject/revise**: add the `[CAR] <feedback>` comment. Do NOT close the task.
- **Defer**: close the browser tab. Come back later.

---

## 6. Stage 4 — Fleet executes

Again, you don't do anything in this stage. But here's what to watch for.

After you approve the plan:

1. Within 15 minutes, SDO's next wake sees the approved CAR plan.
2. SDO authors a **corrective EA prompt** targeting the remediation. It goes to `docs/scheduled/ea_queue/staging/` and waits for Co-Lead review.
3. Co-Lead reviews the staged prompt (DEC-12 Phase 1b).
4. If approved, the prompt moves to `docs/scheduled/ea_queue/` and EA picks it up.
5. EA posts a comprehension report → SDO reviews → EA executes → commits → EA posts completion → SDO reviews.
6. All of these are **new Fleet Reports tasks** in your inbox.

You'll see a flurry of reports over about 30–60 minutes. You don't need to read them all immediately — they're audit trail. But watch for the final **Completion-Review** on the corrective commit — that's the one that tells you the fix is done and whether it was validated.

---

## 7. Stage 5 — You verify and close

### Step 7.1 — Find the final completion-review

In Fleet Reports, look for the most recent `[SDO Completion-Review]` task that references the corrective work. It'll usually appear within 30–60 minutes of your approval.

### Step 7.2 — Read it

The Completion-Review tells you:

- Was the remediation actually committed? (commit hash)
- Did it address the acceptance check the plan specified?
- Any new issues SDO spotted during the audit?

### Step 7.3 — Decide

- **Fix looks right → Pass**: close the task (mark done).
- **Fix didn't work → Flag again**: add another `[CAR]` flag. The cycle starts over. See [§9](#9-what-if-the-fix-doesnt-fix-it).

### Step 7.4 — Close the original report too

Go back to the **original** Fleet Reports task you flagged in Stage 1. If you're satisfied with the fix, close that task too. This cleanly dequeues the originating concern.

(Optional but good audit hygiene: add a comment on the original task linking to the CAR plan task and the final completion-review, so the trail is explicit.)

---

## 8. What if the plan is wrong?

You read Co-Lead's plan and something's off. Maybe:

- Co-Lead misunderstood your concern.
- The remediation is too narrow or too broad.
- The acceptance check doesn't actually verify the fix.
- Something in the plan looks unsafe.

### How to push back

**Leave the CAR Plan task OPEN** (do not close it).

Add a comment starting with `[CAR]`:

```
[CAR] The plan's root-cause hypothesis doesn't match what I observed.

You wrote: "EA misread WI-3 and thought it was optional."
I actually observed: WI-3 was in the diff, but WI-7 (Coverage Map)
is the one that's missing.

Please redraft the plan focused on the missing WI-7 work.
```

On Co-Lead's next wake, it sees your pushback, redrafts the plan, and updates the same Fleet Reports task (or creates a new revision). Continue iterating until the plan is sound.

### How long can this go on?

There's no hard limit, but in practice 2–3 rounds is usually enough. If Co-Lead can't produce a plan you're happy with after 3 rounds, that's a signal something deeper is wrong — maybe the original concern is ambiguous, or there's a broader issue. At that point, switch modes and **work with Claude Desktop directly** to diagnose what's going on.

---

## 9. What if the fix doesn't fix it?

You approved the plan, fleet executed, but the completion-review shows the issue is still there (or a new issue emerged).

### Option A: Start a new CAR

Treat the completion-review as a fresh report. Flag it with a new `[CAR]` describing:

- What was supposed to be fixed.
- What you still see wrong.
- What would be different if it were actually fixed.

This kicks off Stage 1 again with fresh context.

### Option B: Escalate to Claude Desktop

If the CAR cycle is looping without progress (2+ rounds without a fix), it's time to go manual:

> *"We've run two CAR cycles on this issue and it's still not fixed. Here are the Fleet Reports tasks: <ids>. Help me diagnose what's going on. I think we may need to pause the fleet and fix something deeper."*

Claude Desktop can read all the reports, look at the code history, and help you figure out if the problem is in the agent prompts, the wake templates, or the actual code. Sometimes the answer is "pause the fleet, make a manual fix, resume."

---

## 10. Full worked example

Here's a complete CAR cycle from start to finish.

### Scenario

EA-4 just completed. You read its Completion Report and notice:

> The report says "20 files changed, all within scope" but you skim the commit and see `tools/fleet_observability/dashboard_md.py` in the diff. The EA prompt's negative constraints said NO changes to `tools/fleet_observability/`.

### Stage 1 — You flag (2 minutes)

In Vikunja → Fleet Reports → open `[EA-4 Completion] Task 28 — 2026-04-21 15:45`.

Scroll to comments. Add:

```
[CAR] EA-4's commit touches tools/fleet_observability/dashboard_md.py
but the EA prompt's negative constraint #3 explicitly forbade changes
to that directory.

Either the file should be reverted, or the completion report should
explain why it's in-scope (and if so, the SDO review should have
caught that it needed explanation).

I'd want the file reverted as a separate commit, with the reasoning
posted as a comment on the tracking task.
```

Submit. Leave task open.

### Stage 2 — Co-Lead plans (\~7 minutes later, autonomous)

Co-Lead fires on its 15:50 wake. Finds your CAR. Reads the prompt + the commit + your reason. Writes a plan:

- **Root cause**: EA misread a shared helper import as in-scope; the file change was a 3-line fix that got auto-pulled into the diff via a find-replace.
- **Remediation**: EA authors a revert commit for just that file + posts explanation.
- **Acceptance check**: `git diff HEAD~1 HEAD` on the commit must NOT include `tools/fleet_observability/`.

Creates `[CAR Plan] Task 28 — EA-4 scope violation` in Fleet Reports, priority 4.

### Stage 3 — You review (10 minutes)

You open the CAR Plan task. Read the description. Open the disk file for the full plan.

Plan looks reasonable. Root cause matches what you observed. Remediation is proportional. Acceptance check specifically targets the file that concerned you.

You click the checkbox → task closed → approval signaled to fleet.

### Stage 4 — Fleet executes (\~40 minutes, autonomous)

- 16:00 SDO authors a small corrective EA prompt to staging/.
- 16:05 Co-Lead reviews the prompt — APPROVED.
- 16:10 SDO moves staging → queue.
- 16:15 EA reads, posts comprehension.
- 16:20 SDO reviews comprehension — APPROVED.
- 16:25 EA executes: reverts the file, commits, posts completion.
- 16:30 SDO reviews completion — APPROVED, commit hash matches acceptance check.

You see \~5 new Fleet Reports tasks appear during this window.

### Stage 5 — You verify (5 minutes)

Open the final `[SDO Completion-Review]` from 16:30. Read it:

> APPROVED. Commit `abc1234` reverts `tools/fleet_observability/dashboard_md.py` cleanly; diff contains only that file; passes all acceptance checks including the negative-constraint audit specified in the CAR plan.

Looks good. Close that task. Go back to the original EA-4 Completion task and close it too (leaving a comment: "Resolved via CAR plan, see task `<CAR plan task id>`").

CAR cycle complete. Your total active time: \~17 minutes. Fleet did the rest.

---

## Mental shortcut for day-to-day use

When you encounter any report that gives you pause:

1. **Look longer than 20 seconds trying to understand it?** → flag it.
2. **Something looks wrong but you can't articulate why?** → flag it anyway with "unsure but: \<what you see\>".
3. **Unsure if it's worth flagging?** → flag it. Co-Lead's ADJUST verdict (not full remediation, just guidance) is cheap.

Over-flagging is a much smaller problem than under-flagging. Co-Lead will push back if your flag is unfounded, and you'll learn where the fleet's boundaries are. Under-flagging lets issues accumulate.

---

## See also

- [LA_FLEET_REPORTS_HOWTO.md](LA_FLEET_REPORTS_HOWTO.md) — how to read reports in the first place.
- [AUTONOMOUS_FLEET_OPERATIONS.md](AUTONOMOUS_FLEET_OPERATIONS.md) — fleet operations runbook (pause/resume, etc.).
- [docs/DEC12_PEER_REVIEW_LATTICE_PROPOSAL_v1.xml](../DEC12_PEER_REVIEW_LATTICE_PROPOSAL_v1.xml) — the peer-review design that produces the reports.
- [docs/DEC13_REPORT_QUEUE_PROPOSAL_v1.xml](../DEC13_REPORT_QUEUE_PROPOSAL_v1.xml) — the CAR / Fleet Reports design.
