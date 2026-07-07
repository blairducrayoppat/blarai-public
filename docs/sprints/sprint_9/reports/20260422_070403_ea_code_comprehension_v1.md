---
role: ea_code
phase: comprehension
revision: 1
tracking_task: 121
vikunja_comment: 226
posted_at: 2026-04-22T07:04:03-05:00
verdict: null
---

# [agent:ea_code][phase:comprehension] Sprint 9 EA-1 Security Boundary & Wire Protocol — Comprehension v1

## Wake Template Recitation

Session context per `docs/scheduled/wake_templates/ea_code.md` (scheduled wake launched by `tools/scheduled-tasks/wake_launcher.ps1 -Role ea_code`). Section headers of the wake template governing this firing, verbatim:

- **Role invocation** (EA Code; milestone executor; does NOT merge to main)
- **Protocol** (DEC-12 peer-review lattice; three-strike revision cap)
- **Your scope for this firing** (inspect `docs/scheduled/ea_queue/`; ignore `archive/` + `staging/`; STALE-QUEUE GUARD on gate mismatch)
- **State machine (DEC-12)** — Cases A / B / C / D / E / F
- **Formatting standard for Vikunja descriptions and disk reports (DEC-14.5)**
- **Report emission (DEC-13)** — disk copy + Fleet Reports task + commit + cross-reference
- **M5 Comprehension Gate content** — structural recitation required
- **Budget self-check** — 90 min session cap, TTG 2 h
- **Exit criteria** — Case A action posted → exit

**Allowed tools** per wake template Budget self-check: `mcp__vikunja__* Read Write Edit Bash mcp__git__*`. This comprehension firing uses only Read + Bash (git status/log + file inspection) + Vikunja MCP (read task, list comments, add comment, add_label, create_task, assign). No Edit or Write to production code occurs at comprehension phase (Case A).

**State machine classification for this firing**: **Case A — Fresh task**. No prior `[agent:ea_code][phase:comprehension]` comment exists on Task 121. Queue file `docs/scheduled/ea_queue/P5_TASK9_EA1_SECURITY_WIRE_PROTOCOL.xml` was moved from staging → queue at commit `d52e5a1` (SDO, 2026-04-22T05:32:59-05:00) following Co-Lead `VERDICT: APPROVED` at comment #216.

**Gate-label note (L-13 adjacent)**: Task 121 currently carries `Gate:Approved` (id 12) and `Gate:Pending-Human` (id 11) but not `Gate:Pending-Execution`. Per SDO comment #221 the EA Code pickup signal is file presence in `queue/`, not a `Gate:Pending-Execution` label transition; `Gate:Pending-Execution` does not exist as a server label per CLAUDE.md's verified 2026-04-20 `list_labels` snapshot. I treat this as a protocol convention (SDO authoritative) and proceed with Case A. On posting this comprehension gate I apply `Gate:Pending-SDO` (id 9) and remove `Gate:Approved` (id 12) — since `Gate:Approved` was applied by Co-Lead for Phase 1b staged-prompt review, it no longer reflects current state once I post a new pending comprehension.

## Parent Head Verify (L-13)

- Current branch: `feature/p5-task8-ea1-policy-agent-hardening`
- Current HEAD: `d52e5a1` (SDO queue-move commit, doc-only delta)
- `main` tip: `ced672d` ([agent:co_lead] report: completion for Task 121 Sprint 9 continuation XML)
- Sprint 8 EA-1 (commit `2195d8e` per SDV §2.2) has NOT yet merged to main at this firing time; that's a separate Sprint 8 concern.

The execution branch for Sprint 9 EA-1 is `feature/p5-task9-ea1-security-wire-protocol`. Per the EA prompt's §1 Parent Head stanza: I will not branch now. Branching happens at Case C (post-approval execution), at which point I will run `git fetch origin && git checkout main && git pull --ff-only && git rev-parse HEAD` and branch from whatever main HEAD is at that moment — not from the XML's authoring-time `6d18743` or from today's `ced672d` if main has advanced by then. For this comprehension firing my work (Vikunja comment + DEC-13 disk report commit) stays on the inherited Sprint 8 branch — consistent with SDO's queue-move commit having landed on the same branch.

## EA Prompt Recitation

### A. MILESTONE OBJECTIVE (own words, 3-5 sentences)

