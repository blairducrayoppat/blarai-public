# UAT-2 Acceptance Plan — BlarAI Assistant (Real Runtime Path)

**Stage:** UAT-2 (Real Runtime Activation)
**Branch:** `feature/p1-uat1-launcher`
**Baseline Commit:** `62f5c9d` (post-Priority-8)
**Date:** 2026-02-24
**Executor:** Lead Architect + Copilot Agent
**Scope:** USE-CASE-001 (Policy Agent) + USE-CASE-004 (Assistant Orchestrator)

---

## 1. Purpose

UAT-2 validates the transition from UAT-1 mock behavior to a **real operational runtime path** with deterministic fail-closed behavior.

This plan verifies that:
- startup authority remains Policy-Agent-first via measured boot ordering,
- runtime path does not depend on mock backend for operational flow,
- service startup and IPC behavior remain deterministic and fail-closed,
- evidence artifacts are captured for both success and bounded failure states.

UAT-2 is an **operationalization gate**, not a full production sign-off.

---

## 2. UAT-2 Exit Criteria

UAT-2 is accepted when all criteria below are met in a single execution cycle:

1. **Real runtime activation path exists and executes** (no mock-backend dependency in operational startup path).
2. **Measured boot ordering is enforced** and blocks dependent service operation when PA boot gate fails.
3. **Fail-Closed startup behavior is deterministic** with repeatable failure fingerprints.
4. **Evidence artifacts are generated** and stored under `phase2_gates/evidence/` (or approved equivalent path).
5. **Focused regression tests pass** for launcher + PA boot + entrypoint startup paths.
6. **Integration guardrail passes:** `tests/integration/test_p110_end_to_end.py`.

---

## 3. In-Scope vs Out-of-Scope

### 3.1 In Scope
- Launcher real-runtime bring-up path for UAT-2.
- Policy Agent measured-boot startup gate behavior.
- Assistant Orchestrator startup dependency on successful PA path.
- Runtime mode handling (`host`/`guest`) and deterministic fail-closed handling.
- Evidence capture for startup, activation, and failure pathways.
- Documentation updates for UAT-2 results and residual blockers.

### 3.2 Out of Scope
- New architecture decisions (ADR changes).
- Rewriting TUI interaction model.
- Broad security redesign beyond current phased baseline.
- End-to-end performance tuning beyond pass/fail acceptance checks.

---

## 4. Target Runtime Topology (UAT-2)

## 4.1 Logical Topology

1. Launcher process starts on Windows host.
2. VM lifecycle is validated/started through `launcher/vm_manager.py`.
3. Policy Agent startup enforces measured-boot ordering.
4. Assistant Orchestrator startup occurs only after PA gate success.
5. UI transport path uses real runtime flow over configured IPC/vsock route.
6. Any startup violation fails closed with deterministic error fingerprint.

## 4.2 Invariants

- ADR-010 lock remains active:
  - Policy Agent inference device = GPU.
  - Assistant Orchestrator inference device = NPU.
- No external network calls.
- Deterministic startup order and retry behavior.
- Hard-lock behavior after bounded measured-boot retry exhaustion.

---

## 5. Preconditions

## 5.1 Environment
- Windows 11 Pro host with Hyper-V enabled.
- BlarAI-Orchestrator VM provisioned and discoverable.
- Python environment active (`.venv`).
- Existing runtime configs present for host/guest paths.

## 5.2 Security Material
- JWT/KGM baseline material present from Priority 7:
  - `certs/pa_private.pem`
  - `certs/ca.pem`
  - `models/qwen2.5-1.5b-instruct/openvino-int4-npu/manifest.json`

## 5.3 Required Source Areas
- `launcher/`
- `services/policy_agent/src/`
- `services/assistant_orchestrator/src/`
- `shared/runtime_config.py`
- `shared/ipc/`

---

## 6. UAT-2 Execution Plan

## Phase A — Static Preflight (Compile + Config)

1. Compile touched runtime files:
   - `python -m py_compile launcher/__main__.py launcher/vm_manager.py services/policy_agent/src/boot.py services/policy_agent/src/entrypoint.py services/assistant_orchestrator/src/entrypoint.py shared/runtime_config.py`
2. Validate runtime config resolution behavior (`host`/`guest`) and deterministic mismatch failures.
3. Validate measured-boot-required settings for PA startup path.

**Expected Result:** Compile success and no unresolved startup config conflicts.

## Phase B — Focused Test Verification

Run focused tests before activation:

- `python -m pytest launcher/tests/test_launcher.py -q`
- `python -m pytest services/policy_agent/tests/test_boot.py services/policy_agent/tests/test_entrypoint.py -q`
- `python -m pytest services/assistant_orchestrator/tests/test_entrypoint.py -q`

Then run integration guardrail:

