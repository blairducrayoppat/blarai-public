---
# Strategic Design Vision (SDV) — BlarAI Sprint 9
#
# Authored interactively by Co-Lead Architect + Lead Architect at sprint start.
# Baseline against which the end-of-sprint SCR and SWAGR measure success and gap.
---
sprint_id: 9
sprint_name: "Governance Documentation"
predecessor_sprint_id: 8
vikunja_tracking_task_id: 121
start_date: "2026-04-22"
target_completion_date: "open — no hard deadline per LA directive 2026-04-22 (mature-not-minimal motto)"
la_approved_on: "2026-04-22T02:38:28-05:00"
la_approved_by: "blarai"
co_lead_drafted_on: "2026-04-22T02:30:00-05:00"
co_lead_commit_when_drafted: "2195d8e"
sdv_version: 1
---

# Strategic Design Vision — Sprint 9: Governance Documentation

## 1. Executive brief

Sprint 9 authors 12 new governance markdown documents that consolidate scattered operational,
architectural, and security governance across BlarAI's major surface areas: Inter-Process
Communication (IPC), Pre-Governance Output Validation (PGOV), GPU runtime configuration,
error recovery, circuit breakers, context spotlighting, session state, configuration
management, observability, deployment verification, and the policy-engine rule set. These 12
correspond to Vikunja tickets GOV-02 through GOV-09 and GOV-11 through GOV-14. **GOV-01
(Credential & Certificate Lifecycle) and GOV-10 (Weight Integrity Verification) are
deliberately excluded** — both depend on the Microsoft Pluton security processor's sealing
capabilities, and the feasibility of those capabilities on the target hardware is still
under investigation via ISS-4 (Pluton on Intel Core Ultra 258V Lunar Lake). Done = 12 new
governance docs on main under `docs/governance/`, a `docs/governance/README.md` entry page
listing all governance domains (12 authored + 2 Pluton-blocked + 1 phantom reference), 12
Vikunja GOV tickets closed with commit hashes recorded, and a follow-up ticket opened for
post-Sprint-8 migration of the pre-existing `docs/TEST_GOVERNANCE.md` into the new directory.

Sprint 9 runs in **parallel with Sprint 8** per the multi-sprint execution support shipped
in commit `20db5e7` (2026-04-22). Sprint 8 is test-authoring (writes `**/tests/`), Sprint 9
is docs-only (writes `docs/governance/**`) — the two working sets do not overlap. The
Strategic Development Orchestrator (SDO) is responsible for verifying non-overlap at
Execution Agent (EA) prompt-authoring time.

The guiding principle: **mature not minimal**. Each governance doc should be a complete,
standalone operational reference — not the minimum that satisfies the GOV ticket's literal
bullet list. Docs should include target-audience framing (operator / developer / auditor),
prerequisite knowledge, referenced Architecture Decision Records (ADRs), referenced source
files, example scenarios, and recovery procedures. LA directive (2026-04-22): no hard
deadline; the sprint completes when the docs are mature.

## 2. Context

### 2.1 Predecessor sprint outcome

- **Predecessor SCR**: N/A — Sprint 9 is a **parallel peer** of Sprint 8 rather than its
  successor. Sprint 8 is still in-flight (Strategic Design Vision signed 2026-04-22 at
  commit `25ac435`; EA-1 Policy Agent test hardening merged retroactively at commit
  `2195d8e`; EA-2 through EA-5 queued). No Strategic Completion Report (SCR) or Strategic
  Work Analysis & Gap Report (SWAGR) exists for Sprint 8 yet because the sprint has not
  closed.
- **Predecessor SWAGR**: N/A — no SCR to audit.
- **Sprint 7** (the last fully-closed sprint in the record) predates DEC-15 and produced
  no SDV, SCR, or SWAGR. No measurable baseline.
- Sprint 8 is expected to close in the 2026-04-24 to 2026-04-29 window based on Sprint 8's
  own target_completion_date. Sprint 9 running in parallel extends the fleet's throughput
  rather than depending on Sprint 8's closure. **Coexistence is the design intent, not a
  workaround.**

### 2.2 Repo state at kickoff

- Main branch HEAD: `2195d8e` (Sprint 8 EA-1 completion-review retroactive)
- Most recent ledger entry: Entry 50 (Task 7/EA-5 Synthesis — COMPLETE, 2026-04-21). Note:
  `CLAUDE.md` states 43 entries; the operational-state section is stale. Not a Sprint 9
  concern — flagging for a future CLAUDE.md refresh sprint.
- Open Vikunja `Gate:Pending-Human` gates on the Agent Gates bus (project 6): 0 — clean
  start for Sprint 9.
- Open Vikunja `Gate:Pending-CoLead` gates: 0.
- Known-active feature branches: none visible at main HEAD; Sprint 8 EA branches are
  short-lived (auto-merged per DEC-11 §3.4 `trusted_scope`).
- Uncommitted working-tree files at kickoff: 6 (`phase2_gates/evidence/uat2_milestone2_prompt_flow.json`,
  `phase2_gates/evidence/uat2_real_runtime_activation.json`, `tools/autonomy_budget/state.json`,
  `tools/scheduled-tasks/wake-co_lead_architect.xml`, `tools/scheduled-tasks/wake-ea_code.xml`,
  `tools/scheduled-tasks/wake-sdo.xml`) — fleet idle-state artifacts from the
  agents.ps1 task manager tooling (commit `e814c08`), not blocking Sprint 9.

### 2.3 External inputs driving this sprint

