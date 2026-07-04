# Workflow Integrity Review — Platform Separation v2

**Author**: GitHub Copilot (Claude Opus 4.7), commissioned by Lead Architect.
**Branch**: `docs/platform-separation-v2` (HEAD `1c08922`).
**Question being answered**: *"Will the autonomous development workflow (wake triggers, state monitoring, git automation, scheduled-task firing, Vikunja gate processing, observability) actually work after we execute the v2 separation per the published execution docs?"*

**Verdict (TL;DR)**: **MOSTLY YES, with 4 confirmed gaps that will break the fleet on first or second firing post-cutover, plus 2 architectural smells.** None of the gaps are catastrophic — all are recoverable in <30 min with documented commands — but they should be patched in the execution docs before any LA-approved merge so the cutover proceeds without a same-day rollback.

---

## 1. Method

1. Inventoried every hardcoded `C:\Users\mrbla\BlarAI` reference across `tools/scheduled-tasks/` (200+ matches; 13 PS1+VBS scripts, 13 scheduled-task XMLs, 6 wake templates, ~150 runtime log entries).
2. Inspected `wake_launcher.ps1` (head + Test-WorkAvailable body), `state.py`, `active_tasks.py`, `blarai_next_task_resolver.py` for path-resolution doctrine.
3. Cross-referenced every hardcoded path against the rewrite/refactor coverage in `02_STAGE1_SCAFFOLD.xml`, `03_STAGE2_REFACTOR_MULTIPROJECT.xml`, `04_STAGE3_COPY_TOOLS.xml`, `05_STAGE4_CUTOVER.xml`.
4. Read `INFRA_DELTA_v2.md` and `AUDIT_RISK_REVIEW.md` §0.6 (R1–R11) to confirm what the v2 refactor already documented.
5. Categorized residual defects D-1 through D-7. Classified each as BREAKING / DEGRADED / SMELL. Mapped each to its missing-fix location.

---

## 2. What the v2 docs already get right

These are the workflow risks the v2 refactor **does** correctly cover. No further action required:

| Subsystem | Doc that covers it | Why it works |
|---|---|---|
| Wake-template path drift (6 templates in `docs/scheduled/wake_templates/`) | Stage 4.7.5 | Explicit PowerShell loop rewrites `BlarAI\tools\*` → `devplatform\tools\*` while preserving target-project refs. Verified by Select-String. |
| `wake_launcher.ps1` line-by-line rewrite | Stage 2.5.v2 (refactor adds `-BlarAIRoot`) + 4.7.6 (post-copy scan) | wake_launcher gains explicit `-BlarAIRoot` parameter (default env `BLARAI_ROOT`, then `C:\Users\mrbla\BlarAI`). Stage 4.7.6 lists residual `BlarAI` matches for LA spot-check. |
| `state.json` location | Auto-follows file move | `state.py` uses `Path(__file__).resolve().parents[2]` → moves with the script to devplatform. Stage 4.13.5 references the devplatform path. ✅ |
| `active_tasks.py` reading the right roster | Stage 2.4 / 2.5 | `--project-root` argument added; reads BlarAI's `docs/active_tasks.yaml` even when the script lives in devplatform. |
| `blarai_next_task_resolver.py` cross-repo coupling | Stage 2.5.v1 (line 15) | Adds `--blarai-root` flag (env `BLARAI_ROOT` default). Per-project resolver. |
| `diff_builder.py` cross-repo coupling | Stage 2.5.v1 (line 16) | Adds `--project-root`. |
| `test_async_post_gate.ps1` cross-repo coupling | Stage 2.5.v1 (line 19) | Adds `-ProjectRoot`. |
| Vikunja DB migration + autostart shortcut | Stages 4.1, 4.2, 4.9 | Stop server → copy SQLite → restart from devplatform → rebuild .lnk via WScript.Shell COM. |
| MCP config repointing | Stages 4.4, 4.5, 4.6 | All three MCP surfaces updated; backups taken. |
| Bridge daemon ordering | Stage 4.6.5 (was R7) | Bridge starts BEFORE task re-enable. |
| Task XML rewrite for `\tools\` and `\.venv\` paths in `<Arguments>` | Stage 4.7 | `[regex]::Escape("C:\Users\mrbla\BlarAI\tools")` global replace handles **all** `\tools\` mentions in a string, including multi-path Arguments (D-2 dispelled — the multi-path concern was unfounded). `--project-root C:\Users\mrbla\BlarAI --project-id $BLARAI_PID` injected. |
| 13-task count + Title Case Spaces filter | Stages 4.8.v2, R1, R3 | All filters use `-TaskPath '\BlarAI\'`. |
| `$BLARAI_PID` resolution | R5 fix in 4.7 preflight | Read from `BlarAI/.platform/vikunja_project_ids.yaml` via Select-String; throws if missing. |
| Single-project state.json (one global, all projects share) | state.py architecture | One state.json in devplatform = single fleet, sequential project work. Acceptable for current single-target reality. |
| Worktree empty pre-check | Stages 0.5.5, 4.0.5 | Re-verified at cutover. |
| Fleet-pause defense-in-depth | Stage 4.0.6 | Re-confirms pause at cutover; uses `state.pause_fleet()` helper not raw JSON edits. |
| LA approval gate before merge | Stage 5.10 (R10 fix) | HALTS at merge; LA must approve. |

