---
role: ea_code
phase: comprehension
revision: 1
tracking_task: 82
vikunja_comment: 289
posted_at: 2026-04-22T17:34:41Z
verdict: null
---

# [agent:ea_code][phase:comprehension] Task 8 EA-2 — AO + Semantic Router Test Hardening — Comprehension v1

## Wake Template Recitation

**Source**: `tools/scheduled-tasks/wake-templates/ea_code.md` (EA in Code — Scheduled Wake-up Template).
Section headers invoked verbatim:

- Phase 0 — Fleet-blocked exit
- Event-driven wake triggers (Q2-1)
- Your scope for this firing
- State machine (DEC-12) — Case A / B / C / D / E / F
- Formatting standard for Vikunja descriptions and disk reports (DEC-14.5)
- Report emission (DEC-13)
- M5 Comprehension Gate content
- Budget self-check
- Exit criteria
- Links

**`--allowedTools`** scope for this role: `mcp__vikunja__* Read Write Edit Bash mcp__git__*`. Session cap 90 min. TTG 2 h.

**State verdict**: Task 82 Sprint 8 EA-2 is **Case A** (fresh — no prior `[agent:ea_code][phase:comprehension]` for EA-2 on this task; task carries `Gate:Pending-Execution`; queue file `P5_TASK8_EA2_AO_SR_HARDENING.xml` present and valid).

## EA Prompt Recitation

Source: `docs/scheduled/ea_queue/P5_TASK8_EA2_AO_SR_HARDENING.xml` (authored by SDO 2026-04-22).

### A. MILESTONE OBJECTIVE

Close all test coverage, assertion-quality, and boundary-verification gaps in the `assistant_orchestrator` (AO) and `semantic_router` (SR) service clusters identified by the Sprint 7 audit in `docs/TEST_AUDIT_FINDINGS.md`. Scope spans: AO PGOV leakage exact-point boundary (`cosine_similarity == 0.85`); SR dual-gate exact-point boundaries (similarity `== 0.50`, margin `== 0.04`, margin `== 0.03`) via mock-controlled centroids and embeddings; AO `entrypoint.py` config-validation coverage (≥ 6 of ~13 uncovered constraints, all 13 preferred under mature-not-minimal); AO `entrypoint.py` HEARTBEAT handling; AO `entrypoint.py` `stop()` isolation; `circuit_breaker.py` over-limit-token / simultaneous-trip / `new_request()` reset paths; `pgov.py` CREDIT_CARD + HEX_SECRET PII pattern tests; direct-constants assertion test files for AO and SR; and the `pgov_display.py` `hide()` assignment-posing-as-assertion bug fix. **No production code is modified.** All work is pure test-authoring.

### B. WORK ITEMS

