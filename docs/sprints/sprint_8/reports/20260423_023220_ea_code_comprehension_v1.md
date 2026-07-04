---
role: ea_code
phase: comprehension
revision: 1
tracking_task: 82
vikunja_comment: null
posted_at: 2026-04-23T02:32:20Z
verdict: null
---

# [agent:ea_code][phase:comprehension] Sprint 8 EA-4 — Shared + Launcher + Integration Hardening — Comprehension Gate v1

**Tracking task**: Vikunja #82
**Queue file**: `docs/scheduled/ea_queue/P5_TASK8_EA4_SHARED_LAUNCHER_HARDENING.xml`
**Branch target**: `feature/p5-task8-ea4-shared-launcher-hardening`

## Wake template recitation (sections + allowedTools)

Section headers of `docs/scheduled/wake_templates/ea_code_wake.md`:

- Phase 0 — Fleet-blocked exit
- Event-driven wake triggers (Q2-1 + ISS-4)
- Your scope for this firing
- State machine (DEC-12): Case A / B / C / D / E / F
- Formatting standard for Vikunja descriptions and disk reports (DEC-14.5)
- Report emission (DEC-13)
- M5 Comprehension Gate content
- Budget self-check
- Exit criteria
- Links

`--allowedTools` scope: `mcp__vikunja__* Read Write Edit Bash mcp__git__*`.

## EA prompt recitation

### Milestone Objective (verbatim)

Extend the Sprint 8 test suite to cover coverage gaps in `shared/` and `launcher/`: `shared/src/runtime_config.py` (4 untested functions), `launcher/guest_deploy.py` (`_validate_vsock_topology` 8 failure branches + `_validate_guest_runtime_configs` 3 failure scenarios), `launcher/__main__.py` (`_run_uat2_prompt_flow_preflight` + `_cleanup` teardown), `launcher/vm_manager.py` (`request_elevation`), `shared/schemas/car.py` (new `test_car.py`), and 6 untested IPC message type convenience encoders. **No production code is modified.**

### Work Items (11 WIs, one sentence each — no grouping)

- **WI-1** (HIGH): `TestResolveServiceRoot` — 2 tests (normal Python + PyInstaller frozen path via monkeypatched `sys.frozen`/`sys._MEIPASS`).
- **WI-2** (HIGH): `TestResolveDeploymentMode` — 3 tests (explicit param, env var `BLARAI_DEPLOYMENT_MODE`, default).
- **WI-3** (HIGH): `TestParseDeploymentMode` — 3 tests (`"host"`, `"guest"`, invalid string → `ValueError`).
- **WI-4** (HIGH): `TestBuildFailureFingerprint` — 2 tests (structure + required-key set equality).
- **WI-5** (HIGH): `TestValidateVsockTopologyFailures` — 8 tests, one per failure branch in `_validate_vsock_topology()`.
- **WI-6** (HIGH): `TestValidateGuestRuntimeConfigsFailures` — 3 tests (PA fail, AO fail, both fail).
- **WI-7** (HIGH): `TestRunUat2PromptFlowPreflight` — 2 tests (success + exception path).
- **WI-8** (HIGH): `TestCleanupAtExit` — 5 tests (services+VM, services-not-running, vm_was_started=False, session store teardown, None-guards).
- **WI-9** (HIGH): `TestRequestElevation` — 2 tests (success + failure) mocking `ctypes.windll.shell32.ShellExecuteW`.
- **WI-10** (MEDIUM): `TestCanonicalHash` (2), `TestIsComplete` (3), `TestDecisionArtifact` (1), `TestEnums` (3) in new `shared/tests/test_car.py`.
- **WI-11** (MEDIUM): 6 encoder tests for HANDSHAKE_REQUEST/RESPONSE, PROMPT_REQUEST, STREAM_TOKEN, PGOV_RESULT, GENERATION_COMPLETE in new `shared/tests/test_ipc_message_types.py`.

### Negative Constraints (8)

- **NC-1**: L-15 PURE TEST-AUTHORING — no edits to `shared/src/**`, `services/**/src/**`, `launcher/*.py` (non-test), or pyproject.toml outside test config.
- **NC-2**: No renames or file moves — add classes/methods in-place.
- **NC-3**: Per-file ledger (Q1-1) — `docs/ledger/<ts>_sprint8_ea4_shared-launcher-hardening.md`; predecessor `20260422_210246_sprint8_ea3_ui-hardening`.
- **NC-4**: No new runtime dependencies — only pytest, pytest-asyncio, pytest-mock, unittest.mock.
- **NC-5**: No real vsock/socket connections — mock transport layer.
- **NC-6**: No new production seams (no DI hooks, no constructor params added to prod code).
- **NC-7**: L-16 Sprint 9 coexistence — Sprint 9 writes `docs/governance/**`; don't touch it.
- **NC-8**: Scope-limited to named WI targets; document out-of-WI gaps in completion report only.

### Acceptance Checks / Quality Gates

