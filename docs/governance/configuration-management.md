# Configuration Management Governance

## Audience

**Primary**: developer — owns the TOML schema surface, the validation
path that enforces it, and the 13 range/enum constraints that the
production service fails closed on. Any addition of a config key,
change of a valid range, or shift of the validation call site flows
through this doc before merge.

**Secondary**: auditor (verifies fail-closed-startup invariance and
DEC-01..DEC-10 decision-record anchoring); operator (needs to
understand which TOML is authoritative in which deployment mode);
incident responder (reads the failure-fingerprint code set to localize
"why did the service refuse to start"). **Future agent** guidance sits
at the end of **Governance Content**.

## Prerequisites

- [STYLE.md](STYLE.md) — binding governance template.
- **DEC-01..DEC-10** (Task 4 Policy-Agent tuning decisions,
  recorded in `docs/POST_OPERATIONAL_MATURATION_LEDGER.md` Entries for
  Task 4). Cited here as peer decision-records; §3 clarifies the
  scope contrast — DEC-01..DEC-10 govern the Policy Agent, not the
  AO TOML surface enumerated in §2. **ADR-absence note**: no direct
  ADR or DEC anchors the 13 AO constraints; see **Open Questions**
  for the ADR-candidate gap.
- [ADR-011](../adrs/ADR-011-Policy-Agent-GPU-NPU-Retirement.md) — "All
  LLM inference on GPU." The `device = GPU` TOML constraint encodes
  this ADR; cited per STYLE.md's closest-relevant rule as the one
  ADR that a config constraint directly reflects.
- Peer governance docs: [gpu-runtime.md](gpu-runtime.md) (the device
  and speculative-decoding settings this schema enforces);
  [pgov-validation.md](pgov-validation.md) (the PGOV threshold
  constraint); [circuit-breaker.md](circuit-breaker.md) (the
  `max_new_tokens` constraint that bounds breaker reach).

## Source References

Canonical implementation spans the host launcher, shared runtime
helpers, the AO entrypoint, and the authoritative test-side enumeration
of the 13 constraints.

| Artifact | Path | Lines |
|---|---|---|
| Shared config-resolution helpers | `shared/runtime_config.py` | full file |
| `resolve_deployment_mode` precedence | `shared/runtime_config.py` | lines 85-102 |
| `resolve_service_config_path` (symlink reject, path-missing) | `shared/runtime_config.py` | lines 109-147 |
| `ConfigResolutionError` + fail-fingerprint | `shared/runtime_config.py` | lines 48-68 |
| AO `AssistantOrchestrator._resolve_config_path` | `services/assistant_orchestrator/src/entrypoint.py` | lines 424-430 |
| AO `_validate_config_data` (the 13 constraints) | `services/assistant_orchestrator/src/entrypoint.py` | lines 432-562 |
| Authoritative enumeration of the 13 constraints | `services/assistant_orchestrator/tests/test_entrypoint.py` | `TestAssistantOrchestratorConfigValidation` (line 666+) |
| AO-pinned defaults (post-validation constants) | `services/assistant_orchestrator/src/constants.py` | full file |
| Launcher artifact flow to guest VM | `launcher/guest_deploy.py` | full file |

## Governance Content

### 1. Lifecycle

Configuration flows from TOML on the host filesystem to a running
service in four stages:

1. **TOML authoring / commit** — `config/default.toml` (HOST mode) or
   `config/guest_runtime.toml` (GUEST mode) sits under each service
   root. Filenames are enforced by
   `shared/runtime_config.py::_expected_config_filename` (line 105)
   — mixing `default.toml` into a GUEST deployment is rejected with
   `CFG_MODE_CONFIG_MISMATCH` before any validation runs.
2. **Path resolution** — `resolve_service_config_path` (lines
   109-147) rejects symlinks (`CFG_SYMLINK_REJECTED`) and missing
   files (`CFG_PATH_MISSING`) before returning a path.
3. **Schema validation** — on AO `start()`, `_validate_config_data`
   (entrypoint.py lines 432-562) walks the TOML and enforces every
   one of the 13 constraints below. The first failing constraint
   raises `ConfigResolutionError` and `start()` returns a fail-
   closed fingerprint — the service never transitions to RUNNING.
4. **Application** — resolved values are loaded into the
   `AssistantOrchestrator` instance (`ResolvedOrchestratorConfig`
   dataclass) and read by `GPUInference`, `ContextManager`,
   `CircuitBreaker`, and the PGOV validator at request time.

