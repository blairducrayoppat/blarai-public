# MCP Config Sync

**Purpose**: Keep the three MCP configuration files in sync so every Claude surface sees the same server roster (modulo intentional scope differences).

**Source of authority**: Friction point §5.12 (`devplatform\docs\CLAUDE_WORKFLOW_OPTIMIZATION_D7.md` — in the **devplatform** repo, not this one; it moved with the platform extraction `3e73484a`, 2026-04-30). F-1 precedent — plaintext Vikunja password drift between the three files surfaced in Domain 6.

**When to run**: after adding, removing, or changing any MCP server in any of the three files.

---

## 1. The three files and their intended scope

| File | Surface | Git status | Typical server set |
|---|---|---|---|
| `%APPDATA%\Claude\claude_desktop_config.json` | Claude Chat (Desktop) | Outside repo, not version-controlled | Full slate: vikunja, filesystem, git, memory, time, sequentialthinking, fetch (plus others as added) |
| `C:\Users\mrbla\BlarAI\.mcp.json` | Claude Code (project-scoped) | **Gitignored** — contains credentials | Minimal: vikunja (other MCPs available natively in Code) |
| `C:\Users\mrbla\BlarAI\.vscode\mcp.json` | VS Code Copilot | **Gitignored** (`.gitignore:43` ignores `.vscode/`) — present on disk, never committed | Minimal: vikunja |

The divergence is by design — most Domain 6 Tier A+B MCPs are Chat-only per `devplatform\docs\CLAUDE_MCP_ECOSYSTEM_MATRIX.md` §6. Claude Code has native `git`, `WebFetch`, `Bash`, etc., so it doesn't need their MCP duplicates. This runbook is about aligning the *overlapping* servers (credentials, env, command line), not forcing identical rosters.

---

## 2. The sync procedure

### Step 1 — Decide the change at a single source of truth

Pick one file as the canonical source for the change. For BlarAI, the canonical source is typically `claude_desktop_config.json` (the richest surface; Chat is where most Config Agent / Co-Lead / SDO work happens).

### Step 2 — Project the change into the other two files

For each overlapping server in the other two files, copy the updated command, args, and env.

Example — Vikunja password rotation. If the new password is `<NEW>`:

```powershell
# 1. Desktop — edit %APPDATA%\Claude\claude_desktop_config.json
#    Replace env.VIKUNJA_PASSWORD with <NEW>

# 2. Code — edit C:\Users\mrbla\BlarAI\.mcp.json
#    Replace env.VIKUNJA_PASSWORD with <NEW>

# 3. VS Code — edit C:\Users\mrbla\BlarAI\.vscode\mcp.json
#    Replace env.VIKUNJA_PASSWORD with <NEW>
```

### Step 3 — Verify JSON is valid in all three

```powershell
Get-Content '%APPDATA%\Claude\claude_desktop_config.json' | ConvertFrom-Json | Out-Null
Get-Content 'C:\Users\mrbla\BlarAI\.mcp.json' | ConvertFrom-Json | Out-Null
Get-Content 'C:\Users\mrbla\BlarAI\.vscode\mcp.json' | ConvertFrom-Json | Out-Null
```

Each should exit cleanly. Any thrown exception = broken JSON = all servers in that file silently disabled.

### Step 4 — Run the MCP Refresh Drill

See [MCP_REFRESH_DRILL.md](MCP_REFRESH_DRILL.md). Restart Desktop, close Chat tabs, restart Claude Code sessions, restart VS Code.

### Step 5 — Spot-verify the overlapping server works from each surface

Minimum verification: call `project_summary` (or equivalent lightest read) from each surface and confirm a live response.

---

## 3. Credential hygiene

### 3.1 Never commit credentials

`.mcp.json` is gitignored — credentials there are local-only. **Verify** before committing anything adjacent:

```powershell
$git = 'C:\Program Files\Git\cmd\git.exe'
& $git -C 'C:\Users\mrbla\BlarAI' check-ignore -v .mcp.json
# Must print a rule match. If it prints nothing, .mcp.json is NOT ignored — stop and fix .gitignore.
```

