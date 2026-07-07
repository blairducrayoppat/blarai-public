# Task 4.10 Scope Outline — Workload Profile Lock + ADR-012 §2.2 Finalization

**Status:** DRAFT — For Lead Architect review  
**Pre-condition:** Task 4.9d COMPLETE (agreement 1.000, 40/40, adversarial 1.000) → DEC-10 LOCKED  
**Predecessor:** Task 4.9d (commit `40443b0` on `feature/p5-task4-9-pa-quality-gate`)  
**Type:** DOCS-ONLY (no production code changes)  
**Estimated scope:** Single-session Execution Agent, 5 governance docs + ADR update + 1 evidence JSON  

---

## 1. Purpose

Close out Task 4 by locking all remaining EVALUATING/PROVISIONAL parameters in ADR-012 §2.2,
compiling final workload profile tables, and recording the Task 4 closure milestone in the governance
ledger. After Task 4.10, ADR-012 §2.2 contains ZERO EVALUATING rows — every parameter is LOCKED,
DEFERRED with rationale, or MEASURED (informational).

---

## 2. Remaining EVALUATING Parameters to Lock

### 2.1 Input/output split (currently EVALUATING)

| Current | Proposed Lock | Rationale |
|---------|--------------|-----------|
| \~12,288 input / \~4,096 output | LOCK as ADVISORY GUIDELINE | No empirical study performed (no Task allocated). Value is a heuristic derived from max context window = 16,384. For PA: irrelevant (output is 3-10 tokens). For AO: conversational output naturally varies. For USE-CASE-005: \~75/25 split is industry standard for code completion. Lock as advisory with note: "Not empirically tuned — revisit if output truncation observed in production." |

**SDO recommendation:** Lock as advisory guideline with explicit "not empirically optimized" caveat. Alternatively, retire the row entirely (PA doesn't use it, AO/CODE haven't needed it). Lead Architect to decide: LOCK_ADVISORY vs RETIRE_ROW.

### 2.2 GenConfig fields (currently EVALUATING — composite row)

This is a composite row. Sub-component status:

| Sub-parameter | Current status | Proposed lock |
|---------------|---------------|---------------|
| PA `max_new_tokens` = 10 | LOCKED (DEC-08, Task 4.8) | Already locked — no action |
| `num_assistant_tokens` = 3 | LOCKED (DEC-01, Task 4.3) | Already locked — no action |
| `do_sample` = False | LOCKED (project mandate) | Already locked — no action |
| PA `stop_token_ids` = [151645, 151668] | Specified in §2.4, status not explicit | LOCK with §2.4 citation |
| AO `stop_token_ids` = [151645] | Specified in §2.4, status not explicit | LOCK with §2.4 citation |
| AO/CODE `max_new_tokens` | **EVALUATING** | See below |

**AO/CODE `max_new_tokens` decision options:**

- **Option A: LOCK as "no ceiling" (model default / context window limit).** AO and CODE generate variable-length output. No empirical study scoped for AO/CODE max_new_tokens ceiling optimization. Lock at context-window-limit (16,384 minus input tokens) and revisit in Task 5 if output quality issues surface.
- **Option B: DEFER to Task 5.** AO/CODE output ceiling requires real-world usage data that doesn't exist yet (current production runs Qwen3-1.7B, not 14B). Mark as DEFERRED_TO_TASK5 with rationale.

**SDO recommendation:** Option B (DEFER to Task 5). We have no AO/CODE empirical data on Qwen3-14B yet. Task 5 upgrades both to 14B — that's the correct point to tune max_new_tokens for these components. The row status would change from EVALUATING to DEFERRED_TO_TASK5 with explicit justification.

### 2.3 PA Classification Quality Gate (DEC-10) — CLEARED

Task 4.9d achieved perfect agreement (1.000, 40/40) with 6-rule DeterministicPolicyChecker
(4 DENY + 2 ESCALATE) prefiltering 25/40 cases. G-04 CLEARED in 4.9c; 4.9d closed all 3
residual ESCALATE disagreements.

| Decision | Value | Evidence |
|----------|-------|----------|
| DEC-10 | PA classification quality VALIDATED for production | agreement 1.000 (40/40), adversarial 1.000 (8/8) — from 4.9d evidence |
| DR-02 | RESOLVED (was: Task 4.10 blocked pending PA quality gate) | Unblocked by DEC-10 (4.9c), perfected by 4.9d |

ADR-012 §2.2 GenConfig row: append DEC-10 lock annotation with 4.9d final metrics.

---

## 3. Workload Profile Tables

Task 4.10 compiles three per-component production configuration profiles:

### 3.1 USE-CASE-001 — Policy Agent (PA)

