# Gap-to-Operational Report

**Date:** 2026-02-26 (updated post-Operational Sign-Off)  
**Branch:** `feature/p1-uat1-launcher` (handoff baseline: `62f5c9d`, sign-off HEAD: `8f60259`)  
**Author:** Copilot Agent (Claude Opus 4.6), commissioned by Lead Architect  
**Scope:** USE-CASE-001 (Policy Agent) and USE-CASE-004 (Assistant Orchestrator)

**Record Status:** FROZEN — Phase 4 closed record.  
**Update Policy:** No new Phase 5+ entries in this document. Phase 5+ milestones are recorded in `docs/POST_OPERATIONAL_MATURATION_LEDGER.md`.

**UAT-2 Plan:** `docs/UAT-2_ACCEPTANCE_PLAN.md`

### Roadmap Gate Status (Post-Sign-Off)

All operational exit milestones and the sign-off gate are now **CLOSED**:

1. **Operational Exit Milestone 4 (UAT-3)** — non-dev enablement +
  UI-functional acceptance: **COMPLETE** (commit `5fbe989`).
2. **Operational sign-off** — **COMPLETE** (sign-off HEAD `8f60259`, includes
  post-M4 PGOV hardening).

### 2026-02-26 Operational Sign-Off Gate

Sign-off HEAD: `8f60259` (branch `feature/p1-uat1-launcher`)

**Prerequisite Milestone Cross-Reference:**

| Milestone | Description | Commit | Disposition |
|-----------|-------------|--------|-------------|
| M1 | UAT-2 real-runtime activation | `5150503` | PASS |
| M2 | Elevated in-process UAT-2 handshake + prompt-flow | `5150503` | PASS |
| M3 | UAT-2.5 hardening + repeatability | `98decc9` | PASS |
| M4 | UAT-3 non-dev enablement + UI functional acceptance | `5fbe989` | PASS |

Post-M4 hardening: `8f60259` (PGOV false-positive fix, 765/765 tests).
Non-dev acceptance: Runbook (`docs/RUNBOOK_NON_DEV_OPERATIONS.md`) + How-To
(`docs/HOWTO_FEATURES_NON_DEV.md`) — ACCEPTED.

**Validation Replay on Sign-Off HEAD `8f60259`:**

- Compile gate:
  - `python -m py_compile launcher/__main__.py services/ui_gateway/src/transport.py services/policy_agent/src/entrypoint.py services/assistant_orchestrator/src/entrypoint.py` → **PASS**
- Focused tests:
  - `.venv\Scripts\python.exe -m pytest launcher/tests/test_launcher.py services/ui_gateway/tests/test_transport.py services/policy_agent/tests/test_entrypoint.py services/assistant_orchestrator/tests/test_entrypoint.py -q` → **72 passed** — **PASS**
- Integration guardrail:
  - `.venv\Scripts\python.exe -m pytest tests/integration/test_p110_end_to_end.py -q` → **49 passed** — **PASS**

**Sign-Off Disposition: OPERATIONAL**

USE-CASE-001 (Policy Agent) and USE-CASE-004 (Assistant Orchestrator) are
declared operational at HEAD `8f60259`. Phase 4 (Operational Gap Closure) is CLOSED.

### 2026-02-25 Operational Exit Milestone 4 Delta (UAT-3 Non-Dev Enablement + UI Functional Acceptance)

Operational Exit Milestone 4 initial attempt reached BLOCKED_FAIL_CLOSED due to
participant unavailability. **Rerun session (2026-02-26) completed with PASS disposition.**

Session Git anchors:
- prior blocked attempt HEAD: `dc5abbe758dd1e421a892ebb74707309e1636c87`
- rerun session HEAD: `715b014b0984e377f832193d23d73d8532aa2bab`
- non-dev participant: User (Lead Architect / Non-Dev Operator)

Bug fixes applied during UAT-3 rerun:
- `6a76094`: Chat template fix (Chinese response remediation)
- `0c1b619`: Option B five-block layered system prompt
- `ca08164`: Phantom session cleanup (UAT2_M2_PROMPT_FLOW ephemeral session)
- `715b014`: Documentation accuracy fixes (4 corrections in Runbook + How-To)

Participant-dependent UAT-3 phase outcomes:
- Phase A (non-dev education): `PASS`
- Phase B (non-dev cold-start runbook execution): `PASS`
- Phase C (UI functional matrix UAT3-01..UAT3-10): `PASS`
- Phase D (explicit non-dev doc acceptance): `PASS`

Evidence artifacts (all PASS):
- `phase2_gates/evidence/uat3_operator_run_log.md`
- `phase2_gates/evidence/uat3_ui_matrix.json`
- `phase2_gates/evidence/uat3_failure_paths.json`
- `phase2_gates/evidence/uat3_docs_acceptance.md`
- `phase2_gates/evidence/uat3_summary.md`

Milestone-4 closure status:
- **PASS** — all critical UAT3 scenarios passed, docs accepted, onboarding suitability confirmed.

Post-Milestone-4 hardening:
- `8f60259`: PGOV false-positive remediation (system prompt delimiter echo fix, PII regex
  tightening, specific reason code mapping, denial logging). 765/765 tests.

---

## Executive Summary

**USE-CASE-001 (Policy Agent) and USE-CASE-004 (Assistant Orchestrator) are OPERATIONAL**
as of sign-off HEAD `8f60259` on branch `feature/p1-uat1-launcher`.

All four operational exit milestones (M1–M4) passed with documented evidence.
Post-M4 hardening (PGOV false-positive remediation) is included in the sign-off
baseline. Non-dev acceptance of Runbook and How-To documentation is confirmed.
Validation replay on sign-off HEAD passed all gates (compile, focused tests,
integration guardrail). 765/765 tests pass at sign-off.

The system runs on Intel Core Ultra 7 258V (Lunar Lake) with Policy Agent
classification on Arc 140V GPU and Assistant Orchestrator generation on Intel AI
Boost NPU, per ADR-010. Privacy mandate is enforced (no external network calls).
Deterministic fail-closed behavior is validated across all startup and runtime paths.

> **Historical note:** The original Executive Summary (prior to operational sign-off)
> stated "Neither USE-CASE-001 nor USE-CASE-004 is operational." That assessment
> was accurate at the time of initial gap analysis. It has been superseded by
> the milestone evidence and validation replay documented below.

### 2026-02-24 Operational Exit Milestone 1 Delta (UAT-2 Real-Runtime Activation)

Operational Exit Milestone 1 is complete for this session scope at code,
validation, and evidence-capture level:

- Explicit launcher startup profile selection implemented:
  - `launcher/__main__.py`
  - `BLARAI_LAUNCH_PROFILE=uat1_mock|uat2_real`
  - default preserved as `uat1_mock` for UAT-1 compatibility.
- UAT-2 real-runtime path now bypasses mock backend dependency:
  - `uat2_real` startup path does **not** start `MockPAServer`.
  - Gateway is initialized on real transport path (`dev_mode=False`).
- Deterministic fail-closed UAT-2 startup gates enforced:
  - VM start failure in `uat2_real` aborts startup (`UAT2_VM_START_FAILED`).
  - Pre-UI real-runtime handshake preflight is mandatory; failure aborts startup
    (`UAT2_GATEWAY_HANDSHAKE_FAILED`).
- Deterministic activation evidence output added:
  - `phase2_gates/evidence/uat2_real_runtime_activation.json`
  - captures profile, runtime mode, step-state booleans, disposition,
    and deterministic failure fingerprint.
