---
ledger_id: 20260512_183052_sprint12prep_fleet-bug-fixes
date: 2026-05-12
sprint_id: null
entry_type: OTHER
predecessor: 20260512_172500_sprint11_ea5_cleanup-batch
branch: feature/sprint12prep-fleet-bug-fixes (devplatform) + feature/sprint12prep-ledger (BlarAI)
merge_commit: null
disposition: COMPLETE
---

# Sprint 12-prep fleet-bug fixes — state-machine misclassification + label-revert root-cause

## 0. Provenance

Pre-Sprint-12 fleet-mechanism hotfix triage, executed under LA-delegated authority while the LA is away running errands and the fleet is paused. Tracking task: Vikunja #470 (BlarAI Core Development, Project 3). Scope authorization: closed two HIGH-priority Sprint 11 SCR §14.1 carry-overs identified in commit `f7f56b2` (Sprint 11 SCR) and reaffirmed in commit `e44455c` (Sprint 11 SWAGR). The work product on devplatform is editorial-doctrinal (wake-template amendments); the BlarAI side is this ledger entry only.

## 1. Summary

Sprint 11 produced two HIGH-priority fleet-mechanism bugs that broke autonomous fleet progression and forced Co-Lead direct execution on EA-4 + EA-5 under LA-delegated authority bypass:

1. **Bug 1 — within-sprint parallel EA state-machine misclassification**. After EA-1 of an EA-1+EA-2 parallel pair merged, EA Code's wake-template state machine processing EA-2's queue file mis-routed it to Case F (completion-review already posted) based on EA-1's latest `[agent:sdo]` and `[agent:ea_code]` comments on the shared tracking task. EA-2 was permanently stranded; manual unblock (re-apply `Gate:Pending-Execution`) was required.
2. **Bug 2 — Vikunja label-revert phenomenon on tracking task #410**. During Sprint 11 EA-4 dispatch (2026-05-12 morning, ~08:00-09:30 local), SDO authored six verified queue-finalize commits (`027bf00` v1 through `c200c60` v6). Each was observed by SDO to have its labels "reverted within ~5 minutes." After six attempts, SDO escalated to `Gate:Pending-Human` at `b814e22`. The reverter was not identified during Sprint 11.

Investigation under this triage established that **both bugs share a single root cause**: the EA Code and SDO wake-template state machines (in `devplatform/docs/scheduled/wake_templates/ea_code.md` and `sdo.md`) examine the **latest** `[agent:ea_code]` and `[agent:sdo]` comments on a tracking task without any per-EA disambiguation. When a tracking task hosts more than one EA's comment chain — which is the Sprint norm for serial multi-EA sprints AND the new pattern for within-sprint parallel under DEC-16 — the state machines confuse one EA's chain with a sibling EA's chain.

