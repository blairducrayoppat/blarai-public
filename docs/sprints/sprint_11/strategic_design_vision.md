---
# Strategic Design Vision (SDV) — BlarAI Sprint 11
#
# Authored interactively by Co-Lead Architect + Lead Architect at sprint start.
# Baseline against which the end-of-sprint SCR (Strategic Completion Report) and
# SWAGR (Strategic Work Analysis & Gap Report) measure success and gap.
---
sprint_id: 11
sprint_name: "Process-Hygiene Backlog Paydown"
predecessor_sprint_id: 10
vikunja_tracking_task_id: 410
start_date: "2026-05-11"
target_completion_date: "open — no hard deadline; ~3-5 fleet days from unpause per LA mature-not-minimal motto"
la_approved_on: "2026-05-11T21:00:00-05:00"
la_approved_by: "blarai"
co_lead_drafted_on: "2026-05-11T20:30:00-05:00"
co_lead_commit_when_drafted: "44f5f8c"
sdv_version: 3
---

# Strategic Design Vision — Sprint 11: Process-Hygiene Backlog Paydown

## 1. Executive brief

Sprint 11 clears the three-sprint backlog of process-hygiene carry-overs that Sprint
8, Sprint 9, and Sprint 10 SWAGRs (Strategic Work Analysis & Gap Reports) each
recommended and each deferred. Five workstreams ship concrete artifacts: (1) a
DEC (Decision) bundle authoring three formal numbered decisions — parallel-sprint
authorization, ledger-format Q1-1 permanence, and trusted_scope LOC (lines of
code) threshold — that record decisions whose substance already lives in
governance docs but lacks the numbered-DEC record the fleet repeatedly references;
(2) a deterministic Active State refresh procedure that replaces the
"copy-paste from prior text" pattern with live computation (live pytest +
live `git log` + live Vikunja sprint state), wired into the Co-Lead Phase 3
sprint-transition hook; (3) SWAGR template amendment adding a §5.4 cross-repo
ghost-commit sweep subsection (Sprint 9 SWAGR predicted; Sprint 10 SWAGR
confirmed); (4) a real test-baseline drift investigation root-causing the +20
pass / -20 skip movement at `90db41f` that occurred without any Sprint 9/10
test-file touches, including a fail-closed safety review and a Sprint 12+
baseline-string recommendation; (5) a cleanup batch closing Sprint 10's six
MINOR doctrine gaps (`copilot-instructions.md:93` narrative DEC-15 reference,
cross-reference style asymmetry between BlarAI and devplatform, vikunja_mcp
README Quick Start stale `cd` reference, Sprint Auditor wake-template allowance
for sprint-close-only Vikunja comment read).

