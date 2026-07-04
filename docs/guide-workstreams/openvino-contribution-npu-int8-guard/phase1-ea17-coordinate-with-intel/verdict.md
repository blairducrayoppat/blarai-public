# Phase 1 verdict — Guide-#11 cross-verification

**Workstream**: openvino-contribution-npu-int8-guard
**Phase**: 1
**EA**: EA-17
**Verdict author**: Guide-#11
**Date**: 2026-05-12

## Verdict: **PASS_WITH_NOTES**

Concurs with EA-17's self-verdict. All four phase deliverables produced;
all preflight checks executed; fleet pause/resume bracketing landed on
devplatform/main; content commit landed on the correct BlarAI feature
branch; no GitHub posts; no runtime-code edits.

The "with notes" status is driven by four anomalies (A-NEW1 through A-NEW4)
all classified correctly by EA-17. Each anomaly's disposition is recorded
below and in workstream STATUS.md §E2.

## What was independently checked

Verified on disk, not from EA-17's narrative:

| Check | Method | Result |
|---|---|---|
| Pause-fleet commit exists on devplatform/main | `git -C devplatform log --oneline -8 main` | PASS — `c58261a [agent:ea17] chore: pause fleet -- EA-17 phase1 openvino-35641 engagement work` present |
| Content commit exists on BlarAI feature branch | `git -C BlarAI log --oneline -5 feature/p-openvino-35641-phase1-engagement` | PASS — `7702dba [agent:ea17] phase1: openvino-35641 engagement artifacts` present |
| Content commit diff stats match close report | `git -C BlarAI show --stat 7702dba` | PASS — 4 files changed, 889 insertions, all four artifact paths under `phase1-ea17-coordinate-with-intel/` |
| Resume-fleet commit exists on devplatform/main | (same git log as pause) | PASS — `4bc274e [agent:ea17] chore: resume fleet -- EA-17 phase1 engagement work complete` present |
| Fleet state shows resumed | `cat devplatform/tools/autonomy_budget/state.json` | PASS — `fleet_paused: false`, `last_updated_by: "ea_17"`, `last_updated_utc: "2026-05-12T15:30:56Z"` |
| All four artifacts on disk with non-zero size | `Test-Path` + `Get-Item .Length` on each | PASS — engagement-comment-draft.md (5657 B), cla-and-ai-policy-brief.md (10517 B), upstream-state-report.md (14395 B), close-report.md (15398 B) |
| Engagement comment draft is 150-250 words and pastes cleanly | Read engagement-comment-draft.md lines 22-55 | PASS — 243 words; cites PR #34651 with URL; offers three options + invites fourth; @-mentions @Zulkifli-Intel only; AI Assistance block present; no commendations; no code; neutral opener |
| Engagement comment does NOT cite #34450 as resolution precedent | Engagement-comment text scan | PASS — citation absent per dispatch §execution/T1 MUST-NOT clause (correct given preflight 0f outcome) |

## Anomaly dispositions

### A-NEW1 — fleet-hygiene.md §R7 path defect

**Description**: Both this Phase 1 dispatch's preflight 0a and
`devplatform/docs/governance/fleet-hygiene.md` §R7's example invocation
reference `C:/Users/mrbla/BlarAI/tools/autonomy_budget/state.json` as
the path to `state.pause_fleet(...)`. The canonical state file actually
lives at `C:/Users/mrbla/devplatform/tools/autonomy_budget/state.json`
(per `devplatform/tools/autonomy_budget/state.py` `DEFAULT_STATE_PATH`).
EA-17 correctly detected this and used the canonical path; the pause
and resume commits both landed cleanly on devplatform/main as a result.

**Root cause**: this Phase 1 dispatch inherited the wrong path verbatim
from fleet-hygiene.md §R7. The §R7 path is stale — likely a Stage 6.7.5
artifact (platform separation moved tools/autonomy_budget/ from BlarAI
to devplatform but the §R7 example was not updated).

**Disposition**: **Bound to Vikunja ticket in DevPlatform-Meta (project 10)** — created 2026-05-12 as part of this verdict. Title: "Fix fleet-hygiene.md §R7 state.json path: BlarAI → devplatform". Documentation label.

### A-NEW2 — pre-existing devplatform working-tree drift

**Description**: When EA-17 ran preflight 0b on devplatform, the working
tree had pre-existing uncommitted drift on `.mcp.json`, three wake-task
xmls, two flag files, and state.json (timestamp-only). EA-17 explicitly
staged only `tools/autonomy_budget/state.json` for the pause commit; the
other drift remained uncommitted across both pause and resume.

**Root cause**: this drift pattern is catalogued in
`devplatform/docs/governance/fleet-hygiene.md` §1 ("Drift catalogue") —
the `.mcp.json` and flag files are gitignored / runtime-mutated; the
wake-task xmls and state.json are tracked but mutated by fleet operations.

