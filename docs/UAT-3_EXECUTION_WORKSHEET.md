# UAT-3 Execution Worksheet (Strict)

**Stage:** Operational Exit Milestone 4 (UAT-3)
**Branch Baseline:** `feature/p1-uat1-launcher`
**Baseline HEAD (post-Milestone-3):** `98decc95faa72a6a465f771791b5768336652a91`
**Milestone-3 Baseline Evidence:**
- `phase2_gates/evidence/uat25_stability_matrix.json` (`run_count=3`, `disposition=PASS`)
- `phase2_gates/evidence/uat25_failure_injection_matrix.json` (`scenario_count=2`, `all_fail_closed=true`, `baseline_restore.restored=true`)
- `phase2_gates/evidence/uat25_evidence_normalization.json`
- `phase2_gates/evidence/uat25_summary.md`

**Source of truth:** `docs/UAT-3_ACCEPTANCE_PLAN.md`

---

## 1) Scope Guardrails (Hard Constraints)

- Execute **UAT-3 only** (non-dev enablement + UI functional acceptance).
- Do **not** run architecture changes, refactors, or framework switches.
- Do **not** run Milestone-5 / sign-off packaging in this worksheet.
- Fail-closed behavior must be preserved and recorded exactly as observed.

If any guardrail is violated, mark session `INVALID_SCOPE` and stop.

---

## 2) Session Metadata (Fill Before Start)

- UAT date (UTC): 2026-02-26
- Facilitator: `Copilot Agent (Interactive Facilitation Mode)`
- Non-dev participant: `User (Lead Architect / Non-Dev Operator)` — DECLARED
- Participant context: Non-developer vibe coder; directs AI agents to build software; does not write code directly.
- Observer/recorder (optional): `N/A (Agent serves as recorder)`
- Session start timestamp (UTC): 2026-02-25T22:00:00Z (approx)
- Branch at start: `feature/p1-uat1-launcher`
- HEAD at start: `6a76094` (session progressed through 6a76094 → 0c1b619 → ca08164 → 715b014)
- Prior attempt: `cc3293b` (BLOCKED_FAIL_CLOSED / UAT3_NON_DEV_PARTICIPANT_UNAVAILABLE — resolved by this rerun)

Preflight command record:
- `git rev-parse --abbrev-ref HEAD` = `feature/p1-uat1-launcher`
- `git rev-parse HEAD` = `715b014b0984e377f832193d23d73d8532aa2bab`

---

## 3) Entry Criteria Gate (All Required)

Mark each item `PASS` / `FAIL`:

1. UAT-2 real-runtime path evidenced (`uat2_real` activation + prompt-flow artifacts): `PASS`
2. UAT-2.5 hardening/repeatability gate complete (Milestone-3 PASS): `PASS`
3. No blocking startup regressions in current branch: `PASS`
4. Non-dev docs available to participants:
   - `docs/RUNBOOK_NON_DEV_OPERATIONS.md`: `PASS`
   - `docs/HOWTO_FEATURES_NON_DEV.md`: `PASS`

If any item fails, stop and record blocker fingerprint or blocking reason.

---

## 4) Required Output Artifacts (Create During Session)

Must produce all files:

1. `phase2_gates/evidence/uat3_operator_run_log.md`
2. `phase2_gates/evidence/uat3_ui_matrix.json`
3. `phase2_gates/evidence/uat3_failure_paths.json`
4. `phase2_gates/evidence/uat3_docs_acceptance.md`

Each artifact must include these fields:
- `timestamp` (UTC)
- `commit_hash`
- `participant_role` (non-dev)
- `scenario_id`
- `disposition` (`PASS`/`FAIL`)
- `notes` (and remediation, if applicable)

---

## 5) Phase A — Non-Dev Education (On Paper + Guided)

### A.1 Comprehension Checklist (Agent-Facilitated — One Question at a Time)

Mark each `PASS` / `FAIL`:
- Cold-start steps explained correctly: `PASS`
- Startup/UAC behavior explained correctly: `PASS`
- Basic prompt flow explained correctly: `PASS`
- Graceful shutdown path explained correctly: `PASS`
- Fail-closed + escalation path explained correctly: `PASS`

Phase A disposition: `PASS`
Notes:
All five comprehension questions answered correctly by non-dev participant on first attempt.

Stop rule: Bounded comprehension failures (after one retry) are recorded but do not block Phase B.

---

## 6) Phase B — Cold-Start Operational Execution (Hands-On)

### B.1 Strict Procedure Record

- Participant started from cold state using docs only: `PASS`
- Reached operational UI without developer intervention: `PASS`
- Performed normal interaction path: `PASS`
- Executed graceful shutdown: `PASS`

