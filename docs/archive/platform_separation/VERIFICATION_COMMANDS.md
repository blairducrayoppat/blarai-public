# Verification Commands — Lead Architect Cheat Sheet

Copy-paste commands to verify each stage succeeded. The Lead Architect doesn't read code — terminal output is the source of truth.

All commands are PowerShell on Windows.

---

## v2 Additions (2026-04-24)

```powershell
# Worktree precondition (before Stage 0 and Stage 4)
git worktree list                                    # expect: only main worktree

# Fleet pause/resume state
python -c "import json; print('PAUSED' if json.load(open('tools/autonomy_budget/state.json'))['fleet_paused'] else 'RUNNING')"

# state.json schema sanity (9 required fields, schema_version=1)
python -c "import json; s=json.load(open('tools/autonomy_budget/state.json')); req={'schema_version','fleet_paused','fleet_paused_reason','role_paused','last_updated_utc','last_updated_by','last_welcome_back_utc'}; missing=req-set(s); print('OK' if not missing and s['schema_version']==1 else f'MISSING: {missing}')"

# Scheduled task count (live baseline = 13; v2 does NOT change the count)
(Get-ScheduledTask -TaskPath '\BlarAI\').Count    # expect: 13

# Vikunja Fleet Reports project_id locked at 8 (verify via registry seed)
Select-String -Path C:\Users\mrbla\devplatform\projects\registry.yaml -Pattern 'fleet_reports:\s*8'

# Wake-template path scan (after Stage 4.7.5)
Select-String -Path C:\Users\mrbla\devplatform\docs\scheduled\wake_templates\*.md -Pattern 'BlarAI\\tools'   # expect: NO matches

# wake_launcher.ps1 residual BlarAI refs (after Stage 4.7.6)
# CORRECT path: tools/scheduled-tasks/wake_launcher.ps1 (NOT tools/fleet_ops/)
Select-String -Path C:\Users\mrbla\devplatform\tools\scheduled-tasks\wake_launcher.ps1 -Pattern 'C:\\Users\\mrbla\\BlarAI(?!\\-worktrees)' -AllMatches | Select-Object LineNumber, Line

# Test baseline (post-cutover, expect ~981 passed / 22 skipped)
cd C:\Users\mrbla\BlarAI; .\.venv\Scripts\Activate.ps1; pytest shared/ services/ launcher/ --tb=short -q
```

**Function-name reminder:** `state.resume_fleet()` — NEVER `unpause_fleet()`.

---

## Universal Pre-Flight

```powershell
# Confirm working tree and branch
cd C:\Users\mrbla\BlarAI
git status
git branch --show-current
git log --oneline -5
```

---

## Stage 0 — Preflight

```powershell
# Backup anchors exist
Test-Path "C:\Users\mrbla\backups\BlarAI_pre_extract.bundle"
Get-ChildItem "C:\Users\mrbla\backups\blarai_oog_*.zip" | Select Name, Length
Get-ChildItem "C:\Users\mrbla\backups\scheduled_tasks_export\" | Measure-Object | Select Count

# Tag created
cd C:\Users\mrbla\BlarAI; git tag | Select-String "pre-platform-extract"

# Scheduled tasks disabled (correct filter: TaskPath '\BlarAI\')
Get-ScheduledTask -TaskPath '\BlarAI\' | Select-Object TaskName, State

# Branch created
git branch | Select-String "chore/platform-extraction"
```

**Expected**: bundle + zip + XML dir all exist, tag present, all 13 tasks at TaskPath `\BlarAI\` in `Disabled` state, branch exists.

---

## Stage 1 — Scaffold

```powershell
# devplatform exists
Test-Path "C:\Users\mrbla\devplatform"
Test-Path "C:\Users\mrbla\devplatform\.git"
Test-Path "C:\Users\mrbla\devplatform\.venv"
Test-Path "C:\Users\mrbla\devplatform\pyproject.toml"

# Registry in place
Get-Content "C:\Users\mrbla\BlarAI\.platform\vikunja_project_ids.yaml"

# DevPlatform-Meta Vikunja project exists (check via web UI or MCP)
# In a Claude Desktop session: "list my Vikunja projects"
```

**Expected**: devplatform tree set up, registry YAML has both project IDs filled in.

---

## Stage 2 — Refactor

```powershell
# New shared modules exist in BlarAI
Test-Path "C:\Users\mrbla\BlarAI\tools\_vikunja_client.py"
Test-Path "C:\Users\mrbla\BlarAI\tools\_project_context.py"

# Tests pass
cd C:\Users\mrbla\BlarAI; .\.venv\Scripts\Activate.ps1
pytest tools/ --tb=short -q
pytest shared/ services/ --tb=short -q

# Commit happened on feature branch
git log --oneline chore/platform-extraction -5
```

**Expected**: modules exist, tests pass, commit on `chore/platform-extraction`.

---

## Stage 3 — Copy

```powershell
# devplatform has tools
Get-ChildItem C:\Users\mrbla\devplatform\tools -Directory | Select Name

