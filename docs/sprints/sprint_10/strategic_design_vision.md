---
# Strategic Design Vision (SDV) — BlarAI Sprint 10
#
# Authored interactively by Co-Lead Architect + Lead Architect at sprint start.
# Baseline against which the end-of-sprint SCR (Strategic Completion Report) and
# SWAGR (Strategic Work Analysis & Gap Report) measure success and gap.
---
sprint_id: 10
sprint_name: "Doctrine Split"
predecessor_sprint_id: 9
vikunja_tracking_task_id: 369
start_date: "2026-05-09"
target_completion_date: "open — no hard deadline per LA mature-not-minimal motto"
la_approved_on: "2026-05-09T15:00:31-05:00"
la_approved_by: "blarai"
co_lead_drafted_on: "2026-05-09T14:25:16-05:00"
co_lead_commit_when_drafted: "647b52d"
sdv_version: 1
---

# Strategic Design Vision — Sprint 10: Doctrine Split

## 1. Executive brief

Sprint 10 finalizes Platform Separation v2 by performing the doctrine splits
deferred at the Stage 6 FINAL close one day before this sprint kicks off (revives
v1 work items 6.1, 6.2, 6.3, and 6.6). The three BlarAI doctrine files
(`CLAUDE.md`, `.github/copilot-instructions.md`, `AGENTS.md` — 572 lines total)
currently mix BlarAI runtime/architecture context with devplatform
fleet/agent-operating-model doctrine. Sprint 10 partitions this content: BlarAI
keeps runtime, architecture, security, ADR (Architecture Decision Record),
and Use Case context; devplatform receives the SDO (Strategic Development
Orchestrator), EA (Execution Agent), Co-Lead, Sprint Auditor, fleet-pause,
DEC-11/12/13/14.5/15 (Decision records), and sprint-lifecycle doctrine, authored
into `devplatform/CLAUDE.md`, `devplatform/AGENTS.md`, and
`devplatform/.github/copilot-instructions.md` — three destination shells that do
not yet exist. The fleet-pause SOP (Standard Operating Procedure) block's
`from tools.autonomy_budget import state` import is fixed for cross-repo
portability as part of the move. Done = both repos hold coherent single-concern
doctrine; cross-references resolve in both directions; BlarAI's §"Active State"
section is current (closing the 2-sprint-stale finding from Sprint 8 + Sprint 9
SWAGRs); Stage 6 v1 items 6.1/6.2/6.3/6.6 are recorded CLOSED.