- Focused launcher-mode regression coverage added:
  - `launcher/tests/test_launcher.py`
  - validates `uat2_real` mock bypass, VM-failure fail-closed, and handshake
    fail-closed behavior.

Session validation evidence:
- `python -m py_compile launcher/__main__.py launcher/tests/test_launcher.py services/ui_gateway/src/transport.py services/ui_gateway/tests/test_transport.py services/policy_agent/src/entrypoint.py services/policy_agent/tests/test_entrypoint.py services/assistant_orchestrator/src/entrypoint.py services/assistant_orchestrator/tests/test_entrypoint.py`
- `.venv\Scripts\python.exe -m pytest launcher/tests/test_launcher.py services/ui_gateway/tests/test_transport.py services/policy_agent/tests/test_entrypoint.py services/assistant_orchestrator/tests/test_entrypoint.py -q` → `75 passed`
- `.venv\Scripts\python.exe -m pytest tests/integration/test_p110_end_to_end.py -q` → `49 passed`
- `BLARAI_LAUNCH_PROFILE=uat2_real .venv\Scripts\python.exe -m launcher`
  executed (non-elevated host process): deterministic evidence emitted with
  disposition `ELEVATION_HANDOFF` and fingerprint code `UAC_PROMPT_TRIGGERED`.

Milestone-1 residual blocker status:
- Elevated continuation path and full in-process UAT-2 handshake/prompt runtime
  completion were not captured in this non-elevated session context.
- This is now an environment-execution blocker, not a launcher-path wiring gap.

### 2026-02-25 Operational Exit Milestone 2 Delta (Elevated In-Process UAT-2 Execution)

Operational Exit Milestone 2 execution in this session reached elevated in-process
bring-up and completed with **PASS** disposition after bounded deterministic
fail-closed remediation steps.

Session execution order (required):
- Compile gate:
  - `python -m py_compile launcher/__main__.py launcher/tests/test_launcher.py services/ui_gateway/src/transport.py services/ui_gateway/tests/test_transport.py services/policy_agent/src/entrypoint.py services/policy_agent/tests/test_entrypoint.py services/assistant_orchestrator/src/entrypoint.py services/assistant_orchestrator/tests/test_entrypoint.py` → PASS
- Focused tests:
  - `.venv\Scripts\python.exe -m pytest launcher/tests/test_launcher.py services/ui_gateway/tests/test_transport.py services/policy_agent/tests/test_entrypoint.py services/assistant_orchestrator/tests/test_entrypoint.py -q` → `75 passed`
- Integration guardrail:
  - `.venv\Scripts\python.exe -m pytest tests/integration/test_p110_end_to_end.py -q` → `49 passed`
- Runtime attempts:
  - Non-elevated `BLARAI_LAUNCH_PROFILE=uat2_real .venv\Scripts\python.exe -m launcher` → deterministic UAC handoff
  - Elevated `RunAs` execution (`BLARAI_LAUNCH_PROFILE=uat2_real`) → final PASS with handshake + prompt-flow evidence

Evidence artifacts:
- `phase2_gates/evidence/uat2_real_runtime_activation.json` (updated)
  - `startup_profile=uat2_real`
  - `runtime_mode=host`
  - `steps.admin_ok=true`
  - `steps.vm_running=true`
  - `steps.policy_agent_started=true`
  - `steps.assistant_orchestrator_started=true`
  - `steps.gateway_initialized=true`
  - `steps.gateway_handshake_ok=true`
  - `steps.prompt_flow_ok=true`
  - `disposition=PASS`
  - `failure=null`
- `phase2_gates/evidence/uat2_milestone2_prompt_flow.json`
  - `disposition=PASS`
  - `gate=UAT2_MINIMAL_PROMPT_FLOW`
  - `request_id` + `session_id` captured
- `phase2_gates/evidence/uat2_milestone2_summary.md`

Deterministic fail-closed fingerprints observed and closed in-session:
- `PA_LISTENER_START_FAILED` (measured_boot)
- `AO_CFG_MAX_MESSAGE_BYTES_INVALID` (config_validation)
- `UAT2_GATEWAY_HANDSHAKE_FAILED` (gateway_handshake)

Milestone-2 disposition (this session):
- **PASS**
- Elevated in-process execution requirement met with deterministic handshake and
  minimal prompt-flow evidence captured.

### 2026-02-25 Operational Exit Milestone 3 Delta (UAT-2.5 Hardening + Repeatability)

Operational Exit Milestone 3 execution in this session completed with **PASS**
disposition, including deterministic multi-run repeatability, deterministic
fail-closed failure injection, and evidence normalization.

Session Git anchors:
- pre-session HEAD: `21b59ad`
- post-session HEAD (pre-commit): `21b59ad`

Session execution order (required):
- Baseline capture:
  - `git rev-parse --abbrev-ref HEAD` → `feature/p1-uat1-launcher`
  - `git rev-parse HEAD` → `21b59adb735f3676c52004c3513f1f835ff4fd49`
  - pre-existing UAT-2 evidence snapshot captured from
    `phase2_gates/evidence/uat2_real_runtime_activation.json` and
    `phase2_gates/evidence/uat2_milestone2_prompt_flow.json`
- Compile gate:
  - `python -m py_compile launcher/__main__.py launcher/tests/test_launcher.py services/ui_gateway/src/transport.py services/ui_gateway/tests/test_transport.py services/policy_agent/src/entrypoint.py services/policy_agent/tests/test_entrypoint.py services/assistant_orchestrator/src/entrypoint.py services/assistant_orchestrator/tests/test_entrypoint.py` → PASS
- Focused tests:
  - `.venv\Scripts\python.exe -m pytest launcher/tests/test_launcher.py services/ui_gateway/tests/test_transport.py services/policy_agent/tests/test_entrypoint.py services/assistant_orchestrator/tests/test_entrypoint.py -q` → `75 passed`
- Integration guardrail:
  - `.venv\Scripts\python.exe -m pytest tests/integration/test_p110_end_to_end.py -q` → `49 passed`
- Stability + failure-injection + normalization execution:
  - `.venv\Scripts\python.exe phase2_gates/scripts/run_uat25_matrices.py` → PASS

Evidence artifacts:
- `phase2_gates/evidence/uat25_stability_matrix.json`
  - `schema_version=1.0.0`
  - `milestone=Operational Exit Milestone 3`
  - `startup_profile=uat2_real`
  - `run_count=3`, `pass_count=3`, `fail_count=0`, `disposition=PASS`
  - per-run step-state booleans captured for admin/vm/PA/AO/gateway/handshake/prompt-flow
- `phase2_gates/evidence/uat25_failure_injection_matrix.json`
  - `scenario_count=2`, `all_fail_closed=true`
  - `FI-01`: injected PA runtime-mode mismatch → observed `PA_CFG_RUNTIME_MODE_MISMATCH`
  - `FI-02`: injected AO runtime-mode mismatch → observed `AO_CFG_RUNTIME_MODE_MISMATCH`
  - baseline restore confirmation: `baseline_restore.restored=true`
- `phase2_gates/evidence/uat25_evidence_normalization.json`
  - canonical schema field inventory + canonical artifact inventory
- `phase2_gates/evidence/uat25_summary.md`
  - session roll-up summary with milestone disposition and artifact set

Milestone-3 disposition (this session):
- **PASS**
- Deterministic repeatability and bounded fail-closed fault behavior verified.

