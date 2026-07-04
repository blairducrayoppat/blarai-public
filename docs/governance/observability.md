# Observability & Logging Strategy Governance

## Audience

**Primary**: developer — picks a log level, adds a new error code, or
wires a new evidence artifact. The taxonomy below is the contract for
both log severity and failure-fingerprint shape; any new log site
should fit inside it without inventing a new prefix or severity
convention.

**Secondary**: incident responder — greps launcher and service logs
for a failure code, cross-references to an evidence JSON, and decides
which runbook applies.

**Secondary**: auditor — verifies that every fail-closed surface
produces a deterministic, code-tagged log line and an evidence
fingerprint suitable for replay.

## Prerequisites

- [STYLE.md](STYLE.md) — binding governance template.
- [ADR-010](../adrs/ADR-010-Policy-Agent-GPU-Classification.md) —
  Policy Agent classification on GPU; motivates the adjudication
  log events.
- [ADR-011](../adrs/ADR-011-Policy-Agent-GPU-NPU-Retirement.md) —
  GPU-only inference; motivates the model-load and generation log
  events.
- **ADR-absence note**: no ADR directly governs BlarAI's logging
  format, severity taxonomy, or evidence-JSON schema. ADR-010 and
  ADR-011 are the closest-relevant because they produce the
  highest-volume logging surfaces (adjudication events and generation
  events). See **Open Questions** for the ADR-candidate gap.
- Peer governance docs:
  [deployment-verification.md](deployment-verification.md) (the
  evidence-artifact audience for deploy-time events);
  [configuration-management.md](configuration-management.md) (the
  `CFG_*` code set this doc references);
  [error-recovery.md](error-recovery.md) and
  [circuit-breaker.md](circuit-breaker.md) (the service-side error
  surfaces this doc catalogues).

## Source References

| Artifact | Path | Notes |
|---|---|---|
| Launcher logging config (basicConfig + log path) | `launcher/__main__.py` | lines 40-58 |
| Launcher log destinations (`launcher.log`, stderr) | `launcher/__main__.py` | lines 43-55 |
| Launcher error codes + `activation_evidence` | `launcher/__main__.py` | `main` (lines 279-659) |
| `build_failure_fingerprint` (canonical failure shape) | `shared/runtime_config.py` | lines 56-68 |
| Guest-deploy log events + `P5_*` / `P6_*` codes | `launcher/guest_deploy.py` | full file |
| UI Gateway IPC boundary logging | `services/ui_gateway/src/transport.py` | logger defined line 51; event sites throughout |
| PA lifecycle + measured-boot log events | `services/policy_agent/src/entrypoint.py` | logger line 63; events in `start` and `_measured_boot` |
| AO lifecycle + config-load log events | `services/assistant_orchestrator/src/entrypoint.py` | logger line 48; events in `start`, `_validate_config_data`, `_load_model` |
| PGOV pipeline log events (cosine threshold 0.85) | `services/assistant_orchestrator/src/pgov.py` | logger line 53; events in `check_leakage`, `_run_pipeline` |
| Activation-evidence schema | `launcher/__main__.py` | `_record_activation_evidence` (lines 72-83) + `activation_evidence` dict |
| Prompt-flow evidence schema | `launcher/__main__.py` | `_record_prompt_flow_evidence` (lines 86-100) |
| Guest-deploy evidence schema | `launcher/guest_deploy.py` | `_write_json` calls with `disposition` + `failure_fingerprints` |

## Governance Content

### 1. Log-level taxonomy

BlarAI uses the standard Python `logging` levels; every service
configures a module-scoped `logger = logging.getLogger(__name__)` and
delegates to the launcher's `basicConfig` when running under the
launcher. Standalone service runs (tests, guest-deploy entrypoint)
configure their own `basicConfig` at INFO.

