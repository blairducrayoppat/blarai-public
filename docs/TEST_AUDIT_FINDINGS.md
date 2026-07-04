# Test Audit Findings

**Audit Type:** DOCS-ONLY qualitative audit — no production or test file modifications
**Task:** P5-Task-7
**Governance Reference:** `docs/TEST_GOVERNANCE.md`

### EA Index

| EA | Service Scope | Branch | Commit Baseline | Ledger Entry |
|----|--------------|--------|----------------|-------------|
| EA-1 | policy_agent | `feature/p5-task7-ea1-policy-agent-audit` | `88b330d` | Entry 39 |
| EA-1 Correction | policy_agent | `feature/p5-task7-ea1-audit-correction` | `488b198` | Entry 40 |
| EA-2 | assistant_orchestrator, semantic_router | `feature/p5-task7-ea2-ao-sr-audit-correction` | `6ab1ece` | Entry 41 |
| EA-3 | ui_gateway, ui_shell | `feature/p5-task7-ea3-ui-gateway-ui-shell-audit` | `85cae8b` | Entry 48 |
| EA-4 | shared, launcher, tests/integration | `feature/p5-task7-ea4-shared-launcher-integration-audit` | `b858919` | Entry 49 |
| EA-5 | synthesis (sections 5-6) | `feature/p5-task7-ea5-synthesis` | `a3419e9` | Entry 50 |

---

## Coverage Map

### policy_agent

#### Module Coverage Summary

| Production Module | Test File(s) | Overall Coverage | Coverage Level |
|-------------------|--------------|-----------------|----------------|
| `adjudicator.py` | `test_adjudicator.py`, `test_hybrid_adjudicator.py`, `test_integration_car_pipeline.py` | All public API covered. Both pure function and stateful pipeline tested. All 5 decision matrix rows verified. Integrity re-verification paths covered. | **COMPREHENSIVE** |
| `boot.py` | `test_boot.py` | 3 tests cover success, retry-then-succeed, hard-lock. Critical gaps below. | **THIN** |
| `car.py` | `test_car.py`, `test_integration_car_pipeline.py` | `build_car()` main paths covered. Hash determinism tested. Completeness tested. | **ADEQUATE** |
| `config_loader.py` | `test_config_loader.py` | All 4 loader functions with error paths. Includes real on-disk integration test. | **COMPREHENSIVE** |
| `constants.py` | None (implicit) | No dedicated test file. Constants verified implicitly via other modules. | **UNCOVERED (implicit only)** |
| `entrypoint.py` | `test_entrypoint.py` | Boot lock/retry, ordering constraint, runtime mode mismatch, config/model load fail-closed, JWT key validation covered. `validate_runtime_config()` and `stop()` not directly isolated. | **PARTIAL** |
| `gpu_inference.py` | `test_gpu_inference.py` | All public symbols covered across 7 groups (A–G). ADR-012 §2.4 governance assertions present. `DeterministicPolicyChecker` covered (Group G). | **COMPREHENSIVE** |
| `ipc.py` | `test_ipc.py` | All public symbols and lifecycle states covered across 6 groups (A–F). Transport-level round-trip tests included. | **COMPREHENSIVE** |
| `jwt_minter.py` | `test_jwt_minter.py` | All public symbols covered across 5 groups (A–E). JWT claim validation via `pyjwt.decode()`. Nonce uniqueness across 20 mints. Fail-closed paths for bad key files. | **COMPREHENSIVE** |
| `rule_engine.py` | `test_rule_engine.py`, `test_rate_and_resource_rules.py`, `test_integration_car_pipeline.py` | All 5 stages tested individually and in pipeline. Short-circuit behavior per stage verified. Backward-compat (3-stage) verified. Rate counter decoupling from ACL deny verified. | **COMPREHENSIVE** |

#### Coverage Gaps by Module

#### `boot.py` — THIN

| Gap | Impact |
|-----|--------|
| No test for exception thrown in `MeasuredBootStep.action()` (vs. `return False`). Only `return False` is tested. If an action raises, the catch block and `hard_locked` behavior are unverified. | Medium — boot robustness contract is incompletely specified by tests |
| No test for `BootState.failed_step` property. The property computes the first failed step from the boolean fields; this logic is untested. | Low |
| No test for `dev_mode` parameter effect. `dev_mode` is passed to boot but its influence on any step action behavior is untested at the unit level. | Low |
| No test for `MeasuredBootPolicy` with non-default `retry_delay_s`. The sleep function is injected (sleep_fn parameter), but no test varies the delay value. | Low |

#### `entrypoint.py` — PARTIAL

| Gap | Impact |
|-----|--------|
| `validate_runtime_config()` is not tested in isolation. It is exercised as a side effect of `start()` in some tests, but no test directly calls it and verifies every constraint individually. | Medium — validation contract partially verified only |
| `stop()` method not tested in isolation. A test reaches `stop()` via `start() → stop()` (happy path), but no test verifies `stop()` behavior when the service is not running, or when the listener fails to stop. | Low |
| `last_failure` dict is not inspected in all fail-closed tests. Two tests (`test_start_fails_closed_on_rule_config_failure`, `test_start_fails_closed_on_model_load_failure`) assert only `start() is False` and `running is False` — not the error code in `last_failure`. See Assertion Quality Findings for detail. | Low |

#### `constants.py` — UNCOVERED (implicit)

| Gap | Impact |
|-----|--------|
| No dedicated test file for `constants.py`. The values `PROBABILISTIC_CONFIDENCE_THRESHOLD = 0.75`, `ESCALATION_CONFIDENCE_RANGE = (0.50, 0.75)`, `JWT_VALIDITY_SECONDS = 5`, etc. are used in other tests but never directly asserted in a constants test. A constant value regression (e.g., accidental change to `0.80`) would not be caught until a downstream behavioral test fails — with no direct diagnostic signal. | Medium — regression detection for constant-value changes is indirect |
| `QWEN3_IM_END_TOKEN_ID` and `QWEN3_THINK_START_TOKEN_ID` are verified by `test_stop_token_ids_constants_defined` (active). No coverage gap for these constants. | Low |

#### `car.py` — ADEQUATE (minor gaps)

| Gap | Impact |
|-----|--------|
| No test for string `sensitivity` normalization. `test_car.py` tests string `verb` normalization (e.g., `"READ"` → `ActionVerb.READ`) but does NOT test string `sensitivity` normalization (e.g., `"INTERNAL"` → `Sensitivity.INTERNAL`). Both parameters accept strings per `build_car()`. | Medium — parity gap in normalization coverage |
| No test for `parameters_schema` field propagation through `build_car()`. The field is defined on `CanonicalActionRepresentation` but is not constructed or verified in any `test_car.py` test. | Low |

#### Exact Escalation Floor Boundary (0.50) Untested

**Constants:**
```python
PROBABILISTIC_CONFIDENCE_THRESHOLD = 0.75
ESCALATION_CONFIDENCE_RANGE = (0.50, 0.75)
```

**Coverage status:**

| Boundary Point | Value | Expected Decision | Test Location | Status |
|---------------|-------|------------------|---------------|--------|
| Above threshold | 0.90 | ALLOW | `test_hybrid_adjudicator.py::test_row2_both_allow` | ✅ Covered |
| Exact upper threshold | 0.75 | ALLOW (`≥` comparison) | `test_hybrid_adjudicator.py::test_confidence_exactly_at_threshold_allows` | ✅ Covered |
| Just below threshold | 0.7499 | ESCALATE | `test_hybrid_adjudicator.py::test_confidence_just_below_threshold_escalates` | ✅ Covered |
| Mid-escalation range | 0.60 | ESCALATE | `test_hybrid_adjudicator.py::test_row3_escalate_by_confidence` | ✅ Covered |
| Just above escalation floor | N/A | ESCALATE | Not tested | ⚠️ Gap |
| **Exact escalation lower boundary** | **0.50** | **ESCALATE or DENY?** | **Not tested** | ❌ **MISSING** |
| Just below escalation floor | 0.49 | DENY | `test_hybrid_adjudicator.py::test_confidence_below_escalation_floor_denies` | ✅ Covered |
| Minimum (fail-closed) | 0.0 (via error) | DENY | `test_hybrid_adjudicator.py::test_row5_npu_error_fail_closed` | ✅ Covered (via error path) |

**Critical gap:** `confidence == 0.50` is not tested.

The constant `ESCALATION_CONFIDENCE_RANGE = (0.50, 0.75)` uses Python tuple notation.
The boundary inclusion at `0.50` depends entirely on the `adjudicate()` implementation's
comparison operator (`>= 0.50` vs `> 0.50`). Since `0.49` → DENY and `0.60` → ESCALATE,
the exact behavior at `0.50` is currently unverified. A comparison typo (changing `>=` to `>`)
would not be caught by any existing test.

**Recommended action:** Add one test:
```python
def test_confidence_at_escalation_floor_escalates(self) -> None:
    """Confidence == 0.50 → ESCALATE (≥ lower bound inclusive)."""
    adj = self._make_mocked_adjudicator("ALLOW", 0.50)
    ctx = adj.adjudicate_car(_make_car())
    assert ctx.decision == AdjudicationDecision.ESCALATE
```
This test should be added to `test_hybrid_adjudicator.py::TestPipelineWithMockedNPU`.
**Not actioned in EA-1.**

#### RateLimiter Sliding Window Expiry Untested

`RateLimiter` uses a sliding window via `deque`. Tests verify:
- Within-budget allows ✅
- Budget-exhausted denies ✅
- Agent independence ✅
- Reset behavior ✅

**Gap:** No test verifies that requests older than `window_seconds` are evicted and do not
count against the budget. The sliding window expiry logic is the core behavioral invariant
of the rate limiter, yet it is tested only implicitly via the `reset()` method.

The `test_rate_and_resource_rules.py` file imports `time` but does not use it — suggesting
a time-based expiry test may have been intended but was not implemented.

**Recommended action:** Add a time-based sliding window expiry test to
`test_rate_and_resource_rules.py`. May require injecting a mock clock or using
`freeze_time` if available. **Not actioned in EA-1.**

### assistant_orchestrator

#### Module Coverage Summary

| Production Module | Test File(s) | Overall Coverage | Coverage Level |
|-------------------|--------------|-----------------|----------------|
| `circuit_breaker.py` | `test_circuit_breaker.py` | 7 tests across 3 classes. Token and depth cap paths tested at and under limit. Truncation message paths covered. | **ADEQUATE** |
| `constants.py` | None (implicit) | No dedicated test file. Values used implicitly through other module tests. | **UNCOVERED (implicit only)** |
| `context_manager.py` | `test_context_manager.py` | 20 tests across 8 classes. Full session lifecycle, Context Spotlighting, KV-cache tracking, FIFO eviction, stats. | **COMPREHENSIVE** |
| `entrypoint.py` | `test_entrypoint.py` | 10 tests. Config validation (2 of \~15 constraints), model load, handshake/prompt handling, streaming callback, malformed message fail-closed, JWT non-dev paths. | **PARTIAL** |
| `gpu_inference.py` | `test_gpu_inference.py` | 59 tests across 14 classes. Dataclasses, softmax, sampling, fail-closed, KV-cache, preemption, generation with mocks, chat template, thinking mode (ADR-012 §2.4). | **COMPREHENSIVE** |
| `pgov.py` | `test_pgov.py` | 54 tests across 10 classes. All 6 pipeline stages tested individually and integrated. PII (9 patterns, 7 tested), delimiter echo, tool-call allowlist, leakage scoring, fail-closed. | **COMPREHENSIVE** |

#### Coverage Gaps by Module

#### `circuit_breaker.py` — ADEQUATE

| Gap | Impact |
|-----|--------|
| No test for over-limit tokens. Only at-limit (`OUTPUT_TOKEN_CAP`) is tested; behavior when `record_tokens()` is called with a value exceeding the cap in a single call is unverified. | Low |
| No test for simultaneous token + depth trip. `BreakerState.tripped` is a property that ORs `token_tripped` and `depth_tripped`, but no test triggers both simultaneously. | Low |
| No test for `new_request()` reset behavior. `CircuitBreaker.new_request()` returns a fresh `BreakerState`, but no test verifies that subsequent state from a previous request is truly discarded. | Low |

#### `constants.py` — UNCOVERED (implicit)

| Gap | Impact |
|-----|--------|
| No dedicated test file. `OUTPUT_TOKEN_CAP`, `TOOL_CALL_DEPTH_CAP`, `PGOV_COSINE_THRESHOLD`, `DEFAULT_TEMPERATURE`, `DEFAULT_TOP_K`, and other generation/preemption constants are verified only implicitly. A constant-value regression (e.g., accidental change from `0.85` to `0.80` for PGOV cosine threshold) would not produce a direct diagnostic signal. | Medium |
| Stale re-exports `NPU_PRIORITY` and `NPU_KV_CACHE_PERSISTS` are present but have no test verifying correct mapping to GPU-era equivalents. See Stale Test Inventory → assistant_orchestrator. | Low |

#### `entrypoint.py` — PARTIAL

| Gap | Impact |
|-----|--------|
| Only 2 of \~15 TOML config validation constraints are tested (`deployment_mode`, `response_depth_mode`). Missing coverage for: `device` must be `"GPU"`, `priority` range, `model_dir` must exist, `max_new_tokens` bounds, `temperature` bounds, `top_k`/`top_p` bounds, `repetition_penalty` bounds, `vsock_cid`/`vsock_port` validity, `max_message_bytes` bounds, `pgov.cosine_similarity_threshold` bounds. | **High** — the config validation layer is the primary defense against misconfiguration, yet \~13 of \~15 constraints have no test |
| No test for `HEARTBEAT` message handling. `_handle_connection()` dispatches HEARTBEAT, HANDSHAKE, and PROMPT message types; only HANDSHAKE and PROMPT are tested. | Medium |
| `_pgov_reason_codes()` method untested. This method computes structured PGOV reason codes returned to the client; its output format is unverified. | Low |
| No test for `generate_text` returning an error result during `_handle_prompt_request`. Only success and PGOV rejection paths are tested; the case where inference itself fails mid-request is not covered. | Medium |
| `stop()` method not tested in isolation. Only exercised as cleanup after `start()` in the happy path. Behavior when stopping a not-running service is unverified. | Low |

#### `gpu_inference.py` — COMPREHENSIVE (with noted gaps)

| Gap | Impact |
|-----|--------|
| No test for `load_model()` success path (full model + speculative decoding draft model initialization). All mock-based generation tests set `_loaded = True` directly, bypassing actual load logic. Requires real OpenVINO runtime. | Medium — deferred to integration tests |
| No test for weight integrity validation during `load_model()`. The manifest SHA-256 verification logic is untested in isolation. | Medium |
| No test for `_build_generation_config()` method. This method translates `GenerationConfig` dataclass fields to OpenVINO GenAI `GenerationConfig`; the mapping is unverified. | Low |
| `_autoregressive_loop()` is legacy dead code (pipeline uses `_generate_from_prompt()` with `LLMPipeline`). No tests exist and none are needed unless the method is resurrected. | N/A — dead code |

#### `pgov.py` — COMPREHENSIVE (with minor gaps)

| Gap | Impact |
|-----|--------|
| No test for `CREDIT_CARD` PII pattern. The `_PII_PATTERNS` list includes `CREDIT_CARD` regex, but no test case exercises it. | Low |
| No test for `HEX_SECRET` PII pattern. Pattern defined in `_PII_PATTERNS` but no test case. | Low |

#### Exact PGOV Leakage Threshold (0.85) Untested

**Constant:** `PGOV_COSINE_THRESHOLD = 0.85` (from `services/assistant_orchestrator/src/constants.py`)

**Coverage status:**

| Boundary Point | Value | Expected Result | Test Location | Status |
|---------------|-------|----------------|---------------|--------|
| Well above threshold | 0.92 | Rejected (leakage) | `test_pgov.py::TestPGOVPipeline::test_leakage_with_injected_detector` | ✅ Covered |
| Well below threshold | 0.50 | Approved | `test_pgov.py::TestPGOVPipeline::test_leakage_below_threshold_passes` | ✅ Covered |
| **Exact threshold** | **0.85** | **Rejected or Approved?** | **Not tested** | ❌ **MISSING** |
| No chunks (skip leakage) | N/A | Score = 0.0, approved | `test_pgov.py::TestPGOVPipeline::test_no_chunks_skips_leakage` | ✅ Covered |
| Fail-closed (crash) | N/A | Score = 1.0, rejected | `test_pgov.py::TestLeakageDetectorWithMock::test_exception_returns_fail_closed` | ✅ Covered |

**Critical gap:** `cosine_similarity == 0.85` is not tested. The production code in
`_run_pipeline()` uses `>=` comparison for the leakage threshold. But this
inclusion/exclusion at the exact boundary is unverified.

**Recommended action:** Add one test with `mock_detector.check_leakage.return_value = 0.85`
and `cosine_threshold=0.85`, asserting `result.approved is False`.
**Not actioned in EA-2.**

### semantic_router

#### Module Coverage Summary

