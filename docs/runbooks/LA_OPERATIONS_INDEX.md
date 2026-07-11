# Lead Architect Operations Index

> **Who this is for**: you, the Lead Architect (LA). This is your single-point-of-entry into every runbook in `docs/runbooks/`.
>
> **How to use**: skim the "When X happens, read Y" table. Click through. Each runbook is self-contained and novice-friendly.
>
> **Last updated**: 2026-04-21 (DEC-15 + sprint-boundary agents landed).

---

## The mental model in 30 seconds

BlarAI runs on a **fleet of autonomous agents** (EA, SDO, Co-Lead, Sprint Auditor) that execute work between **sprint boundaries**. You (LA) are in the loop at three kinds of moments:

1. **Sprint boundaries** — kicking off, debriefing, discovering what's next.
2. **Per-milestone reports** — reading what the fleet produced and optionally flagging issues.
3. **Operational exceptions** — Vikunja is down, scheduled tasks misfire, a process needs a reboot recovery.

The runbooks below cover all three categories.

---

## Runbook directory — when to read which

### Sprint boundary operations (the slash-command family)

| Situation | Runbook | Slash command |
|---|---|---|
| You want to explore an idea, customer need, or strategic direction BEFORE committing to a sprint | [LA_SPRINT_DISCOVERY_HOWTO.md](LA_SPRINT_DISCOVERY_HOWTO.md) | `/sprint-discovery ["<seed topic>"]` |
| A sprint just completed; you want to understand what happened and decide what's next | [LA_SPRINT_DEBRIEF_HOWTO.md](LA_SPRINT_DEBRIEF_HOWTO.md) | `/sprint-debrief [N]` |
| You've decided what the next sprint is; time to author the SDV | [LA_SPRINT_KICKOFF_HOWTO.md](LA_SPRINT_KICKOFF_HOWTO.md) | `/sprint-kickoff <N> "<theme>"` |

**Typical end-to-end flow**:

```
sprint ends                  sprint N+1
    |                            |
    v                            v
    SCR + SWAGR      ┌───────────────────┐
      (autonomous)   │  Fleet runs EAs   │
    |                └───────────────────┘
    v                    ^
/sprint-debrief          |
    |                    |
    v                    |
/sprint-discovery  ───►  /sprint-kickoff
  (optional — only       (authors SDV,
   when exploring new      signs off, fleet
   directions)             takes over)
```

The dashed path (discovery) is optional. Direct debrief → kickoff is also valid when the next sprint is obvious.

### Per-milestone operations (during a sprint)

| Situation | Runbook |
|---|---|
| You want to read the reports the fleet is producing | [LA_FLEET_REPORTS_HOWTO.md](LA_FLEET_REPORTS_HOWTO.md) |
| You spotted an issue in a report and want the fleet to fix it | [LA_CAR_WORKFLOW_HOWTO.md](LA_CAR_WORKFLOW_HOWTO.md) |

These are the two runbooks you'll use most day-to-day. Fleet Reports is your inbox; CAR is how you flag remediation.

### Operational / exceptional situations

| Situation | Runbook |
|---|---|
| You just rebooted your laptop and want to verify the fleet came back up | [LA_REBOOT_CHECKLIST.md](LA_REBOOT_CHECKLIST.md) |
| The laptop died / is being reformatted and you need to rebuild EVERYTHING from backups | [DISASTER_RECOVERY_RESTORE.md](DISASTER_RECOVERY_RESTORE.md) (master; a copy rides the OneDrive backup root, refreshed nightly) |
| You need to pause the fleet, register scheduled tasks, rotate credentials, or do any install-level work | [AUTONOMOUS_FLEET_OPERATIONS.md](AUTONOMOUS_FLEET_OPERATIONS.md) |
| You see a stash backlog, working tree on the wrong branch, an orphaned EA worktree, or a merge-gate ESCALATE on a path mismatch | [../governance/fleet-hygiene.md](../governance/fleet-hygiene.md) (Recovery procedures R1-R6) |
| You're about to change `wake_launcher.ps1`, `tools/autonomy_budget/`, or anything that affects how the fleet manages working-tree state | [../governance/fleet-hygiene.md](../governance/fleet-hygiene.md) (drift catalogue + stash policy + worktree topology) |
| You're troubleshooting something that doesn't fit the above | Ask Claude Desktop — describe symptoms, let it diagnose |

---

## The agent cast (who does what)

| Agent | Interactive or autonomous? | Output | When |
|---|---|---|---|
| **EA Code** (Execution Agent) | Autonomous | Code / test / doc commits per milestone | Every 15 min scheduled wake |
| **SDO** (Strategic Development Orchestrator) | Autonomous | EA prompts + milestone reviews | Every 15 min scheduled wake |
| **Co-Lead Architect** (autonomous) | Autonomous | SDO continuation XMLs + sprint transitions + merge decisions | Every 15 min scheduled wake |
| **Co-Lead Architect** (interactive) | LA-invoked | SDV authoring collaboration | `/sprint-kickoff` |
| **Sprint Auditor** | Autonomous | SWAGR documents | Every 15 min scheduled wake |
| **Business Analyst / Product Discovery** | LA-invoked | Vikunja tickets | `/sprint-discovery` |
| **Sprint Debriefer** | LA-invoked | Guidance + decisions (no artifact) | `/sprint-debrief` |
| **LA Configuration Agent (me, talking to you now)** | LA-invoked (interactive Claude Code / Desktop) | Anything the LA asks, ad-hoc | Always available |