- **WI-1** (HIGH): Create `services/assistant_orchestrator/tests/test_pgov_boundaries.py::TestPGOVLeakageThresholdBoundary::test_leakage_cosine_similarity_at_threshold_rejects` asserting PGOV denial when an injected leakage detector returns exactly `0.85` (the production `PGOV_COSINE_THRESHOLD`).
- **WI-2** (HIGH): Create `services/semantic_router/tests/test_dual_gate_thresholds.py::TestSemanticRouterDualGateThresholds` with three tests that mock-control router centroids + embeddings to exercise similarity `== 0.50`, margin `== 0.04`, and margin `== 0.03` against the current dual-gate classify path, asserting production behavior at each exact boundary.
- **WI-3** (HIGH): In `services/assistant_orchestrator/tests/test_entrypoint.py`, add `TestAssistantOrchestratorConfigValidation` covering ≥ 6 of ~13 uncovered `validate_runtime_config` constraints (all 13 preferred) with each test asserting `ok is False` AND a specific error-code string — not merely a boolean failure.
- **WI-4** (MEDIUM): In `services/assistant_orchestrator/tests/test_entrypoint.py`, add `TestAssistantOrchestratorHeartbeat::test_handle_connection_dispatches_heartbeat` asserting that a framed HEARTBEAT message passes through `_handle_connection` without exception, emits the production response payload, and leaves the connection open.
- **WI-5** (LOW): In `services/assistant_orchestrator/tests/test_entrypoint.py`, add `TestAssistantOrchestratorStopIsolation::test_stop_when_not_running_does_not_raise` (and optional `test_stop_after_start_completes_cleanly` if feasible with existing mocks) asserting idempotent shutdown semantics.
- **WI-6** (MEDIUM): In `services/assistant_orchestrator/tests/test_circuit_breaker.py`, add `test_token_breaker_over_limit_trips`, `test_simultaneous_token_and_depth_cap_trip`, and `test_new_request_resets_breaker_state` covering strictly-over-cap trips, combined token+depth trips, and reset semantics of `new_request()`.
- **WI-7** (LOW): In `services/assistant_orchestrator/tests/test_pgov.py` PII-patterns class, add `test_pii_pattern_credit_card_detected` and `test_pii_pattern_hex_secret_detected` using synthetic 16-digit / 32+ hex strings and asserting the CREDIT_CARD / HEX_SECRET denial codes match production `_PII_PATTERNS` labels.
- **WI-8** (MEDIUM): Create `services/assistant_orchestrator/tests/test_constants_ao.py::TestAssistantOrchestratorConstants` directly asserting `PGOV_COSINE_THRESHOLD == 0.85`, `OUTPUT_TOKEN_CAP`, `TOOL_CALL_DEPTH_CAP`, the default generation params, `AO_DEVICE == "GPU"`, and the stale NPU re-export mapping (current values, no renames).
- **WI-9** (MEDIUM): Create `services/semantic_router/tests/test_constants_sr.py::TestSemanticRouterConstants` directly asserting `CONFIDENCE_THRESHOLD == 0.50`, `CONFIDENCE_MARGIN == 0.04`, and every other behavioral constant in the file (mature-not-minimal — read constants.py end-to-end).
- **WI-10** (MEDIUM): In `services/ui_shell/tests/test_pgov_display.py::TestPGOVPanelLogic::test_hide_sets_display_none` (lines 118-121 at HEAD `29cea32`), replace the assignment `panel.styles.display = "none"` with a real assertion `assert panel.styles.display == "none"`, mirroring the sibling `test_display_denial_sets_block_display` idiom.

### C. FILES TO CREATE

- `services/assistant_orchestrator/tests/test_pgov_boundaries.py` (WI-1)
- `services/semantic_router/tests/test_dual_gate_thresholds.py` (WI-2)
- `services/assistant_orchestrator/tests/test_constants_ao.py` (WI-8)
- `services/semantic_router/tests/test_constants_sr.py` (WI-9)

### D. FILES TO MODIFY

- `services/assistant_orchestrator/tests/test_entrypoint.py` (WI-3, WI-4, WI-5)
- `services/assistant_orchestrator/tests/test_circuit_breaker.py` (WI-6)
- `services/assistant_orchestrator/tests/test_pgov.py` (WI-7)
- `services/ui_shell/tests/test_pgov_display.py` (WI-10 assertion fix)
- `docs/POST_OPERATIONAL_MATURATION_LEDGER.md` (next-free entry — scan at commit time; target ≥ 53 given current highest entry = 52)

### E. FILES TO READ

Production source (context; not modified):

- `services/assistant_orchestrator/src/pgov.py` (PGOVPipeline, `_PII_PATTERNS`, leakage detector seam)
- `services/assistant_orchestrator/src/circuit_breaker.py` (TokenBreaker, BreakerSet/CircuitBreaker, `new_request()`)
- `services/assistant_orchestrator/src/entrypoint.py` (`validate_runtime_config`, `_handle_connection`, `stop()`)
- `services/assistant_orchestrator/src/constants.py` (PGOV_COSINE_THRESHOLD, OUTPUT_TOKEN_CAP, TOOL_CALL_DEPTH_CAP, DEFAULT_* gen params, AO_DEVICE, stale NPU re-exports)
- `services/semantic_router/src/router.py` (classify / dual-gate logic + centroid/embedding injection seam)
- `services/semantic_router/src/constants.py` (CONFIDENCE_THRESHOLD, CONFIDENCE_MARGIN, taxonomy constants)
- `services/semantic_router/src/intents.py` (centroid structures / intent taxonomy)
- `services/ui_shell/src/pgov_display.py` (PGOVPanel.hide() — confirms assertion target)
- `shared/ipc/protocol.py` (HEARTBEAT encoder, if defined)