| Production Module | Test File(s) | Overall Coverage | Coverage Level |
|-------------------|--------------|-----------------|----------------|
| `constants.py` | None (implicit) | No dedicated test file. `CONFIDENCE_THRESHOLD`, `CONFIDENCE_MARGIN`, `DEFAULT_INTENT` verified implicitly through router tests. | **UNCOVERED (implicit only)** |
| `intents.py` | `test_router.py::TestIntentRoutes` | 5 tests validate route structure (non-empty, phrase counts, valid intents, skill targets). No test for `IntentRoute` frozen dataclass immutability. | **ADEQUATE** |
| `router.py` | `test_router.py` | 31 tests across 9 classes (11 unit, 20 integration). Fail-closed, input guards, classification, threshold behavior, custom routes, latency budget. | **COMPREHENSIVE** |

#### Coverage Gaps by Module

#### `constants.py` — UNCOVERED (implicit)

| Gap | Impact |
|-----|--------|
| No dedicated test. `CONFIDENCE_THRESHOLD=0.50` and `CONFIDENCE_MARGIN=0.04` are the production default gate values but are never directly asserted. A value regression would only be detected when classification behavior changes in integration tests. | Medium |

#### `intents.py` — ADEQUATE (minor gaps)

| Gap | Impact |
|-----|--------|
| No test for `IntentRoute` frozen dataclass immutability. The `@dataclass(frozen=True)` contract is not verified by any test. | Low |
| No test for phrase content quality or semantic diversity. `TestIntentRoutes::test_all_routes_have_phrases` checks count (≥ 5) but not that phrases are meaningfully distinct. | Low |

#### `router.py` — COMPREHENSIVE (with noted gaps)

| Gap | Impact |
|-----|--------|
| `_embed_raw()` private method not tested in isolation. Mean-pooling and L2 normalization logic is exercised only indirectly through `classify()`. A normalization bug would manifest as classification drift rather than a direct failure signal. | Low |
| No test for `load_model()` idempotency (calling `load_model()` twice in sequence). Behavior on repeated load is unverified. | Low |
| No test for `classify()` with loaded model but empty route set. Behavior when no centroids exist is unverified — could produce unexpected results. | Low |
| 20 of 31 tests require the ONNX model on disk (`requires_model` marker). CI environments without the model exercise only 11 unit tests, leaving classification logic untested. | Medium — acceptable for local-only project |

#### Dual-Gate Threshold and Margin Boundaries Untested

**Constants:**
```python
CONFIDENCE_THRESHOLD = 0.50
CONFIDENCE_MARGIN = 0.04
```

**Coverage status for dual-gate logic:**

The `classify()` method implements a two-gate classification:
1. **Absolute gate:** `best_similarity >= CONFIDENCE_THRESHOLD`
2. **Margin gate:** `best_similarity - second_best_similarity >= CONFIDENCE_MARGIN`

Both gates must pass for a non-OUT_OF_SCOPE result.

| Boundary Point | Tested? | Status |
|---------------|---------|--------|
| Similarity just above 0.50 with sufficient margin | Indirectly via `TestClassification` integration tests | ⚠️ Not explicitly tested |
| Similarity exactly 0.50 | Not tested | ❌ MISSING |
| Similarity 0.49 (below threshold) | Indirectly — gibberish test returns OUT_OF_SCOPE | ⚠️ Not explicitly tested |
| Margin exactly 0.04 between top-2 | Not tested | ❌ MISSING |
| Margin 0.03 (below margin) | Not tested | ❌ MISSING |

**Finding:** The dual-gate boundary behavior cannot be tested at exact values using the
integration approach (real embeddings produce unpredictable similarity scores). Unit-testing
the gate logic would require mocking `_embed_raw()` to produce controlled similarity values.
No such mock-based gate test exists.

**Recommended action:** Add a mock-based unit test for `classify()` that injects
pre-computed centroids and controlled embeddings to verify exact boundary behavior of
both gates. **Not actioned in EA-2.**

### ui_gateway

#### Module Coverage Summary

| Production Module | Test File(s) | Overall Coverage | Coverage Level |
|-------------------|--------------|-----------------|----------------|
| `constants.py` | None (implicit via `test_session_store.py` and `test_transport.py`) | No dedicated test file. | **UNCOVERED (implicit only)** |
| `session_store.py` | `test_session_store.py` | 7 test classes, \~25 tests. Schema (5), CreateSession (5), ListSessions (4), Turns (8), DeleteSession (4), ClearSessionTurns (3), SetActiveSession (2). All 8 public methods exercised against an in-memory SQLite DB; CASCADE delete and WAL mode verified via a file-backed fixture. | **COMPREHENSIVE** |
| `transport.py` | `test_transport.py` | 13 test classes, \~40 tests. Unit: StartupState (3), StreamToken (8), GatewayPGOVResult (4), ReasonCodes (3), TransportGatewayInit (3), CheckPaStatus (5), SendPrompt (3), StreamTokens (2), GetPGOVResult (1), ToolCallBuffer (4), Reset (3). Live IPC: LiveHandshake (2), LiveSendPrompt (2), LiveStreamTokens (3), LivePGOVResult (4), LiveErrorHandling (2). | **COMPREHENSIVE** (with caveats; see Boundary Violations) |

#### Coverage Gaps by Module

#### `constants.py` — UNCOVERED (implicit)

| Gap | Impact |
|-----|--------|
| No dedicated test file. `PA_HANDSHAKE_MAX_RETRIES=3`, `PA_HANDSHAKE_BACKOFF_BASE_S=1.0`, `PA_HANDSHAKE_TIMEOUT_S=5.0`, `PROMPT_RESPONSE_TIMEOUT_S=120.0`, `SESSION_TITLE_MAX_CHARS=80` are used but never asserted directly. `TOOL_CALL_BUFFER_MAX_TOKENS` is value-anchored through `test_buffer_overflow_raises` which imports and iterates against it, so a regression there would be detected. | Medium — retry/timeout regressions would only surface through integration runs |
| `STREAM_TOKEN_BUFFER_LIMIT=4096` gates the overflow-break path in `stream_tokens` (transport.py:545-550) and has no test exercising the overflow branch. A regression lowering the limit (or removing the check) would silently alter production behavior. | Medium |

#### `session_store.py` — COMPREHENSIVE (with minor gaps)

| Gap | Impact |
|-----|--------|
| `close()` method not exercised in a dedicated test. It is called only during the `store` fixture teardown; a regression breaking `close()` would not produce a direct diagnostic signal. | Low |
| `get_turns()` alias (lines 232-234) not directly tested; all tests use `get_session_turns()`. | Low |
| `set_active_session(session_id)` does not validate session existence — a nonexistent UUID silently deactivates all sessions and affects zero rows. No test asserts this edge. | Low |
| `add_turn()` with a nonexistent `session_id` relies on the SQLite FK CHECK for rejection (`PRAGMA foreign_keys=ON`); Python-side behavior on the resulting `IntegrityError` is not asserted. | Low |

#### `transport.py` — COMPREHENSIVE (with noted gaps)

| Gap | Impact |
|-----|--------|
| `_connect_hyperv()` (lines 391-411) has no test coverage in any mode. All existing tests use `dev_mode=True` (TCP loopback). Production AF_HYPERV path is entirely unverified at the unit level — deferred to integration. | Medium — acceptable for local-only project |
| `_open_prompt_transport()` private method not directly tested; only exercised via `send_prompt`. | Low |
| `send_prompt` "transport.send returned False" branch (lines 473-477) not explicitly tested. Existing tests either succeed (transport connects and sends) or have no transport (branch not entered). | Low |
| `send_prompt` generic `Exception` handler (lines 484-489) not tested. | Low |
| `stream_tokens` `STREAM_TOKEN_BUFFER_LIMIT` overflow break (lines 545-550) not exercised. | Medium — this is the primary fail-closed guard against runaway streams |
| `stream_tokens` malformed-message `continue` path (lines 536-540) not tested directly — a framer decode error during streaming would follow this branch. | Low |
| `stream_tokens` "unexpected message type" warning/ignore branch (lines 600-604) not tested. | Low |
| `check_pa_status` short-circuit when already connected (lines 258-260) not tested. A regression re-running handshake on a healthy connection would not be caught. | Low |
| `_attempt_pa_handshake` close-on-non-OPERATIONAL response (line 363) not asserted — `test_handshake_non_operational_response` verifies `_transport is None` but does not verify the transport's `close()` was invoked. | Low |

### ui_shell

#### Module Coverage Summary

| Production Module | Test File(s) | Overall Coverage | Coverage Level |
|-------------------|--------------|-----------------|----------------|
| `app.py` | `test_app.py` | 5 test classes, \~18 tests. Construction (8), ActionGuards (2 non-functional — see Assertion Quality), APIWiring (3 non-functional — see Assertion Quality), BootPhase3P113 (5), SessionReload (1). | **PARTIAL** |
| `constants.py` | None. `PGOV_DENIAL_TITLE` + `PGOV_REASON_LABELS` keyset verified in `test_pgov_display.py::TestPGOVPanelConstants`; `RESPONSE_SCROLL_BACK_LINES` verified in `test_streaming.py::TestStreamingDisplayConstants`. All other constants implicit only. | **UNCOVERED (partial)** |
| `pgov_display.py` | `test_pgov_display.py` | 2 test classes, \~13 tests. Constants (3), Logic (10). | **ADEQUATE** |
| `session_panel.py` | None. `SessionListItem` is constructed once in `test_app.py::TestSessionReload`; all `SessionPanel` public methods are untested. | **UNCOVERED (indirect only)** |
| `streaming.py` | `test_streaming.py` | 2 test classes, \~8 tests. Constants (1), Logic (7). | **ADEQUATE** |

#### Coverage Gaps by Module

#### `constants.py` — UNCOVERED (partial)

| Gap | Impact |
|-----|--------|
| No dedicated test. Values not asserted anywhere: `SESSION_PANEL_WIDTH_PCT=25`, `PROMPT_MAX_CHARS=4096`, `TITLE_PLACEHOLDER="New session"`, all `KEY_*` bindings, `STREAM_REFRESH_INTERVAL_MS=50`, `CURSOR_BLINK_INTERVAL_MS=500`, `PGOV_PANEL_BORDER_STYLE`, `BOOT_STATUS_POLL_INTERVAL_S=1.0`, `BOOT_BANNER_TEXT`, `BOOT_FAILED_TEXT`. A regression changing `PROMPT_MAX_CHARS` would not produce a direct diagnostic signal. | Low-Medium |
| `PGOV_REASON_LABELS` values are not asserted individually — `test_reason_labels_are_human_readable` only checks each label is a `str` of length >5. A typo rewriting "PII detected and redacted" to a nonsense string would pass. | Low |

#### `session_panel.py` — UNCOVERED (indirect only)

| Gap | Impact |
|-----|--------|
| Zero dedicated test file. `SessionPanel.refresh_list`, `create_new_session`, `delete_current_session`, `select_session`, `on_mount`, and the `active_session_id` property are untested. The widget wraps synchronous SessionStore calls in `asyncio.to_thread()`; a regression omitting `to_thread()` (which would block the Textual event loop) would not be caught by any test. | Medium — the widget is small but has non-trivial async wiring |
| `SessionListItem.compose()` exercised only indirectly through `TestSessionReload`; no direct assertion on the rendered `Label` text format (`{title}  [dim]({turns})[/dim]`). | Low |

#### `app.py` — PARTIAL

| Gap | Impact |
|-----|--------|
| `compose()` not tested (Textual runtime required; acceptable — deferred to P1.14 integration tests under `tests/integration/test_p114_ui_end_to_end.py` with `slow` marker). | N/A — deferred |
| `action_submit_prompt()` body not tested. The PGOV-denied branch (lines 405-418, including `flush_tool_call_buffer(pgov_approved=False)` + `add_turn(... "denied" ...)`), the PGOV-approved branch (lines 419-436, including `flush_tool_call_buffer(pgov_approved=True)` + approved-token render + `add_turn(... "approved" ...)`), and the `RuntimeError` / generic `Exception` handlers (lines 438-445) are entirely unexercised. | **High** — this is the central user-facing handler and the three branches carry distinct persistence + display semantics |
| `_ensure_session()` not tested — neither the "active session exists" branch nor the "create + set-active + refresh" branch has unit coverage. | Low |
| `action_new_session()` and `action_delete_session()` not tested. | Low |
| `on_input_submitted()` not tested. | Low |
| Boot poll attempt-markers display progression (lines 253-285) is not exercised. Both `_GatewaySuccessStub` and `_GatewayFailedStub` return from `check_pa_status` after a single `await asyncio.sleep(0)`, so the while-loop either exits immediately or executes at most one iteration without traversing the `HANDSHAKING` attempt ticks. The `_write_boot_banner` progress updates (attempt 2/3, attempt 3/3) are never observed. | Medium |
| `_configure_boot_logger()` re-entry guard (lines 93-96, returns existing logger when a `FileHandler` for the same path already exists) not unit-tested; tests use a fresh `tmp_path` per case so the re-entry path is never hit. | Low |

#### `pgov_display.py` — ADEQUATE (with assertion-quality issue)

| Gap | Impact |
|-----|--------|
| `hide()`'s display-reset behavior is effectively unverified — the sole test that targets it (`test_hide_sets_display_none`) contains an assignment in place of an assertion. See Assertion Quality Findings. | Medium — documented as assertion-quality issue |
| No test for a denial result with `reason_codes=[]` (empty list); the rendered panel's behavior in that edge case is unverified (the current code emits a title and sanitized-text line but no reason bullets). | Low |

#### `streaming.py` — ADEQUATE

| Gap | Impact |
|-----|--------|
| `_render_buffer()` private method not directly exercised — tests inspect `display._buffer` state rather than the rendered output. | Low |
| `append_token(token="")` → `_append_text("")` early return (lines 74-75) not tested. | Low |
| `is_streaming` semantics for tool-call tokens not asserted — `test_tool_call_token_written_directly` does not verify `_streaming` is unchanged. See Assertion Quality Findings. | Low |

### shared

#### Module Coverage Summary

| Production Module | Test File(s) | Overall Coverage | Coverage Level |
|-------------------|--------------|-----------------|----------------|
| `constants.py` | None (implicit) | No dedicated test file for the 50+ shared constants spanning 9 categories (memory ceiling, NPU DEPRECATED, trust boundary, latency budgets, circuit breakers, model specs, security defaults, VM provisioning, vsock wiring). Values are used implicitly through consumer modules. | **UNCOVERED (implicit only)** |
| `crypto/jwt_validator.py` | `test_jwt_validator.py` | 38 tests across 8 classes (A–H). NonceStore TTL + GC, EpochTracker, frozen dataclass result, factory method, all 5 validation stages independently, end-to-end mint→validate round-trip, epoch revocation scenarios, legacy pure function. | **COMPREHENSIVE** |
| `ipc/protocol.py` | `test_ipc_protocol.py` | 28 tests across 6 groups (A–F). MessageType enum membership, AdjudicationRequest / AdjudicationResponse dataclass round-trip + frozen, MessageFramer encode/decode including size enforcement, typed request/response/error/heartbeat encoders. | **ADEQUATE** (with gaps) |
| `ipc/vsock.py` | `test_ipc_transport.py` | 34+ tests across 8 groups (A–H plus Group I for `_extract_cn` + `peer_cn`). Dataclass construction, SSL context creation, transport I/O round-trip over TCP loopback, listener lifecycle, mTLS round-trip, production fallback, peer-CN extraction. | **COMPREHENSIVE** (boundary caveats; see Boundary Violations) |
| `models/weight_integrity.py` | `test_weight_integrity.py` | 14 tests across 3 groups (A–C). `compute_sha256`, `load_manifest` parsing and error paths, `verify_weight_integrity` end-to-end. | **COMPREHENSIVE** |
| `runtime_config.py` | `test_runtime_config.py` | 5 tests across 4 classes. Happy-path HOST / GUEST, symlink rejection, missing file, mode mismatch. | **PARTIAL** |
| `schemas/car.py` | None (indirect via `test_jwt_validator.py` + policy_agent tests) | No dedicated test file. `CanonicalActionRepresentation` public surface (`canonical_hash()`, `is_complete()`) and the `ActionVerb` / `Sensitivity` / `AdjudicationDecision` enums plus `DecisionArtifact` are exercised only through consumer tests. | **UNCOVERED (indirect only)** |

#### Coverage Gaps by Module

##### `constants.py` — UNCOVERED (implicit)

