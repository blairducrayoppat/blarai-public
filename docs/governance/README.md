# Governance Documentation Index

This directory is the canonical home for BlarAI governance documents. Each
sibling file owns a single decision surface — a wire-protocol contract, a
fail-closed boundary, a configuration schema, a runtime invariant — and
records the contract a future reader (operator, developer, auditor,
incident responder, or successor agent) must honor before changing the
underlying code.

This README is a navigation index. It adds no new normative content; every
claim about a domain is a one-line summary or quoted excerpt of the linked
doc's own text. The style authority for the directory is
[STYLE.md](STYLE.md); the directory layout convention (lowercase
sub-directory + lower-kebab-case filenames + no `_GOVERNANCE` suffix) is
inherited from the Sprint 9 SDV §5.1 plan.

## Audience

Five reader personas use this directory, mirroring the audience taxonomy
defined in [STYLE.md §Audience Taxonomy](STYLE.md):

- **Operator** — runs BlarAI day-to-day. Reads for behavior, observable
  symptoms, and the small set of self-service remediations sanctioned by
  governance (rolling back a model, restarting a service, reading an
  evidence JSON).
- **Developer** — extends or refactors a service module. Reads for the
  invariants, contracts, and source anchors a code change must preserve
  before it can merge.
- **Auditor** — reviews the security boundary or the decision-record
  anchor (ADR / DEC) backing a fail-closed surface. Reads for the
  Red Team issue closure, the OWASP-LLM-Top-10 mapping, or the
  audit-trail contract.
- **Incident responder** — opens an investigation when BlarAI
  misbehaves in a way an operator cannot self-remediate. Reads for the
  failure-fingerprint catalogue, the recovery procedures, and the
  rollback paths.
- **Future agent** — Configuration Agent, Sprint Auditor, EA Code, SDO,
  Co-Lead Architect, or a successor model resuming after weeks of
  silence. Reads to learn the contract before touching any
  fleet-shared file (`tools/scheduled-tasks/wake_launcher.ps1`,
  `tools/autonomy_budget/state.json`, the EA queue directories, the
  active roster) or before authoring a new governance doc.

## How to Read This Directory

1. Skim the **Audience Taxonomy Matrix** below to find the docs that
   name your persona as a primary reader. Open those first.
2. Each doc opens with `## Audience` and `## Source References` — the
   first tells you whether you are the intended reader; the second tells
   you which production source files the doc binds to.
3. Cross-references between docs are relative (`[ipc protocol](ipc-protocol.md)`).
   References to the wider repo use `../` (e.g., `../adrs/`,
   `../runbooks/`, `../../CLAUDE.md`).
4. If a doc cites a phantom path (`boot-sequence.md`), see
   **Phantom and Forthcoming References** below — the file is not yet
   on disk and its work item is tracked.

## Governance Domain Inventory

The directory currently contains 13 domain docs + the style guide. The
domain docs cluster into five families by shared source surface and EA
authoring origin (Sprint 9 EA-1 through EA-4 + the out-of-plan Fleet
Hygiene addition). Cluster intros explain why the docs cluster.

### Security and Wire Protocol

EA-1 (Sprint 9). The three docs in this cluster own the boundary
between an attacker-controllable input and a deterministic enforcement
surface: the model output validator, the inter-agent message envelope,
and the streaming token path. They share two source surfaces
(`shared/ipc/`, `services/assistant_orchestrator/src/pgov.py`) and one
audit contract (Red Team ISSUE-005 closure for spotlight-layer-3
gaps).