| Level | Use | Examples (from source) |
|---|---|---|
| `DEBUG` | Fine-grained diagnostics useful only while debugging a specific site. Not enabled in production. | `logger.debug(...)` sites (rare in service code; used in tests). |
| `INFO` | Expected lifecycle events, handshake progress, per-request correlation IDs. | `"Boot-Phase-3: beginning PA handshake"`, `"Policy Agent entrypoint started with measured-boot ordering."`, `"stream_tokens: session=%s — receiving from IPC"` |
| `WARNING` | Anomalies that do not halt the flow but are worth noticing. Using an ephemeral-dev code path, falling back to `:memory:` session DB, PGOV pipeline soft-trip. | `"Using ephemeral dev JWT key material."`, `"%LOCALAPPDATA%% not set — using in-memory session database"`, PGOV soft-warn variants. |
| `ERROR` | Fail-closed outcomes. Every `ERROR` at a service boundary corresponds to a failure fingerprint being recorded (see §5). | `"Policy Agent measured boot failed: %s"`, `"PGOV pipeline error (Fail-Closed): %s"`, `"AF_HYPERV connect failed: %s"` |
| `CRITICAL` | Reserved; not currently emitted by service code. Intended for host-level "the process is about to exit" events where ERROR would be lost. | — |

Severity discipline is load-bearing. A grep for `ERROR` against the
launcher log is expected to turn up exactly the surfaces that wrote a
failure fingerprint. A new log site that emits `ERROR` without writing
an evidence record is a governance gap.

### 2. Log destinations

Launcher runtime (`python -m launcher`) configures two handlers via
`logging.basicConfig`:

- `FileHandler` at `%LOCALAPPDATA%\BlarAI\launcher.log` (UTF-8,
  append mode). This is the primary on-disk audit surface for every
  run.
- `StreamHandler` to `sys.stderr`. Raw log lines bleed through the
  Textual TUI as visible artifacts, so just before the TUI launches
  (`app.run()` in `__main__.py` line 642), the stderr handler's level
  is raised to `CRITICAL + 1` — effectively silent. File logging is
  unaffected. The stream handler is never removed; raising its level
  avoids a class of Textual terminal-initialisation bugs where
  handler removal interferes with `fcntl` tty state.

Standalone service runs (`python -m launcher.guest_deploy`, pytest,
ad-hoc scripts) configure stderr-only logging at INFO — there is no
default file sink outside the launcher-driven flow.

Log format (everywhere):

```text
%(asctime)s [%(name)s] %(levelname)s: %(message)s
```

The `%(name)s` field is the logger hierarchy (`blarai.launcher`,
`launcher.vm_manager`, `services.policy_agent.src.entrypoint`, etc.),
which is how a reader maps a line back to a source file.

### 3. Sensitive-data filtering — what is and is not logged

The platform-wide privacy mandate (two-tier, CLAUDE.md) is absolute
for the BlarAI runtime. In practice, log sites follow these rules:

- **Prompt text**: the PA transport-layer boundary and AO IPC
  boundary log event occurrences and byte counts, not prompt
  contents. The UAT2 prompt-flow preflight does log a bounded
  `response_excerpt` (first 512 chars) to its evidence JSON — this is
  the deterministic healthcheck string `"UAT2_M2_HEALTHCHECK"`, not
  user input.
- **Generated response text**: not logged at INFO or above. PGOV's
  `logger.error` on Fail-Closed includes the exception string but not
  the full generated text; the PGOV soft-warn carries the
  `leakage_score` and threshold, not the response.
- **Session IDs, request IDs**: logged at INFO for correlation (e.g.,
  `"stream_tokens: session=%s — receiving from IPC"`). Session IDs
  are opaque UUIDs; no PII is encoded.
- **Credentials / secrets**: never logged. JWT CA certificate paths
  (`security.jwt_ca_cert_path`) and weight-manifest paths
  (`gpu.weight_manifest`) appear in config-resolution error messages
  at ERROR (value is the path string, not the cert/manifest bytes).
- **Environment values**: `BLARAI_RUNTIME_MODE` is logged at INFO
  when the launcher resolves mode. `LOCALAPPDATA` absence is logged
  at WARNING (triggers the `:memory:` fallback).

**Governance gap (I-5).** The codebase does not implement explicit
regex-based PII scrubbing in its log formatter. The privacy guarantee
today is by-construction (call sites do not pass user content to
loggers). A future logging-middleware layer could add belt-and-
suspenders redaction; this is a deferred hardening item. See
**Open Questions**.

### 4. Per-subsystem event classification

**Policy Agent (`services/policy_agent/src/entrypoint.py`).**

