---
ledger_id: 20260605_061513_sprint12_scr_provenance-intent
date: 2026-06-04
sprint_id: 12
entry_type: SCR
predecessor: 20260604_184221_iss1-spec-decode-closure
branch: null
merge_commit: 90b2bed
disposition: COMPLETE
---

# Sprint 12 close — Provenance- and intent-aware content handling

## Summary

Shipped a per-chunk **provenance trust model** (`TRUSTED_LOCAL` / `TRUSTED_MEMORY` /
`UNTRUSTED_EXTERNAL`) and, mid-sprint, a ratified **capability-scoped redesign** of the
action-lock — both live-verified on the real system in the same session. Direct
execution under LA-delegated authority (Q3-B); all increments on `main`, each journaled.
Full SCR: `docs/sprints/sprint_12/strategic_completion_report.md`.

## Deliverables

- **ADR-023** (provenance-based trust model) + **Amendment 1** (capability-scoped
  locking: tool risk tiers; `SAFE` never locked; `DANGEROUS` denied absolutely, no
  `/trust` override). Both ratified 2026-06-04; DECISION_REGISTER updated.
- **#582** provenance foundation · **#584** secure-by-default gate (untrusted-only) ·
  **#579** Stage-5 leakage false-positive fixed · **#570** AO→PA tool-dispatch
  mediation (P-004 enforced at the AO loop) · **#583** `/external` interim untrusted
  channel · **#585** fresh-attachment referent fix · **#591** capability-scoped
  locking.
- Three bugs surfaced by the live screen, fixed in-session (leakage detector reverted-
  then-redesigned, EA-7 referent, EA-6a WinUI-command fall-through).

## Files changed (principal)

`services/assistant_orchestrator/src/{context_manager,entrypoint,tools}.py`,
`services/assistant_orchestrator/src/pgov.py` (leakage), `shared/ipc/protocol.py`
(`external_documents`), `services/ui_gateway/src/transport.py` (`/external`),
`services/ui_winui/MainWindow.xaml.cs` (command fall-through),
`docs/adrs/ADR-023-Provenance-Based-Trust-Model.md` (+ Amendment 1),
`docs/DECISION_REGISTER.md`, tests across `services/assistant_orchestrator/tests/` and
`services/ui_gateway/tests/`.

## Quality gate

`pytest services shared launcher tests` = **1661 passed, 2 skipped, 0 failed**.
LA live-verified the user-facing surface (leakage fix, tools+#570, lock fires,
referent fix, SAFE-not-locked). main HEAD `90b2bed`.

## Carry-overs (Sprint 13)

EA-6 proper (WinUI workspace-folder + mark-external UI, #583); #590 (sign the tool
manifest); LA-gated branch-hygiene pass (193 local branches); §5.4 DANGEROUS-tier lock
posture when the first dangerous tool lands. None blocking. Sprint Auditor SWAGR
follows.
