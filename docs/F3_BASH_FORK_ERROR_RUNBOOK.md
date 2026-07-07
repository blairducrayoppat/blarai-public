# F-3 Runbook — Claude Code Bash Tool Fork Errors on Windows

**Tracking ID**: F-3 in the Configuration Agent follow-up ledger (see `docs/CLAUDE_DESKTOP_CONFIGURATION_AGENT_INITIATION_v3.0.xml` §7).
**Scope**: Windows-only. Originally characterized as Claude-bundled bash unable to fork child processes; the 2026-04-19 incident escalated scope to system-wide MSYS fork failure — every MSYS bash on the machine exhibits the same signature (see §12 for forensics). F-3 covers both variants.
**Last incident**: 2026-04-19 → continuing 2026-04-20.
**Last resolution attempted**: **R5 (system-wide ASLR mitigation disable)** 2026-04-20 — root cause confirmed as Windows Mandatory ASLR (`ForceRelocateImages`) combined with `BottomUp` ASLR randomizing MSYS DLL load addresses across parent/child processes, defeating Cygwin's emulated `fork()`. Both mitigations now disabled system-wide; `BottomUp` disable requires reboot to take effect for new process trees. Stability progressed: pre-fix 0% → ForceRelocateImages OFF + reboot 90% → BottomUp OFF (no reboot) 73% during partial rebase storm. F-3 status: **PENDING REBOOT** for full verification.

---

## 1. Symptom signature

When you try to run **any** Bash tool call in a Claude Code session (including `pwd`), you get output like this, with exit code 254:

```
  0 [main] bash NNN dofork: child -1 - forked process MMMM died unexpectedly, retry 0, exit code 0xC0000142, errno 11
/etc/profile: fork: retry: Resource temporarily unavailable
1189139 [main] bash NNN dofork: child -1 - forked process MMMM died unexpectedly, retry 0, exit code 0xC0000142, errno 11
/etc/profile: fork: retry: Resource temporarily unavailable
... (repeated ~5 times) ...
/etc/profile: fork: Resource temporarily unavailable
```

**Critical tell**: the command never actually runs. The parent bash process starts (its PID appears in the error), but the child dies during DLL initialization. Anything that depends on Bash — including git operations routed through the Bash tool — is blocked.

**Out of scope for this runbook**: if Bash runs but commands inside it fail (permission denials, path errors, syntax) — that is a different class of issue.

---

## 2. Root cause

The bash Claude Code uses is a Windows port of Unix bash (MSYS2/Cygwin lineage). MSYS2 emulates Unix `fork()` on Windows by allocating a shared-memory heap at a **fixed virtual address** in both the parent and child processes. If any other DLL — Windows Defender hook, a different MSYS version, a system library — claims part of that address range in the child's address space, the child cannot initialize its heap and dies with Windows status code `0xC0000142` (`STATUS_DLL_INIT_FAILED`). The `errno 11 / EAGAIN / "Resource temporarily unavailable"` message is a misleading POSIX-layer translation — **not** actual resource exhaustion.

**Common triggers**:
- Windows updates reshuffling DLL load addresses.
- Defender / EDR signature updates changing hook injection patterns.
- Multiple MSYS installs on the system with drifted DLL base addresses.
- A Claude Desktop MSIX auto-update that lands in a half-applied state.

---

## 3. Environment context captured 2026-04-19

Preserved here so future troubleshooting does not have to re-enumerate.

### Claude Desktop install