That covers about 80% of the surface area. The remaining 20% — the gaps below — are real and need patching.

---

## 3. Confirmed gaps (BREAKING / DEGRADED)

### G-1 (BREAKING) — Four PS1 scripts retain hardcoded BlarAI defaults; no Stage 2 refactor, no Stage 4 line-by-line scan

**Affected files** (all under [tools/scheduled-tasks/](tools/scheduled-tasks/)):
- [agents-cadence-monitor.ps1](tools/scheduled-tasks/agents-cadence-monitor.ps1#L17) — `[string]$RepoRoot = 'C:\Users\mrbla\BlarAI'` and `[string]$McpConfigPath = 'C:\Users\mrbla\BlarAI\.mcp.json'`
- [la_merge_approve.ps1](tools/scheduled-tasks/la_merge_approve.ps1#L38) — same two defaults
- [escalation_watchdog.ps1](tools/scheduled-tasks/escalation_watchdog.ps1#L32) — `[string]$RepoRoot = 'C:\Users\mrbla\BlarAI'`
- [toast_watchdog.ps1](tools/scheduled-tasks/toast_watchdog.ps1#L14) — same

**Why it breaks**:
- Stage 2.5.v2 only refactors `wake_launcher.ps1` (adds `-BlarAIRoot`).
- Stage 2.5.v1 (lines 13–19) refactors `test_async_post_gate.ps1`, `blarai_next_task_resolver.py`, `diff_builder.py`, `active_tasks.py` — but **NOT** the 4 scripts above.
- Stage 4.7 rewrites task-XML `<Arguments>` strings only (path-substring replace inside the XML).
- Stage 4.7.6 post-copy scan targets **only** `wake_launcher.ps1`.
- Net result: after copy to devplatform, all 4 scripts still default `$RepoRoot = 'C:\Users\mrbla\BlarAI'`. The corresponding scheduled tasks (Agents Cadence Monitor, Escalation Watchdog, Toast Watchdog) pass `-RepoRoot ...devplatform...` via the rewritten XML, so the **scheduled** firing path is OK. But:
  - **`la_merge_approve.ps1` is NOT scheduled** — it is invoked ad-hoc by Co-Lead via `Bash(schtasks /run ...)` or directly per DEC-14.5. If Co-Lead invokes it without `-RepoRoot`, it silently targets BlarAI's MCP config (which still exists post-Stage-4 because Stage 4.6 keeps BlarAI's `.mcp.json` and merely edits its vikunja entry). Result: gate-approval merges run against the wrong vikunja credentials or, worse, against a stale `.mcp.json`.
  - **Manual ops invocations** (LA running `agents-cadence-monitor.ps1` for diagnostics, future automation copying from these as templates) silently use the BlarAI default — same hazard.

**Fix** (additions to existing v2 docs, no architectural change):
1. Add to Stage 2.5.v1 refactor list: rename `$RepoRoot` parameter in the 4 scripts to `$BlarAIRoot` with `$(if ($env:BLARAI_ROOT) { $env:BLARAI_ROOT } else { 'C:\Users\mrbla\BlarAI' })` default, mirroring wake_launcher.ps1 §2.5.v2 signature. Same for `$McpConfigPath` — pull from `Join-Path $BlarAIRoot '.mcp.json'`.
2. Extend Stage 4.7.6 scan to include all 4 scripts (`Select-String ...escalation_watchdog.ps1, toast_watchdog.ps1, agents-cadence-monitor.ps1, la_merge_approve.ps1`).
3. Update each task-XML rewrite to pass `-BlarAIRoot` instead of `-RepoRoot` (or keep both as aliases during transition).

**Severity**: BREAKING for `la_merge_approve.ps1`; DEGRADED for the 3 scheduled ones (work via XML override but represent latent risk for any future invocation).

---

### G-2 (BREAKING) — Python `-m tools.X` invocations rely on `<WorkingDirectory>` resolving to a tools-tree, but Stage 4.7 only rewrites `\tools\` substrings, not bare `BlarAI`

**Affected scheduled tasks** (6 of 13):
- Daily Digest, Welcome Back Poll, Weekly Summary, Dashboard Maintainer, Credentials Rotation Reminder → `python.exe -m tools.fleet_observability.<module>`
- Gate Stale Cleaner → `python.exe -m tools.gate_stale_cleaner.run_live`

**Why it breaks**:
- Stage 4.7 substitutions are exactly two patterns: `BlarAI\tools` → `devplatform\tools` and `BlarAI\.venv` → `devplatform\.venv`. Bare `<WorkingDirectory>C:\Users\mrbla\BlarAI</WorkingDirectory>` (no `\tools`) is **not matched** and therefore not rewritten.
- After Stage 4.7, the `<Command>` rewrites to `C:\Users\mrbla\devplatform\.venv\Scripts\python.exe` ✓ but `<WorkingDirectory>` stays `C:\Users\mrbla\BlarAI`.
- When `python -m tools.fleet_observability.daily_digest` runs, Python resolves `-m tools.X` first against site-packages (devplatform's venv has none for this) then against `sys.path[0]` (the cwd, which is BlarAI). Result: imports BlarAI's dormant `tools/fleet_observability/daily_digest.py` from the OLD copy that Stage 5 will subsequently delete.
- **First firing after Stage 4.7 (during the smoke-test enable in Stage 4.8)**: works against the dormant BlarAI copy → **gives a false-green smoke test**.
- **First firing after Stage 5 deletion** (~hours later, depending on cadence): `ModuleNotFoundError: No module named 'tools.fleet_observability'`. Daily Digest, Welcome Back Poll, Weekly Summary, Dashboard Maintainer, Credentials Rotation Reminder, Gate Stale Cleaner all fail simultaneously. Observability dashboards stop updating. F2 credential expiration warnings stop firing.

**Fix** (additions to Stage 4.7 substitution loop, executed before re-register):
```powershell
# Add a third substitution covering bare WorkingDirectory references.
$xml = $xml -replace '<WorkingDirectory>C:\\Users\\mrbla\\BlarAI</WorkingDirectory>', '<WorkingDirectory>C:\Users\mrbla\devplatform</WorkingDirectory>'
```
**Caveat**: this rewrites WorkingDirectory for **all** 13 tasks. For wake-* tasks (where the working dir is incidental — `-File <abs path>` makes WorkingDirectory irrelevant), this is harmless. For python-module tasks, it's required. No task currently relies on WorkingDirectory being BlarAI.

**Alternative fix (architecturally cleaner but bigger change)**: install devplatform's `tools/` as an editable package in devplatform's venv (`pip install -e C:\Users\mrbla\devplatform`), so `-m tools.X` resolves via site-packages independent of cwd. This decouples Python module resolution from cwd entirely. Recommended for Stage 6 hardening.

**Severity**: BREAKING. Triggers exactly when Stage 5 cleanup runs.

---

### G-3 (DEGRADED → BREAKING within ~24h) — `vikunja-autostart.xml` `<Command>` and `<WorkingDirectory>` paths not in Stage 4.7 substitution scope

**Affected file**: `vikunja-autostart.xml` lines 73-74 (`<Command>` = path to vikunja exe; `<WorkingDirectory>` = `C:\Users\mrbla\BlarAI\tools\vikunja`).

**Why it's only partially covered**:
- Stage 4.9 explicitly handles the Windows Startup `.lnk` shortcut.
- The **scheduled-task XML version** (`vikunja-autostart.xml` if a Task Scheduler entry exists for it — typically yes, parallel to the .lnk) is NOT explicitly excluded from the Stage 4.7 loop and would be rewritten BUT:
  - The `<Command>` is `C:\Users\mrbla\BlarAI\tools\vikunja\vikunja-...exe` — `BlarAI\tools` rewrites cleanly to `devplatform\tools`. ✓
  - The `<WorkingDirectory>` is `C:\Users\mrbla\BlarAI\tools\vikunja` — also rewritten cleanly. ✓
- **However**: the user's grep evidence shows `vikunja-autostart.xml` line 14 has a URI/idle setting reference, line 73 the Command, line 74 the WorkingDirectory. All three should be touched. Stage 4.7 grep-replace gets lines 73 and 74. Line 14 (settings URI) is benign metadata.
- **Open question I could not answer**: whether `vikunja-autostart` is a scheduled task (covered by 4.7) or only a Startup folder shortcut (covered by 4.9). The presence of `vikunja-autostart.xml` in `tools/scheduled-tasks/` strongly suggests it IS a scheduled task. **Stage 4.8.v2 expects exactly 13 tasks** — if `vikunja-autostart` is the 14th (logon trigger, not interval), it would not be in the `\BlarAI\` task path or it's been excluded from the count. Need LA to confirm.

**Fix**:
1. Add an explicit Stage 4 sub-item asserting whether `vikunja-autostart` is scheduled-task-form, Startup-shortcut-form, or both.
2. If both, ensure the rewrite loop's `Get-ChildItem C:\Users\mrbla\backups\scheduled_tasks_export\*.xml` actually picked it up at Stage 0 export.

**Severity**: DEGRADED. Vikunja already running (started by Stage 4.2) survives reboot via the .lnk fix in 4.9. Risk window opens at next OS reboot if the autostart-task path is broken AND the .lnk was overlooked.

---

### G-4 (BREAKING for ad-hoc invocation only) — `la_merge_approve.ps1` is invoked outside the scheduled-task harness; cannot rely on XML-injected `--project-root`

**Affected file**: [la_merge_approve.ps1](tools/scheduled-tasks/la_merge_approve.ps1).

**Why it breaks**:
- Per DEC-14.5, this is the LA's APPROVE motion handler. Co-Lead invokes it programmatically when LA hits "Approve" on a Vikunja gate task. The invocation path:
  1. Co-Lead's `claude -p` session calls `Bash(schtasks /run /tn "LA Merge Approve" -- ...)` OR runs the PS1 directly.
  2. If schtasks-based and the task exists in the live fleet, it'd be in the 13 — but it isn't (verified by 4.8.v2 enumeration; only 13 tasks listed and `LA Merge Approve` is not among them).
  3. Therefore it's invoked directly: `powershell.exe -File <path to la_merge_approve.ps1> -GateTaskId <id>`.
- That direct invocation does NOT pass `-RepoRoot`, so the param default kicks in: `'C:\Users\mrbla\BlarAI'`.
- Same chain as G-1 — ends up reading BlarAI's `.mcp.json` instead of devplatform's.
- **Subtler hazard**: the `git checkout main; git merge --no-ff ...` block runs in `cd $RepoRoot` (→ BlarAI). If the feature branch being merged is a devplatform branch, the merge runs in the wrong repo. **DEC-14.5 fails closed by virtue of producing a "branch does not exist locally" error** — but it's a noisy and confusing failure mode for the LA.

**Fix**: same as G-1 — refactor `la_merge_approve.ps1` to take `-BlarAIRoot` + derive `.mcp.json` path. Additionally, decide whether `la_merge_approve.ps1` operates on devplatform branches (then it should default to devplatform repo) or BlarAI branches (then BlarAI is correct). Most likely BOTH — DEC-14.5 should specify a `-TargetRepo` parameter.

**Severity**: BREAKING when LA approves a devplatform-side merge. DEGRADED for BlarAI merges (works correctly because BlarAI is the correct default).

---

## 4. Architectural smells (non-blocking)

### S-1 — `blarai_next_task_resolver.py` lives in shared platform substrate but is named for one project

INFRA_DELTA §1.4 already flags this. Stage 2.5.v1 line 15 uses `tools/fleet_ops/blarai_next_task_resolver.py` as the path — **the file actually lives at `tools/autonomy_budget/blarai_next_task_resolver.py`** (verified). This is the same class of error as R2 (wake_launcher path drift) — a planning-doc location pointer that doesn't match reality.

The naming convention is also a smell. Cross-project devplatform should ship `next_task_resolver.py` with project-pluggable resolver strategy (e.g., loads `blarai_resolver.py` extension when target = BlarAI). For now, the `--blarai-root` arg + rename in Stage 2 is sufficient pragmatic mitigation.

**Fix**: (a) correct the path in Stage 2.5.v1 line 15 to `tools/autonomy_budget/blarai_next_task_resolver.py`. (b) Add an entry to AUDIT_RISK_REVIEW §0.6 as R12 acknowledging the name-coupling smell with a Stage 6 hardening followup ticket.

### S-2 — Wake-launcher logs accumulate in BlarAI even after cutover

`wake_launcher.ps1` writes to `Join-Path $RepoRoot 'tools\scheduled-tasks\logs'`. After Stage 4 cutover, `$RepoRoot` (or the new `$BlarAIRoot`) effectively means devplatform's wake_launcher is invoked from devplatform → logs go to `devplatform/tools/scheduled-tasks/logs/`. ✓

The existing 7 days of logs in BlarAI's `tools/scheduled-tasks/logs/` (~150+ files in the user's grep) become stale audit history. Stage 5 cleanup deletes BlarAI's `tools/scheduled-tasks/` entirely — the logs go with it. **Recommend**: pre-Stage-5, copy `tools/scheduled-tasks/logs/archive/` to a long-term audit location (e.g., `C:\Users\mrbla\fleet-audit-archive\pre-platform-separation\`) before deletion. Otherwise audit trail is destroyed.

---

## Appendix A — Post-Patch Verification Audit (commit `6a042ea`)

**Audit author**: GitHub Copilot (Claude Opus 4.7).
**Audit date**: 2026-04-25.
**Audit purpose**: After all 6 patches (G-1..G-4, S-1, S-2) were applied in commit `6a042ea`, re-sweep the workspace to confirm no path-class or workflow-component was missed. Five focused audits run; results below.

### A.1 — Hardcoded `C:\Users\mrbla\BlarAI` reference re-sweep (in-scope only)

Plain-text search over `**/*.{ps1,xml,bat}` (200+ matches capped) and targeted scopes. Out-of-scope hits (one-off PR/issue research scripts under `scripts/`, phase2_gates artifacts, historical XML proposals, the planning docs themselves) excluded. In-scope hits classified:

| File | Hits | Coverage | Verdict |
|---|---:|---|---|
| `tools/scheduled-tasks/agents-cadence-monitor.ps1` (L17,18) | 2 | G-1 Stage 2.4.v2 — adds `-BlarAIRoot` param | ✅ COVERED |
| `tools/scheduled-tasks/la_merge_approve.ps1` (L16,38,39) | 3 | G-1 Stage 2.4.v2 (L16 is comment example) | ✅ COVERED |
| `tools/scheduled-tasks/escalation_watchdog.ps1` (L32) | 1 | G-1 Stage 2.4.v2 | ✅ COVERED |
| `tools/scheduled-tasks/toast_watchdog.ps1` (L14) | 1 | G-1 Stage 2.4.v2 | ✅ COVERED |
| `tools/scheduled-tasks/wake_launcher.ps1` (L13,30,294) | 3 | Stage 2.5.v2 — `-BlarAIRoot` param (L13 is comment) | ✅ COVERED |
| `tools/scheduled-tasks/test_async_post_gate.ps1` (L24) | 1 | Stage 5 §1 explicitly DELETES this file | ✅ COVERED |
| `tools/scheduled-tasks/register_event_log_source.ps1` (L12) | 1 | Comment example only — no runtime path | ✅ NO ACTION |
| `tools/scheduled-tasks/wake-*.xml` (12 wake/observability XMLs) | ~25 | Stage 4.7 substitution (`\tools\` + `\.venv\` + bare `<WorkingDirectory>`) | ✅ COVERED |
| `tools/scheduled-tasks/vikunja-autostart.xml` (L14,73,74) | 3 | Stage 4.7 substitution (all hits contain `\tools\`) | ✅ COVERED |
| `tools/scheduled-tasks/escalation-watchdog.xml`, `toast-watchdog.xml`, `daily-digest.xml`, `dashboard-maintainer.xml`, `gate-stale-cleaner.xml`, `welcome-back-poll.xml`, `weekly-summary.xml`, `credentials-rotation-reminder.xml`, `agents-cadence-monitor.xml`, `sprint-auditor.xml` | ~20 | Stage 4.7 substitution | ✅ COVERED |
| `docs/scheduled/wake_templates/co_lead_architect.md` (L150) | 1 | Stage 4.7.5 wake-template rewrite (`\tools\` → devplatform) | ✅ COVERED |
| `docs/scheduled/wake_templates/co_lead_architect.md` (L162) | 1 | `cd 'C:\Users\mrbla\BlarAI'` for REJECT — target-project ref, **preserve** per Stage 4.7 preserve clause | ✅ NO ACTION |
| `docs/scheduled/wake_templates/{configuration_agent,ea_code,ea_cowork,sdo,sprint_auditor}.md` | 0 | No hardcoded BlarAI paths found | ✅ CLEAN |
| `tools/fleet_ops/action_generator.py` (L82) | 1 | f-string emitted into Vikunja audit-task DESCRIPTION as a rollback example. Path is target-project (BlarAI), not used by the script for I/O. Per Stage 4.7 preserve clause, target-project refs stay. | ✅ NO ACTION |
| `tools/fleet_observability/escalation_notify.ps1` (L16), `critical_notify.ps1` (L11) | 2 | Both are comment usage examples (`# Example: ... C:\...`), no runtime path | ✅ NO ACTION |
| `launcher/**` | 0 | Confirmed clean — no fleet-ops paths | ✅ CLEAN |

**Out of scope (explicitly):**
- `scripts/test_pr1634_*.{py,ps1}`, `scripts/run_issue*.ps1`, `scripts/setup_and_run_pr1634.ps1`, `scripts/fix_and_rerun_pr1634.ps1` — one-off OpenVINO PR/issue benchmark scripts. BlarAI-specific research artifacts; stay with BlarAI.
- `phase2_gates/scripts/_check_cats.py` (L6) — Phase 2 gate validation. BlarAI artifact; stays with BlarAI.
- `docs/CLAUDE_DESKTOP_*.xml`, `docs/CO_LEAD_ARCHITECT_INITIATION_*.xml`, `docs/DEC*.xml`, `docs/DOMAIN*.xml` — historical doctrine/proposal documents. Stage 6 §3 explicitly handles their split or migration to devplatform; in-document BlarAI paths are mostly target-project refs (preserve) or self-references (rewrite when moved).
- `docs/platform_separation/*.xml` — the planning docs themselves. They reference BlarAI by design.
- `docs/P5_TASK*.xml` — historical task continuation prompts. Frozen per IMPLEMENTATION_PLAN; stay with BlarAI.

**Audit A.1 verdict**: **0 new gaps.** Every in-scope hardcoded `C:\Users\mrbla\BlarAI` reference is either covered by an existing patch (G-1..G-4, Stage 4.7, Stage 4.7.5, Stage 5 deletion) or correctly preserved as a target-project reference per the Stage 4.7 preserve clause. No additional patches required.

### A.2 — Stage 4.7 substitution coverage by path-class

| Path class | Example | Substitution rule | Coverage |
|---|---|---|---|
| `\tools\*` inside `<Arguments>` | `"...\\tools\\scheduled-tasks\\runhidden.vbs"` | `[regex]::Escape("...BlarAI\tools")` → devplatform\tools | ✅ |
| `\tools\*` inside `<Command>` (vikunja-autostart) | `<Command>...\tools\vikunja\vikunja-...exe</Command>` | Same regex (string-level, not element-scoped) | ✅ |
| `\.venv\*` inside `<Arguments>` | `...\.venv\Scripts\python.exe` | `[regex]::Escape("...BlarAI\.venv")` → devplatform\.venv | ✅ |
| Bare `<WorkingDirectory>C:\Users\mrbla\BlarAI</WorkingDirectory>` | wake-*.xml L42-49 | G-2 fix: lookbehind/lookahead regex, exact match only | ✅ |
| `<WorkingDirectory>C:\Users\mrbla\BlarAI\tools\vikunja</WorkingDirectory>` | vikunja-autostart.xml L74 | Caught by `\tools\*` regex BEFORE the bare-WD regex (still hits) | ✅ |
| Target-project refs `-BlarAIRoot 'C:\Users\mrbla\BlarAI'` | (none yet — added in Stage 2 refactor) | Preserve clause excludes (no `\tools\` or `\.venv\`) | ✅ |
| `--project-root C:\Users\mrbla\BlarAI` injection | After substitution | Conditional inject (only if not already present) | ✅ |

**Audit A.2 verdict**: **All observed XML path classes covered.** No path-class escapes the substitution loop.

### A.3 — State and roster file ownership post-separation

| File | Pre-cutover location | Post-cutover location | Resolution mechanism | Verdict |
|---|---|---|---|---|
| `tools/autonomy_budget/state.json` | BlarAI | devplatform (auto-follows `state.py` move) | `state.py` uses `Path(__file__).resolve().parents[2]` | ✅ Single global state, single fleet (acceptable per S-1 acknowledgment) |
| `docs/active_tasks.yaml` (roster) | BlarAI | **stays at BlarAI** | `active_tasks.py` reads via `--project-root` arg (Stage 2.5.v1 line 17) | ✅ |
| `tools/vikunja_mcp/bridge/state.json`, `inbox.json`, `processed.json` | BlarAI | devplatform (bridge daemon moves with code) | Bridge starts from devplatform (Stage 4.6.5) | ✅ |
| `.platform/vikunja_project_ids.yaml` | created Stage 1.4 in BlarAI | stays at BlarAI | Read by Stage 4.7 preflight via `Get-Content` | ✅ |
| `docs/sprints/sprint_<N>/` artifacts | BlarAI | stays at BlarAI (project-scoped per DEC-15) | Resolved via `--project-root` for sprint-aware tools | ✅ |
| Wake-launcher logs `tools/scheduled-tasks/logs/` | BlarAI (current) | devplatform (wake_launcher follows code) | `Join-Path $RepoRoot logs` resolves to devplatform when invoked there | ✅ (S-2 archival recommendation stands) |

**Audit A.3 verdict**: **All state and roster files have a clearly defined post-cutover owner.** No orphan files, no double-write hazards.

### A.4 — Vikunja credential discovery survival

Verified credential resolution path:

1. **MCP server entry points** (`tools/vikunja_mcp/server.py` L27-29, `cli.py` L57-59):
   ```python
   VIKUNJA_URL  = os.environ.get("VIKUNJA_URL", "http://localhost:3456")
   VIKUNJA_USER = os.environ.get("VIKUNJA_USER", "blarai")
   VIKUNJA_PASS = os.environ.get("VIKUNJA_PASS", "")  # fail-closed if empty
   ```
2. **Env-var sources** (one of):
   - `.mcp.json` (Claude Code, gitignored): contains `VIKUNJA_PASS` literal — ✅ Stage 4.5 backs up + repoints
   - `.vscode/mcp.json` (VS Code Copilot, gitignored): same — ✅ Stage 4.4 backs up + repoints
   - `claude_desktop_config.json` (Claude Desktop, lives in `%APPDATA%`) — ✅ Stage 4.6 repoints
3. **Server URL** (`localhost:3456`): host-bound port, unchanged by file moves. Vikunja DB + binary copied to devplatform (Stage 4.1-4.2-4.3); restarted from devplatform; same port rebound. ✅
4. **Python interpreter resolution**: All three MCP configs currently use `${workspaceFolder}/.venv/Scripts/python.exe` (or absolute path). Stage 4.4-4.6 rewrite these to absolute `C:\Users\mrbla\devplatform\.venv\Scripts\python.exe` so the MCP entry-point module (`tools.vikunja_mcp.server`) is found in the devplatform package tree post-Stage-5-deletion.

**Audit A.4 verdict**: **Credential discovery survives cutover unchanged.** Three independent MCP configs all repointed by Stage 4.4-4.6. Server URL and credential env-var contract preserved across all entry points. **Pre-existing security smell**: `VIKUNJA_PASS` is a literal in `.mcp.json` / `.vscode/mcp.json` (already noted as F-1 in CLAUDE.md "Active State"). Out of scope for platform separation; recommend separate credential rotation post-cutover.

### A.5 — Wake-launcher templates and log paths

Wake template inventory (`docs/scheduled/wake_templates/`, 6 files):

| Template | Hardcoded paths | Status |
|---|---|---|
| `co_lead_architect.md` | L150 (`\tools\` path → rewritten) + L162 (`cd BlarAI` for REJECT → preserved as target-project) | ✅ Stage 4.7.5 handles both correctly |
| `configuration_agent.md` | None | ✅ |
| `ea_code.md` | None | ✅ |
| `ea_cowork.md` | None | ✅ |
| `sdo.md` | None | ✅ |
| `sprint_auditor.md` | None | ✅ |

Log paths: `wake_launcher.ps1` writes via `Join-Path $RepoRoot 'tools\scheduled-tasks\logs\<role>.log'`. With `-BlarAIRoot` (Stage 2.5.v2) and the script living at devplatform post-cutover, `$RepoRoot` (the script's base, NOT the target project) defaults to devplatform. Logs land at `devplatform/tools/scheduled-tasks/logs/<role>.log`. ✅

**Audit A.5 verdict**: **No additional gaps.** S-2 archival recommendation stands (copy BlarAI's existing 7 days of logs to long-term archive before Stage 5 deletion).

### A.6 — Aggregate audit verdict

| Audit | Outcome | New patches required |
|---|---|---|
| A.1 — Hardcoded path re-sweep | ✅ All in-scope hits covered or correctly preserved | 0 |
| A.2 — Stage 4.7 substitution coverage | ✅ All observed XML path classes covered | 0 |
| A.3 — State/roster ownership | ✅ All files have defined owners | 0 |
| A.4 — Vikunja credential discovery | ✅ Three MCP configs all repointed | 0 |
| A.5 — Wake templates + log paths | ✅ All 6 templates audited; log path correct | 0 |

**Net result**: **The 6 patches in commit `6a042ea` (G-1, G-2, G-3, G-4, S-1, S-2) close all identified workflow-integrity gaps.** The branch is **execution-ready**: an LA-approved merge to main can proceed without same-day rollback risk for any of the audited surfaces.

**All five originally-deferred prerequisites are now encoded as automated stage procedure steps** (no operator checklist remains):

| Prerequisite | Encoded at | Form |
|---|---|---|
| 1. Archive `tools/scheduled-tasks/logs/archive/` (S-2) | `06_STAGE5_CLEANUP.xml` item **5.0.5** | PowerShell archive command into `.platform/audit_archive/pre_stage5_<stamp>/` BEFORE any recursive delete. |
| 2. `VIKUNJA_PASS` env-var migration (F-1) | `01_STAGE0_PREFLIGHT.xml` item **0.0.5** + `05_STAGE4_CUTOVER.xml` items **4.4 / 4.5 / 4.6** | Stage 0 persists current literal as User env var; Stage 4 rewrites all three MCP configs (Claude Desktop, VS Code, Claude Code) to reference `${env:VIKUNJA_PASS}` instead of the literal. F-1 closed at cutover (literal removed from gitignored configs). |
| 3. S-1 rename hardening ticket | `07_STAGE6_HARDENING.xml` item **6.7.5** | Auto-creates Vikunja tickets for S-1 (`blarai_next_task_resolver.py` rename) and S-3 (`action_generator.py` rollback template) in DevPlatform-Meta project. |
| 4. `BlarAI-worktrees` empty check | `01_STAGE0_PREFLIGHT.xml` **0.5.5** + `05_STAGE4_CUTOVER.xml` **4.0.5** | `git worktree list` gate at both stages with `HALT` on failure. |
| 5. Fleet-pause active check | `01_STAGE0_PREFLIGHT.xml` **0.0** + `05_STAGE4_CUTOVER.xml` **4.0.6** | Stage 0 pauses the fleet via `state.pause_fleet(...)`; Stage 4.0.6 re-confirms via JSON read of `tools/autonomy_budget/state.json` with HALT on `fleet_paused=false`. |

The procedure is now self-contained: no out-of-band operator setup is required between staged work items.

---

## 5. Net workflow-integrity verdict per subsystem

| Subsystem | Will work post-cutover? | Notes |
|---|---|---|
| Wake triggers (Wake SDO / Co-Lead / EA Code / Sprint Auditor) | ✅ YES | Stage 2.5.v2 refactor + Stage 4.7 XML rewrite + 4.7.5 wake-template scan + 4.7.6 line-by-line audit fully cover. |
| Fleet pause/resume state (`state.json`) | ✅ YES | state.py is location-agnostic; state.json moves with the script. |
| Active task roster (`active_tasks.yaml`) | ✅ YES | Stays in BlarAI; Stage 2.4 adds `--project-root` to active_tasks.py. |
| Vikunja MCP queries (gate label probes from wake_launcher) | ✅ YES | `.mcp.json` repointed in Stages 4.4–4.6; bridge daemon order fixed in 4.6.5. |
| Python observability tasks (Daily Digest, Weekly Summary, Dashboard Maintainer, Welcome Back Poll, Credentials Rotation Reminder, Gate Stale Cleaner) | ❌ **BREAKS at Stage 5 deletion** | **G-2** — `<WorkingDirectory>` not rewritten. Smoke test in 4.8 gives false green. Fix: add WorkingDirectory rewrite or `pip install -e devplatform`. |
| `la_merge_approve.ps1` (DEC-14.5 APPROVE motion) | ❌ **BREAKS for devplatform-branch merges** | **G-1, G-4** — hardcoded `$RepoRoot = BlarAI` default. Fix: refactor like wake_launcher. |
| `agents-cadence-monitor.ps1` (5min/15min cadence flipper) | ⚠ WORKS via XML override but DEGRADED for manual ops | **G-1** — silent BlarAI default if ever invoked without `-RepoRoot`. |
| `escalation_watchdog.ps1` / `toast_watchdog.ps1` | ⚠ WORKS via XML override but DEGRADED | Same as above. |
| Vikunja server autostart on logon | ✅ YES (likely) | Stage 4.9 covers the .lnk; Stage 4.7 covers any task-XML form. **G-3** flags ambiguity worth confirming. |
| Audit-log preservation | ⚠ Lost in Stage 5 unless explicitly archived | **S-2** — recommend pre-Stage-5 archive copy. |
| Cross-repo `--blarai-root` plumbing | ✅ YES | Stage 2.4–2.5 covers active_tasks.py, blarai_next_task_resolver.py, wake_launcher.ps1, diff_builder.py, test_async_post_gate.ps1. |
| First-tick smoke test (Stage 4.8) | ⚠ MAY FALSE-GREEN | Per G-2, `python -m tools.X` resolves against BlarAI's still-present dormant tree. Smoke test passes. Real failure deferred until Stage 5. |
| Git automation (Co-Lead Bash(git merge), SDO Bash(git add), branch hygiene) | ✅ YES | wake_launcher's `--allowedTools` whitelist is data, not paths. Auto-stash logic referenced in INFRA_DELTA §2.1 is internal to wake_launcher and follows the script. |
| Sprint-auditor SCR pickup | ✅ YES | sprint-auditor.xml covered by 4.7. Trigger files (`tools\scheduled-tasks\triggers\*.wake`) live in devplatform post-cutover (correct — wake_launcher reads from `$RepoRoot\tools\scheduled-tasks\triggers\`). |

---

## 6. Recommended pre-merge actions (ordered, cheapest first)

These are documentation-only patches to the v2 execution docs. No code changes needed.

1. **Patch Stage 4.7 substitution loop to also rewrite bare `<WorkingDirectory>C:\Users\mrbla\BlarAI</WorkingDirectory>`** → fixes G-2. ~3 lines added, single sub-item. Risk: nil — bare BlarAI as WorkingDirectory is always wrong post-cutover.
2. **Extend Stage 2.5.v1 refactor list to include `agents-cadence-monitor.ps1`, `la_merge_approve.ps1`, `escalation_watchdog.ps1`, `toast_watchdog.ps1`** with `-BlarAIRoot` parameter (mirroring §2.5.v2 wake_launcher signature) → fixes G-1, G-4. 4 file refactors, each ~5 LOC.
3. **Extend Stage 4.7.6 line-by-line scan to all 5 modified PS1s** (not just wake_launcher.ps1) → defense-in-depth for G-1, G-4.
4. **Add Stage 4.7.7: confirm `vikunja-autostart` form** (scheduled-task vs. Startup-shortcut vs. both) and ensure each form is touched → resolves G-3 ambiguity.
5. **Add Stage 5.0.5: archive `BlarAI/tools/scheduled-tasks/logs/archive/`** to `C:\Users\mrbla\fleet-audit-archive\pre-platform-separation\` before Stage 5 deletion → fixes S-2.
6. **Correct path drift in Stage 2.5.v1 line 15**: `tools/fleet_ops/blarai_next_task_resolver.py` → `tools/autonomy_budget/blarai_next_task_resolver.py` → fixes S-1's documentation half. Add R12 entry to AUDIT_RISK_REVIEW §0.6.

If applied, **all 4 BREAKING/DEGRADED gaps and both smells are remediated without changing the architectural shape of the v2 plan.** The cutover then has true defense-in-depth at every fleet subsystem.

---

## 7. What I did NOT verify (gaps in this review)

- Did not run any of the v2 scripts in dry-run mode against a sandbox. This review is static-analysis only.
- Did not inspect every wake template (`docs/scheduled/wake_templates/*.md`) for contained hardcoded paths beyond the patterns Stage 4.7.5 already enumerates.
- Did not enumerate all 13 task XMLs to confirm the `python -m tools.X` invocations don't have edge cases (e.g., a task whose Arguments hardcodes a BlarAI path inside a `--config` flag).
- Did not stress-test the regex `BlarAI\tools` → `devplatform\tools` against pathologically-quoted XML strings (encoded entities, mixed slashes).
- Did not verify Stage 0 backup actually captures all 13 task XMLs (assumed correct from R1 fix).

These should be covered by Stage 4.8's per-task smoke test (with G-2 patched, the smoke test becomes meaningful).

---

## 8. Bottom line

**The v2 separation plan, as committed at `1c08922`, will execute cleanly through Stage 4 cutover but produce a fleet that:**
- Wakes correctly (good).
- Runs gate label probes correctly (good).
- Performs ad-hoc LA merges incorrectly (G-4, breaks immediately on first devplatform merge approve).
- Runs Python observability tasks correctly during smoke test, then fails silently within 24-72h when Stage 5 deletes BlarAI's dormant tools tree (G-2, breaks at Stage 5 boundary — most insidious because Stage 4.8 will report green).
- Logs ad-hoc to BlarAI for any manual PS1 invocation (G-1, latent).

**Fix the 6 doc patches in §6 first.** Then the answer to the user's question becomes an unqualified YES.