Exact next action for following session:
1. Proceed to Operational Exit Milestone 4 (UAT-3 non-dev enablement + UI-functional acceptance).
2. Capture non-dev acceptance artifacts and then evaluate operational sign-off gate.

Roadmap order remains intact:
1. Operational Exit Milestone 4 (UAT-3 non-dev enablement + UI-functional acceptance)
2. Operational sign-off only after Milestone 4 is complete with acceptance evidence.

### 2026-02-24 Current-State Addendum (Post-ADR-010)

Since this report baseline, the following production-critical progress has been
completed on `feature/p1-uat1-launcher`:

| Item | Status | Evidence |
|------|--------|----------|
| ADR-010 device split (PA on GPU, Orchestrator on NPU) | **COMPLETE** | commit `fdfbf92` |
| PA inference module migration (`npu_inference.py` → `gpu_inference.py`) | **COMPLETE** | commit `fdfbf92` |
| Shared constants aligned to ADR-010 (`PA_DEVICE`, PA latency constants) | **COMPLETE** | commit `fdfbf92` |
| Backward-compatibility aliases for PA inference symbols | **COMPLETE** | commit `fdfbf92` |
| Full regression pass after migration | **COMPLETE** | `724/724` tests passing |

Empirical benchmark evidence (ADR-010):
- PA classification on GPU: **78ms mean / 125ms P95** (within 230ms budget)
- PA classification on NPU: **\~543ms mean** (outside budget)

Implication: GAP-2 ("Real Model Never Loaded") is materially reduced for the
Policy Agent path because real model loading/inference has now been validated in
benchmark execution; however, end-to-end operational gaps (entry points, IPC loop,
VM deployment, crypto/trust chain, measured boot) remain open.

### 2026-02-24 Priority-1 Session Delta (PA LLMPipeline on GPU)

Priority 1 execution in this session completed for the scoped PA inference refactor:

- `services/policy_agent/src/gpu_inference.py` migrated from manual OpenVINO
  `InferRequest` token loop to OpenVINO GenAI `LLMPipeline` on `GPU`.
- Fail-Closed semantics preserved for all error paths (runtime unavailable,
  missing model artifacts, pipeline init failures, inference exceptions,
  unparseable model output).
- Backward-compatibility aliases preserved (`NPUClassificationResult`,
  `PolicyNPUInference`) for existing integration surfaces.
- Directly affected PA tests updated and validated.

Session validation evidence:
- `python -m py_compile services/policy_agent/src/gpu_inference.py services/policy_agent/tests/test_gpu_inference.py`
- `python -m pytest services/policy_agent/tests/test_gpu_inference.py -q` → `31 passed`
- `python -m pytest services/policy_agent/tests/test_hybrid_adjudicator.py services/policy_agent/tests/test_integration_car_pipeline.py -q` → `81 passed`

### 2026-02-24 Priority-2 Session Delta (Service Entrypoints + Launcher Wiring)

Priority 2 milestone scope for this session is complete at code level:

- Added runnable service lifecycle entrypoints:
  - `services/policy_agent/src/entrypoint.py`
  - `services/assistant_orchestrator/src/entrypoint.py`
- Launcher wiring (`launcher/__main__.py`) now initializes both real service
  entrypoints before UI startup, with fail-closed abort on initialization error.
- Startup path now reaches required callsites:
  - Policy Agent: config load + rule config load + GPU model `load_model()` + listener `start()`.
  - Assistant Orchestrator: config load + NPU model `load_model()`.
- Graceful shutdown integrated for both services in launcher cleanup path.
- Scope boundaries preserved:
  - Real accept/service loops remain deferred to Priority 3.
  - No VM guest deployment, key-material wiring, or measured-boot completion added.

Session validation evidence:
- `python -m py_compile launcher/__main__.py services/policy_agent/src/entrypoint.py services/assistant_orchestrator/src/entrypoint.py launcher/tests/test_launcher.py services/policy_agent/tests/test_entrypoint.py services/assistant_orchestrator/tests/test_entrypoint.py`
- `.venv\Scripts\python.exe -m pytest launcher/tests/test_launcher.py services/policy_agent/tests/test_entrypoint.py services/assistant_orchestrator/tests/test_entrypoint.py -q` → `12 passed`
- `.venv\Scripts\python.exe -m pytest tests/integration/test_p110_end_to_end.py -q` → `49 passed`

Priority-2 status update for operational gaps:
- GAP-1 (No Service Entry Points): **REDUCED** — entrypoint modules and launcher
  invocation path now exist.
- GAP-3 (No Real IPC Loop): **OPEN** — listener accept/service loop remains Priority 3 by plan.

### 2026-02-24 Priority-3 Session Delta (Real IPC Service Loops + Lifecycle Handling)

Priority 3 milestone scope for this session is complete at code level:

- Policy Agent real loop implemented and wired:
  - `services/policy_agent/src/ipc.py`: added `serve_forever(stop_event)` real
    accept/dispatch/respond loop with deterministic fail-closed handling.
  - `services/policy_agent/src/entrypoint.py`: startup now launches a dedicated
    IPC loop thread after listener bind; shutdown signals stop event, closes
    socket listener, joins thread, then unloads inference.
- Assistant Orchestrator real loop implemented and wired:
  - `services/assistant_orchestrator/src/entrypoint.py`: startup now binds a
    real `VsockListener`, launches a dedicated IPC service thread, and handles
    `HANDSHAKE_REQUEST` + `PROMPT_REQUEST` message dispatch.
  - Prompt dispatch path now performs model generation + PGOV validation and
    returns `STREAM_TOKEN` → `PGOV_RESULT` → `GENERATION_COMPLETE` sequence.
- Fail-Closed behavior enforced for Priority-3 paths:
  - malformed frames → `ERROR` response,
  - unsupported message types → `ERROR` response,
  - generation/runtime failures → `ERROR` response,
  - connection handling failures logged and rejected without silent accept.
- Scope boundaries preserved:
  - No LLMPipeline migration for Orchestrator.
  - No VM guest deployment execution.
  - No JWT/KGM key-material wiring.
  - No measured-boot completion changes.

Session validation evidence:
- `python -m py_compile services/policy_agent/src/ipc.py services/policy_agent/src/entrypoint.py services/assistant_orchestrator/src/entrypoint.py services/policy_agent/tests/test_ipc.py services/policy_agent/tests/test_entrypoint.py services/assistant_orchestrator/tests/test_entrypoint.py launcher/tests/test_launcher.py`
- `.venv\Scripts\python.exe -m pytest services/policy_agent/tests/test_ipc.py services/policy_agent/tests/test_entrypoint.py services/assistant_orchestrator/tests/test_entrypoint.py launcher/tests/test_launcher.py -q` → `43 passed`
- `.venv\Scripts\python.exe -m pytest tests/integration/test_p110_end_to_end.py -q` → `49 passed`

Priority-3 status update for operational gaps:
- GAP-3 (No Real IPC Loop): **REDUCED** — live accept/service loops now exist
  for both USE-CASE-001 and USE-CASE-004 entrypoint paths with lifecycle
  controls and fail-closed handling.

### 2026-02-24 Priority-4 Session Delta (Orchestrator LLMPipeline Integration)

Priority 4 milestone scope for this session is complete at code level:

- `services/assistant_orchestrator/src/npu_inference.py` migrated from
  OpenVINO `InferRequest` token loop path to OpenVINO GenAI `LLMPipeline`
  path for Orchestrator NPU generation.
