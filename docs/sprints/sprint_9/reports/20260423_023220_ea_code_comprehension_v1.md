---
role: ea_code
phase: comprehension
revision: 1
tracking_task: 121
vikunja_comment: null
posted_at: 2026-04-23T02:32:20Z
verdict: null
---

# [agent:ea_code][phase:comprehension] Sprint 9 EA-4 — Ops, Deployment, Rule Engine Governance — Comprehension Gate v1

**Tracking task**: Vikunja #121
**Queue file**: `docs/scheduled/ea_queue/P5_TASK9_EA4_OPS_DEPLOYMENT_RULES.xml`
**Branch target**: `feature/p5-task9-ea4-ops-deployment-rules`

## Wake template recitation (sections + allowedTools)

Section headers of `docs/scheduled/wake_templates/ea_code_wake.md`:

- Phase 0 — Fleet-blocked exit
- Event-driven wake triggers (Q2-1 + ISS-4)
- Your scope for this firing
- State machine (DEC-12): Case A / B / C / D / E / F
- Formatting standard for Vikunja descriptions and disk reports (DEC-14.5)
- Report emission (DEC-13)
- M5 Comprehension Gate content
- Budget self-check
- Exit criteria
- Links

`--allowedTools` scope: `mcp__vikunja__* Read Write Edit Bash mcp__git__*`.

## EA prompt recitation

### Milestone Objective (verbatim)

Author three governance documents completing the Sprint 9 ops/deployment/rule-engine triad: `docs/governance/observability.md` (GOV-12), `docs/governance/deployment-verification.md` (GOV-13), `docs/governance/rule-engine.md` (GOV-14). Each doc conforms to the STYLE.md seven-header template, clears the 150-line substantive floor, cites at least one ADR and at least one source file, and addresses the appropriate audience personas. Plus one per-file ledger entry per Q1-1 convention. **No production code is modified.**

### Work Items (4 WIs, one sentence each)

- **WI-1** (HIGH): Author `docs/governance/observability.md` (GOV-12) — log level taxonomy, event classification per subsystem (PA / AO / IPC / lifecycle), error-fingerprinting taxonomy, audit trail; ~400+ lines expected.
- **WI-2** (HIGH): Author `docs/governance/deployment-verification.md` (GOV-13) — pre-deployment checks (vsock topology + guest runtime config), evidence artifacts, smoke-test preflight, automatic + manual rollback, ADR-012 §5 model fallback; ~200-300 lines with substantive Recovery section.
- **WI-3** (HIGH): Author `docs/governance/rule-engine.md` (GOV-14) — enumerate rules from `deterministic_policy_checker.py`, deterministic-before-LLM ordering, fail-closed semantics, CAR schema enforcement via `is_complete()`, semantic-distance threshold, example CARs; ≥150 lines.
- **WI-4** (MEDIUM): Author per-file ledger entry `docs/ledger/<ts>_sprint9_ea4_ops-deployment-rules.md` with frontmatter + Summary/Deliverables/Files Changed/Quality Gate/Notes body (≥ 50 substantive lines).

### Negative Constraints (8)

- **NC-1**: L-15 PURE DOCUMENTATION — no edits to `services/`, `shared/`, `launcher/`, `tests/`, or pyproject.toml.
- **NC-2**: No retroactive edits to EA-1/EA-2/EA-3 docs (10 existing governance docs); forward cross-links allowed.
- **NC-3**: Per-file ledger (Q1-1); predecessor `20260422_203647_sprint9_ea3_operational-state`; do NOT append to frozen `POST_OPERATIONAL_MATURATION_LEDGER.md`.
- **NC-4**: No phantom-reference creation — `boot-sequence.md` must NOT be created (deferred to GOV-15).
- **NC-5**: No migration of `docs/TEST_GOVERNANCE.md` (deferred to GOV-MIGRATE).
- **NC-6**: No new ADRs in `docs/adrs/`.
- **NC-7**: L-16 Sprint 8 coexistence — Sprint 8 writes `**/tests/`; don't touch any test file.
- **NC-8**: Scope-limited to the three named docs + ledger.

### Acceptance Checks / Quality Gates

- **LINE-FLOOR**: each doc ≥ 150 lines (via `Get-Content | Measure-Object -Line`).
- **STYLE-CONFORMANCE**: each doc has the six STYLE.md `##` headers (or five if Recovery merged).
- **SOURCE-ANCHOR**: each doc cites ≥ 1 ADR + ≥ 1 source file.
- **ORACLE**: `git diff main...feature/p5-task9-ea4-ops-deployment-rules --name-only | grep -vE "^docs/"` → EMPTY.
- **REGRESSION**: `.venv\Scripts\pytest shared/ services/ launcher/ --tb=short -q` — ≥ 962 passed, 2 skipped (Sprint 8 baseline unaffected).

## Comprehension — required sections

### A. MILESTONE OBJECTIVE (my words)

