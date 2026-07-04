# Rollback — Novice Operator Guide

**Audience:** You. The Lead Architect, who directs agents but does not write code.
**Companion to:** [`RECOVERY.md`](RECOVERY.md) (the technical reference). This file translates that reference into "what do I do RIGHT NOW".

---

## v2 Quick Recovery: "The fleet keeps eating my files"

**Symptom:** You open VS Code and your edits are gone, OR git shows uncommitted files in unexpected places, OR a branch you didn't create suddenly exists.

**Cause:** The autonomous fleet (cron-fired Claude sessions) was running while you were editing. It uses git auto-stash and may operate from a worktree (`C:\Users\mrbla\BlarAI-worktrees\`).

**What to do:**
1. STOP editing. Don't close VS Code yet.
2. Open a PowerShell in `C:\Users\mrbla\BlarAI` and run:
   ```powershell
   git stash list                              # see if your work is in a stash
   git worktree list                           # see if anything else is using your branch
   ```
3. If `git stash list` shows entries with recent timestamps → your work is recoverable: `git stash pop` (try the most recent first).
4. Pause the fleet immediately so it stops interfering:
   ```powershell
   python -c "from tools.autonomy_budget import state; state.pause_fleet('manual edit session', updated_by='lead_architect', path='C:/Users/mrbla/BlarAI/tools/autonomy_budget/state.json')"
   git add tools/autonomy_budget/state.json
   git commit -m "chore(ops): pause fleet -- manual edit session"
   ```
5. Resume your edits. Unpause when done:
   ```powershell
   python -c "from tools.autonomy_budget import state; state.resume_fleet(updated_by='lead_architect', path='C:/Users/mrbla/BlarAI/tools/autonomy_budget/state.json')"
   git add tools/autonomy_budget/state.json
   git commit -m "chore(ops): unpause fleet"
   ```

**Don't say `unpause_fleet`** — the function is `resume_fleet`. Wrong name = `AttributeError`.

---

## TL;DR Verdict on Current Rollback Readiness

| Aspect | Rating | Notes |
|---|---|---|
| Recovery anchors exist (git tag, bundle, OOG zip) | ✅ Solid | Stage 0 produces all three. |
| 4-level severity ladder makes the right call easy | ✅ Solid | Decision rules in RECOVERY.md §"Decision Rules". |
| Asset coverage matrix tells you what each restore covers | ✅ Solid | Verified column is honest. |
| Novice can execute Level 1 unaided | ✅ Yes | Single `git restore` command. |
| Novice can execute Level 2 unaided | ⚠️ With this guide | PowerShell commands assume Move-Item / Get-Process literacy. |
| Novice can execute Level 3 unaided | ⚠️ With this guide + panic card | Multi-step. Order matters. |
| Novice can execute Level 4 unaided | ❌ No | OOG full-restore needs hand-walking; you'll want an agent at the keyboard. |
| Rollback has been **rehearsed** | ❌ No | **Strongly recommend a dry-run drill before Stage 4.** |

**Bottom line:** the structure is rock-solid. The gap is *practice*. Do the drill in §3 before you start Stage 4 and Levels 1–3 become muscle memory. Level 4 is a "wake an agent" event regardless.

---

## 1. Symptom → Action Table (Read This First When Things Go Wrong)

| What you observe | Severity | First action | Reference |
|---|---|---|---|
| One file looks edited wrong (unstaged) | L1 | `git restore <path>` | RECOVERY.md §L1 |
| One file you committed today is wrong | L1 | `git revert HEAD` | RECOVERY.md §L1 |
| Vikunja UI loads but tasks look mangled / missing | L2 | STOP Vikunja → restore DB from `.cutover_bak` (item 4.1 rollback one-liner) | This file §4 |
| Vikunja won't start at all (port 3456 dead) | L2 | Check process; restart from BlarAI path; if still dead, restore DB | This file §4 |
| MCP tools return errors in VS Code / Claude Code | L2 | Restore the `.pre_stage4_bak` mcp.json files | This file §5 |
| Scheduled task ran and broke something | L2 | `Disable-ScheduledTask -TaskName <name>` immediately, then investigate | RECOVERY.md §L2 |
| Stage 4 partway through and you've lost track | L3 | STOP. Check STATUS.md. Restore from `pre-platform-extract` git tag + DB backup | This file §6 |
| Stage 5 cleanup deleted something you needed | L3 | Restore from git tag (files were committed before deletion in Stage 5.1) | RECOVERY.md §L3 |
| BlarAI repo is corrupted / unrecognizable | L4 | Wake an agent. Do not attempt L4 alone. | RECOVERY.md §L4 |
| Disk failure / Windows reinstalled / catastrophic | L4 | Wake an agent. OOG zip + bundle restore needed. | RECOVERY.md §L4 |

---

## 2. The Panic Card (Print This Before Stage 4)

**Tape this near your monitor before you start the cutover stage.**

```
╔══════════════════════════════════════════════════════════════════╗
║                  BLARAI EXTRACTION — PANIC CARD                  ║
╠══════════════════════════════════════════════════════════════════╣
║                                                                  ║
║  STOP EVERYTHING:                                                ║
║    Get-Process vikunja* | Stop-Process -Force                    ║
║    Get-ScheduledTask -TaskPath '\BlarAI\' |                      ║
║      Disable-ScheduledTask                                       ║
║                                                                  ║
║  WHERE IS MY VIKUNJA DB?                                         ║
║    Backup:  C:\Users\mrbla\BlarAI\tools\vikunja\                 ║
║             vikunja.db.cutover_bak                               ║
║    Bundle:  C:\Users\mrbla\backups\BlarAI_pre_extract.bundle     ║
║    OOG zip: (location set during Stage 0.6)                      ║
║                                                                  ║
║  ROLLBACK DB (item 4.1 inverse):                                 ║
║    Move-Item C:\Users\mrbla\BlarAI\tools\vikunja\                ║
║      vikunja.db.cutover_bak                                      ║
║      C:\Users\mrbla\BlarAI\tools\vikunja\vikunja.db -Force       ║
║    Remove-Item C:\Users\mrbla\devplatform\tools\vikunja\         ║
║      vikunja.db -ErrorAction SilentlyContinue                    ║
║                                                                  ║
║  ROLLBACK GIT (everything BlarAI committed):                     ║
║    cd C:\Users\mrbla\BlarAI                                      ║
║    git reset --hard pre-platform-extract                         ║
║                                                                  ║
║  RESTART VIKUNJA FROM BLARAI:                                    ║
║    cd C:\Users\mrbla\BlarAI\tools\vikunja                        ║
║    Start-Process .\vikunja-v2.3.0-windows-4.0-amd64.exe          ║
║                                                                  ║
║  IF ANY OF THE ABOVE FAILS — STOP AND WAKE AN AGENT.             ║
║  Do not improvise. Do not delete anything. Do not run            ║
║  `git clean` or `git push --force`.                              ║
║                                                                  ║
╚══════════════════════════════════════════════════════════════════╝
```

---

## 3. Dry-Run Rollback Drill (Do This Before Stage 4)

**Why:** Practising restore on disposable data costs \~15 minutes and eliminates 90% of the panic-induced errors that cause real data loss.

**Setup (5 min):**
```powershell
# Make a throwaway sandbox so you don't touch real data
mkdir C:\Users\mrbla\drill
cd C:\Users\mrbla\drill
git init
"hello" | Out-File test.txt
git add . ; git commit -m "before"
git tag drill-anchor
"changed" | Out-File test.txt
git commit -am "after"
```

**Drill 1 — Level 1 restore (1 min):**
```powershell
# Edit test.txt manually with notepad, save garbage. Then:
git restore test.txt
Get-Content test.txt        # Should show "changed"
```
✅ If you see "changed", you understand `git restore`.

**Drill 2 — Level 3 git tag restore (2 min):**
```powershell
git reset --hard drill-anchor
Get-Content test.txt        # Should show "hello"
git log --oneline           # Should show only the "before" commit
```
✅ If you see "hello" and one commit, you understand the nuclear git rollback.

**Drill 3 — DB swap (5 min):**
```powershell
"VERSION_A" | Out-File fake.db
Copy-Item fake.db fake.db.cutover_bak
"VERSION_B" | Out-File fake.db -Force          # simulates a successful migration
Get-Content fake.db                             # "VERSION_B"
# Now simulate disaster — restore:
Move-Item fake.db.cutover_bak fake.db -Force
Get-Content fake.db                             # "VERSION_A"
```
✅ If `fake.db` shows `VERSION_A`, you understand the DB rollback pattern.

**Cleanup:**
```powershell
cd C:\Users\mrbla
Remove-Item -Recurse -Force C:\Users\mrbla\drill
```

After running this drill, **you can execute Levels 1–3 without help**.

---

## 4. Vikunja DB Recovery — Step-by-step

**When:** Tasks look wrong, Vikunja won't start cleanly after Stage 4, or item 4.1 verify failed.

```powershell
# Step 1: Stop Vikunja completely
Get-Process vikunja* -ErrorAction SilentlyContinue | Stop-Process -Force
Start-Sleep -Seconds 2
# Confirm no process holds the DB:
Get-Process vikunja* -ErrorAction SilentlyContinue   # should be empty

# Step 2: Run the rollback one-liner from item 4.1
Move-Item `
  "C:\Users\mrbla\BlarAI\tools\vikunja\vikunja.db.cutover_bak" `
  "C:\Users\mrbla\BlarAI\tools\vikunja\vikunja.db" -Force
Remove-Item "C:\Users\mrbla\devplatform\tools\vikunja\vikunja.db" -ErrorAction SilentlyContinue

# Step 3: Restart from BlarAI (the original location)
cd C:\Users\mrbla\BlarAI\tools\vikunja
Start-Process .\vikunja-v2.3.0-windows-4.0-amd64.exe

# Step 4: Wait, then verify
Start-Sleep -Seconds 5
Invoke-RestMethod http://localhost:3456/api/v1/info
# Open http://localhost:3456 in browser, log in, confirm tasks visible
```

**If `.cutover_bak` does not exist:** that means item 4.1 never ran — your DB is still at the BlarAI path and you've nothing to roll back. Just restart Vikunja from BlarAI.

---

## 5. MCP Config Recovery — Step-by-step

**When:** After Stage 4, MCP tools error out in VS Code or Claude Code.

```powershell
# Restore the backups created by items 4.5 and 4.6
Copy-Item "C:\Users\mrbla\BlarAI\.vscode\mcp.json.pre_stage4_bak" `
          "C:\Users\mrbla\BlarAI\.vscode\mcp.json" -Force
Copy-Item "C:\Users\mrbla\BlarAI\.mcp.json.pre_stage4_bak" `
          "C:\Users\mrbla\BlarAI\.mcp.json" -Force

# Then restart VS Code completely (close all windows) and Claude Code
```

If the `.pre_stage4_bak` files don't exist, items 4.5/4.6 didn't run — your configs are unmodified. Restart the affected app.

---

## 6. "I'm Lost in Stage 4" — Recovery

**Symptoms:** You don't remember which item you were on. Verify commands are returning errors. STATUS.md is out of sync with reality.

```powershell
# 1. STOP all active fleet activity
Get-Process vikunja* -ErrorAction SilentlyContinue | Stop-Process -Force
Get-ScheduledTask -TaskPath '\BlarAI\' | Disable-ScheduledTask

# 2. Take a snapshot of current state (don't delete anything yet)
git -C C:\Users\mrbla\BlarAI status > C:\Users\mrbla\where_was_i.txt
git -C C:\Users\mrbla\BlarAI log --oneline -20 >> C:\Users\mrbla\where_was_i.txt
Get-ChildItem C:\Users\mrbla\BlarAI\tools\vikunja >> C:\Users\mrbla\where_was_i.txt
if (Test-Path C:\Users\mrbla\devplatform) {
  Get-ChildItem C:\Users\mrbla\devplatform\tools\vikunja -ErrorAction SilentlyContinue >> C:\Users\mrbla\where_was_i.txt
}

# 3. Wake an agent. Hand them where_was_i.txt. Do not improvise further.
```

**Why not just `git reset --hard pre-platform-extract`?**
Because Stage 4 mutates state OUTSIDE git: the SQLite DB location, scheduled-task registrations, Windows Startup shortcuts, MCP config files. A git rollback alone leaves those in a half-migrated state. An agent will sequence the unwind correctly.

---

## 7. What This Guide Does NOT Cover

- **Level 4 (catastrophic OOG-zip restore)**: needs an agent at the keyboard — your job is to verify the OOG zip exists in its expected location (Stage 0.6) and is < 90 days old.
- **Disaster after Stage 6 (post-extraction)**: by that point, BlarAI is a research-archive repo and devplatform owns Vikunja. Recovery procedures shift to devplatform's own backups. That's a topic for after Stage 6 sign-off.
- **Hardware failure mid-extraction**: outside this plan's scope. The OOG zip is your insurance.

---

## 8. Self-Test: Are You Ready for Stage 4?

Tick all six before starting Stage 4. If any is unchecked, **stop and resolve it first**.

- [ ] I have run the dry-run drill in §3 and all three drills passed.
- [ ] The panic card in §2 is printed and visible from my chair.
- [ ] I know the location of `BlarAI_pre_extract.bundle`.
- [ ] I know the location of the OOG zip and have verified it opens.
- [ ] `git tag --list pre-platform-extract` returns `pre-platform-extract`.
- [ ] I have at least 60 minutes of uninterrupted time before starting Stage 4.

---

**End of guide.**