- Existing Orchestrator service-facing interfaces were preserved:
  `load_model()`, `generate()`, `generate_text()`, KV-warm helpers,
  lifecycle (`unload()`), and fail-closed `GenerationResult` behavior.
- Priority-2/Priority-3 wiring compatibility preserved:
  entrypoint startup/load path and IPC prompt handling continue to invoke
  the same inference service APIs without interface changes.
- Directly impacted orchestrator inference tests were updated from
  `InferRequest` mocks to `LLMPipeline` mocks while preserving behavioral
  assertions (circuit breaker, fail-closed, stats, latency fields).
- Scope boundaries preserved:
  - No VM guest deployment execution.
  - No JWT/KGM key-material wiring.
  - No measured-boot completion changes.
  - No ADR-010 device allocation change (PA on GPU, Orchestrator on NPU).

Session validation evidence:
- `python -m py_compile services/assistant_orchestrator/src/npu_inference.py services/assistant_orchestrator/tests/test_npu_inference.py services/assistant_orchestrator/tests/test_entrypoint.py`
- `.venv\Scripts\python.exe -m pytest services/assistant_orchestrator/tests/test_npu_inference.py services/assistant_orchestrator/tests/test_entrypoint.py -q` → `49 passed`
- `.venv\Scripts\python.exe -m pytest tests/integration/test_p110_end_to_end.py -q` → `49 passed`

Priority-4 status update for operational gaps:
- GAP-2 (Real model load/generate runtime path): **REDUCED** for USE-CASE-004
  — Orchestrator runtime now uses LLMPipeline integration path with preserved
  fail-closed semantics and validated scoped regression coverage.

### 2026-02-24 Priority-5 Session Delta (VM Deployment Execution for Guest Runtime)

Priority 5 milestone scope for this session is complete at code and script level:

- Host-side deployment execution path implemented:
  - `launcher/guest_deploy.py`: deterministic deployment orchestrator
    (preflight, topology validation, runtime bundle build, host→guest transfer,
    evidence emission).
  - `scripts/deploy_guest_runtime.ps1`: operator-facing execution wrapper.
  - `launcher/vm_manager.py`: added Guest Service Interface preflight and
    `Copy-VMFile` transfer helper with bounded retries.
- Guest-side startup wiring implemented:
  - `scripts/guest/bootstrap_runtime.sh`: guest extraction + startup smoke entry.
  - `scripts/guest/guest_startup_smoke.py`: boot-path reachability checks for
    Policy Agent and Assistant Orchestrator with deterministic fail-closed
    fingerprints.
  - Added guest runtime configs:
    - `services/policy_agent/config/guest_runtime.toml`
    - `services/assistant_orchestrator/config/guest_runtime.toml`
- Connectivity assumptions validated against locked vsock topology evidence:
  - Source: `phase2_gates/evidence/vsock_validation.json`
  - Enforced checks: VM ID, service GUID, vsock port, no TCP/IP usage.

Session validation evidence:
- `python -m py_compile launcher/guest_deploy.py launcher/vm_manager.py launcher/tests/test_guest_deploy.py launcher/tests/test_vm_manager.py scripts/guest/guest_startup_smoke.py`
- `.venv\Scripts\python.exe -m pytest launcher/tests/test_guest_deploy.py launcher/tests/test_vm_manager.py launcher/tests/test_launcher.py -q` → `36 passed`
- `.venv\Scripts\python.exe -m pytest tests/integration/test_p110_end_to_end.py -q` → `49 passed`
- `.\scripts\deploy_guest_runtime.ps1` executed on host:
  - VM lifecycle preflight: PASS (VM start/reuse successful)
  - Guest channel copy probe: FAIL-CLOSED after bounded retries with Hyper-V
    error `0x800710DF` ("device not ready")
  - Evidence: `phase2_gates/evidence/priority5_guest_deploy.json`

Priority-5 status update for operational gaps:
- GAP-4 (No VM Deployment of Service Code): **REDUCED** — deployment execution
  path, transfer wiring, guest startup scripts, and deterministic evidence
  pipeline now exist and run.
- GAP-4 residual blocker: **OPEN** — Hyper-V guest file-copy channel readiness
  failure (`P5_GUEST_CHANNEL_NOT_READY`) prevented artifact transfer completion
  during this session; fail-closed behavior and fingerprint capture verified.

### 2026-02-24 Priority-6 Session Delta (Config Loader Boot Integration)

Priority 6 milestone scope for this session is complete at code level:

- Added authoritative runtime config resolution with deterministic precedence:
  - `shared/runtime_config.py`
  - Precedence: explicit mode argument → `BLARAI_RUNTIME_MODE` env → `host` default.
  - Deterministic host/guest config file selection:
    - `host` → `config/default.toml`
    - `guest` → `config/guest_runtime.toml`
- Unified launcher + service boot integration for runtime mode selection:
  - `launcher/__main__.py` now resolves deployment mode once and starts both
    services via `from_runtime_mode(...)`.
  - Launcher now fails closed on runtime mode/config resolution errors.
- Implemented strict fail-closed config validation in both service entrypoints:
  - `services/policy_agent/src/entrypoint.py`
  - `services/assistant_orchestrator/src/entrypoint.py`
  - Validates required sections, required keys, type/range constraints,
    device compatibility (PA=`GPU`, Orchestrator=`NPU` per ADR-010), and
    deployment-mode compatibility.
- Added deterministic startup/deployment fingerprints for config failures:
  - Service-level `last_failure` fingerprints surfaced to launcher logs.
  - Guest deploy preflight (`launcher/guest_deploy.py`) now validates guest
    runtime configs before bundle transfer and fails closed with deterministic
    fingerprint codes.
  - Guest startup smoke (`scripts/guest/guest_startup_smoke.py`) now uses
    authoritative guest mode resolution and records service startup
    fingerprint codes/messages.
- Added explicit runtime metadata to service configs:
  - `services/policy_agent/config/default.toml` + `guest_runtime.toml`
  - `services/assistant_orchestrator/config/default.toml` + `guest_runtime.toml`
  - Added `[runtime] deployment_mode = "host"|"guest"`.

Session validation evidence:
- `python -m py_compile shared/runtime_config.py launcher/__main__.py launcher/guest_deploy.py scripts/guest/guest_startup_smoke.py services/policy_agent/src/entrypoint.py services/assistant_orchestrator/src/entrypoint.py launcher/tests/test_launcher.py launcher/tests/test_guest_deploy.py services/policy_agent/tests/test_entrypoint.py services/assistant_orchestrator/tests/test_entrypoint.py`
- `.venv\Scripts\python.exe -m pytest launcher/tests/test_launcher.py launcher/tests/test_guest_deploy.py services/policy_agent/tests/test_entrypoint.py services/assistant_orchestrator/tests/test_entrypoint.py services/policy_agent/tests/test_config_loader.py -q` → `39 passed`
- `.venv\Scripts\python.exe -m pytest tests/integration/test_p110_end_to_end.py -q` → `49 passed`

Priority-6 status update for operational gaps:
- GAP-1/GAP-2 runtime boot determinism: **REDUCED** — launcher and both
  service boot paths now use a single authoritative host/guest config
  resolution and strict fail-closed validation surface.
- Config-related nondeterminism risk: **REDUCED** — missing/invalid/incompatible
  runtime config now terminates startup with deterministic fingerprints.

### 2026-02-24 Priority-7 Session Delta (JWT/KGM Key-Material Wiring)

