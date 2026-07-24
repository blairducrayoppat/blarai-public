# Deployment Verification & Rollback Governance

## Audience

**Primary**: operator — runs the launcher end-to-end, reads
activation evidence to confirm a clean boot, and executes the manual
rollback procedures below when a deploy fails or a VM falls out of a
known-good state.

**Secondary**: incident responder — follows §Recovery to return the
system to a healthy state after a failed production activation or a
mid-deploy crash.

## Prerequisites

- [STYLE.md](STYLE.md) — binding governance template.
- [ADR-011](../adrs/ADR-011-All-LLM-Inference-GPU-NPU-Retirement.md) —
  "All LLM inference on GPU." Motivates why the deployment must
  validate that the guest runtime's `device = GPU` constraint holds
  and that model artifacts are present before the service is allowed
  to start.
- [ADR-012](../adrs/ADR-012-Qwen3-14B-Model-Selection-Speculative-Decoding.md) —
  Qwen3-14B as the unified production model; Qwen3-0.6B draft for
  speculative decoding. Model-rollback commentary in §7 derives from
  ADR-012.
- **ADR-absence note**: no ADR directly governs the deployment
  flow, the evidence-JSON schema, the error-code prefix set, or the
  preflight ordering. See **Open Questions**.
- Peer governance docs: [observability.md](observability.md) (the
  evidence-JSON and error-fingerprinting taxonomy this doc relies on);
  [configuration-management.md](configuration-management.md) (the
  `CFG_*` and `AO_CFG_*` codes that the config-preflight stage
  surfaces); [gpu-runtime.md](gpu-runtime.md) (the GPU-runtime
  invariants that deployment artifacts must honor).

## Source References

| Artifact | Path | Notes |
|---|---|---|
| Host launcher main flow | `launcher/__main__.py` | full file; steps 1-7 + atexit `_cleanup` |
| Prompt-flow smoke test | `launcher/__main__.py` | `_run_uat2_prompt_flow_preflight` (lines 103-190) |
| Activation evidence writer | `launcher/__main__.py` | `_record_activation_evidence` (lines 72-83) |
| Prompt-flow evidence writer | `launcher/__main__.py` | `_record_prompt_flow_evidence` (lines 86-100) |
| Priority-5 guest deployment | `launcher/guest_deploy.py` | full file; `deploy_guest_runtime` is the orchestrator |
| Guest config preflight | `launcher/guest_deploy.py` | `_validate_guest_runtime_configs` (lines 166-202) |
| vsock topology check | `launcher/guest_deploy.py` | `_validate_vsock_topology` (lines 96-125) |
| Runtime bundle build | `launcher/guest_deploy.py` | `_build_bundle` (lines 136-163) |
| VM lifecycle (start/stop/state) | `launcher/vm_manager.py` | `ensure_vm_running`, `stop_vm`, `get_vm_state` |
| Admin elevation | `launcher/vm_manager.py` | `is_admin`, `request_elevation` (ctypes ShellExecuteW) |
| vsock constants (`VSOCK_SERVICE_GUID`, `VSOCK_PORT`) | `shared/constants.py` | lines 225-236 |
| `ORCHESTRATOR_VM_ID` / `_VM_NAME` | `shared/constants.py` | lines 225-228 |

## Governance Content

### 1. Two deployment surfaces — host activation vs guest runtime deploy

BlarAI has **two** deploy verbs, and they do different work:

- **Host activation** — `python -m launcher` (the interactive
  production run). Ensures admin rights, starts the Hyper-V VM,
  boots PA and AO services, initializes the session store, executes
  handshake + prompt-flow preflights, and launches the TUI. Writes
  `activation_evidence` JSON. This is the flow an operator executes
  to bring the system up day-to-day.
- **Guest runtime deploy** — `python -m launcher.guest_deploy`
  (Priority-5 one-shot). Packages runtime artifacts into a zip,
  validates vsock topology, validates guest-side config, copies the
  bundle + bootstrap script into the VM via Hyper-V Guest Service
  Interface. Writes `priority5_guest_deploy.json` evidence. This is
  the flow that transfers code/config/models into the VM when they
  change; it does not start the services inside the VM — the
  bootstrap script does that manually, per the evidence's
  `guest_startup.invocation_mode: manual-in-guest`.

