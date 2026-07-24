---
role: ea_code
phase: completion
revision: 1
tracking_task: 82
vikunja_comment: null
posted_at: 2026-04-24T01:50:00Z
verdict: null
---

# Sprint 8 EA-5 — Completion Report

## Commits

On branch `feature/p5-task8-ea5-structural-cleanup` (parent: `88f371e`):

- `3f47a54` — WI-1 NPU → GPU rename across test identifiers.
- `d4dd794` — WI-2 extract jwt key-gen to `shared/tests/_keygen.py`.
- `4d87dfd` — WI-3 relocate 23 live-TCP tests to `tests/integration/`.
- `4f51eef` — WI-4 relocate non-cross-service P114 tests out of
  `tests/integration/` (16 moved, 3 deleted).
- `900f7b0` — WI-4 fix: restore `_capture_panel_text` helper and missing
  imports at relocation destinations.

## Diff summary (`git diff main...HEAD --stat`)

14 files changed, 1391 insertions(+), 1209 deletions(-). All under test paths:
`services/*/tests/`, `shared/tests/`, `tests/integration/`.

## Acceptance check results

| Gate | Command | Result |
|---|---|---|
| O-1 COMPILE | `pytest --collect-only -q shared/ services/ launcher/ tests/` | **PASS** — 1003 collected, 0 errors |
| O-2 TEST-FULL | `pytest shared/ services/ launcher/ --tb=short -q` | **PASS** — 981 passed, 22 skipped (34.86s) |
| O-3 ORACLE N-1 | `git diff main...HEAD --name-only \| grep -vE "tests/\|/tests"` | **EMPTY** — zero production-code files touched |
| O-4 DELTA | Total collected `shared/ services/ launcher/ tests/` | 1090 (main) → 1087 (branch) = **net −3**, matches prompt |

## Regression delta

Net −3 tests:
- +23 tests added at `tests/integration/test_ui_gateway_ipc.py` (11) +
  `test_shared_ipc_transport.py` (12)
- −23 tests removed from source modules (`services/ui_gateway/tests/test_transport.py`,
  `shared/tests/test_ipc_transport.py`)
- +16 tests added at `TestP114Relocated` classes across three service-unit
  modules
- −19 tests removed from `tests/integration/test_p114_ui_end_to_end.py`
  (16 relocated + 3 deleted: 3D.5 duplicate, 3D.11 duplicate, trivial
  stream-token-buffer constant-presence)

## Residual NPU references

Test-identifier grep (`_make_npu`, `TestPipelineWithNPUStub`,
`TestEndToEndWithNPUStub`, `NPU` in test docstrings implying preemption) —
zero residuals in test code. Remaining `NPU` tokens live in historical ADR
documents and Phase-2 gate-evidence JSON files, outside scope.

## Scope exceptions

1. Four non-live methods captured during WI-3 extraction (two transport-guard
   checks + two PGOV-result-cache checks) were moved back to
   `services/ui_gateway/tests/test_transport.py` as new classes
   `TestTransportNoTransportGuards` and `TestGetPGOVResultCache`, preserving
   the "live-TCP only" criterion for `tests/integration/`.
2. Fixture helpers (`_framer`, `_read_framed`, `_write_framed`,
   `_generate_test_certs`, `test_certs`) duplicated at WI-3 destinations per
   DEC-12 unit-policy (no cross-service `conftest.py` coupling).
3. `_capture_panel_text` helper re-added to `TestP114Relocated` at
   `services/ui_shell/tests/test_pgov_display.py` — required by four of the
   five relocated PGOV tests; restores behavioral fidelity.
4. Parent head: branched from `88f371e` per SDO Res 7 (prompt's stated parent
   `89ee727` was superseded by governance-only commits).

## Borderline-preserved tests (prompt §3D)

Confirmed intact in `tests/integration/test_p114_ui_end_to_end.py` post-WI-4:
- `TestP114GroupDBootPhase3Gating::test_no_prompt_dispatched_until_operational`
- `TestP114GroupDBootPhase3Gating::test_after_operational_prompt_dispatches_correctly`
- `TestP114GroupDBootPhase3Gating::test_boot_log_written_on_state_transitions`
- `TestP114GroupEPGOVDisplay::test_approved_result_does_not_trigger_pgov_panel_display`

## Ledger entry

`docs/ledger/20260423_235000_sprint8_ea5_structural-cleanup.md` — authored
this session, COMPLETE disposition.

## Follow-ups

None. All 6 WIs delivered to SDO-approved scope.
