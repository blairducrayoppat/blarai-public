# Deep Risk Review — Platform Separation Process

**Author**: Copilot audit pass, 2026-04-23 (last refreshed 2026-04-26)
**Scope**: Focus on HIGH-risk stages (2, 4) with cross-file logic, embedded code syntax, cutover atomicity, and process maturity.
**Method**: Sequential read of all 7 stage XMLs + master plan; cross-reference of placeholder flow, file-path consistency, command idempotence, and recovery completeness.
**Status**: Most §0 / §0.5 fixes APPLIED to source files in the v2 remediation pass on branch `docs/platform-separation-v2`. See §0 below for the consolidated tally.

---

## §0.5 — v2 Risks Added (2026-04-24)

The v2 deltas (per [INFRA_DELTA_v2.md](INFRA_DELTA_v2.md)) introduce these new risk classes:

| # | Risk | Mitigation in v2 |
|---|------|------------------|
| V1 | **Worktree contamination** — fleet-spawned worktree on the same branch causes silent commit/stash drift during destructive stages. | Pre-checked at Stage 0.5.5; re-verified at 4.0.5. `git worktree list` must be empty (only main). |
| V2 | **Wake-template path drift** — wake_launcher fires templates that hardcode BlarAI tool paths. Cutover misses these → wakes still target BlarAI after cutover. | New Stage 4.7.5 PowerShell loop rewrites all `BlarAI\tools\*` patterns to `devplatform\tools\*` while preserving BlarAI as a target-project reference. Verify via 4.7.5 `<verify>` Select-String. |
| V3 | **state.json schema versioning** — fleet tools may evolve required fields. Untracked drift = silent fleet failure. | `schema_version=1` is committed. `.lock`/`.tmp` siblings ignored. Stage 0.10.v3 validates 9 required fields. |
| V4 | **Governance doc duplication** — both repos may carry `docs/governance/` causing rule conflict. | Stage 5.5.v2 deletes the BlarAI copy after Stage 3.2.v2 copies to devplatform. BlarAI keeps a thin pointer. |
| V5 | **Vikunja label-ID drift** — re-creating labels in a fresh Vikunja DB renumbers them; tools that hardcode IDs break. | All 14 label IDs locked in `devplatform/projects/registry.yaml` via Stage 1.4.v2 seed. CLAUDE.md §Vikunja Conventions is the authoritative source. |
| V6 | **Fleet Reports project_id spoofing** — accidental cross-project posting if `project_id` is computed at the wrong layer. | Hardcoded at registry seed (id=8) + `_vikunja_client` assertion in Stage 2.7.v2. |
| V7 | **`unpause_fleet` AttributeError** — wrong function name will silently leave fleet paused after cutover. | Every v2 reference uses `state.resume_fleet()` and includes an `<api_gotcha>` note. Manual fallback documented in CLAUDE.md SOP. |
| V8 | **Doctrine split race** — splitting CLAUDE.md / copilot-instructions.md while LA is editing them = lost work. | Stage 6.1.v2 explicitly DEFERS the split until a separately-approved session. |

---

## §0 — Prior fixes applied to source XMLs (this pass)

| # | File | Item | Fix |
|---|------|------|-----|
| F1 | `01_STAGE0_PREFLIGHT.xml` | 0.4 | `Get-Process` → `Get-CimInstance Win32_Process` for CommandLine filtering (PS 5.1 limitation). |
| F2 | `05_STAGE4_CUTOVER.xml` | 4.0 | Same CIM fix as F1. |
| F3 | `05_STAGE4_CUTOVER.xml` | 4.3 | Added explicit `$env:VIKUNJA_TOKEN` precondition guard with how-to-obtain-token instructions. |
| F4 | `02_STAGE1_SCAFFOLD.xml` | 1.4 | Added "restart Vikunja temporarily" steps to resolve chicken-and-egg with Stage 0.4 stop. |
| F5 | `07_STAGE6_HARDENING.xml` | 6.2 | Added `infrastructure_prerequisites` to BlarAI-retained sections (Hyper-V VM is product-specific). |