Both flows are **fail-closed**: any stage error aborts the remainder
of the flow, writes evidence with `disposition: FAIL` and a
failure-fingerprint list, and returns non-zero.

### 2. Host activation — step-by-step

Sequence from `launcher/__main__.py::main` with error codes:

| # | Step | Success signal | Failure code |
|---|---|---|---|
| 1 | Resolve `DeploymentMode` | mode decided | `CFG_MODE_INVALID` (re-raised from `shared/runtime_config.py`) |
| 2 | Admin check; if not admin, request UAC elevation | `is_admin() == True` | `UAC_ELEVATION_DENIED` or `UAC_PROMPT_TRIGGERED` (non-error handoff) |
| 3 | Start Hyper-V VM (`ensure_vm_running`) | `VMState.RUNNING` | `VM_START_FAILED` |
| 4 | Start Policy Agent (measured-boot gate) | `PolicyAgentService.start() == True` | PA-specific codes via `last_failure`; fallback `PA_START_FAILED` |
| 5 | Start Assistant Orchestrator | `AssistantOrchestratorService.start() == True` | AO-specific codes via `last_failure`; fallback `AO_START_FAILED` |
| 6 | Initialize `SessionStore` | SQLite ready | `SESSION_STORE_INIT_FAILED` |
| 7a | Transport gateway handshake preflight | `check_pa_status() == True` | `GATEWAY_HANDSHAKE_FAILED` |
| 7b | Prompt-flow smoke test | `_run_uat2_prompt_flow_preflight == True` | `PROMPT_FLOW_FAILED` / `UAT2_PROMPT_FLOW_FAILED` |
| 8 | Launch Textual TUI | TUI loop exits normally | `LAUNCHER_TUI_RUNTIME_ERROR` |

Every stage writes into the `activation_evidence` dict. On any
failure, `_record_activation_evidence` flushes to disk at
`phase2_gates/evidence/uat2_real_runtime_activation.json` (overridable
via `BLARAI_ACTIVATION_EVIDENCE_PATH`). On success, the same file is
written with `disposition: PASS`.

### 3. Guest-runtime deploy — step-by-step

Sequence from `launcher/guest_deploy.py::deploy_guest_runtime`:

| # | Stage | Check | Failure code |
|---|---|---|---|
| 1 | VM start | `ensure_vm_running == True` | `P5_VM_START_FAILED` |
| 2 | Guest Service Interface | `is_guest_service_interface_enabled == True` | `P5_GSI_DISABLED` |
| 3 | vsock topology | `_validate_vsock_topology` → `PASS` + host `vm_id`/`service_guid`/`vsock_port` match `shared/constants.py` + `connection_successful: true` + `tcp_ip_used: false` | `P5_VSOCK_TOPOLOGY_INVALID` |
| 4 | Guest config preflight | `PolicyAgentService.validate_runtime_config("guest")` + `AssistantOrchestratorService.validate_runtime_config("guest")` both PASS | `P6_POLICY_CONFIG_INVALID`, `P6_ORCH_CONFIG_INVALID` |
| 5 | Guest channel probe copy | `.blarai_probe.txt` via `copy_file_to_vm`, 5 retries @ 2s | `P5_GUEST_CHANNEL_NOT_READY` |
| 6 | Bundle build | All `_RUNTIME_DIRS` + optionally `_MODEL_DIRS` + `_RUNTIME_FILES` exist; zip created | `P5_BUNDLE_BUILD_FAILED` |
| 7 | Bundle copy | `runtime_bundle.zip` copied to `guest_root` | `P5_COPY_BUNDLE_FAILED` |
| 8 | Bootstrap copy | `bootstrap_runtime.sh` copied to `guest_root` | `P5_COPY_BOOTSTRAP_FAILED` |