- **COMPILE**: `python -c "import <each new/modified module>"` → no `ImportError`.
- **TEST-FOCUSED**: `.venv\Scripts\pytest shared/tests/ launcher/tests/ --tb=short -q` — all new tests pass, no regressions.
- **TEST-FULL**: `.venv\Scripts\pytest shared/ services/ launcher/ --tb=short -q` — **≥ 982 passed, 2 skipped** (962 baseline + 20 new minimum).
- **ORACLE**: `git diff main...feature/p5-task8-ea4-shared-launcher-hardening --name-only | grep -vE "tests|conftest|docs|pyproject"` → **EMPTY**.

## Comprehension — required sections

### A. MILESTONE OBJECTIVE (my words)

I will harden the Sprint 8 test baseline by authoring ≥ 20 new tests that cover the gaps SDO identified in `shared/src/runtime_config.py`, `shared/schemas/car.py`, `shared/src/ipc_types.py`, `launcher/guest_deploy.py`, `launcher/__main__.py`, and `launcher/vm_manager.py`. Coverage is organized into 11 work items yielding \~42 tests if every branch is covered — the 20-test floor is a minimum, not a ceiling. All tests are unit-level with mocked transport, subprocess, and ctypes calls; zero real vsock connections, zero production-code edits. Deliverables commit to `feature/p5-task8-ea4-shared-launcher-hardening` with a per-file ledger entry.

### B. WORK ITEMS

(See `EA prompt recitation → Work Items` above — 11 items, one sentence each, not grouped.)

### C. FILES TO CREATE

- `shared/tests/test_car.py` — new, 4 classes covering canonical_hash / is_complete / DecisionArtifact / enums.
- `shared/tests/test_ipc_message_types.py` — new, 6 encoder tests (or added to existing IPC test file if present; will verify at pickup).
- `docs/ledger/<YYYYMMDD_HHMMSS>_sprint8_ea4_shared-launcher-hardening.md` — per-file ledger entry.

### D. FILES TO MODIFY

- `shared/tests/test_runtime_config.py` (modify existing or create if absent) — WI-1..WI-4 classes.
- `launcher/tests/test_guest_deploy.py` (modify existing) — WI-5, WI-6 classes.
- `launcher/tests/test_main.py` (modify existing or create if absent) — WI-7, WI-8 classes.
- `launcher/tests/test_vm_manager.py` (modify existing or create if absent) — WI-9 class.

### E. FILES TO READ (production source for context)

- `shared/src/runtime_config.py` (WI-1..WI-4)
- `shared/schemas/car.py` (WI-10)
- `shared/src/ipc_types.py` (WI-11)
- `launcher/guest_deploy.py` (WI-5, WI-6)
- `launcher/__main__.py` (WI-7, WI-8)
- `launcher/vm_manager.py` (WI-9)
- Each existing test file listed in FILES TO MODIFY (for pattern continuity)
- `docs/P5_TASK8_SDO_CONTINUATION_v1.0.xml` §5-§7
- `docs/sprints/sprint_8/strategic_design_vision.md` §4, §5.1, §5.2, §5.3
- `docs/ledger/20260422_210246_sprint8_ea3_ui-hardening.md` (format precedent)
- `docs/ledger/README.md` (Q1-1 convention)

### F. DELIVERABLE STRUCTURE (verbatim recitation)

**Branch**: `feature/p5-task8-ea4-shared-launcher-hardening`

**Test classes + test counts**:

| File | Class | Tests |
|---|---|---|
| `shared/tests/test_runtime_config.py` | `TestResolveServiceRoot` | 2 |
| `shared/tests/test_runtime_config.py` | `TestResolveDeploymentMode` | 3 |
| `shared/tests/test_runtime_config.py` | `TestParseDeploymentMode` | 3 |
| `shared/tests/test_runtime_config.py` | `TestBuildFailureFingerprint` | 2 |
| `launcher/tests/test_guest_deploy.py` | `TestValidateVsockTopologyFailures` | 8 |
| `launcher/tests/test_guest_deploy.py` | `TestValidateGuestRuntimeConfigsFailures` | 3 |
| `launcher/tests/test_main.py` | `TestRunUat2PromptFlowPreflight` | 2 |
| `launcher/tests/test_main.py` | `TestCleanupAtExit` | 5 |
| `launcher/tests/test_vm_manager.py` | `TestRequestElevation` | 2 |
| `shared/tests/test_car.py` | `TestCanonicalHash` | 2 |
| `shared/tests/test_car.py` | `TestIsComplete` | 3 |
| `shared/tests/test_car.py` | `TestDecisionArtifact` | 1 |
| `shared/tests/test_car.py` | `TestEnums` | 3 |
| `shared/tests/test_ipc_message_types.py` | (6 encoder tests) | 6 |

**Total new tests**: \~45 (20-test floor cleared with substantial margin).

**Ledger path**: `docs/ledger/<YYYYMMDD_HHMMSS>_sprint8_ea4_shared-launcher-hardening.md`

**Ledger frontmatter** (verbatim):