Deployment mode is resolved deterministically in
`resolve_deployment_mode` (lines 85-102) with the precedence:
explicit argument → `BLARAI_RUNTIME_MODE` env var → default `host`.
This ordering is a DEC-01 alignment: the explicit argument wins so
that tests and CI can override without touching environment state.

### 2. The 13 TOML Constraints — Authoritative Enumeration

The ground-truth enumeration is
`TestAssistantOrchestratorConfigValidation` in
`services/assistant_orchestrator/tests/test_entrypoint.py`. **If the
table below diverges from the test suite, the test wins — update this
doc.** Per EA-2 Sprint 8 hardening, the test class exercises every
constraint with an out-of-range substitution and asserts a fail-closed
startup.

| # | Key | Section | Valid range | Failure code |
|---|---|---|---|---|
| 1 | `device` | `[gpu]` | case-insensitive `GPU` only | `AO_CFG_DEVICE_INVALID` |
| 2 | `priority` | `[gpu]` | int ∈ [1, 7] | `AO_CFG_PRIORITY_INVALID` |
| 3 | `max_new_tokens` | `[generation]` | int ∈ [1, 4096] | `AO_CFG_MAX_NEW_TOKENS_INVALID` |
| 4 | `temperature` | `[generation]` | float ∈ [0.0, 2.0] | `AO_CFG_TEMPERATURE_INVALID` |
| 5 | `top_k` | `[generation]` | int ∈ [0, 1000] | `AO_CFG_TOP_K_INVALID` |
| 6 | `top_p` | `[generation]` | float ∈ [0.0, 1.0] | `AO_CFG_TOP_P_INVALID` |
| 7 | `repetition_penalty` | `[generation]` | float ∈ [0.5, 2.0] | `AO_CFG_REPETITION_PENALTY_INVALID` |
| 8 | `response_depth_mode` | `[generation]` | enum {`concise`, `standard`, `detailed`} | `AO_CFG_RESPONSE_DEPTH_MODE_INVALID` |
| 9 | `vsock_cid` | `[ipc]` | int ∈ [0, 2³²−1] | `AO_CFG_VSOCK_CID_INVALID` |
| 10 | `vsock_port` | `[ipc]` | int ∈ [1, 65535] | `AO_CFG_VSOCK_PORT_INVALID` |
| 11 | `timeout_ms` | `[ipc]` | int ∈ [1, 120000] | `AO_CFG_TIMEOUT_INVALID` |
| 12 | `max_message_bytes` | `[ipc]` | int ∈ [1024, 1048576] | `AO_CFG_MAX_MESSAGE_BYTES_INVALID` |
| 13 | `cosine_similarity_threshold` | `[pgov]` | float ∈ [0.0, 1.0] | `AO_CFG_PGOV_THRESHOLD_INVALID` |

Additional mandatory keys enforced as presence (not range):
`runtime.deployment_mode`, `gpu.model_dir`, `generation.do_sample`,
`security.dev_mode`, and (when `dev_mode = false`)
`security.jwt_ca_cert_path` + `gpu.weight_manifest`. Optional keys:
`gpu.speculative_decoding_enabled` (bool), `gpu.draft_model_dir`
(non-empty string when present). These are documented here for
completeness but are not part of the 13-constraint enumeration that
`TestAssistantOrchestratorConfigValidation` is built around.

### 3. Task 4 DEC-01..DEC-10 — What They Govern and How They Relate