On success, `priority5_guest_deploy.json` is written with
`disposition: PASS`, the bundle destinations, and an
`expected_evidence` pointer to the per-VM startup JSON the bootstrap
script produces inside the guest (`guest_root/evidence/priority5_guest_startup.json`).

The vsock topology check reads an already-produced evidence file
(`phase2_gates/evidence/vsock_validation.json`); this file is
produced by an upstream Phase-2 gate and is **not** regenerated by
the deploy flow. A stale or deleted `vsock_validation.json` is
treated as a topology failure.

### 4. Evidence-artifact schema

Every evidence JSON written by the launcher shares a common shape:

- `timestamp` — ISO-8601 UTC at write time.
- `milestone` / `gate` — human-friendly identifiers.
- `disposition` — `PASS` | `FAIL` | `ELEVATION_HANDOFF`.
- `fail_closed` — `"true"` (string, for grep-compatibility with log
  lines).
- `failure` — single most-recent failure fingerprint OR `null`.
- `failure_fingerprints` — (guest-deploy variant) ordered list of all
  fingerprints accumulated through the flow.
- Stage-specific keys (e.g., `steps: {admin_ok, vm_running, ...}` on
  host activation; `artifacts: {bundle_destination, ...}` on guest
  deploy).

The failure fingerprint itself is the canonical
`{stage, code, message, disposition, fail_closed}` dict emitted by
`shared/runtime_config.py::build_failure_fingerprint` or the local
`_failure_fingerprint` helper in `guest_deploy.py` (which adds
`timestamp`). Either shape is accepted on read; downstream log
parsers should tolerate the missing-`timestamp` variant.

### 5. Smoke test — UAT2 minimal prompt flow

`_run_uat2_prompt_flow_preflight` (host activation step 7b) is the
functional smoke test that exercises the full IPC + model path before
the TUI is shown to the operator:

1. Creates a session via `SessionStore.create_session`.
2. Sends a scripted prompt (`"UAT2_M2_HEALTHCHECK"`) via the
   transport gateway.
3. Drains all stream tokens from the AO.
4. Fetches the PGOV result for the request.
5. Records an assistant turn with the PGOV status + reason codes.
6. On success, deletes the ephemeral session (so it does not pollute
   the user-visible session list).

On any exception, the flow records a failure fingerprint with
`code=UAT2_PROMPT_FLOW_FAILED` and returns False. The outer launcher
surface then aborts with `PROMPT_FLOW_FAILED` at `main`. There is no
retry loop — the first failure is fatal.

### 6. Deployment timeout observations

- `copy_file_to_vm` calls in `guest_deploy.py` carry explicit
  timeouts: probe-copy 30 s, bundle-copy 900 s (15 min, generous for
  model artifacts), bootstrap-copy 120 s.
- VM start does **not** have an explicit overall timeout in
  `ensure_vm_running`; it polls `get_vm_state` until the state is
  `RUNNING` or an error condition surfaces (see `vm_manager.py`).
- The host prompt-flow preflight has **no explicit timeout** at the
  launcher layer — the underlying IPC uses its own timeouts (see
  [ipc-protocol.md](ipc-protocol.md) and
  [configuration-management.md](configuration-management.md) for
  `ipc.timeout_ms`).
- The handshake preflight similarly inherits IPC-level timeouts via
  `gateway.check_pa_status()`.

**Governance gap (I-3).** No single-value "overall deploy timeout"
constant exists. The cumulative worst-case wall time is dominated by
the 900 s bundle copy. An overall timeout would prevent a hung deploy
from pinning operator attention indefinitely; this is a deferred
hardening item — see **Open Questions**.

### 7. Automatic rollback (fail-closed)

On any host-activation failure, the launcher:

1. Writes the failure fingerprint to `activation_evidence`.
2. Prints a failure banner via `_step` and waits for `Enter`.
3. Returns a non-zero exit code from `main`.
4. On process exit, the `atexit`-registered `_cleanup()` runs:
   - Stops the PA service if it is running.
   - Stops the AO service if it is running.
   - Closes the `SessionStore`.
   - Stops the VM via `stop_vm` if and only if
     `_vm_was_started` is True (i.e., the launcher turned it on this
     run; a VM that was already running is left running).