| Gap | Impact |
|-----|--------|
| No dedicated constants test. Values that gate operational behavior across services are never directly asserted: `COSINE_SIMILARITY_THRESHOLD=0.85`, `MAX_OUTPUT_TOKENS=4096`, `MAX_TOOL_CALL_DEPTH=5`, `VSOCK_PORT=50000`, `VSOCK_SERVICE_GUID`, `ORCHESTRATOR_VM_ID`, `ORCHESTRATOR_VM_NAME`, `SECURE_BOOT`, `VBS_ENABLED`, `TPM_PRESENT`, `FAIL_CLOSED`, `MMAP_READ_ONLY`, and every latency-budget constant. A value regression would not produce a direct diagnostic signal. | Medium |
| `TARGET_MODEL_OV_PATH`, `DRAFT_MODEL_OV_PATH`, `PA_OV_PATH`, and `SEMANTIC_ROUTER_ONNX_PATH` path strings are not asserted anywhere. A typo changing any model directory path would produce a model-load error at runtime rather than a direct test signal. | Low |
| `PA_DEVICE="GPU"` and `AO_DEVICE="GPU"` (post-ADR-011 device constants) are not directly asserted. A regression flipping either back to `"NPU"` would be caught only when service-level config validation happens to notice the mismatch. | Low |

##### `crypto/jwt_validator.py` — COMPREHENSIVE

No material coverage gaps identified. All public surfaces (`NonceStore`, `EpochTracker`, `JWTValidationResult`, `AgenticJWTValidator`, legacy `validate_agentic_jwt`) are exercised across success and failure paths. Minor observations:

| Gap | Impact |
|-----|--------|
| `NonceStore.clear()` is covered, but the interaction `clear()` → `check_and_add(same_nonce)` race-free guarantee under concurrent threads is not tested. The underlying `threading.Lock` is trusted; concurrency regression would be undetectable. | Low |
| `EpochTracker.__init__(initial_epoch=...)` is only exercised with 0 and 5; no test covers very large initial epochs (e.g. near `sys.maxsize`). | Low |

##### `ipc/protocol.py` — ADEQUATE (with gaps)

| Gap | Impact |
|-----|--------|
| Six UI-gateway convenience encoders are untested at the unit level: `encode_handshake_request`, `encode_handshake_response`, `encode_prompt_request`, `encode_stream_token`, `encode_pgov_result`, `encode_generation_complete`. `MessageType` enum values for these are verified via `test_expected_types_exist`, but the encoders themselves are exercised only through `tests/integration/test_p114_ui_end_to_end.py` under the slow marker. A regression dropping or renaming a payload field (e.g. omitting `is_thinking` from `encode_stream_token`) would pass the shared REGRESSION-scope suite. | Medium — protocol-layer regressions deselected from default scope |
| `MessageFramer.decode()` `UnicodeDecodeError` origin is not distinguished from `JSONDecodeError` — both surface as the same "Malformed JSON" error message. Not exercising non-UTF-8 payload bytes separately means a regression altering the decode error branch would not be caught. | Low |
| `decode_request` / `decode_response` wrong-type rejection is tested with only a single alternative message type each (HEARTBEAT and ERROR respectively). Other cross-combinations are not exhaustively covered. | Low |

##### `ipc/vsock.py` — COMPREHENSIVE (with boundary caveats)

| Gap | Impact |
|-----|--------|
| `VsockTransport.connect()` AF_HYPERV (non-dev_mode) success path is not reachable in tests without a Hyper-V VM. Only the fail-closed branch is covered by `test_transport_connect_no_mtls_production_fails`. Acceptable — deferred to integration / runtime. | N/A — deferred |
| `VsockListener.accept()` AF_HYPERV success path equally unreachable. Acceptable. | N/A — deferred |
| `_recv_exact()` partial-read loop (where `recv()` returns fewer bytes than requested across multiple calls) is not directly tested; the loop iterates when the server writes in chunks, which does not happen in any test. | Low |
| `create_client_ssl_context` / `create_server_ssl_context` — the `ValueError` branch (malformed PEM content that parses far enough for `load_cert_chain` to raise `ValueError`) is not distinguished from `ssl.SSLError` or `OSError`. Nonexistent-path test covers only `OSError`. | Low |

##### `models/weight_integrity.py` — COMPREHENSIVE

No material coverage gaps. Observations:

| Gap | Impact |
|-----|--------|
| `compute_sha256(chunk_size=...)` custom chunk-size parameter is not directly exercised; all tests use the default 65536. | Low |
| `load_manifest` success path validates key/value stringness, but does not assert that digests strictly match `^[0-9a-f]{64}$` — a malformed digest (e.g. non-hex characters) would pass load and fail only on comparison. The function's contract is "normalize to lowercase"; it does not validate the hex-64 shape. | Low |

##### `runtime_config.py` — PARTIAL

| Gap | Impact |
|-----|--------|
| `resolve_service_root()` is **not tested at all**. Neither the normal-Python `Path(module_file).resolve().parents[1]` branch nor the PyInstaller `sys._MEIPASS` frozen-bundle branch has any test. This function determines the config directory for every service in a frozen launcher bundle. | **High** — a PyInstaller-frozen regression would manifest only at production launcher start, never in unit tests |
| `resolve_deployment_mode()` is **not tested at all**. Its three-tier precedence (explicit arg → `BLARAI_RUNTIME_MODE` env var → HOST default) has zero coverage. | **High** — deployment-mode selection is the primary control for host vs. guest service configuration |
| `parse_deployment_mode()` is not directly tested. Whitespace normalization, mixed-case handling, explicit invalid-mode rejection with `CFG_MODE_INVALID` are unverified at the unit level (only indirectly tested via `resolve_deployment_mode` which itself is untested). | Medium |
| `build_failure_fingerprint()` not tested. The function constructs the `{stage, code, message, disposition, fail_closed}` dict used by the launcher and services for fail-closed evidence. | Low |
| `ConfigResolutionError`'s `code` vs. `message` dataclass field separation (inherited from `ValueError`) is not directly asserted in isolation. Covered indirectly through assertion of `exc_info.value.code` in the symlink / mode-mismatch / missing-file tests. | Low |
| Two existing tests (`test_symlink_rejected`, `test_symlink_guard_message_contains_path`) use `pytest.skip` when the test host cannot create symlinks. On unelevated Windows shells this reduces the effective coverage of `CFG_SYMLINK_REJECTED`. This is acceptable but worth explicit acknowledgment. | Low |

##### `schemas/car.py` — UNCOVERED (indirect only)

| Gap | Impact |
|-----|--------|
| No dedicated test file. `canonical_hash()` determinism under field permutation, `is_complete()` boolean semantics for each partial-field combination, the UTC timestamp default factory, and the `request_id` required-field enforcement are all exercised only through consumer tests (`services/policy_agent/tests/test_car.py::build_car`; `shared/tests/test_jwt_validator.py::_make_decision`). A regression adding or reordering fields inside `canonical_hash()`'s `json.dumps` dict would change output hashes silently — consumer tests would fail with hash-mismatch, but with no direct diagnostic isolating the schema change. | Medium |
| `ActionVerb`, `Sensitivity`, and `AdjudicationDecision` enum membership plus string round-trips are not directly asserted at the shared level. | Low |
| `DecisionArtifact` Pydantic validators — `confidence` bounds `0.0 ≤ x ≤ 1.0`, `expiry_seconds` default 5, `issuer` default `"policy_agent"` — are untested directly. A regression loosening `confidence` bounds or altering the JWT TTL default would not be caught. | Medium |

### launcher

#### Module Coverage Summary

| Production Module | Test File(s) | Overall Coverage | Coverage Level |
|-------------------|--------------|-----------------|----------------|
| `__main__.py` | `test_launcher.py` | 7 tests against `main()` with every external dependency mocked. Happy path, UAC elevation (accepted / denied), PA start failure, AO start failure, VM start failure, handshake preflight failure. | **PARTIAL** |
| `guest_deploy.py` | `test_guest_deploy.py` | 4 tests. `_validate_vsock_topology` against committed evidence; `_build_bundle` missing-file error; `deploy_guest_runtime` success (with 9 patches); `deploy_guest_runtime` VM-start failure. | **THIN** |
| `vm_manager.py` | `test_vm_manager.py` | 23 tests across 6 classes. `VMState` enum, `get_vm_state` PowerShell paths, `start_vm` happy / unknown / failure, `stop_vm` happy paths, `is_admin` ctypes paths, GSI check, `copy_file_to_vm` success / failure / missing-source. | **ADEQUATE** (with noted gaps) |

#### Coverage Gaps by Module

##### `__main__.py` — PARTIAL

| Gap | Impact |
|-----|--------|
| Launcher-level `ConfigResolutionError` branch (lines 289-294) — raised when `resolve_deployment_mode()` returns a deterministic failure — has no test. | Medium |
| Prompt-flow preflight failure branch (lines 599-613) not tested. `test_handshake_failure_is_fatal` returns False at handshake; no test drives past handshake into the prompt-flow stage to verify the `PROMPT_FLOW_FAILED` fingerprint and the fail-closed exit. | **High** — prompt-flow preflight is a first-class UAT2 gate |
| `_run_uat2_prompt_flow_preflight()` is entirely untested in isolation. The internal `_execute()` coroutine, best-effort preflight-session cleanup, evidence-JSON write, and exception-handler fingerprint logic have zero direct coverage. | **High** — evidence-recording correctness is unverified |
| `_record_activation_evidence()` and `_record_prompt_flow_evidence()` helpers are never exercised directly. Their env-var precedence (`BLARAI_ACTIVATION_EVIDENCE_PATH`, `BLARAI_PROMPT_FLOW_EVIDENCE_PATH`) and relative-path resolution are unverified. | Medium |
| PA `ConfigResolutionError` branch (lines 397-414) and AO `ConfigResolutionError` branch (lines 462-479) — service construction failure before `.start()` — have no tests. | Medium |
| SessionStore init failure branch (lines 522-535) not tested. | Medium |
| TUI-crash exception handler (lines 643-656) not tested; the `LAUNCHER_TUI_RUNTIME_ERROR` fingerprint format is unverified. | Low |
| `_cleanup()` atexit handler (lines 230-250) not tested. Its service-stop / store-close / VM-stop order and guard conditions (`_policy_agent_service is not None and running`) are unverified. | Medium |
| `_vm_was_started` bookkeeping (set True only if the VM transitioned from non-RUNNING) is not asserted anywhere. A regression where cleanup always stops the VM (even a user-started one) would not be caught. | Medium |
| `SESSION_DB_PATH` empty → in-memory `:memory:` fallback branch (lines 514-517) not tested. | Low |

##### `guest_deploy.py` — THIN

| Gap | Impact |
|-----|--------|
| `_validate_vsock_topology` has **zero** failure-path coverage. Eight distinct failure branches (missing evidence file, non-JSON evidence, non-PASS disposition, `vm_id` mismatch, `service_guid` mismatch, `vsock_port` mismatch, `connection_successful=False`, `tcp_ip_used=True`) are all untested. A regression introducing a new field check or renaming an existing one would silently regress. | **High** — vsock topology is the only gate preventing deployment onto a misconfigured VM |
| `_validate_guest_runtime_configs` has zero failure-path coverage — neither PA-invalid nor AO-invalid branches are exercised independently; the happy path is reached only indirectly via the fully-mocked success test. | **High** — guest-mode config correctness is the secondary gate |
| `_build_bundle` success path (including `include_models=True` with full `_MODEL_DIRS` fan-out) not tested. The single success test patches `_build_bundle` wholesale. | Medium |
| `_zip_directory` recursive walk behavior not tested. File inclusion, relative-path correctness inside the archive, and directory-exclusion semantics are unverified. | Medium |
| `deploy_guest_runtime` GSI-disabled, vsock-topology-invalid, guest-runtime-config-invalid, copy-probe failure, copy-bundle failure, and copy-bootstrap failure branches are all untested. The success test patches every external call to return True. | Medium |
| `_parse_args()` argparse plumbing untested. The `--exclude-models` inversion (`include_models = not args.exclude_models`) is unverified. | Low |
| Module-level `main()` is untested (CLI invocation path). | Low |

##### `vm_manager.py` — ADEQUATE (with noted gaps)

| Gap | Impact |
|-----|--------|
| `request_elevation()` — the Windows ShellExecuteW UAC invocation — has **zero** direct coverage. `test_launcher.py::test_requests_elevation_when_not_admin` patches `request_elevation` wholesale, so the function's > 32 success condition and its `AttributeError` / `OSError` except branch are never exercised. | **High** — elevation is the primary gate protecting every Hyper-V operation |
| `start_vm` polling-timeout branch (lines 172-182, VM never reaches RUNNING within `VM_START_TIMEOUT_S`) not tested. A regression introducing an infinite loop or off-by-one in the timeout arithmetic would not be caught. | Medium |
| `stop_vm` polling-timeout branch (lines 221-230, VM never reaches OFF) not tested. | Medium |
| `stop_vm` non-force (`force=False`) branch not tested. | Low |
| `_run_ps` `subprocess.TimeoutExpired` branch and `FileNotFoundError` branch not tested. Both produce the `(-1, "", "…")` sentinel which callers interpret as failure. | Medium |
| `copy_file_to_vm` retry loop — the `retries=3` / `retry_delay_s=2.0` sequence — is untested. `test_copy_file_to_vm_failure` asserts `ok is False` but does not verify that all three attempts occurred; a regression short-circuiting the loop would not be caught. | Medium |
| `copy_file_to_vm` `create_full_path=False` branch not tested. | Low |
| `is_guest_service_interface_enabled` error branch (PowerShell returns non-zero exit code) not tested. | Low |
| `get_vm_state` `Starting` / `Saved` / `Paused` recognized enum values are not directly tested; only RUNNING, OFF, one `Suspended` → UNKNOWN path, empty, and error are covered. | Low |
| `ensure_vm_running` is a single-line wrapper around `start_vm`; coverage is adequate via `start_vm` tests but the wrapper itself is not directly exercised. | Low (deferred) |

### integration

The `tests/integration/` cluster has no dedicated production directory. Each test file exercises cross-service code paths that span multiple service packages and shared libraries.

#### Per-File Cross-Service Surface Mapping

| Test File | Cross-Service Paths Exercised | Coverage Adequacy |
|-----------|-------------------------------|-------------------|
| `test_p110_end_to_end.py` (9 groups, \~55 tests; module-level `pytestmark = pytest.mark.slow`) | **Group A** — full in-process P1 Core Loop with mocked models: `semantic_router.router` + `assistant_orchestrator.gpu_inference` + `assistant_orchestrator.pgov` + `policy_agent.car` + `policy_agent.adjudicator` + `policy_agent.rule_engine` + `policy_agent.jwt_minter` + `shared.crypto.jwt_validator`. **Group B** — same loop routed through real TCP loopback via `shared.ipc.vsock` + `shared.ipc.protocol` + `policy_agent.ipc.PolicyAgentListener`. **Group C** — Fail-Closed across the IPC boundary (connection refused, listener stopped mid-session, handler exception, default-deny fallback). **Group D** — structural preemption: `GenerationResult` preemption-field propagation + `policy_agent.constants.NPU_PRIORITY` vs `assistant_orchestrator.constants.NPU_PRIORITY` ordering. **Group E** — PGOV pipeline integration (`validate_output` + `context_manager` delimiter constants + tool-allowlist). **Group F** — JWT lifecycle across service boundary (signature, expiry, epoch revocation, nonce replay, CAR-hash mismatch, wrong-key rejection, IPC round-trip). **Group G** — latency field presence on dataclasses. **Group H** — CAR / AdjudicationResponse / MessageFramer / CARPromptFormatter serialization identity. **Group I** — `HybridAdjudicator` full pipeline against a stub `PolicyGPUInference("dummy_dir")`. | **ADEQUATE** — Groups A, B, F, I provide deep IPC + JWT + adjudication coverage; Groups D, G are structural-only (dataclass field presence). Real preemption, real latency budgets, and real model inference are intentionally out of scope (models mocked). |
| `test_p114_ui_end_to_end.py` (6 groups, \~23 tests; module-level `pytestmark = pytest.mark.slow`) | **Group A** — `ui_gateway.transport.TransportGateway` handshake + prompt + streaming over `shared.ipc.protocol` framed on an `asyncio.start_server` loopback. **Group B** — `ui_gateway.session_store.SessionStore` SQLite CRUD **in isolation** (no second service). **Group C** — tool-call buffer + TCP streaming round-trip (3 socket-backed tests + 3 in-process state tests). **Group D** — `TransportGateway` state transitions + `ui_shell.app.BlarAIApp` boot-phase-3 gating with stubbed `query_one`; one test drives a real `asyncio.start_server` for handshake propagation. **Group E** — `ui_shell.pgov_display.PGOVPanel` rendering in isolation + `action_submit_prompt` with mocked gateway (one test is cross-service via mock, five are in-process PGOVPanel-only). Standalone test at end asserts `STREAM_TOKEN_BUFFER_LIMIT` constant presence. | **PARTIAL** — the TCP-backed handler tests exercise the `ui_gateway` ↔ asyncio-server wire path convincingly. Significant subset of tests (Group B in full, parts of C / D / E, standalone constant) exercises no cross-service interaction and belongs in service-level unit-test directories. See Boundary Violations → integration. |

#### Cross-Service Surface Gaps