- INFO: `"Policy Agent entrypoint started with measured-boot ordering."`,
  `"Policy Agent entrypoint stopped."`, per-adjudication correlation
  entries.
- WARNING: measured-boot retry advisories, missing-dev-JWT-material
  fallback.
- ERROR: `"Policy Agent measured boot failed: %s"`,
  `"Policy Agent measured boot hard-locked: %s"`,
  `"Policy Agent measured boot invalid state: %s"` — every site
  writes a failure fingerprint into `self._last_failure` before
  returning.
- Adjudication log (per-request): `request_id`, `car_hash`,
  `deterministic_pass`, `probabilistic_pass`, `decision`,
  `confidence`, `blocking_rule` (if DENY). This is the audit trail
  for USE-CASE-001; see [rule-engine.md](rule-engine.md) for the
  DecisionArtifact shape it derives from.

**Assistant Orchestrator (`services/assistant_orchestrator/src/entrypoint.py`).**

- INFO: lifecycle start/stop, model-load progress, config resolution
  success.
- ERROR: `"Orchestrator config load failed: %s"`,
  `"Orchestrator model load failed (Fail-Closed)."`, generation
  failures. Every ERROR has a matching `_last_failure` fingerprint
  dict.
- WARNING: sampling-param bounds advisories, optional-feature
  fallbacks (e.g., speculative decoding disabled).

**PGOV (`services/assistant_orchestrator/src/pgov.py`).**

- INFO: model-load completion, pipeline completion at DEBUG/INFO
  boundary.
- WARNING: soft-warn when the pipeline runs but cosine score is
  below-threshold-but-near-boundary (`logger.warning` site lines
  413-416 and 585).
- ERROR: Fail-Closed exits — `"LeakageDetector load_model failed
  (Fail-Closed): %s"`, `"PGOV pipeline error (Fail-Closed): %s"`.
  The cosine threshold (**0.85**, from `shared/constants.py`) gates
  DENY vs ALLOW at line 577; a score `>= 0.85` on the last stage
  triggers a DENY path with reason
  `f"Leakage score {leakage_score:.3f} >= threshold {cosine_threshold}"`.

**UI Gateway transport (`services/ui_gateway/src/transport.py`).**

- INFO: boot-phase-3 handshake progress, token-stream lifecycle
  (`"stream_tokens: session=%s — receiving from IPC"`), reset events,
  tool-call buffer flushes on PGOV denial.
- WARNING: per-frame parse-degraded events, unexpected state
  transitions that are still recoverable.
- ERROR: `"AF_HYPERV connect failed: %s"`, handshake errors, frame
  decode failures. Each ERROR at transport is correlated with either
  a retry (at INFO) or a surfaced fingerprint at the launcher level.

**Launcher (`launcher/__main__.py`, `launcher/guest_deploy.py`,
`launcher/vm_manager.py`).**

- INFO: every `_step(...)` call. Cleanup progress
  (`"Cleanup: shutting down components"`, `"Cleanup: stopping ...
  service"`, `"Cleanup: complete"`).
- ERROR: every failure branch that writes a failure fingerprint and
  returns non-zero.
- WARNING: `LOCALAPPDATA` absence fallback.

### 5. Error-fingerprinting classification

The canonical failure shape is emitted by
`shared/runtime_config.py::build_failure_fingerprint`:

```python
{
  "stage": "<stage_name>",
  "code": "<CODE>",
  "message": "<human-readable>",
  "disposition": "FAIL",
  "fail_closed": "true",
}
```

`guest_deploy.py::_failure_fingerprint` adds a `timestamp` field
(ISO-8601 UTC); log parsers should accept either shape.

Known code prefixes:

| Prefix | Surface | Examples |
|---|---|---|
| `CFG_*` | Config resolution (`shared/runtime_config.py`) | `CFG_MODE_INVALID`, `CFG_MODE_CONFIG_MISMATCH`, `CFG_SYMLINK_REJECTED`, `CFG_PATH_MISSING`, `CFG_RUNTIME_MODE_MISMATCH` |
| `AO_CFG_*` | AO TOML validation (`services/assistant_orchestrator/src/entrypoint.py`) | The 13 constraints — see [configuration-management.md](configuration-management.md) §2 |
| `PA_*` | PA lifecycle (`services/policy_agent/src/entrypoint.py`) | `PA_START_FAILED` (fallback), measured-boot codes |
| `AO_*` | AO lifecycle | `AO_START_FAILED` (fallback), model-load codes |
| `UAT2_*` | Host activation preflights | `UAT2_PROMPT_FLOW_FAILED` |
| `P5_*` | Guest-runtime deploy (`launcher/guest_deploy.py`) | `P5_VM_START_FAILED`, `P5_GSI_DISABLED`, `P5_VSOCK_TOPOLOGY_INVALID`, `P5_GUEST_CHANNEL_NOT_READY`, `P5_BUNDLE_BUILD_FAILED`, `P5_COPY_BUNDLE_FAILED`, `P5_COPY_BOOTSTRAP_FAILED` |
| `P6_*` | Guest-deploy config preflight | `P6_POLICY_CONFIG_INVALID`, `P6_ORCH_CONFIG_INVALID` |
| `UAC_*` | Admin elevation (`launcher/__main__.py` / `vm_manager.py`) | `UAC_PROMPT_TRIGGERED`, `UAC_ELEVATION_DENIED` |
| `VM_*` | VM lifecycle | `VM_START_FAILED` |
| `GATEWAY_*` | Transport gateway | `GATEWAY_HANDSHAKE_FAILED` |
| `PROMPT_FLOW_*` | Host prompt-flow preflight | `PROMPT_FLOW_FAILED`, `PROMPT_FLOW_STORE_UNAVAILABLE` |
| `SESSION_STORE_*` | Session DB init | `SESSION_STORE_INIT_FAILED` |
| `LAUNCHER_*` | TUI crashes | `LAUNCHER_TUI_RUNTIME_ERROR` |

Adding a new code requires: pick a prefix (reuse if the surface fits;
create a new prefix only for a net-new subsystem), add a ledger entry
(Q1-1) that names the code and its trigger condition, and update this
section in the same commit.

### 6. Performance instrumentation

Current runtime observables that are logged or recorded:

- **Model generation**: tokens streamed are counted by the UAT2
  prompt-flow preflight (`token_count` field in
  `uat2_milestone2_prompt_flow.json`). No steady-state tokens/sec
  metric is emitted to the log today.
- **IPC**: no explicit per-frame latency logging. The gateway logs
  lifecycle events (handshake, stream start, stream end) with
  timestamps visible via `%(asctime)s`.
- **Rule engine** (`services/policy_agent/src/rule_engine.py`): no
  explicit timing — see [rule-engine.md](rule-engine.md) §11.

Performance-instrumentation is an acknowledged gap. A future hardening
could add a `performance` logger at DEBUG carrying tokens/sec,
IPC-roundtrip, rule-engine-latency. Deferred.

### 7. Health-check surfaces

- `TransportGateway.check_pa_status()` — returns a bool. Logs
  `"Boot-Phase-3: beginning PA handshake"` at INFO; surfaces
  ERROR on failure. Used by the host activation step 7a.
- `_run_uat2_prompt_flow_preflight` — returns a bool. Used by host
  activation step 7b.
- No standing periodic health-probe today; health is sampled only at
  activation time.

### 8. Evidence artifacts as audit surface

Evidence JSON files are the structured, machine-parseable companion
to the free-text log. Three artifacts are in play:

- `phase2_gates/evidence/uat2_real_runtime_activation.json` — host
  activation outcome. Steps dict + failure fingerprint on FAIL.
- `phase2_gates/evidence/uat2_milestone2_prompt_flow.json` —
  prompt-flow smoke test outcome. Session ID, request ID, token
  count, PGOV approval, bounded response excerpt.
- `phase2_gates/evidence/priority5_guest_deploy.json` — guest-deploy
  outcome. Bundle/bootstrap destinations, list of fingerprints on
  FAIL.

A "successful run" is two artifacts with `disposition: PASS` plus the
absence of any ERROR lines in `launcher.log`. A failed run is the
reverse: one or both artifacts with `disposition: FAIL` and a
matching ERROR line whose `code` matches the fingerprint's `code`.

### 9. Operator guidance

- **Normal run.** Watch for `✓` banners in the console; the launcher
  prints a `_step` line for each checkpoint and a success mark when
  it completes. On exit, `launcher.log` should end with
  `"Cleanup: complete"`.
