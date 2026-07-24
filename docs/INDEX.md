---
title: BlarAI Documentation Index
status: living
area: governance
---

# BlarAI Documentation Index

*A navigation map of the BlarAI documentation surface. When a doc's location and
this index disagree, the doc on disk wins; fix the line here in the same change.*

**#267's archive half EXECUTED 2026-07-19** (#945 D6, LA-approved): the top-level
sweep, sprint dirs, scheduler queue, fleet manuals, and frozen monolith all moved
under `docs/archive/` with per-surface INDEX files — see
[docs/archive/](archive/) and `docs/governance/doc-lifecycle.md` for the rules.
Top-level `docs/` now holds only the living set below.

**The single source of truth for *current* project state is `CLAUDE.md`
`<status_snapshot>` — not this index.** This file tells you *where things live*;
`CLAUDE.md` tells you *what is true right now*.

---

## 1. Start here — repo-root canonical surfaces

These live at the **repo root**, not under `docs/`. They are the load-bearing
portfolio and governance surfaces.

| File | What it holds | When to read |
|------|---------------|--------------|
| `CLAUDE.md` | Project instructions + the live `<status_snapshot>` (gate figure, current arcs, open issues). | First, every session. The authoritative "what is true now." |
| `BUILD_JOURNAL.md` | First-person build narrative — **hot file = current month only**; prior months verbatim in `docs/archive/journal/` (+ one-line INDEX); the curated front shelf is `docs/BUILD_JOURNAL_ANTHOLOGY.md` (64 gems, five acts, three reading paths). | For the story/judgment behind a change; before appending your own entry. |
| `LESSONS.md` | Three-tier since 2026-07-19: Rules + **Canonical Tier** + **Canon-32** full text + a one-line index of every lesson (the pre-mint search surface); full text in `docs/archive/lessons/LESSONS_ARCHIVE.md`. | Before minting a lesson (search the index first); to learn the project's judgment vocabulary. |
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
| ~~`IMPLEMENTATION_PLAN.md`~~ | ARCHIVED 2026-07-19 (a phases-1–4 execution history, 0 reads measured in 771 transcripts) → `docs/archive/2026/implementation_plan_phases1-4.md`. Current priorities live in Vikunja. | Historical only. |
| `DECISION_REGISTER.md` | SSOT **index** of runtime `DEC-01..10` + runtime trust/security ADRs + a pointer to cross-repo cf-program ADRs. Must be updated in the same change that authors/amends a runtime ADR/DEC. | To find which ADR/DEC governs a decision. |
| `TEST_GOVERNANCE.md` | Test policy, pytest marker taxonomy, named-scope baseline management. | Before changing test selection, markers, or the standing gate. |
| `POST_OPERATIONAL_MATURATION_LEDGER.md` | A pointer stub — the frozen monolith (Entries 1–52) moved to `docs/archive/ledger/` 2026-07-19. New entries go to `docs/ledger/`. | Historical Phase-5 milestones only; do not append anywhere but `docs/ledger/`. |
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
| ~~`active_tasks.yaml`~~ | ARCHIVED 2026-07-19 → `docs/archive/2026/phase5-prompts/`. **Vikunja is the task SSOT.** | Historical only. |

---

## 3. `docs/` subdirectory map

Ordered roughly by how often you need them. Counts are git-tracked files
(2026-07-11).

