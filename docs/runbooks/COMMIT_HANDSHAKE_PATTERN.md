# Commit Handshake Pattern

**Purpose**: Keep BlarAI development moving when Claude Code's Bash tool or direct git access degrades.

**Source of authority**: Friction point §5.10 (`devplatform\docs\CLAUDE_WORKFLOW_OPTIMIZATION_D7.md`) and environmental note in `devplatform\docs\CLAUDE_DESKTOP_CONFIGURATION_AGENT_INITIATION_v3.0.xml` §12. **Both live in the devplatform repo (`C:\Users\mrbla\devplatform`), not in BlarAI** — they moved with the platform extraction (`3e73484a`, 2026-04-30), and devplatform is being sunset, so treat them as historical reference. First documented during v2.0 Configuration Agent session (F-3 incident, ledger Entry 43 era); reconfirmed during Domain 7 session when Bash became silently non-responsive.

**When to apply**: the Claude Code Bash tool exits non-zero with no output, or git invocations fail with `ENOENT` / `not recognized`, or any F-3-class fork error surfaces (`dofork child -1 / 0xC0000142 / errno 11`).

---

## 1. Symptom fingerprints

| Symptom | Likely cause |
|---|---|
| Bash tool exits 1 with no output on `pwd` / `ls` / `git status` | Harness-level Bash failure; possibly F-3 class |
| `dofork child -1 / 0xC0000142 / errno 11` in Bash output | F-3 — Cygwin/MSYS2 fork error (see [F3_BASH_FORK_ERROR_RUNBOOK.md](../archive/2026/phase5-prompts/F3_BASH_FORK_ERROR_RUNBOOK.md)) |
| `git: The term 'git' is not recognized` in PowerShell | Canonical `C:\Program Files\Git\cmd\git.exe` missing from PATH or uninstalled |
| `spawn C:\Program Files\Git\cmd\git.exe ENOENT` in VS Code Source Control errors | Same — Git for Windows binary absent from canonical path |

Confirm before declaring the session degraded:

```powershell
# Git for Windows canonical probe
Test-Path 'C:\Program Files\Git\cmd\git.exe'
& 'C:\Program Files\Git\cmd\git.exe' --version
```

If either of those fails, the Agent cannot run git directly. Enter the handshake pattern.

---

## 2. The pattern — four steps

### Step 1 — Agent writes files directly

Use the Write/Edit/Read tools to make file changes at their canonical paths. No git invocations yet.

### Step 2 — Agent produces a commit command block

Provide the Lead Architect with a **single, copy-pasteable command block** that:

- Uses absolute paths (the Lead Architect's shell may not be in the repo root).
- Uses a HEREDOC (`@'...'@` in PowerShell, `<<'EOF' ... EOF` in bash) so multi-line commit messages survive.
- Ends with a verification command (`git log --oneline -1`) so the Lead Architect can confirm the commit landed without reading code.

Example (PowerShell):

```powershell
$git = 'C:\Program Files\Git\cmd\git.exe'
$repo = 'C:\Users\mrbla\BlarAI'
& $git -C $repo add docs/FOO.md
& $git -C $repo commit -m @'
docs(foo): short summary

Longer explanation if needed.

Co-Authored-By: Claude <noreply@anthropic.com>
'@
& $git -C $repo log --oneline -1
```

### Step 3 — Lead Architect pastes into working terminal

Any terminal where the Lead Architect's git works (PowerShell with Git for Windows on PATH, Git Bash, VS Code terminal). The Agent does not need to know which — just the commit outcome.

### Step 4 — Agent verifies

Read `.git/refs/heads/<branch>` or `.git/logs/HEAD` via the Read tool to confirm the commit hash. This is the handshake — Agent confirmed the Lead Architect's git succeeded without itself running git.

Example confirmation:

```
Read: C:\Users\mrbla\BlarAI\.git\refs\heads\main
Expect: commit hash matching the new commit
```

---

## 3. Agent-side git hierarchy (when Agent CAN run git)

If the Agent's environment can reach a git binary — even if Bash is broken — it should try in this order.

| Priority | Binary | Path | When to use |
|---|---|---|---|
| 1 | Git for Windows (canonical) | `C:\Program Files\Git\cmd\git.exe` | First choice. The canonical install. Version 2.54.0 as of 2026-04-20. |
| 2 | GitHub Desktop's bundled git | `C:\Users\mrbla\AppData\Local\GitHubDesktop\app-<version>\resources\app\git\cmd\git.exe` | Fallback if (1) is missing or unreachable. Legitimate install mentioned in [F3_BASH_FORK_ERROR_RUNBOOK.md](../archive/2026/phase5-prompts/F3_BASH_FORK_ERROR_RUNBOOK.md) §8. |
| 3 | WSL bash + Linux git | `C:\Windows\System32\wsl.exe -- git ...` | Last resort. WSL mount namespace does not understand Windows worktree `.git` file pointers; may require `GIT_DIR`/`GIT_WORK_TREE` overrides. |
| — | **AI Playground portable-git** | `C:\Users\mrbla\AppData\Local\Programs\AI Playground\resources\portable-git\bin\git.exe` | **DO NOT USE.** Excluded per Lead Architect standing rule 2026-04-20. AI Playground is unrelated to BlarAI work. |

### Invoking the canonical git from PowerShell

```powershell
$git = 'C:\Program Files\Git\cmd\git.exe'
$repo = 'C:\Users\mrbla\BlarAI'
& $git -C $repo status --short
& $git -C $repo log --oneline -5
```

### Invoking git via PowerShell when working inside a worktree

Worktrees store a `.git` **file** (not directory) pointing at the main repo's `.git/worktrees/<name>/`. The full git binary handles this transparently — but WSL git does not (mount-namespace path mismatch).

```powershell
$git = 'C:\Program Files\Git\cmd\git.exe'
$worktree = 'C:\Users\mrbla\BlarAI\.claude\worktrees\<worktree-name>'
& $git -C $worktree branch --show-current
& $git -C $worktree log --oneline -3
```

---

## 4. Verification without invoking git (reading the plumbing directly)

When absolutely no git binary is reachable, the Agent can still confirm repo state by reading `.git/` plain-text files.

| File | Content | Use |
|---|---|---|
| `<repo>/.git/HEAD` | `ref: refs/heads/<branch>` or a raw commit SHA | Current branch |
| `<repo>/.git/refs/heads/<branch>` | Raw commit SHA | Tip of that branch |
| `<repo>/.git/logs/HEAD` | Reflog (plain text, one entry per line) | History of HEAD moves |
| `<repo>/.git/packed-refs` | Packed branch/tag refs | Branches not in refs/heads/ |
| Worktree `<worktree>/.git` | Plain-text pointer `gitdir: <abs path>` | Follow to the real git dir at `<main>/.git/worktrees/<name>/` |

This is how Domain 7's commit `5e391af` was verified clean during the session — reading `.git/worktrees/exciting-kilby-7dcc84/logs/HEAD` confirmed the committer identity without running git.

---

## 5. Credential hygiene during the handshake

If the commit message or commit content would contain a credential (password, token, path with username encoded), the Agent must not embed it in the command block. Produce the commit command with credential *references* (env var names, config keys) and let the Lead Architect expand them in their local shell.

The handshake is **not** a credential escape hatch.

---

## 6. Cross-references

- [F-3 Bash Fork Error Runbook](../archive/2026/phase5-prompts/F3_BASH_FORK_ERROR_RUNBOOK.md) — root-cause runbook for F-3 class. (Archived; it is no longer at the docs root.)
- [MCP Refresh Drill](MCP_REFRESH_DRILL.md) — sibling runbook for MCP tool-surface degradation.
- [MCP Config Sync](MCP_CONFIG_SYNC.md) — sibling runbook for keeping the three MCP config files aligned.
- §5.10 in `devplatform\docs\CLAUDE_WORKFLOW_OPTIMIZATION_D7.md` — friction inventory entry this runbook resolves. (**devplatform** repo, not BlarAI.)
- `devplatform\docs\CLAUDE_DESKTOP_CONFIGURATION_AGENT_INITIATION_v3.0.xml` §12 environmental notes. (**devplatform** repo, not BlarAI.)

---

## 7. Document lifecycle

- **v1.0** — 2026-04-20 — initial, authored during Domain 7 recommendations implementation (§6.4). Incorporates lessons from v2.0 Configuration Agent and Domain 7 session's own degraded experience.
