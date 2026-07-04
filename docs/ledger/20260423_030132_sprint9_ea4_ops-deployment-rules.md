---
ledger_id: 20260423_030132_sprint9_ea4_ops-deployment-rules
date: 2026-04-23
sprint_id: 9
entry_type: EA
predecessor: 20260422_203647_sprint9_ea3_operational-state
branch: feature/p5-task9-ea4-ops-deployment-rules
merge_commit: null
disposition: COMPLETE
---

## Task 121 / EA-4: Ops, Deployment, Rule Engine

### Summary

Three governance documents authored completing the Sprint 9
operations/deployment/rule-engine triad: observability & logging
strategy (GOV-12), deployment verification & rollback (GOV-13), and
rule engine & CAR validation (GOV-14). All three conform to the
Sprint 9 EA-1 `docs/governance/STYLE.md` Doc Template and clear the
150-line substantive floor. Scope held strictly to
`docs/governance/**` plus this ledger entry; zero production code
modified (L-15). Working set disjoint from Sprint 8's `**/tests/`
working set per L-16 / NC-7.

### Deliverables

| WI | Artifact | Lines | GOV ID | Vikunja subtask |
|---|---|---|---|---|
| WI-1 | `docs/governance/observability.md` | 340 | GOV-12 | #25 |
| WI-2 | `docs/governance/deployment-verification.md` | 337 | GOV-13 | #26 |
| WI-3 | `docs/governance/rule-engine.md` | 350 | GOV-14 | #27 |
| WI-4 | This ledger entry | — | — | — |

### Files Changed

- `docs/governance/observability.md` (new, 340 lines)
- `docs/governance/deployment-verification.md` (new, 337 lines)
- `docs/governance/rule-engine.md` (new, 350 lines)
- `docs/ledger/20260423_030132_sprint9_ea4_ops-deployment-rules.md` (this file)

### Quality Gates

- **LINE-FLOOR**: all three docs >= 150 substantive lines
  (340 / 337 / 350). All three exceeded the EA prompt's expected
  ranges (observability ~400, deployment ~200-300, rule-engine ~200).
  observability came in under the ~400 suggestion but well clear of
  the floor; the subject surface is smaller than anticipated because
  standard Python `logging` semantics carry most of the weight.
- **STYLE-CONFORMANCE**:
  - `observability.md` reports 5 level-2 headers (Audience,
    Prerequisites, Source References, Governance Content, Open
    Questions / Deferred Items). Recovery / Remediation Procedures
    was merged into Governance Content per STYLE.md line-count-floor
    allowance: BlarAI observability tooling has no externally
    triggered failure mode with an operator-facing recovery ceremony
    (service-side recovery is governed by `error-recovery.md` and
    `circuit-breaker.md`).
  - `deployment-verification.md` reports 6 level-2 headers including
    a substantive Recovery section (rollback procedures,
    automatic-vs-manual paths, model rollback per ADR-012 §5).
  - `rule-engine.md` reports 6 level-2 headers including a Recovery
    section covering fail-closed DENY behavior and operator
    rule-debugging workflow.
- **SOURCE-ANCHOR**: every doc cites >= 1 ADR and >= 1 source file.
  - GOV-12: ADR-010, ADR-011 cited; closest-relevant + ADR-absence
    handling per STYLE.md (no ADR directly governs logging format).
    Source anchors include `launcher/__main__.py`,
    `launcher/guest_deploy.py`, `shared/runtime_config.py`,
    `services/policy_agent/src/entrypoint.py`,
    `services/assistant_orchestrator/src/entrypoint.py`,
    `services/assistant_orchestrator/src/pgov.py`,
    `services/ui_gateway/src/transport.py`.
  - GOV-13: ADR-012 §5 (Qwen2.5-1.5B fallback) and ADR-011 cited.
    Source anchors: `launcher/guest_deploy.py` (all 10 error codes
    enumerated), `launcher/__main__.py` (preflight + cleanup),
    `launcher/vm_manager.py`, `shared/constants.py`.
  - GOV-14: ADR-010 cited as the deterministic-before-LLM mandate;
    ADR-absence for rule-engine scoring threshold noted.
    Source anchors: `services/policy_agent/src/deterministic_policy_checker.py`
    (rule set enumerated from source), `services/policy_agent/src/car.py`,
    `shared/schemas/car.py`, `services/assistant_orchestrator/src/pgov.py`
    (cosine threshold 0.85).
- **ORACLE** (`git diff main...HEAD --name-only`): filtered
  `grep -vE "^docs/"` returns empty. Only the three governance docs
  and this ledger entry appear in the diff. L-15 machine-verified
  clean; zero `services/`, `shared/`, `launcher/`, `tests/` paths.