`_cleanup` is tolerant of partial state — each component is gated by
`is None` / `running` checks, so a cleanup during a partial activation
(e.g., after step 4 but before step 5) does not raise. This is the
auto-rollback contract: on any step's FAIL, the operator gets a
consistent surface where any service the launcher started is stopped,
and any VM the launcher started is stopped — but any component that
was running before the launcher started is left alone.

### 8. Model rollback (ADR-012 §5)

The production configuration targets Qwen3-14B (primary) with
Qwen3-0.6B as the speculative-decoding draft model. ADR-012 §5
specifies the model-rollback path; the runtime config knob is
`gpu.speculative_decoding_enabled` (optional bool; see
[configuration-management.md](configuration-management.md) §2). To
roll back the speculative-decoding stack while retaining Qwen3-14B,
disable the flag and restart the AO. A full primary-model rollback to
an alternate model (e.g., a smaller fallback) requires editing
`gpu.model_dir` in the guest TOML and re-running
`guest_deploy` to push the alternate weights; no config-only
hot-switch is supported.

### 9. Deployment audit trail

- Activation log: `%LOCALAPPDATA%\BlarAI\launcher.log` (INFO-level
  `blarai.launcher` output, plus any logger propagation from
  imported services). See [observability.md](observability.md) for
  format and severity semantics.
- Activation evidence: `phase2_gates/evidence/uat2_real_runtime_activation.json`
  (overridable via `BLARAI_ACTIVATION_EVIDENCE_PATH`).
- Prompt-flow evidence: `phase2_gates/evidence/uat2_milestone2_prompt_flow.json`
  (overridable via `BLARAI_PROMPT_FLOW_EVIDENCE_PATH`).
- Guest-deploy evidence: `phase2_gates/evidence/priority5_guest_deploy.json`
  (default — CLI `--evidence-file` overrides).
- Guest-startup evidence (written inside the VM by the bootstrap
  script): `guest_root/evidence/priority5_guest_startup.json`.

No retention policy exists today; evidence files are idempotently
overwritten on each run. Operators who need history should rotate the
file out-of-band before re-running.

## Recovery / Remediation Procedures

1. **`UAC_ELEVATION_DENIED` (step 2).** The operator declined the
   UAC prompt or is on an unprivileged account. Re-run the launcher
   as administrator (right-click → "Run as administrator"). There is
   no non-elevated degraded mode for Hyper-V VM management.
2. **`VM_START_FAILED` / `P5_VM_START_FAILED` (step 3).** Inspect
   `Get-VM -Name BlarAI-Orchestrator` in an elevated PowerShell.
   Common causes: VM does not exist (re-run initial VM creation
   tooling); VM is in `Saved` state (run
   `Start-VM -Name BlarAI-Orchestrator` manually or delete the saved
   state with `Remove-VMSavedState`); Hyper-V service is not running.
3. **`P5_GSI_DISABLED` (guest-deploy step 2).** The VM's Guest
   Service Interface is off. Enable it via
   `Enable-VMIntegrationService -VMName BlarAI-Orchestrator -Name "Guest Service Interface"`
   and re-run the deploy.
4. **`P5_VSOCK_TOPOLOGY_INVALID` (guest-deploy step 3).** The
   upstream `phase2_gates/evidence/vsock_validation.json` is stale,
   missing, or disagrees with the `VSOCK_*` constants in
   `shared/constants.py`. Re-run the Phase-2 vsock validation gate
   to regenerate the evidence, then re-run guest-deploy. Do **not**
   hand-edit the evidence file — it is produced by a validation
   script with specific host/guest probe results.
5. **`P6_POLICY_CONFIG_INVALID` / `P6_ORCH_CONFIG_INVALID` (step 4).**
   The wrapped `AO_CFG_*` / `CFG_*` code identifies the constraint.
   See [configuration-management.md](configuration-management.md) for
   the per-code remediation. Fix the TOML, re-run.
