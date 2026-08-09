# RAM Headroom — Apply Log (LA-approved batch, 2026-07-15)

**Ticket:** #897 · **Approved by the LA in chat 2026-07-15** (items 1, 2, 3 of the assessment §5 menu; OneDrive explicitly untouched — not in the approved list)
**Applied from an elevated PowerShell session. Every original value is recorded below; every item has a one-line revert.**

**Before (immediately pre-apply):** In-Use 8.61 GB / Available 22.71 GB; Edge 149 background processes, 3,049 MB private.
**After (same session, pre-reboot):** In-Use 7.54 GB / Available 23.78 GB (**~1.1 GB physical returned immediately** from stopping the already-running Edge tree; the full effect — nothing relaunching at login — shows from the next sign-in onward).
**Post-reboot measurement:** pending (recorded here + PERFORMANCE_LOG when taken).

---

## Item 1 — Microsoft Edge login-time preload: OFF

**What was changed (two layers, belt and braces):**
1. Removed the per-user autolaunch entry.
   - Key: `HKCU\SOFTWARE\Microsoft\Windows\CurrentVersion\Run`
   - Name: `MicrosoftEdgeAutoLaunch_8B11C74B4C921AA684F55F7ED6251857`
   - **Original value (for revert):** `"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe" --no-startup-window --win-session-start`
2. Set machine policy so Edge cannot re-add it on self-update (they do re-add):
   - `HKLM\SOFTWARE\Policies\Microsoft\Edge` → `StartupBoostEnabled=0` (DWORD), `BackgroundModeEnabled=0` (DWORD). Keys did not exist before (the whole `Policies\Microsoft\Edge` key was absent — delete it to fully revert).
3. Stopped the 149 already-running background processes (no visible Edge window existed; verified before killing).

**Expected effect:** ~0.4–0.6 GB standing physical + ~3 GB commit no longer taken at every login; 149 fewer processes.
**Watchlist (possible side effects):**
- Edge's *first* launch each session is slower by a second or two (cold start instead of preloaded).
- Edge settings pages for these two toggles will show a "managed by your organization" banner — cosmetic, caused by the policy keys, disappears on revert.
- Extensions that do background work while Edge is closed (none known in use) would stop doing so.

**Revert:**
```powershell
Set-ItemProperty 'HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\Run' -Name 'MicrosoftEdgeAutoLaunch_8B11C74B4C921AA684F55F7ED6251857' -Value '"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe" --no-startup-window --win-session-start'
Remove-Item 'HKLM:\SOFTWARE\Policies\Microsoft\Edge' -Recurse   # elevated
```

## Item 2 — Microsoft Copilot autostart: OFF

**What was changed:** removed the per-user autolaunch entry.
- Key: `HKCU\SOFTWARE\Microsoft\Windows\CurrentVersion\Run`
- Name: `MicrosoftCopilotAutoLaunch_0D3E80647E6BF668CAF38D418B868A79`
- **Original value (for revert):** `"C:\Program Files (x86)\Microsoft\Copilot\Application\mscopilot.exe" --no-startup-window --win-session-start`

**Expected effect:** ~0.2–0.5 GB not taken at login. Copilot itself is NOT uninstalled — it opens normally on demand (taskbar/Start), it just no longer preloads.
**Watchlist:** Copilot's first open is slower; a Windows feature update may silently re-add the Run entry (check after major updates — re-apply if it reappears).
**Revert:**
```powershell
Set-ItemProperty 'HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\Run' -Name 'MicrosoftCopilotAutoLaunch_0D3E80647E6BF668CAF38D418B868A79' -Value '"C:\Program Files (x86)\Microsoft\Copilot\Application\mscopilot.exe" --no-startup-window --win-session-start'
```

## Item 3 — Xbox Game Bar background capture (Game DVR): OFF

**What was changed:**
- `HKCU\SOFTWARE\Microsoft\Windows\CurrentVersion\GameDVR` → `AppCaptureEnabled: 1 → 0` (**original was 1**)
- `HKCU\System\GameConfigStore` → `GameDVR_Enabled: (not set) → 0`

**Expected effect:** removes the background capture/recording service load (a few hundred MB when active, plus GPU capture overhead on the same integrated GPU the models use). The Game Bar app itself remains installed.
**Watchlist:** Win+G instant-replay/"record last 30 seconds" no longer works (deliberate). If screen-recording of a game is ever wanted, revert or use OBS-class tooling.
**Revert:**
```powershell
Set-ItemProperty 'HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\GameDVR' -Name 'AppCaptureEnabled' -Value 1
Remove-ItemProperty 'HKCU:\System\GameConfigStore' -Name 'GameDVR_Enabled'
```

