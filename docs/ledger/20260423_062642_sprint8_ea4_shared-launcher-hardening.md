---
ledger_id: 20260423_062642_sprint8_ea4_shared-launcher-hardening
date: 2026-04-23
sprint_id: 8
entry_type: EA
predecessor: 20260422_210246_sprint8_ea3_ui-hardening
branch: feature/p5-task8-ea4-shared-launcher-hardening
merge_commit: null
disposition: COMPLETE
---

# Sprint 8 EA-4 — Shared + Launcher + Integration Hardening

## Summary

Extended the Sprint 8 test suite to cover coverage gaps in `shared/` and `launcher/` components. Pure test-authoring milestone (L-15); no production code was modified.

## Scope delivered

- **WI-1 TestResolveServiceRoot** (2 tests) — normal Python + PyInstaller `_MEIPASS` branches.
- **WI-2 TestResolveDeploymentMode** (3 tests) — explicit parameter, env var, default.
- **WI-3 TestParseDeploymentMode** (3 tests) — `host`, `guest`, invalid-string `ConfigResolutionError`.
- **WI-4 TestBuildFailureFingerprint** (2 tests) — structure + exact-key-set.
- **WI-5 TestValidateVsockTopologyFailures** (8 tests) — all failure branches of `_validate_vsock_topology`: evidence-missing, malformed-JSON, disposition-not-PASS, vm_id-mismatch, service_guid-mismatch, vsock_port-mismatch, connection-unsuccessful, tcp_ip_used-true.
- **WI-6 TestValidateGuestRuntimeConfigsFailures** (3 tests) — PA-fail, AO-fail, both-fail.
- **WI-7 TestRunUat2PromptFlowPreflight** (2 tests) — success PASS-evidence + exception FAIL-evidence paths.
- **WI-8 TestCleanupAtExit** (5 tests) — services-running/vm-started, services-not-running, vm-not-started, session-store-close, all-None guards.
- **WI-9 TestRequestElevation** (3 tests) — ShellExecuteW success, low-return decline, OSError (over the WI minimum of 2).
- **WI-10 test_car.py** (9 tests) — TestCanonicalHash (2), TestIsComplete (3), TestDecisionArtifact (1), TestEnums (3).
- **WI-11 test_ipc_message_types.py** (6 tests) — one encoder roundtrip per UI-Gateway message type: HANDSHAKE_REQUEST, HANDSHAKE_RESPONSE, PROMPT_REQUEST, STREAM_TOKEN, PGOV_RESULT, GENERATION_COMPLETE.

**Total new tests:** 46 (over the 20-test floor; within the \~42-test WI decomposition estimate).

## Quality gates

| Gate | Result |
|---|---|
| COMPILE | All 6 test modules import without error (covered by pytest collection). |
| TEST-FOCUSED | `shared/tests/ launcher/tests/` — all pass. |
| TEST-FULL | `shared/ services/ launcher/` — **1008 passed, 2 skipped** (baseline 962 → +46). Floor 982 exceeded. |
| ORACLE | `git diff main...feature/p5-task8-ea4-shared-launcher-hardening --name-only | grep -vE "tests|conftest|docs|pyproject"` = EMPTY. |

## Path divergence from EA prompt

The EA prompt referenced several paths that do not match the current repo layout:

- Prompt: `shared/src/runtime_config.py` → actual: `shared/runtime_config.py`.
- Prompt: `shared/src/ipc_types.py` → actual: `shared/ipc/protocol.py` (encoders live on `MessageFramer`).
- Prompt: `launcher/tests/test_main.py` → actual: `launcher/tests/test_launcher.py` (existing test module for `launcher.__main__`).

New tests for WI-7/WI-8 were appended to the existing `test_launcher.py` rather than creating a parallel `test_main.py`, preserving a single module per production file. No production code was touched.

## Parent head

Branched from `24ec0d9` (current `main` at session start). The prompt's stated parent `ad311ac` had been superseded by a subsequent merge commit; per the prompt's instruction ("If HEAD has advanced, use the current main HEAD."), the current HEAD was used.

## Oracle compliance

No files outside `tests/`, `docs/`, and ledger paths were modified. The transient modification to `phase2_gates/evidence/uat2_real_runtime_activation.json` produced by an in-place launcher import during test collection was reverted prior to commit.
