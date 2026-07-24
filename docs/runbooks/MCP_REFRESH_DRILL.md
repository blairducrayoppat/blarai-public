# MCP Refresh Drill

**Purpose**: Guarantee newly-installed or newly-upgraded MCP servers become visible to every agent surface that needs them.

**Source of authority**: Friction point F-8 (`devplatform\docs\CLAUDE_DESKTOP_CONFIGURATION_AGENT_INITIATION_v3.0.xml` §7 — in the **devplatform** repo, not this one) — Claude Chat locks the MCP tool surface at session start. Config changes do not propagate to existing sessions.

**When to run**: after any of the following:

- Installed a new MCP server.
- Changed an MCP server's command, args, env, or credential.
- Removed a misbehaving MCP server.
- Updated a shared credential (e.g. Vikunja password rotation — ties to F-1 class).
- Upgraded the Vikunja server binary or its config.

**Applies to all three MCP config files**:

| File | Scope | Agent surface |
|---|---|---|
| `%APPDATA%\Claude\claude_desktop_config.json` | Claude Chat (Desktop app) | Chat Projects |
| `C:\Users\mrbla\BlarAI\.mcp.json` | Claude Code (project-scoped, gitignored) | EA / Configuration Agent in Code |
| `C:\Users\mrbla\BlarAI\.vscode\mcp.json` | VS Code Copilot | Interactive dev |

---

## The drill

### Step 1 — Verify config JSON is syntactically valid

Before restarting anything. Invalid JSON silently disables ALL servers in that file.

```powershell
# For each of the three files:
Get-Content '%APPDATA%\Claude\claude_desktop_config.json' | ConvertFrom-Json | Out-Null
Get-Content 'C:\Users\mrbla\BlarAI\.mcp.json' | ConvertFrom-Json | Out-Null
Get-Content 'C:\Users\mrbla\BlarAI\.vscode\mcp.json' | ConvertFrom-Json | Out-Null
```

Any command that throws = that file is broken. Fix before proceeding.

### Step 2 — Confirm external dependencies are live

Some MCP servers require an external process to be running at refresh time (the Vikunja MCP requires `vikunja.exe` on `localhost:3456`).

```powershell
# Vikunja — check the binary is running
Get-Process vikunja* -ErrorAction SilentlyContinue
# If empty, start it:
Start-Process 'C:\Users\mrbla\devplatform\tools\vikunja\vikunja-v2.3.0-windows-4.0-amd64.exe'
```

### Step 3 — Restart Claude Desktop

1. Right-click the Claude Desktop tray icon → **Quit**.
2. Reopen Claude Desktop.
3. **Close every existing Chat tab.** Even tabs that look inactive have a locked tool surface — they must be disposed.
4. Open a fresh chat in each Project you will use.

### Step 4 — Restart Claude Code sessions

Claude Code picks up `.mcp.json` on session start. For any active Code session, close it and open a fresh one.

Fresh Configuration Agent or EA sessions after this point will see the new tool surface.

### Step 5 — Restart VS Code

`.vscode/mcp.json` is read when VS Code launches (or when the Copilot extension reloads). Close VS Code fully, reopen.

### Step 6 — Verify new tool surface

For each MCP server that was added or changed, probe it. In Claude Chat or Code:

```
tool_search(query="<server-name>")
```

In Claude Code specifically (this session tool), schemas should load via ToolSearch and tool calls should succeed.

Example for Vikunja:

```
# Chat
tool_search(query="vikunja")
# Then call, e.g. mcp__vikunja__project_summary (or vikunja:project_summary)
```

If `tool_search` returns no match in Chat, the Desktop restart did not take — see troubleshooting below.

### Step 7 — Record the refresh in Vikunja (optional, for MATURE audit trail)

For non-trivial changes (new MCP server installation, credential rotation), add a comment to the associated task in `BlarAI Infrastructure` (project 4) noting the refresh timestamp and any verification results.

---

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `tool_search(query="X")` returns no match in Chat after restart | Desktop restart didn't fully quit; stray tray icon | Use Task Manager → kill all `Claude.exe`. Then relaunch. |
| Tools visible in Chat but calls hang | External dependency (Vikunja) not running | Start the dependency binary; retry. |
| Tools visible in Chat but return authentication errors | Credential in config is stale or wrong | Rotate in source system; update all three config files; re-run drill. |
| `.mcp.json` shows fewer servers than `claude_desktop_config.json` | By design — most Domain 6 Tier A+B MCPs are Chat-only per the ecosystem matrix (`devplatform\docs\CLAUDE_MCP_ECOSYSTEM_MATRIX.md`) §6. Not a bug. | None — verify intent before adding to Code. |
| VS Code shows "no MCP servers" | Copilot extension didn't reload | Command palette → "Developer: Reload Window". |

---

## Cross-references

> Several documents this runbook was written against now live in the **devplatform**
> repo (`C:\Users\mrbla\devplatform`), not in BlarAI — they moved with the platform
> extraction (`3e73484a`, 2026-04-30). They are reference-only; devplatform is being
> sunset. Paths below are repo-qualified so they resolve.

- `F3_BASH_FORK_ERROR_RUNBOOK.md` — orthogonal concern (Bash tool, not MCP surface), but recovery may overlap with environmental drift. Archived in this repo at [`docs/archive/2026/phase5-prompts/F3_BASH_FORK_ERROR_RUNBOOK.md`](../archive/2026/phase5-prompts/F3_BASH_FORK_ERROR_RUNBOOK.md).
- **Claude MCP Ecosystem Matrix** — authoritative MCP server roster + venue intentions (which MCP belongs in which config file). Now `devplatform\docs\CLAUDE_MCP_ECOSYSTEM_MATRIX.md`.
- [Commit Handshake Pattern](COMMIT_HANDSHAKE_PATTERN.md) — sibling runbook for git-tool degradation.
- [MCP Config Sync](MCP_CONFIG_SYNC.md) — sibling runbook for keeping the three config files consistent.
- F-8 §7 in `devplatform\docs\CLAUDE_DESKTOP_CONFIGURATION_AGENT_INITIATION_v3.0.xml`.

---

## Document lifecycle

- **v1.0** — 2026-04-20 — initial, authored during Domain 7 recommendations implementation (§6.4).