Sprint 9 EA-1 authors the first four deliverables of the BlarAI governance documentation corpus under `docs/governance/`: a meta-artifact style guide `STYLE.md` (≤ 120 lines, authored FIRST per L-18) plus three HIGH-severity governance documents — `pgov-validation.md` (GOV-04 / Vikunja #17), `ipc-protocol.md` (GOV-02 / Vikunja #15), and `streaming-output.md` (GOV-03 / Vikunja #16). `STYLE.md` establishes the doc template, section conventions, 150-line floor, and source-anchoring requirement that EA-2, EA-3, EA-4, and EA-5 will inherit as required attachments. The three governance docs consolidate the security-boundary and wire-protocol knowledge currently scattered across production source code (`services/assistant_orchestrator/src/pgov.py`, `services/ui_gateway/src/transport.py`, `services/ui_shell/src/streaming.py`, `shared/schemas/car.py`) into auditor-accessible references, each ≥ 150 lines with ADR and source-file anchoring. The ledger entry (WI-5) closes the EA with the next-free `### Entry N` (SDO projected 56 but current tail is Entry 51 for Sprint 8 EA-1, so next free is 52 — EA verifies at commit time). Ordering constraint: `STYLE.md` MUST be committed (separate commit acceptable) before any of the three docs begin authoring.

### B. WORK ITEMS (one sentence each)

- **WI-1 — Author `docs/governance/STYLE.md`** (authored FIRST per L-18; ≤ 120 lines capped): cross-EA coordination artifact defining doc template, 150-line floor, source-anchoring convention, audience taxonomy, markdown conventions, filename conventions, and out-of-scope boundaries for `docs/governance/**`.
- **WI-2 — Author `docs/governance/pgov-validation.md`** (GOV-04 / Vikunja #17; ≥ 150 lines): six-stage PGOV pipeline (token budget → PII/secret → delimiter echo → tool-call allowlist → retrieval leakage 0.85 cosine → final gate) with embedding-model citation (`bge-small-en-v1.5` ONNX CPU), fail-closed semantics, fallback-message exact text, circuit-breaker interaction, audit-trail governance, and threshold-tuning governance.
- **WI-3 — Author `docs/governance/ipc-protocol.md`** (GOV-02 / Vikunja #15; ≥ 150 lines): CAR schema; serialization; `StreamToken` including `is_thinking`; mTLS + JWT + CAR-hash envelope; vsock `AF_HYPERV` wire protocol with CID/port constants; ordering/backpressure/flow-control semantics (state "none" explicitly where absent); nonce replay; epoch validation; example happy-path + denial cycles; timeout behavior.
- **WI-4 — Author `docs/governance/streaming-output.md`** (GOV-03 / Vikunja #16; ≥ 150 lines): `StreamToken` field semantics; streaming lifecycle (first → mid → final → EOS); TUI receive-and-buffer; PGOV handoff timing; TUI thinking-token rendering per ADR-012 §2.4; `StreamingDisplay` state machine; backpressure; circuit-breaker mid-stream termination; mid-generation crash recovery (forward-reference GOV-06 acceptable).
- **WI-5 — Add Sprint 9 EA-1 entry to `docs/POST_OPERATIONAL_MATURATION_LEDGER.md`**: new `### Entry N` (N = highest existing + 1; SDO projection 56 but current tail is 51 so N = 52, EA re-verifies at commit time) summarizing the four deliverables with line counts, STYLE.md-first acknowledgment, source-anchoring summary, parallel-with-Sprint-8 note, and pytest regression-baseline confirmation.

### C. FILES TO CREATE

- `docs/governance/STYLE.md` (≤ 120 lines; WI-1; committed FIRST)
- `docs/governance/pgov-validation.md` (≥ 150 lines; WI-2)
- `docs/governance/ipc-protocol.md` (≥ 150 lines; WI-3)
- `docs/governance/streaming-output.md` (≥ 150 lines; WI-4)

Sub-artifact: the `Audience` stanza opening each of the three governance docs (canonical section headers prescribed in STYLE.md's Doc Template). Ledger entry `### Entry 52 — Task 9 / EA-1: Sprint 9 Governance Documentation — Security Boundary & Wire Protocol` appended to the existing file.

### D. FILES TO MODIFY

- `docs/POST_OPERATIONAL_MATURATION_LEDGER.md` (WI-5: append one new `### Entry N` section)

No other files. Not `pyproject.toml`, not `conftest.py`, not any ADR, not `docs/TEST_GOVERNANCE.md`, not any file under `services/**/src/`, `shared/**`, `launcher/**`, or `**/tests/`.

### E. FILES TO READ (per-doc anchoring list)

**WI-2 (pgov-validation.md) — required:**
- `services/assistant_orchestrator/src/pgov.py` (full file — six pipeline stages, regex patterns, 0.85 cosine threshold, fail-closed path, fallback message)
- `Use Cases_FINAL.md` (Red Team ISSUE-005 framing)
- ADR-012 §2.4 (thinking-mode strategy; PGOV interaction)

**WI-2 — recommended supporting:**
- `docs/SECURITY_ASSESSMENT.md` (PGOV findings)

**WI-3 (ipc-protocol.md) — required:**
- `shared/schemas/car.py` (CAR dataclass fields + types)
- `services/ui_gateway/src/transport.py` (StreamToken + transport)
- One ADR that governs IPC — closest candidates: ADR-010 (PA GPU allocation, uses CAR) or ADR-011 (all LLM on GPU). If no ADR directly governs IPC I will state so explicitly and cite the closest.

**WI-3 — recommended supporting:**
- `shared/ipc/protocol.py` (protocol implementation)
- `shared/ipc/vsock.py` (vsock transport, AF_HYPERV, CID/port constants)
- `services/policy_agent/src/ipc.py` (PA listener; CAR + JWT verification site)

**WI-4 (streaming-output.md) — required:**
- `services/ui_shell/src/streaming.py` (StreamingDisplay + buffer state machine)
- `services/assistant_orchestrator/src/pgov.py` (PGOV stages involved in streaming handoff)
- ADR-012 §2.4 (thinking-mode strategy — PGOV `/no_think`; AO thinking-allowed-with-strip)

**WI-4 — recommended supporting:**
- `services/ui_gateway/src/transport.py` (StreamToken)
- Task 5 M3 is_thinking ledger entry or commit hash (transport-field addition)

**Shared context reads (for all WIs):**
- `docs/sprints/sprint_9/strategic_design_vision.md` §§5.1, 5.3, 6, 11 (read)
- `docs/P5_TASK9_SDO_CONTINUATION_v1.0.xml` `<ea_decomposition>` EA-1 block (read lines 274-298)
- Vikunja Task 17 (GOV-04), Task 15 (GOV-02), Task 16 (GOV-03) descriptions — to be fetched at execution time
- `docs/POST_OPERATIONAL_MATURATION_LEDGER.md` last 5-8 entries (for WI-5 entry numbering: current highest is **Entry 51** at line 3367)
- `docs/adrs/ADR-010-PA-Device-Allocation-GPU-Classification.md`, `ADR-011-All-LLM-Inference-GPU-NPU-Retirement.md`, `ADR-012-Qwen3-14B-Model-Selection-Speculative-Decoding.md` (ADR content)

### F. DELIVERABLE STRUCTURE (verbatim from EA prompt SECTION 5)

**Branch**: `feature/p5-task9-ea1-security-wire-protocol`

**Files to create** (verbatim):
```
- docs/governance/STYLE.md                   (≤ 120 lines, authored FIRST)
- docs/governance/pgov-validation.md         (≥ 150 lines)
- docs/governance/ipc-protocol.md            (≥ 150 lines)
- docs/governance/streaming-output.md        (≥ 150 lines)
```

**Files to modify** (verbatim):
```
- docs/POST_OPERATIONAL_MATURATION_LEDGER.md (one new ### Entry N section)
```

**Section structure per governance doc** (verbatim from EA prompt — STYLE.md's Doc Template):
```
# {Domain Name} Governance
## Audience
## Prerequisites
## Source References
## Governance Content
## Recovery / Remediation Procedures (if applicable — omit-or-merge per STYLE.md)
## Open Questions / Deferred Items
```

**Commit-message format** (from EA prompt SECTION 9, main EA commit):
```
docs(task9/ea1): security + wire-protocol governance — 4 new docs (incl. STYLE.md), {L} lines total
```
Optional intermediate STYLE.md-only commit:
```
docs(task9/ea1): governance STYLE.md — ≤120-line cross-EA coordination artifact (L-18)
```

**Ledger entry line** (verbatim header, WI-5): `### Entry N — Task 9 / EA-1: Sprint 9 Governance Documentation — Security Boundary & Wire Protocol` (N = 52 per current ledger tail; EA re-verifies at commit).

### G. ORACLE EXPECTATION (verbatim from EA prompt SECTION 7 gate ORACLE)

Command:
```
git diff main...HEAD --name-only | grep -vE "^docs/governance/|^docs/POST_OPERATIONAL_MATURATION_LEDGER\.md$"
```
Expected output: **EMPTY (zero lines).**

Expected `git diff main...HEAD --name-only` output set (exactly these five paths; no others):
```
docs/governance/STYLE.md
docs/governance/ipc-protocol.md
docs/governance/pgov-validation.md
docs/governance/streaming-output.md
docs/POST_OPERATIONAL_MATURATION_LEDGER.md
```

If ANY other file appears, STOP, post completion with the ORACLE failure, and await SDO guidance. Do NOT attempt auto-fixes.

### H. STYLE.md-FIRST ACKNOWLEDGMENT (L-18 verbatim)

Quoting L-18 from the EA prompt header block (XML lines 27-30):

> "IMPORTANT (L-18): This EA has a meta-artifact duty beyond its three governance docs: docs/governance/STYLE.md MUST be authored FIRST, before pgov-validation.md, ipc-protocol.md, or streaming-output.md. STYLE.md becomes a required attachment for EA-2, EA-3, EA-4, and EA-5. Getting it right is prerequisite to Sprint 9 coherence."

And L-18(c) from the negative-constraints block (XML lines 469-473):

> "STYLE.md is for cross-EA coordination, not a public-facing contributor guide. Keep STYLE.md ≤ 120 lines. It is authored FIRST, committed (optionally as its own commit) before the three governance docs begin."

**I confirm**: `docs/governance/STYLE.md` is authored and committed BEFORE I begin `pgov-validation.md`, `ipc-protocol.md`, or `streaming-output.md`. I will use the optional intermediate commit pattern (per WI-1 `<commit_checkpoint>`) so that STYLE.md is on the branch as its own commit before WI-2 begins.

### I. CROSS-SPRINT COEXISTENCE ACKNOWLEDGMENT (L-16 verbatim)

Verbatim recitation as required by the EA prompt Section 2 comprehension gate instruction I:

> "Sprint 9 writes docs/governance/. Sprint 8 writes **/tests/. My writes respect this boundary."

Supplementary context from the EA prompt header block (L-16, XML lines 20-25):

> "Sprint 9 runs in parallel with Sprint 8 per DEC-15 multi-sprint execution (commit 20db5e7). Working-set boundaries are hard: Sprint 8 writes **/tests/ (plus conftest.py, pyproject.toml, ledger); Sprint 9 writes docs/governance/** (plus ledger and IMPLEMENTATION_PLAN.md at EA-5). If your branch diff shows ANY file outside docs/ (or outside docs/governance/ after the first commit), the ORACLE gate fails and you MUST halt."

### J. SOURCE-ANCHORING RECITATION (per SDV §6 / success criterion 6)

**pgov-validation.md (GOV-04 / Vikunja Task #17):**
- ADR to cite: **ADR-012 §2.4** (thinking-mode strategy; PGOV interaction with AO streaming)
- Required source-anchor file: **`services/assistant_orchestrator/src/pgov.py`** (full six-stage pipeline)
- Additional anchor: `Use Cases_FINAL.md` Red Team ISSUE-005

**ipc-protocol.md (GOV-02 / Vikunja Task #15):**
- ADR to cite: **ADR-010** (PA GPU device allocation — CAR usage context) or explicit statement that no ADR directly governs IPC (with closest-relevant cited); SDV §10 "ADR alignment" confirms ADR-010 is among the most frequently cross-referenced
- Required source-anchor file: **`shared/schemas/car.py`** (CAR dataclass)
- Additional anchors: `services/ui_gateway/src/transport.py`, `shared/ipc/protocol.py`, `shared/ipc/vsock.py`, `services/policy_agent/src/ipc.py`

**streaming-output.md (GOV-03 / Vikunja Task #16):**
- ADR to cite: **ADR-012 §2.4** (thinking-mode strategy — PGOV `/no_think`; AO thinking allowed with strip)
- Required source-anchor file: **`services/ui_shell/src/streaming.py`** (StreamingDisplay + buffer state machine)
- Additional anchors: `services/assistant_orchestrator/src/pgov.py` (PGOV handoff stages), `services/ui_gateway/src/transport.py` (StreamToken transport)

`STYLE.md` does NOT require source anchoring — it is a meta-artifact (explicit per XML comprehension-gate stanza J).

### K. TARGET-AUDIENCE ASSIGNMENT (SDV §5.3)

- **pgov-validation.md** — primary: **auditor**; secondary: developer; tertiary: incident responder. Rationale: PGOV governs the fail-closed output surface; the audience most needing this doc is the one confirming security invariants, with developer (pgov.py maintainers) and incident-responder (user-reports "output suppressed") as secondary tiers.
- **ipc-protocol.md** — primary: **developer**; secondary: auditor. Rationale: CAR + vsock + JWT wire details are developer-first (service authors adding new message types), with auditor secondary (confirming replay/epoch/signature invariants).
- **streaming-output.md** — primary: **developer**; secondary: operator (TUI behavior); tertiary: auditor (PGOV handoff). Rationale: streaming is the cross-service integration point between AO token generation, PGOV validation, gateway transport, and TUI render; developer first, but operator matters for TUI behavior and auditor for the PGOV gate.

None of the three docs serves all five audiences (per STYLE.md §Audience Taxonomy per WI-1's `<required_sections>`).

### L. 150-LINE FLOOR ACKNOWLEDGMENT (SDV §5.3 / §6)

The three governance docs (pgov-validation.md, ipc-protocol.md, streaming-output.md) are EACH ≥ 150 lines of substantive content, not counting YAML frontmatter or the H1 title line alone. `STYLE.md` is CAPPED at ≤ 120 lines per L-18(c). Target verification at WI-4 completion via:

```
wc -l docs/governance/*.md
```

Expected floor/ceiling:
- `STYLE.md` ∈ [30, 120]
- `pgov-validation.md` ≥ 150
- `ipc-protocol.md` ≥ 150
- `streaming-output.md` ≥ 150

Per EA prompt `<mature_not_minimal>` block: a doc coming in under 150 lines with ALL `required_coverage` items addressed is a reviewable position (explicit deficit justification in completion comment), not an automatic failure — but the intent is substantive coverage, not a word-count hack.

### M. RISKS AND AMBIGUITIES

1. **Parallel-with-Sprint-8 context**: the inherited branch (`feature/p5-task8-ea1-policy-agent-hardening`) belongs to Sprint 8 and its merge to main is pending (Sprint 8 EA-1 awaits LA merge decision per Co-Lead escalation #211). My Case A disk-report commit lands on this branch — consistent with SDO's `d52e5a1` having landed there. No Sprint 9 scope leakage since I write only `docs/sprints/sprint_9/reports/*.md` + this comprehension comment. At Case C (execution) I will follow the EA prompt's Parent Head stanza: `git fetch && git checkout main && git pull --ff-only` then branch `feature/p5-task9-ea1-security-wire-protocol` from current main HEAD.

2. **Ledger entry number drift vs. SDO projection**: SDO projected Entry 56 but the ledger tail at this firing is Entry 51 (Task 8/EA-1). SDO's projection assumed Sprint 8 would consume entries 51-55 before Sprint 9 EA-1 committed; only Entry 51 has been consumed so far. I will use the EA prompt's "next-free" protocol: at commit time I scan `grep -n "^### Entry " docs/POST_OPERATIONAL_MATURATION_LEDGER.md | tail -1`, take N+1, and use that. Projected actual at this moment: Entry 52. Sprint 8 may advance by the time I reach Case C — I re-verify then.

3. **Source-file shift since GOV ticket authoring (2026-04-18)**: SDV §9.2 known-unknown #3 flags this. I will validate at execution time that each cited source file still exists at the path declared in the GOV ticket "Scattered Sources" list. If a file has been renamed or deleted, I cite the gap explicitly, do not fabricate, and open a Vikunja finding ticket per SDV §5.2 item 5 / §9.1 mitigation.

4. **ADR-for-IPC direct-governance ambiguity**: WI-3 anchor specification allows ADR-010 or an explicit statement that no ADR directly governs IPC. ADR-010 (PA GPU allocation) mentions CAR usage in context but does not LOCK the CAR schema. ADR-011 and ADR-012 also touch adjacent surfaces. I resolve at execution time by reading each ADR's abstract; if none directly governs IPC wire protocol I state so explicitly in `ipc-protocol.md` §Prerequisites and cite the closest-relevant ADR (ADR-010 at minimum, since the CAR surface is central to PA's GPU allocation scope).

5. **`boot-sequence.md` phantom reference (L-17)**: the EA prompt flags this as "informational for EA-1" but binding for EA-2/EA-4. I will not forward-reference `docs/governance/boot-sequence.md` in any of the four authored files. If a source file references a "boot sequence governance doc," I cite the source file directly and footnote the gap. GOV-15 (Vikunja #124) is the follow-up ticket for this phantom.

6. **Gate-label protocol ambiguity noted above**: `Gate:Pending-Execution` does not exist as a server label, so my wake template's STALE-QUEUE GUARD step would trigger on a strict literal reading. SDO comment #221 resolves: pickup signal is file presence in `queue/`. I apply `Gate:Pending-SDO` + remove `Gate:Approved` on posting this comprehension; SDO will validate this interpretation on its next cadence.

No blocking ambiguity; all risks addressable at execution time.

### N. PRODUCTION FILE PROHIBITION ACKNOWLEDGMENT (L-15 verbatim)

Quoting L-15 from the EA prompt `<negative_constraints>` block (XML lines 440-453):

> "NO file write outside docs/governance/ and docs/POST_OPERATIONAL_MATURATION_LEDGER.md. Specifically PROHIBITED file paths for Sprint 9 EA-1: `**/tests/*` (Sprint 8 territory), `shared/**` (production code), `services/*/src/**` (production code), `launcher/**` (production code), `pyproject.toml`, `conftest.py` (anywhere in the tree), `docs/TEST_GOVERNANCE.md` (deferred to GOV-MIGRATE / Vikunja #123), Any ADR file (docs reference ADRs; they do NOT modify them). If the diff shows any file in the above list, the ORACLE gate fails and the EA MUST halt and escalate to SDO via Task 121 comment before attempting fixes."

And L-15 from the prompt header block (XML lines 14-18):

> "IMPORTANT (L-15): This is a PURE DOCUMENTATION milestone. DO NOT modify any file outside docs/governance/ (plus the ledger entry for this EA). If a source-anchoring citation reveals a production-code discrepancy, STOP, document it in your completion report, and wait for SDO direction. Do NOT fix production code here."

**I confirm**: Sprint 9 EA-1 writes ONLY to `docs/governance/**` (STYLE.md, pgov-validation.md, ipc-protocol.md, streaming-output.md) and `docs/POST_OPERATIONAL_MATURATION_LEDGER.md` (Entry 52). If during source-file reading I discover a production-code discrepancy (e.g., the 0.85 cosine threshold in `pgov.py` contradicts what the doc should state), I will halt, record the finding in the EA-1 completion comment, open a Vikunja ticket, and wait for SDO direction — I will NOT modify `pgov.py` or any other production file.

## Negative Constraints Recitation (EA prompt SECTION 6)

- **L-15** (production-code prohibition) — recited above in N verbatim.
- **L-16** (cross-sprint working-set boundary) — Sprint 9 writes ONLY `docs/governance/**` + ledger. If I discover a test that would benefit from addition, I do NOT add it (Sprint 8 territory); I document the observation in the WI-5 ledger entry and move on.
- **L-17** (phantom-reference warning) — `docs/governance/boot-sequence.md` does NOT exist and MUST NOT be authored in EA-1. Cite source files directly; footnote the gap.
- **L-18** (STYLE.md first, ≤ 120 lines) — recited above in H verbatim.
- **SDV §5.2 Pluton-blocked content** — do NOT author `docs/governance/credentials-lifecycle.md` (GOV-01) or `docs/governance/weight-integrity.md` (GOV-10). Blocked on ISS-4.
- **DEC-15 §5.3 parallel-sprint coexistence** — governance docs are timeless references to production code state, not sprint-execution logs. MUST NOT reference Sprint 8 branches, test files, or commit hashes in the governance docs. Ledger entry (WI-5) MAY mention the parallel-with-Sprint-8 context because the ledger IS a sprint-execution log.
- **Per-WI constraints** (summary): WI-1 no example governance-doc content inside STYLE.md; WI-2 no threshold-change prescription; WI-3 no schema changes / no fabricated code examples; WI-4 no future-TUI speculation / no GOV-06 inline.

## Acceptance Checks Recitation (EA prompt SECTION 7 quality_gate — verbatim gate IDs)

1. **MARKDOWN-LINT** — exactly one H1 per doc; H2 ordering matches STYLE.md Doc Template (WI-2/3/4 only); closed fenced blocks; no broken relative links. Command: `grep -E "^# " docs/governance/*.md`.
2. **SOURCE-ANCHOR-CHECK** — each of WI-2/WI-3/WI-4 cites ≥ 1 ADR (by ADR number) and ≥ 1 source file from its GOV ticket's Scattered Sources list. Commands: `grep -E "ADR-[0-9]+" docs/governance/{pgov-validation,ipc-protocol,streaming-output}.md` and `grep -E "services/|shared/" docs/governance/{pgov-validation,ipc-protocol,streaming-output}.md`.
3. **LINE-FLOOR** — STYLE.md ∈ [30, 120]; other three each ≥ 150. Command: `wc -l docs/governance/*.md`.
4. **ORACLE** — recited above in G verbatim. Empty output expected.
5. **REGRESSION-SAFETY-NET** — `.venv/Scripts/pytest shared/ services/ launcher/ --tb=short -q` ≥ 755 passed, 2 skipped (or 777/2 if Sprint 8 EA-1 has merged to main by then). Observed count reported verbatim.

## Plan of Work (cross-referenced to WI)

**Pre-execution (when Case C fires after SDO approval):**
- Run budget self-check: `tools.autonomy_budget.self_check.run(role="ea_code", task_id=121)` — confirm 90-min cap + no active lift.
- `git fetch origin && git checkout main && git pull --ff-only && git rev-parse HEAD` — record main HEAD as branching anchor.
- `git checkout -b feature/p5-task9-ea1-security-wire-protocol` — create Sprint 9 EA-1 branch.
- Re-read `docs/P5_TASK9_SDO_CONTINUATION_v1.0.xml` `<ea_decomposition>` EA-1 block and SDV §§5.1/5.3/6.

**WI-1 (STYLE.md) — FIRST per L-18:**
1. Create `docs/governance/` directory if absent.
2. Author `docs/governance/STYLE.md` with verbatim section headers per WI-1 `<required_sections>`: Purpose and Scope, Doc Template, Line-Count Floor, Source Anchoring, Audience Taxonomy, Markdown Conventions, Cross-Doc References, Filename Conventions, Out of Scope.
3. Verify `wc -l docs/governance/STYLE.md` ≤ 120.
4. Intermediate commit: `docs(task9/ea1): governance STYLE.md — ≤120-line cross-EA coordination artifact (L-18)`.

**WI-2 (pgov-validation.md) — after WI-1 commit:**
1. Read `services/assistant_orchestrator/src/pgov.py` end-to-end; identify line ranges for each of the six pipeline stages + fail-closed path + fallback message + regex patterns + 0.85 threshold site.
2. Read `Use Cases_FINAL.md` Red Team ISSUE-005 and `docs/SECURITY_ASSESSMENT.md` PGOV sections.
3. Confirm ADR-012 §2.4 thinking-mode strategy text.
4. Author `docs/governance/pgov-validation.md` per STYLE.md Doc Template: `# PGOV Validation Governance` / `## Audience` (auditor primary) / `## Prerequisites` (ADR-012 §2.4; peer: ipc-protocol.md) / `## Source References` (pgov.py line ranges) / `## Governance Content` (six stages, embedding model, fail-closed semantics, fallback message text, circuit-breaker interaction, audit trail, threshold-tuning governance, user-visible suppression behavior) / `## Recovery / Remediation Procedures` (threshold-change evidence + audit trail) / `## Open Questions / Deferred Items`.
5. Verify `wc -l` ≥ 150, `grep -E "ADR-[0-9]+"` ≥ 1 match, `grep -E "services/"` ≥ 1 match.

**WI-3 (ipc-protocol.md) — after WI-2:**
1. Read `shared/schemas/car.py` (CAR dataclass fields + validation rules).
2. Read `services/ui_gateway/src/transport.py` (StreamToken; include `is_thinking` transport-layer field).
3. Read `shared/ipc/protocol.py`, `shared/ipc/vsock.py` (AF_HYPERV, CID + port constants), `services/policy_agent/src/ipc.py` (PA listener; JWT-to-CAR hash verification site).
4. Identify governing ADR: inspect ADR-010 / ADR-011 / ADR-012 abstracts; if none directly governs IPC, state so explicitly and cite closest-relevant.
5. Author `docs/governance/ipc-protocol.md` per STYLE.md Doc Template: Audience (developer primary; auditor secondary) / Prerequisites / Source References / Governance Content (CAR schema, serialization, StreamToken including `is_thinking`, mTLS+JWT+CAR-hash envelope, vsock wire protocol, ordering/backpressure/flow-control — state "none" explicitly where absent, error response, JWT-to-CAR verification, nonce replay, epoch validation, example happy-path + denial cycles, timeout behavior) / Recovery (omit-or-merge per STYLE.md — likely merged into Governance Content for this auditor-adjacent doc) / Open Questions.
6. Verify gate commands as for WI-2.

**WI-4 (streaming-output.md) — after WI-3:**
1. Read `services/ui_shell/src/streaming.py` (StreamingDisplay buffer + state machine).
2. Read `services/assistant_orchestrator/src/pgov.py` stages involved in streaming handoff.
3. Re-read `services/ui_gateway/src/transport.py` StreamToken fields.
4. Cite ADR-012 §2.4 thinking-mode strategy.
5. Author `docs/governance/streaming-output.md` per STYLE.md Doc Template: Audience (developer primary; operator TUI behavior; auditor PGOV handoff) / Prerequisites (ADR-012 §2.4; peers: pgov-validation.md, ipc-protocol.md) / Source References / Governance Content (StreamToken field semantics including `is_thinking`, streaming lifecycle, TUI receive-and-buffer, PGOV handoff timing, thinking-token display rendering, StreamingDisplay state machine, backpressure, circuit-breaker mid-stream termination, mid-generation crash recovery with forward-reference to GOV-06 as placeholder) / Recovery (crash recovery) / Open Questions.
6. Verify gate commands as for WI-2/WI-3.

**WI-5 (ledger) — final commit:**
1. Re-scan `grep -n "^### Entry " docs/POST_OPERATIONAL_MATURATION_LEDGER.md | tail -1` — take N+1.
2. Append `### Entry N — Task 9 / EA-1: Sprint 9 Governance Documentation — Security Boundary & Wire Protocol` with body per WI-5 `<required_content>` (deliverables + line counts + STYLE.md-first protocol acknowledgment + source-anchoring summary + parallel-with-Sprint-8 note + pytest baseline confirmation with exact count).

**Pre-commit acceptance-check sequence:**
1. MARKDOWN-LINT: `grep -E "^# " docs/governance/*.md` → exactly 4 H1 lines.
2. SOURCE-ANCHOR-CHECK: three greps per spec.
3. LINE-FLOOR: `wc -l docs/governance/*.md`.
4. ORACLE: `git diff main...HEAD --name-only | grep -vE "^docs/governance/|^docs/POST_OPERATIONAL_MATURATION_LEDGER\.md$"` → empty.
5. REGRESSION-SAFETY-NET: `.venv/Scripts/pytest shared/ services/ launcher/ --tb=short -q` → record exact pass/skip count.
6. Final commit with EA prompt SECTION 9 template.

**Completion comment (Case C exit):**
- `[agent:ea_code][phase:completion]` on Task 121 with commit hash, `git log --oneline main..HEAD`, `git diff main...HEAD --name-only`, `wc -l` output, pytest summary first/last lines, per-doc synopsis + anchor confirmation, ORACLE PASS/FAIL.
- Apply `Gate:Pending-SDO` (id 9); remove prior completion-phase labels.
- Emit DEC-13 completion report (disk + Fleet Reports task assigned to blarai + commit + source-comment trailer).

## STOP

Per the comprehension_gate `<instruction>`: "STOP after posting the comprehension gate. Do NOT proceed to implementation. Wait for SDO VERDICT: APPROVED on Vikunja Task 121 before starting any work."

I am stopping now. Next EA Code firing will be a no-op (Case B) until SDO posts `[agent:sdo][phase:comprehension-review]` with `VERDICT: APPROVED` (→ Case C execution) or `REJECTED` / `ADJUST` (→ revised comprehension).