## Item 4 — Intel Endurance Gaming autostart: OFF

**LA condition checked first:** Endurance Gaming is a battery-life frame-rate limiter that engages only in *game* rendering workloads. It has no role in the compute path BlarAI uses (OpenVINO → Level Zero/OpenCL on the Arc 140V). The graphics **driver is untouched** — only the helper's autostart entry was removed; the program stays on disk.
- Key: `HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Run`
- Name: `Intel Endurance Gaming`
- **Original value (for revert):** `C:\Program Files\Intel\EnduranceGaming\EnduranceGamingProcess.exe`

**Expected effect:** ~142 MB standing returned from next login.
**Watchlist:** none for BlarAI. If battery-throttled gaming is ever wanted, revert. An Intel graphics driver update may re-add the entry — harmless either way.
**Revert (elevated):**
```powershell
Set-ItemProperty 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Run' -Name 'Intel Endurance Gaming' -Value 'C:\Program Files\Intel\EnduranceGaming\EnduranceGamingProcess.exe'
```

## Item 5 — Widgets: verified already off (no change made)

The taskbar Widgets toggle was already disabled (`TaskbarDa=0`) — consistent with the LA's recollection that some of this "should be off already." One small `WidgetService` process still runs (Windows plumbing, tens of MB); the heavier web-content layer only spawns when the Widgets board is opened. **Deliberately NOT uninstalling** the underlying "Windows Web Experience Pack" — larger unexpected-consequence surface for tens of MB; documented here as the known deeper option if ever wanted.

## Item 6 — Pagefile: fixed 24 GB (was auto-managed)

**What was changed:** `AutomaticManagedPagefile: True → False`; `C:\pagefile.sys` set to Initial = Maximum = 24,576 MB (was auto, currently 19,456 MB allocated, observed peak 11,750 MB this boot).
**Why 24 GB:** ≥2× the observed peak, kills mid-model-load growth stalls, and costs only ~4.5 GB more disk than today's allocation against 103.7 GB free — sized deliberately small-side because storage is tight until the new drive arrives (no change needed after it arrives; 24 GB fixed remains correct).
**Takes effect: next reboot.**
**Watchlist:** none expected; commit limit becomes fixed at ~56 GB (32 GB RAM + 24 GB). If a future workload ever pushes committed memory near that, raise the maximum — do not disable.
**Revert (elevated):**
```powershell
Set-CimInstance (Get-CimInstance Win32_ComputerSystem) -Property @{AutomaticManagedPagefile=$true}   # + reboot
```

## Item 7 — Bitdefender scan exceptions — **DONE (entered by the LA in the Bitdefender app, 2026-07-15)**

Add these three folders as **Antivirus (on-access) exceptions** — they are the read-heavy paths scanned on every model load / Python start. BlarAI independently verifies signed model manifests at boot, which mitigates the unscanned-folder trade-off for the weights:

1. `C:\Users\mrbla\BlarAI\models`
2. `C:\Users\mrbla\AppData\Local\BlarAI\ov_cache`
3. `C:\Users\mrbla\BlarAI\.venv`

Click path (Bitdefender app): **Protection → Antivirus → Settings → Manage Exceptions → + Add an Exception** → paste one path → toggle **Antivirus** on for it → **Save** → repeat for each.
**Expected effect:** faster model loads and Python startup (latency, not RAM — stated honestly in the assessment).
**Watchlist:** these three folders are no longer virus-scanned on access. Do not add broader paths (not the whole repo, not the user profile).
**Revert:** same screen → remove the three entries.

---

## Not touched (explicitly)
- **OneDrive** — not in the LA's approved list; autostart entry left exactly as found.
- **KeePass preload, Logi Tune, Vikunja, Bitdefender modules, Security tray** — in daily use or required.
- **Virtualization-Based Security** — evaluated and rejected in the assessment (§5.3).

## Follow-through
- [x] Bitdefender exceptions entered by the LA (2026-07-15, same day as apply).
- [ ] Reboot at the LA's convenience (pagefile activation + clean login without the disabled autostarts).
- [ ] Post-reboot: after-measurement (In-Use at idle, Edge/Copilot process check, pagefile allocation = 24,576 MB) recorded here + as the study's after-picture entry in PERFORMANCE_LOG.md.
- [ ] Watch one Windows/Edge/Intel update cycle for silently re-added autostart entries (all three removal sites listed above).
