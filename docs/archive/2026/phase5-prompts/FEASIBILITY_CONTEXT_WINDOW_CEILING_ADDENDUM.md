---
title: FEASIBILITY_CONTEXT_WINDOW_CEILING_ADDENDUM
status: archived
area: portfolio
---

# P5-FEASIBILITY-003 — Runtime Ceiling Characterization and Containment Validation Addendum

**Date:** 2026-02-26 (UTC)  
**Branch:** `feature/p1-uat1-launcher`  
**Baseline:** `docs/FEASIBILITY_CONTEXT_WINDOW.md`, `docs/FEASIBILITY_CONTEXT_WINDOW_ADDENDUM.md`  
**Scope:** Runtime ceiling characterization and fail-closed containment validation only (no context-window expansion decision)

---

## 1) Milestone Outcome (Dual Disposition)

### 1.1 Runtime Ceiling Characterization

- **Status:** **NOT CHARACTERIZED**
- **Disposition:** **NO_DECISION**
- **Reason code:** `INSUFFICIENT_EVIDENCE`

Observed boundary from this run:
- `last_passing_band_user_tokens = null`
- `first_failing_band_user_tokens = 768`
- `effective_ceiling_interval_user_tokens = null`

Source:
- `phase2_gates/evidence/p5_runtime_ceiling_characterization.json`

### 1.2 Over-Ceiling Containment Validation

- **Status:** **VALIDATED (for sampled over-ceiling bands)**
- **Containment behavior:** deterministic fail-closed, no partial-release leakage observed.

Evidence highlights:
- Over-ceiling bands sampled: `768, 896, 960, 992, 1008, 1024, 1040, 1088, 1152, 1280, 1320`
- `partial_release_failures = 0` for all sampled bands
- Deterministic fingerprint family observed across sampled failures:
  - `AO_MAX_PROMPT_LEN_*` (single dominant deterministic fingerprint)

Sources:
- `phase2_gates/evidence/p5_runtime_ceiling_containment_validation.json`
- `phase2_gates/evidence/p5_runtime_ceiling_containment_contract.json`

---

## 2) Artifacts Produced

1. `phase2_gates/evidence/p5_runtime_ceiling_probe_protocol.json`
2. `phase2_gates/evidence/p5_runtime_ceiling_characterization.json`
3. `phase2_gates/evidence/p5_runtime_ceiling_containment_validation.json`
4. `phase2_gates/evidence/p5_runtime_ceiling_containment_contract.json`

All artifacts include deterministic metadata (`commit_hash`, `profile`, `model_identifier`, timestamp).

---

## 3) Empirical Findings

## 3.1 Characterization Path

- In this harness run, all sampled bands failed with deterministic fail-closed behavior.
- Even the lowest sampled characterization band (`768` user tokens) produced prompt formatting/tokenization totals exceeding stateful NPU prompt-history limits in this runtime path.
- Reproducibility reruns on boundary-critical bands remain deterministic in fingerprint family, but contain no successful runs; therefore no defensible pass/fail interval can be asserted.

## 3.2 Containment Path

- Failure handling remained fail-closed with deterministic fingerprints and explicit error payloads.
- No generated partial text/tokens were released on sampled failing bands (`partial_release=false`, aggregate `partial_release_failures=0`).
- This supports a bounded conclusion that containment behavior is stable for the sampled over-ceiling region in this environment.

---

## 4) Quality Gate and Governance Result

Quality-gate result embedded in containment contract:
- `all_pass = false`
- Gate failures include critical coverage requirement (`EQG-02`) and dependent critical-band coverage (`EQG-09`).
- Enforced milestone disposition remains:
  - `NO_DECISION`
  - `reason_code = INSUFFICIENT_EVIDENCE`

Harness declaration remains:
- `NO_FULL_HARNESS`
- Unsampled regions are explicitly declared with impact statements in generated artifacts.

---

## 5) Required Follow-On Evidence (No Expansion Decision in This Milestone)

To characterize a runtime ceiling interval rather than a first-fail-only boundary:

1. Introduce/validate a probe path that preserves measured user-band intent while controlling formatted prompt overhead and stateful history effects.
2. Re-run boundary-critical bands with sufficient successful coverage (`>= 30` valid combined warm/cold per critical point).
3. Maintain deterministic fingerprint distributions and `partial_release` proofs for all failing sampled bands.
4. Keep fail-closed dispositioning (`NO_DECISION/INSUFFICIENT_EVIDENCE`) until critical-band evidence thresholds are met.

---

## 6) Milestone Constraint Compliance

- Context-window expansion decision: **Not performed**
- Token-limit implementation changes: **None**
- ADR lock modifications (ADR-005/006/010): **None**
- Privacy/local-only and fail-closed policy: **Maintained**
