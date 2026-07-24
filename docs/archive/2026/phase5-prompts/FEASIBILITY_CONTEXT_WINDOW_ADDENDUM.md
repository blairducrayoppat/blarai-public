---
title: FEASIBILITY_CONTEXT_WINDOW_ADDENDUM
status: archived
area: portfolio
---

# P5-FEASIBILITY-002 — Re-Decision Evidence Upgrade Addendum

**Date:** 2026-02-26 (UTC)  
**Branch:** `feature/p1-uat1-launcher`  
**Baseline:** `docs/FEASIBILITY_CONTEXT_WINDOW.md` (P5-FEASIBILITY-001)  
**Scope:** Empirical evidence collection only (no token-limit implementation changes)

---

## 1) Outcome

- **Evidence quality-gate outcome:** **FAIL**
- **Disposition (enforced by EQG-11):** **NO_DECISION**
- **Reason code:** `INSUFFICIENT_EVIDENCE`

Rationale:
- EQG result file shows gate failure on `EQG-02` (critical matrix points with `valid_count >= 30` not satisfied), which forces `NO_DECISION` by policy.

Primary gate evidence:
- `phase2_gates/evidence/p5_redecision_quality_gate.json`

---

## 2) Evidence Artifacts Produced

1. `phase2_gates/evidence/p5_redecision_protocol.json`
2. `phase2_gates/evidence/p5_input_length_latency_matrix.json`
3. `phase2_gates/evidence/p5_output_length_latency_matrix.json`
4. `phase2_gates/evidence/p5_memory_pressure_matrix.json`
5. `phase2_gates/evidence/p5_pgov_stage5_long_output_coverage.json`
6. `phase2_gates/evidence/p5_pa_long_input_stability.json`
7. `phase2_gates/evidence/p5_redecision_quality_gate.json`

All artifacts include commit/profile/model/timestamp metadata and deterministic failure fingerprints.

---

## 3) Empirical Findings (Trace-Mapped)

## 3.1 Input-length matrix

Source: `phase2_gates/evidence/p5_input_length_latency_matrix.json` + `phase2_gates/evidence/p5_memory_pressure_matrix.json`

- Successful coverage exists at the 512-token input band with warm/cold splits and full distributions.
- At and above 1024-target sweep points, repeated Fail-Closed runtime errors occur with deterministic fingerprints indicating a stateful NPU prompt-length ceiling breach:
  - Error signature includes: `data->input_ids.get_size() <= m_max_prompt_len` and `Stateful LLM pipeline on NPU ... up to 1024 tokens`.
- This creates explicit unsampled regions for higher intended input-context bands in this milestone run.

## 3.2 Output-length matrix

Source: `phase2_gates/evidence/p5_output_length_latency_matrix.json` + `phase2_gates/evidence/p5_memory_pressure_matrix.json`

- Output-band points show invalid runs (no successful runs at several points), with explicit missing reasons and counted invalids.
- Because critical points did not reach `>= 30` valid runs, EQG threshold is not satisfied.

## 3.3 PGOV Stage-5 long-output coverage

Source: `phase2_gates/evidence/p5_pgov_stage5_long_output_coverage.json`

- Detector load state is explicitly captured (`loaded=true`).
- Pre/post token-128 placement trials are present with required statistics.
- False-negative/false-positive fields are present per EQG-09.
- Observed detection rates in this run remain low, but interpretation is provisional and bounded by this synthetic placement corpus.

## 3.4 PA long-input stability

Source: `phase2_gates/evidence/p5_pa_long_input_stability.json`

- Bands include required latency distributions and decision agreement rates.
- At least one reproducibility rerun is present.
- This matrix satisfies structural EQG requirements, but overall milestone remains blocked by cross-matrix quality gate failure.

---

## 4) Evidence Quality Gate Summary

Source of truth: `phase2_gates/evidence/p5_redecision_quality_gate.json`

- PASS: `EQG-01, EQG-03, EQG-04, EQG-05, EQG-06, EQG-07, EQG-08, EQG-09, EQG-10, EQG-12`
- FAIL: `EQG-02`
- Enforced NO_DECISION condition: `EQG-11` (dependent on prior failures)

Therefore, by policy:
- **Final disposition must remain `NO_DECISION/INSUFFICIENT_EVIDENCE`.**

---

## 5) Unresolved Gaps and Required Next Evidence Upgrade

To move from `NO_DECISION` to a defensible re-decision:

1. Resolve NPU prompt-length runtime ceiling constraints in the measurement path (currently hard-failing beyond effective 1024-token stateful prompt history in this harness context).
2. Re-run input and output sweeps until each critical point reaches `valid_count >= 30` under warm/cold separation.
3. Preserve deterministic failure fingerprint counting and missing-region impact statements for any remaining unsampled points.
4. Re-evaluate EQG with the updated matrices; only then permit disposition change consideration.

---

## 6) Milestone Disposition (Execution-Bounded)

- **Disposition:** `NO_DECISION`
- **Reason code:** `INSUFFICIENT_EVIDENCE`
- **Token-limit implementation changes:** none
- **ADR lock modifications:** none