| Cross-Service Path | Currently Exercised? | Gap |
|--------------------|---------------------|-----|
| `ui_gateway` + `policy_agent` over IPC (gateway requests authorization from PA) | No | Neither integration file drives the gateway against a live `PolicyAgentListener`. The gateway's orchestrator peer is simulated by a hand-rolled asyncio TCP echo server in `test_p114`; PA handshake / authorization flow is not exercised end-to-end. |
| `ui_shell` + `policy_agent` (UI triggers adjudication) | No | No integration test drives the UI → gateway → orchestrator → PA sequence. |
| `policy_agent` + `assistant_orchestrator` + `semantic_router` three-way IPC | Partial | Only `test_p110` Group B drives PA over real sockets; Orchestrator and Router are exercised in-process (not through vsock). |
| Boot-Phase-3 → prompt-flow → PGOV denial across all three layers | No | `test_p114` Group D exercises boot-phase-3 with a stubbed gateway; `test_p110` exercises PGOV with in-process `validate_output`; neither integrates boot → prompt → PGOV against a live gateway. |
| `launcher/__main__.py::_run_uat2_prompt_flow_preflight` | No | No integration test imports or drives this helper. |
| `launcher.guest_deploy.deploy_guest_runtime` end-to-end (minus Hyper-V) | No | Guest-deploy is covered only by in-file unit tests with heavy patching; no integration test exercises the full `_build_bundle → copy → evidence` sequence even against a tmp_path mock. |
| `shared.ipc.vsock` mTLS over real sockets in a multi-service composition | Partial | `shared/tests/test_ipc_transport.py::TestVsockMTLS` covers mTLS round-trip in isolation (a boundary violation — see Boundary Violations → shared). No integration test exercises mTLS under the full PA↔gateway topology. |

#### Pre-Existing Skips in Scope

Neither integration file contains a `pytest.skip`, `pytest.mark.skip`, or `pytest.importorskip`. Both carry `pytestmark = pytest.mark.slow` at module level, causing deselection under REGRESSION and UNIT scopes per `docs/TEST_GOVERNANCE.md` §1. They are selected only under FULL or SLOW scopes.

---

## Stale Test Inventory

### policy_agent

Items in this section are not functional defects but represent terminology violations,
redundancy, or test artifacts that no longer reflect current architecture naming.

#### Stale Nomenclature — Post-ADR-011 NPU → GPU Renaming

**ADR-011 context:** All LLM inference was moved to GPU; the NPU was retired from the P1
Core Loop. The production class was renamed from `NPUInference` to `PolicyGPUInference`.
Test files that were created before this rename still use "NPU" in identifiers.

| Location | Stale Identifier | Correct Replacement | Severity |
|----------|-----------------|--------------------|----|
| `test_adjudicator.py` | `_make_npu_stub()` helper | `_make_gpu_stub()` | Minor |
| `test_hybrid_adjudicator.py` | `_make_npu_stub()` helper | `_make_gpu_stub()` | Minor |
| `test_hybrid_adjudicator.py` | `TestPipelineWithNPUStub` class name | `TestPipelineWithGPUStub` | Minor |
| `test_integration_car_pipeline.py` | `TestEndToEndWithNPUStub` class name | `TestEndToEndWithGPUStub` | Minor |
| `test_integration_car_pipeline.py` | Docstring: `"The NPU stub is Fail-Closed"`, `"using the real PolicyGPUInference stub"` noted as "NPU stub" | `"GPU stub"` | Minor |

> **Note:** These are cosmetic/terminology violations. The underlying test logic is correct —
> all references use `PolicyGPUInference` at the implementation level. No test behavior is
> affected. The risk is confusion for future maintainers reading class names that say "NPU"
> when the architecture has retired the NPU.

#### Partial Redundancy — `test_adjudicator.py` vs. `test_hybrid_adjudicator.py` Group I

`test_adjudicator.py` contains 5 tests on the pure `adjudicate()` function:
- `test_rule_deny_overrides_npu_allow`
- `test_both_allow`
- `test_npu_error_fail_closed`
- `test_npu_low_confidence_escalates`
- `test_npu_deny_label`

`test_hybrid_adjudicator.py` Group I (`TestAdjudicatePureFunction`) contains 4 overlapping
tests on the same pure function:
- `test_rule_deny_overrides_npu`
- `test_both_allow`
- `test_npu_error_deny`
- `test_npu_escalate`

**Finding:** `test_adjudicator.py` is functionally superseded by Group I of
`test_hybrid_adjudicator.py`. The Group I tests use more explicit assertion patterns
(e.g., checking `deterministic_pass` fields). The standalone file adds marginal value
(one additional test: `test_npu_deny_label`) but creates maintenance duplication — any
API change to `adjudicate()` requires updates in two files.

**Disposition candidate:** Consolidate `test_adjudicator.py` into
`test_hybrid_adjudicator.py::TestAdjudicatePureFunction` and delete the standalone file.
Add the missing `test_npu_deny_label` scenario to Group I before deletion. **Not actioned
in EA-1** — requires test modification, out of scope for DOCS-ONLY milestone.

### assistant_orchestrator

**ADR-011 context:** All LLM inference moved to GPU; NPU retired from P1 Core Loop.
The AO production file was renamed from `npu_inference.py` to `gpu_inference.py` (Task 5).
Several test identifiers and docstrings still reference "NPU".

| Location | Stale Identifier | Correct Replacement | Severity |
|----------|-----------------|--------------------|----|
| `test_gpu_inference.py::TestGenerationWithMock` | Class docstring: `"Full generation pipeline with mocked NPU inference"` | `"Full generation pipeline with mocked GPU inference"` | Minor |
| `test_gpu_inference.py::TestPreemptionDetection` | Class docstring: `"Timing anomaly detection for NPU preemption (ADR-010: PA on GPU)"` | `"Timing anomaly detection for GPU preemption"` | Minor |
| `test_gpu_inference.py::TestInferenceErrors::test_infer_exception` | Mock side effect: `RuntimeError("NPU fault")` | `RuntimeError("GPU fault")` | Minor |

> **Note:** These are cosmetic/terminology violations. The test logic is correct —
> all references use `OrchestratorGPUInference` at the implementation level. The stale NPU
> strings appear only in docstrings and mock exception messages.

### semantic_router

No stale items identified. The semantic router was not affected by the NPU → GPU rename
and contains no references to retired architectural concepts.

### ui_gateway

No stale items identified. The service was introduced at P1.11, post-ADR-011, and contains
no references to retired NPU-era architecture, no dead imports, and no superseded architectural
assumptions.

### ui_shell

No stale items identified. The service was introduced at P1.12, post-ADR-011, and contains no
NPU references, no dead imports, and no superseded naming.

(Observation, non-finding: `P1.11` / `P1.12` markers appearing in module docstrings are
historical phase provenance, not stale architectural language; no audit action warranted.)

### shared

No material stale items identified in the shared test suites. Test files correctly use
post-ADR-011 production class names (`PolicyGPUInference`, `OrchestratorGPUInference`) and
contain no NPU-era helper identifiers.

Observations considered and rejected as out-of-audit-scope (production code, not test code):

- `shared/constants.py` retains NPU-era constants (`NPU_SCHEDULING_MODEL`,
  `NPU_PARALLELISM_RATIO`, `NPU_PA_PRIORITY`, `NPU_ORCH_PRIORITY`, `NPU_KV_CACHE_PERSISTS`)
  explicitly marked DEPRECATED per ADR-011 via docstrings. `NPU_SUBSTRATE_PRIORITY`
  remains live because the NPU is retained as a candidate for non-LLM workloads
  (USE-CASE-002/003) — not stale.
- `shared/schemas/car.py` module docstring line 8 (`NPU-resident probabilistic classifier`)
  and `DecisionArtifact.probabilistic_pass` field docstring (`Whether the NPU
  probabilistic classifier approved`) are stale post-ADR-011 in production code. Shared
  **tests** do not propagate this language; no test-side audit action warranted. The
  production-docstring drift should be addressed outside the Task 7 audit scope.

### launcher

No material stale items identified in launcher test suites. Launcher tests were authored
post-P1.5 and use current identifiers throughout.

Observation (non-finding, production code only): `launcher/__main__.py` top-of-file docstring
step 4 reads "Start Assistant Orchestrator service (NPU)" — stale per ADR-011 (AO runs on
GPU). This appears in the production module docstring; launcher **tests** do not reproduce
the "NPU" language. No test-side audit action warranted.

### integration

**Post-ADR-011 stale identifiers in `tests/integration/test_p110_end_to_end.py`:**

| Location | Stale Identifier | Correct Replacement | Severity |
|----------|-----------------|---------------------|----------|
| Module docstring, line 12-14 | `"All NPU / ONNX models are MOCKED"` | `"All GPU / ONNX models are MOCKED"` | Minor |
| `_make_npu_allow()` helper (line 133) | Function name + docstring `"Simulated NPU ALLOW result"` | `_make_gpu_allow()` with `"Simulated GPU ALLOW result"` | Minor |
| `_make_npu_deny()` helper (line 140) | Function name + docstring `"Simulated NPU DENY result"` | `_make_gpu_deny()` with `"Simulated GPU DENY result"` | Minor |
| `_make_adjudication_handler()` parameter `npu_result` (line 162) + inline bindings in Groups A, B, F | Parameter name and local variables | Rename to `gpu_result` | Minor |
| `TestPreemptionSignalPropagation` class docstring (line 802-808) | `"NPU preemption"`, `"real NPU preemption requires hardware"` | `"GPU preemption"` / `"real GPU preemption requires hardware"` | Minor |
| `test_priority_ordering_structural` (lines 866-875) | Imports `NPU_PRIORITY as PA_PRIORITY` and `NPU_PRIORITY as ORCH_PRIORITY` from `services.policy_agent.src.constants` and `services.assistant_orchestrator.src.constants`. Per EA-1 / EA-2 findings, these names remain as stale re-exports in the service constants modules. The integration test propagates the stale nomenclature via its import aliases. | After the service-level re-exports are renamed, update imports to the current names. | Minor |
| Group D docstring (line 803-808) | `"real NPU preemption requires hardware"` | `"real GPU preemption requires hardware"` | Minor |
| Scattered variable bindings (`npu_result`, `npu_allow`, `npu_deny`) across Groups A, B, F, H, I | Local-variable names. | Rename to `gpu_result`, etc. | Minor |

> **Note:** The underlying test logic is correct — `_make_npu_allow` constructs a
> `GPUClassificationResult` via the current production class name. Stale identifiers
> appear only in helper names, docstrings, and local bindings. Risk is maintenance
> confusion for future readers: a reader encountering `_make_npu_allow` might assume
> NPU inference is architecturally relevant in the P1 Core Loop when ADR-011 explicitly
> retired it.

**`tests/integration/test_p114_ui_end_to_end.py`:** No stale items identified. The UI
service cluster was introduced post-ADR-011 and contains no NPU references.

---

## Assertion Quality Findings

### policy_agent

#### Missing Error Code Assertions in Fail-Closed Tests

**Pattern:** Tests that verify fail-closed behavior in `test_entrypoint.py` assert only
`start() is False` and `running is False`, omitting inspection of `service.last_failure`.
The `last_failure` dict carries the structured error code (`"code"` key) that is the primary
diagnostic for operational triage. Asserting only the boolean outcome means a code regression
that changes the error code (e.g., `PA_RULE_ENGINE_INIT_FAILED` → `PA_GENERIC_FAILURE`) would
pass the test silently.

**Affected tests:**
- `test_start_fails_closed_on_rule_config_failure` — asserts `start() is False`, `running is False`. Missing: `service.last_failure["code"]` assertion.
- `test_start_fails_closed_on_model_load_failure` — same pattern.

**Contrast:** `test_start_non_dev_fails_closed_when_jwt_key_missing` DOES assert
`service.last_failure.get("code") == "PA_CFG_JWT_KEY_PATH_NOT_FOUND"` — this is the
correct pattern and should be applied consistently.

**Recommended action:** Add `last_failure["code"]` assertion to the two tests above to
match the pattern established by the JWT key missing test. **Not actioned in EA-1.**

#### Incomplete Step-Field Assertions in Boot Success Test

**Test:** `test_boot.py::test_run_measured_boot_success_sets_ready`

The test asserts `state.ready is True`, `state.hard_locked is False`, and
`state.attempt_count == 1`. It also verifies the step call ORDER via a `calls` list.

**Gap:** The test does NOT assert that individual step-completion boolean fields
(`state.attestation_verified`, `state.weights_verified`, `state.model_loaded`,
`state.rule_engine_loaded`, `state.listener_started`) are each `True` after a full
successful boot. If a step sets the wrong boolean field (e.g., a typo in the step's
`state_field` name in `MeasuredBootStep`), the test would still pass because only
`state.ready` is checked at the end.

**Recommended action:** Add assertions for each of the 5 step-specific boolean fields in
the success test. **Not actioned in EA-1.**

#### Weak Assertion in `test_adjudicator.py::test_npu_error_fail_closed`

The test asserts `decision.decision == AdjudicationDecision.DENY`. It does not assert:
- `decision.deterministic_pass is True` (rule engine passed before the NPU error)
- `decision.probabilistic_pass is False`
- `decision.confidence == 0.0`

These fields are fully asserted in `test_hybrid_adjudicator.py::TestPipelineWithMockedNPU::test_row5_npu_error_fail_closed`, so the behavioral contract is covered in aggregate. However, the standalone `test_adjudicator.py` test provides incomplete assertion coverage for its scenario.

This finding is secondary to the Partial Redundancy finding in Stale Test Inventory — if
`test_adjudicator.py` is consolidated into `test_hybrid_adjudicator.py`, this gap is
resolved automatically.

### assistant_orchestrator

#### Missing Error Code Assertion in Fail-Closed Test

**Pattern (same as PA):** AO entrypoint tests that verify fail-closed behavior assert
only `start() is False` and `running is False`, omitting `service.last_failure["code"]`.

**Affected test:**
- `test_start_fails_closed_on_model_load_failure` — asserts `start() is False` and
  `running is False`. Missing: `service.last_failure["code"]` assertion.

**Contrast:** Within the same file, `test_start_fails_closed_on_runtime_mode_mismatch`
and `test_start_fails_closed_on_invalid_response_depth_mode` DO assert
`service.last_failure.get("code")` — this is the correct pattern and should be applied
to the model load failure test. **Not actioned in EA-2.**

#### Weak Assertions in Circuit Breaker Tests

**Test:** `test_circuit_breaker.py::TestTokenBreaker::test_at_limit_trips`

The test asserts `state.token_tripped is True` and `state.tripped is True` but does NOT
assert `state.depth_tripped is False`. A hypothetical bug that sets both flags when only
the token cap is reached would pass the test.

Similarly, `TestDepthBreaker::test_at_limit_trips` asserts `state.depth_tripped is True`
but does not assert `state.token_tripped is False`.

**Recommended action:** Add complementary negative assertions to both at-limit tests.
**Not actioned in EA-2.**

#### Untested PII Patterns (CREDIT_CARD, HEX_SECRET)

Two of nine `_PII_PATTERNS` entries in `pgov.py` have no corresponding test case:
- `CREDIT_CARD` — regex for 13–16 digit sequences
- `HEX_SECRET` — regex for 32+ hex character strings

These patterns are defined in production code and executed in the PGOV pipeline but their
regex correctness is unverified by any test. A regex bug (e.g., over-matching or
under-matching) would be undetected.

**Recommended action:** Add test cases to `TestPIIDetection` for both patterns.
**Not actioned in EA-2.**

### semantic_router

`TestConfidenceThresholdBehavior` uses extreme parameter values (threshold=0.99, 0.01;
margin=0.99, 0.0) to verify gate behavior. No test uses the production default values
(`CONFIDENCE_THRESHOLD=0.50`, `CONFIDENCE_MARGIN=0.04`) to verify that the actual
deployed configuration produces expected classification behavior.

A misconfiguration of the default values (e.g., changing `CONFIDENCE_THRESHOLD` from
0.50 to 0.05) would not be caught unless it causes classification behavior change
detectable by `TestClassification` — which uses the defaults implicitly.

**Recommended action:** Add a test that constructs a router with the production default
constants and verifies expected classification at a known decision boundary.
**Not actioned in EA-2.**

### ui_gateway

#### Trivially-True Assertion in `test_server_disconnect_during_stream`

**Test:** `test_transport.py::TestLiveErrorHandling::test_server_disconnect_during_stream` (line 945)

```python
tokens = [t async for t in gw.stream_tokens("sess-1")]
# Should get partial token before stream ends
assert len(tokens) >= 0  # may get 1 token or 0 depending on timing
```

The final assertion is **trivially true** for any list — `len()` on a list is always `>= 0`.
The test confirms only that the code does not raise, not that the disconnect is handled
gracefully per the stated purpose. A regression in which `stream_tokens` raises after a server
disconnect is weakly caught (only via an uncaught exception propagating out of the
comprehension), and the test asserts nothing about the shape of the result.

**Recommended action:** Replace with a deterministic assertion — either assert `tokens == []`
when the disconnect happens before any token is sent (by synchronizing the server handler), or
assert `len(tokens) in {0, 1}` with an accompanying note. **Not actioned in EA-3.**