### §0.6 — v2 remediation pass (2026-04-26, branch `docs/platform-separation-v2`)

The following defects raised in §1 / §3 / §0.5 (and several discovered in re-read) have been patched in source. Branch `docs/platform-separation-v2`; **NO merge to `main`** until Lead Architect approval.

| # | File | Defect | Fix applied |
|---|------|--------|-------------|
| R1 | `STATUS.md`, `INFRA_DELTA_v2.md`, `00_MASTER_PLAN.md` (§11.1, §11.2), `06_STAGE5_CLEANUP.xml` (5.5.5), `07_STAGE6_HARDENING.xml` (6.7.v2) | False "13 → 14, escalation-watchdog added as 14th task" narrative. Live fleet has always been 13 tasks at TaskPath `\BlarAI\`; `Escalation Watchdog` is part of it. | Standardized on **13 tasks** with full task list enumerated in MASTER_PLAN §11.2; v2 banners stripped of "14th" claim; v2 task-count assertions corrected. |
| R2 | `00_MASTER_PLAN.md` §11.2, `03_STAGE2_REFACTOR_MULTIPROJECT.xml` (2.5, 2.5.v2), `05_STAGE4_CUTOVER.xml` (4.7.6) | wake_launcher path written as `tools/fleet_ops/wake_launcher.ps1` (does not exist). | Corrected to `tools/scheduled-tasks/wake_launcher.ps1` everywhere, with explanatory note that v2 inherited this drift from a prior planning doc. |
| R3 | `RECOVERY.md`, `ROLLBACK_NOVICE_GUIDE.md` (§6 + Panic Card), `01_STAGE0_PREFLIGHT.xml` (0.6, 0.6.v2, 0.7, rollback, LA-verify), `05_STAGE4_CUTOVER.xml` (verification cmds), `07_STAGE6_HARDENING.xml` (6.7.v2 monitoring + soak verify) | Filter `Where-Object { $_.TaskName -like 'BlarAI*' }` returns 0 because live tasks use Title Case Spaces (e.g. `Wake SDO`). | Switched all filters to `Get-ScheduledTask -TaskPath '\BlarAI\'` and updated expected counts to 13. |
| R4 | `03_STAGE2_REFACTOR_MULTIPROJECT.xml` (2.5.v2) | Broken PowerShell ternary `($env:VAR, 'default' -ne $null)[0]` (returns array of non-nulls; brittle) and wrong wake_launcher verify path. | Replaced with idiomatic `$(if ($env:VAR) { $env:VAR } else { 'default' })`; verify path corrected. |
| R5 | `03_STAGE2_REFACTOR_MULTIPROJECT.xml` (2.8), `04_STAGE3_COPY_TOOLS.xml` (3.7), `05_STAGE4_CUTOVER.xml` (4.7) | `<BLARAI_PID>` literal placeholders (Risk C1) with no defined substitution flow. | Replaced with explicit preflight that resolves `$BLARAI_PID` from `BlarAI/.platform/vikunja_project_ids.yaml` via `Select-String`; throws if missing. Stage 4.7 also injects `--project-root` / `--project-id` into task `<Arguments>` only when not already present. |
| R6 | `03_STAGE2_REFACTOR_MULTIPROJECT.xml` (2.2) | `_project_context.py` shipped as `...` stub (Risk C2/C5). | Replaced with full \~70-line working implementation: 5-tier resolution order (cli → env → walk-up registry → walk-up `.git` → fallback); rejects bool `project_id` (Risk C3); uses PyYAML; explicit error on missing registry. |
| R7 | `05_STAGE4_CUTOVER.xml` (4.6.5 NEW; 4.10 demoted) | Bridge daemon was started AFTER scheduled tasks were re-enabled, so any wake_* task firing immediately after 4.8 ran without bridge sync. | Inserted new item **4.6.5** that starts the bridge from devplatform BEFORE 4.7 (XML rewrite) and 4.8 (task enable). Item 4.10 demoted to a re-verify health check. |
| R8 | `05_STAGE4_CUTOVER.xml` (4.8) | Fictional task name `BlarAI_wake_sdo` in the example `Enable-AndVerify-Task` call. | Replaced with real Title Case Spaces names (`Wake SDO`, etc.), and `Enable-AndVerify-Task` now accepts/uses `-TaskPath '\BlarAI\'`. |
| R9 | `05_STAGE4_CUTOVER.xml` (line 397), `07_STAGE6_HARDENING.xml` (line 30) | `Get-Process python | Where-Object { $_.CommandLine -match ... }` always returns nothing (Get-Process has no CommandLine property). | Switched to `Get-CimInstance Win32_Process -Filter "Name = 'python.exe'"`. |
| R10 | `06_STAGE5_CLEANUP.xml` (5.10) | Plan auto-merged `chore/platform-extraction` to `main` without Lead Architect approval, violating repo policy. | Item 5.10 now commits on the working branch, prints diff + test baseline, and HALTS with explicit Lead Architect approval gate before the merge block runs. |
| R11 | `VERIFICATION_COMMANDS.md` | Mixed correct and broken filters/paths in the LA-runnable smoke commands. | Normalized to TaskPath filter, correct wake_launcher path, CIM-based bridge probe. |
| R12 | `03_STAGE2_REFACTOR_MULTIPROJECT.xml` (2.4.v2), `05_STAGE4_CUTOVER.xml` (4.7, 4.7.6, NEW 4.7.7), `06_STAGE5_CLEANUP.xml` (NEW 5.0.5) | Workflow-integrity audit (`WORKFLOW_INTEGRITY_REVIEW.md`, 2026-04-24) found four breaking gaps + two architectural smells: **G-1** four PS1 scripts (`agents-cadence-monitor`, `la_merge_approve`, `escalation_watchdog`, `toast_watchdog`) retain hardcoded `$RepoRoot = 'C:\Users\mrbla\BlarAI'` and were absent from the Stage 2 refactor scope; **G-2** Stage 4.7 substring-replace only matched `\tools\` and `\.venv\` — bare `<WorkingDirectory>C:\Users\mrbla\BlarAI</WorkingDirectory>` was untouched, so `python -m tools.X` invocations resolved against the dormant BlarAI tree, producing a false-green smoke test that breaks at Stage 5 deletion (\~24-72h delay); **G-3** vikunja-autostart form (scheduled-task vs Startup `.lnk`) was ambiguous; **G-4** `la_merge_approve.ps1` is invoked outside the scheduled-task harness so XML-injected `--project-root` cannot save it; **S-1** `blarai_next_task_resolver.py` referenced at `tools/fleet_ops/` in Stage 2.4.v2 but actually lives under `tools/autonomy_budget/`; **S-2** audit logs lost in Stage 5 recursive deletion. | (a) Stage 2.4.v2 `<additional_tools>` extended with the 4 PS1 scripts + a canonical `-BlarAIRoot` signature pattern, and the resolver path corrected to `tools/autonomy_budget/`; (b) Stage 4.7 substitution loop now also rewrites `<WorkingDirectory>C:\Users\mrbla\BlarAI</WorkingDirectory>` via lookbehind/lookahead regex (does not touch `-BlarAIRoot 'C:\Users\mrbla\BlarAI'` target-project args); (c) Stage 4.7.6 scan extended from 1 to all 5 PS1 scripts; (d) NEW Stage 4.7.7 enumerates Vikunja-related scheduled tasks anywhere in the task tree and throws if any still reference BlarAI; (e) NEW Stage 5.0.5 archives `*.log`/`*.jsonl`/`*.json.bak`/`state.json*`/`*.history` from the 6 about-to-be-deleted dirs into a timestamped zip under `.platform/audit_archive/` before 5.1 runs. |

**Outstanding (deferred to Lead Architect triage):** §1 risks **C2** (full reference impl for `_vikunja_client.py` — only `_project_context.py` shipped in this pass), **C4** (`vikunja_mcp/server.py` audit), **C6** (broader grep audit script), and §0.5 risks **V1**, **V8** are unchanged.

---

## §1 — CRITICAL: cross-file logic gaps (must address before execution)

### C1 — `<BLARAI_PID>` placeholder has no defined substitution flow
- **Where it appears**: Stage 2.8 smoke test, Stage 3.7 smoke test, Stage 4.7 task-arg rewrite.
- **Where it is set**: Stage 1.5 writes `BlarAI/.platform/vikunja_project_ids.yaml`.
- **Gap**: No prompt instructs the EA to read that yaml and substitute. EA will hand-edit and may guess.
- **Fix**: Add a `<known_constants>` section at the top of every stage prompt that resolves placeholders from a single source-of-truth file at run time, e.g.:
  ```yaml
  BLARAI_PID: $(yq '.blarai' BlarAI/.platform/vikunja_project_ids.yaml)
  ```

### C2 — `_vikunja_client.py` and `_project_context.py` are pseudocode stubs
- Stage 2.1 and 2.2 contain `def list_tasks(self, *, project_id: int, **filters): ...` with bodies replaced by comments like `# ... delegate to underlying HTTP client ...`.
- The EA must invent: (a) HTTP library (requests vs httpx), (b) auth header source, (c) base URL config, (d) error envelope, (e) project-membership check for `get_task`.
- **Risk**: Two future EAs implementing this differently → drift between BlarAI tests and devplatform runtime.
- **Fix**: Stage 2 should ship full reference implementations with passing tests, not pseudocode.

