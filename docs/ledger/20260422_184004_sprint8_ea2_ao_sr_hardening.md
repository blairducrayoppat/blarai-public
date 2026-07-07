---
ledger_id: 20260422_184004_sprint8_ea2_ao_sr_hardening
date: 2026-04-22
sprint_id: 8
entry_type: EA
predecessor: 20260422_181301_sprint9_ea2_runtime-resilience
branch: feature/p5-task8-ea2-ao-sr-hardening
merge_commit: null
disposition: COMPLETE
---

## Task 82 / EA-2: AO + Semantic Router Test Hardening

### Summary

Boundary-inclusive, constants-pinned, and isolation-focused test additions
for the Assistant Orchestrator (AO), Semantic Router (SR), and UI Shell
PGOV panel — closing the coverage gaps called out in the Sprint 7 Test
Quality Audit for the AO/SR slice. Scope held strictly to test files and
this ledger entry; zero production code modified (L-15 production-file
prohibition).

### Deliverables

| WI | Artifact | Coverage Added |
|---|---|---|
| WI-1  | `services/assistant_orchestrator/tests/test_pgov_boundaries.py` (new) | Exact-0.85 leakage-threshold denial + just-below approval |
| WI-2  | `services/semantic_router/tests/test_dual_gate_thresholds.py` (new) | Mock-centroid dual-gate (threshold × margin) + injection overrides |
| WI-3  | `TestAssistantOrchestratorConfigValidation` in `test_entrypoint.py` | 13 out-of-range failure codes (device, priority, temperature, top_k, top_p, repetition_penalty, max_new_tokens, vsock_cid/port, timeout, max_message_bytes, PGOV threshold, response_depth_mode) |
| WI-4  | `TestAssistantOrchestratorHeartbeat` in `test_entrypoint.py` | HEARTBEAT → HEARTBEAT response, request_id preservation, no inference side-effects |
| WI-5  | `TestAssistantOrchestratorStopIsolation` in `test_entrypoint.py` | Idempotent `stop()`, pre-start safety, `_stop_event` set, resolved state cleared |
| WI-6  | `test_circuit_breaker.py` expansion | Over-limit trip, both-breaker simultaneous trip, `new_request()` reset isolation |
| WI-7  | `test_pgov.py` PII additions | `CREDIT_CARD` (Visa + AmEx), `HEX_SECRET` (≥32 hex), short-hex regression |
| WI-8  | `services/assistant_orchestrator/tests/test_constants_ao.py` (new) | AO re-exports pinned to `shared.constants` ground truth + PGOV flag + generation defaults |
| WI-9  | `services/semantic_router/tests/test_constants_sr.py` (new) | SR re-exports, P1.7-calibrated threshold/margin, device/runtime metadata |
| WI-10 | `services/ui_shell/tests/test_pgov_display.py` line 121 | Replaced silent `panel.styles.display = "none"` self-assignment with `assert` (latent bug — test asserted nothing) |
| —    | This ledger entry | — |

### Gate Results

| Gate | Command | Outcome |
|---|---|---|
| COMPILE | `python -c "from <modified-modules> import *"` | PASS (IMPORTS OK) |
| TEST — focused | `pytest test_pgov_boundaries test_constants_ao test_pgov test_circuit_breaker test_constants_sr test_dual_gate_thresholds test_pgov_display -q` | 137 passed |
| TEST — entrypoint | `pytest test_entrypoint.py -q` | 30 passed |
| TEST — full regression | `pytest shared/ services/ -q` | 861 passed, 2 skipped (baseline 835 passed → +26) |
| ORACLE | `git diff HEAD --name-only \| grep -vE "tests\|conftest\|docs\|pyproject"` | EMPTY — tests-only scope holds |

### Scope Discipline (L-15)

- Zero `src/` files touched. Scope strictly `tests/**` + this ledger.
- No new dependencies, no runtime behavior change, no config defaults altered.
- WI-10 fixed a latent test-bug (assignment instead of assertion) — no
  production-side implication; the behavior being asserted already works.

### Notable Implementation Notes

- **Leakage boundary** (WI-1): operator `>=` is inclusive, so exact-0.85
  rejects. Test pins this as a standing invariant.
- **SR dual-gate** (WI-2): built a `_make_router_with_scores` helper that
  assembles 2-D unit centroids whose dot product against a fixed `[1, 0]`
  query vector yields the exact requested similarity — no ONNX model
  required, full determinism.
- **Config validation** (WI-3): exercised via `service.start()` with
  TOML mutations (string-level substitutions on the minimal valid
  config), covering all 13 enum/range constraints in one class.
- **Stop isolation** (WI-5): asserts `_resolved_config`, `_inference`,
  `_listener`, `_loop_thread`, `_jwt_validator` all release to `None`
  post-stop, and a second `stop()` is a no-op (sticky release, not
  double-free).

### Follow-ups

None. Sprint 7 EA-2 test-quality audit slice for AO/SR is closed.

### Cross-References

- Comprehension report: `docs/sprints/sprint_8/reports/20260422_173441_ea_code_comprehension_v1.md`
- SDO comprehension-review approval: Vikunja Task 82 comment #291
- EA queue prompt: `docs/scheduled/ea_queue/P5_TASK8_EA2_AO_SR_HARDENING.xml`