I will author three governance docs closing the Sprint 9 triad for operations, deployment, and rule-engine behavior, each grounded in `deterministic_policy_checker.py`, `guest_deploy.py`, `__main__.py`, `pgov.py`, `car.py`, and `runtime_config.py` source (never invented). Each doc follows STYLE.md's seven-header template, clears the 150-line floor, cites at least one ADR (ADR-010 for rule-engine and PA-logging paths; ADR-012 §5 for deployment model rollback; ADR-011 for GPU-inference events), and declares only the 2-3 audience personas it genuinely serves. A per-file ledger entry records deliverables and quality-gate outcomes. Zero production-code edits; forward-cross-links into prior EA-1/EA-2/EA-3 docs are permitted but retroactive edits are not.

### B. WORK ITEMS

(See `EA prompt recitation → Work Items` above — 4 items, one sentence each.)

### C. FILES TO CREATE

- `docs/governance/observability.md` (GOV-12, ~400+ lines)
- `docs/governance/deployment-verification.md` (GOV-13, ~200-300 lines, Recovery section required)
- `docs/governance/rule-engine.md` (GOV-14, ~150-200 lines)
- `docs/ledger/<YYYYMMDD_HHMMSS>_sprint9_ea4_ops-deployment-rules.md`

### D. FILES TO READ (source research)

**Common (STYLE + format)**:
- `docs/governance/STYLE.md` (seven-header template, line-count floor, source-anchoring, audience taxonomy, phantom-reference policy)
- `docs/P5_TASK9_SDO_CONTINUATION_v1.0.xml` §5 (EA-4 block lines 352-376), §6, §7
- `docs/sprints/sprint_9/strategic_design_vision.md` §4, §5.1 (items 10-12), §5.2, §5.3
- `docs/ledger/20260422_203647_sprint9_ea3_operational-state.md` (predecessor format)
- `docs/ledger/README.md`
- `docs/governance/configuration-management.md` (EA-3 ADR-absence precedent)
- `docs/governance/circuit-breaker.md` (EA-2 ADR-absence precedent)

**WI-1 (observability.md) source anchors**:
- `services/policy_agent/src/deterministic_policy_checker.py`
- `services/policy_agent/src/entrypoint.py`
- `services/assistant_orchestrator/src/entrypoint.py`
- `services/assistant_orchestrator/src/pgov.py`
- `services/ui_gateway/src/transport.py`
- `shared/src/runtime_config.py` (`build_failure_fingerprint` taxonomy)
- `launcher/__main__.py`, `launcher/guest_deploy.py`

**WI-2 (deployment-verification.md) source anchors**:
- `launcher/guest_deploy.py` (full deployment flow, error codes, evidence writing)
- `launcher/__main__.py` (`_run_uat2_prompt_flow_preflight`, `_cleanup`)
- `launcher/vm_manager.py` (VM lifecycle, `request_elevation`)
- `shared/src/constants.py` (VSOCK constants)

**WI-3 (rule-engine.md) source anchors**:
- `services/policy_agent/src/deterministic_policy_checker.py` (full read — rule enumeration authoritative)
- `services/policy_agent/src/car.py` (`is_complete()`)
- `shared/schemas/car.py` (schema + enums `ActionVerb`/`Sensitivity`/`AdjudicationDecision`)
- `services/assistant_orchestrator/src/pgov.py` (cosine threshold, retrieval-leakage check)

### E. DELIVERABLE STRUCTURE (verbatim recitation)

**Branch**: `feature/p5-task9-ea4-ops-deployment-rules`

**Doc filenames + STYLE.md headers** (six headers; Recovery MAY merge into Governance Content for docs with no externally triggered failure mode):

- **`docs/governance/observability.md`**:
  - `# Observability & Logging Strategy Governance`
  - `## Audience`
  - `## Prerequisites`
  - `## Source References`
  - `## Governance Content`
  - `## Recovery / Remediation Procedures` (may merge into Governance Content — no recovery ceremony for observability)
  - `## Open Questions / Deferred Items`

- **`docs/governance/deployment-verification.md`**:
  - `# Deployment Verification & Rollback Governance`
  - `## Audience`
  - `## Prerequisites`
  - `## Source References`
  - `## Governance Content`
  - `## Recovery / Remediation Procedures` (**REQUIRED** — substantive rollback)
  - `## Open Questions / Deferred Items`

- **`docs/governance/rule-engine.md`**:
  - `# Rule Engine & CAR Validation Governance`
  - `## Audience`
  - `## Prerequisites`
  - `## Source References`
  - `## Governance Content`
  - `## Recovery / Remediation Procedures` (may merge — fail-closed DENY is governance, not recovery)
  - `## Open Questions / Deferred Items`

**Ledger path**: `docs/ledger/<YYYYMMDD_HHMMSS>_sprint9_ea4_ops-deployment-rules.md`

**Ledger frontmatter** (verbatim):

```yaml
---
ledger_id: <YYYYMMDD_HHMMSS>_sprint9_ea4_ops-deployment-rules
date: <YYYY-MM-DD>
sprint_id: 9
entry_type: EA
predecessor: 20260422_203647_sprint9_ea3_operational-state
branch: feature/p5-task9-ea4-ops-deployment-rules
merge_commit: null
disposition: COMPLETE
---
```

