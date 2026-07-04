# Infrastructure Delta v1 → v2

**Purpose**: Document what changed in BlarAI between when the v1 platform-separation plan
was committed (`24ec0d9`, 2026-04-23) and the v2 refactor (2026-04-24). Every other file
in `docs/platform_separation/` is being updated to reflect this delta. This file is the
authoritative record of *why* those updates exist.

**v1 plan baseline commit**: `24ec0d9`
**v2 refactor base commit**: `main` HEAD as of 2026-04-24
**Investigation method**: `git diff 24ec0d9..main --stat` filtered to platform-relevant
paths (tools/, docs/governance/, docs/scheduled/, docs/sprints/_templates/,
docs/active_tasks.yaml, CLAUDE.md, AGENTS.md, .github/copilot-instructions.md).

---

## Summary

The v1 plan was authored against a working, but in-flux, fleet. Between v1 commit and
v2 refactor, \~46 files / \~6000 LOC of fleet infrastructure changes landed via Sprint 8
and Sprint 9 hardening. None of them invalidate the v1 architectural intent (extract
the platform tools to a sibling repo), but several change the **inventory of files to
copy**, the **scope of the multi-project refactor**, and the **safety procedures**
that wrap the cutover.

Three categories of change:

1. **NEW infrastructure** the v1 plan does not know about (must be copied / refactored).
2. **CHANGED behavior** in code the v1 plan already knew about (must update procedure).
3. **NEW SOPs** the v1 plan didn't enforce (must be added to every stage).

---

## 1. NEW infrastructure (v1 didn't know about)

### 1.1 `BlarAI-worktrees\` sibling directory (Pattern B)