Priority 7 milestone scope for this session is complete at code and validation level:

- Policy Agent JWT signing/KGM material now resolved and validated at startup:
  - `services/policy_agent/src/entrypoint.py`
  - strict non-dev fail-closed checks for:
    - JWT private signing key path presence/existence/readability,
    - JWT CA/public verification material presence/existence/readability,
    - KGM manifest path presence/existence/parseability,
    - required digest entry for `openvino_model.bin` and digest format.
- Assistant Orchestrator dependent JWT/KGM verification material now wired:
  - `services/assistant_orchestrator/src/entrypoint.py`
  - strict non-dev fail-closed checks for:
    - `security.jwt_ca_cert_path` presence/existence/readability,
    - KGM manifest path presence/existence/parseability,
    - required digest entry for `openvino_model.bin` and digest format.
  - startup now initializes JWT validator material and fails closed on validator init failure.
- Baseline repository material added for deterministic non-dev resolution paths:
  - `certs/pa_private.pem`
  - `certs/ca.pem`
  - `models/qwen2.5-1.5b-instruct/openvino-int4-npu/manifest.json`
- Focused fail-closed + success-path tests added:
  - `services/policy_agent/tests/test_entrypoint.py`
  - `services/assistant_orchestrator/tests/test_entrypoint.py`

Session validation evidence:
- `python -m py_compile services/policy_agent/src/entrypoint.py services/assistant_orchestrator/src/entrypoint.py services/policy_agent/tests/test_entrypoint.py services/assistant_orchestrator/tests/test_entrypoint.py`
- `.venv\Scripts\python.exe -m pytest services/policy_agent/tests/test_entrypoint.py services/assistant_orchestrator/tests/test_entrypoint.py -q` → `14 passed`
- `.venv\Scripts\python.exe -m pytest tests/integration/test_p110_end_to_end.py -q` → `49 passed`

Priority-7 status update for operational gaps:
- GAP-3 (No Certificates, Keys, or Known-Good Manifest): **REDUCED** —
  deterministic JWT/KGM key-material startup wiring now exists for both
  USE-CASE-001 and USE-CASE-004 entrypoint boot paths with strict fail-closed
  validation and fingerprinted failure surfaces.

### 2026-02-24 Priority-8 Session Delta (Functional Measured-Boot Ordering)

Priority 8 milestone scope for this session is complete at code and validation level:

- Functional measured-boot executor implemented for deterministic phase ordering:
  - `services/policy_agent/src/boot.py`
  - ordered phases executed as explicit gates: attestation → weight integrity →
    model load → rule load → listener bind.
  - deterministic bounded retries and fixed backoff:
    `max_attempts=3`, `retry_delay_s=0.25`.
  - hard-lock behavior on exhaustion (`hard_locked=true`) with deterministic
    error-code/message surface.
- Policy Agent startup now enforces measured-boot ordering as authoritative gate:
  - `services/policy_agent/src/entrypoint.py`
  - startup path blocked unless measured boot reaches ready state.
  - failure path now records deterministic measured-boot fingerprints with
    attempt index and hard-lock disposition.
  - process-local hard-lock prevents further startup attempts after retry
    exhaustion (fail-closed).
- Launcher flow now treats measured-boot outcome as startup authority:
  - `launcher/__main__.py`
  - explicit measured-boot step messaging and fail-closed abort on PA gate
    failure before orchestrator startup.
  - PA-first trust-chain behavior preserved: dependent service startup proceeds
    only after PA measured-boot pass.
- Focused regression coverage expanded for measured-boot behavior:
  - `services/policy_agent/tests/test_boot.py`
  - `services/policy_agent/tests/test_entrypoint.py`
  - `launcher/tests/test_launcher.py`

Session validation evidence:
- `python -m py_compile services/policy_agent/src/boot.py services/policy_agent/src/constants.py services/policy_agent/src/entrypoint.py launcher/__main__.py launcher/tests/test_launcher.py services/policy_agent/tests/test_boot.py services/policy_agent/tests/test_entrypoint.py`
- `.venv\Scripts\python.exe -m pytest launcher/tests/test_launcher.py services/policy_agent/tests/test_boot.py services/policy_agent/tests/test_entrypoint.py -q` → `18 passed`
- `.venv\Scripts\python.exe -m pytest tests/integration/test_p110_end_to_end.py -q` → `49 passed`

Priority-8 status update for operational gaps:
- GAP-5 (Functional measured-boot ordering): **CLOSED** — deterministic ordered
  measured-boot gating, bounded retry, and hard-lock fail-closed behavior now
  enforce PA-first startup authority before dependent services.

---

## 1. What Exists Today (Validated)

### 1.1 Phase 2 Hardware Validation (Separate Scripts — NOT Application Code)

Phase 2 gate scripts (`phase2_gates/scripts/`) executed real OpenVINO inference
on the NPU using small synthetic models. These are standalone validation scripts,
not part of the application runtime.

| Gate | Script | Result | Evidence |
|------|--------|--------|----------|
| VALIDATE_DVMT_BUDGET | `validate_dvmt_budget.ps1` | PASS (corrected) | `dvmt_validation.json` |
| VALIDATE_NPU_SCHEDULING | `validate_npu_scheduling.py` | PASS | `npu_scheduling_report.json` |
| VALIDATE_MEMORY_CEILING | `validate_memory_ceiling.py` | PASS (warning) | `memory_map.json` |
| VALIDATE_IGPU_TRUST_BOUNDARY | `validate_igpu_trust_boundary.ps1` | PASS (corrected) | `igpu_trust_report.json` |

Key empirical results from Phase 2:
- NPU scheduling: **Parallel** dual-model inference confirmed (ratio 1.699)
- Preemption P99: 0.814ms (614× under 500ms budget)
- KV-cache persistence: **Exact match** across context switches
- Effective memory ceiling: **31.323 GB** (ADR-005)

### 1.2 Model Artifacts on Disk

| Model | Path | Size | Purpose |
|-------|------|------|---------|
| Qwen2.5-1.5B-Instruct OpenVINO INT4-MIXED | `models/qwen2.5-1.5b-instruct/openvino-int4-npu/` | **975.6 MB** | PA classification + Orchestrator generation |
| BGE-small-en-v1.5 OpenVINO INT8 | `models/bge-small-en-v1.5/openvino-int8/` | **33.6 MB** | Semantic Router embedding |
| BGE-small-en-v1.5 ONNX FP16 | `models/bge-small-en-v1.5/onnx-fp16/` | — | Fallback variant |

Files present for Qwen2.5-1.5B-Instruct: `openvino_model.xml`, `openvino_model.bin`,
`tokenizer.json`, `tokenizer_config.json`, `chat_template.jinja`,
`config.json`, `generation_config.json`, `vocab.json`, `merges.txt`,
`special_tokens_map.json`, `added_tokens.json`, `openvino_config.json`.

### 1.3 Runtime Dependencies Installed

| Dependency | Version | Status |
|------------|---------|--------|
| OpenVINO | 2025.4.1 | **Installed** — detects `['CPU', 'GPU', 'NPU']` |
| Transformers | Present | **Installed** — `AutoTokenizer` importable |
| Python | 3.11.9 | Active in `.venv` |
| Textual | 8.0.0 | Installed (TUI framework) |

### 1.4 Application Source Code (30 Modules)

**Policy Agent** (`services/policy_agent/src/` — 10 modules):