Task 4 locked ten production decisions in the Post-Operational
Maturation Ledger (DEC-01 through DEC-10). They are **Policy Agent
tuning decisions**, not AO runtime-config decisions. The
authoritative one-line summaries, transcribed from the ledger (see
`docs/POST_OPERATIONAL_MATURATION_LEDGER.md` Entry ~34 "Locked
Decisions Wired" and surrounding Task 4 entries):

- **DEC-01.** Number of Assistant Tokens `NAT = 3` for Policy Agent
  speculative decoding.
- **DEC-02.** Speculative-decode accuracy-rate collapse at context
  ≥ 16 K ACCEPTED AS-IS (graceful degradation, no code change).
- **DEC-03.** Policy Agent `max_context = 16384`.
- **DEC-04.** Task 4.5 (Context Band Extension) RETIRED (subsumed by
  Task 4.3's 7-band × 6-NAT matrix).
- **DEC-05.** `SDPA = ON` for the PA inference path.
- **DEC-06.** `prefix_caching = OFF` for the PA inference path.
- **DEC-07.** PA weight precision pinned at f16 for the ingest
  tensor path.
- **DEC-08.** PA `max_new_tokens = 10` LOCKED; `/no_think` MANDATORY
  in the PA chat template (ADR-012 §2.4).
- **DEC-09.** Deterministic Pre-filter Check rules wired via generate
  config (initial rule count), quality-gate pass at 0.925 agreement.
- **DEC-10.** DPC refinement + ESCALATE path LOCKED at 0.925
  agreement rate; authoritative PA decision-surface snapshot.

**Scope contrast.** The 13 AO TOML constraints in §2 above govern AO
runtime — sampling parameters, vsock addressing, PGOV threshold —
and DO NOT overlap with the PA-centric DEC-01..DEC-10 surface
except at the periphery:

- DEC-08's `max_new_tokens = 10` applies to PA only; the AO's own
  `max_new_tokens ∈ [1, 4096]` in §2 constraint 3 is an independent
  ceiling governed by the circuit-breaker (`MAX_OUTPUT_TOKENS`) and
  has no direct DEC entry.
- DEC-08's `/no_think` mandate is PA-only; the AO permits thinking
  mode (ADR-012 §2.4) and no TOML constraint enforces `/no_think`
  on the AO path.
- None of the vsock / IPC / PGOV-threshold constraints are
  DEC-governed today; they trace to ADR-009 (IPC surface) and the
  PGOV default (0.85) recorded in `shared/constants.py`.

**Governance implication.** A proposal to change an AO TOML
constraint does NOT require a Task-4 DEC amendment (those pin PA
decisions). It DOES require a new ledger entry that names the
constraint, the empirical justification, and an update to
`_validate_config_data`, the matching test in
`TestAssistantOrchestratorConfigValidation`, and §2 above — in the
same commit. A proposal to change DEC-01..DEC-10 follows the
amendment path documented in the originating Task 4 ledger entry
and is out of scope for this doc.

### 4. Fail-Closed Startup

The validation path is the sole gate between a TOML file on disk and
a running service. Every failure raises `ConfigResolutionError` with
a deterministic `code` / `message` pair suitable for log fingerprinting
(`shared/runtime_config.py` lines 48-68, `build_failure_fingerprint`).

The service will **not** start if:

- Any required section is missing (`AO_CFG_*_SECTION_MISSING`).
- Any value is out of range (the 13 constraints above).
- Runtime mode in TOML disagrees with the mode the service was
  launched under (`CFG_RUNTIME_MODE_MISMATCH`).
- Config path is a symlink (`CFG_SYMLINK_REJECTED`).
- Config path does not exist (`CFG_PATH_MISSING`).
- `dev_mode = false` and JWT CA path or weight manifest is missing.

There is no graceful-degradation path. A malformed config never
produces a "start with defaults" fallback — the service refuses to
start and surfaces the failure code. This is the privacy-mandate
alignment: fail-closed on boundary errors rather than guessing what
the operator meant.

### 5. Configuration Propagation to the Guest VM

The launcher is responsible for materializing the guest-facing TOML
inside the Hyper-V VM. `launcher/guest_deploy.py` performs the
artifact flow:

- Reads the host-authored TOML.
- Transforms mode-specific keys (e.g., path rewrites from host to
  guest conventions).
- Writes `config/guest_runtime.toml` inside the VM's deployment
  surface.
- Restarts the AO process inside the VM to pick up the new TOML.

From the AO's point of view, the guest TOML is indistinguishable from
any other TOML — the same validation path runs. The launcher is
trusted to produce a valid guest TOML; a malformed transform surfaces
as a `CFG_*` failure on AO restart, which the launcher logs and
reports to the host.

No config hot-reload path exists: every configuration change
requires a service restart. This is intentional — hot-reload
introduces mid-request configuration drift, which would violate the
per-request determinism properties that PGOV and the circuit breaker
rely on.

### 6. Secrets and Host-Only vs Guest-Facing Keys

TOML does not store secrets directly. The fields that touch secret
material are **path references**:

- `security.jwt_ca_cert_path` — path to the JWT CA certificate the
  UI Gateway uses to validate prompt-issued JWTs.
- `gpu.weight_manifest` — path to a manifest file that, per future
  Pluton integration (GOV-10 weight-integrity, Pluton-blocked),
  will pin weight hashes.

Both are required in production (`dev_mode = false`) and optional in
`dev_mode = true`. The secrets themselves live at the referenced
filesystem locations and are never loaded into TOML. Logs redact
path values that contain user-identifying segments; the config
validator does not dereference the paths beyond presence.

### 7. Persona Guidance

- **Developer.** When adding a new config key, the sequence is:
  (1) extend `_validate_config_data` with a range check, (2) add a
  matching out-of-range test to
  `TestAssistantOrchestratorConfigValidation`, (3) update §2 of this
  doc and the DEC-alignment table in §3 in the same commit. Skipping
  any step leaves a divergence that the next audit will catch.
- **Auditor.** The thirteen `AO_CFG_*_INVALID` codes are the complete
  fail-closed surface for generation / IPC / PGOV. The six
  `AO_CFG_*_MISSING` codes cover required-presence. A malformed TOML
  that does not produce one of these codes is a governance gap —
  file an ADR-candidate issue.
- **Operator.** If the AO logs `CFG_MODE_CONFIG_MISMATCH` at startup,
  the TOML filename (`default.toml` vs `guest_runtime.toml`) does not
  match the deployment mode. This is the most common misconfig after
  a fresh deploy. Second-most-common: `CFG_RUNTIME_MODE_MISMATCH`
  (the TOML's `deployment_mode` field disagrees with the env var).
- **Incident responder.** Every startup failure carries a
  deterministic code. Grepping launcher logs for `AO_CFG_` or `CFG_`
  prefix pins the failing constraint immediately; no runtime
  introspection is required.
- **Future agent.** Do not introduce a hot-reload path. The model
  (per-request determinism) depends on configuration being fixed for
  the lifetime of a service process. Hot-reload would require PGOV
  and breaker re-initialization mid-stream, which neither currently
  supports.

## Recovery / Remediation Procedures

1. **Failure code `AO_CFG_*_INVALID`.** Identified constraint is in
   §2. Fix the TOML value to the valid range and restart the service.
   No partial state persists — a failed startup leaves nothing to
   clean up.
2. **Failure code `AO_CFG_*_SECTION_MISSING`.** The named TOML
   section is absent. Consult the HOST `default.toml` or GUEST
   `guest_runtime.toml` exemplar in `services/assistant_orchestrator/config/`
   for the required section template.
3. **Failure code `CFG_SYMLINK_REJECTED`.** The config path resolved
   to a symlink. Replace with a regular file at the same path.
   Symlink support would enable a config-redirection prompt-
   injection vector that this check prevents.
4. **Failure code `CFG_RUNTIME_MODE_MISMATCH`.** The TOML's
   `runtime.deployment_mode` disagrees with the mode the service
   was launched under. Either the env var is wrong (fix via
   `BLARAI_RUNTIME_MODE=`) or the TOML is wrong (fix the field).
5. **Schema addition rollback.** If a new constraint shipped with
   an overly-tight range and legitimate configs started failing,
   the rollback is: revert the `_validate_config_data` hunk, revert
   the test, revert the §2 row — then ship a retuned range as a
   new DEC-amendment entry.

## Open Questions / Deferred Items

- **GOV-11-ADR-01 (ADR-absence).** No direct ADR governs runtime
  configuration, and — as §3 clarifies — Task 4's DEC-01..DEC-10
  govern the Policy Agent, not the AO TOML surface enumerated in §2.
  The 13 AO constraints therefore have neither an ADR nor a DEC
  anchor today; they trace to ADR-011 (`device = GPU`), ADR-009
  (IPC addressing), and to per-key rationale scattered across
  `_validate_config_data` review comments. A future ADR-RUNTIME-CONFIG
  (or a consolidated AO-config DEC entry) would formalize the
  amendment path. EA-2's `circuit-breaker.md` cites DEC-05 where no
  ADR exists — the precedent is DEC-anchoring; AO-config does not
  yet have an equivalent anchor to cite.
- **GOV-11-HOTRELOAD-01.** No hot-reload path. Documented as
  intentional in §5 and §7. Re-opening the question requires an
  ADR that explains how PGOV and breaker state would survive a
  mid-process config change — not trivial.
- **GOV-11-SCHEMA-VERSION-01.** No schema-version field in the TOML.
  Additive changes are compatible by virtue of TOML parsing (unknown
  keys are silently ignored — which is itself a mild risk). A schema
  version would enable a "your TOML is from a newer version than
  this binary" failure mode. Deferred pending the first non-additive
  change.
- **GOV-11-PLUTON-01.** `gpu.weight_manifest` is present in the
  schema today but the manifest format and verification path are
  Pluton-blocked (see weight-integrity.md, GOV-10). This doc pins
  the presence-only contract and defers format to GOV-10.
- **GOV-11-BOOT-01.** The config-resolution step's ordering relative
  to model load, vsock bind, and breaker initialization is implicit
  in the AO `start()` method. A future `boot-sequence.md (forthcoming
  / GOV-15)` will make the ordering explicit.
