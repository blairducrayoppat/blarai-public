# BlarAI Disaster-Recovery Restore Runbook — full system rebuild after loss of this machine

**This file is the tracked MASTER.** The nightly backup (`agentic-setup\scripts\backup-system.ps1`,
Task Scheduler "BlarAI System Backup", ~20:30 daily) copies it to the OneDrive backup root as
`RESTORE_RUNBOOK.md`, so the copy you read *after* a disaster is never staler than the last backup.
Edit it HERE; never edit the OneDrive copy by hand.

- Backup root: `C:\Users\mrbla\OneDrive\BlarAI-Reformat-Backup-2026-07-01` (established 2026-07-01;
  **content refreshes nightly** — see `LAST_BACKUP.txt` + `backup-log.txt` in that folder).
- Last restore drill: **2026-07-09** (see "Rehearsal record" at the end — what is proven, what is not).
- Supersedes the static 2026-07-01 runbook (drifted facts corrected 2026-07-09: Python version,
  lockfile, branch counts, model list, WIP-branch naming, gate baseline).

This backup + the private GitHub repos + the USB secrets stick are together sufficient to rebuild
the full system: BlarAI, the coding fleet (OpenCode + dispatch + AI Control Panel), the jobhunt
tool, Vikunja task tracking, and the Hyper-V guest VM.

---

## ⚠ BEFORE the reformat — three things that cannot be recovered later

