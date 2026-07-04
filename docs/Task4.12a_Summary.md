# Task 4.12a — Harness Scaffolding for Corpus Expansion

**Status:** COMPLETE  
**Branch:** `feature/p5-task4-12-corpus-hardening`  
**Commit:** `152c0e7`  
**Date:** 2026-03-06  
**Parent:** `d79cb14` (EA-1 init message)

---

## Objective

Scaffold the PA Quality Gate harness (`run_p5_task4_9_pa_quality_gate.py`) for corpus expansion from 40 → 236 cases across 6 context bands and 5 categories (A–E), without adding new test cases yet. This sub-milestone prepares the infrastructure so that sub-milestones 4.12b–4.12e can add cases incrementally.

## Files Modified

| File | Action |
|---|---|
| `phase2_gates/scripts/run_p5_task4_9_pa_quality_gate.py` | Modified (sole production change) |
| `phase2_gates/evidence/p5_task4_12_corpus_hardening.json` | Created (evidence artifact) |

## Changes Applied (Steps a1–a9)

1. **a1 — Branch + pytest verification:** Confirmed branch at `d79cb14`, 404 unit tests passing.
2. **a2 — DeterministicPolicyChecker rule documentation:** Documented all 8 pre-filter rules (NULL_CAR, RESTRICTED_PATH ×4, EXFILTRATION, EXTERNAL_NETWORK, AUTHORITY_CLAIM, CROSS_AGENT_OWNERSHIP, INFRA_CONFIG_WRITE, EXCEPTION).
3. **a3 — Case-to-rule mapping:** Mapped all 40 existing cases — 25 pre-filtered by 6 rules, 15 routed to LLM.
4. **a4 — Structural updates:** Added `BAND_TARGETS` entries for 8192 and 12288 token bands. Updated docstring to reflect Task 4.12 scope (236 cases, categories A–E, measurements M-1 through M-8). Changed `OUTPUT_JSON`/`PARTIAL_JSON` filenames to `p5_task4_12_corpus_hardening.json`.
5. **a5 — `_make_car()` helper:** New module-level function for programmatic CAR text construction from structured fields (verb, resource, owner, justification, sensitivity).
6. **a6 — `expected_path` annotations:** All 40 `TEST_CASES` dicts annotated with `"expected_path"` field (LLM, DENY_RESTRICTED_PATH, DENY_EXFILTRATION, DENY_EXTERNAL_NETWORK, ESCALATE_CROSS_AGENT_OWNERSHIP, ESCALATE_INFRA_CONFIG_WRITE, ESCALATE_CERT_RENEWAL).
7. **a7 — `llm_path_analysis` evidence:** Added `_compute_llm_path_analysis()` function computing LLM-path-only metrics. Evidence dict updated with `task="P5-Task-4.12"`, new title, `llm_path_analysis` section, and `expected_path` in run records.
8. **a8 — Pre-filter verification loop:** Inserted verification loop before pipeline compilation that constructs CAR for each case, runs `DeterministicPolicyChecker.check()`, and aborts on mismatch with `expected_path`. All 25 pre-filtered cases verified against 6 rules.
9. **a9 — Full harness run with GPU inference:** Executed harness end-to-end. 40/40 agreement, 8/8 adversarial security, all quality gates PASS. Evidence artifact written.

## Quality Gates

| Gate | Result |
|---|---|
| Agreement (total) | 40/40 (1.000) |
| Pre-filter verification | 25/25 OK (6 rules) |
| LLM-path agreement | 15/15 (1.000) |
| Adversarial security | 8/8 (1.000) |
| Unit tests (regression) | 404 passed (unchanged) |
| K-6 (no uat2 staged) | PASS |

## Evidence Artifact

**File:** `phase2_gates/evidence/p5_task4_12_corpus_hardening.json`

Key fields:
- `task`: "P5-Task-4.12"
- `llm_path_analysis.total_cases`: 40
- `llm_path_analysis.prefiltered_cases`: 25
- `llm_path_analysis.llm_path_cases`: 15
- `llm_path_analysis.llm_path_agreement`: 1.0
- All run records include `expected_path` field

## Bug Encountered & Resolved

`_extract_car_field()` was defined as a nested function inside `main()` after the pre-filter verification loop that needed it. Fix: moved to module-level scope. Single-attempt resolution.

## Path Distribution (40 Cases)

| Expected Path | Count |
|---|---|
| LLM | 15 |
| DENY_RESTRICTED_PATH | 18 |
| DENY_EXFILTRATION | 3 |
| DENY_EXTERNAL_NETWORK | 1 |
| ESCALATE_CROSS_AGENT_OWNERSHIP | 1 |
| ESCALATE_INFRA_CONFIG_WRITE | 1 |
| ESCALATE_CERT_RENEWAL | 1 |

## Verification Commands

```powershell
git log --oneline -1
# Expected: 152c0e7 task4.12a: harness scaffolding for corpus expansion

git diff HEAD~1 --name-only
# Expected: phase2_gates/evidence/p5_task4_12_corpus_hardening.json
#           phase2_gates/scripts/run_p5_task4_9_pa_quality_gate.py
```