| Parameter | Value | Lock source |
|-----------|-------|-------------|
| Model | Qwen3-14B INT4 | ADR-012 §2.1 |
| Device | GPU (Arc 140V) | ADR-011 |
| Draft model | Qwen3-0.6B INT4 28L | DEC-01 (Task 4.2) |
| `num_assistant_tokens` | 3 | DEC-01 (Task 4.3) |
| `max_new_tokens` | 10 | DEC-08 (Task 4.8) |
| `stop_token_ids` | [151645, 151668] | §2.4 |
| Thinking mode | `/no_think` MANDATORY | DEC-09b (Task 4.9b) |
| `INFERENCE_PRECISION_HINT` | f16 | DEC-07 (Task 4.7) |
| `GPU_ENABLE_SDPA_OPTIMIZATION` | ON | DEC-05 (Task 4.4) |
| `enable_prefix_caching` | OFF | DEC-06 (Task 4.6) |
| `use_sparse_attention` | OFF | DEFERRED (Task 4.3b) |
| `do_sample` | False | Project mandate |
| `temperature` | 0.0 | Project mandate |
| DeterministicPolicyChecker | ACTIVE — 6 rules (4 DENY + 2 ESCALATE), 25/40 prefiltered | DEC-10 (Tasks 4.9c–4.9d) |
| Quality gate | agreement 1.000 (40/40), adversarial 1.000 (8/8) | DEC-10 (Tasks 4.9c–4.9d) |

### 3.2 USE-CASE-004 — Assistant Orchestrator (AO)

| Parameter | Value | Lock source |
|-----------|-------|-------------|
| Model | Qwen3-14B INT4 | ADR-012 §2.1 |
| Device | GPU (Arc 140V) | ADR-011 |
| Draft model | Qwen3-0.6B INT4 28L | DEC-01 (Task 4.2) |
| `num_assistant_tokens` | 3 | DEC-01 (Task 4.3) |
| `max_new_tokens` | DEFERRED_TO_TASK5 | Task 4.10 disposition |
| `stop_token_ids` | [151645] | §2.4 |
| Thinking mode | Default (thinking allowed) | §2.4 |
| `INFERENCE_PRECISION_HINT` | f16 | DEC-07 (Task 4.7) |
| `GPU_ENABLE_SDPA_OPTIMIZATION` | ON | DEC-05 (Task 4.4) |
| `enable_prefix_caching` | OFF | DEC-06 (Task 4.6) |
| `use_sparse_attention` | OFF | DEFERRED (Task 4.3b) |
| `do_sample` | False | Project mandate |
| `temperature` | 0.0 | Project mandate |

### 3.3 USE-CASE-005 — Code Agent (not yet in production)

Same as AO profile except:
- Thinking mode: Context-dependent (`/think` for complex, `/no_think` for simple)
- `max_new_tokens`: DEFERRED_TO_TASK5
- Not validated in Task 4 (no production workload yet)

---

## 4. Execution Prompt Deliverables

1. **ADR-012 §2.2 update (D-1):** Change Input/output split status per Lead Architect decision (§2.1 above). Change GenConfig row status per Lead Architect decision (§2.2 above). Append DEC-10 annotation with 4.9d final metrics. Ensure ZERO EVALUATING rows remain.
2. **ADR-012 new §2.6 — Production Workload Profiles (D-2):** Three workload profile tables (§3 above).
3. **Evidence artifact (D-3):** `phase2_gates/evidence/p5_task4_10_profile_lock_summary.json` — compile all DEC-01 through DEC-10 into structured JSON with evidence citations, workload profiles, and Task 4 closure metadata.
4. **POST_OPERATIONAL_MATURATION_LEDGER.md (D-4):** New Entry 28 — Task 4.10 closure milestone.
5. **IMPLEMENTATION_PLAN.md (D-5):** §1.23 for Task 4.10 (DOCS-ONLY milestone). Note: §1.21 is Task 4.9d, §1.22 is Task 4.11.
6. **P5_TASK4_PRODUCTION_CONFIG_FEASIBILITY.md §0 table (D-6):** Update Task 4.10 row to COMPLETE.
7. **ADR-012 header status change (D-7):** Change from "ACCEPTED — Configuration Optimization In Progress" to "ACCEPTED — Configuration Locked (Task 4 Complete)".

---

## 5. Verification Commands

```powershell
# Confirm commit
git log --oneline -1

# Confirm no EVALUATING rows remain in ADR-012
Select-String -Path "docs\adrs\ADR-012*.md" -Pattern "EVALUATING" -SimpleMatch

# Confirm evidence artifact created
Test-Path "phase2_gates\evidence\p5_task4_10_profile_lock_summary.json"

# Confirm files changed
git diff HEAD~1 --name-only
```

---

## 6. Lead Architect Decisions Required Before Prompt Generation

| ID | Question | Options | SDO Recommendation |
|----|----------|---------|-------------------|
| Q-1 | Input/output split row disposition | LOCK_ADVISORY / RETIRE_ROW | LOCK_ADVISORY |
| Q-2 | AO/CODE max_new_tokens disposition | LOCK_NO_CEILING / DEFER_TO_TASK5 | DEFER_TO_TASK5 |
| Q-3 | Should Task 4.10 also update the §0 status table to mark ALL Tasks 4.1–4.9d as COMPLETE? | YES / NO | YES (already done as of this session) |

---

*Generated by SDO v3.6 — session date 2026-03-05*  
*Updated post-4.9d completion (agreement 1.000, commit 40443b0)*
