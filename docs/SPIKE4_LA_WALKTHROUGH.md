# Spike-4 — Lead Architect Walkthrough

**Purpose**: You run this once to confirm Claude Cowork's built-in `/schedule` feature actually fires on schedule during an idle stretch, the same way Domain 8's autonomous-fleet design assumes it will.

**Total time you'll spend**: \~30 minutes of wall-clock, most of it passive waiting.

**Total active-attention you'll need**: \~5 minutes of clicking / pasting / noting.

**One action per step below**. Don't skip ahead.

**Where to write observations**: Vikunja Project 4 task **#36 "Spike-4 observations (Cowork /schedule LA-burst test)"**. Each "note" in the steps below = one comment on that task.

**Related docs**: [`docs/domain8_spike_findings.md` §5](domain8_spike_findings.md) (technical-reader view). [`docs/DOMAIN8_SPIKE_MEMO_APPROVAL_v1.xml`](DOMAIN8_SPIKE_MEMO_APPROVAL_v1.xml) (approval that requested this walkthrough).

---

## Prep (about 2 minutes)

### P-1. Make sure Claude Desktop is open.
Your normal setup; nothing special.

### P-2. Make sure Vikunja is running.
Open a fresh PowerShell window (any flavor — `powershell.exe` or `pwsh.exe`) and paste:
```
Get-Process vikunja* | Select-Object Id, ProcessName
```
**If you see a row** with an Id and ProcessName = `vikunja-v2.3.0-windows-4.0-amd64`: you're good.
**If nothing shows up**: start Vikunja manually by double-clicking `C:\Users\mrbla\BlarAI\tools\vikunja\vikunja-v2.3.0-windows-4.0-amd64.exe`, wait 5 seconds, retry the command.

### P-3. Delete any existing Spike-4 log file so we start clean.
Paste into PowerShell:
```
Remove-Item 'C:\Users\mrbla\BlarAI\tools\vikunja_mcp\bridge\spike4_cowork.log' -ErrorAction SilentlyContinue
```
Silent success means clean. Any other output: paste it into the observations task as a comment and stop.

---

## Execute (about 5 minutes)