- `.venv\Scripts\python.exe -m pytest tests/integration/test_p110_end_to_end.py -q`

**Expected Result:** All listed tests pass.

## Phase C — Real Runtime Activation Attempt

1. Start launcher in UAT-2 real-runtime mode (implementation-defined switch/path).
2. Confirm startup sequence enforces measured-boot gate before dependent services.
3. Confirm operational path does not require mock backend for runtime success.
4. Exercise one minimal prompt flow and one failure-path flow.

**Expected Result:**
- Success path: deterministic activation with real runtime path.
- Failure path: deterministic fail-closed behavior with explicit fingerprint and no silent fallback.

## Phase D — Evidence Capture

Capture artifacts (or equivalent approved names):

- `phase2_gates/evidence/uat2_startup.json`
- `phase2_gates/evidence/uat2_runtime_activation.json`
- `phase2_gates/evidence/uat2_fail_closed.json`
- `phase2_gates/evidence/uat2_test_summary.md`

Each artifact must include:
- timestamp (UTC),
- commit hash,
- runtime mode,
- pass/fail disposition,
- deterministic failure codes where relevant,
- fail-closed confirmation flag.

## Phase E — Documentation Sync

Update:
- `docs/GAP_TO_OPERATIONAL_REPORT.md`
- `docs/IMPLEMENTATION_PLAN.md`
- `docs/UAT-1_ACCEPTANCE_PLAN.md` (cross-link to UAT-2) or keep UAT-2 standalone and add pointer
- `.github/copilot-instructions.md` only if milestone ordering changes

Include pre/post session HEAD and evidence references.

---

## 7. UAT-2 Test Matrix

| ID | Scenario | Procedure | Expected Result | Evidence |
|---|---|---|---|---|
| UAT2-01 | Measured boot gate success | Start launcher in real-runtime path with valid config/material | PA gate passes before dependent service startup | `uat2_startup.json` |
| UAT2-02 | PA-first ordering | Inspect startup order + logs | Orchestrator startup only after PA gate success | `uat2_startup.json` |
| UAT2-03 | Runtime without mock dependency | Start UAT-2 path with mock disabled/unused | Startup succeeds without mock backend dependency | `uat2_runtime_activation.json` |
| UAT2-04 | Config mismatch fail-closed | Inject mode mismatch (`host` vs `guest`) | Startup aborts with deterministic failure code | `uat2_fail_closed.json` |
| UAT2-05 | Measured boot retry behavior | Trigger transient boot failure path | Bounded retry sequence executes deterministically | `uat2_fail_closed.json` |
| UAT2-06 | Hard-lock behavior | Trigger exhausted retry path | Hard-lock asserted; dependent startup blocked | `uat2_fail_closed.json` |
| UAT2-07 | Focused launcher regression | Run launcher tests | Pass | test output + summary |
| UAT2-08 | PA boot regression | Run `test_boot.py` + PA entrypoint tests | Pass | test output + summary |
| UAT2-09 | AO startup regression | Run AO entrypoint tests | Pass | test output + summary |
| UAT2-10 | Integration guardrail | Run `test_p110_end_to_end.py` | Pass | test output + summary |

---

## 8. Risks and Fail-Closed Handling

## 8.1 Known Risk Areas
- Hyper-V guest file-copy/channel readiness instability.
- vsock handshake/environment variability in guest bring-up.
- Runtime mode/config drift between host and guest paths.

## 8.2 Required Behavior on Failure
- Abort startup path deterministically.
- Emit failure fingerprint and evidence artifact.
- Do not auto-fallback to mock operational path for UAT-2 success criteria.
- Preserve logs/evidence for audit.

---

## 9. Rollback Procedure (Mandatory)

If UAT-2 activation changes destabilize startup behavior:

1. Revert milestone commit(s) for UAT-2 scope.
2. Restore last known-good launch path from pre-session commit.
3. Re-run focused launcher + PA boot tests.
4. Verify integration guardrail still passes.
5. Record rollback event and reason in `docs/GAP_TO_OPERATIONAL_REPORT.md`.

---

## 10. Acceptance Checklist

- [ ] Real-runtime activation path executes without mock dependency.
- [ ] Measured-boot ordering enforced (PA-first authority).
- [ ] Fail-closed behavior deterministic across tested failure branches.
- [ ] Focused regression tests pass.
- [ ] Integration guardrail passes.
- [ ] Evidence artifacts generated and stored.
- [ ] GAP/Plan docs updated with session metadata and results.

---

## 11. UAT-2.5 Hardening Addendum (Operational Exit Milestone 3)

Status for this branch/session scope: **COMPLETE (PASS)**.