Sprint 11 runs **serial** — Sprint 10 closed 2026-05-11 (SCR `90db41f`, SWAGR
`14ac80d`), Sprint 11 is the first sprint after that close, and cf-1 (DevPlatform
Cloud-Fleet Redesign Foundation, Vikunja #368) remains chartered but dormant.
Sprint 11 is also the **second consecutive cross-repo sprint** and the first
deliberately so — it writes to BOTH BlarAI main (EA-3 templates, EA-4
investigation report, EA-5 BlarAI side of cleanup) AND devplatform main (EA-1
DEC documents, EA-2 wake-template hook, EA-5 devplatform side of Sprint Auditor
wake template amendment). This exercises the very cross-repo SWAGR-template
amendment that EA-3 itself ships, which is intentional: Sprint 11's own audit
becomes the first test of the new cross-repo sweep section.

The guiding principle is **mature not minimal** per LA standing direction. Each
closure produces a substantive artifact — DEC documents are ≥ 60 lines of
motivation + decision text + alternatives considered, the Active State refresh
procedure is a runnable artifact (procedure file + hook + helper script if
applicable), the test-drift investigation produces a verification matrix with
per-test breakdown, and the doctrine-defect fixes are not one-line patches but
include rationale + cross-reference-style decision text. A "TODO closed" line
in a tracking doc is **not** a Sprint 11 deliverable; a real document, code
change, or governance record is.

Done = (a) three DEC files on devplatform main, formally numbered, each
referencing the existing governance doc + the SWAGR carry-over chain that
motivated it; (b) one procedure file on BlarAI main + one wake-template hook
on devplatform main implementing deterministic Active State refresh; (c) SWAGR
template (+ SDV template if symmetric) §5.4 cross-repo subsection landed on
BlarAI main; (d) one investigation report on BlarAI main with bisect log +
fail-closed verification + baseline recommendation; (e) cleanup batch landing
file edits across BlarAI + devplatform with the cross-reference style decision
recorded; (f) Sprint 10's six MINOR SWAGR gaps verified CLOSED in the Sprint 11
SCR with merge-commit cross-references.

## 2. Context

### 2.1 Predecessor sprint outcome

- **Predecessor SCR**: [docs/sprints/sprint_10/strategic_completion_report.md](../sprint_10/strategic_completion_report.md)
- **Predecessor SWAGR**: [docs/sprints/sprint_10/Strategic_Work_Analysis_and_Gap_Report_Sprint_10_20260511_171900.md](../sprint_10/Strategic_Work_Analysis_and_Gap_Report_Sprint_10_20260511_171900.md)

Sprint 10 (Doctrine Split) delivered all 10 in-scope deliverables across three
strictly-serial EAs (Execution Agents). 7/7 SDV success criteria passed on
independent audit. BlarAI doctrine reduced 40.4% (572 → 341 lines); devplatform
got a fresh 633-line doctrine substrate; the `from tools.autonomy_budget import
state` import portability bug was fixed via a standalone CLI script
(`tools/autonomy_budget/cli.py`, option (c)). The verdict was
`ACCEPTABLE_ALIGNMENT` / `INCREMENTAL` / `IMPROVED`, **0 CRITICAL / 0 MAJOR / 6
MINOR**. Two recurring MAJOR patterns from Sprint 8/9 SWAGRs were broken:
ledger-discontinuity (Sprint 10 EA-1 incidentally landed in Q1-1 per-file)
and CLAUDE.md §"Active State" text staleness (Sprint 10 EA-2 explicitly
refreshed per criterion #5).

Sprint 11 picks up **every** Sprint 10 MINOR gap and **all** the long-pending
micro-DEC carry-overs from Sprint 8 + Sprint 9 + Sprint 10 SWAGRs. This is by
LA design — the three-sprint pattern is established, the fleet has been
operating on the workarounds (`la_merge_approve.ps1`, ad-hoc Active State
edits, sprint-close-comment-not-audited) cleanly enough that the formal records
can now be authored against three data points rather than one. The Sprint 9
SWAGR's "advance one UC (Use Case)" recommendation and the Sprint 10 SWAGR's
sharpened recommendation "Sprint cf-1+1 should be UC-advancement" are both
**deferred to post-cf-1** per the LA's sequencing — Sprint 11 closes
process-hygiene debt first so cf-1 inherits a clean slate.

### 2.2 Repo state at kickoff

- **BlarAI main HEAD**: `44f5f8c` — `[agent:co_lead] archive EA queue prompt
  after merge -- Sprint 10 EA-3 (direct-to-main ledger commit 4b2dfa0)`. Sprint
  10 closure chain: SCR `90db41f`, SWAGR `14ac80d`, archive cleanup `44f5f8c`.
- **devplatform main HEAD**: `9e5555c` — `[sprint:10][role:ea_code][phase:completion]
  EA-3 devplatform doctrine authorship + SOP portability fix`. No devplatform
  commits since Sprint 10 EA-3 close.
- **Most recent ledger entries** (under `docs/ledger/`, Q1-1 format):
  - `20260511_233902_sprint10_ea3_devplatform-doctrine-authorship.md`
  - `20260511_222928_sprint10_ea2_blarai-strip.md`
  - `20260511_174849_sprint10_ea1_classification-matrix.md`

  The monolithic `docs/POST_OPERATIONAL_MATURATION_LEDGER.md` remains frozen
  at Entry 52 per Sprint 8 SWAGR. All Sprint 10 entries landed in `docs/ledger/`
  per-file Q1-1 format — incidentally breaking the recurring discontinuity
  pattern; Sprint 11 EA-1 will formalize this as a permanent rule via DEC-17.
- **Open Vikunja `Gate:Pending-Human` gates on Project 6 (Agent Gates bus)**:
  one stale entry (#398 — duplicate of #397, both EA-2 escalations from Sprint
  10; #397 closed Approved, #398 left open). Not a Sprint 11 blocker; will be
  swept during EA-5 cleanup batch or as routine triage. **Open
  `Gate:Pending-CoLead` gates**: 0.
- **Active feature branches on BlarAI**: none. devplatform: convention is
  direct-to-main per Stage 6.7.5; no convention deviation expected this sprint.
- **Fleet-pause state**: UNPAUSED (most recent `chore(ops)` is `290a2f4`
  "unpause fleet -- Sprint 10 EA-3 done"). Sprint 11 kickoff will pause the
  fleet before substantive git work per fleet-hygiene §4, then unpause after
  the Phase 4 commit chain lands.
- **Active task roster** (`docs/active_tasks.yaml`): **STALE** — still shows
  `task_id: 369, sprint_id: 10` even though Sprint 10's SCR + SWAGR have
  landed. This staleness is itself the exact failure mode EA-2 codifies a fix
  for. The Phase 4 transition step in this kickoff will mark Sprint 10
  complete and add Sprint 11's roster entry, producing the first live data
  point for the deterministic procedure EA-2 will author.
- **Vikunja Sprint 11 tracking task**: #410 (created during Phase 2 of this
  kickoff session; `Gate:Pending-Human` until Phase 4 sign-off).

### 2.3 External inputs driving this sprint

- **LA directive 2026-05-11 (this kickoff session)**: bundle the 3-sprint
  SWAGR micro-DEC carry-overs (parallel-sprint authorization, ledger-format
  permanence, trusted_scope LOC threshold), codify deterministic Active State
  refresh, amend SWAGR template for cross-repo, investigate test-baseline
  drift, close Sprint 10 MINOR doctrine defects (copilot-instructions.md:93 +
  cross-reference style asymmetry), make post-freeze per-file ledger rule
  permanent, and clear small Stage 6.7.5 doc-hygiene items (vikunja_mcp README
  Quick Start, Sprint Auditor sprint-close-comment read-only sweep).
  **Mature-not-minimal**: each closure is a real artifact, not a marker.

- **Sprint 10 SWAGR §14 recommendations** (six items, all in Sprint 11 scope):

  | SWAGR § | Rec | Mapped Sprint 11 EA |
  |---|---|---|
  | §14 #1 | Codify deterministic Active State refresh | EA-2 |
  | §14 #2 | One-line cleanup of `copilot-instructions.md:93` | EA-5 |
  | §14 #3 | Investigate +20 pass / -20 skip drift | EA-4 |
  | §14 #4 | SWAGR template amendment for cross-repo sprints | EA-3 |
  | §14 #5 | Resolve cross-reference style asymmetry call | EA-5 |
  | §14 #6 | Land parallel-sprint / ledger-format / trusted_scope micro-DEC bundle | EA-1 |

  Sprint 10 SWAGR §14 #7 (UC-advancement after cf-1) is deferred per LA
  sequencing decision; not in Sprint 11 scope.

- **Sprint 8 + Sprint 9 SWAGR carry-overs** consolidated into EA-1's DEC
  bundle:

  | Source | Item | Maps to |
  |---|---|---|
  | Sprint 8 SWAGR §14.1 | parallel-sprint shared-artifact DEC | DEC-16 |
  | Sprint 9 SWAGR gap #7 | parallel-sprint shared-artifact DEC (reaffirmed) | DEC-16 |
  | Sprint 8 SWAGR gap #1 (MAJOR-recurring) | ledger-format Q1-1 standing DEC | DEC-17 |
  | Sprint 9 SWAGR gap #1 (MAJOR-recurring) | ledger-format Q1-1 standing DEC (reaffirmed) | DEC-17 |
  | Sprint 10 SWAGR §15.3 | post-freeze per-file ledger rule made permanent | DEC-17 (subsumed) |
  | Sprint 8 SWAGR §14.1 | `trusted_scope` LOC-threshold DEC | DEC-18 |

- **Stage 6.7.5 backlog items** (from Stage 6 FINAL close report; carried
  through Sprint 10 §5.2 #10):
  - `tools/vikunja_mcp/README.md` Quick Start stale `cd` reference → EA-5
  - Sprint Auditor allowed sprint-close-only Vikunja comment read → EA-5
    (devplatform side: amend `docs/scheduled/wake_templates/sprint_auditor.md`
    §2.2 deliberate-exclusion language)
  - Vikunja project rationalization (UU #316) — NOT in Sprint 11 scope; remains
    Stage 6.7.5 backlog.

- **cf-1 charter** (Vikunja Project 10 task #368): chartered but dormant per
  LA. cf-1 begins after Sprint 11 closes. Sprint 11's templates + DECs land
  the cf-1 boundary in a fully-codified-process posture.

- **Sprint 11 LA decisions in this kickoff session (2026-05-11)**:
  - Sprint name: "Process-Hygiene Backlog Paydown" (LA-named, session also
    labeled "Sprint 11 Governance Debt" — same sprint).
  - Coordination: serial (cf-1 dormant; Sprint 10 closed before Sprint 11
    starts).
  - Execution: 5-EA fleet-driven (EA-1 DEC bundle / EA-2 procedure / EA-3
    templates / EA-4 investigation / EA-5 cleanup batch). Strictly serial
    within Sprint 11.
  - Cross-repo: yes — second consecutive, first deliberately so.
  - Mature-not-minimal: explicit LA directive that each closure must produce
    a substantive artifact, not a marker.

## 3. Sprint purpose

The three-sprint SWAGR backlog is now load-bearing technical debt of a
peculiar kind: the substance of every micro-DEC is already implemented and
operational (parallel-sprints work via `set_parallel_sprints_authorized`;
the Q1-1 ledger format is the de facto convention; `la_merge_approve.ps1`
handles every `trusted_scope` escalation), but the numbered-DEC record is
absent. The fleet repeatedly references "DEC-11", "DEC-14.5", "DEC-15" — but
no comparable numbered record exists for the three decisions that have been
de-facto-active for three sprints. This is a documentation-credibility debt:
every sprint that operates on these patterns without a formal record makes
the next sprint's auditor reach for the same SWAGR carry-over recommendation.
Sprint 11's EA-1 closes the loop. Three formal DECs (DEC-16 parallel-sprint
authorization, DEC-17 ledger-format Q1-1 permanence, DEC-18 trusted_scope LOC
threshold) land on devplatform main with motivation text, decision text,
alternatives considered, and cross-references to the existing governance docs
(`parallel-sprints.md`, `ledger/README.md`, `merge-policy.md`) that contain
the operational mechanics. This is **DEC governance hygiene**, not new policy.

The Active State staleness pattern is the most LA-facing of the gaps. Sprint 8
SWAGR gap #5, Sprint 9 SWAGR gap #4, and Sprint 10 SWAGR §15.3 each flagged
the same recurring shape: `CLAUDE.md` §"Active State" text is faithful to a
prior-text copy but drifts behind live state (HEAD reference, test baseline
numbers, sprint roster). Sprint 10 EA-2 explicitly refreshed the text against
SDV criterion #5 — and within the same sprint window the baseline drifted
from `~981 passed, 22 skipped` to `1001 passed, 2 skipped`. Refreshing-from-
prior-text is structurally unable to keep up with live state. EA-2's
deterministic procedure flips the polarity: every Active State refresh begins
with live computation (live `pytest shared/ services/ launcher/`, live
`git log --oneline -1 main`, live Vikunja `list_tasks` on the sprint project
for the sprint roster, live `docs/active_tasks.yaml` read), then writes the
result. The procedure is wired into the Co-Lead Phase 3 sprint-transition
hook (which is where Sprint 11's kickoff session is happening right now — the
absence of automation here is the immediate concrete symptom: `active_tasks.yaml`
still shows `task_id: 369` because no procedure ran). EA-2's deliverable
includes the procedure file (mature-not-minimal: not a one-paragraph stub but
a runnable artifact, possibly with a helper script) AND the wake-template hook
that invokes it on every sprint kickoff.

The SWAGR template cross-repo amendment is a concrete prediction-confirmation
loop closure. Sprint 9 SWAGR §9.3(d) predicted "the eventual first
cross-repo sprint would surface a template gap"; Sprint 10 became that sprint
and confirmed via §5.4 "Cross-repo ghost-commit sweep" subsection authored by
the Sprint Auditor manually (out of template). Sprint 11 EA-3 amends the
canonical SWAGR template at `docs/sprints/_templates/strategic_work_analysis_and_gap_report_template.md`
to add a §5.4 cross-repo subsection that auditors fill in when the sprint
window includes commits on a second repo. EA-3 also fixes the SDV template
§8.4 broken pointer (`docs/governance/parallel-sprints.md` referenced as
BlarAI-relative; the file now lives in devplatform per Sprint 10 doctrine
split). Sprint 11 is itself cross-repo, so its own SWAGR (authored Sprint
12 cadence) will be the first to exercise the new template subsection —
satisfying the SWAGR "eat your own cooking" principle.

The test-baseline drift investigation matters precisely because it's the kind
of finding that compounds silently. +20 pass / -20 skip is benign on the surface
(more tests running, fewer skipped — direction is upward), but the drift
occurred outside any sprint's working set, meaning the cause is environment,
pytest configuration, marker resolution, or a CI-not-fleet-attributable
condition. If it's benign, the recommendation is to update the SDV-anchored
baseline string. If it's a silent fail-closed regression masked by skip-pattern
churn, that's a CRITICAL-class finding that the fleet's normal cadence would
not have surfaced — sprints don't audit drifts they didn't cause. EA-4 produces
a real investigation report: bisect the +20/-20 to a commit window or
configuration change; enumerate every fail-closed-adjacent test among the 20
newly-running cases; verify none weakened or removed; recommend a Sprint 12+
baseline-string update. **Mature-not-minimal** explicitly applies here — a
one-line "drift is benign, update the number" is not a Sprint 11 deliverable.

If Sprint 11 is skipped: the three-sprint micro-DEC carry-overs continue to
appear on every SWAGR's recommendation list, eroding the auditor's ability
to identify new issues; Active State staleness continues to recur each
sprint with the LA having to manually request refreshes; cross-repo sweeps
in cf-1 (which is going to be cross-repo by design — devplatform fleet
redesign with BlarAI doctrine touchpoints) lack template support; the
test-baseline drift compounds for another sprint, making future drifts
harder to root-cause; and Sprint 10's six MINOR gaps remain as audit
findings on the running tally. cf-1 inherits all of this. The strategic
leverage of Sprint 11 is at the cf-1 boundary — cf-1 has hard work to do
(redesigning the fleet) and benefits from a fully-codified
process substrate it doesn't have to fix in-flight.

## 4. Success criteria

1. **DEC bundle on devplatform main.** *Verification*: three files exist on
   devplatform main with names of the form `docs/decisions/DEC-16_*.md`,
   `docs/decisions/DEC-17_*.md`, `docs/decisions/DEC-18_*.md` (or the bundled
   equivalent at the chosen canonical location; final path is EA-1's choice
   within the SDV §5.3 boundary call); each ≥ 60 lines of substantive content
   (mature-not-minimal floor for a DEC); each file contains: §Motivation
   (cite the SWAGR gap chain), §Decision (one-paragraph plain statement of
   what is decided), §Alternatives considered (≥ 2), §Cross-references
   (existing governance doc + ledger + SDV/SCR/SWAGR entries that informed
   it). Commit subject tag `[sprint:11][role:ea_code]` on devplatform main.

2. **Deterministic Active State refresh procedure delivered + integrated.**
   *Verification*: (a) a procedure file exists on BlarAI main at
   `docs/runbooks/active_state_refresh.md` (or equivalent) describing the
   live-computation steps in order (pytest baseline, git HEAD, Vikunja sprint
   state, roster YAML read, write back to CLAUDE.md §"Active State"); ≥ 50
   lines, mature-not-minimal; (b) a hook lands on devplatform main amending
   the Co-Lead wake template (`docs/scheduled/wake_templates/co_lead_architect.md`)
   to reference the procedure at sprint-transition events; (c) BlarAI CLAUDE.md
   §"Active State" at Sprint 11 SCR commit reflects live-computed state
   (test baseline reads live pytest output at SCR commit, not the
   `~981 passed, 22 skipped` SDV-anchored Sprint 8 string).

3. **SWAGR template §5.4 cross-repo subsection landed.** *Verification*:
   `docs/sprints/_templates/strategic_work_analysis_and_gap_report_template.md`
   contains a `### 5.4` subsection titled "Cross-repo ghost-commit sweep"
   with: a one-paragraph applicability gate ("Fill this subsection only if
   the sprint window includes commits on a second repo such as devplatform"),
   a populated table example (repo, commit window, sweep result), and a
   pointer to where additional repos can be added. Same edit applied to the
   SDV template §8.4 if symmetric is chosen, and SCR template §2 if
   applicable; minimum SWAGR-template change required, additional templates
   editorial.

4. **Test-baseline drift root-caused and reported.** *Verification*:
   `docs/sprints/sprint_11/test_baseline_drift_investigation.md` exists on
   BlarAI main with: (a) the commit or condition that introduced the
   +20/-20 movement, identified via bisect or equivalent; (b) per-test
   breakdown of which previously-skipped tests now pass (test names + the
   marker/condition that flipped); (c) explicit fail-closed safety review of
   each newly-running test confirming no fail-closed assertion was weakened
   or removed (cite assertion-line citations); (d) a recommendation for the
   Sprint 12+ SDV-anchored baseline string and a recommendation about whether
   to update CLAUDE.md §"Active State" baseline number immediately or wait
   for Sprint 12 cadence. Report ≥ 80 lines (mature-not-minimal floor).

5. **Sprint 10 MINOR doctrine defect at `copilot-instructions.md:93` closed.**
   *Verification*: at Sprint 11 SCR commit, the SDV criterion #1 regex from
   Sprint 10 SDV §4 (`grep -E 'SDO|sdo|wake.*template|...|DEC-1[1-5]|fleet_paused|...'
   C:\Users\mrbla\BlarAI\.github\copilot-instructions.md`) returns either
   zero matches OR only matches inside pointer-form elements (`*See also:*`
   or `<sprint_lifecycle_pointer>` XML elements). The pre-fix borderline at
   L93 narrative phrase no longer matches.

6. **Cross-reference style asymmetry resolved — symmetric absolute paths.**
   *Verification*: (a) `grep -n "<BlarAI>"
   C:\Users\mrbla\devplatform\CLAUDE.md
   C:\Users\mrbla\devplatform\AGENTS.md
   C:\Users\mrbla\devplatform\.github\copilot-instructions.md` returns
   **zero matches** at Sprint 11 SCR commit (all 13 `<BlarAI>` template
   tokens in `devplatform\CLAUDE.md` expanded to literal
   `C:\Users\mrbla\BlarAI`); (b) `docs/decisions/DEC-19_*.md` exists on
   devplatform main formalizing the convention "all cross-repo references
   in BlarAI / devplatform doctrine use absolute Windows-style paths
   starting with `C:\Users\mrbla\<repo>\...`; template tokens are
   explicitly disallowed because they require substitution by the reader
   and break automated tooling that treats the string literally";
   DEC-19 ≥ 50 lines (mature-not-minimal floor), references Sprint 10
   SWAGR §13 gap #3 as motivation and cross-references DEC-16/17/18 for
   stylistic continuity. (LA-directed v3 amendment: original v1/v2
   "accept asymmetry, document choice" upgraded to symmetric expansion
   per mature-not-minimal mandate.)

7. **Stage 6.7.5 doc-hygiene batch closed.** *Verification*: (a)
   `tools/vikunja_mcp/README.md` Quick Start no longer contains a stale
   absolute `cd` reference (independent invocation from any cwd succeeds);
   (b) Sprint Auditor wake template at
   `C:\Users\mrbla\devplatform\docs\scheduled\wake_templates\sprint_auditor.md`
   §2.2 "Do NOT read" rule is amended to permit a strictly-read-only sweep
   of the single sprint-close `[phase:completion]` comment on the tracking
   task at SCR-audit time, with explicit guardrails (one comment, post-SCR
   landing only, no Co-Lead firing-exit narration); commit subject tag
   `[sprint:11][role:ea_code]` on devplatform main.

## 5. Scope

### 5.1 In-scope

1. **EA-1 — DEC Bundle Authoring (devplatform).** Author three formal
   numbered DEC documents on devplatform:
   - **DEC-16: Parallel-Sprint Authorization & Shared-Artifact Audit
     Discipline.** Formalizes the existing `set_parallel_sprints_authorized`
     mechanism + SDV §8.4 shared-artifact audit requirement. Cross-references
     `docs/governance/parallel-sprints.md` as the operational reference;
     records Sprint 8 SWAGR gap #6 + Sprint 9 SWAGR gap #7 as motivation; no
     mechanics change (the YAML flag + audit-table requirement is already
     active in the SDV template). Approximate length 60-80 lines.
   - **DEC-17: Ledger Format Q1-1 Per-File Permanence (Post-Freeze Rule).**
     Formalizes the post-2026-04-22 rule: monolithic
     `docs/POST_OPERATIONAL_MATURATION_LEDGER.md` is frozen at Entry 52;
     ALL new ledger entries land in `docs/ledger/<timestamp>_*.md` per
     Q1-1 format, no exceptions, no per-sprint exceptions, no per-EA
     exceptions. Subsumes Sprint 10 SWAGR §15.3 recommendation. Cross-
     references `docs/ledger/README.md` (operational mechanics); records
     Sprint 8 SWAGR gap #1 + Sprint 9 SWAGR gap #1 (both MAJOR-recurring,
     chain broken incidentally in Sprint 10) as motivation. Approximate
     length 60-80 lines.
   - **DEC-18: trusted_scope LOC Threshold Policy.** Formalizes the
     current `runaway_loc_threshold: 3000` and `runaway_file_threshold:
     100` values + the `la_merge_approve.ps1` escalation pattern as the
     operational answer to over-threshold diffs. Cross-references
     `docs/governance/merge-policy.md` (authoritative threshold values),
     `tools/autonomy_budget/config.yaml` (single source of truth for the
     numbers), and DEC-14.5 (the helper-script escalation pattern).
     Records Sprint 8 SWAGR §14.1 as motivation. Approximate length 60-80
     lines.

   EA-1 commits all three DEC files in a single devplatform commit
   `[sprint:11][role:ea_code][phase:completion] DEC bundle: parallel-sprint
   authorization + ledger Q1-1 permanence + trusted_scope LOC threshold`.
   No BlarAI-side touches in this EA. EA-1 ledger entry on BlarAI in
   `docs/ledger/<ts>_sprint11_ea1_dec-bundle.md` references the devplatform
   commit hash and the three DEC numbers.

2. **EA-2 — Deterministic Active State Refresh Procedure + Co-Lead Hook.**
   Author a procedure file `C:\Users\mrbla\BlarAI\docs\runbooks\active_state_refresh.md`
   (BlarAI side — operational runbook lives where the data is) describing
   in order: (a) live regression-suite pass/skip count via
   `.venv\Scripts\pytest shared/ services/ launcher/ --tb=no -q | tail`;
   (b) live BlarAI main HEAD via `git log --oneline -1 main`; (c) live
   Vikunja sprint state via `mcp__vikunja__get_task` on the current sprint
   tracking task + `mcp__vikunja__list_tasks` on Project 3 filtered to open
   sprint tracking; (d) live `docs/active_tasks.yaml` read for the roster;
   (e) edits applied to BlarAI CLAUDE.md §"Active State" only, using
   substituted live values. Procedure ≥ 50 lines, with example output for
   each step and the resulting Active State section text. Optionally
   provide a helper script (`tools/active_state_refresh.py` or PowerShell
   equivalent) that automates the data-gathering steps and prints the
   prospective Active State block — mature-not-minimal recommends this.

   On the devplatform side, EA-2 amends the Co-Lead Architect wake template
   `C:\Users\mrbla\devplatform\docs\scheduled\wake_templates\co_lead_architect.md`
   to add (or amend, depending on current template state) a sprint-transition
   hook that runs the BlarAI-side procedure at Sprint Kickoff Phase 3 and at
   Sprint Close (SCR-authoring time). The hook is a procedural reference,
   not an automation guarantee — Co-Lead remains the writer.

   EA-2 commits BlarAI procedure first, then devplatform wake template
   amendment. Two commits, one per repo. Ledger entry on BlarAI references
   both commit hashes.

3. **EA-3 — Template Amendments for Cross-Repo (BlarAI).** Edit
   `C:\Users\mrbla\BlarAI\docs\sprints\_templates\strategic_work_analysis_and_gap_report_template.md`
   to add a new `### 5.4 Cross-repo ghost-commit sweep` subsection with:
   applicability gate ("fill only if sprint window includes commits on a
   second repo"); table template (`repo | commit window | sweep result`);
   guidance prose ("Sprint Auditor extends the §5.4 sweep manually to
   secondary repos using absolute paths; refers to the parallel-sprint best
   practice guide for any shared-mutable artifacts across repos"); a
   pointer to `C:\Users\mrbla\devplatform\docs\governance\parallel-sprints.md`
   as the operational reference for cross-repo coordination.

   In the same EA, fix the SDV template §8.4 broken pointer to
   `docs/governance/parallel-sprints.md` (relative path, broken since
   Sprint 10's doctrine split moved the file to devplatform); re-point as
   absolute path to `C:\Users\mrbla\devplatform\docs\governance\parallel-sprints.md`.
   Update SDV template §8.4 to optionally include a cross-repo row in the
   shared-artifact table when applicable.

   If SCR template has a §5.4 or equivalent ghost-commit-discovery section,
   add the same cross-repo subsection there symmetrically; if not, no SCR
   template change (the SCR is Co-Lead's authored work, less rigorous
   ghost-commit discipline than SWAGR's adversarial audit).

   EA-3 also updates each amended template's revision log at the bottom
   recording the v1→v2 transition with date + change summary.

   Single BlarAI commit, `[sprint:11][role:ea_code]`. Ledger entry per Q1-1.

4. **EA-4 — Test-Baseline Drift Investigation Report.** Conduct a real
   investigation into the +20 pass / -20 skip movement between Sprint 8 EA-5
   close (~981 passed, 22 skipped per CLAUDE.md SDV-anchored baseline) and
   Sprint 10 SCR commit (1001 passed, 2 skipped per Sprint 10 SWAGR §8.1).
   Methodology — at EA-4's discretion within scope — may include any of:
   - git-bisect across Sprint 8 close → Sprint 10 SCR window running
     `pytest shared/ services/ launcher/ --tb=no -q` and recording the
     pass/skip count at each step;
   - identification of 20 specific previously-skipped test cases that now
     pass (by name);
   - per-test marker / condition inspection at the cause commit;
   - explicit fail-closed surface check for each newly-running test:
     pre/post assertion-shape comparison, particularly for tests under
     `services/policy_agent/`, `services/assistant_orchestrator/`,
     `shared/crypto/`, `shared/ipc/`, `services/semantic_router/`.

   Output: `C:\Users\mrbla\BlarAI\docs\sprints\sprint_11\test_baseline_drift_investigation.md`
   with: §1 Methodology; §2 Bisect log (or equivalent); §3 Identified test
   names that flipped + per-test marker/condition rationale; §4 Fail-closed
   surface verification (formal table); §5 Conclusion: drift category
   (benign / suspicious / regression); §6 Recommendation for Sprint 12+
   baseline string + CLAUDE.md §"Active State" update timing. Report ≥ 80
   lines.

   Single BlarAI commit, `[sprint:11][role:ea_code]`. Ledger entry per Q1-1.

5. **EA-5 — Doctrine & Doc-Hygiene Cleanup Batch (cross-repo).** Apply six
   small edits across both repos:
   - **BlarAI: `.github\copilot-instructions.md:93`** — replace the
     narrative phrase containing `DEC-15 sprint lifecycle, fleet-driven`
     with a phrase that omits the literal `DEC-15` reference, OR replace
     the narrative line with a structured `<sprint_lifecycle_pointer>`
     element pointing at devplatform doctrine. EA-5's choice within
     scope; the verification is the regex returns no narrative match
     (Sprint 11 success criterion #5).
   - **devplatform: cross-reference style symmetric-expansion + DEC-19.**
     (v3 amendment — LA-directed shift from "accept asymmetry, document
     choice" to "symmetric expansion + formalize convention" per
     mature-not-minimal mandate.) Two sub-deliverables:
     1. **Token expansion.** Replace the 13 `<BlarAI>` template tokens in
        `C:\Users\mrbla\devplatform\CLAUDE.md` (audited at SDV v3 time at
        lines 27, 28, 30, 36, 56, 57, 63, 65, 70, 71, 98, 131, 151) with
        the literal absolute path `C:\Users\mrbla\BlarAI`. EA-5
        re-enumerates `grep -n "<BlarAI>"
        C:\Users\mrbla\devplatform\CLAUDE.md` at execution time (line
        numbers may have shifted if any other devplatform commit lands
        between SDV v3 sign-off and EA-5 dispatch) and replaces every
        match. `devplatform/AGENTS.md` and
        `devplatform/.github/copilot-instructions.md` already use literal
        absolute paths (confirmed at SDV v3 time, 0 token matches) —
        no edits needed.
     2. **DEC-19 authoring.** Author
        `C:\Users\mrbla\devplatform\docs\decisions\DEC-19_cross-reference-style-convention_v1.md`
        on devplatform main formalizing the convention: all cross-repo
        references in BlarAI and devplatform doctrine use absolute
        Windows-style paths (`C:\Users\mrbla\<repo>\...`); template
        tokens like `<BlarAI>` or `<devplatform>` are explicitly
        disallowed (reason: require substitution by the reader, break
        automated tooling that treats the string literally). DEC-19 ≥
        50 lines per mature-not-minimal floor; §Motivation cites
        Sprint 10 SWAGR §13 gap #3; §Decision states the rule plainly;
        §Alternatives considered enumerates (a) accept-asymmetry, (b)
        define-`<BlarAI>`-once-per-file, (c) symmetric-absolute-paths
        with rationale for choosing (c); §Cross-references link to
        Sprint 10 SCR / SWAGR, DEC-16/17/18 (Sprint 11 EA-1 bundle), and
        Sprint 10 doctrine commit `9e5555c`.

     The original v1/v2 sub-bullet's "decision text record alone" is
     replaced by this combined token-expansion + DEC-19 authoring. EA-5
     commits to devplatform main with subject
     `[sprint:11][role:ea_code][phase:completion] EA-5 devplatform side:
     cross-reference token expansion + DEC-19`. Single devplatform commit
     covers both sub-deliverables (token-expansion + DEC-19 share the
     same EA-5 devplatform-side merge). If `grep` returns more than 13
     matches at execution time, EA-5 enumerates the extras in its
     completion report and expands them all (the count was 13 at SDV v3
     time; drift is unlikely given fleet-pause discipline).
   - **BlarAI: `tools\vikunja_mcp\README.md` Quick Start** — fix the stale
     `cd` reference. Replace with a cwd-agnostic invocation (likely an
     absolute path or the equivalent of `cli.py` style from Sprint 10
     EA-3). The fix is verified by independent invocation from at least
     two cwds.
   - **devplatform: `docs\scheduled\wake_templates\sprint_auditor.md` §2.2
     "Do NOT read" rule** — amend to permit a strictly-read-only sweep of
     the single sprint-close `[phase:completion]` Co-Lead comment on the
     tracking task during SWAGR authoring, with explicit guardrails:
     - one comment only (the post-SCR sprint-close comment, identified by
       `[agent:co_lead][phase:completion]` tag and the SCR commit hash);
     - read-only — auditor does not respond, comment, or react;
     - applies only at SWAGR §5.1 row-10 verification, not elsewhere in
       the audit;
     - all other Co-Lead firing-exit / mid-sprint narration comments
       remain in the deliberate-exclusion list.
   - **(optional, deferable to Stage 6.7.5 backlog)**: Vikunja project
     rationalization UU #316 — explicitly NOT touched this sprint.
   - **(optional, low-priority)**: stale `Gate:Pending-Human` task #398 on
     Project 6 — close as duplicate of #397 with one-comment sweep. This is
     fleet-hygiene, not an EA deliverable; EA-5 may include it if budget
     permits, otherwise routine triage.

   EA-5 commits BlarAI side first (3 edits, single commit), then
   devplatform side (1 edit, single commit). Two commits, one per repo.
   Ledger entry per Q1-1 on BlarAI side referencing both.

6. **Stage 6.7.5 carry-over closure record in SCR.** At Sprint 11 SCR
   authoring, the Co-Lead explicitly enumerates the six Sprint 10 MINOR
   gaps with their closing commit hashes in a §13-style table.

7. **Sprint-close comment on Vikunja tracking task #410.** Standard
   pattern. Co-Lead at sprint close adds a
   `[agent:co_lead][phase:completion]` comment to task #410 noting closure
   with merge commits and SCR/SWAGR paths.

### 5.2 Out-of-scope (deliberately deferred)

1. **UC-002 Memory Search opening milestone or any other UC-advancement
   work** — Sprint 9 SWAGR + Sprint 10 SWAGR both recommended UC-advancement
   after process-hygiene; Sprint 11 IS the process-hygiene close-out, but
   UC work itself is deferred to **post-cf-1** per LA sequencing. Sprint 12
   or Sprint cf-1+1 will resume UC trajectory.

2. **cf-1 (DevPlatform Cloud-Fleet Redesign Foundation) kickoff** — cf-1
   remains dormant through Sprint 11. Sprint 11 closes the process-hygiene
   substrate cf-1 inherits; cf-1 begins after Sprint 11's SCR + SWAGR.

3. **ADR (Architecture Decision Record) amendments** — no ADRs touched.
   ADR-007 / 010 / 011 / 012 + DEC-01..10 (Task 4 production config)
   remain unchanged. Any ADR/DEC drift surfacing in EA-4's investigation
   becomes a follow-up ticket, not a Sprint 11 amendment.

4. **Fleet-code refactoring** — no `services/`, `shared/`, `launcher/`
   source touched. EA-4's investigation reads test files and possibly
   touches conftest / marker config, but does not modify production source.
   If EA-4 root-causes the drift to a production change that warrants
   revision, that's a follow-up ticket.

5. **`tools/vikunja_mcp/` migration** — Vikunja MCP server stays in BlarAI
   per Sprint 10 §5.2 #8. EA-5's Quick Start fix is editorial-only.

6. **Repo or directory renames** — none.

7. **Existing DEC amendments** — DEC-11 / 12 / 13 / 14.5 / 15 + DEC-01..10
   are unchanged. EA-1's three new DECs are additions, not amendments.

8. **New gate label invention** — the Vikunja gate-label set (Pending-SDO
   / Pending-CoLead / Pending-Human / Approved / Rejected / Escalation,
   ids 9–14) stays as-is. EA-5's stale `#398` cleanup is a per-task action,
   not a label scheme change.

9. **Pytest config or marker taxonomy changes** — EA-4 reads markers, does
   not rewrite them. `pyproject.toml` pytest section unchanged.

10. **Vikunja project rationalization (UU #316)** — Stage 6.7.5 backlog;
    explicit out-of-scope. Carry-over remains.

### 5.3 Scope boundaries and edge cases

These are gray-area calls the LA + Co-Lead pre-decide so EA-1..EA-5 don't
have to escalate every ambiguity.

- **Where DECs live** (EA-1 boundary): the three new DECs land in
  `C:\Users\mrbla\devplatform\docs\decisions\DEC-16_*.md` etc.
  Justification: DEC-15 is canonically referenced at
  `devplatform/docs/DEC15_SPRINT_STRATEGIC_REVIEW_PROPOSAL_v1.xml` per
  Sprint 10 doctrine split; DEC-11 is at
  `devplatform/docs/DOMAIN8_DEC11_BUDGET_PROPOSAL_v3.xml`. The three new
  DECs are fleet-process-domain → devplatform side. If
  `devplatform/docs/decisions/` doesn't exist, EA-1 creates it. Filename
  pattern `DEC-NN_<kebab-name>_v1.md` (markdown, not XML — the legacy XML
  pattern was Stage-3-era; markdown is the current convention per
  Sprint 9/10 governance docs).

- **DEC numbering** (EA-1): the next free numbers after DEC-15 are DEC-16
  / 17 / 18 (no other in-flight DEC reservations observed during context
  load). If the cross-reference-style call in EA-5 chooses to record as a
  DEC, it takes DEC-19.

- **DEC bundle commit ordering** (EA-1): a single devplatform commit lands
  all three DECs together — they're a thematic bundle and a single
  serializable artifact. BlarAI-side ledger entry references the devplatform
  commit hash and the three DEC numbers.

- **Active State refresh procedure home** (EA-2): the procedure file lives
  in `C:\Users\mrbla\BlarAI\docs\runbooks\active_state_refresh.md` per
  Sprint 10 doctrine split (runbooks for BlarAI-domain operations stay on
  BlarAI side; pointer goes the other direction). The Co-Lead wake-template
  hook lives in devplatform (wake templates are fleet doctrine, devplatform
  per Sprint 10).

- **Active State refresh procedure scope** (EA-2): the procedure refreshes
  exactly the §"Active State" section of `CLAUDE.md`. It does NOT extend to
  `ACTIVE_SPRINT.md` (which is already Co-Lead-only per existing convention)
  or `active_tasks.yaml` (which is Co-Lead-only via `add_active_task` API).
  The procedure may *cite* these as inputs but writes only to CLAUDE.md.

- **Active State helper script** (EA-2 boundary): if EA-2 adds a helper
  script, it lands at `C:\Users\mrbla\BlarAI\tools\active_state_refresh.py`
  (BlarAI-side tool) or `C:\Users\mrbla\BlarAI\tools\active_state_refresh.ps1`
  (PowerShell equivalent — likely simpler for the scope, since the steps
  are mostly running existing CLIs and printing). EA-2's choice; both are
  in-scope. NOT in-scope: refactoring `tools/autonomy_budget/`, adding a
  new entry to `tools/active_tasks.py`, or installing new Python deps.

- **Template amendment style** (EA-3): the new SWAGR template §5.4
  subsection is **markdown narrative + table**, matching the existing
  template style. No XML elements, no new YAML frontmatter fields. The
  applicability gate is a one-paragraph prose clause, not a programmatic
  check.

- **Symmetric SDV template amendment** (EA-3 boundary): when EA-3 amends
  SWAGR template §5.4, it ALSO touches SDV template §8.4 to (a) fix the
  broken `parallel-sprints.md` pointer and (b) optionally add a cross-repo
  row to the shared-artifact table. The SDV §8.4 broken-pointer fix is
  required; the optional cross-repo row is editorial and may be deferred
  if the row format would unnecessarily duplicate the SWAGR §5.4 sweep.

- **Test-drift investigation methodology** (EA-4 boundary): the
  methodology is at EA-4's discretion within the scope of "real
  investigation". Acceptable methods include git-bisect across the
  Sprint 8 → Sprint 10 window, manual `git log` enumeration of every
  commit that touches `pyproject.toml` / `conftest.py` / `tests/`, or
  marker-resolution analysis at HEAD. EA-4 must produce auditable
  evidence (bisect log or equivalent), not just a conclusion.

- **Test-drift fail-closed verification** (EA-4 hardening): for any newly-
  running test under `services/policy_agent/`, `services/assistant_orchestrator/`
  (especially `pgov.py`), `shared/crypto/`, `shared/ipc/`,
  `services/semantic_router/`, OR any test asserting on `last_failure["code"]`,
  `Sensitivity.UNCLASSIFIED`, PGOV thresholds, or vsock topology, EA-4
  produces a pre/post assertion-shape comparison. Discovery of a weakened
  fail-closed assertion is a CRITICAL finding that requires immediate
  Sprint 11 mid-flight scope adjustment via the LA-arbitration path
  (similar to Sprint 10's PENDING-LA arbitration); EA-4 stops, files the
  finding, and waits for LA direction rather than continuing or attempting
  to fix in-EA.

- **Test-drift recommendation scope** (EA-4 boundary): EA-4 recommends a
  Sprint 12+ SDV-anchored baseline string AND a CLAUDE.md §"Active State"
  update path. EA-4 does NOT directly edit CLAUDE.md (that's EA-2's
  procedure invocation at SCR cadence). EA-4's report is the input; the
  Active State refresh procedure (EA-2 deliverable) consumes it.

- **EA-5 cross-reference style decision** (EA-5 boundary, v3 amendment):
  the convention is **symmetric absolute paths everywhere** — BlarAI side
  already uses literal `C:\Users\mrbla\devplatform\...` paths; devplatform
  side gets the 13 `<BlarAI>` tokens in `devplatform\CLAUDE.md` expanded
  to literal `C:\Users\mrbla\BlarAI` paths. AGENTS.md and
  copilot-instructions.md on devplatform side already use absolute paths
  (confirmed at SDV v3 time, 0 token matches). EA-5 authors DEC-19 on
  devplatform formalizing the convention so cf-1 inherits the rule
  unambiguously. The earlier v1/v2 "accept asymmetry" default is
  superseded by LA's mature-not-minimal direction
  ("feel free to improve and iterate") 2026-05-11 night-handoff session.
  Edit size is ~13 string replacements in a single file plus a ~50-line
  DEC document — well within `trusted_scope` (under 200 LOC); no
  escalation expected.

- **EA-5 stale `Gate:Pending-Human` cleanup (#398)** — optional, may close
  with a one-comment Vikunja action ("duplicate of #397; closed as part of
  Sprint 11 doc-hygiene sweep"). NOT a critical-path deliverable; included
  in scope only if budget permits.

- **Sprint Auditor wake-template amendment guardrails** (EA-5): the
  read-only sweep allowance is **narrow**: one comment per audit, the
  `[agent:co_lead][phase:completion]` sprint-close comment posted within
  the SCR commit's same firing window. All other Co-Lead Vikunja activity
  (firing-exit narration, mid-sprint Q&A, comprehension reports, prompt-
  staging APPROVED reports) remains in the deliberate-exclusion list.
  EA-5's amendment text MUST include this explicitly to prevent scope
  creep in future auditor sessions.

- **Mature-not-minimal floors per EA**:
  - EA-1 DEC files: ≥ 60 lines each (3 DECs); aggregate ≥ 180 lines.
  - EA-2 procedure file: ≥ 50 lines; wake-template hook ≥ 10 lines.
  - EA-3 SWAGR §5.4 subsection: ≥ 25 lines populated.
  - EA-4 investigation report: ≥ 80 lines.
  - EA-5 each edit: substantive (not one-line); cross-reference style
    decision record ≥ 20 lines minimum.

- **Pre-existing Sprint 10 SWAGR gap on Active State drift recurrence** — at
  Sprint 11 SCR commit, the §"Active State" baseline string MUST reflect
  live-computed pytest output. If EA-2 procedure produces a number, the SCR
  uses it. If EA-4 root-causes the drift and recommends an explicit update,
  the SCR records both the prior SDV-anchored string and the new live
  string. The SDV-anchored baseline of `~981 passed, 22 skipped` is
  Sprint 8 EA-5 vintage; Sprint 11 SCR is the natural cutover.

- **Commit message convention**: all EA commits use
  `[sprint:11][role:ea_code][phase:<phase>]` style per fleet convention.
  Phase tags: `[phase:completion]` for the merge commit; `[phase:in-progress]`
  for any pre-completion checkpoints (rare for this sprint's profile).

- **`trusted_scope` escalation expected**: EA-1 (3 DECs aggregating ~180-240
  lines) is unlikely to exceed `runaway_loc_threshold: 3000`. EA-4
  investigation report at ~80-150 lines also unlikely. EA-3 template edits
  are small. EA-2 if it includes a helper script may approach but not
  exceed the threshold. **No EA is currently predicted to escalate**, but
  Sprint 11 carries no risk of `la_merge_approve.ps1` being needed under
  ordinary conditions — distinct from Sprint 10's escalation-heavy profile.

- **No new fleet conventions invented**: Sprint 11 records existing
  practices (parallel-sprint authorization, Q1-1 ledger, trusted_scope
  threshold). It does NOT create new sprint-lifecycle phases, new EA roles,
  or new gate labels. EA-1 specifically authors DECs that ratify existing
  operational mechanics, not propose new ones.

### 5.4 Parallel-Sprint Authorization & Shared-Artifact Audit

**N/A — serial kickoff (no other sprint active).**

The active task roster (`docs/active_tasks.yaml`) at Sprint 11 kickoff
contains exactly one entry — Sprint 10 (`task_id: 369, sprint_id: 10`) —
which is **stale**: Sprint 10's SCR (`90db41f`) and SWAGR (`14ac80d`)
both landed on 2026-05-11, but the roster wasn't refreshed. The Phase 4
transition step in this kickoff will mark task #369 complete and write
Sprint 11's entry (`task_id: 410, sprint_id: 11`) into the roster,
producing a clean serial transition. cf-1 (DevPlatform Cloud-Fleet
Redesign Foundation, Vikunja #368, Project 10) is chartered but dormant
per LA confirmation — cf-1 will not begin until Sprint 11 closes. Sprint
11's roster window will overlap zero with any other sprint.

The fleet-pause state during Sprint 11 will follow the standard
per-EA cycle: pause before each EA dispatch (per fleet-hygiene §4), unpause
on successful EA close. **Exception (v2 amendment, §7)**: EA-1 and EA-2
share a single paused window — Co-Lead pauses, SDO dispatches BOTH EA-1
and EA-2 prompts, both EA-Code firings execute concurrently in the same
window, Co-Lead does Phase 1b reviews + merge-queue serialization in
whichever order the APPROVED reports land, then unpauses after both
merge. EA-3 / EA-4 / EA-5 each get their own pause/unpause cycle per the
standard cadence. This kickoff itself paused before the Phase 4 commit
chain and unpauses after Phase 4 + v2 amendment commits.

Because the audit is N/A, the §8.4.1 shared-artifact table and §8.4.2
authorization sign-off boxes are not populated. `set_parallel_sprints_authorized(True)`
will NOT be called for this sprint; `add_active_task` accepts Sprint 11's
roster entry under standard single-sprint conditions.

**Note**: Sprint 11 EA-1 is *itself* authoring DEC-16 (parallel-sprint
authorization), formalizing the mechanism that the §8.4 audit relies on.
The serial-kickoff posture here is correct regardless — DEC-16 records
existing practice, it does not change the practice during Sprint 11.

## 6. Deliverable summary

| # | Deliverable | Type | Target location | Success criterion |
|---|---|---|---|---|
| 1 | DEC-16 Parallel-Sprint Authorization & Shared-Artifact Audit Discipline | doc (DEC) | `C:\Users\mrbla\devplatform\docs\decisions\DEC-16_parallel-sprint-authorization_v1.md` | #1 |
| 2 | DEC-17 Ledger Format Q1-1 Per-File Permanence (Post-Freeze Rule) | doc (DEC) | `C:\Users\mrbla\devplatform\docs\decisions\DEC-17_ledger-format-q1-1-permanence_v1.md` | #1 |
| 3 | DEC-18 trusted_scope LOC Threshold Policy | doc (DEC) | `C:\Users\mrbla\devplatform\docs\decisions\DEC-18_trusted-scope-loc-threshold_v1.md` | #1 |
| 4 | Active State refresh procedure | doc (runbook) | `C:\Users\mrbla\BlarAI\docs\runbooks\active_state_refresh.md` | #2 |
| 5 | (optional) Active State refresh helper script | code (tool) | `C:\Users\mrbla\BlarAI\tools\active_state_refresh.{py,ps1}` | #2 |
| 6 | Co-Lead Architect wake-template hook | doc (wake template) | `C:\Users\mrbla\devplatform\docs\scheduled\wake_templates\co_lead_architect.md` (amendment) | #2 |
| 7 | SWAGR template §5.4 cross-repo subsection | doc (template) | `C:\Users\mrbla\BlarAI\docs\sprints\_templates\strategic_work_analysis_and_gap_report_template.md` (amendment) | #3 |
| 8 | SDV template §8.4 broken-pointer fix + optional cross-repo row | doc (template) | `C:\Users\mrbla\BlarAI\docs\sprints\_templates\strategic_design_vision_template.md` (amendment) | #3 |
| 9 | Test-baseline drift investigation report | doc | `C:\Users\mrbla\BlarAI\docs\sprints\sprint_11\test_baseline_drift_investigation.md` | #4 |
| 10 | `copilot-instructions.md:93` doctrine defect fix | doc | `C:\Users\mrbla\BlarAI\.github\copilot-instructions.md` | #5 |
| 11 | DEC-19 Cross-Reference Style Convention (absolute paths everywhere) | doc (DEC) | `C:\Users\mrbla\devplatform\docs\decisions\DEC-19_cross-reference-style-convention_v1.md` | #6 |
| 11b | devplatform `CLAUDE.md` `<BlarAI>` → absolute path expansion (13 occurrences) | doc | `C:\Users\mrbla\devplatform\CLAUDE.md` | #6 |
| 12 | `vikunja_mcp/README.md` Quick Start fix | doc | `C:\Users\mrbla\BlarAI\tools\vikunja_mcp\README.md` | #7 |
| 13 | Sprint Auditor wake-template §2.2 amendment | doc (wake template) | `C:\Users\mrbla\devplatform\docs\scheduled\wake_templates\sprint_auditor.md` (amendment) | #7 |
| 14 | Stage 6.7.5 carry-over closure record in SCR | section in SCR | `docs/sprints/sprint_11/strategic_completion_report.md` §13 | (operational) |
| 15 | Sprint-close comment on tracking task #410 | vikunja comment | task #410 (Project 3) | (operational) |

## 7. EA milestone plan

| EA-# | Working title | One-sentence purpose | Depends on | Approx size |
|---|---|---|---|---|
| EA-1 | DEC Bundle Authoring (devplatform) | Author three formal numbered DECs (DEC-16 parallel-sprint auth, DEC-17 Q1-1 ledger permanence, DEC-18 trusted_scope LOC threshold) on devplatform main, formalizing operational patterns active for 3 sprints | main (`44f5f8c` BlarAI, `9e5555c` devplatform) | M |
| EA-2 | Deterministic Active State Refresh Procedure + Co-Lead Hook | Author procedure file on BlarAI + (optional) helper script + Co-Lead wake-template hook on devplatform that flips Active State refresh from copy-prior-text to live-computation | main (BlarAI + devplatform); **parallel with EA-1** | M |
| EA-3 | SWAGR Template Cross-Repo Amendment | Amend `_templates/strategic_work_analysis_and_gap_report_template.md` §5.4 to add cross-repo ghost-commit sweep subsection; fix SDV template §8.4 broken pointer; update template revision logs | EA-1 AND EA-2 both merged | S |
| EA-4 | Test-Baseline Drift Investigation | Bisect / enumerate the +20 pass / -20 skip movement between Sprint 8 EA-5 close and Sprint 10 SCR commit; per-test fail-closed verification; baseline recommendation for Sprint 12+ | EA-3 merged | M |
| EA-5 | Doctrine + Doc-Hygiene Cleanup Batch (cross-repo) | Fix Sprint 10 MINOR doctrine defects (copilot-instructions.md:93 + cross-reference style decision record) + Stage 6.7.5 items (vikunja_mcp README, Sprint Auditor wake-template §2.2 amendment) | EA-4 merged | S |

**Sequencing rationale**: **EA-1 and EA-2 run in parallel; EA-3 / EA-4 /
EA-5 then run serial.** (v2 amendment — see Appendix A.)

- **EA-1 and EA-2 fire concurrently** in a single paused window. Working
  sets are disjoint: EA-1 writes only to devplatform `docs/decisions/`,
  EA-2 writes to BlarAI `docs/runbooks/` + one devplatform wake-template
  section EA-1 does not touch. No file overlap, no read-after-write
  dependency. SDO authors both EA prompts before either fires; Co-Lead's
  Phase 1b reviews can run in any order; merges serialize through
  Co-Lead's queue (one merge at a time — this is the choke point on
  parallel savings).
- **EA-3 fires after both EA-1 and EA-2 are merged.** EA-3 amends
  templates; benefits from a clean post-parallel main with both DEC
  bundle and Active State procedure landed (EA-3's template revision-log
  entries may want to reference DEC-16 / 17 / 18 or the Active State
  procedure path).
- **EA-4 fires after EA-3 merged.** Investigation runs against a stable
  codebase with templates already amended.
- **EA-5 fires last.** Cleanup batches benefit from being applied at the
  end when no further EAs will disturb the touched files; EA-5 also
  records the cross-reference style decision which may inform any
  late-sprint template touchups.

**Cross-repo commit ordering**: EA-1 single devplatform commit (lands in
parallel window); EA-2 BlarAI commit then devplatform commit (lands in
parallel window with EA-1; ordering between EA-1 devplatform commit and
EA-2 devplatform commit is whichever Co-Lead merges first, since both
touch devplatform main); EA-3 single BlarAI commit; EA-4 single BlarAI
commit; EA-5 BlarAI commit then devplatform commit. Eight commits total
across both repos (five BlarAI, three devplatform). Each cross-repo
commit body references the BlarAI-side commit hash where applicable.

**Parallel within-sprint pattern — first BlarAI exercise.** Sprint 8 used
sequential merges of disjoint-working-set EAs; Sprint 9 and Sprint 10
were strictly serial within-sprint. Sprint 11's EA-1 + EA-2 parallel
window is the first deliberate within-sprint parallelism on the
post-DEC-15 cadence. The pattern is **not** ratified by DEC-16 (which
governs *across-sprint* parallelism only); Sprint 11 establishes a single
data point. If within-sprint parallelism becomes a recurring pattern,
Sprint 12+ may ratify it via a separate micro-DEC. Merge serialization
remains: only one EA's merge commit lands on each repo's main at a time
(Co-Lead serializes via the merge queue).

**Clustering rationale**: Sprint 11 is 5-EA workstream-per-deliverable —
each EA owns one coherent artifact set. Each EA is independently mergeable
and produces a discrete value-add. No clustering of multiple deliverables
into a single EA (that would dilute the mature-not-minimal floor per
deliverable).

## 8. Dependencies and prerequisites

### 8.1 Upstream dependencies

- Sprint 10 closed cleanly — ✅ verified. SCR `90db41f`, SWAGR `14ac80d`,
  archive cleanup `44f5f8c` form the complete closure chain. 7/7 SDV
  criteria PASS independent audit.
- BlarAI doctrine substrate (post-Sprint-10 split) — ✅ verified.
  `CLAUDE.md` 156 lines, `copilot-instructions.md` 175 lines XML, `AGENTS.md`
  10 lines pointer stub, all on `44f5f8c`.
- devplatform doctrine substrate (post-Sprint-10 authorship) — ✅ verified.
  `CLAUDE.md` 185 lines, `AGENTS.md` 105 lines, `copilot-instructions.md`
  343 lines XML, all on `9e5555c`.
- Sprint 11 tracking Vikunja task #410 created with `Gate:Pending-Human`
  label — ✅ verified (created during Phase 2 of this kickoff session).
- DEC-15 sprint lifecycle infrastructure intact — ✅ verified (template,
  ACTIVE_SPRINT.md pointer, active_tasks.yaml roster file, sprint reports
  directory convention).
- Co-Lead Architect role active — ✅ this kickoff session.
- `docs/governance/parallel-sprints.md` exists on devplatform for DEC-16
  to cross-reference — ✅ verified at
  `C:\Users\mrbla\devplatform\docs\governance\parallel-sprints.md`.
- `docs/governance/merge-policy.md` exists on devplatform for DEC-18 to
  cross-reference — ✅ verified at
  `C:\Users\mrbla\devplatform\docs\governance\merge-policy.md`.
- `docs/ledger/README.md` exists on BlarAI for DEC-17 to cross-reference —
  ✅ verified.

### 8.2 External dependencies

- devplatform repo accessible at `C:\Users\mrbla\devplatform` and on `main`
  branch — ✅ at kickoff.
- BlarAI Python venv (`.venv/Scripts/pytest`) functional for EA-4's
  bisect/regression-suite runs — assumed present (Sprint 10 SWAGR §8.1 ran
  pytest successfully at `90db41f`).
- Vikunja MCP server availability — ✅ project_summary call succeeded
  during kickoff.
- Windows host PowerShell available for verification commands — ✅.
- No external network dependencies (pure documentation + one investigation
  + one optional helper script).

### 8.3 Assumed invariants

- **cf-1 does NOT begin during Sprint 11** — per LA confirmation; cf-1 is
  dormant.
- **No structural repo changes during Sprint 11** — no rename, no move
  beyond explicitly-scoped EA edits.
- **BlarAI doctrine files (3) not edited outside the EA chain** — only
  EA-2/EA-3/EA-5 touch them, all in defined sections.
- **devplatform doctrine files not edited outside the EA chain** —
  EA-1/EA-2/EA-5 touch defined sections only.
- **LA pause/unpause cadence** — standard per-EA cycle.
- **No production source edits** under `services/`, `shared/`, `launcher/`
  — Sprint 11 is doc + governance only; EA-4 is read-only on prod source.
- **Git HEAD stability** — no force-push, no history rewrite.
- **Vikunja MCP availability** — server up throughout the sprint window.
- **Sprint 10 SCR + SWAGR remain on main** — no retroactive edits.

### 8.4 Parallel-Sprint Authorization & Shared-Artifact Audit

**N/A — serial kickoff (no other sprint active).**

See §5.4 for justification. Sprint 11 closes Sprint 10's roster entry and
adds its own as part of the Phase 4 transition. cf-1 (Vikunja #368)
remains dormant. The §8.4.1 shared-artifact table and §8.4.2 authorization
sign-off boxes are not populated. `set_parallel_sprints_authorized(True)`
is NOT called.

## 9. Risks and unknowns

### 9.1 Known risks

| Risk | Probability | Impact | Mitigation |
|---|---|---|---|
| EA-1 DEC numbering conflict (DEC-16/17/18 already reserved somewhere not surfaced during context load) | LOW | LOW | EA-1's Phase 0 (Comprehension) re-greps for `DEC-16` / `DEC-17` / `DEC-18` across both repos and any docs/decisions/ if it exists before authoring; if a conflict surfaces, EA-1 escalates rather than overwrites |
| EA-2 procedure too prescriptive — automating away LA judgment about what counts as "current state" | LOW | LOW | EA-2 deliverable is a procedure + (optional) helper script, NOT a daemon or scheduled task; Co-Lead remains the writer; the procedure is invoked-on-demand at sprint transitions only |
| EA-3 template amendment introduces breaking change for in-flight SWAGRs | LOW | LOW | The §5.4 addition is purely additive (a new subsection); existing SWAGRs continue to render correctly without §5.4 content; auditor template-state at time of audit is captured in SWAGR frontmatter |
| EA-4 root-causes drift to a real silent fail-closed regression | LOW | HIGH | EA-4 scope explicitly includes fail-closed surface verification with assertion-shape comparison; if regression found, EA-4 stops and escalates to LA (mid-sprint scope adjustment path); this is the highest-impact protective scope |
| EA-4 bisect inconclusive (cause is environment-level not commit-level) | MED | LOW | EA-4 deliverable accommodates a "cause is non-commit (environment / pytest config / marker resolution)" conclusion; the recommendation in that case is to baseline against live state at Sprint 11 SCR commit going forward |
| EA-5 cross-reference style decision triggers LA-mid-sprint redirect to symmetric expansion | MED | MED | EA-5 default disposition is "accept asymmetry, document the choice"; redirect to symmetric expansion would expand scope to touch devplatform doctrine to expand `<BlarAI>` tokens — EA-5 stops and waits for LA arbitration rather than auto-applying |
| EA-2 wake-template hook conflict with Sprint 10 EA-3 devplatform wake-template authorship | LOW | LOW | Sprint 10 EA-3 authored devplatform doctrine, NOT wake templates (wake templates were already in devplatform pre-Sprint-10; Sprint 10 fixed absolute-path bugs in them). EA-2's amendment is editorial inside the existing Co-Lead template |
| Sprint 11 itself becomes the first cross-repo SWAGR to exercise the new §5.4 — auditor template-version mismatch | LOW | LOW | The Sprint Auditor reads the template at audit time (not at sprint start); Sprint 11's auditor session at SCR-cadence will see the EA-3 amended template and use it |
| Active State drift continues during Sprint 11 itself (between SDV sign-off and SCR commit) | MED | LOW | EA-2's procedure will be invoked at Sprint 11 SCR cadence to refresh; SDV-time state drift is acceptable |
| Active State refresh procedure (EA-2) lands but is not invoked at Sprint 11 SCR — recurring pattern persists | MED | MED | Co-Lead's Sprint 11 SCR cadence will run the procedure (verified by SCR's §"Active State" reflecting live pytest output, not SDV-anchored 981/22 string); this is the first procedural data point |
| `Gate:Pending-Human` task #398 (stale) auto-triggers a fleet notification during Sprint 11 EAs | LOW | LOW | Optional EA-5 cleanup; if not closed mid-sprint, routine triage post-Sprint-11; no EA blocker |
| Test-baseline drift investigation surfaces a previously-undiagnosed environmental dependency (e.g., specific Python version, GPU driver, OpenVINO build) | MED | MED | EA-4 reports the environmental dependency as a finding; depending on severity, becomes a Sprint 11 mid-flight CAR escalation OR a Sprint 12 carry-over; report is the deliverable regardless |
| Mature-not-minimal floor missed on a small deliverable (e.g., EA-5 cross-reference style record at exactly 20 lines feeling padded) | LOW | LOW | The floor is a content-density expectation, not a hard line count; if EA-5 produces a focused 15-line decision record with substantive content, Co-Lead's review accepts it; padded prose is rejected |
| EA-1 DEC content drifts from current operational mechanics (DEC text says one thing, governance doc says another) | LOW | MED | EA-1 explicitly cites the existing governance doc as the operational authority in each DEC; the DEC is a ratification record, not a redefinition |
| EA-1 + EA-2 parallel merge-queue contention (v2 SDV amendment): both EAs finish near the same time, both submit to Co-Lead's merge queue, Co-Lead must order them | MED | LOW | Co-Lead merge queue is serial-by-design; merge order between EA-1 and EA-2 is whichever Phase 1b APPROVED report lands first. Both EAs' working sets are disjoint, so no merge conflict possible; the contention is purely on Co-Lead session time. Estimate ~10 min added Co-Lead time vs serial cadence. If both merges hit trusted_scope escalation simultaneously, LA's `la_merge_approve.ps1` invocation is serial regardless |
| Parallel-window devplatform race (v2): EA-1 writes `docs/decisions/DEC-1*.md`, EA-2 amends `docs/scheduled/wake_templates/co_lead_architect.md` — both on devplatform main | LOW | LOW | File paths disjoint; git merges of two disjoint feature branches into devplatform main do not conflict. Convention is direct-to-main on devplatform per N-6; the two EA commits land sequentially in whichever order Co-Lead authorizes. No race condition surface |
| EA-5 token expansion overlooks an intentional `<BlarAI>` use (v3): if `devplatform\CLAUDE.md` contains a literal `<BlarAI>` reference that is meant as the abstract project name rather than a substitutable path token | LOW | LOW | EA-5 enumerates every `grep -n "<BlarAI>"` match in `devplatform\CLAUDE.md` and inspects context line-by-line before bulk-replacing; if any occurrence is the abstract project name (e.g., "the BlarAI project") rather than a path token (e.g., `<BlarAI>\CLAUDE.md`), EA-5 preserves that one and notes the rationale in the EA completion report. At SDV v3 audit time, all 13 tokens in `devplatform\CLAUDE.md` were path-tokens (preceded by `\` and followed by file/directory path); zero abstract-name uses observed |
| EA-5 DEC-19 (v3) drifts from existing absolute-path practice already in place across most of the codebase | LOW | LOW | DEC-19 explicitly cites the pre-existing BlarAI-side practice + the post-Sprint-10-EA-3 devplatform-side mixed state as the motivation; the DEC ratifies existing practice + closes the one-file outlier, NOT a new rule. EA-5 commits the DEC and the token expansion in the same merge to preserve the ratification-record + implementation atomicity |

### 9.2 Known unknowns

1. **What exact commit / configuration introduces the +20/-20 test-baseline
   drift?** EA-4's investigation answers this.
2. **Are any of the 20 newly-running tests fail-closed-adjacent?** EA-4's
   verification table answers this.
3. **Whether EA-2's helper script is worth shipping vs. procedure-only?**
   EA-2's deliverable choice answers this; either is acceptable per
   mature-not-minimal floor.
4. **Whether the cross-reference style call lands as a DEC-19 or a
   template addendum or a governance doc section?** EA-5's choice within
   §5.3 boundary answers this.
5. **Whether `docs/decisions/` exists in devplatform or needs creation
   for EA-1?** EA-1's Phase 0 verifies this; creates if missing.
6. **Whether the Sprint Auditor wake-template §2.2 amendment will need to
   be tested against the Sprint 11 SWAGR firing itself, or if next-sprint
   cadence is the first exercise?** The amendment is procedurally simple —
   §2.2 deliberate-exclusion text edit; Sprint 11's auditor session at SCR
   cadence will be the first to operate under the amended rule (live test).

### 9.3 Unknown unknowns posture

Sprint 11's structural-cleanup nature means most unknowns are at the
**boundary** between formalized practice and undocumented edge cases.
Likely surprise classes: (a) a DEC-16/17/18 number reservation in a file
not surfaced during context load (mitigation: EA-1 re-greps); (b) the
Active State refresh procedure conflicting with an existing fleet-side
mechanism (mitigation: EA-2 reads `tools/autonomy_budget/active_tasks.py`
and Co-Lead wake template before authoring); (c) the test-baseline drift
having a non-obvious environmental cause that EA-4 can't cleanly attribute
to a commit (mitigation: report accommodates this; recommendation falls
back to "baseline against live state at Sprint 11 SCR"); (d) Sprint 10's
incidentally-broken ledger-discontinuity chain not actually being broken —
if Sprint 11 EA-1 hits the monolithic ledger and the legacy guard isn't
firing (Sprint 11 EAs MUST write to `docs/ledger/` per Q1-1; DEC-17 IS
the formalization, but its absence today is the latent risk vector). The
fleet's autonomous-momentum default would silently re-anchor to the
monolithic file if any agent's working memory included that pattern from
pre-2026-04-22 entries — EA-1 commits DEC-17 first to remove this surface.

## 10. Alignment to long-term roadmap

- **Project phase alignment**: Phase 5 Post-Operational Development —
  Sprint 11 is the **fifth consecutive hardening sprint** (Sprint 7 audit,
  Sprint 8 test quality, Sprint 9 governance docs, Sprint 10 doctrine
  split, Sprint 11 process-hygiene paydown). Closes the deferral
  trajectory cf-1 will inherit. After Sprint 11 + cf-1, the next sprint
  is expected to be UC-advancement (UC-002 Memory Search opening
  milestone or ISS-3 PA stop-token fix).
- **Use Case alignment**: indirect (zero UCs advanced this sprint, by
  design per the LA's process-hygiene-first sequencing). The dividend is
  cf-1 readiness + per-session context-budget improvement (DEC records
  reduce documentation lookup time) + Active State accuracy (procedure
  prevents stale baseline strings driving wrong agent assumptions).
- **ADR alignment**: no ADRs amended. ADR-007 (iGPU trust boundary),
  ADR-010 (PA on GPU), ADR-011 (GPU-only inference), ADR-012 (Qwen3-14B +
  speculative decoding + thinking) all unchanged. DEC-01..10 (Task 4
  production config) unchanged.
- **DEC alignment**: three new DECs (DEC-16, DEC-17, DEC-18) — all
  formalizing existing practice, no behavioral change. Existing DECs
  (DEC-11 v3 autonomy budget, DEC-12 peer-review lattice, DEC-13 fleet
  reports queue, DEC-14.5 trusted_scope merge with la_merge_approve,
  DEC-15 sprint lifecycle SDV/SCR/SWAGR) unchanged.
- **Use of `la_merge_approve.ps1`**: not expected for Sprint 11 EAs given
  their diff profile; DEC-18 itself formalizes the pattern that
  `la_merge_approve.ps1` is the operational answer to `trusted_scope`
  escalations (in case Sprint 11 surprises with a large EA-2 helper
  script, the escalation path is the standard one).

## 11. Roles and accountability

| Role | Responsibility this sprint | Budget |
|---|---|---|
| LA (Lead Architect) | SDV sign-off (concurrent with this kickoff per no-stopping directive), 0-2 expected `la_merge_approve` (Sprint 11 EAs profile small), cross-reference style call adjudication (EA-5), test-drift report read, SCR + SWAGR reads | ~20-30 min total |
| Co-Lead Architect | This kickoff session (Phase 0–5); SDO continuation XML authoring; per-EA peer review (Phase 1b prompt-staging APPROVED + Phase 2 merge-gate review); sprint-close SCR authoring; Active State refresh procedure invocation at SCR cadence (using EA-2 deliverable) | Autonomous per DEC-11 §1.1 |
| SDO (Strategic Development Orchestrator) | EA-1..EA-5 prompt authoring (5 prompts); per-EA Phase 1a comprehension review + Phase 1b completion review (10 reviews total) | Autonomous per DEC-11 §1.2 |
| EA Code | EA-1..EA-5 execution (5 firings) | Autonomous per DEC-11 §1.3 |
| Sprint Auditor | SWAGR independent production post-SCR (first run under amended §2.2 if EA-5 lands wake-template amendment before SWAGR firing) | Autonomous per DEC-15 §sprint_auditor_role_spec |

## 12. Estimated effort

- Rough duration: 2-4 fleet-days from fleet unpause to SCR (v2 amendment
  reduces estimate ~1 day vs original v1 prediction due to EA-1 + EA-2
  parallel window). Sprint 10 ran 2 calendar days end-to-end; Sprint 11
  has more EAs but each is smaller, AND EA-1 / EA-2 fire concurrently;
  net duration estimate slightly better than Sprint 10.
- LA active-time expectation: ~20-30 min total — 5-10 min SDV review
  (concurrent with this kickoff), 0-15 min cross-reference style call +
  any unexpected escalations, 5 min SCR read, 10 min SWAGR read.
- EA budget profile:
  - EA-1: 30-60 min (3 DECs to author from scratch with cross-references)
  - EA-2: 30-60 min (procedure + optional helper script + wake-template
    amendment)
  - EA-3: 15-30 min (template surgical edits)
  - EA-4: 60-120 min (real investigation — bisect or equivalent + per-test
    fail-closed verification + report writing)
  - EA-5: 30-60 min (cleanup batch across both repos)
- Total fleet wall-time: 2-4 days with the standard per-EA
  pause-comprehension-execute-review-merge cycle, **with EA-1 and EA-2
  sharing a single paused window** (parallel within-sprint authorization
  per v2 amendment §7); EA-3 / EA-4 / EA-5 then run sequentially per the
  original cadence.
- Confidence in estimate: **medium**. EA-4 carries the largest variance —
  if the drift cause is found quickly via marker inspection, it's a 30-min
  investigation; if it requires git-bisect across 50+ commits, it's
  multi-hour. The +20/-20 magnitude suggests a single conftest /
  pyproject.toml / marker config change, not 20 independent events;
  bisect should converge quickly.

## 13. Deliberate non-goals

1. **UC (Use Case) advancement** — Sprint 11 advances zero Use Cases by
   design. **Rejected because** the LA's sequencing decision is
   process-hygiene-first → cf-1 → UC. Sprint 11 prepares the substrate;
   UC advancement begins post-cf-1.

2. **Fleet code refactoring** — Sprint 11 is doc + governance + investigation,
   not code. **Rejected because** the only code touch is the optional EA-2
   helper script (additive new tool, no refactor) and an editorial fix to
   `tools/vikunja_mcp/README.md` (not code). Refactoring fleet code is
   cf-1's purpose.

3. **New gate label, new agent role, new sprint-lifecycle phase** —
   none invented. **Rejected because** Sprint 11 explicitly formalizes
   existing practice; inventing new scaffolding contradicts that goal.

4. **DEC-15 amendment** — DEC-15 sprint lifecycle unchanged. **Rejected
   because** the lifecycle's three-artifact (SDV/SCR/SWAGR) design is
   working; Sprint 11's SWAGR template amendment is purely additive
   (§5.4 cross-repo).

5. **Production source touches** — zero edits under `services/`, `shared/`,
   `launcher/`. **Rejected because** Sprint 11 is process-hygiene; any
   production touch surfaced by EA-4 becomes a Sprint 12 follow-up,
   not a Sprint 11 inclusion.

6. **`tools/vikunja_mcp/` migration to devplatform** — explicit non-goal
   per Sprint 10 §5.2 #8. **Rejected because** moving the MCP server
   requires rewiring three Claude surfaces (Desktop, Code, VS Code
   Copilot) and breaking sandbox-agent inbox/outbox paths. Out of scope.

7. **Vikunja project rationalization (UU #316)** — Stage 6.7.5 backlog.
   **Rejected because** it's orthogonal to Sprint 11's process-hygiene
   theme and benefits from being addressed as a focused project, not as
   a side-effect of a cleanup batch.

8. **Backfill SDVs for pre-DEC-15 sprints (Sprint 7)** — explicitly
   declined per LA standing direction (see Sprint 10 SDV §13 #2 for the
   same non-goal). **Rejected because** retroactive SDV authoring against
   long-completed work has poor signal-to-noise.

9. **Inventing a new DEC home directory structure beyond
   `docs/decisions/`** — EA-1 either uses an existing devplatform
   `docs/decisions/` (if present) or creates it. **Rejected because**
   inventing alternative hierarchies (e.g., per-domain DEC directories)
   without prior data on DEC volume is premature optimization.

10. **Automating Active State refresh as a scheduled task** — EA-2 ships
    a procedure + (optional) helper, NOT a scheduled cron / Task Scheduler
    job. **Rejected because** automation requires a separate design pass
    on trigger semantics (every commit? every sprint transition? every N
    minutes?), and the immediate need is procedure correctness, not
    automation. cf-1 may revisit.

## 14. Sign-off

### Lead Architect

> I, `blarai`, have reviewed this SDV on `2026-05-11`. I approve the
> sprint scope, success criteria, and risk posture as stated. I accept
> that the fleet will proceed autonomously per the DEC-11 budgets
> within these bounds. I will read the SCR and SWAGR when produced.

_(Signed via the frontmatter field `la_approved_on` above. A commit
authored by LA on main is the durable signature. LA-approval concurrent
with kickoff session per no-stopping directive — Phase 4 commit lands
with `la_approved_on` populated.)_

### Co-Lead Architect

> Co-Lead acknowledges the LA-signed SDV and will translate it into
> the first SDO continuation XML + milestone sequencing per the
> DEC-12 flow. Any scope deviation arising during execution will be
> flagged via the DEC-12 peer-review lattice or escalated via a CAR
> (Course-Adjustment Review).

_(Signed via the frontmatter field `co_lead_drafted_on` + git commit
by [agent:co_lead] that lands this SDV on main.)_

---

## Appendix A — SDV revision log

| Version | Date | Changed by | Change summary |
|---|---|---|---|
| 1 | 2026-05-11 | Co-Lead (kickoff session) | Initial draft; LA sign-off concurrent per no-stopping directive |
| 2 | 2026-05-11 | LA-directed (post-kickoff) | Authorize EA-1 + EA-2 parallel within-sprint execution; EA-3 / EA-4 / EA-5 remain serial. §7 sequencing rationale rewritten (parallel-window narrative + merge-queue choke-point note); §9.1 two new risk rows (parallel merge-queue contention + parallel devplatform-side race — both LOW-impact); §12 duration estimate reduced 3-5 days → 2-4 days. SDO authors EA-1 and EA-2 prompts before either fires |
| 3 | 2026-05-11 | LA-directed (overnight-handoff session, "mature not minimal — feel free to improve and iterate") | Upgrade EA-5 cross-reference style scope from "accept asymmetry, document choice" (v1/v2 default) to "symmetric expansion + formalize convention" — EA-5 now expands the 13 `<BlarAI>` template tokens in `devplatform\CLAUDE.md` to literal `C:\Users\mrbla\BlarAI` absolute paths AND authors `docs/decisions/DEC-19_cross-reference-style-convention_v1.md` on devplatform formalizing absolute-paths-everywhere as canonical (so cf-1 inherits the rule). Pre-amendment audit confirmed: devplatform `AGENTS.md` and `copilot-instructions.md` already use literal absolute paths (0 token matches each); only `CLAUDE.md` has the 13-token outlier. §4 success criterion #6 rewritten with concrete `grep` verification; §5.1 EA-5 sub-bullet rewritten with the 2 sub-deliverables; §5.3 EA-5 cross-reference style decision boundary rewritten; §6 deliverable summary row 11 split into 11 (DEC-19) + 11b (token expansion); §9.1 two new LOW/LOW risk rows for token-expansion-overlook + DEC-19-drift |
