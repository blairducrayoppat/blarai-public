---
ledger_id: 20260607_180000_sprint17_scr_boot-cluster-close
date: 2026-06-07
sprint_id: 17
entry_type: SCR
predecessor: Sprint-16 close ("The Automation Wave"; docs/ledger/ Sprint-16 entries)
branch: sprint17/* (7 stream branches + sprint17/swagr + sprint17/journal-fold + sprint17/close)
merge_commit: streams G1 19ded19 · G2 61f0daf · H-a 7034f9a · H-b 010bda6 · I bacd5f3 · J 475facd · K 873f5b5 · J-fix 22c2161 · SWAGR ed860c8 · fold efd93df
disposition: PARTIAL
---

# Ledger — Sprint 17 "The Boot Cluster" close

## Summary

Penultimate wave toward the #598 air-gap-removal gate. Sprint 17 made the **real
production boot path exist** (#615 guest↔host AF_HYPERV boundary, activated with a
clean host-mode fallback), **built the ADR-027 egress machinery dormant** (the
air-gap stayed welded), and **locked the burned boot/posture seams with automation**
so the gate becomes a scripted audit. Seven worktree builders ran concurrently
against disjoint working sets and merged serially under the Orchestrator-held
merge-gate; the standing gate moved **2212 → 2340 on the dev box (+128 net new
tests; host-independent invariant 0 failed / 108 deselected / 2342 selected),
green at every merge, zero regressions.** Independent opus Auditor SWAGR returned
**STRONG_ALIGNMENT, 0 CRITICAL / 0 MAJOR / 5 MINOR** and reproduced the gate clean.

**Disposition PARTIAL:** the *buildable* scope (C1–C6) is COMPLETE + gate-green +
independently verified; the hardware tiers (C1 real-VM, C2 model-loaded, C4
real-TPM, **C7 FUT-04 ceremony + flip**, C8 Sprint-16 baseline) are BUILT + SCRIPTED
and PENDING their first green run in the one batched LA on-chip session
(committed ≠ done until green). #106/FUT-04 stays PARTIAL until C7. #628 stays open
until the on-chip green runs + the LA's close confirmation.

## Criteria outcomes (SDV §4)

- **C1 #615 guest boundary** — MET (gate tier). AF_HYPERV addressing fix +
  dormant-path activation + topology flip w/ clean host fallback. Real-VM
  round-trip `@hardware` → on-chip. (`19ded19`)
- **C2 full production-mode boot integration** — MET (gate tier). Composed prod
  cascade (cert→AO→mTLS handshake→preflight→teardown) green w/ stand-in material +
  GPU stub. Model-loaded tier `@hardware` → on-chip / Sprint-18. (`61f0daf`)
- **C3 ADR-027 egress machinery** — MET, shipped **DORMANT** (allowlist-widening +
  auto-trip + PA carve-out + exfil screen + locks). Live allowlist stays
  loopback+vsock; air-gap unchanged; enforces post-#556. Split seam verified live
  (detection → `trip()`). (`7034f9a` H-a interface anchor, `010bda6` H-b)
- **C4 security-cascade integration (GAP-7)** — MET (stand-in tier). Real-TPM tier
  `@hardware` (reported green on the reference TPM; unverified in-tree). (`bacd5f3`)
- **C5 production-posture runtime guard (GAP-12/#600)** — MET (gate tier). Runtime
  `dev_mode=False` assertion executes; fixed to assert by invariant. (`475facd` + `22c2161`)
- **C6 offline key-recovery (§5.5)** — MET. Fresh-environment (dead-chip) recovery
  decrypts real at-rest data via the offline recovery key. (`873f5b5`)
- **C7 #106/FUT-04 close** — PENDING (on-chip ceremony + flip + boot).
- **C8 Sprint-16 deferred baseline** — PENDING (on-chip, FIRST: boot-smoke #6(ii) + GUI #621).
- **C9 close hygiene** — DONE (this entry): gate 2340 green; SCR + SWAGR + fold + §5
  reconcile + doctrine sweep + ledger landed.

## Deliverables

- 7 stream merges (above) under the serial merge-gate; 8 journal fragments folded
  into `BUILD_JOURNAL.md` (lessons 73–81); SCR
  (`docs/sprints/sprint_17/strategic_completion_report.md`); independent Auditor
  SWAGR (`docs/sprints/sprint_17/Strategic_Work_Analysis_and_Gap_Report_Sprint_17_20260607_173220.md`);
  SECURITY_ROADMAP §5 gate-tracker reconciled; CLAUDE.md Phase-History refreshed.

## Quality gate

Standing gate (`shared/ services/ launcher/ tests/integration/ tests/security/ -m
"not hardware and not winui and not slow"`): **2340 passed / 2 skipped / 108
deselected / 0 failed** on the dev box (2320/22 in a clean worktree — `models/`-
presence split; invariant 0 failed / 2342 selected). Re-run by the Orchestrator at
every merge; independently reproduced by the Auditor.

## SWAGR dispositions (5 MINOR — all doc-precision or pre-existing carries)

- MINOR-1 (SCR gate count host-specific) — FIXED (SCR states the invariant).
- MINOR-2 (C4 unverified TPM side-claim) — FIXED (SCR wording softened).
- MINOR-3 (ledger after SWAGR, by design) — this entry (DEC-17).
- MINOR-4 (SECURITY_ROADMAP "#787" conceptual naming, ≡#598) — CARRIED (LA naming
  call on the governance file; off-ramp offered).
- MINOR-5 (#626 `tools/tests/` 4 collection errors) — CARRIED to #626 (out-of-scope).

## Carry-forwards (→ Sprint 18 / on-chip)

- The batched LA **on-chip session**: C8 baseline (FIRST) → C1 #615 real-VM boot →
  C7 FUT-04 ceremony + flip; opportunistic C2 model-loaded + C4 real-TPM.
- Sprint-18 pre-gate: production-posture SWAGR sweep + GAP-5/6/8/9 model-loaded
  automation → the **#612 Capstone phase (gate-phase 6, §5.13)** → the **#598
  §5.12 sign-off (phase 7)**. The air-gap stays UP throughout.
- #607 audit retention (LA decision); MINOR-4 (#787); #626; the dependency
  hash-pinning lockfile; the ~33-worktree state-hygiene cleanup.

## Decisions of record

- ADR-027 (egress) + ADR-028 (attestation) honored — no re-litigation, egress
  dormant, zero PCR measured-boot built; DECISION_REGISTER updated in-step (prior).
- The H-split seam connects by **registration** (no circular import); the carve-out
  lives where the rule fires (`gpu_inference.py` RULE 3), not where its name said.
- Gate-honesty: a posture/security test must own the outcome it asserts on, not
  borrow it from the host's provisioning state (the J seam; BUILD_JOURNAL lesson 81).