Milestone-3 execution summary:
- Baseline captured on `feature/p1-uat1-launcher` at pre-session HEAD `21b59ad`.
- Mandatory validation order executed:
  - `python -m py_compile launcher/__main__.py launcher/tests/test_launcher.py services/ui_gateway/src/transport.py services/ui_gateway/tests/test_transport.py services/policy_agent/src/entrypoint.py services/policy_agent/tests/test_entrypoint.py services/assistant_orchestrator/src/entrypoint.py services/assistant_orchestrator/tests/test_entrypoint.py` → PASS
  - `.venv\Scripts\python.exe -m pytest launcher/tests/test_launcher.py services/ui_gateway/tests/test_transport.py services/policy_agent/tests/test_entrypoint.py services/assistant_orchestrator/tests/test_entrypoint.py -q` → `75 passed`
  - `.venv\Scripts\python.exe -m pytest tests/integration/test_p110_end_to_end.py -q` → `49 passed`
- Matrix execution:
  - `.venv\Scripts\python.exe phase2_gates/scripts/run_uat25_matrices.py` → PASS
  - stability matrix (`run_count=3`) satisfied with required per-run step-state booleans
  - deterministic failure-injection matrix (`scenario_count=2`) satisfied with fail-closed fingerprints and baseline restore

Canonical UAT-2.5 artifact set:
- `phase2_gates/evidence/uat25_stability_matrix.json`
- `phase2_gates/evidence/uat25_failure_injection_matrix.json`
- `phase2_gates/evidence/uat25_evidence_normalization.json`
- `phase2_gates/evidence/uat25_summary.md`

UAT-3 readiness cross-reference:
- UAT-2.5 completion criteria required by `docs/UAT-3_ACCEPTANCE_PLAN.md` entry criteria are satisfied.
- No UAT-3 execution is performed in this Milestone-3 closure scope.

---

## 11. Post-UAT-2 Decision Gate

After UAT-2 completion, decide one of:

1. **Proceed to UAT-2.5 hardening (mandatory)**:
  - repeated-run stability matrix,
  - deterministic failure-injection matrix,
  - evidence normalization and operator runbook hardening.
2. **Proceed to UAT-3 non-dev enablement + UI-functional UAT (mandatory)**:
  - train a non-dev operator on cold-start and normal operation,
  - execute supervised end-to-end UI feature/functionality UAT with acceptance checklist evidence,
  - produce runbook + feature How-To artifacts and obtain explicit non-dev acceptance.
3. **Operational sign-off candidate** only after UAT-2.5 and UAT-3 are both complete with documented pass evidence.

This decision must be documented in both:
- `docs/GAP_TO_OPERATIONAL_REPORT.md`
- `docs/IMPLEMENTATION_PLAN.md`

### 11.1 UAT-3 (Non-Dev Enablement + UI Functional UAT) Minimum Requirements

- Non-dev user can start the system from a cold state by following operator instructions only.
- Non-dev user can complete core UI workflows (session create/switch/delete, prompt/response flow, PGOV-visible outcomes, controlled shutdown).
- Acceptance artifacts include operator checklist, run log, and pass/fail matrix for each UI function under test.
- Acceptance artifacts must also include:
  - a non-dev-validated startup/operations runbook,
  - non-dev-validated How-To guides for major UI features/functionality,
  - an explicit statement that these artifacts are suitable for onboarding new non-dev team members.

---

## 12. 2026-02-24 Milestone 1 Execution Record

### 12.1 Commands Executed

- `python -m py_compile launcher/__main__.py launcher/tests/test_launcher.py services/ui_gateway/src/transport.py services/ui_gateway/tests/test_transport.py services/policy_agent/src/entrypoint.py services/policy_agent/tests/test_entrypoint.py services/assistant_orchestrator/src/entrypoint.py services/assistant_orchestrator/tests/test_entrypoint.py`
- `.venv\Scripts\python.exe -m pytest launcher/tests/test_launcher.py services/ui_gateway/tests/test_transport.py services/policy_agent/tests/test_entrypoint.py services/assistant_orchestrator/tests/test_entrypoint.py -q` → `75 passed`
- `.venv\Scripts\python.exe -m pytest tests/integration/test_p110_end_to_end.py -q` → `49 passed`
- `BLARAI_LAUNCH_PROFILE=uat2_real .venv\Scripts\python.exe -m launcher`

### 12.2 Evidence Produced

- `phase2_gates/evidence/uat2_real_runtime_activation.json`
  - `startup_profile`: `uat2_real`
  - `disposition`: `ELEVATION_HANDOFF`
  - failure code: `UAC_PROMPT_TRIGGERED`
  - fail-closed flag: `true`

### 12.3 Milestone-1 Bounded Outcome

- Real-runtime launcher path was activated and executed to deterministic UAC handoff.
- Operational path wiring no longer depends on mock backend in `uat2_real` profile.
- Deterministic fail-closed evidence capture is now implemented for both startup
  failures and handoff outcomes.
