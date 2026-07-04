---
sprint_id: 10
ea_number: 1
authored_by: ea_code
authored_on: 2026-05-11
parent_head: 9263eb26457e2f99d69b6b16f09d33645f0cf292
devplatform_parent_head: 544eb0921af8441c68ab85bd3c03cf0b082a0656
---

# Sprint 10 — Doctrine Classification Matrix

## 1. Summary statistics

### Source file line counts (audit-time)

| File | Lines | Notes |
|---|---:|---|
| `C:\Users\mrbla\BlarAI\CLAUDE.md` | 216 | SDV §1.2/§5.1 baseline cited ~283; current shorter (see §4 Finding F-1). |
| `C:\Users\mrbla\BlarAI\.github\copilot-instructions.md` | 240 | SDV baseline cited ~265; current within drift band. |
| `C:\Users\mrbla\BlarAI\AGENTS.md` | 18 | SDV baseline cited ~24; current 18 — pointer stub. |
| **BlarAI total** | **474** | SDV baseline ~572; -98 drift (see §4 F-1). |
| `C:\Users\mrbla\devplatform\CLAUDE.md` | 4 | Placeholder stub — Stage 6 pre-population (see §4 F-2 + §5). |
| `C:\Users\mrbla\devplatform\.github\copilot-instructions.md` | 2 | Placeholder stub. |
| `C:\Users\mrbla\devplatform\AGENTS.md` | 2 | Placeholder stub. |

### Row counts per partition

| Partition | Count |
|---|---:|
| KEEP-BlarAI | 28 |
| MOVE-devplatform | 19 |
| MIRROR-both | 7 |
| DELETE | 1 |
| **Total rows** | **55** |

### Row counts per tag

| Tag | Count |
|---|---:|
| DECISION-CLEAR | 49 |
| DECISION-PENDING-LA | 6 |
| **Total** | **55** |

### Coverage check

- `CLAUDE.md` `##` headers: 12 (all covered ≥1 row).
- `.github/copilot-instructions.md` top-level XML elements: 12 (all covered ≥1 row); named `<rule>` elements: 14 (covered as sub-rows under `<interaction_rules>`); named `<phase>` elements: 5 (covered as sub-rows under `<phase_directives>`).
- `AGENTS.md` paragraph blocks: 5 rows (exceeds ≥3 floor).

## 2. Matrix table

Columns: **Source** (filename short) — **Section/element** — **Lines** — **Partition** — **Tag** — **Rationale**.

### CLAUDE.md rows

