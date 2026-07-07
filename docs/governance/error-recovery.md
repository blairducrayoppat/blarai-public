# Error Handling & Crash Recovery Governance

## Audience

**Primary**: incident responder — opens an investigation when BlarAI
misbehaves in a way an operator cannot self-remediate; needs to know
where errors surface, what the Fail-Closed contract means for each
subsystem, and what recovery is sanctioned vs. what requires escalation.

**Secondary**: operator (reads the user-facing error texts and the
self-service remediation steps), developer (extends the error classes
when adding a new subsystem).

## Prerequisites

- [ADR-011](../adrs/ADR-011-All-LLM-Inference-GPU-NPU-Retirement.md) —
  GPU-only inference posture. A GPU fault is a service-halting event
  because there is no NPU fallback path for the Core Loop.
- [ADR-012](../adrs/ADR-012-Qwen3-14B-Model-Selection-Speculative-Decoding.md)
  §5 — Qwen2.5-1.5B retained as the legacy model for operator-gated
  rollback if Qwen3-14B fails persistent validation.
- Peer governance docs: [gpu-runtime.md](gpu-runtime.md) (model-load
  semantics and KV-cache invalidation); [circuit-breaker.md](circuit-breaker.md)
  (preventative-recovery surface for runaway generation);
  [pgov-validation.md](pgov-validation.md) (Fail-Closed semantics of
  the output validator); [ipc-protocol.md](ipc-protocol.md) (error
  envelope on the vsock wire).
- The Fail-Closed constant `FAIL_CLOSED = True` in
  `shared/constants.py` line 212 is the architectural default; any
  subsystem that claims a Fail-Open posture is a spec-level deviation
  that requires an ADR.

## Source References

| Artifact | Path | Section / Function |
|---|---|---|
| Deterministic failure fingerprint builder | `shared/runtime_config.py` | `build_failure_fingerprint` |
| AO startup Fail-Closed wiring | `services/assistant_orchestrator/src/entrypoint.py` | `start()` (lines 197-292) |
| AO config validation error class | `services/assistant_orchestrator/src/entrypoint.py` | `_validate_config_data` (lines 432-562) |
| AO per-stage failure codes | `services/assistant_orchestrator/src/entrypoint.py` | `AO_CFG_*`, `AO_MODEL_LOAD_FAILED`, `AO_JWT_VALIDATOR_INIT_FAILED`, `AO_LISTENER_START_FAILED` |
| AO inference Fail-Closed | `services/assistant_orchestrator/src/gpu_inference.py` | `_fail_closed` (lines 1156-1168) |
| AO prompt-request error path | `services/assistant_orchestrator/src/entrypoint.py` | `_handle_prompt_request` (lines 769-885) |
| PGOV Fail-Closed surface | `services/assistant_orchestrator/src/pgov.py` | pipeline error and `FALLBACK_MESSAGE` |
| PA hybrid adjudicator — DENY on any error | `services/policy_agent/src/adjudicator.py` | HybridAdjudicator docstring (lines 32-37) |
| PA runtime weight re-verification | `services/policy_agent/src/adjudicator.py` | "event-triggered runtime re-verification" (lines 25-30) |
| IPC error envelope | `shared/ipc/protocol.py` | `MessageType.ERROR` (line 50-51), `encode_error` |
| vsock transport | `shared/ipc/vsock.py` | `VsockTransport`, `VsockListener` |
| CAR schema | `shared/schemas/car.py` | `CanonicalActionRepresentation`, `AdjudicationDecision` |
| Weight integrity | `shared/models/weight_integrity.py` | `verify_weight_integrity`, `load_manifest` |
| Circuit breaker safe truncation | `services/assistant_orchestrator/src/circuit_breaker.py` | `safe_truncation_message` (lines 99-117) |
| Launcher entry point + log sink | `launcher/__main__.py` | `_LOG_PATH` (lines 40-47), `basicConfig` (line 49) |

## Governance Content

### Fail-Closed Per Subsystem