**Status**: Exists at `C:\Users\mrbla\BlarAI-worktrees\` as of v2.
**v1 plan assumption**: Single working tree at `C:\Users\mrbla\BlarAI\`.
**Reality**: Per-EA-session git worktrees are spawned at
`C:\Users\mrbla\BlarAI-worktrees\<branch-name>\` to let multiple agents work in
parallel without contaminating the main tree.

**Impact on plan**:
- Stage 0 backup must capture `C:\Users\mrbla\BlarAI-worktrees\` if it contains any
  in-flight branches at preflight time (or refuse to start if non-empty —
  worktrees are ephemeral and should be drained before a platform extraction).
- Stage 4 cutover must verify `BlarAI-worktrees\` is **empty** before any
  destructive operation (a worktree pointing to a moved file path will explode).
- Stage 5 cleanup logic must NOT delete the `BlarAI-worktrees\` directory itself —
  it is sibling to BlarAI, not under it.

### 1.2 `docs/governance/` — 7 governance docs

```
docs/governance/README.md                       (334 LOC)
docs/governance/deployment-verification.md      (337 LOC)
docs/governance/fleet-hygiene.md                (803 LOC) — authoritative pause SOP
docs/governance/merge-policy.md                 (61 LOC)
docs/governance/observability.md                (376 LOC)
docs/governance/parallel-sprints.md             (116 LOC)
docs/governance/rule-engine.md                  (350 LOC)
```

These describe the *current* fleet operating model. They are PROCESS docs (not code),
so they migrate with the **platform layer** (devplatform), not with the BlarAI runtime.

**Impact on plan**:
- Add to Stage 4 file-move list: `docs/governance/` → `devplatform/docs/governance/`.
- Add to Stage 6 hardening: doctrine split — `fleet-hygiene.md` and `merge-policy.md`
  apply to BOTH repos and need cross-references.

### 1.3 `docs/scheduled/wake_templates/` — 6 wake templates

```
co_lead_architect.md, configuration_agent.md, ea_code.md,
ea_cowork.md, sdo.md, sprint_auditor.md
```

These are read by `wake_launcher.ps1` to construct the `claude -p` prompt for each
scheduled wake. They reference Vikunja project IDs, label IDs, file paths, and
pause-state checks — everything that defines an autonomous role.

**Impact on plan**:
- Stage 3 copy list: `docs/scheduled/wake_templates/` → `devplatform/docs/scheduled/wake_templates/`.
- Stage 4: any file-path reference inside a wake template that points at
  `C:\Users\mrbla\BlarAI\tools\...` must be rewritten to `C:\Users\mrbla\devplatform\tools\...`.
  Specifically search for: `BlarAI\tools\vikunja_mcp`, `BlarAI\tools\autonomy_budget`,
  `BlarAI\tools\scheduled-tasks`, `BlarAI\tools\fleet_observability`,
  `BlarAI\tools\fleet_ops`, `BlarAI\tools\agents.ps1`, `BlarAI\.venv`.

### 1.4 `tools/autonomy_budget/blarai_next_task_resolver.py` (new, 154 LOC + 164 LOC tests)

Resolves "what should the next active task be" against `docs/active_tasks.yaml` and
the Vikunja state. Not in v1 plan inventory.

**Impact on plan**:
- Stage 3 copy list: ensure `blarai_next_task_resolver.py` + its test file ship.
  (Stage 3 already copies the autonomy_budget tree wholesale, so this is automatic
  *if* the copy uses `Copy-Item -Recurse` rather than an enumerated file list. Verify.)
- Stage 4: this script reads `docs/active_tasks.yaml` (BlarAI-runtime-relative path).
  Decide whether `active_tasks.yaml` lives in BlarAI (runtime tasks) or devplatform
  (fleet roster). Recommendation: **lives in BlarAI** (it's the work queue for
  BlarAI's actual development), but the **resolver script** lives in devplatform
  (it's a fleet tool). The resolver must accept a `--blarai-root` argument or
  read the path from devplatform's `registry.yaml`.

### 1.5 `tools/fleet_ops/diff_builder.py` (new, 168 LOC + 199 LOC tests)

Builds structured diffs for fleet reports. New tool — not in v1 plan.

**Impact on plan**:
- Stage 3 copy list: add `tools/fleet_ops/` to the tree-copy.
- Pure platform tool. No multi-project refactor needed.

> **Path note**: `wake_launcher.ps1` lives at `tools/scheduled-tasks/wake_launcher.ps1`,
> NOT `tools/fleet_ops/wake_launcher.ps1`. Several earlier drafts of this plan referenced
> the wrong directory; corrected throughout v2 stage XMLs.

### 1.6 `tools/fleet_observability/escalation_notify.ps1` (new, 103 LOC)

Toast notification for escalation events. Pairs with `escalation_watchdog.ps1`.

**Impact on plan**: Stage 3 copy list addition.

### 1.7 `tools/scheduled-tasks/escalation_watchdog.ps1` + `.xml` (new tool files, 213 + 43 LOC)

New tool *files* delivered with v2 baseline. The matching scheduled task (`Escalation Watchdog`)
is ALREADY part of the live 13-task fleet at TaskPath `\BlarAI\` — verified live 2026-04-25.
Count stays at **13**, NOT 14. Earlier drafts of this document incorrectly inferred a count
bump; the correction is reflected throughout v2 stage XMLs.

**Impact on plan**:
- Stage 0.6 expected count: **13** (was incorrectly written as \~14 in earlier drafts).
- Stage 4 task-XML rewrite loop must handle `escalation-watchdog.xml` (the export, not a new
  task registration).
- All 13 task XMLs need their `<Command>` paths rewritten BlarAI → devplatform
  for tasks that invoke platform tools.

### 1.8 `tools/scheduled-tasks/test_async_post_gate.ps1` (new, 233 LOC)

Test script for the async-post gate logic in `wake_launcher.ps1`. Stage 3 copy list
addition.

### 1.9 `docs/sprints/_templates/` — SDV + SWAGR templates

```
strategic_design_vision_template.md            (53 LOC)
strategic_work_analysis_and_gap_report_template.md  (29 LOC)
```

DEC-15 sprint structure. **Stays in BlarAI** (sprints are BlarAI development work).
No action needed for separation, but the **rule for which repo owns sprint state**
must be explicit in Stage 6 doctrine.

### 1.10 `docs/ledger/` — per-file ledger entries (DEC-12)

Already exists post-v1. Stays in BlarAI (records BlarAI development history).

---

## 2. CHANGED behavior in v1-known code

### 2.1 `tools/scheduled-tasks/wake_launcher.ps1` (+655 LOC)

**v1 plan assumption**: Wake launcher is a thin wrapper.
**Reality**: Now a 600+ LOC orchestration script with auto-stash logic, async-post
sub-state checks, gate-attribution validation, fleet-pause enforcement, and per-role
dispatch.

**Impact on plan**:
- Stage 4 path-rewrite must scan `wake_launcher.ps1` line-by-line for hardcoded
  `C:\Users\mrbla\BlarAI\` paths and rewrite each. Likely affected:
  - `.venv\Scripts\python.exe` invocations
  - `tools\autonomy_budget\state.json` reads
  - `tools\vikunja_mcp\bridge\` paths
  - `docs\scheduled\wake_templates\` reads
  - Repo-relative path constants at top of script
- Stage 4 verification: dry-run `wake_launcher.ps1 -Role sdo -DryRun` on devplatform
  AFTER cutover; expect exit code 4 (fleet paused) since cutover requires pause.
- The auto-stash behavior is the reason v1's `git stash list` recovery was needed —
  Stage 4 procedure must explicitly pause the fleet (already required) AND verify
  no auto-stashes were created during the move window.

> **Path note**: `wake_launcher.ps1` is at `tools/scheduled-tasks/wake_launcher.ps1`.
> Several earlier drafts mis-referenced `tools/fleet_ops/wake_launcher.ps1` — the file
> has never lived there.

### 2.2 `tools/autonomy_budget/state.json` schema_version = 1

**v1 plan assumption**: state.json was a simple `{paused: bool}` blob.
**Reality**: schema_version 1 with these fields:
```json
{
  "fleet_paused": bool,
  "fleet_paused_reason": str | null,
  "last_digest_utc": str | null,
  "last_la_action_utc": str | null,
  "last_updated_by": str,
  "last_updated_utc": str,
  "last_welcome_back_utc": str | null,
  "role_paused": {
    "co_lead_architect": bool,
    "configuration_agent": bool,
    "ea_code": bool,
    "ea_cowork": bool,
    "sdo": bool
  },
  "schema_version": int
}
```

**Impact on plan**: Every stage that pauses the fleet must use the
`state.pause_fleet(reason, updated_by, path)` Python helper, NOT raw JSON edits
(see `fleet-hygiene.md` §4). Stage XMLs must include the canonical pause/unpause
commands at start and end of each stage.

### 2.3 `tools/autonomy_budget/active_tasks.py` (+127 LOC) + new schema

**v1 plan assumption**: `active_tasks.yaml` was an unstructured list.
**Reality**: Schema-validated with parallel-sprint authorization fields, pause-trigger
audit trail, and the DEC-15 `sprint_id` field.

**Impact on plan**:
- Stage 2 (multi-project refactor) scope expands: when adding `--project-root`
  to Vikunja CLIs, ALSO add `--blarai-root` to `active_tasks.py` and the resolver.
- Stage 4: `active_tasks.yaml` stays in BlarAI; tools that read it (in devplatform)
  need an explicit path argument.

### 2.4 `tools/vikunja_mcp/bridge/` — STILL single-file inbox

**v1 plan assumption**: Confirmed. Bridge protocol unchanged (single `inbox.json`,
single `state.json`, single `processed.json`).
**Verified**: `Get-ChildItem tools/vikunja_mcp/bridge/` shows `.gitignore`,
`.gitkeep`, `__pycache__/`, `tests/`. No `inbox.d/`. v1 plan is correct here.

**Impact on plan**: None — v1 procedure stands.

### 2.5 13 Windows Scheduled Tasks (live 2026-04-25)

Live set, all at TaskPath `\BlarAI\` (Title Case Spaces names verified via
`Get-ScheduledTask -TaskPath '\BlarAI\'`):

