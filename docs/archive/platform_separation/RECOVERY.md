# Platform Separation — RECOVERY

Consolidated rollback procedures by severity. Each stage XML has its own `<rollback>` block — this file aggregates them plus adds full-disaster procedures.

---

## v2 Additions (2026-04-24)

### Worktree contamination recovery
If a stage fails because `git worktree list` shows an active worktree on the same branch we're operating on:
```powershell
git worktree list                        # identify orphan worktree
cd <orphan-worktree-path>; git status    # commit or stash any changes
cd C:\Users\mrbla\BlarAI
git worktree remove <orphan-worktree-path>
git worktree prune
```
Then re-run the failing stage from its first work item.

### state.json schema_version=1 restoration
If `tools/autonomy_budget/state.json` is corrupted or missing required fields:
```powershell
git show HEAD:tools/autonomy_budget/state.json | Out-File -Encoding UTF8 tools/autonomy_budget/state.json
```
Required fields (9): `schema_version` (=1), `fleet_paused`, `fleet_paused_reason`, `role_paused` (5-key dict: sdo/co_lead/ea_code/sprint_auditor/cross_role), `last_updated_utc`, `last_updated_by`, `last_welcome_back_utc`, plus any v2-added fields. Verify post-restore:
```powershell
python -c "import json; s=json.load(open('tools/autonomy_budget/state.json')); assert s['schema_version']==1; assert 'fleet_paused' in s; print('OK')"
```

### Fleet stuck paused after failed cutover
After a failed Stage 4, the fleet is intentionally left paused. Do NOT call `state.resume_fleet()` until either rollback completes OR the cutover is fixed and re-verified. If you accidentally resume, re-pause immediately:
```powershell
python -c "from tools.autonomy_budget import state; state.pause_fleet('post-failure quarantine', updated_by='copilot_agent', path='C:/Users/mrbla/BlarAI/tools/autonomy_budget/state.json')"
```
Note: function is `resume_fleet`, NEVER `unpause_fleet` (AttributeError).

---

## Severity Ladder

| Level | Scope | Trigger | Recovery time |
|---|---|---|---|
| 1 | Single work item failed | Test fails mid-stage | Minutes |
| 2 | Single stage needs reverting | Stage exit criteria unmet | Minutes |
| 3 | Post-cutover regression (Stage 4+) | Fleet misbehaves on devplatform | ~30 min |
| 4 | Full disaster | Vikunja DB corrupted, MCP broken, can't start fleet | ~1 hour from bundle/zip |

---

## Level 1 — Work Item Failure

**Always**: stop. Do not proceed to next work item. Read the specific item's `<expected>` and compare against actual output. If the item has a local `<rollback>` or `<verify>` step, use that.