```yaml
---
ledger_id: <YYYYMMDD_HHMMSS>_sprint8_ea4_shared-launcher-hardening
date: <YYYY-MM-DD>
sprint_id: 8
entry_type: EA
predecessor: 20260422_210246_sprint8_ea3_ui-hardening
branch: feature/p5-task8-ea4-shared-launcher-hardening
merge_commit: null
disposition: COMPLETE
---
```

### G. ORACLE EXPECTATION

Command:

```
git diff main...feature/p5-task8-ea4-shared-launcher-hardening --name-only | grep -vE "tests|conftest|docs|pyproject"
```

Expected output: **EMPTY**. Any path matching `shared/src/`, `services/*/src/`, or `launcher/*.py` (non-test) is an L-15 violation and halts the EA.

### H. QUALITY GATE FLOOR

- **Full-suite floor**: **982 passed, 2 skipped** (962 baseline + 20 new-test minimum).
- **New-test minimum**: **20** (the WI decomposition yields \~42; the floor is a minimum).

### I. RISKS AND AMBIGUITIES (addressing I.1–I.8)

- **I.1** PyInstaller monkeypatching (WI-1): use `monkeypatch.setattr(sys, "frozen", True, raising=False)` and `monkeypatch.setattr(sys, "_MEIPASS", "/fake/meipass", raising=False)`; rely on fixture teardown.
- **I.2** env isolation (WI-2/3): `monkeypatch.setenv` / `monkeypatch.delenv(..., raising=False)`; no direct `os.environ` in test bodies.
- **I.3** vsock evidence path (WI-5): identify constant from source, monkeypatch to `tmp_path / "evidence.json"`.
- **I.4** service imports at module load (WI-5/6): inspect imports at top of `guest_deploy.py`; mock `sys.modules` / conftest-level if side effects exist; never bare-import without verifying.
- **I.5** `__main__` import side effects (WI-7/8): patch `sys.argv = ["__main__"]` pre-import; mock `signal.signal` if needed; mirror existing `test_main.py` pattern.
- **I.6** cleanup globals (WI-8): `monkeypatch.setattr(main_module, "_pa_service", mock_service)` pattern; identify exact global names from source.
- **I.7** ctypes Windows-only (WI-9): mock at `ctypes.windll.shell32.ShellExecuteW` or the wrapper; do NOT import `ctypes.windll` in test body.
- **I.8** EA-4 sizing: \~45 tests planned; 20-floor cleared with margin; "mature not minimal" honored.

### J. PRODUCTION CODE PROHIBITION ACKNOWLEDGMENT

Quoted L-15 prohibition (verbatim from prompt):

> This is a PURE TEST-AUTHORING milestone. DO NOT modify any file outside tests/, conftest.py, docs/, or pyproject.toml. If a production code change is required to unblock a test, STOP, document the blocker in your completion report, and wait for SDO direction. Do not make the change unilaterally.

I acknowledge this prohibition absolutely. If any test requires a production-code change to pass, I will STOP, branch-preserve, and post a blocker comment for SDO. I will not unilaterally modify `shared/src/`, `services/*/src/`, or `launcher/*.py` (non-test) at any point in this EA.

## Plan-of-work (cross-referenced to WIs)

1. **Parent head verify (L-13)** — current `main` HEAD is `f204a24` (prompt said `ad311ac`; HEAD has advanced via two ISS-4 merges that do not touch tests or prod code — safe to branch from `f204a24`). I will `git checkout -b feature/p5-task8-ea4-shared-launcher-hardening` from `f204a24`.
2. **Source read pass** — read all 6 production source files + 4 existing test files before writing any test.
3. **WI-1..WI-4** — extend/create `shared/tests/test_runtime_config.py` (10 tests).
4. **WI-10** — create `shared/tests/test_car.py` (9 tests across 4 classes).
5. **WI-11** — create `shared/tests/test_ipc_message_types.py` (6 tests).
6. **WI-5..WI-6** — extend `launcher/tests/test_guest_deploy.py` (11 tests).
7. **WI-7..WI-8** — extend/create `launcher/tests/test_main.py` (7 tests).
8. **WI-9** — extend/create `launcher/tests/test_vm_manager.py` (2 tests).
9. **Gate runs** — COMPILE → TEST-FOCUSED → TEST-FULL → ORACLE.
10. **Ledger** — author `docs/ledger/<ts>_sprint8_ea4_shared-launcher-hardening.md`.
11. **Commit + completion comment + SDO trigger**.

## Parent head verify (L-13)

Current `main` HEAD: `f204a24` (Merge `feature/iss-4-trigger-protocol-wake-templates`). Prompt-stated parent `ad311ac` has been superseded by two ISS-4 wake-template/launcher-gate merges that touch only `tools/scheduled-tasks/` and `docs/scheduled/wake_templates/` — neither directory is in this EA's working set. Branching from `f204a24` is safe per prompt §1 ("If HEAD has advanced, use the current main HEAD").

---

**Status**: STOP — awaiting `[agent:sdo][phase:comprehension-review] VERDICT: APPROVED`.