**Disposition**: **No new ticket.** This is the known drift class. Surfaced
to LA for awareness. If the drift persists across multiple sessions
without LA intervention, the existing fleet-hygiene followup queue covers
it (Pattern C / "commit-or-alert" deferred per Vikunja Infrastructure
ticket #240).

### A-NEW3 — PR #34651 last-activity delta

**Description**: Phase 1 dispatch §B2 claimed PR #34651's last activity
was 2026-04-16. EA-17's live re-fetch on 2026-05-12 showed last activity
2026-04-24 (force-push / merge commit). 8-day delta.

**Root cause**: dispatch was authored from a WebFetch summary that
captured the author-ping but missed a subsequent force-push or rebase
landing. WebFetch's GitHub summarization is shallow.

**Disposition**: **Informational only.** The engagement comment does
not cite the specific date — citation is the URL only. No engagement
correctness impact. The state report (`upstream-state-report.md` §1)
records the correct 2026-04-24 date.

### A-NEW4 — charter §5 #34532 drift

**Description**: Workstream charter §5 listed `openvino#34532` as
"open, triaged" in the linked-tickets section. EA-17's live state check
showed #34532 is **closed** (last activity 2026-03-06).

**Root cause**: charter authoring used a March-2026 mental model of
project state (when #34532 was active per the March contribution plan).
#34532 closed in early March; charter authored 2026-05-12 didn't
re-verify against live state.

**Disposition**: **Fixed inline.** Guide-#11 amended charter §5 in this
verdict turn to: `openvino#34532 (closed, last activity 2026-03-06 —
corrected from initial "triaged" claim per EA-17 Phase 1 anomaly A-NEW4)`.
The charter edit is in the same commit as this verdict.

## Discrepancies between close report and observed state

None. EA-17's close report claims align with disk state, git state,
fleet state, and Vikunja state across all spot-checks performed.

The only minor variance — the close report §8 commit-SHA table marked
the content and resume SHAs as "pending — appended when commit completes".
EA-17's final-response section "E. Commit SHAs" already populated those
(`7702dba` and `4bc274e` respectively), and both are present in the git
log. Treated as cosmetic — the close report's intent is clearly
documented and the authoritative SHAs are also on disk.

## Hardening followups bound

| # | Ticket | Project | Title | Source |
|---|---|---|---|---|
| 1 | (Vikunja, created in this verdict turn) | 10 (DevPlatform-Meta) | Fix fleet-hygiene.md §R7 state.json path: BlarAI → devplatform | A-NEW1 |
| 2 | (Vikunja, created in this verdict turn) | 4 (BlarAI Infrastructure) | Verify openvino#34450 closure mechanism + Intel response (or absence) | EA-17 close report §6, item 3 |

Fence-post #11-vs-#12 days in dispatch §B1 (EA-17 close report §6 item 4):
**Not bound to a ticket** — the dispatch is a frozen Phase 1 artifact, and
the "11 days since filed" was true at dispatch authoring on 2026-05-12.
The "12 days" temporal-drift observation is informational, not a defect.

## Forward-looking notes

1. **Phase 2 is blocked on substantive Intel response to the engagement
   comment** (once posted) or on the workstream's 2026-07-01 deferral
   window passing. Phase 2 is NOT a Guide-action item until that gate
   opens.
2. **Phase 2 dispatch authoring**, when triggered, must include:
   - Live build-from-source toolchain preflight (Visual Studio 2022,
     CMake, Python, OpenCL + Level Zero runtimes for NPU plugin tests).
   - Branch strategy conditional on Intel's chosen contribution shape
     (extend PR #34651 vs. separate companion PR vs. fourth option).
   - Disk-space + wall-clock expectations for initial submodule init +
     cmake configure (30+ min wall-clock per EA-17 forward-looking note).
3. **Strategic context for Phase 2 planning**: PR #34651's stall is a
   reviewer-pool issue (NPU-plugin team) not an author-blocked one
   (npu_compiler reviewers DID engage same author on PRs #265 + #266 on
   2026-04-17). Phase 2 planning should treat PR #34651's merge-readiness
   as a separate, parallel concern rather than a blocker.

## Closing

Phase 1 work product is solid. The engagement comment is well-targeted
and respects every dispatch constraint. The four artifacts taken together
give the LA a complete posting kit (the comment text, the CLA + AI Usage
compliance brief, the state report, and the close report).

**LA's next action**: review `engagement-comment-draft.md` and, on
approval, post via GitHub webUI to
[issue #35641](https://github.com/openvinotoolkit/openvino/issues/35641).
After posting, record the comment URL in workstream STATUS.md §E2 (or
ask Guide-#11 to).

The workstream stays `Active`. Phase 2 dispatch authoring is paused
until Intel responds or the deferral window opens.