Existing tests (pattern mirroring):

- `services/assistant_orchestrator/tests/test_pgov.py` (leakage-with-injected-detector + PII patterns)
- `services/assistant_orchestrator/tests/test_circuit_breaker.py` (3 classes / 7 tests — setup style)
- `services/assistant_orchestrator/tests/test_entrypoint.py` (HANDSHAKE + PROMPT dispatch patterns)
- `services/semantic_router/tests/test_router.py` (existing mocking patterns)
- `services/ui_shell/tests/test_pgov_display.py` (sibling `test_display_denial_sets_block_display`)
- `services/policy_agent/tests/test_entrypoint.py` (post-EA-1 config-validation pattern, if merged)

Governance / context:

- `docs/P5_TASK8_SDO_CONTINUATION_v1.0.xml` — §5 ea_decomposition EA-2 block; §6 lessons L-12/L-13/L-15; §7 ea_prompt_guidelines
- `docs/sprints/sprint_8/strategic_design_vision.md` — §5.1 item 2 (EA-2 scope), §5.2 Out-of-scope, §5.3 Edge cases + mature-not-minimal cap, §4 Success Criteria, §13.1 Deferred issues
- `docs/TEST_AUDIT_FINDINGS.md` — Coverage Map (AO + SR), Boundary Violations (0.85 / 0.50 / 0.04 / 0.03), Assertion Quality (ui_shell hide bug), Stale Test Inventory
- `docs/TEST_GOVERNANCE.md` — marker taxonomy, skip list, baseline reporting
- `docs/POST_OPERATIONAL_MATURATION_LEDGER.md` — Entry 50 / 51 / 52 format reference (highest existing entry = 52)
- `docs/IMPLEMENTATION_PLAN.md` — reference only

### F. DELIVERABLE STRUCTURE (VERBATIM)

**Branch name**: `feature/p5-task8-ea2-ao-sr-hardening`

**New files**:

- `services/assistant_orchestrator/tests/test_pgov_boundaries.py`
  - class `TestPGOVLeakageThresholdBoundary`
  - functions: `test_leakage_cosine_similarity_at_threshold_rejects`
  - source WI: WI-1
- `services/semantic_router/tests/test_dual_gate_thresholds.py`
  - class `TestSemanticRouterDualGateThresholds`
  - functions: `test_similarity_at_confidence_threshold_passes_or_escalates`, `test_margin_at_exact_gate_classifies`, `test_margin_just_below_gate_escalates_or_rejects`
  - source WI: WI-2
- `services/assistant_orchestrator/tests/test_constants_ao.py`
  - class `TestAssistantOrchestratorConstants`
  - functions: `test_pgov_cosine_threshold`, `test_output_token_cap`, `test_tool_call_depth_cap`, `test_default_generation_params`, `test_ao_device_constant`, `test_stale_reexports_mapping` (plus any additional behavioral constants discovered end-to-end)
  - source WI: WI-8
- `services/semantic_router/tests/test_constants_sr.py`
  - class `TestSemanticRouterConstants`
  - functions: `test_confidence_threshold`, `test_confidence_margin`, `test_any_other_behavioral_constants` (split as constants.py warrants)
  - source WI: WI-9

**Modified files**:

- `services/assistant_orchestrator/tests/test_entrypoint.py` — add `TestAssistantOrchestratorConfigValidation` (≥ 6 / 13 constraints, each asserts specific error_code), `TestAssistantOrchestratorHeartbeat::test_handle_connection_dispatches_heartbeat`, `TestAssistantOrchestratorStopIsolation::test_stop_when_not_running_does_not_raise` (+ optional `test_stop_after_start_completes_cleanly`).
- `services/assistant_orchestrator/tests/test_circuit_breaker.py` — add `test_token_breaker_over_limit_trips`, `test_simultaneous_token_and_depth_cap_trip`, `test_new_request_resets_breaker_state` (existing-class placement per style).
- `services/assistant_orchestrator/tests/test_pgov.py` — add `test_pii_pattern_credit_card_detected`, `test_pii_pattern_hex_secret_detected` to the existing PII-patterns class.
- `services/ui_shell/tests/test_pgov_display.py` — replace the `panel.styles.display = "none"` assignment on the final line of `test_hide_sets_display_none` (lines 118-121) with `assert panel.styles.display == "none"`. No other changes.
- `docs/POST_OPERATIONAL_MATURATION_LEDGER.md` — append Entry N (next-free; target ≥ 53 at commit time — highest existing entry at this firing = 52) per the Entry 50/51/52 format: branch, commit hash, net new test count, baseline X → Y, date, WI disposition summary, WI-3 residual AO config-validation constraint count.