### C3 — §D.1 boolean bypass
- `_require_project_id` checks `isinstance(project_id, int)`. In Python, `isinstance(True, int) == True`. So `client.list_tasks(project_id=True)` passes the gate and queries Vikunja project ID 1.
- **Fix**: Add `and not isinstance(project_id, bool)` to the guard, plus a unit test:
  ```python
  def test_list_tasks_rejects_bool():
      with pytest.raises(ProjectScopeError):
          client.list_tasks(project_id=True)
  ```

### C4 — §D.1 not enforced on the MCP server entrypoint
- Stage 2.4 enumerates CLI tools to refactor but omits `tools/vikunja_mcp/server.py` (the MCP server invoked by Claude Desktop). If `list_tasks` and `search_tasks` MCP tool handlers don't route through `_vikunja_client`, an LLM can still issue scope-leaking queries from a Claude session.
- **Fix**: Add `vikunja_mcp/server.py` (and any FastMCP/JSON-RPC handlers) to the Stage 2.4 audit list, and route every Vikunja-touching tool handler through the new client.

### C5 — `_project_context.resolve()` default is undefined
- Stage 2 says "defaults preserve current behavior" if `--project-root`/`--project-id` are not passed. But `resolve()` is empty pseudocode.
- If EA defaults to `Path.cwd()`, scheduled tasks running from `C:\Windows\System32` will fail to resolve.
- **Fix**: Specify the default explicitly (e.g., walk parents looking for `.platform/vikunja_project_ids.yaml`, fall back to env var `BLARAI_PROJECT_ROOT`).

