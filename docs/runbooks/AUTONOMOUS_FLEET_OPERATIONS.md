# Autonomous Fleet Operations — Operator Runbook

**Audience**: Lead Architect (non-dev operator).
**Partner doc**: [`docs/CLAUDE_AUTONOMOUS_FLEET_OPS_D8.md`](../CLAUDE_AUTONOMOUS_FLEET_OPS_D8.md) (architecture + design).
**Authoritative budget/permissions**: [`docs/DOMAIN8_DEC11_BUDGET_PROPOSAL_v3.xml`](../DOMAIN8_DEC11_BUDGET_PROPOSAL_v3.xml) (body-reconverged) and its archival predecessor [`docs/DOMAIN8_DEC11_BUDGET_PROPOSAL_v2.xml`](../DOMAIN8_DEC11_BUDGET_PROPOSAL_v2.xml).

This runbook is task-based: pick the section you need, follow the numbered steps, done. Each step is one action (one click, one paste, or one observation). PowerShell one-liners are copy-paste ready; no placeholders.

---

## Table of contents

1. [First-time fleet install (one-time bring-up)](#1-first-time-fleet-install-one-time-bring-up)
2. [Install Vikunja autostart (shortcut path)](#2-install-vikunja-autostart-shortcut-path)
3. [Provision F2 credential](#3-provision-f2-credential)
4. [Register Event Log source (one-time elevated)](#4-register-event-log-source-one-time-elevated)
5. [Register per-role wake-up scheduled tasks](#5-register-per-role-wake-up-scheduled-tasks)
6. [Register observability scheduled tasks](#6-register-observability-scheduled-tasks)
7. [Respond to a `Gate:Pending-Human`](#7-respond-to-a-gatepending-human)
8. [Respond to a HARD breach](#8-respond-to-a-hard-breach)
9. [Respond to a CRITICAL breach](#9-respond-to-a-critical-breach)
10. [Review & approve a merge-to-main gate](#10-review--approve-a-merge-to-main-gate)
11. [Rotate the Anthropic API key](#11-rotate-the-anthropic-api-key)
12. [Rollback (revert a bad merge)](#12-rollback-revert-a-bad-merge)
13. [Pause the fleet (vacation / emergency)](#13-pause-the-fleet-vacation--emergency)
14. [Resume the fleet](#14-resume-the-fleet)
15. [Recover from fleet-state divergence (MF-2 HARD)](#15-recover-from-fleet-state-divergence-mf-2-hard)
16. [Diagnose CRITICAL toast not firing (SO-1)](#16-diagnose-critical-toast-not-firing-so-1)
17. [Audit settings.json rules (Spike-7 precedent)](#17-audit-settingsjson-rules-spike-7-precedent)
18. [Adjust autonomy budgets mid-flight](#18-adjust-autonomy-budgets-mid-flight)
19. [Manage the active-task roster (D9)](#19-manage-the-active-task-roster-d9)
20. [Switch merge policy mode (D9)](#20-switch-merge-policy-mode-d9)
21. [Bootstrap a new task (D9)](#21-bootstrap-a-new-task-d9)
22. [Decommission the fleet](#22-decommission-the-fleet)
23. [`agents.ps1` task manager — the one-command way to pause, resume, or reinterval](#23-agents-task-manager-the-one-command-way-to-pause-resume-or-reinterval)

---

## 1. First-time fleet install (one-time bring-up)

Do these in order. Each section below has its own detail.

1. [Install Vikunja autostart (shortcut path)](#2-install-vikunja-autostart-shortcut-path).
2. [Provision F2 credential](#3-provision-f2-credential).
3. [Register Event Log source (one-time elevated)](#4-register-event-log-source-one-time-elevated).
4. [Register per-role wake-up scheduled tasks](#5-register-per-role-wake-up-scheduled-tasks).
5. [Register observability scheduled tasks](#6-register-observability-scheduled-tasks).

After step 5, the fleet is live. Expected first-day behavior:
- Scheduled wake-ups fire on their cadences.
- Daily digest arrives at 05:00 UTC as a new task in Vikunja Project 4.
- If any budget breaches happen, you'll see toasts for CRITICAL and `Gate:Pending-Human` entries for HARD.

---

## 2. Install Vikunja autostart (shortcut path)

**LA override**: use the Startup-folder shortcut, **not** the Task Scheduler XML. The XML variant at [`tools/scheduled-tasks/vikunja-autostart.xml`](../../tools/scheduled-tasks/vikunja-autostart.xml) exists as reference only. Do **NOT** register it without explicit LA re-approval.

1. Open File Explorer. Paste into the address bar: `shell:startup`. Press Enter.
2. Right-click in the Startup folder → **New** → **Shortcut**.
3. Target path: `C:\Users\mrbla\devplatform\tools\vikunja\vikunja-v2.3.0-windows-4.0-amd64.exe`.
4. Name the shortcut: `Vikunja (BlarAI)`.
5. Right-click the new shortcut → **Properties**:
   - **Target** (append after the exe path, separated by one space): `web` — Vikunja v2.x is a CLI tool; the `web` subcommand starts the HTTP server. Without it, the shortcut just prints a help message and exits. The full Target field should read: `"C:\Users\mrbla\devplatform\tools\vikunja\vikunja-v2.3.0-windows-4.0-amd64.exe" web`.
   - **Start in**: `C:\Users\mrbla\devplatform\tools\vikunja`.
   - **Run**: `Minimized` (or set via PowerShell to WindowStyle 7 for fully hidden).
6. Close the Properties dialog.

**Recommended (scripted, truly silent)** — the manual-steps approach above produces a shortcut that still flashes a console window on launch (Windows-shortcut `WindowStyle: minimized` doesn't hide console-subsystem child processes). The VBS-wrapper pattern below matches the scheduled-tasks silent pattern and launches Vikunja with no visible window:
```
$w = New-Object -ComObject WScript.Shell
$s = $w.CreateShortcut((Join-Path ([Environment]::GetFolderPath('Startup')) 'Vikunja (BlarAI).lnk'))
$s.TargetPath = 'C:\Windows\System32\wscript.exe'
$s.Arguments = '"C:\Users\mrbla\devplatform\tools\vikunja\start_vikunja_hidden.vbs"'
$s.WorkingDirectory = 'C:\Users\mrbla\devplatform\tools\vikunja'
$s.WindowStyle = 7
$s.Save()
```
This targets `wscript.exe` (a non-console host) which invokes `tools/vikunja/start_vikunja_hidden.vbs`. The VBS uses `shell.Run "...vikunja.exe web", 0, False` where the `0` argument (SW_HIDE) actually hides the console. Create the same pointing at the Desktop folder if you also want a visible double-click-to-start icon.

**Verify** (next logon):
```
Get-Process vikunja* | Select-Object Id, ProcessName
```
Expect one row with ProcessName = `vikunja-v2.3.0-windows-4.0-amd64`. If zero rows, either (a) Windows is still finishing startup (wait 60s) or (b) the shortcut is missing the `web` argument — open its Properties and confirm Target ends in `web`.

**Uninstall**: delete the `Vikunja (BlarAI)` shortcut from `shell:startup`.

---

## 3. Provision F2 credential

This writes your Anthropic API key to a protected file so scheduled `claude -p` sessions can authenticate.

1. Open a non-elevated PowerShell window.
2. Paste and run:
```
& 'C:\Users\mrbla\devplatform\tools\scheduled-tasks\provision_credentials.ps1'
```
3. When prompted, paste your Anthropic API key (input is hidden).
4. The script writes `C:\Users\mrbla\.blarai-fleet\credentials.env`, restricts ACLs to `mrbla`-only, and runs a `claude --bare -p "echo ok"` smoke test.
5. Confirm the final line says **`PROVISIONING COMPLETE`**.

**Verify** (any time):
```
icacls 'C:\Users\mrbla\.blarai-fleet\credentials.env'
```
Expect one row with `NORTHSTAR100\mrbla:(F)` and no other principals.

---

## 4. Register Event Log source (one-time elevated)

Needed once per machine so Fleet scripts can write to the Windows Application log under source `"BlarAI Fleet"`. Idempotent — rerunning is safe.

1. Open an **elevated** PowerShell window (right-click Start → "Windows PowerShell (Admin)").
2. Paste and run:
```
& 'C:\Users\mrbla\devplatform\tools\scheduled-tasks\register_event_log_source.ps1'
```
3. Expect either `Event Log source 'BlarAI Fleet' registered in log 'Application'` or `...already exists. No action`.
4. Close the elevated window. No further elevation required by fleet scripts.

---

## 5. Register per-role wake-up scheduled tasks

Register each XML via `Register-ScheduledTask`. Do **one at a time** and confirm each before proceeding.

In a non-elevated PowerShell:

```
Register-ScheduledTask -Xml ((Get-Content -Raw 'C:\Users\mrbla\devplatform\tools\scheduled-tasks\wake-co_lead_architect.xml') -replace 'encoding="UTF-8"', 'encoding="UTF-16"') -TaskName 'BlarAI\Wake Co-Lead Architect' -User 'mrbla'
```

```
Register-ScheduledTask -Xml ((Get-Content -Raw 'C:\Users\mrbla\devplatform\tools\scheduled-tasks\wake-sdo.xml') -replace 'encoding="UTF-8"', 'encoding="UTF-16"') -TaskName 'BlarAI\Wake SDO' -User 'mrbla'
```

```
Register-ScheduledTask -Xml ((Get-Content -Raw 'C:\Users\mrbla\devplatform\tools\scheduled-tasks\wake-ea_code.xml') -replace 'encoding="UTF-8"', 'encoding="UTF-16"') -TaskName 'BlarAI\Wake EA Code' -User 'mrbla'
```

**Verify**:
```
Get-ScheduledTask -TaskPath '\BlarAI\' | Format-Table TaskName, State
```
Expect three rows with State = `Ready`.

**Unregister** (per task):
```
Unregister-ScheduledTask -TaskName 'Wake Co-Lead Architect' -TaskPath '\BlarAI\' -Confirm:$false
```

---

## 6. Register observability scheduled tasks

```
Register-ScheduledTask -Xml ((Get-Content -Raw 'C:\Users\mrbla\devplatform\tools\scheduled-tasks\gate-stale-cleaner.xml') -replace 'encoding="UTF-8"', 'encoding="UTF-16"') -TaskName 'BlarAI\Gate Stale Cleaner' -User 'mrbla'
```

```
Register-ScheduledTask -Xml ((Get-Content -Raw 'C:\Users\mrbla\devplatform\tools\scheduled-tasks\toast-watchdog.xml') -replace 'encoding="UTF-8"', 'encoding="UTF-16"') -TaskName 'BlarAI\Toast Watchdog' -User 'mrbla'
```

```
Register-ScheduledTask -Xml ((Get-Content -Raw 'C:\Users\mrbla\devplatform\tools\scheduled-tasks\daily-digest.xml') -replace 'encoding="UTF-8"', 'encoding="UTF-16"') -TaskName 'BlarAI\Daily Digest' -User 'mrbla'
```

```
Register-ScheduledTask -Xml ((Get-Content -Raw 'C:\Users\mrbla\devplatform\tools\scheduled-tasks\weekly-summary.xml') -replace 'encoding="UTF-8"', 'encoding="UTF-16"') -TaskName 'BlarAI\Weekly Summary' -User 'mrbla'
```

```
Register-ScheduledTask -Xml ((Get-Content -Raw 'C:\Users\mrbla\devplatform\tools\scheduled-tasks\welcome-back-poll.xml') -replace 'encoding="UTF-8"', 'encoding="UTF-16"') -TaskName 'BlarAI\Welcome Back Poll' -User 'mrbla'
```

```
Register-ScheduledTask -Xml ((Get-Content -Raw 'C:\Users\mrbla\devplatform\tools\scheduled-tasks\dashboard-maintainer.xml') -replace 'encoding="UTF-8"', 'encoding="UTF-16"') -TaskName 'BlarAI\Dashboard Maintainer' -User 'mrbla'
```

```
Register-ScheduledTask -Xml ((Get-Content -Raw 'C:\Users\mrbla\devplatform\tools\scheduled-tasks\credentials-rotation-reminder.xml') -replace 'encoding="UTF-8"', 'encoding="UTF-16"') -TaskName 'BlarAI\Credentials Rotation Reminder' -User 'mrbla'
```

```
Register-ScheduledTask -Xml ((Get-Content -Raw 'C:\Users\mrbla\devplatform\tools\scheduled-tasks\escalation-watchdog.xml') -replace 'encoding="UTF-8"', 'encoding="UTF-16"') -TaskName 'BlarAI\Escalation Watchdog' -User 'mrbla'
```

The Escalation Watchdog (added 2026-04-23) polls Vikunja every 5 min for new `Gate:Pending-Human` tasks and fires a native Windows toast for each one. Sibling to Toast Watchdog (which is CRITICAL-only). On first run it silent-populates `tools/fleet_observability/escalation_seen.json` so stale labels don't toast-spam. To force re-notification of all currently-pending items: delete `escalation_seen.json` and wait ≤ 5 min. To suppress all escalation toasts: `Disable-ScheduledTask -TaskName 'Escalation Watchdog' -TaskPath '\BlarAI\'`.

**Verify**:
```
Get-ScheduledTask -TaskPath '\BlarAI\' | Format-Table TaskName, State, LastRunTime
```

**Test-fire a specific task** (optional sanity check):
```
Start-ScheduledTask -TaskName 'Toast Watchdog' -TaskPath '\BlarAI\'
```

---

## 7. Respond to a `Gate:Pending-Human`

You start each active burst at the **Fleet Dashboard** (Vikunja Project 7). Summary tasks at priority 5 are pinned at the top.

1. Open Vikunja web UI: `http://localhost:3456`.
2. Navigate to **BlarAI Fleet Dashboard** project (id 7).
3. Sort by priority descending; summary tasks pin to top.
4. Open the `Active Gates Queue` summary. Note the Pending-Human count.
5. For each Pending-Human item (sorted by priority then age):
   - Click the task. Read the description.
   - Scroll to `## One-click actions`. Each option has a copy-paste PowerShell block.
   - **Pick exactly one** option. Paste the corresponding block into PowerShell. Wait for it to finish.
   - The option's script updates Vikunja labels + comments automatically; no manual relabeling required.
6. Return to the dashboard. Refresh. The Pending-Human count should have decremented.

Target cadence: \~30 seconds per one-click decision. If something needs strategic deliberation, use the `defer` action to punt to your next active burst.

---

## 8. Respond to a HARD breach

HARD breaches pause the originating role but leave the rest of the fleet running. You see a `Gate:Pending-Human` in the bus; no toast (HARD does not fire the toast watchdog).

1. Follow [§7](#7-respond-to-a-gatepending-human) flow for the breach task.
2. The one-click actions will usually be:
   - **Continue** — clear the breach, role unpauses, nothing changes.
   - **Adjust threshold** — opens a Budget Lift Request; approves an extension up to 7 days LA-active-time.
   - **Halt role** — keep the role paused until further notice.
3. After paste: the originating role's scheduled wake-up resumes on its next firing (auto-unpause on Gate:Approved).

---

## 9. Respond to a CRITICAL breach

You'll see:
- A **Windows toast** in the Action Center (AppId `windows.immersivecontrolpanel` today; custom BlarAI-Fleet AUMID deferred to PD4).
- A **Gate:Pending-Human** at priority 5 in Project 6.
- `tools/fleet_observability/critical_pending.flag` consumed → renamed to `critical_consumed.<timestamp>.flag`.
- `tools/autonomy_budget/state.json` `fleet_paused=true` with reason.

The fleet is already halted. Take the time you need to root-cause, then:

1. Open the Pending-Human task. Read the full description.
2. If the trigger is `vikunja_unreachable` and Vikunja is now back up:
```
Remove-Item 'C:\Users\mrbla\devplatform\tools\fleet_observability\vikunja_down.flag' -ErrorAction SilentlyContinue
```
3. If the trigger is `security_finding`: do **not** resume the fleet until the root cause is understood. Consult docs/POST_OPERATIONAL_MATURATION_LEDGER.md for precedent.
4. When you're ready to resume, follow [§14](#14-resume-the-fleet) — the task's one-click action "Resume fleet (after root cause ack)" runs the same script.

---

## 10. Review & approve a merge-to-main gate

Co-Lead produces these after the EA→SDO→Co-Lead ladder reaches consensus.

1. Dashboard → `Merge-to-Main Queue` summary → drill in.
2. Each merge-to-main gate includes:
   - Feature branch name.
   - Commit hash list.
   - Pre-formatted `git merge --no-ff` command.
   - Pre-formatted `git revert -m 1 <merge-hash>` rollback command (per M4).
   - Diff summary.
   - One-click: **APPROVE** / **REJECT** / **DEFER** / **HALT**.
3. Paste your chosen action. APPROVE runs the merge immediately and closes the gate.

Target budget: ≤ 5 merge reviews per week, \~15 min each per DEC-11 §1.1 Lead Architect row.

---

## 11. Rotate the Anthropic API key

Quarterly (auto-reminder arrives as a Vikunja task in Project 4).

1. Anthropic console → revoke current key.
2. Anthropic console → generate new key. Copy to clipboard.
3. Open the credentials file:
```
notepad 'C:\Users\mrbla\.blarai-fleet\credentials.env'
```
4. Replace the old value after `ANTHROPIC_API_KEY=` with the new key.
5. Save and close notepad.
6. Verify ACLs unchanged:
```
icacls 'C:\Users\mrbla\.blarai-fleet\credentials.env'
```
Expect still-and-only `NORTHSTAR100\mrbla:(F)`.
7. Smoke test:
```
$env:ANTHROPIC_API_KEY = ((Get-Content 'C:\Users\mrbla\.blarai-fleet\credentials.env') -split '=', 2)[1]; & 'C:\Users\mrbla\AppData\Roaming\Claude\claude-code\2.1.111\claude.exe' --bare -p 'echo rotate'; $env:ANTHROPIC_API_KEY = ''
```
Expect exit 0 and the word `rotate` in output.
8. Close the reminder Vikunja task with a comment noting the rotation timestamp.

---

## 12. Rollback (revert a bad merge)

Every merge-to-main commit message embeds the rollback procedure (M4). Copy-paste from the commit message, or in general:

1. Find the merge hash:
```
git -C 'C:\Users\mrbla\BlarAI' log --merges --oneline -5
```
2. Revert:
```
git -C 'C:\Users\mrbla\BlarAI' revert -m 1 <merge-hash>
```
3. Post-revert sanity:
```
git -C 'C:\Users\mrbla\BlarAI' log --oneline -5
```
4. Create a new Vikunja task in Project 4 titled `Rollback: <feature-branch-name>` with rationale. SDO will see it on next wake-up and plan re-execution.

---

## 13. Pause the fleet (vacation / emergency)

> **Simpler path**: for most pause/resume situations, use the [`agents.ps1` task manager (§23)](#23-agents-task-manager-the-one-command-way-to-pause-resume-or-reinterval). It disables the scheduled tasks entirely so they don't even fire — cheaper on API billing than the state-flag path here, which still wakes the session just to read the flag and exit.
>
> Use this §13 path when you want the state-flag semantics (e.g. the wake still runs for a firing-exit report, or you want a reason string recorded in `state.json`).

> **REQUIRED for any substantive LA-driven git work on the main worktree**: pause the fleet FIRST, do the work, unpause. This covers branch checkouts (mandatory — agent commits land on YOUR feature branch instead of `main`), multi-commit sequences, merges/rebases, stash operations, or any edit-then-commit cycle that takes more than a minute. SDO / Co-Lead / Sprint Auditor wakes share the main worktree and operate on whatever tree-state they find at PREFLIGHT; racing them produces branch contamination and/or mid-edit interleave. Pattern B isolates ONLY EA Code. The canonical commit triplet is `chore: pause` → work commits → `chore: unpause`. See [`docs/governance/fleet-hygiene.md`](../governance/fleet-hygiene.md) §4 (Pause / resume invariants — "LA git-work discipline") for the full SOP table and rationale.

1. Open PowerShell.
2. Paste:
```
python -c "from tools.autonomy_budget import state; state.pause_fleet('operator manual pause', updated_by='la', path='C:/Users/mrbla/devplatform/tools/autonomy_budget/state.json')"
```
3. All scheduled wake-ups will see `fleet_paused=true` on their next firing and exit without running Claude.
4. Confirm:
```
Get-Content 'C:\Users\mrbla\devplatform\tools\autonomy_budget\state.json' | Select-String 'fleet_paused'
```

---

## 14. Resume the fleet

Choose one of:

- **Resume fleet only** (role pauses persist):
```
python -c "from tools.autonomy_budget import state; state.resume_fleet(updated_by='la', path='C:/Users/mrbla/devplatform/tools/autonomy_budget/state.json')"
```
- **Resume everything** (clear fleet_paused + all role_paused flags; C-5 semantics):
```
python -c "from tools.autonomy_budget import state; state.resume_all(updated_by='la', path='C:/Users/mrbla/devplatform/tools/autonomy_budget/state.json')"
```

Next scheduled firing of each task picks up the new state automatically (per M9 no-caching rule).

---

## 15. Recover from fleet-state divergence (MF-2 HARD)

You'll see a Project 4 task titled `[FleetState] Vikunja/file divergence <timestamp>` and a priority-4 `Gate:Pending-Human` (not CRITICAL — divergence is always safe because the file is authoritative).

1. Open the divergence task. Read the mismatch details.
2. Decide if the Vikunja mirror was manually edited (normal operator tweak) or if this is a write-path bug:
   - **Manual edit**: acknowledge and close. Reconciliation already happened automatically (file was trusted; Vikunja was updated to match).
   - **Write-path bug**: open a new F-item to investigate. Fleet continues running on the authoritative file in the meantime.

---

## 16. Diagnose CRITICAL toast not firing (SO-1)

The LA reported they did not recall seeing the Spike-3 dry-run toast. Theme B's watchdog installation includes verification:

1. Create a test flag manually:
```
@'
trigger=test
severity=CRITICAL
role=test
task_id=
fired_at=2026-04-21T00:00:00Z
message=Test firing of toast watchdog
'@ | Set-Content 'C:\Users\mrbla\devplatform\tools\fleet_observability\critical_pending.flag' -Encoding ascii
```
2. Wait up to 1 minute (watchdog cadence).
3. Watch the Windows Action Center for a toast titled `BlarAI Fleet -- test`.

If the toast does **not** appear:

- **Check Settings → System → Notifications**. "Windows PowerShell" (or the AUMID you see in the toast) must have notifications enabled.
- **Check Focus Assist / Do Not Disturb**. Quiet hours can suppress audio but the toast should still land in Action Center.
- **Inspect the consumed flag**:
```
Get-ChildItem 'C:\Users\mrbla\devplatform\tools\fleet_observability\critical_consumed.*.flag' | Sort-Object LastWriteTime | Select-Object -Last 3
```
  If consumed-flags exist: the watchdog ran; the issue is downstream at the OS notification layer.
- **Fallback**: enable an audible cue by adding a short `[Console]::Beep()` or `.wav` play into `critical_notify.ps1`. File an F-item (e.g., F-13) for root-cause investigation and/or PD4 custom AUMID registration.

Do NOT rabbit-hole on toast UX. If visibility is unreliable, the bus Pending-Human entry is the authoritative signal; toast is convenience.

---

## 17. Audit settings.json rules (Spike-7 precedent)

Inspect permission rules accumulated across scopes. Narrow rules (full command matches) are fine; broad `PowerShell(*)` / `Bash(*)` patterns are not.

```
Get-ChildItem -Recurse -File -Filter 'settings*.json' 'C:\Users\mrbla\.claude', 'C:\Users\mrbla\BlarAI\.claude' -ErrorAction SilentlyContinue | ForEach-Object { Write-Host ('=== ' + $_.FullName + ' ==='); Get-Content $_.FullName }
```

If any rule is broader than a specific full-command match, consider editing the file to narrow it. **Remember M15** — autonomous launchers pass `--allowedTools` per invocation and do NOT inherit from settings.json, so a too-broad rule is an interactive-session concern, not a fleet-autonomy concern.

---

## 18. Adjust autonomy budgets mid-flight

Budgets are hot-reloaded at every scheduled task firing (M9). No scheduled-task restart required.

1. Open `C:\Users\mrbla\devplatform\tools\autonomy_budget\config.yaml` in notepad.
2. Edit the value. Common knobs:
   - `roles.<role>.session_runtime_min` (per-session cap in minutes)
   - `roles.<role>.daily_runs` (per-day run count)
   - `roles.<role>.weekly_cum_hours` (weekly cumulative)
   - `fleet.aggregate_weekly_cap_hours` (fleet-wide)
   - `roles.lead_architect.queue_depth_backpressure` (back-pressure threshold)
3. Save. Next scheduled firing picks it up.
4. If you introduce a syntactically invalid YAML or schema-violating value: M10 triggers a CRITICAL halt on the next agent session. Fix the config and use [§14](#14-resume-the-fleet) to resume.

---

## 19. Manage the active-task roster (D9)

The active-task roster at [`docs/active_tasks.yaml`](../active_tasks.yaml) is how the fleet knows "what task(s) am I working on right now?". Scheduled SDO (Theme B) and scheduled Co-Lead (Theme C) read it at every wake-up. Schema validated M10-style; invalid roster halts agent sessions as a CRITICAL breach.

Shape:

```yaml
schema_version: 1
active_tasks:
  - task_id: 28
    continuation_xml: docs/P5_TASK7_SDO_CONTINUATION_v1.0.xml
    started: '2026-04-21'
    pause_after: false
pause_after_current: false
```

All roster writes are atomic (temp + os.replace). Never hand-edit while a scheduled session is running unless the fleet is paused.

### Inspect the roster

```
Get-Content 'C:\Users\mrbla\BlarAI\.platform\active_tasks.yaml'
```

### Add a task

```
python -c "from tools.autonomy_budget import active_tasks; active_tasks.add_active_task(<task_id>, '<continuation_xml_path>', path='C:/Users/mrbla/BlarAI/.platform/active_tasks.yaml')"
```

Replace `<task_id>` with the Vikunja tracking task id (Project 3) and `<continuation_xml_path>` with the repo-relative path to the SDO continuation XML you (or Co-Lead) authored. Idempotent: re-running with the same `(task_id, continuation_xml)` is a no-op; collisions with a different `continuation_xml` raise.

### Pause the fleet at the next task boundary

Flip the task's `pause_after: true` BEFORE it completes. When the task is marked complete, `pause_after_current=true` flips automatically and Co-Lead halts auto-transition.

```
# Manual edit -- or use the helper:
python -c "from tools.autonomy_budget import active_tasks; active_tasks.set_pause_after_current(True, path='C:/Users/mrbla/BlarAI/.platform/active_tasks.yaml')"
```

### Remove a task (mark complete manually)

Normally Co-Lead does this when a task's final milestone merges. Manual override:

```
python -c "from tools.autonomy_budget import active_tasks; active_tasks.mark_task_complete(<task_id>, path='C:/Users/mrbla/BlarAI/.platform/active_tasks.yaml')"
```

If the task had `pause_after: true`, this will flip `pause_after_current: true` — resume with the clear helper below.

### Clear the pause-at-boundary flag

```
python -c "from tools.autonomy_budget import active_tasks; active_tasks.clear_pause_after_current(path='C:/Users/mrbla/BlarAI/.platform/active_tasks.yaml')"
```

The next scheduled Co-Lead firing will then proceed to author the next task's SDO continuation XML (Theme C), assuming a `NextTaskResolver` has the next task authorized.

---

## 20. Switch merge policy mode (D9)

`tools/fleet_ops/merge_policy.py` (ticket 50) gates every merge-to-main in `trusted_scope` mode. Default is `review_all` (LA reviews every merge). The switch is a one-line edit — agents re-read config at every session start (M9), so no process restart required.

### Read current mode

```
Select-String -Path 'C:\Users\mrbla\devplatform\tools\autonomy_budget\config.yaml' -Pattern '^\s*mode:'
```

### Switch to trusted_scope (auto-merge within safety carve-outs)

1. Open `C:\Users\mrbla\devplatform\tools\autonomy_budget\config.yaml` in notepad.
2. Find `merge_policy:` (near the end of the file).
3. Change `mode: review_all` to `mode: trusted_scope`.
4. Save. Close notepad.
5. Verify:
   ```
   Select-String -Path 'C:\Users\mrbla\devplatform\tools\autonomy_budget\config.yaml' -Pattern '^\s*mode:'
   ```

### Switch back to review_all

Reverse of the above — change `mode: trusted_scope` to `mode: review_all`.

### Trusted-scope safety carve-outs (per DEC-11 v3 §3.4)

`decide()` auto-merges only when ALL of these pass:
- Every changed file is under an `allowlist_paths` prefix.
- No filename or path matches any `secret_patterns` glob (`*.env`, `credentials*`, `secrets*`, `*.pem`, `*.key`, `*.cert`, `*.pfx`, SSH keys, `.aws/credentials`, `.gitconfig`).
- Total LOC ≤ `runaway_loc_threshold` (default: 500).
- File count ≤ `runaway_file_threshold` (default: 30).

Any miss → Co-Lead fires `Gate:Pending-Human` the same way `review_all` does. Nothing slips through.

### Adjust thresholds or allowlist

Edit the same `merge_policy:` block in `config.yaml`. Schema validation catches obvious mistakes (`runaway_*_threshold: 0` → CRITICAL halt on next session). Full threshold / pattern list is documented in the file's inline comments.

### Emergency: halt auto-merge globally

Switch `mode: review_all` (1 edit + save) — the next Co-Lead firing sees the change and escalates all merges. No further action needed.

---

## 21. Bootstrap a new task (D9)

This is the procedure for kicking off a new task that the fleet will execute autonomously end-to-end. After bootstrap, the next scheduled EA Code wake-up picks up the queued prompt, executes the milestone, gates fire, reviews cascade, Co-Lead authors next milestones via Theme B, and the task progresses without LA intervention until merge gates (review_all) or the task completes (trusted_scope).

### Prerequisites

- Fleet installed (§1 through §6 of this runbook).
- Vikunja tracking task open for the work (Project 3 for Phase 5 runtime tasks, Project 4 for infrastructure work).
- SDO continuation XML authored at `docs/P5_TASK<N>_SDO_CONTINUATION_v1.0.xml`.
- First EA prompt XML authored at `docs/P5_TASK<N>_EA<M>_<descriptor>.xml`.

### Steps

1. **Copy the first EA prompt into the scheduled queue**:
   ```
   Copy-Item 'C:\Users\mrbla\BlarAI\docs\P5_TASK<N>_EA<M>_<descriptor>.xml' 'C:\Users\mrbla\BlarAI\docs\scheduled\ea_queue\task<N>_ea<M>.xml'
   ```
   Keep the original in `docs/` — it's the historical authored source; the copy in `ea_queue/` is what the scheduled EA picks up.

2. **Add the task to the active-task roster**:
   ```
   python -c "from tools.autonomy_budget import active_tasks; active_tasks.add_active_task(<task_id>, 'docs/P5_TASK<N>_SDO_CONTINUATION_v1.0.xml', path='C:/Users/mrbla/BlarAI/.platform/active_tasks.yaml')"
   ```

3. **Apply `Gate:Pending-Execution` label (id 16)** to the Vikunja tracking task. Use the MCP tool:
   ```
   # via mcp__vikunja__add_label_to_task(task_id=<N>, label_id=16)
   ```

4. **Commit the roster + queue addition**:
   ```
   cd 'C:\Users\mrbla\BlarAI'; git add docs/active_tasks.yaml docs/scheduled/ea_queue/task<N>_ea<M>.xml; git commit -m "[bootstrap] Task <N> - queue EA-<M> prompt + roster entry"
   ```

5. **Verify**:
   ```
   Get-Content 'C:\Users\mrbla\BlarAI\.platform\active_tasks.yaml'
   Get-ChildItem 'C:\Users\mrbla\BlarAI\docs\scheduled\ea_queue\'
   ```

The next scheduled EA Code wake-up (every 15 minutes per `config.yaml` `roles.ea_code.scheduled_poll_cron`) picks up the queued prompt and executes the milestone. After merge, Co-Lead (Theme C) auto-transitions to the next task if pause flags are clear.

### Tear down a bootstrap mid-flight

If you need to abort a bootstrapped task before the EA picks it up:
1. Remove the queued prompt: `Remove-Item 'C:\Users\mrbla\BlarAI\docs\scheduled\ea_queue\task<N>_ea<M>.xml'`
2. Remove the roster entry: `python -c "from tools.autonomy_budget import active_tasks; active_tasks.mark_task_complete(<task_id>, path='C:/Users/mrbla/BlarAI/.platform/active_tasks.yaml')"`
3. Remove the `Gate:Pending-Execution` label from the Vikunja task via `mcp__vikunja__remove_label_from_task(task_id=<N>, label_id=16)` (F-5).
4. Commit the tear-down.

---

## 22. Decommission the fleet

1. Unregister all scheduled tasks:
```
Get-ScheduledTask -TaskPath '\BlarAI\' | Unregister-ScheduledTask -Confirm:$false
```
2. Delete the Vikunja autostart shortcut from `shell:startup`.
3. Optionally: remove the F2 credential file:
```
Remove-Item 'C:\Users\mrbla\.blarai-fleet\credentials.env'; Remove-Item 'C:\Users\mrbla\.blarai-fleet' -ErrorAction SilentlyContinue
```
4. Optionally: remove the Event Log source (requires elevation):
```
Remove-EventLog -Source 'BlarAI Fleet'
```
5. Memory graph cleanup is a post-D8 hygiene task; the Fleet entities remain in the `memory` MCP graph as audit trail even after decommissioning.

Vikunja projects (6 Agent Gates, 7 Fleet Dashboard) remain intact — they're generically useful and contain historical records. Archive them via the Vikunja UI if desired.

---

## 23. `agents.ps1` task manager — the one-command way to pause, resume, or reinterval

`tools/scheduled-tasks/agents.ps1` gives you single-command control over the three agent wake tasks (**Wake SDO**, **Wake Co-Lead Architect**, **Wake EA Code**) without editing XML or using the Task Scheduler GUI. It operates at the Windows Task Scheduler level, so paused agents consume **zero API tokens** — important when you're on API billing and don't want idle firings between sprints.

Utility tasks (Toast Watchdog, Dashboard Maintainer, Welcome Back Poll, Gate Stale Cleaner, Daily Digest, Weekly Summary, Sprint Auditor, Credentials Rotation Reminder) are **not** touched by this script — they keep running so observability stays alive even when the fleet is paused.

### From a PowerShell terminal

```
.\tools\scheduled-tasks\agents.ps1 status              # current state + last/next run times
.\tools\scheduled-tasks\agents.ps1 pause               # disable all 3 agent tasks
.\tools\scheduled-tasks\agents.ps1 resume              # re-enable all 3 agent tasks
.\tools\scheduled-tasks\agents.ps1 interval 30         # change firing interval to 30 minutes
```

### From Claude Code (bash shell) or any non-PowerShell terminal

Prefix with `powershell -File`:

```
powershell -File tools/scheduled-tasks/agents.ps1 status
powershell -File tools/scheduled-tasks/agents.ps1 pause
powershell -File tools/scheduled-tasks/agents.ps1 resume
powershell -File tools/scheduled-tasks/agents.ps1 interval 30
```

### From an interactive Claude Code session

Either ask Claude in English (*"show me agent status"*, *"pause the agents"*, *"set interval to 30 min"*) and it will run the script for you, or type the `!`-prefixed form as the first character of a new prompt line:

```
! powershell -File tools/scheduled-tasks/agents.ps1 status
```

### `pause` vs `state.pause_fleet()` (§13)

| Aspect | `agents.ps1 pause` (this section) | `state.pause_fleet()` (§13) |
|---|---|---|
| Mechanism | Disables the scheduled tasks themselves | Sets `fleet_paused=true` flag in `state.json` |
| Wake-up sessions fire? | No — scheduler never launches them | Yes — session launches, reads flag, exits |
| API token cost while paused | Zero | \~1 tiny firing-exit per 15-min per agent (non-zero) |
| Records a reason string? | No | Yes (`state.json` captures caller + reason) |
| Generates firing-exit reports? | No | Yes (each skipped firing emits a report) |
| Best for | Vacation, off-hours, between sprints | Mid-sprint pause where you want auditable reason + firing-exit trail |

Most LA-triggered pauses should use `agents.ps1 pause`. Reserve `state.pause_fleet()` for scenarios where the audit trail matters (e.g. a security incident response).

### `interval` — what it actually changes

The `interval <N>` action rewrites two places atomically:

1. **The source XML on disk** (`tools/scheduled-tasks/wake-*.xml`) so reinstalls reflect the new cadence.
2. **The live Task Scheduler registration** via `Export-ScheduledTask` → string-replace → `Register-ScheduledTask -Force`.

The new interval takes effect on the next firing boundary. The budget config at `tools/autonomy_budget/config.yaml` (`roles.*.scheduled_poll_cron`) is **not** updated by this script — it's a documentation-only field consumed by humans. If you want the cron value there to match the new live interval, edit it by hand.

Minimum supported interval is 5 minutes (the script rejects lower). There is no maximum.

### Verify the change landed

```
.\tools\scheduled-tasks\agents.ps1 status
```

…shows `last` and `next` run times. If `next` is more than the new interval away, something didn't apply — inspect with `Export-ScheduledTask -TaskPath '\BlarAI\' -TaskName 'Wake SDO'` and look for `<Interval>PT{N}M</Interval>` in the output.

### Why this exists

Before `agents.ps1`, pausing required editing XML or running PowerShell snippets against `Unregister-ScheduledTask`, and changing cadence meant editing each of the three XML files by hand then re-registering. That's hostile to a non-dev operator who just wants "stop the fleet while I'm on vacation" or "slow down the agents while I debug something". The script collapses those workflows to one line.

---

## Cross-references

- Design: [`docs/CLAUDE_AUTONOMOUS_FLEET_OPS_D8.md`](../CLAUDE_AUTONOMOUS_FLEET_OPS_D8.md)
- Locked decisions: [`docs/DOMAIN8_DEC11_BUDGET_PROPOSAL_v3.xml`](../DOMAIN8_DEC11_BUDGET_PROPOSAL_v3.xml)
- MCP refresh drill: [`docs/runbooks/MCP_REFRESH_DRILL.md`](MCP_REFRESH_DRILL.md)
- Commit handshake (if Bash degrades): [`docs/runbooks/COMMIT_HANDSHAKE_PATTERN.md`](COMMIT_HANDSHAKE_PATTERN.md)
- SDO prompt discipline: [`docs/runbooks/SDO_PROMPT_DISCIPLINE_CHECKLIST.md`](SDO_PROMPT_DISCIPLINE_CHECKLIST.md)
- MCP config sync: [`docs/runbooks/MCP_CONFIG_SYNC.md`](MCP_CONFIG_SYNC.md)
- Spike-4 walkthrough: [`docs/SPIKE4_LA_WALKTHROUGH.md`](../SPIKE4_LA_WALKTHROUGH.md)
