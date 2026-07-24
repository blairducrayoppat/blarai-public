---
role: sdo
phase: pending-la-arbitration
revision: 1
tracking_task: 369
vikunja_comment: 520
posted_at: 2026-05-11T22:00:00Z
verdict: null
---

# SDO Phase 2 — LA arbitration request for 6 DECISION-PENDING-LA matrix rows

**Pre-condition**: EA-1 (Doctrine Classification Matrix) merged at `caa46f5` (LA via `la_merge_approve.ps1`, DEC-14.5). Matrix tail at `docs/sprints/sprint_10/doctrine_classification_matrix.md:263` explicitly states: *"LA review of the six DECISION-PENDING-LA rows (#12, #27, #37, #41, plus IR-9 and IR-10 follow-on questions) must precede EA-2 / EA-3 dispatch."* Continuation `P5_TASK10_SDO_CONTINUATION_v1.0.xml` step 8 reinforces: *"DECISION-PENDING-LA rows escalate to Co-Lead at Phase 1b before SDO authors EA-2 / EA-3 — Co-Lead may decide directly or push to LA via Gate:Pending-Human."*

Co-Lead's Phase 1b ESCALATE (`docs/sprints/sprint_10/reports/20260511_192347_co_lead_completion-review_v1.md`) addressed only the `trusted_scope` LOC carve-out — not the 6 row-level partition decisions. LA's `la_merge_approve` accepted the matrix as a document; row-level adjudication remains open. SDO will not author EA-2 until LA decides.

## The 6 questions and SDO recommended dispositions

### Row #12 — `CLAUDE.md` `### Human pointer` (ACTIVE_SPRINT.md descriptor)

- **Lines (BlarAI `CLAUDE.md`)**: 139–141.
- **Matrix provisional partition**: MOVE-devplatform.
- **Question**: move descriptive doctrine to devplatform (file itself stays in BlarAI), or keep in BlarAI for navigational convenience?
- **SDO recommendation**: **MOVE-devplatform**. The file `docs/sprints/ACTIVE_SPRINT.md` stays in BlarAI per SDV §5.3 explicit; the *doctrine describing it* is fleet-lifecycle (audience: agents who need DEC-15 sprint lifecycle context). BlarAI side gets one-line pointer per §5.3 style: `*See also: C:\Users\mrbla\devplatform\CLAUDE.md §Current-Active-Sprint.*`

### Row #27 — `.github/copilot-instructions.md` `<user_identity>`

- **Lines**: 9–14.
- **Matrix provisional partition**: MIRROR-both.
- **Question**: MIRROR-both (LA identity present in both surfaces), or MOVE-devplatform with BlarAI cross-reference (fleet-operator framing)?
- **SDO recommendation**: **MIRROR-both**. LA identity applies symmetrically to interactive BlarAI sessions and fleet sessions. Mature-not-minimal floor (≥100 lines for devplatform doctrine) is easier to satisfy when foundational context like LA identity is present in each surface. Per SDV §5.3, each post-split file is *"a coherent operational reference in its own right"*; an agent reading devplatform doctrine cold should not need a cross-repo lookup for LA identity context.

### Row #37 — `.github/copilot-instructions.md` `<vikunja_task_tracking>` envelope

- **Lines**: 236–257.
- **Matrix provisional partition**: MIRROR-both.
- **Question**: (A) Split envelope — BlarAI keeps `<labels>` + `<conventions>`; devplatform authors `<sdo_responsibilities>` + `<ea_responsibilities>`. (B) MOVE whole envelope to devplatform; BlarAI `CLAUDE.md` Vikunja Conventions section (row #6 KEEP-BlarAI) already covers LA-facing label/convention content.
- **SDO recommendation**: **option (A) — split envelope**. Aligns with SDV §5.3 dispositive test (*"would this section make sense to read while using Vikunja interactively from Claude Desktop in BlarAI? If yes, KEEP; if it only makes sense to a sandbox agent or a fleet operator, MOVE."*). Labels + conventions answer YES for the LA's interactive UI; SDO/EA responsibilities answer NO (purely fleet operating model). Single canonical label-id table lives in BlarAI's `CLAUDE.md` row #6; both XML envelopes cross-reference it rather than duplicating numeric IDs.

### Row #41 — `AGENTS.md` "Non-Claude coding agents reading this file" pointer block (BlarAI side)

- **Lines**: 5–11.
- **Matrix provisional partition**: KEEP-BlarAI.
- **Question**: what level of pointer detail post-split? (a) Bare pointer to BlarAI's `CLAUDE.md` + `.github/copilot-instructions.md`. (b) Brief pointer with one-line agent-role classification (which agent reads which repo). (c) Elaborate enumeration.
- **SDO recommendation**: **(b) — brief pointer with one-line agent-role classification**. Approximate length 5–8 lines. Pattern: *"Claude Code / Copilot for BlarAI runtime work → `C:\Users\mrbla\BlarAI\CLAUDE.md` (this repo). Codex / Cowork sandbox agents for fleet-infrastructure work → `C:\Users\mrbla\devplatform\CLAUDE.md`."* Preserves the "thin pointer stub" identity per SDV §5.3 while reflecting post-split topology accurately.

### IR-9 — `<security_and_workflow_constraints>` split-element well-formedness

- **Source rows**: #35 (envelope KEEP-BlarAI) + #35e (`<fleet_pause_sop>` MOVE-devplatform).
- **Question**: how to encode XML well-formedness when envelope stays in BlarAI but one child moves to devplatform?
- **SDO recommendation**: BlarAI's envelope retains a placeholder child named `<fleet_pause_sop_pointer>` (distinct element name to avoid grep collision with devplatform's authoritative `<fleet_pause_sop>`). Body of the BlarAI pointer element is a single italicized cross-reference line per §5.3. devplatform authors the full `<fleet_pause_sop>` inside its own `<security_and_workflow_constraints>` envelope. This is technical implementation — SDO will encode in EA-2 + EA-3 prompts; surfacing for LA visibility only.

### IR-10 — `<vikunja_task_tracking>` envelope split (follow-on from row #37)

- **Question**: determined by row #37 resolution.
- **SDO recommendation**: follows row #37 disposition. If LA picks (A), both repos carry split envelopes per row #37 disposition above. If (B), envelope MOVEs wholesale to devplatform with BlarAI cross-reference to row #6 `CLAUDE.md` Vikunja Conventions.

## What LA decides

- **APPROVE-ALL** (recommended): SDO encodes all 6 dispositions above into the EA-2 prompt (and EA-3 prompt where applicable) and proceeds to Phase 2 authoring on next firing.
- **APPROVE-WITH-EDITS**: LA notes specific row(s) with alternate disposition; SDO encodes the LA-decided outcome in the EA prompts.
- **DEFER**: SDO holds EA-2 authoring; LA returns to this question later.

## Gate transition

- Remove `Gate:Approved` (id 12) from tracking task #369 (applied by `la_merge_approve.ps1` post-EA-1 merge — no longer accurate now that LA action is required).
- Apply `Gate:Pending-Human` (id 11) on tracking task #369.

## Downstream wake trigger

None fired. LA action is required; no fleet agent is the next mover. The 15-min cron will not produce no-op SDO firings while the task carries `Gate:Pending-Human` (per Phase -1 fleet-blocked exit rule).

---
Fleet Reports task: 388
Vikunja source comment: task #369 comment #520
