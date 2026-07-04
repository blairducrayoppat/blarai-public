# ADR-019: De-Elevate the WinUI Surface to Medium Integrity (Filtered-Token Launch)

**Status:** ACCEPTED — 2026-06-03 (LA pre-approved this session)
**Author:** Lead Architect (Blair) + Claude Opus 4.8 (1M context)
**Related:** ADR-014 (the WinUI 3 surface this de-elevates), ADR-009 (interaction
surface / Transport Gateway interface-agnosticism), ADR-017 (voice bring-up —
source of the privilege-boundary lesson, BUILD_JOURNAL #11), ADR-018 (security
posture / trust root).

---

## 1. Context

BlarAI launches **elevated**: `scripts/run_winui_real.bat` requests
Administrator via UAC, then runs `python -m launcher --winui`. The launcher
*needs* admin — `launcher/vm_manager.py` drives Hyper-V (`Start-VM` / `Stop-VM`
/ `Get-VM`), which is admin-gated. The launcher then spawns the WinUI app as an
ordinary child: `subprocess.Popen([exe])` (`launcher/__main__.py`,
`_run_winui_surface`).

A child process inherits its parent's integrity level. So although the WinUI
executable's manifest is `asInvoker` (it requests **no** elevation of its own),
it ran at **High** integrity purely because the elevated launcher spawned it.
That inheritance broke file attach two ways, both confirmed by the User-Operator
at the live screen:

1. **The Win32 open dialog could not select OneDrive cloud-only files.**
   Thumbnails render but "Open" stays greyed; a copy on the local Desktop works.
   An elevated process cannot drive the per-user OneDrive Files-On-Demand
   hydration service (which runs at Medium integrity for the user).
2. **Drag-drop from Explorer did not work.** It is fully wired
   (`MainWindow.xaml.cs` `OnChatDragOver` / `OnChatDrop` →
   `GetStorageItemsAsync`) but Windows **UIPI** (User Interface Privilege
   Isolation) blocks drag-drop messages from medium-integrity Explorer into a
   high-integrity window.

An earlier change (`855d857`) broadened the dialog's image filters on the theory
that *formats* were the problem. They were not. The root cause is **integrity
level**, and both attach paths are gated on it.

This is BUILD_JOURNAL lesson #11 ("a setting that must cross a privilege
boundary has to travel by a channel that crosses it") seen from the other side:
the integrity the UI runs at is a property that must cross the elevation
boundary, and leaving it to process inheritance silently coupled the UI's
integrity to the launcher's.

## 2. Decision

**Keep the launcher elevated (Hyper-V is unchanged), but spawn the WinUI child
at MEDIUM integrity using a *filtered* token — the same shape Windows itself
mints for the standard-user half of a split UAC token.** The UI then runs
exactly as it would have had BlarAI never elevated, so Explorer ↔ UI is a
same-integrity boundary: the shell namespace (cloud files) is reachable and
UIPI does not apply.

The implementation is `launcher/process_launch.py`; `_run_winui_surface` calls
`launch_winui(exe)` in place of `subprocess.Popen([exe])`.

### 2.1 Why de-elevate only the UI, not re-architect the launcher

The smallest change that fixes the root cause. The backend (Hyper-V, the
in-process Policy Agent / Assistant Orchestrator / Transport Gateway /
SessionStore, and the named-pipe server) legitimately needs admin and stays
exactly as it is. The launcher keeps owning the full lifecycle — VM start/stop,
pipe server, and waiting on the UI to exit. No separate elevated helper, no
launcher-restart coordination, no SQLite-lock or pipe-reconnection risk. Only
the **integrity of one spawned child** changes.

### 2.2 The filtered-token recipe (verified on the Arc 140V host, 2026-06-03)

1. Duplicate the launcher's primary token (`DuplicateTokenEx` → `TokenPrimary`).
2. `CreateRestrictedToken(token, DISABLE_MAX_PRIVILEGE, SidsToDisable=[BUILTIN\
   Administrators], ...)` — privileges drop to just `SeChangeNotify`; the
   Administrators group becomes **use-for-deny-only**.
