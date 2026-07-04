---
role: co_lead_architect
phase: completion
revision: 1
tracking_task: 28
vikunja_comment: null
posted_at: 2026-04-21T22:48:32-05:00
verdict: null
subject: fix sprint_id in active_tasks allowed entry keys (DEC-15)
commit: a173825
---

## Co-Lead Completion — Sprint-ID Fix in active_tasks.py

**Fix applied**: `a173825 [agent:co_lead] fix: add sprint_id to active_tasks allowed entry keys (DEC-15)`

### What Was Wrong

`_ALLOWED_ENTRY_KEYS` in `tools/autonomy_budget/active_tasks.py:141` did not include
`sprint_id`. The `docs/active_tasks.yaml` roster carries `sprint_id: 7` as required by
DEC-15, but the schema validator raised `ActiveTasksError: active_tasks[0] unknown
fields: ['sprint_id']` on every `load_roster()` call.

This blocked `proactive_colead.scan()` (Phase 3) across **3+ consecutive Co-Lead firings**
(tasks 142 and 144 in Agent Gates task 65).

### What Changed

- `_ALLOWED_ENTRY_KEYS`: added `"sprint_id"`.
- `ActiveTask` dataclass: added `sprint_id: int | None = None` field.
- `ActiveTask.to_dict()`: emits `sprint_id` only when not None (backward-compatible).
- `ActiveTask.from_dict()`: reads `sprint_id` optionally.
- `_validate_roster()`: validates `sprint_id` is a positive int when present.
- **4 new tests** added in `tools/autonomy_budget/tests/test_active_tasks.py`.

### Test Results

40/40 `test_active_tasks.py` tests pass. 145/145 `tools/autonomy_budget/` tests pass.

### Phase 3 Status After Fix

`load_roster()` succeeds. `proactive_colead.scan()` returns **None** (correct) because
task 28 is still in `active_tasks` (roster entry not yet completed). The LA-directed
`pause_after: true` on task 28 also ensures no autonomous sprint transition. Phase 3
is correctly a no-op.

### Escalation Resolution

Vikunja task 65 (`[Co-Lead Escalation] DEC-15 roster validator rejects sprint_id`) is
resolved by this commit. Tasks 61/66 in Agent Gates and task 67 in Fleet Reports for
the sprint_auditor HARD-breach are addressed by the companion fix in v2 of this report.

---
Fleet Reports task: (see companion Fleet Reports task created this firing)