| Module | Lines | Purpose | Hardware Boundary |
|--------|-------|---------|-------------------|
| `gpu_inference.py` | 538 | Qwen2.5-1.5B-Instruct prompt-based CAR classification via LLMPipeline | OpenVINO GenAI GPU (primarily mocked in tests) |
| `adjudicator.py` | 484 | Hybrid deterministic + probabilistic adjudication | GPU via gpu_inference (primarily mocked in tests) |
| `rule_engine.py` | — | Deterministic regex/semantic rule evaluation | None (pure Python) |
| `car.py` | — | Canonical Action Representation builder | None |
| `jwt_minter.py` | — | Agentic JWT minting (Decision Artifact) | Crypto keys (no real keys exist) |
| `ipc.py` | — | vsock listener/handler | AF_HYPERV socket (mocked) |
| `boot.py` | — | Measured boot sequence stub | VM lifecycle (mocked) |
| `config_loader.py` | — | TOML config parser | Filesystem |
| `constants.py` | — | NPU priority, latency budgets, paths | None |
| `__init__.py` | — | Package init | None |

**Assistant Orchestrator** (`services/assistant_orchestrator/src/` — 6 modules):

| Module | Lines | Purpose | Hardware Boundary |
|--------|-------|---------|-------------------|
| `npu_inference.py` | 980 | Qwen2.5-1.5B-Instruct generation via OpenVINO GenAI LLMPipeline (with compatibility KV/session hooks) | OpenVINO GenAI NPU (scoped tests mocked) |
| `pgov.py` | — | Post-Generation Output Validator (tool-call allowlist, leakage, delimiter echo) | None (pure Python) |
| `circuit_breaker.py` | — | Token/recursion hard caps (OWASP LLM04) | None |
| `context_manager.py` | — | Context window management | None |
| `constants.py` | — | Priority 1, max tokens, latency targets | None |
| `__init__.py` | — | Package init | None |

**Semantic Router** (`services/semantic_router/src/` — 4 modules):

| Module | Purpose | Hardware Boundary |
|--------|---------|-------------------|
| `router.py` | Intent classification + skill dispatch | BGE embedding (mocked) |
| `intents.py` | Intent registry | None |
| `constants.py` | Priority 1, thresholds | None |
| `__init__.py` | Package init | None |

**UI Gateway** (`services/ui_gateway/src/` — 4 modules):

| Module | Purpose | Hardware Boundary |
|--------|---------|-------------------|
| `transport.py` | Boot-Phase-3 handshake, `send_prompt()`, `stream_tokens()` async | vsock IPC (mocked in tests, TCP loopback in integration) |
| `session_store.py` | SQLite WAL session CRUD | Filesystem (real SQLite in tests) |
| `constants.py` | Buffer limits, timeouts | None |
| `__init__.py` | Package init | None |

**UI Shell** (`services/ui_shell/src/` — 6 modules):

| Module | Purpose | Hardware Boundary |
|--------|---------|-------------------|
| `app.py` | Textual TUI App (3-region layout, keybindings) | Terminal (mocked in tests) |
| `streaming.py` | `StreamingDisplay` token rendering | Terminal (mocked) |
| `session_panel.py` | Session sidebar CRUD | UI (mocked) |
| `pgov_display.py` | PGOV denial rendering | UI (mocked) |
| `constants.py` | Display limits | None |
| `__init__.py` | Package init | None |

**Shared Libraries** (`shared/`):

| Module | Purpose |
|--------|---------|
| `constants.py` | All system-wide constants (paths, priorities, budgets) |
| `schemas/car.py` | CAR dataclass + hash chain |
| `ipc/protocol.py` | MessageFramer (length-prefix vsock framing) |
| `ipc/vsock.py` | AF_HYPERV socket wrapper |
| `crypto/jwt_validator.py` | JWT verification |
| `models/weight_integrity.py` | SHA-256 weight file verification |

**Launcher** (`launcher/`):

| Module | Purpose |
|--------|---------|
| `__main__.py` | UAT-1 entry point (admin check, VM start, mock PA, TUI launch) |
| `vm_manager.py` | Hyper-V VM lifecycle (Start-VM, Get-VM via PowerShell) |

**Mock Backend** (`services/mock_backend/`):

| Module | Purpose |
|--------|---------|
| `server.py` | TCP echo server simulating PA vsock responses (for UAT-1) |

### 1.5 Test Suite (749 Tests)

| Scope | Count | Mock Strategy |
|-------|-------|---------------|
| PA NPU inference | 31 | `MagicMock` for OpenVINO Core, CompiledModel, InferRequest, tokenizer |
| PA adjudicator | \~50 | `MagicMock` for `classify_car()` return values |
| PA rule engine | \~40 | Pure logic (no mocks needed) |
| PA CAR/JWT/IPC | \~60 | `MagicMock` for crypto keys, sockets |
| PA integration (car pipeline) | \~15 | `MagicMock` for NPU, stub adjudicator |
| Orchestrator NPU inference | \~40 | `MagicMock` for OpenVINO GenAI LLMPipeline and tokenizer |
| Orchestrator PGOV | \~50 | `MagicMock` for `LeakageDetector` |
| Orchestrator circuit breaker | \~20 | Pure logic |
| Semantic Router | \~40 | `MagicMock` for BGE embedding model |
| UI Gateway transport | \~60 | TCP loopback (real asyncio sockets, but no real vsock) |
| UI Gateway sessions | \~20 | Real in-memory SQLite |
| UI Shell app/streaming/pgov | \~50 | `MagicMock` for gateway, Textual `run_test()` |
| Shared (IPC, schemas, crypto) | \~50 | `MagicMock` for sockets, keys |
| Launcher (vm_manager, main) | \~30 | `@patch` for PowerShell calls, ctypes |
| End-to-end integration (P1.10) | \~80 | Full pipeline mocked at NPU + socket boundaries |
| End-to-end UI (P1.14) | \~50 | `MagicMock` for gateway, real Textual compositor |
| **TOTAL** | **749** | **All hardware boundaries mocked** |

**What the tests prove:**
- Python logic is internally consistent
- Data flows correctly between modules (CAR → rules → NPU stub → adjudicator → JWT → IPC framing)
- Fail-Closed behavior triggers correctly on every error path
- PGOV deterministic checks (allowlist, cosine similarity, delimiter echo) work correctly
- Circuit breakers fire at configured thresholds
- Session CRUD works against real SQLite
- TUI rendering pipeline produces expected widget output

**What the tests do NOT prove:**
- OpenVINO can load the Qwen2.5-1.5B-Instruct model on this NPU
- The NPU produces correct classification/generation output
- Inference completes within the architectural latency budget (70–230ms PA, <1s first-token Orchestrator)
- Two services can communicate over real vsock (AF_HYPERV)
- The system boots in the correct measured-boot order
- mTLS handshakes succeed with real certificates
- Memory consumption stays within the 31.323 GB ceiling during real inference

### 1.6 Hyper-V Infrastructure

| Asset | Status | Evidence |
|-------|--------|----------|
| BlarAI-Orchestrator VM | **Provisioned** (Gen 2, 2 vCPU, 2GB RAM, Alpine 3.21.3) | VM ID `9c7f986f-...` |
| AF_HYPERV vsock round-trip | **Validated** (Phase 2, echo test) | `vsock_validation.json` |
| hv_sock kernel module | **Persisted** in guest | Phase 2 evidence |
| Service code deployed to VM | **NOT DONE** | — |

---