- **LA discovery session (2026-04-22)**: scoped Sprint 9 as authoring-focused closure of the
  14 GOV tickets, with GOV-01 and GOV-10 excluded pending Pluton investigation (ISS-4).
  Directive: "mature not minimal", no hard deadline.
- **LA direction on directory structure (2026-04-22)**: open question raised about whether
  new governance docs should live under `docs/governance/` versus the current flat pattern
  at `docs/*.md`. LA noted concern about (a) fragmentation between new docs and the
  existing `docs/TEST_GOVERNANCE.md`, and (b) breaking existing inbound references if the
  pre-existing doc is relocated. **Resolution (Co-Lead, this SDV §5.3)**: new Sprint 9
  docs land under `docs/governance/`; the pre-existing `TEST_GOVERNANCE.md` is NOT moved
  during Sprint 9 to avoid conflicting with Sprint 8 (which references it at its current
  path in the signed SDV and likely in in-flight EA prompts). Post-Sprint-8 migration is
  opened as a follow-up Vikunja ticket at sign-off.
- **LA direction on naming convention (2026-04-22)**: noted that no real naming convention
  exists for governance docs today. **Resolution (Co-Lead, this SDV §5.3)**: Sprint 9
  adopts lower-kebab-case filenames under the `docs/governance/` directory (matching the
  existing `docs/runbooks/` subdirectory pattern), dropping the redundant `_GOVERNANCE`
  suffix since the directory name supplies that context.
- **Commit 20db5e7 (2026-04-22)**: multi-sprint parallel execution support shipped. SDO
  wake template Phase 0 now iterates all active_tasks entries independently; Co-Lead
  Phase 3 split into 3a (bootstrap check — author missing continuation XMLs for all active
  roster entries) + 3b (succession scan); EA Code task scheduler's MultipleInstancesPolicy
  flipped from `IgnoreNew` to `Parallel`. Explicit design intent: docs-only sprint vs code
  sprint running simultaneously with working-set separation.
- **DEC-15 (approved 2026-04-21)**: sprint-level SDV/SCR/SWAGR lifecycle. Sprint 8 was its
  first live run; Sprint 9 is the first live run under the parallel-execution variant.
- **Sprint Auditor role active since Sprint 8 kickoff**: will fire on Sprint 9 SCR once
  that artifact exists at sprint end.

## 3. Sprint purpose

BlarAI's operational surface has matured faster than its governance documentation. Code and
ADRs describe **what** the system does and **why** the architecture was chosen; what is
scattered or missing is the **how** — how an operator runs the system, how a developer
debugs a failure, how an auditor confirms a security invariant, how a future agent joining
the codebase orients themselves without reverse-engineering `services/*/src/*.py` comments.
Sprint 7's test-quality audit repeatedly surfaced this gap: reviewers could not confirm
threshold rationales, recovery procedures, or operational intent because those facts lived
only in code docstrings — or not at all. The 14 GOV tickets were authored to close this
gap; Sprint 9 authors 12 of the 14.

The strategic leverage is largest at the security and wire-protocol boundaries (EA-1:
PGOV, IPC, streaming). These three docs tie the operator-visible behavior to the
fail-closed invariants the system is built on; without them, a future incident responder
debugging a PGOV denial sees only "output suppressed" in the TUI and must read
`services/assistant_orchestrator/src/pgov.py` line-by-line to understand why. The runtime
cluster (EA-2: GPU runtime, error recovery, circuit breaker) is the next layer down — the
operational procedures a non-developer operator needs to tune model behavior or recover
from a runtime fault. The state cluster (EA-3: context spotlighting, session state,
configuration) captures the persistence and prompt-assembly governance that USE-CASE-005
(Code Agent) and USE-CASE-009 (Autonomous Maintainer) will build on. The operations cluster
(EA-4: observability, deployment, rule engine) closes the operational-lifecycle surface.