```
Agents Cadence Monitor          Sprint Auditor
Credentials Rotation Reminder   Toast Watchdog
Daily Digest                    Wake Co-Lead Architect
Dashboard Maintainer            Wake EA Code
Escalation Watchdog             Wake SDO
Gate Stale Cleaner              Weekly Summary
                                Welcome Back Poll
```

**Note**: Vikunja autostart is a **Windows Startup-folder shortcut** (Stage 4.9), NOT a
scheduled task — do not count it.

**Impact on plan**: Update Stage 0.6 expected count to **13** (earlier drafts wrote
`~13 → 14` based on the incorrect assumption that `escalation-watchdog` was new — it
is already in the live 13). The **correct task filter is `-TaskPath '\BlarAI\'`**;
name-only filters such as `Where-Object { $_.TaskName -like 'BlarAI*' }` return zero
because real names use Title Case Spaces (e.g., `Wake SDO`, NOT `BlarAI_wake_sdo`).

---

## 3. NEW SOPs (v1 didn't enforce)

### 3.1 Fleet-Pause SOP — MANDATORY for substantive work

**Authority**: `docs/governance/fleet-hygiene.md` §4 ("Pause / unpause SOP").
**Status**: Already added to `.github/copilot-instructions.md` and `CLAUDE.md`
(by the user's most recent edit).

**Verbatim required pattern**:
```powershell
# PAUSE (FIRST action before any branch checkout or non-trivial edit)
python -c "from tools.autonomy_budget import state; state.pause_fleet('<short reason>', updated_by='<agent_name>', path='C:/Users/mrbla/BlarAI/tools/autonomy_budget/state.json')"
git commit -am "chore(ops): pause fleet -- <reason>"

# WORK

# UNPAUSE (LAST action before exit)
python -c "from tools.autonomy_budget import state; state.resume_fleet(updated_by='<agent_name>', path='C:/Users/mrbla/BlarAI/tools/autonomy_budget/state.json')"
git commit -am "chore(ops): unpause fleet -- <reason> done"
```

**Critical gotcha**: The function is `resume_fleet`, NOT `unpause_fleet`. Calling
`state.unpause_fleet(...)` raises `AttributeError`.

**Impact on plan**: EVERY stage XML must:
1. Include a Pre-Flight section that calls `state.pause_fleet(...)` and commits.
2. Include a Post-Flight section that calls `state.resume_fleet(...)` and commits.
3. Wrap any auto-generated EA prompt with the same triplet pattern (the EA must
   re-pause if it loses pause state across context).

### 3.2 Worktrees-empty precondition

**v1 plan assumption**: None.
**Reality**: If `C:\Users\mrbla\BlarAI-worktrees\` contains in-flight branches at
cutover time, moving files in BlarAI will silently break those worktrees.

**Impact on plan**:
- Stage 0 preflight: `git worktree list` must show only the main worktree.
- Stage 4 cutover gate: re-verify worktree list is clean immediately before any
  file move.

### 3.3 Vikunja gate label IDs (use IDs, NOT names)

**Authority**: CLAUDE.md "Labels (server-canonical, verified 2026-04-20)".
**Reality**: All wake templates and EA prompts now reference Vikunja labels by
integer ID, not name. Labels 9–14 are the gate bus (Pending-SDO, Pending-CoLead,
Pending-Human, Approved, Rejected, Escalation).

**Impact on plan**: When devplatform fleet templates reference labels, they must
also use IDs. The `Fleet Reports` Vikunja project (id 8, per CLAUDE.md) is the
fleet's reporting destination — devplatform fleet tools post there.

### 3.4 EA queue archive subdirs (per-sprint)

**Reality**: `docs/ea_queue/archive/sprint_<N>/` directories now exist (commit
`390f04b`). Per-sprint archival.

**Impact on plan**:
- Stage 5 cleanup: archived EA prompts STAY in BlarAI (they record BlarAI development
  history). Do not move to devplatform.
- Stage 6 doctrine: clarify "EA execution prompts are BlarAI artifacts (development
  history); EA wake templates are devplatform artifacts (fleet definition)".

---

## File-by-file v2 update checklist

| File | What changes |
|---|---|
| `00_MASTER_PLAN.md` | Add v2 scope: governance docs, wake templates, new tools, worktrees precondition. Update file inventory. |
| `01_STAGE0_PREFLIGHT.xml` | Pause-fleet pre-flight (already added). Worktree-empty precondition. Task count assertion: **13** (live, TaskPath `\BlarAI\`). |
| `02_STAGE1_SCAFFOLD.xml` | `.gitignore` for state.json runtime fields, Fleet Reports project ID capture. |
| `03_STAGE2_REFACTOR_MULTIPROJECT.xml` | Scope expansion: `--blarai-root` on `active_tasks.py`, `blarai_next_task_resolver.py`, `wake_launcher.ps1`. |
| `04_STAGE3_COPY_TOOLS.xml` | Add to copy list: `docs/governance/`, `docs/scheduled/wake_templates/`, `tools/fleet_ops/`, `tools/fleet_observability/escalation_notify.ps1`, `tools/scheduled-tasks/escalation_watchdog.ps1`, `tools/scheduled-tasks/escalation-watchdog.xml`, `test_async_post_gate.ps1`, `blarai_next_task_resolver.py`. |
| `05_STAGE4_CUTOVER.xml` | Worktrees-empty gate. Wake-template path rewrite. wake_launcher path rewrite (line-by-line scan; correct path `tools/scheduled-tasks/wake_launcher.ps1`). 13 task XMLs. Fleet-pause triplet around the destructive section. Bridge daemon ordering moved BEFORE task re-enable (4.6.5). CLI-arg injection (`--project-root`, `--project-id`) into task `<Arguments>` blocks. |
| `06_STAGE5_CLEANUP.xml` | Decide ownership: `active_tasks.yaml`, `docs/sprints/`, `docs/ledger/`, `docs/ea_queue/archive/` STAY in BlarAI. `docs/governance/`, `docs/scheduled/wake_templates/` MOVE to devplatform. Update doctrine accordingly. |
| `07_STAGE6_HARDENING.xml` | Cross-reference rules between repos. Two-repo `fleet-hygiene.md` enforcement. |
| `STATUS.md` | Bump to v2. Note that v1 commit `ab92cbb` is superseded by v2 (this branch). |
| `RECOVERY.md` | Add worktrees-recovery procedure. Add fleet-state.json restoration procedure. |
| `ROLLBACK_NOVICE_GUIDE.md` | Add "fleet keeps eating my files" recovery (auto-stash + worktree explanation). |
| `VERIFICATION_COMMANDS.md` | Add: `git worktree list`, `Get-Content state.json`, `Get-ScheduledTask -TaskPath '\BlarAI\' | Measure-Object` (expected count 13). |
| `AUDIT_RISK_REVIEW.md` | Add v2 section: 5 new risks (worktree contamination, wake-template path drift, state.json schema version, governance doc duplication, label-ID drift). |

---

## What does NOT change

- Two-repo target architecture (BlarAI runtime + devplatform platform).
- Stage sequencing (0→1→2→3→4→5→6).
- The 15 fixes already applied per `AUDIT_RISK_REVIEW.md` §5.
- Vikunja remains the task tracker; bridge protocol remains single-inbox.
- Stage 4 remains the only high-risk stage.
- ROLLBACK_NOVICE_GUIDE.md structure (panic card, dry-run drill, symptom table).

---

## Provenance

- v1 plan commit: `24ec0d9` (merge), `ab92cbb` (planning branch tip).
- v2 baseline: `main` HEAD as of 2026-04-24.
- v2 branch: `docs/platform-separation-v2`.
- Investigation: `git log 24ec0d9..main --oneline` (50+ commits) +
  `git diff 24ec0d9..main --stat` filtered to platform-relevant paths.
