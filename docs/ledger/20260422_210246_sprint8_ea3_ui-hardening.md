---
ledger_id: 20260422_210246_sprint8_ea3_ui-hardening
date: 2026-04-22
sprint_id: 8
entry_type: EA
predecessor: 20260422_184004_sprint8_ea2_ao_sr_hardening
branch: feature/p5-task8-ea3-ui-hardening
merge_commit: null
disposition: COMPLETE
---

## Sprint 8 EA-3: UI Gateway + UI Shell Test Hardening

### Summary

This ledger entry records the completion of EA-3 for Sprint 8 (Task 82: Test Quality Remediation). EA-3 closes all test-coverage, boundary-verification, and assertion-quality gaps in the UI Gateway (`services/ui_gateway/`) and UI Shell (`services/ui_shell/`) service clusters per the SDO EA-3 prompt (`docs/scheduled/ea_queue/P5_TASK8_EA3_UI_HARDENING.xml`).

### Work Items Completed

| WI | Priority | Outcome |
|---|---|---|
| WI-1 | HIGH | `TestStreamTokensBufferLimit` — 2 tests: at-limit (all LIMIT tokens yielded) and one-over-limit (breaks at LIMIT+1) |
| WI-2 | HIGH | `TestStreamTokensDecodeError` — 1 test: malformed frame skipped via `continue`, surrounding valid tokens yielded |
| WI-3 | HIGH | `TestCheckPaStatusShortCircuit` — 1 test: already-connected gateway returns True without invoking `_attempt_pa_handshake` |
| WI-4 | HIGH | `TestActionSubmitPromptBranches` — PGOV-denied branch: `display_denial` called once, `flush_tool_call_buffer(pgov_approved=False)` |
| WI-5 | HIGH | `TestActionSubmitPromptBranches` — PGOV-approved branch: `flush_tool_call_buffer(pgov_approved=True)`, `display_denial` not called |
| WI-6 | HIGH | `TestActionSubmitPromptBranches` — RuntimeError: write_line contains error text + "[red]Error:". Exception: write_line contains "Unexpected error" + "Fail-Closed" |
| WI-7 | HIGH | Strengthened `TestBlarAIAppActionGuards`: both tests now async, invoke `action_submit_prompt()` and assert `send_prompt` not called |
| WI-8 | MEDIUM | Created `test_session_panel.py` — 11 tests covering `refresh_list`, `create_new_session`, `delete_current_session`, `select_session`, `active_session_id`, no-store guards, `SessionListItem` label format |
| WI-9 | MEDIUM | `TestBootPollAttemptMarkers` — 1 test: pure unit test of attempt_markers list computation (fallback per RISK I.6); boot-poll loop too entangled with Textual widgets for full drive |
| WI-10 | MEDIUM | `TestPaHandshakeRetry` — 2 tests: backoff sequence asserts `[1.0, 2.0]` sleep durations; exhaustion test asserts `MAX_RETRIES-1` sleeps |
| WI-11 | MEDIUM | `TestStreamingFlagTransitions` — 4 tests: flag True during non-final tokens, False after final, False after clear_display, False after start_new_response |
| WI-12 | MEDIUM | Created `test_constants_ui_gateway.py` — 16 tests pinning all constants in `services/ui_gateway/src/constants.py` |
| WI-13 | MEDIUM | Created `test_constants_ui_shell.py` — 22 tests pinning all constants in `services/ui_shell/src/constants.py` including full `PGOV_REASON_LABELS` mapping |
| WI-14 | LOW | `TestToolCallBufferBoundary` — 1 test: fill MAX-1, accept MAX, raise on MAX+1 (exact boundary) |
| WI-15 | LOW | Migrated `asyncio.get_event_loop().run_until_complete(...)` in `test_on_list_view_selected_loads_turns` to `async def` + `await` per pytest-asyncio auto mode |

### Quality Gates

| Gate | Result |
|---|---|
| COMPILE | PASS — all 6 new/modified modules import without error |
| TEST-FOCUSED | PASS — 190 passed (services/ui_gateway/ + services/ui_shell/) |
| TEST-FULL | PASS — 962 passed, 2 skipped (floor: 875) |
| ORACLE | PASS — `git diff main...feature/... --name-only \| grep -vE "tests\|conftest\|docs\|pyproject"` → EMPTY |

### Scope Deviations

- **WI-9 partial coverage**: boot-poll attempt-marker loop (`app.py:237-284`) tested as a pure unit computation only. Full drive requires mocking `asyncio.create_task` and the Textual widget update flow — per RISK I.6 fallback, documented here.
- **WI-8 `refresh_list` widget stubs**: `query_one("#session-list", ListView)` stubbed via `panel.query_one = MagicMock(return_value=AsyncMock())`. This correctly verifies the `asyncio.to_thread` wiring for store access without starting the Textual compositor.

### Test Count Delta

- Pre-EA-3 baseline (derived): 897 passed
- Post-EA-3: 962 passed
- **New tests: 65**
- Breakdown: 7 (transport) + 5 (app) + 4 (streaming) + 11 (session_panel) + 16 (const_ui_gateway) + 22 (const_ui_shell)
