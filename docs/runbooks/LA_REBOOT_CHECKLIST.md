# What to Do When You Reboot — Lead Architect Checklist

> **Who this is for**: you, the Lead Architect (LA), after your laptop restarts.
>
> **Short version**: almost nothing. The fleet is designed to recover on its own. This doc exists so you can verify that it did.
>
> **Time required**: 2 minutes if everything auto-recovers. 5-10 minutes if something needs a manual fix.

---

## Table of contents

1. [The one-minute version](#1-the-one-minute-version)
2. [What happens automatically](#2-what-happens-automatically)
3. [Your 2-minute verification](#3-your-2-minute-verification)
4. [If Vikunja didn't auto-start](#4-if-vikunja-didnt-auto-start)
5. [If scheduled tasks aren't firing](#5-if-scheduled-tasks-arent-firing)
6. [If Claude Desktop / Claude Code was in the middle of something](#6-if-claude-desktop--claude-code-was-in-the-middle-of-something)
7. [Full diagnostic routine](#7-full-diagnostic-routine)

---

## 1. The one-minute version

On a normal reboot:

1. Log in to Windows.
2. Wait ~30 seconds for startup apps to finish loading.
3. Open a browser and go to `http://localhost:3456` — Vikunja should load.
4. You're done. Fleet is operational.

If step 3 fails, see [§4](#4-if-vikunja-didnt-auto-start). If everything else seems off, see [§7](#7-full-diagnostic-routine).

---

## 2. What happens automatically

Here's what Windows + your system configuration handle for you on every reboot, with no input from you:

| Thing | Mechanism | Verification |
|---|---|---|
| **Vikunja server starts** | Shortcut `Vikunja (BlarAI).lnk` in the Startup folder (`shell:startup`) | `http://localhost:3456` loads in browser |
| **Scheduled tasks resume firing** | Windows Task Scheduler — 10 tasks under `\BlarAI\` | Task Scheduler shows state = Ready |
| **Fleet state persists** | `tools/autonomy_budget/state.json` on disk (includes `fleet_paused` flag) | Paused or unpaused survives reboot |
| **OAuth session persists** | Claude Code credentials at `%USERPROFILE%\.claude\.credentials.json` | Agents authenticate without re-login |
| **Long path support** | Registry setting `HKLM\...\FileSystem\LongPathsEnabled = 1` | Takes effect on reboot; no action needed |
| **PATH variable** | Windows environment (user + system) | Terminals you open see correct PATH |

What does NOT persist across reboot (and that's fine):

- Any Claude Code CLI interactive sessions you had open (just reopen them).
- Any terminal windows you had open (same — just reopen).
- Running processes in your session other than those in the Startup folder.

---

## 3. Your 2-minute verification

### Step 3.1 — Log in

Normal Windows login. Enter your password or use Windows Hello.

### Step 3.2 — Wait a moment

Give Windows 30-60 seconds to finish starting background services and Startup-folder apps. Vikunja takes a few seconds to bind to `localhost:3456`.

### Step 3.3 — Verify Vikunja is running

Open any web browser. Go to:

```
http://localhost:3456
```

You should see the Vikunja login screen (or if you're already logged in, your task list).

If you see an error page like "This site can't be reached", Vikunja isn't running. Go to [§4](#4-if-vikunja-didnt-auto-start).

### Step 3.4 — (Optional) Verify the fleet is unpaused

Only bother with this if you want explicit confirmation. Open a terminal (PowerShell) and run:

```powershell
Get-Content 'C:\Users\mrbla\devplatform\tools\autonomy_budget\state.json' | Select-String 'fleet_paused'
```

You should see: `"fleet_paused": false,`. If it says `true`, the fleet is paused (someone — you or an earlier fleet event — paused it). That's fine; it just means no agent activity until you resume. See [AUTONOMOUS_FLEET_OPERATIONS.md §14](AUTONOMOUS_FLEET_OPERATIONS.md#14-resume-the-fleet) to resume.

### Step 3.5 — That's it

Go about your day. The fleet operates in the background. When you're ready to read reports, go to the Fleet Reports project in Vikunja. See [LA_FLEET_REPORTS_HOWTO.md](LA_FLEET_REPORTS_HOWTO.md).

---

## 4. If Vikunja didn't auto-start

Symptoms: `http://localhost:3456` shows "This site can't be reached" in your browser.

### Option A — Double-click the Desktop shortcut (easiest)

There's a shortcut on your Desktop titled **Vikunja (BlarAI)**. Double-click it. A small window may briefly flash, then disappear — that's Vikunja starting up in the background.

Wait 5 seconds, then refresh your browser. Vikunja should load.

### Option B — Launch from the command line

If the Desktop shortcut isn't there or doesn't work:

1. Open PowerShell (press `Win` key, type "PowerShell 7", press Enter).
2. Paste:

   ```
   & 'C:\Users\mrbla\devplatform\tools\vikunja\vikunja-v2.3.0-windows-4.0-amd64.exe'
   ```

3. Leave that PowerShell window open (closing it stops Vikunja).
4. In your browser, refresh `http://localhost:3456`.

### Option C — Check the Startup folder

If Vikunja isn't auto-starting across multiple reboots, the shortcut may have been deleted:

1. Press `Win + R`, type `shell:startup`, press Enter.
2. You should see a shortcut named `Vikunja (BlarAI)` in the folder.
3. If missing: recreate per [AUTONOMOUS_FLEET_OPERATIONS.md §2](AUTONOMOUS_FLEET_OPERATIONS.md#2-install-vikunja-autostart-shortcut-path).

### Option D — Ask Claude Desktop

> *"Vikunja isn't loading on localhost:3456 after reboot. Can you diagnose and fix?"*

---

## 5. If scheduled tasks aren't firing

Symptoms: you expect fleet activity but see no new Fleet Reports tasks, no new commits, no agent activity for more than 10 minutes.

### Quick check

Open PowerShell and run:

```powershell
Get-ScheduledTask -TaskPath '\BlarAI\' | Format-Table TaskName, State
```

You should see 10 tasks, all with State = `Ready`. If any say `Disabled`, that's why they're not firing. If all are `Ready` but nothing's happening, the fleet is probably paused (see §3.4).

### If tasks are Disabled

Re-enable them:

```powershell
Get-ScheduledTask -TaskPath '\BlarAI\' | Enable-ScheduledTask
```

### If tasks are Ready but fleet seems stuck

- Check fleet state: `Get-Content 'C:\Users\mrbla\devplatform\tools\autonomy_budget\state.json'`.
- Look for `fleet_paused: true` — if so, read the `fleet_paused_reason`.
- Ask Claude Desktop for help if the reason is unclear.

---

## 6. If Claude Desktop / Claude Code was in the middle of something

Claude Desktop and Claude Code CLI sessions don't persist across reboot. Any interactive work in progress is gone — but:

- **Committed git history**: preserved on disk. Check `git log` in the repo.
- **Fleet scheduled tasks**: resume on schedule. They pick up from where they left off.
- **Work by scheduled agents**: was already committed to git before reboot (agents commit per-phase). Safe.
- **Uncommitted changes in the working tree**: survive reboot in whatever state they were. Run `git status` to see.

If you want to resume an interactive Claude Code session:

1. Open a PowerShell window.
2. Navigate to the repo: `cd C:\Users\mrbla\BlarAI`.
3. Start: `& 'C:\Users\mrbla\AppData\Roaming\Claude\claude-code\2.1.111\claude.exe'`.
4. It'll remember your OAuth login from before reboot (tokens persist).

---

## 7. Full diagnostic routine

If multiple things feel off, run this in PowerShell and paste the output to Claude Desktop for diagnosis:

```powershell
Write-Host '=== Vikunja ==='
Get-Process vikunja* -ErrorAction SilentlyContinue | Format-Table Id, ProcessName
Write-Host '=== Scheduled Tasks ==='
Get-ScheduledTask -TaskPath '\BlarAI\' | Format-Table TaskName, State
Write-Host '=== Fleet State ==='
Get-Content 'C:\Users\mrbla\devplatform\tools\autonomy_budget\state.json' | Select-String 'fleet_paused|role_paused'
Write-Host '=== Last Agent Firing ==='
Get-ChildItem 'C:\Users\mrbla\devplatform\tools\scheduled-tasks\logs\' -Filter '*.log' -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending | Select-Object -First 3 Name, Length, LastWriteTime
Write-Host '=== Recent Git Activity ==='
& git -C 'C:\Users\mrbla\BlarAI' log --oneline -5
Write-Host '=== Failures Directory ==='
Get-ChildItem 'C:\Users\mrbla\devplatform\tools\scheduled-tasks\logs\failures\' -ErrorAction SilentlyContinue | Format-Table Name, LastWriteTime
```

This captures the full fleet state in one output. Paste it to Claude Desktop with a message like:

> *"Diagnose my fleet state after reboot, here's the diagnostic output:"*

---

## See also

- [AUTONOMOUS_FLEET_OPERATIONS.md](AUTONOMOUS_FLEET_OPERATIONS.md) — main fleet operations runbook (pause/resume, task registration, etc.).
- [LA_FLEET_REPORTS_HOWTO.md](LA_FLEET_REPORTS_HOWTO.md) — how to read reports once fleet is running.
- [LA_CAR_WORKFLOW_HOWTO.md](LA_CAR_WORKFLOW_HOWTO.md) — the corrective-action workflow when you find an issue.
