---
role: ea_code
phase: comprehension
revision: 1
tracking_task: 82
sprint_id: 8
vikunja_comment: 331
posted_at: 2026-04-22T20:19:39Z
verdict: null
---

# [agent:ea_code][phase:comprehension] Sprint 8 EA-3 UI Gateway + UI Shell Test Hardening — Comprehension v1

## Wake Template Recitation

Session context per `docs/scheduled/wake_templates/ea_code.md`. Governing section headers (verbatim):

- **Role invocation** — EA Code; milestone executor; writes code, runs tests, commits; does NOT merge to main.
- **Phase 0 — Fleet-blocked exit** — skipped, fleet not LA-blocked this firing (Task 82 carries `Gate:Pending-Execution`).
- **Event-driven wake triggers (Q2-1)** — `schtasks /run /tn "Wake SDO"` fires after Case A comprehension commit.
- **Your scope for this firing** — inspect `docs/scheduled/ea_queue/`; ignore `archive/` + `staging/`; STALE-QUEUE GUARD when gate mismatch.
- **State machine (DEC-12)** — Cases A / B / C / D / E / F per tracking-task comment history.
- **Formatting standard for Vikunja descriptions and disk reports (DEC-14.5)** — markdown with headers, bullets, bold verdicts, fenced code blocks.
- **Report emission (DEC-13)** — disk copy + Fleet Reports task (project 8) + assign `blarai` + commit + cross-reference.
- **M5 Comprehension Gate content** — structural recitation of wake template + EA prompt + own plan + parent-head.
- **Budget self-check** — 90 min session cap + TTG 2 h.
- **Exit criteria** — Case A action posted → exit; do NOT execute WIs.

Tools used this firing: `Read`, `Bash` (git rev-parse / date / ls), `Write` (this report), `mcp__vikunja__add_task_comment`, `mcp__vikunja__add_label_to_task`, `mcp__vikunja__remove_label_from_task`, `mcp__vikunja__create_task`, `mcp__vikunja__assign_user_to_task`. No production or test source file is touched at Case A.

## State machine classification

**Case A — Fresh task.** No prior `[agent:ea_code][phase:comprehension]` comment exists on Task 82 for EA-3. Queue file `docs/scheduled/ea_queue/P5_TASK8_EA3_UI_HARDENING.xml` was moved from staging → queue at commit `09ff6d2` (SDO queue-move) following Co-Lead **APPROVED** on the Path B rev2 revision (commit `21f7589`). EA-3's predecessor EA-2 branch `feature/p5-task8-ea2-ao-sr-hardening` merged at `0b5e5ec` (main). Predecessor ledger: `docs/ledger/20260422_184004_sprint8_ea2_ao_sr_hardening.md`.

## Parent Head Verify (L-13)