### C6 — Stage 2.6 grep patterns miss real-world variants
- Listed: `requests.*localhost:3456`, `/api/v1/projects/.*/tasks`, `/api/v1/tasks/all`.
- Misses: `httpx`, `aiohttp`, `urllib`, `127.0.0.1:3456`, env-var-driven base URLs (`os.environ["VIKUNJA_URL"]`), templated f-strings (`f"{base}/api/v1/tasks/all"`), websocket clients.
- **Fix**: Replace pattern list with a single audit script that greps for `3456|/api/v1/(tasks|projects)` and requires the EA to triage every hit.

### C7 — Stage 4.4/4.5/4.6 backups asymmetric
- Only 4.4 (Claude Desktop) has `<backup_before_edit>`. 4.5 (`.vscode/mcp.json`) and 4.6 (`.mcp.json`) have no pre-edit backup.
- **Fix**: Add backup commands to 4.5 and 4.6 mirroring 4.4. Suggested:
  ```powershell
  Copy-Item C:\Users\mrbla\BlarAI\.vscode\mcp.json C:\Users\mrbla\BlarAI\.vscode\mcp.json.pre_stage4_bak
  Copy-Item C:\Users\mrbla\BlarAI\.mcp.json C:\Users\mrbla\BlarAI\.mcp.json.pre_stage4_bak
  ```