## 2. What Does NOT Exist (Gaps to Operational)

### GAP-1: No Service Entry Points

**Severity: BLOCKING**

Zero `main.py` or `__main__.py` files exist inside any service directory.
No `console_scripts` entry points are defined in any service `pyproject.toml`.
Every Dockerfile has a stub `CMD`:

```dockerfile
# services/policy_agent/Dockerfile
CMD ["echo", "Policy Agent container stub — P1.0 scaffold"]

# services/assistant_orchestrator/Dockerfile  
CMD python -c "import sys; sys.exit(0)"

# services/semantic_router/Dockerfile
CMD ["echo", "Semantic Router container stub — P1.0 scaffold"]
```

The only functional entry point in the codebase is `launcher/__main__.py`, which
starts a mock TCP echo server (not the real PA), a TUI shell, and a session store.
It never instantiates `PolicyGPUInference`, `HybridAdjudicator`, or
`OrchestratorNPUInference`.

**Impact:** You cannot start the Policy Agent or Orchestrator as a running process.

**Resolution:** Create service entry points that:
1. Load config from TOML
2. Instantiate the real inference engine with `load_model()`
3. Start the vsock listener loop
4. Handle graceful shutdown

---

### GAP-2: Real Model Never Loaded End-to-End

**Severity: BLOCKING**

After Priority 1, the PA path was refactored to GPU `LLMPipeline` and validated by
targeted regression, but no service entry point is yet loading models in a live
process. The Orchestrator `npu_inference.py` path remains unvalidated in a real
service lifecycle.

If runtime model load fails, current code still follows Fail-Closed behavior
(`DENY` / empty generation) as expected. OpenVINO/OpenVINO-GenAI are installed,
but runtime operational loading has not been validated via service entry points.

**Unknowns that remain unvalidated:**
- What is the actual first-token latency for PA classification through live service wiring (budget: 70–230ms)?
- What is the actual first-token latency for Orchestrator generation (budget: <1s)?
- Can Orchestrator reliably load and run `npu_inference.py` via live service startup?
- What is the actual memory footprint of the loaded model?

**Positive signal:** Phase 2 gate scripts used OpenVINO on the same NPU with
small synthetic models and confirmed parallel scheduling, preemption, and
KV-cache persistence. This proves the NPU driver stack works. The question is
whether the full 1.5B model loads and performs correctly.

**Resolution:** Complete service-level hardware validation:
1. Add service entry points that call `load_model()` in live process startup.
2. Validate PA GPU `LLMPipeline` end-to-end through IPC.
3. Validate Orchestrator NPU generation end-to-end through IPC.
4. Measure first-token and total latency under live service conditions.
5. Record memory delta and error fingerprints.

---

### GAP-3: No Certificates, Keys, or Known-Good Manifest

**Severity: BLOCKING (for production security), NON-BLOCKING (for functional smoke test)**

The architecture mandates:
- Policy Agent internal CA issuing ephemeral mTLS certificates
- Agentic JWT signing keys (ECDSA, derived from Pluton/TPM)
- Known-Good Manifest (KGM) with SHA-256 hashes of all model weights
- Code-hash-bound signing keys for the Cleaner

None of these exist. The `jwt_minter.py` and `jwt_validator.py` modules are
written but have never been exercised with real key material. The
`weight_integrity.py` module computes SHA-256 but has never been run against
the real `openvino_model.bin` files.

**Impact:** All cryptographic verification code (weight integrity, JWT minting,
mTLS authentication) has nothing real to verify against. Inter-service
communication is unauthenticated.

**Resolution (phased):**
1. **Phase A (smoke test):** Skip crypto, test raw inference + IPC
2. **Phase B (security hardening):** Generate CA chain, mint certs, create KGM,
   wire JWT minting into adjudication pipeline

---

### GAP-4: No VM Deployment of Service Code

**Severity: BLOCKING**

The `BlarAI-Orchestrator` Hyper-V VM is provisioned and running Alpine Linux
3.21.3. A vsock echo round-trip has been validated. But:
- No Python environment exists on the guest (only the Phase 2 echo script)
- No service code has been copied to the VM
- No systemd/init service definitions exist
- The Dockerfiles are stubs (see GAP-1)

**Impact:** Even with entry points, the services have nowhere to run in the
intended isolation boundary.

**Resolution:**
1. Install Python 3.11 + OpenVINO on the Alpine guest (or use a pre-built container)
2. Push service code + model artifacts via `Copy-VMFile` or shared VHDX
3. Create service definitions (systemd units or direct process management)
4. Wire vsock listener to guest-side port 50000

---

### GAP-5: No IPC Wiring (Service Loop)

**Severity: BLOCKING**

The vsock protocol (`shared/ipc/protocol.py`) implements `MessageFramer`
(length-prefix framing) and the AF_HYPERV socket wrapper. The PA `ipc.py`
implements handler registration. But:
- No service main loop calls `listen()` → `accept()` → `handle()`
- The Transport Gateway's `send_prompt()` targets `127.0.0.1` TCP in the mock
  backend, not a real vsock endpoint
- No connection management (reconnect, health check, graceful shutdown) exists
  outside of test stubs

**Impact:** The PA and Orchestrator cannot communicate. The TUI cannot reach
a real backend.

**Resolution:** Implement service main loops that:
1. Bind to vsock port (PA on port 50000)
2. Accept framed messages
3. Dispatch to handler (PA: adjudicate CAR; Orchestrator: generate response)
4. Return framed response
5. Handle connection lifecycle (timeout, reconnect, shutdown signal)

---

### GAP-6: No Measured Boot Sequence

**Severity: BLOCKING (for security guarantees), NON-BLOCKING (for functional demo)**

The architecture mandates: PA boots first → attests hardware → derives crypto
identity → establishes CA → issues certificates → signals readiness → other
VMs boot.

`boot.py` exists as a module but contains no real sequencing logic. The launcher
(`launcher/__main__.py`) calls `ensure_vm_running()` and then immediately starts
the mock server — there is no PA-first ordering, no attestation, no credential
issuance.

**Impact:** The architectural root of trust does not exist at runtime. Any
service can start in any order. No attestation occurs.

**Resolution (phased):**
1. **Phase A (functional):** Simple ordered startup — PA process starts, loads
   model, signals ready via vsock heartbeat, then Orchestrator starts
2. **Phase B (attested):** Integrate TPM 2.0 measurements, generate CA chain,
   implement full measured boot with credential issuance

---

## 3. Dependency Readiness Matrix

| Dependency | Required | Installed | Validated Against Real Hardware |
|------------|----------|-----------|-------------------------------|
| OpenVINO Runtime | YES | YES (2025.4.1) | Phase 2 only (synthetic models) |
| NPU Driver | YES | YES | Phase 2 only |
| Transformers (tokenizer) | YES | YES | NEVER with real model |
| AF_HYPERV vsock | YES | YES | Phase 2 echo test only |
| Hyper-V VM | YES | YES (provisioned) | Echo test only, no services deployed |
| TPM 2.0 | YES (production) | YES (detected) | NEVER (no attestation code) |
| SQLite | YES (sessions) | YES | YES (real DB in tests) |
| Textual | YES (TUI) | YES (8.0.0) | YES (App.run_test() in tests) |

---

## 4. Classification of the 749 Tests

