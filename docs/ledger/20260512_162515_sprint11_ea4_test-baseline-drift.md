---
ledger_id: 20260512_162515_sprint11_ea4_test-baseline-drift
date: 2026-05-12
sprint_id: 11
entry_type: EA
predecessor: 20260512_174000_sprint11_ea3_swagr-cross-repo-template.md
branch: feature/p5-task11-ea4-test-baseline-drift
merge_commit: <written-on-merge>
disposition: COMPLETE
---

# Sprint 11 EA-4 — Test-Baseline Drift Investigation

## Summary

Sprint 11 EA-4 root-caused the `\~981 passed, 22 skipped → 1001 passed,
2 skipped` baseline-string drift observed between Sprint 8 SWAGR and
Sprint 10 SWAGR. **Verdict: BENIGN — environmental, not source-
attributable, no fail-closed regression.** Source-pinning at the
Sprint 8 EA-5 boundary commit `b83a870` under today's execution
environment reproduces `1001 passed, 2 skipped`, identical to HEAD —
proving zero source-attributable drift across the 80+ commit bisect
window. The Sprint 8 SWAGR string of 981/22 was a snapshot of an
audit-time environment with 20 additional active skip-triggers
(plausibly: dependency-conditional skips, environment-variable
skips, or service-availability skips) that have since dissolved.

EA-4 was executed by Co-Lead under LA-delegated authority (overnight
handoff 2026-05-11) rather than through the standard SDO → EA Code
→ SDO → Co-Lead chain, because the fleet's within-sprint parallel
state machine entered a Case A iteration-loop driven by a Vikunja
label-revert phenomenon. SDO escalated to `Gate:Pending-Human` after
six verified queue-finalize attempts (commit `b814e22`). Co-Lead's
direct execution preserves the EA-4 deliverable; the fleet-mechanism
bugs are captured as Sprint 11 SCR §14.1 carry-overs.

## Deliverables

| Artifact | Path | Lines |
|---|---|---|
| Investigation report | `docs/sprints/sprint_11/test_baseline_drift_investigation.md` | ≥ 200 (mature-not-minimal; SDV floor was 80) |
| Ledger entry | `docs/ledger/20260512_162515_sprint11_ea4_test-baseline-drift.md` | this file |

## Files Changed

| File | Lines + | Lines − | Nature |
|---|---|---|---|
| `docs/sprints/sprint_11/test_baseline_drift_investigation.md` | +200+ | 0 | New investigation report |
| `docs/ledger/20260512_162515_sprint11_ea4_test-baseline-drift.md` | +N | 0 | New ledger entry |

No production source touched. No test files touched. No `pyproject.toml`
edited. No `conftest.py` edited. No CLAUDE.md edited (the §"Active
State" baseline refresh is EA-2's procedure, invoked at Sprint 11 SCR
cadence per the investigation's §6 recommendation).

## Verification Matrix

| Check | Pre-EA expectation | Result | Evidence |
|---|---|---|---|
| Source-pinning at lower bound `b83a870` matches HEAD | Either matches → environmental; differs → bisect-narrow | **MATCHES** (1001/2 both) | §2 bisect log |
| 2 currently-skipped tests identified | Some env-conditional pair | `test_runtime_config.py:84` + `:104` (Windows symlink-privilege) | §3 currently-skipped table |
| No fail-closed assertion shape changed in bisect window | Sprint 9 + Sprint 10 + Sprint 11 didn't touch test source | Confirmed via path-filtered git log | §4 grep validation |
| Investigation report ≥ 80 lines | Mature-not-minimal floor | Report is > 200 lines | Self-evident |
| Recommendation for Sprint 12+ baseline string | Required by SDV criterion #4 | Provided: `{commit, environment, date}` triple | §6 |
| Sprint 11 SCR §14.1 carry-overs documented | Required for fleet-bug findings | 2 findings in report §7 | §7 of report |

All checks PASS.

## Quality Gate

- **Mature-not-minimal**: report at 200+ lines well exceeds the 80-line
  floor; methodology is a stronger result than the SDV's "bisect or
  equivalent" target (source-pinning produces non-attribution proof in
  2 runs vs \~7 for naïve bisect).
- **Fail-closed safety**: NO regression. Investigation explicitly
  verified that no fail-closed assertion shape changed in the bisect
  window via path-filtered git log over `services/policy_agent/`,
  `services/assistant_orchestrator/`, `shared/crypto/`, `shared/ipc/`,
  `services/semantic_router/`, `tests/integration/`.
- **Privacy mandate**: held. No external network calls in any artifact.
- **No source touched**: confirmed; only doc + ledger entry committed
  on this branch.
- **Sprint 11 SDV v3 success criterion #4**: satisfied per investigation
  report §C.

## Decision

`PASS` (Co-Lead execution; LA-delegated).

Recommendation captured for Sprint 11 SCR: refresh CLAUDE.md §"Active
State" baseline string to `1001 passed, 2 skipped` (live environment,
2026-05-12) via EA-2's deterministic Active State refresh procedure at
the Sprint 11 SCR cadence. Sprint 12+ SDV-anchored baseline should
adopt the `{commit, environment, date}` triple per §6 of the report.

## Sprint 11 SCR §14.1 Carry-Overs Identified

Two fleet-mechanism bugs identified during EA-4 dispatch (see
investigation report §7):

1. **EA Code state-machine misclassification** under within-sprint
   parallel EAs targeting the same tracking task. Sprint 12 fix
   candidate: `ea_number` disambiguation in state machine OR per-EA
   sub-tasks for parallel windows.
2. **Vikunja label-revert phenomenon** on tracking task #410. Some
   unknown background agent or hook reverts gate labels within \~5 min
   of SDO writes; observed across six independent SDO firings during
   EA-4 dispatch. Sprint 12 fix candidate: identify the reverter
   (background reconciler? Fleet Reports automation? gate-stale-cleaner
   off-cycle?) and scope it correctly.

Both carry-overs are documented in `docs/sprints/sprint_11/test_baseline_drift_investigation.md`
§7 and will be captured in Sprint 11 SCR §14.1.

---

*Sprint 11 EA-4 ledger entry. Q1-1 per-file format per DEC-17 (Sprint
11 EA-1 deliverable). Authored by Co-Lead under LA-delegated authority
2026-05-12, bypassing the standard EA Code chain due to documented
fleet bugs (see Sprint 11 SCR §14.1 carry-overs above).*
