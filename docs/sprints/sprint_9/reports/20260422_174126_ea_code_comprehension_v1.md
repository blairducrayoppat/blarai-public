---
name: Sprint 9 EA-2 Comprehension v1
description: EA Code M5 comprehension-gate recitation for Sprint 9 EA-2 (Runtime Behavior & Resilience governance docs; GOV-05/06/07)
type: dec-13-report
role: ea_code
phase: comprehension
revision: 1
tracking_task: 121
sprint_id: 9
ea_number: 2
vikunja_comment: 290
posted_at: 2026-04-22T17:41:26Z
verdict: null
---

# [agent:ea_code][phase:comprehension] Task 9 EA-2 — Runtime Behavior & Resilience Governance — Comprehension v1

## Wake Template Recitation

**Source**: `tools/scheduled-tasks/wake-templates/ea_code.md`. Section headers invoked verbatim: Phase 0 — Fleet-blocked exit; Event-driven wake triggers (Q2-1); Your scope for this firing; State machine (DEC-12) — Case A / B / C / D / E / F; Formatting standard for Vikunja descriptions and disk reports (DEC-14.5); Report emission (DEC-13); M5 Comprehension Gate content; Budget self-check; Exit criteria; Links.

**`--allowedTools`**: `mcp__vikunja__* Read Write Edit Bash mcp__git__*`. Session cap 90 min. TTG 2 h.

**State verdict**: Task 121 Sprint 9 EA-2 is **Case A** (fresh — no prior `[agent:ea_code][phase:comprehension]` for EA-2 on this task; task carries `Gate:Pending-Execution`; queue file `P5_TASK9_EA2_RUNTIME_RESILIENCE.xml` present and valid; any prior EA-1 comprehension on this task is for a different, already-closed EA cycle).

## EA Prompt Recitation (16 sections A-P per prompt §2 comprehension_gate)

Source: `docs/scheduled/ea_queue/P5_TASK9_EA2_RUNTIME_RESILIENCE.xml` (authored by SDO 2026-04-22).

### A. MILESTONE OBJECTIVE

Author three governance documents under `docs/governance/` that consolidate BlarAI's runtime-behavior and resilience surface: **gpu-runtime.md** (GOV-05 — model-load, speculative decoding, KV-cache, thinking-mode suppression, empirical baselines, model rollback), **error-recovery.md** (GOV-06 — fail-closed per subsystem, error classes, retry vs escalation matrix, user-facing messages, audit trail), and **circuit-breaker.md** (GOV-07 — MAX_OUTPUT_TOKENS and MAX_TOOL_CALL_DEPTH breakers, trip behavior, fallback text, reset semantics, PGOV+streaming interaction). error-recovery.md forward-references `docs/governance/weight-integrity.md` as NOT-YET-AUTHORED (Pluton-blocked per GOV-10 / ISS-4) — EA-2 does NOT author that file. `docs/governance/STYLE.md` (committed by Sprint 9 EA-1 at `b0f0bde`) is the binding style reference for all three docs; non-conformance is a merge-gate failure.

### B. WORK ITEMS

- **WI-1** (first, HIGH): Author `docs/governance/gpu-runtime.md` — GPU Runtime & Speculative Decoding Configuration Governance; GOV-05 / Vikunja #18; audience operator (primary) / developer / auditor; ≥ 150 lines covering 10 required areas (Qwen3-14B load, draft-model load, num_assistant_tokens=3 lock, KV-cache sizing, circuit-breaker/KV-cache interaction forward-reference, thinking-mode suppression, XAttention OFF rationale, 10.72/4.17 tps baselines, Qwen2.5-1.5B rollback runbook, memory-ceiling awareness).
- **WI-2** (after WI-1, HIGH): Author `docs/governance/error-recovery.md` — Error Handling & Crash Recovery Governance; GOV-06 / Vikunja #19; audience incident responder (primary) / operator / developer; ≥ 150 lines covering 12 required areas (fail-closed per subsystem, PA adjudication errors, AO generation errors + PGOV interaction, JWT/mTLS failure, model-load failure with Qwen2.5-1.5B rollback decision, weight-integrity forward-reference, vsock IPC failures, OOM handling, user-facing error text, logging + audit trail, retry vs escalation matrix, boot-time vs runtime failure distinction citing source files directly per L-17).
- **WI-3** (after WI-2, HIGH): Author `docs/governance/circuit-breaker.md` — Circuit Breaker Governance; GOV-07 / Vikunja #20; audience developer (primary) / operator / auditor; ≥ 150 lines covering 12 required areas (MAX_OUTPUT_TOKENS=4096 + MAX_TOOL_CALL_DEPTH=5 with constant-definition line cites, token-counter thinking-token semantics, tool-call depth semantics, trip behavior + fallback text, exact fallback message source cite, per-session vs cross-session reset, threshold-tuning governance, monitoring/logging, PGOV interaction, streaming interaction, KV-cache interaction, two narrative example scenarios).
- **WI-4** (final commit of EA-2): Add Sprint 9 EA-2 ledger entry to `docs/POST_OPERATIONAL_MATURATION_LEDGER.md` with header `### Entry N — Task 9 / EA-2: Sprint 9 Governance Documentation — Runtime Behavior & Resilience` (N = highest existing entry + 1 at commit).

