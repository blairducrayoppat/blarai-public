# BlarAI Non-Dev Operations Runbook

**Audience:** Non-developer operators
**Purpose:** Safely start, operate, and stop BlarAI from a cold state
**Scope:** Daily operation for USE-CASE-001 and USE-CASE-004 user-facing flow

---

## 1. Before You Start

## 1.1 Prerequisites
- You are on the approved workstation.
- Windows is fully booted and responsive.
- Hyper-V is enabled on the machine.
- You know the location of the BlarAI launcher script: `launch_blarai.bat` (in the project root `C:\Users\mrbla\BlarAI`).

## 1.2 Safety Rules
- Do not edit configuration files manually.
- Do not bypass admin/UAC prompts with custom scripts unless instructed.
- If startup fails, follow the fail-closed escalation path in Section 7.

---

## 2. Cold-Start Procedure

1. Close other heavy applications not required for your task.
2. Open BlarAI by double-clicking `launch_blarai.bat` (in the project root).
3. If prompted by Windows UAC, approve with your authorized admin credentials.
4. Wait for startup to finish (no forced restarts during this phase).
5. Confirm that the main UI opens and is responsive.

**Expected Outcome:** BlarAI reaches operational UI without manual developer intervention.

---

## 3. Standard Operating Procedure (SOP)

## 3.1 Start Session
1. Create a new session with **Ctrl+N**, or select an existing session in the left panel.
2. Enter a prompt in the input area.
3. Submit and wait for response rendering.

## 3.2 Validate Response Surface
- Confirm output appears in the active session.
- If policy controls trigger, verify PGOV/denial visibility is understandable.

## 3.3 Continue Workflow
- Use session switch/create/delete as needed.
- Keep work in the correct session context.

---

## 4. Controlled Shutdown Procedure

1. Finish current interaction.
2. Use in-app quit command / documented shortcut.
3. Wait for app to fully close.
4. Do not kill background processes unless instructed by escalation.

**Expected Outcome:** Application exits cleanly.

---

## 5. Daily Verification Checklist

- [ ] Startup from cold state succeeded.
- [ ] UI loaded and accepted input.
- [ ] Prompt/response flow worked.
- [ ] Policy-visible outcomes were readable.
- [ ] Shutdown completed cleanly.

---

## 6. Known Operator Scenarios

## 6.1 Startup Takes Longer Than Expected
- Wait until startup either completes or presents a deterministic failure message.
- Do not relaunch multiple instances in parallel.

## 6.2 UI Opens but Response Does Not Proceed
- Retry once using documented UI retry action.
- If still blocked, capture screenshot + timestamp and escalate.

## 6.3 Policy Denial Observed
- Treat as expected fail-closed behavior unless system indicates internal error.
- Record denial context if required by your team process.

---

## 7. Fail-Closed Escalation Path

Escalate to technical owner when any of the following occurs:
- App cannot reach operational UI after approved startup path.
- Repeated startup failures in same shift.
- Deterministic failure/fingerprint message appears and persists.
- UI becomes non-responsive during normal operation.

When escalating, provide:
1. Time of failure (UTC if possible).
2. What step failed (startup, prompt flow, shutdown, etc.).
3. Screenshot or exact on-screen error text.
4. Any recent changes (system updates, restart, etc.).

---

## 8. Onboarding Confirmation

A new non-dev team member is considered operationally onboarded when they can:
- Start BlarAI from cold state using this runbook,
- Complete core UI workflows without developer help,
- Perform controlled shutdown,
- Correctly follow escalation on failure.

---

## 9. UAT-3 Acceptance State (2026-02-26)

- Status: `ACCEPTED`
- Session disposition: `PASS`
- Non-dev participant: User (Lead Architect / Non-Dev Operator)
- Evidence: `phase2_gates/evidence/uat3_docs_acceptance.md`

This document has been accepted as onboarding-grade by the Lead Architect
(non-dev operator) during UAT-3 Milestone 4 execution. Four inaccuracies
were identified and corrected during acceptance review (commit `715b014`).