3. Stamp the token's mandatory label down to Medium (`SetTokenInformation`,
   `TokenIntegrityLevel` = `S-1-16-8192`).
4. Launch with `CreateProcessWithTokenW`.

Steps 1–4 were each verified live: the resulting token reports integrity RID
`0x2000` (Medium), Administrators deny-only, privilege count 1; a child launched
with it runs at Medium while the launcher is High, and exit-code propagation
works.

### 2.3 Why `CreateProcessWithTokenW` (not `CreateProcessAsUser`)

`CreateProcessAsUser` rejects a *filtered* token with
`ERROR_PRIVILEGE_NOT_HELD (1314)` — it needs `SeAssignPrimaryToken`, which an
elevated admin process does **not** hold by default. `CreateProcessWithTokenW`
needs only `SeImpersonate`, which the elevated launcher *does* hold, and is the
documented call for launching with an arbitrary token. pywin32 does not expose
it (`win32process.CreateProcessWithTokenW` is absent on this build), so it is
bound via `ctypes` against `advapi32`, with `argtypes` set so 64-bit handles are
not truncated.

The UAC *linked* token (`GetTokenInformation(TokenLinkedToken)`) was tried first
as the most direct source of the standard-user token, but `DuplicateTokenEx` on
it fails with `ERROR_BAD_IMPERSONATION_LEVEL (1346)` at every impersonation
level on this host. Building the filtered token explicitly (2.2) is functionally
equivalent and reliable.

### 2.4 Fail-safe, never fail-dead

Every step is guarded and the launch degrades rather than failing:

`filtered token → plain Medium-label duplicate → ordinary (elevated) launch`

If the filtered-token build fails, a plain Medium-label token is used; if the
Medium launch fails entirely, the launcher falls back to the prior
`subprocess.Popen` (elevated) so the window **always** comes up. The worst case
is the old behavior (attach of cloud files / drag-drop degraded), never a dead
surface. When not elevated at all (dev runs), the child is already Medium and is
launched directly.

### 2.5 The named pipe needs an explicit security descriptor

The UI ↔ backend named pipe (`\\.\pipe\BlarAI`, ADR-014) is created by the
elevated (High) server. It was first reasoned that a same-user Medium client
would connect under *default* security (a no-label object is treated as Medium,
and the default DACL grants the creating user). **Live-verify proved that
wrong** — the de-elevated UI hit `Access to the path is denied` on connect and
showed the backend as down (no sessions either). The pipe is therefore created
with an explicit security descriptor —
`D:P(A;;FA;;;<current-user-SID>)(A;;FA;;;SY)S:(ML;;NW;;;ME)` — granting the
current user + SYSTEM full access and labelling the pipe **Medium**
(no-write-up), so the Medium client is not blocked by the mandatory-integrity
policy. Construction is fail-safe: on any error it falls back to default
security (same-integrity clients still work), so it can never stop the pipe
coming up. Verified standalone — a Medium child spawned via the de-elevation
primitive (2.2) opens the High server's pipe with this SD and exchanges data.
See `services/ui_backend/src/server.py` `_pipe_security_attributes`.

### 2.6 Observability (BUILD_JOURNAL #16)

The Medium-integrity path can only be exercised end-to-end on the elevated,
GPU-bound, windowed run that no headless test of ours reaches. So the launcher
logs, to `launcher.log`, which path it took and the integrity it actually
achieved (`"launched pid N at Medium integrity (launcher is High)"`). Live-verify
becomes a single read, not a guess across the boundary.

## 3. Consequences

- **Drag-drop attach works.** Explorer -> UI is now a same-integrity drop;
  live-verified 2026-06-03. (Cloud-only file *selection in the open dialog* does
  not — see the dialog bullet below.)
- **The UI is now least-privilege.** A filtered, Medium-integrity, admin-deny-
  only token is strictly *less* privileged than the previous High-integrity
  inheritance — a security improvement, consistent with BlarAI's posture.