- **Failed run.** The console carries a single `ERROR:` banner; the
  log tail carries the matching `ERROR`-level line and the evidence
  JSON carries the machine-readable fingerprint. Cross-reference the
  `code` against §5 → jump to the remediation in
  [deployment-verification.md](deployment-verification.md) §Recovery.
- **Grep strategy.** `Select-String "ERROR:" $env:LOCALAPPDATA\BlarAI\launcher.log`
  lists every fail-closed surface from a given run. `Select-String
  "\[(PA|AO|P5|P6|CFG|UAC|VM)_"` narrows to fingerprint codes.

## Recovery / Remediation Procedures

Observability is passive — it surfaces evidence rather than directly
restoring runtime state. Remediation therefore routes through the
corresponding subsystem's governance doc:

1. **Missing log file at `%LOCALAPPDATA%\BlarAI\launcher.log`.** The
   directory is auto-created by `logging.basicConfig` at
   `launcher/__main__.py:40-58`; if the file does not appear, check
   filesystem permissions on `%LOCALAPPDATA%\BlarAI` and ensure the
   process has write access. Re-run activation after resolving.
2. **`ERROR:` banner in console but no matching log line.** Indicates
   the `StreamHandler` fired before `FileHandler` was attached, which
   should be impossible given current `basicConfig` ordering. Capture
   the console transcript and file a governance ticket — this is a
   regression in boot-sequence integrity (GOV-15 precursor).
3. **Evidence JSON (`*_activation_evidence.json`,
   `uat2_prompt_flow.json`) absent after fail-closed.** The
   `_record_*_evidence` helpers at `launcher/__main__.py` write these
   before `sys.exit`. Absence suggests an exception escaped the helper;
   search the log tail for the stack trace. Treat the run as
   audit-incomplete and re-run.
4. **PA/AO logger silence during a confirmed denial.** The Policy
   Agent logs every `RuleEngineResult` deny at WARNING via
   `run_rule_engine`; if a known-deny CAR produces no log, suspect
   handler-filter configuration and cross-check
   [rule-engine.md](rule-engine.md) §Short-Circuit Evaluation.
5. **Log file growth rate anomaly.** `launcher.log` append-only. A
   sudden size spike almost always indicates a handler recursion or a
   tight-loop fail-closed retry; kill the launcher and inspect the
   last 200 lines for a repeating error fingerprint.
6. **Textual TUI swallowing logs.** During an interactive AO session,
   stderr is captured by Textual's display surface. Bypass by
   running with `BLARAI_HEADLESS=1` or tailing the file handler
   directly.

## Open Questions / Deferred Items

- **GOV-12-ADR-01 (ADR-absence).** No ADR governs logging format,
  severity taxonomy, or evidence-JSON schema. A future
  ADR-OBSERVABILITY would formalize the `build_failure_fingerprint`
  shape and the known code-prefix set as the authoritative audit
  surface.
- **GOV-12-PII-REDACT-01 (I-5).** No regex-based PII scrubbing in
  the log formatter today. Current privacy guarantee is
  by-construction (call sites do not pass user content). A
  logging-middleware with explicit scrub patterns would be a
  hardening. Deferred pending a concrete leakage finding.
- **GOV-12-ROTATION-01.** `launcher.log` appends indefinitely; no
  rotation policy. A `RotatingFileHandler` with size/day bounds is a
  trivial hardening; it was not adopted because `%LOCALAPPDATA%` on
  Windows is single-user and the log growth rate is low, but it is
  worth revisiting if production runs become long-lived.
- **GOV-12-METRICS-01.** No performance metrics logger (tokens/sec,
  IPC roundtrip). See §6.
- **GOV-12-HEALTH-PERIODIC-01.** No periodic health-probe surface;
  health is sampled only at activation. A future `/healthz`-style
  endpoint would be helpful for long-lived runs. Deferred.
- **GOV-12-BOOT-SEQUENCE-01.** The interplay between logging setup
  (lines 40-58) and subsequent imports (lines 197-217) is carefully
  ordered so that imported modules' loggers inherit the root
  config. This is implicit in `__main__.py` structure; a future
  `boot-sequence.md` (GOV-15) will document the ordering explicitly.
