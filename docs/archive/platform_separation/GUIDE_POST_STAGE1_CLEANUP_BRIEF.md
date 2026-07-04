# Post-Stage-1 Cleanup — Lead Architect Brief

**Issued**: Guide instance 2, 2026-04-24T23:35:00Z
**Audience**: Lead Architect (LA), as a decision-and-context companion to the Executor directive
**EA-facing companion**: [`GUIDE_POST_STAGE1_CLEANUP_DIRECTIVE.xml`](GUIDE_POST_STAGE1_CLEANUP_DIRECTIVE.xml) (same folder)
**Status**: Stage 1 is closed. This brief explains a between-stages cleanup pass authorized to run before Stage 2 kickoff.

---

## TL;DR

You asked me to choose the mature option for four forward-looking risks (F1–F4) I surfaced at Stage 1 closure, plus two follow-on classification questions (Q7, Q8) you flagged afterward. All six fold into a single consolidated EA cleanup pass:

| ID | Risk / Question | Mature option chosen | Why |
|---|---|---|---|
| **F1** | `_project_context.py` looks up wrong yaml key — every fleet tool would `ValueError` at first runtime call | **Generalize**: derive the key from `root.name.lower() + "_project_id"` | Works for BlarAI today AND any future project with no further code changes |
| **F2** | MCP tools may not be exposed in future Executor sessions — every Vikunja-touching stage would re-file an A5-style anomaly | **Codify the REST fallback**: add a `<vikunja_access_protocol>` block to Stages 2, 3, 4 XMLs documenting both paths | We can't reliably control the Executor surface; REST is byte-equivalent and Stage 1 EA already proved it works end-to-end |
| **F3** | Three preflight regexes (`'blarai:\s*(\d+)'`) won't match the actual yaml key (`blarai_project_id:`) — every Stage 2.8 / 3.7 / 4.7 would throw | **Fix the regex** at all three sites | Yaml is the source of truth; regex must match it. One canonical key name beats two redundant ones. |
| **F4** | `BlarAI Agent Gates` (Vikunja project 6) is misclassified as a BlarAI-auxiliary in `registry.yaml` | **Promote to fleet-level**: move to top-level `projects.agent_gates_bus` alongside `fleet_reports` | Per BlarAI/CLAUDE.md, project 6 IS the Agent Gates bus — a shared resource referenced by labels 9–14. After multi-project, devplatform_meta will post gates here too. |
| **Q7** | `Architecture Decisions` (Vikunja project 5) — fleet-level or BlarAI-only ADRs? | **Promote to fleet-level**: move to top-level `projects.architecture_decisions` | Vikunja project name has NO project prefix (unlike `BlarAI Infrastructure`, `BlarAI Drafts`, etc.) — strongest available signal that it's intended for cross-project ADR (Architecture Decision Record) tracking. Worst case: Stage 6 investigation reveals it's BlarAI-specific; one-line revert. |
| **Q8** | Auxiliary projects 4 / 7 / 9 (`BlarAI Infrastructure`, `BlarAI Fleet Dashboard`, `BlarAI Drafts`) — keep / archive / reclassify? | **Annotate with provisional notes; defer firm decision to Stage 6** | Task-count and last-update data not available at Stage 1; would require starting Vikunja and per-project queries. Premature classification risks dropping active work. YAML comments document ambiguity (especially "BlarAI Fleet Dashboard" — name conflicts with concept) and direct Stage 6 to investigate. |

The EA will produce **two commits** (one on BlarAI's `chore/platform-extraction`, one on devplatform's `main`). Stage 1 closure status is **UNCHANGED** — Stage 1 stays COMPLETE; this is post-close cleanup, not a re-open.

---

## Why each fix is mature

### F1 — Generalize, don't just rename one key