- **The Win32 open dialog is kept for now, but does not pick cloud-only files.**
  Live-verify showed the legacy `GetOpenFileNameW` still cannot select OneDrive
  Files-On-Demand placeholders even de-elevated — a common-dialog limitation, not
  an integrity one. Switching to the modern `IFileOpenDialog` / WinRT
  `FileOpenPicker` is the follow-up; drag-drop and `/load` cover attach meanwhile.
- **`EnableDragDropAcrossElevation` becomes a fallback safety net**, not the
  primary mechanism. At Medium integrity it is a harmless no-op; it still helps
  the rare elevated-fallback path (2.4). Kept, with its comment rewritten to say
  so.
- **Live-verify is required** (the WinUI surface cannot be build-verified
  headless — BUILD_JOURNAL #2/#16). The token primitive is verified; the windowed
  behavior (window appears, pipe connects, cloud-file pick, drag-drop) is the
  User-Operator's commit-on-green check.

## 4. Alternatives Considered

- **Cloud-file hydration helper** (force-download a picked OneDrive file before
  attaching). Rejected: treats a symptom, leaves drag-drop broken, and adds a
  download path inside the elevated process.
- **Teach the `/load <file>` workaround only.** It works today (copy into
  `userdata/`, `/load`) and remains a useful fallback, but it is not the
  Gemini-shaped attach experience ADR-014 is built for. Kept as a documented
  fallback, not the fix.
- **Full process re-architecture** (de-elevated launcher + separate elevated
  Hyper-V helper, with reconnection/lifecycle coordination). Rejected for this
  change: much larger blast radius (launcher-restart semantics, SQLite locks,
  pipe reconnection, repeated UAC) for no additional user-visible benefit over
  2.1. Remains available if the launcher ever needs to outlive the UI.
- **`CreateProcessAsUser` with the filtered token.** Rejected: fails 1314 (2.3).
- **UAC linked token via `DuplicateTokenEx`.** Rejected: fails 1346 on this host
  (2.3).
- **Leave the UI elevated and switch to the WinRT picker.** Rejected: the WinRT
  picker is unreliable elevated (the very reason the Win32 dialog was chosen in
  ADR-014), and it would not fix drag-drop, which is a UIPI/integrity problem the
  picker choice cannot touch.

## 5. Security Posture

A pre-change audit (this session) confirmed **no** network isolation, firewall
rule, VM configuration, or fail-closed check depends on the *UI* process being
elevated. The named pipe is a kernel object with `PIPE_REJECT_REMOTE_CLIENTS`
and a user-scoped DACL — its security is independent of the client's integrity.
All fail-closed startup gates live in the launcher (which stays elevated). The
no-external-network mandate is untouched. The net effect on posture is positive:
the user-facing surface drops from High to a filtered Medium token.

## 6. Verification

**Verified live (Arc 140V host, elevated session, 2026-06-03):** the filtered
token's integrity / group / privilege shape; `CreateProcessWithTokenW` launching
a Medium child from a High parent; `wait()` / exit-code propagation; a Medium
child opening the High server's pipe with the explicit SD (2.5) and exchanging
data; the launcher test subset (60 passed) and full Python regression sweep with
the new module + unit tests.

**Confirmed by the first User-Operator run (2026-06-03):** the window appears
de-elevated (the launch path works). That run also surfaced the pipe failure —
default pipe security denied the Medium client (`Access to the path is denied`)
— which is fixed by 2.5 and re-verified standalone above.

**Confirmed on relaunch (User-Operator, 2026-06-03):** with the explicit pipe
SD, the de-elevated UI connects to the backend and the chats list populates;
**drag-drop from Explorer attaches a file** (the headline attach win — impossible
when elevated). The Win32 open dialog **still does not select OneDrive cloud-only
files** — accepted for now; spun out as a follow-up (modern `IFileOpenDialog` /
WinRT picker). Net: 2 of 3 attach goals landed + the UI is now least-privilege;
merged to main.
