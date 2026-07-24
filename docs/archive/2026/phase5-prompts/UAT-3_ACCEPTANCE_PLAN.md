---
title: UAT-3_ACCEPTANCE_PLAN
status: archived
area: portfolio
---

# UAT-3 Acceptance Plan — Non-Dev Enablement + UI Functional UAT

**Stage:** UAT-3 (Non-Dev Operational Enablement + UI Feature Acceptance)
**Branch:** `feature/p1-uat1-launcher`
**Baseline:** Post UAT-2 / UAT-2.5 milestone flow
**Date:** 2026-02-25
**Executor:** Lead Architect + Non-Dev UAT Participants + Copilot Agent
**Scope:** USE-CASE-001 (Policy Agent) + USE-CASE-004 (Assistant Orchestrator)

---

## 1. Purpose

UAT-3 validates that a **non-dev operator** can safely and reliably operate the BlarAI system from a cold state and use the UI to execute core workflows without developer intervention.

This stage is the final human-operability gate before operational sign-off. It confirms:
- non-dev onboarding readiness,
- end-to-end UI feature/functionality usability,
- runbook and How-To quality,
- traceable acceptance evidence suitable for onboarding future non-dev team members.

---

## 2. Mandatory Sign-Off Conditions

Operational sign-off is blocked unless all UAT-3 conditions pass:

1. Non-dev participants successfully perform cold-start and normal operation by following documentation only.
2. Supervised UI functional UAT passes for all required workflows.
3. A non-dev-approved runbook exists and is versioned.
4. Non-dev-approved feature/functionality How-To documents exist and are versioned.
5. Artifacts are judged usable for onboarding new non-dev team members.
6. Evidence logs and acceptance records are captured and linked in operational docs.

---

## 3. UAT-3 Scope

### 3.1 In Scope
- Operator education from cold start (host booted, AI system not running).
- Startup, basic operations, error recognition, and controlled shutdown.
- UI workflows: session lifecycle, prompt/response, PGOV-visible outcomes, retry/recovery flows.
- Documentation quality validation for non-dev users.
- Acceptance records and onboarding suitability confirmation.

### 3.2 Out of Scope
- Architecture changes.
- New feature development.
- Deep performance optimization.
- Security model redesign.

---

## 4. Roles and Responsibilities

- **User (Lead Architect / Non-Dev Operator)**
  - The Lead Architect is a non-developer ("vibe coder") who directs AI agents
    to build software. They serve as BOTH the project authority AND the non-dev
    UAT participant. They execute runbook and How-To workflows without developer
    shortcuts, report outcomes, and provide acceptance/rejection decisions.
- **Copilot Agent (Interactive Facilitator)**
  - Guides the user through each UAT-3 phase step by step.
  - Asks comprehension questions (Phase A), provides hands-on instructions (Phase B/C),
    collects acceptance statements (Phase D).
  - Prepares test environment, runs technical validation gates, captures evidence artifacts.
  - Does NOT auto-answer on behalf of the user or skip interactive checkpoints.
- **Observer / Recorder (optional)**
  - Not applicable for this project — the Agent serves as recorder.

---

## 5. Entry Criteria

UAT-3 may begin only when:

1. UAT-2 real-runtime path is implemented and evidenced.
2. UAT-2.5 hardening/repeatability gate is complete.
3. Current branch has no blocking startup regressions.
4. Required docs exist and are accessible to non-dev participants:
   - Runbook (startup/operation/shutdown)
   - Feature/functionality How-Tos

### 5.1 Readiness Cross-Reference (Post UAT-2.5)

- UAT-2.5 hardening/repeatability gate evidence is available in:
  - `phase2_gates/evidence/uat25_stability_matrix.json`
  - `phase2_gates/evidence/uat25_failure_injection_matrix.json`
  - `phase2_gates/evidence/uat25_evidence_normalization.json`
  - `phase2_gates/evidence/uat25_summary.md`
- Milestone-3 disposition is `PASS` for this branch/session scope.
- This update is readiness-only; no UAT-3 execution activities are recorded in this session.

---

## 6. UAT-3 Execution Phases

Execution control artifact:
- Use `docs/UAT-3_EXECUTION_WORKSHEET.md` as the strict run-time checklist and evidence-capture worksheet for UAT-3 execution.

## Phase A — Non-Dev Education (Agent-Facilitated Comprehension Check)

Goal: verify documentation can teach operation before hands-on UAT.