Intervention log (must be empty for strict pass):
(empty — no developer intervention required)

Phase B disposition: `PASS`

Note: Agent guides user through each step interactively and records outcomes.
Stop rule: If any critical step fails, proceed to Phase C for scenarios still safely executable.

---

## 7) Phase C — UI Functional UAT Matrix (UAT3-01 … UAT3-10)

Record each scenario exactly once with `PASS` / `FAIL` and evidence pointer.

| Scenario ID | Result | Notes / Failure Fingerprint | Evidence Pointer |
|---|---|---|---|
| UAT3-01 Cold-start launch | `PASS` | Launched via launch_blarai.bat, all services started | `uat3_operator_run_log.md` |
| UAT3-02 Session create | `PASS` | Ctrl+N created new session | `uat3_ui_matrix.json` |
| UAT3-03 Session switch | `PASS` | Session switch persisted history; bug fix b8dca40 | `uat3_ui_matrix.json` |
| UAT3-04 Session delete | `PASS` | Deleted session removed from list | `uat3_ui_matrix.json` |
| UAT3-05 Prompt/response flow | `PASS` | NPU response rendered in English | `uat3_ui_matrix.json` |
| UAT3-06 PGOV visibility | `PASS` | Red Policy Denial box on injection; normal prompt permitted | `uat3_ui_matrix.json` |
| UAT3-07 Fail-closed behavior | `PASS` | Recovery after policy denial confirmed | `uat3_failure_paths.json` |
| UAT3-08 Graceful shutdown | `PASS` | Ctrl+Q clean exit | `uat3_operator_run_log.md` |
| UAT3-09 Relaunch continuity | `PASS` | Sessions persisted; phantom fix ca08164 | `uat3_ui_matrix.json` |
| UAT3-10 Documentation usability | `PASS` | 4 doc fixes applied (715b014), docs accepted | `uat3_docs_acceptance.md` |

Phase C disposition rule:
- `PASS` only if all critical workflows pass and any non-critical issue has bounded workaround.

---

## 8) Phase D — Documentation Acceptance + Onboarding Suitability

### D.1 Non-Dev Acceptance Checklist

- Runbook accepted by non-dev participant(s): `ACCEPTED`
- Feature How-To accepted by non-dev participant(s): `ACCEPTED`
- Docs judged onboarding-ready for new non-devs: `ACCEPTED`

Feedback summary:
Lead Architect (non-dev operator) identified 4 inaccuracies during UAT3-10 review: (1) RUNBOOK §1.1 BlarAI.exe→launch_blarai.bat, (2) RUNBOOK §3.1 added Ctrl+N shortcut, (3) HOWTO §1 BlarAI.exe→launch_blarai.bat, (4) HOWTO §2 added Ctrl+N. All corrected in commit 715b014 and re-verified. Both documents accepted as onboarding-grade after corrections.

Required output:
- `phase2_gates/evidence/uat3_docs_acceptance.md` with explicit acceptance or rejection rationale.

---

## 9) Session Exit Gate (Milestone 4 Disposition)

Mark final disposition:
- `PASS` (all critical UAT3 scenarios pass + docs accepted + onboarding suitability confirmed)
- `BOUNDED_FAIL_CLOSED` (deterministic, auditable failures with remediation plan)
- `BLOCKED` (cannot continue due to blocker; include fingerprint or deterministic reason)

Final disposition: `PASS`
Primary blocker/fingerprint (if not PASS):
N/A — all critical UAT3 scenarios passed, docs accepted, onboarding suitability confirmed.

---

## 10) Post-Execution Documentation Sync Checklist

After execution, update all:
- `docs/GAP_TO_OPERATIONAL_REPORT.md`
- `docs/IMPLEMENTATION_PLAN.md`
- `docs/UAT-2_ACCEPTANCE_PLAN.md`
- `docs/UAT-3_ACCEPTANCE_PLAN.md` (append execution record)

Must include:
- pre/post session HEAD
- exact executed steps
- evidence artifact links
- final disposition and remediation (if any)

---

## 11) Sign-Off Block

| Role | Name | Date (UTC) | Result | Signature |
|---|---|---|---|---|
| Non-Dev Participant / Lead Architect | User | 2026-02-26 | PASS | User (Lead Architect) |
| Interactive Facilitator | Copilot Agent | 2026-02-26 | PASS | Copilot Agent (Claude Opus 4.6) |

---

## 12) Worksheet Integrity Check (Before Commit)

- All required artifacts created: `PASS`
- All mandatory fields present in each artifact: `PASS`
- UAT3-01..UAT3-10 each recorded exactly once: `PASS`
- Disposition aligns with evidence: `PASS`
- Scope remained Milestone-4 only: `PASS`

If any check fails, do not mark Milestone 4 complete.