Behind each role is a **wake template** at `docs/scheduled/wake_templates/` (for scheduled agents) OR a **slash command prompt** at `.claude/commands/` (for LA-invoked agents). Those are the canonical role specs if you want to dig deeper.

---

## The artifact layers (where stuff lives)

| Layer | Who writes | Where | How often |
|---|---|---|---|
| **Code commits** on main | EA Code (fleet) / LA (manual merges) | Git | Per EA milestone |
| **Milestone reports** (DEC-13) | EA / SDO / Co-Lead per-phase | `docs/sprints/sprint_<N>/reports/` or `docs/reports/task_<id>/` | Multiple per sprint |
| **Strategic Design Vision** (SDV) | LA + Co-Lead interactive | `docs/sprints/sprint_<N>/strategic_design_vision.md` | Once per sprint (start) |
| **Strategic Completion Report** (SCR) | Co-Lead autonomous | `docs/sprints/sprint_<N>/strategic_completion_report.md` | Once per sprint (end) |
| **Strategic Work Analysis and Gap Report** (SWAGR) | Sprint Auditor autonomous | `docs/sprints/sprint_<N>/Strategic_Work_Analysis_*.md` | Once per sprint (post-SCR) |
| **Corrective Action Reports** (CAR) | Co-Lead on LA flag | `docs/reports/corrective_actions/` | On-demand |
| **Vikunja tickets** | BA / LA / any agent | Vikunja local SQLite (`http://localhost:3456`) | Continuous |
| **Ledger** | EA at milestone complete | `docs/POST_OPERATIONAL_MATURATION_LEDGER.md` | Per milestone |

**Rule**: Disk is authoritative for audit. Vikunja is operational queue UX. Everything important on disk is in git.

---

## The convention-enforced single sources of truth

Three files, three purposes. Never hardcode anything that can be derived from these:

| File | What it tells you | How agents use it |
|---|---|---|
| `docs/active_tasks.yaml` | Which sprint is currently active (via `sprint_id`) | Every scheduled agent reads this at wake |
| `docs/sprints/ACTIVE_SPRINT.md` | Human-readable sprint state + historic archive | LA and interactive agents reference |
| `CLAUDE.md` | Project-wide convention (DEC-15 derivation rules, etc.) | Loaded automatically in every Claude Code session |

When in doubt, read these three.

---

## Escape hatches

- **Something looks broken, I don't know where to start** → open Claude Desktop or Claude Code, describe symptoms, let the agent diagnose. This is always OK.
- **I want to pause everything** → [AUTONOMOUS_FLEET_OPERATIONS.md §23](AUTONOMOUS_FLEET_OPERATIONS.md#23-agents-task-manager-the-one-command-way-to-pause-resume-or-reinterval) is the simplest path (one PowerShell command). §13/§14 describe the deeper Python-level pause mechanism. Or ask Claude Desktop: *"Pause the fleet."*
- **I want to understand something not in these runbooks** → no runbook is exhaustive; ask Claude Desktop or Claude Code directly. The runbooks cover the common cases.

---

## Quick-reference acronyms

| Acronym | Meaning |
|---|---|
| **LA** | Lead Architect (you) |
| **EA** | Execution Agent (writes code) |
| **SDO** | Strategic Development Orchestrator (plans work, reviews EA) |
| **Co-Lead** | Co-Lead Architect (plans SDO work, reviews SDO, handles merges + sprint transitions) |
| **SDV** | Strategic Design Vision (sprint-start design doc) |
| **SCR** | Strategic Completion Report (sprint-end summary) |
| **SWAGR** | Strategic Work Analysis and Gap Report (independent peer audit post-SCR) |
| **CAR** | Corrective Action Report (remediation triggered by LA flag) |
| **WI** | Work Item (a single numbered task in an EA prompt) |
| **ADR** | Architecture Decision Record (locked architectural choice) |
| **DEC** | Decision document (locked operational/process choice) |
| **UC** | Use Case (one of the 9 canonical BlarAI use cases) |
| **LOC** | Lines of Code |
| **MCP** | Model Context Protocol (how Claude talks to Vikunja + other tools) |
| **Vikunja** | Your task-tracker at `http://localhost:3456` |
| **BA** | Business Analyst (the product-discovery agent) |

---

## Version history

- **2026-04-21**: Initial authoring alongside DEC-15 (SDV/SCR/SWAGR + Sprint Auditor) and the sprint-boundary slash-command family (discovery / kickoff / debrief).