Sprint 10 runs **serial** — predecessor Sprint 9 closed 2026-04-24, the active
task roster (`docs/active_tasks.yaml`) is empty, and the next devplatform sprint
("cf-1 — DevPlatform Cloud-Fleet Redesign — Foundation", Vikunja task #368) is
chartered but dormant per LA confirmation 2026-05-09. cf-1 will not begin until
Sprint 10 closes; this is by design — cf-1 is going to redesign the fleet, and
the redesign needs a coherent doctrine destination to author into. Sprint 10
builds that destination.

The guiding principle is **mature not minimal** per LA standing direction. The
split is structural, but each post-split file is expected to be a coherent
operational reference in its own right — not a thin pointer-with-a-couple-of-
sentences. devplatform's three destination files are authored to be readable
standalone by a future cf-1 EA or by a Codex / Cowork sandbox agent that has
never seen the BlarAI runtime context.

## 2. Context

### 2.1 Predecessor sprint outcome

- **Predecessor SCR**: [docs/sprints/sprint_9/strategic_completion_report.md](../sprint_9/strategic_completion_report.md)
- **Predecessor SWAGR**: [docs/sprints/sprint_9/Strategic_Work_Analysis_and_Gap_Report_Sprint_9_20260424_053153.md](../sprint_9/Strategic_Work_Analysis_and_Gap_Report_Sprint_9_20260424_053153.md)

Sprint 9 ("Governance Documentation") delivered all 12 in-scope GOV
(Governance) ticket docs plus the `STYLE.md` and `README.md` synthesis (~3,925
lines of content) across 5 sequential EA milestones, all auto-merged under
`trusted_scope`. Sprint 9 SCR claimed criterion #3 FAIL on GOV-ticket closure
but the Sprint 9 SWAGR independently verified all 12 GOV tickets in fact have
`done=true` — fact-check error in the SCR, not a real failure. Sprint 9's
verdict: PARTIAL_ALIGNMENT, 0 CRITICAL / 2 MAJOR / 5 MINOR gaps.

The Sprint 9 SWAGR's explicit Sprint 10 recommendation was "advance one Use
Case (ISS-3 PA stop-token fix or UC-005 Code Agent's opening milestone)." The
LA's chosen direction (doctrine split via the deferred Stage 6 items) is a
deliberate prioritization away from that recommendation. Justification:
Platform Separation v2 was declared procedurally COMPLETE yesterday but its
doctrine deliverables (6.1/6.2/6.3/6.6) remained deferred; the next devplatform
sprint (cf-1) will redesign the fleet and explicitly needs a clean doctrine
substrate. Sprint 10 closes this loop before cf-1 begins, which is a
sequencing-driven priority that the SWAGR's UC-advancement recommendation
could not see (the SWAGR audited Sprint 9's content, not the Stage 6 close
report which arrived two weeks later).

Sprint 8 + Sprint 9 SWAGRs both flagged carry-over gaps that Sprint 10
partially addresses:

- **CLAUDE.md §"Active State" 2-sprint stale** (Sprint 8 SWAGR gap #5; Sprint 9
  SWAGR gap #4) — explicitly resolved by Sprint 10 EA-2 as part of the BlarAI
  strip (success criterion #5).
- **Ledger discontinuity for EA-1 monolithic writes** (Sprint 8 SWAGR gap #1;
  Sprint 9 SWAGR gap #1, MAJOR-recurring) — NOT addressed this sprint;
  doctrine split is structural, not ledger-format-related. Carries forward.
- **Parallel-sprint shared-artifact audit DEC** (Sprint 8 SWAGR gap #6; Sprint
  9 SWAGR gap #7) — NOT addressed this sprint per §13 deliberate non-goal #7;
  Sprint 10 is single-sprint serial, no data point produced. Carries forward
  to cf-1 or a dedicated process sprint.

### 2.2 Repo state at kickoff

- **BlarAI main HEAD**: `647b52d` — `Remove outdated agent definitions and team
  recipes for BlarAI, including business analyst, co-lead, devil-advocate,
  execution-agent, researcher, sdo, and sprint-auditor roles. This cleanup
  streamlines the agent framework and eliminates redundancy in documentation.`
- **devplatform main HEAD**: not directly read this kickoff; last-known
  reference per Stage 6 FINAL close report is the Phase 8 unpause commit; cf-1
  preparation may have advanced devplatform main since. EA-1's audit will
  re-anchor to live HEAD at execution time.
- **Most recent ledger entry**: `docs/ledger/20260424_050528_sprint9_ea5_governance-landing-page.md`
  (Sprint 9 EA-5 closing). The frozen monolithic ledger
  `docs/POST_OPERATIONAL_MATURATION_LEDGER.md` remains frozen at Entry 52 per
  Sprint 8 SWAGR; new entries land in `docs/ledger/`.
- **Open Vikunja `Gate:Pending-Human` gates on Project 6 (Agent Gates bus)**:
  0 — clean start.
- **Open Vikunja `Gate:Pending-CoLead` gates on Project 6**: 0.
- **Active feature branches**: none on BlarAI main; devplatform main convention
  is direct-to-main per Stage 6.7.5 history.
- **Fleet-pause state**: PAUSED. Set 2026-05-08T11:40:59Z by `la`, reason
  "devplatform cloud-fleet redesign in progress". This pause is LA's pre-cf-1
  hold; Sprint 10 does NOT touch the pause state during kickoff. The LA will
  unpause on their own schedule when ready to dispatch Sprint 10 EAs to the
  fleet.
- **Active task roster** (`docs/active_tasks.yaml`): empty (`active_tasks: []`)
  — Sprint 10's roster entry will be added at sign-off (Phase 4).
- **Latest closed sprint-meta artifact**: Stage 6 FINAL close report
  `docs/archive/platform_separation/temp_for_responses/6.X-EA_INSTANCE_17_STAGE6_FINAL_CLOSE_REPORT.md`
  (committed yesterday `77b56de`).

### 2.3 External inputs driving this sprint

- **LA directive 2026-05-09 (this kickoff session)**: revive Stage 6 v1 items
  6.1/6.2/6.3/6.6. The original 6.1.v2 disposition (Stage 6 spec, 2026-04-24)
  said "DO NOT split CLAUDE.md / copilot-instructions.md as part of v2
  execution... defer the split until a separate, explicitly-approved session."
  Today's kickoff is that explicitly-approved session.
- **Stage 6 FINAL close report** (yesterday): the proximate context. Recorded
  the 4 items as DEFERRED with rationale "v2 6.1.v2 disposition + LA
  2026-05-08 confirmation; SOP work already done; revival ticket (if any) gets
  fresh ack chain." Sprint 10 is the revival.
- **cf-1 charter** (Vikunja Project 10 task #368, "Sprint cf-1: DevPlatform
  Cloud-Fleet Redesign — Foundation (sprint tracking)"): chartered but dormant
  per LA. cf-1 begins after Sprint 10 closes. Sprint 10 builds the doctrine
  substrate cf-1 will author into.
- **Sprint 8 SWAGR gap #5 + Sprint 9 SWAGR gap #4** (CLAUDE.md §"Active State"
  2-sprint stale): folded into Sprint 10 success criterion #5.
- **Sprint 10 LA decisions in this kickoff session** (2026-05-09):
  - Sprint name: "Doctrine Split".
  - Coordination: serial (cf-1 dormant until Sprint 10 closes).
  - Execution: 3-EA fleet-driven (EA-1 audit + classification matrix; EA-2
    BlarAI strip + Active State refresh; EA-3 devplatform doctrine authorship +
    SOP portability fix).
  - SOP `from tools.autonomy_budget import state` import portability bug: in
    scope (success criterion #4).
- **Stage 6 v1 spec, item 6.6 commit-step convention**: the original spec
  prescribed two commit messages, one per repo:
  ```
  cd C:\Users\mrbla\BlarAI; git add CLAUDE.md AGENTS.md .github/copilot-instructions.md;
    git commit -m "Stage 6: split doctrine — BlarAI retains product context, devplatform owns platform doctrine"
  cd C:\Users\mrbla\devplatform; git add -A;
    git commit -m "Stage 6: finalize platform doctrine"
  ```
  Sprint 10 will use sprint-style commit messages
  (`[sprint:10][role:ea_code][phase:completion]` per the existing fleet
  convention) rather than the verbatim Stage 6 strings. The convention being
  preserved is the *ordering* (BlarAI-side commit lands before
  devplatform-side commit; both reference each other in their commit body).

## 3. Sprint purpose

BlarAI's three doctrine files compound a fragmentation cost on every agent
session. `CLAUDE.md` (283 lines) is roughly 60% BlarAI runtime context (project
identity, architecture, Use Cases, ADR/DEC inventory, security mandates, coding
standards) and roughly 40% fleet operating model (Vikunja MCP wiring, sprint
lifecycle pointers, agent operating model with comprehension gates,
fleet-pause SOP, key documents that index fleet artifacts).
`.github/copilot-instructions.md` (265 lines) inverts the ratio — roughly 55%
fleet operating model (chat role taxonomy with SDO and EA, autonomous-momentum
rules, attachment scope discipline, Vikunja task tracking with stale `P5-Active`
labels, full fleet-pause SOP block) and roughly 45% BlarAI runtime context
(phase directives, hardware and determinism, security and workflow constraints,
infrastructure prerequisites, coding standards). `AGENTS.md` (24 lines) is
already a thin pointer stub but points at the very files that contain the mixed
content, so the indirection doesn't help — a Codex agent reading AGENTS.md
finds itself routed into the fragmented authority.

The specific cost: every Claude Code session, every Copilot agent session,
every Codex / Cowork sandbox session that initializes by reading these three
files spends ~30–40% of its initial-context budget on doctrine that does not
apply to the work it is about to do. A fresh Co-Lead session reads BlarAI
runtime architecture it will never touch; a fresh BlarAI-runtime-task
Claude Code session reads fleet sprint-lifecycle conventions it will never use.
The mixed content also propagates the fragmentation: a SDO authoring an EA
prompt loads BlarAI runtime context that biases its EA prompt toward runtime
language even when the EA milestone is fleet-infrastructure work; conversely,
an EA doing BlarAI runtime work loads fleet operating model and bakes fleet
conventions into its commit messages, branch names, or peer-review framing.

The strategic leverage of the split is at the cf-1 boundary. cf-1 is going to
redesign the fleet — likely changing the SDO / Co-Lead / EA / Sprint Auditor
model, the wake template structure, the autonomy budget framework, the gate
lattice, and the report queue conventions. If cf-1 begins without devplatform's
doctrine destination shells in place, every cf-1 EA prompt will either
copy-paste fragments out of BlarAI's mixed files (re-entrenching the
fragmentation in a new venue) or invent doctrine de novo (creating a new
divergence between what the fleet code does and what its doctrine claims).
Sprint 10 builds the destination so cf-1 can author cleanly.

The secondary leverage is correctness. BlarAI's fleet-pause SOP block currently
prescribes `python -c "from tools.autonomy_budget import state; state.pause_fleet(...)"`
but the `tools.autonomy_budget` module lives only in devplatform post-Stage-4
cutover (commit `df3d940`, 2026-04-28). Running the SOP literally from a
PowerShell sitting in `C:\Users\mrbla\BlarAI` raises `ModuleNotFoundError:
No module named 'tools.autonomy_budget'`. The SOP currently works only because
every operator who has run it happened to be in the devplatform working
directory at the moment. The split forces this surface to resolve — either via
a portable invocation (e.g., absolute python -m call with the devplatform path
on `sys.path`) or via a standalone CLI script in devplatform that the doctrine
calls by absolute path.

If Sprint 10 is skipped: the fragmentation cost continues to compound; cf-1
has no clean destination to author its updated fleet doctrine; every future
fleet update creates two divergent versions (one in BlarAI's mixed files, one
in cf-1's outputs); the SOP foot-gun stays loaded; and the 2-sprint-stale
§"Active State" gap continues to accumulate, becoming embarrassing
documentation drift.

## 4. Success criteria

1. **BlarAI doctrine files contain zero fleet/SDO/EA/sprint-lifecycle
   guidance.** *Verification*: `grep -E
   'SDO|sdo|wake.*template|sprint.*kickoff|EA Code|Sprint Auditor|Co-Lead|continuation XML|trusted_scope|active_tasks\.yaml|DEC-1[1-5]|fleet_paused|autonomy_budget|cron|peer.review.lattice'
   C:\Users\mrbla\BlarAI\CLAUDE.md C:\Users\mrbla\BlarAI\.github\copilot-instructions.md C:\Users\mrbla\BlarAI\AGENTS.md`
   returns empty OR returns only one-line cross-reference pointers of the form
   `*See also: <devplatform absolute path> §<section>*`. Vikunja conventions
   (label IDs, priority scale, MCP tool list, server-startup procedure) STAY
   in BlarAI per §5.3 because the LA uses Vikunja from the BlarAI working
   directory; the verification regex above does not flag those.

2. **devplatform doctrine files exist with the migrated fleet content.**
   *Verification*: `Test-Path C:\Users\mrbla\devplatform\CLAUDE.md`,
   `Test-Path C:\Users\mrbla\devplatform\AGENTS.md`, and
   `Test-Path C:\Users\mrbla\devplatform\.github\copilot-instructions.md` all
   return `True` against devplatform main; each file ≥ 100 lines (mature-not-
   minimal floor); each file has been touched by a `[sprint:10][role:ea_code]`
   commit on devplatform main.

3. **Cross-references resolve in both directions.** *Verification*: BlarAI's
   `CLAUDE.md` contains at least one explicit pointer of the form
   `*Fleet doctrine lives at `C:\Users\mrbla\devplatform\CLAUDE.md` §<section>.*`
   for each fleet topic moved out (fleet-pause SOP, agent operating model,
   sprint lifecycle); devplatform's `CLAUDE.md` contains at least one pointer
   of the form `*BlarAI runtime context lives at `C:\Users\mrbla\BlarAI\CLAUDE.md` §<section>.*`
   for each runtime topic the fleet may need to consult (Use Cases,
   architecture, security mandates, ADRs). Pointers use absolute Windows-style
   paths (`C:\Users\mrbla\...`) for unambiguous resolution from any working
   directory.

4. **SOP block import portability bug fixed.** *Verification*: from a fresh
   PowerShell sitting in `C:\` (or any working directory other than
   `C:\Users\mrbla\devplatform`), the canonical pause invocation prescribed by
   devplatform's CLAUDE.md fleet-pause SOP runs to completion without
   `ModuleNotFoundError`, and the canonical resume invocation likewise. Tested
   from at least 3 working directories during EA-3 verification: `C:\`,
   `C:\Users\mrbla\BlarAI`, `C:\Users\mrbla\devplatform`. The specific
   technique chosen by EA-3 (e.g., absolute python -m invocation, sys.path
   prepend, standalone CLI script, or other) is implementation detail; the SDV
   requires only that the verification command works from all three
   directories.

5. **BlarAI §"Active State" current.** *Verification*: BlarAI's `CLAUDE.md`
   §"Active State" reflects post-Sprint-9-close baseline: HEAD reference points
   at `git log --oneline main` (or current main); test baseline reads ~981
   passed (per CLAUDE.md note "post-Sprint-8 EA-5"); Task 7 marked COMPLETE;
   Sprints 7, 8, 9 all marked COMPLETE; Sprint 10 marked active; Domain 6 MCP
   marked COMPLETE. The 2-sprint-stale finding from Sprint 8 SWAGR gap #5 +
   Sprint 9 SWAGR gap #4 is explicitly resolved.

6. **Post-split BlarAI line counts decrease meaningfully.** *Verification*:
   `(Get-Content C:\Users\mrbla\BlarAI\CLAUDE.md, C:\Users\mrbla\BlarAI\.github\copilot-instructions.md, C:\Users\mrbla\BlarAI\AGENTS.md | Measure-Object -Line).Lines`
   returns a total ≥ 30% smaller than the pre-split 572-line baseline (target
   ~285–400 lines, soft target 50% reduction). Line count is a proxy — section
   coherence wins. If a 30% reduction would leave dangling references or
   break a coherent runtime narrative, EA-2 prefers coherence and explicitly
   cites which sections it kept verbatim despite hitting the floor in its
   completion report.

7. **Stage 6 v1 items 6.1, 6.2, 6.3, 6.6 recorded CLOSED.** *Verification*:
   the Sprint 10 SCR (authored at sprint close) explicitly records these four
   items as CLOSED with the merge commits that landed each. The archived
   `docs/archive/platform_separation/STATUS.md` is the procedural record; the
   SCR is the authoritative closure note (a separate amendment to STATUS.md is
   not required, since STATUS.md is archived per Stage 6 close — the SCR
   suffices).

## 5. Scope

### 5.1 In-scope

1. **EA-1 — Doctrine Classification Matrix**
   (`docs/sprints/sprint_10/doctrine_classification_matrix.md`): Read all three
   BlarAI doctrine files (`CLAUDE.md`, `.github/copilot-instructions.md`,
   `AGENTS.md`) plus the (zero existing) devplatform counterparts at
   audit-time HEAD. Partition every section / paragraph / XML element into one
   of {**KEEP-BlarAI** = stays in BlarAI; **MOVE-devplatform** = removed from
   BlarAI, authored into devplatform; **MIRROR-both** = present in both repos
   with the same intent but possibly differently phrased; **DELETE** = stale
   or contradictory, removed from both repos with rationale}. Tag each row as
   either DECISION-CLEAR (no LA escalation needed) or DECISION-PENDING-LA
   (requires LA arbitration before EA-2 / EA-3 proceed). Output is a single
   markdown file with a row-per-section table; no edits to doctrine files this
   EA.

2. **EA-2 — BlarAI Strip + Active State Refresh + AGENTS.md Pointer Update**:
   Apply EA-1's matrix's MOVE-devplatform and DELETE rows by stripping the
   marked content from BlarAI's three doctrine files. Apply MIRROR-both rows
   by retaining the BlarAI-side mirror, possibly re-phrased to fit a
   runtime-only narrative. Refresh BlarAI's `CLAUDE.md` §"Active State"
   section from the post-Sprint-9 baseline (live HEAD reference, current test
   baseline ~981, sprint roster state, ledger pointer). Update
   BlarAI's `AGENTS.md` thin pointer to reflect the post-split BlarAI shape
   (the pointer becomes more accurate because it now points at strictly
   runtime-focused doctrine). Add cross-reference pointers (BlarAI →
   devplatform) for each section moved. Commit on a feature branch
   (`feature/p5-task10-ea2-blarai-strip` or similar fleet-conventional name);
   merge to BlarAI main per the standard `trusted_scope` flow. Note: EA-2
   may exceed the `trusted_scope` 500-LOC threshold given it touches three
   files with substantial removals — escalation is acceptable and expected;
   LA may merge via `la_merge_approve.ps1` if the auto-gate flags.

3. **EA-3 — devplatform Doctrine Authorship + SOP Portability Fix**: Author
   `devplatform/CLAUDE.md`, `devplatform/AGENTS.md`, and
   `devplatform/.github/copilot-instructions.md` from EA-1's MOVE-devplatform
   and MIRROR-both rows. Each file ≥ 100 lines, mature-not-minimal,
   self-readable by a Cowork / Codex sandbox agent that has not pre-loaded
   BlarAI runtime context. Add cross-reference pointers (devplatform →
   BlarAI) for each runtime topic the fleet may need to consult. Fix the
   `from tools.autonomy_budget import state` import portability bug per
   success criterion #4 — the implementation choice (absolute python -m,
   sys.path prepend, standalone CLI script, or other) is EA-3's call, but
   the chosen approach is documented in EA-3's completion report and verified
   against the 3-working-directory test in #4. Commit on devplatform main per
   devplatform's existing direct-to-main convention (Stage 6.7.5 history
   establishes this pattern). The commit references the BlarAI-side
   commit hash from EA-2 in its body; symmetric back-reference is added in
   EA-2's commit body if it lands first, else the cross-reference is
   appended via a follow-up commit on the BlarAI side at EA-3 close.

4. **Stage 6 v1 closure record in Sprint 10 SCR**: at sprint close (Co-Lead
   Phase 3 SCR authoring), the SCR explicitly enumerates items 6.1, 6.2,
   6.3, and 6.6 as CLOSED with their respective EA merge commits. The archived
   STATUS.md (`docs/archive/platform_separation/STATUS.md`) is NOT amended —
   the archive is intentionally frozen per Stage 6 FINAL close, and the SCR
   is the live authoritative closure record for the deferred items.

5. **Sprint-close comment on Vikunja tracking task #369**: standard pattern.
   Co-Lead at sprint close adds a `[agent:co_lead][phase:completion]` comment
   to task #369 noting closure with merge commits and SCR/SWAGR paths.

### 5.2 Out-of-scope (deliberately deferred)

1. **Refactoring fleet code** — that is cf-1's purpose. Sprint 10 only edits
   doctrine documents. The single exception is the focused
   `tools/autonomy_budget` import portability fix (success criterion #4),
   which is a one-touch correction the doctrine split would otherwise leave as
   an unresolved foot-gun; it is in-scope because it is the surface the
   doctrine describes.

2. **Authoring new fleet conventions** — Sprint 10 moves existing content; it
   does not invent new sprint-lifecycle, EA-prompt, or SDO-protocol mechanics.
   If EA-1's classification surfaces a section that is stale, contradictory,
   or refers to a deprecated convention, the EA flags it as a finding for a
   follow-up ticket rather than rewriting. Examples that would NOT be
   in-scope rewrites: changing the wake-template Phase numbering; altering
   the DEC-15 SDV/SCR/SWAGR sequence; introducing a new gate label.

3. **Migrating governance docs** (`docs/governance/*.md`) — they describe
   BlarAI runtime invariants (PGOV thresholds, IPC protocol, GPU runtime,
   etc.) and stay in BlarAI. Cross-references from devplatform's authored
   doctrine to BlarAI's governance docs are added as pointers, not relocated
   files.

4. **Touching ADRs** (`docs/adrs/ADR-*.md`) — they describe runtime
   architectural decisions and stay in BlarAI. Sprint 10 does not amend any
   ADR. If a doctrine split surfaces a contradictory ADR claim, that becomes
   a follow-up ticket, not a Sprint 10 amendment.

5. **Authoring the parallel-sprint shared-artifact DEC** — flagged by Sprint
   8 SWAGR (gap #6) and Sprint 9 SWAGR (gap #7). Sprint 10 is single-sprint
   serial and does not even produce a parallel-execution data point this
   sprint. The DEC will land in cf-1 (which by definition will be the
   second-half of a serial pair-with-Sprint-10) or in a dedicated process
   sprint; out-of-scope here.

6. **Ledger-format / monolithic-vs-Q1-1 discipline DEC** — Sprint 8 + Sprint
   9 SWAGRs flagged this MAJOR-recurring; Sprint 10 EA-1 entries should land
   in `docs/ledger/` (Q1-1 per-file format) by default to avoid recurring the
   discontinuity, but the standing DEC authoring is out-of-scope here.

7. **`trusted_scope` diff-size tolerance for structural-cleanup EAs** —
   Sprint 8 SWAGR §14.1 micro-DEC item; out-of-scope. Sprint 10 EA-2 is
   likely to exceed `trusted_scope` 500-LOC threshold; LA-merge-approve via
   `la_merge_approve.ps1` is the accepted workaround, not a rewrite of the
   threshold rule.

8. **Removing or restructuring `tools/vikunja_mcp/`** — the MCP (Model Context
   Protocol) server runs from BlarAI for the LA's interactive Vikunja
   workflow; the Vikunja bridge daemon for sandbox agents also runs from
   BlarAI. Moving them would require rewiring three Claude surfaces (Desktop,
   Code, VS Code Copilot) and breaking sandbox-agent inbox/outbox paths.
   Out-of-scope structural change.

9. **Renaming repos or directory structures** — catastrophically disruptive;
   would invalidate every existing path reference. Out-of-scope.

10. **Vikunja project-rationalization** (Stage 6.7.5 ticket UU #316,
    Vikunja Project 10) — pending and orthogonal to doctrine split.
    Out-of-scope; remains an open Stage 6.7.5 backlog item per Stage 6 FINAL
    close report.

### 5.3 Scope boundaries and edge cases

These are gray-area calls the LA and Co-Lead need to pre-decide so EA-1's
classification matrix has authoritative reference points and EA-2 / EA-3 do
not have to escalate every ambiguity.

- **What "fleet doctrine" means precisely (MOVE-devplatform candidates)**:
  any guidance that describes (a) the SDO / Co-Lead / EA Code / Sprint Auditor
  agents, their cron-fired wake templates, and their prompt-authoring
  responsibilities; (b) the DEC-11 autonomy budget model; (c) the DEC-12
  peer-review lattice and gate flow; (d) the DEC-13 Fleet Reports queue;
  (e) the DEC-14.5 trusted_scope merge model and `la_merge_approve.ps1`
  escalation; (f) the DEC-15 sprint lifecycle (SDV/SCR/SWAGR/`active_tasks.yaml`/
  `ACTIVE_SPRINT.md`); (g) the comprehension-gate-then-stop protocol when
  applied to autonomous agents; (h) the fleet-pause SOP and the
  `autonomy_budget` state.json schema; (i) the EA prompt XML format
  conventions, the SDO continuation XML format, the agent role taxonomy.

- **What "BlarAI runtime doctrine" means precisely (KEEP-BlarAI candidates)**:
  any guidance that describes (a) the 9 Use Cases (UC-001 through UC-009);
  (b) the target hardware (Lunar Lake Core Ultra 7 258V, Arc 140V, 31.323 GB
  ceiling); (c) Hyper-V VM isolation, vsock, OpenVINO, Qwen3-14B + speculative
  decoding; (d) the security mandates (privacy, fail-closed, no external
  network); (e) the locked ADRs (007, 010, 011, 012) and DEC-01 through DEC-10
  (Task 4 production config); (f) BlarAI project structure (services/,
  shared/, launcher/, etc.); (g) coding standards (PEP 8, type hints,
  deterministic execution, gate-check order); (h) the Comprehension Gate as
  applied to interactive Claude Desktop sessions when the LA hands a task to
  an agent in this repo; (i) Phase History (Phases 1-5); (j) §"Active State"
  (current sprint, current HEAD, test baseline, open issues).

- **Vikunja conventions — the split call**: the *labels* (Active id 1,
  Architecture id 4, Documentation id 7, etc.), *priority scale* (0-5),
  *task title pattern* ("Task N: ..." or "ISS-N: ..."), *MCP tool list*
  (the 19 tools by name), and the *server-startup commands* ("If tools fail
  with connection errors: cd to vikunja and run the binary") are content
  the **LA uses interactively from the BlarAI working directory**. They
  STAY in BlarAI's `CLAUDE.md`. The *Vikunja MCP bridge daemon* doctrine
  (the host-side process synchronizing state.json/inbox.json/processed.json
  for sandbox agents) is fleet infrastructure — it MOVES to devplatform's
  `CLAUDE.md`. The clean test: "would this section make sense to read while
  using Vikunja interactively from Claude Desktop in BlarAI?" If yes, KEEP;
  if it only makes sense to a sandbox agent or a fleet operator setting up
  the bridge, MOVE.

- **Comprehension Gate — the mirror call**: the Comprehension Gate as a
  protocol applies to BOTH (a) Claude sessions doing runtime task work in
  BlarAI and (b) fleet sessions doing infrastructure work in devplatform.
  EA-1's default partition is **MIRROR-both**: the protocol is described in
  both repos, possibly with slight phrasing variation per audience (BlarAI:
  "before any work in this repo, present a summary"; devplatform: "before
  any fleet-infrastructure work, present a summary"). EA-1 may instead
  propose MOVE-devplatform with a BlarAI cross-reference if the protocol is
  inherently fleet-shaped (it was authored as part of the fleet operating
  model); the matrix records the choice with rationale.

- **Fleet-Pause SOP — the move call**: clearly fleet doctrine, MOVE to
  devplatform. BlarAI's CLAUDE.md and `.github/copilot-instructions.md` get
  one-line cross-reference pointers of the form: "*When working in this repo,
  follow the fleet-pause SOP at `C:\Users\mrbla\devplatform\CLAUDE.md`
  §Fleet-Pause-SOP.*" The pointer is necessary because every Claude Code
  session in BlarAI still needs to honor the fleet pause (the SOP applies
  cross-repo); only the verbose procedure description moves.

- **Phase History (Phases 1–5)**: BlarAI runtime history. STAYS in BlarAI's
  `CLAUDE.md`.

- **§"Current Active Sprint (DEC-15)" subsection**: this is fleet sprint
  lifecycle — the table referencing `docs/active_tasks.yaml`, the
  `docs/sprints/sprint_<id>/` artifact paths, the agent reading rules.
  MOVES to devplatform's `CLAUDE.md`. BlarAI's `CLAUDE.md` gets a one-line
  pointer: "*Current sprint state lives at
  `C:\Users\mrbla\devplatform\CLAUDE.md` §Current-Active-Sprint, with the
  human-readable pointer at `docs/sprints/ACTIVE_SPRINT.md` in this repo
  (auto-maintained by Co-Lead).*" The
  `docs/sprints/ACTIVE_SPRINT.md` file itself stays in BlarAI (it is
  per-sprint convenience; touching it would re-fragment).

- **§"Agent Operating Model" subsection (Comprehension Gate + Fleet-Pause
  SOP)**: this entire subsection of CLAUDE.md is fleet operating model.
  MOVES to devplatform.

- **Coding Standards**: STAYS in BlarAI (BlarAI runtime code is what's being
  coded). devplatform may have its own coding standards section if devplatform
  has substantial Python infrastructure code; EA-3 copies-or-mirrors at its
  discretion based on what already exists in `devplatform/tools/`.

- **`.github/copilot-instructions.md` — XML preservation**: existing format
  is XML. EA-2 and EA-3 preserve well-formedness in both repos. If a section
  is split mid-XML-element, both halves get well-formed wrappers. If a parent
  element exists only in one repo, the children that move take their parent
  element with them in the destination file (rather than orphaning).

- **devplatform doctrine style**: doctrine in devplatform doesn't have to
  mirror BlarAI's exact tone — devplatform serves a fleet operating model
  audience (autonomous agents, not the LA driving an interactive session).
  EA-3 may consolidate or restructure where the BlarAI version was constrained
  by being a guest in a runtime-focused file. The mature-not-minimal floor
  (≥ 100 lines per devplatform file) ensures content is substantive; the
  ceiling is editorial — devplatform files do not need to mirror BlarAI's
  283/265-line-each surface area.

- **Cross-reference style**: each cross-reference is a single line, italicized,
  using the form "*See also: `<absolute path>` §<section name>*." Multiple
  cross-references are bulleted. No prose linking ("for more information on
  X, you should consult Y"); no directional verbs ("see"/"refer to"/"check").
  Keeps the cross-reference grid mechanical and grep-able.

- **Adjacent-scope expansion (mature-not-minimal)**: if EA-3, while authoring
  devplatform's doctrine, finds that two adjacent sections benefit from being
  cross-referenced internally (within devplatform's own files), the
  cross-reference is in-scope. Adjacent expansion outside devplatform doctrine
  (e.g., editing a runbook in BlarAI to add a fleet pointer) is OUT-of-scope
  and recorded as a finding for a follow-up ticket.

- **Stage 6 v1 ack-chain framing**: the Stage 6 spec's original 6.1-6.3
  acks (e.g., `g6-ea_n*` style if any survived in spec) are NOT carried
  forward. Per Stage 6 FINAL close report's deferral rationale, "revival
  ticket gets fresh ack chain." Sprint 10 EA prompts use the active fleet
  ack convention (`g10-ea<N>_n<M>` per the existing global EA-numbering
  pattern recorded in user memory `feedback_ea_numbering_global.md`).

- **AGENTS.md post-split shape**: BlarAI's AGENTS.md remains a thin pointer
  stub, but the pointer text is updated to be accurate post-split (e.g., it
  may now point to BlarAI's CLAUDE.md for runtime work + devplatform's
  CLAUDE.md for fleet work, with a one-line classification of which agent
  reads which). devplatform's AGENTS.md is authored fresh — it will likely
  be more substantive (≥ 100 lines per the floor) since fleet work is what
  Codex / Cowork sandbox agents actually do.

### 5.4 Parallel-Sprint Authorization & Shared-Artifact Audit

**N/A — serial kickoff (no other sprint active).**

The active task roster (`docs/active_tasks.yaml`) is `active_tasks: []` at
Sprint 10 kickoff. cf-1 (DevPlatform Cloud-Fleet Redesign — Foundation,
Vikunja task #368, Project 10) is chartered but dormant per LA confirmation
2026-05-09 ("cf-1 is not active and will not occur until this is done").
Sprint 10 will close before cf-1 begins; the two sprints will not coexist on
the roster simultaneously.

The fleet-pause state during Sprint 10 (set 2026-05-08T11:40:59Z by `la`,
reason "devplatform cloud-fleet redesign in progress") is the LA's pre-cf-1
hold, not a parallel-sprint coordination. Sprint 10 does not pause/unpause
during kickoff; the LA may unpause at any point during Sprint 10 to dispatch
the 3 EAs to the fleet, and re-pause for cf-1 after Sprint 10 closes.

Because the audit is N/A, the §8.4.1 shared-artifact table and §8.4.2
authorization sign-off boxes are not populated. `set_parallel_sprints_authorized(True)`
will NOT be called for this sprint; `add_active_task` will accept Sprint 10's
roster entry under standard single-sprint conditions.

## 6. Deliverable summary

| # | Deliverable | Type | Target location | Success criterion |
|---|---|---|---|---|
| 1 | Doctrine Classification Matrix | doc (internal) | `docs/sprints/sprint_10/doctrine_classification_matrix.md` | (EA-1 internal artifact) |
| 2 | BlarAI `CLAUDE.md` (stripped + Active State refresh) | doc | `C:\Users\mrbla\BlarAI\CLAUDE.md` | #1, #3, #5, #6 |
| 3 | BlarAI `.github/copilot-instructions.md` (stripped) | doc | `C:\Users\mrbla\BlarAI\.github\copilot-instructions.md` | #1, #3, #6 |
| 4 | BlarAI `AGENTS.md` (pointer refresh) | doc | `C:\Users\mrbla\BlarAI\AGENTS.md` | #1, #3 |
| 5 | devplatform `CLAUDE.md` (authored) | doc | `C:\Users\mrbla\devplatform\CLAUDE.md` | #2, #3 |
| 6 | devplatform `.github/copilot-instructions.md` (authored) | doc | `C:\Users\mrbla\devplatform\.github\copilot-instructions.md` | #2, #3 |
| 7 | devplatform `AGENTS.md` (authored) | doc | `C:\Users\mrbla\devplatform\AGENTS.md` | #2, #3 |
| 8 | SOP import portability fix | code | (EA-3 chooses path within devplatform) | #4 |
| 9 | Stage 6 v1 closure record | section in SCR | `docs/sprints/sprint_10/strategic_completion_report.md` §"Stage 6 v1 deferred items closed" | #7 |
| 10 | Sprint-close comment on tracking task #369 | vikunja comment | task #369 (Project 3) | (operational) |

## 7. EA milestone plan

| EA-# | Working title | One-sentence purpose | Depends on | Approx size |
|---|---|---|---|---|
| EA-1 | Doctrine Classification Matrix | Audit the three BlarAI doctrine files (and devplatform's empty counterparts) and produce a per-section partition table (KEEP-BlarAI / MOVE-devplatform / MIRROR-both / DELETE) that EA-2 and EA-3 implement against | main (`647b52d`) | M |
| EA-2 | BlarAI Strip + Active State Refresh + AGENTS.md Pointer Update | Apply EA-1's matrix's MOVE-devplatform and DELETE rows by stripping content; refresh §"Active State"; update AGENTS.md pointer; add BlarAI → devplatform cross-references; commit on feature branch and merge to BlarAI main | EA-1 merged | L |
| EA-3 | devplatform Doctrine Authorship + SOP Portability Fix | Author `devplatform/CLAUDE.md`, `devplatform/AGENTS.md`, `devplatform/.github/copilot-instructions.md` from EA-1's MOVE-devplatform + MIRROR-both rows; add devplatform → BlarAI cross-references; fix `from tools.autonomy_budget import state` import portability; commit on devplatform main per existing direct-to-main convention | EA-2 merged | L |

**Sequencing rationale**: strictly sequential within Sprint 10. EA-1 produces
the design artifact (the classification matrix) that EA-2 and EA-3 implement;
publishing the matrix as a standalone deliverable provides the LA an
intermediate review surface — if the matrix is ambiguous or surfaces a
classification call the LA wants to redirect, the cost of correction is one
EA, not three. EA-2 must merge before EA-3 begins so that EA-3 can read the
post-strip BlarAI shape and avoid mirroring sections that no longer exist.
EA-3 lands second so that BlarAI's cross-references (added by EA-2) reference
known-good devplatform paths (which exist by the time EA-2's commit is read,
because EA-3 lands on devplatform main directly without the BlarAI-side
gating).

**Cross-repo commit ordering note**: EA-2 commits to BlarAI main; EA-3
commits to devplatform main. The §2.3 commit-step convention preserved from
Stage 6 v1 item 6.6 is the *ordering* (BlarAI lands first, devplatform lands
second), not the verbatim Stage-6-era commit message strings. Each commit
body references the other's hash; if EA-3 lands first by accident due to a
fleet-cadence anomaly, the cross-reference is appended via a follow-up commit
on the BlarAI side at EA-3 close.

**Clustering rationale**: not applicable — Sprint 10 is a 3-EA milestone-per-
phase decomposition, not a clustering-of-deliverables decomposition. Each EA
is one phase: audit → BlarAI implementation → devplatform implementation.

## 8. Dependencies and prerequisites

### 8.1 Upstream dependencies

- Stage 6 FINAL closed and committed — ✅ HEAD `647b52d` confirms (the
  tracking commits `74a4ae1`, `4bde1eb`, `77b56de`, `d10789b` are the Stage 6
  closure chain).
- 3 BlarAI doctrine files exist and are well-formed — ✅ verified at kickoff:
  `CLAUDE.md` 283 lines, `.github/copilot-instructions.md` 265 lines XML,
  `AGENTS.md` 24 lines pointer stub.
- Sprint 10 tracking Vikunja task #369 created with `Gate:Pending-Human` —
  ✅ created during kickoff Phase 1 (commit precedes SDV draft).
- Sprint 9 closed cleanly (predecessor SCR + SWAGR present) — ✅ verified.
- Co-Lead Architect role active — ✅ this kickoff session.
- DEC-15 sprint lifecycle infrastructure intact (template, ACTIVE_SPRINT.md
  pointer, active_tasks.yaml roster, sprint reports directory convention) —
  ✅ verified at kickoff.

### 8.2 External dependencies

- devplatform repo accessible at `C:\Users\mrbla\devplatform` and on `main`
  branch — ✅ at kickoff time.
- Vikunja MCP server running (or trivially restartable per CLAUDE.md
  instructions) — ✅.
- Windows host PowerShell available for verification commands — ✅.
- No external network dependencies (pure documentation + one local code fix).

### 8.3 Assumed invariants

- **cf-1 does NOT begin during Sprint 10** — per LA confirmation 2026-05-09.
  If cf-1 unexpectedly begins (e.g., LA changes direction mid-sprint), Sprint
  10 escalates via CAR (Cross-sprint Amendment Request) and §5.4 is
  retroactively populated. Probability LOW per LA's stated direction.
- **No structural changes to either repo during Sprint 10** — no rename, no
  repo split, no submodule introduction, no path-layout change. Sprint 10
  works against the current repo shapes.
- **The 3 BlarAI doctrine files are not edited outside the Sprint 10 EA chain
  during the sprint window** — if the LA discovers a mid-sprint need to edit
  one of these files (e.g., security-critical correction), the LA's edit
  precedes the next Sprint 10 EA's checkout, and EA-1's matrix is
  re-validated against the updated baseline.
- **LA may unpause the fleet at any point during Sprint 10 to dispatch the 3
  EAs** — pause/unpause coordination is the LA's responsibility; Sprint 10
  itself does not touch the pause state. EA prompts authored by SDO during
  Sprint 10 will include the standard fleet-pause SOP pre-flight per existing
  convention.
- **BlarAI ↔ devplatform mutual visibility holds** — one EA can read both
  repos via absolute paths. Both repos are on the same Windows filesystem,
  no cross-host complications.
- **Vikunja MCP server availability throughout Sprint 10** — if the server
  becomes unreachable mid-sprint, EAs commit their content first, then
  reconcile Vikunja state when the server returns.
- **Git HEAD stability on both repos** — no force-push or history rewrite on
  either main during Sprint 10. Force-push is a fleet-wide halt trigger
  regardless of sprint.

### 8.4 Parallel-Sprint Authorization & Shared-Artifact Audit

N/A — serial kickoff (no other sprint active). See §5.4 for full rationale.
`set_parallel_sprints_authorized(True)` will NOT be called for this sprint.

## 9. Risks and unknowns

### 9.1 Known risks

| Risk | Probability | Impact | Mitigation |
|---|---|---|---|
| EA-1's classification matrix produces ambiguous rows that EA-2 and EA-3 disagree on (e.g., the Comprehension Gate row) | Medium | Medium | EA-1 explicitly tags ambiguous rows DECISION-PENDING-LA; SDV §5.3 pre-disposes the trickier cases (Comprehension Gate → MIRROR-both default; Vikunja conventions split call documented; Fleet-Pause SOP → MOVE clearly); Co-Lead at peer review either decides or escalates |
| Line-count target (#6, ≥30% reduction floor) forces deletions that hurt coherence | Low | Medium | Line count is a soft target per §4 #6; coherence wins. EA-2 cites which sections were kept verbatim despite hitting the floor in its completion report; LA arbitrates if the deletion-vs-coherence trade-off becomes contentious |
| devplatform-side authoring style drifts noticeably from BlarAI's tone, creating cognitive dissonance for the LA reading both | Low | Low | EA-3 explicitly mirrors BlarAI's section header conventions; deviations are documented as design choices in EA-3's completion report; LA may redirect via CAR if the drift is excessive |
| SOP import portability fix introduces a regression in pause/resume semantics | Low | High | EA-3 verifies pause + resume (full triplet) from 3 working directories before commit (BlarAI root, devplatform root, `C:\`); the verification artifact is included in EA-3's completion report with verbatim PowerShell output |
| Fleet unpause window during Sprint 10 lands a non-Sprint-10 commit on a doctrine file mid-sprint (e.g., LA edits CLAUDE.md for a security correction) | Low | Medium | LA-coordinated; Sprint 10's working set is the 3 files in each repo; if a non-Sprint-10 edit lands, EA-1 re-validates its matrix against the updated baseline before EA-2 / EA-3 begin |
| EA-3's devplatform direct-to-main commit pattern differs from BlarAI's branched-merge pattern, surprising a peer reviewer | Confirmed (not a risk per se, design choice) | N/A | EA-3 documents the cross-repo pattern divergence in its completion report; the divergence reflects existing Stage 6.7.5 history and is not a Sprint 10 invention |
| Active State refresh in EA-2 conflicts with cf-1's eventual Active State write | Low | Low | Active State is BlarAI runtime state, not fleet state — should not be cf-1's territory; if cf-1 nevertheless edits Active State, the conflict is resolved by Sprint 11 (or whichever sprint follows cf-1) per standard sprint-transition Co-Lead Phase 3 refresh |
| `.github/copilot-instructions.md` XML envelope splits non-trivially (parent element has children that should split) | Medium | Low | EA-2 / EA-3 preserve XML well-formedness in both repos; if a parent's children split, the parent is duplicated in both repos with the appropriate child subset; EA-1's matrix flags such elements as DECISION-PENDING-LA if non-trivial |
| EA-2 exceeds `trusted_scope` 500-LOC threshold and merge-gate ESCALATEs | High (likely) | Low | LA-merge-approve via `la_merge_approve.ps1` is the accepted workaround, established in Sprint 9 EA-4 (ISS-239 ESCALATE pattern); LA budget for ~5 min ESCALATE handling per §11 |
| Sprint 10 EA prompts (authored by SDO at execution time) inherit Stage 6 ack chain framing inappropriately | Low | Low | Per Stage 6 FINAL close report rationale, "revival ticket gets fresh ack chain"; SDO references Sprint 10 SDV (this document) as the alignment baseline, not the Stage 6 spec; ack labels follow `g10-ea<N>_n<M>` global-EA-numbering pattern |
| BlarAI's `tools/vikunja_mcp/README.md` Quick Start §2 has known stale `cd` reference (Stage 6 close report A12 carry-over) — Sprint 10 doctrine reads might surface it | Confirmed (pre-existing) | Low | Out-of-scope per §5.2 #1 (Sprint 10 doesn't refactor fleet code or run-tooling docs); EA-1 records the encounter as a finding but does not act |

### 9.2 Known unknowns

1. **Final post-split line counts** — depend on EA-1's matrix decisions.
   Soft target ~50% reduction (~286 lines total across the three BlarAI
   files), hard floor 30% reduction (~400 lines). Variance driven by how
   many DELETE rows the matrix produces vs MIRROR-both rows.
2. **Number of MIRROR-both rows in EA-1's matrix** — affects EA-3's authorial
   volume in devplatform. Estimate range: 3–8 mirror rows (Comprehension Gate,
   commit-message conventions, branch-naming if used, gate-checking order
   philosophy, possibly the fail-closed principle if it shows up in fleet
   contexts).
3. **The right tech-implementation for SOP import portability** — EA-3
   chooses among (a) absolute python -m invocation with `PYTHONPATH=C:\Users\mrbla\devplatform`
   prepended; (b) sys.path-augmenting wrapper script `pause_fleet.py` shipped
   in devplatform; (c) standalone CLI script `tools/autonomy_budget/cli.py`
   with `python C:\path\to\cli.py pause "<reason>"`; (d) a small package
   manifest making `tools.autonomy_budget` importable when devplatform is on
   `PYTHONPATH`. SDV does not pre-decide; EA-3 chooses based on what's
   already idiomatic in devplatform (likely (c) given Stage 6.7.5's
   PS1-script-with-env-var pattern).
4. **Whether EA-3 needs to touch `tools/autonomy_budget/state.py` itself
   or only the doctrine description of how to invoke it** — if (a) or (c)
   are chosen, no Python code change; if (b) or (d), small Python file
   added/touched. Either path is in-scope under success criterion #4.
5. **devplatform main HEAD at EA-3 execution time** — may have advanced
   between Sprint 10 kickoff (now) and EA-3 dispatch. EA-3's prompt re-anchors
   to live HEAD at execution time.
6. **Whether EA-3's devplatform commits trigger any cf-1-prep observation**
   — cf-1 is dormant; if cf-1 happens to schedule a hold or a precondition
   that Sprint 10 doctrine-creation triggers, that's information to surface,
   not a block.

### 9.3 Unknown unknowns posture

The non-obvious failure modes are:

(a) **The Comprehension Gate doctrine entanglement**: the gate is currently
in BlarAI's CLAUDE.md as part of the Agent Operating Model section. It
applies to BOTH runtime task work (in BlarAI) and fleet work (in
devplatform). EA-1 may discover the gate's authoring intent assumed a single
unified doctrine venue; splitting it without re-thinking may produce two
slightly different gates that drift over time. SDV §5.3 default is
MIRROR-both; if EA-1 discovers this is structurally fragile, escalation
path is to author the gate as a standalone `docs/governance/comprehension-
gate.md` in BlarAI with cross-references from both CLAUDE.md files. Out-of-
scope for Sprint 10 to make that move proactively, but EA-1 may flag it.

(b) **`.github/copilot-instructions.md` XML envelope structural fragility**:
existing XML elements may have implicit dependencies (e.g., a `<rule>` cited
by name from another section). If a moved `<rule>` is referenced by a
remaining BlarAI rule, the reference becomes broken. EA-1's matrix should
flag inter-element references; EA-2 / EA-3 implement appropriate cross-
references or duplications. Probability of a non-trivial dependency chain:
medium (the XML has 14 named `<rule>` elements + 5 named `<phase>` elements).

(c) **Cross-references in BlarAI documentation outside the 3 doctrine files
that point at sections about to move** — e.g., a runbook in
`docs/runbooks/` that cites "see CLAUDE.md §Fleet-Pause SOP" by section
name. After the move, the cross-reference becomes broken (the section no
longer exists in CLAUDE.md). EA-2's strip should sweep `docs/`,
`docs/governance/`, `docs/runbooks/` for such references and either
update them in-place or record findings for follow-up tickets. Sprint 10
prefers in-place fix where the change is mechanical (one-line cross-
reference update); records as follow-up where the reference is more
structural.

(d) **Sprint Auditor template gaps for cross-repo sprints** — Sprint 10 is
the first BlarAI sprint that writes to BOTH BlarAI main AND devplatform main.
The SWAGR template `docs/sprints/_templates/Strategic_Work_Analysis_*.md`
may not have a §5.4 cross-repo ghost-commit section; the auditor may flag
the gap and recommend template amendment. Sprint 11+ concern, not a Sprint
10 blocker.

## 10. Alignment to long-term roadmap

- **Project phase alignment**: Phase 5 Post-Operational Development. Sprint
  10 closes Platform Separation v2 procedurally — the procedure was declared
  COMPLETE yesterday at Stage 6 FINAL, but the deferred items 6.1/6.2/6.3/6.6
  remained the open loose end. Closing them lets cf-1 begin from a clean
  doctrine substrate. Sprint 10 also addresses two recurring SWAGR carry-over
  gaps (CLAUDE.md §"Active State" 2-sprint stale; partial reduction of
  doctrine fragmentation).

- **Use Case alignment**: indirect — no UC advances. The mature dividend is
  that future UC sprints (UC-005 Code Agent, UC-002 Memory Search, UC-009
  Autonomous Maintainer) start from a doctrine baseline that doesn't conflate
  runtime intent with fleet operating model. Less attention waste per future
  agent session reading initial context. The Sprint 9 SWAGR's recommendation
  ("advance one Use Case in Sprint 10") is deferred to Sprint 11 or a later
  sprint per LA's sequencing decision.

- **ADR alignment**: no ADRs amended. ADR-007 (iGPU trust boundary), ADR-010
  (PA classification on GPU), ADR-011 (LLM inference on GPU; NPU retired),
  ADR-012 (Qwen3-14B + speculative decoding), and ADR-005 (memory ceiling)
  are runtime architectural decisions that stay in BlarAI doctrine. They may
  be cross-referenced from devplatform doctrine where fleet code touches
  runtime concerns (e.g., the launcher's deployment target hardware
  references), but the ADR content itself is not amended.

- **DEC alignment**: DEC-11 (autonomy budgets), DEC-12 (peer-review lattice),
  DEC-13 (Fleet Reports queue), DEC-14.5 (trusted_scope merge), and DEC-15
  (sprint lifecycle) are the fleet operating model — they are the canonical
  references for the doctrine being moved to devplatform. DEC-01 through
  DEC-10 (Task 4 production config) are BlarAI runtime production-config
  decisions and stay in BlarAI's doctrine. **No new DEC is authored this
  sprint** — the parallel-sprint shared-artifact DEC carry-over from Sprint
  8/9 SWAGRs is explicitly out-of-scope (§5.2 #5); the ledger-format DEC
  carry-over is also out-of-scope (§5.2 #6); the trusted_scope diff-size
  DEC is out-of-scope (§5.2 #7).

## 11. Roles and accountability

| Role | Responsibility this sprint | Budget |
|---|---|---|
| LA (Lead Architect) | SDV sign-off; CAR adjudication if EA-1's classification matrix surfaces a DECISION-PENDING-LA row that requires LA arbitration; merge approval via `la_merge_approve.ps1` if EA-2 exceeds `trusted_scope` (likely); SCR + SWAGR read at sprint close; fleet pause/unpause coordination across the cf-1 boundary | ~30 min total |
| Co-Lead Architect | This kickoff session (Phases 0–5 of `/sprint-kickoff`); SDO continuation XML authoring for Sprint 10 if/when fleet unpauses; EA peer review for 3 EAs at comprehension gate + completion gate; SCR authoring at sprint close | Autonomous per DEC-11 §1.1 |
| SDO (Strategic Development Orchestrator) | EA prompt authoring for 3 EAs (each prompt grounded in this SDV + EA-1's matrix where relevant); EA peer review at completion gate; non-overlap sweep is N/A (single-sprint serial) | Autonomous per DEC-11 §1.2 |
| EA Code | Milestone execution for 3 EAs; EA-1 produces classification matrix as a markdown file; EA-2 commits to BlarAI on a feature branch + merges; EA-3 commits to devplatform main directly per Stage-6.7.5 convention; each EA reads this SDV (and EA-1's matrix where applicable) as alignment baseline | Autonomous per DEC-11 §1.3 |
| Sprint Auditor | SWAGR independent production post-SCR; first audit covering a cross-repo sprint (BlarAI + devplatform main) — auditor may flag SWAGR template gaps re: cross-repo ghost-commit sweep; auditor environment unchanged from Sprint 9 (no pytest, doc-only sprint) | Autonomous per DEC-15 §sprint_auditor_role_spec |

## 12. Estimated effort

- **Rough duration**: 3 EAs × ~1 fleet-day each (Sprint 9 baseline) = ~3
  fleet-days. Sprint 10 may run slower than Sprint 9 because EA-1's design
  surface is non-trivial (classification across 572 lines of mixed doctrine
  with multiple DECISION-PENDING-LA candidates likely surfacing). Reference
  estimate: 3–5 calendar days from fleet unpause to Sprint 10 SCR. Calendar
  duration is gated by LA's pre-cf-1-pause schedule rather than fleet
  capacity per se.

- **LA active-time expectation**: ~30 minutes total — 15 min SDV sign-off
  (this kickoff session); ~5 min CAR adjudication if EA-1's matrix surfaces
  a DECISION-PENDING-LA row (estimated 1–3 such rows); ~5 min merge-gate
  ESCALATE handling for EA-2 (likely to exceed `trusted_scope` line-count
  threshold); ~5 min SCR + SWAGR read at sprint close. Variance driver: if
  EA-1's classification matrix is unambiguous (DECISION-CLEAR for all rows),
  LA active time falls to ~25 min; if the matrix surfaces 4+ DECISION-PENDING-
  LA rows, LA active time may rise to ~45 min.

- **Confidence in estimate**: medium. Three drivers of variance:
  1. EA-1's classification ambiguity rate — primary variance.
  2. Whether `.github/copilot-instructions.md` XML splits cleanly or
     non-trivially.
  3. Whether the LA chooses to drive the fleet on Sprint 10 with a single
     unpause window (efficient) or with multiple stop-start windows around
     other workstreams (slower, more LA active-time per restart).

## 13. Deliberate non-goals

1. **Authoring a `docs/governance/doctrine-fragmentation-retrospective.md`
   reflecting on why the fragmentation accumulated** — the SCR is the
   retrospective for this sprint; a separate doc would inflate deliverable
   count without reader benefit. Rejected as scope inflation.

2. **Migrating BlarAI's `tools/vikunja_mcp/` directory to devplatform** —
   the MCP server runs from BlarAI for the LA's interactive Vikunja
   workflow (Claude Desktop + Code + VS Code Copilot); the bridge daemon
   for sandbox agents also runs from BlarAI's host paths. Moving would
   require rewiring three Claude surfaces and breaking sandbox-agent inbox/
   outbox conventions. Rejected as out-of-scope structural change.

3. **Authoring a "Where things live" mega-index in either repo** — a flat
   index would duplicate the cross-references the doctrine files themselves
   contain. Rejected as redundancy. The mature solution is well-structured
   doctrine with consistent cross-reference style (§5.3), which Sprint 10
   delivers.

4. **Renaming the repos or directory structures** — catastrophically
   disruptive; would invalidate every existing path reference, ledger entry,
   commit message, and runbook citation. Rejected as orthogonal to doctrine
   split.

5. **Changing the Vikunja project layout** (Project 3 = BlarAI Core
   Development, Project 6 = Agent Gates bus, Project 8 = Fleet Reports,
   Project 9 = BlarAI Drafts, Project 10 = DevPlatform-Meta) — the existing
   layout serves both repos and is documented in CLAUDE.md (BlarAI side) +
   project_summary tool output. Rejected as orthogonal.

6. **Introducing a `Status:Draft` workflow for doctrine docs** (analogous to
   the BlarAI Drafts pattern in Vikunja Project 9) — both repos' doctrine
   files are authoritative on commit, not drafts; a draft workflow would add
   process overhead without solving a real problem. Rejected as gratuitous.

7. **Authoring the parallel-sprint shared-artifact DEC during Sprint 10** —
   Sprint 10 is single-sprint serial; the DEC's data point is parallel
   coexistence, which Sprint 10 does not produce. Will land in cf-1 (the
   first half of which will be parallel with Sprint 11 or beyond) or in a
   dedicated process sprint. Rejected as wrong sprint for the artifact.

8. **Removing the obsolete labels from `.github/copilot-instructions.md`**
   (the stale `<labels>` element references `P5-Active`, `P5-Complete` which
   were renamed to `Active`, `Complete` server-side per CLAUDE.md note) **as
   a separate Sprint 10 deliverable** — this defect surfaces during EA-1's
   audit and gets folded into EA-2's strip naturally (the Vikunja-conventions
   subsection STAYS in BlarAI per §5.3, and its label list gets refreshed
   to current server-canonical names while it's being re-edited). No
   standalone deliverable; not a separate non-goal in the strict sense, just
   an observation about how it lands.

9. **Authoring devplatform's CONTRIBUTING.md, README.md, or other top-level
   non-doctrine docs** — Sprint 10 is doctrine-only. devplatform's broader
   documentation surface is cf-1's purview. Rejected as scope creep.

10. **Backfilling Sprint 8 / Sprint 9 EA-1 ledger discontinuity** (Sprint 8
    SWAGR gap #1; Sprint 9 SWAGR gap #1, MAJOR-recurring) — orthogonal to
    doctrine split. The recurring pattern is a process defect addressed
    separately. If EA-1 / EA-2 / EA-3 ledger entries this sprint
    naturally land in `docs/ledger/` (Q1-1 per-file format), that breaks
    the recurring-pattern chain incidentally; explicit backfill of prior
    sprints is out-of-scope.

## 14. Sign-off

### Lead Architect

> I, `blarai`, have reviewed this SDV on `2026-05-09`. I
> approve the sprint scope, success criteria, and risk posture as stated. I
> accept that the fleet will proceed autonomously per the DEC-11 budgets
> within these bounds (subject to my own pause/unpause coordination across
> the cf-1 boundary). I will read the SCR and SWAGR when produced.

_(Signed via the frontmatter field `la_approved_on` above. A commit authored
by LA on main is the durable signature.)_

### Co-Lead Architect

> Co-Lead acknowledges the LA-signed SDV and will translate it into the first
> SDO continuation XML + milestone sequencing per the DEC-12 flow once the
> fleet unpauses. Any scope deviation arising during execution will be
> flagged via the DEC-12 peer-review lattice or escalated via a CAR
> (Cross-sprint Amendment Request, despite this being a single-sprint
> serial — the CAR mechanism applies to in-sprint scope deviations as well).

_(Signed via the frontmatter field `co_lead_drafted_on` + git commit by
[agent:co_lead] that lands this SDV on main.)_

---

## Appendix A — SDV revision log

| Version | Date | Changed by | Change summary |
|---|---|---|---|
| 1 | 2026-05-09 | Co-Lead | Initial draft |
