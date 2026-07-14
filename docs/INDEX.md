# BlarAI Documentation Index

*A navigation map of the BlarAI documentation surface. Additive and
descriptive only — this file **moves and deletes nothing**. When a doc's
location and this index disagree, the doc on disk wins; open an issue rather
than trusting a stale line here.*

**Created for Vikunja #267 (doc-sprawl audit).** #267 also asks for the
*destructive* half of doc hygiene — archiving superseded files, adding
`status:` frontmatter, reducing the top-level `docs/` count to ≤30. None of
that is done here; this pass is the safe, additive slice (a navigation index +
a flagged inventory for Lead-Architect triage). See
[§ Doc-Sprawl Notes](#doc-sprawl-notes-for-la-triage) at the bottom.

**The single source of truth for *current* project state is `CLAUDE.md`
(§ Active State) — not this index.** This file tells you *where things live*;
`CLAUDE.md` tells you *what is true right now*.

---

## 1. Start here — repo-root canonical surfaces

These live at the **repo root**, not under `docs/`. They are the load-bearing
portfolio and governance surfaces.

| File | What it holds | When to read |
|------|---------------|--------------|
| `CLAUDE.md` | Project instructions + the live **Active State** section (sprint state, test baseline, open issues). | First, every session. The authoritative "what is true now." |
| `BUILD_JOURNAL.md` | Chronological first-person narrative of how BlarAI was built — failures, recoveries, trade-offs. Portfolio-load-bearing. | For the story/judgment behind a change; before appending your own entry. |
| `LESSONS.md` | Distilled numbered lessons led by a curated **Canonical Tier (~20 classes)**. Its top Rules section is the curation SOP. | Before minting a lesson (search first); to learn the project's judgment vocabulary. |
| `FIELD_NOTES.md` | Mechanical, environment-specific gotchas (API traps, engine dialects, driver quirks). Reference, not judgment. | Grep it before touching a named surface (OpenVINO, Windows, a regex engine). |
| `Use Cases_FINAL.md` | Canonical definitions of the 7 Use Cases — the full product vision. | To confirm what a Use Case (UC-001..010) actually scopes. |
| `PERFORMANCE_LOG.md` | Human-narrative performance measurements (community-grade, reproducible). Paired with `docs/performance/` JSON. | When recording or citing a hardware/model benchmark. |
| `README.md` / `SECURITY.md` / `LICENSE.md` / `COMMERCIAL-LICENSE.md` | Public-facing project framing, security policy, licensing. | Public/onboarding context. |
| `AGENTS.md` | Codex agent instructions (peer to `.github/copilot-instructions.md`). | When working as / configuring a non-Claude agent surface. |
| `AI Risk Assessment and Mitigation Strategy.md`, `Critical Design Review — Red Team Assessment.md`, `Phase_2_Test_Plan.md`, `Enabling XAttention on Intel Arc - Gemini Study.md` | Long-form root-level studies (risk, red-team CDR, Phase-2 test plan, an Arc XAttention study). | Deep dives on those specific topics. |

---

## 2. Key living top-level `docs/` files

The genuinely current documents at `docs/` top level. (The large historical
clusters — Phase-5 `Task4.*` and `P5_*` prompts, upstream-contribution
drafts — are described in [§4](#4-historical--working-artifact-families-top-level)
and flagged in the sprawl notes; they are **not** listed here individually.)

| File | What it holds | When to read |
|------|---------------|--------------|
| `IMPLEMENTATION_PLAN.md` | Priority-1 Core Loop implementation plan; milestone tracking across all phases. | Planning against the milestone spine. |
| `DECISION_REGISTER.md` | SSOT **index** of runtime `DEC-01..10` + runtime trust/security ADRs + a pointer to cross-repo cf-program ADRs. Must be updated in the same change that authors/amends a runtime ADR/DEC. | To find which ADR/DEC governs a decision. |
| `TEST_GOVERNANCE.md` | Test policy, pytest marker taxonomy, named-scope baseline management. | Before changing test selection, markers, or the standing gate. |
| `POST_OPERATIONAL_MATURATION_LEDGER.md` | Phase-5+ milestone records — **FROZEN at Entry 52** (2026-04-22). New entries go to `docs/ledger/`. | Historical Phase-5 milestones only; do not append here. |
| `GAP_TO_OPERATIONAL_REPORT.md` | Frozen Phase-4 closed record (operational-gap closure). | Historical Phase-4 reference. |
| `SECURITY_ASSESSMENT.md` | Validated security findings. | Security posture review. |
| `TEST_AUDIT_FINDINGS.md` | Test Quality Audit findings (Task 7 / Sprint 8). | Test-quality context. |
| `HOWTO_FEATURES_NON_DEV.md` | Non-dev feature how-to guide. | Operator feature usage. |
| `RUNBOOK_NON_DEV_OPERATIONS.md` | Non-dev operations runbook. (Authoritative LA runbooks live in `docs/runbooks/`.) | Operator ops. |
| `FLEET_DISPATCH_LOG.md` | Durable long-term fleet-dispatch KPI log. | Dispatch-fleet performance history. |
| `LEARNING_LOOPS_PROGRAM_DESIGN.md` | Operator-feedback-memory + self-improving-fleet program design (ADR-036/037). | Learning-loops / feedback-memory work. |
| `MODEL_EVALUATION_QWEN36_27B.md` | Qwen3.6-27B / ThinkingCap successor evaluation. | Model-upgrade watch (successor to Qwen3-14B). |
| `MODEL_SHARING_INVESTIGATION.md` | "One 14B, not two" shared-inference investigation. | Model-sharing / co-residency memory. |
| `openvino_2026.2_upgrade_opportunity_catalog.md` | OpenVINO 2026.1.0 → 2026.2.1 upgrade-opportunity catalog. | OpenVINO substrate upgrades. |
| `uc010_dispatch_asset_pipeline.md` | UC-010 asset generation for headless dispatch builds. | UC-010 / dispatch asset work. |
| `eagle3_conversion_findings_2026-06-29.md` | EAGLE-3 draft-head OpenVINO conversion findings. | Speculative-decode draft-model research. |
| `active_tasks.yaml` | Legacy static task list. **Vikunja is now the task SSOT** — likely stale (see sprawl notes). | Historical only. |

---

## 3. `docs/` subdirectory map

Ordered roughly by how often you need them. Counts are git-tracked files
(2026-07-11).

| Directory | Files | What it holds | When to read |
|-----------|------:|---------------|--------------|
| `adrs/` | 34 | Architecture Decision Records **ADR-005 … ADR-038** (rationale + trade-offs for every locked decision). Indexed by `DECISION_REGISTER.md`. | To read the *why* behind a locked architectural/security decision. |
| `ledger/` | 31 | Per-entry maturation ledger (Q1-1 format, 2026-04-22 onward) — the **live** successor to the frozen monolithic ledger. Has `README.md`. | Recording or reading a Phase-5+ milestone entry. |
| `sprints/` | 276 | Per-sprint strategic docs (SDV / SCR / SWAGR), reports, and `_templates/`. `ACTIVE_SPRINT.md` is the live sprint pointer. | Sprint kickoff, close, or audit. Already well-organized (out of #267 scope). |
| `runbooks/` | 23 | Operator/LA runbooks — go-live ceremonies, reboot checklist, disaster recovery, MCP sync, VM lifecycle. `LA_OPERATIONS_INDEX.md` indexes them. | Running an operational ceremony or recovery. |
| `governance/` | 17 | Fleet governance doctrine — rule-engine, circuit-breaker, IPC protocol, session-state, observability, PII-redaction, AIGP study plan, `handoff-brief-template.md`. `README.md` is the landing page. | Governance/doctrine work. Out of #267 scope (Sprint 9 rebuilt it). |
| `research/` | 16 | Dated research studies — agent protocols, the Coordinator program (#841), dispatch leverage, assistant memory, Kagi key handling. Design-only. | Grounding a design decision in prior research. |
| `security/` | 54 | Security audits, the capstone presentation deck, egress machinery/activation records, `DATA_MAP.md`, guest-parser/oracle provisioning records, PCR-seal & trust-root POCs, UC-003 live-fetch proofs. | Security review, egress posture, capstone. **See sprawl note on node_modules bloat.** |
| `performance/` | 140 | Machine-readable perf JSON + `perf_history` — the dataset feeding OpenVINO/HuggingFace community contribution. `README_coresident_ut.md` explains the co-resident harness. | Recording or citing benchmark data (pairs with root `PERFORMANCE_LOG.md`). |
| `journal_fragments/` | 6 | Parallel-safe inbox for `BUILD_JOURNAL.md` entries — one file per session, folded in at quiet points. `README.md` has the SOP. | When appending a journal entry during parallel/multi-session work. |
| `handoffs/` | 0 (gitignored) | Context-exhaustion handoff briefs — a gitignored working-tree dir. | When authoring/consuming a session handoff brief. |
| `reports/` | 38 | Dated SDO / co-lead / EA completion + firing-exit reports. Historical fleet-process records. | Fleet-process history. Out of #267 scope (already organized). |
| `scheduled/` | 22 | The EA dispatch queue (`ea_queue/`) + its archive of executed EA prompts by sprint. | Fleet dispatch-queue history. |
| `learning/` | 25 | Presentation decks (`fable5_deck/`, `lessons_deck/`) — portfolio/learning artifacts with speaker notes. | Portfolio deck work. |
| `guide-workstreams/` | 18 | Guide-role workstream trackers (OpenVINO contribution, upstream shepherding). Each has a `README.md`. | Tracking a Guide-role external-contribution workstream. |
| `upstream/` | 10 | OpenVINO upstream-contribution working sets (e.g. `725_xgrammar_stop_token/`) + GPU-from-source build plan. | External OSS contribution work. |
| `claude_projects/` | 6 | Claude Desktop "project" custom-instruction sets (CO_LEAD / SDO / EA / CORE_REFERENCE) + UI-paste. `README.md`. | Configuring a Claude Desktop project surface. |
| `archive/` | 121 | Retained superseded docs (currently `platform_separation/`). **This is the destination for #267's archival step.** | Recovering a superseded doc. |
| `design/` | 1 | Engineering design docs (swap-driver increment 2). | Design deep-dive. |
| `battery/` | 1 | Battery-campaign prescope. | Overnight battery-campaign context. |
| `claude_cowork/` | 1 | Claude CoWork EA instructions. | CoWork surface config. |
| `demo/` | 0 (gitignored) | Demo capture assets. | Demo prep. |

---

## 4. Historical / working-artifact families (top-level)

These large top-level clusters are **historical working artifacts** (Phase-5,
roughly April–June 2026). They are kept for the portfolio record but are **not
live guidance** — do not read them as current. They are the primary target of
#267's archival step (see sprawl notes).

- **Phase-5 `Task4.*` cluster (~63 files)** — Task-4.x production-config
  feasibility era: execution reports, summaries, `_v1`/`_v2.xml` execution
  prompts, `_SDO_MESSAGE.xml`, `_EA_INIT*.xml`. The single largest cluster.
- **`P5_*` / `P5-*` agent prompts + feasibility (~38 files, 28 of them `.xml`)** —
  SDO/EA initiation prompts, task continuations, feasibility execution prompts
  (`P5_FEASIBILITY_*`, `FEASIBILITY_*`).
- **OpenVINO / upstream contribution drafts (~20 files)** — `GENAI_FEATURE_REQUEST_*`,
  `ISSUE_*`, `PR_*`, `QWEN35_CONTRIBUTION_GUIDE`, `OPENVINO_CONTRIBUTION_PLAN_*`,
  `VPUX_*`, `NPU_SMOKE_TEST_REPORT`. A `docs/upstream/` subdir already exists as
  the natural home for these.
- **UAT plans (4 files)** — `UAT-1/2/3_ACCEPTANCE_PLAN.md` + `UAT-3_EXECUTION_WORKSHEET.md`
  (Phase-4 acceptance).

---

## Doc-Sprawl Notes (for LA triage)

**Flags only. Nothing here has been moved, renamed, or deleted.** This section
records what an inventory pass surfaced so the Lead Architect can decide the
destructive half of #267 (archive / drafts / lifecycle frontmatter). Doing that
reorganization is explicitly *out of scope* for this additive pass.

### Current state (2026-07-11)

- **Top-level `docs/` tracked files: 151** (88 `.md`, 67 `.xml` — nearly every
  XML is Phase-5 agent-orchestration scaffolding — plus `active_tasks.yaml`,
  and one `.log` / one `.litcoffee`). The `.log`/`.litcoffee` are odd for a docs
  tree and worth an eyeball.
- **`docs/` total: 995 git-tracked files** across 21 subdirectories.
- #267 was filed at 183 top-level files (2026-04-24). Top-level is now 151 —
  some cleanup has already happened (e.g. the `CLAUDE_DESKTOP_CONFIGURATION_AGENT_INITIATION_v1/v2/v3.xml`,
  `CO_LEAD_ARCHITECT_INITIATION_v1/v2.xml`, and `DOMAIN8_DEC11_*` triplets the
  ticket cited are **already gone** from top level; the CO_LEAD/SDO/EA
  instructions now live consolidated under `docs/claude_projects/`).

### Sprawl clusters (candidates for #267's `docs/archive/<year>/` move)

| Cluster | ~Count | Nature | Candidate destination |
|---------|-------:|--------|-----------------------|
| Phase-5 `Task4.*` | ~63 | Apr-2026 Task-4 execution reports/summaries + `_v1/_v2.xml` prompts + SDO/EA messages | `docs/archive/2026/phase5_task4/` |
| `P5_*` / `P5-*` prompts + feasibility | ~38 (28 xml) | SDO/EA initiation & continuation prompts, feasibility execution prompts | `docs/archive/2026/phase5_prompts/` |
| OpenVINO/upstream contribution drafts | ~20 | Issue/PR/feature-request working drafts | consolidate under existing `docs/upstream/` |
| `UAT-*` | 4 | Phase-4 acceptance plans | `docs/archive/2026/uat/` |

The remaining ~26 top-level files are the **living docs** listed in [§2](#2-key-living-top-level-docs-files)
plus a few standalone studies — a plausible ≤30 "active top-level" target once
the four clusters above are archived, matching #267's acceptance criterion.

### Versioned families without a "this is live" signal

- `P5_SDO_INITIATION_PROMPT_v4.0.xml` **+** `v5.0.xml` — two versions, no pointer
  to the live one.
- `Task4.9_v1.xml` **+** `Task4.9_v2.xml` (and the `Task4.9a_v1` / `Task4.9b_v2` /
  `Task4.9c_v1` / `Task4.9d_v1` siblings) — `_v1`/`_v2` execution-prompt pairs.
- `FEASIBILITY_CONTEXT_WINDOW.md` **+** `_ADDENDUM.md` **+** `_CEILING_ADDENDUM.md`
  (`P5-FEASIBILITY-001/002/003`) — a triplet. These read as *additive addenda*
  (each supersedes the prior decision), so likely legitimate, but the
  relationship is implicit — a one-line "supersedes/superseded-by" header on
  each would resolve it.

### Likely-stale

- **`docs/active_tasks.yaml`** — a static task list, but Vikunja is now the task
  SSOT. Almost certainly stale; verify before archiving.
- **`docs/reports/*_sdo_firing_exit_v1..v7.md`** — seven versioned "firing exit"
  reports from 2026-04-21/22; only the last is plausibly of record.

### Ticket premises that have drifted (for whoever executes #267)

- #267 says to extend `docs/governance/STYLE.md` (from Sprint 9). **There is no
  `STYLE.md`** — the governance landing page is `docs/governance/README.md`. The
  lifecycle convention (#267 step 4) should target a new
  `docs/governance/doc-lifecycle.md` or `README.md`, not a non-existent
  `STYLE.md`.
- #267's cited example triplets (`CLAUDE_DESKTOP_CONFIGURATION_AGENT_INITIATION_*`,
  `CO_LEAD_ARCHITECT_INITIATION_*`, `DOMAIN8_DEC11_*`) are **already resolved** —
  the acceptance criteria wording should be refreshed against current state
  before the sprint runs.

### Hygiene: recursive-scan bloat (not committed sprawl, but real)

- `docs/security/capstone_2026-06/_validate/node_modules/` and
  `docs/security/explainers/_validate/node_modules/` hold **~19,200 untracked
  files** between them (npm deps for the mermaid/cytoscape/katex diagram
  validators). They are **gitignored** — not committed sprawl — but they
  balloon any recursive `find`/glob/grep over `docs/` from ~1,000 to ~20,400
  files, which slows and pollutes fleet-agent scans. Worth confirming a
  `.gitignore` covers them and, ideally, relocating the `_validate` toolchains
  out of `docs/` entirely.

---

*End of index. To extend: add the row, keep it descriptive, move/delete
nothing here — reorganization is #267's separate, LA-gated step.*
