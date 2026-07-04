---
role: co_lead_architect
phase: completion
revision: 2
tracking_task: 28
vikunja_comment: null
posted_at: 2026-04-21T22:48:32-05:00
verdict: null
subject: register sprint_auditor role in autonomy_budget config (DEC-15)
commit: 267de97
---

## Co-Lead Completion — Sprint Auditor Role Registration

**Fix applied**: `267de97 [agent:co_lead] fix: register sprint_auditor role in autonomy_budget (DEC-15)`

### What Was Wrong

The `sprint_auditor` role was introduced by DEC-15 (wake template at
`docs/scheduled/wake_templates/sprint_auditor.md`) but was missing from:

1. `_AGENT_ROLES` tuple in `tools/autonomy_budget/self_check.py:48` →
   `ValueError: Unknown agent role: 'sprint_auditor'` on every Phase 0 self-check.
2. `roles:` section of `tools/autonomy_budget/config.yaml` →
   `KeyError` on `cfg["roles"]["sprint_auditor"]` after `_AGENT_ROLES` check passed.

This caused **HARD breach on every 15-min sprint_auditor firing** since DEC-15 was
deployed (Agent Gates tasks 61, 66; Fleet Reports task 67).

### What Changed

**`tools/autonomy_budget/self_check.py`**:
- Added `"sprint_auditor"` to `_AGENT_ROLES`.

**`tools/autonomy_budget/config.yaml`**:
- Added `sprint_auditor` role entry with config derived from the wake template:
  - `scheduled_surface: claude_code_headless`
  - `session_runtime_min: 30` (from wake template Budget self-check section)
  - `daily_runs: 4`
  - `ttg_hours: 24` (SWAGR is archive-grade, non-blocking)
  - `weekly_cum_hours: 8`
  - `scheduled_poll_cron: "*/15 * * * *"`
  - `allowed_tools`: verbatim from wake template Budget self-check section

### Test Results

145/145 `tools/autonomy_budget/` tests pass. Config loads without error.
`self_check.run(role="sprint_auditor", task_id=None)` returns `may_proceed: True`.

### Escalation Resolution

Agent Gates tasks 61 and 66 (`[Sprint Auditor] HARD breach — sprint_auditor role not
registered`) are resolved by this commit. Fleet Reports task 67 is resolved.

The sprint_auditor can now fire normally on its 15-min cadence. Sprint 7 has no SDV
(pre-DEC-15), so the auditor will find no audit candidates until an SCR exists for a
DEC-15+ sprint with an SDV. Phase 1 of the sprint_auditor will be a clean no-op until
Co-Lead authors an SCR for a completed sprint.

---
Fleet Reports task: (see companion Fleet Reports task created this firing)
