---
# Strategic Design Vision (SDV) — BlarAI Sprint <N>
#
# This file is an LA-facing strategic document. It is authored
# interactively at sprint start by Co-Lead Architect + Lead Architect.
# It is the baseline against which the end-of-sprint SCR and SWAGR
# measure success and gap.
#
# Fill in every field below. Do NOT skip sections — if a section is
# genuinely not applicable, write "N/A — <one-sentence reason>" rather
# than deleting. Empty sections are a signal of incomplete thinking.
#
# Frontmatter fields below are machine-read by Sprint Auditor and
# related tooling. Keep field names verbatim.
---
sprint_id: <N>
sprint_name: "<short human-readable theme, e.g. 'Test Governance Hardening'>"
predecessor_sprint_id: <M | null>        # null for the project's first sprint
vikunja_tracking_task_id: <id>           # the Vikunja task this sprint rolls up to
start_date: "<YYYY-MM-DD>"
target_completion_date: "<YYYY-MM-DD>"   # LA-LA's honest estimate; not a hard deadline
la_approved_on: "<YYYY-MM-DDTHH:MM±HH:MM>"  # filled at LA sign-off
la_approved_by: "blarai"
co_lead_drafted_on: "<YYYY-MM-DDTHH:MM±HH:MM>"
co_lead_commit_when_drafted: "<git_HEAD_7char_at_draft_time>"
sdv_version: 1                            # increments on any LA-amended revision
---

# Strategic Design Vision — Sprint <N>: <Sprint Name>

## 1. Executive brief

**3–5 sentences, plain English.** What is this sprint, why is it happening now, and what does "done" look like?

> Example style: "Sprint 8 hardens the test-audit framework produced by Sprint 7 into a repeatable governance process. We do this now because Sprint 7's findings revealed 37 coverage gaps that need structured tracking, and the next use-case rollout (USE-CASE-005) expects a mature test baseline. Done = a live test-governance dashboard, an enforcing pre-commit check, and the open gaps from Sprint 7 triaged into three buckets (fix-now, defer-to-phase-6, accept-as-risk)."

## 2. Context

**Situation at sprint start.** Required subsections:

### 2.1 Predecessor sprint outcome

- Link to predecessor SCR: `docs/sprints/sprint_<M>/strategic_completion_report.md`
- Link to predecessor SWAGR: `docs/sprints/sprint_<M>/Strategic_Work_Analysis_and_Gap_Report_Sprint_<M>_*.md`
- 2–3 sentence summary of what that sprint delivered and any open threads it left.

### 2.2 Repo state at kickoff

- Main branch HEAD: `<git commit 7-char>`
- Most recent ledger entry: Entry `<N>`
- Open Vikunja Pending-Human gates: `<count + names>`
- Known-active feature branches: `<list>`

### 2.3 External inputs driving this sprint

- LA asks / user memory items influencing scope: `<bulleted list>`
- Stakeholder concerns surfaced since predecessor: `<bulleted list>`
- Any relevant ADR / DEC proposals in play: `<list>`

## 3. Sprint purpose

**Why this sprint, in prose.** 2–4 paragraphs explaining the strategic rationale. Tie to long-term project roadmap. Answer: if we skipped this sprint, what would break or degrade?

## 4. Success criteria

**Measurable, binary outcomes.** 3–7 criteria. Each should be verifiable at sprint end via either (a) a commit on main, (b) a test result, or (c) a file on disk.

Format: numbered list, each criterion 1–3 sentences. Use the "Given / When / Then" pattern if helpful.

1. **<Criterion name>**: <criterion body>. *Verification method: <e.g., "test suite X passes", "commit on main touches file Y", "ledger Entry Z authored">.*
2. …

## 5. Scope

### 5.1 In-scope

Specific, numbered deliverables. Each item becomes a candidate EA milestone.

1. **<Deliverable name>**: <one paragraph body describing what will exist when done>.
2. …

### 5.2 Out-of-scope (deliberately deferred)

What is explicitly NOT being done this sprint, and why. Prevents scope creep and scope confusion.

1. **<Item>** — <reason for deferral; when it might be addressed>.
2. …

### 5.3 Scope boundaries and edge cases

Gray-area calls the LA and Co-Lead reviewed. E.g. "refactoring adjacent module X is OUT unless a test requires it, in which case a minimal edit is IN."

## 6. Deliverable summary

High-level list of artifacts produced by sprint end. Map each to a success criterion in §4.

| Deliverable | Type | Target location | Success criterion |
|---|---|---|---|
| `<file or feature>` | `<doc / code / test / schema / config>` | `<path>` | `#<N>` |

## 7. EA milestone plan

**Ordered list of EA batches.** Co-Lead authors the actual EA prompt XMLs one at a time during the sprint via the normal DEC-12 flow. This section is the PLAN, not the prompts.