### C. FILES TO CREATE

- `docs/governance/gpu-runtime.md` (WI-1; ≥ 150 lines; GOV-05 / Vikunja #18)
- `docs/governance/error-recovery.md` (WI-2; ≥ 150 lines; GOV-06 / Vikunja #19)
- `docs/governance/circuit-breaker.md` (WI-3; ≥ 150 lines; GOV-07 / Vikunja #20)
- Ledger entry line — new `### Entry N` section appended inside `docs/POST_OPERATIONAL_MATURATION_LEDGER.md` (WI-4).

### D. FILES TO MODIFY

- `docs/POST_OPERATIONAL_MATURATION_LEDGER.md` — append one new `### Entry N` section per WI-4 (N = next-free at commit time). **This is the ONLY non-governance file modified by EA-2.**

### E. FILES TO READ

ADRs: ADR-011, ADR-012, ADR-012 §2.2, §2.4, §5; DEC-01..DEC-10.

Per-WI anchor sources (prompt-named; actual-tree mapping in Section O):
- WI-1: `services/assistant_orchestrator/src/model_loader.py` → substitute `gpu_inference.py`; `services/assistant_orchestrator/src/circuit_breaker.py`; `phase2_gates/evidence/*`.
- WI-2: `services/assistant_orchestrator/src/error_handling.py` → substitute `entrypoint.py` / `pgov.py`; `model_loader.py` → `gpu_inference.py`; `services/policy_agent/src/error_handling.py` (if exists); `shared/ipc/protocol.py`; `shared/schemas/car.py`; `launcher/__main__.py`; `circuit_breaker.py`.
- WI-3: `services/assistant_orchestrator/src/circuit_breaker.py` (PRIMARY); `pgov.py`; `services/ui_shell/src/streaming.py`; `model_loader.py` → `gpu_inference.py`.

Governance/context: `docs/P5_TASK9_SDO_CONTINUATION_v1.0.xml`; SDV §§4, 5.1 items 4-6, 5.2, 5.3, 6, 7, 9, 11; `docs/governance/STYLE.md`; EA-1 peers `pgov-validation.md`, `ipc-protocol.md`, `streaming-output.md`; Vikunja Tasks 18/19/20; ledger; `CLAUDE.md`.

### F. DELIVERABLE STRUCTURE (VERBATIM)

**Branch**: `feature/p5-task9-ea2-runtime-resilience`

**File paths**:
- `docs/governance/gpu-runtime.md`
- `docs/governance/error-recovery.md`
- `docs/governance/circuit-breaker.md`
- `docs/POST_OPERATIONAL_MATURATION_LEDGER.md`

**Section structure per STYLE.md Doc Template (verbatim)**:

```
# {Domain Name} Governance
## Audience
## Prerequisites
## Source References
## Governance Content
## Recovery / Remediation Procedures
## Open Questions / Deferred Items
```

**Per-doc-type flex**:
- gpu-runtime.md: `## Recovery / Remediation Procedures` REQUIRED (model-rollback runbook).
- error-recovery.md: merged into Governance Content (omit stub).
- circuit-breaker.md: merged into Governance Content (omit stub).

**Ledger entry**: `### Entry N — Task 9 / EA-2: Sprint 9 Governance Documentation — Runtime Behavior & Resilience` (N = highest+1 at commit).

**Expected commit message** (SECTION 9 verbatim): see queue file; `{L}` filled from `wc -l` sum; anchor-sources line adjusted per Section O.

### G. ORACLE EXPECTATION (VERBATIM)

Two-step gate — BOTH commands MUST return zero lines:

```
git diff main...feature/p5-task9-ea2-runtime-resilience --name-only | grep -vE "^docs/"
git diff main...feature/p5-task9-ea2-runtime-resilience --name-only | grep -vE "^docs/governance/|^docs/POST_OPERATIONAL_MATURATION_LEDGER\.md$|^docs/IMPLEMENTATION_PLAN\.md$"
```

`docs/IMPLEMENTATION_PLAN.md` permitted in Step 2's filter for EA-5 symmetry but EA-2 MUST NOT modify it.

### H. STYLE.md CONFORMANCE ACKNOWLEDGMENT

Quoting L-18 verbatim:

> IMPORTANT (L-18): STYLE.md already exists on main (committed by Sprint 9 EA-1 at commit b0f0bde). Read docs/governance/STYLE.md before authoring any WI. Conform to its Doc Template, section ordering, line-count floor, source-anchoring, audience taxonomy, markdown conventions, and cross-doc reference rules. Non-conformance is a merge-gate failure.

I have READ `docs/governance/STYLE.md` from current main (HEAD `97c5d98`; STYLE.md unchanged since `b0f0bde`). I will conform verbatim to: Doc Template (seven H2 headers in order), Line-Count Floor (≥ 150 lines), Source Anchoring (≥ 1 ADR + ≥ 1 source file), Audience Taxonomy, Markdown Conventions, Cross-Doc References, Filename Conventions, Out-of-Scope rules. I will NOT amend STYLE.md itself.

### I. CROSS-SPRINT COEXISTENCE ACKNOWLEDGMENT (L-16)

Quoting verbatim per prompt requirement:

> This sprint runs in parallel with Sprint 8. My writes are confined to docs/governance/. Sprint 8 writes are confined to **/tests/.

### J. PHANTOM-REFERENCE ACKNOWLEDGMENT (L-17)

Quoting verbatim per prompt requirement:

> docs/governance/boot-sequence.md DOES NOT EXIST (phantom reference discovered during Sprint 9 planning; tracked in GOV-15 / Vikunja #124 for future authoring). If my doc would naturally cite a boot-sequence governance doc, I cite the relevant source files directly (e.g., services/*/src/boot.py, launcher/__main__.py) and note that boot-sequence governance is future-sprint scope.

### K. WEIGHT-INTEGRITY FORWARD-REFERENCE ACKNOWLEDGMENT

error-recovery.md (WI-2) will forward-reference `docs/governance/weight-integrity.md` as **NOT-YET-AUTHORED** (Pluton-blocked per GOV-10 / Vikunja #23 / ISS-4), using the sanctioned marker from WI-2 §6:

> Weight-integrity check procedure is governed by the future [weight-integrity.md](weight-integrity.md) doc (GOV-10 / Vikunja #23), currently blocked on ISS-4 Pluton investigation. When that doc lands, this section links to its recovery subsection.

Sanctioned broken relative link per MARKDOWN-LINT gate. EA-2 will NOT author `weight-integrity.md` itself.

### L. SOURCE-ANCHORING RECITATION (per SDV §6)

- **gpu-runtime.md** — GOV-05 / #18; ADR-011, ADR-012, ADR-012 §2.2/§2.4/§5, DEC-01..DEC-10; source: `model_loader.py` → `gpu_inference.py` + `circuit_breaker.py`.
- **error-recovery.md** — GOV-06 / #19; ADR-011, ADR-012 §5; source: `error_handling.py` → `entrypoint.py`/`pgov.py` + `shared/ipc/protocol.py`, `shared/schemas/car.py`, `launcher/__main__.py`.
- **circuit-breaker.md** — GOV-07 / #20; ADR-012 §2.4; source: `circuit_breaker.py` (PRIMARY — MAX_OUTPUT_TOKENS=4096, MAX_TOOL_CALL_DEPTH=5, trip logic) + `pgov.py`, `streaming.py`.

### M. TARGET-AUDIENCE ASSIGNMENT

- **gpu-runtime.md** — primary **operator**; secondary **developer**, **auditor**.
- **error-recovery.md** — primary **incident responder**; secondary **operator**, **developer**.
- **circuit-breaker.md** — primary **developer**; secondary **operator**, **auditor**.

### N. 150-LINE FLOOR ACKNOWLEDGMENT

Each of the three docs ≥ 150 lines of substantive content. `gpu-runtime.md` flagged in SDV §9.2 as likely 400+ lines. Any under-150 doc justified in the completion comment per STYLE.md reviewable-position rule.

### O. RISKS AND AMBIGUITIES

- **ANCHOR-FILE NAMING DRIFT (HIGH — SCOPE IMPACT)**: Prompt references `services/assistant_orchestrator/src/model_loader.py` and `services/assistant_orchestrator/src/error_handling.py` but **neither exists** at HEAD `97c5d98`. Current AO files: `circuit_breaker.py`, `context_manager.py`, `__init__.py`, `pgov.py`, `constants.py`, `entrypoint.py`, `gpu_inference.py`. Substitute: read `gpu_inference.py` for model-load surface, and `entrypoint.py` + `pgov.py` for error-handling surface. Cite actual files. Commit-message `Anchor sources:` line will be updated. No file renames / no invented modules.
- **Parallel-with-Sprint-8 (L-16)**: Sprint 8 EA-2 comprehension posted \~7 min prior (Task 82 comment 289). Sprint 8 writes `**/tests/` only; mine confined to `docs/governance/**` + ledger.
- **Phantom boot-sequence temptation (L-17)**: Cite `launcher/__main__.py` + startup entry points; NEVER cite `boot-sequence.md`.
- **Weight-integrity broken link**: Sanctioned.
- **Ledger entry drift**: Highest `### Entry N` is 52 at this firing; Sprint 8 EA-2 may land first and consume 53; re-scan at commit.
- **Parent-head drift**: Snapshot `29cea32`; current main `97c5d98`. Branch from current main.
- **ADR physical location**: Glob for `ADR-011*` and `ADR-012*` during implementation.
- **PA `error_handling.py`**: If absent, cite PA's `entrypoint.py`.
- **Empirical baseline evidence**: If `phase2_gates/evidence/*` not locatable, state the gap and cite closest reference.
- **STYLE.md Recovery-header flex**: gpu-runtime.md KEEPS standalone Recovery; error-recovery.md + circuit-breaker.md MERGE into Governance Content (omit stub).
- **Retroactive-edit prohibition**: Gaps in EA-1 docs → WI-4 ledger escalation; never inline edits.
- **Broken-link aside**: Only weight-integrity forward-reference sanctioned.

### P. PRODUCTION FILE PROHIBITION ACKNOWLEDGMENT

Quoting L-15 verbatim:

> DO NOT modify any file outside docs/governance/ (except the ledger docs/POST_OPERATIONAL_MATURATION_LEDGER.md at sprint-close entries and docs/IMPLEMENTATION_PLAN.md at EA-5). If a non-governance file change appears necessary to unblock a doc (e.g., a stale CLAUDE.md claim contradicts a doc you're writing), STOP, document the blocker in your completion report, and wait for SDO direction. Do not make the change unilaterally.

PROHIBITED paths for Sprint 9 EA-2: `**/tests/*`, `shared/**`, `services/*/src/**`, `launcher/**`, `pyproject.toml`, `conftest.py`, `docs/TEST_GOVERNANCE.md`, any ADR, `docs/IMPLEMENTATION_PLAN.md` (EA-5 reserved). Any diff entry in these paths = ORACLE two-step gate FAIL → HALT + escalate.

## Parent-head verification (L-13)

Prompt snapshot: `29cea32` (SDO authoring 2026-04-22). Current main HEAD: **`97c5d98`** — ahead via fleet commits `5d9ed2c`/`6f4c566`/`12b1b58`/`3d031f2` + this session's Task 82 comprehension disk-report commit. Branch `feature/p5-task9-ea2-runtime-resilience` cut from `97c5d98` per prompt §1.

## Plan of work (cross-referenced to WIs)

1. After SDO APPROVE: `git fetch origin && git checkout main && git pull --ff-only && git checkout -b feature/p5-task9-ea2-runtime-resilience`.
2. Read ADRs (`ADR-011`, `ADR-012` §2.2/§2.4/§5).
3. Read anchor sources: `gpu_inference.py`, `entrypoint.py`, `pgov.py`, `circuit_breaker.py`, `context_manager.py`, `constants.py`, `launcher/__main__.py`, `shared/ipc/protocol.py`, `shared/schemas/car.py`, `services/ui_shell/src/streaming.py`, PA startup/error paths.
4. Read EA-1 peer governance docs + STYLE.md.
5. Read Vikunja Tasks 18/19/20 Scattered Sources.
6. **WI-1** `gpu-runtime.md` (largest; \~400+ lines). Per STYLE.md Doc Template. All 10 required_coverage items. Keep Recovery standalone.
7. **WI-2** `error-recovery.md`. All 12 required_coverage items. Forward-reference circuit-breaker.md + weight-integrity.md. Merge Recovery (omit stub).
8. **WI-3** `circuit-breaker.md`. Cite MAX_OUTPUT_TOKENS=4096 + MAX_TOOL_CALL_DEPTH=5 by path+constant-name. All 12 required_coverage items. Merge Recovery (omit stub).
9. MARKDOWN-LINT gate.
10. SOURCE-ANCHOR gate.
11. LINE-FLOOR gate: each ≥ 150.
12. ORACLE gate: two-step git diff — BOTH empty.
13. REGRESSION-SAFETY-NET gate: pytest ≥ 755 passed, 2 skipped.
14. **WI-4** ledger entry (next-free N).
15. Commit per SECTION 9 template.
16. Post `[agent:ea_code][phase:completion]` on Task 121.
17. Apply `Gate:Pending-SDO` to Task 121.
18. Emit DEC-13 completion disk report + Fleet Reports task + commit.
19. Fire `schtasks /run /tn "Wake SDO"` Q2-1 trigger.

STOP after posting this comprehension. Implementation begins only after `[agent:sdo][phase:comprehension-review] VERDICT: APPROVED`.