Activities:
1. Agent summarizes key runbook and How-To sections for the user.
2. Agent asks 5 comprehension questions one at a time in chat, waiting for user answers.
3. Agent grades each answer PASS/FAIL. If FAIL, explains correct answer and re-asks once.

Pass Criteria:
- User can explain cold-start, login/launch path, basic prompt flow, and shutdown path correctly.
- User can identify fail-closed behavior and escalation path in docs.
- Bounded comprehension failures (after retry) are recorded but do not block subsequent phases.

## Phase B — Cold-Start Operational Execution (Hands-On)

Goal: validate non-dev ability to start and operate system from cold state using docs only.

Activities:
1. Participant performs startup from cold state.
2. Participant reaches operational UI.
3. Participant performs normal interaction path.
4. Participant executes graceful shutdown.

Pass Criteria:
- No developer intervention beyond safety oversight.
- Procedure follows runbook steps.
- Any failure is handled per documented remediation flow.

## Phase C — UI Functional UAT Matrix

Goal: validate all required UI functions and user-facing workflows.

Required test categories:
1. Session management (create/switch/delete).
2. Prompt submission and response rendering.
3. PGOV-visible outcomes (permit/deny visibility).
4. Retry/recovery behavior for expected failure modes.
5. Shutdown and relaunch continuity checks.

Pass Criteria:
- All critical workflows pass.
- Non-critical issues are documented with severity and workaround.

## Phase D — Documentation Acceptance and Onboarding Suitability

Goal: non-dev users formally accept docs as onboarding material.

Activities:
1. Collect structured feedback on runbook and How-Tos.
2. Apply final revisions.
3. Obtain explicit non-dev acceptance sign-off.

Pass Criteria:
- Runbook and How-Tos are accepted by non-dev participants.
- Documentation deemed reusable for onboarding new non-dev team members.

---

## 7. UAT-3 Functional Test Matrix

| ID | Area | Procedure | Expected Result | Evidence |
|---|---|---|---|---|
| UAT3-01 | Cold-start launch | Follow runbook from cold state | System reaches operational UI without dev intervention | `uat3_operator_run_log.md` |
| UAT3-02 | Session create | Create new session from UI | Session appears and is selectable | `uat3_ui_matrix.json` |
| UAT3-03 | Session switch | Switch between sessions | Correct history/context shown per selected session | `uat3_ui_matrix.json` |
| UAT3-04 | Session delete | Delete an existing session | Session removed with expected UX behavior | `uat3_ui_matrix.json` |
| UAT3-05 | Prompt/response flow | Submit prompts through UI | Response appears via expected runtime path | `uat3_ui_matrix.json` |
| UAT3-06 | PGOV visibility | Trigger/observe PGOV outcomes | Permit/deny states are understandable to non-dev user | `uat3_ui_matrix.json` |
| UAT3-07 | Fail-closed behavior | Execute documented failure scenario | User follows documented recovery/escalation path | `uat3_failure_paths.json` |
| UAT3-08 | Graceful shutdown | Follow shutdown steps | System exits cleanly without residual user confusion | `uat3_operator_run_log.md` |
| UAT3-09 | Relaunch continuity | Relaunch and validate expected continuity | System behavior matches documented expectations | `uat3_ui_matrix.json` |
| UAT3-10 | Documentation usability | Non-dev review of runbook + How-Tos | Docs accepted as onboarding-grade artifacts | `uat3_docs_acceptance.md` |

---

## 8. Artifact Requirements (Mandatory)

At minimum, produce:

1. `docs/RUNBOOK_NON_DEV_OPERATIONS.md`
   - cold-start, startup, normal operations, shutdown, fail-closed handling, escalation path.
2. `docs/HOWTO_FEATURES_NON_DEV.md`
   - task-oriented How-Tos for each major UI feature/functionality.
3. `phase2_gates/evidence/uat3_operator_run_log.md`
4. `phase2_gates/evidence/uat3_ui_matrix.json`
5. `phase2_gates/evidence/uat3_failure_paths.json`
6. `phase2_gates/evidence/uat3_docs_acceptance.md`

Each evidence artifact must include:
- timestamp (UTC),
- commit hash,
- participant role/type (non-dev),
- scenario ID,
- pass/fail disposition,
- notes/remediation where applicable.

---

## 9. Documentation Update Requirements

After UAT-3 completion, update all of:
- `docs/GAP_TO_OPERATIONAL_REPORT.md`
- `docs/IMPLEMENTATION_PLAN.md`
- `docs/UAT-2_ACCEPTANCE_PLAN.md`
- `docs/UAT-3_ACCEPTANCE_PLAN.md` (this file, with execution record)
- `.github/copilot-instructions.md` (only if milestone sequencing/status changes)

