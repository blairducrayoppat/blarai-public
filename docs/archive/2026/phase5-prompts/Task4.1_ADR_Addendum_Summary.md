---
title: Task4.1_ADR_Addendum_Summary
status: archived
area: portfolio
---

# Task 4.1 — Housekeeping Commit + ADR-012 §2.5 PA Latency Budget Addendum

**Execution Prompt:** `docs/Task4.1_v1.xml`
**Branch:** `feature/p5-task4-1-adr-addendum`
**Commits:** `cbce517` (housekeeping bundle) · `c4b6d4c` (docs/governance)
**Type:** DOCS_ONLY — no production logic changes in this milestone scope
**Pre-condition:** `main` HEAD `c464392` (LEDGER 12 entries, ADR-012 §2.4 M1/M2/M3 DONE)

## Objective

1. Create a feature branch and commit 6 pending uncommitted files from the prior SDO session as a housekeeping bundle — closing out the AO `/no_think` implementation (ADR-012 §2.4 M-AO) and formalizing the Task 4 specification and SDO handoff documents.
2. Add **ADR-012 §2.5** documenting the 2,000ms P95 PA inference latency budget decision (replaces the invalid 230ms baseline from ADR-010 / Qwen2.5-1.5B-NPU era).
3. Append **LEDGER Entry 13**: AO `/no_think` default system prompt — all ADR-012 §2.4 implementation items now DONE.
4. Update **IMPLEMENTATION_PLAN.md §1.17** for Task 4.1 disposition.
5. Emit evidence artifact: `phase2_gates/evidence/p5_task4_1_adr_addendum.json`.

## Decision Locked

| ID | Decision | ADR Section |
|----|----------|-------------|
| D-T4-01 | PA inference latency budget: **2,000ms P95 flat** | ADR-012 §2.5 |

**Derivation basis:** 10.72 tps empirical (P5-005b D-01) + TTFT 408ms at 4K + overhead + P95 variance headroom.
- Realistic e2e (5-token output, 4K input): \~875ms
- Worst-case at `max_new_tokens=32`: \~2,987ms — **exceeds budget** → Task 4.8 must reduce `max_new_tokens`
- Replaces: ADR-010 §3.2 — 125ms P95 (Qwen2.5-1.5B/NPU — invalidated)

## Commit #1 — Housekeeping Bundle (`cbce517`)

| File | Change |
|------|--------|
| `services/assistant_orchestrator/src/npu_inference.py` | `/no_think` directive added to `_DEFAULT_SYSTEM_PROMPT` Block 6; per-turn `/think` opt-in documented in comments |
| `services/assistant_orchestrator/tests/test_npu_inference.py` | `test_system_prompt_no_think_default`: renamed + assertion inverted — asserts `/no_think` IS present |
| `docs/adrs/ADR-012-Qwen3-14B-Model-Selection-Speculative-Decoding.md` | Minor 1-line edit from prior SDO session |
| `docs/P5_TASK4_PRODUCTION_CONFIG_FEASIBILITY.md` | NEW — full Task 4 spec: 10 sub-sessions, test matrices, quality gates, workload profiles |
| `docs/P5_TASK4_SDO_HANDOFF.xml` | NEW — SDO governance handoff v3.4; supersedes `CONTINUATION_PROMPT.md` v3.2 |
| `.github/copilot-instructions.md` | v3.1 → v3.2 update: Phase 5 directive block reflects HEAD, LEDGER 12 entries, Task 4 ACTIVE |

## Commit #2 — Docs/Governance Bundle (`c4b6d4c`)

| File | Change |
|------|--------|
| `docs/adrs/ADR-012-Qwen3-14B-Model-Selection-Speculative-Decoding.md` | §2.5 inserted: PA latency budget table, derivation, Task 4.8 implication, gate dependencies |
| `docs/POST_OPERATIONAL_MATURATION_LEDGER.md` | Entry 13 appended: AO `/no_think` default DONE, ADR-012 §2.4 all items COMPLETE, UAT-4a OPEN |
| `docs/IMPLEMENTATION_PLAN.md` | §1.17 appended: Task 4.1 disposition, branch, date, 6 committed files, PA latency budget locked |
| `phase2_gates/evidence/p5_task4_1_adr_addendum.json` | NEW — evidence artifact (see below) |

## ADR-012 §2.4 Status at Milestone Close

| Item | Status |
|------|--------|
| M1 — PA `/no_think` + dual stop tokens | DONE |
| M2 — AO thinking stripping + streamer suppression | DONE |
| M3 — `StreamToken.is_thinking` transport field | DONE |
| M-AO — AO `/no_think` default system prompt | **DONE (this milestone)** |
| UAT-4a — AO `/think` per-turn toggle | OPEN — requires Task 5 (Qwen3-14B/GPU AO) |

## UAT Gates Introduced

| Gate | Title | Prerequisite | Status |
|------|-------|-------------|--------|
| UAT-4a | AO `/think` per-turn toggle | Task 5 complete (AO on Qwen3-14B/GPU) | OPEN |
| UAT-4b | PA classification ≤ 2,000ms P95 in live TUI | Task 5 + Task 4.8 `max_new_tokens` lock | OPEN |

## Evidence Artifact

`phase2_gates/evidence/p5_task4_1_adr_addendum.json`

Key fields: `"disposition": "COMPLETE"`, `"scope": "DOCS_ONLY"`, `"decisions_locked": [D-T4-01]`, test baseline (786 collected / 755 passed / 31 deferred pre-existing).

## Verification Results

| Check | Command | Result |
|-------|---------|--------|
| C-01 | `git log --oneline -4` | Both commits above `c464392 (main)` ✅ |
| C-02 | `git diff main HEAD --name-only` | 9 files; `uat2_real_runtime_activation.json` absent ✅ |
| C-03 | JSON validation + field check | All 4 required fields present ✅ |
| C-04 | `pytest shared/ services/ --tb=short -q` | **670 passed**, 0 failures ✅ |

## Hard Exclude (Preserved Throughout)

`phase2_gates/evidence/uat2_real_runtime_activation.json` — live-system FAIL artifact. Phase 4 PASS baseline on `main` preserved. Resolution deferred to Task 5.