**Naming conventions**: test classes PascalCase (TestPGOVLeakageThresholdBoundary, …); test functions snake_case starting with `test_`; no numbered prefixes on headers; no rename of any existing class/function/file (stale-name cleanup is EA-5 scope).

**Ledger entry reserved**: 52 per prompt; scan at commit time and use next free (likely ≥ 53 given Sprint 9 EA-1 consumed 52).

### G. ORACLE EXPECTATION (VERBATIM)

```
git diff main...feature/p5-task8-ea2-ao-sr-hardening --name-only | grep -vE "tests|conftest|docs|pyproject"
```

Expected output: **EMPTY** (zero lines). If any production file appears, Sprint 8's pure-test-authoring mandate is violated; STOP and report in completion without attempting auto-fix — the branch is evidence.

### H. MATURE-NOT-MINIMAL 1-HOUR CAP ACKNOWLEDGMENT

I acknowledge the SDV §5.3 / prompt §10 directive: adjacent findings discovered during WI work are in-scope only if each adds ≤ 1 hour of additional work; items exceeding the cap are flagged in the completion report with estimated effort for Co-Lead to open as next-sprint Vikunja tasks — I will NOT absorb them silently. For WI-3 specifically, the floor is ≥ 6 of 13 validate_runtime_config constraints; mature-not-minimal preference is all 13. Residual uncovered constraints will be named and justified in the completion report.

### I. RISKS AND AMBIGUITIES

- **WI-2 mocking seam (HIGH)**: dual-gate exact-point tests require controlled centroids AND a deterministic embedding function. If `router.py` exposes no clean seam (monkeypatch-safe attribute or constructor injection) and the tests would require production-code additions, I STOP per NC-1 and report the blocker — I do NOT add production hooks.
- **WI-3 constraint enumeration**: the prompt lists 13 candidate constraints but notes item 13 is "any additional constraint surfaced in `entrypoint.py` `validate_runtime_config`". I will read the method end-to-end and cover all discoverable constraints; residual misses will be named with rationale (e.g. "covered indirectly by existing test", "requires production change to make testable").
- **WI-3 error-code assertions**: every failure test must assert the specific error-code string, not merely `ok is False`. I will read source to identify codes and will NOT invent strings (NC-11).
- **WI-4 HEARTBEAT encoder availability**: the audit notes encoders exist for handshake/prompt/stream/pgov/generation-complete but HEARTBEAT is not enumerated. If the encoder is missing, I will follow `_handle_connection`'s inbound HEARTBEAT dispatch path directly and assert on the response emitted by production code rather than an encoder indirection — I will not add a new encoder.
- **WI-6 orchestrator class name**: the prompt names `CircuitBreaker` / `BreakerSet` as candidates; I will read source to find the exact class and follow its trip-reporting semantics. I will test what production decides (first-tripped vs combined reason) — I will NOT assume priority.
- **WI-10 scope clarification**: the one-line assertion correction touches `services/ui_shell/tests/test_pgov_display.py` (not an AO test file) per SDV §5.1 item 2 explicit assignment to EA-2. Confirmed in scope.
- **Mock-controlled centroids / embeddings strategy (WI-2)**: plan is monkeypatch of `_centroids` attribute + patching of the embedding function, mirroring any seam `test_router.py` already uses. If neither seam exists, I'll construct the router with injected dependencies if the constructor accepts them; otherwise I STOP.
- **AO config-validation floor of 6/13**: I commit to attempting all 13 and reporting the residual; only if a constraint's test requires source changes do I defer it.
- **pgov_display.hide() test path**: the test lives under `services/ui_shell/tests/`, NOT `services/assistant_orchestrator/tests/`. Confirmed — fix in ui_shell per SDV §5.1 item 2.
- **Ledger entry drift**: highest existing `### Entry N` is 52 at this firing (verified via grep); will use 53 at commit unless further Sprint 9/8 advances consume it.