6. **`P5_GUEST_CHANNEL_NOT_READY` (step 5).** The probe copy
   timed out after 5 retries. The VM may be under heavy boot load or
   the Hyper-V Integration Services may have regressed. Wait \~30 s,
   confirm `Get-VMIntegrationService` shows both Guest Service
   Interface and Heartbeat as `OK`, then re-run.
7. **`P5_BUNDLE_BUILD_FAILED` (step 6).** A required source directory
   or script is missing from the host working tree. The message names
   the missing path. Fix the tree (or ensure the deploy is run from
   the repo root), re-run.
8. **`P5_COPY_BUNDLE_FAILED` / `P5_COPY_BOOTSTRAP_FAILED` (steps 7-8).**
   Guest disk may be full, or the guest path may not be writable.
   SSH/console into the VM, verify `guest_root` has write permission
   and free space, re-run.
9. **`PROMPT_FLOW_FAILED` (host step 7b).** The end-to-end prompt
   path failed. Check the prompt-flow evidence JSON for the inner
   failure fingerprint (typically a timeout or a PGOV FAIL). If the
   cause is transient (network-less vsock hiccup), re-run the
   launcher; if it is a PGOV config issue, see
   [pgov-validation.md](pgov-validation.md) and
   [configuration-management.md](configuration-management.md).
10. **Manual emergency rollback.** If the launcher is unkillable or
    the VM has entered a mixed state:
    1. From an elevated PowerShell: `Stop-Process -Name python -Force`
       (kills any orphaned launcher/service processes).
    2. `Stop-VM -Name BlarAI-Orchestrator -Force`.
    3. If VM is corrupt: `Stop-VM ... -TurnOff`, delete the saved
       state, confirm the `.vhdx` at `C:\HyperV\BlarAI\Orchestrator.vhdx`
       is not locked, then re-run host activation.
11. **Model rollback.** Disable speculative decoding or swap the
    model dir per §8; re-run `guest_deploy` with the new config;
    re-run host activation.

## Open Questions / Deferred Items

- **GOV-13-ADR-01 (ADR-absence).** No ADR governs the deployment
  flow, the evidence-JSON schema, the error-code prefix set (`P5_*`,
  `P6_*`, `UAT2_*`), or the preflight ordering. ADR-011 and ADR-012
  are cited above as closest-relevant (they govern the GPU and model
  invariants the deployment must uphold) but neither documents the
  deployment surface itself.
- **GOV-13-TIMEOUT-01 (I-3).** No overall deployment timeout
  constant exists. A hung vsock topology read or a hung UAC dialog
  could pin operator attention indefinitely. A future hardening
  sprint should introduce a single `DEPLOY_TIMEOUT_S` constant with
  a sensible ceiling (e.g., 1800 s = 30 min) and wire it through
  `deploy_guest_runtime`. Track via a dedicated Vikunja ticket.
- **GOV-13-EVIDENCE-RETENTION-01.** Evidence files overwrite on
  every run. An incident responder analyzing a flaky deploy across
  multiple attempts has to rotate files out-of-band. A per-run
  timestamped evidence path (or a `evidence/history/<ts>/` rotation)
  would be a small hardening. Deferred.
- **GOV-13-VM-TIMEOUT-01.** `ensure_vm_running` polls indefinitely
  for `VMState.RUNNING`. See `launcher/vm_manager.py` for the poll
  loop; a max-wait would bound the worst case.
- **GOV-13-GUEST-STARTUP-01.** `guest_startup.invocation_mode`
  is `manual-in-guest` — the bootstrap script must be executed
  inside the VM after deploy. A future iteration could drive the
  bootstrap via PowerShell Direct or the Guest Service Interface's
  command channel, removing the manual step. Deferred.
- **GOV-13-BOOT-SEQUENCE-01.** The ordering of activation steps
  (admin → VM → PA → AO → store → gateway → TUI) is implicit in
  `__main__.py::main`. A future `boot-sequence.md` (GOV-15) will
  pull this into a dedicated governance doc.
