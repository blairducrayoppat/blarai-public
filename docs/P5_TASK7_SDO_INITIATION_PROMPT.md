# Task 7: Test Quality Audit — SDO Initiation Prompt

**Date:** 2026-04-18
**From:** Lead Architect
**To:** New SDO Session (persistent)
**Predecessor:** Task 6 (Test Governance Framework) — MERGED to main (verified by prior SDO session).

---

## Purpose

I need you (SDO) to serve as my **persistent planning partner for the entire Test Quality Audit lifecycle** — Task 7 and any remediation tasks that follow from it. Your responsibilities:

1. **Plan the audit.** Assess scope, determine whether the audit fits in a single EA session or needs decomposition, and present your plan for my approval.
2. **Generate scoped EA prompts.** For each approved audit milestone, produce a self-contained XML EA prompt that an Execution Agent can complete in a single session.
3. **Track progress across EA sessions.** As EAs complete audit milestones and produce findings, you synthesize results, identify patterns, and advise on priority.
4. **Plan remediation.** Once the audit is complete, help me scope Task 8+ remediation milestones based on the prioritized findings.
5. **Advise throughout.** Challenge my assumptions, flag risks, and recommend sequencing — same operating model as any SDO session.

You are NOT an EA. You do NOT execute implementation work. You generate prompts and track state.

## Context

### Why this task exists

Testing has grown organically across 5 phases of development. 835 tests pass, but I have no confidence that:
1. All production modules have adequate test coverage
2. Existing tests are actually testing meaningful behavior (vs. superficial assertions)
3. Test boundaries (unit vs. integration) are correctly drawn
4. There isn't stale test code testing dead/renamed code paths
5. Tests produce the diagnostic information needed to make decisions when they fail

Task 6 establishes the governance framework (what scopes exist, what markers mean, when to write tests, what "adequate" looks like). Task 7 measures the current test suite against that framework and identifies gaps.

### Sequencing rationale

**Governance → Audit → Remediation.** Task 6 creates the standard. Task 7 measures against the standard. Task 7 findings become scoped remediation milestones (Task 8+). EAs doing audit work must NOT fix anything — diagnose only. Remediation is a separate task sequence that you (SDO) will help plan after audit findings are in.

### Current test inventory (empirically verified 2026-04-18)

| Directory | Test Files | Production Files (src/) | Ratio |
|-----------|-----------|------------------------|-------|
| services/policy_agent | 12 | 10 | 1.20 |
| services/assistant_orchestrator | 5 | 6 | 0.83 |
| services/semantic_router | 1 | 3 | 0.33 |
| services/ui_gateway | 2 | 3 | 0.67 |
| services/ui_shell | 3 | 5 | 0.60 |
| shared (all subdirs) | 5 | 7 | 0.71 |
| launcher | 3 | 3* | 1.00 |
| tests/integration | 2 | (cross-service) | — |
| **Total** | **33 files** | **34 files** | — |

*launcher has __main__.py, guest_deploy.py, vm_manager.py + __init__.py

### Test baseline (from Task 6)
- REGRESSION scope: 755 passed, 2 skipped, 80 deselected
- FULL scope: 835 passed, 2 skipped
- Pre-existing skips: `test_build_prompt_does_not_contain_no_think`, `test_stop_token_ids_constants_defined`

### What the audit must answer

These are the 4 questions I need answered. Structure the EA prompt around them:

1. **Coverage gaps:** Which production modules/classes/functions have zero or inadequate test coverage? Map every production `.py` file to its test file(s) and flag files with no corresponding tests.

2. **Stale/dead tests:** Which tests reference functions, classes, imports, or module paths that no longer exist? Which tests test behavior that was superseded by later milestones (e.g., NPU inference tests after ADR-011 retired the NPU)?

3. **Assertion quality:** Which tests have weak assertions — `assert True`, bare `assert obj`, `assert result is not None` without checking the actual value, `try/except` blocks that swallow errors, tests that test internal implementation details rather than behavior?

4. **Boundary correctness:** Are unit tests actually unit tests (no real I/O, no socket connections, no file system writes)? Are integration tests properly marked `slow`? Are there tests that should be integration tests but aren't marked?

### Scope constraint — single session feasibility assessment

33 test files + 34 production files = 67 files. Your first planning action should be to assess whether this is feasible for a single EA session or needs decomposition.

**If single-session:** Generate one EA prompt covering all 4 audit questions across all 8 test directories with Tier 3 fail-safe (see below).

