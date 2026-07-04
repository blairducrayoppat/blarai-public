# Sprint 16 — Stream F: Coverage Audit
## Prioritized Real-Integrated-Path Gap List

**Audit scope:** `main` at HEAD `82a21e5`, BEFORE the Sprint-16 code builders
(A / B1 / B2 / D) merge their new tests. Where this wave is known to close a gap,
it is marked "closing in Sprint 16 (stream X)" rather than "open."

**Audit authority:** TEST_GOVERNANCE.md §2.7 (Coverage Mandate + fidelity ladder)
and SDV Sprint 16 §4 criterion #8.

**Fidelity ladder (§2.7 §4):**
- **Unit** — mocked seam; runs without services; `services/*/tests/`, `shared/tests/`, `launcher/tests/`
- **Integration** — real cross-service seam, loopback socket or real IPC; `tests/integration/` (slow-marked)
- **E2E / hardware** — model loaded, production posture; `tests/harness/` (hardware + winui markers)

**Layer-A baseline at audit date:** 2172 passed, 2 skipped, 15 deselected
(`pytest shared/ services/ launcher/ -m "not hardware and not winui and not slow"`)

---

## Per-Subsystem Coverage Table

| Subsystem | Has unit? | Has integration (real seam)? | Has E2E (model-loaded / GUI)? | Gap summary | Priority |
|---|---|---|---|---|---|
| **policy_agent** | YES — extensive (gpu_inference, adjudicator, rule_engine, ipc, jwt_minter, boot, cascade_stub, rate_resource) | YES — `test_p110_end_to_end.py` Groups B/C: real TCP loopback PA listener + live socket I/O; GPU mocked | NO — no on-chip test with real Qwen3-14B classify_car | Real model classify_car path never automatically tested; `test_gpu_inference.py` mocks OpenVINO | MED |
| **assistant_orchestrator** | YES — entrypoint, gpu_inference, context_manager, pgov, substrate, thinking_strip, tools, websearch | YES — `test_p110_end_to_end.py` Groups A/E/F (in-process, not cross-service socket); `test_prompt_round_trip_host_mode.py` (REAL AO IPC listener + real gateway, GPU stubbed) | PARTIAL — `test_sprint12_real_model.py` (hardware marker, real Qwen3-14B + real IPC, dev posture); boot-cascade smoke absent | Boot-cascade smoke (cert-mint → service handshake → preflight → prompt → tear-down) not automated — exactly the class that caused the Sprint-15 manual marathon; closing in Sprint 16 (stream D) | HIGH |
| **semantic_router** | YES — router, dual_gate_thresholds, constants | NO real-IPC integration test | PARTIAL — `test_real_model_latency.py::test_semantic_router_loads_and_classifies` (hardware; real bge-small on CPU) | No automated test of the real gateway→router routing path; the AO unit tests mock router classification | MED |
| **ui_gateway** | YES — session_store, transport, document_loader, document_loader_media, session_store_encryption, decrypt_resilience, constants; integration transport tests at `tests/integration/test_ui_gateway_ipc.py` (slow, real TCP) | YES — `test_ui_gateway_ipc.py`: real asyncio TCP server speaking MessageFramer; `test_prompt_round_trip_host_mode.py`: real TransportGateway → real AO listener | NO — no test of the real gateway connected to a real model-loaded AO over the production port, without GPU stub | The prompt round-trip test (ISS-10 fix) uses a GPU stub; the model-loaded round-trip is the next tier up; closing in Sprint 16 (stream D, boot-smoke) as a precursor | HIGH |
| **ui_shell (Textual TUI)** | YES — app, app_load_command, pgov_display, session_panel, streaming, think_parser, constants, baseline_streaming_snapshot | YES — `test_p114_ui_end_to_end.py` Groups A/C/D/E: real asyncio TCP servers + real BlarAIApp, mocked gateway for some groups | NO — no test of the TUI rendering against a real model-loaded backend | The `test_p114_ui_end_to_end.py` wires a mock gateway for prompt-dispatch tests; real gateway + model path is untested by automation | MED |
| **ui_winui (WinUI3 GUI)** | PARTIAL — `test_winui_backend.py` (Windows-only, named-pipe round-trip with scripted backend) | YES — `test_winui_input.py` + `test_winui_sprint12.py` (winui + slow markers): real WinUI exe + real named pipe + pywinauto (2 scenarios: dead-input fix + /external routing); scripted fake backend, no models | NO — no test of WinUI against a real model-loaded AO; the GUI harness uses a scripted fake backend, so the real AO rendering path (streaming, PGOV display, session list with quarantined rows, voice, document/provenance) is untested by automation | The harness's "dispatcher layer drives a fake gateway" gap named in §2.7; critical path (app-launch/connect, send-prompt→stream→render, PGOV display, session lifecycle, thinking/streaming) absent; closing in Sprint 16 (stream A, #621) | HIGH |
| **ui_backend (WinUI IPC dispatcher)** | YES — dispatcher, dispatcher_voice, error_sanitize, protocol; uses StubGateway and in-memory SessionStore | NO — no real cross-process test of the named-pipe RPC protocol against the live WinUI exe | NO | The dispatcher is tested with a StubGateway; the real gateway → dispatcher → WinUI round-trip is only exercised when the GUI harness runs (which uses a scripted stub, not the real dispatcher) | MED |
| **shared/security** (tpm_sealer, tpm_signer, audit_log, ceremony_preflight, dev_mode_guard, egress_guard, dek_envelope, field_cipher, cert_provisioning) | YES — comprehensive unit tests for each module; SoftwareSealer / stub-TPM round-trip in default suite; real-TPM tests slow-marked | NO automated integration test of the full boot security cascade (ceremony_preflight → cert load → mTLS handshake → per-boot key derivation) in a single automated run | NO on-hardware test of the real TPM ceremony path (seal/unseal with production CNG provider) in CI | The full Tier-2 boot security cascade is tested component-by-component but never as an integrated automated sequence; the Sprint-15 production live-verify found cert-mount failures that no test would have caught; boot-cascade smoke (stream D) partially closes this | HIGH |
| **shared/ipc** (vsock, protocol, message_framer) | YES — ipc_message_types, ipc_protocol, ipc_protocol_documents (unit, non-socket) | YES — `tests/integration/test_shared_ipc_transport.py`: real TCP loopback (dev_mode), mTLS round-trip with generated certs; `test_p110_end_to_end.py` Group B: real socket I/O | NO real AF_HYPERV (vsock) test; all integration tests use TCP loopback dev_mode=True | The real vsock (AF_HYPERV) guest↔host boundary is never tested by automation; #615 closes this in Sprint 17; no test can run in dev_mode that exercises the production AF_HYPERV socket | HIGH |
| **shared/models** (weight_integrity, manifest_signer, stage_production_manifest) | YES — test_weight_integrity (single-file check), test_manifest_signer, test_stage_production_manifest; all unit with temp files | NO — no integration test of `verify_weight_integrity` called at `load_model()` time across ALL manifest entries in both PA and AO `gpu_inference.py`; today's `load_model()` checks only `openvino_model.bin` | NO — no on-hardware test of the full weight sweep against the deployed model dir | The multi-entry sweep at load is the gap; closing in Sprint 16 (stream B, #106) | HIGH |
| **launcher** (boot cascade: admin check → VM state → PA start → AO start → prompt-flow preflight → gateway wiring) | YES — test_launcher (mocked), test_process_launch, test_vm_manager, test_guest_deploy, test_dev_mode_interlock, test_resolve_gateway_port | NO — the production boot sequence with real service start/stop, real port binding, real gateway handshake, and the prompt-flow preflight is NOT exercised by any automated test; all launcher tests mock every service at the class level | NO — no headless model-loaded boot-smoke | The exact failure class from Sprint-15 EA-4: real cert mount → real mTLS → real handshake → real prompt preflight — each seam mocked in the unit suite but burned the LA at a terminal; closing in Sprint 16 (stream D, #619 boot-cascade smoke) | HIGH |
| **voice** (engine, audio) | YES — test_engine (FakeWhisper + FakeKokoro; unit), test_audio | NO real-device integration test (no live microphone / speaker) | NO | Voice I/O is untested end-to-end; the integration with the AO streaming path (TTS on STREAM_TOKEN) has no automated test | MED |
| **Cross-seam: IPC routing (gateway port → AO vs PA)** | NO prior to Sprint 15 ISS-10 fix | YES — `tests/integration/test_prompt_round_trip_host_mode.py`: real gateway → real AO listener (stubbed GPU), asserts correct port resolution and no "Unsupported message type"; characterizes the misroute symptom directly | NO — model-loaded variant (real Qwen3-14B, production port) untested by automation | The stub-based integration test closes the regression lock; the model-loaded tier is the next gap; partially addressed by stream D boot-smoke | HIGH |
| **Cross-seam: boot wiring (launcher → services → preflight → gateway)** | NO (launcher mocks all services) | NO | NO | The boot cascade as a composed sequence — admin check, VM state, PA/AO start, handshake, preflight, prompt arrive — is NEVER exercised as a whole by automation; every step is individually mocked; closing in Sprint 16 (stream D) | HIGH |
| **Cross-seam: GUI against real backend (WinUI → dispatcher → real gateway → model)** | NO | NO | NO — the two-scenario winui harness uses a scripted stub; the full path (real WinUI → real named-pipe dispatcher → real gateway → model-loaded AO) has never been driven by automation | The most expensive gap for ongoing development: every GUI feature lands untested against the real model path; closing in Sprint 16 (stream A, #621) partially (stub tier extended; model-loaded tier defined + runbooked for later execution) | HIGH |
| **Security posture locks** (dev_mode=false, secure-by-default PGOV, test isolation guard, egress import guard) | YES — `test_secure_defaults.py` (shipped config), `test_root_test_isolation.py` (conftest guard), `test_no_external_egress.py` (import scan) | N/A — these are static/config locks | NO runtime posture test (production-mode boot with real certs/keys asserted in CI) | A runtime posture test (#600 / §2.5) is a tracked deliverable; the static locks exist but the dynamic guard (production posture at boot time, asserted programmatically) is absent | MED |
| **Weight integrity at load (in-process seam, PA + AO gpu_inference.py)** | PARTIAL — `test_gpu_inference.py` tests single-file verify but NOT the full manifest sweep in `load_model()` | NO integration test exercises `load_model()` → `verify_weight_integrity` → fail-closed on tampered/missing file | NO | Only `openvino_model.bin` is checked at load; other manifest entries are unchecked; closing in Sprint 16 (stream B, #106) | HIGH |
| **Guest-boundary IPC (AF_HYPERV vsock real VM)** | NO | NO — all IPC tests use dev_mode TCP loopback | NO | The real Hyper-V guest↔host socket is never tested; #615 before #598; Sprint 17 | HIGH |

---

## Prioritized Gap List — Sprints 17+

### HIGH priority (seams burned the project or gate-critical)

**GAP-1 — Boot-cascade smoke-to-preflight (headless, automated)**
The full boot sequence (cert mint → PA start → AO start → mTLS handshake → prompt-flow preflight → tear-down) has no automated headless test. Every component is unit-tested with mocks, but the composed sequence is verified only manually. Sprint-15 EA-4 required ten separate manual discoveries.
*Mapping:* `tests/integration/` or `launcher/tests/` new file; requires real service start (GPU stubbed), real port binding, real IPC. Ticket #619 (closing in Sprint 16, stream D — the lightweight smoke lock on the current cascade; the FULL production-mode integration test is Sprint 17).

**GAP-2 — GUI against real backend (WinUI → named-pipe → real gateway → model-loaded AO)**
The pywinauto harness uses a scripted stub backend. The real path — WinUI.exe → named-pipe RPC → ui_backend dispatcher → TransportGateway → real AO → Qwen3-14B → STREAM_TOKEN → WinUI render — has zero automated coverage. Every GUI-touching sprint implicitly relies on the LA clicking through the app.
*Mapping:* `tests/harness/test_winui_*`; requires built exe, real AO, real model. Ticket #621 (closing in Sprint 16, stream A — harness extended with critical-path scenarios and model-loaded tier defined + runbooked; model-loaded tier execution batched to a later dev-machine session).

**GAP-3 — AF_HYPERV real guest-boundary (vsock AF_HYPERV, not TCP loopback)**
All IPC integration tests use `dev_mode=True` (TCP loopback). The real Hyper-V guest↔host AF_HYPERV socket path — the actual production transport for the guest-mode deployment — has never been exercised by automation. The production topology relies on this path.
*Mapping:* `tests/integration/` new test requiring a running Alpine VM; must be marked `hardware`. Ticket #615 (Sprint 17, before #598).

**GAP-4 — Weight integrity sweep at load (all manifest entries, both PA and AO)**
`gpu_inference.py::load_model()` in both PA and AO checks only `openvino_model.bin` against the manifest. All other manifest entries (attention layers, etc.) are loaded without integrity verification. No test verifies that a swapped or missing `.bin` file causes `load_model()` to fail-closed.
*Mapping:* `services/policy_agent/tests/` + `services/assistant_orchestrator/tests/`; tests that pass a manifest with a wrong digest for one non-openvino_model.bin file and assert fail-closed. Ticket #106 (closing in Sprint 16, stream B — the multi-entry sweep at load).

**GAP-5 — Model-loaded prompt round-trip (full posture: real Qwen3-14B, production cert, real gateway)**
The `test_prompt_round_trip_host_mode.py` regression lock stubs the GPU (`_StubInference`). The real end-to-end — gateway → AO with Qwen3-14B loaded, production mTLS, real PGOV output validation — has only been run manually. Without automation, a regression in the streaming path, the PGOV leakage scan, or the thinking-strip filter will only surface at the LA's terminal.
*Mapping:* `tests/harness/test_sprint12_real_model.py` already covers partial AO turn path with real model + real IPC; gap is the full gateway→AO→prompt→PGOV→response chain in production posture. Complement with a model-loaded scenario in `tests/harness/` or extend the sprint12 test. Sprint 17+.

**GAP-6 — IPC routing regression lock (model-loaded, production ports)**
`test_prompt_round_trip_host_mode.py` locks the ISS-10 fix with a GPU stub. The model-loaded variant — real Qwen3-14B, production ports, real PGOV — is the next tier and is currently absent. A regression to the pre-fix wiring would manifest only under model-loaded conditions.
*Mapping:* Extend `tests/integration/test_prompt_round_trip_host_mode.py` with a `@pytest.mark.hardware` scenario using the real model. Sprint 17+.

**GAP-7 — Shared/security Tier-2 boot cascade integration (cert provision → mTLS → per-boot key derivation → audit log)**
Security components are individually unit-tested. No automated test exercises the full Tier-2 ceremony-to-boot chain: provision-signing-key → generate certs → boot → per-boot cert mint → mTLS handshake → TPM-signed audit record. The Sprint-15 production live-verify found failures in this chain that no test would have caught.
*Mapping:* A new integration test or harness scenario that walks the security boot sequence with real cert gen (temp CA), real mTLS, real SoftwareSealer (stand-in) or real TPM (hardware marker). Sprint 17+.

### MED priority (real gaps, not yet burned; second tier)

**GAP-8 — Semantic router cross-service routing path (AO dispatches to real router)**
The AO unit tests mock `SemanticRouter.classify()`. The real path — AO receives a prompt, calls the real bge-small router via the real ONNX runtime — is only tested by the `hardware`-marked `test_semantic_router_loads_and_classifies`, which tests the router in isolation, not inside an AO turn. A regression in the AO→router wiring would be invisible to the unit suite.
*Mapping:* Extend `test_sprint12_real_model.py` or a new `tests/integration/` file to verify the real router is called during an AO turn. Sprint 17+.
> **ANNOTATION (Sprint-18 C3, 2026-06-08 — SWAGR MINOR-5):** This GAP's premise is **known-false**. Sprint 18 verified (grep + the independent Auditor) that the AO **never calls `SemanticRouter.classify()` inside `_handle_connection`** — there is no AO→router wiring to regression-test. The router is a standalone, built-ahead component (its own code marks it "not a security boundary"), **DEFERRED** (not an integration gap to build now) until the first skill-dispatch handler lands (web-search, #577). LA-decided 2026-06-08. C3 landed `test_real_router_and_ao_turn_cross_service` — proving the *adjacent* router→AO path + documenting the gap — scored PARTIAL. Tracking: **#632**.

**GAP-9 — TUI (Textual ui_shell) against real gateway**
`test_p114_ui_end_to_end.py` Group D/E wires `BlarAIApp` with a mock gateway for prompt dispatch. The real shell-to-gateway path — BlarAIApp → real TransportGateway → real AO — is untested by automation. Streaming render, PGOV display, session persistence all rely on the LA launching the TUI manually.
*Mapping:* A `slow`-marked integration test that wires a real `TransportGateway` (against the stub-AO from `test_prompt_round_trip_host_mode.py`) and drives `BlarAIApp`. Sprint 17+.

**GAP-10 — ui_backend dispatcher against real WinUI (named-pipe IPC)**
`services/ui_backend/tests/test_dispatcher.py` uses `StubGateway` and in-memory store. The real named-pipe RPC protocol between the WinUI exe and the dispatcher is tested only by the `winui`-marked harness tests (which use the scripted backend, bypassing the real dispatcher). A regression in the dispatcher's named-pipe framing, streaming contract, or session-store wiring will only show up when the GUI harness (stream A) runs against the real dispatcher.
*Mapping:* A `winui`-marked test that wires the real `RpcDispatcher` behind the scripted pipe server and drives it from the WinUI. Sprint 17+ (depends on stream A's harness extension).

**GAP-11 — Voice end-to-end (audio capture → Whisper STT → AO prompt → Kokoro TTS → playback)**
Voice unit tests (`test_engine.py`, `test_audio.py`) use fake Whisper and Kokoro. The full round-trip — real microphone input → real Whisper ONNX → AO streaming reply → real Kokoro TTS → real audio output — has no automated path. The ISS-2 thinking-leak fix and the conversational voice mode shipped without end-to-end automation.
*Mapping:* A `hardware`-marked harness scenario using recorded PCM as a stand-in for live audio, driving the real engine. Sprint 17+; non-trivial (audio I/O is hard to stub deterministically).

**GAP-12 — Production-posture runtime guard (test that production boot asserts dev_mode=false)**
`test_secure_defaults.py` checks the shipped TOML config. `test_root_test_isolation.py` checks the conftest. Neither is a runtime test: no automated test boots BlarAI in production posture and asserts `dev_mode=False` at runtime. `TEST_GOVERNANCE.md §2.5` calls this out as a tracked deliverable (#600).
*Mapping:* `tests/security/test_production_posture.py` — a `slow`-marked test that starts the AO/PA with production config and queries their runtime state. Sprint 17+; depends on the boot-cascade smoke (GAP-1) as infrastructure.

### LOW priority (gaps exist but risk is lower)

**GAP-13 — Policy Agent real-model classify_car (on-chip)**
The PA unit suite mocks OpenVINO. No automated test loads the real Qwen3-14B classification pipeline and classifies a real CAR. The hardware latency harness (`scenarios.py`) does not include a PA classification scenario (only router, VLM, AO chat). A silent regression in the prompt formatter, the label parser, or the confidence threshold would not surface automatically.
*Mapping:* Add `pa_classify_latency` to `tests/harness/scenarios.py` and a corresponding `hardware`-marked test. Sprint 17+.

**GAP-14 — Dependency pin verification (hash-based, supply-chain)**
The six `pyproject.toml` files have no hash-pinning; a compromised dependency version could silently install. `test_no_external_egress.py` guards against importing a forbidden library but cannot detect a compromised version of an allowed one.
*Mapping:* Closing in Sprint 16 (stream C) — pins added; hash-verify where toolchain supports it.

---

## Cross-reference to Open Tickets

| Ticket | Description | Gaps addressed | Status |
|---|---|---|---|
| #619 | Production-parity boot-cascade lane | GAP-1, GAP-6 (partial) | Partially closing in Sprint 16 (stream D): key-transition + sealer-stand-in integration tests + lightweight boot-cascade smoke to preflight; full production-mode integration test is Sprint 17 |
| #621 | WinUI GUI automation harness | GAP-2 | Closing in Sprint 16 (stream A): harness extended to full critical-path list; model-loaded tier defined + runbooked (execution batched) |
| #106 | Full weight integrity (FUT-04) | GAP-4 | Advancing in Sprint 16 (stream B): multi-entry sweep at load (PA + AO); signed-manifest mechanism built + staged; PARTIAL close — on-chip ceremony + activation is a later batched session |
| #615 | Guest-boundary AF_HYPERV | GAP-3 | Sprint 17 (before #598) |
| #622 | Coverage audit (this document) | All gaps | This Sprint 16 stream F deliverable |
| #620 | Prompt-route integration + model-loaded preflight as boot gate | GAP-5, GAP-6 | Sprint 15 ISS-10 fix landed the regression lock (stub); model-loaded tier = Sprint 17+ |
| #600 | Production-posture test gate | GAP-12 | Sprint 17+; depends on GAP-1 infrastructure |

---

## Summary statistics

| Dimension | Count |
|---|---|
| Major subsystems mapped | 15 (12 named subsystems + 3 cross-cutting seams) |
| With unit tests | 14/15 (ui_backend partial; voice partial; all others YES) |
| With a real-integrated-path test (real socket / real IPC seam) | 7/15 |
| With E2E / model-loaded automation | 2/15 (semantic_router: hardware real-model latency; assistant_orchestrator: hardware Sprint-12 real-model IPC) |
| HIGH-priority gaps | 7 (GAP-1 through GAP-7) |
| MED-priority gaps | 5 (GAP-8 through GAP-12) |
| LOW-priority gaps | 2 (GAP-13, GAP-14) |
| Gaps closing in Sprint 16 (full or partial) | 4 (GAP-1: D; GAP-2: A; GAP-4: B; GAP-14: C) |

---

## Burn-down recommendation for Sprints 17–18

**Sprint 17 (the "Boot Cluster"):** GAP-3 (#615 AF_HYPERV real VM boundary), GAP-1 part 2 (full
production-mode boot integration test post-#615/egress), GAP-7 (security cascade integration),
GAP-12 (production-posture runtime guard). These form a coherent "boot + posture" cluster and are
the direct prerequisite for the #598 gate.

**Sprint 18 (pre-gate sweep):** GAP-5 + GAP-6 (model-loaded prompt round-trip in production posture),
GAP-8 (router cross-service), GAP-9 (TUI against real gateway). These are the "does the real system
work end-to-end, automation-verifiable, no LA at the terminal" sweep that makes the #598 gate audit
a scripted run rather than a manual marathon.

**Sprint 18+ (ongoing):** GAP-10 (dispatcher-WinUI), GAP-11 (voice E2E), GAP-13 (PA real-model
classify). These are real gaps but lower urgency while the air-gap-removal campaign is in flight.