#### Missing Field Assertions in Tool-Call Buffering Test

**Test:** `test_transport.py::TestLiveStreamTokens::test_stream_tokens_buffers_tool_calls`

The test verifies text tokens are yielded and tool-call tokens are buffered but does not assert
`tokens[0].is_tool_call is False` or `tokens[1].is_tool_call is False`. A regression flipping
the `is_tool_call` field in `StreamToken.from_dict` (e.g., a typo `data.get("is_tool_call", True)`)
would not change the yielded token count and this test would still pass. Low severity.

**Recommended action:** Add `assert tokens[0].is_tool_call is False` and
`assert buffered[0].is_tool_call is True`. **Not actioned in EA-3.**

#### Partial Field Assertions in PGOV Cache Tests

**Test:** `test_transport.py::TestLivePGOVResult::test_cache_hit_returns_result`

Asserts `result.approved is True` and `result.sanitized_text == "All clear"`, but does not
assert `result.request_id == "req-42"` or `result.reason_codes == []`. A regression mis-wiring
the request_id or reason_codes on cache hit would not be caught. Low severity.

**Recommended action:** Add full-field assertions. **Not actioned in EA-3.**

#### Real-Time Backoff Sleeps in Handshake Failure Tests

**Pattern:** `test_transport.py::TestCheckPaStatus::test_handshake_fails_with_no_port` (lines
320-327) and `test_handshake_fails_with_unreachable_port` (lines 329-335) do not monkey-patch
`asyncio.sleep`, so each test sleeps through the real `PA_HANDSHAKE_BACKOFF_BASE_S * (1 + 2) = 3 s`
retry backoff. The sibling test `test_check_pa_status_state_failed` DOES patch `asyncio.sleep` via
`MonkeyPatch.context()` and completes instantly. The two missing patches are a consistency bug that
adds \~6 s of real wall-clock time to the unit suite.

Not strictly an assertion-quality issue but a test-discipline inconsistency.

**Recommended action:** Apply the same `asyncio.sleep` monkey-patch pattern used in
`test_check_pa_status_state_failed`. **Not actioned in EA-3.**

### ui_shell

#### Assignment Posing As Assertion in `test_hide_sets_display_none`

**Test:** `test_pgov_display.py::TestPGOVPanelLogic::test_hide_sets_display_none` (lines 118-121)

```python
def test_hide_sets_display_none(self, panel: PGOVPanel) -> None:
    panel.display_denial(_make_denial())
    panel.hide()
    panel.styles.display = "none"  # Verify the assignment happened
```

The final line is an **assignment**, not an assertion. The accompanying comment states the intent
("Verify the assignment happened") but the statement mutates state rather than inspecting it. The
test passes regardless of whether `hide()` actually resets `styles.display`. A regression in which
`hide()` fails to set `styles.display = "none"` is not caught. The correct idiom — used
successfully by the sibling test `test_display_denial_sets_block_display` — is
`assert panel.styles.display == "none"`.

**Impact:** Medium-High — `PGOVPanel.hide()`'s display-reset behavior is effectively unverified.

**Recommended action:** Replace the assignment with an assertion. **Not actioned in EA-3.**

#### Non-Functional Tests in `TestBlarAIAppActionGuards`

**Tests:** `test_app.py::TestBlarAIAppActionGuards::test_submit_noop_when_not_operational` and
`test_submit_noop_when_no_gateway` (lines 72-87).

Both tests consist solely of constructor-state inspections:

```python
def test_submit_noop_when_not_operational(self) -> None:
    app = BlarAIApp()
    assert app._operational is False
    # Cannot call action directly without Textual compositor,
    # but verify the guard condition is correct
    assert not app._operational
```

The two assertions are tautological (`app._operational is False` and `not app._operational`).
Neither test invokes `action_submit_prompt()`. The test class docstring states "Verify action
methods respect operational guards," but the guards themselves (`app.py:365-366`:
`if not self._operational or self._gateway is None: return`) are **not exercised**. A regression
removing either guard would not be caught by any test in this class.