> **Note on Cowork `/schedule` flow** (corrected 2026-04-21 after LA's first walkthrough attempt): Cowork's `/schedule` command asks *what* to schedule, then *how often*. You do NOT paste a prompt first and then `/schedule` it. Instead, you type `/schedule` directly and Cowork walks you through describing the task + the recurrence.

### 1. In Claude Desktop, click the **Cowork** tab (left sidebar).

### 2. Click **New task** (or the equivalent + / New button for a Cowork task).

### 3. Mount the BlarAI workspace when Cowork asks which folder to use.
Select `C:\Users\mrbla\BlarAI`. Accept whatever defaults Cowork offers.

### 4. Type `/schedule` in the Cowork chat input and send.
Just the single word — forward slash + schedule. Cowork shows a picker titled **"What task would you like to schedule?"** with options 1-4 plus "Something else" at the bottom.

### 5. Select **"Something else"** (option 4).
Arrow-down to it or press **`4`**. A free-form input appears where you type the task description.

### 6. Paste this **exact** prompt as the task description:
```
Write the current UTC timestamp (ISO-8601 format ending in Z) plus a random 4-digit marker to tools/vikunja_mcp/bridge/spike4_cowork.log. APPEND — do not overwrite. Format: one line per run, TAB-separated: timestamp<TAB>marker<TAB>spike4-fired. Create parent dirs if missing. Then exit.
```
Press Enter. Cowork advances to the recurrence picker (page 2 of 2).

### 7. On the recurrence picker, choose **every 15 minutes**.
If Cowork offers "custom", pick `15m`. Note: Cowork may not offer a "4 runs" cap — its recurrence model tends to be "every N minutes indefinitely". That's fine; we'll delete the task after the observation window (see step 16).

### 8. Confirm the schedule.
Cowork should reply with a one-line confirmation and show the scheduled task name (likely `spike4-cowork-heartbeat` or similar). **Note that confirmation text verbatim** as a comment on Vikunja task #36.

### 9. Pre-approve permissions via "Run now" (important).
Cowork's own suggestion after scheduling: click **Scheduled** in the left sidebar → find `spike4-cowork-heartbeat` → click **Run now**. When the run starts, Claude will prompt for permission on `Bash` / `mkdir` / `printf` — grant `Always allow` for each.

**Why this matters**: without pre-approval, every scheduled firing will pause on those permission prompts. Since you're walking away, prompts go unanswered and runs produce no log lines. Pre-approval makes scheduled firings clean and unattended.

After the Run now completes, confirm the first log line landed:
```
Get-Content 'C:\Users\mrbla\BlarAI\tools\vikunja_mcp\bridge\spike4_cowork.log'
```
Expect one line. If you see it: scheduled firings from here on should append silently. If you don't see it: something went wrong in the Run now; note the error on task 36 and stop.

### 10. Close the Cowork session (but leave Claude Desktop open).
Simulates you walking away. The machine must stay awake — if your laptop is on battery, plug it in.

---

## Wait (about 20–30 minutes)

### 11. Don't touch Claude Desktop until at least 3 firings have elapsed.
That's \~45 minutes of wall-clock. Do other things.

---

## Verify (about 3 minutes)

### 12. Paste this PowerShell one-liner to view the log:
```
Get-Content 'C:\Users\mrbla\BlarAI\tools\vikunja_mcp\bridge\spike4_cowork.log'
```

### 13. Paste this one-liner to count the firings:
```
(Get-Content 'C:\Users\mrbla\BlarAI\tools\vikunja_mcp\bridge\spike4_cowork.log').Count
```

### 14. Note the count and the first + last timestamps as a comment on Vikunja task #36.

---

## Observations to record (Vikunja task #36, one comment per item)

| # | Observation | What we're confirming |
|---|---|---|
| i | Did the schedule fire at least once during your idle stretch? | That `/schedule` works at all when you're not actively using Cowork. |
| ii | Did firings produce distinct timestamp entries (not duplicates)? | That each scheduled run is a fresh invocation. |
| iii | How many total firings did you observe in the \~30 min window? | Sanity-check against the 4-run limit. Expected: 1–3 depending on timing. |
| iv | Anything unexpected in Claude Desktop's UI during the wait? | E.g. popups, session prompts, errors. |
| v | Does the log show 4 lines, fewer, or none? | Gives us fleet-reliability signal. |

---

## Expected-outputs table

| If you see… | It means… | Action |
|---|---|---|
| Log file has 3–4 lines, each with a unique timestamp + marker | **PASS** — Cowork `/schedule` works as assumed. | Comment "PASS" on task #36. Theme D deliverable 9 live registration is unblocked. |
| Log file has 1–2 lines | **PARTIAL** — schedule fired but fewer times than expected. | Comment with the line count + timestamps. Likely fine (machine may have slept or Desktop closed briefly); agent will advise. |
| Log file is empty or missing | **FAIL** — schedule didn't fire. | Comment "FAIL — file empty" + any UI observations. Theme D deliverable 9 will need re-scoping; agent will propose alternative. |
| Any lines with identical timestamps | **UNCLEAR** — schedule fired but produced duplicates. | Comment the duplicates; agent investigates. |
| Claude Desktop prompted you for anything during the wait | **INCOMPLETE** — Cowork may need interactive attention. | Comment the prompt text verbatim; agent flags for Theme D rework. |

---

## When done

### 15. Close Vikunja task #36 (mark complete).
Add a final one-line comment summarizing: "PASS / PARTIAL / FAIL — [one sentence]".

### 16. Delete the Cowork scheduled task (it runs indefinitely otherwise).
Go to Cowork **Scheduled** sidebar → find `spike4-cowork-heartbeat` → delete or disable. Without this step the scheduler will keep appending a line every 15 minutes forever, cluttering the log file.

### 17. Ping the agent in chat with task #36 closed.
"Spike-4 done — check task 36 for observations" or similar. Agent picks up and proceeds to Theme D deliverable 9 live registration or pivots as needed.

---

## If something goes wrong mid-run

- **Vikunja crashes during the wait**: that's a separate Vikunja-down concern, not a Spike-4 failure. Restart Vikunja, note it in task #36, continue observation collection on whatever log lines accumulated before the crash.
- **Cowork refuses to accept `/schedule`**: note the error; the whole feasibility assumption is at risk. Comment "Cowork refused /schedule" on task #36; agent pivots Theme D del. 9 to a Windows-Task-Scheduler-invoked Cowork launcher path.
- **You forgot to leave Desktop open**: re-run from step 3 after P-3 cleanup.

---

## Cross-reference

- [Spike memo §5](domain8_spike_findings.md) — technical-reader procedure (the source this walkthrough translates).
- [Spike memo §5 Contingency](domain8_spike_findings.md) — what happens if Spike-4 fails.
- [DEC-11 proposal §5.2 F1 resolution](DOMAIN8_DEC11_BUDGET_PROPOSAL_v2.xml) — the 24/7-Desktop-open commitment that Spike-4 operationally validates.