# devplatform MCP config has env var references (not plaintext password)
Get-Content C:\Users\mrbla\devplatform\.vscode\mcp.json | Select-String "VIKUNJA_PASS"

# devplatform editable install works
cd C:\Users\mrbla\devplatform; .\.venv\Scripts\Activate.ps1
pip list | Select-String "devplatform"
python -c "from tools import _vikunja_client; print('ok')"

# Dry-run smoke test (should not write anything)
python -m tools.vikunja_mcp.cli --project-id <devplatform_meta_id> --dry-run list-tasks
```

**Expected**: 7 tool dirs present, env-var substitution in configs (not plaintext), package installed editable, dry-run executes cleanly.

---

## Stage 4 — Cutover

```powershell
# Vikunja DB moved
Test-Path "C:\Users\mrbla\BlarAI\tools\vikunja\vikunja.db"      # should be False
Test-Path "C:\Users\mrbla\devplatform\tools\vikunja\vikunja.db" # should be True

# Vikunja running from devplatform
Invoke-RestMethod http://localhost:3456/api/v1/info
Get-Process | Where-Object { $_.Path -like "*devplatform*vikunja*" } | Select Path

# MCP configs have backups AND point to devplatform
Test-Path "$env:APPDATA\Claude\claude_desktop_config.json.pre_stage4_bak"
Get-Content "$env:APPDATA\Claude\claude_desktop_config.json" | Select-String "devplatform"

# Scheduled tasks re-enabled and passing (correct filter: TaskPath '\BlarAI\')
Get-ScheduledTask -TaskPath '\BlarAI\' | Get-ScheduledTaskInfo |
  Select TaskName, LastRunTime, LastTaskResult | Format-Table

# Bridge daemon running from devplatform
Get-Process python | Where-Object { $_.Path -like "*devplatform*" } | Select Path, Id
```

**Expected**: DB moved, Vikunja API responds, MCP configs have backups + repointed, all scheduled tasks `LastTaskResult = 0`.

---

## Stage 5 — Cleanup

```powershell
# Platform tool dirs removed from BlarAI
Get-ChildItem C:\Users\mrbla\BlarAI\tools -Directory | Select Name
# Should show only: openvino_contrib_agent (and any BlarAI-only dirs)

# .platform populated
Get-ChildItem C:\Users\mrbla\BlarAI\.platform

# BlarAI tests still pass
cd C:\Users\mrbla\BlarAI; .\.venv\Scripts\Activate.ps1
pytest shared/ services/ --tb=short -q
# Expected: ~981 passed, 22 skipped (post-Sprint 9 hardening; pre-Sprint 9 baseline was 755 passed, 2 skipped — see STATUS.md and Stage 5.8.v2)

# Platform doctrine docs removed from BlarAI/docs/
Get-ChildItem C:\Users\mrbla\BlarAI\docs -File | Where-Object {
  $_.Name -match "CLAUDE_|CO_LEAD_|DEC[0-9]+|DOMAIN[0-9]"
}
# Expected: empty

# Merge to main
cd C:\Users\mrbla\BlarAI
git log --oneline main -5
git tag | Select-String "platform"
# Expected: post-platform-extract tag present, merge commit on main
```

---

## Stage 6 — Hardening

```powershell
# Doctrine files exist in both repos
Test-Path C:\Users\mrbla\BlarAI\CLAUDE.md
Test-Path C:\Users\mrbla\devplatform\CLAUDE.md

# BlarAI CLAUDE.md should be smaller than before
(Get-Content C:\Users\mrbla\BlarAI\CLAUDE.md -Raw).Length

# 24h soak — all tasks healthy (correct filter: TaskPath '\BlarAI\')
Get-ScheduledTask -TaskPath '\BlarAI\' |
  Get-ScheduledTaskInfo |
  Select TaskName, LastRunTime, LastTaskResult |
  Format-Table

# All LastTaskResult should be 0

# Archive moved
Test-Path C:\Users\mrbla\BlarAI\docs\archive\platform_separation
Test-Path C:\Users\mrbla\BlarAI\docs\platform_separation  # should be False
```

---

## Quick Health-Check (any time post-migration)

Save this as a one-liner for the Lead Architect to run whenever they want to confirm the fleet is healthy:

```powershell
Write-Host "=== Vikunja ===";
try { Invoke-RestMethod http://localhost:3456/api/v1/info | Select version } catch { Write-Host "VIKUNJA DOWN" -Foreground Red };
Write-Host "=== Scheduled Tasks ===";
Get-ScheduledTask -TaskPath '\BlarAI\' | Get-ScheduledTaskInfo |
  Select TaskName, LastRunTime, @{n="Result";e={if($_.LastTaskResult -eq 0){"OK"}else{"FAIL($($_.LastTaskResult))"}}} |
  Format-Table -AutoSize;
Write-Host "=== Bridge Daemon ===";
Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
  Where-Object { $_.CommandLine -match 'vikunja_mcp\.bridge' } |
  Select-Object ProcessId, CommandLine, CreationDate
```

**Healthy output**: Vikunja version string, all tasks "OK", bridge daemon process listed.
