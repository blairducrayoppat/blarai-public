# BlarAI How-To Guide (Non-Dev Features)

**Audience:** Non-developer operators
**Purpose:** Task-based instructions for common UI features and functionality

---

## How-To 1: Start the System from Cold State

1. Open BlarAI by double-clicking `launch_blarai.bat` (in the project root).
2. Approve UAC if prompted.
3. Wait for operational UI.
4. Confirm you can type into prompt input.

If startup fails, follow the escalation steps in `docs/RUNBOOK_NON_DEV_OPERATIONS.md`.

---

## How-To 2: Create a New Session

1. Press **Ctrl+N** to create a new session.
2. Verify the new session appears in the session panel.
3. Select it before sending prompts.

---

## How-To 3: Switch Between Sessions

1. Click the target session in the session panel.
2. Confirm chat context updates to that session.
3. Continue work only after verifying active session.

---

## How-To 4: Delete a Session

1. Select the session to remove.
2. Use the delete action/shortcut.
3. Confirm the session is removed from list.

Use caution: deletion may be irreversible depending on retention policy.

---

## How-To 5: Submit a Prompt and Read Output

1. Type a prompt in input box.
2. Submit prompt.
3. Wait for response rendering.
4. Verify response appears in current session.

---

## How-To 6: Interpret PGOV / Policy Outcomes

1. Look for permit/deny or policy-related UI indicators.
2. If denied, treat as expected fail-closed behavior unless a system error is shown.
3. If unclear, capture screenshot and escalate per runbook.

---

## How-To 7: Retry After a Recoverable UI Failure

1. Use documented retry action once.
2. If failure persists, do not spam retries.
3. Record timestamp + visible message.
4. Escalate through runbook path.

---

## How-To 8: Shut Down Safely

1. Finish current operation.
2. Use in-app quit path/shortcut.
3. Wait for complete exit.
4. Do not force-close unless instructed by support.

---

## How-To 9: Collect Minimal Incident Info for Support

When reporting issues, include:
- What you were doing (feature/workflow),
- Exact time of issue,
- Screenshot or exact text,
- Whether retry was attempted.

This reduces resolution time and improves onboarding quality.

---

## Quick Reference: Core Feature Checklist

- [ ] Cold-start launch
- [ ] Session create
- [ ] Session switch
- [ ] Session delete
- [ ] Prompt/response flow
- [ ] PGOV visibility understanding
- [ ] Retry behavior
- [ ] Safe shutdown

---

## UAT-3 Acceptance State (2026-02-26)

- Status: `ACCEPTED`
- Session disposition: `PASS`
- Non-dev participant: User (Lead Architect / Non-Dev Operator)
- Evidence: `phase2_gates/evidence/uat3_docs_acceptance.md`

This document has been accepted as onboarding-grade by the Lead Architect
(non-dev operator) during UAT-3 Milestone 4 execution. Four inaccuracies
were identified and corrected during acceptance review (commit `715b014`).