### C8 — Stage 4.7 path replace does not add new CLI args
- Description says scheduled tasks should pick up `--project-root C:\Users\mrbla\BlarAI --project-id <BLARAI_PID>`, but the `-replace` regex only swaps the BlarAI path for the devplatform path.
- **Risk**: Tasks run with no `--project-id`, hit `_project_context.resolve()`'s default, and either fail or operate on wrong project.
- **Fix**: After the path swap, parse the `<Arguments>` element of each task XML and inject `--project-root` and `--project-id` if not already present.

### C9 — Bridge daemon ordering (Stage 4.10) is too late
- Scheduled tasks are enabled in 4.8 and may fire before the bridge starts in 4.10. Tasks invoking fleet tools that require the bridge will fail their first run.
- **Fix**: Move bridge start to 4.6.5 (between MCP repointing and scheduled-task work).

### C10 — Stage 4 has no per-substep go/no-go gate
- The cutover is 13 contiguous items. If 4.7 partially fails, the rollback section says "use level-3 rollback" but no item explicitly says "STOP here, run verify, decide go/no-go".
- **Fix**: Insert explicit `<gate>` checkpoints between logical groups: (4.1–4.3 DB), (4.4–4.6 MCP configs), (4.7–4.8 scheduled tasks), (4.9–4.11 daemons + smoke).

---

## §2 — MAJOR: code & command bugs in embedded snippets

### M1 — Stage 4.1 risks DB clobber and corruption
- `Move-Item -Force` overwrites destination with no warning. If a stale `vikunja.db` exists at the devplatform path, it is silently replaced.
- The pre-move "stop Vikunja" assumption rests on Stage 0.4 (possibly days old). Vikunja may have been restarted manually since.
- **Fix**:
  ```powershell
  if (Test-Path "C:\Users\mrbla\devplatform\tools\vikunja\vikunja.db") {
    throw "Destination exists; aborting to avoid clobber."
  }
  Get-Process vikunja* -ErrorAction SilentlyContinue | Stop-Process -Force
  $srcHash = (Get-FileHash "C:\Users\mrbla\BlarAI\tools\vikunja\vikunja.db" -Algorithm SHA256).Hash
  Copy-Item "C:\Users\mrbla\BlarAI\tools\vikunja\vikunja.db" "C:\Users\mrbla\BlarAI\tools\vikunja\vikunja.db.cutover_bak"
  Move-Item "C:\Users\mrbla\BlarAI\tools\vikunja\vikunja.db" "C:\Users\mrbla\devplatform\tools\vikunja\vikunja.db"
  $dstHash = (Get-FileHash "C:\Users\mrbla\devplatform\tools\vikunja\vikunja.db" -Algorithm SHA256).Hash
  if ($srcHash -ne $dstHash) { throw "DB hash mismatch after move." }
  # Also: PRAGMA integrity_check via sqlite3.exe if available
  ```
- Also handle `files/` attachment directory (Vikunja default) — the prompt only mentions it parenthetically with no command.

### M2 — Stage 4.2 `Start-Sleep 3` is not adequate cold-start wait
- Vikunja with a sizable DB may take >3s to begin serving. Hardcoded sleep masks transient errors.
- **Fix**: Polling loop:
  ```powershell
  $deadline = (Get-Date).AddSeconds(30)
  while ((Get-Date) -lt $deadline) {
    try { Invoke-RestMethod http://localhost:3456/api/v1/info -TimeoutSec 2 | Out-Null; break }
    catch { Start-Sleep -Milliseconds 500 }
  }
  ```

### M3 — Stage 4.7 `Register-ScheduledTask -Xml` may fail on BOM
- `Export-ScheduledTask` historically emits XML with a UTF-16 BOM. `Register-ScheduledTask -Xml $xml` requires a clean string. The current code reads with `Get-Content -Raw` (preserves BOM).
- **Fix**: Strip BOM:
  ```powershell
  $xml = (Get-Content $taskXmlPath -Raw) -replace "^\uFEFF",""
  ```