Include pre/post session HEAD, acceptance outcomes, and links to all UAT-3 evidence artifacts.

---

## 10. Exit and Sign-Off Gate

UAT-3 is complete when:
- all critical UAT3-* scenarios pass,
- runbook + How-Tos are explicitly accepted by non-dev participants,
- onboarding suitability is explicitly confirmed,
- required artifacts are complete and linked in roadmap docs.

Operational sign-off may proceed only after UAT-2, UAT-2.5, and UAT-3 are all complete with accepted evidence.

---

## 11. Rollback / Rework Path

If UAT-3 fails:
1. Record failed scenario(s) and root-cause category:
   - documentation gap,
   - usability gap,
   - runtime reliability gap,
   - process/training gap.
2. Apply bounded corrective actions.
3. Re-run failed UAT3-* scenarios with updated artifacts.
4. Re-collect non-dev acceptance evidence.

No operational sign-off is allowed while UAT-3 has unresolved critical failures.

---

## 12. Sign-Off Template

| Role | Name | Date | Result | Signature |
|---|---|---|---|---|
| Non-Dev Participant 1 |  |  | Pass / Fail |  |
| Non-Dev Participant 2 (optional) |  |  | Pass / Fail |  |
| Lead Architect |  |  | Approved / Rework Required |  |
| Technical Facilitator |  |  | Complete / Incomplete |  |

---

## 13. 2026-02-25 Milestone 4 Execution Record

### 13.1 Session Git Metadata

- Branch: `feature/p1-uat1-launcher`
- Pre-session HEAD: `dc5abbe758dd1e421a892ebb74707309e1636c87`
- Post-session HEAD (pre-commit): `dc5abbe758dd1e421a892ebb74707309e1636c87`

### 13.2 Commands Executed (Required Technical Gate Order)

1. Baseline capture:
  - `git rev-parse --abbrev-ref HEAD`
  - `git rev-parse HEAD`
2. Compile gate:
  - `python -m py_compile launcher/__main__.py services/ui_shell/src/app.py services/ui_gateway/src/transport.py services/policy_agent/src/entrypoint.py services/assistant_orchestrator/src/entrypoint.py`
  - Result: `COMPILE_GATE_PASS`
3. Focused tests:
  - `.venv\Scripts\python.exe -m pytest launcher/tests/test_launcher.py services/ui_gateway/tests/test_transport.py services/policy_agent/tests/test_entrypoint.py services/assistant_orchestrator/tests/test_entrypoint.py -q`
  - Result: `75 passed`
4. Integration guardrail:
  - `.venv\Scripts\python.exe -m pytest tests/integration/test_p110_end_to_end.py -q`
  - Result: `49 passed`

### 13.3 Participant-Dependent Phase Outcome

- Phase A (non-dev education/comprehension): `BLOCKED`
- Phase B (cold-start hands-on by non-dev): `BLOCKED`
- Phase C (UAT3-01..UAT3-10 UI matrix): `BLOCKED`
- Phase D (explicit non-dev doc acceptance): `BLOCKED`

Deterministic blocker fingerprint:
- `UAT3_NON_DEV_PARTICIPANT_UNAVAILABLE`

### 13.4 Evidence Artifacts

- `phase2_gates/evidence/uat3_operator_run_log.md`
- `phase2_gates/evidence/uat3_ui_matrix.json`
- `phase2_gates/evidence/uat3_failure_paths.json`
- `phase2_gates/evidence/uat3_docs_acceptance.md`
- `phase2_gates/evidence/uat3_summary.md`

### 13.5 Milestone-4 Disposition (Session-Bounded)

- **BLOCKED_FAIL_CLOSED**
- Technical validation gates passed, but mandatory non-dev execution and explicit
  non-dev acceptance statements were not collectible in this session context.

### 13.6 Residual Milestone-4 Closure Requirements

1. Execute Phase A/B/C with at least one non-dev participant, no developer shortcuts.
2. Record pass/fail outcomes for UAT3-01..UAT3-10 with participant-backed evidence.
3. Capture explicit non-dev acceptance statements for:
  - `docs/RUNBOOK_NON_DEV_OPERATIONS.md`
  - `docs/HOWTO_FEATURES_NON_DEV.md`
4. Confirm onboarding-reuse suitability statement from non-dev participant(s).
