# Platform Separation — Master Plan

**Project**: Extract the Claude development-platform layer from `C:\Users\mrbla\BlarAI` into a standalone repo at `C:\Users\mrbla\devplatform`.

**Author**: GitHub Copilot (planning session, 2026-04-23)
**v2 update author**: GitHub Copilot (delta-capture session, 2026-04-24+)
**Authority**: Lead Architect approved all locked decisions (§A–§F) and recommendations below.
**Execution mode**: Per-stage XML prompts executed in fresh VS Code Copilot sessions (not the agent fleet — see §Execution Model).

> **v2 — Read this first.** This plan was originally drafted at BlarAI commit `24ec0d9` (v1 merge). Since then, main has accumulated significant infrastructure that this plan must absorb: governance docs (`docs/governance/`), wake templates (`docs/scheduled/wake_templates/`), new fleet tools (`blarai_next_task_resolver.py`, `tools/fleet_ops/diff_builder.py`, `escalation_notify.ps1`, `escalation-watchdog.*`, `test_async_post_gate.ps1`), parallel-sprint authorization (`tools/autonomy_budget/active_tasks.py`), an expanded `state.json` schema (v1), and the BlarAI-worktrees pattern (`C:\Users\mrbla\BlarAI-worktrees\`). The scheduled-task fleet count remains **13** (live, TaskPath `\BlarAI\`); earlier v2 drafts mistakenly claimed `escalation-watchdog` was a 14th task — it is already part of the live 13. The full inventory of v2 deltas lives in [`INFRA_DELTA_v2.md`](INFRA_DELTA_v2.md). Each stage XML carries a `<v2_updates>` block that lists the additive work items v2 introduces. Treat the v1 content as the baseline and the `<v2_updates>` blocks as the authoritative scope expansion.

---

## 1. Objective

Separate two logically distinct concerns currently commingled in one workspace:

- **BlarAI product** — local AI system (USE-CASE-001 + USE-CASE-004 operational). Stays at `C:\Users\mrbla\BlarAI`.
- **Claude development platform** — Co-Lead / SDO / EA fleet, Vikunja, MCP bridge, observability, autonomy budget, gate runners. Moves to `C:\Users\mrbla\devplatform`.

Post-move, the platform can manage multiple projects (BlarAI being the first); BlarAI becomes just one of N projects the platform coordinates.

## 2. Locked Decisions

| ID | Decision | Lock |
|----|----------|------|
| §A | **A1 — project-scoped artifacts under `BlarAI/.platform/`** | Platform tools live in `devplatform/tools/`. Per-project runtime artifacts (sprints, scheduled-tasks outputs, active_tasks.yaml) live under `BlarAI/.platform/`. |
| §B | **B1 — each project owns its own `.venv`** | Platform gets its own `.venv` at `devplatform/.venv`. No shared Python. |
| §C | **Multi-project seam built in during this move** | Fleet tools refactored to accept `--project-root` and `project_id`. See Stage 2. |
| §D | **Convention + discipline** | Small project count (<5) managed by convention. Every fleet tool accepts explicit project filter. |
| §D.1 | **Vikunja queries — HARD RULE** | **Every fleet tool's Vikunja query MUST pass an explicit `project_id` filter. "All tasks" queries are forbidden.** Enforced in `_vikunja_client.py` wrapper. |
| §E | **Platform = new `git init` repo** | No remote initially. BlarAI keeps its history. Single "Extract platform layer" commit on BlarAI side. |
| §F | **Both registered alongside in Claude Desktop** | `claude_desktop_config.json` gains a second workspace entry; doesn't replace BlarAI. |

## 3. Target Layout

```
C:\Users\mrbla\
├── BlarAI\                      # BlarAI product repo (existing, pruned)
│   ├── shared\ services\ launcher\ models\ …   # unchanged
│   ├── tools\openvino_contrib_agent\            # stays (BlarAI-only tool)
│   ├── docs\                                    # BlarAI docs only (ADRs, ledgers, Task*, P5_*)
│   └── .platform\                               # project-scoped platform artifacts
│       ├── active_tasks.yaml
│       ├── sprints\
│       ├── scheduled\                           # ea_queue, reports archive
│       └── vikunja_project_ids.yaml             # {blarai: N, devplatform_meta: M}
│
├── devplatform\                 # NEW — platform repo
│   ├── .venv\
│   ├── tools\
│   │   ├── vikunja\ vikunja_mcp\ fleet_ops\
│   │   ├── fleet_observability\ autonomy_budget\
│   │   ├── gate_stale_cleaner\ scheduled-tasks\
│   │   └── _vikunja_client.py                   # hard-rule wrapper (project_id mandatory)
│   ├── docs\                                    # platform doctrine (CLAUDE_*, CO_LEAD_*, DEC*, DOMAIN*)
│   ├── projects\
│   │   ├── registry.yaml                        # {blarai: {root: "C:/Users/mrbla/BlarAI", vikunja_id: N}}
│   │   └── blarai.yaml                          # allowlist, paths, env
│   ├── .mcp.json  .vscode\mcp.json
│   ├── AGENTS.md  CLAUDE.md
│   └── .github\copilot-instructions.md          # platform-scoped
│
└── backups\                     # recovery anchors (see §5)
    ├── BlarAI_pre_extract.bundle
    └── blarai_oog_2026MMDD_HHMMSS.zip
```

## 4. Execution Model — Why Not the Fleet?

The fleet is the **wrong tool** for this move because the fleet itself is what's being moved (bootstrap paradox). An EA prompt that refactors `wake_launcher.ps1` risks breaking the next wake; a prompt write to `BlarAI/scheduled/ea_queue/` fails mid-move when that directory is being relocated.

We replicate the fleet's discipline without the circular dependency:

- **Scoped per-stage prompts** — one XML per stage in this folder, modeled on EA prompt format (comprehension gate, work items, verification, rollback).
- **Fresh VS Code Copilot session per stage** — bounded context, no drift.
- **Durable state** — `STATUS.md` updated after every stage. New sessions read it first.
- **Recovery anchors** — belt-and-suspenders backup strategy (see §5).

After Stage 4 (cutover), the fleet runs cleanly from `devplatform`. Stages 5–6 could optionally go through the fleet at that point.

## 5. Recovery Strategy — Three Layers

Git tags alone are insufficient because the move touches state git doesn't track (Vikunja DB, MCP configs, scheduled tasks, Windows startup shortcuts).

| Layer | Artifact | Purpose |
|-------|----------|---------|
| 1 | `git tag pre-platform-extract` | Protects BlarAI's tracked file state. |
| 2 | `git bundle create C:\Users\mrbla\backups\BlarAI_pre_extract.bundle --all` | Portable self-contained repo backup. Survives repo corruption. |
| 3 | OOG zip (`blarai_oog_<timestamp>.zip`) of `.venv`-excluded out-of-git state | Covers Vikunja SQLite DB, MCP configs, scheduled-task XML exports, startup shortcut. |

**Retention rule**: do NOT delete `pre-platform-extract` tag or either backup file for **at least 90 days** after Stage 4 cutover. Some breakage (e.g., weekly_summary task, sprint auditor) doesn't surface until next scheduled fire.

## 6. Stages — At a Glance

| # | Stage | Risk | Can run in 1 session? | Prompt |
|---|-------|------|------------------------|--------|
| 0 | Pre-flight (backups, disable scheduled tasks) | LOW | Yes | [01_STAGE0_PREFLIGHT.xml](01_STAGE0_PREFLIGHT.xml) |
| 1 | Scaffold `devplatform/` alongside BlarAI | LOW | Yes | [02_STAGE1_SCAFFOLD.xml](02_STAGE1_SCAFFOLD.xml) |
| 2 | Refactor BlarAI fleet tools for `--project-root` seam | **HIGH** | Yes — dedicated | [03_STAGE2_REFACTOR_MULTIPROJECT.xml](03_STAGE2_REFACTOR_MULTIPROJECT.xml) |
| 3 | COPY (not move) platform tools to devplatform; run in parallel | MED | Yes | [04_STAGE3_COPY_TOOLS.xml](04_STAGE3_COPY_TOOLS.xml) |
| 4 | Cutover (MCP repointing, Vikunja autostart, scheduled tasks) | **HIGH** | Yes — single continuous block | [05_STAGE4_CUTOVER.xml](05_STAGE4_CUTOVER.xml) |
| 5 | Cleanup (delete platform tools from BlarAI, move to `.platform/`) | MED | Yes | [06_STAGE5_CLEANUP.xml](06_STAGE5_CLEANUP.xml) |
| 6 | Hardening (split CLAUDE.md, split copilot-instructions, 24h soak) | LOW | Across ≥2 sessions | [07_STAGE6_HARDENING.xml](07_STAGE6_HARDENING.xml) |

**Total realistic schedule**: 5–7 distinct sessions over ~1–2 weeks.

## 7. Hard Rule — Bake Into Stage 2

Every fleet tool that queries Vikunja MUST pass `project_id`. The `_vikunja_client.py` wrapper (created in Stage 2) enforces this at runtime:

```python
def list_tasks(self, *, project_id: int, **filters):
    if project_id is None or not isinstance(project_id, int):
        raise ValueError(
            "SECURITY: Vikunja list_tasks requires explicit int project_id. "
            "'All tasks' queries are forbidden by §D.1."
        )
    ...
```

All existing call sites audited and updated in Stage 2. Documented in `devplatform/.github/copilot-instructions.md` as a `<security_rule>`.

## 8. Vikunja Project IDs

No IDs allocated yet. Created during Stage 1.4 via `mcp__vikunja__create_project`:

- Existing projects (whatever IDs are in Vikunja today) → assigned to BlarAI in `registry.yaml`.
- New project **"DevPlatform-Meta"** created for platform-layer work (fleet tool improvements, MCP infra, governance evolution).
- IDs written to:
  - `devplatform/projects/registry.yaml` (platform-side registry)
  - `BlarAI/.platform/vikunja_project_ids.yaml` (BlarAI-side reverse lookup)

## 9. Files in This Folder

- [`00_MASTER_PLAN.md`](00_MASTER_PLAN.md) — this file
- [`INFRA_DELTA_v2.md`](INFRA_DELTA_v2.md) — **v2 only.** Full inventory of post-v1 infrastructure that v2 absorbs. Source of truth for every `<v2_updates>` block in the stage XMLs.
- [`01_STAGE0_PREFLIGHT.xml`](01_STAGE0_PREFLIGHT.xml) through [`07_STAGE6_HARDENING.xml`](07_STAGE6_HARDENING.xml) — per-stage execution prompts (each carries a v2_updates block)
- [`STATUS.md`](STATUS.md) — living state; updated after every stage
- [`RECOVERY.md`](RECOVERY.md) — rollback procedures by stage
- [`ROLLBACK_NOVICE_GUIDE.md`](ROLLBACK_NOVICE_GUIDE.md) — non-dev rollback guide
- [`VERIFICATION_COMMANDS.md`](VERIFICATION_COMMANDS.md) — copy-paste verification cheat sheet
- [`AUDIT_RISK_REVIEW.md`](AUDIT_RISK_REVIEW.md) — pre-execution audit and risk review

## 10. How to Execute a Stage

1. Open fresh VS Code Copilot session in `C:\Users\mrbla\BlarAI` workspace.
2. Attach the stage's XML (e.g., `01_STAGE0_PREFLIGHT.xml`) and `STATUS.md`.
3. Tell Copilot: *"Execute this stage prompt."*
4. Copilot presents comprehension summary → you approve → Copilot executes.
5. Run verification commands from `VERIFICATION_COMMANDS.md`.
6. Copilot updates `STATUS.md` with outcome, commit hash, evidence files.
7. Stop. New session for next stage.

If any stage fails verification: stop, consult `RECOVERY.md` for that stage, decide whether to roll back or fix forward.

---

## 11. v2 Scope Expansion (Authoritative)

This section catalogues the post-v1 infrastructure each stage must absorb. **Source of truth: [INFRA_DELTA_v2.md](INFRA_DELTA_v2.md).** Each stage XML carries a `<v2_updates>` block referencing items here.

### 11.1 New infrastructure (must be copied / migrated)

- `docs/governance/` — 7 governance docs (~2377 LOC). MOVE to devplatform.
- `docs/scheduled/wake_templates/` — 6 wake templates (cron-fired wake prompts). MOVE to devplatform.
- `tools/fleet_ops/blarai_next_task_resolver.py` (~154 LOC). MOVE to devplatform; gains `--blarai-root` flag.
- `tools/fleet_ops/diff_builder.py` (~168 LOC). MOVE to devplatform.
- `tools/fleet_observability/escalation_notify.ps1` (~103 LOC). MOVE to devplatform.
- `tools/scheduled-tasks/escalation-watchdog.xml` and matching `.ps1` (~213 + 43 LOC). MOVE to devplatform. **Tool files are new in v2; the matching scheduled task `Escalation Watchdog` is ALREADY part of the live 13-task fleet — not a new 14th task.**
- `tools/scheduled-tasks/test_async_post_gate.ps1` (~233 LOC). MOVE to devplatform.
- `docs/sprints/_templates/` (SDV / SCR / SWAGR). STAY in BlarAI (per-project artifact).
- `docs/ledger/` (per-entry directory format, Q1-1 onwards). STAY in BlarAI.

### 11.2 Changed behavior (must be re-tested)

- `tools/scheduled-tasks/wake_launcher.ps1` — grew by ~655 LOC. Stage 4 must do a line-by-line path-rewrite scan (not just regex). **Correct path: `tools/scheduled-tasks/wake_launcher.ps1`** (NOT `tools/fleet_ops/wake_launcher.ps1` — the file has never lived there; earlier drafts mis-referenced it).
- `tools/autonomy_budget/state.json` — schema_version=1 with fields: `fleet_paused`, `fleet_paused_reason`, `last_digest_utc`, `last_la_action_utc`, `last_updated_by`, `last_updated_utc`, `last_welcome_back_utc`, `role_paused` (5-role dict), `schema_version`.
- `tools/autonomy_budget/active_tasks.py` — +127 LOC, schema-validated, parallel-sprint authorization. Gains `--blarai-root`.
- Bridge: still single `inbox.json` (NOT `inbox.d/` — v1 assumption corrected).
- Scheduled tasks: **13 total at TaskPath `\BlarAI\`** (verified live 2026-04-25). The set: Agents Cadence Monitor, Credentials Rotation Reminder, Daily Digest, Dashboard Maintainer, Escalation Watchdog, Gate Stale Cleaner, Sprint Auditor, Toast Watchdog, Wake Co-Lead Architect, Wake EA Code, Wake SDO, Weekly Summary, Welcome Back Poll. Vikunja autostart is a **Windows Startup-folder shortcut** (Stage 4.9), NOT a scheduled task. Earlier v2 drafts wrote 14 — corrected.

### 11.3 New SOPs (mandatory)

- **Fleet-pause SOP**: every substantive multi-commit op runs `state.pause_fleet(...)` → work → `state.resume_fleet(...)` (NOT `unpause_fleet` — wrong name). See `.github/copilot-instructions.md` §fleet_pause_sop. Stage 0 adds this as item 0.0.
- **Worktrees-empty precondition**: `C:\Users\mrbla\BlarAI-worktrees\` exists as a sibling. Stage 0 must verify `git worktree list` shows only main before destructive ops; Stage 4 re-verifies.
- **Vikunja label IDs locked**: Active=1, Complete=2, Blocked=3, Architecture=4, Infrastructure=5, Testing=6, Documentation=7, Security=8, Gate:Pending-SDO=9, Gate:Pending-CoLead=10, Gate:Pending-Human=11, Gate:Approved=12, Gate:Rejected=13, Gate:Escalation=14. Fleet Reports project id=8.
- **EA per-sprint archives**: `docs/ea_queue/archive/` STAYS in BlarAI (per-project artifact).

### 11.4 What does NOT change from v1

- Two-repo target (BlarAI + devplatform).
- Stage sequencing 0–6.
- 15 prior fixes from v1 audit (BOM stripping, hash verification, hostile path rollback, etc.).
- Single-inbox bridge.
- Locked decisions §A–§F.

### 11.5 v2 Provenance

- v1 plan baseline: BlarAI commit `24ec0d9` (merge), tip `ab92cbb`.
- v2 baseline: BlarAI `main` HEAD as of 2026-04-24.
- Branch: `docs/platform-separation-v2`.
- Delta document: [INFRA_DELTA_v2.md](INFRA_DELTA_v2.md), committed at `0bff488`.