If Sprint 9 were skipped: future EAs touching any of these services would operate without a
governance baseline, forcing each new EA prompt to re-derive operational intent from
scattered sources. This creates two compounding risks: (1) divergent interpretations across
EAs (one EA assumes PGOV's 0.85 threshold is adjustable; another treats it as invariant),
and (2) slower EA execution as each prompt must include extensive code-reference preambles.
Governance docs act as pre-loaded context for future EAs — author them once, reference them
many times.

Sprint 9 also exercises the multi-sprint parallel execution support for the first time.
That infrastructure shipped four hours before this SDV was drafted; Sprint 9 is the shakedown
run. Lessons learned from the parallel coexistence (git conflicts, SDO non-overlap checks,
EA scheduler concurrency) feed back into the SCR and SWAGR at sprint end.

## 4. Success criteria

1. **12 governance docs on main**: all 12 in-scope governance documents authored under
   `docs/governance/*.md` following the lower-kebab-case naming convention. Each doc is
   complete per the "mature not minimal" directive — it includes target audience,
   prerequisite knowledge, referenced ADRs, referenced source files, example scenarios,
   and (where applicable) recovery procedures. *Verification: `ls docs/governance/*.md`
   returns 12 files matching the names in §6; each file ≥ 150 lines; each file has been
   touched by a commit on main with author `[agent:ea_code]`.*

2. **Governance landing page present**: `docs/governance/README.md` exists and enumerates
   all 14 governance domains (12 authored + 2 Pluton-blocked) plus the phantom-reference
   gap (`BOOT_SEQUENCE_GOVERNANCE`). Each entry has a one-line abstract and either a link
   to the doc or a note explaining why it is deferred. *Verification: file exists on main;
   grep confirms 14 entries + the phantom note.*

3. **12 GOV Vikunja tickets closed with commit hashes**: every in-scope GOV ticket
   (GOV-02 through GOV-09, GOV-11 through GOV-14) marked complete via `complete_task`;
   sprint-close comment records the merge commit hash. *Verification: `list_tasks`
   filtered to project 3 with `done=true` returns these 12 GOV titles; each has a
   closing comment with a 7-char hash.*

4. **Zero production/test code changes**: No file outside `docs/` appears in any Sprint 9
   EA's git diff against main. *Verification: `git diff main...<ea-branch> --name-only |
   grep -vE "^docs/"` returns empty for every Sprint 9 EA branch.*

5. **Regression baseline unaffected by parallel Sprint 8 coexistence**: Sprint 8's success
   criteria (755 passed / 2 skipped floor) hold throughout Sprint 9 execution. Any test
   regression observed during Sprint 9 is a Sprint 8 concern, not a Sprint 9 concern, but
   Sprint 9 commits MUST NOT cause a regression. *Verification: Sprint 8's own pytest
   verification remains green at every Sprint 9 merge point.*

6. **Each doc anchored to verifiable source**: Every governance doc cross-references at
   least one ADR (where applicable) and at least one source file from its GOV ticket's
   "Scattered Sources" list. This is the anti-fiction guarantee — docs describe behavior
   traceable to code, not aspirational procedures. *Verification: grep each doc for a
   `docs/adrs/ADR-` or `services/` path reference.*

7. **Two follow-up tickets opened** at sprint sign-off: (a) `GOV-MIGRATE: Consolidate
   docs/TEST_GOVERNANCE.md into docs/governance/ after Sprint 8 closes` and (b) `GOV-15:
   Author Boot Sequence Governance doc (phantom reference discovered during Sprint 9
   audit)`. *Verification: `search_tasks("GOV-MIGRATE")` and `search_tasks("GOV-15")` both
   return non-empty results after Sprint 9 SCR.*

## 5. Scope

### 5.1 In-scope

Each of the 12 deliverables is one governance document. Source specifications are the
corresponding Vikunja GOV ticket description — each ticket already declares intent, target
audience, and the source-file inventory to research.

1. **EA-1 / GOV-04 — PGOV Validation Governance** (`docs/governance/pgov-validation.md`):
   Six-stage output-validation pipeline (token budget → PII/secret detection → delimiter
   echo → tool-call allowlist → retrieval leakage → final gate); embedding model
   (`bge-small-en-v1.5` ONNX on CPU) and cosine threshold 0.85 rationale; fail-closed
   semantics (PGOV error = maximum leakage score = suppress); fallback message exact text;
   user notification mechanics; audit-trail governance; threshold-tuning governance.

2. **EA-1 / GOV-02 — IPC Protocol & Message Format Governance**
   (`docs/governance/ipc-protocol.md`): Canonical Action Representation (CAR) schema;
   `StreamToken` structure; request/response envelope (mTLS + JWT + CAR hash); vsock wire
   protocol (`AF_HYPERV` socket, CID/port constants, TCP-like behavior); ordering /
   backpressure / flow-control semantics; error response format; JWT-to-CAR hash
   verification at destination; nonce replay detection; epoch validation; example
   request/response cycles; timeout behavior.

3. **EA-1 / GOV-03 — Streaming Output Governance**
   (`docs/governance/streaming-output.md`): `StreamToken` field semantics; streaming
   lifecycle (first → mid → final → end-of-sequence); TUI receive-and-buffer; PGOV
   validation timing; TUI display of thinking tokens (`is_thinking=True`);
   `StreamingDisplay` buffer/state machine; backpressure; circuit-breaker mid-stream
   termination; mid-generation crash recovery.

4. **EA-2 / GOV-05 — GPU Runtime & Speculative Decoding Configuration Governance**
   (`docs/governance/gpu-runtime.md`): Model-load procedure (Qwen3-14B INT4 + Qwen3-0.6B
   INT4 draft); `num_assistant_tokens=3` lock per ADR-012 §2.2; KV-cache management (FP16,
   PA \~350-550MB, AO \~1-1.2GB); circuit-breaker trip effect on KV-cache; thinking-mode
   suppression mechanics (`/no_think` + stop-token IDs `[151645, 151668]`); XAttention OFF
   rationale; empirical performance baseline (10.72 tps @ 4K, 4.17 tps @ 20K per P5-005b);
   model rollback procedure (Qwen2.5-1.5B retained per ADR-012 §5).

5. **EA-2 / GOV-06 — Error Handling & Crash Recovery Governance**
   (`docs/governance/error-recovery.md`): Fail-Closed principle per subsystem; PA
   adjudication errors; AO generation errors; JWT/mTLS failure handling; model-load
   failure; weight-integrity check failure (forward-references GOV-10 once Pluton
   unblocks); vsock IPC failures; OOM handling; user-facing error messages per class;
   logging and audit trail; automatic retry vs manual escalation matrix; boot-time vs
   runtime failure distinction.

6. **EA-2 / GOV-07 — Circuit Breaker Governance**
   (`docs/governance/circuit-breaker.md`): Two independent breakers (`MAX_OUTPUT_TOKENS=
   4096` + `MAX_TOOL_CALL_DEPTH=5`); token-counter semantics (including thinking-token
   behavior); trip behavior (output truncation + fallback message); exact fallback message
   text; per-session vs cross-session reset semantics; threshold-tuning governance;
   monitoring (breaker-trip logging + operator query); interaction with PGOV; interaction
   with streaming.

7. **EA-3 / GOV-08 — Context Spotlighting & Anti-Injection Governance**
   (`docs/governance/context-spotlighting.md`): Delimiter tokens (`CONTEXT_BEGIN`,
   `CONTEXT_END`, `SYSTEM_BEGIN`, `SYSTEM_END`); insertion points in prompt-assembly
   pipeline; rationale (prevent injection via retrieved documents); model instructions re:
   untrusted-data boundary; delimiter-validation in PGOV stage 3; retrieved-content
   chunking; isochronous retrieval timing rationale; empty-context behavior; compliance
   audit procedures.

8. **EA-3 / GOV-09 — Session State Persistence & Recovery Governance**
   (`docs/governance/session-state.md`): SQLite session storage
   (`%LOCALAPPDATA%\BlarAI\sessions.db`, schema); persisted attributes; flush timing;
   session lookup by ID; orphaned-session cleanup and retention; UUID generation scheme;
   cross-restart persistence; session privacy (encryption-at-rest status); session
   export/backup; deletion semantics (permanent vs soft-deleted for audit); concurrent
   session limits; KV-cache relationship to session state; KV-cache state after system
   crash.

9. **EA-3 / GOV-11 — Configuration Management Governance**
   (`docs/governance/configuration-management.md`): Config-file format and locations;
   per-service configuration requirements (PA / AO / TUI / launcher); startup-validation
   fatality matrix; hot-reload vs full-restart; config versioning and migration;
   secrets-in-config policy; config-audit log; default-values rationale; configuration
   dependency chain.

10. **EA-4 / GOV-12 — Observability & Logging Strategy Governance**
    (`docs/governance/observability.md`): Log levels and event classification; log
    destinations (stdout / file / multiple sinks); log format (JSON structured vs plain);
    log rotation; sensitive-data filtering; PA adjudication logging; AO generation
    logging; IPC logging scope; performance instrumentation; health-check metrics; audit
    trail; error-fingerprinting classification.

11. **EA-4 / GOV-13 — Deployment Verification & Rollback Governance**
    (`docs/governance/deployment-verification.md`): Pre-deployment checks; runtime-artifact
    deployment (`launcher/guest_deploy.py`); model-artifact deployment verification;
    deployment-evidence artifacts; smoke-test execution; deployment timeout; rollback
    procedure (automatic + manual emergency); model rollback (Qwen2.5-1.5B per ADR-012
    §5); deployment-audit trail; post-restart validation; emergency-rollback manual.

12. **EA-4 / GOV-14 — Rule Engine & CAR Validation Governance**
    (`docs/governance/rule-engine.md`): Deterministic rule set (regex + semantic
    distance); deterministic-before-LLM ordering; fail-closed semantics; rule
    authoring and versioning; CAR schema enforcement; semantic-distance metric and
    threshold; example CARs (pass vs fail); per-action-verb rules; ESCALATE rules;
    performance budget; rule-debugging procedures.

13. **EA-5 / Sprint 9 synthesis — Governance Landing Page**
    (`docs/governance/README.md`): Table of all 14 governance domains + the phantom-ref
    gap + the TEST_GOVERNANCE migration note; one-line abstract per entry; link (or
    deferred-with-reason note); target-audience taxonomy (operator / developer /
    auditor) showing which docs serve which audience; navigation footer linking to
    related CLAUDE.md sections, ADRs, and runbooks.

### 5.2 Out-of-scope (deliberately deferred)

1. **GOV-01: Credential & Certificate Lifecycle Governance** — requires documentation of
   Pluton-sealed Certificate Authority (CA) key storage procedures that depend on Pluton
   feasibility findings not yet available. Deferred until ISS-4 (Pluton investigation on
   Intel Core Ultra 258V Lunar Lake) closes and the Pluton operational surface is known.
2. **GOV-10: Weight Integrity Verification Procedure** — requires documentation of the
   Pluton-sealed manifest provisioning ceremony and boot-time SHA-256 check against
   sealed-manifest hash. Same deferral reason as GOV-01.
3. **Migration of `docs/TEST_GOVERNANCE.md` into `docs/governance/`** — the pre-existing
   governance doc has approximately 101 inbound references across 34 files, including 3
   in Sprint 8's signed SDV and likely in in-flight Sprint 8 EA prompts. Moving it during
   active Sprint 8 parallel execution would break those references and violate the
   working-set separation guarantee. A follow-up ticket `GOV-MIGRATE` is opened at
   Sprint 9 sign-off; the migration executes in a future sprint after Sprint 8 closes.
4. **Authoring `docs/governance/boot-sequence.md`** — referenced in GOV-10 ticket body
   and GOV-12 ticket body as if it exists, but **no file exists on disk**. This is a
   phantom reference that was never authored. A follow-up ticket `GOV-15` is opened at
   Sprint 9 sign-off; authoring is a future-sprint scope.
5. **Production code or test changes** — Sprint 9 is a pure documentation sprint. If an EA
   discovers a code defect during research (e.g., a constant in `pgov.py` contradicts the
   ADR it should implement), the EA records the finding in its completion report and
   opens a new Vikunja ticket. It does NOT modify code.
6. **Retroactive re-audit of existing `docs/TEST_GOVERNANCE.md`** — Sprint 9 authors new
   docs; it does not re-review or amend existing ones. If inconsistencies are discovered,
   they become new tickets.
7. **Doc-lint tooling, governance portal, or documentation-as-code automation** — mature
   tooling ambitions that exceed the single-sprint scope; may be Sprint 10+ scope.
8. **Amendment of existing ADRs** — docs reference ADRs for traceability; they do not
   modify ADR content. If a doc surfaces an ADR ambiguity, a new Vikunja ticket opens.

### 5.3 Scope boundaries and edge cases

- **Directory structure**: all 12 new docs + the landing page live under
  `docs/governance/`. Rationale: establishes a clean organizational home for the
  governance class, matches the existing `docs/runbooks/` lowercase-subdirectory
  precedent, and prepares the ground for the deferred `TEST_GOVERNANCE.md` migration
  without requiring Sprint 9 to perform the migration itself.

- **Filename convention (per-doc)**: lower-kebab-case, no `_GOVERNANCE` suffix. The
  directory name (`governance/`) supplies the governance context; appending
  `_GOVERNANCE` to every filename is redundant. Examples: `ipc-protocol.md` not
  `IPC_PROTOCOL_GOVERNANCE.md`; `circuit-breaker.md` not `CIRCUIT_BREAKER_GOVERNANCE.md`.
  This convention is intentionally different from the pre-existing
  `docs/TEST_GOVERNANCE.md`; when that doc is migrated in a future sprint, it is
  renamed to `docs/governance/test.md` as part of the migration.

- **Landing-page filename**: `docs/governance/README.md` — chosen because GitHub
  auto-renders `README.md` when a user browses a directory, giving the governance
  directory a self-serving entry point without requiring a separate `INDEX.md`.

- **"Mature not minimal" floor per doc**: each governance doc is expected to run at least
  150 lines of substantive content. Docs shorter than that are a signal of incomplete
  thinking, not of a narrow topic. GOV-14 (Rule Engine) is the shortest-scope ticket and
  sets the floor; larger-scope docs like GOV-05 (GPU Runtime) may run 400+ lines.

- **Source anchoring (success criterion 6)**: every doc MUST cross-reference at least one
  ADR (where applicable) and at least one source file from its ticket's "Scattered
  Sources" list. This prevents docs from drifting into aspirational or fictional
  territory. EA comprehension gates must recite the source-file list the EA plans to
  anchor against.

- **Adjacent-scope expansion (mature-not-minimal extension)**: if while writing
  `circuit-breaker.md` an EA discovers that the PGOV interaction (already documented in
  `pgov-validation.md` at §N) would benefit from being mirrored in the circuit-breaker
  doc, the EA is authorized to include the mirror. Cross-referencing is not scope creep;
  it is coherence maintenance. However, the EA does NOT retroactively edit
  `pgov-validation.md` — only forward-references are added.

- **Target-audience framing**: each doc opens with an "Audience" stanza declaring who the
  doc is for (typically a subset of: operator, developer, auditor, incident responder,
  future agent). This framing shapes the tone — operator-facing docs emphasize runbook
  steps; developer-facing docs emphasize source pointers; auditor-facing docs emphasize
  fail-closed invariants and evidence.

- **EA-1 establishes the style guide**: the first EA (GOV-04 PGOV + GOV-02 IPC + GOV-03
  Streaming) authors a terse `docs/governance/STYLE.md` as a sub-artifact before
  beginning the three docs. Subsequent EAs (EA-2, EA-3, EA-4) read STYLE.md before
  authoring. This centralizes cross-EA style consistency without blocking EA-1 on a
  separate style-guide EA. STYLE.md is NOT listed as a success-criterion deliverable
  because it is an internal-coordination artifact, not a governance doc.

- **SDO non-overlap verification (Sprint 8 coexistence)**: when SDO authors each Sprint 9
  EA prompt, its Phase 2 step must verify that no concurrent Sprint 8 EA prompt writes
  to `docs/governance/**`. At prompt-authoring time this is trivial (Sprint 8 writes
  under `**/tests/`), but SDO must record the check explicitly in its comprehension
  recitation. If Sprint 8 scope ever expanded to touch `docs/governance/**` mid-sprint,
  SDO would halt the Sprint 9 EA and escalate.

## 6. Deliverable summary

| # | Deliverable | Type | Target location | Success criterion |
|---|---|---|---|---|
| 1 | PGOV Validation governance | doc | `docs/governance/pgov-validation.md` | #1, #6 |
| 2 | IPC Protocol governance | doc | `docs/governance/ipc-protocol.md` | #1, #6 |
| 3 | Streaming Output governance | doc | `docs/governance/streaming-output.md` | #1, #6 |
| 4 | GPU Runtime governance | doc | `docs/governance/gpu-runtime.md` | #1, #6 |
| 5 | Error Recovery governance | doc | `docs/governance/error-recovery.md` | #1, #6 |
| 6 | Circuit Breaker governance | doc | `docs/governance/circuit-breaker.md` | #1, #6 |
| 7 | Context Spotlighting governance | doc | `docs/governance/context-spotlighting.md` | #1, #6 |
| 8 | Session State governance | doc | `docs/governance/session-state.md` | #1, #6 |
| 9 | Configuration Management governance | doc | `docs/governance/configuration-management.md` | #1, #6 |
| 10 | Observability governance | doc | `docs/governance/observability.md` | #1, #6 |
| 11 | Deployment Verification governance | doc | `docs/governance/deployment-verification.md` | #1, #6 |
| 12 | Rule Engine governance | doc | `docs/governance/rule-engine.md` | #1, #6 |
| 13 | Governance landing page | doc | `docs/governance/README.md` | #2 |
| 14 | Internal style guide (EA-1 sub-artifact) | doc | `docs/governance/STYLE.md` | (internal coordination) |
| 15 | Sprint 9 follow-up: TEST_GOVERNANCE migration ticket | vikunja | project 3 | #7 |
| 16 | Sprint 9 follow-up: GOV-15 boot-sequence ticket | vikunja | project 3 | #7 |
| 17 | Sprint-close comment on Sprint 9 tracking task | vikunja | tracking task | #3 |

## 7. EA milestone plan

| EA-# | Working title | Docs (GOV ticket #) | Severity mix | Approx size | Depends on |
|---|---|---|---|---|---|
| EA-1 | Security Boundary & Wire Protocol | GOV-04 PGOV, GOV-02 IPC, GOV-03 Streaming | 3× HIGH | L (establishes STYLE.md) | main (`2195d8e`) |
| EA-2 | Runtime Behavior & Resilience | GOV-05 GPU Runtime, GOV-06 Error Recovery, GOV-07 Circuit Breaker | 3× HIGH | M | EA-1 merged (STYLE.md) |
| EA-3 | Operational State | GOV-08 Context Spotlighting, GOV-09 Session State, GOV-11 Configuration Management | 3× MEDIUM | M | EA-2 merged |
| EA-4 | Ops, Deployment, Rule Engine | GOV-12 Observability, GOV-13 Deployment, GOV-14 Rule Engine | 2× MEDIUM + 1× LOW | M | EA-3 merged |
| EA-5 | Governance Landing Page | `README.md` synthesis + audience-taxonomy table | synthesis | S | EA-4 merged |

**Sequencing rationale**: HIGH-severity docs front-load so that if fleet capacity is
interrupted mid-sprint, the highest-leverage governance is already on main. EA-1 is
larger than the others because it also authors STYLE.md. EA-5 is the smallest (the
landing page synthesizes already-committed docs) and runs last because it references
all preceding docs. Within-sprint sequencing is strictly sequential (one EA at a time);
**parallel execution with Sprint 8 is the cross-sprint concurrency that matters**, not
within-Sprint-9 EA parallelism.

**Clustering rationale**: 
- EA-1 clusters the three security/wire-protocol docs that share source files
  (`services/assistant_orchestrator/src/pgov.py`, `services/ui_gateway/src/transport.py`,
  `services/ui_shell/src/streaming.py`). Authoring them together lets the EA read each
  source once and emit three coherent docs rather than revisiting.
- EA-2 clusters runtime-behavior docs that share `services/assistant_orchestrator/src/
  circuit_breaker.py` and the GPU-inference surface.
- EA-3 clusters state-management docs around `services/assistant_orchestrator/src/
  context_manager.py`, session persistence, and `shared/runtime_config.py`.
- EA-4 clusters ops/deployment/rule-engine docs around launcher + policy-engine surfaces.

## 8. Dependencies and prerequisites

### 8.1 Upstream dependencies

- Multi-sprint parallel execution support landed — ✅ commit `20db5e7` (2026-04-22)
- EA Code task scheduler's `MultipleInstancesPolicy` = `Parallel` — ✅ commit `20db5e7`
- SDO wake template Phase 0 iterating all active_tasks entries — ✅ commit `20db5e7`
- Co-Lead wake template Phase 3a/3b split — ✅ commit `20db5e7`
- Active Sprint 8 does not claim `docs/governance/**` in its SDV scope — ✅ confirmed
  (Sprint 8 SDV §5.1 enumerates test authoring only)
- Sprint 9 tracking Vikunja task created — ⏳ executed at sign-off (§Phase 4 of sprint
  kickoff skill)
- 12 GOV tickets exist in Vikunja project 3 — ✅ confirmed (tickets 15-22, 24-27)

### 8.2 External dependencies

- No external network dependencies (pure documentation sprint).
- No external tool dependencies beyond the fleet runtime (Claude Code scheduled tasks,
  Vikunja, git).
- Windows host for fleet EA agents — ✅ unchanged from Sprint 8.

### 8.3 Assumed invariants

- Sprint 8 does NOT expand scope during its remaining EAs (EA-2 through EA-5) to touch
  `docs/governance/**`. If it does, Sprint 9 SDO halts the affected Sprint 9 EA and
  escalates via a CAR (Cross-sprint Amendment Request).
- Source files referenced by each governance doc remain stable for the duration of
  Sprint 9. If a Sprint 8 EA's test-authoring changes expose a production-code defect
  worth fixing mid-sprint, that is Sprint 8's scope exception (already out-of-scope per
  Sprint 8 SDV §5.2 item 4); Sprint 9 would continue to describe the current behavior.
- Vikunja MCP server remains reachable for ticket closure. If Vikunja outage occurs
  mid-sprint, EAs commit their docs first, then close tickets when Vikunja returns.
- Git HEAD at `2195d8e` (or a forward-compatible descendant) remains the Sprint 9 base
  reference. Forced-reset or history-rewrite on main is a fleet-wide halt trigger
  regardless of sprint.

## 9. Risks and unknowns

### 9.1 Known risks

| Risk | Probability | Impact | Mitigation |
|---|---|---|---|
| Parallel-execution git conflict with Sprint 8 (both sprints touch `docs/`) | Low | Medium | SDO non-overlap check at prompt-authoring (§5.3); Sprint 8 SDV §5.1 confirms test-only writes; working sets are disjoint (`docs/governance/**` vs `**/tests/`) |
| Governance-doc style drift across EAs | Medium | Medium | EA-1 authors STYLE.md before beginning its three docs; subsequent EAs read STYLE.md as prompt input; Co-Lead peer review at each EA gate checks style adherence |
| EA over-applies "mature not minimal" → runaway doc length | Medium | Low | §5.3 sets a 150-line floor but no ceiling; Co-Lead peer review enforces editorial tightness; EAs flag docs over \~800 lines for Co-Lead coherence check |
| EA under-applies "mature not minimal" → thin docs that repeat the ticket bullet list | Medium | Medium | §5.3 sets a 150-line floor; source-anchoring requirement (§6) forces substantive content; Co-Lead peer review rejects docs that lack the Audience / Prerequisites / ADR / Source References stanzas |
| Source file referenced by a doc is misnamed or missing | Low | Low | EA reads each source file before citing; EAs treat discovery of a missing source as a finding, open a Vikunja ticket, and cite the gap rather than fabricate |
| Phantom `BOOT_SEQUENCE_GOVERNANCE.md` references propagate into new docs (EAs cite a file that doesn't exist) | Medium | Low | SDO prompt for GOV-10-adjacent work (e.g., GOV-05, GOV-12) explicitly warns the EA that `BOOT_SEQUENCE_GOVERNANCE.md` is phantom; EAs cite the boot-sequence behavior by source file, not doc |
| Sprint 8 closes mid-Sprint-9 and triggers Sprint 9 "predecessor_sprint_id" reinterpretation | Low | Low | Sprint 9's `predecessor_sprint_id=8` is a provenance field; Sprint 8's SCR/SWAGR produce at Sprint 8's own close regardless of Sprint 9 state; no Sprint 9 fields depend on Sprint 8 close |
| Pluton investigation (ISS-4) produces a finding mid-sprint that changes governance scope (e.g., Pluton is unavailable → credential-storage approach needs redesign) | Low | Medium | ISS-4 is expected to take weeks; Sprint 9 explicitly excludes Pluton-dependent GOV-01/10; if ISS-4 concludes mid-Sprint-9, LA may open a Sprint 9.1 or Sprint 10 scope expansion — Sprint 9 itself is insulated |

### 9.2 Known unknowns

1. Exact doc length per topic — GOV-05 (GPU Runtime + speculative decoding) and GOV-11
   (Configuration Management) are the largest surfaces; could run 500+ lines each. GOV-14
   (Rule Engine) is the narrowest and may run \~200 lines. Total Sprint 9 doc volume is
   estimated at 3000-4500 lines across 12 docs plus the landing page and STYLE.md.
2. Whether the parallel-execution SDO non-overlap check works as intended on first live
   exercise. Commit `20db5e7` is four hours old at Sprint 9 kickoff; Sprint 8 still runs
   sequentially. Sprint 9 is the shakedown.
3. Whether any GOV ticket's "Scattered Sources" list points to a file that has been
   renamed or deleted since ticket authoring (2026-04-18). EAs validate at prompt-read
   time.
4. How the Sprint Auditor's SWAGR frames cross-sprint coexistence. The SWAGR template
   does not yet have a parallel-sprint section; the auditor may flag the coexistence
   pattern and recommend template amendment. That's a Sprint 10+ concern, not a Sprint 9
   blocker.

### 9.3 Unknown unknowns posture

This sprint is nearly pure translation-from-spec — ticket → markdown doc. The design
surface is narrow. The two non-obvious failure modes are: (a) parallel-execution fleet
infrastructure failing in a way that corrupts either Sprint 8's or Sprint 9's state,
which would manifest as a wake template failing to parse the active_tasks roster or an EA
firing against the wrong sprint's prompt; (b) governance docs inadvertently baking in
implementation details that are already obsolete because Sprint 8's test-authoring work
will change behavior the doc relies on. The latter is mitigated by Sprint 8 SDV §5.2's
"no production code changes" constraint — Sprint 8 adds tests against existing behavior,
not new behavior — so Sprint 9 docs describing current behavior should remain valid
post-Sprint-8. If Sprint 8 surprises us by changing behavior, Sprint 9 reopens the
affected doc as a v2 in a later sprint; this is acceptable mature-evolution friction.

## 10. Alignment to long-term roadmap

- **Project phase alignment**: Phase 5 Post-Operational Development, governance
  hardening workstream. Sprint 9 is the first documentation sprint of that workstream;
  prior sprints (7, 8) addressed test quality. Together they form a two-axis hardening
  campaign: test coverage (Sprint 7/8) + operational governance (Sprint 9). Future
  sprints in the workstream include the deferred `TEST_GOVERNANCE.md` migration, the
  phantom-reference `BOOT_SEQUENCE` authoring, and the Pluton-dependent GOV-01/10 once
  ISS-4 unblocks them.

- **Use Case alignment**: all 9 Use Cases (UCs) benefit from governance documentation,
  but the leverage is largest for future use cases not yet implemented. USE-CASE-005
  (Code Agent) reads `session-state.md` and `configuration-management.md` to understand
  context persistence; USE-CASE-002 (Memory Search) reads `pgov-validation.md` and
  `context-spotlighting.md` to understand retrieval and injection boundaries;
  USE-CASE-009 (Autonomous Maintainer) reads `error-recovery.md` and `circuit-breaker.md`
  to understand fault boundaries. The docs are authored for the agents that will read
  them during future-sprint design, not just for the present human operator.

- **ADR alignment**: governance docs reference ADRs as source-of-truth for architectural
  decisions but do NOT amend ADRs. ADR-007 (iGPU trust boundary), ADR-010 (PA device
  allocation GPU), ADR-011 (all LLM inference on GPU), ADR-012 (Qwen3-14B + speculative
  decoding) are the most frequently cross-referenced. DEC-01 through DEC-10 (Task 4
  production config) are cross-referenced from `gpu-runtime.md` and
  `configuration-management.md`.

- **DEC alignment**: Sprint 9 is DEC-15's first parallel-execution live run. DEC-11
  (autonomy budgets) governs fleet runtime unchanged. DEC-12 (EA peer review lattice)
  governs EA gate flow unchanged. DEC-13 (report queue) emits fleet reports unchanged.
  DEC-14.5 (self-contained merge approve) governs trusted-scope auto-merge unchanged.

## 11. Roles and accountability

| Role | Responsibility this sprint | Budget |
|---|---|---|
| LA (Lead Architect) | SDV sign-off; CAR adjudication if a scope exception surfaces; SWAGR read at sprint end; approval of STYLE.md during EA-1 peer review if Co-Lead escalates a style question | \~20 min total |
| Co-Lead Architect | SDO continuation XML authoring for Sprint 9; EA prompt peer review via DEC-12 gate; **style-guide coherence check** on EA-1's STYLE.md before it becomes the cross-EA reference; SCR authoring at sprint end | Autonomous per DEC-11 §1.1 |
| SDO (Strategic Development Orchestrator) | 5 EA-prompt authoring cycles; **new duty**: non-overlap verification with Sprint 8 at each EA-prompt authoring; EA peer review | Autonomous per DEC-11 §1.2 |
| EA Code | Milestone execution (5 EAs); each EA reads STYLE.md (after EA-1 establishes it) and the assigned GOV tickets; authors docs under `docs/governance/`; opens follow-up tickets as findings surface | Autonomous per DEC-11 §1.3 |
| Sprint Auditor | SWAGR independent production post-SCR; **new territory**: first cross-sprint coexistence to audit — may flag gaps in SWAGR template re: parallel-execution | Autonomous per DEC-15 §sprint_auditor_role_spec |

## 12. Estimated effort

- **Rough duration**: open-ended per LA directive (no hard deadline; mature-not-minimal).
  Reference estimate for planning: 5 EAs × \~1 fleet-day per EA = 5 fleet-days. At the
  15-minute wake cadence with parallel Sprint 8 execution, this maps to roughly 1 to 1.5
  calendar weeks at current fleet capacity. Actual duration will be longer if EAs run
  deeper-than-minimum per the "mature not minimal" directive.
- **LA active-time expectation**: \~20 minutes total — 15 min SDV sign-off, \~5 min SWAGR
  read at sprint close. EA merges are auto-merged by Co-Lead under `trusted_scope` mode
  (DEC-11 §3.4); no per-merge LA gate fires unless a merge exceeds trusted-scope criteria
  (500 LOC threshold — unlikely for a single governance doc; if a doc commit exceeds it,
  it is almost certainly overweight and Co-Lead will flag for tightening rather than
  auto-approve).
- **Confidence in estimate**: **medium-high**. The work is translation-from-spec with
  minimal design surface, reducing estimate variance. The primary variance driver is
  "mature not minimal" interpretation — a deeper interpretation lengthens individual
  docs. Secondary variance: first exercise of parallel-execution infrastructure may
  surface latent bugs requiring fleet-ops fixes that cost days.

## 13. Deliberate non-goals

1. **Authoring a CONTRIBUTING-for-governance-docs guide** — **Rejected because** STYLE.md
   is the internal EA-coordination artifact and it suffices for the sprint; an external
   contributor guide is a Phase 6 concern.
2. **Cross-referencing every governance doc to every related ADR exhaustively** —
   **Rejected because** each doc needs at least one ADR cross-reference (success
   criterion 6) but forcing exhaustive cross-referencing inflates docs with low-leverage
   citations. Each doc cites the ADR(s) most directly load-bearing for its topic.
3. **Migrating `docs/TEST_GOVERNANCE.md` into `docs/governance/` during Sprint 9** —
   **Rejected** to avoid breaking Sprint 8's in-flight EA prompt references and the
   signed Sprint 8 SDV. Opened as follow-up ticket.
4. **Authoring `docs/governance/boot-sequence.md`** — **Rejected** because no GOV ticket
   exists for it; the phantom-reference discovery is outside Sprint 9 scope. Opened as
   follow-up ticket GOV-15.
5. **Authoring `pluton-operations.md` or any Pluton-related governance** — **Rejected**
   because Pluton feasibility on Intel Core Ultra 258V Lunar Lake is still under ISS-4
   investigation; authoring governance before the capability surface is known risks
   committing fiction to main.
6. **Building a governance-portal web view or markdown-rendering pipeline** —
   **Rejected** as tooling ambition outside a single-sprint scope.
7. **Governance doc linting / format enforcement tooling** — **Rejected** as premature
   automation; establish the convention first, automate enforcement once 12 docs provide
   the pattern corpus.
8. **Retroactive re-review of `docs/TEST_GOVERNANCE.md` during Sprint 9** — **Rejected**
   because the doc is actively referenced by Sprint 8; touching it risks conflict.

## 14. Sign-off

### Lead Architect

> I, `blarai`, have reviewed this SDV on `<date>`. I approve the sprint scope, success
> criteria, and risk posture as stated. I accept that the fleet will proceed autonomously
> per the DEC-11 budgets within these bounds. I will read the SCR and SWAGR when produced.

_(Signed via the frontmatter field `la_approved_on` above. A commit authored by LA on main
is the durable signature.)_

### Co-Lead Architect

> Co-Lead acknowledges the LA-signed SDV and will translate it into the first SDO
> continuation XML + milestone sequencing per the DEC-12 flow. Any scope deviation arising
> during execution will be flagged via the DEC-12 peer-review lattice or escalated via a
> CAR.

_(Signed via the frontmatter field `co_lead_drafted_on` + git commit by [agent:co_lead]
that lands this SDV on main.)_

---

## Appendix A — SDV revision log

| Version | Date | Changed by | Change summary |
|---|---|---|---|
| 1 | 2026-04-22 | Co-Lead | Initial draft |