1. **The BlarAI offline recovery key.** BlarAI's knowledge/session/substrate databases are
   encrypted with a DEK sealed to this machine's TPM. The provisioning ceremony printed an
   **offline recovery key exactly once** (to be stored on paper/USB/safe). After a reformat, the
   ONLY way to decrypt the backed-up databases is:
   `python -m shared.security.provision_dek_keystore --recover`
   which prompts for that key. **Confirm you can find it before wiping.**
   If it is lost, the encrypted DBs in `runtime-data/BlarAI/` are unrecoverable (everything else
   in this backup still restores fine).
   - The recovery-unwrap *code path* is gate-tested (`shared/tests/test_field_cipher_and_dek_envelope.py`:
     dual-unwrap, wrong-key fail-closed, TPM-tamper fallback). The *physical input* — the printed
     key — is the only untested link. **Verification log:** 2026-07-09 — operator
     confirmed possession in-chat (#782 c.1555). Re-confirm annually and after any move of
     the printed copy; the unwrap-with-the-physical-key drill awaits a second machine.
2. **The secrets bundle.** `C:\Users\mrbla\reformat-secrets\` was deliberately staged OUTSIDE
   OneDrive. Copy it to a USB stick now. It contains: SSH keypair, .gitconfig, jobhunt `.env`
   (Anthropic API key), `.blarai-fleet\credentials.env` (Anthropic API key), the three
   `.mcp.json` files (Vikunja password), Codex auth, Claude Desktop MCP config, and
   `user-env-vars.txt` (User-scope env vars incl. `VIKUNJA_PASS`).
3. **OneDrive sync completion.** This backup folder is ~50 GB (models alone are 49 GB). Open the
   OneDrive tray icon and wait for **"Up to date"** before wiping. Spot-check on onedrive.live.com
   that `models/` and `hyperv-vm/` show full sizes.

---

## What lives where

| Store | Contents |
|---|---|
| **GitHub (private, account `blairducrayoppat`)** | `blarai` (all branches — 555 pushed as of 2026-07-09 — incl. the rolling `backup/wip-rolling` snapshot of uncommitted work), `agentic-setup`, `devplatform`, `jobhunt`, `jobhunt-eligibility` — full source + docs (ADRs, BUILD_JOURNAL, runbooks, sprints). Pushed nightly. |
| **The OneDrive backup folder** | git bundles (point-in-time 2026-07-01 — the belt-and-braces history incl. 3 legacy branches GitHub refused for oversized blobs), model weights, encrypted runtime DBs + keystores (nightly SQLite snapshots), Vikunja DB + server, OVMS install, opencode config + history DB, Claude memory/agents/skills, Hyper-V VM disk, system config exports, restore scripts, this runbook (nightly copy). |
| **USB stick (you copy it)** | `reformat-secrets` bundle |
| **GitHub (public)** | `blarai-public` / `agentic-setup-public` snapshot mirrors (portfolio surface, weekly Monday task + manual runs). NOT a restore source — no secrets, no history. |
| **Survives on its own** | OneDrive Desktop (launcher shortcuts), BIOS/UEFI settings (shared-GPU-memory behavior on Lunar Lake is BIOS/driver-default — no registry override was set), the TPM (hardware — but see recovery-key note above) |

Notes on deliberate exclusions: `oss/` OpenVINO clones (re-clone from GitHub; local tweak saved as
`misc/openvino.genai-local-changes.patch`), `C:\models\coder-30b` (re-download: HuggingFace
`OpenVINO/Qwen3-Coder-30B-A3B-Instruct-int4-ov`), all `ov_cache`/NPU caches (regenerate on first
model load), `.venv`s (rebuild from lockfiles), `projects/` fleet test output (disposable).
The backup script's push-exclusion list also names `feat/719-golive-ceremony` — that branch no
longer exists anywhere (stale entry, harmless; the 3 real oversized branches are in the 7/1 bundle).

---

## Restore sequence

### Phase 1 — Base OS + toolchains
1. Windows 11 Pro, sign into Microsoft account → let OneDrive sync (enable Files On-Demand to
   avoid pulling 50 GB immediately).
2. Enable Windows features: **Hyper-V** (all), then reboot.
   `Enable-WindowsOptionalFeature -Online -FeatureName Microsoft-Hyper-V -All`
3. Install toolchains — versions recorded in `system/toolchain-inventory.txt`, full app list in
   `system/winget-packages.json`: `winget import system/winget-packages.json`
   Minimum set: Git, GitHub CLI, **Python 3.11** (the runtime venv is pinned to 3.11.9 — the
   validated OpenVINO GenAI substrate) **plus Python 3.14** (the AF_HYPERV guest bridge — see
   blarai `shared/fleet/guest_oracle_bridge.py` header), Node.js LTS, .NET 8 SDK, Intel GPU
   driver + Intel Graphics Software, Claude Desktop, VS Code.
4. Intel graphics: install driver + IGS. Reference exports in `system/`
   (`reg-graphicsdrivers.reg`, `IntelGraphicsSoftware-settings/`) — for comparison, not blind
   import (driver GUIDs change per install).

### Phase 2 — Identity + secrets (from USB)
1. Copy `ssh/` → `C:\Users\<you>\.ssh`, `gitconfig` → `C:\Users\<you>\.gitconfig`,
   `git-credentials` → `C:\Users\<you>\.git-credentials` (stored git/HF tokens; gitconfig uses
   credential.helper=store).
2. Run `scripts/restore-user-env-vars.ps1 <usb>\user-env-vars.txt` (re-creates User-scope env
   vars incl. `VIKUNJA_PASS`).
3. `gh auth login` (GitHub CLI), sign into Claude Desktop / Claude Code.
4. Copy `claude_desktop_config.json` → `%APPDATA%\Claude\`.
5. **Recommended:** rotate the Anthropic API keys and Vikunja password that sat in plaintext,
   then update `jobhunt\.env`, `.blarai-fleet\credentials.env`.

### Phase 3 — Repos
```powershell
cd C:\Users\<you>
gh repo clone blairducrayoppat/blarai-private blarai
gh repo clone blairducrayoppat/agentic-setup-private agentic-setup
gh repo clone blairducrayoppat/devplatform
gh repo clone blairducrayoppat/jobhunt
mkdir projects; cd projects
gh repo clone blairducrayoppat/jobhunt-eligibility
```
(Alternative/offline: `git clone <backup>\git-bundles\<name>-20260701.bundle` — point-in-time
2026-07-01; GitHub is the current-history leg. The blarai bundle additionally carries the 3 legacy
branches GitHub refused for an oversized evidence blob: `copilot/worktree-2026-03-13T06-25-42`,
`feature/openvino-contrib-agent`, `fix/vpux-crash-reproduction-intel-pr`.)

Uncommitted work at backup time lives on the rolling `backup/wip-rolling` branch in each repo
(each snapshot commit chains onto the previous one; the newest is the tree state at the last
20:30 backup) — check it out or cherry-pick to recover working state.

Then restore the gitignored files into place (from USB): the three `.mcp.json` → repo roots of
blarai / agentic-setup / devplatform; `jobhunt.env` → `jobhunt\.env`;
`blarai-fleet.credentials.env` → `C:\Users\<you>\.blarai-fleet\credentials.env`.

### Phase 4 — Claude Code config + memory
Copy from `claude/` in the backup folder into `C:\Users\<you>\.claude\`: `agents\`, `commands\`,
`skills\`, `settings.json`, `keybindings.json`, `CLAUDE.md`, and `projects\<namespace>\memory\`
(all namespaces — this is Claude's persistent memory of the whole program).

### Phase 5 — Models + inference stack
1. `models/blarai-models/*` → `C:\Users\<you>\blarai\models\` (13 model directories + `docsets/`,
   ~49 GB as of 2026-07-09).
2. Expand `ovms/ovms-2026.2-install.zip` → `C:\ovms`.
3. Coder model: `pip install huggingface_hub` (throwaway venv) then
   `hf download OpenVINO/Qwen3-Coder-30B-A3B-Instruct-int4-ov --local-dir C:\models\coder-30b`
4. BlarAI venv — **Python 3.11, current lockfile**:
   `cd blarai; py -3.11 -m venv .venv; .venv\Scripts\pip install -r requirements.2026.2.1.lock.txt`
   (`requirements.2026.2.1.lock.txt` = the validated 2026.2.1 substrate, frozen 2026-07-09.
   The older `requirements.2026.1.0.lock.txt` is historical — restoring from it would silently
   downgrade OpenVINO below the substrate every 2026-06/07 measurement was made on.
   agentic-setup + jobhunt likewise from their own lockfiles/requirements.)

### Phase 6 — BlarAI runtime data + encryption re-seal
1. Copy `runtime-data/BlarAI/*` → `%LOCALAPPDATA%\BlarAI\` (3 DBs + 3 keystore JSONs +
   ui_prefs.json — the DBs are nightly consistent SQLite snapshots).
2. Re-seal the DEK to the new install's TPM (needs the **offline recovery key**):
   `python -m shared.security.provision_dek_keystore --recover`
3. Launch via the Desktop shortcut (`scripts\run_winui_real.bat`) and verify old
   sessions/knowledge decrypt. URL-ingest mode launcher = `scripts\run_winui_golive.bat`
   (Desktop: "BlarAI - URL Ingest").

### Phase 7 — Vikunja
1. Copy `vikunja/vikunja.db` → `%LOCALAPPDATA%\Vikunja\vikunja.db`.
2. Copy server files (`vikunja-v2.3.0-windows-4.0-amd64.exe`, `config.yml`,
   `start_vikunja*.{bat,vbs}`) → `C:\Users\<you>\devplatform\tools\vikunja\`.
   **Use `vikunja.config.yml` from the USB secrets bundle** — the OneDrive copy has the JWT
   secret redacted.
3. Re-create the Startup shortcut (see `system/startup-items.txt`) pointing at
   `start_vikunja_hidden.vbs`. Verify at http://localhost:3456.

### Phase 8 — Hyper-V guest VM
Run `scripts/recreate-vm.ps1` (elevated) — copies `hyperv-vm/Orchestrator.vhdx` back to
`C:\HyperV\BlarAI\` and re-creates the **BlarAI-Orchestrator** Gen-2 VM (2 vCPU, 1 GB startup /
2 GB max dynamic memory). The Alpine ISO and `vsock_echo.py` test script are alongside.
Note: the guest parser (vsock 50001) + guest oracle (vsock 50002) services live on the VHDX and
come back with it; re-provisioning scripts are in blarai `scripts/guest/` if they don't.

### Phase 9 — Coding fleet + OpenCode
1. `npm i -g opencode-ai` (the fleet pins a version — see `agentic-setup` state/pin artifacts;
   install that version, currently 1.17.8).
2. Copy `opencode/config/*` → `C:\Users\<you>\.config\opencode\` (opencode.json, AGENTS.md,
   agents\, plugin\). Optional: `opencode/opencode.db` → `C:\Users\<you>\.local\share\opencode\`
   (session history).
3. Fleet state continuity (optional): `misc/fleet-queue.json`, `misc/recent-projects.txt` →
   `agentic-setup\state\`.
4. Desktop launchers are already back via OneDrive Desktop sync; they point into
   `agentic-setup\*.cmd` which came back with the repo clone.
5. Re-register the scheduled tasks that matter: "BlarAI System Backup" + "BlarAI Public
   Snapshot" (`agentic-setup\scripts\register-backup-task.ps1`), and the battery nightly task if
   a campaign is active (see `agentic-setup\scripts\run-battery-night.ps1` header).

### Phase 10 — Verification gate
1. BlarAI standing gate (LOCALAPPDATA redirected per test discipline, venv interpreter):
   `pytest shared/ services/ launcher/ tests/integration/ tests/security/ -m "not hardware and not winui and not slow"`
   — expect the current baseline in `CLAUDE.md` §Active State (≈5900+ passing, 0 failures, as of
   2026-07-09).
2. Launch "Everyday AI (14B)" → chat turn streams.
3. AI Control Panel → model status + VM state render.
4. "Deep Coding (30B)" + `opencode` → coder responds; then a BlarAI `dispatch` smoke test against
   a repo under `projects\`.
5. `2 - Start jobhunt.bat` → pipeline board loads at 127.0.0.1:8765.
6. Vikunja MCP: in Claude Code run `project_summary`.

---

## Scheduled tasks / startup
Only ONE startup item mattered: the Vikunja hidden starter (Phase 7). The exported task XMLs in
`system/scheduled-tasks/` are app-installed maintenance tasks (Intel/Edge/OneDrive/etc.) that
return automatically with their apps — re-import selectively only if something is missed:
`Register-ScheduledTask -Xml (Get-Content .\system\scheduled-tasks\<name>.xml -Raw) -TaskName <name>`
The BlarAI-owned tasks (backup, public snapshot, battery nightly) are re-registered in Phase 9.

---

## Rehearsal record

| Date | Leg | Result |
|---|---|---|
| 2026-07-09 | Private-remote clone (blarai, shallow) → usable tree at last-pushed HEAD | PASS |
| 2026-07-09 | Git bundle `blarai-20260701.bundle` verify → "records a complete history" | PASS |
| 2026-07-09 | OneDrive DB snapshots (knowledge/sessions/substrate) restored to scratch → `PRAGMA integrity_check` ok on all three | PASS |
| 2026-07-09 | Weights spot-check: OneDrive vs local `openvino_model.xml` sha256 identical | PASS |

**Not rehearsed (named, per the community-grade honesty rule):** the TPM recovery-unwrap with the
*physical* printed key (code path gate-tested; physical input verification pending — Vikunja
#782); a full restore onto different hardware (a future LA-present ceremony); OneDrive
*cloud-side* completeness beyond the tray "Up to date" check.

## Keeping this runbook current

- **Master lives here** (`blarai/docs/runbooks/DISASTER_RECOVERY_RESTORE.md`); the nightly backup
  copies it to the OneDrive backup root. If you are reading the OneDrive copy after a disaster,
  it is at most one day older than the last backup.
- When these facts drift, update the master: the lockfile name (new OpenVINO substrate ⇒ new
  freeze), the model list, the gate baseline, branch counts, the opencode pin.
- Git bundles are point-in-time — refresh them after any new oversized-branch exclusion is added
  to `backup-system.ps1`, and opportunistically at quarterly consolidation passes.
- The recovery-key verification (⚠ item 1) should be re-confirmed annually and after any move of
  the printed key.
