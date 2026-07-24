---
role: sdo
phase: comprehension-review
revision: 1
tracking_task: 82
vikunja_comment: 415
posted_at: 2026-04-24T00:52:00Z
verdict: APPROVED
---

# SDO Comprehension-Review — Task 82 Sprint 8 EA-5 — **APPROVED**

## Context

EA Code posted `[agent:ea_code][phase:comprehension]` (comment **#414**, 2026-04-23 19:27 -05:00) for **Sprint 8 EA-5 — Cross-Service Structural Cleanup** (`docs/scheduled/ea_queue/P5_TASK8_EA5_STRUCTURAL_CLEANUP.xml`, 449 lines). This review resolves DEC-12 Phase 1a for the harder-than-standard comprehension gate mandated by SDV §5.3.

## Verdict: **APPROVED**

Comprehension meets all four approval criteria in §3 `<approval_criteria>`:

| Criterion | Evidence |
|---|---|
| (a) every `required_item` appears verbatim with path/line/target/call-site count | §3A.2 (14 occurrences enumerated line-by-line), §3A.4 (3 matches with exact line+target string), §3A.5 (20 call-sites enumerated for `_make_npu_allow`), §3C (all 23 live-TCP tests verified at declared or corrected line numbers), §3D (19 tests verified with destinations) |
| (b) no guessing language — every assertion backed by file read/grep | explicit `grep -c` output cited (3A.2 "119 total NPU/npu refs"), line-level verifications for 3C.1–3C.23, 3E.1–3E.3 conftest.py existence checks |
| (c) subsection 3E infrastructure complete, no invented destinations | all 3 destination service-unit files verified to exist (L count cited); no new unit-test files proposed |
| (d) internal execution order explicitly acknowledged | "rename → imports → moves" sequence restated in the plan-of-work block with inter-step `pytest --co -q` gate |

## Noteworthy observations (not blocking)

- EA correctly flagged **two authoring errors in the prompt itself**: 3A.1 (`_make_npu_stub` does not exist in `test_adjudicator.py`) and 3A.3 (`TestEndToEndWithNPUStub` is in `test_integration_car_pipeline.py`, not `test_hybrid_adjudicator.py`). Conservative defaults chosen (strict skip / rename at actual location). This is exactly the behavior L-14's harder-than-standard gate is designed to elicit.
- **parent_head drift**: prompt declared `89ee727` but worktree HEAD is `e1692ee` (3 governance-only commits ahead — `3f1be6d`, `a74e1be`, `e1692ee`, all touching `docs/scheduled/ea_queue/**` only, zero working-set overlap). EA's decision to branch from HEAD is correct. See decision #7 below.
- **3A.6 STOP disposition** confirmed correct: `GPU_PRIORITY` not present in `services/**/src/constants.py`; per N-1 no production-code changes by EA-5.

## SDO resolutions to EA's 7 pending decisions

| # | EA question | **SDO resolution** |
|---|---|---|
| 1 | 3A.1 — `_make_npu_stub` absent in `test_adjudicator.py`: strict skip (A) or expand scope (B)? | **A — strict skip.** Note the absence in the completion report's "Scope exceptions" section; do **not** absorb broader `test_npu_*` / `npu=` variable renames into EA-5. |
| 2 | 3A.5b — `_make_npu_deny` has 0 call-sites: rename-and-keep or rename-and-delete? | **Rename-and-keep** (`_make_gpu_deny`). Consistent naming; avoids an extra deletion that would expand the diff. |
| 3 | 3A.6 — `GPU_PRIORITY` not in prod: STOP confirmed? | **STOP confirmed.** Leave `test_p110_end_to_end.py` lines 870–875 untouched. Include a single-line "Follow-up" note in the completion report proposing a future production-code ticket. Do **not** file the ticket yourself. |
| 4 | 3A.7 — `TestPreemptionSignalPropagation` docstring: rewrite-if-stale TBD? | **Read during WI-1; rewrite only if the docstring contains an NPU architectural assertion contradicting ADR-011.** If it's merely a label reference (e.g. `npu_result` variable name in example code), leave untouched — that's a job for a future broader nomenclature sweep outside EA-5 scope. |
| 5 | 3B.3 — include `generate_key_pair()` in `_keygen.py`? | **Omit by default.** Include it only if WI-2 verification reveals either consumer already calls it. O-4's minimality rule governs. |
| 6 | 3D — 8 unclassified p114 tests: treat as borderline-preserved? | **Yes — borderline-preserved.** The 19-move list was audit-scoped; tests outside both the move list and the explicit borderline list are implicitly retained in `test_p114_ui_end_to_end.py` with the existing module-level `slow` marker. Record the count (8) in the completion comment's Scope Exceptions block for audit traceability. |
| 7 | parent_head — branch from `e1692ee` (HEAD) not prompt-declared `89ee727`? | **Branch from `e1692ee` (HEAD).** Intermediate commits are governance-only (verified). This is the correct interpretation of L-13's "re-verify at branch checkout time" clause. Record the actual `parent_head` EA used in the ledger entry's frontmatter for audit. |

## Hygiene note (non-blocking)

EA's comment #414 claimed a disk archive at `docs/sprints/sprint_8/reports/20260423_202149_ea_code_comprehension_v1.md`, but that file was **not committed** to the repo. The full comprehension content is in the Vikunja comment (which is sufficient for review), but per DEC-13 the disk copy should be committed alongside the comment. EA: please commit the disk file during WI-1 or WI-6 as a fix-forward (not a blocker for proceeding).

## Gate action

- Remove `Gate:Pending-SDO` (id 9)
- Apply `Gate:Approved` (id 12)
- EA may now execute WI-1 on branch `feature/p5-task8-ea5-structural-cleanup` cut from worktree HEAD `e1692ee`

## Next expected EA action

EA Code Case A path: after this APPROVED verdict, EA posts `[agent:ea_code][phase:execution-start]` (optional) and begins WI-1 (rename pass). Per the internal execution order, WI-1 → `pytest --co -q` → WI-2 → `pytest --co -q` → WI-3 → `pytest --co -q` → WI-4 → WI-5 (full regression) → WI-6 (ledger). Completion review returns to SDO Phase 1b after EA posts `[agent:ea_code][phase:completion]` + `Gate:Pending-SDO`.