| EA-# | Working title | One-sentence purpose | Depends on | Approx size |
|---|---|---|---|---|
| EA-1 | `<name>` | `<what it does>` | `<EA-N / main>` | `<S / M / L>` |
| EA-2 | … | … | EA-1 | … |

## 8. Dependencies and prerequisites

### 8.1 Upstream dependencies

Things that must exist or be true BEFORE any EA can start. E.g. "Merge of PR #nn", "config migration", "predecessor SCR".

### 8.2 External dependencies

Anything outside the repo. E.g. a specific Anthropic API tier, a running Vikunja version, a hardware assumption.

### 8.3 Assumed invariants

"We assume X is stable for the duration of this sprint." If X changes, the sprint may need a CAR loop.

### 8.4 Parallel-Sprint Authorization & Shared-Artifact Audit

**Applicability**: Fill out this subsection *only* when this sprint will run concurrently with one or more already-active sprints. If the roster (`docs/active_tasks.yaml`) will be empty when this sprint starts, write **"N/A — serial kickoff (no other sprint active)"** and skip the audit. Otherwise, the audit is **required** before the LA signs the SDV, and `set_parallel_sprints_authorized(True)` must be called before `add_active_task` will accept this sprint's entry.

**Why this section exists**: Sprint 8 and Sprint 9 ran in parallel 2026-04-22/23 without this audit. Both sprints' EA-1 milestones computed "next = Entry 51" on the monolithic ledger simultaneously, producing an unresolvable merge conflict that forced a mid-sprint ledger-format change (Q1-1). This section prevents that class of surprise.

**Concurrent sprints this one overlaps**: list by `sprint_id` and `task_id`.

| This sprint | Overlapping sprint(s) | Overlap window |
|---|---|---|
| `<this sprint_id / task_id>` | `<sprint_id / task_id>` | `<YYYY-MM-DD → YYYY-MM-DD-or-open>` |

#### 8.4.1 Shared-artifact classification

Enumerate every artifact this sprint will **write** that is not sprint-scoped. For each, classify the write pattern and pick a mitigation. Reference: `C:\Users\mrbla\devplatform\docs\governance\parallel-sprints.md` for the full best-practice guide.

| Artifact | Will this sprint write it? | Pattern | Collision risk | Mitigation chosen |
|---|---|---|---|---|
| `main` branch (BlarAI) | Y (via EA merges) | M (shared-mutable) | Low (Co-Lead serializes merges) | serialize-at-co-lead (default) |
| `devplatform main` (when cross-repo) | Y (via direct-to-main commits per cross-repo EA) | M (shared-mutable across cross-repo sprints) | Low (Co-Lead serializes; one direct commit per cross-repo EA) | serialize-at-co-lead |
| `docs/active_tasks.yaml` | Y (add+remove roster entry) | M (shared-mutable) | Low (atomic write + distinct task_id) | atomic-write-by-task_id (existing API) |
| `tools/autonomy_budget/state.json` | Rare | M | Medium (race observed historically) | coordinate LA pause-state changes out-of-band |
| `docs/sprints/ACTIVE_SPRINT.md` | Y (Co-Lead auto-maintained) | O (overwrite) | Low (Co-Lead only writer) | single-writer rule (Co-Lead) |
| Vikunja Project 6 (Agent Gates bus) | Y | A (append gates) | None (new task IDs) | none needed |
| Vikunja Project 8 (Fleet Reports) | Y | A (append) | None | none needed |
| `docs/ledger/` (per-entry files) | Y (Q1-1 format) | A (atomic-create with timestamp filename) | None | none needed — Q1-1 already sharded |
| `docs/scheduled/ea_queue/archive/sprint_<N>/` | Y (Co-Lead archive step) | O (per-sprint subdir) | None | per-sprint subdir (2026-04-24) |
| **`<this sprint's other shared writes>`** | `<Y/N>` | `<R/A/O/M>` | `<None/Low/Med/High>` | `<mitigation>` |

**Pattern codes**:
- **R** = Read-only (no write — trivially safe, usually omit from table).
- **A** = Append-only atomic (e.g., atomic-create to a uniquely-named new file).
- **O** = Overwrite own entry (write to a path unique to this sprint — sprint-scoped).
- **M** = Shared-mutable (two sprints could write the same bytes; requires explicit coordination).

**Mitigation options** (pick one per M-class row):
1. **Shard to sprint-scoped path** (best — eliminate the shared-artifact entirely).
2. **Atomic write + UUID/timestamp filename** (append-only pattern).
3. **Single-writer rule** (exactly one role ever writes; other roles read-only).
4. **Serialize across sprints** (the step runs for only one sprint at a time; block via fleet pause or explicit lock).
5. **Accept + monitor** (low-probability collision; document detection + recovery).

If any M-class row's chosen mitigation is #5 ("accept + monitor"), the SDV requires a specific §9 Known Risk entry with probability and detection mechanism.

