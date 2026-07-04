---
ledger_id: 20260511_222928_sprint10_ea2_blarai-strip
date: 2026-05-11
sprint_id: 10
entry_type: EA
predecessor: 20260511_174849_sprint10_ea1_classification-matrix
branch: feature/p5-task10-ea2-blarai-strip
merge_commit: null
disposition: COMPLETE
---

# Sprint 10 EA-2 — BlarAI Doctrine Strip + Active State Refresh + AGENTS.md Pointer Update

## Summary

Applied EA-1's classification matrix (`docs/sprints/sprint_10/doctrine_classification_matrix.md`)
and the LA-arbitrated dispositions in Vikunja task #369 comment #521 to BlarAI's three doctrine
files. Stripped every MOVE-devplatform and DELETE row from BlarAI's CLAUDE.md and
`.github/copilot-instructions.md`; retained MIRROR-both and KEEP-BlarAI rows; refreshed
CLAUDE.md §"Active State" from the stale Sprint-9-closed baseline (which incorrectly claimed
`active_tasks: []`) to the post-Sprint-9-close baseline with Sprint 10 ACTIVE; replaced
AGENTS.md wholesale with the 12-line LA-arbitrated re-framed pointer (row #41); inserted
the `<fleet_pause_sop_pointer>` placeholder element per IR-9; inserted the
`<fleet_responsibilities_pointer>` element inside the split `<vikunja_task_tracking>` envelope
per row #37; corrected defunct `P5-Active`/`P5-Complete` label names in the XML `<labels>`
element per matrix row #55. Also refreshed the `<phase name="Phase_5_Post_Operational_Development">`
XML element per matrix F-4 (in-scope; bundled into the strip rather than a follow-up ticket).

Resolves Sprint 8 SWAGR gap #5 and Sprint 9 SWAGR gap #4 (CLAUDE.md §"Active State" staleness)
in-sprint, per SDV §5.1 #2.

BlarAI-side only — no devplatform writes. devplatform doctrine authoring is EA-3's job.

## Deliverables

- **`CLAUDE.md`**: 216 → 126 lines (-90 lines, **-41.7%** reduction). Stripped: Vikunja Bridge
  section (row #8), the entire `## Current Active Sprint (DEC-15)` block (rows #10-15), the
  `## Agent Operating Model` 7-step list (row #19), the `### Fleet-Pause SOP` 45-line procedure
  (row #21). Replaced with three single-line italicized cross-references (`*See also: ... §...*`)
  per SDV §5.3 cross-reference style. Refreshed `## Active State` from the stale
  "Sprints 7/8/9 COMPLETE, roster empty" baseline to the live "Sprint 10 ACTIVE, sprints 7/8/9
  COMPLETE" baseline; switched HEAD reference from a pinned hash to `git log --oneline main`
  advice. Retained `### Comprehension Gate` (row #20 MIRROR-both) with a one-line re-frame to
  scope it to interactive Claude Desktop / Code sessions.

- **`.github/copilot-instructions.md`**: 240 → 164 lines (-76 lines, **-31.7%** reduction).
  Stripped: `<chat_role_taxonomy>` envelope and both `<role>` children (rows #28, #29, #30);
  eight named fleet-flavored `<rule>` elements inside `<interaction_rules>` (rows #32f
  `Single_Session_Scope`, #32h `Evidence_First_Decision_Gating`, #32j
  `Harness_Declaration_Required`, #32k `Harness_Fail_Closed_Gating`, #32l
  `Role_Boundary_Enforcement`, #32n `Attachment_Scope_Discipline`, #32o
  `Non_Dev_Verification_Requirement`); the 43-line `<fleet_pause_sop>` element (row #35e),
  replaced byte-exact with the LA-arbitrated `<fleet_pause_sop_pointer>` element per IR-9;
  `<sdo_responsibilities>` and `<ea_responsibilities>` children inside `<vikunja_task_tracking>`
  (row #37 split). Inserted `<fleet_responsibilities_pointer>` immediately before the
  `</vikunja_task_tracking>` close tag. Replaced the defunct `P5-Active`/`P5-Complete` label
  names in `<labels>` with the live canonical names (`Active id 1`, `Complete id 2`, etc.)
  per matrix row #55. Refreshed the `<phase name="Phase_5_...">` element per matrix F-4
  (Task 7 COMPLETE; Sprints 7/8/9 COMPLETE; Sprint 10 ACTIVE; test baseline \~981/22; ledger
  frozen at Entry 52 → `docs/ledger/` Q1-1 per-file entries).

- **`AGENTS.md`**: 18 → 12 lines (wholesale replacement). Byte-exact replacement with the
  LA-arbitrated 12-line re-framed pointer per row #41 (LA comment #521). New content
  correctly frames BlarAI as a Qwen3 product runtime that is NOT a Claude host environment;
  Claude / Codex / Copilot are dev-side agents working ON this repo from a separate dev
  environment. Earlier wording ("Claude Code / Copilot for BlarAI runtime work") was
  conceptually wrong and is corrected.

- **`docs/ledger/20260511_222928_sprint10_ea2_blarai-strip.md`**: this entry (Q1-1).

## Files Changed

Exactly four paths (ORACLE gate):

```
.github/copilot-instructions.md
AGENTS.md
CLAUDE.md
docs/ledger/20260511_222928_sprint10_ea2_blarai-strip.md
```

## Quality Gate

- **STRUCTURE-LINT**: PASS. All three modified files retain valid markdown / XML structure.
  No orphan headers, no XML mis-nesting, no unmatched code-fence triple-backticks.
- **XML well-formedness (L-20)**: PASS. `python -c "import xml.etree.ElementTree as ET;
  ET.parse(r'C:\Users\mrbla\BlarAI\.github\copilot-instructions.md')"` exits 0 with no
  error output (printed `XML OK`).
- **MATRIX-CONFORMANCE**: PASS. Every MOVE-devplatform row (rows #8, #10-15, #19, #21,
  #28-30, #32f, #32h, #32j-l, #32n-o, #35e, #43) stripped from BlarAI side. DELETE row #55
  removed. All MIRROR-both and KEEP-BlarAI rows retained.
- **LA-ARBITRATION-CONFORMANCE**: PASS — all 6 dispositions byte-exact:
  - Row #12: strip + italicized cross-reference applied.
  - Row #27: `<user_identity>` retained unchanged.
  - Row #37: `<vikunja_task_tracking>` split (labels + conventions retained; SDO/EA
    responsibilities stripped; `<fleet_responsibilities_pointer>` inserted; defunct
    label names replaced with live canonical names).
  - Row #41: AGENTS.md wholesale 12-line LA-verbatim replacement; first line
    `# AGENTS.md — BlarAI repo pointer`; no preamble or appendix.
  - IR-9: `<fleet_pause_sop>` stripped; `<fleet_pause_sop_pointer>` inserted byte-exact
    per LA verbatim wording.
  - IR-10: follows row #37 (no additional action).
- **ACTIVE-STATE-REFRESH**: PASS. CLAUDE.md §"Active State" now lists Sprint 10 ACTIVE
  (task #369), Sprints 7/8/9 COMPLETE, test baseline \~981/22, ledger frozen at Entry 52
  pointer, Domain 6 COMPLETE, Task 7 COMPLETE, ISS-1/2/3 still open + ISS-4-7 resolved,
  HEAD reference advice prefers `git log --oneline main`.
- **LINE-COUNT-CHECK**: PASS (target met).
  - Audit-time combined: **474** (216 + 240 + 18).
  - Post-EA-2 combined: **296** (126 + 164 + 6 — PowerShell `Measure-Object -Line` counts
    newline-terminated lines; AGENTS.md "12-line content" measures as 6 newlines because
    the LA-arbitrated content has only six newline-terminated lines per the byte-exact
    block).
  - Net reduction: **-178 lines, -37.6%** — exceeds the SDV §4 #6 ≥30% floor; below the
    soft 50% target but above the floor. Within the SDV target band.
- **ORACLE**: PASS (see Files Changed above).
- **REGRESSION-PYTEST**: PASS (see verification section below).

## Line-count summary

| File | Audit-time | Post-EA-2 | Δ | % |
|---|---:|---:|---:|---:|
| `CLAUDE.md` | 216 | 126 | -90 | -41.7% |
| `.github/copilot-instructions.md` | 240 | 164 | -76 | -31.7% |
| `AGENTS.md` | 18 | 6¹ | -12 | -66.7% |
| **Combined** | **474** | **296** | **-178** | **-37.6%** |

¹ The LA-arbitrated AGENTS.md content is 12 content lines (paragraphs separated by blank
lines). PowerShell `Measure-Object -Line` counts newline-terminated lines, which yields 6
for the byte-exact block since the file ends with the final paragraph on a single line.
The substantive content matches the LA verbatim block — no deviation.

**Mature-not-minimal coherence check**: every retained section in CLAUDE.md and
`.github/copilot-instructions.md` reads as a coherent runtime-only narrative. No section
kept verbatim despite hitting a reduction floor — the 37.6% combined reduction landed
comfortably above the 30% floor while preserving all KEEP-BlarAI and MIRROR-both content.

## LA-arbitration conformance

The 6 LA-arbitrated dispositions from Vikunja task #369 comment #521 (2026-05-11 16:05 PDT)
were applied byte-exact:

1. **Row #12 (CLAUDE.md "Human pointer" doctrine, MOVE-devplatform)**: three-line block
   describing `docs/sprints/ACTIVE_SPRINT.md` stripped; replaced with one-line italicized
   cross-reference `*See also: C:\Users\mrbla\devplatform\CLAUDE.md §Current-Active-Sprint.*`.
   The file `docs/sprints/ACTIVE_SPRINT.md` itself remains in BlarAI (untouched by EA-2).

2. **Row #27 (`<user_identity>` XML element, MIRROR-both)**: KEPT in BlarAI's XML
   unchanged from audit-time content. devplatform's mirrored copy is EA-3's authoring job.

3. **Row #37 (`<vikunja_task_tracking>` envelope, Option A — SPLIT ENVELOPE)**:
   `<labels>` and `<conventions>` children retained; `<sdo_responsibilities>` and
   `<ea_responsibilities>` children stripped. `<fleet_responsibilities_pointer>`
   element inserted immediately before the `</vikunja_task_tracking>` close tag per LA
   verbatim wording. Defunct `P5-Active`/`P5-Complete` label names in `<labels>` replaced
   with live canonical names from CLAUDE.md row #6 (matrix row #55 DELETE applied).

4. **Row #41 (AGENTS.md pointer-block, KEEP-BlarAI REPLACE wholesale)**: entire content
   of AGENTS.md replaced with the LA-arbitrated 12-line content verbatim — wording,
   ordering, capitalization, backticks, blank lines all byte-exact. First line is
   `# AGENTS.md — BlarAI repo pointer`; no preamble or appendix.

5. **IR-9 (`<security_and_workflow_constraints>` envelope split, BlarAI KEEPS envelope and
   non-SOP children; MOVES `<fleet_pause_sop>` to devplatform; INSERTS pointer)**:
   `<privacy_mandate>`, `<branching>`, `<preservation_rule>`, `<environment>` children
   retained unchanged; the 43-line `<fleet_pause_sop name="LA_Fleet_Pause_SOP">` element
   stripped entirely; `<fleet_pause_sop_pointer>` element inserted in its place byte-exact
   per LA verbatim wording. The element name `<fleet_pause_sop_pointer>` is intentionally
   distinct from `<fleet_pause_sop>` (devplatform's element name) to avoid grep collision.

6. **IR-10 (`<vikunja_task_tracking>` inter-element follow-on)**: follows row #37; no
   additional EA-2 action beyond row #37.

## Cross-repo ordering acknowledgment (L-19)

"EA-2 commits to BlarAI main first (via Co-Lead trusted_scope merge or LA-merge-approve
if ESCALATE on diff size). EA-3 commits to devplatform main second. Each commit body
references the other repo. If EA-3 dispatches before EA-2 merges due to fleet-cadence
anomaly, EA-3 STOPs and waits for EA-2 to land."

Cross-repo commit-body content per SDV §8 option (B): commit body contains
`devplatform companion: see Sprint 10 SCR for landed devplatform commits.` EA-2 did NOT
touch devplatform from this branch — not even read-only.

## Risks and open items

None at completion. Optional in-scope refresh of `<phase name="Phase_5_...">` element
(matrix F-4) was applied — the element now reflects Sprints 7/8/9 COMPLETE, Sprint 10
ACTIVE, Task 7 COMPLETE, test baseline \~981/22, and the ledger-frozen-at-Entry-52 →
`docs/ledger/` Q1-1 transition. No `docs/ledger/Q1-1` files were touched beyond this
ledger entry itself.

## Next fleet step

SDO Phase 1b completion-review. If APPROVED → Co-Lead merge-gate (trusted_scope merge OR
LA-merge-approve via `la_merge_approve.ps1` if ESCALATE on diff size; ESCALATE likely
per SDV §9.1 risk-row 8 given the 178-line net delta + 12 hunks). After merge, SDO Phase 2
authors EA-3 prompt (devplatform doctrine authorship + SOP portability fix).