The Fail-Closed principle — **on uncertainty, deny rather than permit** —
is enforced at five subsystem boundaries. Each boundary is surfaced
uniformly: the subsystem produces a bounded, serializable failure
fingerprint rather than an unstructured traceback.

| Subsystem | Enforcement point | On error |
|---|---|---|
| Policy Agent | `HybridAdjudicator` (`services/policy_agent/src/adjudicator.py` lines 32-37) | Return `AdjudicationDecision.DENY`; no JWT minted |
| AO Inference | `OrchestratorGPUInference._fail_closed` (`gpu_inference.py` lines 1156-1168) | Empty `GenerationResult` with `error` populated; transport relays via `MessageType.ERROR` |
| AO PGOV | `pgov.py` pipeline error branch | `sanitized_text = FALLBACK_MESSAGE`, `approved=False`; the user sees a canned policy-constraint message |
| IPC Transport | `shared/ipc/vsock.py` `VsockTransport` | Connection teardown on malformed frame; `MessageFramer.decode` raises `ValueError` caught at the service handler and rewritten to an `ERROR` envelope |
| TUI / UI Gateway | Streaming handshake timeout | Boot aborts, launcher logs to `%LOCALAPPDATA%\BlarAI\launcher.log`, user sees a terminal message |
| Launcher | `launcher/__main__.py` startup sequence | Fail-Closed exit with graceful VM stop; no partial-state handoff to the TUI |

### Deterministic Failure Fingerprints

The AO service uses `build_failure_fingerprint` from
`shared/runtime_config.py` to produce identical `{stage, code, message}`
envelopes at every failure boundary. This is the contract that an
incident responder can rely on — the stage is one of `config_resolution`,
`config_validation`, `model_load`, `jwt_validator_init`, `listener_start`;
the code is a stable upper-snake-case identifier (e.g.
`AO_MODEL_LOAD_FAILED`); and the message is a one-sentence human
string. The fingerprint is surfaced on `AssistantOrchestratorService.
last_failure` for the launcher to read after a failed `start()`.

The same pattern is exercised by `_validate_config_data` at
`entrypoint.py` lines 432-562, which raises `ConfigResolutionError`
whose `code` field fills the fingerprint. There is no path by which a
silently-swallowed exception produces a "happy" boot.

### Policy Agent Adjudication Errors

PA errors deny by construction. The `HybridAdjudicator` docstring
(adjudicator.py lines 32-37) enumerates three denial paths:

1. **Rule-engine DENY** is authoritative and short-circuits both
   event-triggered integrity re-verification and the GPU classifier.
   No JWT minted.
2. **Runtime weight-integrity divergence** (re-computed SHA-256
   before every GPU inference call, adjudicator.py lines 25-30) ⇒
   halt inference, DENY, audit-log. Prevents a JWT from being minted
   against corrupted weights.
3. **GPU classifier exception** ⇒ pipeline Fail-Closed to DENY. The
   CAR hash is preserved in the audit log even on error.

User-visible outcome: a denied action fails with the launcher / caller
receiving a DENY adjudication and its reason code. A caller that expects
an ALLOW and receives a DENY has two legitimate paths: fix the requested
action (most common) or escalate for rule-engine amendment (rare).

### Assistant Orchestrator Generation Errors

The AO has three layered error paths:

1. **Startup failure**. Any of the five startup stages
   (`config_validation`, `model_load`, `jwt_validator_init`,
   `listener_start`, `listener_bind`) sets `self._last_failure` and
   returns `False` from `start()` (`entrypoint.py` lines 197-292).
   The launcher reads `last_failure` and logs the fingerprint; the AO
   does NOT enter a half-started state.
2. **Mid-stream generation error**. The AO service loop
   (`_serve_forever`, `entrypoint.py` lines 713-736) wraps each
   `_handle_connection` call in a try/except; on exception the
   transport is closed (no partial-output leak) and the loop
   continues serving other sessions. The failed request's user sees
   a `MessageType.ERROR` envelope.