### M4 — Stage 4.8 `LastTaskResult = 267009` interpreted as failure
- 267009 means "task is still running" — common for weekly_summary / sprint_auditor which run >10s.
- The current "Start-Sleep 10" + `LastTaskResult ≠ 0` check will report false failures.
- **Fix**: Wait for `State -eq 'Ready'` and `LastTaskResult -ne 267009` before judging:
  ```powershell
  do { Start-Sleep 2; $info = Get-ScheduledTaskInfo $name } while ($info.LastTaskResult -eq 267009)
  if ($info.LastTaskResult -ne 0) { throw "Task $name failed: $($info.LastTaskResult)" }
  ```

### M5 — Stage 4.9 `.lnk` editing is hand-waved
- "Update its target path" with no command. `.lnk` is a binary OLE file; editing requires `WScript.Shell` COM.
- **Fix**: Provide the COM snippet:
  ```powershell
  $sh = New-Object -ComObject WScript.Shell
  $sc = $sh.CreateShortcut("$env:APPDATA\Microsoft\Windows\Start Menu\Programs\Startup\Vikunja.lnk")
  $sc.TargetPath = "C:\Users\mrbla\devplatform\tools\vikunja\vikunja-v2.3.0-windows-4.0-amd64.exe"
  $sc.WorkingDirectory = "C:\Users\mrbla\devplatform\tools\vikunja"
  $sc.Save()
  ```

### M6 — Stage 4.10 bridge start is not durable
- `python -m tools.vikunja_mcp.bridge --verbose` runs in foreground; closing the terminal kills it.
- **Fix**: `Start-Process` with redirected logs, or register as a scheduled task `At log on`.

### M7 — Stage 4.11 "open a fresh Claude Desktop session" is non-scriptable
- A manual UI step that the EA cannot programmatically verify.
- **Fix**: Replace with a CLI MCP probe (e.g., `npx @modelcontextprotocol/inspector` against the configured server) OR mark as Lead-Architect manual gate.

### M8 — Stage 0.7 disable verification has timing window
- `Disable-ScheduledTask` returns before task scheduler refreshes. Immediate re-query may show old state.
- **Fix**: After disabling, `Start-Sleep 1; Get-ScheduledTask | Where-Object State -ne 'Disabled'`.

### M9 — Stage 5.3 `<move>` elements are documentation only
- `<move from="..." to="..."/>` XML elements have no executor. EA will not run anything unless `Move-Item` commands are explicit.
- **Fix**: Replace with explicit `<command>Move-Item ... -Force</command>` blocks.

### M10 — Stage 5.4 hides a multi-file refactor as a one-liner
- "Update devplatform fleet tools to look in `.platform/` for coordination files" — but no list of files, no grep, no patches.
- This is a sizable refactor that touches many tools and runs against now-live devplatform.
- **Fix**: Decompose 5.4 into (a) audit script that lists every reference, (b) per-file patch list, (c) regression test invocation.

---

## §3 — MEDIUM: process maturity opportunities