### J. PRODUCTION FILE PROHIBITION ACKNOWLEDGMENT

Quoted verbatim from prompt NC-1:

> DO NOT modify any file outside tests/, conftest.py, docs/, or pyproject.toml. If a production code change is required to unblock a test, STOP, document the blocker in your completion report, and wait for SDO direction. Do not make the change unilaterally.

I acknowledge this as a HARD constraint; any violation is a branch-preserved audit event per the ORACLE gate.

## Parent-head verification (L-13)

Current main HEAD: **`3d031f2`** (`3d031f280677597e175d0737452a1761f0476200`). Prompt `parent_head` snapshot: `29cea32` at SDO authoring time. Current main has advanced past that snapshot (intervening fleet commits `5d9ed2c`, `6f4c566`, `12b1b58`, `3d031f2`). Per prompt §1, I branch from current main (`3d031f2`), not the snapshot — `feature/p5-task8-ea2-ao-sr-hardening` will be cut from `3d031f2` after SDO approval.

## Plan of work (cross-referenced to WIs)

1. After SDO APPROVE, `git fetch origin && git checkout main && git pull --ff-only && git checkout -b feature/p5-task8-ea2-ao-sr-hardening`.
2. Baseline capture: `.venv/Scripts/pytest shared/ services/ launcher/ --tb=short -q` on main — record X (expected ~813 passed, 2 skipped post-EA-1).
3. Read production files listed in Section E end-to-end (pgov.py, circuit_breaker.py, entrypoint.py, AO + SR constants.py, router.py, intents.py, pgov_display.py).
4. **WI-10 first** (smallest, highest certainty): one-line assertion fix — confirms tooling works.
5. **WI-1** test_pgov_boundaries.py — mirror `test_leakage_with_injected_detector` pattern; assert exact-0.85 denial + production reason code.
6. **WI-7** PII patterns — add CREDIT_CARD + HEX_SECRET tests to existing class; use synthetic inputs.
7. **WI-8** test_constants_ao.py — direct value assertions per read of constants.py.
8. **WI-9** test_constants_sr.py — direct value assertions per read of SR constants.py.
9. **WI-2** test_dual_gate_thresholds.py — mock centroids + embedding function; exact 0.50 / 0.04 / 0.03 tests following production behavior (read `router.py` for inclusive-vs-exclusive comparator).
10. **WI-6** circuit_breaker.py tests — over-limit, simultaneous-trip, new_request() reset (per-class placement matching existing style).
11. **WI-5** `stop()` isolation — test_stop_when_not_running_does_not_raise; optional test_stop_after_start_completes_cleanly if mocks suffice.
12. **WI-4** HEARTBEAT — test_handle_connection_dispatches_heartbeat following HANDSHAKE/PROMPT fixture pattern.
13. **WI-3** config-validation — parametrized ≥ 6 / 13 constraints (target 13); each assertion includes specific error_code string.
14. COMPILE gate: `python -c "import services.assistant_orchestrator.tests.test_pgov_boundaries"` × 4 new files.
15. TEST gate: full regression suite; record Y; verify Y ≥ X (net delta ≥ 15 new tests).
16. ORACLE gate: `git diff main...HEAD --name-only | grep -vE "tests|conftest|docs|pyproject"` — empty.
17. Write ledger entry (next-free; expected 53) per Entry 50/51/52 format.
18. Commit: `test(task8/ea2): AO + semantic_router boundary + isolation + constants hardening — N new tests, baseline X → Y`.
19. Post `[agent:ea_code][phase:completion]` on Task 82 with commit hash, diff, acceptance-check results, WI-3 residual count, any scope deviations.
20. Apply `Gate:Pending-SDO`, remove `Gate:Approved` from comprehension phase.
21. Emit DEC-13 disk report + Fleet Reports task + commit + source-comment cross-reference.
22. Fire `schtasks /run /tn "Wake SDO"` event-driven trigger (Q2-1 post-completion success path).

STOP after posting this comprehension. Implementation begins only after `[agent:sdo][phase:comprehension-review] VERDICT: APPROVED`.