The in-line comment explicitly acknowledges the limitation ("Cannot call action directly without
Textual compositor"). The correct pattern — demonstrated in the same file by
`TestBootPhase3P113`, which stubs `query_one` to return `_DisplayStub` / `_PromptStub` and then
invokes `await app._poll_boot_status()` — supports calling action methods after stubbing UI
queries. The same approach would enable actual guard-behavior verification.

**Impact:** High — two tests document behavior they do not verify.

**Recommended action:** Replace both tests with functional guard invocations via the
`_query_one` stubbing pattern used by `TestBootPhase3P113`. **Not actioned in EA-3.**

#### Non-Functional Tests in `TestBlarAIAppAPIWiring`

**Tests:** `test_app.py::TestBlarAIAppAPIWiring::test_send_prompt_requires_session_id_and_text`,
`test_get_pgov_result_is_sync`, and `test_check_pa_status_returns_bool` (lines 89-126).

`test_send_prompt_requires_session_id_and_text` constructs a fully mocked gateway and then
asserts only that mock attributes are `not None` — which is trivially true for any `MagicMock`.
The test's stated purpose is "Verify send_prompt is called with (session_id, prompt)" but no such
call is made; `app.action_submit_prompt()` is never invoked. No wiring is verified.

`test_check_pa_status_returns_bool` inspects the method's type annotation via `inspect.signature`
rather than calling the method or verifying a returned value. This catches only deliberate
annotation changes.

`test_get_pgov_result_is_sync` is functional — it constructs a real `TransportGateway` and calls
the method — and is the only test of the three that performs any real verification.

**Impact:** High — two of three API-wiring tests do not assert API wiring.

**Recommended action:** Replace the two non-functional tests with integration-style calls that
drive `action_submit_prompt` through the gateway mocks and inspect `gateway.send_prompt.call_args`.
**Not actioned in EA-3.**

#### Insufficient Truncation Assertion

**Test:** `test_pgov_display.py::TestPGOVPanelLogic::test_display_denial_truncates_long_text`

```python
def test_display_denial_truncates_long_text(self, panel: PGOVPanel) -> None:
    long_text = "X" * 500
    panel.display_denial(_make_denial(text=long_text))
    rendered = panel.update.call_args[0][0]
    assert len(long_text) > 200
    assert "X" * 200 in rendered
```

The substring assertion `"X" * 200 in rendered` is satisfied by the full 500-char string since
`"XX…X"` (500) contains `"XX…X"` (200) as a substring. The test does not assert the truncation
upper bound. A regression changing the slice `[:200]` to `[:500]` or removing the truncation
entirely would pass.

**Recommended action:** Add `assert "X" * 201 not in rendered`. **Not actioned in EA-3.**

#### Missing `_streaming` Invariant Assertion for Tool-Call Path

**Test:** `test_streaming.py::TestStreamingDisplayLogic::test_tool_call_token_written_directly`

Asserts that a tool-call token's text is buffered and `write` is called, but does not assert that
`display._streaming` remains `False` for tool-call tokens. The production code intentionally does
not set `_streaming=True` on the tool-call branch (streaming.py:60-64, early return). A regression
that sets `_streaming=True` before the early return would not be caught. Low severity.

**Recommended action:** Add `assert display.is_streaming is False` after the tool-call append.
**Not actioned in EA-3.**

#### Loose Separator Assertion in `TestSessionReload`

**Test:** `test_app.py::TestSessionReload::test_on_list_view_selected_loads_turns` (line 413)

```python
assert any("─" in line for line in display_lines)
```

A single box-drawing character anywhere in any line satisfies this. The production code emits a
40-character separator (`"─" * 40`); the assertion does not verify the form. Low severity.

**Recommended action:** Assert `any("─" * 40 in line for line in display_lines)`.
**Not actioned in EA-3.**

#### Deprecated `asyncio.get_event_loop()` Pattern

**Test:** `test_app.py::TestSessionReload::test_on_list_view_selected_loads_turns` (line 403)

The test uses `asyncio.get_event_loop().run_until_complete(app.on_list_view_selected(event))`.
`asyncio.get_event_loop()` is deprecated in Python 3.10+ when there is no current event loop and
scheduled for removal in future Python versions. The rest of the async tests in the file use
`pytest.mark.asyncio`; this single test does not. Not a correctness issue today but a brittleness
concern.

**Recommended action:** Mark the test with `@pytest.mark.asyncio` and `await` the coroutine
directly. **Not actioned in EA-3.**

### shared

#### Untested UI-Gateway Encoders in `test_ipc_protocol.py`

Group F (`TestMessageFramerTyped`) tests `encode_request`, `decode_request`,
`encode_response`, `decode_response`, `encode_error`, and `encode_heartbeat`. It does NOT
test `encode_handshake_request`, `encode_handshake_response`, `encode_prompt_request`,
`encode_stream_token`, `encode_pgov_result`, or `encode_generation_complete` — all six
UI-gateway convenience encoders defined in `shared/ipc/protocol.py` lines 301-380. A
regression altering a payload field in any of these encoders (e.g. dropping `is_thinking`
from `encode_stream_token`) would pass the shared REGRESSION-scope suite and surface only
in `tests/integration/test_p114_ui_end_to_end.py` under the slow marker.

**Recommended action:** Add a new test class `TestMessageFramerUIGatewayEncoders` that
encodes each UI-gateway message type and decodes it back via `MessageFramer.decode`,
asserting every payload field survives round-trip. **Not actioned in EA-4.**

#### Weak Empty-Token Rejection Assertion in `test_jwt_validator.py`

`TestValidation5StageGate::test_stage1_empty_token_rejected` (line 287-290) asserts only
`result.valid is False`. It does not inspect `result.error`. Both a `DECODE: …` error and
an `UNEXPECTED: …` error would pass this test. The companion test
`test_stage1_garbage_token_rejected` does assert `"DECODE" in (result.error or "")`; the
empty-token test should use the same pattern.

**Recommended action:** Add `assert "DECODE" in (result.error or "")` to match the sibling
garbage-token test. **Not actioned in EA-4.**

#### Missing Server-Side `peer_cn` Assertion in `test_mtls_roundtrip`

`TestVsockMTLS::test_mtls_roundtrip` (lines 569-615) asserts the client / server payload
round-trip equality but never inspects the server-side transport's `peer_cn`.
`TestVsockTransportPeerCN::test_peer_cn_extracted_from_mtls_cert` covers the peer_cn
extraction in isolation, but the full end-to-end mTLS round-trip test does not verify
that data transfer and peer identity are exposed on the same accepted transport. A
regression decoupling mTLS cert validation from the transport's `peer_cn` property would
not be caught by `test_mtls_roundtrip` alone.

**Recommended action:** Capture the server-side `VsockTransport` from the `accepted[0]`
slot pattern and `assert accepted[0].peer_cn == "BlarAI Test Client"`. **Not actioned in
EA-4.**

#### Test Fixture Coverage Gap — `resolve_service_root` Never Exercised

All `test_runtime_config.py` tests use the `_make_service_root` helper which creates a
`config/` directory directly under `tmp_path`. None invokes `shared.runtime_config.resolve_service_root()` — the production shared resolver that every service calls to locate
its config directory in both normal-Python and PyInstaller-frozen modes. The existing
tests therefore prove nothing about the resolver code path that production actually
exercises at launcher startup.

**Recommended action:** Add a dedicated `TestResolveServiceRoot` class with (a) one test
for the normal-Python `Path(module_file).resolve().parents[1]` branch and (b) one test
for the PyInstaller branch with `sys._MEIPASS` monkey-patched. **Not actioned in EA-4.**

#### Weak Rejection-Count Assertion in `test_rejection_count_increments`

`TestValidation5StageGate::test_rejection_count_increments` (lines 350-355) asserts
`v.rejection_count == 2` after two failed validations. It does not verify that
`v.rejection_count == 0` before the first call, or that a **successful** validation does
NOT increment the rejection counter. A regression where every validation (pass or fail)
bumped `_rejection_count` would pass this test. An intermediate success / failure mix is
the only pattern that would fully pin the counter contract.

**Recommended action:** Reshape the test to validate one valid token (expect counter == 0)
then invalidate a different token (expect counter == 1), demonstrating the counter
responds only to failures. **Not actioned in EA-4.**

### launcher

#### Silent Mock-State Assertions in `test_launcher.py::test_production_happy_path`

The happy-path test asserts `result == 0` and four `.from_runtime_mode` / class
constructors were called once each, plus `mock_app_cls.return_value.run.assert_called_once()`. It does **not** assert:

- The activation-evidence JSON was written (no verification of `_record_activation_evidence`).
- `_run_uat2_prompt_flow_preflight` was called (though `return_value=True` is patched, no
  call verification is made).
- `gateway.check_pa_status` was actually awaited (the `AsyncMock` is configured but the
  await is not verified).
- The `activation_evidence` disposition transitioned to `PASS` before `app.run()`.

A regression that removed the prompt-flow preflight call, skipped the evidence write, or
launched the TUI before the handshake completed would pass this test. The test's title
("Full happy path") overstates what is verified.

**Recommended action:** Add
`mock_gateway.check_pa_status.assert_awaited_once()`,
`mock_prompt_flow.assert_called_once()`, and a `tmp_path`-based
`BLARAI_ACTIVATION_EVIDENCE_PATH` monkey-patch that allows the test to read the written
evidence JSON and verify `disposition == "PASS"`. **Not actioned in EA-4.**

#### Retry-Count Invariant Not Asserted in `test_copy_file_to_vm_failure`

`TestGuestIntegrationHelpers::test_copy_file_to_vm_failure` asserts `ok is False` but
does not inspect `mock_ps.call_count`. The default `retries=3` controls a loop with a
`time.sleep(retry_delay_s)` between attempts; a regression that short-circuited the loop
on the first failure would produce the same `False` result with only one PowerShell call.

**Recommended action:** Add `assert mock_ps.call_count == 3` to the failure test. Add a
paired `assert mock_ps.call_count == 1` to `test_copy_file_to_vm_success` to verify no
retry on first-attempt success. Monkey-patch `time.sleep` to `lambda _: None` so the test
does not pay the real retry-delay wall-clock. **Not actioned in EA-4.**

#### Ad-Hoc Class-Stub Conflation in `test_deploy_guest_runtime_success`

The test declares `class _State: value = "Off"` as an ad-hoc stand-in for `VMState`, sets
`mock_state.return_value = _State()`, and drives `deploy_guest_runtime` through nine
`@patch` decorators. The assertion surface reduces to two top-level payload fields:
`disposition == "PASS"` and `guest_service_interface_enabled is True`. Evidence fields
such as `vsock_topology_validation.source`, `artifacts.bundle_destination`,
`config_preflight.policy_agent`, `guest_startup.command`, and
`artifacts.include_models=False` are never asserted despite appearing in the written
JSON. A regression altering the evidence schema (rename, field removal, or type change)
would not be caught.

**Recommended action:** Replace scattered top-level asserts with a single structural
equality check against an expected payload dict, with volatile fields (`timestamp`)
redacted. Use real `VMState.OFF` rather than an ad-hoc class. **Not actioned in EA-4.**

#### Single-Branch Fail-Closed Test in `test_guest_deploy.py`

`test_deploy_guest_runtime_fail_closed_on_vm_start` is the **only** negative-path test
for `deploy_guest_runtime`. It asserts the first failure fingerprint has
`code == "P5_VM_START_FAILED"` but does not inspect the `disposition`, `fail_closed`,
`timestamp`, `stage`, or `vm_state_before` fields of the fingerprint. The fingerprint
schema is effectively untested; any other `P5_*` code path (`P5_GSI_DISABLED`,
`P5_VSOCK_TOPOLOGY_INVALID`, `P5_POLICY_CONFIG_INVALID`, `P5_ORCH_CONFIG_INVALID`,
`P5_GUEST_CHANNEL_NOT_READY`, `P5_BUNDLE_BUILD_FAILED`, `P5_COPY_BUNDLE_FAILED`,
`P5_COPY_BOOTSTRAP_FAILED`) has zero coverage.

**Recommended action:** Enumerate the nine failure codes and add one parametrized test
per code, asserting the complete fingerprint dict shape. **Not actioned in EA-4.**

#### ConfigResolutionError Paths Untested in `test_launcher.py`

`test_launcher.py` does not exercise any `ConfigResolutionError` branch. Three separate
branches (launcher-level mode resolution, PA `from_runtime_mode`, AO `from_runtime_mode`)
each produce distinct failure fingerprints with distinct `code` values written into the
activation evidence. Their correctness is untested.

**Recommended action:** Add
`test_launcher_mode_resolution_failure_returns_1`,
`test_policy_agent_config_resolution_failure_returns_1`,
`test_orchestrator_config_resolution_failure_returns_1`. Each asserts `main() == 1` and
the correct fingerprint `code` value. **Not actioned in EA-4.**

### integration

#### Tautological Router-Result Assertion in `test_out_of_scope_query_denied`

The test (line 334-343) constructs
`ClassificationResult(intent=Intent.OUT_OF_SCOPE, confidence=0.45, latency_ms=12.0)` and
then asserts `router_result.intent == Intent.OUT_OF_SCOPE` and
`router_result.confidence < 0.75`. Both assertions are tautologies — the values were
literal arguments three lines earlier. No pipeline behavior is verified. The title ("Out
of scope query → safe rejection") claims rejection-path verification, but no rejection
path is exercised.

**Recommended action:** Either (a) drive a real `SemanticRouter.classify()` with a
gibberish query and assert `OUT_OF_SCOPE`, or (b) extend the test to verify that an
`OUT_OF_SCOPE` classification does NOT result in CAR construction or PA engagement
(negative assertion on the downstream pipeline). **Not actioned in EA-4.**

#### Redundant Double-Invocation in `test_pipeline_request_id_chain`

Line 370-372 constructs a tuple expression with a discarded first element:

```python
_, decision = run_rule_engine(car, acl_matrix=ACL_MATRIX), adjudicate(
    car, run_rule_engine(car, acl_matrix=ACL_MATRIX), npu_result
)
```

`run_rule_engine` is invoked twice — once for the discarded tuple position, once inside
`adjudicate`'s positional argument. The two invocations are deterministic and produce
identical results, so behavior is correct, but the pattern is confusing. The first call
is wasted work and its result is silently dropped.

**Recommended action:** Replace with the standard idiom
`rule_result = run_rule_engine(car, acl_matrix=ACL_MATRIX); decision = adjudicate(car, rule_result, npu_result)`.
**Not actioned in EA-4.**

#### Trivially-True Dataclass Assertions Across Group G

Group G (`TestLatencyBudgetStructure`) is four tests of a dataclass shape that prove
little. Example — `test_classification_result_has_latency` constructs
`ClassificationResult(intent=…, confidence=0.90, latency_ms=15.5)` and asserts
`result.latency_ms >= 0.0`. Identical pattern in
`test_generation_result_has_timing_fields`, `test_npu_classification_result_has_latency`,
`test_adjudication_latency_fields_structurally_valid`. Every assertion operates on a value
supplied literally by the test itself. The group's title ("Validate latency budget FIELDS
are present and structurally correct") is honest about limited intent — but the tests
only verify Python dataclass field typing, not that production pipeline code populates
these fields.

**Recommended action:** Replace at least one of the four with a test that invokes real
pipeline code (with the model boundary mocked) and asserts the pipeline populates
`latency_ms` on the returned object. The other three may be replaced with a single
parametrized dataclass-hydration test. **Not actioned in EA-4.**

#### Tautological Constant Test `test_p114_stream_token_buffer_limit_constant_present`

The final module-level test in `test_p114_ui_end_to_end.py` (line 655-656) asserts
`STREAM_TOKEN_BUFFER_LIMIT >= 1`. Any positive integer satisfies this. A regression
lowering the constant to 1 or 2 would pass the assertion. The production value at time
of audit is 4096 (per EA-3 finding on `services/ui_gateway/src/constants.py`).

**Recommended action:** Replace with value-anchored `assert STREAM_TOKEN_BUFFER_LIMIT == 4096`
or delete — `TestP114GroupCStreamTokenFlow::test_stream_token_buffer_limit_respected`
already covers the constant's behavioral role via monkey-patch. **Not actioned in EA-4.**

#### Narrow Assertion in `test_adjudication_context_has_latency_breakdown`

The test (line 1203-1217) asserts `ctx.latency.total_ms >= 0.0` and
`isinstance(ctx.latency.total_ms, float)`. Both are trivially true for any float value
(including zero; `isinstance` check is unnecessary for a dataclass field). The docstring
describes the expected behavior ("NPU stub returns error → DENY short-circuit") but the
test asserts neither `ctx.decision == AdjudicationDecision.DENY` nor
`ctx.npu_result.error is not None`, leaving the short-circuit contract unpinned.

**Recommended action:** Add explicit DENY and error-is-not-None assertions following the
pattern used by Group I (`TestHybridAdjudicatorIntegration::test_stub_npu_full_pipeline_deny`).
**Not actioned in EA-4.**

#### Broad-Catch `pytest.raises` Pattern in `test_tool_call_buffer_overflow_fail_closed`

The test (line 415-420) asserts
`with pytest.raises(ValueError, match="buffer exceeded")`. The match pattern
`"buffer exceeded"` matches any `ValueError` containing that substring; a hypothetical
regression where the tool-call buffer raises for a different reason (e.g. "tool_call
buffer exceeded maximum tokens allocated for request") that still matches the substring
would pass, including scenarios where the buffer failure originates from the wrong
branch. This is minor — `"buffer exceeded"` is a reasonable substring — but the assertion
is softer than the sibling stream-buffer test (which value-anchors via
`mp.setattr(transport_module, "STREAM_TOKEN_BUFFER_LIMIT", 2)`).

**Recommended action:** Tighten to the exact production message or extend the match with
the constant-value reference. **Not actioned in EA-4.**

---

## Boundary Violations

### policy_agent

No material boundary violations identified for policy_agent.

### assistant_orchestrator

#### Cross-Service Import in Test Suite

**Finding:** `test_entrypoint.py` (line 17) imports:
```python
from services.policy_agent.src.jwt_minter import AgenticJWTMinter
```

This is a **cross-service boundary violation**. The AO test suite depends on PA's
`jwt_minter` module to generate JWT key pairs for the non-dev security test
(`test_start_non_dev_succeeds_with_jwt_ca_and_kgm`).

**Impact:** Medium. If the PA `jwt_minter` API changes (e.g., rename, parameter change),
an AO test will break — even though no AO production code changed. This creates a
maintenance coupling between services that violates the principle of service isolation.

**Recommended action:** Extract the key-pair generation into a shared test utility
(e.g., `tests/conftest.py` or `shared/test_utils/`) or inline a minimal key-gen stub
in the AO test file. **Not actioned in EA-2.**

### semantic_router

No material boundary violations identified for semantic_router.

### ui_gateway

#### Integration-Style Live-TCP Tests in a Service Unit-Test File

The `test_transport.py` suite contains a cluster of tests that rely on real TCP sockets bound
in-process via `asyncio.start_server("127.0.0.1", 0)`. Per `docs/TEST_GOVERNANCE.md` Test
Boundary Rule, unit tests in `services/*/tests/` MUST mock external dependencies including IPC
sockets and network calls; integration tests belong under `tests/integration/` with a
module-level `pytest.mark.slow` marker.

The following tests establish real loopback TCP servers and exercise the full
`VsockTransport(dev_mode=True)` socket path end-to-end:

- `TestCheckPaStatus::test_handshake_success_with_mock_server` (line 338)
- `TestLiveHandshake::test_handshake_stores_transport` (line 510)
- `TestLiveHandshake::test_handshake_non_operational_response` (line 536)
- `TestLiveSendPrompt::test_send_prompt_sends_ipc_message` (line 566)
- `TestLiveStreamTokens::test_stream_tokens_full_flow` (line 616)
- `TestLiveStreamTokens::test_stream_tokens_buffers_tool_calls` (line 685)
- `TestLivePGOVResult::test_pgov_denied_flow` (line 772)
- `TestLivePGOVResult::test_generation_complete_before_pgov_still_caches_result` (line 819)
- `TestLivePGOVResult::test_blank_pgov_request_id_maps_to_active_request` (line 866)
- `TestLiveErrorHandling::test_server_disconnect_during_stream` (line 916)
- `TestLiveErrorHandling::test_error_message_type_ends_stream` (line 951)

Each spins up an OS-assigned loopback port and the gateway under test connects via
`VsockTransport(config, dev_mode=True)`. The tests exercise the live MessageFramer wire protocol,
`asyncio.to_thread` blocking-socket calls, and the full receive loop. None is a pure logic test:
each requires a working network stack and an asyncio event loop driving real sockets.

That these tests run on loopback and typically complete in well under one second is a
performance mitigation but does not change their boundary classification under the governance
rule.

**Impact:** Medium. These tests catch real protocol regressions that pure mocks would miss, but
their placement in a service unit-test file:
(a) couples `services/ui_gateway/tests/` to a running asyncio TCP stack;
(b) bypasses the `slow` marker's default-deselected behavior, so they run on every UNIT/REGRESSION
    scope invocation rather than only on explicit opt-in;
(c) creates a maintenance mismatch if/when the service is refactored to use real AF_HYPERV sockets
    (the tests would no longer reflect production transport).

**Borderline case:** `TestCheckPaStatus::test_handshake_fails_with_unreachable_port` connects to
`127.0.0.1:1` without starting a server. It does not require a running peer but does depend on
OS-level connection-refused semantics — a true boundary-adjacent case. Its purpose is Fail-Closed
verification of the handshake retry loop. Justified if retained as-is but should be acknowledged
as exercising the real socket path.

**Explicitly NOT a boundary violation:**
- `TestCheckPaStatus::test_handshake_fails_with_no_port` (port=0) raises ConnectionError
  synchronously inside `_attempt_pa_handshake` before any socket is created — pure logic test.
- `TestSchema::test_wal_mode_requested` uses `tempfile.TemporaryDirectory` to create a real
  SQLite file. `TEST_GOVERNANCE.md` explicitly excludes self-contained temporary-file scaffolding
  from the boundary rule.

**Recommended action:** Relocate the 11 enumerated live-TCP tests to a new
`tests/integration/test_ui_gateway_ipc.py` with module-level
`pytestmark = pytest.mark.slow`, and keep pure-logic transport unit tests (StartupState,
StreamToken / GatewayPGOVResult dataclasses, ReasonCodes, init-state, buffer/flush, reset,
get_pgov_result cache default, `TestCheckPaStatus::test_check_pa_status_state_failed` which
already mocks `_attempt_pa_handshake`) in `services/ui_gateway/tests/test_transport.py`. **Not
actioned in EA-3.**

### ui_shell

No material boundary violations identified for ui_shell.

Observations considered and rejected:

- `TestBootPhase3P113` tests use `monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))` and cause
  `_configure_boot_logger()` to open a real `FileHandler` on `tmp_path/BlarAI/boot.log`. pytest's
  `tmp_path` is controlled, test-scoped, isolated scaffolding per the governance rule's exclusion
  for "Self-contained temporary-file scaffolding or controlled test doubles".
- `test_pgov_display.py` and `test_streaming.py` use
  `patch.object(..., "__init__", lambda self, **kw: None)` to bypass Textual's DOM base-class
  construction. This is a controlled test-double pattern, not a boundary violation.
- `test_app.py::TestSessionReload::test_on_list_view_selected_loads_turns` instantiates
  `SessionListItem(summary)` with a MagicMock summary. The base `ListItem` class is imported as a
  lightweight Textual widget without driving the DOM compositor; no live widget tree is mounted.
  Not a boundary violation.

### shared

#### Live-TCP Tests in `shared/tests/test_ipc_transport.py`

Per `docs/TEST_GOVERNANCE.md` §6 Test Boundary Rule, unit tests in `shared/tests/` MUST
mock external dependencies including IPC sockets. The majority of `test_ipc_transport.py`
establishes real TCP loopback servers via
`socket.socket(AF_INET, SOCK_STREAM).bind(("127.0.0.1", 0)).listen(...)` plus threaded
accept loops, and drives the full `VsockTransport(dev_mode=True)` socket send / receive
path end-to-end. This is the same anti-pattern EA-3 flagged for
`services/ui_gateway/tests/test_transport.py` — the shared transport test file precedes
ui_gateway in codebase history and established the pattern.

The following tests establish real loopback servers or bind real sockets and exercise the
live wire protocol:

- `TestVsockTransportIO::test_send_receive_roundtrip` (line 323)
- `TestVsockTransportIO::test_send_empty_payload` (line 363)
- `TestVsockListenerBasic::test_start_stop_lifecycle` (line 422) — binds a real socket on port 0
- `TestVsockListenerBasic::test_double_stop_is_safe` (line 434) — binds a real socket
- `TestVsockListenerAccept::test_accept_returns_transport` (line 451)
- `TestVsockListenerAccept::test_accept_timeout_returns_none` (line 481) — binds a real socket
- `TestVsockListenerAccept::test_end_to_end_transport_through_listener` (line 493)
- `TestVsockListenerAccept::test_bidirectional_through_listener` (line 529)
- `TestVsockMTLS::test_mtls_roundtrip` (line 569)
- `TestVsockProductionFallback::test_listener_start_no_mtls_production_fails` (line 636) — binds on port 0 in AF_INET, then the mTLS enforcement rejects pre-bind in production; the listener is created and `.start()` is driven
- `TestVsockTransportPeerCN::test_peer_cn_none_in_dev_mode_accept` (line 724)
- `TestVsockTransportPeerCN::test_peer_cn_extracted_from_mtls_cert` (line 752)

**Impact:** Medium. The tests catch real framing + mTLS regressions that pure mocks
would miss, but their placement in `shared/tests/` (a unit-test directory per
TEST_GOVERNANCE §1) (a) bypasses the `slow` marker's default-deselection, so they run on
every UNIT and REGRESSION invocation; (b) introduce OS-level loopback socket dependency,
thread scheduling dependency, and self-signed-cert cryptography dependency into the
shared-library unit-test surface; (c) duplicate boundary classification that EA-3 already
flagged on the higher layer.

**Borderline cases (retained with justification):**

- `TestVsockTransportIO::test_connect_to_nonexistent_port_returns_false` (line 396)
  connects to `127.0.0.1:59999` without starting a server. Depends on OS connection-refused
  semantics. Purpose is Fail-Closed retry-loop verification. Borderline — acknowledged as
  exercising the real socket path but preserves a valuable Fail-Closed guarantee.
- `TestVsockTransportBasic::test_injected_socket_marks_connected` (line 292) creates a
  socket but never binds or connects. Pure state inspection. Not a boundary violation.
- `TestVsockTransportBasic::test_send_oversized_returns_false` (line 301) creates a socket
  but never binds. The size check fires before any network I/O. Not a boundary violation.
- `TestVsockProductionFallback::test_transport_connect_no_mtls_production_fails` (line 626)
  tests the AF_HYPERV code path in non-dev mode, which falls through to mTLS enforcement
  and returns False without opening a socket on non-Hyper-V machines. Not a boundary
  violation.

**Explicitly NOT a boundary violation:**

- `TestVsockAddressConfig::*` — pure dataclass construction.
- `TestSSLContextCreation::*` — SSL-context construction from certs generated into a
  `tmp_path_factory` directory via the `cryptography` library. Self-contained temp-file
  scaffolding; excluded per governance.
- `_generate_test_certs` fixture (lines 50-155) — self-contained temp-file scaffolding.

**Recommended action:** Relocate the 12 enumerated live-TCP tests to a new
`tests/integration/test_shared_ipc_transport.py` with module-level
`pytestmark = pytest.mark.slow`. Keep pure-logic tests (address / config dataclasses,
SSL-context construction, send-when-not-connected, send-oversized, peer_cn kwarg
injection, `_extract_cn` unit tests) in `shared/tests/test_ipc_transport.py`. **Not
actioned in EA-4.**

#### Cross-Service Import in `shared/tests/test_jwt_validator.py`

Lines 35-39 import:

```python
from services.policy_agent.src.jwt_minter import (
    AgenticJWTMinter,
    EpochManager,
    MintedJWT,
)
```

`shared/tests/` is the unit-test location for the **shared** library. Importing from
`services.policy_agent.*` inverts the dependency layering: a shared-library test depends
on a specific service's implementation to generate test fixtures (key pairs and minted
tokens). Any API change to `services.policy_agent.src.jwt_minter` (rename, signature
change, module relocation) breaks the shared test suite even though no shared-library
code changed.

This is the same cross-service coupling pattern that EA-2 recorded for
`services/assistant_orchestrator/tests/test_entrypoint.py` importing the same
`AgenticJWTMinter`. Two test suites across two layers carry the same PA-API dependency
for key-pair generation.

**Impact:** Medium. The coupling is stable as long as `AgenticJWTMinter.generate_key_pair()`
remains the canonical key-gen entrypoint, but the layering inversion means every consumer
test carries a PA-API dependency.

**Recommended action:** Extract key-pair generation into a shared test utility (e.g.
`shared/tests/_keygen.py` or root-level `tests/conftest.py`) so neither the AO entrypoint
test nor the shared JWT validator test imports from `services.policy_agent`. **Not
actioned in EA-4.**

### launcher

No material boundary violations identified for launcher.

Observations considered and rejected:

- `test_guest_deploy.py::test_validate_vsock_topology_success` calls
  `_validate_vsock_topology(repo_root)` against the real repository-committed file at
  `phase2_gates/evidence/vsock_validation.json`. The dependency is a committed-repo file
  (deterministic, version-controlled, test-machine-independent) rather than an external
  system or live socket. Per the governance rule, "self-contained temporary-file
  scaffolding or controlled test doubles do not automatically count as boundary
  violations." The committed evidence file sits between temp-file scaffolding and an
  external dependency. **Decision:** not a material boundary violation. Recording as
  observation only — the test is silently coupled to the committed evidence file; a
  regression regenerating that evidence with different field names would fail this test
  even though `_validate_vsock_topology` is unchanged.
- `test_vm_manager.py::test_copy_file_to_vm_missing_source` and
  `test_copy_file_to_vm_success` / `test_copy_file_to_vm_failure` write payload files via
  `tmp_path`. `tmp_path` is pytest-controlled, isolated scaffolding per the governance
  rule's exclusion. Not boundary violations.
- `test_vm_manager.py::TestIsAdmin::*` patches `ctypes.windll.shell32` entirely. No live
  Windows-API call is made. Not a boundary violation.

### integration

#### Non-Cross-Service Tests Placed Under `tests/integration/`

Per the boundary contract, intentional, marker-declared cross-service behavior in
`tests/integration/` is the **designed** contract and is NOT a boundary violation. The
contract does, however, permit flagging "tests that are placed under `tests/integration/`
but perform no genuine cross-service interaction."

The following tests in `test_p114_ui_end_to_end.py` carry the module-level `slow` marker
but exercise only a single service or a single component within a service in isolation.
They do NOT drive a cross-service code path. They should live in service-level unit-test
directories:

| Test | Current Location | Correct Location | Rationale |
|------|-----------------|------------------|-----------|
| `TestP114GroupBSessionCRUD::test_create_session_returns_uuid_string` (line 247) | `tests/integration/test_p114_ui_end_to_end.py` | `services/ui_gateway/tests/test_session_store.py` | Instantiates `SessionStore` in isolation; no transport, no app, no second service. |
| `TestP114GroupBSessionCRUD::test_list_sessions_returns_created_sessions` (line 256) | same | `services/ui_gateway/tests/test_session_store.py` | Same pattern — in-process SessionStore only. |
| `TestP114GroupBSessionCRUD::test_add_turn_persists_turn` (line 265) | same | `services/ui_gateway/tests/test_session_store.py` | Same pattern. |
| `TestP114GroupBSessionCRUD::test_get_turns_returns_persisted_turns_in_order` (line 275) | same | `services/ui_gateway/tests/test_session_store.py` | Same pattern. |
| `TestP114GroupBSessionCRUD::test_delete_session_removes_session_and_cascades_turns` (line 286) | same | `services/ui_gateway/tests/test_session_store.py` | Same pattern; duplicates the `TestDeleteSession::test_cascade_deletes_turns` coverage already present at the service level per EA-3. |
| `TestP114GroupBSessionCRUD::test_create_session_title_truncated_to_limit` (line 298) | same | `services/ui_gateway/tests/test_session_store.py` | Same pattern. |
| `TestP114GroupATransportGatewayAPI::test_send_prompt_returns_request_id_string` (line 142) | same | `services/ui_gateway/tests/test_transport.py` | Sets `gw._state = StartupState.OPERATIONAL` directly; no socket; pure UUID-shape assertion. |
| `TestP114GroupATransportGatewayAPI::test_send_prompt_raises_when_not_operational` (line 235) | same | `services/ui_gateway/tests/test_transport.py` | No socket, no second service; pure state check. |
| `TestP114GroupCStreamTokenFlow::test_flush_tool_call_buffer_approved_releases_tokens` (line 345) | same | `services/ui_gateway/tests/test_transport.py` | Pure in-process `TransportGateway` buffer manipulation. |
| `TestP114GroupCStreamTokenFlow::test_flush_tool_call_buffer_denied_discards_tokens` (line 352) | same | `services/ui_gateway/tests/test_transport.py` | Same pattern. |
| `TestP114GroupCStreamTokenFlow::test_tool_call_buffer_overflow_fail_closed` (line 415) | same | `services/ui_gateway/tests/test_transport.py` | Same pattern; duplicates `test_buffer_overflow_raises` already present at the service level per EA-3. |
| `TestP114GroupDBootPhase3Gating::test_gateway_reset_returns_to_initializing` (line 496) | same | `services/ui_gateway/tests/test_transport.py` | Pure state-transition on `TransportGateway.reset()`; no socket. |
| `TestP114GroupDBootPhase3Gating::test_gateway_state_transition_to_failed_after_retries` (line 489) | same | `services/ui_gateway/tests/test_transport.py` | Exercises handshake fail path with no server — equivalent to `test_handshake_fails_with_no_port` already flagged under EA-3 at the service level. |
| `TestP114GroupEPGOVDisplay::test_reason_code_labels_render_for_three_codes` (line 544) | same | `services/ui_shell/tests/test_pgov_display.py` | Pure `PGOVPanel` render test with stubbed `update`; no cross-service interaction. |
| `TestP114GroupEPGOVDisplay::test_multiple_reason_codes_render_all_labels` (line 559) | same | `services/ui_shell/tests/test_pgov_display.py` | Same pattern. |
| `TestP114GroupEPGOVDisplay::test_sanitized_text_truncated_at_200_chars` (line 573) | same | `services/ui_shell/tests/test_pgov_display.py` | Same pattern; also implements the tightened truncation assertion recommended by EA-3 (`"x" * 201 not in rendered`). |
| `TestP114GroupEPGOVDisplay::test_pgov_panel_hide_clears_display` (line 588) | same | `services/ui_shell/tests/test_pgov_display.py` | Pure `PGOVPanel.hide()` test — addresses EA-3's `test_hide_sets_display_none` assignment-as-assertion finding by using the correct `assert captured["text"] == ""` pattern. |
| `TestP114GroupEPGOVDisplay::test_unknown_reason_code_renders_fallback_label` (line 640) | same | `services/ui_shell/tests/test_pgov_display.py` | Same pattern. |
| Module-level `test_p114_stream_token_buffer_limit_constant_present` (line 655) | same | removed or relocated to `services/ui_gateway/tests/test_transport.py` | Asserts a constant exists; trivially true; no cross-service interaction. |

**Impact:** Medium. These 19 tests are deselected from REGRESSION by the `slow` marker,
so regressions in `SessionStore` CRUD, `PGOVPanel` rendering, or `TransportGateway`
state-transition logic go undetected by the default quality-gate scope. Three of them
(`test_delete_session_removes_session_and_cascades_turns`, `test_tool_call_buffer_overflow_fail_closed`, and the four `PGOVPanel` tests) duplicate coverage that EA-3 already
recorded in the service-level test files — they are dead weight in the slow suite.

**Borderline cases (retained under `tests/integration/` with justification):**

- `TestP114GroupDBootPhase3Gating::test_no_prompt_dispatched_until_operational` and
  `test_after_operational_prompt_dispatches_correctly` — drive
  `BlarAIApp.action_submit_prompt()` with a stubbed `query_one`. The action crosses the
  ui_shell → ui_gateway boundary (calls `gateway.send_prompt`), so it IS cross-service
  even when the gateway is a `MagicMock`. Keeping them in `tests/integration/` is
  defensible.
- `TestP114GroupDBootPhase3Gating::test_boot_log_written_on_state_transitions` — drives
  `BlarAIApp._poll_boot_status()` against a pure-Python `_GatewayBootSuccess` stub (not a
  `MagicMock`). Exercises the ui_shell boot-log file write and state progression —
  cross-service in spirit even without a socket. Acceptable.
- `TestP114GroupEPGOVDisplay::test_approved_result_does_not_trigger_pgov_panel_display`
  — drives `BlarAIApp.action_submit_prompt` with a mocked gateway; cross-service in
  spirit. Acceptable.

**Genuinely cross-service tests in `test_p114` (retained with no issue):**
`test_stream_tokens_yields_streamtoken_sequence`, `test_stream_tokens_final_token_is_final_true`, `test_check_pa_status_true_with_echo_server`,
`test_check_pa_status_false_when_no_pa`, `test_tool_call_tokens_buffered_until_pgov_clearance`, `test_normal_tokens_flow_without_buffering`,
`test_stream_token_buffer_limit_respected`, `test_gateway_state_transition_to_operational`
— each launches a real `asyncio.start_server` on loopback and drives the full ui_gateway
↔ asyncio-server wire path. These are the designed contract for this file.

**Recommended action:** Relocate the 19 enumerated non-cross-service tests to the
indicated service-level test files. Reconcile duplicate coverage with the EA-3 findings
already recorded for `test_session_store.py`, `test_transport.py`, and
`test_pgov_display.py`. **Not actioned in EA-4** (out of DOCS-ONLY scope; no test
modifications permitted).

#### `test_p110_end_to_end.py` — No Material Boundary Violations

All groups in `test_p110_end_to_end.py` are either:

- Cross-service with real IPC (Groups B, C, F partial) — intentional, marker-declared
  integration-boundary behavior.
- Cross-service in-process (Groups A, D, E, G, H, I) — multiple service modules
  instantiated and driven together in the same Python process; this is a valid
  integration-test pattern even though no socket I/O occurs.
- Group G field-presence assertions — flagged as weak in Assertion Quality Findings but
  not boundary violations (pure in-process dataclass tests are valid, just underpowered).

No material boundary violations identified for `test_p110_end_to_end.py`.

---

## Prioritized Gap Report

### HIGH Priority

- [cross-service: policy_agent, assistant_orchestrator] Add `last_failure["code"]` assertions to the three fail-closed tests that currently verify only `start() is False` / `running is False` (PA `test_start_fails_closed_on_rule_config_failure`, PA `test_start_fails_closed_on_model_load_failure`, AO `test_start_fails_closed_on_model_load_failure`): matches the structured-error-code pattern already established by sibling tests (PA `test_start_non_dev_fails_closed_when_jwt_key_missing`, AO `test_start_fails_closed_on_runtime_mode_mismatch`). Source: Assertion Quality Findings.
- [policy_agent] Add a mock-based test asserting `confidence == 0.50` escalates, pinning the `>= 0.50` inclusive-lower-bound comparator: exact-threshold boundary gap at the escalation floor per Coverage Map (Exact Escalation Floor Boundary Untested) — a comparator typo from `>=` to `>` is currently undetectable.
- [assistant_orchestrator] Add a mock-detector test at `cosine_similarity == 0.85` asserting `result.approved is False`: exact-threshold boundary gap at the PGOV leakage fail-closed gate per Coverage Map (Exact PGOV Leakage Threshold Untested) — an inclusion/exclusion regression at the production `>=` boundary is currently undetectable.
- [semantic_router] Add mock-based dual-gate tests that inject controlled `_embed_raw` outputs to pin exact-boundary behavior at `CONFIDENCE_THRESHOLD=0.50` and `CONFIDENCE_MARGIN=0.04`: critical decision-surface threshold per Coverage Map (Dual-Gate Threshold and Margin Boundaries Untested) — integration-style tests cannot exercise exact values because real embeddings produce unpredictable similarity scores.
- [assistant_orchestrator] Extend `test_entrypoint.py` to verify each of the \~13 currently-untested TOML config validation constraints in isolation (`device`, `priority`, `model_dir`, `max_new_tokens`, `temperature`, `top_k`, `top_p`, `repetition_penalty`, `vsock_cid`, `vsock_port`, `max_message_bytes`, `pgov.cosine_similarity_threshold`): the primary defense against misconfiguration currently has only 2 of \~15 constraints covered per Coverage Map.
- [shared] Add a `TestResolveServiceRoot` class covering both branches of `resolve_service_root` (normal-Python `Path(module_file).resolve().parents[1]` and the PyInstaller `sys._MEIPASS` frozen-bundle path) plus all three tiers of `resolve_deployment_mode` (explicit arg → `BLARAI_RUNTIME_MODE` env → HOST default): both helpers have zero direct coverage today per Coverage Map, so a PyInstaller-frozen regression would manifest only at production launcher start.
- [launcher] Add tests that drive `_run_uat2_prompt_flow_preflight()` to success and to failure and read the written evidence JSON to confirm `PROMPT_FLOW_FAILED` fingerprint shape plus disposition transitions, and exercise the `_record_activation_evidence` / `_record_prompt_flow_evidence` env-var precedence paths: the UAT2 prompt-flow preflight gate is entirely untested in isolation per Coverage Map, including the `main()` failure branch and the three helper methods.
- [launcher] Enumerate the eight failure branches of `guest_deploy._validate_vsock_topology` (missing evidence, non-JSON evidence, non-PASS disposition, `vm_id` mismatch, `service_guid` mismatch, `vsock_port` mismatch, `connection_successful=False`, `tcp_ip_used=True`) plus the two branches of `_validate_guest_runtime_configs` (PA-invalid, AO-invalid) as parametrized tests asserting fingerprint codes and dispositions: these are the only gates preventing deployment onto a misconfigured VM and currently have zero failure-path coverage per Coverage Map.
- [launcher] Add a test that exercises `vm_manager.request_elevation()` directly — the Windows `ShellExecuteW` >32 success condition and both `AttributeError` / `OSError` fallback branches: the primary gate protecting every Hyper-V operation has zero direct coverage per Coverage Map (`test_requests_elevation_when_not_admin` patches the helper wholesale).
- [launcher] Add the nine `P5_*` failure-code parametrized tests for `test_guest_deploy.py` (`P5_GSI_DISABLED`, `P5_VSOCK_TOPOLOGY_INVALID`, `P5_POLICY_CONFIG_INVALID`, `P5_ORCH_CONFIG_INVALID`, `P5_GUEST_CHANNEL_NOT_READY`, `P5_BUNDLE_BUILD_FAILED`, `P5_COPY_BUNDLE_FAILED`, `P5_COPY_BOOTSTRAP_FAILED`, and extend the existing `P5_VM_START_FAILED` test to assert the full fingerprint dict shape): only `P5_VM_START_FAILED` is currently covered per Assertion Quality Findings, leaving eight fail-closed error-code paths untested.
- [launcher] Add three `ConfigResolutionError` tests to `test_launcher.py` (launcher-level mode resolution, PA `from_runtime_mode`, AO `from_runtime_mode`) asserting `main() == 1` and the correct fingerprint code, and extend `test_production_happy_path` with `gateway.check_pa_status.assert_awaited_once()`, `mock_prompt_flow.assert_called_once()`, and a `tmp_path`-based `BLARAI_ACTIVATION_EVIDENCE_PATH` read confirming `disposition == "PASS"`: the three fail-closed error-code branches have no coverage and the happy-path test asserts only mock construction per Assertion Quality Findings.
- [ui_shell] Replace the non-functional `TestBlarAIAppActionGuards` and `TestBlarAIAppAPIWiring` test classes with functional guard invocations using the `query_one` stubbing pattern already proven by `TestBootPhase3P113`, and exercise `action_submit_prompt` through the gateway mocks with `gateway.send_prompt.call_args` inspection: the central user-facing handler's three branches (PGOV-denied, PGOV-approved, RuntimeError / generic Exception) and the operational guards are entirely unexercised today per Assertion Quality Findings and Coverage Map.
- [cross-service: policy_agent, assistant_orchestrator, integration] Rename stale NPU identifiers across the three clusters and coordinate with the service-constants re-export rename so integration imports follow: PA `_make_npu_stub` helper, PA `TestPipelineWithNPUStub` and `TestEndToEndWithNPUStub` class names, AO `test_gpu_inference.py` class docstrings and `RuntimeError("NPU fault")` mock exception, and integration `_make_npu_allow` / `_make_npu_deny` helpers + `NPU_PRIORITY as PA_PRIORITY` / `ORCH_PRIORITY` import aliases + Group D `TestPreemptionSignalPropagation` docstring: stale architectural assumption per rubric — a future engineer could assume the NPU is architecturally relevant in the P1 Core Loop when ADR-011 explicitly retired it. Source: Stale Test Inventory.

### MEDIUM Priority

- [policy_agent] Flesh out `boot.py` THIN coverage (action-exception path in `MeasuredBootStep.action()`, `BootState.failed_step` property, `dev_mode` parameter effect, `retry_delay_s` variance) and add assertions for the five step-specific boolean fields (`attestation_verified`, `weights_verified`, `model_loaded`, `rule_engine_loaded`, `listener_started`) to `test_run_measured_boot_success_sets_ready`: per Coverage Map and Assertion Quality Findings, boot-robustness contract is incompletely specified and a step-field typo would pass today.
- [policy_agent] Add a time-based sliding-window expiry test to `RateLimiter` (likely via an injected mock clock or `freeze_time`): the core behavioral invariant is tested only implicitly via `reset()` per Coverage Map — the unused `time` import in `test_rate_and_resource_rules.py` suggests an unfinished intent.
- [policy_agent] Add tests for string `sensitivity` normalization and `parameters_schema` field propagation through `build_car()`: normalization coverage parity gap per Coverage Map — string `verb` is covered, string `sensitivity` is not.
- [assistant_orchestrator] Add `TestPIIDetection` cases for the `CREDIT_CARD` and `HEX_SECRET` patterns in `_PII_PATTERNS`: both are defined in production and executed in the PGOV pipeline but never exercised per Coverage Map and Assertion Quality Findings.
- [assistant_orchestrator] Add complementary negative assertions to `TestTokenBreaker::test_at_limit_trips` (`state.depth_tripped is False`) and `TestDepthBreaker::test_at_limit_trips` (`state.token_tripped is False`) and add branch tests for over-limit tokens, simultaneous token+depth trip, and `new_request()` reset: per Assertion Quality Findings and Coverage Map, current tests cannot distinguish single-axis trips from dual-axis bugs.
- [semantic_router] Add a router test constructed with the production-default constants (`CONFIDENCE_THRESHOLD=0.50`, `CONFIDENCE_MARGIN=0.04`) and verify classification at a known decision boundary: `TestConfidenceThresholdBehavior` currently uses extreme values (0.99 / 0.01) that cannot detect a regression of the deployed defaults per Assertion Quality Findings.
- [ui_gateway] Add a `STREAM_TOKEN_BUFFER_LIMIT` overflow-break test using `monkeypatch.setattr(transport_module, "STREAM_TOKEN_BUFFER_LIMIT", N)`: the primary fail-closed guard against runaway token streams is unexercised per Coverage Map — the same value-anchoring pattern is already established by `test_tool_call_buffer_overflow_fail_closed`.
- [ui_gateway] Tighten transport weak assertions: replace trivially-true `len(tokens) >= 0` in `test_server_disconnect_during_stream` with a deterministic shape assertion; add `is_tool_call` field assertions to `test_stream_tokens_buffers_tool_calls`; extend `TestLivePGOVResult::test_cache_hit_returns_result` with `request_id` and `reason_codes` assertions: per Assertion Quality Findings, current assertions accept passing results for genuine regressions.
- [ui_gateway] Apply the `asyncio.sleep` monkey-patch (already established by `test_check_pa_status_state_failed`) to `test_handshake_fails_with_no_port` and `test_handshake_fails_with_unreachable_port`: consistency bug adds \~6 s of real wall-clock time to the unit suite per Assertion Quality Findings.
- [ui_shell] Add targeted tests for `_ensure_session` (both branches), `action_new_session`, `action_delete_session`, `on_input_submitted`, and the boot-poll `HANDSHAKING` attempt-marker progression (ticks 2/3 and 3/3) using the `query_one` stubbing pattern: `app.py` PARTIAL coverage per Coverage Map leaves these untested.
- [ui_shell] Add a dedicated `session_panel.py` test file exercising `refresh_list`, `create_new_session`, `delete_current_session`, `select_session`, `on_mount`, and `active_session_id`, with explicit assertions that each sync `SessionStore` call is wrapped in `asyncio.to_thread()`: zero dedicated coverage per Coverage Map — a regression omitting `to_thread` would block the Textual event loop silently.
- [ui_shell] Replace the assignment-posing-as-assertion in `test_hide_sets_display_none` with `assert panel.styles.display == "none"` (matching the sibling `test_display_denial_sets_block_display`), and add `assert "X"*201 not in rendered` to `test_display_denial_truncates_long_text` to pin the truncation upper bound: per Assertion Quality Findings, `PGOVPanel.hide()` display-reset is effectively unverified today and truncation is satisfied by any ≥200-X string.
- [shared] Add a `TestMessageFramerUIGatewayEncoders` class with encode → `MessageFramer.decode` round-trip coverage for all six UI-gateway encoders (`encode_handshake_request`, `encode_handshake_response`, `encode_prompt_request`, `encode_stream_token`, `encode_pgov_result`, `encode_generation_complete`): these are exercised only under the slow-marker `tests/integration/test_p114_ui_end_to_end.py` per Coverage Map and Assertion Quality Findings — a payload-field regression (e.g. dropping `is_thinking` from `encode_stream_token`) would pass the REGRESSION suite.
- [shared] Capture the server-side `VsockTransport` in `TestVsockMTLS::test_mtls_roundtrip` and `assert accepted[0].peer_cn == "BlarAI Test Client"`, and add `assert "DECODE" in (result.error or "")` to `test_stage1_empty_token_rejected` to match its garbage-token sibling: per Assertion Quality Findings, mTLS + peer-identity exposure is unpinned on the full round-trip and empty-token rejection discriminates no error class.
- [shared] Reshape `test_rejection_count_increments` to validate one valid token (expect counter == 0) then invalidate another (expect counter == 1), demonstrating the counter responds only to failures: per Assertion Quality Findings, the current final-state assertion would pass a regression bumping the counter on every validation.
- [launcher] Add `mock_ps.call_count` assertions to `test_copy_file_to_vm_failure` (expect 3) and `test_copy_file_to_vm_success` (expect 1), monkey-patch `time.sleep` to avoid paying the real retry-delay, and add coverage for `start_vm` / `stop_vm` polling-timeout branches plus `_run_ps` `subprocess.TimeoutExpired` and `FileNotFoundError` sentinel branches: per Assertion Quality Findings and Coverage Map, retry-count invariants and timeout-arithmetic regressions are currently undetectable.
- [launcher] Replace the ad-hoc `_State` class-stub in `test_deploy_guest_runtime_success` with `VMState.OFF`, swap the scattered top-level asserts for a single structural expected-payload dict (redacting volatile fields like `timestamp`), and add a real-path `_build_bundle` success test plus a `_zip_directory` recursive-walk test: per Assertion Quality Findings and Coverage Map, the evidence schema is unasserted and the bundle builder is patched wholesale.
- [launcher] Add coverage for `__main__.py` PARTIAL branches: `_cleanup()` atexit handler (service-stop / store-close / VM-stop order and guard conditions), `_vm_was_started` bookkeeping (set True only when VM transitioned), `SessionStore` init failure branch, TUI-crash exception handler (`LAUNCHER_TUI_RUNTIME_ERROR` fingerprint), PA `ConfigResolutionError` construction branch, AO `ConfigResolutionError` construction branch, and `SESSION_DB_PATH="" → ":memory:"` fallback: per Coverage Map, each branch is unexercised and carries fail-closed fingerprint semantics.
- [integration] Strengthen the weak-assertion cluster: rewrite at least one of the four Group G dataclass-hydration tests to drive real pipeline code (with model boundary mocked) asserting `latency_ms` population; value-anchor or delete `test_p114_stream_token_buffer_limit_constant_present` (superseded by `test_stream_token_buffer_limit_respected`); extend `test_adjudication_context_has_latency_breakdown` with `ctx.decision == AdjudicationDecision.DENY` and `ctx.npu_result.error is not None`; replace `test_out_of_scope_query_denied`'s tautological literal-construction with a real `SemanticRouter.classify()` gibberish-input assertion plus negative pipeline verification; clean up the `_, decision = run_rule_engine(car, ...), adjudicate(...)` double-invocation in `test_pipeline_request_id_chain`: per Assertion Quality Findings, these tests pass values they themselves supplied literally.
- [cross-service: ui_gateway, shared] Relocate 23 live-TCP tests from unit-test directories to new integration files with module-level `pytestmark = pytest.mark.slow` per governance §6 boundary rule: the 11 enumerated `services/ui_gateway/tests/test_transport.py` Live tests to `tests/integration/test_ui_gateway_ipc.py`, and the 12 enumerated `shared/tests/test_ipc_transport.py` tests to `tests/integration/test_shared_ipc_transport.py`. Source: Boundary Violations.
- [cross-service: assistant_orchestrator, shared] Extract key-pair and JWT minting into a shared test utility (e.g. `shared/tests/_keygen.py` or root `tests/conftest.py`) so `services/assistant_orchestrator/tests/test_entrypoint.py` and `shared/tests/test_jwt_validator.py` no longer import from `services.policy_agent.src.jwt_minter`: per Boundary Violations, the current layering inversion couples AO tests and shared tests to PA's API.
- [integration] Relocate the 19 non-cross-service tests currently under `tests/integration/test_p114_ui_end_to_end.py` to their correct service-level test files (`services/ui_gateway/tests/test_session_store.py`, `services/ui_gateway/tests/test_transport.py`, `services/ui_shell/tests/test_pgov_display.py`) and reconcile duplicates with the coverage already recorded in those files per Boundary Violations: these 19 tests are deselected from REGRESSION by the slow marker despite exercising single-service logic.
- [integration] Add targeted integration tests for the documented cross-service surface gaps: `ui_gateway` + `policy_agent` over IPC handshake + authorization, `ui_shell` → gateway → orchestrator → PA prompt flow, boot-phase-3 → prompt → PGOV-denial full stack, `launcher.__main__._run_uat2_prompt_flow_preflight`, `launcher.guest_deploy.deploy_guest_runtime` end-to-end (Hyper-V boundary mocked), and `shared.ipc.vsock` mTLS under the full PA ↔ gateway topology: per Coverage Map, no integration test currently exercises any of these paths.
- [launcher] Add `guest_deploy` branch coverage for GSI-disabled, copy-probe failure, copy-bundle failure, copy-bootstrap failure, `_zip_directory` recursive walk, and `_parse_args()` CLI plumbing (including the `include_models = not args.exclude_models` inversion): per Coverage Map, these branches are patched wholesale or not exercised in the single happy-path success test.

### LOW Priority

- [cross-service: policy_agent, assistant_orchestrator, semantic_router, ui_gateway, ui_shell, shared] Add one constants-regression test per cluster asserting each production-critical `constants.py` value (e.g. `PROBABILISTIC_CONFIDENCE_THRESHOLD == 0.75`, `ESCALATION_CONFIDENCE_RANGE == (0.50, 0.75)`, `PGOV_COSINE_THRESHOLD == 0.85`, `CONFIDENCE_THRESHOLD == 0.50`, `STREAM_TOKEN_BUFFER_LIMIT == 4096`, `PROMPT_MAX_CHARS == 4096`, `VSOCK_PORT == 50000`, `PA_DEVICE == "GPU"`, `AO_DEVICE == "GPU"`): per Coverage Map, `constants.py` is UNCOVERED-implicit across six clusters — low-ROI per rubric because constants are exercised transitively, but a direct-value regression would otherwise propagate indirectly.
- [policy_agent] Consolidate `test_adjudicator.py` into `test_hybrid_adjudicator.py::TestAdjudicatePureFunction` (Group I) after porting the unique `test_npu_deny_label` scenario, then delete the standalone file: per Stale Test Inventory, the standalone file adds one unique case and creates duplicate-maintenance burden for any `adjudicate()` API change.
- [ui_shell] Tighten minor assertion polish: add `assert display.is_streaming is False` after tool-call append in `test_tool_call_token_written_directly`; tighten `TestSessionReload::test_on_list_view_selected_loads_turns` separator check to `any("─" * 40 in line for line in display_lines)`; migrate the same test to `@pytest.mark.asyncio` + direct `await` to retire the deprecated `asyncio.get_event_loop()` pattern. Source: Assertion Quality Findings.
- [ui_gateway] Add unit tests for transport minor branches (`_open_prompt_transport`, `send_prompt` "transport.send returned False" + generic `Exception`, `stream_tokens` malformed-message `continue` + unexpected-message-type ignore, `check_pa_status` short-circuit when already connected, `_attempt_pa_handshake` close-on-non-OPERATIONAL `close()` invocation) and `session_store` minor gaps (`close()`, `get_turns()` alias, `set_active_session` nonexistent UUID silent behavior, `add_turn` `IntegrityError` Python-side behavior): per Coverage Map.
- [shared] Add a dedicated `schemas/car.py` test file covering `canonical_hash()` determinism under field permutation, `is_complete()` boolean semantics, UTC timestamp default factory, `request_id` required-field enforcement, `ActionVerb` / `Sensitivity` / `AdjudicationDecision` enum round-trips, and `DecisionArtifact` validators (`confidence` bounds, `expiry_seconds` default 5, `issuer` default `"policy_agent"`); plus one test each for `load_manifest` hex-64 digest-shape validation, `ipc/vsock._recv_exact` partial-read loop, and `MessageFramer.decode` `UnicodeDecodeError` vs `JSONDecodeError` discrimination: per Coverage Map, all are indirect-only today.
- [launcher] Add `vm_manager.py` minor branch coverage: `stop_vm` non-force branch, `_run_ps` `FileNotFoundError` branch, `is_guest_service_interface_enabled` non-zero-exit error branch, `get_vm_state` `Starting` / `Saved` / `Paused` enum values, and the `ensure_vm_running` single-line wrapper. Source: Coverage Map.
- [integration] Tighten the `pytest.raises(ValueError, match="buffer exceeded")` match pattern in `test_tool_call_buffer_overflow_fail_closed` to the exact production message or a constant-value reference, matching the value-anchored rigor of the sibling stream-buffer test. Source: Assertion Quality Findings.
- [ui_shell] Add value-anchored assertions for `PGOV_REASON_LABELS` individual string values and `PROMPT_MAX_CHARS`: per Coverage Map, the current `len(label) > 5` check would pass a typo rewriting `"PII detected and redacted"` to nonsense.

### Synthesis Summary

45 remediation items identified across three tiers (13 HIGH, 24 MEDIUM, 8 LOW). Dominant themes: (1) fail-closed tests that omit structured error-code assertions, recurring across policy_agent, assistant_orchestrator, and launcher clusters; (2) untested exact-threshold boundaries at critical decision surfaces (escalation floor 0.50, PGOV leakage 0.85, dual-gate 0.50 / 0.04); (3) zero-coverage helpers on primary gates (Hyper-V UAC elevation, vsock topology validation, UAT2 prompt-flow preflight, runtime-config resolvers); (4) stale NPU nomenclature post-ADR-011 persisting across three clusters; (5) boundary-rule violations (23 live-TCP tests mis-placed in unit directories, two cross-service imports inverting layering, 19 non-cross-service tests mis-placed in integration); (6) `constants.py` UNCOVERED-implicit status across six clusters, consolidated as a single cross-service LOW item. Task 7 acceptance criteria are met; Tier 3 fail-safe is not invoked.

---

## Pre-existing Skip Analysis

### Skip 1 — shared/tests/test_runtime_config.py (first symlink skip site)

- **Test function name:** `TestSymlinkGuard::test_symlink_rejected`
- **Skip reason string (verbatim):** `"Symlink creation requires elevated privileges on this system."`
- **Production behavior covered:** `shared.runtime_config.resolve_service_config_path()` must raise `ConfigResolutionError(code="CFG_SYMLINK_REJECTED")` when the target config file is a symlink. The test constructs a real file outside the config dir, creates a symlink to it at `config/default.toml`, then asserts the resolver rejects the symlink with the `CFG_SYMLINK_REJECTED` error code. The symlink guard is the sole defense against pointer-swap attacks on service config resolution.
- **Platform sensitivity:** POSIX platforms (Linux, macOS) permit unprivileged symlink creation. Windows requires either Developer Mode or administrator privileges for `CreateSymbolicLinkW`. The helper `_can_symlink(tmp_path)` (lines 20-32) attempts a probe symlink and returns False on `OSError` or `NotImplementedError`, making the skip self-selecting based on the runtime environment's privilege level rather than a static platform check.
- **Disposition:** **KEEP** — rationale: the skip is privilege-driven, not correctness-driven. On elevated Windows shells, POSIX developer machines, and CI runners with sufficient privileges, the test executes and provides coverage of the `CFG_SYMLINK_REJECTED` path. On unelevated shells it degrades gracefully rather than failing spuriously. Removing the skip would convert an environmental constraint into a hard failure without improving coverage. The probe-helper pattern is appropriate and matches industry convention for privilege-sensitive filesystem tests.

### Skip 2 — shared/tests/test_runtime_config.py (second symlink skip site)

- **Test function name:** `TestSymlinkGuard::test_symlink_guard_message_contains_path`
- **Skip reason string (verbatim):** `"Symlink creation requires elevated privileges on this system."`
- **Production behavior covered:** The `CFG_SYMLINK_REJECTED` error's `message` field must contain the offending path (specifically the filename `default.toml`). Distinct from Skip 1, which verifies the error code; this test verifies the human-readable diagnostic string. Taken together, the two tests pin the contract that the symlink guard both fails with a specific code AND produces a path-bearing message for operational triage.
- **Platform sensitivity:** Identical to Skip 1 — POSIX permits unprivileged symlink creation; Windows requires elevation. The test uses the same `_can_symlink(tmp_path)` probe helper and degrades identically.
- **Disposition:** **KEEP** — rationale: same privilege-driven self-selection as Skip 1. The two tests are paired: removing either leaves half the `CFG_SYMLINK_REJECTED` contract unpinned (either code without message, or message without code). The skip guards test execution rather than assertion strength; it does not mask correctness gaps.

### Skip Disposition Summary

- Skip 1: **KEEP**
- Skip 2: **KEEP**
- Collective recommendation: both KEEP. Both skip sites implement the same privilege-driven self-selection via the `_can_symlink(tmp_path)` probe helper, producing graceful degradation on systems that cannot create symlinks (notably unelevated Windows shells) while preserving full coverage on POSIX developer machines, elevated Windows shells, and CI runners with sufficient privileges. Neither skip masks a production-code defect or an assertion-quality issue; both are environmental gates. A follow-on architectural consideration (recorded here as a narrative recommendation, not an EA-5 action) is to add a CI matrix job with explicit symlink-capable configuration so that the two tests are always exercised in at least one scheduled pipeline run, making privilege coverage empirical rather than host-dependent. Introducing such a CI configuration is outside Task 7 scope and would not modify either production or test code.