| ID | Recommendation |
|----|----------------|
| P1 | Add `<known_constants>` block at top of every stage prompt that resolves `<BLARAI_PID>`, `<DEVPLATFORM_META_PID>`, `<VIKUNJA_TOKEN>`, etc. from a single source-of-truth file. Eliminates EA guessing. |
| P2 | Add `-WhatIf`/dry-run mode to all PowerShell blocks in Stage 4. Lead Architect can dry-run cutover end-to-end before committing. |
| P3 | Pre-write `rollback_stage4.ps1` script that executes the level-3 rollback in one command (stop devplatform Vikunja, restore DB from `.cutover_bak`, restore MCP backups, restart BlarAI Vikunja, re-disable tasks). Beats narrative rollback under pressure. |
| P4 | Capture session log per stage to `docs/platform_separation/session_logs/stage{N}_{timestamp}.log` via `Start-Transcript`. Forensic audit trail. |
| P5 | Add explicit "branch sanity" check at the top of each stage: `if ((git branch --show-current) -ne 'chore/platform-extraction') { throw "Wrong branch." }`. Prevents accidental main commits between sessions. |
| P6 | After Stage 4 cutover, re-run `pytest tools/tests/test_vikunja_client_scope.py` from devplatform to confirm §D.1 wrapper still active. Currently no post-cutover regression test. |
| P7 | Stage 4.0 should declare a "Vikunja write quiescence window" formally — no Claude session, no UI access, no MCP traffic — and verify with a short polling loop that `LastWriteTime` of the DB has not changed for ≥5 seconds before move. |
| P8 | Add a "deprecation cycle" for §D.1: emit `DeprecationWarning` for one cycle when `project_id` is omitted, before raising `ProjectScopeError`. Otherwise rare scheduled tasks crash hard on first run. |
| P9 | After Stage 5 cleanup, run `Get-ChildItem C:\Users\mrbla\BlarAI -Recurse -Filter "*.py" \| Select-String "BlarAI\\tools\\(vikunja\|fleet)"` to confirm no residual import. |
| P10 | Tag the head of `chore/platform-extraction` immediately before the Stage 5.10 merge to main. Allows clean revert of the merge if soak surfaces issues. |
| P11 | Stage 3.4 should provide an explicit dependency list (or instruct `pip freeze` minus a known runtime list), not "filter to what platform tools need". |
| P12 | Stage 3.6 secret handling should specify `[Environment]::SetEnvironmentVariable("VIKUNJA_PASS", "x", "User")` for persistence across VS Code restarts, not session-scoped `$env:VIKUNJA_PASS`. |

---

## §4 — Cutover Atomicity Verdict

> *"Is the cutover properly handled?"*

**Answer: Not yet.** Stage 4 in current form has these atomicity weaknesses:

1. **No pre-move DB integrity capture** (hash, row counts, `PRAGMA integrity_check`).
2. **No pre-move clobber check** at destination.
3. **Asymmetric backups** across 4.4/4.5/4.6 (only 4.4 backs up).
4. **Path-replace + arg-injection** are conflated in 4.7 but only path-replace is implemented.
5. **No explicit go/no-go gates** between logical sub-groups.
6. **Bridge daemon ordering** allows scheduled tasks to fire before bridge is up.
7. **Cold-start waits are hardcoded** (3s) rather than polling-with-deadline.
8. **`LastTaskResult` interpretation** does not handle "task still running" (267009).
9. **No rollback automation** — narrative-only, error-prone under pressure.
10. **Manual UI probes** (Claude Desktop verify in 4.11) are unverifiable by the EA.

**Recommendation**: Apply C7, C8, C9, C10, M1, M2, M3, M4, M5, M6, P3 before executing Stage 4. The other items are improvements but not blockers.

---

## §5 — Suggested follow-up patches (not yet applied; awaiting Lead Architect decision)

These are the high-confidence fixes I am comfortable applying autonomously to source XMLs in a follow-up turn:

- C3 (boolean bypass guard)
- C7 (4.5/4.6 backups)
- M1 (4.1 hash + clobber check + Vikunja stop verify)
- M2 (4.2 polling loop)
- M3 (4.7 BOM strip)
- M4 (4.8 wait-for-state)
- M5 (4.9 .lnk COM script)
- M8 (0.7 disable timing fix)
- M9 (5.3 explicit Move-Item commands)
- P5 (branch sanity check at top of each stage)

Items requiring design input before patching:
- C1 / P1 (constants resolution mechanism)
- C2 (real `_vikunja_client.py` implementation)
- C4 (MCP server entrypoint inclusion in §D.1 enforcement)
- C5 (`resolve()` default behavior)
- C6 (audit script pattern strategy)
- C8 (CLI arg injection logic for scheduled tasks)
- C9 (bridge ordering — confirms 4.6.5 placement OK?)
- C10 (gate placement granularity)
- P2 (dry-run feasibility per command)
- P3 (`rollback_stage4.ps1` content review)

---

**End of audit.**