**The bug.** Stage 2 XML item 2.2 inline `_project_context.py` resolves the project ID like this:
```python
project_id = (
    cli_project_id
    if cli_project_id is not None
    else registry.get("blarai")
    or registry.get("project_id")
)
```
But the yaml schema Stage 1 wrote (per Stage 1.5 XML's prescription) is `blarai_project_id: 3`. The key `"blarai"` doesn't exist. `registry.get("blarai")` returns `None`. The function then raises `ValueError`. Every fleet tool that doesn't pass `--project-id` explicitly would fail at startup.

**Quick fix vs. mature fix.** I could just rename `"blarai"` → `"blarai_project_id"` (one line, one project). That works for BlarAI but hardcodes the project name. Tomorrow when devplatform_meta needs the same lookup, we'd add another hardcoded branch.

**Mature fix.** Derive the key from the project root name:
```python
name_key = f"{root.name.lower()}_project_id"
project_id = registry.get(name_key) or registry.get("project_id")
```
For root `C:\Users\mrbla\BlarAI`, `root.name.lower()` is `"blarai"` → key `"blarai_project_id"` → matches yaml. For root `C:\Users\mrbla\devplatform`, key would be `"devplatform_project_id"` → matches the convention. Same one-line cost; works forever.

### F2 — Why I'm revising my own earlier recommendation

In my Stage 1 closure analysis I originally recommended option (a): "ensure Stage 2+ Executor surface has Vikunja MCP tools loaded before comprehension-gate approval." After thinking it through I'm switching to option (b): "codify REST as documented fallback in Stages 2/3/4 XMLs."

**Why I changed my mind.** The MCP tool surface is determined by the Executor harness (GitHub Copilot Chat in your case). Whether `mcp__vikunja__*` tools are visible to a given EA session is not something you and I can reliably control session-to-session — Stage 1 EA had them listed as "deferred" with no `tool_search` mechanism to surface them, and we don't know why. We may not be able to fix it for the next session either.

**REST is byte-identical.** The MCP server literally wraps the same `POST /api/v1/login` + `GET /api/v1/projects` endpoints. The Stage 1 EA proved this end-to-end (project_id=10 created, server-side effects identical). Both paths read credentials from the same place: `mcpServers.vikunja.env.VIKUNJA_PASS` in `.vscode/mcp.json`. Neither bypasses Master Plan §D.1 enforcement, because §D.1 is for fleet RUNTIME (`_vikunja_client.py`), not stage execution.

**The fix.** Add a `<vikunja_access_protocol>` block to Stages 2, 3, 4 XMLs (right after `</comprehension_gate>`) that names MCP as preferred, REST as documented fallback, and the credential source as `.vscode/mcp.json mcpServers.vikunja.env.VIKUNJA_PASS`. This makes the procedure resilient to whatever Executor surface the next session has. No more A5-style anomalies.

### F3 — Fix the regex, not the yaml

**The bug.** Three stage XMLs (2.8, 3.7, 4.7) have a `$BLARAI_PID` resolution preflight:
```powershell
$BLARAI_PID = (Get-Content C:\Users\mrbla\BlarAI\.platform\vikunja_project_ids.yaml |
               Select-String 'blarai:\s*(\d+)').Matches.Groups[1].Value
```
The regex `'blarai:\s*(\d+)'` looks for literal `blarai:` (colon directly after `blarai`). The yaml has `blarai_project_id:` (colon after `_project_id`). No match. `$BLARAI_PID` is empty. Every preflight throws despite Stage 1.4 being correctly complete.

**Two options to consider.** (a) Fix the regex to match what Stage 1 wrote. (b) Add a redundant `blarai: 3` key to the yaml.

**Mature pick: (a).** Why not (b)? Because adding a redundant key means the yaml has two ways to express the same value (`blarai:` AND `blarai_project_id:`). That's a maintenance smell that grows with every new project. The yaml's prefixed-key convention is good (it matches F1's generalized pattern). Keep the yaml clean; fix the three regexes.

**Three identical edits.** Each preflight changes from `'blarai:\s*(\d+)'` to `'blarai_project_id:\s*(\d+)'`. PowerShell code around it is unchanged.

### F4 — Project 6 is fleet-level, not BlarAI-auxiliary

**The semantic problem.** Stage 1 EA recorded Vikunja `project_id=6` ("BlarAI Agent Gates") under `blarai_auxiliary_projects:` in `devplatform/projects/registry.yaml`. By the Vikunja-side name (which has "BlarAI" in it), this classification looks defensible. But:

- **BlarAI/CLAUDE.md** explicitly says: "Gate labels (Agent Gates bus, **project 6**): Gate:Pending-SDO (id 9), Gate:Pending-CoLead (id 10), …, Gate:Escalation (id 14)". So **project 6 is the Agent Gates bus** — a fleet-level mechanism that labels 9–14 reference.
- **After multi-project**, devplatform_meta tasks need a destination for gate states too. If devplatform_meta gates also land in project 6, then project 6 is shared across projects → fleet-level, not BlarAI-only.
- **Future tooling** that queries the registry for fleet-level resources (the way it queries `fleet_reports: 8`) would miss project 6 if it stays in the auxiliaries map.

**Mature fix.** Promote to fleet-level. Edit `devplatform/projects/registry.yaml`:
- Remove `blarai_agent_gates: 6` from `blarai_auxiliary_projects:`.
- Add a new entry under top-level `projects:`:
  ```yaml
    agent_gates_bus:
      vikunja_project_id: 6
      note: "Shared gate bus across all platform-managed projects. Labels 9-14 (Gate:Pending-SDO through Gate:Escalation) post against this project. All projects' SDO / Co-Lead / EA gate states route here. Per BlarAI/CLAUDE.md §Vikunja Conventions (Agent Gates bus, project 6)."
  ```

The Vikunja project's name on the server stays "BlarAI Agent Gates" — renaming server-side is out of scope here (optional Stage 6 hygiene task).

### Q7 — Architecture Decisions (Project 5) is fleet-level for the same reason as Project 6

**The semantic signal.** Stage 1 EA recorded `architecture_decisions: 5` under `blarai_auxiliary_projects:`. But the Vikunja project name is just "Architecture Decisions" — **no project prefix at all**, unlike "BlarAI Infrastructure" (4), "BlarAI Fleet Dashboard" (7), "BlarAI Drafts" (9). This is the same naming-pattern signal that flagged Project 6 (the Agent Gates bus) as fleet-level: when a Vikunja project has no project prefix, it's intended to span projects.

**ADR scope reasoning.**
- BlarAI's project-specific Architecture Decision Records (ADRs) — ADR-010, ADR-011, ADR-012, etc. — already live in `BlarAI/docs/`. They are documented as Markdown files under BlarAI's own repo.
- A separate Vikunja project named "Architecture Decisions" (with no prefix) is most likely the **proposal/review/voting workflow** for ADRs across all platform-managed projects. devplatform_meta will need to file ADRs too (e.g., "should we adopt registry schema convention X?").
- Promoting Project 5 to fleet-level ensures both BlarAI and devplatform_meta route ADR proposals to the same bus.

**Mature fix.** Same pattern as F4. Edit `devplatform/projects/registry.yaml`:
- Remove `architecture_decisions: 5` from `blarai_auxiliary_projects:`.
- Add a new entry under top-level `projects:`:
  ```yaml
    architecture_decisions:
      vikunja_project_id: 5
      note: "Cross-project Architecture Decision Record (ADR) tracking. ... Promoted from blarai_auxiliary_projects per Stage 1 closure review Q7."
  ```

**Worst-case cost.** If Stage 6 investigation discovers all ADR tasks in project 5 reference BlarAI-internal architecture (Hyper-V, OpenVINO, USE-CASE-XXX), re-classification is a one-line revert. The fleet-level classification is the more defensible default given the name; we lose nothing by being wrong here.

### Q8 — Auxiliaries 4, 7, 9 — defer firm decision to Stage 6, but document the ambiguity now

**Why I'm deferring (mature, not lazy).** A correct classification here requires data we don't have at Stage 1:
- Active task count per project (is it being used?)
- Last-update date (when was the last task touched?)
- Task content sample (does the work in here align with the project name?)

Getting this data requires starting Vikunja temporarily and calling `list_tasks` for each project. That's investigation work, properly scoped to Stage 6 hardening (which already has an investigation pattern via item 6.7.5 ticket creation).

**What I am doing.** Annotate each remaining auxiliary entry with YAML comments that:
1. State the provisional classification basis (name pattern, conceptual fit).
2. Flag ambiguity explicitly where the name conflicts with the concept (notably Project 7 "BlarAI Fleet Dashboard" — name has BlarAI prefix but the "Fleet Dashboard" concept is fleet-level; could be either).
3. Direct Stage 6 to query Vikunja and decide keep / archive / reclassify per project.

**The annotated map will look like:**
```yaml
# BlarAI-scoped auxiliary projects.
# Provisional classification -- actual usage (task count, last-update) not investigated
# at Stage 1. Stage 6 hardening should query each via Vikunja and decide:
#   - Keep as auxiliary (active BlarAI work confirmed)
#   - Archive in Vikunja (no active tasks in 90+ days)
#   - Reclassify (e.g., promote to fleet-level if name was misleading)
blarai_auxiliary_projects:
  # Likely BlarAI Hyper-V VM / OpenVINO / hardware infrastructure tracking.
  blarai_infrastructure: 4
  # AMBIGUOUS: name has BlarAI prefix but "Fleet Dashboard" concept is fleet-level.
  blarai_fleet_dashboard: 7
  # Likely BlarAI scratchpad/drafts project.
  blarai_drafts: 9
```

**Schema unchanged.** The `key: int` form stays; I'm only adding YAML comments. Future tooling that reads `blarai_auxiliary_projects[name]` keeps working. Mature deferral is honest deferral with documented direction, not silent ignoring.

---

## What the EA will do, step by step

The EA's directive ([`GUIDE_POST_STAGE1_CLEANUP_DIRECTIVE.xml`](GUIDE_POST_STAGE1_CLEANUP_DIRECTIVE.xml)) lists seven work items:

| Item | What | File(s) | Result |
|---|---|---|---|
| C1 | F1 fix — generalize `_project_context.py` lookup | `03_STAGE2_REFACTOR_MULTIPROJECT.xml` (item 2.2 inline) | One-block replacement |
| C2 | F2 codification — add `<vikunja_access_protocol>` block | `03_STAGE2_*.xml`, `04_STAGE3_*.xml`, `05_STAGE4_*.xml` | Same block inserted in all three after `</comprehension_gate>` |
| C3 | F3 fix — correct preflight regex | `03_STAGE2_*.xml` (2.8), `04_STAGE3_*.xml` (3.7), `05_STAGE4_*.xml` (4.7) | Three identical regex updates |
| C4 | F4 fix — promote `agent_gates_bus` to fleet-level | `devplatform/projects/registry.yaml` | One block moved + restructured |
| C6 | Q7 fix — promote `architecture_decisions` to fleet-level | `devplatform/projects/registry.yaml` (same commit as C4) | One block moved + restructured |
| C7 | Q8 deferral — annotate remaining auxiliaries with provisional-classification YAML comments | `devplatform/projects/registry.yaml` (same commit as C4/C6) | Comments added; schema unchanged |
| C5 | Log A6, A7, A8, A9, A10 anomalies + execution-log entry | `STATUS.md` | Five new anomaly sections, one log line |

**Two commits land:**
1. **BlarAI** on `chore/platform-extraction`, message: `chore(platform_separation): between-stages cleanup -- Stage 2 XML defect fixes + REST fallback codification + STATUS A6/A7/A8/A9/A10`
2. **devplatform** on `main`, message: `fix(registry): promote agent_gates_bus + architecture_decisions to fleet-level; annotate remaining auxiliaries pending Stage 6 review`

Order doesn't matter (different repos, no dependency).

---

## Verification expectations (after the EA finishes)

The EA's directive ends with 14 verification commands they must run before signaling complete. When the EA pastes their report back, I will independently:

1. Read each modified XML/yaml/markdown file and confirm the prescribed edits landed correctly.
2. Run the same `Select-String` and `git log` commands in this Claude Code session to cross-check.
3. Confirm both repos clean post-commit, fleet still paused, Vikunja still stopped.
4. Confirm Stage 1 work products (devplatform skeleton, etc.) are untouched.

If anything looks off, I'll bounce back to the EA with corrections (same comprehension-gate-style review pattern). Otherwise we move to the Stage 1 → Stage 2 handoff.

---

## What's NOT in scope for this cleanup

The EA directive is explicit about boundaries to prevent scope creep:

- ❌ No edits to Stage 1 work products (devplatform skeleton stays as-is beyond the F4 registry edit).
- ❌ No edits to Stage 0 / Stage 1 / Stage 5 / Stage 6 XMLs (F1–F4 don't surface there).
- ❌ No Vikunja API calls to rename "BlarAI Agent Gates" server-side (that's an optional Stage 6 hygiene task).
- ❌ No `state.json` touches (fleet stays paused).
- ❌ No `stash@{0}` touches (same reason as Stage 1 acknowledgment).
- ❌ No edits to this brief or the directive XML itself (audit artifacts).

---

## After the EA's report comes back

1. You paste the EA's stage-complete report back to me in this chat.
2. I verify against the 10 commands + read the diffs independently.
3. If clean: I recommend **"emit handoff"** — I produce the Guide instance 2 → Guide instance 3 handoff brief covering Stage 2 watchpoints (the Stage 2 EA will need fresh context for the high-risk multi-project refactor).
4. You save the handoff brief, open a fresh Guide chat, attach `GUIDE_PROMPT.xml` + `STATUS.md` + new `GUIDE_HANDOFF_LATEST.xml`, then open a fresh Executor chat with `03_STAGE2_REFACTOR_MULTIPROJECT.xml` + `STATUS.md`.

---

## Decisions still pending after this cleanup

All Stage-1-closure-surfaced questions (F1, F2, F3, F4, Q7, Q8) are addressed by this consolidated cleanup pass. The only remaining open items are intentional Stage 6 follow-ons documented in the registry YAML comments:

- **Stage 6 / A10**: Investigate auxiliary projects 4, 7, 9 (`BlarAI Infrastructure`, `BlarAI Fleet Dashboard`, `BlarAI Drafts`) — start Vikunja, query `list_tasks` per project, decide keep/archive/reclassify per project (especially Project 7 where the BlarAI prefix conflicts with the "Fleet Dashboard" concept). Pattern follows existing 6.7.5 ticket creation.
- **Stage 6 / A9 follow-up**: Confirm `architecture_decisions` (Project 5) classification by inspecting actual ADR content. If all ADR tasks reference BlarAI-internal architecture (Hyper-V, OpenVINO, USE-CASE-XXX), re-demote; otherwise the fleet-level promotion stands.
- **Stage 6 / A8 hygiene (optional)**: Rename Vikunja project "BlarAI Agent Gates" → "Agent Gates" via `mcp__vikunja__update_project` for naming consistency with its fleet-level role.

None of these block Stage 2. The Stage 2 EA can proceed cleanly.

---

## Quick reference

- **Forward this XML to the still-open Stage 1 EA chat**: [`GUIDE_POST_STAGE1_CLEANUP_DIRECTIVE.xml`](GUIDE_POST_STAGE1_CLEANUP_DIRECTIVE.xml)
- **Keep this brief open for context**: you're reading it
- **Next action**: paste the directive XML into the Stage 1 EA chat and tell it: *"Execute this between-stages cleanup directive."*