Typical pattern:
- If only a file was created/modified: `git diff` → manually revert or `git checkout <path>`.
- If a scheduled task was changed: `Unregister-ScheduledTask` then re-register from the pristine export in `C:\Users\mrbla\backups\scheduled_tasks_export\`.

---

## Level 2 — Stage Rollback

Each stage XML contains a `<rollback>` block specific to it. Cross-reference:

- **Stage 0 rollback**: Just delete the tag, bundle, and zip. Re-enable scheduled tasks (`Enable-ScheduledTask`).
- **Stage 1 rollback**: `Remove-Item -Recurse C:\Users\mrbla\devplatform`. Delete DevPlatform-Meta project in Vikunja (via `mcp__vikunja__delete_project` or web UI). Delete `C:\Users\mrbla\BlarAI\.platform\vikunja_project_ids.yaml`.
- **Stage 2 rollback**: `cd C:\Users\mrbla\BlarAI; git reset --hard HEAD~1` (on `chore/platform-extraction` branch). Fleet stays disabled, no runtime impact.
- **Stage 3 rollback**: `cd C:\Users\mrbla\devplatform; git reset --hard HEAD~1`. BlarAI is unaffected.
- **Stage 4 rollback**: See stage XML — 4 sub-levels from Vikunja-only to full rollback. Most likely: restore MCP configs from `.pre_stage4_bak` files and move Vikunja DB back to BlarAI.
- **Stage 5 rollback**: `cd C:\Users\mrbla\BlarAI; git reset --hard pre-platform-extract` restores all deleted platform tools and docs from git. MCP configs (Stage 4 state) stay — decide whether to cascade rollback to Stage 4.
- **Stage 6 rollback**: Just revert the doctrine split commits on both repos. Platform keeps working.

---

## Level 3 — Post-Cutover Fleet Regression

After Stage 4, the fleet runs from devplatform. If a scheduled task fails:

1. `Disable-ScheduledTask -TaskName <failing>` immediately.
2. `Get-WinEvent -LogName Microsoft-Windows-TaskScheduler/Operational -MaxEvents 20` — read the error.
3. If python traceback: check `python -m tools.<module>` works manually from the devplatform .venv.
4. If the devplatform toolchain is the problem, temporarily repoint that ONE task's XML back to BlarAI paths (BlarAI platform-tool files still exist until Stage 5). Re-enable.
5. Fix the devplatform copy, re-repoint the task, re-enable.

If multiple tasks fail: execute Stage 4 Rollback Level 4 (full rollback to pre-cutover).

---

## Level 4 — Full Disaster Recovery from Backups

Trigger: Vikunja DB is corrupt, both repos have issues, MCP configs won't work, etc.

### From git bundle
```powershell
cd C:\Users\mrbla
Remove-Item -Recurse -Force BlarAI_broken    # rename the broken one first
Move-Item BlarAI BlarAI_broken
git clone C:\Users\mrbla\backups\BlarAI_pre_extract.bundle BlarAI
cd BlarAI
git checkout pre-platform-extract
```
This gives back a bit-exact BlarAI at the pre-Stage-0 state. Note: git bundle does NOT contain untracked files, the Vikunja DB, MCP configs, or scheduled tasks.

### From OOG zip
```powershell
Expand-Archive -Path "C:\Users\mrbla\backups\blarai_oog_<timestamp>.zip" -DestinationPath "C:\Users\mrbla\restore_staging"
# Manually reinstate:
#   Vikunja DB → BlarAI/tools/vikunja/vikunja.db
#   MCP configs → $env:APPDATA\Claude\claude_desktop_config.json, .vscode/mcp.json, .mcp.json
#   Bridge state → tools/vikunja_mcp/bridge/*.json
```

### Scheduled Tasks
```powershell
Get-ChildItem C:\Users\mrbla\backups\scheduled_tasks_export\*.xml | ForEach-Object {
  Unregister-ScheduledTask -TaskName $_.BaseName -Confirm:$false -ErrorAction SilentlyContinue;
  Register-ScheduledTask -Xml (Get-Content $_.FullName -Raw) -TaskName $_.BaseName
}
```

### Re-verify
```powershell
# Vikunja
cd C:\Users\mrbla\BlarAI\tools\vikunja; Start-Process .\vikunja-v2.3.0-windows-4.0-amd64.exe
Invoke-RestMethod http://localhost:3456/api/v1/info
# Fleet
Get-ScheduledTask -TaskPath '\BlarAI\' | Select TaskName, State
# Claude Desktop: restart the app, ask it to list Vikunja projects
```

---

## What the Recovery Anchors DO and DON'T Cover

| Asset | Git tag | Git bundle | OOG zip | Sched task XMLs |
|---|:-:|:-:|:-:|:-:|
| Tracked source files | ✅ | ✅ | ✅ | — |
| Untracked files | — | — | ✅ | — |
| .gitignored files (e.g., .venv) | — | — | rebuildable from pyproject | — |
| Vikunja SQLite DB | — | — | ✅ | — |
| MCP configs ($env:APPDATA\Claude\) | — | — | ✅ | — |
| `.vscode/mcp.json` | — | ✅ (tracked) | ✅ | — |
| Bridge state (inbox/processed/state.json) | — | — | ✅ | — |
| Windows Scheduled Tasks | — | — | — | ✅ |
| Claude Desktop project pins | — | — | ✅ | — |

**Takeaway**: all three anchors together cover everything that could be lost. Miss any one of them and a specific asset becomes unrecoverable.

---

## Decision Rule: When to Level-Up

- If 1 work item fails and you understand why → Level 1.
- If you can't explain the failure within 15 minutes → Level 2.
- If Level 2 rollback didn't restore working state → Level 3 (or Level 4 if cutover already happened).
- If the fleet, Vikunja, and MCP are all broken → Level 4 immediately. Don't try to fix in place.

**Default bias**: when in doubt, roll back. This is a reversible migration precisely because we invested in three recovery layers.