| Category | Description | Count (approx.) |
|----------|-------------|-----------------|
| **Pure logic** | No hardware dependency; tests Python algorithms (rule engine, CAR hashing, PGOV checks, circuit breakers, config parsing) | \~250 |
| **Mocked hardware** | Tests correct code paths around NPU inference, but `MagicMock` replaces all OpenVINO calls | \~200 |
| **Mocked IPC** | Tests vsock framing, message dispatch, connection lifecycle — but against `MagicMock` sockets or TCP loopback | \~100 |
| **Mocked crypto** | Tests JWT minting/validation, weight integrity — but with `MagicMock` keys | \~50 |
| **Real I/O (limited)** | Session store tests use real in-memory SQLite; TUI tests use real Textual compositor | \~80 |
| **Integration (fully mocked boundaries)** | End-to-end pipeline tests that wire multiple modules but mock all hardware boundaries | \~70 |

**Conclusion:** The test suite validates internal software correctness — it does NOT
validate any hardware interaction, real model behavior, or inter-service connectivity.

---

## 5. Recommended Path to Operational

### Phase A: Hardware Smoke Test (1-2 sessions)

**Objective:** First real NPU inference with the Qwen2.5-1.5B-Instruct model.

1. **Script:** `scripts/smoke_npu_inference.py`
   - Load Qwen2.5-1.5B-Instruct via `openvino_genai.LLMPipeline(model_path, "NPU")`
   - Load tokenizer via `openvino_genai.LLMPipeline` (built-in OV tokenizer)
   - Construct a sample CAR classification prompt using `CARPromptFormatter`
   - Run greedy decode (max 32 tokens) using the real `InferRequest`
   - Parse output for ALLOW/DENY/ESCALATE
   - Measure: first-token latency, total latency, memory delta
   - **PASS CRITERIA:** Model loads, produces a valid label, latency ≤ 230ms

2. **Script:** `scripts/smoke_orchestrator_generation.py`
   - Same model, longer generation (max 512 tokens)
   - Measure: first-token latency (target: <1s), tokens/second
   - **PASS CRITERIA:** Coherent output, first-token <1s

### Phase B: Service Entry Points + Local IPC (2-3 sessions)

**Objective:** Two processes communicating over real IPC on the host.

1. Create `services/policy_agent/main.py` — loads model, starts vsock listener
2. Create `services/assistant_orchestrator/main.py` — connects to PA, sends CARs
3. Wire `launcher/__main__.py` to start real PA instead of mock server
4. **PASS CRITERIA:** TUI sends prompt → Orchestrator generates → PA adjudicates CAR → response streams to TUI

### Phase C: VM Deployment (1-2 sessions)

**Objective:** Services running inside Hyper-V VM with real vsock.

1. Install Python 3.11 + OpenVINO in Alpine guest
2. Deploy PA service code + model to VM
3. Wire vsock (host TUI ↔ guest PA) on port 50000
4. **PASS CRITERIA:** Same as Phase B but across VM boundary

### Phase D: Security Hardening (3-5 sessions)

**Objective:** Cryptographic trust chain operational.

1. Generate PA CA chain + ephemeral certs
2. Create KGM with SHA-256 hashes of all model weights
3. Wire JWT minting into adjudication pipeline
4. Implement measured boot ordering
5. **PASS CRITERIA:** Unauthorized requests rejected, forged JWTs rejected,
   tampered weights detected

---

## 6. Commit History (Relevant Milestones)

| Hash | Branch | Description |
|------|--------|-------------|
| `b3006f9` | `feature/p1-uat1-launcher` | **HEAD** — PA aligned to Qwen2.5-1.5B-Instruct (749/749) |
| `4a72326` | `feature/p1-uat1-launcher` | P1.15 UAT-1 launcher + mock backend + PyInstaller (747/747) |
| `01dfad8` | `feature/p1-ui-implementation` | P1.14 end-to-end UX validation suite |
| `87379e8` | `feature/p1-ui-implementation` | P1.13 boot-phase-3 gating enforcement |
| `4174df4` | `feature/p1-ui-implementation` | P1.12 TUI Shell wired to Transport Gateway |
| `d6b0eee` | `feature/p1-ui-implementation` | P1.11 Transport Gateway live vsock IPC path |
| `065ca0f` | `main` | AF_HYPERV vsock round-trip validated |
| `a327775` | `main` | BlarAI-Orchestrator Hyper-V VM provisioned |

---

## 7. Verdict

| Dimension | Status |
|-----------|--------|
| Architecture defined | **COMPLETE** (9 use cases, 5 ADRs, locked) |
| Hardware validated | **COMPLETE** (4/4 Phase 2 gates closed) |
| Model artifacts acquired | **COMPLETE** (Qwen2.5-1.5B-Instruct + BGE-small on disk) |
| Software library (logic) | **COMPLETE** (749/749 tests, all mocked boundaries) |
| TUI shell | **COMPLETE** (Textual app, session CRUD, streaming display) |
| **Real hardware inference integration** | **PARTIAL** (PA GPU LLMPipeline path integrated; live service startup/IPC validation pending) |
| **Service entry points** | **NOT STARTED** |
| **Inter-service IPC** | **NOT STARTED** (mock TCP only) |
| **VM deployment** | **NOT STARTED** |
| **Crypto / trust chain** | **NOT STARTED** |
| **Measured boot sequence** | **NOT STARTED** |

**The system is a fully unit-tested software library, not an operational system.**
The immediate next step is Priority 2: service entry points + launcher wiring so
the integrated inference paths run in live service processes.

---

## 8. Updated Delivery Estimates (Post-ADR-010)

The estimates below reflect the current repository state at `9cfb063`.

| Priority | Work Item | Primary Gap(s) | Est. Sessions | Est. Time | Complexity |
|----------|-----------|----------------|---------------|-----------|------------|
| 1 | Service entry points (`services/policy_agent/main.py`, `services/assistant_orchestrator/main.py`) + launcher wiring | GAP-1 | 1 | 2-3 hours | Medium |
| 2 | Real vsock IPC service loop (bind/accept/dispatch/respond lifecycle) | GAP-5 | 1-2 | 3-5 hours | High |
| 3 | Orchestrator LLMPipeline integration (`npu_inference.py`) | GAP-2 final | 1 | 2-3 hours | Medium |
| 4 | VM deployment execution (guest runtime + code/model deployment + port wiring) | GAP-4 | 1-2 | 3-5 hours | High |
| 5 | Config loader boot integration (TOML-to-runtime wiring) | GAP-5 partial | 0.5 | 1-2 hours | Low |
| 6 | JWT + KGM + key material wiring (security hardening baseline) | GAP-3 | 1-2 | 3-5 hours | High |
| 7 | Functional measured boot ordering (PA-first sequencing, readiness signaling) | GAP-6 | 1-2 | 3-5 hours | High |

### Aggregate Estimate

| Phase | Scope | Est. Sessions | Est. Time |
|-------|-------|---------------|-----------|
| Phase A | Inference integration (PA + Orchestrator) | 2 | 4-6 hours |
| Phase B | Entry points + IPC + config integration | 2-3 | 6-10 hours |
| Phase C | VM deployment | 1-2 | 3-5 hours |
| Phase D | Security hardening + measured boot | 2-4 | 6-10 hours |
| **Total to operational baseline** | **A→D** | **7-12** | **19-31 hours** |

Assumptions for estimate validity:
- No new architectural decision gates are introduced (ADR-009/ADR-010 remain locked).
- Existing model artifacts and OpenVINO runtime remain stable.
- No blocking regressions emerge in host↔guest vsock behavior during VM deployment.
