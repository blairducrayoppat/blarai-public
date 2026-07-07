---
ledger_id: 20260605_203743_sprint13_scr_tier1-finishers
date: 2026-06-05
sprint_id: 13
entry_type: SCR
predecessor: 20260605_061513_sprint12_scr_provenance-intent
branch: null
merge_commit: aa41a0e
disposition: COMPLETE
---

# Sprint 13 close — Tier-1 security finishers

## Summary

The air-gap-removal campaign's **first fleet wave**: the three no-ceremony Tier-1 finishers,
built by three disjoint worktree-isolated builder subagents (model sonnet) in parallel, with
the Orchestrator holding the merge gate (agents never merged to `main`, never touched
`BUILD_JOURNAL.md`). Each closes a verified 2026-06-03 audit finding. Full SCR:
`docs/sprints/sprint_13/strategic_completion_report.md`. SDV signed under LA-delegated authority
(autonomy grant 2026-06-05).

## Deliverables

- **#601 EA-1 — PII credit-card Luhn fix** (audit Domain 5): `CREDIT_CARD` now gated on a real
  mod-10 checksum in both detection paths; `pii_mode` unchanged (`off`, DEC-05). Merge `d910739`.
- **#602 EA-2 — tamper-evident audit stream** (audit Domain 7): hash-chained append-only
  Policy-Agent decision log, pluggable signer (HMAC stub; TPM swap = LA ceremony), now ACTIVE in
  the live PA. Merge `a8284d1` (2 rounds: `17adf05` sink + `42b3e56` the merge-gate live-wiring
  catch).
- **#603 EA-3 — dev-mode interlock + loud opt-in** (audit Domain 1/2/6, Decision 8): fail-closed
  `dev_mode ∧ network_facing` refuse + loud INSECURE banner; running-default NOT flipped
  (Tier-2-cert-gated). Merge `ea879ed`.

## Merge-gate catch (the portfolio highlight)

EA-2 round 1 built a correct, 38-test-green tamper-evident sink and DI-wired it into the
adjudicator — but the production PA factory constructed the adjudicator **without** the sink, so
the live PA persisted zero records: the audit's own "built but wired into nothing" anti-pattern
recurring inside the sprint built to close it, hidden by a fully green suite. Caught by reading
the production construction site; round 2 activated it + added a `has_audit_log` regression lock.
BUILD_JOURNAL lessons **46** (mechanism-tested ≠ live-invoked) + **47** (comment-claimed,
code-unenforced = governance debt).

## Quality gate

`pytest shared services launcher tests/integration tests/harness -m "not hardware and not winui
and not slow"` = **1883 passed, 0 failed, 98 deselected** on integrated `main` (kickoff baseline
1797). `test_launcher.py` 19/19 incl. `test_production_happy_path` (EA-3's `#588` failure is
model-less-worktree-only). main HEAD `aa41a0e`. SDV criteria **5/5 MET**.

## Carry-overs

TPM signer swap for the audit stream (Tier-2 ceremony, LA); dev-mode running-default flip
(`dev_mode=false`, Tier-2-cert-gated + LA live-verify); audit-stream retention/rotation
(`on_rotate` stub, Sprint 14); audit-stream **tail-deletion** limitation (chain misses newest-record
truncation — needs external count attestation); measured-boot attestation (4th Tier-1 item,
ceremony-bound). Production-posture live-verify + the TPM ceremony are the LA's batched Tier-2
steps. #598 remains the go/no-go. Sprint Auditor SWAGR follows.