### F. ORACLE EXPECTATION

Command:

```
git diff main...feature/p5-task9-ea4-ops-deployment-rules --name-only | grep -vE "^docs/"
```

Expected output: **EMPTY**. Only paths under `docs/` appear in the diff; any `services/`, `shared/`, `launcher/`, or `tests/` path is an L-15 violation.

### G. SOURCE ANCHORING PLAN (per doc)

| Doc | ADR(s) | Source files (≥ 2) |
|---|---|---|
| `observability.md` | ADR-010 (PA classification / audit trail), ADR-011 (GPU inference events) — ADR-absence for logging format documented in Prerequisites + Open Questions per I.2 | `shared/src/runtime_config.py` (`build_failure_fingerprint`), `services/ui_gateway/src/transport.py` (IPC boundary logs), `services/policy_agent/src/deterministic_policy_checker.py` (PA decision logs), `services/assistant_orchestrator/src/pgov.py` (PGOV events) |
| `deployment-verification.md` | ADR-012 §5 (Qwen2.5-1.5B fallback), ADR-011 (GPU verification path) | `launcher/guest_deploy.py`, `launcher/__main__.py`, `launcher/vm_manager.py`, `shared/src/constants.py` |
| `rule-engine.md` | ADR-010 (deterministic-before-LLM) | `services/policy_agent/src/deterministic_policy_checker.py`, `services/policy_agent/src/car.py`, `shared/schemas/car.py`, `services/assistant_orchestrator/src/pgov.py` |

### H. MATURE-NOT-MINIMAL ACKNOWLEDGMENT

Floor is 150 substantive lines per doc; expected depths are 400+ / 200-300 / 150-200 for GOV-12/13/14 respectively. I will write to substance, not to the floor — if a domain naturally runs longer, it runs longer.

### I. RISKS AND AMBIGUITIES (addressing I.1–I.6)

- **I.1** boot-sequence.md phantom: do NOT create, do NOT link; cite phantom in Open Questions per STYLE.md.
- **I.2** GOV-12 ADR-absence: cite ADR-010/011 as closest-relevant; document absence in Prerequisites + Open Questions (EA-2/EA-3 precedent).
- **I.3** GOV-13 deployment timeout: if no constant in `__main__.py`/`guest_deploy.py`, document the gap and open a Vikunja ticket; no invented timeout.
- **I.4** GOV-14 rule enumeration: source (`deterministic_policy_checker.py`) is authoritative; note discrepancies with prior summaries in Open Questions.
- **I.5** GOV-12 PII redaction reality check: if redaction is not implemented, say so; open ticket for gap; do not claim aspirational behavior.
- **I.6** audience personas: claim 2-3 per doc (GOV-12: developer/operator/incident-responder; GOV-13: operator/incident-responder; GOV-14: developer/auditor).

### J. PRODUCTION CODE PROHIBITION ACKNOWLEDGMENT

Quoted L-15 prohibition (verbatim from prompt):

> This is a PURE DOCUMENTATION milestone. DO NOT modify any file outside docs/. If a code defect is discovered during research, record it in the completion report and open a Vikunja ticket. Do NOT modify services/, shared/, launcher/, tests/, or pyproject.toml.

I acknowledge. Any defect discovered during source research is logged (completion report + Vikunja ticket) and NOT fixed in this EA.

## Plan-of-work (cross-referenced to WIs)

1. **Parent head verify (L-13)** — current `main` HEAD is `f204a24`; prompt said `ad311ac`; ISS-4 merges do not touch `docs/governance/**`; branching from `f204a24`.
2. **Source read pass** — STYLE.md + SDV + continuation XML + predecessor ledger + two ADR-absence precedent docs + all WI source files.
3. **WI-3 first** (rule-engine.md) — narrowest, highest source-authority density; establishes rule-count baseline I'll cross-reference from WI-1.
4. **WI-1** (observability.md) — broadest doc; anchors to all four service subsystems + `build_failure_fingerprint` taxonomy.
5. **WI-2** (deployment-verification.md) — substantive Recovery section; cross-links observability.md for evidence format and gpu-runtime.md for model fallback.
6. **WI-4** (ledger) — author per-file ledger with frontmatter + 5-section body.
7. **Gate runs** — LINE-FLOOR → STYLE-CONFORMANCE → SOURCE-ANCHOR → ORACLE → REGRESSION (Sprint 8 baseline ≥ 962).
8. **Commit + completion comment + SDO trigger**.

## Parent head verify (L-13)

Current `main` HEAD: `f204a24`. Prompt-stated `ad311ac` has been superseded by two ISS-4 merges that touch `tools/scheduled-tasks/` and `docs/scheduled/wake_templates/` only — both outside this EA's working set (`docs/governance/`, `docs/ledger/`). Safe to branch from `f204a24`.

---

**Status**: STOP — awaiting `[agent:sdo][phase:comprehension-review] VERDICT: APPROVED`.