| # | Source | Section/element | Lines | Partition | Tag | Rationale |
|--:|---|---|---|---|---|---|
| 1 | CLAUDE.md | Title header `# BlarAI — Project Instructions for Claude Desktop` | 1 | KEEP-BlarAI | DECISION-CLEAR | Title scoped to BlarAI repo; devplatform's CLAUDE.md authors its own title. |
| 2 | CLAUDE.md | `## Project Identity` | 3-10 | KEEP-BlarAI | DECISION-CLEAR | SDV §5.3 KEEP-BlarAI candidates (a) UCs, (b) hardware; describes BlarAI runtime mission + UC operational state. |
| 3 | CLAUDE.md | `## Architecture Summary` | 12-22 | KEEP-BlarAI | DECISION-CLEAR | SDV §5.3 KEEP-BlarAI (b) hardware, (c) VM/vsock/OpenVINO/Qwen3, (d) privacy mandate. Two-tier privacy callout is BlarAI runtime doctrine. |
| 4 | CLAUDE.md | `## Task Tracking — Vikunja (MCP)` intro | 24-31 | KEEP-BlarAI | DECISION-CLEAR | SDV §5.3 explicit: "MCP wiring locations + 19 tools direct access — LA uses interactively from BlarAI working directory — STAYS in BlarAI". |
| 5 | CLAUDE.md | `### Available MCP Tools` (19-tool list) | 33-38 | KEEP-BlarAI | DECISION-CLEAR | SDV §5.3 explicit: "MCP tool list (the 19 tools by name) — STAYS in BlarAI". |
| 6 | CLAUDE.md | `### Vikunja Conventions` (labels, priority, ids) | 40-57 | KEEP-BlarAI | DECISION-CLEAR | SDV §5.3 explicit: "labels, priority scale, task title pattern — STAY in BlarAI's CLAUDE.md". |
| 7 | CLAUDE.md | `### Vikunja Server` (startup commands) | 59-66 | KEEP-BlarAI | DECISION-CLEAR | SDV §5.3 explicit: "server-startup commands — STAY in BlarAI". Note: command body references `C:\Users\mrbla\devplatform\tools\vikunja` — that is a path the LA runs from BlarAI; doctrine remains in BlarAI per §5.3 dispositive test. |
| 8 | CLAUDE.md | `### Vikunja Bridge (Sandbox Agents)` (host-side daemon) | 68-87 | MOVE-devplatform | DECISION-CLEAR | SDV §5.3 explicit: "Vikunja MCP bridge daemon doctrine — fleet infrastructure — MOVES to devplatform's CLAUDE.md". |
| 9 | CLAUDE.md | `## Project Structure` (tree diagram) | 89-108 | KEEP-BlarAI | DECISION-CLEAR | SDV §5.3 KEEP-BlarAI (f) BlarAI project structure (services/, shared/, launcher/, etc.). |
| 10 | CLAUDE.md | `## Current Active Sprint (DEC-15)` intro + `### Single source of truth` | 110-127 | MOVE-devplatform | DECISION-CLEAR | SDV §5.3 explicit: "§Current Active Sprint (DEC-15) — fleet sprint lifecycle — MOVES to devplatform's CLAUDE.md". |
| 11 | CLAUDE.md | `### Derived paths` table (SDV/SCR/SWAGR/reports) | 129-137 | MOVE-devplatform | DECISION-CLEAR | Part of MOVE block above; DEC-15 artifact paths are fleet-lifecycle. |
| 12 | CLAUDE.md | `### Human pointer` (ACTIVE_SPRINT.md) | 139-141 | MOVE-devplatform | DECISION-PENDING-LA | Section describes a file (`docs/sprints/ACTIVE_SPRINT.md`) that **stays in BlarAI** per SDV §5.3 ("`docs/sprints/ACTIVE_SPRINT.md` file itself stays in BlarAI"), but the descriptive doctrine is fleet-lifecycle. Provisional partition MOVE-devplatform; BlarAI side gets one-line pointer per §5.3 cross-reference style. Flagged PENDING-LA in case LA prefers KEEP-BlarAI for navigational convenience. |
| 13 | CLAUDE.md | `### When agents should consult the SDV` | 143-149 | MOVE-devplatform | DECISION-CLEAR | Describes Co-Lead / SDO / Sprint Auditor / EA Code reading rules — fleet operating model per SDV §5.3 (a). |
| 14 | CLAUDE.md | `### What this pattern does NOT do` | 151-155 | MOVE-devplatform | DECISION-CLEAR | DEC-15 boundary conditions for fleet sprint lifecycle. |
| 15 | CLAUDE.md | `### References` (DEC-15 proposal + templates + ACTIVE_SPRINT + active_tasks.yaml) | 157-162 | MOVE-devplatform | DECISION-CLEAR | DEC-15 navigation refs; partition matches parent §Current Active Sprint. |
| 16 | CLAUDE.md | `## Phase History (Condensed)` table | 164-172 | KEEP-BlarAI | DECISION-CLEAR | SDV §5.3 KEEP-BlarAI (i) Phase History (Phases 1-5). |
| 17 | CLAUDE.md | `## Locked Architectural Decisions` block | 174-180 | KEEP-BlarAI | DECISION-CLEAR | SDV §5.3 KEEP-BlarAI (e) locked ADRs (010, 011, 012) and DEC-01 through DEC-10. Cluster row per comprehension §10 granularity call. |
| 18 | CLAUDE.md | `## Active State` (sprint state, test baseline, ISS-1/2/3, F-1) | 182-191 | KEEP-BlarAI | DECISION-CLEAR | SDV §5.3 KEEP-BlarAI (j) §"Active State" (current sprint, current HEAD, test baseline, open issues). EA-2 refreshes content per SDV §5.1 #2; classification preserves location. Staleness defect tracked at §4 F-3. |
| 19 | CLAUDE.md | `## Agent Operating Model` intro + 7-step list | 193-203 | MOVE-devplatform | DECISION-CLEAR | SDV §5.3 explicit: "§Agent Operating Model subsection (Comprehension Gate + Fleet-Pause SOP) — this entire subsection of CLAUDE.md is fleet operating model — MOVES to devplatform". |
| 20 | CLAUDE.md | `### Comprehension Gate` | 205-207 | MIRROR-both | DECISION-CLEAR | SDV §5.3 explicit: "EA-1's default partition is MIRROR-both". Both audiences (interactive Claude Desktop in BlarAI + fleet sessions in devplatform) need the protocol locally without cross-repo lookup latency. BlarAI side framed for runtime-task work; devplatform side framed for fleet-infrastructure work. |
| 21 | CLAUDE.md | `### Fleet-Pause SOP` (authority, helper, manual fallback, decision table) | 209-253 | MOVE-devplatform | DECISION-CLEAR | SDV §5.3 explicit: "Fleet-Pause SOP — clearly fleet doctrine, MOVE to devplatform. BlarAI's CLAUDE.md and `.github/copilot-instructions.md` get one-line cross-reference pointers". |
| 22 | CLAUDE.md | `## Coding Standards` (PEP 8, gate order, etc.) | 255-262 | KEEP-BlarAI | DECISION-CLEAR | SDV §5.3 explicit: "Coding Standards — STAYS in BlarAI (BlarAI runtime code is what's being coded)". |
| 23 | CLAUDE.md | `## Key Documents` table | 264-274 | KEEP-BlarAI | DECISION-CLEAR | Pointers to BlarAI-side docs (IMPLEMENTATION_PLAN.md, ledgers, TEST_GOVERNANCE.md, Use Cases_FINAL.md, pyproject.toml); all BlarAI runtime artifacts. |
| 24 | CLAUDE.md | `## Security Constraints` (fail-closed, no network, VM isolation, vsock, privacy) | 276-283 | KEEP-BlarAI | DECISION-CLEAR | SDV §5.3 KEEP-BlarAI (d) security mandates (privacy, fail-closed, no external network). |

### .github/copilot-instructions.md rows