#### 8.4.2 Authorization sign-off

- [ ] I have enumerated every shared-mutable artifact this sprint will write above.
- [ ] I have cross-checked the overlapping sprint(s)' SDV §8.4 (if they exist) for the same artifacts.
- [ ] Every M-class row has a mitigation picked from options 1-5.
- [ ] Any "accept + monitor" choice has a matching §9 entry.
- [ ] `set_parallel_sprints_authorized(True)` will be called before `add_active_task` for this sprint.

LA confirms this section is complete via SDV sign-off (§14).

## 9. Risks and unknowns

### 9.1 Known risks

Things that could go wrong, with probability + impact + mitigation.

| Risk | Probability | Impact | Mitigation |
|---|---|---|---|
| `<description>` | `<low / med / high>` | `<low / med / high>` | `<action to take>` |

### 9.2 Known unknowns

Questions whose answers we don't have yet but that we'll learn during the sprint.

1. …

### 9.3 Unknown unknowns posture

A one-paragraph acknowledgment of the kinds of things we're probably missing. Forces humility into the plan.

## 10. Alignment to long-term roadmap

How this sprint advances the project at the largest scale.

- **Project phase alignment**: `<e.g., "Phase 5 Post-Operational Development, third of four planned test-governance sprints">`
- **Use Case alignment**: `<which of the 9 Use Cases this touches>`
- **ADR alignment**: `<relevant ADRs and whether this sprint confirms or revises them>`
- **DEC alignment**: `<relevant DECs>`

## 11. Roles and accountability

| Role | Responsibility this sprint | Budget |
|---|---|---|
| LA (Lead Architect) | SDV sign-off, CAR adjudication, SWAGR read, occasional merge approval on carve-out miss | \~20 min / week |
| Co-Lead Architect | SDO continuation authoring, milestone peer review, SCR | Autonomous per DEC-11 §1.1 |
| SDO | EA prompt authoring, EA work peer review | Autonomous per DEC-11 §1.2 |
| EA Code | Milestone execution | Autonomous per DEC-11 §1.3 |
| Sprint Auditor | SWAGR independent production | Autonomous per DEC-15 §sprint_auditor_role_spec |

## 12. Estimated effort

- Rough duration: `<e.g., "2–3 days fleet-time, ~5 EA milestones">`
- LA active-time expectation: `<e.g., "~45 min total: 15 min SDV sign-off, 15 min CARs, 15 min SWAGR read">`
- Confidence in estimate: `<low / medium / high>` — be honest.

## 13. Deliberate non-goals

Things we've considered doing but affirmatively decided NOT to do. Not the same as "out-of-scope" — these are features that someone proposed and we rejected.

1. `<item>` — **Rejected because** `<reason>`.
2. …

## 14. Sign-off

### Lead Architect

> I, `<LA name>`, have reviewed this SDV on `<date>`. I approve the
> sprint scope, success criteria, and risk posture as stated. I accept
> that the fleet will proceed autonomously per the DEC-11 budgets
> within these bounds. I will read the SCR and SWAGR when produced.

_(Signed via the frontmatter field `la_approved_on` above. A commit
authored by LA on main is the durable signature.)_

### Co-Lead Architect

> Co-Lead acknowledges the LA-signed SDV and will translate it into
> the first SDO continuation XML + milestone sequencing per the
> DEC-12 flow. Any scope deviation arising during execution will be
> flagged via the DEC-12 peer-review lattice or escalated via a CAR.

_(Signed via the frontmatter field `co_lead_drafted_on` + git commit
by [agent:co_lead] that lands this SDV on main.)_

---

## Appendix A — SDV revision log

Track every revision. Each amendment increments `sdv_version` in
frontmatter. Keep a reverse-chronological log here.

| Version | Date | Changed by | Change summary |
|---|---|---|---|
| 1 | `<date>` | LA | Initial sign-off |
| 2 | `<date>` | LA | Amended §5.1 deliverable #3 after EA-1 surfaced scope boundary issue |
| (template) | 2026-05-12 | Sprint 11 EA-3 | Fixed §8.4.1 broken pointer: replaced the BlarAI-relative path to the parallel-sprints doctrine (which no longer resolves on BlarAI after Sprint 10 EA-3 moved the file to devplatform) with the absolute path `C:\Users\mrbla\devplatform\docs\governance\parallel-sprints.md`. Added `devplatform main` row to §8.4.1 shared-artifact classification table (Y / M / Low / serialize-at-co-lead) so cross-repo sprints have an explicit pre-listed shared-mutable artifact instead of inventing one each kickoff. Motivation chain: Sprint 9 SWAGR §9.3 item 4 predicted template gaps around cross-sprint coexistence; Sprint 10 doctrine split (EA-3, commit `cf95e4b`) created the broken pointer; Sprint 11 EA-3 closes the loop together with the SWAGR template §5.5 amendment. |
