# Session Ops Surface — STANDING (the one copy)

SSOT for BlarAI process control in Claude sessions: the standing authorization plus the
start / stop / verify commands. Landing cards and doctrine **cite this path — never paste
this content** (the pre-2026-07-28 era pasted a near-identical copy into ~30 of its 137
briefs, with no shared history; measured, see #1144). When the ops surface changes, update THIS file in
the same change that alters it — it is version-controlled, so drift is diffable here and
nowhere else.

**STANDING AUTHORIZATION (User-Operator):** sessions run ELEVATED (admin) with FULL
authority to start/stop BlarAI, start/stop the coder (30B) and any dispatch, and
start/stop/query the battery scheduled task — WITHOUT asking. **NEVER pause work to ask the
User-Operator to start/stop any of these** (auto-memory: freely-start/stop-AO/launcher/GPU/
builds; stop-doomed-runs-fast; execute-don't-stop-when-goal-clear). Only genuine
`decision_boundary` items route to the User-Operator — a capability/quality/security-posture
flip, a go-live ceremony — NEVER routine process control.

**UP vs DOWN:** keep BlarAI DOWN for merges + the standing gate (clean-env: no live-app
`:5001` skips, models present). UP only for a live surface (drive a chat, a validation
dispatch).

## START (elevated shell)

```powershell
Start-Process -FilePath "C:\Users\mrbla\BlarAI\.venv\Scripts\pythonw.exe" -ArgumentList '-m','launcher','--winui' -WorkingDirectory "C:\Users\mrbla\BlarAI"
```

- MUST be the venv-shim `pythonw` (bare/system pythonw dies silently — lacks
  `cryptography`); cwd = repo. Elevated is fine — the shim de-elevates the WinUI child
  (orphan-guarded).
- Confirm UP (~30–60 s, 14B cold-load): `:5001` listening
  (`Get-NetTCPConnection -LocalPort 5001 -State Listen`); `%LOCALAPPDATA%\BlarAI\launcher.log`
  shows "Minimal prompt-flow preflight passed"; the "BlarAI" WinUI window exists.
- Not up? Read `%LOCALAPPDATA%\BlarAI\crash.log` (a launcher.log showing only "Cleanup: …"
  with no error ⇒ the reason is in crash.log). The WinUI window is a foreground grab — you
  ARE authorized to raise it without warning/asking (supersedes warn-before-screen-taking
  for autonomous operation).

## STOP

Kill the launcher tree — the orphan-guard Job Object kills the WinUI + backend children; the
boot reconciler `shared/fleet/swap_state.py` converges any stranded swap on next start:

```powershell
Get-CimInstance Win32_Process -Filter "Name='pythonw.exe'" | Where-Object { $_.CommandLine -match '-m launcher' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
```

Usually TWO matches (venv shim + real launcher) — kill both. `sessions.db` is born-encrypted
+ flushed ⇒ no data loss.

## CODER / DISPATCH (30B)

A dispatch manages its OWN swap — steps the 14B aside, loads the 30B coder, runs the
plan-graph, restores the 14B + reports. Trigger via /dispatch or New-Project once BlarAI is
up. Stop a doomed run yourself (never ask): reap the `run-fleet` + BOTH `swap_ops` drivers,
then relaunch BlarAI (the reconciler cleans the stranded swap):

```powershell
Get-CimInstance Win32_Process -Filter "Name='pythonw.exe'" | Where-Object { $_.CommandLine -match 'swap_ops|run.fleet' }
```

## BATTERY TASK (nightly ~23:00)

Fires on its own — no action needed. You may `Get-`/`Start-`/`Stop-ScheduledTask` it (name
via `Get-ScheduledTask | Where-Object { $_.TaskName -match 'blar|battery' }`). Overnight GPU
work MUST run via the elevated scheduled task (a hand-launched console strands on UAC).

## PID liveness

Use `tasklist` / `Get-Process` — NEVER git-bash `kill -0` (false negatives on native
Windows PIDs).