| # | Source | Section/element | Lines | Partition | Tag | Rationale |
|--:|---|---|---|---|---|---|
| 25 | copilot-instructions.md | XML root `<copilot_instructions version="3.2">` + `</copilot_instructions>` envelope | 1, 266 | MIRROR-both | DECISION-CLEAR | Both repos retain the XML envelope. Per SDV §5.3 "XML preservation — well-formedness in both repos; if a parent element exists only in one repo, the children that move take their parent with them". |
| 26 | copilot-instructions.md | `<project_vision>` (mission, scope_current, longevity) | 3-7 | KEEP-BlarAI | DECISION-CLEAR | BlarAI runtime mission + UC scope + decades longevity — KEEP candidates per SDV §5.3 (a) UCs, (b) hardware-rooted trust. |
| 27 | copilot-instructions.md | `<user_identity>` (role, technical_profile, workflow, communication_preference) | 9-14 | MIRROR-both | DECISION-PENDING-LA | LA identity applies to BOTH interactive runtime sessions AND fleet sessions. Provisional MIRROR-both — BlarAI version framed for runtime context; devplatform version framed for fleet context. Flagged PENDING-LA: LA may prefer MOVE-devplatform (fleet-operator framing) with a BlarAI cross-reference, since the `<workflow>` element references "Strategic Development Orchestrator that tracks roadmap state and generates scoped XML prompts" — fleet-shaped. |
| 28 | copilot-instructions.md | `<chat_role_taxonomy><role name="Strategic_Development_Orchestrator">` | 17-31 | MOVE-devplatform | DECISION-CLEAR | SDV §5.3 (a) fleet doctrine — describes SDO agent + cron-fired wake template + prompt authoring. |
| 29 | copilot-instructions.md | `<chat_role_taxonomy><role name="Execution_Agent">` | 32-44 | MOVE-devplatform | DECISION-CLEAR | SDV §5.3 (a) fleet doctrine — describes EA agent. |
| 30 | copilot-instructions.md | `<chat_role_taxonomy>` envelope | 16, 45 | MOVE-devplatform | DECISION-CLEAR | Both children move; per §5.3 XML rule, parent envelope moves with children. |
| 31 | copilot-instructions.md | `<core_operating_principles>` (`<persona>`, `<hierarchy>`) | 47-50 | MIRROR-both | DECISION-CLEAR | "Autonomous Principal Engineer" persona + "User is the Lead Architect" hierarchy apply both repos; both Copilot agents (interactive + fleet) operate under these. |
| 32 | copilot-instructions.md | `<interaction_rules>` envelope | 52, 69 | MIRROR-both | DECISION-CLEAR | Split children — some rules KEEP, some MOVE — so envelope appears in both repos per SDV §5.3 XML rule. |
| 32a | copilot-instructions.md | `<rule name="Autonomous_Project_Momentum">` | 53 | MIRROR-both | DECISION-CLEAR | Generic autonomous-momentum directive applies to both interactive runtime and fleet agents. |
| 32b | copilot-instructions.md | `<rule name="Autonomous_Documentation">` | 54 | MIRROR-both | DECISION-CLEAR | ADR/PRD/Test Plan creation discipline applies to both contexts. |
| 32c | copilot-instructions.md | `<rule name="Autonomous_Control_Flow">` | 55 | MIRROR-both | DECISION-CLEAR | Multi-step execution authority — both contexts. |
| 32d | copilot-instructions.md | `<rule name="Architectural_Decision_Gate">` | 56 | KEEP-BlarAI | DECISION-CLEAR | ADR gating for BlarAI runtime architecture (TUI vs. Web vs. Desktop example) — runtime-architecture concern. |
| 32e | copilot-instructions.md | `<rule name="Operational_Gap_Closure_Order">` | 57 | KEEP-BlarAI | DECISION-CLEAR | References `docs/GAP_TO_OPERATIONAL_REPORT.md` — BlarAI Phase-4 closed record. |
| 32f | copilot-instructions.md | `<rule name="Single_Session_Scope">` | 58 | MOVE-devplatform | DECISION-CLEAR | Single-session execution scope is fleet-EA operating model. |
| 32g | copilot-instructions.md | `<rule name="Operational_Doc_Sync">` | 59 | KEEP-BlarAI | DECISION-CLEAR | References BlarAI ledgers (`POST_OPERATIONAL_MATURATION_LEDGER.md`, `GAP_TO_OPERATIONAL_REPORT.md`). |
| 32h | copilot-instructions.md | `<rule name="Evidence_First_Decision_Gating">` | 60 | MOVE-devplatform | DECISION-CLEAR | Fleet SDO prompt-authoring discipline. |
| 32i | copilot-instructions.md | `<rule name="No_Assumption_When_Measurable">` | 61 | MIRROR-both | DECISION-CLEAR | Empirical-evidence-over-assumption applies both contexts. |
| 32j | copilot-instructions.md | `<rule name="Harness_Declaration_Required">` | 62 | MOVE-devplatform | DECISION-CLEAR | SDO prompt-authoring harness declaration — fleet. |
| 32k | copilot-instructions.md | `<rule name="Harness_Fail_Closed_Gating">` | 63 | MOVE-devplatform | DECISION-CLEAR | Fleet prompt-authoring fail-closed gating. |
| 32l | copilot-instructions.md | `<rule name="Role_Boundary_Enforcement">` | 64 | MOVE-devplatform | DECISION-CLEAR | SDO/EA role boundary — fleet operating model. |
| 32m | copilot-instructions.md | `<rule name="Session_Initiation_Comprehension">` | 65 | MIRROR-both | DECISION-CLEAR | Comprehension gate at session start — both contexts (mirrors §5.3 Comprehension Gate default). |
| 32n | copilot-instructions.md | `<rule name="Attachment_Scope_Discipline">` | 66 | MOVE-devplatform | DECISION-CLEAR | Refs `docs/P5_SDO_INITIATION_PROMPT_v5.0.xml`, `docs/CONTINUATION_PROMPT.md` — SDO session context. |
| 32o | copilot-instructions.md | `<rule name="Non_Dev_Verification_Requirement">` | 67 | MOVE-devplatform | DECISION-CLEAR | SDO prompt-authoring verification-section requirement — fleet. |
| 32p | copilot-instructions.md | `<rule name="Zero_Fluff">` | 68 | MIRROR-both | DECISION-CLEAR | Tone directive — both contexts. |
| 33 | copilot-instructions.md | `<phase_directives>` envelope | 71, 161 | KEEP-BlarAI | DECISION-CLEAR | All five `<phase>` children describe BlarAI runtime phase history (Phases 1-5) — SDV §5.3 (i). |
| 33a | copilot-instructions.md | `<phase name="Phase_1_Architectural_Definition">` | 72-74 | KEEP-BlarAI | DECISION-CLEAR | BlarAI runtime Phase 1 (UC architecture lock). |
| 33b | copilot-instructions.md | `<phase name="Phase_2_Empirical_Validation_and_Scaffolding">` | 75-77 | KEEP-BlarAI | DECISION-CLEAR | BlarAI runtime Phase 2 (HW gates + P1.0-P1.10). |
| 33c | copilot-instructions.md | `<phase name="Phase_3_UI_Requirements_Design_and_Scaffolding">` | 78-89 | KEEP-BlarAI | DECISION-CLEAR | BlarAI runtime Phase 3 (TUI scaffold, ADR-009). |
| 33d | copilot-instructions.md | `<phase name="Phase_4_Operational_Gap_Closure">` | 90-127 | KEEP-BlarAI | DECISION-CLEAR | BlarAI runtime Phase 4 (UAT-1/2/3, sign-off HEAD 8f60259). |
| 33e | copilot-instructions.md | `<phase name="Phase_5_Post_Operational_Development">` | 128-160 | KEEP-BlarAI | DECISION-CLEAR | BlarAI runtime Phase 5 (Tasks 4-7, ADR-011/012, ISS-1/2/3); content references Sprint 5/6/7-era state and is stale (see §4 F-4) but classification is unchanged. |
| 34 | copilot-instructions.md | `<hardware_and_determinism>` (target_soc, hard_ceiling, device_allocation, logic) | 163-168 | KEEP-BlarAI | DECISION-CLEAR | SDV §5.3 (b) hardware (Lunar Lake, Arc 140V, 31.323 GB ceiling); (c) Qwen3-14B + speculative decoding. |
| 35 | copilot-instructions.md | `<security_and_workflow_constraints>` envelope | 170, 218 | KEEP-BlarAI | DECISION-CLEAR | Most children KEEP per SDV §5.3 (d) security mandates + branching/preservation discipline. `<fleet_pause_sop>` child MOVEs (32x below) — envelope stays per XML rule since other children remain. |
| 35a | copilot-instructions.md | `<branching>` | 171 | KEEP-BlarAI | DECISION-CLEAR | Branch-discipline directive applies in BlarAI runtime. |
| 35b | copilot-instructions.md | `<environment>` (Windows 11, PowerShell, WSL2, Hyper-V) | 172 | KEEP-BlarAI | DECISION-CLEAR | SDV §5.3 KEEP — runtime environment specifics. |
| 35c | copilot-instructions.md | `<privacy_mandate>` (no external network calls, fail-closed) | 173 | KEEP-BlarAI | DECISION-CLEAR | SDV §5.3 (d) security mandates. |
| 35d | copilot-instructions.md | `<preservation_rule>` (don't delete failed-validation branches) | 174 | MIRROR-both | DECISION-CLEAR | Failure-branch preservation applies in both repos. |
| 35e | copilot-instructions.md | `<fleet_pause_sop name="LA_Fleet_Pause_SOP">` (verbose procedure) | 175-217 | MOVE-devplatform | DECISION-CLEAR | SDV §5.3 explicit: "Fleet-Pause SOP — clearly fleet doctrine, MOVE to devplatform". BlarAI side replaces with one-line cross-reference pointer. |
| 36 | copilot-instructions.md | `<infrastructure_prerequisites><vm_provisioning>` (BlarAI-Orchestrator VM details) | 220-234 | KEEP-BlarAI | DECISION-CLEAR | BlarAI runtime VM specifics (Hyper-V, Alpine Linux, vsock GUID, hvtools) — SDV §5.3 (c). |
| 37 | copilot-instructions.md | `<vikunja_task_tracking>` (overview, mcp_tools, labels, sdo_responsibilities, ea_responsibilities, conventions) | 236-257 | MIRROR-both | DECISION-PENDING-LA | Mixed content: `<labels>` + `<conventions>` align with SDV §5.3 KEEP (LA uses interactively); `<sdo_responsibilities>` + `<ea_responsibilities>` align with SDV §5.3 MOVE (fleet-agent doctrine). Provisional MIRROR-both: split into BlarAI's "labels + conventions" KEEP-half and devplatform's "SDO/EA responsibilities" MOVE-half, with both halves referencing the live label-id table in BlarAI's CLAUDE.md (row #6) as authoritative source. Flagged PENDING-LA: LA may prefer single-repo location (e.g. consolidate label list in BlarAI CLAUDE.md only, MOVE the whole `<vikunja_task_tracking>` envelope to devplatform with cross-reference). Note: `<labels>` text in this XML still references stale `P5-Active`/`P5-Complete` names that CLAUDE.md row #6 explicitly contradicts — see §4 F-5. |
| 38 | copilot-instructions.md | `<coding_standards>` (python, error_handling, gate_checking) | 259-263 | KEEP-BlarAI | DECISION-CLEAR | SDV §5.3 explicit: "Coding Standards — STAYS in BlarAI". |
| 39 | copilot-instructions.md | `<control_signal>` (EXECUTE DIRECTIVES AUTONOMOUSLY) | 265 | MIRROR-both | DECISION-CLEAR | Closing imperative — both repos use it. |

### AGENTS.md rows

| # | Source | Section/element | Lines | Partition | Tag | Rationale |
|--:|---|---|---|---|---|---|
| 40 | AGENTS.md | Title + Status line (`superseded by CLAUDE.md + .github/copilot-instructions.md`) | 1-3 | KEEP-BlarAI | DECISION-CLEAR | BlarAI-side pointer stub remains (SDV §5.3 "AGENTS.md post-split shape: BlarAI's AGENTS.md remains a thin pointer stub"). EA-2 updates the *pointer text* (referenced files), not the stub identity. |
| 41 | AGENTS.md | "Non-Claude coding agents reading this file" block (CLAUDE.md + copilot-instructions.md pointers) | 5-11 | KEEP-BlarAI | DECISION-PENDING-LA | Provisional KEEP-BlarAI per SDV §5.3 stub-shape. PENDING-LA because SDV §5.3 also says "pointer text is updated to be accurate post-split (...may now point to BlarAI's CLAUDE.md for runtime work + devplatform's CLAUDE.md for fleet work, with a one-line classification of which agent reads which)" — that text update is EA-2 scope, but the LA may want a different ratio of detail (just-a-pointer vs. classify-by-agent-role). The EA-2 author needs an explicit call on length. |
| 42 | AGENTS.md | Vikunja MCP tools-without-MCP pointer (cli.py + README.md) | 13-15 | KEEP-BlarAI | DECISION-CLEAR | Vikunja CLI lives in BlarAI's `tools/vikunja_mcp/`; pointer stays in BlarAI. |
| 43 | AGENTS.md | Sandbox-agents bridge block (state.json / inbox.json / processed.json) | 17-20 | MOVE-devplatform | DECISION-CLEAR | Sandbox-agent file-based bridge IS fleet infrastructure per SDV §5.3 (row #8 above also moves the BlarAI-CLAUDE.md `### Vikunja Bridge (Sandbox Agents)` block to devplatform). AGENTS.md sandbox-agent paragraph follows the same partition. Devplatform's AGENTS.md (≥100 lines per §5.3 floor) carries the operational protocol. |
| 44 | AGENTS.md | Footer ("intentionally minimal" + "do not restore deleted content") | 22-24 | KEEP-BlarAI | DECISION-CLEAR | Stub-policy footer for BlarAI's AGENTS.md; EA-2 may re-phrase to reflect post-split scope. |

### Cross-repo author rows (mature-not-minimal completeness — devplatform side)

These rows enumerate substantive content that EA-3 authors **fresh** in devplatform from the MOVE rows above, plus the SDV §5.3 (a)-(i) "fleet doctrine" enumeration that has no current BlarAI source. Listed for downstream EA-3 reference; no BlarAI source-file partition implication.

| # | Source | Section/element | Lines | Partition | Tag | Rationale |
|--:|---|---|---|---|---|---|
| 45 | (none, devplatform-author) | DEC-11 autonomy budget model (referenced in SDV §5.3 (b); no current source in BlarAI's three doctrine files) | n/a | MOVE-devplatform | DECISION-CLEAR | SDV §5.3 (b) explicit fleet doctrine. EA-3 sources from `tools/autonomy_budget/` code comments + `docs/DEC11_*.xml` (if present) or authors a fresh summary. |
| 46 | (none, devplatform-author) | DEC-12 peer-review lattice + gate flow (referenced SDV §5.3 (c)) | n/a | MOVE-devplatform | DECISION-CLEAR | SDV §5.3 (c). EA-3 sources from `docs/DEC12_PEER_REVIEW_LATTICE_PROPOSAL_v1.xml`. |
| 47 | (none, devplatform-author) | DEC-13 Fleet Reports queue (referenced SDV §5.3 (d)) | n/a | MOVE-devplatform | DECISION-CLEAR | SDV §5.3 (d). EA-3 sources from `docs/DEC13_REPORT_QUEUE_PROPOSAL_v1.xml`. |
| 48 | (none, devplatform-author) | DEC-14.5 `trusted_scope` merge model + `la_merge_approve.ps1` (referenced SDV §5.3 (e)) | n/a | MOVE-devplatform | DECISION-CLEAR | SDV §5.3 (e). EA-3 sources from `tools/scheduled-tasks/la_merge_approve.ps1` + DEC-14.5 governance doc. |
| 49 | (none, devplatform-author) | Wake-template summary (SDO/Co-Lead/EA Code/Sprint Auditor cron-fired wakes — SDV §5.3 (a)) | n/a | MOVE-devplatform | DECISION-CLEAR | SDV §5.3 (a). EA-3 summarizes the four wake-template files in `tools/scheduled-tasks/templates/` (does NOT mirror them verbatim — they remain authoritative). |
| 50 | (none, devplatform-author) | Comprehension-gate-then-stop protocol for autonomous agents (SDV §5.3 (g)) | n/a | MOVE-devplatform | DECISION-CLEAR | SDV §5.3 (g). Distinct from the interactive Comprehension Gate (row #20 MIRROR-both). Autonomous-agent variant emphasizes stop-and-wait-for-review-via-Vikunja-label, not stop-and-wait-for-LA-chat-approval. |
| 51 | (none, devplatform-author) | `autonomy_budget` state.json schema (SDV §5.3 (h)) | n/a | MOVE-devplatform | DECISION-CLEAR | SDV §5.3 (h). EA-3 sources from `tools/autonomy_budget/state.py` + sample state.json. |
| 52 | (none, devplatform-author) | EA prompt XML format conventions + SDO continuation XML format + agent role taxonomy (SDV §5.3 (i)) | n/a | MOVE-devplatform | DECISION-CLEAR | SDV §5.3 (i). Note: agent role taxonomy partial duplication with row #28 + #29 (SDO + EA `<role>` elements); EA-3 deduplicates rather than restating. |
| 53 | (none, devplatform-author) | DEC-15 sprint lifecycle (SDV/SCR/SWAGR/`active_tasks.yaml`/`ACTIVE_SPRINT.md` — SDV §5.3 (f)) | n/a | MOVE-devplatform | DECISION-CLEAR | SDV §5.3 (f). Row #10-15 (BlarAI's `## Current Active Sprint (DEC-15)` block) is the primary source; EA-3 may consolidate per §5.3 "may consolidate or restructure where the BlarAI version was constrained by being a guest in a runtime-focused file". |
| 54 | (none, devplatform-author) | Fleet-pause SOP destination authoring (the verbose procedure from row #35e and row #21 lands here) | n/a | MOVE-devplatform | DECISION-CLEAR | SDV §5.3 explicit. Authored from rows #21 (CLAUDE.md `### Fleet-Pause SOP`) + #35e (`<fleet_pause_sop>` XML element); EA-3 deduplicates to a single canonical statement. |
| 55 | copilot-instructions.md / CLAUDE.md | Stale `P5-Active`/`P5-Complete` label-name references (in `<vikunja_task_tracking><labels>` line 239) — explicitly contradicted by CLAUDE.md row #6 caveat "previous CLAUDE.md revisions referenced `P5-Active`/`P5-Complete` which are NOT on the server" | 239 (XML) | DELETE | DECISION-CLEAR | Defunct label-name reference; SDV §5.2 #2 in-scope "stale or contradictory, removed from both repos with rationale". Authoritative live label list is CLAUDE.md row #6 (id 1 Active, id 2 Complete, etc.). |

## 3. Inter-element references (`.github/copilot-instructions.md` XML)

Cross-element references inside the XML doctrine file. References that **cross partitions** (one endpoint KEEP-BlarAI, other MOVE-devplatform) are noted; per WI-6 + N-7, both endpoint rows in §2 are flagged DECISION-PENDING-LA where the references creates a load-bearing dependency.

| # | Source element | References | Target element | Cross-partition? | Notes |
|--:|---|---|---|---|---|
| IR-1 | `<rule name="Architectural_Decision_Gate">` (row 32d, KEEP) | "See below" for ADR Gate | `<phase_directives>` (row 33, KEEP) | NO | Both KEEP. |
| IR-2 | `<rule name="Operational_Gap_Closure_Order">` (row 32e, KEEP) | "from docs/GAP_TO_OPERATIONAL_REPORT.md" | external file (BlarAI) | NO | External file is BlarAI-side; no cross-partition. |
| IR-3 | `<rule name="Operational_Doc_Sync">` (row 32g, KEEP) | "docs/IMPLEMENTATION_PLAN.md plus the phase-appropriate ledger" | external files (BlarAI) | NO | All BlarAI. |
| IR-4 | `<rule name="Session_Initiation_Comprehension">` (row 32m, MIRROR) | "SDO initiation prompts (docs/P5_SDO_INITIATION_PROMPT_*.xml)" | external fleet docs | NO (MIRROR endpoint) | MIRROR rule references fleet artifacts; devplatform mirror naturally lands there. |
| IR-5 | `<rule name="Attachment_Scope_Discipline">` (row 32n, MOVE) | "docs/P5_SDO_INITIATION_PROMPT_v5.0.xml is SDO-session context only" + "docs/CONTINUATION_PROMPT.md is archived" | external files | NO | Both targets are SDO-session artifacts; MOVE-devplatform with rule. |
| IR-6 | `<rule name="Non_Dev_Verification_Requirement">` (row 32o, MOVE) | "Every execution prompt generated by the SDO MUST include a Verification section" | `<role name="Strategic_Development_Orchestrator">` (row 28, MOVE) | NO | Both MOVE. |
| IR-7 | `<phase name="Phase_4...">` (row 33d, KEEP) | "Operational sign-off gate — COMPLETE (sign-off HEAD 8f60259)" | external file `docs/GAP_TO_OPERATIONAL_REPORT.md` (BlarAI) | NO | Both BlarAI. |
| IR-8 | `<phase name="Phase_5...">` (row 33e, KEEP) | "docs/POST_OPERATIONAL_MATURATION_LEDGER.md" + "docs/TEST_GOVERNANCE.md" | external BlarAI ledgers | NO | Both BlarAI. |
| IR-9 | `<security_and_workflow_constraints>` envelope (row 35, KEEP) | wraps `<fleet_pause_sop>` (row 35e, MOVE) | (parent/child) | **YES — split element** | Envelope stays in BlarAI (other children KEEP); `<fleet_pause_sop>` child MOVEs. Per SDV §5.3 XML rule: BlarAI's envelope retains a `<fleet_pause_sop_pointer>` one-line cross-reference; devplatform's envelope is authored fresh containing the full `<fleet_pause_sop>`. Both rows #35 and #35e remain DECISION-CLEAR but **EA-2 + EA-3 implementers must coordinate well-formedness**: BlarAI's `<fleet_pause_sop_pointer>` element name is unique to avoid grep collision; devplatform names the full element `<fleet_pause_sop>` per current convention. |
| IR-10 | `<vikunja_task_tracking>` envelope (row 37, MIRROR PENDING-LA) | wraps `<labels>` (KEEP-flavor) + `<sdo_responsibilities>` (MOVE-flavor) + `<ea_responsibilities>` (MOVE-flavor) + `<conventions>` (KEEP-flavor) | (parent/children) | **YES — split element, multiple endpoints** | Row #37 already PENDING-LA. The element is internally split between KEEP-flavor children (labels, conventions for LA's interactive use) and MOVE-flavor children (SDO/EA responsibilities — fleet operating model). Two clean resolutions: (A) split envelope: BlarAI keeps `<labels>` + `<conventions>`; devplatform authors fresh `<sdo_responsibilities>` + `<ea_responsibilities>` in its own `<vikunja_task_tracking>` envelope. (B) MOVE whole envelope: BlarAI's CLAUDE.md row #6 (Vikunja Conventions, KEEP) already covers the LA-facing label/convention content; XML envelope can MOVE wholesale to devplatform. LA picks. |
| IR-11 | `<chat_role_taxonomy><role name="Strategic_Development_Orchestrator">` (row 28, MOVE) | "See docs/CONTINUATION_PROMPT.md §prompt_scoping" + "See §vikunja_task_tracking" | rule 32n (MOVE) + row 37 (MIRROR PENDING-LA) | **Conditionally** (depends on IR-10 resolution) | If LA picks IR-10 resolution (A), the §vikunja_task_tracking cross-reference lands cleanly in devplatform's split envelope; if (B), also clean — whole envelope is in devplatform. |
| IR-12 | `<chat_role_taxonomy><role name="Execution_Agent">` (row 29, MOVE) | "See §vikunja_task_tracking" | row 37 (MIRROR PENDING-LA) | **Conditionally** | Same as IR-11. |

**Summary**: 12 cross-element references identified. 2 are split-element / cross-partition load-bearing (IR-9 fleet_pause_sop split; IR-10 vikunja_task_tracking split). 2 are conditional on IR-10 resolution (IR-11, IR-12). 8 are intra-partition or external-file (no cross-partition risk).

## 4. Findings for follow-up tickets

Doctrine-file defects, contradictions, or staleness discovered during audit. Per N-1, **EA-1 records these for LA + Co-Lead triage at SCR / SWAGR; EA-1 does NOT edit the source**.

### F-1 — Line-count drift from SDV baseline

SDV §1.2 baseline cited BlarAI doctrine surface as ~283 + ~265 + ~24 = ~572 lines. Audit-time measurement: 216 + 240 + 18 = 474. Net drift -98 lines (-17%). Most drift is in `CLAUDE.md` (-67) — likely accumulated trimming since SDV authoring (2026-05-09); does not change the partition scope; flagged for completeness. Sprint 10 success-criteria thresholds (e.g. EA-3's devplatform doctrine ≥100 lines per file) are independent of BlarAI surface area, so no scope impact.

### F-2 — devplatform doctrine paths are NOT absent — placeholder stubs exist

The EA-1 prompt §WI-1 expected all three `Test-Path C:\Users\mrbla\devplatform\...` invocations to return `False`. Actual: all returned **`True`**.

Verbatim PowerShell output captured at audit time `2026-05-11T17:48:01Z`:

```
C:\Users\mrbla\devplatform\CLAUDE.md : True
C:\Users\mrbla\devplatform\.github\copilot-instructions.md : True
C:\Users\mrbla\devplatform\AGENTS.md : True
```

Contents:

- `devplatform\CLAUDE.md` (4 lines): placeholder stating "Full content will be written in Stage 6 of platform separation. Until then, use `C:\Users\mrbla\BlarAI\CLAUDE.md` for authoritative guidance."
- `devplatform\.github\copilot-instructions.md` (2 lines): placeholder "Populated in Stage 6 of platform separation."
- `devplatform\AGENTS.md` (2 lines): placeholder "See `CLAUDE.md` and `.github/copilot-instructions.md`. Populated in Stage 6."

**Impact on EA-3 scope**: per SDV §5.1 #3, EA-3 authors devplatform's three doctrine files from scratch with ≥100 lines each. The placeholder stubs are obsolete bootstraps from a prior Stage 6 attempt (cf. archived `docs/archive/platform_separation/STATUS.md`). EA-3's prompt should instruct **overwrite** of the three stubs, not "create new files" — the file paths already exist with placeholder content. The success-criterion ≥100-line floor is unchanged.

**Recommendation**: SDO Phase 2 (EA-3 prompt authoring) should explicitly note the stubs and require EA-3 to overwrite rather than create. No Sprint 10 protocol change needed.

### F-3 — `CLAUDE.md` §Active State references stale sprint state

`CLAUDE.md` line 186 reads: *"Sprint state: Sprints 7, 8, and 9 all COMPLETE. Roster at `docs/active_tasks.yaml` is empty (`active_tasks: []`); fleet will no-op on wake until next `/sprint-kickoff`."* — but `docs/active_tasks.yaml` currently lists Sprint 10 as active. ACTIVE_SPRINT.md is also stale per line 186's own caveat: *"will refresh on the next sprint transition — it currently still lists Sprints 8+9 as active (pre-closure)."*

**Resolution path**: EA-2 (SDV §5.1 #2) explicitly refreshes §Active State from post-Sprint-9 baseline. This is in-scope for EA-2, not a follow-up ticket. Recording here for traceability.

### F-4 — `.github/copilot-instructions.md` `<phase name="Phase_5_Post_Operational_Development">` references stale state

XML element (lines 128-160) describes Phase 5 state up through Task 5/6/7-era ("Task 7 (Test Quality Audit): IN PROGRESS — EA-1, EA-2 merged; EA-3 prompt drafted; EA-4/EA-5 pending") and live HEAD `be52ef4`. Audit-time reality: Task 7 closed by Sprint 8; HEAD has advanced through Sprints 7/8/9/10; ledger entries 42+ → 52 → frozen → `docs/ledger/` Q1-1 entries. Test baseline cited as "755 passed" is contradicted by `CLAUDE.md` row #18 "981 passed, 22 skipped (post-Sprint-8 EA-5)".

**Resolution path**: EA-2 may also refresh this in scope (the XML is a doctrine file EA-2 strips per SDV §5.1 #2 and `<phase name="Phase_5...">` is KEEP-BlarAI per row #33e). Recording for EA-2 awareness so the refresh is bundled into the strip operation rather than a follow-up ticket.

### F-5 — `<vikunja_task_tracking><labels>` references defunct `P5-Active`/`P5-Complete` names

XML line 239 reads: *"P5-Active (blue), P5-Complete (green), Blocked (red), Architecture (purple), Infrastructure (orange), Testing (cyan), Documentation (brown), Security (pink)."* — but `CLAUDE.md` row #6 explicitly says these names are NOT on the server (current canonical names are `Active` id 1, `Complete` id 2, etc.).

**Resolution path**: row #55 in §2 already marks this content as **DELETE** with rationale. EA-2's strip pass removes the defunct names; EA-3's authoring (or EA-2's MIRROR retention of `<labels>`) replicates from CLAUDE.md row #6.

### F-6 — `tools.autonomy_budget` import portability foot-gun

Confirmed by direct test during EA-1 pause invocation: `python -c "from tools.autonomy_budget import state; ..."` fails with `ModuleNotFoundError` when invoked from BlarAI's working directory. Workaround `$env:PYTHONPATH = "C:\Users\mrbla\devplatform"` works. Both `CLAUDE.md` row #21 and `.github/copilot-instructions.md` row #35e contain the broken snippet without the workaround prominently displayed. The SDO continuation prompt's EA-1 pre-flight block explicitly documents the workaround and flags this as "the very bug EA-3 will fix (success criterion #4)".

**Resolution path**: EA-3 success criterion #4 (per SDV §4). In-scope; not a follow-up. Recording for EA-3 awareness so the fix lands in the SOP doctrine text that EA-3 authors (devplatform side) rather than only in the underlying Python entry-point.

### F-7 — `<role>` element naming convention drift (`<role name="..."` vs `<rule name="...">`)

`.github/copilot-instructions.md` mixes two name attribute conventions: (a) `<role name="...">` inside `<chat_role_taxonomy>`, and (b) `<rule name="...">` inside `<interaction_rules>` + `<phase name="...">` inside `<phase_directives>`. Convention is consistent across siblings but creates a minor inter-element-reference enumeration challenge — grep for `name="` returns both rules and phases. Not a defect per se; flagged for EA-3 in case devplatform's authoring adopts a single normalized naming scheme (e.g. all top-level identifiers via `id="...">` to disambiguate). **Recommendation**: EA-3 authors discretion; no scope change. Recording for completeness.

## 5. devplatform target-path absence verification

Per WI-1, three `Test-Path` invocations against the devplatform doctrine paths. Verbatim output (captured at `2026-05-11T17:48:01Z` from worktree `C:\Users\mrbla\BlarAI-worktrees\ea_code_20260511_134650`):

```
PS> Test-Path C:\Users\mrbla\devplatform\CLAUDE.md
True

PS> Test-Path C:\Users\mrbla\devplatform\.github\copilot-instructions.md
True

PS> Test-Path C:\Users\mrbla\devplatform\AGENTS.md
True
```

**Result**: ALL THREE paths return `True`. The EA-1 prompt's expectation of `False`-on-all-three is invalidated by audit-time reality — see §4 F-2 for full content + impact analysis. The placeholder stubs do not block EA-3 (per §4 F-2, EA-3 overwrites them); EA-1 records the finding and proceeds with classification.

**Files present at audit time (line counts)**:

| Path | Lines | First line |
|---|---:|---|
| `C:\Users\mrbla\devplatform\CLAUDE.md` | 4 | `# DevPlatform — Claude Desktop Instructions (placeholder)` |
| `C:\Users\mrbla\devplatform\.github\copilot-instructions.md` | 2 | `# DevPlatform — Copilot Instructions (placeholder)` |
| `C:\Users\mrbla\devplatform\AGENTS.md` | 2 | `# AGENTS.md — devplatform pointer` |

---

**End of matrix.** Downstream consumers: EA-2 (BlarAI strip) and EA-3 (devplatform authorship + SOP fix). LA review of the six DECISION-PENDING-LA rows (#12, #27, #37, #41, plus IR-9 and IR-10 follow-on questions) must precede EA-2 / EA-3 dispatch.