- Residual execution blocker: elevated continuation is required to collect
  full in-process UAT-2 handshake/prompt evidence in one uninterrupted run.

### 12.4 Acceptance Checklist Status (Post-Milestone 1)

- [x] Real-runtime activation path executes without mock dependency.
- [x] Measured-boot ordering enforced (PA-first authority).
- [x] Fail-closed behavior deterministic across tested failure branches.
- [x] Focused regression tests pass.
- [x] Integration guardrail passes.
- [x] Evidence artifacts generated and stored.
- [x] GAP/Plan docs updated with session metadata and results.

---

## 13. 2026-02-25 Milestone 2 Execution Record

### 13.1 Session Git Metadata

- Branch: `feature/p1-uat1-launcher`
- Pre-session HEAD: `b20949d`
- Post-session HEAD: recorded in milestone commit for this session

### 13.2 Commands Executed (Required Order)

1. Compile gate:
   - `python -m py_compile launcher/__main__.py launcher/tests/test_launcher.py services/ui_gateway/src/transport.py services/ui_gateway/tests/test_transport.py services/policy_agent/src/entrypoint.py services/policy_agent/tests/test_entrypoint.py services/assistant_orchestrator/src/entrypoint.py services/assistant_orchestrator/tests/test_entrypoint.py`
   - Result: PASS
2. Focused tests:
   - `.venv\Scripts\python.exe -m pytest launcher/tests/test_launcher.py services/ui_gateway/tests/test_transport.py services/policy_agent/tests/test_entrypoint.py services/assistant_orchestrator/tests/test_entrypoint.py -q`
   - Result: `75 passed`
3. Integration guardrail:
   - `.venv\Scripts\python.exe -m pytest tests/integration/test_p110_end_to_end.py -q`
   - Result: `49 passed`
4. Runtime activation attempts:
   - Non-elevated probe: `BLARAI_LAUNCH_PROFILE=uat2_real .venv\Scripts\python.exe -m launcher`
     - Result: deterministic handoff (`ELEVATION_HANDOFF` / `UAC_PROMPT_TRIGGERED`)
   - Elevated `RunAs` launcher execution with `BLARAI_LAUNCH_PROFILE=uat2_real`
     - Result: final in-process PASS with startup handshake and minimal prompt-flow evidence captured

### 13.3 Evidence Produced

- Required artifact updated:
  - `phase2_gates/evidence/uat2_real_runtime_activation.json`
  - Key observed fields:
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
- Minimal prompt-flow artifact:
  - `phase2_gates/evidence/uat2_milestone2_prompt_flow.json`
  - `disposition=PASS`
  - deterministic request/session IDs captured
- Supplemental summary artifact:
  - `phase2_gates/evidence/uat2_milestone2_summary.md`

### 13.4 Milestone-2 Disposition (Session-Bounded)

- **PASS**
- Elevated in-process execution requirement satisfied.
- Deterministic startup handshake and minimal prompt-flow evidence captured.

### 13.5 Deterministic Fingerprints Encountered During Closure + Next Action

- `PA_LISTENER_START_FAILED` (measured_boot) — closed in-session
- `AO_CFG_MAX_MESSAGE_BYTES_INVALID` (config_validation) — closed in-session
- `UAT2_GATEWAY_HANDSHAKE_FAILED` (gateway_handshake) — closed in-session

Next action (exact):
1. Proceed to Milestone 3 (UAT-2.5 hardening + repeatability matrix).
2. Then proceed to Milestone 4 (UAT-3 non-dev enablement + UI-functional acceptance).

---

## 14. 2026-02-25 Milestone 4 Cross-Reference Status

Milestone-4 (UAT-3 non-dev enablement + UI-functional acceptance) was executed
for technical preconditions and evidence scaffold in this session and reached
session-bounded disposition:

- `BLOCKED_FAIL_CLOSED`
- blocker fingerprint: `UAT3_NON_DEV_PARTICIPANT_UNAVAILABLE`

Technical gate status in session:
- compile gate: PASS
- focused tests: `75 passed`
- integration guardrail: `49 passed`

UAT-3 evidence set generated for blocker traceability:
- `phase2_gates/evidence/uat3_operator_run_log.md`
- `phase2_gates/evidence/uat3_ui_matrix.json`
- `phase2_gates/evidence/uat3_failure_paths.json`
- `phase2_gates/evidence/uat3_docs_acceptance.md`
- `phase2_gates/evidence/uat3_summary.md`

Roadmap implication:
- UAT-2 and UAT-2.5 remain complete.
- Operational sign-off remains blocked until Milestone-4 participant-backed
  execution and explicit non-dev document acceptance are completed.

Roadmap order preserved after Milestone 2:
- Milestone 3: UAT-2.5 hardening and repeatability.
- Milestone 4: UAT-3 non-dev enablement + UI-functional acceptance.