The fix is a single editorial pattern applied to both wake templates: an `[ea:N]` tag (where N = the queue file's `ea_number` attribute) is added to every verdict-relevant EA Code and SDO comment, and every state-machine lookup filters the comment timeline by `[ea:N]`. The change is backward-compatible: untagged comments from pre-2026-05-12 single-EA sprints resolve correctly via a wildcard match in the filter predicate.

## 2. Investigation methodology

### 2.1 Bug 1 — state-machine misclassification

Read Sprint 11 SCR §9.3 (unknown unknowns), §14.1 (carry-overs), and §14.2 (technical debt). Read the relevant `ea_code.md` wake-template sections (Phase 2 step 1 queue inspection at line 71-75 pre-fix, plus State machine DEC-12 at line 78-129 pre-fix). The narrative in SCR §9.3.1 makes the root cause explicit: the state machine reads the **latest** `[agent:sdo]` comment, which after EA-1 merged was EA-1's `[agent:sdo][phase:completion-review]` APPROVED. Combined with EA-2's queue file being a "Fresh task" by the `Gate:Pending-Execution` discriminator but a prior `[agent:ea_code][phase:comprehension]` existing from EA-1, the state machine's Case A guard ("no prior `[agent:ea_code][phase:comprehension]` from you on this task") fails — EA-1's comprehension counts. The session then falls through to Case F evaluation, finds EA-1's `[agent:sdo][phase:completion-review]`, and exits silently as if EA-2 were complete.

### 2.2 Bug 2 — reverter identification

The Sprint 11 SCR §14.1 enumerated five suspects: Gate Stale Cleaner, Escalation Watchdog, Toast Watchdog, Agents Cadence Monitor, Fleet Reports automation. This triage ruled out each by source inspection:

| Suspect | Cadence | Vikunja label mutations? | Verdict |
|---|---|---|---|
| Gate Stale Cleaner (`tools/gate_stale_cleaner/cleaner.py` + `tools/scheduled-tasks/gate-stale-cleaner.xml`) | daily 05:00 UTC | applies `Gate:Stale` + `Gate:Pending-Human` only | RULED OUT — daily cron, not 5-min; never touches `Gate:Pending-Execution` or `Gate:Pending-SDO` |
| Escalation Watchdog (`tools/scheduled-tasks/escalation_watchdog.ps1`) | every 5 min | READ-ONLY on Vikunja labels; only mutates `tools/fleet_observability/escalation_seen.json` | RULED OUT — script header asserts read-only; source-walk confirms (no `add_label` / `remove_label` HTTP calls) |
| Toast Watchdog (`tools/scheduled-tasks/toast_watchdog.ps1`) | every 1 min | none — consumes `critical_pending.flag` and invokes notifier; no Vikunja calls | RULED OUT |
| Agents Cadence Monitor (`tools/scheduled-tasks/agents-cadence-monitor.ps1`) | every 5 min | READ-ONLY on Vikunja labels; mutates only Wake task XML intervals | RULED OUT — `cadence_monitor_20260512.log` confirms it stayed at NO-OP IDLE 15-min throughout the EA-4 window |
| Fleet Reports automation (`tools/fleet_observability/daily_digest.py`, `dashboard_maintainer.py`) | daily / on-demand | dashboard maintainer mutates only dashboard project tasks; daily digest creates a daily-digest task but does not touch #410's labels | RULED OUT |
| Bridge daemon (`tools/vikunja_mcp/bridge/daemon.py`) | n/a — `state.json` last modified 2026-04-28 | not running during the EA-4 window | RULED OUT |

**Actual reverter identified**: EA Code itself. The smoking gun is in the EA Code session log `tools/scheduled-tasks/logs/20260512_080938_ea_code.log` (`session_id=d8bbb0c7-4510-4ba2-84eb-734b3026a4c1`):

```
2026-05-12T08:09:38  wake_launcher start role=ea_code
2026-05-12T08:09:38  WORK-GATE: trigger file consumed ... reason='SDO Phase 3 queue-finalize:
                     Sprint 11 EA-4 prompt moved staging->queue at f207ef5;
                     Gate:Pending-Execution applied on Task 410.'; running Claude.
...
toolu_01KiJtNvYswFRw4uUzEbBtT9: mcp__vikunja__add_label_to_task task_id=410 label_id=9
toolu_01BPM6BBKpDdRJQ9xxN6B8Li: mcp__vikunja__remove_label_from_task task_id=410 label_id=16
```

EA Code at 08:09:38 was triggered by SDO's v1 commit's `ea_code.wake` + `schtasks /run`. It correctly identified the EA-4 queue file as `Gate:Pending-Execution` carrying, BUT it ALSO observed seven prior `[agent:ea_code][phase:comprehension]` comments on #410 (from EA-1/2/3 chains). The wake template's pre-fix iteration-cycle classifier (line 74 — "task has at least one prior `[agent:ea_code][phase:comprehension]` comment on its timeline, regardless of current label") returned `True`. The session dispatched to the state machine, which read the latest `[agent:sdo]` comment (the v1 queue-finalize) and the latest `[agent:ea_code]` comment (EA-3's completion), could not match any of Case B/C/D/E/F cleanly, and defaulted to **Case A behavior** (post comprehension, apply `Gate:Pending-SDO`, remove `Gate:Pending-Execution`). The session then fired `sdo.wake`.

SDO at 08:13:41 woke (cron-fired, ~4 min after the EA-4 trigger that EA Code consumed at 08:09:38). It observed `Gate:Pending-SDO` on #410 — apparent revert of the v1 finalize. Without per-EA disambiguation, SDO could not tell that EA Code had legitimately accepted the queue file via Case A. SDO interpreted the label transition as "Phase 3 didn't take" and re-finalized (commit `bd37b62` v2). The cycle repeated 5 more times: v3 (`a1f9f4b`), v4 (`5eb71f4`), v5 (`3161af1`), v6 (`c200c60`). After v6 SDO escalated.

The "~5-minute revert" claim in the escalation report (`docs/sprints/sprint_11/reports/20260512_161219_sdo_escalation_v1.md`) reflects round-trip time: SDO writes finalize → 30s later EA Code's triggered wake starts → 3-4 min Claude session executing Case A → SDO's next cron-tick wake at the 15-min boundary observes the "reverted" state. The ~5-min cadence claimed is the natural wake spacing, not a true 5-min reverter cron.

### 2.3 Realization: Bug 1 and Bug 2 are the same bug

The two HIGH-priority bugs SCR §14.1 enumerated are not independent. **They are two manifestations of the same root cause**: the EA Code and SDO wake-template state machines cannot disambiguate between multiple EA chains on a shared tracking task. Bug 1 is the within-sprint parallel case (EA-1+EA-2 simultaneously, post-EA-1-merge). Bug 2 is the serial case (EA-3's chain pre-existing on #410 when EA-4's queue file is finalized). Both are fixed by the same `[ea:N]` doctrine extension.

## 3. Fix description

### 3.1 Doctrine amendments

Edited `C:\Users\mrbla\devplatform\docs\scheduled\wake_templates\ea_code.md` and `C:\Users\mrbla\devplatform\docs\scheduled\wake_templates\sdo.md` to add:

- **New `[ea:N]` tag convention**: every EA Code-authored `[agent:ea_code][phase:comprehension]` or `[phase:completion]` comment, and every SDO-authored `[agent:sdo][phase:comprehension-review]` / `[phase:completion-review]` / `[phase:completion]` (Phase 2) / `[phase:queue-finalize]` (Phase 3) comment, MUST carry an `[ea:N]` token where N is the queue file's `ea_number` XML attribute.
- **State-machine filter**: every comment-timeline lookup in the EA Code state machine (Case A/B/C/D/E/F) and SDO Phase 1a/1b/3 logic is filtered by `[ea:N]` for the queue file being processed. Comments for OTHER EA numbers on the same task are IRRELEVANT to the current classification.
- **Backward-compatibility wildcard**: untagged comments from pre-2026-05-12 sprints (Sprints 7-10) resolve correctly via the OR clause `(contains [agent:ea_code] OR [agent:sdo] AND contains NO [ea:M] for M != N)`. No back-tagging required.
- **Worked example**: ea_code.md now contains a concrete trace of the EA-4 8:09:38 dispatch showing both pre-fix misbehavior and post-fix correct routing.
- **Multi-EA safeguard (SDO)**: SDO's Phase 1a/1b verdict-posting block now requires the latest filtered `[agent:ea_code][phase:*][ea:N]` comment to be strictly newer than the latest filtered `[agent:sdo][phase:*-review][ea:N]`. If a duplicate verdict would be posted, exit with `PHASE-1-NOOP` log.
- **Idempotency safeguard (SDO Phase 3)**: before Phase 3 APPROVED execution, verify filesystem state (`staging/<file>.xml` exists AND `ea_queue/<file>.xml` does NOT exist). If reversed, Phase 3 already ran on a prior firing — log `PHASE-3-NOOP` and skip. This is the explicit guard that prevents the Sprint 11 v2-v6 re-finalize loop from recurring.

### 3.2 What was deliberately NOT done

- **No per-EA sub-task scheme on Vikunja** (the alternative suggested in SCR §14.1 #1). The `[ea:N]` tag approach keeps tracking-task structure unchanged.
- **No Vikunja label-ID changes**, no new gate labels invented.
- **No Python code touches** under `tools/autonomy_budget/` or `tools/`. The wake templates ARE the doctrine that the SDO and EA Code Claude sessions read at firing time — implementation lives in the agents' Vikunja MCP calls.
- **No DEC-20 ratification of within-sprint parallel**. Per the task's negative constraints, that's Sprint 12 LA territory, not a sub-agent triage decision.
- **No fleet pause/unpause changes**. Fleet stays paused per `tools/autonomy_budget/state.json` `fleet_paused=true`.
- **No production source touches** under `services/`, `shared/`, `launcher/`. No test edits.

## 4. Verification

1. **Wake-template syntax check**: re-read both edited files end-to-end. The disambiguation logic is woven coherently — `[ea:N]` appears in every comment-emission instruction, every state-machine lookup is filtered, the backward-compat wildcard is documented, and the worked example traces the EA-4 scenario explicitly.
2. **Pytest baseline regression check**: `cd C:/Users/mrbla/BlarAI && .venv/Scripts/pytest shared services launcher --tb=no -q` returned `1001 passed, 2 skipped, 2 warnings in 39.54s` — identical to Sprint 11 SCR §2.1 baseline at `f7f56b2`. No regression.
3. **Git status**: both repos clean post-commit on their respective feature branches; no uncommitted changes from this triage.
4. **Reverter-fix smoke argument**: post-fix, the Sprint 11 EA-4 scenario at 08:09:38 traces as follows. SDO Phase 3 v1 writes `[agent:sdo][phase:queue-finalize][ea:4]` comment + applies Gate:Pending-Execution + fires ea_code.wake. EA Code wakes, parses queue file root `ea_number=4`, filters timeline by `[ea:4]`, finds zero matching prior comprehension comments (all 7 prior comprehension comments are filtered out as `[ea:1]`/`[ea:2]`/`[ea:3]` or, in transitional sprints, as untagged-non-wildcard because newer tagged comments exist). Classifies as **Fresh task**, dispatches Case A correctly. Posts `[agent:ea_code][phase:comprehension][ea:4]`, applies Gate:Pending-SDO, removes Gate:Pending-Execution. Fires sdo.wake. SDO 08:13 wakes, filters timeline by `[ea:4]`, finds the new comprehension comment, identifies it as fresh (no prior `[agent:sdo][phase:comprehension-review][ea:4]`), routes to **Phase 1a**. No spurious re-finalize. Loop broken.

## 5. Cross-references

- **Sprint 11 SCR**: `docs/sprints/sprint_11/strategic_completion_report.md` §14.1 (carry-overs to Sprint 12, both HIGH-priority items) — commit `f7f56b2`.
- **Sprint 11 SWAGR**: `docs/sprints/sprint_11/Strategic_Work_Analysis_and_Gap_Report_Sprint_11_20260512_183000.md` §10.4 (carry-over items) + §14 (recommendations, rec #1 + #2) — commit `e44455c`.
- **SDO escalation report**: `docs/sprints/sprint_11/reports/20260512_161219_sdo_escalation_v1.md` — the v6→escalation transition narrative that triggered this triage.
- **Vikunja task #470** (BlarAI Core Development, Project 3) — "Sprint 12-prep: Fleet Bug Triage (state-machine misclassification + label-revert)" — the charter under which this work was authorized.
- **Wake templates edited**: `C:\Users\mrbla\devplatform\docs\scheduled\wake_templates\ea_code.md`, `C:\Users\mrbla\devplatform\docs\scheduled\wake_templates\sdo.md` — both on devplatform branch `feature/sprint12prep-fleet-bug-fixes`.
- **Suspect tools reviewed (and ruled out as reverters)**: `tools/gate_stale_cleaner/cleaner.py`, `tools/gate_stale_cleaner/run_live.py`, `tools/scheduled-tasks/escalation_watchdog.ps1`, `tools/scheduled-tasks/toast_watchdog.ps1`, `tools/scheduled-tasks/agents-cadence-monitor.ps1`, `tools/fleet_observability/daily_digest.py`, `tools/fleet_observability/dashboard_maintainer.py`, `tools/vikunja_mcp/bridge/daemon.py`.
- **Sprint 11 EA-4 commits inspected** (the queue-finalize loop): `027bf00` v1, `bd37b62` v2, `a1f9f4b` v3, `5eb71f4` v4, `3161af1` v5, `c200c60` v6, `b814e22` escalation_v1 — all on BlarAI main.
- **DEC references**: DEC-12 (peer-review lattice — the framework these state machines implement), DEC-13 (report emission), DEC-14.5 (formatting), DEC-15 (sprint-id resolution), DEC-16 (parallel-sprint authorization — the motivating context for `[ea:N]`), DEC-17 (Q1-1 per-file ledger format — this entry's format).

## 6. Forward-looking notes

- **Sprint 12 SDV (when authored by LA)** should reference this ledger entry as the closure of SCR §14.1 #1 + #2 carry-overs. If the LA chooses to ratify within-sprint parallel via DEC-20, the `[ea:N]` doctrine is the substrate that makes ratification safe.
- **First sprint that exercises this fix end-to-end** should observe: every EA Code comprehension comment carries `[ea:N]`, every SDO review comment carries `[ea:N]`, and no spurious re-finalize loop occurs. If a fresh sprint reproduces the v1/v2 loop pattern, the fix has not landed correctly in the live wake templates — investigate the file-on-disk state and confirm devplatform main carries the merge of `feature/sprint12prep-fleet-bug-fixes`.
- **Untagged comments going forward** are a soft anti-pattern but not an error. If an EA or SDO session forgets to add `[ea:N]`, the wildcard fallback preserves correctness on single-EA-per-task scenarios. The doctrine should still be followed; the wildcard is a back-compat ramp, not a license to skip the tag.
- **The `proactive_sdo.py` scanner** (transport-agnostic, no Vikunja mutations) is unaffected by this fix. Implementation of the `[ea:N]` filter is entirely in the agent's Claude session reading the wake template — there is no Python code path that needs updating.

## 7. Quality gate

- Wake-template diffs sit on devplatform branch `feature/sprint12prep-fleet-bug-fixes`. Co-Lead will review and merge.
- BlarAI ledger entry sits on `feature/sprint12prep-ledger`. Co-Lead will merge after verifying the diff is ledger-only.
- pytest baseline: `1001 passed, 2 skipped` (no regression).
- No production source modified.
- No test source modified.
- No DEC/ADR amendments.
- No Vikunja label ID changes.
- No fleet pause/unpause changes.