> **Corrected 2026-07-20 (#979).** This section used to say `.vscode/mcp.json`
> "is git-tracked historically" and that moving it out of tracking was an open
> hardening item. That is not the case, and was verified on disk:
>
> - `.gitignore:43` ignores the whole `.vscode/` directory.
> - `git ls-files .vscode/` returns nothing — nothing under it is tracked.
> - `git log --all -- .vscode/mcp.json` returns nothing — **the file has never
>   been committed**, so no credential in it has ever entered git history.
> - `.mcp.json` is likewise ignored (`.gitignore:122`), untracked, never committed.
>
> Both credential-bearing files are therefore out of git by construction. The
> old remediation this section prescribed — "move `.vscode/mcp.json` out of
> tracking" — is already satisfied, so it has been removed rather than left
> standing as an open action. There is nothing to untrack and no history to
> rewrite for either path.

Neither `.mcp.json` nor `.vscode/mcp.json` is in git. If you are adding a **new**
config file that will carry a credential, keep that property — either gitignore it
before the first commit, or source the credential from an env var backed by a
gitignored `.env` and reference the var in the JSON.

The remaining open item from F-1 is narrower than this document used to imply:
credentials still sit in **plaintext on disk** in these files (they are merely
outside version control), and the envvar-sourced-credential design is still
unimplemented. That is a real hardening item; accidental git exposure is not.

### 3.2 Rotate on compromise signals

Signals: credential appeared in a public paste, committed to git by accident, leaked via log, device stolen. Rotation pattern:

1. Rotate the credential in the source system (e.g. Vikunja web UI → user → change password).
2. Project the new credential into all three config files per this runbook.
3. Run the MCP Refresh Drill.
4. If the old credential ever touched git history: **rotate first (steps 1–3 above), then stop and escalate. Do not rewrite history yourself.**

> **Corrected 2026-07-20 (#979).** This step used to read "consider whether a
> history rewrite is warranted (local-only repo → low risk; future push to remote →
> high risk, rewrite preemptively)." Both halves were wrong.
>
> **This repo is not local-only.** It has two remotes and one of them is public —
> `origin` → `blarai-private`, `public` → `blarai-public` (`git remote -v`). A
> credential in history is a present exposure question, not a hypothetical future
> one, so the risk framing was inverted in the credential-exposure section.
>
> **And rewriting history is forbidden here, without exception.** Project doctrine
> bars destructive git operations outright: no force-push, no history rewrite, no
> branch deletion. Other sessions share this tree and there is no human able to
> rescue a botched rewrite. A runbook instructing an operator to rewrite history
> tells them to perform the one operation the project does not permit.
>
> Rotation (steps 1–3) is the control that actually works — it makes the leaked
> value useless wherever it already sits. Whether to excise anything from shared,
> possibly-published history is a Lead-Architect decision, not this runbook's.

---

## 4. Future automation (not implemented)

A single JSON source file (`config/mcp-servers.json`) with a sync script that projects into the three destinations is **deferred** per D7 §6.7. Trigger conditions for implementing:

- MCP server count grows past \~10 and manual sync becomes error-prone.
- Credential rotation becomes frequent (e.g. Vikunja moves to rotating tokens).
- Multi-operator scenario introduces sync drift between operators.

Until then, this runbook (manual sync with verification) is sufficient.

---

## 5. Cross-references

> The three `CLAUDE_*` documents below live in the **devplatform** repo
> (`C:\Users\mrbla\devplatform`), not in BlarAI — they moved with the platform
> extraction (`3e73484a`, 2026-04-30). devplatform is being sunset; treat them as
> historical reference only.

- `devplatform\docs\CLAUDE_MCP_ECOSYSTEM_MATRIX.md` — which server belongs in which file.
- [MCP_REFRESH_DRILL.md](MCP_REFRESH_DRILL.md) — the post-sync restart procedure.
- [COMMIT_HANDSHAKE_PATTERN.md](COMMIT_HANDSHAKE_PATTERN.md) — git operations if the Agent needs to commit config changes while Bash is degraded.
- F-1 §7 in `devplatform\docs\CLAUDE_DESKTOP_CONFIGURATION_AGENT_INITIATION_v3.0.xml` — Vikunja credential hardening history.
- §5.12 in `devplatform\docs\CLAUDE_WORKFLOW_OPTIMIZATION_D7.md`.

---

## 6. Document lifecycle

- **v1.0** — 2026-04-20 — initial, authored during Domain 7 recommendations implementation (§6.7).
