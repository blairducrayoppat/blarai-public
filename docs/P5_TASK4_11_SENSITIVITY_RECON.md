# RECON-1: Sensitivity Fixture Audit
**Milestone**: P5-TASK4.11-EA1 (P0 Security Hardening)  
**Date**: 2026-04-01  
**Status**: COMPLETE — No EA-2 blockers identified

---

## Objective

Audit all test fixtures that construct `CanonicalActionRepresentation` (CAR) objects to determine whether any fixture relies on a `sensitivity` default value that could interact with P0 changes. Verify no test erroneously relies on `UNCLASSIFIED` sensitivity in a path expected to succeed.

---

## Scope

Files searched: `shared/tests/`, `services/policy_agent/tests/`, `tests/`  
Pattern: `sensitivity`, `build_car`, `CanonicalActionRepresentation`

---

## Findings

### 1. `build_car()` default in production code

**File**: `services/policy_agent/src/car.py` line 34  
**Default**: `sensitivity: Sensitivity | str = Sensitivity.UNCLASSIFIED`  
**Assessment**: Intentional Fail-Closed default. `UNCLASSIFIED` triggers `SENSITIVITY_CLASSIFICATION` DENY rule. Correct by design. No change needed.

---

### 2. Test helper fixtures — explicit INTERNAL sensitivity

All major test helpers that build CARs for **positive-path** (ALLOW-expected) flows use **explicit** `Sensitivity.INTERNAL` or higher:

| File | Fixture | Default value |
|---|---|---|
| `test_gpu_inference.py` | `_valid_car()` | `Sensitivity.INTERNAL` (explicit kwarg default) |
| `test_hybrid_adjudicator.py` | `_make_car()` | `Sensitivity.INTERNAL` (explicit kwarg default) |
| `test_integration_car_pipeline.py` | `_make_car()` | `Sensitivity.INTERNAL` (explicit kwarg default) |
| `test_p110_end_to_end.py` | `_build_valid_car()` | `Sensitivity.INTERNAL` (explicit kwarg default) |
| `test_adjudicator.py` | inline `build_car(...)` | `sensitivity=Sensitivity.INTERNAL` (explicit) |

None of these rely on the `build_car()` default. All are safe.

---

### 3. Deliberate `UNCLASSIFIED` usage

Several tests intentionally construct CARs with `Sensitivity.UNCLASSIFIED` to exercise the Fail-Closed DENY path:

- `test_car.py::test_build_car_unclassified_sensitivity_default` — validates default IS `UNCLASSIFIED`
- `test_p110_end_to_end.py` — 4 tests at lines 411, 515, 1093, 1380 — all exercise `SENSITIVITY_CLASSIFICATION` DENY
- `test_hybrid_adjudicator.py` — 6 tests deliberately set `UNCLASSIFIED` to verify NPU is not invoked on DENY
- `test_gpu_inference.py` `_make_car()` at line 550 — `Sensitivity.UNCLASSIFIED` default used in DeterministicPolicyChecker tests only (not GPU inference path)

All deliberate. No accidental usage.

---

### 4. New Group J tests (P5-TASK4.11-EA1)

New test helpers in Group J (`TestValidateParametersSchema`, `TestFormatCarBoundaryDelimiters`) use `build_car()` via local `_bc` alias with explicit `sensitivity=Sensitivity.INTERNAL`. No reliance on defaults. Safe.

---

## Risk Assessment

| Risk | Status |
|---|---|
| Test fixture using UNCLASSIFIED accidentally expecting ALLOW | **NOT PRESENT** |
| EA-2 work (sensitivity default changes) blocked by P0 tests | **NOT PRESENT** — EA-2 scope is `jwt_validator.py` + `runtime_config.py`, no sensitivity changes |
| P0-1 CN tests could trigger sensitivity DENY | **NOT PRESENT** — all Group G CAR JSON uses `"sensitivity": "INTERNAL"` |

---

## Conclusion

No test fixture deficiencies identified. All sensitivity usage in tests is either:
- Explicit `INTERNAL` (positive-path testing)
- Explicit `UNCLASSIFIED` (Fail-Closed path testing)

No EA-2 scope leakage. P0 implementation proceeds safely.