- Current HEAD at this firing: `09ff6d2` (SDO: Task 82 EA-3 queue-move + Task 121 EA-3 comprehension-review APPROVED).
- Prompt `<parent_head>` value: `cf0ab6a` (SDO Task 121 queue-move, before this firing's intervening commits `21f7589`, `9875c7a`, `09ff6d2`).
- Resolution per L-13: branch will be created from **current main HEAD `09ff6d2`** at Case C, not stale `cf0ab6a`. Diff between the two is documentation-only (EA-3 comprehension reports + queue-move commits); zero production or test-file delta affecting EA-3 work. The `<depends_on>` requirement (EA-2 merged at `0b5e5ec`) is satisfied.

---

## EA Prompt Recitation (A–J per `<comprehension_gate>` instruction)

### A. MILESTONE OBJECTIVE

Close all test-coverage, boundary-verification, and assertion-quality gaps in the UI Gateway (`services/ui_gateway/`) and UI Shell (`services/ui_shell/`) service clusters that were surfaced by the Sprint 7 audit and scoped by SDV §5.1 item 3 and continuation XML §5 EA-3 block. This is a **pure test-authoring** milestone: every deliverable lands under `services/ui_gateway/tests/`, `services/ui_shell/tests/`, or `docs/ledger/`. Production source is read-only; no seams, no hooks, no `_for_testing` attributes. Scope is bounded to 15 work items covering streaming overflow guards, handshake retry/backoff assertions, PGOV branch coverage in `action_submit_prompt`, `SessionPanel` async-to_thread wiring, boot-poll attempt-marker progression, streaming flag transitions, constants-pinning for both services, and a deprecated-asyncio-pattern scan.

### B. WORK ITEMS (one sentence each for all 15 WIs — not grouped)

- **WI-1 (HIGH)** — Add `TestStreamTokensBufferLimit` class to `test_transport.py` pinning the exact-boundary + (LIMIT+1) overflow behavior of `stream_tokens()` at `STREAM_TOKEN_BUFFER_LIMIT` (read from constants at pickup).
- **WI-2 (HIGH)** — Add `TestStreamTokensDecodeError` class pinning the malformed-frame continue-path in `stream_tokens()` (decode catch is `ValueError` per `transport.py:534-540`).
- **WI-3 (HIGH)** — Add `TestCheckPaStatusShortCircuit` class pinning the `if self._connected:` short-circuit at `transport.py:258-260`, asserting the handshake/send path is not invoked.
- **WI-4 (HIGH)** — Add `TestActionSubmitPromptBranches` class with the PGOV-denied branch test (`app.py:405-418`): assert `pgov_panel.display_denial(result)` once and `flush_tool_call_buffer(pgov_approved=False)` invoked.
- **WI-5 (HIGH)** — Extend `TestActionSubmitPromptBranches` with the PGOV-approved branch test (`app.py:419-436`): assert `flush_tool_call_buffer(pgov_approved=True)` invoked and denial panel NOT called.
- **WI-6 (HIGH)** — Extend `TestActionSubmitPromptBranches` with RuntimeError (`app.py:438-440` — "Error: {exc}" styling) and generic-Exception (`app.py:441-445` — "Unexpected error — Fail-Closed." + `logger.error(..., exc_info=True)`) handler tests using `caplog`.
- **WI-7 (HIGH)** — Strengthen tautological stub tests in `test_app.py` (existing `test_submit_noop_when_not_operational` / `test_submit_noop_when_no_gateway` near lines 74-86) to actually invoke `action_submit_prompt` under each guard condition and assert `gateway.send_prompt.assert_not_called()`; fall back to option (b) only if option (a) would require a production seam.
- **WI-8 (MEDIUM)** — Create `services/ui_shell/tests/test_session_panel.py` with `TestSessionPanelPublicMethods` + `TestSessionListItemLabelFormat` covering the four async methods of `SessionPanel` (`refresh_list`, `create_new_session`, `delete_current_session`, `select_session`) with monkey-patched `asyncio.to_thread` per Risk I.2, plus the `SessionListItem` label format `f"{title}  [dim]({turns})[/dim]"` derived from `session_panel.py:45-48`.
- **WI-9 (MEDIUM)** — Add `TestBootPollAttemptMarkers` class covering `app.py:237-284` attempt-marker progression; primary strategy = drive a mocked gateway whose `check_pa_status` resolves on attempt 3 with monotonic-clock monkeypatch; fallback per Risk I.6 = unit-test the `attempt_markers` list computation (`app.py:237-242`) only.
- **WI-10 (MEDIUM)** — Tighten PA handshake retry/backoff assertions in `test_transport.py` (`TestPaHandshakeRetry`): pin the sleep-duration sequence `[PA_HANDSHAKE_BACKOFF_BASE_S, PA_HANDSHAKE_BACKOFF_BASE_S * 2]` via a recording fake_sleep (Risk I.8), and pin `sleep` called exactly `(MAX_RETRIES - 1)` times when all retries fail.
- **WI-11 (MEDIUM)** — Add `TestStreamingFlagTransitions` class to `test_streaming.py` covering `StreamingDisplay._streaming` flips: True during non-final tokens, False on final token, False after `clear_display()`, False after `start_new_response()` (class name `StreamingDisplay`, not a speculated alternative — confirmed at `streaming.py:24`).
- **WI-12 (MEDIUM)** — Create `services/ui_gateway/tests/test_constants_ui_gateway.py` with `TestUiGatewayConstants` direct-assertion tests pinning every constant in `ui_gateway/src/constants.py` enumerated at pickup; no `shared.constants` re-exports are present in this file (verified at pickup), so the re-export-pinning block collapses to zero tests — I will confirm this in the completion report.
- **WI-13 (MEDIUM)** — Create `services/ui_shell/tests/test_constants_ui_shell.py` with `TestUiShellConstants` pinning all `ui_shell/src/constants.py` constants, including the full 6-key `PGOV_REASON_LABELS` mapping in one `test_pgov_reason_labels_complete_mapping` test, and the five `KEY_*` bindings.
- **WI-14 (LOW)** — Add `TestToolCallBufferBoundary` covering the `>=` overflow path in `transport.py:648` — fill to MAX-1, append once (no exception), append again (`ValueError` with production message).
- **WI-15 (LOW)** — Scan `services/ui_gateway/tests/**` and `services/ui_shell/tests/**` for `run_until_complete`; if none found (expected per Sprint 7 audit), close with a single-line confirmation in the completion report with no code changes.

### C. FILES TO CREATE

- `services/ui_shell/tests/test_session_panel.py` (WI-8)
- `services/ui_gateway/tests/test_constants_ui_gateway.py` (WI-12)
- `services/ui_shell/tests/test_constants_ui_shell.py` (WI-13)
- `docs/ledger/<YYYYMMDD_HHMMSS>_sprint8_ea3_ui-hardening.md` (Q1-1 per-file convention, predecessor `20260422_184004_sprint8_ea2_ao_sr_hardening`)

### D. FILES TO MODIFY

- `services/ui_gateway/tests/test_transport.py` (WI-1, WI-2, WI-3, WI-10, WI-14 — add new classes; do NOT rewrite existing)
- `services/ui_shell/tests/test_app.py` (WI-4, WI-5, WI-6, WI-7, WI-9 — add new classes; strengthen lines 74-86 stubs iff option (a) is feasible without a production seam)
- `services/ui_shell/tests/test_streaming.py` (WI-11 — add new class)

No `src/**`, `shared/**`, `launcher/**`, or `conftest.py` files will be modified. No `pyproject.toml` edits planned (no new markers needed).

### E. FILES TO READ

Production source (read-only): `services/ui_gateway/src/transport.py`, `services/ui_gateway/src/constants.py`, `services/ui_gateway/src/session_store.py`, `services/ui_shell/src/app.py`, `services/ui_shell/src/session_panel.py`, `services/ui_shell/src/streaming.py`, `services/ui_shell/src/constants.py`, `services/ui_shell/src/pgov_display.py`, `shared/constants.py`. Existing tests (for pattern reference): `services/ui_gateway/tests/test_transport.py`, `services/ui_gateway/tests/test_session_store.py`, `services/ui_shell/tests/test_app.py`, `services/ui_shell/tests/test_pgov_display.py`, `services/ui_shell/tests/test_streaming.py`, `services/assistant_orchestrator/tests/test_constants_ao.py` (EA-2 idiom), `services/semantic_router/tests/test_constants_sr.py` (re-export idiom via `is`). Governance: `docs/P5_TASK8_SDO_CONTINUATION_v1.0.xml`, `docs/sprints/sprint_8/strategic_design_vision.md`, `docs/ledger/20260422_184004_sprint8_ea2_ao_sr_hardening.md`, `docs/ledger/README.md`, `docs/TEST_GOVERNANCE.md`.

### F. DELIVERABLE STRUCTURE (verbatim)

- **Branch**: `feature/p5-task8-ea3-ui-hardening`
- **Test files + classes**:
  - `services/ui_gateway/tests/test_transport.py` → `TestStreamTokensBufferLimit` (WI-1), `TestStreamTokensDecodeError` (WI-2), `TestCheckPaStatusShortCircuit` (WI-3), `TestPaHandshakeRetry` — create or extend (WI-10), `TestToolCallBufferBoundary` (WI-14).
  - `services/ui_shell/tests/test_app.py` → `TestActionSubmitPromptBranches` (WI-4/5/6), `TestBootPollAttemptMarkers` (WI-9), in-place strengthening of `test_submit_noop_when_*` (WI-7 option (a)).
  - `services/ui_shell/tests/test_session_panel.py` → `TestSessionPanelPublicMethods`, `TestSessionListItemLabelFormat` (WI-8, NEW file).
  - `services/ui_shell/tests/test_streaming.py` → `TestStreamingFlagTransitions` (WI-11).
  - `services/ui_gateway/tests/test_constants_ui_gateway.py` → `TestUiGatewayConstants` (WI-12, NEW file).
  - `services/ui_shell/tests/test_constants_ui_shell.py` → `TestUiShellConstants` (WI-13, NEW file).
- **Naming conventions**: snake_case test functions prefixed `test_`; class names PascalCase prefixed `Test`; pytest-asyncio via `@pytest.mark.asyncio` on async tests; `AsyncMock` for awaitables, `Mock` for sync.
- **Ledger path**: `docs/ledger/<YYYYMMDD_HHMMSS>_sprint8_ea3_ui-hardening.md` with the frontmatter block verbatim from `<ledger_frontmatter>`.

### G. ORACLE EXPECTATION (verbatim)

```
git diff main...feature/p5-task8-ea3-ui-hardening --name-only | grep -vE "tests|conftest|docs|pyproject"
```

Expected output: **EMPTY** (zero lines).

### H. MATURE-NOT-MINIMAL 1-HOUR CAP ACKNOWLEDGMENT

Acknowledged per SDV §5.3 and prompt §10. Adjacent findings up to 1 hour absorbed inline; anything exceeding documented in completion report for Co-Lead.

### I. RISKS AND AMBIGUITIES

Detailed in Vikunja comment 331, covering Risks I.1 (Textual App no live loop), I.2 (asyncio.to_thread verification), I.6 (boot-poll entanglement fallback), I.7 (LOCALAPPDATA env), I.8 (asyncio.sleep monkeypatch). Divergence noted: `ui_gateway`/`ui_shell` constants do not re-export from `shared.constants`, so WI-12/13's re-export-pinning block collapses to zero tests (conditional per prompt phrasing).

### J. PRODUCTION FILE PROHIBITION ACKNOWLEDGMENT (verbatim quote)

From `<negative_constraints>` NC-1: "L-15 PRODUCTION FILE PROHIBITION — Zero production source files may be modified. Specifically: NO edits to `services/ui_gateway/src/**`, `services/ui_shell/src/**`, `shared/**`, `launcher/**`, or `services/*/src/**`. If a production change appears necessary to unblock a test (e.g., to add a seam), STOP, document the blocker in the completion report, and wait for SDO direction."

Also NC-6 (No live Textual App) and NC-7 (No new production seams) acknowledged.

---

## Plan-of-work cross-referenced to WIs

Execution order:

1. Branch from `09ff6d2` → `feature/p5-task8-ea3-ui-hardening`.
2. Pass 1 — transport.py tests (WI-1, WI-2, WI-3, WI-10, WI-14).
3. Pass 2 — streaming.py tests (WI-11).
4. Pass 3 — session_panel.py new file (WI-8).
5. Pass 4 — app.py `TestActionSubmitPromptBranches` (WI-4, WI-5, WI-6).
6. Pass 5 — app.py stub strengthening (WI-7).
7. Pass 6 — boot-poll (WI-9) with Risk I.6 fallback.
8. Pass 7 — constants pinning (WI-12, WI-13).
9. Pass 8 — deprecated asyncio scan (WI-15).
10. Ledger entry.
11. Quality gates COMPILE → TEST-FOCUSED → TEST-FULL → ORACLE.
12. Commit per `<commit_template>`.
13. Case C completion comment.
14. DEC-13 report.

## Gate label transition

- Applied `Gate:Pending-SDO` (label id 9) to Task 82.
- Removed `Gate:Pending-Execution` (label id 16) from Task 82.

## Budget self-check

Case A firing estimated 25–35 min of 90 min cap. Case C execution deferred to subsequent firing under fresh envelope.

## Cross-references

- **Source prompt**: `docs/scheduled/ea_queue/P5_TASK8_EA3_UI_HARDENING.xml`
- **SDV**: `docs/sprints/sprint_8/strategic_design_vision.md` §5.1 item 3, §5.3, §4
- **SDO continuation**: `docs/P5_TASK8_SDO_CONTINUATION_v1.0.xml`
- **Predecessor ledger**: `docs/ledger/20260422_184004_sprint8_ea2_ao_sr_hardening.md`
- **Vikunja comment**: 331 on Task 82
- **Parent HEAD**: `09ff6d2`