| Directory | Files | What it holds | When to read |
|-----------|------:|---------------|--------------|
| `adrs/` | 34 | Architecture Decision Records **ADR-005 … ADR-038** (rationale + trade-offs for every locked decision). Indexed by `DECISION_REGISTER.md`. | To read the *why* behind a locked architectural/security decision. |
| `ledger/` | 31 | Per-entry maturation ledger (Q1-1 format, 2026-04-22 onward) — the **live** successor to the frozen monolithic ledger. Has `README.md`. | Recording or reading a Phase-5+ milestone entry. |
| `sprints/` | ~10 | `ACTIVE_SPRINT.md` (the ≤30-line live pointer), `_templates/`, and `sprint_18/` (moves at the next quiet pass). Sprints 8–17 → `archive/sprints/` (2026-07-19). | The live sprint pointer; historic sprints via `archive/sprints/INDEX.md`. |
| `runbooks/` | 23 | Operator/LA runbooks — go-live ceremonies, reboot checklist, disaster recovery, MCP sync, VM lifecycle. `LA_OPERATIONS_INDEX.md` indexes them. | Running an operational ceremony or recovery. |
| `governance/` | 17 | Fleet governance doctrine — rule-engine, circuit-breaker, IPC protocol, session-state, observability, PII-redaction, AIGP study plan, `handoff-brief-template.md`. `README.md` is the landing page. | Governance/doctrine work. Out of #267 scope (Sprint 9 rebuilt it). |
| `research/` | 16 | Dated research studies — agent protocols, the Coordinator program (#841), dispatch leverage, assistant memory, Kagi key handling. Design-only. | Grounding a design decision in prior research. |
| `security/` | 54 | Security audits, the capstone presentation deck, egress machinery/activation records, `DATA_MAP.md`, guest-parser/oracle provisioning records, PCR-seal & trust-root POCs, UC-003 live-fetch proofs. | Security review, egress posture, capstone. **See sprawl note on node_modules bloat.** |
| `performance/` | 140 | Machine-readable perf JSON + `perf_history` — the dataset feeding OpenVINO/HuggingFace community contribution. `README_coresident_ut.md` explains the co-resident harness. | Recording or citing benchmark data (pairs with root `PERFORMANCE_LOG.md`). |
| `journal_fragments/` | 6 | Parallel-safe inbox for `BUILD_JOURNAL.md` entries — one file per session, folded in at quiet points. `README.md` has the SOP. | When appending a journal entry during parallel/multi-session work. |
| `handoffs/` | 0 (gitignored) | Context-exhaustion handoff briefs — a gitignored working-tree dir. | When authoring/consuming a session handoff brief. |
| `reports/` | 38 | Dated SDO / co-lead / EA completion + firing-exit reports. Historical fleet-process records. | Fleet-process history. Out of #267 scope (already organized). |
| `scheduled/` | 0 | Emptied 2026-07-19 — the executed scheduler-queue XMLs moved to `archive/scheduled/`. | Historical only (via the archive). |
| `learning/` | 25 | Presentation decks (`fable5_deck/`, `lessons_deck/`) — portfolio/learning artifacts with speaker notes. | Portfolio deck work. |
| `guide-workstreams/` | 18 | Guide-role workstream trackers (OpenVINO contribution, upstream shepherding). Each has a `README.md`. | Tracking a Guide-role external-contribution workstream. |
| `upstream/` | 10 | OpenVINO upstream-contribution working sets (e.g. `725_xgrammar_stop_token/`) + GPU-from-source build plan. | External OSS contribution work. |
| `claude_projects/` | 0 | RETIRED-WORLD manuals — moved to `archive/2026/retired_fleet_instructions/` 2026-07-19 (do not read as current guidance). | Historical only. |
| `archive/` | ~700 | The archive wing: `journal/` + `lessons/` + `sprints/` + `scheduled/` + `testing/` + `ledger/` + `2026/` clusters + `platform_separation/`, each with an INDEX/README. **Index → volume: any entry in ≤2 reads.** | Recovering any archived entry or superseded doc. |
| `design/` | 1 | Engineering design docs (swap-driver increment 2). | Design deep-dive. |
| `battery/` | 1 | Battery-campaign prescope. | Overnight battery-campaign context. |
| `claude_cowork/` | 0 | RETIRED-WORLD manual — moved to `archive/2026/retired_fleet_instructions/` 2026-07-19. | Historical only. |
| `demo/` | 0 (gitignored) | Demo capture assets. | Demo prep. |

---

## 4. The archive wing (was: sprawl notes — EXECUTED)

The doc-sprawl inventory that used to live here was **executed on 2026-07-19**
(#267's archive half, run as #945 D6 with LA approval — evidence:
`docs/research/doc-infrastructure-audit-2026-07/`):

- The ~140 loose prompt-era top-level files (Task4.*/P5_*/upstream drafts/UAT plans
  + `active_tasks.yaml`) → `archive/2026/phase5-prompts/` (md movers stamped
  `status: archived`).
- Sprints 8–17 + `iss_2` → `archive/sprints/` (+INDEX); the frozen monolith ledger →
  `archive/ledger/` (+stub); the executed scheduler XMLs → `archive/scheduled/`;
  the retired fleet manuals + 2 runbooks → `archive/2026/retired_fleet_*`.
- Repo-root frozen studies + reference data → `docs/reference/`; root captures →
  `archive/root-debris/`.
- BUILD_JOURNAL/LESSONS rotation + the anthology: see the §1 rows above.

Keeping it clean is no longer vigilance: `tests/security/test_doctrine_freshness.py`
(#945 D8) gate-enforces figure-sync, size budgets, pointer freshness, and a
retired-lexicon scan over the always-loaded surfaces. The known remaining
working-tree hygiene item: the ~19,200 git-ignored node_modules files under
`docs/security/**/_validate/` (regenerable npm toolchains; removal approved as
#945 D9).

---

*End of index. To extend: add the row, keep it descriptive; archives grow via
the monthly rotation, never by hand-sweeping.*