3. **Post-generation PGOV denial**. Generation succeeded but the
   output failed PGOV. The AO transmits the `FALLBACK_MESSAGE` as
   the final stream token and emits a `PGOV_RESULT` envelope with
   `approved=False` and the violation reason codes
   (`_pgov_reason_codes`, `entrypoint.py` lines 51-68). The TUI
   shows the fallback text; there is no "output suppressed" banner
   by deliberate choice — the fallback text IS the notification per
   [pgov-validation.md](pgov-validation.md).

### PGOV Interaction with Mid-Stream Crash

If generation crashes partway through (e.g., the underlying
`LLMPipeline.generate` raises), `_generate_from_prompt`
(`gpu_inference.py` lines 937-938) returns a Fail-Closed
`GenerationResult` with `error` populated. The AO prompt handler
(`_handle_prompt_request` line 831) short-circuits to transmit a
`MessageType.ERROR` envelope and does NOT invoke PGOV on the partial
output. Partial output is discarded in this path — PGOV never sees
a truncated generation because the error branch runs first. This is
the correct posture: PGOV's role is output validation, not error
reporting.

A separate case is `CircuitBreaker` truncation (not a crash): the
generation returns cleanly with `truncated=True`, PGOV runs on the
truncated text, and the user sees the last-valid prefix plus the
`safe_truncation_message`. See [circuit-breaker.md](circuit-breaker.md)
for the full trip semantics.

### JWT / mTLS Failure Handling

JWT validator initialization failure at AO startup (`entrypoint.py`
lines 251-259) is Fail-Closed when `dev_mode=false` — the AO refuses
to start without a valid JWT CA/public key. The `dev_mode=true` path
allows a missing CA for local development but is not an operational
deployment.

mTLS material validation happens in `_validate_security_material`
(lines 649-711) BEFORE the listener binds:

- Missing `weight_manifest` in production ⇒ `AO_CFG_WEIGHT_MANIFEST_MISSING`.
- Missing or malformed `jwt_ca_cert_path` ⇒ `AO_CFG_JWT_CA_PATH_MISSING`
  or `AO_CFG_JWT_CA_INVALID`.
- Malformed Known-Good Manifest ⇒ `AO_CFG_KGM_INVALID` / missing
  digest ⇒ `AO_CFG_KGM_MODEL_DIGEST_MISSING`.

On the data path, a JWT validation failure at the PA is returned as
a DENY adjudication; the caller does not retry automatically because
JWT failures are typically clock-skew or rotation-timing issues, both
of which benefit from human attention over blind retry.

### Model-Load Failure