- **Distribution**: sideloaded MSIX package from **Anthropic direct download** (https://claude.ai/download). **Not in the Microsoft Store.**
- **Package identity observed**: `Claude_1.3109.0.0_x64__pzs8sxrjxfjjc`
- **Install location**: `C:\Program Files\WindowsApps\Claude_1.3109.0.0_x64__pzs8sxrjxfjjc\`
- **Transient sub-tool extraction**: `C:\Users\mrbla\AppData\Roaming\Claude\claude-code\<version>\` (Claude Desktop unpacks Claude Code subprocesses here on demand and cleans them up between invocations; the sub-folder may vanish even while Claude Desktop is running normally)
- **Sub-tool version observed during incident**: `2.1.111`

### User data — preserved across reinstall

- `C:\Users\mrbla\.claude\` — projects, memory, skills, sessions, credentials
- `C:\Users\mrbla\AppData\Roaming\Claude\claude_desktop_config.json` — MCP config (symlinked from `.claude\`)

### MSYS inventory on the machine

| Path | Size | Source | Fork-healthy? |
|---|---|---|---|
| `C:\Program Files\Git\usr\bin\msys-2.0.dll` | 3,362,399 B | Git for Windows | **YES** (verified with parent→child fork test) |
| `C:\Program Files\JetBrains\PyCharm 2025.3.2\plugins\cwm-plugin\msys-ssh-agent\msys-2.0.dll` | 19,565,704 B | PyCharm bundled | Unused by Claude |
| `C:\Users\mrbla\AppData\Local\GitHubDesktop\app-3.5.3\resources\app\git\usr\bin\msys-2.0.dll` | 19,880,208 B | GitHub Desktop bundled | Unused by Claude |
| `C:\Users\mrbla\AppData\Local\Programs\AI Playground\resources\portable-git\usr\bin\msys-2.0.dll` | 3,360,863 B | AI Playground bundled | Unused by Claude |
| *Inside the Claude MSIX package* | *not directly inspectable — MSIX read-only* | Claude Desktop bundled | **NO** — this is the one failing |

### System `bash.exe` on PATH

`C:\Windows\system32\bash.exe` — this is **WSL bash**, not MSYS. Irrelevant to this issue but shows up in diagnostics.

---

## 4. Fast triage flow

```
Symptom confirmed?
    │
    ▼
[R1: Full restart — 2 min]
    │
    ├─ Fixed → done
    │
    ▼
[R2: Clean MSIX reinstall — 10 min]
    │
    ├─ Fixed → done  ← this is the resolution that works
    │
    ▼
[R3: rebaseall fallback — 20 min]
    │
    └─ Only needed if R2 did not fix it
       AND host Git Bash fork test also now fails
       (i.e., system-wide MSYS damage)
```

---

## 5. Diagnostic commands (confirm + capture forensic state)

Run in plain PowerShell, **outside** Claude Code. Paste the output into a new incident entry at the bottom of this doc.

```powershell
# === D1. Running Claude processes ===
Get-Process claude -ErrorAction SilentlyContinue |
    Select-Object Name, Id, Path |
    Format-Table -AutoSize -Wrap

# === D2. MSYS DLL inventory ===
$roots = @("C:\Program Files","C:\Program Files (x86)","$env:LOCALAPPDATA","$env:APPDATA") |
    Where-Object { Test-Path $_ }
$roots | ForEach-Object {
    Get-ChildItem -Path $_ -Recurse -Filter "msys-2.0.dll" -ErrorAction SilentlyContinue |
        Select-Object FullName, @{N='Size';E={"{0:N0}" -f $_.Length}}, LastWriteTime
}

# === D3. Host bash fork test (rules out system-wide MSYS damage) ===
$bashExe = (Get-Command bash -ErrorAction SilentlyContinue).Source
if ($bashExe) {
    Write-Host "Using: $bashExe"
    & $bashExe -c "echo parent-ok; bash -c 'echo child-ok'"
    Write-Host "Exit code: $LASTEXITCODE"
}
# Expected output: parent-ok / child-ok / Exit code: 0
# If this FAILS, host MSYS is also broken — go to Procedure R3.
# If it PASSES but Claude Code's Bash still fails — the fault is inside the MSIX package. Go to R2.

# === D4. MSIX package identity ===
Get-AppxPackage -Name "*Claude*" | Select Name, Version, InstallLocation
```

---

## 6. Procedure R1 — Full restart

1. Close Claude Desktop (all windows).
2. Right-click any tray icons → Quit.
3. Task Manager → Details → kill every `claude.exe` process.
4. Wait 30 seconds.
5. **Reboot the machine.** More reliable than manual process hunting — MSIX packages retain locks that only a full reboot clears.
6. After login, launch Claude Desktop → open the project.
7. In a Claude Code session, ask it to run `pwd` via Bash. Clean output → done.

**Cost**: 2 minutes. **Success rate this incident**: 0 (did not fix). Useful for transient states; worth trying first regardless.

---

## 7. Procedure R2 — Clean MSIX reinstall (authoritative fix)

### R2.1 — Back up config

```powershell
$backup = "$env:USERPROFILE\claude-backup-$(Get-Date -Format yyyyMMdd-HHmmss)"
New-Item -ItemType Directory -Path $backup | Out-Null
Copy-Item "$env:APPDATA\Claude\claude_desktop_config.json" $backup -ErrorAction SilentlyContinue
Copy-Item "$env:USERPROFILE\.claude" "$backup\dot-claude" -Recurse -ErrorAction SilentlyContinue
Write-Host "Backup at: $backup"
explorer $backup
```

Verify Explorer opens the backup folder with `claude_desktop_config.json` + a `dot-claude\` folder inside. Do not proceed until confirmed.

### R2.2 — Download the installer

- Primary: https://claude.ai/download
- Alternate: https://www.anthropic.com/download

**Do not search Microsoft Store.** Claude Desktop is not listed there.

### R2.3 — Uninstall the broken MSIX

1. Settings → Apps → Installed Apps → find "Claude" → `...` → Uninstall.
2. If Settings-based uninstall fails, use elevated PowerShell:
   ```powershell
   Get-AppxPackage -Name "*Claude*" | Remove-AppxPackage
   ```
3. **Reboot.** Do not skip.

### R2.4 — Install fresh

1. Run the installer downloaded in R2.2.
2. Sign in when prompted.
3. Open your project folder in Claude Code.

### R2.5 — Verify

In a new Claude Code session, run `pwd && git status --short` via Bash. Clean output = F-3 resolved.

If MCP servers aren't visible, check `%APPDATA%\Claude\claude_desktop_config.json` exists (should be preserved — but if missing, restore from `$backup\claude_desktop_config.json`). Restart Claude Desktop after any config restore.

---

## 8. Procedure R3 — host `rebaseall` across safe non-Claude MSYS installs

Use after R2 has executed and not resolved the symptom. R2's failure means the collision is not inside the Claude-bundled package; the next hypothesis is a host-level DLL whose preferred load address overlaps Claude-bundled bash's fork-heap range. `rebaseall` rewrites the preferred-load-address field across a given MSYS installation's DLL set, clearing that collision.

The D3 host-fork test **does not gate R3**. Host Git Bash's own fork can pass (D3 green) while Claude-bundled bash's fork still fails — exactly this incident's shape. Do not skip R3 based on D3 alone.

### 8.1 Scope — which MSYS installs to rebase, and why

Only rebase installations that are **standard MSYS layouts AND low blast-radius if anything goes wrong**. Refer to the §3 DLL inventory.

**In scope** (rebase these):

1. **Git for Windows** at `C:\Program Files\Git\usr\bin\`. Standard MSYS (\~3.36 MB). Most likely collision source — exercised frequently and installed at the MSYS-default layout. Reversible via the Git-for-Windows installer.
2. **AI Playground portable-git** at `C:\Users\mrbla\AppData\Local\Programs\AI Playground\resources\portable-git\usr\bin\`. Near-identical MSYS build (\~3.36 MB, same upstream family as Git for Windows per matching byte sizes). Not on BlarAI's critical path. Reversible via AI Playground reinstall.

**Out of scope** (do NOT rebase these):

3. **PyCharm bundled** at `C:\Program Files\JetBrains\PyCharm 2025.3.2\plugins\cwm-plugin\msys-ssh-agent\`. Non-standard MSYS (\~19.57 MB — significantly larger than stock, indicating a patched/embedded build). Lives inside JetBrains's Code With Me plugin's ssh-agent subsystem. `rebaseall`'s DLL database may not match this non-standard layout; a failed rebase could break PyCharm's Code With Me SSH connectivity and require a targeted plugin reinstall to recover.
4. **GitHub Desktop bundled** at `C:\Users\mrbla\AppData\Local\GitHubDesktop\app-3.5.3\resources\app\git\usr\bin\`. Non-standard MSYS (\~19.88 MB, Electron-app-embedded). GitHub Desktop auto-updates frequently; a `rebaseall`-modified msys-2.0.dll could fail the next update's DLL integrity check and leave GitHub Desktop unable to launch.

**Distinguishing criterion**: **\~3.36 MB** msys-2.0.dll = standard MSYS layout, safe for `rebaseall`. **\~19 MB** msys-2.0.dll = patched/embedded build bundled into a host app, safer to recover via the app's own reinstall path if it's ever implicated. If a future incident log entry needs PyCharm or GitHub Desktop rebased, use each app's native reinstall first; `rebaseall` on their DLLs is a last resort.

### 8.2 Procedure

1. Close **all** Claude Desktop windows, Claude Code sessions (including the one running this runbook), Git Bash windows, MSYS windows, and AI Playground if it's running. Modern `rebase.exe` writes new preferred addresses to disk (consumed on the DLL's next load) rather than modifying DLLs in memory, so a currently-running process no longer hard-blocks the rebase — but closing them is still best practice to avoid racing a mid-load DLL and to ensure the fresh addresses take effect on the subsequent launch.
2. Open plain `cmd.exe` (NOT PowerShell, NOT bash).
3. **Rebase Git for Windows first** (most likely collision source):
   ```cmd
   cd /d "C:\Program Files\Git\usr\bin"
   bash.exe /usr/bin/rebaseall -v
   ```
   Historical note: older MSYS2/Cygwin references used `ash.exe` here because `ash` is statically linked and couldn't self-lock `msys-2.0.dll` during rebase. Modern Git for Windows (\~2022+) omits `ash.exe` entirely; `bash.exe` runs the same `rebaseall` script fine because modern `rebase.exe` writes to disk rather than locking the in-memory DLL. Using `bash.exe` is the canonical invocation on current installs.

   \~30 seconds. Each DLL's new base address prints as `/path/dll: new base = 0xNNNNNNNN, new size = 0xNN`. No errors = success. Capture any errors to §12.
4. **Then rebase AI Playground's portable-git**:
   ```cmd
   cd /d "C:\Users\mrbla\AppData\Local\Programs\AI Playground\resources\portable-git\usr\bin"
   bash.exe /usr/bin/rebaseall -v
   ```
   If `bash.exe` is missing from AI Playground's `usr/bin/` (some portable-git builds strip down the shell set), fall back to Git for Windows's `bash.exe` pointed at AI Playground's rebaseall:
   ```cmd
   "C:\Program Files\Git\usr\bin\bash.exe" "C:\Users\mrbla\AppData\Local\Programs\AI Playground\resources\portable-git\usr\bin\rebaseall" -v
   ```
   If AI Playground's portable-git doesn't include `rebaseall` at all, or lacks an `/etc/rebase.db.*` database for it to read, skip this step and record the outcome in §12. A stripped-down portable-git can't be rebased; that isn't a failure of R3, it just rules out AI Playground's MSYS as the collider.
5. Re-run diagnostic D3 in PowerShell. Expected: `parent-ok / child-ok / Exit code: 0`.
6. Launch a fresh Claude Code session and run `echo test` via the Bash tool. Clean output = R3 resolved F-3.

#### 8.2.1 If `bash.exe` also errors with "not recognized"

Unusual — Git Bash wouldn't function without it — but worth a preflight if the rebase invocations fail. Run:

```cmd
dir "C:\Program Files\Git\usr\bin\bash.exe" "C:\Program Files\Git\usr\bin\rebaseall" "C:\Program Files\Git\usr\bin\rebase.exe" "C:\Program Files\Git\usr\bin\dash.exe"
```

Outcomes:
- `bash.exe` present but `rebaseall` missing — Git for Windows is a MinGit build (stripped for minimal git functionality) without the rebase utilities. Install full Git for Windows or a standalone MSYS2 to get `rebaseall`.
- `bash.exe` missing — Git for Windows install is corrupt; reinstall Git for Windows before retrying R3.
- Everything present but `bash.exe /usr/bin/rebaseall` still errors — capture the exact error to §12; this becomes a new forensic data point.

### 8.3 If R3 rebases successfully but does not resolve F-3

Applies when `rebaseall` forked successfully, wrote new preferred addresses, and completed without errors, but a fresh Claude Code session's Bash tool still fails. If `rebaseall` itself could not fork — as observed in the 2026-04-19 incident (§12 item 4) — skip to **§8.4** instead; the escalation tree below presupposes a functioning host MSYS.

Escalation path, in order:

1. **Windows Defender folder exclusion** for `C:\Program Files\WindowsApps\Claude_*` (§11.1). Rules out AV-hook injection.
2. **DLL-load forensics** (Process Monitor / WinDbg) to identify the actual colliding DLL at fork time.
3. **PyCharm / GitHub Desktop rebase** — only if forensics specifically identifies one as the collider, and even then prefer the app's native reinstall path over `rebaseall` on its embedded MSYS.

### 8.4 Procedure R4 — System Restore (when host MSYS fork is broken too)

Use when `rebaseall` itself cannot fork on the host (both Git for Windows and AI Playground bash exhibit the same `dofork child -1 / 0xC0000142 / errno 11` signature, as in the 2026-04-19 incident). That means the failure is no longer a Claude-bundled-bash-only collision — it is a **system-wide condition** affecting every MSYS process on the machine, most plausibly caused by a Windows Update or security-feature toggle applied during a recent reboot.

R4 rolls Windows system state (registry, drivers, OS files) back to a snapshot predating the system change. Personal files and `C:\Users\mrbla\.claude\` user data are preserved.

#### R4 procedure

1. Close all apps, especially Claude Desktop and Claude Code.
2. Start menu → type **"Create a restore point"** → Enter. Opens System Properties → System Protection tab.
3. Click **"System Restore..."** → Next. Check **"Show more restore points"** (bottom-left) to reveal auto-generated ones.
4. Select the most recent restore point **dated before the last known-good D3 pass**. For the 2026-04-19 incident, that means before today's R2 reboot (ideally a restore point from 2026-04-18 or earlier).
5. Next → Finish → Yes. Windows reboots and restores (\~5–15 minutes).
6. After reboot, verify host MSYS is healthy via `cmd.exe`:
   ```cmd
   bash.exe -c "echo parent-ok; bash -c 'echo child-ok'"
   ```
   Expected: `parent-ok` followed by `child-ok`.
7. Launch fresh Claude Code session, attach the 5 files per §10, paste the handoff message (with R3 outcome field marked `N/A — R4 used instead`). The fresh session runs `echo test` via Bash — clean output = F-3 resolved.

#### 8.4.1 If no pre-regression restore point exists

Diagnostic fallback, in order. Stop at the first check that identifies the root cause.

1. **Windows Update history**. Settings → Windows Update → Update history. Scan for updates installed today. If any present, "Uninstall updates" → remove the most recent → reboot → retest the cmd.exe D3 above.
2. **Exploit Protection**. Windows Security → App & browser control → Exploit protection settings → System settings tab → check **"Force randomization for images (Mandatory ASLR)"**. If "On" or "Use default (On)," change to **"Off by default"**. Reboot; retest.
3. **Core Isolation**. Windows Security → Device security → Core isolation details → toggle **Memory integrity** off. Reboot when prompted; retest.
4. **AppInit_DLLs injection** (PowerShell):
   ```powershell
   Get-ItemProperty "HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Windows" | Select LoadAppInit_DLLs, AppInit_DLLs
   Get-ItemProperty "HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows NT\CurrentVersion\Windows" | Select LoadAppInit_DLLs, AppInit_DLLs
   ```
   If `LoadAppInit_DLLs = 1` and `AppInit_DLLs` contains a DLL path, that DLL is being injected into every process (including MSYS children) and is a prime collision suspect. Investigate the DLL's origin before removing — may be a legitimate AV/EDR component, in which case coordinate with its vendor.
5. **DLL-load forensics**. Last resort: Process Monitor (Sysinternals) or WinDbg to trace DLL loads in a failing bash child and identify the colliding module by preferred-address vs. fork-heap-address comparison.

---

## 9. Anti-patterns — do NOT do these

1. **Do not attempt to `rebaseall` inside `C:\Program Files\WindowsApps\`.** MSIX packages are code-signed and read-only. Any modification breaks the signature, and Windows will refuse to launch the app. Only `rebaseall` host-level MSYS (Git for Windows).

2. **Do not switch to `npm install -g @anthropic-ai/claude-code` as a workaround for BlarAI.** The npm CLI package provides Claude Code only — **no Claude Chat, no Claude Cowork.** BlarAI's Domain 5 (Cowork Operating Protocol, Vikunja file-based Bridge, EA-in-Cowork instructions) and Domain 8 (autonomous-fleet vision with Cowork EAs) assume the full MSIX-delivered three-mode ecosystem. Switching would collapse prior domain work. The npm distribution is appropriate for developers who only want the CLI; it is the wrong tool for this project.

3. **Do not search Microsoft Store for Claude Desktop.** It is not listed there. Anthropic ships Claude Desktop exclusively via direct MSIX download from their own domain. The `WindowsApps\` install location is shared between Store apps and sideloaded MSIX; the package identity alone does not tell you which.

4. **Do not reinstall Git for Windows as a fix for this issue.** Git for Windows has its **own** bundled MSYS at `C:\Program Files\Git\usr\bin\msys-2.0.dll`, completely separate from Claude's bundled MSYS. Reinstalling Git heals host Git Bash but does nothing to Claude's bundled bash. This is exactly the trap that made F-3 appear "resolved" when it wasn't.

---

## 10. Continuity plan across a reinstall, rebase, or restart

Any recovery procedure that closes Claude Code (full restart, MSIX reinstall, host `rebaseall`, Defender-exclusion + relaunch) **loses the active session's conversational state**. On-disk data is preserved.

### Before closing the session

- Land any in-progress edits to disk via Edit/Write (no Bash required).
- Update the §12 incident log with: which procedure is about to be attempted, what the session was mid-way through, and any derived state not yet persisted to a file.
- If relevant, update the active role-initiation prompt (e.g. `docs/CLAUDE_DESKTOP_CONFIGURATION_AGENT_INITIATION_v3.0.xml` §7) so the successor session reads a current F-3 state, not a stale one.

### After the procedure completes — fresh session hand-off

Start a new Claude Code session and paste this hand-off prompt, filling the `[...]` placeholders:

> Attach `docs/CLAUDE_DESKTOP_CONFIGURATION_AGENT_INITIATION_v3.0.xml`, `docs/F3_BASH_FORK_ERROR_RUNBOOK.md`, and `docs/CLAUDE_MCP_ECOSYSTEM_MATRIX.md`.
>
> F-3 recovery procedure `[R1 / R2 / R2b / R3 / Defender-excl / other]` was executed with outcome `[PASSED / FAILED]`. Read §12 of the runbook for the most recent incident log entry, re-execute the v3.0 §9 comprehension gate against current state (not the predecessor state baked into the v3.0 prompt), and stop at "GATE SUBMITTED. Awaiting Lead Architect review."
>
> If PASSED: the first concrete action after approval is `pwd` via Bash to confirm the fix, then `chore: land Domain 6 matrix + F-3 runbook` committing both files together, then update v3.0 §7 F-3 entry to RESOLVED with a cross-reference to the runbook incident log, then surface the matrix for Tier A+B approval. Do not re-scope Domain 6.
>
> If FAILED: do not attempt Bash. Propose the next escalation step (from §12 outcome tree) with rationale, await Lead Architect approval, and execute via Edit/Write + PowerShell commit-handshake pattern per v3.0 §12.

---

## 11. Prevention / hardening

1. **Windows Defender folder exclusion for the Claude install directory.**
   - Windows Security → Virus & threat protection → Manage settings → Add or remove exclusions → add folder exclusion for `C:\Program Files\WindowsApps\Claude_*`.
   - Trade-off: Defender no longer scans inside the Claude package. Acceptable because the binaries are Anthropic-signed. Benefit: removes one common trigger (AV hook injection changing DLL bases on signature updates).

2. **Version pinning.** When a Claude Desktop version resolves F-3, note the version number in this doc's incident log. If a later auto-update re-triggers the symptom, you have a known-good fallback version to request from Anthropic support.

3. **Limit MSYS install proliferation.** Each additional bundled MSYS on the system is another potential DLL-base-collision source. Avoid installing bundled-git tools you do not actually use.

---

## 12. Incident log

### 2026-04-19 — Claude Desktop 1.3109.0.0 → reinstall

**Trigger context**: Domain 6 of the Configuration Agent audit (MCP server ecosystem matrix). Bash tool was working at session start, then began failing partway through the session. No user-initiated configuration changes preceded the onset.

**Session checkpoint at incident onset**: matrix artifact `docs/CLAUDE_MCP_ECOSYSTEM_MATRIX.md` was written to disk successfully. The next step — committing the matrix via Bash — began failing with `dofork` errors.

**Diagnostic findings**:
- Host Git Bash fork test (D3): **PASSED** (parent-ok / child-ok / exit 0). Host MSYS healthy.
- MSYS DLL inventory (D2): 4 non-Claude installs present; none implicated.
- Claude install (D4): MSIX `Claude_1.3109.0.0_x64__pzs8sxrjxfjjc`, sideloaded from Anthropic direct (not Store).
- Transient sub-folder `%APPDATA%\Claude\claude-code\2.1.111\` present in an early process-list diagnostic, then absent \~10 minutes later. Consistent with an auto-update that cleaned the old staging folder but did not fully activate the new version. Strongest single evidence pointing at MSIX-bundled-bash as the fault site.

**Hypotheses considered and ruled out**:
- *"Git for Windows reinstall will fix it"* — the Lead Architect had reinstalled Git for Windows prior to this session (3/23/2026), believing it resolved F-3. Not so: Git for Windows and Claude Desktop bundle separate MSYS DLLs. Host MSYS was healthy per D3, but Claude's bundled MSYS was broken.
- *"Microsoft Store update"* — Claude Desktop is not a Store app despite living in `WindowsApps\`. Search returns zero hits. Path invalid.
- *"npm Claude Code as fallback"* — scope-incompatible with BlarAI's Cowork-dependent domains. Ruled out.

**Resolution attempted**:
1. Procedure R1 (full cold reboot) — **did NOT fix**. Fork errors persisted unchanged after a complete power cycle.
2. Procedure R2 (clean MSIX reinstall) — **did NOT fix**. MSIX uninstalled per R2.3, system rebooted, Claude Desktop reinstalled from Anthropic direct download per R2.4. A fresh Claude Code session launched post-reinstall exhibits the identical `dofork child -1 / 0xC0000142 / errno 11` signature on a trivial `echo test` invocation (verified by the successor Configuration Agent session's Bash tool test, immediately before this amendment). The "MSIX-bundled-bash is itself malformed" hypothesis is therefore refuted — the fault survives a full package reinstall. Failure mode is driven by something at host level (DLL address collision, Defender hook injection, or an unrelated bundled MSYS install claiming overlapping load addresses) that the reinstalled Claude-bundled bash still meets on fork.
3. Procedure R3 (host `rebaseall` across Git for Windows + AI Playground per §8.1 scope) — first command attempt 2026-04-19 used `ash.exe` per legacy runbook guidance, which is not present in this machine's Git for Windows install (`'ash.exe' is not recognized as an internal or external command`). Runbook §8.2 corrected mid-session to specify `bash.exe` as the canonical runner — modern Git for Windows (\~2022+) omits `ash.exe` entirely because modern `rebase.exe` writes new preferred addresses to disk rather than locking DLLs in memory, so the static-shell requirement no longer applies. §8.2.1 added to cover the edge case where `bash.exe` is also missing (MinGit or corrupt install).
4. R3 retry 2026-04-19 with `bash.exe /usr/bin/rebaseall -v` — **BOTH Git for Windows AND AI Playground exhibited the IDENTICAL `dofork child -1 / 0xC0000142 / errno 11` signature as Claude-bundled bash.** `rebaseall` itself could not fork, so no DLL was actually rebased. This is a **scope-change finding**: host MSYS fork has gone from D3-PASSED earlier the same day to D3-FAILED system-wide. **F-3 is no longer a Claude-bundled-bash-only failure; every MSYS bash on the machine now fails to fork.** Between the D3 pass and this attempt, the only system-state change was R2's reboot cycle — Windows likely applied an Update or toggled a security mitigation during reboot. All subsequent runbook procedures (R3 rebase, Defender exclusion at §11.1, PyCharm/GitHub Desktop rebase) were designed for Claude-bundled-only scope and no longer apply as-written.
5. Procedure R4 (System Restore to a pre-R2-reboot snapshot) — **PENDING Lead Architect execution.** See §8.4 below.

**Post-resolution action items** (for the session that comes back alive after R2):
1. Commit `docs/CLAUDE_MCP_ECOSYSTEM_MATRIX.md` and `docs/F3_BASH_FORK_ERROR_RUNBOOK.md` together.
2. Update `docs/CLAUDE_DESKTOP_CONFIGURATION_AGENT_INITIATION_v3.0.xml` §7: mark F-3 RESOLVED via MSIX reinstall, cross-reference this runbook.
3. Resume Domain 6: Lead Architect reviews matrix, approves/amends Tier A+B slate, then per-candidate install proposals begin with `git` MCP.

**Lessons captured**:
- Reinstalling Git for Windows does **not** fix Claude Code's Bash tool. Different MSYS DLL instances.
- MSIX auto-update can leave a package in a half-applied state where sub-components vanish from disk even while the parent app keeps running. Reinstall CAN clear that specific failure mode but is **not universally sufficient** — the 2026-04-19 R2 execution did not resolve this incident's symptom.
- Microsoft Store is not a path for Claude Desktop. Anthropic-direct download only.
- A full cold reboot does not heal an MSIX package with a permanent bundled-DLL heap-base collision. R1 worth trying but do not expect it to fix persistent F-3.
- **Clean MSIX reinstall is not the authoritative fix.** 2026-04-19's R2 execution (uninstall + reboot + reinstall from Anthropic direct + fresh session) did not clear the fork failure. The authoritative fix, if any, lies in the host-level MSYS DLL-base landscape (R3), not in the Claude package itself.
- **The collision hypothesis must now target host-level DLLs, not the bundled package.** If the bundled DLL were the sole cause, a fresh extraction from the signed MSIX would differ behaviorally from the prior corrupt state. Since it does not, the collision is driven by a host-level DLL (Defender hook, a system DLL, or one of the other MSYS installs listed in §3) that the newly-extracted bundled bash still meets on fork.

---

### 2026-04-20 — Root cause confirmed: Windows ASLR vs MSYS fork

**Trigger context**: Continuation of 2026-04-19. R4 (System Restore) was the documented next step but was not executed; instead, fallback diagnostics from §8.4.1 step 2 (system mitigation inspection) were performed and identified the actual root cause.

**Diagnostic findings**:
- `Get-ProcessMitigation -System` showed `ASLR.ForceRelocateImages: ON` (system-wide Mandatory ASLR) and `ASLR.BottomUp: ON`. This is the configuration that defeats Cygwin/MSYS emulated `fork()`: `fork()` requires `msys-2.0.dll` and other MSYS DLLs to load at the **identical virtual address** in the parent and the child process; ASLR (specifically `BottomUp`, amplified by `ForceRelocateImages` for non-DYNAMICBASE images) randomizes those addresses on every process creation, so the child's heap-base initialization fails with `STATUS_DLL_INIT_FAILED (0xC0000142)`.
- Suspect Windows Update KBs installed 2026-04-16 (4 days before incident onset): KB5082417, KB5083769, KB5088467. These are the most plausible vector for flipping `ForceRelocateImages` to ON on this machine.
- Empirical fork test with Mandatory ASLR ON: parent→bash 5/5 PASS, parent→external-binary (fork+exec) 0/10 PASS — exact pattern expected from per-process DLL re-randomization.

**Root cause** (confirmed):
> Windows Mandatory ASLR (`ForceRelocateImages`) plus `BottomUp` ASLR randomize MSYS DLL load addresses across parent/child process pairs. Cygwin's emulated `fork()` requires deterministic addresses. Result: every MSYS `fork()` that crosses a process boundary fails with `0xC0000142 / errno 11`.

This **supersedes** the §2 "single-DLL collision" hypothesis and the §8.1 "rebaseall fixes everything" assumption. `rebaseall` writes preferred load addresses into PE headers but cannot defeat `BottomUp` ASLR — Windows still re-randomizes regardless of the preferred base.

**Resolution applied (R5)**:
1. Stopped the Claude VS Code extension process (PID 10444 on this incident).
2. Elevated PowerShell: `Set-ProcessMitigation -System -Disable ForceRelocateImages` → verified `ForceRelocateImages: OFF`.
3. **Cold reboot.** Post-reboot bash fork stability climbed from 0/10 to 9/10 (one residual `child_copy: cygheap read copy failed`).
4. Attempted elevated `dash.exe /usr/bin/rebaseall -v` to consolidate. Run rebased \~150 DLLs successfully, then dash itself hit a fork failure mid-run; on retry hit `rebase: Too many DLLs for available address space: Cannot allocate memory` — the default rebase address window is exhausted by Git for Windows' DLL count. Partial rebase persisted to disk regardless.
5. Stability snapshot post-partial-rebase: 12/20 PASS (60%) — confirming `BottomUp` ASLR is still randomizing per-process bases.
6. Elevated PowerShell: `Set-ProcessMitigation -System -Disable BottomUp` → verified `BottomUp: OFF`. (Mitigation only takes effect for new process trees post-reboot.)
7. Stability snapshot pre-reboot, BottomUp OFF: 22/30 PASS (73%) — improvement from inherited mitigation policy in some new processes.
8. **Reboot pending** — required for `BottomUp` OFF to apply to all new process trees, including the Claude Desktop / Claude VS Code extension process trees that spawn the Bash tool.

**Security trade-off accepted by Lead Architect**:
- `ForceRelocateImages` OFF system-wide: removes the *forced* relocation of non-DYNAMICBASE-marked images. Modern apps that opt into ASLR at link time (effectively all of VS Code, Office, browsers, Claude) are unaffected. Reduces hardening for legacy/native binaries lacking the DYNAMICBASE flag — security cost is moderate, scoped, and reversible.
- `BottomUp` OFF system-wide: removes the per-process base randomization for bottom-up heap/stack/image allocations. This is a more meaningful reduction; it weakens ASLR for nearly all processes, even DYNAMICBASE-aware ones. `HighEntropy` remains ON. Security cost is non-trivial but reversible. Lead Architect approved 2026-04-20 on grounds that bash forking is a P1-blocker for BlarAI development and the same class of mitigation toggle had already been authorized for `ForceRelocateImages`.
- Reversal command (when a future Windows servicing update or hardening initiative restores correct MSYS behavior): `Set-ProcessMitigation -System -Enable ForceRelocateImages,BottomUp` (elevated) + reboot.

**Verification gates (post-reboot, pending Lead Architect run)**:
1. `(Get-ProcessMitigation -System).ASLR | Format-List` → expect `ForceRelocateImages: OFF`, `BottomUp: OFF`, `HighEntropy: ON`.
2. 30-trial fork loop:
   ```powershell
   $pass=0;$fail=0; 1..30 | ForEach-Object {
     $out = & "C:\Program Files\Git\usr\bin\bash.exe" -lc "echo ok && ls /usr/bin/cat.exe > /dev/null && echo done" 2>&1 | Out-String
     if ($out -match 'dofork: child -1|fork: Resource temporarily unavailable|child_copy: cygheap') { $fail++ } else { $pass++ }
   }; "PASS: $pass / FAIL: $fail"
   ```
   Acceptance: ≥ 29/30 PASS. If < 29, retry elevated `dash.exe /usr/bin/rebaseall -v` (now possible because BottomUp OFF makes dash's own forks reliable) to finish the partial rebase.
3. Fresh Claude Code session in VS Code: invoke a trivial `pwd` Bash tool call. Acceptance: returns the working directory with exit 0, no `dofork` errors in stderr.

**Lessons captured (additive to 2026-04-19 entry)**:
- The authoritative root cause for system-wide MSYS fork failure on a freshly-updated Windows 11 machine is **system-wide ASLR mitigations**, not bundled-DLL corruption. Always check `Get-ProcessMitigation -System` early when D3 is failing system-wide (§8.4.1 step 2 was correct; promote it to a primary check, not a fallback).
- `rebaseall` cannot defeat `BottomUp` ASLR. Rebasing is necessary but not sufficient when the OS is randomizing addresses anyway.
- Windows Update KBs from 2026-04-16 (KB5082417, KB5083769, KB5088467) are the suspected vector for flipping `ForceRelocateImages` ON on this machine. If a future incident recurs, check `wmic qfe list` for fresh KBs first.
- R4 (System Restore) was unnecessary in this incident — R5 (targeted ASLR mitigation disable) achieved the fix without rolling back the OS state. Add R5 as a documented procedure to §8 in a future doc-hygiene pass.
- Reboot is mandatory after disabling `BottomUp`. Do not declare success on no-reboot stability deltas.

---

### 2026-04-20 (post-R5, Domain 7 impl session) — Bash tool transient silent-exit + Git for Windows reinstall correlation

**Context**: R5 had already been applied earlier on 2026-04-20; F-3 was considered RESOLVED going into the Domain 7 Configuration Agent session. Mid-session, the Claude Code Bash tool began exiting code 1 silently — no output, no familiar `dofork` / `0xC0000142` fingerprint.

**Symptom profile** (different from canonical F-3):

| Aspect | Canonical F-3 (2026-04-19 / R5 2026-04-20) | This regression |
|---|---|---|
| Bash exit code | Non-zero with `dofork child -1`, `0xC0000142`, `errno 11`, or `fork: Resource temporarily unavailable` on stderr | Silent exit 1, zero stderr, zero stdout |
| Affected commands | Any Bash command that forked a child (most real commands) | Even simple `pwd`, `ls`, `echo` — any Bash invocation at all |
| Host MSYS fork health (outside Claude) | Also broken (D3 FAIL) | Not tested this session, but unknown |
| VS Code git integration | Was still working (different binary) | Also broken — Source Control panel showed `spawn C:\Program Files\Git\cmd\git.exe ENOENT` |

**Probable cause**: `C:\Program Files\Git\cmd\git.exe` was missing (the directory `C:\Program Files\Git\etc\` existed but was empty of binaries). Root-cause hypothesis: Git for Windows was uninstalled, corrupted, or partially removed at some point between R5 (earlier 2026-04-20) and the Configuration Agent session start (later same day). Claude Code's bundled Bash shares the host MSYS2 runtime chain; a missing Git for Windows cascades into Bash being unable to resolve its own invocation chain even though it's a different binary tree than `C:\Program Files\Git\usr\bin\bash.exe`.

**Observation** (contradicts but does not invalidate §8.3 guidance): after Lead Architect reinstalled Git for Windows 2.54.0 to the canonical `C:\Program Files\Git\` location, the Claude Code Bash tool **recovered in the same session** — `echo`, `pwd`, `uname -a`, and `git --version` all returned cleanly with exit 0. No session restart was required.

**Note on prior guidance**: §8.3 and the "Do-not" admonitions elsewhere in this runbook say reinstalling Git for Windows does NOT fix Claude's bundled Bash because Claude bundles its own MSYS. That remains true **for the canonical F-3 fork-error failure mode**. The 2026-04-20 silent-exit regression is a DIFFERENT failure mode where a missing host Git for Windows install appears to break Claude's Bash tool by some indirect dependency (possibly Claude's Bash shell resolution, PATH, or a shared DLL not bundled into Claude). Treat the two failure modes as distinct:

- **Canonical F-3 (dofork errors)**: host MSYS and bundled MSYS are both broken; R5 (ASLR disable) is the fix. Git for Windows reinstall does nothing.
- **Silent Bash exit 1 + VS Code `spawn ENOENT`**: Git for Windows binary is missing from `C:\Program Files\Git\`. Reinstall restores it.

**Forensic rule of thumb**: if Bash fails WITH stderr (any `dofork` / fork / cygheap message), F-3 class — follow existing runbook. If Bash fails SILENTLY with exit 1 and VS Code simultaneously reports `spawn C:\Program Files\Git\cmd\git.exe ENOENT`, first probe `Test-Path 'C:\Program Files\Git\cmd\git.exe'` — if absent, reinstall Git for Windows and retry.

**Fallback when Git for Windows is unreachable and the Agent must commit**: use [`docs/runbooks/COMMIT_HANDSHAKE_PATTERN.md`](runbooks/COMMIT_HANDSHAKE_PATTERN.md). Git hierarchy (canonical → GitHub Desktop bundled → WSL) is codified there. AI Playground's portable git is **explicitly excluded** per Lead Architect standing rule 2026-04-20.

**Session operational artifacts**: The Domain 7 recommendations implementation session (ledger Entry 45) used GitHub Desktop's bundled git (`C:\Users\mrbla\AppData\Local\GitHubDesktop\app-3.5.3\resources\app\git\cmd\git.exe`, version 2.47.3) for commits 1 and 2 while `C:\Program Files\Git\` was missing, then switched to the freshly-reinstalled canonical Git for Windows 2.54.0 for commits 3, 4, and 5 after reinstall. All commits landed with correct author identity (`Blair <mr.blair.do@gmail.com>`) — both git binaries read the same `~/.gitconfig`.

**Lessons captured (additive to R5 entry)**:
- F-3 is a family, not a single failure mode. Silent-exit Bash + `spawn ENOENT` in VS Code is a distinct "F-3-adjacent" class whose resolution is Git-for-Windows-reinstall, not ASLR-disable. Document both in the runbook.
- Git for Windows reinstall is NOT a general-purpose F-3 fix — but IS the right fix when the `spawn ENOENT` fingerprint is present.
- The Commit Handshake Pattern (new runbook 2026-04-20) is the right fallback when either failure class is active and the Agent can still write files + issue PowerShell commands.
- VS Code's Source Control error messages (`spawn ... ENOENT`) are a strong early-warning signal for this class. The Lead Architect noticing "Source Control panel has no repo" is equivalent to running the `Test-Path` probe.
