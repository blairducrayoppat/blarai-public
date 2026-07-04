---
ledger_id: 20260423_235000_sprint8_ea5_structural-cleanup
date: 2026-04-23
sprint_id: 8
entry_type: EA
predecessor: 20260423_062642_sprint8_ea4_shared-launcher-hardening
branch: feature/p5-task8-ea5-structural-cleanup
merge_commit: null
disposition: COMPLETE
---

# Sprint 8 EA-5 — Cross-Service Structural Cleanup

## Summary

Structural-only test reorganization milestone. Renamed retired NPU nomenclature
to GPU (ADR-011), extracted a shared jwt key-gen utility to end a cross-service
import-layering inversion, relocated 23 live-TCP tests out of service-unit
modules into `tests/integration/`, and relocated 16 P114 UI tests from the
integration tree into their correct service-scope homes (deleting 3
duplicate/trivial tests). Pure test-file reorganization (N-1); no production
code was modified.

## Scope delivered

- **WI-1 NPU → GPU rename** — Identifiers, docstrings, and group headers updated
  across `services/assistant_orchestrator/tests/test_gpu_inference.py` (3 edits),
  `services/policy_agent/tests/test_hybrid_adjudicator.py` (`_make_npu_stub` →
  `_make_gpu_stub`, `TestPipelineWithNPUStub` → `TestPipelineWithGPUStub`),
  `services/policy_agent/tests/test_integration_car_pipeline.py`
  (`TestEndToEndWithNPUStub` → `TestEndToEndWithGPUStub`), and
  `tests/integration/test_p110_end_to_end.py` (`_make_npu_allow`/`_make_npu_deny`
  → `_make_gpu_allow`/`_make_gpu_deny`). Per SDO Res 2, `_make_gpu_deny` was
  kept as a rename of `_make_npu_deny`. Per SDO Res 3, `GPU_PRIORITY` was NOT
  introduced (not present in prod). Per SDO Res 4, docstrings were rewritten
  only where they contradicted ADR-011.
- **WI-2 shared jwt keygen extraction** — New `shared/tests/_keygen.py`
  re-exports the PA `jwt_minter` surface (`AgenticJWTMinter`, `EpochManager`,
  `MintedJWT`). Consumers
  `services/assistant_orchestrator/tests/test_entrypoint.py` and
  `shared/tests/test_jwt_validator.py` now import from `shared.tests._keygen`
  instead of `services.policy_agent.src.jwt_minter`, eliminating a cross-service
  import inversion. Per SDO Res 5, `generate_key_pair` was omitted since no
  consumer used it.
- **WI-3 live-TCP relocation** — 23 tests using real `asyncio.start_server` or
  live vsock sockets were moved to `tests/integration/test_ui_gateway_ipc.py`
  (11 tests) and `tests/integration/test_shared_ipc_transport.py` (12 tests),
  both carrying `pytestmark = pytest.mark.slow`. Four non-live methods
  inadvertently captured during extraction were moved back to
  `services/ui_gateway/tests/test_transport.py` as
  `TestTransportNoTransportGuards` and `TestGetPGOVResultCache`. Fixture
  duplication (e.g., `test_certs`) was preserved at the destination.
- **WI-4 P114 unit-scope relocation** — 16 tests relocated from
  `tests/integration/test_p114_ui_end_to_end.py` into service-scope modules as
  `TestP114Relocated`: 5 session-CRUD tests to
  `services/ui_gateway/tests/test_session_store.py`, 6 transport/stream tests
  to `services/ui_gateway/tests/test_transport.py`, 5 PGOV-display tests to
  `services/ui_shell/tests/test_pgov_display.py`. The `slow` marker was
  stripped at destinations (unit-scope per 3F.3). Three tests were deleted:
  `test_delete_session_removes_session_and_cascades_turns` (3D.5 duplicate),
  `test_tool_call_buffer_overflow_fail_closed` (3D.11 duplicate), and the
  module-level `test_p114_stream_token_buffer_limit_constant_present` (trivial
  constant-presence check). The four borderline-preserved tests named in the
  prompt (3D boot-phase trio + PGOV approved-path non-display) remain intact
  in the p114 module.

## Quality gates

| Gate | Result |
|---|---|
| COMPILE | `pytest --collect-only -q shared/ services/ launcher/ tests/` → 1003 tests collected, 0 errors. |
| TEST-FULL | `pytest shared/ services/ launcher/` → **981 passed, 22 skipped** in 34.86s. |
| ORACLE | `git diff main...HEAD --name-only` = 14 files, all under `services/*/tests/`, `shared/tests/`, `tests/integration/`. No production code touched (N-1). |
| DELTA | Total tests collected in `shared/ services/ launcher/ tests/` went from 1090 (main) to 1087 (branch) = **net −3** tests, matching the EA prompt expectation (3 deletions). |

## Residual NPU references

`grep -rn "NPU\|_make_npu\|npu_" shared/ services/ launcher/ tests/` residuals
were reviewed; remaining hits are in unrelated Phase-2 gate evidence files and
ADR historical context, not test identifiers. All test-identifier NPU
references have been renamed.

## Scope exceptions

- **Fixture duplication at WI-3 destinations (framer helpers, `test_certs`
  keypair generation)** — intentional per DEC-12 cross-service unit policy: the
  source modules retain their own copies for their non-live tests, and
  relocated suites carry the helpers they need without creating a
  cross-service `conftest.py` coupling.
- **`TestP114Relocated` wrapper class** — used at each WI-4 destination rather
  than merging methods into existing test classes to keep relocation provenance
  visible (prefixed header comment cites EA-5 WI-4 and the 3F.3 marker-strip
  rule).
- **`_capture_panel_text` helper re-added at pgov_display destination** — the
  helper method was part of the original p114 class and is required by four of
  the five relocated PGOV tests; adding it to the destination class is the
  minimum viable structural fidelity.

## Parent head

Branched from `88f371e` (current `main` at session start). The EA prompt's
stated parent `89ee727` had been superseded by governance-only commits
(`72e583a`, `e895fac`, `c943c9d`, `4be57ae`, `88f371e`) per SDO Res 7;
intermediate commits contained no test-file mutations that would invalidate
the structural-cleanup precondition.

## Oracle compliance

14 files changed; 0 outside test paths. No `services/*/src/`, `shared/` (non-
tests), `launcher/` (non-tests), or `pyproject.toml` files were modified.
Ledger entry and comprehension report commits are documentation-only.