- [pgov-validation.md](pgov-validation.md) — owns the six-stage
  deterministic post-generation validator that closes Red Team
  ISSUE-005 at the AO output boundary. EA-1 / GOV-04 (Vikunja #17).
- [ipc-protocol.md](ipc-protocol.md) — owns the CAR + envelope wire
  contract for inter-agent messages, including the Action
  Authorization Boundary (AAB) and replay-revocation hardening rules.
  EA-1 / GOV-02 (Vikunja #15).
- [streaming-output.md](streaming-output.md) — owns the streaming
  token protocol and the PGOV handoff invariants between AO streamer,
  Gateway, and TUI. EA-1 / GOV-03 (Vikunja #16).

### Runtime Behavior and Resilience

EA-2 (Sprint 9). The three docs in this cluster own the runtime
behavior of the GPU-resident inference loop and the fail-closed
fallback paths around it. Shared source surfaces:
`services/assistant_orchestrator/src/` (model loop + circuit breaker)
and `launcher/guest_deploy.py` (model rollback).

- [gpu-runtime.md](gpu-runtime.md) — owns the Arc 140V GPU memory
  envelope, Qwen3-14B speculative-decoding configuration (ADR-012
  §2.2 `num_assistant_tokens` lock), and rollback path to the
  Qwen2.5-1.5B fallback weights. EA-2 / GOV-05 (Vikunja #18).
- [error-recovery.md](error-recovery.md) — owns the cross-service
  Fail-Closed contract, the user-facing error texts, and the
  developer extension points for adding a new error subclass.
  EA-2 / GOV-06 (Vikunja #19).
- [circuit-breaker.md](circuit-breaker.md) — owns the Orchestrator
  circuit-breaker thresholds, trip semantics, and
  `record_tokens` / `record_tool_call` call sites that hard-enforce
  OWASP LLM04 "Model Denial of Service" mitigation. EA-2 / GOV-07
  (Vikunja #20).

### Operational State

EA-3 (Sprint 9). The three docs in this cluster own the per-session
state surfaces that bridge UI Shell, UI Gateway, and Orchestrator,
plus the configuration schema that governs every service at startup.
Shared invariant: per-session keying (no cross-session bleed) and
fail-closed startup on schema violation.

- [context-spotlighting.md](context-spotlighting.md) — owns the AO
  context-assembly path, the delimiter constants, and the rule that
  retrieved content must reach the model marker-delimited (closes
  Red Team ISSUE-008 "Prompt injection via retrieved documents").
  EA-3 / GOV-08 (Vikunja #21).
- [session-state.md](session-state.md) — owns session ID minting,
  persistence schema, reconnect semantics, and the per-session
  scope at which PGOV results / circuit-breaker state / context
  window are keyed. EA-3 / GOV-09 (Vikunja #22).
- [configuration-management.md](configuration-management.md) — owns
  the TOML schema, the 13 range/enum constraints validated at
  startup, and the DEC-01..DEC-10 decision-record anchoring for
  every production configuration knob. EA-3 / GOV-11 (Vikunja #24).

### Ops, Deployment, and Rules

EA-4 (Sprint 9). The three docs in this cluster own the operator-
and incident-responder facing surfaces: how the launcher reports a
clean boot, how a failed deploy is rolled back, and the
deterministic rule-engine that gates Policy Agent adjudications
before any probabilistic classifier runs.

- [observability.md](observability.md) — owns the log-severity
  taxonomy, the failure-fingerprint code set, and the evidence-JSON
  shape that lets an incident responder cross-reference a log line
  to a runbook entry. EA-4 / GOV-12 (Vikunja #25).
- [deployment-verification.md](deployment-verification.md) — owns
  the launcher activation-evidence contract, the manual rollback
  procedures, and the model-rollback path per ADR-012 §5.
  EA-4 / GOV-13 (Vikunja #26).
- [rule-engine.md](rule-engine.md) — owns the deterministic
  rule-set, the `ActionVerb` enum surface, and the ACL matrix /
  deny list that short-circuits before any probabilistic classifier
  runs (ADR-010 deterministic-before-LLM mandate). EA-4 / GOV-14
  (Vikunja #27).

### Fleet Hygiene

Out-of-plan addition during the Sprint 9 window. This single-member
cluster covers the multi-agent, multi-worktree fleet contract: how
roles cooperate, how the wake launcher chooses a worktree, how the
auto-stash drift pathology is contained, and how an interactive LA
session pauses the autonomous fleet before substantive git work.
Provenance: added by commit `a6ba981` (initial) and refactored to
agent-first ordering by commit `c2a2ca2` from a fleet-hygiene
maturation stream that ran in parallel with Sprint 9, not from the
Sprint 9 SDV §5.1 14-doc plan.

- [fleet-hygiene.md](fleet-hygiene.md) — owns the cross-role
  contract for wake-launcher worktree topology, fleet-pause SOP,
  branch-discipline rules, drift recovery, and the canonical
  Pattern A / Pattern B per-EA worktree decision. Out-of-plan
  (commits `a6ba981`..`c2a2ca2`).

## Audience Taxonomy Matrix

Each row records whether the named doc's `## Audience` section names
the persona as a primary or secondary reader. ✓ = named (primary or
secondary); — = not named. The matrix is constructed mechanically by
reading each doc's Audience section verbatim — it is not a re-judgement
of who *should* read the doc. Mapping rules for near-synonyms are in
the ledger Notes (e.g., "operator (LA)" in fleet-hygiene.md maps to
**Operator**).

| Doc | Operator | Developer | Auditor | Incident Responder | Future Agent |
|-----|----------|-----------|---------|--------------------|--------------|
| [STYLE.md](STYLE.md) | — | — | — | — | ✓ |
| [circuit-breaker.md](circuit-breaker.md) | — | ✓ | ✓ | ✓ | — |
| [configuration-management.md](configuration-management.md) | ✓ | ✓ | ✓ | ✓ | ✓ |
| [context-spotlighting.md](context-spotlighting.md) | — | ✓ | ✓ | ✓ | — |
| [deployment-verification.md](deployment-verification.md) | ✓ | — | — | ✓ | — |
| [error-recovery.md](error-recovery.md) | ✓ | ✓ | — | ✓ | — |
| [fleet-hygiene.md](fleet-hygiene.md) | ✓ | — | — | ✓ | ✓ |
| [gpu-runtime.md](gpu-runtime.md) | ✓ | ✓ | ✓ | — | — |
| [ipc-protocol.md](ipc-protocol.md) | — | ✓ | ✓ | — | — |
| [observability.md](observability.md) | — | ✓ | ✓ | ✓ | — |
| [pgov-validation.md](pgov-validation.md) | — | ✓ | ✓ | ✓ | — |
| [rule-engine.md](rule-engine.md) | — | ✓ | ✓ | — | — |
| [session-state.md](session-state.md) | — | ✓ | ✓ | ✓ | — |
| [streaming-output.md](streaming-output.md) | ✓ | ✓ | ✓ | — | — |

## Deferred Domains

Two governance domains from the Sprint 9 SDV §5.1 plan were
explicitly deferred at sprint kickoff because their substantive
content depends on a Pluton-capability investigation that has not
yet completed. Both are tracked in Vikunja and are blocked on the
same investigation ticket:

- **GOV-01 — Credential & Certificate Lifecycle Governance**
  (Vikunja [#14](http://localhost:3456/tasks/14)). Would document
  the mTLS certificate issuance flow, Pluton-sealed CA key handling,
  ephemeral per-boot certificate generation, JWT epoch propagation,
  and the certificate-compromise recovery runbook. Deferred because
  the design assumes Pluton-sealed CA keys, and the precise API
  surface available on Lunar Lake is unverified.
- **GOV-10 — Weight Integrity Verification Procedure**
  (Vikunja [#23](http://localhost:3456/tasks/23)). Would document
  the boot-time SHA-256 weight check against a Pluton-sealed
  manifest, the event-triggered runtime re-verification, the
  Known-Good Manifest provisioning ceremony, and the corruption-
  detection logging path. Deferred for the same Pluton dependency.

Common blocker: **ISS-4 — Investigate Pluton capabilities on Intel
Core Ultra 258V (Lunar Lake)**
(Vikunja [#101](http://localhost:3456/tasks/101)). Until ISS-4
delivers a findings doc covering the Windows TPM2.0 / Pluton SDK
surface, key-sealing feasibility, and attestation paths, both
GOV-01 and GOV-10 risk being authored against an architecture
assumption that does not match the hardware. Re-check ISS-4 status
before unblocking either ticket.

## Phantom and Forthcoming References

One forward-reference target appears in already-merged governance
docs (and in the Sprint 9 EA-4 docs' Open Questions sections) but
does not exist on disk. It is **listed without a resolving link**
to honor L-17.

- **boot-sequence.md** — referenced as "(forthcoming — see GOV-15)"
  by GOV-10 (#23), GOV-12 (#25), and the Sprint 7 prompt
  `docs/P5_TASK7_EA2_AO_SR_AUDIT_CORRECTION.xml`. Tracked as
  **GOV-15 — Author Boot Sequence Governance doc**
  (Vikunja [#124](http://localhost:3456/tasks/124)). Will cover
  the `BootState` enum + step progression in
  `services/policy_agent/src/boot.py`, the per-step failure modes,
  the `dev_mode` and `retry_delay_s` semantics, and the
  boot-failure logging paths. Pluton-dependent sections (sealed-CA
  init, sealed-manifest verification) are explicitly out of scope
  for GOV-15 and will land in GOV-01 / GOV-10 after ISS-4 closes.

## Pending Migrations

- **GOV-MIGRATE — `docs/TEST_GOVERNANCE.md` → `docs/governance/test.md`**
  (Vikunja [#123](http://localhost:3456/tasks/123)). Sprint 9
  established the lower-kebab-case `docs/governance/` convention
  but explicitly deferred migration of the pre-existing
  top-level `docs/TEST_GOVERNANCE.md` file to avoid breaking
  Sprint 8 (which references it from its signed SDV and from
  in-flight EA prompts). The migration unblocks once Sprint 8
  closes (Vikunja task #82 marked done). Migration scope: rename
  the file, update ~101 inbound references across 34 files
  (key active surfaces include `../../CLAUDE.md`,
  `../../.github/copilot-instructions.md`, several
  `../claude_projects/*.md` files, and the Sprint 9 governance
  docs themselves), then update this README to remove the legacy
  top-level path note.

## Style Authority

[STYLE.md](STYLE.md) is the style authority for every doc in this
directory. It defines:

- the **Doc Template** (Audience / Prerequisites / Source References
  / Governance Content / Recovery / Open Questions),
- the **Line-Count Floor** (≥ 150 substantive lines per domain doc),
- the **Source Anchoring** rules (path + section header preferred
  over fragile line ranges; ADR-absence handling guidance),
- the **Audience Taxonomy** (the five personas this index uses),
- the **Markdown Conventions** (header depths, code-fence language
  tags, bold-for-verdict convention),
- the **Filename Conventions** (lower-kebab-case, no
  `_GOVERNANCE` suffix), and
- the **Out of Scope** list (what does NOT belong in
  `docs/governance/`: e.g., personal-LA runbooks, ADR proposals,
  conversational design notes).

This README is a synthesis index, not a domain doc, and adapts the
template (Audience and inventory replace Source References /
Governance Content / Recovery) per STYLE.md §Doc Template's
allowance for index docs. It does not introduce new normative
governance content.

## Open Questions / Deferred Items

- **GOV-MIGRATE blocker.** The TEST_GOVERNANCE.md migration is
  blocked on Sprint 8 closure (Vikunja #82). Until Sprint 8's
  SCR is committed to main, this README must continue to note
  that test governance lives at the legacy top-level path
  `../TEST_GOVERNANCE.md`.
- **GOV-01 / GOV-10 unblock condition.** Both deferred Pluton
  domains depend on ISS-4 (Vikunja #101) producing
  `docs/PLUTON_CAPABILITY_FINDINGS.md`. Re-check ISS-4 status
  before scheduling either ticket.
- **GOV-15 Pluton-dependent sections.** Boot-sequence governance
  will be authored under GOV-15 (Vikunja #124) without the
  sealed-CA init / sealed-manifest verification sections; those
  remain owned by GOV-01 / GOV-10 once Pluton unblocks. Cross-doc
  authority boundary should be re-stated in the GOV-15 doc when
  authored.
- **fleet-hygiene.md cluster.** Authored out-of-sprint-plan
  during the Sprint 9 window. Sprint 9 SCR should record
  whether the cluster name "Fleet Hygiene" is the canonical
  long-term home for any future cross-role coordination doc, or
  whether the cluster should be folded once a peer doc lands.
- **Audience Taxonomy near-synonyms.** Two docs use near-synonym
  persona labels: `fleet-hygiene.md` says "operator (LA)" rather
  than bare "operator", and three docs name "future agent" only
  via a description ("Future agent guidance sits at the end of
  Governance Content" in `configuration-management.md`). The
  matrix maps these conservatively to **Operator** and
  **Future Agent** respectively; see ledger Notes for the
  mapping rule.

## Navigation

- Repo entry point: [`../../CLAUDE.md`](../../CLAUDE.md) — the
  cross-cutting project instructions, including the Vikunja MCP
  conventions, the Fleet-Pause SOP pointer, and the locked ADR /
  DEC list.
- Decision records: [`../adrs/`](../adrs/) — locked Architectural
  Decision Records (ADR-010 / ADR-011 / ADR-012 govern the GPU /
  NPU / model-loading boundaries cited throughout this directory).
- Operational runbooks: [`../runbooks/`](../runbooks/) — LA-facing
  recovery procedures and the
  [LA Operations Index](../runbooks/LA_OPERATIONS_INDEX.md) entry
  point that lands here on exceptional cases.
- Test governance (legacy path until GOV-MIGRATE):
  [`../TEST_GOVERNANCE.md`](../TEST_GOVERNANCE.md).