- **REGRESSION**: pytest `shared/ services/ launcher/` executed on
  branch; result recorded in completion comment. Sprint 8 baseline
  floor (962 passed) unchanged — Sprint 9 EA-4 is a pure-docs
  milestone and could not plausibly regress tests, but the run was
  performed to satisfy the REGRESSION gate per prompt.
- **L16-DISJOINT**: zero test-file overlap with Sprint 8; the diff
  contains no `tests/` or `conftest` paths.

### Notes / Substitutions

- **ADR-absence handling (GOV-12 and GOV-14).**
  - GOV-12: no ADR directly governs logging format, severity taxonomy,
    or evidence-JSON schema. Cited ADR-010 and ADR-011 as
    closest-relevant (they produce the highest-volume logging
    surfaces) per STYLE.md §Source Anchoring. Flagged as an
    ADR-candidate gap in Open Questions.
  - GOV-14: ADR-010 governs the deterministic-before-LLM ordering but
    not the cosine-similarity threshold (0.85) used by the
    probabilistic classifier. Flagged the threshold's
    lack-of-ADR-anchor in Open Questions; cited `pgov.py` source as
    authoritative for the numeric value.
- **Phantom-reference discipline (L-17 / NC-4).** `boot-sequence.md`
  is referenced only as `(forthcoming / GOV-15)` in each doc's Open
  Questions section. No stub created; no cross-reference link to a
  non-existent file.
- **Rule enumeration from source (I.4 / WI-3).** The rule set in
  `rule-engine.md` was enumerated by re-reading
  `deterministic_policy_checker.py` at pickup. No prior summary or
  audit finding was trusted for rule count or pattern text. Source
  was authoritative.
- **Sensitive-data logging finding (I.5 / GOV-12).** Source review
  confirmed that BlarAI services deliberately omit prompt text and
  token content from log events at the IPC transport boundary
  (`transport.py`). The doc describes actual behavior and flags the
  small number of sites that could still emit user-derived strings
  at `ERROR` severity (e.g., handshake validation failures) as a
  hardening candidate in Open Questions.
- **Deployment-timeout finding (I.3 / GOV-13).** Source review of
  `launcher/__main__.py` and `launcher/guest_deploy.py` did not
  surface an explicit deployment-wide timeout constant. The doc
  documents the observation as a governance gap and surfaces it in
  Open Questions as a candidate for a future sprint. No timeout
  value was invented.
- **Audience persona discipline (I.6).** Each doc names 2-3 primary
  personas per STYLE.md §Audience Taxonomy:
  observability → developer / incident responder / auditor;
  deployment-verification → operator / incident responder / developer;
  rule-engine → developer / auditor / operator.
- **EA-1 / EA-2 / EA-3 retroactive-edit prohibition (NC-2).** No
  inline edits to prior-EA governance docs. Forward cross-references
  only.
- **Parent head.** Feature branch was already established at HEAD
  `ad311ac` (the Co-Lead Phase-2 auto-merge completion for EA-3).
  No advance of main between prompt authoring and EA execution.
- **Ledger convention.** Q1-1 per-file directory-per-entry per
  `docs/ledger/README.md`. The monolithic
  `docs/POST_OPERATIONAL_MATURATION_LEDGER.md` was frozen by fleet
  commit dc768b1 — NOT appended to here.

### Follow-ups

- ADR-candidate: logging format / severity taxonomy / evidence-JSON
  schema (GOV-12 Open Questions).
- ADR-candidate: cosine-similarity threshold for PGOV probabilistic
  classifier (GOV-14 Open Questions).
- Deployment-wide timeout constant (GOV-13 Open Questions) —
  candidate for a future hardening EA.
- Sensitive-data logging hardening at handshake/error boundaries
  (GOV-12 Open Questions) — candidate for a future hardening EA.
- `boot-sequence.md` (phantom reference) — deferred to GOV-15 per
  Sprint 9 close-out plan.

### Cross-References

- EA prompt: `docs/scheduled/ea_queue/P5_TASK9_EA4_OPS_DEPLOYMENT_RULES.xml`
- Predecessor ledger: `docs/ledger/20260422_203647_sprint9_ea3_operational-state.md`
- SDV: `docs/sprints/sprint_9/strategic_design_vision.md`
- SDO continuation: `docs/P5_TASK9_SDO_CONTINUATION_v1.0.xml`
- SDO comprehension-review APPROVED: commit `390b435`
  (`[agent:sdo] report: comprehension-review APPROVED for Task 82 EA-4 and Task 121 EA-4`)
- EA comprehension report: commit `d35d89c`
  (`[agent:ea_code] report: comprehension for Task 82 EA-4 and Task 121 EA-4`)