**If multi-session:** Propose a decomposition (e.g., per-service, per-audit-question, high-density vs. low-density) and present it for my approval before generating any EA prompts.

**Tier 3 fail-safe (applies to every EA prompt you generate):** If an EA determines mid-session that it cannot complete its assigned scope without quality degradation, it must STOP and produce a partial report plus a recommended re-scoping. The EA must NOT rush through remaining files.

### Audit methodology — tiered approach

Each EA prompt you generate should follow this structure:

**Tier 1 (mandatory):** Inventory — map every production file to its test file(s). This is a mechanical listing that reveals coverage gaps immediately.

**Tier 2 (mandatory):** Per-service scan — for each assigned test directory, read every test file and evaluate assertion quality, staleness, and boundary correctness against the production code it tests.

**Tier 3 (conditional):** Fail-safe stop and partial report (see above).

### Deliverable structure

Each EA session produces findings that contribute to a single consolidated document: `docs/TEST_AUDIT_FINDINGS.md`

If you decompose into multiple EA sessions, each EA appends to or creates a section of this document. You (SDO) are responsible for tracking which sections are complete and ensuring the final document has all required sections before declaring the audit complete.

Required sections in the final document:
1. **Coverage Map** — table: production file → test file(s) → coverage assessment (COVERED / PARTIAL / NONE)
2. **Stale Test Inventory** — list of tests referencing dead code, with evidence (import path, function name)
3. **Assertion Quality Findings** — per-service summary + specific examples of weak assertions
4. **Boundary Violations** — tests misclassified as unit/integration
5. **Prioritized Gap Report** — ordered list of remediation items with severity (HIGH/MEDIUM/LOW) and estimated scope (files to create/modify)
6. **Pre-existing Skip Analysis** — the 2 skipped tests: should they be fixed, removed, or kept as-is? Provide recommendation with rationale.

### What the audit must NOT do

- Do NOT modify any test files
- Do NOT modify any production files
- Do NOT create conftest.py files
- Do NOT fix anything — diagnose only
- Do NOT run tests with coverage tools (we have no coverage dependency and installing one is out of scope)
- Do NOT add tests

### Required attachments for the EA prompt

The SDO must list these in the EA prompt's required_attachments section:

| File | Reason |
|------|--------|
| `docs/TEST_GOVERNANCE.md` | The audit standard — created by Task 6 |
| `pyproject.toml` | Root pytest configuration |
| The EA prompt itself | Standard |

No other attachments needed — the EA will use workspace search tools to read production and test files.

### SDO operating expectations

1. **Assess and propose decomposition.** Present your audit plan — single EA or multi-EA decomposition with rationale — for my approval before generating any EA prompts.

2. **Generate EA prompts one at a time.** After I approve your plan, generate the first EA prompt. After that EA completes and reports back, I'll share its findings with you. You then generate the next EA prompt (if multi-session) or proceed to synthesis.

3. **LEDGER tracking.** Each EA prompt must include recording an entry in the Post-Operational Maturation Ledger. The first audit EA gets Entry 39 (Entry 38 will be Task 6). Subsequent EAs get sequential entries.

4. **No code changes gate.** Every audit EA prompt must enforce DOC_ONLY: `git diff main --name-only` must show ONLY `docs/TEST_AUDIT_FINDINGS.md` and `docs/POST_OPERATIONAL_MATURATION_LEDGER.md`.

5. **Synthesis and remediation planning.** Once all audit EAs are complete, produce a consolidated summary for me. Then help me scope Task 8+ remediation milestones — each scoped to a single EA session per the standard rules.

6. **Follow copilot-instructions.md operating model.** All standard SDO rules apply: comprehension gate, single-session EA scoping, non-dev verification commands, evidence-first decisions, role boundary enforcement.

7. **State updates for EA prompts.** Note the following will differ from the v5.0 SDO initiation prompt:
   - Main HEAD will be whatever commit Task 6 merges to (not 103dfe6 or a597f1f)
   - LEDGER will be at Entry 38 (Task 6)
   - Test baseline: see Task 6 deliverables in TEST_GOVERNANCE.md
   - `copilot-instructions.md` baseline will have been updated by Task 6

---

**Immediate action:** Perform your comprehension gate. Summarize your understanding of: (a) your role as persistent SDO for the audit lifecycle, (b) Task 7 scope and the 4 audit questions, (c) the deliverable structure, (d) constraints (read-only, no code changes), (e) your proposed approach to decomposition. Then WAIT for my approval before generating any EA prompts.