Model-load failure at AO startup (`entrypoint.py` lines 241-248)
returns `AO_MODEL_LOAD_FAILED` and aborts startup. The decision of
whether to invoke the ADR-012 §5 Qwen2.5-1.5B rollback path is
operator-gated — the AO does NOT auto-fall-back to the legacy model.
Rationale: auto-fallback would mask a potentially investigatable
failure (corrupted weights, missing manifest, device error). The
rollback procedure is documented in
[gpu-runtime.md](gpu-runtime.md#model-rollback--qwen3-14b--qwen25-15b).

Model-load failure at PA startup follows the same pattern via its
own entrypoint; the PA short-circuits to DENY for every adjudication
until the service is restarted with healthy weights.

### Weight-Integrity Check Failure

Weight-integrity check procedure is governed by the future
[weight-integrity.md](weight-integrity.md) doc (GOV-10 /
Vikunja #23), currently blocked on ISS-4 Pluton investigation. When
that doc lands, this section links to its recovery subsection.

Operationally today: the AO entrypoint's `_validate_security_material`
calls `load_manifest` and checks the digest of `openvino_model.bin`
against the manifest at startup. The PA's `HybridAdjudicator`
re-verifies the digest before EVERY GPU inference call (a separate
runtime re-verification, adjudicator.py lines 25-30). A mismatch is
Fail-Closed: AO refuses to start; PA denies the current adjudication
and continues denying until the service is restarted. There is no
auto-recovery on weight drift — the operator investigates whether
the drift was legitimate (authorized model update) or adversarial
(disk tampering) before restoring healthy weights.

### vsock IPC Failures

`shared/ipc/vsock.py` and `shared/ipc/protocol.py` define three
distinct IPC failure modes:

1. **Connection reset**. `VsockTransport.receive` returns `None`;
   the service handler closes the transport and the service loop
   continues. The caller sees a dropped connection and retries
   (IPC clients retry dropped connections — a single transient
   reset is not escalated).
2. **Message truncation / malformed JSON**. `MessageFramer.decode`
   raises `ValueError`; the service handler responds with a
   `MessageType.ERROR` envelope carrying `"Malformed message: <exc>"`
   (`entrypoint.py` line 746). The caller surfaces this to its
   user (for the TUI case, the UI Gateway relays it).
3. **Oversized message**. The framing layer enforces a 64 KB max
   (`DEFAULT_MAX_MESSAGE_BYTES` at `protocol.py` line 38,
   configurable via `VsockConfig.max_message_bytes`). Oversized
   inputs are rejected before the handler sees them.

The IPC layer does NOT retry on its own. Retries are the caller's
business; a single-reset retry is sanctioned, repeated resets
against the same endpoint escalate to operator review (the launcher
log captures the pattern).

### OOM Handling

There is no runtime OOM guard in the AO inference path. The memory
ceiling (`EFFECTIVE_CEILING_GB = 31.323` per `shared/constants.py`
line 19) is enforced by design-time sizing (DEC-01..DEC-10 Task 4
production configuration decisions), not by runtime instrumentation.
Observable OOM manifests as:

- `LLMPipeline` construction failure at AO start ⇒
  `AO_MODEL_LOAD_FAILED`.
- Process SIGKILL by the Windows OOM killer ⇒ the launcher detects
  the service vanish and halts the TUI.

Recovery: verify no third-party workload has pushed the host over
the 31.323 GB budget (e.g., a dev-time browser with 40+ tabs); then
restart BlarAI. If OOM recurs under normal load, escalate — the
memory budget may have drifted.

### User-Facing Error Messages Per Class

| Error class | Seen where | Exact text |
|---|---|---|
| PGOV denial | TUI streaming area | "I'm unable to provide that response due to content policy constraints. Please rephrase your request." (`pgov.py` lines 93-97) |
| Circuit-breaker token trip | TUI, after truncated output | "Output token limit reached (4096 tokens)." (`circuit_breaker.py` line 111) |
| Circuit-breaker depth trip | TUI, after truncated output | "Tool-call recursion limit reached (5 hops)." (`circuit_breaker.py` line 115) |
| AO generation error | TUI, in place of response | "Generation error — Fail-Closed: &lt;exception-repr&gt;" (`gpu_inference.py` lines 565, 618, 938) |
| Malformed IPC message | TUI, ambient error surface | "Malformed message: &lt;exception-repr&gt;" (`entrypoint.py` line 746) |
| AO not ready | TUI, on first prompt | "ORCHESTRATOR_NOT_READY" (`entrypoint.py` line 779) |
| Adjudication DENY (PA) | Launcher/audit log | Not user-facing in the Core Loop; surfaces to the caller of the CAR submission |

The user surface deliberately does not expose which PGOV stage failed
or which stage of AO startup failed — operator remediation comes from
the log, not the error text. This is Information-Hiding by design.

### Logging and Audit Trail

Launcher logs to `%LOCALAPPDATA%\BlarAI\launcher.log` per
`launcher/__main__.py` lines 40-47; format is `%(asctime)s [%(name)s]
%(levelname)s: %(message)s` (line 51). The sink is local-disk, no
external forwarding — consistent with BlarAI's air-gapped runtime
posture.

Per-subsystem loggers:

- `blarai.launcher` (launcher/__main__.py line 58)
- `services.assistant_orchestrator.src.entrypoint` (module
  `__name__`)
- `services.assistant_orchestrator.src.gpu_inference`
- `services.assistant_orchestrator.src.pgov`
- `services.policy_agent.src.adjudicator`

PGOV denials log at `WARNING` with a truncated `text_preview`
(`%.120r`, 120-char max preview — `pgov.py` lines 585-590). No full
denied output is persisted; the preview is the audit signal. Sink
retention is governed by `observability-logging.md` (GOV-12 / Vikunja
#25), currently at author-phase in this same sprint. Pending that
doc, the operational rule is "local disk, no rotation tooling shipped
today".

### Retry vs Escalation Matrix

| Error class | Retry? | Escalation trigger |
|---|---|---|
| Single vsock connection reset | Caller retries once | Repeated reset within 60 s ⇒ operator |
| Malformed IPC frame | No retry | Always ⇒ operator (suggests sender bug or wire corruption) |
| PGOV denial | No retry | Repeated denial on benign queries ⇒ PGOV triage per [pgov-validation.md](pgov-validation.md) |
| Circuit-breaker trip | No retry (the output is the signal) | High-frequency trips ⇒ threshold-tuning review |
| AO startup `config_validation` | No retry | Always ⇒ operator fixes config |
| AO startup `model_load` | No retry | Always ⇒ weight-integrity investigation |
| AO startup `jwt_validator_init` | No retry | Always ⇒ cert-rotation check |
| PA adjudication DENY (rule engine) | No retry | Expected ⇒ caller redesigns action OR escalates rule-engine amendment |
| Weight-integrity divergence | No retry | Always ⇒ incident-response (disk tamper vs. authorized update) |
| OOM SIGKILL | Auto-restart via launcher | Repeated ⇒ memory-budget review |

### Boot-Time vs Runtime Failure Distinction

The boundary between "boot-time" and "runtime" failure matters for
recovery. Boot-time failures (AO/PA startup) are cleanly Fail-Closed
— the launcher halts the VM, stops services, and exits. There is
no half-running system to recover. Runtime failures (generation
error, IPC reset, PGOV denial) happen against an already-live service
and recover in place: the service loop continues, subsequent requests
are unaffected, and only the failed request's user sees the error.

The launcher's startup sequence (`launcher/__main__.py`) goes:
Administrator elevation ⇒ Hyper-V VM start ⇒ PA measured-boot gate
⇒ AO service start ⇒ SessionStore init ⇒ TransportGateway init ⇒
BlarAIApp launch. Any step failing ⇒ graceful Fail-Closed exit.
A consolidated boot-sequence governance doc is future-sprint scope
(GOV-15 / Vikunja #124); the authoritative source files today are
`launcher/__main__.py` and the service entry points
(`services/assistant_orchestrator/src/entrypoint.py`,
`services/policy_agent/src/entrypoint.py`).

## Open Questions / Deferred Items

- **Weight-integrity governance** — full Pluton ceremony and Known-
  Good Manifest rotation procedure deferred to GOV-10 /
  [weight-integrity.md](weight-integrity.md), Pluton-blocked on
  ISS-4. This doc forward-references it; the forward link is
  intentionally broken until GOV-10 lands.
- **Boot-sequence governance** — the launcher + service startup
  crosses multiple files and deserves a consolidated doc. Deferred
  to GOV-15 / Vikunja #124. Within this doc, individual source
  files are cited directly rather than routing through a not-yet-
  authored `boot-sequence.md`.
- **Observability / logging retention** — currently "local disk,
  no rotation tooling". Full governance authored in-sprint as
  GOV-12 / observability-logging.md (EA-4). When that doc lands,
  this doc's Logging and Audit Trail subsection links there for
  retention policy.
- **Credential rotation procedure** — adjacent to JWT/mTLS failure
  handling but scoped to GOV-01 / credentials-lifecycle.md
  (Pluton-blocked on ISS-4). Not in this doc's scope.
- **Automated OOM instrumentation** — current posture is design-
  time sizing. If a future sprint adds runtime OOM detection, this
  doc's OOM subsection updates to name the detection surface.
